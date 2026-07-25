import type {
  BriefBlock,
  CollectionSchedule,
  DecisionBrief,
  Impact,
  Investigation,
  NavigationSummary,
  RunState,
  Signal,
  SourceHealth,
  Urgency,
  WatchlistSummary,
  WorkspaceState,
} from './domain';
import type { PreparedCsvImport } from './imports';
import {
  asArray,
  asNumber,
  asObject,
  asString,
  mapAuthenticity,
  mapBootstrap,
  mapBrief,
  mapClaim,
  mapEvidence,
  mapInvestigation,
  mapNavigation,
  mapRun,
  mapSchedule,
  mapSignal,
  mapSource,
  mapSynthesis,
  mapWatchlist,
  toWireDocument,
  toWireReference,
  type JsonObject,
} from './mappers';
import { subscribeRunEvents, type RunStreamEvent, type StreamReset } from './sse';
import { resolveAccessToken, SessionExpiredError } from './session';
import { resolveConnectionProfile } from './connection';

export interface ExportPreview {
  renderedContent: string;
  referenceDigest: string;
  exportTimestamp: string;
  exportType: 'prd_research_input_markdown';
  selectionManifest: { block_ids: string[]; include_citations: boolean };
  authenticity: WorkspaceState['authenticity'];
}

export interface BriefExport {
  id: string;
  decisionBriefVersionId: string;
  exportType: 'prd_research_input_markdown';
  destination: 'local_download' | 'copy_markdown';
  outputDigest: string;
  createdAt: string;
  authenticity: WorkspaceState['authenticity'];
}

export interface NoCounterEvidenceSearchInput {
  queries: string[];
  exclusionCriteria: string[];
  limitations: string[];
}

export interface ImportProgress {
  stage: 'creating_session' | 'session_created' | 'previewing_consent' | 'consent_previewed' | 'awaiting_consent' | 'grant_ready' | 'uploading' | 'verifying_upload' | 'finalizing' | 'retryable_failure' | 'completed' | 'cancelled';
  message: string;
  sessionId?: string;
  destinationWorkspaceId?: string;
  objectKey?: string;
  maximumBytes?: number;
  expiresAt?: string;
  jobId?: string;
  attempt?: number;
  retryable?: boolean;
}

export interface ImportResult { sessionId: string; manifestId: string; jobId: string }

export interface SourceViewer {
  contentVersionId: string;
  title: string;
  body: string;
  beforeQuote: string;
  highlightedQuote: string;
  afterQuote: string;
  publishedAt: string | null;
  capturedAt: string;
  availability: 'captured' | 'deleted' | 'unavailable';
  source: { id: string; name: string; kind: SourceHealth['sourceKind'] };
  author: string | null;
  canonicalUrl: string | null;
  independenceGroupId: string | null;
  authenticity: WorkspaceState['authenticity'];
}
export interface SignalSample { contentVersionId: string; role: 'trigger' | 'context'; contribution: number; viewer: SourceViewer }
export type SignalDismissReason = 'duplicate' | 'single_author_spike' | 'irrelevant' | 'known_issue' | 'bad_data' | 'other';

export interface PendingImport { sessionId: string; rowVersion: number; prepared: PreparedCsvImport; source: SourceHealth }
export interface ConsentPreview extends PendingImport { destinationWorkspaceId: string; objectKey: string; maximumBytes: number; mediaType: string; expiresAt: string; selectedScopeDigest: string; scopeDigest: string; policyVersion: string; previewScope: JsonObject }
export interface GrantedImport extends ConsentPreview { uploadGrant: string }

export type CloudSourceCreateInput =
  | { connectorType: 'github'; name: string; credentialRef: string; cadence: 'daily' | 'weekly' | 'manual'; timezone: string; owner: string; repository: string; includeIssues: boolean; includeDiscussions: boolean; includeReleases: boolean }
  | { connectorType: 'rss'; name: string; credentialRef?: string; cadence: 'daily' | 'weekly' | 'manual'; timezone: string; feedName: string; feedUrl: string };

export interface CloudSourceConfiguration {
  name: string;
  cadence: 'daily' | 'weekly' | 'manual';
  timezone: string;
  credentialRef?: string;
  githubOwner?: string;
  githubRepository?: string;
  rssFeedName?: string;
  rssFeedUrl?: string;
}

export interface GlintApi {
  readonly workspaceId: string;
  /** Authenticated workspace-scoped transport for the parallel Quant API. */
  quantRequest?<T = unknown>(path: string, init?: RequestInit): Promise<T>;
  bootstrap(): Promise<WorkspaceState>;
  navigation(): Promise<NavigationSummary>;
  setupImportedDataset(): Promise<void>;
  createCloudSource(input: CloudSourceCreateInput): Promise<SourceHealth>;
  updateCloudSource(source: SourceHealth, configuration: CloudSourceConfiguration): Promise<SourceHealth>;
  activateSource(source: SourceHealth): Promise<SourceHealth>;
  disableSource(source: SourceHealth): Promise<SourceHealth>;
  removeSource(source: SourceHealth): Promise<SourceHealth>;
  reconnectSource(source: SourceHealth): Promise<SourceHealth>;
  validateSource(source: SourceHealth): Promise<SourceHealth>;
  sourceHealth(sourceId: string): Promise<SourceHealth>;
  createSchedule(source: SourceHealth, watchlist: WatchlistSummary, query: string): Promise<CollectionSchedule>;
  setScheduleEnabled(schedule: CollectionSchedule, enabled: boolean): Promise<CollectionSchedule>;
  refreshInvestigation(investigationId: string): Promise<Investigation>;
  runSnapshot(runId: string): Promise<NonNullable<Investigation['run']>>;
  triage(signalId: string, impact: Impact, urgency: Urgency): Promise<Signal>;
  transitionSignal(signalId: string, action: 'monitor' | 'dismiss' | 'undo', details?: { cooldownUntil?: string; dismissReason?: SignalDismissReason; note?: string }): Promise<Signal>;
  canUndoSignal(signal: Signal): boolean;
  createInvestigation(signalId: string, question: string, allowCloudModel?: boolean): Promise<Investigation>;
  startRun(investigationId: string): Promise<Investigation>;
  cancelRun(investigationId: string): Promise<Investigation>;
  retryRun(investigationId: string): Promise<Investigation>;
  signalSamples(signalId: string): Promise<SignalSample[]>;
  reviewEvidence(investigationId: string, evidenceId: string, decision: 'valid' | 'weak' | 'rejected'): Promise<Investigation>;
  sourceViewer(signalId: string, evidence: Investigation['evidence'][number]): Promise<SourceViewer>;
  reviewClaim(investigationId: string, claimId: string, decision: 'verify' | 'reject'): Promise<Investigation>;
  createSynthesis(investigationId: string): Promise<Investigation>;
  reviseSynthesis(investigationId: string, executiveSummary: string): Promise<Investigation>;
  reviewSynthesis(investigationId: string, decision: 'verify' | 'reject'): Promise<Investigation>;
  createBrief(investigationId: string): Promise<DecisionBrief>;
  updateBrief(briefId: string, judgment: string, recommendationId: string, recommendationBody: string, status: 'accepted' | 'rejected'): Promise<DecisionBrief>;
  saveNoCounterEvidenceSearch(briefId: string, input: NoCounterEvidenceSearchInput): Promise<DecisionBrief>;
  markReady(briefId: string): Promise<DecisionBrief>;
  createImportSession(prepared: PreparedCsvImport, source: SourceHealth, onProgress: (progress: ImportProgress) => void): Promise<PendingImport>;
  previewImportConsent(pending: PendingImport, onProgress: (progress: ImportProgress) => void): Promise<ConsentPreview>;
  grantImportUpload(preview: ConsentPreview, onProgress: (progress: ImportProgress) => void): Promise<GrantedImport>;
  uploadGrantedImport(granted: GrantedImport, onProgress: (progress: ImportProgress) => void): Promise<ImportResult>;
  importCsv(prepared: PreparedCsvImport, source: SourceHealth, onProgress: (progress: ImportProgress) => void): Promise<ImportResult>;
  recoverImport(onProgress: (progress: ImportProgress) => void): Promise<ImportResult | null>;
  cancelImport(importId: string, onProgress: (progress: ImportProgress) => void): Promise<void>;
  retryImport(importId: string, onProgress: (progress: ImportProgress) => void): Promise<ImportResult>;
  subscribeRun(runId: string, lastEventId: string | undefined, signal: AbortSignal, onEvent: (event: RunStreamEvent) => void, onReset: (reset: StreamReset) => Promise<void>): Promise<void>;
  previewExport(briefId: string): Promise<ExportPreview>;
  executeExport(briefId: string, preview: ExportPreview, destination: BriefExport['destination'], idempotencyKey: string): Promise<BriefExport>;
}

const sleep = (milliseconds: number) => new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
function signalSessionId(): string {
  if (typeof sessionStorage === 'undefined') return crypto.randomUUID();
  const key = 'glint:signal-disposition-session';
  const existing = sessionStorage.getItem(key);
  if (existing) return existing;
  const created = crypto.randomUUID();
  sessionStorage.setItem(key, created);
  return created;
}

function canonicalJson(value: unknown): string {
  const normalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(normalize);
    if (item && typeof item === 'object') return Object.fromEntries(Object.entries(item as JsonObject).sort(([left], [right]) => left.localeCompare(right)).map(([key, child]) => [key, normalize(child)]));
    return item;
  };
  return JSON.stringify(normalize(value));
}

async function sha256(value: string): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return `sha256:${[...new Uint8Array(bytes)].map((item) => item.toString(16).padStart(2, '0')).join('')}`;
}

