import { describe, expect, it } from 'vitest';
import type { Claim, DecisionBrief, Evidence, Investigation, ResearchRun, RunEvent, Synthesis } from '../../domain';
import { presentAgentSession } from './agent-presentation';

const event = (sequence: number, type: string, message = `${type} safe summary`): RunEvent => ({
  id: `event-${sequence}`,
  sequence,
  type,
  message,
  timestamp: `2026-07-16T00:0${sequence}:00Z`,
  authenticity: 'imported',
});

const run = (overrides: Partial<ResearchRun> = {}): ResearchRun => ({
  id: 'run-1',
  state: 'completed',
  rowVersion: 1,
  latestSequence: 5,
  attemptNumber: 1,
  graphVersion: 'bounded-research-v1',
  generationMethod: 'deterministic',
  provider: '',
  model: null,
  promptRefs: [],
  traceRef: null,
  usedCostUsd: '999.99',
  budget: { maxCostUsd: '4.00', maxDurationSeconds: 900 },
  waitingForInputReason: null,
  ...overrides,
});

const evidence = (overrides: Partial<Evidence> = {}): Evidence => ({
  id: 'evidence-1',
  investigationId: 'investigation-1',
  researchRunId: 'run-1',
  stance: 'supports',
  quote: 'Enterprise teams need a permission preview before an agent executes tools.',
  quoteStart: 0,
  quoteEnd: 76,
  contentVersionId: 'content-1',
  status: 'proposed',
  provenance: { researchRunId: 'run-1', extractionMethod: 'deterministic-v1' },
  latestReviewId: null,
  authenticity: 'imported',
  ...overrides,
});

const claim = (overrides: Partial<Claim> = {}): Claim => ({
  id: 'claim-1',
  investigationId: 'investigation-1',
  researchRunId: 'run-1',
  versionId: 'claim-version-1',
  rowVersion: 1,
  text: 'Permission uncertainty slows enterprise onboarding.',
  status: 'proposed',
  limitations: ['The approved scope is bounded.'],
  evidenceLinks: [{ id: 'link-1', evidenceId: 'evidence-1', stance: 'supports', weight: 1, rationale: null }],
  authenticity: 'imported',
  ...overrides,
});

const synthesis = (overrides: Partial<Synthesis> = {}): Synthesis => ({
  id: 'synthesis-1',
  versionId: 'synthesis-version-1',
  rowVersion: 1,
  status: 'verified',
  executiveSummary: 'Permission preview is sufficiently supported for prioritization review.',
  businessImplications: ['Reduce onboarding uncertainty.'],
  limitations: ['Approved sources only.'],
  verifiedClaimVersionIds: ['claim-version-1'],
  generationMethod: 'deterministic',
  generatorVersion: 'deterministic-v1',
  modelPromptRefs: [],
  authenticity: 'human_authored',
  ...overrides,
});

const investigation = (overrides: Partial<Investigation> = {}): Investigation => ({
  id: 'investigation-1',
  signalId: 'signal-1',
  question: 'Should we prioritize permission preview for enterprise teams?',
  status: 'reviewing',
  scopeVersionId: 'scope-1',
  sourceConnectionIds: ['source-1', 'source-2', 'source-3'],
  contentVersionIds: Array.from({ length: 12 }, (_, index) => `content-${index + 1}`),
  allowCloudModel: false,
  timeRange: { start: '2026-05-01T00:00:00Z', end: '2026-05-31T23:59:59Z' },
  run: run(),
  evidence: [evidence()],
  claims: [claim()],
  synthesis: null,
  events: [event(1, 'run.queued'), event(2, 'run.started'), event(3, 'evidence.proposed'), event(4, 'claim.version_proposed'), event(5, 'run.completed')],
  rowVersion: 2,
  authenticity: 'imported',
  ...overrides,
});

const brief = (): DecisionBrief => ({
  id: 'brief-1',
  investigationId: 'investigation-1',
  question: investigation().question,
  version: 1,
  status: 'draft',
  authenticity: 'human_authored',
  freshness: 'current',
  readiness: 'draft',
  rowVersion: 1,
  versionId: 'brief-version-1',
  blockDocument: { schemaVersion: '1', blocks: [], noCounterEvidenceSearch: null },
  referenceSnapshot: { synthesisVersionId: 'synthesis-version-1', synthesisReviewId: 'review-1', claimVersionIds: ['claim-version-1'], claimReviewIds: ['claim-review-1'], claimEvidenceIds: ['link-1'], evidenceReviewIds: ['evidence-review-1'], evidenceIds: ['evidence-1'], contentVersionIds: ['content-1'] },
  templateVersion: 'brief-v1',
  humanEditDigest: 'sha256:test',
});

