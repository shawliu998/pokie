from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.contracts.quant import QuantArtifactKind, QuantResearchDecision
from packages.domain.canonical import canonical_digest
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context
from services.api.app.modules.quant.store import (
    LEGACY_RESEARCH_DECISION_REPOSITORY_MARKER,
    RESEARCH_DECISION_REPOSITORY_PREFIX,
    QuantArtifactRecord,
    QuantExperimentRecord,
    QuantRunRecord,
    QuantStore,
)
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.provider import MockQuantAgentProvider


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {principal_id}", "Idempotency-Key": str(uuid4())}
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _reseal_internal_p19_manifests(state: dict[str, Any]) -> None:
    reports = [artifact for artifact in state["artifacts"] if artifact["kind"] == "research_report"]
    report_identities = [
        {
            "artifact_id": artifact["id"],
            "workspace_id": artifact["workspace_id"],
            "run_id": artifact["run_id"],
            "selected_candidate_id": artifact["content"].get("selected_candidate_id"),
            "decision_exempt": artifact["content"].get("research_decision") is None,
            "artifact_digest": artifact["digest"],
            "content_digest": canonical_digest(artifact["content"]),
        }
        for artifact in reports
    ]
    artifacts_by_id = {artifact["id"]: artifact for artifact in state["artifacts"]}
    comparison_identities: list[dict[str, Any]] = []
    for report in reports:
        decision = report["content"].get("research_decision")
        if not isinstance(decision, dict):
            continue
        comparison = artifacts_by_id[decision["source_comparison_artifact_id"]]
        comparison_identities.append(
            {
                "artifact_id": comparison["id"],
                "workspace_id": comparison["workspace_id"],
                "run_id": comparison["run_id"],
                "artifact_digest": comparison["digest"],
                "content_digest": canonical_digest(comparison["content"]),
            }
        )
    report_identities.sort(key=lambda item: item["artifact_id"])
    comparison_identities.sort(key=lambda item: item["artifact_id"])
    state["research_decision_report_manifest_digest"] = canonical_digest(report_identities)
    marker_digest = canonical_digest(
        {"reports": report_identities, "comparisons": comparison_identities}
    ).removeprefix("sha256:")
    state["research_decision_contract_marker"] = (
        f"{RESEARCH_DECISION_REPOSITORY_PREFIX}{marker_digest[:56]}"
    )


def _candidate(candidate_id: str, ordinal: int) -> QuantExperimentRecord:
    return QuantExperimentRecord(
        id=candidate_id,
        workspace_id="workspace-1",
        run_id="run-1",
        ordinal=ordinal,
        name=candidate_id,
        hypothesis="Bounded candidate.",
        verdict="viable",  # type: ignore[arg-type]
        summary="Completed.",
        template="sma_crossover",
        parameters={"fast_window": 10 + ordinal, "slow_window": 100 + ordinal},
        state="completed",
        metrics={"trade_count": ordinal},
    )


def _row(
    candidate_id: str,
    *,
    sharpe: float,
    trades: int,
    pass_regimes: tuple[str, ...],
) -> dict[str, Any]:
    folds = [
        {
            "status": "pass",
            "market_regime": {"label": label},
        }
        for label in pass_regimes
    ]
    folds.extend(
        {
            "status": "fail",
            "market_regime": {"label": f"failed-{index}"},
        }
        for index in range(3 - len(folds))
    )
    return {
        "candidate_id": candidate_id,
        "total_return_pct": sharpe,
        "maximum_drawdown_pct": -10.0,
        "sharpe_ratio": sharpe,
        "trade_count": trades,
        "walk_forward": {
            "evaluation_partition": "train",
            "folds": folds,
        },
    }


