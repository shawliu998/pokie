"""Server-owned Phase 0 workspace fixtures for the Mac projection.

The selector is process configuration used by local development/E2E only.  It
is never accepted from an HTTP request and is never rendered as a UI control.
All values are synthetic demonstration records; no provider, model, backtest,
broker, network, or code-execution path is involved.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from sqlalchemy import select

from packages.contracts.enums import DataAuthenticity
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context


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
        "quant-running": ("running_experiments", "experiments", ["cancel_run"], "Fixture experiments are being recorded."),
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


def apply_fixture_command(
    *, workspace_id: str, command: str, expected_row_version: int
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
        snapshot = quant_workspace_fixture(current_name)
        if expected_row_version != current_version:
            raise ValueError("The fixture snapshot row version is stale.")
        legal = snapshot["run"]["legalCommands"] + snapshot["composerLegalCommands"]
        if command not in legal:
            raise ValueError("The command is not legal for the current API fixture snapshot.")
        next_name = {
            "ask": current_name,
            "generate_plan": "quant-plan-approval",
            "approve_plan": "quant-running",
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
                fixture_row_version=current_version,
                data_authenticity=DataAuthenticity.GENERATED.value,
            )
            db.add(row)
        row.fixture_state = next_name
        row.fixture_row_version = current_version + 1
        row.row_version += 1
        db.commit()
        return quant_workspace_fixture(
            next_name, fixture_row_version=current_version + 1
        )


def quant_workspace_fixture(
    raw_state: str | None = None,
    *,
    workspace_id: str | None = None,
    fixture_row_version: int | None = None,
) -> dict[str, Any]:
    stored: tuple[str, int] | None = None
    if workspace_id is not None and raw_state is None:
        with get_session_factory()() as db:
            set_rls_context(db, workspace_id, "quant-fixture-api")
            row = db.get(QuantRepositoryState, workspace_id)
            if row is not None and row.fixture_state:
                stored = (row.fixture_state, row.fixture_row_version)
    fixture_name = raw_state or (
        stored[0] if stored else os.environ.get(FIXTURE_ENV, DEFAULT_FIXTURE)
    )
    if fixture_name not in FIXTURE_STATES:
        allowed = ", ".join(sorted(FIXTURE_STATES))
        raise ValueError(f"{FIXTURE_ENV} must be one of: {allowed}")
    state, current_step, legal_commands, status_summary = _state_config(fixture_name)
    no_viable = fixture_name == "quant-no-viable-candidate"
    candidates = [
        {
            "id": "candidate-a", "name": "Candidate A · SMA 20/100", "parameters": "fast=20 · slow=100",
            "verdict": "rejected", "verdictReason": "Parameter sensitivity",
            "metrics": {"annualizedReturn": 9.6, "maxDrawdown": -24.8, "sharpe": 0.83, "trades": 38},
            "strategySpecVersion": "strategy-fixture-v1", "strategySpec": "family: sma_cross\nfast_window: 20\nslow_window: 100\nposition: long_or_cash",
            "robustness": ["Fails adjacent-window sensitivity check", "Synthetic values only"],
        },
        {
            "id": "candidate-b", "name": "Candidate B · SMA 50/200", "parameters": "fast=50 · slow=200",
            "verdict": "rejected" if no_viable else "promising",
            "verdictReason": "Failed configured validation" if no_viable else "Candidate for paper evaluation",
            "metrics": {"annualizedReturn": 8.9, "maxDrawdown": -18.7, "sharpe": 0.88, "trades": 18},
            "strategySpecVersion": "strategy-fixture-v1", "strategySpec": "family: sma_cross\nfast_window: 50\nslow_window: 200\nposition: long_or_cash",
            "robustness": ["One candidate-scoped repair retained", "Synthetic values only"],
        },
        {
            "id": "candidate-c", "name": "Candidate C · 200-day trend filter", "parameters": "window=200",
            "verdict": "rejected" if no_viable else "inconclusive",
            "verdictReason": "Failed configured validation" if no_viable else "Too few independent trade periods",
            "metrics": {"annualizedReturn": 9.3, "maxDrawdown": -21.4, "sharpe": 0.86, "trades": 12},
            "strategySpecVersion": "strategy-fixture-v1", "strategySpec": "family: trend_filter\nwindow: 200\nposition: long_or_cash",
            "robustness": ["Insufficient independent periods", "Synthetic values only"],
        },
    ]
    conclusion = (
        "No candidate passed validation; the research process still completed normally."
        if no_viable
        else "Candidate B has the strongest fixture profile; Candidate A is rejected and Candidate C is inconclusive."
    )
    events = [
        (1, "run.created", "system", "Research attempt created from a synthetic fixture."),
        (2, "data.load.completed", "system", "Pinned synthetic SPY fixture snapshot loaded."),
        (3, "backtest.failed", "system", "Candidate B fixture experiment stopped safely; the run did not fail."),
        (4, "repair.completed", "system", "Candidate B fixture repair completed within the approved limit."),
        (5, "candidate.rejected", "validator", "Candidate A rejected; candidate verdict is independent of run health."),
        (6, "validation.completed", "validator", "Synthetic robustness validation completed."),
        (7, "report.generated", "agent", "Research Report generated from persisted synthetic fixture records."),
    ]
    terminal_type = "run.failed" if state == "failed" else "run.cancelled" if state == "cancelled" else "run.completed"
    events.append((8, terminal_type, "system", status_summary))
    snapshot: dict[str, Any] = {
        "workspaceName": "PokieQuant Research", "version": "Phase 0 · server-fixture-v1",
        "authenticity": "synthetic_fixture", "runtimeLabel": "Deterministic fixture", "modelLabel": "Not connected",
        "project": {"id": "55555555-5555-4555-8555-555555555501", "title": "SPY · Trend Research", "goal": "Evaluate bounded SPY trend hypotheses with synthetic evidence.", "symbol": "SPY", "updatedAt": "2026-07-17T02:24:00Z", "statusLabel": status_summary, "needsAction": state.startswith("waiting_")},
        "recentProjects": [],
        "scope": {"version": 1, "symbol": "SPY", "market": "US Equity", "interval": "1D", "dateRange": {"start": "2018-01-02", "end": "2023-12-29"}, "benchmark": "SPY Buy and Hold", "assumptions": ["Synthetic demonstration values", "No network retrieval", "No executable strategy code"]},
        "run": {"id": "55555555-5555-4555-8555-555555555502", "rowVersion": fixture_row_version if fixture_row_version is not None else stored[1] if stored else 8, "attemptNumber": 1, "state": state, "mode": "auto_research", "currentStepId": current_step, "latestSequence": 8, "startedAt": "2026-07-17T02:18:00Z", "completedAt": "2026-07-17T02:24:00Z" if state in {"completed", "failed", "cancelled"} else None, "usedExperiments": 3, "usedRepairAttempts": 1, "legalCommands": legal_commands, "traceRef": "fixture-trace-spy-01"},
        "limits": {"maxExperiments": 3, "maxRepairAttempts": 2, "maxRuntimeMinutes": 5, "internetAccess": False, "arbitraryPython": False, "paperTrading": False},
        "plan": _plan(current_step, state),
        "events": [{"id": f"fixture-event-{sequence}", "sequence": sequence, "type": event_type, "timestamp": f"2026-07-17T02:{18 + sequence:02d}:00Z", "actor": actor, "safeSummary": summary} for sequence, event_type, actor, summary in events],
        "artifacts": [
            {"id": "fixture-dataset", "type": "dataset_snapshot", "title": "SPY Daily Synthetic Snapshot", "summary": "Bounded synthetic OHLCV demonstration values.", "status": "ready", "origin": "Server fixture repository", "authenticity": "synthetic_fixture", "relatedLabel": "SPY · 1D", "digest": "sha256:fixture-dataset-a120"},
            {"id": "fixture-validation", "type": "validation_report", "title": "Synthetic Robustness Validation", "summary": "Candidate-scoped fixture verdicts.", "status": "ready", "origin": "Deterministic validator fixture", "authenticity": "synthetic_fixture", "relatedLabel": "3 candidates", "digest": "sha256:fixture-validation-5b20"},
            {"id": "fixture-report", "type": "research_report", "title": "SPY Synthetic Research Report", "summary": conclusion, "status": "reviewed" if state == "completed" else "ready", "origin": "Server fixture projection", "authenticity": "synthetic_fixture", "relatedLabel": "Attempt 1", "digest": "sha256:fixture-report-4e91"},
        ],
        "dataset": {"id": "fixture-spy-daily-v1", "name": "SPY Daily Synthetic Fixture 2018–2023", "symbol": "SPY", "interval": "1D", "dateRange": {"start": "2018-01-02", "end": "2023-12-29"}, "barCount": 4, "schemaVersion": "market-bars-fixture-v1", "parserVersion": "fixture-parser-v1", "digest": "sha256:fixture-dataset-a120", "authenticity": "synthetic_fixture"},
        "bars": [{"date": "2018-01-02", "open": 100, "high": 104, "low": 98, "close": 103, "volume": 1000}, {"date": "2019-01-02", "open": 103, "high": 110, "low": 101, "close": 108, "volume": 1200, "marker": "entry"}, {"date": "2020-01-02", "open": 108, "high": 112, "low": 99, "close": 101, "volume": 1400, "marker": "policy"}, {"date": "2021-01-04", "open": 101, "high": 118, "low": 100, "close": 116, "volume": 1300, "marker": "exit"}],
        "benchmark": {"annualizedReturn": 10.8, "maxDrawdown": -33.7, "sharpe": 0.72, "trades": 1},
        "candidates": candidates,
        "trades": [{"id": "fixture-trade-1", "candidateId": "candidate-b", "entryDate": "2019-01-02", "exitDate": "2021-01-04", "returnPct": 7.4, "holdingDays": 733, "reason": "Synthetic fixture crossover record"}],
        "report": {"id": "fixture-report", "title": "SPY Synthetic Research Report", "conclusion": conclusion, "proposedNextStep": "Review limitations; no broker or paper-trading action is available.", "limitations": ["All values are synthetic demonstration fixtures.", "No real backtest or market-data retrieval occurred.", "This is not investment advice."], "humanReviewStatus": "Fixture review record", "validatorVersion": "validator-fixture-v1", "generationMethod": "Server-owned deterministic fixture projection", "disclaimer": "Demonstration results are synthetic and are not investment advice, a recommendation, or evidence of future performance."},
        "composerLegalCommands": ["ask", "generate_plan"] if fixture_name == "quant-ready" else [],
    }
    snapshot["recentProjects"] = [deepcopy(snapshot["project"])]
    return snapshot
