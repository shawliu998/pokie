"""Rebuild compact Quant Agent context from durable repository state."""

from __future__ import annotations

from packages.contracts.quant import QuantAgentContext
from services.api.app.modules.quant.store import QuantStore


class QuantAgentContextBuilder:
    def __init__(self, store: QuantStore) -> None:
        self.store = store

    def build(self, *, workspace_id: str, run_id: str) -> QuantAgentContext:
        return QuantAgentContext.model_validate(
            self.store.agent_context_data(workspace_id=workspace_id, run_id=run_id)
        )
