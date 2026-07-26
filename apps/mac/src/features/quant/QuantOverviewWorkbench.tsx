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
      {'Review this plan before Qurio runs experiments.'}
    </p>}
  </section>;
}

function ResearchPlanForApproval({ snapshot }: { snapshot: QuantWorkspaceSnapshot }) {
  if (snapshot.run.state !== 'waiting_plan_approval' || !snapshot.researchPlan) return null;
  return <section className="pq-plan-review" aria-label="Research plan awaiting approval">
    <header><div><span>Plan review</span><h2>Plan for approval</h2></div><span>{snapshot.dataset.symbol} · {snapshot.scope.interval}</span></header>
    {snapshot.researchPlan.objectiveSummary && <p className="pq-plan-review-objective">{snapshot.researchPlan.objectiveSummary}</p>}
    <StrategyScopeContract snapshot={snapshot} />
    <dl className="quant-report-decision-path">
      <div><dt>Dataset</dt><dd>{snapshot.dataset.symbol} · {snapshot.scope.interval}</dd></div>
      <div><dt>Range</dt><dd>{snapshot.scope.dateRange.start} — {snapshot.scope.dateRange.end}</dd></div>
      <div><dt>Execution costs</dt><dd>{snapshot.kernelCheck.feeRateBps} bps fee + {snapshot.kernelCheck.slippageRateBps} bps slippage per fill</dd></div>
      <div><dt>Candidate families</dt><dd>{candidateFamilySummary(snapshot)}</dd></div>
      <div><dt>Comparison objective</dt><dd>{selectionObjectiveLabels[snapshot.researchPlan.selectionObjective]}</dd></div>
      <div><dt>Completion criteria</dt><dd>{snapshot.researchPlan.completionCriteria.join(' ')}</dd></div>
      {snapshot.researchMemory && <div><dt>Prior-work constraint</dt><dd>{snapshot.researchMemory.sourceRunCount} same-evidence runs · {snapshot.researchMemory.testedCandidateCount} exact strategies. Approved execution excludes the same template + parameters; prior holdout evidence is not reused.</dd></div>}
      <div><dt>Budgets</dt><dd>{snapshot.run.maxAgentIterations} Agent actions · {snapshot.limits.maxExperiments} experiments · {snapshot.limits.maxRepairAttempts} repairs per experiment</dd></div>
    </dl>
  </section>;
}

