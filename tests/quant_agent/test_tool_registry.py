from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from packages.contracts.quant import QuantAgentAction, QuantAgentDecision
from packages.contracts.quant.enums import QuantExperimentVerdict
from packages.domain.canonical import canonical_digest
from services.api.app.modules.quant.store import (
    QuantExperimentRecord,
    QuantFixtureLease,
    QuantStore,
)
from services.worker.app.quant_agent.runner import QuantAgentRunner
from services.worker.app.quant_agent.tool_registry import (
    QuantToolExecutionContext,
    QuantToolRegistry,
    _CreateCandidateTool,  # pyright: ignore[reportPrivateUsage]
)


class _StoreThatMustNotMutate:
    def create_agent_candidate(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("invalid parameters must fail before persistence")


class _ApprovedPlanGuardStore:
    def __init__(self) -> None:
        self.write_count = 0

    def create_agent_candidate(
        self, *args: object, **kwargs: object
    ) -> tuple[None, list[str], str]:
        return None, [], "CANDIDATE_OUTSIDE_APPROVED_PLAN"

    def get_run(self, *, workspace_id: str, run_id: str) -> SimpleNamespace:
        assert workspace_id == "workspace"
        assert run_id == "run"
        return SimpleNamespace(planned_candidate_families=["sma_crossover", "breakout"])


class _ReplanRelationInvalidStore:
    def __init__(self, experiments: list[QuantExperimentRecord]) -> None:
        self.experiments = experiments
        self.write_count = 0

    def create_agent_candidate(
        self, *args: object, **kwargs: object
    ) -> tuple[None, list[str], str]:
        self.write_count += 1
        return None, [], "ITERATION_REPLAN_TEMPLATE_RELATION_INVALID"

    def experiments_for_run(self, *, workspace_id: str, run_id: str) -> list[QuantExperimentRecord]:
        assert workspace_id == "workspace"
        assert run_id == "run"
        return self.experiments


def test_invalid_candidate_parameters_fail_before_store_mutation() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observation = _CreateCandidateTool().execute(
        context=QuantToolExecutionContext(
            store=cast(QuantStore, _StoreThatMustNotMutate()),
            lease=lease,
        ),
        arguments={
            "name": "invalid SMA",
            "template": "sma_crossover",
            "hypothesis": "This must be rejected.",
            "parameters": {"fast_window": 50, "slow_window": 20},
        },
    )

    assert not observation.success
    assert observation.error_code == "INVALID_PARAMETERS"


def test_plan_external_candidate_returns_authoritative_typed_repair_without_write() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    store = _ApprovedPlanGuardStore()
    arguments: dict[str, object] = {
        "name": "Unplanned RSI",
        "template": "rsi_mean_reversion",
        "hypothesis": "Test one plan-external family.",
        "parameters": {"period": 14, "entry_threshold": 30, "exit_threshold": 55},
    }

    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.CREATE_CANDIDATE,
        context=QuantToolExecutionContext(
            store=cast(QuantStore, store),
            lease=lease,
        ),
        arguments=arguments,
    )

    assert store.write_count == 0
    assert observation.model_dump(mode="json", exclude={"repair"}) == {
        "action": "create_candidate",
        "success": False,
        "safe_summary": (
            "Candidate template is outside the approved research plan. Replace the template "
            "and matching parameters with an allowed registered family, or stop."
        ),
        "candidate_id": None,
        "artifact_ids": [],
        "data": {},
        "error_code": "INVALID_ARGUMENTS",
        "retryable": False,
        "terminal": False,
        "call_fingerprint": canonical_digest(
            {"action": "create_candidate", "arguments": arguments}
        ),
    }
    assert observation.repair is not None
    assert observation.repair.retry_policy == "modify_arguments_or_stop"
    assert observation.repair.call_fingerprint == observation.call_fingerprint
    assert observation.repair.allowed_shape == (
        "Use create_candidate.template from the approved candidate families "
        "(sma_crossover, breakout) and replace create_candidate.parameters with the "
        "canonical parameter shape for that selected registered family."
    )
    assert [
        (
            violation.path,
            violation.code,
            violation.required_change,
            violation.allowed_values,
            violation.rejected_value_fingerprint,
        )
        for violation in observation.repair.violations
    ] == [
        (
            "template",
            "invalid_value",
            "replace",
            ["sma_crossover", "breakout"],
            canonical_digest("rsi_mean_reversion"),
        ),
        (
            "parameters",
            "invalid_shape",
            "replace",
            [],
            canonical_digest({"period": 14, "entry_threshold": 30, "exit_threshold": 55}),
        ),
    ]