const incompleteCopy = (value: string) => !value.trim() || /\b(pending|tbd|todo|placeholder)\b/i.test(value);

export function eligibleResearchSources(signal: Signal, sources: SourceHealth[]): SourceHealth[] {
  const signalSourceIds = new Set(signal.perSourceFreshness.map((item) => item.sourceConnectionId));
  if (signalSourceIds.size === 0) return [];
  return sources.filter((source) => {
    if (!signalSourceIds.has(source.id)) return false;
    if (source.sourceKind === 'imported_dataset') return source.currentImportManifestId !== null;
    if (source.sourceKind === 'cloud') return ['healthy', 'degraded'].includes(source.status) && ['current', 'stale'].includes(source.freshness.state) && source.freshness.lastSuccessAt !== null;
    return false;
  });
}

export class RestAdapter implements GlintApi {
  private latestWorkspace: WorkspaceState | null = null;

  constructor(private readonly baseUrl: string, readonly workspaceId: string, private readonly accessToken: string, private readonly onUnauthorized?: () => void) {
    if (!accessToken.trim()) throw new Error('A non-empty access token is required.');
  }

  private headers(mutating = false, extra?: HeadersInit): Headers {
    const headers = new Headers({ Authorization: `Bearer ${this.accessToken}`, 'X-Workspace-ID': this.workspaceId });
    if (mutating) headers.set('Idempotency-Key', crypto.randomUUID());
    new Headers(extra).forEach((value, key) => headers.set(key, value));
    return headers;
  }

  private async raw(path: string, init: RequestInit = {}, allowNotFound = false): Promise<Response | null> {
    const method = init.method ?? 'GET';
    const mutating = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    const headers = this.headers(mutating, init.headers);
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(`${this.baseUrl}/v1${path}`, { ...init, headers });
    if (response.status === 401) {
      this.onUnauthorized?.();
      throw new SessionExpiredError();
    }
    if (allowNotFound && response.status === 404) return null;
    if (!response.ok) {
      const body = await response.json().catch(() => null) as { error?: { message?: string } } | null;
      throw new Error(body?.error?.message ?? `Request failed (${response.status}).`);
    }
    return response;
  }

