export type Authenticity = 'seed' | 'imported' | 'collected' | 'generated' | 'human_authored';
export type Destination = 'inbox' | 'investigations' | 'decisions' | 'monitoring';
export type Impact = 'high' | 'medium' | 'low' | 'unknown' | null;
export type Urgency = 'now' | 'this_week' | 'monitor' | 'unknown' | null;
export type Priority = 'P0' | 'P1' | 'P2' | 'P3' | null;
export type EvidenceStatus = 'proposed' | 'valid' | 'weak' | 'rejected';
export type ClaimStatus = 'proposed' | 'needs_review' | 'verified' | 'rejected' | 'superseded';
export type RunState = 'queued' | 'running' | 'waiting_for_input' | 'completed' | 'failed' | 'cancelled';
export type ResearchGenerationMethod = 'deterministic' | 'model';

export interface SourceFreshness {
  state: 'current' | 'stale' | 'never';
  lastSuccessAt: string | null;
}

export interface SourceHealth {
  id: string;
  workspaceId: string;
  name: string;
  sourceKind: 'cloud' | 'local' | 'imported_dataset';
  connectorType: 'csv' | 'seed_fixture' | 'github' | 'rss';
  runtime: 'static_import' | 'cloud' | 'mac_device';
  connectorVersion: string;
  sourceConfig: GitHubSourceConfig | RssSourceConfig | null;
  cadence: 'daily' | 'weekly' | 'manual' | null;
  timezone: string | null;
  capabilities: Array<'search' | 'fetch' | 'health'>;
  rowVersion: number;
  currentImportManifestId: string | null;
  status: 'draft' | 'validating' | 'healthy' | 'degraded' | 'auth_required' | 'disabled' | 'failed';
  health: { state: 'unknown' | 'healthy' | 'degraded' | 'auth_required' | 'rate_limited' | 'failed' | 'disabled'; checkedAt: string | null; lastErrorCode: string | null };
  freshness: SourceFreshness;
  lastRunAt: string | null;
  authenticity: Authenticity;
}

export interface GitHubSourceConfig {
  connectorType: 'github';
  repositories: Array<{ owner: string; repository: string; includeIssues: boolean; includeDiscussions: boolean; includeReleases: boolean }>;
}

export interface RssSourceConfig {
  connectorType: 'rss';
  feeds: Array<{ name: string; feedUrl: string }>;
}

export interface WatchlistSummary {
  id: string;
  projectId: string;
  name: string;
  objective: string;
  status: 'draft' | 'active' | 'paused' | 'archived';
  sourceConnectionIds: string[];
  rules: { entities: string[]; includeTerms: string[]; excludeTerms: string[]; languages: string[]; regions: string[]; cadence: 'realtime' | 'daily' | 'weekly' | 'manual'; currentWindowDays: number; baselineWindowDays: number };
  initialBaseline: { status: 'collecting' | 'insufficient' | 'ready'; currentCount: number; requiredCount: number; candidateCount: number; expectedDetectableAt: string | null; reason: string | null; lastTerminalRunAt: string | null };
  rowVersion: number;
}

export interface CollectionSchedule {
  id: string;
  sourceConnectionId: string;
  watchlistId: string;
  query: Record<string, unknown>;
  cadenceSeconds: number;
  timezone: string;
  misfirePolicy: 'skip' | 'run_once';
  catchUp: boolean;
  overlapPolicy: 'skip' | 'queue_one';
  nextRunAt: string;
  enabled: boolean;
  leaseHeld: boolean;
  leaseExpiresAt: string | null;
  heartbeatAt: string | null;
  rowVersion: number;
  authenticity: Authenticity;
}

export interface PerSourceFreshness extends SourceFreshness { sourceConnectionId: string }

export interface Signal {
  id: string;
  title: string;
  watchlistId: string;
  status: 'new' | 'triaged' | 'investigating' | 'explained' | 'monitoring' | 'dismissed';
  authenticity: Authenticity;
  snapshotAt: string;
  confidence: 'high' | 'medium' | 'low';
  confidenceExplanation: string;
  triggerRules: string[];
  limitations: string[];
  totalSourceCount: number;
  independentSources: number;
  crossSourceConfirmation: boolean;
  currentCount: number;
  baselineCount: number;
  mentionCount: number;
  platformCount: number;
  growthRatio: number;
  robustZ: number;
  perSourceFreshness: PerSourceFreshness[];
  window: { currentStart: string; currentEnd: string; baselineStart: string; baselineEnd: string };
  impact: Impact;
  urgency: Urgency;
  priority: Priority;
  rowVersion: number;
  impactAssessmentVersion: number;
  urgencyAssessmentVersion: number;
  disposition: { action: 'investigate' | 'explain' | 'monitor' | 'dismiss' | 'undo'; previousStatus: Signal['status']; sessionId: string; cooldownUntil: string | null; dismissReason: 'duplicate' | 'single_author_spike' | 'irrelevant' | 'known_issue' | 'bad_data' | 'other' | null; note: string | null; transitionedAt: string; undoneAt: string | null } | null;
}

export interface Evidence {
  id: string;
  investigationId: string;
  researchRunId: string;
  stance: 'supports' | 'opposes' | 'neutral';
  quote: string;
  quoteStart: number;
  quoteEnd: number;
  contentVersionId: string;
  status: EvidenceStatus;
  provenance: { researchRunId: string; extractionMethod: string };
  latestReviewId: string | null;
  authenticity: Authenticity;
}

export interface ClaimEvidenceLink {
  id: string;
  evidenceId: string;
  stance: 'supports' | 'opposes' | 'neutral';
  weight: number;
  rationale: string | null;
}

