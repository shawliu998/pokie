import { describe, expect, it } from 'vitest';
import type { GlintApi } from './api';
import { createApiQuantApi, createFixtureQuantApi, quantIdempotencyKey } from './quant-api';

describe('Quant fixture API adapter', () => {
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

    expect(listed[0]).toMatchObject({ id: dto.dataset_id, symbol: 'ACME', barCount: 300, authenticity: 'imported_fixture', source: { sourceName: 'Example Exchange', fileName: 'acme.csv', priceAdjustment: 'split_adjusted' }, quality: { schemaVersion: 'quant-data-quality-v1', policyVersion: 'ohlcv-quality-v1', status: 'warning', verificationStatus: 'checked', calendarGapCount: 2, largestCalendarGapDays: 3, zeroVolumeBarCount: 1, priceJumpCount: 4 } });
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

  it('generates API-compatible UUID idempotency keys', () => {
    expect(quantIdempotencyKey()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  });
});
