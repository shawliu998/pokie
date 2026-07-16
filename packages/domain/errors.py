"""Shared exceptions for Glint's dependency-free domain layer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)
class DomainError(Exception):
    """Base class for a safe, typed domain failure.

    ``message`` and ``details`` are suitable for an API error envelope.  Callers
    must still run them through the redactor before logging.
    """

    message: str
    code: str = "DOMAIN_ERROR"
    details: Mapping[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class InvariantViolation(DomainError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "INVARIANT_VIOLATION",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code, details)


class InvalidTransition(DomainError):
    def __init__(
        self,
        aggregate: str,
        current: str,
        requested: str,
    ) -> None:
        super().__init__(
            f"{aggregate} cannot transition from {current!r} using {requested!r}.",
            "INVALID_STATE",
            {"aggregate": aggregate, "current": current, "requested": requested},
        )


class ConsentRejected(DomainError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "CONSENT_EXPIRED_OR_REVOKED",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code, details)


class ObjectScopeMismatch(DomainError):
    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, "OBJECT_SCOPE_MISMATCH", details)


class DigestMismatch(DomainError):
    def __init__(self, field: str, expected: str, actual: str) -> None:
        super().__init__(
            f"Digest mismatch for {field}.",
            "DIGEST_MISMATCH",
            {"field": field, "expected": expected, "actual": actual},
        )


class WorkspaceScopeViolation(DomainError):
    def __init__(self, message: str = "Resource is outside the active workspace.") -> None:
        # Deliberately omit foreign resource identifiers.
        super().__init__(message, "NOT_FOUND")


class UnsafeValue(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "UNSAFE_VALUE")
