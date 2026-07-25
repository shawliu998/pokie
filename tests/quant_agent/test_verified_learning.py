from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentDecision,
    QuantLearningEventRef,
    QuantLearningFieldDelta,
    QuantLearningTrace,
    QuantLearningViolation,
    QuantRepairMemory,
    QuantToolIdentity,
    QuantToolObservation,
)
from packages.contracts.quant.enums import (
    QuantArtifactKind,
    QuantExperimentVerdict,
    QuantRunMode,
    QuantRunState,
)
from packages.domain.canonical import canonical_digest
from services.api.app.db.models import QuantRepositoryState
from services.api.app.modules.quant.snapshot import (
    _project_replan_repair,
    quant_agent_workspace_snapshot,
)
from services.api.app.modules.quant.store import (
    RESEARCH_MEMORY_CONTRACT_VERSION,
    VERIFIED_LEARNING_REPOSITORY_CONTRACT_VERSION,
    QuantExperimentRecord,
    QuantRunRecord,
    QuantStore,
)
from services.worker.app.quant_agent.runner import QuantAgentRunner
from services.worker.app.quant_agent.tool_registry import (
    QuantToolExecutionContext,
    QuantToolRegistry,
)


def _decision(
    action: QuantAgentAction,
    arguments: dict[str, object],
) -> QuantAgentDecision:
    return QuantAgentDecision(
        action=action,
        arguments=arguments,
        decision_summary=f"Exercise {action.value}.",
        expected_result="One bounded tool observation.",
    )


def _create_run(
    store: QuantStore,
    *,
    workspace_id: str,
    suffix: str,
    mode: QuantRunMode = QuantRunMode.AUTO,
) -> QuantRunRecord:
    project = store.create_project(
        workspace_id=workspace_id,
        name=f"Verified learning {suffix}",
        objective=f"Verify tool-contract repair {suffix}.",
    )
    return store.create_run(
        workspace_id=workspace_id,
        project_id=project.id,
        question=f"Verify tool-contract repair {suffix}.",
        mode=mode,
        expected_project_row_version=project.row_version,
    )


def _execute(
    store: QuantStore,
    run: QuantRunRecord,
    decision: QuantAgentDecision,
    *,
    worker: str,
) -> QuantToolObservation:
    claim = store.claim_agent_run(workspace_id=run.workspace_id, worker_id=worker)
    assert claim is not None
    assert store.record_agent_decision(claim, decision)
    observation = QuantToolRegistry().execute(
        action=decision.action,
        arguments=decision.arguments,
        context=QuantToolExecutionContext(store=store, lease=claim),
    )
    assert store.complete_agent_step(claim, observation)
    return observation


def _trace_artifacts(store: QuantStore, run: QuantRunRecord) -> list[Any]:
    return [
        artifact
        for artifact in store.artifacts_for_run(
            workspace_id=run.workspace_id,
            run_id=run.id,
        )
        if artifact.kind is QuantArtifactKind.LEARNING_TRACE
    ]


def _terminalize(store: QuantStore, run: QuantRunRecord, reason: str) -> None:
    run.state = QuantRunState.FAILED
    run.agent_status = "failed"
    run.failure_reason = reason
    run.updated_at = datetime.now(UTC)
    store._append_event(  # pyright: ignore[reportPrivateUsage]
        run,
        "run.failed",
        {
            "state": QuantRunState.FAILED,
            "reason_code": "verified_learning_test_terminal",
            "safe_summary": reason,
        },
    )
    store._persist_workspace(run.workspace_id)  # pyright: ignore[reportPrivateUsage]


def _renumber_persisted_events(state: dict[str, Any]) -> None:
    for persisted_run in state["runs"]:
        run_events = [item for item in state["events"] if item["run_id"] == persisted_run["id"]]
        for sequence, event in enumerate(run_events, start=1):
            event["sequence"] = sequence
        persisted_run["latest_sequence"] = len(run_events)


def _rebind_learning_trace_event_refs(state: dict[str, Any]) -> None:
    events_by_id = {event["id"]: event for event in state["events"]}
    for artifact in state["artifacts"]:
        if artifact["kind"] != "learning_trace":
            continue
        content = artifact["content"]
        references = [
            content["failed_event"],
            content["outcome_event"],
            *content["supporting_events"],
        ]
        correction_started = content.get("correction_started_event")
        if correction_started is not None:
            references.append(correction_started)
        for reference in references:
            event = events_by_id[reference["event_id"]]
            reference["sequence"] = event["sequence"]
            reference["event_digest"] = canonical_digest(
                {
                    "event_id": event["id"],
                    "workspace_id": event["workspace_id"],
                    "run_id": event["run_id"],
                    "sequence": event["sequence"],
                    "event_type": event["event_type"],
                    "payload_digest": canonical_digest(event["payload"]),
                    "trace_id": event["trace_id"],
                    "occurred_at": datetime.fromisoformat(event["occurred_at"]),
                }
            )
        artifact["digest"] = canonical_digest(content)


def _resolved_episode(store: QuantStore, run: QuantRunRecord) -> QuantLearningTrace:
    rejected = _execute(
        store,
        run,
        _decision(
            QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
            {"unexpected": True},
        ),
        worker=f"invalid-{run.id}",
    )
    assert rejected.error_code == "INVALID_ARGUMENTS"
    corrected = _execute(
        store,
        run,
        _decision(QuantAgentAction.INSPECT_RESEARCH_CONTEXT, {}),
        worker=f"corrected-{run.id}",
    )
    assert corrected.success
    artifacts = _trace_artifacts(store, run)
    assert len(artifacts) == 1
    assert artifacts[0].digest == canonical_digest(artifacts[0].content)
    trace = QuantLearningTrace.model_validate(artifacts[0].content)
    _terminalize(store, run, "Resolved repair episode test completed.")
    return trace


