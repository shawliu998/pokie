import { afterEach, describe, expect, it, vi } from 'vitest';
import { eligibleResearchSources, RestAdapter, type ImportProgress } from './api';
import type { PreparedCsvImport } from './imports';
import type { Signal, SourceHealth, WorkspaceState } from './domain';

const response = (body: unknown, headers?: HeadersInit) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json', ...Object.fromEntries(new Headers(headers)) } });
const session = (state: string, rowVersion: number, extras: Record<string, unknown> = {}) => ({ id: 'import-1', state, row_version: rowVersion, retryable: false, terminal_manifest_id: null, failure_code: null, data_authenticity: 'imported', ...extras });
const job = (commandId: string, state: string, attempt: number, extras: Record<string, unknown> = {}) => ({ id: commandId, command_id: commandId, import_session_id: 'import-1', state, attempt, result_manifest_id: null, failure_code: null, data_authenticity: 'imported', ...extras });

const source: SourceHealth = { id: 'source-1', workspaceId: 'workspace-1', name: 'Feedback CSV', sourceKind: 'imported_dataset', connectorType: 'csv', runtime: 'static_import', connectorVersion: 'csv-v1', sourceConfig: null, cadence: null, timezone: null, capabilities: [], rowVersion: 1, currentImportManifestId: null, status: 'healthy', health: { state: 'healthy', checkedAt: null, lastErrorCode: null }, freshness: { state: 'never', lastSuccessAt: null }, lastRunAt: null, authenticity: 'imported' };
const fileBytes = new TextEncoder().encode('id,text\r\n1,hello\r\n');
const prepared: PreparedCsvImport = { file: { name: 'feedback.csv', type: 'text/csv', size: fileBytes.byteLength } as File, fileName: 'feedback.csv', fileSizeBytes: fileBytes.byteLength, fileDigest: `sha256:${'a'.repeat(64)}`, localManifestDigest: `sha256:${'b'.repeat(64)}`, expectedUploadDigest: `sha256:${'a'.repeat(64)}`, selectedScope: { columns: ['id', 'text'] }, selectedScopeDigest: `sha256:${'c'.repeat(64)}`, parserVersion: 'csv-v1', schemaVersion: 'interview-import-v1', rowCount: 1 };

