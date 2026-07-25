import type {
  CandidateVerdict,
  QuantArtifact,
  QuantCommand,
  QuantCandidate,
  QuantCandidateEvolution,
  QuantExecutableResearchPlan,
  QuantRunEvent,
  QuantRunState,
  QuantSelectionDecision,
  QuantWorkspaceSnapshot,
  TradeRecord,
} from '../../quant-domain';
import type { QuantRunHistoryItem } from '../../quant-api';

export type QuantTone = 'neutral' | 'info' | 'warning' | 'positive' | 'danger';

interface QuantEvidenceFocusBase {
  runId: string;
  candidateId: string;
}

type QuantEvidenceFocusTarget =
  | { destination: 'analysis'; target: 'drawdown' }
  | { destination: 'analysis'; target: 'trade'; tradeId: string }
  | { destination: 'report'; target: 'validation' }
  | { destination: 'report'; target: 'trades'; tradeId?: string }
  | { destination: 'runs'; target: 'source_comparison'; sourceRunId: string };

export type QuantEvidenceFocusRequest = QuantEvidenceFocusBase & QuantEvidenceFocusTarget & { label: string };

export type QuantEvidenceFocusIntent = QuantEvidenceFocusBase & QuantEvidenceFocusTarget & { id: string };

export interface QuantEvidenceFocusResolution {
  destination: 'analysis' | 'report' | 'runs';
  target: 'drawdown' | 'trade' | 'validation' | 'trades' | 'source_comparison';
  candidateId: string;
  receipt: string;
  evidenceReference: string;
}

export interface QuantEvidenceFocusResult {
  status: 'opened' | 'unavailable';
  receipt: string;
  evidenceReference: string;
}

export type QuantRunRelationship = 'root_version' | 'continued_version' | 'retry_attempt' | 'unresolved';

export interface QuantRunRelationshipProjection {
  relationship: QuantRunRelationship;
  baseRelationship?: 'root_version' | 'continued_version';
  retryAttemptNumber?: number;
  sourceRunId?: string;
  priorAttemptRunId?: string;
}

const relationshipUnavailable: QuantRunRelationshipProjection = { relationship: 'unresolved' };
const relationshipSourceTerminalStates: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled']);
const evidenceFocusReportStates: ReadonlySet<string> = new Set(['completed', 'waiting_for_review']);

export function projectEvidenceFocusActions(snapshot: QuantWorkspaceSnapshot, candidateId: string): QuantEvidenceFocusRequest[] {
  const candidate = snapshot.candidates.find((item) => item.id === candidateId);
  if (!candidate) return [];
  const actions: QuantEvidenceFocusRequest[] = [];
  const performance = snapshot.performanceSeries.find((series) => series.id === candidateId);
  if (performance?.points.length) {
    actions.push({ runId: snapshot.run.id, candidateId, destination: 'analysis', target: 'drawdown', label: 'Open max drawdown' });
  }
  const trade = snapshot.trades.find((item) => item.candidateId === candidateId);
  if (trade) {
    actions.push({ runId: snapshot.run.id, candidateId, destination: 'analysis', target: 'trade', tradeId: trade.id, label: 'Open retained trade' });
  }
  const generalization = snapshot.report?.generalization;
  const authoritativeSelection = snapshot.report?.selectionDecision?.selectedCandidateId;
  if (evidenceFocusReportStates.has(snapshot.run.state)
    && generalization?.selectedCandidateId === candidateId
    && (!authoritativeSelection || authoritativeSelection === candidateId)) {
    actions.push({
      runId: snapshot.run.id,
      candidateId,
      destination: 'report',
      target: 'validation',
      label: generalization.holdout ? 'Open sealed validation' : 'Open validation status',
    });
  }
  const continuedFrom = snapshot.run.continuedFrom;
  const selectedCandidateId = authoritativeSelection ?? generalization?.selectedCandidateId;
  if (continuedFrom
    && relationshipSourceTerminalStates.has(snapshot.run.state)
    && selectedCandidateId === candidateId) {
    actions.push({
      runId: snapshot.run.id,
      candidateId,
      destination: 'runs',
      target: 'source_comparison',
      sourceRunId: continuedFrom.parentRunId,
      label: 'Compare with source',
    });
  }
  return actions;
}

export function resolveEvidenceFocusIntent(snapshot: QuantWorkspaceSnapshot, intent: QuantEvidenceFocusIntent): QuantEvidenceFocusResolution | null {
  if (!intent.id.trim() || intent.runId !== snapshot.run.id) return null;
  const candidate = snapshot.candidates.find((item) => item.id === intent.candidateId);
  if (!candidate) return null;
  const candidateName = candidate.name.replace(/^Candidate [A-Z] · /, '');
  if (intent.destination === 'analysis' && intent.target === 'drawdown') {
    const performance = snapshot.performanceSeries.find((series) => series.id === candidate.id);
    if (!performance?.points.length) return null;
    return {
      destination: intent.destination,
      target: intent.target,
      candidateId: candidate.id,
      receipt: `${candidateName} · Analysis / Max drawdown`,
      evidenceReference: `${snapshot.run.id} · ${candidate.id} · max drawdown`,
    };
  }
  if (intent.destination === 'analysis' && intent.target === 'trade') {
    const trade = snapshot.trades.find((item) => item.id === intent.tradeId && item.candidateId === candidate.id);
    if (!trade) return null;
    return {
      destination: intent.destination,
      target: intent.target,
      candidateId: candidate.id,
      receipt: `${candidateName} · Analysis / Market · ${trade.entryDate} — ${trade.exitDate}`,
      evidenceReference: `${snapshot.run.id} · ${candidate.id} · ${trade.id}`,
    };
  }
  if (intent.destination === 'report' && intent.target === 'validation') {
    const generalization = snapshot.report?.generalization;
    const authoritativeSelection = snapshot.report?.selectionDecision?.selectedCandidateId;
    if (!evidenceFocusReportStates.has(snapshot.run.state)
      || generalization?.selectedCandidateId !== candidate.id
      || (authoritativeSelection && authoritativeSelection !== candidate.id)) return null;
    return {
      destination: intent.destination,
      target: intent.target,
      candidateId: candidate.id,
      receipt: `${candidateName} · Report / Validation`,
      evidenceReference: `${snapshot.run.id} · ${candidate.id} · validation ${generalization.status}`,
    };
  }
  if (intent.destination === 'report' && intent.target === 'trades') {
    const trade = intent.tradeId
      ? snapshot.trades.find((item) => item.id === intent.tradeId && item.candidateId === candidate.id)
      : snapshot.trades.find((item) => item.candidateId === candidate.id);
    if (!trade) return null;
    return {
      destination: intent.destination,
      target: intent.target,
      candidateId: candidate.id,
      receipt: `${candidateName} · Report / Trades`,
      evidenceReference: `${snapshot.run.id} · ${candidate.id} · ${trade.id}`,
    };
  }
  if (intent.destination === 'runs' && intent.target === 'source_comparison') {
    const selectedCandidateId = snapshot.report?.selectionDecision?.selectedCandidateId
      ?? snapshot.report?.generalization?.selectedCandidateId;
    if (!relationshipSourceTerminalStates.has(snapshot.run.state)
      || snapshot.run.continuedFrom?.parentRunId !== intent.sourceRunId
      || selectedCandidateId !== candidate.id) return null;
    return {
      destination: intent.destination,
      target: intent.target,
      candidateId: candidate.id,
      receipt: `${candidateName} · Runs / Compare with source`,
      evidenceReference: `${snapshot.run.id} ↔ ${intent.sourceRunId}`,
    };
  }
  return null;
}

