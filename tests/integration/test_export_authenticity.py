from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from services.api.app.db.models import DecisionBriefVersion
from services.api.app.modules.common import digest
from services.api.app.modules.decisions.service import _render_export_markdown


@pytest.mark.parametrize(
    ("authenticity", "label"),
    [("seed", "Seed"), ("imported", "Imported"), ("collected", "Collected")],
)
def test_canonical_export_markdown_and_digest_include_data_authenticity(
    authenticity: str, label: str
) -> None:
    version = DecisionBriefVersion(
        id=str(uuid4()),
        workspace_id=str(uuid4()),
        decision_brief_id=str(uuid4()),
        version_number=1,
        synthesis_version_id=str(uuid4()),
        synthesis_review_id=str(uuid4()),
        block_document={
            "blocks": [
                {
                    "id": "recommendation-1",
                    "type": "recommendation",
                    "body": "Prioritize the permission preview.",
                    "recommendation_status": "accepted",
                }
            ]
        },
        reference_snapshot_json={"content_version_ids": []},
        template_version="decision-brief-v1",
        human_edit_digest="sha256:human-edit",
        created_by=str(uuid4()),
        data_authenticity=authenticity,
    )
    selection = {"block_ids": ["recommendation-1"], "include_citations": False}
    readiness_context = {
        "decision_question": "Should permission preview be prioritized?",
        "limitations": ["One bounded research scope."],
        "counter_evidence_ids": [str(uuid4())],
        "no_counter_evidence_search": None,
        "readiness_state": "decision_ready/current",
    }
    export_timestamp = datetime(2026, 7, 16, 9, 30, tzinfo=UTC)
    source_reference_ids = [str(uuid4())]
    evidence_references = [{"evidence_id": str(uuid4()), "content_version_id": str(uuid4())}]
    rendered, reference_digest = _render_export_markdown(
        version=version,
        export_type="prd_research_input_markdown",
        selection_manifest=selection,
        readiness_context=readiness_context,
        export_timestamp=export_timestamp,
        source_reference_ids=source_reference_ids,
        evidence_content_version_references=evidence_references,
    )
    assert rendered.startswith(f"# PRD Research Input\n\n> Data authenticity: {label}\n\n")
    assert f"- Decision Brief Version: 1 ({version.id})" in rendered
    assert f"- Data Authenticity: {label}" in rendered
    assert f"- Source References: source:{source_reference_ids[0]}" in rendered
    assert (
        "  - evidence:{evidence_id} -> content-version:{content_version_id}".format(
            **evidence_references[0]
        )
        in rendered
    )
    assert "- Export Timestamp: 2026-07-16T09:30:00Z" in rendered
    assert "- Readiness State: decision_ready/current" in rendered
    assert digest(rendered.encode()).startswith("sha256:")
    assert reference_digest == digest(
        {
            "decision_brief_version_id": version.id,
            "export_type": "prd_research_input_markdown",
            "selection_manifest": selection,
            "selected_blocks": version.block_document["blocks"],
            "reference_snapshot": version.reference_snapshot_json,
            "readiness_context": readiness_context,
            "data_authenticity": authenticity,
            "export_timestamp": "2026-07-16T09:30:00Z",
            "source_reference_ids": source_reference_ids,
            "evidence_content_version_references": evidence_references,
        }
    )