describe('RestAdapter import contract', () => {
  afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

  it('fails closed when the configured access token is empty', () => {
    expect(() => new RestAdapter('http://api.test', 'workspace-1', '   ')).toThrow(/access token/i);
  });

  it('invalidates the secure session on API 401 without persisting the credential', async () => {
    const invalidated = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { message: 'expired' } }), { status: 401, headers: { 'Content-Type': 'application/json' } })));
    await expect(new RestAdapter('http://api.test', 'workspace-1', 'opaque-token', invalidated).sourceHealth('source-1')).rejects.toThrow(/secure Glint session/i);
    expect(invalidated).toHaveBeenCalledOnce();
    expect(Object.values(localStorage)).not.toContain('opaque-token');
  });

  it('uses nested consent, X-Upload-Grant, scoped PUT, object_key, and terminal job polling', async () => {
    const objectKey = 'workspaces/workspace-1/imports/import-1/payload.csv';
    const previewScope = { destination_workspace_id: 'workspace-1', import_session_id: 'import-1', import_session_row_version: 1, source_connection_id: 'source-1', source_row_version: 1, current_import_manifest_id: null, local_manifest_digest: prepared.localManifestDigest, file_digest: prepared.fileDigest, expected_upload_digest: prepared.expectedUploadDigest, selected_scope_digest: prepared.selectedScopeDigest, upload_object_scope: { object_key: objectKey, max_bytes: prepared.fileSizeBytes, media_type: 'text/csv' }, policy_version: 'import-transfer-v1' };
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/imports') && init?.method === 'POST') return response(session('draft', 1));
      if (url.includes('/imports/import-1/upload-consent/preview?')) return response({ preview_scope: previewScope, scope_digest: `sha256:${'d'.repeat(64)}`, data_authenticity: 'imported' });
      if (url.endsWith('/imports/import-1/upload-consent')) {
        const requestBody = JSON.parse(String(init?.body));
        return response({ import_session: session('consented', 2), consent_record: { decision: 'grant', destination_workspace_id: 'workspace-1', selected_scope_digest: prepared.selectedScopeDigest, policy_version: 'import-transfer-v1', upload_object_scope: previewScope.upload_object_scope, model_egress_authorization: 'none', expires_at: requestBody.expires_at, data_authenticity: 'imported' }, upload: { object_key: objectKey, maximum_bytes: prepared.fileSizeBytes, media_type: 'text/csv', expires_at: requestBody.expires_at }, data_authenticity: 'imported' }, { 'X-Upload-Grant': 'grant-secret' });
      }
      if (url.endsWith('/imports/import-1/object')) return response({ object_key: objectKey, data_authenticity: 'imported' });
      if (url.endsWith('/imports/import-1/upload-complete')) return response(session('uploaded', 3));
      if (url.endsWith('/imports/import-1/finalize')) return response(job('job-1', 'completed', 1, { result_manifest_id: 'manifest-1' }));
      if (url.endsWith('/imports/import-1') && !init?.method) return response(session('finalized', 4, { terminal_manifest_id: 'manifest-1' }));
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const progress: ImportProgress[] = [];
    const result = await new RestAdapter('http://api.test', 'workspace-1', 'fixture-access-token').importCsv(prepared, source, (item) => progress.push(item));
    expect(result).toEqual({ sessionId: 'import-1', manifestId: 'manifest-1', jobId: 'job-1' });
    const put = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/imports/import-1/object'));
    expect(put?.[1]?.method).toBe('PUT');
    expect(new Headers(put?.[1]?.headers).get('X-Upload-Grant')).toBe('grant-secret');
    const complete = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/upload-complete'));
    expect(JSON.parse(String(complete?.[1]?.body))).toEqual({ expected_row_version: 2, object_key: objectKey });
    const consentPost = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/imports/import-1/upload-consent'));
    expect(JSON.parse(String(consentPost?.[1]?.body))).toMatchObject({ preview_scope: previewScope, scope_digest: `sha256:${'d'.repeat(64)}`, confirmation: true });
    expect(progress).toContainEqual(expect.objectContaining({ destinationWorkspaceId: 'workspace-1', objectKey, maximumBytes: prepared.fileSizeBytes }));
  });

  it('retries only a retryable failed session', async () => {
    let getCount = 0;
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/imports/import-1') && !init?.method) { getCount += 1; return response(getCount === 1 ? session('failed', 5, { retryable: true, failure_code: 'WORKER_TIMEOUT' }) : session('finalized', 7, { terminal_manifest_id: 'manifest-2' })); }
      if (url.endsWith('/imports/import-1/finalize')) return response(job('job-2', 'completed', 2, { result_manifest_id: 'manifest-2' }));
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const result = await new RestAdapter('http://api.test', 'workspace-1', 'fixture-access-token').retryImport('import-1', () => undefined);
    expect(result.manifestId).toBe('manifest-2');
    expect(JSON.parse(String(fetchMock.mock.calls.find(([url]) => String(url).endsWith('/finalize'))?.[1]?.body))).toEqual({ expected_row_version: 5 });
  });

  it('cancels a non-terminal import with its current row version', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/imports/import-1') && !init?.method) return response(session('uploaded', 4));
      if (url.endsWith('/imports/import-1/cancel') && init?.method === 'POST') return response(session('cancelled', 5));
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const progress: ImportProgress[] = [];
    await new RestAdapter('http://api.test', 'workspace-1', 'fixture-access-token').cancelImport('import-1', (item) => progress.push(item));
    const cancel = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/cancel'));
    expect(JSON.parse(String(cancel?.[1]?.body))).toEqual({ expected_row_version: 4, reason: 'Cancelled by Owner PM in Glint.' });
    expect(progress).toContainEqual(expect.objectContaining({ stage: 'cancelled', sessionId: 'import-1' }));
  });

  it('restores a persisted finalization job and resumes polling after reload', async () => {
    localStorage.setItem('glint:active-import:workspace-1', JSON.stringify({ importId: 'import-1', jobId: 'job-1' }));
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/imports')) return response({ items: [{ import_session: session('validating', 4), finalization_job: job('job-1', 'claimed', 1), data_authenticity: 'imported' }], next_cursor: null });
      if (url.endsWith('/import-finalization-jobs/job-1')) return response(job('job-1', 'completed', 1, { result_manifest_id: 'manifest-1' }));
      if (url.endsWith('/imports/import-1')) return response(session('finalized', 5, { terminal_manifest_id: 'manifest-1' }));
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const result = await new RestAdapter('http://api.test', 'workspace-1', 'access-token').recoverImport(() => undefined);
    expect(result).toEqual({ sessionId: 'import-1', manifestId: 'manifest-1', jobId: 'job-1' });
    expect(localStorage.getItem('glint:active-import:workspace-1')).toBeNull();
  });

  it('discovers a recent retryable import from the server recovery page without local state', async () => {
    localStorage.clear();
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      if (String(input).endsWith('/imports')) return response({ items: [{ import_session: session('failed', 6, { retryable: true, failure_code: 'WORKER_TIMEOUT' }), finalization_job: job('job-1', 'failed', 1, { failure_code: 'WORKER_TIMEOUT' }), data_authenticity: 'imported' }], page: { next_cursor: null, has_more: false } });
      throw new Error(`Unexpected request ${String(input)}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const progress: ImportProgress[] = [];
    await expect(new RestAdapter('http://api.test', 'workspace-1', 'access-token').recoverImport((item) => progress.push(item))).resolves.toBeNull();
    expect(progress).toContainEqual(expect.objectContaining({ stage: 'retryable_failure', sessionId: 'import-1', jobId: 'job-1', retryable: true }));
    expect(localStorage.getItem('glint:active-import:workspace-1')).toContain('import-1');
  });
});

describe('Signal-linked research source eligibility', () => {
  const signal = { perSourceFreshness: [{ sourceConnectionId: 'cloud-1', state: 'stale' as const, lastSuccessAt: '2026-07-15T05:00:00Z' }] } as Parameters<typeof eligibleResearchSources>[0];

  it('selects only successful Signal-linked cloud content and never falls back to unrelated imports', () => {
    const cloud = { ...source, id: 'cloud-1', sourceKind: 'cloud' as const, connectorType: 'github' as const, runtime: 'cloud' as const, status: 'degraded' as const, freshness: { state: 'stale' as const, lastSuccessAt: '2026-07-15T05:00:00Z' } };
    const unrelatedImport = { ...source, currentImportManifestId: 'manifest-1' };
    expect(eligibleResearchSources(signal, [unrelatedImport, cloud]).map((item) => item.id)).toEqual(['cloud-1']);
    expect(eligibleResearchSources({ ...signal, perSourceFreshness: [] }, [unrelatedImport])).toEqual([]);
  });

  it('rejects manual cadence instead of mapping it to a daily schedule', async () => {
    const adapter = new RestAdapter('http://api.test', 'workspace-1', 'access-token');
    const manualCloud = { ...source, id: 'cloud-1', sourceKind: 'cloud' as const, connectorType: 'github' as const, runtime: 'cloud' as const, status: 'healthy' as const, cadence: 'manual' as const, timezone: 'UTC', sourceConfig: { connectorType: 'github' as const, repositories: [{ owner: 'openai', repository: 'glint', includeIssues: true, includeDiscussions: true, includeReleases: true }] } };
    await expect(adapter.createSchedule(manualCloud, { id: 'watchlist-1', projectId: 'project-1', name: 'Watchlist', objective: 'Monitor signals.', status: 'active', sourceConnectionIds: ['cloud-1'], rules: { entities: ['product'], includeTerms: [], excludeTerms: [], languages: [], regions: [], cadence: 'daily', currentWindowDays: 7, baselineWindowDays: 28 }, initialBaseline: { status: 'ready', currentCount: 2, requiredCount: 2, candidateCount: 2, expectedDetectableAt: null, reason: null, lastTerminalRunAt: '2026-07-15T05:00:00Z' }, rowVersion: 1 }, 'query')).rejects.toThrow(/manual cadence/i);
  });

  it('starts a reused Investigation from its authoritative pinned scope', async () => {
    const adapter = new RestAdapter('http://api.test', 'workspace-1', 'access-token');
    const signal = {
      id: 'signal-1',
      perSourceFreshness: [{ sourceConnectionId: 'source-current', state: 'current', lastSuccessAt: '2026-07-15T05:00:00Z' }],
      window: { currentStart: '2026-07-01T00:00:00Z', currentEnd: '2026-07-15T00:00:00Z' },
    } as unknown as Signal;
    const currentSource = { ...source, id: 'source-current', currentImportManifestId: 'manifest-current' };
    (adapter as unknown as { latestWorkspace: WorkspaceState }).latestWorkspace = { signals: [signal], sources: [currentSource] } as WorkspaceState;
    const investigationDto = { id: 'investigation-1', signal_id: signal.id, decision_question: 'Pinned decision question', status: 'draft', current_scope_version_id: 'scope-1', row_version: 3, data_authenticity: 'imported' };
    const scopeDto = { id: 'scope-1', source_scope_json: { source_connection_ids: ['source-pinned'], content_version_ids: ['content-pinned'], allow_cloud_model: false }, time_range: { start: '2026-06-01T00:00:00Z', end: '2026-06-30T00:00:00Z' } };
    let runBody: Record<string, unknown> | null = null;
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/investigations') && init?.method === 'POST') return response(investigationDto);
      if (url.endsWith('/investigations/investigation-1')) return response(investigationDto);
      if (url.endsWith('/research-runs') && init?.method === 'POST') { runBody = JSON.parse(String(init.body)); return response({}); }
      if (url.endsWith('/research-runs')) return response({ items: [], page: { next_cursor: null, has_more: false } });
      if (url.includes('/claims?investigation_id=')) return response({ items: [], page: { next_cursor: null, has_more: false } });
      if (url.endsWith('/investigations/investigation-1/synthesis')) return new Response(JSON.stringify({ error: { message: 'not found' } }), { status: 404, headers: { 'Content-Type': 'application/json' } });
      if (url.endsWith('/investigations/investigation-1/scope-versions')) return response({ items: [scopeDto], page: { next_cursor: null, has_more: false } });
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    await adapter.createInvestigation(signal.id, 'A newer UI question');

    expect(runBody).toMatchObject({
      investigation_id: 'investigation-1',
      investigation_scope_version_id: 'scope-1',
      question: 'Pinned decision question',
      source_scope: scopeDto.source_scope_json,
      time_range: scopeDto.time_range,
      expected_investigation_row_version: 3,
    });
  });
});

describe('Source Viewer exact projection', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses one exact ContentVersion request and never scans ContentItems', async () => {
    const quote = 'Exact immutable quote.';
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      expect(String(input)).toBe('http://api.test/v1/content-versions/content-version-1');
      return response({ id: 'content-version-1', workspace_id: 'workspace-1', content_item_id: 'content-item-1', source_connection_id: 'source-1', source_name: 'Glint GitHub', source_kind: 'cloud', source_item_id: 'issue-1', identity_key: 'github:issue-1', title: 'Exact source', canonical_url: 'https://example.com/issue-1', duplicate_cluster_id: null, independence_group_id: 'group-1', version_number: 1, content_digest: `sha256:${'a'.repeat(64)}`, normalized_title: 'Exact source', normalized_body: `${quote} More context.`, metadata_json: { author: 'owner' }, published_at: '2026-07-15T04:00:00Z', captured_at: '2026-07-15T05:00:00Z', parser_version: 'github-v1', availability: 'captured', availability_last_checked_at: '2026-07-15T05:00:00Z', availability_reason: null, data_scope: 'public', data_authenticity: 'collected', created_at: '2026-07-15T05:00:00Z' });
    });
    vi.stubGlobal('fetch', fetchMock);
    const evidence = { id: 'evidence-1', investigationId: 'investigation-1', researchRunId: 'run-1', stance: 'supports', quote, quoteStart: 0, quoteEnd: quote.length, contentVersionId: 'content-version-1', status: 'proposed', provenance: { researchRunId: 'run-1', extractionMethod: 'deterministic' }, latestReviewId: null, authenticity: 'collected' } as const;
    const viewer = await new RestAdapter('http://api.test', 'workspace-1', 'access-token').sourceViewer('signal-1', evidence);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(viewer).toMatchObject({ highlightedQuote: quote, author: 'owner', independenceGroupId: 'group-1', source: { id: 'source-1', name: 'Glint GitHub', kind: 'cloud' } });
  });
});

describe('Decision Brief no-counter search contract', () => {
  afterEach(() => vi.unstubAllGlobals());

  const initialDocument = { schema_version: 'decision-brief-blocks-v1', blocks: [{ id: 'fact-1', type: 'fact', body: 'Pinned fact.', claim_version_ids: ['claim-version-1'], evidence_ids: ['evidence-1'], content_version_ids: ['content-version-1'] }, { id: 'judgment-1', type: 'pm_judgment', body: 'Proceed carefully.', actor_id: 'owner-1' }, { id: 'recommendation-1', type: 'recommendation', body: 'Validate first.', recommendation_status: 'accepted' }], no_counter_evidence_search: null };
  const referenceSnapshot = { synthesis_version_id: 'synthesis-version-1', synthesis_review_id: 'synthesis-review-1', claim_version_ids: ['claim-version-1'], claim_review_ids: ['claim-review-1'], claim_evidence_ids: ['claim-evidence-1'], evidence_review_ids: ['evidence-review-1'], evidence_ids: ['evidence-1'], content_version_ids: ['content-version-1'] };
  const briefDto = (blockDocument: unknown = initialDocument, rowVersion = 7, versionNumber = 2) => ({ id: 'brief-1', workspace_id: 'workspace-1', investigation_id: 'investigation-1', current_version: { id: `brief-version-${versionNumber}`, version_number: versionNumber, block_document: blockDocument, reference_snapshot_json: referenceSnapshot, template_version: 'decision-brief-v1', human_edit_digest: `sha256:${'a'.repeat(64)}`, readiness: 'draft', freshness: 'current' }, status: 'draft', row_version: rowVersion, data_authenticity: 'collected' });

  it('pins exact current ScopeVersion sources/time range and sends a full document with matching digest', async () => {
    const scope = { id: 'scope-version-2', source_scope_json: { source_connection_ids: ['source-2', 'source-1'], content_version_ids: ['content-version-1'], allow_cloud_model: false }, time_range: { start: '2026-07-01T00:00:00Z', end: '2026-07-15T00:00:00Z' } };
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/decision-briefs/brief-1') && !init?.method) return response(briefDto());
      if (url.endsWith('/investigations/investigation-1')) return response({ id: 'investigation-1', signal_id: 'signal-1', decision_question: 'Should we proceed?', status: 'reviewing', current_scope_version_id: 'scope-version-2', row_version: 4, data_authenticity: 'collected' });
      if (url.endsWith('/research-runs')) return response({ items: [], page: { next_cursor: null, has_more: false } });
      if (url.includes('/claims?investigation_id=')) return response({ items: [], page: { next_cursor: null, has_more: false } });
      if (url.endsWith('/investigations/investigation-1/synthesis')) return new Response(JSON.stringify({ error: { message: 'not found' } }), { status: 404, headers: { 'Content-Type': 'application/json' } });
      if (url.endsWith('/investigations/investigation-1/scope-versions')) return response({ items: [scope], page: { next_cursor: null, has_more: false } });
      if (url.endsWith('/decision-briefs/brief-1') && init?.method === 'PATCH') {
        const requestBody = JSON.parse(String(init.body));
        return response(briefDto(requestBody.block_document, 8, 3));
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const saved = await new RestAdapter('http://api.test', 'workspace-1', 'access-token').saveNoCounterEvidenceSearch('brief-1', { queries: ['  permission objection  '], exclusionCriteria: ['  Duplicate captures  '], limitations: ['  Pinned sources only  '] });
    expect(saved.blockDocument.noCounterEvidenceSearch).toEqual({ queries: ['permission objection'], sourceConnectionIds: ['source-2', 'source-1'], windowStart: scope.time_range.start, windowEnd: scope.time_range.end, exclusionCriteria: ['Duplicate captures'], limitations: ['Pinned sources only'] });
    const patchCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/decision-briefs/brief-1') && init?.method === 'PATCH');
    const patchBody = JSON.parse(String(patchCall?.[1]?.body));
    expect(Object.keys(patchBody).sort()).toEqual(['block_document', 'expected_row_version', 'human_edit_digest']);
    expect(patchBody.expected_row_version).toBe(7);
    expect(Object.keys(patchBody.block_document.no_counter_evidence_search).sort()).toEqual(['exclusion_criteria', 'limitations', 'queries', 'source_connection_ids', 'window_end', 'window_start']);
    expect(patchBody.block_document.no_counter_evidence_search).toEqual({ queries: ['permission objection'], source_connection_ids: ['source-2', 'source-1'], window_start: scope.time_range.start, window_end: scope.time_range.end, exclusion_criteria: ['Duplicate captures'], limitations: ['Pinned sources only'] });
    const normalize = (value: unknown): unknown => Array.isArray(value) ? value.map(normalize) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right)).map(([key, child]) => [key, normalize(child)])) : value;
    const digestBytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(normalize(patchBody.block_document))));
    expect(patchBody.human_edit_digest).toBe(`sha256:${[...new Uint8Array(digestBytes)].map((item) => item.toString(16).padStart(2, '0')).join('')}`);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/signals/'))).toBe(false);
  });

  it('rejects every empty user-authored search list before any request', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new RestAdapter('http://api.test', 'workspace-1', 'access-token');
    const complete = { queries: ['query'], exclusionCriteria: ['exclusion'], limitations: ['limitation'] };
    for (const key of ['queries', 'exclusionCriteria', 'limitations'] as const) await expect(adapter.saveNoCounterEvidenceSearch('brief-1', { ...complete, [key]: ['   '] })).rejects.toThrow(/non-empty entry/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('SourceValidationJob source-version fencing', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('accepts the enqueue-incremented version and pins it through polling to the terminal source', async () => {
    const cloudSource: SourceHealth = { ...source, id: 'cloud-1', name: 'Cloud source', sourceKind: 'cloud', connectorType: 'github', runtime: 'cloud', sourceConfig: { connectorType: 'github', repositories: [{ owner: 'openai', repository: 'glint', includeIssues: true, includeDiscussions: true, includeReleases: true }] }, cadence: 'daily', timezone: 'UTC', capabilities: ['health'], rowVersion: 4, status: 'healthy', authenticity: 'collected' };
    const sourceDto = (rowVersion: number) => ({ id: 'cloud-1', workspace_id: 'workspace-1', name: 'Cloud source', source_kind: 'cloud', runtime: 'cloud', connector_type: 'github', connector_version: 'github-v1', status: 'healthy', source_config: { connector_type: 'github', repositories: [{ owner: 'openai', repository: 'glint', include_issues: true, include_discussions: true, include_releases: true }] }, cadence: 'daily', timezone: 'UTC', last_run_at: null, last_success_at: '2026-07-15T05:00:00Z', health: { state: 'healthy', checked_at: '2026-07-15T05:01:00Z', last_error_code: null }, freshness: { state: 'current', last_success_at: '2026-07-15T05:00:00Z' }, capabilities: ['health'], current_import_manifest: null, row_version: rowVersion, data_authenticity: 'collected' });
    const jobDto = (state: 'queued' | 'completed') => ({ id: 'job-1', source_connection_id: 'cloud-1', command: 'health_check', state, expected_source_row_version: 5, result_source_status: state === 'completed' ? 'healthy' : null, failure_code: null, failure_reason: null, data_authenticity: 'collected' });
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/sources/cloud-1/health-check')) {
        expect(JSON.parse(String(init?.body))).toMatchObject({ expected_row_version: 4 });
        return response(jobDto('queued'));
      }
      if (url.endsWith('/source-validation-jobs/job-1')) return response(jobDto('completed'));
      if (url.endsWith('/sources/cloud-1')) return response(sourceDto(6));
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    await expect(new RestAdapter('http://api.test', 'workspace-1', 'access-token').validateSource(cloudSource)).resolves.toMatchObject({ id: 'cloud-1', rowVersion: 6, status: 'healthy' });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('source-validation-jobs'))).toHaveLength(1);
  });
});

describe('BriefExport audit idempotency', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends the caller-owned idempotency key unchanged on an audit retry', async () => {
    const briefDto = { id: 'brief-1', workspace_id: 'workspace-1', investigation_id: 'investigation-1', current_version: { id: 'brief-version-1', decision_brief_id: 'brief-1', investigation_id: 'investigation-1', version_number: 1, synthesis_version_id: 'synthesis-version-1', synthesis_review_id: 'synthesis-review-1', block_document: { schema_version: 'decision-brief-blocks-v1', blocks: [{ id: 'fact-1', type: 'fact', body: 'Fact.', claim_version_ids: ['claim-version-1'], evidence_ids: ['evidence-1'], content_version_ids: ['content-version-1'] }, { id: 'judgment-1', type: 'pm_judgment', body: 'Proceed.', actor_id: 'owner-1' }, { id: 'recommendation-1', type: 'recommendation', body: 'Ship safely.', recommendation_status: 'accepted' }], no_counter_evidence_search: null }, reference_snapshot_json: { synthesis_version_id: 'synthesis-version-1', synthesis_review_id: 'synthesis-review-1', claim_version_ids: ['claim-version-1'], claim_review_ids: ['claim-review-1'], claim_evidence_ids: ['claim-evidence-1'], evidence_review_ids: ['evidence-review-1'], evidence_ids: ['evidence-1'], content_version_ids: ['content-version-1'] }, template_version: 'brief-v1', human_edit_digest: `sha256:${'a'.repeat(64)}`, readiness: 'decision_ready', freshness: 'current', created_by: 'owner-1', created_at: '2026-07-15T05:00:00Z', data_authenticity: 'collected' }, status: 'decision_ready', owner_id: 'owner-1', decision_outcome: null, next_checkpoint_at: null, row_version: 2, data_authenticity: 'collected', created_at: '2026-07-15T05:00:00Z', updated_at: '2026-07-15T05:00:00Z' };
    let auditAttempts = 0;
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/decision-briefs/brief-1') && !init?.method) return response(briefDto);
      if (url.endsWith('/decision-briefs/brief-1/exports')) {
        auditAttempts += 1;
        if (auditAttempts === 1) return new Response(JSON.stringify({ error: { message: 'audit unavailable' } }), { status: 503, headers: { 'Content-Type': 'application/json' } });
        return response({ id: 'export-1', decision_brief_version_id: 'brief-version-1', export_type: 'prd_research_input_markdown', destination: 'copy_markdown', output_digest: 'sha256:0063ca4546ac82e2b33f97ae38ee5197a9bfda52149f10129c1cf735e71d63d2', created_at: '2026-07-15T05:01:00Z', data_authenticity: 'collected' });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new RestAdapter('http://api.test', 'workspace-1', 'access-token');
    const preview = { renderedContent: '# PRD', referenceDigest: `sha256:${'c'.repeat(64)}`, exportType: 'prd_research_input_markdown' as const, selectionManifest: { block_ids: ['fact-1'], include_citations: true }, authenticity: 'collected' as const };
    await expect(adapter.executeExport('brief-1', preview, 'copy_markdown', 'stable-export-key')).rejects.toThrow('audit unavailable');
    await expect(adapter.executeExport('brief-1', preview, 'copy_markdown', 'stable-export-key')).resolves.toMatchObject({ id: 'export-1', authenticity: 'collected' });
    const exportCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/exports'));
    expect(exportCalls).toHaveLength(2);
    expect(exportCalls.map((call) => new Headers(call[1]?.headers).get('Idempotency-Key'))).toEqual(['stable-export-key', 'stable-export-key']);
  });
});

describe('clean workspace Imported Dataset setup', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('creates project, CSV source, active source, Watchlist, and active Watchlist through exact routes', async () => {
    const sourceDto = (status: 'draft' | 'healthy', rowVersion: number) => ({ id: 'source-1', workspace_id: 'workspace-1', name: 'Imported CSV dataset', source_kind: 'imported_dataset', runtime: 'static_import', connector_type: 'csv', connector_version: 'csv-v1', status, source_config: null, cadence: null, timezone: null, last_run_at: null, last_success_at: null, health: { state: 'unknown', checked_at: null, last_error_code: null }, freshness: { state: 'never', last_success_at: null }, capabilities: [], data_scope: 'workspace_confidential', current_import_manifest: null, row_version: rowVersion, data_authenticity: 'imported', created_at: '2026-07-15T05:00:00Z', updated_at: '2026-07-15T05:00:00Z' });
    const watchlistDto = (status: 'draft' | 'active', rowVersion: number) => ({ id: 'watchlist-1', workspace_id: 'workspace-1', project_id: 'project-1', name: 'Imported feedback', objective: 'Monitor imported product feedback for decision-relevant changes.', status, rules_version: 1, owner_id: 'owner-1', source_connection_ids: ['source-1'], rules: { schema_version: 'watchlist-rules-v1', entities: ['product feedback'], query_rules: { include_terms: ['feedback'], exclude_terms: [], languages: [], regions: [] }, cadence: 'manual', current_window_days: 30, baseline_window_days: 90, notification_intent: false }, initial_baseline: { status: 'collecting', current_count: 0, required_count: 2, candidate_count: 0, expected_detectable_at: null, reason: 'No terminal import exists yet.', last_terminal_run_at: null }, row_version: rowVersion, data_authenticity: 'human_authored', created_at: '2026-07-15T05:00:00Z', updated_at: '2026-07-15T05:00:00Z' });
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/projects')) return response({ id: 'project-1' });
      if (url.endsWith('/sources') && init?.method === 'POST') return response(sourceDto('draft', 1));
      if (url.endsWith('/sources/source-1/activate')) return response(sourceDto('healthy', 2));
      if (url.endsWith('/watchlists') && init?.method === 'POST') return response(watchlistDto('draft', 1));
      if (url.endsWith('/watchlists/watchlist-1/activate')) return response(watchlistDto('active', 2));
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    await new RestAdapter('http://api.test', 'workspace-1', 'access-token').setupImportedDataset();
    const sourceCreate = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/sources') && !String(url).endsWith('/source-1/activate'));
    expect(JSON.parse(String(sourceCreate?.[1]?.body))).toMatchObject({ source_kind: 'imported_dataset', runtime: 'static_import', connector_type: 'csv', data_scope: 'workspace_confidential' });
    const watchlistCreate = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/watchlists'));
    expect(JSON.parse(String(watchlistCreate?.[1]?.body))).toMatchObject({ project_id: 'project-1', source_connection_ids: ['source-1'], rules: { cadence: 'manual' } });
  });
});
