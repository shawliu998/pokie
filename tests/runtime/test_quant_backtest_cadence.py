from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from packages.domain.quant_backtest import (
    BacktestCadence,
    BacktestInputError,
    BacktestInterval,
    DailyBar,
    ExecutionConfig,
    MarketBar,
    StrategySpec,
    backtest_buy_and_hold,
    run_backtest,
)


def market_bars(
    closes: Sequence[float],
    *,
    opens: Sequence[float] | None = None,
    step: timedelta = timedelta(hours=1),
) -> tuple[MarketBar, ...]:
    opens = opens or closes
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        MarketBar(
            timestamp=start + index * step,
            open=opening,
            high=max(opening, close),
            low=min(opening, close),
            close=close,
            volume=10.5 + index,
        )
        for index, (opening, close) in enumerate(zip(opens, closes, strict=True))
    )


def daily_bars(
    closes: Sequence[float], *, opens: Sequence[float] | None = None
) -> tuple[DailyBar, ...]:
    opens = opens or closes
    start = date(2026, 1, 1)
    return tuple(
        DailyBar(
            date=start + timedelta(days=index),
            open=opening,
            high=max(opening, close),
            low=min(opening, close),
            close=close,
            volume=10.5 + index,
        )
        for index, (opening, close) in enumerate(zip(opens, closes, strict=True))
    )


def test_continuous_cadence_mapping_and_validation_are_explicit() -> None:
    assert BacktestCadence.continuous("1h") == BacktestCadence(BacktestInterval.HOUR, 8_760)
    assert BacktestCadence.continuous("4h") == BacktestCadence(BacktestInterval.FOUR_HOURS, 2_190)
    assert BacktestCadence.continuous("1D") == BacktestCadence(BacktestInterval.DAILY, 365)
    with pytest.raises(BacktestInputError, match="interval"):
        BacktestCadence("15m", 1)  # type: ignore[arg-type]
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(BacktestInputError, match="periods_per_year"):
            BacktestCadence(BacktestInterval.HOUR, invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("interval", "periods_per_year"),
    [
        (BacktestInterval.HOUR, 8_760),
        (BacktestInterval.FOUR_HOURS, 2_190),
        (BacktestInterval.DAILY, 252),
        (BacktestInterval.DAILY, 365),
    ],
)
def test_only_modeled_interval_annualization_pairs_are_accepted(
    interval: BacktestInterval, periods_per_year: int
) -> None:
    assert BacktestCadence(interval, periods_per_year).periods_per_year == periods_per_year


@pytest.mark.parametrize(
    ("interval", "periods_per_year"),
    [
        (BacktestInterval.HOUR, 252),
        (BacktestInterval.HOUR, 365),
        (BacktestInterval.FOUR_HOURS, 252),
        (BacktestInterval.FOUR_HOURS, 8_760),
        (BacktestInterval.DAILY, 2_190),
        (BacktestInterval.DAILY, 8_760),
    ],
)
def test_scientifically_invalid_interval_annualization_pairs_are_rejected(
    interval: BacktestInterval, periods_per_year: int
) -> None:
    with pytest.raises(BacktestInputError, match="interval and periods_per_year"):
        BacktestCadence(interval, periods_per_year)


def test_market_bar_is_independent_strict_utc_and_finite() -> None:
    bar = market_bars([100])[0]
    assert not isinstance(bar, DailyBar)
    with pytest.raises(BacktestInputError, match="UTC"):
        MarketBar(datetime(2026, 1, 1), 1, 1, 1, 1, 1)
    with pytest.raises(BacktestInputError, match="UTC"):
        MarketBar(
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8))),
            1,
            1,
            1,
            1,
            1,
        )
    for values in (
        (0, 1, 1, 1, 1),
        (1, 0.5, 1, 1, 1),
        (1, 1, 2, 1, 1),
        (1, 1, 1, math.inf, 1),
        (1, 1, 1, 1, -1),
        (1, 1, 1, 1, math.nan),
        (1, 1, 1, 1, math.inf),
    ):
        with pytest.raises(BacktestInputError):
            MarketBar(datetime(2026, 1, 1, tzinfo=UTC), *values)


