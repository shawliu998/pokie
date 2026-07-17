from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from packages.domain.quant_backtest import (
    BacktestInputError,
    DailyBar,
    ExecutionConfig,
    StrategyFamily,
    StrategySpec,
    backtest_buy_and_hold,
    run_backtest,
    validate_bars,
)


def bars(closes: list[float], *, opens: list[float] | None = None) -> tuple[DailyBar, ...]:
    opens = opens or closes
    return tuple(
        DailyBar(
            date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + index),
            opening,
            max(opening, close),
            min(opening, close),
            close,
        )
        for index, (opening, close) in enumerate(zip(opens, closes))
    )


def test_next_bar_open_execution_and_costs_are_deterministic() -> None:
    data = bars([10, 20, 20, 10], opens=[10, 50, 20, 8])
    config = ExecutionConfig(initial_cash=1_000, fee_rate=0.01, slippage_rate=0.1)
    result = run_backtest(data, StrategySpec.sma(2, 3), config)
    assert result.equity_curve[0].quantity == 0
    assert result.equity_curve[1].quantity == 0
    assert result.equity_curve[2].quantity == 0
    assert result.equity_curve[3].quantity == pytest.approx(1_000 / (8 * 1.1 * 1.01))
    assert result.equity_curve[3].cash == 0
    assert result.trades == ()
    assert result == run_backtest(tuple(data), StrategySpec.sma(2, 3), config)


@pytest.mark.parametrize(
    "strategy",
    [StrategySpec.sma(2, 3), StrategySpec.rsi(2), StrategySpec.breakout(2)],
)
def test_each_strategy_family_runs_without_optional_dependencies(strategy: StrategySpec) -> None:
    result = run_backtest(bars([10, 9, 11, 12, 10, 13, 14, 12]), strategy)
    assert result.strategy is strategy
    assert len(result.equity_curve) == 8
    assert result.metrics.final_equity >= 0


def test_buy_and_hold_is_a_single_deterministic_benchmark() -> None:
    result = backtest_buy_and_hold(
        bars([10, 12, 15], opens=[10, 11, 14]), ExecutionConfig(initial_cash=100)
    )
    assert result.strategy is None
    assert len(result.trades) == 1
    assert result.equity_curve[0].equity == 100.0
    assert result.equity_curve[-1].equity == 150.0
    assert result.metrics.trade_count == 1


def test_empty_and_insufficient_data_are_stable() -> None:
    empty = run_backtest((), StrategySpec.sma(2, 3))
    assert empty.equity_curve == ()
    assert empty.trades == ()
    assert empty.metrics.final_equity == 100_000.0
    assert backtest_buy_and_hold(()).metrics.total_return == 0.0
    insufficient = run_backtest(bars([10, 11]), StrategySpec.sma(2, 3))
    assert insufficient.trades == ()
    assert all(point.quantity == 0 for point in insufficient.equity_curve)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: StrategySpec.sma(0, 3),
        lambda: StrategySpec.sma(3, 3),
        lambda: StrategySpec.rsi(0),
        lambda: StrategySpec.rsi(2, oversold=80, overbought=70),
        lambda: StrategySpec.breakout(0),
    ],
)
def test_strategy_validation(factory) -> None:
    with pytest.raises(BacktestInputError):
        factory()


def test_bar_and_execution_validation() -> None:
    with pytest.raises(BacktestInputError):
        DailyBar(date(2026, 1, 1), 10, 9, 8, 9)
    with pytest.raises(BacktestInputError):
        validate_bars(bars([10, 11]) + (bars([12])[0],))
    with pytest.raises(BacktestInputError):
        ExecutionConfig(initial_cash=0)
    with pytest.raises(BacktestInputError):
        run_backtest(bars([10]), "sma")


def test_kernel_has_no_network_process_or_model_boundaries() -> None:
    source_path = Path(__file__).parents[2] / "packages/domain/quant_backtest.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
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
    assert roots.isdisjoint({"httpx", "requests", "socket", "subprocess", "urllib", "openai"})
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint({"eval", "exec", "compile", "__import__"})


def test_strategy_family_values_are_stable() -> None:
    assert tuple(family.value for family in StrategyFamily) == ("sma", "rsi", "breakout")
