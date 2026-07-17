import type {
  Authenticity,
  DecisionBrief,
  Evidence,
  Investigation,
  ResearchGenerationMethod,
  RunEvent,
  RunState,
  SourceHealth,
} from '../../domain';

export type AgentStatus = 'ready' | 'preparing' | 'running' | 'waiting-review' | 'needs-input' | 'completed' | 'failed' | 'cancelled';
export type AgentStepStatus = 'pending' | 'running' | 'completed' | 'waiting' | 'failed' | 'skipped';
export type AgentStepOwner = 'agent' | 'human' | 'system';
export type AgentArtifactType = 'source-scope' | 'evidence-proposal' | 'finding-proposal' | 'synthesis-draft' | 'decision-brief' | 'run-failure' | 'human-review';
export type AgentActionKind = 'start-run' | 'review-evidence' | 'review-findings' | 'create-synthesis' | 'review-synthesis' | 'create-brief' | 'open-brief' | 'retry' | 'cancel';

export interface AgentScopeSummary {
  sourceCount: number;
  contentVersionCount: number;
  sourceLabel: string;
  contentVersionLabel: string;
  timeRange: Investigation['timeRange'];
  sourceNames: string[];
}

export interface AgentPlanStepPresentation {
  id: string;
  owner: AgentStepOwner;
  title: string;
  description: string;
  status: AgentStepStatus;
  artifactCount: number;
  timestamp: string | null;
  needsAction: boolean;
  internalNode: string | null;
}

export interface AgentActivityPresentation {
  id: string;
  title: string;
  summary: string;
  timestamp: string | null;
  artifactCount: number;
  eventType: string | null;
  sequence: number | null;
  authenticity: Authenticity;
}

export interface AgentArtifactPresentation {
  id: string;
  type: AgentArtifactType;
  typeLabel: string;
  statusLabel: string;
  originLabel: string;
  title: string;
  body: string;
  relationshipLabel: string | null;
  authenticity: Authenticity;
  primaryAction: AgentActionKind | null;
}

export interface PendingHumanAction {
  kind: AgentActionKind;
  title: string;
  body: string;
  actionLabel: string;
  count: number | null;
}

export interface AgentCurrentAction {
  title: string;
  purpose: string;
  inputLabel: string;
  outputLabel: string;
  userNeedLabel: string;
}

export interface AgentSessionPresentation {
  status: AgentStatus;
  statusLabel: string;
  statusTone: 'neutral' | 'info' | 'warning' | 'positive' | 'danger';
  goal: string;
  mode: 'deterministic' | 'model-assisted';
  modeLabel: string;
  authenticity: Authenticity;
  fixtureLabel: string | null;
  scopeSummary: AgentScopeSummary;
  budgetLimitLabel: string | null;
  modelEgress: {
    approved: boolean;
    provider: string | null;
    model: string | null;
    willSend: string;
    willNotSend: string;
  };
  planSteps: AgentPlanStepPresentation[];
  completedStepCount: number;
  currentAction: AgentCurrentAction;
  pendingHumanAction: PendingHumanAction | null;
  activity: AgentActivityPresentation[];
  artifacts: AgentArtifactPresentation[];
  currentStepId: string;
  canCancel: boolean;
  canStart: boolean;
  canRetry: boolean;
  canCreateBrief: boolean;
  canOpenBrief: boolean;
  advanced: {
    runId: string | null;
    scopeVersionId: string;
    graphVersion: string | null;
    latestSequence: number | null;
    traceRef: string | null;
    promptRefs: string[];
    currentInternalNode: string | null;
  };
}

export interface AgentPresentationOptions {
  sources?: SourceHealth[];
  brief?: DecisionBrief | null;
  fixture?: boolean;
}

