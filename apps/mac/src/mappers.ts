import type {
  Authenticity,
  BriefBlock,
  BriefReferenceSnapshot,
  Claim,
  CollectionSchedule,
  DecisionBrief,
  Evidence,
  Investigation,
  NavigationSummary,
  RunState,
  Signal,
  SourceHealth,
  Synthesis,
  WatchlistSummary,
  WorkspaceState,
} from './domain';

export type JsonObject = Record<string, unknown>;

export const asObject = (value: unknown, name: string): JsonObject => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`Invalid ${name} DTO.`);
  return value as JsonObject;
};

export const asArray = (value: unknown, name: string): unknown[] => {
  if (!Array.isArray(value)) throw new Error(`Invalid ${name} DTO.`);
  return value;
};

export const asString = (value: unknown, name: string): string => {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`Invalid ${name} DTO.`);
  return value;
};

export const asNumber = (value: unknown, name: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`Invalid ${name} DTO.`);
  return value;
};

const asNullableString = (value: unknown, name: string): string | null => {
  if (value === null) return null;
  return asString(value, name);
};

const asStrings = (value: unknown, name: string): string[] => asArray(value, name).map((item, index) => asString(item, `${name}[${index}]`));

export function mapAuthenticity(value: unknown, name = 'data_authenticity'): Authenticity {
  if (value === 'seed' || value === 'imported' || value === 'collected' || value === 'generated' || value === 'human_authored') return value;
  throw new Error(`Missing or unknown ${name}.`);
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[], name: string): T {
  if (typeof value === 'string' && allowed.includes(value as T)) return value as T;
  throw new Error(`Invalid ${name} DTO.`);
}

export function mapSource(value: unknown): SourceHealth {
  const dto = asObject(value, 'SourceConnection');
  const freshness = asObject(dto.freshness, 'SourceConnection.freshness');
  const health = asObject(dto.health, 'SourceConnection.health');
  const manifest = dto.current_import_manifest === null ? null : asObject(dto.current_import_manifest, 'SourceConnection.current_import_manifest');
  const connectorType = enumValue(dto.connector_type, ['csv', 'seed_fixture', 'github', 'rss'] as const, 'SourceConnection.connector_type');
  let sourceConfig: SourceHealth['sourceConfig'] = null;
  if (dto.source_config !== null) {
    const config = asObject(dto.source_config, 'SourceConnection.source_config');
    if (connectorType === 'github') {
      sourceConfig = {
        connectorType: 'github',
        repositories: asArray(config.repositories, 'GitHubSourceConfig.repositories').map((item) => {
          const repository = asObject(item, 'GitHubRepositoryConfig');
          if (typeof repository.include_issues !== 'boolean' || typeof repository.include_discussions !== 'boolean' || typeof repository.include_releases !== 'boolean') throw new Error('Invalid GitHubRepositoryConfig DTO.');
          return { owner: asString(repository.owner, 'GitHubRepositoryConfig.owner'), repository: asString(repository.repository, 'GitHubRepositoryConfig.repository'), includeIssues: repository.include_issues, includeDiscussions: repository.include_discussions, includeReleases: repository.include_releases };
        }),
      };
    } else if (connectorType === 'rss') {
      sourceConfig = { connectorType: 'rss', feeds: asArray(config.feeds, 'RSSSourceConfig.feeds').map((item) => { const feed = asObject(item, 'RSSFeedConfig'); return { name: asString(feed.name, 'RSSFeedConfig.name'), feedUrl: asString(feed.feed_url, 'RSSFeedConfig.feed_url') }; }) };
    } else {
      throw new Error('Imported sources must not expose source_config.');
    }
  }
  return {
    id: asString(dto.id, 'SourceConnection.id'),
    workspaceId: asString(dto.workspace_id, 'SourceConnection.workspace_id'),
    name: asString(dto.name, 'SourceConnection.name'),
    sourceKind: enumValue(dto.source_kind, ['cloud', 'local', 'imported_dataset'] as const, 'SourceConnection.source_kind'),
    connectorType,
    runtime: enumValue(dto.runtime, ['static_import', 'cloud', 'mac_device'] as const, 'SourceConnection.runtime'),
    connectorVersion: asString(dto.connector_version, 'SourceConnection.connector_version'),
    sourceConfig,
    cadence: dto.cadence === null ? null : enumValue(dto.cadence, ['daily', 'weekly', 'manual'] as const, 'SourceConnection.cadence'),
    timezone: asNullableString(dto.timezone, 'SourceConnection.timezone'),
    capabilities: asArray(dto.capabilities, 'SourceConnection.capabilities').map((item) => enumValue(item, ['search', 'fetch', 'health'] as const, 'SourceConnection.capability')),
    rowVersion: asNumber(dto.row_version, 'SourceConnection.row_version'),
    currentImportManifestId: manifest ? asString(manifest.id, 'ImportManifestSummary.id') : null,
    status: enumValue(dto.status, ['draft', 'validating', 'healthy', 'degraded', 'auth_required', 'disabled', 'failed'] as const, 'SourceConnection.status'),
    health: {
      state: enumValue(health.state, ['unknown', 'healthy', 'degraded', 'auth_required', 'rate_limited', 'failed', 'disabled'] as const, 'SourceHealth.state'),
      checkedAt: asNullableString(health.checked_at, 'SourceHealth.checked_at'),
      lastErrorCode: health.last_error_code === null ? null : asString(health.last_error_code, 'SourceHealth.last_error_code'),
    },
    freshness: {
      state: enumValue(freshness.state, ['current', 'stale', 'never'] as const, 'SourceFreshness.state'),
      lastSuccessAt: asNullableString(freshness.last_success_at, 'SourceFreshness.last_success_at'),
    },
    lastRunAt: asNullableString(dto.last_run_at, 'SourceConnection.last_run_at'),
    authenticity: mapAuthenticity(dto.data_authenticity),
  };
}

