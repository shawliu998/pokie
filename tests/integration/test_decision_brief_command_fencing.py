from __future__ import annotations

from uuid import uuid4

import pytest

from services.api.app.core.errors import ApiError
from services.api.app.db.models import DecisionBrief, Investigation
from services.api.app.db.session import get_session_factory
from services.api.app.modules.common import digest
from services.api.app.modules.decisions.service import mark_ready, revise_brief


def _stale_brief_after_concurrent_update() -> DecisionBrief:
    workspace_id = str(uuid4())
    brief_id = str(uuid4())
    version_id = str(uuid4())
    stale = DecisionBrief(
        id=brief_id,
        workspace_id=workspace_id,
        investigation_id=str(uuid4()),
        current_version_id=version_id,
        status="draft",
        owner_id=str(uuid4()),
        row_version=1,
        data_authenticity="human_authored",
    )
    factory = get_session_factory()
    with factory() as db:
        db.add_all(
            [
                Investigation(
                    id=stale.investigation_id,
                    workspace_id=workspace_id,
                    project_id=str(uuid4()),
                    signal_id=str(uuid4()),
                    status="active",
                    owner_id=stale.owner_id,
                    data_authenticity="human_authored",
                ),
                DecisionBrief(
                    id=brief_id,
                    workspace_id=workspace_id,
                    investigation_id=stale.investigation_id,
                    current_version_id=version_id,
                    status="draft",
                    owner_id=stale.owner_id,
                    row_version=2,
                    data_authenticity="human_authored",
                ),
            ]
        )
        db.commit()
    return stale


def _assert_version_conflict(error: ApiError, brief_id: str) -> None:
    assert error.status_code == 412
    assert error.code == "VERSION_CONFLICT"
    assert error.details == {"resource_id": brief_id, "current_row_version": 2}


def test_revise_brief_refreshes_a_stale_command_before_version_checks() -> None:
    stale = _stale_brief_after_concurrent_update()
    document = {
        "schema_version": "decision-brief-blocks-v1",
        "blocks": [],
        "no_counter_evidence_search": None,
    }

    with get_session_factory()() as db, pytest.raises(ApiError) as raised:
        revise_brief(
            db,
            brief=stale,
            actor_id=stale.owner_id,
            block_document=document,
            expected_row_version=1,
            human_edit_digest=digest(document),
            request_id=str(uuid4()),
        )

    _assert_version_conflict(raised.value, stale.id)


def test_mark_ready_refreshes_a_stale_command_before_current_version_checks() -> None:
    stale = _stale_brief_after_concurrent_update()

    with get_session_factory()() as db, pytest.raises(ApiError) as raised:
        mark_ready(
            db,
            brief=stale,
            actor_id=stale.owner_id,
            payload={
                "decision_brief_version_id": stale.current_version_id,
                "expected_row_version": 1,
                "decision": "mark_decision_ready",
                "reason": "Stale concurrent readiness command.",
                "policy_version": "decision-readiness-v1",
                "checklist_digest": f"sha256:{'0' * 64}",
            },
            request_id=str(uuid4()),
        )

    _assert_version_conflict(raised.value, stale.id)
