import { describe, expect, it } from 'vitest';
import e2eQuantFixtures from '../e2e/fixtures/quant-workspace-fixtures.json';
import { quantFixtureSnapshot } from './features/quant/quant-fixtures';
import {
  parseQuantWorkspaceSnapshot,
  QuantWorkspaceCompatibilityError,
  QUANT_WORKSPACE_SUPPORTED_VERSION,
} from './quant-workspace-parser';
import type { QuantCandidateEvolution, QuantWorkspaceSnapshot } from './quant-domain';

function cloneFixture(): QuantWorkspaceSnapshot {
  return JSON.parse(JSON.stringify(quantFixtureSnapshot)) as QuantWorkspaceSnapshot;
}

function completeRegimeWalkForward(snapshot: QuantWorkspaceSnapshot) {
  const candidate = snapshot.candidates[0]!.metrics;
  const benchmark = snapshot.benchmark!;
  const fold = (foldIndex: number, label: 'uptrend_normal_volatility' | 'sideways_high_volatility') => {
    const [trend, volatility] = label === 'uptrend_normal_volatility'
      ? ['uptrend', 'normal_volatility'] as const
      : ['sideways', 'high_volatility'] as const;
    return {
      foldIndex,
      historyStart: '2023-01-01',
      historyEnd: '2023-04-30',
      evaluationStart: `2023-0${foldIndex + 4}-01`,
      evaluationEnd: `2023-0${foldIndex + 4}-30`,
      marketRegime: { label, trend, volatility, historyStart: '2023-03-01', historyEnd: '2023-04-30', historyBarCount: 60, trailingReturn: foldIndex, annualizedVolatility: 24.5 },
      candidate,
      benchmark,
      status: 'pass',
    };
  };
  return {
    method: 'expanding',
    ruleVersion: 'expanding-3fold-20pct-v1',
    evaluationPartition: 'train',
    foldCount: 3,
    windowBarCount: 48,
    stateRuleVersion: 'market-state-v1',
    stateLookbackBars: 60,
    status: 'completed',
    reason: 'Fixed candidate evaluated in three expanding training-only windows.',
    folds: [fold(1, 'uptrend_normal_volatility'), fold(2, 'uptrend_normal_volatility'), fold(3, 'sideways_high_volatility')],
    aggregate: {
      evaluatedFolds: 3,
      candidatePositiveReturnFolds: 3,
      candidateLowerDrawdownFolds: 2,
      candidateMedianReturn: 8,
      benchmarkMedianReturn: 7,
      candidateMedianDrawdown: -4,
      benchmarkMedianDrawdown: -6,
      candidateMedianSharpe: 1.2,
      benchmarkMedianSharpe: 1,
      distinctMarketRegimes: 2,
      regimeDiversityStatus: 'covered',
      byMarketRegime: [
        { label: 'uptrend_normal_volatility', foldCount: 2, candidateMedianReturn: 8, benchmarkMedianReturn: 7, candidateMedianDrawdown: -4, benchmarkMedianDrawdown: -6, candidateMedianSharpe: 1.2, benchmarkMedianSharpe: 1 },
        { label: 'sideways_high_volatility', foldCount: 1, candidateMedianReturn: 6, benchmarkMedianReturn: 5, candidateMedianDrawdown: -5, benchmarkMedianDrawdown: -6, candidateMedianSharpe: 1, benchmarkMedianSharpe: 0.8 },
      ],
    },
  };
}

type LooseRecord = Record<string, unknown>;
type RobustnessFixtureRaw = LooseRecord & { report: LooseRecord; run: LooseRecord; dataset: LooseRecord; artifacts: LooseRecord[] };

function robustnessGroup(raw: RobustnessFixtureRaw): LooseRecord {
  return raw.report.robustnessSensitivity as LooseRecord;
}

function robustnessCostScenarios(raw: RobustnessFixtureRaw): LooseRecord[] {
  return robustnessGroup(raw).costScenarios as LooseRecord[];
}

function robustnessNeighbors(raw: RobustnessFixtureRaw): LooseRecord[] {
  return robustnessGroup(raw).parameterNeighbors as LooseRecord[];
}

