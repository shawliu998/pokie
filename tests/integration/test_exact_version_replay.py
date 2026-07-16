from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.db.models import (
    BriefExport,
    Claim,
    ClaimEvidence,
    ClaimReview,
    ClaimVersion,
    DecisionBrief,
    DecisionBriefFreshnessRecord,
    DecisionBriefReadinessReview,
    DecisionBriefVersion,
    Evidence,
    EvidenceReview,
    Investigation,
    InvestigationSynthesis,
    InvestigationSynthesisVersion,
    SynthesisReview,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.common import digest
from tests.conftest import command_headers, query_headers
from tests.security.helpers import create_workspace


def _seed_replay_chain(workspace_id: str, actor_id: str) -> dict[str, str | int]:
    with get_session_factory()() as db:
        investigation = Investigation(
            workspace_id=workspace_id,
            project_id=str(uuid4()),
            signal_id=str(uuid4()),
            status="complete",
            owner_id=actor_id,
            data_authenticity="human_authored",
        )
        db.add(investigation)
        db.flush()
        evidence = Evidence(
            workspace_id=workspace_id,
            investigation_id=investigation.id,
            research_run_id=str(uuid4()),
            content_version_id=str(uuid4()),
            quote_start=0,
            quote_end=28,
            quote_text="Exact replay remains frozen.",
            quote_text_digest=digest("Exact replay remains frozen."),
            stance="supports",
            relevance=1.0,
            reliability=1.0,
            independence=1.0,
            recency=1.0,
            specificity=1.0,
            extraction_method="test-fixture-v1",
            data_authenticity="human_authored",
        )
        claim = Claim(
            workspace_id=workspace_id,
            investigation_id=investigation.id,
            research_run_id=evidence.research_run_id,
            aggregate_status="verified",
            owner_id=actor_id,
            data_authenticity="human_authored",
        )
        db.add_all([evidence, claim])
        db.flush()
        evidence_review = EvidenceReview(
            workspace_id=workspace_id,
            evidence_id=evidence.id,
            decision="valid",
            reviewer_id=actor_id,
            reason="Frozen exact evidence is valid.",
            policy_version="evidence-review-v1",
            data_authenticity="human_authored",
        )
        claim_version = ClaimVersion(
            workspace_id=workspace_id,
            claim_id=claim.id,
            version_number=1,
            claim_type="observation",
            text="Exact replay preserves reviewed lineage.",
            confidence_inputs_json={"supporting_evidence_count": 1},
            confidence_score=1.0,
            confidence_level="high",
            confidence_policy_version="claim-confidence-v2",
            confidence_input_digest=digest({"supporting_evidence_count": 1}),
            calibration_status="uncalibrated",
            limitations=["Fixture evidence covers one exact snapshot."],
            generation_method="deterministic",
            generator_version="test-claim-v1",
            suggestion_origin="deterministic_rule",
            created_by=actor_id,
            data_authenticity="human_authored",
        )
        db.add_all([evidence_review, claim_version])
        db.flush()
        claim.current_version_id = claim_version.id
        link = ClaimEvidence(
            workspace_id=workspace_id,
            claim_version_id=claim_version.id,
            evidence_id=evidence.id,
            stance="supports",
            weight=1.0,
            rationale="Exact frozen support.",
            linked_by=actor_id,
            data_authenticity="human_authored",
        )
        db.add(link)
        db.flush()
        review_snapshot = {
            "claim_version_id": claim_version.id,
            "claim_evidence_ids": [link.id],
            "evidence_review_ids": [evidence_review.id],
        }
        claim_review = ClaimReview(
            workspace_id=workspace_id,
            claim_version_id=claim_version.id,
            decision="verify",
            claim_evidence_snapshot_json=[link.id],
            evidence_review_snapshot_json=[evidence_review.id],
            snapshot_digest=digest(review_snapshot),
            reviewer_id=actor_id,
            reason="Claim lineage is exact.",
            policy_version="claim-review-v1",
            data_authenticity="human_authored",
        )
        synthesis = InvestigationSynthesis(
            workspace_id=workspace_id,
            investigation_id=investigation.id,
            data_authenticity="human_authored",
        )
        db.add_all([claim_review, synthesis])
        db.flush()
        synthesis_version = InvestigationSynthesisVersion(
            workspace_id=workspace_id,
            synthesis_id=synthesis.id,
            version_number=1,
            verified_claim_version_snapshot_json=[claim_version.id],
            claim_review_snapshot_json=[claim_review.id],
            generation_method="deterministic",
            generator_version="test-synthesis-v1",
            model_prompt_refs_json=[],
            executive_summary="Exact replay preserves reviewed lineage.",
            business_implications=["Keep immutable version replay available."],
            limitations=["Fixture evidence covers one exact snapshot."],
            provenance_digest=digest(
                {
                    "claim_version_ids": [claim_version.id],
                    "claim_review_ids": [claim_review.id],
                }
            ),
            created_by=actor_id,
            data_authenticity="human_authored",
        )
        db.add(synthesis_version)
        db.flush()
        synthesis.current_version_id = synthesis_version.id
        investigation.current_synthesis_id = synthesis.id
        unverified_synthesis_version = InvestigationSynthesisVersion(
            workspace_id=workspace_id,
            synthesis_id=synthesis.id,
            version_number=2,
            verified_claim_version_snapshot_json=[claim_version.id],
            claim_review_snapshot_json=[claim_review.id],
            generation_method="deterministic",
            generator_version="test-synthesis-v2",
            model_prompt_refs_json=[],
            executive_summary="This exact synthesis has not been approved.",
            business_implications=["It cannot ground a Brief revision yet."],
            limitations=["Approval is deliberately absent."],
            provenance_digest=digest(
                {
                    "claim_version_ids": [claim_version.id],
                    "claim_review_ids": [claim_review.id],
                    "revision": 2,
                }
            ),
            created_by=actor_id,
            data_authenticity="human_authored",
        )
        db.add(unverified_synthesis_version)
        synthesis_review = SynthesisReview(
            workspace_id=workspace_id,
            synthesis_version_id=synthesis_version.id,
            decision="verify",
            reviewer_id=actor_id,
            reason="Synthesis grounding is verified.",
            policy_version="synthesis-review-v1",
            data_authenticity="human_authored",
        )
        db.add(synthesis_review)
        db.flush()
        snapshot = {
            "synthesis_version_id": synthesis_version.id,
            "synthesis_review_id": synthesis_review.id,
            "claim_version_ids": [claim_version.id],
            "claim_review_ids": [claim_review.id],
            "claim_evidence_ids": [link.id],
            "evidence_review_ids": [evidence_review.id],
            "evidence_ids": [evidence.id],
            "content_version_ids": [evidence.content_version_id],
        }
        document = {
            "schema_version": "decision-brief-blocks-v1",
            "blocks": [
                {
                    "id": "fact-1",
                    "type": "fact",
                    "body": claim_version.text,
                    "claim_version_ids": [claim_version.id],
                    "evidence_ids": [evidence.id],
                    "content_version_ids": [evidence.content_version_id],
                },
                {
                    "id": "synthesis-1",
                    "type": "synthesis",
                    "body": synthesis_version.executive_summary,
                    "synthesis_version_id": synthesis_version.id,
                    "generation_method": synthesis_version.generation_method,
                    "generator_version": synthesis_version.generator_version,
                    "model_prompt_refs": [],
                },
                {
                    "id": "judgment-1",
                    "type": "pm_judgment",
                    "body": "Preserve exact replay for auditability.",
                    "actor_id": actor_id,
                },
                {
                    "id": "recommendation-1",
                    "type": "recommendation",
                    "body": "Ship exact immutable replay endpoints.",
                    "recommendation_status": "accepted",
                },
            ],
        }
        brief = DecisionBrief(
            workspace_id=workspace_id,
            investigation_id=investigation.id,
            status="decision_ready",
            owner_id=actor_id,
            data_authenticity="human_authored",
        )
        db.add(brief)
        db.flush()
        base_version = DecisionBriefVersion(
            workspace_id=workspace_id,
            decision_brief_id=brief.id,
            version_number=1,
            synthesis_version_id=synthesis_version.id,
            synthesis_review_id=synthesis_review.id,
            block_document=document,
            reference_snapshot_json=snapshot,
            template_version="decision-brief-v1",
            human_edit_digest=digest(document),
            created_by=actor_id,
            data_authenticity="human_authored",
        )
        db.add(base_version)
        db.flush()
        brief.current_version_id = base_version.id
        investigation.decision_brief_id = brief.id
        readiness = DecisionBriefReadinessReview(
            workspace_id=workspace_id,
            decision_brief_version_id=base_version.id,
            decision="mark_decision_ready",
            reviewer_id=actor_id,
            reason="Exact fixture is ready.",
            policy_version="decision-readiness-v1",
            checklist_digest=digest({"version_id": base_version.id}),
            data_authenticity="human_authored",
        )
        freshness = DecisionBriefFreshnessRecord(
            workspace_id=workspace_id,
            decision_brief_version_id=base_version.id,
            status="current",
            affected_reference_snapshot_json=[],
            reason="Exact references are current.",
            policy_version="brief-freshness-v1",
            data_authenticity="human_authored",
        )
        export = BriefExport(
            workspace_id=workspace_id,
            decision_brief_version_id=base_version.id,
            export_type="prd_research_input_markdown",
            destination="local_download",
            selection_manifest_json={
                "block_ids": ["fact-1", "judgment-1", "recommendation-1"],
                "include_citations": True,
            },
            reference_digest=digest({"version_id": base_version.id, "kind": "reference"}),
            policy_version="export-policy-v1",
            template_version="prd-research-input-v1",
            rendered_snapshot_uri=f"object://brief-exports/{uuid4()}.md",
            output_digest=digest(b"# Exact immutable replay\n"),
            created_by=actor_id,
            data_authenticity="human_authored",
        )
        db.add_all([readiness, freshness, export])
        db.commit()
        return {
            "investigation_id": investigation.id,
            "evidence_id": evidence.id,
            "evidence_review_id": evidence_review.id,
            "claim_id": claim.id,
            "claim_version_id": claim_version.id,
            "synthesis_version_id": synthesis_version.id,
            "unverified_synthesis_version_id": unverified_synthesis_version.id,
            "brief_id": brief.id,
            "base_brief_version_id": base_version.id,
            "brief_row_version": brief.row_version,
            "export_id": export.id,
        }


def test_exact_version_replay_and_explicit_brief_revision(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Exact replay workspace")
    workspace_id = str(workspace["id"])
    chain = _seed_replay_chain(workspace_id, principal_id)
    headers = query_headers(principal_id, workspace_id)

    claim = client.get(
        f"/v1/claims/{chain['claim_id']}/versions/{chain['claim_version_id']}",
        headers=headers,
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["id"] == chain["claim_version_id"]
    assert claim.json()["status"] == "verified"

    synthesis = client.get(
        f"/v1/investigations/{chain['investigation_id']}/synthesis/versions/"
        f"{chain['synthesis_version_id']}",
        headers=headers,
    )
    assert synthesis.status_code == 200, synthesis.text
    assert synthesis.json()["id"] == chain["synthesis_version_id"]
    assert synthesis.json()["status"] == "verified"

    base = client.get(
        f"/v1/decision-briefs/{chain['brief_id']}/versions/{chain['base_brief_version_id']}",
        headers=headers,
    )
    assert base.status_code == 200, base.text
    assert base.json()["readiness"] == "decision_ready"
    assert base.json()["freshness"] == "current"

    export = client.get(f"/v1/brief-exports/{chain['export_id']}", headers=headers)
    assert export.status_code == 200, export.text
    assert export.json()["decision_brief_version_id"] == chain["base_brief_version_id"]

    with get_session_factory()() as db:
        claim_row = db.get(Claim, str(chain["claim_id"]))
        old_claim_version = db.get(ClaimVersion, str(chain["claim_version_id"]))
        synthesis_row = db.get(InvestigationSynthesisVersion, str(chain["synthesis_version_id"]))
        synthesis_owner = (
            db.get(InvestigationSynthesis, synthesis_row.synthesis_id)
            if synthesis_row is not None
            else None
        )
        assert claim_row is not None and old_claim_version is not None
        assert synthesis_row is not None and synthesis_owner is not None
        current_claim_version = ClaimVersion(
            workspace_id=workspace_id,
            claim_id=claim_row.id,
            version_number=2,
            claim_type=old_claim_version.claim_type,
            text="Current pointer moved after the terminal export.",
            confidence_inputs_json={"supporting_evidence_count": 1},
            confidence_score=1.0,
            confidence_level="high",
            confidence_policy_version="claim-confidence-v2",
            confidence_input_digest=digest({"supporting_evidence_count": 1, "version": 2}),
            calibration_status="uncalibrated",
            limitations=["The historic export remains bound to ClaimVersion 1."],
            generation_method="deterministic",
            generator_version="test-claim-v2",
            suggestion_origin="deterministic_rule",
            created_by=principal_id,
            data_authenticity="human_authored",
        )
        db.add(current_claim_version)
        db.flush()
        current_link = ClaimEvidence(
            workspace_id=workspace_id,
            claim_version_id=current_claim_version.id,
            evidence_id=str(chain["evidence_id"]),
            stance="supports",
            weight=1.0,
            rationale="The new exact ClaimVersion keeps explicit support.",
            linked_by=principal_id,
            data_authenticity="human_authored",
        )
        db.add(current_link)
        db.flush()
        current_claim_review = ClaimReview(
            workspace_id=workspace_id,
            claim_version_id=current_claim_version.id,
            decision="verify",
            claim_evidence_snapshot_json=[current_link.id],
            evidence_review_snapshot_json=[str(chain["evidence_review_id"])],
            snapshot_digest=digest(
                {
                    "claim_version_id": current_claim_version.id,
                    "claim_evidence_ids": [current_link.id],
                    "evidence_review_ids": [str(chain["evidence_review_id"])],
                }
            ),
            reviewer_id=principal_id,
            reason="The current ClaimVersion has an exact verified snapshot.",
            policy_version="claim-review-v1",
            data_authenticity="human_authored",
        )
        db.add(current_claim_review)
        db.flush()
        claim_row.current_version_id = current_claim_version.id
        claim_row.row_version += 1
        current_synthesis = InvestigationSynthesisVersion(
            workspace_id=workspace_id,
            synthesis_id=synthesis_owner.id,
            version_number=3,
            verified_claim_version_snapshot_json=[current_claim_version.id],
            claim_review_snapshot_json=[current_claim_review.id],
            generation_method="deterministic",
            generator_version="test-synthesis-v3",
            model_prompt_refs_json=[],
            executive_summary="The post-export current synthesis is separately versioned.",
            business_implications=["Historic replay remains available."],
            limitations=["This is a deterministic test grounding."],
            provenance_digest=digest(
                {
                    "claim_version_ids": [current_claim_version.id],
                    "claim_review_ids": [current_claim_review.id],
                }
            ),
            created_by=principal_id,
            data_authenticity="human_authored",
        )
        db.add(current_synthesis)
        db.flush()
        current_synthesis_review = SynthesisReview(
            workspace_id=workspace_id,
            synthesis_version_id=current_synthesis.id,
            decision="verify",
            reviewer_id=principal_id,
            reason="The current synthesis is verified independently.",
            policy_version="synthesis-review-v1",
            data_authenticity="human_authored",
        )
        db.add(current_synthesis_review)
        synthesis_owner.current_version_id = current_synthesis.id
        synthesis_owner.row_version += 1
        db.commit()
        current_synthesis_id = current_synthesis.id

    historic_claim = client.get(
        f"/v1/claims/{chain['claim_id']}/versions/{chain['claim_version_id']}",
        headers=headers,
    )
    assert historic_claim.status_code == 200, historic_claim.text
    assert historic_claim.json()["id"] == chain["claim_version_id"]
    assert historic_claim.json()["status"] == "superseded"
    assert {key: value for key, value in historic_claim.json().items() if key != "status"} == {
        key: value for key, value in claim.json().items() if key != "status"
    }
    historic_synthesis = client.get(
        f"/v1/investigations/{chain['investigation_id']}/synthesis/versions/"
        f"{chain['synthesis_version_id']}",
        headers=headers,
    )
    assert historic_synthesis.status_code == 200, historic_synthesis.text
    assert historic_synthesis.json()["id"] == chain["synthesis_version_id"]
    assert historic_synthesis.json()["status"] == "needs_review"
    assert {key: value for key, value in historic_synthesis.json().items() if key != "status"} == {
        key: value for key, value in synthesis.json().items() if key != "status"
    }
    assert (
        client.get(f"/v1/brief-exports/{chain['export_id']}", headers=headers).json()
        == export.json()
    )

    unverified = client.post(
        f"/v1/decision-briefs/{chain['brief_id']}/revisions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "base_decision_brief_version_id": chain["base_brief_version_id"],
            "synthesis_version_id": chain["unverified_synthesis_version_id"],
            "expected_row_version": chain["brief_row_version"],
        },
    )
    assert unverified.status_code == 409
    assert unverified.json()["error"]["code"] == "APPROVAL_REQUIRED"

    revision = client.post(
        f"/v1/decision-briefs/{chain['brief_id']}/revisions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "base_decision_brief_version_id": chain["base_brief_version_id"],
            "synthesis_version_id": current_synthesis_id,
            "expected_row_version": chain["brief_row_version"],
        },
    )
    assert revision.status_code == 201, revision.text
    revised = revision.json()
    revised_version_id = revised["current_version"]["id"]
    assert revised["status"] == "draft"
    assert revised["row_version"] == int(chain["brief_row_version"]) + 1
    assert revised_version_id != chain["base_brief_version_id"]
    assert revised["current_version"]["version_number"] == 2
    assert revised["current_version"]["synthesis_version_id"] == current_synthesis_id
    assert revised["current_version"]["created_by"] == principal_id
    assert revised["current_version"]["readiness"] == "draft"
    assert (
        revised["current_version"]["reference_snapshot_json"]["synthesis_version_id"]
        == current_synthesis_id
    )
    judgment = next(
        block
        for block in revised["current_version"]["block_document"]["blocks"]
        if block["type"] == "pm_judgment"
    )
    assert judgment["actor_id"] == principal_id
    assert judgment["body"] == "Preserve exact replay for auditability."
    recommendation = next(
        block
        for block in revised["current_version"]["block_document"]["blocks"]
        if block["type"] == "recommendation"
    )
    assert recommendation == base.json()["block_document"]["blocks"][-1]

    replayed_base = client.get(
        f"/v1/decision-briefs/{chain['brief_id']}/versions/{chain['base_brief_version_id']}",
        headers=headers,
    )
    assert replayed_base.status_code == 200, replayed_base.text
    assert replayed_base.json() == base.json()
    replayed_revision = client.get(
        f"/v1/decision-briefs/{chain['brief_id']}/versions/{revised_version_id}",
        headers=headers,
    )
    assert replayed_revision.status_code == 200, replayed_revision.text
    assert replayed_revision.json() == revised["current_version"]
    replayed_export = client.get(f"/v1/brief-exports/{chain['export_id']}", headers=headers)
    assert replayed_export.json() == export.json()


def test_claim_revision_appends_brief_staleness(client: TestClient, principal_id: str) -> None:
    workspace = create_workspace(client, principal_id, "Claim staleness workspace")
    workspace_id = str(workspace["id"])
    chain = _seed_replay_chain(workspace_id, principal_id)
    headers = command_headers(principal_id, workspace_id)

    with get_session_factory()() as db:
        claim = db.get(Claim, str(chain["claim_id"]))
        assert claim is not None
        expected_row_version = claim.row_version

    revised = client.post(
        f"/v1/claims/{chain['claim_id']}/versions",
        headers=headers,
        json={
            "claim_type": "observation",
            "text": "A newer human interpretation supersedes the frozen ClaimVersion.",
            "limitations": ["The revision requires a fresh ClaimReview."],
            "evidence_links": [
                {
                    "evidence_id": chain["evidence_id"],
                    "stance": "supports",
                    "weight": 1.0,
                    "rationale": "The same exact evidence supports the revised wording.",
                }
            ],
            "expected_claim_row_version": expected_row_version,
        },
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["generation_method"] == "human"
    assert revised.json()["status"] == "needs_review"

    freshness = client.get(
        f"/v1/decision-briefs/{chain['brief_id']}/versions/"
        f"{chain['base_brief_version_id']}/freshness",
        headers=query_headers(principal_id, workspace_id),
    )
    assert freshness.status_code == 200, freshness.text
    assert freshness.json()["status"] == "evidence_stale"
    assert freshness.json()["affected_reference_snapshot_json"] == [chain["claim_version_id"]]

    stale = client.post(
        f"/v1/decision-briefs/{chain['brief_id']}/revisions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "base_decision_brief_version_id": chain["base_brief_version_id"],
            "synthesis_version_id": chain["synthesis_version_id"],
            "expected_row_version": chain["brief_row_version"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "APPROVAL_REQUIRED"

    other_workspace = create_workspace(client, principal_id, "Other replay workspace")
    other_headers = query_headers(principal_id, str(other_workspace["id"]))
    scoped_paths = [
        f"/v1/claims/{chain['claim_id']}/versions/{chain['claim_version_id']}",
        f"/v1/investigations/{chain['investigation_id']}/synthesis/versions/"
        f"{chain['synthesis_version_id']}",
        f"/v1/decision-briefs/{chain['brief_id']}/versions/{chain['base_brief_version_id']}",
        f"/v1/brief-exports/{chain['export_id']}",
    ]
    for path in scoped_paths:
        response = client.get(path, headers=other_headers)
        assert response.status_code == 404, (path, response.text)
