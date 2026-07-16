from __future__ import annotations

from services.api.app.main import app


def _response_ref(spec: dict[str, object], path: str, method: str, status: str) -> str:
    operation = spec["paths"][path][method]  # type: ignore[index]
    return operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]  # type: ignore[index]


def test_exact_version_replay_and_revision_routes_use_canonical_contracts() -> None:
    spec = app.openapi()
    expected = {
        (
            "/v1/claims/{claim_id}/versions/{version_id}",
            "get",
            "200",
        ): "#/components/schemas/ClaimVersionResponse",
        (
            "/v1/investigations/{investigation_id}/synthesis/versions/{version_id}",
            "get",
            "200",
        ): "#/components/schemas/InvestigationSynthesisVersionResponse",
        (
            "/v1/decision-briefs/{brief_id}/versions/{version_id}",
            "get",
            "200",
        ): "#/components/schemas/DecisionBriefVersionResponse",
        (
            "/v1/brief-exports/{export_id}",
            "get",
            "200",
        ): "#/components/schemas/BriefExportResponse",
        (
            "/v1/decision-briefs/{brief_id}/revisions",
            "post",
            "201",
        ): "#/components/schemas/DecisionBriefResponse",
        (
            "/v1/content-items/{item_id}/versions",
            "get",
            "200",
        ): "#/components/schemas/CursorPage_ContentVersionResponse_",
        (
            "/v1/audit-logs",
            "get",
            "200",
        ): "#/components/schemas/CursorPage_AuditLogResponse_",
    }
    for (path, method, status), schema_ref in expected.items():
        assert _response_ref(spec, path, method, status) == schema_ref

    revision = spec["paths"]["/v1/decision-briefs/{brief_id}/revisions"]["post"]
    assert (
        revision["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/DecisionBriefRevisionRequest"
    )
    audit_parameters = {
        parameter["name"]
        for parameter in spec["paths"]["/v1/audit-logs"]["get"]["parameters"]
        if parameter["in"] == "query"
    }
    assert {
        "action",
        "target_type",
        "target_id",
        "actor_id",
        "occurred_after",
        "occurred_before",
        "cursor",
        "limit",
    }.issubset(audit_parameters)
    audit_properties = spec["components"]["schemas"]["AuditLogResponse"]["properties"]
    assert "details_json" not in audit_properties
    assert (
        "rendered_snapshot_uri"
        not in spec["components"]["schemas"]["BriefExportResponse"]["properties"]
    )
    for path in ("/v1/content-items", "/v1/content-items/{item_id}/versions"):
        content_query_parameters = {
            parameter["name"]
            for parameter in spec["paths"][path]["get"]["parameters"]
            if parameter["in"] == "query"
        }
        assert {"cursor", "limit"}.issubset(content_query_parameters)
