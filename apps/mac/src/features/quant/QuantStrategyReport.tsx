import { useState } from 'react';
import { Badge, Status } from '@glint/ui';
import type { QuantCandidate, QuantWorkspaceSnapshot } from '../../quant-domain';
import type { QuantCandidatePresentation } from './quant-presentation';

type ReportTab = 'overview' | 'performance' | 'experiments' | 'trades' | 'robustness' | 'strategy' | 'logs';
const tabs: ReportTab[] = ['overview', 'performance', 'experiments', 'trades', 'robustness', 'strategy', 'logs'];

const metric = (value: number, suffix = '') => `${value.toFixed(value % 1 === 0 ? 0 : 1)}${suffix}`;

function MetricsRow({ name, metrics, verdict }: { name: string; metrics: QuantCandidate['metrics']; verdict: string }) {
  return <tr><th scope="row">{name}</th><td>{metric(metrics.annualizedReturn, '%')}</td><td>{metric(metrics.maxDrawdown, '%')}</td><td>{metrics.sharpe.toFixed(2)}</td><td>{metrics.trades}</td><td>{verdict}</td></tr>;
}

export function QuantStrategyReport({ snapshot, candidates, selectedCandidateId, onSelectCandidate }: {
  snapshot: QuantWorkspaceSnapshot;
  candidates: QuantCandidatePresentation[];
  selectedCandidateId: string;
  onSelectCandidate: (id: string) => void;
}) {
  const [tab, setTab] = useState<ReportTab>('overview');
  const selected = snapshot.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? snapshot.candidates[0];
  const benchmark = snapshot.benchmark;
  const report = snapshot.report;
  if (!selected || !benchmark || !report) return <section className="quant-report quant-report-empty" aria-label="Strategy Report pending"><div><p className="quant-eyebrow">Strategy Report</p><h3>Agent output is pending</h3><p>Candidate metrics, trades, and conclusions stay hidden until the API reports computed synthetic evidence and a generated report.</p><Badge tone="warning">Synthetic Demo Fixture</Badge></div></section>;
  const selectedPresentation = candidates.find((candidate) => candidate.id === selected.id);

  return <section className="quant-report" aria-labelledby="quant-report-title">
    <header><div><p className="quant-eyebrow">Strategy Report</p><h3 id="quant-report-title">Experiment evidence</h3></div><label><span>Candidate</span><select value={selected.id} onChange={(event) => onSelectCandidate(event.target.value)}>{snapshot.candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select></label>{selectedPresentation && <Status tone={selectedPresentation.verdictTone}>{selectedPresentation.verdictLabel}</Status>}</header>
    <div className="quant-report-tabs" role="tablist" aria-label="Strategy report sections">{tabs.map((item) => <button role="tab" id={`quant-tab-${item}`} aria-controls={`quant-panel-${item}`} aria-selected={tab === item} tabIndex={tab === item ? 0 : -1} key={item} onClick={() => setTab(item)}>{item}</button>)}</div>
    <div className="quant-report-panel" role="tabpanel" id={`quant-panel-${tab}`} aria-labelledby={`quant-tab-${tab}`}>
      {tab === 'overview' && <><div className="quant-report-conclusion"><div><p className="quant-eyebrow">Conclusion</p><h4>{report.conclusion}</h4></div><Badge tone="warning">Synthetic Demo Fixture</Badge></div><div className="quant-metric-cards"><article><span>Annualized return</span><strong>{metric(selected.metrics.annualizedReturn, '%')}</strong><small>Benchmark {metric(benchmark.annualizedReturn, '%')}</small></article><article><span>Maximum drawdown</span><strong>{metric(selected.metrics.maxDrawdown, '%')}</strong><small>Benchmark {metric(benchmark.maxDrawdown, '%')}</small></article><article><span>Sharpe</span><strong>{selected.metrics.sharpe.toFixed(2)}</strong><small>Benchmark {benchmark.sharpe.toFixed(2)}</small></article><article><span>Trades</span><strong>{selected.metrics.trades}</strong><small>Persisted computed count</small></article></div><p className="quant-disclaimer">{report.disclaimer}</p></>}
      {tab === 'performance' && <table><caption>Candidate and benchmark synthetic metrics</caption><thead><tr><th>Series</th><th>Return</th><th>Drawdown</th><th>Sharpe</th><th>Trades</th><th>Result</th></tr></thead><tbody><MetricsRow name="Buy and Hold" metrics={benchmark} verdict="Benchmark" /><MetricsRow name={selected.name} metrics={selected.metrics} verdict={selectedPresentation?.verdictLabel ?? selected.verdict} /></tbody></table>}
      {tab === 'experiments' && <table><caption>All persisted candidate experiments</caption><thead><tr><th>Candidate</th><th>Parameters</th><th>Return</th><th>Drawdown</th><th>Sharpe</th><th>Verdict</th></tr></thead><tbody>{snapshot.candidates.map((candidate) => <tr key={candidate.id}><th scope="row"><button className="quant-table-link" onClick={() => onSelectCandidate(candidate.id)}>{candidate.name}</button></th><td>{candidate.parameters}</td><td>{metric(candidate.metrics.annualizedReturn, '%')}</td><td>{metric(candidate.metrics.maxDrawdown, '%')}</td><td>{candidate.metrics.sharpe.toFixed(2)}</td><td>{candidates.find((item) => item.id === candidate.id)?.verdictLabel}</td></tr>)}</tbody></table>}
      {tab === 'trades' && <table><caption>{selected.name} retained trade records</caption><thead><tr><th>Entry</th><th>Exit</th><th>Return</th><th>Holding</th><th>Reason</th></tr></thead><tbody>{snapshot.trades.filter((trade) => trade.candidateId === selected.id).map((trade) => <tr key={trade.id}><td>{trade.entryDate}</td><td>{trade.exitDate}</td><td>{metric(trade.returnPct, '%')}</td><td>{trade.holdingDays} days</td><td>{trade.reason}</td></tr>)}</tbody></table>}
      {tab === 'robustness' && <div className="quant-check-list"><h4>{selected.verdictReason}</h4><ul>{selected.robustness.map((finding) => <li key={finding}>{finding}</li>)}</ul><p>Candidate verdicts describe hypothesis quality. They do not change the completed run state.</p></div>}
      {tab === 'strategy' && <div className="quant-spec"><div><Badge tone="neutral">{selected.strategySpecVersion}</Badge><span>Read-only specification · not executable code</span></div><pre>{selected.strategySpec}</pre></div>}
      {tab === 'logs' && <ol className="quant-safe-logs">{snapshot.events.map((event) => <li key={event.id}><time>{event.timestamp}</time><span>{event.safeSummary}</span></li>)}</ol>}
    </div>
  </section>;
}
