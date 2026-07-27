"""Closed deterministic Quant tool registry backed by the generic runtime."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ValidationError

from packages.agent_runtime import ToolError, ToolRegistry, ToolSpec
from packages.contracts.quant import (
    QUANT_AGENT_TOOL_REGISTRY_VERSION,
    CreateCandidateArguments,
    FinishResearchArguments,
    QuantAgentAction,
    QuantEmptyToolArguments,
    QuantToolIdentity,
    QuantToolObservation,
    QuantToolRepair,
    QuantToolRepairViolation,
    ReviseCandidateArguments,
    RunBacktestArguments,
    quant_tool_identity,
    quant_tool_version,
    validate_quant_tool_arguments,
)
from packages.domain.canonical import canonical_digest
from services.api.app.modules.quant.store import (
    QuantExperimentRecord,
    QuantFixtureLease,
    QuantStore,
)


class QuantToolExecutionContext:
    """Narrow context passed to every Quant tool."""

    def __init__(self, *, store: QuantStore, lease: QuantFixtureLease) -> None:
        self.store = store
        self.lease = lease


class _InspectResearchContextTool:
    name = QuantAgentAction.INSPECT_RESEARCH_CONTEXT
    spec = ToolSpec(
        name=name.value,
        version=quant_tool_version(name),
        description="Inspect the current research context, dataset and budget.",
        input_model=QuantEmptyToolArguments,
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
        version=quant_tool_version(name),
        description="List supported deterministic strategy templates.",
        input_model=QuantEmptyToolArguments,
        output_model=QuantToolObservation,
    )

    def execute(
        self, *, context: QuantToolExecutionContext, arguments: dict[str, object]
    ) -> QuantToolObservation:
        if arguments:
            return _failed(self.name, "INVALID_ARGUMENTS", "Template listing accepts no arguments.")
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
        version=quant_tool_version(name),
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
            change_rationale=parsed.change_rationale,
            replan_decision=parsed.replan_decision,
        )
        if error or candidate is None:
            return _failed(self.name, error or "CREATE_FAILED", "Candidate could not be created.")
        return QuantToolObservation(
            action=self.name,
            success=True,
            candidate_id=candidate.id,
            artifact_ids=artifact_ids,
            safe_summary=f"Candidate {candidate.name} was created.",
            data={
                "template": candidate.template,
                "parameters": candidate.parameters,
                "feedback_artifact_id": candidate.feedback_artifact_id,
            },
        )


class _RunBacktestTool:
    name = QuantAgentAction.RUN_BACKTEST
    spec = ToolSpec(
        name=name.value,
        version=quant_tool_version(name),
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
        version=quant_tool_version(name),
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
        version=quant_tool_version(name),
        description="Compare completed candidates against the buy-and-hold benchmark.",
        input_model=QuantEmptyToolArguments,
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
        version=quant_tool_version(name),
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
            series_decision=parsed.series_decision,
            replan_decision=parsed.replan_decision,
            research_decision=parsed.research_decision,
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
    action: QuantAgentAction,
    code: str,
    summary: str,
    *,
    retryable: bool = False,
    call_fingerprint: str | None = None,
    repair: QuantToolRepair | None = None,
) -> QuantToolObservation:
    return QuantToolObservation(
        action=action,
        success=False,
        safe_summary=summary,
        error_code=code,
        retryable=retryable,
        call_fingerprint=call_fingerprint,
        repair=repair,
    )


def _field_value(arguments: dict[str, object], path: str) -> tuple[bool, object]:
    if path == "$":
        return True, arguments
    current: object = arguments
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False, None
        current = current[segment]
    return True, current


def _tool_call_fingerprint(action: QuantAgentAction, arguments: dict[str, object]) -> str:
    return canonical_digest(
        {
            "action": action.value,
            "arguments": arguments,
        }
    )


def _candidate_outside_approved_plan_repair(
    *,
    arguments: dict[str, object],
    call_fingerprint: str,
    planned_candidate_families: list[str],
) -> QuantToolRepair:
    """Translate the Store's authoritative plan guard into an executable repair."""

    return QuantToolRepair(
        action=QuantAgentAction.CREATE_CANDIDATE,
        call_fingerprint=call_fingerprint,
        allowed_shape=(
            "Use create_candidate.template from the approved candidate families "
            f"({', '.join(planned_candidate_families)}) and replace "
            "create_candidate.parameters with the canonical parameter shape for that "
            "selected registered family."
        ),
        violations=[
            QuantToolRepairViolation(
                path="template",
                code="invalid_value",
                constraint=(
                    "The candidate template must be one of the approved candidate families."
                ),
                correction=(
                    "Replace template with one of the approved registered candidate families."
                ),
                required_change="replace",
                allowed_values=planned_candidate_families,
                rejected_value_fingerprint=canonical_digest(arguments["template"]),
            ),
            QuantToolRepairViolation(
                path="parameters",
                code="invalid_shape",
                constraint=(
                    "Candidate parameters must match the canonical shape for the selected "
                    "approved registered family."
                ),
                correction=(
                    "Replace parameters with a valid, canonical-distinct parameter object "
                    "for the selected approved family."
                ),
                required_change="replace",
                rejected_value_fingerprint=canonical_digest(arguments["parameters"]),
            ),
        ],
    )


