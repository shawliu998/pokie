from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from packages.contracts.quant import (
    QuantAgentBudget,
    QuantAgentContext,
    QuantAgentPlan,
    QuantBarInterval,
    QuantResearchMemoryContext,
)
from packages.contracts.quant.enums import (
    QuantExperimentVerdict,
    QuantRunMode,
    QuantRunState,
)
from packages.contracts.quant.fixture_data import SPY_DAILY_FIXTURE
from packages.domain.canonical import canonical_digest
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context
from services.api.app.modules.quant.snapshot import quant_agent_workspace_snapshot
from services.api.app.modules.quant.store import (
    LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION,
    RESEARCH_MEMORY_CONTRACT_VERSION,
    QuantExperimentRecord,
    QuantRunRecord,
    QuantStore,
)
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.provider import MockQuantAgentProvider


def _workspace(client: TestClient, principal_id: str, name: str) -> str:
    response = client.post(
        "/v1/workspaces",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "name": name,
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["workspace_id"])


def _create_plan_run(
    store: QuantStore,
    *,
    workspace_id: str,
    project_id: str,
    question: str,
    parent: QuantRunRecord | None = None,
    seed: QuantExperimentRecord | None = None,
    research_start: date | None = None,
    research_end: date | None = None,
) -> QuantRunRecord:
    project = store.get_project(workspace_id=workspace_id, project_id=project_id)
    return store.create_run(
        workspace_id=workspace_id,
        project_id=project_id,
        question=question,
        mode=QuantRunMode.PLAN,
        expected_project_row_version=project.row_version,
        research_start=research_start,
        research_end=research_end,
        parent_run_id=parent.id if parent is not None else None,
        seed_candidate_id=seed.id if seed is not None else None,
        refinement_reason=(
            "Continue with one canonical-distinct bounded strategy." if parent is not None else None
        ),
    )


def _agent_plan(
    *,
    families: list[str],
    objective: str = "risk_adjusted_return",
) -> QuantAgentPlan:
    return QuantAgentPlan.model_validate(
        {
            "objective_summary": "Execute a bounded focused research plan.",
            "steps": [
                {
                    "key": "research",
                    "title": "Research",
                    "owner": "agent",
                    "description": "Test the approved strategy families.",
                }
            ],
            "candidate_families": families,
            "strategy_scope": {
                "schema_version": "quant-strategy-scope-v1",
                "status": "supported",
                "reason": "The request fits the registered strategy templates.",
                "proxy_description": None,
                "excluded_behaviors": [],
            },
            "selection_objective": objective,
            "max_experiments": 3,
            "max_repairs": 1,
            "completion_criteria": ["Compare every completed candidate."],
        }
    )


def _add_completed_candidate(
    store: QuantStore,
    run: QuantRunRecord,
    *,
    suffix: str,
    template: str,
    parameters: dict[str, int | float],
    metrics: dict[str, int | float] | None = None,
) -> QuantExperimentRecord:
    key = store.canonical_candidate_key(template, parameters)
    candidate = QuantExperimentRecord(
        id=f"candidate-{run.id}-{suffix}",
        workspace_id=run.workspace_id,
        run_id=run.id,
        ordinal=1 + sum(item.run_id == run.id for item in store._experiments.values()),  # pyright: ignore[reportPrivateUsage]
        name=f"{template}-{suffix}",
        hypothesis=f"Private hypothesis sentinel {suffix}",
        verdict=QuantExperimentVerdict.VIABLE,
        summary=f"Private summary sentinel {suffix}",
        template=template,
        parameters=parameters,
        state="completed",
        metrics=metrics
        or {
            "trade_count": 4,
            "total_return_pct": 2.0,
            "sharpe_ratio": 0.5,
        },
        candidate_key=key,
    )
    store._experiments[candidate.id] = candidate  # pyright: ignore[reportPrivateUsage]
    return candidate


def _complete_run(store: QuantStore, run: QuantRunRecord) -> None:
    run.state = QuantRunState.COMPLETED
    run.agent_status = "completed"
    run.updated_at = datetime.now(tz=UTC)
    store._append_event(  # pyright: ignore[reportPrivateUsage]
        run,
        "run.completed",
        {
            "state": QuantRunState.COMPLETED,
            "safe_summary": "The focused P17 source completed.",
        },
    )
    store._persist_workspace(run.workspace_id)  # pyright: ignore[reportPrivateUsage]


def _market_csv(count: int = 2_200) -> str:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    rows = ["timestamp,open,high,low,close,volume"]
    for index in range(count):
        opening = Decimal("100") + Decimal(index % 17) / Decimal("10")
        close = opening + Decimal((index % 5) - 2) / Decimal("20")
        rows.append(
            f"{timestamp.isoformat().replace('+00:00', 'Z')},"
            f"{opening},{max(opening, close) + Decimal('0.25')},"
            f"{min(opening, close) - Decimal('0.25')},{close},{100 + index}"
        )
        timestamp += timedelta(hours=1)
    return "\n".join(rows) + "\n"


def _create_run_by_contract(
    store: QuantStore,
    *,
    workspace_id: str,
    project_id: str,
    contract: str,
    market_record: Any | None,
) -> QuantRunRecord:
    project = store.get_project(workspace_id=workspace_id, project_id=project_id)
    if contract == "legacy":
        return store.create_run(
            workspace_id=workspace_id,
            project_id=project_id,
            question="Exercise legacy P17 creation transaction.",
            mode=QuantRunMode.PLAN,
            expected_project_row_version=project.row_version,
        )
    assert market_record is not None
    if contract == "private_market":
        return store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
            workspace_id=workspace_id,
            project_id=project_id,
            question="Exercise private market P17 creation transaction.",
            mode=QuantRunMode.PLAN,
            expected_project_row_version=project.row_version,
            dataset_id=market_record.id,
        )
    return store.create_market_run(
        workspace_id=workspace_id,
        project_id=project_id,
        question="Exercise public market P17 creation transaction.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=project.row_version,
        dataset_id=market_record.id,
        research_start_utc=market_record.dataset.covered_start,
        research_end_utc=market_record.dataset.covered_end,
    )


