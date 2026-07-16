import { useCallback, useEffect, useMemo, useState } from 'react';
import type React from 'react';
import { createRoot } from 'react-dom/client';
import { Badge, Button, EmptyState, Status } from '@glint/ui';
import './styles.css';
import { createApi, eligibleResearchSources, projectRunEvent, type BriefExport, type CloudSourceConfiguration, type CloudSourceCreateInput, type ConsentPreview, type ExportPreview, type GlintApi, type GrantedImport, type ImportProgress, type NoCounterEvidenceSearchInput, type PendingImport, type SignalSample, type SourceViewer } from './api';
import type { CollectionSchedule, DecisionBrief, Destination, Evidence, Impact, Investigation, Signal, SourceHealth, Urgency, WatchlistSummary, WorkspaceState } from './domain';
import { authenticityLabel, priorityLabel, selectCloudScheduleWatchlist } from './domain';
import { prepareCsvImport } from './imports';
import { completeLocalExport, TerminalAuditError } from './export-flow';
import { clearAccessToken, isNativeRuntime, SessionExpiredError, SessionFailure, storeAccessToken } from './session';
import { loadWorkspaceCache, storeWorkspaceCache } from './cache';
import { createSerialMutationQueue } from './brief-mutations';

const label = (value: string) => value.replaceAll('_', ' ');
const displayTime = (date: string | null) => date ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(date)) : 'Never';
const bytes = (value: number) => new Intl.NumberFormat(undefined, { style: 'unit', unit: 'byte', notation: 'compact' }).format(value);
const incompleteCopy = (value: string) => !value.trim() || /\b(pending|tbd|todo|placeholder)\b/i.test(value);

function SessionRoot() {
  const [api, setApi] = useState<GlintApi | null>(null);
  const [failure, setFailure] = useState<SessionFailure | null>(null);
  const [loading, setLoading] = useState(true);
  const native = isNativeRuntime();
  const expire = useCallback(() => {
    setApi(null);
    setFailure(new SessionExpiredError());
    if (isNativeRuntime()) void clearAccessToken().catch(() => setFailure(new SessionFailure('unavailable', 'The expired session could not be cleared from macOS Keychain.')));
  }, []);
  const connect = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    try {
      const connected = await createApi(expire);
      setApi(connected.api);
    } catch (reason) {
      setApi(null);
      setFailure(reason instanceof SessionFailure ? reason : new SessionFailure('unavailable', reason instanceof Error ? reason.message : 'Secure session bootstrap failed.'));
    } finally {
      setLoading(false);
    }
  }, [expire]);
  useEffect(() => { void connect(); }, [connect]);
  if (loading) return <div className="loading-shell" aria-live="polite"><div className="skeleton title" /><div className="skeleton wide" /><p>Loading secure session…</p></div>;
  if (!api) return <SessionRecovery failure={failure} native={native} onReconnect={connect} />;
  return <App api={api} />;
}

