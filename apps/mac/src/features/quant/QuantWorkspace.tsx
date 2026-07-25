import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@glint/ui';
import { quantIdempotencyKey, type QuantApi } from '../../quant-api';
import type { DatasetSnapshot, QuantCommand, QuantNavDestination, QuantResearchMode, QuantWorkspaceSnapshot } from '../../quant-domain';
import { useCompactLayout } from '../../hooks/useCompactLayout';
import { QuantActivityFeed, QuantArtifactCards, QuantKernelCheckCard, QuantRunMonitor } from './QuantActivity';
import { QuantDataPage } from './QuantDataPage';
import { presentQuantProblem, QuantInlineProblem, type QuantProblem } from './quant-errors';
import { QuantGoalComposer, type QuantRefinementContext, type QuantResearchFollowUp } from './QuantGoalComposer';
import { QuantInspector, type QuantInspectTarget } from './QuantInspector';
import { QuantOverviewWorkbench, QuantUtilityFrame, ResearchCopilotContent, type WorkspaceTab } from './QuantOverviewWorkbench';
import { canContinueResearch, presentQuantWorkspace, presentResearchCopilot, projectTerminalDecision, resolveEvidenceFocusIntent, type QuantActionPresentation, type QuantCopilotActionKind, type QuantEvidenceFocusIntent, type QuantEvidenceFocusRequest, type QuantEvidenceFocusResult } from './quant-presentation';
import { QuantRunsPage } from './QuantRunsPage';
import { QuantSidebar } from './QuantSidebar';
import { QuantStrategyReport } from './QuantStrategyReport';
import { QuantStrategyLab } from './QuantStrategyLab';
import { QuantRuntimeSettings } from './QuantRuntimeSettings';
import './quant-workspace.css';

const quantDestinations: ReadonlySet<QuantNavDestination> = new Set(['new_research', 'projects', 'runs', 'data', 'settings']);
const progressOverviewStates = new Set(['loading_data', 'generating_candidates', 'generating_report']);
const experimentWorkspaceStates = new Set(['queued', 'running_experiments', 'repairing', 'validating']);
const agentDecisionSurfaceStates = new Set(['queued', 'loading_data', 'generating_candidates', 'running_experiments', 'repairing', 'validating', 'generating_report']);

function initialDestination(): QuantNavDestination {
  try {
    const stored = sessionStorage.getItem('pokiequant.destination') as QuantNavDestination | null;
    return stored && quantDestinations.has(stored) ? stored : 'projects';
  } catch {
    return 'projects';
  }
}

function focusAfterPaint(target: () => HTMLElement | null | undefined) {
  requestAnimationFrame(() => requestAnimationFrame(() => target()?.focus()));
}

function verifiedTime(value: string | null): string {
  if (!value) return 'not yet verified';
  return new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(value));
}