function isTerminalHistoryState(state: string): boolean {
  return relationshipSourceTerminalStates.has(state);
}

function sameUtcInstant(first: string | undefined, second: string | undefined): boolean {
  if (!first || !second) return false;
  const firstTime = Date.parse(first);
  const secondTime = Date.parse(second);
  return Number.isFinite(firstTime) && firstTime === secondTime;
}

function sameResearchIdentity(left: QuantRunHistoryItem, right: QuantRunHistoryItem): boolean {
  const sameBaseIdentity = left.projectId === right.projectId
    && left.datasetId === right.datasetId
    && left.contract === right.contract;
  if (!sameBaseIdentity) return false;
  if (left.contract !== 'market-v2-public' || right.contract !== 'market-v2-public') return true;
  const sameSource = Boolean(left.symbol && right.symbol && left.symbol === right.symbol)
    && left.interval === right.interval
    && left.periodsPerYear === right.periodsPerYear
    && Boolean(left.datasetDigest && left.datasetDigest === right.datasetDigest);
  if (!sameSource) return false;
  const sameRange = sameUtcInstant(left.researchStartUtc, right.researchStartUtc)
    && sameUtcInstant(left.researchEndUtc, right.researchEndUtc);
  const samePins = Boolean(left.runtimeDescriptorDigest && left.runtimeDescriptorDigest === right.runtimeDescriptorDigest)
    && Boolean(left.sealedSplitDigest && left.sealedSplitDigest === right.sealedSplitDigest);
  const distinctPins = Boolean(left.runtimeDescriptorDigest && right.runtimeDescriptorDigest && left.runtimeDescriptorDigest !== right.runtimeDescriptorDigest)
    && Boolean(left.sealedSplitDigest && right.sealedSplitDigest && left.sealedSplitDigest !== right.sealedSplitDigest);
  return sameRange ? samePins : distinctPins;
}

function sameAttemptIdentity(left: QuantRunHistoryItem, right: QuantRunHistoryItem): boolean {
  if (!sameResearchIdentity(left, right)) return false;
  if (left.contract !== 'market-v2-public' || right.contract !== 'market-v2-public') return true;
  return sameUtcInstant(left.researchStartUtc, right.researchStartUtc)
    && sameUtcInstant(left.researchEndUtc, right.researchEndUtc)
    && Boolean(left.runtimeDescriptorDigest && left.runtimeDescriptorDigest === right.runtimeDescriptorDigest)
    && Boolean(left.sealedSplitDigest && left.sealedSplitDigest === right.sealedSplitDigest);
}

export function quantRunHistoryMatchesSnapshot(run: QuantRunHistoryItem, snapshot: QuantWorkspaceSnapshot): boolean {
  const snapshotParentRunId = snapshot.run.continuedFrom?.parentRunId ?? null;
  const snapshotSeedCandidateId = snapshot.run.continuedFrom?.seedCandidateId ?? null;
  const snapshotRefinementReason = snapshot.run.continuedFrom?.reason ?? null;
  const sameBaseIdentity = run.id === snapshot.run.id
    && run.projectId === snapshot.project.id
    && run.datasetId === snapshot.dataset.id
    && run.state === snapshot.run.state
    && (run.mode === 'auto' ? 'auto_research' : run.mode) === snapshot.run.mode
    && run.question === snapshot.project.goal
    && run.attemptNumber === snapshot.run.attemptNumber
    && run.retryOfRunId === (snapshot.run.retryOfRunId ?? null)
    && run.parentRunId === snapshotParentRunId
    && run.seedCandidateId === snapshotSeedCandidateId
    && run.refinementReason === snapshotRefinementReason
    && run.provider === snapshot.run.provider
    && run.model === snapshot.run.model;
  if (!sameBaseIdentity) return false;
  if (run.contract === 'legacy-daily-v1') {
    return snapshot.run.contract === 'legacy-daily-v1' && snapshot.dataset.contract === 'legacy-daily-v1';
  }
  if (snapshot.run.contract !== 'market-v2-public' || snapshot.dataset.contract !== 'market-v2') return false;
  const sameUtcInstant = (first: string | undefined, second: string): boolean => {
    if (!first) return false;
    const firstTime = Date.parse(first);
    const secondTime = Date.parse(second);
    return Number.isFinite(firstTime) && firstTime === secondTime;
  };
  return run.symbol === snapshot.scope.symbol
    && run.interval === snapshot.scope.interval
    && run.periodsPerYear === snapshot.dataset.periodsPerYear
    && sameUtcInstant(run.researchStartUtc, snapshot.scope.dateRange.start)
    && sameUtcInstant(run.researchEndUtc, snapshot.scope.dateRange.end)
    && run.datasetDigest === snapshot.dataset.digest
    && Boolean(snapshot.dataset.runtimeDescriptorDigest && run.runtimeDescriptorDigest === snapshot.dataset.runtimeDescriptorDigest)
    && Boolean(snapshot.dataset.sealedSplitDigest && run.sealedSplitDigest === snapshot.dataset.sealedSplitDigest);
}

function validAttempt(run: QuantRunHistoryItem): boolean {
  return Number.isInteger(run.attemptNumber) && run.attemptNumber >= 1;
}

function validLineage(run: QuantRunHistoryItem): boolean {
  const fields = [run.parentRunId, run.seedCandidateId, run.refinementReason];
  if (fields.every((value) => value === null)) return true;
  return typeof run.parentRunId === 'string'
    && run.parentRunId.length > 0
    && typeof run.seedCandidateId === 'string'
    && run.seedCandidateId.length > 0
    && typeof run.refinementReason === 'string'
    && run.refinementReason.length > 0
    && run.refinementReason === run.refinementReason.trim();
}

/**
 * Reads only the retained directory fields. A retry resolves before any parent
 * link so a retried continuation remains an attempt of its source version.
 */
