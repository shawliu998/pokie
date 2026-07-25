import type {
  MarketBar,
  QuantAuthenticity,
  QuantBarInterval,
  QuantDatasetPreview,
  QuantMarketDatasetSnapshot,
  QuantRunState,
} from './quant-domain';

const DIGEST = /^sha256:[0-9a-f]{64}$/;
const UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/;
const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/;
const INTERVALS: ReadonlySet<string> = new Set(['1h', '4h', '1D']);
const RUN_STATES: ReadonlySet<string> = new Set([
  'draft', 'planning', 'waiting_plan_approval', 'queued', 'loading_data', 'generating_candidates',
  'running_experiments', 'repairing', 'validating', 'generating_report', 'waiting_for_review',
  'completed', 'failed', 'cancelled',
]);
type MarketCalendar = QuantMarketDatasetSnapshot['marketCalendar'];
type MarketSession = QuantMarketDatasetSnapshot['marketSession'];

const EXCHANGE_TIME_ZONES: Partial<Record<MarketCalendar, string>> = {
  '24x7': 'UTC',
  XNYS: 'America/New_York',
  XNAS: 'America/New_York',
  XSHG: 'Asia/Shanghai',
  XSHE: 'Asia/Shanghai',
};

function row(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object.`);
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${label} must be a non-empty string.`);
  return value;
}

function optionalText(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  return text(value, label);
}

function nullableText(value: unknown, label: string): string | null {
  if (value === null) return null;
  return text(value, label);
}

function integer(value: unknown, label: string, minimum = 0): number {
  if (!Number.isInteger(value) || Number(value) < minimum) throw new Error(`${label} must be an integer of at least ${minimum}.`);
  return Number(value);
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') throw new Error(`${label} must be a boolean.`);
  return value;
}

function digest(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!DIGEST.test(parsed)) throw new Error(`${label} must be a SHA-256 digest.`);
  return parsed;
}

function utc(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!UTC_TIMESTAMP.test(parsed) || Number.isNaN(Date.parse(parsed))) throw new Error(`${label} must be an RFC3339 UTC timestamp.`);
  return parsed;
}

function interval(value: unknown, label: string): QuantBarInterval {
  if (typeof value !== 'string' || !INTERVALS.has(value)) throw new Error(`${label} is unsupported.`);
  return value as QuantBarInterval;
}

function authenticity(value: unknown, label: string): QuantAuthenticity {
  if (value !== 'synthetic_fixture' && value !== 'imported' && value !== 'collected') throw new Error(`${label} is unsupported.`);
  return value;
}

function decimal(value: unknown, label: string, allowZero: boolean): { wire: string; numeric: number } {
  const wire = typeof value === 'string' ? value : '';
  if (!DECIMAL.test(wire)) throw new Error(`${label} must be a finite non-negative decimal.`);
  const numeric = Number(wire);
  if (!Number.isFinite(numeric) || numeric < 0 || (!allowZero && numeric === 0)) throw new Error(`${label} is outside the supported chart range.`);
  return { wire, numeric };
}

function validIanaTimeZone(value: string): boolean {
  try {
    new Intl.DateTimeFormat('en', { timeZone: value }).format(0);
    return true;
  } catch {
    return false;
  }
}

export function assertQuantMarketDatasetCadence({ intervalValue, periodsPerYear, calendar, session, timeZone, researchEligible }: {
  intervalValue: QuantBarInterval;
  periodsPerYear: number | null;
  calendar: MarketCalendar;
  session: MarketSession;
  timeZone: string;
  researchEligible: boolean;
}): void {
  if (!validIanaTimeZone(timeZone)) throw new Error('time_zone must be a valid IANA time zone.');
  if (calendar === 'unknown') {
    if (intervalValue !== '1D' || session !== 'unknown' || periodsPerYear !== null || researchEligible) throw new Error('unknown calendar requires an ineligible 1D dataset, unknown session, and no annualization.');
    return;
  }
  if (calendar === '24x7') {
    const expected = intervalValue === '1h' ? 8760 : intervalValue === '4h' ? 2190 : 365;
    if (session !== 'continuous' || timeZone !== 'UTC' || periodsPerYear !== expected) throw new Error(`24x7 ${intervalValue} requires continuous UTC data and periods_per_year=${expected}.`);
    return;
  }
  if (intervalValue !== '1D' || session !== 'regular' || periodsPerYear !== 252) throw new Error(`${calendar} currently requires regular-session 1D data and periods_per_year=252.`);
  const requiredTimeZone = EXCHANGE_TIME_ZONES[calendar];
  if (requiredTimeZone && timeZone !== requiredTimeZone) throw new Error(`${calendar} requires time_zone=${requiredTimeZone}.`);
}

