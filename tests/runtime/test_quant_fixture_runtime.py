from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID

import pytest

from packages.contracts.quant.enums import (
    QuantCandidateVerdict,
    QuantEventType,
    QuantFixtureScenario,
    QuantRunState,
)
from packages.contracts.quant.runtime import build_quant_script


RUN_ID = str(UUID("55555555-5555-4555-8555-555555555555"))


def _event_types(scenario: QuantFixtureScenario) -> list[QuantEventType]:
    return [step.event_type for step in build_quant_script(run_id=RUN_ID, scenario=scenario)]


def test_normal_fixture_repairs_candidate_without_failing_run() -> None:
    steps = build_quant_script(run_id=RUN_ID, scenario=QuantFixtureScenario.NORMAL)
    event_types = [step.event_type for step in steps]
    assert QuantEventType.BACKTEST_FAILED in event_types
    assert QuantEventType.REPAIR_STARTED in event_types
    assert QuantEventType.REPAIR_COMPLETED in event_types
    assert QuantEventType.RUN_FAILED not in event_types
    backtest_failure = next(step for step in steps if step.event_type == QuantEventType.BACKTEST_FAILED)
    assert backtest_failure.payload.candidate_key == "B"
    assert backtest_failure.run_state == QuantRunState.REPAIRING
    assert steps[-1].event_type == QuantEventType.REVIEW_REQUIRED
    assert steps[-1].run_state == QuantRunState.WAITING_FOR_REVIEW


def test_no_viable_candidate_is_a_healthy_reviewable_result() -> None:
    steps = build_quant_script(run_id=RUN_ID, scenario=QuantFixtureScenario.NO_VIABLE)
    verdicts = [
        step.payload.verdict
        for step in steps
        if step.event_type == QuantEventType.CANDIDATE_REJECTED
    ]
    assert verdicts == [QuantCandidateVerdict.REJECTED] * 3
    assert QuantEventType.RUN_FAILED not in [step.event_type for step in steps]
    assert steps[-1].run_state == QuantRunState.WAITING_FOR_REVIEW


@pytest.mark.parametrize(
    ("scenario", "terminal_event", "terminal_state"),
    [
        (QuantFixtureScenario.FAILED_SAFE, QuantEventType.RUN_FAILED, QuantRunState.FAILED),
        (QuantFixtureScenario.CANCELLED, QuantEventType.RUN_CANCELLED, QuantRunState.CANCELLED),
    ],
)
def test_terminal_fixture_stops_emitting_after_terminal_event(
    scenario: QuantFixtureScenario,
    terminal_event: QuantEventType,
    terminal_state: QuantRunState,
) -> None:
    steps = build_quant_script(run_id=RUN_ID, scenario=scenario)
    assert steps[-1].terminal is True
    assert steps[-1].event_type == terminal_event
    assert steps[-1].run_state == terminal_state
    assert _event_types(scenario).count(terminal_event) == 1


def test_fixture_runtime_has_no_network_process_or_arbitrary_execution_imports() -> None:
    source_path = Path(__file__).parents[2] / "packages/contracts/quant/runtime.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert imported_roots.isdisjoint(
        {"asyncio", "httpx", "requests", "socket", "subprocess", "urllib"}
    )
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint({"eval", "exec", "compile", "__import__"})
