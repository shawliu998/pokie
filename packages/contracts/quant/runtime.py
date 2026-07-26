"""Narrow QuantExecutionRuntime-shaped port: deterministic fixture script and plan steps.

This module is the single source of truth for the canonical Phase 0 fixture
sequence. The API fixture seeding and the worker fixture pipeline both build
from it, so a replayed run always produces the same ordered events, artifacts,
and experiments. No market data, network, broker, or execution logic exists
here; every value is a deterministic fixture labelled with its authenticity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from .enums import (
    QuantArtifactKind,
    QuantCandidateVerdict,
    QuantDataAuthenticity,
    QuantEventType,
    QuantFixtureScenario,
    QuantRunState,
    QuantStepStatus,
)
from .events import QuantEventPayload

QUANT_NAMESPACE = UUID("3f6b2a41-9c2e-4b7d-9a1e-2f5c8d0e1a34")
QUANT_FIXTURE_BASE_TIME = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)

QUANT_CANDIDATE_KEYS = ("A", "B", "C")


def quant_deterministic_id(kind: str, *parts: object) -> str:
    return str(uuid5(QUANT_NAMESPACE, repr((kind, *parts))))


def quant_fixture_digest(kind: str, *parts: object) -> str:
    payload = repr((kind, *parts)).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class QuantPlanStepDef:
    key: str
    title: str
    owner: str


QUANT_PLAN_STEP_DEFS: tuple[QuantPlanStepDef, ...] = (
    QuantPlanStepDef("define_scope", "Define research scope", "user"),
    QuantPlanStepDef("load_dataset", "Load market dataset", "system"),
    QuantPlanStepDef("build_benchmark", "Build benchmark", "system"),
    QuantPlanStepDef("generate_candidates", "Generate candidates", "agent"),
    QuantPlanStepDef("run_experiments", "Run experiments", "agent"),
    QuantPlanStepDef("repair_failures", "Repair failures", "agent"),
    QuantPlanStepDef("validate_robustness", "Validate robustness", "validator"),
    QuantPlanStepDef("compare_candidates", "Compare candidates", "agent"),
    QuantPlanStepDef("generate_report", "Generate report", "agent"),
    QuantPlanStepDef("human_decision", "Human decision", "user"),
)


@dataclass(frozen=True, slots=True)
class QuantArtifactSpec:
    artifact_id: str
    kind: QuantArtifactKind
    label: str
    digest: str


@dataclass(frozen=True, slots=True)
class QuantExperimentSpec:
    experiment_id: str
    candidate_id: str
    candidate_key: str
    candidate_name: str
    verdict: QuantCandidateVerdict | None
    metrics: dict[str, Any]
    repair_count: int


@dataclass(frozen=True, slots=True)
class QuantScriptStep:
    """One deterministic script beat: an event plus its owned side effects."""

    event_type: QuantEventType
    run_state: QuantRunState
    payload: QuantEventPayload
    artifact: QuantArtifactSpec | None = None
    experiment: QuantExperimentSpec | None = None
    conclusion: str | None = None
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class QuantClaim:
    """A fenced worker claim on one approved run attempt."""

    run_id: str
    workspace_id: str
    fence_token: str
    scenario: QuantFixtureScenario
    attempt_number: int
    plan_version_id: str | None
    base_time: datetime


def quant_candidate_id(run_id: str, candidate_key: str) -> str:
    return quant_deterministic_id("quant-candidate", run_id, candidate_key)


def quant_artifact_id(run_id: str, kind: QuantArtifactKind, key: str = "") -> str:
    return quant_deterministic_id("quant-artifact", run_id, kind.value, key)


def quant_experiment_id(run_id: str, candidate_key: str) -> str:
    return quant_deterministic_id("quant-experiment", run_id, candidate_key)


def _fixture_metrics(run_id: str, candidate_key: str) -> dict[str, Any]:
    digest = hashlib.sha256(f"quant-metrics:{run_id}:{candidate_key}".encode()).digest()

    def scale(index: int, modulo: int) -> float:
        return round(digest[index] % modulo / 1000, 3)

    return {
        "cagr": scale(0, 220),
        "max_drawdown": scale(1, 35),
        "sharpe": scale(2, 2400),
        "win_rate": scale(3, 900),
        "fixture": True,
    }


def _candidate_name(candidate_key: str) -> str:
    return f"Fixture Candidate {candidate_key}"


def build_quant_script(
    *,
    run_id: str,
    scenario: QuantFixtureScenario,
    authenticity: QuantDataAuthenticity = QuantDataAuthenticity.SYNTHETIC_FIXTURE,
) -> tuple[QuantScriptStep, ...]:
    """Build the deterministic worker script for one approved run attempt.

    The canonical script reproduces the Phase 0 reference sequence, including
    Candidate B's recoverable candidate-scoped failure and repair. ``no_viable``
    rejects every candidate while keeping the run healthy. ``failed_safe``
    stops safely during Candidate B's experiment with a persisted diagnostic.
    """

    del authenticity  # authenticity is carried by records, not by step content
    steps: list[QuantScriptStep] = []
    dataset_id = quant_artifact_id(run_id, QuantArtifactKind.DATASET_SNAPSHOT)
    benchmark_id = quant_artifact_id(run_id, QuantArtifactKind.BENCHMARK)
    report_id = quant_artifact_id(run_id, QuantArtifactKind.RESEARCH_REPORT)

    def candidate_payload(candidate_key: str, **extra: Any) -> QuantEventPayload:
        return QuantEventPayload(
            candidate_id=UUID(quant_candidate_id(run_id, candidate_key)),
            candidate_key=candidate_key,
            **extra,
        )

    def backtest_artifact(candidate_key: str) -> QuantArtifactSpec:
        return QuantArtifactSpec(
            artifact_id=quant_artifact_id(run_id, QuantArtifactKind.BACKTEST_RESULT, candidate_key),
            kind=QuantArtifactKind.BACKTEST_RESULT,
            label=f"Backtest result for Fixture Candidate {candidate_key}",
            digest=quant_fixture_digest("backtest", run_id, candidate_key),
        )

    def experiment(candidate_key: str, repair_count: int = 0) -> QuantExperimentSpec:
        return QuantExperimentSpec(
            experiment_id=quant_experiment_id(run_id, candidate_key),
            candidate_id=quant_candidate_id(run_id, candidate_key),
            candidate_key=candidate_key,
            candidate_name=_candidate_name(candidate_key),
            verdict=None,
            metrics=_fixture_metrics(run_id, candidate_key),
            repair_count=repair_count,
        )

    steps.append(
        QuantScriptStep(
            QuantEventType.DATA_LOAD_STARTED,
            QuantRunState.LOADING_DATA,
            QuantEventPayload(artifact_id=UUID(dataset_id)),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.DATA_LOAD_COMPLETED,
            QuantRunState.LOADING_DATA,
            QuantEventPayload(artifact_id=UUID(dataset_id)),
            artifact=QuantArtifactSpec(
                artifact_id=dataset_id,
                kind=QuantArtifactKind.DATASET_SNAPSHOT,
                label="Pinned fixture market dataset snapshot",
                digest=quant_fixture_digest("dataset", run_id),
            ),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.BENCHMARK_GENERATED,
            QuantRunState.GENERATING_CANDIDATES,
            QuantEventPayload(artifact_id=UUID(benchmark_id)),
            artifact=QuantArtifactSpec(
                artifact_id=benchmark_id,
                kind=QuantArtifactKind.BENCHMARK,
                label="Fixture benchmark series",
                digest=quant_fixture_digest("benchmark", run_id),
            ),
        )
    )

    # Candidate A completes cleanly.
    steps.append(
        QuantScriptStep(
            QuantEventType.CANDIDATE_GENERATED,
            QuantRunState.GENERATING_CANDIDATES,
            candidate_payload("A"),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.BACKTEST_STARTED,
            QuantRunState.RUNNING_EXPERIMENTS,
            candidate_payload("A"),
        )
    )
    if scenario == QuantFixtureScenario.FAILED_SAFE:
        diagnostics_id = quant_artifact_id(run_id, QuantArtifactKind.DIAGNOSTICS)
        steps.append(
            QuantScriptStep(
                QuantEventType.RUN_FAILED,
                QuantRunState.FAILED,
                QuantEventPayload(
                    run_state=QuantRunState.FAILED,
                    safe_summary=(
                        "Fixture worker stopped safely before Candidate B finished; "
                        "persisted events and artifacts are retained."
                    ),
                ),
                artifact=QuantArtifactSpec(
                    artifact_id=diagnostics_id,
                    kind=QuantArtifactKind.DIAGNOSTICS,
                    label="Safe worker diagnostics",
                    digest=quant_fixture_digest("diagnostics", run_id),
                ),
                terminal=True,
            )
        )
        return tuple(steps)

    steps.append(
        QuantScriptStep(
            QuantEventType.BACKTEST_COMPLETED,
            QuantRunState.RUNNING_EXPERIMENTS,
            candidate_payload("A", artifact_id=UUID(backtest_artifact("A").artifact_id)),
            artifact=backtest_artifact("A"),
            experiment=experiment("A"),
        )
    )

    if scenario == QuantFixtureScenario.CANCELLED:
        steps.append(
            QuantScriptStep(
                QuantEventType.RUN_CANCELLED,
                QuantRunState.CANCELLED,
                QuantEventPayload(
                    run_state=QuantRunState.CANCELLED,
                    safe_summary="Fixture run cancelled; previously persisted work is retained.",
                ),
                terminal=True,
            )
        )
        return tuple(steps)

    # Candidate B fails once (candidate-scoped, recoverable) then is repaired.
    steps.append(
        QuantScriptStep(
            QuantEventType.CANDIDATE_GENERATED,
            QuantRunState.GENERATING_CANDIDATES,
            candidate_payload("B"),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.BACKTEST_STARTED,
            QuantRunState.RUNNING_EXPERIMENTS,
            candidate_payload("B"),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.BACKTEST_FAILED,
            QuantRunState.REPAIRING,
            candidate_payload(
                "B",
                safe_summary="Candidate B fixture backtest stopped safely; repair is available.",
            ),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.REPAIR_STARTED,
            QuantRunState.REPAIRING,
            candidate_payload("B", repair_count=1),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.REPAIR_COMPLETED,
            QuantRunState.RUNNING_EXPERIMENTS,
            candidate_payload("B", repair_count=1),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.BACKTEST_STARTED,
            QuantRunState.RUNNING_EXPERIMENTS,
            candidate_payload("B", repair_count=1),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.BACKTEST_COMPLETED,
            QuantRunState.RUNNING_EXPERIMENTS,
            candidate_payload(
                "B", artifact_id=UUID(backtest_artifact("B").artifact_id), repair_count=1
            ),
            artifact=backtest_artifact("B"),
            experiment=experiment("B", repair_count=1),
        )
    )

    # Candidate C completes cleanly.
    steps.append(
        QuantScriptStep(
            QuantEventType.CANDIDATE_GENERATED,
            QuantRunState.GENERATING_CANDIDATES,
            candidate_payload("C"),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.BACKTEST_STARTED,
            QuantRunState.RUNNING_EXPERIMENTS,
            candidate_payload("C"),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.BACKTEST_COMPLETED,
            QuantRunState.RUNNING_EXPERIMENTS,
            candidate_payload("C", artifact_id=UUID(backtest_artifact("C").artifact_id)),
            artifact=backtest_artifact("C"),
            experiment=experiment("C"),
        )
    )

    steps.append(
        QuantScriptStep(
            QuantEventType.VALIDATION_STARTED, QuantRunState.VALIDATING, QuantEventPayload()
        )
    )
    no_viable = scenario == QuantFixtureScenario.NO_VIABLE
    verdicts = {
        "A": QuantCandidateVerdict.REJECTED,
        "B": QuantCandidateVerdict.REJECTED if no_viable else QuantCandidateVerdict.PROMISING,
        "C": QuantCandidateVerdict.REJECTED,
    }
    for key in QUANT_CANDIDATE_KEYS:
        verdict = verdicts[key]
        event_type = (
            QuantEventType.CANDIDATE_PROMOTED
            if verdict == QuantCandidateVerdict.PROMISING
            else QuantEventType.CANDIDATE_REJECTED
        )
        steps.append(
            QuantScriptStep(
                event_type,
                QuantRunState.VALIDATING,
                candidate_payload(
                    key,
                    experiment_id=UUID(quant_experiment_id(run_id, key)),
                    verdict=verdict,
                    reason_code=(
                        "robustness_checks_passed"
                        if verdict == QuantCandidateVerdict.PROMISING
                        else "robustness_checks_failed"
                    ),
                ),
                experiment=QuantExperimentSpec(
                    experiment_id=quant_experiment_id(run_id, key),
                    candidate_id=quant_candidate_id(run_id, key),
                    candidate_key=key,
                    candidate_name=_candidate_name(key),
                    verdict=verdict,
                    metrics=_fixture_metrics(run_id, key),
                    repair_count=1 if key == "B" else 0,
                ),
            )
        )
    steps.append(
        QuantScriptStep(
            QuantEventType.VALIDATION_COMPLETED,
            QuantRunState.GENERATING_REPORT,
            QuantEventPayload(),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.REPORT_GENERATED,
            QuantRunState.WAITING_FOR_REVIEW,
            QuantEventPayload(artifact_id=UUID(report_id)),
            artifact=QuantArtifactSpec(
                artifact_id=report_id,
                kind=QuantArtifactKind.RESEARCH_REPORT,
                label="Quant research report",
                digest=quant_fixture_digest("research_report", run_id),
            ),
        )
    )
    steps.append(
        QuantScriptStep(
            QuantEventType.REVIEW_REQUIRED,
            QuantRunState.WAITING_FOR_REVIEW,
            QuantEventPayload(target_type="research_report", target_id=UUID(report_id)),
        )
    )
    return tuple(steps)


QUANT_COMPLETION_CONCLUSION = "Candidate B retained for paper evaluation."
QUANT_NO_VIABLE_CONCLUSION = "No candidate passed validation."


def quant_script_timestamp(base_time: datetime, step_index: int) -> datetime:
    return base_time + timedelta(seconds=step_index + 1)


def derive_plan_step_statuses(
    state: QuantRunState, *, during: QuantRunState | None = None
) -> dict[str, QuantStepStatus]:
    """Project run state onto plan steps; disagreement never invents progress.

    ``during`` records the active execution state when a run failed or was
    cancelled, so the halted step is marked ``failed``/``skipped`` instead of
    the snapshot pretending the step finished.
    """

    active_step_by_state = {
        QuantRunState.DRAFT: ("define_scope", QuantStepStatus.ACTIVE),
        QuantRunState.PLANNING: ("define_scope", QuantStepStatus.ACTIVE),
        QuantRunState.WAITING_PLAN_APPROVAL: ("define_scope", QuantStepStatus.WAITING),
        QuantRunState.QUEUED: ("load_dataset", QuantStepStatus.PENDING),
        QuantRunState.LOADING_DATA: ("load_dataset", QuantStepStatus.ACTIVE),
        QuantRunState.GENERATING_CANDIDATES: ("generate_candidates", QuantStepStatus.ACTIVE),
        QuantRunState.RUNNING_EXPERIMENTS: ("run_experiments", QuantStepStatus.ACTIVE),
        QuantRunState.REPAIRING: ("repair_failures", QuantStepStatus.ACTIVE),
        QuantRunState.VALIDATING: ("validate_robustness", QuantStepStatus.ACTIVE),
        QuantRunState.GENERATING_REPORT: ("generate_report", QuantStepStatus.ACTIVE),
        QuantRunState.WAITING_FOR_REVIEW: ("human_decision", QuantStepStatus.WAITING),
    }
    order = [step.key for step in QUANT_PLAN_STEP_DEFS]
    if state == QuantRunState.COMPLETED:
        return {key: QuantStepStatus.COMPLETED for key in order}
    if state in (QuantRunState.FAILED, QuantRunState.CANCELLED):
        reference = during or QuantRunState.RUNNING_EXPERIMENTS
        current_key = active_step_by_state.get(
            reference, ("run_experiments", QuantStepStatus.ACTIVE)
        )[0]
        halted = (
            QuantStepStatus.FAILED if state == QuantRunState.FAILED else QuantStepStatus.SKIPPED
        )
        statuses: dict[str, QuantStepStatus] = {}
        for key in order:
            if order.index(key) < order.index(current_key):
                statuses[key] = QuantStepStatus.COMPLETED
            elif key == current_key:
                statuses[key] = halted
            else:
                statuses[key] = (
                    QuantStepStatus.PENDING
                    if state == QuantRunState.FAILED
                    else QuantStepStatus.SKIPPED
                )
        return statuses
    current_key, current_status = active_step_by_state.get(
        state, ("define_scope", QuantStepStatus.ACTIVE)
    )
    statuses = {}
    for key in order:
        if order.index(key) < order.index(current_key):
            statuses[key] = QuantStepStatus.COMPLETED
        elif key == current_key:
            statuses[key] = current_status
        else:
            statuses[key] = QuantStepStatus.PENDING
    return statuses
