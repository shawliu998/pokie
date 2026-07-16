"""Continuous connector collection with retry, idempotency, and health updates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from connectors.shared.contracts import (
    ConnectorError,
    ConnectorInvalidCredential,
    ConnectorPartialFailure,
    ConnectorRateLimited,
    ConnectorStatus,
    ConnectorTimeout,
    SourceConnector,
)
from connectors.shared.contracts import (
    RawContentItem as ConnectorRawContentItem,
)
from services.worker.app.contracts import (
    CollectionLeaseContext,
    ContentVersion,
    DataAuthenticity,
    InitialBaselineProjection,
    RawContentItem,
    Signal,
    SourceHealthStatus,
    SourceRefetchTarget,
    WorkerDomainAdapter,
)
from services.worker.app.pipelines.dedupe import DedupeAssignment, deduplicate_versions
from services.worker.app.pipelines.digests import deterministic_id
from services.worker.app.pipelines.signals import (
    SignalDetectionConfig,
    detect_signal,
)


@dataclass(frozen=True, slots=True)
class CollectionCommand:
    workspace_id: str
    watchlist_id: str
    source_connection_id: str
    query: str
    collection_key: str
    terms: tuple[str, ...]
    current_window: tuple[datetime, datetime]
    baseline_window: tuple[datetime, datetime]
    scheduled_for: datetime
    exclude_terms: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    detector_version: str = "signal-v1"
    max_pages: int = 5
    schedule_id: str | None = None
    schedule_lease_token: str | None = None
    schedule_fencing_version: int = 0
    schedule_attempt: int = 1
    cadence_seconds: int | None = None
    timezone: str = "UTC"
    connector_config: dict[str, object] | None = None
    collection_kind: str = "collection"
    refetch_limit: int = 0


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.1
    max_delay_seconds: float = 2.0

    def delay_for_attempt(self, attempt: int) -> float:
        return min(self.max_delay_seconds, self.base_delay_seconds * (2 ** max(attempt - 1, 0)))


@dataclass(frozen=True, slots=True)
class CollectionJobResult:
    state: str
    item_count: int
    content_version_count: int
    attempts: int
    health_status: SourceHealthStatus
    error_class: str | None = None
    signal_count: int = 0
    partial: bool = False
    retry_after_seconds: int | None = None


class SignalPersistenceContext(TypedDict):
    candidate_count: int
    dedupe_cluster_count: int
    dedupe_independence_group_count: int
    signal_count: int
    signal_suppressed_reason: str | None
    initial_baseline: dict[str, object]


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self.next_allowed_at: dict[str, datetime] = {}

    def allow(self, key: str, now: datetime) -> bool:
        return now >= self.next_allowed_at.get(key, datetime.min.replace(tzinfo=UTC))

    def defer(self, key: str, now: datetime, seconds: int) -> None:
        self.next_allowed_at[key] = now + timedelta(seconds=seconds)


class ConnectorCollectionJob:
    def __init__(
        self,
        domain: WorkerDomainAdapter,
        connector: SourceConnector,
        retry_policy: RetryPolicy | None = None,
        rate_limiter: InMemoryRateLimiter | None = None,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
        heartbeat: Callable[[datetime], None] | None = None,
    ) -> None:
        self.domain = domain
        self.connector = connector
        self.retry_policy = retry_policy or RetryPolicy()
        self.rate_limiter = rate_limiter
        self.sleeper = sleeper or _noop_sleep
        self.clock = clock or (lambda: datetime.now(tz=UTC))
        self.heartbeat = heartbeat or _noop_heartbeat

    def run(self, command: CollectionCommand) -> CollectionJobResult:
        now = self.clock()
        collection_run_id = self.domain.begin_collection_run(
            command.workspace_id,
            command.source_connection_id,
            command.collection_key,
            {
                "watchlist_id": command.watchlist_id,
                "scheduled_for": command.scheduled_for.isoformat(),
                "detector_version": command.detector_version,
                "query": command.query,
                "terms": list(command.terms),
                "current_start": command.current_window[0].isoformat(),
                "current_end": command.current_window[1].isoformat(),
                "baseline_start": command.baseline_window[0].isoformat(),
                "baseline_end": command.baseline_window[1].isoformat(),
                "schedule_id": command.schedule_id,
                "schedule_lease_token": command.schedule_lease_token,
                "schedule_fencing_version": command.schedule_fencing_version,
                "lease_checked_at": now.isoformat(),
                "attempt": command.schedule_attempt,
                "cadence_seconds": command.cadence_seconds,
                "cadence": _cadence_from_seconds(command.cadence_seconds),
                "timezone": command.timezone,
                "connector_config": command.connector_config or {},
                "kind": command.collection_kind,
            },
        )
        lease = _lease_context(command, collection_run_id)
        if self.rate_limiter is not None and not self.rate_limiter.allow(
            command.source_connection_id, now
        ):
            self.domain.update_source_health(
                command.source_connection_id,
                SourceHealthStatus.RATE_LIMITED,
                {
                    "freshness_state": "stale",
                    "error": "rate_limited",
                    "collection_key": command.collection_key,
                },
                lease,
            )
            self.domain.complete_collection_run(
                lease,
                "failed",
                _counters(fetched=0, failed=1),
                {"state": "stale", "error": "rate_limited"},
                "RATE_LIMITED",
            )
            return CollectionJobResult(
                "rate_limited", 0, 0, 0, SourceHealthStatus.RATE_LIMITED, "RateLimiterDeferred"
            )
        if command.collection_kind == "source_validation":
            return self._run_source_validation(command, lease)

        last_error: Exception | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                connector_items, health_status, truncated, health_details = self._collect_pages(
                    command
                )
                if _is_terminal_empty_health_failure(health_status, connector_items):
                    retry_after = _retry_after_from_details(health_details)
                    return self._complete_terminal_failure(
                        command,
                        lease,
                        health_status,
                        _failure_code_for_health(health_status),
                        attempt,
                        retry_after,
                    )
                versions = self.domain.upsert_collected_raw_items(
                    command.workspace_id,
                    command.source_connection_id,
                    [_to_worker_raw(command.workspace_id, item) for item in connector_items],
                    command.collection_key,
                    lease,
                )
                refetch_context = self._refetch_existing_items(command, lease)
                self.heartbeat(self.clock())
                signal_context = self._detect_and_persist_signal(command, lease)
                backfill_suppressed = _backfill_suppressed(connector_items, command)
                partial = truncated or health_status != SourceHealthStatus.HEALTHY
                run_state = "partial_success" if partial else "succeeded"
                source_health = _source_health_for_usable_items(health_status, connector_items)
                freshness_state = "stale" if partial or backfill_suppressed else "current"
                counters = _counters(
                    fetched=len(connector_items),
                    created=len(versions),
                    skipped=max(0, len(connector_items) - len(versions)),
                    failed=1 if health_status == SourceHealthStatus.FAILED else 0,
                    updated=refetch_context["updated"],
                )
                self.domain.update_source_health(
                    command.source_connection_id,
                    source_health,
                    {
                        "freshness_state": freshness_state,
                        **(
                            {"last_success_at": self.clock().isoformat()}
                            if freshness_state == "current"
                            and source_health == SourceHealthStatus.HEALTHY
                            else {}
                        ),
                        "item_count": len(connector_items),
                        "collection_key": command.collection_key,
                        **(
                            {
                                "warning": "backfill_suppressed",
                                "freshness_warning": "backfill_suppressed",
                            }
                            if backfill_suppressed
                            else {}
                        ),
                    },
                    lease,
                )
                self.domain.complete_collection_run(
                    lease,
                    run_state,
                    counters,
                    {
                        "state": freshness_state,
                        "scheduled_for": command.scheduled_for.isoformat(),
                        "detector_version": command.detector_version,
                        "dedupe_cluster_count": signal_context["dedupe_cluster_count"],
                        "dedupe_independence_group_count": signal_context[
                            "dedupe_independence_group_count"
                        ],
                        "signal_count": signal_context["signal_count"],
                        "signal_candidate_count": signal_context["candidate_count"],
                        "signal_suppressed_reason": signal_context["signal_suppressed_reason"],
                        "initial_baseline": signal_context["initial_baseline"],
                        "refetch_checked": refetch_context["checked"],
                        "refetch_deleted": refetch_context["deleted"],
                        "refetch_recovered": refetch_context["recovered"],
                        "truncated": truncated,
                        "backfill_suppressed": backfill_suppressed,
                        **({"warning": "backfill_suppressed"} if backfill_suppressed else {}),
                    },
                    None,
                )
                return CollectionJobResult(
                    run_state,
                    len(connector_items),
                    len(versions),
                    attempt,
                    source_health,
                    signal_count=signal_context["signal_count"],
                    partial=partial,
                )
            except ConnectorPartialFailure as exc:
                versions = self.domain.upsert_collected_raw_items(
                    command.workspace_id,
                    command.source_connection_id,
                    [_to_worker_raw(command.workspace_id, item) for item in exc.items],
                    command.collection_key,
                    lease,
                )
                self.heartbeat(self.clock())
                signal_context = self._detect_and_persist_signal(command, lease)
                self.domain.update_source_health(
                    command.source_connection_id,
                    SourceHealthStatus.DEGRADED,
                    {
                        "freshness_state": "stale",
                        "error": "partial_failure",
                        "collection_key": command.collection_key,
                    },
                    lease,
                )
                self.domain.complete_collection_run(
                    lease,
                    "partial_success",
                    _counters(
                        fetched=len(exc.items),
                        created=len(versions),
                        skipped=max(0, len(exc.items) - len(versions)),
                        failed=1,
                    ),
                    {
                        "state": "stale",
                        "detector_version": command.detector_version,
                        "dedupe_cluster_count": signal_context["dedupe_cluster_count"],
                        "dedupe_independence_group_count": signal_context[
                            "dedupe_independence_group_count"
                        ],
                        "signal_count": signal_context["signal_count"],
                        "signal_candidate_count": signal_context["candidate_count"],
                        "signal_suppressed_reason": signal_context["signal_suppressed_reason"],
                        "initial_baseline": signal_context["initial_baseline"],
                        "partial": True,
                    },
                    exc.__class__.__name__,
                )
                return CollectionJobResult(
                    "partial_success",
                    len(exc.items),
                    len(versions),
                    attempt,
                    SourceHealthStatus.DEGRADED,
                    exc.__class__.__name__,
                    signal_context["signal_count"],
                    True,
                )
            except ConnectorInvalidCredential as exc:
                return self._complete_terminal_failure(
                    command,
                    lease,
                    SourceHealthStatus.AUTH_REQUIRED,
                    exc.__class__.__name__,
                    attempt,
                )
            except ConnectorRateLimited as exc:
                last_error = exc
                retry_after = exc.retry_after_seconds or 60
                if self.rate_limiter is not None:
                    self.rate_limiter.defer(command.source_connection_id, self.clock(), retry_after)
                return self._complete_terminal_failure(
                    command,
                    lease,
                    SourceHealthStatus.RATE_LIMITED,
                    exc.__class__.__name__,
                    attempt,
                    retry_after,
                )
            except ConnectorTimeout as exc:
                last_error = exc
                if attempt == self.retry_policy.max_attempts:
                    break
                self.sleeper(self.retry_policy.delay_for_attempt(attempt))
            except ConnectorError as exc:
                last_error = exc
                break
            except Exception as exc:
                return self._complete_terminal_failure(
                    command,
                    lease,
                    SourceHealthStatus.DEGRADED,
                    exc.__class__.__name__,
                    attempt,
                )

        status = (
            SourceHealthStatus.RATE_LIMITED
            if isinstance(last_error, ConnectorRateLimited)
            else SourceHealthStatus.FAILED
        )
        self.domain.update_source_health(
            command.source_connection_id,
            status,
            {
                "freshness_state": "stale",
                "error": last_error.__class__.__name__ if last_error else "unknown",
                "collection_key": command.collection_key,
            },
            lease,
        )
        self.domain.complete_collection_run(
            lease,
            "failed",
            _counters(fetched=0, failed=1),
            {"state": "stale", "error": status.value},
            last_error.__class__.__name__ if last_error else "unknown",
        )
        return CollectionJobResult(
            "failed",
            0,
            0,
            self.retry_policy.max_attempts,
            status,
            last_error.__class__.__name__ if last_error else "unknown",
        )

    def _run_source_validation(
        self, command: CollectionCommand, lease: CollectionLeaseContext
    ) -> CollectionJobResult:
        try:
            self.heartbeat(self.clock())
            health = self.connector.health()
            status = _map_status(health.status)
            if status == SourceHealthStatus.HEALTHY:
                checked_at = health.checked_at.isoformat()
                self.domain.update_source_health(
                    command.source_connection_id,
                    SourceHealthStatus.HEALTHY,
                    {
                        "freshness_state": "current",
                        "last_success_at": checked_at,
                        "collection_key": command.collection_key,
                    },
                    lease,
                )
                self.domain.complete_collection_run(
                    lease,
                    "succeeded",
                    _counters(fetched=0),
                    {
                        "state": "current",
                        "kind": "source_validation",
                        "last_success_at": checked_at,
                        "checked_at": checked_at,
                    },
                    None,
                )
                return CollectionJobResult(
                    "succeeded", 0, 0, 1, SourceHealthStatus.HEALTHY, signal_count=0
                )
            retry_after = _retry_after_from_details(health.details)
            return self._complete_terminal_failure(
                command,
                lease,
                status,
                _validation_failure_code(status),
                1,
                retry_after,
            )
        except ConnectorInvalidCredential as exc:
            return self._complete_terminal_failure(
                command,
                lease,
                SourceHealthStatus.AUTH_REQUIRED,
                exc.__class__.__name__,
                1,
            )
        except ConnectorRateLimited as exc:
            retry_after = exc.retry_after_seconds or 60
            return self._complete_terminal_failure(
                command,
                lease,
                SourceHealthStatus.RATE_LIMITED,
                exc.__class__.__name__,
                1,
                retry_after,
            )
        except ConnectorError as exc:
            return self._complete_terminal_failure(
                command,
                lease,
                _map_status(getattr(exc, "status", ConnectorStatus.FAILED)),
                exc.__class__.__name__,
                1,
            )
        except Exception as exc:
            return self._complete_terminal_failure(
                command,
                lease,
                SourceHealthStatus.DEGRADED,
                exc.__class__.__name__,
                1,
            )

    def _complete_terminal_failure(
        self,
        command: CollectionCommand,
        lease: CollectionLeaseContext,
        status: SourceHealthStatus,
        failure_code: str,
        attempt: int,
        retry_after_seconds: int | None = None,
    ) -> CollectionJobResult:
        freshness = {
            "state": "stale",
            "error": failure_code,
            **(
                {"retry_after_seconds": retry_after_seconds}
                if retry_after_seconds is not None
                else {}
            ),
        }
        self.domain.update_source_health(
            command.source_connection_id,
            status,
            {
                "freshness_state": "stale",
                "error": failure_code,
                "collection_key": command.collection_key,
                **(
                    {"retry_after_seconds": retry_after_seconds}
                    if retry_after_seconds is not None
                    else {}
                ),
            },
            lease,
        )
        self.domain.complete_collection_run(
            lease,
            "failed",
            _counters(fetched=0, failed=1),
            freshness,
            failure_code,
        )
        return CollectionJobResult(
            "failed",
            0,
            0,
            attempt,
            status,
            failure_code,
            retry_after_seconds=retry_after_seconds,
        )

    def _collect_pages(
        self, command: CollectionCommand
    ) -> tuple[list[ConnectorRawContentItem], SourceHealthStatus, bool, dict[str, object]]:
        items: list[ConnectorRawContentItem] = []
        cursor: str | None = None
        health = SourceHealthStatus.HEALTHY
        health_details: dict[str, object] = {}
        truncated = False
        for page_index in range(command.max_pages):
            self.heartbeat(self.clock())
            page = self.connector.search(command.query, cursor=cursor)
            items.extend(page.items)
            page_health = _map_status(page.health.status)
            if _status_rank(page_health) >= _status_rank(health):
                health_details = dict(page.health.details)
            health = _worst_status(health, page_health)
            cursor = page.next_cursor
            if cursor is None:
                break
            if page_index == command.max_pages - 1:
                truncated = True
        return items, health, truncated, health_details

    def _detect_and_persist_signal(
        self, command: CollectionCommand, lease: CollectionLeaseContext
    ) -> SignalPersistenceContext:
        candidates = self.domain.get_signal_candidate_versions(
            command.workspace_id,
            command.watchlist_id,
            command.terms,
            command.current_window,
            command.baseline_window,
            command.collection_key,
            lease,
        )
        dedupe = deduplicate_versions(candidates)
        self.domain.persist_dedupe_assignments(
            command.workspace_id,
            {
                version_id: {
                    "duplicate_cluster_id": assignment.duplicate_cluster_id,
                    "independence_group_id": assignment.independence_group_id,
                    "duplicate_reason": assignment.duplicate_reason,
                }
                for version_id, assignment in dedupe.assignments.items()
            },
            command.collection_key,
            lease,
        )
        signal_result = detect_signal(
            candidates,
            SignalDetectionConfig(
                workspace_id=command.workspace_id,
                watchlist_id=command.watchlist_id,
                terms=command.terms,
                current_window=command.current_window,
                baseline_window=command.baseline_window,
                exclude_terms=command.exclude_terms,
                languages=command.languages,
                regions=command.regions,
                entities=command.entities,
                topics=command.topics,
                detector_version=command.detector_version,
            ),
        )
        signal_count = 0
        signal_suppressed_reason = signal_result.reason if signal_result.suppressed else None
        baseline_projection = self.domain.get_initial_baseline_projection(
            command.workspace_id,
            command.watchlist_id,
            command.collection_key,
            lease,
            len(candidates),
        )
        initial_baseline = _initial_baseline_payload(baseline_projection)
        if signal_result.signal is not None:
            if baseline_projection.status != "ready":
                signal_suppressed_reason = "initial_baseline_insufficient"
            else:
                signal = _bind_signal_to_collection(
                    _bind_signal_dedupe(
                        _bind_signal_candidates(signal_result.signal, candidates),
                        dedupe.assignments,
                    ),
                    command.collection_key,
                )
                persisted = self.domain.create_signal(signal, lease)
                signal_count = 1 if persisted.created else 0
                signal_suppressed_reason = persisted.suppressed_reason
        return {
            "candidate_count": len(candidates),
            "dedupe_cluster_count": len(dedupe.duplicate_cluster_sizes),
            "dedupe_independence_group_count": len(dedupe.independence_group_sizes),
            "signal_count": signal_count,
            "signal_suppressed_reason": signal_suppressed_reason,
            "initial_baseline": initial_baseline,
        }

    def _refetch_existing_items(
        self, command: CollectionCommand, lease: CollectionLeaseContext
    ) -> dict[str, int]:
        if command.refetch_limit <= 0:
            return {"checked": 0, "deleted": 0, "recovered": 0, "updated": 0}
        targets = self.domain.get_source_refetch_targets(
            command.workspace_id,
            command.source_connection_id,
            command.collection_key,
            lease,
            command.refetch_limit,
        )
        if not targets:
            return {"checked": 0, "deleted": 0, "recovered": 0, "updated": 0}
        checked = 0
        deleted = 0
        recovered = 0
        raws: list[RawContentItem] = []
        for target in targets:
            self.heartbeat(self.clock())
            result = self.connector.fetch(target.source_item_id)
            checked += 1
            if result.deleted:
                deleted += 1
                raws.append(_deleted_refetch_raw(command, target, self.clock()))
            elif result.item is not None:
                recovered += 1
                raws.append(_to_worker_raw(command.workspace_id, result.item))
        if raws:
            self.domain.upsert_collected_raw_items(
                command.workspace_id,
                command.source_connection_id,
                raws,
                command.collection_key,
                lease,
            )
        return {
            "checked": checked,
            "deleted": deleted,
            "recovered": recovered,
            "updated": len(raws),
        }


def _to_worker_raw(workspace_id: str, item: ConnectorRawContentItem) -> RawContentItem:
    return RawContentItem(
        id=deterministic_id(
            "collected-raw",
            item.source_connection_id,
            item.external_id,
            item.content_version_digest,
        ),
        workspace_id=workspace_id,
        source_connection_id=item.source_connection_id,
        source_item_id=item.external_id,
        title=item.title,
        body=item.body,
        canonical_url=item.canonical_url,
        author=item.author,
        published_at=item.published_at,
        captured_at=item.captured_at,
        content_digest=item.content_version_digest,
        data_authenticity=DataAuthenticity.COLLECTED,
        metadata={
            **item.metadata,
            "raw_digest": item.raw_digest,
            "connector_type": item.connector_type,
            "source_connection_id": item.source_connection_id,
            "author": item.author,
        },
    )


def _deleted_refetch_raw(
    command: CollectionCommand, target: SourceRefetchTarget, checked_at: datetime
) -> RawContentItem:
    digest = deterministic_id(
        "deleted-content",
        command.source_connection_id,
        target.source_item_id,
        checked_at.date().isoformat(),
    )
    return RawContentItem(
        id=deterministic_id("deleted-raw", command.collection_key, target.source_item_id, digest),
        workspace_id=command.workspace_id,
        source_connection_id=command.source_connection_id,
        source_item_id=target.source_item_id,
        title=f"Unavailable source item {target.source_item_id}",
        body="",
        canonical_url=target.canonical_url,
        author=None,
        published_at=None,
        captured_at=checked_at,
        content_digest=f"sha256:{digest}",
        data_authenticity=DataAuthenticity.COLLECTED,
        metadata={
            "raw_digest": f"sha256:{deterministic_id('deleted-raw-digest', digest)}",
            "connector_type": command.connector_config.get("connector_type", "connector-v1")
            if command.connector_config
            else "connector-v1",
            "availability": "deleted",
            "availability_reason": "source returned deleted during refetch",
            "deleted": True,
            "checked_at": checked_at.isoformat(),
            "previous_source_item_id": target.source_item_id,
            "previous_content_version_id": target.current_content_version_id,
        },
    )


def _noop_sleep(seconds: float) -> None:
    del seconds


def _noop_heartbeat(now: datetime) -> None:
    del now


def _bind_signal_to_collection(signal: Signal, collection_key: str) -> Signal:
    return replace(signal, dimensions={**signal.dimensions, "collection_key": collection_key})


def _bind_signal_candidates(signal: Signal, candidates: list[ContentVersion]) -> Signal:
    candidate_ids = tuple(sorted({version.id for version in candidates}))
    return replace(
        signal,
        dimensions={**signal.dimensions, "candidate_content_version_ids": candidate_ids},
    )


def _bind_signal_dedupe(signal: Signal, assignments: Mapping[str, DedupeAssignment]) -> Signal:
    dedupe_assignments = {
        version_id: {
            "duplicate_cluster_id": assignment.duplicate_cluster_id,
            "independence_group_id": assignment.independence_group_id,
            "duplicate_reason": assignment.duplicate_reason,
        }
        for version_id, assignment in assignments.items()
    }
    return replace(
        signal, dimensions={**signal.dimensions, "dedupe_assignments": dedupe_assignments}
    )


def _lease_context(command: CollectionCommand, collection_run_id: str) -> CollectionLeaseContext:
    if not command.schedule_id or not command.schedule_lease_token:
        raise ValueError("collection command lacks schedule lease")
    return CollectionLeaseContext(
        collection_run_id=collection_run_id,
        schedule_id=command.schedule_id,
        schedule_lease_token=command.schedule_lease_token,
        schedule_fencing_version=command.schedule_fencing_version,
    )


def _map_status(status: ConnectorStatus) -> SourceHealthStatus:
    return {
        ConnectorStatus.HEALTHY: SourceHealthStatus.HEALTHY,
        ConnectorStatus.DEGRADED: SourceHealthStatus.DEGRADED,
        ConnectorStatus.FAILED: SourceHealthStatus.FAILED,
        ConnectorStatus.AUTH_REQUIRED: SourceHealthStatus.AUTH_REQUIRED,
        ConnectorStatus.RATE_LIMITED: SourceHealthStatus.RATE_LIMITED,
        ConnectorStatus.DISABLED: SourceHealthStatus.DISABLED,
    }[status]


def _worst_status(left: SourceHealthStatus, right: SourceHealthStatus) -> SourceHealthStatus:
    return right if _status_rank(right) > _status_rank(left) else left


def _status_rank(status: SourceHealthStatus) -> int:
    order = {
        SourceHealthStatus.HEALTHY: 0,
        SourceHealthStatus.DEGRADED: 1,
        SourceHealthStatus.RATE_LIMITED: 2,
        SourceHealthStatus.AUTH_REQUIRED: 3,
        SourceHealthStatus.FAILED: 4,
        SourceHealthStatus.DISABLED: 4,
    }
    return order[status]


def _is_terminal_empty_health_failure(
    status: SourceHealthStatus, items: list[ConnectorRawContentItem]
) -> bool:
    return not items and status in {
        SourceHealthStatus.FAILED,
        SourceHealthStatus.AUTH_REQUIRED,
        SourceHealthStatus.RATE_LIMITED,
        SourceHealthStatus.DISABLED,
    }


def _source_health_for_usable_items(
    status: SourceHealthStatus, items: list[ConnectorRawContentItem]
) -> SourceHealthStatus:
    if items and status == SourceHealthStatus.FAILED:
        return SourceHealthStatus.DEGRADED
    return status


def _failure_code_for_health(status: SourceHealthStatus) -> str:
    return {
        SourceHealthStatus.FAILED: "CONNECTOR_FAILED",
        SourceHealthStatus.AUTH_REQUIRED: "AUTH_REQUIRED",
        SourceHealthStatus.RATE_LIMITED: "RATE_LIMITED",
        SourceHealthStatus.DISABLED: "SOURCE_DISABLED",
    }.get(status, "CONNECTOR_FAILED")


def _validation_failure_code(status: SourceHealthStatus) -> str:
    return {
        SourceHealthStatus.FAILED: "VALIDATION_FAILED",
        SourceHealthStatus.DEGRADED: "VALIDATION_DEGRADED",
        SourceHealthStatus.AUTH_REQUIRED: "ConnectorInvalidCredential",
        SourceHealthStatus.RATE_LIMITED: "ConnectorRateLimited",
        SourceHealthStatus.DISABLED: "SOURCE_DISABLED",
    }.get(status, "VALIDATION_FAILED")


def _retry_after_from_details(details: Mapping[str, object]) -> int | None:
    value = details.get("retry_after_seconds") or details.get("retry_after")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(1, value)
    if isinstance(value, str) and value.isdigit():
        return max(1, int(value))
    return None


def _initial_baseline_payload(projection: InitialBaselineProjection) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": projection.status,
        "current_count": projection.current_count,
        "required_count": projection.required_count,
        "candidate_count": projection.candidate_count,
    }
    if projection.expected_detectable_at is not None:
        payload["expected_detectable_at"] = projection.expected_detectable_at.isoformat()
    if projection.reason is not None:
        payload["reason"] = projection.reason
    if projection.last_terminal_run_at is not None:
        payload["last_terminal_run_at"] = projection.last_terminal_run_at.isoformat()
    return payload


def _backfill_suppressed(items: list[ConnectorRawContentItem], command: CollectionCommand) -> bool:
    if not items:
        return False
    current_start = _as_utc(command.current_window[0])
    latest_event_time = max(_as_utc(item.published_at or item.captured_at) for item in items)
    return latest_event_time < current_start


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _counters(
    *,
    fetched: int,
    created: int = 0,
    updated: int = 0,
    skipped: int = 0,
    failed: int = 0,
) -> dict[str, int]:
    return {
        "fetched": max(0, fetched),
        "created": max(0, created),
        "updated": max(0, updated),
        "skipped": max(0, skipped),
        "failed": max(0, failed),
    }


def _cadence_from_seconds(cadence_seconds: int | None) -> str:
    if cadence_seconds == 86_400:
        return "daily"
    if cadence_seconds == 604_800:
        return "weekly"
    return "manual"
