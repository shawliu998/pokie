"""GitHub connector for repositories, issues, discussions, and releases."""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

from connectors.shared.contracts import (
    ConnectorCapabilities,
    ConnectorHealth,
    ConnectorInvalidCredential,
    ConnectorPartialFailure,
    ConnectorRateLimited,
    ConnectorStatus,
    ConnectorTransport,
    FetchResult,
    RawContentItem,
    SearchPage,
    TransportResponse,
    checked_at,
)
from connectors.shared.utils import (
    canonical_json_digest,
    canonicalize_url,
    collapse_text,
    parse_datetime,
)


@dataclass(frozen=True, slots=True)
class GitHubConnectorConfig:
    source_connection_id: str
    owner: str
    repo: str
    token_ref: str | None = None
    include_repository: bool = True
    include_issues: bool = True
    include_discussions: bool = True
    include_releases: bool = True
    api_base_url: str = "https://api.github.com"
    graphql_url: str = "https://api.github.com/graphql"
    per_page: int = 100
    cursor_secret: str | None = None


class GitHubConnector:
    connector_type = "github"

    def __init__(
        self,
        config: GitHubConnectorConfig,
        transport: ConnectorTransport,
        token_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.token_resolver = token_resolver

    def capabilities(self) -> ConnectorCapabilities:
        kinds = ["repository", "issue", "release"]
        if self.config.include_discussions:
            kinds.append("discussion" if self.config.token_ref else "discussion:auth_required")
        return ConnectorCapabilities(
            connector_type=self.connector_type,
            supports_search=True,
            supports_fetch=True,
            supports_pagination=True,
            supports_incremental=True,
            rate_limit_policy="github-rest-graphql-v1",
            content_kinds=tuple(kinds),
        )

    def health(self) -> ConnectorHealth:
        url = self._url(f"/repos/{self.config.owner}/{self.config.repo}")
        response = self.transport.request("GET", url, headers=self._headers())
        if response.status_code == 401:
            raise ConnectorInvalidCredential("github credential rejected")
        if response.status_code in {403, 429}:
            raise ConnectorRateLimited(
                "github rate limit or access block", _retry_after(response.headers)
            )
        if response.status_code >= 400:
            return ConnectorHealth(
                self.connector_type,
                ConnectorStatus.FAILED,
                checked_at(),
                "failed",
                {"status_code": response.status_code},
            )
        return ConnectorHealth(
            self.connector_type,
            ConnectorStatus.HEALTHY,
            checked_at(),
            "current",
            {"repository": f"{self.config.owner}/{self.config.repo}"},
        )

    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        if cursor:
            composite = self._decode_cursor(cursor)
            if composite is not None:
                self._validate_composite_cursor(composite)
                return self._search_composite_cursor(query, composite)
            if cursor.startswith("graphql:discussions:"):
                return self._search_discussions(query, cursor.removeprefix("graphql:discussions:"))
            response = self._request(cursor)
            items = self._parse_response_items(cursor, response)
            return SearchPage(
                _filter_items(items, query),
                _next_link(response.headers),
                _health_from_response(self.connector_type, response.status_code),
            )

        all_items: list[RawContentItem] = []
        cursors: dict[str, str] = {}
        urls = self._search_urls()
        degraded_reasons: list[str] = []
        failed_reasons: list[str] = []
        statuses: list[ConnectorStatus] = []
        for kind, url in urls:
            response = self._request(url)
            items = self._parse_response_items(url, response)
            all_items.extend(items)
            response_health = _health_from_response(self.connector_type, response.status_code)
            statuses.append(response_health.status)
            if response_health.status == ConnectorStatus.FAILED:
                failed_reasons.append(f"{kind}:{response.status_code}")
            next_url = _next_link(response.headers)
            if next_url:
                cursors[kind] = next_url
        if self.config.include_discussions:
            if not self.config.token_ref or not self.token_resolver:
                degraded_reasons.append("discussions_require_graphql_token")
            else:
                try:
                    page = self._search_discussions(query, None)
                    all_items.extend(page.items)
                    if page.next_cursor:
                        cursors["discussions"] = page.next_cursor.removeprefix(
                            "graphql:discussions:"
                        )
                    statuses.append(page.health.status)
                    if page.health.status != ConnectorStatus.HEALTHY:
                        degraded_reasons.append("discussions_degraded")
                except ConnectorInvalidCredential:
                    degraded_reasons.append("discussions_auth_required")
                except ConnectorPartialFailure as exc:
                    all_items.extend(exc.items)
                    degraded_reasons.append("discussions_partial_failure")
        status = _worst_status(statuses + ([ConnectorStatus.DEGRADED] if degraded_reasons else []))
        details = {}
        if degraded_reasons:
            details["degraded_reasons"] = degraded_reasons
        if failed_reasons:
            details["failed_reasons"] = failed_reasons
        health = ConnectorHealth(
            self.connector_type,
            status,
            checked_at(),
            "current"
            if status == ConnectorStatus.HEALTHY
            else ("failed" if status == ConnectorStatus.FAILED else "degraded"),
            details,
        )
        return SearchPage(_filter_items(all_items, query), self._encode_cursor(cursors), health)

    def fetch(self, external_id: str) -> FetchResult:
        if ":discussion:" in external_id:
            return self._fetch_discussion(external_id)
        url = self._fetch_url(external_id)
        response = self._request(url)
        if response.status_code == 404:
            return FetchResult(
                None,
                ConnectorHealth(
                    self.connector_type,
                    ConnectorStatus.DEGRADED,
                    checked_at(),
                    "deleted",
                    {"external_id": external_id},
                ),
                deleted=True,
            )
        items = self._parse_response_items(url, response)
        item = items[0] if items else None
        return FetchResult(
            item, _health_from_response(self.connector_type, response.status_code), deleted=False
        )

    def _fetch_discussion(self, external_id: str) -> FetchResult:
        if not self.config.token_ref or not self.token_resolver:
            raise ConnectorInvalidCredential("github discussions require graphql token")
        number_text = external_id.rsplit(":discussion:", 1)[-1]
        try:
            number = int(number_text)
        except ValueError:
            raise ValueError(
                "discussion external_id must end with a numeric discussion number"
            ) from None
        payload = {
            "query": DISCUSSION_QUERY,
            "variables": {"owner": self.config.owner, "name": self.config.repo, "number": number},
        }
        response = self.transport.request(
            "POST",
            self.config.graphql_url,
            headers=self._graphql_headers(),
            body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        if response.status_code == 401:
            raise ConnectorInvalidCredential("github graphql credential rejected")
        document = json.loads(response.body.decode("utf-8") or "{}")
        if document.get("errors"):
            if _graphql_auth_error(document["errors"]):
                raise ConnectorInvalidCredential("github discussion graphql permission denied")
            return FetchResult(
                None,
                ConnectorHealth(
                    self.connector_type,
                    ConnectorStatus.DEGRADED,
                    checked_at(),
                    "degraded",
                    {"external_id": external_id},
                ),
                deleted=False,
            )
        node = ((document.get("data") or {}).get("repository") or {}).get("discussion")
        if not node:
            return FetchResult(
                None,
                ConnectorHealth(
                    self.connector_type,
                    ConnectorStatus.DEGRADED,
                    checked_at(),
                    "deleted",
                    {"external_id": external_id},
                ),
                deleted=True,
            )
        return FetchResult(
            self._discussion_item(node),
            ConnectorHealth(
                self.connector_type, ConnectorStatus.HEALTHY, checked_at(), "current", {}
            ),
            deleted=False,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/vnd.github+json",
            "x-github-api-version": "2022-11-28",
            "user-agent": "glint-worker/1.0",
        }
        if self.config.token_ref and self.token_resolver:
            token = self._resolve_token()
            headers["authorization"] = f"Bearer {token}"
        return headers

    def _request(self, url: str) -> TransportResponse:
        response = self.transport.request("GET", url, headers=self._headers())
        if response.status_code == 401:
            raise ConnectorInvalidCredential("github credential rejected")
        if response.status_code in {403, 429}:
            raise ConnectorRateLimited(
                "github rate limit or access block", _retry_after(response.headers)
            )
        if response.status_code >= 500:
            raise ConnectorRateLimited(
                f"github temporary failure {response.status_code}", _retry_after(response.headers)
            )
        return response

    def _url(self, path: str) -> str:
        return self.config.api_base_url.rstrip("/") + path

    def _search_urls(self) -> list[tuple[str, str]]:
        owner = self.config.owner
        repo = self.config.repo
        per_page = self.config.per_page
        urls: list[tuple[str, str]] = []
        if self.config.include_repository:
            urls.append(("repository", self._url(f"/repos/{owner}/{repo}")))
        if self.config.include_issues:
            urls.append(
                ("issues", self._url(f"/repos/{owner}/{repo}/issues?state=all&per_page={per_page}"))
            )
        if self.config.include_releases:
            urls.append(
                ("releases", self._url(f"/repos/{owner}/{repo}/releases?per_page={per_page}"))
            )
        return urls

    def _search_composite_cursor(self, query: str, cursor_state: dict[str, str]) -> SearchPage:
        all_items: list[RawContentItem] = []
        next_state: dict[str, str] = {}
        degraded_reasons: list[str] = []
        failed_reasons: list[str] = []
        statuses: list[ConnectorStatus] = []
        for kind, value in sorted(cursor_state.items()):
            if kind == "discussions":
                try:
                    page = self._search_discussions(query, value)
                except ConnectorInvalidCredential:
                    degraded_reasons.append("discussions_auth_required")
                    continue
                except ConnectorPartialFailure as exc:
                    all_items.extend(exc.items)
                    degraded_reasons.append("discussions_partial_failure")
                    continue
                all_items.extend(page.items)
                statuses.append(page.health.status)
                if page.next_cursor:
                    next_state[kind] = page.next_cursor.removeprefix("graphql:discussions:")
                if page.health.status != ConnectorStatus.HEALTHY:
                    degraded_reasons.append("discussions_degraded")
                continue
            response = self._request(value)
            all_items.extend(self._parse_response_items(value, response))
            response_health = _health_from_response(self.connector_type, response.status_code)
            statuses.append(response_health.status)
            if response_health.status == ConnectorStatus.FAILED:
                failed_reasons.append(f"{kind}:{response.status_code}")
            next_url = _next_link(response.headers)
            if next_url:
                next_state[kind] = next_url
        status = _worst_status(statuses + ([ConnectorStatus.DEGRADED] if degraded_reasons else []))
        details = {}
        if degraded_reasons:
            details["degraded_reasons"] = degraded_reasons
        if failed_reasons:
            details["failed_reasons"] = failed_reasons
        return SearchPage(
            _filter_items(all_items, query),
            self._encode_cursor(next_state),
            ConnectorHealth(
                self.connector_type,
                status,
                checked_at(),
                "current"
                if status == ConnectorStatus.HEALTHY
                else ("failed" if status == ConnectorStatus.FAILED else "degraded"),
                details,
            ),
        )

    def _encode_cursor(self, cursors: dict[str, str]) -> str | None:
        clean = {key: value for key, value in cursors.items() if value}
        if not clean:
            return None
        state = json.dumps(clean, sort_keys=True, separators=(",", ":"))
        signature = hmac.new(self._cursor_secret(), state.encode("utf-8"), sha256).hexdigest()
        return CURSOR_PREFIX + json.dumps(
            {"state": clean, "sig": signature},
            sort_keys=True,
            separators=(",", ":"),
        )

    def _decode_cursor(self, cursor: str) -> dict[str, str] | None:
        if not cursor.startswith(CURSOR_PREFIX):
            return None
        try:
            value = json.loads(cursor.removeprefix(CURSOR_PREFIX))
        except json.JSONDecodeError as exc:
            raise ValueError("invalid GitHub composite cursor") from exc
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("state"), dict)
            or not isinstance(value.get("sig"), str)
            or any(
                not isinstance(key, str) or not isinstance(item, str)
                for key, item in value["state"].items()
            )
        ):
            raise ValueError("invalid GitHub composite cursor")
        state = json.dumps(value["state"], sort_keys=True, separators=(",", ":"))
        expected = hmac.new(self._cursor_secret(), state.encode("utf-8"), sha256).hexdigest()
        if not hmac.compare_digest(expected, value["sig"]):
            raise ValueError("invalid GitHub composite cursor signature")
        return value["state"]

    def _cursor_secret(self) -> bytes:
        if not self.config.cursor_secret:
            raise ConnectorPartialFailure("github cursor secret is required", [])
        secret = self.config.cursor_secret.encode("utf-8")
        if len(secret) < 32:
            raise ConnectorPartialFailure("github cursor secret must be at least 32 bytes", [])
        return secret

    def _validate_composite_cursor(self, cursor_state: dict[str, str]) -> None:
        allowed_rest = {"issues", "releases"}
        base = urlsplit(self.config.api_base_url)
        for kind, value in cursor_state.items():
            if kind == "discussions":
                parsed = urlsplit(value)
                if parsed.scheme or parsed.netloc:
                    raise ValueError("GitHub discussions cursor must be an opaque GraphQL cursor")
                continue
            if kind not in allowed_rest:
                raise ValueError("unsupported GitHub cursor resource")
            parsed = urlsplit(value)
            if parsed.scheme != "https" or parsed.username or parsed.password:
                raise ValueError("GitHub REST cursor must be an https URL without userinfo")
            if parsed.netloc.lower() != base.netloc.lower():
                raise ValueError("GitHub REST cursor host does not match api_base_url")
            expected_prefix = f"/repos/{self.config.owner}/{self.config.repo}/{kind}"
            if parsed.path != expected_prefix:
                raise ValueError("GitHub REST cursor path escaped the configured repository")

    def _fetch_url(self, external_id: str) -> str:
        prefix = f"github:{self.config.owner}/{self.config.repo}:"
        if not external_id.startswith(prefix):
            raise ValueError("external_id does not belong to this GitHub connector")
        resource = external_id.removeprefix(prefix)
        if resource == "repository":
            return self._url(f"/repos/{self.config.owner}/{self.config.repo}")
        kind, _, ident = resource.partition(":")
        if kind == "issue":
            return self._url(f"/repos/{self.config.owner}/{self.config.repo}/issues/{ident}")
        if kind == "release":
            return self._url(f"/repos/{self.config.owner}/{self.config.repo}/releases/{ident}")
        if kind == "discussion":
            return self.config.graphql_url
        raise ValueError("unsupported GitHub external_id kind")

    def _parse_response_items(self, url: str, response: TransportResponse) -> list[RawContentItem]:
        if response.status_code == 404:
            return []
        payload = json.loads(response.body.decode("utf-8") or "null")
        if "/issues" in url:
            records = payload if isinstance(payload, list) else [payload]
            return [
                self._issue_item(record) for record in records if not record.get("pull_request")
            ]
        if "/releases" in url:
            records = payload if isinstance(payload, list) else [payload]
            return [self._release_item(record) for record in records]
        if isinstance(payload, Mapping):
            return [self._repository_item(payload)]
        return []

    def _search_discussions(self, query: str, after: str | None) -> SearchPage:
        payload = {
            "query": DISCUSSIONS_QUERY,
            "variables": {
                "owner": self.config.owner,
                "name": self.config.repo,
                "first": min(self.config.per_page, 100),
                "after": after,
            },
        }
        response = self.transport.request(
            "POST",
            self.config.graphql_url,
            headers=self._graphql_headers(),
            body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        if response.status_code == 401:
            raise ConnectorInvalidCredential("github graphql credential rejected")
        if response.status_code in {403, 429}:
            raise ConnectorRateLimited(
                "github graphql rate limit or access block", _retry_after(response.headers)
            )
        document = json.loads(response.body.decode("utf-8") or "{}")
        errors = document.get("errors") or []
        if errors:
            if _graphql_auth_error(errors):
                raise ConnectorInvalidCredential("github discussions graphql permission denied")
            raise ConnectorPartialFailure("github discussions graphql partial failure", [])
        connection = ((document.get("data") or {}).get("repository") or {}).get("discussions") or {}
        nodes = connection.get("nodes") or []
        page_info = connection.get("pageInfo") or {}
        next_cursor = (
            f"graphql:discussions:{page_info.get('endCursor')}"
            if page_info.get("hasNextPage") and page_info.get("endCursor")
            else None
        )
        return SearchPage(
            _filter_items([self._discussion_item(node) for node in nodes], query),
            next_cursor,
            ConnectorHealth(
                self.connector_type,
                ConnectorStatus.HEALTHY,
                checked_at(),
                "current",
                {"graphql": "discussions"},
            ),
        )

    def _graphql_headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/vnd.github+json",
            "content-type": "application/json",
            "user-agent": "glint-worker/1.0",
        }
        if self.config.token_ref and self.token_resolver:
            token = self._resolve_token()
            headers["authorization"] = f"Bearer {token}"
        return headers

    def _resolve_token(self) -> str:
        if not self.config.token_ref or not self.token_resolver:
            raise ConnectorInvalidCredential("github credential reference is not configured")
        try:
            return self.token_resolver(self.config.token_ref)
        except ConnectorInvalidCredential:
            raise
        except Exception as exc:
            raise ConnectorInvalidCredential(
                "github credential reference could not be resolved"
            ) from exc

    def _repository_item(self, record: Mapping[str, Any]) -> RawContentItem:
        full_name = str(record.get("full_name") or f"{self.config.owner}/{self.config.repo}")
        body = collapse_text(record.get("description")) or "Repository metadata"
        return _item(
            connector_type=self.connector_type,
            source_connection_id=self.config.source_connection_id,
            external_id=f"github:{full_name}:repository",
            title=full_name,
            body=body,
            canonical_url=record.get("html_url"),
            author=self.config.owner,
            published_at=record.get("updated_at")
            or record.get("pushed_at")
            or record.get("created_at"),
            kind="repository",
            raw=record,
        )

    def _issue_item(self, record: Mapping[str, Any]) -> RawContentItem:
        number = record.get("number")
        body = "\n".join(
            filter(None, [collapse_text(record.get("title")), collapse_text(record.get("body"))])
        )
        return _item(
            connector_type=self.connector_type,
            source_connection_id=self.config.source_connection_id,
            external_id=f"github:{self.config.owner}/{self.config.repo}:issue:{number}",
            title=collapse_text(record.get("title")) or f"Issue {number}",
            body=body,
            canonical_url=record.get("html_url"),
            author=(record.get("user") or {}).get("login"),
            published_at=record.get("updated_at") or record.get("created_at"),
            kind="issue",
            raw=record,
        )

    def _release_item(self, record: Mapping[str, Any]) -> RawContentItem:
        release_id = record.get("id") or record.get("tag_name")
        body = "\n".join(
            filter(None, [collapse_text(record.get("name")), collapse_text(record.get("body"))])
        )
        return _item(
            connector_type=self.connector_type,
            source_connection_id=self.config.source_connection_id,
            external_id=f"github:{self.config.owner}/{self.config.repo}:release:{release_id}",
            title=collapse_text(record.get("name") or record.get("tag_name"))
            or f"Release {release_id}",
            body=body,
            canonical_url=record.get("html_url"),
            author=(record.get("author") or {}).get("login"),
            published_at=record.get("published_at") or record.get("created_at"),
            kind="release",
            raw=record,
        )

    def _discussion_item(self, record: Mapping[str, Any]) -> RawContentItem:
        number = record.get("number") or record.get("id")
        body = "\n".join(
            filter(
                None,
                [
                    collapse_text(record.get("title")),
                    collapse_text(record.get("bodyText") or record.get("body")),
                ],
            )
        )
        author_record = record.get("author") or record.get("user") or {}
        return _item(
            connector_type=self.connector_type,
            source_connection_id=self.config.source_connection_id,
            external_id=f"github:{self.config.owner}/{self.config.repo}:discussion:{number}",
            title=collapse_text(record.get("title")) or f"Discussion {number}",
            body=body,
            canonical_url=record.get("html_url") or record.get("url"),
            author=author_record.get("login"),
            published_at=record.get("updatedAt")
            or record.get("publishedAt")
            or record.get("updated_at")
            or record.get("created_at"),
            kind="discussion",
            raw=record,
        )


