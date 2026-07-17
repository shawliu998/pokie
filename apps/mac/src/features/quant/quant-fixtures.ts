import type { MarketBar, QuantPlanStep, QuantRunEvent, QuantWorkspaceSnapshot } from '../../quant-domain';

const plan: QuantPlanStep[] = [
  ['scope', 'Define research scope', 'Freeze SPY, 1D, benchmark, date range, assumptions, and limits.', 'user', 1, true],
  ['dataset', 'Load market dataset', 'Verify and pin the immutable SPY fixture snapshot.', 'system', 1, false],
  ['benchmark', 'Build benchmark', 'Prepare the Buy and Hold comparison.', 'system', 1, false],
  ['candidates', 'Generate candidates', 'Persist three bounded moving-average candidates.', 'agent', 3, false],
  ['experiments', 'Run experiments', 'Record deterministic fixture backtest results.', 'agent', 6, false],
  ['repair', 'Repair recoverable failures', 'Retain one bounded repair attempt without changing scope.', 'agent', 1, false],
  ['validation', 'Validate robustness', 'Apply sensitivity, cost, split, and concentration checks.', 'validator', 1, false],
  ['comparison', 'Compare candidates', 'Compare candidates with the approved benchmark.', 'agent', 1, false],
  ['report', 'Generate report', 'Create the final auditable Research Report.', 'agent', 1, false],
  ['decision', 'Human decision', 'Review the research result and choose the next governed step.', 'user', 1, true],
].map(([id, title, description, owner, artifactCount, humanGate]) => ({
  id: String(id), title: String(title), description: String(description), owner: owner as QuantPlanStep['owner'],
  artifactCount: Number(artifactCount), humanGate: Boolean(humanGate), status: 'completed',
}));

const event = (sequence: number, type: string, timestamp: string, actor: QuantRunEvent['actor'], safeSummary: string, artifactId?: string): QuantRunEvent => ({
  id: `quant-event-${sequence}`, sequence, type, timestamp, actor, safeSummary, artifactId,
});

const closes = [196, 207, 202, 218, 226, 220, 238, 246, 241, 258, 269, 263, 281, 292, 286, 307, 316, 309, 332, 345, 338, 356, 369, 382];
const bars: MarketBar[] = closes.map((close, index) => ({
  date: `${2018 + Math.floor(index / 4)}-${String((index % 4) * 3 + 1).padStart(2, '0')}-02`,
  open: close - (index % 3 === 0 ? 5 : -2),
  high: close + 8 + (index % 4),
  low: close - 9 - (index % 3),
  close,
  volume: 62_000_000 + (index % 6) * 9_000_000,
  marker: index === 4 ? 'entry' : index === 8 ? 'policy' : index === 12 ? 'exit' : index === 17 ? 'macro' : index === 20 ? 'entry' : undefined,
}));

