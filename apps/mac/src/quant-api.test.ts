import { describe, expect, it, vi } from 'vitest';
import type { GlintApi } from './api';
import { createApiQuantApi, createFixtureQuantApi, parseQuantMarketDataConnector, parseQuantStrategyReportExport, quantIdempotencyKey, QUANT_WORKSPACE_REQUEST_TIMEOUT_MS } from './quant-api';
import { quantFixtureSnapshot } from './features/quant/quant-fixtures';
import { QuantWorkspaceCompatibilityError } from './quant-workspace-parser';

describe('Quant fixture API adapter', () => {
  it('keeps Paper requests on their independent transport and maps account state', async () => {
    const now = '2026-07-25T08:00:00Z';
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const snapshot = {
      contract_version: 'qurio-paper-v1',
      environment: 'paper',
      account: {
        account_id: '00000000-0000-4000-8000-000000000901',
        workspace_id: '00000000-0000-4000-8000-000000000902',
        environment: 'paper',
        broker: 'local_simulator',
        currency: 'USD',
        status: 'active',
        cash: '100000.00',
        buying_power: '100000.00',
        equity: '100000.00',
        row_version: 1,
        last_reconciled_at: null,
        updated_at: now,
      },
      positions: [],
      orders: [],
      fills: [],
      legal_actions: ['create_draft', 'submit', 'cancel', 'reconcile'],
      generated_at: now,
    };
    const glint = {
      async quantRequest() { return quantFixtureSnapshot; },
      async paperRequest(path: string, init?: RequestInit) {
        calls.push({ path, init });
        return snapshot;
      },
    } as unknown as GlintApi;
    const paper = await createApiQuantApi(glint).getPaperSnapshot();
    expect(paper).toMatchObject({
      contractVersion: 'qurio-paper-v1',
      environment: 'paper',
      account: { broker: 'local_simulator', cash: '100000.00', rowVersion: 1 },
    });
    expect(calls).toEqual([{ path: '/paper/snapshot', init: undefined }]);
  });

  it('rejects commands absent from the completed snapshot without mutating run state', async () => {
    const api = createFixtureQuantApi();
    const before = (await api.getWorkspaceSnapshot()).run.state;
    const unsupported = await api.sendCommand({ command: 'start_new_run', expectedVersion: 12, idempotencyKey: 'test-unsupported' });
    const illegal = await api.sendCommand({ command: 'retry_run', expectedVersion: 12, idempotencyKey: 'test-illegal' });
    expect(unsupported.status).toBe('rejected');
    expect(illegal.status).toBe('rejected');
    expect((await api.getWorkspaceSnapshot()).run.state).toBe(before);
  });

  it('maps immutable dataset DTOs and posts CSV text with an idempotency key', async () => {
    const importKey = '77777777-7777-4777-8777-777777777777';
    const dto = {
      dataset_id: 'ohlcv-ACME-1234',
      workspace_id: 'workspace-1',
      name: 'ACME daily',
      symbol: 'ACME',
      interval: '1D',
      covered_start: '2023-01-01',
      covered_end: '2023-12-31',
      bar_count: 300,
      schema_version: 'quant-daily-bars-v1',
      parser_version: 'quant-ohlcv-csv-v1',
      digest: `sha256:${'a'.repeat(64)}`,
      source_metadata: {
        kind: 'csv_upload',
        file_name: 'acme.csv',
        source_name: 'Example Exchange',
        source_reference: 'export:123',
        submitted_csv_digest: `sha256:${'b'.repeat(64)}`,
        market_calendar: 'XNYS',
        time_zone: 'America/New_York',
        price_adjustment: 'split_adjusted',
      },
      data_quality: {
        schema_version: 'quant-data-quality-v1',
        policy_version: 'ohlcv-quality-v1',
        status: 'warning',
        verification_status: 'checked',
        report_digest: `sha256:${'c'.repeat(64)}`,
        dataset_digest: `sha256:${'a'.repeat(64)}`,
        bar_count: 300,
        calendar_gap_count: 2,
        largest_calendar_gap_days: 3,
        unexpected_session_count: 0,
        zero_volume_bar_count: 1,
        price_jump_count: 4,
        issues: [{ code: 'calendar_gap', severity: 'warning', message: 'Calendar gaps are not exchange-calendar verification.', count: 2 }],
        notes: ['Input checks do not establish market-data authenticity.'],
      },
      data_authenticity: 'imported',
      created_at: '2026-07-17T00:00:00Z',
    } as const;
    const providerDto = {
      ...dto,
      dataset_id: 'provider-BTCUSDT-1234',
      name: 'BTCUSDT Binance Spot daily',
      symbol: 'BTCUSDT',
      source_metadata: {
        kind: 'provider_fetch',
        source_name: 'Binance Spot public market data',
        source_reference: 'binance-vision:/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=365',
        submitted_csv_digest: `sha256:${'e'.repeat(64)}`,
        market_calendar: '24x7',
        time_zone: 'UTC',
        price_adjustment: 'unadjusted',
        provider_id: 'binance_spot',
        provider_response_digest: `sha256:${'d'.repeat(64)}`,
        retrieved_at: '2026-07-18T00:00:00Z',
        requested_limit: 365,
        returned_bar_count: 364,
        dropped_incomplete_count: 1,
        normalization_note: 'Dropped the incomplete current daily candle.',
        attestation_status: 'provider_retrieved',
      },
    } as const;
    const nasdaqDto = {
      ...dto,
      dataset_id: 'provider-AAPL-1234',
      name: 'AAPL Nasdaq Equity daily',
      symbol: 'AAPL',
      source_metadata: {
        kind: 'provider_fetch',
        source_name: 'Nasdaq Equity provider data',
        source_reference: 'nasdaq-equity:AAPL',
        market_calendar: 'XNAS',
        time_zone: 'America/New_York',
        price_adjustment: 'unadjusted',
        provider_id: 'nasdaq_equity',
        retrieved_at: '2026-07-18T00:00:00Z',
        requested_limit: 5000,
        returned_bar_count: 502,
        dropped_incomplete_count: 0,
        normalization_note: 'Normalized provider sessions to daily bars.',
        attestation_status: 'provider_retrieved',
        price_adjustment_verification_status: 'not_applicable',
        provider_response_attestations: [
          { kind: 'daily_bars', digest: `sha256:${'f'.repeat(64)}`, source_reference: 'nasdaq:AAPL:historical' },
          { kind: 'instrument_info', digest: `sha256:${'e'.repeat(64)}`, source_reference: 'nasdaq:AAPL:info' },
          { kind: 'dividends', digest: `sha256:${'g'.repeat(64)}`, source_reference: 'nasdaq:AAPL:dividends' },
        ],
        corporate_actions_attestation: {
          dividends_status: 'retrieved_unverified',
          splits_status: 'unavailable',
          coverage_start: '2024-07-18',
          coverage_end: '2026-07-18',
          dividend_coverage_start: '2024-07-18',
          dividend_coverage_end: '2026-07-18',
          split_coverage_start: '2026-01-01',
          split_coverage_end: '2026-07-18',
          split_snapshot_as_of: '2026-07-18',
          split_completeness_status: 'current_snapshot_only',
          split_reconciliation_status: 'not_reconciled',
          split_events: [{ effective_date: '2026-06-15', ratio_numerator: 2, ratio_denominator: 1 }],
          dividend_event_count: 82,
          split_event_count: null,
          note: 'Dividend coverage is retained; split coverage was unavailable.',
        },
      },
    } as const;
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest(path: string, init?: RequestInit) {
        calls.push({ path, init });
        if (path.endsWith('/import-csv')) return dto;
        if (path.endsWith('/fetch-binance-spot')) return providerDto;
        if (path.endsWith('/fetch-nasdaq-equity')) return nasdaqDto;
        return [dto];
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);

    const listed = await api.listDatasets();
    const imported = await api.importDatasetCsv({
      name: 'ACME daily',
      symbol: 'ACME',
      csvText: 'date,open,high,low,close\n2023-01-01,1,2,1,2\n',
      fileName: 'acme.csv',
      sourceName: 'Example Exchange',
      sourceReference: 'export:123',
      marketCalendar: 'XNYS',
      timeZone: 'America/New_York',
      priceAdjustment: 'split_adjusted',
      idempotencyKey: importKey,
    });

    expect(listed[0]).toMatchObject({ id: dto.dataset_id, symbol: 'ACME', barCount: 300, authenticity: 'imported', source: { sourceName: 'Example Exchange', fileName: 'acme.csv', priceAdjustment: 'split_adjusted' }, quality: { schemaVersion: 'quant-data-quality-v1', policyVersion: 'ohlcv-quality-v1', status: 'warning', verificationStatus: 'checked', calendarGapCount: 2, largestCalendarGapDays: 3, zeroVolumeBarCount: 1, priceJumpCount: 4 } });
    expect(imported.id).toBe(dto.dataset_id);
    expect(calls[0]).toEqual({ path: '/quant/datasets', init: undefined });
    expect(calls[1]?.path).toBe('/quant/datasets/import-csv');
    expect(calls[1]?.init?.method).toBe('POST');
    expect(new Headers(calls[1]?.init?.headers).get('Idempotency-Key')).toBe(importKey);
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      name: 'ACME daily',
      symbol: 'ACME',
      csv_text: 'date,open,high,low,close\n2023-01-01,1,2,1,2\n',
      file_name: 'acme.csv',
      source_name: 'Example Exchange',
      source_reference: 'export:123',
      market_calendar: 'XNYS',
      time_zone: 'America/New_York',
      price_adjustment: 'split_adjusted',
    });

    const fetched = await api.fetchBinanceSpotDataset({ idempotencyKey: importKey });
    expect(fetched).toMatchObject({ id: providerDto.dataset_id, source: { kind: 'provider_fetch', marketCalendar: '24x7', timeZone: 'UTC', providerId: 'binance_spot', requestedLimit: 365, returnedBarCount: 364, droppedIncompleteCount: 1, attestationStatus: 'provider_retrieved' } });
    expect(calls[2]?.path).toBe('/quant/datasets/fetch-binance-spot');
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({ symbol: 'BTCUSDT', interval: '1d', limit: 365 });

    const nasdaq = await api.fetchNasdaqEquityDataset({ idempotencyKey: importKey });
    expect(nasdaq).toMatchObject({ id: nasdaqDto.dataset_id, source: { kind: 'provider_fetch', providerId: 'nasdaq_equity', marketCalendar: 'XNAS', timeZone: 'America/New_York', priceAdjustment: 'unadjusted', priceAdjustmentVerificationStatus: 'not_applicable', providerResponseAttestations: [{ kind: 'daily_bars' }, { kind: 'instrument_info' }, { kind: 'dividends' }], corporateActionsAttestation: { dividendsStatus: 'retrieved_unverified', splitsStatus: 'unavailable', dividendCoverageStart: '2024-07-18', splitCoverageStart: '2026-01-01', splitSnapshotAsOf: '2026-07-18', splitCompletenessStatus: 'current_snapshot_only', splitReconciliationStatus: 'not_reconciled', splitEvents: [{ effectiveDate: '2026-06-15', ratioNumerator: 2, ratioDenominator: 1 }], dividendEventCount: 82, splitEventCount: null } } });
    expect(calls[3]?.path).toBe('/quant/datasets/fetch-nasdaq-equity');
    expect(JSON.parse(String(calls[3]?.init?.body))).toEqual({ symbol: 'AAPL', lookback_days: 730 });
  });

  it('posts dedicated market-v2 CSV and Binance Add Data requests with explicit intervals', async () => {
    const importKey = '88888888-8888-4888-8888-888888888888';
    const sha = (value: string) => `sha256:${value.repeat(64)}`;
    const marketCsvDto = {
      schema_version: 'quant-market-bars-v2',
      dataset_id: 'market-csv-btcusdt-4h',
      workspace_id: 'workspace-1',
      name: 'BTCUSDT CSV 4 hour',
      symbol: 'BTCUSDT',
      interval: '4h',
      covered_start: '2024-01-01T00:00:00+00:00',
      covered_end: '2025-12-31T20:00:00+00:00',
      bar_count: 4386,
      market_calendar: '24x7',
      market_session: 'continuous',
      time_zone: 'UTC',
      periods_per_year: 2190,
      digest: sha('a'),
      record_digest: sha('b'),
      evidence: {
        source_kind: 'csv_upload',
        file_name: 'btcusdt-4h.csv',
        source_name: 'Research CSV',
        source_reference: 'upload:btc-4h',
        normalizer_version: 'quant-market-csv-v1',
        submitted_csv_digest: sha('c'),
      },
      quality: { status: 'accepted', cadence_gap_count: 0, normalization_note: 'Contiguous 4h UTC bars.' },
      research_eligible: true,
      data_authenticity: 'imported',
      created_at: '2026-07-22T00:00:00+00:00',
    } as const;
    const marketBinanceDto = {
      ...marketCsvDto,
      dataset_id: 'market-binance-btcusdt-1h',
      name: 'BTCUSDT Binance Spot 1 hour',
      interval: '1h',
      covered_end: '2024-07-27T07:00:00+00:00',
      bar_count: 5000,
      periods_per_year: 8760,
      digest: sha('d'),
      record_digest: sha('e'),
      evidence: {
        source_kind: 'provider_fetch',
        file_name: null,
        source_name: 'Binance Spot deterministic API fixture',
        source_reference: 'fixture://binance/BTCUSDT/1h/5000',
        normalizer_version: 'binance-market-bars-v2',
        retrieved_at_utc: '2026-07-22T00:00:00+00:00',
        requested_bar_count: 5000,
        returned_bar_count: 5000,
        retained_bar_count: 5000,
        closed_dropped_count: 0,
        deduplicated_count: 0,
        page_raw_sha256: [sha('9')],
        batch_digest: sha('f'),
        termination_reason: 'requested_limit',
        target_satisfied: true,
      },
      data_authenticity: 'synthetic_fixture',
      created_at: '2026-07-22T00:05:00+00:00',
    } as const;
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest(path: string, init?: RequestInit) {
        calls.push({ path, init });
        if (path === '/quant/datasets/v2/import-csv') return marketCsvDto;
        if (path === '/quant/datasets/v2/fetch-binance') return marketBinanceDto;
        throw new Error(`Unexpected path ${path}`);
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);

    const imported = await api.importMarketDatasetCsv({
      name: 'BTCUSDT CSV 4 hour',
      symbol: 'BTCUSDT',
      interval: '4h',
      csvText: 'timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1,1,1,1,1\n',
      fileName: 'btcusdt-4h.csv',
      sourceName: 'Research CSV',
      sourceReference: 'upload:btc-4h',
      idempotencyKey: importKey,
    });
    const fetched = await api.fetchMarketBinanceDataset({
      name: 'BTCUSDT Binance Spot 1 hour',
      symbol: 'btcusdt',
      interval: '1h',
      limit: 5000,
      idempotencyKey: importKey,
    });

    expect(imported).toMatchObject({ contract: 'market-v2', interval: '4h', periodsPerYear: 2190, source: { kind: 'csv_upload', fileName: 'btcusdt-4h.csv', sourceName: 'Research CSV', sourceReference: 'upload:btc-4h' } });
    expect(fetched).toMatchObject({ contract: 'market-v2', interval: '1h', periodsPerYear: 8760, source: { kind: 'provider_fetch', sourceName: 'Binance Spot deterministic API fixture', sourceReference: 'fixture://binance/BTCUSDT/1h/5000', requestedBarCount: 5000, returnedBarCount: 5000, retainedBarCount: 5000 } });
    expect(calls.map((call) => call.path)).toEqual(['/quant/datasets/v2/import-csv', '/quant/datasets/v2/fetch-binance']);
    expect(new Headers(calls[0]?.init?.headers).get('Idempotency-Key')).toBe(importKey);
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      name: 'BTCUSDT CSV 4 hour',
      symbol: 'BTCUSDT',
      interval: '4h',
      csv_text: 'timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1,1,1,1,1\n',
      file_name: 'btcusdt-4h.csv',
      source_name: 'Research CSV',
      source_reference: 'upload:btc-4h',
    });
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      name: 'BTCUSDT Binance Spot 1 hour',
      symbol: 'BTCUSDT',
      interval: '1h',
      limit: 5000,
    });
  });

  it('generates API-compatible UUID idempotency keys', () => {
    expect(quantIdempotencyKey()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  });

  it('loads and parses a bounded dataset preview independently from the run snapshot', async () => {
    const calls: string[] = [];
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest<T = unknown>(path: string) {
        calls.push(path);
        return { dataset_id: 'dataset-btc', symbol: 'BTCUSDT', interval: '1D', data_authenticity: 'collected', covered_start: '2024-01-01', covered_end: '2024-12-31', total_bar_count: 365, returned_bar_count: 2, max_points: 240, sampling_rule: 'latest_contiguous', bars: [{ date: '2024-12-30', open: '94000', high: '96000', low: '93000', close: '95000', volume: 12000 }, { date: '2024-12-31', open: '95000', high: '97000', low: '94500', close: '96500', volume: 14000 }] } as T;
      },
    } as unknown as GlintApi;
    const preview = await createApiQuantApi(glint).getDatasetPreview('dataset-btc');
    expect(preview).toMatchObject({ datasetId: 'dataset-btc', symbol: 'BTCUSDT', authenticity: 'collected', returnedBarCount: 2, bars: [{ close: 95000 }, { close: 96500 }] });
    expect(calls).toEqual(['/quant/datasets/dataset-btc/preview?max_points=240']);
  });

  it('posts the selected export type and strictly parses Markdown and JSON report exports', async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const markdownResponse = {
      export_type: 'strategy_report_markdown', run_id: 'run-history', candidate_id: 'candidate-b',
      data_authenticity: 'generated',
      filename: 'spy-strategy-report-run-hist.md', media_type: 'text/markdown',
      rendered_content: '# SPY Strategy Report\n', content_digest: `sha256:${'a'.repeat(64)}`,
    };
    const jsonResponse = {
      export_type: 'strategy_evidence_bundle_json', run_id: 'run-history', candidate_id: 'candidate-b',
      data_authenticity: 'generated',
      filename: 'qurio-spy-evidence-run-hist.json', media_type: 'application/json',
      rendered_content: '{\n  "schema_version": "strategy_evidence_bundle_v1"\n}\n', content_digest: `sha256:${'b'.repeat(64)}`,
    };
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest(path: string, init?: RequestInit) {
        calls.push({ path, init });
        const request = JSON.parse(String(init?.body)) as { export_type: string };
        return request.export_type === 'strategy_evidence_bundle_json' ? jsonResponse : markdownResponse;
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);
    const preview = await api.previewStrategyReportExport('run-history', 'candidate-b', 'strategy_report_markdown');
    expect(preview).toMatchObject({ exportType: 'strategy_report_markdown', runId: 'run-history', candidateId: 'candidate-b', authenticity: 'synthetic_fixture', filename: markdownResponse.filename, renderedContent: markdownResponse.rendered_content });
    const jsonPreview = await api.previewStrategyReportExport('run-history', 'candidate-b', 'strategy_evidence_bundle_json');
    expect(jsonPreview).toMatchObject({ exportType: 'strategy_evidence_bundle_json', runId: 'run-history', candidateId: 'candidate-b', filename: jsonResponse.filename, mediaType: 'application/json', renderedContent: jsonResponse.rendered_content });
    expect(calls[0]?.path).toBe('/quant/strategy-report-exports/preview');
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ export_type: 'strategy_report_markdown', run_id: 'run-history', candidate_id: 'candidate-b' });
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({ export_type: 'strategy_evidence_bundle_json', run_id: 'run-history', candidate_id: 'candidate-b' });
    expect(() => parseQuantStrategyReportExport({ ...markdownResponse, filename: '../unsafe.md' })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...markdownResponse, rendered_content: '' })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...markdownResponse, data_authenticity: 'human_authored' })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...jsonResponse, export_type: 'strategy_evidence_bundle_json', media_type: 'text/markdown' })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...jsonResponse, filename: 'spy-report.md' })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...jsonResponse, rendered_content: 'x'.repeat(1_048_577) })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...jsonResponse, rendered_content: '' })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...jsonResponse, content_digest: 'sha256:not-a-digest' })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...jsonResponse, run_id: '' })).toThrow('invalid');
    expect(() => parseQuantStrategyReportExport({ ...jsonResponse, candidate_id: '' })).toThrow('invalid');
  });

  it('creates an API-owned Project and Run with the selected dataset and mode', async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest(path: string, init?: RequestInit) {
        calls.push({ path, init });
        return path === '/quant/projects' ? { id: 'project-new', row_version: 3 } : { id: 'run-new' };
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);
    const project = await api.createProject({ name: 'SPY research', objective: 'Test a trend hypothesis', idempotencyKey: 'project-key' });
    const run = await api.createRun({ projectId: project.id, mode: 'auto', question: 'Test a trend hypothesis', expectedProjectRowVersion: project.rowVersion, datasetId: 'dataset-selected', researchStart: '2023-01-03', researchEnd: '2024-12-31', idempotencyKey: 'run-key' });

    expect(project).toEqual({ id: 'project-new', rowVersion: 3 });
    expect(run).toEqual({ id: 'run-new' });
    expect(calls.map((call) => call.path)).toEqual(['/quant/projects', '/quant/runs']);
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({ project_id: 'project-new', mode: 'auto', question: 'Test a trend hypothesis', expected_project_row_version: 3, dataset_id: 'dataset-selected', research_start: '2023-01-03', research_end: '2024-12-31' });
  });

  it('uses dedicated v2 dataset, Market Run, and mutation contracts without date coercion', async () => {
    const sha = (value: string) => `sha256:${value.repeat(64)}`;
    const dataset = {
      schema_version: 'quant-market-bars-v2', dataset_id: 'market-dataset-4h', workspace_id: '00000000-0000-4000-8000-000000000001', name: 'BTCUSDT 4 hour', symbol: 'BTCUSDT', interval: '4h',
      covered_start: '2024-01-01T00:00:00+00:00', covered_end: '2024-12-31T20:00:00+00:00', bar_count: 2196,
      digest: sha('a'), record_digest: sha('b'), periods_per_year: 2190, market_calendar: '24x7', market_session: 'continuous', time_zone: 'UTC',
      research_eligible: true, data_authenticity: 'collected', created_at: '2026-07-22T00:00:00+00:00',
      evidence: { source_kind: 'provider_fetch', source_name: 'Binance Spot public market data', source_reference: 'binance:BTCUSDT:4h', file_name: null, normalizer_version: 'binance-market-bars-v2', retrieved_at_utc: '2026-07-22T00:00:00+00:00', requested_bar_count: 2196, returned_bar_count: 2196, retained_bar_count: 2196, closed_dropped_count: 0, deduplicated_count: 0, page_raw_sha256: [sha('f')], batch_digest: sha('e'), termination_reason: 'requested_limit', target_satisfied: true },
      quality: { status: 'accepted', cadence_gap_count: 0, normalization_note: 'Contiguous 4h UTC bars.' },
    };
    const run = {
      schema_version: 'quant-market-run-v2', id: 'market-run-4h', row_version: 3, project_id: 'project-market', dataset_id: dataset.dataset_id, dataset_digest: dataset.digest,
      symbol: dataset.symbol, interval: '4h', periods_per_year: 2190, research_start_utc: dataset.covered_start, research_end_utc: dataset.covered_end,
      runtime_descriptor_digest: sha('c'), sealed_split_digest: sha('d'), state: 'waiting_plan_approval', mode: 'plan', question: 'Test 4h trend strategies.',
      plan_revision: 2, attempt_number: 1, parent_run_id: null, seed_candidate_id: null, refinement_reason: null, retry_of_run_id: null, provider: 'deepseek', model: 'deepseek-chat', used_experiments: 0, created_at: '2026-07-22T00:00:00+00:00', updated_at: '2026-07-22T00:01:00+00:00',
    };
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const glint = { workspaceId: 'workspace-1', async quantRequest(path: string, init?: RequestInit) {
      calls.push({ path, init });
      if (path === '/quant/datasets/v2') return [dataset];
      if (path.includes('/preview')) return { dataset, data_authenticity: dataset.data_authenticity, total_bar_count: 2196, returned_bar_count: 1, max_points: 240, sampling_rule: 'latest_contiguous', bars: [{ timestamp: dataset.covered_end, open: '93000.12345678', high: '95000.00000000', low: '92000.00000000', close: '94000.87654321', volume: '12.345678901234567890' }] };
      if (path.startsWith('/quant/market-runs') && (!init || init.method !== 'POST')) return [run];
      return run;
    } } as unknown as GlintApi;
    const api = createApiQuantApi(glint);
    const [listed] = await api.listMarketDatasets();
    const preview = await api.getMarketDatasetPreview(dataset.dataset_id);
    const created = await api.createMarketRun({ projectId: run.project_id, mode: 'plan', question: run.question, expectedProjectRowVersion: 4, datasetId: dataset.dataset_id, researchStartUtc: dataset.covered_start, researchEndUtc: dataset.covered_end, idempotencyKey: 'market-create-key' });
    const history = await api.listMarketRuns();
    const commandRun = { ...quantFixtureSnapshot.run, id: run.id, rowVersion: run.row_version, contract: 'market-v2-public' as const, planRevision: run.plan_revision };
    await api.sendCommand({ command: 'approve_plan', expectedVersion: run.row_version, idempotencyKey: 'market-approve-key', run: commandRun });

    expect(listed).toMatchObject({ contract: 'market-v2', interval: '4h', periodsPerYear: 2190, researchEligible: true });
    expect(preview).toMatchObject({ contract: 'market-v2', coveredEnd: dataset.covered_end, bars: [{ date: dataset.covered_end, decimalValues: { close: '94000.87654321', volume: '12.345678901234567890' } }] });
    expect(created).toMatchObject({ contract: 'market-v2-public', researchStartUtc: dataset.covered_start, researchEndUtc: dataset.covered_end });
    expect(history).toMatchObject([{ contract: 'market-v2-public', id: run.id, interval: '4h', periodsPerYear: 2190, datasetDigest: dataset.digest, runtimeDescriptorDigest: run.runtime_descriptor_digest, sealedSplitDigest: run.sealed_split_digest }]);
    expect(calls.map((call) => call.path)).toEqual(['/quant/datasets/v2', `/quant/datasets/v2/${dataset.dataset_id}/preview?max_points=240`, '/quant/market-runs', '/quant/market-runs?limit=100', `/quant/market-runs/${run.id}/approve-plan`]);
    expect(JSON.parse(String(calls[2]?.init?.body))).toMatchObject({ project_id: run.project_id, mode: 'plan', dataset_id: dataset.dataset_id, research_start_utc: dataset.covered_start, research_end_utc: dataset.covered_end });
    expect(JSON.parse(String(calls[4]?.init?.body))).toEqual({ expected_row_version: 3, plan_revision: 2, reason: 'Plan approved from the research workspace.' });
  });

  it('sends refinement lineage only as a complete server contract', async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const glint = { workspaceId: 'workspace-1', async quantRequest(path: string, init?: RequestInit) { calls.push({ path, init }); return { id: 'run-child' }; } } as unknown as GlintApi;
    await createApiQuantApi(glint).createRun({ projectId: 'project-source', mode: 'plan', question: 'Refine the retained trend rule.', expectedProjectRowVersion: 4, datasetId: 'dataset-source', researchStart: '2023-01-03', researchEnd: '2024-12-31', parentRunId: 'run-parent', seedCandidateId: 'candidate-b', refinementReason: 'Reduce holdout drawdown.', idempotencyKey: 'refine-key' });
    expect(JSON.parse(String(calls[0]?.init?.body))).toMatchObject({ parent_run_id: 'run-parent', seed_candidate_id: 'candidate-b', refinement_reason: 'Reduce holdout drawdown.' });
  });

  it('sends public market continuation lineage only as a complete server contract', async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const digest = (value: string) => `sha256:${value.repeat(64)}`;
    const response = {
      schema_version: 'quant-market-run-v2', id: 'market-run-child', row_version: 1,
      project_id: 'project-source', dataset_id: 'market-dataset-4h', dataset_digest: digest('a'),
      symbol: 'BTCUSDT', interval: '4h', periods_per_year: 2190,
      research_start_utc: '2024-01-01T00:00:00Z', research_end_utc: '2024-12-31T20:00:00Z',
      runtime_descriptor_digest: digest('b'), sealed_split_digest: digest('c'),
      state: 'waiting_plan_approval', mode: 'plan', question: 'Refine the retained 4h trend rule.',
      plan_revision: 1, attempt_number: 1, retry_of_run_id: null,
      parent_run_id: 'market-run-parent', seed_candidate_id: 'candidate-b',
      refinement_reason: 'Reduce holdout drawdown.', provider: 'deepseek', model: 'deepseek-chat',
      used_experiments: 0, created_at: '2026-07-22T00:00:00Z', updated_at: '2026-07-22T00:00:00Z',
    };
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest(path: string, init?: RequestInit) {
        calls.push({ path, init });
        return response;
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);
    const request = {
      projectId: 'project-source', mode: 'plan' as const,
      question: 'Refine the retained 4h trend rule.', expectedProjectRowVersion: 4,
      datasetId: 'market-dataset-4h', researchStartUtc: '2024-01-01T00:00:00Z',
      researchEndUtc: '2024-12-31T20:00:00Z', idempotencyKey: 'market-refine-key',
    };
    await expect(api.createMarketRun({ ...request, parentRunId: 'market-run-parent' })).rejects.toThrow('continuation requires');
    await expect(api.createMarketRun({ ...request, parentRunId: 'market-run-parent', seedCandidateId: 'candidate-b' })).rejects.toThrow('continuation requires');
    await expect(api.createMarketRun({ ...request, parentRunId: 'market-run-parent', seedCandidateId: 'candidate-b', refinementReason: '   ' })).rejects.toThrow('continuation requires');
    expect(calls).toHaveLength(0);

    const created = await api.createMarketRun({
      ...request,
      parentRunId: 'market-run-parent',
      seedCandidateId: 'candidate-b',
      refinementReason: '  Reduce holdout drawdown.  ',
    });
    expect(created).toMatchObject({ id: 'market-run-child', parentRunId: 'market-run-parent', seedCandidateId: 'candidate-b' });
    expect(JSON.parse(String(calls[0]?.init?.body))).toMatchObject({
      parent_run_id: 'market-run-parent',
      seed_candidate_id: 'candidate-b',
      refinement_reason: 'Reduce holdout drawdown.',
    });

    await api.createMarketRun(request);
    const normalCreateBody = JSON.parse(String(calls[1]?.init?.body));
    expect(normalCreateBody).not.toHaveProperty('parent_run_id');
    expect(normalCreateBody).not.toHaveProperty('seed_candidate_id');
    expect(normalCreateBody).not.toHaveProperty('refinement_reason');

    await api.createMarketRun({
      ...request,
      mode: 'auto',
      researchLoop: { followUpMode: 'one_train_only_follow_up', maxVersions: 2, maxTotalExperiments: 6, maxTotalAgentActions: 24 },
    });
    expect(JSON.parse(String(calls[2]?.init?.body))).toMatchObject({
      research_loop: {
        follow_up_mode: 'one_train_only_follow_up',
        max_versions: 2,
        max_total_experiments: 6,
        max_total_agent_actions: 24,
      },
    });
    await expect(api.createMarketRun({
      ...request,
      researchLoop: { followUpMode: 'one_train_only_follow_up', maxVersions: 2, maxTotalExperiments: 6, maxTotalAgentActions: 24 },
    })).rejects.toThrow('root Auto Research');
  });

  it('rejects partial or blank continuation lineage before creating a normal run', async () => {
    const glint = { workspaceId: 'workspace-1', async quantRequest() { throw new Error('must not request'); } } as unknown as GlintApi;
    const request = { projectId: 'project', mode: 'plan' as const, question: 'Refine', expectedProjectRowVersion: 1, datasetId: 'dataset', researchStart: '2024-01-01', researchEnd: '2024-12-31', idempotencyKey: 'key' };
    const api = createApiQuantApi(glint);
    await expect(api.createRun({ ...request, parentRunId: 'parent' })).rejects.toThrow('continuation requires');
    await expect(api.createRun({ ...request, parentRunId: 'parent', seedCandidateId: 'seed' })).rejects.toThrow('continuation requires');
    await expect(api.createRun({ ...request, parentRunId: 'parent', seedCandidateId: 'seed', refinementReason: '   ' })).rejects.toThrow('continuation requires');
  });

  it('lists retained history and parses a selected run snapshot', async () => {
    const calls: string[] = [];
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest<T = unknown>(path: string) {
        calls.push(path);
        if (path === '/quant/projects') return [{ id: 'project-1', name: 'BTC research', objective: 'Test trend.', status: 'active', row_version: 2, created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-02T00:00:00Z' }] as T;
        if (path === '/quant/runs') return [
          { id: 'run-2', project_id: 'project-2', dataset_id: 'dataset-2', state: 'waiting_for_review', mode: 'plan', question: 'Review momentum.', attempt_number: 2, parent_run_id: null, seed_candidate_id: null, refinement_reason: null, retry_of_run_id: null, provider: 'deepseek', model: 'deepseek-chat', used_experiments: 3, created_at: '2026-07-03T00:00:00Z', updated_at: '2026-07-03T01:00:00Z' },
          { id: 'run-1', project_id: 'project-1', dataset_id: 'dataset-1', state: 'completed', mode: 'auto', question: 'Test trend.', attempt_number: 1, parent_run_id: null, seed_candidate_id: null, refinement_reason: null, retry_of_run_id: null, provider: 'deepseek', model: 'deepseek-chat', used_experiments: 2, created_at: '2026-07-02T00:00:00Z', updated_at: '2026-07-02T01:00:00Z' },
        ] as T;
        if (path.startsWith('/quant/runs?')) return [{ id: 'run-1', project_id: 'project-1', dataset_id: 'dataset-1', state: 'completed', mode: 'auto', question: 'Test trend.', attempt_number: 1, parent_run_id: null, seed_candidate_id: null, refinement_reason: null, retry_of_run_id: null, provider: 'deepseek', model: 'deepseek-chat', used_experiments: 2, created_at: '2026-07-02T00:00:00Z', updated_at: '2026-07-02T01:00:00Z' }] as T;
        if (path === '/quant/runs/run-1/workspace-snapshot') return { ...structuredClone(quantFixtureSnapshot), run: { ...structuredClone(quantFixtureSnapshot.run), id: 'run-1' } } as T;
        return quantFixtureSnapshot as T;
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);

    expect(await api.listProjects()).toMatchObject([{ id: 'project-1', rowVersion: 2 }]);
    expect(await api.listRuns()).toMatchObject([
      { id: 'run-2', projectId: 'project-2', datasetId: 'dataset-2', parentRunId: null, seedCandidateId: null, refinementReason: null, retryOfRunId: null, state: 'waiting_for_review', mode: 'plan', attemptNumber: 2, updatedAt: '2026-07-03T01:00:00Z' },
      { id: 'run-1', projectId: 'project-1', datasetId: 'dataset-1', parentRunId: null, seedCandidateId: null, refinementReason: null, retryOfRunId: null, state: 'completed', mode: 'auto', attemptNumber: 1, updatedAt: '2026-07-02T01:00:00Z' },
    ]);
    expect(await api.listRuns('project-1')).toMatchObject([{ id: 'run-1', projectId: 'project-1', usedExperiments: 2 }]);
    expect((await api.getRunWorkspaceSnapshot('run-1')).run.id).toBe('run-1');
    expect(calls).toEqual(['/quant/projects', '/quant/runs', '/quant/runs?project_id=project-1', '/quant/runs/run-1/workspace-snapshot']);
  });

  it('rejects a historical snapshot bound to a different Run than requested', async () => {
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest<T = unknown>() { return quantFixtureSnapshot as T; },
    } as unknown as GlintApi;
    await expect(createApiQuantApi(glint).getRunWorkspaceSnapshot('run-requested')).rejects.toThrow('differs from the requested Run');
  });

  it('keeps all-absent legacy root lineage compatible but rejects partial or malformed modern lineage', async () => {
    const base = { id: 'run-1', project_id: 'project-1', dataset_id: 'dataset-1', state: 'completed', mode: 'auto', question: 'Test trend.', attempt_number: 1, retry_of_run_id: null, provider: 'deepseek', model: null, used_experiments: 2, created_at: '2026-07-02T00:00:00Z', updated_at: '2026-07-02T01:00:00Z' };
    const legacyRoot = { ...base };
    const rootApi = createApiQuantApi({ workspaceId: 'workspace-1', async quantRequest() { return [legacyRoot]; } } as unknown as GlintApi);
    await expect(rootApi.listRuns()).resolves.toMatchObject([{ parentRunId: null, seedCandidateId: null, refinementReason: null }]);

    for (const invalid of [
      { ...base, parent_run_id: null },
      { ...base, parent_run_id: 'run-source', seed_candidate_id: 'candidate-a' },
      { ...base, parent_run_id: 'run-source', seed_candidate_id: 'candidate-a', refinement_reason: '   ' },
    ]) {
      const api = createApiQuantApi({ workspaceId: 'workspace-1', async quantRequest() { return [invalid]; } } as unknown as GlintApi);
      await expect(api.listRuns()).rejects.toThrow();
    }
  });
});

