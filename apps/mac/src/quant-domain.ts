export type QuantResearchMode = 'ask' | 'plan' | 'auto_research';
export type QuantBarInterval = '1h' | '4h' | '1D';
export type QuantDatasetContract = 'legacy-daily-v1' | 'market-v2';
export type QuantRunContract = 'legacy-daily-v1' | 'market-v2-public' | 'market-v2-private';

export type QuantRunState =
  | 'draft'
  | 'planning'
  | 'waiting_plan_approval'
  | 'queued'
  | 'loading_data'
  | 'generating_candidates'
  | 'running_experiments'
  | 'repairing'
  | 'validating'
  | 'generating_report'
  | 'waiting_for_review'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'unknown';

export type QuantStepStatus = 'pending' | 'active' | 'waiting' | 'completed' | 'failed' | 'skipped';
export type CandidateVerdict = 'promising' | 'inconclusive' | 'rejected' | 'invalid';
export type QuantAuthenticity = 'synthetic_fixture' | 'imported' | 'collected';
export type QuantOwner = 'user' | 'system' | 'agent' | 'validator';
export type QuantNavDestination = 'new_research' | 'projects' | 'runs' | 'data' | 'settings';

export type QuantCommand =
  | 'ask'
  | 'generate_plan'
  | 'start_auto_research'
  | 'run_fixture'
  | 'approve_plan'
  | 'request_plan_changes'
  | 'approve_execution'
  | 'cancel_run'
  | 'retry_run'
  | 'complete_review'
  | 'start_new_run';

export interface QuantLimits {
  maxExperiments: number;
  maxRepairAttempts: number;
  maxRuntimeMinutes: number;
  internetAccess: false;
  arbitraryPython: false;
  paperTrading: false;
}

export interface QuantResearchScope {
  version: number;
  symbol: string;
  market: string;
  interval: QuantBarInterval;
  dateRange: { start: string; end: string };
  benchmark: string;
  assumptions: string[];
}

export interface QuantResearchProject {
  id: string;
  latestRunId?: string;
  title: string;
  goal: string;
  symbol: string;
  updatedAt: string;
  statusLabel: string;
  needsAction: boolean;
}

export interface QuantResearchRun {
  contract: QuantRunContract;
  id: string;
  rowVersion: number;
  attemptNumber: number;
  state: QuantRunState;
  mode: QuantResearchMode;
  currentStepId: string;
  latestSequence: number;
  startedAt: string;
  completedAt: string | null;
  usedExperiments: number;
  usedRepairAttempts: number;
  agentIteration: number;
  maxAgentIterations: number;
  provider: string;
  model: string | null;
  legalCommands: QuantCommand[];
  traceRef: string;
  planRevision?: number;
  retryOfRunId?: string;
  continuedFrom?: {
    parentRunId: string;
    seedCandidateId: string;
    candidateName: string;
    sourceQuestion: string;
    reason: string;
  };
}

export interface QuantPlanStep {
  id: string;
  title: string;
  description: string;
  owner: QuantOwner;
  status: QuantStepStatus;
  artifactCount: number;
  humanGate: boolean;
}

export interface QuantRunEvent {
  id: string;
  sequence: number;
  type: string;
  timestamp: string;
  actor: QuantOwner;
  safeSummary: string;
  artifactId?: string;
  action?: string;
  expectedResult?: string;
  candidateId?: string;
  artifactIds?: string[];
}

export type QuantArtifactType =
  | 'research_scope'
  | 'dataset_snapshot'
  | 'strategy_spec'
  | 'backtest_result'
  | 'equity_curve'
  | 'trade_log'
  | 'validation_report'
  | 'research_report'
  | 'execution_log';

export interface QuantArtifact {
  id: string;
  type: QuantArtifactType;
  title: string;
  summary: string;
  status: 'draft' | 'ready' | 'reviewed' | 'rejected';
  origin: string;
  authenticity: QuantAuthenticity;
  relatedLabel: string;
  digest: string;
}

interface DatasetSnapshotBase {
  id: string;
  name: string;
  symbol: string;
  dateRange: { start: string; end: string };
  barCount: number;
  schemaVersion: string;
  digest: string;
  authenticity: QuantAuthenticity;
  researchEligible: boolean;
  createdAt?: string;
}

