"""Opaque, workspace-bound keyset cursor helpers for public list endpoints."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from typing import Any

from services.api.app.core.errors import ApiError


def encode_cursor(*, workspace_id: str, scope: str, keyset: Mapping[str, str | int]) -> str:
    payload = {
        "v": 1,
        "workspace_id": workspace_id,
        "scope": scope,
        "keyset": dict(keyset),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(*, cursor: str, workspace_id: str, scope: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError
        if payload.get("workspace_id") != workspace_id or payload.get("scope") != scope:
            raise ValueError
        keyset = payload.get("keyset")
        if not isinstance(keyset, dict):
            raise ValueError
        return keyset
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        TypeError,
    ) as exc:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "The pagination cursor is invalid for this workspace or resource.",
        ) from exc


def page_payload(
    *,
    rows: Sequence[Any],
    limit: int,
    items: list[dict[str, Any]],
    workspace_id: str,
    scope: str,
    last_keyset: Mapping[str, str | int] | None,
) -> dict[str, Any]:
    has_more = len(rows) > limit
    return {
        "items": items,
        "page": {
            "next_cursor": (
                encode_cursor(
                    workspace_id=workspace_id,
                    scope=scope,
                    keyset=last_keyset,
                )
                if has_more and items and last_keyset is not None
                else None
            ),
            "has_more": has_more,
        },
    }
