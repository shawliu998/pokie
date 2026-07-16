from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from packages.contracts.schemas import DecisionBriefBlockDocument
from services.api.app.core.object_store import get_object_store
from services.api.app.db.models import (
    BriefExport,
    Claim,
    ClaimEvidence,
    ClaimVersion,
    ContentItem,
    ContentVersion,
    Evidence,
    ImportManifestContentVersion,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.common import digest
from services.api.app.modules.decisions.service import readiness_checklist_digest
from services.api.app.modules.research.service import ResearchRunResultRepository
from services.api.app.modules.sources.service import ImportFinalizationRepository
from tests.conftest import command_headers, query_headers
from tests.integration.import_proposals import NormalizedFixtureItem, normalization_proposal


def _sha(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def _brief_document_digest(document: dict[str, Any]) -> str:
    canonical = DecisionBriefBlockDocument.model_validate(document).model_dump(mode="json")
    return digest(canonical)


def _bootstrap(client: TestClient, principal_id: str) -> dict[str, Any]:
    workspace = client.post(
        "/v1/workspaces",
        headers=command_headers(principal_id),
        json={"name": "AI Coding Agents"},
    ).json()
    workspace_id = workspace["id"]
    project = client.post(
        "/v1/projects",
        headers=command_headers(principal_id, workspace_id),
        json={"name": "Research"},
    ).json()
    source = client.post(
        "/v1/sources",
        headers=command_headers(principal_id, workspace_id),
        json={
            "name": "Imported interviews",
            "source_kind": "imported_dataset",
            "runtime": "static_import",
            "connector_type": "csv",
            "connector_version": "1.0.0",
            "data_scope": "workspace_confidential",
        },
    ).json()
    source = client.post(
        f"/v1/sources/{source['id']}/activate",
        headers=command_headers(principal_id, workspace_id),
        json={"expected_row_version": source["row_version"], "reason": "Approved fixture import"},
    ).json()
    watchlist = client.post(
        "/v1/watchlists",
        headers=command_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "name": "Permissions",
            "objective": "Understand permission setup friction",
            "source_connection_ids": [source["id"]],
            "rules": {
                "entities": ["Codex"],
                "query_rules": {"include_terms": ["permission"]},
                "cadence": "manual",
                "current_window_days": 7,
                "baseline_window_days": 28,
            },
        },
    ).json()
    client.post(
        f"/v1/watchlists/{watchlist['id']}/activate",
        headers=command_headers(principal_id, workspace_id),
        json={"expected_row_version": watchlist["row_version"], "reason": "Ready"},
    )
    return {"workspace": workspace, "project": project, "source": source, "watchlist": watchlist}


def _finalized_import(
    client: TestClient, principal_id: str, bootstrap: dict[str, Any]
) -> dict[str, Any]:
    workspace_id = bootstrap["workspace"]["id"]
    source = bootstrap["source"]
    csv_body = (
        b"problem,quote,url,author,published_at\n"
        b"Permissions,Need a preview before granting access,"
        b"https://example.com/issues/1,Ada,2026-07-14T08:00:00Z\n"
        b"Pricing,Team plan is expensive,https://example.com/issues/2,Lin,2026-07-14T09:00:00Z\n"
    )
    scope = {"columns": ["problem", "quote"]}
    session = client.post(
        "/v1/imports",
        headers=command_headers(principal_id, workspace_id),
        json={
            "source_connection_id": source["id"],
            "expected_source_row_version": source["row_version"],
            "expected_current_import_manifest_id": None,
            "local_manifest_digest": _sha(csv_body),
            "file_digest": _sha(csv_body),
            "expected_upload_digest": _sha(csv_body),
            "client_file_name": "interviews.csv",
            "file_size_bytes": len(csv_body),
            "media_type": "text/csv",
            "parser_version": "csv-v1",
            "schema_version": "interview-import-v1",
            "selected_scope_json": scope,
            "selected_scope_digest": _sha(b"problem,quote"),
        },
    ).json()
    preview_response = client.get(
        f"/v1/imports/{session['id']}/upload-consent/preview",
        headers=query_headers(principal_id, workspace_id),
        params={"expected_row_version": session["row_version"]},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    consent_response = client.post(
        f"/v1/imports/{session['id']}/upload-consent",
        headers=command_headers(principal_id, workspace_id),
        json={
            "preview_scope": preview["preview_scope"],
            "scope_digest": preview["scope_digest"],
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "confirmation": True,
        },
    )
    assert consent_response.status_code == 200
    consent = consent_response.json()
    session = consent["import_session"]
    upload = client.put(
        f"/v1/imports/{session['id']}/object",
        headers=command_headers(
            principal_id,
            workspace_id,
            **{
                "X-Upload-Grant": consent_response.headers["X-Upload-Grant"],
                "Content-Type": "text/csv",
            },
        ),
        content=csv_body,
    )
    assert upload.status_code == 201
    session = client.post(
        f"/v1/imports/{session['id']}/upload-complete",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_row_version": session["row_version"],
            "object_key": consent["upload"]["object_key"],
        },
    ).json()
    finalize_key = str(uuid4())
    finalize_headers = command_headers(principal_id, workspace_id)
    finalize_headers["Idempotency-Key"] = finalize_key
    first = client.post(
        f"/v1/imports/{session['id']}/finalize",
        headers=finalize_headers,
        json={"expected_row_version": session["row_version"]},
    )
    assert first.status_code == 202
    replay = client.post(
        f"/v1/imports/{session['id']}/finalize",
        headers=finalize_headers,
        json={"expected_row_version": session["row_version"]},
    )
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    job = first.json()
    with get_session_factory()() as db:
        ImportFinalizationRepository.claim(
            db,
            workspace_id=workspace_id,
            command_id=job["id"],
            worker_id="worker-1",
        )
    normalized: list[NormalizedFixtureItem] = [
        {
            "external_id": f"{session['id']}:row:1",
            "title": "Permissions",
            "body": "problem: Permissions\nquote: Need a preview before granting access",
            "canonical_url": "https://example.com/issues/1",
            "author": "Ada",
            "published_at": "2026-07-14T08:00:00Z",
        },
        {
            "external_id": f"{session['id']}:row:2",
            "title": "Pricing",
            "body": "problem: Pricing\nquote: Team plan is expensive",
            "canonical_url": "https://example.com/issues/2",
            "author": "Lin",
            "published_at": "2026-07-14T09:00:00Z",
        },
    ]
    with get_session_factory()() as db:
        proposal = normalization_proposal(db, command_id=job["id"], items=normalized)
        manifest = ImportFinalizationRepository.complete(
            db,
            workspace_id=workspace_id,
            command_id=job["id"],
            worker_id="worker-1",
            proposal=proposal,
        )
        manifest_id = manifest.id
        assert manifest.id == str(proposal.manifest.id)
        assert manifest.normalized_payload_digest == proposal.manifest.normalized_payload_digest
    with get_session_factory()() as db:
        same = ImportFinalizationRepository.complete(
            db,
            workspace_id=workspace_id,
            command_id=job["id"],
            worker_id="worker-1",
            proposal=proposal,
        )
        assert same.id == manifest_id
        version_ids = db.scalars(
            select(ImportManifestContentVersion.content_version_id).where(
                ImportManifestContentVersion.import_manifest_id == manifest_id
            )
        ).all()
        assert len(version_ids) == 2
        first_item = db.get(ContentItem, str(proposal.content_items[0].id))
        first_version = db.get(ContentVersion, str(proposal.content_versions[0].id))
        assert first_item is not None and first_version is not None
        assert first_item.canonical_url == "https://example.com/issues/1"
        assert first_version.content_digest == proposal.content_versions[0].content_digest
        assert first_version.metadata_json["author"] == "Ada"
        assert first_version.metadata_json["published_at"] == "2026-07-14T08:00:00+00:00"
    return {"manifest_id": manifest_id, "version_ids": list(version_ids)}


def test_import_consent_terminal_manifest_and_lineage(
    client: TestClient, principal_id: str
) -> None:
    bootstrap = _bootstrap(client, principal_id)
    result = _finalized_import(client, principal_id, bootstrap)
    workspace_id = bootstrap["workspace"]["id"]
    manifest = client.get(
        f"/v1/import-manifests/{result['manifest_id']}",
        headers=query_headers(principal_id, workspace_id),
    )
    assert manifest.status_code == 200
    assert manifest.json()["content_count"] == 2
    signals = client.get("/v1/signals", headers=query_headers(principal_id, workspace_id)).json()
    assert len(signals["items"]) == 1
    imported_signal = signals["items"][0]
    assert imported_signal["detector_version"] == "import-signal-v1"
    assert imported_signal["trigger_rules"] == ["static_import_content_count > 0"]
    assert imported_signal["limitations"] == ["Static import has no continuous freshness."]
    assert imported_signal["total_source_count"] == 1
    assert imported_signal["per_source_freshness"] == [
        {
            "source_connection_id": bootstrap["source"]["id"],
            "state": "current",
            "last_success_at": manifest.json()["finalized_at"],
        }
    ]
    collection_runs = client.get(
        "/v1/collection-runs", headers=query_headers(principal_id, workspace_id)
    )
    assert collection_runs.status_code == 200
    assert collection_runs.json()["items"][0]["state"] == "succeeded"


def test_exact_version_research_review_and_export(client: TestClient, principal_id: str) -> None:
    bootstrap = _bootstrap(client, principal_id)
    imported = _finalized_import(client, principal_id, bootstrap)
    workspace_id = bootstrap["workspace"]["id"]
    signal = client.get("/v1/signals", headers=query_headers(principal_id, workspace_id)).json()[
        "items"
    ][0]
    signal_id = signal["id"]
    triaged = client.post(
        f"/v1/signals/{signal_id}/triage",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_signal_row_version": signal["row_version"],
            "business_impact": {
                "confirmed_level": "high",
                "reason": "Owner confirmed onboarding impact.",
                "expected_assessment_version": signal["dimensions"]["business_impact"]["version"],
            },
            "urgency": {
                "confirmed_level": "this_week",
                "reason": "Owner confirmed planning urgency.",
                "expected_assessment_version": signal["dimensions"]["urgency"]["version"],
            },
        },
    )
    assert triaged.status_code == 200, triaged.text
    start = datetime.now(UTC) - timedelta(days=7)
    end = datetime.now(UTC)
    investigation = client.post(
        "/v1/investigations",
        headers=command_headers(principal_id, workspace_id),
        json={
            "signal_id": signal_id,
            "decision_question": "Should permission preview be prioritized?",
            "source_scope": {
                "source_connection_ids": [bootstrap["source"]["id"]],
                "content_version_ids": imported["version_ids"],
                "allow_cloud_model": False,
            },
            "time_range": {"start": start.isoformat(), "end": end.isoformat()},
            "budget": {"max_cost_usd": 0, "max_duration_seconds": 60},
            "stop_conditions": ["one verified claim"],
        },
    ).json()
    assert investigation["status"] == "draft"
    direct_activate = client.post(
        f"/v1/investigations/{investigation['id']}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "activate",
            "expected_row_version": investigation["row_version"],
            "reason": "Direct activation must not bypass the first Run transaction.",
        },
    )
    assert direct_activate.status_code == 422
    run = client.post(
        "/v1/research-runs",
        headers=command_headers(principal_id, workspace_id),
        json={
            "investigation_id": investigation["id"],
            "investigation_scope_version_id": investigation["current_scope_version_id"],
            "question": investigation["decision_question"],
            "source_scope": {
                "source_connection_ids": [bootstrap["source"]["id"]],
                "content_version_ids": imported["version_ids"],
                "allow_cloud_model": False,
            },
            "time_range": {"start": start.isoformat(), "end": end.isoformat()},
            "budget": {"max_cost_usd": 0, "max_duration_seconds": 60},
            "expected_investigation_row_version": investigation["row_version"],
        },
    ).json()
    investigation_after_run = client.get(
        f"/v1/investigations/{investigation['id']}",
        headers=query_headers(principal_id, workspace_id),
    ).json()
    assert investigation_after_run["status"] == "active"
    signal_after_run = client.get(
        f"/v1/signals/{signal_id}", headers=query_headers(principal_id, workspace_id)
    ).json()
    assert signal_after_run["status"] == "investigating"
    with get_session_factory()() as db:
        claimed = ResearchRunResultRepository.claim_queued(
            db,
            workspace_id=workspace_id,
            run_id=run["id"],
            worker_id="worker-1",
            worker_attempt_id="attempt-1",
        )
        assert claimed is not None
    with get_session_factory()() as db:
        ResearchRunResultRepository.mark_started(
            db, workspace_id=workspace_id, run_id=run["id"], worker_attempt_id="attempt-1"
        )
        versions = db.scalars(
            select(ContentVersion).where(ContentVersion.id.in_(imported["version_ids"]))
        ).all()
        proposals = [
            {
                "content_version_id": version.id,
                "quote_start": 0,
                "quote_end": len(version.normalized_body),
                "stance": "supports",
                "relevance": 0.9,
                "reliability": 0.8,
                "independence": 0.7,
                "recency": 0.8,
                "specificity": 0.9,
            }
            for version in versions
        ]
        evidence_rows, claim_version = ResearchRunResultRepository.persist_deterministic_result(
            db,
            workspace_id=workspace_id,
            run_id=run["id"],
            actor_id=principal_id,
            request_id=str(uuid4()),
            worker_attempt_id="attempt-1",
            evidence_proposals=proposals,
            claim_proposal={
                "claim_type": "product_risk",
                "text": "Permission setup creates onboarding friction.",
                "limitations": ["Imported interviews only."],
            },
        )
        evidence_ids = [row.id for row in evidence_rows]
        claim_version_id = claim_version.id
        claim = db.scalar(select(Claim).where(Claim.current_version_id == claim_version_id))
        assert claim is not None
        claim_id = claim.id
    for evidence_id in evidence_ids:
        review_response = client.post(
            f"/v1/evidence/{evidence_id}/review",
            headers=command_headers(principal_id, workspace_id),
            json={
                "decision": "valid",
                "reason": "Exact quote verified",
                "policy_version": "evidence-review-v1",
            },
        )
        assert review_response.status_code == 201, review_response.text
    # A restarted client reconstructs the exact append-only review snapshot from GET.
    evidence_review_ids: list[str] = []
    for evidence_id in evidence_ids:
        evidence_projection = client.get(
            f"/v1/evidence/{evidence_id}",
            headers=query_headers(principal_id, workspace_id),
        )
        assert evidence_projection.status_code == 200, evidence_projection.text
        latest_review = evidence_projection.json()["latest_review"]
        assert latest_review is not None
        assert latest_review["decision"] == "valid"
        assert latest_review["policy_version"] == "evidence-review-v1"
        evidence_review_ids.append(latest_review["id"])
    with get_session_factory()() as db:
        claim_row = db.get(Claim, claim_id)
        links = db.scalars(
            select(ClaimEvidence)
            .where(ClaimEvidence.claim_version_id == claim_version_id)
            .order_by(ClaimEvidence.id)
        ).all()
        snapshot_digest = digest(
            {
                "claim_version_id": claim_version_id,
                "claim_evidence_ids": [row.id for row in links],
                "evidence_review_ids": sorted(evidence_review_ids),
            }
        )
        claim_row_version = claim_row.row_version if claim_row else 0
    claim_review = client.post(
        f"/v1/claims/{claim_id}/versions/{claim_version_id}/review",
        headers=command_headers(principal_id, workspace_id),
        json={
            "claim_version_id": claim_version_id,
            "expected_claim_row_version": claim_row_version,
            "decision": "verify",
            "evidence_review_ids": evidence_review_ids,
            "expected_claim_evidence_snapshot_digest": snapshot_digest,
            "reason": "Support is represented exactly",
        },
    )
    assert claim_review.status_code == 201, claim_review.text
    synthesis = client.post(
        f"/v1/investigations/{investigation['id']}/synthesis",
        headers=command_headers(principal_id, workspace_id),
        json={"verified_claim_version_ids": [claim_version_id]},
    ).json()
    synthesis_version_id = synthesis["current_version"]["id"]
    review = client.post(
        f"/v1/investigations/{investigation['id']}/synthesis/versions/{synthesis_version_id}/review",
        headers=command_headers(principal_id, workspace_id),
        json={
            "synthesis_version_id": synthesis_version_id,
            "expected_row_version": synthesis["row_version"],
            "decision": "verify",
            "reason": "Grounded in exact verified claim",
            "policy_version": "synthesis-review-v1",
        },
    )
    assert review.status_code == 201, review.text
    brief = client.post(
        f"/v1/investigations/{investigation['id']}/decision-brief",
        headers=command_headers(principal_id, workspace_id),
        json={
            "synthesis_version_id": synthesis_version_id,
            "template_version": "decision-brief-v1",
        },
    ).json()
    document = brief["current_version"]["block_document"]
    spoofed_actor = deepcopy(document)
    judgment = next(block for block in spoofed_actor["blocks"] if block["type"] == "pm_judgment")
    judgment["actor_id"] = str(uuid4())
    rejected = client.patch(
        f"/v1/decision-briefs/{brief['id']}",
        headers=command_headers(principal_id, workspace_id),
        json={
            "block_document": spoofed_actor,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": _brief_document_digest(spoofed_actor),
        },
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "FORBIDDEN"

    rewritten_synthesis = deepcopy(document)
    synthesis_block = next(
        block for block in rewritten_synthesis["blocks"] if block["type"] == "synthesis"
    )
    synthesis_block["body"] = "Human rewrite that would retain false generator provenance."
    rejected = client.patch(
        f"/v1/decision-briefs/{brief['id']}",
        headers=command_headers(principal_id, workspace_id),
        json={
            "block_document": rewritten_synthesis,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": _brief_document_digest(rewritten_synthesis),
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "LINEAGE_INTEGRITY_ERROR"

    cross_mixed_fact = deepcopy(document)
    fact = next(block for block in cross_mixed_fact["blocks"] if block["type"] == "fact")
    assert len(fact["evidence_ids"]) >= 2 and len(fact["content_version_ids"]) >= 2
    selected_evidence_id = fact["evidence_ids"][0]
    with get_session_factory()() as db:
        selected_evidence = db.get(Evidence, selected_evidence_id)
        assert selected_evidence is not None
        mismatched_content_id = next(
            value
            for value in fact["content_version_ids"]
            if value != selected_evidence.content_version_id
        )
    fact["evidence_ids"] = [selected_evidence_id]
    fact["content_version_ids"] = [mismatched_content_id]
    rejected = client.patch(
        f"/v1/decision-briefs/{brief['id']}",
        headers=command_headers(principal_id, workspace_id),
        json={
            "block_document": cross_mixed_fact,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": _brief_document_digest(cross_mixed_fact),
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "LINEAGE_INTEGRITY_ERROR"

    pending_recommendation = deepcopy(document)
    for block in pending_recommendation["blocks"]:
        if block["type"] == "pm_judgment":
            block["body"] = "Prioritize a permission preview in the next planning cycle."
        if block["type"] == "recommendation":
            block["recommendation_status"] = "accepted"
    pending_response = client.patch(
        f"/v1/decision-briefs/{brief['id']}",
        headers=command_headers(principal_id, workspace_id),
        json={
            "block_document": pending_recommendation,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": _brief_document_digest(pending_recommendation),
        },
    )
    assert pending_response.status_code == 200, pending_response.text
    pending_brief = pending_response.json()
    with get_session_factory()() as db:
        pending_version = db.get(
            __import__(
                "services.api.app.db.models", fromlist=["DecisionBriefVersion"]
            ).DecisionBriefVersion,
            pending_brief["current_version"]["id"],
        )
        pending_checklist = readiness_checklist_digest(pending_version, "decision-readiness-v1")
    pending_ready = client.post(
        f"/v1/decision-briefs/{brief['id']}/mark-decision-ready",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": pending_brief["current_version"]["id"],
            "expected_row_version": pending_brief["row_version"],
            "decision": "mark_decision_ready",
            "reason": "Recommendation status alone is insufficient",
            "policy_version": "decision-readiness-v1",
            "checklist_digest": pending_checklist,
        },
    )
    assert pending_ready.status_code == 422
    recommendation_id = next(
        block["id"]
        for block in pending_recommendation["blocks"]
        if block["type"] == "recommendation"
    )
    pending_export = client.post(
        f"/v1/decision-briefs/{brief['id']}/exports/preview",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": pending_brief["current_version"]["id"],
            "export_type": "prd_research_input_markdown",
            "selection_manifest": {
                "block_ids": [recommendation_id],
                "include_citations": False,
            },
        },
    )
    assert pending_export.status_code == 409
    assert pending_export.json()["error"]["code"] == "APPROVAL_REQUIRED"

    brief = pending_brief
    document = pending_recommendation
    for block in document["blocks"]:
        if block["type"] == "pm_judgment":
            block["body"] = "Prioritize a permission preview in the next planning cycle."
        if block["type"] == "recommendation":
            block["body"] = "Prototype the permission preview."
            block["recommendation_status"] = "accepted"
    supports_only = client.patch(
        f"/v1/decision-briefs/{brief['id']}",
        headers=command_headers(principal_id, workspace_id),
        json={
            "block_document": document,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": _brief_document_digest(document),
        },
    ).json()
    with get_session_factory()() as db:
        supports_only_version = db.get(
            __import__(
                "services.api.app.db.models", fromlist=["DecisionBriefVersion"]
            ).DecisionBriefVersion,
            supports_only["current_version"]["id"],
        )
        supports_only_checklist = readiness_checklist_digest(
            supports_only_version, "decision-readiness-v1"
        )
    supports_only_ready = client.post(
        f"/v1/decision-briefs/{brief['id']}/mark-decision-ready",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": supports_only["current_version"]["id"],
            "expected_row_version": supports_only["row_version"],
            "decision": "mark_decision_ready",
            "reason": "Supporting evidence alone is not complete.",
            "policy_version": "decision-readiness-v1",
            "checklist_digest": supports_only_checklist,
        },
    )
    assert supports_only_ready.status_code == 422
    assert "counter-evidence" in supports_only_ready.json()["error"]["message"]

    brief = supports_only
    document = deepcopy(brief["current_version"]["block_document"])
    document["no_counter_evidence_search"] = {
        "queries": ["permission preview onboarding friction counter evidence"],
        "source_connection_ids": [bootstrap["source"]["id"]],
        "window_start": (start - timedelta(days=1)).isoformat(),
        "window_end": end.isoformat(),
        "exclusion_criteria": ["Excluded records outside the confirmed import scope."],
        "limitations": ["The imported interviews may omit satisfied users."],
    }
    brief_response = client.patch(
        f"/v1/decision-briefs/{brief['id']}",
        headers=command_headers(principal_id, workspace_id),
        json={
            "block_document": document,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": _brief_document_digest(document),
        },
    )
    assert brief_response.status_code == 200, brief_response.text
    brief = brief_response.json()
    with get_session_factory()() as db:
        wrong_window_version = db.get(
            __import__(
                "services.api.app.db.models", fromlist=["DecisionBriefVersion"]
            ).DecisionBriefVersion,
            brief["current_version"]["id"],
        )
        wrong_window_checklist = readiness_checklist_digest(
            wrong_window_version, "decision-readiness-v1"
        )
    wrong_window_ready = client.post(
        f"/v1/decision-briefs/{brief['id']}/mark-decision-ready",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "expected_row_version": brief["row_version"],
            "decision": "mark_decision_ready",
            "reason": "The search window is not the confirmed scope.",
            "policy_version": "decision-readiness-v1",
            "checklist_digest": wrong_window_checklist,
        },
    )
    assert wrong_window_ready.status_code == 422
    assert wrong_window_ready.json()["error"]["code"] == "LINEAGE_INTEGRITY_ERROR"
    assert "window" in wrong_window_ready.json()["error"]["message"]

    document = deepcopy(brief["current_version"]["block_document"])
    document["no_counter_evidence_search"]["window_start"] = start.isoformat()
    brief_response = client.patch(
        f"/v1/decision-briefs/{brief['id']}",
        headers=command_headers(principal_id, workspace_id),
        json={
            "block_document": document,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": _brief_document_digest(document),
        },
    )
    assert brief_response.status_code == 200, brief_response.text
    brief = brief_response.json()
    with get_session_factory()() as db:
        version = db.get(ClaimVersion, claim_version_id)
        assert version is not None
        brief_version = db.get(
            __import__(
                "services.api.app.db.models", fromlist=["DecisionBriefVersion"]
            ).DecisionBriefVersion,
            brief["current_version"]["id"],
        )
        checklist = readiness_checklist_digest(brief_version, "decision-readiness-v1")
    ready = client.post(
        f"/v1/decision-briefs/{brief['id']}/mark-decision-ready",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "expected_row_version": brief["row_version"],
            "decision": "mark_decision_ready",
            "reason": "Checklist complete",
            "policy_version": "decision-readiness-v1",
            "checklist_digest": checklist,
        },
    )
    assert ready.status_code == 201, ready.text
    selected = [
        block["id"]
        for block in document["blocks"]
        if block["type"] in {"fact", "pm_judgment", "recommendation"}
    ]
    preview = client.post(
        f"/v1/decision-briefs/{brief['id']}/exports/preview",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "export_type": "prd_research_input_markdown",
            "selection_manifest": {"block_ids": selected, "include_citations": True},
        },
    )
    assert preview.status_code == 200, preview.text
    assert "Synthetic" not in preview.json()["rendered_content"]
    assert "> Data authenticity: Imported" in preview.json()["rendered_content"]
    exported = client.post(
        f"/v1/decision-briefs/{brief['id']}/exports",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "export_type": "prd_research_input_markdown",
            "destination": "local_download",
            "selection_manifest": {"block_ids": selected, "include_citations": True},
            "reference_digest": preview.json()["reference_digest"],
        },
    )
    assert exported.status_code == 201, exported.text
    assert exported.json()["reference_digest"] == preview.json()["reference_digest"]
    with get_session_factory()() as db:
        export_row = db.get(BriefExport, exported.json()["id"])
        assert export_row is not None
        stored = get_object_store().get(export_row.rendered_snapshot_uri.removeprefix("object://"))
        assert stored.body == preview.json()["rendered_content"].encode()
        assert export_row.output_digest == digest(stored.body)
        assert exported.json()["output_digest"] == export_row.output_digest
    rejected_evidence = client.post(
        f"/v1/evidence/{evidence_ids[0]}/review",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision": "rejected",
            "reason": "A later source check invalidated the quoted support.",
            "policy_version": "evidence-review-v1",
        },
    )
    assert rejected_evidence.status_code == 201, rejected_evidence.text
    claim_after_reject = client.get(
        f"/v1/claims/{claim_id}", headers=query_headers(principal_id, workspace_id)
    ).json()
    assert claim_after_reject["current_version"]["status"] == "needs_review"
    synthesis_after_reject = client.get(
        f"/v1/investigations/{investigation['id']}/synthesis",
        headers=query_headers(principal_id, workspace_id),
    ).json()
    assert synthesis_after_reject["current_version"]["status"] == "needs_review"
    freshness = client.get(
        f"/v1/decision-briefs/{brief['id']}/versions/{brief['current_version']['id']}/freshness",
        headers=query_headers(principal_id, workspace_id),
    )
    assert freshness.status_code == 200, freshness.text
    assert freshness.json()["status"] == "evidence_stale"
    stale_preview = client.post(
        f"/v1/decision-briefs/{brief['id']}/exports/preview",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "export_type": "prd_research_input_markdown",
            "selection_manifest": {"block_ids": selected, "include_citations": True},
        },
    )
    assert stale_preview.status_code == 409
    stale_export = client.post(
        f"/v1/decision-briefs/{brief['id']}/exports",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision_brief_version_id": brief["current_version"]["id"],
            "export_type": "prd_research_input_markdown",
            "destination": "local_download",
            "selection_manifest": {"block_ids": selected, "include_citations": True},
            "reference_digest": preview.json()["reference_digest"],
        },
    )
    assert stale_export.status_code == 409
    valid_again = client.post(
        f"/v1/evidence/{evidence_ids[0]}/review",
        headers=command_headers(principal_id, workspace_id),
        json={
            "decision": "valid",
            "reason": "A new check is valid but cannot revive an old ClaimReview snapshot.",
            "policy_version": "evidence-review-v1",
        },
    )
    assert valid_again.status_code == 201, valid_again.text
    still_needs_review = client.get(
        f"/v1/claims/{claim_id}", headers=query_headers(principal_id, workspace_id)
    ).json()
    assert still_needs_review["current_version"]["status"] == "needs_review"
    events = client.get(
        f"/v1/research-runs/{run['id']}/events",
        headers=query_headers(principal_id, workspace_id),
    )
    assert events.status_code == 200
    assert "claim.version_proposed" in events.text
    assert events.text.count("investigation.started_from_signal") == 2
