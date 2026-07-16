"""SourceConnector contract shared by GitHub and RSS adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol


class ConnectorStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    DISABLED = "disabled"


class ConnectorError(RuntimeError):
    status: ConnectorStatus = ConnectorStatus.FAILED
    retryable: bool = False


class ConnectorTimeout(ConnectorError):
    retryable = True


class ConnectorRateLimited(ConnectorError):
    status = ConnectorStatus.RATE_LIMITED
    retryable = True

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ConnectorInvalidCredential(ConnectorError):
    status = ConnectorStatus.AUTH_REQUIRED


class ConnectorPartialFailure(ConnectorError):
    status = ConnectorStatus.DEGRADED
    retryable = True

    def __init__(self, message: str, items: list[RawContentItem] | None = None) -> None:
        super().__init__(message)
        self.items = items or []


@dataclass(frozen=True, slots=True)
class RawContentItem:
    connector_type: str
    source_connection_id: str
    external_id: str
    title: str
    body: str
    canonical_url: str | None
    author: str | None
    published_at: datetime | None
    captured_at: datetime
    content_version_digest: str
    raw_digest: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConnectorCapabilities:
    connector_type: str
    supports_search: bool
    supports_fetch: bool
    supports_pagination: bool
    supports_incremental: bool
    rate_limit_policy: str
    content_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    connector_type: str
    status: ConnectorStatus
    checked_at: datetime
    freshness_state: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: list[RawContentItem]
    next_cursor: str | None
    health: ConnectorHealth


@dataclass(frozen=True, slots=True)
class FetchResult:
    item: RawContentItem | None
    health: ConnectorHealth
    deleted: bool = False


class SourceConnector(Protocol):
    connector_type: str

    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        """Return normalized raw content items for a query/page."""
        ...

    def fetch(self, external_id: str) -> FetchResult:
        """Fetch one item by connector-specific external ID."""
        ...

    def health(self) -> ConnectorHealth:
        """Return source health without leaking credentials."""
        ...

    def capabilities(self) -> ConnectorCapabilities:
        """Return stable connector capabilities."""
        ...


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    url: str


class ConnectorTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
        expected_addresses: tuple[str, ...] | None = None,
    ) -> TransportResponse:
        """Perform one connector request."""
        ...


def checked_at() -> datetime:
    return datetime.now(tz=UTC)