export function projectQuantRunRelationship(
  run: QuantRunHistoryItem,
  loadedRuns: readonly QuantRunHistoryItem[],
): QuantRunRelationshipProjection {
  const runsById = new Map<string, QuantRunHistoryItem>();
  const duplicateIds = new Set<string>();
  for (const item of loadedRuns) {
    if (runsById.has(item.id)) duplicateIds.add(item.id);
    else runsById.set(item.id, item);
  }

  const resolve = (current: QuantRunHistoryItem, ancestors: ReadonlySet<string>): QuantRunRelationshipProjection => {
    if (!validAttempt(current) || !validLineage(current) || duplicateIds.has(current.id) || ancestors.has(current.id)) return relationshipUnavailable;
    const nextAncestors = new Set(ancestors);
    nextAncestors.add(current.id);
    const resolveReference = (id: string | null): QuantRunHistoryItem | null => {
      if (!id || id === current.id || duplicateIds.has(id)) return null;
      const target = runsById.get(id);
      return target && sameResearchIdentity(current, target) ? target : null;
    };

    if (current.retryOfRunId !== null) {
      const source = resolveReference(current.retryOfRunId);
      if (
        !source
        || !sameAttemptIdentity(current, source)
        || !isTerminalHistoryState(source.state)
        || current.attemptNumber !== source.attemptNumber + 1
        || current.parentRunId !== source.parentRunId
        || current.seedCandidateId !== source.seedCandidateId
        || current.refinementReason !== source.refinementReason
        || current.question !== source.question
        || current.mode !== source.mode
        || current.provider !== source.provider
        || current.model !== source.model
      ) return relationshipUnavailable;
      if (loadedRuns.filter((item) => item.retryOfRunId === source.id).length !== 1) return relationshipUnavailable;
      const sourceRelationship = resolve(source, nextAncestors);
      const baseRelationship = sourceRelationship.relationship === 'retry_attempt'
        ? sourceRelationship.baseRelationship
        : sourceRelationship.relationship;
      if (baseRelationship !== 'root_version' && baseRelationship !== 'continued_version') return relationshipUnavailable;
      return {
        relationship: 'retry_attempt',
        baseRelationship,
        retryAttemptNumber: current.attemptNumber,
        ...(sourceRelationship.sourceRunId ? { sourceRunId: sourceRelationship.sourceRunId } : {}),
        priorAttemptRunId: source.id,
      };
    }

    if (current.parentRunId !== null) {
      if (current.attemptNumber !== 1) return relationshipUnavailable;
      const source = resolveReference(current.parentRunId);
      if (!source || !isTerminalHistoryState(source.state)) return relationshipUnavailable;
      const sourceRelationship = resolve(source, nextAncestors);
      if (sourceRelationship.relationship === 'unresolved') return relationshipUnavailable;
      return { relationship: 'continued_version', baseRelationship: 'continued_version', sourceRunId: source.id };
    }

    return current.attemptNumber === 1
      ? { relationship: 'root_version', baseRelationship: 'root_version' }
      : relationshipUnavailable;
  };

  return resolve(run, new Set());
}

export function quantRunRelationshipLabel(projection: QuantRunRelationshipProjection): string {
  if (projection.relationship === 'root_version') return 'Root version';
  if (projection.relationship === 'continued_version') return 'Continued version';
  if (projection.relationship === 'retry_attempt' && projection.baseRelationship && projection.retryAttemptNumber) {
    return `${projection.baseRelationship === 'root_version' ? 'Root version' : 'Continued version'} · Retry attempt ${projection.retryAttemptNumber}`;
  }
  return 'Relationship unavailable';
}

function elapsedDuration(seconds: number): string {
  let remainder = seconds;
  const days = Math.floor(remainder / 86_400);
  remainder %= 86_400;
  const hours = Math.floor(remainder / 3_600);
  remainder %= 3_600;
  const minutes = Math.floor(remainder / 60);
  const trailingSeconds = remainder % 60;
  const parts: string[] = [];
  if (days) parts.push(`${days}d`);
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (trailingSeconds) parts.push(`${trailingSeconds}s`);
  return parts.join(' ') || '0h';
}

export function formatTradeHolding(trade: TradeRecord, legacyStyle: 'compact' | 'long' = 'long'): string {
  if (trade.holdingBars !== undefined && trade.holdingElapsedSeconds !== undefined) {
    return `${trade.holdingBars} bars · ${elapsedDuration(trade.holdingElapsedSeconds)}`;
  }
  return legacyStyle === 'compact' ? `${trade.holdingDays}d` : `${trade.holdingDays} days`;
}

export function canContinueResearch(snapshot: QuantWorkspaceSnapshot, candidate: QuantCandidate | undefined): boolean {
  const compatibleContract = (snapshot.run.contract === 'legacy-daily-v1' && snapshot.dataset.contract === 'legacy-daily-v1')
    || (snapshot.run.contract === 'market-v2-public' && snapshot.dataset.contract === 'market-v2');
  return Boolean(compatibleContract
    && candidate?.canSeedResearch
    && ['completed', 'failed', 'cancelled'].includes(snapshot.run.state));
}

export type QuantNextResearchProposal = {
  recommendation: 'refine' | 'stop';
  execution: 'one_bounded_auto_run' | 'none';
  change: string;
  rationale: string;
  evidenceRequired: string;
  stopCondition: string;
  refinementReason: string;
};

export type QuantTerminalDecisionProjection = {
  finalCandidateId: string;
  finalCandidateName: string;
  selectionReason: string;
  selectionBasis: QuantSelectionDecision['basis'];
  holdoutStatus: 'pass' | 'fail' | 'inconclusive';
  holdoutReason: string;
  decision: 'stop' | 'refine';
  decisionDetail: string;
  canRefine: boolean;
  refinementReason: string;
  /** Present only for an eligible, retained Refine decision. */
  refinement?: {
    proposedChange: string;
    evidenceBasis: string;
    successCondition: string;
    stopCondition: string;
  };
};

export interface QuantPaperTradingEligibility {
  eligible: boolean;
  candidateId: string | null;
  candidateName: string | null;
  reason: string;
  canOpenDecision: boolean;
}

/**
 * Paper simulation is a handoff from the authoritative terminal decision only.
 * It intentionally does not infer a retained candidate from provisional report fields.
 */
export function projectPaperTradingEligibility(snapshot: QuantWorkspaceSnapshot): QuantPaperTradingEligibility {
  const terminalDecision = projectTerminalDecision(snapshot);
  const canOpenDecision = Boolean(snapshot.report);

  if (terminalDecision?.holdoutStatus === 'pass') {
    const candidate = snapshot.candidates.find((item) => item.id === terminalDecision.finalCandidateId);
    if (candidate && candidate.name === terminalDecision.finalCandidateName) {
      return {
        eligible: true,
        candidateId: candidate.id,
        candidateName: candidate.name,
        reason: 'Final report retained',
        canOpenDecision,
      };
    }
    return {
      eligible: false,
      candidateId: terminalDecision.finalCandidateId,
      candidateName: terminalDecision.finalCandidateName,
      reason: 'The passed decision’s retained candidate is unavailable.',
      canOpenDecision,
    };
  }

  if (terminalDecision?.holdoutStatus === 'fail') {
    return {
      eligible: false,
      candidateId: terminalDecision.finalCandidateId,
      candidateName: terminalDecision.finalCandidateName,
      reason: terminalDecision.holdoutReason || 'The retained candidate failed the sealed holdout.',
      canOpenDecision,
    };
  }

  if (terminalDecision?.holdoutStatus === 'inconclusive') {
    return {
      eligible: false,
      candidateId: terminalDecision.finalCandidateId,
      candidateName: terminalDecision.finalCandidateName,
      reason: terminalDecision.holdoutReason || 'The sealed holdout was inconclusive.',
      canOpenDecision,
    };
  }

  if (snapshot.run.state !== 'completed') {
    return {
      eligible: false,
      candidateId: null,
      candidateName: null,
      reason: 'Research is still in progress; wait for a sealed decision.',
      canOpenDecision,
    };
  }

  const report = snapshot.report;
  if (!report || !report.selectionDecision || !report.generalization) {
    return {
      eligible: false,
      candidateId: null,
      candidateName: null,
      reason: 'No terminal decision is available.',
      canOpenDecision,
    };
  }

  const selectedCandidateId = report.selectionDecision.selectedCandidateId;
  const generalizationCandidateId = report.generalization.selectedCandidateId;
  const candidate = selectedCandidateId
    ? snapshot.candidates.find((item) => item.id === selectedCandidateId)
    : undefined;

  if (!selectedCandidateId) {
    return {
      eligible: false,
      candidateId: null,
      candidateName: null,
      reason: 'No retained candidate was selected.',
      canOpenDecision,
    };
  }

  if (selectedCandidateId !== generalizationCandidateId || !candidate) {
    return {
      eligible: false,
      candidateId: selectedCandidateId,
      candidateName: candidate?.name ?? null,
      reason: 'The retained candidate identity is missing or inconsistent.',
      canOpenDecision,
    };
  }

  return {
    eligible: false,
    candidateId: selectedCandidateId,
    candidateName: candidate.name,
    reason: report.generalization.status === 'not_evaluated'
      ? 'Experiments complete — validation pending'
      : 'The retained candidate is not eligible for paper trading.',
    canOpenDecision,
  };
}

