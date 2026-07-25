import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Badge } from '@glint/ui';
import type { QuantApi, QuantRunHistoryItem } from '../../quant-api';
import type { BacktestMetrics, DatasetDataQuality, GeneralizationMetrics, QuantMarketDatasetQuality, QuantRobustnessMetrics, QuantRobustnessSensitivity, QuantWorkspaceSnapshot, ResearchGeneralization, ResearchWalkForward } from '../../quant-domain';
import { StrategyPerformanceChart } from './QuantStrategyLab';
import { QuantReportExportDialog } from './QuantReportExportDialog';
import { QuantTerminalDecision } from './QuantTerminalDecision';
import { formatTradeHolding, projectNextResearchProposal, projectQuantRunRelationship, projectTerminalDecision, quantRunHistoryMatchesSnapshot, type QuantCandidatePresentation, type QuantDecisionPresentation, type QuantEvidenceFocusIntent } from './quant-presentation';

type ReportTab = 'summary' | 'candidates' | 'validation' | 'trades' | 'strategy' | 'audit';
const tabs: ReportTab[] = ['summary', 'candidates', 'validation', 'trades', 'strategy', 'audit'];

const metric = (value: number, suffix = '') => `${value.toFixed(value % 1 === 0 ? 0 : 1)}${suffix}`;
const costRatePercent = (rate: number) => `${(rate * 100).toFixed(rate * 100 < 0.1 ? 2 : 1)}%`;
const percent = (value: number | undefined) => value === undefined || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
const statusLabel = (status: string) => status === 'not_evaluated' ? 'Not evaluated' : status[0]?.toUpperCase() + status.slice(1).replaceAll('_', ' ');
const candidateName = (value: string) => value.replace(/^Candidate [A-Z] · /, '');
const frontStageConclusion = (value: string) => value.replace(
  /suitable for live trading/gi,
  'promotable within this research scope',
);
const candidateParameters = (value: string) => value.replaceAll('_', ' ').replaceAll('=', ' ');

function ReportState({ tone, children }: { tone: 'positive' | 'danger' | 'warning' | 'neutral' | 'info'; children: string }) {
  return <span className={`quant-report-state is-${tone}`}>{children}</span>;
}

function MetricsRow({ partition, name, metrics }: { partition: string; name: string; metrics: BacktestMetrics }) {
  return <tr><td>{partition}</td><th scope="row">{name}</th><td>{metric(metrics.annualizedReturn, '%')}</td><td>{metric(metrics.maxDrawdown, '%')}</td><td>{metrics.sharpe.toFixed(2)}</td><td>{metrics.trades}</td></tr>;
}

function GeneralizationMetricsTable({ train, holdout }: { train?: GeneralizationMetrics; holdout?: GeneralizationMetrics }) {
  if (!train && !holdout) return <div className="quant-report-empty-state"><strong>Partition metrics unavailable</strong><p>This run retained split metadata but no comparable training or holdout metrics.</p></div>;
  return <table className="quant-research-table quant-partition-table"><caption>Candidate and benchmark by evaluation partition</caption><thead><tr><th>Partition</th><th>Series</th><th>Annual return</th><th>Drawdown</th><th>Sharpe</th><th>Trades</th></tr></thead><tbody>
    {train && <><MetricsRow partition="Training" name="Candidate" metrics={train.candidate} /><MetricsRow partition="Training" name="Buy and hold" metrics={train.benchmark} /></>}
    {holdout && <><MetricsRow partition="Sealed holdout" name="Candidate" metrics={holdout.candidate} /><MetricsRow partition="Sealed holdout" name="Buy and hold" metrics={holdout.benchmark} /></>}
  </tbody></table>;
}

const generalizationTone = (status: ResearchGeneralization['status']): 'positive' | 'danger' | 'warning' | 'neutral' => {
  if (status === 'pass') return 'positive';
  if (status === 'fail') return 'danger';
  if (status === 'inconclusive') return 'warning';
  return 'neutral';
};