def _iteration_replan_template_relation_repair(
    *,
    action: QuantAgentAction,
    arguments: dict[str, object],
    call_fingerprint: str,
    experiments: list[QuantExperimentRecord],
) -> QuantToolRepair | None:
    """Translate the Store's ITERATION_REPLAN_TEMPLATE_RELATION_INVALID into an action-only repair.

    The authoritative improvement reference is resolved from the Run's experiments, not from
    any model-supplied template.
    """

    if action is not QuantAgentAction.CREATE_CANDIDATE:
        return None
    replan = arguments.get("replan_decision")
    if not isinstance(replan, dict):
        return None
    reference_id = replan.get("improvement_reference_candidate_id")
    if not isinstance(reference_id, str):
        return None
    reference = next((item for item in experiments if item.id == reference_id), None)
    if reference is None:
        return None
    proposed_template = arguments.get("template")
    if not isinstance(proposed_template, str):
        return None
    if proposed_template == reference.template:
        required_action = "refine_parameters"
        relationship = "matches"
    else:
        required_action = "switch_approved_family"
        relationship = "differs from"
    current_action = replan.get("action")
    if current_action == required_action:
        return None
    return QuantToolRepair(
        action=action,
        call_fingerprint=call_fingerprint,
        allowed_shape=(
            "When create_candidate.template matches the improvement reference candidate's "
            "template, replan_decision.action must be refine_parameters. When it differs, "
            "replan_decision.action must be switch_approved_family. Replace only "
            "replan_decision.action with the required value."
        ),
        violations=[
            QuantToolRepairViolation(
                path="replan_decision.action",
                code="invalid_value",
                constraint=(
                    "The replan action must agree with the relationship between the proposed "
                    "candidate template and the authoritative improvement reference candidate's "
                    "template."
                ),
                correction=(
                    f"The proposed template {relationship} the reference template, so replace "
                    f"replan_decision.action with {required_action}."
                ),
                required_change="replace",
                allowed_values=[required_action],
                rejected_value_fingerprint=(
                    canonical_digest(current_action) if isinstance(current_action, str) else None
                ),
            )
        ],
    )


def _premature_iteration_replan_repair(
    *,
    action: QuantAgentAction,
    arguments: dict[str, object],
    call_fingerprint: str,
) -> QuantToolRepair | None:
    """Remove only iteration evidence that does not exist before the A/B comparison."""

    if action is not QuantAgentAction.CREATE_CANDIDATE or "replan_decision" not in arguments:
        return None
    return QuantToolRepair(
        action=action,
        call_fingerprint=call_fingerprint,
        allowed_shape=(
            "Before two base candidates and their training comparison exist, keep the "
            "create_candidate proposal unchanged and remove only replan_decision."
        ),
        violations=[
            QuantToolRepairViolation(
                path="replan_decision",
                code="field_not_allowed_for_action",
                constraint=(
                    "replan_decision requires authoritative iteration feedback from a "
                    "completed two-candidate training comparison."
                ),
                correction="Remove replan_decision and keep every other argument unchanged.",
                required_change="remove",
                rejected_value_fingerprint=canonical_digest(arguments["replan_decision"]),
            )
        ],
    )


