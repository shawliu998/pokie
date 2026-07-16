from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from packages.contracts.events import RunEvent as ContractRunEvent
from packages.contracts.events import StreamResetEvent, encode_sse
from packages.contracts.schemas import (
    BriefExportCreateRequest,
    BriefExportPreviewRequest,
    BriefExportPreviewResponse,
    BriefExportResponse,
    ClaimResponse,
    ClaimReviewRequest,
    ClaimReviewResponse,
    ClaimVersionCreateRequest,
    ClaimVersionResponse,
    CursorPage,
    DecisionBriefCreateRequest,
    DecisionBriefFreshnessRecheckRequest,
    DecisionBriefFreshnessRecordResponse,
    DecisionBriefReadinessRequest,
    DecisionBriefReadinessReviewResponse,
    DecisionBriefResponse,
    DecisionBriefRevisionRequest,
    DecisionBriefVersionResponse,
    DecisionBriefVersionUpdateRequest,
    EvidenceResponse,
    EvidenceReviewRequest,
    EvidenceReviewResponse,
    InvestigationCreateRequest,
    InvestigationResponse,
    InvestigationScopeVersionResponse,
    InvestigationSynthesisResponse,
    InvestigationSynthesisVersionResponse,
    InvestigationTransitionRequest,
    InvestigationUpdateRequest,
    ResearchRunCancelRequest,
    ResearchRunCreateRequest,
    ResearchRunResponse,
    SynthesisCreateRequest,
    SynthesisReviewRequest,
    SynthesisReviewResponse,
    SynthesisUpdateRequest,
)
from services.api.app.api import presenters as p
from services.api.app.api.pagination import decode_cursor, page_payload
from services.api.app.core.auth import WorkspaceContext, require_owner
from services.api.app.core.errors import ApiError, invalid_state, not_found, version_conflict
from services.api.app.db.models import (
    BriefExport,
    Claim,
    ClaimVersion,
    DecisionBrief,
    DecisionBriefVersion,
    Evidence,
    Investigation,
    InvestigationScopeVersion,
    InvestigationSynthesis,
    InvestigationSynthesisVersion,
    ResearchRun,
    RunEvent,
)
from services.api.app.db.session import get_db, get_session_factory, set_rls_context
from services.api.app.modules.common import append_run_event, audit
from services.api.app.modules.decisions.service import (
    create_decision_brief,
    create_export,
    create_synthesis,
    freshness_recheck,
    latest_freshness,
    mark_ready,
    render_export_preview,
    review_synthesis,
    revise_brief,
    revise_synthesis,
    start_brief_revision,
)
from services.api.app.modules.evidence.service import (
    create_claim_version,
    review_claim_version,
    review_evidence,
)
from services.api.app.modules.research.service import (
    create_investigation,
    create_research_run,
    revise_investigation_scope,
    transition_investigation,
)

router = APIRouter(prefix="/v1")
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[WorkspaceContext, Depends(require_owner)]


def _request_id(request: Request) -> str:
    return request.state.request_id


def _row(db: Session, model: Any, row_id: UUID | str, workspace_id: str) -> Any:
    row = db.scalar(
        select(model).where(model.id == str(row_id), model.workspace_id == workspace_id)
    )
    if row is None:
        raise not_found(model.__name__)
    return row


