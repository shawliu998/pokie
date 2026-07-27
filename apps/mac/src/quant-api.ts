import type { DatasetDataQuality, DatasetSnapshot, QuantAuthenticity, QuantBarInterval, QuantCommand, QuantDatasetPreview, QuantResearchRun, QuantWorkspaceSnapshot } from './quant-domain';
import { quantFixtureSnapshot } from './features/quant/quant-fixtures';
import type { GlintApi } from './api';
import { parseQuantDatasetPreview } from './quant-dataset-preview-parser';
import { parseQuantWorkspaceSnapshot, QuantWorkspaceCompatibilityError } from './quant-workspace-parser';
import { parseQuantMarketDataset, parseQuantMarketDatasetPreview, parseQuantMarketRun, type QuantMarketRunRecord } from './quant-market-parser';

export const QUANT_WORKSPACE_REQUEST_TIMEOUT_MS = 12_000;

export interface QuantCommandRequest {
  command: QuantCommand;
  expectedVersion: number;
  idempotencyKey: string;
  payload?: Record<string, unknown>;
  run?: Pick<QuantResearchRun, 'id' | 'contract' | 'planRevision'>;
}

export interface QuantCommandReceipt {
  status: 'accepted' | 'fixture_only' | 'rejected';
  message: string;
}

export type PaperOrderState = 'draft' | 'submitted' | 'partially_filled' | 'filled' | 'cancelled' | 'rejected';

export interface PaperAccount {
  accountId: string;
  environment: 'paper';
  broker: 'local_simulator';
  currency: 'USD';
  status: 'active' | 'unconfigured' | 'error';
  cash: string;
  buyingPower: string;
  equity: string;
  rowVersion: number;
  lastReconciledAt: string | null;
  updatedAt: string;
}

export interface PaperPosition {
  symbol: string;
  quantity: string;
  averageEntryPrice: string;
  currentPrice: string;
  marketValue: string;
  unrealizedPl: string;
  updatedAt: string;
}

export interface PaperOrder {
  orderId: string;
  state: PaperOrderState;
  sourceRunId: string;
  sourceCandidateId: string;
  sourceEvidenceDigest: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: string;
  filledQuantity: string;
  orderType: 'market';
  timeInForce: 'day';
  limitPrice: string | null;
  referencePrice: string;
  estimatedNotional: string;
  averageFillPrice: string | null;
  rowVersion: number;
  createdAt: string;
  updatedAt: string;
}

export interface PaperFill {
  fillId: string;
  orderId: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: string;
  price: string;
  notional: string;
  occurredAt: string;
}

export interface PaperSnapshot {
  contractVersion: 'qurio-paper-v1';
  environment: 'paper';
  account: PaperAccount;
  positions: PaperPosition[];
  orders: PaperOrder[];
  fills: PaperFill[];
  generatedAt: string;
}

export interface PaperDraftRequest {
  sourceRunId: string;
  sourceCandidateId: string;
  side: 'buy' | 'sell';
  quantity: string;
  orderType: 'market';
  timeInForce: 'day';
  expectedAccountRowVersion: number;
  idempotencyKey: string;
}

function parsePaperSnapshot(value: unknown): PaperSnapshot {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Paper snapshot must be an object.');
  const row = value as Record<string, unknown>;
  if (row.contract_version !== 'qurio-paper-v1' || row.environment !== 'paper' || !row.account) {
    throw new Error('Paper snapshot contract is unsupported.');
  }
  const account = row.account as Record<string, unknown>;
  const mapOrder = (value: unknown): PaperOrder => {
    const order = value as Record<string, unknown>;
    return {
    orderId: String(order.order_id), state: order.state, sourceRunId: String(order.source_run_id),
    sourceCandidateId: String(order.source_candidate_id), sourceEvidenceDigest: String(order.source_evidence_digest),
    symbol: String(order.symbol), side: order.side, quantity: String(order.quantity),
    filledQuantity: String(order.filled_quantity), orderType: order.order_type, timeInForce: order.time_in_force,
    limitPrice: order.limit_price == null ? null : String(order.limit_price), referencePrice: String(order.reference_price),
    estimatedNotional: String(order.estimated_notional), averageFillPrice: order.average_fill_price == null ? null : String(order.average_fill_price),
    rowVersion: Number(order.row_version), createdAt: String(order.created_at), updatedAt: String(order.updated_at),
    } as PaperOrder;
  };
  return {
    contractVersion: 'qurio-paper-v1',
    environment: 'paper',
    account: {
      accountId: String(account.account_id), environment: 'paper', broker: account.broker as PaperAccount['broker'],
      currency: 'USD', status: account.status as PaperAccount['status'], cash: String(account.cash),
      buyingPower: String(account.buying_power), equity: String(account.equity),
      rowVersion: Number(account.row_version), lastReconciledAt: account.last_reconciled_at == null ? null : String(account.last_reconciled_at),
      updatedAt: String(account.updated_at),
    },
    positions: (Array.isArray(row.positions) ? row.positions : []).map((value) => {
      const position = value as Record<string, unknown>;
      return {
        symbol: String(position.symbol), quantity: String(position.quantity),
        averageEntryPrice: String(position.average_entry_price), currentPrice: String(position.current_price),
        marketValue: String(position.market_value), unrealizedPl: String(position.unrealized_pl),
        updatedAt: String(position.updated_at),
      };
    }),
    orders: (Array.isArray(row.orders) ? row.orders : []).map(mapOrder),
    fills: (Array.isArray(row.fills) ? row.fills : []).map((value) => {
      const fill = value as Record<string, unknown>;
      return {
        fillId: String(fill.fill_id), orderId: String(fill.order_id), symbol: String(fill.symbol),
        side: fill.side, quantity: String(fill.quantity), price: String(fill.price),
        notional: String(fill.notional), occurredAt: String(fill.occurred_at),
      } as PaperFill;
    }),
    generatedAt: String(row.generated_at),
  };
}

