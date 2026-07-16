"""Fail-safe secret and local filesystem path scrubbing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .errors import UnsafeValue

REDACTED_SECRET = "[REDACTED_SECRET]"
REDACTED_PATH = "[REDACTED_PATH]"

_SECRET_KEY = re.compile(
    r"(?:^|_)(?:authorization|proxy_authorization|api_key|apikey|access_token|"
    r"refresh_token|id_token|token|password|passwd|secret|client_secret|cookie|"
    r"set_cookie|private_key|credential|signed_url|upload_grant)(?:$|_)",
    re.IGNORECASE,
)
_PATH_KEY = re.compile(
    r"(?:^|_)(?:path|file_path|filesystem_path|local_path|absolute_path)(?:$|_)",
    re.IGNORECASE,
)

_PATH_PATTERNS = (
    re.compile(r"file://(?:localhost)?/(?:[^\s\"'<>]+)"),
    re.compile(r"(?<![\w])/(?:Users|home|private|Volumes|tmp|var/folders)/[^\s\"'<>]+"),
    re.compile(r"(?<![\w])[A-Za-z]:\\(?:[^\s\"'<>]+)"),
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(?:sk|gh[opusr]|github_pat)_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    re.compile(
        r"(?i)([?&](?:x-amz-signature|x-amz-credential|signature|sig|token|"
        r"access_token|api_key|password|secret|credential)=)[^&#\s]+"
    ),
)


def is_secret_key(key: object) -> bool:
    return isinstance(key, str) and _SECRET_KEY.search(key.replace("-", "_")) is not None


def is_path_key(key: object) -> bool:
    return isinstance(key, str) and _PATH_KEY.search(key.replace("-", "_")) is not None


def contains_local_path(value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in _PATH_PATTERNS)


def contains_secret(value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in _SECRET_PATTERNS)


def redact_text(value: str) -> str:
    """Replace known credential shapes and absolute local paths in free text."""

    result = value
    for pattern in _PATH_PATTERNS:
        result = pattern.sub(REDACTED_PATH, result)
    for index, pattern in enumerate(_SECRET_PATTERNS):
        if index == len(_SECRET_PATTERNS) - 1:
            # Keep a URL's parameter name for diagnostics while dropping value.
            result = pattern.sub(lambda match: match.group(1) + REDACTED_SECRET, result)
        else:
            result = pattern.sub(REDACTED_SECRET, result)
    return result


def redact(value: Any) -> Any:
    """Recursively return a JSON-like, secret-free diagnostic representation."""

    if is_dataclass(value) and not isinstance(value, type):
        return redact(asdict(value))
    if isinstance(value, Enum):
        return redact(value.value)
    if isinstance(value, Mapping):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if is_secret_key(key):
                result[key] = REDACTED_SECRET
            elif is_path_key(key):
                result[key] = REDACTED_PATH if item is not None else None
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, set):
        return {redact(item) for item in value}
    if isinstance(value, str):
        return redact_text(value)
    return value


def assert_safe_diagnostic(value: Any) -> None:
    """Reject a payload if scrubbing would change it.

    Use this at persistence/event boundaries that must never accept secrets or a
    Mac path.  Logging code normally uses :func:`redact` instead.
    """

    if _contains_unsafe_value(value):
        raise UnsafeValue("Payload contains a secret or local filesystem path.")


def _contains_unsafe_value(value: Any) -> bool:
    if is_dataclass(value) and not isinstance(value, type):
        return _contains_unsafe_value(asdict(value))
    if isinstance(value, Enum):
        return _contains_unsafe_value(value.value)
    if isinstance(value, Mapping):
        return any(
            (is_secret_key(key) and item is not None)
            or (is_path_key(key) and item is not None)
            or _contains_unsafe_value(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple | set):
        return any(_contains_unsafe_value(item) for item in value)
    return isinstance(value, str) and (contains_secret(value) or contains_local_path(value))


def assert_no_local_path(value: Any) -> None:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        for key, item in value.items():
            if is_path_key(key) and item is not None:
                raise UnsafeValue("A local filesystem path cannot cross this boundary.")
            assert_no_local_path(item)
    elif isinstance(value, list | tuple | set):
        for item in value:
            assert_no_local_path(item)
    elif isinstance(value, str) and contains_local_path(value):
        raise UnsafeValue("A local filesystem path cannot cross this boundary.")