def _datetime_keyset(cursor: str, workspace_id: str, scope: str) -> tuple[datetime, str]:
    values = decode_cursor(cursor=cursor, workspace_id=workspace_id, scope=scope)
    try:
        return datetime.fromisoformat(str(values["at"])), str(values["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "The pagination cursor is malformed.") from exc


@router.post("/investigations", response_model=InvestigationResponse, status_code=201)
def post_investigation(
    body: InvestigationCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = create_investigation(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return p.investigation(db, row)


@router.get("/investigations", response_model=CursorPage[InvestigationResponse])
def list_investigations(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "investigations"
    query = select(Investigation).where(Investigation.workspace_id == context.workspace_id)
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(
                Investigation.created_at < at,
                and_(Investigation.created_at == at, Investigation.id < row_id),
            )
        )
    fetched = db.scalars(
        query.order_by(Investigation.created_at.desc(), Investigation.id.desc()).limit(limit + 1)
    ).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.investigation(db, row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.get("/investigations/{investigation_id}", response_model=InvestigationResponse)
def get_investigation(investigation_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.investigation(db, _row(db, Investigation, investigation_id, context.workspace_id))


@router.patch("/investigations/{investigation_id}", response_model=InvestigationResponse)
def patch_investigation(
    investigation_id: UUID, body: InvestigationUpdateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = revise_investigation_scope(
        db,
        investigation=_row(db, Investigation, investigation_id, context.workspace_id),
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return p.investigation(db, row)


@router.get(
    "/investigations/{investigation_id}/scope-versions",
    response_model=CursorPage[InvestigationScopeVersionResponse],
)
def list_scopes(
    investigation_id: UUID,
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    _row(db, Investigation, investigation_id, context.workspace_id)
    scope_name = f"investigation-scopes:{investigation_id}"
    query = select(InvestigationScopeVersion).where(
        InvestigationScopeVersion.workspace_id == context.workspace_id,
        InvestigationScopeVersion.investigation_id == str(investigation_id),
    )
    if cursor is not None:
        values = decode_cursor(cursor=cursor, workspace_id=context.workspace_id, scope=scope_name)
        try:
            version_number, row_id = int(values["version"]), str(values["id"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ApiError(422, "VALIDATION_ERROR", "The pagination cursor is malformed.") from exc
        query = query.where(
            or_(
                InvestigationScopeVersion.version_number > version_number,
                and_(
                    InvestigationScopeVersion.version_number == version_number,
                    InvestigationScopeVersion.id > row_id,
                ),
            )
        )
    fetched = db.scalars(
        query.order_by(
            InvestigationScopeVersion.version_number, InvestigationScopeVersion.id
        ).limit(limit + 1)
    ).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.scope(row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope_name,
        last_keyset={"version": rows[-1].version_number, "id": rows[-1].id} if rows else None,
    )


@router.post("/investigations/{investigation_id}/transitions", response_model=InvestigationResponse)
def transition_investigation_route(
    investigation_id: UUID,
    body: InvestigationTransitionRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    row = transition_investigation(
        db,
        investigation=_row(db, Investigation, investigation_id, context.workspace_id),
        actor_id=context.principal_id,
        action=body.action.value,
        expected_row_version=body.expected_row_version,
        reason=body.reason,
        request_id=_request_id(request),
    )
    return p.investigation(db, row)


@router.post("/research-runs", response_model=ResearchRunResponse, status_code=202)
def post_research_run(
    body: ResearchRunCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row, _command = create_research_run(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return p.research_run(row)


@router.get("/research-runs", response_model=CursorPage[ResearchRunResponse])
def list_research_runs(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "research-runs"
    query = select(ResearchRun).where(ResearchRun.workspace_id == context.workspace_id)
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(
                ResearchRun.created_at < at,
                and_(ResearchRun.created_at == at, ResearchRun.id < row_id),
            )
        )
    fetched = db.scalars(
        query.order_by(ResearchRun.created_at.desc(), ResearchRun.id.desc()).limit(limit + 1)
    ).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.research_run(row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.get("/research-runs/{run_id}", response_model=ResearchRunResponse)
def get_research_run(run_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.research_run(_row(db, ResearchRun, run_id, context.workspace_id))


@router.post("/research-runs/{run_id}/cancel", response_model=ResearchRunResponse)
def cancel_research_run(
    run_id: UUID, body: ResearchRunCancelRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = _row(db, ResearchRun, run_id, context.workspace_id)
    if row.row_version != body.expected_row_version:
        raise version_conflict(row.id, row.row_version)
    if row.state not in {"queued", "running", "waiting_for_input"}:
        raise invalid_state("Only an unfinished Research Run can be cancelled.")
    row.state = "cancelled"
    row.row_version += 1
    append_run_event(
        db,
        workspace_id=row.workspace_id,
        investigation_id=row.investigation_id,
        run_id=row.id,
        event_type="run.cancelled",
        payload={"state": "cancelled", "safe_summary": body.reason},
        trace_id=row.trace_id,
        event_idempotency_key=f"run:{row.id}:cancelled",
    )
    audit(
        db,
        workspace_id=row.workspace_id,
        actor_id=context.principal_id,
        action="research_run.cancelled",
        target_type="ResearchRun",
        target_id=row.id,
        request_id=_request_id(request),
        reason=body.reason,
    )
    db.commit()
    return p.research_run(row)


@router.get("/research-runs/{run_id}/events")
def stream_run_events(
    run_id: UUID,
    context: Ctx,
    db: Db,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    run = _row(db, ResearchRun, run_id, context.workspace_id)
    after_sequence = 0
    if last_event_id:
        cursor = db.scalar(
            select(RunEvent).where(
                RunEvent.event_id == last_event_id, RunEvent.research_run_id == run.id
            )
        )
        if cursor is None:
            reset = StreamResetEvent(
                snapshot_url=f"/v1/research-runs/{run.id}",
                latest_sequence=run.latest_sequence,
                data_authenticity=run.data_authenticity,
            )
            return StreamingResponse(iter([encode_sse(reset)]), media_type="text/event-stream")
        after_sequence = cursor.sequence

    def generate() -> Iterator[str]:
        cursor_sequence = after_sequence
        heartbeat_at = time.monotonic() + 15.0
        factory = get_session_factory()
        while True:
            with factory() as stream_db:
                set_rls_context(stream_db, context.workspace_id, context.principal_id)
                current_run = stream_db.scalar(
                    select(ResearchRun).where(
                        ResearchRun.id == run.id,
                        ResearchRun.workspace_id == context.workspace_id,
                    )
                )
                if current_run is None:
                    return
                rows = stream_db.scalars(
                    select(RunEvent)
                    .where(
                        RunEvent.research_run_id == run.id,
                        RunEvent.workspace_id == context.workspace_id,
                        RunEvent.sequence > cursor_sequence,
                    )
                    .order_by(RunEvent.sequence)
                ).all()
                state = current_run.state
                for row in rows:
                    event = ContractRunEvent.model_validate(
                        {
                            "investigation_id": row.investigation_id,
                            "research_run_id": row.research_run_id,
                            "sequence": row.sequence,
                            "event_id": row.event_id,
                            "type": row.type,
                            "payload_json": row.payload_json,
                            "trace_id": row.trace_id,
                            "occurred_at": row.occurred_at,
                            "data_authenticity": row.data_authenticity,
                        }
                    )
                    cursor_sequence = row.sequence
                    yield encode_sse(event)
            if state in {"completed", "failed", "cancelled"}:
                return
            now = time.monotonic()
            if now >= heartbeat_at:
                yield ": heartbeat\n\n"
                heartbeat_at = now + 15.0
            time.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/evidence/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(evidence_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.evidence(db, _row(db, Evidence, evidence_id, context.workspace_id))


@router.post(
    "/evidence/{evidence_id}/review", response_model=EvidenceReviewResponse, status_code=201
)
def post_evidence_review(
    evidence_id: UUID, body: EvidenceReviewRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = review_evidence(
        db,
        evidence=_row(db, Evidence, evidence_id, context.workspace_id),
        actor_id=context.principal_id,
        decision=body.decision.value,
        reason=body.reason,
        policy_version=body.policy_version,
        request_id=_request_id(request),
    )
    return {
        "id": row.id,
        "evidence_id": row.evidence_id,
        "decision": row.decision,
        "reviewer_id": row.reviewer_id,
        "reason": row.reason,
        "policy_version": row.policy_version,
        "reviewed_at": row.reviewed_at,
        "data_authenticity": row.data_authenticity,
    }


@router.get("/claims", response_model=CursorPage[ClaimResponse])
def list_claims(
    context: Ctx,
    db: Db,
    investigation_id: UUID | None = None,
    run_id: UUID | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = f"claims:investigation={investigation_id}:run={run_id}"
    query = select(Claim).where(Claim.workspace_id == context.workspace_id)
    if investigation_id:
        query = query.where(Claim.investigation_id == str(investigation_id))
    if run_id:
        query = query.where(Claim.research_run_id == str(run_id))
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(Claim.created_at > at, and_(Claim.created_at == at, Claim.id > row_id))
        )
    fetched = db.scalars(query.order_by(Claim.created_at, Claim.id).limit(limit + 1)).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.claim(db, row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.get("/claims/{claim_id}", response_model=ClaimResponse)
def get_claim(claim_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.claim(db, _row(db, Claim, claim_id, context.workspace_id))


@router.get("/claims/{claim_id}/versions/{version_id}", response_model=ClaimVersionResponse)
def get_claim_version(claim_id: UUID, version_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    claim = _row(db, Claim, claim_id, context.workspace_id)
    version = _row(db, ClaimVersion, version_id, context.workspace_id)
    if version.claim_id != claim.id:
        raise not_found("Claim version")
    return p.claim_version(db, version, claim)


@router.post("/claims/{claim_id}/versions", response_model=ClaimVersionResponse, status_code=201)
def post_claim_version(
    claim_id: UUID, body: ClaimVersionCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    claim = _row(db, Claim, claim_id, context.workspace_id)
    version = create_claim_version(
        db,
        claim=claim,
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return p.claim_version(db, version, claim)


@router.post(
    "/claims/{claim_id}/versions/{version_id}/review",
    response_model=ClaimReviewResponse,
    status_code=201,
)
def post_claim_review(
    claim_id: UUID,
    version_id: UUID,
    body: ClaimReviewRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    if str(version_id) != str(body.claim_version_id):
        raise ApiError(422, "VALIDATION_ERROR", "Path and body ClaimVersion IDs differ.")
    claim = _row(db, Claim, claim_id, context.workspace_id)
    version = _row(db, ClaimVersion, version_id, context.workspace_id)
    row = review_claim_version(
        db,
        claim=claim,
        version=version,
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return {
        "id": row.id,
        "claim_version_id": row.claim_version_id,
        "decision": row.decision,
        "claim_evidence_snapshot_json": row.claim_evidence_snapshot_json,
        "evidence_review_snapshot_json": row.evidence_review_snapshot_json,
        "snapshot_digest": row.snapshot_digest,
        "reviewer_id": row.reviewer_id,
        "reason": row.reason,
        "policy_version": row.policy_version,
        "reviewed_at": row.reviewed_at,
        "data_authenticity": row.data_authenticity,
    }


@router.post(
    "/investigations/{investigation_id}/synthesis",
    response_model=InvestigationSynthesisResponse,
    status_code=201,
)
def post_synthesis(
    investigation_id: UUID, body: SynthesisCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = create_synthesis(
        db,
        investigation=_row(db, Investigation, investigation_id, context.workspace_id),
        actor_id=context.principal_id,
        claim_version_ids=[str(value) for value in body.verified_claim_version_ids],
        request_id=_request_id(request),
    )
    return p.synthesis(db, row)


@router.get(
    "/investigations/{investigation_id}/synthesis", response_model=InvestigationSynthesisResponse
)
def get_synthesis(investigation_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    row = db.scalar(
        select(InvestigationSynthesis).where(
            InvestigationSynthesis.investigation_id == str(investigation_id),
            InvestigationSynthesis.workspace_id == context.workspace_id,
        )
    )
    if row is None:
        raise not_found("Investigation synthesis")
    return p.synthesis(db, row)


@router.get(
    "/investigations/{investigation_id}/synthesis/versions/{version_id}",
    response_model=InvestigationSynthesisVersionResponse,
)
def get_synthesis_version(
    investigation_id: UUID, version_id: UUID, context: Ctx, db: Db
) -> dict[str, Any]:
    investigation = _row(db, Investigation, investigation_id, context.workspace_id)
    version = _row(db, InvestigationSynthesisVersion, version_id, context.workspace_id)
    synthesis = _row(db, InvestigationSynthesis, version.synthesis_id, context.workspace_id)
    if synthesis.investigation_id != investigation.id:
        raise not_found("Investigation synthesis version")
    return p.synthesis_version(db, version, investigation.id)


@router.patch(
    "/investigations/{investigation_id}/synthesis", response_model=InvestigationSynthesisResponse
)
def patch_synthesis(
    investigation_id: UUID, body: SynthesisUpdateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = db.scalar(
        select(InvestigationSynthesis).where(
            InvestigationSynthesis.investigation_id == str(investigation_id),
            InvestigationSynthesis.workspace_id == context.workspace_id,
        )
    )
    if row is None:
        raise not_found("Investigation synthesis")
    row = revise_synthesis(
        db,
        synthesis=row,
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return p.synthesis(db, row)


@router.post(
    "/investigations/{investigation_id}/synthesis/versions/{version_id}/review",
    response_model=SynthesisReviewResponse,
    status_code=201,
)
def post_synthesis_review(
    investigation_id: UUID,
    version_id: UUID,
    body: SynthesisReviewRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    if str(version_id) != str(body.synthesis_version_id):
        raise ApiError(422, "VALIDATION_ERROR", "Path and body synthesis IDs differ.")
    synthesis = db.scalar(
        select(InvestigationSynthesis).where(
            InvestigationSynthesis.investigation_id == str(investigation_id),
            InvestigationSynthesis.workspace_id == context.workspace_id,
        )
    )
    if synthesis is None:
        raise not_found("Investigation synthesis")
    row = review_synthesis(
        db,
        synthesis=synthesis,
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return {
        "id": row.id,
        "synthesis_version_id": row.synthesis_version_id,
        "decision": row.decision,
        "reviewer_id": row.reviewer_id,
        "reason": row.reason,
        "policy_version": row.policy_version,
        "reviewed_at": row.reviewed_at,
        "data_authenticity": row.data_authenticity,
    }


@router.post(
    "/investigations/{investigation_id}/decision-brief",
    response_model=DecisionBriefResponse,
    status_code=201,
)
def post_brief(
    investigation_id: UUID, body: DecisionBriefCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = create_decision_brief(
        db,
        investigation=_row(db, Investigation, investigation_id, context.workspace_id),
        actor_id=context.principal_id,
        synthesis_version_id=str(body.synthesis_version_id),
        template_version=body.template_version,
        request_id=_request_id(request),
    )
    return p.brief(db, row)


@router.get("/decision-briefs", response_model=CursorPage[DecisionBriefResponse])
def list_briefs(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "decision-briefs"
    query = select(DecisionBrief).where(DecisionBrief.workspace_id == context.workspace_id)
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(
                DecisionBrief.created_at < at,
                and_(DecisionBrief.created_at == at, DecisionBrief.id < row_id),
            )
        )
    fetched = db.scalars(
        query.order_by(DecisionBrief.created_at.desc(), DecisionBrief.id.desc()).limit(limit + 1)
    ).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.brief(db, row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.get("/decision-briefs/{brief_id}", response_model=DecisionBriefResponse)
def get_brief(brief_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.brief(db, _row(db, DecisionBrief, brief_id, context.workspace_id))


@router.get(
    "/decision-briefs/{brief_id}/versions/{version_id}",
    response_model=DecisionBriefVersionResponse,
)
def get_brief_version(brief_id: UUID, version_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    brief = _row(db, DecisionBrief, brief_id, context.workspace_id)
    version = _row(db, DecisionBriefVersion, version_id, context.workspace_id)
    if version.decision_brief_id != brief.id:
        raise not_found("Decision Brief version")
    return p.brief_version(db, version, brief.investigation_id)


@router.patch("/decision-briefs/{brief_id}", response_model=DecisionBriefResponse)
def patch_brief(
    brief_id: UUID, body: DecisionBriefVersionUpdateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = revise_brief(
        db,
        brief=_row(db, DecisionBrief, brief_id, context.workspace_id),
        actor_id=context.principal_id,
        block_document=body.block_document.model_dump(mode="json"),
        expected_row_version=body.expected_row_version,
        human_edit_digest=body.human_edit_digest,
        request_id=_request_id(request),
    )
    return p.brief(db, row)


@router.post(
    "/decision-briefs/{brief_id}/revisions",
    response_model=DecisionBriefResponse,
    status_code=201,
)
def post_brief_revision(
    brief_id: UUID, body: DecisionBriefRevisionRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = start_brief_revision(
        db,
        brief=_row(db, DecisionBrief, brief_id, context.workspace_id),
        actor_id=context.principal_id,
        base_version_id=str(body.base_decision_brief_version_id),
        synthesis_version_id=str(body.synthesis_version_id),
        expected_row_version=body.expected_row_version,
        request_id=_request_id(request),
    )
    return p.brief(db, row)


@router.post(
    "/decision-briefs/{brief_id}/mark-decision-ready",
    response_model=DecisionBriefReadinessReviewResponse,
    status_code=201,
)
def post_ready(
    brief_id: UUID, body: DecisionBriefReadinessRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = mark_ready(
        db,
        brief=_row(db, DecisionBrief, brief_id, context.workspace_id),
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return {
        "id": row.id,
        "decision_brief_version_id": row.decision_brief_version_id,
        "decision": row.decision,
        "reviewer_id": row.reviewer_id,
        "reason": row.reason,
        "policy_version": row.policy_version,
        "checklist_digest": row.checklist_digest,
        "reviewed_at": row.reviewed_at,
        "data_authenticity": row.data_authenticity,
    }


@router.get(
    "/decision-briefs/{brief_id}/versions/{version_id}/freshness",
    response_model=DecisionBriefFreshnessRecordResponse,
)
def get_freshness(brief_id: UUID, version_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    brief = _row(db, DecisionBrief, brief_id, context.workspace_id)
    version = _row(db, DecisionBriefVersion, version_id, context.workspace_id)
    if version.decision_brief_id != brief.id:
        raise not_found("Decision Brief version")
    row = latest_freshness(db, version.id)
    if row is None:
        raise not_found("Freshness record")
    return {
        "id": row.id,
        "decision_brief_version_id": row.decision_brief_version_id,
        "status": row.status,
        "affected_reference_snapshot_json": [
            item.get("evidence_id") or item.get("reference_id")
            for item in row.affected_reference_snapshot_json
            if item.get("evidence_id") or item.get("reference_id")
        ],
        "reason": row.reason,
        "policy_version": row.policy_version,
        "assessed_at": row.assessed_at,
        "data_authenticity": row.data_authenticity,
    }


@router.post(
    "/decision-briefs/{brief_id}/versions/{version_id}/freshness/recheck",
    response_model=DecisionBriefFreshnessRecordResponse,
    status_code=201,
)
def post_freshness(
    brief_id: UUID,
    version_id: UUID,
    body: DecisionBriefFreshnessRecheckRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    brief = _row(db, DecisionBrief, brief_id, context.workspace_id)
    version = _row(db, DecisionBriefVersion, version_id, context.workspace_id)
    if version.decision_brief_id != brief.id:
        raise not_found("Decision Brief version")
    row = freshness_recheck(
        db,
        version=version,
        actor_id=context.principal_id,
        reason=body.reason,
        request_id=_request_id(request),
    )
    return {
        "id": row.id,
        "decision_brief_version_id": row.decision_brief_version_id,
        "status": row.status,
        "affected_reference_snapshot_json": [
            item.get("evidence_id") or item.get("reference_id")
            for item in row.affected_reference_snapshot_json
            if item.get("evidence_id") or item.get("reference_id")
        ],
        "reason": row.reason,
        "policy_version": row.policy_version,
        "assessed_at": row.assessed_at,
        "data_authenticity": row.data_authenticity,
    }


@router.post(
    "/decision-briefs/{brief_id}/exports/preview", response_model=BriefExportPreviewResponse
)
def preview_export(
    brief_id: UUID, body: BriefExportPreviewRequest, context: Ctx, db: Db
) -> dict[str, Any]:
    brief = _row(db, DecisionBrief, brief_id, context.workspace_id)
    version = _row(db, DecisionBriefVersion, body.decision_brief_version_id, context.workspace_id)
    if version.decision_brief_id != brief.id:
        raise not_found("Decision Brief version")
    rendered, reference_digest, export_timestamp = render_export_preview(
        db,
        brief=brief,
        version=version,
        export_type=body.export_type.value,
        selection_manifest=body.selection_manifest.model_dump(mode="json"),
    )
    return {
        "decision_brief_version_id": version.id,
        "export_type": body.export_type,
        "rendered_content": rendered,
        "reference_digest": reference_digest,
        "export_timestamp": export_timestamp,
        "data_authenticity": version.data_authenticity,
    }


@router.post(
    "/decision-briefs/{brief_id}/exports", response_model=BriefExportResponse, status_code=201
)
def post_export(
    brief_id: UUID, body: BriefExportCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    brief = _row(db, DecisionBrief, brief_id, context.workspace_id)
    version = _row(db, DecisionBriefVersion, body.decision_brief_version_id, context.workspace_id)
    if version.decision_brief_id != brief.id:
        raise not_found("Decision Brief version")
    payload = body.model_dump(mode="json")
    payload["export_timestamp"] = body.export_timestamp
    row = create_export(
        db,
        brief=brief,
        version=version,
        actor_id=context.principal_id,
        payload=payload,
        request_id=_request_id(request),
    )
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "decision_brief_version_id": row.decision_brief_version_id,
        "export_type": row.export_type,
        "destination": row.destination,
        "selection_manifest_json": row.selection_manifest_json,
        "reference_digest": row.reference_digest,
        "policy_version": row.policy_version,
        "template_version": row.template_version,
        "output_digest": row.output_digest,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "data_authenticity": row.data_authenticity,
    }


@router.get("/brief-exports/{export_id}", response_model=BriefExportResponse)
def get_brief_export(export_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.brief_export(_row(db, BriefExport, export_id, context.workspace_id))