export function mapWatchlist(value: unknown): WatchlistSummary {
  const dto = asObject(value, 'Watchlist');
  const rules = asObject(dto.rules, 'Watchlist.rules');
  const queryRules = asObject(rules.query_rules, 'Watchlist.rules.query_rules');
  const initialBaseline = asObject(dto.initial_baseline, 'Watchlist.initial_baseline');
  return {
    id: asString(dto.id, 'Watchlist.id'),
    projectId: asString(dto.project_id, 'Watchlist.project_id'),
    name: asString(dto.name, 'Watchlist.name'),
    objective: asString(dto.objective, 'Watchlist.objective'),
    status: enumValue(dto.status, ['draft', 'active', 'paused', 'archived'] as const, 'Watchlist.status'),
    sourceConnectionIds: asStrings(dto.source_connection_ids, 'Watchlist.source_connection_ids'),
    rules: { entities: asStrings(rules.entities, 'Watchlist.rules.entities'), includeTerms: asStrings(queryRules.include_terms, 'Watchlist.rules.query_rules.include_terms'), excludeTerms: asStrings(queryRules.exclude_terms, 'Watchlist.rules.query_rules.exclude_terms'), languages: asStrings(queryRules.languages, 'Watchlist.rules.query_rules.languages'), regions: asStrings(queryRules.regions, 'Watchlist.rules.query_rules.regions'), cadence: enumValue(rules.cadence, ['realtime', 'daily', 'weekly', 'manual'] as const, 'Watchlist.rules.cadence'), currentWindowDays: asNumber(rules.current_window_days, 'Watchlist.rules.current_window_days'), baselineWindowDays: asNumber(rules.baseline_window_days, 'Watchlist.rules.baseline_window_days') },
    initialBaseline: { status: enumValue(initialBaseline.status, ['collecting', 'insufficient', 'ready'] as const, 'Watchlist.initial_baseline.status'), currentCount: asNumber(initialBaseline.current_count, 'Watchlist.initial_baseline.current_count'), requiredCount: asNumber(initialBaseline.required_count, 'Watchlist.initial_baseline.required_count'), candidateCount: asNumber(initialBaseline.candidate_count, 'Watchlist.initial_baseline.candidate_count'), expectedDetectableAt: asNullableString(initialBaseline.expected_detectable_at, 'Watchlist.initial_baseline.expected_detectable_at'), reason: asNullableString(initialBaseline.reason, 'Watchlist.initial_baseline.reason'), lastTerminalRunAt: asNullableString(initialBaseline.last_terminal_run_at, 'Watchlist.initial_baseline.last_terminal_run_at') },
    rowVersion: asNumber(dto.row_version, 'Watchlist.row_version'),
  };
}

