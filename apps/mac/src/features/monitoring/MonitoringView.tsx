import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Button, Status } from '@glint/ui';
import type { CloudSourceConfiguration, CloudSourceCreateInput, ConsentPreview, GlintApi, GrantedImport, ImportProgress, PendingImport } from '../../api';
import type { CollectionSchedule, SourceHealth, WatchlistSummary } from '../../domain';
import { authenticityLabel, selectCloudScheduleWatchlist } from '../../domain';
import { prepareCsvImport } from '../../imports';
import { DetailHeader, Section } from '../../components/DetailPrimitives';
import { bytes, displayTime } from '../../lib/formatting';

export function MonitoringView({ api, workspaceId, sources, watchlists, schedules, disabled, onComplete }: { api: GlintApi; workspaceId: string; sources: SourceHealth[]; watchlists: WatchlistSummary[]; schedules: CollectionSchedule[]; disabled: boolean; onComplete: () => Promise<void> }) {
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

export function CloudSourceCreator({ disabled, onCreate }: { disabled: boolean; onCreate: (input: CloudSourceCreateInput) => Promise<unknown> }) {
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

export function SourceConfigurationForm({ source, disabled, busy, onSave }: { source: SourceHealth; disabled: boolean; busy: boolean; onSave: (configuration: CloudSourceConfiguration) => Promise<unknown> }) {
  const [name, setName] = useState(source.name);
  const [cadence, setCadence] = useState(source.cadence ?? 'daily');
  const [timezone, setTimezone] = useState(source.timezone ?? 'UTC');
  const [credentialRef, setCredentialRef] = useState('env://github_token');
  const [githubOwner, setGithubOwner] = useState(source.sourceConfig?.connectorType === 'github' ? source.sourceConfig.repositories[0]?.owner ?? '' : '');
  const [githubRepository, setGithubRepository] = useState(source.sourceConfig?.connectorType === 'github' ? source.sourceConfig.repositories[0]?.repository ?? '' : '');
  const [rssFeedName, setRssFeedName] = useState(source.sourceConfig?.connectorType === 'rss' ? source.sourceConfig.feeds[0]?.name ?? '' : '');
  const [rssFeedUrl, setRssFeedUrl] = useState(source.sourceConfig?.connectorType === 'rss' ? source.sourceConfig.feeds[0]?.feedUrl ?? '' : '');
  useEffect(() => { setName(source.name); setCadence(source.cadence ?? 'daily'); setTimezone(source.timezone ?? 'UTC'); if (source.sourceConfig?.connectorType === 'github') { setGithubOwner(source.sourceConfig.repositories[0]?.owner ?? ''); setGithubRepository(source.sourceConfig.repositories[0]?.repository ?? ''); } else if (source.sourceConfig?.connectorType === 'rss') { setRssFeedName(source.sourceConfig.feeds[0]?.name ?? ''); setRssFeedUrl(source.sourceConfig.feeds[0]?.feedUrl ?? ''); } }, [source.id, source.name, source.cadence, source.timezone, source.sourceConfig]);
  const targetValid = source.connectorType === 'github' ? Boolean(githubOwner.trim() && githubRepository.trim() && credentialRef.trim()) : Boolean(rssFeedName.trim() && rssFeedUrl.startsWith('https://'));
  const configuration: CloudSourceConfiguration = { name, cadence, timezone, ...(source.connectorType === 'github' ? { credentialRef, githubOwner, githubRepository } : { rssFeedName, rssFeedUrl }) };
  return <div className="source-config">
    <label>Name<input aria-label={`${source.name} configuration name`} value={name} disabled={disabled || busy} onChange={(event) => setName(event.target.value)} /></label>
    <label>Cadence<select aria-label={`${source.name} configuration cadence`} value={cadence} disabled={disabled || busy} onChange={(event) => setCadence(event.target.value as typeof cadence)}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="manual">Manual</option></select></label>
    <label>Timezone<input aria-label={`${source.name} configuration timezone`} value={timezone} disabled={disabled || busy} onChange={(event) => setTimezone(event.target.value)} /></label>
    {source.connectorType === 'github' ? <><label>GitHub owner<input aria-label={`${source.name} GitHub owner`} value={githubOwner} disabled={disabled || busy} onChange={(event) => setGithubOwner(event.target.value)} /></label><label>GitHub repository<input aria-label={`${source.name} GitHub repository`} value={githubRepository} disabled={disabled || busy} onChange={(event) => setGithubRepository(event.target.value)} /></label><label>Replacement credential reference<input aria-label={`${source.name} replacement credential reference`} value={credentialRef} pattern="^(vault|keychain|stronghold|env)://.+" disabled={disabled || busy} onChange={(event) => setCredentialRef(event.target.value)} /></label></> : <><label>RSS feed name<input aria-label={`${source.name} RSS feed name`} value={rssFeedName} disabled={disabled || busy} onChange={(event) => setRssFeedName(event.target.value)} /></label><label>RSS feed URL<input aria-label={`${source.name} RSS feed URL`} type="url" value={rssFeedUrl} disabled={disabled || busy} onChange={(event) => setRssFeedUrl(event.target.value)} /></label></>}
    <Button aria-label={`Save ${source.name} configuration`} disabled={disabled || busy || !name.trim() || !timezone.trim() || !targetValid} onClick={() => void onSave(configuration)}>Save configuration & sync schedules</Button>
  </div>;
}

export function SourceCard({ source, schedules, activeWatchlists, recommendedWatchlist, disabled, onConfigure, onActivate, onDisable, onRemove, onReconnect, onHealth, onSchedule, onSetSchedule }: { source: SourceHealth; schedules: CollectionSchedule[]; activeWatchlists: WatchlistSummary[]; recommendedWatchlist?: WatchlistSummary; disabled: boolean; onConfigure: (configuration: CloudSourceConfiguration) => Promise<unknown>; onActivate: () => Promise<unknown>; onDisable: () => Promise<unknown>; onRemove: () => Promise<unknown>; onReconnect: () => Promise<unknown>; onHealth: () => Promise<unknown>; onSchedule: (query: string, watchlist: WatchlistSummary) => Promise<unknown>; onSetSchedule: (schedule: CollectionSchedule, enabled: boolean) => Promise<unknown> }) {
  const [query, setQuery] = useState('permission friction');
  const [watchlistId, setWatchlistId] = useState(recommendedWatchlist?.id ?? '');
  const [busy, setBusy] = useState(false);
  useEffect(() => { setWatchlistId((current) => activeWatchlists.some((watchlist) => watchlist.id === current) ? current : recommendedWatchlist?.id ?? ''); }, [activeWatchlists, recommendedWatchlist?.id, source.id]);
  const run = async (task: () => Promise<unknown>) => { setBusy(true); try { await task(); } finally { setBusy(false); } };
  const activeWatchlist = activeWatchlists.find((watchlist) => watchlist.id === watchlistId);
  const schedulable = source.sourceKind === 'cloud' && source.cadence !== 'manual' && ['validating', 'healthy', 'degraded'].includes(source.status) && Boolean(activeWatchlist);
  return <article className="source-health" aria-label={`${source.name} source`} data-source-id={source.id} tabIndex={-1}>
    <div><Status tone={source.health.state === 'healthy' ? 'positive' : source.health.state === 'unknown' ? 'neutral' : 'warning'}>{source.health.state}</Status> <Badge tone="info">{source.connectorType}</Badge> <Badge>{authenticityLabel(source.authenticity)}</Badge> <Status tone={source.status === 'disabled' ? 'neutral' : source.status === 'failed' ? 'danger' : 'info'}>{source.status}</Status></div>
    <h4>{source.name}</h4><p>{source.sourceKind} · {source.runtime}{source.cadence ? ` · ${source.cadence} · ${source.timezone}` : ''}</p>
    <p>Freshness: <strong>{source.freshness.state}</strong> · last success {displayTime(source.freshness.lastSuccessAt)} · last run {displayTime(source.lastRunAt)}</p><p>Health checked {displayTime(source.health.checkedAt)}{source.health.lastErrorCode ? ` · ${source.health.lastErrorCode}` : ''}</p>
    <small>Capabilities: {source.capabilities.length ? source.capabilities.join(', ') : 'none'} · row version {source.rowVersion}</small>
    {source.sourceKind === 'cloud' && <><SourceConfigurationForm source={source} disabled={disabled} busy={busy} onSave={(configuration) => run(() => onConfigure(configuration))} /><div className="actions"><Button aria-label={`Check ${source.name} health`} disabled={disabled || busy} onClick={() => void run(onHealth)}>Validate health</Button>{(source.status === 'draft' || source.status === 'disabled') && <Button aria-label={`Activate ${source.name}`} disabled={disabled || busy} onClick={() => void run(onActivate)}>Activate</Button>}{source.status !== 'draft' && source.status !== 'disabled' && <Button aria-label={`Reconnect ${source.name}`} disabled={disabled || busy} onClick={() => void run(onReconnect)}>Reconnect</Button>}{source.status !== 'disabled' && <Button aria-label={`Disable ${source.name}`} disabled={disabled || busy} onClick={() => void run(onDisable)}>Disable</Button>}<Button aria-label={`Remove ${source.name}`} disabled={disabled || busy} onClick={() => void run(onRemove)}>Remove (retain history)</Button></div>
    <div className="schedule-controls"><label>Schedule Watchlist<select aria-label={`${source.name} schedule Watchlist`} value={watchlistId} disabled={disabled || busy} onChange={(event) => setWatchlistId(event.target.value)}><option value="">Choose an active Watchlist…</option>{activeWatchlists.map((watchlist) => <option value={watchlist.id} key={watchlist.id}>{watchlist.name}</option>)}</select></label><label>Schedule query<input aria-label={`${source.name} schedule query`} value={query} disabled={disabled || busy} onChange={(event) => setQuery(event.target.value)} /></label><Button aria-label={`Schedule ${source.name}`} disabled={disabled || busy || !schedulable || schedules.length > 0} onClick={() => activeWatchlist ? void run(() => onSchedule(query, activeWatchlist)) : undefined}>Create schedule</Button><small>{source.cadence === 'manual' ? 'Manual cadence never creates an enabled schedule.' : activeWatchlist ? `Active Watchlist: ${activeWatchlist.name}; source will be bound before schedule creation.` : 'Choose an active Watchlist explicitly; Glint never silently mixes cloud and imported scopes.'}</small></div>
    {schedules.map((schedule) => <p key={schedule.id}><Status tone={schedule.enabled ? 'positive' : 'neutral'}>{schedule.enabled ? 'scheduled' : 'paused'}</Status> every {schedule.cadenceSeconds}s · next {displayTime(schedule.nextRunAt)} <Button aria-label={`${schedule.enabled ? 'Pause' : 'Enable'} ${source.name} schedule`} disabled={disabled || busy || (!schedule.enabled && source.cadence === 'manual')} onClick={() => void run(() => onSetSchedule(schedule, !schedule.enabled))}>{schedule.enabled ? 'Pause' : 'Enable'}</Button></p>)}</>}
  </article>;
}
