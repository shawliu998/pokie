import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';

const PORT = Number(process.env.GLINT_FIXTURE_PORT ?? 4174);
const ACCESS_TOKEN = process.env.GLINT_FIXTURE_ACCESS_TOKEN_STDIN === '1'
  ? readFileSync(0, 'utf8')
  : (process.env.GLINT_FIXTURE_ACCESS_TOKEN ?? 'fixture-access-token');
const ALLOWED_ORIGIN = process.env.GLINT_FIXTURE_ALLOWED_ORIGIN ?? 'http://127.0.0.1:5173';
if (!/^http:\/\/127\.0\.0\.1:[1-9]\d{0,4}$/.test(ALLOWED_ORIGIN)) {
  throw new Error('GLINT_FIXTURE_ALLOWED_ORIGIN must be an exact loopback HTTP origin.');
}
const ID = {
  workspace: '00000000-0000-4000-8000-000000000001', owner: '00000000-0000-4000-8000-000000000002', project: '00000000-0000-4000-8000-000000000003', watchlist: '00000000-0000-4000-8000-000000000004',
  csvSource: '00000000-0000-4000-8000-000000000010', githubSource: '00000000-0000-4000-8000-000000000011', rssSource: '00000000-0000-4000-8000-000000000012', manifest: '00000000-0000-4000-8000-000000000013', signal: '00000000-0000-4000-8000-000000000020',
  import: '00000000-0000-4000-8000-000000000030', consent: '00000000-0000-4000-8000-000000000031', job: '00000000-0000-4000-8000-000000000032', investigation: '00000000-0000-4000-8000-000000000040', scope: '00000000-0000-4000-8000-000000000041', run: '00000000-0000-4000-8000-000000000042',
  evidence: '00000000-0000-4000-8000-000000000050', evidenceReview: '00000000-0000-4000-8000-000000000051', contentVersion: '00000000-0000-4000-8000-000000000052', contentItem: '00000000-0000-4000-8000-000000000053', independenceGroup: '00000000-0000-4000-8000-000000000054', claim: '00000000-0000-4000-8000-000000000060', claimVersion: '00000000-0000-4000-8000-000000000061', claimEvidence: '00000000-0000-4000-8000-000000000062', claimReview: '00000000-0000-4000-8000-000000000063',
    synthesis: '00000000-0000-4000-8000-000000000070', synthesisVersion: '00000000-0000-4000-8000-000000000071', synthesisReview: '00000000-0000-4000-8000-000000000072', brief: '00000000-0000-4000-8000-000000000080', briefVersion1: '00000000-0000-4000-8000-000000000081', briefVersion2: '00000000-0000-4000-8000-000000000082', briefVersion3: '00000000-0000-4000-8000-000000000084', readinessReview: '00000000-0000-4000-8000-000000000083', export: '00000000-0000-4000-8000-000000000090',
    createdGithub: '00000000-0000-4000-8000-000000000100', createdRss: '00000000-0000-4000-8000-000000000101', schedule: '00000000-0000-4000-8000-000000000110', validationHealth: '00000000-0000-4000-8000-000000000120', validationReconnect: '00000000-0000-4000-8000-000000000121',
};
const NOW = '2026-07-15T05:00:00Z';
const LATER = '2026-07-15T05:05:00Z';
const EXPORT_TIMESTAMP = LATER;
const SHA = (letter) => `sha256:${letter.repeat(64)}`;
const EVIDENCE_QUOTE = 'Permission previews would unblock our enterprise rollout.';
const textDigest = (value) => `sha256:${createHash('sha256').update(value).digest('hex')}`;
const state = { apiOffline: false, mutationRequestCount: 0, sseRequestCount: 0, offlineMutationRequestCount: 0, offlineSseRequestCount: 0, offlineExportRequestCount: 0, importState: 'none', importPayload: null, consentPreviewCount: 0, consentGrantAttempts: 0, consentGrantCount: 0, uploadCount: 0, signalTriaged: false, signalDisposition: null, signalTransitionCount: 0, investigationStatus: 'none', investigationRowVersion: 1, runState: 'none', runRowVersion: 1, latestSequence: 0, sseAttempt: 0, evidenceStatus: 'proposed', claimStatus: 'needs_review', synthesisStatus: 'none', synthesisRowVersion: 2, briefStatus: 'none', briefRowVersion: 1, briefVersion: 1, briefDocument: null, briefReadiness: 'draft', cloudSources: [], validationJobs: [], schedules: [], watchlistSourceIds: [ID.csvSource, ID.githubSource, ID.rssSource], watchlistRowVersion: 2, exportPostCount: 0, exportTerminalCount: 0, exportIdempotencyKeys: [], exportTimestamps: [] };

function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, normalize(item)]));
  return value;
}
const digest = (value) => `sha256:${createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(normalize(value))).digest('hex')}`;
const timestamps = () => ({ created_at: NOW, updated_at: LATER });
const cors = { 'Access-Control-Allow-Origin': ALLOWED_ORIGIN, 'Access-Control-Allow-Headers': 'Authorization, Content-Type, Idempotency-Key, If-Match, Last-Event-ID, X-Upload-Grant, X-Workspace-ID', 'Access-Control-Allow-Methods': 'GET, POST, PATCH, PUT, DELETE, OPTIONS', 'Access-Control-Expose-Headers': 'X-Upload-Grant, X-Request-ID' };
const send = (res, status, body, headers = {}) => { res.writeHead(status, { ...cors, 'Content-Type': 'application/json', ...headers }); res.end(JSON.stringify(body)); };
const fail = (res, message, status = 422) => send(res, status, { error: { code: 'VALIDATION_ERROR', message, request_id: ID.owner, details: {} } });
const failCode = (res, code, message, status) => send(res, status, { error: { code, message, request_id: ID.owner, details: {} } });
const page = (items) => ({ items, page: { next_cursor: null, has_more: false } });
const requireValue = (condition, message) => { if (!condition) throw new Error(message); };

async function body(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const bytes = Buffer.concat(chunks);
  if (!bytes.length) return null;
  return req.headers['content-type']?.startsWith('application/json') ? JSON.parse(bytes.toString('utf8')) : bytes;
}

function assertHeaders(req) {
  requireValue(req.headers.authorization === `Bearer ${ACCESS_TOKEN}`, 'Authorization must carry the configured access token, never a principal UUID.');
  requireValue(req.headers['x-workspace-id'] === ID.workspace, 'X-Workspace-ID must identify the fixture workspace.');
  if (!['GET', 'HEAD', 'OPTIONS', 'PUT'].includes(req.method)) requireValue(typeof req.headers['idempotency-key'] === 'string', 'Mutation requires Idempotency-Key.');
}