function parsePaperOrder(value: unknown): PaperOrder {
  return parsePaperSnapshot({
    contract_version: 'qurio-paper-v1',
    environment: 'paper',
    account: {
      account_id: '00000000-0000-4000-8000-000000000001', broker: 'local_simulator',
      status: 'active', cash: '0', buying_power: '0', equity: '0', row_version: 1,
      last_reconciled_at: null, updated_at: new Date().toISOString(),
    },
    positions: [], orders: [value], fills: [], generated_at: new Date().toISOString(),
  }).orders[0]!;
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

export interface QuantMarketDatasetImportRequest {
  name: string;
  symbol: string;
  interval: QuantBarInterval;
  marketCalendar?: '24x7' | 'XNYS' | 'XNAS' | 'XSHG' | 'XSHE';
  csvText: string;
  fileName?: string;
  sourceName?: string;
  sourceReference?: string;
  idempotencyKey: string;
}

export interface QuantBinanceSpotFetchRequest {
  symbol?: string;
  limit?: number;
  idempotencyKey: string;
}

export interface QuantMarketBinanceFetchRequest {
  name?: string;
  symbol?: string;
  interval: QuantBarInterval;
  limit?: number;
  idempotencyKey: string;
}

export type QuantConnectorInterval = Extract<QuantBarInterval, '4h' | '1D'>;

export interface QuantMarketDataConnector {
  id: string;
  provider: string;
  displayName: string;
  sourceKind: 'market_bars';
  supportedSymbols: string[];
  supportedIntervals: QuantConnectorInterval[];
  minimumRecentBars: Record<QuantConnectorInterval, number>;
  maximumRecentBars: number;
  fetchPath: string;
  version: string;
  sourceTermsUrl: string;
  sourceDocumentationUrl: string;
}

export interface QuantConnectorFetchRequest {
  connectorId: string;
  name?: string;
  symbol: string;
  interval: QuantConnectorInterval;
  limit: number;
  idempotencyKey: string;
}

function requiredConnectorText(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`Connector ${field} must be a non-empty string.`);
  return value;
}

function requiredHttpsUrl(value: unknown, field: string): string {
  const text = requiredConnectorText(value, field);
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    throw new Error(`Connector ${field} must be an HTTPS URL.`);
  }
  if (url.protocol !== 'https:') throw new Error(`Connector ${field} must be an HTTPS URL.`);
  return text;
}

export function parseQuantMarketDataConnector(value: unknown): QuantMarketDataConnector {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Connector directory item must be an object.');
  const row = value as Record<string, unknown>;
  const id = requiredConnectorText(row.connector_id, 'connector_id');
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id)) throw new Error('Connector connector_id is invalid.');
  const expectedFetchPath = `/v1/quant/connectors/${id}/fetch`;
  if (row.source_kind !== 'market_bars') throw new Error('Connector source_kind is unsupported.');
  if (!Array.isArray(row.supported_symbols) || row.supported_symbols.length === 0
    || row.supported_symbols.some((symbol) => typeof symbol !== 'string' || !/^[A-Z0-9]+$/.test(symbol))) {
    throw new Error('Connector supported_symbols is invalid.');
  }
  if (new Set(row.supported_symbols).size !== row.supported_symbols.length) throw new Error('Connector supported_symbols must be unique.');
  if (!Array.isArray(row.supported_intervals) || row.supported_intervals.length === 0
    || row.supported_intervals.some((interval) => interval !== '4h' && interval !== '1D')) {
    throw new Error('Connector supported_intervals is invalid.');
  }
  if (new Set(row.supported_intervals).size !== row.supported_intervals.length) throw new Error('Connector supported_intervals must be unique.');
  if (!row.minimum_recent_bars || typeof row.minimum_recent_bars !== 'object' || Array.isArray(row.minimum_recent_bars)) {
    throw new Error('Connector minimum_recent_bars is invalid.');
  }
  const minimumRows = row.minimum_recent_bars as Record<string, unknown>;
  const intervals = row.supported_intervals as QuantConnectorInterval[];
  if (Object.keys(minimumRows).length !== intervals.length
    || intervals.some((interval) => !Number.isInteger(minimumRows[interval]) || Number(minimumRows[interval]) < 1)) {
    throw new Error('Connector minimum_recent_bars must cover every supported interval.');
  }
  if (!Number.isInteger(row.maximum_recent_bars) || Number(row.maximum_recent_bars) < Math.max(...intervals.map((interval) => Number(minimumRows[interval])))) {
    throw new Error('Connector maximum_recent_bars is invalid.');
  }
  if (row.data_authenticity !== 'generated') throw new Error('Connector data_authenticity must be generated.');
  if (row.fetch_endpoint !== expectedFetchPath) throw new Error('Connector fetch_endpoint does not match its connector identity.');
  return {
    id,
    provider: requiredConnectorText(row.provider, 'provider'),
    displayName: requiredConnectorText(row.display_name, 'display_name'),
    sourceKind: 'market_bars',
    supportedSymbols: [...row.supported_symbols] as string[],
    supportedIntervals: [...intervals],
    minimumRecentBars: Object.fromEntries(intervals.map((interval) => [interval, Number(minimumRows[interval])])) as Record<QuantConnectorInterval, number>,
    maximumRecentBars: Number(row.maximum_recent_bars),
    fetchPath: expectedFetchPath,
    version: requiredConnectorText(row.connector_version, 'connector_version'),
    sourceTermsUrl: requiredHttpsUrl(row.source_terms_url, 'source_terms_url'),
    sourceDocumentationUrl: requiredHttpsUrl(row.source_documentation_url, 'source_documentation_url'),
  };
}

export interface QuantNasdaqEquityFetchRequest {
  symbol?: string;
  lookbackDays?: number;
  idempotencyKey: string;
}

export interface QuantProjectCreateRequest {
  name: string;
  objective: string;
  idempotencyKey: string;
}

export interface QuantProjectCreateResult {
  id: string;
  rowVersion: number;
}

export interface QuantRunCreateRequest {
  projectId: string;
  mode: 'plan' | 'auto';
  question: string;
  expectedProjectRowVersion: number;
  datasetId: string;
  researchStart: string;
  researchEnd: string;
  parentRunId?: string;
  seedCandidateId?: string;
  refinementReason?: string;
  idempotencyKey: string;
}

export interface QuantRunCreateResult {
  id: string;
}

export interface QuantMarketRunCreateRequest {
  projectId: string;
  mode: 'plan' | 'auto';
  question: string;
  expectedProjectRowVersion: number;
  datasetId: string;
  researchStartUtc: string;
  researchEndUtc: string;
  parentRunId?: string;
  seedCandidateId?: string;
  refinementReason?: string;
  researchLoop?: {
    followUpMode: 'one_train_only_follow_up';
    maxVersions: 2;
    maxTotalExperiments: 6;
    maxTotalAgentActions: 24;
  };
  idempotencyKey: string;
}

export interface QuantProjectHistoryItem {
  id: string;
  name: string;
  objective: string;
  status: string;
  rowVersion: number;
  createdAt: string;
  updatedAt: string;
}

export interface QuantRunHistoryItem {
  contract: 'legacy-daily-v1' | 'market-v2-public';
  id: string;
  projectId: string;
  datasetId: string;
  state: string;
  mode: 'plan' | 'auto';
  question: string;
  attemptNumber: number;
  parentRunId: string | null;
  seedCandidateId: string | null;
  refinementReason: string | null;
  retryOfRunId: string | null;
  provider: string;
  model: string | null;
  usedExperiments: number;
  createdAt: string;
  updatedAt: string;
  symbol?: string;
  interval?: '1h' | '4h' | '1D';
  periodsPerYear?: number;
  researchStartUtc?: string;
  researchEndUtc?: string;
  datasetDigest?: string;
  runtimeDescriptorDigest?: string;
  sealedSplitDigest?: string;
}