def _setup_contract_creation(
    store: QuantStore,
    *,
    workspace_id: str,
    contract: str,
) -> tuple[str, Any | None]:
    market_record: Any | None = None
    if contract != "legacy":
        market_record = store.import_market_dataset_v2_csv(
            workspace_id=workspace_id,
            name=f"{contract} BTCUSDT 1h",
            symbol="BTCUSDT",
            interval=QuantBarInterval.HOUR,
            csv_text=_market_csv(),
            source_name="P17 transaction CSV",
            source_reference=f"test:p17:{contract}",
            file_name=f"{contract}.csv",
        )
    project = store.create_project(
        workspace_id=workspace_id,
        name=f"{contract} transaction",
        objective="Keep Run creation atomic.",
    )
    store._persist_workspace(workspace_id)  # pyright: ignore[reportPrivateUsage]
    return project.id, market_record


def _finish_mock_run(workspace_id: str, run_id: str) -> QuantStore:
    for _ in range(15):
        assert run_quant_agent_once(workspace_id=workspace_id)
        store = QuantStore()
        run = store.get_run(workspace_id=workspace_id, run_id=run_id)
        if run.state in {
            QuantRunState.COMPLETED,
            QuantRunState.FAILED,
            QuantRunState.CANCELLED,
        }:
            return store
    raise AssertionError("Mock research did not reach a terminal state.")


def _assert_memory_key_whitelist(memory: dict[str, Any]) -> None:
    assert set(memory) == {
        "schema_version",
        "source_run_ids",
        "sources",
        "tested_candidate_keys",
        "candidates",
        "comparability",
        "context_digest",
    }
    source_keys = {
        "run_id",
        "relationship",
        "attempt_number",
        "retry_of_run_id",
        "dataset_id",
        "dataset_digest",
        "symbol",
        "interval",
        "periods_per_year",
        "range_start",
        "range_end",
        "runtime_descriptor_digest",
        "training_split_digest",
        "selection_objective",
        "comparability",
        "limitations",
    }
    candidate_keys = {
        "source_run_id",
        "candidate_key",
        "template",
        "parameters",
        "training_rank",
        "training_failure_category",
    }
    assert all(set(source) == source_keys for source in memory["sources"])
    assert all(set(candidate) == candidate_keys for candidate in memory["candidates"])


def test_empty_memory_pin_is_explicit_and_deterministic(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "P17 empty memory")
    store = QuantStore()
    project = store.create_project(
        workspace_id=workspace_id,
        name="Empty memory",
        objective="Start without prior compatible experiments.",
    )
    first = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="First independent root.",
    )
    second = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="Second root while the first remains nonterminal.",
    )

    assert first.research_memory is not None
    assert second.research_memory is not None
    assert first.research_memory == second.research_memory
    assert first.research_memory.source_run_ids == []
    assert first.research_memory.tested_candidate_keys == []
    assert first.research_memory.context_digest == QuantStore._research_memory_digest(  # pyright: ignore[reportPrivateUsage]
        first.research_memory
    )


def test_retrieval_is_ancestor_first_stable_bounded_and_filters_ineligible_runs(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "P17 retrieval")
    foreign_workspace_id = _workspace(client, principal_id, "P17 foreign")
    store = QuantStore()
    project = store.create_project(
        workspace_id=workspace_id,
        name="Series project",
        objective="Retain bounded same-evidence memory.",
    )
    root = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="Root",
    )
    root_seed = _add_completed_candidate(
        store,
        root,
        suffix="root",
        template="sma_crossover",
        parameters={"fast_window": 11, "slow_window": 71},
    )
    _complete_run(store, root)
    child = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="Child",
        parent=root,
        seed=root_seed,
    )
    child_seed = _add_completed_candidate(
        store,
        child,
        suffix="child",
        template="breakout",
        parameters={"lookback_window": 31},
    )
    _complete_run(store, child)

    compatible_runs: list[QuantRunRecord] = []
    for index in range(6):
        history_project = store.create_project(
            workspace_id=workspace_id,
            name=f"History {index}",
            objective="Compatible retained history.",
        )
        source = _create_plan_run(
            store,
            workspace_id=workspace_id,
            project_id=history_project.id,
            question=f"Compatible source {index}",
        )
        _add_completed_candidate(
            store,
            source,
            suffix=f"sma-{index}",
            template="sma_crossover",
            parameters={"fast_window": 20 + index, "slow_window": 100 + index},
        )
        _add_completed_candidate(
            store,
            source,
            suffix=f"rsi-{index}",
            template="rsi_mean_reversion",
            parameters={
                "period": 14,
                "entry_threshold": 20 + index,
                "exit_threshold": 60,
            },
        )
        _add_completed_candidate(
            store,
            source,
            suffix=f"breakout-{index}",
            template="breakout",
            parameters={"lookback_window": 40 + index},
        )
        _complete_run(store, source)
        compatible_runs.append(source)

    nonterminal_project = store.create_project(
        workspace_id=workspace_id,
        name="Nonterminal",
        objective="Must not enter memory.",
    )
    nonterminal = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=nonterminal_project.id,
        question="Still awaiting approval.",
    )
    _add_completed_candidate(
        store,
        nonterminal,
        suffix="nonterminal",
        template="breakout",
        parameters={"lookback_window": 90},
    )
    store._persist_workspace(workspace_id)  # pyright: ignore[reportPrivateUsage]

    range_project = store.create_project(
        workspace_id=workspace_id,
        name="Different split",
        objective="Must not enter same-evidence memory.",
    )
    range_source = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=range_project.id,
        question="Different evidence range.",
        research_start=SPY_DAILY_FIXTURE.bars[0].trading_date,
        research_end=SPY_DAILY_FIXTURE.bars[251].trading_date,
    )
    _add_completed_candidate(
        store,
        range_source,
        suffix="range",
        template="breakout",
        parameters={"lookback_window": 91},
    )
    _complete_run(store, range_source)

    market_record = store.import_market_dataset_v2_csv(
        workspace_id=workspace_id,
        name="BTCUSDT 1h",
        symbol="BTCUSDT",
        interval=QuantBarInterval.HOUR,
        csv_text=_market_csv(),
        source_name="P17 test CSV",
        source_reference="test:p17:hourly",
        file_name="p17-hourly.csv",
    )
    market_project = store.create_project(
        workspace_id=workspace_id,
        name="Different cadence",
        objective="Must not enter daily memory.",
    )
    market_run = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=market_project.id,
        question="Hourly BTC source.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=market_project.row_version,
        dataset_id=market_record.id,
    )
    _add_completed_candidate(
        store,
        market_run,
        suffix="hourly",
        template="breakout",
        parameters={"lookback_window": 92},
    )
    _complete_run(store, market_run)

    foreign_store = QuantStore()
    foreign_project = foreign_store.create_project(
        workspace_id=foreign_workspace_id,
        name="Foreign",
        objective="Must remain workspace-scoped.",
    )
    foreign_run = _create_plan_run(
        foreign_store,
        workspace_id=foreign_workspace_id,
        project_id=foreign_project.id,
        question="Foreign source.",
    )
    _add_completed_candidate(
        foreign_store,
        foreign_run,
        suffix="foreign",
        template="breakout",
        parameters={"lookback_window": 93},
    )
    _complete_run(foreign_store, foreign_run)

    target = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="Grandchild target.",
        parent=child,
        seed=child_seed,
    )
    same_target = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="Equivalent grandchild target.",
        parent=child,
        seed=child_seed,
    )
    memory = target.research_memory
    assert memory is not None
    assert same_target.research_memory == memory
    assert memory.source_run_ids[:2] == [child.id, root.id]
    assert len(memory.source_run_ids) == 5
    assert len(memory.tested_candidate_keys) <= 15
    excluded = {
        nonterminal.id,
        range_source.id,
        market_run.id,
        foreign_run.id,
    }
    assert not excluded.intersection(memory.source_run_ids)
    assert all(source.comparability == "same_evidence" for source in memory.sources)
    assert all(
        source.symbol == SPY_DAILY_FIXTURE.symbol
        and source.interval == "1D"
        and source.periods_per_year == 252
        for source in memory.sources
    )
    assert set(memory.source_run_ids).issubset(
        {root.id, child.id, *(run.id for run in compatible_runs)}
    )


