import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';

const PORT = Number(process.env.GLINT_FIXTURE_PORT ?? 4174);
const ACCESS_TOKEN = process.env.GLINT_FIXTURE_ACCESS_TOKEN_STDIN === '1'
  ? readFileSync(0, 'utf8')
  : (process.env.GLINT_FIXTURE_ACCESS_TOKEN ?? 'fixture-access-token');
const ALLOWED_ORIGIN = process.env.GLINT_FIXTURE_ALLOWED_ORIGIN ?? 'http://127.0.0.1:5173';
const QUANT_FAILURE = process.env.POKIEQUANT_E2E_FAILURE ?? null;
const QUANT_DELAY_MS = Number(process.env.POKIEQUANT_E2E_DELAY_MS ?? 0);
if (!Number.isInteger(QUANT_DELAY_MS) || QUANT_DELAY_MS < 0 || QUANT_DELAY_MS > 10_000) throw new Error('POKIEQUANT_E2E_DELAY_MS must be an integer from 0 to 10000.');
const QUANT_MUTATION_DELAY_MS = Number(process.env.POKIEQUANT_E2E_MUTATION_DELAY_MS ?? 0);
if (!Number.isInteger(QUANT_MUTATION_DELAY_MS) || QUANT_MUTATION_DELAY_MS < 0 || QUANT_MUTATION_DELAY_MS > 10_000) throw new Error('POKIEQUANT_E2E_MUTATION_DELAY_MS must be an integer from 0 to 10000.');
const QUANT_FAILURES = new Set(['rate-limit', 'provider-timeout']);
if (QUANT_FAILURE && !QUANT_FAILURES.has(QUANT_FAILURE)) throw new Error(`Unsupported POKIEQUANT_E2E_FAILURE: ${QUANT_FAILURE}`);
const QUANT_FIXTURES = JSON.parse(readFileSync(new URL('./fixtures/quant-workspace-fixtures.json', import.meta.url), 'utf8'));
const INITIAL_QUANT_FIXTURE_STATE = process.env.POKIEQUANT_E2E_RUN_STATE ?? 'quant-completed';
let quantFixtureState = INITIAL_QUANT_FIXTURE_STATE;
if (!(quantFixtureState in QUANT_FIXTURES)) throw new Error(`Unsupported POKIEQUANT_E2E_RUN_STATE: ${quantFixtureState}`);
let quantRowVersion = 8;
let quantGoal = QUANT_FIXTURES[quantFixtureState].project.goal;
let quantRunMode = QUANT_FIXTURES[quantFixtureState].run.mode;
let quantProjectRowVersion = 1;
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
const cloneFixtureValue = (value) => JSON.parse(JSON.stringify(value));
const state = { apiOffline: false, mutationRequestCount: 0, sseRequestCount: 0, offlineMutationRequestCount: 0, offlineSseRequestCount: 0, offlineExportRequestCount: 0, importState: 'none', importPayload: null, consentPreviewCount: 0, consentGrantAttempts: 0, consentGrantCount: 0, uploadCount: 0, signalTriaged: false, signalDisposition: null, signalTransitionCount: 0, investigationStatus: 'none', investigationRowVersion: 1, runState: 'none', runRowVersion: 1, latestSequence: 0, sseAttempt: 0, evidenceStatus: 'proposed', claimStatus: 'needs_review', synthesisStatus: 'none', synthesisRowVersion: 2, briefStatus: 'none', briefRowVersion: 1, briefVersion: 1, briefDocument: null, briefReadiness: 'draft', cloudSources: [], validationJobs: [], schedules: [], watchlistSourceIds: [ID.csvSource, ID.githubSource, ID.rssSource], watchlistRowVersion: 2, exportPostCount: 0, exportTerminalCount: 0, exportIdempotencyKeys: [], exportTimestamps: [], paperAccountVersion: 1, paperOrders: [], paperPositions: [], paperFills: [], paperReconciledAt: null };

const initialFixtureState = cloneFixtureValue(state);

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

function quantDatasetDto({ id, name, symbol, barCount, sourceMetadata, coveredStart = '2023-01-03', coveredEnd = '2024-12-31' }) {
  const datasetDigest = textDigest(`${id}:${symbol}:${barCount}`);
  return {
    dataset_id: id,
    name,
    symbol,
    interval: '1D',
    covered_start: coveredStart,
    covered_end: coveredEnd,
    bar_count: barCount,
    schema_version: 'quant-daily-bars-v1',
    parser_version: 'fixture-api-v1',
    digest: datasetDigest,
    source_metadata: sourceMetadata,
    data_quality: {
      schema_version: 'quant-data-quality-v1', policy_version: 'fixture-policy-v1', status: 'passed', verification_status: 'checked', report_digest: textDigest(`quality:${id}`), dataset_digest: datasetDigest, bar_count: barCount, calendar_gap_count: 0, largest_calendar_gap_days: 3, unexpected_session_count: 0, zero_volume_bar_count: 0, price_jump_count: 0, issues: [], notes: ['Deterministic API fixture dataset.'],
    },
    data_authenticity: 'imported',
    created_at: NOW,
  };
}

const quantPreviewBars = new Map();

function latestContiguousFixtureBars(symbol, endDate, count) {
  const dates = [];
  const cursor = new Date(`${endDate}T00:00:00Z`);
  while (dates.length < count) {
    if (cursor.getUTCDay() !== 0 && cursor.getUTCDay() !== 6) dates.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  dates.reverse();
  const base = symbol.includes('BTC') ? 42_000 : symbol === 'SPY' ? 390 : 120;
  return dates.map((date, index) => {
    const center = base * (1 + index * 0.0012 + Math.sin(index / 8) * 0.018);
    const open = center * (1 + Math.sin(index / 3) * 0.004);
    const close = center * (1 + Math.cos(index / 5) * 0.004);
    return { date, open: Number(open.toFixed(2)), high: Number((Math.max(open, close) * 1.008).toFixed(2)), low: Number((Math.min(open, close) * 0.992).toFixed(2)), close: Number(close.toFixed(2)), volume: Math.round((symbol.includes('BTC') ? 24_000 : 68_000_000) * (1 + Math.sin(index / 6) * 0.22)) };
  });
}

function registerQuantDataset(dataset) {
  quantPreviewBars.set(dataset.dataset_id, latestContiguousFixtureBars(dataset.symbol, dataset.covered_end, Math.min(240, dataset.bar_count)));
  return dataset;
}

const quantDatasets = [registerQuantDataset(quantDatasetDto({
  id: QUANT_FIXTURES[quantFixtureState].dataset.id,
  name: QUANT_FIXTURES[quantFixtureState].dataset.name,
  symbol: QUANT_FIXTURES[quantFixtureState].dataset.symbol,
  barCount: QUANT_FIXTURES[quantFixtureState].dataset.barCount,
  coveredStart: QUANT_FIXTURES[quantFixtureState].dataset.dateRange.start,
  coveredEnd: QUANT_FIXTURES[quantFixtureState].dataset.dateRange.end,
  sourceMetadata: { kind: 'csv_upload', file_name: 'synthetic-fixture.csv', source_name: 'Deterministic fixture', source_reference: 'fixture://spy', submitted_csv_digest: null, market_calendar: 'weekday', time_zone: 'America/New_York', price_adjustment: 'unadjusted' },
}))];
const initialQuantDatasets = cloneFixtureValue(quantDatasets);

const MARKET_DATASET_ID = '66666666-6666-4666-8666-666666666604';
const HOURLY_MARKET_DATASET_ID = '66666666-6666-4666-8666-666666666601';
const DAILY_MARKET_DATASET_ID = '66666666-6666-4666-8666-666666666603';
const MARKET_RUN_ID = '77777777-7777-4777-8777-777777777704';
const MARKET_CHILD_RUN_ID = '77777777-7777-4777-8777-777777777708';
const MARKET_DYNAMIC_RETRY_RUN_ID = '77777777-7777-4777-8777-777777777709';
const MARKET_HISTORY_RUN_ID = '77777777-7777-4777-8777-777777777703';
const MARKET_CONTINUED_RUN_ID = '77777777-7777-4777-8777-777777777706';
const MARKET_RETRY_RUN_ID = '77777777-7777-4777-8777-777777777705';
const MARKET_START = '2024-01-01T00:00:00+00:00';
const MARKET_END = '2025-12-31T20:00:00+00:00';
const MARKET_DATASET_DIGEST = SHA('6');
const HOURLY_MARKET_START = '2024-01-01T00:00:00+00:00';
const HOURLY_MARKET_END = '2024-07-27T07:00:00+00:00';
const HOURLY_MARKET_DATASET_DIGEST = SHA('b');

function marketStepHours(interval) {
  if (interval === '1h') return 1;
  if (interval === '4h') return 4;
  if (interval === '1D') return 24;
  throw new Error(`Unsupported market interval ${interval}`);
}

function marketPeriodsPerYear(interval) {
  if (interval === '1h') return 8760;
  if (interval === '4h') return 2190;
  if (interval === '1D') return 365;
  throw new Error(`Unsupported market interval ${interval}`);
}

function marketRequiredBars(interval, periodsPerYear = marketPeriodsPerYear(interval)) {
  return Math.max(252, Math.ceil(periodsPerYear / 4));
}

function marketIntervalLabel(interval) {
  if (interval === '1h') return '1 hour';
  if (interval === '4h') return '4 hour';
  if (interval === '1D') return '1 day';
  throw new Error(`Unsupported market interval ${interval}`);
}

function marketBarCount(interval, start, end) {
  return Math.floor((Date.parse(end) - Date.parse(start)) / (marketStepHours(interval) * 60 * 60 * 1000)) + 1;
}

function marketResearchEligible(interval, barCount, coveredStart, coveredEnd, periodsPerYear = marketPeriodsPerYear(interval)) {
  const stepMs = marketStepHours(interval) * 60 * 60 * 1000;
  const inclusiveCoverageMs = Date.parse(coveredEnd) - Date.parse(coveredStart) + stepMs;
  const requiredBars = marketRequiredBars(interval, periodsPerYear);
  return barCount >= requiredBars && inclusiveCoverageMs >= requiredBars * stepMs;
}

function utcWire(value) {
  return new Date(value).toISOString().replace('.000Z', '+00:00');
}

function csvNumber(value, label, allowZero = false) {
  const parsed = Number(value);
  requireValue(Number.isFinite(parsed), `${label} must be numeric.`);
  requireValue(allowZero ? parsed >= 0 : parsed > 0, `${label} must be ${allowZero ? 'non-negative' : 'positive'}.`);
  return parsed;
}

function canonicalizeForDigest(value) {
  if (Array.isArray(value)) return value.map(canonicalizeForDigest);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key.normalize('NFC'), canonicalizeForDigest(value[key])]),
    );
  }
  if (typeof value === 'string') return value.normalize('NFC');
  if (typeof value === 'number') {
    requireValue(Number.isFinite(value), 'Canonical digests require finite numeric values.');
    return Object.is(value, -0) ? 0 : value;
  }
  return value;
}

function canonicalDigest(value) {
  return `sha256:${createHash('sha256').update(JSON.stringify(canonicalizeForDigest(value))).digest('hex')}`;
}

function marketBarsDigest(rows) {
  return textDigest(rows.map((row) => [row.timestamp, row.open, row.high, row.low, row.close, row.volume].join(',')).join('\n'));
}

function marketCsvDatasetId(symbol, interval, csvText) {
  const bars = csvText
    .trim()
    .split(/\r?\n/)
    .slice(1)
    .filter(Boolean)
    .map((line) => {
      const [timestamp, open, high, low, close, volume] = line.split(',').map((cell) => cell.trim());
      return { timestamp, open, high, low, close, volume };
    });
  const identity = canonicalDigest({
    symbol,
    interval,
    bars,
  }).replace('sha256:', '').slice(0, 16);
  return `market-csv-${symbol}-${interval}-${identity}`;
}

function buildSyntheticMarketBars({ symbol, interval, start, count }) {
  const stepMs = marketStepHours(interval) * 60 * 60 * 1000;
  const base = symbol.includes('BTC') ? 65_000 : 400;
  return Array.from({ length: count }, (_, index) => {
    const timestamp = utcWire(Date.parse(start) + index * stepMs);
    const center = base + index * (interval === '1D' ? 18 : interval === '4h' ? 11 : 3) + Math.sin(index / 8) * (interval === '1D' ? 220 : 90);
    const open = center + Math.sin(index / 5) * 17;
    const close = center + Math.cos(index / 7) * 19;
    const high = Math.max(open, close) + 13;
    const low = Math.min(open, close) - 11;
    const volume = symbol.includes('BTC') ? 9 + (index % 23) * 0.173913 : 1_000_000 + index * 2_500;
    return {
      timestamp,
      open: open.toFixed(8),
      high: high.toFixed(8),
      low: low.toFixed(8),
      close: close.toFixed(8),
      volume: volume.toFixed(8),
    };
  });
}

