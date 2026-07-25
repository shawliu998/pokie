import { describe, expect, it } from 'vitest';
import { parseQuantMarketDataset, parseQuantMarketDatasetPreview, parseQuantMarketRun } from './quant-market-parser';

const sha = (value: string) => `sha256:${value.repeat(64)}`;

const marketDataset = {
  schema_version: 'quant-market-bars-v2',
  dataset_id: 'market-dataset-4h',
  name: 'BTCUSDT 4 hour',
  symbol: 'BTCUSDT',
  interval: '4h',
  covered_start: '2024-01-01T00:00:00+00:00',
  covered_end: '2024-12-31T20:00:00+00:00',
  bar_count: 2196,
  digest: sha('a'),
  record_digest: sha('b'),
  periods_per_year: 2190,
  market_calendar: '24x7',
  market_session: 'continuous',
  time_zone: 'UTC',
  research_eligible: true,
  data_authenticity: 'collected',
  created_at: '2026-07-22T00:00:00+00:00',
  evidence: {
    source_kind: 'provider_fetch',
    source_name: 'Binance Spot public market data',
    source_reference: 'binance:/api/v3/klines?symbol=BTCUSDT&interval=4h',
    file_name: null,
    normalizer_version: 'binance-market-bars-v2',
    retrieved_at_utc: '2026-07-22T00:00:00+00:00',
    requested_bar_count: 2196,
    returned_bar_count: 2196,
    retained_bar_count: 2196,
    closed_dropped_count: 0,
    deduplicated_count: 0,
    batch_digest: sha('e'),
    termination_reason: 'requested_limit',
    target_satisfied: true,
  },
  quality: { status: 'accepted', cadence_gap_count: 0, normalization_note: 'Contiguous 4h UTC bars.' },
} as const;

const marketRun = {
  schema_version: 'quant-market-run-v2', id: 'market-run-4h', row_version: 2,
  project_id: 'project-market', dataset_id: marketDataset.dataset_id, dataset_digest: marketDataset.digest,
  symbol: 'BTCUSDT', interval: '4h', periods_per_year: 2190,
  research_start_utc: marketDataset.covered_start, research_end_utc: marketDataset.covered_end,
  runtime_descriptor_digest: sha('c'), sealed_split_digest: sha('d'), state: 'waiting_plan_approval',
  mode: 'plan', question: 'Test interpretable 4h strategies.', plan_revision: 1, attempt_number: 1,
  parent_run_id: null, seed_candidate_id: null, refinement_reason: null, retry_of_run_id: null,
  provider: 'deepseek', model: 'deepseek-chat', used_experiments: 0,
  created_at: '2026-07-22T00:00:00+00:00', updated_at: '2026-07-22T00:01:00+00:00',
} as const;

