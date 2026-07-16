"""Deterministic connector helpers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
}


def sha256_digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_digest_text(value: str) -> str:
    return sha256_digest_bytes(value.encode("utf-8"))


def canonical_json_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_digest_text(encoded)


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    if scheme not in {"http", "https"}:
        return None
    if parts.username or parts.password:
        return None
    if not parts.hostname:
        return None
    netloc = parts.hostname.lower()
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    path = re.sub(r"/+$", "", parts.path or "/")
    query = urlencode(
        [
            (key, value)
            for key, value in sorted(parse_qsl(parts.query, keep_blank_values=True))
            if key not in TRACKING_PARAMS
        ]
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError:
        try:
            return parsedate_to_datetime(value).astimezone(UTC)
        except (TypeError, ValueError):
            return None


def collapse_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
