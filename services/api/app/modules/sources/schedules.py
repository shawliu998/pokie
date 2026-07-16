from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from services.api.app.core.errors import ApiError, invalid_state, not_found, version_conflict
from services.api.app.db.models import CollectionSchedule, SourceConnection, Watchlist
from services.api.app.modules.common import audit, text_digest, utcnow

MAX_SCHEDULE_QUERY_BYTES = 16_384
COMMON_QUERY_FIELDS = {
    "query",
    "terms",
    "include_terms",
    "exclude_terms",
    "languages",
    "regions",
    "entities",
    "topics",
    "current_window",
    "baseline_window",
    "current_window_days",
    "baseline_window_days",
    "watchlist_rules_version",
    "watchlist_rules_schema_version",
    "detector_version",
    "max_pages",
}
GITHUB_QUERY_FIELDS = {
    "owner",
    "repo",
    "include_repository",
    "include_issues",
    "include_discussions",
    "include_releases",
    "per_page",
}
RSS_QUERY_FIELDS = {
    "feed_url",
    "feed_title",
    "timeout_seconds",
    "max_redirects",
    "max_response_bytes",
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _require_schedulable(source: SourceConnection, watchlist: Watchlist) -> None:
    if source.source_kind != "cloud" or source.runtime != "cloud":
        raise ApiError(403, "POLICY_BLOCKED", "Only an approved cloud source may be scheduled.")
    if source.approved_by is None or source.status not in {"validating", "healthy", "degraded"}:
        raise ApiError(403, "POLICY_BLOCKED", "The cloud source must be activated first.")
    if watchlist.status != "active":
        raise ApiError(409, "INVALID_STATE", "The Watchlist must be active before scheduling.")
    approved_source_ids = watchlist.rules_json.get("source_connection_ids", [])
    if source.id not in approved_source_ids:
        raise ApiError(
            403,
            "SOURCE_SCOPE_BLOCKED",
            "The source is not approved by this Watchlist.",
        )


def _validate_schedule_query(source: SourceConnection, value: dict[str, Any]) -> dict[str, Any]:
    if (
        len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
        > MAX_SCHEDULE_QUERY_BYTES
    ):
        raise ApiError(422, "VALIDATION_ERROR", "Schedule query exceeds the byte limit.")
    allowed = COMMON_QUERY_FIELDS | (
        GITHUB_QUERY_FIELDS if source.connector_type == "github" else RSS_QUERY_FIELDS
    )
    unknown = set(value) - allowed
    if unknown:
        raise ApiError(
            422,
            "SOURCE_SCOPE_BLOCKED",
            "Schedule query contains fields outside the approved connector contract.",
            {"fields": sorted(unknown)},
        )
    result = dict(value)
    query = result.get("query")
    if query is not None and (not isinstance(query, str) or len(query.encode()) > 500):
        raise ApiError(422, "VALIDATION_ERROR", "Schedule query text is invalid.")
    terms = result.get("terms")
    if terms is not None and (
        not isinstance(terms, list)
        or len(terms) > 20
        or any(not isinstance(item, str) or len(item.encode()) > 100 for item in terms)
    ):
        raise ApiError(422, "VALIDATION_ERROR", "Schedule terms exceed the allowed bounds.")
    max_pages = result.get("max_pages", 5)
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 20:
        raise ApiError(422, "VALIDATION_ERROR", "max_pages must be between 1 and 20.")
    result["max_pages"] = max_pages
    config = source.config_json or {}
    if source.connector_type == "github":
        owner = result.get("owner")
        repo = result.get("repo")
        if not isinstance(owner, str) or not isinstance(repo, str):
            raise ApiError(422, "SOURCE_SCOPE_BLOCKED", "GitHub schedule requires owner and repo.")
        approved = next(
            (
                item
                for item in config.get("repositories", [])
                if str(item.get("owner", "")).casefold() == owner.casefold()
                and str(item.get("repository", "")).casefold() == repo.casefold()
            ),
            None,
        )
        if approved is None:
            raise ApiError(403, "SOURCE_SCOPE_BLOCKED", "GitHub repository is not approved.")
        for capability in ("include_issues", "include_discussions", "include_releases"):
            requested = result.get(capability, approved.get(capability, True))
            if not isinstance(requested, bool) or (
                requested and not approved.get(capability, True)
            ):
                raise ApiError(
                    403, "SOURCE_SCOPE_BLOCKED", "Schedule exceeds approved GitHub scope."
                )
            result[capability] = requested
        per_page = result.get("per_page", 100)
        if not isinstance(per_page, int) or isinstance(per_page, bool) or not 1 <= per_page <= 100:
            raise ApiError(422, "VALIDATION_ERROR", "per_page must be between 1 and 100.")
        result["per_page"] = per_page
        result["include_repository"] = bool(result.get("include_repository", True))
    elif source.connector_type == "rss":
        feed_url = result.get("feed_url")
        approved_feed = next(
            (
                item
                for item in config.get("feeds", [])
                if str(item.get("feed_url")) == str(feed_url)
            ),
            None,
        )
        if approved_feed is None:
            raise ApiError(403, "SOURCE_SCOPE_BLOCKED", "RSS feed is not approved.")
        result["feed_title"] = result.get("feed_title") or approved_feed.get("name")
        timeout = result.get("timeout_seconds", 10.0)
        redirects = result.get("max_redirects", 3)
        max_bytes = result.get("max_response_bytes", 2_000_000)
        if (
            not isinstance(timeout, int | float)
            or isinstance(timeout, bool)
            or not 1 <= timeout <= 30
        ):
            raise ApiError(422, "VALIDATION_ERROR", "RSS timeout is outside the allowed range.")
        if not isinstance(redirects, int) or isinstance(redirects, bool) or not 0 <= redirects <= 5:
            raise ApiError(422, "VALIDATION_ERROR", "RSS redirects are outside the allowed range.")
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or not 1 <= max_bytes <= 2_000_000
        ):
            raise ApiError(422, "VALIDATION_ERROR", "RSS response byte cap is invalid.")
        result.update(
            timeout_seconds=float(timeout),
            max_redirects=redirects,
            max_response_bytes=max_bytes,
        )
    else:
        raise ApiError(422, "SOURCE_SCOPE_BLOCKED", "Unsupported schedule connector.")
    return result


