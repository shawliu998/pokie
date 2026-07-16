from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from packages.contracts.schemas import (
    AuditLogFilter,
    AuditLogResponse,
    CollectionRunResponse,
    CollectionScheduleCreateRequest,
    CollectionScheduleResponse,
    CollectionScheduleUpdateRequest,
    ContentItemResponse,
    ContentVersionResponse,
    CursorPage,
    ImportCancelRequest,
    ImportFinalizationJobResponse,
    ImportFinalizeRequest,
    ImportManifestResponse,
    ImportRecoveryItem,
    ImportSessionCreateRequest,
    ImportSessionResponse,
    NavigationSummary,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    SignalEvidenceResponse,
    SignalResponse,
    SignalTransitionRequest,
    SignalTriageRequest,
    SourceConnectionCreateRequest,
    SourceConnectionResponse,
    SourceConnectionUpdateRequest,
    SourceValidationJobResponse,
    SourceValidationRequest,
    SyncBootstrapResponse,
    UploadCompleteRequest,
    UploadConsentPreviewRequest,
    UploadConsentPreviewResponse,
    UploadConsentRequest,
    UploadConsentResponse,
    WatchlistCreateRequest,
    WatchlistResponse,
    WatchlistStateCommand,
    WatchlistUpdateRequest,
    WorkspaceCreateRequest,
    WorkspaceMembershipResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)
from services.api.app.api import presenters as p
from services.api.app.api.pagination import decode_cursor, page_payload
from services.api.app.core.auth import (
    Principal,
    WorkspaceContext,
    get_principal,
    require_owner,
)
from services.api.app.core.errors import ApiError, not_found, version_conflict
from services.api.app.db.models import (
    AuditLog,
    CollectionRun,
    CollectionSchedule,
    ContentItem,
    ContentVersion,
    DecisionBrief,
    ImportFinalizationJobRecord,
    ImportManifest,
    ImportSession,
    Investigation,
    Project,
    Signal,
    SignalEvidence,
    SourceConnection,
    SourceValidationJobRecord,
    Watchlist,
    Workspace,
    WorkspaceMember,
    new_id,
)
from services.api.app.db.session import get_db, set_principal_context, set_rls_context
from services.api.app.modules.common import audit, utcnow
from services.api.app.modules.signals.service import transition_signal
from services.api.app.modules.sources.schedules import (
    configure_schedule,
    synchronize_source_schedules,
    update_schedule,
)
from services.api.app.modules.sources.service import (
    authorize_upload_grant,
    begin_finalize,
    cancel_import,
    complete_upload,
    create_import_session,
    grant_upload_consent,
    preview_upload_consent,
    store_uploaded_object,
)
from services.api.app.modules.sources.validation import SourceValidationJobRepository

router = APIRouter(prefix="/v1")
Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[WorkspaceContext, Depends(require_owner)]