export type QuantStrategyReportExportType = 'strategy_report_markdown' | 'strategy_evidence_bundle_json';

interface QuantStrategyReportExportBase {
  runId: string;
  candidateId: string;
  authenticity: QuantAuthenticity;
  filename: string;
  renderedContent: string;
  contentDigest: string;
}

export interface QuantStrategyReportMarkdownExport extends QuantStrategyReportExportBase {
  exportType: 'strategy_report_markdown';
  mediaType: 'text/markdown';
}

export interface QuantStrategyEvidenceBundleJsonExport extends QuantStrategyReportExportBase {
  exportType: 'strategy_evidence_bundle_json';
  mediaType: 'application/json';
}

export type QuantStrategyReportExport = QuantStrategyReportMarkdownExport | QuantStrategyEvidenceBundleJsonExport;

export function parseQuantStrategyReportExport(value: unknown): QuantStrategyReportExport {
  if (!value || typeof value !== 'object') throw new Error('Strategy report export response is invalid.');
  const row = value as Record<string, unknown>;
  const filename = row.filename;
  const content = row.rendered_content;
  const digest = row.content_digest;
  const runId = row.run_id;
  const candidateId = row.candidate_id;
  const authenticity = row.data_authenticity === 'generated' || row.data_authenticity === 'synthetic_fixture'
    ? 'synthetic_fixture'
    : row.data_authenticity === 'imported' || row.data_authenticity === 'collected'
      ? row.data_authenticity
      : null;
  const validFilename = typeof filename === 'string' && filename.length > 0 && filename.length <= 120;
  const sharedValid = typeof runId === 'string'
    && runId.length > 0
    && typeof candidateId === 'string'
    && candidateId.length > 0
    && validFilename
    && typeof content === 'string'
    && content.length > 0
    && typeof digest === 'string'
    && /^sha256:[0-9a-f]{64}$/.test(digest)
    && authenticity !== null;
  const renderedBytes = typeof content === 'string' ? new TextEncoder().encode(content).length : 0;
  const isMarkdown = row.export_type === 'strategy_report_markdown';
  const isJson = row.export_type === 'strategy_evidence_bundle_json';
  const validFormat = isMarkdown
    ? typeof filename === 'string'
      && /^[A-Za-z0-9][A-Za-z0-9._-]*\.md$/.test(filename)
      && row.media_type === 'text/markdown'
      && renderedBytes <= 262_144
    : isJson
      && typeof filename === 'string'
      && /^[A-Za-z0-9][A-Za-z0-9._-]*\.json$/.test(filename)
      && row.media_type === 'application/json'
      && renderedBytes <= 1_048_576;
  if (!sharedValid || !validFormat) {
    throw new Error('Strategy report export response is invalid.');
  }
  if (isMarkdown) {
    return {
      exportType: 'strategy_report_markdown',
      runId: runId as string,
      candidateId: candidateId as string,
      authenticity: authenticity as QuantAuthenticity,
      filename: filename as string,
      mediaType: 'text/markdown',
      renderedContent: content as string,
      contentDigest: digest as string,
    };
  }
  return {
    exportType: 'strategy_evidence_bundle_json',
    runId: runId as string,
    candidateId: candidateId as string,
    authenticity: authenticity as QuantAuthenticity,
    filename: filename as string,
    mediaType: 'application/json',
    renderedContent: content as string,
    contentDigest: digest as string,
  };
}

