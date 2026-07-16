import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { Badge, Button, EmptyState, Status } from '@glint/ui';
import type { PanelImperativeHandle } from 'react-resizable-panels';
import type { GlintApi, SignalDismissReason, SourceViewer } from '../../api';
import type { DecisionBrief, Destination, Investigation } from '../../domain';
import { authenticityLabel } from '../../domain';
import { useRunStream } from '../../hooks/useRunStream';
import { useCompactLayout } from '../../hooks/useCompactLayout';
import { useNativeMenu } from '../../hooks/useNativeMenu';
import { useWorkbenchKeyboard } from '../../hooks/useWorkbenchKeyboard';
import { adjacentItemId, buildGlobalSearchResults, buildWorkbenchCommands, destinationItemIds } from '../../lib/commands';
import { displayTime } from '../../lib/formatting';
import { canExecuteWrite, compactWorkbenchReducer } from '../../lib/workbench-state';
import { DataStatusDialog } from '../../components/DataStatusDialog';
import { ListPane, Sidebar } from '../../components/Navigation';
import { DecisionBriefDetail } from '../decisions/DecisionBriefDetail';
import { CommandPalette } from '../commands/CommandPalette';
import { GlobalSearchDialog } from '../commands/GlobalSearchDialog';
import { KeyboardShortcutsDialog } from '../commands/KeyboardShortcutsDialog';
import { SourceViewerDialog } from '../evidence/SourceViewerDialog';
import { ExportDialog } from '../export/ExportDialog';
import { SignalDetail } from '../inbox/SignalInbox';
import { SignalDismissDialog } from '../inbox/SignalDismissDialog';
import { InvestigationDetail } from '../investigations/InvestigationDetail';
import { InvestigationPlanDialog } from '../investigations/InvestigationPlanDialog';
import { MonitoringView } from '../monitoring/MonitoringView';
import { useWorkspace } from '../workspace/useWorkspace';
import { WorkbenchLayout } from './WorkbenchLayout';

type WorkbenchOverlay = 'plan' | 'export' | 'status' | 'commands' | 'search' | 'shortcuts' | 'dismiss' | null;