function robustnessSnapshotRaw(): RobustnessFixtureRaw {
  const raw = JSON.parse(JSON.stringify(quantFixtureSnapshot)) as RobustnessFixtureRaw;
  const report = raw.report;
  report.generalization = {
    status: 'not_evaluated', reason: 'No fresh sealed holdout was evaluated.', selectedCandidateId: 'candidate-b',
    split: { method: 'chronological', ruleVersion: 'chronological-80-20-v1', trainBarCount: 800, holdoutBarCount: 200, cutoffDate: '2023-01-01', datasetId: raw.dataset.id, datasetDigest: raw.dataset.digest },
  };
  report.selectionDecision = { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' };
  const metrics = { totalReturnPct: 12, annualizedReturnPct: 8, maximumDrawdownPct: -6, sharpeRatio: 1.2, tradeCount: 9, winRatePct: 55, finalEquity: 11200 };
  const benchmarkMetrics = { totalReturnPct: 10, annualizedReturnPct: 7, maximumDrawdownPct: -8, sharpeRatio: 0.9, tradeCount: 1, winRatePct: 100, finalEquity: 11000 };
  const candidateParameters = { fast_window: 50, slow_window: 200 };
  report.robustnessSensitivity = {
    schemaVersion: 'robustness_sensitivity_v1', evaluationPartition: 'train', runId: raw.run.id, reportArtifactId: report.id,
    candidate: { candidateId: 'candidate-b', template: 'sma_crossover', parameters: candidateParameters, canonicalKey: 'a'.repeat(64) },
    finalTrainingComparison: { artifactId: 'fixture-validation', artifactDigest: raw.artifacts.find((item) => item.id === 'fixture-validation')!.digest },
    dataset: { datasetId: raw.dataset.id, datasetDigest: raw.dataset.digest }, interval: '1D', periodsPerYear: 252, runtimeDescriptorDigest: 'b'.repeat(64),
    trainingSplit: { identityKind: 'deterministic_legacy_split', ruleVersion: 'chronological-80-20-v1', trainingBarCount: 800, trainingStart: '2018-01-02', trainingEnd: '2022-12-30', trainingSplitDigest: 'c'.repeat(64), sealedSplitDigest: null },
    executionRuleVersion: 'quant-execution-cost-policy-v1', samplerRuleVersion: 'oat-parameter-neighborhood-v1',
    costScenarios: [
      { scenario: 'baseline_1x', multiplier: 1, feeRate: 0.001, slippageRate: 0.0005, candidateMetrics: metrics, benchmarkMetrics },
      { scenario: 'stressed_2x', multiplier: 2, feeRate: 0.002, slippageRate: 0.001, candidateMetrics: metrics, benchmarkMetrics },
      { scenario: 'stressed_4x', multiplier: 4, feeRate: 0.004, slippageRate: 0.002, candidateMetrics: metrics, benchmarkMetrics },
    ],
    parameterNeighbors: [{ parameterName: 'fast_window', direction: 'lower', parameters: { fast_window: 40, slow_window: 200 }, canonicalKey: 'd'.repeat(64), candidateMetrics: metrics }],
    kernelCallCount: 7,
  };
  return raw;
}

function marketFixture(interval: '1h' | '4h' | '1D' = '4h'): QuantWorkspaceSnapshot {
  const snapshot = cloneFixture();
  const start = '2024-01-01T00:00:00+00:00';
  const end = interval === '1h' ? '2025-12-31T23:00:00+00:00' : interval === '4h' ? '2025-12-31T20:00:00+00:00' : '2025-12-31T00:00:00+00:00';
  const periodsPerYear = interval === '1h' ? 8760 : interval === '4h' ? 2190 : 365;
  const datasetDigest = `sha256:${'6'.repeat(64)}`;
  const runtimeDescriptorDigest = `sha256:${'7'.repeat(64)}`;
  const sealedSplitDigest = `sha256:${'8'.repeat(64)}`;
  snapshot.run = { ...snapshot.run, contract: 'market-v2-private' };
  snapshot.scope = { ...snapshot.scope, symbol: 'BTCUSDT', interval, dateRange: { start, end } };
  snapshot.dataset = {
    contract: 'market-v2', id: `market-dataset-${interval}`, name: `BTCUSDT ${interval}`, symbol: 'BTCUSDT', interval,
    dateRange: { start, end }, barCount: 4386, schemaVersion: 'quant-market-bars-v2', parserVersion: 'fixture-market-v2', digest: datasetDigest,
    authenticity: 'synthetic_fixture', researchEligible: true, periodsPerYear, marketCalendar: '24x7', marketSession: 'continuous', timeZone: 'UTC', runtimeDescriptorDigest, sealedSplitDigest,
    source: { kind: 'provider_fetch', fileName: null, sourceName: 'Deterministic market fixture', sourceReference: `fixture://BTCUSDT/${interval}`, normalizerVersion: 'fixture-market-v2', retrievedAtUtc: '2026-07-22T00:00:00+00:00', requestedBarCount: 4386, returnedBarCount: 4386, retainedBarCount: 4386, closedDroppedCount: 0, deduplicatedCount: 0, terminationReason: 'requested_limit', targetSatisfied: true },
    quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'Contiguous fixture bars.' },
  };
  const timestamp = (index: number, length: number) => new Date(Date.parse(start) + index * ((Date.parse(end) - Date.parse(start)) / Math.max(1, length - 1))).toISOString().replace('.000Z', '+00:00');
  snapshot.bars = snapshot.bars.map((bar, index, rows) => ({ ...bar, date: timestamp(index, rows.length) }));
  snapshot.performanceSeries = snapshot.performanceSeries.map((series) => ({ ...series, points: series.points.map((point, index, rows) => ({ ...point, date: timestamp(index, rows.length) })) }));
  snapshot.trades = snapshot.trades.map((trade, index, rows) => ({
    id: trade.id,
    candidateId: trade.candidateId,
    entryDate: timestamp(index, rows.length * 2),
    exitDate: timestamp(index + 1, rows.length * 2),
    returnPct: trade.returnPct,
    holdingBars: 22,
    holdingElapsedSeconds: 316_800,
    reason: trade.reason,
  }));
  snapshot.kernelCheck = { ...snapshot.kernelCheck, datasetId: snapshot.dataset.id, datasetDigest, barCount: snapshot.dataset.barCount, interval, periodsPerYear, runtimeDescriptorDigest, sealedSplitDigest };
  if (snapshot.report) snapshot.report = { ...snapshot.report, datasetContext: { symbol: 'BTCUSDT', interval, periodsPerYear, range: { start, end }, runtimeDescriptorDigest, sealedSplitDigest } };
  return snapshot;
}

