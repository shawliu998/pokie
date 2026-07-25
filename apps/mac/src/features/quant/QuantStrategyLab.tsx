import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import type { QuantCandidate, QuantLiveCandidate, QuantWorkspaceSnapshot, StrategyPerformancePoint, TradeRecord } from '../../quant-domain';
import { chartDomain, keyboardPointIndex, matchPointByDate, nearestPointIndex, seriesPath, xForDate, yForValue, type ChartBounds } from './strategy-performance-chart-math';
import { canContinueResearch, formatTradeHolding, projectDecisionLedger, type QuantEvidenceFocusIntent } from './quant-presentation';
import { QuantMarketChart, type QuantMarketTradeMarker } from './QuantMarketWorkspace';

type SortKey = 'annualizedReturn' | 'sharpe' | 'maxDrawdown' | 'trades';
type AnalysisView = 'equity' | 'drawdown' | 'market' | 'periods' | 'trades';
type AnalysisEvidenceAnchor =
  | { runId: string; candidateId: string; target: 'drawdown'; date: string }
  | { runId: string; candidateId: string; target: 'trade'; tradeId: string };

const analysisViews: AnalysisView[] = ['equity', 'drawdown', 'market', 'periods', 'trades'];

function candidateLabel(value: string) {
  return value.replace(/^Candidate [A-Z] · /, '');
}