const PRODUCT_STEP_COPY = {
  scope: ['Confirming approved scope', 'Checks the frozen question, source boundary, content versions, window, and configured limits.'],
  sources: ['Preparing approved sources', 'Makes only approved immutable content available to this run.'],
  evidence: ['Analyzing evidence', 'Proposes relevant passages from the approved source set.'],
  citations: ['Verifying citations', 'Checks proposal references against immutable content versions.'],
  findings: ['Drafting findings', 'Proposes findings supported by the current evidence set.'],
} as const;

const EVENT_COPY: Record<string, { title: string; summary: string }> = {
  'run.queued': { title: 'Scope confirmed', summary: 'The immutable run input was accepted.' },
  'run.started': { title: 'Sources prepared', summary: 'Approved sources were bounded for this run.' },
  'evidence.proposed': { title: 'Evidence proposed', summary: 'Candidate evidence was persisted for review.' },
  'evidence.validated': { title: 'Citation validation completed', summary: 'Evidence references were checked against immutable content.' },
  'claim.version_proposed': { title: 'Findings proposed', summary: 'Findings were persisted for human review.' },
  'run.completed': { title: 'Agent paused for review', summary: 'The run completed its proposal work. Human review remains required.' },
  'run.failed': { title: 'Agent stopped safely', summary: 'The run ended without bypassing review or persistence rules.' },
  'run.cancelled': { title: 'Run cancelled', summary: 'The run stopped at the user’s request. Persisted artifacts remain visible.' },
};

function plural(count: number, singular: string, pluralLabel = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralLabel}`;
}

function durationLabel(seconds: number): string {
  if (seconds > 0 && seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds}s`;
}

function budgetLimitLabel(investigation: Investigation): string | null {
  const budget = investigation.run?.budget;
  if (!budget) return null;
  return `Budget limit: $${budget.maxCostUsd} · ${durationLabel(budget.maxDurationSeconds)}`;
}

function statusFor(investigation: Investigation, brief: DecisionBrief | null): AgentStatus {
  const run = investigation.run;
  if (!run) return 'ready';
  if (run.state === 'queued') return 'preparing';
  if (run.state === 'running') return 'running';
  if (run.state === 'waiting_for_input') return 'needs-input';
  if (run.state === 'failed') return 'failed';
  if (run.state === 'cancelled') return 'cancelled';
  if (pendingReviewAction(investigation, brief)) return 'waiting-review';
  return 'completed';
}

function statusPresentation(status: AgentStatus): Pick<AgentSessionPresentation, 'statusLabel' | 'statusTone'> {
  if (status === 'ready') return { statusLabel: 'Ready to start', statusTone: 'neutral' };
  if (status === 'preparing') return { statusLabel: 'Preparing', statusTone: 'info' };
  if (status === 'running') return { statusLabel: 'Running', statusTone: 'info' };
  if (status === 'waiting-review') return { statusLabel: 'Waiting for review', statusTone: 'warning' };
  if (status === 'needs-input') return { statusLabel: 'Needs input', statusTone: 'warning' };
  if (status === 'completed') return { statusLabel: 'Completed', statusTone: 'positive' };
  if (status === 'failed') return { statusLabel: 'Failed', statusTone: 'danger' };
  return { statusLabel: 'Cancelled', statusTone: 'neutral' };
}

function modePresentation(method: ResearchGenerationMethod | null, allowCloudModel: boolean): Pick<AgentSessionPresentation, 'mode' | 'modeLabel'> {
  const model = method === 'model' || (!method && allowCloudModel);
  return model
    ? { mode: 'model-assisted', modeLabel: 'Model-assisted research' }
    : { mode: 'deterministic', modeLabel: 'Deterministic research' };
}

function latestEventTime(events: RunEvent[], types: string[]): string | null {
  return [...events].reverse().find((event) => types.includes(event.type))?.timestamp ?? null;
}

function evidenceReviewed(evidence: Evidence[]): boolean {
  return evidence.length > 0 && evidence.every((item) => item.status !== 'proposed');
}