function validateRunCadence(intervalValue: QuantBarInterval, periodsPerYear: number | null, eligible: boolean) {
  if (periodsPerYear === null) {
    if (eligible) throw new Error('A research-eligible market dataset requires periods_per_year.');
    return;
  }
  const allowed = intervalValue === '1h' ? [8760] : intervalValue === '4h' ? [2190] : [252, 365];
  if (!allowed.includes(periodsPerYear)) throw new Error('interval and periods_per_year are inconsistent.');
}

function parseEvidence(value: unknown) {
  const item = row(value, 'evidence');
  const kind = item.source_kind;
  if (kind !== 'provider_fetch' && kind !== 'csv_upload') throw new Error('evidence.source_kind is unsupported.');
  const normalizerVersion = text(item.normalizer_version, 'evidence.normalizer_version');
  const sourceName = text(item.source_name, 'evidence.source_name');
  const sourceReference = optionalText(item.source_reference, 'evidence.source_reference');
  const fileName = optionalText(item.file_name, 'evidence.file_name');
  if (fileName && /[/\\\0]/.test(fileName)) throw new Error('evidence.file_name must not be a path.');
  if (kind === 'provider_fetch') {
    if (!sourceReference || fileName !== null) throw new Error('Provider evidence is incomplete.');
    const retrievedAtUtc = utc(item.retrieved_at_utc, 'evidence.retrieved_at_utc');
    const requestedBarCount = integer(item.requested_bar_count, 'evidence.requested_bar_count', 1);
    const returnedBarCount = integer(item.returned_bar_count, 'evidence.returned_bar_count');
    const retainedBarCount = integer(item.retained_bar_count, 'evidence.retained_bar_count');
    const closedDroppedCount = integer(item.closed_dropped_count, 'evidence.closed_dropped_count');
    const deduplicatedCount = integer(item.deduplicated_count, 'evidence.deduplicated_count');
    const batchDigest = digest(item.batch_digest, 'evidence.batch_digest');
    const terminationReason = item.termination_reason;
    if (terminationReason !== 'requested_limit' && terminationReason !== 'history_exhausted' && terminationReason !== 'page_cap') throw new Error('evidence.termination_reason is unsupported.');
    return {
      kind, fileName: null, sourceName, sourceReference, normalizerVersion, retrievedAtUtc,
      requestedBarCount, returnedBarCount, retainedBarCount, closedDroppedCount, deduplicatedCount,
      terminationReason, targetSatisfied: boolean(item.target_satisfied, 'evidence.target_satisfied'), batchDigest,
    } as const;
  }
  if (item.submitted_csv_digest === undefined || item.submitted_csv_digest === null) throw new Error('CSV evidence requires submitted_csv_digest.');
  const submittedCsvDigest = digest(item.submitted_csv_digest, 'evidence.submitted_csv_digest');
  return {
    kind, fileName, sourceName, sourceReference, normalizerVersion, retrievedAtUtc: null,
    requestedBarCount: null, returnedBarCount: null, retainedBarCount: null, closedDroppedCount: null,
    deduplicatedCount: null, terminationReason: null, targetSatisfied: null, submittedCsvDigest,
  } as const;
}