function ResearchLaunchPanel({ snapshot, busy, onGeneratePlan, onEditObjective }: {
  snapshot: QuantWorkspaceSnapshot;
  busy: boolean;
  onGeneratePlan: () => void;
  onEditObjective: () => void;
}) {
  const isPlanning = snapshot.run.state === 'planning';
  return <section className="pq-research-launch" aria-labelledby="pq-research-launch-title">
    <span className="pq-research-launch-kicker">{isPlanning ? 'Preparing plan' : 'Ready to plan'}</span>
    <h2 id="pq-research-launch-title">{isPlanning ? 'Generating the research plan' : 'Generate the research plan'}</h2>
    <p className="pq-research-launch-objective">{snapshot.project.goal}</p>
    <dl className="pq-research-launch-facts">
      <div><dt>Market</dt><dd>{snapshot.scope.symbol} · {snapshot.scope.market} · {snapshot.scope.interval}</dd></div>
      <div><dt>Research period</dt><dd>{snapshot.scope.dateRange.start} — {snapshot.scope.dateRange.end}</dd></div>
      <div><dt>Experiment budget</dt><dd>{snapshot.limits.maxExperiments} candidates · {snapshot.limits.maxRepairAttempts} repairs each</dd></div>
      <div><dt>Execution costs</dt><dd>{snapshot.kernelCheck.feeRateBps} bps fee · {snapshot.kernelCheck.slippageRateBps} bps slippage</dd></div>
    </dl>
    <div className="pq-research-launch-actions">
      {!isPlanning && <button className="pq-primary-button" disabled={busy} onClick={onGeneratePlan}>{busy ? 'Generating plan…' : 'Generate plan'}</button>}
      {!isPlanning && <button className="pq-text-action" disabled={busy} onClick={onEditObjective}>Edit objective</button>}
      {isPlanning && <p role="status">Qurio is turning the objective into a bounded experiment and validation plan.</p>}
    </div>
    <p className="pq-research-launch-note">You will review the candidate families, comparison objective and limits before any experiment runs.</p>
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

type ResearchEvidenceAnswer = {
  title: string;
  detail: string;
};

function retainedCandidateName(value: string) {
  return value.replace(/^Candidate [A-Z] · /, '');
}

function answerFromRetainedResearch(snapshot: QuantWorkspaceSnapshot, question: string): ResearchEvidenceAnswer {
  const decision = presentPromotionDecision(snapshot);
  const selectedCandidateId = snapshot.report?.selectionDecision?.selectedCandidateId
    ?? snapshot.report?.generalization?.selectedCandidateId;
  const selected = snapshot.candidates.find((candidate) => candidate.id === selectedCandidateId);
  if (/(predict|forecast|tomorrow|next price|涨|跌|预测|明天)/i.test(question)) {
    return {
      title: 'Qurio does not forecast the next price',
      detail: `This workspace compares bounded historical strategy evidence for ${snapshot.dataset.symbol} · ${snapshot.scope.interval}. It does not produce a directional market call or trading recommendation.`,
    };
  }
  if (/(holdout|validation|out.of.sample|样本外|验证)/i.test(question)) {
    const generalization = snapshot.report?.generalization;
    return generalization
      ? {
        title: `Sealed holdout · ${validationStatusLabel(generalization.status)}`,
        detail: generalization.reason || decision.summary,
      }
      : {
        title: 'Sealed holdout is not available yet',
        detail: 'Qurio will not treat training comparison evidence as a final validation result.',
      };
  }
  if (/(why|select|choice|chosen|选择|为什么)/i.test(question)) {
    return selected
      ? {
        title: `Final training choice · ${retainedCandidateName(selected.name)}`,
        detail: selected.evolution?.selectionReason
          ?? snapshot.report?.selectionDecision?.reason
          ?? 'The retained report does not include a more specific selection reason.',
      }
      : {
        title: 'No authoritative final choice',
        detail: 'The retained selection and validation identities do not yet support one final candidate.',
      };
  }
  if (/(weak|risk|drawdown|problem|failed|弱点|风险|回撤|失败)/i.test(question)) {
    return selected
      ? {
        title: `${retainedCandidateName(selected.name)} · retained risk`,
        detail: `Training max drawdown ${formatPercent(selected.metrics.maxDrawdown)} with ${selected.metrics.trades} closed trades. ${snapshot.report?.generalization?.reason ?? 'No sealed-holdout weakness has been retained yet.'}`,
      }
      : {
        title: decision.title,
        detail: decision.summary,
      };
  }
  if (/(next|refine|change|continue|下一步|改进|继续)/i.test(question)) {
    return {
      title: 'Recommended next research action',
      detail: decision.nextStep,
    };
  }
  return {
    title: projectionAnswerTitle(snapshot),
    detail: `${snapshot.project.goal} Current evidence: ${decision.summary} Next: ${decision.nextStep}`,
  };
}

function projectionAnswerTitle(snapshot: QuantWorkspaceSnapshot) {
  if (snapshot.run.state === 'completed') return 'Research conclusion';
  if (snapshot.run.state === 'failed' || snapshot.run.state === 'cancelled') return 'Run outcome';
  return 'Current research state';
}

export function ResearchCopilotContent({ projection, snapshot, recentEvents, evidenceFocusActions, busy, compact = false, mode = 'full', onAction, onEvidenceFocus }: {
  projection: QuantCopilotProjection;
  snapshot: QuantWorkspaceSnapshot;
  recentEvents: QuantWorkspaceSnapshot['events'];
  evidenceFocusActions: QuantEvidenceFocusRequest[];
  busy: boolean;
  compact?: boolean;
  mode?: 'full' | 'live-decision';
  onAction: (kind: QuantCopilotActionKind, payload?: Record<string, unknown>) => void;
  onEvidenceFocus: (request: QuantEvidenceFocusRequest) => void;
}) {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<ResearchEvidenceAnswer | null>(null);
  const [showPlanChange, setShowPlanChange] = useState(false);
  const [planChange, setPlanChange] = useState('');
  const liveDecision = mode === 'live-decision';
  const live = liveDecision ? snapshot.liveResearch : null;
  const current = live?.currentExperiment ?? null;
  const initialCandidates = live?.candidates.filter((candidate) => candidate.ordinal <= 2) ?? [];
  const candidateC = live?.candidates.find((candidate) => candidate.ordinal === 3);
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
  if (liveDecision) {
    const now = current ?? live?.latestResult ?? null;
    const nowRetained = now ? snapshot.candidates.find((candidate) => candidate.id === now.id) : undefined;
    const nowEvolution = nowRetained?.evolution?.origin === 'training_feedback' ? nowRetained.evolution : undefined;
    const nowRole = now
      ? now.ordinal === 1
        ? 'Initial hypothesis A'
        : now.ordinal === 2
          ? 'Initial hypothesis B'
          : nowEvolution
            ? 'Agent adaptation C'
            : `Candidate ${now.ordinal}`
      : 'Research run';
    const whyCandidate = candidateC ?? current;
    const whyRetained = whyCandidate
      ? snapshot.candidates.find((candidate) => candidate.id === whyCandidate.id)
      : undefined;
    const whyEvolution = whyRetained?.evolution?.origin === 'training_feedback'
      ? whyRetained.evolution
      : undefined;
    const whyTitle = whyCandidate
      ? `${whyCandidate.ordinal > 2 && whyEvolution ? 'Agent adaptation C' : liveCandidateName(whyCandidate.name)} · ${liveCandidateState(whyCandidate.state)}`
      : nextTitle;
    const whyDetail = whyEvolution?.changeRationale
      ? `${whyEvolution.feedbackReferenceCandidateName ? `Based on ${liveCandidateName(whyEvolution.feedbackReferenceCandidateName)}. ` : ''}${whyEvolution.changeRationale}`
      : whyCandidate?.hypothesis ?? projection.next.detail;
    const completedExperiments = live?.candidates.filter((candidate) => candidate.state === 'completed').length ?? 0;
    const remainingExperiments = Math.max(0, snapshot.limits.maxExperiments - snapshot.run.usedExperiments);
    const evidenceReference = whyEvolution?.feedbackReferenceCandidateName
      ? `Training comparison · ${liveCandidateName(whyEvolution.feedbackReferenceCandidateName)} supplied the retained observation`
      : live?.latestResult
        ? `Latest retained training result · Experiment ${live.latestResult.ordinal}`
        : 'No completed training result has been retained yet';
    return <div className="pq-live-memo" aria-label="Qurio research memo">
      <span className="pq-live-memo-kicker">Qurio memo</span>
      <section aria-labelledby={`${idPrefix}-now`}>
        <span id={`${idPrefix}-now`}>Now</span>
        <h2>{now ? `${nowRole} · ${liveCandidateName(now.name)}` : projection.current.title}</h2>
        <p>{now ? liveCandidateState(now.state) : projection.current.detail}</p>
      </section>
      <section aria-labelledby={`${idPrefix}-observation`}>
        <span id={`${idPrefix}-observation`}>Material observation</span>
        <h2>{projection.observation.title}</h2>
        <p>{projection.observation.detail}</p>
        <small>{evidenceReference}</small>
      </section>
      <section aria-labelledby={`${idPrefix}-why`}>
        <span id={`${idPrefix}-why`}>Why this experiment</span>
        <h2>{whyTitle}</h2>
        <p>{whyDetail}</p>
      </section>
      <footer>
        <span>{completedExperiments} complete · {remainingExperiments} experiment{remainingExperiments === 1 ? '' : 's'} remaining</span>
        <small>{Math.max(0, snapshot.run.maxAgentIterations - snapshot.run.agentIteration)} Agent actions remain inside the approved plan</small>
      </footer>
      {projection.next.actions.length > 0 && <div className="pq-copilot-actions">{projection.next.actions.map((action) => <button key={action.kind} className={action.tone === 'primary' ? 'is-primary' : undefined} disabled={busy} onClick={() => onAction(action.kind)}>{busy ? 'Working…' : action.label}</button>)}</div>}
    </div>;
  }
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
      <dl><div><dt>State</dt><dd>{runStateLabel(snapshot.run.state)}</dd></div><div><dt>Plan</dt><dd>{snapshot.plan.filter((step) => step.status === 'completed').length} / {snapshot.plan.length} complete</dd></div><div><dt>Dataset</dt><dd>{snapshot.dataset.symbol} · {snapshot.scope.interval}</dd></div><div><dt>Cadence</dt><dd>{snapshot.scope.interval} · {snapshot.kernelCheck.periodsPerYear?.toLocaleString() ?? 'PPY unavailable'} PPY</dd></div><div><dt>Range</dt><dd>{snapshot.scope.dateRange.start} — {snapshot.scope.dateRange.end}{snapshot.scope.interval === '1D' ? '' : ' UTC'}</dd></div></dl>
      {recentEvents.length > 0 && <div className="pq-copilot-events"><strong>Recent activity</strong><ol>{recentEvents.map((event) => <li key={event.id}><time dateTime={event.timestamp}>{formatEventTime(event.timestamp)}</time><span>{event.safeSummary}</span></li>)}</ol></div>}
    </details>}
    {!liveDecision && projection.readOnly && <p className="pq-copilot-readonly">Historical evidence is read-only.</p>}
    {!liveDecision && answer && <section className="pq-copilot-answer" aria-live="polite" aria-label="Qurio evidence answer">
      <span>Qurio answer</span>
      <strong>{answer.title}</strong>
      <p>{answer.detail}</p>
    </section>}
    {!liveDecision && <form className="pq-copilot-composer" aria-busy={busy} onSubmit={(event) => {
      event.preventDefault();
      const submitted = question.trim();
      if (!submitted || busy) return;
      setAnswer(answerFromRetainedResearch(snapshot, submitted));
      setQuestion('');
    }}>
      <label htmlFor={`${idPrefix}-question`}>Ask Qurio about this research</label>
      <textarea id={`${idPrefix}-question`} aria-label="Ask Qurio about this research" placeholder="Why this candidate? What failed? What should change next?" value={question} maxLength={500} disabled={busy} onChange={(event) => setQuestion(event.target.value)} />
      <div><span>Read-only · retained evidence</span><button type="submit" disabled={!question.trim() || busy}>{busy ? 'Working…' : 'Ask'}</button></div>
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
  const terminalRun = ['completed', 'failed', 'cancelled'].includes(snapshot.run.state);
  const reportSelectionId = snapshot.report?.selectionDecision?.selectedCandidateId;
  const generalizationSelectionId = snapshot.report?.generalization?.selectedCandidateId;
  const authoritativeSelectionId = reportSelectionId
    && (terminalRun ? generalizationSelectionId === reportSelectionId : !generalizationSelectionId || generalizationSelectionId === reportSelectionId)
    ? reportSelectionId
    : undefined;
  const authoritativeSelection = authoritativeSelectionId
    ? snapshot.candidates.find((candidate) => candidate.id === authoritativeSelectionId)
    : undefined;
  const trainingLeader = snapshot.candidates.find((candidate) => candidate.verdict === 'promising');
  const featuredCandidate = authoritativeSelection ?? (terminalRun ? undefined : trainingLeader ?? snapshot.candidates[0]);
  const selectedCandidate = snapshot.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? featuredCandidate;
  const validationEvidenceApplies = Boolean(
    authoritativeSelection
    && generalizationSelectionId === reportSelectionId
    && selectedCandidate?.id === authoritativeSelection.id,
  );
  const hasValidationResult = Boolean(snapshot.report?.generalization);
  const validationEvidenceUnavailable = hasValidationResult && !validationEvidenceApplies;
  const walkForward = validationEvidenceApplies ? snapshot.report?.walkForward : undefined;
  const holdout = snapshot.run.state === 'completed' || snapshot.run.state === 'waiting_for_review'
    ? validationEvidenceApplies ? snapshot.report?.generalization : undefined
    : undefined;
  const decision = useMemo(() => presentPromotionDecision(snapshot), [snapshot]);
  const [performanceView, setPerformanceView] = useState<'equity' | 'drawdown'>('equity');
  const recentEvents = snapshot.events.slice(-4).reverse();
  const transientRows = transientPhaseRows[snapshot.run.state];
  const copilot = useMemo(() => presentResearchCopilot(snapshot, { selectedCandidateId, isHistorical }), [isHistorical, selectedCandidateId, snapshot]);
  const evidenceFocusActions = useMemo(() => onEvidenceFocus ? projectEvidenceFocusActions(snapshot, selectedCandidateId) : [], [onEvidenceFocus, selectedCandidateId, snapshot]);
  const canAsk = copilot.canAsk;
  const isResearchLaunch = snapshot.run.state === 'draft' || snapshot.run.state === 'planning';
  const terminal = terminalRun;
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
          : snapshot.run.state === 'completed' && authoritativeSelection
            ? { ...decision, title: `${authoritativeSelection.name.replace(/^Candidate [A-Z] · /, '')} · ${decision.title}` }
            : decision;
  const onTabKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const enabledTabs = isResearchLaunch ? workspaceTabs.slice(0, 1) : workspaceTabs;
    const current = enabledTabs.indexOf(activeTab);
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % enabledTabs.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + enabledTabs.length) % enabledTabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = enabledTabs.length - 1;
    else return;
    event.preventDefault();
    const nextTab = enabledTabs[next] ?? activeTab;
    onTabChange(nextTab);
    requestAnimationFrame(() => document.getElementById(`pq-workspace-tab-${nextTab}`)?.focus());
  };

  const tabLabel: Record<WorkspaceTab, string> = { overview: 'Overview', experiments: 'Experiments', analysis: 'Analysis', report: 'Decision' };
  return <section className={`pq-workbench${terminal ? ' is-terminal' : ''}${isResearchLaunch ? ' is-research-launch' : ''}${canAsk && !isResearchLaunch ? ' has-interactive-copilot' : ' is-context'}`} aria-label="Qurio research workspace">
    <header className="pq-workbench-header">
      <h1>{snapshot.scope.symbol} Research</h1>
      <nav aria-label="Research views" role="tablist" onKeyDown={onTabKeyDown}>
        {workspaceTabs.map((tab) => {
          const unavailable = isResearchLaunch && tab !== 'overview';
          return <button key={tab} role="tab" id={`pq-workspace-tab-${tab}`} aria-controls={`pq-workspace-panel-${tab}`} aria-selected={activeTab === tab} aria-disabled={unavailable || undefined} disabled={unavailable} tabIndex={activeTab === tab ? 0 : -1} onClick={() => onTabChange(tab)}>{tabLabel[tab]}</button>;
        })}
      </nav>
    </header>
    {activeTab === 'overview' ? <div className={`pq-overview-grid${isResearchLaunch ? ' is-research-launch' : ''}`} role="tabpanel" id="pq-workspace-panel-overview" aria-labelledby="pq-workspace-tab-overview">
      <main className="pq-overview-main">
        <div className="pq-context-bar">
          <strong>{snapshot.scope.symbol}</strong>
          <span>{snapshot.scope.market}</span>
          <span>{snapshot.scope.interval}</span>
          <span>{snapshot.scope.dateRange.start} — {snapshot.scope.dateRange.end}</span>
          {snapshot.researchMemory && <span>Memory applied: {snapshot.researchMemory.sourceRunCount} prior runs · {snapshot.researchMemory.testedCandidateCount} exact strategies constrained</span>}
        </div>
        <div className="pq-overview-content">
          {isResearchLaunch && <ResearchLaunchPanel snapshot={snapshot} busy={busy} onGeneratePlan={() => onCommand('generate_plan')} onEditObjective={onRunResearch} />}
          {compactLayout && !isResearchLaunch && <ResearchCopilotContent compact projection={copilot} snapshot={snapshot} recentEvents={recentEvents} evidenceFocusActions={evidenceFocusActions} busy={busy} onAction={handleCopilotAction} onEvidenceFocus={onEvidenceFocus ?? (() => undefined)} />}
          <ResearchPlanForApproval snapshot={snapshot} />
          {!isResearchLaunch && <QuantDecisionGate decision={overviewDecision} className="is-overview" />}
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
              <dl><div><dt>Sealed holdout</dt><dd className={`is-${validationEvidenceUnavailable ? 'unavailable' : holdout?.status ?? 'pending'}`}>{validationEvidenceUnavailable ? 'Unavailable' : validationStatusLabel(holdout?.status)}</dd></div><div><dt>Positive-return folds</dt><dd>{walkForward ? `${walkForward.aggregate.candidatePositiveReturnFolds} / ${walkForward.foldCount}` : '—'}</dd></div><div><dt>Holdout annual return</dt><dd>{formatPercent(holdout?.holdout?.candidate.annualizedReturn)}</dd></div><div><dt>Decision</dt><dd>{validationEvidenceUnavailable ? 'Evidence unavailable' : decision.label}</dd></div></dl>
            </section>
            {snapshot.candidates.length > 0 && <CandidateComparison snapshot={snapshot} selectedCandidateId={selectedCandidate?.id ?? ''} onSelectCandidate={onSelectCandidate} variant="snapshot" />}
          </div>}
        </div>
      </main>
      {!compactLayout && !isResearchLaunch && <aside className={`pq-copilot ${canAsk ? 'is-interactive' : 'is-context'}`} aria-label="Qurio">
        <header><strong>Qurio</strong><span>{snapshot.scope.symbol} · Overview</span></header>
        <ResearchCopilotContent projection={copilot} snapshot={snapshot} recentEvents={recentEvents} evidenceFocusActions={evidenceFocusActions} busy={busy} onAction={handleCopilotAction} onEvidenceFocus={onEvidenceFocus ?? (() => undefined)} />
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
  const title = destination === 'new_research' ? 'New research' : destination === 'runs' ? 'History' : destination === 'data' ? 'Data directory' : destination === 'paper' ? 'Paper Trading' : 'Settings';
  const singleColumn = destination === 'settings' || destination === 'runs' || destination === 'paper';
  const hideCopilot = singleColumn || (destination === 'data' && dataPreviewing);
  return <section className={`pq-utility-frame is-${destination}${singleColumn ? ' is-single' : ''}${destination === 'data' && dataPreviewing ? ' is-data-preview' : ''}`} aria-label={title}>
    <header><strong>{title}</strong>{!hideCopilot && <span>{destination === 'data' ? dataImporting ? 'Import guide' : 'Dataset inspector' : 'Preflight review'}</span>}</header>
    <div className="pq-utility-grid">
      <div className="pq-utility-center">{children}</div>
      {!hideCopilot && <aside className="pq-utility-copilot" aria-label={destination === 'data' ? 'Dataset inspector' : 'Research preflight'}>
        <div className="pq-utility-scroll">
          <span className="pq-copilot-kicker">{destination === 'data' ? dataImporting ? 'Data import' : 'Selected dataset' : 'Research preflight'}</span>
          <h2>{destination === 'data' ? dataImporting ? 'Validate before selection' : `${dataset.symbol} · ${dataset.interval}` : 'Review the execution boundary'}</h2>
          <p>{destination === 'data' ? dataImporting ? 'Provider responses and uploads are validated before they can replace the selected research dataset.' : `${dataset.name} is selected in the local catalog. Check its coverage and quality before using it in research.` : 'Choose a research-ready dataset, then describe the market outcome you want the Agent to test.'}</p>
          {destination === 'data' ? dataImporting ? <><section className="pq-utility-card"><strong>Import contract</strong><dl><div><dt>Execution</dt><dd>Server owned</dd></div><div><dt>Validation</dt><dd>Required</dd></div><div><dt>Result</dt><dd>Immutable version</dd></div></dl></section><p className="pq-utility-guidance">The current dataset remains selected until validation succeeds.</p></> : <><section className="pq-utility-facts" aria-label="Dataset fitness"><dl><div><dt>Coverage</dt><dd>{dataset.dateRange.start} — {dataset.dateRange.end}</dd></div><div><dt>Bars</dt><dd>{dataset.barCount.toLocaleString()}</dd></div><div><dt>Quality</dt><dd className={datasetQualityClass(dataset)}>{datasetQualityLabel(dataset)}</dd></div><div><dt>Price path</dt><dd>Preview from the catalog</dd></div></dl></section><details className="pq-utility-card"><summary>Retained metadata</summary><dl><div><dt>Digest</dt><dd><code>{dataset.digest.slice(0, 16)}…</code></dd></div><div><dt>Schema</dt><dd>{dataset.schemaVersion}</dd></div><div><dt>Source</dt><dd>{dataset.source ? `${dataset.source.sourceName} · ${dataset.contract === 'market-v2' ? dataset.timeZone : dataset.source.timeZone ?? 'timezone unavailable'}` : 'Unavailable'}</dd></div></dl>{onInspectDataset && <button onClick={onInspectDataset}>Open metadata record</button>}</details></> : <><section className="pq-utility-facts" aria-label="Research readiness"><dl><div><dt>Dataset</dt><dd>{dataset.symbol} · {dataset.interval}</dd></div><div><dt>Data quality</dt><dd className={datasetQualityClass(dataset)}>{datasetQualityLabel(dataset)}</dd></div><div><dt>Sample</dt><dd className={dataset.researchEligible ? 'is-positive' : 'is-danger'}>{dataset.researchEligible ? 'Minimum history met' : 'Insufficient history'}</dd></div></dl></section><p className="pq-utility-guidance">Describe a measurable market outcome. The plan will show the validation path before research starts.</p></>}
        </div>
      </aside>}
    </div>
  </section>;
}
