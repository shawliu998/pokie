"""Server-owned workspace fixtures and durable Quant result projections.

The selector is process configuration used by local development/E2E only.  It
is never accepted from an HTTP request and is never rendered as a UI control.
Fixture values remain synthetic demonstration records. Durable runs project
their pinned daily or timestamped market-bar runtime without provider, broker,
network, or arbitrary code execution during snapshot construction.
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from datetime import date
from typing import Any

from sqlalchemy import select

from packages.contracts.enums import DataAuthenticity
from packages.contracts.quant import (
    QuantEvidenceReplanDecision,
    QuantLearningTrace,
    QuantResearchDecision,
    QuantRobustnessSensitivity,
)
from packages.contracts.quant.data import QuantDailyBarDataset
from packages.contracts.quant.enums import QuantArtifactKind
from packages.contracts.quant.fixture_data import SPY_DAILY_FIXTURE
from packages.contracts.quant.schemas import QuantWorkspaceTradeProjection
from packages.domain.canonical import canonical_digest
from packages.domain.quant_backtest import (
    BacktestBar,
    BacktestCadence,
    DailyBar,
    MarketBar,
    backtest_buy_and_hold,
)
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context
from services.api.app.modules.quant.execution import BASELINE_EXECUTION
from services.api.app.modules.quant.kernel_check import (
    build_quant_kernel_capability,
    build_quant_kernel_check,
    build_quant_research_projection,
)

FIXTURE_ENV = "POKIEQUANT_E2E_RUN_STATE"
DEFAULT_FIXTURE = "quant-ready"
FIXTURE_STATES = frozenset(
    {
        "quant-ready",
        "quant-plan-approval",
        "quant-loading-data",
        "quant-generating-candidates",
        "quant-running",
        "quant-repairing",
        "quant-validating",
        "quant-generating-report",
        "quant-waiting-review",
        "quant-completed",
        "quant-no-viable-candidate",
        "quant-failed-safe",
        "quant-cancelled",
    }
)


def _state_config(name: str) -> tuple[str, str, list[str], str]:
    return {
        "quant-ready": ("draft", "scope", ["generate_plan"], "Scope is ready for planning."),
        "quant-plan-approval": (
            "waiting_plan_approval",
            "scope",
            ["approve_plan", "request_plan_changes", "cancel_run"],
            "The synthetic plan is waiting for approval.",
        ),
        "quant-loading-data": (
            "loading_data",
            "dataset",
            [],
            "The pinned dataset is being verified.",
        ),
        "quant-generating-candidates": (
            "generating_candidates",
            "candidates",
            [],
            "Bounded candidate specifications are being prepared.",
        ),
        "quant-running": (
            "running_experiments",
            "experiments",
            ["run_fixture", "cancel_run"],
            "The approved synthetic Agent is ready to run.",
        ),
        "quant-repairing": (
            "repairing",
            "repair",
            ["cancel_run"],
            "Candidate B is in a bounded fixture repair.",
        ),
        "quant-validating": (
            "validating",
            "validation",
            ["cancel_run"],
            "Fixture robustness validation is active.",
        ),
        "quant-generating-report": (
            "generating_report",
            "report",
            [],
            "Retained evidence is being assembled into the report.",
        ),
        "quant-waiting-review": (
            "waiting_for_review",
            "decision",
            ["complete_review"],
            "The fixture report is waiting for review.",
        ),
        "quant-completed": ("completed", "decision", [], "Research process completed."),
        "quant-no-viable-candidate": (
            "completed",
            "decision",
            [],
            "No candidate passed validation.",
        ),
        "quant-failed-safe": (
            "failed",
            "experiments",
            ["retry_run"],
            "The fixture worker stopped safely.",
        ),
        "quant-cancelled": (
            "cancelled",
            "experiments",
            ["retry_run"],
            "The fixture run was cancelled.",
        ),
    }[name]


def artifact_type_for_kind(kind: str) -> str:
    if kind == "plan":
        return "execution_log"
    if kind == "research_scope":
        return "research_scope"
    if kind == "dataset_snapshot":
        return "dataset_snapshot"
    if kind == "benchmark":
        return "backtest_result"
    if kind == "strategy_spec":
        return "strategy_spec"
    if kind == "backtest_result":
        return "backtest_result"
    if kind == "backtest_metrics":
        return "backtest_result"
    if kind == "equity_curve":
        return "equity_curve"
    if kind == "trade_log":
        return "trade_log"
    if kind == "validation_report":
        return "validation_report"
    if kind == "robustness_sensitivity":
        return "validation_report"
    if kind == "research_report":
        return "research_report"
    if kind == "execution_log":
        return "execution_log"
    if kind == "diagnostics":
        return "execution_log"
    raise ValueError(f"Unsupported artifact kind: {kind}")


def _payload_refs_internal_artifacts(payload: dict[str, Any], internal_ids: set[str]) -> bool:
    artifact_id = payload.get("artifact_id")
    if artifact_id is not None and str(artifact_id) in internal_ids:
        return True
    artifact_ids = payload.get("artifact_ids")
    return isinstance(artifact_ids, list) and any(
        str(item) in internal_ids for item in artifact_ids
    )


ACTIVE_RESEARCH_STATES = {
    "loading_data",
    "generating_candidates",
    "running_experiments",
    "repairing",
    "validating",
    "generating_report",
}

LIVE_PHASE_COPY = {
    "loading_data": (
        "Loading research data",
        "Generate candidate specifications after the dataset is ready.",
    ),
    "generating_candidates": (
        "Generating candidates",
        "Run the first prepared candidate against the training range.",
    ),
    "running_experiments": (
        "Running experiments",
        "Continue the candidate queue, then compare completed results.",
    ),
    "repairing": (
        "Repairing candidate",
        "Backtest the revised candidate when its parameters are ready.",
    ),
    "validating": (
        "Validating results",
        "Apply walk-forward checks and the sealed holdout review.",
    ),
    "generating_report": (
        "Building report",
        "Publish the comparison and limitations for review.",
    ),
}


def _fixture_live_research(state: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if state not in ACTIVE_RESEARCH_STATES:
        return None

    hypotheses = {
        "candidate-a": "Test a faster moving-average trend signal against buy and hold.",
        "candidate-b": "Test a slower moving-average trend signal for lower drawdown.",
        "candidate-c": "Test whether a long-horizon breakout remains robust with sparse trades.",
    }

    def row(
        candidate: dict[str, Any], ordinal: int, status: str, *, metrics: bool
    ) -> dict[str, Any]:
        return {
            "id": candidate["id"],
            "ordinal": ordinal,
            "name": candidate["name"],
            "hypothesis": hypotheses[candidate["id"]],
            "parameters": candidate["parameters"],
            "state": status,
            "repairCount": 1 if status == "repairing" else 0,
            "metrics": candidate["metrics"] if metrics else None,
        }

    rows: list[dict[str, Any]] = []
    current = None
    latest = None
    if state == "generating_candidates":
        current = row(candidates[0], 1, "queued", metrics=False)
        rows = [current]
    elif state == "running_experiments":
        latest = row(candidates[0], 1, "completed", metrics=True)
        current = row(candidates[1], 2, "running", metrics=False)
        rows = [latest, current]
    elif state == "repairing":
        latest = row(candidates[0], 1, "completed", metrics=True)
        current = row(candidates[1], 2, "repairing", metrics=False)
        rows = [latest, current]
    elif state in {"validating", "generating_report"}:
        rows = [
            row(candidate, index + 1, "completed", metrics=True)
            for index, candidate in enumerate(candidates)
        ]
        latest = rows[-1]

    phase_label, next_step = LIVE_PHASE_COPY[state]
    iterations = {
        "loading_data": 0,
        "generating_candidates": 1,
        "running_experiments": 2,
        "repairing": 3,
        "validating": 4,
        "generating_report": 5,
    }
    return {
        "phase": state,
        "phaseLabel": phase_label,
        "iteration": iterations[state],
        "currentExperiment": current,
        "latestResult": latest,
        "candidates": [{**item, "canSeedResearch": False} for item in rows],
        "nextStep": next_step,
    }


def _plan(current_step: str, state: str) -> list[dict[str, Any]]:
    rows = (
        ("scope", "Define research scope", "user", True),
        ("dataset", "Load market dataset", "system", False),
        ("benchmark", "Build benchmark", "system", False),
        ("candidates", "Generate candidates", "agent", False),
        ("experiments", "Run experiments", "agent", False),
        ("repair", "Repair recoverable failures", "agent", False),
        ("validation", "Validate robustness", "validator", False),
        ("comparison", "Compare candidates", "agent", False),
        ("report", "Generate report", "agent", False),
        ("decision", "Human decision", "user", True),
    )
    keys = [row[0] for row in rows]
    current = keys.index(current_step)
    result: list[dict[str, Any]] = []
    for index, (key, title, owner, human_gate) in enumerate(rows):
        if state == "completed":
            status = "completed"
        elif state == "failed":
            status = "completed" if index < current else "failed" if index == current else "pending"
        elif state == "cancelled":
            status = "completed" if index < current else "skipped"
        elif index < current:
            status = "completed"
        elif index > current:
            status = "pending"
        elif state.startswith("waiting_"):
            status = "waiting"
        else:
            status = "active"
        result.append(
            {
                "id": key,
                "title": title,
                "description": f"Synthetic fixture step: {title.lower()}.",
                "owner": owner,
                "status": status,
                "artifactCount": 1 if status == "completed" else 0,
                "humanGate": human_gate,
            }
        )
    return result


def reset_workspace_fixtures() -> None:
    # Tests reset the database schema. Durable state must not be hidden behind
    # a process-local reset hook.
    return None


def _chart_sample(
    dataset: QuantDailyBarDataset,
    trades: list[dict[str, Any]],
    retained_trades: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return a bounded chart projection while retaining computed trade markers."""

    last_index = len(dataset.bars) - 1
    indices = {round(position * last_index / 23) for position in range(24)}
    marker_by_date: dict[str, str] = {}
    for trade in trades:
        marker_by_date[trade["entryDate"]] = "entry"
        marker_by_date[trade["exitDate"]] = "exit"
    retained_dates = {
        trade[date_key]
        for trade in retained_trades or trades
        for date_key in ("entryDate", "exitDate")
    }
    indices.update(
        index
        for index, bar in enumerate(dataset.bars)
        if bar.trading_date.isoformat() in retained_dates
    )
    return [
        {
            "date": dataset.bars[index].trading_date.isoformat(),
            "open": float(dataset.bars[index].open),
            "high": float(dataset.bars[index].high),
            "low": float(dataset.bars[index].low),
            "close": float(dataset.bars[index].close),
            "volume": dataset.bars[index].volume,
            **(
                {"marker": marker_by_date[dataset.bars[index].trading_date.isoformat()]}
                if dataset.bars[index].trading_date.isoformat() in marker_by_date
                else {}
            ),
        }
        for index in sorted(indices)
    ]


