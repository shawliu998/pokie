"""Workspace-scoped API for Qurio's simulation-only execution boundary."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from packages.contracts.paper import (
    PaperOrderCancelRequest,
    PaperOrderDraftRequest,
    PaperOrderResponse,
    PaperOrderSubmitRequest,
    PaperReconcileRequest,
    PaperSnapshotResponse,
)
from services.api.app.core.auth import WorkspaceContext, require_owner
from services.api.app.core.errors import ApiError
from services.api.app.modules.paper import PaperTradingStore

router = APIRouter(prefix="/v1/paper")
Ctx = Annotated[WorkspaceContext, Depends(require_owner)]


def _store() -> PaperTradingStore:
    return PaperTradingStore()


def _require_idempotency(value: str | None) -> None:
    if value is None:
        raise ApiError(422, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")


@router.get("/snapshot", response_model=PaperSnapshotResponse)
def get_paper_snapshot(context: Ctx) -> dict[str, Any]:
    return _store().snapshot(
        workspace_id=context.workspace_id,
        principal_id=context.principal_id,
    )


@router.post("/orders/drafts", response_model=PaperOrderResponse, status_code=201)
def create_paper_order_draft(
    body: PaperOrderDraftRequest,
    context: Ctx,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_idempotency(idempotency_key)
    return _store().create_draft(
        workspace_id=context.workspace_id,
        principal_id=context.principal_id,
        body=body,
    )


@router.post("/orders/{order_id}/submit", response_model=PaperOrderResponse)
def submit_paper_order(
    order_id: UUID,
    body: PaperOrderSubmitRequest,
    context: Ctx,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_idempotency(idempotency_key)
    return _store().submit(
        workspace_id=context.workspace_id,
        principal_id=context.principal_id,
        order_id=str(order_id),
        expected_order_row_version=body.expected_order_row_version,
        expected_account_row_version=body.expected_account_row_version,
    )


@router.post("/orders/{order_id}/cancel", response_model=PaperOrderResponse)
def cancel_paper_order(
    order_id: UUID,
    body: PaperOrderCancelRequest,
    context: Ctx,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_idempotency(idempotency_key)
    return _store().cancel(
        workspace_id=context.workspace_id,
        principal_id=context.principal_id,
        order_id=str(order_id),
        expected_order_row_version=body.expected_order_row_version,
    )


@router.post("/reconcile", response_model=PaperSnapshotResponse)
def reconcile_paper_account(
    body: PaperReconcileRequest,
    context: Ctx,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_idempotency(idempotency_key)
    return _store().reconcile(
        workspace_id=context.workspace_id,
        principal_id=context.principal_id,
        expected_account_row_version=body.expected_account_row_version,
    )