function source(kind) {
  if (kind === 'csv') return { id: ID.csvSource, workspace_id: ID.workspace, name: 'Customer feedback CSV', source_kind: 'imported_dataset', runtime: 'static_import', connector_type: 'csv', connector_version: 'csv-v1', status: 'healthy', source_config: null, cadence: null, timezone: null, last_run_at: state.importState === 'finalized' ? LATER : null, last_success_at: state.importState === 'finalized' ? LATER : null, health: { state: 'healthy', checked_at: LATER, last_error_code: null }, freshness: { state: state.importState === 'finalized' ? 'current' : 'never', last_success_at: state.importState === 'finalized' ? LATER : null }, capabilities: [], data_scope: 'workspace_confidential', current_import_manifest: state.importState === 'finalized' ? { id: ID.manifest, content_count: 1, finalized_at: LATER, data_authenticity: 'imported' } : null, row_version: state.importState === 'finalized' ? 2 : 1, data_authenticity: 'imported', ...timestamps() };
  if (kind === 'github') return { id: ID.githubSource, workspace_id: ID.workspace, name: 'Glint GitHub', source_kind: 'cloud', runtime: 'cloud', connector_type: 'github', connector_version: 'github-v1', status: 'degraded', source_config: { connector_type: 'github', repositories: [{ owner: 'openai', repository: 'glint', include_issues: true, include_discussions: true, include_releases: true }] }, cadence: 'daily', timezone: 'UTC', last_run_at: LATER, last_success_at: NOW, health: { state: 'degraded', checked_at: LATER, last_error_code: 'PARTIAL_DISCUSSIONS_SCOPE' }, freshness: { state: 'stale', last_success_at: NOW }, capabilities: ['search', 'fetch', 'health'], data_scope: 'public', current_import_manifest: null, row_version: 4, data_authenticity: 'collected', ...timestamps() };
  return { id: ID.rssSource, workspace_id: ID.workspace, name: 'Competitor release RSS', source_kind: 'cloud', runtime: 'cloud', connector_type: 'rss', connector_version: 'rss-v1', status: 'draft', source_config: { connector_type: 'rss', feeds: [{ name: 'Competitor releases', feed_url: 'https://example.com/releases.xml' }] }, cadence: 'weekly', timezone: 'Asia/Shanghai', last_run_at: null, last_success_at: null, health: { state: 'unknown', checked_at: null, last_error_code: null }, freshness: { state: 'never', last_success_at: null }, capabilities: ['fetch', 'health'], data_scope: 'public', current_import_manifest: null, row_version: 1, data_authenticity: 'collected', ...timestamps() };
}

function watchlist() {
  return { id: ID.watchlist, workspace_id: ID.workspace, project_id: ID.project, name: 'Permission friction watchlist', objective: 'Track permission friction across approved sources.', status: 'active', rules_version: 1, owner_id: ID.owner, source_connection_ids: state.watchlistSourceIds, rules: { schema_version: 'watchlist-rules-v1', entities: ['permission'], query_rules: { include_terms: ['permission'], exclude_terms: [], languages: [], regions: [] }, cadence: 'daily', current_window_days: 7, baseline_window_days: 28, notification_intent: false }, initial_baseline: { status: 'ready', current_count: 7, required_count: 3, candidate_count: 7, expected_detectable_at: NOW, reason: null, last_terminal_run_at: NOW }, row_version: state.watchlistRowVersion, data_authenticity: 'human_authored', ...timestamps() };
}

function createdCloudSource(record) {
  const payload = record.payload;
  return { id: record.id, workspace_id: ID.workspace, name: payload.name, source_kind: 'cloud', runtime: 'cloud', connector_type: payload.connector_type, connector_version: payload.connector_version, status: record.status, source_config: payload.source_config, cadence: payload.cadence, timezone: payload.timezone, last_run_at: null, last_success_at: null, health: { state: record.healthState, checked_at: record.healthCheckedAt, last_error_code: null }, freshness: { state: 'never', last_success_at: null }, capabilities: payload.connector_type === 'github' ? ['search', 'fetch', 'health'] : ['fetch', 'health'], data_scope: payload.data_scope, current_import_manifest: null, row_version: record.rowVersion, data_authenticity: 'collected', ...timestamps() };
}

function schedule(record) {
  return { id: ID.schedule, workspace_id: ID.workspace, source_connection_id: record.sourceConnectionId, watchlist_id: ID.watchlist, query_json: record.queryJson, cadence_seconds: record.cadenceSeconds, timezone: record.timezone, misfire_policy: 'run_once', catch_up: false, overlap_policy: 'skip', next_run_at: record.nextRunAt, enabled: record.enabled, lease_held: false, lease_expires_at: null, heartbeat_at: null, row_version: record.rowVersion, data_authenticity: 'collected', ...timestamps() };
}

function importSession(rowVersion) {
  const payload = state.importPayload;
  requireValue(payload, 'ImportSession payload is missing.');
  const uploaded = ['uploaded', 'finalized'].includes(state.importState);
  return { ...payload, id: ID.import, workspace_id: ID.workspace, state: state.importState, uploaded_object_key: uploaded ? `imports/${ID.import}/payload.csv` : null, uploaded_object_digest: uploaded ? payload.expected_upload_digest : null, terminal_manifest_id: state.importState === 'finalized' ? ID.manifest : null, failure_code: null, retryable: false, row_version: rowVersion, data_authenticity: 'imported', ...timestamps() };
}
function finalizationJob(stateName = 'completed') {
  return { id: ID.job, command_id: ID.job, workspace_id: ID.workspace, import_session_id: ID.import, expected_session_row_version: 3, expected_source_row_version: 1, expected_current_import_manifest_id: null, consent_record_id: ID.consent, state: stateName, attempt: 1, result_manifest_id: stateName === 'completed' ? ID.manifest : null, failure_code: stateName === 'failed' ? 'FIXTURE_FAILURE' : null, lease_expires_at: null, data_authenticity: 'imported', ...timestamps() };
}

function signal() {
  const confirmed = state.signalTriaged;
  const disposition = state.signalDisposition;
  const status = disposition?.action === 'dismiss' ? 'dismissed' : disposition?.action === 'undo' ? disposition.previous_status : confirmed ? 'triaged' : 'new';
  return { id: ID.signal, workspace_id: ID.workspace, watchlist_id: ID.watchlist, title: 'Permission friction rose in collected GitHub content', status, detector_version: 'detector-v2', trigger_rules: ['github_permission_mentions_delta >= 2'], limitations: ['GitHub discussions scope is currently partial.'], total_source_count: 1, independent_source_count: 1, cross_source_confirmation: false, per_source_freshness: [{ source_connection_id: ID.githubSource, state: 'stale', last_success_at: NOW }], window: { current_start: '2026-07-08T00:00:00Z', current_end: '2026-07-15T00:00:00Z', baseline_start: '2026-06-10T00:00:00Z', baseline_end: '2026-07-08T00:00:00Z' }, metrics: { current_count: 7, baseline_count: 2, mention_count: 7, independent_source_count: 1, platform_count: 1, growth_ratio: 3.5, robust_z: 2.25 }, dimensions: { detection_confidence: { level: 'high', calibration_status: 'calibrated', explanation: 'Versioned GitHub content crossed the configured change threshold.' }, business_impact: { suggested_level: 'medium', suggested_explanation: 'Enterprise onboarding mentions increased.', suggestion_origin: 'deterministic_rule', suggestion_version: 'impact-v1', confirmed_level: confirmed ? 'high' : null, confirmed_by: confirmed ? ID.owner : null, confirmed_at: confirmed ? LATER : null, version: confirmed ? 1 : 0 }, urgency: { suggested_level: 'monitor', suggested_explanation: 'No outage language detected.', suggestion_origin: 'deterministic_rule', suggestion_version: 'urgency-v1', confirmed_level: confirmed ? 'this_week' : null, confirmed_by: confirmed ? ID.owner : null, confirmed_at: confirmed ? LATER : null, version: confirmed ? 1 : 0 }, priority: { level: confirmed ? 'P1' : null, status: confirmed ? 'derived' : 'pending_confirmation', policy_version: 'priority-matrix-v1', explanation: confirmed ? 'Derived from confirmed Impact and Urgency.' : 'Awaiting owner confirmation.' } }, disposition, row_version: (confirmed ? 2 : 1) + state.signalTransitionCount, data_authenticity: 'collected', ...timestamps() };
}