def test_workspace_snapshot_projects_only_pinned_research_memory_counts(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "P17 snapshot projection")
    store = QuantStore()
    project = store.create_project(
        workspace_id=workspace_id,
        name="Snapshot memory",
        objective="Expose retained prior research without its evidence.",
    )
    root = store.create_run(
        workspace_id=workspace_id,
        project_id=project.id,
        question="Establish a bounded source run.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
    )
    root_snapshot = quant_agent_workspace_snapshot(workspace_id=workspace_id, run_id=root.id)
    assert root_snapshot is not None
    assert "researchMemory" not in root_snapshot

    seed = _add_completed_candidate(
        store,
        root,
        suffix="source",
        template="sma_crossover",
        parameters={"fast_window": 12, "slow_window": 48},
    )
    _complete_run(store, root)
    root = store.get_run(workspace_id=workspace_id, run_id=root.id)
    project = store.get_project(workspace_id=workspace_id, project_id=project.id)
    child = store.create_run(
        workspace_id=workspace_id,
        project_id=project.id,
        question="Refine with the already pinned prior work.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
        parent_run_id=root.id,
        seed_candidate_id=seed.id,
        refinement_reason="Use a canonical-distinct candidate.",
    )
    assert child.research_memory is not None
    snapshot = quant_agent_workspace_snapshot(workspace_id=workspace_id, run_id=child.id)
    assert snapshot is not None
    assert snapshot["researchMemory"] == {
        "sourceRunCount": len(child.research_memory.source_run_ids),
        "testedCandidateCount": len(child.research_memory.tested_candidate_keys),
    }
    assert set(snapshot["researchMemory"]) == {"sourceRunCount", "testedCandidateCount"}


