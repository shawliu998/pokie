"""Deterministic quant fixture runner."""

from __future__ import annotations

import os
from datetime import timedelta

from packages.domain.quant import QuantFixtureRunState
from services.api.app.modules.quant.store import QuantStore, get_quant_store

DEFAULT_ENV_VAR = "POKIEQUANT_E2E_RUN_STATE"


def _fixture_state(value: str | None) -> str:
    raw = value or os.environ.get(DEFAULT_ENV_VAR, QuantFixtureRunState.COMPLETED.value)
    try:
        return QuantFixtureRunState(raw).value
    except ValueError as exc:  # pragma: no cover - validated by tests
        raise ValueError(
            f"{DEFAULT_ENV_VAR} must be one of: "
            + ", ".join(state.value for state in QuantFixtureRunState)
        ) from exc


class QuantFixtureRunner:
    def __init__(self, store: QuantStore | None = None) -> None:
        self.store = store or get_quant_store()

    def run_once(
        self,
        *,
        workspace_id: str | None = None,
        fixture_state: str | None = None,
        worker_id: str = "pokiequant-fixture-worker",
        lease_for: timedelta = timedelta(seconds=120),
    ) -> bool:
        state = _fixture_state(fixture_state)
        if workspace_id is not None:
            lease = self.store.claim_fixture_run(
                workspace_id=workspace_id,
                worker_id=worker_id,
                lease_for=lease_for,
            )
            if lease is None or not self.store.heartbeat_fixture_run(lease):
                return False
            return self.store.execute_fixture_claim(lease, fixture_state=state)
        for candidate_workspace_id in self.store.workspace_ids():
            lease = self.store.claim_fixture_run(
                workspace_id=candidate_workspace_id,
                worker_id=worker_id,
                lease_for=lease_for,
            )
            if (
                lease is not None
                and self.store.heartbeat_fixture_run(lease)
                and self.store.execute_fixture_claim(lease, fixture_state=state)
            ):
                return True
        return False


def run_quant_fixture_once(
    store: QuantStore | None = None,
    *,
    workspace_id: str | None = None,
    fixture_state: str | None = None,
    worker_id: str = "pokiequant-fixture-worker",
    lease_for: timedelta = timedelta(seconds=120),
) -> bool:
    return QuantFixtureRunner(store).run_once(
        workspace_id=workspace_id,
        fixture_state=fixture_state,
        worker_id=worker_id,
        lease_for=lease_for,
    )
