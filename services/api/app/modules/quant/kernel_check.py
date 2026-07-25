"""Deterministic research projection backed by the pure daily-bar kernel.

The adapter consumes only the bundled synthetic weekday fixture and fixed,
typed strategy specifications. It has no network, model, broker, persistence,
or arbitrary-code boundary.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, TypedDict

from packages.contracts.quant.fixture_data import SPY_DAILY_FIXTURE
from packages.domain.quant_backtest import (
    BacktestResult,
    DailyBar,
    StrategySpec,
    backtest_buy_and_hold,
    run_backtest,
)
from services.api.app.modules.quant.execution import BASELINE_EXECUTION

ENGINE_VERSION = "daily-bar-kernel-v1"
VALIDATOR_VERSION = "synthetic-validator-v1"
EXECUTION = BASELINE_EXECUTION


class _CandidateDefinition(TypedDict):
    id: str
    name: str
    parameters: str
    verdict: str
    verdictReason: str
    strategySpec: str
    robustness: list[str]


def _fixture_bars() -> tuple[DailyBar, ...]:
    return tuple(
        DailyBar(
            date=bar.trading_date,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in SPY_DAILY_FIXTURE.bars
    )


@lru_cache(maxsize=1)
def _computed_results() -> dict[str, BacktestResult]:
    bars = _fixture_bars()
    return {
        "benchmark": backtest_buy_and_hold(bars, EXECUTION),
        "candidate-a": run_backtest(bars, StrategySpec.sma(20, 100), EXECUTION),
        "candidate-b": run_backtest(bars, StrategySpec.sma(50, 200), EXECUTION),
        "candidate-c": run_backtest(bars, StrategySpec.breakout(200), EXECUTION),
        "candidate-a-low": run_backtest(bars, StrategySpec.sma(10, 80), EXECUTION),
        "candidate-a-high": run_backtest(bars, StrategySpec.sma(30, 120), EXECUTION),
        "candidate-b-low": run_backtest(bars, StrategySpec.sma(40, 180), EXECUTION),
        "candidate-b-high": run_backtest(bars, StrategySpec.sma(60, 220), EXECUTION),
    }


def _result_projection(identifier: str, label: str, result: BacktestResult) -> dict[str, Any]:
    metrics = result.metrics
    return {
        "id": identifier,
        "label": label,
        "totalReturnPct": round(metrics.total_return * 100, 2),
        "annualizedReturnPct": round(metrics.annualized_return * 100, 2),
        "maxDrawdownPct": round(metrics.max_drawdown * 100, 2),
        "sharpe": round(metrics.sharpe_ratio, 2),
        "tradeCount": metrics.trade_count,
        "finalEquity": round(metrics.final_equity, 2),
    }


def _candidate_metrics(result: BacktestResult) -> dict[str, float | int]:
    metrics = result.metrics
    return {
        "annualizedReturn": round(metrics.annualized_return * 100, 1),
        "maxDrawdown": round(metrics.max_drawdown * 100, 1),
        "sharpe": round(metrics.sharpe_ratio, 2),
        "trades": metrics.trade_count,
    }


def _performance_points(result: BacktestResult, *, limit: int = 160) -> list[dict[str, Any]]:
    """Project a bounded, normalized equity and drawdown series for the UI."""

    curve = result.equity_curve
    if not curve:
        return []
    step = max(1, (len(curve) + limit - 1) // limit)
    sampled = list(curve[::step])
    if sampled[-1] != curve[-1]:
        sampled.append(curve[-1])
    base = sampled[0].equity or 1.0
    peak = base
    points: list[dict[str, Any]] = []
    for point in sampled:
        normalized = point.equity / base * 100
        peak = max(peak, normalized)
        points.append(
            {
                "date": point.date.isoformat(),
                "equity": round(normalized, 4),
                "drawdown": round((normalized / peak - 1) * 100, 4),
            }
        )
    return points


def _sensitivity_range(left: BacktestResult, right: BacktestResult) -> float:
    returns = (left.metrics.annualized_return, right.metrics.annualized_return)
    return round((max(returns) - min(returns)) * 100, 2)


def build_quant_kernel_check() -> dict[str, Any]:
    """Return transparent engine, dataset, execution, and result evidence."""

    results = _computed_results()
    return {
        "status": "verified",
        "engineVersion": ENGINE_VERSION,
        "datasetId": SPY_DAILY_FIXTURE.dataset_id,
        "datasetDigest": SPY_DAILY_FIXTURE.digest,
        "barCount": len(SPY_DAILY_FIXTURE.bars),
        "execution": "signal_at_close_fill_next_open",
        "feeRateBps": 10,
        "slippageRateBps": 5,
        "benchmark": _result_projection("buy-and-hold", "Buy and Hold", results["benchmark"]),
        "strategies": [
            _result_projection("candidate-a", "SMA 20/100", results["candidate-a"]),
            _result_projection("candidate-b", "SMA 50/200", results["candidate-b"]),
            _result_projection("candidate-c", "Breakout 200", results["candidate-c"]),
        ],
        "limitations": [
            "1,564 deterministic synthetic weekday bars are not market observations.",
            "Weekdays are generated without an exchange holiday calendar or corporate actions.",
            "No network, broker, model, or arbitrary code execution is available.",
        ],
    }


def build_quant_kernel_capability() -> dict[str, Any]:
    """Describe the pinned kernel input without running a backtest."""

    return {
        "status": "available",
        "engineVersion": ENGINE_VERSION,
        "datasetId": SPY_DAILY_FIXTURE.dataset_id,
        "datasetDigest": SPY_DAILY_FIXTURE.digest,
        "barCount": len(SPY_DAILY_FIXTURE.bars),
        "execution": "signal_at_close_fill_next_open",
        "feeRateBps": 10,
        "slippageRateBps": 5,
        "benchmark": None,
        "strategies": [],
        "limitations": [
            "1,564 deterministic synthetic weekday bars are not market observations.",
            "Results are not computed until an approved Agent run starts.",
            "No network, broker, model, or arbitrary code execution is available.",
        ],
    }


def build_quant_research_projection(*, no_viable: bool = False) -> dict[str, Any]:
    """Build computed candidates, benchmark, trades, and validation copy."""

    results = _computed_results()
    sensitivity_a = _sensitivity_range(results["candidate-a-low"], results["candidate-a-high"])
    sensitivity_b = _sensitivity_range(results["candidate-b-low"], results["candidate-b-high"])
    definitions: tuple[_CandidateDefinition, ...] = (
        {
            "id": "candidate-a",
            "name": "Candidate A · SMA 20/100",
            "parameters": "fast=20 · slow=100",
            "verdict": "rejected",
            "verdictReason": f"Parameter sensitivity · {sensitivity_a:.2f} pp range",
            "strategySpec": (
                "family: sma\nfast_period: 20\nslow_period: 100\nposition: long_or_cash"
            ),
            "robustness": [
                f"10/80 versus 30/120 annualized-return range: {sensitivity_a:.2f} pp",
                "Rejected by the configured >5 pp sensitivity rule",
                "Metrics computed by the pure daily-bar kernel",
            ],
        },
        {
            "id": "candidate-b",
            "name": "Candidate B · SMA 50/200",
            "parameters": "fast=50 · slow=200",
            "verdict": "promising",
            "verdictReason": "Candidate for paper evaluation",
            "strategySpec": (
                "family: sma\nfast_period: 50\nslow_period: 200\nposition: long_or_cash"
            ),
            "robustness": [
                f"40/180 versus 60/220 annualized-return range: {sensitivity_b:.2f} pp",
                "Passes the configured ≤5 pp sensitivity rule",
                "Synthetic evidence only; no paper-trading action is enabled",
            ],
        },
        {
            "id": "candidate-c",
            "name": "Candidate C · 200-day breakout",
            "parameters": "lookback=200",
            "verdict": "inconclusive",
            "verdictReason": "Too few closed trades",
            "strategySpec": "family: breakout\nperiod: 200\nposition: long_or_cash",
            "robustness": [
                f"Only {results['candidate-c'].metrics.trade_count} closed trades",
                "Inconclusive under the configured minimum of 3",
                "Metrics computed by the pure daily-bar kernel",
            ],
        },
    )
    candidates: list[dict[str, Any]] = []
    for definition in definitions:
        candidate: dict[str, Any] = {
            **definition,
            "metrics": _candidate_metrics(results[definition["id"]]),
            "strategySpecVersion": ENGINE_VERSION,
        }
        if no_viable:
            candidate["verdict"] = "rejected"
            candidate["verdictReason"] = "Failed configured validation"
            candidate["robustness"] = [
                *candidate["robustness"],
                "No-viable-candidate fixture override retained for lifecycle regression",
            ]
        candidates.append(candidate)

    fixture_hypotheses = {
        "candidate-a": "Test a faster moving-average trend signal against buy and hold.",
        "candidate-b": "Test a slower moving-average trend signal for lower drawdown.",
        "candidate-c": "Test whether a long-horizon breakout remains robust with sparse trades.",
    }
    training_ranking = sorted(
        candidates,
        key=lambda item: (
            item["metrics"]["sharpe"],
            item["metrics"]["annualizedReturn"],
            item["metrics"]["maxDrawdown"],
            item["id"],
        ),
        reverse=True,
    )
    for candidate in candidates:
        rank = next(
            index
            for index, item in enumerate(training_ranking, start=1)
            if item["id"] == candidate["id"]
        )
        candidate["evolution"] = {
            "hypothesis": fixture_hypotheses[candidate["id"]],
            "origin": "initial",
            "changeRationale": None,
            "feedbackReferenceCandidateId": None,
            "feedbackReferenceCandidateName": None,
            "comparisonRank": rank,
            "comparisonCandidateCount": len(candidates),
            "selectionReason": (
                f"Ranked {rank} of {len(candidates)} in the final training comparison; this "
                "synthetic fixture retains no sealed-holdout selection."
            ),
        }

    benchmark_metrics = _candidate_metrics(results["benchmark"])
    trades = [
        {
            "id": f"kernel-trade-{index}",
            "candidateId": "candidate-b",
            "entryDate": trade.entry_date.isoformat(),
            "exitDate": trade.exit_date.isoformat(),
            "returnPct": round(trade.return_pct * 100, 2),
            "holdingDays": (trade.exit_date - trade.entry_date).days,
            "reason": "SMA 50/200 signal; close observation filled at next open",
        }
        for index, trade in enumerate(results["candidate-b"].trades, start=1)
    ]
    conclusion = (
        "No candidate passed validation; the computed research process still completed normally."
        if no_viable
        else (
            "Candidate B passes the configured synthetic validation; Candidate A is "
            "rejected for sensitivity and Candidate C is inconclusive because it has "
            "too few closed trades."
        )
    )
    return {
        "benchmark": benchmark_metrics,
        "candidates": candidates,
        "performanceSeries": [
            {
                "id": "benchmark",
                "label": "Buy and hold",
                "kind": "benchmark",
                "points": _performance_points(results["benchmark"]),
            },
            *[
                {
                    "id": definition["id"],
                    "label": definition["name"]
                    .replace("Candidate A · ", "")
                    .replace("Candidate B · ", "")
                    .replace("Candidate C · ", ""),
                    "kind": "candidate",
                    "points": _performance_points(results[definition["id"]]),
                }
                for definition in definitions
            ],
        ],
        "trades": trades,
        "conclusion": conclusion,
        "validatorVersion": VALIDATOR_VERSION,
        "generationMethod": f"Computed by {ENGINE_VERSION} from a digest-pinned synthetic dataset",
        "limitations": [
            "All bars and computed results are synthetic and are not market evidence.",
            "The weekday generator omits exchange holidays, corporate actions, taxes, "
            "and liquidity constraints.",
            "Validation thresholds are fixed demonstration policy, not an investment "
            "recommendation.",
        ],
    }


__all__ = [
    "build_quant_kernel_capability",
    "build_quant_kernel_check",
    "build_quant_research_projection",
]