def test_pinned_memory_blocks_create_and_revise_then_retry_clones_and_restore_verifies(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "P17 integration")
    store = QuantStore()
    project = store.create_project(
        workspace_id=workspace_id,
        name="Memory integration",
        objective="Avoid repeated experiments.",
    )
    root = store.create_run(
        workspace_id=workspace_id,
        project_id=project.id,
        question="Reduce drawdown with a simple filter.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
    )
    store = _finish_mock_run(workspace_id, root.id)
    root = store.get_run(workspace_id=workspace_id, run_id=root.id)
    seed = store.experiments_for_run(workspace_id=workspace_id, run_id=root.id)[0]
    project = store.get_project(workspace_id=workspace_id, project_id=project.id)
    child = store.create_run(
        workspace_id=workspace_id,
        project_id=project.id,
        question="Refine without repeating the source candidates.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
        parent_run_id=root.id,
        seed_candidate_id=seed.id,
        refinement_reason="Test one canonical-distinct parameterization.",
    )
    context = store.agent_context_data(workspace_id=workspace_id, run_id=child.id)
    memory = context["research_memory"]
    _assert_memory_key_whitelist(memory)
    assert memory["source_run_ids"][0] == root.id
    assert len(memory["tested_candidate_keys"]) == 3
    serialized = json.dumps(memory, sort_keys=True)
    assert root.final_conclusion is not None
    assert root.final_conclusion not in serialized
    assert all(
        experiment.hypothesis not in serialized
        for experiment in store.experiments_for_run(workspace_id=workspace_id, run_id=root.id)
    )

    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="p17-dedupe")
    assert claim is not None
    prior = memory["candidates"][0]
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    created, artifacts, error = store.create_agent_candidate(
        claim,
        name="Exact prior duplicate",
        template=prior["template"],
        hypothesis="This must fail without mutation.",
        parameters=prior["parameters"],
    )
    assert created is None
    assert artifacts == []
    assert error == "RESEARCH_MEMORY_EXACT_DUPLICATE"
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    prior_sma = next(
        candidate for candidate in memory["candidates"] if candidate["template"] == "sma_crossover"
    )
    novel, _, error = store.create_agent_candidate(
        claim,
        name="Novel repair source",
        template="sma_crossover",
        hypothesis="Create one distinct candidate before a blocked revision.",
        parameters={"fast_window": 7, "slow_window": 70},
    )
    assert error is None and novel is not None
    store.release_agent_claim(claim)
    child.state = QuantRunState.RUNNING_EXPERIMENTS
    child.agent_status = "waiting_next_step"
    store._persist_workspace(workspace_id)  # pyright: ignore[reportPrivateUsage]
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="p17-revise-dedupe")
    assert claim is not None
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    revised, artifacts, error = store.revise_agent_candidate(
        claim,
        candidate_id=novel.id,
        reason="Attempt an exact prior identity.",
        parameter_patch=prior_sma["parameters"],
    )
    assert revised is None
    assert artifacts == []
    assert error == "RESEARCH_MEMORY_EXACT_DUPLICATE"
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    store.release_agent_claim(claim)
    child.state = QuantRunState.FAILED
    child.agent_status = "failed"
    child.failure_reason = "Stopped after the focused memory gate test."
    store._persist_workspace(workspace_id)  # pyright: ignore[reportPrivateUsage]
    retry = store.retry_run(
        workspace_id=workspace_id,
        run_id=child.id,
        expected_row_version=child.row_version,
        reason="Verify exact memory clone.",
    )
    assert retry.research_memory is not child.research_memory
    assert retry.research_memory is not None
    assert child.research_memory is not None
    assert retry.research_memory.model_dump(mode="json") == child.research_memory.model_dump(
        mode="json"
    )

    reloaded = QuantStore()
    restored_retry = reloaded.get_run(workspace_id=workspace_id, run_id=retry.id)
    assert restored_retry.research_memory == retry.research_memory
    guarded = QuantStore()
    guarded_before = guarded.get_run(workspace_id=workspace_id, run_id=root.id).research_memory
    tampered = deepcopy(store._workspace_state(workspace_id))  # pyright: ignore[reportPrivateUsage]
    tampered_root = next(item for item in tampered["runs"] if item["id"] == root.id)
    tampered_root["research_memory"]["context_digest"] = "sha256:tampered"
    with pytest.raises(ValueError, match="Research Memory"):
        guarded._restore_workspace(workspace_id, tampered)  # pyright: ignore[reportPrivateUsage]
    assert (
        guarded.get_run(workspace_id=workspace_id, run_id=root.id).research_memory == guarded_before
    )


def test_memory_covers_all_families_and_replan_cannot_reopen_a_prior_exact_candidate(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "P17 all-family pin")
    store = QuantStore()
    source_project = store.create_project(
        workspace_id=workspace_id,
        name="Cross-objective source",
        objective="Retain a breakout tested under a return objective.",
    )
    source = store.create_run(
        workspace_id=workspace_id,
        project_id=source_project.id,
        question="Maximize bounded training return.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=source_project.row_version,
        agent_plan=_agent_plan(
            families=["breakout"],
            objective="total_return",
        ),
    )
    prior = _add_completed_candidate(
        store,
        source,
        suffix="breakout",
        template="breakout",
        parameters={"lookback_window": 77},
    )
    _complete_run(store, source)

    target_project = store.create_project(
        workspace_id=workspace_id,
        name="Restricted target",
        objective="Begin with SMA, then request breakout.",
    )
    target = store.create_run(
        workspace_id=workspace_id,
        project_id=target_project.id,
        question="Start with an SMA-only drawdown plan.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=target_project.row_version,
        agent_plan=_agent_plan(
            families=["sma_crossover"],
            objective="drawdown_control",
        ),
    )
    assert target.research_memory is not None
    assert prior.candidate_key in target.research_memory.tested_candidate_keys
    pinned_source = next(
        item for item in target.research_memory.sources if item.run_id == source.id
    )
    assert pinned_source.selection_objective == "total_return"
    pinned_candidate = next(
        item
        for item in target.research_memory.candidates
        if item.candidate_key == prior.candidate_key
    )
    assert pinned_candidate.training_rank is None

    revised = store.request_plan_changes(
        workspace_id=workspace_id,
        run_id=target.id,
        expected_row_version=target.row_version,
        plan_revision=target.plan_revision,
        change_request="Use the approved breakout family instead.",
        agent_plan=_agent_plan(
            families=["breakout"],
            objective="drawdown_control",
        ),
    )
    store.approve_plan(
        workspace_id=workspace_id,
        run_id=revised.id,
        expected_row_version=revised.row_version,
        plan_revision=revised.plan_revision,
        reason="Exercise the all-family memory gate.",
    )
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="p17-replan")
    assert claim is not None
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    created, artifacts, error = store.create_agent_candidate(
        claim,
        name="Prior breakout",
        template="breakout",
        hypothesis="This exact strategy must remain blocked after replan.",
        parameters={"lookback_window": 77},
    )
    assert created is None
    assert artifacts == []
    assert error == "RESEARCH_MEMORY_EXACT_DUPLICATE"
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "tamper_kind",
    [
        "missing_memory",
        "missing_marker_and_memory",
        "coordinated_downgrade",
        "canonical_empty",
        "canonical_subset",
        "canonical_reorder",
        "cross_workspace_source",
        "nonterminal_source",
        "source_identity",
    ],
)
def test_restore_rejects_missing_or_incomplete_rehashed_memory_atomically(
    client: TestClient,
    principal_id: str,
    tamper_kind: str,
) -> None:
    workspace_id = _workspace(client, principal_id, f"P17 restore {tamper_kind}")
    store = QuantStore()
    source_project = store.create_project(
        workspace_id=workspace_id,
        name="Restore source",
        objective="Provide complete canonical memory.",
    )
    source = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=source_project.id,
        question="Completed source.",
    )
    _add_completed_candidate(
        store,
        source,
        suffix="sma",
        template="sma_crossover",
        parameters={"fast_window": 13, "slow_window": 89},
    )
    _add_completed_candidate(
        store,
        source,
        suffix="breakout",
        template="breakout",
        parameters={"lookback_window": 61},
    )
    _complete_run(store, source)
    target_project = store.create_project(
        workspace_id=workspace_id,
        name="Restore target",
        objective="Pin every eligible prior identity.",
    )
    target = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=target_project.id,
        question="Target with complete pin.",
    )
    assert target.research_memory is not None
    assert len(target.research_memory.candidates) == 2

    guarded = QuantStore()
    guarded_target = guarded.get_run(workspace_id=workspace_id, run_id=target.id)
    before = guarded_target.research_memory
    tampered = deepcopy(store._workspace_state(workspace_id))  # pyright: ignore[reportPrivateUsage]
    run_payload = next(item for item in tampered["runs"] if item["id"] == target.id)
    source_payload = next(item for item in tampered["runs"] if item["id"] == source.id)
    plan_payload = next(
        item for item in tampered["artifacts"] if item["id"] == target.plan_artifact_id
    )
    if tamper_kind == "missing_memory":
        run_payload.pop("research_memory")
    elif tamper_kind == "missing_marker_and_memory":
        run_payload.pop("research_memory_contract_version")
        run_payload.pop("research_memory")
    elif tamper_kind == "coordinated_downgrade":
        run_payload.pop("research_memory_contract_version")
        run_payload.pop("research_memory")
        tampered["research_memory_manifest"].pop(target.id)
        plan_payload["content"].pop("research_memory_contract_version")
        plan_payload["content"].pop("research_memory_digest")
    elif tamper_kind == "nonterminal_source":
        source_payload["state"] = QuantRunState.RUNNING_EXPERIMENTS.value
    else:
        memory = run_payload["research_memory"]
        if tamper_kind == "canonical_empty":
            memory["source_run_ids"] = []
            memory["sources"] = []
            memory["tested_candidate_keys"] = []
            memory["candidates"] = []
        elif tamper_kind == "canonical_subset":
            memory["tested_candidate_keys"] = memory["tested_candidate_keys"][:-1]
            memory["candidates"] = memory["candidates"][:-1]
        elif tamper_kind == "canonical_reorder":
            memory["tested_candidate_keys"] = list(reversed(memory["tested_candidate_keys"]))
            memory["candidates"] = list(reversed(memory["candidates"]))
        elif tamper_kind == "cross_workspace_source":
            memory["source_run_ids"][0] = "foreign-workspace-run"
            memory["sources"][0]["run_id"] = "foreign-workspace-run"
            for candidate in memory["candidates"]:
                candidate["source_run_id"] = "foreign-workspace-run"
        else:
            memory["sources"][0]["dataset_digest"] = "sha256:tampered-source-identity"
        digest = canonical_digest(
            {key: value for key, value in memory.items() if key != "context_digest"}
        )
        memory["context_digest"] = digest
        tampered["research_memory_manifest"][target.id]["context_digest"] = digest
        plan_payload["content"]["research_memory_digest"] = digest

    with pytest.raises(ValueError, match="Research Memory"):
        guarded._restore_workspace(workspace_id, tampered)  # pyright: ignore[reportPrivateUsage]
    assert guarded.get_run(workspace_id=workspace_id, run_id=target.id) is guarded_target
    assert guarded_target.research_memory == before


