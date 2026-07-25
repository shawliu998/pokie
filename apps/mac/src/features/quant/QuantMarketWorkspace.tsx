import { useMemo, useState } from 'react';
import type { MarketBar, QuantBarInterval, QuantWorkspaceSnapshot } from '../../quant-domain';
import { rollingSma } from './quant-market-math';

export interface QuantMarketInspectTarget {
  kind: 'market_event';
  title: string;
  bar: MarketBar;
}

export interface QuantMarketTradeMarker {
  id: string;
  date: string;
  kind: 'entry' | 'exit';
}

function chartPath(values: readonly (number | null)[], width: number, height: number, min: number, max: number): string {
  let drawing = false;
  return values.map((value, index) => {
    if (value == null) { drawing = false; return ''; }
    const x = 30 + (index / Math.max(1, values.length - 1)) * (width - 60);
    const y = 16 + ((max - value) / Math.max(1, max - min)) * (height - 42);
    const command = drawing ? 'L' : 'M';
    drawing = true;
    return `${command}${x.toFixed(1)},${y.toFixed(1)}`;
  }).filter(Boolean).join(' ');
}

export function QuantMarketChart({ bars, symbol, interval, dateRange, title = 'Market preview', description, onInspect, tradeMarkers, highlightedTradeDates = [], enableIndicators = true }: {
  bars: MarketBar[];
  symbol: string;
  interval: QuantBarInterval;
  dateRange: { start: string; end: string };
  title?: string;
  description?: string;
  onInspect?: (target: QuantMarketInspectTarget) => void;
  tradeMarkers?: QuantMarketTradeMarker[];
  highlightedTradeDates?: string[];
  enableIndicators?: boolean;
}) {
  const [chartType, setChartType] = useState<'candlestick' | 'line'>('candlestick');
  const [showSma20, setShowSma20] = useState(true);
  const [showSma50, setShowSma50] = useState(true);
  const width = 820;
  const height = 250;
  const chart = useMemo(() => {
    if (bars.length === 0) return null;
    const closes = bars.map((bar) => bar.close);
    const sma20 = rollingSma(closes, 20);
    const sma50 = rollingSma(closes, 50);
    const min = Math.min(...bars.map((bar) => bar.low));
    const max = Math.max(...bars.map((bar) => bar.high));
    return {
      min,
      max,
      sma20,
      sma50,
      closePath: chartPath(closes, width, height, min, max),
      sma20Path: chartPath(sma20, width, height, min, max),
      sma50Path: chartPath(sma50, width, height, min, max),
      maxVolume: Math.max(...bars.map((bar) => bar.volume)),
    };
  }, [bars]);

  if (!chart) return <section className="quant-market quant-market-empty"><header><h3>{symbol} · {interval}</h3></header><strong>No price bars available</strong><p>This dataset preview did not return OHLCV observations.</p></section>;
  const hasSma20 = enableIndicators && chart.sma20.some((value) => value != null);
  const hasSma50 = enableIndicators && chart.sma50.some((value) => value != null);
  const hasVolume = chart.maxVolume > 0;
  const candleWidth = Math.max(1, Math.min(8, ((width - 60) / bars.length) * .62));
  const highlightedDates = new Set(highlightedTradeDates);
  const barIndexByDate = new Map(bars.map((bar, index) => [bar.date, index]));
  const visibleTradeMarkers = (tradeMarkers ?? []).flatMap((marker) => {
    const index = barIndexByDate.get(marker.date);
    return index === undefined ? [] : [{ ...marker, index }];
  });

  return <section className="quant-market" aria-labelledby="quant-market-title">
    <header className="quant-market-toolbar"><div><span>{title}</span><h3 id="quant-market-title">{symbol} · {interval}</h3></div><div className="quant-chart-controls" role="group" aria-label="Market chart controls"><button aria-pressed={chartType === 'candlestick'} onClick={() => setChartType('candlestick')}>Candlestick</button><button aria-pressed={chartType === 'line'} onClick={() => setChartType('line')}>Line</button>{hasSma20 && <button aria-pressed={showSma20} onClick={() => setShowSma20((value) => !value)}>SMA 20</button>}{hasSma50 && <button aria-pressed={showSma50} onClick={() => setShowSma50((value) => !value)}>SMA 50</button>}</div></header>
    <figure className="quant-chart">
      <svg viewBox={`0 0 ${width} ${height + (hasVolume ? 54 : 12)}`} role="img" aria-labelledby="quant-chart-title quant-chart-desc" preserveAspectRatio="none">
        <title id="quant-chart-title">{`${symbol} ${interval} price and volume chart`}</title><desc id="quant-chart-desc">{description ?? `Stored ${interval} OHLCV from ${bars[0]!.date} to ${bars.at(-1)!.date}.`}</desc>
        {[0, 1, 2, 3, 4].map((line) => <line key={line} x1="30" x2={width - 30} y1={16 + line * 46} y2={16 + line * 46} className="quant-grid-line" />)}
        {chartType === 'line' ? <path d={chart.closePath} className="quant-price-line" /> : bars.map((bar, index) => {
          const x = 30 + (index / Math.max(1, bars.length - 1)) * (width - 60);
          const y = (value: number) => 16 + ((chart.max - value) / Math.max(1, chart.max - chart.min)) * (height - 42);
          const rising = bar.close >= bar.open;
          return <g key={bar.date} className={rising ? 'quant-candle-up' : 'quant-candle-down'}><line x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} /><rect x={x - candleWidth / 2} y={Math.min(y(bar.open), y(bar.close))} width={candleWidth} height={Math.max(1, Math.abs(y(bar.open) - y(bar.close)))} /></g>;
        })}
        {hasSma20 && showSma20 && <path d={chart.sma20Path} className="quant-sma-20" />}{hasSma50 && showSma50 && <path d={chart.sma50Path} className="quant-sma-50" />}
        {(tradeMarkers !== undefined ? visibleTradeMarkers : bars.flatMap((bar, index) => bar.marker ? [{ id: `${bar.date}-${bar.marker}`, date: bar.date, kind: bar.marker, index }] : [])).map((marker) => {
          const x = 30 + (marker.index / Math.max(1, bars.length - 1)) * (width - 60);
          const highlighted = highlightedDates.has(marker.date);
          return <g key={marker.id} className={`quant-trade-marker is-${marker.kind}${highlighted ? ' is-highlighted' : ''}`}><line x1={x} x2={x} y1="22" y2={height - 18} className="quant-event-line" /><text x={x + 3} y={marker.kind === 'entry' ? 31 : 45} className="quant-event-label">{marker.kind}</text></g>;
        })}
        {hasVolume && bars.map((bar, index) => { const x = 30 + (index / Math.max(1, bars.length - 1)) * (width - 60); const volumeHeight = (bar.volume / chart.maxVolume) * 36; return <rect key={`volume-${bar.date}`} x={x - candleWidth / 2} y={height + 42 - volumeHeight} width={candleWidth} height={volumeHeight} className="quant-volume" />; })}
      </svg>
      <figcaption><span>{dateRange.start} – {dateRange.end}</span><span className="legend-price">Price</span>{hasSma20 && showSma20 && <span className="legend-sma20">SMA 20</span>}{hasSma50 && showSma50 && <span className="legend-sma50">SMA 50</span>}{hasVolume && <span>Volume</span>}</figcaption>
    </figure>
    {((enableIndicators && (!hasSma20 || !hasSma50)) || !hasVolume) && <p className="quant-chart-availability">{enableIndicators && !hasSma20 ? `SMA 20 requires 20 bars; ${bars.length} available. ` : ''}{enableIndicators && !hasSma50 ? `SMA 50 requires 50 bars; ${bars.length} available. ` : ''}{!hasVolume ? 'Volume is unavailable for this preview.' : ''}</p>}
    {onInspect && <div className="quant-market-events" aria-label="Chart events">{bars.filter((bar) => bar.marker).map((bar) => <button key={`${bar.date}-${bar.marker}`} onClick={() => onInspect({ kind: 'market_event', title: `${bar.marker} dataset marker`, bar })}><strong>{bar.marker}</strong><span>{bar.date}</span></button>)}</div>}
    <p className="quant-chart-note">{enableIndicators ? 'Stored contiguous observations; indicators are rolling calculations over the displayed bars.' : 'Bounded stored observations with retained strategy trade timestamps; no performance metric is recalculated here.'}</p>
  </section>;
}

export function QuantMarketWorkspace({ snapshot, onInspect }: { snapshot: QuantWorkspaceSnapshot; onInspect: (target: QuantMarketInspectTarget) => void }) {
  return <QuantMarketChart bars={snapshot.bars} symbol={snapshot.scope.symbol} interval={snapshot.scope.interval} dateRange={snapshot.scope.dateRange} title="Market workspace" description={`A bounded chart projection of the pinned ${snapshot.authenticity === 'synthetic_fixture' ? 'synthetic fixture' : 'workspace-imported dataset'}.`} onInspect={onInspect} enableIndicators={false} />;
}