export function mapSchedule(value: unknown): CollectionSchedule {
  const dto = asObject(value, 'CollectionSchedule');
  if (typeof dto.catch_up !== 'boolean' || typeof dto.enabled !== 'boolean' || typeof dto.lease_held !== 'boolean') throw new Error('Invalid CollectionSchedule DTO.');
  return {
    id: asString(dto.id, 'CollectionSchedule.id'),
    sourceConnectionId: asString(dto.source_connection_id, 'CollectionSchedule.source_connection_id'),
    watchlistId: asString(dto.watchlist_id, 'CollectionSchedule.watchlist_id'),
    query: asObject(dto.query_json, 'CollectionSchedule.query_json'),
    cadenceSeconds: asNumber(dto.cadence_seconds, 'CollectionSchedule.cadence_seconds'),
    timezone: asString(dto.timezone, 'CollectionSchedule.timezone'),
    misfirePolicy: enumValue(dto.misfire_policy, ['skip', 'run_once'] as const, 'CollectionSchedule.misfire_policy'),
    catchUp: dto.catch_up,
    overlapPolicy: enumValue(dto.overlap_policy, ['skip', 'queue_one'] as const, 'CollectionSchedule.overlap_policy'),
    nextRunAt: asString(dto.next_run_at, 'CollectionSchedule.next_run_at'),
    enabled: dto.enabled,
    leaseHeld: dto.lease_held,
    leaseExpiresAt: asNullableString(dto.lease_expires_at, 'CollectionSchedule.lease_expires_at'),
    heartbeatAt: asNullableString(dto.heartbeat_at, 'CollectionSchedule.heartbeat_at'),
    rowVersion: asNumber(dto.row_version, 'CollectionSchedule.row_version'),
    authenticity: mapAuthenticity(dto.data_authenticity),
  };
}

