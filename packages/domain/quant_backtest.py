"""Pure, deterministic daily and explicit-cadence market-bar backtesting primitives.

The kernel deliberately has no persistence, transport, market-data, broker, or
model boundary.  A strategy observes a completed bar and its order is filled
at the following bar's open.  It supports one asset and the two states needed
by the bounded Phase 1 scope: Long and Cash.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from statistics import mean, pstdev


class BacktestInputError(ValueError):
    """Raised when bars, strategy parameters, or execution assumptions are invalid."""


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class StrategyFamily(StrEnum):
    SMA = "sma"
    RSI = "rsi"
    BREAKOUT = "breakout"


class BacktestInterval(StrEnum):
    """Provider-neutral bar intervals supported by the C3A domain kernel."""

    HOUR = "1h"
    FOUR_HOURS = "4h"
    DAILY = "1D"


_PERIODS_PER_YEAR_BY_INTERVAL = {
    BacktestInterval.HOUR: frozenset({8_760}),
    BacktestInterval.FOUR_HOURS: frozenset({2_190}),
    BacktestInterval.DAILY: frozenset({252, 365}),
}


@dataclass(frozen=True, slots=True)
class BacktestCadence:
    """Explicit annualization cadence for timestamped market bars."""

    interval: BacktestInterval
    periods_per_year: int

    def __post_init__(self) -> None:
        try:
            interval = BacktestInterval(self.interval)
        except (TypeError, ValueError) as exc:
            raise BacktestInputError("cadence interval must be 1h, 4h, or 1D.") from exc
        object.__setattr__(self, "interval", interval)
        if (
            not isinstance(  # type: ignore[reportUnnecessaryIsInstance]
                self.periods_per_year, int
            )
            or isinstance(self.periods_per_year, bool)
            or self.periods_per_year <= 0
        ):
            raise BacktestInputError("periods_per_year must be a positive integer.")
        if self.periods_per_year not in _PERIODS_PER_YEAR_BY_INTERVAL[interval]:
            raise BacktestInputError(
                "cadence interval and periods_per_year must be one of "
                "1h/8760, 4h/2190, 1D/252, or 1D/365."
            )

    @classmethod
    def continuous(cls, interval: BacktestInterval | str) -> BacktestCadence:
        """Return the explicit 24x7 cadence for one supported interval."""

        try:
            checked_interval = BacktestInterval(interval)
        except (TypeError, ValueError) as exc:
            raise BacktestInputError("cadence interval must be 1h, 4h, or 1D.") from exc
        return cls(
            checked_interval,
            {
                BacktestInterval.HOUR: 8_760,
                BacktestInterval.FOUR_HOURS: 2_190,
                BacktestInterval.DAILY: 365,
            }[checked_interval],
        )


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One OHLCV bar for the single asset being tested."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.date, datetime) or not isinstance(  # type: ignore[reportUnnecessaryIsInstance]
            self.date, date
        ):
            raise BacktestInputError("bar.date must be a datetime.date, not a datetime.")
        values = (self.open, self.high, self.low, self.close)
        if not all(_finite_number(value) for value in values):
            raise BacktestInputError("OHLC values must be finite numbers.")
        if min(values) <= 0:
            raise BacktestInputError("OHLC values must be positive.")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise BacktestInputError("bar.high/bar.low must contain open and close.")
        if self.volume is not None and (not _finite_number(self.volume) or self.volume < 0):
            raise BacktestInputError("volume must be a finite non-negative number.")


@dataclass(frozen=True, slots=True)
class MarketBar:
    """One timestamped OHLCV bar, independent from the legacy DailyBar type."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if not isinstance(  # type: ignore[reportUnnecessaryIsInstance]
            self.timestamp, datetime
        ):
            raise BacktestInputError("bar.timestamp must be a UTC-aware datetime.")
        offset = self.timestamp.utcoffset()
        if self.timestamp.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise BacktestInputError("bar.timestamp must be a UTC-aware datetime.")
        values = (self.open, self.high, self.low, self.close)
        if not all(_finite_number(value) for value in values):
            raise BacktestInputError("OHLC values must be finite numbers.")
        if min(values) <= 0:
            raise BacktestInputError("OHLC values must be positive.")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise BacktestInputError("bar.high/bar.low must contain open and close.")
        if not _finite_number(self.volume) or self.volume < 0:
            raise BacktestInputError("volume must be a finite non-negative number.")


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """All-in execution assumptions shared by a strategy and its benchmark."""

    initial_cash: float = 100_000.0
    fee_rate: float = 0.0
    slippage_rate: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("initial_cash", self.initial_cash),
            ("fee_rate", self.fee_rate),
            ("slippage_rate", self.slippage_rate),
        ):
            if not _finite_number(value):
                raise BacktestInputError(f"{name} must be a finite number.")
        if self.initial_cash <= 0:
            raise BacktestInputError("initial_cash must be positive.")
        if self.fee_rate < 0 or self.slippage_rate < 0:
            raise BacktestInputError("fee_rate and slippage_rate cannot be negative.")
        if self.fee_rate >= 1 or self.slippage_rate >= 1:
            raise BacktestInputError("fee_rate and slippage_rate must be less than 1.")


