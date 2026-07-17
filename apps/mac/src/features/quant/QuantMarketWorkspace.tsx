import { useMemo, useState } from 'react';
import { Badge } from '@glint/ui';
import type { MarketBar, QuantWorkspaceSnapshot } from '../../quant-domain';
import { quantAuthenticityLabel } from '../../quant-domain';

export interface QuantMarketInspectTarget {
  kind: 'market_event';
  title: string;
  bar: MarketBar;
}

function linePath(values: number[], width: number, height: number, min: number, max: number): string {
  return values.map((value, index) => {
    const x = 30 + (index / Math.max(1, values.length - 1)) * (width - 60);
    const y = 16 + ((max - value) / Math.max(1, max - min)) * (height - 42);
    return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

export function QuantMarketWorkspace({ snapshot, onInspect }: { snapshot: QuantWorkspaceSnapshot; onInspect: (target: QuantMarketInspectTarget) => void }) {
  const [chartType, setChartType] = useState<'candlestick' | 'line'>('candlestick');
  const [showSma50, setShowSma50] = useState(true);
  const [showSma200, setShowSma200] = useState(true);
  const width = 820;
  const height = 250;
  const chart = useMemo(() => {
    const lows = snapshot.bars.map((bar) => bar.low);
    const highs = snapshot.bars.map((bar) => bar.high);
    const min = Math.min(...lows) - 8;
    const max = Math.max(...highs) + 8;
    return { min, max, closePath: linePath(snapshot.bars.map((bar) => bar.close), width, height, min, max), sma50Path: linePath(snapshot.bars.map((bar) => bar.close * .975), width, height, min, max), sma200Path: linePath(snapshot.bars.map((bar) => bar.close * .92), width, height, min, max) };
  }, [snapshot.bars]);

  return <section className="quant-market" aria-labelledby="quant-market-title">
    <header className="quant-market-toolbar"><div><p className="quant-eyebrow">Market Workspace</p><h3 id="quant-market-title">{snapshot.scope.symbol} · {snapshot.scope.interval}</h3></div><div className="quant-chart-controls" role="group" aria-label="Market chart controls"><button aria-pressed={chartType === 'candlestick'} onClick={() => setChartType('candlestick')}>Candlestick</button><button aria-pressed={chartType === 'line'} onClick={() => setChartType('line')}>Line</button><button aria-pressed={showSma50} onClick={() => setShowSma50((value) => !value)}>SMA 50</button><button aria-pressed={showSma200} onClick={() => setShowSma200((value) => !value)}>SMA 200</button></div><Badge tone="warning">{quantAuthenticityLabel(snapshot.authenticity)}</Badge></header>
    <figure className="quant-chart">
      <svg viewBox={`0 0 ${width} ${height + 54}`} role="img" aria-labelledby="quant-chart-title quant-chart-desc" preserveAspectRatio="none">
        <title id="quant-chart-title">Synthetic SPY daily market chart</title><desc id="quant-chart-desc">A bounded presentation sample from the synthetic fixture. Close values rise from {snapshot.bars[0]?.close} to {snapshot.bars.at(-1)?.close}, with entry, exit, policy, and macro markers.</desc>
        {[0, 1, 2, 3, 4].map((line) => <line key={line} x1="30" x2={width - 30} y1={16 + line * 46} y2={16 + line * 46} className="quant-grid-line" />)}
        {chartType === 'line' ? <path d={chart.closePath} className="quant-price-line" /> : snapshot.bars.map((bar, index) => {
          const x = 30 + (index / Math.max(1, snapshot.bars.length - 1)) * (width - 60);
          const y = (value: number) => 16 + ((chart.max - value) / (chart.max - chart.min)) * (height - 42);
          const rising = bar.close >= bar.open;
          return <g key={bar.date} className={rising ? 'quant-candle-up' : 'quant-candle-down'}><line x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} /><rect x={x - 5} y={Math.min(y(bar.open), y(bar.close))} width="10" height={Math.max(2, Math.abs(y(bar.open) - y(bar.close)))} /></g>;
        })}
        {showSma50 && <path d={chart.sma50Path} className="quant-sma-50" />}{showSma200 && <path d={chart.sma200Path} className="quant-sma-200" />}
        {snapshot.bars.map((bar, index) => {
          if (!bar.marker) return null;
          const x = 30 + (index / Math.max(1, snapshot.bars.length - 1)) * (width - 60);
          return <g key={`${bar.date}-${bar.marker}`}><line x1={x} x2={x} y1="22" y2={height - 18} className="quant-event-line" /><text x={x + 3} y="31" className="quant-event-label">{bar.marker}</text></g>;
        })}
        {snapshot.bars.map((bar, index) => { const x = 30 + (index / Math.max(1, snapshot.bars.length - 1)) * (width - 60); const maxVolume = Math.max(...snapshot.bars.map((item) => item.volume)); return <rect key={`volume-${bar.date}`} x={x - 4} y={height + 42 - (bar.volume / maxVolume) * 36} width="8" height={(bar.volume / maxVolume) * 36} className="quant-volume" />; })}
      </svg>
      <figcaption><span>{snapshot.scope.dateRange.start} – {snapshot.scope.dateRange.end}</span><span className="legend-price">Price</span><span className="legend-sma50">SMA 50 fixture series</span><span className="legend-sma200">SMA 200 fixture series</span><span>Volume</span></figcaption>
    </figure>
    <div className="quant-market-events" aria-label="Chart events">{snapshot.bars.filter((bar) => bar.marker).map((bar) => <button key={`${bar.date}-${bar.marker}`} onClick={() => onInspect({ kind: 'market_event', title: `${bar.marker} fixture marker`, bar })}><strong>{bar.marker}</strong><span>{bar.date}</span></button>)}</div>
    <p className="quant-chart-note">Text summary: this is a sampled chart projection of the named fixture dataset, not live market data or a backtest calculation.</p>
  </section>;
}