function investigation() { return { id: ID.investigation, workspace_id: ID.workspace, project_id: ID.project, signal_id: ID.signal, current_scope_version_id: ID.scope, status: state.investigationStatus === 'none' ? 'draft' : state.investigationStatus, owner_id: ID.owner, current_synthesis_id: state.synthesisStatus === 'none' ? null : ID.synthesis, decision_brief_id: state.briefStatus === 'none' ? null : ID.brief, decision_question: 'Should permission execution preview enter next-quarter prioritization?', row_version: state.investigationRowVersion, data_authenticity: 'collected', ...timestamps() }; }
function scope() { return { id: ID.scope, workspace_id: ID.workspace, investigation_id: ID.investigation, version_number: 1, decision_question: investigation().decision_question, source_scope_json: { source_connection_ids: [ID.githubSource], content_version_ids: [], allow_cloud_model: false }, time_range: { start: '2026-07-08T00:00:00Z', end: '2026-07-15T00:00:00Z' }, budget: { max_cost_usd: '4.0000', max_duration_seconds: 900 }, stop_conditions: ['Evidence and counter-evidence have both been reviewed.'], created_by: ID.owner, change_reason: 'Initial investigation scope.', created_at: NOW, data_authenticity: 'collected' }; }
function run() { return { id: ID.run, workspace_id: ID.workspace, investigation_id: ID.investigation, investigation_scope_version_id: ID.scope, state: state.runState, waiting_for_input_reason: null, graph_version: 'deterministic-cloud-v1', run_input_manifest_digest: SHA('d'), budget: { max_cost_usd: '4.0000', max_duration_seconds: 900 }, used_cost_usd: '0.1000', attempt_number: 1, initiated_by: ID.owner, latest_sequence: state.latestSequence, row_version: state.runRowVersion, data_authenticity: 'collected', ...timestamps() }; }
function evidence() { return { id: ID.evidence, workspace_id: ID.workspace, investigation_id: ID.investigation, research_run_id: ID.run, content_version_id: ID.contentVersion, quote_start: 0, quote_end: EVIDENCE_QUOTE.length, quote_text: EVIDENCE_QUOTE, quote_text_digest: SHA('e'), stance: 'supports', status: state.evidenceStatus, latest_review: state.evidenceStatus === 'proposed' ? null : { id: ID.evidenceReview, decision: state.evidenceStatus, policy_version: 'evidence-review-v1', reviewed_at: LATER }, relevance: 0.9, reliability: 0.8, independence: 1, recency: 0.9, specificity: 0.8, provenance: { research_run_id: ID.run, extraction_method: 'deterministic_collected_v1' }, data_authenticity: 'collected' }; }
function claim() { return { id: ID.claim, workspace_id: ID.workspace, investigation_id: ID.investigation, research_run_id: ID.run, current_version: { id: ID.claimVersion, claim_id: ID.claim, version_number: 1, claim_type: 'product_risk', text: 'Opaque permission execution materially slows enterprise onboarding.', confidence_inputs_json: { support_count: 1 }, confidence_level: 'medium', calibration_status: 'uncalibrated', limitations: ['The collected source scope is bounded.'], status: state.claimStatus, created_by: ID.owner, created_at: NOW, data_authenticity: 'collected' }, evidence_links: [{ id: ID.claimEvidence, evidence_id: ID.evidence, stance: 'supports', weight: 1, rationale: 'Pinned exact Evidence.' }], owner_id: ID.owner, row_version: state.claimStatus === 'verified' ? 2 : 1, data_authenticity: 'collected', ...timestamps() }; }
function synthesis() { return { id: ID.synthesis, workspace_id: ID.workspace, investigation_id: ID.investigation, current_version: { id: ID.synthesisVersion, synthesis_id: ID.synthesis, investigation_id: ID.investigation, version_number: 1, verified_claim_version_snapshot_json: [ID.claimVersion], claim_review_snapshot_json: [ID.claimReview], generation_method: 'deterministic', generator_version: 'deterministic-synthesis-v1', model_prompt_refs_json: [], executive_summary: claim().current_version.text, business_implications: [claim().current_version.text], limitations: ['The collected source scope is bounded.'], provenance_digest: SHA('f'), status: state.synthesisStatus, created_by: ID.owner, created_at: NOW, data_authenticity: 'collected' }, row_version: state.synthesisRowVersion, data_authenticity: 'collected', ...timestamps() }; }
const reference = { synthesis_version_id: ID.synthesisVersion, synthesis_review_id: ID.synthesisReview, claim_version_ids: [ID.claimVersion], claim_review_ids: [ID.claimReview], claim_evidence_ids: [ID.claimEvidence], evidence_review_ids: [ID.evidenceReview], evidence_ids: [ID.evidence], content_version_ids: [ID.contentVersion] };
function initialDocument() { return { schema_version: 'decision-brief-blocks-v1', blocks: [{ id: 'fact-1', type: 'fact', body: claim().current_version.text, claim_version_ids: [ID.claimVersion], evidence_ids: [ID.evidence], content_version_ids: [ID.contentVersion] }, { id: 'synthesis-1', type: 'synthesis', body: synthesis().current_version.executive_summary, synthesis_version_id: ID.synthesisVersion, generation_method: 'deterministic', generator_version: 'deterministic-synthesis-v1', model_prompt_refs: [] }, { id: 'judgment-1', type: 'pm_judgment', body: 'PM judgment pending', actor_id: ID.owner }, { id: 'recommendation-1', type: 'recommendation', body: 'Recommendation pending', recommendation_status: 'proposed' }], no_counter_evidence_search: null }; }
const renderedExport = () => `# PRD Research Input

> Data authenticity: Collected

## Export Metadata

- Decision Brief Version: ${state.briefVersion} (${currentBriefVersionId()})
- Data Authenticity: Collected
- Source References: source:${ID.githubSource}
- Evidence References / Content Versions:
  - evidence:${ID.evidence} -> content-version:${ID.contentVersion}
- Export Timestamp: ${EXPORT_TIMESTAMP}
- Readiness State: decision_ready/current

## Fact

Opaque permission execution materially slows enterprise onboarding.

## PM Judgment

The owner PM recommends enterprise-admin validation.

## Recommendation

Validate a permission execution preview with enterprise administrators.
`;
function currentBriefVersionId() { const versionId = [ID.briefVersion1, ID.briefVersion2, ID.briefVersion3][state.briefVersion - 1]; requireValue(versionId, `Fixture has no DecisionBriefVersion ${state.briefVersion}.`); return versionId; }
const exportReferenceDigest = () => digest({ decision_brief_version_id: currentBriefVersionId(), export_timestamp: EXPORT_TIMESTAMP, rendered_content: renderedExport() });
function brief() { const document = state.briefDocument ?? initialDocument(); return { id: ID.brief, workspace_id: ID.workspace, investigation_id: ID.investigation, current_version: { id: currentBriefVersionId(), decision_brief_id: ID.brief, investigation_id: ID.investigation, version_number: state.briefVersion, synthesis_version_id: ID.synthesisVersion, synthesis_review_id: ID.synthesisReview, block_document: document, reference_snapshot_json: reference, template_version: 'decision-brief-v1', human_edit_digest: digest(document), readiness: state.briefReadiness, freshness: 'current', created_by: ID.owner, created_at: NOW, data_authenticity: 'collected' }, status: state.briefStatus, owner_id: ID.owner, decision_outcome: null, next_checkpoint_at: null, row_version: state.briefRowVersion, data_authenticity: 'collected', ...timestamps() }; }