export interface Claim {
  id: string;
  investigationId: string;
  researchRunId: string;
  versionId: string;
  rowVersion: number;
  text: string;
  status: ClaimStatus;
  limitations: string[];
  evidenceLinks: ClaimEvidenceLink[];
  authenticity: Authenticity;
}

export interface RunEvent {
  id: string;
  sequence: number;
  type: string;
  message: string;
  timestamp: string;
  authenticity: Authenticity;
}

export interface Synthesis {
  id: string;
  versionId: string;
  rowVersion: number;
  status: 'draft' | 'needs_review' | 'verified' | 'rejected' | 'superseded';
  executiveSummary: string;
  businessImplications: string[];
  limitations: string[];
  verifiedClaimVersionIds: string[];
  generationMethod: 'deterministic' | 'model';
  generatorVersion: string;
  modelPromptRefs: string[];
  authenticity: Authenticity;
}

export interface ResearchRun {
  id: string;
  state: RunState;
  rowVersion: number;
  latestSequence: number;
  attemptNumber: number;
  graphVersion: string;
  generationMethod: ResearchGenerationMethod;
  provider: string;
  model: string | null;
  promptRefs: string[];
  traceRef: string | null;
  usedCostUsd: string;
  budget: { maxCostUsd: string; maxDurationSeconds: number };
  waitingForInputReason: string | null;
}

export interface Investigation {
  id: string;
  signalId: string;
  question: string;
  status: 'draft' | 'active' | 'needs_input' | 'reviewing' | 'completed' | 'closed_insufficient' | 'cancelled';
  scopeVersionId: string;
  sourceConnectionIds: string[];
  contentVersionIds: string[];
  allowCloudModel: boolean;
  timeRange: { start: string; end: string } | null;
  run: ResearchRun | null;
  evidence: Evidence[];
  claims: Claim[];
  synthesis: Synthesis | null;
  events: RunEvent[];
  rowVersion: number;
  authenticity: Authenticity;
}

export type BriefBlock =
  | { id: string; type: 'fact'; body: string; claimVersionIds: string[]; evidenceIds: string[]; contentVersionIds: string[] }
  | { id: string; type: 'synthesis'; body: string; synthesisVersionId: string; generationMethod: 'deterministic' | 'model'; generatorVersion: string; modelPromptRefs: string[] }
  | { id: string; type: 'pm_judgment'; body: string; actorId: string }
  | { id: string; type: 'recommendation'; body: string; recommendationStatus: 'proposed' | 'accepted' | 'rejected' };

export interface NoCounterEvidenceSearch {
  queries: string[];
  sourceConnectionIds: string[];
  windowStart: string;
  windowEnd: string;
  exclusionCriteria: string[];
  limitations: string[];
}

export interface BriefBlockDocument { schemaVersion: string; blocks: BriefBlock[]; noCounterEvidenceSearch: NoCounterEvidenceSearch | null }

export interface BriefReferenceSnapshot {
  synthesisVersionId: string;
  synthesisReviewId: string;
  claimVersionIds: string[];
  claimReviewIds: string[];
  claimEvidenceIds: string[];
  evidenceReviewIds: string[];
  evidenceIds: string[];
  contentVersionIds: string[];
}

export interface DecisionBrief {
  id: string;
  investigationId: string;
  question: string;
  version: number;
  status: 'draft' | 'decision_ready' | 'decided' | 'archived';
  authenticity: Authenticity;
  freshness: 'current' | 'evidence_stale';
  readiness: 'draft' | 'decision_ready';
  rowVersion: number;
  versionId: string;
  blockDocument: BriefBlockDocument;
  referenceSnapshot: BriefReferenceSnapshot;
  templateVersion: string;
  humanEditDigest: string;
}

export interface NavigationSummary {
  unreviewedSignalCount: number;
  investigationNeedsInputCount: number;
  draftDecisionBriefCount: number;
  monitoringHealth: 'healthy' | 'degraded';
  computedAt: string;
}

export interface WorkspaceState {
  workspaceId: string;
  principalId: string;
  workspaceName: string;
  cachedAt: string | null;
  authenticity: Authenticity;
  signals: Signal[];
  investigations: Investigation[];
  briefs: DecisionBrief[];
  sources: SourceHealth[];
  watchlists: WatchlistSummary[];
  schedules: CollectionSchedule[];
  navigation: NavigationSummary;
}

export function selectCloudScheduleWatchlist(
  watchlists: WatchlistSummary[],
  sources: SourceHealth[],
): WatchlistSummary | undefined {
  const cloudSourceIds = new Set(
    sources.filter((source) => source.sourceKind === 'cloud').map((source) => source.id),
  );
  const active = watchlists.filter((watchlist) => watchlist.status === 'active');
  return active.find((watchlist) =>
    watchlist.sourceConnectionIds.some((sourceId) => cloudSourceIds.has(sourceId)),
  );
}

export function derivePriority(impact: Impact, urgency: Urgency): Priority {
  if (!impact || !urgency || impact === 'unknown' || urgency === 'unknown') return null;
  if (impact === 'high' && urgency === 'now') return 'P0';
  if ((impact === 'high' && urgency === 'this_week') || (impact === 'medium' && urgency === 'now')) return 'P1';
  if (impact === 'medium' && urgency === 'this_week') return 'P2';
  return 'P3';
}

export function priorityLabel(signal: Pick<Signal, 'impact' | 'urgency' | 'priority'>): string {
  if (signal.impact === 'unknown' || signal.urgency === 'unknown') return 'Unranked · insufficient input';
  return signal.priority ?? 'Needs triage';
}

export function authenticityLabel(value: Authenticity): string {
  return value.replace('_', ' ');
}