function WalkForwardPanel({ walkForward }: { walkForward?: ResearchWalkForward }) {
  if (!walkForward) return <section className="quant-report-empty-state"><strong>Walk-forward evidence unavailable</strong><p>This report predates repeated training-window validation.</p></section>;
  return <section className="quant-walk-forward" aria-label="Training walk-forward robustness">
    <header><div><h4>Walk-forward robustness</h4><p>{walkForward.reason} Training-only modeled windows are not sealed-holdout evidence.</p></div><ReportState tone={walkForward.status === 'completed' ? 'positive' : 'neutral'}>{statusLabel(walkForward.status)}</ReportState></header>
    <dl>
      <div><dt>Evaluated windows</dt><dd>{walkForward.aggregate.evaluatedFolds} / {walkForward.foldCount}</dd></div>
      <div><dt>Positive return</dt><dd>{walkForward.aggregate.candidatePositiveReturnFolds} / {walkForward.foldCount}</dd></div>
      <div><dt>Lower drawdown</dt><dd>{walkForward.aggregate.candidateLowerDrawdownFolds} / {walkForward.foldCount}</dd></div>
      <div><dt>Window size</dt><dd>{walkForward.windowBarCount} bars</dd></div>
    </dl>
    <div className="pq-table-scroll"><table className="quant-research-table"><caption>Training-only expanding windows and modeled market state</caption><thead><tr><th>Window</th><th>Evaluation</th><th>Modeled regime</th><th>Candidate return</th><th>Benchmark return</th><th>Candidate drawdown</th><th>Benchmark drawdown</th><th>Result</th></tr></thead><tbody>{walkForward.folds.map((fold) => <tr key={fold.foldIndex}><th scope="row">{fold.foldIndex}</th><td>{fold.evaluationStart} – {fold.evaluationEnd}</td><td>{fold.marketRegime?.label ?? 'State not retained'}</td><td>{metric(fold.candidate.annualizedReturn, '%')}</td><td>{metric(fold.benchmark.annualizedReturn, '%')}</td><td>{metric(fold.candidate.maxDrawdown, '%')}</td><td>{metric(fold.benchmark.maxDrawdown, '%')}</td><td><span className={`quant-status-text is-${fold.status}`}>{statusLabel(fold.status)}</span></td></tr>)}</tbody></table></div>
    {walkForward.aggregate.byMarketRegime && <><header><div><h4>Modeled-regime summary</h4><p>{walkForward.aggregate.distinctMarketRegimes} retained regime{walkForward.aggregate.distinctMarketRegimes === 1 ? '' : 's'} · {statusLabel(walkForward.aggregate.regimeDiversityStatus ?? 'insufficient_regime_diversity')}</p></div></header><div className="pq-table-scroll"><table className="quant-research-table"><caption>Training-only retained aggregate by modeled market regime</caption><thead><tr><th>Modeled regime</th><th>Windows</th><th>Candidate median return</th><th>Benchmark median return</th><th>Candidate median drawdown</th><th>Benchmark median drawdown</th><th>Candidate median Sharpe</th><th>Benchmark median Sharpe</th></tr></thead><tbody>{walkForward.aggregate.byMarketRegime.map((regime) => <tr key={regime.label}><th scope="row">{regime.label}</th><td>{regime.foldCount}</td><td>{metric(regime.candidateMedianReturn, '%')}</td><td>{metric(regime.benchmarkMedianReturn, '%')}</td><td>{metric(regime.candidateMedianDrawdown, '%')}</td><td>{metric(regime.benchmarkMedianDrawdown, '%')}</td><td>{metric(regime.candidateMedianSharpe)}</td><td>{metric(regime.benchmarkMedianSharpe)}</td></tr>)}</tbody></table></div></>}
    <details className="quant-report-provenance"><summary>Walk-forward provenance</summary><dl><div><dt>Rule version</dt><dd><code>{walkForward.ruleVersion}</code></dd></div><div><dt>State rule version</dt><dd><code>{walkForward.stateRuleVersion ?? 'Not retained'}</code></dd></div><div><dt>State lookback</dt><dd>{walkForward.stateLookbackBars === undefined ? 'Not retained' : `${walkForward.stateLookbackBars} bars`}</dd></div><div><dt>Evaluation partition</dt><dd>{walkForward.evaluationPartition} only</dd></div></dl></details>
  </section>;
}

function RobustnessMetricCells({ metrics }: { metrics: QuantRobustnessMetrics }) {
  return <><td className="is-numeric">{metric(metrics.totalReturnPct, '%')}</td><td className="is-numeric">{metric(metrics.annualizedReturnPct, '%')}</td><td className="is-numeric">{metric(metrics.maximumDrawdownPct, '%')}</td><td className="is-numeric">{metric(metrics.sharpeRatio)}</td><td className="is-numeric">{metrics.tradeCount}</td><td className="is-numeric">{metric(metrics.winRatePct, '%')}</td><td className="is-numeric">{metric(metrics.finalEquity)}</td></>;
}

