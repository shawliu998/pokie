from __future__ import annotations

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
    }
    rendered, reference_digest = _render_export_markdown(
        version=version,
        export_type="prd_research_input_markdown",
        selection_manifest=selection,
        readiness_context=readiness_context,
    )
    assert rendered.startswith(f"# PRD Research Input\n\n> Data authenticity: {label}\n\n")
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
        }
    )
