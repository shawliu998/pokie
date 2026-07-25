import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import liveFixtures from '../../../e2e/fixtures/quant-workspace-fixtures.json';
import type { QuantWorkspaceSnapshot } from '../../quant-domain';
import { ResearchCopilotContent } from './QuantOverviewWorkbench';
import { presentResearchCopilot } from './quant-presentation';
import { QuantStrategyLab } from './QuantStrategyLab';

function renderDecision(snapshot: QuantWorkspaceSnapshot) {
  return renderToStaticMarkup(
    <ResearchCopilotContent
      mode="live-decision"
      projection={presentResearchCopilot(snapshot)}
      snapshot={snapshot}
      recentEvents={[]}
      evidenceFocusActions={[]}
      busy={false}
      onAction={vi.fn()}
      onAsk={vi.fn()}
      onEvidenceFocus={vi.fn()}
    />,
  );
}

describe('Live Agent decision surface', () => {
  it('keeps the latest retained observation and explains the exact Observation → C adaptation', () => {
    const snapshot = structuredClone(liveFixtures['quant-validating']) as unknown as QuantWorkspaceSnapshot;
    snapshot.candidates = snapshot.candidates.map((candidate) => candidate.id === 'candidate-c'
      ? {
          ...candidate,
          evolution: {
            ...candidate.evolution!,
            origin: 'training_feedback',
            changeRationale: 'Widen the lookback after Candidate A showed the strongest train-only risk-adjusted result.',
            feedbackReferenceCandidateId: 'candidate-a',
            feedbackReferenceCandidateName: 'Candidate A · SMA 20/100',
          },
        }
      : candidate);

    const markup = renderDecision(snapshot);

    expect(markup).toMatch(/>Current<[\s\S]*>Observation<[\s\S]*>Next</);
    expect(markup).toContain('Initial hypothesis A');
    expect(markup).toContain('Initial hypothesis B');
    expect(markup).toContain('200-day breakout completed training');
    expect(markup).toContain('+16.3% annual return · 4.46 Sharpe · -15.5% drawdown.');
    expect(markup).toContain('The train-only observation from SMA 20/100 drove this adaptation.');
    expect(markup).toContain('Widen the lookback');
    expect(markup).not.toContain('Run details');
    expect(markup).not.toContain('Recent activity');
  });

  it('shows a truthful waiting state before the first retained observation', () => {
    const snapshot = liveFixtures['quant-generating-candidates'] as unknown as QuantWorkspaceSnapshot;
    const markup = renderDecision(snapshot);

    expect(markup).toContain('Initial hypothesis A · SMA 20/100');
    expect(markup).toContain('Candidate specifications in progress');
    expect(markup).toContain('No training result is available until the first bounded candidate completes.');
    expect(markup).toContain('Complete the initial A/B hypotheses');
    expect(markup).not.toContain('drove this adaptation');
  });

  it('keeps the Workspace candidate table secondary and labels live A/B roles without duplicating its decision summary', () => {
    const snapshot = liveFixtures['quant-running'] as unknown as QuantWorkspaceSnapshot;
    const markup = renderToStaticMarkup(
      <QuantStrategyLab
        snapshot={snapshot}
        selectedCandidateId=""
        onSelectCandidate={vi.fn()}
        variant="experiments"
        showLiveDecisionSummary={false}
      />,
    );

    expect(markup).toContain('Candidate progress');
    expect(markup).toContain('Initial hypothesis A');
    expect(markup).toContain('Initial hypothesis B');
    expect(markup).not.toContain('Current experiment');
    expect(markup).not.toContain('Latest result');
    expect(markup).not.toContain('Next step');
  });
});
