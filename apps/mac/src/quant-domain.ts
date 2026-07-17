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

export function quantAuthenticityLabel(authenticity: QuantAuthenticity): 'Synthetic Demo Fixture' | 'Imported Demo Fixture' {
  return authenticity === 'synthetic_fixture' ? 'Synthetic Demo Fixture' : 'Imported Demo Fixture';
}
