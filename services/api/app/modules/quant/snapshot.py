"""Server-owned Phase 0 workspace fixtures for the Mac projection.

The selector is process configuration used by local development/E2E only.  It
is never accepted from an HTTP request and is never rendered as a UI control.
All values are synthetic demonstration records. A bounded pure daily-bar
kernel computes candidate metrics, trades, and report evidence locally; no
provider, model, broker, network, or arbitrary code-execution path is involved.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from sqlalchemy import select

from packages.contracts.enums import DataAuthenticity
from packages.contracts.quant.data import QuantDailyBarDataset
from packages.contracts.quant.fixture_data import SPY_DAILY_FIXTURE
from packages.domain.canonical import canonical_digest
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context
from services.api.app.modules.quant.kernel_check import (
    build_quant_kernel_capability,
    build_quant_kernel_check,
    build_quant_research_projection,
)


FIXTURE_ENV = "POKIEQUANT_E2E_RUN_STATE"
DEFAULT_FIXTURE = "quant-completed"
FIXTURE_STATES = frozenset(
    {
        "quant-ready",
        "quant-plan-approval",
        "quant-running",
        "quant-repairing",
        "quant-validating",
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
        "quant-running": ("running_experiments", "experiments", ["run_fixture", "cancel_run"], "The approved synthetic Agent is ready to run."),
        "quant-repairing": ("repairing", "repair", ["cancel_run"], "Candidate B is in a bounded fixture repair."),
        "quant-validating": ("validating", "validation", ["cancel_run"], "Fixture robustness validation is active."),
        "quant-waiting-review": ("waiting_for_review", "decision", ["complete_review"], "The fixture report is waiting for review."),
        "quant-completed": ("completed", "decision", [], "Research process completed."),
        "quant-no-viable-candidate": ("completed", "decision", [], "No candidate passed validation."),
        "quant-failed-safe": ("failed", "experiments", ["retry_run"], "The fixture worker stopped safely."),
        "quant-cancelled": ("cancelled", "experiments", ["retry_run"], "The fixture run was cancelled."),
    }[name]


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
    dataset: QuantDailyBarDataset, trades: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return a bounded chart projection while retaining computed trade markers."""

    last_index = len(dataset.bars) - 1
    indices = {round(position * last_index / 23) for position in range(24)}
    marker_by_date: dict[str, str] = {}
    for trade in trades:
        marker_by_date[trade["entryDate"]] = "entry"
        marker_by_date[trade["exitDate"]] = "exit"
    indices.update(
        index
        for index, bar in enumerate(dataset.bars)
        if bar.trading_date.isoformat() in marker_by_date
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
    results_visible = state in {"validating", "waiting_for_review", "completed"}
    report_visible = state in {"waiting_for_review", "completed"}
    kernel_check = (
        build_quant_kernel_check()
        if results_visible
        else build_quant_kernel_capability()
    )
    dataset = SPY_DAILY_FIXTURE
    dataset_start = dataset.covered_start.isoformat()
    dataset_end = dataset.covered_end.isoformat()
    no_viable = fixture_name == "quant-no-viable-candidate"
    research = (
        build_quant_research_projection(no_viable=no_viable)
        if results_visible
        else None
    )
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
        (3, "backtest.failed", "system", "Candidate B fixture experiment stopped safely; the run did not fail."),
        (4, "repair.completed", "system", "Candidate B fixture repair completed within the approved limit."),
        (5, "candidate.rejected", "validator", "Candidate A rejected; candidate verdict is independent of run health."),
        (6, "validation.completed", "validator", "Synthetic robustness validation completed."),
        (7, "report.generated", "agent", "Research Report generated from persisted synthetic fixture records."),
    ]
    progress_event_count = {
        "draft": 1,
        "waiting_plan_approval": 1,
        "running_experiments": 2,
        "repairing": 4,
        "validating": 6,
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
        {"id": "fixture-dataset", "type": "dataset_snapshot", "title": "SPY Daily Synthetic Snapshot", "summary": "1,564 deterministic weekday OHLCV rows used by the pure research kernel.", "status": "ready", "origin": "Server fixture repository", "authenticity": "synthetic_fixture", "relatedLabel": "SPY · 1D · synthetic weekdays", "digest": dataset.digest},
    ]
    if results_visible:
        assert research is not None and validation_digest is not None
        visible_artifacts.append(
            {"id": "fixture-validation", "type": "validation_report", "title": "Synthetic Robustness Validation", "summary": "Computed candidate metrics with fixed sensitivity and trade-count rules.", "status": "ready", "origin": research["generationMethod"], "authenticity": "synthetic_fixture", "relatedLabel": "3 computed candidates", "digest": validation_digest}
        )
    if report_visible:
        assert research is not None and report_digest is not None
        visible_artifacts.append(
            {"id": "fixture-report", "type": "research_report", "title": "SPY Synthetic Research Report", "summary": conclusion, "status": "reviewed" if state == "completed" else "ready", "origin": research["generationMethod"], "authenticity": "synthetic_fixture", "relatedLabel": "Attempt 1", "digest": report_digest}
        )
    snapshot: dict[str, Any] = {
        "workspaceName": "PokieQuant Research", "version": "Phase 0 · server-fixture-v1",
        "authenticity": "synthetic_fixture", "runtimeLabel": "Deterministic fixture", "modelLabel": "Not connected",
        "project": {"id": "55555555-5555-4555-8555-555555555501", "title": "SPY · Trend Research", "goal": research_goal, "symbol": "SPY", "updatedAt": "2026-07-17T02:24:00Z", "statusLabel": status_summary, "needsAction": state.startswith("waiting_")},
        "recentProjects": [],
        "scope": {"version": 1, "symbol": "SPY", "market": "US Equity", "interval": "1D", "dateRange": {"start": dataset_start, "end": dataset_end}, "benchmark": "SPY Buy and Hold", "assumptions": ["1,564 generated synthetic weekday bars; no exchange calendar", "10 bps fee and 5 bps slippage per fill", "No network retrieval; only fixed typed strategy specifications"]},
        "run": {"id": "55555555-5555-4555-8555-555555555502", "rowVersion": fixture_row_version if fixture_row_version is not None else stored[1] if stored else 8, "attemptNumber": 1, "state": state, "mode": "auto_research", "currentStepId": current_step, "latestSequence": events[-1][0], "startedAt": "2026-07-17T02:18:00Z", "completedAt": "2026-07-17T02:24:00Z" if state in {"completed", "failed", "cancelled"} else None, "usedExperiments": 3 if results_visible else 1 if state in {"running_experiments", "repairing"} else 0, "usedRepairAttempts": 1 if state in {"repairing", "validating", "waiting_for_review", "completed"} else 0, "legalCommands": legal_commands, "traceRef": "fixture-trace-spy-01"},
        "limits": {"maxExperiments": 3, "maxRepairAttempts": 2, "maxRuntimeMinutes": 5, "internetAccess": False, "arbitraryPython": False, "paperTrading": False},
        "plan": _plan(current_step, state),
        "events": [{"id": f"fixture-event-{sequence}", "sequence": sequence, "type": event_type, "timestamp": f"2026-07-17T02:{18 + sequence:02d}:00Z", "actor": actor, "safeSummary": summary} for sequence, event_type, actor, summary in events],
        "artifacts": visible_artifacts,
        "dataset": {"id": dataset.dataset_id, "name": "SPY Daily Synthetic Weekday Fixture · 2018–2023", "symbol": dataset.symbol, "interval": dataset.interval.value, "dateRange": {"start": dataset_start, "end": dataset_end}, "barCount": len(dataset.bars), "schemaVersion": dataset.schema_version, "parserVersion": "deterministic-weekday-generator-v2", "digest": dataset.digest, "authenticity": dataset.provenance.value},
        "bars": _chart_sample(dataset, research["trades"] if research is not None else []),
        "kernelCheck": kernel_check,
        "benchmark": research["benchmark"] if research is not None else None,
        "candidates": candidates if results_visible else [],
        "trades": research["trades"] if report_visible and research is not None else [],
        "report": {"id": "fixture-report", "title": "SPY Synthetic Research Report", "conclusion": conclusion, "proposedNextStep": "Review limitations; no broker or paper-trading action is available.", "limitations": research["limitations"], "humanReviewStatus": "Fixture review record", "validatorVersion": research["validatorVersion"], "generationMethod": research["generationMethod"], "disclaimer": "Synthetic results are not investment advice, a recommendation, market evidence, or evidence of future performance."} if report_visible and research is not None else None,
        "composerLegalCommands": ["ask", "generate_plan"] if fixture_name == "quant-ready" else [],
    }
    snapshot["recentProjects"] = [deepcopy(snapshot["project"])]
    return snapshot
