from __future__ import annotations

import ast
from pathlib import Path

from services.api.app.modules.quant.kernel_check import (
    build_quant_kernel_check,
    build_quant_research_projection,
)


def test_computed_research_projection_is_deterministic_and_consistent() -> None:
    check = build_quant_kernel_check()
    projection = build_quant_research_projection()

    assert check == build_quant_kernel_check()
    assert projection == build_quant_research_projection()
    assert check["barCount"] == 1564
    assert check["benchmark"]["annualizedReturnPct"] == 23.22
    assert projection["benchmark"] == {
        "annualizedReturn": 23.2,
        "maxDrawdown": -23.8,
        "sharpe": 5.3,
        "trades": 1,
    }
    assert [candidate["verdict"] for candidate in projection["candidates"]] == [
        "rejected",
        "promising",
        "inconclusive",
    ]
    assert [candidate["metrics"]["trades"] for candidate in projection["candidates"]] == [
        7,
        2,
        2,
    ]
    assert len(projection["trades"]) == 2


def test_no_viable_projection_changes_verdicts_not_computed_metrics() -> None:
    normal = build_quant_research_projection()
    negative = build_quant_research_projection(no_viable=True)

    assert all(candidate["verdict"] == "rejected" for candidate in negative["candidates"])
    assert [item["metrics"] for item in negative["candidates"]] == [
        item["metrics"] for item in normal["candidates"]
    ]
    assert "still completed normally" in negative["conclusion"]


def test_research_adapter_has_no_network_process_model_or_arbitrary_execution() -> None:
    source = (
        Path(__file__).parents[2]
        / "services/api/app/modules/quant/kernel_check.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    roots.update(
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert roots.isdisjoint(
        {"httpx", "requests", "socket", "subprocess", "urllib", "openai"}
    )
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called.isdisjoint({"eval", "exec", "compile", "__import__"})