def _decision_fixture(
    *,
    leader_trades: int = 3,
    selected_trades: int = 2,
    third_trades: int = 1,
    leader_regimes: tuple[str, ...] = ("trend",),
    selected_regimes: tuple[str, ...] = ("trend", "high-vol"),
    third_regimes: tuple[str, ...] = (),
) -> tuple[
    QuantStore,
    QuantRunRecord,
    list[QuantExperimentRecord],
    QuantArtifactRecord,
]:
    store = QuantStore()
    run = QuantRunRecord(
        id="run-1",
        workspace_id="workspace-1",
        project_id="project-1",
        question="Choose from training evidence.",
        mode="auto",  # type: ignore[arg-type]
    )
    completed = [_candidate(f"candidate-{index}", index) for index in (1, 2, 3)]
    rows = [
        _row(
            "candidate-1",
            sharpe=3.0,
            trades=leader_trades,
            pass_regimes=leader_regimes,
        ),
        _row(
            "candidate-2",
            sharpe=2.0,
            trades=selected_trades,
            pass_regimes=selected_regimes,
        ),
        _row(
            "candidate-3",
            sharpe=1.0,
            trades=third_trades,
            pass_regimes=third_regimes,
        ),
    ]
    artifact = QuantArtifactRecord(
        id="comparison-final",
        workspace_id=run.workspace_id,
        run_id=run.id,
        ordinal=20,
        kind=QuantArtifactKind.VALIDATION_REPORT,
        title="Final training comparison",
        digest="sha256:test",
        content={
            "evaluation_partition": "train",
            "selection_objective": "risk_adjusted_return",
            "candidates": rows,
            "ranking": ["candidate-1", "candidate-2", "candidate-3"],
        },
        created_at=datetime.now(tz=UTC),
    )
    artifact.digest = canonical_digest(artifact.content)
    return store, run, completed, artifact


def test_research_decision_contract_is_closed() -> None:
    decision = QuantResearchDecision(
        selected_candidate_id="candidate-1",
        source_comparison_artifact_id="comparison-final",
        decision_basis="approved_objective_rank",
    )
    assert decision.deviation is None
    with pytest.raises(ValidationError):
        QuantResearchDecision.model_validate(
            {
                **decision.model_dump(mode="json"),
                "decision_basis": "robustness_override",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QuantResearchDecision.model_validate(
            {**decision.model_dump(mode="json"), "free_form_reason": "Trust the model."}
        )


@pytest.mark.parametrize(
    ("reason", "fixture_overrides"),
    (
        ("walk_forward_stability", {}),
        ("regime_coverage", {}),
        (
            "minimum_trade_evidence",
            {
                "leader_trades": 0,
                "selected_trades": 1,
                "third_trades": 1,
            },
        ),
    ),
)
def test_closed_robustness_override_uses_only_final_training_evidence(
    reason: str,
    fixture_overrides: dict[str, Any],
) -> None:
    store, run, completed, comparison = _decision_fixture(**fixture_overrides)
    decision = QuantResearchDecision.model_validate(
        {
            "selected_candidate_id": "candidate-2",
            "source_comparison_artifact_id": comparison.id,
            "decision_basis": "robustness_override",
            "deviation": {
                "reason": reason,
                "reference_candidate_id": "candidate-1",
            },
        }
    )
    assert (
        store._validate_research_decision(  # pyright: ignore[reportPrivateUsage]
            run=run,
            selected=completed[1],
            completed=completed,
            comparison_artifact=comparison,
            decision=decision,
        )
        is None
    )


@pytest.mark.parametrize(
    ("reason", "fixture_overrides"),
    (
        (
            "walk_forward_stability",
            {
                "leader_regimes": ("trend", "low-vol"),
                "selected_regimes": ("trend", "high-vol"),
                "third_regimes": (),
            },
        ),
        (
            "regime_coverage",
            {
                "leader_regimes": ("trend", "low-vol"),
                "selected_regimes": ("trend", "high-vol"),
                "third_regimes": (),
            },
        ),
    ),
)
def test_robustness_override_ties_fall_back_to_objective_leader(
    reason: str,
    fixture_overrides: dict[str, Any],
) -> None:
    store, run, completed, comparison = _decision_fixture(**fixture_overrides)
    decision = QuantResearchDecision.model_validate(
        {
            "selected_candidate_id": "candidate-2",
            "source_comparison_artifact_id": comparison.id,
            "decision_basis": "robustness_override",
            "deviation": {
                "reason": reason,
                "reference_candidate_id": "candidate-1",
            },
        }
    )
    assert (
        store._validate_research_decision(  # pyright: ignore[reportPrivateUsage]
            run=run,
            selected=completed[1],
            completed=completed,
            comparison_artifact=comparison,
            decision=decision,
        )
        == "RESEARCH_DECISION_OVERRIDE_UNSUPPORTED"
    )


def test_comparison_digest_and_nested_partition_fail_closed_before_projection() -> None:
    store, run, completed, comparison = _decision_fixture()
    decision = QuantResearchDecision.model_validate(
        {
            "selected_candidate_id": "candidate-2",
            "source_comparison_artifact_id": comparison.id,
            "decision_basis": "robustness_override",
            "deviation": {
                "reason": "walk_forward_stability",
                "reference_candidate_id": "candidate-1",
            },
        }
    )
    store._artifacts[comparison.id] = comparison  # pyright: ignore[reportPrivateUsage]
    comparison.content["candidates"][0]["trade_count"] += 1
    assert (
        store._validate_research_decision(  # pyright: ignore[reportPrivateUsage]
            run=run,
            selected=completed[1],
            completed=completed,
            comparison_artifact=comparison,
            decision=decision,
        )
        == "RESEARCH_DECISION_BINDING_MISMATCH"
    )
    assert store._latest_training_comparison(run) is None  # pyright: ignore[reportPrivateUsage]

    comparison.digest = canonical_digest(comparison.content)
    comparison.content["candidates"][0]["walk_forward"]["evaluation_partition"] = "holdout"
    comparison.digest = canonical_digest(comparison.content)
    assert (
        store._validate_research_decision(  # pyright: ignore[reportPrivateUsage]
            run=run,
            selected=completed[1],
            completed=completed,
            comparison_artifact=comparison,
            decision=decision,
        )
        == "RESEARCH_DECISION_EVIDENCE_INVALID"
    )
    assert store._latest_training_comparison(run) is None  # pyright: ignore[reportPrivateUsage]


def test_unsupported_override_fails_without_workspace_mutation(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": "P19 zero mutation",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    workspace_id = workspace.json()["workspace_id"]
    project = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "P19", "objective": "Choose a candidate."},
    ).json()
    created = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "mode": "auto",
            "question": "Choose a candidate.",
            "expected_project_row_version": project["row_version"],
        },
    ).json()
    store = QuantStore()
    for _ in range(10):
        assert run_quant_agent_once(
            store=store,
            provider=MockQuantAgentProvider(),
            workspace_id=workspace_id,
        )
    context = store.agent_context_data(workspace_id=workspace_id, run_id=created["id"])
    comparison = context["latest_comparison"]
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="p19-invalid")
    assert claim is not None
    baseline = deepcopy(
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    )
    decision = QuantResearchDecision.model_validate(
        {
            "selected_candidate_id": comparison["ranking"][-1],
            "source_comparison_artifact_id": comparison["artifact_id"],
            "decision_basis": "robustness_override",
            "deviation": {
                "reason": "minimum_trade_evidence",
                "reference_candidate_id": comparison["ranking"][0],
            },
        }
    )
    report, artifact_ids, error = store.finish_agent_research(
        claim,
        selected_candidate_id=decision.selected_candidate_id,
        conclusion="Unsupported deviation.",
        next_step="stop",
        research_decision=decision,
    )
    assert report is None and artifact_ids == []
    assert error == "RESEARCH_DECISION_OVERRIDE_UNSUPPORTED"
    assert (
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        == baseline
    )