export interface LegacyDatasetSnapshot extends DatasetSnapshotBase {
  contract: 'legacy-daily-v1';
  interval: '1D';
  parserVersion: string;
  source?: DatasetSource;
  quality?: DatasetDataQuality;
}

export interface QuantMarketDatasetSource {
  kind: 'csv_upload' | 'provider_fetch';
  fileName: string | null;
  sourceName: string;
  sourceReference: string | null;
  normalizerVersion: string;
  retrievedAtUtc: string | null;
  requestedBarCount: number | null;
  returnedBarCount: number | null;
  retainedBarCount: number | null;
  closedDroppedCount: number | null;
  deduplicatedCount: number | null;
  terminationReason: 'requested_limit' | 'history_exhausted' | 'page_cap' | null;
  targetSatisfied: boolean | null;
  submittedCsvDigest?: string | null;
  batchDigest?: string | null;
}

export interface QuantMarketDatasetQuality {
  status: 'accepted' | 'blocked';
  cadenceGapCount: number;
  normalizationNote: string;
}

export interface QuantMarketDatasetSnapshot extends DatasetSnapshotBase {
  contract: 'market-v2';
  interval: QuantBarInterval;
  parserVersion: string;
  recordDigest?: string;
  periodsPerYear: number | null;
  marketCalendar: 'unknown' | 'weekday' | '24x7' | 'XNYS' | 'XNAS' | 'XSHG' | 'XSHE';
  marketSession: 'unknown' | 'continuous' | 'regular';
  timeZone: string;
  source: QuantMarketDatasetSource;
  quality: QuantMarketDatasetQuality;
  runtimeDescriptorDigest?: string;
  sealedSplitDigest?: string;
}

export type DatasetSnapshot = LegacyDatasetSnapshot | QuantMarketDatasetSnapshot;

export interface DatasetCsvSource {
  kind: 'csv_upload';
  fileName: string | null;
  sourceName: string;
  sourceReference: string | null;
  submittedCsvDigest: string | null;
  marketCalendar?: 'unknown' | 'weekday' | '24x7' | 'XNYS' | 'XNAS' | 'XSHG' | 'XSHE';
  timeZone?: string;
  priceAdjustment: 'unknown' | 'unadjusted' | 'split_adjusted' | 'total_return_adjusted';
}

export interface DatasetProviderFetchSource {
  kind: 'provider_fetch';
  sourceName: string;
  sourceReference: string | null;
  submittedCsvDigest: string | null;
  marketCalendar: 'unknown' | 'weekday' | '24x7' | 'XNYS' | 'XNAS' | 'XSHG' | 'XSHE';
  timeZone: string;
  priceAdjustment: 'unknown' | 'unadjusted' | 'split_adjusted' | 'total_return_adjusted';
  providerId: string;
  providerResponseAttestations: Array<{
    kind: string;
    digest: string;
    sourceReference: string;
  }>;
  retrievedAt: string;
  requestedLimit: number;
  returnedBarCount: number;
  droppedIncompleteCount: number;
  normalizationNote: string;
  attestationStatus: string;
  priceAdjustmentVerificationStatus?: string;
  corporateActionsAttestation?: {
    dividendsStatus: string;
    splitsStatus: string;
    coverageStart: string | null;
    coverageEnd: string | null;
    dividendCoverageStart?: string | null;
    dividendCoverageEnd?: string | null;
    splitCoverageStart?: string | null;
    splitCoverageEnd?: string | null;
    splitSnapshotAsOf?: string | null;
    splitCompletenessStatus?: string;
    splitReconciliationStatus?: string;
    splitEvents?: Array<{ effectiveDate: string; ratioNumerator: number; ratioDenominator: number }>;
    dividendEventCount: number | null;
    splitEventCount: number | null;
    note: string;
  };
}

export type DatasetSource = DatasetCsvSource | DatasetProviderFetchSource;

export interface DatasetDataQuality {
  schemaVersion: string;
  policyVersion: string;
  status: 'passed' | 'warning' | 'blocked';
  verificationStatus: 'checked' | 'rejected';
  reportDigest: string;
  datasetDigest: string;
  barCount: number;
  calendarGapCount: number;
  largestCalendarGapDays: number;
  unexpectedSessionCount?: number;
  zeroVolumeBarCount: number;
  priceJumpCount: number;
  issues: Array<{
    code: string;
    severity: string;
    message: string;
    count: number;
  }>;
  notes: string[];
}