export function parseQuantMarketDataset(value: unknown): QuantMarketDatasetSnapshot {
  const item = row(value, 'Market dataset');
  if (item.schema_version !== 'quant-market-bars-v2') throw new Error('Market dataset schema_version is unsupported.');
  const intervalValue = interval(item.interval, 'interval');
  const coveredStart = utc(item.covered_start, 'covered_start');
  const coveredEnd = utc(item.covered_end, 'covered_end');
  if (coveredStart > coveredEnd) throw new Error('Market dataset coverage is invalid.');
  const eligible = boolean(item.research_eligible, 'research_eligible');
  const periodsPerYear = item.periods_per_year === null ? null : integer(item.periods_per_year, 'periods_per_year', 1);
  validateRunCadence(intervalValue, periodsPerYear, eligible);
  const qualityRow = row(item.quality, 'quality');
  if (qualityRow.status !== 'accepted' && qualityRow.status !== 'blocked') throw new Error('quality.status is unsupported.');
  const cadenceGapCount = integer(qualityRow.cadence_gap_count, 'quality.cadence_gap_count');
  if ((cadenceGapCount > 0) !== (qualityRow.status === 'blocked')) throw new Error('quality status and cadence gaps are inconsistent.');
  if (eligible && qualityRow.status !== 'accepted') throw new Error('A blocked market dataset cannot be research eligible.');
  const marketCalendar = item.market_calendar;
  if (!['unknown', 'weekday', '24x7', 'XNYS', 'XNAS', 'XSHG', 'XSHE'].includes(String(marketCalendar))) throw new Error('market_calendar is unsupported.');
  const marketSession = item.market_session;
  if (!['unknown', 'continuous', 'regular'].includes(String(marketSession))) throw new Error('market_session is unsupported.');
  const timeZone = text(item.time_zone, 'time_zone');
  assertQuantMarketDatasetCadence({ intervalValue, periodsPerYear, calendar: marketCalendar as MarketCalendar, session: marketSession as MarketSession, timeZone, researchEligible: eligible });
  const evidence = parseEvidence(item.evidence);
  return {
    contract: 'market-v2',
    id: text(item.dataset_id, 'dataset_id'),
    name: text(item.name, 'name'),
    symbol: text(item.symbol, 'symbol'),
    interval: intervalValue,
    dateRange: { start: coveredStart, end: coveredEnd },
    barCount: integer(item.bar_count, 'bar_count', 1),
    schemaVersion: 'quant-market-bars-v2',
    parserVersion: evidence.normalizerVersion,
    digest: digest(item.digest, 'digest'),
    recordDigest: digest(item.record_digest, 'record_digest'),
    authenticity: authenticity(item.data_authenticity, 'data_authenticity'),
    researchEligible: eligible,
    createdAt: utc(item.created_at, 'created_at'),
    periodsPerYear,
    marketCalendar: marketCalendar as QuantMarketDatasetSnapshot['marketCalendar'],
    marketSession: marketSession as QuantMarketDatasetSnapshot['marketSession'],
    timeZone,
    source: evidence,
    quality: {
      status: qualityRow.status,
      cadenceGapCount,
      normalizationNote: text(qualityRow.normalization_note, 'quality.normalization_note'),
    },
  };
}

function parsePreviewBar(value: unknown, index: number): MarketBar {
  const item = row(value, `bars[${index}]`);
  const date = utc(item.timestamp, `bars[${index}].timestamp`);
  const open = decimal(item.open, `bars[${index}].open`, false);
  const high = decimal(item.high, `bars[${index}].high`, false);
  const low = decimal(item.low, `bars[${index}].low`, false);
  const close = decimal(item.close, `bars[${index}].close`, false);
  const volume = decimal(item.volume, `bars[${index}].volume`, true);
  if (high.numeric < Math.max(open.numeric, close.numeric) || low.numeric > Math.min(open.numeric, close.numeric)) throw new Error(`bars[${index}] has invalid OHLC bounds.`);
  return {
    date, open: open.numeric, high: high.numeric, low: low.numeric, close: close.numeric, volume: volume.numeric,
    decimalValues: { open: open.wire, high: high.wire, low: low.wire, close: close.wire, volume: volume.wire },
  };
}

export function parseQuantMarketDatasetPreview(value: unknown): QuantDatasetPreview {
  const item = row(value, 'Market dataset preview');
  const dataset = parseQuantMarketDataset(item.dataset);
  const previewAuthenticity = authenticity(item.data_authenticity, 'data_authenticity');
  if (previewAuthenticity !== dataset.authenticity) throw new Error('Market dataset preview authenticity differs from its dataset.');
  if (!Array.isArray(item.bars) || item.bars.length === 0) throw new Error('Market dataset preview bars must be a non-empty array.');
  const bars = item.bars.map(parsePreviewBar);
  const returnedBarCount = integer(item.returned_bar_count, 'returned_bar_count', 1);
  const maxPoints = integer(item.max_points, 'max_points', 1);
  const totalBarCount = integer(item.total_bar_count, 'total_bar_count', 1);
  if (item.sampling_rule !== 'latest_contiguous' || maxPoints > 400 || bars.length !== returnedBarCount || returnedBarCount > maxPoints) throw new Error('Market dataset preview bounds are invalid.');
  if (bars.some((bar, index) => index > 0 && bars[index - 1]!.date >= bar.date)) throw new Error('Market dataset preview timestamps must be strictly ordered.');
  return {
    contract: 'market-v2', datasetId: dataset.id, symbol: dataset.symbol, interval: dataset.interval,
    authenticity: previewAuthenticity,
    coveredStart: dataset.dateRange.start, coveredEnd: dataset.dateRange.end, totalBarCount,
    returnedBarCount, maxPoints, samplingRule: 'latest_contiguous', bars,
  };
}