def test_legacy_repository_row_materializes_memory_and_upgrades_external_contract(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id = _workspace(client, principal_id, "P17 external legacy migration")
    store = QuantStore()
    source_project = store.create_project(
        workspace_id=workspace_id,
        name="Legacy source",
        objective="Provide one legacy candidate.",
    )
    source = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=source_project.id,
        question="Legacy source Run.",
    )
    prior = _add_completed_candidate(
        store,
        source,
        suffix="legacy",
        template="sma_crossover",
        parameters={"fast_window": 19, "slow_window": 109},
    )
    _complete_run(store, source)
    target_project = store.create_project(
        workspace_id=workspace_id,
        name="Legacy target",
        objective="Exercise one-time memory materialization.",
    )
    target = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=target_project.id,
        question="Legacy target Run.",
    )

    legacy_state = deepcopy(store._workspace_state(workspace_id))  # pyright: ignore[reportPrivateUsage]
    legacy_state.pop("research_memory_manifest")
    legacy_state.pop("verified_learning_policy", None)
    for run_payload in legacy_state["runs"]:
        run_payload.pop("research_memory_contract_version")
        run_payload.pop("research_memory")
        run_payload.pop("repair_memory", None)
        run_payload.pop("planned_candidate_families")
        run_payload.pop("selection_objective")
        run_payload.pop("completion_criteria")
    for artifact_payload in legacy_state["artifacts"]:
        if artifact_payload["kind"] != "plan":
            continue
        artifact_payload["content"].pop("research_memory_contract_version")
        artifact_payload["content"].pop("research_memory_digest")
        artifact_payload["content"].pop("candidate_families")
        artifact_payload["content"].pop("selection_objective")
        artifact_payload["content"].pop("completion_criteria")

    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p17-legacy-migration-test")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        row.state_json = legacy_state
        row.research_memory_contract_version = LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION
        row.row_version += 1
        db.commit()

    migrated_store = QuantStore()
    migrated = migrated_store.get_run(workspace_id=workspace_id, run_id=target.id)
    assert migrated.research_memory_contract_version == RESEARCH_MEMORY_CONTRACT_VERSION
    assert migrated.research_memory is not None
    assert migrated.research_memory.source_run_ids == [source.id]
    assert migrated.research_memory.tested_candidate_keys == [prior.candidate_key]

    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p17-legacy-migration-verify")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        assert row.research_memory_contract_version == RESEARCH_MEMORY_CONTRACT_VERSION
        assert row.state_json["research_memory_manifest"][target.id] == {
            "contract_version": RESEARCH_MEMORY_CONTRACT_VERSION,
            "context_digest": migrated.research_memory.context_digest,
        }
        persisted_target = next(item for item in row.state_json["runs"] if item["id"] == target.id)
        persisted_plan = next(
            item
            for item in row.state_json["artifacts"]
            if item["id"] == persisted_target["plan_artifact_id"]
        )
        assert persisted_target["selection_objective"] == "risk_adjusted_return"
        assert persisted_plan["content"]["selection_objective"] == "risk_adjusted_return"
        assert (
            persisted_plan["content"]["candidate_families"]
            == persisted_target["planned_candidate_families"]
        )
        assert (
            persisted_plan["content"]["completion_criteria"]
            == persisted_target["completion_criteria"]
        )

    fresh = QuantStore().get_run(workspace_id=workspace_id, run_id=target.id)
    assert fresh.research_memory == migrated.research_memory