function parseMarketCsvBars(csvText, interval) {
  const lines = csvText.trim().split(/\r?\n/);
  requireValue(lines.length >= 2, 'CSV must include a header and at least one bar.');
  requireValue(lines[0] === 'timestamp,open,high,low,close,volume', 'CSV header must exactly match timestamp,open,high,low,close,volume.');
  const stepMs = marketStepHours(interval) * 60 * 60 * 1000;
  const rows = [];
  let previousTimestamp = null;
  for (let index = 1; index < lines.length; index += 1) {
    const line = lines[index]?.trim();
    if (!line) continue;
    const cells = line.split(',');
    requireValue(cells.length === 6, `CSV row ${index + 1} must contain exactly 6 columns.`);
    const [timestampText, openText, highText, lowText, closeText, volumeText] = cells.map((cell) => cell.trim());
    requireValue(/^\d{4}-\d{2}-\d{2}T\d{2}:00:00Z$/.test(timestampText), `CSV row ${index + 1} timestamp must be an hourly UTC instant ending in Z.`);
    const timestamp = Date.parse(timestampText);
    requireValue(Number.isFinite(timestamp), `CSV row ${index + 1} timestamp is invalid.`);
    const hour = Number(timestampText.slice(11, 13));
    requireValue(interval !== '1D' || hour === 0, `CSV row ${index + 1} must align to 1D UTC cadence.`);
    requireValue(interval !== '4h' || hour % 4 === 0, `CSV row ${index + 1} must align to 4h UTC cadence.`);
    if (previousTimestamp !== null) {
      requireValue(timestamp > previousTimestamp, `CSV rows must be strictly increasing in time.`);
      requireValue(timestamp - previousTimestamp === stepMs, `CSV rows must follow exact ${interval} UTC cadence.`);
    }
    previousTimestamp = timestamp;
    const open = csvNumber(openText, `CSV row ${index + 1} open`);
    const high = csvNumber(highText, `CSV row ${index + 1} high`);
    const low = csvNumber(lowText, `CSV row ${index + 1} low`);
    const close = csvNumber(closeText, `CSV row ${index + 1} close`);
    const volume = csvNumber(volumeText, `CSV row ${index + 1} volume`, true);
    requireValue(high >= Math.max(open, close), `CSV row ${index + 1} high must be >= open and close.`);
    requireValue(low <= Math.min(open, close), `CSV row ${index + 1} low must be <= open and close.`);
    rows.push({
      timestamp: utcWire(timestamp),
      open: String(open),
      high: String(high),
      low: String(low),
      close: String(close),
      volume: String(volume),
    });
  }
  requireValue(rows.length > 0, 'CSV must contain at least one non-empty bar row.');
  return rows;
}

function buildMarketDatasetFromBars({
  datasetId,
  name,
  symbol,
  interval,
  authenticity,
  sourceKind,
  sourceName,
  sourceReference,
  fileName = null,
  submittedCsvDigest = null,
  requestedBarCount = null,
  batchDigest = null,
  bars,
}) {
  requireValue(Array.isArray(bars) && bars.length > 0, 'Market dataset bars are required.');
  const recordDigest = marketBarsDigest(bars);
  const coveredStart = bars[0]?.timestamp;
  const coveredEnd = bars[bars.length - 1]?.timestamp;
  const barCount = bars.length;
  const periodsPerYear = marketPeriodsPerYear(interval);
  const digestSeed = JSON.stringify({
    datasetId,
    symbol,
    interval,
    periodsPerYear,
    coveredStart,
    coveredEnd,
    barCount,
    recordDigest,
    sourceKind,
  });
  return {
    dataset: {
      schema_version: 'quant-market-bars-v2',
      dataset_id: datasetId,
      workspace_id: ID.workspace,
      name,
      symbol,
      interval,
      covered_start: coveredStart,
      covered_end: coveredEnd,
      bar_count: barCount,
      digest: textDigest(`dataset:${digestSeed}`),
      record_digest: textDigest(`record:${recordDigest}`),
      periods_per_year: periodsPerYear,
      market_calendar: '24x7',
      market_session: 'continuous',
      time_zone: 'UTC',
      research_eligible: marketResearchEligible(
        interval,
        barCount,
        coveredStart,
        coveredEnd,
        periodsPerYear,
      ),
      data_authenticity: authenticity,
      created_at: NOW,
      evidence: {
        source_kind: sourceKind,
        file_name: fileName,
        source_name: sourceName,
        source_reference: sourceReference,
        normalizer_version: sourceKind === 'csv_upload' ? 'fixture-market-csv-v2' : 'fixture-market-bars-v2',
        ...(sourceKind === 'csv_upload'
          ? { submitted_csv_digest: submittedCsvDigest ?? textDigest('fixture-empty-csv') }
          : {
            retrieved_at_utc: NOW,
            requested_bar_count: requestedBarCount ?? barCount,
            returned_bar_count: barCount,
            retained_bar_count: barCount,
            closed_dropped_count: 0,
            deduplicated_count: 0,
            page_raw_sha256: [textDigest(`page:${sourceReference ?? datasetId}:${requestedBarCount ?? barCount}:${recordDigest}`)],
            batch_digest: batchDigest ?? textDigest(`batch:${digestSeed}`),
            termination_reason: 'requested_limit',
            target_satisfied: true,
          }),
      },
      quality: {
        status: 'accepted',
        cadence_gap_count: 0,
        normalization_note: sourceKind === 'csv_upload'
          ? `Parsed deterministic ${interval} CSV fixture bars with contiguous UTC cadence.`
          : `Deterministic contiguous ${interval} fixture bars; no provider network call.`,
      },
    },
    bars,
  };
}

function marketDatasetDto({
  datasetId,
  name,
  symbol,
  interval,
  coveredStart,
  coveredEnd,
  authenticity,
  sourceKind,
  fileName = null,
  sourceName,
  sourceReference,
  submittedCsvDigest = null,
  requestedBarCount = null,
  returnedBarCount = null,
  retainedBarCount = null,
  batchDigest = null,
  digestSeed,
}) {
  const barCount = marketBarCount(interval, coveredStart, coveredEnd);
  const periodsPerYear = marketPeriodsPerYear(interval);
  const evidence = {
    source_kind: sourceKind,
    file_name: fileName,
    source_name: sourceName,
    source_reference: sourceReference,
    normalizer_version: 'fixture-market-bars-v2',
    ...(sourceKind === 'provider_fetch'
      ? {
        retrieved_at_utc: NOW,
        requested_bar_count: requestedBarCount ?? barCount,
        returned_bar_count: returnedBarCount ?? barCount,
        retained_bar_count: retainedBarCount ?? barCount,
        closed_dropped_count: 0,
        deduplicated_count: 0,
        page_raw_sha256: [textDigest(`page:${sourceReference ?? datasetId}:${requestedBarCount ?? barCount}:${digestSeed ?? datasetId}`)],
        batch_digest: batchDigest ?? textDigest(`batch:${digestSeed ?? datasetId}`),
        termination_reason: 'requested_limit',
        target_satisfied: true,
      }
      : { submitted_csv_digest: submittedCsvDigest ?? textDigest(`csv:${digestSeed ?? datasetId}`) }),
  };
  return {
    schema_version: 'quant-market-bars-v2',
    dataset_id: datasetId,
    workspace_id: ID.workspace,
    name,
    symbol,
    interval,
    covered_start: coveredStart,
    covered_end: coveredEnd,
    bar_count: barCount,
    digest: textDigest(`dataset:${digestSeed ?? datasetId}`),
    record_digest: textDigest(`record:${digestSeed ?? datasetId}`),
    periods_per_year: periodsPerYear,
    market_calendar: '24x7',
    market_session: 'continuous',
    time_zone: 'UTC',
    research_eligible: marketResearchEligible(
      interval,
      barCount,
      coveredStart,
      coveredEnd,
      periodsPerYear,
    ),
    data_authenticity: authenticity,
    created_at: NOW,
    evidence,
    quality: {
      status: 'accepted',
      cadence_gap_count: 0,
      normalization_note: `Deterministic contiguous ${interval} fixture bars; no provider network call.`,
    },
  };
}

const quantMarketDataset = marketDatasetDto({
  datasetId: MARKET_DATASET_ID,
  name: 'BTCUSDT Binance Spot 4 hour',
  symbol: 'BTCUSDT',
  interval: '4h',
  coveredStart: MARKET_START,
  coveredEnd: MARKET_END,
  authenticity: 'synthetic_fixture',
  sourceKind: 'provider_fetch',
  sourceName: 'Binance Spot deterministic API fixture',
  sourceReference: 'fixture://binance/BTCUSDT/4h',
  requestedBarCount: 4386,
  returnedBarCount: 4386,
  retainedBarCount: 4386,
  batchDigest: SHA('a'),
  digestSeed: 'market-4h',
});
quantMarketDataset.digest = MARKET_DATASET_DIGEST;
quantMarketDataset.record_digest = SHA('9');

const quantHourlyMarketDataset = marketDatasetDto({
  datasetId: HOURLY_MARKET_DATASET_ID,
  name: 'BTCUSDT Binance Spot 1 hour',
  symbol: 'BTCUSDT',
  interval: '1h',
  coveredStart: HOURLY_MARKET_START,
  coveredEnd: HOURLY_MARKET_END,
  authenticity: 'synthetic_fixture',
  sourceKind: 'provider_fetch',
  sourceName: 'Binance Spot deterministic API fixture',
  sourceReference: 'fixture://binance/BTCUSDT/1h/5000',
  requestedBarCount: 5000,
  returnedBarCount: 5000,
  retainedBarCount: 5000,
  batchDigest: SHA('f'),
  digestSeed: 'market-1h',
});
quantHourlyMarketDataset.digest = HOURLY_MARKET_DATASET_DIGEST;
quantHourlyMarketDataset.record_digest = SHA('e');

const quantMarketPreviewBars = new Map();

function buildDefaultMarketPreviewBars(dataset) {
  return buildSyntheticMarketBars({
    symbol: dataset.symbol,
    interval: dataset.interval,
    start: dataset.covered_start,
    count: dataset.bar_count,
  });
}

function registerMarketDataset(dataset, bars = buildDefaultMarketPreviewBars(dataset)) {
  quantMarketPreviewBars.set(dataset.dataset_id, bars);
  return dataset;
}

const quantMarketDatasets = [
  registerMarketDataset(quantMarketDataset),
  registerMarketDataset(quantHourlyMarketDataset),
];
const initialQuantMarketDatasets = cloneFixtureValue(quantMarketDatasets);
const quantConnectorDirectory = [{
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
}];

function upsertMarketDataset(dataset, bars = buildDefaultMarketPreviewBars(dataset)) {
  const index = quantMarketDatasets.findIndex((item) => item.dataset_id === dataset.dataset_id);
  if (index >= 0) quantMarketDatasets.splice(index, 1, dataset);
  else quantMarketDatasets.push(dataset);
  quantMarketPreviewBars.set(dataset.dataset_id, bars);
  return dataset;
}

function marketDatasetSource(dataset) {
  const base = {
    kind: dataset.evidence.source_kind,
    fileName: dataset.evidence.file_name ?? null,
    sourceName: dataset.evidence.source_name,
    sourceReference: dataset.evidence.source_reference ?? null,
    normalizerVersion: dataset.evidence.normalizer_version,
  };
  if (dataset.evidence.source_kind === 'provider_fetch') {
    return {
      ...base,
      retrievedAtUtc: dataset.evidence.retrieved_at_utc,
      requestedBarCount: dataset.evidence.requested_bar_count,
      returnedBarCount: dataset.evidence.returned_bar_count,
      retainedBarCount: dataset.evidence.retained_bar_count,
      closedDroppedCount: dataset.evidence.closed_dropped_count,
      deduplicatedCount: dataset.evidence.deduplicated_count,
      terminationReason: dataset.evidence.termination_reason,
      targetSatisfied: dataset.evidence.target_satisfied,
      submittedCsvDigest: null,
      batchDigest: dataset.evidence.batch_digest,
    };
  }
  return {
    ...base,
    retrievedAtUtc: null,
    requestedBarCount: null,
    returnedBarCount: null,
    retainedBarCount: null,
    closedDroppedCount: null,
    deduplicatedCount: null,
    terminationReason: null,
    targetSatisfied: null,
    submittedCsvDigest: dataset.evidence.submitted_csv_digest,
    batchDigest: null,
  };
}

function buildMarketCsvDataset(payload) {
  const interval = payload.interval;
  const symbol = String(payload.symbol).trim().toUpperCase();
  const bars = parseMarketCsvBars(payload.csv_text, interval);
  const datasetId = marketCsvDatasetId(symbol, interval, payload.csv_text);
  return buildMarketDatasetFromBars({
    datasetId,
    name: String(payload.name).trim(),
    symbol,
    interval,
    authenticity: 'imported',
    sourceKind: 'csv_upload',
    sourceName: payload.source_name ?? 'User-provided market CSV',
    sourceReference: payload.source_reference ?? null,
    fileName: payload.file_name ?? null,
    submittedCsvDigest: textDigest(payload.csv_text),
    bars,
  });
}