def _replan_lease() -> QuantFixtureLease:
    return QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def _reference_candidate(*, candidate_id: str, template: str) -> QuantExperimentRecord:
    return QuantExperimentRecord(
        id=candidate_id,
        workspace_id="workspace",
        run_id="run",
        ordinal=1,
        name="Reference",
        hypothesis="Reference candidate.",
        verdict=QuantExperimentVerdict.VIABLE,
        summary="Reference candidate.",
        template=template,
        parameters={"fast_window": 20, "slow_window": 100},
    )


def test_replan_template_mismatch_returns_action_only_repair() -> None:
    reference = _reference_candidate(candidate_id="ref-1", template="breakout")
    store = _ReplanRelationInvalidStore(experiments=[reference])
    arguments: dict[str, object] = {
        "name": "SMA 30/100",
        "template": "sma_crossover",
        "hypothesis": "Test a same-reference-family candidate.",
        "parameters": {"fast_window": 30, "slow_window": 100},
        "change_rationale": "The reference is breakout, so this requires a family switch.",
        "replan_decision": {
            "action": "refine_parameters",
            "source_comparison_artifact_id": "comparison-safe-id",
            "improvement_reference_candidate_id": reference.id,
        },
    }

    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.CREATE_CANDIDATE,
        context=QuantToolExecutionContext(store=cast(QuantStore, store), lease=_replan_lease()),
        arguments=arguments,
    )

    assert store.write_count == 1
    assert not observation.success
    assert observation.error_code == "INVALID_ARGUMENTS"
    assert observation.candidate_id is None
    assert observation.artifact_ids == []
    assert observation.data == {}
    assert observation.call_fingerprint is not None
    assert observation.repair is not None
    assert observation.repair.action is QuantAgentAction.CREATE_CANDIDATE
    assert observation.repair.call_fingerprint == observation.call_fingerprint
    assert observation.repair.allowed_shape == (
        "When create_candidate.template matches the improvement reference candidate's "
        "template, replan_decision.action must be refine_parameters. When it differs, "
        "replan_decision.action must be switch_approved_family. Replace only "
        "replan_decision.action with the required value."
    )
    assert [
        (
            violation.path,
            violation.code,
            violation.required_change,
            violation.allowed_values,
            violation.rejected_value_fingerprint,
        )
        for violation in observation.repair.violations
    ] == [
        (
            "replan_decision.action",
            "invalid_value",
            "replace",
            ["switch_approved_family"],
            canonical_digest("refine_parameters"),
        ),
    ]
    rejected_replan = cast(dict[str, object], arguments["replan_decision"])
    corrected = QuantAgentDecision(
        action=QuantAgentAction.CREATE_CANDIDATE,
        arguments={
            **arguments,
            "replan_decision": {
                **rejected_replan,
                "action": "switch_approved_family",
            },
        },
        decision_summary="Apply only the closed action repair.",
        expected_result="The repair executes only when its rejected arguments are available.",
    )
    assert not QuantAgentRunner._applies_tool_repair(  # pyright: ignore[reportPrivateUsage]
        decision=corrected,
        repair=observation.repair,
    )
    assert QuantAgentRunner._applies_tool_repair(  # pyright: ignore[reportPrivateUsage]
        decision=corrected,
        repair=observation.repair,
        rejected_arguments=arguments,
    )