# Keep the name short for the common call site while retaining the explicit name.
BacktestConfig = ExecutionConfig


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """Validated parameters for one supported long/cash strategy family."""

    family: StrategyFamily
    fast_period: int | None = None
    slow_period: int | None = None
    period: int | None = None
    oversold: float = 30.0
    overbought: float = 70.0

    def __post_init__(self) -> None:
        try:
            family = StrategyFamily(self.family)
        except (TypeError, ValueError) as exc:
            raise BacktestInputError("family must be sma, rsi, or breakout.") from exc
        object.__setattr__(self, "family", family)
        if family is StrategyFamily.SMA:
            if not _positive_int(self.fast_period) or not _positive_int(self.slow_period):
                raise BacktestInputError(
                    "SMA fast_period and slow_period must be positive integers."
                )
            assert self.fast_period is not None and self.slow_period is not None
            if self.fast_period >= self.slow_period:
                raise BacktestInputError("SMA fast_period must be smaller than slow_period.")
        elif family is StrategyFamily.RSI:
            if not _positive_int(self.period):
                raise BacktestInputError("RSI period must be a positive integer.")
            if not all(_finite_number(value) for value in (self.oversold, self.overbought)):
                raise BacktestInputError("RSI thresholds must be finite numbers.")
            if not 0 < self.oversold < self.overbought < 100:
                raise BacktestInputError(
                    "RSI thresholds must satisfy 0 < oversold < overbought < 100."
                )
        elif not _positive_int(self.period):
            raise BacktestInputError("Breakout period must be a positive integer.")

    @classmethod
    def sma(cls, fast_period: int, slow_period: int) -> StrategySpec:
        return cls(StrategyFamily.SMA, fast_period=fast_period, slow_period=slow_period)

    @classmethod
    def rsi(cls, period: int, *, oversold: float = 30.0, overbought: float = 70.0) -> StrategySpec:
        return cls(StrategyFamily.RSI, period=period, oversold=oversold, overbought=overbought)

    @classmethod
    def breakout(cls, period: int) -> StrategySpec:
        return cls(StrategyFamily.BREAKOUT, period=period)


@dataclass(frozen=True, slots=True)
class Trade:
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    quantity: float
    entry_fee: float
    exit_fee: float
    pnl: float
    return_pct: float
    entry_timestamp: datetime | None = None
    exit_timestamp: datetime | None = None
    holding_bars: int | None = None
    holding_elapsed_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class EquityPoint:
    date: date
    cash: float
    quantity: float
    close: float
    equity: float
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    initial_equity: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    trade_count: int
    winning_trades: int
    losing_trades: int
    exposure: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    strategy: StrategySpec | None
    equity_curve: tuple[EquityPoint, ...]
    trades: tuple[Trade, ...]
    metrics: BacktestMetrics


