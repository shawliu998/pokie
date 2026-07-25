from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from packages.contracts.openapi import openapi_components
from services.api.app.api.routes_core import router as core_router
from services.api.app.api.routes_paper import router as paper_router
from services.api.app.api.routes_quant import router as quant_router
from services.api.app.api.routes_research import router as research_router
from services.api.app.core.auth import authenticate_authorization
from services.api.app.core.config import get_settings
from services.api.app.core.errors import ApiError, api_error_handler
from services.api.app.core.object_store import get_object_store
from services.api.app.db.models import Base, IdempotencyRecord
from services.api.app.db.session import get_engine, get_session_factory, set_rls_context

NIL_UUID = "00000000-0000-0000-0000-000000000000"
IDEMPOTENCY_LEASE_SECONDS = 300
IDEMPOTENCY_WAIT_SECONDS = 60


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    if settings.environment == "production":
        if settings.service_role != "api":
            raise RuntimeError("The FastAPI process requires GLINT_SERVICE_ROLE=api")
        get_object_store()
        with get_engine().connect() as connection:
            role = connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            if role.current_user != "glint_api" or role.rolsuper or role.rolbypassrls:
                raise RuntimeError(
                    "Production API must connect as non-superuser, non-BYPASSRLS glint_api"
                )
    if settings.create_schema_on_startup:
        if settings.environment == "production":
            raise RuntimeError("Production schema changes require Alembic migrations")
        Base.metadata.create_all(get_engine())
    yield


app = FastAPI(
    title="Glint API",
    version="1.0.0-phase1",
    description="Workspace-scoped Phase 1 modular monolith contracts.",
    lifespan=lifespan,
)

settings = get_settings()
if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "Last-Event-ID",
            "X-Request-ID",
            "X-Upload-Grant",
            "X-Workspace-ID",
        ],
        expose_headers=["X-Request-ID", "X-Upload-Grant", "Idempotency-Replayed"],
    )


def _json_error(
    status: int, code: str, message: str, request_id: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
                "details": details or {},
            }
        },
        headers={"X-Request-ID": request_id},
    )


def _idempotency_predicate(
    *, workspace_scope: str, principal_id: str, route: str, key: str
) -> tuple[Any, ...]:
    return (
        IdempotencyRecord.workspace_scope == workspace_scope,
        IdempotencyRecord.principal_id == principal_id,
        IdempotencyRecord.route == route,
        IdempotencyRecord.idempotency_key == key,
    )


async def _claim_idempotency_key(
    *,
    workspace_scope: str,
    principal_id: str,
    route: str,
    key: str,
    fingerprint: str,
    request_id: str,
) -> tuple[str | None, Response | None]:
    factory = get_session_factory()
    owner_token = str(uuid4())
    now = datetime.now(UTC)
    with factory() as db:
        set_rls_context(db, workspace_scope, principal_id)
        db.add(
            IdempotencyRecord(
                workspace_scope=workspace_scope,
                principal_id=principal_id,
                route=route,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                state="pending",
                owner_token=owner_token,
                lease_expires_at=now + timedelta(seconds=IDEMPOTENCY_LEASE_SECONDS),
            )
        )
        try:
            db.commit()
            return owner_token, None
        except IntegrityError:
            db.rollback()

    deadline = monotonic() + IDEMPOTENCY_WAIT_SECONDS
    predicate = _idempotency_predicate(
        workspace_scope=workspace_scope,
        principal_id=principal_id,
        route=route,
        key=key,
    )
    while True:
        now = datetime.now(UTC)
        with factory() as db:
            set_rls_context(db, workspace_scope, principal_id)
            existing = db.scalar(select(IdempotencyRecord).where(*predicate))
            if existing is None:
                await asyncio.sleep(0.02)
                continue
            if existing.request_fingerprint != fingerprint:
                return None, _json_error(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "The Idempotency-Key was reused with a different request.",
                    request_id,
                )
            if (
                existing.state == "completed"
                and existing.response_status is not None
                and existing.response_json is not None
            ):
                return None, JSONResponse(
                    status_code=existing.response_status,
                    content=existing.response_json,
                    headers={"X-Request-ID": request_id, "Idempotency-Replayed": "true"},
                )
            if existing.lease_expires_at <= now:
                claimed = db.scalar(
                    update(IdempotencyRecord)
                    .where(
                        IdempotencyRecord.id == existing.id,
                        IdempotencyRecord.state == "pending",
                        IdempotencyRecord.lease_expires_at <= now,
                    )
                    .values(
                        owner_token=owner_token,
                        lease_expires_at=now + timedelta(seconds=IDEMPOTENCY_LEASE_SECONDS),
                    )
                    .returning(IdempotencyRecord.id)
                )
                if claimed is not None:
                    db.commit()
                    return owner_token, None
                db.rollback()
        if monotonic() >= deadline:
            return None, _json_error(
                409,
                "IDEMPOTENCY_CONFLICT",
                "The matching request is still in progress.",
                request_id,
            )
        await asyncio.sleep(0.02)


