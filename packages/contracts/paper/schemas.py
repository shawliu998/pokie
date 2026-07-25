"""Closed wire contracts for simulation-only portfolio execution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from packages.contracts.base import ContractModel, NonEmptyString

PaperBroker = Literal["local_simulator"]
PaperOrderSide = Literal["buy", "sell"]
PaperOrderType = Literal["market"]
PaperTimeInForce = Literal["day"]
PaperOrderState = Literal[
    "draft", "submitted", "partially_filled", "filled", "cancelled", "rejected"
]


class PaperAccountResponse(ContractModel):
    account_id: UUID
    workspace_id: UUID
    environment: Literal["paper"]
    broker: PaperBroker
    currency: Literal["USD"]
    status: Literal["active", "unconfigured", "error"]
    cash: Decimal = Field(ge=0, decimal_places=2)
    buying_power: Decimal = Field(ge=0, decimal_places=2)
    equity: Decimal = Field(ge=0, decimal_places=2)
    row_version: int = Field(ge=1)
    last_reconciled_at: AwareDatetime | None = None
    updated_at: AwareDatetime


class PaperPositionResponse(ContractModel):
    symbol: NonEmptyString
    quantity: Decimal = Field(gt=0, decimal_places=8)
    average_entry_price: Decimal = Field(gt=0, decimal_places=8)
    current_price: Decimal = Field(gt=0, decimal_places=8)
    market_value: Decimal = Field(ge=0, decimal_places=2)
    unrealized_pl: Decimal = Field(decimal_places=2)
    updated_at: AwareDatetime


class PaperOrderDraftRequest(ContractModel):
    source_run_id: UUID
    source_candidate_id: NonEmptyString
    side: PaperOrderSide
    quantity: Decimal = Field(gt=0, le=1_000_000, decimal_places=8)
    order_type: Literal["market"] = "market"
    time_in_force: Literal["day"] = "day"
    expected_account_row_version: int = Field(ge=1)


class PaperOrderSubmitRequest(ContractModel):
    expected_order_row_version: int = Field(ge=1)
    expected_account_row_version: int = Field(ge=1)


class PaperOrderCancelRequest(ContractModel):
    expected_order_row_version: int = Field(ge=1)


class PaperReconcileRequest(ContractModel):
    expected_account_row_version: int = Field(ge=1)


class PaperOrderResponse(ContractModel):
    order_id: UUID
    workspace_id: UUID
    environment: Literal["paper"]
    broker: PaperBroker
    state: PaperOrderState
    source_run_id: UUID
    source_candidate_id: NonEmptyString
    source_evidence_digest: NonEmptyString
    symbol: NonEmptyString
    side: PaperOrderSide
    quantity: Decimal = Field(gt=0, decimal_places=8)
    filled_quantity: Decimal = Field(ge=0, decimal_places=8)
    order_type: PaperOrderType
    time_in_force: PaperTimeInForce
    limit_price: Decimal | None = Field(default=None, gt=0, decimal_places=8)
    reference_price: Decimal = Field(gt=0, decimal_places=8)
    estimated_notional: Decimal = Field(gt=0, decimal_places=2)
    average_fill_price: Decimal | None = Field(default=None, gt=0, decimal_places=8)
    external_order_id: NonEmptyString | None = None
    rejection_reason: NonEmptyString | None = None
    row_version: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    submitted_at: AwareDatetime | None = None
    filled_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = None


class PaperFillResponse(ContractModel):
    fill_id: UUID
    order_id: UUID
    workspace_id: UUID
    symbol: NonEmptyString
    side: PaperOrderSide
    quantity: Decimal = Field(gt=0, decimal_places=8)
    price: Decimal = Field(gt=0, decimal_places=8)
    notional: Decimal = Field(gt=0, decimal_places=2)
    occurred_at: AwareDatetime


class PaperSnapshotResponse(ContractModel):
    contract_version: Literal["qurio-paper-v1"] = "qurio-paper-v1"
    environment: Literal["paper"] = "paper"
    account: PaperAccountResponse
    positions: list[PaperPositionResponse]
    orders: list[PaperOrderResponse]
    fills: list[PaperFillResponse]
    legal_actions: list[Literal["create_draft", "submit", "cancel", "reconcile"]]
    generated_at: datetime