def _datetime_keyset(cursor: str, workspace_id: str, scope: str) -> tuple[datetime, str]:
    values = decode_cursor(cursor=cursor, workspace_id=workspace_id, scope=scope)
    try:
        return datetime.fromisoformat(str(values["at"])), str(values["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "The pagination cursor is malformed.") from exc


def _request_id(request: Request) -> str:
    return request.state.request_id


def _row(db: Session, model: Any, row_id: UUID, workspace_id: str) -> Any:
    result = db.scalar(
        select(model).where(model.id == str(row_id), model.workspace_id == workspace_id)
    )
    if result is None:
        raise not_found(model.__name__)
    return result


@router.get("/workspaces", response_model=list[WorkspaceMembershipResponse])
def list_workspaces(
    principal: Annotated[Principal, Depends(get_principal)], db: Db
) -> list[dict[str, Any]]:
    set_principal_context(db, principal.user_id)
    members = db.scalars(
        select(WorkspaceMember).where(
            WorkspaceMember.user_id == principal.user_id, WorkspaceMember.status == "active"
        )
    ).all()
    result: list[dict[str, Any]] = []
    for member in members:
        set_rls_context(db, member.workspace_id, principal.user_id)
        workspace = db.get(Workspace, member.workspace_id)
        if workspace:
            result.append(
                {
                    "workspace_id": member.workspace_id,
                    "user_id": member.user_id,
                    "workspace_name": workspace.name,
                    "role": member.role,
                    "status": member.status,
                    "data_authenticity": workspace.data_authenticity,
                }
            )
    return result


@router.post("/workspaces", response_model=WorkspaceResponse, status_code=201)
def create_workspace(
    body: WorkspaceCreateRequest,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    db: Db,
) -> dict[str, Any]:
    workspace_id = new_id()
    set_rls_context(db, workspace_id, principal.user_id)
    row = Workspace(
        id=workspace_id,
        name=body.name,
        data_region=body.data_region,
        retention_policy_version=body.retention_policy_version,
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()
    db.add(WorkspaceMember(workspace_id=row.id, user_id=principal.user_id, role="owner"))
    audit(
        db,
        workspace_id=row.id,
        actor_id=principal.user_id,
        action="workspace.created",
        target_type="Workspace",
        target_id=row.id,
        request_id=_request_id(request),
        after={"name": row.name},
    )
    db.commit()
    return p.workspace(row)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(workspace_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    if str(workspace_id) != context.workspace_id:
        raise not_found("Workspace")
    row = db.get(Workspace, context.workspace_id)
    if row is None:
        raise not_found("Workspace")
    return p.workspace(row)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def patch_workspace(
    workspace_id: UUID,
    body: WorkspaceUpdateRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    row = (
        db.get(Workspace, context.workspace_id)
        if str(workspace_id) == context.workspace_id
        else None
    )
    if row is None:
        raise not_found("Workspace")
    if row.row_version != body.expected_row_version:
        raise version_conflict(row.id, row.row_version)
    if body.name is not None:
        row.name = body.name
    if body.retention_policy_version is not None:
        row.retention_policy_version = body.retention_policy_version
    row.row_version += 1
    audit(
        db,
        workspace_id=row.id,
        actor_id=context.principal_id,
        action="workspace.updated",
        target_type="Workspace",
        target_id=row.id,
        request_id=_request_id(request),
        after={"row_version": row.row_version},
    )
    db.commit()
    return p.workspace(row)


@router.get("/projects", response_model=CursorPage[ProjectResponse])
def list_projects(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "projects"
    query = select(Project).where(Project.workspace_id == context.workspace_id)
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(Project.created_at > at, and_(Project.created_at == at, Project.id > row_id))
        )
    fetched = db.scalars(query.order_by(Project.created_at, Project.id).limit(limit + 1)).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.project(row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.post("/projects", response_model=ProjectResponse, status_code=201)
def create_project(
    body: ProjectCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = Project(
        workspace_id=context.workspace_id, name=body.name, created_by=context.principal_id
    )
    db.add(row)
    db.flush()
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action="project.created",
        target_type="Project",
        target_id=row.id,
        request_id=_request_id(request),
        after={"name": row.name},
    )
    db.commit()
    return p.project(row)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def patch_project(
    project_id: UUID, body: ProjectUpdateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = _row(db, Project, project_id, context.workspace_id)
    if row.row_version != body.expected_row_version:
        raise version_conflict(row.id, row.row_version)
    if body.name is not None:
        row.name = body.name
    if body.status is not None:
        row.status = body.status.value
    row.row_version += 1
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action="project.updated",
        target_type="Project",
        target_id=row.id,
        request_id=_request_id(request),
        after={"row_version": row.row_version},
    )
    db.commit()
    return p.project(row)


@router.get("/watchlists", response_model=CursorPage[WatchlistResponse])
def list_watchlists(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "watchlists"
    query = select(Watchlist).where(Watchlist.workspace_id == context.workspace_id)
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(Watchlist.created_at > at, and_(Watchlist.created_at == at, Watchlist.id > row_id))
        )
    fetched = db.scalars(query.order_by(Watchlist.created_at, Watchlist.id).limit(limit + 1)).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.watchlist(db, row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.post("/watchlists", response_model=WatchlistResponse, status_code=201)
def create_watchlist(
    body: WatchlistCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    _row(db, Project, body.project_id, context.workspace_id)
    sources = db.scalars(
        select(SourceConnection).where(
            SourceConnection.workspace_id == context.workspace_id,
            SourceConnection.id.in_([str(value) for value in body.source_connection_ids]),
        )
    ).all()
    if len(sources) != len(set(body.source_connection_ids)):
        raise ApiError(
            422, "SOURCE_SCOPE_BLOCKED", "Watchlist sources must belong to the workspace."
        )
    row = Watchlist(
        workspace_id=context.workspace_id,
        project_id=str(body.project_id),
        name=body.name,
        objective=body.objective,
        rules_json={
            "source_connection_ids": [str(value) for value in body.source_connection_ids],
            "rules": body.rules.model_dump(mode="json"),
        },
        owner_id=context.principal_id,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action="watchlist.created",
        target_type="Watchlist",
        target_id=row.id,
        request_id=_request_id(request),
        after={"rules_version": 1},
    )
    db.commit()
    return p.watchlist(db, row)


@router.patch("/watchlists/{watchlist_id}", response_model=WatchlistResponse)
def patch_watchlist(
    watchlist_id: UUID, body: WatchlistUpdateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = _row(db, Watchlist, watchlist_id, context.workspace_id)
    if row.row_version != body.expected_row_version:
        raise version_conflict(row.id, row.row_version)
    update = body.model_dump(mode="json", exclude_none=True)
    for key in ("name", "objective"):
        if key in update:
            setattr(row, key, update[key])
    updated_rules = dict(row.rules_json or {})
    if "source_connection_ids" in update:
        source_connection_ids = [str(value) for value in update["source_connection_ids"]]
        sources = db.scalars(
            select(SourceConnection).where(
                SourceConnection.workspace_id == context.workspace_id,
                SourceConnection.id.in_(source_connection_ids),
            )
        ).all()
        if len(sources) != len(set(source_connection_ids)):
            raise ApiError(
                422,
                "SOURCE_SCOPE_BLOCKED",
                "Watchlist sources must belong to the workspace.",
            )
        updated_rules["source_connection_ids"] = source_connection_ids
    if "rules" in update:
        updated_rules["rules"] = update["rules"]
        row.rules_version += 1
    row.rules_json = updated_rules
    row.row_version += 1
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action="watchlist.updated",
        target_type="Watchlist",
        target_id=row.id,
        request_id=_request_id(request),
        after={"rules_version": row.rules_version},
    )
    db.commit()
    return p.watchlist(db, row)


def _watchlist_state(
    row: Watchlist,
    body: WatchlistStateCommand,
    target: str,
    request: Request,
    context: WorkspaceContext,
    db: Session,
) -> dict[str, Any]:
    if row.row_version != body.expected_row_version:
        raise version_conflict(row.id, row.row_version)
    row.status = target
    row.row_version += 1
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action=f"watchlist.{target}",
        target_type="Watchlist",
        target_id=row.id,
        request_id=_request_id(request),
        reason=body.reason,
    )
    db.commit()
    return p.watchlist(db, row)


@router.post("/watchlists/{watchlist_id}/activate", response_model=WatchlistResponse)
def activate_watchlist(
    watchlist_id: UUID, body: WatchlistStateCommand, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    return _watchlist_state(
        _row(db, Watchlist, watchlist_id, context.workspace_id),
        body,
        "active",
        request,
        context,
        db,
    )


@router.post("/watchlists/{watchlist_id}/pause", response_model=WatchlistResponse)
def pause_watchlist(
    watchlist_id: UUID, body: WatchlistStateCommand, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    return _watchlist_state(
        _row(db, Watchlist, watchlist_id, context.workspace_id),
        body,
        "paused",
        request,
        context,
        db,
    )


@router.get("/sources", response_model=CursorPage[SourceConnectionResponse])
def list_sources(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "sources"
    query = select(SourceConnection).where(SourceConnection.workspace_id == context.workspace_id)
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(
                SourceConnection.created_at > at,
                and_(SourceConnection.created_at == at, SourceConnection.id > row_id),
            )
        )
    fetched = db.scalars(
        query.order_by(SourceConnection.created_at, SourceConnection.id).limit(limit + 1)
    ).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.source(db, row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.post("/sources", response_model=SourceConnectionResponse, status_code=201)
def create_source(
    body: SourceConnectionCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    if body.source_kind.value == "local":
        raise ApiError(403, "POLICY_BLOCKED", "Local sources are owned by the Mac runtime.")
    row = SourceConnection(
        workspace_id=context.workspace_id,
        name=body.name,
        source_kind=body.source_kind.value,
        runtime=body.runtime.value,
        connector_type=body.connector_type.value,
        connector_version=body.connector_version,
        status="draft",
        credential_ref=body.credential_ref,
        config_json=body.source_config.model_dump(mode="json") if body.source_config else {},
        cadence=body.cadence.value if body.cadence else None,
        timezone=body.timezone,
        freshness_state="never",
        health_state="unknown",
        data_scope=body.data_scope.value,
        data_authenticity=(
            "seed"
            if body.connector_type.value == "seed_fixture"
            else "imported"
            if body.source_kind.value == "imported_dataset"
            else "collected"
        ),
    )
    db.add(row)
    db.flush()
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action="source.created",
        target_type="SourceConnection",
        target_id=row.id,
        request_id=_request_id(request),
        after={"source_kind": row.source_kind},
    )
    db.commit()
    return p.source(db, row)


@router.get("/sources/{source_id}", response_model=SourceConnectionResponse)
def get_source(source_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.source(db, _row(db, SourceConnection, source_id, context.workspace_id))


@router.patch("/sources/{source_id}", response_model=SourceConnectionResponse)
def patch_source(
    source_id: UUID,
    body: SourceConnectionUpdateRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    row = SourceValidationJobRepository.lock_source_for_lifecycle_command(
        db,
        workspace_id=context.workspace_id,
        source_connection_id=str(source_id),
    )
    if row.row_version != body.expected_row_version:
        raise version_conflict(row.id, row.row_version)
    changes = body.model_dump(mode="json", exclude_unset=True)
    changes.pop("expected_row_version", None)
    changed_fields = set(changes)
    cloud_only = {"source_config", "credential_ref", "cadence", "timezone"}
    if row.source_kind != "cloud" and cloud_only.intersection(changes):
        raise ApiError(422, "SOURCE_SCOPE_BLOCKED", "Cloud configuration requires a cloud source.")
    config = changes.pop("source_config", None)
    target_changed = False
    if "source_config" in body.model_fields_set:
        if config is None or config["connector_type"] != row.connector_type:
            raise ApiError(422, "VALIDATION_ERROR", "Source config must match the connector.")
        target_changed = config != row.config_json
        if target_changed and row.status not in {"draft", "failed", "auth_required"}:
            raise ApiError(
                409,
                "INVALID_STATE",
                "Cloud targets can be repaired only while draft, failed, or auth_required.",
            )
        if target_changed:
            row.config_json = config
            row.status = "validating"
            row.health_state = "unknown"
            row.health_error_code = None
        else:
            changed_fields.discard("source_config")
    for field in ("name", "credential_ref", "timezone"):
        if field in changes:
            if getattr(row, field) == changes[field]:
                changed_fields.discard(field)
            setattr(row, field, changes[field])
    if "data_scope" in changes:
        if row.data_scope == changes["data_scope"]:
            changed_fields.discard("data_scope")
        row.data_scope = changes["data_scope"]
    if "cadence" in changes:
        if changes["cadence"] is None:
            raise ApiError(422, "VALIDATION_ERROR", "Cloud cadence cannot be cleared.")
        if row.cadence == changes["cadence"]:
            changed_fields.discard("cadence")
        row.cadence = changes["cadence"]
    row.row_version += 1
    if changed_fields.intersection({"source_config", "cadence", "timezone"}):
        synchronize_source_schedules(
            db,
            source=row,
            changed_fields=changed_fields,
            actor_id=context.principal_id,
            request_id=_request_id(request),
        )
    if target_changed:
        audit(
            db,
            workspace_id=context.workspace_id,
            actor_id=context.principal_id,
            action="source.target_corrected",
            target_type="SourceConnection",
            target_id=row.id,
            request_id=_request_id(request),
            after={"status": row.status, "row_version": row.row_version},
        )
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action="source.updated",
        target_type="SourceConnection",
        target_id=row.id,
        request_id=_request_id(request),
        after={"row_version": row.row_version, "changed_fields": sorted(changed_fields)},
    )
    db.commit()
    return p.source(db, row)


@router.post("/sources/{source_id}/activate", response_model=SourceConnectionResponse)
def activate_source(
    source_id: UUID, body: WatchlistStateCommand, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = SourceValidationJobRepository.lock_source_for_lifecycle_command(
        db,
        workspace_id=context.workspace_id,
        source_connection_id=str(source_id),
    )
    if row.row_version != body.expected_row_version:
        raise version_conflict(row.id, row.row_version)
    row.status = "validating" if row.source_kind == "cloud" else "healthy"
    row.health_state = "unknown" if row.source_kind == "cloud" else row.health_state
    row.health_error_code = None
    row.approved_by = context.principal_id
    row.row_version += 1
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action="source.activated",
        target_type="SourceConnection",
        target_id=row.id,
        request_id=_request_id(request),
        reason=body.reason,
    )
    db.commit()
    return p.source(db, row)


def _source_state_command(
    *,
    row: SourceConnection,
    body: WatchlistStateCommand,
    request: Request,
    context: WorkspaceContext,
    db: Session,
    status: str,
    health_state: str,
    action: str,
) -> dict[str, Any]:
    if row.row_version != body.expected_row_version:
        raise version_conflict(row.id, row.row_version)
    row.status = status
    row.health_state = health_state
    row.health_error_code = None
    row.row_version += 1
    if status == "disabled":
        db.execute(
            update(CollectionSchedule)
            .where(
                CollectionSchedule.workspace_id == row.workspace_id,
                CollectionSchedule.source_connection_id == row.id,
            )
            .values(
                enabled=False,
                lease_owner_token=None,
                lease_expires_at=None,
                heartbeat_at=None,
                row_version=CollectionSchedule.row_version + 1,
            )
        )
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action=action,
        target_type="SourceConnection",
        target_id=row.id,
        request_id=_request_id(request),
        reason=body.reason,
    )
    db.commit()
    return p.source(db, row)


@router.post("/sources/{source_id}/disable", response_model=SourceConnectionResponse)
def disable_source(
    source_id: UUID,
    body: WatchlistStateCommand,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    return _source_state_command(
        row=SourceValidationJobRepository.lock_source_for_lifecycle_command(
            db,
            workspace_id=context.workspace_id,
            source_connection_id=str(source_id),
        ),
        body=body,
        request=request,
        context=context,
        db=db,
        status="disabled",
        health_state="disabled",
        action="source.disabled",
    )


@router.post("/sources/{source_id}/remove", response_model=SourceConnectionResponse)
def remove_source(
    source_id: UUID,
    body: WatchlistStateCommand,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    return _source_state_command(
        row=SourceValidationJobRepository.lock_source_for_lifecycle_command(
            db,
            workspace_id=context.workspace_id,
            source_connection_id=str(source_id),
        ),
        body=body,
        request=request,
        context=context,
        db=db,
        status="disabled",
        health_state="disabled",
        action="source.removed",
    )


def _queue_source_validation(
    *,
    source_id: UUID,
    command: str,
    body: SourceValidationRequest,
    request: Request,
    context: WorkspaceContext,
    db: Session,
) -> dict[str, Any]:
    job = SourceValidationJobRepository.enqueue(
        db,
        workspace_id=context.workspace_id,
        source_connection_id=str(source_id),
        command=command,
        expected_source_row_version=body.expected_row_version,
        actor_id=context.principal_id,
        request_id=_request_id(request),
        idempotency_key=str(UUID(request.headers["Idempotency-Key"])),
        reason=body.reason,
    )
    return p.source_validation_job(job)


@router.post(
    "/sources/{source_id}/health-check",
    response_model=SourceValidationJobResponse,
    status_code=202,
)
def health_check_source(
    source_id: UUID,
    body: SourceValidationRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    return _queue_source_validation(
        source_id=source_id,
        command="health_check",
        body=body,
        request=request,
        context=context,
        db=db,
    )


@router.post(
    "/sources/{source_id}/reconnect",
    response_model=SourceValidationJobResponse,
    status_code=202,
)
def reconnect_source(
    source_id: UUID,
    body: SourceValidationRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    return _queue_source_validation(
        source_id=source_id,
        command="reconnect",
        body=body,
        request=request,
        context=context,
        db=db,
    )


@router.get("/source-validation-jobs/{job_id}", response_model=SourceValidationJobResponse)
def get_source_validation_job(job_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    row = _row(db, SourceValidationJobRecord, job_id, context.workspace_id)
    return p.source_validation_job(row)


@router.get("/sources/{source_id}/health", response_model=SourceConnectionResponse)
def source_health(source_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.source(db, _row(db, SourceConnection, source_id, context.workspace_id))


@router.post("/imports", response_model=ImportSessionResponse, status_code=201)
def create_import(
    body: ImportSessionCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = create_import_session(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return p.import_session(row)


@router.get("/imports", response_model=CursorPage[ImportRecoveryItem])
def list_imports(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "imports"
    query = select(ImportSession).where(ImportSession.workspace_id == context.workspace_id)
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(
                ImportSession.updated_at < at,
                and_(ImportSession.updated_at == at, ImportSession.id < row_id),
            )
        )
    fetched = db.scalars(
        query.order_by(ImportSession.updated_at.desc(), ImportSession.id.desc()).limit(limit + 1)
    ).all()
    sessions = fetched[:limit]
    session_ids = [row.id for row in sessions]
    jobs = (
        db.scalars(
            select(ImportFinalizationJobRecord).where(
                ImportFinalizationJobRecord.workspace_id == context.workspace_id,
                ImportFinalizationJobRecord.import_session_id.in_(session_ids),
            )
        ).all()
        if session_ids
        else []
    )
    jobs_by_session = {row.import_session_id: row for row in jobs}
    items = [
        {
            "import_session": p.import_session(row),
            "finalization_job": (
                p.finalization_job(jobs_by_session[row.id]) if row.id in jobs_by_session else None
            ),
            "data_authenticity": row.data_authenticity,
        }
        for row in sessions
    ]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=items,
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": sessions[-1].updated_at.isoformat(), "id": sessions[-1].id}
        if sessions
        else None,
    )


@router.get("/imports/{import_id}", response_model=ImportSessionResponse)
def get_import(import_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.import_session(_row(db, ImportSession, import_id, context.workspace_id))


@router.get(
    "/imports/{import_id}/upload-consent/preview",
    response_model=UploadConsentPreviewResponse,
)
def upload_consent_preview(
    import_id: UUID,
    preview: Annotated[UploadConsentPreviewRequest, Depends()],
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    row = _row(db, ImportSession, import_id, context.workspace_id)
    scope, scope_digest = preview_upload_consent(
        db, session=row, expected_row_version=preview.expected_row_version
    )
    return {
        "preview_scope": scope,
        "scope_digest": scope_digest,
        "data_authenticity": row.data_authenticity,
    }


@router.post("/imports/{import_id}/upload-consent", response_model=UploadConsentResponse)
def upload_consent(
    import_id: UUID,
    body: UploadConsentRequest,
    request: Request,
    response: Response,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    row = _row(db, ImportSession, import_id, context.workspace_id)
    consent_row, grant, raw_token = grant_upload_consent(
        db,
        session=row,
        actor_id=context.principal_id,
        preview_scope=body.preview_scope.model_dump(mode="json"),
        scope_digest=body.scope_digest,
        expires_at=body.expires_at,
        confirmation=body.confirmation,
        request_id=_request_id(request),
    )
    response.headers["X-Upload-Grant"] = raw_token
    return {
        "import_session": p.import_session(row),
        "consent_record": p.consent(consent_row),
        "upload": {
            "object_key": grant.object_key,
            "maximum_bytes": grant.max_bytes,
            "media_type": grant.media_type,
            "expires_at": grant.expires_at,
        },
        "data_authenticity": row.data_authenticity,
    }


@router.put("/imports/{import_id}/object", status_code=201)
async def upload_object(
    import_id: UUID,
    request: Request,
    context: Ctx,
    db: Db,
    x_upload_grant: Annotated[str, Header(alias="X-Upload-Grant")],
    content_type: Annotated[str, Header(alias="Content-Type")],
    content_length: Annotated[str | None, Header(alias="Content-Length")] = None,
) -> dict[str, Any]:
    grant = authorize_upload_grant(
        db,
        workspace_id=context.workspace_id,
        import_session_id=str(import_id),
        raw_token=x_upload_grant,
        content_type=content_type,
    )
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise ApiError(422, "VALIDATION_ERROR", "Content-Length must be an integer.") from exc
        if declared_size < 0 or declared_size > grant.max_bytes:
            raise ApiError(413, "POLICY_BLOCKED", "The upload exceeded its authorized size.")
    chunks: list[bytes] = []
    observed_size = 0
    hasher = hashlib.sha256()
    async for chunk in request.stream():
        observed_size += len(chunk)
        if observed_size > grant.max_bytes:
            raise ApiError(413, "POLICY_BLOCKED", "The upload exceeded its authorized size.")
        hasher.update(chunk)
        chunks.append(chunk)
    object_key = store_uploaded_object(
        db,
        workspace_id=context.workspace_id,
        import_session_id=str(import_id),
        raw_token=x_upload_grant,
        content_type=content_type,
        body=b"".join(chunks),
        observed_digest=f"sha256:{hasher.hexdigest()}",
    )
    return {"object_key": object_key, "data_authenticity": "imported"}


@router.post("/imports/{import_id}/upload-complete", response_model=ImportSessionResponse)
def upload_complete(
    import_id: UUID, body: UploadCompleteRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = complete_upload(
        db,
        session=_row(db, ImportSession, import_id, context.workspace_id),
        actor_id=context.principal_id,
        expected_row_version=body.expected_row_version,
        object_key=body.object_key,
        request_id=_request_id(request),
    )
    return p.import_session(row)


@router.post(
    "/imports/{import_id}/finalize", response_model=ImportFinalizationJobResponse, status_code=202
)
def finalize_import(
    import_id: UUID,
    body: ImportFinalizeRequest,
    request: Request,
    context: Ctx,
    db: Db,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    job = begin_finalize(
        db,
        session=_row(db, ImportSession, import_id, context.workspace_id),
        actor_id=context.principal_id,
        expected_row_version=body.expected_row_version,
        request_id=_request_id(request),
        idempotency_key=idempotency_key,
    )
    return p.finalization_job(job)


@router.get("/import-finalization-jobs/{command_id}", response_model=ImportFinalizationJobResponse)
def get_finalization_job(command_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.finalization_job(
        _row(db, ImportFinalizationJobRecord, command_id, context.workspace_id)
    )


@router.post("/imports/{import_id}/cancel", response_model=ImportSessionResponse)
def cancel_import_route(
    import_id: UUID, body: ImportCancelRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = cancel_import(
        db,
        session=_row(db, ImportSession, import_id, context.workspace_id),
        actor_id=context.principal_id,
        expected_row_version=body.expected_row_version,
        reason=body.reason,
        request_id=_request_id(request),
    )
    return p.import_session(row)


@router.get("/import-manifests/{manifest_id}", response_model=ImportManifestResponse)
def get_manifest(manifest_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.manifest(_row(db, ImportManifest, manifest_id, context.workspace_id))


@router.get("/collection-runs", response_model=CursorPage[CollectionRunResponse])
def list_collection_runs(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "collection-runs"
    query = select(CollectionRun).where(CollectionRun.workspace_id == context.workspace_id)
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(
                CollectionRun.created_at < at,
                and_(CollectionRun.created_at == at, CollectionRun.id < row_id),
            )
        )
    fetched = db.scalars(
        query.order_by(CollectionRun.created_at.desc(), CollectionRun.id.desc()).limit(limit + 1)
    ).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.collection_run(db, row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.get("/collection-schedules", response_model=CursorPage[CollectionScheduleResponse])
def list_schedules(
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = "collection-schedules"
    query = select(CollectionSchedule).where(
        CollectionSchedule.workspace_id == context.workspace_id
    )
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(
                CollectionSchedule.next_run_at > at,
                and_(CollectionSchedule.next_run_at == at, CollectionSchedule.id > row_id),
            )
        )
    fetched = db.scalars(
        query.order_by(CollectionSchedule.next_run_at, CollectionSchedule.id).limit(limit + 1)
    ).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.schedule(row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].next_run_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.post("/collection-schedules", response_model=CollectionScheduleResponse, status_code=201)
def create_schedule(
    body: CollectionScheduleCreateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    if str(body.workspace_id) != context.workspace_id:
        raise not_found("Workspace")
    row = configure_schedule(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        payload=body.model_dump(),
        request_id=_request_id(request),
    )
    return p.schedule(row)


@router.patch("/collection-schedules/{schedule_id}", response_model=CollectionScheduleResponse)
def patch_schedule(
    schedule_id: UUID, body: CollectionScheduleUpdateRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = update_schedule(
        db,
        schedule=_row(db, CollectionSchedule, schedule_id, context.workspace_id),
        actor_id=context.principal_id,
        payload=body.model_dump(exclude_none=True),
        request_id=_request_id(request),
    )
    return p.schedule(row)


@router.get("/content-items", response_model=CursorPage[ContentItemResponse])
def list_content(
    context: Ctx,
    db: Db,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    query = select(ContentItem).where(
        ContentItem.workspace_id == context.workspace_id,
        ContentItem.current_version_id.is_not(None),
    )
    if cursor is not None:
        anchor = _row(db, ContentItem, cursor, context.workspace_id)
        if anchor.current_version_id is None:
            raise not_found("Content item cursor")
        query = query.where(
            or_(
                ContentItem.created_at > anchor.created_at,
                and_(
                    ContentItem.created_at == anchor.created_at,
                    ContentItem.id > anchor.id,
                ),
            )
        )
    fetched = db.scalars(
        query.order_by(ContentItem.created_at, ContentItem.id).limit(limit + 1)
    ).all()
    has_more = len(fetched) > limit
    rows = fetched[:limit]
    return {
        "items": [
            {
                "id": row.id,
                "workspace_id": row.workspace_id,
                "source_connection_id": row.source_connection_id,
                "source_item_id": row.source_item_id,
                "canonical_url": row.canonical_url,
                "identity_key": row.identity_key,
                "title": row.title,
                "current_version_id": row.current_version_id,
                "duplicate_cluster_id": row.duplicate_cluster_id,
                "row_version": row.row_version,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "data_authenticity": row.data_authenticity,
            }
            for row in rows
        ],
        "page": {
            "next_cursor": rows[-1].id if has_more and rows else None,
            "has_more": has_more,
        },
    }


@router.get("/content-versions/{version_id}", response_model=ContentVersionResponse)
def get_content_version(version_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    row = _row(db, ContentVersion, version_id, context.workspace_id)
    return p.content_version(db, row)


@router.get("/content-items/{item_id}/versions", response_model=CursorPage[ContentVersionResponse])
def list_content_versions(
    item_id: UUID,
    context: Ctx,
    db: Db,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    item = _row(db, ContentItem, item_id, context.workspace_id)
    query = select(ContentVersion).where(
        ContentVersion.workspace_id == context.workspace_id,
        ContentVersion.content_item_id == item.id,
    )
    if cursor is not None:
        anchor = _row(db, ContentVersion, cursor, context.workspace_id)
        if anchor.content_item_id != item.id:
            raise not_found("Content version cursor")
        query = query.where(
            or_(
                ContentVersion.version_number > anchor.version_number,
                and_(
                    ContentVersion.version_number == anchor.version_number,
                    ContentVersion.id > anchor.id,
                ),
            )
        )
    fetched = db.scalars(
        query.order_by(ContentVersion.version_number, ContentVersion.id).limit(limit + 1)
    ).all()
    has_more = len(fetched) > limit
    rows = fetched[:limit]
    return {
        "items": [p.content_version(db, row) for row in rows],
        "page": {
            "next_cursor": rows[-1].id if has_more and rows else None,
            "has_more": has_more,
        },
    }


@router.get("/audit-logs", response_model=CursorPage[AuditLogResponse])
def list_audit_logs(
    context: Ctx,
    db: Db,
    filters: Annotated[AuditLogFilter, Depends()],
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    if (
        filters.occurred_after is not None
        and filters.occurred_before is not None
        and filters.occurred_after > filters.occurred_before
    ):
        raise ApiError(422, "VALIDATION_ERROR", "occurred_after must precede occurred_before.")
    query = select(AuditLog).where(AuditLog.workspace_id == context.workspace_id)
    if filters.action is not None:
        query = query.where(AuditLog.action == filters.action)
    if filters.target_type is not None:
        query = query.where(AuditLog.target_type == filters.target_type)
    if filters.target_id is not None:
        query = query.where(AuditLog.target_id == str(filters.target_id))
    if filters.actor_id is not None:
        query = query.where(AuditLog.actor_id == str(filters.actor_id))
    if filters.occurred_after is not None:
        query = query.where(AuditLog.occurred_at >= filters.occurred_after)
    if filters.occurred_before is not None:
        query = query.where(AuditLog.occurred_at <= filters.occurred_before)
    if cursor is not None:
        anchor = _row(db, AuditLog, cursor, context.workspace_id)
        query = query.where(
            or_(
                AuditLog.occurred_at < anchor.occurred_at,
                and_(
                    AuditLog.occurred_at == anchor.occurred_at,
                    AuditLog.id < anchor.id,
                ),
            )
        )
    fetched = db.scalars(
        query.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit + 1)
    ).all()
    has_more = len(fetched) > limit
    rows = fetched[:limit]
    return {
        "items": [p.audit_log(row) for row in rows],
        "page": {
            "next_cursor": rows[-1].id if has_more and rows else None,
            "has_more": has_more,
        },
    }


@router.get("/signals", response_model=CursorPage[SignalResponse])
def list_signals(
    context: Ctx,
    db: Db,
    include_dismissed: bool = False,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    scope = f"signals:include_dismissed={str(include_dismissed).lower()}"
    query = select(Signal).where(Signal.workspace_id == context.workspace_id)
    if not include_dismissed:
        query = query.where(Signal.status != "dismissed")
    if cursor is not None:
        at, row_id = _datetime_keyset(cursor, context.workspace_id, scope)
        query = query.where(
            or_(Signal.created_at < at, and_(Signal.created_at == at, Signal.id < row_id))
        )
    fetched = db.scalars(
        query.order_by(Signal.created_at.desc(), Signal.id.desc()).limit(limit + 1)
    ).all()
    rows = fetched[:limit]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=[p.signal(db, row) for row in rows],
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"at": rows[-1].created_at.isoformat(), "id": rows[-1].id} if rows else None,
    )


@router.get("/navigation-summary", response_model=NavigationSummary)
def navigation_summary(context: Ctx, db: Db) -> dict[str, Any]:
    unreviewed = (
        db.scalar(
            select(func.count(Signal.id)).where(
                Signal.workspace_id == context.workspace_id, Signal.status == "new"
            )
        )
        or 0
    )
    needs_input = (
        db.scalar(
            select(func.count(Investigation.id)).where(
                Investigation.workspace_id == context.workspace_id,
                Investigation.status == "needs_input",
            )
        )
        or 0
    )
    draft_briefs = (
        db.scalar(
            select(func.count(DecisionBrief.id)).where(
                DecisionBrief.workspace_id == context.workspace_id,
                DecisionBrief.status == "draft",
            )
        )
        or 0
    )
    degraded = (
        db.scalar(
            select(func.count(SourceConnection.id)).where(
                SourceConnection.workspace_id == context.workspace_id,
                SourceConnection.status.in_(("degraded", "failed", "auth_required")),
            )
        )
        or 0
    )
    return {
        "workspace_id": context.workspace_id,
        "unreviewed_signal_count": unreviewed,
        "investigation_needs_input_count": needs_input,
        "draft_decision_brief_count": draft_briefs,
        "monitoring_health": "degraded" if degraded else "healthy",
        "computed_at": utcnow(),
        "data_authenticity": "human_authored",
    }


@router.get("/sync/bootstrap", response_model=SyncBootstrapResponse)
def sync_bootstrap(context: Ctx, db: Db) -> dict[str, Any]:
    workspace_row = db.get(Workspace, context.workspace_id)
    if workspace_row is None:
        raise not_found("Workspace")
    projects = db.scalars(
        select(Project)
        .where(Project.workspace_id == context.workspace_id)
        .order_by(Project.created_at, Project.id)
    ).all()
    watchlists = db.scalars(
        select(Watchlist)
        .where(Watchlist.workspace_id == context.workspace_id)
        .order_by(Watchlist.created_at, Watchlist.id)
    ).all()
    sources = db.scalars(
        select(SourceConnection)
        .where(SourceConnection.workspace_id == context.workspace_id)
        .order_by(SourceConnection.created_at, SourceConnection.id)
    ).all()
    signals = db.scalars(
        select(Signal)
        .where(Signal.workspace_id == context.workspace_id)
        .order_by(Signal.created_at.desc(), Signal.id.desc())
    ).all()
    investigations = db.scalars(
        select(Investigation)
        .where(Investigation.workspace_id == context.workspace_id)
        .order_by(Investigation.created_at.desc(), Investigation.id.desc())
    ).all()
    briefs = db.scalars(
        select(DecisionBrief)
        .where(DecisionBrief.workspace_id == context.workspace_id)
        .order_by(DecisionBrief.created_at.desc(), DecisionBrief.id.desc())
    ).all()
    return {
        "workspace_id": context.workspace_id,
        "workspace": p.workspace(workspace_row),
        "projects": [p.project(row) for row in projects],
        "watchlists": [p.watchlist(db, row) for row in watchlists],
        "sources": [p.source(db, row) for row in sources],
        "signals": [p.signal(db, row) for row in signals],
        "investigations": [p.investigation(db, row) for row in investigations],
        "decision_briefs": [p.brief(db, row) for row in briefs],
        "cursors": {"run_events": None},
        "computed_at": utcnow(),
        "data_authenticity": workspace_row.data_authenticity,
    }


@router.get("/signals/{signal_id}", response_model=SignalResponse)
def get_signal(signal_id: UUID, context: Ctx, db: Db) -> dict[str, Any]:
    return p.signal(db, _row(db, Signal, signal_id, context.workspace_id))


@router.get("/signals/{signal_id}/evidence", response_model=CursorPage[SignalEvidenceResponse])
def get_signal_evidence(
    signal_id: UUID,
    context: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    _row(db, Signal, signal_id, context.workspace_id)
    scope = f"signal-evidence:{signal_id}"
    query = select(SignalEvidence).where(
        SignalEvidence.signal_id == str(signal_id),
        SignalEvidence.workspace_id == context.workspace_id,
    )
    if cursor is not None:
        values = decode_cursor(cursor=cursor, workspace_id=context.workspace_id, scope=scope)
        try:
            row_id = str(values["id"])
        except KeyError as exc:
            raise ApiError(422, "VALIDATION_ERROR", "The pagination cursor is malformed.") from exc
        query = query.where(SignalEvidence.id > row_id)
    fetched = db.scalars(query.order_by(SignalEvidence.id).limit(limit + 1)).all()
    rows = fetched[:limit]
    items = [
        {
            "signal_id": row.signal_id,
            "content_version_id": row.content_version_id,
            "role": row.role,
            "independence_group_id": row.independence_group_id,
            "contribution": row.contribution,
            "data_authenticity": row.data_authenticity,
        }
        for row in rows
    ]
    return page_payload(
        rows=fetched,
        limit=limit,
        items=items,
        workspace_id=context.workspace_id,
        scope=scope,
        last_keyset={"id": rows[-1].id} if rows else None,
    )


@router.post("/signals/{signal_id}/triage", response_model=SignalResponse)
def triage_signal(
    signal_id: UUID, body: SignalTriageRequest, request: Request, context: Ctx, db: Db
) -> dict[str, Any]:
    row = _row(db, Signal, signal_id, context.workspace_id)
    if row.row_version != body.expected_signal_row_version:
        raise version_conflict(row.id, row.row_version)
    dimensions = dict(row.dimensions_json)
    now = utcnow().isoformat()
    for key, assessment in (("business_impact", body.business_impact), ("urgency", body.urgency)):
        current = {
            "suggested_level": None,
            "suggested_explanation": None,
            "suggestion_origin": "none",
            "suggestion_version": None,
            "confirmed_level": None,
            "confirmed_by": None,
            "confirmed_at": None,
            "version": 0,
            **dict(dimensions.get(key, {})),
        }
        current_version = current.get("version", 0)
        if not isinstance(current_version, int) or isinstance(current_version, bool):
            current_version = 0
        if current_version != assessment.expected_assessment_version:
            raise ApiError(412, "VERSION_CONFLICT", "Signal assessment version changed.")
        current.update(
            {
                "confirmed_level": assessment.confirmed_level.value,
                "confirmed_by": context.principal_id,
                "confirmed_at": now,
                "version": current_version + 1,
            }
        )
        dimensions[key] = current
    impact = dimensions["business_impact"]["confirmed_level"]
    urgency = dimensions["urgency"]["confirmed_level"]
    if "unknown" in {impact, urgency}:
        priority = {
            "level": None,
            "status": "insufficient_input",
            "policy_version": "priority-matrix-v1",
            "explanation": "Unknown cannot enter the priority matrix.",
        }
    else:
        matrix = {
            ("high", "now"): "P0",
            ("high", "this_week"): "P1",
            ("medium", "now"): "P1",
            ("medium", "this_week"): "P2",
        }
        priority = {
            "level": matrix.get((impact, urgency), "P3"),
            "status": "derived",
            "policy_version": "priority-matrix-v1",
            "explanation": "Derived from exact assessment versions.",
        }
    dimensions["priority"] = priority
    row.dimensions_json = dimensions
    row.status = "triaged"
    row.row_version += 1
    audit(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.principal_id,
        action="signal.triaged",
        target_type="Signal",
        target_id=row.id,
        request_id=_request_id(request),
        after={"priority": priority},
    )
    db.commit()
    return p.signal(db, row)


@router.post("/signals/{signal_id}/transitions", response_model=SignalResponse)
def post_signal_transition(
    signal_id: UUID,
    body: SignalTransitionRequest,
    request: Request,
    context: Ctx,
    db: Db,
) -> dict[str, Any]:
    row = transition_signal(
        db,
        signal=_row(db, Signal, signal_id, context.workspace_id),
        actor_id=context.principal_id,
        payload=body.model_dump(mode="json"),
        request_id=_request_id(request),
    )
    return p.signal(db, row)