def _positive_int(value: int | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _rounded(value: float) -> float:
    return round(value, 12)


def validate_bars(bars: Iterable[DailyBar]) -> tuple[DailyBar, ...]:
    """Materialize and validate an ordered daily-bar input without mutating it."""

    if isinstance(bars, (str, bytes)):
        raise BacktestInputError("bars must be an iterable of DailyBar values.")
    try:
        materialized = tuple(bars)
    except TypeError as exc:
        raise BacktestInputError("bars must be an iterable of DailyBar values.") from exc
    if any(
        not isinstance(bar, DailyBar)  # type: ignore[reportUnnecessaryIsInstance]
        for bar in materialized
    ):
        raise BacktestInputError("bars must contain only DailyBar values.")
    if any(
        left.date >= right.date for left, right in zip(materialized, materialized[1:], strict=False)
    ):
        raise BacktestInputError("bars must be strictly ordered by date with no duplicates.")
    return materialized


def validate_market_bars(
    bars: Iterable[MarketBar], cadence: BacktestCadence
) -> tuple[MarketBar, ...]:
    """Validate ordered market bars against an explicit timestamp cadence."""

    if isinstance(bars, (str, bytes)):
        raise BacktestInputError("bars must be an iterable of MarketBar values.")
    if not isinstance(  # type: ignore[reportUnnecessaryIsInstance]
        cadence, BacktestCadence
    ):
        raise BacktestInputError("cadence must be a BacktestCadence.")
    try:
        materialized = tuple(bars)
    except TypeError as exc:
        raise BacktestInputError("bars must be an iterable of MarketBar values.") from exc
    if any(
        not isinstance(bar, MarketBar)  # type: ignore[reportUnnecessaryIsInstance]
        for bar in materialized
    ):
        raise BacktestInputError("bars must contain only MarketBar values.")
    if any(
        left.timestamp >= right.timestamp
        for left, right in zip(materialized, materialized[1:], strict=False)
    ):
        raise BacktestInputError("bars must be strictly ordered by timestamp with no duplicates.")
    for bar in materialized:
        timestamp = bar.timestamp
        aligned_to_hour = (
            timestamp.minute == 0 and timestamp.second == 0 and timestamp.microsecond == 0
        )
        aligned = aligned_to_hour and (
            cadence.interval is BacktestInterval.HOUR
            or (cadence.interval is BacktestInterval.FOUR_HOURS and timestamp.hour % 4 == 0)
            or (cadence.interval is BacktestInterval.DAILY and timestamp.hour == 0)
        )
        if not aligned:
            raise BacktestInputError(
                f"bar timestamps must align to the {cadence.interval} UTC boundary."
            )
    return materialized


BacktestBar = DailyBar | MarketBar


def _validated_bars_and_periods(
    bars: Iterable[BacktestBar], cadence: BacktestCadence | None
) -> tuple[tuple[BacktestBar, ...], int, bool]:
    if isinstance(bars, (str, bytes)):
        raise BacktestInputError("bars must be an iterable of DailyBar or MarketBar values.")
    try:
        materialized = tuple(bars)
    except TypeError as exc:
        raise BacktestInputError(
            "bars must be an iterable of DailyBar or MarketBar values."
        ) from exc
    if cadence is not None and not isinstance(  # type: ignore[reportUnnecessaryIsInstance]
        cadence, BacktestCadence
    ):
        raise BacktestInputError("cadence must be a BacktestCadence.")
    if not materialized:
        if cadence is None:
            return (), 252, False
        is_market = cadence != BacktestCadence(BacktestInterval.DAILY, 252)
        return (), cadence.periods_per_year, is_market
    daily = all(isinstance(bar, DailyBar) for bar in materialized)
    market = all(isinstance(bar, MarketBar) for bar in materialized)
    if not daily and not market:
        raise BacktestInputError("bars cannot mix DailyBar and MarketBar values.")
    if daily:
        if cadence is not None and cadence != BacktestCadence(BacktestInterval.DAILY, 252):
            raise BacktestInputError("DailyBar cadence, when supplied, must be 1D/252.")
        checked_daily = tuple(bar for bar in materialized if isinstance(bar, DailyBar))
        return validate_bars(checked_daily), 252, False
    if cadence is None:
        raise BacktestInputError("MarketBar inputs require an explicit cadence.")
    checked_market = tuple(bar for bar in materialized if isinstance(bar, MarketBar))
    return validate_market_bars(checked_market, cadence), cadence.periods_per_year, True


def _bar_date(bar: BacktestBar) -> date:
    return bar.date if isinstance(bar, DailyBar) else bar.timestamp.date()


def _bar_timestamp(bar: BacktestBar) -> datetime | None:
    return bar.timestamp if isinstance(bar, MarketBar) else None


def _elapsed_seconds(entry: BacktestBar, exit: BacktestBar) -> int | None:
    entry_timestamp = _bar_timestamp(entry)
    exit_timestamp = _bar_timestamp(exit)
    if entry_timestamp is None or exit_timestamp is None:
        return None
    return int((exit_timestamp - entry_timestamp).total_seconds())


def _sma(values: Sequence[float], period: int, index: int) -> float | None:
    if index + 1 < period:
        return None
    return mean(values[index + 1 - period : index + 1])


def _rsi(values: Sequence[float], period: int, index: int) -> float | None:
    if index < period:
        return None
    changes = [
        values[position] - values[position - 1] for position in range(index - period + 1, index + 1)
    ]
    gains = sum(max(change, 0.0) for change in changes) / period
    losses = sum(max(-change, 0.0) for change in changes) / period
    if losses == 0:
        return 100.0 if gains else 50.0
    return 100.0 - (100.0 / (1.0 + gains / losses))


def _desired_position(
    closes: Sequence[float], spec: StrategySpec, index: int, in_long: bool
) -> bool:
    if spec.family is StrategyFamily.SMA:
        fast = _sma(closes, spec.fast_period or 0, index)
        slow = _sma(closes, spec.slow_period or 0, index)
        if fast is None or slow is None:
            return in_long
        return fast > slow
    if spec.family is StrategyFamily.RSI:
        value = _rsi(closes, spec.period or 0, index)
        if value is None:
            return in_long
        if value <= spec.oversold:
            return True
        if value >= spec.overbought:
            return False
        return in_long
    period = spec.period or 0
    if index < period:
        return in_long
    prior = closes[index - period : index]
    if closes[index] > max(prior):
        return True
    if closes[index] < min(prior):
        return False
    return in_long


def _buy(cash: float, bar: BacktestBar, config: ExecutionConfig) -> tuple[float, float, float]:
    fill = bar.open * (1.0 + config.slippage_rate)
    quantity = cash / (fill * (1.0 + config.fee_rate))
    fee = quantity * fill * config.fee_rate
    return _rounded(quantity), _rounded(cash - quantity * fill - fee), _rounded(fee)


def _sell(quantity: float, bar: BacktestBar, config: ExecutionConfig) -> tuple[float, float, float]:
    fill = bar.open * (1.0 - config.slippage_rate)
    gross = quantity * fill
    fee = gross * config.fee_rate
    return _rounded(fill), _rounded(gross - fee), _rounded(fee)


def _metrics(
    curve: Sequence[EquityPoint],
    trades: Sequence[Trade],
    config: ExecutionConfig,
    bars_count: int,
    periods_per_year: int,
) -> BacktestMetrics:
    initial = config.initial_cash
    final = curve[-1].equity if curve else initial
    total_return = (final / initial) - 1.0
    years = (bars_count - 1) / float(periods_per_year)
    annualized = (final / initial) ** (1.0 / years) - 1.0 if years > 0 and final > 0 else 0.0
    drawdowns: list[float] = []
    peak = initial
    for point in curve:
        peak = max(peak, point.equity)
        drawdowns.append(point.equity / peak - 1.0)
    period_returns = [
        curve[i].equity / curve[i - 1].equity - 1.0
        for i in range(1, len(curve))
        if curve[i - 1].equity
    ]
    deviation = pstdev(period_returns) if len(period_returns) > 1 else 0.0
    sharpe = (
        mean(period_returns) / deviation * math.sqrt(float(periods_per_year)) if deviation else 0.0
    )
    winners = sum(trade.pnl > 0 for trade in trades)
    losers = sum(trade.pnl <= 0 for trade in trades)
    invested_bars = sum(point.quantity > 0 for point in curve)
    return BacktestMetrics(
        initial_equity=_rounded(initial),
        final_equity=_rounded(final),
        total_return=_rounded(total_return),
        annualized_return=_rounded(annualized),
        max_drawdown=_rounded(min(drawdowns, default=0.0)),
        sharpe_ratio=_rounded(sharpe),
        win_rate=_rounded(winners / len(trades)) if trades else 0.0,
        trade_count=len(trades),
        winning_trades=winners,
        losing_trades=losers,
        exposure=_rounded(invested_bars / bars_count) if bars_count else 0.0,
    )


def run_backtest(
    bars: Iterable[BacktestBar],
    strategy: StrategySpec,
    config: ExecutionConfig | None = None,
    *,
    measurement_start_index: int = 0,
    cadence: BacktestCadence | None = None,
) -> BacktestResult:
    """Run one long/cash strategy; signals at close ``i`` fill at open ``i+1``.

    Bars before ``measurement_start_index`` are indicator history only.  The
    first measured bar can create a signal at its close, so its earliest fill
    is the following measured bar's open.
    """

    checked_bars, periods_per_year, market_input = _validated_bars_and_periods(bars, cadence)
    if (
        not isinstance(measurement_start_index, int)  # type: ignore[reportUnnecessaryIsInstance]
        or isinstance(measurement_start_index, bool)
        or not 0 <= measurement_start_index <= len(checked_bars)
    ):
        raise BacktestInputError(
            "measurement_start_index must be an integer between 0 and the number of bars."
        )
    if not isinstance(  # type: ignore[reportUnnecessaryIsInstance]
        strategy, StrategySpec
    ):
        raise BacktestInputError("strategy must be a StrategySpec.")
    checked_config = config if config is not None else ExecutionConfig()
    if not isinstance(  # type: ignore[reportUnnecessaryIsInstance]
        checked_config, ExecutionConfig
    ):
        raise BacktestInputError("config must be an ExecutionConfig.")

    cash = float(checked_config.initial_cash)
    quantity = 0.0
    pending_long = False
    entry_date: date | None = None
    entry_price = 0.0
    entry_quantity = 0.0
    entry_fee = 0.0
    entry_index: int | None = None
    curve: list[EquityPoint] = []
    trades: list[Trade] = []
    closes = tuple(bar.close for bar in checked_bars)
    for index in range(measurement_start_index, len(checked_bars)):
        bar = checked_bars[index]
        if pending_long and quantity == 0.0:
            quantity, cash, entry_fee = _buy(cash, bar, checked_config)
            entry_date = _bar_date(bar)
            entry_price = bar.open * (1.0 + checked_config.slippage_rate)
            entry_quantity = quantity
            entry_index = index
        elif not pending_long and quantity > 0.0:
            exit_price, proceeds, exit_fee = _sell(quantity, bar, checked_config)
            cash = _rounded(cash + proceeds)
            invested = entry_quantity * entry_price + entry_fee
            trade_pnl = proceeds - invested
            trades.append(
                Trade(
                    entry_date=entry_date or _bar_date(bar),
                    entry_price=_rounded(entry_price),
                    exit_date=_bar_date(bar),
                    exit_price=exit_price,
                    quantity=entry_quantity,
                    entry_fee=entry_fee,
                    exit_fee=exit_fee,
                    pnl=_rounded(trade_pnl),
                    return_pct=_rounded(trade_pnl / invested) if invested else 0.0,
                    entry_timestamp=(
                        _bar_timestamp(checked_bars[entry_index])
                        if market_input and entry_index is not None
                        else None
                    ),
                    exit_timestamp=_bar_timestamp(bar) if market_input else None,
                    holding_bars=(
                        index - entry_index if market_input and entry_index is not None else None
                    ),
                    holding_elapsed_seconds=(
                        _elapsed_seconds(checked_bars[entry_index], bar)
                        if market_input and entry_index is not None
                        else None
                    ),
                )
            )
            quantity = 0.0
            entry_date = None
            entry_index = None
        equity = cash + quantity * bar.close
        curve.append(
            EquityPoint(
                _bar_date(bar),
                _rounded(cash),
                _rounded(quantity),
                bar.close,
                _rounded(equity),
                _bar_timestamp(bar) if market_input else None,
            )
        )
        pending_long = _desired_position(
            closes, strategy, index, pending_long if quantity else False
        )
    immutable_curve = tuple(curve)
    immutable_trades = tuple(trades)
    return BacktestResult(
        strategy,
        immutable_curve,
        immutable_trades,
        _metrics(
            immutable_curve,
            immutable_trades,
            checked_config,
            len(immutable_curve),
            periods_per_year,
        ),
    )


def backtest_buy_and_hold(
    bars: Iterable[BacktestBar],
    config: ExecutionConfig | None = None,
    *,
    cadence: BacktestCadence | None = None,
) -> BacktestResult:
    """Buy on the first bar's open and hold through the final close.

    The benchmark's final point is marked to market at the final close; no
    synthetic close transaction is included in its trade log.
    """

    checked_bars, periods_per_year, market_input = _validated_bars_and_periods(bars, cadence)
    checked_config = config if config is not None else ExecutionConfig()
    if not isinstance(  # type: ignore[reportUnnecessaryIsInstance]
        checked_config, ExecutionConfig
    ):
        raise BacktestInputError("config must be an ExecutionConfig.")
    if not checked_bars:
        return BacktestResult(None, (), (), _metrics((), (), checked_config, 0, periods_per_year))
    quantity, cash, entry_fee = _buy(checked_config.initial_cash, checked_bars[0], checked_config)
    curve = tuple(
        EquityPoint(
            _bar_date(bar),
            _rounded(cash),
            quantity,
            bar.close,
            _rounded(cash + quantity * bar.close),
            _bar_timestamp(bar) if market_input else None,
        )
        for bar in checked_bars
    )
    final_bar = checked_bars[-1]
    entry_price = _rounded(checked_bars[0].open * (1.0 + checked_config.slippage_rate))
    final_price = final_bar.close
    trade = Trade(
        entry_date=_bar_date(checked_bars[0]),
        entry_price=entry_price,
        exit_date=_bar_date(final_bar),
        exit_price=final_price,
        quantity=quantity,
        entry_fee=entry_fee,
        exit_fee=0.0,
        pnl=_rounded(quantity * (final_price - entry_price) - entry_fee),
        return_pct=_rounded(
            (quantity * final_price - quantity * entry_price - entry_fee)
            / (quantity * entry_price + entry_fee)
        ),
        entry_timestamp=_bar_timestamp(checked_bars[0]) if market_input else None,
        exit_timestamp=_bar_timestamp(final_bar) if market_input else None,
        holding_bars=len(checked_bars) - 1 if market_input else None,
        holding_elapsed_seconds=(
            _elapsed_seconds(checked_bars[0], final_bar) if market_input else None
        ),
    )
    trades = (trade,)
    return BacktestResult(
        None,
        curve,
        trades,
        _metrics(curve, trades, checked_config, len(checked_bars), periods_per_year),
    )


buy_and_hold = backtest_buy_and_hold


__all__ = [
    "BacktestBar",
    "BacktestCadence",
    "BacktestConfig",
    "BacktestInputError",
    "BacktestInterval",
    "BacktestMetrics",
    "BacktestResult",
    "DailyBar",
    "EquityPoint",
    "ExecutionConfig",
    "MarketBar",
    "StrategyFamily",
    "StrategySpec",
    "Trade",
    "backtest_buy_and_hold",
    "buy_and_hold",
    "run_backtest",
    "validate_bars",
    "validate_market_bars",
]
