import { useState } from 'react';
import { Badge, Status } from '@glint/ui';
import type { DatasetDataQuality, GeneralizationMetrics, QuantCandidate, QuantWorkspaceSnapshot, ResearchGeneralization, ResearchWalkForward } from '../../quant-domain';
import { quantAuthenticityLabel } from '../../quant-domain';
import type { QuantCandidatePresentation } from './quant-presentation';

type ReportTab = 'overview' | 'performance' | 'generalization' | 'experiments' | 'trades' | 'robustness' | 'strategy' | 'logs';
const tabs: ReportTab[] = ['overview', 'performance', 'generalization', 'experiments', 'trades', 'robustness', 'strategy', 'logs'];

const metric = (value: number, suffix = '') => `${value.toFixed(value % 1 === 0 ? 0 : 1)}${suffix}`;

function MetricsRow({ name, metrics, verdict }: { name: string; metrics: QuantCandidate['metrics']; verdict: string }) {
  return <tr><th scope="row">{name}</th><td>{metric(metrics.annualizedReturn, '%')}</td><td>{metric(metrics.maxDrawdown, '%')}</td><td>{metrics.sharpe.toFixed(2)}</td><td>{metrics.trades}</td><td>{verdict}</td></tr>;
}

function GeneralizationMetricsTable({ title, metrics }: { title: string; metrics: GeneralizationMetrics }) {
  return <table><caption>{title}</caption><thead><tr><th>Series</th><th>Return</th><th>Drawdown</th><th>Sharpe</th><th>Trades</th><th>Sample</th></tr></thead><tbody><MetricsRow name="Candidate" metrics={metrics.candidate} verdict={title} /><MetricsRow name="Benchmark" metrics={metrics.benchmark} verdict={title} /></tbody></table>;
}

const generalizationTone = (status: ResearchGeneralization['status']): 'positive' | 'danger' | 'warning' | 'neutral' => {
  if (status === 'pass') return 'positive';
  if (status === 'fail') return 'danger';
  if (status === 'inconclusive') return 'warning';
  return 'neutral';
};

function WalkForwardPanel({ walkForward }: { walkForward?: ResearchWalkForward }) {
  if (!walkForward) return <div className="quant-walk-forward"><h4>Training walk-forward unavailable</h4><p>This report predates repeated training-window validation.</p></div>;
  return <section className="quant-walk-forward" aria-label="Training walk-forward robustness">
    <h4>Training walk-forward robustness</h4>
    <p>{walkForward.reason} These windows are visible training evidence, not the sealed final holdout.</p>
    <dl>
      <div><dt>Rule version</dt><dd><code>{walkForward.ruleVersion}</code></dd></div>
      <div><dt>Partition</dt><dd>{walkForward.evaluationPartition}</dd></div>
      <div><dt>Evaluated folds</dt><dd>{walkForward.aggregate.evaluatedFolds} / {walkForward.foldCount}</dd></div>
      <div><dt>Window bars</dt><dd>{walkForward.windowBarCount}</dd></div>
      <div><dt>Positive-return folds</dt><dd>{walkForward.aggregate.candidatePositiveReturnFolds}</dd></div>
      <div><dt>Lower-drawdown folds</dt><dd>{walkForward.aggregate.candidateLowerDrawdownFolds}</dd></div>
    </dl>
    <table><caption>Expanding training-only evaluation windows</caption><thead><tr><th>Fold</th><th>Evaluation</th><th>Candidate return</th><th>Benchmark return</th><th>Candidate drawdown</th><th>Benchmark drawdown</th><th>Status</th></tr></thead><tbody>{walkForward.folds.map((fold) => <tr key={fold.foldIndex}><th scope="row">{fold.foldIndex}</th><td>{fold.evaluationStart} – {fold.evaluationEnd}</td><td>{metric(fold.candidate.annualizedReturn, '%')}</td><td>{metric(fold.benchmark.annualizedReturn, '%')}</td><td>{metric(fold.candidate.maxDrawdown, '%')}</td><td>{metric(fold.benchmark.maxDrawdown, '%')}</td><td>{fold.status}</td></tr>)}</tbody></table>
  </section>;
}

