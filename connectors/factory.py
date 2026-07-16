"""Factory for production SourceConnector instances."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from connectors.github.connector import GitHubConnector, GitHubConnectorConfig
from connectors.rss.connector import RssConnector, RssConnectorConfig
from connectors.shared.contracts import (
    ConnectorInvalidCredential,
    ConnectorTransport,
    SourceConnector,
)
from connectors.shared.http_transport import ProductionHttpTransport


class ConnectorFactoryError(RuntimeError):
    """Raised when a SourceConnection cannot be instantiated safely."""


TOKEN_REF_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
GITHUB_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


@dataclass(frozen=True, slots=True)
class EnvironmentSecretResolver:
    """Resolve token refs from env without accepting inline secrets."""

    prefix: str = "GLINT_SECRET_"

    def __call__(self, token_ref: str) -> str:
        logical_name = _env_logical_name(token_ref)
        env_name = self.prefix + logical_name.upper().replace("-", "_").replace(".", "_")
        value = os.environ.get(env_name)
        if value:
            return value
        raise ConnectorInvalidCredential("connector credential reference could not be resolved")


@dataclass(slots=True)
class SourceConnectorFactory:
    transport: ConnectorTransport
    token_resolver: Callable[[str], str] | None = None
    cursor_secret: str | None = None

    def create(self, source: Any, config: dict[str, Any]) -> SourceConnector:
        connector_type = str(getattr(source, "connector_type", "")).lower()
        if connector_type == "github":
            return self._github(source, config)
        if connector_type in {"rss", "atom"}:
            return self._rss(source, config)
        raise ConnectorFactoryError(f"unsupported connector_type: {connector_type}")

    def _github(self, source: Any, config: dict[str, Any]) -> GitHubConnector:
        approved = _approved_config(source)
        owner = config.get("owner")
        repo = config.get("repo")
        repository = config.get("repository")
        if repository and (not owner or not repo):
            owner, separator, repo_name = str(repository).partition("/")
            if separator:
                repo = repo or repo_name
        if not owner or not repo:
            raise ConnectorFactoryError(
                "github connector requires owner and repo in schedule query_json"
            )
        if not GITHUB_SLUG_RE.fullmatch(str(owner)) or not GITHUB_SLUG_RE.fullmatch(str(repo)):
            raise ConnectorFactoryError("github owner/repo contains invalid characters")
        approved_repositories = approved.get("repositories")
        if isinstance(approved_repositories, list):
            approved_match = next(
                (
                    item
                    for item in approved_repositories
                    if isinstance(item, dict)
                    and str(item.get("owner", "")).casefold() == str(owner).casefold()
                    and str(item.get("repository", "")).casefold() == str(repo).casefold()
                ),
                None,
            )
            if approved_match is None:
                raise ConnectorFactoryError(
                    "github repository is outside the approved SourceConnection config"
                )
            for field in ("include_issues", "include_discussions", "include_releases"):
                requested = bool(config.get(field, approved_match.get(field, True)))
                if requested and not bool(approved_match.get(field, True)):
                    raise ConnectorFactoryError(
                        "github schedule exceeds approved repository capabilities"
                    )
        else:
            approved_owner = approved.get("owner")
            approved_repo = approved.get("repo")
            approved_repository = approved.get("repository")
            if approved_repository and (not approved_owner or not approved_repo):
                approved_owner, separator, approved_repo_name = str(approved_repository).partition(
                    "/"
                )
                if separator:
                    approved_repo = approved_repo or approved_repo_name
            if approved_owner is not None and str(owner) != str(approved_owner):
                raise ConnectorFactoryError(
                    "github owner is outside the approved SourceConnection config"
                )
            if approved_repo is not None and str(repo) != str(approved_repo):
                raise ConnectorFactoryError(
                    "github repo is outside the approved SourceConnection config"
                )
        token_ref = getattr(source, "credential_ref", None)
        if token_ref:
            _env_logical_name(str(token_ref))
        return GitHubConnector(
            GitHubConnectorConfig(
                source_connection_id=source.id,
                owner=str(owner),
                repo=str(repo),
                token_ref=str(token_ref) if token_ref else None,
                include_repository=bool(config.get("include_repository", True)),
                include_issues=bool(config.get("include_issues", True)),
                include_discussions=bool(config.get("include_discussions", True)),
                include_releases=bool(config.get("include_releases", True)),
                per_page=int(config.get("per_page", 100)),
                cursor_secret=self.cursor_secret,
            ),
            self.transport,
            self.token_resolver,
        )

    def _rss(self, source: Any, config: dict[str, Any]) -> RssConnector:
        approved = _approved_config(source)
        feed_url = config.get("feed_url") or config.get("url")
        if not feed_url:
            raise ConnectorFactoryError("rss connector requires feed_url in schedule query_json")
        approved_feeds = approved.get("feeds")
        if isinstance(approved_feeds, list):
            approved_feed = next(
                (
                    item
                    for item in approved_feeds
                    if isinstance(item, dict) and str(item.get("feed_url")) == str(feed_url)
                ),
                None,
            )
            if approved_feed is None:
                raise ConnectorFactoryError(
                    "rss feed_url is outside the approved SourceConnection config"
                )
            config = {**config, "feed_title": config.get("feed_title") or approved_feed.get("name")}
        else:
            approved_url = approved.get("feed_url") or approved.get("url")
            if approved_url is not None and str(feed_url) != str(approved_url):
                raise ConnectorFactoryError(
                    "rss feed_url is outside the approved SourceConnection config"
                )
        return RssConnector(
            RssConnectorConfig(
                source_connection_id=source.id,
                feed_url=str(feed_url),
                feed_title=config.get("feed_title"),
                timeout_seconds=float(config.get("timeout_seconds", 10.0)),
                max_redirects=int(config.get("max_redirects", 3)),
                max_response_bytes=int(config.get("max_response_bytes", 2_000_000)),
            ),
            self.transport,
        )


def create_connector_factory() -> SourceConnectorFactory:
    max_bytes = int(os.environ.get("GLINT_CONNECTOR_MAX_RESPONSE_BYTES", "2000000"))
    return SourceConnectorFactory(
        transport=ProductionHttpTransport(max_response_bytes=max_bytes),
        token_resolver=EnvironmentSecretResolver(),
        cursor_secret=_production_cursor_secret(),
    )


def _approved_config(source: Any) -> dict[str, Any]:
    freshness = getattr(source, "freshness", {}) or {}
    if isinstance(freshness, dict) and isinstance(freshness.get("config"), dict):
        return dict(freshness["config"])
    config = getattr(source, "config_json", None)
    return dict(config) if isinstance(config, dict) else {}


def _production_cursor_secret() -> str | None:
    secret = os.environ.get("GLINT_CONNECTOR_CURSOR_SECRET")
    mode = os.environ.get("GLINT_WORKER_MODE", "production")
    if mode in {"test", "dev"} and not secret:
        return None
    if not secret:
        raise ConnectorFactoryError("GLINT_CONNECTOR_CURSOR_SECRET is required in production")
    if len(secret.encode("utf-8")) < 32 or len(set(secret)) < 8:
        raise ConnectorFactoryError(
            "GLINT_CONNECTOR_CURSOR_SECRET must be at least 32 bytes and high entropy"
        )
    return secret


def _env_logical_name(token_ref: str) -> str:
    parts = urlsplit(token_ref)
    if parts.scheme != "env" or parts.username or parts.password or parts.query or parts.fragment:
        raise ConnectorFactoryError(
            "only env:// credential references are supported by this worker"
        )
    if parts.path not in {"", "/"}:
        raise ConnectorFactoryError("env credential references must use env://logical-name")
    logical_name = parts.netloc
    if not TOKEN_REF_RE.fullmatch(logical_name):
        raise ConnectorFactoryError("connector credential reference contains invalid characters")
    return logical_name