function buildMarketBinanceDataset(payload) {
  const interval = payload.interval;
  const symbol = String(payload.symbol ?? 'BTCUSDT').trim().toUpperCase();
  const requestedBarCount = Math.max(1, Math.min(5000, Number(payload.limit ?? (interval === '4h' ? 4386 : interval === '1D' ? 365 : 5000))));
  if (symbol === 'BTCUSDT' && interval === '4h' && requestedBarCount === 4386) {
    return {
      dataset: cloneFixtureValue(quantMarketDataset),
      bars: cloneFixtureValue(quantMarketPreviewBars.get(MARKET_DATASET_ID) ?? buildDefaultMarketPreviewBars(quantMarketDataset)),
    };
  }
  const datasetId = symbol === 'BTCUSDT' && interval === '1D' && requestedBarCount === 365
    ? DAILY_MARKET_DATASET_ID
    : `fixture-market-binance-${symbol.toLowerCase()}-${interval.toLowerCase()}-${requestedBarCount}`;
  const displayName = payload.name?.trim() || `${symbol} Binance Spot ${marketIntervalLabel(interval)}`;
  const baseStart = interval === '1D' ? '2023-01-01T00:00:00+00:00' : '2024-01-01T00:00:00+00:00';
  const bars = buildSyntheticMarketBars({
    symbol,
    interval,
    start: baseStart,
    count: requestedBarCount,
  });
  return buildMarketDatasetFromBars({
    datasetId,
    name: displayName,
    symbol,
    interval,
    authenticity: 'synthetic_fixture',
    sourceKind: 'provider_fetch',
    sourceName: 'Binance Spot deterministic API fixture',
    sourceReference: `fixture://binance/${symbol}/${interval}/${requestedBarCount}`,
    requestedBarCount,
    bars,
  });
}

function buildKrakenConnectorDataset(payload) {
  const interval = payload.interval;
  const symbol = String(payload.symbol ?? '').trim().toUpperCase();
  const minimum = interval === '4h' ? 548 : 252;
  const requestedBarCount = Number(payload.limit);
  requireValue(['BTCUSD', 'BTCUSDT', 'ETHUSD', 'ETHUSDT'].includes(symbol), 'Kraken connector fixture symbol is unsupported.');
  requireValue(interval === '4h' || interval === '1D', 'Kraken connector fixture interval is unsupported.');
  requireValue(Number.isInteger(requestedBarCount) && requestedBarCount >= minimum && requestedBarCount <= 719, `Kraken connector fixture requires ${minimum}–719 bars for ${interval}.`);
  const bars = buildSyntheticMarketBars({
    symbol,
    interval,
    start: interval === '4h' ? '2026-04-24T20:00:00+00:00' : '2024-08-05T00:00:00+00:00',
    count: requestedBarCount,
  });
  return buildMarketDatasetFromBars({
    datasetId: `fixture-connector-kraken-${symbol.toLowerCase()}-${interval.toLowerCase()}-${requestedBarCount}`,
    name: payload.name?.trim() || `${symbol} Kraken Spot ${marketIntervalLabel(interval)}`,
    symbol,
    interval,
    authenticity: 'synthetic_fixture',
    sourceKind: 'provider_fetch',
    sourceName: 'Kraken Spot deterministic connector fixture',
    sourceReference: `fixture://connector/kraken/${symbol}/${interval}/${requestedBarCount}`,
    requestedBarCount,
    bars,
  });
}

function marketIdentity(datasetId) {
  const dataset = quantMarketDatasets.find((item) => item.dataset_id === datasetId);
  if (!dataset) throw new Error(`Unknown market dataset ${datasetId}`);
  const descriptorSeed = JSON.stringify({
    datasetDigest: dataset.digest,
    recordDigest: dataset.record_digest,
    interval: dataset.interval,
    periodsPerYear: dataset.periods_per_year,
    coveredStart: dataset.covered_start,
    coveredEnd: dataset.covered_end,
    barCount: dataset.bar_count,
  });
  const splitSeed = JSON.stringify({
    datasetDigest: dataset.digest,
    recordDigest: dataset.record_digest,
    interval: dataset.interval,
    periodsPerYear: dataset.periods_per_year,
    coveredStart: dataset.covered_start,
    coveredEnd: dataset.covered_end,
    barCount: dataset.bar_count,
    kind: 'sealed-split',
  });
  return {
    dataset,
    datasetId: dataset.dataset_id,
    datasetDigest: dataset.digest,
    descriptorDigest: textDigest(`descriptor:${descriptorSeed}`),
    splitDigest: textDigest(`split:${splitSeed}`),
    start: dataset.covered_start,
    end: dataset.covered_end,
    interval: dataset.interval,
    periodsPerYear: dataset.periods_per_year,
    stepHours: marketStepHours(dataset.interval),
    projectTitle: `${dataset.symbol} ${dataset.interval} Research`,
    defaultQuestion: `Compare interpretable ${dataset.symbol} ${dataset.interval} strategies across repeated training windows.`,
  };
}

function marketDatasetResponse(dataset, contractMode = false) {
  if (!contractMode || dataset.data_authenticity !== 'synthetic_fixture') return dataset;
  return { ...dataset, data_authenticity: 'generated' };
}

function marketTimestamp(index, count, identity = marketIdentity(MARKET_DATASET_ID)) {
  const start = Date.parse(identity.start);
  const end = Date.parse(identity.end);
  const cadenceMs = identity.stepHours * 60 * 60 * 1000;
  if (count <= 1) return new Date(start).toISOString().replace('.000Z', '+00:00');
  if (identity.interval === '1h' && count > 2 && index === 0) return new Date(start).toISOString().replace('.000Z', '+00:00');
  if (identity.interval === '1h' && count > 2 && index === 1) return new Date(start + cadenceMs).toISOString().replace('.000Z', '+00:00');
  const remainingIndex = identity.interval === '1h' && count > 2 ? Math.max(0, index - 1) : index;
  const remainingCount = identity.interval === '1h' && count > 2 ? count - 2 : count - 1;
  const remainingStart = identity.interval === '1h' && count > 2 ? start + cadenceMs : start;
  const step = Math.max(cadenceMs, Math.floor((end - remainingStart) / Math.max(1, remainingCount) / cadenceMs) * cadenceMs);
  return new Date(Math.min(end, remainingStart + remainingIndex * step)).toISOString().replace('.000Z', '+00:00');
}

function marketRunDto(snapshot) {
  const identity = marketIdentity(snapshot.dataset.id);
  return {
    schema_version: 'quant-market-run-v2', id: snapshot.run.id, row_version: snapshot.run.rowVersion, project_id: snapshot.project.id,
    dataset_id: identity.datasetId, dataset_digest: identity.datasetDigest, symbol: identity.dataset.symbol, interval: identity.interval, periods_per_year: identity.periodsPerYear,
    research_start_utc: snapshot.scope.dateRange.start, research_end_utc: snapshot.scope.dateRange.end, runtime_descriptor_digest: snapshot.dataset.runtimeDescriptorDigest, sealed_split_digest: snapshot.dataset.sealedSplitDigest,
    state: snapshot.run.state, mode: snapshot.run.mode === 'auto_research' ? 'auto' : 'plan', question: snapshot.project.goal, plan_revision: snapshot.run.planRevision ?? 1,
    attempt_number: snapshot.run.attemptNumber, parent_run_id: snapshot.run.continuedFrom?.parentRunId ?? null,
    seed_candidate_id: snapshot.run.continuedFrom?.seedCandidateId ?? null,
    refinement_reason: snapshot.run.continuedFrom?.reason ?? null,
    retry_of_run_id: snapshot.run.retryOfRunId ?? null, retry_child_run_id: null, provider: snapshot.run.provider, model: snapshot.run.model, used_experiments: snapshot.run.usedExperiments,
    created_at: snapshot.run.startedAt, updated_at: snapshot.run.completedAt ?? LATER,
  };
}

function marketSnapshot(stateName = 'quant-completed', runId = MARKET_HISTORY_RUN_ID, question, mode = 'auto_research', datasetId = MARKET_DATASET_ID, researchRange) {
  const identity = marketIdentity(datasetId);
  const start = researchRange?.start ?? identity.start;
  const end = researchRange?.end ?? identity.end;
  const usesFullCoverage = Date.parse(start) === Date.parse(identity.start) && Date.parse(end) === Date.parse(identity.end);
  const runtimeBarCount = Math.floor((Date.parse(end) - Date.parse(start)) / (identity.stepHours * 60 * 60 * 1000)) + 1;
  const runtimeDescriptorSeed = JSON.stringify({
    datasetDigest: identity.datasetDigest,
    recordDigest: identity.dataset.record_digest,
    interval: identity.interval,
    periodsPerYear: identity.periodsPerYear,
    rangeStart: start,
    rangeEnd: end,
    barCount: runtimeBarCount,
  });
  const runtimeSplitSeed = JSON.stringify({
    datasetDigest: identity.datasetDigest,
    recordDigest: identity.dataset.record_digest,
    interval: identity.interval,
    periodsPerYear: identity.periodsPerYear,
    rangeStart: start,
    rangeEnd: end,
    barCount: runtimeBarCount,
    kind: 'sealed-split',
  });
  const runtimeIdentity = {
    ...identity,
    start,
    end,
    descriptorDigest: usesFullCoverage ? identity.descriptorDigest : textDigest(`descriptor:${runtimeDescriptorSeed}`),
    splitDigest: usesFullCoverage ? identity.splitDigest : textDigest(`split:${runtimeSplitSeed}`),
  };
  question ??= identity.defaultQuestion;
  const snapshot = JSON.parse(JSON.stringify(QUANT_FIXTURES[stateName]));
  const runtimeState = snapshot.run.state;
  snapshot.authenticity = 'synthetic_fixture';
  snapshot.runtimeLabel = `Deterministic ${identity.interval} market-bar kernel`;
  snapshot.project.id = '44444444-4444-4444-8444-444444444406';
  snapshot.project.title = identity.projectTitle;
  snapshot.project.goal = question;
  snapshot.project.symbol = identity.dataset.symbol;
  snapshot.project.updatedAt = LATER;
  snapshot.scope.symbol = identity.dataset.symbol;
  snapshot.scope.market = '24x7 Market';
  snapshot.scope.interval = identity.interval;
  snapshot.scope.dateRange = { start, end };
  snapshot.run.id = runId;
  snapshot.run.state = runtimeState;
  snapshot.run.mode = mode;
  snapshot.run.rowVersion = quantRowVersion;
  snapshot.run.planRevision = 1;
  snapshot.run.provider = 'fixture';
  snapshot.run.model = 'fixture-market-agent';
  snapshot.run.startedAt = '2026-07-20T09:00:00+00:00';
  snapshot.run.completedAt = ['completed', 'failed', 'cancelled'].includes(runtimeState) ? '2026-07-20T09:11:00+00:00' : null;
  snapshot.dataset = {
    id: identity.datasetId, name: identity.dataset.name, symbol: identity.dataset.symbol, interval: identity.interval, dateRange: { start, end }, barCount: runtimeBarCount,
    schemaVersion: 'quant-market-bars-v2', parserVersion: identity.dataset.evidence.normalizer_version, digest: identity.datasetDigest, authenticity: identity.dataset.data_authenticity, createdAt: NOW,
    periodsPerYear: identity.periodsPerYear, marketCalendar: '24x7', marketSession: 'continuous', timeZone: 'UTC', runtimeDescriptorDigest: runtimeIdentity.descriptorDigest, sealedSplitDigest: runtimeIdentity.splitDigest,
    source: marketDatasetSource(identity.dataset),
    quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: identity.dataset.quality.normalization_note },
  };
  snapshot.bars = snapshot.bars.map((bar, index, rows) => ({ ...bar, date: marketTimestamp(index, rows.length, runtimeIdentity) }));
  snapshot.performanceSeries = snapshot.performanceSeries.map((series) => ({ ...series, points: series.points.map((point, index, rows) => ({ ...point, date: marketTimestamp(index, rows.length, runtimeIdentity) })) }));
  snapshot.trades = snapshot.trades.map((trade, index) => ({
    id: trade.id,
    candidateId: trade.candidateId,
    entryDate: marketTimestamp(Math.min(index * 3 + 2, snapshot.bars.length - 2), snapshot.bars.length, runtimeIdentity),
    exitDate: marketTimestamp(Math.min(index * 3 + 4, snapshot.bars.length - 1), snapshot.bars.length, runtimeIdentity),
    returnPct: trade.returnPct,
    holdingBars: 2,
    holdingElapsedSeconds: 2 * (identity.interval === '1h' ? 3_600 : identity.interval === '4h' ? 14_400 : 86_400),
    reason: trade.reason,
  }));
  snapshot.kernelCheck.engineVersion = 'market-bar-kernel-v1';
  snapshot.kernelCheck.datasetId = identity.datasetId;
  snapshot.kernelCheck.datasetDigest = identity.datasetDigest;
  snapshot.kernelCheck.barCount = runtimeBarCount;
  Object.assign(snapshot.kernelCheck, { interval: identity.interval, periodsPerYear: identity.periodsPerYear, runtimeDescriptorDigest: runtimeIdentity.descriptorDigest, sealedSplitDigest: runtimeIdentity.splitDigest });
  if (snapshot.report) snapshot.report.datasetContext = { symbol: identity.dataset.symbol, interval: identity.interval, periodsPerYear: identity.periodsPerYear, range: { start, end }, runtimeDescriptorDigest: runtimeIdentity.descriptorDigest, sealedSplitDigest: runtimeIdentity.splitDigest };
  if (snapshot.report && runtimeState === 'completed' && !snapshot.report.generalization) {
    snapshot.report.generalization = marketTerminalGeneralization(snapshot);
  }
  if (snapshot.report?.generalization?.split) {
    const cutoff = marketTimestamp(22, 28, runtimeIdentity);
    Object.assign(snapshot.report.generalization.split, { datasetId: identity.datasetId, datasetDigest: identity.datasetDigest, interval: identity.interval, periodsPerYear: identity.periodsPerYear, cutoffTimestampUtc: cutoff, rangeStartUtc: start, rangeEndUtc: end, descriptorDigest: runtimeIdentity.descriptorDigest, sealDigest: runtimeIdentity.splitDigest });
    snapshot.report.generalization.split.cutoffDate = cutoff;
    if (snapshot.report.walkForward?.folds) {
      snapshot.report.walkForward.folds = snapshot.report.walkForward.folds.map((fold, index) => ({ ...fold, historyStart: start, historyEnd: marketTimestamp(9 + index * 4, 28, runtimeIdentity), evaluationStart: marketTimestamp(10 + index * 4, 28, runtimeIdentity), evaluationEnd: marketTimestamp(13 + index * 4, 28, runtimeIdentity) }));
    }
  }
  snapshot.researchPlan = {
    objectiveSummary: question,
    candidateFamilies: ['sma_crossover', 'breakout'],
    selectionObjective: 'drawdown_control',
    completionCriteria: ['Backtest all approved candidates and retain one final training comparison.'],
  };
  if (snapshot.report) {
    snapshot.report.selectionDecision = {
      basis: 'approved_objective_rank',
      selectedCandidateId: 'candidate-b',
    };
    delete snapshot.report.iterationStop;
    snapshot.candidates = snapshot.candidates.map((candidate) => {
      if (candidate.id === 'candidate-a') return {
        ...candidate,
        canSeedResearch: false,
        evolution: {
          hypothesis: 'Test a faster moving-average trend signal against buy and hold.',
          origin: 'initial',
          changeRationale: null,
          feedbackReferenceCandidateId: null,
          feedbackReferenceCandidateName: null,
          comparisonRank: 2,
          comparisonCandidateCount: 3,
          selectionReason: 'Ranked 2 of 3 under the approved drawdown-control objective.',
        },
      };
      if (candidate.id === 'candidate-b') return {
        ...candidate,
        canSeedResearch: true,
        evolution: {
          hypothesis: 'Test a slower moving-average trend signal for lower drawdown.',
          origin: 'initial',
          changeRationale: null,
          feedbackReferenceCandidateId: null,
          feedbackReferenceCandidateName: null,
          comparisonRank: 1,
          comparisonCandidateCount: 3,
          selectionReason: 'Ranked 1 of 3 under the approved drawdown-control objective.',
        },
      };
      return {
        ...candidate,
        canSeedResearch: false,
        evolution: {
          hypothesis: 'Test whether a wider breakout window improves the initial training reference.',
          origin: 'training_feedback',
          changeRationale: 'Widen the breakout window after the initial training comparison.',
          feedbackReferenceCandidateId: 'candidate-a',
          feedbackReferenceCandidateName: 'Candidate A · SMA 20/100',
          comparisonRank: 3,
          comparisonCandidateCount: 3,
          selectionReason: 'Ranked 3 of 3 under the approved drawdown-control objective.',
        },
      };
    });
  }
  return snapshot;
}