describe('public market dataset and run parsers', () => {
  it('retains the v2 discriminant, cadence, UTC identity and Decimal preview wire values', () => {
    expect(parseQuantMarketDataset(marketDataset)).toMatchObject({ contract: 'market-v2', interval: '4h', periodsPerYear: 2190, researchEligible: true, authenticity: 'collected', source: { batchDigest: sha('e') } });
    const preview = parseQuantMarketDatasetPreview({
      dataset: marketDataset, total_bar_count: 2196, returned_bar_count: 2, max_points: 240,
      data_authenticity: marketDataset.data_authenticity,
      sampling_rule: 'latest_contiguous',
      bars: [
        { timestamp: '2024-12-31T16:00:00+00:00', open: '93250.12345678', high: '94000.00000000', low: '92800.50000000', close: '93600.12340000', volume: '12.345678901234567890' },
        { timestamp: '2024-12-31T20:00:00+00:00', open: '93600.12340000', high: '94500.00000000', low: '93000.00000000', close: '94100.87654321', volume: '9.000000000000000001' },
      ],
    });
    expect(preview.authenticity).toBe('collected');
    expect(preview.bars[0]).toMatchObject({ date: '2024-12-31T16:00:00+00:00', decimalValues: { open: '93250.12345678', volume: '12.345678901234567890' } });
    expect(() => parseQuantMarketDatasetPreview({
      dataset: marketDataset,
      data_authenticity: 'imported',
      total_bar_count: 2196,
      returned_bar_count: 1,
      max_points: 1,
      sampling_rule: 'latest_contiguous',
      bars: [{ timestamp: '2024-12-31T20:00:00+00:00', open: '1', high: '2', low: '1', close: '1.5', volume: '1' }],
    })).toThrow('differs');
  });

  it('parses the dedicated public market run without converting its UTC range to dates', () => {
    expect(parseQuantMarketRun(marketRun)).toMatchObject({ contract: 'market-v2-public', interval: '4h', periodsPerYear: 2190, researchStartUtc: marketDataset.covered_start, planRevision: 1, parentRunId: null, seedCandidateId: null, refinementReason: null, retryOfRunId: null, researchLoop: null, researchSeries: null });
    expect(parseQuantMarketRun({
      ...marketRun,
      id: 'market-run-child',
      parent_run_id: marketRun.id,
      seed_candidate_id: 'candidate-b',
      refinement_reason: 'Reduce drawdown while retaining the source cadence.',
    })).toMatchObject({ parentRunId: marketRun.id, seedCandidateId: 'candidate-b', refinementReason: 'Reduce drawdown while retaining the source cadence.' });
    expect(() => parseQuantMarketRun({ ...marketRun, parent_run_id: undefined })).toThrow('parent_run_id');
    expect(() => parseQuantMarketRun({ ...marketRun, parent_run_id: marketRun.id })).toThrow('supplied together');
    expect(() => parseQuantMarketRun({ ...marketRun, parent_run_id: marketRun.id, seed_candidate_id: 'candidate-b' })).toThrow('supplied together');
    expect(() => parseQuantMarketRun({ ...marketRun, parent_run_id: marketRun.id, seed_candidate_id: 'candidate-b', refinement_reason: '   ' })).toThrow('refinement_reason');
    expect(() => parseQuantMarketRun({ ...marketRun, retry_of_run_id: 7 })).toThrow('retry_of_run_id');
  });

  it('retains strict server-owned research-series state and rejects partial identity', () => {
    const research_loop = {
      schema_version: 'quant-research-loop-policy-v1', follow_up_mode: 'one_train_only_follow_up',
      max_versions: 2, max_total_experiments: 6, max_total_agent_actions: 24,
      automatic_retry: false, decision_partition: 'train', descriptor_policy: 'exact',
    };
    const research_series = {
      schema_version: 'quant-research-series-context-v1', root_run_id: marketRun.id,
      current_run_id: marketRun.id, version_number: 1, remaining_versions: 1,
      allowed_actions: ['finish_without_follow_up', 'precommit_one_refinement'], blocking_reasons: [],
      ancestor_candidate_keys: [], policy_digest: sha('f'),
    };
    expect(parseQuantMarketRun({ ...marketRun, mode: 'auto', research_loop, research_series })).toMatchObject({
      researchLoop: { followUpMode: 'one_train_only_follow_up', maxVersions: 2 },
      researchSeries: { rootRunId: marketRun.id, currentRunId: marketRun.id, remainingVersions: 1 },
    });
    expect(() => parseQuantMarketRun({ ...marketRun, mode: 'auto', research_loop })).toThrow('supplied together');
    expect(() => parseQuantMarketRun({ ...marketRun, mode: 'auto', research_loop, research_series: { ...research_series, current_run_id: 'other-run' } })).toThrow('identity');
    expect(() => parseQuantMarketRun({ ...marketRun, mode: 'auto', research_loop: { ...research_loop, max_total_agent_actions: 25 }, research_series })).toThrow('budget');
  });

  it.each([
    ['unknown schema', { ...marketDataset, schema_version: 'quant-daily-bars-v1' }],
    ['naive coverage', { ...marketDataset, covered_start: '2024-01-01T00:00:00' }],
    ['cadence mismatch', { ...marketDataset, periods_per_year: 252 }],
    ['blocked but eligible', { ...marketDataset, quality: { ...marketDataset.quality, status: 'blocked', cadence_gap_count: 1 } }],
  ])('fails closed for %s', (_label, payload) => {
    expect(() => parseQuantMarketDataset(payload)).toThrow();
  });

  it.each([
    ['1h 24x7', { interval: '1h', periods_per_year: 8760, market_calendar: '24x7', market_session: 'continuous', time_zone: 'UTC' }],
    ['4h 24x7', { interval: '4h', periods_per_year: 2190, market_calendar: '24x7', market_session: 'continuous', time_zone: 'UTC' }],
    ['1D 24x7', { interval: '1D', periods_per_year: 365, market_calendar: '24x7', market_session: 'continuous', time_zone: 'UTC' }],
    ['XNYS daily', { interval: '1D', periods_per_year: 252, market_calendar: 'XNYS', market_session: 'regular', time_zone: 'America/New_York' }],
    ['XNAS daily', { interval: '1D', periods_per_year: 252, market_calendar: 'XNAS', market_session: 'regular', time_zone: 'America/New_York' }],
    ['XSHG daily', { interval: '1D', periods_per_year: 252, market_calendar: 'XSHG', market_session: 'regular', time_zone: 'Asia/Shanghai' }],
    ['XSHE daily', { interval: '1D', periods_per_year: 252, market_calendar: 'XSHE', market_session: 'regular', time_zone: 'Asia/Shanghai' }],
    ['weekday daily', { interval: '1D', periods_per_year: 252, market_calendar: 'weekday', market_session: 'regular', time_zone: 'Europe/London' }],
  ])('accepts the C1 cadence mapping for %s', (_label, cadence) => {
    expect(parseQuantMarketDataset({ ...marketDataset, ...cadence })).toMatchObject({
      interval: cadence.interval,
      periodsPerYear: cadence.periods_per_year,
      marketCalendar: cadence.market_calendar,
      marketSession: cadence.market_session,
      timeZone: cadence.time_zone,
    });
  });

  it.each([
    ['4h New York timezone', { time_zone: 'America/New_York' }],
    ['4h exchange calendar', { market_calendar: 'XNYS', market_session: 'regular', time_zone: 'America/New_York', periods_per_year: 252 }],
    ['4h daily annualization', { periods_per_year: 365 }],
    ['24x7 regular session', { market_session: 'regular' }],
    ['24x7 daily PPY on 4h', { periods_per_year: 365 }],
    ['exchange continuous session', { interval: '1D', periods_per_year: 252, market_calendar: 'XNYS', market_session: 'continuous', time_zone: 'America/New_York' }],
    ['exchange UTC timezone', { interval: '1D', periods_per_year: 252, market_calendar: 'XNYS', market_session: 'regular', time_zone: 'UTC' }],
    ['unknown calendar marked eligible', { interval: '1D', periods_per_year: null, market_calendar: 'unknown', market_session: 'unknown', research_eligible: true }],
  ])('rejects the C1 cadence mismatch %s even when research_eligible is true', (_label, cadence) => {
    expect(() => parseQuantMarketDataset({ ...marketDataset, ...cadence })).toThrow();
  });

  it('accepts an explicitly ineligible unknown daily calendar without inferring annualization', () => {
    expect(parseQuantMarketDataset({
      ...marketDataset,
      interval: '1D',
      periods_per_year: null,
      market_calendar: 'unknown',
      market_session: 'unknown',
      research_eligible: false,
    })).toMatchObject({ interval: '1D', periodsPerYear: null, researchEligible: false, marketCalendar: 'unknown' });
  });

  it('rejects invalid Decimal bars and unordered timestamps', () => {
    const base = { dataset: marketDataset, data_authenticity: marketDataset.data_authenticity, total_bar_count: 2196, returned_bar_count: 2, max_points: 2, sampling_rule: 'latest_contiguous' };
    expect(() => parseQuantMarketDatasetPreview({ ...base, bars: [
      { timestamp: '2024-01-01T04:00:00Z', open: 'NaN', high: '2', low: '1', close: '1.5', volume: '1' },
      { timestamp: '2024-01-01T08:00:00Z', open: '1', high: '2', low: '1', close: '1.5', volume: '1' },
    ] })).toThrow();
    expect(() => parseQuantMarketDatasetPreview({ ...base, bars: [
      { timestamp: '2024-01-01T08:00:00Z', open: '1', high: '2', low: '1', close: '1.5', volume: '1' },
      { timestamp: '2024-01-01T04:00:00Z', open: '1', high: '2', low: '1', close: '1.5', volume: '1' },
    ] })).toThrow('strictly ordered');
    expect(() => parseQuantMarketDatasetPreview({ ...base, returned_bar_count: 1, bars: [
      { timestamp: '2024-01-01T04:00:00Z', open: 1, high: '2', low: '1', close: '1.5', volume: '1' },
    ] })).toThrow('decimal');
  });
});
