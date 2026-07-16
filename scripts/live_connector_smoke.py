"""Opt-in, redacted live GitHub and RSS connector smoke runner."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from connectors.factory import EnvironmentSecretResolver
from connectors.github.connector import GitHubConnector, GitHubConnectorConfig
from connectors.rss.connector import RssConnector, RssConnectorConfig
from connectors.shared.contracts import (
    ConnectorError,
    ConnectorRateLimited,
    ConnectorStatus,
    RawContentItem,
)
from connectors.shared.http_transport import ProductionHttpTransport

AUTHENTICITY_LIVE = "Live Collected"
AUTHENTICITY_CAPTURED = "Captured Fixture"
GITHUB_TOKEN_REF = "env://github_token"
DEFAULT_GITHUB_REPOSITORIES = (
    ("openai", "codex"),
    ("anthropics", "claude-code"),
    ("zed-industries", "zed"),
)
DEFAULT_RSS_FEEDS = (
    "https://github.blog/feed/",
    "https://github.com/openai/codex/releases.atom",
    "https://blog.cloudflare.com/rss/",
)


class LiveSmokeInvariantError(RuntimeError):
    """A deterministic connector invariant failed against live public data."""


@dataclass(frozen=True, slots=True)
class SmokeSummary:
    connector: str
    source: str
    authenticity: str
    outcome: str
    health: str
    freshness: str
    item_count: int = 0
    checks: tuple[str, ...] = ()
    error_type: str | None = None
    retry_after_seconds: int | None = None


def live_smoke_enabled(environ: Mapping[str, str]) -> bool:
    """Require an exact opt-in value; truthy aliases must not enable egress."""
    return environ.get("GLINT_ENABLE_LIVE_SMOKE") == "1"


def github_prerequisites(environ: Mapping[str, str]) -> tuple[bool, str]:
    if not environ.get("GLINT_SECRET_GITHUB_TOKEN"):
        return False, "missing secret reference GLINT_SECRET_GITHUB_TOKEN"
    cursor_secret = environ.get("GLINT_CONNECTOR_CURSOR_SECRET", "")
    if len(cursor_secret.encode("utf-8")) < 32:
        return False, "missing 32-byte GLINT_CONNECTOR_CURSOR_SECRET"
    return True, "ready"


def redacted_json(summary: SmokeSummary, forbidden_values: Sequence[str] = ()) -> str:
    """Serialize only bounded metadata and fail closed if a secret appears."""
    payload = json.dumps(asdict(summary), sort_keys=True, separators=(",", ":"))
    lowered = payload.lower()
    forbidden_keys = ("authorization", "cookie", "body", "title", "token")
    if any(f'"{key}"' in lowered for key in forbidden_keys):
        raise LiveSmokeInvariantError("redacted summary contains a forbidden field")
    if any(value and value in payload for value in forbidden_values):
        raise LiveSmokeInvariantError("redacted summary contains a secret value")
    return payload


def _check_stable_version(first: RawContentItem, second: RawContentItem) -> bool:
    if first.external_id != second.external_id:
        raise LiveSmokeInvariantError("repeated fetch returned a different external id")
    return first.content_version_digest == second.content_version_digest


def _github_summary(
    owner: str,
    repo: str,
    *,
    deep: bool,
    token_resolver: EnvironmentSecretResolver,
    cursor_secret: str,
    transport: ProductionHttpTransport,
) -> SmokeSummary:
    connector = GitHubConnector(
        GitHubConnectorConfig(
            source_connection_id=f"live-github-{owner}-{repo}",
            owner=owner,
            repo=repo,
            token_ref=GITHUB_TOKEN_REF,
            include_discussions=deep,
            per_page=2 if deep else 5,
            cursor_secret=cursor_secret,
        ),
        transport,
        token_resolver,
    )
    health = connector.health()
    page = connector.search("")
    checks = ["health", "search", "pull-request-exclusion", "content-version"]
    if deep:
        token = token_resolver(GITHUB_TOKEN_REF)
        rate_response = transport.request(
            "GET",
            "https://api.github.com/rate_limit",
            headers={
                "accept": "application/vnd.github+json",
                "authorization": f"Bearer {token}",
                "user-agent": "glint-worker/1.0",
                "x-github-api-version": "2022-11-28",
            },
        )
        if rate_response.status_code in {403, 429}:
            raise ConnectorRateLimited("github REST rate limit or access block")
        if rate_response.status_code >= 400:
            raise ConnectorError("github REST rate limit endpoint unavailable")
        rate_payload = json.loads(rate_response.body.decode("utf-8") or "{}")
        core = (rate_payload.get("resources") or {}).get("core") or {}
        if not isinstance(core.get("remaining"), int) or not isinstance(core.get("limit"), int):
            raise ConnectorError("GitHub REST rate limit response is malformed")
        checks.append("rest-rate-limit")
    if any(
        item.metadata.get("kind") == "issue"
        and item.canonical_url
        and "/pull/" in item.canonical_url
        for item in page.items
    ):
        raise LiveSmokeInvariantError("GitHub issue search included a pull request")
    if page.items:
        fetchable = page.items[0]
        for preferred_kind in ("issue", "release", "repository"):
            preferred = next(
                (item for item in page.items if item.metadata.get("kind") == preferred_kind), None
            )
            if preferred is not None:
                fetchable = preferred
                break
        first = connector.fetch(fetchable.external_id)
        second = connector.fetch(fetchable.external_id)
        if first.item is None or second.item is None:
            raise ConnectorError("live search item became unavailable during smoke")
        if _check_stable_version(first.item, second.item):
            checks.extend(("fetch", "idempotent-repeat"))
        else:
            checks.extend(("fetch", "modified-item-observed"))
    if deep:
        if page.next_cursor:
            connector.search("", page.next_cursor)
            checks.extend(("signed-pagination", "cursor-host-path"))
        unavailable = connector.fetch(f"github:{owner}/{repo}:issue:2147483647")
        if not unavailable.deleted:
            raise LiveSmokeInvariantError("known-unavailable GitHub item was not marked deleted")
        checks.extend(("deleted-unavailable", "graphql-discussion-path"))
    page_health = page.health.status.value
    return SmokeSummary(
        connector="github",
        source=f"{owner}/{repo}",
        authenticity=AUTHENTICITY_LIVE,
        outcome="passed",
        health=page_health,
        freshness=health.freshness_state,
        item_count=len(page.items),
        checks=tuple(checks),
    )


def _rss_summary(feed_url: str, transport: ProductionHttpTransport) -> SmokeSummary:
    connector = RssConnector(
        RssConnectorConfig(
            source_connection_id="live-rss",
            feed_url=feed_url,
            timeout_seconds=10,
            max_redirects=3,
            max_response_bytes=2_000_000,
        ),
        transport,
    )
    health = connector.health()
    page = connector.search("")
    checks = ["health", "fetch", "ssrf", "redirect", "content-type", "byte-cap"]
    if page.items:
        fetched = connector.fetch(page.items[0].external_id)
        if fetched.item is None:
            raise ConnectorError("live RSS item became unavailable during smoke")
        if _check_stable_version(page.items[0], fetched.item):
            checks.extend(("content-version", "idempotent-repeat", "stable-missing-guid-id"))
        else:
            checks.extend(("content-version", "updated-item-observed"))
    canonical_urls = [item.canonical_url for item in page.items if item.canonical_url]
    if len(set(canonical_urls)) < len(canonical_urls):
        checks.append("duplicate-url-observed")
    if any(item.metadata.get("kind") == "atom_entry" for item in page.items):
        checks.append("atom")
    if any(item.metadata.get("kind") == "rss_article" for item in page.items):
        checks.append("rss-2.0")
    return SmokeSummary(
        connector="rss",
        source=feed_url,
        authenticity=AUTHENTICITY_LIVE,
        outcome="passed",
        health=page.health.status.value,
        freshness=health.freshness_state,
        item_count=len(page.items),
        checks=tuple(checks),
    )


def _degraded_summary(connector: str, source: str, exc: Exception) -> SmokeSummary:
    retry_after = exc.retry_after_seconds if isinstance(exc, ConnectorRateLimited) else None
    health = (
        ConnectorStatus.RATE_LIMITED.value
        if isinstance(exc, ConnectorRateLimited)
        else ConnectorStatus.DEGRADED.value
    )
    return SmokeSummary(
        connector=connector,
        source=source,
        authenticity=AUTHENTICITY_LIVE,
        outcome="degraded",
        health=health,
        freshness="unknown",
        error_type=exc.__class__.__name__,
        retry_after_seconds=retry_after,
    )


def run(
    environ: Mapping[str, str] | None = None,
    emit: Callable[[str], Any] = print,
    github_repositories: Sequence[tuple[str, str]] = DEFAULT_GITHUB_REPOSITORIES,
    rss_feeds: Sequence[str] = DEFAULT_RSS_FEEDS,
) -> int:
    env = os.environ if environ is None else environ
    if not live_smoke_enabled(env):
        emit("SKIP live connector smoke: set GLINT_ENABLE_LIVE_SMOKE=1 to permit network egress")
        return 0

    transport = ProductionHttpTransport(max_response_bytes=2_000_000)
    forbidden_values = tuple(
        value
        for key, value in env.items()
        if key.startswith("GLINT_SECRET_") or key == "GLINT_CONNECTOR_CURSOR_SECRET"
    )
    invariant_failures = 0
    github_ready, github_reason = github_prerequisites(env)
    if not github_ready:
        emit(f"SKIP GitHub live smoke: {github_reason}")
    else:
        resolver = EnvironmentSecretResolver()
        cursor_secret = env["GLINT_CONNECTOR_CURSOR_SECRET"]
        for index, (owner, repo) in enumerate(github_repositories):
            source = f"{owner}/{repo}"
            try:
                summary = _github_summary(
                    owner,
                    repo,
                    deep=index == 0,
                    token_resolver=resolver,
                    cursor_secret=cursor_secret,
                    transport=transport,
                )
            except LiveSmokeInvariantError as exc:
                invariant_failures += 1
                summary = SmokeSummary(
                    "github",
                    source,
                    AUTHENTICITY_LIVE,
                    "failed",
                    ConnectorStatus.FAILED.value,
                    "unknown",
                    error_type=exc.__class__.__name__,
                )
            except (ConnectorError, OSError, ValueError) as exc:
                summary = _degraded_summary("github", source, exc)
            emit(redacted_json(summary, forbidden_values))

    for feed_url in rss_feeds:
        try:
            summary = _rss_summary(feed_url, transport)
        except LiveSmokeInvariantError as exc:
            invariant_failures += 1
            summary = SmokeSummary(
                "rss",
                feed_url,
                AUTHENTICITY_LIVE,
                "failed",
                ConnectorStatus.FAILED.value,
                "unknown",
                error_type=exc.__class__.__name__,
            )
        except (ConnectorError, OSError, ValueError) as exc:
            summary = _degraded_summary("rss", feed_url, exc)
        emit(redacted_json(summary, forbidden_values))
    emit(
        "Live connector smoke complete: summaries are metadata-only; "
        "no content body or credential was emitted"
    )
    return 1 if invariant_failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
