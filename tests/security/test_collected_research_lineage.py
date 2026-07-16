from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from services.api.app.core.errors import ApiError
from services.api.app.db.models import (
    CollectionRun,
    ResearchRun,
    SignalEvidence,
    SourceConnection,
    Watchlist,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.research.service import ResearchRunResultRepository
from tests.conftest import command_headers, query_headers
from tests.integration.collected_research_fixtures import seed_collected_signal_scope
from tests.integration.test_collected_research_lineage import _create_investigation_and_run


@pytest.mark.parametrize(
    "mutation",
    [
        "unapproved_source",
        "watchlist_membership_removed",
        "missing_independence",
        "nonterminal_run",
    ],
)
def test_collected_investigation_rejects_unapproved_or_unfrozen_lineage(
    client: TestClient, principal_id: str, mutation: str
) -> None:
    fixture = seed_collected_signal_scope(client, principal_id)
    workspace = fixture["workspace"]
    source = fixture["source"]
    signal = client.get(
        f"/v1/signals/{fixture['signal_id']}",
        headers=query_headers(principal_id, str(workspace["id"])),
    ).json()
    triage = client.post(
        f"/v1/signals/{fixture['signal_id']}/triage",
        headers=command_headers(principal_id, str(workspace["id"])),
        json={
            "expected_signal_row_version": signal["row_version"],
            "business_impact": {
                "confirmed_level": "high",
                "reason": "Owner confirmed impact before scope validation.",
                "expected_assessment_version": signal["dimensions"]["business_impact"]["version"],
            },
            "urgency": {
                "confirmed_level": "this_week",
                "reason": "Owner confirmed urgency before scope validation.",
                "expected_assessment_version": signal["dimensions"]["urgency"]["version"],
            },
        },
    )
    assert triage.status_code == 200, triage.text
    with get_session_factory()() as db:
        if mutation == "unapproved_source":
            row = db.get(SourceConnection, str(source["id"]))
            assert row is not None
            row.approved_by = None
        elif mutation == "watchlist_membership_removed":
            row = db.get(Watchlist, str(fixture["watchlist"]["id"]))
            assert row is not None
            row.rules_json = {**row.rules_json, "source_connection_ids": []}
        elif mutation == "missing_independence":
            row = db.get(SignalEvidence, str(fixture["signal_evidence_id"]))
            assert row is not None
            row.independence_group_id = None
        else:
            row = db.get(CollectionRun, str(fixture["collection_run_id"]))
            assert row is not None
            row.state = "running"
            row.finished_at = None
        db.commit()

    now = fixture["now"]
    response = client.post(
        "/v1/investigations",
        headers=command_headers(principal_id, str(workspace["id"])),
        json={
            "signal_id": fixture["signal_id"],
            "decision_question": "Should collected friction be prioritized?",
            "source_scope": {
                "source_connection_ids": [source["id"]],
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
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] in {
        "SOURCE_SCOPE_BLOCKED",
        "LINEAGE_INTEGRITY_ERROR",
    }


def test_v2_result_persistence_rejects_collection_snapshot_tampering(
    client: TestClient, principal_id: str
) -> None:
    fixture = seed_collected_signal_scope(client, principal_id)
    workspace_id = str(fixture["workspace"]["id"])
    _investigation, run = _create_investigation_and_run(client, principal_id, fixture)
    with get_session_factory()() as db:
        claimed = ResearchRunResultRepository.claim_queued(
            db,
            workspace_id=workspace_id,
            run_id=str(run["id"]),
            worker_id="worker-tamper-check",
            worker_attempt_id="tamper-attempt",
        )
        assert claimed is not None
    with get_session_factory()() as db:
        ResearchRunResultRepository.mark_started(
            db,
            workspace_id=workspace_id,
            run_id=str(run["id"]),
            worker_attempt_id="tamper-attempt",
        )
    with get_session_factory()() as db:
        collection = db.get(CollectionRun, str(fixture["collection_run_id"]))
        assert collection is not None
        collection.counters_json = {**collection.counters_json, "created": 99}
        db.commit()
    with get_session_factory()() as db:
        with pytest.raises(ApiError) as exc_info:
            ResearchRunResultRepository.persist_deterministic_result(
                db,
                workspace_id=workspace_id,
                run_id=str(run["id"]),
                actor_id=principal_id,
                request_id="tamper-result",
                worker_attempt_id="tamper-attempt",
                evidence_proposals=[
                    {
                        "content_version_id": fixture["content_version_id"],
                        "quote_start": 0,
                        "quote_end": 20,
                        "stance": "supports",
                        "relevance": 0.9,
                        "reliability": 0.8,
                        "independence": 0.8,
                        "recency": 1.0,
                        "specificity": 0.8,
                    }
                ],
                claim_proposal={
                    "claim_type": "product_risk",
                    "text": "Tampered lineage must fail.",
                    "limitations": [],
                },
            )
        assert exc_info.value.code == "LINEAGE_INTEGRITY_ERROR"
        stored_run = db.get(ResearchRun, str(run["id"]))
        assert stored_run is not None and stored_run.state == "running"