export function projectNextResearchProposal(
  snapshot: QuantWorkspaceSnapshot,
  candidate: QuantCandidate | undefined,
  comparisonOutcome?: string,
): QuantNextResearchProposal | null {
  if (!candidate || !canContinueResearch(snapshot, candidate) || !snapshot.report) return null;
  const generalization = snapshot.report.generalization;
  const status = generalization?.status ?? 'not_evaluated';
  if (status === 'not_evaluated' && !comparisonOutcome) return null;
  const rationale = generalization?.reason || snapshot.report.proposedNextStep || comparisonOutcome || 'The retained result requires another bounded decision.';
  if (status === 'pass') {
    return {
      recommendation: 'stop',
      execution: 'none',
      change: 'Do not create another research version by default.',
      rationale,
      evidenceRequired: 'Use the retained report and sealed-holdout result as the decision record.',
      stopCondition: 'Stop this research sequence unless the user introduces a materially different hypothesis.',
      refinementReason: '',
    };
  }
  const change = status === 'inconclusive'
    ? 'Test one bounded parameter change aimed at producing sufficient holdout exposure.'
    : status === 'fail'
      ? 'Test one bounded parameter change aimed at preserving positive return while reducing holdout drawdown.'
      : 'Test one bounded change that addresses the retained report recommendation.';
  const evidenceRequired = status === 'inconclusive'
    ? 'Require non-zero holdout exposure and a final comparison against the retained seed.'
    : 'Require a final candidate comparison and one new sealed-holdout result.';
  const stopCondition = 'Stop after this independent Refine if it does not improve the named weakness or remains inconclusive.';
  return {
    recommendation: 'refine',
    execution: 'one_bounded_auto_run',
    change,
    rationale,
    evidenceRequired,
    stopCondition,
    refinementReason: `${change} Reason: ${rationale} Retain ${candidate.name} (${candidate.parameters}) as the seed. ${evidenceRequired} ${stopCondition}`,
  };
}

/**
 * Projects the completed Report's single terminal decision from retained, server-owned evidence.
 * No candidate ranking, metric calculation, or identity reconciliation happens in the client.
 */
export function projectTerminalDecision(snapshot: QuantWorkspaceSnapshot): QuantTerminalDecisionProjection | null {
  if (snapshot.run.state !== 'completed') return null;
  const report = snapshot.report;
  const decision = report?.selectionDecision;
  const generalization = report?.generalization;
  const finalCandidateId = decision?.selectedCandidateId;
  const holdoutStatus = generalization?.status;
  if (!report
    || !decision
    || !generalization
    || !finalCandidateId
    || generalization.selectedCandidateId !== finalCandidateId
    || (holdoutStatus !== 'pass'
      && holdoutStatus !== 'fail'
      && holdoutStatus !== 'inconclusive')) return null;

  const finalCandidate = snapshot.candidates.find((candidate) => candidate.id === finalCandidateId);
  const selectionReason = finalCandidate?.evolution?.selectionReason.trim()
    || decision.reason
    || decision.basis;
  if (!finalCandidate || !selectionReason) return null;

  const nextProposal = projectNextResearchProposal(snapshot, finalCandidate);
  if (holdoutStatus === 'pass') {
    return {
      finalCandidateId: finalCandidate.id,
      finalCandidateName: finalCandidate.name,
      selectionReason,
      selectionBasis: decision.basis,
      holdoutStatus,
      holdoutReason: generalization.reason,
      decision: 'stop',
      decisionDetail: nextProposal?.recommendation === 'stop'
        ? nextProposal.stopCondition
        : 'Stop this research series unless the user introduces a materially different hypothesis.',
      canRefine: false,
      refinementReason: '',
    };
  }
  const refinementProposal = nextProposal?.recommendation === 'refine' ? nextProposal : null;

  return {
    finalCandidateId: finalCandidate.id,
    finalCandidateName: finalCandidate.name,
    selectionReason,
    selectionBasis: decision.basis,
    holdoutStatus,
    holdoutReason: generalization.reason,
    decision: 'refine',
    decisionDetail: refinementProposal
      ? refinementProposal.change
      : 'This retained final choice is not eligible to seed a new research version.',
    canRefine: Boolean(refinementProposal),
    refinementReason: refinementProposal?.refinementReason ?? '',
    ...(refinementProposal
      ? {
          refinement: {
            proposedChange: refinementProposal.change,
            evidenceBasis: refinementProposal.rationale,
            successCondition: refinementProposal.evidenceRequired,
            stopCondition: refinementProposal.stopCondition,
          },
        }
      : {}),
  };
}

export type QuantViewAction = 'open_report' | 'compare_candidates' | 'open_diagnostics';

export interface QuantActivityPresentation {
  id: string;
  title: string;
  summary: string;
  timestamp: string;
  actorLabel: string;
  artifactId?: string;
  kind: 'event' | 'agent_decision' | 'tool_call';
  action?: string;
  expectedResult?: string;
  advanced: { eventType: string; sequence: number; safeSummary: string };
}

export interface QuantActionPresentation {
  kind: QuantCommand | QuantViewAction;
  label: string;
  tone: 'primary' | 'default';
}

export interface QuantCandidatePresentation {
  id: string;
  name: string;
  verdictLabel: string;
  verdictTone: QuantTone;
  reason: string;
}

export interface QuantWorkspacePresentation {
  statusLabel: string;
  statusTone: QuantTone;
  decision: QuantDecisionPresentation;
  currentActionTitle: string;
  currentActionPurpose: string;
  completedStepCount: number;
  negativeConclusion: boolean;
  activity: QuantActivityPresentation[];
  actions: QuantActionPresentation[];
  candidates: QuantCandidatePresentation[];
  primaryArtifacts: QuantArtifact[];
}

export interface QuantDecisionPresentation {
  label: string;
  title: string;
  summary: string;
  nextStep: string;
  tone: QuantTone;
}