function useCopilotCompactLayout(): boolean {
  const [compact, setCompact] = useState(() => window.innerWidth <= 1180);
  useEffect(() => {
    const update = () => setCompact(window.innerWidth <= 1180);
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);
  return compact;
}

function commandSuccessTitle(kind: QuantCommand): string {
  return {
    ask: 'Question submitted',
    generate_plan: 'Plan created',
    start_auto_research: 'Research started',
    approve_plan: 'Plan approved',
    request_plan_changes: 'Plan changes requested',
    run_fixture: 'Research started',
    approve_execution: 'Execution approved',
    cancel_run: 'Run cancelled',
    retry_run: 'New attempt created',
    complete_review: 'Review completed',
    start_new_run: 'New run created',
  }[kind];
}

function continuationContext(snapshot: QuantWorkspaceSnapshot, candidateId: string): QuantRefinementContext | null {
  const candidate = snapshot.candidates.find((item) => item.id === candidateId);
  if (!candidate || !canContinueResearch(snapshot, candidate)) return null;
  const validation = snapshot.report?.generalization?.status;
  const benchmarkDelta = snapshot.benchmark
    ? candidate.metrics.annualizedReturn - snapshot.benchmark.annualizedReturn
    : undefined;
  const summary = [
    `${candidate.metrics.annualizedReturn >= 0 ? '+' : ''}${candidate.metrics.annualizedReturn.toFixed(1)}% annual return`,
    benchmarkDelta === undefined ? null : `${benchmarkDelta >= 0 ? '+' : ''}${benchmarkDelta.toFixed(1)} pts vs benchmark`,
    validation ? `sealed holdout ${validation.replaceAll('_', ' ')}` : null,
  ].filter(Boolean).join(' · ');
  return {
    projectId: snapshot.project.id,
    parentRunId: snapshot.run.id,
    seedCandidateId: candidate.id,
    candidateName: candidate.name.replace(/^Candidate [A-Z] · /, ''),
    sourceQuestion: snapshot.project.goal,
    sourceDateRange: { ...snapshot.scope.dateRange },
    summary,
  };
}

export function QuantWorkspaceLoading({ slow = false, error = null, onRetry }: { slow?: boolean; error?: QuantProblem | null; onRetry: () => void }) {
  return <main className="quant-shell quant-boot" aria-busy={!error}>
    <div className="quant-boot-layout">
      <aside className="quant-boot-sidebar" aria-hidden="true">
        <div className="quant-brand"><img className="quant-brand-wordmark" src="/brand/qurio-wordmark-inverse.svg" alt="Qurio" /></div>
        <span>Qurio workspace</span>
        <nav><span>Workspace</span><span>New research</span><span>History</span><span>Data</span><span>Settings</span></nav>
      </aside>
      <section className="quant-boot-main" aria-live="polite">
        <header><strong>Qurio workspace</strong></header>
        <div className="quant-boot-state">
          {error
            ? <QuantInlineProblem problem={error} action={error.retryable ? <Button onClick={onRetry}>Retry connection</Button> : undefined} />
            : <><strong>{slow ? 'Still waiting for the local API' : 'Connecting to the local runtime'}</strong><p>{slow ? 'The service may still be starting. No action is required; this view will update when a verified snapshot arrives.' : 'Loading the latest verified research snapshot.'}</p></>}
        </div>
      </section>
    </div>
  </main>;
}

function OverviewPage({ api, destination, snapshot, selectedDataset, composerMode, commandPending, openingRunId, openRunError, refinement, refinementLoading, refinementError, evidenceFocus, onEvidenceFocusResolved, onCancelRefinement, onSelectDataset, onUseDatasetForResearch, onDataImportViewChange, onDataPreviewViewChange, onOpenWorkspace, onStartNewResearch, onRefineFromComparison, onAddData, onComposer, onStartNewRun, onOpenRun }: {
  api: QuantApi;
  destination: Exclude<QuantNavDestination, 'projects'>;
  snapshot: QuantWorkspaceSnapshot;
  selectedDataset: DatasetSnapshot;
  composerMode: QuantResearchMode;
  commandPending: boolean;
  openingRunId: string | null;
  openRunError: string | null;
  refinement: QuantRefinementContext | null;
  refinementLoading: boolean;
  refinementError: string | null;
  evidenceFocus?: QuantEvidenceFocusIntent | null;
  onEvidenceFocusResolved?: (id: string, result: QuantEvidenceFocusResult) => void;
  onCancelRefinement: () => void;
  onSelectDataset: (dataset: DatasetSnapshot) => void;
  onUseDatasetForResearch: (dataset: DatasetSnapshot) => void;
  onDataImportViewChange: (importing: boolean) => void;
  onDataPreviewViewChange: (previewing: boolean) => void;
  onOpenWorkspace: () => void;
  onStartNewResearch: () => void;
  onRefineFromComparison: (source: QuantWorkspaceSnapshot, candidateId: string, reason: string) => void;
  onAddData: () => void;
  onComposer: (command: QuantCommand, payload: Record<string, unknown>) => void;
  onStartNewRun: (mode: QuantResearchMode, goal: string, dataset: DatasetSnapshot, dateRange: { start: string; end: string }, refinement?: QuantRefinementContext, refinementReason?: string, followUp?: QuantResearchFollowUp) => void;
  onOpenRun: (runId: string) => Promise<void>;
}) {
  if (destination === 'new_research') return <div className="quant-page quant-new-page"><div className="quant-page-title"><h1>New research</h1><p>{refinement ? 'Set the next objective from retained evidence, then generate a plan for review.' : 'Select market evidence, define a measurable objective, and generate a plan before Qurio runs experiments.'}</p></div>{refinementLoading ? <p className="quant-inline-note" role="status">Loading continuation source…</p> : refinementError ? <QuantInlineProblem problem={{ kind: 'validation', title: 'Continuation unavailable', detail: refinementError, retryable: false }} action={<Button onClick={onCancelRefinement}>Start new research</Button>} /> : <QuantGoalComposer api={api} snapshot={snapshot} selectedDataset={selectedDataset} initialMode={composerMode} initialGoal={refinement ? `Continue research from ${refinement.candidateName}: ${refinement.sourceQuestion}` : ''} large busy={commandPending} refinement={refinement} onCancelRefinement={onCancelRefinement} onSelectDataset={onSelectDataset} onAddData={onAddData} onSubmit={onComposer} onStartNewRun={onStartNewRun} />}</div>;
  if (destination === 'runs') return <QuantRunsPage api={api} snapshot={snapshot} openingRunId={openingRunId} openRunError={openRunError} onOpenRun={onOpenRun} onOpenReport={onOpenWorkspace} onStartNewResearch={onStartNewResearch} onRefineFromComparison={onRefineFromComparison} evidenceFocus={evidenceFocus} onEvidenceFocusResolved={onEvidenceFocusResolved} />;
  if (destination === 'data') return <QuantDataPage api={api} snapshot={snapshot} selectedDataset={selectedDataset} onSelect={onSelectDataset} onUseForResearch={onUseDatasetForResearch} onImportViewChange={onDataImportViewChange} onPreviewViewChange={onDataPreviewViewChange} />;
  return <QuantRuntimeSettings snapshot={snapshot} />;
}

function QuantWorkspaceView({ api, snapshot, isHistorical, refreshError, refreshing, lastVerifiedAt, openingRunId, openRunError, onRefresh, onOpenRun }: { api: QuantApi; snapshot: QuantWorkspaceSnapshot; isHistorical: boolean; refreshError: string | null; refreshing: boolean; lastVerifiedAt: string | null; openingRunId: string | null; openRunError: string | null; onRefresh: (showLatest?: boolean) => Promise<void>; onOpenRun: (runId: string, options?: { historical?: boolean }) => Promise<void> }) {
  const presentation = useMemo(() => presentQuantWorkspace(snapshot), [snapshot]);
  const compact = useCompactLayout();
  const compactCopilot = useCopilotCompactLayout();
  const preferredCandidateId = snapshot.report?.generalization?.selectedCandidateId
    ?? snapshot.candidates.find((candidate) => candidate.verdict === 'promising')?.id
    ?? snapshot.candidates[0]?.id
    ?? '';
  const [destination, setDestination] = useState<QuantNavDestination>(initialDestination);
  const [projectTab, setProjectTab] = useState<WorkspaceTab>(experimentWorkspaceStates.has(snapshot.run.state) ? 'experiments' : 'overview');
  const [composerMode, setComposerMode] = useState<QuantResearchMode>('plan');
  const [selectedCandidateId, setSelectedCandidateId] = useState(preferredCandidateId);
  const [selectedDataset, setSelectedDataset] = useState<DatasetSnapshot>(snapshot.dataset);
  const [refinement, setRefinement] = useState<QuantRefinementContext | null>(null);
  const [refinementLoading, setRefinementLoading] = useState(false);
  const [refinementError, setRefinementError] = useState<string | null>(null);
  const [dataImporting, setDataImporting] = useState(false);
  const [dataPreviewing, setDataPreviewing] = useState(false);
  const [inspectorTarget, setInspectorTarget] = useState<QuantInspectTarget | null>(null);
  const [notice, setNotice] = useState<{ tone: 'neutral' | 'danger'; title: string; detail?: string } | null>(null);
  const [evidenceFocus, setEvidenceFocus] = useState<QuantEvidenceFocusIntent | null>(null);
  const [commandPending, setCommandPending] = useState(false);
  const liveDecisionProjection = useMemo(() => presentResearchCopilot(snapshot, { selectedCandidateId, isHistorical }), [isHistorical, selectedCandidateId, snapshot]);
  const commandLock = useRef(false);
  const evidenceFocusSequence = useRef(0);
  const previousDestination = useRef<QuantNavDestination>(destination);
  const previousRun = useRef({ id: snapshot.run.id, state: snapshot.run.state });
  const noticeRef = useRef<HTMLDivElement | null>(null);
  const inspectorInvoker = useRef<HTMLElement | null>(null);

  const clearContinuation = useCallback(() => {
    setRefinement(null);
    setRefinementError(null);
    setRefinementLoading(false);
    const url = new URL(window.location.href);
    url.searchParams.delete('continueRun');
    url.searchParams.delete('seedCandidate');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }, []);

  const beginNewResearch = useCallback(() => {
    clearContinuation();
    setEvidenceFocus(null);
    setComposerMode('plan');
    setSelectedDataset(snapshot.dataset);
    setDestination('new_research');
  }, [clearContinuation, snapshot.dataset]);

  useEffect(() => {
    const url = new URL(window.location.href);
    const parentRunId = url.searchParams.get('continueRun');
    const seedCandidateId = url.searchParams.get('seedCandidate');
    if (!parentRunId && !seedCandidateId) return;
    if (!parentRunId || !seedCandidateId) {
      setRefinementError('The continuation source is incomplete. Start a new research run instead.');
      setDestination('new_research');
      return;
    }
    let current = true;
    setRefinementLoading(true);
    setRefinementError(null);
    setDestination('new_research');
    void api.getRunWorkspaceSnapshot(parentRunId).then((source) => {
      if (!current) return;
      const context = continuationContext(source, seedCandidateId);
      if (!context) {
        setRefinementError('The selected source strategy is no longer available for continuation.');
        return;
      }
      setSelectedDataset(source.dataset);
      setRefinement(context);
    }).catch((reason) => {
      if (current) setRefinementError(presentQuantProblem(reason, 'Continuation source').detail);
    }).finally(() => { if (current) setRefinementLoading(false); });
    return () => { current = false; };
  }, [api]);

  useEffect(() => {
    setSelectedCandidateId(preferredCandidateId);
    setEvidenceFocus(null);
  }, [snapshot.run.id, preferredCandidateId]);

  useEffect(() => {
    const previous = previousRun.current;
    const runChanged = previous.id !== snapshot.run.id;
    const enteredProgressOverview = progressOverviewStates.has(snapshot.run.state)
      && (runChanged || !progressOverviewStates.has(previous.state));
    const enteredExperimentWorkspace = experimentWorkspaceStates.has(snapshot.run.state)
      && (runChanged || !experimentWorkspaceStates.has(previous.state));
    previousRun.current = { id: snapshot.run.id, state: snapshot.run.state };
    if (enteredProgressOverview) setProjectTab('overview');
    else if (enteredExperimentWorkspace) setProjectTab('experiments');
  }, [snapshot.run.id, snapshot.run.state]);

  useEffect(() => {
    try { sessionStorage.setItem('pokiequant.destination', destination); } catch { /* Tauri/browser storage may be unavailable. */ }
  }, [destination]);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'n' || target?.matches('input, textarea, select, [contenteditable="true"]')) return;
      event.preventDefault();
      beginNewResearch();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [beginNewResearch]);

  useEffect(() => {
    if (notice?.tone !== 'danger') return;
    focusAfterPaint(() => noticeRef.current);
  }, [notice]);

  useEffect(() => {
    const previous = previousDestination.current;
    previousDestination.current = destination;
    if (previous !== 'projects' && destination === 'projects') focusAfterPaint(() => document.getElementById(`pq-workspace-tab-${projectTab}`));
  }, [destination, projectTab]);

  const openInspector = (target: QuantInspectTarget) => { inspectorInvoker.current = document.activeElement as HTMLElement | null; setInspectorTarget(target); };
  const closeInspector = () => { setInspectorTarget(null); requestAnimationFrame(() => inspectorInvoker.current?.focus()); };
  const command = async (kind: QuantCommand, payload?: Record<string, unknown>) => {
    if (commandLock.current) return;
    if (isHistorical) {
      setNotice({ tone: 'danger', title: 'Historical run is read-only', detail: 'Return to the latest run before issuing a lifecycle command.' });
      return;
    }
    commandLock.current = true;
    setCommandPending(true);
    try {
      const receipt = await api.sendCommand({ command: kind, expectedVersion: snapshot.run.rowVersion, idempotencyKey: quantIdempotencyKey(), payload: { runId: snapshot.run.id, ...payload }, run: snapshot.run });
      setNotice({ tone: receipt.status === 'rejected' ? 'danger' : 'neutral', title: receipt.status === 'rejected' ? 'Command not accepted' : commandSuccessTitle(kind), detail: receipt.message });
      if (receipt.status !== 'rejected') {
        await onRefresh(true);
        if (kind !== 'ask') setDestination('projects');
      }
    } catch (reason) {
      const problem = presentQuantProblem(reason, 'Agent command');
      setNotice({ tone: 'danger', title: problem.title, detail: problem.detail });
    } finally {
      commandLock.current = false;
      setCommandPending(false);
    }
  };
  const startNewRun = async (mode: QuantResearchMode, goal: string, dataset: DatasetSnapshot, dateRange: { start: string; end: string }, source?: QuantRefinementContext, refinementReason?: string, followUp?: QuantResearchFollowUp) => {
    if (commandLock.current) return;
    commandLock.current = true;
    setCommandPending(true);
    try {
      const continuationReason = refinementReason?.trim();
      if (source && !continuationReason) throw new Error('Explain what should change before continuing research.');
      const project = source
        ? (await api.listProjects()).find((item) => item.id === source.projectId)
        : await api.createProject({ name: `${dataset.symbol} Research`, objective: goal, idempotencyKey: quantIdempotencyKey() });
      if (!project) throw new Error('The source project is unavailable. Reload the source run and try again.');
      if (dataset.contract === 'market-v2') {
        if (!dataset.researchEligible || dataset.periodsPerYear === null) throw new Error('This stored market dataset is not research eligible.');
        await api.createMarketRun({
          projectId: project.id,
          mode: mode === 'auto_research' ? 'auto' : 'plan',
          question: goal,
          expectedProjectRowVersion: project.rowVersion,
          datasetId: dataset.id,
          researchStartUtc: dateRange.start,
          researchEndUtc: dateRange.end,
          ...(source ? { parentRunId: source.parentRunId, seedCandidateId: source.seedCandidateId, refinementReason: continuationReason } : {}),
          ...(followUp === 'one_train_only_follow_up' ? { researchLoop: { followUpMode: followUp, maxVersions: 2 as const, maxTotalExperiments: 6 as const, maxTotalAgentActions: 24 as const } } : {}),
          idempotencyKey: quantIdempotencyKey(),
        });
      } else {
        await api.createRun({
          projectId: project.id,
          mode: mode === 'auto_research' ? 'auto' : 'plan',
          question: goal,
          expectedProjectRowVersion: project.rowVersion,
          datasetId: dataset.id,
          researchStart: dateRange.start,
          researchEnd: dateRange.end,
          ...(source ? { parentRunId: source.parentRunId, seedCandidateId: source.seedCandidateId, refinementReason: continuationReason } : {}),
          idempotencyKey: quantIdempotencyKey(),
        });
      }
      clearContinuation();
      setNotice({ tone: 'neutral', title: mode === 'plan' ? 'Plan created' : 'Research started', detail: source ? `${dataset.symbol} · ${dataset.interval} was pinned to an independent continuation run.` : `${dataset.symbol} · ${dataset.interval} was pinned to the new immutable run.` });
      await onRefresh(true);
      setDestination('projects');
    } catch (reason) {
      const problem = presentQuantProblem(reason, 'New research run');
      setNotice({ tone: 'danger', title: problem.title, detail: problem.detail });
    } finally {
      commandLock.current = false;
      setCommandPending(false);
    }
  };
  const beginContinuation = (candidateId: string, initialReason?: string) => {
    if (isHistorical) {
      setNotice({ tone: 'danger', title: 'Historical run is read-only', detail: 'Return to the latest run before continuing research.' });
      return;
    }
    const source = continuationContext(snapshot, candidateId);
    const candidate = snapshot.candidates.find((item) => item.id === candidateId);
    if (!source || !canContinueResearch(snapshot, candidate)) {
      setNotice({ tone: 'danger', title: 'Continuation unavailable', detail: 'Choose a retained candidate with a strategy specification before continuing research.' });
      return;
    }
    const url = new URL(window.location.href);
    url.searchParams.set('continueRun', source.parentRunId);
    url.searchParams.set('seedCandidate', source.seedCandidateId);
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    setSelectedDataset(snapshot.dataset);
    setRefinementError(null);
    setRefinement({ ...source, ...(typeof initialReason === 'string' && initialReason.trim() ? { initialReason } : {}) });
    setComposerMode('plan');
    setDestination('new_research');
  };
  const beginComparisonRefinement = (sourceSnapshot: QuantWorkspaceSnapshot, candidateId: string, reason: string) => {
    const source = continuationContext(sourceSnapshot, candidateId);
    if (!source) {
      setNotice({ tone: 'danger', title: 'Refinement unavailable', detail: 'The compared result no longer contains an eligible retained strategy.' });
      return;
    }
    const url = new URL(window.location.href);
    url.searchParams.set('continueRun', source.parentRunId);
    url.searchParams.set('seedCandidate', source.seedCandidateId);
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    setSelectedDataset(sourceSnapshot.dataset);
    setRefinementError(null);
    setRefinement({ ...source, initialReason: reason });
    setComposerMode('plan');
    setDestination('new_research');
  };
  const runCampaignRefinement = (candidateId: string, reason: string) => {
    if (isHistorical) {
      setNotice({ tone: 'danger', title: 'Historical run is read-only', detail: 'Return to the latest run before starting an autonomous refinement.' });
      return;
    }
    const source = continuationContext(snapshot, candidateId);
    if (!source || !reason.trim()) {
      setNotice({ tone: 'danger', title: 'Suggested refinement unavailable', detail: 'The retained candidate or next-research proposal is incomplete.' });
      return;
    }
    const goal = `Continue research from ${source.candidateName}: ${source.sourceQuestion}`;
    void startNewRun('auto_research', goal, snapshot.dataset, { ...snapshot.scope.dateRange }, source, reason);
  };
  const terminalDecision = projectTerminalDecision(snapshot);
  const continueFromReport = (candidateId: string, reason?: string) => {
    if (snapshot.run.state === 'completed'
      && (!terminalDecision || terminalDecision.decision !== 'refine' || !terminalDecision.canRefine || candidateId !== terminalDecision.finalCandidateId)) {
      setNotice({ tone: 'danger', title: 'Continuation unavailable', detail: 'Only the retained final choice may refine this completed research series.' });
      return;
    }
    beginContinuation(candidateId, reason);
  };
  const continueFromSecondaryEvidence = !isHistorical && snapshot.run.state !== 'completed'
    ? () => beginContinuation(selectedCandidateId)
    : undefined;
  const consumeEvidenceFocus = (id: string) => {
    setEvidenceFocus((current) => current?.id === id ? null : current);
  };
  const resolveRunsEvidenceFocus = (id: string, result: QuantEvidenceFocusResult) => {
    if (evidenceFocus?.id !== id) return;
    setEvidenceFocus(null);
    setNotice({
      tone: result.status === 'opened' ? 'neutral' : 'danger',
      title: result.status === 'opened' ? 'Source comparison opened' : 'Source comparison unavailable',
      detail: `${result.receipt} · ${result.evidenceReference}`,
    });
  };
  const selectCandidate = (candidateId: string) => {
    setEvidenceFocus(null);
    setSelectedCandidateId(candidateId);
  };
  const openProjectTab = (tab: WorkspaceTab) => {
    setEvidenceFocus(null);
    setProjectTab(tab);
  };
  const focusEvidence = (request: QuantEvidenceFocusRequest) => {
    const id = `evidence-focus-${snapshot.run.id}-${++evidenceFocusSequence.current}`;
    const intent: QuantEvidenceFocusIntent = request.target === 'trade'
      ? { id, runId: request.runId, candidateId: request.candidateId, destination: request.destination, target: request.target, tradeId: request.tradeId }
      : request.target === 'trades'
        ? { id, runId: request.runId, candidateId: request.candidateId, destination: request.destination, target: request.target, ...(request.tradeId ? { tradeId: request.tradeId } : {}) }
        : request.target === 'source_comparison'
          ? { id, runId: request.runId, candidateId: request.candidateId, destination: request.destination, target: request.target, sourceRunId: request.sourceRunId }
          : request.target === 'drawdown'
          ? { id, runId: request.runId, candidateId: request.candidateId, destination: request.destination, target: request.target }
          : { id, runId: request.runId, candidateId: request.candidateId, destination: request.destination, target: request.target };
    const resolution = resolveEvidenceFocusIntent(snapshot, intent);
    if (!resolution) {
      setEvidenceFocus(null);
      setNotice({ tone: 'danger', title: 'Evidence unavailable', detail: 'The requested Run, candidate, or retained evidence no longer matches this snapshot.' });
      return;
    }
    setSelectedCandidateId(intent.candidateId);
    setEvidenceFocus(intent);
    if (resolution.destination === 'runs') {
      setDestination('runs');
      setNotice({ tone: 'neutral', title: 'Locating source comparison', detail: resolution.evidenceReference });
      return;
    }
    setProjectTab(resolution.destination);
    setNotice({ tone: 'neutral', title: 'Evidence focus applied', detail: `${resolution.receipt} · ${resolution.evidenceReference}` });
  };
  const act = (action: QuantActionPresentation, payload?: Record<string, unknown>) => {
    if (action.kind === 'open_report') openInspector({ kind: 'report' });
    else if (action.kind === 'compare_candidates') { setEvidenceFocus(null); setSelectedCandidateId(preferredCandidateId); setProjectTab('report'); setNotice({ tone: 'neutral', title: 'Candidate comparison opened', detail: 'The selected candidate is visible in Strategy Report.' }); }
    else if (action.kind === 'open_diagnostics') openInspector({ kind: 'run' });
    else void command(action.kind, payload);
  };
  const actFromLiveDecision = (kind: QuantCopilotActionKind, payload?: Record<string, unknown>) => {
    if (kind === 'open_analysis') openProjectTab('analysis');
    else if (kind === 'open_report') openProjectTab('report');
    else if (kind === 'new_research') beginNewResearch();
    else if (kind === 'continue_research') beginContinuation(selectedCandidateId);
    else if (kind === 'return_latest') void onRefresh(true);
    else void command(kind, payload);
  };

  const isPolling = ['planning', 'queued', 'loading_data', 'generating_candidates', 'running_experiments', 'repairing', 'validating', 'generating_report'].includes(snapshot.run.state);
  const activityCanvas = <div className="quant-activity-pane"><QuantRunMonitor snapshot={snapshot} presentation={presentation} onAction={act} isPolling={isPolling} busy={commandPending} /><details className="quant-secondary-disclosure"><summary>Activity &amp; artifacts · {snapshot.events.length} events</summary><QuantKernelCheckCard snapshot={snapshot} /><QuantActivityFeed snapshot={snapshot} presentation={presentation} onInspect={(event) => openInspector({ kind: 'event', event })} /><QuantArtifactCards artifacts={presentation.primaryArtifacts} onInspect={(artifact) => openInspector({ kind: 'artifact', artifact })} /></details></div>;
  const showLiveDecisionSurface = agentDecisionSurfaceStates.has(snapshot.run.state);
  const liveDecisionSurface = showLiveDecisionSurface ? <aside className="pq-live-decision-column" aria-label="Qurio research decision">
    <header><strong>Qurio research decision</strong><span>{snapshot.scope.symbol} · Experiments</span></header>
    <ResearchCopilotContent mode="live-decision" projection={liveDecisionProjection} snapshot={snapshot} recentEvents={[]} evidenceFocusActions={[]} busy={commandPending} onAction={actFromLiveDecision} onAsk={() => undefined} onEvidenceFocus={() => undefined} />
    <div className="quant-widget-frame">{activityCanvas}</div>
  </aside> : null;
  const report = <QuantStrategyReport api={api} snapshot={snapshot} candidates={presentation.candidates} decision={presentation.decision} selectedCandidateId={selectedCandidateId} onSelectCandidate={selectCandidate} onOpenAnalysis={() => openProjectTab('analysis')} onContinueResearch={isHistorical ? undefined : continueFromReport} onRunAutopilot={isHistorical ? undefined : runCampaignRefinement} campaignBusy={commandPending} onOpenRun={(runId) => onOpenRun(runId, { historical: true })} onOpenHistory={() => { setEvidenceFocus(null); setDestination('runs'); }} onStartNewResearch={beginNewResearch} evidenceFocus={evidenceFocus?.destination === 'report' ? evidenceFocus : null} onEvidenceFocusConsumed={consumeEvidenceFocus} />;
  const experiments = <QuantStrategyLab snapshot={snapshot} selectedCandidateId={selectedCandidateId} onSelectCandidate={selectCandidate} onContinueResearch={continueFromSecondaryEvidence} variant="experiments" showLiveDecisionSummary={!showLiveDecisionSurface} />;
  const analysis = <QuantStrategyLab snapshot={snapshot} selectedCandidateId={selectedCandidateId} onSelectCandidate={selectCandidate} onContinueResearch={continueFromSecondaryEvidence} variant="analysis" evidenceFocus={evidenceFocus?.destination === 'analysis' ? evidenceFocus : null} onEvidenceFocusConsumed={consumeEvidenceFocus} />;

  const projectDetails = compact
    ? projectTab === 'experiments'
      ? <div className="quant-compact-stack">{liveDecisionSurface}{experiments}{!showLiveDecisionSurface && <div className="quant-widget-frame">{activityCanvas}</div>}</div>
      : projectTab === 'analysis'
        ? <div className="quant-compact-stack">{analysis}<div className="quant-widget-frame">{activityCanvas}</div></div>
        : projectTab === 'report'
          ? <div className="quant-widget-frame pq-report-frame">{report}</div>
          : null
    : projectTab === 'experiments' ? <div className={`pq-strategy-workspace${showLiveDecisionSurface ? ' is-live-run' : ''}`}>{experiments}{liveDecisionSurface ?? <div className="quant-widget-frame">{activityCanvas}</div>}</div> : projectTab === 'analysis' ? <div className="pq-strategy-workspace">{analysis}<div className="quant-widget-frame">{activityCanvas}</div></div> : <div className="quant-widget-frame pq-report-frame">{report}</div>;

  const projectWorkspace = <QuantOverviewWorkbench snapshot={snapshot} activeTab={projectTab} onTabChange={openProjectTab} onRunResearch={beginNewResearch} onOpenAnalysis={() => openProjectTab('analysis')} onOpenReport={() => openProjectTab('report')} onContinueResearch={continueFromSecondaryEvidence} onReturnLatest={() => void onRefresh(true)} selectedCandidateId={selectedCandidateId} onSelectCandidate={selectCandidate} busy={commandPending} isHistorical={isHistorical} compactLayout={compactCopilot} onCommand={(kind, payload) => void command(kind, payload)} onEvidenceFocus={focusEvidence}>{projectDetails}</QuantOverviewWorkbench>;
  const utilityContent = destination === 'projects' ? null : <OverviewPage api={api} destination={destination} snapshot={snapshot} selectedDataset={selectedDataset} composerMode={composerMode} commandPending={commandPending} openingRunId={openingRunId} openRunError={openRunError} refinement={refinement} refinementLoading={refinementLoading} refinementError={refinementError} evidenceFocus={evidenceFocus?.destination === 'runs' ? evidenceFocus : null} onEvidenceFocusResolved={resolveRunsEvidenceFocus} onCancelRefinement={beginNewResearch} onSelectDataset={setSelectedDataset} onUseDatasetForResearch={(dataset) => { clearContinuation(); setEvidenceFocus(null); setSelectedDataset(dataset); setComposerMode('plan'); setDataPreviewing(false); setDestination('new_research'); }} onDataImportViewChange={setDataImporting} onDataPreviewViewChange={setDataPreviewing} onOpenWorkspace={() => { setEvidenceFocus(null); setProjectTab('report'); setDestination('projects'); }} onStartNewResearch={beginNewResearch} onRefineFromComparison={beginComparisonRefinement} onAddData={() => { setEvidenceFocus(null); setDataImporting(true); setDataPreviewing(false); setDestination('data'); }} onComposer={(kind, payload) => void command(kind, payload)} onStartNewRun={(mode, goal, dataset, dateRange, source, reason, followUp) => void startNewRun(mode, goal, dataset, dateRange, source, reason, followUp)} onOpenRun={(runId) => onOpenRun(runId, { historical: true })} />;

  return <main className="quant-shell">
    {refreshError && <div className="quant-refresh-warning" role="status" title={refreshError}><strong>Live updates paused</strong><span>Showing snapshot verified at {verifiedTime(lastVerifiedAt)}</span><button disabled={refreshing} onClick={() => void onRefresh()}>{refreshing ? 'Refreshing…' : 'Refresh now'}</button></div>}
    <div className="quant-shell-body">
      <QuantSidebar snapshot={snapshot} destination={destination} onSelect={(next) => { setEvidenceFocus(null); if (next === 'new_research') { beginNewResearch(); return; } if (next !== 'data') { setDataImporting(false); setDataPreviewing(false); } setDestination(next); }} onSelectProject={(_projectId, runId) => { setEvidenceFocus(null); setDataImporting(false); setDataPreviewing(false); setDestination('runs'); void onOpenRun(runId); }} />
      <div className={`quant-main-surface is-projects${isHistorical ? ' is-historical' : ''}`}>
        {isHistorical && (destination !== 'projects' || projectTab !== 'overview') && <div className="quant-history-banner" role="status"><span><strong>Historical run</strong> · Read-only evidence from {snapshot.project.title.split(' · ')[0]}</span><button onClick={() => void onRefresh(true)}>Return to latest run</button></div>}
        {destination === 'runs' && openRunError && <p className="quant-runs-error" role="alert">{openRunError}</p>}
        <div className="quant-main-content">{destination === 'projects' ? projectWorkspace : <QuantUtilityFrame destination={destination} snapshot={snapshot} dataset={selectedDataset} dataImporting={dataImporting} dataPreviewing={dataPreviewing} onInspectDataset={() => openInspector({ kind: 'dataset', dataset: selectedDataset })}>{utilityContent}</QuantUtilityFrame>}</div>
      </div>
    </div>
    {inspectorTarget && <QuantInspector snapshot={snapshot} presentation={presentation} target={inspectorTarget} onClose={closeInspector} />}
    {notice && <div ref={noticeRef} tabIndex={-1} className={`quant-notice is-${notice.tone}`} role={notice.tone === 'danger' ? 'alert' : 'status'}><div><strong>{notice.title}</strong>{notice.detail && <span>{notice.detail}</span>}</div><button aria-label="Dismiss notification" onClick={() => setNotice(null)}>×</button></div>}
  </main>;
}