def _freeze_watchlist_rules(watchlist: Watchlist, value: dict[str, Any]) -> dict[str, Any]:
    rules = watchlist.rules_json.get("rules", {})
    query_rules = rules.get("query_rules", {})
    current_days = rules.get("current_window_days")
    baseline_days = rules.get("baseline_window_days")
    if not isinstance(current_days, int) or not isinstance(baseline_days, int):
        raise ApiError(409, "INVALID_STATE", "The Watchlist has no valid versioned windows.")
    frozen: dict[str, Any] = {
        "watchlist_rules_version": watchlist.rules_version,
        "watchlist_rules_schema_version": rules.get("schema_version", "watchlist-rules-v1"),
        "include_terms": list(query_rules.get("include_terms", [])),
        "exclude_terms": list(query_rules.get("exclude_terms", [])),
        "languages": list(query_rules.get("languages", [])),
        "regions": list(query_rules.get("regions", [])),
        "entities": list(rules.get("entities", [])),
        "topics": list(rules.get("topics", [])),
        "current_window_days": current_days,
        "baseline_window_days": baseline_days,
        "current_window": {"days": current_days},
        "baseline_window": {"days": baseline_days, "offset_days": current_days},
    }
    for field, expected in frozen.items():
        if field in value and value[field] != expected:
            raise ApiError(
                403,
                "SOURCE_SCOPE_BLOCKED",
                "Schedule query conflicts with the bound Watchlist rules version.",
                {"field": field},
            )
    result = value | frozen
    if (
        len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
        > MAX_SCHEDULE_QUERY_BYTES
    ):
        raise ApiError(422, "VALIDATION_ERROR", "Frozen schedule query exceeds the byte limit.")
    return result


def _bound_schedule_query(
    source: SourceConnection, watchlist: Watchlist, value: dict[str, Any]
) -> dict[str, Any]:
    return _freeze_watchlist_rules(watchlist, _validate_schedule_query(source, value))


