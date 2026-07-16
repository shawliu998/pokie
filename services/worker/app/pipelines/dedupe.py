"""Deterministic duplicate and independence grouping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from services.worker.app.contracts import ContentVersion
from services.worker.app.pipelines.digests import deterministic_id, sha256_text

TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class DedupeAssignment:
    content_version_id: str
    duplicate_cluster_id: str
    independence_group_id: str
    key: str
    duplicate_reason: str


@dataclass(frozen=True, slots=True)
class DedupeResult:
    assignments: dict[str, DedupeAssignment]
    duplicate_cluster_sizes: dict[str, int]
    independence_group_sizes: dict[str, int]


def _tokens(version: ContentVersion) -> set[str]:
    return set(TOKEN_RE.findall(f"{version.normalized_title} {version.normalized_body}".lower()))


def _title_key(version: ContentVersion) -> str:
    title = re.sub(r"\W+", " ", version.normalized_title.lower()).strip()
    return sha256_text(title)


def _body_key(version: ContentVersion) -> str:
    body = re.sub(r"\W+", " ", version.normalized_body.lower()).strip()
    return sha256_text(body)


def _canonical_host_path(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"


def _normalized_author(version: ContentVersion) -> str | None:
    author = version.author or version.metadata.get("author")
    if not isinstance(author, str):
        return None
    normalized = re.sub(r"\s+", " ", author.strip().casefold())
    return normalized or None


def _origin_key(version: ContentVersion) -> str:
    source_namespace = (
        version.metadata.get("source_connection_id")
        or version.metadata.get("source_id")
        or version.metadata.get("connector_type")
    )
    canonical = _canonical_host_path(version.canonical_url)
    host = canonical.split("/", 1)[0] if canonical else None
    author = _normalized_author(version)
    if source_namespace and author:
        return f"source:{source_namespace}:author:{author}"
    if host and author:
        return f"host:{host}:author:{author}"
    if source_namespace:
        feed = version.metadata.get("feed_url") or version.metadata.get("source_feed_url")
        if isinstance(feed, str):
            feed_key = _canonical_host_path(feed)
            if feed_key:
                return f"source:{source_namespace}:feed:{feed_key}"
        if host:
            return f"source:{source_namespace}:host:{host}"
        return f"source:{source_namespace}:item:{version.content_item_id}"
    canonical = _canonical_host_path(version.canonical_url)
    if canonical:
        return f"host:{canonical.split('/', 1)[0]}"
    return f"content-item:{version.content_item_id}"


def deduplicate_versions(
    versions: list[ContentVersion], near_threshold: float = 0.88
) -> DedupeResult:
    assignments: dict[str, DedupeAssignment] = {}
    cluster_keys: list[tuple[str, set[str], str]] = []

    for version in sorted(versions, key=lambda item: item.id):
        canonical = _canonical_host_path(version.canonical_url)
        tokens = _tokens(version)
        body_key = _body_key(version)
        key = canonical or body_key
        reason = "canonical_url" if canonical else "body_hash"

        for existing_key, existing_tokens, existing_reason in cluster_keys:
            if existing_key == body_key:
                key = existing_key
                reason = f"body_hash:{existing_reason}"
                break
            if not tokens or not existing_tokens:
                continue
            similarity = len(tokens & existing_tokens) / len(tokens | existing_tokens)
            if similarity >= near_threshold:
                key = existing_key
                reason = f"near_duplicate:{existing_reason}"
                break

        if key == body_key and not any(existing_key == key for existing_key, _, _ in cluster_keys):
            title_key = _title_key(version)
            for existing_key, _, _ in cluster_keys:
                if existing_key == title_key:
                    key = title_key
                    reason = "title_hash"
                    break
            else:
                key = title_key if len(tokens) < 6 else key

        if not any(existing_key == key for existing_key, _, _ in cluster_keys):
            cluster_keys.append((key, tokens, reason))

        duplicate_cluster_id = deterministic_id("duplicate-cluster", key)
        independence_group_id = deterministic_id("independence-group", _origin_key(version))
        assignments[version.id] = DedupeAssignment(
            content_version_id=version.id,
            duplicate_cluster_id=duplicate_cluster_id,
            independence_group_id=independence_group_id,
            key=key,
            duplicate_reason=reason,
        )

    cluster_sizes: dict[str, int] = {}
    independence_sizes: dict[str, int] = {}
    for assignment in assignments.values():
        cluster_sizes[assignment.duplicate_cluster_id] = (
            cluster_sizes.get(assignment.duplicate_cluster_id, 0) + 1
        )
        independence_sizes[assignment.independence_group_id] = (
            independence_sizes.get(assignment.independence_group_id, 0) + 1
        )
    return DedupeResult(assignments, cluster_sizes, independence_sizes)
