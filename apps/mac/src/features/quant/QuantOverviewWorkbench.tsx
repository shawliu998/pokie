import { useMemo, useState, type KeyboardEvent, type ReactNode } from 'react';
import type { DatasetSnapshot, QuantCommand, QuantNavDestination, QuantWorkspaceSnapshot } from '../../quant-domain';
import { QuantDecisionGate } from './QuantDecisionGate';
import { CandidateComparison, StrategyPerformanceChart } from './QuantStrategyLab';
import { presentPromotionDecision, presentResearchCopilot, presentStrategyScopeDecision, projectEvidenceFocusActions, type QuantCopilotActionKind, type QuantCopilotProjection, type QuantEvidenceFocusRequest } from './quant-presentation';

type WorkspaceTab = 'overview' | 'experiments' | 'analysis' | 'report';
const workspaceTabs: WorkspaceTab[] = ['overview', 'experiments', 'analysis', 'report'];

function formatPercent(value: number | undefined, digits = 1) {
  if (value === undefined || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

function formatEventTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${new Intl.DateTimeFormat('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }).format(date)} UTC`;
}

function runStateLabel(value: string) {
  if (value === 'waiting_for_review') return 'Review required';
  if (value === 'waiting_plan_approval') return 'Plan review';
  if (value === 'loading_data') return 'Verifying dataset';
  if (value === 'generating_candidates') return 'Preparing candidates';
  if (value === 'running_experiments') return 'Running experiments';
  if (value === 'repairing') return 'Repairing candidate';
  if (value === 'validating') return 'Validating evidence';
  if (value === 'generating_report') return 'Building report';
  return `${value[0]?.toUpperCase() ?? ''}${value.slice(1).replaceAll('_', ' ')}`;
}

const candidateFamilyLabels = {
  sma_crossover: 'Moving-average trend',
  rsi_mean_reversion: 'RSI mean reversion',
  breakout: 'Price breakout',
} as const;

const selectionObjectiveLabels = {
  risk_adjusted_return: 'Risk-adjusted return',
  total_return: 'Total return',
  drawdown_control: 'Drawdown control',
} as const;

function candidateFamilySummary(snapshot: QuantWorkspaceSnapshot) {
  const families = snapshot.researchPlan?.candidateFamilies ?? [];
  if (families.length === 0) return 'None — the request is outside the registered strategy boundary';
  return families.map((family) => candidateFamilyLabels[family]).join(' · ');
}

function StrategyScopeContract({ snapshot }: { snapshot: QuantWorkspaceSnapshot }) {
  if (!snapshot.researchPlan) return null;
  const scope = presentStrategyScopeDecision(snapshot.researchPlan);
  return <section className={`pq-strategy-scope is-${scope.status}`} aria-label={`Strategy scope: ${scope.label}`}>
    <header><strong>{scope.label}</strong><span>{scope.title}</span></header>
    <p>{scope.reason}</p>
    {scope.proxyDescription && <div className="pq-strategy-scope-proxy"><strong>Proxy</strong><span>{scope.proxyDescription}</span></div>}
    {scope.excludedBehaviors.length > 0 && <div className="pq-strategy-scope-exclusions">
      <strong>{scope.status === 'unsupported' ? 'Outside current capability' : 'Not included'}</strong>
      <ul>{scope.excludedBehaviors.map((behavior) => <li key={behavior}>{behavior}</li>)}</ul>
    </div>}
    {scope.requiresConfirmation && <p className="pq-strategy-scope-confirmation">
      {snapshot.run.mode === 'auto_research' ? 'Auto Research is paused for explicit confirmation.' : 'Explicit confirmation is required before experiments begin.'}
    </p>}
  </section>;
}

function validationStatusLabel(status: string | undefined) {
  if (!status || status === 'not_evaluated') return 'Pending';
  return `${status[0]?.toUpperCase()}${status.slice(1).replaceAll('_', ' ')}`;
}

const transientPhaseRows: Partial<Record<QuantWorkspaceSnapshot['run']['state'], readonly [string, string, string]>> = {
  loading_data: ['Scope and limits locked', 'Dataset verification', 'Benchmark generation'],
  generating_candidates: ['Dataset and benchmark ready', 'Candidate preparation', 'Bounded experiments'],
  generating_report: ['Validation evidence retained', 'Report assembly', 'Human review'],
};

function datasetQualityLabel(dataset: DatasetSnapshot) {
  if (!dataset.quality) return `Not checked · ${dataset.barCount.toLocaleString()} bars`;
  if (dataset.contract === 'market-v2') {
    return `${dataset.quality.status === 'accepted' ? 'Accepted' : 'Blocked'} · ${dataset.barCount.toLocaleString()} bars`;
  }
  const status = dataset.quality.status === 'passed' ? 'Verified' : dataset.quality.status === 'warning' ? 'Warning' : 'Blocked';
  return `${status} · ${dataset.quality.barCount.toLocaleString()} bars`;
}

function datasetQualityClass(dataset: DatasetSnapshot) {
  if (dataset.contract === 'market-v2') return dataset.quality.status === 'accepted' ? 'is-positive' : 'is-danger';
  if (dataset.quality?.status === 'passed') return 'is-positive';
  if (dataset.quality?.status === 'warning') return 'is-warning';
  if (dataset.quality?.status === 'blocked') return 'is-danger';
  return undefined;
}

function liveCandidateName(value: string) {
  return value.replace(/^Candidate [A-Z] · /, '');
}

function liveCandidateState(value: string) {
  return `${value[0]?.toUpperCase() ?? ''}${value.slice(1).replaceAll('_', ' ')}`;
}

export function ResearchCopilotContent({ projection, snapshot, recentEvents, evidenceFocusActions, busy, compact = false, mode = 'full', onAction, onAsk, onEvidenceFocus }: {
  projection: QuantCopilotProjection;
  snapshot: QuantWorkspaceSnapshot;
  recentEvents: QuantWorkspaceSnapshot['events'];
  evidenceFocusActions: QuantEvidenceFocusRequest[];
  busy: boolean;
  compact?: boolean;
  mode?: 'full' | 'live-decision';
  onAction: (kind: QuantCopilotActionKind, payload?: Record<string, unknown>) => void;
  onAsk: (question: string) => void;
  onEvidenceFocus: (request: QuantEvidenceFocusRequest) => void;
}) {
  const [question, setQuestion] = useState('');
  const [showPlanChange, setShowPlanChange] = useState(false);
  const [planChange, setPlanChange] = useState('');
  const liveDecision = mode === 'live-decision';
  const live = liveDecision ? snapshot.liveResearch : null;
  const current = live?.currentExperiment ?? null;
  const initialCandidates = live?.candidates.filter((candidate) => candidate.ordinal <= 2) ?? [];
  const candidateC = live?.candidates.find((candidate) => candidate.ordinal > 2);
  const retainedCandidateC = candidateC
    ? snapshot.candidates.find((candidate) => candidate.id === candidateC.id && candidate.evolution?.origin === 'training_feedback')
    : undefined;
  const candidateCEvolution = retainedCandidateC?.evolution;
  const currentRole = current
    ? current.ordinal <= 2
      ? `Initial hypothesis ${current.ordinal === 1 ? 'A' : 'B'}`
      : current.ordinal === 3
        ? candidateCEvolution ? 'Adaptation C' : 'Candidate C'
        : `Candidate ${current.ordinal}`
    : null;
  const currentTitle = current && currentRole
    ? `${currentRole} · ${liveCandidateName(current.name)}`
    : projection.current.title;
  const currentQuestion = current?.hypothesis ?? projection.current.question;
  const currentDetail = current
    ? `${current.parameters || 'Parameters are being prepared'} · ${liveCandidateState(current.state)}`
    : projection.current.detail;
  let nextTitle = liveDecision ? 'Wait for the next retained decision' : '';
  let nextDetail = projection.next.detail;
  if (liveDecision && candidateC && candidateCEvolution?.changeRationale && candidateCEvolution.feedbackReferenceCandidateName) {
    nextTitle = `${candidateC.state === 'completed' ? 'Candidate C changed the test' : 'Candidate C is the next test'} · ${liveCandidateName(candidateC.name)}`;
    nextDetail = `The train-only observation from ${liveCandidateName(candidateCEvolution.feedbackReferenceCandidateName)} drove this adaptation. ${candidateCEvolution.changeRationale} ${candidateC.hypothesis} ${projection.next.detail}`;
  } else if (liveDecision && candidateC) {
    nextTitle = `${candidateC.state === 'completed' ? 'Candidate C is retained' : 'Candidate C is being tested'} · ${liveCandidateName(candidateC.name)}`;
    nextDetail = `The exact retained reason for Candidate C is not available in this snapshot. ${candidateC.hypothesis} ${projection.next.detail}`;
  } else if (liveDecision && initialCandidates.length >= 2) {
    nextTitle = 'Compare the initial A/B hypotheses';
  } else if (liveDecision && initialCandidates.length === 1) {
    nextTitle = 'Complete the initial A/B hypotheses';
  } else if (liveDecision && snapshot.run.state === 'queued') {
    nextTitle = 'Wait for bounded execution';
  }
  const idPrefix = liveDecision ? 'pq-live-agent' : compact ? 'pq-compact' : 'pq-rail';
  return <div className={`pq-copilot-content${compact ? ' is-compact' : ''}${liveDecision ? ' is-live-decision' : ''}`}>
    <div className="pq-copilot-sections">
      <section className="pq-copilot-section is-current" aria-labelledby={`${idPrefix}-current`}>
        <span id={`${idPrefix}-current`}>Current</span>
        <h2>{currentTitle}</h2>
        <p className="pq-copilot-question">{currentQuestion}</p>
        <small>{currentDetail}</small>
        {liveDecision && initialCandidates.length > 0 && <dl className="pq-agent-hypotheses" aria-label="Initial hypotheses">
          {initialCandidates.map((candidate) => <div key={candidate.id}><dt>Initial hypothesis {candidate.ordinal === 1 ? 'A' : 'B'}</dt><dd>{liveCandidateName(candidate.name)} · {liveCandidateState(candidate.state)}</dd></div>)}
        </dl>}
      </section>
      <section className={`pq-copilot-section is-observation is-${projection.observation.tone}`} aria-labelledby={`${idPrefix}-observation`}>
        <span id={`${idPrefix}-observation`}>Observation</span>
        <h2>{projection.observation.title}</h2>
        <p>{projection.observation.detail}</p>
        {liveDecision && live?.latestResult?.metrics && <small>Latest retained training evidence · Experiment {live.latestResult.ordinal}</small>}
      </section>
      <section className="pq-copilot-section is-next" aria-labelledby={`${idPrefix}-next`}>
        <span id={`${idPrefix}-next`}>Next</span>
        {liveDecision && <h2>{nextTitle}</h2>}
        {!liveDecision && snapshot.run.state === 'waiting_plan_approval' && snapshot.researchPlan && <>
          <h2>Research contract</h2>
          {snapshot.researchPlan.objectiveSummary && <p>{snapshot.researchPlan.objectiveSummary}</p>}
          <StrategyScopeContract snapshot={snapshot} />
          <dl className="quant-report-decision-path">
            <div><dt>Dataset</dt><dd>{snapshot.dataset.symbol} · {snapshot.scope.interval}</dd></div>
            <div><dt>Range</dt><dd>{snapshot.scope.dateRange.start} — {snapshot.scope.dateRange.end}</dd></div>
            <div><dt>Execution costs</dt><dd>{snapshot.kernelCheck.feeRateBps} bps fee + {snapshot.kernelCheck.slippageRateBps} bps slippage per fill</dd></div>
            <div><dt>Candidate families</dt><dd>{candidateFamilySummary(snapshot)}</dd></div>
            <div><dt>Comparison objective</dt><dd>{selectionObjectiveLabels[snapshot.researchPlan.selectionObjective]}</dd></div>
            <div><dt>Completion criteria</dt><dd>{snapshot.researchPlan.completionCriteria.join(' ')}</dd></div>
            <div><dt>Budgets</dt><dd>{snapshot.run.maxAgentIterations} Agent actions · {snapshot.limits.maxExperiments} experiments · {snapshot.limits.maxRepairAttempts} repairs per experiment</dd></div>
          </dl>
        </>}
        <p>{nextDetail}</p>
        {projection.next.actions.length > 0 && <div className="pq-copilot-actions">{projection.next.actions.map((action) => <button key={action.kind} className={action.tone === 'primary' ? 'is-primary' : undefined} disabled={busy} onClick={() => action.kind === 'request_plan_changes' ? setShowPlanChange(true) : onAction(action.kind)}>{busy ? 'Working…' : action.label}</button>)}</div>}
        {!liveDecision && evidenceFocusActions.length > 0 && <><p><strong>Retained evidence</strong></p><div className="pq-copilot-actions">{evidenceFocusActions.map((action) => <button key={`${action.destination}-${action.target}-${'tradeId' in action ? action.tradeId ?? '' : ''}`} onClick={() => onEvidenceFocus(action)}>{action.label}</button>)}</div></>}
        {showPlanChange && <form className="pq-plan-change-form" onSubmit={(event) => { event.preventDefault(); const changeRequest = planChange.trim(); if (!changeRequest || busy) return; onAction('request_plan_changes', { changeRequest }); }}>
          <label htmlFor={`${idPrefix}-plan-change`}>What should change in the plan?</label>
          <textarea id={`${idPrefix}-plan-change`} value={planChange} maxLength={1000} disabled={busy} autoFocus onChange={(event) => setPlanChange(event.target.value)} />
          <div><button type="button" disabled={busy} onClick={() => { setShowPlanChange(false); setPlanChange(''); }}>Cancel</button><button type="submit" className="is-primary" disabled={!planChange.trim() || busy}>{busy ? 'Working…' : 'Generate revised plan'}</button></div>
        </form>}
      </section>
    </div>
    {!liveDecision && <details className="pq-copilot-details">
      <summary>Run details</summary>
      <dl><div><dt>State</dt><dd>{runStateLabel(snapshot.run.state)}</dd></div><div><dt>Plan</dt><dd>{snapshot.plan.filter((step) => step.status === 'completed').length} / {snapshot.plan.length} complete</dd></div>{snapshot.researchPlan && <><div><dt>Scope</dt><dd>{presentStrategyScopeDecision(snapshot.researchPlan).label}</dd></div><div><dt>Strategies</dt><dd>{candidateFamilySummary(snapshot)}</dd></div><div><dt>Comparison priority</dt><dd>{selectionObjectiveLabels[snapshot.researchPlan.selectionObjective]}</dd></div><div><dt>Done when</dt><dd>{snapshot.researchPlan.completionCriteria.join(' ')}</dd></div></>}<div><dt>Dataset</dt><dd>{snapshot.dataset.symbol} · {snapshot.scope.interval}</dd></div><div><dt>Cadence</dt><dd>{snapshot.scope.interval} · {snapshot.kernelCheck.periodsPerYear?.toLocaleString() ?? 'PPY unavailable'} PPY</dd></div><div><dt>Range</dt><dd>{snapshot.scope.dateRange.start} — {snapshot.scope.dateRange.end}{snapshot.scope.interval === '1D' ? '' : ' UTC'}</dd></div></dl>
      {recentEvents.length > 0 && <div className="pq-copilot-events"><strong>Recent activity</strong><ol>{recentEvents.map((event) => <li key={event.id}><time dateTime={event.timestamp}>{formatEventTime(event.timestamp)}</time><span>{event.safeSummary}</span></li>)}</ol></div>}
    </details>}
    {!liveDecision && projection.readOnly && <p className="pq-copilot-readonly">Historical evidence is read-only.</p>}
    {!liveDecision && projection.canAsk && <form className="pq-copilot-composer" aria-busy={busy} onSubmit={(event) => { event.preventDefault(); if (!question.trim() || busy) return; onAsk(question.trim()); setQuestion(''); }}>
      <textarea aria-label="Ask about this run" placeholder="Ask about this run…" value={question} maxLength={2000} disabled={busy} onChange={(event) => setQuestion(event.target.value)} />
      <div><span>Ask about retained evidence</span><button type="submit" disabled={!question.trim() || busy}>{busy ? 'Working…' : 'Ask'}</button></div>
    </form>}
  </div>;
}

export function QuantOverviewWorkbench({
  snapshot,
  activeTab,
  onTabChange,
  onRunResearch,
  onOpenAnalysis,
  onOpenReport,
  onContinueResearch,
  onReturnLatest,
  selectedCandidateId,
  onSelectCandidate,
  onCommand,
  onEvidenceFocus,
  busy = false,
  isHistorical = false,
  compactLayout = false,
  children,
}: {
  snapshot: QuantWorkspaceSnapshot;
  activeTab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  onRunResearch: () => void;
  onOpenAnalysis: () => void;
  onOpenReport: () => void;
  onContinueResearch?: () => void;
  onReturnLatest?: () => void;
  selectedCandidateId: string;
  onSelectCandidate: (id: string) => void;
  onCommand: (command: QuantCommand, payload?: Record<string, unknown>) => void;
  onEvidenceFocus?: (request: QuantEvidenceFocusRequest) => void;
  busy?: boolean;
  isHistorical?: boolean;
  compactLayout?: boolean;
  children?: ReactNode;
}) {
  const retained = snapshot.candidates.find((candidate) => candidate.verdict === 'promising');
  const featuredCandidate = retained ?? snapshot.candidates.reduce<(typeof snapshot.candidates)[number] | undefined>((best, candidate) => {
    if (!best || candidate.metrics.sharpe > best.metrics.sharpe) return candidate;
    return best;
  }, undefined);
  const selectedCandidate = snapshot.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? featuredCandidate;
  const walkForward = snapshot.report?.walkForward;
  const holdout = snapshot.run.state === 'completed' || snapshot.run.state === 'waiting_for_review'
    ? snapshot.report?.generalization
    : undefined;
  const decision = useMemo(() => presentPromotionDecision(snapshot), [snapshot]);
  const [performanceView, setPerformanceView] = useState<'equity' | 'drawdown'>('equity');
  const recentEvents = snapshot.events.slice(-4).reverse();
  const transientRows = transientPhaseRows[snapshot.run.state];
  const copilot = useMemo(() => presentResearchCopilot(snapshot, { selectedCandidateId, isHistorical }), [isHistorical, selectedCandidateId, snapshot]);
  const evidenceFocusActions = useMemo(() => onEvidenceFocus ? projectEvidenceFocusActions(snapshot, selectedCandidateId) : [], [onEvidenceFocus, selectedCandidateId, snapshot]);
  const canAsk = copilot.canAsk;
  const terminal = ['completed', 'failed', 'cancelled'].includes(snapshot.run.state);
  const noViableCandidate = snapshot.run.state === 'completed' && snapshot.candidates.length > 0 && snapshot.candidates.every((candidate) => candidate.verdict !== 'promising');
  const showResults = terminal || snapshot.run.state === 'waiting_for_review';
  const hasPerformance = Boolean(selectedCandidate && snapshot.performanceSeries.some((series) => series.id === selectedCandidate.id && series.points.length > 1));
  const handleCopilotAction = (kind: QuantCopilotActionKind, payload?: Record<string, unknown>) => {
    if (kind === 'open_analysis') onOpenAnalysis();
    else if (kind === 'open_report') onOpenReport();
    else if (kind === 'new_research') onRunResearch();
    else if (kind === 'continue_research') onContinueResearch?.();
    else if (kind === 'return_latest') onReturnLatest?.();
    else if (payload) onCommand(kind, payload);
    else onCommand(kind);
  };
  const overviewDecision = snapshot.run.state === 'failed'
    ? { ...decision, title: 'Research stopped before a decision', summary: 'No promotion decision was produced from the completed evidence.', nextStep: 'Review recent activity, then start a new research run.' }
    : snapshot.run.state === 'cancelled'
      ? { ...decision, nextStep: 'Review the retained work or start a new research run.' }
      : noViableCandidate
        ? { ...decision, nextStep: 'Revise the hypothesis or candidate constraints, then start new research.' }
        : snapshot.run.state === 'waiting_for_review'
          ? { ...decision, summary: 'The completed evidence is ready for a human decision.', nextStep: 'Review the strategy report and validation findings.' }
          : snapshot.run.state === 'completed' && selectedCandidate
            ? { ...decision, title: `${selectedCandidate.name.replace(/^Candidate [A-Z] · /, '')} · ${decision.title}` }
            : decision;
  const onTabKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const current = workspaceTabs.indexOf(activeTab);
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % workspaceTabs.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + workspaceTabs.length) % workspaceTabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = workspaceTabs.length - 1;
    else return;
    event.preventDefault();
    const nextTab = workspaceTabs[next] ?? activeTab;
    onTabChange(nextTab);
    requestAnimationFrame(() => document.getElementById(`pq-workspace-tab-${nextTab}`)?.focus());
  };

  return <section className={`pq-workbench${terminal ? ' is-terminal' : ''}${canAsk ? ' has-interactive-copilot' : ' is-context'}`} aria-label="Research workspace">
    <header className="pq-workbench-header">
      <h1>{snapshot.scope.symbol} Research</h1>
      <nav aria-label="Research views" role="tablist" onKeyDown={onTabKeyDown}>
        {workspaceTabs.map((tab) => <button key={tab} role="tab" id={`pq-workspace-tab-${tab}`} aria-controls={`pq-workspace-panel-${tab}`} aria-selected={activeTab === tab} tabIndex={activeTab === tab ? 0 : -1} onClick={() => onTabChange(tab)}>{(tab[0] ?? '').toUpperCase() + tab.slice(1)}</button>)}
      </nav>
    </header>
    {activeTab === 'overview' ? <div className="pq-overview-grid" role="tabpanel" id="pq-workspace-panel-overview" aria-labelledby="pq-workspace-tab-overview">
      <main className="pq-overview-main">
        <div className="pq-context-bar">
          <strong>{snapshot.scope.symbol}</strong>
          <span>{snapshot.scope.market}</span>
          <span>{snapshot.scope.interval}</span>
          <span>{snapshot.scope.dateRange.start} — {snapshot.scope.dateRange.end}</span>
          {snapshot.researchMemory && <span>Prior research: {snapshot.researchMemory.sourceRunCount} runs · {snapshot.researchMemory.testedCandidateCount} strategies considered</span>}
        </div>
        <div className="pq-overview-content">
          {compactLayout && <ResearchCopilotContent compact projection={copilot} snapshot={snapshot} recentEvents={recentEvents} evidenceFocusActions={evidenceFocusActions} busy={busy} onAction={handleCopilotAction} onAsk={(value) => onCommand('ask', { question: value })} onEvidenceFocus={onEvidenceFocus ?? (() => undefined)} />}
          <QuantDecisionGate decision={overviewDecision} className="is-overview" />
          {transientRows && <section className="pq-transient-phase" aria-label="Current run progress" aria-live="polite">
            <header><strong>Run progress</strong><span>Live</span></header>
            <ol>
              <li><span>Completed</span><strong>{transientRows[0]}</strong></li>
              <li className="is-active"><span>Current</span><strong>{transientRows[1]}</strong></li>
              <li><span>Next</span><strong>{transientRows[2]}</strong></li>
            </ol>
          </section>}
          {showResults && <div className="pq-results-overview">
            <section className={`pq-results-performance${hasPerformance ? '' : ' is-empty'}`} aria-labelledby="pq-results-performance-heading">
              <header><div><h2 id="pq-results-performance-heading">Strategy vs benchmark</h2><p>{selectedCandidate ? selectedCandidate.name.replace(/^Candidate [A-Z] · /, '') : 'No selected strategy'}</p></div>{hasPerformance ? <div className="pq-results-view-tabs" role="tablist" aria-label="Overview performance view">
                {(['equity', 'drawdown'] as const).map((view) => <button key={view} role="tab" aria-selected={performanceView === view} onClick={() => setPerformanceView(view)}>{view === 'equity' ? 'Equity' : 'Drawdown'}</button>)}
              </div> : <span className="pq-results-unavailable">Performance series unavailable</span>}</header>
              <div className="pq-results-chart">{selectedCandidate ? <StrategyPerformanceChart snapshot={snapshot} selectedCandidateId={selectedCandidate.id} view={performanceView} /> : <div className="pq-strategy-empty"><strong>No strategy result</strong><p>This run ended before a candidate result was retained.</p></div>}</div>
            </section>
            <dl className="pq-key-comparison" aria-label="Key strategy comparison">
              <div><dt>Annual return</dt><dd>{formatPercent(selectedCandidate?.metrics.annualizedReturn)}</dd></div>
              <div><dt>Sharpe</dt><dd>{selectedCandidate?.metrics.sharpe.toFixed(2) ?? '—'}</dd></div>
              <div><dt>Max drawdown</dt><dd>{formatPercent(selectedCandidate?.metrics.maxDrawdown)}</dd></div>
              <div><dt>Trades</dt><dd>{selectedCandidate?.metrics.trades ?? '—'}</dd></div>
              <div><dt>Vs benchmark</dt><dd>{formatPercent(selectedCandidate && snapshot.benchmark ? selectedCandidate.metrics.annualizedReturn - snapshot.benchmark.annualizedReturn : undefined)}</dd></div>
            </dl>
            <section className="pq-validation-summary" aria-labelledby="pq-validation-summary-heading">
              <header><h2 id="pq-validation-summary-heading">Validation and decision</h2><span>{hasPerformance ? 'Performance series retained' : 'Performance series unavailable'}</span></header>
              <dl><div><dt>Sealed holdout</dt><dd className={`is-${holdout?.status ?? 'pending'}`}>{validationStatusLabel(holdout?.status)}</dd></div><div><dt>Positive-return folds</dt><dd>{walkForward ? `${walkForward.aggregate.candidatePositiveReturnFolds} / ${walkForward.foldCount}` : '—'}</dd></div><div><dt>Holdout annual return</dt><dd>{formatPercent(holdout?.holdout?.candidate.annualizedReturn)}</dd></div><div><dt>Decision</dt><dd>{decision.label}</dd></div></dl>
            </section>
            {snapshot.candidates.length > 0 && <CandidateComparison snapshot={snapshot} selectedCandidateId={selectedCandidate?.id ?? ''} onSelectCandidate={onSelectCandidate} variant="snapshot" />}
          </div>}
        </div>
      </main>
      {!compactLayout && <aside className={`pq-copilot ${canAsk ? 'is-interactive' : 'is-context'}`} aria-label="Research Copilot">
        <header><strong>Research Copilot</strong><span>{snapshot.scope.symbol} · Overview</span></header>
        <ResearchCopilotContent projection={copilot} snapshot={snapshot} recentEvents={recentEvents} evidenceFocusActions={evidenceFocusActions} busy={busy} onAction={handleCopilotAction} onAsk={(value) => onCommand('ask', { question: value })} onEvidenceFocus={onEvidenceFocus ?? (() => undefined)} />
      </aside>}
    </div> : <div className="pq-existing-view" role="tabpanel" id={`pq-workspace-panel-${activeTab}`} aria-labelledby={`pq-workspace-tab-${activeTab}`}>{children}</div>}
  </section>;
}

export type { WorkspaceTab };

export function QuantUtilityFrame({ destination, snapshot, dataset = snapshot.dataset, children, dataImporting = false, dataPreviewing = false, onInspectDataset }: {
  destination: Exclude<QuantNavDestination, 'projects'>;
  snapshot: QuantWorkspaceSnapshot;
  dataset?: DatasetSnapshot;
  children: ReactNode;
  dataImporting?: boolean;
  dataPreviewing?: boolean;
  onInspectDataset?: () => void;
}) {
  const title = destination === 'new_research' ? 'New research' : destination === 'runs' ? 'Runs' : destination === 'data' ? 'Data directory' : 'Runtime & policy';
  const singleColumn = destination === 'settings' || destination === 'runs';
  const hideCopilot = singleColumn || (destination === 'data' && dataPreviewing);
  return <section className={`pq-utility-frame is-${destination}${singleColumn ? ' is-single' : ''}${destination === 'data' && dataPreviewing ? ' is-data-preview' : ''}`} aria-label={title}>
    <header><strong>{title}</strong>{!hideCopilot && <span>{destination === 'data' ? dataImporting ? 'Import guide' : 'Dataset inspector' : 'Preflight review'}</span>}</header>
    <div className="pq-utility-grid">
      <div className="pq-utility-center">{children}</div>
      {!hideCopilot && <aside className="pq-utility-copilot" aria-label={destination === 'data' ? 'Dataset inspector' : 'Research preflight'}>
        <div className="pq-utility-scroll">
          <span className="pq-copilot-kicker">{destination === 'data' ? dataImporting ? 'Data import' : 'Selected dataset' : 'Research preflight'}</span>
          <h2>{destination === 'data' ? dataImporting ? 'Validate before selection' : `${dataset.symbol} · ${dataset.interval}` : 'Review the execution boundary'}</h2>
          <p>{destination === 'data' ? dataImporting ? 'Provider responses and uploads are validated before they can replace the selected research dataset.' : `${dataset.name} is selected in the local catalog. Inspect its retained identity before using it in a new run.` : 'A new run will pin this dataset, objective and validation policy before the Agent starts.'}</p>
          {destination === 'data' ? dataImporting ? <><section className="pq-utility-card"><strong>Import contract</strong><dl><div><dt>Execution</dt><dd>Server owned</dd></div><div><dt>Validation</dt><dd>Required</dd></div><div><dt>Result</dt><dd>Immutable version</dd></div></dl></section><p className="pq-utility-guidance">The current dataset remains selected until validation succeeds.</p></> : <><section className="pq-utility-card"><strong>Immutable identity</strong><dl><div><dt>Digest</dt><dd><code>{dataset.digest.slice(0, 16)}…</code></dd></div><div><dt>Schema</dt><dd>{dataset.schemaVersion}</dd></div></dl></section><section className="pq-utility-card"><strong>Provenance</strong><p>{dataset.source ? `${dataset.source.sourceName} · ${dataset.interval} · ${dataset.contract === 'market-v2' ? dataset.timeZone : dataset.source.timeZone ?? 'timezone unavailable'}` : 'Source metadata unavailable'}</p>{onInspectDataset && <button onClick={onInspectDataset}>Open metadata record</button>}</section></> : <><section className="pq-utility-facts" aria-label="Research boundary"><dl><div><dt>Dataset</dt><dd>{dataset.symbol} · {dataset.interval}</dd></div><div><dt>Data quality</dt><dd className={datasetQualityClass(dataset)}>{datasetQualityLabel(dataset)}</dd></div><div><dt>Validation</dt><dd>Expanding windows</dd></div><div><dt>Holdout</dt><dd className="is-warning">Chronological · sealed</dd></div><div><dt>Promotion</dt><dd>Human review</dd></div></dl></section><p className="pq-utility-guidance">Describe a measurable market outcome. Strategy selection remains the Agent’s task.</p></>}
        </div>
      </aside>}
    </div>
  </section>;
}