function percent(value: number | undefined, digits = 1) {
  if (value === undefined || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

function yearlyReturns(points: StrategyPerformancePoint[]) {
  const years = new Map<string, { first: number; last: number }>();
  for (const point of points) {
    const year = point.date.slice(0, 4);
    const current = years.get(year);
    if (current) current.last = point.equity;
    else years.set(year, { first: point.equity, last: point.equity });
  }
  return [...years].map(([year, values]) => ({ year, returnPct: values.first ? (values.last / values.first - 1) * 100 : 0 }));
}

function chartRangeLabel(value: string, interval: QuantWorkspaceSnapshot['scope']['interval']) {
  if (interval === '1D') return value;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return `${new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }).format(parsed)} UTC`;
}

function chartInspectionDateLabel(value: string, interval: QuantWorkspaceSnapshot['scope']['interval']) {
  const parsed = new Date(value.includes('T') ? value : `${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  const date = new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
    ...(interval === '1D' ? {} : { hour: '2-digit', minute: '2-digit', hour12: false }),
  }).format(parsed);
  return `${date} UTC`;
}

export function StrategyPerformanceChart({ snapshot, selectedCandidateId, view, focusedDate }: { snapshot: QuantWorkspaceSnapshot; selectedCandidateId: string; view: 'equity' | 'drawdown'; focusedDate?: string }) {
  const candidate = snapshot.performanceSeries.find((series) => series.id === selectedCandidateId);
  const benchmark = snapshot.performanceSeries.find((series) => series.kind === 'benchmark');
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [pinnedIndex, setPinnedIndex] = useState<number | null>(null);
  const previousFocusedDate = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (candidate && focusedDate) {
      const index = candidate.points.findIndex((point) => point.date === focusedDate);
      if (index >= 0) {
        setPinnedIndex(index);
        setHoveredIndex(null);
      }
    } else if (previousFocusedDate.current) {
      setPinnedIndex(null);
      setHoveredIndex(null);
    }
    previousFocusedDate.current = focusedDate;
  }, [candidate, focusedDate]);
  if (!candidate?.points.length) return <div className="pq-strategy-empty"><strong>Performance series pending</strong><p>The chart will appear after this candidate completes a backtest.</p></div>;
  const key = view;
  const width = 760;
  const height = 250;
  const bounds: ChartBounds = { width, height, left: 54, right: 10, top: 12, bottom: 12 };
  const values = [...candidate.points, ...(benchmark?.points ?? [])].map((point) => point[key]);
  const domain = chartDomain(values, view);
  const startDate = candidate.points[0]!.date;
  const endDate = candidate.points.at(-1)!.date;
  const candidatePath = seriesPath(candidate.points, key, domain, bounds, startDate, endDate);
  const benchmarkPath = benchmark ? seriesPath(benchmark.points, key, domain, bounds, startDate, endDate) : '';
  const drawdownAreaPath = view === 'drawdown' && candidatePath
    ? `${candidatePath} L${xForDate(endDate, startDate, endDate, bounds).toFixed(1)} ${yForValue(0, domain, bounds).toFixed(1)} L${xForDate(startDate, startDate, endDate, bounds).toFixed(1)} ${yForValue(0, domain, bounds).toFixed(1)} Z`
    : '';
  const selectedIndex = Math.min(candidate.points.length - 1, Math.max(0, hoveredIndex ?? pinnedIndex ?? candidate.points.length - 1));
  const selectedPoint = candidate.points[selectedIndex]!;
  const benchmarkPoint = benchmark ? matchPointByDate(benchmark.points, selectedPoint.date) : null;
  const candidateValue = view === 'equity' ? selectedPoint.equity - 100 : selectedPoint.drawdown;
  const benchmarkValue = benchmarkPoint ? view === 'equity' ? benchmarkPoint.equity - 100 : benchmarkPoint.drawdown : undefined;
  const difference = benchmarkValue === undefined ? undefined : candidateValue - benchmarkValue;
  const selectedX = xForDate(selectedPoint.date, startDate, endDate, bounds);
  const pointerIndex = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const chartX = rect.width ? (event.clientX - rect.left) / rect.width * width : bounds.left;
    return nearestPointIndex(candidate.points, chartX, bounds);
  };
  const onChartKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = keyboardPointIndex(selectedIndex, event.key as 'ArrowLeft' | 'ArrowRight' | 'Home' | 'End', candidate.points.length);
    if (next >= 0) setPinnedIndex(next);
    setHoveredIndex(null);
  };
  const axisLabel = (value: number) => percent(view === 'equity' ? value - 100 : value, Math.abs(domain.max - domain.min) < 10 ? 1 : 0);
  const chartLabel = benchmark?.points.length ? `${candidate.label} ${view} compared with benchmark` : `${candidate.label} ${view} performance`;
  return <figure className="pq-strategy-chart" aria-label={chartLabel}>
    <header className="pq-strategy-inspection" aria-label="Performance inspection">
      <dl><div><dt>Date</dt><dd><time dateTime={selectedPoint.date}>{chartInspectionDateLabel(selectedPoint.date, snapshot.scope.interval)}</time></dd></div><div><dt><span className="pq-series-key is-candidate" />Strategy</dt><dd><strong>{percent(candidateValue)}</strong></dd></div>{benchmarkPoint && <div><dt><span className="pq-series-key is-benchmark" />Benchmark</dt><dd>{percent(benchmarkValue)}</dd></div>}{benchmarkPoint && <div><dt>Difference</dt><dd>{percent(difference)}</dd></div>}</dl>
      {benchmarkPoint && benchmarkPoint.date !== selectedPoint.date && <span>Benchmark matched to {chartInspectionDateLabel(benchmarkPoint.date, snapshot.scope.interval)}</span>}
    </header>
    <div className="pq-strategy-plot" role="group" tabIndex={0} aria-label={`Inspect ${candidate.label} ${view} performance. Use Left and Right arrows to move by date; Home and End jump to the range bounds.`} onPointerMove={(event) => setHoveredIndex(pointerIndex(event))} onPointerLeave={() => setHoveredIndex(null)} onPointerDown={(event) => { const next = pointerIndex(event); if (next >= 0) setPinnedIndex(next); }} onKeyDown={onChartKeyDown}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={chartLabel}>
        {domain.ticks.map((tick) => { const y = yForValue(tick, domain, bounds); return <g key={tick}><line x1={bounds.left} x2={width - bounds.right} y1={y} y2={y} className="pq-strategy-gridline" /><text x={bounds.left - 8} y={y + 3} textAnchor="end" className="pq-strategy-axis-label">{axisLabel(tick)}</text></g>; })}
        {drawdownAreaPath && <path d={drawdownAreaPath} className="pq-strategy-area is-candidate is-drawdown" />}
        {benchmarkPath && <path d={benchmarkPath} className="pq-strategy-line is-benchmark" />}
        {candidatePath && <path d={candidatePath} className="pq-strategy-line is-candidate" />}
        <line x1={selectedX} x2={selectedX} y1={bounds.top} y2={height - bounds.bottom} className="pq-strategy-crosshair" />
        {benchmarkPoint && <circle cx={xForDate(benchmarkPoint.date, startDate, endDate, bounds)} cy={yForValue(benchmarkPoint[key], domain, bounds)} r="2.5" className="pq-strategy-marker is-benchmark" />}
        <circle cx={selectedX} cy={yForValue(selectedPoint[key], domain, bounds)} r="3.5" className="pq-strategy-marker is-candidate" />
      </svg>
    </div>
    <figcaption><time dateTime={candidate.points[0]!.date}>{chartRangeLabel(candidate.points[0]!.date, snapshot.scope.interval)}</time><time dateTime={candidate.points.at(-1)!.date}>{chartRangeLabel(candidate.points.at(-1)!.date, snapshot.scope.interval)}</time></figcaption>
  </figure>;
}

export function CandidateComparison({ snapshot, selectedCandidateId, onSelectCandidate, variant = 'full' }: { snapshot: QuantWorkspaceSnapshot; selectedCandidateId: string; onSelectCandidate: (id: string) => void; variant?: 'full' | 'snapshot' }) {
  const [sortKey, setSortKey] = useState<SortKey>('sharpe');
  const [descending, setDescending] = useState(true);
  const candidates = useMemo(() => [...snapshot.candidates].sort((left, right) => {
    const result = left.metrics[sortKey] - right.metrics[sortKey];
    return descending ? -result : result;
  }), [descending, snapshot.candidates, sortKey]);
  const sort = (next: SortKey) => {
    if (next === sortKey) setDescending((value) => !value);
    else { setSortKey(next); setDescending(true); }
  };
  const heading = (label: string, key: SortKey) => <button className="pq-sort-button" aria-label={`Sort by ${label}`} onClick={() => sort(key)}>{label}{sortKey === key ? <span aria-hidden="true"> {descending ? '↓' : '↑'}</span> : null}</button>;
  const headingId = variant === 'snapshot' ? 'pq-candidate-snapshot-heading' : 'pq-candidate-comparison-heading';
  const ledger = variant === 'full' ? projectDecisionLedger(snapshot) : null;
  const stopReason = {
    no_novel_candidate: 'No novel Candidate C satisfied the approved plan.',
    insufficient_action_budget: 'The remaining action budget could not support another novel Candidate C.',
  } as const;
  const selectionBasis = {
    approved_objective_rank: 'Approved comparison objective',
    robustness_override: 'Server-validated robustness override',
  } as const;
  return <section className={`pq-candidate-comparison is-${variant}`} aria-labelledby={headingId}>
    <header><div><h2 id={headingId}>{variant === 'snapshot' ? 'Candidate snapshot' : 'Candidate comparison'}</h2><p>{variant === 'snapshot' ? 'Select a strategy to update every result view.' : 'Training results relative to the pinned buy-and-hold benchmark.'}</p></div><span>{snapshot.candidates.length} strategies</span></header>
    <div className="pq-table-scroll"><table className="quant-research-table"><caption className="quant-visually-hidden">Candidate strategy comparison</caption><thead><tr><th>Strategy</th><th className="is-numeric">{heading('Annual return', 'annualizedReturn')}</th><th className="is-numeric">{heading('Sharpe', 'sharpe')}</th><th className="is-numeric">{heading('Drawdown', 'maxDrawdown')}</th><th className="is-numeric">{heading('Trades', 'trades')}</th><th className="is-numeric">Vs benchmark</th><th className="is-action">Result</th></tr></thead><tbody>
      {candidates.map((candidate) => <tr key={candidate.id} className={candidate.id === selectedCandidateId ? 'is-selected' : undefined}><th scope="row"><button className="quant-table-link" aria-pressed={candidate.id === selectedCandidateId} onClick={() => onSelectCandidate(candidate.id)}>{candidateLabel(candidate.name)}</button></th><td className="is-numeric">{percent(candidate.metrics.annualizedReturn)}</td><td className="is-numeric">{candidate.metrics.sharpe.toFixed(2)}</td><td className="is-numeric">{percent(candidate.metrics.maxDrawdown)}</td><td className="is-numeric">{candidate.metrics.trades}</td><td className="is-numeric">{percent(snapshot.benchmark ? candidate.metrics.annualizedReturn - snapshot.benchmark.annualizedReturn : undefined)}</td><td className="is-action">{candidate.verdict === 'promising' ? 'Leading' : candidate.verdict === 'rejected' ? 'Rejected' : 'Inconclusive'}</td></tr>)}
      {snapshot.benchmark && <tr className="is-benchmark"><th scope="row">Buy and hold</th><td className="is-numeric">{percent(snapshot.benchmark.annualizedReturn)}</td><td className="is-numeric">{snapshot.benchmark.sharpe.toFixed(2)}</td><td className="is-numeric">{percent(snapshot.benchmark.maxDrawdown)}</td><td className="is-numeric">{snapshot.benchmark.trades}</td><td className="is-numeric">—</td><td className="is-action">Benchmark</td></tr>}
    </tbody></table></div>
    {ledger && <section className="pq-candidate-evolution" aria-labelledby="pq-candidate-evolution-heading"><header><div><span>Decision ledger</span><h3 id="pq-candidate-evolution-heading">Training decision</h3></div><span>{ledger.path === 'adapted_candidate' ? 'A/B → Observation → Candidate C → Final choice' : 'A/B → Observation → Stop → Final choice'}</span></header><dl>
      <div><dt>Initial candidates A/B</dt><dd>{ledger.initialCandidates.map((candidate) => `${candidateLabel(candidate.name)} — ${candidate.hypothesis}`).join(' · ')}</dd></div>
      <div><dt>{ledger.outcome.kind === 'candidate' ? 'Training observation → Candidate C' : 'Training observation → Stop'}</dt><dd>{candidateLabel(ledger.observation.referenceCandidateName)} was the train-only improvement reference. {ledger.outcome.kind === 'candidate' ? `${candidateLabel(ledger.outcome.candidateName)} — ${ledger.outcome.hypothesis} ${ledger.outcome.rationale}` : `Stopped before Candidate C. ${stopReason[ledger.outcome.reason]}`}</dd></div>
      {ledger.outcome.kind === 'candidate' && ledger.outcome.replanRepair && <div className="pq-replan-repair"><dt>Agent request correction</dt><dd>The first Candidate C request used “Refine parameters” and was rejected. The Agent kept the candidate inputs, changed only the action to “Switch approved family”, and created Candidate C.</dd></div>}
      <div><dt>Final choice</dt><dd>{candidateLabel(ledger.finalChoice.candidateName)} · {selectionBasis[ledger.finalChoice.basis]}. {ledger.finalChoice.selectionReason}</dd></div>
    </dl></section>}
  </section>;
}

function liveStatus(candidate: QuantLiveCandidate): string {
  return {
    completed: 'Completed',
    running: 'Running',
    queued: 'Queued',
    repairing: 'Repairing',
    revised: 'Superseded',
    failed: 'Stopped',
  }[candidate.state];
}

function liveCandidateRole(snapshot: QuantWorkspaceSnapshot, candidate: QuantLiveCandidate): string {
  if (candidate.ordinal === 1) return 'Initial hypothesis A';
  if (candidate.ordinal === 2) return 'Initial hypothesis B';
  const retained = snapshot.candidates.find((item) => item.id === candidate.id);
  if (candidate.ordinal === 3 && retained?.evolution?.origin === 'training_feedback') return 'Adaptation C';
  return candidate.ordinal === 3 ? 'Candidate C' : `Candidate ${candidate.ordinal}`;
}

function LiveMetrics({ candidate }: { candidate: QuantLiveCandidate | null }) {
  if (!candidate?.metrics) return <div className="pq-live-pending"><strong>No completed result yet</strong><p>Metrics appear after a candidate finishes its training backtest.</p></div>;
  return <dl className="pq-live-metrics"><div><dt>Return</dt><dd>{percent(candidate.metrics.annualizedReturn)}</dd></div><div><dt>Sharpe</dt><dd>{candidate.metrics.sharpe.toFixed(2)}</dd></div><div><dt>Drawdown</dt><dd>{percent(candidate.metrics.maxDrawdown)}</dd></div><div><dt>Trades</dt><dd>{candidate.metrics.trades}</dd></div></dl>;
}

function LiveResearchWorkbench({ snapshot, showDecisionSummary }: { snapshot: QuantWorkspaceSnapshot; showDecisionSummary: boolean }) {
  const live = snapshot.liveResearch;
  const current = live?.currentExperiment ?? null;
  const candidates = live?.candidates ?? [];
  const pendingSlots = Math.max(0, snapshot.limits.maxExperiments - candidates.length);
  return <section className="pq-live-research" aria-labelledby="pq-live-research-heading">
    <header className="pq-live-header"><div><h2 id="pq-live-research-heading">{live?.phaseLabel ?? 'Research queued'}</h2><p>{snapshot.project.goal}</p></div>{live && <span>Iteration {live.iteration} of {snapshot.run.maxAgentIterations}</span>}</header>
    {showDecisionSummary && live && <div className="pq-live-focus">
      <section aria-labelledby="pq-current-experiment-heading"><header><h3 id="pq-current-experiment-heading">Current experiment</h3>{current && <span>Experiment {current.ordinal} of {snapshot.limits.maxExperiments}</span>}</header>{current ? <><strong>{candidateLabel(current.name)}</strong><p>{current.hypothesis}</p><dl><div><dt>Parameters</dt><dd>{current.parameters || 'Parameters are being prepared'}</dd></div><div><dt>Stage</dt><dd>{liveStatus(current)}</dd></div>{current.repairCount > 0 && <div><dt>Revision</dt><dd>{current.repairCount}</dd></div>}</dl></> : <div className="pq-live-pending"><strong>{live.phase === 'loading_data' ? 'Verifying the selected dataset' : live.phase === 'validating' ? 'Candidate execution complete' : 'No candidate is running'}</strong><p>{live.phase === 'loading_data' ? 'Candidate generation begins after coverage and quality checks finish.' : live.phase === 'validating' ? 'Completed candidates are moving through robustness and holdout checks.' : 'The retained results are being assembled into the research report.'}</p></div>}</section>
      <section aria-labelledby="pq-latest-result-heading"><header><h3 id="pq-latest-result-heading">Latest result</h3>{live.latestResult && <span>Experiment {live.latestResult.ordinal}</span>}</header>{live.latestResult && <><strong>{candidateLabel(live.latestResult.name)}</strong><p>{live.latestResult.hypothesis}</p></>}<LiveMetrics candidate={live.latestResult} /></section>
    </div>}
    <section className="pq-live-candidates" aria-labelledby="pq-live-candidates-heading"><header><div><h3 id="pq-live-candidates-heading">Candidate progress</h3><p>{candidates.filter((candidate) => candidate.state === 'completed').length} completed · {pendingSlots} candidate slots remain</p></div></header><div className="pq-table-scroll"><table className="quant-research-table"><caption className="quant-visually-hidden">Live candidate experiment progress</caption><thead><tr><th>Candidate</th><th>Role</th><th>Hypothesis</th><th>Parameters</th><th className="is-numeric">Return</th><th className="is-numeric">Sharpe</th><th className="is-action">State</th></tr></thead><tbody>{candidates.map((candidate) => <tr key={candidate.id}><th scope="row">{candidateLabel(candidate.name)}</th><td>{liveCandidateRole(snapshot, candidate)}</td><td>{candidate.hypothesis}</td><td>{candidate.parameters || '—'}</td><td className="is-numeric">{candidate.metrics ? percent(candidate.metrics.annualizedReturn) : '—'}</td><td className="is-numeric">{candidate.metrics ? candidate.metrics.sharpe.toFixed(2) : '—'}</td><td className="is-action">{liveStatus(candidate)}</td></tr>)}{candidates.length === 0 && <tr className="is-pending"><th scope="row">No candidate yet</th><td>Waiting</td><td>The Agent has not retained an initial hypothesis.</td><td>—</td><td className="is-numeric">—</td><td className="is-numeric">—</td><td className="is-action">Queued</td></tr>}{Array.from({ length: pendingSlots }, (_, index) => <tr key={`pending-${index}`} className="is-pending"><th scope="row">Candidate slot {candidates.length + index + 1}</th><td>Not assigned</td><td>Not selected yet</td><td>—</td><td className="is-numeric">—</td><td className="is-numeric">—</td><td className="is-action">Pending</td></tr>)}</tbody></table></div></section>
    {showDecisionSummary && live && <footer><strong>Next step</strong><span>{live.nextStep}</span></footer>}
  </section>;
}

function TradeTable({ trades, caption, selectedTradeId, onSelectTrade }: { trades: TradeRecord[]; caption: string; selectedTradeId?: string; onSelectTrade?: (id: string) => void }) {
  if (trades.length === 0) return <div className="pq-strategy-empty"><strong>No retained trades</strong><p>The selected candidate has no persisted closed trades in this snapshot.</p></div>;
  return <table className="quant-research-table pq-trades-table"><caption>{caption}</caption><thead><tr><th>Entry</th><th>Exit</th><th className="is-numeric">Return</th><th className="is-numeric">Holding</th></tr></thead><tbody>{trades.map((trade) => <tr key={trade.id} className={trade.id === selectedTradeId ? 'is-selected' : undefined}><td>{onSelectTrade ? <button className="quant-table-link" aria-pressed={trade.id === selectedTradeId} onClick={() => onSelectTrade(trade.id)}>{trade.entryDate}</button> : trade.entryDate}</td><td>{trade.exitDate}</td><td className="is-numeric">{percent(trade.returnPct)}</td><td className="is-numeric">{formatTradeHolding(trade, 'compact')}</td></tr>)}</tbody></table>;
}

function MarketTradeContext({ snapshot, selected, trades, focusedTradeId }: { snapshot: QuantWorkspaceSnapshot; selected: QuantCandidate; trades: TradeRecord[]; focusedTradeId?: string }) {
  const [selectedTradeId, setSelectedTradeId] = useState(focusedTradeId ?? trades[0]?.id ?? '');
  const previousFocusedTradeId = useRef<string | undefined>(focusedTradeId);
  useEffect(() => {
    if (focusedTradeId && trades.some((trade) => trade.id === focusedTradeId)) setSelectedTradeId(focusedTradeId);
    else if (previousFocusedTradeId.current) setSelectedTradeId(trades[0]?.id ?? '');
    previousFocusedTradeId.current = focusedTradeId;
  }, [focusedTradeId, trades]);
  const selectedTrade = trades.find((trade) => trade.id === selectedTradeId) ?? trades[0];
  const markers: QuantMarketTradeMarker[] = trades.flatMap((trade) => [
    { id: `${trade.id}-entry`, date: trade.entryDate, kind: 'entry' as const },
    { id: `${trade.id}-exit`, date: trade.exitDate, kind: 'exit' as const },
  ]);
  return <div className="pq-market-trade-context">
    {selectedTrade && <dl className="pq-market-trade-inspection" aria-label="Selected trade context"><div><dt>Entry</dt><dd>{selectedTrade.entryDate}</dd></div><div><dt>Exit</dt><dd>{selectedTrade.exitDate}</dd></div><div><dt>Return</dt><dd>{percent(selectedTrade.returnPct)}</dd></div><div><dt>Holding</dt><dd>{formatTradeHolding(selectedTrade, 'compact')}</dd></div></dl>}
    <QuantMarketChart bars={snapshot.bars} symbol={snapshot.scope.symbol} interval={snapshot.scope.interval} dateRange={snapshot.scope.dateRange} title={`${candidateLabel(selected.name)} trade context`} description={`Retained ${snapshot.scope.interval} market observations with entry and exit markers for ${candidateLabel(selected.name)}.`} tradeMarkers={markers} highlightedTradeDates={selectedTrade ? [selectedTrade.entryDate, selectedTrade.exitDate] : []} enableIndicators={false} />
    <div className="pq-market-trade-table"><TradeTable trades={trades} caption="Select a trade to inspect it against the retained market path" selectedTradeId={selectedTrade?.id} onSelectTrade={setSelectedTradeId} /></div>
  </div>;
}

function AnalysisPanel({ snapshot, selected, evidenceFocus, onEvidenceFocusConsumed, onContinueResearch }: { snapshot: QuantWorkspaceSnapshot; selected: QuantCandidate; evidenceFocus?: QuantEvidenceFocusIntent | null; onEvidenceFocusConsumed?: (id: string) => void; onContinueResearch?: () => void }) {
  const [view, setView] = useState<AnalysisView>('equity');
  const [evidenceAnchor, setEvidenceAnchor] = useState<AnalysisEvidenceAnchor | null>(null);
  const appliedEvidenceFocusId = useRef<string | null>(null);
  const evidenceAnchorIdentity = useRef({ runId: snapshot.run.id, candidateId: selected.id });
  const series = snapshot.performanceSeries.find((item) => item.id === selected.id);
  const benchmark = snapshot.performanceSeries.find((item) => item.kind === 'benchmark');
  const periods = series ? yearlyReturns(series.points) : [];
  const benchmarkPeriods = new Map((benchmark ? yearlyReturns(benchmark.points) : []).map((item) => [item.year, item.returnPct]));
  const trades = snapshot.trades.filter((trade) => trade.candidateId === selected.id);
  const focusedTradeId = evidenceAnchor?.runId === snapshot.run.id
    && evidenceAnchor.candidateId === selected.id
    && evidenceAnchor.target === 'trade'
    ? evidenceAnchor.tradeId
    : undefined;
  const focusedDrawdownDate = evidenceAnchor?.runId === snapshot.run.id
    && evidenceAnchor.candidateId === selected.id
    && evidenceAnchor.target === 'drawdown'
    ? evidenceAnchor.date
    : undefined;
  useEffect(() => {
    if (evidenceAnchorIdentity.current.runId === snapshot.run.id
      && evidenceAnchorIdentity.current.candidateId === selected.id) return;
    evidenceAnchorIdentity.current = { runId: snapshot.run.id, candidateId: selected.id };
    setEvidenceAnchor(null);
    appliedEvidenceFocusId.current = null;
  }, [selected.id, snapshot.run.id]);
  useEffect(() => {
    if (!evidenceFocus
      || evidenceFocus.runId !== snapshot.run.id
      || evidenceFocus.candidateId !== selected.id
      || evidenceFocus.destination !== 'analysis'
      || appliedEvidenceFocusId.current === evidenceFocus.id) return;
    if (evidenceFocus.target === 'drawdown') {
      if (!series?.points.length) return;
      const lowest = series.points.reduce((current, point) => point.drawdown < current.drawdown ? point : current);
      setEvidenceAnchor({ runId: snapshot.run.id, candidateId: selected.id, target: 'drawdown', date: lowest.date });
      setView('drawdown');
    } else {
      if (!trades.some((trade) => trade.id === evidenceFocus.tradeId)) return;
      setEvidenceAnchor({ runId: snapshot.run.id, candidateId: selected.id, target: 'trade', tradeId: evidenceFocus.tradeId });
      setView('market');
    }
    appliedEvidenceFocusId.current = evidenceFocus.id;
    onEvidenceFocusConsumed?.(evidenceFocus.id);
  }, [evidenceFocus, onEvidenceFocusConsumed, selected.id, series, snapshot.run.id, trades]);
  const selectView = (next: AnalysisView) => {
    setEvidenceAnchor(null);
    setView(next);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = analysisViews.indexOf(view);
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % analysisViews.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + analysisViews.length) % analysisViews.length;
    else return;
    event.preventDefault();
    selectView(analysisViews[next] ?? view);
  };
  const canContinue = Boolean(onContinueResearch && canContinueResearch(snapshot, selected));
  return <section className="pq-strategy-analysis" aria-labelledby="pq-strategy-analysis-heading">
    <header><div><h2 id="pq-strategy-analysis-heading">{candidateLabel(selected.name)}</h2><p>{selected.parameters}</p>{canContinue && <button className="pq-continue-research" onClick={onContinueResearch}>Continue research</button>}</div><dl><div><dt>Return</dt><dd>{percent(selected.metrics.annualizedReturn)}</dd></div><div><dt>Sharpe</dt><dd>{selected.metrics.sharpe.toFixed(2)}</dd></div><div><dt>Drawdown</dt><dd>{percent(selected.metrics.maxDrawdown)}</dd></div><div><dt>Trades</dt><dd>{selected.metrics.trades}</dd></div></dl></header>
    <div className="pq-analysis-tabs" role="tablist" aria-label="Strategy analysis views" onKeyDown={onKeyDown}>{analysisViews.map((item) => <button key={item} role="tab" aria-selected={view === item} tabIndex={view === item ? 0 : -1} onClick={() => selectView(item)}>{item === 'periods' ? 'Period returns' : item[0]?.toUpperCase() + item.slice(1)}</button>)}</div>
    <div className="pq-analysis-view" role="tabpanel">
      {(view === 'equity' || view === 'drawdown') && <StrategyPerformanceChart snapshot={snapshot} selectedCandidateId={selected.id} view={view} focusedDate={view === 'drawdown' ? focusedDrawdownDate : undefined} />}
      {view === 'market' && <MarketTradeContext snapshot={snapshot} selected={selected} trades={trades} focusedTradeId={focusedTradeId} />}
      {view === 'periods' && (periods.length > 0 ? <table className="quant-research-table"><caption>Calendar-period returns</caption><thead><tr><th>Year</th><th className="is-numeric">Strategy</th><th className="is-numeric">Benchmark</th><th className="is-numeric">Difference</th></tr></thead><tbody>{periods.map((item) => { const baseline = benchmarkPeriods.get(item.year); return <tr key={item.year}><th scope="row">{item.year}</th><td className="is-numeric">{percent(item.returnPct)}</td><td className="is-numeric">{percent(baseline)}</td><td className="is-numeric">{percent(baseline === undefined ? undefined : item.returnPct - baseline)}</td></tr>; })}</tbody></table> : <div className="pq-strategy-empty"><strong>Period returns pending</strong><p>This candidate has no completed performance series.</p></div>)}
      {view === 'trades' && <TradeTable trades={trades} caption={`${candidateLabel(selected.name)} trades`} />}
    </div>
  </section>;
}

export function QuantStrategyLab({ snapshot, selectedCandidateId, onSelectCandidate, onContinueResearch, evidenceFocus, onEvidenceFocusConsumed, variant, showLiveDecisionSummary = true }: { snapshot: QuantWorkspaceSnapshot; selectedCandidateId: string; onSelectCandidate: (id: string) => void; onContinueResearch?: () => void; evidenceFocus?: QuantEvidenceFocusIntent | null; onEvidenceFocusConsumed?: (id: string) => void; variant: 'experiments' | 'analysis'; showLiveDecisionSummary?: boolean }) {
  const liveExperimentState = ['queued', 'loading_data', 'generating_candidates', 'running_experiments', 'repairing', 'validating', 'generating_report'].includes(snapshot.run.state);
  if (variant === 'experiments' && liveExperimentState) return <LiveResearchWorkbench snapshot={snapshot} showDecisionSummary={showLiveDecisionSummary} />;
  const selected = snapshot.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? snapshot.candidates[0];
  if (!selected) {
    const terminal = ['completed', 'failed', 'cancelled'].includes(snapshot.run.state);
    return <section className="pq-strategy-lab"><div className="pq-strategy-empty"><strong>{terminal ? 'No candidate evidence retained' : 'Candidate results pending'}</strong><p>{terminal ? 'This run ended without retaining a completed candidate result.' : 'Strategies will appear here as the Agent completes experiments.'}</p></div></section>;
  }
  return <div className={`pq-strategy-lab is-${variant}`}>
    {variant === 'experiments' && <><CandidateComparison snapshot={snapshot} selectedCandidateId={selected.id} onSelectCandidate={onSelectCandidate} /><div className="pq-experiment-selection"><span>Inspecting strategy · {candidateLabel(selected.name)}</span>{onContinueResearch && canContinueResearch(snapshot, selected) && <button onClick={onContinueResearch}>Continue research</button>}</div></>}
    <AnalysisPanel snapshot={snapshot} selected={selected} evidenceFocus={variant === 'analysis' && selectedCandidateId === selected.id ? evidenceFocus : null} onEvidenceFocusConsumed={onEvidenceFocusConsumed} onContinueResearch={variant === 'analysis' ? onContinueResearch : undefined} />
  </div>;
}
