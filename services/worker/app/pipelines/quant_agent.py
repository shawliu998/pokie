"""Incremental autonomous Quant Agent worker pipeline."""

from __future__ import annotations

from datetime import timedelta

from services.api.app.modules.quant.store import QuantStore, get_quant_store
from services.worker.app.quant_agent.provider import (
    QuantAgentProvider,
    load_quant_agent_provider,
)
from services.worker.app.quant_agent.runner import QuantAgentRunner


class QuantAgentPipeline:
    def __init__(
        self,
        store: QuantStore | None = None,
        provider: QuantAgentProvider | None = None,
    ) -> None:
        self.store = store or get_quant_store()
        self.provider = provider or load_quant_agent_provider()

    def run_once(
        self,
        *,
        workspace_id: str | None = None,
        worker_id: str = "pokiequant-agent-worker",
        lease_for: timedelta = timedelta(seconds=120),
    ) -> bool:
        workspace_ids = [workspace_id] if workspace_id else self.store.workspace_ids()
        for candidate_workspace_id in workspace_ids:
            claim = self.store.claim_agent_run(
                workspace_id=candidate_workspace_id,
                worker_id=worker_id,
                lease_for=lease_for,
            )
            if claim is None or not self.store.heartbeat_fixture_run(claim, lease_for):
                continue
            return (
                QuantAgentRunner(store=self.store, provider=self.provider)
                .run_step(claim=claim)
                .did_work
            )
        return False


def run_quant_agent_once(
    store: QuantStore | None = None,
    *,
    provider: QuantAgentProvider | None = None,
    workspace_id: str | None = None,
    worker_id: str = "pokiequant-agent-worker",
    lease_for: timedelta = timedelta(seconds=120),
) -> bool:
    return QuantAgentPipeline(store, provider).run_once(
        workspace_id=workspace_id,
        worker_id=worker_id,
        lease_for=lease_for,
    )