function RobustnessSensitivityPanel({ sensitivity, finalCandidateName, legacy }: { sensitivity?: QuantRobustnessSensitivity; finalCandidateName: string; legacy: boolean }) {
  if (!sensitivity) return <section className="quant-walk-forward" aria-label="Robustness sensitivity"><header><div><h4>Robustness sensitivity</h4><p>{legacy ? 'No retained train-only cost or parameter sensitivity evidence is available for this legacy report.' : 'No retained train-only cost or parameter sensitivity evidence is available for this report.'}</p></div><ReportState tone="neutral">Unavailable</ReportState></header></section>;
  return <section className="quant-walk-forward" aria-label="Robustness sensitivity">
    <header><div><h4>Robustness sensitivity</h4><p>{finalCandidateName} · local training evidence under retained cost scenarios and one-at-a-time parameter neighbors. It does not establish global robustness and is not sealed holdout evidence.</p></div><ReportState tone="neutral">Training only</ReportState></header>
    <div className="pq-table-scroll"><table className="quant-research-table"><caption>Retained cost scenarios · candidate and benchmark absolute metrics</caption><thead><tr><th>Scenario</th><th className="is-numeric">Fee</th><th className="is-numeric">Slippage</th><th>Series</th><th className="is-numeric">Total return</th><th className="is-numeric">Annual return</th><th className="is-numeric">Drawdown</th><th className="is-numeric">Sharpe</th><th className="is-numeric">Trades</th><th className="is-numeric">Win rate</th><th className="is-numeric">Final equity</th></tr></thead><tbody>{sensitivity.costScenarios.flatMap((scenario) => [<tr key={`${scenario.scenario}-candidate`}><th scope="row" rowSpan={2}>{scenario.scenario}</th><td className="is-numeric" rowSpan={2}>{costRatePercent(scenario.feeRate)}</td><td className="is-numeric" rowSpan={2}>{costRatePercent(scenario.slippageRate)}</td><td>Candidate</td><RobustnessMetricCells metrics={scenario.candidateMetrics} /></tr>, <tr key={`${scenario.scenario}-benchmark`}><td>Buy and hold</td><RobustnessMetricCells metrics={scenario.benchmarkMetrics} /></tr>])}</tbody></table></div>
    {sensitivity.parameterNeighbors.length > 0 ? <div className="pq-table-scroll"><table className="quant-research-table"><caption>Retained one-at-a-time parameter neighbors · candidate absolute metrics</caption><thead><tr><th>Parameter</th><th>Direction</th><th>Parameters</th><th className="is-numeric">Total return</th><th className="is-numeric">Annual return</th><th className="is-numeric">Drawdown</th><th className="is-numeric">Sharpe</th><th className="is-numeric">Trades</th><th className="is-numeric">Win rate</th><th className="is-numeric">Final equity</th></tr></thead><tbody>{sensitivity.parameterNeighbors.map((neighbor) => <tr key={neighbor.canonicalKey}><th scope="row">{neighbor.parameterName}</th><td>{neighbor.direction}</td><td>{Object.entries(neighbor.parameters).map(([name, value]) => `${name}=${value}`).join(' · ')}</td><RobustnessMetricCells metrics={neighbor.candidateMetrics} /></tr>)}</tbody></table></div> : <p>No retained legal, in-range one-at-a-time neighbors were available. This does not establish stability.</p>}
    <details className="quant-report-provenance"><summary>Sensitivity provenance</summary><dl><div><dt>Report</dt><dd><code>{sensitivity.reportArtifactId}</code></dd></div><div><dt>Source comparison</dt><dd><code>{sensitivity.finalTrainingComparison.artifactId} · {sensitivity.finalTrainingComparison.artifactDigest}</code></dd></div><div><dt>Dataset</dt><dd><code>{sensitivity.dataset.datasetId} · {sensitivity.dataset.datasetDigest}</code></dd></div><div><dt>Training split</dt><dd><code>{sensitivity.trainingSplit.trainingSplitDigest}</code></dd></div><div><dt>Execution rule</dt><dd><code>{sensitivity.executionRuleVersion}</code></dd></div><div><dt>Sampler rule</dt><dd><code>{sensitivity.samplerRuleVersion}</code></dd></div><div><dt>Kernel calls</dt><dd>{sensitivity.kernelCallCount}</dd></div></dl></details>
  </section>;
}

function DatasetQualityPanel({ quality }: { quality?: DatasetDataQuality | QuantMarketDatasetQuality }) {
  if (!quality) return <section className="quant-report-empty-state"><strong>Dataset quality unavailable</strong><p>This legacy snapshot has no retained quality report.</p></section>;
  if ('cadenceGapCount' in quality) {
    return <section className="quant-walk-forward" aria-label="Dataset quality">
      <header><div><h4>Dataset quality</h4><p>Cadence checks describe the pinned market bars used by this run.</p></div><ReportState tone={quality.status === 'accepted' ? 'positive' : 'danger'}>{statusLabel(quality.status)}</ReportState></header>
      <dl><div><dt>Cadence gaps</dt><dd>{quality.cadenceGapCount}</dd></div><div><dt>Normalization</dt><dd>{quality.normalizationNote}</dd></div></dl>
    </section>;
  }
  const anomalyCount = (quality.unexpectedSessionCount ?? 0) + quality.zeroVolumeBarCount + quality.priceJumpCount;
  return <section className="quant-walk-forward" aria-label="Dataset quality">
    <header><div><h4>Dataset quality</h4><p>Checks describe the pinned input, not strategy performance or market-data authenticity.</p></div><ReportState tone={quality.status === 'passed' ? 'positive' : quality.status === 'blocked' ? 'danger' : 'warning'}>{statusLabel(quality.status)}</ReportState></header>
    <dl><div><dt>Verification</dt><dd>{statusLabel(quality.verificationStatus)}</dd></div><div><dt>Checked bars</dt><dd>{quality.barCount.toLocaleString()}</dd></div><div><dt>Calendar gaps</dt><dd>{quality.calendarGapCount}</dd></div><div><dt>Other anomalies</dt><dd>{anomalyCount}</dd></div></dl>
    {(quality.issues.length > 0 || quality.notes.length > 0) && <details className="quant-report-provenance"><summary>Quality findings</summary>{quality.issues.length > 0 && <ul>{quality.issues.map((issue) => <li key={`${issue.code}-${issue.message}`}>{statusLabel(issue.severity)} · {issue.message} ({issue.count})</li>)}</ul>}{quality.notes.length > 0 && <ul>{quality.notes.map((note) => <li key={note}>{note}</li>)}</ul>}</details>}
  </section>;
}