@pytest.mark.parametrize("failure_timing", ["precommit", "postcommit"])
def test_legacy_memory_migration_reconciles_commit_failure_without_current_cache_ghosts(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
    failure_timing: str,
) -> None:
    workspace_id = _workspace(client, principal_id, f"P17 legacy {failure_timing} commit")
    control_workspace_id = _workspace(client, principal_id, "P17 migration cache control")
    seed_store = QuantStore()
    project = seed_store.create_project(
        workspace_id=workspace_id,
        name="Legacy migration commit boundary",
        objective="Keep cache publication aligned with the durable contract.",
    )
    target = _create_plan_run(
        seed_store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="Materialize this legacy Run exactly once.",
    )
    control_project = seed_store.create_project(
        workspace_id=control_workspace_id,
        name="Unrelated workspace",
        objective="Remain untouched by target-workspace reconciliation.",
    )

    legacy_state = deepcopy(
        seed_store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    )
    legacy_state.pop("research_memory_manifest")
    legacy_state.pop("verified_learning_policy", None)
    for run_payload in legacy_state["runs"]:
        run_payload.pop("research_memory_contract_version")
        run_payload.pop("research_memory")
        run_payload.pop("repair_memory", None)
    for artifact_payload in legacy_state["artifacts"]:
        if artifact_payload["kind"] != "plan":
            continue
        artifact_payload["content"].pop("research_memory_contract_version")
        artifact_payload["content"].pop("research_memory_digest")
    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p17-legacy-commit-failure-setup")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        row.state_json = legacy_state
        row.research_memory_contract_version = LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION
        row.row_version += 1
        db.commit()

    migrating_store = QuantStore()
    assert (
        migrating_store.get_project(
            workspace_id=control_workspace_id,
            project_id=control_project.id,
        ).id
        == control_project.id
    )
    target_cache_before = migrating_store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    control_cache_before = migrating_store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        control_workspace_id
    )
    original_commit = Session.commit
    injected = False

    def fail_migration_commit(session: Session) -> None:
        nonlocal injected
        if injected:
            original_commit(session)
            return
        injected = True
        if failure_timing == "postcommit":
            original_commit(session)
        raise RuntimeError(f"injected {failure_timing} legacy migration commit failure")

    monkeypatch.setattr(Session, "commit", fail_migration_commit)

    if failure_timing == "precommit":
        with pytest.raises(
            RuntimeError,
            match="injected precommit legacy migration commit failure",
        ):
            migrating_store.get_run(workspace_id=workspace_id, run_id=target.id)
        assert workspace_id not in migrating_store._loaded_workspaces  # pyright: ignore[reportPrivateUsage]
        assert workspace_id not in migrating_store._storage_versions  # pyright: ignore[reportPrivateUsage]
        assert (
            migrating_store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
            == target_cache_before
        )
        with get_session_factory()() as db:
            set_rls_context(db, workspace_id, "p17-precommit-durable-check")
            durable_row = db.get(QuantRepositoryState, workspace_id)
            assert durable_row is not None
            assert (
                durable_row.research_memory_contract_version
                == LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION
            )
            assert "research_memory_manifest" not in durable_row.state_json
        migrated = QuantStore().get_run(workspace_id=workspace_id, run_id=target.id)
    else:
        migrated = migrating_store.get_run(workspace_id=workspace_id, run_id=target.id)
        assert workspace_id in migrating_store._loaded_workspaces  # pyright: ignore[reportPrivateUsage]

    assert (
        migrating_store._workspace_state(  # pyright: ignore[reportPrivateUsage]
            control_workspace_id
        )
        == control_cache_before
    )
    assert migrated.research_memory_contract_version == RESEARCH_MEMORY_CONTRACT_VERSION
    assert migrated.research_memory is not None
    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p17-commit-reconciliation-verify")
        durable_row = db.get(QuantRepositoryState, workspace_id)
        assert durable_row is not None
        assert durable_row.research_memory_contract_version == RESEARCH_MEMORY_CONTRACT_VERSION
        assert durable_row.state_json["research_memory_manifest"][target.id] == {
            "contract_version": RESEARCH_MEMORY_CONTRACT_VERSION,
            "context_digest": migrated.research_memory.context_digest,
        }
    fresh = QuantStore().get_run(workspace_id=workspace_id, run_id=target.id)
    assert fresh.research_memory == migrated.research_memory


@pytest.mark.parametrize("contract", ["legacy", "private_market", "public_market"])
def test_each_run_create_contract_rolls_back_memory_builder_failure_without_ghost_state(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
    contract: str,
) -> None:
    workspace_id = _workspace(client, principal_id, f"P17 {contract} builder rollback")
    store = QuantStore()
    project_id, market_record = _setup_contract_creation(
        store,
        workspace_id=workspace_id,
        contract=contract,
    )
    project_reference = store.get_project(workspace_id=workspace_id, project_id=project_id)
    reference_before = (
        project_reference.latest_run_id,
        project_reference.row_version,
        project_reference.updated_at,
    )
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    def fail_memory_builder(*_: Any, **__: Any) -> None:
        raise RuntimeError("injected P17 memory builder failure")

    monkeypatch.setattr(store, "_build_research_memory_pin", fail_memory_builder)
    with pytest.raises(RuntimeError, match="injected P17 memory builder failure"):
        _create_run_by_contract(
            store,
            workspace_id=workspace_id,
            project_id=project_id,
            contract=contract,
            market_record=market_record,
        )

    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
    assert (
        project_reference.latest_run_id,
        project_reference.row_version,
        project_reference.updated_at,
    ) == reference_before
    reloaded = QuantStore()
    reloaded.list_projects(workspace_id=workspace_id)
    assert reloaded._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("contract", ["legacy", "private_market", "public_market"])
