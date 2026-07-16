"""Optimistic Signal disposition transitions and cooldown audit semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from services.api.app.core.errors import ApiError, invalid_state, version_conflict
from services.api.app.db.models import Signal, new_id
from services.api.app.modules.common import audit, utcnow

_TRANSITIONS = {
    ("triaged", "investigate"): "investigating",
    ("monitoring", "investigate"): "investigating",
    ("investigating", "explain"): "explained",
    ("new", "monitor"): "monitoring",
    ("triaged", "monitor"): "monitoring",
    ("investigating", "monitor"): "monitoring",
    ("explained", "monitor"): "monitoring",
    ("new", "dismiss"): "dismissed",
    ("triaged", "dismiss"): "dismissed",
    ("explained", "dismiss"): "dismissed",
    ("monitoring", "dismiss"): "dismissed",
}


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        raw = str(value)
        result = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ApiError(422, "VALIDATION_ERROR", "Signal transition time must be timezone-aware.")
    return result.astimezone(UTC)


def transition_signal(
    db: Session,
    *,
    signal: Signal,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> Signal:
    if signal.row_version != int(payload["expected_row_version"]):
        raise version_conflict(signal.id, signal.row_version)
    action = str(payload["action"])
    session_id = str(payload["session_id"])
    note = payload.get("note")
    now = utcnow()
    before = {
        "status": signal.status,
        "row_version": signal.row_version,
        "disposition": signal.disposition_json or None,
    }
    if action == "undo":
        current = dict(signal.disposition_json or {})
        if (
            signal.status not in {"monitoring", "dismissed"}
            or current.get("action") not in {"monitor", "dismiss"}
            or current.get("session_id") != session_id
            or current.get("undone_at") is not None
        ):
            raise invalid_state("Undo is limited to the current session and current disposition.")
        signal.status = str(current["previous_status"])
        signal.disposition_json = {
            **current,
            "action": "undo",
            "transitioned_by": actor_id,
            "transitioned_at": now.isoformat(),
            "undone_at": now.isoformat(),
        }
    else:
        target = _TRANSITIONS.get((signal.status, action))
        if target is None:
            raise invalid_state(f"Signal cannot {action} from {signal.status}.")
        cooldown_until = _parse_datetime(payload.get("cooldown_until"))
        if action == "monitor" and (cooldown_until is None or cooldown_until <= now):
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Keep monitoring requires a future cooldown_until.",
            )
        prior = dict(signal.disposition_json or {})
        if (
            signal.status == "monitoring"
            and action == "investigate"
            and prior.get("previous_status") not in {"triaged", "investigating", "explained"}
        ):
            raise invalid_state("Signal must be atomically triaged before investigation.")
        breaking_cooldown = False
        prior_cooldown = _parse_datetime(prior.get("cooldown_until"))
        if (
            signal.status == "monitoring"
            and action == "investigate"
            and prior.get("action") == "monitor"
            and prior_cooldown is not None
            and prior_cooldown > now
        ):
            if not note:
                raise ApiError(
                    422,
                    "COOLDOWN_BREAK_REASON_REQUIRED",
                    "Explain the independent source or significant change that broke cooldown.",
                )
            breaking_cooldown = True
        signal.disposition_json = {
            "transition_id": new_id(),
            "action": action,
            "previous_status": signal.status,
            "session_id": session_id,
            "monitoring_snapshot": (
                {
                    "detector_version": signal.detector_version,
                    "window": signal.window_json,
                    "metrics": signal.metrics_json,
                    "signal_row_version": signal.row_version,
                }
                if action == "monitor"
                else prior.get("monitoring_snapshot")
            ),
            "cooldown_until": (
                cooldown_until.isoformat()
                if cooldown_until is not None
                else prior.get("cooldown_until")
            ),
            "dismiss_reason": payload.get("dismiss_reason"),
            "note": note,
            "transitioned_by": actor_id,
            "transitioned_at": now.isoformat(),
            "cooldown_broken_at": now.isoformat() if breaking_cooldown else None,
            "cooldown_break_reason": str(note) if breaking_cooldown else None,
            "undone_at": None,
        }
        signal.status = target
    signal.row_version += 1
    audit_action = (
        "signal.cooldown_broken"
        if signal.disposition_json.get("cooldown_broken_at")
        else "signal.transitioned"
    )
    audit(
        db,
        workspace_id=signal.workspace_id,
        actor_id=actor_id,
        action=audit_action,
        target_type="Signal",
        target_id=signal.id,
        request_id=request_id,
        before=before,
        after={
            "status": signal.status,
            "row_version": signal.row_version,
            "disposition": signal.disposition_json,
        },
        reason=str(note) if note else None,
    )
    db.commit()
    return signal