function marketChronologicalSplit(snapshot) {
  const barCount = snapshot.dataset.barCount;
  const trainBarCount = Math.max(1, Math.min(Math.floor(barCount * 80 / 100), barCount - 1));
  const holdoutBarCount = barCount - trainBarCount;
  if (trainBarCount <= 0 || holdoutBarCount <= 0) throw new Error('Market fixture requires a non-empty chronological train/holdout split.');
  const cutoffMs = Date.parse(snapshot.scope.dateRange.start) + trainBarCount * marketStepHours(snapshot.dataset.interval) * 60 * 60 * 1000;
  const cutoffTimestampUtc = new Date(cutoffMs).toISOString().replace('.000Z', '+00:00');
  return {
    method: 'chronological',
    ruleVersion: 'chronological-80-20-v1',
    trainBarCount,
    holdoutBarCount,
    cutoffDate: cutoffTimestampUtc,
    datasetId: snapshot.dataset.id,
    datasetDigest: snapshot.dataset.digest,
    interval: snapshot.dataset.interval,
    periodsPerYear: snapshot.dataset.periodsPerYear,
    cutoffTimestampUtc,
    rangeStartUtc: snapshot.scope.dateRange.start,
    rangeEndUtc: snapshot.scope.dateRange.end,
    descriptorDigest: snapshot.dataset.runtimeDescriptorDigest,
    sealDigest: snapshot.dataset.sealedSplitDigest,
  };
}

function marketTerminalGeneralization(snapshot) {
  return {
    status: 'fail',
    reason: 'The retained sealed holdout did not support the final choice.',
    selectedCandidateId: 'candidate-b',
    split: marketChronologicalSplit(snapshot),
  };
}

function markMarketSnapshotWithoutHoldout(snapshot) {
  if (!snapshot.report) return snapshot;
  snapshot.report.generalization = {
    status: 'not_evaluated',
    reason: 'This continued or retry Run reuses overlapping prior evidence as development evidence; no fresh sealed holdout was evaluated or projected.',
    selectedCandidateId: 'candidate-b',
    split: marketChronologicalSplit(snapshot),
  };
  return snapshot;
}

const quantMarketHistoricalSnapshot = marketSnapshot();
quantMarketHistoricalSnapshot.candidates = quantMarketHistoricalSnapshot.candidates.map((candidate) => ({
  ...candidate,
  canSeedResearch: candidate.id === 'candidate-b',
}));
const quantMarketContinuedSnapshot = JSON.parse(JSON.stringify(quantMarketHistoricalSnapshot));
quantMarketContinuedSnapshot.run.id = MARKET_CONTINUED_RUN_ID;
quantMarketContinuedSnapshot.run.startedAt = '2026-07-21T08:00:00+00:00';
quantMarketContinuedSnapshot.run.completedAt = '2026-07-21T08:11:00+00:00';
quantMarketContinuedSnapshot.project.goal = 'Continue BTCUSDT 4h research with a slower trend filter and tighter drawdown objective.';
quantMarketContinuedSnapshot.project.updatedAt = quantMarketContinuedSnapshot.run.completedAt;
quantMarketContinuedSnapshot.run.continuedFrom = {
  parentRunId: MARKET_HISTORY_RUN_ID,
  seedCandidateId: 'candidate-b',
  candidateName: 'Candidate B · SMA 50/200',
  sourceQuestion: quantMarketHistoricalSnapshot.project.goal,
  reason: 'Use the retained 4h candidate while testing a tighter drawdown objective.',
};
quantMarketContinuedSnapshot.candidates = quantMarketContinuedSnapshot.candidates.map((candidate) => ({ ...candidate, canSeedResearch: false }));
markMarketSnapshotWithoutHoldout(quantMarketContinuedSnapshot);
const quantMarketRetrySnapshot = JSON.parse(JSON.stringify(quantMarketContinuedSnapshot));
quantMarketRetrySnapshot.run.id = MARKET_RETRY_RUN_ID;
quantMarketRetrySnapshot.run.attemptNumber = 2;
quantMarketRetrySnapshot.run.startedAt = '2026-07-22T09:00:00+00:00';
quantMarketRetrySnapshot.run.completedAt = '2026-07-22T09:11:00+00:00';
quantMarketRetrySnapshot.project.updatedAt = quantMarketRetrySnapshot.run.completedAt;
quantMarketRetrySnapshot.run.retryOfRunId = MARKET_CONTINUED_RUN_ID;
const dynamicMarketRunDirectory = new Map();
const dynamicMarketSnapshotReads = new Map();
let activeMarketRunId = null;

function dynamicMarketSnapshots() {
  return [...dynamicMarketRunDirectory.values()];
}

function publicMarketSnapshots() {
  return [quantMarketHistoricalSnapshot, quantMarketContinuedSnapshot, quantMarketRetrySnapshot, ...dynamicMarketSnapshots()];
}

function allQuantSnapshots() {
  return [...quantHistoryFixtures(), ...publicMarketSnapshots()];
}

function resetFixtureState() {
  const freshState = cloneFixtureValue(initialFixtureState);
  for (const key of Object.keys(state)) delete state[key];
  Object.assign(state, freshState);
  quantFixtureState = INITIAL_QUANT_FIXTURE_STATE;
  quantRowVersion = 8;
  quantGoal = QUANT_FIXTURES[quantFixtureState].project.goal;
  quantRunMode = QUANT_FIXTURES[quantFixtureState].run.mode;
  quantProjectRowVersion = 1;
  quantPreviewBars.clear();
  quantDatasets.splice(0, quantDatasets.length);
  for (const dataset of initialQuantDatasets) quantDatasets.push(registerQuantDataset(cloneFixtureValue(dataset)));
  quantMarketPreviewBars.clear();
  quantMarketDatasets.splice(0, quantMarketDatasets.length);
  for (const dataset of initialQuantMarketDatasets) quantMarketDatasets.push(registerMarketDataset(cloneFixtureValue(dataset)));
  activeMarketRunId = null;
  dynamicMarketRunDirectory.clear();
  dynamicMarketSnapshotReads.clear();
}

function quantHistoryFixtures() {
  const current = JSON.parse(JSON.stringify(QUANT_FIXTURES[quantFixtureState]));
  current.run.rowVersion = quantRowVersion;
  current.run.mode = quantRunMode;
  current.project.goal = quantGoal;

  const seriesRoot = JSON.parse(JSON.stringify(QUANT_FIXTURES['quant-completed']));
  seriesRoot.run.id = '55555555-5555-4555-8555-555555555506';
  seriesRoot.run.attemptNumber = 1;
  seriesRoot.run.startedAt = '2026-06-11T09:30:00Z';
  seriesRoot.run.completedAt = '2026-06-11T09:42:00Z';
  seriesRoot.project.id = '44444444-4444-4444-8444-444444444403';
  seriesRoot.project.title = 'SPY Regime Study';
  seriesRoot.project.goal = 'Establish the SPY trend-filter baseline before a focused continuation.';
  seriesRoot.project.updatedAt = seriesRoot.run.completedAt;

  const comparable = JSON.parse(JSON.stringify(QUANT_FIXTURES['quant-completed']));
  comparable.run.id = '55555555-5555-4555-8555-555555555503';
  comparable.run.attemptNumber = 1;
  comparable.run.startedAt = '2026-06-12T09:30:00Z';
  comparable.run.completedAt = '2026-06-12T09:42:00Z';
  comparable.project.id = '44444444-4444-4444-8444-444444444403';
  comparable.project.title = 'SPY Regime Study';
  comparable.project.goal = 'Compare slower SPY trend filters across the same research range.';
  comparable.project.updatedAt = comparable.run.completedAt;
  comparable.run.continuedFrom = {
    parentRunId: seriesRoot.run.id,
    seedCandidateId: 'candidate-b',
    candidateName: 'Candidate B · SMA 50/200',
    sourceQuestion: seriesRoot.project.goal,
    reason: 'Compare slower trend filters while retaining the original SPY research evidence.',
  };
  comparable.candidates = comparable.candidates.map((candidate, index) => ({
    ...candidate,
    metrics: {
      ...candidate.metrics,
      annualizedReturn: candidate.metrics.annualizedReturn - 1.8 - index * 0.2,
      sharpe: candidate.metrics.sharpe - 0.12,
      maxDrawdown: candidate.metrics.maxDrawdown - 0.7,
      trades: candidate.metrics.trades + 3,
    },
  }));

  const retryOfComparable = JSON.parse(JSON.stringify(comparable));
  retryOfComparable.run.id = '55555555-5555-4555-8555-555555555505';
  retryOfComparable.run.attemptNumber = 2;
  retryOfComparable.run.startedAt = '2026-06-13T09:30:00Z';
  retryOfComparable.run.completedAt = '2026-06-13T09:42:00Z';
  retryOfComparable.project.updatedAt = retryOfComparable.run.completedAt;
  retryOfComparable.run.retryOfRunId = comparable.run.id;

  const incompatible = JSON.parse(JSON.stringify(QUANT_FIXTURES['quant-completed']));
  incompatible.run.id = '55555555-5555-4555-8555-555555555504';
  incompatible.run.attemptNumber = 1;
  incompatible.run.startedAt = '2026-05-04T13:10:00Z';
  incompatible.run.completedAt = '2026-05-04T13:25:00Z';
  incompatible.project.id = '44444444-4444-4444-8444-444444444404';
  incompatible.project.title = 'QQQ Momentum Review';
  incompatible.project.goal = 'Evaluate QQQ momentum resilience after the 2020 regime shift.';
  incompatible.project.symbol = 'QQQ';
  incompatible.project.updatedAt = incompatible.run.completedAt;
  incompatible.dataset.id = '33333333-3333-4333-8333-333333333399';
  incompatible.dataset.name = 'QQQ daily research snapshot';
  incompatible.dataset.symbol = 'QQQ';
  incompatible.scope.symbol = 'QQQ';
  incompatible.scope.dateRange = { start: '2020-01-02', end: '2023-12-29' };
  incompatible.dataset.dateRange = { ...incompatible.scope.dateRange };
  incompatible.candidates = incompatible.candidates.map((candidate, index) => ({
    ...candidate,
    metrics: {
      ...candidate.metrics,
      annualizedReturn: candidate.metrics.annualizedReturn + 2.4 + index * 0.3,
      sharpe: candidate.metrics.sharpe + 0.18,
      maxDrawdown: candidate.metrics.maxDrawdown + 1.1,
      trades: Math.max(1, candidate.metrics.trades - 2),
    },
  }));
  return [current, seriesRoot, comparable, retryOfComparable, incompatible];
}