export interface QuantDecisionLedgerProjection {
  path: 'adapted_candidate' | 'structured_stop';
  initialCandidates: Array<{
    id: string;
    name: string;
    hypothesis: string;
  }>;
  observation: {
    referenceCandidateId: string;
    referenceCandidateName: string;
  };
  outcome: {
    kind: 'candidate';
    candidateId: string;
    candidateName: string;
    hypothesis: string;
    rationale: string;
    replanRepair?: QuantCandidateEvolution['replanRepair'];
  } | {
    kind: 'stop';
    reason: 'no_novel_candidate' | 'insufficient_action_budget';
    referenceCandidateId: string;
    referenceCandidateName: string;
  };
  finalChoice: {
    candidateId: string;
    candidateName: string;
    basis: QuantSelectionDecision['basis'];
    reason?: QuantSelectionDecision['reason'];
    referenceCandidateId?: string;
    referenceCandidateName?: string;
    selectionReason: string;
  };
}

export type QuantCopilotActionKind = QuantCommand
  | 'open_analysis'
  | 'open_report'
  | 'new_research'
  | 'continue_research'
  | 'return_latest';

export interface QuantCopilotAction {
  kind: QuantCopilotActionKind;
  label: string;
  tone: 'primary' | 'default';
}

export interface QuantCopilotProjection {
  current: { title: string; detail: string; question: string };
  observation: { title: string; detail: string; tone: QuantTone };
  next: { detail: string; actions: QuantCopilotAction[] };
  canAsk: boolean;
  readOnly: boolean;
}

export interface QuantStrategyScopePresentation {
  status: 'supported' | 'bounded_proxy' | 'unsupported';
  label: 'Supported' | 'Supported · Legacy plan' | 'Bounded proxy' | 'Not supported';
  title: string;
  reason: string;
  proxyDescription?: string;
  excludedBehaviors: string[];
  legacy: boolean;
  requiresConfirmation: boolean;
  blocksApproval: boolean;
}

const legacySupportedStrategyScopeReason = 'Legacy retained plan predates strategy-scope classification and is treated as supported.';

function isLegacySupportedStrategyScope(
  scope: NonNullable<QuantExecutableResearchPlan['strategyScope']>,
): boolean {
  return scope.schemaVersion === 'quant-strategy-scope-v1'
    && scope.status === 'supported'
    && scope.reason === legacySupportedStrategyScopeReason
    && scope.proxyDescription === undefined
    && scope.excludedBehaviors.length === 0;
}

export function presentStrategyScopeDecision(
  plan: QuantExecutableResearchPlan,
): QuantStrategyScopePresentation {
  const scope = plan.strategyScope;
  if (!scope) {
    return {
      status: 'supported',
      label: 'Supported · Legacy plan',
      title: 'Supported within registered strategies',
      reason: legacySupportedStrategyScopeReason,
      excludedBehaviors: [],
      legacy: true,
      requiresConfirmation: false,
      blocksApproval: false,
    };
  }
  if (isLegacySupportedStrategyScope(scope)) {
    return {
      status: scope.status,
      label: 'Supported · Legacy plan',
      title: 'Supported within registered strategies',
      reason: scope.reason,
      excludedBehaviors: [],
      legacy: true,
      requiresConfirmation: false,
      blocksApproval: false,
    };
  }
  if (scope.status === 'bounded_proxy') {
    return {
      status: scope.status,
      label: 'Bounded proxy',
      title: 'Review the bounded proxy',
      reason: scope.reason,
      proxyDescription: scope.proxyDescription,
      excludedBehaviors: scope.excludedBehaviors,
      legacy: false,
      requiresConfirmation: true,
      blocksApproval: false,
    };
  }
  if (scope.status === 'unsupported') {
    return {
      status: scope.status,
      label: 'Not supported',
      title: 'Change the research request',
      reason: scope.reason,
      excludedBehaviors: scope.excludedBehaviors,
      legacy: false,
      requiresConfirmation: false,
      blocksApproval: true,
    };
  }
  return {
    status: scope.status,
    label: 'Supported',
    title: 'Supported as specified',
    reason: scope.reason,
    excludedBehaviors: [],
    legacy: false,
    requiresConfirmation: false,
    blocksApproval: false,
  };
}

function strategyScopeAllowsCommand(
  snapshot: QuantWorkspaceSnapshot,
  command: QuantCommand,
): boolean {
  if (!snapshot.researchPlan) return true;
  const scope = presentStrategyScopeDecision(snapshot.researchPlan);
  if (!scope.blocksApproval) return true;
  return command === 'request_plan_changes' || command === 'cancel_run';
}

const stateCopy: Record<QuantRunState, [string, QuantTone, string, string]> = {
  draft: ['Ready', 'neutral', 'Research scope is ready', 'Generate a plan from the bounded goal and configured limits.'],
  planning: ['Planning', 'info', 'Generating a structured plan', 'The fixture API owns this planning state.'],
  waiting_plan_approval: ['Waiting for plan approval', 'warning', 'Plan approval is required', 'Review the frozen scope and limits before execution.'],
  queued: ['Queued', 'info', 'Waiting for deterministic execution', 'Execution can begin only after the required approval record exists.'],
  loading_data: ['Verifying dataset', 'info', 'Verifying the pinned dataset', 'The dataset identity, digest, and required history are being checked before research begins.'],
  generating_candidates: ['Preparing candidates', 'info', 'Preparing bounded candidates', 'Candidate specifications are being created within the approved universe and experiment limits.'],
  running_experiments: ['Running experiments', 'info', 'Evaluating approved candidates', 'The Agent is running one bounded experiment at a time against the pinned dataset.'],
  repairing: ['Repairing candidate', 'warning', 'Retrying a recoverable experiment', 'The affected candidate is being retried within the approved repair limit. Completed results remain unchanged.'],
  validating: ['Validating evidence', 'info', 'Running robustness checks', 'Completed candidates are being checked across walk-forward windows and the sealed holdout.'],
  generating_report: ['Building report', 'info', 'Assembling the research report', 'Retained results, validation findings, and limitations are being assembled for human review.'],
  waiting_for_review: ['Waiting for review', 'warning', 'Research results need review', 'Review findings and the report draft before completing the process.'],
  completed: ['Experiments complete', 'warning', 'Experiments complete', 'Review the retained validation evidence and final decision.'],
  failed: ['Failed safely', 'danger', 'The run stopped safely', 'Persisted artifacts remain available for diagnosis and a new attempt.'],
  cancelled: ['Cancelled', 'neutral', 'The run was cancelled', 'Events and artifacts recorded before cancellation remain immutable.'],
  unknown: ['Unrecognized state', 'neutral', 'The run state is not recognized', 'Check diagnostics for the raw state value returned by the server.'],
};