function pendingReviewAction(investigation: Investigation, brief: DecisionBrief | null): PendingHumanAction | null {
  const proposedEvidence = investigation.evidence.filter((item) => item.status === 'proposed');
  if (proposedEvidence.length > 0) return {
    kind: 'review-evidence',
    title: `${plural(proposedEvidence.length, 'evidence proposal')} need${proposedEvidence.length === 1 ? 's' : ''} your review`,
    body: 'Open the immutable source before recording Valid, Weak, or Reject.',
    actionLabel: 'Review evidence',
    count: proposedEvidence.length,
  };

  const proposedFindings = investigation.claims.filter((item) => item.status === 'proposed' || item.status === 'needs_review');
  if (proposedFindings.length > 0 && evidenceReviewed(investigation.evidence)) return {
    kind: 'review-findings',
    title: `${plural(proposedFindings.length, 'finding')} ${proposedFindings.length === 1 ? 'is' : 'are'} based on reviewed evidence`,
    body: 'Verification means sufficient support for this Investigation, not a universal truth guarantee.',
    actionLabel: 'Review findings',
    count: proposedFindings.length,
  };

  const hasVerifiedFinding = investigation.claims.some((item) => item.status === 'verified');
  if (hasVerifiedFinding && !investigation.synthesis) return {
    kind: 'create-synthesis',
    title: 'Verified findings are ready for synthesis',
    body: 'Create a reviewable draft from the exact verified finding versions.',
    actionLabel: 'Create synthesis',
    count: investigation.claims.filter((item) => item.status === 'verified').length,
  };

  if (investigation.synthesis?.status === 'draft' || investigation.synthesis?.status === 'needs_review') return {
    kind: 'review-synthesis',
    title: 'The Agent drafted a synthesis from verified findings',
    body: 'Review and verify the current version before a Decision Brief can be created.',
    actionLabel: 'Review synthesis',
    count: 1,
  };

  if (investigation.synthesis?.status === 'verified' && !brief) return {
    kind: 'create-brief',
    title: 'Verified synthesis is ready for a Decision Brief',
    body: 'Create the governed decision artifact from this exact synthesis version.',
    actionLabel: 'Create Decision Brief',
    count: 1,
  };

  if (brief) return null;
  return null;
}

function stepStatus(
  id: string,
  investigation: Investigation,
  status: AgentStatus,
  pending: PendingHumanAction | null,
  brief: DecisionBrief | null,
): AgentStepStatus {
  const run = investigation.run;
  const failed = status === 'failed';
  const completedRun = run?.state === 'completed';
  const evidenceExists = investigation.evidence.length > 0;
  const findingsExist = investigation.claims.length > 0;
  const allEvidenceReviewed = evidenceReviewed(investigation.evidence);
  const allFindingsReviewed = findingsExist && investigation.claims.every((item) => !['proposed', 'needs_review'].includes(item.status));
  if (id === 'scope') return failed && !run ? 'failed' : run ? 'completed' : status === 'ready' ? 'completed' : 'pending';
  if (id === 'sources') {
    if (failed && !evidenceExists) return 'failed';
    if (run && (run.state !== 'queued' || investigation.events.some((event) => event.type === 'run.started'))) return 'completed';
    return run?.state === 'queued' ? 'running' : 'pending';
  }
  if (id === 'evidence') {
    if (evidenceExists || completedRun) return 'completed';
    if (failed) return 'failed';
    return run?.state === 'running' ? 'running' : 'pending';
  }
  if (id === 'citations') {
    if (evidenceExists && completedRun) return 'completed';
    if (failed && evidenceExists) return 'failed';
    return evidenceExists && run?.state === 'running' ? 'running' : 'pending';
  }
  if (id === 'findings') {
    if (findingsExist) return 'completed';
    if (failed && (evidenceExists || completedRun)) return 'failed';
    return evidenceExists && run?.state === 'running' ? 'running' : 'pending';
  }
  if (id === 'review-evidence') {
    if (pending?.kind === 'review-evidence') return 'waiting';
    if (allEvidenceReviewed) return 'completed';
    return 'pending';
  }
  if (id === 'review-findings') {
    if (pending?.kind === 'review-findings') return 'waiting';
    if (allFindingsReviewed) return 'completed';
    return 'pending';
  }
  if (id === 'review-synthesis') {
    if (pending?.kind === 'create-synthesis' || pending?.kind === 'review-synthesis') return 'waiting';
    if (investigation.synthesis?.status === 'verified') return 'completed';
    if (investigation.synthesis?.status === 'rejected') return 'completed';
    return 'pending';
  }
  if (id === 'decision-brief') {
    if (pending?.kind === 'create-brief') return 'waiting';
    if (brief) return 'completed';
    return 'pending';
  }
  return 'pending';
}