def test_learning_traces_are_typed_distinct_digest_verified_and_leak_free() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    resolved_run = _create_run(store, workspace_id=workspace_id, suffix="resolved")
    resolved = _resolved_episode(store, resolved_run)

    stopped_run = _create_run(store, workspace_id=workspace_id, suffix="stopped")
    rejected = _execute(
        store,
        stopped_run,
        _decision(
            QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
            {"unexpected": True},
        ),
        worker="stopped-invalid",
    )
    assert rejected.repair is not None
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="stopped-guard")
    assert claim is not None
    assert store.record_agent_contract_repair_exhausted(
        claim,
        rejected_action=rejected.action.value,
        attempted_action=QuantAgentAction.LIST_STRATEGY_TEMPLATES.value,
        rejected_call_fingerprint=rejected.repair.call_fingerprint,
        attempted_call_fingerprint=canonical_digest(
            {
                "action": QuantAgentAction.LIST_STRATEGY_TEMPLATES.value,
                "arguments": {},
            }
        ),
    )
    stopped_artifact = _trace_artifacts(store, stopped_run)
    assert len(stopped_artifact) == 1, [
        (item.kind.value, item.run_id, item.content.get("outcome"))
        for item in store._artifacts.values()  # pyright: ignore[reportPrivateUsage]
        if item.workspace_id == workspace_id
    ]
    stopped = QuantLearningTrace.model_validate(stopped_artifact[0].content)
    assert stopped_artifact[0].digest == canonical_digest(stopped_artifact[0].content)

    failed_run = _create_run(store, workspace_id=workspace_id, suffix="failed")
    rejected_failed = _execute(
        store,
        failed_run,
        _decision(
            QuantAgentAction.RUN_BACKTEST,
            {"candidate_id": "missing-candidate", "unexpected": True},
        ),
        worker="failed-invalid",
    )
    assert rejected_failed.error_code == "INVALID_ARGUMENTS"
    business_failed = _execute(
        store,
        failed_run,
        _decision(
            QuantAgentAction.RUN_BACKTEST,
            {"candidate_id": "missing-candidate"},
        ),
        worker="failed-corrected",
    )
    assert not business_failed.success
    assert business_failed.error_code != "INVALID_ARGUMENTS"
    failed_artifact = _trace_artifacts(store, failed_run)[0]
    assert failed_artifact.digest == canonical_digest(failed_artifact.content)
    failed = QuantLearningTrace.model_validate(failed_artifact.content)
    _terminalize(store, failed_run, "Failed repair outcome test completed.")

    assert resolved.outcome == "resolved"
    assert stopped.outcome == "stopped"
    assert failed.outcome == "failed"
    assert len({resolved.trace_id, stopped.trace_id, failed.trace_id}) == 3
    assert resolved.correction_delta[0].path == "unexpected"
    assert stopped.correction_delta == []
    assert failed.correction_delta[0].path == "unexpected"

    target = _create_run(store, workspace_id=workspace_id, suffix="eligibility")
    assert target.repair_memory is not None
    assert len(target.repair_memory.entries) == 1
    assert target.repair_memory.entries[0].source_trace_ids == [resolved.trace_id]
    foreign = _create_run(
        store,
        workspace_id=str(uuid4()),
        suffix="foreign-workspace",
    )
    assert foreign.repair_memory is not None
    assert foreign.repair_memory.entries == []

    prohibited = (
        "holdout",
        "generalization",
        "robustness",
        "metric",
        "trade",
        "bar",
        "reasoning",
        "provider_output",
    )
    for payload in (
        resolved.model_dump(mode="json"),
        stopped.model_dump(mode="json"),
        failed.model_dump(mode="json"),
        target.repair_memory.model_dump(mode="json"),
    ):
        encoded = json.dumps(payload, sort_keys=True).lower()
        assert not any(term in encoded for term in prohibited)


class _InvalidInspectProvider:
    provider_name = "deepseek"
    model_name = "test-model"

    def plan(self, research_goal: str) -> None:  # pragma: no cover - not called
        raise AssertionError(research_goal)

    def decide(self, context: Any) -> QuantAgentDecision:
        return _decision(
            QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
            {"unexpected": True},
        )


class _InspectDecisionSequenceProvider:
    provider_name = "deepseek"
    model_name = "test-model"

    def __init__(self, decisions: list[QuantAgentDecision]) -> None:
        self._decisions = iter(decisions)

    def plan(self, research_goal: str) -> None:  # pragma: no cover - not called
        raise AssertionError(research_goal)

    def decide(self, context: Any) -> QuantAgentDecision:
        return next(self._decisions)


def test_consecutive_invalid_episodes_close_with_one_trace_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = str(uuid4())
    monkeypatch.setenv("POKIEQUANT_AGENT_PROVIDER", "deepseek")
    monkeypatch.setenv("POKIEQUANT_AGENT_MODEL", "test-model")
    store = QuantStore()
    run = _create_run(store, workspace_id=workspace_id, suffix="consecutive-invalid")
    runner = QuantAgentRunner(
        store=store,
        provider=_InspectDecisionSequenceProvider(
            [
                _decision(
                    QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
                    {"unexpected": True},
                ),
                _decision(
                    QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
                    {"different": True},
                ),
                _decision(QuantAgentAction.INSPECT_RESEARCH_CONTEXT, {}),
            ]
        ),  # type: ignore[arg-type]
    )

    for index in range(2):
        claim = store.claim_agent_run(
            workspace_id=workspace_id,
            worker_id=f"consecutive-invalid-{index}",
        )
        assert claim is not None
        result = runner.run_step(claim=claim)
        assert result.did_work and not result.terminal
        assert len(_trace_artifacts(store, run)) == index

    claim = store.claim_agent_run(
        workspace_id=workspace_id,
        worker_id="consecutive-invalid-valid",
    )
    assert claim is not None
    result = runner.run_step(claim=claim)
    assert result.did_work and not result.terminal

    events = store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    invalid_failures = [
        event
        for event in events
        if event["event_type"] == "tool.failed"
        and event["payload"].get("error_code") == "INVALID_ARGUMENTS"
    ]
    artifacts = _trace_artifacts(store, run)
    traces = sorted(
        (QuantLearningTrace.model_validate(item.content) for item in artifacts),
        key=lambda trace: trace.failed_event.sequence,
    )
    assert len(invalid_failures) == 2
    assert len(traces) == 2
    assert {trace.failed_call_fingerprint for trace in traces} == {
        event["payload"]["call_fingerprint"] for event in invalid_failures
    }
    assert [trace.outcome for trace in traces] == ["failed", "resolved"]
    assert str(traces[0].outcome_event.event_id) == invalid_failures[1]["event_id"]
    assert (
        traces[0].corrected_call_fingerprint == invalid_failures[1]["payload"]["call_fingerprint"]
    )
    assert traces[0].failed_call_fingerprint != traces[0].corrected_call_fingerprint
    assert traces[1].outcome_event.event_id != traces[0].outcome_event.event_id

    persisted = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    restored = QuantStore()
    restored._restore_workspace(  # pyright: ignore[reportPrivateUsage]
        workspace_id,
        persisted,
    )
    assert (
        len(
            [
                artifact
                for artifact in restored._artifacts.values()  # pyright: ignore[reportPrivateUsage]
                if artifact.kind is QuantArtifactKind.LEARNING_TRACE
            ]
        )
        == 2
    )

    missing_trace = deepcopy(persisted)
    removed_artifact_id = next(
        item["id"] for item in missing_trace["artifacts"] if item["kind"] == "learning_trace"
    )
    missing_trace["artifacts"] = [
        item for item in missing_trace["artifacts"] if item["id"] != removed_artifact_id
    ]
    missing_trace["events"] = [
        item
        for item in missing_trace["events"]
        if not (
            item["event_type"] == "artifact.published"
            and item["payload"].get("artifact_id") == removed_artifact_id
        )
    ]
    _renumber_persisted_events(missing_trace)
    _rebind_learning_trace_event_refs(missing_trace)
    rejected_restore = QuantStore()
    with pytest.raises(ValueError, match="learning trace is missing"):
        rejected_restore._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            missing_trace,
        )
    assert rejected_restore._runs == {}  # pyright: ignore[reportPrivateUsage]
    assert rejected_restore._artifacts == {}  # pyright: ignore[reportPrivateUsage]


