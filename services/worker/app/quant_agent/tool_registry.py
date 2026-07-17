"""Closed deterministic Quant tool registry backed by the generic runtime."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from packages.agent_runtime import ToolError, ToolRegistry, ToolSpec
from packages.contracts.quant import (
    CreateCandidateArguments,
    FinishResearchArguments,
    QuantAgentAction,
    QuantToolObservation,
    ReviseCandidateArguments,
    RunBacktestArguments,
)
from services.api.app.modules.quant.store import QuantFixtureLease, QuantStore


class QuantToolExecutionContext:
    """Narrow context passed to every Quant tool."""

    def __init__(self, *, store: QuantStore, lease: QuantFixtureLease) -> None:
        self.store = store
        self.lease = lease


class _EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _InspectResearchContextTool:
    name = QuantAgentAction.INSPECT_RESEARCH_CONTEXT
    spec = ToolSpec(
        name=name.value,
        version="1.0.0",
        description="Inspect the current research context, dataset and budget.",
        input_model=_EmptyArguments,
        output_model=QuantToolObservation,
    )

    def execute(
        self, *, context: QuantToolExecutionContext, arguments: dict[str, object]
    ) -> QuantToolObservation:
        if arguments:
            return _failed(
                self.name, "INVALID_ARGUMENTS", "Context inspection accepts no arguments."
            )
        data = context.store.agent_context_data(
            workspace_id=context.lease.workspace_id, run_id=context.lease.run_id
        )
        budget = data["budget"]
        return QuantToolObservation(
            action=self.name,
            success=True,
            safe_summary="Research context inspected.",
            data={
                "dataset": data["dataset_summary"],
                "benchmark_available": data["benchmark_summary"] is not None,
                "candidate_count": len(data["candidates"]),
                "remaining_experiments": budget["remaining_experiments"],
                "remaining_repairs": budget["remaining_repairs"],
            },
        )


class _ListStrategyTemplatesTool:
    name = QuantAgentAction.LIST_STRATEGY_TEMPLATES
    spec = ToolSpec(
        name=name.value,
        version="1.0.0",
        description="List supported deterministic strategy templates.",
        input_model=_EmptyArguments,
        output_model=QuantToolObservation,
    )

    def execute(
        self, *, context: QuantToolExecutionContext, arguments: dict[str, object]
    ) -> QuantToolObservation:
        if arguments:
            return _failed(
                self.name, "INVALID_ARGUMENTS", "Template listing accepts no arguments."
            )
        return QuantToolObservation(
            action=self.name,
            success=True,
            safe_summary="Three supported local strategy templates were listed.",
            data={"templates": context.store.agent_templates()},
        )


def _validate_parameters(template: str, parameters: dict[str, int | float]) -> str | None:
    keys = set(parameters)
    if any(isinstance(value, bool) for value in parameters.values()):
        return "Strategy parameters cannot be booleans."
    if template == "sma_crossover":
        if keys != {"fast_window", "slow_window"}:
            return "SMA requires fast_window and slow_window."
        fast, slow = parameters["fast_window"], parameters["slow_window"]
        if not isinstance(fast, int) or not isinstance(slow, int):
            return "SMA windows must be integers."
        if not 2 <= fast <= 150 or not 10 <= slow <= 300 or fast >= slow:
            return "SMA windows are outside the allowed range or order."
    elif template == "rsi_mean_reversion":
        if not {"entry_threshold", "exit_threshold"}.issubset(keys) or keys - {
            "period",
            "entry_threshold",
            "exit_threshold",
        }:
            return "RSI requires entry_threshold and exit_threshold; period is optional."
        period = parameters.get("period", 14)
        entry, exit_ = parameters["entry_threshold"], parameters["exit_threshold"]
        if not isinstance(period, int) or not 2 <= period <= 100:
            return "RSI period must be an integer from 2 to 100."
        if not 10 <= entry <= 45 or not 45 <= exit_ <= 80 or entry >= exit_:
            return "RSI thresholds are outside the allowed range or order."
    elif template == "breakout":
        if keys != {"lookback_window"}:
            return "Breakout requires lookback_window."
        lookback = parameters["lookback_window"]
        if not isinstance(lookback, int) or not 5 <= lookback <= 250:
            return "Breakout lookback must be an integer from 5 to 250."
    else:
        return "Unknown strategy template."
    return None


class _CreateCandidateTool:
    name = QuantAgentAction.CREATE_CANDIDATE
    spec = ToolSpec(
        name=name.value,
        version="1.0.0",
        description="Create a new candidate experiment with validated parameters.",
        input_model=CreateCandidateArguments,
        output_model=QuantToolObservation,
    )

    def execute(
        self, *, context: QuantToolExecutionContext, arguments: dict[str, object]
    ) -> QuantToolObservation:
        parsed = CreateCandidateArguments.model_validate(arguments)
        problem = _validate_parameters(parsed.template, parsed.parameters)
        if problem:
            return _failed(self.name, "INVALID_PARAMETERS", problem)
        candidate, artifact_ids, error = context.store.create_agent_candidate(
            context.lease,
            name=parsed.name,
            template=parsed.template,
            hypothesis=parsed.hypothesis,
            parameters=parsed.parameters,
        )
        if error or candidate is None:
            return _failed(self.name, error or "CREATE_FAILED", "Candidate could not be created.")
        return QuantToolObservation(
            action=self.name,
            success=True,
            candidate_id=candidate.id,
            artifact_ids=artifact_ids,
            safe_summary=f"Candidate {candidate.name} was created.",
            data={"template": candidate.template, "parameters": candidate.parameters},
        )


class _RunBacktestTool:
    name = QuantAgentAction.RUN_BACKTEST
    spec = ToolSpec(
        name=name.value,
        version="1.0.0",
        description="Run the deterministic local backtest for one candidate.",
        input_model=RunBacktestArguments,
        output_model=QuantToolObservation,
    )

    def execute(
        self, *, context: QuantToolExecutionContext, arguments: dict[str, object]
    ) -> QuantToolObservation:
        parsed = RunBacktestArguments.model_validate(arguments)
        candidate, artifact_ids, error = context.store.run_agent_backtest(
            context.lease, candidate_id=parsed.candidate_id
        )
        if error or candidate is None:
            return _failed(
                self.name,
                error or "BACKTEST_FAILED",
                "The local backtest did not complete.",
                retryable=error == "INVALID_STRATEGY_PARAMETERS",
            )
        return QuantToolObservation(
            action=self.name,
            success=True,
            candidate_id=candidate.id,
            artifact_ids=artifact_ids,
            safe_summary=f"Backtest completed for {candidate.name}.",
            data={"metrics": candidate.metrics},
        )


class _ReviseCandidateTool:
    name = QuantAgentAction.REVISE_CANDIDATE
    spec = ToolSpec(
        name=name.value,
        version="1.0.0",
        description="Revise an existing candidate's parameters within the repair budget.",
        input_model=ReviseCandidateArguments,
        output_model=QuantToolObservation,
    )

    def execute(
        self, *, context: QuantToolExecutionContext, arguments: dict[str, object]
    ) -> QuantToolObservation:
        parsed = ReviseCandidateArguments.model_validate(arguments)
        candidate = next(
            (
                item
                for item in context.store.agent_context_data(
                    workspace_id=context.lease.workspace_id,
                    run_id=context.lease.run_id,
                )["candidates"]
                if item["candidate_id"] == parsed.candidate_id
            ),
            None,
        )
        if candidate is None:
            return _failed(self.name, "UNKNOWN_CANDIDATE", "Candidate revision failed safely.")
        revised_parameters = {**candidate["parameters"], **parsed.parameter_patch}
        problem = _validate_parameters(candidate["template"], revised_parameters)
        if problem:
            return _failed(self.name, "INVALID_PARAMETERS", problem)
        candidate, artifact_ids, error = context.store.revise_agent_candidate(
            context.lease,
            candidate_id=parsed.candidate_id,
            reason=parsed.reason,
            parameter_patch=parsed.parameter_patch,
        )
        if error or candidate is None:
            return _failed(
                self.name, error or "REVISION_FAILED", "Candidate revision failed safely."
            )
        return QuantToolObservation(
            action=self.name,
            success=True,
            candidate_id=candidate.id,
            artifact_ids=artifact_ids,
            safe_summary=f"Candidate was revised as {candidate.name}.",
            data={"parameters": candidate.parameters, "repair_count": candidate.repair_count},
        )


class _CompareCandidatesTool:
    name = QuantAgentAction.COMPARE_CANDIDATES
    spec = ToolSpec(
        name=name.value,
        version="1.0.0",
        description="Compare completed candidates against the buy-and-hold benchmark.",
        input_model=_EmptyArguments,
        output_model=QuantToolObservation,
    )

    def execute(
        self, *, context: QuantToolExecutionContext, arguments: dict[str, object]
    ) -> QuantToolObservation:
        if arguments:
            return _failed(self.name, "INVALID_ARGUMENTS", "Comparison accepts no arguments.")
        comparison, artifact_ids, error = context.store.compare_agent_candidates(context.lease)
        if error or comparison is None:
            return _failed(
                self.name, error or "COMPARISON_FAILED", "No candidate comparison was generated."
            )
        return QuantToolObservation(
            action=self.name,
            success=True,
            artifact_ids=artifact_ids,
            safe_summary=(
                f"{len(comparison['candidates'])} completed candidates were compared "
                "with the benchmark."
            ),
            data=comparison,
        )


class _FinishResearchTool:
    name = QuantAgentAction.FINISH_RESEARCH
    spec = ToolSpec(
        name=name.value,
        version="1.0.0",
        description="Finish research and produce the final report.",
        input_model=FinishResearchArguments,
        output_model=QuantToolObservation,
    )

    def execute(
        self, *, context: QuantToolExecutionContext, arguments: dict[str, object]
    ) -> QuantToolObservation:
        parsed = FinishResearchArguments.model_validate(arguments)
        report, artifact_ids, error = context.store.finish_agent_research(
            context.lease,
            selected_candidate_id=parsed.selected_candidate_id,
            conclusion=parsed.conclusion,
            next_step=parsed.next_step,
        )
        if error or report is None:
            return _failed(self.name, error or "FINISH_FAILED", "Research could not finish yet.")
        return QuantToolObservation(
            action=self.name,
            success=True,
            candidate_id=parsed.selected_candidate_id,
            artifact_ids=artifact_ids,
            safe_summary="The autonomous research report was generated.",
            data={"conclusion": parsed.conclusion, "next_step": parsed.next_step},
            terminal=True,
        )


def _failed(
    action: QuantAgentAction, code: str, summary: str, *, retryable: bool = False
) -> QuantToolObservation:
    return QuantToolObservation(
        action=action,
        success=False,
        safe_summary=summary,
        error_code=code,
        retryable=retryable,
    )


class QuantToolRegistry:
    """Closed seven-tool registry using the shared Pydantic-validated runtime."""

    def __init__(self, tools: list[Any] | None = None) -> None:
        registered = tools or [
            _InspectResearchContextTool(),
            _ListStrategyTemplatesTool(),
            _CreateCandidateTool(),
            _RunBacktestTool(),
            _ReviseCandidateTool(),
            _CompareCandidatesTool(),
            _FinishResearchTool(),
        ]
        self._runtime = ToolRegistry[QuantToolExecutionContext](version="1.0.0")
        for tool in registered:
            self._register(tool)

    def _register(self, tool: Any) -> None:
        def execute(
            context: QuantToolExecutionContext, input_model: BaseModel
        ) -> QuantToolObservation:
            return tool.execute(
                context=context, arguments=input_model.model_dump(mode="json", exclude_none=True)
            )

        self._runtime.register(tool.spec, execute)

    @property
    def manifest(self) -> dict[str, Any]:
        return self._runtime.manifest()

    def execute(
        self,
        *,
        action: QuantAgentAction,
        context: QuantToolExecutionContext,
        arguments: dict[str, object],
    ) -> QuantToolObservation:
        if not self._runtime.has(action.value):
            return _failed(action, "UNKNOWN_TOOL", f"Unknown Quant tool: {action.value}")
        try:
            return cast(
                QuantToolObservation,
                self._runtime.execute(
                    name=action.value,
                    context=context,
                    arguments=arguments,
                ),
            )
        except ToolError:
            return _failed(
                action,
                "INVALID_ARGUMENTS",
                f"Arguments for {action.value} failed closed validation.",
            )