function planSteps(investigation: Investigation, status: AgentStatus, pending: PendingHumanAction | null, brief: DecisionBrief | null): AgentPlanStepPresentation[] {
  const items: Array<Omit<AgentPlanStepPresentation, 'status' | 'timestamp'>> = [
    { id: 'scope', owner: 'system', title: PRODUCT_STEP_COPY.scope[0], description: PRODUCT_STEP_COPY.scope[1], artifactCount: 1, needsAction: false, internalNode: 'validate_manifest' },
    { id: 'sources', owner: 'agent', title: PRODUCT_STEP_COPY.sources[0], description: PRODUCT_STEP_COPY.sources[1], artifactCount: investigation.contentVersionIds.length, needsAction: false, internalNode: 'bound_content' },
    { id: 'evidence', owner: 'agent', title: PRODUCT_STEP_COPY.evidence[0], description: PRODUCT_STEP_COPY.evidence[1], artifactCount: investigation.evidence.length, needsAction: false, internalNode: 'propose_evidence' },
    { id: 'citations', owner: 'system', title: PRODUCT_STEP_COPY.citations[0], description: PRODUCT_STEP_COPY.citations[1], artifactCount: investigation.evidence.length, needsAction: false, internalNode: 'validate_evidence' },
    { id: 'findings', owner: 'agent', title: PRODUCT_STEP_COPY.findings[0], description: PRODUCT_STEP_COPY.findings[1], artifactCount: investigation.claims.length, needsAction: false, internalNode: 'propose_claim' },
    { id: 'review-evidence', owner: 'human', title: 'Review evidence', description: 'An authorized human reviews each proposal against its immutable source.', artifactCount: investigation.evidence.length, needsAction: pending?.kind === 'review-evidence', internalNode: 'require_human_review' },
    { id: 'review-findings', owner: 'human', title: 'Review findings', description: 'An authorized human verifies whether reviewed evidence sufficiently supports each finding.', artifactCount: investigation.claims.length, needsAction: pending?.kind === 'review-findings', internalNode: null },
    { id: 'review-synthesis', owner: 'human', title: 'Review synthesis', description: 'An authorized human reviews the synthesis built from verified findings.', artifactCount: investigation.synthesis ? 1 : 0, needsAction: pending?.kind === 'create-synthesis' || pending?.kind === 'review-synthesis', internalNode: null },
    { id: 'decision-brief', owner: 'human', title: 'Approve decision brief', description: 'A verified synthesis can be handed into a governed Decision Brief.', artifactCount: brief ? 1 : 0, needsAction: pending?.kind === 'create-brief', internalNode: null },
  ];
  const timestampTypes: Record<string, string[]> = {
    scope: ['run.queued'],
    sources: ['run.started'],
    evidence: ['evidence.proposed'],
    citations: ['evidence.validated', 'run.completed'],
    findings: ['claim.version_proposed'],
    'review-evidence': [],
    'review-findings': [],
    'review-synthesis': [],
    'decision-brief': [],
  };
  return items.map((item) => ({
    ...item,
    status: stepStatus(item.id, investigation, status, pending, brief),
    timestamp: latestEventTime(investigation.events, timestampTypes[item.id] ?? []),
  }));
}