def test_consecutive_invalid_then_repair_exhausted_closes_failed_and_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = str(uuid4())
    monkeypatch.setenv("POKIEQUANT_AGENT_PROVIDER", "deepseek")
    monkeypatch.setenv("POKIEQUANT_AGENT_MODEL", "test-model")
    store = QuantStore()
    run = _create_run(store, workspace_id=workspace_id, suffix="consecutive-invalid-stop")
    runner = QuantAgentRunner(
        store=store,
        provider=_InspectDecisionSequenceProvider(
            [
                _decision(
                    QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
                    {"unexpected": True},
                ),
                _decision(
                    QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
                    {"different": True},
                ),
                _decision(QuantAgentAction.LIST_STRATEGY_TEMPLATES, {}),
            ]
        ),  # type: ignore[arg-type]
    )

    for index in range(3):
        claim = store.claim_agent_run(
            workspace_id=workspace_id,
            worker_id=f"consecutive-invalid-stop-{index}",
        )
        assert claim is not None
        result = runner.run_step(claim=claim)
        assert result.did_work
        assert result.terminal is (index == 2)

    events = store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    invalid_failures = [
        event
        for event in events
        if event["event_type"] == "tool.failed"
        and event["payload"].get("error_code") == "INVALID_ARGUMENTS"
    ]
    traces = sorted(
        (
            QuantLearningTrace.model_validate(artifact.content)
            for artifact in _trace_artifacts(store, run)
        ),
        key=lambda trace: trace.failed_event.sequence,
    )
    assert len(invalid_failures) == 2
    assert len(traces) == 2
    assert [trace.outcome for trace in traces] == ["failed", "stopped"]
    assert [trace.failed_call_fingerprint for trace in traces] == [
        event["payload"]["call_fingerprint"] for event in invalid_failures
    ]
    assert str(traces[0].outcome_event.event_id) == invalid_failures[1]["event_id"]
    assert (
        traces[0].corrected_call_fingerprint == invalid_failures[1]["payload"]["call_fingerprint"]
    )

    persisted = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    restored = QuantStore()
    restored._restore_workspace(  # pyright: ignore[reportPrivateUsage]
        workspace_id,
        persisted,
    )
    assert len(_trace_artifacts(restored, restored._runs[run.id])) == 2  # pyright: ignore[reportPrivateUsage]

    learning_artifact_ids = [
        item["id"] for item in persisted["artifacts"] if item["kind"] == "learning_trace"
    ]
    assert len(learning_artifact_ids) == 2
    for removed_artifact_id in learning_artifact_ids:
        missing_trace = deepcopy(persisted)
        missing_trace["artifacts"] = [
            item for item in missing_trace["artifacts"] if item["id"] != removed_artifact_id
        ]
        missing_trace["events"] = [
            item
            for item in missing_trace["events"]
            if not (
                item["event_type"] == "artifact.published"
                and item["payload"].get("artifact_id") == removed_artifact_id
            )
        ]
        _renumber_persisted_events(missing_trace)
        _rebind_learning_trace_event_refs(missing_trace)
        rejected_restore = QuantStore()
        with pytest.raises(ValueError, match="learning trace is missing"):
            rejected_restore._restore_workspace(  # pyright: ignore[reportPrivateUsage]
                workspace_id,
                missing_trace,
            )
        assert rejected_restore._runs == {}  # pyright: ignore[reportPrivateUsage]
        assert rejected_restore._artifacts == {}  # pyright: ignore[reportPrivateUsage]