def test_replan_template_match_returns_action_only_repair() -> None:
    reference = _reference_candidate(candidate_id="ref-1", template="sma_crossover")
    store = _ReplanRelationInvalidStore(experiments=[reference])
    arguments: dict[str, object] = {
        "name": "SMA 30/100",
        "template": "sma_crossover",
        "hypothesis": "Test a refined parameter set.",
        "parameters": {"fast_window": 30, "slow_window": 100},
        "change_rationale": "Same-family proposal requires parameter refinement.",
        "replan_decision": {
            "action": "switch_approved_family",
            "source_comparison_artifact_id": "comparison-safe-id",
            "improvement_reference_candidate_id": reference.id,
        },
    }

    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.CREATE_CANDIDATE,
        context=QuantToolExecutionContext(store=cast(QuantStore, store), lease=_replan_lease()),
        arguments=arguments,
    )

    assert store.write_count == 1
    assert not observation.success
    assert observation.error_code == "INVALID_ARGUMENTS"
    assert observation.repair is not None
    assert [
        (
            violation.path,
            violation.code,
            violation.required_change,
            violation.allowed_values,
        )
        for violation in observation.repair.violations
    ] == [
        (
            "replan_decision.action",
            "invalid_value",
            "replace",
            ["refine_parameters"],
        ),
    ]


def test_replan_template_relation_unknown_reference_preserves_original_failure() -> None:
    reference = _reference_candidate(candidate_id="ref-1", template="breakout")
    store = _ReplanRelationInvalidStore(experiments=[reference])
    arguments: dict[str, object] = {
        "name": "SMA 30/100",
        "template": "sma_crossover",
        "hypothesis": "Reference lookup will fail.",
        "parameters": {"fast_window": 30, "slow_window": 100},
        "change_rationale": "The improvement reference candidate is unknown.",
        "replan_decision": {
            "action": "refine_parameters",
            "source_comparison_artifact_id": "comparison-safe-id",
            "improvement_reference_candidate_id": "unknown-candidate-id",
        },
    }

    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.CREATE_CANDIDATE,
        context=QuantToolExecutionContext(store=cast(QuantStore, store), lease=_replan_lease()),
        arguments=arguments,
    )

    assert store.write_count == 1
    assert not observation.success
    assert observation.error_code == "ITERATION_REPLAN_TEMPLATE_RELATION_INVALID"
    assert observation.repair is None


def test_empty_argument_tool_rejects_unknown_fields() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
        context=QuantToolExecutionContext(
            store=cast(QuantStore, _StoreThatMustNotMutate()),
            lease=lease,
        ),
        arguments={"unexpected": True},
    )

    assert not observation.success
    assert observation.error_code == "INVALID_ARGUMENTS"


def test_feedback_replan_invalid_arguments_return_closed_field_repairs() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.CREATE_CANDIDATE,
        context=QuantToolExecutionContext(
            store=cast(QuantStore, _StoreThatMustNotMutate()),
            lease=lease,
        ),
        arguments={
            "name": "SMA 30/100",
            "template": "sma_crossover",
            "hypothesis": "Test one feedback-driven candidate.",
            "parameters": {"fast_window": 30, "slow_window": 100},
            "change_rationale": "Use the A/B training comparison to test a slower crossover.",
            "replan_decision": {
                "action": "refine_parameters",
                "source_comparison_artifact_id": "comparison-safe-id",
                "improvement_reference_candidate_id": "candidate-safe-id",
                # This is the sanitized Q1 DeepSeek failure shape. The
                # candidate proposal belongs only at create_candidate top level.
                "proposed_parameters": {"fast_window": 30, "slow_window": 100},
            },
        },
    )

    assert not observation.success
    assert observation.error_code == "INVALID_ARGUMENTS"
    assert observation.call_fingerprint is not None
    assert observation.repair is not None
    assert observation.repair.action is QuantAgentAction.CREATE_CANDIDATE
    assert observation.repair.call_fingerprint == observation.call_fingerprint
    assert observation.repair.allowed_shape == (
        "For refine_parameters or switch_approved_family, keep the candidate template and "
        "parameters only at create_candidate.template and create_candidate.parameters. "
        "replan_decision contains action, source_comparison_artifact_id, and "
        "improvement_reference_candidate_id only."
    )
    assert [
        (
            violation.path,
            violation.code,
            violation.required_change,
            violation.correction,
        )
        for violation in observation.repair.violations
    ] == [
        (
            "replan_decision.proposed_parameters",
            "field_not_allowed_for_action",
            "remove",
            "Remove replan_decision.proposed_parameters; keep the proposal in "
            "create_candidate.parameters.",
        )
    ]
    assert "fast_window" not in observation.safe_summary