export const quantFixtureSnapshot: QuantWorkspaceSnapshot = {
  workspaceName: 'PokieQuant Research',
  version: 'Phase 0 · fixture-v1',
  authenticity: 'synthetic_fixture',
  runtimeLabel: 'Deterministic',
  modelLabel: 'Not connected',
  project: {
    id: 'quant-project-spy-trend', title: 'SPY · Trend Research', symbol: 'SPY', statusLabel: 'Completed · review result',
    needsAction: false, updatedAt: '2026-07-17T10:24:00+08:00',
    goal: 'Evaluate whether simple trend-following rules improve SPY drawdown characteristics without relying on fragile parameters.',
  },
  recentProjects: [
    { id: 'quant-project-spy-trend', title: 'SPY · Trend Research', symbol: 'SPY', statusLabel: 'Completed', needsAction: false, updatedAt: '2026-07-17T10:24:00+08:00', goal: 'Evaluate bounded SPY trend rules.' },
    { id: 'quant-project-nvda-news', title: 'NVDA · News Reaction', symbol: 'NVDA', statusLabel: 'Plan draft', needsAction: true, updatedAt: '2026-07-16T16:10:00+08:00', goal: 'Plan an event-reaction study.' },
    { id: 'quant-project-btc-breakout', title: 'BTC · Breakout Study', symbol: 'BTC', statusLabel: 'Archived fixture', needsAction: false, updatedAt: '2026-07-12T09:40:00+08:00', goal: 'Review a bounded breakout study.' },
  ],
  scope: {
    version: 3, symbol: 'SPY', market: 'US Equity', interval: '1D', benchmark: 'SPY Buy and Hold',
    dateRange: { start: '2018-01-02', end: '2023-12-29' },
    assumptions: ['Daily close execution fixture', '10 bps round-trip cost assumption', 'No leverage or shorting'],
  },
  run: {
    id: 'quant-run-spy-01', rowVersion: 12, attemptNumber: 1, state: 'completed', mode: 'auto_research',
    currentStepId: 'decision', latestSequence: 18, startedAt: '2026-07-17T10:18:00+08:00', completedAt: '2026-07-17T10:24:00+08:00',
    usedExperiments: 3, usedRepairAttempts: 1, legalCommands: ['start_new_run'], traceRef: 'fixture-trace-spy-01',
  },
  limits: { maxExperiments: 3, maxRepairAttempts: 2, maxRuntimeMinutes: 5, internetAccess: false, arbitraryPython: false, paperTrading: false },
  plan,
  events: [
    event(18, 'run.completed', '2026-07-17T10:24:00+08:00', 'system', 'Research process completed; candidate verdicts remain independent.', 'artifact-research-report'),
    event(17, 'report.generated', '2026-07-17T10:23:40+08:00', 'agent', 'Research Report generated from persisted fixture artifacts.', 'artifact-research-report'),
    event(16, 'candidate.promoted', '2026-07-17T10:23:12+08:00', 'validator', 'Candidate B retained for paper evaluation review; no trading action was enabled.'),
    event(15, 'candidate.rejected', '2026-07-17T10:23:02+08:00', 'validator', 'Candidate A rejected for parameter sensitivity; the run continued normally.'),
    event(14, 'validation.completed', '2026-07-17T10:22:48+08:00', 'validator', 'Robustness validation completed for all three candidates.', 'artifact-validation'),
    event(11, 'repair.completed', '2026-07-17T10:21:26+08:00', 'system', 'One candidate-scoped fixture repair completed within the approved limit.', 'artifact-execution-log'),
    event(6, 'data.load.completed', '2026-07-17T10:19:05+08:00', 'system', 'Immutable SPY daily fixture snapshot loaded.', 'artifact-dataset'),
  ],
  artifacts: [
    { id: 'artifact-research-report', type: 'research_report', title: 'SPY Trend Research Report', summary: 'Candidate B has the strongest fixture robustness profile; Candidate A is rejected and Candidate C is inconclusive.', status: 'reviewed', origin: 'Deterministic fixture projection', authenticity: 'synthetic_fixture', relatedLabel: 'Run 01 · attempt 1', digest: 'sha256:fixture-report-4e91' },
    { id: 'artifact-validation', type: 'validation_report', title: 'Robustness Validation', summary: 'Sensitivity, cost, concentration, and time-split checks for three candidates.', status: 'ready', origin: 'Validator fixture', authenticity: 'synthetic_fixture', relatedLabel: '3 candidates', digest: 'sha256:fixture-validation-5b20' },
    { id: 'artifact-dataset', type: 'dataset_snapshot', title: 'SPY Daily Snapshot', summary: 'Immutable bounded OHLCV fixture used by this attempt.', status: 'ready', origin: 'Bundled fixture repository', authenticity: 'synthetic_fixture', relatedLabel: '1,509 daily bars', digest: 'sha256:fixture-spy-bars-a120' },
    { id: 'artifact-execution-log', type: 'execution_log', title: 'Safe Execution Log', summary: 'Closed fixture events for experiments, one repair, validation, and reporting.', status: 'ready', origin: 'Deterministic runtime', authenticity: 'synthetic_fixture', relatedLabel: '18 events', digest: 'sha256:fixture-log-c3f1' },
  ],
  dataset: { id: 'dataset-spy-daily-v1', name: 'SPY Daily Fixture 2018–2023', symbol: 'SPY', interval: '1D', dateRange: { start: '2018-01-02', end: '2023-12-29' }, barCount: 1509, schemaVersion: 'market-bars-v1', parserVersion: 'fixture-parser-v1', digest: 'sha256:fixture-spy-bars-a120', authenticity: 'synthetic_fixture' },
  bars,
  benchmark: { annualizedReturn: 10.8, maxDrawdown: -33.7, sharpe: 0.72, trades: 1 },
  candidates: [
    { id: 'candidate-a', name: 'Candidate A · SMA 20/100', parameters: 'fast=20 · slow=100', verdict: 'rejected', verdictReason: 'Parameter sensitivity', metrics: { annualizedReturn: 9.6, maxDrawdown: -24.8, sharpe: 0.83, trades: 38 }, strategySpecVersion: 'strategy-spec-v1.1', strategySpec: 'family: sma_cross\nfast_window: 20\nslow_window: 100\nposition: long_or_cash', robustness: ['Fails adjacent-window sensitivity check', 'Cost check passes', 'Concentration check passes'] },
    { id: 'candidate-b', name: 'Candidate B · SMA 50/200', parameters: 'fast=50 · slow=200', verdict: 'promising', verdictReason: 'Candidate for paper evaluation', metrics: { annualizedReturn: 8.9, maxDrawdown: -18.7, sharpe: 0.88, trades: 18 }, strategySpecVersion: 'strategy-spec-v1.0', strategySpec: 'family: sma_cross\nfast_window: 50\nslow_window: 200\nposition: long_or_cash', robustness: ['Sensitivity check passes', 'Cost check passes', 'Time-split check passes with limitation'] },
    { id: 'candidate-c', name: 'Candidate C · 200-day trend filter', parameters: 'window=200', verdict: 'inconclusive', verdictReason: 'Too few independent trade periods', metrics: { annualizedReturn: 9.3, maxDrawdown: -21.4, sharpe: 0.86, trades: 12 }, strategySpecVersion: 'strategy-spec-v1.0', strategySpec: 'family: trend_filter\nwindow: 200\nposition: long_or_cash', robustness: ['Cost check passes', 'Insufficient independent periods', 'More out-of-sample evidence required'] },
  ],
  trades: [
    { id: 'trade-1', candidateId: 'candidate-b', entryDate: '2018-04-04', exitDate: '2018-10-19', returnPct: 4.8, holdingDays: 198, reason: '50-day SMA crossed above 200-day SMA' },
    { id: 'trade-2', candidateId: 'candidate-b', entryDate: '2019-04-12', exitDate: '2020-03-09', returnPct: 9.2, holdingDays: 332, reason: 'Trend exit after slow average break' },
    { id: 'trade-3', candidateId: 'candidate-b', entryDate: '2020-07-07', exitDate: '2022-03-11', returnPct: 31.4, holdingDays: 612, reason: '50-day SMA crossed above 200-day SMA' },
  ],
  report: {
    id: 'report-spy-01', title: 'SPY Trend Research Report', conclusion: 'Candidate B has the strongest robustness profile in this synthetic fixture. Candidate A is rejected; Candidate C remains inconclusive.', proposedNextStep: 'Design a separate, governed paper-evaluation plan. No broker or paper-trading connection is enabled.', limitations: ['All displayed market data and results are synthetic demonstration fixtures.', 'The Phase 0 shell did not run a real backtest or retrieve market data.', 'A research workflow label is not an investment recommendation.'], humanReviewStatus: 'Reviewed fixture report', validatorVersion: 'validator-fixture-v1', generationMethod: 'Deterministic fixture projection', disclaimer: 'This product is a research interface. Demonstration results are synthetic and are not investment advice, a recommendation, or evidence of future performance.',
  },
  composerLegalCommands: ['ask', 'generate_plan'],
};