def test_exact_remove_only_repair_is_reused_before_execution_and_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    source = _create_run(store, workspace_id=workspace_id, suffix="source")
    trace = _resolved_episode(store, source)

    monkeypatch.setenv("POKIEQUANT_AGENT_PROVIDER", "deepseek")
    monkeypatch.setenv("POKIEQUANT_AGENT_MODEL", "test-model")
    target = _create_run(store, workspace_id=workspace_id, suffix="target")
    baseline_sequence = target.latest_sequence
    assert target.repair_memory is not None
    assert target.repair_memory.entries[0].source_trace_ids == [trace.trace_id]

    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="reuse-runner")
    assert claim is not None
    result = QuantAgentRunner(
        store=store,
        provider=_InvalidInspectProvider(),  # type: ignore[arg-type]
    ).run_step(claim=claim)
    assert result.did_work and not result.terminal

    events = [
        event
        for event in store.events_for_run(workspace_id=workspace_id, run_id=target.id)
        if event["sequence"] > baseline_sequence
    ]
    assert [event["event_type"] for event in events] == [
        "agent.action_selected",
        "agent.repair_memory_reused",
        "tool.started",
        "tool.completed",
    ]
    assert events[0]["payload"]["arguments"] == {}
    assert events[2]["payload"]["arguments"] == {}
    assert all(event["event_type"] != "tool.failed" for event in events)
    receipt = events[1]["payload"]["repair_memory_reuse"]
    assert receipt["source_trace_ids"] == [str(trace.trace_id)]
    assert receipt["changed_paths"] == ["unexpected"]
    assert "arguments" not in receipt

    snapshot = quant_agent_workspace_snapshot(
        workspace_id=workspace_id,
        run_id=target.id,
    )
    assert snapshot is not None
    assert "agent.repair_memory_reused" not in {event["type"] for event in snapshot["events"]}
    source_snapshot = quant_agent_workspace_snapshot(
        workspace_id=workspace_id,
        run_id=source.id,
    )
    assert source_snapshot is not None
    assert all(
        artifact["id"] not in {item.id for item in _trace_artifacts(store, source)}
        for artifact in source_snapshot["artifacts"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "digest",
        "future",
        "truncated",
        "event_order",
        "correction_action_mismatch",
        "crosses_prior_outcome",
        "cross_workspace",
    ],
)
def test_restore_rejects_invalid_learning_trace_atomically(mutation: str) -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    run = _create_run(store, workspace_id=workspace_id, suffix=f"restore-{mutation}")
    _resolved_episode(store, run)
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    tampered = deepcopy(baseline)
    artifact = next(item for item in tampered["artifacts"] if item["kind"] == "learning_trace")
    if mutation == "digest":
        artifact["content"]["provider"] = "tampered"
    elif mutation == "future":
        artifact["content"]["schema_version"] = "quant-learning-trace-v2"
        artifact["digest"] = canonical_digest(artifact["content"])
    elif mutation == "truncated":
        artifact["content"].pop("outcome_event")
        artifact["digest"] = canonical_digest(artifact["content"])
    elif mutation == "event_order":
        artifact["content"]["outcome_event"]["sequence"] = artifact["content"]["failed_event"][
            "sequence"
        ]
        artifact["digest"] = canonical_digest(artifact["content"])
    elif mutation == "correction_action_mismatch":
        correction_event_id = artifact["content"]["correction_started_event"]["event_id"]
        correction_event = next(
            event for event in tampered["events"] if event["id"] == correction_event_id
        )
        correction_event["payload"]["action"] = "list_strategy_templates"
        _rebind_learning_trace_event_refs(tampered)
    elif mutation == "crosses_prior_outcome":
        failed_event_id = artifact["content"]["failed_event"]["event_id"]
        run_events = [event for event in tampered["events"] if event["run_id"] == str(run.id)]
        failed_index = next(
            index for index, event in enumerate(run_events) if event["id"] == failed_event_id
        )
        rejected_started = run_events[failed_index - 1]
        assert rejected_started["event_type"] == "tool.started"
        artifact["content"]["correction_started_event"]["event_id"] = rejected_started["id"]
        _rebind_learning_trace_event_refs(tampered)
    else:
        artifact["content"]["workspace_id"] = str(uuid4())
        artifact["digest"] = canonical_digest(artifact["content"])

    with pytest.raises((TypeError, ValueError)):
        store._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            tampered,
        )
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


def test_restore_rejects_recomputed_stopped_action_tamper_atomically() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    run = _create_run(store, workspace_id=workspace_id, suffix="stopped-action-restore")
    rejected = _execute(
        store,
        run,
        _decision(
            QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
            {"unexpected": True},
        ),
        worker="stopped-action-invalid",
    )
    assert rejected.repair is not None
    claim = store.claim_agent_run(
        workspace_id=workspace_id,
        worker_id="stopped-action-guard",
    )
    assert claim is not None
    assert store.record_agent_contract_repair_exhausted(
        claim,
        rejected_action=rejected.action.value,
        attempted_action=QuantAgentAction.FINISH_RESEARCH.value,
        rejected_call_fingerprint=rejected.repair.call_fingerprint,
        attempted_call_fingerprint=canonical_digest(
            {
                "action": QuantAgentAction.FINISH_RESEARCH.value,
                "arguments": {},
            }
        ),
    )

    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    tampered = deepcopy(baseline)
    changed_event_digests: dict[str, str] = {}
    for event_type in ("agent.decision_failed", "run.failed"):
        source_event = next(
            event
            for event in store._events[run.id]  # pyright: ignore[reportPrivateUsage]
            if event.event_type == event_type
            and event.payload.get("reason_code") == "agent_contract_repair_exhausted"
        )
        forged_event = deepcopy(source_event)
        forged_event.payload["rejected_action"] = QuantAgentAction.FINISH_RESEARCH.value
        changed_event_digests[source_event.id] = store._learning_event_digest(  # pyright: ignore[reportPrivateUsage]
            forged_event
        )
        persisted_event = next(
            event for event in tampered["events"] if event["id"] == source_event.id
        )
        persisted_event["payload"]["rejected_action"] = QuantAgentAction.FINISH_RESEARCH.value

    artifact = next(item for item in tampered["artifacts"] if item["kind"] == "learning_trace")
    outcome_ref = artifact["content"]["outcome_event"]
    outcome_ref["event_digest"] = changed_event_digests[outcome_ref["event_id"]]
    for supporting_ref in artifact["content"]["supporting_events"]:
        supporting_ref["event_digest"] = changed_event_digests[supporting_ref["event_id"]]
    artifact["digest"] = canonical_digest(artifact["content"])

    with pytest.raises(ValueError, match="stopped learning trace"):
        store._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            tampered,
        )
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