describe('Quant API workspace snapshot boundary', () => {
  it('requests the snapshot as unknown and parses it through the runtime boundary', async () => {
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest<T = unknown>() {
        return quantFixtureSnapshot as T;
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);
    const snapshot = await api.getWorkspaceSnapshot();
    expect(snapshot).toEqual(quantFixtureSnapshot);
  });

  it('hydrates a public Market Run when equivalent UTC instants use different RFC3339 offsets', async () => {
    const snapshot = JSON.parse(JSON.stringify(quantFixtureSnapshot));
    const digest = `sha256:${'6'.repeat(64)}`;
    const runtimeDescriptorDigest = `sha256:${'7'.repeat(64)}`;
    const sealedSplitDigest = `sha256:${'8'.repeat(64)}`;
    const start = '2026-02-05T12:00:00+00:00';
    const end = '2026-07-22T00:00:00+00:00';
    snapshot.run = { ...snapshot.run, id: 'market-run-live', mode: 'auto_research', contract: 'market-v2-private' };
    snapshot.project = { ...snapshot.project, id: 'market-project-live', latestRunId: snapshot.run.id };
    snapshot.scope = { ...snapshot.scope, symbol: 'BTCUSDT', interval: '4h', dateRange: { start, end } };
    snapshot.dataset = {
      contract: 'market-v2', id: 'market-dataset-live', name: 'BTCUSDT 4h', symbol: 'BTCUSDT', interval: '4h', dateRange: { start, end }, barCount: 1000,
      schemaVersion: 'quant-market-bars-v2', parserVersion: 'binance-market-bars-v2', digest, authenticity: 'collected', researchEligible: true,
      periodsPerYear: 2190, marketCalendar: '24x7', marketSession: 'continuous', timeZone: 'UTC', runtimeDescriptorDigest, sealedSplitDigest,
      source: { kind: 'provider_fetch', fileName: null, sourceName: 'Binance Spot public market data', sourceReference: 'binance:BTCUSDT:4h', normalizerVersion: 'binance-market-bars-v2', retrievedAtUtc: '2026-07-22T04:14:39+00:00', requestedBarCount: 1000, returnedBarCount: 1001, retainedBarCount: 1000, closedDroppedCount: 1, deduplicatedCount: 0, terminationReason: 'requested_limit', targetSatisfied: true },
      quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'No cadence gaps detected.' },
    };
    snapshot.kernelCheck = { ...snapshot.kernelCheck, datasetId: snapshot.dataset.id, datasetDigest: digest, barCount: 1000, interval: '4h', periodsPerYear: 2190, runtimeDescriptorDigest, sealedSplitDigest };
    snapshot.report = null;
    snapshot.candidates = [];
    snapshot.performanceSeries = [];
    snapshot.trades = [];
    snapshot.bars = [];
    const marketRun = {
      schema_version: 'quant-market-run-v2', id: snapshot.run.id, row_version: snapshot.run.rowVersion, project_id: snapshot.project.id,
      dataset_id: snapshot.dataset.id, dataset_digest: digest, symbol: 'BTCUSDT', interval: '4h', periods_per_year: 2190,
      research_start_utc: '2026-02-05T12:00:00Z', research_end_utc: '2026-07-22T00:00:00Z', runtime_descriptor_digest: runtimeDescriptorDigest,
      sealed_split_digest: sealedSplitDigest, state: snapshot.run.state, mode: 'auto', question: snapshot.project.goal, plan_revision: 1,
      attempt_number: 1, parent_run_id: null, seed_candidate_id: null, refinement_reason: null, retry_of_run_id: null, provider: 'deepseek', model: 'deepseek-chat', used_experiments: 0, created_at: '2026-07-22T04:15:00Z', updated_at: '2026-07-22T04:16:00Z',
    };
    const glint = { workspaceId: 'workspace-1', async quantRequest(path: string) { return path === '/quant/workspace-snapshot' ? snapshot : [marketRun]; } } as unknown as GlintApi;

    const hydrated = await createApiQuantApi(glint).getWorkspaceSnapshot();

    expect(hydrated.run).toMatchObject({ id: marketRun.id, contract: 'market-v2-public' });

    snapshot.run.continuedFrom = {
      parentRunId: 'market-run-source', seedCandidateId: 'candidate-b', candidateName: 'SMA 50/200',
      sourceQuestion: 'Compare the retained source evidence.', reason: 'Test a slower trend filter.',
    };
    Object.assign(marketRun, {
      parent_run_id: 'market-run-source', seed_candidate_id: 'candidate-b',
      refinement_reason: 'Test a slower trend filter.',
    });
    await expect(createApiQuantApi(glint).getWorkspaceSnapshot()).resolves.toMatchObject({
      run: { contract: 'market-v2-public', continuedFrom: snapshot.run.continuedFrom },
    });
    Object.assign(marketRun, { seed_candidate_id: 'candidate-other' });
    await expect(createApiQuantApi(glint).getWorkspaceSnapshot()).rejects.toThrow('identity differs');
  });

  it('preserves the server-authoritative unsupported Market Run commands during hydration', async () => {
    const snapshot = JSON.parse(JSON.stringify(quantFixtureSnapshot));
    const digest = `sha256:${'1'.repeat(64)}`;
    const runtimeDescriptorDigest = `sha256:${'2'.repeat(64)}`;
    const sealedSplitDigest = `sha256:${'3'.repeat(64)}`;
    const start = '2026-02-05T12:00:00+00:00';
    const end = '2026-07-22T00:00:00+00:00';
    snapshot.run = {
      ...snapshot.run,
      id: 'market-run-unsupported',
      state: 'waiting_plan_approval',
      mode: 'plan',
      contract: 'market-v2-private',
      legalCommands: ['request_plan_changes', 'cancel_run'],
    };
    snapshot.project = { ...snapshot.project, id: 'market-project-unsupported', latestRunId: snapshot.run.id };
    snapshot.scope = { ...snapshot.scope, symbol: 'BTCUSDT', interval: '4h', dateRange: { start, end } };
    snapshot.dataset = {
      contract: 'market-v2',
      id: 'market-dataset-unsupported',
      name: 'BTCUSDT 4h',
      symbol: 'BTCUSDT',
      interval: '4h',
      dateRange: { start, end },
      barCount: 1000,
      schemaVersion: 'quant-market-bars-v2',
      parserVersion: 'binance-market-bars-v2',
      digest,
      authenticity: 'collected',
      researchEligible: true,
      periodsPerYear: 2190,
      marketCalendar: '24x7',
      marketSession: 'continuous',
      timeZone: 'UTC',
      runtimeDescriptorDigest,
      sealedSplitDigest,
      source: {
        kind: 'provider_fetch',
        fileName: null,
        sourceName: 'Binance Spot public market data',
        sourceReference: 'binance:BTCUSDT:4h',
        normalizerVersion: 'binance-market-bars-v2',
        retrievedAtUtc: '2026-07-22T04:14:39+00:00',
        requestedBarCount: 1000,
        returnedBarCount: 1001,
        retainedBarCount: 1000,
        closedDroppedCount: 1,
        deduplicatedCount: 0,
        terminationReason: 'requested_limit',
        targetSatisfied: true,
      },
      quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'No cadence gaps detected.' },
    };
    snapshot.kernelCheck = {
      ...snapshot.kernelCheck,
      datasetId: snapshot.dataset.id,
      datasetDigest: digest,
      barCount: 1000,
      interval: '4h',
      periodsPerYear: 2190,
      runtimeDescriptorDigest,
      sealedSplitDigest,
    };
    snapshot.researchPlan = {
      candidateFamilies: [],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Revise the request before experiments begin.'],
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'unsupported',
        reason: 'The request requires long-short portfolio logic.',
        excludedBehaviors: ['Short positions', 'Cross-asset ranking'],
      },
    };
    snapshot.report = null;
    snapshot.candidates = [];
    snapshot.performanceSeries = [];
    snapshot.trades = [];
    snapshot.bars = [];
    const marketRun = {
      schema_version: 'quant-market-run-v2',
      id: snapshot.run.id,
      row_version: snapshot.run.rowVersion,
      project_id: snapshot.project.id,
      dataset_id: snapshot.dataset.id,
      dataset_digest: digest,
      symbol: 'BTCUSDT',
      interval: '4h',
      periods_per_year: 2190,
      research_start_utc: start,
      research_end_utc: end,
      runtime_descriptor_digest: runtimeDescriptorDigest,
      sealed_split_digest: sealedSplitDigest,
      state: 'waiting_plan_approval',
      mode: 'plan',
      question: snapshot.project.goal,
      plan_revision: 1,
      attempt_number: 1,
      parent_run_id: null,
      seed_candidate_id: null,
      refinement_reason: null,
      retry_of_run_id: null,
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      used_experiments: 0,
      created_at: '2026-07-22T04:15:00Z',
      updated_at: '2026-07-22T04:16:00Z',
    };
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest(path: string) {
        return path === '/quant/workspace-snapshot' ? snapshot : [marketRun];
      },
    } as unknown as GlintApi;

    const hydrated = await createApiQuantApi(glint).getWorkspaceSnapshot();

    expect(hydrated.run).toMatchObject({
      contract: 'market-v2-public',
      legalCommands: ['request_plan_changes', 'cancel_run'],
    });
    expect(hydrated.run.legalCommands).not.toContain('approve_plan');
    expect(hydrated.run.legalCommands).not.toContain('ask');
  });

  it('throws a compatibility error for an unsupported snapshot version', async () => {
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest<T = unknown>() {
        return { version: 'future-v1' } as T;
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);
    await expect(api.getWorkspaceSnapshot()).rejects.toThrow(QuantWorkspaceCompatibilityError);
  });

  it('strictly parses the connector directory and routes Kraken fetches into market-v2', async () => {
    const connectorDto = {
      data_authenticity: 'generated',
      connector_id: 'kraken-spot-ohlc-v1',
      provider: 'kraken_spot',
      display_name: 'Kraken Spot public OHLC',
      source_kind: 'market_bars',
      supported_symbols: ['BTCUSD', 'BTCUSDT', 'ETHUSD', 'ETHUSDT'],
      supported_intervals: ['4h', '1D'],
      minimum_recent_bars: { '4h': 548, '1D': 252 },
      maximum_recent_bars: 719,
      fetch_endpoint: '/v1/quant/connectors/kraken-spot-ohlc-v1/fetch',
      connector_version: 'kraken-spot-ohlc-v1',
      source_terms_url: 'https://www.kraken.com/legal',
      source_documentation_url: 'https://docs.kraken.com/api-reference/market-data/get-ohlc-data',
    } as const;
    expect(parseQuantMarketDataConnector(connectorDto)).toMatchObject({
      id: 'kraken-spot-ohlc-v1',
      provider: 'kraken_spot',
      supportedIntervals: ['4h', '1D'],
      minimumRecentBars: { '4h': 548, '1D': 252 },
      maximumRecentBars: 719,
    });
    expect(() => parseQuantMarketDataConnector({ ...connectorDto, fetch_endpoint: '/v1/quant/connectors/other/fetch' })).toThrow('fetch_endpoint');
    expect(() => parseQuantMarketDataConnector({ ...connectorDto, data_authenticity: 'imported' })).toThrow('data_authenticity');

    const datasetDto = {
      schema_version: 'quant-market-bars-v2',
      dataset_id: 'kraken-btcusd-4h',
      workspace_id: 'workspace-1',
      name: 'BTCUSD Kraken Spot 4 hour',
      symbol: 'BTCUSD',
      interval: '4h',
      covered_start: '2026-04-24T20:00:00+00:00',
      covered_end: '2026-07-24T00:00:00+00:00',
      bar_count: 548,
      market_calendar: '24x7',
      market_session: 'continuous',
      time_zone: 'UTC',
      periods_per_year: 2190,
      digest: `sha256:${'a'.repeat(64)}`,
      record_digest: `sha256:${'b'.repeat(64)}`,
      evidence: {
        source_kind: 'provider_fetch',
        source_name: 'Kraken Spot public OHLC',
        source_reference: 'kraken:BTCUSD:4h',
        normalizer_version: 'kraken-spot-ohlc-v1',
        retrieved_at_utc: '2026-07-24T04:00:00+00:00',
        requested_bar_count: 548,
        returned_bar_count: 548,
        retained_bar_count: 548,
        closed_dropped_count: 0,
        deduplicated_count: 0,
        termination_reason: 'requested_limit',
        target_satisfied: true,
        raw_page_digests: [`sha256:${'c'.repeat(64)}`],
        batch_digest: `sha256:${'d'.repeat(64)}`,
      },
      quality: { status: 'accepted', cadence_gap_count: 0, normalization_note: 'Contiguous 4h UTC bars.' },
      research_eligible: true,
      data_authenticity: 'collected',
      created_at: '2026-07-24T04:00:00+00:00',
    };
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest(path: string, init?: RequestInit) {
        calls.push({ path, init });
        return path === '/quant/connectors' ? [connectorDto] : datasetDto;
      },
    } as unknown as GlintApi;
    const api = createApiQuantApi(glint);
    await expect(api.listConnectors()).resolves.toEqual([expect.objectContaining({ id: connectorDto.connector_id })]);
    await expect(api.fetchConnectorDataset({
      connectorId: connectorDto.connector_id,
      name: 'BTCUSD Kraken Spot 4 hour',
      symbol: 'btcusd',
      interval: '4h',
      limit: 548,
      idempotencyKey: '99999999-9999-4999-8999-999999999999',
    })).resolves.toMatchObject({ contract: 'market-v2', symbol: 'BTCUSD', interval: '4h', researchEligible: true });
    expect(calls[1]?.path).toBe('/quant/connectors/kraken-spot-ohlc-v1/fetch');
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      name: 'BTCUSD Kraken Spot 4 hour',
      symbol: 'BTCUSD',
      interval: '4h',
      limit: 548,
    });
  });

  it('times out a workspace snapshot request so the UI can offer recovery', async () => {
    vi.useFakeTimers();
    try {
      const glint = {
        workspaceId: 'workspace-1',
        quantRequest<T = unknown>(_path: string, init?: RequestInit): Promise<T> {
          return new Promise<T>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
          });
        },
      } as unknown as GlintApi;
      const request = createApiQuantApi(glint).getWorkspaceSnapshot();
      const rejection = expect(request).rejects.toThrow('Workspace snapshot request timed out.');
      await vi.advanceTimersByTimeAsync(QUANT_WORKSPACE_REQUEST_TIMEOUT_MS);
      await rejection;
    } finally {
      vi.useRealTimers();
    }
  });
});