function bootstrap() {
  return { workspace_id: ID.workspace, workspace: { id: ID.workspace, workspace_id: ID.workspace, name: 'API Contract Workspace', status: 'active', data_region: 'default', retention_policy_version: 'retention-v1', row_version: 1, data_authenticity: 'human_authored', ...timestamps() }, projects: [], watchlists: [watchlist()], sources: [source('csv'), source('github'), source('rss'), ...state.cloudSources.map(createdCloudSource)], signals: state.importState === 'finalized' ? [signal()] : [], investigations: state.investigationStatus === 'none' ? [] : [investigation()], decision_briefs: state.briefStatus === 'none' ? [] : [brief()], cursors: { run_events: null }, computed_at: LATER, data_authenticity: 'human_authored' };
}

function navigation() { return { workspace_id: ID.workspace, unreviewed_signal_count: state.importState === 'finalized' && !state.signalTriaged ? 1 : 0, investigation_needs_input_count: 0, draft_decision_brief_count: state.briefStatus === 'draft' ? 1 : 0, monitoring_health: 'degraded', computed_at: LATER, data_authenticity: 'human_authored' }; }

const runEventId = (sequence) => `00000000-0000-4000-8000-${String(200 + sequence).padStart(12, '0')}`;
function sseEvent(sequence, eventType, payload) { const eventId = runEventId(sequence); const wire = { data_authenticity: 'collected', run_id: ID.run, sequence, event_id: eventId, event_type: eventType, payload, trace_id: 'fixture-trace', timestamp: LATER }; return `id: ${eventId}\nevent: ${eventType}\ndata: ${JSON.stringify(wire)}\n\n`; }