def _abandon_idempotency_key(
    *,
    workspace_scope: str,
    principal_id: str,
    route: str,
    key: str,
    owner_token: str,
) -> None:
    factory = get_session_factory()
    with factory() as db:
        set_rls_context(db, workspace_scope, principal_id)
        db.execute(
            delete(IdempotencyRecord).where(
                *_idempotency_predicate(
                    workspace_scope=workspace_scope,
                    principal_id=principal_id,
                    route=route,
                    key=key,
                ),
                IdempotencyRecord.state == "pending",
                IdempotencyRecord.owner_token == owner_token,
            )
        )
        db.commit()


@app.middleware("http")
async def request_policy(request: Request, call_next: Any) -> Response:
    request_id_header = request.headers.get("X-Request-ID")
    try:
        request_id = str(UUID(request_id_header)) if request_id_header else str(uuid4())
    except ValueError:
        request_id = str(uuid4())
    request.state.request_id = request_id
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    # This preview endpoint is a deterministic renderer over retained records;
    # it must remain usable when the database is opened read-only for evidence
    # reopen, so it bypasses idempotency claim/update writes while keeping auth
    # and workspace isolation in the route dependencies.
    if request.method == "POST" and request.url.path == "/v1/quant/strategy-report-exports/preview":
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    if request.method == "PUT" and request.url.path.endswith("/object"):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    key = request.headers.get("Idempotency-Key")
    try:
        key = str(UUID(key)) if key else None
    except ValueError:
        return _json_error(422, "VALIDATION_ERROR", "Idempotency-Key must be a UUID.", request_id)
    if key is None:
        return _json_error(422, "VALIDATION_ERROR", "Idempotency-Key is required.", request_id)
    body = await request.body()
    fingerprint = (
        "sha256:"
        + hashlib.sha256(
            request.method.encode()
            + b"\0"
            + request.url.path.encode()
            + b"\0"
            + request.url.query.encode()
            + b"\0"
            + body
        ).hexdigest()
    )
    try:
        principal_id = authenticate_authorization(request.headers.get("Authorization")).user_id
    except ApiError as error:
        return _json_error(
            error.status_code,
            error.code,
            error.message,
            request_id,
            error.details,
        )
    workspace_scope = request.headers.get("X-Workspace-ID", NIL_UUID)
    try:
        workspace_scope = str(UUID(workspace_scope))
    except ValueError:
        workspace_scope = NIL_UUID
    route = f"{request.method} {request.url.path}"
    owner_token, replay = await _claim_idempotency_key(
        workspace_scope=workspace_scope,
        principal_id=principal_id,
        route=route,
        key=key,
        fingerprint=fingerprint,
        request_id=request_id,
    )
    if replay is not None:
        return replay
    if owner_token is None:
        return _json_error(
            500, "INVALID_STATE", "Idempotency ownership was not established.", request_id
        )
    try:
        response = await call_next(request)
    except Exception:
        _abandon_idempotency_key(
            workspace_scope=workspace_scope,
            principal_id=principal_id,
            route=route,
            key=key,
            owner_token=owner_token,
        )
        raise
    chunks = [chunk async for chunk in response.body_iterator]
    response_body = b"".join(chunks)
    headers = dict(response.headers)
    headers["X-Request-ID"] = request_id
    rebuilt = Response(
        content=response_body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
    )
    if response.headers.get("content-type", "").startswith("application/json"):
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError:
            return rebuilt
        factory = get_session_factory()
        with factory() as db:
            set_rls_context(db, workspace_scope, principal_id)
            db.execute(
                update(IdempotencyRecord)
                .where(
                    *_idempotency_predicate(
                        workspace_scope=workspace_scope,
                        principal_id=principal_id,
                        route=route,
                        key=key,
                    ),
                    IdempotencyRecord.state == "pending",
                    IdempotencyRecord.owner_token == owner_token,
                )
                .values(
                    state="completed",
                    response_status=response.status_code,
                    response_json=payload,
                    lease_expires_at=datetime.now(UTC),
                )
            )
            db.commit()
    return rebuilt


@app.exception_handler(ApiError)
async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
    return await api_error_handler(request, error)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    safe_errors = [
        {"type": item["type"], "loc": list(item["loc"]), "msg": item["msg"]}
        for item in error.errors()
    ]
    return _json_error(
        422,
        "VALIDATION_ERROR",
        "Request validation failed.",
        request.state.request_id,
        {"errors": safe_errors},
    )


@app.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


# These module routers already own their complete ``/v1`` prefixes and have no
# router-level lifespan handlers. Register their concrete routes so route
# discovery, OpenAPI generation, and older DTO generators all see one stable
# flat application surface across FastAPI releases.
app.router.routes.extend(core_router.routes)
app.router.routes.extend(paper_router.routes)
app.router.routes.extend(quant_router.routes)
app.router.routes.extend(research_router.routes)


def glint_openapi() -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    document = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    components = document.setdefault("components", {}).setdefault("schemas", {})
    components.update(openapi_components()["components"]["schemas"])
    app.openapi_schema = document
    return document


app.openapi = glint_openapi