@pytest.mark.parametrize("failure_timing", ["precommit", "postcommit"])
def test_each_run_create_contract_reconciles_persist_failure_without_split_brain(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
    contract: str,
    failure_timing: str,
) -> None:
    workspace_id = _workspace(
        client,
        principal_id,
        f"P17 {contract} {failure_timing} persist",
    )
    store = QuantStore()
    project_id, market_record = _setup_contract_creation(
        store,
        workspace_id=workspace_id,
        contract=contract,
    )
    project_reference = store.get_project(workspace_id=workspace_id, project_id=project_id)
    reference_before = (
        project_reference.latest_run_id,
        project_reference.row_version,
    )
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    original_persist = store._persist_workspace  # pyright: ignore[reportPrivateUsage]

    def fail_persist(target_workspace_id: str) -> None:
        if failure_timing == "postcommit":
            original_persist(target_workspace_id)
        raise RuntimeError(f"injected {failure_timing} P17 persist failure")

    monkeypatch.setattr(store, "_persist_workspace", fail_persist)
    if failure_timing == "precommit":
        with pytest.raises(RuntimeError, match="injected precommit P17 persist failure"):
            _create_run_by_contract(
                store,
                workspace_id=workspace_id,
                project_id=project_id,
                contract=contract,
                market_record=market_record,
            )
        assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
        assert (
            project_reference.latest_run_id,
            project_reference.row_version,
        ) == reference_before
    else:
        created = _create_run_by_contract(
            store,
            workspace_id=workspace_id,
            project_id=project_id,
            contract=contract,
            market_record=market_record,
        )
        assert project_reference.latest_run_id == created.id
        assert store._workspace_state(workspace_id) != baseline  # pyright: ignore[reportPrivateUsage]
    reloaded = QuantStore()
    reloaded.list_projects(workspace_id=workspace_id)
    assert reloaded._workspace_state(workspace_id) == store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )


def test_retry_clones_old_pin_while_continue_retrieves_fresh_terminal_history(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id = _workspace(client, principal_id, "P17 retry versus continue")
    store = QuantStore()
    project = store.create_project(
        workspace_id=workspace_id,
        name="Version lineage",
        objective="Distinguish an attempt from a fresh version.",
    )
    root = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="Root source.",
    )
    root_seed = _add_completed_candidate(
        store,
        root,
        suffix="root",
        template="sma_crossover",
        parameters={"fast_window": 17, "slow_window": 97},
    )
    _complete_run(store, root)
    first_version = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=project.id,
        question="First continued version.",
        parent=root,
        seed=root_seed,
    )
    version_seed = _add_completed_candidate(
        store,
        first_version,
        suffix="version",
        template="breakout",
        parameters={"lookback_window": 73},
    )
    assert first_version.research_memory is not None
    first_pin = first_version.research_memory.model_dump(mode="json")
    _complete_run(store, first_version)

    history_project = store.create_project(
        workspace_id=workspace_id,
        name="Later history",
        objective="Become eligible only after the first version started.",
    )
    later = _create_plan_run(
        store,
        workspace_id=workspace_id,
        project_id=history_project.id,
        question="Later terminal source.",
    )
    _add_completed_candidate(
        store,
        later,
        suffix="later",
        template="rsi_mean_reversion",
        parameters={"period": 14, "entry_threshold": 23, "exit_threshold": 59},
    )
    _complete_run(store, later)

    retry = store.retry_run(
        workspace_id=workspace_id,
        run_id=first_version.id,
        expected_row_version=first_version.row_version,
        reason="Repeat the exact first-version attempt.",
    )
    assert retry.research_memory is not None
    assert retry.research_memory.model_dump(mode="json") == first_pin
    assert later.id not in retry.research_memory.source_run_ids

    current_project = store.get_project(workspace_id=workspace_id, project_id=project.id)
    continued = store.create_run(
        workspace_id=workspace_id,
        project_id=project.id,
        question="Fresh continued version.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=current_project.row_version,
        parent_run_id=first_version.id,
        seed_candidate_id=version_seed.id,
        refinement_reason="Retrieve terminal history available at this new version.",
    )
    assert continued.research_memory is not None
    assert continued.research_memory.model_dump(mode="json") != first_pin
    assert continued.research_memory.source_run_ids[:2] == [first_version.id, root.id]
    assert later.id in continued.research_memory.source_run_ids


def test_public_market_memory_excludes_same_dataset_private_runtime_source(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id = _workspace(client, principal_id, "P17 public excludes private")
    store = QuantStore()
    record = store.import_market_dataset_v2_csv(
        workspace_id=workspace_id,
        name="Shared BTCUSDT 1h",
        symbol="BTCUSDT",
        interval=QuantBarInterval.HOUR,
        csv_text=_market_csv(),
        source_name="P17 visibility CSV",
        source_reference="test:p17:visibility",
        file_name="visibility.csv",
    )
    private_project = store.create_project(
        workspace_id=workspace_id,
        name="Private source",
        objective="Must not enter public history.",
    )
    private_run = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=private_project.id,
        question="Internal verification source.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=private_project.row_version,
        dataset_id=record.id,
    )
    _add_completed_candidate(
        store,
        private_run,
        suffix="private",
        template="breakout",
        parameters={"lookback_window": 47},
    )
    _complete_run(store, private_run)

    public_project = store.create_project(
        workspace_id=workspace_id,
        name="Public target",
        objective="Use only public market history.",
    )
    public_run = store.create_market_run(
        workspace_id=workspace_id,
        project_id=public_project.id,
        question="Public bounded market target.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=public_project.row_version,
        dataset_id=record.id,
        research_start_utc=record.dataset.covered_start,
        research_end_utc=record.dataset.covered_end,
    )
    assert public_run.research_memory is not None
    assert private_run.id not in public_run.research_memory.source_run_ids
    assert all(source.run_id != private_run.id for source in public_run.research_memory.sources)