describe('presentAgentSession', () => {
  it('presents a frozen Investigation with no run as ready to start', () => {
    const presentation = presentAgentSession(investigation({ run: null, evidence: [], claims: [], events: [], status: 'draft' }));
    expect(presentation.statusLabel).toBe('Ready to start');
    expect(presentation.currentAction.title).toBe('Approved scope is ready');
    expect(presentation.canStart).toBe(true);
    expect(presentation.activity[0]?.title).toBe('Approved scope ready');
    expect(presentation.planSteps.find((step) => step.id === 'scope')?.status).toBe('completed');
  });

  it('maps a running ResearchRun to a real current step without percentage progress', () => {
    const presentation = presentAgentSession(investigation({ run: run({ state: 'running', latestSequence: 2 }), evidence: [], claims: [], events: [event(1, 'run.queued'), event(2, 'run.started')] }));
    expect(presentation.statusLabel).toBe('Running');
    expect(presentation.currentStepId).toBe('evidence');
    expect(presentation.currentAction.title).toBe('Glint is analyzing evidence');
    expect(JSON.stringify(presentation)).not.toMatch(/\d+%/);
  });

  it('projects raw events to stable product copy while retaining the technical event in Advanced data', () => {
    const presentation = presentAgentSession(investigation());
    expect(presentation.activity.map((item) => item.title)).toEqual(['Scope confirmed', 'Sources prepared', 'Evidence proposed', 'Findings proposed', 'Agent paused for review']);
    expect(presentation.activity[2]?.eventType).toBe('evidence.proposed');
    expect(presentation.advanced.currentInternalNode).toBe('require_human_review');
  });

  it('uses a safe fallback for an unknown event instead of parsing its message into UI state', () => {
    const presentation = presentAgentSession(investigation({ events: [event(1, 'provider.internal.changed', 'Opaque provider payload')] }));
    expect(presentation.activity[0]).toMatchObject({ title: 'Run activity recorded', summary: 'Opaque provider payload', eventType: 'provider.internal.changed' });
  });

  it('prioritizes proposed Evidence as the pending human gate', () => {
    const presentation = presentAgentSession(investigation());
    expect(presentation.statusLabel).toBe('Waiting for review');
    expect(presentation.pendingHumanAction).toMatchObject({ kind: 'review-evidence', actionLabel: 'Review evidence', count: 1 });
    expect(presentation.planSteps.find((step) => step.id === 'review-evidence')?.status).toBe('waiting');
  });

  it('moves to Findings review only after all Evidence is human-reviewed', () => {
    const presentation = presentAgentSession(investigation({ evidence: [evidence({ status: 'valid', latestReviewId: 'evidence-review-1' })] }));
    expect(presentation.pendingHumanAction).toMatchObject({ kind: 'review-findings', actionLabel: 'Review findings' });
    expect(presentation.artifacts.find((item) => item.type === 'evidence-proposal')?.statusLabel).toBe('Verified evidence');
  });

  it('maps deterministic and model-assisted modes without using raw enum copy', () => {
    expect(presentAgentSession(investigation()).modeLabel).toBe('Deterministic research');
    const modelPresentation = presentAgentSession(investigation({ allowCloudModel: true, run: run({ generationMethod: 'model', provider: 'DeepSeek', model: 'deepseek-chat' }) }));
    expect(modelPresentation.modeLabel).toBe('Model-assisted research');
    expect(modelPresentation.modelEgress).toMatchObject({ approved: true, provider: 'DeepSeek', model: 'deepseek-chat' });
  });

  it('summarizes approved scope from real source and content-version counts', () => {
    const presentation = presentAgentSession(investigation());
    expect(presentation.scopeSummary).toMatchObject({ sourceCount: 3, contentVersionCount: 12, sourceLabel: '3 approved sources', contentVersionLabel: '12 immutable content versions' });
  });

  it('shows only configured budget limits and never exposes an untrusted used-cost value', () => {
    const presentation = presentAgentSession(investigation());
    expect(presentation.budgetLimitLabel).toBe('Budget limit: $4.00 · 15 min');
    expect(JSON.stringify(presentation)).not.toContain('999.99');
    expect(JSON.stringify(presentation)).not.toContain('usedCost');
  });

  it('completes the Plan and exposes the real Decision Brief handoff', () => {
    const reviewedEvidence = evidence({ status: 'valid', latestReviewId: 'evidence-review-1' });
    const reviewedClaim = claim({ status: 'verified' });
    const presentation = presentAgentSession(investigation({ evidence: [reviewedEvidence], claims: [reviewedClaim], synthesis: synthesis(), status: 'completed' }), { brief: brief() });
    expect(presentation.statusLabel).toBe('Completed');
    expect(presentation.pendingHumanAction).toBeNull();
    expect(presentation.canOpenBrief).toBe(true);
    expect(presentation.planSteps.every((step) => step.status === 'completed')).toBe(true);
  });

  it('marks a failed Plan step and allows Retry without inventing retained artifacts', () => {
    const presentation = presentAgentSession(investigation({ run: run({ state: 'failed' }), evidence: [], claims: [], events: [event(1, 'run.queued'), event(2, 'run.started'), event(3, 'run.failed', 'Citation validation failed safely.')] }));
    expect(presentation.statusLabel).toBe('Failed');
    expect(presentation.canRetry).toBe(true);
    expect(presentation.planSteps.some((step) => step.status === 'failed')).toBe(true);
    expect(presentation.currentAction.outputLabel).toContain('0 evidence proposals');
  });

  it('visibly labels fixtures without changing authenticity', () => {
    const presentation = presentAgentSession(investigation(), { fixture: true });
    expect(presentation.fixtureLabel).toBe('Imported Demo Fixture');
    expect(presentation.authenticity).toBe('imported');
  });
});