export interface MarketBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  decimalValues?: { open: string; high: string; low: string; close: string; volume: string };
  marker?: 'entry' | 'exit' | 'market' | 'earnings' | 'policy' | 'macro';
}

export interface QuantDatasetPreview {
  contract: QuantDatasetContract;
  datasetId: string;
  symbol: string;
  interval: QuantBarInterval;
  authenticity: QuantAuthenticity;
  coveredStart: string;
  coveredEnd: string;
  totalBarCount: number;
  returnedBarCount: number;
  maxPoints: number;
  samplingRule: 'latest_contiguous';
  bars: MarketBar[];
}

export interface BacktestMetrics {
  annualizedReturn: number;
  maxDrawdown: number;
  sharpe: number;
  trades: number;
}

export interface QuantCandidate {
  id: string;
  name: string;
  parameters: string;
  verdict: CandidateVerdict;
  verdictReason: string;
  metrics: BacktestMetrics;
  strategySpecVersion: string;
  strategySpec: string;
  canSeedResearch?: boolean;
  robustness: string[];
  evolution?: QuantCandidateEvolution;
}

export interface QuantCandidateEvolution {
  hypothesis: string;
  origin: 'initial' | 'training_feedback';
  changeRationale: string | null;
  feedbackReferenceCandidateId: string | null;
  feedbackReferenceCandidateName: string | null;
  comparisonRank: number | null;
  comparisonCandidateCount: number | null;
  selectionReason: string;
  replanRepair?: {
    rejectedAction: 'refine_parameters';
    correctedAction: 'switch_approved_family';
    retainedInputs: true;
    outcome: 'candidate_created';
  };
}

export type QuantLiveCandidateState = 'completed' | 'running' | 'queued' | 'repairing' | 'revised' | 'failed';

export interface QuantLiveCandidate {
  id: string;
  ordinal: number;
  name: string;
  hypothesis: string;
  parameters: string;
  state: QuantLiveCandidateState;
  repairCount: number;
  metrics: BacktestMetrics | null;
}

export interface QuantLiveResearch {
  phase: QuantRunState;
  phaseLabel: string;
  iteration: number;
  currentExperiment: QuantLiveCandidate | null;
  latestResult: QuantLiveCandidate | null;
  candidates: QuantLiveCandidate[];
  nextStep: string;
}

interface TradeRecordBase {
  id: string;
  candidateId: string;
  entryDate: string;
  exitDate: string;
  returnPct: number;
  reason: string;
}

export interface LegacyTradeRecord extends TradeRecordBase {
  holdingDays: number;
  holdingBars?: never;
  holdingElapsedSeconds?: never;
}

export interface MarketTradeRecord extends TradeRecordBase {
  holdingDays?: never;
  holdingBars: number;
  holdingElapsedSeconds: number;
}

export type TradeRecord = LegacyTradeRecord | MarketTradeRecord;

export interface StrategyPerformancePoint {
  date: string;
  equity: number;
  drawdown: number;
}

export interface StrategyPerformanceSeries {
  id: string;
  label: string;
  kind: 'candidate' | 'benchmark';
  points: StrategyPerformancePoint[];
}

export interface GeneralizationSplit {
  method: 'chronological';
  ruleVersion: string;
  trainBarCount: number;
  holdoutBarCount: number;
  cutoffDate: string;
  datasetId: string;
  datasetDigest: string;
  interval?: QuantBarInterval;
  periodsPerYear?: number;
  cutoffTimestampUtc?: string;
  rangeStartUtc?: string;
  rangeEndUtc?: string;
  descriptorDigest?: string;
  sealDigest?: string;
}

export interface GeneralizationMetrics {
  candidate: BacktestMetrics;
  benchmark: BacktestMetrics;
}

export interface ResearchGeneralization {
  status: 'pass' | 'fail' | 'inconclusive' | 'not_evaluated';
  reason: string;
  selectedCandidateId?: string | null;
  split: GeneralizationSplit;
  train?: GeneralizationMetrics;
  holdout?: GeneralizationMetrics;
}