def test_switch_replan_rejects_both_duplicate_proposal_fields_with_two_repairs() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.CREATE_CANDIDATE,
        context=QuantToolExecutionContext(
            store=cast(QuantStore, _StoreThatMustNotMutate()),
            lease=lease,
        ),
        arguments={
            "name": "Breakout 55",
            "template": "breakout",
            "hypothesis": "Test a feedback-driven family switch.",
            "parameters": {"lookback_window": 55},
            "change_rationale": "Switch from the A/B reference using training evidence.",
            "replan_decision": {
                "action": "switch_approved_family",
                "source_comparison_artifact_id": "comparison-safe-id",
                "improvement_reference_candidate_id": "candidate-safe-id",
                "proposed_template": "breakout",
                "proposed_parameters": {"lookback_window": 55},
            },
        },
    )

    assert not observation.success
    assert observation.repair is not None
    assert [(item.path, item.required_change) for item in observation.repair.violations] == [
        ("replan_decision.proposed_template", "remove"),
        ("replan_decision.proposed_parameters", "remove"),
    ]


def test_finish_research_missing_selected_candidate_returns_executable_field_repair() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.FINISH_RESEARCH,
        context=QuantToolExecutionContext(
            store=cast(QuantStore, _StoreThatMustNotMutate()),
            lease=lease,
        ),
        arguments={
            "conclusion": "Select the leading candidate from the final training comparison.",
            "next_step": "paper_evaluation",
            "research_decision": {
                "selected_candidate_id": "candidate-safe-id",
                "source_comparison_artifact_id": "comparison-safe-id",
                "decision_basis": "approved_objective_rank",
            },
        },
    )

    assert not observation.success
    assert observation.error_code == "INVALID_ARGUMENTS"
    assert observation.repair is not None
    assert [
        (
            violation.path,
            violation.code,
            violation.required_change,
            violation.allowed_values,
        )
        for violation in observation.repair.violations
    ] == [
        (
            "selected_candidate_id",
            "field_required",
            "supply",
            ["candidate-safe-id"],
        )
    ]
    assert observation.repair.violations[0].correction == (
        "Supply selected_candidate_id with the same candidate ID already declared in "
        "research_decision.selected_candidate_id."
    )


def test_exact_unchanged_generic_root_validation_call_does_not_count_as_repaired() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    arguments: dict[str, object] = {
        "selected_candidate_id": "candidate-safe-id",
        "conclusion": "A selected candidate requires a structured research decision.",
        "next_step": "stop",
    }
    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.FINISH_RESEARCH,
        context=QuantToolExecutionContext(
            store=cast(QuantStore, _StoreThatMustNotMutate()),
            lease=lease,
        ),
        arguments=arguments,
    )

    assert observation.repair is not None
    assert observation.repair.violations[0].path == "$"
    assert observation.repair.violations[0].rejected_value_fingerprint is not None
    unchanged = QuantAgentDecision(
        action=QuantAgentAction.FINISH_RESEARCH,
        arguments=arguments,
        decision_summary="Repeat the same invalid root shape.",
        expected_result="The unchanged call must not execute twice.",
    )
    assert not QuantAgentRunner._applies_tool_repair(  # pyright: ignore[reportPrivateUsage]
        decision=unchanged,
        repair=observation.repair,
    )
