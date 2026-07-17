from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
import os
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.contracts.enums import DataAuthenticity
from packages.contracts.quant.enums import (
    QuantArtifactKind,
    QuantArtifactReviewStatus,
    QuantExperimentVerdict,
    QuantProjectStatus,
    QuantRunMode,
    QuantRunState,
    QuantCandidateVerdict,
    QuantFixtureScenario,
)
from packages.contracts.quant.runtime import build_quant_script
from services.api.app.core.errors import invalid_state, not_found, version_conflict
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _uuid(label: str, *parts: object) -> UUID:
    return uuid5(NAMESPACE_URL, "pokiequant.quant:" + ":".join(str(part) for part in (label, *parts)))


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


@dataclass(slots=True)
class QuantRunRecord:
    id: str
    workspace_id: str
    project_id: str
    question: str
    mode: QuantRunMode
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
        self._projects: dict[str, QuantProjectRecord] = {}
        self._runs: dict[str, QuantRunRecord] = {}
        self._events: dict[str, list[QuantEventRecord]] = {}
        self._artifacts: dict[str, QuantArtifactRecord] = {}
        self._experiments: dict[str, QuantExperimentRecord] = {}

    def clear(self) -> None:
        with self._lock:
            self._projects.clear()
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
                "projects": [asdict(row) for row in self._projects.values() if row.workspace_id == workspace_id],
                "runs": [asdict(row) for row in self._runs.values() if row.workspace_id == workspace_id],
                "events": [asdict(row) for rows in self._events.values() for row in rows if row.workspace_id == workspace_id],
                "artifacts": [asdict(row) for row in self._artifacts.values() if row.workspace_id == workspace_id],
                "experiments": [asdict(row) for row in self._experiments.values() if row.workspace_id == workspace_id],
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
                for project in sorted(self._projects.values(), key=lambda item: item.created_at, reverse=True)
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
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = self.get_project(workspace_id=workspace_id, project_id=project_id)
            if project.row_version != expected_project_row_version:
                raise version_conflict(project.id, project.row_version)
            run_id = str(_uuid("run", workspace_id, project_id, question, mode.value, project.row_version))
            run = QuantRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                question=question,
                mode=mode,
                trace_id=str(_uuid("trace", run_id, 1)),
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
            self._publish_plan(run)
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
            if run.row_version != expected_row_version and run.state is not QuantRunState.RUNNING_EXPERIMENTS:
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
            run.state = QuantRunState.RUNNING_EXPERIMENTS
            run.approval_reason = reason
            run.row_version += 1
            run.updated_at = _utcnow()
            self._append_event(
                run,
                "plan.approved",
                {
                    "state": QuantRunState.RUNNING_EXPERIMENTS,
                    "plan_revision": run.plan_revision,
                    "safe_summary": "The pinned plan revision was approved.",
                },
            )
            self._append_event(
                run,
                "run.started",
                {
                    "state": QuantRunState.RUNNING_EXPERIMENTS,
                    "plan_revision": run.plan_revision,
                    "attempt_number": run.attempt_number,
                    "safe_summary": "The approved run started.",
                },
            )
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
            self._persist_workspace(workspace_id)
            return child

    def execute_fixture_once(self, *, workspace_id: str, fixture_state: str) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            running = [
                run
                for run in sorted(self._runs.values(), key=lambda item: item.created_at)
                if run.workspace_id == workspace_id and run.state is QuantRunState.RUNNING_EXPERIMENTS
            ]
            if not running:
                return False
            run = running[0]
            self._finish_run(run, fixture_state)
            self._persist_workspace(workspace_id)
            return True

    def _publish_plan(self, run: QuantRunRecord) -> None:
        summary = self._plan_summary(run)
        run.plan_summary = summary
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
                "plan_steps": [
                    "Pin the synthetic demo dataset snapshot",
                    "Draft bounded strategy hypotheses",
                    "Evaluate candidates against fixture bars",
                    "Record validation findings and verdicts",
                    "Publish the fixture research report",
                ],
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

    def _finish_run(self, run: QuantRunRecord, fixture_state: str) -> None:
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
                            experiment.run_id == run.id
                            for experiment in self._experiments.values()
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

    def _append_event(self, run: QuantRunRecord, event_type: str, payload: dict[str, Any]) -> QuantEventRecord:
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
        return _text("Deterministic plan for", run.question, f"(revision {run.plan_revision})")

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
            "state": run.state,
            "mode": run.mode,
            "question": run.question,
            "plan_revision": run.plan_revision,
            "attempt_number": run.attempt_number,
            "trace_id": run.trace_id,
            "latest_sequence": run.latest_sequence,
            "retry_of_run_id": run.retry_of_run_id,
            "failure_reason": run.failure_reason,
            "data_authenticity": run.data_authenticity,
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
            "created_at": experiment.created_at,
            "data_authenticity": experiment.data_authenticity,
        }

    def events_for_run(self, *, workspace_id: str, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
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