function quantHistoryRow(snapshot) {
  return {
    id: snapshot.run.id,
    project_id: snapshot.project.id,
    dataset_id: snapshot.dataset.id,
    state: snapshot.run.state,
    mode: snapshot.run.mode === 'auto_research' ? 'auto' : 'plan',
    question: snapshot.project.goal,
    attempt_number: snapshot.run.attemptNumber,
    parent_run_id: snapshot.run.continuedFrom?.parentRunId ?? null,
    seed_candidate_id: snapshot.run.continuedFrom?.seedCandidateId ?? null,
    refinement_reason: snapshot.run.continuedFrom?.reason ?? null,
    retry_of_run_id: snapshot.run.retryOfRunId ?? null,
    provider: snapshot.run.provider,
    model: snapshot.run.model,
    used_experiments: snapshot.run.usedExperiments,
    created_at: snapshot.run.startedAt,
    updated_at: snapshot.run.completedAt ?? snapshot.run.startedAt,
  };
}

function quantReportMarkdown(snapshot, candidate) {
  const metric = (value, digits = 1) => Number.isFinite(value) ? Number(value).toFixed(digits) : '—';
  const benchmark = snapshot.benchmark ?? {};
  const delta = Number.isFinite(candidate.metrics.annualizedReturn) && Number.isFinite(benchmark.annualizedReturn)
    ? candidate.metrics.annualizedReturn - benchmark.annualizedReturn
    : null;
  const trades = snapshot.trades.filter((trade) => trade.candidateId === candidate.id);
  const lines = [
    `# ${snapshot.scope.symbol} Strategy Report`, '', '## Research Context', '',
    `- Project: ${snapshot.project.title}`,
    `- Research question: ${snapshot.project.goal}`,
    `- Dataset: ${snapshot.dataset.name} · ${snapshot.scope.symbol} · ${snapshot.scope.interval}`,
    `- Research range: ${snapshot.scope.dateRange.start} to ${snapshot.scope.dateRange.end}`, '',
    '## Selected Strategy', '', `- Strategy: ${candidate.name}`, `- Parameters: ${candidate.parameters}`, '',
    '## Strategy vs Benchmark', '', '| Metric | Strategy | Benchmark | Difference |', '|---|---:|---:|---:|',
    `| Annual return | ${metric(candidate.metrics.annualizedReturn)}% | ${metric(benchmark.annualizedReturn)}% | ${metric(delta)}% |`,
    `| Sharpe | ${metric(candidate.metrics.sharpe, 2)} | ${metric(benchmark.sharpe, 2)} | — |`,
    `| Maximum drawdown | ${metric(candidate.metrics.maxDrawdown)}% | ${metric(benchmark.maxDrawdown)}% | — |`,
    `| Trades | ${candidate.metrics.trades} | ${benchmark.trades ?? '—'} | — |`, '',
    '## Run Conclusion and Recommendation', '', snapshot.report.conclusion, '',
    `**Recommendation:** ${snapshot.report.proposedNextStep}`, '', '## Validation', '',
    '- Holdout outcome: Not evaluated for this selected export candidate.', '', '## Limitations', '',
    ...snapshot.report.limitations.map((item) => `- ${item}`), '', '## Trades', '',
  ];
  if (trades.length) {
    lines.push('| Entry | Exit | Return | Holding period |', '|---|---|---:|---:|');
    for (const trade of trades) {
      const holding = 'holdingBars' in trade
        ? `${trade.holdingBars} bars · ${trade.holdingElapsedSeconds / 86_400 >= 1 ? `${Math.floor(trade.holdingElapsedSeconds / 86_400)}d${trade.holdingElapsedSeconds % 86_400 ? ` ${Math.floor((trade.holdingElapsedSeconds % 86_400) / 3_600)}h` : ''}` : `${trade.holdingElapsedSeconds / 3_600}h`}`
        : `${trade.holdingDays} days`;
      lines.push(`| ${trade.entryDate} | ${trade.exitDate} | ${metric(trade.returnPct)}% | ${holding} |`);
    }
  } else lines.push('No retained closed trades for this candidate.');
  lines.push('', '## Strategy Specification', '', '```yaml', candidate.strategySpec, '```', '');
  return lines.join('\n');
}

function quantEvidenceBundleJson(snapshot, candidate) {
  const selectionDecision = snapshot.report?.selectionDecision;
  const finalCandidateId = selectionDecision?.selectedCandidateId ?? snapshot.report?.generalization?.selectedCandidateId;
  const runContract = snapshot.dataset.contract === 'market-v2' ? 'quant-market-run-v2' : 'quant-daily-run-v1';
  const artifactRef = (role, content, candidateId = null, explicitId = null) => ({
    artifact_id: explicitId ?? `fixture-${snapshot.run.id}-${role}${candidateId ? `-${candidateId}` : ''}`,
    stored_digest: textDigest(JSON.stringify(content ?? null)),
  });
  const manifestEntry = (role, kind, reference, candidateId = null) => ({
    role,
    kind,
    artifact_id: reference.artifact_id,
    stored_digest: reference.stored_digest,
    ...(candidateId ? { candidate_id: candidateId } : {}),
  });
  const strategyParts = (item) => {
    const parsed = {};
    for (const line of String(item.strategySpec ?? '').split(/\r?\n/)) {
      const separator = line.indexOf(':');
      if (separator < 1) continue;
      const key = line.slice(0, separator).trim();
      const rawValue = line.slice(separator + 1).trim();
      if (key === 'family') continue;
      const numericValue = Number(rawValue);
      parsed[key] = rawValue !== '' && Number.isFinite(numericValue) ? numericValue : rawValue;
    }
    return parsed;
  };
  const strategyTemplate = (item) => String(item.strategySpec ?? '').match(/^family:\s*([^\n]+)/)?.[1] ?? 'fixture_strategy';
  const finalCandidate = snapshot.candidates.find((item) => item.id === finalCandidateId) ?? candidate;
  const reportRef = artifactRef('report', snapshot.report, null, snapshot.report?.id ?? `fixture-${snapshot.run.id}-report`);
  const comparisonContent = {
    evaluation_partition: 'train',
    benchmark: snapshot.benchmark ?? null,
    candidates: snapshot.candidates.map((item) => ({ candidate_id: item.id, ...item.metrics, walk_forward: snapshot.report?.walkForward ?? null })),
    ranking: snapshot.candidates.map((item) => item.id),
    walk_forward: snapshot.report?.walkForward ?? null,
  };
  const comparisonRef = artifactRef('final-training-comparison', comparisonContent);
  const generalization = snapshot.report?.generalization ?? {
    status: 'not_evaluated',
    reason: 'This deterministic fixture retains no separate sealed-holdout projection.',
    selected_candidate_id: finalCandidateId,
  };
  const researchDecision = {
    basis: selectionDecision?.basis ?? 'approved_objective_rank',
    selected_candidate_id: finalCandidateId,
    source_comparison_artifact_id: comparisonRef.artifact_id,
  };
  const robustnessContent = snapshot.report?.robustnessSensitivity ?? {
    schema_version: 'robustness_sensitivity_v1',
    evaluation_partition: 'train',
    run_id: snapshot.run.id,
    report_artifact_id: reportRef.artifact_id,
    candidate: { candidate_id: finalCandidate.id, template: strategyTemplate(finalCandidate), parameters: strategyParts(finalCandidate), canonical_key: textDigest(finalCandidate.strategySpec ?? finalCandidate.id) },
    final_training_comparison: { artifact_id: comparisonRef.artifact_id, artifact_digest: comparisonRef.stored_digest },
    dataset: { dataset_id: snapshot.dataset.id, dataset_digest: snapshot.dataset.digest },
    interval: snapshot.dataset.interval,
    periods_per_year: snapshot.dataset.periodsPerYear,
    training_split: { identity_kind: 'fixture_split', rule_version: 'fixture-v1' },
    execution_rule_version: 'fixture-quant-execution-v1',
    sampler_rule_version: 'fixture-oat-v1',
    cost_scenarios: [],
    parameter_neighbors: [],
    kernel_call_count: 0,
  };
  const robustnessRef = artifactRef('robustness-sensitivity', robustnessContent, finalCandidate.id);
  const candidateBundles = snapshot.candidates.map((item, index) => {
    const specContent = { template: strategyTemplate(item), parameters: strategyParts(item), strategy_spec: item.strategySpec, strategy_spec_version: item.strategySpecVersion };
    const backtestContent = { evaluation_partition: 'train', candidate_id: item.id, metrics: item.metrics };
    const curveContent = { candidate_id: item.id, points: snapshot.performanceSeries.find((series) => series.id === item.id)?.points ?? [] };
    const tradeContent = { candidate_id: item.id, trades: snapshot.trades.filter((trade) => trade.candidateId === item.id) };
    const strategyRef = artifactRef('strategy-spec', specContent, item.id);
    const backtestRef = artifactRef('backtest-result', backtestContent, item.id);
    const curveRef = artifactRef('equity-curve', curveContent, item.id);
    const tradeRef = artifactRef('trade-log', tradeContent, item.id);
    return {
      candidate: {
        candidate_id: item.id,
        ordinal: index + 1,
        name: item.name,
        hypothesis: item.evolution?.hypothesis ?? item.name,
        template: strategyTemplate(item),
        parameters: strategyParts(item),
        canonical_key: textDigest(item.strategySpec ?? item.id),
        state: 'completed',
        verdict: item.verdict,
        metrics: item.metrics,
        parent_candidate_id: null,
        change_rationale: item.evolution?.changeRationale ?? null,
        replan_decision: null,
        strategy_spec: strategyRef,
        backtest_result: backtestRef,
      },
      refs: { strategyRef, backtestRef, curveRef, tradeRef },
      contents: { specContent, backtestContent, curveContent, tradeContent },
    };
  });
  const artifactManifest = [
    manifestEntry('research_report', 'research_report', reportRef),
    manifestEntry('final_training_comparison', 'validation_report', comparisonRef),
    ...candidateBundles.flatMap(({ candidate: item, refs }) => [
      manifestEntry('strategy_spec', 'strategy_spec', refs.strategyRef, item.candidate_id),
      manifestEntry('backtest_result', 'backtest_result', refs.backtestRef, item.candidate_id),
      manifestEntry('equity_curve', 'equity_curve', refs.curveRef, item.candidate_id),
      manifestEntry('trade_log', 'trade_log', refs.tradeRef, item.candidate_id),
    ]),
    manifestEntry('robustness_sensitivity', 'robustness_sensitivity', robustnessRef, finalCandidate.id),
  ];
  const bundle = {
    schema_version: 'strategy_evidence_bundle_v1',
    run: {
      project_id: snapshot.project.id,
      run_id: snapshot.run.id,
      contract: runContract,
      attempt_number: snapshot.run.attemptNumber,
      mode: snapshot.run.mode,
      question: snapshot.project.goal,
      provider: snapshot.run.provider,
      model: snapshot.run.model,
      data_authenticity: snapshot.authenticity ?? snapshot.dataset.authenticity,
      created_at: snapshot.run.startedAt,
      updated_at: snapshot.run.completedAt ?? snapshot.project.updatedAt ?? snapshot.run.startedAt,
    },
    lineage: {
      parent_run_id: null,
      seed_candidate_id: null,
      refinement_reason: null,
      retry_of_run_id: null,
      retry_child_run_id: null,
      root_run_id: snapshot.run.id,
      version_number: 1,
      child_run_id: null,
      series_decision: null,
    },
    dataset: {
      contract: runContract,
      dataset_id: snapshot.dataset.id,
      dataset_digest: snapshot.dataset.digest,
      symbol: snapshot.scope.symbol,
      interval: snapshot.scope.interval,
      periods_per_year: snapshot.dataset.periodsPerYear,
      retained_range: { start: snapshot.scope.dateRange.start, end: snapshot.scope.dateRange.end, bar_count: snapshot.dataset.barCount },
      runtime_descriptor_digest: snapshot.dataset.runtimeDescriptorDigest,
      sealed_split_digest: snapshot.dataset.sealedSplitDigest,
      source_metadata: snapshot.dataset.source ?? null,
      data_quality: snapshot.dataset.quality ?? null,
      evaluation_split: generalization.split ?? null,
    },
    plan: {
      artifact: { artifact_id: artifactRef('plan', snapshot.researchPlan ?? snapshot.project, null, `fixture-${snapshot.run.id}-plan`).artifact_id },
      revision: snapshot.run.planRevision ?? 1,
      objective_summary: snapshot.researchPlan?.objectiveSummary ?? snapshot.project.goal,
      candidate_families: snapshot.researchPlan?.candidateFamilies ?? snapshot.candidates.map((item) => strategyTemplate(item)),
      selection_objective: snapshot.researchPlan?.selectionObjective ?? 'approved_objective_rank',
      completion_criteria: snapshot.researchPlan?.completionCriteria ?? ['Backtest all approved candidates and retain one final training comparison.'],
      budgets: { max_agent_iterations: snapshot.run.maxAgentIterations ?? 12, max_experiments: snapshot.run.usedExperiments, max_repairs: snapshot.run.usedRepairAttempts ?? 1 },
    },
    candidates: candidateBundles.map(({ candidate: item }) => item),
    final_training_comparison: {
      artifact: comparisonRef,
      ...comparisonContent,
    },
    selected_result: {
      candidate_id: finalCandidateId,
      research_decision: researchDecision,
      replan_decision: null,
      conclusion: snapshot.report?.conclusion,
      next_step: snapshot.report?.proposedNextStep,
      report: reportRef,
    },
    candidate_curves: candidateBundles.map(({ candidate: item, refs, contents }) => ({ candidate_id: item.candidate_id, artifact: refs.curveRef, points: contents.curveContent.points })),
    selected_candidate_trades: {
      candidate_id: finalCandidateId,
      artifact: candidateBundles.find(({ candidate: item }) => item.candidate_id === finalCandidateId)?.refs.tradeRef,
      rows: snapshot.trades.filter((trade) => trade.candidateId === finalCandidateId),
    },
    validation: {
      generalization,
      walk_forward: snapshot.report?.walkForward,
      robustness_sensitivity: { artifact: robustnessRef, content: robustnessContent },
    },
    limitations: snapshot.report?.limitations ?? [],
    artifact_manifest: artifactManifest,
  };
  return `${JSON.stringify(bundle, null, 2)}\n`;
}

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
function scope() {
  return { id: ID.scope, workspace_id: ID.workspace, investigation_id: ID.investigation, version_number: 1, decision_question: investigation().decision_question, source_scope_json: { source_connection_ids: [ID.githubSource], content_version_ids: [], allow_cloud_model: false }, time_range: { start: '2026-07-08T00:00:00Z', end: '2026-07-15T00:00:00Z' }, budget: { max_cost_usd: '4.0000', max_duration_seconds: 900 }, stop_conditions: ['Evidence and counter-evidence have both been reviewed.'], created_by: ID.owner, change_reason: 'Initial investigation scope.', created_at: NOW, data_authenticity: 'collected' };
}
function run() { return { id: ID.run, workspace_id: ID.workspace, investigation_id: ID.investigation, investigation_scope_version_id: ID.scope, state: state.runState, waiting_for_input_reason: null, graph_version: 'deterministic-cloud-v1', generation_method: 'deterministic', provider: 'deterministic', model: null, prompt_refs: [], trace_ref: null, run_input_manifest_digest: SHA('d'), budget: { max_cost_usd: '4.0000', max_duration_seconds: 900 }, used_cost_usd: '0.1000', attempt_number: 1, initiated_by: ID.owner, latest_sequence: state.latestSequence, row_version: state.runRowVersion, data_authenticity: 'collected', ...timestamps() }; }
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