export interface QuantApi {
  getWorkspaceSnapshot(): Promise<QuantWorkspaceSnapshot>;
  sendCommand(request: QuantCommandRequest): Promise<QuantCommandReceipt>;
  createProject(request: QuantProjectCreateRequest): Promise<QuantProjectCreateResult>;
  createRun(request: QuantRunCreateRequest): Promise<QuantRunCreateResult>;
  createMarketRun(request: QuantMarketRunCreateRequest): Promise<QuantMarketRunRecord>;
  listProjects(): Promise<QuantProjectHistoryItem[]>;
  listRuns(projectId?: string): Promise<QuantRunHistoryItem[]>;
  listMarketRuns(projectId?: string): Promise<QuantRunHistoryItem[]>;
  getRunWorkspaceSnapshot(runId: string): Promise<QuantWorkspaceSnapshot>;
  previewStrategyReportExport(runId: string, candidateId: string, exportType: QuantStrategyReportExportType): Promise<QuantStrategyReportExport>;
  listDatasets(): Promise<DatasetSnapshot[]>;
  listMarketDatasets(): Promise<DatasetSnapshot[]>;
  getDatasetPreview(datasetId: string): Promise<QuantDatasetPreview>;
  getMarketDatasetPreview(datasetId: string): Promise<QuantDatasetPreview>;
  importDatasetCsv(request: QuantDatasetImportRequest): Promise<DatasetSnapshot>;
  importMarketDatasetCsv(request: QuantMarketDatasetImportRequest): Promise<DatasetSnapshot>;
  fetchBinanceSpotDataset(request: QuantBinanceSpotFetchRequest): Promise<DatasetSnapshot>;
  fetchMarketBinanceDataset(request: QuantMarketBinanceFetchRequest): Promise<DatasetSnapshot>;
  listConnectors(): Promise<QuantMarketDataConnector[]>;
  fetchConnectorDataset(request: QuantConnectorFetchRequest): Promise<DatasetSnapshot>;
  fetchNasdaqEquityDataset(request: QuantNasdaqEquityFetchRequest): Promise<DatasetSnapshot>;
  getPaperSnapshot(): Promise<PaperSnapshot>;
  createPaperDraft(request: PaperDraftRequest): Promise<PaperOrder>;
  submitPaperOrder(orderId: string, orderVersion: number, accountVersion: number, idempotencyKey: string): Promise<PaperOrder>;
  cancelPaperOrder(orderId: string, orderVersion: number, idempotencyKey: string): Promise<PaperOrder>;
  reconcilePaperAccount(accountVersion: number, idempotencyKey: string): Promise<PaperSnapshot>;
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
  created_at?: string;
  source_metadata: {
    kind: 'csv_upload' | 'provider_fetch';
    file_name?: string | null;
    source_name?: string;
    source_reference?: string | null;
    submitted_csv_digest?: string | null;
    market_calendar?: 'unknown' | 'weekday' | '24x7' | 'XNYS' | 'XNAS' | 'XSHG' | 'XSHE';
    time_zone?: string;
    price_adjustment?: 'unknown' | 'unadjusted' | 'split_adjusted' | 'total_return_adjusted';
    provider_id?: string;
    provider_response_digest?: string;
    provider_response_attestations?: Array<{ kind: string; digest: string; source_reference: string }>;
    retrieved_at?: string;
    requested_limit?: number;
    returned_bar_count?: number;
    dropped_incomplete_count?: number;
    normalization_note?: string;
    attestation_status?: string;
    corporate_actions_attestation?: {
      dividends_status: string;
      splits_status: string;
      coverage_start: string | null;
      coverage_end: string | null;
      dividend_coverage_start?: string | null;
      dividend_coverage_end?: string | null;
      split_coverage_start?: string | null;
      split_coverage_end?: string | null;
      split_snapshot_as_of?: string | null;
      split_completeness_status?: string;
      split_reconciliation_status?: string;
      split_events?: Array<{ effective_date: string; ratio_numerator: number; ratio_denominator: number }>;
      dividend_event_count: number | null;
      split_event_count: number | null;
      note: string;
    };
    price_adjustment_verification_status?: string;
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
  const source = dto.source_metadata.kind === 'provider_fetch'
    ? {
      kind: 'provider_fetch' as const,
      sourceName: dto.source_metadata.source_name ?? 'Provider market data',
      sourceReference: dto.source_metadata.source_reference ?? null,
      submittedCsvDigest: dto.source_metadata.submitted_csv_digest ?? null,
      marketCalendar: dto.source_metadata.market_calendar ?? 'unknown',
      timeZone: dto.source_metadata.time_zone ?? 'UTC',
      priceAdjustment: dto.source_metadata.price_adjustment ?? 'unknown',
      providerId: dto.source_metadata.provider_id ?? 'unknown_provider',
      providerResponseAttestations: (dto.source_metadata.provider_response_attestations
        ?? (dto.source_metadata.provider_response_digest ? [{ kind: 'provider_response', digest: dto.source_metadata.provider_response_digest, source_reference: dto.source_metadata.source_reference ?? '' }] : [])
      ).map((item) => ({ kind: item.kind, digest: item.digest, sourceReference: item.source_reference })),
      retrievedAt: dto.source_metadata.retrieved_at ?? '',
      requestedLimit: dto.source_metadata.requested_limit ?? 0,
      returnedBarCount: dto.source_metadata.returned_bar_count ?? dto.bar_count,
      droppedIncompleteCount: dto.source_metadata.dropped_incomplete_count ?? 0,
      normalizationNote: dto.source_metadata.normalization_note ?? 'No provider normalization note was retained.',
      attestationStatus: dto.source_metadata.attestation_status ?? 'unavailable',
      priceAdjustmentVerificationStatus: dto.source_metadata.price_adjustment_verification_status,
      corporateActionsAttestation: dto.source_metadata.corporate_actions_attestation
        ? {
          dividendsStatus: dto.source_metadata.corporate_actions_attestation.dividends_status,
          splitsStatus: dto.source_metadata.corporate_actions_attestation.splits_status,
          coverageStart: dto.source_metadata.corporate_actions_attestation.coverage_start,
          coverageEnd: dto.source_metadata.corporate_actions_attestation.coverage_end,
          dividendCoverageStart: dto.source_metadata.corporate_actions_attestation.dividend_coverage_start
            ?? dto.source_metadata.corporate_actions_attestation.coverage_start,
          dividendCoverageEnd: dto.source_metadata.corporate_actions_attestation.dividend_coverage_end
            ?? dto.source_metadata.corporate_actions_attestation.coverage_end,
          splitCoverageStart: dto.source_metadata.corporate_actions_attestation.split_coverage_start
            ?? dto.source_metadata.corporate_actions_attestation.coverage_start,
          splitCoverageEnd: dto.source_metadata.corporate_actions_attestation.split_coverage_end
            ?? dto.source_metadata.corporate_actions_attestation.coverage_end,
          splitSnapshotAsOf: dto.source_metadata.corporate_actions_attestation.split_snapshot_as_of ?? null,
          splitCompletenessStatus: dto.source_metadata.corporate_actions_attestation.split_completeness_status,
          splitReconciliationStatus: dto.source_metadata.corporate_actions_attestation.split_reconciliation_status,
          splitEvents: dto.source_metadata.corporate_actions_attestation.split_events?.map((event) => ({
            effectiveDate: event.effective_date,
            ratioNumerator: event.ratio_numerator,
            ratioDenominator: event.ratio_denominator,
          })),
          dividendEventCount: dto.source_metadata.corporate_actions_attestation.dividend_event_count,
          splitEventCount: dto.source_metadata.corporate_actions_attestation.split_event_count,
          note: dto.source_metadata.corporate_actions_attestation.note,
        }
        : undefined,
    }
    : {
      kind: 'csv_upload' as const,
      fileName: dto.source_metadata.file_name ?? null,
      sourceName: dto.source_metadata.source_name ?? 'User-provided CSV',
      sourceReference: dto.source_metadata.source_reference ?? null,
      submittedCsvDigest: dto.source_metadata.submitted_csv_digest ?? null,
      marketCalendar: dto.source_metadata.market_calendar,
      timeZone: dto.source_metadata.time_zone,
      priceAdjustment: dto.source_metadata.price_adjustment ?? 'unknown',
    };
  return {
    contract: 'legacy-daily-v1',
    id: dto.dataset_id,
    name: dto.name,
    symbol: dto.symbol,
    interval: dto.interval,
    dateRange: { start: dto.covered_start, end: dto.covered_end },
    barCount: dto.bar_count,
    schemaVersion: dto.schema_version,
    parserVersion: dto.parser_version,
    digest: dto.digest,
    authenticity: dto.source_metadata.kind === 'provider_fetch' ? 'collected' : 'imported',
    researchEligible: dto.bar_count >= 252 && dto.data_quality?.status !== 'blocked',
    ...(dto.created_at ? { createdAt: dto.created_at } : {}),
    source,
    ...(dto.data_quality ? { quality: mapDatasetQuality(dto.data_quality) } : {}),
  };
}

function requiredHistoryText(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-empty string.`);
  return value;
}

function nullableHistoryText(value: unknown, field: string): string | null {
  if (value === null) return null;
  return requiredHistoryText(value, field);
}

function parseLegacyHistoryLineage(row: Record<string, unknown>): Pick<QuantRunHistoryItem, 'parentRunId' | 'seedCandidateId' | 'refinementReason'> {
  const fields = ['parent_run_id', 'seed_candidate_id', 'refinement_reason'] as const;
  const presentFields = fields.filter((field) => Object.prototype.hasOwnProperty.call(row, field));
  // A wholly absent trio is an older root-run response. Any partial modern
  // response is unsafe to project as a relationship and therefore rejects.
  if (presentFields.length === 0) return { parentRunId: null, seedCandidateId: null, refinementReason: null };
  if (presentFields.length !== fields.length) throw new Error('Legacy run continuation lineage must be supplied together.');
  const parentRunId = nullableHistoryText(row.parent_run_id, 'parent_run_id');
  const seedCandidateId = nullableHistoryText(row.seed_candidate_id, 'seed_candidate_id');
  const refinementReason = nullableHistoryText(row.refinement_reason, 'refinement_reason');
  const lineage = [parentRunId, seedCandidateId, refinementReason];
  if (lineage.some((field) => field !== null) && !lineage.every((field) => field !== null)) {
    throw new Error('Legacy run continuation lineage must be supplied together.');
  }
  if (refinementReason !== null && refinementReason !== refinementReason.trim()) {
    throw new Error('Legacy run refinement_reason must be trimmed.');
  }
  return { parentRunId, seedCandidateId, refinementReason };
}

function parseLegacyRunHistoryItem(value: unknown): QuantRunHistoryItem {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Run history item must be an object.');
  const row = value as Record<string, unknown>;
  if (row.mode !== 'plan' && row.mode !== 'auto') throw new Error('mode is unsupported.');
  if (!Number.isInteger(row.attempt_number) || Number(row.attempt_number) < 1) throw new Error('attempt_number must be a positive integer.');
  if (!Number.isInteger(row.used_experiments) || Number(row.used_experiments) < 0) throw new Error('used_experiments must be a non-negative integer.');
  if (row.model !== null && typeof row.model !== 'string') throw new Error('model must be a string or null.');
  const lineage = parseLegacyHistoryLineage(row);
  return {
    contract: 'legacy-daily-v1',
    id: requiredHistoryText(row.id, 'id'),
    projectId: requiredHistoryText(row.project_id, 'project_id'),
    datasetId: requiredHistoryText(row.dataset_id, 'dataset_id'),
    state: requiredHistoryText(row.state, 'state'),
    mode: row.mode,
    question: requiredHistoryText(row.question, 'question'),
    attemptNumber: Number(row.attempt_number),
    ...lineage,
    retryOfRunId: nullableHistoryText(row.retry_of_run_id, 'retry_of_run_id'),
    provider: requiredHistoryText(row.provider, 'provider'),
    model: row.model,
    usedExperiments: Number(row.used_experiments),
    createdAt: requiredHistoryText(row.created_at, 'created_at'),
    updatedAt: requiredHistoryText(row.updated_at, 'updated_at'),
  };
}

/**
 * Offline/test adapter seam. The production HTTP adapter is defined below.
 * This fixture adapter never changes run state; lifecycle transitions remain
 * API-owned.
 */
export function createFixtureQuantApi(): QuantApi {
  const now = new Date().toISOString();
  const fixturePaper: PaperSnapshot = {
    contractVersion: 'qurio-paper-v1',
    environment: 'paper',
    account: {
      accountId: '00000000-0000-4000-8000-000000000901',
      environment: 'paper',
      broker: 'local_simulator',
      currency: 'USD',
      status: 'active',
      cash: '100000.00',
      buyingPower: '100000.00',
      equity: '100000.00',
      rowVersion: 1,
      lastReconciledAt: null,
      updatedAt: now,
    },
    positions: [],
    orders: [],
    fills: [],
    generatedAt: now,
  };
  return {
    async getWorkspaceSnapshot() { return quantFixtureSnapshot; },
    async sendCommand(request) {
      const snapshot = quantFixtureSnapshot;
      const legal = snapshot.run.legalCommands.includes(request.command) || snapshot.composerLegalCommands.includes(request.command);
      return legal
        ? { status: 'fixture_only', message: 'Quant API adapter stub received the legal command. No run-state transition is applied by the frontend fixture.' }
        : { status: 'rejected', message: 'This command is not legal for the current API fixture snapshot.' };
    },
    async createProject() { return { id: 'fixture-quant-project', rowVersion: 1 }; },
    async createRun() { return { id: 'fixture-quant-run' }; },
    async createMarketRun() { throw new Error('Market Run creation requires the authenticated Quant API.'); },
    async listProjects() { return [{ id: quantFixtureSnapshot.project.id, name: quantFixtureSnapshot.project.title, objective: quantFixtureSnapshot.project.goal, status: 'active', rowVersion: 1, createdAt: quantFixtureSnapshot.project.updatedAt, updatedAt: quantFixtureSnapshot.project.updatedAt }]; },
    async listRuns() { return [{ contract: 'legacy-daily-v1', id: quantFixtureSnapshot.run.id, projectId: quantFixtureSnapshot.project.id, datasetId: quantFixtureSnapshot.dataset.id, state: quantFixtureSnapshot.run.state, mode: quantFixtureSnapshot.run.mode === 'auto_research' ? 'auto' : 'plan', question: quantFixtureSnapshot.project.goal, attemptNumber: quantFixtureSnapshot.run.attemptNumber, parentRunId: quantFixtureSnapshot.run.continuedFrom?.parentRunId ?? null, seedCandidateId: quantFixtureSnapshot.run.continuedFrom?.seedCandidateId ?? null, refinementReason: quantFixtureSnapshot.run.continuedFrom?.reason ?? null, retryOfRunId: quantFixtureSnapshot.run.retryOfRunId ?? null, provider: quantFixtureSnapshot.run.provider, model: quantFixtureSnapshot.run.model, usedExperiments: quantFixtureSnapshot.run.usedExperiments, createdAt: quantFixtureSnapshot.run.startedAt, updatedAt: quantFixtureSnapshot.run.completedAt ?? quantFixtureSnapshot.run.startedAt }]; },
    async listMarketRuns() { return []; },
    async getRunWorkspaceSnapshot() { return quantFixtureSnapshot; },
    async previewStrategyReportExport() {
      throw new Error('Strategy report export requires the authenticated Quant API.');
    },
    async listDatasets() { return [quantFixtureSnapshot.dataset]; },
    async listMarketDatasets() { return []; },
    async getDatasetPreview(datasetId) {
      if (datasetId !== quantFixtureSnapshot.dataset.id) throw new Error('Fixture dataset preview was not found.');
      return { contract: quantFixtureSnapshot.dataset.contract, datasetId, symbol: quantFixtureSnapshot.dataset.symbol, interval: quantFixtureSnapshot.dataset.interval, authenticity: quantFixtureSnapshot.dataset.authenticity, coveredStart: quantFixtureSnapshot.dataset.dateRange.start, coveredEnd: quantFixtureSnapshot.dataset.dateRange.end, totalBarCount: quantFixtureSnapshot.dataset.barCount, returnedBarCount: quantFixtureSnapshot.bars.length, maxPoints: 240, samplingRule: 'latest_contiguous', bars: quantFixtureSnapshot.bars };
    },
    async getMarketDatasetPreview() { throw new Error('Market dataset preview requires the authenticated Quant API.'); },
    async importDatasetCsv() {
      throw new Error('CSV import requires the authenticated Quant API.');
    },
    async importMarketDatasetCsv() {
      throw new Error('Market-bar CSV import requires the authenticated Quant API.');
    },
    async fetchBinanceSpotDataset() {
      throw new Error('Binance Spot fetch requires the authenticated Quant API.');
    },
    async fetchMarketBinanceDataset() {
      throw new Error('Market-bar Binance fetch requires the authenticated Quant API.');
    },
    async listConnectors() { return []; },
    async fetchConnectorDataset() {
      throw new Error('Connector fetch requires the authenticated Quant API.');
    },
    async fetchNasdaqEquityDataset() {
      throw new Error('Nasdaq Equity fetch requires the authenticated Quant API.');
    },
    async getPaperSnapshot() { return structuredClone(fixturePaper); },
    async createPaperDraft(request) {
      const price = String(quantFixtureSnapshot.bars.at(-1)?.close ?? 100);
      const createdAt = new Date().toISOString();
      const order: PaperOrder = {
        orderId: quantIdempotencyKey(), state: 'draft', sourceRunId: request.sourceRunId,
        sourceCandidateId: request.sourceCandidateId, sourceEvidenceDigest: `sha256:${'0'.repeat(64)}`,
        symbol: quantFixtureSnapshot.scope.symbol, side: request.side, quantity: request.quantity,
        filledQuantity: '0', orderType: request.orderType, timeInForce: request.timeInForce,
        limitPrice: null, referencePrice: price,
        estimatedNotional: (Number(request.quantity) * Number(price)).toFixed(2),
        averageFillPrice: null, rowVersion: 1, createdAt, updatedAt: createdAt,
      };
      fixturePaper.orders.unshift(order);
      return structuredClone(order);
    },
    async submitPaperOrder(orderId, orderVersion, accountVersion) {
      const order = fixturePaper.orders.find((item) => item.orderId === orderId);
      if (!order || order.state !== 'draft' || order.rowVersion !== orderVersion || fixturePaper.account.rowVersion !== accountVersion) {
        throw new Error('The Paper order changed; refresh before submitting.');
      }
      order.state = 'filled';
      order.filledQuantity = order.quantity;
      order.averageFillPrice = order.limitPrice ?? order.referencePrice;
      order.rowVersion += 1;
      order.updatedAt = new Date().toISOString();
      fixturePaper.account.rowVersion += 1;
      return structuredClone(order);
    },
    async cancelPaperOrder(orderId, orderVersion) {
      const order = fixturePaper.orders.find((item) => item.orderId === orderId);
      if (!order || order.state !== 'draft' || order.rowVersion !== orderVersion) throw new Error('Only a current draft can be cancelled.');
      order.state = 'cancelled';
      order.rowVersion += 1;
      order.updatedAt = new Date().toISOString();
      return structuredClone(order);
    },
    async reconcilePaperAccount(accountVersion) {
      if (fixturePaper.account.rowVersion !== accountVersion) throw new Error('The Paper account changed; refresh before reconciling.');
      fixturePaper.account.rowVersion += 1;
      fixturePaper.account.lastReconciledAt = new Date().toISOString();
      return structuredClone(fixturePaper);
    },
  };
}

/** Build the production Mac adapter on top of the authenticated Glint session. */
export function createApiQuantApi(api: GlintApi): QuantApi {
  const quantRequest = api.quantRequest?.bind(api);
  if (!quantRequest) throw new Error('The authenticated API does not expose the Quant transport.');
  const paperRequest = api.paperRequest?.bind(api);
  const publicMarketCommands: ReadonlySet<QuantCommand> = new Set([
    'approve_plan',
    'request_plan_changes',
    'cancel_run',
    'retry_run',
  ]);
  const retainPublicMarketCommands = (snapshot: QuantWorkspaceSnapshot): QuantCommand[] => {
    const unsupported = snapshot.researchPlan?.strategyScope?.status === 'unsupported';
    return snapshot.run.legalCommands.filter((command) => (
      publicMarketCommands.has(command)
      && (!unsupported || command === 'request_plan_changes' || command === 'cancel_run')
    ));
  };
  const sameUtcInstant = (left: string, right: string): boolean => {
    const leftTime = Date.parse(left);
    const rightTime = Date.parse(right);
    return Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime === rightTime;
  };
  const hydrateSnapshotContract = async (raw: unknown): Promise<QuantWorkspaceSnapshot> => {
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(raw);
    if (!compatibility.supported) throw new QuantWorkspaceCompatibilityError(compatibility);
    const parsed = snapshot!;
    if (parsed.dataset.contract !== 'market-v2') return parsed;
    const rows = await quantRequest<unknown[]>('/quant/market-runs?limit=100');
    const marketRuns = rows.map(parseQuantMarketRun);
    const publicRun = marketRuns.find((run) => run.id === parsed.run.id);
    if (!publicRun) return parsed;
    if (publicRun.projectId !== parsed.project.id
      || publicRun.datasetId !== parsed.dataset.id
      || publicRun.datasetDigest !== parsed.dataset.digest
      || publicRun.symbol !== parsed.dataset.symbol
      || publicRun.interval !== parsed.dataset.interval
      || publicRun.periodsPerYear !== parsed.dataset.periodsPerYear
      || !sameUtcInstant(publicRun.researchStartUtc, parsed.dataset.dateRange.start)
      || !sameUtcInstant(publicRun.researchEndUtc, parsed.dataset.dateRange.end)
      || publicRun.runtimeDescriptorDigest !== parsed.dataset.runtimeDescriptorDigest
      || publicRun.sealedSplitDigest !== parsed.dataset.sealedSplitDigest
      || (publicRun.mode === 'auto' ? 'auto_research' : publicRun.mode) !== parsed.run.mode
      || publicRun.attemptNumber !== parsed.run.attemptNumber
      || publicRun.retryOfRunId !== (parsed.run.retryOfRunId ?? null)
      || publicRun.parentRunId !== (parsed.run.continuedFrom?.parentRunId ?? null)
      || publicRun.seedCandidateId !== (parsed.run.continuedFrom?.seedCandidateId ?? null)
      || publicRun.refinementReason !== (parsed.run.continuedFrom?.reason ?? null)) {
      throw new Error('Market Run identity differs from its workspace snapshot.');
    }
    parsed.run.contract = 'market-v2-public';
    parsed.run.planRevision = publicRun.planRevision;
    parsed.run.legalCommands = retainPublicMarketCommands(parsed);
    return parsed;
  };
  return {
    async getWorkspaceSnapshot() {
      const controller = new AbortController();
      const timeout = globalThis.setTimeout(() => controller.abort(), QUANT_WORKSPACE_REQUEST_TIMEOUT_MS);
      let raw: unknown;
      try {
        raw = await quantRequest<unknown>('/quant/workspace-snapshot', { signal: controller.signal });
      } catch (reason) {
        if (controller.signal.aborted) throw new Error('Workspace snapshot request timed out.');
        throw reason;
      } finally {
        globalThis.clearTimeout(timeout);
      }
      return hydrateSnapshotContract(raw);
    },
    async sendCommand(request) {
      const supported: ReadonlySet<QuantCommand> = new Set(['ask', 'generate_plan', 'start_auto_research', 'approve_plan', 'run_fixture', 'request_plan_changes', 'cancel_run', 'retry_run', 'complete_review']);
      if (!supported.has(request.command)) return { status: 'rejected', message: 'The server snapshot did not expose a supported lifecycle command.' };
      if (request.run?.contract === 'market-v2-private') return { status: 'rejected', message: 'This retained market run is read-only.' };
      if (request.run?.contract === 'market-v2-public') {
        if (!['approve_plan', 'request_plan_changes', 'cancel_run', 'retry_run'].includes(request.command)) return { status: 'rejected', message: 'This command is not part of the public Market Run contract.' };
        const action = request.command === 'approve_plan' ? 'approve-plan' : request.command === 'request_plan_changes' ? 'request-plan-changes' : request.command === 'cancel_run' ? 'cancel' : 'retry';
        const body = request.command === 'approve_plan'
          ? { expected_row_version: request.expectedVersion, plan_revision: request.run.planRevision, reason: 'Plan approved from the research workspace.' }
          : request.command === 'request_plan_changes'
            ? { expected_row_version: request.expectedVersion, plan_revision: request.run.planRevision, change_request: String(request.payload?.changeRequest ?? 'Revise the plan before running experiments.') }
            : { expected_row_version: request.expectedVersion, reason: request.command === 'cancel_run' ? 'Cancelled from the research workspace.' : 'Retry requested from the research workspace.' };
        if ((request.command === 'approve_plan' || request.command === 'request_plan_changes') && !request.run.planRevision) throw new Error('The Market Run plan revision is unavailable. Refresh before submitting this action.');
        const response = parseQuantMarketRun(await quantRequest(`/quant/market-runs/${encodeURIComponent(request.run.id)}/${action}`, {
          method: 'POST', headers: { 'Idempotency-Key': request.idempotencyKey }, body: JSON.stringify(body),
        }));
        if (request.command !== 'retry_run' && response.id !== request.run.id) throw new Error('Market Run mutation returned a different run identity.');
        return { status: 'accepted', message: request.command === 'retry_run' ? 'A clean Market Run attempt was created.' : 'Market Run action accepted; refreshing the authoritative snapshot.' };
      }
      await quantRequest('/quant/workspace-snapshot/commands', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({ command: request.command, expected_row_version: request.expectedVersion, payload: request.payload ?? {} }),
      });
      return { status: 'accepted', message: 'Command accepted by the API; refreshing the authoritative snapshot.' };
    },
    async createProject(request) {
      const row = await quantRequest<{ id: string; row_version: number }>('/quant/projects', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({ name: request.name, objective: request.objective }),
      });
      return { id: row.id, rowVersion: row.row_version };
    },
    async createRun(request) {
      const lineage = [request.parentRunId, request.seedCandidateId, request.refinementReason];
      if (lineage.some((value) => value !== undefined) && (!request.parentRunId || !request.seedCandidateId || !request.refinementReason?.trim())) {
        throw new Error('A continuation requires parent run, source candidate, and a non-empty refinement reason.');
      }
      const row = await quantRequest<{ id: string }>('/quant/runs', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          project_id: request.projectId,
          mode: request.mode,
          question: request.question,
          expected_project_row_version: request.expectedProjectRowVersion,
          dataset_id: request.datasetId,
          research_start: request.researchStart,
          research_end: request.researchEnd,
          ...(request.parentRunId && request.seedCandidateId && request.refinementReason?.trim() ? {
            parent_run_id: request.parentRunId,
            seed_candidate_id: request.seedCandidateId,
            refinement_reason: request.refinementReason.trim(),
          } : {}),
        }),
      });
      return { id: row.id };
    },
    async createMarketRun(request) {
      const lineage = [request.parentRunId, request.seedCandidateId, request.refinementReason];
      if (lineage.some((value) => value !== undefined) && (!request.parentRunId || !request.seedCandidateId || !request.refinementReason?.trim())) {
        throw new Error('A continuation requires parent run, source candidate, and a non-empty refinement reason.');
      }
      if (request.researchLoop && (request.mode !== 'auto' || request.parentRunId)) {
        throw new Error('A research loop can be enabled only on a root Auto Research run.');
      }
      const row = await quantRequest<unknown>('/quant/market-runs', {
        method: 'POST', headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          project_id: request.projectId,
          mode: request.mode,
          question: request.question,
          expected_project_row_version: request.expectedProjectRowVersion,
          dataset_id: request.datasetId,
          research_start_utc: request.researchStartUtc,
          research_end_utc: request.researchEndUtc,
          ...(request.parentRunId && request.seedCandidateId && request.refinementReason?.trim() ? {
            parent_run_id: request.parentRunId,
            seed_candidate_id: request.seedCandidateId,
            refinement_reason: request.refinementReason.trim(),
          } : {}),
          ...(request.researchLoop ? {
            research_loop: {
              follow_up_mode: request.researchLoop.followUpMode,
              max_versions: request.researchLoop.maxVersions,
              max_total_experiments: request.researchLoop.maxTotalExperiments,
              max_total_agent_actions: request.researchLoop.maxTotalAgentActions,
            },
          } : {}),
        }),
      });
      return parseQuantMarketRun(row);
    },
    async listProjects() {
      const rows = await quantRequest<Array<{ id: string; name: string; objective: string; status: string; row_version: number; created_at: string; updated_at: string }>>('/quant/projects');
      return rows.map((row) => ({ id: row.id, name: row.name, objective: row.objective, status: row.status, rowVersion: row.row_version, createdAt: row.created_at, updatedAt: row.updated_at }));
    },
    async listRuns(projectId) {
      const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
      const rows = await quantRequest<unknown[]>(`/quant/runs${suffix}`);
      return rows.map(parseLegacyRunHistoryItem);
    },
    async listMarketRuns(projectId) {
      const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}&limit=100` : '?limit=100';
      const rows = await quantRequest<unknown[]>(`/quant/market-runs${suffix}`);
      return rows.map(parseQuantMarketRun).map((run) => ({ contract: run.contract, id: run.id, projectId: run.projectId, datasetId: run.datasetId, state: run.state, mode: run.mode, question: run.question, attemptNumber: run.attemptNumber, parentRunId: run.parentRunId, seedCandidateId: run.seedCandidateId, refinementReason: run.refinementReason, retryOfRunId: run.retryOfRunId, provider: run.provider, model: run.model, usedExperiments: run.usedExperiments, createdAt: run.createdAt, updatedAt: run.updatedAt, symbol: run.symbol, interval: run.interval, periodsPerYear: run.periodsPerYear, researchStartUtc: run.researchStartUtc, researchEndUtc: run.researchEndUtc, datasetDigest: run.datasetDigest, runtimeDescriptorDigest: run.runtimeDescriptorDigest, sealedSplitDigest: run.sealedSplitDigest }));
    },
    async getRunWorkspaceSnapshot(runId) {
      const raw = await quantRequest<unknown>(`/quant/runs/${encodeURIComponent(runId)}/workspace-snapshot`);
      const snapshot = await hydrateSnapshotContract(raw);
      if (snapshot.run.id !== runId) throw new Error('Historical Run snapshot identity differs from the requested Run.');
      return snapshot;
    },
    async previewStrategyReportExport(runId, candidateId, exportType) {
      const raw = await quantRequest<unknown>('/quant/strategy-report-exports/preview', {
        method: 'POST',
        headers: { 'Idempotency-Key': quantIdempotencyKey() },
        body: JSON.stringify({
          export_type: exportType,
          run_id: runId,
          candidate_id: candidateId,
        }),
      });
      return parseQuantStrategyReportExport(raw);
    },
    async listDatasets() {
      const rows = await quantRequest<QuantDatasetDto[]>('/quant/datasets');
      return rows.map(mapDataset);
    },
    async listMarketDatasets() {
      const rows = await quantRequest<unknown[]>('/quant/datasets/v2');
      return rows.map(parseQuantMarketDataset);
    },
    async getDatasetPreview(datasetId) {
      const raw = await quantRequest<unknown>(`/quant/datasets/${encodeURIComponent(datasetId)}/preview?max_points=240`);
      return parseQuantDatasetPreview(raw);
    },
    async getMarketDatasetPreview(datasetId) {
      const raw = await quantRequest<unknown>(`/quant/datasets/v2/${encodeURIComponent(datasetId)}/preview?max_points=240`);
      return parseQuantMarketDatasetPreview(raw);
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
    async importMarketDatasetCsv(request) {
      const row = await quantRequest<unknown>('/quant/datasets/v2/import-csv', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          name: request.name,
          symbol: request.symbol,
          interval: request.interval,
          market_calendar: request.marketCalendar ?? '24x7',
          csv_text: request.csvText,
          file_name: request.fileName,
          source_name: request.sourceName ?? 'User-provided CSV',
          source_reference: request.sourceReference,
        }),
      });
      return parseQuantMarketDataset(row);
    },
    async fetchBinanceSpotDataset(request) {
      const row = await quantRequest<QuantDatasetDto>('/quant/datasets/fetch-binance-spot', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          symbol: request.symbol?.trim().toUpperCase() || 'BTCUSDT',
          interval: '1d',
          limit: request.limit ?? 365,
        }),
      });
      return mapDataset(row);
    },
    async fetchMarketBinanceDataset(request) {
      const row = await quantRequest<unknown>('/quant/datasets/v2/fetch-binance', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          ...(request.name?.trim() ? { name: request.name.trim() } : {}),
          symbol: request.symbol?.trim().toUpperCase() || 'BTCUSDT',
          interval: request.interval,
          limit: request.limit ?? 365,
        }),
      });
      return parseQuantMarketDataset(row);
    },
    async listConnectors() {
      const rows = await quantRequest<unknown[]>('/quant/connectors');
      return rows.map(parseQuantMarketDataConnector);
    },
    async fetchConnectorDataset(request) {
      const row = await quantRequest<unknown>(`/quant/connectors/${encodeURIComponent(request.connectorId)}/fetch`, {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          ...(request.name?.trim() ? { name: request.name.trim() } : {}),
          symbol: request.symbol.trim().toUpperCase(),
          interval: request.interval,
          limit: request.limit,
        }),
      });
      return parseQuantMarketDataset(row);
    },
    async fetchNasdaqEquityDataset(request) {
      const row = await quantRequest<QuantDatasetDto>('/quant/datasets/fetch-nasdaq-equity', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          symbol: request.symbol?.trim().toUpperCase() || 'AAPL',
          lookback_days: request.lookbackDays ?? 730,
        }),
      });
      return mapDataset(row);
    },
    async getPaperSnapshot() {
      if (!paperRequest) throw new Error('The authenticated API does not expose the Paper transport.');
      return parsePaperSnapshot(await paperRequest<unknown>('/paper/snapshot'));
    },
    async createPaperDraft(request) {
      if (!paperRequest) throw new Error('The authenticated API does not expose the Paper transport.');
      return parsePaperOrder(await paperRequest<unknown>('/paper/orders/drafts', {
        method: 'POST',
        headers: { 'Idempotency-Key': request.idempotencyKey },
        body: JSON.stringify({
          source_run_id: request.sourceRunId,
          source_candidate_id: request.sourceCandidateId,
          side: request.side,
          quantity: request.quantity,
          order_type: request.orderType,
          time_in_force: request.timeInForce,
          expected_account_row_version: request.expectedAccountRowVersion,
        }),
      }));
    },
    async submitPaperOrder(orderId, orderVersion, accountVersion, idempotencyKey) {
      if (!paperRequest) throw new Error('The authenticated API does not expose the Paper transport.');
      return parsePaperOrder(await paperRequest<unknown>(`/paper/orders/${encodeURIComponent(orderId)}/submit`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({
          expected_order_row_version: orderVersion,
          expected_account_row_version: accountVersion,
        }),
      }));
    },
    async cancelPaperOrder(orderId, orderVersion, idempotencyKey) {
      if (!paperRequest) throw new Error('The authenticated API does not expose the Paper transport.');
      return parsePaperOrder(await paperRequest<unknown>(`/paper/orders/${encodeURIComponent(orderId)}/cancel`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ expected_order_row_version: orderVersion }),
      }));
    },
    async reconcilePaperAccount(accountVersion, idempotencyKey) {
      if (!paperRequest) throw new Error('The authenticated API does not expose the Paper transport.');
      return parsePaperSnapshot(await paperRequest<unknown>('/paper/reconcile', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ expected_account_row_version: accountVersion }),
      }));
    },
  };
}
