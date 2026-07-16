"""Derived initial-baseline projection shared by API and collection writers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.db.models import (
    CollectionRun,
    CollectionSchedule,
    ContentVersion,
    Watchlist,
)

TERMINAL_COLLECTION_STATES = {"succeeded", "partial_success", "failed", "cancelled"}
CONTENT_BEARING_COLLECTION_STATES = {"succeeded", "partial_success"}
MINIMUM_INITIAL_BASELINE_COUNT = 2


def initial_baseline_projection(db: Session, watchlist: Watchlist) -> dict[str, Any]:
    source_ids = sorted(
        str(value) for value in (watchlist.rules_json or {}).get("source_connection_ids", [])
    )
    required_count = max(MINIMUM_INITIAL_BASELINE_COUNT, len(source_ids))
    terminal_runs = list(
        db.scalars(
            select(CollectionRun)
            .where(
                CollectionRun.workspace_id == watchlist.workspace_id,
                CollectionRun.watchlist_id == watchlist.id,
                CollectionRun.state.in_(TERMINAL_COLLECTION_STATES),
            )
            .order_by(CollectionRun.finished_at.desc(), CollectionRun.created_at.desc())
        ).all()
    )
    latest_by_source: dict[str, CollectionRun] = {}
    for run in terminal_runs:
        latest_by_source.setdefault(run.source_connection_id, run)
    successful_source_ids = {
        source_id
        for source_id, run in latest_by_source.items()
        if run.state in CONTENT_BEARING_COLLECTION_STATES
    }
    current_count = 0
    if successful_source_ids:
        current_count = len(
            set(
                db.scalars(
                    select(ContentVersion.id).where(
                        ContentVersion.workspace_id == watchlist.workspace_id,
                        ContentVersion.source_connection_id.in_(successful_source_ids),
                    )
                ).all()
            )
        )
    candidate_count = sum(
        max(0, int((run.freshness_json or {}).get("signal_candidate_count", 0)))
        for run in latest_by_source.values()
    )
    next_run_at = db.scalar(
        select(CollectionSchedule.next_run_at)
        .where(
            CollectionSchedule.workspace_id == watchlist.workspace_id,
            CollectionSchedule.watchlist_id == watchlist.id,
            CollectionSchedule.enabled.is_(True),
        )
        .order_by(CollectionSchedule.next_run_at)
        .limit(1)
    )
    last_terminal = next(
        (run.finished_at or run.created_at for run in terminal_runs),
        None,
    )
    if current_count >= required_count:
        status = "ready"
        expected_detectable_at = None
        reason = None
    elif not terminal_runs:
        status = "collecting"
        expected_detectable_at = next_run_at
        reason = (
            None
            if next_run_at is not None
            else "No terminal CollectionRun has established an initial baseline."
        )
    else:
        status = "insufficient"
        expected_detectable_at = next_run_at
        failed = all(
            run.state not in CONTENT_BEARING_COLLECTION_STATES for run in latest_by_source.values()
        )
        reason = (
            "All latest terminal CollectionRuns failed or were cancelled."
            if failed
            else (
                None
                if next_run_at is not None
                else "Terminal collection completed without enough baseline content."
            )
        )
    return {
        "status": status,
        "current_count": current_count,
        "required_count": required_count,
        "candidate_count": candidate_count,
        "expected_detectable_at": expected_detectable_at,
        "reason": reason,
        "last_terminal_run_at": last_terminal,
    }


def has_ready_initial_baseline(db: Session, watchlist: Watchlist) -> bool:
    return initial_baseline_projection(db, watchlist)["status"] == "ready"