def _feedback_replan_repair(
    *,
    action: QuantAgentAction,
    arguments: dict[str, object],
    call_fingerprint: str,
) -> QuantToolRepair | None:
    if action is not QuantAgentAction.CREATE_CANDIDATE:
        return None
    replan = arguments.get("replan_decision")
    if not isinstance(replan, dict) or replan.get("action") not in {
        "refine_parameters",
        "switch_approved_family",
    }:
        return None
    violations: list[QuantToolRepairViolation] = []
    for field, top_level in (
        ("proposed_template", "template"),
        ("proposed_parameters", "parameters"),
    ):
        if field not in replan:
            continue
        violations.append(
            QuantToolRepairViolation(
                path=f"replan_decision.{field}",
                code="field_not_allowed_for_action",
                constraint=(
                    f"{field} is valid only for stop_no_novel_candidate; "
                    f"{replan['action']} uses create_candidate.{top_level}."
                ),
                correction=(
                    f"Remove replan_decision.{field}; keep the proposal in "
                    f"create_candidate.{top_level}."
                ),
                required_change="remove",
                rejected_value_fingerprint=canonical_digest(replan[field]),
            )
        )
    if not violations:
        return None
    return QuantToolRepair(
        action=action,
        call_fingerprint=call_fingerprint,
        allowed_shape=(
            "For refine_parameters or switch_approved_family, keep the candidate template and "
            "parameters only at create_candidate.template and create_candidate.parameters. "
            "replan_decision contains action, source_comparison_artifact_id, and "
            "improvement_reference_candidate_id only."
        ),
        violations=violations,
    )


def _finish_research_repair(
    *,
    action: QuantAgentAction,
    arguments: dict[str, object],
    call_fingerprint: str,
) -> QuantToolRepair | None:
    """Translate cross-field finish invariants into executable field repairs."""

    if action is not QuantAgentAction.FINISH_RESEARCH:
        return None
    research_decision = arguments.get("research_decision")
    if not isinstance(research_decision, dict):
        return None
    declared_candidate_id = research_decision.get("selected_candidate_id")
    if not isinstance(declared_candidate_id, str) or not declared_candidate_id:
        return None
    selected_candidate_id = arguments.get("selected_candidate_id")
    if selected_candidate_id is None:
        violation = QuantToolRepairViolation(
            path="selected_candidate_id",
            code="field_required",
            constraint=(
                "A finish carrying research_decision must also carry the same "
                "top-level selected_candidate_id."
            ),
            correction=(
                "Supply selected_candidate_id with the same candidate ID already declared in "
                "research_decision.selected_candidate_id."
            ),
            required_change="supply",
            allowed_values=[declared_candidate_id],
        )
    elif selected_candidate_id != declared_candidate_id:
        violation = QuantToolRepairViolation(
            path="selected_candidate_id",
            code="invalid_value",
            constraint=(
                "selected_candidate_id must match research_decision.selected_candidate_id."
            ),
            correction=(
                "Replace selected_candidate_id with the candidate ID already declared in "
                "research_decision.selected_candidate_id."
            ),
            required_change="replace",
            allowed_values=[declared_candidate_id],
            rejected_value_fingerprint=canonical_digest(selected_candidate_id),
        )
    else:
        return None
    return QuantToolRepair(
        action=action,
        call_fingerprint=call_fingerprint,
        allowed_shape=(
            "When research_decision is present, selected_candidate_id is required at the "
            "finish_research top level and must equal "
            "research_decision.selected_candidate_id."
        ),
        violations=[violation],
    )