function activityFor(investigation: Investigation): AgentActivityPresentation[] {
  const projected = investigation.events.map((event) => {
    const copy = EVENT_COPY[event.type] ?? { title: 'Run activity recorded', summary: 'A safe run event was recorded.' };
    return {
      id: event.id,
      title: copy.title,
      summary: event.message.trim() || copy.summary,
      timestamp: event.timestamp,
      artifactCount: event.type === 'evidence.proposed' ? investigation.evidence.length : event.type === 'claim.version_proposed' ? investigation.claims.length : 0,
      eventType: event.type,
      sequence: event.sequence,
      authenticity: event.authenticity,
    };
  });
  if (projected.length > 0) return projected;
  return [{
    id: `scope-${investigation.scopeVersionId}`,
    title: 'Approved scope ready',
    summary: 'The Decision Question and approved source boundary are frozen for this Investigation.',
    timestamp: null,
    artifactCount: 1,
    eventType: null,
    sequence: null,
    authenticity: investigation.authenticity,
  }];
}

function evidenceStatusLabel(evidence: Evidence): string {
  if (evidence.status === 'proposed') return 'Needs review';
  if (evidence.status === 'valid') return 'Verified evidence';
  if (evidence.status === 'weak') return 'Reviewed · Weak';
  return 'Reviewed · Rejected';
}

function artifactsFor(investigation: Investigation, brief: DecisionBrief | null, sourceNames: string[]): AgentArtifactPresentation[] {
  const runMethod = investigation.run?.generationMethod ?? (investigation.allowCloudModel ? 'model' : 'deterministic');
  const proposalOrigin = runMethod === 'model' ? 'Model proposal' : 'Deterministic proposal';
  const scope: AgentArtifactPresentation = {
    id: `scope-${investigation.scopeVersionId}`,
    type: 'source-scope',
    typeLabel: 'Source Scope',
    statusLabel: 'Approved scope',
    originLabel: 'Workspace policy',
    title: plural(investigation.sourceConnectionIds.length, 'approved source'),
    body: sourceNames.length > 0 ? sourceNames.join(' · ') : `${plural(investigation.contentVersionIds.length, 'immutable content version')} pinned`,
    relationshipLabel: plural(investigation.contentVersionIds.length, 'content version'),
    authenticity: investigation.authenticity,
    primaryAction: null,
  };
  const evidence = investigation.evidence.map<AgentArtifactPresentation>((item) => ({
    id: item.id,
    type: 'evidence-proposal',
    typeLabel: 'Evidence Proposal',
    statusLabel: evidenceStatusLabel(item),
    originLabel: proposalOrigin,
    title: item.stance === 'supports' ? 'Supporting evidence' : item.stance === 'opposes' ? 'Opposing evidence' : 'Neutral evidence',
    body: item.quote,
    relationshipLabel: '1 immutable source',
    authenticity: item.authenticity,
    primaryAction: item.status === 'proposed' ? 'review-evidence' : null,
  }));
  const findings = investigation.claims.map<AgentArtifactPresentation>((item) => ({
    id: item.id,
    type: 'finding-proposal',
    typeLabel: 'Finding Proposal',
    statusLabel: item.status === 'verified' ? 'Human-reviewed finding' : item.status === 'rejected' ? 'Reviewed · Rejected' : 'Needs review',
    originLabel: proposalOrigin,
    title: 'Finding',
    body: item.text,
    relationshipLabel: plural(item.evidenceLinks.length, 'evidence reference'),
    authenticity: item.authenticity,
    primaryAction: item.status === 'proposed' || item.status === 'needs_review' ? 'review-findings' : null,
  }));
  const synthesis = investigation.synthesis ? [{
    id: investigation.synthesis.id,
    type: 'synthesis-draft' as const,
    typeLabel: 'Synthesis Draft',
    statusLabel: investigation.synthesis.status === 'verified' ? 'Verified' : investigation.synthesis.status === 'rejected' ? 'Rejected' : 'Needs review',
    originLabel: investigation.synthesis.generationMethod === 'model' ? 'Model proposal' : 'Deterministic proposal',
    title: 'Investigation synthesis',
    body: investigation.synthesis.executiveSummary,
    relationshipLabel: plural(investigation.synthesis.verifiedClaimVersionIds.length, 'verified finding'),
    authenticity: investigation.synthesis.authenticity,
    primaryAction: investigation.synthesis.status === 'draft' || investigation.synthesis.status === 'needs_review' ? 'review-synthesis' as const : null,
  }] : [];
  const briefs = brief ? [{
    id: brief.id,
    type: 'decision-brief' as const,
    typeLabel: 'Decision Brief',
    statusLabel: brief.status === 'decision_ready' ? 'Decision ready' : 'Draft',
    originLabel: 'Decision artifact',
    title: brief.question,
    body: `Version ${brief.version} · ${brief.freshness === 'current' ? 'Current evidence' : 'Evidence changed'}`,
    relationshipLabel: plural(brief.referenceSnapshot.claimVersionIds.length, 'finding reference'),
    authenticity: brief.authenticity,
    primaryAction: 'open-brief' as const,
  }] : [];
  return [scope, ...evidence, ...findings, ...synthesis, ...briefs];
}