const eventCopy: Record<string, string> = {
  'run.created': 'Research attempt created',
  'plan.generated': 'Research plan generated',
  'review.required': 'Your review is required',
  'plan.approved': 'Plan approved',
  'data.load.started': 'Loading the approved dataset',
  'data.load.completed': 'Dataset snapshot loaded',
  'benchmark.generated': 'Benchmark prepared',
  'candidate.generated': 'Candidate generated',
  'backtest.started': 'Experiment started',
  'backtest.completed': 'Experiment completed',
  'backtest.failed': 'Candidate experiment stopped safely',
  'repair.started': 'Repair attempt started',
  'repair.completed': 'Repair attempt completed',
  'validation.started': 'Robustness validation started',
  'validation.completed': 'Robustness validation completed',
  'candidate.rejected': 'Candidate rejected by validator',
  'candidate.promoted': 'Candidate retained for validation',
  'report.generated': 'Research Report generated',
  'run.completed': 'Research process completed',
  'run.cancelled': 'Run cancelled; retained work remains',
  'run.failed': 'Run stopped safely',
  'agent.action_selected': 'Agent decision',
  'agent.decision_failed': 'Agent decision failed safely',
  'agent.provider_fallback': 'Agent provider fallback',
  'tool.started': 'Tool call started',
  'tool.completed': 'Tool call completed',
  'tool.failed': 'Tool call failed safely',
  'comparison.generated': 'Candidate comparison generated',
};

const actorCopy: Record<QuantRunEvent['actor'], string> = {
  user: 'User', system: 'System', agent: 'Agent', validator: 'Validator',
};

const verdictCopy: Record<CandidateVerdict, [string, QuantTone]> = {
  promising: ['Retained for validation', 'positive'],
  inconclusive: ['Inconclusive', 'warning'],
  rejected: ['Rejected', 'danger'],
  invalid: ['Invalid candidate', 'neutral'],
};

const commandLabels: Partial<Record<QuantCommand, string>> = {
  approve_plan: 'Approve & Run',
  run_fixture: 'Run Synthetic Agent',
  request_plan_changes: 'Request Changes',
  approve_execution: 'Approve Once',
  cancel_run: 'Cancel Run',
  retry_run: 'Retry as New Attempt',
  complete_review: 'Complete Review',
  start_new_run: 'Start New Run',
};

export function presentPromotionDecision(snapshot: QuantWorkspaceSnapshot): QuantDecisionPresentation {
  const generalization = snapshot.report?.generalization;
  const noViableCandidate = snapshot.run.state === 'completed'
    && snapshot.candidates.length > 0
    && snapshot.candidates.every((candidate) => candidate.verdict !== 'promising');
  const selectedCandidate = snapshot.candidates.find((candidate) => candidate.id === generalization?.selectedCandidateId)
    ?? snapshot.candidates.find((candidate) => candidate.verdict === 'promising');
  const candidateName = selectedCandidate?.name ?? 'The selected candidate';
  const proposedNextStep = snapshot.report?.proposedNextStep;

  if (snapshot.run.state === 'failed') {
    return {
      label: 'Run stopped',
      title: 'Research failed safely',
      summary: 'No promotion decision was produced. Persisted events and artifacts remain available for diagnosis.',
      nextStep: 'Inspect the retained diagnostics, then start a new immutable attempt.',
      tone: 'danger',
    };
  }
  if (snapshot.run.state === 'cancelled') {
    return {
      label: 'No decision',
      title: 'Research was cancelled',
      summary: 'The run ended before sealed-holdout validation produced a promotion decision.',
      nextStep: 'Review retained work or start a new immutable research run.',
      tone: 'neutral',
    };
  }
  if (snapshot.run.state === 'waiting_for_review' && !generalization) {
    return {
      label: 'Review required',
      title: 'Research evidence is ready for review',
      summary: 'The run is waiting for a human decision before it can become immutable.',
      nextStep: 'Review the report draft and validation findings.',
      tone: 'warning',
    };
  }
  if (noViableCandidate && !generalization) {
    return {
      label: 'Not promotable',
      title: 'No candidate passed validation',
      summary: 'Every evaluated candidate was rejected or remained inconclusive. No candidate advanced to the sealed holdout.',
      nextStep: 'Revise the hypothesis or candidate constraints, then start a new immutable run.',
      tone: 'danger',
    };
  }
  if (snapshot.run.state !== 'completed' && !generalization) {
    return {
      label: 'Decision pending',
      title: 'Research is still in progress',
      summary: 'Results remain provisional until chronological validation and the sealed holdout are complete.',
      nextStep: stateCopy[snapshot.run.state][3],
      tone: 'info',
    };
  }
  if (generalization?.status === 'pass') {
    return {
      label: 'Eligible for human review',
      title: 'Sealed holdout passed',
      summary: generalization.reason || `${candidateName} passed the sealed holdout.`,
      nextStep: proposedNextStep || 'Review the retained limitations before considering paper evaluation.',
      tone: 'positive',
    };
  }
  if (generalization?.status === 'fail') {
    return {
      label: 'Not promotable',
      title: 'Sealed holdout failed',
      summary: generalization.reason || `${candidateName} failed the sealed holdout.`,
      nextStep: 'Revise the hypothesis and start a new immutable research run.',
      tone: 'danger',
    };
  }
  if (generalization?.status === 'inconclusive') {
    return {
      label: 'Not promotable',
      title: 'Sealed holdout inconclusive',
      summary: generalization.reason || `${candidateName} did not produce decisive sealed-holdout evidence.`,
      nextStep: 'Collect sufficient evidence in a new immutable run before considering promotion.',
      tone: 'warning',
    };
  }
  return {
    label: 'Not promotable',
    title: 'Sealed holdout pending',
    summary: generalization?.reason || 'No sealed holdout result is available for this completed run.',
    nextStep: 'Complete sealed holdout validation before considering promotion.',
    tone: 'warning',
  };
}

export function projectDecisionLedger(snapshot: QuantWorkspaceSnapshot): QuantDecisionLedgerProjection | null {
  const report = snapshot.report;
  const decision = report?.selectionDecision;
  const selectedCandidateId = decision?.selectedCandidateId;
  if (!report || !decision || !selectedCandidateId) return null;

  const initialCandidates = snapshot.candidates.filter((candidate) => candidate.evolution?.origin === 'initial');
  const adaptedCandidates = snapshot.candidates.filter((candidate) => candidate.evolution?.origin === 'training_feedback');
  const stop = report.iterationStop;
  if (initialCandidates.length !== 2 || (adaptedCandidates.length === 1) === Boolean(stop)) return null;

  const adaptedCandidate = adaptedCandidates.length === 1 ? adaptedCandidates[0] : undefined;
  if (adaptedCandidates.length > 1) return null;
  const referenceCandidateId = adaptedCandidate?.evolution?.feedbackReferenceCandidateId ?? stop?.referenceCandidateId;
  const referenceCandidate = initialCandidates.find((candidate) => candidate.id === referenceCandidateId);
  const selectedCandidate = snapshot.candidates.find((candidate) => candidate.id === selectedCandidateId);
  const decisionReference = decision.referenceCandidateId
    ? snapshot.candidates.find((candidate) => candidate.id === decision.referenceCandidateId)
    : undefined;
  if (!referenceCandidateId || !referenceCandidate || !selectedCandidate?.evolution) return null;
  if (decision.referenceCandidateId && !decisionReference) return null;

  const initialProjection = initialCandidates.map((candidate) => ({
    id: candidate.id,
    name: candidate.name,
    hypothesis: candidate.evolution!.hypothesis,
  }));
  const finalChoice: QuantDecisionLedgerProjection['finalChoice'] = {
    candidateId: selectedCandidate.id,
    candidateName: selectedCandidate.name,
    basis: decision.basis,
    selectionReason: selectedCandidate.evolution.selectionReason,
    ...(decision.reason ? { reason: decision.reason } : {}),
    ...(decision.referenceCandidateId
      ? {
          referenceCandidateId: decision.referenceCandidateId,
          referenceCandidateName: decisionReference!.name,
        }
      : {}),
  };

  if (adaptedCandidate?.evolution?.changeRationale) {
    return {
      path: 'adapted_candidate',
      initialCandidates: initialProjection,
      observation: {
        referenceCandidateId,
        referenceCandidateName: referenceCandidate.name,
      },
      outcome: {
        kind: 'candidate',
        candidateId: adaptedCandidate.id,
        candidateName: adaptedCandidate.name,
        hypothesis: adaptedCandidate.evolution.hypothesis,
        rationale: adaptedCandidate.evolution.changeRationale,
        replanRepair: adaptedCandidate.evolution.replanRepair,
      },
      finalChoice,
    };
  }
  if (!stop) return null;
  return {
    path: 'structured_stop',
    initialCandidates: initialProjection,
    observation: {
      referenceCandidateId,
      referenceCandidateName: referenceCandidate.name,
    },
    outcome: {
      kind: 'stop',
      reason: stop.reason,
      referenceCandidateId,
      referenceCandidateName: referenceCandidate.name,
    },
    finalChoice,
  };
}