function marketRobustnessSnapshotRaw(): RobustnessFixtureRaw {
  const raw = JSON.parse(JSON.stringify(marketFixture())) as RobustnessFixtureRaw;
  const sourceSensitivity = robustnessGroup(robustnessSnapshotRaw());
  const report = raw.report;
  const dataset = raw.dataset;
  const context = report.datasetContext as LooseRecord;
  report.generalization = {
    status: 'not_evaluated', reason: 'No fresh sealed holdout was evaluated.', selectedCandidateId: 'candidate-b',
    split: { method: 'chronological', ruleVersion: 'chronological-80-20-v1', trainBarCount: 800, holdoutBarCount: 200, cutoffDate: '2025-01-01', datasetId: dataset.id, datasetDigest: dataset.digest, interval: dataset.interval, periodsPerYear: dataset.periodsPerYear, cutoffTimestampUtc: '2025-01-01T00:00:00+00:00', rangeStartUtc: (dataset.dateRange as LooseRecord).start, rangeEndUtc: (dataset.dateRange as LooseRecord).end, descriptorDigest: context.runtimeDescriptorDigest, sealDigest: context.sealedSplitDigest },
  };
  report.selectionDecision = { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' };
  report.robustnessSensitivity = {
    ...sourceSensitivity,
    runId: raw.run.id, reportArtifactId: report.id,
    dataset: { datasetId: dataset.id, datasetDigest: dataset.digest }, interval: dataset.interval, periodsPerYear: dataset.periodsPerYear, runtimeDescriptorDigest: context.runtimeDescriptorDigest,
    trainingSplit: { identityKind: 'sealed_market_split', ruleVersion: 'chronological-80-20-v1', trainingBarCount: 800, trainingStart: (dataset.dateRange as LooseRecord).start, trainingEnd: '2024-12-31T20:00:00+00:00', trainingSplitDigest: context.sealedSplitDigest, sealedSplitDigest: context.sealedSplitDigest },
  };
  return raw;
}

function setMarketRangeStart(raw: RobustnessFixtureRaw, start: string) {
  ((raw.scope as LooseRecord).dateRange as LooseRecord).start = start;
  (raw.dataset.dateRange as LooseRecord).start = start;
  ((raw.report.datasetContext as LooseRecord).range as LooseRecord).start = start;
  (((raw.report.generalization as LooseRecord).split as LooseRecord).rangeStartUtc) = start;
  ((robustnessGroup(raw).trainingSplit as LooseRecord).trainingStart) = start;
}

describe('parseQuantWorkspaceSnapshot', () => {
  it('parses a complete authoritative modeled-regime projection while retaining legacy walk-forward snapshots', () => {
    const legacy = cloneFixture();
    const legacyReport = legacy.report as unknown as Record<string, unknown>;
    const currentWalkForward = completeRegimeWalkForward(legacy);
    const legacyWalkForward = JSON.parse(JSON.stringify(currentWalkForward)) as Record<string, unknown>;
    delete legacyWalkForward.stateRuleVersion;
    delete legacyWalkForward.stateLookbackBars;
    for (const fold of legacyWalkForward.folds as Array<Record<string, unknown>>) delete fold.marketRegime;
    const legacyAggregate = legacyWalkForward.aggregate as Record<string, unknown>;
    delete legacyAggregate.distinctMarketRegimes;
    delete legacyAggregate.regimeDiversityStatus;
    delete legacyAggregate.byMarketRegime;
    legacyReport.walkForward = legacyWalkForward;
    expect(parseQuantWorkspaceSnapshot(legacy).snapshot?.report?.walkForward?.aggregate.byMarketRegime).toBeUndefined();

    const input = cloneFixture();
    (input.report as unknown as Record<string, unknown>).walkForward = completeRegimeWalkForward(input);
    const parsed = parseQuantWorkspaceSnapshot(input).snapshot;
    expect(parsed?.report?.walkForward).toMatchObject({ stateRuleVersion: 'market-state-v1', stateLookbackBars: 60 });
    expect(parsed?.report?.walkForward?.folds[0]?.marketRegime?.label).toBe('uptrend_normal_volatility');
    expect(parsed?.report?.walkForward?.aggregate).toMatchObject({ distinctMarketRegimes: 2, regimeDiversityStatus: 'covered' });
  });

  it.each([
    ['partial regime group', (walkForward: Record<string, unknown>) => { delete walkForward.stateLookbackBars; }],
    ['empty state rule version', (walkForward: Record<string, unknown>) => { walkForward.stateRuleVersion = ''; }],
    ['zero state lookback', (walkForward: Record<string, unknown>) => { walkForward.stateLookbackBars = 0; }],
    ['unknown regime field', (walkForward: Record<string, unknown>) => { ((walkForward.folds as Array<Record<string, unknown>>)[0]!.marketRegime as Record<string, unknown>).unexpected = true; }],
    ['non-finite regime statistic', (walkForward: Record<string, unknown>) => { ((walkForward.folds as Array<Record<string, unknown>>)[0]!.marketRegime as Record<string, unknown>).trailingReturn = Infinity; }],
    ['mismatched regime label', (walkForward: Record<string, unknown>) => { ((walkForward.folds as Array<Record<string, unknown>>)[0]!.marketRegime as Record<string, unknown>).label = 'downtrend_normal_volatility'; }],
    ['duplicate aggregate label', (walkForward: Record<string, unknown>) => { ((walkForward.aggregate as Record<string, unknown>).byMarketRegime as Array<Record<string, unknown>>)[1]!.label = 'uptrend_normal_volatility'; }],
    ['aggregate count mismatch', (walkForward: Record<string, unknown>) => { (walkForward.aggregate as Record<string, unknown>).distinctMarketRegimes = 3; }],
    ['aggregate fold-count mismatch', (walkForward: Record<string, unknown>) => { ((walkForward.aggregate as Record<string, unknown>).byMarketRegime as Array<Record<string, unknown>>)[0]!.foldCount = 1; }],
    ['evaluated-fold count mismatch', (walkForward: Record<string, unknown>) => { (walkForward.aggregate as Record<string, unknown>).evaluatedFolds = 2; }],
    ['walk-forward fold count mismatch', (walkForward: Record<string, unknown>) => { walkForward.foldCount = 2; }],
  ])('fails closed for %s', (_name, mutate) => {
    const input = cloneFixture();
    const walkForward = completeRegimeWalkForward(input) as unknown as Record<string, unknown>;
    mutate(walkForward);
    (input.report as unknown as Record<string, unknown>).walkForward = walkForward;

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);
    expect(snapshot).toBeNull();
    expect(compatibility.supported).toBe(false);
  });

  it('parses the optional Research Contract objective and closed structured stop', () => {
    const legacy = cloneFixture();
    expect(parseQuantWorkspaceSnapshot(legacy).snapshot?.researchPlan?.objectiveSummary).toBeUndefined();
    expect(parseQuantWorkspaceSnapshot(legacy).snapshot?.report?.iterationStop).toBeUndefined();

    const current = cloneFixture() as unknown as Record<string, unknown>;
    current.researchPlan = {
      candidateFamilies: ['sma_crossover', 'breakout'],
      selectionObjective: 'drawdown_control',
      completionCriteria: ['Backtest every candidate.', 'Compare completed candidates.'],
      objectiveSummary: 'Compare bounded trend candidates while controlling drawdown.',
    };
    (current.report as Record<string, unknown>).iterationStop = {
      reason: 'no_novel_candidate',
      referenceCandidateId: 'candidate-a',
    };

    const parsed = parseQuantWorkspaceSnapshot(current).snapshot;
    expect(parsed?.researchPlan?.objectiveSummary).toBe('Compare bounded trend candidates while controlling drawdown.');
    expect(parsed?.report?.iterationStop).toEqual({
      reason: 'no_novel_candidate',
      referenceCandidateId: 'candidate-a',
    });
  });

  it.each([
    { reason: 'provider_error', referenceCandidateId: 'candidate-a' },
    { reason: 'no_novel_candidate', referenceCandidateId: 'candidate-a', artifactId: 'artifact-secret' },
  ])('fails closed for an invalid structured stop %#', (iterationStop) => {
    const input = cloneFixture() as unknown as Record<string, unknown>;
    (input.report as Record<string, unknown>).iterationStop = iterationStop;

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot).toBeNull();
    expect(compatibility.supported).toBe(false);
  });

  it('parses the closed selection decision while preserving legacy reports', () => {
    const legacy = cloneFixture();
    expect(parseQuantWorkspaceSnapshot(legacy).snapshot?.report?.selectionDecision).toBeUndefined();
    const priorSerializedDecision = cloneFixture();
    if (!priorSerializedDecision.report) throw new Error('fixture report is required');
    priorSerializedDecision.report.selectionDecision = { basis: 'approved_objective_rank' };
    expect(parseQuantWorkspaceSnapshot(priorSerializedDecision).snapshot?.report?.selectionDecision).toEqual({
      basis: 'approved_objective_rank',
    });
    const current = cloneFixture();
    if (!current.report) throw new Error('fixture report is required');
    current.report.selectionDecision = {
      basis: 'robustness_override',
      selectedCandidateId: 'candidate-b',
      reason: 'walk_forward_stability',
      referenceCandidateId: 'candidate-a',
    };
    expect(parseQuantWorkspaceSnapshot(current).snapshot?.report?.selectionDecision).toEqual(current.report.selectionDecision);
    const invalid = cloneFixture() as unknown as Record<string, unknown>;
    const invalidReport = (invalid.report as Record<string, unknown>);
    invalidReport.selectionDecision = { basis: 'robustness_override', reason: 'free_form' };
    expect(parseQuantWorkspaceSnapshot(invalid).snapshot).toBeNull();

    const unknownSelectionField = cloneFixture() as unknown as Record<string, unknown>;
    (unknownSelectionField.report as Record<string, unknown>).selectionDecision = {
      basis: 'approved_objective_rank',
      selectedCandidateId: 'candidate-a',
      sourceComparisonArtifactId: 'comparison-secret',
    };
    expect(parseQuantWorkspaceSnapshot(unknownSelectionField).snapshot).toBeNull();
  });

  it.each(Object.entries(e2eQuantFixtures))('keeps the %s end-to-end fixture parser-compatible', (_name, fixture) => {
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(fixture);
    expect(compatibility, compatibility.warnings.join('\n')).toMatchObject({ supported: true, missingFields: [] });
    expect(snapshot).not.toBeNull();
    expect(snapshot?.candidates.every((candidate) => candidate.canSeedResearch === false)).toBe(true);
  });

  it('accepts the current fixture snapshot as a valid workspace response', () => {
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(quantFixtureSnapshot);

    expect(compatibility.schemaVersion).toBe(quantFixtureSnapshot.version);
    expect(compatibility.supported).toBe(true);
    expect(compatibility.degraded).toBe(false);
    expect(compatibility.missingFields).toEqual([]);
    expect(compatibility.unknownFields).toEqual([]);
    expect(compatibility.warnings).toEqual([]);
    expect(snapshot).toEqual(quantFixtureSnapshot);
  });

  it('fails closed when persisted candidate evolution claims an unknown evidence origin', () => {
    const input = cloneFixture();
    input.candidates[0]!.evolution!.origin = 'sealed_holdout' as 'initial';

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot).toBeNull();
    expect(compatibility.missingFields).toContain('candidates.0.evolution.origin');
  });

  it.each([
    {
      replanRepair: {
        rejectedAction: 'refine_parameters',
        correctedAction: 'switch_approved_family',
        retainedInputs: true,
        outcome: 'candidate_created',
      },
      expected: 'parses',
    },
    {
      replanRepair: {
        rejectedAction: 'switch_approved_family',
        correctedAction: 'switch_approved_family',
        retainedInputs: true,
        outcome: 'candidate_created',
      },
      expected: 'rejects',
    },
    {
      replanRepair: {
        rejectedAction: 'refine_parameters',
        correctedAction: 'switch_approved_family',
        retainedInputs: false,
        outcome: 'candidate_created',
      },
      expected: 'rejects',
    },
  ])('fails closed for an invalid replanRepair shape %#', ({ replanRepair, expected }) => {
    const input = cloneFixture();
    const candidate = input.candidates[0]!;
    candidate.evolution = { ...candidate.evolution!, replanRepair: replanRepair as QuantCandidateEvolution['replanRepair'] };

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    if (expected === 'parses') {
      expect(compatibility.supported).toBe(true);
      expect(snapshot?.candidates[0]?.evolution?.replanRepair).toEqual(replanRepair);
    } else {
      expect(snapshot).toBeNull();
      expect(compatibility.supported).toBe(false);
    }
  });

  it('retains the optional retry identity without adding a second lineage projection', () => {
    const input = cloneFixture();
    input.run = { ...input.run, retryOfRunId: 'run-prior-attempt' };

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(compatibility.supported).toBe(true);
    expect(snapshot?.run.retryOfRunId).toBe('run-prior-attempt');
  });

  it('accepts the current autonomous-agent projection version', () => {
    const input = cloneFixture();
    input.version = QUANT_WORKSPACE_SUPPORTED_VERSION;

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot?.version).toBe(QUANT_WORKSPACE_SUPPORTED_VERSION);
    expect(compatibility).toMatchObject({
      schemaVersion: QUANT_WORKSPACE_SUPPORTED_VERSION,
      supported: true,
      degraded: false,
    });
  });

  it('preserves a strict market snapshot cadence and RFC3339 UTC identities', () => {
    const input = marketFixture();
    const expectedPoint = input.performanceSeries[0]!.points[1]!.date;
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(compatibility.supported).toBe(true);
    expect(snapshot?.run.contract).toBe('market-v2-private');
    expect(snapshot?.dataset).toMatchObject({ contract: 'market-v2', interval: '4h', periodsPerYear: 2190 });
    expect(snapshot?.performanceSeries[0]?.points[1]?.date).toBe(expectedPoint);
    expect(snapshot?.report?.datasetContext?.range).toEqual(input.dataset.dateRange);
    expect(snapshot?.trades[0]).toMatchObject({ holdingBars: 22, holdingElapsedSeconds: 316_800 });
    expect(snapshot?.trades[0]).not.toHaveProperty('holdingDays');
  });

  it.each(['holdingBars', 'holdingElapsedSeconds'] as const)(
    'fails closed when a market trade is missing %s',
    (field) => {
      const input = marketFixture();
      delete (input.trades[0] as unknown as Record<string, unknown>)[field];

      const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

      expect(snapshot).toBeNull();
      expect(compatibility.supported).toBe(false);
      expect(compatibility.missingFields).toContain(`trades.0.${field}`);
    },
  );

  it('rejects fractional or daily holding fields in a market trade', () => {
    const fractional = marketFixture();
    (fractional.trades[0] as { holdingBars: number }).holdingBars = 1.5;
    expect(parseQuantWorkspaceSnapshot(fractional).snapshot).toBeNull();

    const mixed = marketFixture();
    (mixed.trades[0] as unknown as Record<string, unknown>).holdingDays = 3;
    expect(parseQuantWorkspaceSnapshot(mixed).snapshot).toBeNull();
  });

  it('keeps the legacy daily holding-days contract unchanged', () => {
    const input = cloneFixture();
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(compatibility.supported).toBe(true);
    expect(snapshot?.trades[0]).toHaveProperty('holdingDays');
    expect(snapshot?.trades[0]).not.toHaveProperty('holdingBars');
    expect(snapshot?.trades[0]).not.toHaveProperty('holdingElapsedSeconds');
  });

  it('parses completed Market Run report cadence quality without coercing it to the daily quality contract', () => {
    const input = marketFixture();
    input.report!.datasetQuality = { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'No cadence gaps detected.' };

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(compatibility, compatibility.warnings.join('\n')).toMatchObject({ supported: true, degraded: false });
    expect(snapshot?.report?.datasetQuality).toEqual({ status: 'accepted', cadenceGapCount: 0, normalizationNote: 'No cadence gaps detected.' });
  });

  it.each([
    ['1h', 8760],
    ['4h', 2190],
    ['1D', 365],
  ] as const)('accepts a complete %s market runtime identity', (interval, periodsPerYear) => {
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(marketFixture(interval));
    expect(compatibility, compatibility.warnings.join('\n')).toMatchObject({ supported: true, degraded: false });
    expect(snapshot?.dataset).toMatchObject({ contract: 'market-v2', interval, periodsPerYear });
    expect(snapshot?.run.contract).toBe('market-v2-private');
  });

  it.each([
    ['missing annualization', (input: QuantWorkspaceSnapshot) => { delete (input.dataset as unknown as Record<string, unknown>).periodsPerYear; }],
    ['missing runtime pin', (input: QuantWorkspaceSnapshot) => { delete (input.dataset as unknown as Record<string, unknown>).runtimeDescriptorDigest; }],
    ['missing split pin', (input: QuantWorkspaceSnapshot) => { delete (input.dataset as unknown as Record<string, unknown>).sealedSplitDigest; }],
    ['market contract with daily schema', (input: QuantWorkspaceSnapshot) => { input.dataset.schemaVersion = 'quant-daily-bars-v1'; }],
    ['legacy contract mixed with market cadence', (input: QuantWorkspaceSnapshot) => { input.dataset.contract = 'legacy-daily-v1'; }],
    ['market run contract mixed with a legacy dataset', (input: QuantWorkspaceSnapshot) => {
      const legacy = cloneFixture().dataset;
      input.dataset = legacy;
      input.scope = { ...cloneFixture().scope };
    }],
  ] as const)('fails closed for %s instead of degrading to legacy daily', (_label, mutate) => {
    const input = marketFixture('1D');
    mutate(input);
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);
    expect(snapshot).toBeNull();
    expect(compatibility.supported).toBe(false);
    expect(compatibility.degraded).toBe(true);
    expect(compatibility.warnings.length).toBeGreaterThan(0);
  });

  it('does not trust a public market run label until the API directory validates it', () => {
    const input = marketFixture('1h');
    input.run.contract = 'market-v2-public';
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);
    expect(compatibility.supported).toBe(true);
    expect(snapshot?.run.contract).toBe('market-v2-private');
  });

  it('rejects inconsistent market runtime and report identities', () => {
    const input = marketFixture();
    input.kernelCheck.periodsPerYear = 252;
    input.report!.datasetContext!.range.end = '2025-12-31T16:00:00+00:00';
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot).toBeNull();
    expect(compatibility.missingFields).toContain('kernelCheck');
  });

  it('preserves additive unknown fields without interrupting parsing', () => {
    const input = cloneFixture();
    (input as unknown as Record<string, unknown>).futureField = 'extra';
    (input.run as unknown as Record<string, unknown>).extraInfo = { nested: true };

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(compatibility.supported).toBe(true);
    expect(compatibility.degraded).toBe(false);
    expect(compatibility.unknownFields).toContain('futureField');
    expect(compatibility.unknownFields).toContain('run.extraInfo');
    expect(snapshot).toEqual(quantFixtureSnapshot);
  });

  it('parses a strict executable research plan and rejects unknown families', () => {
    const valid = cloneFixture();
    valid.researchPlan = {
      candidateFamilies: ['sma_crossover', 'breakout'],
      selectionObjective: 'drawdown_control',
      completionCriteria: ['Backtest every candidate.', 'Compare completed candidates.'],
    };
    expect(parseQuantWorkspaceSnapshot(valid).snapshot?.researchPlan).toEqual(valid.researchPlan);

    const invalid = cloneFixture();
    (invalid as unknown as Record<string, unknown>).researchPlan = {
      candidateFamilies: ['arbitrary_python'],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Compare completed candidates.'],
    };
    const parsed = parseQuantWorkspaceSnapshot(invalid);
    expect(parsed.snapshot).toBeNull();
    expect(parsed.compatibility.missingFields).toContain('researchPlan.candidateFamilies.0');

    const invalidObjective = cloneFixture();
    (invalidObjective as unknown as Record<string, unknown>).researchPlan = {
      candidateFamilies: ['sma_crossover'],
      selectionObjective: 'model_decides_later',
      completionCriteria: ['Compare completed candidates.'],
    };
    const objectiveParsed = parseQuantWorkspaceSnapshot(invalidObjective);
    expect(objectiveParsed.snapshot).toBeNull();
    expect(objectiveParsed.compatibility.missingFields).toContain('researchPlan.selectionObjective');

    const unknownPlanField = cloneFixture() as unknown as Record<string, unknown>;
    unknownPlanField.researchPlan = {
      candidateFamilies: ['sma_crossover'],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Compare completed candidates.'],
      sourcePlanArtifactId: 'plan-secret',
    };
    expect(parseQuantWorkspaceSnapshot(unknownPlanField).snapshot).toBeNull();
  });

  it('parses the closed strategy-scope decision and preserves the legacy default boundary', () => {
    const legacy = cloneFixture();
    legacy.researchPlan = {
      candidateFamilies: ['sma_crossover'],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Compare completed candidates.'],
    };
    expect(parseQuantWorkspaceSnapshot(legacy).snapshot?.researchPlan?.strategyScope).toBeUndefined();

    const supported = cloneFixture();
    supported.researchPlan = {
      candidateFamilies: ['sma_crossover', 'breakout'],
      selectionObjective: 'drawdown_control',
      completionCriteria: ['Compare completed candidates.'],
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'supported',
        reason: 'The request is expressible with registered trend strategies.',
        excludedBehaviors: [],
      },
    };
    expect(parseQuantWorkspaceSnapshot(supported).snapshot?.researchPlan?.strategyScope).toEqual(supported.researchPlan.strategyScope);

    const nullableSupported = cloneFixture() as unknown as Record<string, unknown>;
    nullableSupported.researchPlan = {
      candidateFamilies: ['sma_crossover'],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Compare completed candidates.'],
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'supported',
        reason: 'The request is supported without a proxy.',
        proxyDescription: null,
        excludedBehaviors: [],
      },
    };
    expect(parseQuantWorkspaceSnapshot(nullableSupported).snapshot?.researchPlan?.strategyScope).toEqual({
      schemaVersion: 'quant-strategy-scope-v1',
      status: 'supported',
      reason: 'The request is supported without a proxy.',
      excludedBehaviors: [],
    });

    const boundedProxy = cloneFixture();
    boundedProxy.researchPlan = {
      candidateFamilies: ['rsi_mean_reversion'],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Compare completed candidates.'],
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'bounded_proxy',
        reason: 'The requested momentum filter is approximated with registered RSI rules.',
        proxyDescription: 'Test a bounded RSI threshold proxy on the selected OHLCV bars.',
        excludedBehaviors: ['Exact MACD signal parity', 'ATR-sized positions'],
      },
    };
    expect(parseQuantWorkspaceSnapshot(boundedProxy).snapshot?.researchPlan?.strategyScope).toEqual(boundedProxy.researchPlan.strategyScope);

    const unsupported = cloneFixture();
    unsupported.researchPlan = {
      candidateFamilies: [],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Revise the request before experiments begin.'],
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'unsupported',
        reason: 'The request requires a long-short multi-asset strategy.',
        excludedBehaviors: ['Short positions', 'Cross-asset ranking'],
      },
    };
    expect(parseQuantWorkspaceSnapshot(unsupported).snapshot?.researchPlan?.strategyScope).toEqual(unsupported.researchPlan.strategyScope);
  });

  it.each([
    {
      name: 'supported scope with exclusions',
      candidateFamilies: ['sma_crossover'],
      scope: { schemaVersion: 'quant-strategy-scope-v1', status: 'supported', reason: 'Supported.', excludedBehaviors: ['Short positions'] },
      path: 'researchPlan.strategyScope',
    },
    {
      name: 'bounded proxy without a proxy description',
      candidateFamilies: ['rsi_mean_reversion'],
      scope: { schemaVersion: 'quant-strategy-scope-v1', status: 'bounded_proxy', reason: 'Use a proxy.', excludedBehaviors: ['Exact MACD parity'] },
      path: 'researchPlan.strategyScope',
    },
    {
      name: 'unsupported scope with an executable family',
      candidateFamilies: ['breakout'],
      scope: { schemaVersion: 'quant-strategy-scope-v1', status: 'unsupported', reason: 'Not supported.', excludedBehaviors: ['Short positions'] },
      path: 'researchPlan.candidateFamilies',
    },
    {
      name: 'unknown strategy-scope field',
      candidateFamilies: ['sma_crossover'],
      scope: { schemaVersion: 'quant-strategy-scope-v1', status: 'supported', reason: 'Supported.', excludedBehaviors: [], arbitraryPython: true },
      path: 'researchPlan.strategyScope.arbitraryPython',
    },
  ])('fails closed for $name', ({ candidateFamilies, scope, path }) => {
    const invalid = cloneFixture() as unknown as Record<string, unknown>;
    invalid.researchPlan = {
      candidateFamilies,
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Compare completed candidates.'],
      strategyScope: scope,
    };
    const parsed = parseQuantWorkspaceSnapshot(invalid);
    expect(parsed.snapshot).toBeNull();
    expect([...parsed.compatibility.missingFields, ...parsed.compatibility.unknownFields]).toContain(path);
  });

  it('accepts the count-only research memory projection and rejects malformed variants', () => {
    const valid = cloneFixture();
    valid.researchMemory = { sourceRunCount: 3, testedCandidateCount: 9 };
    expect(parseQuantWorkspaceSnapshot(valid).snapshot?.researchMemory).toEqual(valid.researchMemory);

    for (const mutate of [
      (input: Record<string, unknown>) => { input.researchMemory = { sourceRunCount: 3 }; },
      (input: Record<string, unknown>) => { input.researchMemory = { sourceRunCount: 0, testedCandidateCount: 9 }; },
      (input: Record<string, unknown>) => { input.researchMemory = { sourceRunCount: 3.5, testedCandidateCount: 9 }; },
      (input: Record<string, unknown>) => { input.researchMemory = { sourceRunCount: 3, testedCandidateCount: 9, sourceRunIds: ['run-1'] }; },
      (input: Record<string, unknown>) => { input.researchMemory = null; },
    ]) {
      const invalid = cloneFixture() as unknown as Record<string, unknown>;
      mutate(invalid);
      const parsed = parseQuantWorkspaceSnapshot(invalid);
      expect(parsed.snapshot).toBeNull();
      expect(parsed.compatibility.supported).toBe(false);
    }
  });

  it('preserves the server-projected seedability bit without inferring it from strategy text', () => {
    const input = cloneFixture();
    input.candidates[1] = { ...input.candidates[1]!, canSeedResearch: true };

    const { snapshot } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot?.candidates[1]?.canSeedResearch).toBe(true);
    expect(snapshot?.candidates[0]?.canSeedResearch).toBe(false);
  });

  it('reports missing required fields as unsupported without fabricating a snapshot', () => {
    const input = cloneFixture();
    delete (input as unknown as Record<string, unknown>).run;
    delete (input as unknown as Record<string, unknown>).benchmark;

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot).toBeNull();
    expect(compatibility.supported).toBe(false);
    expect(compatibility.degraded).toBe(true);
    expect(compatibility.missingFields).toContain('run');
    expect(compatibility.missingFields).toContain('benchmark');
    expect(compatibility.warnings.some((w) => w.includes('run'))).toBe(true);
    expect(compatibility.warnings.some((w) => w.includes('benchmark'))).toBe(true);
  });

  it('rejects malformed live experiment metrics instead of inventing active-run evidence', () => {
    const input = JSON.parse(JSON.stringify(e2eQuantFixtures['quant-running'])) as QuantWorkspaceSnapshot;
    const live = input.liveResearch!;
    (live.latestResult!.metrics as unknown as Record<string, unknown>).sharpe = 'high';
    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);
    expect(snapshot).toBeNull();
    expect(compatibility.missingFields).toContain('liveResearch.latestResult.metrics.sharpe');
  });

  it('maps an unknown run state to the unknown sentinel and keeps the response usable', () => {
    const input = cloneFixture();
    input.run.state = 'executing_magic' as unknown as QuantWorkspaceSnapshot['run']['state'];

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot).not.toBeNull();
    expect(snapshot!.run.state).toBe('unknown');
    expect(compatibility.supported).toBe(true);
    expect(compatibility.degraded).toBe(true);
    expect(compatibility.warnings.some((w) => w.includes('run.state') && w.includes('executing_magic'))).toBe(true);
  });

  it('blocks unsupported snapshot versions with a stable compatibility notice', () => {
    const input = cloneFixture();
    input.version = 'future-schema-v2';

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot).toBeNull();
    expect(compatibility.supported).toBe(false);
    expect(compatibility.degraded).toBe(false);
    expect(compatibility.schemaVersion).toBe('future-schema-v2');
    expect(compatibility.warnings[0]).toMatch(/future-schema-v2/);
    expect(compatibility.warnings[0]).toMatch(QUANT_WORKSPACE_SUPPORTED_VERSION);
  });

  it('rejects non-finite numeric fields instead of coercing them', () => {
    const input = cloneFixture();
    input.run.rowVersion = NaN;
    (input.benchmark as unknown as Record<string, number>).annualizedReturn = Infinity;

    const { snapshot, compatibility } = parseQuantWorkspaceSnapshot(input);

    expect(snapshot).toBeNull();
    expect(compatibility.supported).toBe(false);
    expect(compatibility.degraded).toBe(true);
    expect(compatibility.missingFields).toContain('run.rowVersion');
    expect(compatibility.missingFields).toContain('benchmark.annualizedReturn');
    expect(compatibility.warnings.some((w) => w.includes('run.rowVersion') && w.includes('finite number'))).toBe(true);
    expect(compatibility.warnings.some((w) => w.includes('benchmark.annualizedReturn') && w.includes('finite number'))).toBe(true);
  });

  it('keeps legacy reports compatible when robustness sensitivity is absent', () => {
    const { snapshot } = parseQuantWorkspaceSnapshot(cloneFixture());
    expect(snapshot).not.toBeNull();
    expect(snapshot!.report?.robustnessSensitivity).toBeUndefined();
  });

  it('parses the exact train-only robustness sensitivity group bound to the final candidate', () => {
    const { snapshot } = parseQuantWorkspaceSnapshot(robustnessSnapshotRaw());
    expect(snapshot?.report?.robustnessSensitivity).toMatchObject({
      evaluationPartition: 'train', candidate: { candidateId: 'candidate-b', template: 'sma_crossover' }, kernelCallCount: 7,
    });
    expect(snapshot?.report?.robustnessSensitivity?.costScenarios.map((item) => item.scenario)).toEqual(['baseline_1x', 'stressed_2x', 'stressed_4x']);
  });

  it('requires market sensitivity runtime and sealed-split identity to match dataset and report context', () => {
    const raw = marketRobustnessSnapshotRaw();
    expect(parseQuantWorkspaceSnapshot(raw).snapshot?.report?.robustnessSensitivity?.trainingSplit.identityKind).toBe('sealed_market_split');
    robustnessGroup(raw).runtimeDescriptorDigest = 'z'.repeat(64);
    expect(parseQuantWorkspaceSnapshot(raw).snapshot).toBeNull();
  });

  it.each(['2024-02-30T00:00:00+00:00', '2024-12-30T24:00:00+00:00'])('rejects normalized-but-impossible UTC training start %s', (start) => {
    const raw = marketRobustnessSnapshotRaw();
    setMarketRangeStart(raw, start);
    expect(parseQuantWorkspaceSnapshot(raw).snapshot).toBeNull();
  });

  it('accepts a valid leap-day UTC training start in canonical Z syntax', () => {
    const raw = marketRobustnessSnapshotRaw();
    setMarketRangeStart(raw, '2024-02-29T00:00:00Z');
    expect(parseQuantWorkspaceSnapshot(raw).snapshot?.report?.robustnessSensitivity?.trainingSplit.trainingStart).toBe('2024-02-29T00:00:00Z');
  });

  it.each<[string, () => RobustnessFixtureRaw]>([
    ['legacy garbage training window', () => { const raw = robustnessSnapshotRaw(); (robustnessGroup(raw).trainingSplit as LooseRecord).trainingStart = 'not-a-date'; return raw; }],
    ['legacy later training start', () => { const raw = robustnessSnapshotRaw(); (robustnessGroup(raw).trainingSplit as LooseRecord).trainingStart = '2018-01-03'; return raw; }],
    ['legacy training end at cutoff', () => { const raw = robustnessSnapshotRaw(); (robustnessGroup(raw).trainingSplit as LooseRecord).trainingEnd = '2023-01-01'; return raw; }],
    ['market garbage training window', () => { const raw = marketRobustnessSnapshotRaw(); (robustnessGroup(raw).trainingSplit as LooseRecord).trainingStart = 'not-a-timestamp'; return raw; }],
    ['market later training start', () => { const raw = marketRobustnessSnapshotRaw(); (robustnessGroup(raw).trainingSplit as LooseRecord).trainingStart = '2024-01-01T04:00:00+00:00'; return raw; }],
    ['market training end at cutoff', () => { const raw = marketRobustnessSnapshotRaw(); (robustnessGroup(raw).trainingSplit as LooseRecord).trainingEnd = '2025-01-01T00:00:00+00:00'; return raw; }],
  ])('rejects %s', (_label, build) => {
    expect(parseQuantWorkspaceSnapshot(build()).snapshot).toBeNull();
  });

  it.each<[string, (raw: RobustnessFixtureRaw) => void]>([
    ['partial group', (raw) => { delete robustnessGroup(raw).costScenarios; }],
    ['unknown holdout injection', (raw) => { robustnessGroup(raw).holdout = {}; }],
    ['score injection', (raw) => { robustnessGroup(raw).score = 1; }],
    ['pass injection', (raw) => { robustnessGroup(raw).pass = true; }],
    ['non-finite metrics', (raw) => { ((robustnessCostScenarios(raw)[0]!.candidateMetrics as LooseRecord).sharpeRatio) = Infinity; }],
    ['missing cost scenario', (raw) => { robustnessCostScenarios(raw).pop(); }],
    ['duplicate cost scenario', (raw) => { robustnessCostScenarios(raw)[1]!.scenario = 'baseline_1x'; }],
    ['incorrect cost configuration', (raw) => { robustnessCostScenarios(raw)[2]!.feeRate = 0.003; }],
    ['too many neighbors', (raw) => { const group = robustnessGroup(raw); group.parameterNeighbors = Array.from({ length: 7 }, (_, index) => ({ ...robustnessNeighbors(raw)[0], canonicalKey: String(index).padStart(64, 'e') })); group.kernelCallCount = 13; }],
    ['duplicate neighbor identity', (raw) => { const group = robustnessGroup(raw); group.parameterNeighbors = [...robustnessNeighbors(raw), { ...robustnessNeighbors(raw)[0], canonicalKey: 'f'.repeat(64) }]; group.kernelCallCount = 8; }],
    ['non OAT neighbor', (raw) => { (robustnessNeighbors(raw)[0]!.parameters as LooseRecord).slow_window = 180; }],
    ['wrong neighbor parameter keys', (raw) => { robustnessNeighbors(raw)[0]!.parameters = { fast_window: 40 }; }],
    ['incorrect call count', (raw) => { robustnessGroup(raw).kernelCallCount = 6; }],
    ['wrong run identity', (raw) => { robustnessGroup(raw).runId = 'other-run'; }],
    ['wrong report identity', (raw) => { robustnessGroup(raw).reportArtifactId = 'other-report'; }],
    ['wrong candidate identity', (raw) => { (robustnessGroup(raw).candidate as LooseRecord).candidateId = 'candidate-a'; }],
    ['wrong selection identity', (raw) => { (raw.report.selectionDecision as LooseRecord).selectedCandidateId = 'candidate-a'; }],
    ['wrong comparison artifact', (raw) => { (robustnessGroup(raw).finalTrainingComparison as LooseRecord).artifactId = 'fixture-report'; }],
    ['wrong dataset identity', (raw) => { (robustnessGroup(raw).dataset as LooseRecord).datasetId = 'other-dataset'; }],
    ['wrong legacy split identity', (raw) => { (robustnessGroup(raw).trainingSplit as LooseRecord).sealedSplitDigest = 'g'.repeat(64); }],
  ])('rejects robustness sensitivity with %s', (_label, mutate) => {
    const raw = robustnessSnapshotRaw();
    mutate(raw);
    expect(parseQuantWorkspaceSnapshot(raw).snapshot).toBeNull();
  });

  it('exposes a stable error class for compatibility failures', () => {
    const input = cloneFixture();
    input.version = 'incompatible-v1';

    const { compatibility } = parseQuantWorkspaceSnapshot(input);
    const error = new QuantWorkspaceCompatibilityError(compatibility);

    expect(error.name).toBe('QuantWorkspaceCompatibilityError');
    expect(error.compatibility).toBe(compatibility);
    expect(error.message).toMatch(/incompatible-v1/);
    expect(error.message).toMatch(QUANT_WORKSPACE_SUPPORTED_VERSION);
  });
});