def test_legacy_restore_does_not_backfill_learning_trace_or_repair_memory() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    run = _create_run(store, workspace_id=workspace_id, suffix="legacy")
    _resolved_episode(store, run)
    legacy = deepcopy(store._workspace_state(workspace_id))  # pyright: ignore[reportPrivateUsage]
    trace_ids = {item["id"] for item in legacy["artifacts"] if item["kind"] == "learning_trace"}
    legacy["artifacts"] = [item for item in legacy["artifacts"] if item["id"] not in trace_ids]
    legacy["events"] = [
        item
        for item in legacy["events"]
        if not (
            item["event_type"] == "artifact.published"
            and item["payload"].get("artifact_id") in trace_ids
        )
    ]
    for item in legacy["runs"]:
        item.pop("repair_memory", None)
    legacy.pop("verified_learning_policy", None)
    _renumber_persisted_events(legacy)

    restored = QuantStore()
    restored._restore_workspace(  # pyright: ignore[reportPrivateUsage]
        workspace_id,
        legacy,
        repository_memory_contract_version=RESEARCH_MEMORY_CONTRACT_VERSION,
    )
    restored._loaded_workspaces.add(workspace_id)  # pyright: ignore[reportPrivateUsage]
    restored_run = restored.get_run(workspace_id=workspace_id, run_id=run.id)
    assert restored_run.repair_memory is None
    assert _trace_artifacts(restored, restored_run) == []


def test_external_repository_marker_blocks_full_new_pin_downgrade() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    run = _create_run(store, workspace_id=workspace_id, suffix="pin-downgrade")
    _resolved_episode(store, run)
    with store._session_factory() as db:  # pyright: ignore[reportPrivateUsage]
        repository = db.get(QuantRepositoryState, workspace_id)
        assert repository is not None
        repository_marker = repository.research_memory_contract_version
        assert repository_marker.startswith(VERIFIED_LEARNING_REPOSITORY_CONTRACT_VERSION)
        assert len(repository_marker) <= 64
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    stripped = deepcopy(baseline)
    trace_ids = {item["id"] for item in stripped["artifacts"] if item["kind"] == "learning_trace"}
    stripped.pop("verified_learning_policy")
    for persisted_run in stripped["runs"]:
        persisted_run.pop("repair_memory", None)
    stripped["artifacts"] = [item for item in stripped["artifacts"] if item["id"] not in trace_ids]
    stripped["events"] = [
        item
        for item in stripped["events"]
        if item["event_type"]
        not in {
            "agent.action_selected",
            "tool.started",
            "tool.failed",
            "tool.completed",
        }
        and not (
            item["event_type"] == "artifact.published"
            and item["payload"].get("artifact_id") in trace_ids
        )
    ]
    _renumber_persisted_events(stripped)

    with pytest.raises(ValueError, match="policy marker is missing"):
        store._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            stripped,
            repository_memory_contract_version=repository_marker,
        )
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


def test_external_marker_binds_every_current_repair_memory_pin() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    anchor = _create_run(store, workspace_id=workspace_id, suffix="policy-anchor")
    _terminalize(store, anchor, "Retain one independent pinned policy anchor.")
    source = _create_run(store, workspace_id=workspace_id, suffix="policy-source")
    _resolved_episode(store, source)
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    with store._session_factory() as db:  # pyright: ignore[reportPrivateUsage]
        repository = db.get(QuantRepositoryState, workspace_id)
        assert repository is not None
        repository_marker = repository.research_memory_contract_version
        assert repository_marker.startswith(VERIFIED_LEARNING_REPOSITORY_CONTRACT_VERSION)
        assert len(repository_marker) <= 64

    restored = QuantStore(session_factory=store._session_factory)  # pyright: ignore[reportPrivateUsage]
    assert restored.get_run(workspace_id=workspace_id, run_id=anchor.id).repair_memory is not None
    assert restored.get_run(workspace_id=workspace_id, run_id=source.id).repair_memory is not None

    direct = QuantStore()
    direct._restore_workspace(  # pyright: ignore[reportPrivateUsage]
        workspace_id,
        baseline,
        repository_memory_contract_version=repository_marker,
    )
    assert direct._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    stripped = deepcopy(baseline)
    persisted_source = next(item for item in stripped["runs"] if item["id"] == source.id)
    persisted_source.pop("repair_memory")
    policy = stripped["verified_learning_policy"]
    policy["pins"].pop(source.id)
    policy["policy_digest"] = canonical_digest(
        {
            "schema_version": policy["schema_version"],
            "pins": policy["pins"],
        }
    )
    trace_ids = {
        item["id"]
        for item in stripped["artifacts"]
        if item["kind"] == "learning_trace" and item["run_id"] == source.id
    }
    stripped["artifacts"] = [item for item in stripped["artifacts"] if item["id"] not in trace_ids]
    stripped["events"] = [
        item
        for item in stripped["events"]
        if not (
            item["run_id"] == source.id
            and item["event_type"]
            in {
                "agent.action_selected",
                "tool.started",
                "tool.failed",
                "tool.completed",
            }
        )
        and not (
            item["event_type"] == "artifact.published"
            and item["payload"].get("artifact_id") in trace_ids
        )
    ]
    _renumber_persisted_events(stripped)

    rejected = QuantStore()
    with pytest.raises(ValueError, match="repository marker does not match"):
        rejected._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            stripped,
            repository_memory_contract_version=repository_marker,
        )
    assert rejected._runs == {}  # pyright: ignore[reportPrivateUsage]
    assert rejected._artifacts == {}  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ValueError, match="unsupported"):
        QuantStore()._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            baseline,
            repository_memory_contract_version=("quant-research-memory-v1+verified-learning-v1"),
        )


def test_restore_rejects_duplicate_learning_publication_sequence() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    run = _create_run(store, workspace_id=workspace_id, suffix="trace-sequence")
    _resolved_episode(store, run)
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    tampered = deepcopy(baseline)
    trace_id = next(
        item["id"] for item in tampered["artifacts"] if item["kind"] == "learning_trace"
    )
    publication = next(
        item
        for item in tampered["events"]
        if item["event_type"] == "artifact.published"
        and item["payload"].get("artifact_id") == trace_id
    )
    later_run_failure = next(
        item
        for item in tampered["events"]
        if item["event_type"] == "run.failed" and item["sequence"] > publication["sequence"]
    )
    publication["sequence"] = later_run_failure["sequence"]

    with pytest.raises(ValueError, match="event sequences"):
        store._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            tampered,
        )
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