def test_mock_provider_skips_pinned_exact_key_without_series_context() -> None:
    candidate_key = QuantStore.canonical_candidate_key(
        "sma_crossover", {"fast_window": 50, "slow_window": 200}
    )
    payload = {
        "schema_version": "quant-research-memory-v1",
        "source_run_ids": ["source-run"],
        "sources": [
            {
                "run_id": "source-run",
                "relationship": "workspace_history",
                "attempt_number": 1,
                "retry_of_run_id": None,
                "dataset_id": "dataset",
                "dataset_digest": "sha256:dataset",
                "symbol": "SPY",
                "interval": "1D",
                "periods_per_year": 252,
                "range_start": "2020-01-01",
                "range_end": "2024-01-01",
                "runtime_descriptor_digest": "sha256:runtime",
                "training_split_digest": "sha256:split",
                "selection_objective": "risk_adjusted_return",
                "comparability": "same_evidence",
                "limitations": [
                    "duplicate_avoidance_only",
                    "prior_training_context_only",
                ],
            }
        ],
        "tested_candidate_keys": [candidate_key],
        "candidates": [
            {
                "source_run_id": "source-run",
                "candidate_key": candidate_key,
                "template": "sma_crossover",
                "parameters": {"fast_window": 50, "slow_window": 200},
                "training_rank": 1,
                "training_failure_category": None,
            }
        ],
        "comparability": "same_evidence",
    }
    memory = QuantResearchMemoryContext.model_validate(
        {**payload, "context_digest": canonical_digest(payload)}
    )
    context = QuantAgentContext(
        run_id="run",
        project_id="project",
        research_goal="Reduce drawdown",
        mode="auto",
        run_state="running_experiments",
        dataset_summary={},
        benchmark_summary=None,
        available_templates=[],
        candidates=[],
        budget=QuantAgentBudget(
            max_iterations=12,
            used_iterations=2,
            remaining_iterations=10,
            max_experiments=3,
            used_experiments=0,
            remaining_experiments=3,
            max_repairs=2,
            used_repairs=0,
            remaining_repairs=2,
        ),
        recent_events=[],
        recent_observations=[
            {"action": "inspect_research_context", "success": True},
            {"action": "list_strategy_templates", "success": True},
        ],
        plan_summary=None,
        final_conclusion=None,
        research_memory=memory,
    )

    decision = MockQuantAgentProvider().decide(context)

    assert decision.action.value == "create_candidate"
    assert (
        QuantStore.canonical_candidate_key(
            str(decision.arguments["template"]),
            dict(decision.arguments["parameters"]),
        )
        not in memory.tested_candidate_keys
    )


def test_mock_provider_finishes_safely_when_bounded_candidate_set_is_exhausted() -> None:
    bounded_candidates = [
        ("sma_crossover", {"fast_window": 50, "slow_window": 200}),
        ("sma_crossover", {"fast_window": 20, "slow_window": 100}),
        ("breakout", {"lookback_window": 200}),
        ("sma_crossover", {"fast_window": 15, "slow_window": 80}),
        ("sma_crossover", {"fast_window": 30, "slow_window": 150}),
        ("sma_crossover", {"fast_window": 10, "slow_window": 60}),
        (
            "rsi_mean_reversion",
            {"period": 14, "entry_threshold": 28, "exit_threshold": 58},
        ),
        (
            "rsi_mean_reversion",
            {"period": 14, "entry_threshold": 20, "exit_threshold": 50},
        ),
        (
            "rsi_mean_reversion",
            {"period": 14, "entry_threshold": 35, "exit_threshold": 65},
        ),
        ("breakout", {"lookback_window": 40}),
        ("breakout", {"lookback_window": 80}),
        ("breakout", {"lookback_window": 120}),
    ]
    memory_candidates = [
        {
            "source_run_id": "source-run",
            "candidate_key": QuantStore.canonical_candidate_key(template, parameters),
            "template": template,
            "parameters": parameters,
            "training_rank": None,
            "training_failure_category": None,
        }
        for template, parameters in bounded_candidates
    ]
    payload = {
        "schema_version": "quant-research-memory-v1",
        "source_run_ids": ["source-run"],
        "sources": [
            {
                "run_id": "source-run",
                "relationship": "workspace_history",
                "attempt_number": 1,
                "retry_of_run_id": None,
                "dataset_id": "dataset",
                "dataset_digest": "sha256:dataset",
                "symbol": "SPY",
                "interval": "1D",
                "periods_per_year": 252,
                "range_start": "2020-01-01",
                "range_end": "2024-01-01",
                "runtime_descriptor_digest": "sha256:runtime",
                "training_split_digest": "sha256:split",
                "selection_objective": "risk_adjusted_return",
                "comparability": "same_evidence",
                "limitations": [
                    "duplicate_avoidance_only",
                    "prior_training_context_only",
                ],
            }
        ],
        "tested_candidate_keys": [candidate["candidate_key"] for candidate in memory_candidates],
        "candidates": memory_candidates,
        "comparability": "same_evidence",
    }
    memory = QuantResearchMemoryContext.model_validate(
        {**payload, "context_digest": canonical_digest(payload)}
    )
    context = QuantAgentContext(
        run_id="run",
        project_id="project",
        research_goal="Reduce drawdown",
        mode="auto",
        run_state="running_experiments",
        dataset_summary={},
        benchmark_summary=None,
        available_templates=[],
        candidates=[],
        budget=QuantAgentBudget(
            max_iterations=12,
            used_iterations=2,
            remaining_iterations=10,
            max_experiments=3,
            used_experiments=0,
            remaining_experiments=3,
            max_repairs=2,
            used_repairs=0,
            remaining_repairs=2,
        ),
        recent_events=[],
        recent_observations=[
            {"action": "inspect_research_context", "success": True},
            {"action": "list_strategy_templates", "success": True},
        ],
        plan_summary=None,
        final_conclusion=None,
        research_memory=memory,
    )

    decision = MockQuantAgentProvider().decide(context)

    assert decision.action.value == "finish_research"
    assert decision.arguments["selected_candidate_id"] is None
    assert decision.arguments["next_step"] == "stop"