  private async request<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.raw(path, init);
    if (!response) throw new Error(`Missing response for ${path}.`);
    return response.json() as Promise<T>;
  }

  async quantRequest<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
    if (!path.startsWith("/quant/") || path.includes("..")) {
      throw new Error("Quant API paths must stay inside /v1/quant/.");
    }
    return this.request<T>(path, init);
  }

  private activeImportKey(): string { return `glint:active-import:${this.workspaceId}`; }

  private rememberImport(importId: string, jobId?: string): void {
    if (typeof localStorage !== 'undefined') localStorage.setItem(this.activeImportKey(), JSON.stringify({ importId, ...(jobId ? { jobId } : {}) }));
  }

  private forgetImport(): void {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(this.activeImportKey());
  }

  private async optional(path: string): Promise<unknown | null> {
    const response = await this.raw(path, {}, true);
    return response ? response.json() : null;
  }

  async bootstrap(): Promise<WorkspaceState> {
    const [bootstrapDto, navigationDto, schedulesDto, membershipsDto] = await Promise.all([this.request('/sync/bootstrap'), this.request('/navigation-summary'), this.request('/collection-schedules'), this.request('/workspaces')]);
    const membership = asArray(membershipsDto, 'WorkspaceMembership list').map((item) => asObject(item, 'WorkspaceMembership')).find((item) => item.workspace_id === this.workspaceId);
    if (!membership || asString(membership.status, 'WorkspaceMembership.status') !== 'active') throw new SessionExpiredError();
    const principalId = asString(membership.user_id, 'WorkspaceMembership.user_id');
    const schedules = this.pageItems(schedulesDto, 'CollectionSchedule page').map(mapSchedule);
    const mapped = mapBootstrap(bootstrapDto, mapNavigation(navigationDto), schedules);
    if (mapped.workspaceId !== this.workspaceId || mapAuthenticity(membership.data_authenticity, 'WorkspaceMembership.data_authenticity') !== mapped.authenticity) throw new Error('Workspace membership scope differs from the bootstrap projection.');
    const state = { ...mapped, principalId, cachedAt: null };
    this.latestWorkspace = state;
    const enriched = await Promise.all(state.investigations.map((investigation) => this.loadInvestigation(investigation.id, investigation)));
    const next = { ...state, investigations: enriched };
    this.latestWorkspace = next;
    return next;
  }

  async navigation(): Promise<NavigationSummary> { return mapNavigation(await this.request('/navigation-summary')); }

  async setupImportedDataset(): Promise<void> {
    const project = asObject(await this.request('/projects', { method: 'POST', body: JSON.stringify({ name: 'Imported research' }) }), 'Project');
    const projectId = asString(project.id, 'Project.id');
    const draftSource = mapSource(await this.request('/sources', { method: 'POST', body: JSON.stringify({ name: 'Imported CSV dataset', source_kind: 'imported_dataset', runtime: 'static_import', connector_type: 'csv', connector_version: 'csv-v1', data_scope: 'workspace_confidential' }) }));
    const source = mapSource(await this.request(`/sources/${draftSource.id}/activate`, { method: 'POST', body: JSON.stringify({ expected_row_version: draftSource.rowVersion, reason: 'Owner PM activated the Imported Dataset source.' }) }));
    const draftWatchlist = mapWatchlist(await this.request('/watchlists', { method: 'POST', body: JSON.stringify({ project_id: projectId, name: 'Imported feedback', objective: 'Monitor imported product feedback for decision-relevant changes.', source_connection_ids: [source.id], rules: { schema_version: 'watchlist-rules-v1', entities: ['product feedback'], query_rules: { include_terms: ['feedback'], exclude_terms: [], languages: [], regions: [] }, cadence: 'manual', current_window_days: 30, baseline_window_days: 90, notification_intent: false } }) }));
    await this.request(`/watchlists/${draftWatchlist.id}/activate`, { method: 'POST', body: JSON.stringify({ expected_row_version: draftWatchlist.rowVersion, reason: 'Owner PM activated the Imported Dataset Watchlist.' }) });
  }

  async createCloudSource(input: CloudSourceCreateInput): Promise<SourceHealth> {
    if (!input.name.trim() || !input.timezone.trim()) throw new Error('Cloud source name and IANA timezone are required.');
    const sourceConfig = input.connectorType === 'github'
      ? { connector_type: 'github', repositories: [{ owner: input.owner, repository: input.repository, include_issues: input.includeIssues, include_discussions: input.includeDiscussions, include_releases: input.includeReleases }] }
      : { connector_type: 'rss', feeds: [{ name: input.feedName, feed_url: input.feedUrl }] };
    return mapSource(await this.request('/sources', { method: 'POST', body: JSON.stringify({
      name: input.name,
      source_kind: 'cloud',
      runtime: 'cloud',
      connector_type: input.connectorType,
      connector_version: `${input.connectorType}-v1`,
      data_scope: 'public',
      source_config: sourceConfig,
      ...(input.credentialRef?.trim() ? { credential_ref: input.credentialRef.trim() } : {}),
      cadence: input.cadence,
      timezone: input.timezone,
    }) }));
  }

  async updateCloudSource(source: SourceHealth, configuration: CloudSourceConfiguration): Promise<SourceHealth> {
    if (source.sourceKind !== 'cloud') throw new Error('Only cloud sources can use cloud configuration.');
    if (!source.sourceConfig) throw new Error('Cloud source configuration is unavailable.');
    const sourceConfig = source.sourceConfig.connectorType === 'github' ? (() => { const target = source.sourceConfig.repositories[0]; if (!target || !configuration.githubOwner?.trim() || !configuration.githubRepository?.trim()) throw new Error('GitHub owner and repository are required.'); return { connector_type: 'github', repositories: [{ owner: configuration.githubOwner.trim(), repository: configuration.githubRepository.trim(), include_issues: target.includeIssues, include_discussions: target.includeDiscussions, include_releases: target.includeReleases }] }; })() : (() => { if (!configuration.rssFeedName?.trim() || !configuration.rssFeedUrl?.trim()) throw new Error('RSS feed name and HTTPS URL are required.'); return { connector_type: 'rss', feeds: [{ name: configuration.rssFeedName.trim(), feed_url: configuration.rssFeedUrl.trim() }] }; })();
    return mapSource(await this.request(`/sources/${source.id}`, { method: 'PATCH', body: JSON.stringify({ name: configuration.name, cadence: configuration.cadence, timezone: configuration.timezone, source_config: sourceConfig, ...(configuration.credentialRef?.trim() ? { credential_ref: configuration.credentialRef.trim() } : {}), expected_row_version: source.rowVersion }) }));
  }

  private async sourceCommand(source: SourceHealth, action: 'activate' | 'disable' | 'remove'): Promise<SourceHealth> {
    if (source.sourceKind !== 'cloud') throw new Error('Only cloud sources support this lifecycle command.');
    return mapSource(await this.request(`/sources/${source.id}/${action}`, { method: 'POST', body: JSON.stringify({ expected_row_version: source.rowVersion, reason: `${action} requested by Owner PM in Glint.` }) }));
  }

  async activateSource(source: SourceHealth): Promise<SourceHealth> { return this.sourceCommand(source, 'activate'); }
  async disableSource(source: SourceHealth): Promise<SourceHealth> { return this.sourceCommand(source, 'disable'); }
  async removeSource(source: SourceHealth): Promise<SourceHealth> { return this.sourceCommand(source, 'remove'); }
  private parseSourceValidationJob(value: unknown, source: SourceHealth, command: 'health_check' | 'reconnect', expectedSourceRowVersion: number) {
    const dto = asObject(value, 'SourceValidationJob');
    const pinnedSourceRowVersion = asNumber(dto.expected_source_row_version, 'SourceValidationJob.expected_source_row_version');
    if (asString(dto.source_connection_id, 'SourceValidationJob.source_connection_id') !== source.id || asString(dto.command, 'SourceValidationJob.command') !== command || pinnedSourceRowVersion !== expectedSourceRowVersion) throw new Error('Source validation job escaped the exact source version.');
    if (mapAuthenticity(dto.data_authenticity, 'SourceValidationJob.data_authenticity') !== source.authenticity) throw new Error('Source validation job authenticity differs from the source.');
    const state = asString(dto.state, 'SourceValidationJob.state');
    if (!['queued', 'claimed', 'completed', 'failed'].includes(state)) throw new Error('Invalid SourceValidationJob.state DTO.');
    return { id: asString(dto.id, 'SourceValidationJob.id'), state, expectedSourceRowVersion: pinnedSourceRowVersion, resultStatus: dto.result_source_status === null ? null : asString(dto.result_source_status, 'SourceValidationJob.result_source_status'), failureCode: dto.failure_code === null ? null : asString(dto.failure_code, 'SourceValidationJob.failure_code'), failureReason: dto.failure_reason === null ? null : asString(dto.failure_reason, 'SourceValidationJob.failure_reason') };
  }
  private async runSourceValidation(source: SourceHealth, command: 'health_check' | 'reconnect'): Promise<SourceHealth> {
    if (source.sourceKind !== 'cloud') throw new Error('Only cloud sources support asynchronous validation.');
    let job = this.parseSourceValidationJob(await this.request(`/sources/${source.id}/${command === 'health_check' ? 'health-check' : 'reconnect'}`, { method: 'POST', body: JSON.stringify({ expected_row_version: source.rowVersion, reason: `${command} requested by Owner PM in Glint.` }) }), source, command, source.rowVersion + 1);
    for (let attempt = 0; attempt < 120 && !['completed', 'failed'].includes(job.state); attempt += 1) {
      await sleep(250);
      job = this.parseSourceValidationJob(await this.request(`/source-validation-jobs/${job.id}`), source, command, job.expectedSourceRowVersion);
    }
    if (job.state === 'failed') throw new Error(`${job.failureCode ?? 'SOURCE_VALIDATION_FAILED'}${job.failureReason ? ` · ${job.failureReason}` : ''}`);
    if (job.state !== 'completed' || !job.resultStatus) throw new Error('Source validation is still running; retry status refresh.');
    const updated = mapSource(await this.request(`/sources/${source.id}`));
    if (updated.status !== job.resultStatus || updated.rowVersion !== job.expectedSourceRowVersion + 1) throw new Error('Terminal SourceValidationJob differs from the exact SourceConnection version.');
    return updated;
  }
  async reconnectSource(source: SourceHealth): Promise<SourceHealth> { return this.runSourceValidation(source, 'reconnect'); }
  async validateSource(source: SourceHealth): Promise<SourceHealth> { return this.runSourceValidation(source, 'health_check'); }
  async sourceHealth(sourceId: string): Promise<SourceHealth> { return mapSource(await this.request(`/sources/${sourceId}/health`)); }

  async createSchedule(source: SourceHealth, watchlist: WatchlistSummary, query: string): Promise<CollectionSchedule> {
    if (source.sourceKind !== 'cloud' || !source.sourceConfig || !source.timezone || !source.cadence) throw new Error('A configured cloud source is required.');
    if (watchlist.status !== 'active') throw new Error('The Watchlist must be active before scheduling.');
    if (source.cadence === 'manual') throw new Error('Manual cadence does not create or enable a collection schedule. Choose daily or weekly first.');
    let boundWatchlist = watchlist;
    if (!watchlist.sourceConnectionIds.includes(source.id)) {
      boundWatchlist = mapWatchlist(await this.request(`/watchlists/${watchlist.id}`, { method: 'PATCH', body: JSON.stringify({ source_connection_ids: [...watchlist.sourceConnectionIds, source.id], expected_row_version: watchlist.rowVersion }) }));
    }
    let queryJson: JsonObject;
    if (source.sourceConfig.connectorType === 'github') {
      const [target] = source.sourceConfig.repositories;
      if (!target || source.sourceConfig.repositories.length !== 1) throw new Error('Scheduling requires exactly one approved GitHub repository.');
      queryJson = { owner: target.owner, repo: target.repository, query: query.trim(), include_issues: target.includeIssues, include_discussions: target.includeDiscussions, include_releases: target.includeReleases, max_pages: 5 };
    } else {
      const [target] = source.sourceConfig.feeds;
      if (!target || source.sourceConfig.feeds.length !== 1) throw new Error('Scheduling requires exactly one approved RSS feed.');
      queryJson = { feed_url: target.feedUrl, feed_title: target.name, query: query.trim(), max_pages: 5 };
    }
    const cadenceSeconds = source.cadence === 'weekly' ? 604800 : 86400;
    return mapSchedule(await this.request('/collection-schedules', { method: 'POST', body: JSON.stringify({ workspace_id: this.workspaceId, source_connection_id: source.id, watchlist_id: boundWatchlist.id, query_json: queryJson, cadence_seconds: cadenceSeconds, timezone: source.timezone, misfire_policy: 'run_once', catch_up: false, overlap_policy: 'skip', next_run_at: new Date(Date.now() + 300_000).toISOString(), enabled: true }) }));
  }

  async setScheduleEnabled(schedule: CollectionSchedule, enabled: boolean): Promise<CollectionSchedule> {
    return mapSchedule(await this.request(`/collection-schedules/${schedule.id}`, { method: 'PATCH', body: JSON.stringify({ enabled, expected_row_version: schedule.rowVersion }) }));
  }

  private pageItems(value: unknown, name: string): unknown[] { return asArray(asObject(value, name).items, `${name}.items`); }

  private async loadInvestigation(investigationId: string, fallback?: Investigation): Promise<Investigation> {
    const [investigationDto, runsDto, claimsDto, synthesisDto, scopesDto] = await Promise.all([
      this.request(`/investigations/${investigationId}`),
      this.request('/research-runs'),
      this.request(`/claims?investigation_id=${encodeURIComponent(investigationId)}`),
      this.optional(`/investigations/${investigationId}/synthesis`),
      this.request(`/investigations/${investigationId}/scope-versions`),
    ]);
    const investigation = mapInvestigation(investigationDto);
    const matchingRuns = this.pageItems(runsDto, 'ResearchRun page').map((item) => ({ dto: asObject(item, 'ResearchRun'), run: mapRun(item) })).filter(({ dto }) => dto.investigation_id === investigationId);
    const latestRun = matchingRuns.sort((left, right) => right.run!.attemptNumber - left.run!.attemptNumber)[0]?.run ?? null;
    const claims = this.pageItems(claimsDto, 'Claim page').map(mapClaim);
    const evidenceIds = [...new Set(claims.flatMap((claim) => claim.evidenceLinks.map((link) => link.evidenceId)))];
    const evidence = await Promise.all(evidenceIds.map(async (evidenceId) => mapEvidence(await this.request(`/evidence/${evidenceId}`))));
    const scopes = this.pageItems(scopesDto, 'InvestigationScope page').map((item) => asObject(item, 'InvestigationScope'));
    const currentScope = scopes.find((scope) => scope.id === investigation.scopeVersionId);
    const sourceScope = currentScope ? asObject(currentScope.source_scope_json, 'InvestigationScope.source_scope_json') : null;
    const timeRange = currentScope ? asObject(currentScope.time_range, 'InvestigationScope.time_range') : null;
    const allowCloudModel = sourceScope ? (() => { if (typeof sourceScope.allow_cloud_model !== 'boolean') throw new Error('Invalid ResearchSourceScope.allow_cloud_model DTO.'); return sourceScope.allow_cloud_model; })() : false;
    return {
      ...investigation,
      sourceConnectionIds: sourceScope ? asArray(sourceScope.source_connection_ids, 'ResearchSourceScope.source_connection_ids').map((item, index) => asString(item, `ResearchSourceScope.source_connection_ids[${index}]`)) : [],
      contentVersionIds: sourceScope ? asArray(sourceScope.content_version_ids, 'ResearchSourceScope.content_version_ids').map((item, index) => asString(item, `ResearchSourceScope.content_version_ids[${index}]`)) : [],
      allowCloudModel,
      timeRange: timeRange ? { start: asString(timeRange.start, 'InvestigationScope.time_range.start'), end: asString(timeRange.end, 'InvestigationScope.time_range.end') } : null,
      run: latestRun,
      claims,
      evidence,
      synthesis: synthesisDto ? mapSynthesis(synthesisDto) : null,
      events: fallback?.events ?? [],
    };
  }

  async refreshInvestigation(investigationId: string): Promise<Investigation> {
    const fallback = this.latestWorkspace?.investigations.find((item) => item.id === investigationId);
    return this.loadInvestigation(investigationId, fallback);
  }

  async runSnapshot(runId: string): Promise<NonNullable<Investigation['run']>> {
    const run = mapRun(await this.request(`/research-runs/${runId}`));
    if (!run) throw new Error('Invalid ResearchRun snapshot.');
    return run;
  }

  async triage(id: string, impact: Impact, urgency: Urgency): Promise<Signal> {
    const current = this.latestWorkspace?.signals.find((signal) => signal.id === id) ?? (await this.bootstrap()).signals.find((signal) => signal.id === id);
    if (!current || !impact || !urgency) throw new Error('Signal or required human triage is unavailable.');
    const updated = mapSignal(await this.request(`/signals/${id}/triage`, { method: 'POST', body: JSON.stringify({ expected_signal_row_version: current.rowVersion, business_impact: { confirmed_level: impact, reason: 'Confirmed by Owner PM in Glint.', expected_assessment_version: current.impactAssessmentVersion }, urgency: { confirmed_level: urgency, reason: 'Confirmed by Owner PM in Glint.', expected_assessment_version: current.urgencyAssessmentVersion } }) }));
    if (this.latestWorkspace) this.latestWorkspace = { ...this.latestWorkspace, signals: this.latestWorkspace.signals.map((item) => item.id === updated.id ? updated : item) };
    return updated;
  }

  async transitionSignal(signalId: string, action: 'monitor' | 'dismiss' | 'undo', details: { cooldownUntil?: string; dismissReason?: SignalDismissReason; note?: string } = {}): Promise<Signal> {
    const current = this.latestWorkspace?.signals.find((item) => item.id === signalId) ?? (await this.bootstrap()).signals.find((item) => item.id === signalId);
    if (!current) throw new Error('Signal is unavailable.');
    if (action === 'monitor' && !details.cooldownUntil) throw new Error('Keep monitoring requires an explicit cooldown time.');
    if (action === 'dismiss' && (!details.dismissReason || !details.note?.trim())) throw new Error('Dismiss requires a reason and note.');
    const updated = mapSignal(await this.request(`/signals/${signalId}/transitions`, { method: 'POST', body: JSON.stringify({ action, expected_row_version: current.rowVersion, session_id: signalSessionId(), ...(details.cooldownUntil ? { cooldown_until: details.cooldownUntil } : {}), ...(details.dismissReason ? { dismiss_reason: details.dismissReason } : {}), ...(details.note?.trim() ? { note: details.note.trim() } : {}) }) }));
    if (this.latestWorkspace) this.latestWorkspace = { ...this.latestWorkspace, signals: this.latestWorkspace.signals.map((item) => item.id === updated.id ? updated : item) };
    return updated;
  }

  canUndoSignal(signal: Signal): boolean { return Boolean(signal.disposition && signal.disposition.sessionId === signalSessionId() && signal.disposition.undoneAt === null && (signal.status === 'monitoring' || signal.status === 'dismissed')); }

  private researchPayload(signal: Signal, question: string, sourceConnectionIds: string[], contentVersionIds: string[] = [], allowCloudModel = false) {
    return { question, source_scope: { source_connection_ids: sourceConnectionIds, content_version_ids: contentVersionIds, allow_cloud_model: allowCloudModel }, time_range: { start: signal.window.currentStart, end: signal.window.currentEnd }, budget: { max_cost_usd: '4.0000', max_duration_seconds: 900 } };
  }

  async createInvestigation(signalId: string, question: string, allowCloudModel = false): Promise<Investigation> {
    if (!question.trim()) throw new Error('A decision question is required.');
    const workspace = this.latestWorkspace ?? await this.bootstrap();
    const signal = workspace.signals.find((item) => item.id === signalId);
    if (!signal) throw new Error('Signal is unavailable.');
    const eligible = eligibleResearchSources(signal, workspace.sources);
    if (eligible.length === 0) throw new Error('No Signal-linked source has eligible terminal imported content or successful cloud freshness.');
    const sourceConnectionIds = eligible.map((source) => source.id);
    const common = this.researchPayload(signal, question, sourceConnectionIds, [], allowCloudModel);
    const created = mapInvestigation(await this.request('/investigations', { method: 'POST', body: JSON.stringify({ signal_id: signalId, decision_question: question, source_scope: common.source_scope, time_range: common.time_range, budget: common.budget, stop_conditions: ['Evidence and counter-evidence have both been reviewed.'] }) }));
    const pinned = await this.loadInvestigation(created.id, created);
    if (!pinned.timeRange || pinned.sourceConnectionIds.length === 0) throw new Error('Pinned Investigation scope is unavailable.');
    const pinnedRun = {
      ...this.researchPayload(signal, pinned.question, pinned.sourceConnectionIds, pinned.contentVersionIds, pinned.allowCloudModel),
      time_range: pinned.timeRange,
    };
    await this.request('/research-runs', { method: 'POST', body: JSON.stringify({ investigation_id: pinned.id, investigation_scope_version_id: pinned.scopeVersionId, ...pinnedRun, expected_investigation_row_version: pinned.rowVersion }) });
    return this.loadInvestigation(pinned.id, pinned);
  }

  async cancelRun(investigationId: string): Promise<Investigation> {
    const investigation = await this.refreshInvestigation(investigationId);
    if (!investigation.run) throw new Error('ResearchRun is unavailable.');
    await this.request(`/research-runs/${investigation.run.id}/cancel`, { method: 'POST', body: JSON.stringify({ expected_row_version: investigation.run.rowVersion, reason: 'Cancelled by Owner PM in Glint.' }) });
    return this.refreshInvestigation(investigationId);
  }

  async startRun(investigationId: string): Promise<Investigation> {
    const workspace = this.latestWorkspace ?? await this.bootstrap();
    const investigation = await this.refreshInvestigation(investigationId);
    if (investigation.run || investigation.status !== 'draft') throw new Error('Only a draft Investigation without a ResearchRun can be started.');
    const signal = workspace.signals.find((item) => item.id === investigation.signalId);
    if (!signal || investigation.sourceConnectionIds.length === 0) throw new Error('Pinned Investigation scope is unavailable.');
    const common = this.researchPayload(signal, investigation.question, investigation.sourceConnectionIds, investigation.contentVersionIds, investigation.allowCloudModel);
    await this.request('/research-runs', { method: 'POST', body: JSON.stringify({ investigation_id: investigation.id, investigation_scope_version_id: investigation.scopeVersionId, ...common, expected_investigation_row_version: investigation.rowVersion }) });
    return this.refreshInvestigation(investigationId);
  }

  async retryRun(investigationId: string): Promise<Investigation> {
    const workspace = this.latestWorkspace ?? await this.bootstrap();
    const investigation = await this.refreshInvestigation(investigationId);
    const signal = workspace.signals.find((item) => item.id === investigation.signalId);
    if (!signal || investigation.sourceConnectionIds.length === 0) throw new Error('Pinned Investigation scope is unavailable.');
    const common = this.researchPayload(signal, investigation.question, investigation.sourceConnectionIds, investigation.contentVersionIds, investigation.allowCloudModel);
    await this.request('/research-runs', { method: 'POST', body: JSON.stringify({ investigation_id: investigation.id, investigation_scope_version_id: investigation.scopeVersionId, ...common, expected_investigation_row_version: investigation.rowVersion }) });
    return this.refreshInvestigation(investigationId);
  }

  async reviewEvidence(investigationId: string, evidenceId: string, decision: 'valid' | 'weak' | 'rejected'): Promise<Investigation> {
    asObject(await this.request(`/evidence/${evidenceId}/review`, { method: 'POST', body: JSON.stringify({ decision, reason: 'Reviewed by Owner PM in Glint.', policy_version: 'evidence-review-v1' }) }), 'EvidenceReview');
    return this.refreshInvestigation(investigationId);
  }

  private mapSourceViewer(value: unknown, expectedContentVersionId: string, expectedAuthenticity?: WorkspaceState['authenticity'], quote?: { start: number; end: number; text: string }): SourceViewer {
    const version = asObject(value, 'ContentVersion');
    const contentVersionId = asString(version.id, 'ContentVersion.id');
    if (contentVersionId !== expectedContentVersionId) throw new Error('Source Viewer returned a different ContentVersion.');
    const authenticity = mapAuthenticity(version.data_authenticity, 'ContentVersion.data_authenticity');
    if (expectedAuthenticity && authenticity !== expectedAuthenticity) throw new Error('Source Viewer authenticity differs across the Evidence lineage.');
    const availability = asString(version.availability, 'ContentVersion.availability');
    if (!['captured', 'deleted', 'unavailable'].includes(availability)) throw new Error('Invalid ContentVersion.availability DTO.');
    const body = typeof version.normalized_body === 'string' ? version.normalized_body : (() => { throw new Error('Invalid ContentVersion.normalized_body DTO.'); })();
    const characters = Array.from(body);
    const start = quote?.start ?? 0;
    const end = quote?.end ?? Math.min(characters.length, 240);
    if (start < 0 || end < start || end > characters.length) throw new Error('Evidence quote offsets escaped the immutable ContentVersion body.');
    const highlightedQuote = characters.slice(start, end).join('');
    if (quote && highlightedQuote !== quote.text) throw new Error('Evidence quote text differs from the immutable ContentVersion offsets.');
    const sourceKind = asString(version.source_kind, 'ContentVersion.source_kind');
    if (!['cloud', 'local', 'imported_dataset'].includes(sourceKind)) throw new Error('Invalid ContentVersion.source_kind DTO.');
    const metadata = asObject(version.metadata_json, 'ContentVersion.metadata_json');
    return {
      contentVersionId,
      title: asString(version.normalized_title, 'ContentVersion.normalized_title'),
      body,
      beforeQuote: characters.slice(0, start).join(''),
      highlightedQuote,
      afterQuote: characters.slice(end).join(''),
      publishedAt: version.published_at === null ? null : asString(version.published_at, 'ContentVersion.published_at'),
      capturedAt: asString(version.captured_at, 'ContentVersion.captured_at'),
      availability: availability as SourceViewer['availability'],
      source: { id: asString(version.source_connection_id, 'ContentVersion.source_connection_id'), name: asString(version.source_name, 'ContentVersion.source_name'), kind: sourceKind as SourceHealth['sourceKind'] },
      author: metadata.author === undefined ? null : asString(metadata.author, 'ContentVersion.metadata_json.author'),
      canonicalUrl: version.canonical_url === null ? null : asString(version.canonical_url, 'ContentVersion.canonical_url'),
      independenceGroupId: version.independence_group_id === null ? null : asString(version.independence_group_id, 'ContentVersion.independence_group_id'),
      authenticity,
    };
  }

  async sourceViewer(signalId: string, evidence: Investigation['evidence'][number]): Promise<SourceViewer> {
    void signalId;
    return this.mapSourceViewer(await this.request(`/content-versions/${evidence.contentVersionId}`), evidence.contentVersionId, evidence.authenticity, { start: evidence.quoteStart, end: evidence.quoteEnd, text: evidence.quote });
  }

  async signalSamples(signalId: string): Promise<SignalSample[]> {
    const evidenceItems = this.pageItems(await this.request(`/signals/${signalId}/evidence`), 'SignalEvidence page').map((item) => asObject(item, 'SignalEvidence')).filter((item) => item.role === 'trigger' || item.role === 'supporting' || item.role === 'counter').slice(0, 5);
    return Promise.all(evidenceItems.map(async (item) => {
      if (asString(item.signal_id, 'SignalEvidence.signal_id') !== signalId) throw new Error('Representative sample escaped the selected Signal.');
      const contentVersionId = asString(item.content_version_id, 'SignalEvidence.content_version_id');
      const authenticity = mapAuthenticity(item.data_authenticity, 'SignalEvidence.data_authenticity');
      const viewer = this.mapSourceViewer(await this.request(`/content-versions/${contentVersionId}`), contentVersionId, authenticity);
      const groupId = item.independence_group_id === null ? null : asString(item.independence_group_id, 'SignalEvidence.independence_group_id');
      if (groupId !== viewer.independenceGroupId) throw new Error('Representative sample independence group differs from its exact ContentVersion.');
      return { contentVersionId, role: item.role === 'trigger' ? 'trigger' : 'context', contribution: asNumber(item.contribution, 'SignalEvidence.contribution'), viewer };
    }));
  }

  async reviewClaim(investigationId: string, claimId: string, decision: 'verify' | 'reject'): Promise<Investigation> {
    const investigation = await this.refreshInvestigation(investigationId);
    const claim = investigation.claims.find((item) => item.id === claimId);
    if (!claim) throw new Error('Exact ClaimVersion is unavailable.');
    const evidenceReviewIds = claim.evidenceLinks.map((link) => investigation.evidence.find((item) => item.id === link.evidenceId)?.latestReviewId ?? null).filter((value): value is string => value !== null).sort();
    const snapshot = { claim_version_id: claim.versionId, claim_evidence_ids: claim.evidenceLinks.map((link) => link.id).sort(), evidence_review_ids: evidenceReviewIds };
    if (decision === 'verify' && evidenceReviewIds.length !== claim.evidenceLinks.length) throw new Error('Verify requires one exact EvidenceReview per linked Evidence.');
    await this.request(`/claims/${claim.id}/versions/${claim.versionId}/review`, { method: 'POST', body: JSON.stringify({ claim_version_id: claim.versionId, expected_claim_row_version: claim.rowVersion, decision, evidence_review_ids: evidenceReviewIds, expected_claim_evidence_snapshot_digest: decision === 'verify' ? await sha256(canonicalJson(snapshot)) : null, reason: 'Reviewed by Owner PM in Glint.' }) });
    return this.refreshInvestigation(investigationId);
  }

  async createSynthesis(investigationId: string): Promise<Investigation> {
    const investigation = await this.refreshInvestigation(investigationId);
    if (investigation.synthesis) throw new Error('A synthesis already exists; revise the current version instead.');
    const verifiedClaimVersionIds = investigation.claims.filter((claim) => claim.status === 'verified').map((claim) => claim.versionId);
    if (verifiedClaimVersionIds.length === 0) throw new Error('Verify at least one ClaimVersion before creating synthesis.');
    await this.request(`/investigations/${investigationId}/synthesis`, { method: 'POST', body: JSON.stringify({ verified_claim_version_ids: verifiedClaimVersionIds }) });
    return this.refreshInvestigation(investigationId);
  }

  async reviseSynthesis(investigationId: string, executiveSummary: string): Promise<Investigation> {
    const investigation = await this.refreshInvestigation(investigationId);
    const synthesis = investigation.synthesis;
    if (!synthesis) throw new Error('Exact Synthesis version is unavailable.');
    if (incompleteCopy(executiveSummary)) throw new Error('Synthesis revision must contain complete reviewable content.');
    await this.request(`/investigations/${investigationId}/synthesis`, { method: 'PATCH', body: JSON.stringify({ executive_summary: executiveSummary.trim(), business_implications: synthesis.businessImplications, limitations: synthesis.limitations, expected_row_version: synthesis.rowVersion, change_reason: 'Revised by Owner PM in Glint.' }) });
    return this.refreshInvestigation(investigationId);
  }

  async reviewSynthesis(investigationId: string, decision: 'verify' | 'reject'): Promise<Investigation> {
    const investigation = await this.refreshInvestigation(investigationId);
    const synthesis = investigation.synthesis;
    if (!synthesis) throw new Error('Create and inspect a synthesis before reviewing it.');
    if (synthesis.status === 'verified' || synthesis.status === 'rejected') throw new Error(`The current synthesis version is already ${synthesis.status}.`);
    await this.request(`/investigations/${investigationId}/synthesis/versions/${synthesis.versionId}/review`, { method: 'POST', body: JSON.stringify({ synthesis_version_id: synthesis.versionId, expected_row_version: synthesis.rowVersion, decision, reason: `${decision === 'verify' ? 'Verified' : 'Rejected'} by Owner PM in Glint.`, policy_version: 'synthesis-review-v1' }) });
    return this.refreshInvestigation(investigationId);
  }

  async createBrief(investigationId: string): Promise<DecisionBrief> {
    const investigation = await this.refreshInvestigation(investigationId);
    if (!investigation.synthesis || investigation.synthesis.status !== 'verified') throw new Error('A verified synthesis is required.');
    return mapBrief(await this.request(`/investigations/${investigationId}/decision-brief`, { method: 'POST', body: JSON.stringify({ synthesis_version_id: investigation.synthesis.versionId, template_version: 'decision-brief-v1' }) }), investigation.question);
  }

  private async getBrief(id: string): Promise<DecisionBrief> {
    const raw = await this.request(`/decision-briefs/${id}`);
    const dto = asObject(raw, 'DecisionBrief');
    const investigationId = asString(dto.investigation_id, 'DecisionBrief.investigation_id');
    const question = this.latestWorkspace?.investigations.find((item) => item.id === investigationId)?.question ?? 'Decision brief';
    return mapBrief(raw, question);
  }

  async updateBrief(id: string, judgment: string, recommendationId: string, recommendationBody: string, status: 'accepted' | 'rejected'): Promise<DecisionBrief> {
    const current = await this.getBrief(id);
    if (!judgment.trim()) throw new Error('PM Judgment block cannot be empty.');
    if (status === 'accepted' && (incompleteCopy(judgment) || incompleteCopy(recommendationBody))) throw new Error('Accepted Recommendation and PM Judgment cannot contain pending placeholder wording.');
    const blocks: BriefBlock[] = current.blockDocument.blocks.map((block) => block.type === 'pm_judgment' ? { ...block, body: judgment.trim() } : block.type === 'recommendation' && block.id === recommendationId ? { ...block, body: recommendationBody.trim(), recommendationStatus: status } : block);
    if (!blocks.some((block) => block.type === 'recommendation' && block.id === recommendationId)) throw new Error('Recommendation block is unavailable.');
    const updated: DecisionBrief = { ...current, blockDocument: { ...current.blockDocument, blocks } };
    const blockDocument = toWireDocument(updated);
    return mapBrief(await this.request(`/decision-briefs/${id}`, { method: 'PATCH', body: JSON.stringify({ block_document: blockDocument, expected_row_version: current.rowVersion, human_edit_digest: await sha256(canonicalJson(blockDocument)) }) }), current.question);
  }

  async saveNoCounterEvidenceSearch(id: string, input: NoCounterEvidenceSearchInput): Promise<DecisionBrief> {
    const normalizeRequired = (values: string[], label: string): string[] => {
      if (!Array.isArray(values) || values.length === 0 || values.some((value) => typeof value !== 'string' || !value.trim())) throw new Error(`${label} requires at least one non-empty entry.`);
      return values.map((value) => value.trim());
    };
    const queries = normalizeRequired(input.queries, 'Counter-evidence queries');
    const exclusionCriteria = normalizeRequired(input.exclusionCriteria, 'Counter-evidence exclusion criteria');
    const limitations = normalizeRequired(input.limitations, 'Counter-evidence limitations');
    const current = await this.getBrief(id);
    const investigation = await this.refreshInvestigation(current.investigationId);
    if (investigation.sourceConnectionIds.length === 0 || investigation.sourceConnectionIds.some((sourceId) => !sourceId.trim())) throw new Error('The current Investigation source scope is unavailable.');
    if (!investigation.timeRange?.start.trim() || !investigation.timeRange.end.trim()) throw new Error('The current Investigation time range is unavailable.');
    const updated: DecisionBrief = {
      ...current,
      blockDocument: {
        ...current.blockDocument,
        noCounterEvidenceSearch: {
          queries,
          sourceConnectionIds: [...investigation.sourceConnectionIds],
          windowStart: investigation.timeRange.start,
          windowEnd: investigation.timeRange.end,
          exclusionCriteria,
          limitations,
        },
      },
    };
    const blockDocument = toWireDocument(updated);
    return mapBrief(await this.request(`/decision-briefs/${id}`, { method: 'PATCH', body: JSON.stringify({ block_document: blockDocument, expected_row_version: current.rowVersion, human_edit_digest: await sha256(canonicalJson(blockDocument)) }) }), current.question);
  }

  async markReady(id: string): Promise<DecisionBrief> {
    const current = await this.getBrief(id);
    const judgment = current.blockDocument.blocks.find((block) => block.type === 'pm_judgment');
    const accepted = current.blockDocument.blocks.filter((block) => block.type === 'recommendation' && block.recommendationStatus === 'accepted');
    if (!judgment || incompleteCopy(judgment.body)) throw new Error('Readiness requires a complete PM Judgment.');
    if (accepted.length === 0 || accepted.some((block) => incompleteCopy(block.body))) throw new Error('Readiness requires at least one complete accepted Recommendation.');
    const policyVersion = 'decision-readiness-v1';
    const checklistDigest = await sha256(canonicalJson({ decision_brief_version_id: current.versionId, block_document: toWireDocument(current), reference_snapshot: toWireReference(current), policy_version: policyVersion }));
    const review = asObject(await this.request(`/decision-briefs/${id}/mark-decision-ready`, { method: 'POST', body: JSON.stringify({ decision_brief_version_id: current.versionId, expected_row_version: current.rowVersion, decision: 'mark_decision_ready', reason: 'Owner PM completed the readiness checklist.', policy_version: policyVersion, checklist_digest: checklistDigest }) }), 'DecisionBriefReadinessReview');
    if (asString(review.checklist_digest, 'DecisionBriefReadinessReview.checklist_digest') !== checklistDigest) throw new Error('Readiness review returned a mismatched checklist_digest.');
    return this.getBrief(id);
  }

  private parseImportSession(value: unknown) {
    const dto = asObject(value, 'ImportSession');
    const state = asString(dto.state, 'ImportSession.state');
    if (!['draft', 'consented', 'uploaded', 'validating', 'finalized', 'failed', 'cancelled'].includes(state)) throw new Error('Invalid ImportSession.state DTO.');
    if (typeof dto.retryable !== 'boolean') throw new Error('Invalid ImportSession.retryable DTO.');
    const terminalManifestId = dto.terminal_manifest_id === null ? null : asString(dto.terminal_manifest_id, 'ImportSession.terminal_manifest_id');
    const failureCode = dto.failure_code === null ? null : asString(dto.failure_code, 'ImportSession.failure_code');
    mapAuthenticity(dto.data_authenticity, 'ImportSession.data_authenticity');
    if (state === 'finalized' && (!terminalManifestId || failureCode)) throw new Error('Finalized ImportSession requires only a terminal manifest.');
    if (state === 'failed' && (!failureCode || terminalManifestId)) throw new Error('Failed ImportSession requires only a failure code.');
    if (!['finalized', 'failed'].includes(state) && (terminalManifestId || failureCode)) throw new Error('Non-terminal ImportSession cannot expose a terminal outcome.');
    return { id: asString(dto.id, 'ImportSession.id'), state, rowVersion: asNumber(dto.row_version, 'ImportSession.row_version'), retryable: dto.retryable, terminalManifestId, failureCode };
  }

  private parseFinalizationJob(value: unknown) {
    const dto = asObject(value, 'ImportFinalizationJob');
    const id = asString(dto.id, 'ImportFinalizationJob.id');
    const commandId = asString(dto.command_id, 'ImportFinalizationJob.command_id');
    if (id !== commandId) throw new Error('ImportFinalizationJob id differs from command_id.');
    const state = asString(dto.state, 'ImportFinalizationJob.state');
    if (!['queued', 'claimed', 'completed', 'failed'].includes(state)) throw new Error('Invalid ImportFinalizationJob.state DTO.');
    const resultManifestId = dto.result_manifest_id === null ? null : asString(dto.result_manifest_id, 'ImportFinalizationJob.result_manifest_id');
    const failureCode = dto.failure_code === null ? null : asString(dto.failure_code, 'ImportFinalizationJob.failure_code');
    if (state === 'completed' && (!resultManifestId || failureCode)) throw new Error('Completed ImportFinalizationJob requires only a result manifest.');
    if (state === 'failed' && (!failureCode || resultManifestId)) throw new Error('Failed ImportFinalizationJob requires only a failure code.');
    if (!['completed', 'failed'].includes(state) && (resultManifestId || failureCode)) throw new Error('Non-terminal ImportFinalizationJob cannot expose an outcome.');
    mapAuthenticity(dto.data_authenticity, 'ImportFinalizationJob.data_authenticity');
    return { raw: dto, commandId, importId: asString(dto.import_session_id, 'ImportFinalizationJob.import_session_id'), state, attempt: asNumber(dto.attempt, 'ImportFinalizationJob.attempt'), resultManifestId, failureCode };
  }

  private async pollFinalization(importId: string, jobId: string, firstJob: JsonObject | null, onProgress: (progress: ImportProgress) => void): Promise<ImportResult> {
    for (let poll = 0; poll < 40; poll += 1) {
      const job = this.parseFinalizationJob(poll === 0 && firstJob ? firstJob : await this.request(`/import-finalization-jobs/${jobId}`));
      if (job.commandId !== jobId || job.importId !== importId) throw new Error('ImportFinalizationJob escaped the recovered ImportSession.');
      const { state, attempt } = job;
      onProgress({ stage: 'finalizing', message: `Finalization job ${state} · attempt ${attempt}`, sessionId: importId, jobId, attempt });
      if (state === 'completed') {
        const manifestId = job.resultManifestId!;
        const session = this.parseImportSession(await this.request(`/imports/${importId}`));
        if (session.state !== 'finalized' || session.terminalManifestId !== manifestId) throw new Error('Completed finalization did not produce the exact terminal ImportManifest.');
        this.forgetImport();
        onProgress({ stage: 'completed', message: `Finalized ImportManifest · ${manifestId}`, sessionId: importId, jobId, attempt });
        return { sessionId: importId, manifestId, jobId };
      }
      if (state === 'failed') {
        const session = this.parseImportSession(await this.request(`/imports/${importId}`));
        onProgress({ stage: 'retryable_failure', message: session.failureCode ? `Finalization failed · ${session.failureCode}` : 'Finalization failed.', sessionId: importId, jobId, attempt, retryable: session.retryable });
        throw new Error(session.retryable ? 'Import finalization failed and can be retried.' : 'Import finalization failed and must be recreated.');
      }
      await sleep(250);
    }
    throw new Error('Import finalization is still running; polling can be resumed from the job ID.');
  }

  private async finalize(importId: string, rowVersion: number, onProgress: (progress: ImportProgress) => void): Promise<ImportResult> {
    const job = this.parseFinalizationJob(await this.request(`/imports/${importId}/finalize`, { method: 'POST', body: JSON.stringify({ expected_row_version: rowVersion }) }));
    if (job.importId !== importId) throw new Error('Finalize returned a job for a different ImportSession.');
    const jobId = job.commandId;
    this.rememberImport(importId, jobId);
    return this.pollFinalization(importId, jobId, job.raw, onProgress);
  }

  async createImportSession(prepared: PreparedCsvImport, source: SourceHealth, onProgress: (progress: ImportProgress) => void): Promise<PendingImport> {
    if (source.sourceKind !== 'imported_dataset') throw new Error('CSV can only target an Imported Dataset source.');
    onProgress({ stage: 'creating_session', message: 'Creating metadata-only ImportSession' });
    const created = this.parseImportSession(await this.request('/imports', { method: 'POST', body: JSON.stringify({ source_connection_id: source.id, expected_source_row_version: source.rowVersion, expected_current_import_manifest_id: source.currentImportManifestId, local_manifest_digest: prepared.localManifestDigest, file_digest: prepared.fileDigest, expected_upload_digest: prepared.expectedUploadDigest, client_file_name: prepared.fileName, file_size_bytes: prepared.fileSizeBytes, media_type: 'text/csv', parser_version: prepared.parserVersion, schema_version: prepared.schemaVersion, selected_scope_json: prepared.selectedScope, selected_scope_digest: prepared.selectedScopeDigest }) }));
    this.rememberImport(created.id);
    onProgress({ stage: 'session_created', message: 'Metadata-only ImportSession created; no file bytes transferred.', sessionId: created.id });
    return { sessionId: created.id, rowVersion: created.rowVersion, prepared, source };
  }

  async previewImportConsent(pending: PendingImport, onProgress: (progress: ImportProgress) => void): Promise<ConsentPreview> {
    onProgress({ stage: 'previewing_consent', message: 'Loading the no-side-effect upload consent scope', sessionId: pending.sessionId });
    const response = asObject(await this.request(`/imports/${pending.sessionId}/upload-consent/preview?expected_row_version=${pending.rowVersion}`), 'UploadConsentPreview');
    if (mapAuthenticity(response.data_authenticity, 'UploadConsentPreview.data_authenticity') !== 'imported') throw new Error('Upload consent preview authenticity must remain imported.');
    const previewScope = asObject(response.preview_scope, 'UploadConsentScopeBinding');
    const objectScope = asObject(previewScope.upload_object_scope, 'UploadConsentScopeBinding.upload_object_scope');
    const destinationWorkspaceId = asString(previewScope.destination_workspace_id, 'UploadConsentScopeBinding.destination_workspace_id');
    const objectKey = asString(objectScope.object_key, 'UploadObjectScope.object_key');
    const maximumBytes = asNumber(objectScope.max_bytes, 'UploadObjectScope.max_bytes');
    const mediaType = asString(objectScope.media_type, 'UploadObjectScope.media_type');
    const selectedScopeDigest = asString(previewScope.selected_scope_digest, 'UploadConsentScopeBinding.selected_scope_digest');
    const scopeDigest = asString(response.scope_digest, 'UploadConsentPreview.scope_digest');
    const policyVersion = asString(previewScope.policy_version, 'UploadConsentScopeBinding.policy_version');
    const currentManifestId = previewScope.current_import_manifest_id === null ? null : asString(previewScope.current_import_manifest_id, 'UploadConsentScopeBinding.current_import_manifest_id');
    if (destinationWorkspaceId !== this.workspaceId || asString(previewScope.import_session_id, 'UploadConsentScopeBinding.import_session_id') !== pending.sessionId || asNumber(previewScope.import_session_row_version, 'UploadConsentScopeBinding.import_session_row_version') !== pending.rowVersion) throw new Error('Upload consent preview escaped the current ImportSession scope.');
    if (asString(previewScope.source_connection_id, 'UploadConsentScopeBinding.source_connection_id') !== pending.source.id || asNumber(previewScope.source_row_version, 'UploadConsentScopeBinding.source_row_version') !== pending.source.rowVersion || currentManifestId !== pending.source.currentImportManifestId) throw new Error('Upload consent preview differs from the selected Imported Dataset source version.');
    if (asString(previewScope.local_manifest_digest, 'UploadConsentScopeBinding.local_manifest_digest') !== pending.prepared.localManifestDigest || asString(previewScope.file_digest, 'UploadConsentScopeBinding.file_digest') !== pending.prepared.fileDigest || asString(previewScope.expected_upload_digest, 'UploadConsentScopeBinding.expected_upload_digest') !== pending.prepared.expectedUploadDigest || selectedScopeDigest !== pending.prepared.selectedScopeDigest) throw new Error('Upload consent preview differs from the local metadata manifest.');
    if (maximumBytes !== pending.prepared.fileSizeBytes || mediaType !== 'text/csv') throw new Error('Upload consent preview allocated an unexpected file scope.');
    const expiresAt = new Date(Date.now() + 10 * 60 * 1000).toISOString();
    const preview = { ...pending, destinationWorkspaceId, objectKey, maximumBytes, mediaType, expiresAt, selectedScopeDigest, scopeDigest, policyVersion, previewScope };
    onProgress({ stage: 'consent_previewed', message: 'No-side-effect consent scope ready for explicit review.', sessionId: pending.sessionId, destinationWorkspaceId, objectKey, maximumBytes, expiresAt });
    return preview;
  }

  async grantImportUpload(preview: ConsentPreview, onProgress: (progress: ImportProgress) => void): Promise<GrantedImport> {
    onProgress({ stage: 'awaiting_consent', message: 'Appending the explicitly confirmed upload consent', sessionId: preview.sessionId, destinationWorkspaceId: preview.destinationWorkspaceId, objectKey: preview.objectKey, maximumBytes: preview.maximumBytes, expiresAt: preview.expiresAt });
    const consentResponse = await this.raw(`/imports/${preview.sessionId}/upload-consent`, { method: 'POST', body: JSON.stringify({ preview_scope: preview.previewScope, scope_digest: preview.scopeDigest, confirmation: true, expires_at: preview.expiresAt }) });
    if (!consentResponse) throw new Error('Upload consent response is missing.');
    const uploadGrant = consentResponse.headers.get('X-Upload-Grant');
    if (!uploadGrant) throw new Error('Upload consent did not expose X-Upload-Grant.');
    const consent = asObject(await consentResponse.json(), 'UploadConsent');
    const consentSession = this.parseImportSession(consent.import_session);
    const consentRecord = asObject(consent.consent_record, 'TransferConsentRecord');
    const upload = asObject(consent.upload, 'UploadGrantMetadata');
    const consentAuthenticity = mapAuthenticity(consent.data_authenticity, 'UploadConsent.data_authenticity');
    const recordAuthenticity = mapAuthenticity(consentRecord.data_authenticity, 'TransferConsentRecord.data_authenticity');
    if (consentAuthenticity !== 'imported' || recordAuthenticity !== 'imported') throw new Error('Upload consent authenticity must remain imported.');
    if (asString(consentRecord.decision, 'TransferConsentRecord.decision') !== 'grant' || asString(consentRecord.model_egress_authorization, 'TransferConsentRecord.model_egress_authorization') !== 'none') throw new Error('Upload consent did not grant the local-only transfer policy.');
    const destinationWorkspaceId = asString(consentRecord.destination_workspace_id, 'TransferConsentRecord.destination_workspace_id');
    if (destinationWorkspaceId !== preview.destinationWorkspaceId || asString(consentRecord.selected_scope_digest, 'TransferConsentRecord.selected_scope_digest') !== preview.selectedScopeDigest || asString(consentRecord.policy_version, 'TransferConsentRecord.policy_version') !== preview.policyVersion) throw new Error('Upload consent record differs from the confirmed preview scope.');
    const objectKey = asString(upload.object_key, 'UploadGrantMetadata.object_key');
    const maximumBytes = asNumber(upload.maximum_bytes, 'UploadGrantMetadata.maximum_bytes');
    const mediaType = asString(upload.media_type, 'UploadGrantMetadata.media_type');
    const grantExpiresAt = asString(upload.expires_at, 'UploadGrantMetadata.expires_at');
    const objectScope = asObject(consentRecord.upload_object_scope, 'TransferConsentRecord.upload_object_scope');
    if (consentSession.id !== preview.sessionId || consentSession.state !== 'consented' || asString(objectScope.object_key, 'UploadObjectScope.object_key') !== preview.objectKey || asNumber(objectScope.max_bytes, 'UploadObjectScope.max_bytes') !== preview.maximumBytes || asString(objectScope.media_type, 'UploadObjectScope.media_type') !== preview.mediaType || objectKey !== preview.objectKey || maximumBytes !== preview.maximumBytes || mediaType !== preview.mediaType || new Date(grantExpiresAt).getTime() !== new Date(preview.expiresAt).getTime()) throw new Error('Upload grant metadata drifted from the explicitly confirmed preview.');
    const granted = { ...preview, rowVersion: consentSession.rowVersion, expiresAt: grantExpiresAt, uploadGrant };
    onProgress({ stage: 'grant_ready', message: 'Append-only consent recorded; confirm separately before transferring file bytes.', sessionId: preview.sessionId, destinationWorkspaceId, objectKey, maximumBytes, expiresAt: grantExpiresAt });
    return granted;
  }

  async uploadGrantedImport(granted: GrantedImport, onProgress: (progress: ImportProgress) => void): Promise<ImportResult> {
    onProgress({ stage: 'uploading', message: 'Uploading to the confirmed workspace object scope', sessionId: granted.sessionId, destinationWorkspaceId: granted.destinationWorkspaceId, objectKey: granted.objectKey, maximumBytes: granted.maximumBytes, expiresAt: granted.expiresAt });
    const uploadResponse = await fetch(`${this.baseUrl}/v1/imports/${granted.sessionId}/object`, { method: 'PUT', headers: this.headers(false, { 'Content-Type': 'text/csv', 'X-Upload-Grant': granted.uploadGrant }), body: granted.prepared.file });
    if (uploadResponse.status === 401) {
      this.onUnauthorized?.();
      throw new SessionExpiredError();
    }
    if (!uploadResponse.ok) throw new Error(`Upload failed (${uploadResponse.status}).`);
    const uploaded = asObject(await uploadResponse.json(), 'UploadedObject');
    if (asString(uploaded.object_key, 'UploadedObject.object_key') !== granted.objectKey) throw new Error('Uploaded object_key differs from the consented object scope.');
    if (mapAuthenticity(uploaded.data_authenticity, 'UploadedObject.data_authenticity') !== 'imported') throw new Error('Uploaded object authenticity must remain imported.');
    onProgress({ stage: 'verifying_upload', message: 'Verifying uploaded digest and object scope', sessionId: granted.sessionId, destinationWorkspaceId: granted.destinationWorkspaceId, objectKey: granted.objectKey, maximumBytes: granted.maximumBytes, expiresAt: granted.expiresAt });
    const completed = this.parseImportSession(await this.request(`/imports/${granted.sessionId}/upload-complete`, { method: 'POST', body: JSON.stringify({ expected_row_version: granted.rowVersion, object_key: granted.objectKey }) }));
    return this.finalize(granted.sessionId, completed.rowVersion, onProgress);
  }

  async importCsv(prepared: PreparedCsvImport, source: SourceHealth, onProgress: (progress: ImportProgress) => void): Promise<ImportResult> {
    const pending = await this.createImportSession(prepared, source, onProgress);
    const preview = await this.previewImportConsent(pending, onProgress);
    const granted = await this.grantImportUpload(preview, onProgress);
    return this.uploadGrantedImport(granted, onProgress);
  }

  async recoverImport(onProgress: (progress: ImportProgress) => void): Promise<ImportResult | null> {
    let rememberedImportId: string | null = null;
    let rememberedJobId: string | null = null;
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(this.activeImportKey());
      if (raw) {
        const stored = asObject(JSON.parse(raw), 'Stored active import');
        rememberedImportId = asString(stored.importId, 'Stored active import.importId');
        rememberedJobId = stored.jobId === undefined ? null : asString(stored.jobId, 'Stored active import.jobId');
      }
    }
    const recoveryItems = this.pageItems(await this.request('/imports'), 'ImportRecovery page').map((value) => {
      const item = asObject(value, 'ImportRecoveryItem');
      if (mapAuthenticity(item.data_authenticity, 'ImportRecoveryItem.data_authenticity') !== 'imported') throw new Error('ImportRecoveryItem authenticity must remain imported.');
      const session = this.parseImportSession(item.import_session);
      const job = item.finalization_job === null ? null : this.parseFinalizationJob(item.finalization_job);
      if (job && job.importId !== session.id) throw new Error('ImportRecoveryItem finalization job escaped its ImportSession.');
      return { session, job };
    });
    const recovered = (rememberedImportId ? recoveryItems.find((item) => item.session.id === rememberedImportId) : undefined)
      ?? recoveryItems.find((item) => !['finalized', 'cancelled'].includes(item.session.state) && (item.session.state !== 'failed' || item.session.retryable));
    if (!recovered) {
      if (rememberedImportId) this.forgetImport();
      return null;
    }
    const { session, job } = recovered;
    const importId = session.id;
    const jobId = job?.commandId ?? rememberedJobId;
    this.rememberImport(importId, jobId ?? undefined);
    if (session.state === 'finalized' && session.terminalManifestId && jobId) { this.forgetImport(); return { sessionId: importId, manifestId: session.terminalManifestId, jobId }; }
    if (session.state === 'cancelled') { this.forgetImport(); onProgress({ stage: 'cancelled', message: 'Recovered ImportSession is cancelled.', sessionId: importId }); return null; }
    if (session.state === 'validating' && jobId) return this.pollFinalization(importId, jobId, job?.raw ?? null, onProgress);
    if (session.state === 'validating') throw new Error('Validating ImportSession omitted its recoverable finalization job.');
    if (session.state === 'uploaded') return this.finalize(importId, session.rowVersion, onProgress);
    if (session.state === 'failed' && session.retryable) { onProgress({ stage: 'retryable_failure', message: session.failureCode ? `Recovered retryable import · ${session.failureCode}` : 'Recovered retryable import.', sessionId: importId, retryable: true, ...(jobId ? { jobId } : {}) }); return null; }
    onProgress({ stage: session.state === 'consented' ? 'grant_ready' : 'session_created', message: session.state === 'consented' ? 'Recovered consented ImportSession; upload grant is not persisted. Cancel and recreate to continue safely.' : 'Recovered metadata ImportSession; cancel it or select the file again to continue.', sessionId: importId });
    return null;
  }

  async cancelImport(importId: string, onProgress: (progress: ImportProgress) => void): Promise<void> {
    const session = this.parseImportSession(await this.request(`/imports/${importId}`));
    if (['finalized', 'failed', 'cancelled'].includes(session.state)) throw new Error(`A terminal ${session.state} import cannot be cancelled.`);
    const cancelled = this.parseImportSession(await this.request(`/imports/${importId}/cancel`, { method: 'POST', body: JSON.stringify({ expected_row_version: session.rowVersion, reason: 'Cancelled by Owner PM in Glint.' }) }));
    if (cancelled.state !== 'cancelled') throw new Error('Import cancellation did not reach a terminal cancelled state.');
    this.forgetImport();
    onProgress({ stage: 'cancelled', message: 'Import cancelled; upload grant revoked.', sessionId: importId });
  }

  async retryImport(importId: string, onProgress: (progress: ImportProgress) => void): Promise<ImportResult> {
    const session = this.parseImportSession(await this.request(`/imports/${importId}`));
    if (session.state !== 'failed' || !session.retryable) throw new Error('Only a retryable failed ImportSession can be finalized again.');
    return this.finalize(importId, session.rowVersion, onProgress);
  }

  async subscribeRun(runId: string, lastEventId: string | undefined, signal: AbortSignal, onEvent: (event: RunStreamEvent) => void, onReset: (reset: StreamReset) => Promise<void>): Promise<void> {
    try {
      await subscribeRunEvents({ baseUrl: this.baseUrl, workspaceId: this.workspaceId, accessToken: this.accessToken, runId, lastEventId, signal, onEvent, onReset });
    } catch (reason) {
      if (reason instanceof SessionExpiredError) this.onUnauthorized?.();
      throw reason;
    }
  }

  async previewExport(briefId: string): Promise<ExportPreview> {
    const brief = await this.getBrief(briefId);
    const judgment = brief.blockDocument.blocks.find((block) => block.type === 'pm_judgment');
    const accepted = brief.blockDocument.blocks.filter((block) => block.type === 'recommendation' && block.recommendationStatus === 'accepted');
    if (brief.readiness !== 'decision_ready' || !judgment || incompleteCopy(judgment.body) || accepted.length === 0 || accepted.some((block) => incompleteCopy(block.body))) throw new Error('Export requires a readiness-reviewed Brief with complete accepted content.');
    const blockIds = brief.blockDocument.blocks.filter((block) => block.type === 'fact' || block.type === 'pm_judgment' || (block.type === 'recommendation' && block.recommendationStatus === 'accepted')).map((block) => block.id);
    const selectionManifest = { block_ids: blockIds, include_citations: true };
    const response = asObject(await this.request(`/decision-briefs/${briefId}/exports/preview`, { method: 'POST', body: JSON.stringify({ decision_brief_version_id: brief.versionId, export_type: 'prd_research_input_markdown', selection_manifest: selectionManifest }) }), 'BriefExportPreview');
    const exportType = asString(response.export_type, 'BriefExportPreview.export_type');
    if (exportType !== 'prd_research_input_markdown') throw new Error('Unexpected BriefExportPreview export_type.');
    const renderedContent = typeof response.rendered_content === 'string' ? response.rendered_content : (() => { throw new Error('Invalid BriefExportPreview.rendered_content DTO.'); })();
    const authenticity = mapAuthenticity(response.data_authenticity, 'BriefExportPreview.data_authenticity');
    const exportTimestamp = asString(response.export_timestamp, 'BriefExportPreview.export_timestamp');
    const marker = { seed: 'Seed', imported: 'Imported', collected: 'Collected', generated: 'Generated', human_authored: 'Human Authored' }[authenticity];
    if (!renderedContent.includes(`Data authenticity: ${marker}`)) throw new Error('Canonical export Markdown omitted its data authenticity marker.');
    if (!renderedContent.includes(`Export Timestamp: ${exportTimestamp}`)) throw new Error('Canonical export Markdown omitted its server-issued timestamp.');
    return { renderedContent, referenceDigest: asString(response.reference_digest, 'BriefExportPreview.reference_digest'), exportTimestamp, exportType, selectionManifest, authenticity };
  }

  async executeExport(briefId: string, preview: ExportPreview, destination: BriefExport['destination'], idempotencyKey: string): Promise<BriefExport> {
    const brief = await this.getBrief(briefId);
    const response = asObject(await this.request(`/decision-briefs/${briefId}/exports`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ decision_brief_version_id: brief.versionId, export_type: preview.exportType, selection_manifest: preview.selectionManifest, destination, reference_digest: preview.referenceDigest, export_timestamp: preview.exportTimestamp }) }), 'BriefExport');
    const responseDestination = asString(response.destination, 'BriefExport.destination');
    const responseType = asString(response.export_type, 'BriefExport.export_type');
    if (responseDestination !== destination || responseType !== preview.exportType || asString(response.decision_brief_version_id, 'BriefExport.decision_brief_version_id') !== brief.versionId) throw new Error('BriefExport is not terminal for the exact previewed version and destination.');
    const authenticity = mapAuthenticity(response.data_authenticity, 'BriefExport.data_authenticity');
    if (authenticity !== preview.authenticity) throw new Error('Terminal BriefExport authenticity differs from the canonical preview.');
    const outputDigest = asString(response.output_digest, 'BriefExport.output_digest');
    if (outputDigest !== await sha256(preview.renderedContent)) throw new Error('Terminal BriefExport output_digest differs from the canonical local Markdown bytes.');
    const createdAt = asString(response.created_at, 'BriefExport.created_at');
    if (createdAt !== preview.exportTimestamp) throw new Error('Terminal BriefExport timestamp differs from the canonical preview.');
    return { id: asString(response.id, 'BriefExport.id'), decisionBriefVersionId: brief.versionId, exportType: preview.exportType, destination, outputDigest, createdAt, authenticity };
  }
}