function currentActionFor(
  investigation: Investigation,
  status: AgentStatus,
  currentStep: AgentPlanStepPresentation,
  pending: PendingHumanAction | null,
): AgentCurrentAction {
  if (status === 'failed') return {
    title: 'The Agent stopped safely',
    purpose: investigation.events.at(-1)?.message || 'The run ended without bypassing review or persistence rules.',
    inputLabel: plural(investigation.contentVersionIds.length, 'immutable content version'),
    outputLabel: `${plural(investigation.evidence.length, 'evidence proposal')} · ${plural(investigation.claims.length, 'finding')}`,
    userNeedLabel: 'Review retained work and diagnostics before retrying.',
  };
  if (status === 'needs-input') return {
    title: 'Glint is waiting for an authorized action',
    purpose: investigation.run?.waitingForInputReason || 'The run paused safely at a human gate.',
    inputLabel: plural(investigation.contentVersionIds.length, 'immutable content version'),
    outputLabel: `${plural(investigation.evidence.length, 'evidence proposal')} retained`,
    userNeedLabel: 'This version cannot accept a free-text continuation. You may cancel the run.',
  };
  if (pending) return {
    title: pending.title,
    purpose: pending.body,
    inputLabel: plural(investigation.contentVersionIds.length, 'immutable content version'),
    outputLabel: `${plural(investigation.evidence.length, 'evidence proposal')} · ${plural(investigation.claims.length, 'finding')}`,
    userNeedLabel: 'Your review is required before the workflow can continue.',
  };
  if (status === 'completed') return {
    title: 'This Investigation is complete',
    purpose: 'The governed research and review path is complete for the current scope.',
    inputLabel: plural(investigation.contentVersionIds.length, 'immutable content version'),
    outputLabel: investigation.synthesis ? 'Verified synthesis available' : `${plural(investigation.claims.length, 'reviewed finding')}`,
    userNeedLabel: 'Open the Decision Brief to continue the decision workflow.',
  };
  return {
    title: status === 'ready' ? 'Approved scope is ready' : `Glint is ${currentStep.title.toLocaleLowerCase()}`,
    purpose: currentStep.description,
    inputLabel: plural(investigation.contentVersionIds.length, 'immutable content version'),
    outputLabel: `${plural(investigation.evidence.length, 'evidence proposal')} · ${plural(investigation.claims.length, 'finding')}`,
    userNeedLabel: status === 'ready' ? 'Review the plan before starting.' : 'No action is needed from you right now.',
  };
}

