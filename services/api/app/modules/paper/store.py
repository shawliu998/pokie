"""Durable local paper broker with no live-trading code path."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from packages.contracts.paper import (
    PaperOrderDraftRequest,
    PaperOrderResponse,
    PaperSnapshotResponse,
)
from services.api.app.core.errors import invalid_state, not_found, version_conflict
from services.api.app.db.models import PaperTradingState
from services.api.app.db.session import get_session_factory, set_rls_context
from services.api.app.modules.quant.snapshot import quant_agent_workspace_snapshot

MONEY = Decimal("0.01")
QUANTITY = Decimal("0.00000001")
STARTING_CASH = Decimal("100000.00")


def _now() -> datetime:
    return datetime.now(UTC)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY, rounding=ROUND_HALF_UP)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


class PaperTradingStore:
    """One workspace-scoped paper account and its retained execution history."""

    def __init__(self) -> None:
        self._session_factory = get_session_factory()

    @staticmethod
    def _initial_state(workspace_id: str) -> dict[str, Any]:
        now = _iso()
        return {
            "account": {
                "account_id": str(uuid4()),
                "workspace_id": workspace_id,
                "environment": "paper",
                "broker": "local_simulator",
                "currency": "USD",
                "status": "active",
                "cash": str(STARTING_CASH),
                "buying_power": str(STARTING_CASH),
                "equity": str(STARTING_CASH),
                "row_version": 1,
                "last_reconciled_at": None,
                "updated_at": now,
            },
            "positions": [],
            "orders": [],
            "fills": [],
        }

    def _state_row(self, *, workspace_id: str, principal_id: str) -> PaperTradingState:
        with self._session_factory() as db:
            set_rls_context(db, workspace_id, principal_id)
            row = db.get(PaperTradingState, workspace_id)
            if row is None:
                row = PaperTradingState(
                    workspace_id=workspace_id,
                    contract_version="qurio-paper-v1",
                    state_json=self._initial_state(workspace_id),
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            db.expunge(row)
            return row

    def _mutate(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        mutation: Any,
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            set_rls_context(db, workspace_id, principal_id)
            row = db.scalar(
                select(PaperTradingState)
                .where(PaperTradingState.workspace_id == workspace_id)
                .with_for_update()
            )
            if row is None:
                row = PaperTradingState(
                    workspace_id=workspace_id,
                    contract_version="qurio-paper-v1",
                    state_json=self._initial_state(workspace_id),
                )
                db.add(row)
                db.flush()
            state = json.loads(json.dumps(row.state_json))
            mutation(state)
            row.state_json = state
            row.row_version += 1
            row.updated_at = _now()
            db.commit()
            return state

    def snapshot(self, *, workspace_id: str, principal_id: str) -> dict[str, Any]:
        row = self._state_row(workspace_id=workspace_id, principal_id=principal_id)
        state = json.loads(json.dumps(row.state_json))
        return PaperSnapshotResponse(
            account=state["account"],
            positions=state["positions"],
            orders=list(reversed(state["orders"])),
            fills=list(reversed(state["fills"])),
            legal_actions=["create_draft", "submit", "cancel", "reconcile"],
            generated_at=_now(),
        ).model_dump(mode="json")

    @staticmethod
    def _research_source(
        *, workspace_id: str, run_id: str, candidate_id: str
    ) -> tuple[str, Decimal, str]:
        snapshot = quant_agent_workspace_snapshot(workspace_id=workspace_id, run_id=run_id)
        if snapshot is None:
            raise not_found("Research Run")
        if snapshot["run"]["state"] != "completed":
            raise invalid_state("Paper orders require a completed retained Research Run.")
        candidate = next(
            (item for item in snapshot["candidates"] if item["id"] == candidate_id),
            None,
        )
        if candidate is None:
            raise not_found("Research candidate")
        report = snapshot.get("report") or {}
        selection_decision = report.get("selectionDecision") or {}
        generalization = report.get("generalization") or {}
        selected_candidate_id = (
            report.get("selectedCandidateId")
            or selection_decision.get("selectedCandidateId")
            or generalization.get("selectedCandidateId")
        )
        if selected_candidate_id != candidate_id:
            raise invalid_state(
                "Paper orders require the candidate retained by the final Research Report."
            )
        bars = snapshot.get("bars") or []
        if not bars or not isinstance(bars[-1].get("close"), int | float):
            raise invalid_state("The retained Run has no reference market close.")
        symbol = str(snapshot["scope"]["symbol"])
        reference_price = _decimal(bars[-1]["close"])
        evidence = {
            "run_id": run_id,
            "candidate_id": candidate_id,
            "dataset_digest": snapshot["dataset"]["digest"],
            "reference_date": bars[-1]["date"],
            "reference_price": str(reference_price),
        }
        digest = "sha256:" + hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return symbol, reference_price, digest

    def create_draft(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        body: PaperOrderDraftRequest,
    ) -> dict[str, Any]:
        symbol, reference_price, evidence_digest = self._research_source(
            workspace_id=workspace_id,
            run_id=str(body.source_run_id),
            candidate_id=body.source_candidate_id,
        )
        created: dict[str, Any] = {}

        def mutation(state: dict[str, Any]) -> None:
            account = state["account"]
            if account["row_version"] != body.expected_account_row_version:
                raise version_conflict(account["account_id"], account["row_version"])
            now = _iso()
            execution_price = reference_price
            order = {
                "order_id": str(uuid4()),
                "workspace_id": workspace_id,
                "environment": "paper",
                "broker": "local_simulator",
                "state": "draft",
                "source_run_id": str(body.source_run_id),
                "source_candidate_id": body.source_candidate_id,
                "source_evidence_digest": evidence_digest,
                "symbol": symbol,
                "side": body.side,
                "quantity": str(_quantity(body.quantity)),
                "filled_quantity": "0",
                "order_type": body.order_type,
                "time_in_force": body.time_in_force,
                "limit_price": None,
                "reference_price": str(reference_price),
                "estimated_notional": str(_money(execution_price * body.quantity)),
                "average_fill_price": None,
                "external_order_id": None,
                "rejection_reason": None,
                "row_version": 1,
                "created_at": now,
                "updated_at": now,
                "submitted_at": None,
                "filled_at": None,
                "cancelled_at": None,
            }
            state["orders"].append(order)
            created.update(order)

        self._mutate(
            workspace_id=workspace_id,
            principal_id=principal_id,
            mutation=mutation,
        )
        return PaperOrderResponse.model_validate(created).model_dump(mode="json")

    @staticmethod
    def _find_order(state: dict[str, Any], order_id: str) -> dict[str, Any]:
        order = next(
            (item for item in state["orders"] if item["order_id"] == order_id),
            None,
        )
        if order is None:
            raise not_found("Paper order")
        return order

    def submit(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        order_id: str,
        expected_order_row_version: int,
        expected_account_row_version: int,
    ) -> dict[str, Any]:
        submitted: dict[str, Any] = {}

        def mutation(state: dict[str, Any]) -> None:
            account = state["account"]
            order = self._find_order(state, order_id)
            if order["row_version"] != expected_order_row_version:
                raise version_conflict(order_id, order["row_version"])
            if account["row_version"] != expected_account_row_version:
                raise version_conflict(account["account_id"], account["row_version"])
            if order["state"] != "draft":
                raise invalid_state("Only a draft paper order can be submitted.")
            price = _decimal(order["limit_price"] or order["reference_price"])
            quantity = _decimal(order["quantity"])
            notional = _money(price * quantity)
            positions = state["positions"]
            position = next(
                (item for item in positions if item["symbol"] == order["symbol"]),
                None,
            )
            cash = _decimal(account["cash"])
            if order["side"] == "buy":
                if notional > cash:
                    raise invalid_state("Paper account buying power is insufficient.")
                cash -= notional
                if position is None:
                    position = {
                        "symbol": order["symbol"],
                        "quantity": str(quantity),
                        "average_entry_price": str(price),
                        "current_price": str(price),
                        "market_value": str(notional),
                        "unrealized_pl": "0.00",
                        "updated_at": _iso(),
                    }
                    positions.append(position)
                else:
                    old_quantity = _decimal(position["quantity"])
                    old_cost = old_quantity * _decimal(position["average_entry_price"])
                    new_quantity = old_quantity + quantity
                    position["quantity"] = str(_quantity(new_quantity))
                    position["average_entry_price"] = str(
                        _quantity((old_cost + notional) / new_quantity)
                    )
                    position["current_price"] = str(price)
                    position["market_value"] = str(_money(new_quantity * price))
                    position["unrealized_pl"] = str(
                        _money(new_quantity * (price - _decimal(position["average_entry_price"])))
                    )
                    position["updated_at"] = _iso()
            else:
                if position is None or _decimal(position["quantity"]) < quantity:
                    raise invalid_state("Paper position quantity is insufficient.")
                cash += notional
                remaining = _decimal(position["quantity"]) - quantity
                if remaining == 0:
                    positions.remove(position)
                else:
                    position["quantity"] = str(_quantity(remaining))
                    position["current_price"] = str(price)
                    position["market_value"] = str(_money(remaining * price))
                    position["unrealized_pl"] = str(
                        _money(remaining * (price - _decimal(position["average_entry_price"])))
                    )
                    position["updated_at"] = _iso()
            now = _iso()
            account["cash"] = str(_money(cash))
            account["buying_power"] = account["cash"]
            account["equity"] = str(
                _money(cash + sum(_decimal(item["market_value"]) for item in positions))
            )
            account["row_version"] += 1
            account["updated_at"] = now
            order.update(
                {
                    "state": "filled",
                    "filled_quantity": order["quantity"],
                    "average_fill_price": str(price),
                    "row_version": order["row_version"] + 1,
                    "updated_at": now,
                    "submitted_at": now,
                    "filled_at": now,
                }
            )
            state["fills"].append(
                {
                    "fill_id": str(uuid4()),
                    "order_id": order_id,
                    "workspace_id": workspace_id,
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "quantity": order["quantity"],
                    "price": str(price),
                    "notional": str(notional),
                    "occurred_at": now,
                }
            )
            submitted.update(order)

        self._mutate(
            workspace_id=workspace_id,
            principal_id=principal_id,
            mutation=mutation,
        )
        return PaperOrderResponse.model_validate(submitted).model_dump(mode="json")

    def cancel(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        order_id: str,
        expected_order_row_version: int,
    ) -> dict[str, Any]:
        cancelled: dict[str, Any] = {}

        def mutation(state: dict[str, Any]) -> None:
            order = self._find_order(state, order_id)
            if order["row_version"] != expected_order_row_version:
                raise version_conflict(order_id, order["row_version"])
            if order["state"] != "draft":
                raise invalid_state("Only a draft paper order can be cancelled.")
            now = _iso()
            order.update(
                {
                    "state": "cancelled",
                    "row_version": order["row_version"] + 1,
                    "updated_at": now,
                    "cancelled_at": now,
                }
            )
            cancelled.update(order)

        self._mutate(
            workspace_id=workspace_id,
            principal_id=principal_id,
            mutation=mutation,
        )
        return PaperOrderResponse.model_validate(cancelled).model_dump(mode="json")

    def reconcile(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        expected_account_row_version: int,
    ) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            account = state["account"]
            if account["row_version"] != expected_account_row_version:
                raise version_conflict(account["account_id"], account["row_version"])
            account["equity"] = str(
                _money(
                    _decimal(account["cash"])
                    + sum(_decimal(item["market_value"]) for item in state["positions"])
                )
            )
            account["buying_power"] = account["cash"]
            account["row_version"] += 1
            account["last_reconciled_at"] = _iso()
            account["updated_at"] = account["last_reconciled_at"]

        self._mutate(
            workspace_id=workspace_id,
            principal_id=principal_id,
            mutation=mutation,
        )
        return self.snapshot(workspace_id=workspace_id, principal_id=principal_id)
