"""Small deterministic scheduler for connector collection commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from services.worker.app.contracts import WorkerDomainAdapter
from services.worker.app.jobs.collection import CollectionCommand
from services.worker.app.pipelines.digests import deterministic_id


@dataclass(slots=True)
class CollectionSchedule:
    workspace_id: str
    watchlist_id: str
    source_connection_id: str
    query: str
    terms: tuple[str, ...]
    current_window: tuple[datetime, datetime]
    baseline_window: tuple[datetime, datetime]
    cadence_seconds: int
    next_run_at: datetime
    enabled: bool = True
    lease_until: datetime | None = None


class CollectionScheduler:
    def __init__(self, schedules: list[CollectionSchedule] | None = None) -> None:
        self.schedules = schedules or []

    def due_commands(self, now: datetime, lease_seconds: int = 60) -> list[CollectionCommand]:
        commands: list[CollectionCommand] = []
        for schedule in self.schedules:
            if not schedule.enabled or schedule.next_run_at > now:
                continue
            if schedule.lease_until and schedule.lease_until > now:
                continue
            scheduled_for = schedule.next_run_at
            window_key = scheduled_for.isoformat()
            collection_key = deterministic_id(
                "collection-window",
                schedule.workspace_id,
                schedule.source_connection_id,
                schedule.query,
                window_key,
            )
            commands.append(
                CollectionCommand(
                    workspace_id=schedule.workspace_id,
                    watchlist_id=schedule.watchlist_id,
                    source_connection_id=schedule.source_connection_id,
                    query=schedule.query,
                    collection_key=collection_key,
                    terms=schedule.terms,
                    current_window=schedule.current_window,
                    baseline_window=schedule.baseline_window,
                    scheduled_for=scheduled_for,
                )
            )
            schedule.lease_until = now + timedelta(seconds=lease_seconds)
        return commands

    def release_lease(self, source_connection_id: str, now: datetime | None = None) -> None:
        del now
        for schedule in self.schedules:
            if schedule.source_connection_id == source_connection_id:
                schedule.lease_until = None


class RepositoryCollectionScheduler:
    """Repository-backed scheduler facade for production workers."""

    def __init__(
        self, domain: WorkerDomainAdapter, worker_id: str, lease_seconds: int = 60
    ) -> None:
        self.domain = domain
        self.worker_id = worker_id
        self.lease_for = timedelta(seconds=lease_seconds)

    def claim_one(self, now: datetime):
        return self.domain.claim_due_collection_schedule(self.worker_id, now, self.lease_for)

    def heartbeat(self, schedule_id: str, lease_token: str, now: datetime) -> None:
        self.domain.heartbeat_collection_schedule(schedule_id, lease_token, now, self.lease_for)

    def complete(
        self,
        schedule_id: str,
        lease_token: str,
        success: bool,
        next_run_at: datetime | None,
        now: datetime | None = None,
    ) -> None:
        self.domain.complete_collection_schedule(
            schedule_id, lease_token, success, next_run_at, now
        )

    def release(self, schedule_id: str, lease_token: str) -> None:
        self.domain.release_collection_schedule(schedule_id, lease_token)