export function mapSignal(value: unknown): Signal {
  const dto = asObject(value, 'Signal');
  const dimensions = asObject(dto.dimensions, 'Signal.dimensions');
  const impact = asObject(dimensions.business_impact, 'Signal.business_impact');
  const urgency = asObject(dimensions.urgency, 'Signal.urgency');
  const priority = asObject(dimensions.priority, 'Signal.priority');
  const confidence = asObject(dimensions.detection_confidence, 'Signal.detection_confidence');
  const metrics = asObject(dto.metrics, 'Signal.metrics');
  const window = asObject(dto.window, 'Signal.window');
  const currentCount = asNumber(metrics.current_count, 'SignalMetrics.current_count');
  const baselineCount = asNumber(metrics.baseline_count, 'SignalMetrics.baseline_count');
  const mentionCount = asNumber(metrics.mention_count, 'SignalMetrics.mention_count');
  asNumber(metrics.independent_source_count, 'SignalMetrics.independent_source_count');
  const platformCount = asNumber(metrics.platform_count, 'SignalMetrics.platform_count');
  const growthRatio = asNumber(metrics.growth_ratio, 'SignalMetrics.growth_ratio');
  const robustZ = asNumber(metrics.robust_z, 'SignalMetrics.robust_z');
  if (typeof dto.cross_source_confirmation !== 'boolean') throw new Error('Invalid Signal.cross_source_confirmation DTO.');
  const disposition = dto.disposition === null ? null : (() => { const item = asObject(dto.disposition, 'Signal.disposition'); return { action: enumValue(item.action, ['investigate', 'explain', 'monitor', 'dismiss', 'undo'] as const, 'SignalDisposition.action'), previousStatus: enumValue(item.previous_status, ['new', 'triaged', 'investigating', 'explained', 'monitoring', 'dismissed'] as const, 'SignalDisposition.previous_status'), sessionId: asString(item.session_id, 'SignalDisposition.session_id'), cooldownUntil: asNullableString(item.cooldown_until, 'SignalDisposition.cooldown_until'), dismissReason: item.dismiss_reason === null ? null : enumValue(item.dismiss_reason, ['duplicate', 'single_author_spike', 'irrelevant', 'known_issue', 'bad_data', 'other'] as const, 'SignalDisposition.dismiss_reason'), note: asNullableString(item.note, 'SignalDisposition.note'), transitionedAt: asString(item.transitioned_at, 'SignalDisposition.transitioned_at'), undoneAt: asNullableString(item.undone_at, 'SignalDisposition.undone_at') }; })();
  return {
    id: asString(dto.id, 'Signal.id'),
    title: asString(dto.title, 'Signal.title'),
    watchlistId: asString(dto.watchlist_id, 'Signal.watchlist_id'),
    status: enumValue(dto.status, ['new', 'triaged', 'investigating', 'explained', 'monitoring', 'dismissed'] as const, 'Signal.status'),
    authenticity: mapAuthenticity(dto.data_authenticity),
    snapshotAt: asString(dto.updated_at, 'Signal.updated_at'),
    confidence: enumValue(confidence.level, ['high', 'medium', 'low'] as const, 'DetectionConfidence.level'),
    confidenceExplanation: asString(confidence.explanation, 'DetectionConfidence.explanation'),
    triggerRules: asStrings(dto.trigger_rules, 'Signal.trigger_rules'),
    limitations: asStrings(dto.limitations, 'Signal.limitations'),
    totalSourceCount: asNumber(dto.total_source_count, 'Signal.total_source_count'),
    independentSources: asNumber(dto.independent_source_count, 'Signal.independent_source_count'),
    crossSourceConfirmation: dto.cross_source_confirmation,
    currentCount,
    baselineCount,
    mentionCount,
    platformCount,
    growthRatio,
    robustZ,
    perSourceFreshness: asArray(dto.per_source_freshness, 'Signal.per_source_freshness').map((item) => { const entry = asObject(item, 'PerSourceFreshness'); return { sourceConnectionId: asString(entry.source_connection_id, 'PerSourceFreshness.source_connection_id'), state: enumValue(entry.state, ['current', 'stale', 'never'] as const, 'PerSourceFreshness.state'), lastSuccessAt: asNullableString(entry.last_success_at, 'PerSourceFreshness.last_success_at') }; }),
    window: { currentStart: asString(window.current_start, 'SignalWindow.current_start'), currentEnd: asString(window.current_end, 'SignalWindow.current_end'), baselineStart: asString(window.baseline_start, 'SignalWindow.baseline_start'), baselineEnd: asString(window.baseline_end, 'SignalWindow.baseline_end') },
    impact: impact.confirmed_level === null ? null : enumValue(impact.confirmed_level, ['high', 'medium', 'low', 'unknown'] as const, 'ImpactAssessment.confirmed_level'),
    urgency: urgency.confirmed_level === null ? null : enumValue(urgency.confirmed_level, ['now', 'this_week', 'monitor', 'unknown'] as const, 'UrgencyAssessment.confirmed_level'),
    priority: priority.level === null ? null : enumValue(priority.level, ['P0', 'P1', 'P2', 'P3'] as const, 'SignalPriority.level'),
    rowVersion: asNumber(dto.row_version, 'Signal.row_version'),
    impactAssessmentVersion: asNumber(impact.version, 'ImpactAssessment.version'),
    urgencyAssessmentVersion: asNumber(urgency.version, 'UrgencyAssessment.version'),
    disposition,
  };
}