export interface QuantMarketRunRecord {
  contract: 'market-v2-public';
  schemaVersion: 'quant-market-run-v2';
  id: string;
  rowVersion: number;
  projectId: string;
  datasetId: string;
  datasetDigest: string;
  symbol: string;
  interval: QuantBarInterval;
  periodsPerYear: number;
  researchStartUtc: string;
  researchEndUtc: string;
  runtimeDescriptorDigest: string;
  sealedSplitDigest: string;
  state: QuantRunState;
  mode: 'plan' | 'auto';
  question: string;
  planRevision: number;
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
  researchLoop: QuantResearchLoopPolicy | null;
  researchSeries: QuantResearchSeriesContext | null;
}

export interface QuantResearchLoopPolicy {
  followUpMode: 'stop_after_run' | 'one_train_only_follow_up';
  maxVersions: 1 | 2;
  maxTotalExperiments: 3 | 6;
  maxTotalAgentActions: 12 | 24;
}

export interface QuantResearchSeriesContext {
  rootRunId: string;
  currentRunId: string;
  versionNumber: 1 | 2;
  remainingVersions: 0 | 1;
  allowedActions: Array<'finish_without_follow_up' | 'precommit_one_refinement'>;
  blockingReasons: string[];
  ancestorCandidateKeys: string[];
  policyDigest: string;
}

function parseResearchLoop(value: unknown): QuantResearchLoopPolicy | null {
  if (value === null || value === undefined) return null;
  const item = row(value, 'research_loop');
  if (item.schema_version !== 'quant-research-loop-policy-v1' || item.automatic_retry !== false || item.decision_partition !== 'train' || item.descriptor_policy !== 'exact') throw new Error('research_loop policy is unsupported.');
  const followUpMode = item.follow_up_mode;
  const expected = followUpMode === 'stop_after_run' ? [1, 3, 12] : followUpMode === 'one_train_only_follow_up' ? [2, 6, 24] : null;
  if (!expected || item.max_versions !== expected[0] || item.max_total_experiments !== expected[1] || item.max_total_agent_actions !== expected[2]) throw new Error('research_loop budget is inconsistent.');
  return { followUpMode: followUpMode as QuantResearchLoopPolicy['followUpMode'], maxVersions: expected[0] as 1 | 2, maxTotalExperiments: expected[1] as 3 | 6, maxTotalAgentActions: expected[2] as 12 | 24 };
}

function parseResearchSeries(value: unknown): QuantResearchSeriesContext | null {
  if (value === null || value === undefined) return null;
  const item = row(value, 'research_series');
  if (item.schema_version !== 'quant-research-series-context-v1') throw new Error('research_series schema is unsupported.');
  const versionNumber = integer(item.version_number, 'research_series.version_number', 1);
  const remainingVersions = integer(item.remaining_versions, 'research_series.remaining_versions');
  if ((versionNumber !== 1 && versionNumber !== 2) || (remainingVersions !== 0 && remainingVersions !== 1)) throw new Error('research_series version budget is unsupported.');
  if (!Array.isArray(item.allowed_actions) || item.allowed_actions.length === 0 || item.allowed_actions.some((action) => action !== 'finish_without_follow_up' && action !== 'precommit_one_refinement')) throw new Error('research_series.allowed_actions is unsupported.');
  if (!Array.isArray(item.blocking_reasons) || !item.blocking_reasons.every((reason) => typeof reason === 'string' && Boolean(reason.trim()))) throw new Error('research_series.blocking_reasons is invalid.');
  if (!Array.isArray(item.ancestor_candidate_keys) || !item.ancestor_candidate_keys.every((key) => typeof key === 'string' && Boolean(key.trim()))) throw new Error('research_series.ancestor_candidate_keys is invalid.');
  return {
    rootRunId: text(item.root_run_id, 'research_series.root_run_id'),
    currentRunId: text(item.current_run_id, 'research_series.current_run_id'),
    versionNumber: versionNumber as 1 | 2,
    remainingVersions: remainingVersions as 0 | 1,
    allowedActions: item.allowed_actions,
    blockingReasons: item.blocking_reasons,
    ancestorCandidateKeys: item.ancestor_candidate_keys,
    policyDigest: digest(item.policy_digest, 'research_series.policy_digest'),
  };
}