export interface WalkForwardFold {
  foldIndex: number;
  historyStart: string;
  historyEnd: string;
  evaluationStart: string;
  evaluationEnd: string;
  candidate: BacktestMetrics;
  benchmark: BacktestMetrics;
  status: 'pass' | 'fail' | 'inconclusive' | 'not_evaluated';
  marketRegime?: WalkForwardMarketRegime;
}

export interface WalkForwardMarketRegime {
  label: string;
  trend: 'uptrend' | 'downtrend' | 'sideways';
  volatility: 'high_volatility' | 'normal_volatility';
  historyStart: string;
  historyEnd: string;
  historyBarCount: number;
  trailingReturn: number;
  annualizedVolatility: number;
}

export interface WalkForwardRegimeSummary {
  label: string;
  foldCount: number;
  candidateMedianReturn: number;
  benchmarkMedianReturn: number;
  candidateMedianDrawdown: number;
  benchmarkMedianDrawdown: number;
  candidateMedianSharpe: number;
  benchmarkMedianSharpe: number;
}

export interface ResearchWalkForward {
  method: 'expanding';
  ruleVersion: string;
  evaluationPartition: 'train';
  foldCount: number;
  windowBarCount: number;
  stateRuleVersion?: string;
  stateLookbackBars?: number;
  status: 'completed' | 'not_evaluated';
  reason: string;
  folds: WalkForwardFold[];
  aggregate: {
    evaluatedFolds: number;
    candidatePositiveReturnFolds: number;
    candidateLowerDrawdownFolds: number;
    candidateMedianReturn: number;
    benchmarkMedianReturn: number;
    candidateMedianDrawdown: number;
    benchmarkMedianDrawdown: number;
    candidateMedianSharpe: number;
    benchmarkMedianSharpe: number;
    distinctMarketRegimes?: number;
    regimeDiversityStatus?: 'covered' | 'insufficient_regime_diversity';
    byMarketRegime?: WalkForwardRegimeSummary[];
  };
}

export interface QuantRobustnessMetrics {
  totalReturnPct: number;
  annualizedReturnPct: number;
  maximumDrawdownPct: number;
  sharpeRatio: number;
  tradeCount: number;
  winRatePct: number;
  finalEquity: number;
}

export interface QuantRobustnessSensitivity {
  schemaVersion: 'robustness_sensitivity_v1';
  evaluationPartition: 'train';
  runId: string;
  reportArtifactId: string;
  candidate: { candidateId: string; template: 'sma_crossover' | 'rsi_mean_reversion' | 'breakout'; parameters: Record<string, number>; canonicalKey: string };
  finalTrainingComparison: { artifactId: string; artifactDigest: string };
  dataset: { datasetId: string; datasetDigest: string };
  interval: QuantBarInterval;
  periodsPerYear: number;
  runtimeDescriptorDigest: string;
  trainingSplit: { identityKind: 'sealed_market_split' | 'deterministic_legacy_split'; ruleVersion: 'chronological-80-20-v1'; trainingBarCount: number; trainingStart: string; trainingEnd: string; trainingSplitDigest: string; sealedSplitDigest: string | null };
  executionRuleVersion: 'quant-execution-cost-policy-v1';
  samplerRuleVersion: 'oat-parameter-neighborhood-v1';
  costScenarios: Array<{ scenario: 'baseline_1x' | 'stressed_2x' | 'stressed_4x'; multiplier: 1 | 2 | 4; feeRate: number; slippageRate: number; candidateMetrics: QuantRobustnessMetrics; benchmarkMetrics: QuantRobustnessMetrics }>;
  parameterNeighbors: Array<{ parameterName: string; direction: 'lower' | 'upper'; parameters: Record<string, number>; canonicalKey: string; candidateMetrics: QuantRobustnessMetrics }>;
  kernelCallCount: number;
}