function DatasetQualityPanel({ quality }: { quality?: DatasetDataQuality }) {
  if (!quality) return <section className="quant-walk-forward" aria-label="Dataset quality"><h4>Dataset quality unavailable</h4><p>This legacy or synthetic snapshot has no retained quality report. Quality checks are not market-data verification or strategy performance.</p></section>;
  return <section className="quant-walk-forward" aria-label="Dataset quality">
    <h4>Dataset quality (pinned version) <Status tone={quality.status === 'passed' ? 'positive' : quality.status === 'blocked' ? 'danger' : 'warning'}>{quality.status}</Status></h4>
    <p>Quality checks describe the pinned input, not market-data authenticity or strategy performance.</p>
    <dl><div><dt>Verification</dt><dd>{quality.verificationStatus}</dd></div><div><dt>Checked bars</dt><dd>{quality.barCount.toLocaleString()}</dd></div><div><dt>Calendar gaps</dt><dd>{quality.calendarGapCount}</dd></div><div><dt>Largest gap</dt><dd>{quality.largestCalendarGapDays} days</dd></div><div><dt>Unexpected sessions</dt><dd>{quality.unexpectedSessionCount ?? 0}</dd></div><div><dt>Zero-volume bars</dt><dd>{quality.zeroVolumeBarCount}</dd></div><div><dt>Price jumps</dt><dd>{quality.priceJumpCount}</dd></div></dl>
    {quality.issues.length > 0 && <ul>{quality.issues.map((issue) => <li key={`${issue.code}-${issue.message}`}>{issue.severity}: {issue.message} ({issue.count})</li>)}</ul>}
    {quality.notes.length > 0 && <ul>{quality.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
  </section>;
}

export function QuantGeneralizationPanel({ generalization, walkForward, datasetQuality }: { generalization?: ResearchGeneralization; walkForward?: ResearchWalkForward; datasetQuality?: DatasetDataQuality }) {
  if (!generalization) return <div className="quant-check-list"><h4>Generalization unavailable</h4><p>This report does not include a chronological train/holdout evaluation.</p></div>;

  return <div className="quant-check-list quant-generalization">
    <h4>Chronological generalization <Status tone={generalizationTone(generalization.status)}>{generalization.status.replaceAll('_', ' ')}</Status></h4>
    <p>{generalization.reason}</p>
    <dl>
      <div><dt>Split method</dt><dd>{generalization.split.method}</dd></div>
      <div><dt>Rule version</dt><dd><code>{generalization.split.ruleVersion}</code></dd></div>
      <div><dt>Training bars</dt><dd>{generalization.split.trainBarCount}</dd></div>
      <div><dt>Holdout bars</dt><dd>{generalization.split.holdoutBarCount}</dd></div>
      <div><dt>Cutoff date</dt><dd>{generalization.split.cutoffDate}</dd></div>
      <div><dt>Selected candidate</dt><dd>{generalization.selectedCandidateId ?? 'Unavailable'}</dd></div>
      <div><dt>Dataset</dt><dd><code>{generalization.split.datasetId}</code></dd></div>
      <div><dt>Dataset digest</dt><dd><code>{generalization.split.datasetDigest}</code></dd></div>
    </dl>
    {generalization.train ? <GeneralizationMetricsTable title="Training metrics" metrics={generalization.train} /> : <p>Training metrics unavailable.</p>}
    {generalization.holdout ? <GeneralizationMetricsTable title="Holdout metrics" metrics={generalization.holdout} /> : <p>Holdout metrics unavailable.</p>}
    <WalkForwardPanel walkForward={walkForward} />
    <DatasetQualityPanel quality={datasetQuality} />
  </div>;
}

export function QuantStrategyReport({ snapshot, candidates, selectedCandidateId, onSelectCandidate }: {
  snapshot: QuantWorkspaceSnapshot;
  candidates: QuantCandidatePresentation[];
  selectedCandidateId: string;
  onSelectCandidate: (id: string) => void;
}) {
  const [tab, setTab] = useState<ReportTab>('overview');
  const report = snapshot.report;
  const selected = snapshot.candidates.find((candidate) => candidate.id === selectedCandidateId)
    ?? snapshot.candidates.find((candidate) => candidate.id === report?.generalization?.selectedCandidateId)
    ?? snapshot.candidates[0];
  const benchmark = snapshot.benchmark;
  const authenticityLabel = quantAuthenticityLabel(snapshot.authenticity);
  if (!selected || !benchmark || !report) return <section className="quant-report quant-report-empty" aria-label="Strategy Report pending"><div><p className="quant-eyebrow">Strategy Report</p><h3>Agent output is pending</h3><p>Candidate metrics, trades, and conclusions stay hidden until the API reports computed evidence and a generated report.</p><Badge tone="warning">{authenticityLabel}</Badge></div></section>;
  const selectedPresentation = candidates.find((candidate) => candidate.id === selected.id);

  return <section className="quant-report" aria-labelledby="quant-report-title">
    <header><div><p className="quant-eyebrow">Strategy Report</p><h3 id="quant-report-title">Experiment evidence</h3></div><label><span>Candidate</span><select value={selected.id} onChange={(event) => onSelectCandidate(event.target.value)}>{snapshot.candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select></label>{selectedPresentation && <Status tone={selectedPresentation.verdictTone}>{selectedPresentation.verdictLabel}</Status>}</header>
    <div className="quant-report-tabs" role="tablist" aria-label="Strategy report sections">{tabs.map((item) => <button role="tab" id={`quant-tab-${item}`} aria-controls={`quant-panel-${item}`} aria-selected={tab === item} tabIndex={tab === item ? 0 : -1} key={item} onClick={() => setTab(item)}>{item}</button>)}</div>
    <div className="quant-report-panel" role="tabpanel" id={`quant-panel-${tab}`} aria-labelledby={`quant-tab-${tab}`}>
      {tab === 'overview' && <><div className="quant-report-conclusion"><div><p className="quant-eyebrow">Conclusion</p><h4>{report.conclusion}</h4></div><Badge tone="warning">{authenticityLabel}</Badge></div><div className="quant-metric-cards"><article><span>Training annualized return</span><strong>{metric(selected.metrics.annualizedReturn, '%')}</strong><small>Training benchmark {metric(benchmark.annualizedReturn, '%')}</small></article><article><span>Training maximum drawdown</span><strong>{metric(selected.metrics.maxDrawdown, '%')}</strong><small>Training benchmark {metric(benchmark.maxDrawdown, '%')}</small></article><article><span>Training Sharpe</span><strong>{selected.metrics.sharpe.toFixed(2)}</strong><small>Training benchmark {benchmark.sharpe.toFixed(2)}</small></article><article><span>Training trades</span><strong>{selected.metrics.trades}</strong><small>Persisted computed count</small></article></div><p className="quant-disclaimer">{report.disclaimer}</p></>}
      {tab === 'performance' && <table><caption>Training candidate and benchmark computed metrics</caption><thead><tr><th>Series</th><th>Return</th><th>Drawdown</th><th>Sharpe</th><th>Trades</th><th>Result</th></tr></thead><tbody><MetricsRow name="Training buy and hold" metrics={benchmark} verdict="Benchmark" /><MetricsRow name={`Training ${selected.name}`} metrics={selected.metrics} verdict={selectedPresentation?.verdictLabel ?? selected.verdict} /></tbody></table>}
      {tab === 'generalization' && <QuantGeneralizationPanel generalization={report.generalization} walkForward={report.walkForward} datasetQuality={report.datasetQuality ?? snapshot.dataset.quality} />}
      {tab === 'experiments' && <table><caption>All persisted training candidate experiments</caption><thead><tr><th>Candidate</th><th>Parameters</th><th>Return</th><th>Drawdown</th><th>Sharpe</th><th>Verdict</th></tr></thead><tbody>{snapshot.candidates.map((candidate) => <tr key={candidate.id}><th scope="row"><button className="quant-table-link" onClick={() => onSelectCandidate(candidate.id)}>{candidate.name}</button></th><td>{candidate.parameters}</td><td>{metric(candidate.metrics.annualizedReturn, '%')}</td><td>{metric(candidate.metrics.maxDrawdown, '%')}</td><td>{candidate.metrics.sharpe.toFixed(2)}</td><td>{candidates.find((item) => item.id === candidate.id)?.verdictLabel}</td></tr>)}</tbody></table>}
      {tab === 'trades' && <table><caption>{selected.name} retained training trade records</caption><thead><tr><th>Entry</th><th>Exit</th><th>Return</th><th>Holding</th><th>Reason</th></tr></thead><tbody>{snapshot.trades.filter((trade) => trade.candidateId === selected.id).map((trade) => <tr key={trade.id}><td>{trade.entryDate}</td><td>{trade.exitDate}</td><td>{metric(trade.returnPct, '%')}</td><td>{trade.holdingDays} days</td><td>{trade.reason}</td></tr>)}</tbody></table>}
      {tab === 'robustness' && <div className="quant-check-list"><h4>{selected.verdictReason}</h4><ul>{selected.robustness.map((finding) => <li key={finding}>{finding}</li>)}</ul><p>Candidate verdicts describe hypothesis quality. They do not change the completed run state.</p></div>}
      {tab === 'strategy' && <div className="quant-spec"><div><Badge tone="neutral">{selected.strategySpecVersion}</Badge><span>Read-only specification · not executable code</span></div><pre>{selected.strategySpec}</pre></div>}
      {tab === 'logs' && <ol className="quant-safe-logs">{snapshot.events.map((event) => <li key={event.id}><time>{event.timestamp}</time><span>{event.safeSummary}</span></li>)}</ol>}
    </div>
  </section>;
}
