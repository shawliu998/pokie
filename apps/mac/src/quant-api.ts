import type { DatasetDataQuality, DatasetSnapshot, QuantCommand, QuantWorkspaceSnapshot } from './quant-domain';
import { quantFixtureSnapshot } from './features/quant/quant-fixtures';
import type { GlintApi } from './api';

export interface QuantCommandRequest {
  command: QuantCommand;
  expectedVersion: number;
  idempotencyKey: string;
  payload?: Record<string, unknown>;
}

export interface QuantCommandReceipt {
  status: 'accepted' | 'fixture_only' | 'rejected';
  message: string;
}

let fallbackIdempotencySequence = 0;

export function quantIdempotencyKey(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const tail = (Date.now() + fallbackIdempotencySequence++).toString(16).padStart(12, '0').slice(-12);
  return `00000000-0000-4000-8000-${tail}`;
}

export interface QuantDatasetImportRequest {
  name: string;
  symbol: string;
  csvText: string;
  fileName?: string;
  sourceName?: string;
  sourceReference?: string;
  marketCalendar?: 'unknown' | 'weekday' | 'XNYS' | 'XNAS' | 'XSHG' | 'XSHE';
  timeZone?: string;
  priceAdjustment?: 'unknown' | 'unadjusted' | 'split_adjusted' | 'total_return_adjusted';
  idempotencyKey: string;
}

export interface QuantApi {
  getWorkspaceSnapshot(): Promise<QuantWorkspaceSnapshot>;
  sendCommand(request: QuantCommandRequest): Promise<QuantCommandReceipt>;
  listDatasets(): Promise<DatasetSnapshot[]>;
  importDatasetCsv(request: QuantDatasetImportRequest): Promise<DatasetSnapshot>;
}

interface QuantDatasetDto {
  dataset_id: string;
  name: string;
  symbol: string;
  interval: '1D';
  covered_start: string;
  covered_end: string;
  bar_count: number;
  schema_version: string;
  parser_version: string;
  digest: string;
  source_metadata: {
    kind: 'csv_upload';
    file_name: string | null;
    source_name: string;
    source_reference: string | null;
    submitted_csv_digest: string | null;
    market_calendar: 'unknown' | 'weekday' | 'XNYS' | 'XNAS' | 'XSHG' | 'XSHE';
    time_zone: string;
    price_adjustment: 'unknown' | 'unadjusted' | 'split_adjusted' | 'total_return_adjusted';
  };
  data_quality?: QuantDatasetDataQualityDto;
}

interface QuantDatasetDataQualityDto {
  schema_version: string;
  policy_version: string;
  status: 'passed' | 'warning' | 'blocked';
  verification_status: 'checked' | 'rejected';
  report_digest: string;
  dataset_digest: string;
  bar_count: number;
  calendar_gap_count: number;
  largest_calendar_gap_days: number;
  unexpected_session_count: number;
  zero_volume_bar_count: number;
  price_jump_count: number;
  issues: Array<{ code: string; severity: string; message: string; count: number }>;
  notes: string[];
}

function mapDatasetQuality(dto: QuantDatasetDataQualityDto): DatasetDataQuality {
  return {
    schemaVersion: dto.schema_version,
    policyVersion: dto.policy_version,
    status: dto.status,
    verificationStatus: dto.verification_status,
    reportDigest: dto.report_digest,
    datasetDigest: dto.dataset_digest,
    barCount: dto.bar_count,
    calendarGapCount: dto.calendar_gap_count,
    largestCalendarGapDays: dto.largest_calendar_gap_days,
    unexpectedSessionCount: dto.unexpected_session_count,
    zeroVolumeBarCount: dto.zero_volume_bar_count,
    priceJumpCount: dto.price_jump_count,
    issues: dto.issues.map((issue) => ({ ...issue })),
    notes: [...dto.notes],
  };
}

function mapDataset(dto: QuantDatasetDto): DatasetSnapshot {
  return {
    id: dto.dataset_id,
    name: dto.name,
    symbol: dto.symbol,
    interval: dto.interval,
    dateRange: { start: dto.covered_start, end: dto.covered_end },
    barCount: dto.bar_count,
    schemaVersion: dto.schema_version,
    parserVersion: dto.parser_version,
    digest: dto.digest,
    authenticity: 'imported_fixture',
    source: {
      kind: dto.source_metadata.kind,
      fileName: dto.source_metadata.file_name,
      sourceName: dto.source_metadata.source_name,
      sourceReference: dto.source_metadata.source_reference,
      submittedCsvDigest: dto.source_metadata.submitted_csv_digest,
      marketCalendar: dto.source_metadata.market_calendar,
      timeZone: dto.source_metadata.time_zone,
      priceAdjustment: dto.source_metadata.price_adjustment,
    },
    ...(dto.data_quality ? { quality: mapDatasetQuality(dto.data_quality) } : {}),
  };
}

/**
 * Offline/test adapter seam. The production HTTP adapter is defined below.
 * This fixture adapter never changes run state; lifecycle transitions remain
 * API-owned.
 */
export function createFixtureQuantApi(): QuantApi {
  return {
    async getWorkspaceSnapshot() { return quantFixtureSnapshot; },
    async sendCommand(request) {
      const snapshot = quantFixtureSnapshot;
      const legal = snapshot.run.legalCommands.includes(request.command) || snapshot.composerLegalCommands.includes(request.command);
      return legal
        ? { status: 'fixture_only', message: 'Quant API adapter stub received the legal command. No run-state transition is applied by the frontend fixture.' }
        : { status: 'rejected', message: 'This command is not legal for the current API fixture snapshot.' };
    },
    async listDatasets() { return []; },
    async importDatasetCsv() {
      throw new Error('CSV import requires the authenticated Quant API.');
    },
  };
}

/** Build the production Mac adapter on top of the authenticated Glint session. */
export function createApiQuantApi(api: GlintApi): QuantApi {
  const quantRequest = api.quantRequest?.bind(api);
  if (!quantRequest) throw new Error('The authenticated API does not expose the Quant transport.');
  return {
    async getWorkspaceSnapshot() {
      return quantRequest<QuantWorkspaceSnapshot>('/quant/workspace-snapshot');
    },
    async sendCommand(request) {
      const supported: ReadonlySet<QuantCommand> = new Set(['ask', 'generate_plan', 'start_auto_research', 'approve_plan', 'run_fixture', 'request_plan_changes', 'cancel_run', 'retry_run', 'complete_review']);
      if (!supported.has(request.command)) return { status: 'rejected', message: 'The server snapshot did not expose a supported lifecycle command.' };
      await quantRequest('/quant/workspace-snapshot/commands', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({ command: request.command, expected_row_version: request.expectedVersion, payload: request.payload ?? {} }),
      });
      return { status: 'accepted', message: 'Command accepted by the API; refreshing the authoritative snapshot.' };
    },
    async listDatasets() {
      const rows = await quantRequest<QuantDatasetDto[]>('/quant/datasets');
      return rows.map(mapDataset);
    },
    async importDatasetCsv(request) {
      const row = await quantRequest<QuantDatasetDto>('/quant/datasets/import-csv', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          name: request.name,
          symbol: request.symbol,
          csv_text: request.csvText,
          file_name: request.fileName,
          source_name: request.sourceName ?? 'User-provided CSV',
          source_reference: request.sourceReference,
          market_calendar: request.marketCalendar ?? 'unknown',
          time_zone: request.timeZone ?? 'UTC',
          price_adjustment: request.priceAdjustment ?? 'unknown',
        }),
      });
      return mapDataset(row);
    },
  };
}