def test_restore_rejects_duplicate_reuse_receipt_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    source = _create_run(store, workspace_id=workspace_id, suffix="receipt-sequence-source")
    _resolved_episode(store, source)
    monkeypatch.setenv("POKIEQUANT_AGENT_PROVIDER", "deepseek")
    monkeypatch.setenv("POKIEQUANT_AGENT_MODEL", "test-model")
    target = _create_run(store, workspace_id=workspace_id, suffix="receipt-sequence-target")
    claim = store.claim_agent_run(
        workspace_id=workspace_id,
        worker_id="receipt-sequence",
    )
    assert claim is not None
    result = QuantAgentRunner(
        store=store,
        provider=_InvalidInspectProvider(),  # type: ignore[arg-type]
    ).run_step(claim=claim)
    assert result.did_work and not result.terminal

    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    tampered = deepcopy(baseline)
    target_events = [item for item in tampered["events"] if item["run_id"] == target.id]
    receipt = next(
        item for item in target_events if item["event_type"] == "agent.repair_memory_reused"
    )
    selected = next(
        item
        for item in target_events
        if item["event_type"] == "agent.action_selected" and item["sequence"] < receipt["sequence"]
    )
    receipt["sequence"] = selected["sequence"]

    with pytest.raises(ValueError, match="event sequences"):
        store._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            tampered,
        )
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


def test_retry_and_continue_retain_the_required_pin_semantics() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    source_trace_run = _create_run(store, workspace_id=workspace_id, suffix="pin-source")
    _resolved_episode(store, source_trace_run)
    source = _create_run(store, workspace_id=workspace_id, suffix="lineage")
    assert source.repair_memory is not None

    candidate = QuantExperimentRecord(
        id=str(uuid4()),
        workspace_id=workspace_id,
        run_id=source.id,
        ordinal=1,
        name="Seed breakout",
        hypothesis="Retain one bounded valid seed.",
        verdict=QuantExperimentVerdict.VIABLE,
        summary="Seed retained.",
        template="breakout",
        parameters={"lookback_window": 40},
        state="completed",
        candidate_key=store.canonical_candidate_key("breakout", {"lookback_window": 40}),
    )
    store._experiments[candidate.id] = candidate  # pyright: ignore[reportPrivateUsage]
    source.state = QuantRunState.FAILED
    source.agent_status = "failed"
    source.failure_reason = "Focused lineage setup."
    source.updated_at = datetime.now(UTC)
    store._append_event(  # pyright: ignore[reportPrivateUsage]
        source,
        "run.failed",
        {
            "state": QuantRunState.FAILED,
            "reason_code": "focused_lineage_setup",
            "safe_summary": source.failure_reason,
        },
    )
    store._persist_workspace(workspace_id)  # pyright: ignore[reportPrivateUsage]

    retry = store.retry_run(
        workspace_id=workspace_id,
        run_id=source.id,
        expected_row_version=source.row_version,
        reason="Verify exact repair pin clone.",
    )
    assert retry.repair_memory is not None
    assert retry.repair_memory.model_dump(mode="json") == source.repair_memory.model_dump(
        mode="json"
    )

    project = store.get_project(workspace_id=workspace_id, project_id=source.project_id)
    continued = store.create_run(
        workspace_id=workspace_id,
        project_id=source.project_id,
        question="Continue with the retained verified repair pin.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=project.row_version,
        parent_run_id=source.id,
        seed_candidate_id=candidate.id,
        refinement_reason="Test one independent bounded continuation.",
    )
    assert continued.repair_memory is not None
    expected = store._build_repair_memory_pin(continued)  # pyright: ignore[reportPrivateUsage]
    assert continued.repair_memory.model_dump(mode="json") == expected.model_dump(mode="json")


def test_conflicting_correction_signatures_are_ineligible_and_preserve_r0() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    source = _create_run(store, workspace_id=workspace_id, suffix="conflict-source")
    _resolved_episode(store, source)
    target = _create_run(store, workspace_id=workspace_id, suffix="conflict-target")
    original = _trace_artifacts(store, source)[0]
    conflicting = deepcopy(original)
    conflicting.id = str(uuid4())
    conflicting.content["trace_id"] = str(uuid4())
    conflicting.content["violations"][0]["path"] = "different"
    conflicting.content["correction_delta"][0]["path"] = "different"
    conflicting.digest = canonical_digest(conflicting.content)
    artifacts = dict(store._artifacts)  # pyright: ignore[reportPrivateUsage]
    artifacts[conflicting.id] = conflicting
    memory = store._compose_repair_memory_pin(  # pyright: ignore[reportPrivateUsage]
        target,
        runs=store._runs,  # pyright: ignore[reportPrivateUsage]
        artifacts=artifacts,
    )
    assert memory.entries == []

    runner = QuantAgentRunner(store=store, provider=_InvalidInspectProvider())  # type: ignore[arg-type]
    proposed = _decision(
        QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
        {"unexpected": True},
    )
    unchanged, receipt = runner._reuse_verified_repair(  # pyright: ignore[reportPrivateUsage]
        decision=proposed,
        memory=memory,
    )
    assert unchanged == proposed
    assert receipt is None


def test_reuse_receipt_write_rolls_back_on_uncommitted_persistence_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    source = _create_run(store, workspace_id=workspace_id, suffix="rollback-source")
    _resolved_episode(store, source)
    target = _create_run(store, workspace_id=workspace_id, suffix="rollback-target")
    assert target.repair_memory is not None
    runner = QuantAgentRunner(store=store, provider=_InvalidInspectProvider())  # type: ignore[arg-type]
    proposed = _decision(
        QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
        {"unexpected": True},
    )
    corrected, receipt = runner._reuse_verified_repair(  # pyright: ignore[reportPrivateUsage]
        decision=proposed,
        memory=target.repair_memory,
    )
    assert receipt is not None
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="rollback")
    assert claim is not None
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    with store._session_factory() as db:  # pyright: ignore[reportPrivateUsage]
        repository = db.get(QuantRepositoryState, workspace_id)
        assert repository is not None
        baseline_repository_marker = repository.research_memory_contract_version

    def fail_write(_: str) -> None:
        raise RuntimeError("injected uncommitted write failure")

    monkeypatch.setattr(store, "_persist_workspace", fail_write)
    with pytest.raises(RuntimeError, match="injected"):
        store.record_agent_decision(
            claim,
            corrected,
            reuse_receipt=receipt,
        )
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
    with store._session_factory() as db:  # pyright: ignore[reportPrivateUsage]
        repository = db.get(QuantRepositoryState, workspace_id)
        assert repository is not None
        assert repository.research_memory_contract_version == baseline_repository_marker


