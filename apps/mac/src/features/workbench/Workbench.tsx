import { useCallback, useEffect, useState } from 'react';
import { Badge, Button, EmptyState, Status } from '@glint/ui';
import type { GlintApi } from '../../api';
import type { DecisionBrief, Destination, Investigation } from '../../domain';
import { authenticityLabel } from '../../domain';
import { useRunStream } from '../../hooks/useRunStream';
import { displayTime } from '../../lib/formatting';
import { canExecuteWrite } from '../../lib/workbench-state';
import { DataStatusDialog } from '../../components/DataStatusDialog';
import { ListPane, Sidebar } from '../../components/Navigation';
import { DecisionBriefDetail } from '../decisions/DecisionBriefDetail';
import { ExportDialog } from '../export/ExportDialog';
import { SignalDetail } from '../inbox/SignalInbox';
import { InvestigationDetail } from '../investigations/InvestigationDetail';
import { InvestigationPlanDialog } from '../investigations/InvestigationPlanDialog';
import { MonitoringView } from '../monitoring/MonitoringView';
import { useWorkspace } from '../workspace/useWorkspace';

export function Workbench({ api }: { api: GlintApi }) {
  const { workspace, setWorkspace, selectedId, setSelectedId, loading, error, setError, offline, reload } = useWorkspace(api);
  const [destination, setDestination] = useState<Destination>('inbox');
  const [modal, setModal] = useState<'plan' | 'export' | 'status' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const selectedSignal = workspace?.signals.find((signal) => signal.id === selectedId) ?? workspace?.signals[0];
  const selectedInvestigation = workspace?.investigations.find((item) => item.id === selectedId) ?? workspace?.investigations[0];
  const selectedBrief = workspace?.briefs.find((item) => item.id === selectedId) ?? workspace?.briefs.find((brief) => brief.status === 'draft') ?? workspace?.briefs[0];

  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') setModal(null); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const updateInvestigation = useCallback((investigation: Investigation) => setWorkspace((current) => current ? { ...current, investigations: current.investigations.map((item) => item.id === investigation.id ? investigation : item) } : current), []);

  const runConnection = useRunStream({ api, offline, investigation: selectedInvestigation, setWorkspace });

  const select = (next: Destination, id: string) => { setDestination(next); setSelectedId(id); };
  const updateBrief = (brief: DecisionBrief) => setWorkspace((current) => current ? { ...current, briefs: current.briefs.map((item) => item.id === brief.id ? brief : item), navigation: { ...current.navigation, draftDecisionBriefCount: current.briefs.filter((item) => item.id === brief.id ? brief.status === 'draft' : item.status === 'draft').length } } : current);
  const safe = async (task: () => Promise<void>) => { try { setError(null); await task(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Action failed.'); } };

  if (loading) return <div className="loading-shell" aria-live="polite"><div className="skeleton title" /><div className="skeleton wide" /><div className="skeleton wide" /></div>;
  if (error && !workspace) return <div className="fatal"><EmptyState title="Glint could not load this workspace" body={`${error} No cached content is available.`} action={<Button onClick={() => void reload()}>Retry connection</Button>} /></div>;
  if (!workspace) return null;
  const writeDisabled = !canExecuteWrite({ offline });
  const selectedBriefInvestigation = selectedBrief ? workspace.investigations.find((item) => item.id === selectedBrief.investigationId) : undefined;
  const hasReviewedCounterEvidence = Boolean(selectedBriefInvestigation?.claims.some((claim) => claim.evidenceLinks.some((link) => link.stance === 'opposes' && ['valid', 'weak'].includes(selectedBriefInvestigation.evidence.find((evidence) => evidence.id === link.evidenceId)?.status ?? ''))));

  return <main className="app-shell">
    <header className="toolbar"><span className="traffic" aria-hidden="true">● ● ●</span><strong>Glint / {workspace.workspaceName}</strong><span className="toolbar-spacer" /><Badge tone="info">{authenticityLabel(workspace.authenticity)}</Badge><button onClick={() => setModal('status')} className="data-status"><Status tone={offline || workspace.navigation.monitoringHealth === 'degraded' ? 'warning' : 'positive'}>{offline ? 'Offline' : workspace.navigation.monitoringHealth === 'degraded' ? 'Source degraded' : 'Current'}</Status></button></header>
    {offline && <div className="offline" role="status">Offline cached read-only · cached_at {displayTime(workspace.cachedAt)}. Editing, runs, SSE, exports, reconnect, and source commands are disabled. <Button onClick={() => void reload()}>Retry connection</Button></div>}
    {error && <div className="error-banner" role="alert">{error} <Button onClick={() => setError(null)}>Dismiss</Button></div>}
    {notice && <div className="toast" role="status">{notice}<button aria-label="Dismiss notification" onClick={() => setNotice(null)}>×</button></div>}
    <div className="three-column">
      <Sidebar destination={destination} workspace={workspace} onSelect={(next) => { setDestination(next); const first = next === 'inbox' ? workspace.signals[0]?.id : next === 'investigations' ? workspace.investigations[0]?.id : next === 'decisions' ? workspace.briefs[0]?.id : 'monitoring'; if (first) setSelectedId(first); }} />
      <ListPane destination={destination} workspace={workspace} selectedId={selectedId} filter={filter} setFilter={setFilter} onSelect={(id) => select(destination, id)} />
      <section className="detail" aria-label="Detail panel">
        {destination === 'inbox' && selectedSignal && <SignalDetail signal={selectedSignal} sources={workspace.sources} disabled={writeDisabled} onLoadSamples={() => api.signalSamples(selectedSignal.id)} onTriage={(impact, urgency) => safe(async () => { const updated = await api.triage(selectedSignal.id, impact, urgency); setWorkspace({ ...workspace, signals: workspace.signals.map((item) => item.id === updated.id ? updated : item) }); })} onStart={() => setModal('plan')} />}
        {destination === 'investigations' && selectedInvestigation && <InvestigationDetail investigation={selectedInvestigation} disabled={writeDisabled} runConnection={runConnection} onOpenEvidence={(evidence) => api.sourceViewer(selectedInvestigation.signalId, evidence)} onReviewEvidence={(evidence, decision) => safe(async () => updateInvestigation(await api.reviewEvidence(selectedInvestigation.id, evidence.id, decision)))} onReviewClaim={(claimId, decision) => safe(async () => updateInvestigation(await api.reviewClaim(selectedInvestigation.id, claimId, decision)))} onCreateSynthesis={() => safe(async () => updateInvestigation(await api.createSynthesis(selectedInvestigation.id)))} onReviseSynthesis={(summary) => safe(async () => updateInvestigation(await api.reviseSynthesis(selectedInvestigation.id, summary)))} onReviewSynthesis={(decision) => safe(async () => updateInvestigation(await api.reviewSynthesis(selectedInvestigation.id, decision)))} onCreateBrief={() => safe(async () => { const brief = await api.createBrief(selectedInvestigation.id); setWorkspace({ ...workspace, briefs: workspace.briefs.some((item) => item.id === brief.id) ? workspace.briefs.map((item) => item.id === brief.id ? brief : item) : [...workspace.briefs, brief] }); select('decisions', brief.id); })} onCancelRun={() => safe(async () => updateInvestigation(await api.cancelRun(selectedInvestigation.id)))} onRetryRun={() => safe(async () => updateInvestigation(await api.retryRun(selectedInvestigation.id)))} />}
        {destination === 'decisions' && selectedBrief && <DecisionBriefDetail brief={selectedBrief} disabled={writeDisabled} hasReviewedCounterEvidence={hasReviewedCounterEvidence} onUpdate={(judgment, recommendationId, recommendationBody, status) => safe(async () => updateBrief(await api.updateBrief(selectedBrief.id, judgment, recommendationId, recommendationBody, status)))} onSaveCounterEvidenceSearch={(input) => safe(async () => updateBrief(await api.saveNoCounterEvidenceSearch(selectedBrief.id, input)))} onReady={() => safe(async () => updateBrief(await api.markReady(selectedBrief.id)))} onExport={() => setModal('export')} />}
        {destination === 'monitoring' && <MonitoringView api={api} workspaceId={workspace.workspaceId} sources={workspace.sources} watchlists={workspace.watchlists} schedules={workspace.schedules} disabled={writeDisabled} onComplete={reload} />}
      </section>
    </div>
    {modal === 'plan' && selectedSignal && <InvestigationPlanDialog signal={selectedSignal} sources={workspace.sources} disabled={writeDisabled} onClose={() => setModal(null)} onRun={(question) => safe(async () => { const investigation = await api.createInvestigation(selectedSignal.id, question); setWorkspace({ ...workspace, investigations: workspace.investigations.some((item) => item.id === investigation.id) ? workspace.investigations.map((item) => item.id === investigation.id ? investigation : item) : [...workspace.investigations, investigation] }); setModal(null); select('investigations', investigation.id); })} />}
    {modal === 'export' && selectedBrief && <ExportDialog brief={selectedBrief} disabled={writeDisabled} onClose={() => setModal(null)} onPreview={() => api.previewExport(selectedBrief.id)} onExecute={(preview, nextDestination, idempotencyKey) => api.executeExport(selectedBrief.id, preview, nextDestination, idempotencyKey)} onDone={(message) => { setModal(null); setNotice(message); }} />}
    {modal === 'status' && <DataStatusDialog sources={workspace.sources} onClose={() => setModal(null)} />}
  </main>;
}
