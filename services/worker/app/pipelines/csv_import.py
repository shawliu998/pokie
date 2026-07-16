"""CSV import normalization for the Phase 1 imported dataset path."""

from __future__ import annotations

import csv
from collections.abc import Callable
from io import StringIO
from typing import Any

from connectors.shared.utils import canonicalize_url, collapse_text, parse_datetime
from services.worker.app.contracts import ContentItem, ContentVersion, ImportSession, RawContentItem
from services.worker.app.pipelines.digests import (
    canonical_json_digest,
    deterministic_id,
    sha256_text,
)

FORMULA_PREFIXES = ("=", "+", "-", "@")
MAX_FIELD_BYTES = 1_000_000
MAX_ROWS = 50_000
MAX_CELL_BYTES = 20_000
MAX_COLUMNS = 200


def _safe_cell(value: str | None) -> str:
    text = collapse_text(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def _body_from_row(row: dict[str, str], selected_columns: list[str]) -> str:
    values: list[str] = []
    for column in selected_columns:
        value = _safe_cell(row.get(column))
        if value:
            values.append(f"{column}: {value}")
    if values:
        return "\n".join(values)
    return "\n".join(
        f"{key}: {_safe_cell(value)}" for key, value in row.items() if _safe_cell(value)
    )


def normalize_csv_import(
    session: ImportSession, body: bytes, heartbeat: Callable[[], None] | None = None
) -> tuple[list[RawContentItem], list[ContentItem], list[ContentVersion], str]:
    """Parse a CSV upload into production-shaped raw/content/version objects."""

    csv.field_size_limit(MAX_FIELD_BYTES)
    decoded = body.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(decoded))
    headers = list(reader.fieldnames or [])
    if not headers:
        raise ValueError("CSV has no header row")
    _validate_headers(headers)

    selected_columns = list(session.selected_scope_json.get("columns") or headers)
    missing = [column for column in selected_columns if column not in headers]
    if missing:
        raise ValueError(f"selected columns missing from CSV: {', '.join(missing)}")

    raw_items: list[RawContentItem] = []
    content_items: list[ContentItem] = []
    content_versions: list[ContentVersion] = []
    for index, row in enumerate(reader, start=1):
        if heartbeat is not None and index % 1000 == 1:
            heartbeat()
        if index > MAX_ROWS:
            raise ValueError("CSV row count exceeds server limit")
        if None in row:
            raise ValueError("CSV row has more cells than headers")
        if set(row) != set(headers):
            raise ValueError("CSV row does not match header shape")
        _validate_row_cells(row)
        row_values: dict[str, Any] = {key: _safe_cell(value) for key, value in row.items()}
        source_item_id = (
            row_values.get("id") or row_values.get("source_item_id") or f"{session.id}:row:{index}"
        )
        title = (
            row_values.get("title")
            or row_values.get("problem")
            or row_values.get("quote")
            or f"Imported CSV row {index}"
        )
        normalized_title = _safe_cell(title)
        normalized_body = _body_from_row(row, selected_columns)
        canonical_url = canonicalize_url(row_values.get("url") or row_values.get("canonical_url"))
        author = row_values.get("author") or row_values.get("segment")
        published_at = parse_datetime(
            row_values.get("published_at") or row_values.get("created_at")
        )
        content_digest = canonical_json_digest(
            {
                "title": normalized_title,
                "body": normalized_body,
                "canonical_url": canonical_url,
                "source_item_id": source_item_id,
            }
        )
        raw_id = deterministic_id("raw-import", session.id, source_item_id, content_digest)
        content_item_id = deterministic_id(
            "content-item", session.source_connection_id, source_item_id, canonical_url
        )
        content_version_id = deterministic_id("content-version", content_item_id, content_digest)
        identity_key = canonical_url or f"{session.source_connection_id}:{source_item_id}"
        raw_item = RawContentItem(
            id=raw_id,
            workspace_id=session.workspace_id,
            source_connection_id=session.source_connection_id,
            source_item_id=str(source_item_id),
            title=normalized_title,
            body=normalized_body,
            canonical_url=canonical_url,
            author=author,
            published_at=published_at,
            captured_at=published_at or session_state_time(session),
            content_digest=content_digest,
            data_authenticity=session.data_authenticity,
            metadata={"row_number": index, "schema_version": session.schema_version},
        )
        version = ContentVersion(
            id=content_version_id,
            workspace_id=session.workspace_id,
            content_item_id=content_item_id,
            version_number=1,
            content_digest=content_digest,
            normalized_title=normalized_title,
            normalized_body=normalized_body,
            captured_at=raw_item.captured_at,
            parser_version=session.parser_version,
            canonical_url=canonical_url,
            author=author,
            data_authenticity=session.data_authenticity,
            metadata={"source_item_id": str(source_item_id), "row_number": index},
        )
        item = ContentItem(
            id=content_item_id,
            workspace_id=session.workspace_id,
            source_connection_id=session.source_connection_id,
            source_item_id=str(source_item_id),
            canonical_url=canonical_url,
            identity_key=identity_key,
            title=normalized_title,
            current_version_id=content_version_id,
            duplicate_cluster_id=None,
            independence_group_id=None,
            data_authenticity=session.data_authenticity,
        )
        raw_items.append(raw_item)
        content_items.append(item)
        content_versions.append(version)

    if not content_versions:
        raise ValueError("CSV has no data rows")

    normalized_payload_digest = sha256_text(
        "\n".join(version.content_digest for version in content_versions)
    )
    return raw_items, content_items, content_versions, normalized_payload_digest


def _validate_headers(headers: list[str]) -> None:
    if len(headers) > MAX_COLUMNS:
        raise ValueError("CSV column count exceeds server limit")
    normalized = [header.strip() for header in headers]
    if any(not header for header in normalized):
        raise ValueError("CSV headers must be non-empty")
    if len({header.casefold() for header in normalized}) != len(normalized):
        raise ValueError("CSV headers must be unique")


def _validate_row_cells(row: dict[str | None, str | None]) -> None:
    for key, value in row.items():
        if key is None:
            raise ValueError("CSV row has extra unnamed cells")
        if value is not None and len(value.encode("utf-8")) > MAX_CELL_BYTES:
            raise ValueError("CSV cell exceeds server limit")


def session_state_time(session: ImportSession):
    """Keep deterministic fixture timestamps when no row timestamp exists."""

    from services.worker.app.contracts import now_utc

    del session
    return now_utc()