export function projectRunEvent(investigation: Investigation, event: RunStreamEvent): Investigation {
  const state = event.payload.state;
  const runState = typeof state === 'string' && ['queued', 'running', 'waiting_for_input', 'completed', 'failed', 'cancelled'].includes(state) ? state as RunState : investigation.run?.state;
  const message = typeof event.payload.safe_summary === 'string' ? event.payload.safe_summary : event.eventType.replaceAll('.', ' ');
  const events = investigation.events.some((item) => item.id === event.eventId) ? investigation.events : [...investigation.events, { id: event.eventId, sequence: event.sequence, type: event.eventType, message, timestamp: event.timestamp, authenticity: event.authenticity }].sort((left, right) => left.sequence - right.sequence);
  return { ...investigation, run: investigation.run ? { ...investigation.run, state: runState ?? investigation.run.state, latestSequence: Math.max(investigation.run.latestSequence, event.sequence) } : investigation.run, events };
}

export async function createApi(onUnauthorized?: () => void): Promise<{ api: GlintApi; mode: 'api' }> {
  const { apiUrl, workspaceId } = resolveConnectionProfile();
  const accessToken = await resolveAccessToken();
  const api = new RestAdapter(apiUrl, workspaceId, accessToken, onUnauthorized);
  await api.quantRequest('/quant/workspace-snapshot');
  return { api, mode: 'api' };
}