def test_learning_trace_write_rolls_back_with_its_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    run = _create_run(store, workspace_id=workspace_id, suffix="trace-rollback")
    rejected = _execute(
        store,
        run,
        _decision(
            QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
            {"unexpected": True},
        ),
        worker="trace-rollback-invalid",
    )
    assert rejected.error_code == "INVALID_ARGUMENTS"

    claim = store.claim_agent_run(
        workspace_id=workspace_id,
        worker_id="trace-rollback-corrected",
    )
    assert claim is not None
    corrected = _decision(QuantAgentAction.INSPECT_RESEARCH_CONTEXT, {})
    assert store.record_agent_decision(claim, corrected)
    observation = QuantToolRegistry().execute(
        action=corrected.action,
        arguments=corrected.arguments,
        context=QuantToolExecutionContext(store=store, lease=claim),
    )
    assert observation.success
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    def fail_write(_: str) -> None:
        raise RuntimeError("injected trace write failure")

    monkeypatch.setattr(store, "_persist_workspace", fail_write)
    with pytest.raises(RuntimeError, match="injected"):
        store.complete_agent_step(claim, observation)
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
    assert _trace_artifacts(store, run) == []


def test_incompatible_or_unknown_repair_memory_preserves_r0_path() -> None:
    workspace_id = str(uuid4())
    store = QuantStore()
    source = _create_run(store, workspace_id=workspace_id, suffix="compat-source")
    _resolved_episode(store, source)
    target = _create_run(store, workspace_id=workspace_id, suffix="compat-target")
    assert target.repair_memory is not None
    runner = QuantAgentRunner(store=store, provider=_InvalidInspectProvider())  # type: ignore[arg-type]
    proposed = _decision(
        QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
        {"another_unknown": True},
    )
    unchanged, receipt = runner._reuse_verified_repair(  # pyright: ignore[reportPrivateUsage]
        decision=proposed,
        memory=target.repair_memory,
    )
    assert unchanged == proposed
    assert receipt is None

    incompatible_payload = target.repair_memory.model_dump(
        mode="json",
        exclude={"context_digest"},
    )
    incompatible_payload["entries"][0]["tool"]["input_schema_digest"] = "sha256:" + "0" * 64
    incompatible = QuantRepairMemory.model_validate(
        {
            **incompatible_payload,
            "context_digest": canonical_digest(incompatible_payload),
        }
    )
    unchanged, receipt = runner._reuse_verified_repair(  # pyright: ignore[reportPrivateUsage]
        decision=_decision(
            QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
            {"unexpected": True},
        ),
        memory=incompatible,
    )
    assert receipt is None
    claim = store.claim_agent_run(
        workspace_id=workspace_id,
        worker_id="compat-r0",
    )
    assert claim is not None
    observation = QuantToolRegistry().execute(
        action=unchanged.action,
        arguments=unchanged.arguments,
        context=QuantToolExecutionContext(
            store=store,
            lease=claim,
        ),
    )
    assert observation.error_code == "INVALID_ARGUMENTS"
    assert observation.repair is not None


def _trace_tool_identity() -> QuantToolIdentity:
    return QuantToolIdentity(
        registry_version="quant-agent-tool-registry-v1",
        action=QuantAgentAction.CREATE_CANDIDATE,
        tool_version="quant-agent-create-candidate-v1",
        input_schema_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )


def _event_digest(
    event_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
    workspace_id: str,
    run_id: str,
    trace_id: str,
) -> str:
    return canonical_digest(
        {
            "event_id": event_id,
            "workspace_id": workspace_id,
            "run_id": run_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload_digest": canonical_digest(payload),
            "trace_id": trace_id,
            "occurred_at": datetime.now(UTC),
        }
    )


def _make_replan_repair_events(
    *,
    workspace_id: str,
    run_id: str,
    trace_id: str,
    candidate_id: str,
    reference_candidate_id: str,
    rejected_action: str = "refine_parameters",
    corrected_action: str = "switch_approved_family",
    change_other_field: bool = False,
) -> tuple[list[dict[str, Any]], QuantLearningTrace]:
    rejected_started_id = str(uuid4())
    failed_id = str(uuid4())
    corrected_started_id = str(uuid4())
    outcome_id = str(uuid4())

    base_arguments: dict[str, Any] = {
        "name": "Candidate C",
        "template": "breakout",
        "hypothesis": "Test whether a long-horizon breakout remains robust with sparse trades.",
        "parameters": {"lookback_window": 40},
        "change_rationale": "Switch family based on the train-only observation.",
        "replan_decision": {
            "action": rejected_action,
            "source_comparison_artifact_id": "comparison-a-b",
            "improvement_reference_candidate_id": reference_candidate_id,
        },
    }
    corrected_arguments = deepcopy(base_arguments)
    corrected_arguments["replan_decision"]["action"] = corrected_action
    if change_other_field:
        corrected_arguments["parameters"] = {"lookback_window": 50}

    rejected_started_payload = {
        "action": "create_candidate",
        "arguments": base_arguments,
        "call_fingerprint": canonical_digest(
            {"action": "create_candidate", "arguments": base_arguments}
        ),
    }
    failed_payload = {
        **rejected_started_payload,
        "error_code": "INVALID_ARGUMENTS",
        "tool_repair": {
            "action": "create_candidate",
            "call_fingerprint": rejected_started_payload["call_fingerprint"],
            "violations": [
                {
                    "path": "replan_decision.action",
                    "code": "invalid_value",
                    "required_change": "replace",
                }
            ],
        },
    }
    corrected_started_payload = {
        "action": "create_candidate",
        "arguments": corrected_arguments,
        "call_fingerprint": canonical_digest(
            {"action": "create_candidate", "arguments": corrected_arguments}
        ),
    }
    outcome_payload = {
        "action": "create_candidate",
        "success": True,
        "candidate_id": candidate_id,
        "artifact_ids": [],
        "safe_summary": "Candidate C was created.",
    }

    events: list[dict[str, Any]] = [
        {
            "event_id": rejected_started_id,
            "sequence": 1,
            "event_type": "tool.started",
            "timestamp": datetime.now(UTC),
            "actor": "agent",
            "payload": rejected_started_payload,
        },
        {
            "event_id": failed_id,
            "sequence": 2,
            "event_type": "tool.failed",
            "timestamp": datetime.now(UTC),
            "actor": "agent",
            "payload": failed_payload,
        },
        {
            "event_id": corrected_started_id,
            "sequence": 3,
            "event_type": "tool.started",
            "timestamp": datetime.now(UTC),
            "actor": "agent",
            "payload": corrected_started_payload,
        },
        {
            "event_id": outcome_id,
            "sequence": 4,
            "event_type": "tool.completed",
            "timestamp": datetime.now(UTC),
            "actor": "agent",
            "payload": outcome_payload,
        },
    ]

    trace = QuantLearningTrace(
        trace_id=UUID(trace_id),
        workspace_id=workspace_id,
        run_id=UUID(run_id),
        attempt_number=1,
        provider="mock",
        model=None,
        selection_objective="risk_adjusted_return",
        context_identity_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        tool=_trace_tool_identity(),
        failed_event=QuantLearningEventRef(
            event_id=UUID(failed_id),
            sequence=2,
            event_digest=_event_digest(
                failed_id, 2, "tool.failed", failed_payload, workspace_id, run_id, trace_id
            ),
        ),
        failed_call_fingerprint=rejected_started_payload["call_fingerprint"],
        error_code="INVALID_ARGUMENTS",
        violations=[
            QuantLearningViolation(
                path="replan_decision.action",
                code="invalid_value",
                required_change="replace",
            )
        ],
        correction_delta=[
            QuantLearningFieldDelta(
                path="replan_decision.action",
                change="replace",
                before_digest=canonical_digest("refine_parameters"),
                after_digest=canonical_digest("switch_approved_family"),
            )
        ],
        correction_started_event=QuantLearningEventRef(
            event_id=UUID(corrected_started_id),
            sequence=3,
            event_digest=_event_digest(
                corrected_started_id,
                3,
                "tool.started",
                corrected_started_payload,
                workspace_id,
                run_id,
                trace_id,
            ),
        ),
        corrected_call_fingerprint=corrected_started_payload["call_fingerprint"],
        outcome="resolved",
        outcome_event=QuantLearningEventRef(
            event_id=UUID(outcome_id),
            sequence=4,
            event_digest=_event_digest(
                outcome_id, 4, "tool.completed", outcome_payload, workspace_id, run_id, trace_id
            ),
        ),
        supporting_events=[],
        closed_at=datetime.now(UTC),
    )
    return events, trace


