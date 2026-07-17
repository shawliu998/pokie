import { useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Button, Status } from '@glint/ui';
import { Group, Panel, Separator } from 'react-resizable-panels';
import type { QuantApi } from '../../quant-api';
import type { QuantCommand, QuantNavDestination, QuantWorkspaceSnapshot } from '../../quant-domain';
import { quantAuthenticityLabel } from '../../quant-domain';
import { useCompactLayout } from '../../hooks/useCompactLayout';
import { QuantActionCenter, QuantActivityFeed, QuantArtifactCards, QuantKernelCheckCard } from './QuantActivity';
import { QuantGoalComposer } from './QuantGoalComposer';
import { QuantInspector, type QuantInspectTarget } from './QuantInspector';
import { QuantMarketWorkspace } from './QuantMarketWorkspace';
import { QuantPlanRail } from './QuantPlanRail';
import { presentQuantWorkspace, type QuantActionPresentation } from './quant-presentation';
import { QuantSidebar } from './QuantSidebar';
import { QuantStrategyReport } from './QuantStrategyReport';
import './quant-workspace.css';

type CompactSegment = 'plan' | 'activity' | 'market' | 'report';

function idempotencyKey(command: QuantCommand): string {
  return `quant-ui-${command}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
}

function QuantToolbar({ snapshot, onDestination, onInspect }: { snapshot: QuantWorkspaceSnapshot; onDestination: (destination: QuantNavDestination) => void; onInspect: () => void }) {
  return <header className="quant-toolbar">
    <div className="quant-toolbar-context"><strong>{snapshot.scope.symbol}</strong><span>{snapshot.scope.market}</span><span>{snapshot.scope.interval}</span><Badge tone="warning">{quantAuthenticityLabel(snapshot.authenticity)}</Badge></div>
    <div className="quant-toolbar-modes" role="group" aria-label="Research mode"><button onClick={() => onDestination('new_research')}>Ask</button><button onClick={() => onDestination('new_research')}>Plan</button><button aria-pressed="true" onClick={() => onDestination('projects')}>Auto Research</button></div>
    <div className="quant-toolbar-actions"><span>{snapshot.limits.maxExperiments} experiments · {snapshot.limits.maxRepairAttempts} repairs · {snapshot.limits.maxRuntimeMinutes} min</span><Button onClick={onInspect}>Inspector</Button></div>
  </header>;
}

function ProjectHeader({ snapshot, presentation }: { snapshot: QuantWorkspaceSnapshot; presentation: ReturnType<typeof presentQuantWorkspace> }) {
  const retainedCount = snapshot.candidates.filter((candidate) => candidate.verdict === 'promising').length;
  const rejectedCount = snapshot.candidates.filter((candidate) => candidate.verdict === 'rejected').length;
  const inconclusiveCount = snapshot.candidates.filter((candidate) => candidate.verdict === 'inconclusive').length;
  const result = snapshot.run.state === 'completed'
    ? retainedCount === 0
      ? 'No candidate passed validation · run completed normally'
      : `${retainedCount} candidate retained · ${rejectedCount} rejected · ${inconclusiveCount} inconclusive`
    : snapshot.run.state === 'waiting_for_review'
      ? 'Agent output ready for human review'
      : snapshot.run.state === 'failed'
        ? 'Stopped safely · retained diagnostics available'
        : snapshot.run.state === 'cancelled'
          ? 'Cancelled · no later Agent output accepted'
          : 'Pending synthetic Agent execution';
  return <header className="quant-project-header"><div><p className="quant-eyebrow">Project · Run {String(snapshot.run.attemptNumber).padStart(2, '0')}</p><h1>{snapshot.project.goal}</h1><div><Status tone={presentation.statusTone}>{presentation.statusLabel}</Status><Badge tone="neutral">Auto Research</Badge><Badge tone="warning">{quantAuthenticityLabel(snapshot.authenticity)}</Badge></div></div><dl><div><dt>Approved scope</dt><dd>{snapshot.scope.symbol} · {snapshot.scope.interval} · {snapshot.scope.dateRange.start} – {snapshot.scope.dateRange.end}</dd></div><div><dt>Result</dt><dd>{result}</dd></div></dl></header>;
}

function OverviewPage({ destination, snapshot, onOpenWorkspace, onInspect, onComposer }: {
  destination: Exclude<QuantNavDestination, 'projects'>;
  snapshot: QuantWorkspaceSnapshot;
  onOpenWorkspace: () => void;
  onInspect: (target: QuantInspectTarget) => void;
  onComposer: (command: QuantCommand, payload: Record<string, unknown>) => void;
}) {
  if (destination === 'new_research') return <div className="quant-page quant-new-page"><div className="quant-page-title"><p className="quant-eyebrow">New Research</p><h1>Start from a bounded market question</h1><p>Choose Ask for a read-only fixture explanation or Plan for a reviewable scope. Auto Research stays unavailable until the API reports plan approval.</p></div><QuantGoalComposer snapshot={snapshot} large onSubmit={onComposer} /></div>;
  if (destination === 'runs') { const runPresentation = presentQuantWorkspace(snapshot); const hasRetainedCandidate = snapshot.candidates.some((candidate) => candidate.verdict === 'promising'); return <div className="quant-page"><div className="quant-page-title"><p className="quant-eyebrow">Runs</p><h1>Research attempts</h1><p>Retry creates a new attempt; prior events, verdicts, and artifacts remain immutable.</p></div><button className="quant-run-card" onClick={onOpenWorkspace}><div><strong>{snapshot.project.title}</strong><span>Attempt {snapshot.run.attemptNumber} · {snapshot.run.mode.replace('_', ' ')}</span></div><Status tone={runPresentation.statusTone}>{runPresentation.statusLabel}</Status><dl><div><dt>Experiments</dt><dd>{snapshot.run.usedExperiments} recorded</dd></div><div><dt>Repairs</dt><dd>{snapshot.run.usedRepairAttempts} recorded</dd></div><div><dt>Conclusion</dt><dd>{snapshot.run.state === 'completed' ? hasRetainedCandidate ? 'Mixed candidate verdicts' : 'No candidate passed validation' : 'Pending Agent result'}</dd></div></dl></button></div>; }
  if (destination === 'data') return <div className="quant-page"><div className="quant-page-title"><p className="quant-eyebrow">Data</p><h1>Immutable datasets</h1><p>Phase 0 exposes only named fixtures. No live connection control is available.</p></div><article className="quant-data-card"><header><div><p className="quant-eyebrow">Dataset Snapshot</p><h2>{snapshot.dataset.name}</h2></div><Badge tone="warning">{quantAuthenticityLabel(snapshot.dataset.authenticity)}</Badge></header><dl><div><dt>Symbol / interval</dt><dd>{snapshot.dataset.symbol} · {snapshot.dataset.interval}</dd></div><div><dt>Date range</dt><dd>{snapshot.dataset.dateRange.start} – {snapshot.dataset.dateRange.end}</dd></div><div><dt>Bar count</dt><dd>{snapshot.dataset.barCount.toLocaleString()}</dd></div><div><dt>Schema</dt><dd>{snapshot.dataset.schemaVersion}</dd></div></dl><Button onClick={() => onInspect({ kind: 'dataset' })}>Inspect provenance</Button></article></div>;
  return <div className="quant-page"><div className="quant-page-title"><p className="quant-eyebrow">Settings</p><h1>Runtime and policy</h1><p>These are truthful, read-only capabilities for the deterministic Phase 0 fixture.</p></div><div className="quant-policy-grid"><article><span>Runtime</span><strong>{snapshot.runtimeLabel}</strong><small>Named fixture projection</small></article><article><span>Market network</span><strong>Disabled</strong><small>No live or historical provider retrieval</small></article><article><span>Arbitrary Python</span><strong>Disabled</strong><small>No code execution in this shell</small></article><article><span>Paper trading</span><strong>Disabled</strong><small>No broker connection or order action</small></article><article><span>Model</span><strong>{snapshot.modelLabel}</strong><small>No tokens or provider cost displayed</small></article></div></div>;
}

function QuantWorkspaceView({ api, snapshot, onRefresh }: { api: QuantApi; snapshot: QuantWorkspaceSnapshot; onRefresh: () => Promise<void> }) {
  const presentation = useMemo(() => presentQuantWorkspace(snapshot), [snapshot]);
  const compact = useCompactLayout();
  const [destination, setDestination] = useState<QuantNavDestination>('projects');
  const [segment, setSegment] = useState<CompactSegment>('activity');
  const [selectedCandidateId, setSelectedCandidateId] = useState('candidate-b');
  const [inspectorTarget, setInspectorTarget] = useState<QuantInspectTarget | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [commandPending, setCommandPending] = useState(false);
  const inspectorInvoker = useRef<HTMLElement | null>(null);

  const openInspector = (target: QuantInspectTarget) => { inspectorInvoker.current = document.activeElement as HTMLElement | null; setInspectorTarget(target); };
  const closeInspector = () => { setInspectorTarget(null); requestAnimationFrame(() => inspectorInvoker.current?.focus()); };
  const command = async (kind: QuantCommand, payload?: Record<string, unknown>) => {
    if (commandPending) return;
    setCommandPending(true);
    try {
      const receipt = await api.sendCommand({ command: kind, expectedVersion: snapshot.run.rowVersion, idempotencyKey: idempotencyKey(kind), payload: { runId: snapshot.run.id, ...payload } });
      setNotice(receipt.message);
      if (receipt.status !== 'rejected') {
        await onRefresh();
        if (kind !== 'ask') setDestination('projects');
      }
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : 'The Agent command could not be completed.');
    } finally {
      setCommandPending(false);
    }
  };
  const act = (action: QuantActionPresentation) => {
    if (action.kind === 'open_report') openInspector({ kind: 'report' });
    else if (action.kind === 'compare_candidates') { setSelectedCandidateId('candidate-b'); setSegment('report'); setNotice('Candidate comparison is visible in Strategy Report.'); }
    else if (action.kind === 'open_diagnostics') openInspector({ kind: 'run' });
    else void command(action.kind);
  };

  const activityCanvas = <div className="quant-activity-pane"><QuantActionCenter presentation={presentation} onAction={act} /><QuantKernelCheckCard snapshot={snapshot} /><QuantActivityFeed snapshot={snapshot} presentation={presentation} onInspect={(event) => openInspector({ kind: 'event', event })} /><QuantArtifactCards artifacts={presentation.primaryArtifacts} onInspect={(artifact) => openInspector({ kind: 'artifact', artifact })} /></div>;
  const market = <QuantMarketWorkspace snapshot={snapshot} onInspect={openInspector} />;
  const report = <QuantStrategyReport snapshot={snapshot} candidates={presentation.candidates} selectedCandidateId={selectedCandidateId} onSelectCandidate={(id) => { setSelectedCandidateId(id); const candidate = snapshot.candidates.find((item) => item.id === id); if (candidate && compact) openInspector({ kind: 'candidate', candidate }); }} />;

  const projectWorkspace = <div className="quant-project-workspace"><ProjectHeader snapshot={snapshot} presentation={presentation} />{compact ? <><nav className="quant-segments" aria-label="Workspace sections">{(['plan', 'activity', 'market', 'report'] as const).map((item) => <button key={item} aria-current={segment === item ? 'page' : undefined} onClick={() => setSegment(item)}>{item}</button>)}</nav><div className="quant-compact-segment">{segment === 'plan' ? <QuantPlanRail steps={snapshot.plan} currentStepId={snapshot.run.currentStepId} completedStepCount={presentation.completedStepCount} /> : segment === 'activity' ? activityCanvas : segment === 'market' ? market : report}</div></> : <Group id="quant-workspace-panels" orientation="horizontal" className="quant-workspace-panels" resizeTargetMinimumSize={{ coarse: 24, fine: 8 }}><Panel id="quant-plan-panel" defaultSize={220} minSize={190} maxSize={300} groupResizeBehavior="preserve-pixel-size"><QuantPlanRail steps={snapshot.plan} currentStepId={snapshot.run.currentStepId} completedStepCount={presentation.completedStepCount} /></Panel><Separator className="quant-resize-separator" aria-label="Resize plan and activity" /><Panel id="quant-activity-panel" defaultSize={360} minSize={320} maxSize={470} groupResizeBehavior="preserve-pixel-size">{activityCanvas}</Panel><Separator className="quant-resize-separator" aria-label="Resize activity and market" /><Panel id="quant-market-panel" minSize={500}><Group id="quant-market-report-panels" orientation="vertical" className="quant-market-report-panels"><Panel id="quant-market-chart" defaultSize={330} minSize={250} groupResizeBehavior="preserve-pixel-size">{market}</Panel><Separator className="quant-horizontal-separator" aria-label="Resize market chart and strategy report" /><Panel id="quant-strategy-report" minSize={240}>{report}</Panel></Group></Panel></Group>}<QuantGoalComposer snapshot={snapshot} onSubmit={(kind, payload) => void command(kind, payload)} /></div>;

  return <main className="quant-shell">
    <QuantToolbar snapshot={snapshot} onDestination={setDestination} onInspect={() => openInspector({ kind: 'run' })} />
    <Group id="pokiequant-shell" orientation="horizontal" className="quant-shell-body"><Panel id="quant-sidebar" defaultSize={228} minSize={190} maxSize={280} collapsible collapsedSize={0} groupResizeBehavior="preserve-pixel-size"><QuantSidebar snapshot={snapshot} destination={destination} onSelect={setDestination} /></Panel><Separator className="quant-resize-separator" aria-label="Resize navigation and workspace" /><Panel id="quant-main" minSize={700}>{destination === 'projects' ? projectWorkspace : <OverviewPage destination={destination} snapshot={snapshot} onOpenWorkspace={() => setDestination('projects')} onInspect={openInspector} onComposer={(kind, payload) => void command(kind, payload)} />}</Panel></Group>
    {inspectorTarget && <QuantInspector snapshot={snapshot} presentation={presentation} target={inspectorTarget} onClose={closeInspector} />}
    {notice && <div className="quant-notice" role="status">{notice}<button aria-label="Dismiss notification" onClick={() => setNotice(null)}>×</button></div>}
  </main>;
}

export function QuantWorkspace({ api }: { api: QuantApi }) {
  const [snapshot, setSnapshot] = useState<QuantWorkspaceSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = async () => {
    try {
      setError(null);
      setSnapshot(await api.getWorkspaceSnapshot());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'PokieQuant could not load the API snapshot.');
    }
  };
  useEffect(() => { void refresh(); }, [api]);
  if (!snapshot) {
    return <main className="quant-shell"><div className="loading-shell" aria-live="polite">{error ? <><p role="alert">{error}</p><Button onClick={() => void refresh()}>Retry API snapshot</Button></> : <p>Loading server-owned PokieQuant snapshot…</p>}</div></main>;
  }
  return <QuantWorkspaceView api={api} snapshot={snapshot} onRefresh={refresh} />;
}