function paperSnapshot() {
  const cash = 100000 - state.paperFills.reduce((total, fill) => total + Number(fill.notional), 0);
  const marketValue = state.paperPositions.reduce((total, position) => total + Number(position.market_value), 0);
  return {
    contract_version: 'qurio-paper-v1',
    environment: 'paper',
    account: {
      account_id: '00000000-0000-4000-8000-000000000901',
      workspace_id: ID.workspace,
      environment: 'paper',
      broker: 'local_simulator',
      currency: 'USD',
      status: 'active',
      cash: cash.toFixed(2),
      buying_power: cash.toFixed(2),
      equity: (cash + marketValue).toFixed(2),
      row_version: state.paperAccountVersion,
      last_reconciled_at: state.paperReconciledAt,
      updated_at: LATER,
    },
    positions: state.paperPositions,
    orders: state.paperOrders,
    fills: state.paperFills,
    legal_actions: ['create_draft', 'submit', 'cancel', 'reconcile'],
    generated_at: LATER,
  };
}

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
    if (req.method === 'POST' && path === '/fixture-reset') { resetFixtureState(); return send(res, 200, { reset: true }); }
    if (req.method === 'POST' && path === '/fixture-control') { requireValue(typeof payload.api_offline === 'boolean', 'Fixture control requires an explicit API offline state.'); state.apiOffline = payload.api_offline; return send(res, 200, { api_offline: state.apiOffline }); }
    if (req.method === 'GET' && path === '/fixture-state') return send(res, 200, { quant_fixture_state: quantFixtureState, quant_run_state: QUANT_FIXTURES[quantFixtureState].run.state, quant_run_mode: quantRunMode, quant_goal: quantGoal, quant_row_version: quantRowVersion, quant_project_row_version: quantProjectRowVersion, active_market_run_id: activeMarketRunId, api_offline: state.apiOffline, mutation_request_count: state.mutationRequestCount, sse_request_count: state.sseRequestCount, offline_mutation_request_count: state.offlineMutationRequestCount, offline_sse_request_count: state.offlineSseRequestCount, offline_export_request_count: state.offlineExportRequestCount, consent_preview_count: state.consentPreviewCount, consent_grant_attempts: state.consentGrantAttempts, consent_grant_count: state.consentGrantCount, upload_count: state.uploadCount, signal_transition_count: state.signalTransitionCount, signal_disposition: state.signalDisposition, investigation_status: state.investigationStatus, investigation_row_version: state.investigationRowVersion, run_state: state.runState, run_row_version: state.runRowVersion, latest_sequence: state.latestSequence, evidence_status: state.evidenceStatus, claim_status: state.claimStatus, synthesis_status: state.synthesisStatus, brief_status: state.briefStatus, export_post_count: state.exportPostCount, export_terminal_count: state.exportTerminalCount, export_idempotency_keys: state.exportIdempotencyKeys, export_timestamps: state.exportTimestamps });
    if (state.apiOffline) {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method)) state.offlineMutationRequestCount += 1;
      if (req.method === 'GET' && path.endsWith('/events')) state.offlineSseRequestCount += 1;
      if (req.method === 'POST' && path.endsWith('/exports')) state.offlineExportRequestCount += 1;
      return failCode(res, 'API_OFFLINE', 'Fixture API is offline.', 503);
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method)) state.mutationRequestCount += 1;
    if (req.method === 'POST' && path.startsWith('/quant/') && QUANT_MUTATION_DELAY_MS > 0) await new Promise((resolve) => globalThis.setTimeout(resolve, QUANT_MUTATION_DELAY_MS));
    if (req.method === 'GET' && path === '/paper/snapshot') return send(res, 200, paperSnapshot());
    if (req.method === 'POST' && path === '/paper/orders/drafts') {
      requireValue(payload?.order_type === 'market' && payload?.time_in_force === 'day', 'Paper fixture supports Market/Day only.');
      requireValue(payload?.expected_account_row_version === state.paperAccountVersion, 'Paper account version changed.');
      const referencePrice = '365.25';
      const order = {
        order_id: `00000000-0000-4000-8000-${String(910 + state.paperOrders.length).padStart(12, '0')}`,
        workspace_id: ID.workspace,
        environment: 'paper',
        broker: 'local_simulator',
        state: 'draft',
        source_run_id: payload.source_run_id,
        source_candidate_id: payload.source_candidate_id,
        source_evidence_digest: SHA('p'),
        symbol: 'SPY',
        side: payload.side,
        quantity: Number(payload.quantity).toFixed(8),
        filled_quantity: '0',
        order_type: 'market',
        time_in_force: 'day',
        limit_price: null,
        reference_price: referencePrice,
        estimated_notional: (Number(payload.quantity) * Number(referencePrice)).toFixed(2),
        average_fill_price: null,
        external_order_id: null,
        rejection_reason: null,
        row_version: 1,
        created_at: LATER,
        updated_at: LATER,
        submitted_at: null,
        filled_at: null,
        cancelled_at: null,
      };
      state.paperOrders.unshift(order);
      return send(res, 201, order);
    }
    const paperSubmit = path.match(/^\/paper\/orders\/([^/]+)\/submit$/);
    if (req.method === 'POST' && paperSubmit) {
      const order = state.paperOrders.find((item) => item.order_id === decodeURIComponent(paperSubmit[1]));
      requireValue(order?.state === 'draft', 'Paper order must be a draft.');
      requireValue(payload?.expected_order_row_version === order.row_version, 'Paper order version changed.');
      requireValue(payload?.expected_account_row_version === state.paperAccountVersion, 'Paper account version changed.');
      order.state = 'filled';
      order.filled_quantity = order.quantity;
      order.average_fill_price = order.reference_price;
      order.row_version += 1;
      order.submitted_at = LATER;
      order.filled_at = LATER;
      state.paperAccountVersion += 1;
      const notional = (Number(order.quantity) * Number(order.reference_price)).toFixed(2);
      state.paperPositions = [{
        symbol: order.symbol,
        quantity: order.quantity,
        average_entry_price: order.reference_price,
        current_price: order.reference_price,
        market_value: notional,
        unrealized_pl: '0.00',
        updated_at: LATER,
      }];
      state.paperFills = [{
        fill_id: '00000000-0000-4000-8000-000000000920',
        order_id: order.order_id,
        workspace_id: ID.workspace,
        symbol: order.symbol,
        side: order.side,
        quantity: order.quantity,
        price: order.reference_price,
        notional,
        occurred_at: LATER,
      }];
      return send(res, 200, order);
    }
    if (req.method === 'POST' && path === '/paper/reconcile') {
      requireValue(payload?.expected_account_row_version === state.paperAccountVersion, 'Paper account version changed.');
      state.paperAccountVersion += 1;
      state.paperReconciledAt = LATER;
      return send(res, 200, paperSnapshot());
    }
    if (req.method === 'GET' && path === '/quant/workspace-snapshot') {
      if (QUANT_DELAY_MS > 0) await new Promise((resolve) => globalThis.setTimeout(resolve, QUANT_DELAY_MS));
      if (activeMarketRunId) {
        let activeMarketSnapshot = dynamicMarketRunDirectory.get(activeMarketRunId);
        if (!activeMarketSnapshot) return failCode(res, 'NOT_FOUND', 'Active Market Run was not found.', 404);
        const reads = (dynamicMarketSnapshotReads.get(activeMarketRunId) ?? 0) + 1;
        dynamicMarketSnapshotReads.set(activeMarketRunId, reads);
        if (activeMarketSnapshot.run.state === 'running_experiments' && reads >= 3) {
          const prior = activeMarketSnapshot;
          activeMarketSnapshot = marketSnapshot('quant-completed', prior.run.id, prior.project.goal, prior.run.mode, prior.dataset.id, prior.scope.dateRange);
          activeMarketSnapshot.project.id = prior.project.id;
          activeMarketSnapshot.run.attemptNumber = prior.run.attemptNumber;
          activeMarketSnapshot.run.retryOfRunId = prior.run.retryOfRunId;
          activeMarketSnapshot.run.continuedFrom = prior.run.continuedFrom;
          activeMarketSnapshot.run.rowVersion = quantRowVersion;
          if (activeMarketSnapshot.run.continuedFrom || activeMarketSnapshot.run.retryOfRunId) markMarketSnapshotWithoutHoldout(activeMarketSnapshot);
          dynamicMarketRunDirectory.set(activeMarketRunId, activeMarketSnapshot);
        }
        return send(res, 200, cloneFixtureValue(activeMarketSnapshot));
      }
      const snapshot = JSON.parse(JSON.stringify(QUANT_FIXTURES[quantFixtureState]));
      if (quantFixtureState === 'quant-completed' && snapshot.report) {
        snapshot.report.selectedCandidateId = 'candidate-b';
      }
      snapshot.run.rowVersion = quantRowVersion;
      snapshot.run.mode = quantRunMode;
      snapshot.project.goal = quantGoal;
      return send(res, 200, snapshot);
    }
    if (req.method === 'GET' && path === '/quant/projects') {
      const projectSnapshots = allQuantSnapshots();
      return send(res, 200, projectSnapshots.filter((snapshot, index, rows) => rows.findIndex((item) => item.project.id === snapshot.project.id) === index).map((snapshot) => ({
        id: snapshot.project.id,
        name: snapshot.project.title,
        objective: snapshot.project.goal,
        status: 'active',
        row_version: quantProjectRowVersion,
        created_at: snapshot.run.startedAt,
        updated_at: snapshot.project.updatedAt,
      })));
    }
    if (req.method === 'GET' && path === '/quant/runs') {
      const requestedProjectId = requestUrl.searchParams.get('project_id');
      const runs = quantHistoryFixtures()
        .filter((snapshot) => !requestedProjectId || requestedProjectId === snapshot.project.id)
        .map(quantHistoryRow);
      return send(res, 200, runs);
    }
    if (req.method === 'GET' && path === '/quant/market-runs') {
      const requestedProjectId = requestUrl.searchParams.get('project_id');
      const snapshots = publicMarketSnapshots();
      return send(res, 200, snapshots.filter((snapshot) => !requestedProjectId || requestedProjectId === snapshot.project.id).map(marketRunDto));
    }
    if (req.method === 'GET' && /^\/quant\/runs\/[^/]+\/workspace-snapshot$/.test(path)) {
      const runId = decodeURIComponent(path.split('/')[3]);
      const snapshot = allQuantSnapshots().find((item) => item.run.id === runId);
      if (!snapshot) return failCode(res, 'NOT_FOUND', 'Quant Run was not found.', 404);
      return send(res, 200, snapshot);
    }
    if (req.method === 'POST' && path === '/quant/strategy-report-exports/preview') {
      requireValue(payload?.export_type === 'strategy_report_markdown' || payload?.export_type === 'strategy_evidence_bundle_json', 'Unsupported Quant report export type.');
      const snapshot = allQuantSnapshots().find((item) => item.run.id === payload.run_id);
      if (!snapshot?.report) return failCode(res, 'NOT_FOUND', 'Strategy Report was not found.', 404);
      const candidate = snapshot.candidates.find((item) => item.id === payload.candidate_id);
      if (!candidate) return failCode(res, 'INVALID_STATE', 'Candidate does not belong to this Run.', 409);
      const safeSymbol = snapshot.scope.symbol.toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
      if (payload.export_type === 'strategy_evidence_bundle_json') {
        const finalCandidateId = snapshot.report.selectionDecision?.selectedCandidateId;
        if (!finalCandidateId || finalCandidateId !== candidate.id || (snapshot.report.generalization?.selectedCandidateId && snapshot.report.generalization.selectedCandidateId !== finalCandidateId)) {
          return failCode(res, 'INVALID_STATE', 'Evidence bundle is available for the final selected strategy only.', 409);
        }
        const renderedContent = quantEvidenceBundleJson(snapshot, candidate);
        return send(res, 200, {
          export_type: 'strategy_evidence_bundle_json', run_id: snapshot.run.id, candidate_id: candidate.id,
          data_authenticity: snapshot.dataset.authenticity,
          filename: `qurio-${safeSymbol}-evidence-${snapshot.run.id.slice(0, 8)}.json`, media_type: 'application/json',
          rendered_content: renderedContent, content_digest: textDigest(renderedContent),
        });
      }
      const renderedContent = quantReportMarkdown(snapshot, candidate);
      return send(res, 200, {
        export_type: 'strategy_report_markdown', run_id: snapshot.run.id, candidate_id: candidate.id,
        data_authenticity: snapshot.dataset.authenticity,
        filename: `${safeSymbol}-strategy-report-${snapshot.run.id.slice(0, 8)}.md`, media_type: 'text/markdown',
        rendered_content: renderedContent, content_digest: textDigest(renderedContent),
      });
    }
    if (req.method === 'GET' && path === '/quant/connectors') return send(res, 200, quantConnectorDirectory);
    if (req.method === 'POST' && path === '/quant/connectors/kraken-spot-ohlc-v1/fetch') {
      if (QUANT_FAILURE === 'rate-limit') return failCode(res, 'RATE_LIMITED', '429 Too Many Requests from Kraken Spot.', 429);
      const { dataset, bars } = buildKrakenConnectorDataset(payload);
      upsertMarketDataset(dataset, bars);
      return send(res, 201, marketDatasetResponse(dataset, req.headers['x-fixture-contract-mode'] === 'response-model'));
    }
    if (req.method === 'GET' && path === '/quant/datasets') return send(res, 200, quantDatasets);
    if (req.method === 'GET' && path === '/quant/datasets/v2') {
      const contractMode = req.headers['x-fixture-contract-mode'] === 'response-model';
      return send(res, 200, quantMarketDatasets.map((dataset) => marketDatasetResponse(dataset, contractMode)));
    }
    const marketDatasetRoute = path.match(/^\/quant\/datasets\/v2\/([^/]+)$/);
    if (req.method === 'GET' && marketDatasetRoute) {
      const dataset = quantMarketDatasets.find((item) => item.dataset_id === decodeURIComponent(marketDatasetRoute[1]));
      if (!dataset) return failCode(res, 'NOT_FOUND', 'Market Dataset was not found.', 404);
      return send(res, 200, marketDatasetResponse(dataset, req.headers['x-fixture-contract-mode'] === 'response-model'));
    }
    const marketPreviewRoute = path.match(/^\/quant\/datasets\/v2\/([^/]+)\/preview$/);
    if (req.method === 'GET' && marketPreviewRoute) {
      const dataset = quantMarketDatasets.find((item) => item.dataset_id === decodeURIComponent(marketPreviewRoute[1]));
      if (!dataset) return failCode(res, 'NOT_FOUND', 'Market Dataset was not found.', 404);
      const maxPoints = Math.max(1, Math.min(400, Number(requestUrl.searchParams.get('max_points') ?? 240)));
      const bars = (quantMarketPreviewBars.get(dataset.dataset_id) ?? buildDefaultMarketPreviewBars(dataset)).slice(-maxPoints);
      const contractMode = req.headers['x-fixture-contract-mode'] === 'response-model';
      const responseDataset = marketDatasetResponse(dataset, contractMode);
      if (contractMode) {
        return send(res, 200, {
          dataset: responseDataset,
          data_authenticity: responseDataset.data_authenticity,
          total_bar_count: dataset.bar_count,
          returned_bar_count: bars.length,
          max_points: maxPoints,
          sampling_rule: 'latest_contiguous',
          bars,
        });
      }
      return send(res, 200, { dataset: responseDataset, symbol: dataset.symbol, interval: dataset.interval, covered_start: dataset.covered_start, covered_end: dataset.covered_end, data_authenticity: responseDataset.data_authenticity, total_bar_count: dataset.bar_count, returned_bar_count: bars.length, max_points: maxPoints, sampling_rule: 'latest_contiguous', bars });
    }
    if (req.method === 'GET' && /^\/quant\/datasets\/[^/]+\/preview$/.test(path)) {
      const datasetId = decodeURIComponent(path.split('/')[3]);
      const dataset = quantDatasets.find((item) => item.dataset_id === datasetId);
      if (!dataset) return failCode(res, 'NOT_FOUND', 'Quant Dataset was not found.', 404);
      const maxPoints = Math.max(50, Math.min(400, Number(requestUrl.searchParams.get('max_points') ?? 240)));
      const bars = (quantPreviewBars.get(datasetId) ?? []).slice(-maxPoints);
      return send(res, 200, { dataset_id: dataset.dataset_id, symbol: dataset.symbol, interval: dataset.interval, data_authenticity: dataset.data_authenticity, covered_start: dataset.covered_start, covered_end: dataset.covered_end, total_bar_count: dataset.bar_count, returned_bar_count: bars.length, max_points: maxPoints, sampling_rule: 'latest_contiguous', bars });
    }
    if (req.method === 'POST' && path === '/quant/datasets/v2/import-csv') {
      requireValue(
        typeof payload.name === 'string'
          && typeof payload.symbol === 'string'
          && typeof payload.interval === 'string'
          && typeof payload.csv_text === 'string',
        'Market CSV fixture import requires name, symbol, interval, and csv_text.',
      );
      const interval = payload.interval;
      requireValue(['1h', '4h', '1D'].includes(interval), 'Market CSV fixture import only supports 1h, 4h, or 1D.');
      const { dataset, bars } = buildMarketCsvDataset(payload);
      const existing = quantMarketDatasets.find((item) => item.dataset_id === dataset.dataset_id);
      if (existing) {
        const sameRequest = existing.name === dataset.name
          && existing.symbol === dataset.symbol
          && existing.interval === dataset.interval
          && existing.evidence.file_name === dataset.evidence.file_name
          && existing.evidence.source_name === dataset.evidence.source_name
          && (existing.evidence.source_reference ?? null) === (dataset.evidence.source_reference ?? null)
          && existing.evidence.submitted_csv_digest === dataset.evidence.submitted_csv_digest;
        if (!sameRequest) {
          return failCode(res, 'IMMUTABLE_CONFLICT', 'Market CSV content already exists with different immutable source evidence.', 409);
        }
        return send(res, 201, existing);
      }
      upsertMarketDataset(dataset, bars);
      return send(res, 201, dataset);
    }
    if (req.method === 'POST' && path === '/quant/datasets/v2/fetch-binance') {
      if (QUANT_FAILURE === 'rate-limit') return failCode(res, 'RATE_LIMITED', '429 Too Many Requests from Binance Spot.', 429);
      requireValue(typeof payload.interval === 'string', 'Market Binance fixture fetch requires interval.');
      requireValue(['1h', '4h', '1D'].includes(payload.interval), 'Market Binance fixture fetch only supports 1h, 4h, or 1D.');
      const { dataset, bars } = buildMarketBinanceDataset(payload);
      upsertMarketDataset(dataset, bars);
      return send(res, 201, marketDatasetResponse(dataset, req.headers['x-fixture-contract-mode'] === 'response-model'));
    }
    if (req.method === 'POST' && path === '/quant/datasets/import-csv') {
      requireValue(typeof payload.name === 'string' && typeof payload.symbol === 'string' && typeof payload.csv_text === 'string', 'CSV fixture import requires name, symbol, and csv_text.');
      const dataset = registerQuantDataset(quantDatasetDto({
        id: `fixture-csv-${quantDatasets.length + 1}`,
        name: payload.name.trim(),
        symbol: payload.symbol.trim().toUpperCase(),
        barCount: Math.max(252, payload.csv_text.trim().split(/\r?\n/).length - 1),
        sourceMetadata: { kind: 'csv_upload', file_name: payload.file_name ?? null, source_name: payload.source_name ?? 'User-provided CSV', source_reference: payload.source_reference ?? null, submitted_csv_digest: textDigest(payload.csv_text), market_calendar: payload.market_calendar ?? 'unknown', time_zone: payload.time_zone ?? 'UTC', price_adjustment: payload.price_adjustment ?? 'unknown' },
      }));
      quantDatasets.push(dataset);
      return send(res, 201, dataset);
    }
    if (req.method === 'POST' && path === '/quant/datasets/fetch-binance-spot') {
      if (QUANT_FAILURE === 'rate-limit') return failCode(res, 'RATE_LIMITED', '429 Too Many Requests from Binance Spot.', 429);
      const symbol = String(payload.symbol ?? 'BTCUSDT').toUpperCase();
      const limit = Number(payload.limit ?? 365);
      const dataset = registerQuantDataset(quantDatasetDto({
        id: `fixture-binance-${symbol.toLowerCase()}`,
        name: `${symbol} Binance Spot fixture`, symbol, barCount: limit,
        sourceMetadata: { kind: 'provider_fetch', source_name: 'Binance Spot deterministic fixture', source_reference: `fixture://binance/${symbol}`, submitted_csv_digest: null, market_calendar: '24x7', time_zone: 'UTC', price_adjustment: 'unadjusted', provider_id: 'binance_spot', provider_response_attestations: [{ kind: 'provider_response', digest: textDigest(`binance:${symbol}:${limit}`), source_reference: `fixture://binance/${symbol}` }], retrieved_at: NOW, requested_limit: limit, returned_bar_count: limit, dropped_incomplete_count: 0, normalization_note: 'Deterministic fixture; no provider network call.', attestation_status: 'verified' },
      }));
      quantDatasets.push(dataset);
      return send(res, 201, dataset);
    }
    if (req.method === 'POST' && path === '/quant/datasets/fetch-nasdaq-equity') {
      if (QUANT_FAILURE === 'rate-limit') return failCode(res, 'RATE_LIMITED', '429 Too Many Requests from Nasdaq Equity.', 429);
      const symbol = String(payload.symbol ?? 'AAPL').toUpperCase();
      const limit = Math.max(370, Math.min(3650, Number(payload.lookback_days ?? 730)));
      const dataset = registerQuantDataset(quantDatasetDto({
        id: `fixture-nasdaq-${symbol.toLowerCase()}`,
        name: `${symbol} Nasdaq Equity fixture`, symbol, barCount: Math.min(limit, 730),
        sourceMetadata: { kind: 'provider_fetch', source_name: 'Nasdaq Equity deterministic fixture', source_reference: `fixture://nasdaq/${symbol}`, submitted_csv_digest: null, market_calendar: 'XNAS', time_zone: 'America/New_York', price_adjustment: 'split_adjusted', provider_id: 'nasdaq_equity', provider_response_attestations: [{ kind: 'provider_response', digest: textDigest(`nasdaq:${symbol}:${limit}`), source_reference: `fixture://nasdaq/${symbol}` }], retrieved_at: NOW, requested_limit: limit, returned_bar_count: Math.min(limit, 730), dropped_incomplete_count: 0, normalization_note: 'Deterministic fixture; no provider network call.', attestation_status: 'verified', price_adjustment_verification_status: 'verified' },
      }));
      quantDatasets.push(dataset);
      return send(res, 201, dataset);
    }
    if (req.method === 'POST' && path === '/quant/projects') {
      if (QUANT_FAILURE === 'provider-timeout') return failCode(res, 'PROVIDER_TIMEOUT', 'DeepSeek request timed out before producing a decision.', 504);
      requireValue(typeof payload.name === 'string' && typeof payload.objective === 'string', 'Quant Project creation requires name and objective.');
      quantProjectRowVersion += 1;
      return send(res, 201, { id: '00000000-0000-4000-8000-000000000301', workspace_id: ID.workspace, name: payload.name, objective: payload.objective, status: 'active', row_version: quantProjectRowVersion, data_authenticity: 'human_authored', ...timestamps() });
    }
    if (req.method === 'POST' && path === '/quant/runs') {
      requireValue(payload.project_id === '00000000-0000-4000-8000-000000000301', 'Quant Run must reference the created fixture Project.');
      requireValue(payload.expected_project_row_version === quantProjectRowVersion, 'Quant Run must pin the created Project row version.');
      requireValue(quantDatasets.some((dataset) => dataset.dataset_id === payload.dataset_id), 'Quant Run must pin an available fixture dataset.');
      requireValue(['plan', 'auto'].includes(payload.mode), 'Quant Run mode must be plan or auto.');
      const selectedDataset = quantDatasets.find((dataset) => dataset.dataset_id === payload.dataset_id);
      requireValue(typeof payload.research_start === 'string' && typeof payload.research_end === 'string', 'Quant Run must pin a research range.');
      requireValue(payload.research_start >= selectedDataset.covered_start && payload.research_end <= selectedDataset.covered_end && payload.research_start <= payload.research_end, 'Quant Run research range must stay inside dataset coverage.');
      quantGoal = String(payload.question).trim();
      quantRunMode = payload.mode === 'auto' ? 'auto_research' : 'plan';
      quantFixtureState = payload.mode === 'auto' ? 'quant-running' : 'quant-plan-approval';
      quantRowVersion += 1;
      return send(res, 201, { id: '00000000-0000-4000-8000-000000000302', workspace_id: ID.workspace, project_id: payload.project_id, dataset_id: payload.dataset_id, dataset_digest: selectedDataset.digest, research_start: payload.research_start, research_end: payload.research_end, state: payload.mode === 'auto' ? 'running_experiments' : 'waiting_plan_approval', mode: payload.mode, question: quantGoal, plan_revision: 1, attempt_number: 1, retry_of_run_id: null, latest_sequence: 0, trace_id: 'fixture-new-run', failure_reason: null, row_version: quantRowVersion, data_authenticity: 'human_authored', ...timestamps() });
    }
    if (req.method === 'POST' && path === '/quant/market-runs') {
      const lineage = [payload.parent_run_id, payload.seed_candidate_id, payload.refinement_reason];
      const hasLineage = lineage.some((value) => value !== undefined && value !== null);
      requireValue(!hasLineage || lineage.every((value) => value !== undefined && value !== null), 'Market continuation requires parent, seed candidate and reason together.');
      const source = hasLineage
        ? publicMarketSnapshots().find((snapshot) => snapshot.run.id === payload.parent_run_id)
        : null;
      if (hasLineage) {
        requireValue(source && ['completed', 'failed', 'cancelled'].includes(source.run.state), 'Market continuation requires a terminal public source Run.');
        requireValue(payload.project_id === source.project.id, 'Market continuation must stay in the source Project.');
        requireValue(payload.dataset_id === source.dataset.id, 'Market continuation must retain the source dataset.');
        const seed = source.candidates.find((candidate) => candidate.id === payload.seed_candidate_id);
        requireValue(seed?.canSeedResearch === true, 'Market continuation requires a server-projected seedable candidate.');
        requireValue(typeof payload.refinement_reason === 'string' && payload.refinement_reason.trim().length > 0, 'Market continuation requires a reason.');
      } else {
        requireValue(payload.project_id === '00000000-0000-4000-8000-000000000301', 'Market Run must reference the created fixture Project.');
      }
      requireValue(payload.expected_project_row_version === quantProjectRowVersion, 'Market Run must pin the created Project row version.');
      const identity = marketIdentity(payload.dataset_id);
      const requestedStart = Date.parse(payload.research_start_utc);
      const requestedEnd = Date.parse(payload.research_end_utc);
      const coverageStart = Date.parse(identity.start);
      const coverageEnd = Date.parse(identity.end);
      const cadenceMs = identity.stepHours * 60 * 60 * 1000;
      requireValue(Number.isFinite(requestedStart) && Number.isFinite(requestedEnd), 'Market Run must use valid UTC timestamps.');
      requireValue(requestedStart >= coverageStart && requestedEnd <= coverageEnd && requestedStart <= requestedEnd, 'Market Run range must stay inside stored UTC coverage.');
      requireValue((requestedStart - coverageStart) % cadenceMs === 0 && (requestedEnd - coverageStart) % cadenceMs === 0, 'Market Run range must align to stored bars.');
      requireValue(
        Math.floor((requestedEnd - requestedStart) / cadenceMs) + 1 >= marketRequiredBars(identity.interval, identity.periodsPerYear),
        `Market Run range must contain at least ${marketRequiredBars(identity.interval, identity.periodsPerYear)} bars.`,
      );
      requireValue(['plan', 'auto'].includes(payload.mode), 'Market Run mode must be plan or auto.');
      const marketGoal = String(payload.question).trim();
      const marketMode = payload.mode === 'auto' ? 'auto_research' : 'plan';
      quantRowVersion += 1;
      const researchRange = { start: payload.research_start_utc, end: payload.research_end_utc };
      const dynamicRunId = source ? MARKET_CHILD_RUN_ID : MARKET_RUN_ID;
      const activeMarketSnapshot = marketSnapshot(payload.mode === 'auto' ? 'quant-running' : 'quant-plan-approval', dynamicRunId, marketGoal, marketMode, identity.datasetId, researchRange);
      activeMarketSnapshot.project.id = payload.project_id;
      if (source) activeMarketSnapshot.run.continuedFrom = {
        parentRunId: source.run.id,
        seedCandidateId: payload.seed_candidate_id,
        candidateName: source.candidates.find((candidate) => candidate.id === payload.seed_candidate_id).name,
        sourceQuestion: source.project.goal,
        reason: payload.refinement_reason.trim(),
      };
      activeMarketSnapshot.run.rowVersion = quantRowVersion;
      activeMarketRunId = activeMarketSnapshot.run.id;
      dynamicMarketRunDirectory.set(activeMarketSnapshot.run.id, activeMarketSnapshot);
      dynamicMarketSnapshotReads.set(activeMarketSnapshot.run.id, 0);
      return send(res, 201, marketRunDto(activeMarketSnapshot));
    }
    const marketMutation = path.match(/^\/quant\/market-runs\/([^/]+)\/(approve-plan|request-plan-changes|cancel|retry)$/);
    if (req.method === 'POST' && marketMutation) {
      const runId = decodeURIComponent(marketMutation[1]);
      const action = marketMutation[2];
      const activeMarketSnapshot = activeMarketRunId ? dynamicMarketRunDirectory.get(activeMarketRunId) : null;
      if (!activeMarketSnapshot || activeMarketSnapshot.run.id !== runId) return failCode(res, 'NOT_FOUND', 'Market Run was not found.', 404);
      requireValue(payload.expected_row_version === activeMarketSnapshot.run.rowVersion, 'Market Run mutation must pin row version.');
      if (action === 'approve-plan' || action === 'request-plan-changes') requireValue(payload.plan_revision === activeMarketSnapshot.run.planRevision, 'Market Run plan mutation must pin plan revision.');
      const prior = activeMarketSnapshot;
      quantRowVersion += 1;
      let nextMarketSnapshot;
      if (action === 'request-plan-changes') {
        nextMarketSnapshot = marketSnapshot('quant-plan-approval', runId, prior.project.goal, 'plan', prior.dataset.id, prior.scope.dateRange);
        nextMarketSnapshot.run.planRevision = prior.run.planRevision + 1;
      } else if (action === 'approve-plan') {
        nextMarketSnapshot = marketSnapshot('quant-running', runId, prior.project.goal, 'plan', prior.dataset.id, prior.scope.dateRange);
      } else if (action === 'cancel') {
        nextMarketSnapshot = marketSnapshot('quant-cancelled', runId, prior.project.goal, prior.run.mode, prior.dataset.id, prior.scope.dateRange);
      } else {
        nextMarketSnapshot = marketSnapshot('quant-running', MARKET_DYNAMIC_RETRY_RUN_ID, prior.project.goal, prior.run.mode, prior.dataset.id, prior.scope.dateRange);
        nextMarketSnapshot.run.attemptNumber = prior.run.attemptNumber + 1;
        nextMarketSnapshot.run.retryOfRunId = prior.run.id;
      }
      nextMarketSnapshot.project.id = prior.project.id;
      nextMarketSnapshot.run.continuedFrom = prior.run.continuedFrom;
      nextMarketSnapshot.run.rowVersion = quantRowVersion;
      activeMarketRunId = nextMarketSnapshot.run.id;
      dynamicMarketRunDirectory.set(nextMarketSnapshot.run.id, nextMarketSnapshot);
      dynamicMarketSnapshotReads.set(nextMarketSnapshot.run.id, 0);
      return send(res, 200, marketRunDto(nextMarketSnapshot));
    }
    if (req.method === 'POST' && path === '/quant/workspace-snapshot/commands') {
      if (QUANT_FAILURE === 'provider-timeout') return failCode(res, 'PROVIDER_TIMEOUT', 'DeepSeek request timed out before producing a decision.', 504);
      const snapshot = JSON.parse(JSON.stringify(QUANT_FIXTURES[quantFixtureState]));
      const legal = [...snapshot.run.legalCommands, ...snapshot.composerLegalCommands];
      requireValue(payload.expected_row_version === quantRowVersion, 'Quant fixture command must pin the current row version.');
      requireValue(legal.includes(payload.command), 'Quant fixture command is not legal for the current snapshot.');
      const submittedGoal = payload.payload?.goal;
      if (submittedGoal !== undefined) {
        requireValue(['ask', 'generate_plan'].includes(payload.command), 'Approved Quant goal cannot change during execution.');
        requireValue(typeof submittedGoal === 'string' && submittedGoal.trim().length >= 1 && submittedGoal.trim().length <= 2000, 'Quant goal must contain 1 to 2000 characters.');
        quantGoal = submittedGoal.trim();
      }
      quantFixtureState = {
        ask: quantFixtureState,
        generate_plan: 'quant-plan-approval',
        approve_plan: 'quant-running',
        run_fixture: 'quant-waiting-review',
        request_plan_changes: 'quant-plan-approval',
        cancel_run: 'quant-cancelled',
        retry_run: 'quant-ready',
        complete_review: 'quant-completed',
      }[payload.command];
      quantRowVersion += 1;
      const next = JSON.parse(JSON.stringify(QUANT_FIXTURES[quantFixtureState]));
      next.run.rowVersion = quantRowVersion;
      next.project.goal = quantGoal;
      return send(res, 200, next);
    }
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