function trainingObservation(snapshot: QuantWorkspaceSnapshot): { title: string; detail: string; tone: QuantTone } | null {
  const latest = snapshot.liveResearch?.latestResult;
  if (latest?.metrics) {
    const metrics = latest.metrics;
    return {
      title: `${latest.name.replace(/^Candidate [A-Z] · /, '')} completed training`,
      detail: `${metrics.annualizedReturn >= 0 ? '+' : ''}${metrics.annualizedReturn.toFixed(1)}% annual return · ${metrics.sharpe.toFixed(2)} Sharpe · ${metrics.maxDrawdown.toFixed(1)}% drawdown.`,
      tone: metrics.annualizedReturn >= 0 ? 'info' : 'warning',
    };
  }
  const current = snapshot.liveResearch?.currentExperiment;
  if (current) {
    return {
      title: `${current.name.replace(/^Candidate [A-Z] · /, '')} is ${current.state.replaceAll('_', ' ')}`,
      detail: current.hypothesis,
      tone: current.state === 'failed' ? 'danger' : current.state === 'repairing' ? 'warning' : 'info',
    };
  }
  return null;
}

/**
 * Produces a front-stage research summary from typed retained state only. It
 * deliberately does not interpret event prose or expose a report/holdout
 * before the run reaches review or a terminal state.
 */
export function presentResearchCopilot(
  snapshot: QuantWorkspaceSnapshot,
  options: { selectedCandidateId?: string; isHistorical?: boolean } = {},
): QuantCopilotProjection {
  const lifecycle = presentQuantWorkspace(snapshot);
  const readOnly = options.isHistorical === true;
  const legal = new Set(readOnly ? [] : [...snapshot.run.legalCommands, ...snapshot.composerLegalCommands]);
  const terminal = ['completed', 'failed', 'cancelled'].includes(snapshot.run.state);
  const reviewable = snapshot.run.state === 'waiting_for_review';
  const decision = presentPromotionDecision(snapshot);
  const completedCandidates = snapshot.candidates.length || snapshot.liveResearch?.candidates.filter((candidate) => candidate.state === 'completed').length || 0;
  const planCompleted = snapshot.plan.filter((step) => step.status === 'completed').length;
  const currentStep = snapshot.plan.find((step) => step.id === snapshot.run.currentStepId);
  const actions: QuantCopilotAction[] = [];
  const add = (kind: QuantCopilotActionKind, label: string, tone: 'primary' | 'default' = 'default') => {
    if (!actions.some((action) => action.kind === kind)) actions.push({ kind, label, tone });
  };
  const legalAction = (kind: QuantCommand, label: string, tone: 'primary' | 'default' = 'default') => {
    if (legal.has(kind) && strategyScopeAllowsCommand(snapshot, kind)) add(kind, label, tone);
  };

  let observation: QuantCopilotProjection['observation'];
  if ((terminal || reviewable) && snapshot.report) {
    observation = { title: decision.title, detail: decision.summary, tone: decision.tone };
  } else if (snapshot.run.state === 'loading_data') {
    observation = { title: 'Dataset verification in progress', detail: 'No experiment evidence is available until the pinned dataset passes its checks.', tone: 'info' };
  } else if (snapshot.run.state === 'generating_candidates') {
    observation = { title: 'Candidate specifications in progress', detail: 'No training result is available until the first bounded candidate completes.', tone: 'info' };
  } else if (['draft', 'planning', 'waiting_plan_approval', 'queued'].includes(snapshot.run.state)) {
    observation = { title: 'No experiment evidence yet', detail: 'Research has not reached candidate execution, so retained candidate data is not treated as current evidence.', tone: 'neutral' };
  } else {
    observation = trainingObservation(snapshot) ?? (completedCandidates > 0
      ? { title: `${completedCandidates} training ${completedCandidates === 1 ? 'candidate' : 'candidates'} retained`, detail: 'Comparison evidence remains provisional until validation and report completion.', tone: 'info' }
      : { title: 'No candidate evidence yet', detail: 'The first inspectable result will appear after a training backtest completes.', tone: snapshot.run.state === 'failed' ? 'danger' : 'neutral' });
  }

  let nextDetail = snapshot.liveResearch?.nextStep || stateCopy[snapshot.run.state][3];
  if (readOnly) {
    nextDetail = 'This retained run is read-only. Return to the latest run before issuing a command.';
    add('return_latest', 'Return to latest', 'primary');
    if (snapshot.candidates.length > 0) add('open_analysis', 'Open analysis');
    if (snapshot.report) add('open_report', 'Open decision');
  } else if (snapshot.run.state === 'waiting_plan_approval') {
    legalAction('approve_plan', 'Approve & run', 'primary');
    legalAction('request_plan_changes', 'Request changes', actions.length ? 'default' : 'primary');
    legalAction('cancel_run', 'Cancel run');
    if (snapshot.researchPlan) {
      const scope = presentStrategyScopeDecision(snapshot.researchPlan);
      if (scope.blocksApproval) {
        nextDetail = 'Revise the request to a supported strategy or an explicit bounded proxy before research can start.';
      } else if (scope.requiresConfirmation) {
        nextDetail = 'Confirm the proxy and omissions before Qurio runs experiments.';
      }
    }
  } else if (snapshot.run.state === 'waiting_for_review') {
    legalAction('complete_review', 'Complete review', 'primary');
    if (!actions.length && snapshot.report) add('open_report', 'Open decision', 'primary');
    else if (snapshot.report) add('open_report', 'Open decision');
    if (snapshot.candidates.length > 0) add('open_analysis', 'Open analysis');
    legalAction('request_plan_changes', 'Request changes');
  } else if (snapshot.run.state === 'completed') {
    if (snapshot.report) add('open_report', 'Open decision', 'primary');
    else if (snapshot.candidates.length > 0) add('open_analysis', 'Open analysis', 'primary');
    else add('new_research', 'New research', 'primary');
    if (snapshot.candidates.length > 0 && !actions.some((action) => action.kind === 'open_analysis')) add('open_analysis', 'Open analysis');
    add('new_research', 'New research');
    nextDetail = decision.nextStep;
  } else if (snapshot.run.state === 'failed' || snapshot.run.state === 'cancelled') {
    legalAction('retry_run', 'Retry run', 'primary');
    if (!actions.length) add('new_research', 'New research', 'primary');
    if (snapshot.candidates.length > 0) add('open_analysis', 'Open analysis');
    if (snapshot.report) add('open_report', 'Open decision');
    add('new_research', 'New research');
  } else if (snapshot.run.state === 'draft') {
    legalAction('generate_plan', 'Generate plan', 'primary');
    legalAction('start_auto_research', 'Generate plan first', actions.length ? 'default' : 'primary');
    legalAction('run_fixture', 'Run research', actions.length ? 'default' : 'primary');
    legalAction('cancel_run', 'Cancel run');
    if (!actions.length) add('new_research', 'New research', 'primary');
  } else if (snapshot.run.state === 'unknown') {
    nextDetail = 'Refresh the run before taking an action. Its state is not recognized.';
    add('new_research', 'New research', 'primary');
  } else {
    legalAction('approve_execution', 'Approve execution', 'primary');
    legalAction('run_fixture', 'Run research', actions.length ? 'default' : 'primary');
    legalAction('cancel_run', 'Cancel run', actions.length ? 'default' : 'primary');
    if (snapshot.run.state === 'validating' || snapshot.run.state === 'generating_report') add('open_analysis', 'Open analysis', actions.length ? 'default' : 'primary');
  }

  return {
    current: {
      title: snapshot.liveResearch?.phaseLabel || lifecycle.currentActionTitle,
      detail: currentStep ? `${currentStep.title} · ${planCompleted} of ${snapshot.plan.length} plan steps complete.` : `${planCompleted} of ${snapshot.plan.length} plan steps complete.`,
      question: snapshot.project.goal,
    },
    observation,
    next: { detail: nextDetail, actions },
    canAsk: !readOnly && legal.has('ask') && strategyScopeAllowsCommand(snapshot, 'ask'),
    readOnly,
  };
}