export function QuantGeneralizationPanel({ generalization, walkForward, robustnessSensitivity, datasetQuality, selectedCandidateName, legacy = false }: { generalization?: ResearchGeneralization; walkForward?: ResearchWalkForward; robustnessSensitivity?: QuantRobustnessSensitivity; datasetQuality?: DatasetDataQuality | QuantMarketDatasetQuality; selectedCandidateName?: string; legacy?: boolean }) {
  if (!generalization) return <div className="quant-report-empty-state"><strong>Validation evidence unavailable</strong><p>This report does not include a chronological training and sealed-holdout evaluation.</p></div>;
  return <div className="quant-check-list quant-generalization">
    <header className="quant-validation-heading"><div><h4>Sealed holdout</h4><p>{generalization.reason}</p></div><ReportState tone={generalizationTone(generalization.status)}>{statusLabel(generalization.status)}</ReportState></header>
    <dl>
      <div><dt>Training bars</dt><dd>{generalization.split.trainBarCount.toLocaleString()}</dd></div>
      <div><dt>Holdout bars</dt><dd>{generalization.split.holdoutBarCount.toLocaleString()}</dd></div>
      <div><dt>Cutoff</dt><dd>{generalization.split.cutoffTimestampUtc ?? generalization.split.cutoffDate}</dd></div>
      <div><dt>Selected candidate</dt><dd>{selectedCandidateName ?? generalization.selectedCandidateId ?? 'Unavailable'}</dd></div>
    </dl>
    <GeneralizationMetricsTable train={generalization.train} holdout={generalization.holdout} />
    <details className="quant-report-provenance"><summary>Validation provenance</summary><dl><div><dt>Method</dt><dd>{generalization.split.method}</dd></div><div><dt>Rule version</dt><dd><code>{generalization.split.ruleVersion}</code></dd></div><div><dt>Dataset</dt><dd><code>{generalization.split.datasetId}</code></dd></div><div><dt>Dataset digest</dt><dd><code>{generalization.split.datasetDigest}</code></dd></div></dl></details>
    <WalkForwardPanel walkForward={walkForward} />
    <RobustnessSensitivityPanel sensitivity={robustnessSensitivity} finalCandidateName={selectedCandidateName ?? generalization.selectedCandidateId ?? 'Final candidate'} legacy={legacy} />
    <DatasetQualityPanel quality={datasetQuality} />
  </div>;
}

function CandidateTable({ snapshot, candidates, selectedCandidateId, onSelectCandidate }: { snapshot: QuantWorkspaceSnapshot; candidates: QuantCandidatePresentation[]; selectedCandidateId: string; onSelectCandidate: (id: string) => void }) {
  return <table className="quant-research-table quant-candidate-table"><caption>Training-partition comparison</caption><thead><tr><th>Strategy</th><th>Parameters</th><th>Annual return</th><th>Drawdown</th><th>Sharpe</th><th>Trades</th><th>Training result</th></tr></thead><tbody>
    {snapshot.benchmark && <tr><th scope="row">Buy and hold</th><td>Reference</td><td>{metric(snapshot.benchmark.annualizedReturn, '%')}</td><td>{metric(snapshot.benchmark.maxDrawdown, '%')}</td><td>{snapshot.benchmark.sharpe.toFixed(2)}</td><td>{snapshot.benchmark.trades}</td><td>Benchmark</td></tr>}
    {snapshot.candidates.map((candidate) => <tr key={candidate.id} className={candidate.id === selectedCandidateId ? 'is-selected' : undefined}><th scope="row"><button className="quant-table-link" aria-pressed={candidate.id === selectedCandidateId} onClick={() => onSelectCandidate(candidate.id)}>{candidateName(candidate.name)}</button></th><td>{candidateParameters(candidate.parameters)}</td><td>{metric(candidate.metrics.annualizedReturn, '%')}</td><td>{metric(candidate.metrics.maxDrawdown, '%')}</td><td>{candidate.metrics.sharpe.toFixed(2)}</td><td>{candidate.metrics.trades}</td><td>{candidate.verdict === 'promising' ? 'Retained for validation' : candidates.find((item) => item.id === candidate.id)?.verdictLabel}</td></tr>)}
  </tbody></table>;
}