def test_market_bars_require_cadence_and_reject_mixed_or_unordered_inputs() -> None:
    data = market_bars([10, 11])
    with pytest.raises(BacktestInputError, match="cadence"):
        run_backtest(data, StrategySpec.breakout(1))
    with pytest.raises(BacktestInputError, match="cadence"):
        backtest_buy_and_hold(data)
    with pytest.raises(BacktestInputError, match="BacktestCadence"):
        backtest_buy_and_hold(data, cadence="1h")  # type: ignore[arg-type]
    with pytest.raises(BacktestInputError, match="mix"):
        run_backtest(
            (daily_bars([10])[0], data[1]),
            StrategySpec.breakout(1),
            cadence=BacktestCadence.continuous("1h"),
        )
    with pytest.raises(BacktestInputError, match="timestamp"):
        backtest_buy_and_hold((data[1], data[0]), cadence=BacktestCadence.continuous("1h"))
    with pytest.raises(BacktestInputError, match="timestamp"):
        backtest_buy_and_hold((data[0], data[0]), cadence=BacktestCadence.continuous("1h"))


@pytest.mark.parametrize(
    ("cadence", "timestamp"),
    [
        (
            BacktestCadence.continuous("1h"),
            datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
        ),
        (
            BacktestCadence.continuous("4h"),
            datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
        ),
        (
            BacktestCadence(BacktestInterval.DAILY, 252),
            datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        ),
        (
            BacktestCadence(BacktestInterval.DAILY, 365),
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        ),
    ],
)
def test_market_bar_timestamps_must_align_to_their_cadence(
    cadence: BacktestCadence, timestamp: datetime
) -> None:
    bar = MarketBar(timestamp, 10, 10, 10, 10, 1)
    with pytest.raises(BacktestInputError, match="align"):
        backtest_buy_and_hold((bar,), cadence=cadence)


def test_empty_single_bar_and_zero_deviation_market_metrics_are_stable() -> None:
    cadence = BacktestCadence.continuous("1h")
    empty = run_backtest((), StrategySpec.breakout(1), cadence=cadence)
    single = backtest_buy_and_hold(market_bars([10]), cadence=cadence)
    flat = backtest_buy_and_hold(market_bars([10, 10, 10]), cadence=cadence)
    assert empty.metrics.final_equity == 100_000.0
    assert empty.metrics.annualized_return == empty.metrics.sharpe_ratio == 0.0
    assert single.metrics.annualized_return == single.metrics.sharpe_ratio == 0.0
    assert flat.metrics.annualized_return == flat.metrics.sharpe_ratio == 0.0


def test_daily_default_and_explicit_1d_252_are_identical() -> None:
    data = daily_bars([10, 9, 11, 12, 10, 13, 14, 12])
    cadence = BacktestCadence(BacktestInterval.DAILY, 252)
    strategy = StrategySpec.breakout(2)
    assert run_backtest(data, strategy) == run_backtest(data, strategy, cadence=cadence)
    assert backtest_buy_and_hold(data) == backtest_buy_and_hold(data, cadence=cadence)
    for wrong in (
        BacktestCadence.continuous("1D"),
        BacktestCadence.continuous("1h"),
    ):
        with pytest.raises(BacktestInputError, match="DailyBar"):
            run_backtest(data, strategy, cadence=wrong)


def test_daily_default_path_has_a_small_fixed_golden() -> None:
    result = run_backtest(
        daily_bars([10, 20, 20, 10, 10], opens=[10, 50, 20, 8, 7]),
        StrategySpec.sma(2, 3),
        ExecutionConfig(initial_cash=1_000),
    )

    assert (
        result.metrics.initial_equity,
        result.metrics.final_equity,
        result.metrics.total_return,
        result.metrics.annualized_return,
        result.metrics.max_drawdown,
        result.metrics.sharpe_ratio,
        result.metrics.trade_count,
        result.metrics.exposure,
    ) == (
        1_000,
        875.0,
        -0.125,
        -0.999777921078,
        -0.3,
        -1.018350154435,
        1,
        0.2,
    )
    assert tuple(
        (point.date, point.cash, point.quantity, point.close, point.equity, point.timestamp)
        for point in result.equity_curve
    ) == (
        (date(2026, 1, 1), 1_000.0, 0.0, 10, 1_000.0, None),
        (date(2026, 1, 2), 1_000.0, 0.0, 20, 1_000.0, None),
        (date(2026, 1, 3), 1_000.0, 0.0, 20, 1_000.0, None),
        (date(2026, 1, 4), 0.0, 125.0, 10, 1_250.0, None),
        (date(2026, 1, 5), 875.0, 0.0, 10, 875.0, None),
    )
    trade = result.trades[0]
    assert (
        trade.entry_date,
        trade.entry_price,
        trade.exit_date,
        trade.exit_price,
        trade.quantity,
        trade.pnl,
        trade.return_pct,
        trade.entry_timestamp,
        trade.exit_timestamp,
        trade.holding_bars,
        trade.holding_elapsed_seconds,
    ) == (
        date(2026, 1, 4),
        8.0,
        date(2026, 1, 5),
        7.0,
        125.0,
        -125.0,
        -0.125,
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    ("cadence", "step"),
    [
        (BacktestCadence.continuous("1h"), timedelta(hours=1)),
        (BacktestCadence.continuous("4h"), timedelta(hours=4)),
    ],
)
def test_market_cagr_and_sharpe_use_explicit_periods_per_year(
    cadence: BacktestCadence, step: timedelta
) -> None:
    result = backtest_buy_and_hold(market_bars([100, 110, 110], step=step), cadence=cadence)
    expected_cagr = 1.1 ** (cadence.periods_per_year / 2) - 1
    assert result.metrics.annualized_return == pytest.approx(expected_cagr, rel=1e-12)
    assert result.metrics.sharpe_ratio == pytest.approx(
        math.sqrt(cadence.periods_per_year), rel=1e-12
    )


