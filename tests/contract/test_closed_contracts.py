from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.contracts import enums
from packages.contracts.registry import ALL_CONTRACT_MODELS
from packages.contracts.schemas import (
    CursorPagination,
    ImportSessionCreateRequest,
    NavigationSummary,
    SignalAssessmentRequest,
    SourceConnectionCreateRequest,
    SourceConnectionUpdateRequest,
    WatchlistQueryRules,
)


def enum_values(enum_type: type[enums.StrEnum]) -> set[str]:
    return {member.value for member in enum_type}


@pytest.mark.parametrize(
    ("enum_type", "expected"),
    [
        (
            enums.ImportSessionState,
            {"draft", "consented", "uploaded", "validating", "finalized", "failed", "cancelled"},
        ),
        (
            enums.SignalStatus,
            {"new", "triaged", "investigating", "explained", "monitoring", "dismissed"},
        ),
        (enums.SignalTransition, {"investigate", "explain", "monitor", "dismiss", "undo"}),
        (
            enums.InvestigationStatus,
            {
                "draft",
                "active",
                "needs_input",
                "reviewing",
                "completed",
                "closed_insufficient",
                "cancelled",
            },
        ),
        (
            enums.ResearchRunState,
            {"queued", "running", "waiting_for_input", "completed", "failed", "cancelled"},
        ),
        (
            enums.EvidenceReviewProjection,
            {"proposed", "valid", "weak", "rejected"},
        ),
        (
            enums.ClaimReviewProjection,
            {"proposed", "needs_review", "verified", "rejected", "superseded"},
        ),
        (
            enums.SynthesisReviewProjection,
            {"draft", "needs_review", "verified", "rejected", "superseded"},
        ),
        (
            enums.DecisionBriefStatus,
            {"draft", "decision_ready", "decided", "archived"},
        ),
        (enums.DecisionBriefFreshnessStatus, {"current", "evidence_stale"}),
        (
            enums.BusinessRunEventType,
            {
                "investigation.started_from_signal",
                "run.queued",
                "run.started",
                "run.waiting_for_input",
                "run.resumed",
                "run.completed",
                "run.failed",
                "run.cancelled",
                "task.started",
                "task.completed",
                "task.failed",
                "tool.started",
                "tool.completed",
                "tool.failed",
                "evidence.proposed",
                "evidence.reviewed",
                "claim.version_proposed",
                "claim.version_reviewed",
                "claim.version_superseded",
                "synthesis.proposed",
                "synthesis.reviewed",
                "review.required",
            },
        ),
    ],
)
def test_closed_enum_values_are_exact(enum_type: type[enums.StrEnum], expected: set[str]) -> None:
    assert enum_values(enum_type) == expected


def test_stream_reset_is_not_a_business_event() -> None:
    assert "stream.reset" not in enum_values(enums.BusinessRunEventType)
    assert enum_values(enums.StreamControlEventType) == {"stream.reset"}


def test_contract_enums_match_domain_invariants() -> None:
    enums.assert_domain_enum_compatibility()


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WatchlistQueryRules.model_validate(
            {
                "include_terms": ["permissions"],
                "exclude_terms": [],
                "languages": ["en"],
                "regions": [],
                "unknown_rule": True,
            }
        )


def test_cursor_page_limit_is_bounded() -> None:
    assert CursorPagination().limit == 50
    with pytest.raises(ValidationError):
        CursorPagination(limit=101)


def test_all_contract_timestamps_require_utc() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        NavigationSummary.model_validate(
            {
                "workspace_id": uuid4(),
                "unreviewed_signal_count": 0,
                "investigation_needs_input_count": 0,
                "draft_decision_brief_count": 0,
                "monitoring_health": "healthy",
                "computed_at": datetime.now(timezone(timedelta(hours=8))),
                "data_authenticity": "generated",
            }
        )


def test_assessment_dimension_selects_the_exact_closed_level_enum() -> None:
    request = SignalAssessmentRequest.model_validate(
        {
            "dimension": "urgency",
            "confirmed_level": "unknown",
            "reason": "The timing cannot be determined yet.",
            "expected_signal_row_version": 1,
            "expected_assessment_version": 0,
        }
    )
    assert request.confirmed_level is enums.UrgencyLevel.UNKNOWN


def import_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "source_connection_id": str(uuid4()),
        "expected_source_row_version": 1,
        "expected_current_import_manifest_id": None,
        "local_manifest_digest": "sha256:local",
        "file_digest": "sha256:file",
        "expected_upload_digest": "sha256:upload",
        "client_file_name": "interviews.csv",
        "file_size_bytes": 100,
        "media_type": "text/csv",
        "parser_version": "csv-v1",
        "schema_version": "interview-v1",
        "selected_scope_json": {"columns": ["quote"]},
        "selected_scope_digest": "sha256:scope",
    }
    request.update(overrides)
    return request


@pytest.mark.parametrize(
    "file_name", ["/Users/me/interviews.csv", "../interviews.csv", r"C:\\tmp\\i.csv"]
)
def test_import_accepts_file_name_but_never_a_filesystem_path(file_name: str) -> None:
    with pytest.raises(ValidationError, match="not a filesystem path"):
        ImportSessionCreateRequest.model_validate(import_request(client_file_name=file_name))


def test_source_kind_runtime_pair_is_closed() -> None:
    with pytest.raises(ValidationError, match="incompatible"):
        SourceConnectionCreateRequest.model_validate(
            {
                "name": "Imported interviews",
                "source_kind": "imported_dataset",
                "runtime": "cloud",
                "connector_type": "csv",
                "connector_version": "1.0.0",
                "data_scope": "workspace_confidential",
            }
        )


def _property_names(schema: object) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            names.update(properties)
        for value in schema.values():
            names.update(_property_names(value))
    elif isinstance(schema, list):
        for value in schema:
            names.update(_property_names(value))
    return names


def test_public_schemas_have_no_secret_or_filesystem_path_fields() -> None:
    forbidden = {
        "access_token",
        "api_key",
        "cookie",
        "credential",
        "credential_ref",
        "filesystem_path",
        "local_path",
        "mac_path",
        "password",
        "refresh_token",
        "secret",
        "signed_url",
    }
    credential_input_models = {
        SourceConnectionCreateRequest,
        SourceConnectionUpdateRequest,
    }
    for model in ALL_CONTRACT_MODELS:
        properties = _property_names(model.model_json_schema(mode="serialization", by_alias=True))
        model_forbidden = forbidden - (
            {"credential_ref"} if model in credential_input_models else set()
        )
        assert model_forbidden.isdisjoint(properties), model.__name__
        assert not {name for name in properties if name.endswith("_path")}, model.__name__


def test_every_business_response_declares_authenticity() -> None:
    response_models = [
        model for model in ALL_CONTRACT_MODELS if model.__name__.endswith("Response")
    ]
    exempt = {"AcceptedCommand"}
    missing = {
        model.__name__
        for model in response_models
        if model.__name__ not in exempt and "data_authenticity" not in model.model_fields
    }
    assert not missing