def test_pre_p19_report_restores_then_content_or_marker_tamper_fails_closed(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": "P19 migration",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    workspace_id = workspace.json()["workspace_id"]
    project = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "P19", "objective": "Complete research."},
    ).json()
    run = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "mode": "auto",
            "question": "Complete research.",
            "expected_project_row_version": project["row_version"],
        },
    ).json()
    store = QuantStore()
    for _ in range(11):
        assert run_quant_agent_once(
            store=store,
            provider=MockQuantAgentProvider(),
            workspace_id=workspace_id,
        )
    legacy_state = deepcopy(
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    )
    legacy_state.pop("research_decision_contract_marker", None)
    legacy_state.pop("research_decision_report_manifest_digest", None)
    report = next(
        artifact for artifact in legacy_state["artifacts"] if artifact["kind"] == "research_report"
    )
    report["content"]["research_decision"] = None
    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p19-legacy")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        row.state_json = legacy_state
        row.research_decision_contract_marker = LEGACY_RESEARCH_DECISION_REPOSITORY_MARKER
        row.row_version += 1
        db.commit()

    restored = QuantStore()
    assert restored.get_run(workspace_id=workspace_id, run_id=run["id"]).state.value == "completed"
    restored._persist_workspace(workspace_id)  # pyright: ignore[reportPrivateUsage]
    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p19-content-tamper")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        assert row.research_decision_contract_marker.startswith(RESEARCH_DECISION_REPOSITORY_PREFIX)
        sealed_state = deepcopy(row.state_json)
        sealed_marker = row.research_decision_contract_marker
        tampered_state = deepcopy(sealed_state)
        decision_exempt_report = next(
            artifact
            for artifact in tampered_state["artifacts"]
            if artifact["kind"] == "research_report"
        )
        assert decision_exempt_report["content"]["research_decision"] is None
        decision_exempt_report["content"]["conclusion"] = "Tampered after repository sealing."
        row.state_json = tampered_state
        row.row_version += 1
        db.commit()

    content_rejected = QuantStore()
    content_baseline = content_rejected._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    with pytest.raises(ValueError, match="repository marker"):
        content_rejected.get_run(workspace_id=workspace_id, run_id=run["id"])
    assert (
        content_rejected._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        == content_baseline
    )

    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p19-tamper")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        row.state_json = sealed_state
        row.research_decision_contract_marker = sealed_marker
        row.row_version += 1
        db.commit()

    marker_restored = QuantStore()
    assert (
        marker_restored.get_run(workspace_id=workspace_id, run_id=run["id"]).state.value
        == "completed"
    )

    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p19-marker-tamper")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        row.research_decision_contract_marker = f"{RESEARCH_DECISION_REPOSITORY_PREFIX}tampered"
        row.row_version += 1
        db.commit()

    rejected = QuantStore()
    baseline = rejected._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ValueError, match="repository marker"):
        rejected.get_run(workspace_id=workspace_id, run_id=run["id"])
    assert (
        rejected._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        == baseline
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "null_marker",
        "legacy_downgrade",
        "delete_decision",
        "delete_report",
        "stale_digest",
        "closed_reason",
        "comparison_partition",
    ),
)
def test_sealed_p19_repository_tamper_fails_closed(
    client: TestClient,
    principal_id: str,
    tamper: str,
) -> None:
    workspace = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": f"P19 sealed {tamper}",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    workspace_id = workspace.json()["workspace_id"]
    project = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "P19", "objective": "Complete research."},
    ).json()
    run = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "mode": "auto",
            "question": "Complete research.",
            "expected_project_row_version": project["row_version"],
        },
    ).json()
    store = QuantStore()
    for _ in range(11):
        assert run_quant_agent_once(
            store=store,
            provider=MockQuantAgentProvider(),
            workspace_id=workspace_id,
        )
    direct_state: dict[str, Any] | None = None
    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, f"p19-{tamper}")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        state = deepcopy(row.state_json)
        report = next(
            artifact for artifact in state["artifacts"] if artifact["kind"] == "research_report"
        )
        if tamper == "null_marker":
            direct_state = state
            db.rollback()
        elif tamper == "legacy_downgrade":
            row.research_decision_contract_marker = LEGACY_RESEARCH_DECISION_REPOSITORY_MARKER
            report["content"]["research_decision"] = None
        elif tamper == "delete_decision":
            report["content"]["research_decision"] = None
        elif tamper == "delete_report":
            state["artifacts"].remove(report)
            _reseal_internal_p19_manifests(state)
        elif tamper == "stale_digest":
            report["content"]["research_decision"]["deviation"] = {
                "reason": "regime_coverage",
                "reference_candidate_id": "tampered",
            }
        elif tamper == "comparison_partition":
            comparison_id = report["content"]["research_decision"]["source_comparison_artifact_id"]
            comparison = next(
                artifact for artifact in state["artifacts"] if artifact["id"] == comparison_id
            )
            comparison["content"]["candidates"][0]["walk_forward"]["evaluation_partition"] = (
                "holdout"
            )
            comparison["digest"] = canonical_digest(comparison["content"])
            _reseal_internal_p19_manifests(state)
        else:
            report["content"]["research_decision"]["decision_basis"] = "robustness_override"
            report["content"]["research_decision"]["deviation"] = {
                "reason": "free_form_reason",
                "reference_candidate_id": "tampered",
            }
            report["digest"] = canonical_digest(report["content"])
            _reseal_internal_p19_manifests(state)
        if tamper != "null_marker":
            row.state_json = state
            row.row_version += 1
            db.commit()

    rejected = QuantStore()
    baseline = rejected._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises((TypeError, ValueError)):
        if direct_state is not None:
            rejected._restore_workspace(  # pyright: ignore[reportPrivateUsage]
                workspace_id,
                direct_state,
                repository_research_decision_contract_marker=None,
            )
        else:
            rejected.get_run(workspace_id=workspace_id, run_id=run["id"])
    assert rejected._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