export function Workbench({ api }: { api: GlintApi }) {
  const { workspace, setWorkspace, selectedId, setSelectedId, loading, error, setError, offline, reload } = useWorkspace(api);
  const [destination, setDestination] = useState<Destination>('inbox');
  const [modal, setModal] = useState<WorkbenchOverlay>(null);
  const [sourceViewer, setSourceViewer] = useState<SourceViewer | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const compact = useCompactLayout();
  const [compactState, dispatchCompact] = useReducer(compactWorkbenchReducer, { pane: 'list', selectedId: '' });
  const sidebarPanelRef = useRef<PanelImperativeHandle>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [pendingSourceFocusId, setPendingSourceFocusId] = useState<string | null>(null);
  const selectedSignal = workspace?.signals.find((signal) => signal.id === selectedId) ?? workspace?.signals[0];
  const selectedInvestigation = workspace?.investigations.find((item) => item.id === selectedId) ?? workspace?.investigations[0];
  const selectedBrief = workspace?.briefs.find((item) => item.id === selectedId) ?? workspace?.briefs.find((brief) => brief.status === 'draft') ?? workspace?.briefs[0];

  useEffect(() => {
    if (!pendingSourceFocusId || destination !== 'monitoring') return;
    const frame = requestAnimationFrame(() => {
      const card = document.querySelector<HTMLElement>(`[data-source-id="${CSS.escape(pendingSourceFocusId)}"]`);
      if (!card) return;
      card.focus();
      card.scrollIntoView({ block: 'center' });
      setPendingSourceFocusId(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [destination, pendingSourceFocusId]);

  const updateInvestigation = useCallback((investigation: Investigation) => setWorkspace((current) => current ? { ...current, investigations: current.investigations.map((item) => item.id === investigation.id ? investigation : item) } : current), []);

  const runConnection = useRunStream({ api, offline, investigation: selectedInvestigation, setWorkspace });

  const select = (next: Destination, id: string) => { setDestination(next); setSelectedId(id); dispatchCompact({ type: 'select', id }); };
  const selectDestination = (next: Destination) => {
    setDestination(next);
    dispatchCompact({ type: 'show-list' });
    const first = next === 'inbox' ? workspace?.signals[0]?.id : next === 'investigations' ? workspace?.investigations[0]?.id : next === 'decisions' ? workspace?.briefs[0]?.id : 'monitoring';
    if (first) setSelectedId(first);
  };
  const toggleSidebar = () => {
    const panel = sidebarPanelRef.current;
    if (!panel) return;
    if (panel.isCollapsed()) panel.expand(); else panel.collapse();
  };
  const updateBrief = (brief: DecisionBrief) => setWorkspace((current) => current ? { ...current, briefs: current.briefs.map((item) => item.id === brief.id ? brief : item), navigation: { ...current.navigation, draftDecisionBriefCount: current.briefs.filter((item) => item.id === brief.id ? brief.status === 'draft' : item.status === 'draft').length } } : current);
  const updateSignal = (signal: NonNullable<typeof selectedSignal>) => setWorkspace((current) => current ? { ...current, signals: current.signals.map((item) => item.id === signal.id ? signal : item) } : current);
  const safe = async (task: () => Promise<void>) => { try { setError(null); await task(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Action failed.'); } };

  const canOpenSelected = destination === 'inbox' ? Boolean(selectedSignal) : destination === 'investigations' ? Boolean(selectedInvestigation) : destination === 'decisions' ? Boolean(selectedBrief) : false;
  const hasEligibleSignalSource = Boolean(selectedSignal?.perSourceFreshness.some(({ sourceConnectionId }) => workspace?.sources.some((source) => source.id === sourceConnectionId && !['auth_required', 'disabled', 'failed'].includes(source.status))));
  const canStartInvestigation = Boolean(!offline && destination === 'inbox' && selectedSignal && selectedSignal.status !== 'new' && selectedSignal.status !== 'dismissed' && hasEligibleSignalSource);
  const canOpenSourceViewer = Boolean(!offline && ((destination === 'inbox' && selectedSignal) || (destination === 'investigations' && selectedInvestigation?.evidence.length)));
  const canDismissSignal = Boolean(!offline && destination === 'inbox' && selectedSignal && ['new', 'triaged', 'explained', 'monitoring'].includes(selectedSignal.status));
  const canExportBrief = Boolean(!offline && destination === 'decisions' && selectedBrief?.status === 'decision_ready' && selectedBrief.freshness === 'current');
  const openSelected = () => {
    const id = destination === 'inbox' ? selectedSignal?.id : destination === 'investigations' ? selectedInvestigation?.id : destination === 'decisions' ? selectedBrief?.id : undefined;
    if (!id) return false;
    select(destination, id);
    return true;
  };
  const moveSelection = (direction: 1 | -1) => {
    if (!workspace) return false;
    const next = adjacentItemId(destinationItemIds(workspace, destination, filter), selectedId, direction);
    if (!next) return false;
    setSelectedId(next);
    return true;
  };
  const startInvestigation = () => { if (!canStartInvestigation) return false; setModal('plan'); return true; };
  const dismissSignal = () => { if (!canDismissSignal) return false; setModal('dismiss'); return true; };
  const openSelectedSource = () => {
    if (!canOpenSourceViewer) return false;
    void safe(async () => {
      if (destination === 'inbox' && selectedSignal) {
        const sample = (await api.signalSamples(selectedSignal.id))[0];
        if (!sample) throw new Error('No immutable source sample is available for this Signal.');
        setSourceViewer(sample.viewer);
      } else if (destination === 'investigations' && selectedInvestigation?.evidence[0]) {
        setSourceViewer(await api.sourceViewer(selectedInvestigation.signalId, selectedInvestigation.evidence[0]));
      }
    });
    return true;
  };

  useWorkbenchKeyboard({
    overlayOpen: Boolean(modal || sourceViewer),
    openCommandPalette: () => setModal('commands'),
    openGlobalSearch: () => setModal('search'),
    closeOverlay: () => { if (sourceViewer) setSourceViewer(null); else setModal(null); },
    escape: () => { if (compact && compactState.pane === 'detail') { dispatchCompact({ type: 'show-list' }); return true; } return false; },
    moveSelection,
    openSelected,
    startInvestigation,
    openSourceViewer: openSelectedSource,
    dismissSignal,
  });
  useNativeMenu((command) => {
    if (modal || sourceViewer) return;
    if (command === 'view.toggle-sidebar' && !compact) toggleSidebar();
    else if (command === 'view.focus-search') {
      const input = document.querySelector<HTMLInputElement>('.list-pane input');
      if (input) input.focus(); else setModal('search');
    }
    else if (command === 'view.command-palette') setModal('commands');
    else if (command === 'view.reload-workspace') void reload();
    else if (command === 'navigate.inbox') selectDestination('inbox');
    else if (command === 'navigate.investigations') selectDestination('investigations');
    else if (command === 'navigate.decisions') selectDestination('decisions');
    else if (command === 'navigate.monitoring') selectDestination('monitoring');
    else if (command === 'navigate.back-to-list') {
      if (compact && compactState.pane === 'detail') dispatchCompact({ type: 'show-list' });
      requestAnimationFrame(() => document.querySelector<HTMLElement>('.list-pane input, .list-pane button, .list-pane')?.focus());
    } else if (command === 'help.keyboard-shortcuts') setModal('shortcuts');
  });

  if (loading) return <div className="loading-shell" aria-live="polite"><div className="skeleton title" /><div className="skeleton wide" /><div className="skeleton wide" /></div>;
  if (error && !workspace) return <div className="fatal"><EmptyState title="Glint could not load this workspace" body={`${error} No cached content is available.`} action={<Button onClick={() => void reload()}>Retry connection</Button>} /></div>;
  if (!workspace) return null;
  const writeDisabled = !canExecuteWrite({ offline });
  const selectedBriefInvestigation = selectedBrief ? workspace.investigations.find((item) => item.id === selectedBrief.investigationId) : undefined;
  const hasReviewedCounterEvidence = Boolean(selectedBriefInvestigation?.claims.some((claim) => claim.evidenceLinks.some((link) => link.stance === 'opposes' && ['valid', 'weak'].includes(selectedBriefInvestigation.evidence.find((evidence) => evidence.id === link.evidenceId)?.status ?? ''))));
  const commands = buildWorkbenchCommands({ canOpenSelected, canStartInvestigation, canOpenSourceViewer, canDismissSignal, canExportBrief, canToggleSidebar: !compact }, {
    goTo: selectDestination,
    openSelected: () => { openSelected(); },
    startInvestigation: () => { startInvestigation(); },
    openSourceViewer: () => { openSelectedSource(); },
    dismissSignal: () => { dismissSignal(); },
    exportBrief: () => setModal('export'),
    reloadWorkspace: () => { void reload(); },
    showDataStatus: () => setModal('status'),
    toggleSidebar,
    showKeyboardShortcuts: () => setModal('shortcuts'),
  });
  const globalSearchResults = buildGlobalSearchResults(workspace);

  return <main className="app-shell">
    <header className="toolbar"><button className="icon-button" aria-label={sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'} aria-expanded={!sidebarCollapsed} disabled={compact} onClick={toggleSidebar}>☰</button><strong>Glint / {workspace.workspaceName}</strong><span className="toolbar-spacer" /><button className="text-button" aria-label="Open global search" title="Global Search (⌘P)" onClick={() => setModal('search')}>⌘P</button><button className="text-button" aria-label="Open Command Palette" title="Command Palette (⌘K)" onClick={() => setModal('commands')}>⌘K</button><Badge tone="info">{authenticityLabel(workspace.authenticity)}</Badge><button onClick={() => setModal('status')} className="data-status"><Status tone={offline || workspace.navigation.monitoringHealth === 'degraded' ? 'warning' : 'positive'}>{offline ? 'Offline' : workspace.navigation.monitoringHealth === 'degraded' ? 'Source degraded' : 'Current'}</Status></button></header>
    {offline && <div className="offline" role="status">Offline cached read-only · cached_at {displayTime(workspace.cachedAt)}. Editing, runs, SSE, exports, reconnect, and source commands are disabled. <Button onClick={() => void reload()}>Retry connection</Button></div>}
    {error && <div className="error-banner" role="alert">{error} <Button onClick={() => setError(null)}>Dismiss</Button></div>}
    {notice && <div className="toast" role="status">{notice}<button aria-label="Dismiss notification" onClick={() => setNotice(null)}>×</button></div>}
    <WorkbenchLayout compact={compact} compactPane={compactState.pane} sidebarPanelRef={sidebarPanelRef} onSidebarCollapsedChange={setSidebarCollapsed} onBack={() => dispatchCompact({ type: 'show-list' })}
      sidebar={<Sidebar destination={destination} workspace={workspace} onSelect={selectDestination} />}
      list={<ListPane destination={destination} workspace={workspace} selectedId={selectedId} filter={filter} setFilter={setFilter} onSelect={(id) => select(destination, id)} />}
      detail={<section className="detail" aria-label="Detail panel">
        {destination === 'inbox' && selectedSignal && <SignalDetail signal={selectedSignal} sources={workspace.sources} disabled={writeDisabled} onLoadSamples={() => api.signalSamples(selectedSignal.id)} onTriage={(impact, urgency) => safe(async () => updateSignal(await api.triage(selectedSignal.id, impact, urgency)))} onStart={() => setModal('plan')} onDismiss={() => setModal('dismiss')} />}
        {destination === 'investigations' && selectedInvestigation && <InvestigationDetail investigation={selectedInvestigation} disabled={writeDisabled} runConnection={runConnection} onOpenEvidence={(evidence) => api.sourceViewer(selectedInvestigation.signalId, evidence)} onReviewEvidence={(evidence, decision) => safe(async () => updateInvestigation(await api.reviewEvidence(selectedInvestigation.id, evidence.id, decision)))} onReviewClaim={(claimId, decision) => safe(async () => updateInvestigation(await api.reviewClaim(selectedInvestigation.id, claimId, decision)))} onCreateSynthesis={() => safe(async () => updateInvestigation(await api.createSynthesis(selectedInvestigation.id)))} onReviseSynthesis={(summary) => safe(async () => updateInvestigation(await api.reviseSynthesis(selectedInvestigation.id, summary)))} onReviewSynthesis={(decision) => safe(async () => updateInvestigation(await api.reviewSynthesis(selectedInvestigation.id, decision)))} onCreateBrief={() => safe(async () => { const brief = await api.createBrief(selectedInvestigation.id); setWorkspace({ ...workspace, briefs: workspace.briefs.some((item) => item.id === brief.id) ? workspace.briefs.map((item) => item.id === brief.id ? brief : item) : [...workspace.briefs, brief] }); select('decisions', brief.id); })} onCancelRun={() => safe(async () => updateInvestigation(await api.cancelRun(selectedInvestigation.id)))} onRetryRun={() => safe(async () => updateInvestigation(await api.retryRun(selectedInvestigation.id)))} />}
        {destination === 'decisions' && selectedBrief && <DecisionBriefDetail brief={selectedBrief} disabled={writeDisabled} hasReviewedCounterEvidence={hasReviewedCounterEvidence} onUpdate={(judgment, recommendationId, recommendationBody, status) => safe(async () => updateBrief(await api.updateBrief(selectedBrief.id, judgment, recommendationId, recommendationBody, status)))} onSaveCounterEvidenceSearch={(input) => safe(async () => updateBrief(await api.saveNoCounterEvidenceSearch(selectedBrief.id, input)))} onReady={() => safe(async () => updateBrief(await api.markReady(selectedBrief.id)))} onExport={() => setModal('export')} />}
        {destination === 'monitoring' && <MonitoringView api={api} workspaceId={workspace.workspaceId} sources={workspace.sources} watchlists={workspace.watchlists} schedules={workspace.schedules} disabled={writeDisabled} onComplete={reload} />}
      </section>}
    />
    {modal === 'plan' && selectedSignal && <InvestigationPlanDialog signal={selectedSignal} sources={workspace.sources} disabled={writeDisabled} onClose={() => setModal(null)} onRun={(question) => safe(async () => { const investigation = await api.createInvestigation(selectedSignal.id, question); setWorkspace({ ...workspace, investigations: workspace.investigations.some((item) => item.id === investigation.id) ? workspace.investigations.map((item) => item.id === investigation.id ? investigation : item) : [...workspace.investigations, investigation] }); setModal(null); select('investigations', investigation.id); })} />}
    {modal === 'export' && selectedBrief && <ExportDialog brief={selectedBrief} disabled={writeDisabled} onClose={() => setModal(null)} onPreview={() => api.previewExport(selectedBrief.id)} onExecute={(preview, nextDestination, idempotencyKey) => api.executeExport(selectedBrief.id, preview, nextDestination, idempotencyKey)} onDone={(message) => { setModal(null); setNotice(message); }} />}
    {modal === 'status' && <DataStatusDialog sources={workspace.sources} onClose={() => setModal(null)} />}
    {modal === 'commands' && <CommandPalette commands={commands} onClose={() => setModal(null)} />}
    {modal === 'search' && <GlobalSearchDialog results={globalSearchResults} onClose={() => setModal(null)} onSelect={(result) => { if (result.kind === 'Source') setPendingSourceFocusId(result.id); select(result.destination, result.id); }} />}
    {modal === 'shortcuts' && <KeyboardShortcutsDialog onClose={() => setModal(null)} />}
    {modal === 'dismiss' && selectedSignal && <SignalDismissDialog signal={selectedSignal} disabled={writeDisabled} onClose={() => setModal(null)} onConfirm={(reason: SignalDismissReason, note) => void safe(async () => { updateSignal(await api.transitionSignal(selectedSignal.id, 'dismiss', { dismissReason: reason, note })); setModal(null); setNotice('Signal dismissed. The audited disposition remains available in Signal history.'); })} />}
    {sourceViewer && <SourceViewerDialog viewer={sourceViewer} onClose={() => setSourceViewer(null)} />}
  </main>;
}