export function parseQuantMarketRun(value: unknown): QuantMarketRunRecord {
  const item = row(value, 'Market run');
  if (item.schema_version !== 'quant-market-run-v2') throw new Error('Market run schema_version is unsupported.');
  const intervalValue = interval(item.interval, 'interval');
  const periodsPerYear = integer(item.periods_per_year, 'periods_per_year', 1);
  validateRunCadence(intervalValue, periodsPerYear, true);
  const state = item.state;
  if (typeof state !== 'string' || !RUN_STATES.has(state)) throw new Error('Market run state is unsupported.');
  if (item.mode !== 'plan' && item.mode !== 'auto') throw new Error('Market run mode is unsupported.');
  const start = utc(item.research_start_utc, 'research_start_utc');
  const end = utc(item.research_end_utc, 'research_end_utc');
  if (start > end) throw new Error('Market run research range is invalid.');
  const runId = text(item.id, 'id');
  const attemptNumber = integer(item.attempt_number, 'attempt_number', 1);
  const parentRunId = nullableText(item.parent_run_id, 'parent_run_id');
  const seedCandidateId = nullableText(item.seed_candidate_id, 'seed_candidate_id');
  const refinementReason = nullableText(item.refinement_reason, 'refinement_reason');
  const lineage = [parentRunId, seedCandidateId, refinementReason];
  if (lineage.some((field) => field !== null) && !lineage.every((field) => field !== null)) {
    throw new Error('Market run continuation lineage must be supplied together.');
  }
  if (refinementReason !== null && refinementReason !== refinementReason.trim()) {
    throw new Error('Market run refinement_reason must be trimmed.');
  }
  const researchLoop = parseResearchLoop(item.research_loop);
  const researchSeries = parseResearchSeries(item.research_series);
  if ((researchLoop === null) !== (researchSeries === null)) throw new Error('Market run research_loop and research_series must be supplied together.');
  if (researchSeries && (item.mode !== 'auto' || researchSeries.currentRunId !== runId)) throw new Error('Market run research_series identity is inconsistent.');
  if (researchLoop && researchSeries) {
    const mayRefine = researchSeries.allowedActions.includes('precommit_one_refinement');
    if (researchSeries.versionNumber === 2 && researchSeries.remainingVersions !== 0) throw new Error('Market run research_series version two has no remaining budget.');
    if (researchSeries.remainingVersions === 1 && (researchSeries.versionNumber !== 1 || researchLoop.maxVersions !== 2)) throw new Error('Market run research_series remaining budget is inconsistent.');
    const expectedRefine = researchLoop.followUpMode === 'one_train_only_follow_up' && researchSeries.remainingVersions === 1;
    if (!researchSeries.allowedActions.includes('finish_without_follow_up') || mayRefine !== expectedRefine) throw new Error('Market run research_series actions do not match its remaining budget.');
  }
  return {
    contract: 'market-v2-public', schemaVersion: 'quant-market-run-v2', id: runId,
    rowVersion: integer(item.row_version, 'row_version', 1), projectId: text(item.project_id, 'project_id'),
    datasetId: text(item.dataset_id, 'dataset_id'), datasetDigest: digest(item.dataset_digest, 'dataset_digest'),
    symbol: text(item.symbol, 'symbol'), interval: intervalValue, periodsPerYear,
    researchStartUtc: start, researchEndUtc: end,
    runtimeDescriptorDigest: digest(item.runtime_descriptor_digest, 'runtime_descriptor_digest'),
    sealedSplitDigest: digest(item.sealed_split_digest, 'sealed_split_digest'), state: state as QuantRunState,
    mode: item.mode, question: text(item.question, 'question'), planRevision: integer(item.plan_revision, 'plan_revision'),
    attemptNumber, parentRunId, seedCandidateId, refinementReason,
    retryOfRunId: nullableText(item.retry_of_run_id, 'retry_of_run_id'), provider: text(item.provider, 'provider'),
    model: optionalText(item.model, 'model'), usedExperiments: integer(item.used_experiments, 'used_experiments'),
    createdAt: utc(item.created_at, 'created_at'), updatedAt: utc(item.updated_at, 'updated_at'),
    researchLoop,
    researchSeries,
  };
}
