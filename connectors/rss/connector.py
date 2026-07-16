"""RSS/Atom connector with canonical URLs and content version digests."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from ipaddress import ip_address
from socket import getaddrinfo
from urllib.parse import urljoin, urlsplit

from connectors.shared.contracts import (
    ConnectorCapabilities,
    ConnectorHealth,
    ConnectorPartialFailure,
    ConnectorRateLimited,
    ConnectorStatus,
    ConnectorTransport,
    FetchResult,
    RawContentItem,
    SearchPage,
    checked_at,
)
from connectors.shared.utils import (
    canonical_json_digest,
    canonicalize_url,
    collapse_text,
    parse_datetime,
)

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
DC = "{http://purl.org/dc/elements/1.1/}"


@dataclass(frozen=True, slots=True)
class RssConnectorConfig:
    source_connection_id: str
    feed_url: str
    feed_title: str | None = None
    timeout_seconds: float = 10.0
    max_redirects: int = 3
    resolver: Callable[[str], list[str]] | None = None
    max_response_bytes: int = 2_000_000


class RssConnector:
    connector_type = "rss"

    def __init__(self, config: RssConnectorConfig, transport: ConnectorTransport) -> None:
        self.config = config
        self.transport = transport

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            connector_type=self.connector_type,
            supports_search=True,
            supports_fetch=True,
            supports_pagination=False,
            supports_incremental=True,
            rate_limit_policy="feed-fetch-v1",
            content_kinds=("rss_article", "atom_entry"),
        )

    def health(self) -> ConnectorHealth:
        response = self._fetch_feed()
        if response.status_code in {403, 429}:
            raise ConnectorRateLimited("rss source rate limited")
        if response.status_code >= 400:
            return ConnectorHealth(
                self.connector_type,
                ConnectorStatus.FAILED,
                checked_at(),
                "failed",
                {"status_code": response.status_code},
            )
        try:
            self._parse_feed(response.body)
        except ET.ParseError:
            return ConnectorHealth(
                self.connector_type,
                ConnectorStatus.DEGRADED,
                checked_at(),
                "degraded",
                {"reason": "invalid_xml"},
            )
        return ConnectorHealth(
            self.connector_type,
            ConnectorStatus.HEALTHY,
            checked_at(),
            "current",
            {"feed_url": self.config.feed_url},
        )

    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del cursor
        response = self._fetch_feed()
        if response.status_code in {403, 429}:
            raise ConnectorRateLimited("rss source rate limited")
        if response.status_code >= 400:
            health = ConnectorHealth(
                self.connector_type,
                ConnectorStatus.FAILED,
                checked_at(),
                "failed",
                {"status_code": response.status_code},
            )
            return SearchPage([], None, health)
        try:
            items = self._parse_feed(response.body)
        except ET.ParseError as exc:
            raise ConnectorPartialFailure("invalid RSS/Atom XML", []) from exc
        filtered = _filter_items(items, query)
        return SearchPage(
            filtered,
            None,
            ConnectorHealth(
                self.connector_type,
                ConnectorStatus.HEALTHY,
                checked_at(),
                "current",
                {"item_count": len(items)},
            ),
        )

    def fetch(self, external_id: str) -> FetchResult:
        page = self.search("")
        for item in page.items:
            if item.external_id == external_id:
                return FetchResult(item, page.health, deleted=False)
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

    def _parse_feed(self, body: bytes) -> list[RawContentItem]:
        root = ET.fromstring(body)
        if root.tag.endswith("feed"):
            return self._parse_atom(root)
        channel = root.find("channel")
        if channel is None:
            return []
        return [self._rss_item(item) for item in channel.findall("item")]

    def _fetch_feed(self):
        url = self.config.feed_url
        for _ in range(self.config.max_redirects + 1):
            expected_addresses = _validate_fetch_url(url, self.config.resolver)
            response = self.transport.request(
                "GET",
                url,
                headers={"user-agent": "glint-worker/1.0"},
                timeout_seconds=self.config.timeout_seconds,
                expected_addresses=tuple(expected_addresses),
            )
            if len(response.body) > self.config.max_response_bytes:
                raise ConnectorPartialFailure("rss response exceeded byte cap", [])
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location") or response.headers.get("Location")
                if not location:
                    return response
                url = urljoin(url, location)
                continue
            return response
        raise ConnectorPartialFailure("rss redirect limit exceeded", [])

    def _parse_atom(self, root: ET.Element) -> list[RawContentItem]:
        return [self._atom_entry(entry) for entry in root.findall(f"{ATOM}entry")]

    def _rss_item(self, item: ET.Element) -> RawContentItem:
        title = collapse_text(_text(item, "title")) or "Untitled RSS item"
        link = _text(item, "link")
        guid = _text(item, "guid") or link or title
        body = collapse_text(_text(item, f"{CONTENT}encoded") or _text(item, "description"))
        author = collapse_text(
            _text(item, "author")
            or _text(item, f"{DC}creator")
            or _text_by_local_name(item, "creator")
        )
        published_at = parse_datetime(_text(item, "pubDate"))
        return self._item(
            str(guid),
            title,
            body,
            link,
            author,
            published_at,
            "rss_article",
            ET.tostring(item, encoding="unicode"),
        )

    def _atom_entry(self, entry: ET.Element) -> RawContentItem:
        title = collapse_text(_text(entry, f"{ATOM}title")) or "Untitled Atom entry"
        link = _atom_link(entry)
        entry_id = _text(entry, f"{ATOM}id") or link or title
        body = collapse_text(_text(entry, f"{ATOM}content") or _text(entry, f"{ATOM}summary"))
        author_node = entry.find(f"{ATOM}author")
        author = collapse_text(
            _text(author_node, f"{ATOM}name") if author_node is not None else None
        )
        published_at = parse_datetime(
            _text(entry, f"{ATOM}updated") or _text(entry, f"{ATOM}published")
        )
        return self._item(
            str(entry_id),
            title,
            body,
            link,
            author,
            published_at,
            "atom_entry",
            ET.tostring(entry, encoding="unicode"),
        )

    def _item(
        self,
        external_key: str,
        title: str,
        body: str,
        link: str | None,
        author: str | None,
        published_at: datetime | None,
        kind: str,
        raw_xml: str,
    ) -> RawContentItem:
        canonical = canonicalize_url(link or external_key)
        external_id = f"rss:{self.config.feed_url}:{canonical or external_key}"
        normalized = {
            "title": title,
            "body": body,
            "canonical_url": canonical,
            "external_id": external_id,
        }
        return RawContentItem(
            connector_type=self.connector_type,
            source_connection_id=self.config.source_connection_id,
            external_id=external_id,
            title=title,
            body=body,
            canonical_url=canonical,
            author=author or self.config.feed_title,
            published_at=published_at,
            captured_at=checked_at(),
            content_version_digest=canonical_json_digest(normalized),
            raw_digest=canonical_json_digest(raw_xml),
            metadata={"kind": kind, "feed_url": self.config.feed_url},
        )


def _text(node: ET.Element | None, name: str) -> str | None:
    if node is None:
        return None
    child = node.find(name)
    if child is None or child.text is None:
        return None
    return child.text


def _text_by_local_name(node: ET.Element | None, local_name: str) -> str | None:
    if node is None:
        return None
    for child in list(node):
        if child.tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1] == local_name and child.text:
            return child.text
    return None


def _atom_link(entry: ET.Element) -> str | None:
    for link in entry.findall(f"{ATOM}link"):
        rel = link.attrib.get("rel", "alternate")
        if rel == "alternate" and link.attrib.get("href"):
            return link.attrib["href"]
    return None


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
    for raw in query.split():
        token = raw.strip().strip('"').lower()
        if not token:
            continue
        excluded = token.startswith("-")
        if excluded:
            token = token[1:].strip('"')
        if ":" in token:
            continue
        if excluded:
            exclude_terms.append(token)
        else:
            include_terms.append(token)
    return include_terms, exclude_terms


def _validate_fetch_url(url: str, resolver: Callable[[str], list[str]] | None) -> list[str]:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ConnectorPartialFailure("rss fetch requires https", [])
    if parts.username or parts.password:
        raise ConnectorPartialFailure("rss fetch forbids URL userinfo", [])
    host = parts.hostname
    if not host:
        raise ConnectorPartialFailure("rss fetch host is missing", [])
    addresses = _resolve_host(host, resolver)
    for address in addresses:
        parsed = ip_address(address)
        if (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_multicast
            or parsed.is_reserved
        ):
            raise ConnectorPartialFailure("rss fetch target blocked by egress policy", [])
    return addresses


def _resolve_host(host: str, resolver: Callable[[str], list[str]] | None) -> list[str]:
    try:
        return [str(ip_address(host))]
    except ValueError:
        pass
    if resolver is not None:
        return resolver(host)
    try:
        return sorted({str(info[4][0]) for info in getaddrinfo(host, 443, proto=0)})
    except OSError as exc:
        raise ConnectorPartialFailure("rss host resolution failed", []) from exc
