from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts.enums import ClaimType
from packages.contracts.openapi import json_schema_bundle, openapi_components
from packages.contracts.registry import CONTRACT_MODEL_BY_NAME
from packages.contracts.schemas import (
    SignalEvidenceResponse,
    SourceConnectionCreateRequest,
    SourceConnectionResponse,
)

REQUIRED_SHARED_COMPONENTS = {
    "AcceptedCommand",
    "AuditLogFilter",
    "AuditLogResponse",
    "ClaimBatchReviewRequest",
    "ContentSummary",
    "CursorPage",
    "CursorPagination",
    "DecisionBriefRevisionRequest",
    "ErrorBody",
    "ErrorEnvelope",
    "ImmutableResource",
    "InvestigationTransitionRequest",
    "MutableResource",
    "ResearchBudget",
    "RunEvent",
    "SignalAssessmentRequest",
    "SignalTransitionRequest",
    "SourceConnectionUpdateRequest",
    "StreamResetEvent",
    "UploadConsentPreviewRequest",
    "UploadConsentPreviewResponse",
    "UploadConsentScopeBinding",
}


WORKSPACE_ID = UUID("11111111-1111-5111-8111-111111111111")
SOURCE_ID = UUID("22222222-2222-5222-8222-222222222222")
SIGNAL_ID = UUID("33333333-3333-5333-8333-333333333333")
CONTENT_VERSION_ID = UUID("44444444-4444-5444-8444-444444444444")
INDEPENDENCE_GROUP_ID = UUID("55555555-5555-5555-8555-555555555555")


def test_required_shared_models_are_in_schema_and_openapi_aggregation() -> None:
    assert REQUIRED_SHARED_COMPONENTS.issubset(CONTRACT_MODEL_BY_NAME)
    selected = [CONTRACT_MODEL_BY_NAME[name] for name in sorted(REQUIRED_SHARED_COMPONENTS)]
    assert REQUIRED_SHARED_COMPONENTS.issubset(json_schema_bundle(selected)["schemas"])
    components = openapi_components(selected)["components"]["schemas"]
    assert REQUIRED_SHARED_COMPONENTS.issubset(components)


def test_signal_evidence_contract_preserves_origin_independence_group() -> None:
    evidence = SignalEvidenceResponse.model_validate(
        {
            "signal_id": SIGNAL_ID,
            "content_version_id": CONTENT_VERSION_ID,
            "role": "trigger",
            "independence_group_id": INDEPENDENCE_GROUP_ID,
            "contribution": 1.0,
            "data_authenticity": "collected",
        }
    )
    assert evidence.independence_group_id == INDEPENDENCE_GROUP_ID
    schema = SignalEvidenceResponse.model_json_schema()
    assert schema["properties"]["independence_group_id"]["anyOf"][0]["format"] == "uuid"


def test_claim_type_contract_accepts_worker_observation_proposals() -> None:
    assert ClaimType("observation") is ClaimType.OBSERVATION


def test_github_source_config_is_strict_and_accepts_only_a_credential_reference() -> None:
    request = SourceConnectionCreateRequest.model_validate(
        {
            "name": "GitHub product feedback",
            "source_kind": "cloud",
            "runtime": "cloud",
            "connector_type": "github",
            "connector_version": "github-v1",
            "data_scope": "workspace_confidential",
            "credential_ref": "vault://github/product-feedback",
            "cadence": "daily",
            "timezone": "UTC",
            "source_config": {
                "connector_type": "github",
                "repositories": [
                    {
                        "owner": "openai",
                        "repository": "example",
                        "include_issues": True,
                        "include_discussions": True,
                        "include_releases": False,
                    }
                ],
            },
        }
    )
    assert request.credential_ref == "vault://github/product-feedback"

    payload = request.model_dump(mode="json")
    payload["api_key"] = "must-not-pass"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceConnectionCreateRequest.model_validate(payload)