def _item(
    *,
    connector_type: str,
    source_connection_id: str,
    external_id: str,
    title: str,
    body: str,
    canonical_url: str | None,
    author: str | None,
    published_at: str | None,
    kind: str,
    raw: Mapping[str, Any],
) -> RawContentItem:
    canonical = canonicalize_url(canonical_url)
    normalized = {
        "title": title,
        "body": body,
        "canonical_url": canonical,
        "external_id": external_id,
    }
    return RawContentItem(
        connector_type=connector_type,
        source_connection_id=source_connection_id,
        external_id=external_id,
        title=title,
        body=body,
        canonical_url=canonical,
        author=author,
        published_at=parse_datetime(published_at),
        captured_at=checked_at(),
        content_version_digest=canonical_json_digest(normalized),
        raw_digest=canonical_json_digest(raw),
        metadata={"kind": kind},
    )


def _filter_items(items: list[RawContentItem], query: str) -> list[RawContentItem]:
    include_terms, exclude_terms = _query_filter_terms(query)
    if not include_terms and not exclude_terms:
        return items
    filtered: list[RawContentItem] = []
    for item in items:
        haystack = f"{item.title} {item.body}".lower()
        if exclude_terms and any(term in haystack for term in exclude_terms):
            continue
        if not include_terms or any(term in haystack for term in include_terms):
            filtered.append(item)
    return filtered