def _generic_validation_repair(
    *,
    action: QuantAgentAction,
    arguments: dict[str, object],
    call_fingerprint: str,
    error: ToolError | ValidationError,
) -> QuantToolRepair:
    cause = error.__cause__ if isinstance(error, ToolError) else error
    violations_by_path: dict[str, QuantToolRepairViolation] = {}
    if isinstance(cause, ValidationError):
        for item in cause.errors(include_url=False, include_context=False, include_input=False):
            location_parts = [str(part) for part in item["loc"]]
            path = ".".join(location_parts) or "$"
            error_type = str(item["type"])
            numeric_union_container = ".".join(location_parts[:-2])
            if (
                len(location_parts) >= 3
                and location_parts[-1] in {"int", "float"}
                and numeric_union_container
                in {
                    "parameters",
                    "parameter_patch",
                    "replan_decision.proposed_parameters",
                }
            ):
                path = ".".join(location_parts[:-1])
            elif path != "$" and error_type not in {"missing", "extra_forbidden"}:
                present, _ = _field_value(arguments, path)
                if not present:
                    parts = path.split(".")
                    for end in range(len(parts) - 1, 0, -1):
                        existing_path = ".".join(parts[:end])
                        present, _ = _field_value(arguments, existing_path)
                        if present:
                            path = existing_path
                            break
            if path in violations_by_path:
                continue
            if error_type == "missing":
                code = "field_required"
                required_change = "supply"
                constraint = "This field is required by the registered tool input contract."
                correction = f"Supply {path} with a value allowed by the registered input schema."
            elif error_type == "extra_forbidden":
                code = "field_not_allowed_for_action"
                required_change = "remove"
                constraint = "This field is not accepted by the registered tool input contract."
                correction = f"Remove {path} from the next {action.value} call."
            elif error_type == "literal_error":
                code = "invalid_value"
                required_change = "replace"
                constraint = "This field must use one of the registered closed values."
                correction = f"Replace {path} with a value allowed by the registered input schema."
            else:
                code = "invalid_shape"
                required_change = "replace"
                constraint = "This field must satisfy the registered tool input contract."
                correction = f"Replace {path} with a value allowed by the registered input schema."
            present, value = _field_value(arguments, path)
            violations_by_path[path] = QuantToolRepairViolation(
                path=path,
                code=code,
                constraint=constraint,
                correction=correction,
                required_change=required_change,
                rejected_value_fingerprint=(
                    canonical_digest(value) if present and required_change == "replace" else None
                ),
            )
            if len(violations_by_path) >= 8:
                break
    violations = list(violations_by_path.values())
    if not violations:
        violations.append(
            QuantToolRepairViolation(
                path="$",
                code="invalid_shape",
                constraint="Arguments must satisfy the registered closed tool input contract.",
                correction=(
                    f"Replace the {action.value} arguments with the registered input shape."
                ),
                required_change="replace",
                rejected_value_fingerprint=canonical_digest(arguments),
            )
        )
    return QuantToolRepair(
        action=action,
        call_fingerprint=call_fingerprint,
        allowed_shape=(
            f"Use only the fields, closed values, and constraints declared by the registered "
            f"{action.value} input schema."
        ),
        violations=violations,
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
        self._runtime = ToolRegistry[QuantToolExecutionContext](
            version=QUANT_AGENT_TOOL_REGISTRY_VERSION
        )
        self._specs: dict[QuantAgentAction, ToolSpec] = {}
        for tool in registered:
            self._register(tool)

    def _register(self, tool: Any) -> None:
        action = QuantAgentAction(tool.spec.name)
        expected_identity = quant_tool_identity(action)
        if (
            tool.spec.version != expected_identity.tool_version
            or canonical_digest(tool.spec.input_schema) != expected_identity.input_schema_digest
        ):
            raise ToolError(f"Tool {action.value} does not match its versioned input identity.")

        def execute(
            context: QuantToolExecutionContext, input_model: BaseModel
        ) -> QuantToolObservation:
            return tool.execute(
                context=context, arguments=input_model.model_dump(mode="json", exclude_none=True)
            )

        self._runtime.register(tool.spec, execute)
        self._specs[action] = tool.spec

    @property
    def manifest(self) -> dict[str, Any]:
        return self._runtime.manifest()

    def identity(self, action: QuantAgentAction) -> QuantToolIdentity:
        return quant_tool_identity(action)

    def normalize_arguments(
        self,
        *,
        action: QuantAgentAction,
        arguments: dict[str, object],
    ) -> dict[str, Any]:
        return validate_quant_tool_arguments(action, arguments)

    def preflight_repair(
        self,
        *,
        action: QuantAgentAction,
        arguments: dict[str, object],
    ) -> QuantToolRepair | None:
        """Return the current typed input repair without executing the tool."""

        if not self._runtime.has(action.value):
            return None
        try:
            validate_quant_tool_arguments(action, arguments)
        except ValidationError as exc:
            call_fingerprint = _tool_call_fingerprint(action, arguments)
            return (
                _feedback_replan_repair(
                    action=action,
                    arguments=arguments,
                    call_fingerprint=call_fingerprint,
                )
                or _finish_research_repair(
                    action=action,
                    arguments=arguments,
                    call_fingerprint=call_fingerprint,
                )
                or _generic_validation_repair(
                    action=action,
                    arguments=arguments,
                    call_fingerprint=call_fingerprint,
                    error=exc,
                )
            )
        return None

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
            observation = cast(
                QuantToolObservation,
                self._runtime.execute(
                    name=action.value,
                    context=context,
                    arguments=arguments,
                ),
            )
            if (
                action is QuantAgentAction.CREATE_CANDIDATE
                and observation.error_code == "CANDIDATE_OUTSIDE_APPROVED_PLAN"
            ):
                run = context.store.get_run(
                    workspace_id=context.lease.workspace_id,
                    run_id=context.lease.run_id,
                )
                call_fingerprint = _tool_call_fingerprint(action, arguments)
                return _failed(
                    action,
                    "INVALID_ARGUMENTS",
                    (
                        "Candidate template is outside the approved research plan. Replace "
                        "the template and matching parameters with an allowed registered "
                        "family, or stop."
                    ),
                    call_fingerprint=call_fingerprint,
                    repair=_candidate_outside_approved_plan_repair(
                        arguments=arguments,
                        call_fingerprint=call_fingerprint,
                        planned_candidate_families=list(run.planned_candidate_families),
                    ),
                )
            if (
                action is QuantAgentAction.CREATE_CANDIDATE
                and observation.error_code == "ITERATION_REPLAN_TEMPLATE_RELATION_INVALID"
            ):
                experiments = context.store.experiments_for_run(
                    workspace_id=context.lease.workspace_id,
                    run_id=context.lease.run_id,
                )
                call_fingerprint = _tool_call_fingerprint(action, arguments)
                repair = _iteration_replan_template_relation_repair(
                    action=action,
                    arguments=arguments,
                    call_fingerprint=call_fingerprint,
                    experiments=experiments,
                )
                if repair is not None:
                    return _failed(
                        action,
                        "INVALID_ARGUMENTS",
                        (
                            "The replan action conflicts with the proposed and reference "
                            "template relationship. Replace replan_decision.action, or stop."
                        ),
                        call_fingerprint=call_fingerprint,
                        repair=repair,
                    )
            if (
                action is QuantAgentAction.CREATE_CANDIDATE
                and observation.error_code == "UNEXPECTED_ITERATION_REPLAN_DECISION"
            ):
                call_fingerprint = _tool_call_fingerprint(action, arguments)
                repair = _premature_iteration_replan_repair(
                    action=action,
                    arguments=arguments,
                    call_fingerprint=call_fingerprint,
                )
                if repair is not None:
                    return _failed(
                        action,
                        "INVALID_ARGUMENTS",
                        (
                            "Iteration evidence is not available before the base comparison. "
                            "Remove only replan_decision, then retry the same candidate."
                        ),
                        call_fingerprint=call_fingerprint,
                        repair=repair,
                    )
            return observation
        except ToolError as exc:
            call_fingerprint = _tool_call_fingerprint(action, arguments)
            repair = (
                _feedback_replan_repair(
                    action=action,
                    arguments=arguments,
                    call_fingerprint=call_fingerprint,
                )
                or _finish_research_repair(
                    action=action,
                    arguments=arguments,
                    call_fingerprint=call_fingerprint,
                )
                or _generic_validation_repair(
                    action=action,
                    arguments=arguments,
                    call_fingerprint=call_fingerprint,
                    error=exc,
                )
            )
            return _failed(
                action,
                "INVALID_ARGUMENTS",
                (
                    f"Arguments for {action.value} failed closed validation. "
                    "Apply the typed field repairs before retrying, or stop."
                ),
                call_fingerprint=call_fingerprint,
                repair=repair,
            )