def _market_chart_sample(
    bars: tuple[BacktestBar, ...],
    trades: list[dict[str, Any]],
    retained_trades: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return timestamp-preserving chart rows from one validated market runtime."""

    market_bars = tuple(bar for bar in bars if isinstance(bar, MarketBar))
    if len(market_bars) != len(bars):
        raise ValueError("A market chart projection requires only timestamped MarketBar rows.")
    last_index = len(market_bars) - 1
    indices = {round(position * last_index / 23) for position in range(24)}
    marker_by_timestamp: dict[str, str] = {}
    for trade in trades:
        marker_by_timestamp[trade["entryDate"]] = "entry"
        marker_by_timestamp[trade["exitDate"]] = "exit"
    retained_timestamps = {
        trade[date_key]
        for trade in retained_trades or trades
        for date_key in ("entryDate", "exitDate")
    }
    indices.update(
        index
        for index, bar in enumerate(market_bars)
        if bar.timestamp.isoformat() in retained_timestamps
    )
    return [
        {
            "date": market_bars[index].timestamp.isoformat(),
            "open": market_bars[index].open,
            "high": market_bars[index].high,
            "low": market_bars[index].low,
            "close": market_bars[index].close,
            "volume": market_bars[index].volume,
            **(
                {"marker": marker_by_timestamp[market_bars[index].timestamp.isoformat()]}
                if market_bars[index].timestamp.isoformat() in marker_by_timestamp
                else {}
            ),
        }
        for index in sorted(indices)
    ]


def _normalized_performance_points(raw_points: object, *, limit: int = 160) -> list[dict[str, Any]]:
    """Normalize retained equity artifacts into a bounded chart contract."""

    if not isinstance(raw_points, list):
        return []
    valid = [
        item
        for item in raw_points
        if isinstance(item, dict)
        and isinstance(item.get("date"), str)
        and isinstance(item.get("equity"), (int, float))
    ]
    if not valid:
        return []
    step = max(1, (len(valid) + limit - 1) // limit)
    sampled = valid[::step]
    if sampled[-1] is not valid[-1]:
        sampled.append(valid[-1])
    base = float(sampled[0]["equity"]) or 1.0
    peak = 100.0
    points: list[dict[str, Any]] = []
    for item in sampled:
        equity = float(item["equity"]) / base * 100
        peak = max(peak, equity)
        points.append(
            {
                "date": item["date"],
                "equity": round(equity, 4),
                "drawdown": round((equity / peak - 1) * 100, 4),
            }
        )
    return points


def _benchmark_performance_points(dataset: QuantDailyBarDataset) -> list[dict[str, Any]]:
    split_index = max(1, min(len(dataset.bars) * 80 // 100, len(dataset.bars) - 1))
    bars = tuple(
        DailyBar(
            date=bar.trading_date,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in dataset.bars[:split_index]
    )
    result = backtest_buy_and_hold(bars, BASELINE_EXECUTION)
    return _normalized_performance_points(
        [{"date": point.date.isoformat(), "equity": point.equity} for point in result.equity_curve]
    )


def _market_benchmark_performance_points(
    bars: tuple[BacktestBar, ...], cadence: BacktestCadence
) -> list[dict[str, Any]]:
    """Project a benchmark from the same timestamped training partition as candidates."""

    result = backtest_buy_and_hold(
        bars,
        BASELINE_EXECUTION,
        cadence=cadence,
    )
    return _normalized_performance_points(
        [
            {
                "date": (
                    point.timestamp.isoformat()
                    if point.timestamp is not None
                    else point.date.isoformat()
                ),
                "equity": point.equity,
            }
            for point in result.equity_curve
        ]
    )


def _report_metrics_projection(value: object) -> dict[str, float | int] | None:
    if not isinstance(value, dict):
        return None
    return {
        "annualizedReturn": float(value.get("annualized_return_pct", 0)),
        "maxDrawdown": float(value.get("maximum_drawdown_pct", 0)),
        "sharpe": float(value.get("sharpe_ratio", 0)),
        "trades": int(value.get("trade_count", 0)),
    }


def _robustness_sensitivity_projection(
    contract: QuantRobustnessSensitivity,
) -> dict[str, Any]:
    """Project contract fields while preserving canonical strategy parameter keys."""

    def metrics(value: Any) -> dict[str, float | int]:
        return {
            "totalReturnPct": value.total_return_pct,
            "annualizedReturnPct": value.annualized_return_pct,
            "maximumDrawdownPct": value.maximum_drawdown_pct,
            "sharpeRatio": value.sharpe_ratio,
            "tradeCount": value.trade_count,
            "winRatePct": value.win_rate_pct,
            "finalEquity": value.final_equity,
        }

    return {
        "schemaVersion": contract.schema_version,
        "evaluationPartition": contract.evaluation_partition,
        "runId": contract.run_id,
        "reportArtifactId": contract.report_artifact_id,
        "candidate": {
            "candidateId": contract.candidate.candidate_id,
            "template": contract.candidate.template,
            "parameters": dict(contract.candidate.parameters),
            "canonicalKey": contract.candidate.canonical_key,
        },
        "finalTrainingComparison": {
            "artifactId": contract.final_training_comparison.artifact_id,
            "artifactDigest": contract.final_training_comparison.artifact_digest,
        },
        "dataset": {
            "datasetId": contract.dataset.dataset_id,
            "datasetDigest": contract.dataset.dataset_digest,
        },
        "interval": contract.interval,
        "periodsPerYear": contract.periods_per_year,
        "runtimeDescriptorDigest": contract.runtime_descriptor_digest,
        "trainingSplit": {
            "identityKind": contract.training_split.identity_kind,
            "ruleVersion": contract.training_split.rule_version,
            "trainingBarCount": contract.training_split.training_bar_count,
            "trainingStart": contract.training_split.training_start,
            "trainingEnd": contract.training_split.training_end,
            "trainingSplitDigest": contract.training_split.training_split_digest,
            "sealedSplitDigest": contract.training_split.sealed_split_digest,
        },
        "executionRuleVersion": contract.execution_rule_version,
        "samplerRuleVersion": contract.sampler_rule_version,
        "costScenarios": [
            {
                "scenario": item.scenario,
                "multiplier": item.multiplier,
                "feeRate": item.fee_rate,
                "slippageRate": item.slippage_rate,
                "candidateMetrics": metrics(item.candidate_metrics),
                "benchmarkMetrics": metrics(item.benchmark_metrics),
            }
            for item in contract.cost_scenarios
        ],
        "parameterNeighbors": [
            {
                "parameterName": item.parameter_name,
                "direction": item.direction,
                "parameters": dict(item.parameters),
                "canonicalKey": item.canonical_key,
                "candidateMetrics": metrics(item.candidate_metrics),
            }
            for item in contract.parameter_neighbors
        ],
        "kernelCallCount": contract.kernel_call_count,
    }


def _generalization_projection(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    split = value.get("split")
    if not isinstance(split, dict):
        return None

    def partition(name: str) -> dict[str, Any] | None:
        row = value.get(name)
        if not isinstance(row, dict):
            return None
        candidate = _report_metrics_projection(row.get("candidate"))
        benchmark = _report_metrics_projection(row.get("benchmark"))
        if candidate is None or benchmark is None:
            return None
        return {"candidate": candidate, "benchmark": benchmark}

    split_projection: dict[str, Any] = {
        "method": split.get("method", "chronological"),
        "ruleVersion": split.get("rule_version", ""),
        "trainBarCount": split.get("train_bar_count", 0),
        "holdoutBarCount": split.get("holdout_bar_count", 0),
        "cutoffDate": split.get("cutoff_date", ""),
        "datasetId": split.get("dataset_id", ""),
        "datasetDigest": split.get("dataset_digest", ""),
    }
    if "interval" in split:
        split_projection.update(
            {
                "interval": split.get("interval"),
                "periodsPerYear": split.get("periods_per_year"),
                "cutoffTimestampUtc": split.get("cutoff_timestamp_utc"),
                "rangeStartUtc": split.get("range_start_utc"),
                "rangeEndUtc": split.get("range_end_utc"),
                "descriptorDigest": split.get("descriptor_digest"),
                "sealDigest": split.get("seal_digest"),
            }
        )
    return {
        "status": value.get("status", "not_evaluated"),
        "reason": value.get("reason", "Holdout evaluation was not available."),
        "selectedCandidateId": value.get("selected_candidate_id"),
        "split": split_projection,
        "train": partition("train"),
        "holdout": partition("holdout"),
    }


def _walk_forward_projection(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    folds = value.get("folds")
    aggregate = value.get("aggregate")
    if not isinstance(folds, list) or not isinstance(aggregate, dict):
        return None

    def metrics(item: object) -> dict[str, float | int] | None:
        return _report_metrics_projection(item)

    projected_folds: list[dict[str, Any]] = []
    for fold in folds:
        if not isinstance(fold, dict):
            continue
        candidate = metrics(fold.get("candidate"))
        benchmark = metrics(fold.get("benchmark"))
        if candidate is None or benchmark is None:
            continue
        projected_folds.append(
            {
                "foldIndex": fold.get("fold_index", 0),
                "historyStart": fold.get("history_start", ""),
                "historyEnd": fold.get("history_end", ""),
                "evaluationStart": fold.get("evaluation_start", ""),
                "evaluationEnd": fold.get("evaluation_end", ""),
                "marketRegime": {
                    "label": fold.get("market_regime", {}).get("label", "")
                    if isinstance(fold.get("market_regime"), dict)
                    else "",
                    "trend": fold.get("market_regime", {}).get("trend", "")
                    if isinstance(fold.get("market_regime"), dict)
                    else "",
                    "volatility": fold.get("market_regime", {}).get("volatility", "")
                    if isinstance(fold.get("market_regime"), dict)
                    else "",
                    "historyStart": fold.get("market_regime", {}).get("history_start", "")
                    if isinstance(fold.get("market_regime"), dict)
                    else "",
                    "historyEnd": fold.get("market_regime", {}).get("history_end", "")
                    if isinstance(fold.get("market_regime"), dict)
                    else "",
                    "historyBarCount": int(
                        fold.get("market_regime", {}).get("history_bar_count", 0)
                    )
                    if isinstance(fold.get("market_regime"), dict)
                    else 0,
                    "trailingReturn": float(
                        fold.get("market_regime", {}).get("trailing_return_pct", 0)
                    )
                    if isinstance(fold.get("market_regime"), dict)
                    else 0.0,
                    "annualizedVolatility": float(
                        fold.get("market_regime", {}).get("annualized_volatility_pct", 0)
                    )
                    if isinstance(fold.get("market_regime"), dict)
                    else 0.0,
                },
                "candidate": candidate,
                "benchmark": benchmark,
                "status": fold.get("status", "not_evaluated"),
            }
        )
    aggregate_projection = {
        "evaluatedFolds": int(aggregate.get("evaluated_folds", 0)),
        "candidatePositiveReturnFolds": int(aggregate.get("candidate_positive_return_folds", 0)),
        "candidateLowerDrawdownFolds": int(aggregate.get("candidate_lower_drawdown_folds", 0)),
        "candidateMedianReturn": float(aggregate.get("candidate_median_return_pct", 0)),
        "benchmarkMedianReturn": float(aggregate.get("benchmark_median_return_pct", 0)),
        "candidateMedianDrawdown": float(aggregate.get("candidate_median_drawdown_pct", 0)),
        "benchmarkMedianDrawdown": float(aggregate.get("benchmark_median_drawdown_pct", 0)),
        "candidateMedianSharpe": float(aggregate.get("candidate_median_sharpe_ratio", 0)),
        "benchmarkMedianSharpe": float(aggregate.get("benchmark_median_sharpe_ratio", 0)),
        "distinctMarketRegimes": int(aggregate.get("distinct_market_regimes", 0)),
        "regimeDiversityStatus": aggregate.get(
            "regime_diversity_status", "insufficient_regime_diversity"
        ),
        "byMarketRegime": [
            {
                "label": row.get("label", ""),
                "foldCount": int(row.get("fold_count", 0)),
                "candidateMedianReturn": float(row.get("candidate_median_return_pct", 0)),
                "benchmarkMedianReturn": float(row.get("benchmark_median_return_pct", 0)),
                "candidateMedianDrawdown": float(row.get("candidate_median_drawdown_pct", 0)),
                "benchmarkMedianDrawdown": float(row.get("benchmark_median_drawdown_pct", 0)),
                "candidateMedianSharpe": float(row.get("candidate_median_sharpe_ratio", 0)),
                "benchmarkMedianSharpe": float(row.get("benchmark_median_sharpe_ratio", 0)),
            }
            for row in aggregate.get("by_market_regime", [])
            if isinstance(row, dict)
        ],
    }
    return {
        "method": value.get("method", "expanding"),
        "ruleVersion": value.get("rule_version", ""),
        "evaluationPartition": value.get("evaluation_partition", "train"),
        "foldCount": int(value.get("fold_count", 0)),
        "windowBarCount": int(value.get("window_bar_count", 0)),
        "stateRuleVersion": value.get("state_rule_version", ""),
        "stateLookbackBars": int(value.get("state_lookback_bars", 0)),
        "status": value.get("status", "not_evaluated"),
        "reason": value.get("reason", "Walk-forward evaluation was not available."),
        "folds": projected_folds,
        "aggregate": aggregate_projection,
    }


def _dataset_quality_projection(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    issues = value.get("issues")
    notes = value.get("notes")
    if not isinstance(issues, list) or not isinstance(notes, list):
        return None
    return {
        "schemaVersion": value.get("schema_version", ""),
        "policyVersion": value.get("policy_version", ""),
        "status": value.get("status", "warning"),
        "verificationStatus": value.get("verification_status", "checked"),
        "reportDigest": value.get("report_digest", ""),
        "datasetDigest": value.get("dataset_digest", ""),
        "barCount": int(value.get("bar_count", 0)),
        "calendarGapCount": int(value.get("calendar_gap_count", 0)),
        "largestCalendarGapDays": int(value.get("largest_calendar_gap_days", 0)),
        "unexpectedSessionCount": int(value.get("unexpected_session_count", 0)),
        "zeroVolumeBarCount": int(value.get("zero_volume_bar_count", 0)),
        "priceJumpCount": int(value.get("price_jump_count", 0)),
        "issues": [dict(item) for item in issues if isinstance(item, dict)],
        "notes": [str(item) for item in notes],
    }


def _project_replan_repair(
    artifacts: list[Any],
    event_rows: list[dict[str, Any]],
    candidate_id: str,
) -> dict[str, Any] | None:
    """Project one validator-proven create_candidate action-only replan repair.

    Fail closed: only a single matching learning trace produces the bounded
    public shape; anything ambiguous or missing omits the field.
    """

    def _strip_replan_action(value: object) -> object:
        if not isinstance(value, dict):
            return value
        result: dict[str, Any] = {}
        for key, val in value.items():
            if key == "replan_decision" and isinstance(val, dict):
                result[key] = {k: v for k, v in val.items() if k != "action"}
            else:
                result[key] = _strip_replan_action(val)
        return result

    try:
        traces = [
            QuantLearningTrace.model_validate(item.content)
            for item in artifacts
            if item.kind is QuantArtifactKind.LEARNING_TRACE
        ]
    except ValueError:
        return None

    events_by_id = {str(item["event_id"]): item for item in event_rows}

    def _matches(trace: QuantLearningTrace) -> bool:
        if trace.outcome != "resolved":
            return False
        if trace.tool.action.value != "create_candidate":
            return False
        if len(trace.violations) != 1 or len(trace.correction_delta) != 1:
            return False
        violation = trace.violations[0]
        if (
            violation.path != "replan_decision.action"
            or violation.code != "invalid_value"
            or violation.required_change != "replace"
        ):
            return False
        delta = trace.correction_delta[0]
        if delta.path != "replan_decision.action" or delta.change != "replace":
            return False
        if trace.correction_started_event is None:
            return False
        failed = events_by_id.get(str(trace.failed_event.event_id))
        corrected_started = events_by_id.get(str(trace.correction_started_event.event_id))
        outcome = events_by_id.get(str(trace.outcome_event.event_id))
        if not failed or not corrected_started or not outcome:
            return False
        if (
            failed["sequence"] != trace.failed_event.sequence
            or corrected_started["sequence"] != trace.correction_started_event.sequence
            or outcome["sequence"] != trace.outcome_event.sequence
        ):
            return False
        failed_payload = failed.get("payload")
        corrected_started_payload = corrected_started.get("payload")
        outcome_payload = outcome.get("payload")
        if (
            failed["event_type"] != "tool.failed"
            or not isinstance(failed_payload, dict)
            or failed_payload.get("error_code") != "INVALID_ARGUMENTS"
            or failed_payload.get("action") != "create_candidate"
        ):
            return False
        rejected_started = next(
            (
                item
                for item in event_rows
                if item["sequence"] == failed["sequence"] - 1
                and item["event_type"] == "tool.started"
            ),
            None,
        )
        if rejected_started is None:
            return False
        if (
            corrected_started["event_type"] != "tool.started"
            or not isinstance(corrected_started_payload, dict)
            or corrected_started_payload.get("action") != "create_candidate"
        ):
            return False
        if (
            outcome["event_type"] != "tool.completed"
            or not isinstance(outcome_payload, dict)
            or outcome_payload.get("action") != "create_candidate"
            or outcome_payload.get("success") is not True
            or outcome_payload.get("candidate_id") != candidate_id
        ):
            return False
        rejected_started_payload = rejected_started.get("payload")
        if not isinstance(rejected_started_payload, dict):
            return False
        rejected_args = rejected_started_payload.get("arguments")
        corrected_args = corrected_started_payload.get("arguments")
        if not isinstance(rejected_args, dict) or not isinstance(corrected_args, dict):
            return False
        if rejected_started_payload.get("action") != "create_candidate":
            return False
        if _strip_replan_action(rejected_args) != _strip_replan_action(corrected_args):
            return False
        rejected_action = (
            rejected_args.get("replan_decision", {}).get("action")
            if isinstance(rejected_args.get("replan_decision"), dict)
            else None
        )
        corrected_action = (
            corrected_args.get("replan_decision", {}).get("action")
            if isinstance(corrected_args.get("replan_decision"), dict)
            else None
        )
        return (
            rejected_action == "refine_parameters" and corrected_action == "switch_approved_family"
        )

    matching = [trace for trace in traces if _matches(trace)]
    if len(matching) != 1:
        return None
    return {
        "rejectedAction": "refine_parameters",
        "correctedAction": "switch_approved_family",
        "retainedInputs": True,
        "outcome": "candidate_created",
    }


def apply_fixture_command(
    *,
    workspace_id: str,
    command: str,
    expected_row_version: int,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "quant-fixture-api")
        row = db.scalar(
            select(QuantRepositoryState)
            .where(QuantRepositoryState.workspace_id == workspace_id)
            .with_for_update()
        )
        current_name = (
            row.fixture_state
            if row is not None and row.fixture_state
            else os.environ.get(FIXTURE_ENV, DEFAULT_FIXTURE)
        )
        current_version = row.fixture_row_version if row is not None else 8
        current_input = dict(row.fixture_input_json or {}) if row is not None else {}
        snapshot = quant_workspace_fixture(current_name, fixture_input=current_input)
        if expected_row_version != current_version:
            raise ValueError("The fixture snapshot row version is stale.")
        legal = snapshot["run"]["legalCommands"] + snapshot["composerLegalCommands"]
        if command not in legal:
            raise ValueError("The command is not legal for the current API fixture snapshot.")
        next_name = {
            "ask": current_name,
            "generate_plan": "quant-plan-approval",
            "approve_plan": "quant-running",
            "run_fixture": "quant-waiting-review",
            "request_plan_changes": "quant-plan-approval",
            "cancel_run": "quant-cancelled",
            "retry_run": "quant-ready",
            "complete_review": "quant-completed",
        }[command]
        if row is None:
            row = QuantRepositoryState(
                workspace_id=workspace_id,
                state_json={},
                row_version=0,
                fixture_input_json={},
                fixture_row_version=current_version,
                data_authenticity=DataAuthenticity.GENERATED.value,
            )
            db.add(row)
        goal = (payload or {}).get("goal")
        normalized_goal: str | None = None
        if goal is not None:
            if command not in {"ask", "generate_plan"}:
                raise ValueError(
                    "The approved synthetic research goal cannot change during execution."
                )
            if not isinstance(goal, str) or not goal.strip() or len(goal.strip()) > 2000:
                raise ValueError("The synthetic research goal must contain 1 to 2000 characters.")
            normalized_goal = goal.strip()
        row.fixture_state = next_name
        if normalized_goal is not None:
            current_input["goal"] = normalized_goal
        row.fixture_input_json = current_input
        row.fixture_row_version = current_version + 1
        row.row_version += 1
        db.commit()
        return quant_workspace_fixture(
            next_name,
            fixture_row_version=current_version + 1,
            fixture_input=current_input,
        )


def quant_workspace_fixture(
    raw_state: str | None = None,
    *,
    workspace_id: str | None = None,
    fixture_row_version: int | None = None,
    fixture_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stored: tuple[str, int] | None = None
    if workspace_id is not None and raw_state is None:
        with get_session_factory()() as db:
            set_rls_context(db, workspace_id, "quant-fixture-api")
            row = db.get(QuantRepositoryState, workspace_id)
            if row is not None and row.fixture_state:
                stored = (row.fixture_state, row.fixture_row_version)
                fixture_input = dict(row.fixture_input_json or {})
    fixture_name = raw_state or (
        stored[0] if stored else os.environ.get(FIXTURE_ENV, DEFAULT_FIXTURE)
    )
    if fixture_name not in FIXTURE_STATES:
        allowed = ", ".join(sorted(FIXTURE_STATES))
        raise ValueError(f"{FIXTURE_ENV} must be one of: {allowed}")
    state, current_step, legal_commands, status_summary = _state_config(fixture_name)
    results_visible = state in {
        "validating",
        "generating_report",
        "waiting_for_review",
        "completed",
    }
    report_visible = state in {"waiting_for_review", "completed"}
    kernel_check = (
        build_quant_kernel_check() if results_visible else build_quant_kernel_capability()
    )
    dataset = SPY_DAILY_FIXTURE
    dataset_start = dataset.covered_start.isoformat()
    dataset_end = dataset.covered_end.isoformat()
    no_viable = fixture_name == "quant-no-viable-candidate"
    research = build_quant_research_projection(no_viable=no_viable) if results_visible else None
    live_candidate_source = research["candidates"] if research is not None else []
    if state in {"running_experiments", "repairing"}:
        live_candidate_source = build_quant_research_projection()["candidates"]
    elif state == "generating_candidates":
        live_candidate_source = [
            {
                "id": "candidate-a",
                "name": "Candidate A · SMA 20/100",
                "parameters": "fast=20 · slow=100",
                "metrics": None,
            }
        ]
    candidates = research["candidates"] if research is not None else []
    conclusion = research["conclusion"] if research is not None else "Agent output is pending."
    validation_digest = (
        canonical_digest(
            {
                "dataset_digest": dataset.digest,
                "validator_version": research["validatorVersion"],
                "candidates": candidates,
            }
        )
        if research is not None
        else None
    )
    report_digest = (
        canonical_digest(
            {
                "dataset_digest": dataset.digest,
                "conclusion": conclusion,
                "limitations": research["limitations"],
                "generation_method": research["generationMethod"],
            }
        )
        if research is not None
        else None
    )
    candidates = [{**item, "canSeedResearch": False} for item in candidates]
    live_candidate_source = [{**item, "canSeedResearch": False} for item in live_candidate_source]
    default_goal = "Evaluate bounded SPY trend hypotheses with synthetic evidence."
    stored_goal = (fixture_input or {}).get("goal", default_goal)
    research_goal = (
        stored_goal.strip()
        if isinstance(stored_goal, str) and stored_goal.strip()
        else default_goal
    )
    base_events = [
        (1, "run.created", "system", "Research attempt created from a synthetic fixture."),
        (2, "data.load.completed", "system", "Pinned synthetic SPY fixture snapshot loaded."),
        (
            3,
            "backtest.failed",
            "system",
            "Candidate B fixture experiment stopped safely; the run did not fail.",
        ),
        (
            4,
            "repair.completed",
            "system",
            "Candidate B fixture repair completed within the approved limit.",
        ),
        (
            5,
            "candidate.rejected",
            "validator",
            "Candidate A rejected; candidate verdict is independent of run health.",
        ),
        (6, "validation.completed", "validator", "Synthetic robustness validation completed."),
        (
            7,
            "report.generated",
            "agent",
            "Research Report generated from persisted synthetic fixture records.",
        ),
    ]
    progress_event_count = {
        "draft": 1,
        "waiting_plan_approval": 1,
        "loading_data": 1,
        "generating_candidates": 2,
        "running_experiments": 2,
        "repairing": 4,
        "validating": 6,
        "generating_report": 6,
        "waiting_for_review": 7,
        "completed": 7,
        "failed": 3,
        "cancelled": 2,
    }[state]
    events = base_events[:progress_event_count]
    if state in {"completed", "failed", "cancelled"}:
        terminal_type = (
            "run.failed"
            if state == "failed"
            else "run.cancelled"
            if state == "cancelled"
            else "run.completed"
        )
        events.append((len(events) + 1, terminal_type, "system", status_summary))
    visible_artifacts = [
        {
            "id": "fixture-dataset",
            "type": "dataset_snapshot",
            "title": "SPY Daily Synthetic Snapshot",
            "summary": "1,564 deterministic weekday OHLCV rows used by the pure research kernel.",
            "status": "ready",
            "origin": "Server fixture repository",
            "authenticity": "synthetic_fixture",
            "relatedLabel": "SPY · 1D · synthetic weekdays",
            "digest": dataset.digest,
        },
    ]
    if results_visible:
        assert research is not None and validation_digest is not None
        visible_artifacts.append(
            {
                "id": "fixture-validation",
                "type": "validation_report",
                "title": "Synthetic Robustness Validation",
                "summary": (
                    "Computed candidate metrics with fixed sensitivity and trade-count rules."
                ),
                "status": "ready",
                "origin": research["generationMethod"],
                "authenticity": "synthetic_fixture",
                "relatedLabel": "3 computed candidates",
                "digest": validation_digest,
            }
        )
    if report_visible:
        assert research is not None and report_digest is not None
        visible_artifacts.append(
            {
                "id": "fixture-report",
                "type": "research_report",
                "title": "SPY Synthetic Research Report",
                "summary": conclusion,
                "status": "reviewed" if state == "completed" else "ready",
                "origin": research["generationMethod"],
                "authenticity": "synthetic_fixture",
                "relatedLabel": "Attempt 1",
                "digest": report_digest,
            }
        )
    snapshot: dict[str, Any] = {
        "workspaceName": "Qurio Research",
        "version": "Phase 0 · server-fixture-v1",
        "authenticity": "synthetic_fixture",
        "runtimeLabel": "Incremental local Agent",
        "modelLabel": "Mock Agent",
        "project": {
            "id": "55555555-5555-4555-8555-555555555501",
            "latestRunId": "55555555-5555-4555-8555-555555555502",
            "title": "SPY · Trend Research",
            "goal": research_goal,
            "symbol": "SPY",
            "updatedAt": "2026-07-17T02:24:00Z",
            "statusLabel": status_summary,
            "needsAction": state.startswith("waiting_"),
        },
        "recentProjects": [],
        "scope": {
            "version": 1,
            "symbol": "SPY",
            "market": "US Equity",
            "interval": "1D",
            "dateRange": {"start": dataset_start, "end": dataset_end},
            "benchmark": "SPY Buy and Hold",
            "assumptions": [
                "1,564 generated synthetic weekday bars; no exchange calendar",
                "10 bps fee and 5 bps slippage per fill",
                "No network retrieval; only fixed typed strategy specifications",
            ],
        },
        "run": {
            "id": "55555555-5555-4555-8555-555555555502",
            "rowVersion": fixture_row_version
            if fixture_row_version is not None
            else stored[1]
            if stored
            else 8,
            "attemptNumber": 1,
            "state": state,
            "mode": "auto_research",
            "currentStepId": current_step,
            "latestSequence": events[-1][0],
            "startedAt": "2026-07-17T02:18:00Z",
            "completedAt": "2026-07-17T02:24:00Z"
            if state in {"completed", "failed", "cancelled"}
            else None,
            "usedExperiments": 3
            if results_visible
            else 1
            if state in {"running_experiments", "repairing"}
            else 0,
            "usedRepairAttempts": 1
            if state in {"repairing", "validating", "waiting_for_review", "completed"}
            else 0,
            "agentIteration": 10
            if state == "completed"
            else 5
            if state in {"running_experiments", "repairing", "validating", "waiting_for_review"}
            else 0,
            "maxAgentIterations": 12,
            "provider": "Mock Agent",
            "model": None,
            "legalCommands": legal_commands,
            "traceRef": "fixture-trace-spy-01",
        },
        "limits": {
            "maxExperiments": 3,
            "maxRepairAttempts": 2,
            "maxRuntimeMinutes": 5,
            "internetAccess": False,
            "arbitraryPython": False,
            "paperTrading": False,
        },
        "plan": _plan(current_step, state),
        "events": [
            {
                "id": f"fixture-event-{sequence}",
                "sequence": sequence,
                "type": event_type,
                "timestamp": f"2026-07-17T02:{18 + sequence:02d}:00Z",
                "actor": actor,
                "safeSummary": summary,
            }
            for sequence, event_type, actor, summary in events
        ],
        "artifacts": visible_artifacts,
        "dataset": {
            "id": dataset.dataset_id,
            "name": "SPY Daily Synthetic Weekday Fixture · 2018–2023",
            "symbol": dataset.symbol,
            "interval": dataset.interval.value,
            "dateRange": {"start": dataset_start, "end": dataset_end},
            "barCount": len(dataset.bars),
            "schemaVersion": dataset.schema_version,
            "parserVersion": "deterministic-weekday-generator-v2",
            "digest": dataset.digest,
            "authenticity": dataset.provenance.value,
        },
        "bars": _chart_sample(dataset, research["trades"] if research is not None else []),
        "kernelCheck": kernel_check,
        "benchmark": research["benchmark"] if research is not None else None,
        "candidates": candidates if results_visible else [],
        "liveResearch": _fixture_live_research(state, live_candidate_source),
        "performanceSeries": research["performanceSeries"] if research is not None else [],
        "trades": research["trades"] if report_visible and research is not None else [],
        "report": {
            "id": "fixture-report",
            "title": "SPY Synthetic Research Report",
            "conclusion": conclusion,
            "proposedNextStep": (
                "Review limitations; no broker or paper-trading action is available."
            ),
            "limitations": research["limitations"],
            "humanReviewStatus": "Fixture review record",
            "validatorVersion": research["validatorVersion"],
            "generationMethod": research["generationMethod"],
            "disclaimer": (
                "Synthetic results are not investment advice, a recommendation, market "
                "evidence, or evidence of future performance."
            ),
        }
        if report_visible and research is not None
        else None,
        "composerLegalCommands": ["ask", "generate_plan", "start_auto_research"]
        if fixture_name == "quant-ready"
        else [],
    }
    snapshot["recentProjects"] = [deepcopy(snapshot["project"])]
    return snapshot


def quant_agent_workspace_snapshot(
    *, workspace_id: str, run_id: str | None = None
) -> dict[str, Any] | None:
    """Project a durable autonomous run into the existing Mac view model.

    The latest run remains the default for the live workspace. Supplying a run
    id is reserved for read-only historical inspection.
    """

    from services.api.app.modules.quant.store import QuantStore, user_facing_report_text

    store = QuantStore()
    runs = store.list_runs(workspace_id=workspace_id)
    if not runs:
        return None
    run = store.get_run(workspace_id=workspace_id, run_id=run_id) if run_id is not None else runs[0]
    project = store.get_project(workspace_id=workspace_id, project_id=run.project_id)
    runtime_projection = store.runtime_projection(run)
    runtime = runtime_projection.descriptor
    runtime_split = runtime_projection.split
    daily_dataset = runtime_projection.daily_dataset
    dataset_record = runtime_projection.daily_record
    market_record = runtime_projection.market_record
    is_market_runtime = market_record is not None
    dataset = market_record.dataset if market_record is not None else daily_dataset
    if dataset is None:  # pragma: no cover - runtime projection is a closed union
        raise ValueError("The runtime projection has no source dataset.")
    dataset_name = (
        market_record.name
        if market_record is not None
        else (
            dataset_record.name
            if dataset_record is not None
            else "SPY Daily Synthetic Weekday Fixture · 2018–2023"
        )
    )
    dataset_authenticity = (
        runtime.data_authenticity.value
        if is_market_runtime
        else (
            dataset_record.data_authenticity.value
            if dataset_record is not None
            else "synthetic_fixture"
        )
    )
    snapshot = quant_workspace_fixture("quant-ready")
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    approved_plan = context["approved_plan"]
    memory = context["research_memory"]
    source_run_count = len(memory["source_run_ids"])
    tested_candidate_count = len(memory["tested_candidate_keys"])
    research_plan = {
        "candidateFamilies": approved_plan["candidate_families"],
        "strategyScope": {
            "schemaVersion": approved_plan["strategy_scope"]["schema_version"],
            "status": approved_plan["strategy_scope"]["status"],
            "reason": approved_plan["strategy_scope"]["reason"],
            "excludedBehaviors": approved_plan["strategy_scope"]["excluded_behaviors"],
            **(
                {"proxyDescription": approved_plan["strategy_scope"]["proxy_description"]}
                if approved_plan["strategy_scope"]["proxy_description"] is not None
                else {}
            ),
        },
        "selectionObjective": approved_plan["selection_objective"],
        "completionCriteria": approved_plan["completion_criteria"],
    }
    if run.plan_summary:
        research_plan["objectiveSummary"] = run.plan_summary
    snapshot["researchPlan"] = research_plan
    # The Agent context validates the pinned memory before it reaches this
    # projection. Keep the UI contract deliberately count-only.
    if source_run_count > 0 and tested_candidate_count > 0:
        snapshot["researchMemory"] = {
            "sourceRunCount": source_run_count,
            "testedCandidateCount": tested_candidate_count,
        }
    experiments = store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
    event_rows = store.events_for_run(workspace_id=workspace_id, run_id=run.id)

    action_to_step = {
        "inspect_research_context": "dataset",
        "list_strategy_templates": "candidates",
        "create_candidate": "candidates",
        "run_backtest": "experiments",
        "revise_candidate": "repair",
        "compare_candidates": "comparison",
        "finish_research": "report",
    }
    current_step = action_to_step.get(run.last_action or "", "scope")
    if run.state.value == "completed":
        current_step = "decision"
    state = run.state.value
    step_keys = [item["id"] for item in snapshot["plan"]]
    current_index = step_keys.index(current_step)
    for index, step in enumerate(snapshot["plan"]):
        if state == "completed":
            step["status"] = "completed"
        elif state in {"failed", "cancelled"}:
            step["status"] = "completed" if index < current_index else "skipped"
        elif index < current_index:
            step["status"] = "completed"
        elif index == current_index:
            step["status"] = "active"
        else:
            step["status"] = "pending"
        step["description"] = "Durable autonomous Agent step."

    if is_market_runtime and run.market_run_contract_version is None:
        legal_commands = []
    elif state == "waiting_plan_approval":
        legal_commands = (
            ["request_plan_changes", "cancel_run"]
            if run.strategy_scope.status == "unsupported"
            else ["approve_plan", "request_plan_changes", "cancel_run"]
        )
    elif state not in {"completed", "failed", "cancelled"}:
        legal_commands = ["cancel_run"]
    else:
        legal_commands = ["retry_run"]

    def event_actor(event_type: str) -> str:
        if event_type.startswith("agent.") or event_type.startswith("candidate."):
            return "agent"
        return "system"

    snapshot["workspaceName"] = "Qurio Research"
    snapshot["version"] = "Phase 1A · autonomous-agent-v1"
    snapshot["runtimeLabel"] = "Incremental local Agent"
    snapshot["modelLabel"] = "Mock Agent" if run.provider == "mock" else run.model or "DeepSeek"
    snapshot["project"] = {
        "id": project.id,
        "latestRunId": run.id,
        "title": project.name,
        "goal": run.question,
        "symbol": runtime.symbol,
        "updatedAt": run.updated_at.isoformat(),
        "statusLabel": run.agent_status.replace("_", " ").title(),
        "needsAction": state == "waiting_plan_approval",
    }
    # Preserve list order from the store (newest first) while exposing one
    # truthful navigation item per project.
    latest_run_by_project = {}
    for item in runs:
        latest_run_by_project.setdefault(item.project_id, item)
    snapshot["recentProjects"] = [
        {
            "id": item.id,
            "latestRunId": latest.id,
            "title": item.name,
            "goal": latest.question if latest is not None else item.objective,
            "symbol": (
                store.runtime_projection(latest).descriptor.symbol if latest is not None else "—"
            ),
            "updatedAt": (
                latest.updated_at.isoformat() if latest is not None else item.updated_at.isoformat()
            ),
            "statusLabel": (
                latest.state.value.replace("_", " ").title()
                if latest is not None
                else item.status.value.replace("_", " ").title()
            ),
            "needsAction": (latest is not None and latest.state.value == "waiting_plan_approval"),
        }
        for item in store.list_projects(workspace_id=workspace_id)
        if (latest := latest_run_by_project.get(item.id)) is not None
    ]
    snapshot["authenticity"] = dataset_authenticity
    provider_id = dataset_record.source_metadata.provider_id if dataset_record is not None else None
    if market_record is not None:
        market = (
            "24x7 Market"
            if market_record.dataset.market_calendar.value == "24x7"
            else "Imported Market Data"
        )
    elif provider_id == "binance_spot":
        market = "Crypto Spot"
    elif provider_id == "nasdaq_equity" or dataset_record is None:
        market = "US Equity"
    else:
        market = "Imported Market Data"
    snapshot["scope"] = {
        **snapshot["scope"],
        "symbol": runtime.symbol,
        "market": market,
        "interval": runtime.interval.value,
        "dateRange": {
            "start": (
                runtime.coverage_start_utc.isoformat()
                if is_market_runtime
                else run.research_start.isoformat()
            ),
            "end": (
                runtime.coverage_end_utc.isoformat()
                if is_market_runtime
                else run.research_end.isoformat()
            ),
        },
        "benchmark": f"{runtime.symbol} Buy and Hold",
        "assumptions": [
            (
                f"{len(runtime.bars):,} {runtime.interval.value} OHLCV bars in the "
                "pinned UTC research range"
                if is_market_runtime
                else f"{len(store.bars_for_run(run)):,} daily OHLCV bars in the research range"
            ),
            *(
                [f"{runtime.periods_per_year:,} periods per year for annualized metrics"]
                if is_market_runtime
                else []
            ),
            "10 bps fee and 5 bps slippage per fill",
            "No Agent network tool; only fixed typed strategy specifications",
        ],
    }
    snapshot["dataset"] = {
        "id": dataset.dataset_id,
        "name": dataset_name,
        "symbol": dataset.symbol,
        "interval": dataset.interval.value,
        "dateRange": {
            "start": (
                runtime.coverage_start_utc.isoformat()
                if is_market_runtime
                else dataset.covered_start.isoformat()
            ),
            "end": (
                runtime.coverage_end_utc.isoformat()
                if is_market_runtime
                else dataset.covered_end.isoformat()
            ),
        },
        "barCount": len(runtime.bars) if is_market_runtime else len(dataset.bars),
        "schemaVersion": dataset.schema_version,
        "parserVersion": (
            market_record.evidence.normalizer_version
            if market_record is not None
            else (
                dataset_record.parser_version
                if dataset_record is not None
                else "deterministic-weekday-generator-v2"
            )
        ),
        "digest": dataset.digest,
        "authenticity": dataset_authenticity,
        **(
            {
                "source": {
                    "kind": dataset_record.source_metadata.kind,
                    "fileName": dataset_record.source_metadata.file_name,
                    "sourceName": dataset_record.source_metadata.source_name,
                    "sourceReference": dataset_record.source_metadata.source_reference,
                    "submittedCsvDigest": (dataset_record.source_metadata.submitted_csv_digest),
                    "providerId": dataset_record.source_metadata.provider_id,
                    "providerResponseDigest": (
                        dataset_record.source_metadata.provider_response_digest
                    ),
                    "providerResponseAttestations": [
                        {
                            "kind": item.kind,
                            "digest": item.digest,
                            "sourceReference": item.source_reference,
                        }
                        for item in dataset_record.source_metadata.provider_response_attestations
                    ],
                    "corporateActionsAttestation": (
                        {
                            "dividendsStatus": actions.dividends_status,
                            "splitsStatus": actions.splits_status,
                            "coverageStart": (
                                actions.coverage_start.isoformat()
                                if actions.coverage_start is not None
                                else None
                            ),
                            "coverageEnd": (
                                actions.coverage_end.isoformat()
                                if actions.coverage_end is not None
                                else None
                            ),
                            "dividendCoverageStart": (
                                actions.dividend_coverage_start.isoformat()
                                if actions.dividend_coverage_start is not None
                                else None
                            ),
                            "dividendCoverageEnd": (
                                actions.dividend_coverage_end.isoformat()
                                if actions.dividend_coverage_end is not None
                                else None
                            ),
                            "splitCoverageStart": (
                                actions.split_coverage_start.isoformat()
                                if actions.split_coverage_start is not None
                                else None
                            ),
                            "splitCoverageEnd": (
                                actions.split_coverage_end.isoformat()
                                if actions.split_coverage_end is not None
                                else None
                            ),
                            "splitSnapshotAsOf": (
                                actions.split_snapshot_as_of.isoformat()
                                if actions.split_snapshot_as_of is not None
                                else None
                            ),
                            "splitCompletenessStatus": actions.split_completeness_status,
                            "splitReconciliationStatus": actions.split_reconciliation_status,
                            "dividendEventCount": actions.dividend_event_count,
                            "splitEventCount": actions.split_event_count,
                            "splitEvents": [
                                {
                                    "effectiveDate": event.effective_date.isoformat(),
                                    "ratioNumerator": str(event.ratio_numerator),
                                    "ratioDenominator": str(event.ratio_denominator),
                                }
                                for event in actions.split_events
                            ],
                            "note": actions.note,
                        }
                        if (actions := dataset_record.source_metadata.corporate_actions_attestation)
                        is not None
                        else None
                    ),
                    "priceAdjustmentVerificationStatus": (
                        dataset_record.source_metadata.price_adjustment_verification_status
                    ),
                    "retrievedAt": (
                        dataset_record.source_metadata.retrieved_at.isoformat()
                        if dataset_record.source_metadata.retrieved_at is not None
                        else None
                    ),
                    "requestedLimit": dataset_record.source_metadata.requested_limit,
                    "returnedBarCount": (dataset_record.source_metadata.returned_bar_count),
                    "droppedIncompleteCount": (
                        dataset_record.source_metadata.dropped_incomplete_count
                    ),
                    "normalizationNote": (dataset_record.source_metadata.normalization_note),
                    "attestationStatus": (dataset_record.source_metadata.attestation_status),
                    "marketCalendar": dataset_record.source_metadata.market_calendar,
                    "timeZone": dataset_record.source_metadata.time_zone,
                    "priceAdjustment": dataset_record.source_metadata.price_adjustment,
                },
                "quality": _dataset_quality_projection(
                    context["dataset_summary"].get("data_quality")
                ),
            }
            if dataset_record is not None
            else {}
        ),
        **(
            {
                "periodsPerYear": runtime.periods_per_year,
                "marketCalendar": market_record.dataset.market_calendar.value,
                "marketSession": market_record.dataset.market_session.value,
                "timeZone": market_record.dataset.time_zone,
                "runtimeDescriptorDigest": runtime.descriptor_digest,
                "sealedSplitDigest": runtime_split.seal_digest,
                "source": {
                    "kind": market_record.evidence.source_kind.value,
                    "fileName": market_record.evidence.file_name,
                    "sourceName": market_record.evidence.source_name,
                    "sourceReference": market_record.evidence.source_reference,
                    "submittedCsvDigest": market_record.evidence.submitted_csv_digest,
                    "retrievedAtUtc": (
                        market_record.evidence.retrieved_at_utc.isoformat()
                        if market_record.evidence.retrieved_at_utc is not None
                        else None
                    ),
                    "requestedBarCount": market_record.evidence.requested_bar_count,
                    "returnedBarCount": market_record.evidence.returned_bar_count,
                    "retainedBarCount": market_record.evidence.retained_bar_count,
                    "closedDroppedCount": market_record.evidence.closed_dropped_count,
                    "deduplicatedCount": market_record.evidence.deduplicated_count,
                    "batchDigest": market_record.evidence.batch_digest,
                    "terminationReason": market_record.evidence.termination_reason,
                    "targetSatisfied": market_record.evidence.target_satisfied,
                    "normalizerVersion": market_record.evidence.normalizer_version,
                },
                "quality": {
                    "status": market_record.quality.status,
                    "cadenceGapCount": market_record.quality.cadence_gap_count,
                    "normalizationNote": market_record.quality.normalization_note,
                },
            }
            if market_record is not None
            else {}
        ),
    }
    if is_market_runtime:
        snapshot["bars"] = _market_chart_sample(runtime.bars, [])
    else:
        if daily_dataset is None:  # pragma: no cover - closed projection union
            raise ValueError("The daily runtime projection has no daily dataset.")
        snapshot["bars"] = _chart_sample(daily_dataset, [])
    snapshot["trades"] = []
    snapshot["run"] = {
        "id": run.id,
        "rowVersion": run.row_version,
        "attemptNumber": run.attempt_number,
        "state": state,
        "mode": "auto_research" if run.mode.value == "auto" else "plan",
        "currentStepId": current_step,
        "latestSequence": run.latest_sequence,
        "startedAt": run.created_at.isoformat(),
        "completedAt": run.updated_at.isoformat()
        if state in {"completed", "failed", "cancelled"}
        else None,
        "usedExperiments": run.used_experiments,
        "usedRepairAttempts": run.used_repairs,
        "agentIteration": run.agent_iteration,
        "maxAgentIterations": run.max_agent_iterations,
        "provider": "Mock Agent" if run.provider == "mock" else "DeepSeek",
        "model": run.model,
        "legalCommands": legal_commands,
        "traceRef": run.trace_id,
        **({"retryOfRunId": run.retry_of_run_id} if run.retry_of_run_id is not None else {}),
        **(
            {
                "continuedFrom": {
                    "parentRunId": refinement["parent_run_id"],
                    "seedCandidateId": refinement["seed_candidate_id"],
                    "candidateName": refinement["seed_candidate"]["name"],
                    "sourceQuestion": refinement["source_research_goal"],
                    "reason": refinement["refinement_reason"],
                }
            }
            if (refinement := context.get("refinement")) is not None
            else {}
        ),
    }
    snapshot["limits"] = {
        **snapshot["limits"],
        "maxExperiments": run.max_experiments,
        "maxRepairAttempts": run.max_repairs,
    }
    internal_artifact_ids = {
        item.id
        for item in artifacts
        if item.kind
        in {
            QuantArtifactKind.ITERATION_FEEDBACK,
            QuantArtifactKind.LEARNING_TRACE,
        }
    }

    def frontstage_safe_summary(payload: dict[str, Any]) -> str:
        """Keep internal iteration feedback out of the user-facing activity stream."""

        summary = str(payload.get("safe_summary", "Agent activity recorded."))
        return re.sub(
            r"\biteration(?:[_\s-]+)feedback\b",
            "prior training comparison",
            summary,
            flags=re.IGNORECASE,
        )

    def frontstage_artifact_id(payload: dict[str, Any]) -> str | None:
        artifact_id = payload.get("artifact_id")
        if artifact_id is None or str(artifact_id) in internal_artifact_ids:
            return None
        return str(artifact_id)

    def frontstage_artifact_ids(payload: dict[str, Any]) -> list[str]:
        artifact_ids = payload.get("artifact_ids")
        if not isinstance(artifact_ids, list):
            return []
        return [
            str(item)
            for item in artifact_ids
            if str(item) not in internal_artifact_ids
        ]

    def hide_internal_event(event_type: str, payload: dict[str, Any]) -> bool:
        if not _payload_refs_internal_artifacts(payload, internal_artifact_ids):
            return False
        # Tool outcomes are real front-stage observations. Keep the event while
        # stripping internal learning-trace / iteration-feedback references.
        return event_type not in {"tool.completed", "tool.failed"}

    snapshot["events"] = [
        {
            "id": item["event_id"],
            "sequence": item["sequence"],
            "type": item["event_type"],
            "timestamp": item["timestamp"].isoformat(),
            "actor": event_actor(item["event_type"]),
            "safeSummary": frontstage_safe_summary(item["payload"]),
            **(
                {"artifactId": artifact_id}
                if (artifact_id := frontstage_artifact_id(item["payload"])) is not None
                else {}
            ),
            **({"action": item["payload"]["action"]} if item["payload"].get("action") else {}),
            **(
                {"expectedResult": item["payload"]["expected_result"]}
                if item["payload"].get("expected_result")
                else {}
            ),
            **(
                {"candidateId": item["payload"]["candidate_id"]}
                if item["payload"].get("candidate_id")
                else {}
            ),
            **(
                {"artifactIds": artifact_ids}
                if (artifact_ids := frontstage_artifact_ids(item["payload"]))
                else {}
            ),
        }
        for item in event_rows
        if item["event_type"] != "agent.repair_memory_reused"
        and not hide_internal_event(item["event_type"], item["payload"])
    ]
    snapshot["artifacts"] = [
        {
            "id": item.id,
            "type": artifact_type_for_kind(item.kind.value),
            "title": item.title,
            "summary": user_facing_report_text(
                item.content.get("conclusion", item.title), fallback=item.title
            ),
            "status": "ready",
            "origin": "Autonomous local Agent",
            "authenticity": dataset_authenticity,
            "relatedLabel": f"Run {run.attempt_number}",
            "digest": item.digest,
        }
        for item in artifacts
        if item.kind
        not in {
            QuantArtifactKind.ITERATION_FEEDBACK,
            QuantArtifactKind.LEARNING_TRACE,
        }
    ]
    verdict_map = {"viable": "promising", "not_viable": "inconclusive", "rejected": "rejected"}

    def live_candidate(item: Any) -> dict[str, Any]:
        candidate_state = item.state
        if candidate_state == "created":
            candidate_state = "repairing" if item.repair_count > 0 else "queued"
        if candidate_state not in {
            "completed",
            "running",
            "queued",
            "repairing",
            "revised",
            "failed",
        }:
            candidate_state = "queued"
        metrics = (
            {
                "annualizedReturn": item.metrics["annualized_return_pct"],
                "maxDrawdown": item.metrics["maximum_drawdown_pct"],
                "sharpe": item.metrics["sharpe_ratio"],
                "trades": item.metrics["trade_count"],
            }
            if item.metrics
            else None
        )
        return {
            "id": item.id,
            "ordinal": item.ordinal,
            "name": item.name,
            "hypothesis": item.hypothesis,
            "parameters": " · ".join(f"{key}={value}" for key, value in item.parameters.items()),
            "state": candidate_state,
            "repairCount": item.repair_count,
            "metrics": metrics,
        }

    live_rows = [live_candidate(item) for item in sorted(experiments, key=lambda row: row.ordinal)]
    current_live = next(
        (item for item in reversed(live_rows) if item["state"] in {"running", "repairing"}),
        next((item for item in reversed(live_rows) if item["state"] == "queued"), None),
    )
    latest_live = next(
        (item for item in reversed(live_rows) if item["state"] == "completed" and item["metrics"]),
        None,
    )
    if state in ACTIVE_RESEARCH_STATES:
        phase_label, next_step = LIVE_PHASE_COPY[state]
        snapshot["liveResearch"] = {
            "phase": state,
            "phaseLabel": phase_label,
            "iteration": run.agent_iteration + 1,
            "currentExperiment": current_live,
            "latestResult": latest_live,
            "candidates": live_rows,
            "nextStep": next_step,
        }
    else:
        snapshot["liveResearch"] = None

    def can_seed_research(item: Any) -> bool:
        return item.state == "completed" and item.template != "fixture" and bool(item.parameters)

    experiment_names = {item.id: item.name for item in experiments}
    latest_training_comparison = next(
        (
            item
            for item in sorted(artifacts, key=lambda row: row.ordinal, reverse=True)
            if item.kind.value == "validation_report"
            and item.content.get("evaluation_partition") == "train"
            and isinstance(item.content.get("ranking"), list)
        ),
        None,
    )
    training_ranking = (
        [item for item in latest_training_comparison.content["ranking"] if isinstance(item, str)]
        if latest_training_comparison is not None
        else []
    )
    retained_report = next(
        (
            item
            for item in sorted(artifacts, key=lambda row: row.ordinal, reverse=True)
            if item.kind.value == "research_report"
        ),
        None,
    )
    report_selection = (
        retained_report.content.get("selected_candidate_id")
        if retained_report is not None
        else None
    )
    raw_selection_decision = (
        retained_report.content.get("research_decision") if retained_report is not None else None
    )
    selection_decision: dict[str, Any] | None = None
    if isinstance(raw_selection_decision, dict):
        try:
            research_decision = QuantResearchDecision.model_validate(raw_selection_decision)
        except ValueError:
            pass
        else:
            if research_decision.selected_candidate_id == report_selection:
                selection_decision = {
                    "basis": research_decision.decision_basis,
                    "selectedCandidateId": research_decision.selected_candidate_id,
                }
                if research_decision.deviation is not None:
                    selection_decision.update(
                        {
                            "reason": research_decision.deviation.reason,
                            "referenceCandidateId": (
                                research_decision.deviation.reference_candidate_id
                            ),
                        }
                    )
    feedback_by_id = {
        item.id: item
        for item in artifacts
        if item.kind.value == "iteration_feedback"
        and item.content.get("evaluation_partition") == "train"
    }

    def candidate_evolution(item: Any) -> dict[str, Any]:
        feedback = feedback_by_id.get(item.feedback_artifact_id)
        reference: dict[str, Any] = {}
        if feedback is not None:
            candidate_reference = feedback.content.get("improvement_reference")
            if isinstance(candidate_reference, dict):
                reference = candidate_reference
        reference_id = reference.get("candidate_id")
        reference_name = (
            experiment_names.get(reference_id) if isinstance(reference_id, str) else None
        )
        rank = training_ranking.index(item.id) + 1 if item.id in training_ranking else None
        candidate_count = len(training_ranking) if rank is not None else None
        objective_label = {
            "risk_adjusted_return": "risk-adjusted return",
            "total_return": "total return",
            "drawdown_control": "drawdown control",
        }.get(run.selection_objective, "approved")
        override_reason_label = {
            "walk_forward_stability": "walk-forward stability",
            "regime_coverage": "regime coverage",
            "minimum_trade_evidence": "minimum trade evidence",
        }
        if rank is None:
            selection_reason = "No final training-comparison rank was retained for this candidate."
        elif item.id == report_selection:
            if selection_decision and selection_decision["basis"] == "robustness_override":
                reference_id = str(selection_decision["referenceCandidateId"])
                reference_name = experiment_names.get(reference_id, reference_id)
                reason = override_reason_label[str(selection_decision["reason"])]
                selection_reason = (
                    f"Selected by a server-validated {reason} override after ranking {rank} of "
                    f"{candidate_count}, instead of objective leader {reference_name}; sealed "
                    "holdout evidence was not available at selection time."
                )
            else:
                selection_reason = (
                    f"Selected as rank 1 of {candidate_count} under the approved {objective_label} "
                    "objective; sealed holdout evidence was not available at selection time."
                )
        else:
            if (
                selection_decision
                and selection_decision["basis"] == "robustness_override"
                and item.id == selection_decision["referenceCandidateId"]
            ):
                selected_name = experiment_names.get(str(report_selection), str(report_selection))
                reason = override_reason_label[str(selection_decision["reason"])]
                selection_reason = (
                    f"Ranked 1 of {candidate_count} for {objective_label}, but a server-validated "
                    f"{reason} override selected {selected_name} for sealed holdout evaluation."
                )
            else:
                selection_reason = (
                    f"Ranked {rank} of {candidate_count} in the final training comparison and was "
                    "not selected for sealed holdout evaluation."
                )
        return {
            "hypothesis": item.hypothesis,
            "origin": "training_feedback" if feedback is not None else "initial",
            "changeRationale": item.change_rationale,
            "feedbackReferenceCandidateId": reference_id if isinstance(reference_id, str) else None,
            "feedbackReferenceCandidateName": reference_name,
            "comparisonRank": rank,
            "comparisonCandidateCount": candidate_count,
            "selectionReason": selection_reason,
        }

    snapshot["candidates"] = []
    for item in experiments:
        if item.template == "fixture":
            continue
        evolution = candidate_evolution(item)
        replan_repair = _project_replan_repair(artifacts, event_rows, item.id)
        if replan_repair is not None:
            evolution["replanRepair"] = replan_repair
        snapshot["candidates"].append(
            {
                "id": item.id,
                "name": item.name,
                "parameters": " · ".join(
                    f"{key}={value}" for key, value in item.parameters.items()
                ),
                "verdict": verdict_map[item.verdict.value],
                "verdictReason": item.summary,
                "metrics": {
                    "annualizedReturn": item.metrics.get("annualized_return_pct", 0),
                    "maxDrawdown": item.metrics.get("maximum_drawdown_pct", 0),
                    "sharpe": item.metrics.get("sharpe_ratio", 0),
                    "trades": item.metrics.get("trade_count", 0),
                },
                "strategySpecVersion": (
                    "market-bar-kernel-v1" if is_market_runtime else "daily-bar-kernel-v1"
                ),
                "strategySpec": f"template: {item.template}\nparameters: {item.parameters}",
                "canSeedResearch": can_seed_research(item),
                "robustness": [item.latest_observation or "Backtest pending."],
                "evolution": evolution,
            }
        )
    candidate_names = {item.id: item.name for item in experiments}
    snapshot["performanceSeries"] = []
    if any(item.metrics for item in experiments):
        if is_market_runtime:
            if runtime.cadence is None:  # pragma: no cover - v2 resolver requires cadence
                raise ValueError("The market runtime projection has no cadence.")
            benchmark_points = _market_benchmark_performance_points(
                runtime_split.training_bars, runtime.cadence
            )
        else:
            if daily_dataset is None:  # pragma: no cover - closed projection union
                raise ValueError("The daily runtime projection has no daily dataset.")
            benchmark_points = _benchmark_performance_points(daily_dataset)
        snapshot["performanceSeries"].append(
            {
                "id": "benchmark",
                "label": "Buy and hold",
                "kind": "benchmark",
                "points": benchmark_points,
            }
        )
    snapshot["performanceSeries"].extend(
        {
            "id": str(item.content.get("candidate_id")),
            "label": candidate_names.get(str(item.content.get("candidate_id")), "Candidate"),
            "kind": "candidate",
            "points": _normalized_performance_points(item.content.get("points")),
        }
        for item in artifacts
        if item.kind.value == "equity_curve"
        and item.content.get("candidate_id")
        and item.content.get("points")
    )
    computed_experiments = [item for item in experiments if item.metrics]

    def kernel_result(identifier: str, label: str, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": identifier,
            "label": label,
            "totalReturnPct": metrics.get("total_return_pct", 0),
            "annualizedReturnPct": metrics.get("annualized_return_pct", 0),
            "maxDrawdownPct": metrics.get("maximum_drawdown_pct", 0),
            "sharpe": metrics.get("sharpe_ratio", 0),
            "tradeCount": metrics.get("trade_count", 0),
            "finalEquity": metrics.get("final_equity", 0),
        }

    snapshot["kernelCheck"] = {
        "status": "verified" if computed_experiments else "available",
        "engineVersion": ("market-bar-kernel-v1" if is_market_runtime else "daily-bar-kernel-v1"),
        "datasetId": runtime.dataset_id,
        "datasetDigest": runtime.dataset_digest,
        "barCount": len(runtime.bars) if is_market_runtime else len(dataset.bars),
        **(
            {
                "interval": runtime.interval.value,
                "periodsPerYear": runtime.periods_per_year,
                "runtimeDescriptorDigest": runtime.descriptor_digest,
                "sealedSplitDigest": runtime_split.seal_digest,
            }
            if is_market_runtime
            else {}
        ),
        "execution": "signal_at_close_fill_next_open",
        "feeRateBps": 10,
        "slippageRateBps": 5,
        "benchmark": (
            kernel_result("buy-and-hold", "Buy and Hold", context["benchmark_summary"])
            if computed_experiments
            else None
        ),
        "strategies": [
            kernel_result(item.id, item.name, item.metrics) for item in computed_experiments
        ],
        "limitations": [
            (
                "Nasdaq bars, listing information, and dividend rows retain separate response "
                "digests; dividends were not independently verified and splits were unavailable."
                if dataset_record is not None
                and dataset_record.source_metadata.provider_id == "nasdaq_equity"
                else (
                    "Provider-retrieved timestamped bars retain bounded source evidence but "
                    "were not cross-validated against a second market source."
                    if market_record is not None
                    and market_record.evidence.source_kind.value == "provider_fetch"
                    else (
                        "Workspace-imported timestamped bars were not independently verified "
                        "against a market data provider."
                        if market_record is not None
                        else (
                            "Provider-retrieved bars retain a raw-response digest but were not "
                            "cross-validated against a second market source."
                            if dataset_record is not None
                            and dataset_record.source_metadata.kind == "provider_fetch"
                            else (
                                "Workspace-imported bars were not independently verified against a "
                                "market data provider."
                                if dataset_record is not None
                                else "The deterministic synthetic bars are not market observations."
                            )
                        )
                    )
                )
            ),
            (
                "Candidate and benchmark metrics shown outside Generalization use the "
                "chronological training partition."
            ),
            "No statistical significance or live execution was evaluated.",
            "The Agent has no network, broker, or arbitrary code execution tool.",
        ],
    }
    snapshot["benchmark"] = {
        "annualizedReturn": context["benchmark_summary"]["annualized_return_pct"],
        "maxDrawdown": context["benchmark_summary"]["maximum_drawdown_pct"],
        "sharpe": context["benchmark_summary"]["sharpe_ratio"],
        "trades": context["benchmark_summary"]["trade_count"],
    }
    report_artifact = (
        next((item for item in artifacts if item.kind.value == "research_report"), None)
        if state == "completed"
        else None
    )
    selected_candidate_id = (
        report_artifact.content.get("selected_candidate_id")
        if report_artifact is not None
        else None
    )
    robustness_sensitivity: dict[str, Any] | None = None
    if report_artifact is not None:
        robustness_link = report_artifact.content.get("robustness_sensitivity")
        if robustness_link is not None:
            if (
                not isinstance(robustness_link, dict)
                or set(robustness_link) != {"artifact_id", "artifact_digest"}
                or not isinstance(robustness_link.get("artifact_id"), str)
                or not isinstance(robustness_link.get("artifact_digest"), str)
            ):
                raise ValueError("The report robustness sensitivity link is invalid.")
            linked_artifacts = [
                item for item in artifacts if item.id == robustness_link["artifact_id"]
            ]
            if len(linked_artifacts) != 1:
                raise ValueError("The linked robustness sensitivity artifact is missing.")
            linked_artifact = linked_artifacts[0]
            if (
                linked_artifact.kind is not QuantArtifactKind.ROBUSTNESS_SENSITIVITY
                or linked_artifact.run_id != run.id
                or linked_artifact.digest != robustness_link["artifact_digest"]
                or linked_artifact.digest != canonical_digest(linked_artifact.content)
            ):
                raise ValueError("The linked robustness sensitivity identity is invalid.")
            parsed_robustness = QuantRobustnessSensitivity.model_validate(linked_artifact.content)
            if (
                parsed_robustness.run_id != run.id
                or parsed_robustness.report_artifact_id != report_artifact.id
                or parsed_robustness.candidate.candidate_id != selected_candidate_id
            ):
                raise ValueError("The linked robustness sensitivity content is invalid.")
            robustness_sensitivity = _robustness_sensitivity_projection(parsed_robustness)
    iteration_stop: dict[str, str] | None = None
    if report_artifact is not None:
        raw_replan_decision = report_artifact.content.get("replan_decision")
        if isinstance(raw_replan_decision, dict):
            try:
                replan_decision = QuantEvidenceReplanDecision.model_validate(raw_replan_decision)
            except ValueError:
                pass
            else:
                stop_reason = {
                    "stop_no_novel_candidate": "no_novel_candidate",
                    "stop_insufficient_budget": "insufficient_action_budget",
                }.get(replan_decision.action)
                if stop_reason is not None:
                    iteration_stop = {
                        "reason": stop_reason,
                        "referenceCandidateId": (
                            replan_decision.improvement_reference_candidate_id
                        ),
                    }
    if report_artifact is None and not any(
        item.kind.value == "trade_log"
        and item.content.get("candidate_id") == selected_candidate_id
        and item.content.get("trades")
        for item in artifacts
    ):
        fallback_trade_artifact = next(
            (
                item
                for item in artifacts
                if item.kind.value == "trade_log" and item.content.get("trades")
            ),
            None,
        )
        if fallback_trade_artifact is not None:
            selected_candidate_id = fallback_trade_artifact.content.get("candidate_id")

    def projected_trade(artifact: Any, trade: dict[str, Any], index: int) -> dict[str, Any]:
        entry = str(trade.get("entry_timestamp") or trade["entry_date"])
        exit_value = str(trade.get("exit_timestamp") or trade["exit_date"])
        holding = (
            {
                "holdingBars": trade.get("holding_bars"),
                "holdingElapsedSeconds": trade.get("holding_elapsed_seconds"),
            }
            if is_market_runtime
            else {
                "holdingDays": max(
                    0,
                    (
                        date.fromisoformat(trade["exit_date"])
                        - date.fromisoformat(trade["entry_date"])
                    ).days,
                )
            }
        )
        return QuantWorkspaceTradeProjection.model_validate(
            {
                "id": f"{artifact.id}:{index}",
                "candidateId": artifact.content.get("candidate_id"),
                "entryDate": entry,
                "exitDate": exit_value,
                "returnPct": trade["return_pct"],
                **holding,
                "reason": "Persisted chronological training backtest trade.",
            }
        ).model_dump(mode="json", by_alias=True, exclude_none=True)

    snapshot["trades"] = [
        projected_trade(artifact, trade, index)
        for artifact in artifacts
        if artifact.kind.value == "trade_log" and artifact.content.get("candidate_id")
        for index, trade in enumerate(artifact.content.get("trades", []), start=1)
    ]
    selected_trades = [
        trade for trade in snapshot["trades"] if trade["candidateId"] == selected_candidate_id
    ]
    if is_market_runtime:
        snapshot["bars"] = _market_chart_sample(runtime.bars, selected_trades, snapshot["trades"])
    else:
        if daily_dataset is None:  # pragma: no cover - closed projection union
            raise ValueError("The daily runtime projection has no daily dataset.")
        snapshot["bars"] = _chart_sample(daily_dataset, selected_trades, snapshot["trades"])
    snapshot["report"] = (
        {
            "id": report_artifact.id,
            "title": report_artifact.title,
            "selectedCandidateId": report_selection,
            "conclusion": user_facing_report_text(
                report_artifact.content.get("conclusion", run.final_conclusion or ""),
                fallback=(
                    "The final training comparison selected the retained strategy for evaluation."
                ),
            ),
            "proposedNextStep": report_artifact.content.get("next_step", "stop").replace("_", " "),
            "limitations": [
                user_facing_report_text(item, fallback="A retained limitation requires review.")
                for item in report_artifact.content.get("limitations", [])
                if isinstance(item, str)
            ],
            "humanReviewStatus": "Agent report retained",
            "validatorVersion": "chronological-80-20-v1",
            "generationMethod": "Autonomous Agent over deterministic local tools",
            **({"selectionDecision": selection_decision} if selection_decision is not None else {}),
            **({"iterationStop": iteration_stop} if iteration_stop is not None else {}),
            **(
                {"robustnessSensitivity": robustness_sensitivity}
                if robustness_sensitivity is not None
                else {}
            ),
            **(
                {
                    "datasetContext": {
                        "symbol": runtime.symbol,
                        "interval": runtime.interval.value,
                        "periodsPerYear": runtime.periods_per_year,
                        "range": {
                            "start": runtime.coverage_start_utc.isoformat(),
                            "end": runtime.coverage_end_utc.isoformat(),
                        },
                        "runtimeDescriptorDigest": runtime.descriptor_digest,
                        "sealedSplitDigest": runtime_split.seal_digest,
                    }
                }
                if is_market_runtime
                else {}
            ),
            "generalization": _generalization_projection(
                report_artifact.content.get("generalization")
            ),
            "walkForward": _walk_forward_projection(report_artifact.content.get("walk_forward")),
            "datasetQuality": _dataset_quality_projection(
                report_artifact.content.get("dataset", {}).get("data_quality")
                if isinstance(report_artifact.content.get("dataset"), dict)
                else None
            )
            if not is_market_runtime
            else (
                {
                    "status": market_record.quality.status,
                    "cadenceGapCount": market_record.quality.cadence_gap_count,
                    "normalizationNote": market_record.quality.normalization_note,
                }
            ),
            "disclaimer": (
                "Imported-data results are not investment advice or evidence of future performance."
                if dataset_record is not None or market_record is not None
                else "Synthetic results are not investment advice or evidence of future "
                "performance."
            ),
        }
        if report_artifact is not None
        else None
    )
    snapshot["composerLegalCommands"] = (
        []
        if is_market_runtime
        else (["start_auto_research"] if state in {"completed", "failed", "cancelled"} else [])
    )
    return snapshot