def test_strategy_and_benchmark_share_cadence_metric_math() -> None:
    cadence = BacktestCadence.continuous("1h")
    data = market_bars([10, 20, 20, 10, 12, 9], opens=[10, 50, 20, 8, 11, 7])
    strategy = run_backtest(data, StrategySpec.sma(2, 3), cadence=cadence)
    benchmark = backtest_buy_and_hold(data, cadence=cadence)
    for result in (strategy, benchmark):
        curve = result.equity_curve
        expected_years = (len(curve) - 1) / cadence.periods_per_year
        expected_cagr = (
            (curve[-1].equity / curve[0].equity) ** (1 / expected_years) - 1
            if expected_years > 0
            else 0.0
        )
        returns = [
            curve[index].equity / curve[index - 1].equity - 1 for index in range(1, len(curve))
        ]
        average = sum(returns) / len(returns)
        deviation = math.sqrt(sum((value - average) ** 2 for value in returns) / len(returns))
        expected_sharpe = average / deviation * math.sqrt(cadence.periods_per_year)
        assert result.metrics.annualized_return == pytest.approx(expected_cagr)
        assert result.metrics.sharpe_ratio == pytest.approx(expected_sharpe)


def test_market_next_open_and_trade_holding_metadata_use_fill_indices() -> None:
    cadence = BacktestCadence.continuous("1h")
    data = market_bars(
        [10, 20, 20, 10, 10],
        opens=[10, 50, 20, 8, 7],
    )
    result = run_backtest(data, StrategySpec.sma(2, 3), cadence=cadence)
    trade = result.trades[0]
    assert trade.entry_timestamp is not None
    assert trade.exit_timestamp is not None
    assert trade.entry_price == 8
    assert trade.exit_price == 7
    assert trade.entry_date == trade.entry_timestamp.date()
    assert trade.exit_date == trade.exit_timestamp.date()
    assert trade.entry_timestamp == data[3].timestamp
    assert trade.exit_timestamp == data[4].timestamp
    assert trade.holding_bars == 1
    assert trade.holding_elapsed_seconds == 3_600
    assert tuple(point.timestamp for point in result.equity_curve) == tuple(
        bar.timestamp for bar in data
    )


def test_market_benchmark_holding_metadata_spans_first_to_last_bar() -> None:
    cadence = BacktestCadence.continuous("4h")
    data = market_bars([10, 11, 12], step=timedelta(hours=4))
    trade = backtest_buy_and_hold(data, cadence=cadence).trades[0]
    assert trade.holding_bars == 2
    assert trade.holding_elapsed_seconds == 8 * 60 * 60


def test_same_daily_path_with_market_1d_252_has_identical_metrics() -> None:
    closes = [10, 9, 11, 12, 10, 13, 14, 12]
    opens = [10, 9, 10, 11, 12, 10, 13, 14]
    daily = daily_bars(closes, opens=opens)
    market = market_bars(closes, opens=opens, step=timedelta(days=1))
    cadence = BacktestCadence(BacktestInterval.DAILY, 252)
    strategy = StrategySpec.breakout(2)
    assert (
        run_backtest(daily, strategy).metrics
        == run_backtest(market, strategy, cadence=cadence).metrics
    )
    assert (
        backtest_buy_and_hold(daily).metrics
        == backtest_buy_and_hold(market, cadence=cadence).metrics
    )


def test_market_backtests_are_deterministic() -> None:
    data = market_bars([10, 9, 11, 12, 10, 13])
    cadence = BacktestCadence.continuous("1h")
    strategy = StrategySpec.breakout(2)
    assert run_backtest(data, strategy, cadence=cadence) == run_backtest(
        tuple(data), strategy, cadence=cadence
    )