def _query_filter_terms(query: str) -> tuple[list[str], list[str]]:
    include_terms: list[str] = []
    exclude_terms: list[str] = []
    for token in re.findall(r'-?"[^"]+"|-?[a-zA-Z0-9_./:-]+', query):
        term = token.strip().strip('"').lower()
        if not term:
            continue
        excluded = term.startswith("-")
        if excluded:
            term = term[1:].strip('"')
        if ":" in term:
            continue
        if excluded:
            exclude_terms.append(term)
        else:
            include_terms.append(term)
    return include_terms, exclude_terms


def _next_link(headers: Mapping[str, str]) -> str | None:
    link = headers.get("link") or headers.get("Link")
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' in part:
            match = re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


CURSOR_PREFIX = "github:v1:"


def _retry_after(headers: Mapping[str, str]) -> int | None:
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _health_from_response(connector_type: str, status_code: int) -> ConnectorHealth:
    if status_code < 400:
        return ConnectorHealth(
            connector_type,
            ConnectorStatus.HEALTHY,
            checked_at(),
            "current",
            {"status_code": status_code},
        )
    return ConnectorHealth(
        connector_type, ConnectorStatus.FAILED, checked_at(), "failed", {"status_code": status_code}
    )


def _worst_status(statuses: list[ConnectorStatus]) -> ConnectorStatus:
    if ConnectorStatus.FAILED in statuses:
        return ConnectorStatus.FAILED
    if ConnectorStatus.RATE_LIMITED in statuses:
        return ConnectorStatus.RATE_LIMITED
    if ConnectorStatus.AUTH_REQUIRED in statuses:
        return ConnectorStatus.AUTH_REQUIRED
    if ConnectorStatus.DEGRADED in statuses:
        return ConnectorStatus.DEGRADED
    return ConnectorStatus.HEALTHY


def _graphql_auth_error(errors: list[Mapping[str, Any]]) -> bool:
    joined = " ".join(
        str(error.get("type") or error.get("message") or "") for error in errors
    ).lower()
    return any(
        token in joined
        for token in (
            "forbidden",
            "unauthorized",
            "requires authentication",
            "resource not accessible",
        )
    )


DISCUSSIONS_QUERY = """
query GlintRepositoryDiscussions($owner: String!, $name: String!, $first: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: $first, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { endCursor hasNextPage }
      nodes {
        id
        number
        title
        bodyText
        url
        updatedAt
        publishedAt
        author { login }
      }
    }
  }
}
"""


DISCUSSION_QUERY = """
query GlintRepositoryDiscussion($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      id
      number
      title
      bodyText
      url
      updatedAt
      publishedAt
      author { login }
    }
  }
}
"""
