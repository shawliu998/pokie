from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.contracts.schemas import (
    UploadConsentPreviewResponse,
    UploadConsentRequest,
)
from packages.domain.canonical import canonical_digest


def _scope() -> dict[str, object]:
    workspace_id = uuid4()
    import_session_id = uuid4()
    return {
        "destination_workspace_id": workspace_id,
        "import_session_id": import_session_id,
        "import_session_row_version": 1,
        "source_connection_id": uuid4(),
        "source_row_version": 3,
        "current_import_manifest_id": None,
        "local_manifest_digest": "sha256:" + "1" * 64,
        "file_digest": "sha256:" + "2" * 64,
        "expected_upload_digest": "sha256:" + "3" * 64,
        "selected_scope_digest": "sha256:" + "4" * 64,
        "upload_object_scope": {
            "object_key": (f"workspaces/{workspace_id}/imports/{import_session_id}/payload.csv"),
            "max_bytes": 4096,
            "media_type": "text/csv",
        },
        "policy_version": "import-transfer-v1",
    }


def test_preview_and_consent_share_the_exact_typed_scope() -> None:
    scope = _scope()
    digest = canonical_digest(scope)
    preview = UploadConsentPreviewResponse.model_validate(
        {
            "preview_scope": scope,
            "scope_digest": digest,
            "data_authenticity": "imported",
        }
    )
    consent = UploadConsentRequest.model_validate(
        {
            "preview_scope": preview.preview_scope.model_dump(mode="json"),
            "scope_digest": preview.scope_digest,
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
            "confirmation": True,
        }
    )
    assert consent.preview_scope.import_session_row_version == 1
    assert consent.preview_scope.source_row_version == 3
    assert consent.scope_digest == digest


def test_consent_cannot_omit_the_preview_scope_or_digest() -> None:
    with pytest.raises(ValidationError):
        UploadConsentRequest.model_validate(
            {
                "expires_at": datetime.now(UTC) + timedelta(minutes=5),
                "confirmation": True,
            }
        )
