from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.contracts.enums import DataAuthenticity
from packages.contracts.quant import (
    QUANT_OHLCV_CSV_PARSER_VERSION,
    QuantAgentDecision,
    QuantAgentPlan,
    QuantDailyBarDataset,
    QuantToolObservation,
    parse_ohlcv_csv,
)
from packages.contracts.quant.enums import (
    QuantArtifactKind,
    QuantArtifactReviewStatus,
    QuantCandidateVerdict,
    QuantExperimentVerdict,
    QuantFixtureScenario,
    QuantProjectStatus,
    QuantRunMode,
    QuantRunState,
)
from packages.contracts.quant.fixture_data import SPY_DAILY_FIXTURE
from packages.domain.canonical import canonical_digest
from packages.domain.quant_backtest import (
    BacktestMetrics,
    DailyBar,
    ExecutionConfig,
    StrategySpec,
    backtest_buy_and_hold,
    run_backtest,
)
from services.api.app.core.errors import invalid_state, not_found, version_conflict
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context

MIN_AUTONOMOUS_RESEARCH_BARS = 252


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _uuid(label: str, *parts: object) -> UUID:
    return uuid5(
        NAMESPACE_URL, "pokiequant.quant:" + ":".join(str(part) for part in (label, *parts))
    )


def _text(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part is not None).strip()


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _datetime(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


@dataclass(slots=True)
class QuantProjectRecord:
    id: str
    workspace_id: str
    name: str
    objective: str
    status: QuantProjectStatus = QuantProjectStatus.ACTIVE
    latest_run_id: str | None = None
    row_version: int = 1
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED


@dataclass(frozen=True, slots=True)
class QuantDatasetRecord:
    id: str
    workspace_id: str
    name: str
    dataset: QuantDailyBarDataset
    parser_version: str = QUANT_OHLCV_CSV_PARSER_VERSION
    created_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.IMPORTED


@dataclass(slots=True)
class QuantRunRecord:
    id: str
    workspace_id: str
    project_id: str
    question: str
    mode: QuantRunMode
    dataset_id: str = SPY_DAILY_FIXTURE.dataset_id
    dataset_digest: str = SPY_DAILY_FIXTURE.digest
    state: QuantRunState = QuantRunState.QUEUED
    plan_revision: int = 1
    attempt_number: int = 1
    latest_sequence: int = 0
    trace_id: str = field(default_factory=lambda: str(_uuid("trace", "pending")))
    plan_artifact_id: str | None = None
    retry_of_run_id: str | None = None
    plan_summary: str | None = None
    plan_change_request: str | None = None
    approval_reason: str | None = None
    failure_reason: str | None = None
    cancelled_reason: str | None = None
    retry_child_run_id: str | None = None
    agent_iteration: int = 0
    agent_status: str = "idle"
    max_agent_iterations: int = 12
    max_experiments: int = 3
    max_repairs: int = 2
    used_experiments: int = 0
    used_repairs: int = 0
    last_action: str | None = None
    last_observation: str | None = None
    final_conclusion: str | None = None
    provider: str = "mock"
    model: str | None = None
    consecutive_provider_failures: int = 0
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    row_version: int = 1
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED


@dataclass(slots=True)
class QuantEventRecord:
    id: str
    workspace_id: str
    run_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    trace_id: str
    occurred_at: datetime
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED

    def to_contract(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_id": self.id,
            "event_type": self.event_type,
            "payload": self.payload,
            "trace_id": self.trace_id,
            "timestamp": self.occurred_at,
            "data_authenticity": self.data_authenticity,
        }


@dataclass(slots=True)
class QuantArtifactRecord:
    id: str
    workspace_id: str
    run_id: str
    ordinal: int
    kind: QuantArtifactKind
    title: str
    digest: str
    review_status: QuantArtifactReviewStatus = QuantArtifactReviewStatus.UNREVIEWED
    content: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED


@dataclass(slots=True)
class QuantExperimentRecord:
    id: str
    workspace_id: str
    run_id: str
    ordinal: int
    name: str
    hypothesis: str
    verdict: QuantExperimentVerdict
    summary: str
    template: str = "fixture"
    parameters: dict[str, Any] = field(default_factory=dict)
    state: str = "completed"
    metrics: dict[str, Any] = field(default_factory=dict)
    repair_count: int = 0
    candidate_key: str | None = None
    parent_experiment_id: str | None = None
    latest_observation: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED


@dataclass(frozen=True, slots=True)
class QuantFixtureLease:
    workspace_id: str
    run_id: str
    token: str
    fencing_version: int
    expires_at: datetime


class QuantStore:
    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._lock = RLock()
        self._session_factory = session_factory or get_session_factory()
        self._loaded_workspaces: set[str] = set()
        self._storage_versions: dict[str, int] = {}
        self._datasets: dict[tuple[str, str], QuantDatasetRecord] = {}
        self._projects: dict[str, QuantProjectRecord] = {}
        self._runs: dict[str, QuantRunRecord] = {}
        self._events: dict[str, list[QuantEventRecord]] = {}
        self._artifacts: dict[str, QuantArtifactRecord] = {}
        self._experiments: dict[str, QuantExperimentRecord] = {}

    def clear(self) -> None:
        with self._lock:
            self._projects.clear()
            self._datasets.clear()
            self._runs.clear()
            self._events.clear()
            self._artifacts.clear()
            self._experiments.clear()
            self._loaded_workspaces.clear()
            self._storage_versions.clear()

    def _ensure_workspace_loaded(self, workspace_id: str) -> None:
        if workspace_id in self._loaded_workspaces:
            return
        with self._session_factory() as db:
            set_rls_context(db, workspace_id, "quant-repository")
            row = db.get(QuantRepositoryState, workspace_id)
            if row is not None:
                self._restore_workspace(workspace_id, row.state_json or {})
                self._storage_versions[workspace_id] = row.row_version
            else:
                self._storage_versions[workspace_id] = 0
        self._loaded_workspaces.add(workspace_id)

    def _restore_workspace(self, workspace_id: str, state: dict[str, Any]) -> None:
        self._datasets.update(
            {
                (workspace_id, item["id"]): QuantDatasetRecord(
                    **{
                        **item,
                        "dataset": QuantDailyBarDataset.model_validate(item["dataset"]),
                        "created_at": _datetime(item["created_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    }
                )
                for item in state.get("datasets", [])
                if item.get("workspace_id") == workspace_id
            }
        )
        self._projects.update(
            {
                item["id"]: QuantProjectRecord(
                    **{
                        **item,
                        "status": QuantProjectStatus(item["status"]),
                        "created_at": _datetime(item["created_at"]),
                        "updated_at": _datetime(item["updated_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    }
                )
                for item in state.get("projects", [])
                if item.get("workspace_id") == workspace_id
            }
        )
        self._runs.update(
            {
                item["id"]: QuantRunRecord(
                    **{
                        **item,
                        "mode": QuantRunMode(item["mode"]),
                        "state": QuantRunState(item["state"]),
                        "created_at": _datetime(item["created_at"]),
                        "updated_at": _datetime(item["updated_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    }
                )
                for item in state.get("runs", [])
                if item.get("workspace_id") == workspace_id
            }
        )
        for item in state.get("events", []):
            if item.get("workspace_id") != workspace_id:
                continue
            event = QuantEventRecord(
                **{
                    **item,
                    "occurred_at": _datetime(item["occurred_at"]),
                    "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                }
            )
            self._events.setdefault(event.run_id, []).append(event)
        self._artifacts.update(
            {
                item["id"]: QuantArtifactRecord(
                    **{
                        **item,
                        "kind": QuantArtifactKind(item["kind"]),
                        "review_status": QuantArtifactReviewStatus(item["review_status"]),
                        "created_at": _datetime(item["created_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    }
                )
                for item in state.get("artifacts", [])
                if item.get("workspace_id") == workspace_id
            }
        )
        self._experiments.update(
            {
                item["id"]: QuantExperimentRecord(
                    **{
                        **item,
                        "verdict": QuantExperimentVerdict(item["verdict"]),
                        "created_at": _datetime(item["created_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    }
                )
                for item in state.get("experiments", [])
                if item.get("workspace_id") == workspace_id
            }
        )

    def _workspace_state(self, workspace_id: str) -> dict[str, Any]:
        return _json_value(
            {
                "datasets": [
                    {
                        **asdict(row),
                        "dataset": row.dataset.model_dump(mode="json"),
                    }
                    for row in self._datasets.values()
                    if row.workspace_id == workspace_id
                ],
                "projects": [
                    asdict(row)
                    for row in self._projects.values()
                    if row.workspace_id == workspace_id
                ],
                "runs": [
                    asdict(row) for row in self._runs.values() if row.workspace_id == workspace_id
                ],
                "events": [
                    asdict(row)
                    for rows in self._events.values()
                    for row in rows
                    if row.workspace_id == workspace_id
                ],
                "artifacts": [
                    asdict(row)
                    for row in self._artifacts.values()
                    if row.workspace_id == workspace_id
                ],
                "experiments": [
                    asdict(row)
                    for row in self._experiments.values()
                    if row.workspace_id == workspace_id
                ],
            }
        )

    def _persist_workspace(self, workspace_id: str) -> None:
        expected = self._storage_versions.get(workspace_id, 0)
        with self._session_factory() as db:
            set_rls_context(db, workspace_id, "quant-repository")
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == workspace_id)
                .with_for_update()
            )
            if row is None:
                if expected != 0:
                    raise version_conflict(workspace_id, expected)
                row = QuantRepositoryState(
                    workspace_id=workspace_id,
                    state_json={},
                    fixture_row_version=8,
                    data_authenticity=DataAuthenticity.GENERATED.value,
                )
                db.add(row)
            elif row.row_version != expected:
                raise version_conflict(workspace_id, row.row_version)
            row.state_json = self._workspace_state(workspace_id)
            row.row_version = expected + 1
            row.updated_at = _utcnow()
            db.commit()
            self._storage_versions[workspace_id] = row.row_version

    def _invalidate_worker_lease(self, workspace_id: str) -> None:
        expected = self._storage_versions[workspace_id]
        with self._session_factory() as db:
            set_rls_context(db, workspace_id, "quant-api-cancel")
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == workspace_id)
                .with_for_update()
            )
            if row is None or row.row_version != expected:
                raise version_conflict(workspace_id, row.row_version if row else expected)
            row.worker_lease_token = None
            row.worker_lease_expires_at = None
            row.worker_fencing_version += 1
            row.row_version += 1
            db.commit()
            self._storage_versions[workspace_id] = row.row_version

    def claim_fixture_run(
        self,
        *,
        workspace_id: str,
        worker_id: str,
        lease_for: timedelta = timedelta(seconds=120),
    ) -> QuantFixtureLease | None:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            running = sorted(
                (
                    run
                    for run in self._runs.values()
                    if run.workspace_id == workspace_id
                    and run.state is QuantRunState.RUNNING_EXPERIMENTS
                ),
                key=lambda item: item.created_at,
            )
            if not running:
                return None
            now = _utcnow()
            with self._session_factory() as db:
                set_rls_context(db, workspace_id, worker_id)
                row = db.scalar(
                    select(QuantRepositoryState)
                    .where(QuantRepositoryState.workspace_id == workspace_id)
                    .with_for_update()
                )
                expected = self._storage_versions[workspace_id]
                if row is None or row.row_version != expected:
                    return None
                if row.worker_lease_expires_at is not None and row.worker_lease_expires_at > now:
                    return None
                row.worker_fencing_version += 1
                token = str(
                    _uuid(
                        "worker-lease",
                        workspace_id,
                        running[0].id,
                        row.worker_fencing_version,
                    )
                )
                row.worker_lease_token = token
                row.worker_lease_expires_at = now + lease_for
                row.worker_heartbeat_at = now
                row.row_version += 1
                db.commit()
                self._storage_versions[workspace_id] = row.row_version
                return QuantFixtureLease(
                    workspace_id=workspace_id,
                    run_id=running[0].id,
                    token=token,
                    fencing_version=row.worker_fencing_version,
                    expires_at=row.worker_lease_expires_at,
                )

    def heartbeat_fixture_run(
        self, lease: QuantFixtureLease, lease_for: timedelta = timedelta(seconds=120)
    ) -> bool:
        now = _utcnow()
        with self._session_factory() as db:
            set_rls_context(db, lease.workspace_id, lease.token)
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == lease.workspace_id)
                .with_for_update()
            )
            if (
                row is None
                or row.worker_lease_token != lease.token
                or row.worker_fencing_version != lease.fencing_version
                or row.worker_lease_expires_at is None
                or row.worker_lease_expires_at <= now
            ):
                return False
            row.worker_heartbeat_at = now
            row.worker_lease_expires_at = now + lease_for
            db.commit()
            return True

    def execute_fixture_claim(self, lease: QuantFixtureLease, *, fixture_state: str) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if run is None or run.state is not QuantRunState.RUNNING_EXPERIMENTS:
                return False
            if not self._fixture_lease_is_current(lease):
                return False
            self._finish_run(run, fixture_state)
            # The script is built in memory and committed atomically. Recheck
            # the lease/fence/version immediately before that single durable
            # emission so cancellation or expiry cannot allow a late write.
            if not self._fixture_lease_is_current(lease):
                return False
            self._persist_workspace(lease.workspace_id)
        with self._session_factory() as db:
            set_rls_context(db, lease.workspace_id, lease.token)
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == lease.workspace_id)
                .with_for_update()
            )
            if row is not None and row.worker_lease_token == lease.token:
                row.worker_lease_token = None
                row.worker_lease_expires_at = None
                row.row_version += 1
                db.commit()
                self._storage_versions[lease.workspace_id] = row.row_version
        return True

    def _fixture_lease_is_current(self, lease: QuantFixtureLease) -> bool:
        with self._session_factory() as db:
            set_rls_context(db, lease.workspace_id, lease.token)
            row = db.get(QuantRepositoryState, lease.workspace_id)
            return bool(
                row is not None
                and row.row_version == self._storage_versions.get(lease.workspace_id)
                and row.worker_lease_token == lease.token
                and row.worker_fencing_version == lease.fencing_version
                and row.worker_lease_expires_at is not None
                and row.worker_lease_expires_at > _utcnow()
            )

    # Incremental autonomous Agent execution. The existing workspace lease is
    # deliberately reused: there is one fenced writer regardless of worker kind.
    def claim_agent_run(
        self,
        *,
        workspace_id: str,
        worker_id: str,
        lease_for: timedelta = timedelta(seconds=120),
    ) -> QuantFixtureLease | None:
        return self.claim_fixture_run(
            workspace_id=workspace_id,
            worker_id=worker_id,
            lease_for=lease_for,
        )

    def record_agent_decision(self, lease: QuantFixtureLease, decision: QuantAgentDecision) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return False
            assert run is not None
            run.agent_status = "executing_tool"
            run.last_action = decision.action.value
            self._append_event(
                run,
                "agent.action_selected",
                {
                    "action": decision.action.value,
                    "arguments": _json_value(decision.arguments),
                    "decision_summary": decision.decision_summary,
                    "expected_result": decision.expected_result,
                    "iteration": run.agent_iteration + 1,
                    "safe_summary": decision.decision_summary,
                },
            )
            self._append_event(
                run,
                "tool.started",
                {
                    "action": decision.action.value,
                    "arguments": _json_value(decision.arguments),
                    "safe_summary": f"Tool {decision.action.value} started.",
                },
            )
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace(lease.workspace_id)
            return True

    def complete_agent_step(
        self, lease: QuantFixtureLease, observation: QuantToolObservation
    ) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if run is None or run.workspace_id != lease.workspace_id:
                return False
            if not self._fixture_lease_is_current(lease):
                return False
            event_type = "tool.completed" if observation.success else "tool.failed"
            self._append_event(
                run,
                event_type,
                {
                    "action": observation.action.value,
                    "success": observation.success,
                    "candidate_id": observation.candidate_id,
                    "artifact_ids": observation.artifact_ids,
                    "metrics_summary": observation.data.get("metrics"),
                    "error_code": observation.error_code,
                    "retryable": observation.retryable,
                    "safe_summary": observation.safe_summary,
                },
            )
            run.agent_iteration += 1
            run.last_observation = observation.safe_summary
            run.consecutive_provider_failures = 0
            if observation.terminal:
                run.agent_status = "completed"
            elif run.state not in {
                QuantRunState.COMPLETED,
                QuantRunState.FAILED,
                QuantRunState.CANCELLED,
            }:
                run.state = QuantRunState.RUNNING_EXPERIMENTS
                run.agent_status = "waiting_next_step"
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace(lease.workspace_id)
        self.release_agent_claim(lease)
        return True

    def record_agent_provider_failure(
        self,
        lease: QuantFixtureLease,
        safe_summary: str,
        *,
        allow_mock_fallback: bool,
    ) -> int:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return 0
            assert run is not None
            run.agent_iteration += 1
            run.consecutive_provider_failures += 1
            run.agent_status = "waiting_next_step"
            run.last_observation = safe_summary
            self._append_event(
                run,
                "agent.decision_failed",
                {
                    "iteration": run.agent_iteration,
                    "reason_code": "provider_decision_failed",
                    "safe_summary": safe_summary,
                },
            )
            if run.consecutive_provider_failures >= 2:
                if allow_mock_fallback:
                    run.provider = "mock"
                    run.model = None
                    self._append_event(
                        run,
                        "agent.provider_fallback",
                        {
                            "safe_summary": (
                                "The Agent switched to the deterministic Mock provider."
                            )
                        },
                    )
                else:
                    run.state = QuantRunState.FAILED
                    run.agent_status = "failed"
                    run.failure_reason = "The configured model provider remained unavailable."
                    self._append_event(
                        run,
                        "run.failed",
                        {
                            "state": QuantRunState.FAILED,
                            "reason_code": "agent_provider_unavailable",
                            "safe_summary": run.failure_reason,
                        },
                    )
            run.row_version += 1
            run.updated_at = _utcnow()
            failures = run.consecutive_provider_failures
            self._persist_workspace(lease.workspace_id)
        self.release_agent_claim(lease)
        return failures

    def mark_provider_fallback(self, lease: QuantFixtureLease) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return False
            assert run is not None
            run.provider = "mock"
            run.model = None
            self._append_event(
                run,
                "agent.provider_fallback",
                {"safe_summary": "The Agent switched to the deterministic Mock provider."},
            )
            run.row_version += 1
            self._persist_workspace(lease.workspace_id)
            return True

    def release_agent_claim(self, lease: QuantFixtureLease) -> None:
        with self._session_factory() as db:
            set_rls_context(db, lease.workspace_id, lease.token)
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == lease.workspace_id)
                .with_for_update()
            )
            if row is not None and row.worker_lease_token == lease.token:
                row.worker_lease_token = None
                row.worker_lease_expires_at = None
                row.row_version += 1
                db.commit()
                self._storage_versions[lease.workspace_id] = row.row_version

    def _agent_claim_is_writable(
        self, run: QuantRunRecord | None, lease: QuantFixtureLease
    ) -> bool:
        return bool(
            run is not None
            and run.state is QuantRunState.RUNNING_EXPERIMENTS
            and run.agent_status != "cancelled"
            and self._fixture_lease_is_current(lease)
        )

    def create_agent_candidate(
        self,
        lease: QuantFixtureLease,
        *,
        name: str,
        template: str,
        hypothesis: str,
        parameters: dict[str, int | float],
    ) -> tuple[QuantExperimentRecord | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            if run.used_experiments >= run.max_experiments:
                return None, [], "EXPERIMENT_BUDGET_EXHAUSTED"
            normalized = _json_value(parameters)
            duplicate = next(
                (
                    item
                    for item in self._experiments.values()
                    if item.run_id == run.id
                    and item.template == template
                    and item.parameters == normalized
                ),
                None,
            )
            if duplicate is not None:
                return None, [], "DUPLICATE_CANDIDATE"
            candidate_id = str(
                _uuid("agent-candidate", run.id, template, canonical_digest(normalized))
            )
            candidate = QuantExperimentRecord(
                id=candidate_id,
                workspace_id=run.workspace_id,
                run_id=run.id,
                ordinal=1 + sum(item.run_id == run.id for item in self._experiments.values()),
                name=name,
                hypothesis=hypothesis,
                verdict=QuantExperimentVerdict.NOT_VIABLE,
                summary="Candidate created and ready for local backtesting.",
                template=template,
                parameters=normalized,
                state="created",
                candidate_key=candidate_id,
            )
            self._experiments[candidate.id] = candidate
            artifact = self._new_agent_artifact(
                run,
                QuantArtifactKind.STRATEGY_SPEC,
                f"Strategy specification: {name}",
                {"template": template, "parameters": normalized, "hypothesis": hypothesis},
                key=candidate.id,
            )
            run.used_experiments += 1
            run.state = QuantRunState.GENERATING_CANDIDATES
            self._append_event(
                run,
                "candidate.generated",
                {
                    "candidate_id": candidate.id,
                    "experiment_id": candidate.id,
                    "experiment_name": candidate.name,
                    "safe_summary": f"Candidate {candidate.name} was created.",
                },
            )
            self._append_artifact_event(run, artifact)
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace(run.workspace_id)
            return candidate, [artifact.id], None

    def run_agent_backtest(
        self, lease: QuantFixtureLease, *, candidate_id: str
    ) -> tuple[QuantExperimentRecord | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            candidate = self._experiments.get(candidate_id)
            if candidate is None or candidate.run_id != run.id:
                return None, [], "UNKNOWN_CANDIDATE"
            if candidate.state == "completed":
                return None, [], "CANDIDATE_ALREADY_BACKTESTED"
            run.state = QuantRunState.RUNNING_EXPERIMENTS
            candidate.state = "running"
            self._append_event(
                run,
                "backtest.started",
                {
                    "candidate_id": candidate.id,
                    "experiment_id": candidate.id,
                    "safe_summary": f"Local backtest started for {candidate.name}.",
                },
            )
            try:
                result = run_backtest(
                    self._agent_bars(run),
                    self._strategy_spec(candidate.template, candidate.parameters),
                    ExecutionConfig(fee_rate=0.001, slippage_rate=0.0005),
                )
            except ValueError:
                candidate.state = "failed"
                candidate.latest_observation = "The local kernel rejected the candidate parameters."
                self._append_event(
                    run,
                    "backtest.failed",
                    {
                        "candidate_id": candidate.id,
                        "experiment_id": candidate.id,
                        "reason_code": "invalid_strategy_parameters",
                        "safe_summary": candidate.latest_observation,
                    },
                )
                self._persist_workspace(run.workspace_id)
                return candidate, [], "INVALID_STRATEGY_PARAMETERS"
            metrics = self._metrics_projection(result.metrics)
            benchmark = backtest_buy_and_hold(
                self._agent_bars(run),
                ExecutionConfig(fee_rate=0.001, slippage_rate=0.0005),
            )
            candidate.metrics = metrics
            candidate.state = "completed"
            candidate.verdict = (
                QuantExperimentVerdict.VIABLE
                if result.metrics.max_drawdown > benchmark.metrics.max_drawdown
                else QuantExperimentVerdict.NOT_VIABLE
            )
            candidate.summary = (
                f"Kernel result: {metrics['trade_count']} trades, "
                f"maximum drawdown {metrics['maximum_drawdown_pct']}%."
            )
            candidate.latest_observation = candidate.summary
            artifacts = [
                self._new_agent_artifact(
                    run,
                    QuantArtifactKind.BACKTEST_RESULT,
                    f"Backtest metrics: {candidate.name}",
                    {"candidate_id": candidate.id, "metrics": metrics},
                    key=f"{candidate.id}:metrics",
                ),
                self._new_agent_artifact(
                    run,
                    QuantArtifactKind.EQUITY_CURVE,
                    f"Equity curve: {candidate.name}",
                    {
                        "candidate_id": candidate.id,
                        "points": [
                            {"date": point.date.isoformat(), "equity": round(point.equity, 4)}
                            for point in result.equity_curve[
                                :: max(1, len(result.equity_curve) // 100)
                            ]
                        ],
                    },
                    key=f"{candidate.id}:equity",
                ),
                self._new_agent_artifact(
                    run,
                    QuantArtifactKind.TRADE_LOG,
                    f"Trade log: {candidate.name}",
                    {
                        "candidate_id": candidate.id,
                        "trades": [
                            {
                                "entry_date": trade.entry_date.isoformat(),
                                "exit_date": trade.exit_date.isoformat(),
                                "return_pct": round(trade.return_pct * 100, 4),
                            }
                            for trade in result.trades
                        ],
                    },
                    key=f"{candidate.id}:trades",
                ),
            ]
            self._append_event(
                run,
                "backtest.completed",
                {
                    "candidate_id": candidate.id,
                    "experiment_id": candidate.id,
                    "safe_summary": candidate.summary,
                },
            )
            for artifact in artifacts:
                self._append_artifact_event(run, artifact)
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace(run.workspace_id)
            return candidate, [artifact.id for artifact in artifacts], None

    def revise_agent_candidate(
        self,
        lease: QuantFixtureLease,
        *,
        candidate_id: str,
        reason: str,
        parameter_patch: dict[str, int | float],
    ) -> tuple[QuantExperimentRecord | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            original = self._experiments.get(candidate_id)
            if original is None or original.run_id != run.id:
                return None, [], "UNKNOWN_CANDIDATE"
            if run.used_repairs >= run.max_repairs:
                return None, [], "REPAIR_BUDGET_EXHAUSTED"
            parameters = {**original.parameters, **_json_value(parameter_patch)}
            try:
                self._strategy_spec(original.template, parameters)
            except (KeyError, TypeError, ValueError):
                return None, [], "INVALID_STRATEGY_PARAMETERS"
            duplicate = next(
                (
                    item
                    for item in self._experiments.values()
                    if item.run_id == run.id
                    and item.template == original.template
                    and item.parameters == parameters
                ),
                None,
            )
            if duplicate is not None:
                return None, [], "DUPLICATE_CANDIDATE"
            revised_id = str(
                _uuid(
                    "agent-revision",
                    original.id,
                    canonical_digest(parameters),
                    run.used_repairs + 1,
                )
            )
            revised = QuantExperimentRecord(
                id=revised_id,
                workspace_id=run.workspace_id,
                run_id=run.id,
                ordinal=1 + sum(item.run_id == run.id for item in self._experiments.values()),
                name=f"{original.name} revision {original.repair_count + 1}",
                hypothesis=original.hypothesis,
                verdict=QuantExperimentVerdict.NOT_VIABLE,
                summary=f"Revised because: {reason}",
                template=original.template,
                parameters=parameters,
                state="created",
                repair_count=original.repair_count + 1,
                candidate_key=original.candidate_key or original.id,
                parent_experiment_id=original.id,
            )
            original.state = "revised"
            self._experiments[revised.id] = revised
            artifact = self._new_agent_artifact(
                run,
                QuantArtifactKind.STRATEGY_SPEC,
                f"Revised strategy specification: {revised.name}",
                {"template": revised.template, "parameters": parameters, "reason": reason},
                key=revised.id,
            )
            run.used_repairs += 1
            run.state = QuantRunState.REPAIRING
            self._append_event(
                run,
                "repair.started",
                {
                    "candidate_id": original.id,
                    "safe_summary": f"Revision started for {original.name}.",
                },
            )
            self._append_event(
                run,
                "candidate.revised",
                {
                    "candidate_id": revised.id,
                    "experiment_id": revised.id,
                    "repair_count": revised.repair_count,
                    "safe_summary": f"Candidate revised as {revised.name}.",
                },
            )
            self._append_event(
                run,
                "repair.completed",
                {
                    "candidate_id": revised.id,
                    "repair_count": revised.repair_count,
                    "safe_summary": "Candidate revision completed.",
                },
            )
            self._append_artifact_event(run, artifact)
            run.row_version += 1
            self._persist_workspace(run.workspace_id)
            return revised, [artifact.id], None

    def compare_agent_candidates(
        self, lease: QuantFixtureLease
    ) -> tuple[dict[str, Any] | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            completed = [
                item
                for item in self._experiments.values()
                if item.run_id == run.id and item.state == "completed"
            ]
            if not completed:
                return None, [], "NO_COMPLETED_CANDIDATES"
            benchmark_result = backtest_buy_and_hold(
                self._agent_bars(run),
                ExecutionConfig(fee_rate=0.001, slippage_rate=0.0005),
            )
            benchmark = self._metrics_projection(benchmark_result.metrics)
            rows = [
                {
                    "candidate_id": item.id,
                    "name": item.name,
                    **item.metrics,
                    "drawdown_improvement_pct": round(
                        item.metrics["maximum_drawdown_pct"] - benchmark["maximum_drawdown_pct"],
                        4,
                    ),
                    "return_difference": round(
                        item.metrics["total_return_pct"] - benchmark["total_return_pct"], 4
                    ),
                    "drawdown_difference": round(
                        item.metrics["maximum_drawdown_pct"] - benchmark["maximum_drawdown_pct"], 4
                    ),
                    "sharpe_difference": round(
                        item.metrics["sharpe_ratio"] - benchmark["sharpe_ratio"], 4
                    ),
                    "trade_count_difference": item.metrics["trade_count"]
                    - benchmark["trade_count"],
                }
                for item in completed
            ]
            comparison = {"benchmark": benchmark, "candidates": rows}
            artifact = self._new_agent_artifact(
                run,
                QuantArtifactKind.VALIDATION_REPORT,
                "Candidate comparison",
                comparison,
                key=f"comparison:{run.agent_iteration}",
            )
            self._append_event(
                run,
                "comparison.generated",
                {
                    "artifact_id": artifact.id,
                    "safe_summary": (
                        f"{len(completed)} completed candidates were compared with buy and hold."
                    ),
                },
            )
            self._append_artifact_event(run, artifact)
            self._persist_workspace(run.workspace_id)
            return comparison, [artifact.id], None

    def finish_agent_research(
        self,
        lease: QuantFixtureLease,
        *,
        selected_candidate_id: str | None,
        conclusion: str,
        next_step: str,
    ) -> tuple[dict[str, Any] | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            completed = [
                item
                for item in self._experiments.values()
                if item.run_id == run.id and item.state == "completed"
            ]
            if not completed and run.agent_iteration < run.max_agent_iterations - 1:
                return None, [], "NO_COMPLETED_CANDIDATES"
            selected = self._experiments.get(selected_candidate_id or "")
            if selected_candidate_id and (
                selected is None or selected.run_id != run.id or selected.state != "completed"
            ):
                return None, [], "INVALID_SELECTED_CANDIDATE"
            dataset = self.dataset_for_run(run)
            source_limitation = (
                "The pinned dataset was imported by the workspace and was not independently "
                "verified against a market data provider."
                if dataset.dataset_id != SPY_DAILY_FIXTURE.dataset_id
                else "The pinned dataset is synthetic and is not real market data."
            )
            report = {
                "research_goal": run.question,
                "plan_summary": run.plan_summary,
                "dataset": self.agent_dataset_summary(run),
                "benchmark": self.agent_benchmark_summary(run),
                "candidates_tested": [self.agent_candidate_summary(item) for item in completed],
                "selected_candidate_id": selected_candidate_id,
                "conclusion": conclusion,
                "next_step": next_step,
                "limitations": [
                    source_limitation,
                    "Results are local backtests, not investment advice or trading instructions.",
                    "No statistical significance or live execution was evaluated.",
                ],
                "run_metadata": {
                    "run_id": run.id,
                    "provider": run.provider,
                    "model": run.model,
                    "iterations": run.agent_iteration + 1,
                },
            }
            artifact = self._new_agent_artifact(
                run,
                QuantArtifactKind.RESEARCH_REPORT,
                "Autonomous Quant Research Report",
                report,
                key="agent-report",
            )
            run.final_conclusion = conclusion
            run.state = QuantRunState.COMPLETED
            run.agent_status = "completed"
            self._append_event(
                run,
                "report.generated",
                {
                    "artifact_id": artifact.id,
                    "safe_summary": "The autonomous research report was generated.",
                },
            )
            self._append_artifact_event(run, artifact)
            self._append_event(
                run,
                "run.completed",
                {
                    "state": QuantRunState.COMPLETED,
                    "plan_revision": run.plan_revision,
                    "attempt_number": run.attempt_number,
                    "safe_summary": "The autonomous research run completed.",
                },
            )
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace(run.workspace_id)
            return report, [artifact.id], None

    def _new_agent_artifact(
        self,
        run: QuantRunRecord,
        kind: QuantArtifactKind,
        title: str,
        content: dict[str, Any],
        *,
        key: str,
    ) -> QuantArtifactRecord:
        artifact = QuantArtifactRecord(
            id=str(_uuid("agent-artifact", run.id, kind.value, key)),
            workspace_id=run.workspace_id,
            run_id=run.id,
            ordinal=1 + sum(item.run_id == run.id for item in self._artifacts.values()),
            kind=kind,
            title=title,
            digest=canonical_digest(content),
            content=_json_value(content),
        )
        self._artifacts[artifact.id] = artifact
        return artifact

    def _append_artifact_event(self, run: QuantRunRecord, artifact: QuantArtifactRecord) -> None:
        self._append_event(
            run,
            "artifact.published",
            {
                "artifact_id": artifact.id,
                "artifact_kind": artifact.kind,
                "safe_summary": f"Artifact published: {artifact.title}.",
            },
        )

    def _agent_bars(self, run: QuantRunRecord) -> tuple[DailyBar, ...]:
        dataset = self.dataset_for_run(run)
        return tuple(
            DailyBar(
                date=bar.trading_date,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
            for bar in dataset.bars
        )

    @staticmethod
    def _strategy_spec(template: str, parameters: dict[str, Any]) -> StrategySpec:
        if template == "sma_crossover":
            return StrategySpec.sma(int(parameters["fast_window"]), int(parameters["slow_window"]))
        if template == "rsi_mean_reversion":
            return StrategySpec.rsi(
                int(parameters.get("period", 14)),
                oversold=float(parameters["entry_threshold"]),
                overbought=float(parameters["exit_threshold"]),
            )
        if template == "breakout":
            return StrategySpec.breakout(int(parameters["lookback_window"]))
        raise ValueError("Unknown strategy template.")

    @staticmethod
    def _metrics_projection(metrics: BacktestMetrics) -> dict[str, Any]:
        return {
            "total_return_pct": round(metrics.total_return * 100, 4),
            "annualized_return_pct": round(metrics.annualized_return * 100, 4),
            "maximum_drawdown_pct": round(metrics.max_drawdown * 100, 4),
            "sharpe_ratio": round(metrics.sharpe_ratio, 4),
            "trade_count": metrics.trade_count,
            "win_rate_pct": round(metrics.win_rate * 100, 4),
            "final_equity": round(metrics.final_equity, 4),
        }

    # Immutable datasets
    def import_dataset_csv(
        self, *, workspace_id: str, name: str, symbol: str, csv_text: str
    ) -> QuantDatasetRecord:
        dataset = parse_ohlcv_csv(csv_text, name=name, symbol=symbol)
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            key = (workspace_id, dataset.dataset_id)
            existing = self._datasets.get(key)
            if existing is not None:
                return existing
            record = QuantDatasetRecord(
                id=dataset.dataset_id,
                workspace_id=workspace_id,
                name=name.strip(),
                dataset=dataset,
            )
            self._datasets[key] = record
            self._persist_workspace(workspace_id)
            return record

    def list_datasets(self, *, workspace_id: str) -> list[QuantDatasetRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            return sorted(
                (
                    record
                    for record in self._datasets.values()
                    if record.workspace_id == workspace_id
                ),
                key=lambda item: item.created_at,
                reverse=True,
            )

    def dataset_for_run(self, run: QuantRunRecord) -> QuantDailyBarDataset:
        if run.dataset_id == SPY_DAILY_FIXTURE.dataset_id:
            dataset = SPY_DAILY_FIXTURE
        else:
            record = self._datasets.get((run.workspace_id, run.dataset_id))
            if record is None:
                raise not_found("QuantDataset")
            dataset = record.dataset
        if dataset.digest != run.dataset_digest:
            raise invalid_state("The run's pinned dataset digest no longer matches storage.")
        return dataset

    def get_dataset(
        self, *, workspace_id: str, dataset_id: str
    ) -> QuantDatasetRecord | None:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            if dataset_id == SPY_DAILY_FIXTURE.dataset_id:
                return None
            record = self._datasets.get((workspace_id, dataset_id))
            if record is None:
                raise not_found("QuantDataset")
            return record

    def _resolve_dataset(
        self, *, workspace_id: str, dataset_id: str | None
    ) -> QuantDailyBarDataset:
        selected_id = dataset_id or SPY_DAILY_FIXTURE.dataset_id
        if selected_id == SPY_DAILY_FIXTURE.dataset_id:
            return SPY_DAILY_FIXTURE
        record = self._datasets.get((workspace_id, selected_id))
        if record is None:
            raise not_found("QuantDataset")
        if len(record.dataset.bars) < MIN_AUTONOMOUS_RESEARCH_BARS:
            raise invalid_state(
                "Autonomous research requires at least "
                f"{MIN_AUTONOMOUS_RESEARCH_BARS} daily bars."
            )
        return record.dataset

    def validate_dataset_for_run(
        self, *, workspace_id: str, dataset_id: str | None
    ) -> QuantDailyBarDataset:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            return self._resolve_dataset(
                workspace_id=workspace_id, dataset_id=dataset_id
            )

    # Projects
    def create_project(self, *, workspace_id: str, name: str, objective: str) -> QuantProjectRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = QuantProjectRecord(
                id=str(_uuid("project", workspace_id, name, objective)),
                workspace_id=workspace_id,
                name=name,
                objective=objective,
            )
            self._projects[project.id] = project
            self._persist_workspace(workspace_id)
            return project

    def list_projects(self, *, workspace_id: str) -> list[QuantProjectRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            return [
                project
                for project in sorted(
                    self._projects.values(), key=lambda item: item.created_at, reverse=True
                )
                if project.workspace_id == workspace_id
            ]

    def get_project(self, *, workspace_id: str, project_id: str) -> QuantProjectRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = self._projects.get(project_id)
            if project is None or project.workspace_id != workspace_id:
                raise not_found("QuantProject")
            return project

    # Runs
    def create_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        question: str,
        mode: QuantRunMode,
        expected_project_row_version: int,
        agent_plan: QuantAgentPlan | None = None,
        dataset_id: str | None = None,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = self.get_project(workspace_id=workspace_id, project_id=project_id)
            if project.row_version != expected_project_row_version:
                raise version_conflict(project.id, project.row_version)
            dataset = self._resolve_dataset(
                workspace_id=workspace_id, dataset_id=dataset_id
            )
            run_id = str(
                _uuid(
                    "run",
                    workspace_id,
                    project_id,
                    question,
                    mode.value,
                    dataset.dataset_id,
                    project.row_version,
                )
            )
            run = QuantRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                question=question,
                mode=mode,
                dataset_id=dataset.dataset_id,
                dataset_digest=dataset.digest,
                trace_id=str(_uuid("trace", run_id, 1)),
                provider=self._configured_agent_provider(),
                model=self._configured_agent_model(),
            )
            self._runs[run.id] = run
            project.latest_run_id = run.id
            project.row_version += 1
            project.updated_at = _utcnow()
            self._append_event(
                run,
                "run.queued",
                {
                    "state": QuantRunState.QUEUED,
                    "attempt_number": run.attempt_number,
                    "safe_summary": "The run was queued.",
                },
            )
            self._publish_plan(run, agent_plan)
            if mode is QuantRunMode.AUTO:
                self._start_run(run, "Auto Research accepted the generated bounded plan.")
            self._persist_workspace(workspace_id)
            return run

    def list_runs(
        self, *, workspace_id: str, project_id: str | None = None
    ) -> list[QuantRunRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            runs = [run for run in self._runs.values() if run.workspace_id == workspace_id]
            if project_id is not None:
                runs = [run for run in runs if run.project_id == project_id]
            return sorted(runs, key=lambda item: item.created_at, reverse=True)

    def get_run(self, *, workspace_id: str, run_id: str) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self._runs.get(run_id)
            if run is None or run.workspace_id != workspace_id:
                raise not_found("QuantRun")
            return run

    def approve_plan(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        plan_revision: int,
        reason: str | None,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            if (
                run.row_version != expected_row_version
                and run.state is not QuantRunState.RUNNING_EXPERIMENTS
            ):
                raise version_conflict(run.id, run.row_version)
            if run.plan_revision != plan_revision:
                raise invalid_state("The plan revision is no longer current.")
            if run.state is QuantRunState.CANCELLED:
                return run
            if run.state in {QuantRunState.COMPLETED, QuantRunState.FAILED}:
                return run
            if run.state is QuantRunState.RUNNING_EXPERIMENTS:
                return run
            if run.state is not QuantRunState.WAITING_PLAN_APPROVAL:
                raise invalid_state("Approve-plan requires a plan awaiting approval.")
            self._start_run(run, reason)
            self._persist_workspace(workspace_id)
            return run

    def request_plan_changes(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        plan_revision: int,
        change_request: str,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            if run.row_version != expected_row_version and run.plan_revision != plan_revision:
                raise version_conflict(run.id, run.row_version)
            if run.state is QuantRunState.CANCELLED:
                return run
            if run.state in {QuantRunState.COMPLETED, QuantRunState.FAILED}:
                raise invalid_state("Plan changes can only be requested before a run finishes.")
            if run.plan_revision != plan_revision and run.plan_change_request == change_request:
                return run
            if run.state is not QuantRunState.WAITING_PLAN_APPROVAL:
                raise invalid_state("Plan changes require a plan awaiting approval.")
            run.plan_change_request = change_request
            run.plan_revision += 1
            run.state = QuantRunState.PLANNING
            run.row_version += 1
            run.updated_at = _utcnow()
            self._append_event(
                run,
                "plan.changes_requested",
                {
                    "state": QuantRunState.PLANNING,
                    "plan_revision": plan_revision,
                    "reason_code": "plan_changes_requested",
                    "safe_summary": "Changes were requested for the plan.",
                },
            )
            self._publish_plan(run)
            self._persist_workspace(workspace_id)
            return run

    def cancel_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            if run.row_version != expected_row_version and run.state is not QuantRunState.CANCELLED:
                raise version_conflict(run.id, run.row_version)
            if run.state is QuantRunState.CANCELLED:
                return run
            if run.state in {QuantRunState.COMPLETED, QuantRunState.FAILED}:
                return run
            run.state = QuantRunState.CANCELLED
            run.cancelled_reason = reason
            run.row_version += 1
            run.updated_at = _utcnow()
            self._append_event(
                run,
                "run.cancelled",
                {
                    "state": QuantRunState.CANCELLED,
                    "reason_code": reason,
                    "safe_summary": "Run cancelled.",
                },
            )
            self._persist_workspace(workspace_id)
            self._invalidate_worker_lease(workspace_id)
            return run

    def retry_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            if run.row_version != expected_row_version and run.retry_child_run_id is None:
                raise version_conflict(run.id, run.row_version)
            if run.retry_child_run_id is not None:
                return self.get_run(workspace_id=workspace_id, run_id=run.retry_child_run_id)
            if run.state not in {
                QuantRunState.COMPLETED,
                QuantRunState.FAILED,
                QuantRunState.CANCELLED,
            }:
                raise invalid_state("Retry requires a terminal run.")
            child = QuantRunRecord(
                id=str(_uuid("run-retry", run.id, run.attempt_number + 1, reason)),
                workspace_id=workspace_id,
                project_id=run.project_id,
                question=run.question,
                mode=run.mode,
                attempt_number=run.attempt_number + 1,
                retry_of_run_id=run.id,
                trace_id=str(_uuid("trace", run.id, run.attempt_number + 1)),
                provider=run.provider,
                model=run.model,
                max_agent_iterations=run.max_agent_iterations,
                max_experiments=run.max_experiments,
                max_repairs=run.max_repairs,
                dataset_id=run.dataset_id,
                dataset_digest=run.dataset_digest,
            )
            self._runs[child.id] = child
            run.retry_child_run_id = child.id
            run.row_version += 1
            run.updated_at = _utcnow()
            self._append_event(
                child,
                "run.queued",
                {
                    "state": QuantRunState.QUEUED,
                    "attempt_number": child.attempt_number,
                    "safe_summary": "The retry was queued.",
                },
            )
            self._publish_plan(child)
            if child.mode is QuantRunMode.AUTO:
                self._start_run(child, "Auto Research accepted the retry plan.")
            self._persist_workspace(workspace_id)
            return child

    def execute_fixture_once(self, *, workspace_id: str, fixture_state: str) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            running = [
                run
                for run in sorted(self._runs.values(), key=lambda item: item.created_at)
                if run.workspace_id == workspace_id
                and run.state is QuantRunState.RUNNING_EXPERIMENTS
            ]
            if not running:
                return False
            run = running[0]
            self._finish_run(run, fixture_state)
            self._persist_workspace(workspace_id)
            return True

    def _publish_plan(self, run: QuantRunRecord, agent_plan: QuantAgentPlan | None = None) -> None:
        summary = agent_plan.objective_summary if agent_plan else self._plan_summary(run)
        run.plan_summary = summary
        run.plan_steps = (
            [step.model_dump(mode="json") for step in agent_plan.steps]
            if agent_plan
            else self._agent_plan_steps(run.question)
        )
        if agent_plan is not None:
            run.max_experiments = agent_plan.max_experiments
            run.max_repairs = agent_plan.max_repairs
        plan_artifact = QuantArtifactRecord(
            id=str(_uuid("artifact", run.id, run.plan_revision, "plan")),
            workspace_id=run.workspace_id,
            run_id=run.id,
            ordinal=1,
            kind=QuantArtifactKind.PLAN,
            title=f"Plan revision {run.plan_revision}",
            digest=f"sha256:plan:{run.id}:{run.plan_revision}",
        )
        self._artifacts[plan_artifact.id] = plan_artifact
        run.plan_artifact_id = plan_artifact.id
        self._append_event(
            run,
            "plan.proposed",
            {
                "state": QuantRunState.PLANNING,
                "plan_revision": run.plan_revision,
                "plan_steps": [step["title"] for step in run.plan_steps],
                "artifact_id": plan_artifact.id,
                "safe_summary": "A plan revision was proposed for review.",
            },
        )
        self._append_event(
            run,
            "plan.awaiting_approval",
            {
                "state": QuantRunState.WAITING_PLAN_APPROVAL,
                "plan_revision": run.plan_revision,
                "safe_summary": "The plan is waiting for approval.",
            },
        )
        run.state = QuantRunState.WAITING_PLAN_APPROVAL
        run.row_version += 1
        run.updated_at = _utcnow()

    def _start_run(self, run: QuantRunRecord, reason: str | None) -> None:
        run.state = QuantRunState.RUNNING_EXPERIMENTS
        run.agent_status = "waiting_next_step"
        run.approval_reason = reason
        run.row_version += 1
        run.updated_at = _utcnow()
        self._append_event(
            run,
            "plan.approved",
            {
                "state": QuantRunState.RUNNING_EXPERIMENTS,
                "plan_revision": run.plan_revision,
                "safe_summary": "The bounded Agent plan was accepted.",
            },
        )
        self._append_event(
            run,
            "run.started",
            {
                "state": QuantRunState.RUNNING_EXPERIMENTS,
                "plan_revision": run.plan_revision,
                "attempt_number": run.attempt_number,
                "safe_summary": "The autonomous research run started.",
            },
        )

    @staticmethod
    def _agent_plan_steps(question: str) -> list[dict[str, Any]]:
        lowered = question.lower()
        if any(
            token in lowered for token in ("trade", "frequent", "opportunit", "频繁", "交易机会")
        ):
            families = "RSI mean reversion, fast SMA and short breakout"
        elif any(token in lowered for token in ("mean reversion", "均值回归")):
            families = "RSI mean reversion and a short SMA control"
        elif any(token in lowered for token in ("drawdown", "回撤")):
            families = "slow SMA and long breakout drawdown controls"
        else:
            families = "simple SMA, RSI and breakout templates"
        return [
            {"key": "inspect", "title": "Inspect the pinned research context", "owner": "agent"},
            {"key": "templates", "title": f"Select from {families}", "owner": "agent"},
            {
                "key": "experiments",
                "title": "Create and backtest up to three candidates",
                "owner": "agent",
            },
            {
                "key": "compare",
                "title": "Compare completed candidates with buy and hold",
                "owner": "agent",
            },
            {
                "key": "report",
                "title": "Finish with an evidence-backed conclusion",
                "owner": "agent",
            },
        ]

    @staticmethod
    def _configured_agent_provider() -> str:
        provider = os.environ.get("POKIEQUANT_AGENT_PROVIDER", "mock").strip().lower()
        if provider == "deepseek" and os.environ.get("DEEPSEEK_API_KEY"):
            return "deepseek"
        return "mock"

    @staticmethod
    def _configured_agent_model() -> str | None:
        if QuantStore._configured_agent_provider() != "deepseek":
            return None
        return os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"

    def _finish_run(self, run: QuantRunRecord, fixture_state: str) -> None:
        # Import inside the fixture-only path so normal quant-agent worker code
        # never depends on the Phase 0 fixture script generator.
        from packages.contracts.quant.runtime import build_quant_script

        scenario = {
            "completed": QuantFixtureScenario.NORMAL,
            "completed_rejected_candidate": QuantFixtureScenario.NORMAL,
            "completed_no_viable_candidates": QuantFixtureScenario.NO_VIABLE,
            "failed": QuantFixtureScenario.FAILED_SAFE,
        }[fixture_state]
        for step in build_quant_script(run_id=run.id, scenario=scenario):
            # The canonical script is the only worker sequence. Candidate-scoped
            # failures therefore remain repair events and never become run.failed.
            run.state = step.run_state
            payload = step.payload.model_dump(mode="json", exclude_none=True)
            if step.event_type.value == "run.failed":
                payload.setdefault("reason_code", "fixture_worker_failed_safe")
                run.failure_reason = payload.get("safe_summary", "Fixture worker stopped safely.")
            self._append_event(run, step.event_type.value, payload)
            if step.artifact is not None:
                ordinal = 1 + sum(
                    artifact.run_id == run.id for artifact in self._artifacts.values()
                )
                self._artifacts[step.artifact.artifact_id] = QuantArtifactRecord(
                    id=step.artifact.artifact_id,
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=ordinal,
                    kind=step.artifact.kind,
                    title=step.artifact.label,
                    digest=step.artifact.digest,
                )
            if step.experiment is not None:
                existing = self._experiments.get(step.experiment.experiment_id)
                verdict = {
                    QuantCandidateVerdict.PROMISING: QuantExperimentVerdict.VIABLE,
                    QuantCandidateVerdict.REJECTED: QuantExperimentVerdict.REJECTED,
                    QuantCandidateVerdict.INCONCLUSIVE: QuantExperimentVerdict.NOT_VIABLE,
                    QuantCandidateVerdict.INVALID: QuantExperimentVerdict.REJECTED,
                    None: QuantExperimentVerdict.NOT_VIABLE,
                }[step.experiment.verdict]
                self._experiments[step.experiment.experiment_id] = QuantExperimentRecord(
                    id=step.experiment.experiment_id,
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=(
                        existing.ordinal
                        if existing is not None
                        else 1
                        + sum(
                            experiment.run_id == run.id for experiment in self._experiments.values()
                        )
                    ),
                    name=step.experiment.candidate_name,
                    hypothesis="Deterministic synthetic fixture hypothesis.",
                    verdict=verdict,
                    summary="Canonical fixture runtime result; no real backtest occurred.",
                )
        if run.state is QuantRunState.WAITING_FOR_REVIEW:
            # The legacy Phase 0 API fixture carries a pre-recorded synthetic
            # review. The worker script still stops at review.required; this
            # repository-owned projection records the reviewed terminal state.
            run.state = QuantRunState.COMPLETED
            self._append_event(
                run,
                "run.completed",
                {
                    "state": QuantRunState.COMPLETED,
                    "plan_revision": run.plan_revision,
                    "attempt_number": run.attempt_number,
                    "reason_code": "synthetic_review_fixture_complete",
                    "safe_summary": "The synthetic reviewed run completed.",
                },
            )
        run.row_version += 1
        run.updated_at = _utcnow()

    def _fixture_outputs(
        self, run: QuantRunRecord, fixture_state: str
    ) -> tuple[list[QuantExperimentRecord], list[QuantArtifactRecord]]:
        report = QuantArtifactRecord(
            id=str(_uuid("artifact", run.id, run.plan_revision, fixture_state, "report")),
            workspace_id=run.workspace_id,
            run_id=run.id,
            ordinal=2,
            kind=QuantArtifactKind.RESEARCH_REPORT,
            title=f"fixture-{fixture_state}-report",
            digest=f"sha256:fixture-{fixture_state}-report",
        )
        if fixture_state == "completed_no_viable_candidates":
            experiments = [
                QuantExperimentRecord(
                    id=str(_uuid("experiment", run.id, "no-viable-1")),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=1,
                    name="candidate-1",
                    hypothesis="No viable candidate expected.",
                    verdict=QuantExperimentVerdict.NOT_VIABLE,
                    summary="Fixture state excludes viable outputs.",
                ),
                QuantExperimentRecord(
                    id=str(_uuid("experiment", run.id, "no-viable-2")),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=2,
                    name="candidate-2",
                    hypothesis="No viable candidate expected.",
                    verdict=QuantExperimentVerdict.NOT_VIABLE,
                    summary="Fixture state excludes viable outputs.",
                ),
            ]
            return experiments, [report]
        if fixture_state == "completed_rejected_candidate":
            experiments = [
                QuantExperimentRecord(
                    id=str(_uuid("experiment", run.id, "rejected")),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=1,
                    name="candidate-1",
                    hypothesis="Rejected candidate retained for auditability.",
                    verdict=QuantExperimentVerdict.REJECTED,
                    summary="Rejected candidate retained.",
                )
            ]
            return experiments, [report]
        experiments = [
            QuantExperimentRecord(
                id=str(_uuid("experiment", run.id, "viable")),
                workspace_id=run.workspace_id,
                run_id=run.id,
                ordinal=1,
                name="candidate-1",
                hypothesis="Fixture completion produced one viable candidate.",
                verdict=QuantExperimentVerdict.VIABLE,
                summary="Deterministic fixture success.",
            ),
            QuantExperimentRecord(
                id=str(_uuid("experiment", run.id, "rejected")),
                workspace_id=run.workspace_id,
                run_id=run.id,
                ordinal=2,
                name="candidate-2",
                hypothesis="Rejected candidate retained for auditability.",
                verdict=QuantExperimentVerdict.REJECTED,
                summary="Rejected candidate retained.",
            ),
        ]
        return experiments, [report]

    def _append_event(
        self, run: QuantRunRecord, event_type: str, payload: dict[str, Any]
    ) -> QuantEventRecord:
        sequence = run.latest_sequence + 1
        event = QuantEventRecord(
            id=str(_uuid("event", run.id, sequence, event_type)),
            workspace_id=run.workspace_id,
            run_id=run.id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            trace_id=str(_uuid("trace", run.id, sequence, event_type)),
            occurred_at=_utcnow(),
        )
        self._events.setdefault(run.id, []).append(event)
        run.latest_sequence = sequence
        return event

    def _plan_summary(self, run: QuantRunRecord) -> str:
        focus = self._agent_plan_steps(run.question)[1]["title"]
        return _text(
            "Bounded autonomous plan for",
            run.question,
            f"Focus: {focus}.",
            f"Revision {run.plan_revision}.",
        )

    def agent_dataset_summary(self, run: QuantRunRecord) -> dict[str, Any]:
        dataset = self.dataset_for_run(run)
        return {
            "dataset_id": dataset.dataset_id,
            "symbol": dataset.symbol,
            "interval": dataset.interval.value,
            "bars": len(dataset.bars),
            "start": dataset.covered_start.isoformat(),
            "end": dataset.covered_end.isoformat(),
            "digest": dataset.digest,
            "authenticity": dataset.provenance.value,
        }

    def agent_benchmark_summary(self, run: QuantRunRecord) -> dict[str, Any]:
        result = backtest_buy_and_hold(
            self._agent_bars(run),
            ExecutionConfig(fee_rate=0.001, slippage_rate=0.0005),
        )
        return self._metrics_projection(result.metrics)

    @staticmethod
    def agent_templates() -> list[dict[str, Any]]:
        return [
            {
                "name": "sma_crossover",
                "description": (
                    "Long when the fast moving average is above the slow moving average."
                ),
                "parameters": {
                    "fast_window": {"type": "integer", "minimum": 2, "maximum": 150},
                    "slow_window": {"type": "integer", "minimum": 10, "maximum": 300},
                },
            },
            {
                "name": "rsi_mean_reversion",
                "description": "Enter after oversold RSI and exit after recovery.",
                "parameters": {
                    "period": {"type": "integer", "minimum": 2, "maximum": 100},
                    "entry_threshold": {"type": "number", "minimum": 10, "maximum": 45},
                    "exit_threshold": {"type": "number", "minimum": 45, "maximum": 80},
                },
            },
            {
                "name": "breakout",
                "description": "Enter when price breaks above a trailing range.",
                "parameters": {
                    "lookback_window": {"type": "integer", "minimum": 5, "maximum": 250}
                },
            },
        ]

    @staticmethod
    def agent_candidate_summary(candidate: QuantExperimentRecord) -> dict[str, Any]:
        return {
            "candidate_id": candidate.id,
            "name": candidate.name,
            "template": candidate.template,
            "hypothesis": candidate.hypothesis,
            "parameters": candidate.parameters,
            "state": candidate.state,
            "repair_count": candidate.repair_count,
            "verdict": candidate.verdict.value,
            "metrics": candidate.metrics or None,
            "latest_observation": candidate.latest_observation,
            "parent_experiment_id": candidate.parent_experiment_id,
        }

    def agent_context_data(self, *, workspace_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            candidates = sorted(
                (
                    item
                    for item in self._experiments.values()
                    if item.run_id == run.id and item.template != "fixture"
                ),
                key=lambda item: item.ordinal,
            )
            events = self._events.get(run.id, [])[-15:]
            latest_observation_by_action: dict[str, dict[str, Any]] = {}
            for event in self._events.get(run.id, []):
                action = event.payload.get("action")
                if event.event_type in {"tool.completed", "tool.failed"} and isinstance(
                    action, str
                ):
                    latest_observation_by_action[action] = {
                        "action": action,
                        "success": event.payload.get("success"),
                        "safe_summary": event.payload.get("safe_summary"),
                        "error_code": event.payload.get("error_code"),
                    }
            observations = list(latest_observation_by_action.values())
            return {
                "run_id": run.id,
                "project_id": run.project_id,
                "research_goal": run.question,
                "mode": run.mode.value,
                "run_state": run.state.value,
                "dataset_summary": self.agent_dataset_summary(run),
                "benchmark_summary": self.agent_benchmark_summary(run),
                "available_templates": self.agent_templates(),
                "candidates": [self.agent_candidate_summary(item) for item in candidates],
                "budget": {
                    "max_iterations": run.max_agent_iterations,
                    "used_iterations": run.agent_iteration,
                    "remaining_iterations": max(0, run.max_agent_iterations - run.agent_iteration),
                    "max_experiments": run.max_experiments,
                    "used_experiments": run.used_experiments,
                    "remaining_experiments": max(0, run.max_experiments - run.used_experiments),
                    "max_repairs": run.max_repairs,
                    "used_repairs": run.used_repairs,
                    "remaining_repairs": max(0, run.max_repairs - run.used_repairs),
                },
                "recent_events": [
                    {
                        "sequence": event.sequence,
                        "event_type": event.event_type,
                        "safe_summary": event.payload.get("safe_summary"),
                    }
                    for event in events
                ],
                "recent_observations": observations,
                "plan_summary": run.plan_summary,
                "final_conclusion": run.final_conclusion,
            }

    # Serializers
    def to_project_response(self, project: QuantProjectRecord) -> dict[str, Any]:
        return {
            "id": project.id,
            "workspace_id": project.workspace_id,
            "row_version": project.row_version,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "name": project.name,
            "objective": project.objective,
            "status": project.status,
            "data_authenticity": project.data_authenticity,
        }

    def to_run_response(self, run: QuantRunRecord) -> dict[str, Any]:
        return {
            "id": run.id,
            "workspace_id": run.workspace_id,
            "row_version": run.row_version,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "project_id": run.project_id,
            "dataset_id": run.dataset_id,
            "dataset_digest": run.dataset_digest,
            "state": run.state,
            "mode": run.mode,
            "question": run.question,
            "plan_revision": run.plan_revision,
            "attempt_number": run.attempt_number,
            "trace_id": run.trace_id,
            "latest_sequence": run.latest_sequence,
            "retry_of_run_id": run.retry_of_run_id,
            "failure_reason": run.failure_reason,
            "agent_iteration": run.agent_iteration,
            "agent_status": run.agent_status,
            "max_agent_iterations": run.max_agent_iterations,
            "max_experiments": run.max_experiments,
            "max_repairs": run.max_repairs,
            "used_experiments": run.used_experiments,
            "used_repairs": run.used_repairs,
            "last_action": run.last_action,
            "last_observation": run.last_observation,
            "final_conclusion": run.final_conclusion,
            "provider": run.provider,
            "model": run.model,
            "data_authenticity": run.data_authenticity,
        }

    @staticmethod
    def to_dataset_response(record: QuantDatasetRecord) -> dict[str, Any]:
        dataset = record.dataset
        return {
            "dataset_id": record.id,
            "workspace_id": record.workspace_id,
            "name": record.name,
            "symbol": dataset.symbol,
            "interval": dataset.interval.value,
            "covered_start": dataset.covered_start,
            "covered_end": dataset.covered_end,
            "bar_count": len(dataset.bars),
            "schema_version": dataset.schema_version,
            "parser_version": record.parser_version,
            "digest": dataset.digest,
            "data_authenticity": record.data_authenticity,
            "created_at": record.created_at,
        }

    def to_artifact_response(self, artifact: QuantArtifactRecord) -> dict[str, Any]:
        return {
            "id": artifact.id,
            "workspace_id": artifact.workspace_id,
            "run_id": artifact.run_id,
            "ordinal": artifact.ordinal,
            "kind": artifact.kind,
            "title": artifact.title,
            "digest": artifact.digest,
            "review_status": artifact.review_status,
            "created_at": artifact.created_at,
            "data_authenticity": artifact.data_authenticity,
        }

    def to_experiment_response(self, experiment: QuantExperimentRecord) -> dict[str, Any]:
        return {
            "id": experiment.id,
            "workspace_id": experiment.workspace_id,
            "run_id": experiment.run_id,
            "ordinal": experiment.ordinal,
            "name": experiment.name,
            "hypothesis": experiment.hypothesis,
            "verdict": experiment.verdict,
            "summary": experiment.summary,
            "template": experiment.template,
            "parameters": experiment.parameters,
            "state": experiment.state,
            "metrics": experiment.metrics,
            "repair_count": experiment.repair_count,
            "candidate_key": experiment.candidate_key,
            "parent_experiment_id": experiment.parent_experiment_id,
            "created_at": experiment.created_at,
            "data_authenticity": experiment.data_authenticity,
        }

    def events_for_run(
        self, *, workspace_id: str, run_id: str, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            return [
                event.to_contract()
                for event in self._events.get(run.id, [])
                if event.sequence > after_sequence
            ]

    def workspace_ids(self) -> list[str]:
        with self._lock:
            configured = os.environ.get("GLINT_WORKSPACE_ID")
            if configured:
                self._ensure_workspace_loaded(configured)
            elif self._session_factory.kw.get("bind").dialect.name == "sqlite":
                with self._session_factory() as db:
                    for workspace_id in db.scalars(select(QuantRepositoryState.workspace_id)):
                        self._ensure_workspace_loaded(workspace_id)
            workspaces = {project.workspace_id for project in self._projects.values()}
            workspaces.update(run.workspace_id for run in self._runs.values())
            return sorted(workspaces)

    def latest_sequence(self, *, workspace_id: str, run_id: str) -> int:
        return self.get_run(workspace_id=workspace_id, run_id=run_id).latest_sequence

    def artifacts_for_run(self, *, workspace_id: str, run_id: str) -> list[QuantArtifactRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            self.get_run(workspace_id=workspace_id, run_id=run_id)
            return [artifact for artifact in self._artifacts.values() if artifact.run_id == run_id]

    def experiments_for_run(self, *, workspace_id: str, run_id: str) -> list[QuantExperimentRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            self.get_run(workspace_id=workspace_id, run_id=run_id)
            return [item for item in self._experiments.values() if item.run_id == run_id]

    def get_artifact(self, *, workspace_id: str, artifact_id: str) -> QuantArtifactRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            artifact = self._artifacts.get(artifact_id)
            if artifact is None or artifact.workspace_id != workspace_id:
                raise not_found("QuantArtifact")
            return artifact

    def get_experiment(self, *, workspace_id: str, experiment_id: str) -> QuantExperimentRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            experiment = self._experiments.get(experiment_id)
            if experiment is None or experiment.workspace_id != workspace_id:
                raise not_found("QuantExperiment")
            return experiment


def get_quant_store() -> QuantStore:
    return QuantStore()


def reset_quant_store() -> None:
    from services.api.app.modules.quant.snapshot import reset_workspace_fixtures

    reset_workspace_fixtures()
