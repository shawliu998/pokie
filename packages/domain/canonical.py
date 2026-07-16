"""Canonical JSON and SHA-256 helpers used by immutable snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from .errors import DigestMismatch, InvariantViolation

SHA256_PREFIX = "sha256:"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _canonical_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvariantViolation("Canonical datetimes must be timezone-aware.")
    utc = value.astimezone(UTC)
    text = utc.isoformat(timespec="microseconds")
    if text.endswith(".000000+00:00"):
        text = text.replace(".000000+00:00", "Z")
    elif text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def _normalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _canonical_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvariantViolation("NaN and infinity are not canonical JSON values.")
        # JSON's shortest round-trippable representation is stable on supported
        # CPython versions.  Negative zero is normalized to avoid two digests for
        # the same domain value.
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise InvariantViolation("Canonical JSON object keys must be strings.")
            key = unicodedata.normalize("NFC", raw_key)
            if key in normalized:
                raise InvariantViolation(
                    "Canonical JSON contains duplicate keys after Unicode normalization."
                )
            normalized[key] = _normalize(raw_value)
        return normalized
    if isinstance(value, list | tuple):
        return [_normalize(item) for item in value]
    raise InvariantViolation(f"Unsupported canonical JSON value type: {type(value).__name__}.")


def canonical_json(value: Any) -> str:
    """Return stable UTF-8 JSON with normalized strings and sorted object keys."""

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def digest_bytes(value: bytes | bytearray | memoryview) -> str:
    return SHA256_PREFIX + hashlib.sha256(bytes(value)).hexdigest()


def digest_text(value: str) -> str:
    return digest_bytes(unicodedata.normalize("NFC", value).encode("utf-8"))


def canonical_digest(value: Any) -> str:
    return digest_bytes(canonical_json_bytes(value))


def is_sha256_digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def require_sha256_digest(value: str, *, field: str = "digest") -> str:
    if not is_sha256_digest(value):
        raise InvariantViolation(
            f"{field} must use the lowercase sha256:<64 hex chars> format.",
            details={"field": field},
        )
    return value


def verify_digest(
    value: Any,
    expected: str,
    *,
    field: str = "value",
    canonical: bool = True,
) -> None:
    require_sha256_digest(expected, field=field)
    if canonical:
        actual = canonical_digest(value)
    elif isinstance(value, str):
        actual = digest_text(value)
    elif isinstance(value, bytes | bytearray | memoryview):
        actual = digest_bytes(value)
    else:
        raise InvariantViolation("Non-canonical digest verification accepts only text or bytes.")
    if actual != expected:
        raise DigestMismatch(field, expected, actual)