export function mapEvidence(value: unknown): Evidence {
  const dto = asObject(value, 'Evidence');
  const provenance = asObject(dto.provenance, 'Evidence.provenance');
  const latestReview = dto.latest_review === null ? null : asObject(dto.latest_review, 'Evidence.latest_review');
  return {
    id: asString(dto.id, 'Evidence.id'),
    investigationId: asString(dto.investigation_id, 'Evidence.investigation_id'),
    researchRunId: asString(dto.research_run_id, 'Evidence.research_run_id'),
    stance: enumValue(dto.stance, ['supports', 'opposes', 'neutral'] as const, 'Evidence.stance'),
    quote: asString(dto.quote_text, 'Evidence.quote_text'),
    quoteStart: asNumber(dto.quote_start, 'Evidence.quote_start'),
    quoteEnd: asNumber(dto.quote_end, 'Evidence.quote_end'),
    contentVersionId: asString(dto.content_version_id, 'Evidence.content_version_id'),
    status: enumValue(dto.status, ['proposed', 'valid', 'weak', 'rejected'] as const, 'Evidence.status'),
    provenance: { researchRunId: asString(provenance.research_run_id, 'EvidenceProvenance.research_run_id'), extractionMethod: asString(provenance.extraction_method, 'EvidenceProvenance.extraction_method') },
    latestReviewId: latestReview ? asString(latestReview.id, 'EvidenceReviewSummary.id') : null,
    authenticity: mapAuthenticity(dto.data_authenticity),
  };
}

export function mapClaim(value: unknown): Claim {
  const dto = asObject(value, 'Claim');
  const version = asObject(dto.current_version, 'Claim.current_version');
  return {
    id: asString(dto.id, 'Claim.id'),
    investigationId: asString(dto.investigation_id, 'Claim.investigation_id'),
    researchRunId: asString(dto.research_run_id, 'Claim.research_run_id'),
    versionId: asString(version.id, 'ClaimVersion.id'),
    rowVersion: asNumber(dto.row_version, 'Claim.row_version'),
    text: asString(version.text, 'ClaimVersion.text'),
    status: enumValue(version.status, ['proposed', 'needs_review', 'verified', 'rejected', 'superseded'] as const, 'ClaimVersion.status'),
    limitations: asStrings(version.limitations, 'ClaimVersion.limitations'),
    evidenceLinks: asArray(dto.evidence_links, 'Claim.evidence_links').map((item) => { const link = asObject(item, 'ClaimEvidenceLink'); return { id: asString(link.id, 'ClaimEvidenceLink.id'), evidenceId: asString(link.evidence_id, 'ClaimEvidenceLink.evidence_id'), stance: enumValue(link.stance, ['supports', 'opposes', 'neutral'] as const, 'ClaimEvidenceLink.stance'), weight: asNumber(link.weight, 'ClaimEvidenceLink.weight'), rationale: link.rationale === null ? null : asString(link.rationale, 'ClaimEvidenceLink.rationale') }; }),
    authenticity: mapAuthenticity(dto.data_authenticity),
  };
}

export function mapSynthesis(value: unknown): Synthesis {
  const dto = asObject(value, 'InvestigationSynthesis');
  const version = asObject(dto.current_version, 'InvestigationSynthesis.current_version');
  return {
    id: asString(dto.id, 'InvestigationSynthesis.id'),
    versionId: asString(version.id, 'InvestigationSynthesisVersion.id'),
    rowVersion: asNumber(dto.row_version, 'InvestigationSynthesis.row_version'),
    status: enumValue(version.status, ['draft', 'needs_review', 'verified', 'rejected', 'superseded'] as const, 'InvestigationSynthesisVersion.status'),
    executiveSummary: asString(version.executive_summary, 'InvestigationSynthesisVersion.executive_summary'),
    businessImplications: asStrings(version.business_implications, 'InvestigationSynthesisVersion.business_implications'),
    limitations: asStrings(version.limitations, 'InvestigationSynthesisVersion.limitations'),
    verifiedClaimVersionIds: asStrings(version.verified_claim_version_snapshot_json, 'InvestigationSynthesisVersion.verified_claim_version_snapshot_json'),
    generationMethod: enumValue(version.generation_method, ['deterministic', 'model'] as const, 'InvestigationSynthesisVersion.generation_method'),
    generatorVersion: asString(version.generator_version, 'InvestigationSynthesisVersion.generator_version'),
    modelPromptRefs: asStrings(version.model_prompt_refs_json, 'InvestigationSynthesisVersion.model_prompt_refs_json'),
    authenticity: mapAuthenticity(dto.data_authenticity),
  };
}