def _make_learning_trace_artifact(trace: QuantLearningTrace) -> Any:
    return SimpleNamespace(
        kind=QuantArtifactKind.LEARNING_TRACE,
        content=trace.model_dump(mode="json"),
    )


def test_replan_repair_projection_exact_action_only() -> None:
    workspace_id = str(uuid4())
    run_id = str(uuid4())
    trace_id = str(uuid4())
    candidate_id = "candidate-c"
    reference_candidate_id = "candidate-b"
    events, trace = _make_replan_repair_events(
        workspace_id=workspace_id,
        run_id=run_id,
        trace_id=trace_id,
        candidate_id=candidate_id,
        reference_candidate_id=reference_candidate_id,
    )
    artifact = _make_learning_trace_artifact(trace)
    projection = _project_replan_repair([artifact], events, candidate_id)
    assert projection == {
        "rejectedAction": "refine_parameters",
        "correctedAction": "switch_approved_family",
        "retainedInputs": True,
        "outcome": "candidate_created",
    }


def test_replan_repair_projection_omits_when_other_input_changes() -> None:
    workspace_id = str(uuid4())
    run_id = str(uuid4())
    trace_id = str(uuid4())
    candidate_id = "candidate-c"
    reference_candidate_id = "candidate-b"
    events, trace = _make_replan_repair_events(
        workspace_id=workspace_id,
        run_id=run_id,
        trace_id=trace_id,
        candidate_id=candidate_id,
        reference_candidate_id=reference_candidate_id,
        change_other_field=True,
    )
    artifact = _make_learning_trace_artifact(trace)
    assert _project_replan_repair([artifact], events, candidate_id) is None


def test_replan_repair_projection_omits_with_ambiguous_second_trace() -> None:
    workspace_id = str(uuid4())
    run_id = str(uuid4())
    trace_id = str(uuid4())
    candidate_id = "candidate-c"
    reference_candidate_id = "candidate-b"
    events, trace = _make_replan_repair_events(
        workspace_id=workspace_id,
        run_id=run_id,
        trace_id=trace_id,
        candidate_id=candidate_id,
        reference_candidate_id=reference_candidate_id,
    )
    second_trace = trace.model_copy(update={"trace_id": UUID(str(uuid4()))})
    all_artifacts = [
        _make_learning_trace_artifact(trace),
        _make_learning_trace_artifact(second_trace),
    ]
    assert _project_replan_repair(all_artifacts, events, candidate_id) is None


def test_replan_repair_projection_omits_for_wrong_candidate() -> None:
    workspace_id = str(uuid4())
    run_id = str(uuid4())
    trace_id = str(uuid4())
    candidate_id = "candidate-c"
    reference_candidate_id = "candidate-b"
    events, trace = _make_replan_repair_events(
        workspace_id=workspace_id,
        run_id=run_id,
        trace_id=trace_id,
        candidate_id=candidate_id,
        reference_candidate_id=reference_candidate_id,
    )
    artifact = _make_learning_trace_artifact(trace)
    assert _project_replan_repair([artifact], events, "candidate-other") is None


@pytest.mark.parametrize(
    ("event_index", "field", "value"),
    [
        (1, "action", "run_backtest"),
        (3, "action", "run_backtest"),
        (3, "success", False),
    ],
)
def test_replan_repair_projection_requires_matching_successful_tool_outcome(
    event_index: int,
    field: str,
    value: object,
) -> None:
    workspace_id = str(uuid4())
    run_id = str(uuid4())
    candidate_id = "candidate-c"
    events, trace = _make_replan_repair_events(
        workspace_id=workspace_id,
        run_id=run_id,
        trace_id=str(uuid4()),
        candidate_id=candidate_id,
        reference_candidate_id="candidate-b",
    )
    events[event_index]["payload"][field] = value
    assert (
        _project_replan_repair(
            [_make_learning_trace_artifact(trace)],
            events,
            candidate_id,
        )
        is None
    )