function currentStepFor(steps: AgentPlanStepPresentation[]): AgentPlanStepPresentation {
  const current = steps.find((step) => step.status === 'failed')
    ?? steps.find((step) => step.status === 'waiting')
    ?? steps.find((step) => step.status === 'running')
    ?? [...steps].reverse().find((step) => step.status === 'completed')
    ?? steps[0];
  if (!current) throw new Error('Agent presentation requires at least one plan step.');
  return current;
}

export function presentAgentSession(investigation: Investigation, options: AgentPresentationOptions = {}): AgentSessionPresentation {
  const brief = options.brief ?? null;
  const sourceById = new Map((options.sources ?? []).map((source) => [source.id, source]));
  const sourceNames = investigation.sourceConnectionIds.map((id) => sourceById.get(id)?.name).filter((name): name is string => Boolean(name));
  const status = statusFor(investigation, brief);
  const pending = investigation.run?.state === 'completed' ? pendingReviewAction(investigation, brief) : null;
  const steps = planSteps(investigation, status, pending, brief);
  const currentStep = currentStepFor(steps);
  const method = investigation.run?.generationMethod ?? null;
  const mode = modePresentation(method, investigation.allowCloudModel);
  return {
    status,
    ...statusPresentation(status),
    goal: investigation.question,
    ...mode,
    authenticity: investigation.authenticity,
    fixtureLabel: options.fixture ? 'Imported Demo Fixture' : null,
    scopeSummary: {
      sourceCount: investigation.sourceConnectionIds.length,
      contentVersionCount: investigation.contentVersionIds.length,
      sourceLabel: plural(investigation.sourceConnectionIds.length, 'approved source'),
      contentVersionLabel: plural(investigation.contentVersionIds.length, 'immutable content version'),
      timeRange: investigation.timeRange,
      sourceNames,
    },
    budgetLimitLabel: budgetLimitLabel(investigation),
    modelEgress: {
      approved: mode.mode === 'model-assisted' && investigation.allowCloudModel,
      provider: investigation.run?.provider || null,
      model: investigation.run?.model ?? null,
      willSend: 'The Decision Question and selected excerpts from the approved scope.',
      willNotSend: 'Workspace credentials, approval state, unrelated workspace content, and local file paths.',
    },
    planSteps: steps,
    completedStepCount: steps.filter((step) => step.status === 'completed').length,
    currentAction: currentActionFor(investigation, status, currentStep, pending),
    pendingHumanAction: pending,
    activity: activityFor(investigation),
    artifacts: artifactsFor(investigation, brief, sourceNames),
    currentStepId: currentStep.id,
    canCancel: Boolean(investigation.run && ['queued', 'running', 'waiting_for_input'].includes(investigation.run.state)),
    canStart: !investigation.run && investigation.status === 'draft',
    canRetry: Boolean(investigation.run && ['failed', 'cancelled'].includes(investigation.run.state)),
    canCreateBrief: pending?.kind === 'create-brief',
    canOpenBrief: Boolean(brief),
    advanced: {
      runId: investigation.run?.id ?? null,
      scopeVersionId: investigation.scopeVersionId,
      graphVersion: investigation.run?.graphVersion ?? null,
      latestSequence: investigation.run?.latestSequence ?? null,
      traceRef: investigation.run?.traceRef ?? null,
      promptRefs: investigation.run?.promptRefs ?? [],
      currentInternalNode: currentStep.internalNode,
    },
  };
}

export function agentRunStateLabel(state: RunState | null): string {
  if (!state) return 'Ready to start';
  return statusPresentation(state === 'queued' ? 'preparing' : state === 'running' ? 'running' : state === 'waiting_for_input' ? 'needs-input' : state === 'failed' ? 'failed' : state === 'cancelled' ? 'cancelled' : 'completed').statusLabel;
}