export function mapRun(value: unknown): Investigation['run'] {
  const dto = asObject(value, 'ResearchRun');
  const graphVersion = asString(dto.graph_version, 'ResearchRun.graph_version');
  const budget = asObject(dto.budget, 'ResearchRun.budget');
  const generationMethod = enumValue(dto.generation_method, ['deterministic', 'model'] as const, 'ResearchRun.generation_method');
  return {
    id: asString(dto.id, 'ResearchRun.id'),
    state: enumValue(dto.state, ['queued', 'running', 'waiting_for_input', 'completed', 'failed', 'cancelled'] as const, 'ResearchRun.state') as RunState,
    rowVersion: asNumber(dto.row_version, 'ResearchRun.row_version'),
    latestSequence: asNumber(dto.latest_sequence, 'ResearchRun.latest_sequence'),
    attemptNumber: asNumber(dto.attempt_number, 'ResearchRun.attempt_number'),
    graphVersion,
    generationMethod,
    provider: asString(dto.provider, 'ResearchRun.provider'),
    model: dto.model === undefined || dto.model === null ? null : asString(dto.model, 'ResearchRun.model'),
    promptRefs: asStrings(dto.prompt_refs, 'ResearchRun.prompt_refs'),
    traceRef: dto.trace_ref === undefined || dto.trace_ref === null ? null : asString(dto.trace_ref, 'ResearchRun.trace_ref'),
    usedCostUsd: asString(dto.used_cost_usd, 'ResearchRun.used_cost_usd'),
    budget: {
      maxCostUsd: asString(budget.max_cost_usd, 'ResearchBudget.max_cost_usd'),
      maxDurationSeconds: asNumber(budget.max_duration_seconds, 'ResearchBudget.max_duration_seconds'),
    },
    waitingForInputReason: dto.waiting_for_input_reason === undefined || dto.waiting_for_input_reason === null ? null : asString(dto.waiting_for_input_reason, 'ResearchRun.waiting_for_input_reason'),
  };
}

export function mapInvestigation(value: unknown): Investigation {
  const dto = asObject(value, 'Investigation');
  return {
    id: asString(dto.id, 'Investigation.id'),
    signalId: asString(dto.signal_id, 'Investigation.signal_id'),
    question: asString(dto.decision_question, 'Investigation.decision_question'),
    status: enumValue(dto.status, ['draft', 'active', 'needs_input', 'reviewing', 'completed', 'closed_insufficient', 'cancelled'] as const, 'Investigation.status'),
    scopeVersionId: asString(dto.current_scope_version_id, 'Investigation.current_scope_version_id'),
    sourceConnectionIds: [],
    contentVersionIds: [],
    allowCloudModel: false,
    timeRange: null,
    run: null,
    evidence: [],
    claims: [],
    synthesis: null,
    events: [],
    rowVersion: asNumber(dto.row_version, 'Investigation.row_version'),
    authenticity: mapAuthenticity(dto.data_authenticity),
  };
}

function mapBlock(value: unknown): BriefBlock {
  const block = asObject(value, 'DecisionBriefBlock');
  const id = asString(block.id, 'DecisionBriefBlock.id');
  const body = asString(block.body, 'DecisionBriefBlock.body');
  if (block.type === 'fact') return { id, type: 'fact', body, claimVersionIds: asStrings(block.claim_version_ids, 'FactBlock.claim_version_ids'), evidenceIds: asStrings(block.evidence_ids, 'FactBlock.evidence_ids'), contentVersionIds: asStrings(block.content_version_ids, 'FactBlock.content_version_ids') };
  if (block.type === 'synthesis') return { id, type: 'synthesis', body, synthesisVersionId: asString(block.synthesis_version_id, 'SynthesisBlock.synthesis_version_id'), generationMethod: enumValue(block.generation_method, ['deterministic', 'model'] as const, 'SynthesisBlock.generation_method'), generatorVersion: asString(block.generator_version, 'SynthesisBlock.generator_version'), modelPromptRefs: asStrings(block.model_prompt_refs, 'SynthesisBlock.model_prompt_refs') };
  if (block.type === 'pm_judgment') return { id, type: 'pm_judgment', body, actorId: asString(block.actor_id, 'PMJudgmentBlock.actor_id') };
  if (block.type === 'recommendation') return { id, type: 'recommendation', body, recommendationStatus: enumValue(block.recommendation_status, ['proposed', 'accepted', 'rejected'] as const, 'RecommendationBlock.recommendation_status') };
  throw new Error('Invalid DecisionBriefBlock.type DTO.');
}