def test_rss_config_rejects_multiple_feeds_and_unknown_fields() -> None:
    payload: dict[str, object] = {
        "name": "Release feeds",
        "source_kind": "cloud",
        "runtime": "cloud",
        "connector_type": "rss",
        "connector_version": "rss-v1",
        "data_scope": "public",
        "cadence": "daily",
        "timezone": "UTC",
        "source_config": {
            "connector_type": "rss",
            "feeds": [
                {"name": "Releases", "feed_url": "https://example.com/releases.xml"},
                {"name": "Duplicate", "feed_url": "https://example.com/releases.xml"},
            ],
        },
    }
    with pytest.raises(ValidationError, match="at most 1 item"):
        SourceConnectionCreateRequest.model_validate(payload)

    payload["source_config"] = {
        "connector_type": "rss",
        "feeds": [
            {
                "name": "Releases",
                "feed_url": "https://example.com/releases.xml",
                "request_headers": {"Authorization": "must-not-pass"},
            }
        ],
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceConnectionCreateRequest.model_validate(payload)


@pytest.mark.parametrize(
    "feed_url",
    ["http://example.com/feed.xml", "https://user:password@example.com/feed.xml"],
)
def test_rss_config_requires_https_without_userinfo(feed_url: str) -> None:
    with pytest.raises(ValidationError, match="HTTPS without userinfo"):
        SourceConnectionCreateRequest.model_validate(
            {
                "name": "Unsafe feed",
                "source_kind": "cloud",
                "runtime": "cloud",
                "connector_type": "rss",
                "connector_version": "rss-v1",
                "data_scope": "public",
                "cadence": "daily",
                "timezone": "UTC",
                "source_config": {
                    "connector_type": "rss",
                    "feeds": [{"name": "Unsafe", "feed_url": feed_url}],
                },
            }
        )


@pytest.mark.parametrize("slug", ["owner/repo", "bad value", "x" * 101, ""])
def test_github_config_rejects_slugs_the_worker_cannot_execute(slug: str) -> None:
    with pytest.raises(ValidationError):
        SourceConnectionCreateRequest.model_validate(
            {
                "name": "Invalid GitHub source",
                "source_kind": "cloud",
                "runtime": "cloud",
                "connector_type": "github",
                "connector_version": "github-v1",
                "data_scope": "public",
                "cadence": "daily",
                "timezone": "UTC",
                "source_config": {
                    "connector_type": "github",
                    "repositories": [{"owner": slug, "repository": "repo"}],
                },
            }
        )


def test_imported_source_forbids_credential_reference() -> None:
    with pytest.raises(ValidationError, match="cannot have cloud config or credential_ref"):
        SourceConnectionCreateRequest.model_validate(
            {
                "name": "Imported interviews",
                "source_kind": "imported_dataset",
                "runtime": "static_import",
                "connector_type": "csv",
                "connector_version": "csv-v1",
                "data_scope": "workspace_confidential",
                "credential_ref": "vault://imports/not-allowed",
            }
        )


def test_source_response_has_health_and_freshness_but_never_credential_reference() -> None:
    now = datetime(2026, 7, 15, 5, tzinfo=UTC)
    response = SourceConnectionResponse.model_validate(
        {
            "id": SOURCE_ID,
            "workspace_id": WORKSPACE_ID,
            "name": "GitHub product feedback",
            "source_kind": "cloud",
            "runtime": "cloud",
            "connector_type": "github",
            "connector_version": "github-v1",
            "source_config": {
                "connector_type": "github",
                "repositories": [
                    {"owner": "openai", "repository": "example"},
                ],
            },
            "cadence": "daily",
            "timezone": "UTC",
            "last_run_at": now,
            "last_success_at": now,
            "status": "healthy",
            "health": {"state": "healthy", "checked_at": now},
            "freshness": {"state": "current", "last_success_at": now},
            "capabilities": ["search", "fetch", "health"],
            "data_scope": "workspace_confidential",
            "current_import_manifest": None,
            "row_version": 1,
            "created_at": now,
            "updated_at": now,
            "data_authenticity": "collected",
        }
    )
    payload = response.model_dump(mode="json")
    assert payload["health"]["state"] == "healthy"
    assert payload["freshness"]["state"] == "current"
    assert "credential_ref" not in payload
    assert "credential_ref" not in SourceConnectionResponse.model_json_schema()["properties"]


@pytest.mark.parametrize("connector_type", ["github", "rss"])
def test_thin_cloud_source_contract_rejects_multiple_targets(connector_type: str) -> None:
    targets: dict[str, object]
    if connector_type == "github":
        targets = {
            "repositories": [
                {"owner": "openai", "repository": "one"},
                {"owner": "openai", "repository": "two"},
            ]
        }
    else:
        targets = {
            "feeds": [
                {"name": "One", "feed_url": "https://example.com/one.xml"},
                {"name": "Two", "feed_url": "https://example.com/two.xml"},
            ]
        }
    with pytest.raises(ValidationError, match="at most 1 item"):
        SourceConnectionCreateRequest.model_validate(
            {
                "name": "Too broad",
                "source_kind": "cloud",
                "runtime": "cloud",
                "connector_type": connector_type,
                "connector_version": "connector-v1",
                "data_scope": "public",
                "cadence": "daily",
                "timezone": "UTC",
                "source_config": {"connector_type": connector_type, **targets},
            }
        )
