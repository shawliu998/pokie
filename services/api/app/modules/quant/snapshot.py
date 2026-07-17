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
from datetime import date
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
DEFAULT_FIXTURE = "quant-ready"
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
        build_quant_kernel_check() if results_visible else build_quant_kernel_capability()
    )
    dataset = SPY_DAILY_FIXTURE
    dataset_start = dataset.covered_start.isoformat()
    dataset_end = dataset.covered_end.isoformat()
    no_viable = fixture_name == "quant-no-viable-candidate"
    research = build_quant_research_projection(no_viable=no_viable) if results_visible else None
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
        "workspaceName": "PokieQuant Research",
        "version": "Phase 0 · server-fixture-v1",
        "authenticity": "synthetic_fixture",
        "runtimeLabel": "Incremental local Agent",
        "modelLabel": "Mock Agent",
        "project": {
            "id": "55555555-5555-4555-8555-555555555501",
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


def quant_agent_workspace_snapshot(*, workspace_id: str) -> dict[str, Any] | None:
    """Project the latest durable autonomous run into the existing Mac view model."""

    from services.api.app.modules.quant.store import QuantStore

    store = QuantStore()
    runs = store.list_runs(workspace_id=workspace_id)
    if not runs:
        return None
    run = runs[0]
    project = store.get_project(workspace_id=workspace_id, project_id=run.project_id)
    dataset = store.dataset_for_run(run)
    dataset_record = store.get_dataset(
        workspace_id=workspace_id, dataset_id=dataset.dataset_id
    )
    dataset_name = (
        dataset_record.name
        if dataset_record is not None
        else "SPY Daily Synthetic Weekday Fixture · 2018–2023"
    )
    dataset_authenticity = dataset.provenance.value
    snapshot = quant_workspace_fixture("quant-ready")
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
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

    if state == "waiting_plan_approval":
        legal_commands = ["approve_plan", "request_plan_changes", "cancel_run"]
    elif state not in {"completed", "failed", "cancelled"}:
        legal_commands = ["cancel_run"]
    else:
        legal_commands = ["retry_run"]

    def event_actor(event_type: str) -> str:
        if event_type.startswith("agent.") or event_type.startswith("candidate."):
            return "agent"
        return "system"

    snapshot["workspaceName"] = "PokieQuant Research"
    snapshot["version"] = "Phase 1A · autonomous-agent-v1"
    snapshot["runtimeLabel"] = "Incremental local Agent"
    snapshot["modelLabel"] = "Mock Agent" if run.provider == "mock" else run.model or "DeepSeek"
    snapshot["project"] = {
        "id": project.id,
        "title": project.name,
        "goal": run.question,
        "symbol": dataset.symbol,
        "updatedAt": run.updated_at.isoformat(),
        "statusLabel": run.agent_status.replace("_", " ").title(),
        "needsAction": state == "waiting_plan_approval",
    }
    snapshot["recentProjects"] = [deepcopy(snapshot["project"])]
    snapshot["authenticity"] = dataset_authenticity
    snapshot["scope"] = {
        **snapshot["scope"],
        "symbol": dataset.symbol,
        "interval": dataset.interval.value,
        "dateRange": {
            "start": dataset.covered_start.isoformat(),
            "end": dataset.covered_end.isoformat(),
        },
        "benchmark": f"{dataset.symbol} Buy and Hold",
        "assumptions": [
            f"{len(dataset.bars):,} pinned daily OHLCV bars",
            "10 bps fee and 5 bps slippage per fill",
            "No network retrieval; only fixed typed strategy specifications",
        ],
    }
    snapshot["dataset"] = {
        "id": dataset.dataset_id,
        "name": dataset_name,
        "symbol": dataset.symbol,
        "interval": dataset.interval.value,
        "dateRange": {
            "start": dataset.covered_start.isoformat(),
            "end": dataset.covered_end.isoformat(),
        },
        "barCount": len(dataset.bars),
        "schemaVersion": dataset.schema_version,
        "parserVersion": (
            dataset_record.parser_version
            if dataset_record is not None
            else "deterministic-weekday-generator-v2"
        ),
        "digest": dataset.digest,
        "authenticity": dataset_authenticity,
    }
    snapshot["bars"] = _chart_sample(dataset, [])
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
    }
    snapshot["limits"] = {
        **snapshot["limits"],
        "maxExperiments": run.max_experiments,
        "maxRepairAttempts": run.max_repairs,
    }
    snapshot["events"] = [
        {
            "id": item["event_id"],
            "sequence": item["sequence"],
            "type": item["event_type"],
            "timestamp": item["timestamp"].isoformat(),
            "actor": event_actor(item["event_type"]),
            "safeSummary": item["payload"].get("safe_summary", "Agent activity recorded."),
            **(
                {"artifactId": item["payload"]["artifact_id"]}
                if item["payload"].get("artifact_id")
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
                {"artifactIds": item["payload"]["artifact_ids"]}
                if item["payload"].get("artifact_ids")
                else {}
            ),
        }
        for item in event_rows
    ]
    artifact_type = {
        "plan": "execution_log",
        "research_scope": "research_scope",
        "dataset_snapshot": "dataset_snapshot",
        "benchmark": "backtest_result",
        "strategy_spec": "strategy_spec",
        "backtest_result": "backtest_result",
        "backtest_metrics": "backtest_result",
        "equity_curve": "equity_curve",
        "trade_log": "trade_log",
        "validation_report": "validation_report",
        "research_report": "research_report",
        "execution_log": "execution_log",
        "diagnostics": "execution_log",
    }
    snapshot["artifacts"] = [
        {
            "id": item.id,
            "type": artifact_type[item.kind.value],
            "title": item.title,
            "summary": item.content.get("conclusion", item.title),
            "status": "ready",
            "origin": "Autonomous local Agent",
            "authenticity": dataset_authenticity,
            "relatedLabel": f"Run {run.attempt_number}",
            "digest": item.digest,
        }
        for item in artifacts
    ]
    verdict_map = {"viable": "promising", "not_viable": "inconclusive", "rejected": "rejected"}
    snapshot["candidates"] = [
        {
            "id": item.id,
            "name": item.name,
            "parameters": " · ".join(f"{key}={value}" for key, value in item.parameters.items()),
            "verdict": verdict_map[item.verdict.value],
            "verdictReason": item.summary,
            "metrics": {
                "annualizedReturn": item.metrics.get("annualized_return_pct", 0),
                "maxDrawdown": item.metrics.get("maximum_drawdown_pct", 0),
                "sharpe": item.metrics.get("sharpe_ratio", 0),
                "trades": item.metrics.get("trade_count", 0),
            },
            "strategySpecVersion": "daily-bar-kernel-v1",
            "strategySpec": f"template: {item.template}\nparameters: {item.parameters}",
            "robustness": [item.latest_observation or "Backtest pending."],
        }
        for item in experiments
        if item.template != "fixture"
    ]
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
        "engineVersion": "daily-bar-kernel-v1",
        "datasetId": dataset.dataset_id,
        "datasetDigest": dataset.digest,
        "barCount": len(dataset.bars),
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
                "Workspace-imported bars were not independently verified against a market "
                "data provider."
                if dataset_record is not None
                else "The deterministic synthetic bars are not market observations."
            ),
            "No statistical significance or live execution was evaluated.",
            "No network, broker, or arbitrary code execution is available.",
        ],
    }
    snapshot["benchmark"] = {
        "annualizedReturn": context["benchmark_summary"]["annualized_return_pct"],
        "maxDrawdown": context["benchmark_summary"]["maximum_drawdown_pct"],
        "sharpe": context["benchmark_summary"]["sharpe_ratio"],
        "trades": context["benchmark_summary"]["trade_count"],
    }
    report_artifact = next(
        (item for item in artifacts if item.kind.value == "research_report"), None
    )
    selected_candidate_id = (
        report_artifact.content.get("selected_candidate_id")
        if report_artifact is not None
        else None
    )
    trade_artifact = next(
        (
            item
            for item in artifacts
            if item.kind.value == "trade_log"
            and item.content.get("candidate_id") == selected_candidate_id
        ),
        None,
    )
    if trade_artifact is None or not trade_artifact.content.get("trades"):
        trade_artifact = next(
            (
                item
                for item in artifacts
                if item.kind.value == "trade_log" and item.content.get("trades")
            ),
            None,
        )
        if trade_artifact is not None:
            selected_candidate_id = trade_artifact.content.get("candidate_id")
    selected_trades = trade_artifact.content.get("trades", []) if trade_artifact else []
    snapshot["trades"] = [
        {
            "id": f"{trade_artifact.id}:{index}" if trade_artifact else f"trade:{index}",
            "candidateId": selected_candidate_id,
            "entryDate": item["entry_date"],
            "exitDate": item["exit_date"],
            "returnPct": item["return_pct"],
            "holdingDays": max(
                0,
                (
                    date.fromisoformat(item["exit_date"])
                    - date.fromisoformat(item["entry_date"])
                ).days,
            ),
            "reason": "Persisted local backtest trade.",
        }
        for index, item in enumerate(selected_trades, start=1)
    ]
    snapshot["bars"] = _chart_sample(dataset, snapshot["trades"])
    snapshot["report"] = (
        {
            "id": report_artifact.id,
            "title": report_artifact.title,
            "conclusion": report_artifact.content.get("conclusion", run.final_conclusion or ""),
            "proposedNextStep": report_artifact.content.get("next_step", "stop").replace("_", " "),
            "limitations": report_artifact.content.get("limitations", []),
            "humanReviewStatus": "Agent report retained",
            "validatorVersion": "daily-bar-kernel-v1",
            "generationMethod": "Autonomous Agent over deterministic local tools",
            "disclaimer": (
                "Imported-data results are not investment advice or evidence of future "
                "performance."
                if dataset_record is not None
                else "Synthetic results are not investment advice or evidence of future "
                "performance."
            ),
        }
        if report_artifact is not None
        else None
    )
    snapshot["composerLegalCommands"] = (
        ["start_auto_research"]
        if state in {"completed", "failed", "cancelled"}
        else []
    )
    return snapshot