function mapReference(value: unknown): BriefReferenceSnapshot {
  const dto = asObject(value, 'DecisionBriefReferenceSnapshot');
  return { synthesisVersionId: asString(dto.synthesis_version_id, 'DecisionBriefReferenceSnapshot.synthesis_version_id'), synthesisReviewId: asString(dto.synthesis_review_id, 'DecisionBriefReferenceSnapshot.synthesis_review_id'), claimVersionIds: asStrings(dto.claim_version_ids, 'DecisionBriefReferenceSnapshot.claim_version_ids'), claimReviewIds: asStrings(dto.claim_review_ids, 'DecisionBriefReferenceSnapshot.claim_review_ids'), claimEvidenceIds: asStrings(dto.claim_evidence_ids, 'DecisionBriefReferenceSnapshot.claim_evidence_ids'), evidenceReviewIds: asStrings(dto.evidence_review_ids, 'DecisionBriefReferenceSnapshot.evidence_review_ids'), evidenceIds: asStrings(dto.evidence_ids, 'DecisionBriefReferenceSnapshot.evidence_ids'), contentVersionIds: asStrings(dto.content_version_ids, 'DecisionBriefReferenceSnapshot.content_version_ids') };
}

export function mapBrief(value: unknown, question = 'Decision brief'): DecisionBrief {
  const dto = asObject(value, 'DecisionBrief');
  const version = asObject(dto.current_version, 'DecisionBrief.current_version');
  const document = asObject(version.block_document, 'DecisionBriefVersion.block_document');
  return {
    id: asString(dto.id, 'DecisionBrief.id'),
    investigationId: asString(dto.investigation_id, 'DecisionBrief.investigation_id'),
    question,
    version: asNumber(version.version_number, 'DecisionBriefVersion.version_number'),
    versionId: asString(version.id, 'DecisionBriefVersion.id'),
    rowVersion: asNumber(dto.row_version, 'DecisionBrief.row_version'),
    status: enumValue(dto.status, ['draft', 'decision_ready', 'decided', 'archived'] as const, 'DecisionBrief.status'),
    authenticity: mapAuthenticity(dto.data_authenticity),
    freshness: enumValue(version.freshness, ['current', 'evidence_stale'] as const, 'DecisionBriefVersion.freshness'),
    readiness: enumValue(version.readiness, ['draft', 'decision_ready'] as const, 'DecisionBriefVersion.readiness'),
    blockDocument: { schemaVersion: asString(document.schema_version, 'DecisionBriefBlockDocument.schema_version'), blocks: asArray(document.blocks, 'DecisionBriefBlockDocument.blocks').map(mapBlock), noCounterEvidenceSearch: document.no_counter_evidence_search === null ? null : (() => { const search = asObject(document.no_counter_evidence_search, 'NoCounterEvidenceSearchRecord'); return { queries: asStrings(search.queries, 'NoCounterEvidenceSearchRecord.queries'), sourceConnectionIds: asStrings(search.source_connection_ids, 'NoCounterEvidenceSearchRecord.source_connection_ids'), windowStart: asString(search.window_start, 'NoCounterEvidenceSearchRecord.window_start'), windowEnd: asString(search.window_end, 'NoCounterEvidenceSearchRecord.window_end'), exclusionCriteria: asStrings(search.exclusion_criteria, 'NoCounterEvidenceSearchRecord.exclusion_criteria'), limitations: asStrings(search.limitations, 'NoCounterEvidenceSearchRecord.limitations') }; })() },
    referenceSnapshot: mapReference(version.reference_snapshot_json),
    templateVersion: asString(version.template_version, 'DecisionBriefVersion.template_version'),
    humanEditDigest: asString(version.human_edit_digest, 'DecisionBriefVersion.human_edit_digest'),
  };
}

