"""Execute exactly one persisted Quant Agent decision per worker claim."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentContext,
    QuantAgentDecision,
    QuantRepairMemory,
    QuantRepairMemoryReuseReceipt,
    QuantToolObservation,
    QuantToolRepair,
)
from packages.contracts.quant.enums import QuantRunState
from packages.domain.canonical import canonical_digest
from services.api.app.modules.quant.store import QuantFixtureLease, QuantStore

from .context_builder import QuantAgentContextBuilder
from .provider import (
    MockQuantAgentProvider,
    QuantAgentProvider,
    QuantAgentProviderError,
    allow_mock_fallback,
    final_research_selection,
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
            if run.provider != "mock" and isinstance(provider, MockQuantAgentProvider):
                raise QuantAgentProviderError(
                    "A non-Mock run cannot execute with the Mock provider."
                )
            decision = self._initial_comparison_decision(context) or (
                self._budget_finish_decision(context)
                if self._must_use_budget_controller(
                    agent_iteration=run.agent_iteration,
                    max_agent_iterations=run.max_agent_iterations,
                    used_experiments=run.used_experiments,
                    max_experiments=run.max_experiments,
                    context=context,
                )
                else provider.decide(context)
            )
        except Exception:
            try:
                allow_fallback = allow_mock_fallback()
            except QuantAgentProviderError:
                allow_fallback = False
            self.store.record_agent_provider_failure(
                claim,
                "The model provider could not produce a valid bounded decision.",
                allow_mock_fallback=allow_fallback,
            )
            return QuantAgentStepResult(True, False)

        pending_repair = self.store.latest_invalid_tool_repair(
            workspace_id=claim.workspace_id,
            run_id=claim.run_id,
        )
        rejected_arguments: dict[str, object] | None = None
        if pending_repair is not None:
            rejected_arguments = self.store.rejected_arguments_for_repair(
                workspace_id=claim.workspace_id,
                run_id=claim.run_id,
                call_fingerprint=pending_repair.call_fingerprint,
            )
        if pending_repair is not None and not self._applies_tool_repair(
            decision=decision,
            repair=pending_repair,
            rejected_arguments=rejected_arguments,
        ):
            failed = self.store.record_agent_contract_repair_exhausted(
                claim,
                rejected_action=pending_repair.action.value,
                attempted_action=decision.action.value,
                rejected_call_fingerprint=pending_repair.call_fingerprint,
                attempted_call_fingerprint=canonical_digest(
                    {
                        "action": decision.action.value,
                        "arguments": decision.arguments,
                    }
                ),
            )
            if not failed:
                self.store.release_agent_claim(claim)
            return QuantAgentStepResult(failed, failed)

        reuse_receipt: QuantRepairMemoryReuseReceipt | None = None
        if pending_repair is None:
            decision, reuse_receipt = self._reuse_verified_repair(
                decision=decision,
                memory=self.store.repair_memory_for_run(
                    workspace_id=claim.workspace_id,
                    run_id=claim.run_id,
                ),
            )

        if not self.store.record_agent_decision(
            claim,
            decision,
            reuse_receipt=reuse_receipt,
        ):
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
    def _argument_at_path(arguments: dict[str, object], path: str) -> tuple[bool, object]:
        if path == "$":
            return True, arguments
        current: object = arguments
        for segment in path.split("."):
            if not isinstance(current, dict) or segment not in current:
                return False, None
            current = current[segment]
        return True, current

    @classmethod
    def _applies_tool_repair(
        cls,
        *,
        decision: QuantAgentDecision,
        repair: QuantToolRepair,
        rejected_arguments: dict[str, object] | None = None,
    ) -> bool:
        """Require a substantive field repair before the same action may run again.

        For action-only repairs (e.g. replan_decision.action), every unlisted
        argument must remain semantically identical to the rejected call.
        """

        if decision.action != repair.action:
            return False
        if cls._is_action_only_repair(repair) and (
            rejected_arguments is None
            or not cls._arguments_match_except_path(
                decision.arguments,
                rejected_arguments,
                path=repair.violations[0].path,
            )
        ):
            return False
        for violation in repair.violations:
            present, value = cls._argument_at_path(decision.arguments, violation.path)
            if violation.required_change == "remove":
                if present:
                    return False
            elif violation.required_change == "supply":
                if not present:
                    return False
                if violation.allowed_values and str(value) not in violation.allowed_values:
                    return False
            else:
                if not present:
                    return False
                if violation.allowed_values and str(value) not in violation.allowed_values:
                    return False
                if (
                    violation.rejected_value_fingerprint is not None
                    and canonical_digest(value) == violation.rejected_value_fingerprint
                ):
                    return False
        return True

    @staticmethod
    def _is_action_only_repair(repair: QuantToolRepair) -> bool:
        """Detect the closed replan-relation repair without depending on prose."""

        return (
            len(repair.violations) == 1
            and repair.violations[0].path == "replan_decision.action"
            and repair.violations[0].required_change == "replace"
            and len(repair.violations[0].allowed_values) == 1
            and repair.violations[0].allowed_values[0]
            in {"refine_parameters", "switch_approved_family"}
            and repair.violations[0].rejected_value_fingerprint is not None
        )

    @staticmethod
    def _arguments_match_except_path(
        current: dict[str, object],
        previous: dict[str, object],
        *,
        path: str,
    ) -> bool:
        """Return True when current and previous are identical outside of `path`."""

        if path == "$":
            return False
        parts = path.split(".")

        def walk(left: object, right: object, remaining: list[str]) -> bool:
            if not remaining:
                return True
            if not isinstance(left, dict) or not isinstance(right, dict):
                return canonical_digest(left) == canonical_digest(right)
            if set(left.keys()) != set(right.keys()):
                return False
            key = remaining[0]
            for k, left_value in left.items():
                if k == key:
                    if not walk(left_value, right[k], remaining[1:]):
                        return False
                elif canonical_digest(left_value) != canonical_digest(right[k]):
                    return False
            return True

        return walk(current, previous, parts)

    @staticmethod
    def _remove_argument_path(arguments: dict[str, object], path: str) -> bool:
        if path == "$":
            return False
        parts = path.split(".")
        current: object = arguments
        for segment in parts[:-1]:
            if not isinstance(current, dict):
                return False
            current = current.get(segment)
        if not isinstance(current, dict) or parts[-1] not in current:
            return False
        del current[parts[-1]]
        return True

    def _reuse_verified_repair(
        self,
        *,
        decision: QuantAgentDecision,
        memory: QuantRepairMemory | None,
    ) -> tuple[QuantAgentDecision, QuantRepairMemoryReuseReceipt | None]:
        """Apply only an exact current-schema, remove-only pinned repair."""

        if memory is None or not memory.entries:
            return decision, None
        repair = self.tools.preflight_repair(
            action=decision.action,
            arguments=decision.arguments,
        )
        if repair is None or any(item.required_change != "remove" for item in repair.violations):
            return decision, None
        remove_paths = sorted(item.path for item in repair.violations)
        identity = self.tools.identity(decision.action)
        entry = next(
            (
                item
                for item in memory.entries
                if item.action == decision.action
                and item.failed_call_fingerprint == repair.call_fingerprint
                and item.tool == identity
                and item.remove_paths == remove_paths
            ),
            None,
        )
        if entry is None:
            return decision, None
        corrected_arguments = deepcopy(decision.arguments)
        if not all(self._remove_argument_path(corrected_arguments, path) for path in remove_paths):
            return decision, None
        try:
            normalized_arguments = self.tools.normalize_arguments(
                action=decision.action,
                arguments=corrected_arguments,
            )
        except Exception:
            return decision, None
        corrected_fingerprint = canonical_digest(
            {
                "action": decision.action.value,
                "arguments": normalized_arguments,
            }
        )
        receipt = QuantRepairMemoryReuseReceipt(
            source_trace_ids=entry.source_trace_ids,
            action=decision.action,
            original_call_fingerprint=repair.call_fingerprint,
            corrected_call_fingerprint=corrected_fingerprint,
            changed_paths=remove_paths,
        )
        return (
            decision.model_copy(update={"arguments": normalized_arguments}),
            receipt,
        )

    @classmethod
    def _must_use_budget_controller(
        cls,
        *,
        agent_iteration: int,
        max_agent_iterations: int,
        used_experiments: int,
        max_experiments: int,
        context: QuantAgentContext,
    ) -> bool:
        """Reserve the bounded actions required for an honest terminal transition."""

        remaining_iterations = max(0, max_agent_iterations - agent_iteration)
        if agent_iteration >= max_agent_iterations or remaining_iterations <= 1:
            return True
        if used_experiments >= max_experiments and any(
            candidate.state == "failed" for candidate in context.candidates
        ):
            return True
        if (
            used_experiments >= max_experiments
            and remaining_iterations <= 2
            and any(candidate.state != "completed" for candidate in context.candidates)
        ):
            return True
        return bool(
            remaining_iterations <= 2
            and cls._budget_finish_decision(context).action is QuantAgentAction.COMPARE_CANDIDATES
        )

    @staticmethod
    def _initial_comparison_decision(
        context: QuantAgentContext,
    ) -> QuantAgentDecision | None:
        """Persist the mandatory A/B comparison before asking a provider to replan."""

        base_completed = [
            candidate
            for candidate in context.candidates
            if (
                candidate.state == "completed"
                and candidate.metrics is not None
                and candidate.template != "fixture"
                and candidate.feedback_artifact_id is None
            )
        ]
        has_pending = any(
            candidate.state in {"created", "running", "repairing"}
            for candidate in context.candidates
        )
        if (
            context.budget.max_experiments != 3
            or len(base_completed) != 2
            or has_pending
            or context.iteration_feedback is not None
            or context.budget.remaining_experiments <= 0
        ):
            return None
        return QuantAgentDecision(
            action=QuantAgentAction.COMPARE_CANDIDATES,
            arguments={},
            decision_summary=(
                "Compare the two completed base candidates before the bounded replan."
            ),
            expected_result="One persisted train-only A/B comparison and iteration feedback.",
        )

    @staticmethod
    def _budget_finish_decision(context: QuantAgentContext) -> QuantAgentDecision:
        completed = {
            candidate.candidate_id: candidate
            for candidate in context.candidates
            if (
                candidate.state == "completed"
                and candidate.metrics is not None
                and candidate.template != "fixture"
            )
        }
        latest_comparison = context.latest_comparison
        latest_completed_ids = set(completed)
        comparison_is_fresh = bool(
            latest_comparison and set(latest_comparison.candidate_ids) == latest_completed_ids
        )
        if completed and not comparison_is_fresh:
            return QuantAgentDecision(
                action=QuantAgentAction.COMPARE_CANDIDATES,
                arguments={},
                decision_summary=(
                    "Compare the completed candidates before any final research finish."
                ),
                expected_result="A persisted train-only comparison over the current candidates.",
            )
        selected, research_decision, decision_detail = (
            final_research_selection(context)
            if comparison_is_fresh
            else (None, None, "No fresh final comparison was available.")
        )
        arguments: dict[str, object] = {
            "selected_candidate_id": selected,
            "conclusion": (
                "The autonomous research loop reached its iteration budget. "
                f"The latest explicit training comparison selected the retained candidate. "
                f"{decision_detail}"
                if selected is not None
                else "No candidate completed before the iteration budget was reached."
            ),
            "next_step": "stop",
        }
        if selected is not None and research_decision is not None:
            arguments["research_decision"] = research_decision
        feedback_children = [
            candidate for candidate in context.candidates if candidate.feedback_artifact_id
        ]
        if (
            context.iteration_feedback is not None
            and not feedback_children
            and comparison_is_fresh
            and context.budget.remaining_iterations < 4
        ):
            arguments["replan_decision"] = {
                "action": "stop_insufficient_budget",
                "source_comparison_artifact_id": (
                    context.iteration_feedback.comparison_artifact_id
                ),
                "improvement_reference_candidate_id": (
                    context.iteration_feedback.improvement_reference.candidate_id
                ),
            }
        if context.research_series is not None and latest_comparison is not None:
            if (
                "replan_decision" not in arguments
                and selected is not None
                and "precommit_one_refinement" in context.research_series.allowed_actions
            ):
                arguments["series_decision"] = {
                    "action": "refine_selected",
                    "source_comparison_artifact_id": latest_comparison.artifact_id,
                    "seed_candidate_id": selected,
                    "focus": "improve_walk_forward_stability",
                    "refinement_reason": (
                        "Use the final training comparison to test one bounded, canonical-distinct "
                        "refinement without using sealed holdout evidence."
                    ),
                }
            else:
                arguments["series_decision"] = {
                    "action": "stop",
                    "source_comparison_artifact_id": latest_comparison.artifact_id,
                }
        return QuantAgentDecision(
            action=QuantAgentAction.FINISH_RESEARCH,
            arguments=arguments,
            decision_summary="Finish safely because the Agent iteration budget was reached.",
            expected_result="A final report retaining all completed experiments.",
        )
