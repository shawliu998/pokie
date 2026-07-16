from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from packages.contracts.schemas import DecisionBriefBlockDocument
from services.api.app.core.object_store import get_object_store
from services.api.app.db.models import (
    BriefExport,
    Claim,
    ClaimEvidence,
    ContentItem,
    ContentVersion,
    DecisionBriefVersion,
    Evidence,
    ImportManifest,
    ImportManifestContentVersion,
    ImportSession,
    RawContentItem,
    ResearchRun,
    SignalEvidence,
    SourceConnection,
    Watchlist,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.common import digest
from services.api.app.modules.decisions.service import readiness_checklist_digest
from services.api.app.modules.research.service import ResearchRunResultRepository
from tests.conftest import command_headers, query_headers
from tests.integration.collected_research_fixtures import seed_collected_signal_scope


def _brief_document_digest(document: dict[str, Any]) -> str:
    canonical = DecisionBriefBlockDocument.model_validate(document).model_dump(mode="json")
    return digest(canonical)


def _create_investigation_and_run(
    client: TestClient, principal_id: str, fixture: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace = fixture["workspace"]
    source = fixture["source"]
    assert isinstance(workspace, dict) and isinstance(source, dict)
    workspace_id = str(workspace["id"])
    source_scope = {
        "source_connection_ids": [fixture["source"]["id"]],
        "content_version_ids": [fixture["content_version_id"]],
        "allow_cloud_model": False,
    }
    now = fixture["now"]
    question = "Should collected permission friction be prioritized?"
    signal = client.get(
        f"/v1/signals/{fixture['signal_id']}",
        headers=query_headers(principal_id, workspace_id),
    ).json()
    if signal["status"] == "new":
        triage = client.post(
            f"/v1/signals/{fixture['signal_id']}/triage",
            headers=command_headers(principal_id, workspace_id),
            json={
                "expected_signal_row_version": signal["row_version"],
                "business_impact": {
                    "confirmed_level": "high",
                    "reason": "Owner confirmed collected-source impact.",
                    "expected_assessment_version": signal["dimensions"]["business_impact"][
                        "version"
                    ],
                },
                "urgency": {
                    "confirmed_level": "this_week",
                    "reason": "Owner confirmed collected-source urgency.",
                    "expected_assessment_version": signal["dimensions"]["urgency"]["version"],
                },
            },
        )
        assert triage.status_code == 200, triage.text
    investigation_response = client.post(
        "/v1/investigations",
        headers=command_headers(principal_id, workspace_id),
        json={
            "signal_id": fixture["signal_id"],
            "decision_question": question,
            "source_scope": source_scope,
            "time_range": {
                "start": (now - timedelta(days=7)).isoformat(),
                "end": now.isoformat(),
            },
            "budget": {"max_cost_usd": 0, "max_duration_seconds": 60},
            "stop_conditions": ["one human-reviewed claim"],
        },
    )
    assert investigation_response.status_code == 201, investigation_response.text
    investigation = investigation_response.json()
    assert investigation["status"] == "draft"
    run_response = client.post(
        "/v1/research-runs",
        headers=command_headers(principal_id, workspace_id),
        json={
            "investigation_id": investigation["id"],
            "investigation_scope_version_id": investigation["current_scope_version_id"],
            "question": question,
            "source_scope": source_scope,
            "time_range": {
                "start": (now - timedelta(days=7)).isoformat(),
                "end": now.isoformat(),
            },
            "budget": {"max_cost_usd": 0, "max_duration_seconds": 60},
            "expected_investigation_row_version": investigation["row_version"],
        },
    )
    assert run_response.status_code == 202, run_response.text
    return investigation, run_response.json()


def test_untriaged_signal_cannot_create_investigation(
    client: TestClient, principal_id: str
) -> None:
    fixture = seed_collected_signal_scope(client, principal_id)
    workspace_id = str(fixture["workspace"]["id"])
    now = fixture["now"]
    response = client.post(
        "/v1/investigations",
        headers=command_headers(principal_id, workspace_id),
        json={
            "signal_id": fixture["signal_id"],
            "decision_question": "Should untriaged friction be prioritized?",
            "source_scope": {
                "source_connection_ids": [fixture["source"]["id"]],
                "content_version_ids": [fixture["content_version_id"]],
                "allow_cloud_model": False,
            },
            "time_range": {
                "start": (now - timedelta(days=7)).isoformat(),
                "end": now.isoformat(),
            },
            "budget": {"max_cost_usd": 0, "max_duration_seconds": 60},
            "stop_conditions": ["one human-reviewed claim"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRIAGE_REQUIRED"


def test_legacy_signal_dimensions_project_validated_defaults(
    client: TestClient, principal_id: str
) -> None:
    fixture = seed_collected_signal_scope(client, principal_id)
    workspace_id = str(fixture["workspace"]["id"])
    response = client.get(
        f"/v1/signals/{fixture['signal_id']}",
        headers=query_headers(principal_id, workspace_id),
    )
    assert response.status_code == 200, response.text
    signal = response.json()
    assert signal["dimensions"]["detection_confidence"]["level"] == "low"
    assert signal["dimensions"]["business_impact"]["suggestion_origin"] == "none"
    assert signal["dimensions"]["urgency"]["version"] == 0
    assert signal["dimensions"]["priority"]["status"] == "pending_confirmation"


def test_collected_signal_creates_v2_run_with_terminal_collection_lineage(
    client: TestClient, principal_id: str
) -> None:
    fixture = seed_collected_signal_scope(client, principal_id)
    workspace = fixture["workspace"]
    assert isinstance(workspace, dict)
    workspace_id = str(workspace["id"])

    evidence_response = client.get(
        f"/v1/signals/{fixture['signal_id']}/evidence",
        headers=query_headers(principal_id, workspace_id),
    )
    assert evidence_response.status_code == 200, evidence_response.text
    signal_evidence = evidence_response.json()["items"]
    assert signal_evidence[0]["independence_group_id"] == fixture["independence_group_id"]

    _investigation, run = _create_investigation_and_run(client, principal_id, fixture)
    assert run["graph_version"] == "deterministic-content-v2"
    assert run["data_authenticity"] == "collected"
    with get_session_factory()() as db:
        run_row = db.get(ResearchRun, str(run["id"]))
        assert run_row is not None
        manifest = run_row.run_input_manifest_json
        assert manifest["schema_version"] == "run-input-manifest-v2"
        assert manifest["terminal_import_manifests"] == []
        assert len(manifest["terminal_collection_runs"]) == 1
        terminal_run = manifest["terminal_collection_runs"][0]
        assert terminal_run["collection_run_id"] == fixture["collection_run_id"]
        assert terminal_run["state"] == "succeeded"
        assert terminal_run["finished_at"] is not None
        content = manifest["content_versions"][0]
        assert content["origin_type"] == "collected"
        assert content["import_manifest_id"] is None
        assert content["collection_run_id"] == fixture["collection_run_id"]
        assert content["raw_content_item_id"] == fixture["raw_content_item_id"]
        assert content["signal_evidence_independence_group_id"] == fixture["independence_group_id"]
        claimed = ResearchRunResultRepository.claim_queued(
            db,
            workspace_id=workspace_id,
            run_id=str(run["id"]),
            worker_id="worker-v2",
            worker_attempt_id="attempt-v2",
        )
        assert claimed is not None
    with get_session_factory()() as db:
        ResearchRunResultRepository.mark_started(
            db,
            workspace_id=workspace_id,
            run_id=str(run["id"]),
            worker_attempt_id="attempt-v2",
        )
        evidence_rows, claim_version = ResearchRunResultRepository.persist_deterministic_result(
            db,
            workspace_id=workspace_id,
            run_id=str(run["id"]),
            actor_id=principal_id,
            request_id="collected-research-result",
            worker_attempt_id="attempt-v2",
            evidence_proposals=[
                {
                    "content_version_id": fixture["content_version_id"],
                    "quote_start": 0,
                    "quote_end": 47,
                    "stance": "supports",
                    "relevance": 0.9,
                    "reliability": 0.8,
                    "independence": 0.8,
                    "recency": 1.0,
                    "specificity": 0.8,
                }
            ],
            claim_proposal={
                "claim_type": "observation",
                "text": "Permission friction blocks onboarding.",
                "limitations": [],
            },
        )
        assert len(evidence_rows) == 1
        stored = db.scalar(select(Evidence).where(Evidence.id == evidence_rows[0].id))
        assert stored is not None
        assert stored.extraction_method == "deterministic_content_v2"
        assert stored.data_authenticity == "collected"
        assert claim_version.data_authenticity == "collected"
        assert claim_version.generation_method == "deterministic"
        assert claim_version.suggestion_origin == "deterministic_rule"
        assert claim_version.generator_version == "deterministic-content-v2"
        assert claim_version.confidence_policy_version == "claim-confidence-v2"
        assert claim_version.confidence_score == 0
        assert claim_version.confidence_inputs_json["effective_evidence_count"] == 0
        assert claim_version.confidence_input_digest.startswith("sha256:")
        evidence_id = stored.id
        claim = db.scalar(select(Claim).where(Claim.current_version_id == claim_version.id))
        assert claim is not None
        claim_id = claim.id
        claim_version_id = claim_version.id

    claim_page_response = client.get(
        f"/v1/claims?investigation_id={_investigation['id']}",
        headers=query_headers(principal_id, workspace_id),
    )
    assert claim_page_response.status_code == 200, claim_page_response.text
    projected_claim = claim_page_response.json()["items"][0]
    assert projected_claim["id"] == claim_id
    assert projected_claim["current_version"]["claim_type"] == "observation"
    assert projected_claim["data_authenticity"] == "collected"

    evidence_review_response = client.post(
        f"/v1/evidence/{evidence_id}/review",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision": "valid",
            "reason": "Collected quote and origin were verified",
            "policy_version": "evidence-review-v1",
        },
    )
    assert evidence_review_response.status_code == 201, evidence_review_response.text
    assert evidence_review_response.json()["data_authenticity"] == "collected"
    evidence_review_id = evidence_review_response.json()["id"]
    with get_session_factory()() as db:
        claim_row = db.get(Claim, claim_id)
        links = db.scalars(
            select(ClaimEvidence).where(ClaimEvidence.claim_version_id == claim_version_id)
        ).all()
        assert claim_row is not None
        snapshot_digest = digest(
            {
                "claim_version_id": claim_version_id,
                "claim_evidence_ids": [link.id for link in links],
                "evidence_review_ids": [evidence_review_id],
            }
        )
        claim_row_version = claim_row.row_version
    claim_review_response = client.post(
        f"/v1/claims/{claim_id}/versions/{claim_version_id}/review",
        headers=command_headers(principal_id, workspace_id),
        json={
            "claim_version_id": claim_version_id,
            "expected_claim_row_version": claim_row_version,
            "decision": "verify",
            "evidence_review_ids": [evidence_review_id],
            "expected_claim_evidence_snapshot_digest": snapshot_digest,
            "reason": "Collected evidence snapshot is exact",
        },
    )
    assert claim_review_response.status_code == 201, claim_review_response.text
    assert claim_review_response.json()["data_authenticity"] == "collected"

    synthesis_response = client.post(
        f"/v1/investigations/{_investigation['id']}/synthesis",
        headers=command_headers(principal_id, workspace_id),
        json={"verified_claim_version_ids": [claim_version_id]},
    )
    assert synthesis_response.status_code == 201, synthesis_response.text
    synthesis = synthesis_response.json()
    assert synthesis["data_authenticity"] == "collected"
    assert synthesis["current_version"]["data_authenticity"] == "collected"
    synthesis_version_id = synthesis["current_version"]["id"]
    synthesis_review_response = client.post(
        f"/v1/investigations/{_investigation['id']}/synthesis/versions/"
        f"{synthesis_version_id}/review",
        headers=command_headers(principal_id, workspace_id),
        json={
            "synthesis_version_id": synthesis_version_id,
            "expected_row_version": synthesis["row_version"],
            "decision": "verify",
            "reason": "Synthesis is grounded in a verified collected claim",
            "policy_version": "synthesis-review-v1",
        },
    )
    assert synthesis_review_response.status_code == 201, synthesis_review_response.text
    assert synthesis_review_response.json()["data_authenticity"] == "collected"

    brief_response = client.post(
        f"/v1/investigations/{_investigation['id']}/decision-brief",
        headers=command_headers(principal_id, workspace_id),
        json={
            "synthesis_version_id": synthesis_version_id,
            "template_version": "decision-brief-v1",
        },
    )
    assert brief_response.status_code == 201, brief_response.text
    brief = brief_response.json()
    assert brief["data_authenticity"] == "collected"
    assert brief["current_version"]["data_authenticity"] == "collected"
    document = brief["current_version"]["block_document"]
    document["no_counter_evidence_search"] = {
        "queries": ["permission friction counter evidence"],
        "source_connection_ids": [fixture["source"]["id"]],
        "window_start": (fixture["now"] - timedelta(days=7)).isoformat(),
        "window_end": fixture["now"].isoformat(),
        "exclusion_criteria": ["Excluded content outside the frozen CollectionRun window."],
        "limitations": ["One approved cloud source may not represent all users."],
    }
    for block in document["blocks"]:
        if block["type"] == "pm_judgment":
            block["body"] = "Prioritize a collected-source permission preview experiment."
        elif block["type"] == "recommendation":
            block["body"] = "Prototype the permission preview from collected evidence."
            block["recommendation_status"] = "accepted"
    brief_update_response = client.patch(
        f"/v1/decision-briefs/{brief['id']}",
        headers=command_headers(principal_id, workspace_id),
        json={
            "block_document": document,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": _brief_document_digest(document),
        },
    )
    assert brief_update_response.status_code == 200, brief_update_response.text
    brief = brief_update_response.json()
    with get_session_factory()() as db:
        brief_version = db.get(DecisionBriefVersion, brief["current_version"]["id"])
        assert brief_version is not None
        checklist_digest = readiness_checklist_digest(brief_version, "decision-readiness-v1")
    ready_response = client.post(
        f"/v1/decision-briefs/{brief['id']}/mark-decision-ready",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "expected_row_version": brief["row_version"],
            "decision": "mark_decision_ready",
            "reason": "Collected-only owner loop is review-complete",
            "policy_version": "decision-readiness-v1",
            "checklist_digest": checklist_digest,
        },
    )
    assert ready_response.status_code == 201, ready_response.text
    assert ready_response.json()["data_authenticity"] == "collected"

    selected_block_ids = [
        block["id"]
        for block in document["blocks"]
        if block["type"] in {"fact", "pm_judgment", "recommendation"}
    ]
    preview_response = client.post(
        f"/v1/decision-briefs/{brief['id']}/exports/preview",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "export_type": "prd_research_input_markdown",
            "selection_manifest": {
                "block_ids": selected_block_ids,
                "include_citations": True,
            },
        },
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["data_authenticity"] == "collected"
    assert "> Data authenticity: Collected" in preview["rendered_content"]
    export_response = client.post(
        f"/v1/decision-briefs/{brief['id']}/exports",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "export_type": "prd_research_input_markdown",
            "destination": "local_download",
            "selection_manifest": {
                "block_ids": selected_block_ids,
                "include_citations": True,
            },
            "reference_digest": preview["reference_digest"],
            "export_timestamp": preview["export_timestamp"],
        },
    )
    assert export_response.status_code == 201, export_response.text
    exported = export_response.json()
    assert exported["data_authenticity"] == "collected"
    with get_session_factory()() as db:
        export_row = db.get(BriefExport, exported["id"])
        assert export_row is not None
        stored = get_object_store().get(export_row.rendered_snapshot_uri.removeprefix("object://"))
        assert stored.body == preview["rendered_content"].encode()
        assert export_row.output_digest == digest(stored.body)
        assert exported["output_digest"] == export_row.output_digest


def test_mixed_imported_and_collected_signal_freezes_exactly_one_origin_per_content(
    client: TestClient, principal_id: str
) -> None:
    fixture = seed_collected_signal_scope(client, principal_id)
    workspace = fixture["workspace"]
    assert isinstance(workspace, dict)
    workspace_id = str(workspace["id"])
    imported_source_id = "66666666-6666-5666-8666-666666666666"
    with get_session_factory()() as db:
        source = SourceConnection(
            id=imported_source_id,
            workspace_id=workspace_id,
            name="Imported interviews",
            source_kind="imported_dataset",
            runtime="static_import",
            connector_type="csv",
            connector_version="csv-v1",
            status="healthy",
            data_authenticity="imported",
        )
        session = ImportSession(
            workspace_id=workspace_id,
            source_connection_id=source.id,
            expected_source_row_version=1,
            local_manifest_digest="sha256:mixed-local",
            file_digest="sha256:mixed-file",
            expected_upload_digest="sha256:mixed-upload",
            client_file_name="mixed.csv",
            file_size_bytes=10,
            media_type="text/csv",
            parser_version="csv-v1",
            schema_version="mixed-v1",
            selected_scope_json={"columns": ["body"]},
            selected_scope_digest="sha256:mixed-scope",
            state="finalized",
            uploaded_object_key="imports/mixed.csv",
            uploaded_object_digest="sha256:mixed-upload",
            created_by=principal_id,
            data_authenticity="imported",
        )
        db.add_all([source, session])
        db.flush()
        manifest = ImportManifest(
            workspace_id=workspace_id,
            import_session_id=session.id,
            source_connection_id=source.id,
            file_digest=session.file_digest,
            uploaded_object_key="imports/mixed.csv",
            uploaded_object_digest=session.expected_upload_digest,
            parser_version="csv-v1",
            schema_version="mixed-v1",
            selected_scope_json={"columns": ["body"]},
            selected_scope_digest=session.selected_scope_digest,
            consent_record_id=str(fixture["signal_id"]),
            normalized_payload_digest="sha256:mixed-normalized",
            content_count=1,
            finalized_at=fixture["now"],
            data_authenticity="imported",
        )
        db.add(manifest)
        db.flush()
        source.current_import_manifest_id = manifest.id
        session.terminal_manifest_id = manifest.id
        raw = RawContentItem(
            workspace_id=workspace_id,
            import_manifest_id=manifest.id,
            source_connection_id=source.id,
            source_external_id="interview-1",
            raw_snapshot_uri="s3://glint/imports/mixed-row-1.json",
            raw_digest="sha256:mixed-raw",
            data_authenticity="imported",
        )
        item = ContentItem(
            workspace_id=workspace_id,
            source_connection_id=source.id,
            source_item_id="interview-1",
            identity_key="csv:interview-1",
            title="Imported permission interview",
            data_authenticity="imported",
        )
        db.add_all([raw, item])
        db.flush()
        version = ContentVersion(
            workspace_id=workspace_id,
            content_item_id=item.id,
            source_connection_id=source.id,
            raw_content_item_id=raw.id,
            version_number=1,
            content_digest="sha256:mixed-content",
            normalized_title=item.title,
            normalized_body="Imported interview confirms permission friction.",
            captured_at=fixture["now"],
            raw_snapshot_uri=raw.raw_snapshot_uri,
            parser_version="csv-v1",
            data_authenticity="imported",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        db.add(
            ImportManifestContentVersion(
                workspace_id=workspace_id,
                import_manifest_id=manifest.id,
                content_version_id=version.id,
                ordinal=1,
                data_authenticity="imported",
            )
        )
        db.add(
            SignalEvidence(
                workspace_id=workspace_id,
                signal_id=str(fixture["signal_id"]),
                content_version_id=version.id,
                role="context",
                contribution=0.5,
                added_by="worker",
                data_authenticity="imported",
            )
        )
        later_session = ImportSession(
            workspace_id=workspace_id,
            source_connection_id=source.id,
            expected_source_row_version=2,
            local_manifest_digest="sha256:later-local",
            file_digest="sha256:later-file",
            expected_upload_digest="sha256:later-upload",
            client_file_name="later.csv",
            file_size_bytes=11,
            media_type="text/csv",
            parser_version="csv-v1",
            schema_version="mixed-v1",
            selected_scope_json={"columns": ["body"]},
            selected_scope_digest="sha256:later-scope",
            state="finalized",
            uploaded_object_key="imports/later.csv",
            uploaded_object_digest="sha256:later-upload",
            created_by=principal_id,
            data_authenticity="imported",
        )
        db.add(later_session)
        db.flush()
        later_manifest = ImportManifest(
            workspace_id=workspace_id,
            import_session_id=later_session.id,
            source_connection_id=source.id,
            file_digest=later_session.file_digest,
            uploaded_object_key="imports/later.csv",
            uploaded_object_digest=later_session.expected_upload_digest,
            parser_version="csv-v1",
            schema_version="mixed-v1",
            selected_scope_json={"columns": ["body"]},
            selected_scope_digest=later_session.selected_scope_digest,
            consent_record_id=str(fixture["signal_id"]),
            normalized_payload_digest="sha256:later-normalized",
            content_count=0,
            finalized_at=fixture["now"],
            data_authenticity="imported",
        )
        db.add(later_manifest)
        db.flush()
        later_session.terminal_manifest_id = later_manifest.id
        source.current_import_manifest_id = later_manifest.id
        later_manifest_id = later_manifest.id
        watchlist = db.get(Watchlist, str(fixture["watchlist"]["id"]))
        assert watchlist is not None
        watchlist.rules_json = {
            **watchlist.rules_json,
            "source_connection_ids": [str(fixture["source"]["id"]), source.id],
        }
        db.commit()
        imported_version_id = version.id

    source_scope = {
        "source_connection_ids": [str(fixture["source"]["id"]), imported_source_id],
        "content_version_ids": [fixture["content_version_id"], imported_version_id],
        "allow_cloud_model": False,
    }
    now = fixture["now"]
    signal = client.get(
        f"/v1/signals/{fixture['signal_id']}",
        headers=query_headers(principal_id, workspace_id),
    ).json()
    triage = client.post(
        f"/v1/signals/{fixture['signal_id']}/triage",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_signal_row_version": signal["row_version"],
            "business_impact": {
                "confirmed_level": "high",
                "reason": "Owner confirmed mixed-source impact.",
                "expected_assessment_version": signal["dimensions"]["business_impact"]["version"],
            },
            "urgency": {
                "confirmed_level": "this_week",
                "reason": "Owner confirmed mixed-source urgency.",
                "expected_assessment_version": signal["dimensions"]["urgency"]["version"],
            },
        },
    )
    assert triage.status_code == 200, triage.text
    investigation_response = client.post(
        "/v1/investigations",
        headers=command_headers(principal_id, workspace_id),
        json={
            "signal_id": fixture["signal_id"],
            "decision_question": "Should mixed evidence change the permission roadmap?",
            "source_scope": source_scope,
            "time_range": {
                "start": (now - timedelta(days=7)).isoformat(),
                "end": now.isoformat(),
            },
            "budget": {"max_cost_usd": 0, "max_duration_seconds": 60},
            "stop_conditions": ["one human-reviewed claim"],
        },
    )
    assert investigation_response.status_code == 201, investigation_response.text
    investigation = investigation_response.json()
    run_response = client.post(
        "/v1/research-runs",
        headers=command_headers(principal_id, workspace_id),
        json={
            "investigation_id": investigation["id"],
            "investigation_scope_version_id": investigation["current_scope_version_id"],
            "question": investigation["decision_question"],
            "source_scope": source_scope,
            "time_range": {
                "start": (now - timedelta(days=7)).isoformat(),
                "end": now.isoformat(),
            },
            "budget": {"max_cost_usd": 0, "max_duration_seconds": 60},
            "expected_investigation_row_version": investigation["row_version"],
        },
    )
    assert run_response.status_code == 202, run_response.text
    with get_session_factory()() as db:
        run = db.get(ResearchRun, run_response.json()["id"])
        assert run is not None
        manifest_json = run.run_input_manifest_json
        assert manifest_json["schema_version"] == "run-input-manifest-v2"
        assert len(manifest_json["terminal_import_manifests"]) == 1
        assert (
            manifest_json["terminal_import_manifests"][0]["import_manifest_id"]
            != later_manifest_id
        )
        assert len(manifest_json["terminal_collection_runs"]) == 1
        assert {item["origin_type"] for item in manifest_json["content_versions"]} == {
            "imported",
            "collected",
        }
        assert all(
            (item["import_manifest_id"] is None) != (item["collection_run_id"] is None)
            for item in manifest_json["content_versions"]
        )
