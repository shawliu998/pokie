import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { AgentActionCenter } from './AgentActionCenter';
import { AgentActivityFeed } from './AgentActivityFeed';
import { AgentArtifactCard } from './AgentArtifactCard';
import { AgentHeader } from './AgentHeader';
import { AgentPlanRail } from './AgentPlanRail';
import type { AgentSessionPresentation } from './agent-presentation';

const presentation: AgentSessionPresentation = {
  status: 'waiting-review',
  statusLabel: 'Waiting for review',
  statusTone: 'warning',
  goal: 'Should we prioritize permission preview for enterprise teams?',
  mode: 'deterministic',
  modeLabel: 'Deterministic research',
  authenticity: 'imported',
  fixtureLabel: 'Imported Demo Fixture',
  scopeSummary: { sourceCount: 3, contentVersionCount: 12, sourceLabel: '3 approved sources', contentVersionLabel: '12 immutable content versions', timeRange: { start: '2026-05-01T00:00:00Z', end: '2026-05-31T23:59:59Z' }, sourceNames: ['Customer feedback CSV', 'Glint GitHub', 'Competitor release RSS'] },
  budgetLimitLabel: 'Budget limit: $4.00 · 15 min',
  modelEgress: { approved: false, provider: null, model: null, willSend: 'Approved excerpts.', willNotSend: 'Credentials.' },
  planSteps: [
    { id: 'scope', owner: 'system', title: 'Confirming approved scope', description: 'Checks the frozen scope.', status: 'completed', artifactCount: 1, timestamp: '2026-05-31T12:00:00Z', needsAction: false, internalNode: 'validate_manifest' },
    { id: 'review-evidence', owner: 'human', title: 'Review evidence', description: 'Review every proposal.', status: 'waiting', artifactCount: 1, timestamp: null, needsAction: true, internalNode: 'require_human_review' },
  ],
  completedStepCount: 1,
  currentAction: { title: '1 evidence proposal needs your review', purpose: 'Open the immutable source.', inputLabel: '12 immutable content versions', outputLabel: '1 evidence proposal · 1 finding', userNeedLabel: 'Your review is required.' },
  pendingHumanAction: { kind: 'review-evidence', title: '1 evidence proposal needs your review', body: 'Open the immutable source before recording a decision.', actionLabel: 'Review evidence', count: 1 },
  activity: [{ id: 'event-1', title: 'Evidence proposed', summary: '1 evidence proposal was persisted.', timestamp: '2026-05-31T12:00:00Z', artifactCount: 1, eventType: 'evidence.proposed', sequence: 3, authenticity: 'imported' }],
  artifacts: [{ id: 'evidence-1', type: 'evidence-proposal', typeLabel: 'Evidence Proposal', statusLabel: 'Needs review', originLabel: 'Deterministic proposal', title: 'Supporting evidence', body: 'Permission previews would unblock our enterprise rollout.', relationshipLabel: '1 immutable source', authenticity: 'imported', primaryAction: 'review-evidence' }],
  currentStepId: 'review-evidence',
  canCancel: false,
  canStart: false,
  canRetry: false,
  canCreateBrief: false,
  canOpenBrief: false,
  advanced: { runId: 'run-1', scopeVersionId: 'scope-1', graphVersion: 'bounded-v1', latestSequence: 5, traceRef: null, promptRefs: [], currentInternalNode: 'require_human_review' },
};

describe('Agent Workspace components', () => {
  it('renders Header scope, fixture disclosure, mode, and limit without fake usage', () => {
    const markup = renderToStaticMarkup(<AgentHeader presentation={presentation} disabled={false} onCancel={vi.fn()} onRetry={vi.fn()} onCreateBrief={vi.fn()} onOpenBrief={vi.fn()} />);
    expect(markup).toContain('Imported Demo Fixture');
    expect(markup).toContain('3 approved sources');
    expect(markup).toContain('Budget limit: $4.00 · 15 min');
    expect(markup).not.toContain('of $4.00');
  });

  it('renders distinct Plan ownership and the active human gate', () => {
    const markup = renderToStaticMarkup(<AgentPlanRail steps={presentation.planSteps} currentStepId={presentation.currentStepId} completedStepCount={presentation.completedStepCount} />);
    expect(markup).toContain('owner-system');
    expect(markup).toContain('owner-human');
    expect(markup).toContain('Your action is required');
    expect(markup).not.toContain('%');
  });

  it('renders safe Activity projection with technical detail collapsed', () => {
    const markup = renderToStaticMarkup(<AgentActivityFeed presentation={presentation} />);
    expect(markup).toContain('Evidence proposed');
    expect(markup).toContain('Technical event');
    expect(markup).toContain('evidence.proposed');
    expect(markup).not.toContain('prompt');
  });

  it('renders only the currently valid Action Center operation', () => {
    const markup = renderToStaticMarkup(<AgentActionCenter presentation={presentation} disabled={false} onAction={vi.fn()} />);
    expect(markup).toContain('Review evidence');
    expect(markup).not.toContain('Continue');
  });

  it('renders an Artifact Card without exposing its UUID', () => {
    const artifact = presentation.artifacts[0];
    if (!artifact) throw new Error('Artifact fixture is required.');
    const markup = renderToStaticMarkup(<AgentArtifactCard artifact={artifact} disabled={false} onAction={vi.fn()} />);
    expect(markup).toContain('Evidence Proposal');
    expect(markup).toContain('Deterministic proposal');
    expect(markup).not.toContain('evidence-1');
  });
});