function SessionRecovery({ failure, native, onReconnect }: { failure: SessionFailure | null; native: boolean; onReconnect: () => Promise<void> }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await storeAccessToken(token);
      setToken('');
      await onReconnect();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to store the secure session.');
    } finally {
      setBusy(false);
    }
  };
  return <main className="fatal"><section className="session-recovery" aria-labelledby="session-title"><h1 id="session-title">Secure session required</h1><p role="alert">{failure?.message ?? 'Glint could not initialize its secure session.'}</p>{native ? <><p>Paste a current access token. It is sent directly to the native macOS Keychain command and is never written to localStorage.</p><label>Access token<input type="password" autoComplete="off" spellCheck={false} value={token} disabled={busy} onChange={(event) => setToken(event.target.value)} /></label>{error && <p role="alert">{error}</p>}<div className="actions"><Button className="primary" disabled={busy || !token.trim()} onClick={() => void save()}>Store in Keychain & reconnect</Button><Button disabled={busy} onClick={() => void clearAccessToken().then(onReconnect).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Unable to clear the secure session.'))}>Clear stored session</Button></div></> : <><p>Browser sessions are allowed only in development and API-mode E2E. Configure VITE_GLINT_ACCESS_TOKEN in that process and restart it.</p><Button onClick={() => void onReconnect()}>Retry secure bootstrap</Button></>}</section></main>;
}

function App({ api }: { api: GlintApi }) {
  const [workspace, setWorkspace] = useState<WorkspaceState | null>(null);
  const [destination, setDestination] = useState<Destination>('inbox');
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [modal, setModal] = useState<'plan' | 'export' | 'status' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [runConnection, setRunConnection] = useState<'connected' | 'reconnecting' | 'reset'>('connected');
  const selectedSignal = workspace?.signals.find((signal) => signal.id === selectedId) ?? workspace?.signals[0];
  const selectedInvestigation = workspace?.investigations.find((item) => item.id === selectedId) ?? workspace?.investigations[0];
  const selectedBrief = workspace?.briefs.find((item) => item.id === selectedId) ?? workspace?.briefs.find((brief) => brief.status === 'draft') ?? workspace?.briefs[0];

  const reload = useCallback(async () => {
    setError(null);
    try {
      const next = await api.bootstrap();
      let cachedAt: string | null = null;
      try { cachedAt = await storeWorkspaceCache(next); }
      catch (reason) { setError(reason instanceof Error ? `Live workspace loaded, but the protected offline cache was not updated: ${reason.message}` : 'Live workspace loaded, but the protected offline cache was not updated.'); }
      setWorkspace({ ...next, cachedAt });
      setOffline(false);
      setSelectedId((current) => current || next.signals[0]?.id || next.investigations[0]?.id || next.briefs[0]?.id || '');
    } catch (reason) {
      if (reason instanceof SessionExpiredError) { setError(reason.message); return; }
      const cached = await loadWorkspaceCache(api.workspaceId).catch(() => null);
      if (cached) {
        setWorkspace(cached);
        setOffline(true);
        setSelectedId((current) => current || cached.signals[0]?.id || cached.investigations[0]?.id || cached.briefs[0]?.id || '');
        setError(`Live API unavailable. Protected read-only cache loaded from ${displayTime(cached.cachedAt)}.`);
      } else setError(reason instanceof Error ? reason.message : 'Unable to load the workspace.');
    } finally { setLoading(false); }
  }, [api]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    const online = () => { void reload(); };
    const offlineEvent = () => setOffline(true);
    window.addEventListener('online', online);
    window.addEventListener('offline', offlineEvent);
    return () => { window.removeEventListener('online', online); window.removeEventListener('offline', offlineEvent); };
  }, [reload]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') setModal(null); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const updateInvestigation = useCallback((investigation: Investigation) => setWorkspace((current) => current ? { ...current, investigations: current.investigations.map((item) => item.id === investigation.id ? investigation : item) } : current), []);

  useEffect(() => {
    const run = selectedInvestigation?.run;
    if (offline || !run || (['completed', 'failed', 'cancelled'].includes(run.state) && selectedInvestigation.events.length > 0)) return;
    const controller = new AbortController();
    const storageKey = `glint:run-cursor:${run.id}`;
    const terminalReplay = ['completed', 'failed', 'cancelled'].includes(run.state) && selectedInvestigation.events.length === 0;
    const stored = terminalReplay ? { eventId: '', sequence: 0 } : JSON.parse(localStorage.getItem(storageKey) ?? '{"eventId":"","sequence":0}') as { eventId: string; sequence: number };
    let cursor = stored;
    let delay = 500;
    let recovery: Promise<void> | null = null;
    let resetRequested = false;
    const refresh = async (preserveEvents = true) => {
      const refreshed = await api.refreshInvestigation(selectedInvestigation.id);
      setWorkspace((current) => current ? { ...current, investigations: current.investigations.map((item) => item.id === refreshed.id ? { ...refreshed, events: preserveEvents ? item.events : [] } : item) } : current);
    };
    const connect = async (): Promise<void> => {
      setRunConnection('connected');
      try {
        await api.subscribeRun(run.id, cursor.eventId || undefined, controller.signal, (event) => {
          if (event.eventId === cursor.eventId || event.sequence <= cursor.sequence) return;
          if (cursor.sequence > 0 && event.sequence > cursor.sequence + 1) {
            setRunConnection('reset');
            recovery = (async () => {
              await api.runSnapshot(run.id);
              cursor = { eventId: '', sequence: 0 };
              localStorage.removeItem(storageKey);
              await refresh(false);
            })();
            throw new Error('Run event sequence gap; snapshot reset required.');
          }
          setWorkspace((current) => current ? { ...current, investigations: current.investigations.map((item) => item.id === selectedInvestigation.id ? projectRunEvent(item, event) : item) } : current);
          if (/^(evidence|claim|synthesis)\.|^review\./.test(event.eventType) || event.eventType === 'run.completed') void refresh();
          cursor = { eventId: event.eventId, sequence: event.sequence };
          localStorage.setItem(storageKey, JSON.stringify(cursor));
        }, async (reset) => {
          resetRequested = true;
          setRunConnection('reset');
          await api.runSnapshot(run.id);
          cursor = { eventId: '', sequence: 0 };
          localStorage.removeItem(storageKey);
          await refresh(false);
          void reset.latestSequence;
        });
        const snapshot = await api.runSnapshot(run.id);
        if (!controller.signal.aborted && (resetRequested || !['completed', 'failed', 'cancelled'].includes(snapshot.state))) {
          resetRequested = false;
          throw new Error('SSE stream requires replay or closed before the run reached a terminal state.');
        }
      } catch {
        if (!controller.signal.aborted) {
          if (recovery) { await recovery; recovery = null; }
          setRunConnection('reconnecting');
          await new Promise((resolve) => window.setTimeout(resolve, delay));
          delay = Math.min(delay * 2, 8000);
          if (!controller.signal.aborted) await connect();
        }
      }
    };
    void connect();
    return () => controller.abort();
  }, [offline, selectedInvestigation?.id, selectedInvestigation?.run?.id, updateInvestigation]);

  const select = (next: Destination, id: string) => { setDestination(next); setSelectedId(id); };
  const updateBrief = (brief: DecisionBrief) => setWorkspace((current) => current ? { ...current, briefs: current.briefs.map((item) => item.id === brief.id ? brief : item), navigation: { ...current.navigation, draftDecisionBriefCount: current.briefs.filter((item) => item.id === brief.id ? brief.status === 'draft' : item.status === 'draft').length } } : current);
  const safe = async (task: () => Promise<void>) => { try { setError(null); await task(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Action failed.'); } };

  if (loading) return <div className="loading-shell" aria-live="polite"><div className="skeleton title" /><div className="skeleton wide" /><div className="skeleton wide" /></div>;
  if (error && !workspace) return <div className="fatal"><EmptyState title="Glint could not load this workspace" body={`${error} No cached content is available.`} action={<Button onClick={() => void reload()}>Retry connection</Button>} /></div>;
  if (!workspace) return null;
  const writeDisabled = offline;
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
        {destination === 'decisions' && selectedBrief && <BriefDetail brief={selectedBrief} disabled={writeDisabled} hasReviewedCounterEvidence={hasReviewedCounterEvidence} onUpdate={(judgment, recommendationId, recommendationBody, status) => safe(async () => updateBrief(await api.updateBrief(selectedBrief.id, judgment, recommendationId, recommendationBody, status)))} onSaveCounterEvidenceSearch={(input) => safe(async () => updateBrief(await api.saveNoCounterEvidenceSearch(selectedBrief.id, input)))} onReady={() => safe(async () => updateBrief(await api.markReady(selectedBrief.id)))} onExport={() => setModal('export')} />}
        {destination === 'monitoring' && <Monitoring api={api} workspaceId={workspace.workspaceId} sources={workspace.sources} watchlists={workspace.watchlists} schedules={workspace.schedules} disabled={writeDisabled} onComplete={reload} />}
      </section>
    </div>
    {modal === 'plan' && selectedSignal && <PlanDialog signal={selectedSignal} sources={workspace.sources} disabled={writeDisabled} onClose={() => setModal(null)} onRun={(question) => safe(async () => { const investigation = await api.createInvestigation(selectedSignal.id, question); setWorkspace({ ...workspace, investigations: workspace.investigations.some((item) => item.id === investigation.id) ? workspace.investigations.map((item) => item.id === investigation.id ? investigation : item) : [...workspace.investigations, investigation] }); setModal(null); select('investigations', investigation.id); })} />}
    {modal === 'export' && selectedBrief && <ExportDialog brief={selectedBrief} disabled={writeDisabled} onClose={() => setModal(null)} onPreview={() => api.previewExport(selectedBrief.id)} onExecute={(preview, nextDestination, idempotencyKey) => api.executeExport(selectedBrief.id, preview, nextDestination, idempotencyKey)} onDone={(message) => { setModal(null); setNotice(message); }} />}
    {modal === 'status' && <StatusDialog sources={workspace.sources} onClose={() => setModal(null)} />}
  </main>;
}

function Sidebar({ destination, workspace, onSelect }: { destination: Destination; workspace: WorkspaceState; onSelect: (value: Destination) => void }) {
  const rows: Array<[Destination, string, string]> = [['inbox', 'Inbox', String(workspace.navigation.unreviewedSignalCount)], ['investigations', 'Investigations', workspace.navigation.investigationNeedsInputCount ? String(workspace.navigation.investigationNeedsInputCount) : ''], ['decisions', 'Decisions', workspace.navigation.draftDecisionBriefCount ? String(workspace.navigation.draftDecisionBriefCount) : ''], ['monitoring', 'Monitoring', workspace.navigation.monitoringHealth === 'degraded' ? 'Degraded' : '']];
  return <nav className="sidebar" aria-label="Primary"><p>WORK</p>{rows.slice(0, 3).map(([id, name, count]) => <button className={destination === id ? 'nav-row active' : 'nav-row'} onClick={() => onSelect(id)} key={id}><span>{name}</span>{count && <Badge tone={id === 'decisions' ? 'warning' : 'neutral'}>{count}</Badge>}</button>)}<p>MANAGE</p>{rows.slice(3).map(([id, name, count]) => <button className={destination === id ? 'nav-row active' : 'nav-row'} onClick={() => onSelect(id)} key={id}><span>{name}</span>{count && <Badge tone="warning">⚠ {count}</Badge>}</button>)}<div className="sidebar-bottom"><small>{workspace.workspaceName}</small><small>{authenticityLabel(workspace.authenticity)}</small></div></nav>;
}

function ListPane({ destination, workspace, selectedId, filter, setFilter, onSelect }: { destination: Destination; workspace: WorkspaceState; selectedId: string; filter: string; setFilter: (value: string) => void; onSelect: (id: string) => void }) {
  const items = useMemo(() => destination === 'inbox' ? workspace.signals : destination === 'investigations' ? workspace.investigations : destination === 'decisions' ? workspace.briefs : [], [destination, workspace]);
  const titles = { inbox: 'Inbox', investigations: 'Investigations', decisions: 'Decisions', monitoring: 'Monitoring' };
  if (destination === 'monitoring') return <section className="list-pane"><header><h1>Monitoring</h1><p>Source health</p></header><div className="list-empty">Cloud and imported sources are shown in the detail pane.</div></section>;
  const matching = items.filter((item) => ('title' in item ? item.title : 'question' in item ? item.question : '').toLowerCase().includes(filter.toLowerCase()));
  return <section className="list-pane"><header><div><h1>{titles[destination]}</h1><span>{matching.length} connected</span></div><input value={filter} onChange={(event) => setFilter(event.target.value)} aria-label={`Search ${titles[destination]}`} placeholder="Filter current list" /></header>{matching.length === 0 ? <EmptyState title="No matching items" body="No connected object matches this filter." action={<Button onClick={() => setFilter('')}>Clear filters</Button>} /> : <div>{destination === 'inbox' && (matching as Signal[]).map((item) => <SignalRow item={item} selected={selectedId === item.id} onClick={() => onSelect(item.id)} key={item.id} />)}{destination === 'investigations' && (matching as Investigation[]).map((item) => <button className={selectedId === item.id ? 'list-row selected' : 'list-row'} onClick={() => onSelect(item.id)} key={item.id}><Status tone={item.status === 'needs_input' ? 'warning' : 'info'}>{label(item.status)}</Status><strong>{item.question}</strong><small>{item.evidence.length} evidence · {item.run ? label(item.run.state) : 'No run'}</small></button>)}{destination === 'decisions' && (matching as DecisionBrief[]).map((item) => <button className={selectedId === item.id ? 'list-row selected' : 'list-row'} onClick={() => onSelect(item.id)} key={item.id}><Status tone={item.status === 'decision_ready' ? 'positive' : 'warning'}>{label(item.status)}</Status><strong>{item.question}</strong><small>v{item.version} · {item.freshness === 'current' ? 'Evidence current' : 'Evidence updated'}</small></button>)}</div>}</section>;
}

function SignalRow({ item, selected, onClick }: { item: Signal; selected: boolean; onClick: () => void }) {
  return <button className={selected ? 'signal-row selected' : 'signal-row'} onClick={onClick}><div><Badge tone="info">{authenticityLabel(item.authenticity)}</Badge> <Status tone="info">Detected: {item.confidence}</Status><strong>{item.title}</strong><small>Watchlist {item.watchlistId} · {item.triggerRules.join(', ')}</small><small>{item.independentSources} independent sources · snapshot {displayTime(item.snapshotAt)}</small></div><span className="priority">{priorityLabel(item)}</span></button>;
}

function SignalDetail({ signal, sources, disabled, onLoadSamples, onTriage, onStart }: { signal: Signal; sources: SourceHealth[]; disabled: boolean; onLoadSamples: () => Promise<SignalSample[]>; onTriage: (impact: Impact, urgency: Urgency) => void; onStart: () => void }) {
  const [impact, setImpact] = useState<Impact>(signal.impact);
  const [urgency, setUrgency] = useState<Urgency>(signal.urgency);
  const [samples, setSamples] = useState<SignalSample[]>([]);
  const [sampleError, setSampleError] = useState<string | null>(null);
  const [viewer, setViewer] = useState<SourceViewer | null>(null);
  useEffect(() => { setImpact(signal.impact); setUrgency(signal.urgency); }, [signal]);
  useEffect(() => {
    setSamples([]); setSampleError(null); setViewer(null);
    if (disabled) return;
    void onLoadSamples().then(setSamples).catch((reason: unknown) => setSampleError(reason instanceof Error ? reason.message : 'Representative samples are unavailable.'));
  }, [signal.id, disabled]);
  return <div className="detail-body">
    <DetailHeader title={signal.title} status={<><Badge tone="info">{authenticityLabel(signal.authenticity)}</Badge><Status tone="info">Detected: {signal.confidence}</Status></>} />
    <Section title="What changed"><p>{signal.confidenceExplanation}</p><dl><dt>Current window</dt><dd>{displayTime(signal.window.currentStart)} → {displayTime(signal.window.currentEnd)} · {signal.currentCount} current / {signal.mentionCount} mentions</dd><dt>Baseline window</dt><dd>{displayTime(signal.window.baselineStart)} → {displayTime(signal.window.baselineEnd)} · {signal.baselineCount} baseline</dd><dt>Growth / robust z</dt><dd>{signal.growthRatio.toFixed(2)}× / {signal.robustZ.toFixed(2)}</dd><dt>Cross-source</dt><dd>{signal.crossSourceConfirmation ? 'Yes' : 'No'} · {signal.independentSources} independent / {signal.totalSourceCount} total sources</dd><dt>Platforms</dt><dd>{signal.platformCount}</dd></dl></Section>
    <Section title="Why detected"><ul>{signal.triggerRules.map((rule) => <li key={rule}>{rule}</li>)}</ul><p className="hint">Detection confidence is detector-owned and is not a fact-correctness score.</p></Section>
    <Section title="Representative samples">{sampleError && <p role="alert">{sampleError}</p>}{!sampleError && !disabled && samples.length === 0 && <p>Loading exact SignalEvidence samples…</p>}{disabled && <p>Representative bodies are not retained in the redacted offline cache.</p>}{samples.map((sample) => <article className="evidence" key={sample.contentVersionId}><Badge tone={sample.role === 'trigger' ? 'warning' : 'info'}>{sample.role}</Badge><h4>{sample.viewer.title}</h4><p>“{sample.viewer.highlightedQuote}”</p><small>{sample.viewer.source.name} · {sample.viewer.author ?? 'author unavailable'} · published {displayTime(sample.viewer.publishedAt)} · captured {displayTime(sample.viewer.capturedAt)} · independence {sample.viewer.independenceGroupId ?? 'not assigned'} · contribution {sample.contribution}</small><div><Button onClick={() => setViewer(sample.viewer)}>Open Source Viewer</Button></div></article>)}</Section>
    <Section title="Data quality & limitations"><ul>{signal.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></Section>
    <Section title="Per-source freshness">{signal.perSourceFreshness.length === 0 ? <p>No source freshness projection was attached.</p> : signal.perSourceFreshness.map((freshness) => { const source = sources.find((item) => item.id === freshness.sourceConnectionId); return <p key={freshness.sourceConnectionId}><Status tone={freshness.state === 'current' ? 'positive' : 'warning'}>{freshness.state}</Status> {source?.name ?? freshness.sourceConnectionId} · last success {displayTime(freshness.lastSuccessAt)}</p>; })}</Section>
    <Section title="Triage"><p className="hint">Confirm both human assessments to derive Priority.</p><div className="triage-grid"><label>Business Impact<select value={impact ?? ''} onChange={(event) => setImpact((event.target.value || null) as Impact)} disabled={disabled}><option value="">Unassessed</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="unknown">Unknown</option></select></label><label>Urgency<select value={urgency ?? ''} onChange={(event) => setUrgency((event.target.value || null) as Urgency)} disabled={disabled}><option value="">Unassessed</option><option value="now">Now</option><option value="this_week">This week</option><option value="monitor">Monitor</option><option value="unknown">Unknown</option></select></label><div><span>Derived Priority</span><strong>{impact === signal.impact && urgency === signal.urgency ? priorityLabel(signal) : impact === 'unknown' || urgency === 'unknown' ? 'Unranked · insufficient input' : 'Calculated on confirmation'}</strong><small>Policy: priority-matrix-v1</small></div></div><Button disabled={disabled || !impact || !urgency} onClick={() => onTriage(impact, urgency)}>Confirm Impact & Urgency</Button></Section>
    <div className="actions"><Button className="primary" disabled={disabled || signal.status === 'new'} onClick={onStart}>Start Investigation</Button></div>
    {viewer && <SourceViewerDialog viewer={viewer} onClose={() => setViewer(null)} />}
  </div>;
}

function InvestigationDetail({ investigation, disabled, runConnection, onOpenEvidence, onReviewEvidence, onReviewClaim, onCreateSynthesis, onReviseSynthesis, onReviewSynthesis, onCreateBrief, onCancelRun, onRetryRun }: { investigation: Investigation; disabled: boolean; runConnection: 'connected' | 'reconnecting' | 'reset'; onOpenEvidence: (evidence: Evidence) => Promise<SourceViewer>; onReviewEvidence: (evidence: Evidence, decision: 'valid' | 'weak' | 'rejected') => void; onReviewClaim: (id: string, decision: 'verify' | 'reject') => void; onCreateSynthesis: () => void; onReviseSynthesis: (summary: string) => void; onReviewSynthesis: (decision: 'verify' | 'reject') => void; onCreateBrief: () => void; onCancelRun: () => void; onRetryRun: () => void }) {
  const [tab, setTab] = useState<'overview' | 'evidence' | 'claims' | 'synthesis' | 'runs'>('overview');
  const [summary, setSummary] = useState(investigation.synthesis?.executiveSummary ?? '');
  const [viewer, setViewer] = useState<SourceViewer | null>(null);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [viewerLoadingId, setViewerLoadingId] = useState<string | null>(null);
  const [viewedEvidenceIds, setViewedEvidenceIds] = useState<Set<string>>(() => new Set());
  useEffect(() => setSummary(investigation.synthesis?.executiveSummary ?? ''), [investigation.synthesis?.versionId, investigation.synthesis?.executiveSummary]);
  const openEvidence = async (evidence: Evidence) => {
    setViewerError(null);
    setViewerLoadingId(evidence.id);
    try {
      const loaded = await onOpenEvidence(evidence);
      setViewer(loaded);
      setViewedEvidenceIds((current) => new Set(current).add(evidence.id));
    } catch (reason) {
      setViewerError(reason instanceof Error ? reason.message : 'Source Viewer could not load the immutable content.');
    } finally {
      setViewerLoadingId(null);
    }
  };
  const synthesis = investigation.synthesis;
  const reviewable = synthesis?.status === 'draft' || synthesis?.status === 'needs_review';
  return <div className="detail-body"><DetailHeader title={investigation.question} status={<><Badge tone="info">{authenticityLabel(investigation.authenticity)}</Badge><Status tone={investigation.status === 'completed' ? 'positive' : 'info'}>{label(investigation.status)}</Status></>} /><div className="tabs" role="tablist">{(['overview', 'evidence', 'claims', 'synthesis', 'runs'] as const).map((item) => <button role="tab" aria-selected={tab === item} onClick={() => setTab(item)} key={item}>{label(item)}</button>)}</div>{tab === 'overview' && <><Section title="Pinned scope"><p>Source connections: {investigation.sourceConnectionIds.length ? investigation.sourceConnectionIds.join(', ') : 'Unavailable'}.</p><p>ScopeVersion <code>{investigation.scopeVersionId}</code>. Model egress is not authorized.</p></Section><Section title="Research run"><p>{investigation.run ? <>Attempt {investigation.run.attemptNumber} · <Status tone={investigation.run.state === 'completed' ? 'positive' : investigation.run.state === 'failed' ? 'danger' : 'info'}>{investigation.run.state}</Status> · sequence {investigation.run.latestSequence}</> : 'No run snapshot.'}</p></Section></>}{tab === 'evidence' && <Section title="Evidence review"><p className="hint">Open the immutable Source Viewer before appending a review.</p>{viewerError && <p role="alert">{viewerError}</p>}{investigation.evidence.map((evidence) => { const viewed = viewedEvidenceIds.has(evidence.id) || evidence.status !== 'proposed'; return <article className="evidence" key={evidence.id}><Badge tone={evidence.stance === 'supports' ? 'positive' : 'warning'}>{evidence.stance}</Badge><blockquote>“{evidence.quote}”</blockquote><small>ContentVersion {evidence.contentVersionId} · {evidence.provenance.extractionMethod}</small><div><Status tone={evidence.status === 'valid' ? 'positive' : evidence.status === 'proposed' ? 'warning' : 'neutral'}>{evidence.status}</Status><Button disabled={viewerLoadingId === evidence.id} onClick={() => void openEvidence(evidence)}>{viewerLoadingId === evidence.id ? 'Loading source…' : viewed ? 'Reopen source' : 'Open source'}</Button><Button disabled={disabled || !viewed} onClick={() => onReviewEvidence(evidence, 'valid')}>Valid</Button><Button disabled={disabled || !viewed} onClick={() => onReviewEvidence(evidence, 'weak')}>Weak</Button><Button disabled={disabled || !viewed} onClick={() => onReviewEvidence(evidence, 'rejected')}>Reject</Button></div></article>; })}</Section>}{tab === 'claims' && <Section title="Claims">{investigation.claims.map((claim) => { const supports = claim.evidenceLinks.filter((link) => link.stance === 'supports').length; const opposes = claim.evidenceLinks.filter((link) => link.stance === 'opposes').length; return <article className="claim" key={claim.id}><Status tone={claim.status === 'verified' ? 'positive' : 'warning'}>{label(claim.status)}</Status><h3>{claim.text}</h3><p>Supporting {supports} · Opposing {opposes}</p><small>{claim.limitations.join(' ')}</small><div><Button disabled={disabled || claim.status === 'verified'} onClick={() => onReviewClaim(claim.id, 'verify')}>Verify</Button><Button disabled={disabled || claim.status === 'rejected'} onClick={() => onReviewClaim(claim.id, 'reject')}>Reject</Button></div></article>; })}</Section>}{tab === 'synthesis' && <Section title="Investigation synthesis">{synthesis ? <><Badge tone="info">{synthesis.generationMethod} synthesis</Badge><label>Executive summary<textarea aria-label="Synthesis executive summary" disabled={disabled || synthesis.status === 'verified'} value={summary} onChange={(event) => setSummary(event.target.value)} /></label><h4>Business implications</h4><ul>{synthesis.businessImplications.map((item) => <li key={item}>{item}</li>)}</ul><h4>Limitations</h4><ul>{synthesis.limitations.map((item) => <li key={item}>{item}</li>)}</ul><p><Status tone={synthesis.status === 'verified' ? 'positive' : synthesis.status === 'rejected' ? 'danger' : 'warning'}>{synthesis.status}</Status></p><div className="actions"><Button disabled={disabled || synthesis.status === 'verified' || incompleteCopy(summary) || summary === synthesis.executiveSummary} onClick={() => onReviseSynthesis(summary)}>Save revision</Button><Button disabled={disabled || !reviewable} onClick={() => onReviewSynthesis('verify')}>Verify synthesis</Button><Button disabled={disabled || !reviewable} onClick={() => onReviewSynthesis('reject')}>Reject synthesis</Button></div></> : <><p>Create a reviewable synthesis from the exact verified ClaimVersions. Creation never approves it.</p><Button disabled={disabled || !investigation.claims.some((claim) => claim.status === 'verified')} onClick={onCreateSynthesis}>Create synthesis</Button></>}<Button className="primary" disabled={disabled || synthesis?.status !== 'verified'} onClick={onCreateBrief}>Create Decision Brief</Button></Section>}{tab === 'runs' && <Section title="Run events"><div className="sse"><Status tone={runConnection === 'connected' ? 'positive' : 'warning'}>{runConnection === 'connected' ? 'SSE connected' : runConnection === 'reconnecting' ? 'SSE reconnecting — run is not failed' : 'SSE cursor reset — snapshot reloaded'}</Status>{investigation.run && ['queued', 'running', 'waiting_for_input'].includes(investigation.run.state) && <Button disabled={disabled} onClick={onCancelRun}>Cancel run</Button>}{investigation.run && ['failed', 'cancelled'].includes(investigation.run.state) && <Button disabled={disabled} onClick={onRetryRun}>Retry run</Button>}</div>{investigation.events.map((event) => <p className="run-event" key={event.id}><code>{event.sequence}</code> {event.message} <small>{displayTime(event.timestamp)}</small></p>)}</Section>}{viewer && <SourceViewerDialog viewer={viewer} onClose={() => setViewer(null)} />}</div>;
}

function SourceViewerDialog({ viewer, onClose }: { viewer: SourceViewer; onClose: () => void }) {
  return <div className="modal-backdrop"><section className="modal source-viewer" role="dialog" aria-modal="true" aria-label="Source Viewer"><h2>{viewer.title}</h2><p><Status tone={viewer.availability === 'captured' ? 'positive' : 'danger'}>{viewer.availability}</Status> <Badge tone="info">{authenticityLabel(viewer.authenticity)}</Badge></p><dl><dt>Source</dt><dd>{viewer.source.name} · {viewer.source.kind}</dd><dt>Author</dt><dd>{viewer.author ?? 'Not supplied'}</dd><dt>Captured</dt><dd>{displayTime(viewer.capturedAt)}</dd><dt>Published</dt><dd>{displayTime(viewer.publishedAt)}</dd><dt>Independence group</dt><dd>{viewer.independenceGroupId ?? 'Not assigned'}</dd><dt>ContentVersion</dt><dd><code>{viewer.contentVersionId}</code></dd>{viewer.canonicalUrl && <><dt>Canonical URL</dt><dd>{viewer.canonicalUrl}</dd></>}</dl><h3>Immutable captured body</h3><pre>{viewer.beforeQuote}<mark>{viewer.highlightedQuote}</mark>{viewer.afterQuote}</pre><div className="modal-actions"><Button onClick={onClose}>Close Source Viewer</Button></div></section></div>;
}

function BriefDetail({ brief, disabled, hasReviewedCounterEvidence, onUpdate, onSaveCounterEvidenceSearch, onReady, onExport }: { brief: DecisionBrief; disabled: boolean; hasReviewedCounterEvidence: boolean; onUpdate: (judgment: string, recommendationId: string, recommendationBody: string, status: 'accepted' | 'rejected') => Promise<void>; onSaveCounterEvidenceSearch: (input: NoCounterEvidenceSearchInput) => Promise<void>; onReady: () => Promise<void>; onExport: () => void }) {
  const judgmentBlock = brief.blockDocument.blocks.find((block) => block.type === 'pm_judgment');
  const recommendations = brief.blockDocument.blocks.filter((block): block is Extract<typeof block, { type: 'recommendation' }> => block.type === 'recommendation');
  const searchRecord = brief.blockDocument.noCounterEvidenceSearch;
  const [judgment, setJudgment] = useState(judgmentBlock?.body ?? '');
  const [recommendationBodies, setRecommendationBodies] = useState<Record<string, string>>(() => Object.fromEntries(recommendations.map((item) => [item.id, item.body])));
  const [searchQueries, setSearchQueries] = useState(() => searchRecord?.queries.join('\n') ?? '');
  const [exclusionCriteria, setExclusionCriteria] = useState(() => searchRecord?.exclusionCriteria.join('\n') ?? '');
  const [searchLimitations, setSearchLimitations] = useState(() => searchRecord?.limitations.join('\n') ?? '');
  const [mutationBusy, setMutationBusy] = useState(false);
  const [mutationQueue] = useState(() => createSerialMutationQueue(setMutationBusy));
  useEffect(() => () => mutationQueue.dispose(), [mutationQueue]);
  useEffect(() => setJudgment(judgmentBlock?.body ?? ''), [brief.versionId, judgmentBlock?.body]);
  useEffect(() => setRecommendationBodies(Object.fromEntries(recommendations.map((item) => [item.id, item.body]))), [brief.versionId]);
  useEffect(() => {
    setSearchQueries(searchRecord?.queries.join('\n') ?? '');
    setExclusionCriteria(searchRecord?.exclusionCriteria.join('\n') ?? '');
    setSearchLimitations(searchRecord?.limitations.join('\n') ?? '');
  }, [brief.versionId, searchRecord]);
  const lines = (value: string) => value.split('\n').map((item) => item.trim()).filter(Boolean);
  const parsedSearch = { queries: lines(searchQueries), exclusionCriteria: lines(exclusionCriteria), limitations: lines(searchLimitations) };
  const searchInputComplete = parsedSearch.queries.length > 0 && parsedSearch.exclusionCriteria.length > 0 && parsedSearch.limitations.length > 0;
  const ready = brief.readiness === 'decision_ready';
  const mutationDisabled = disabled || ready || mutationBusy;
  const acceptedComplete = recommendations.some((item) => item.recommendationStatus === 'accepted' && !incompleteCopy(item.body));
  return <div className="detail-body" aria-busy={mutationBusy}>
    <DetailHeader title={brief.question} status={<><Badge tone="info">{authenticityLabel(brief.authenticity)}</Badge><Status tone={ready ? 'positive' : 'warning'}>{ready ? 'Decision-ready' : 'Draft incomplete'}</Status><span>v{brief.version} · Evidence {brief.freshness}</span>{mutationBusy && <span role="status">Saving brief changes…</span>}</>} />
    {brief.blockDocument.blocks.map((block) => block.type === 'pm_judgment'
      ? <ContentBlock type="PM judgment" title="Product Implications" key={block.id}>
        <textarea aria-label="PM Judgment" disabled={mutationDisabled} value={judgment} onChange={(event) => setJudgment(event.target.value)} />
        <small>Actor {block.actorId} · required for readiness</small>
      </ContentBlock>
      : block.type === 'recommendation'
        ? <ContentBlock type="Recommendation" title="Recommendation" key={block.id}>
          <textarea aria-label={`Recommendation ${block.id}`} disabled={mutationDisabled} value={recommendationBodies[block.id] ?? block.body} onChange={(event) => setRecommendationBodies((current) => ({ ...current, [block.id]: event.target.value }))} />
          <div>
            <Status tone={block.recommendationStatus === 'accepted' ? 'positive' : block.recommendationStatus === 'rejected' ? 'danger' : 'warning'}>{block.recommendationStatus}</Status>
            <Button disabled={mutationDisabled || incompleteCopy(judgment) || incompleteCopy(recommendationBodies[block.id] ?? block.body)} onClick={() => void mutationQueue.run(() => onUpdate(judgment, block.id, recommendationBodies[block.id] ?? block.body, 'accepted'))}>{block.recommendationStatus === 'accepted' ? 'Save accepted' : 'Accept'}</Button>
            <Button disabled={mutationDisabled || !judgment.trim() || !(recommendationBodies[block.id] ?? block.body).trim()} onClick={() => void mutationQueue.run(() => onUpdate(judgment, block.id, recommendationBodies[block.id] ?? block.body, 'rejected'))}>Reject</Button>
          </div>
        </ContentBlock>
        : block.type === 'fact'
          ? <ContentBlock type="Fact" title="Verified fact" key={block.id}><p>{block.body}</p><small>{block.contentVersionIds.map((id) => `ContentVersion ${id}`).join(' · ')}</small></ContentBlock>
          : <ContentBlock type="Deterministic synthesis" title="Evidence summary" key={block.id}><p>{block.body}</p><small>{block.generatorVersion} · {block.generationMethod}</small></ContentBlock>)}
    <section className="counter-evidence-search" role="region" aria-label="Counter-evidence search">
      <div className="counter-evidence-heading"><h3>Counter-evidence search</h3><Status tone={searchRecord ? 'positive' : 'warning'}>{searchRecord ? 'Recorded' : 'Not recorded'}</Status>{hasReviewedCounterEvidence && <Badge tone="info">Reviewed opposing evidence present</Badge>}</div>
      <p className="hint">Only save this record after you actually performed the search. Glint records the method you enter; it does not run or infer a counter-evidence search.</p>
      {searchRecord && <dl><dt>Pinned sources</dt><dd>{searchRecord.sourceConnectionIds.join(', ')}</dd><dt>Pinned window</dt><dd>{searchRecord.windowStart} to {searchRecord.windowEnd}</dd></dl>}
      <label>Queries, one per line<textarea aria-label="Counter-evidence search queries" disabled={mutationDisabled} value={searchQueries} onChange={(event) => setSearchQueries(event.target.value)} /></label>
      <label>Exclusion criteria, one per line<textarea aria-label="Counter-evidence exclusion criteria" disabled={mutationDisabled} value={exclusionCriteria} onChange={(event) => setExclusionCriteria(event.target.value)} /></label>
      <label>Limitations, one per line<textarea aria-label="Counter-evidence search limitations" disabled={mutationDisabled} value={searchLimitations} onChange={(event) => setSearchLimitations(event.target.value)} /></label>
      <Button disabled={mutationDisabled || !searchInputComplete} onClick={() => void mutationQueue.run(() => onSaveCounterEvidenceSearch(parsedSearch))}>Save counter-evidence search</Button>
    </section>
    <div className="readiness">
      <h3>Decision-ready review</h3>
      <ul><li>{!incompleteCopy(judgment) ? '✓' : '○'} PM Judgment authored without placeholder wording</li><li>{acceptedComplete ? '✓' : '○'} At least one complete Recommendation accepted</li><li>{brief.blockDocument.blocks.some((item) => item.type === 'fact') ? '✓' : '○'} Verified facts with exact references</li><li>{hasReviewedCounterEvidence ? '✓ Reviewed opposing evidence is present' : searchRecord ? '✓ Explicit no-counter search scope recorded' : '○ No-counter search record may be required; the backend will make the final readiness decision'}</li></ul>
      <Button className="primary" disabled={mutationDisabled || incompleteCopy(judgment) || !acceptedComplete} onClick={() => void mutationQueue.run(onReady)}>Mark Decision-ready</Button>
      <Button disabled={!ready || disabled || mutationBusy || brief.freshness === 'evidence_stale'} onClick={onExport}>Export PRD Research Input</Button>
    </div>
  </div>;
}

function Monitoring({ api, workspaceId, sources, watchlists, schedules, disabled, onComplete }: { api: GlintApi; workspaceId: string; sources: SourceHealth[]; watchlists: WatchlistSummary[]; schedules: CollectionSchedule[]; disabled: boolean; onComplete: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [prepared, setPrepared] = useState<Awaited<ReturnType<typeof prepareCsvImport>> | null>(null);
  const [pending, setPending] = useState<PendingImport | null>(null);
  const [consentPreview, setConsentPreview] = useState<ConsentPreview | null>(null);
  const [granted, setGranted] = useState<GrantedImport | null>(null);
  const [progress, setProgress] = useState<ImportProgress | null>(null);
  const [cloudMessage, setCloudMessage] = useState<string | null>(null);
  const trackProgress = useCallback((next: ImportProgress) => setProgress((current) => ({ ...current, ...next })), []);
  const importedSources = sources.filter((item) => item.sourceKind === 'imported_dataset');
  const [sourceId, setSourceId] = useState('');
  const source = importedSources.find((item) => item.id === sourceId);
  const activeWatchlists = useMemo(
    () => watchlists.filter((item) => item.status === 'active'),
    [watchlists],
  );
  const recommendedCloudWatchlist = useMemo(
    () => selectCloudScheduleWatchlist(watchlists, sources),
    [sources, watchlists],
  );

  useEffect(() => {
    if (disabled) return;
    void api.recoverImport(trackProgress).then((result) => { if (result) void onComplete(); }).catch((reason: unknown) => setProgress({ stage: 'retryable_failure', message: reason instanceof Error ? reason.message : 'Unable to recover the active import.', retryable: true }));
  }, [api, disabled, onComplete, trackProgress]);

  const cloudAction = async (task: () => Promise<unknown>, success: string) => {
    try { setCloudMessage(null); await task(); setCloudMessage(success); await onComplete(); }
    catch (reason) { setCloudMessage(reason instanceof Error ? reason.message : 'Cloud source action failed.'); }
  };
  const resetImport = () => { setPrepared(null); setPending(null); setConsentPreview(null); setGranted(null); };
  const review = async () => {
    if (!file) return;
    setProgress(null); resetImport();
    try { setPrepared(await prepareCsvImport(file)); }
    catch (reason) { setProgress({ stage: 'cancelled', message: reason instanceof Error ? reason.message : 'Unable to parse CSV.' }); }
  };
  const createSession = async () => {
    if (!prepared || !source) return;
    try { setPending(await api.createImportSession(prepared, source, trackProgress)); }
    catch (reason) { setProgress({ stage: 'retryable_failure', message: reason instanceof Error ? reason.message : 'Unable to create ImportSession.', retryable: false }); }
  };
  const previewConsent = async () => {
    if (!pending) return;
    try { setConsentPreview(await api.previewImportConsent(pending, trackProgress)); }
    catch (reason) { setProgress((current) => ({ ...current, stage: 'retryable_failure', message: reason instanceof Error ? reason.message : 'Unable to preview upload consent.', sessionId: pending.sessionId, retryable: false })); }
  };
  const grant = async () => {
    if (!consentPreview) return;
    try { setGranted(await api.grantImportUpload(consentPreview, trackProgress)); }
    catch (reason) {
      setConsentPreview(null);
      setProgress((current) => ({ ...current, stage: 'retryable_failure', message: `${reason instanceof Error ? reason.message : 'Unable to record upload consent.'} Request a fresh no-side-effect scope preview before confirming again.`, sessionId: consentPreview.sessionId, retryable: false }));
    }
  };
  const start = async () => {
    if (!granted) return;
    try { await api.uploadGrantedImport(granted, trackProgress); resetImport(); await onComplete(); }
    catch { /* progress keeps the exact actionable state */ }
  };
  const retry = async () => {
    if (!progress?.sessionId) return;
    try { await api.retryImport(progress.sessionId, trackProgress); await onComplete(); }
    catch { /* progress remains actionable */ }
  };
  const cancel = async () => {
    const sessionId = progress?.sessionId ?? pending?.sessionId ?? granted?.sessionId;
    if (!sessionId) return;
    try { await api.cancelImport(sessionId, trackProgress); resetImport(); }
    catch (reason) { setProgress((current) => ({ ...current, stage: 'cancelled', message: reason instanceof Error ? reason.message : 'Unable to cancel import.', sessionId })); }
  };

  return <div className="detail-body">
    <DetailHeader title="Monitoring" status={<Badge tone="info">Source Connections</Badge>} />
    <Section title="Initial baseline state">
      {watchlists.length === 0 ? <p>No Watchlist exists yet.</p> : watchlists.map((watchlist) => <article className="source-health" aria-label={`${watchlist.name} baseline`} key={watchlist.id}><h4>{watchlist.name}</h4><p><Status tone={watchlist.initialBaseline.status === 'ready' ? 'positive' : 'warning'}>{watchlist.initialBaseline.status === 'collecting' ? 'Collecting initial baseline' : watchlist.initialBaseline.status}</Status> {watchlist.initialBaseline.currentCount} current / {watchlist.initialBaseline.requiredCount} required · {watchlist.initialBaseline.candidateCount} candidates</p><p>{watchlist.initialBaseline.reason ?? (watchlist.initialBaseline.status === 'ready' ? 'Initial baseline is ready for change detection.' : 'Waiting for terminal collection content.')}</p><small>Expected detectable {displayTime(watchlist.initialBaseline.expectedDetectableAt)} · last terminal run {displayTime(watchlist.initialBaseline.lastTerminalRunAt)} · current {watchlist.rules.currentWindowDays}d / baseline {watchlist.rules.baselineWindowDays}d</small></article>)}
    </Section>
    <Section title="Cloud source setup">
      <p>GitHub and RSS targets are persisted as strict, single-target cloud configurations. Credential references are replaceable opaque references; secret values are never rendered.</p>
      <CloudSourceCreator disabled={disabled} onCreate={(input) => cloudAction(() => api.createCloudSource(input), `${input.connectorType.toUpperCase()} source created in draft state.`)} />
      {cloudMessage && <p role="status">{cloudMessage}</p>}
    </Section>
    <Section title="Source health">
      {sources.map((item) => {
        const sourceSchedules = schedules.filter((schedule) => schedule.sourceConnectionId === item.id);
        return <SourceCard source={item} schedules={sourceSchedules} activeWatchlists={activeWatchlists} recommendedWatchlist={recommendedCloudWatchlist} disabled={disabled} key={item.id}
          onConfigure={(configuration) => cloudAction(() => api.updateCloudSource(item, configuration), `${item.name} configuration and bound schedules synchronized atomically.`)}
          onActivate={() => cloudAction(() => api.activateSource(item), `${item.name} activation requested.`)} onDisable={() => cloudAction(() => api.disableSource(item), `${item.name} disabled; historical content retained.`)} onRemove={() => cloudAction(() => api.removeSource(item), `${item.name} removed from active monitoring; historical content retained.`)} onReconnect={() => cloudAction(() => api.reconnectSource(item), `${item.name} reconnect validation completed.`)} onHealth={() => cloudAction(() => api.validateSource(item), `${item.name} health validation completed.`)}
          onSchedule={(query, watchlist) => cloudAction(() => api.createSchedule(item, watchlist, query), `${item.name} schedule created.`)} onSetSchedule={(schedule, enabled) => cloudAction(() => api.setScheduleEnabled(schedule, enabled), `${item.name} schedule ${enabled ? 'enabled' : 'paused'}.`)} />;
      })}
    </Section>
    <Section title="Import CSV">
      <p>Parsing and SHA-256 digests happen in this client; filesystem paths and file content never enter ImportSession metadata.</p>
      {importedSources.length === 0 ? <div><p>No Imported Dataset source is available.</p><Button className="primary" disabled={disabled} onClick={() => void cloudAction(() => api.setupImportedDataset(), 'Imported Dataset project, source, and active Watchlist created.')}>Setup Imported Dataset</Button></div> : <>
        <label>Destination source<select aria-label="Destination source" value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">Choose an Imported Dataset…</option>{importedSources.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
        <input aria-label="CSV file" type="file" accept=".csv,text/csv" disabled={disabled || Boolean(pending)} onChange={(event) => { setFile(event.target.files?.[0] ?? null); resetImport(); setProgress(null); }} />
        {file && <p><strong>{file.name}</strong> · {bytes(file.size)}</p>}
        <Button className="primary" disabled={disabled || !file || !source || Boolean(pending)} onClick={() => void review()}>Review upload scope</Button>
      </>}
      {prepared && source && <div className="import-review" role="region" aria-label="Upload scope review">
        <h4>Metadata session and upload scope</h4><p><Badge tone="warning">Upload scope</Badge> Workspace storage only · Model egress: none.</p>
        <dl><dt>Destination workspace</dt><dd><code>{workspaceId}</code></dd><dt>Destination source</dt><dd>{source.name} · <code>{source.id}</code></dd><dt>Parser / schema</dt><dd>{prepared.parserVersion} / {prepared.schemaVersion}</dd><dt>Rows / columns</dt><dd>{prepared.rowCount} / {prepared.selectedScope.columns.join(', ')}</dd><dt>File digest</dt><dd><code>{prepared.fileDigest}</code></dd><dt>Local manifest digest</dt><dd><code>{prepared.localManifestDigest}</code></dd></dl>
        {consentPreview && <div className="consent-preview" role="region" aria-label="Exact consent preview"><h4>Exact no-side-effect consent preview</h4><dl><dt>Destination workspace</dt><dd><code>{consentPreview.destinationWorkspaceId}</code></dd><dt>Object key</dt><dd><code>{consentPreview.objectKey}</code></dd><dt>Maximum bytes</dt><dd>{bytes(consentPreview.maximumBytes)}</dd><dt>Media type</dt><dd>{consentPreview.mediaType}</dd><dt>Grant expires</dt><dd>{displayTime(consentPreview.expiresAt)}</dd><dt>Selected scope digest</dt><dd><code>{consentPreview.selectedScopeDigest}</code></dd><dt>Consent scope digest</dt><dd><code>{consentPreview.scopeDigest}</code></dd><dt>Model egress</dt><dd>none · {consentPreview.policyVersion}</dd></dl></div>}
        <div className="actions"><Button onClick={resetImport}>Cancel import</Button>{!pending && <Button className="primary" disabled={disabled} onClick={() => void createSession()}>Create metadata session</Button>}{pending && !consentPreview && !granted && <Button className="primary" disabled={disabled} onClick={() => void previewConsent()}>Preview consent scope</Button>}{consentPreview && !granted && <Button className="primary" disabled={disabled} onClick={() => void grant()}>Confirm scoped upload grant</Button>}{granted && <Button className="primary" disabled={disabled} onClick={() => void start()}>Confirm upload bytes</Button>}</div>
      </div>}
      {progress && <div className="import-progress" aria-live="polite"><Status tone={progress.stage === 'retryable_failure' ? 'warning' : progress.stage === 'completed' ? 'positive' : 'info'}>{progress.message}</Status>{progress.destinationWorkspaceId && <dl><dt>Destination workspace</dt><dd><code>{progress.destinationWorkspaceId}</code></dd><dt>Object key</dt><dd><code>{progress.objectKey}</code></dd><dt>Maximum bytes</dt><dd>{bytes(progress.maximumBytes ?? 0)}</dd><dt>Grant expires</dt><dd>{displayTime(progress.expiresAt ?? null)}</dd></dl>}<div className="actions">{progress.sessionId && !['completed', 'cancelled'].includes(progress.stage) && <Button disabled={disabled} onClick={() => void cancel()}>Cancel active import</Button>}{progress.stage === 'retryable_failure' && progress.retryable && <Button className="primary" disabled={disabled} onClick={() => void retry()}>Retry finalization</Button>}</div></div>}
    </Section>
  </div>;
}

function CloudSourceCreator({ disabled, onCreate }: { disabled: boolean; onCreate: (input: CloudSourceCreateInput) => Promise<unknown> }) {
  const [connectorType, setConnectorType] = useState<'github' | 'rss'>('github');
  const [name, setName] = useState('Product feedback GitHub');
  const [credentialRef, setCredentialRef] = useState('env://github_token');
  const [cadence, setCadence] = useState<'daily' | 'weekly' | 'manual'>('daily');
  const [timezone, setTimezone] = useState('UTC');
  const [owner, setOwner] = useState('openai');
  const [repository, setRepository] = useState('glint-ui-contracts');
  const [feedName, setFeedName] = useState('Product releases');
  const [feedUrl, setFeedUrl] = useState('https://example.com/product-releases.xml');
  const submit = () => onCreate(connectorType === 'github' ? { connectorType, name, credentialRef, cadence, timezone, owner, repository, includeIssues: true, includeDiscussions: true, includeReleases: true } : { connectorType, name, cadence, timezone, feedName, feedUrl });
  return <form className="cloud-source-form" aria-label="Cloud source setup" onSubmit={(event) => { event.preventDefault(); void submit(); }}><label>Cloud connector<select value={connectorType} disabled={disabled} onChange={(event) => setConnectorType(event.target.value as 'github' | 'rss')}><option value="github">GitHub</option><option value="rss">RSS</option></select></label><label>Cloud source name<input value={name} disabled={disabled} required onChange={(event) => setName(event.target.value)} /></label>{connectorType === 'github' ? <><label>Credential reference<input value={credentialRef} disabled={disabled} required pattern="^(vault|keychain|stronghold|env)://.+" onChange={(event) => setCredentialRef(event.target.value)} /></label><label>GitHub owner<input value={owner} disabled={disabled} required onChange={(event) => setOwner(event.target.value)} /></label><label>GitHub repository<input value={repository} disabled={disabled} required onChange={(event) => setRepository(event.target.value)} /></label></> : <><label>RSS feed name<input value={feedName} disabled={disabled} required onChange={(event) => setFeedName(event.target.value)} /></label><label>RSS feed URL<input value={feedUrl} type="url" pattern="https://.*" disabled={disabled} required onChange={(event) => setFeedUrl(event.target.value)} /></label></>}<label>Cloud cadence<select value={cadence} disabled={disabled} onChange={(event) => setCadence(event.target.value as typeof cadence)}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="manual">Manual</option></select></label><label>Cloud timezone<input value={timezone} disabled={disabled} required onChange={(event) => setTimezone(event.target.value)} /></label><Button type="submit" className="primary" disabled={disabled}>Create cloud source</Button></form>;
}

function SourceCard({ source, schedules, activeWatchlists, recommendedWatchlist, disabled, onConfigure, onActivate, onDisable, onRemove, onReconnect, onHealth, onSchedule, onSetSchedule }: { source: SourceHealth; schedules: CollectionSchedule[]; activeWatchlists: WatchlistSummary[]; recommendedWatchlist?: WatchlistSummary; disabled: boolean; onConfigure: (configuration: CloudSourceConfiguration) => Promise<unknown>; onActivate: () => Promise<unknown>; onDisable: () => Promise<unknown>; onRemove: () => Promise<unknown>; onReconnect: () => Promise<unknown>; onHealth: () => Promise<unknown>; onSchedule: (query: string, watchlist: WatchlistSummary) => Promise<unknown>; onSetSchedule: (schedule: CollectionSchedule, enabled: boolean) => Promise<unknown> }) {
  const [name, setName] = useState(source.name);
  const [cadence, setCadence] = useState(source.cadence ?? 'daily');
  const [timezone, setTimezone] = useState(source.timezone ?? 'UTC');
  const [credentialRef, setCredentialRef] = useState('env://github_token');
  const [githubOwner, setGithubOwner] = useState(source.sourceConfig?.connectorType === 'github' ? source.sourceConfig.repositories[0]?.owner ?? '' : '');
  const [githubRepository, setGithubRepository] = useState(source.sourceConfig?.connectorType === 'github' ? source.sourceConfig.repositories[0]?.repository ?? '' : '');
  const [rssFeedName, setRssFeedName] = useState(source.sourceConfig?.connectorType === 'rss' ? source.sourceConfig.feeds[0]?.name ?? '' : '');
  const [rssFeedUrl, setRssFeedUrl] = useState(source.sourceConfig?.connectorType === 'rss' ? source.sourceConfig.feeds[0]?.feedUrl ?? '' : '');
  const [query, setQuery] = useState('permission friction');
  const [watchlistId, setWatchlistId] = useState(recommendedWatchlist?.id ?? '');
  const [busy, setBusy] = useState(false);
  useEffect(() => { setName(source.name); setCadence(source.cadence ?? 'daily'); setTimezone(source.timezone ?? 'UTC'); if (source.sourceConfig?.connectorType === 'github') { setGithubOwner(source.sourceConfig.repositories[0]?.owner ?? ''); setGithubRepository(source.sourceConfig.repositories[0]?.repository ?? ''); } else if (source.sourceConfig?.connectorType === 'rss') { setRssFeedName(source.sourceConfig.feeds[0]?.name ?? ''); setRssFeedUrl(source.sourceConfig.feeds[0]?.feedUrl ?? ''); } }, [source.id, source.name, source.cadence, source.timezone, source.sourceConfig]);
  useEffect(() => { setWatchlistId((current) => activeWatchlists.some((watchlist) => watchlist.id === current) ? current : recommendedWatchlist?.id ?? ''); }, [activeWatchlists, recommendedWatchlist?.id, source.id]);
  const run = async (task: () => Promise<unknown>) => { setBusy(true); try { await task(); } finally { setBusy(false); } };
  const activeWatchlist = activeWatchlists.find((watchlist) => watchlist.id === watchlistId);
  const schedulable = source.sourceKind === 'cloud' && source.cadence !== 'manual' && ['validating', 'healthy', 'degraded'].includes(source.status) && Boolean(activeWatchlist);
  const targetValid = source.connectorType === 'github' ? Boolean(githubOwner.trim() && githubRepository.trim() && credentialRef.trim()) : Boolean(rssFeedName.trim() && rssFeedUrl.startsWith('https://'));
  const configuration: CloudSourceConfiguration = { name, cadence, timezone, ...(source.connectorType === 'github' ? { credentialRef, githubOwner, githubRepository } : { rssFeedName, rssFeedUrl }) };
  return <article className="source-health" aria-label={`${source.name} source`}>
    <div><Status tone={source.health.state === 'healthy' ? 'positive' : source.health.state === 'unknown' ? 'neutral' : 'warning'}>{source.health.state}</Status> <Badge tone="info">{source.connectorType}</Badge> <Badge>{authenticityLabel(source.authenticity)}</Badge> <Status tone={source.status === 'disabled' ? 'neutral' : source.status === 'failed' ? 'danger' : 'info'}>{source.status}</Status></div>
    <h4>{source.name}</h4><p>{source.sourceKind} · {source.runtime}{source.cadence ? ` · ${source.cadence} · ${source.timezone}` : ''}</p>
    <p>Freshness: <strong>{source.freshness.state}</strong> · last success {displayTime(source.freshness.lastSuccessAt)} · last run {displayTime(source.lastRunAt)}</p><p>Health checked {displayTime(source.health.checkedAt)}{source.health.lastErrorCode ? ` · ${source.health.lastErrorCode}` : ''}</p>
    <small>Capabilities: {source.capabilities.length ? source.capabilities.join(', ') : 'none'} · row version {source.rowVersion}</small>
    {source.sourceKind === 'cloud' && <><div className="source-config">
      <label>Name<input aria-label={`${source.name} configuration name`} value={name} disabled={disabled || busy} onChange={(event) => setName(event.target.value)} /></label>
      <label>Cadence<select aria-label={`${source.name} configuration cadence`} value={cadence} disabled={disabled || busy} onChange={(event) => setCadence(event.target.value as typeof cadence)}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="manual">Manual</option></select></label>
      <label>Timezone<input aria-label={`${source.name} configuration timezone`} value={timezone} disabled={disabled || busy} onChange={(event) => setTimezone(event.target.value)} /></label>
      {source.connectorType === 'github' ? <><label>GitHub owner<input aria-label={`${source.name} GitHub owner`} value={githubOwner} disabled={disabled || busy} onChange={(event) => setGithubOwner(event.target.value)} /></label><label>GitHub repository<input aria-label={`${source.name} GitHub repository`} value={githubRepository} disabled={disabled || busy} onChange={(event) => setGithubRepository(event.target.value)} /></label><label>Replacement credential reference<input aria-label={`${source.name} replacement credential reference`} value={credentialRef} pattern="^(vault|keychain|stronghold|env)://.+" disabled={disabled || busy} onChange={(event) => setCredentialRef(event.target.value)} /></label></> : <><label>RSS feed name<input aria-label={`${source.name} RSS feed name`} value={rssFeedName} disabled={disabled || busy} onChange={(event) => setRssFeedName(event.target.value)} /></label><label>RSS feed URL<input aria-label={`${source.name} RSS feed URL`} type="url" value={rssFeedUrl} disabled={disabled || busy} onChange={(event) => setRssFeedUrl(event.target.value)} /></label></>}
      <Button aria-label={`Save ${source.name} configuration`} disabled={disabled || busy || !name.trim() || !timezone.trim() || !targetValid} onClick={() => void run(() => onConfigure(configuration))}>Save configuration & sync schedules</Button>
    </div><div className="actions"><Button aria-label={`Check ${source.name} health`} disabled={disabled || busy} onClick={() => void run(onHealth)}>Validate health</Button>{(source.status === 'draft' || source.status === 'disabled') && <Button aria-label={`Activate ${source.name}`} disabled={disabled || busy} onClick={() => void run(onActivate)}>Activate</Button>}{source.status !== 'draft' && source.status !== 'disabled' && <Button aria-label={`Reconnect ${source.name}`} disabled={disabled || busy} onClick={() => void run(onReconnect)}>Reconnect</Button>}{source.status !== 'disabled' && <Button aria-label={`Disable ${source.name}`} disabled={disabled || busy} onClick={() => void run(onDisable)}>Disable</Button>}<Button aria-label={`Remove ${source.name}`} disabled={disabled || busy} onClick={() => void run(onRemove)}>Remove (retain history)</Button></div>
    <div className="schedule-controls"><label>Schedule Watchlist<select aria-label={`${source.name} schedule Watchlist`} value={watchlistId} disabled={disabled || busy} onChange={(event) => setWatchlistId(event.target.value)}><option value="">Choose an active Watchlist…</option>{activeWatchlists.map((watchlist) => <option value={watchlist.id} key={watchlist.id}>{watchlist.name}</option>)}</select></label><label>Schedule query<input aria-label={`${source.name} schedule query`} value={query} disabled={disabled || busy} onChange={(event) => setQuery(event.target.value)} /></label><Button aria-label={`Schedule ${source.name}`} disabled={disabled || busy || !schedulable || schedules.length > 0} onClick={() => activeWatchlist ? void run(() => onSchedule(query, activeWatchlist)) : undefined}>Create schedule</Button><small>{source.cadence === 'manual' ? 'Manual cadence never creates an enabled schedule.' : activeWatchlist ? `Active Watchlist: ${activeWatchlist.name}; source will be bound before schedule creation.` : 'Choose an active Watchlist explicitly; Glint never silently mixes cloud and imported scopes.'}</small></div>
    {schedules.map((schedule) => <p key={schedule.id}><Status tone={schedule.enabled ? 'positive' : 'neutral'}>{schedule.enabled ? 'scheduled' : 'paused'}</Status> every {schedule.cadenceSeconds}s · next {displayTime(schedule.nextRunAt)} <Button aria-label={`${schedule.enabled ? 'Pause' : 'Enable'} ${source.name} schedule`} disabled={disabled || busy || (!schedule.enabled && source.cadence === 'manual')} onClick={() => void run(() => onSetSchedule(schedule, !schedule.enabled))}>{schedule.enabled ? 'Pause' : 'Enable'}</Button></p>)}</>}
  </article>;
}

function DetailHeader({ title, status }: { title: string; status: React.ReactNode }) { return <header className="detail-header"><h2>{title}</h2><div>{status}</div></header>; }
function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section className="section"><h3>{title}</h3>{children}</section>; }
function ContentBlock({ type, title, children }: { type: string; title: string; children: React.ReactNode }) { return <section className="content-block"><Badge tone={type === 'Fact' ? 'neutral' : type === 'PM judgment' ? 'info' : 'warning'}>{type}</Badge><h3>{title}</h3>{children}</section>; }

function PlanDialog({ signal, sources, disabled, onClose, onRun }: { signal: Signal; sources: SourceHealth[]; disabled: boolean; onClose: () => void; onRun: (question: string) => void }) {
  const [question, setQuestion] = useState(`What decision should we make in response to “${signal.title}”?`);
  const eligible = eligibleResearchSources(signal, sources);
  return <div className="modal-backdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-label="Investigation plan"><h2>Plan Investigation</h2><p>This creates a bounded deterministic run only from Signal-linked, versioned source content. No model egress is authorized.</p><label>Decision Question<textarea value={question} onChange={(event) => setQuestion(event.target.value)} /></label><dl><dt>Time window</dt><dd>{displayTime(signal.window.currentStart)} → {displayTime(signal.window.currentEnd)}</dd><dt>Source content</dt><dd>{eligible.map((item) => item.sourceKind === 'imported_dataset' ? `${item.name} · Imported terminal manifest ${item.currentImportManifestId}` : `${item.name} · Cloud ${item.connectorType} collection · ${item.freshness.state} since ${displayTime(item.freshness.lastSuccessAt)}`).join('\n') || 'No Signal-linked source has eligible versioned content'}</dd><dt>Budget</dt><dd>Up to $4.00 / 15 minutes</dd><dt>Authenticity</dt><dd>{authenticityLabel(signal.authenticity)}</dd></dl><div className="modal-actions"><Button onClick={onClose}>Back to Signal</Button><Button className="primary" disabled={disabled || !question.trim() || eligible.length === 0} onClick={() => onRun(question)}>Run Investigation</Button></div></section></div>;
}

function ExportDialog({ brief, disabled, onClose, onPreview, onExecute, onDone }: { brief: DecisionBrief; disabled: boolean; onClose: () => void; onPreview: () => Promise<ExportPreview>; onExecute: (preview: ExportPreview, destination: BriefExport['destination'], idempotencyKey: string) => Promise<BriefExport>; onDone: (message: string) => void }) {
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [pendingAudit, setPendingAudit] = useState<{ destination: BriefExport['destination']; idempotencyKey: string } | null>(null);
  useEffect(() => { void onPreview().then(setPreview).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Unable to render export preview.')).finally(() => setBusy(false)); }, [onPreview]);
  const finishTerminal = (terminal: BriefExport, destination: BriefExport['destination']) => {
    setPendingAudit(null);
    onDone(`${destination === 'copy_markdown' ? 'Copied' : 'Exported'} PRD Research Input · terminal BriefExport ${terminal.id} · ${authenticityLabel(terminal.authenticity)}.`);
  };
  const retryTerminal = async (destination: BriefExport['destination'], idempotencyKey: string) => {
    if (!preview) return;
    try {
      const terminal = await onExecute(preview, destination, idempotencyKey);
      finishTerminal(terminal, destination);
    } catch (reason) {
      setPendingAudit({ destination, idempotencyKey });
      setError(`Local output completed, but the terminal export audit record failed: ${reason instanceof Error ? reason.message : 'unknown audit error'}. Retry audit recording with the same idempotency key.`);
    }
  };
  const execute = async (action: 'copy' | 'download') => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    const destination = action === 'copy' ? 'copy_markdown' : 'local_download';
    const idempotencyKey = crypto.randomUUID();
    try {
      const terminal = await completeLocalExport(async () => {
        if (action === 'copy') await navigator.clipboard.writeText(preview.renderedContent);
        else { const url = URL.createObjectURL(new Blob([preview.renderedContent], { type: 'text/markdown' })); const link = document.createElement('a'); link.href = url; link.download = `glint-prd-research-input-v${brief.version}.md`; link.click(); URL.revokeObjectURL(url); }
      }, () => onExecute(preview, destination, idempotencyKey));
      finishTerminal(terminal, destination);
    } catch (reason) {
      if (reason instanceof TerminalAuditError) {
        setPendingAudit({ destination, idempotencyKey });
        setError(`Local output completed, but the terminal export audit record failed: ${reason.message}. Retry audit recording with the same idempotency key.`);
      } else {
        setError(`Local ${action} failed; no BriefExport audit record was created. ${reason instanceof Error ? reason.message : ''}`);
      }
      setBusy(false);
      return;
    }
    setBusy(false);
  };
  const retryAudit = async () => { if (!pendingAudit) return; setBusy(true); setError(null); await retryTerminal(pendingAudit.destination, pendingAudit.idempotencyKey); setBusy(false); };
  return <div className="modal-backdrop"><section className="modal export" role="dialog" aria-modal="true" aria-label="PRD Research Input Preview"><h2>PRD Research Input</h2><p>From Decision Brief v{brief.version} · readiness-reviewed · {brief.freshness}</p>{preview && <p className="authenticity-callout"><Badge tone={preview.authenticity === 'seed' ? 'warning' : 'info'}>Data authenticity: {authenticityLabel(preview.authenticity)}</Badge> The canonical server-rendered Markdown below carries the same marker.</p>}{busy && !preview ? <p>Rendering exact-version preview…</p> : preview && <pre>{preview.renderedContent}</pre>}{error && <p role="alert">{error}</p>}<p className="hint">Export type: prd_research_input_markdown. Synthesis and unaccepted recommendations are excluded by policy.</p><div className="modal-actions"><Button onClick={onClose}>Close</Button>{pendingAudit ? <Button className="primary" disabled={disabled || busy} onClick={() => void retryAudit()}>Retry audit record</Button> : <><Button disabled={disabled || busy || !preview} onClick={() => void execute('copy')}>Copy Markdown</Button><Button className="primary" disabled={disabled || busy || !preview} onClick={() => void execute('download')}>Export .md</Button></>}</div></section></div>;
}

function StatusDialog({ sources, onClose }: { sources: SourceHealth[]; onClose: () => void }) {
  return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Data status"><h2>Data status</h2><p><Badge tone="positive">REST API</Badge></p><p>This client only reads and writes through the configured REST API contract.</p>{sources.map((source) => <p key={source.id}><Status tone={source.health.state === 'healthy' ? 'positive' : 'warning'}>{source.health.state}</Status> {source.name} · freshness {source.freshness.state}</p>)}<Button onClick={onClose}>Close</Button></section></div>;
}

createRoot(document.getElementById('root')!).render(<SessionRoot />);