export function QuantStrategyReport({ api, snapshot, candidates, decision, selectedCandidateId, onSelectCandidate, onOpenAnalysis, onContinueResearch, onRunAutopilot, campaignBusy = false, onOpenRun, onOpenHistory, onStartNewResearch, evidenceFocus, onEvidenceFocusConsumed }: { api: QuantApi; snapshot: QuantWorkspaceSnapshot; candidates: QuantCandidatePresentation[]; decision: QuantDecisionPresentation; selectedCandidateId: string; onSelectCandidate: (id: string) => void; onOpenAnalysis: () => void; onContinueResearch?: (candidateId: string, reason?: string) => void; onRunAutopilot?: (candidateId: string, reason: string) => void; campaignBusy?: boolean; onOpenRun?: (runId: string) => Promise<void> | void; onOpenHistory: () => void; onStartNewResearch: () => void; evidenceFocus?: QuantEvidenceFocusIntent | null; onEvidenceFocusConsumed?: (id: string) => void }) {
  const [tab, setTab] = useState<ReportTab>('summary');
  const [exportCandidateId, setExportCandidateId] = useState<string | null>(null);
  const [relatedRuns, setRelatedRuns] = useState<QuantRunHistoryItem[]>([]);
  const [openingRelatedRunId, setOpeningRelatedRunId] = useState<string | null>(null);
  const exportButtonRef = useRef<HTMLButtonElement | null>(null);
  const openExport = (candidateId: string) => {
    exportButtonRef.current = document.activeElement instanceof HTMLButtonElement ? document.activeElement : null;
    setExportCandidateId(candidateId);
  };
  const report = snapshot.report;
  const selected = snapshot.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? snapshot.candidates.find((candidate) => candidate.id === report?.selectionDecision?.selectedCandidateId) ?? snapshot.candidates[0];
  const benchmark = snapshot.benchmark;
  useEffect(() => {
    if (!evidenceFocus
      || evidenceFocus.runId !== snapshot.run.id
      || evidenceFocus.candidateId !== selectedCandidateId
      || evidenceFocus.destination !== 'report'
      || !snapshot.candidates.some((candidate) => candidate.id === evidenceFocus.candidateId)) return;
    setTab(evidenceFocus.target === 'validation' ? 'validation' : 'trades');
    onEvidenceFocusConsumed?.(evidenceFocus.id);
  }, [evidenceFocus?.id, evidenceFocus, onEvidenceFocusConsumed, selectedCandidateId, snapshot.candidates, snapshot.run.id]);
  useEffect(() => {
    let active = true;
    void Promise.all([api.listRuns(snapshot.project.id), api.listMarketRuns(snapshot.project.id)])
      .then(([legacyRuns, marketRuns]) => { if (active) setRelatedRuns([...legacyRuns, ...marketRuns]); })
      .catch(() => { if (active) setRelatedRuns([]); });
    return () => { active = false; };
  }, [api, snapshot.project.id, snapshot.run.id, snapshot.run.state]);
  if (!selected || !benchmark || !report) {
    const stopped = snapshot.run.state === 'failed' || snapshot.run.state === 'cancelled';
    return <section className="quant-report quant-report-empty" aria-label="Decision unavailable"><div><span className="quant-report-context">Decision</span><h3>{stopped ? 'Decision was not produced' : 'Decision evidence pending'}</h3><p>{snapshot.run.state === 'failed' ? 'The run stopped before a decision could be produced.' : snapshot.run.state === 'cancelled' ? 'The run was cancelled before a decision could be produced.' : 'A selected strategy, benchmark and completed evidence are required before Qurio can present a decision.'}</p><button className="button primary" onClick={onStartNewResearch}>New research</button></div></section>;
  }
  const selectedTrades = snapshot.trades.filter((trade) => trade.candidateId === selected.id);
  const hasPerformance = snapshot.performanceSeries.some((series) => series.id === selected.id && series.points.length > 1);
  const holdout = report.generalization;
  const walkForward = report.walkForward;
  const finalCandidateId = report.generalization?.selectedCandidateId;
  const finalCandidate = finalCandidateId ? snapshot.candidates.find((candidate) => candidate.id === finalCandidateId) : undefined;
  const validationIdentityConsistent = Boolean(
    finalCandidate
    && report.selectionDecision?.selectedCandidateId === finalCandidate.id,
  );
  const isFinalCandidate = validationIdentityConsistent && finalCandidate?.id === selected.id;
  const terminalDecision = projectTerminalDecision(snapshot);
  const hasTerminalDecisionSurface = snapshot.run.state === 'completed';
  const conclusion = isFinalCandidate
    ? frontStageConclusion(report.conclusion)
    : 'This candidate was not the Run’s final selection; its retained training evidence is shown without a sealed-holdout conclusion.';
  const recommendation = isFinalCandidate
    ? report.proposedNextStep
    : 'Alternative candidate · training evidence only. Compare it with the final choice.';
  const nextProposal = !hasTerminalDecisionSurface && isFinalCandidate ? projectNextResearchProposal(snapshot, selected) : null;
  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = tabs.indexOf(tab);
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    const nextTab = tabs[next] ?? tab;
    setTab(nextTab);
    requestAnimationFrame(() => document.getElementById(`quant-tab-${nextTab}`)?.focus());
  };
  const continuation = snapshot.run.continuedFrom;
  const retryAttempt = snapshot.run.retryOfRunId ? snapshot.run.attemptNumber : null;
  const currentHistoryEntries = relatedRuns.filter((run) => run.id === snapshot.run.id);
  const currentHistoryRun = currentHistoryEntries.length === 1 && quantRunHistoryMatchesSnapshot(currentHistoryEntries[0]!, snapshot)
    ? currentHistoryEntries[0]
    : undefined;
  const relationship = currentHistoryRun ? projectQuantRunRelationship(currentHistoryRun, relatedRuns) : null;
  const sourceRun = relationship?.sourceRunId ? relatedRuns.find((run) => run.id === relationship.sourceRunId) : undefined;
  const priorAttemptRun = relationship?.priorAttemptRunId ? relatedRuns.find((run) => run.id === relationship.priorAttemptRunId) : undefined;
  const hasSnapshotRelationship = Boolean(continuation || retryAttempt);
  const relationshipUnavailable = (hasSnapshotRelationship && !relationship)
    || (relationship?.relationship === 'unresolved')
    || (hasSnapshotRelationship && currentHistoryEntries.length > 0 && !currentHistoryRun);
  const openRelatedRun = async (runId: string) => {
    if (!onOpenRun || openingRelatedRunId) return;
    setOpeningRelatedRunId(runId);
    try {
      await onOpenRun(runId);
    } finally {
      setOpeningRelatedRunId(null);
    }
  };

  return <section className="quant-report" aria-labelledby="quant-report-title">
    <header><div><span className="quant-report-context">Decision</span><h3 id="quant-report-title">{snapshot.scope.symbol} evidence</h3>{snapshot.dataset.contract === 'market-v2' && <p>{snapshot.scope.interval} · {snapshot.dataset.periodsPerYear?.toLocaleString()} periods/year · {snapshot.scope.dateRange.start} – {snapshot.scope.dateRange.end}</p>}{(continuation || retryAttempt || sourceRun || priorAttemptRun || relationshipUnavailable) && <div className="quant-report-lineage-context" aria-label="Research relationship">{continuation && <><span>{relationshipUnavailable ? 'Retained continuation context' : 'Continued from source version'}</span><span>Source candidate: {continuation.candidateName}</span><span>Reason: {continuation.reason}</span><span>Source question: {continuation.sourceQuestion}</span></>}{retryAttempt && <span>{relationshipUnavailable ? `Retained retry context · Attempt ${retryAttempt}` : `Retry attempt ${retryAttempt}`}</span>}{relationshipUnavailable && <span>Relationship unavailable</span>}{sourceRun && onOpenRun && <button type="button" className="quant-lineage-action" disabled={openingRelatedRunId !== null} onClick={() => void openRelatedRun(sourceRun.id)}>{openingRelatedRunId === sourceRun.id ? 'Opening…' : 'Open source version'}</button>}{priorAttemptRun && onOpenRun && <button type="button" className="quant-lineage-action" disabled={openingRelatedRunId !== null} onClick={() => void openRelatedRun(priorAttemptRun.id)}>{openingRelatedRunId === priorAttemptRun.id ? 'Opening…' : 'Open prior attempt'}</button>}</div>}</div><label><span>Candidate</span><select value={selected.id} onChange={(event) => onSelectCandidate(event.target.value)}>{snapshot.candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidateName(candidate.name)}</option>)}</select></label></header>
    {hasTerminalDecisionSurface && <QuantTerminalDecision decision={terminalDecision} onExportFinalEvidence={terminalDecision ? openExport : undefined} onOpenHistory={onOpenHistory} onRefineFinalChoice={terminalDecision?.canRefine && onContinueResearch ? (candidateId, reason) => onContinueResearch(candidateId, reason) : undefined} />}
    <div className="quant-report-tabs" role="tablist" aria-label="Research report sections" onKeyDown={onTabKeyDown}>{tabs.map((item) => <button role="tab" id={`quant-tab-${item}`} aria-controls={`quant-panel-${item}`} aria-selected={tab === item} tabIndex={tab === item ? 0 : -1} key={item} onClick={() => setTab(item)}>{item}</button>)}</div>
    <div className="quant-report-panel" role="tabpanel" id={`quant-panel-${tab}`} aria-labelledby={`quant-tab-${tab}`}>
      {tab === 'summary' && <div className="quant-report-summary">
        <section className="quant-report-summary-lede" aria-labelledby="quant-report-conclusion-heading">
          <header><div><span>{isFinalCandidate ? decision.label : 'Alternative candidate · training evidence'}</span><h4 id="quant-report-conclusion-heading">{candidateName(selected.name)} · {isFinalCandidate ? decision.title : 'Training evidence retained'}</h4></div><ReportState tone={decision.tone}>{statusLabel(snapshot.run.state)}</ReportState></header>
          <p>{conclusion}</p>
          {selected.evolution && <dl className="quant-report-decision-path"><div><dt>Research hypothesis</dt><dd>{selected.evolution.hypothesis}</dd></div>{selected.evolution.changeRationale && <div><dt>Iteration change</dt><dd>{selected.evolution.changeRationale}</dd></div>}<div><dt>{isFinalCandidate ? 'Selection basis' : 'Training selection basis'}</dt><dd>{selected.evolution.selectionReason}</dd></div></dl>}
          {!hasTerminalDecisionSurface && <div className="quant-report-recommendation"><strong>Recommendation</strong><span>{recommendation}</span></div>}
        </section>
        <section className="quant-report-decision-evidence" aria-label="Decision evidence">
          <dl className="quant-report-key-metrics" aria-label="Selected strategy key metrics"><div><dt>Annual return</dt><dd>{percent(selected.metrics.annualizedReturn)}</dd></div><div><dt>Sharpe</dt><dd>{selected.metrics.sharpe.toFixed(2)}</dd></div><div><dt>Max drawdown</dt><dd>{percent(selected.metrics.maxDrawdown)}</dd></div><div><dt>Trades</dt><dd>{selected.metrics.trades}</dd></div><div><dt>Vs benchmark</dt><dd>{percent(selected.metrics.annualizedReturn - benchmark.annualizedReturn)}</dd></div></dl>
          <section className="quant-report-validation-summary" aria-labelledby="quant-report-validation-heading"><header><h4 id="quant-report-validation-heading">Validation</h4><ReportState tone={isFinalCandidate && holdout ? generalizationTone(holdout.status) : 'neutral'}>{isFinalCandidate && holdout ? statusLabel(holdout.status) : validationIdentityConsistent ? 'Final candidate only' : 'Not available'}</ReportState></header><dl><div><dt>{isFinalCandidate ? 'Holdout annual return' : 'Final candidate holdout'}</dt><dd>{validationIdentityConsistent ? percent(holdout?.holdout?.candidate.annualizedReturn) : '—'}</dd></div><div><dt>{isFinalCandidate ? 'Positive-return folds' : 'Final candidate folds'}</dt><dd>{validationIdentityConsistent && walkForward ? `${walkForward.aggregate.candidatePositiveReturnFolds} / ${walkForward.foldCount}` : '—'}</dd></div><div><dt>Decision</dt><dd>{isFinalCandidate ? decision.label : validationIdentityConsistent ? 'Final-candidate evidence only' : 'Unavailable'}</dd></div></dl></section>
        </section>
        <div className="quant-report-actions" aria-label="Decision actions">
          <div className="quant-report-action-primary"><button className="button primary" onClick={onOpenAnalysis}>Open analysis</button></div>
          <div className="quant-report-action-secondary">{(!terminalDecision || !isFinalCandidate) && <button ref={exportButtonRef} className="button" onClick={() => openExport(selected.id)}>{terminalDecision ? 'Export selected candidate report' : 'Export report'}</button>}<button className="button" onClick={() => setTab('trades')}>View trades</button>{!hasTerminalDecisionSurface && <button className="button" onClick={onStartNewResearch}>New research</button>}</div>
        </div>
        {nextProposal && <section className="quant-next-research-proposal" aria-labelledby="quant-next-research-heading"><header><div><span>Recommended next step</span><h4 id="quant-next-research-heading">Next research decision</h4></div><ReportState tone={nextProposal.recommendation === 'refine' ? 'warning' : 'positive'}>{nextProposal.recommendation === 'refine' ? 'Refinement recommended' : 'No refinement recommended'}</ReportState></header><dl><div><dt>Proposed change</dt><dd>{nextProposal.change}</dd></div><div><dt>Why</dt><dd>{nextProposal.rationale}</dd></div><div><dt>Evidence required</dt><dd>{nextProposal.evidenceRequired}</dd></div><div><dt>Stop condition</dt><dd>{nextProposal.stopCondition}</dd></div></dl>{nextProposal.execution === 'one_bounded_auto_run' && (onRunAutopilot || onContinueResearch) && <div className="quant-next-research-actions"><div><strong>One suggested refinement</strong><span>Starts one independent refinement version, then returns here for review.</span></div><div>{onRunAutopilot && <button className="button primary" disabled={campaignBusy} onClick={() => onRunAutopilot(selected.id, nextProposal.refinementReason)}>{campaignBusy ? 'Starting…' : 'Run suggested refinement'}</button>}{onContinueResearch && <button className="button" disabled={campaignBusy} onClick={() => onContinueResearch(selected.id, nextProposal.refinementReason)}>Edit refinement</button>}</div></div>}</section>}
        <section className={`quant-report-performance${hasPerformance ? '' : ' is-empty'}`} aria-labelledby="quant-report-performance-heading"><header><div><h4 id="quant-report-performance-heading">Strategy vs benchmark</h4><p>{candidateName(selected.name)} · persisted {snapshot.scope.interval} performance</p></div>{!hasPerformance && <span>Performance series unavailable</span>}</header><div><StrategyPerformanceChart snapshot={snapshot} selectedCandidateId={selected.id} view="equity" /></div></section>
        <section className="quant-report-limitations quant-report-summary-limitations" aria-labelledby="quant-report-limitations-heading"><header><h4 id="quant-report-limitations-heading">Limitations</h4><span>{report.limitations.length}</span></header>{report.limitations.length > 0 ? <ul>{report.limitations.slice(0, 2).map((limitation) => <li key={limitation}>{limitation}</li>)}</ul> : <p>No limitations were retained in this report.</p>}</section>
      </div>}
      {tab === 'candidates' && <CandidateTable snapshot={snapshot} candidates={candidates} selectedCandidateId={selected.id} onSelectCandidate={onSelectCandidate} />}
      {tab === 'validation' && <>{validationIdentityConsistent && finalCandidate ? <><QuantGeneralizationPanel generalization={report.generalization} walkForward={report.walkForward} robustnessSensitivity={report.robustnessSensitivity} datasetQuality={report.datasetQuality ?? snapshot.dataset.quality} selectedCandidateName={candidateName(finalCandidate.name)} legacy={snapshot.dataset.contract === 'legacy-daily-v1'} /><section className="quant-report-findings"><h4>Final candidate findings</h4><p>{finalCandidate.verdictReason}</p>{finalCandidate.robustness.length > 0 ? <ul>{finalCandidate.robustness.map((finding) => <li key={finding}>{finding}</li>)}</ul> : <p>No additional final-candidate robustness findings were retained.</p>}</section>{selected.id !== finalCandidate.id && <section className="quant-report-findings"><h4>Alternative candidate</h4><p>{candidateName(selected.name)} retains its own training evidence only and does not inherit final candidate sealed-holdout, cross-window, cost-sensitivity, or parameter-neighborhood conclusions.</p></section>}</> : <div className="quant-report-empty-state"><strong>Validation evidence unavailable</strong><p>The authoritative final candidate identity is absent or conflicts with this report, so sealed-holdout and cross-window conclusions are withheld.</p></div>}</>}
      {tab === 'trades' && (selectedTrades.length > 0 ? <table className="quant-research-table"><caption>{selected.name} · retained training trades</caption><thead><tr><th>Entry</th><th>Exit</th><th>Return</th><th>Holding</th><th>Reason</th></tr></thead><tbody>{selectedTrades.map((trade) => <tr key={trade.id}><td>{trade.entryDate}</td><td>{trade.exitDate}</td><td>{metric(trade.returnPct, '%')}</td><td>{formatTradeHolding(trade)}</td><td>{trade.reason}</td></tr>)}</tbody></table> : <div className="quant-report-empty-state"><strong>No retained trades</strong><p>{candidateName(selected.name)} produced no persisted training trade records.</p></div>)}
      {tab === 'strategy' && <div className="quant-spec"><div><Badge tone="neutral">{selected.strategySpecVersion}</Badge><span>Read-only specification · not executable code</span></div><pre>{selected.strategySpec}</pre></div>}
      {tab === 'audit' && (snapshot.events.length > 0 ? <ol className="quant-safe-logs">{snapshot.events.map((event) => <li key={event.id}><time>{event.timestamp}</time><span>{event.safeSummary}</span></li>)}</ol> : <div className="quant-report-empty-state"><strong>No audit events</strong><p>This snapshot contains no retained run events.</p></div>)}
    </div>
    {exportCandidateId && <QuantReportExportDialog api={api} runId={snapshot.run.id} candidateId={exportCandidateId} finalCandidateId={terminalDecision?.finalCandidateId} onClose={() => { setExportCandidateId(null); requestAnimationFrame(() => exportButtonRef.current?.focus()); }} />}
  </section>;
}
