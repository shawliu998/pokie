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

    expect(markup).toMatch(/>Now<[\s\S]*>Material observation<[\s\S]*>Why this experiment</);
    expect(markup).toContain('Agent adaptation C · 200-day breakout');
    expect(markup).toContain('200-day breakout completed training');
    expect(markup).toContain('+16.3% annual return · 4.46 Sharpe · -15.5% drawdown.');
    expect(markup).toContain('Based on SMA 20/100.');
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
    expect(markup).toContain('Why this experiment');
    expect(markup).toContain('Test a faster moving-average trend signal against buy and hold.');
    expect(markup).not.toContain('drove this adaptation');
  });

  it('keeps the Workspace candidate table secondary to one visible Agent decision', () => {
    const snapshot = structuredClone(liveFixtures['quant-running']) as unknown as QuantWorkspaceSnapshot;
    snapshot.events = [
      ...snapshot.events,
      {
        id: 'agent-move-decision',
        sequence: 100,
        type: 'agent.action_selected',
        timestamp: '2026-07-26T00:00:00Z',
        actor: 'agent',
        safeSummary: 'Test Candidate B after Candidate A retained positive training evidence.',
        action: 'run_backtest',
        expectedResult: 'Retained training metrics and trades for Candidate B.',
      },
      {
        id: 'agent-move-started',
        sequence: 101,
        type: 'tool.started',
        timestamp: '2026-07-26T00:00:01Z',
        actor: 'system',
        safeSummary: 'Training backtest started.',
        action: 'run_backtest',
      },
    ];
    const markup = renderToStaticMarkup(
      <QuantStrategyLab
        snapshot={snapshot}
        selectedCandidateId=""
        onSelectCandidate={vi.fn()}
        variant="experiments"
      />,
    );

    expect(markup).toContain('Agent loop · current decision');
    expect(markup).toContain('Candidate experiments');
    expect(markup).toContain('Initial hypothesis A');
    expect(markup).toContain('Initial hypothesis B');
    expect(markup).toContain('Observation');
    expect(markup).toContain('Why Qurio changed');
    expect(markup).toContain('Next action');
    expect(markup).toContain('Registered tool');
    expect(markup).toContain('Run training backtest');
    expect(markup).toContain('Retained training metrics and trades for Candidate B.');
    expect(markup).toContain('Tool observation · Running');
    expect(markup).toContain('The tool is running. Qurio has not retained an observation yet.');
    expect(markup).not.toContain('run_backtest</code>');
    expect(markup.match(/Agent loop · current decision/g)).toHaveLength(1);
  });
});