function presentActivity(event: QuantRunEvent): QuantActivityPresentation {
  const knownTitle = eventCopy[event.type];
  const kind = event.type === 'agent.action_selected'
    ? 'agent_decision'
    : event.type.startsWith('tool.')
      ? 'tool_call'
      : 'event';
  return {
    id: event.id,
    title: knownTitle ?? 'Run activity recorded',
    summary: knownTitle ? event.safeSummary : 'A durable run event was recorded. Open Advanced Inspector for its safe diagnostic fields.',
    timestamp: event.timestamp,
    actorLabel: actorCopy[event.actor],
    artifactId: event.artifactId,
    kind,
    action: event.action,
    expectedResult: event.expectedResult,
    advanced: { eventType: event.type, sequence: event.sequence, safeSummary: event.safeSummary },
  };
}

function presentActions(snapshot: QuantWorkspaceSnapshot): QuantActionPresentation[] {
  const actions: QuantActionPresentation[] = [];
  if (snapshot.run.state === 'waiting_for_review') {
    actions.push({ kind: 'open_report', label: 'Open Decision Draft', tone: 'primary' });
    actions.push({ kind: 'compare_candidates', label: 'Review Validation Findings', tone: 'default' });
  }
  if (snapshot.run.state === 'completed') {
    actions.push({ kind: 'open_report', label: 'Open Decision', tone: 'primary' });
    actions.push({ kind: 'compare_candidates', label: 'Compare Candidates', tone: 'default' });
  }
  if (snapshot.run.state === 'failed') actions.push({ kind: 'open_diagnostics', label: 'Open Diagnostics', tone: 'default' });
  for (const command of snapshot.run.legalCommands) {
    const label = commandLabels[command];
    if (label && strategyScopeAllowsCommand(snapshot, command)) {
      actions.push({ kind: command, label, tone: actions.length === 0 ? 'primary' : 'default' });
    }
  }
  return actions;
}

export function presentQuantWorkspace(snapshot: QuantWorkspaceSnapshot): QuantWorkspacePresentation {
  const [defaultStatusLabel, defaultStatusTone, defaultCurrentActionTitle, defaultActionPurpose] = stateCopy[snapshot.run.state];
  const terminalDecision = projectTerminalDecision(snapshot);
  const statusLabel = snapshot.run.state === 'completed'
    ? terminalDecision?.holdoutStatus === 'pass'
      ? 'Research complete'
      : terminalDecision
        ? 'Research concluded'
        : 'Experiments complete — validation pending'
    : defaultStatusLabel;
  const statusTone: QuantTone = snapshot.run.state === 'completed'
    ? terminalDecision?.holdoutStatus === 'pass'
      ? 'positive'
      : terminalDecision?.holdoutStatus === 'fail'
        ? 'danger'
        : 'warning'
    : defaultStatusTone;
  const currentActionTitle = snapshot.run.state === 'completed'
    ? terminalDecision?.holdoutStatus === 'pass'
      ? 'Research complete'
      : terminalDecision
        ? 'Research concluded'
        : 'Experiments complete — validation pending'
    : defaultCurrentActionTitle;
  const generalization = snapshot.run.state === 'completed' || snapshot.run.state === 'waiting_for_review'
    ? snapshot.report?.generalization
    : undefined;
  const decision = presentPromotionDecision(snapshot);
  const currentActionPurpose = snapshot.run.state === 'completed' ? decision.summary : defaultActionPurpose;
  const negativeConclusion = generalization?.status === 'fail'
    || snapshot.candidates.every((candidate) => candidate.verdict !== 'promising');
  return {
    statusLabel,
    statusTone,
    decision,
    currentActionTitle,
    currentActionPurpose,
    completedStepCount: snapshot.plan.filter((step) => step.status === 'completed').length,
    negativeConclusion,
    activity: [...snapshot.events].sort((left, right) => right.sequence - left.sequence).map(presentActivity),
    actions: presentActions(snapshot),
    candidates: snapshot.candidates.map((candidate) => {
      const selectedStatus = candidate.id === generalization?.selectedCandidateId ? generalization.status : undefined;
      const [verdictLabel, verdictTone] = selectedStatus === 'pass'
        ? ['Passed sealed holdout', 'positive'] as const
        : selectedStatus === 'fail'
          ? ['Failed sealed holdout', 'danger'] as const
          : selectedStatus === 'inconclusive'
            ? ['Holdout inconclusive', 'warning'] as const
            : verdictCopy[candidate.verdict];
      return { id: candidate.id, name: candidate.name, verdictLabel, verdictTone, reason: candidate.verdictReason };
    }),
    primaryArtifacts: [...snapshot.artifacts].sort((left, right) => Number(right.type === 'research_report') - Number(left.type === 'research_report')),
  };
}
