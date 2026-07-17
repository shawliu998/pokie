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
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const glint = {
      workspaceId: 'workspace-1',
      async quantRequest(path: string, init?: RequestInit) {
        calls.push({ path, init });
        return path.endsWith('/import-csv') ? dto : [dto];
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
  });

  it('generates API-compatible UUID idempotency keys', () => {
    expect(quantIdempotencyKey()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  });
});