export function QuantWorkspace({ api }: { api: QuantApi }) {
  const [snapshot, setSnapshot] = useState<QuantWorkspaceSnapshot | null>(null);
  const [latestRunId, setLatestRunId] = useState<string | null>(null);
  const [error, setError] = useState<QuantProblem | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingSlow, setLoadingSlow] = useState(false);
  const [lastVerifiedAt, setLastVerifiedAt] = useState<string | null>(null);
  const [openingRunId, setOpeningRunId] = useState<string | null>(null);
  const [openRunError, setOpenRunError] = useState<string | null>(null);
  const refreshInFlight = useRef(false);
  const openRunInFlight = useRef(false);
  const viewingHistorical = useRef(false);
  const refresh = useCallback(async (showLatest = false) => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    setRefreshing(true);
    try {
      const latest = await api.getWorkspaceSnapshot();
      setError(null);
      setLastVerifiedAt(new Date().toISOString());
      setLatestRunId(latest.run.id);
      if (showLatest) viewingHistorical.current = false;
      if (!viewingHistorical.current) setSnapshot(latest);
    } catch (reason) {
      setError(presentQuantProblem(reason, 'Workspace snapshot'));
    } finally {
      refreshInFlight.current = false;
      setRefreshing(false);
    }
  }, [api]);
  const openRun = useCallback(async (runId: string, options?: { historical?: boolean }) => {
    const openAsHistorical = options?.historical === true;
    if (openRunInFlight.current || (snapshot?.run.id === runId && !openAsHistorical)) return;
    openRunInFlight.current = true;
    setOpeningRunId(runId);
    setOpenRunError(null);
    const openingLatest = runId === latestRunId && !openAsHistorical;
    try {
      const next = openingLatest ? await api.getWorkspaceSnapshot() : await api.getRunWorkspaceSnapshot(runId);
      if (next.run.id !== runId) throw new Error('Historical Run snapshot identity differs from the requested Run.');
      if (openingLatest) {
        viewingHistorical.current = false;
        setError(null);
        setLastVerifiedAt(new Date().toISOString());
        setLatestRunId(next.run.id);
      } else {
        viewingHistorical.current = true;
      }
      setSnapshot(next);
    } catch (reason) {
      const problem = presentQuantProblem(reason, 'Historical run');
      setOpenRunError(`Run could not be opened: ${problem.detail}`);
    } finally {
      openRunInFlight.current = false;
      setOpeningRunId(null);
    }
  }, [api, latestRunId, snapshot?.run.id]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (snapshot || error) { setLoadingSlow(false); return; }
    const timer = window.setTimeout(() => setLoadingSlow(true), 1_200);
    return () => window.clearTimeout(timer);
  }, [error, snapshot]);
  useEffect(() => {
    if (!snapshot || ['completed', 'failed', 'cancelled'].includes(snapshot.run.state)) return;
    const timer = window.setInterval(() => { void refresh(); }, 1_000);
    return () => window.clearInterval(timer);
  }, [refresh, snapshot?.run.state]);
  if (!snapshot) {
    return <QuantWorkspaceLoading slow={loadingSlow} error={error} onRetry={() => void refresh()} />;
  }
  return <QuantWorkspaceView api={api} snapshot={snapshot} isHistorical={viewingHistorical.current || Boolean(latestRunId && snapshot.run.id !== latestRunId)} refreshError={error?.detail ?? null} refreshing={refreshing} lastVerifiedAt={lastVerifiedAt} openingRunId={openingRunId} openRunError={openRunError} onRefresh={refresh} onOpenRun={openRun} />;
}