def _retarget_schedule_query(source: SourceConnection, value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    config = source.config_json or {}
    if source.connector_type == "github":
        repositories = config.get("repositories", [])
        if len(repositories) != 1:
            raise ApiError(409, "INVALID_STATE", "The GitHub source target is unavailable.")
        repository = repositories[0]
        result.update(
            owner=repository["owner"],
            repo=repository["repository"],
            include_issues=repository.get("include_issues", True),
            include_discussions=repository.get("include_discussions", True),
            include_releases=repository.get("include_releases", True),
        )
    elif source.connector_type == "rss":
        feeds = config.get("feeds", [])
        if len(feeds) != 1:
            raise ApiError(409, "INVALID_STATE", "The RSS source target is unavailable.")
        feed = feeds[0]
        result.update(feed_url=feed["feed_url"], feed_title=feed["name"])
    return result


def configure_schedule(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> CollectionSchedule:
    source = db.scalar(
        select(SourceConnection).where(
            SourceConnection.id == str(payload["source_connection_id"]),
            SourceConnection.workspace_id == workspace_id,
        )
    )
    watchlist = db.scalar(
        select(Watchlist).where(
            Watchlist.id == str(payload["watchlist_id"]),
            Watchlist.workspace_id == workspace_id,
        )
    )
    if source is None or watchlist is None:
        raise not_found("Schedule source or Watchlist")
    _require_schedulable(source, watchlist)
    row = CollectionSchedule(
        workspace_id=workspace_id,
        source_connection_id=source.id,
        watchlist_id=watchlist.id,
        query_json=_bound_schedule_query(source, watchlist, payload["query_json"]),
        cadence_seconds=payload["cadence_seconds"],
        timezone=payload["timezone"],
        misfire_policy=payload["misfire_policy"],
        catch_up=payload["catch_up"],
        overlap_policy=payload["overlap_policy"],
        next_run_at=payload["next_run_at"],
        enabled=payload.get("enabled", True),
        data_authenticity="collected",
    )
    db.add(row)
    db.flush()
    audit(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="collection_schedule.created",
        target_type="CollectionSchedule",
        target_id=row.id,
        request_id=request_id,
        after={"source_connection_id": source.id, "cadence_seconds": row.cadence_seconds},
    )
    db.commit()
    return row


def update_schedule(
    db: Session,
    *,
    schedule: CollectionSchedule,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> CollectionSchedule:
    if schedule.row_version != payload["expected_row_version"]:
        raise version_conflict(schedule.id, schedule.row_version)
    source = db.scalar(
        select(SourceConnection).where(
            SourceConnection.id == schedule.source_connection_id,
            SourceConnection.workspace_id == schedule.workspace_id,
        )
    )
    watchlist = db.scalar(
        select(Watchlist).where(
            Watchlist.id == schedule.watchlist_id,
            Watchlist.workspace_id == schedule.workspace_id,
        )
    )
    if source is None or watchlist is None:
        raise not_found("Schedule source or Watchlist")
    _require_schedulable(source, watchlist)
    raw_query = (
        payload["query_json"]
        if "query_json" in payload and payload["query_json"] is not None
        else schedule.query_json
    )
    schedule.query_json = _bound_schedule_query(source, watchlist, raw_query)
    for name in (
        "cadence_seconds",
        "timezone",
        "misfire_policy",
        "catch_up",
        "overlap_policy",
        "next_run_at",
        "enabled",
    ):
        if name in payload and payload[name] is not None:
            setattr(schedule, name, payload[name])
    schedule.row_version += 1
    audit(
        db,
        workspace_id=schedule.workspace_id,
        actor_id=actor_id,
        action="collection_schedule.updated",
        target_type="CollectionSchedule",
        target_id=schedule.id,
        request_id=request_id,
        after={"row_version": schedule.row_version, "enabled": schedule.enabled},
    )
    db.commit()
    return schedule


def synchronize_source_schedules(
    db: Session,
    *,
    source: SourceConnection,
    changed_fields: set[str],
    actor_id: str,
    request_id: str,
) -> None:
    schedules = db.scalars(
        select(CollectionSchedule).where(
            CollectionSchedule.workspace_id == source.workspace_id,
            CollectionSchedule.source_connection_id == source.id,
        )
    ).all()
    cadence_seconds = {"daily": 86_400, "weekly": 604_800}.get(source.cadence or "")
    for schedule in schedules:
        watchlist = db.scalar(
            select(Watchlist).where(
                Watchlist.id == schedule.watchlist_id,
                Watchlist.workspace_id == source.workspace_id,
            )
        )
        if watchlist is None:
            raise invalid_state("A source schedule lost its bound Watchlist.")
        if "source_config" in changed_fields:
            schedule.query_json = _bound_schedule_query(
                source,
                watchlist,
                _retarget_schedule_query(source, schedule.query_json),
            )
        if "timezone" in changed_fields and source.timezone is not None:
            schedule.timezone = source.timezone
        if "cadence" in changed_fields:
            if source.cadence == "manual":
                schedule.enabled = False
                schedule.lease_owner_token = None
                schedule.lease_expires_at = None
                schedule.heartbeat_at = None
            elif cadence_seconds is not None:
                schedule.cadence_seconds = cadence_seconds
        if (
            {"cadence", "timezone"}.intersection(changed_fields)
            and schedule.enabled
            and cadence_seconds is not None
        ):
            schedule.next_run_at = utcnow() + timedelta(seconds=cadence_seconds)
        schedule.row_version += 1
        audit(
            db,
            workspace_id=source.workspace_id,
            actor_id=actor_id,
            action="collection_schedule.source_synchronized",
            target_type="CollectionSchedule",
            target_id=schedule.id,
            request_id=request_id,
            after={
                "source_connection_id": source.id,
                "source_row_version": source.row_version,
                "changed_fields": sorted(changed_fields),
                "enabled": schedule.enabled,
            },
        )


class CollectionScheduleRepository:
    """Worker-facing atomic schedule lease repository with hashed owner tokens."""

    @classmethod
    def claim_due(
        cls,
        db: Session,
        *,
        workspace_id: str,
        owner_token: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> CollectionSchedule | None:
        current = _aware(now or utcnow())
        token_digest = text_digest(owner_token)
        candidate = db.scalar(
            select(CollectionSchedule.id)
            .where(
                CollectionSchedule.workspace_id == workspace_id,
                CollectionSchedule.enabled.is_(True),
                CollectionSchedule.next_run_at <= current,
                (
                    CollectionSchedule.lease_expires_at.is_(None)
                    | (CollectionSchedule.lease_expires_at <= current)
                ),
            )
            .order_by(CollectionSchedule.next_run_at)
            .limit(1)
        )
        if candidate is None:
            return None
        lease_until = current + timedelta(seconds=lease_seconds)
        claimed_id = db.scalar(
            update(CollectionSchedule)
            .where(
                CollectionSchedule.id == candidate,
                CollectionSchedule.workspace_id == workspace_id,
                CollectionSchedule.enabled.is_(True),
                (
                    CollectionSchedule.lease_expires_at.is_(None)
                    | (CollectionSchedule.lease_expires_at <= current)
                ),
            )
            .values(
                lease_owner_token=token_digest,
                lease_expires_at=lease_until,
                heartbeat_at=current,
                lease_attempt=CollectionSchedule.lease_attempt + 1,
                lease_fencing_version=CollectionSchedule.lease_fencing_version + 1,
            )
            .returning(CollectionSchedule.id)
        )
        if claimed_id is None:
            db.rollback()
            return None
        db.commit()
        return db.scalar(select(CollectionSchedule).where(CollectionSchedule.id == claimed_id))

    @classmethod
    def heartbeat(
        cls,
        db: Session,
        *,
        schedule_id: str,
        owner_token: str,
        lease_seconds: int,
        expected_attempt: int,
        expected_fencing_version: int,
    ) -> CollectionSchedule:
        current = utcnow()
        updated = db.scalar(
            update(CollectionSchedule)
            .where(
                CollectionSchedule.id == schedule_id,
                CollectionSchedule.lease_owner_token == text_digest(owner_token),
                CollectionSchedule.lease_expires_at > current,
                CollectionSchedule.lease_attempt == expected_attempt,
                CollectionSchedule.lease_fencing_version == expected_fencing_version,
            )
            .values(
                heartbeat_at=current,
                lease_expires_at=current + timedelta(seconds=lease_seconds),
            )
            .returning(CollectionSchedule.id)
        )
        if updated is None:
            db.rollback()
            raise ApiError(409, "JOB_LEASE_EXPIRED", "The collection schedule lease is invalid.")
        db.commit()
        row = db.get(CollectionSchedule, updated)
        if row is None:
            raise not_found("Collection schedule")
        return row

    @classmethod
    def release(
        cls,
        db: Session,
        *,
        schedule_id: str,
        owner_token: str,
        next_run_at: datetime,
        expected_attempt: int,
        expected_fencing_version: int,
    ) -> None:
        updated = db.scalar(
            update(CollectionSchedule)
            .where(
                CollectionSchedule.id == schedule_id,
                CollectionSchedule.lease_owner_token == text_digest(owner_token),
                CollectionSchedule.lease_expires_at > utcnow(),
                CollectionSchedule.lease_attempt == expected_attempt,
                CollectionSchedule.lease_fencing_version == expected_fencing_version,
            )
            .values(
                next_run_at=next_run_at,
                lease_owner_token=None,
                lease_expires_at=None,
                heartbeat_at=None,
            )
            .returning(CollectionSchedule.id)
        )
        if updated is None:
            db.rollback()
            raise ApiError(409, "JOB_LEASE_EXPIRED", "The collection schedule lease is invalid.")
        db.commit()
