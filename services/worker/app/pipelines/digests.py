"""Stable digest and UUID helpers for deterministic worker output."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid5

GLINT_NAMESPACE = UUID("019f6531-d58f-7860-a154-30c7a89f433d")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_json_digest(value: object) -> str:
    return sha256_text(canonical_json(value))


def deterministic_id(kind: str, *parts: object) -> str:
    return str(uuid5(GLINT_NAMESPACE, canonical_json([kind, *parts])))