const server = createServer(async (req, res) => {
  const requestUrl = new URL(req.url, `http://${req.headers.host}`);
  process.stdout.write(
    `${req.method} ${requestUrl.pathname} origin=${req.headers.origin ?? 'none'}\n`,
  );
  if (req.method === 'OPTIONS') { res.writeHead(204, cors); res.end(); return; }
  try {
    if (req.method === 'GET' && req.url === '/healthz') return send(res, 200, { status: 'ok' });
    assertHeaders(req);
    const path = requestUrl.pathname.replace(/^\/v1/, '');
    const payload = await body(req);
    if (req.method === 'POST' && path === '/fixture-control') { requireValue(typeof payload.api_offline === 'boolean', 'Fixture control requires an explicit API offline state.'); state.apiOffline = payload.api_offline; return send(res, 200, { api_offline: state.apiOffline }); }
    if (req.method === 'GET' && path === '/fixture-state') return send(res, 200, { api_offline: state.apiOffline, mutation_request_count: state.mutationRequestCount, sse_request_count: state.sseRequestCount, offline_mutation_request_count: state.offlineMutationRequestCount, offline_sse_request_count: state.offlineSseRequestCount, offline_export_request_count: state.offlineExportRequestCount, consent_preview_count: state.consentPreviewCount, consent_grant_attempts: state.consentGrantAttempts, consent_grant_count: state.consentGrantCount, upload_count: state.uploadCount, signal_transition_count: state.signalTransitionCount, signal_disposition: state.signalDisposition, export_post_count: state.exportPostCount, export_terminal_count: state.exportTerminalCount, export_idempotency_keys: state.exportIdempotencyKeys, export_timestamps: state.exportTimestamps });
    if (state.apiOffline) {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method)) state.offlineMutationRequestCount += 1;
      if (req.method === 'GET' && path.endsWith('/events')) state.offlineSseRequestCount += 1;
      if (req.method === 'POST' && path.endsWith('/exports')) state.offlineExportRequestCount += 1;
      return failCode(res, 'API_OFFLINE', 'Fixture API is offline.', 503);
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method)) state.mutationRequestCount += 1;
    if (req.method === 'GET' && path === '/sync/bootstrap') return send(res, 200, bootstrap());
    if (req.method === 'GET' && path === '/workspaces') return send(res, 200, [{ workspace_id: ID.workspace, user_id: ID.owner, workspace_name: 'Glint Contract Workspace', role: 'owner', status: 'active', data_authenticity: 'human_authored' }]);
    if (req.method === 'GET' && path === '/navigation-summary') return send(res, 200, navigation());
    if (req.method === 'GET' && path === '/collection-schedules') return send(res, 200, page(state.schedules.map(schedule)));
    if (req.method === 'POST' && path === '/sources') {
      requireValue(payload.source_kind === 'cloud' && payload.runtime === 'cloud' && ['github', 'rss'].includes(payload.connector_type), 'Cloud SourceConnection must use the cloud runtime and a supported connector.');
      requireValue(payload.connector_version === `${payload.connector_type}-v1` && payload.data_scope === 'public' && ['daily', 'weekly', 'manual'].includes(payload.cadence) && typeof payload.timezone === 'string', 'Cloud SourceConnection requires connector version, data scope, cadence, and timezone.');
      requireValue(payload.source_config?.connector_type === payload.connector_type, 'Strict source_config must match connector_type.');
      if (payload.connector_type === 'github') {
        requireValue(payload.credential_ref === 'env://github_token', 'GitHub credential_ref must default to the replaceable environment reference.');
        requireValue(payload.source_config.repositories?.length === 1 && payload.source_config.repositories[0].owner === 'openai' && payload.source_config.repositories[0].repository === 'glint-ui-contracts', 'GitHub create must carry one exact approved repository.');
        requireValue(['include_issues', 'include_discussions', 'include_releases'].every((key) => payload.source_config.repositories[0][key] === true), 'GitHub create must explicitly configure collection capabilities.');
      } else {
        requireValue(payload.source_config.feeds?.length === 1 && payload.source_config.feeds[0].name === 'Product releases' && payload.source_config.feeds[0].feed_url === 'https://example.com/product-releases.xml', 'RSS create must carry one exact HTTPS feed.');
        requireValue(!('credential_ref' in payload), 'RSS create must not invent a credential reference.');
      }
      const id = payload.connector_type === 'github' ? ID.createdGithub : ID.createdRss;
      requireValue(!state.cloudSources.some((item) => item.id === id), `Only one fixture ${payload.connector_type} source may be created.`);
      const record = { id, payload, status: 'draft', healthState: 'unknown', healthCheckedAt: null, rowVersion: 1 };
      state.cloudSources.push(record);
      return send(res, 201, createdCloudSource(record));
    }
    const sourceRoute = path.match(/^\/sources\/([^/]+)$/);
    if (sourceRoute && req.method === 'GET') {
      const base = sourceRoute[1] === ID.csvSource ? source('csv') : sourceRoute[1] === ID.githubSource ? source('github') : sourceRoute[1] === ID.rssSource ? source('rss') : null;
      const created = state.cloudSources.find((item) => item.id === sourceRoute[1]);
      requireValue(base || created, 'SourceConnection was not found.');
      return send(res, 200, base ?? createdCloudSource(created));
    }
    if (sourceRoute && req.method === 'PATCH') {
      const record = state.cloudSources.find((item) => item.id === sourceRoute[1]);
      requireValue(record, 'Created cloud source was not found.');
      requireValue(payload.expected_row_version === record.rowVersion, 'Source PATCH must pin expected_row_version.');
      requireValue(payload.source_config?.connector_type === record.payload.connector_type && (payload.source_config.repositories?.length === 1 || payload.source_config.feeds?.length === 1), 'Source PATCH must send the complete matching single-target source_config.');
      requireValue(typeof payload.name === 'string' && ['daily', 'weekly', 'manual'].includes(payload.cadence) && typeof payload.timezone === 'string', 'Source PATCH must send exact editable configuration.');
      if (record.payload.connector_type === 'github') requireValue(payload.credential_ref === 'env://github_token', 'GitHub credential reference must be explicitly replaceable during configuration.');
      record.payload = { ...record.payload, name: payload.name, cadence: payload.cadence, timezone: payload.timezone, source_config: payload.source_config, ...(payload.credential_ref ? { credential_ref: payload.credential_ref } : {}) };
      record.rowVersion += 1;
      return send(res, 200, createdCloudSource(record));
    }
    const sourceCommand = path.match(/^\/sources\/([^/]+)\/(activate|disable|remove)$/);
    if (sourceCommand && req.method === 'POST') {
      const record = state.cloudSources.find((item) => item.id === sourceCommand[1]);
      requireValue(record, 'Created cloud source was not found.');
      requireValue(payload.expected_row_version === record.rowVersion && typeof payload.reason === 'string', `Source ${sourceCommand[2]} must pin expected_row_version and reason.`);
      const action = sourceCommand[2];
      record.status = action === 'disable' || action === 'remove' ? 'disabled' : 'validating';
      record.healthState = action === 'disable' || action === 'remove' ? 'disabled' : 'unknown';
      record.healthCheckedAt = null;
      record.rowVersion += 1;
      return send(res, 200, createdCloudSource(record));
    }
    const validationCommand = path.match(/^\/sources\/([^/]+)\/(health-check|reconnect)$/);
    if (validationCommand && req.method === 'POST') {
      const record = state.cloudSources.find((item) => item.id === validationCommand[1]);
      requireValue(record && payload.expected_row_version === record.rowVersion && typeof payload.reason === 'string', 'Source validation must pin exact source row_version and reason.');
      const command = validationCommand[2] === 'health-check' ? 'health_check' : 'reconnect';
      const jobId = command === 'health_check' ? ID.validationHealth : ID.validationReconnect;
      record.status = 'validating'; record.healthState = 'unknown'; record.healthCheckedAt = null; record.rowVersion += 1;
      const expectedRowVersion = record.rowVersion;
      record.status = command === 'health_check' ? 'healthy' : 'degraded'; record.healthState = record.status; record.healthCheckedAt = LATER; record.rowVersion += 1;
      const job = { id: jobId, workspace_id: ID.workspace, source_connection_id: record.id, command, state: 'completed', expected_source_row_version: expectedRowVersion, attempt: 1, result_source_status: record.status, failure_code: null, failure_reason: null, lease_expires_at: null, created_at: NOW, updated_at: LATER, data_authenticity: 'collected' };
      state.validationJobs.push(job);
      return send(res, 202, job);
    }
    const validationJob = path.match(/^\/source-validation-jobs\/([^/]+)$/);
    if (validationJob && req.method === 'GET') { const job = state.validationJobs.find((item) => item.id === validationJob[1]); requireValue(job, 'SourceValidationJob was not found.'); return send(res, 200, job); }
    const sourceHealth = path.match(/^\/sources\/([^/]+)\/health$/);
    if (sourceHealth && req.method === 'GET') {
      const record = state.cloudSources.find((item) => item.id === sourceHealth[1]);
      requireValue(record, 'Created cloud source was not found.');
      return send(res, 200, createdCloudSource(record));
    }
    if (req.method === 'PATCH' && path === `/watchlists/${ID.watchlist}`) {
      requireValue(payload.expected_row_version === state.watchlistRowVersion && Array.isArray(payload.source_connection_ids), 'Watchlist binding must pin row_version and send the complete source list.');
      requireValue(payload.source_connection_ids.includes(ID.createdGithub), 'Cloud source must be bound to the active Watchlist before scheduling.');
      state.watchlistSourceIds = payload.source_connection_ids;
      state.watchlistRowVersion += 1;
      return send(res, 200, watchlist());
    }
    if (req.method === 'POST' && path === '/collection-schedules') {
      const record = state.cloudSources.find((item) => item.id === payload.source_connection_id);
      requireValue(record && ['validating', 'healthy', 'degraded'].includes(record.status), 'Schedule requires an activated cloud source.');
      requireValue(state.watchlistSourceIds.includes(record.id), 'Schedule requires the source to be bound to the active Watchlist first.');
      requireValue(payload.workspace_id === ID.workspace && payload.watchlist_id === ID.watchlist, 'Schedule must bind the current workspace and active Watchlist.');
      requireValue(payload.cadence_seconds === 86400 && payload.timezone === record.payload.timezone && payload.misfire_policy === 'run_once' && payload.catch_up === false && payload.overlap_policy === 'skip' && payload.enabled === true, 'Schedule policy fields must match the strict owner configuration.');
      if (record.payload.connector_type === 'github') requireValue(payload.query_json.owner === 'openai' && payload.query_json.repo === 'glint-ui-contracts' && payload.query_json.query === 'permission friction' && payload.query_json.max_pages === 5, 'GitHub schedule query must stay inside the approved repository.');
      else requireValue(payload.query_json.feed_url === 'https://example.com/product-releases.xml', 'RSS schedule query must stay inside the approved feed.');
      const scheduleRecord = { sourceConnectionId: record.id, queryJson: payload.query_json, cadenceSeconds: payload.cadence_seconds, timezone: payload.timezone, nextRunAt: payload.next_run_at, enabled: true, rowVersion: 1 };
      state.schedules.push(scheduleRecord);
      return send(res, 201, schedule(scheduleRecord));
    }
    if (req.method === 'PATCH' && path === `/collection-schedules/${ID.schedule}`) {
      const record = state.schedules.find((item) => item.sourceConnectionId === ID.createdGithub);
      requireValue(record && payload.expected_row_version === record.rowVersion && typeof payload.enabled === 'boolean', 'Schedule PATCH must pin row_version and explicit enabled state.');
      requireValue(Object.keys(payload).sort().join(',') === 'enabled,expected_row_version', 'Schedule enable/disable PATCH must not mutate unrelated policy fields.');
      record.enabled = payload.enabled;
      record.rowVersion += 1;
      return send(res, 200, schedule(record));
    }
    if (req.method === 'GET' && path === '/imports') return send(res, 200, page(state.importState === 'none' ? [] : [{ import_session: importSession(state.importState === 'finalized' ? 4 : state.importState === 'uploaded' ? 3 : state.importState === 'consented' ? 2 : 1), finalization_job: state.importState === 'finalized' ? finalizationJob() : null, data_authenticity: 'imported' }]));
    if (req.method === 'POST' && path === '/imports') { requireValue(payload.client_file_name === 'feedback.csv' && !('file_path' in payload) && !('file' in payload), 'ImportSession must remain metadata-only.'); state.importPayload = payload; state.importState = 'draft'; return send(res, 201, importSession(1)); }
    if (req.method === 'GET' && path === `/imports/${ID.import}/upload-consent/preview`) {
      requireValue(requestUrl.searchParams.get('expected_row_version') === '1', 'Consent preview must pin the draft ImportSession row_version.');
      requireValue(state.importState === 'draft' && state.importPayload, 'Consent preview requires a metadata-only draft ImportSession.');
      state.consentPreviewCount += 1;
      const metadata = state.importPayload;
      const previewScope = { destination_workspace_id: ID.workspace, import_session_id: ID.import, import_session_row_version: 1, source_connection_id: ID.csvSource, source_row_version: 1, current_import_manifest_id: null, local_manifest_digest: metadata.local_manifest_digest, file_digest: metadata.file_digest, expected_upload_digest: metadata.expected_upload_digest, selected_scope_digest: metadata.selected_scope_digest, upload_object_scope: { object_key: `imports/${ID.import}.csv`, max_bytes: metadata.file_size_bytes, media_type: 'text/csv' }, policy_version: 'import-transfer-v1' };
      return send(res, 200, { preview_scope: previewScope, scope_digest: digest(previewScope), data_authenticity: 'imported' });
    }
    if (req.method === 'POST' && path === `/imports/${ID.import}/upload-consent`) {
      state.consentGrantAttempts += 1;
      if (state.consentGrantAttempts === 1) return failCode(res, 'CONSENT_SCOPE_STALE', 'Upload consent scope changed; load and review a fresh preview.', 412);
      const metadata = state.importPayload;
      const exactScope = { destination_workspace_id: ID.workspace, import_session_id: ID.import, import_session_row_version: 1, source_connection_id: ID.csvSource, source_row_version: 1, current_import_manifest_id: null, local_manifest_digest: metadata.local_manifest_digest, file_digest: metadata.file_digest, expected_upload_digest: metadata.expected_upload_digest, selected_scope_digest: metadata.selected_scope_digest, upload_object_scope: { object_key: `imports/${ID.import}.csv`, max_bytes: metadata.file_size_bytes, media_type: 'text/csv' }, policy_version: 'import-transfer-v1' };
      requireValue(payload.confirmation === true && JSON.stringify(normalize(payload.preview_scope)) === JSON.stringify(normalize(exactScope)) && payload.scope_digest === digest(exactScope), 'UploadConsent must append the exact reviewed preview scope and digest.');
      state.consentGrantCount += 1; state.importState = 'consented';
      return send(res, 200, { import_session: importSession(2), consent_record: { id: ID.consent, workspace_id: ID.workspace, import_session_id: ID.import, decision: 'grant', local_manifest_digest: metadata.local_manifest_digest, file_digest: metadata.file_digest, expected_upload_digest: metadata.expected_upload_digest, selected_scope_json: metadata.selected_scope_json, selected_scope_digest: metadata.selected_scope_digest, destination_workspace_id: ID.workspace, upload_object_scope: exactScope.upload_object_scope, model_egress_authorization: 'none', policy_version: 'import-transfer-v1', actor_id: ID.owner, recorded_at: NOW, expires_at: payload.expires_at, supersedes_id: null, data_authenticity: 'imported' }, upload: { object_key: exactScope.upload_object_scope.object_key, maximum_bytes: exactScope.upload_object_scope.max_bytes, media_type: 'text/csv', expires_at: payload.expires_at }, data_authenticity: 'imported' }, { 'X-Upload-Grant': 'fixture-upload-grant' });
    }
    if (req.method === 'PUT' && path === `/imports/${ID.import}/object`) { requireValue(req.headers['x-upload-grant'] === 'fixture-upload-grant' && Buffer.isBuffer(payload), 'PUT object requires the response-header upload grant and bytes.'); state.uploadCount += 1; return send(res, 201, { object_key: `imports/${ID.import}.csv`, data_authenticity: 'imported' }); }
    if (req.method === 'POST' && path === `/imports/${ID.import}/upload-complete`) { requireValue(payload.expected_row_version === 2 && payload.object_key === `imports/${ID.import}.csv`, 'UploadComplete must use exact object_key.'); state.importState = 'uploaded'; return send(res, 200, importSession(3)); }
    if (req.method === 'POST' && path === `/imports/${ID.import}/finalize`) { requireValue(payload.expected_row_version === 3, 'Finalize must pin uploaded row_version.'); state.importState = 'finalized'; return send(res, 202, finalizationJob()); }
    if (req.method === 'GET' && path === `/imports/${ID.import}`) return send(res, 200, importSession(state.importState === 'finalized' ? 4 : 3));
    if (req.method === 'POST' && path === `/signals/${ID.signal}/triage`) { requireValue(payload.expected_signal_row_version === 1 && payload.business_impact.confirmed_level === 'high' && payload.urgency.confirmed_level === 'this_week', 'SignalTriage must carry exact assessments.'); state.signalTriaged = true; return send(res, 200, signal()); }
    if (req.method === 'POST' && path === `/signals/${ID.signal}/transitions`) {
      const current = signal();
      requireValue(payload.expected_row_version === current.row_version, 'Signal transition must pin the current row_version.');
      requireValue(payload.action === 'dismiss', 'Fixture command workflow only allows the audited dismiss transition.');
      requireValue(['duplicate', 'single_author_spike', 'irrelevant', 'known_issue', 'bad_data', 'other'].includes(payload.dismiss_reason), 'Dismiss reason must use the contract enum.');
      requireValue(typeof payload.note === 'string' && payload.note.trim().length > 0 && typeof payload.session_id === 'string', 'Dismiss must carry a note and UI session id.');
      state.signalDisposition = { action: 'dismiss', previous_status: current.status, session_id: payload.session_id, cooldown_until: null, dismiss_reason: payload.dismiss_reason, note: payload.note.trim(), transitioned_at: LATER, undone_at: null };
      state.signalTransitionCount += 1;
      return send(res, 200, signal());
    }
    if (req.method === 'POST' && path === '/investigations') { requireValue(payload.signal_id === ID.signal && payload.source_scope.source_connection_ids.length === 1 && payload.source_scope.source_connection_ids[0] === ID.githubSource, 'Investigation must pin only the successful cloud source named by Signal evidence.'); state.investigationStatus = 'draft'; state.investigationRowVersion = 1; return send(res, 201, investigation()); }
    if (req.method === 'POST' && path === `/investigations/${ID.investigation}/transitions`) return failCode(res, 'INVALID_STATE', 'Independent activation is forbidden; ResearchRun creation owns first activation.', 409);
    if (req.method === 'GET' && path === `/investigations/${ID.investigation}`) return send(res, 200, investigation());
    if (req.method === 'GET' && path === `/investigations/${ID.investigation}/scope-versions`) return send(res, 200, page([scope()]));
    if (req.method === 'POST' && path === '/research-runs') { requireValue(payload.investigation_id === ID.investigation && payload.investigation_scope_version_id === ID.scope && payload.expected_investigation_row_version === 1 && state.investigationStatus === 'draft' && state.signalTriaged, 'ResearchRun must atomically activate the triaged draft Investigation with its current ScopeVersion.'); state.investigationStatus = 'active'; state.investigationRowVersion = 2; state.runState = 'running'; state.latestSequence = 2; state.runRowVersion = 2; return send(res, 202, run()); }
    if (req.method === 'GET' && path === '/research-runs') return send(res, 200, page(state.runState === 'none' ? [] : [run()]));
    if (req.method === 'GET' && path === `/research-runs/${ID.run}`) return send(res, 200, run());
    if (req.method === 'GET' && path === `/research-runs/${ID.run}/events`) {
      state.sseRequestCount += 1;
      state.sseAttempt += 1;
      res.writeHead(200, { ...cors, 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      if (state.sseAttempt === 1) {
        requireValue(!req.headers['last-event-id'], 'Initial SSE tail must not invent a Last-Event-ID.');
        state.latestSequence = 2;
        state.runRowVersion = 2;
        res.end(sseEvent(1, 'run.queued', { state: 'queued', safe_summary: 'Immutable run input accepted.' }) + sseEvent(2, 'run.started', { state: 'running', safe_summary: 'Deterministic worker started.' }));
        return;
      }
      if (state.sseAttempt === 2) {
        requireValue(req.headers['last-event-id'] === runEventId(2), 'SSE reconnect must resume with the durable Last-Event-ID.');
        state.latestSequence = 4;
        res.end(sseEvent(2, 'run.started', { state: 'running', safe_summary: 'Deterministic worker started.' }) + sseEvent(4, 'claim.version_proposed', { claim_id: ID.claim, claim_version_id: ID.claimVersion, safe_summary: 'BROKEN GAP EVENT MUST BE DISCARDED' }));
        return;
      }
      requireValue(!req.headers['last-event-id'], 'A gap reset must clear the stale Last-Event-ID before reconnecting.');
      state.runState = 'completed';
      state.latestSequence = 5;
      state.runRowVersion = 3;
      res.end(sseEvent(1, 'run.queued', { state: 'queued', safe_summary: 'Immutable run input accepted.' }) + sseEvent(2, 'run.started', { state: 'running', safe_summary: 'Deterministic worker started.' }) + sseEvent(3, 'evidence.proposed', { evidence_id: ID.evidence, safe_summary: 'Evidence proposal persisted.' }) + sseEvent(4, 'claim.version_proposed', { claim_id: ID.claim, claim_version_id: ID.claimVersion, safe_summary: 'Claim proposal persisted.' }) + sseEvent(5, 'run.completed', { state: 'completed', safe_summary: 'Evidence and Claim proposal persisted.' }));
      return;
    }
    if (req.method === 'GET' && path === '/claims') return send(res, 200, page(state.runState === 'none' ? [] : [claim()]));
    if (req.method === 'GET' && path === `/evidence/${ID.evidence}`) return send(res, 200, evidence());
    if (req.method === 'GET' && path === '/content-items') return fail(res, 'Full ContentItem scans are forbidden.', 500);
    if (req.method === 'GET' && path === `/content-versions/${ID.contentVersion}`) return send(res, 200, { id: ID.contentVersion, workspace_id: ID.workspace, content_item_id: ID.contentItem, source_connection_id: ID.githubSource, source_name: 'Glint GitHub', source_kind: 'cloud', source_item_id: 'github:openai/glint:issue:42', identity_key: 'github:openai/glint:issue:42', title: 'Permission execution preview request', canonical_url: 'https://github.com/openai/glint/issues/42', duplicate_cluster_id: null, independence_group_id: ID.independenceGroup, version_number: 1, content_digest: SHA('c'), normalized_title: 'Permission execution preview request', normalized_body: `${EVIDENCE_QUOTE}\n\nCaptured GitHub issue context remains immutable.`, metadata_json: { author: 'customer-admin', canonical_url: 'https://github.com/openai/glint/issues/42', published_at: NOW, source_item_id: 'github:openai/glint:issue:42', independence_group_id: ID.independenceGroup }, published_at: NOW, captured_at: LATER, parser_version: 'github-v1', availability: 'captured', availability_last_checked_at: LATER, availability_reason: null, data_scope: 'public', data_authenticity: 'collected', created_at: LATER });
    if (req.method === 'GET' && path === `/signals/${ID.signal}/evidence`) return send(res, 200, page([{ signal_id: ID.signal, content_version_id: ID.contentVersion, role: 'trigger', independence_group_id: ID.independenceGroup, contribution: 0.9, data_authenticity: 'collected' }]));
    if (req.method === 'POST' && path === `/evidence/${ID.evidence}/review`) { requireValue(payload.decision === 'valid' && payload.policy_version === 'evidence-review-v1', 'EvidenceReview requires exact DTO and policy_version.'); state.evidenceStatus = 'valid'; return send(res, 201, { id: ID.evidenceReview, evidence_id: ID.evidence, decision: 'valid', reviewer_id: ID.owner, reason: payload.reason, policy_version: payload.policy_version, reviewed_at: LATER, data_authenticity: 'collected' }); }
    if (req.method === 'POST' && path === `/claims/${ID.claim}/versions/${ID.claimVersion}/review`) { const expected = digest({ claim_version_id: ID.claimVersion, claim_evidence_ids: [ID.claimEvidence], evidence_review_ids: [ID.evidenceReview] }); requireValue(payload.decision === 'verify' && payload.expected_claim_evidence_snapshot_digest === expected && payload.evidence_review_ids[0] === ID.evidenceReview, 'ClaimReview must pin exact EvidenceReview snapshot digest.'); state.claimStatus = 'verified'; return send(res, 201, { id: ID.claimReview, claim_version_id: ID.claimVersion, decision: 'verify', claim_evidence_snapshot_json: [ID.claimEvidence], evidence_review_snapshot_json: [ID.evidenceReview], snapshot_digest: expected, reviewer_id: ID.owner, reason: payload.reason, policy_version: 'claim-review-v1', reviewed_at: LATER, data_authenticity: 'collected' }); }
    if (req.method === 'GET' && path === `/investigations/${ID.investigation}/synthesis`) return state.synthesisStatus === 'none' ? fail(res, 'Investigation synthesis not found.', 404) : send(res, 200, synthesis());
    if (req.method === 'POST' && path === `/investigations/${ID.investigation}/synthesis`) { requireValue(payload.verified_claim_version_ids[0] === ID.claimVersion, 'Synthesis must use the verified ClaimVersion.'); state.synthesisStatus = 'needs_review'; state.synthesisRowVersion = 2; state.investigationRowVersion = 3; return send(res, 201, synthesis()); }
    if (req.method === 'PATCH' && path === `/investigations/${ID.investigation}/synthesis`) { requireValue(payload.expected_row_version === state.synthesisRowVersion && typeof payload.executive_summary === 'string' && Array.isArray(payload.business_implications) && Array.isArray(payload.limitations), 'Synthesis revision must send complete content and row_version.'); state.synthesisStatus = 'needs_review'; state.synthesisRowVersion += 1; return send(res, 200, synthesis()); }
    if (req.method === 'POST' && path === `/investigations/${ID.investigation}/synthesis/versions/${ID.synthesisVersion}/review`) { requireValue(payload.synthesis_version_id === ID.synthesisVersion && payload.expected_row_version === state.synthesisRowVersion && ['verify', 'reject'].includes(payload.decision) && payload.policy_version === 'synthesis-review-v1', 'SynthesisReview must pin exact version, decision, and policy.'); state.synthesisStatus = payload.decision === 'verify' ? 'verified' : 'rejected'; state.synthesisRowVersion += 1; return send(res, 201, { id: ID.synthesisReview, synthesis_version_id: ID.synthesisVersion, decision: payload.decision, reviewer_id: ID.owner, reason: payload.reason, policy_version: payload.policy_version, reviewed_at: LATER, data_authenticity: 'collected' }); }
    if (req.method === 'POST' && path === `/investigations/${ID.investigation}/decision-brief`) { requireValue(payload.synthesis_version_id === ID.synthesisVersion, 'DecisionBrief must use exact verified synthesis.'); state.briefStatus = 'draft'; state.briefRowVersion = 1; state.briefVersion = 1; state.briefDocument = initialDocument(); state.investigationRowVersion = 4; return send(res, 201, brief()); }
    if (req.method === 'GET' && path === `/decision-briefs/${ID.brief}`) return send(res, 200, brief());
    if (req.method === 'PATCH' && path === `/decision-briefs/${ID.brief}`) {
      requireValue(payload.expected_row_version === state.briefRowVersion && Array.isArray(payload.block_document.blocks) && payload.block_document.blocks.length === 4 && payload.human_edit_digest === digest(payload.block_document), 'Brief PATCH requires full block_document, row_version, and matching digest.');
      if (state.briefVersion === 1) {
        const accepted = payload.block_document.blocks.find((block) => block.type === 'recommendation');
        requireValue(payload.block_document.no_counter_evidence_search === null && accepted?.recommendation_status === 'accepted', 'The first Brief PATCH must save the human judgment and accepted Recommendation without inventing a search record.');
      } else if (state.briefVersion === 2) {
        const record = payload.block_document.no_counter_evidence_search;
        const requiredKeys = 'exclusion_criteria,limitations,queries,source_connection_ids,window_end,window_start';
        const substantive = (items) => Array.isArray(items) && items.length > 0 && items.every((item) => typeof item === 'string' && item.trim() === item && item.length > 0);
        requireValue(record && Object.keys(record).sort().join(',') === requiredKeys && substantive(record.queries) && substantive(record.exclusion_criteria) && substantive(record.limitations), 'The second Brief PATCH must save a complete explicit no-counter search record with the exact wire keys.');
        requireValue(record.source_connection_ids.join(',') === scope().source_scope_json.source_connection_ids.join(',') && record.window_start === scope().time_range.start && record.window_end === scope().time_range.end, 'No-counter search scope and window must exactly match the current Investigation ScopeVersion.');
      } else requireValue(false, 'Only the two expected Brief PATCH operations are allowed.');
      state.briefDocument = payload.block_document; state.briefVersion += 1; state.briefRowVersion += 1; return send(res, 200, brief());
    }
    if (req.method === 'POST' && path === `/decision-briefs/${ID.brief}/mark-decision-ready`) { const current = brief(); const currentVersionId = current.current_version.id; const expectedRowVersion = state.briefRowVersion; const expected = digest({ decision_brief_version_id: currentVersionId, block_document: current.current_version.block_document, reference_snapshot: reference, policy_version: payload.policy_version }); requireValue(payload.decision_brief_version_id === currentVersionId && payload.expected_row_version === expectedRowVersion && payload.checklist_digest === expected, 'Readiness requires the exact current Brief version, row_version, and checklist_digest.'); state.briefStatus = 'decision_ready'; state.briefReadiness = 'decision_ready'; state.briefRowVersion += 1; return send(res, 201, { id: ID.readinessReview, decision_brief_version_id: currentVersionId, decision: 'mark_decision_ready', reviewer_id: ID.owner, reason: payload.reason, policy_version: payload.policy_version, checklist_digest: expected, reviewed_at: LATER, data_authenticity: 'collected' }); }
    if (req.method === 'POST' && path === `/decision-briefs/${ID.brief}/exports/preview`) { const currentVersionId = brief().current_version.id; requireValue(payload.decision_brief_version_id === currentVersionId && payload.export_type === 'prd_research_input_markdown' && payload.selection_manifest.block_ids.join(',') === 'fact-1,judgment-1,recommendation-1' && payload.export_timestamp === undefined, 'Export preview requires the exact current version, type, selected block_ids, and no client timestamp.'); return send(res, 200, { decision_brief_version_id: currentVersionId, export_type: 'prd_research_input_markdown', rendered_content: renderedExport(), reference_digest: exportReferenceDigest(), export_timestamp: EXPORT_TIMESTAMP, data_authenticity: 'collected' }); }
    if (req.method === 'POST' && path === `/decision-briefs/${ID.brief}/exports`) { const currentVersionId = brief().current_version.id; requireValue(payload.decision_brief_version_id === currentVersionId && payload.export_type === 'prd_research_input_markdown' && ['copy_markdown', 'local_download'].includes(payload.destination) && payload.reference_digest === exportReferenceDigest() && payload.export_timestamp === EXPORT_TIMESTAMP, 'BriefExport must echo the exact timestamp and digest from the exact-version preview.'); state.exportPostCount += 1; state.exportIdempotencyKeys.push(req.headers['idempotency-key']); state.exportTimestamps.push(payload.export_timestamp); if (state.exportPostCount === 1) return fail(res, 'Fixture audit transport failure after local output completed.', 503); requireValue(state.exportIdempotencyKeys[0] === state.exportIdempotencyKeys[1] && state.exportTimestamps[0] === state.exportTimestamps[1], 'Audit retry must reuse the exact same Idempotency-Key and preview timestamp.'); state.exportTerminalCount = 1; return send(res, 201, { id: ID.export, workspace_id: ID.workspace, decision_brief_version_id: currentVersionId, export_type: 'prd_research_input_markdown', destination: payload.destination, selection_manifest_json: payload.selection_manifest, reference_digest: exportReferenceDigest(), policy_version: 'export-policy-v1', template_version: 'prd-research-input-v1', output_digest: textDigest(renderedExport()), created_by: ID.owner, created_at: EXPORT_TIMESTAMP, data_authenticity: 'collected' }); }
    return fail(res, `Unhandled fixture route ${req.method} ${path}`, 404);
  } catch (error) { return fail(res, error instanceof Error ? error.message : 'Fixture validation failed.'); }
});

server.listen(PORT, '127.0.0.1', () => process.stdout.write(`Glint strict API fixture listening on ${PORT}\n`));