export function mapNavigation(value: unknown): NavigationSummary {
  const dto = asObject(value, 'NavigationSummary');
  return { unreviewedSignalCount: asNumber(dto.unreviewed_signal_count, 'NavigationSummary.unreviewed_signal_count'), investigationNeedsInputCount: asNumber(dto.investigation_needs_input_count, 'NavigationSummary.investigation_needs_input_count'), draftDecisionBriefCount: asNumber(dto.draft_decision_brief_count, 'NavigationSummary.draft_decision_brief_count'), monitoringHealth: enumValue(dto.monitoring_health, ['healthy', 'degraded'] as const, 'NavigationSummary.monitoring_health'), computedAt: asString(dto.computed_at, 'NavigationSummary.computed_at') };
}

export function mapBootstrap(value: unknown, navigation: NavigationSummary, schedules: CollectionSchedule[] = []): Omit<WorkspaceState, 'principalId' | 'cachedAt'> {
  const dto = asObject(value, 'SyncBootstrap');
  const workspace = asObject(dto.workspace, 'SyncBootstrap.workspace');
  const investigations = asArray(dto.investigations, 'SyncBootstrap.investigations').map(mapInvestigation);
  const questionByInvestigation = new Map(investigations.map((item) => [item.id, item.question]));
  return {
    workspaceId: asString(dto.workspace_id, 'SyncBootstrap.workspace_id'),
    workspaceName: asString(workspace.name, 'Workspace.name'),
    authenticity: mapAuthenticity(dto.data_authenticity),
    signals: asArray(dto.signals, 'SyncBootstrap.signals').map(mapSignal),
    investigations,
    briefs: asArray(dto.decision_briefs, 'SyncBootstrap.decision_briefs').map((item) => { const raw = asObject(item, 'DecisionBrief'); const investigationId = asString(raw.investigation_id, 'DecisionBrief.investigation_id'); return mapBrief(item, questionByInvestigation.get(investigationId) ?? 'Decision brief'); }),
    sources: asArray(dto.sources, 'SyncBootstrap.sources').map(mapSource),
    watchlists: asArray(dto.watchlists, 'SyncBootstrap.watchlists').map(mapWatchlist),
    schedules,
    navigation,
  };
}

export function toWireBlock(block: BriefBlock): JsonObject {
  if (block.type === 'fact') return { id: block.id, type: block.type, body: block.body, claim_version_ids: block.claimVersionIds, evidence_ids: block.evidenceIds, content_version_ids: block.contentVersionIds };
  if (block.type === 'synthesis') return { id: block.id, type: block.type, body: block.body, synthesis_version_id: block.synthesisVersionId, generation_method: block.generationMethod, generator_version: block.generatorVersion, model_prompt_refs: block.modelPromptRefs };
  if (block.type === 'pm_judgment') return { id: block.id, type: block.type, body: block.body, actor_id: block.actorId };
  return { id: block.id, type: block.type, body: block.body, recommendation_status: block.recommendationStatus };
}

export const toWireDocument = (brief: DecisionBrief): JsonObject => ({ schema_version: brief.blockDocument.schemaVersion, blocks: brief.blockDocument.blocks.map(toWireBlock), no_counter_evidence_search: brief.blockDocument.noCounterEvidenceSearch ? { queries: brief.blockDocument.noCounterEvidenceSearch.queries, source_connection_ids: brief.blockDocument.noCounterEvidenceSearch.sourceConnectionIds, window_start: brief.blockDocument.noCounterEvidenceSearch.windowStart, window_end: brief.blockDocument.noCounterEvidenceSearch.windowEnd, exclusion_criteria: brief.blockDocument.noCounterEvidenceSearch.exclusionCriteria, limitations: brief.blockDocument.noCounterEvidenceSearch.limitations } : null });

export const toWireReference = (brief: DecisionBrief): JsonObject => ({ synthesis_version_id: brief.referenceSnapshot.synthesisVersionId, synthesis_review_id: brief.referenceSnapshot.synthesisReviewId, claim_version_ids: brief.referenceSnapshot.claimVersionIds, claim_review_ids: brief.referenceSnapshot.claimReviewIds, claim_evidence_ids: brief.referenceSnapshot.claimEvidenceIds, evidence_review_ids: brief.referenceSnapshot.evidenceReviewIds, evidence_ids: brief.referenceSnapshot.evidenceIds, content_version_ids: brief.referenceSnapshot.contentVersionIds });
