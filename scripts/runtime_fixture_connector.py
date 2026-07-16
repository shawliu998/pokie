"""Deterministic cloud connector used only by the Compose acceptance fixture.

The worker still uses its production scheduler, SQLAlchemy adapter, object store,
dedupe, and signal pipeline.  This module replaces only the network transport so
the acceptance run is repeatable and never needs live GitHub credentials.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from connectors.shared.contracts import (
    ConnectorCapabilities,
    ConnectorHealth,
    ConnectorStatus,
    FetchResult,
    RawContentItem,
    SearchPage,
)


class AcceptanceConnector:
    def __init__(self, source_connection_id: str, connector_type: str, variant: str) -> None:
        self.source_connection_id = source_connection_id
        self.connector_type = connector_type
        self.variant = variant

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            connector_type=self.connector_type,
            supports_search=True,
            supports_fetch=True,
            supports_pagination=False,
            supports_incremental=True,
            rate_limit_policy="acceptance-fixture",
            content_kinds=("issue",) if self.connector_type == "github" else ("article",),
        )

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_type=self.connector_type,
            status=ConnectorStatus.HEALTHY,
            checked_at=datetime.now(UTC),
            freshness_state="current",
            details={"transport": "deterministic-acceptance-fixture"},
        )

    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del query, cursor
        captured_at = datetime.now(UTC)
        published_at = captured_at - timedelta(hours=1)
        if self.variant == "first":
            title = "Permission controls slow enterprise onboarding"
            body = "Administrators report that permission review blocks the first team setup."
            author = "acceptance-owner-a"
            external_id = "acceptance-permission-first"
        else:
            title = "Permission approvals need clearer access before launch"
            body = (
                "Reviewers describe access approval as the main permission friction before launch."
            )
            author = "acceptance-owner-b"
            external_id = "acceptance-permission-second"
        raw_body = f"{title}\n{body}".encode()
        item = RawContentItem(
            connector_type=self.connector_type,
            source_connection_id=self.source_connection_id,
            external_id=external_id,
            title=title,
            body=body,
            canonical_url=(
                f"https://github.example.test/glint/issues/{external_id}"
                if self.connector_type == "github"
                else f"https://example.test/glint/{external_id}"
            ),
            author=author,
            published_at=published_at,
            captured_at=captured_at,
            content_version_digest=f"sha256:{hashlib.sha256(raw_body).hexdigest()}",
            raw_digest=f"sha256:{hashlib.sha256(b'raw:' + raw_body).hexdigest()}",
            metadata={"author": author, "fixture_variant": self.variant},
        )
        return SearchPage([item], None, self.health())

    def fetch(self, external_id: str) -> FetchResult:
        page = self.search("permission")
        item = next((item for item in page.items if item.external_id == external_id), None)
        return FetchResult(item, page.health, deleted=item is None)


class AcceptanceConnectorFactory:
    def create(self, source: Any, config: dict[str, Any]) -> AcceptanceConnector:
        del config
        variant = "second" if str(getattr(source, "connector_type", "")) == "rss" else "first"
        return AcceptanceConnector(str(source.id), str(source.connector_type), variant)


def create_acceptance_connector_factory() -> AcceptanceConnectorFactory:
    return AcceptanceConnectorFactory()
