"""Execute exactly one persisted Quant Agent decision per worker claim."""

from __future__ import annotations

import os
from dataclasses import dataclass

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentContext,
    QuantAgentDecision,
    QuantToolObservation,
)
from packages.contracts.quant.enums import QuantRunState
from services.api.app.modules.quant.store import QuantFixtureLease, QuantStore

from .context_builder import QuantAgentContextBuilder
from .provider import (
    MockQuantAgentProvider,
    QuantAgentProvider,
)
from .tool_registry import QuantToolExecutionContext, QuantToolRegistry


@dataclass(frozen=True, slots=True)
class QuantAgentStepResult:
    did_work: bool
    terminal: bool


class QuantAgentRunner:
    def __init__(
        self,
        *,
        store: QuantStore,
        provider: QuantAgentProvider,
        tools: QuantToolRegistry | None = None,
        context_builder: QuantAgentContextBuilder | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.tools = tools or QuantToolRegistry()
        self.context_builder = context_builder or QuantAgentContextBuilder(store)

    def run_step(self, *, claim: QuantFixtureLease) -> QuantAgentStepResult:
        run = self.store.get_run(workspace_id=claim.workspace_id, run_id=claim.run_id)
        if run.state in {
            QuantRunState.COMPLETED,
            QuantRunState.FAILED,
            QuantRunState.CANCELLED,
        }:
            self.store.release_agent_claim(claim)
            return QuantAgentStepResult(False, True)

        context = self.context_builder.build(workspace_id=claim.workspace_id, run_id=claim.run_id)
        provider: QuantAgentProvider = (
            MockQuantAgentProvider() if run.provider == "mock" else self.provider
        )
        try:
            decision = (
                self._budget_finish_decision(context)
                if run.agent_iteration >= run.max_agent_iterations
                else provider.decide(context)
            )
        except Exception:
            allow_fallback = os.environ.get(
                "POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK", "true"
            ).lower() not in {"0", "false", "no"}
            self.store.record_agent_provider_failure(
                claim,
                "The model provider could not produce a valid bounded decision.",
                allow_mock_fallback=allow_fallback,
            )
            return QuantAgentStepResult(True, False)

        if not self.store.record_agent_decision(claim, decision):
            self.store.release_agent_claim(claim)
            return QuantAgentStepResult(False, False)
        try:
            observation = self.tools.execute(
                action=decision.action,
                arguments=decision.arguments,
                context=QuantToolExecutionContext(store=self.store, lease=claim),
            )
        except Exception:
            observation = QuantToolObservation(
                action=decision.action,
                success=False,
                safe_summary="The selected Quant tool failed safely.",
                error_code="TOOL_EXECUTION_FAILED",
                retryable=True,
            )
        completed = self.store.complete_agent_step(claim, observation)
        return QuantAgentStepResult(completed, observation.terminal)

    @staticmethod
    def _budget_finish_decision(context: QuantAgentContext) -> QuantAgentDecision:
        candidates = context.candidates
        selected = next(
            (
                candidate.candidate_id
                for candidate in candidates
                if candidate.state == "completed" and candidate.metrics is not None
            ),
            None,
        )
        return QuantAgentDecision(
            action=QuantAgentAction.FINISH_RESEARCH,
            arguments={
                "selected_candidate_id": selected,
                "conclusion": (
                    "The autonomous research loop reached its iteration budget. "
                    "Existing completed experiments were retained; the first completed "
                    "candidate was selected deterministically for holdout evaluation."
                    if selected is not None
                    else "No candidate completed before the iteration budget was reached."
                ),
                "next_step": "stop",
            },
            decision_summary="Finish safely because the Agent iteration budget was reached.",
            expected_result="A final report retaining all completed experiments.",
        )