export interface ResearchReport {
  id: string;
  title: string;
  conclusion: string;
  proposedNextStep: string;
  limitations: string[];
  humanReviewStatus: string;
  validatorVersion: string;
  generationMethod: string;
  disclaimer: string;
  selectionDecision?: QuantSelectionDecision;
  iterationStop?: QuantIterationStop;
  generalization?: ResearchGeneralization;
  walkForward?: ResearchWalkForward;
  robustnessSensitivity?: QuantRobustnessSensitivity;
  datasetQuality?: DatasetDataQuality | QuantMarketDatasetQuality;
  datasetContext?: {
    symbol: string;
    interval: QuantBarInterval;
    periodsPerYear: number;
    range: { start: string; end: string };
    runtimeDescriptorDigest: string;
    sealedSplitDigest: string;
  };
}

export interface QuantSelectionDecision {
  basis: 'approved_objective_rank' | 'robustness_override';
  selectedCandidateId?: string;
  reason?: 'walk_forward_stability' | 'regime_coverage' | 'minimum_trade_evidence';
  referenceCandidateId?: string;
}

export interface QuantIterationStop {
  reason: 'no_novel_candidate' | 'insufficient_action_budget';
  referenceCandidateId: string;
}

export interface QuantKernelResult {
  id: string;
  label: string;
  totalReturnPct: number;
  annualizedReturnPct: number;
  maxDrawdownPct: number;
  sharpe: number;
  tradeCount: number;
  finalEquity: number;
}

export interface QuantKernelCheck {
  status: 'available' | 'verified';
  engineVersion: string;
  datasetId: string;
  datasetDigest: string;
  barCount: number;
  execution: 'signal_at_close_fill_next_open';
  feeRateBps: number;
  slippageRateBps: number;
  benchmark: QuantKernelResult | null;
  strategies: QuantKernelResult[];
  limitations: string[];
  interval?: QuantBarInterval;
  periodsPerYear?: number;
  runtimeDescriptorDigest?: string;
  sealedSplitDigest?: string;
}

export interface QuantWorkspaceSnapshot {
  workspaceName: string;
  version: string;
  authenticity: QuantAuthenticity;
  runtimeLabel: string;
  modelLabel: string;
  project: QuantResearchProject;
  recentProjects: QuantResearchProject[];
  scope: QuantResearchScope;
  run: QuantResearchRun;
  limits: QuantLimits;
  plan: QuantPlanStep[];
  researchPlan?: QuantExecutableResearchPlan;
  researchMemory?: QuantResearchMemoryProjection;
  events: QuantRunEvent[];
  artifacts: QuantArtifact[];
  dataset: DatasetSnapshot;
  bars: MarketBar[];
  kernelCheck: QuantKernelCheck;
  benchmark: BacktestMetrics | null;
  candidates: QuantCandidate[];
  liveResearch: QuantLiveResearch | null;
  performanceSeries: StrategyPerformanceSeries[];
  trades: TradeRecord[];
  report: ResearchReport | null;
  composerLegalCommands: QuantCommand[];
}

export interface QuantExecutableResearchPlan {
  candidateFamilies: ('sma_crossover' | 'rsi_mean_reversion' | 'breakout')[];
  selectionObjective: 'risk_adjusted_return' | 'total_return' | 'drawdown_control';
  completionCriteria: string[];
  objectiveSummary?: string;
  strategyScope?: QuantStrategyScopeDecision;
}

export interface QuantStrategyScopeDecision {
  schemaVersion: 'quant-strategy-scope-v1';
  status: 'supported' | 'bounded_proxy' | 'unsupported';
  reason: string;
  proxyDescription?: string;
  excludedBehaviors: string[];
}

export interface QuantResearchMemoryProjection {
  sourceRunCount: number;
  testedCandidateCount: number;
}

export interface QuantCompatibility {
  schemaVersion: string;
  supported: boolean;
  degraded: boolean;
  missingFields: string[];
  unknownFields: string[];
  warnings: string[];
}

export function quantAuthenticityLabel(authenticity: QuantAuthenticity): 'Synthetic Demo Fixture' | 'Imported Dataset' | 'Collected Dataset' {
  if (authenticity === 'synthetic_fixture') return 'Synthetic Demo Fixture';
  return authenticity === 'collected' ? 'Collected Dataset' : 'Imported Dataset';
}

export function quantResearchModeLabel(mode: QuantResearchMode | 'auto'): 'Ask' | 'Plan' | 'Auto Research' {
  if (mode === 'ask') return 'Ask';
  if (mode === 'plan') return 'Plan';
  return 'Auto Research';
}
