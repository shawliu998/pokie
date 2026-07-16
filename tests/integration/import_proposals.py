from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from packages.contracts.schemas import ImportNormalizationProposal
from services.api.app.db.models import ImportFinalizationJobRecord, ImportSession

GLINT_NAMESPACE = UUID("019f6531-d58f-7860-a154-30c7a89f433d")


class NormalizedFixtureItem(TypedDict, total=False):
    external_id: str
    title: str
    body: str
    canonical_url: str | None
    author: str | None
    published_at: str | None


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _id(kind: str, *parts: object) -> str:
    return str(uuid5(GLINT_NAMESPACE, _canonical_json([kind, *parts])))


def normalization_proposal(
    db: Session,
    *,
    command_id: str,
    items: list[NormalizedFixtureItem],
    finalized_at: datetime | None = None,
) -> ImportNormalizationProposal:
    job = db.get(ImportFinalizationJobRecord, command_id)
    assert job is not None
    session = db.get(ImportSession, job.import_session_id)
    assert session is not None
    captured_at = finalized_at or datetime.now(UTC)
    raw_items: list[dict[str, object]] = []
    content_items: list[dict[str, object]] = []
    content_versions: list[dict[str, object]] = []
    for row_number, item in enumerate(items, start=1):
        external_id = item["external_id"]
        canonical_url = item.get("canonical_url")
        content_digest = _digest(
            _canonical_json(
                {
                    "title": item["title"],
                    "body": item["body"],
                    "canonical_url": canonical_url,
                    "source_item_id": external_id,
                }
            )
        )
        raw_id = _id("raw-import", session.id, external_id, content_digest)
        content_item_id = _id(
            "content-item", session.source_connection_id, external_id, canonical_url
        )
        content_version_id = _id("content-version", content_item_id, content_digest)
        published_at = item.get("published_at")
        raw_items.append(
            {
                "id": raw_id,
                "workspace_id": session.workspace_id,
                "source_connection_id": session.source_connection_id,
                "source_item_id": external_id,
                "title": item["title"],
                "body": item["body"],
                "canonical_url": canonical_url,
                "author": item.get("author"),
                "published_at": published_at,
                "captured_at": published_at or captured_at,
                "content_digest": content_digest,
                "data_authenticity": session.data_authenticity,
                "metadata": {"row_number": row_number, "schema_version": session.schema_version},
            }
        )
        content_items.append(
            {
                "id": content_item_id,
                "workspace_id": session.workspace_id,
                "source_connection_id": session.source_connection_id,
                "source_item_id": external_id,
                "canonical_url": canonical_url,
                "identity_key": canonical_url or f"{session.source_connection_id}:{external_id}",
                "title": item["title"],
                "current_version_id": content_version_id,
                "duplicate_cluster_id": None,
                "independence_group_id": None,
                "data_authenticity": session.data_authenticity,
            }
        )
        content_versions.append(
            {
                "id": content_version_id,
                "workspace_id": session.workspace_id,
                "content_item_id": content_item_id,
                "version_number": 1,
                "content_digest": content_digest,
                "normalized_title": item["title"],
                "normalized_body": item["body"],
                "captured_at": published_at or captured_at,
                "parser_version": session.parser_version,
                "canonical_url": canonical_url,
                "author": item.get("author"),
                "data_authenticity": session.data_authenticity,
                "metadata": {"source_item_id": external_id, "row_number": row_number},
            }
        )
    normalized_payload_digest = _digest(
        "\n".join(str(version["content_digest"]) for version in content_versions)
    )
    return ImportNormalizationProposal.model_validate(
        {
            "manifest": {
                "id": _id("import-manifest", session.id, normalized_payload_digest),
                "workspace_id": session.workspace_id,
                "import_session_id": session.id,
                "source_connection_id": session.source_connection_id,
                "file_digest": session.file_digest,
                "uploaded_object_key": session.uploaded_object_key,
                "uploaded_object_digest": session.uploaded_object_digest,
                "parser_version": session.parser_version,
                "schema_version": session.schema_version,
                "selected_scope_digest": session.selected_scope_digest,
                "consent_record_id": job.consent_record_id,
                "normalized_payload_digest": normalized_payload_digest,
                "content_count": len(content_versions),
                "finalized_at": captured_at,
                "data_authenticity": session.data_authenticity,
            },
            "raw_items": raw_items,
            "content_items": content_items,
            "content_versions": content_versions,
        }
    )
