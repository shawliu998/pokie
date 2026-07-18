export type QuantResearchMode = 'ask' | 'plan' | 'auto_research';

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
  | 'cancelled';

export type QuantStepStatus = 'pending' | 'active' | 'waiting' | 'completed' | 'failed' | 'skipped';
export type CandidateVerdict = 'promising' | 'inconclusive' | 'rejected' | 'invalid';
export type QuantAuthenticity = 'synthetic_fixture' | 'imported_fixture';
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
  interval: '1D';
  dateRange: { start: string; end: string };
  benchmark: string;
  assumptions: string[];
}

export interface QuantResearchProject {
  id: string;
  title: string;
  goal: string;
  symbol: string;
  updatedAt: string;
  statusLabel: string;
  needsAction: boolean;
}

export interface QuantResearchRun {
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

export interface DatasetSnapshot {
  id: string;
  name: string;
  symbol: string;
  interval: '1D';
  dateRange: { start: string; end: string };
  barCount: number;
  schemaVersion: string;
  parserVersion: string;
  digest: string;
  authenticity: QuantAuthenticity;
  source?: DatasetSource;
  quality?: DatasetDataQuality;
}

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
  marker?: 'entry' | 'exit' | 'market' | 'earnings' | 'policy' | 'macro';
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
  robustness: string[];
}

export interface TradeRecord {
  id: string;
  candidateId: string;
  entryDate: string;
  exitDate: string;
  returnPct: number;
  holdingDays: number;
  reason: string;
}

export interface GeneralizationSplit {
  method: 'chronological';
  ruleVersion: string;
  trainBarCount: number;
  holdoutBarCount: number;
  cutoffDate: string;
  datasetId: string;
  datasetDigest: string;
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
}

export interface ResearchWalkForward {
  method: 'expanding';
  ruleVersion: string;
  evaluationPartition: 'train';
  foldCount: number;
  windowBarCount: number;
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
  };
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
  generalization?: ResearchGeneralization;
  walkForward?: ResearchWalkForward;
  datasetQuality?: DatasetDataQuality;
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
  events: QuantRunEvent[];
  artifacts: QuantArtifact[];
  dataset: DatasetSnapshot;
  bars: MarketBar[];
  kernelCheck: QuantKernelCheck;
  benchmark: BacktestMetrics | null;
  candidates: QuantCandidate[];
  trades: TradeRecord[];
  report: ResearchReport | null;
  composerLegalCommands: QuantCommand[];
}

export function quantAuthenticityLabel(authenticity: QuantAuthenticity): 'Synthetic Demo Fixture' | 'Imported Dataset' {
  return authenticity === 'synthetic_fixture' ? 'Synthetic Demo Fixture' : 'Imported Dataset';
}
