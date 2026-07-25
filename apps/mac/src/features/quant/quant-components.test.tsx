import { renderToStaticMarkup } from 'react-dom/server';
import { createRoot } from 'react-dom/client';
import { act, StrictMode, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import liveFixtures from '../../../e2e/fixtures/quant-workspace-fixtures.json';
import { QuantActivityFeed, QuantArtifactCards, QuantKernelCheckCard, QuantRunMonitor } from './QuantActivity';
import { QuantDataPage } from './QuantDataPage';
import { QuantGoalComposer, quantDatasetReadyForAutoResearch } from './QuantGoalComposer';
import { QuantInspector } from './QuantInspector';
import { QuantMarketWorkspace } from './QuantMarketWorkspace';
import { QuantOverviewWorkbench, QuantUtilityFrame } from './QuantOverviewWorkbench';
import { QuantPlanRail } from './QuantPlanRail';
import { QuantPaperTradingPage } from './QuantPaperTradingPage';
import { presentQuantWorkspace, type QuantEvidenceFocusIntent } from './quant-presentation';
import { QuantRunsPage } from './QuantRunsPage';
import { QuantWorkspace, QuantWorkspaceLoading } from './QuantWorkspace';
import { QuantRuntimeSettings } from './QuantRuntimeSettings';
import { SessionRecovery } from '../session/SessionBoundary';
import { QuantGeneralizationPanel, QuantStrategyReport } from './QuantStrategyReport';
import { QuantTerminalDecision } from './QuantTerminalDecision';
import { QuantStrategyLab, StrategyPerformanceChart } from './QuantStrategyLab';
import { quantFixtureSnapshot } from './quant-fixtures';
import { createFixtureQuantApi, type QuantApi } from '../../quant-api';
import { parseQuantWorkspaceSnapshot } from '../../quant-workspace-parser';
import type { DatasetSnapshot, QuantCommand, QuantWorkspaceSnapshot } from '../../quant-domain';

const presentation = presentQuantWorkspace(quantFixtureSnapshot);
const legacyFixtureDataset = quantFixtureSnapshot.dataset.contract === 'legacy-daily-v1'
  ? quantFixtureSnapshot.dataset
  : (() => { throw new Error('The checked component fixture must remain a legacy daily dataset.'); })();
((globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean })).IS_REACT_ACT_ENVIRONMENT = true;
const datasetQuality = {
  schemaVersion: 'quant-data-quality-v1',
  policyVersion: 'ohlcv-quality-v1',
  status: 'warning' as const,
  verificationStatus: 'checked' as const,
  reportDigest: 'sha256:data-quality-report',
  datasetDigest: 'sha256:data-quality-dataset',
  barCount: 1564,
  calendarGapCount: 4,
  largestCalendarGapDays: 3,
  zeroVolumeBarCount: 2,
  priceJumpCount: 1,
  issues: [{ code: 'calendar_gap', severity: 'warning', message: 'Calendar gaps need an exchange calendar to interpret.', count: 4 }],
  notes: ['Input checks do not establish market-data authenticity.'],
};
const candidateNameForTest = (value: string) => value.replace(/^Candidate [A-Z] · /, '');

function robustnessReportSnapshot() {
  const snapshot = structuredClone(quantFixtureSnapshot);
  const report = snapshot.report!;
  report.generalization = {
    status: 'not_evaluated', reason: 'No fresh sealed holdout was evaluated.', selectedCandidateId: 'candidate-b',
    split: { method: 'chronological', ruleVersion: 'chronological-80-20-v1', trainBarCount: 800, holdoutBarCount: 200, cutoffDate: '2023-01-01', datasetId: snapshot.dataset.id, datasetDigest: snapshot.dataset.digest },
  };
  report.selectionDecision = { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' };
  const candidateMetrics = { totalReturnPct: 12, annualizedReturnPct: 8, maximumDrawdownPct: -6, sharpeRatio: 1.2, tradeCount: 9, winRatePct: 55, finalEquity: 11200 };
  const benchmarkMetrics = { totalReturnPct: 10, annualizedReturnPct: 7, maximumDrawdownPct: -8, sharpeRatio: 0.9, tradeCount: 1, winRatePct: 100, finalEquity: 11000 };
  report.robustnessSensitivity = {
    schemaVersion: 'robustness_sensitivity_v1', evaluationPartition: 'train', runId: snapshot.run.id, reportArtifactId: report.id,
    candidate: { candidateId: 'candidate-b', template: 'sma_crossover', parameters: { fast_window: 50, slow_window: 200 }, canonicalKey: 'a'.repeat(64) },
    finalTrainingComparison: { artifactId: 'fixture-validation', artifactDigest: snapshot.artifacts.find((item) => item.id === 'fixture-validation')!.digest },
    dataset: { datasetId: snapshot.dataset.id, datasetDigest: snapshot.dataset.digest }, interval: '1D', periodsPerYear: 252, runtimeDescriptorDigest: 'b'.repeat(64),
    trainingSplit: { identityKind: 'deterministic_legacy_split', ruleVersion: 'chronological-80-20-v1', trainingBarCount: 800, trainingStart: '2018-01-02', trainingEnd: '2022-12-30', trainingSplitDigest: 'c'.repeat(64), sealedSplitDigest: null },
    executionRuleVersion: 'quant-execution-cost-policy-v1', samplerRuleVersion: 'oat-parameter-neighborhood-v1',
    costScenarios: [
      { scenario: 'baseline_1x', multiplier: 1, feeRate: 0.001, slippageRate: 0.0005, candidateMetrics, benchmarkMetrics },
      { scenario: 'stressed_2x', multiplier: 2, feeRate: 0.002, slippageRate: 0.001, candidateMetrics, benchmarkMetrics },
      { scenario: 'stressed_4x', multiplier: 4, feeRate: 0.004, slippageRate: 0.002, candidateMetrics, benchmarkMetrics },
    ],
    parameterNeighbors: [{ parameterName: 'fast_window', direction: 'lower', parameters: { fast_window: 40, slow_window: 200 }, canonicalKey: 'd'.repeat(64), candidateMetrics }],
    kernelCallCount: 7,
  };
  return snapshot;
}

describe('Quant Workspace components', () => {
  it('moves a retained report candidate through a reviewable Paper order draft', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const research = structuredClone(quantFixtureSnapshot);
    research.report!.selectedCandidateId = 'candidate-b';
    await act(async () => {
      root.render(<QuantPaperTradingPage api={createFixtureQuantApi()} research={research} />);
      await Promise.resolve();
    });
    expect(container.textContent).toContain('Paper Trading');
    expect(container.textContent).toContain('$100,000.00');
    const review = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === 'Review draft');
    expect(review?.disabled).toBe(false);
    await act(async () => {
      review?.click();
      await new Promise((resolve) => globalThis.setTimeout(resolve, 0));
    });
    expect(container.textContent).toContain('draft');
    expect(container.textContent).toContain('Submit');
    expect(container.textContent).toContain('Cancel');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('keeps managed runtime controls inside the native settings destination and locks them for an active run', () => {
    const active = structuredClone(quantFixtureSnapshot);
    active.run.state = 'running_experiments';
    const native = renderToStaticMarkup(<QuantRuntimeSettings snapshot={active} nativeRuntime />);
    const browser = renderToStaticMarkup(<QuantRuntimeSettings snapshot={active} nativeRuntime={false} />);
    expect(native).toContain('Current run');
    expect(native).toContain(active.run.provider);
    expect(native).toContain('Managed local runtime');
    expect(native).toContain('Finish, cancel, or open a terminal run');
    expect(native).toContain('disabled=""');
    expect(browser).not.toContain('Managed local runtime');
  });

  it('shows local startup only in the native session recovery path', () => {
    const reconnect = vi.fn(async () => undefined);
    const native = renderToStaticMarkup(<SessionRecovery failure={null} native onReconnect={reconnect} />);
    const browser = renderToStaticMarkup(<SessionRecovery failure={null} native={false} onReconnect={reconnect} />);
    expect(native).toContain('Start local runtime');
    expect(native).toContain('Start &amp; connect');
    expect(browser).not.toContain('Start local runtime');
  });

  it('keeps the workspace geometry stable during initial and slow API loading', () => {
    const initial = renderToStaticMarkup(<QuantWorkspaceLoading onRetry={vi.fn()} />);
    const slow = renderToStaticMarkup(<QuantWorkspaceLoading slow onRetry={vi.fn()} />);
    expect(initial).toContain('quant-boot-layout');
    expect(initial).toContain('Connecting to the local runtime');
    expect(slow).toContain('Still waiting for the local API');
    expect(slow).toContain('No action is required');
    expect(slow).not.toContain('spinner');
  });

  it('makes the run conclusion primary and keeps audit identifiers behind disclosure', () => {
    const markup = renderToStaticMarkup(<QuantRunsPage api={createFixtureQuantApi()} snapshot={quantFixtureSnapshot} onOpenRun={vi.fn()} onOpenReport={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(markup).toContain('Sealed holdout pending');
    expect(markup).toContain('Training annual return');
    expect(markup).toContain('Training max drawdown');
    expect(markup).toContain('Selected candidate');
    expect(markup).toContain('Run audit record');
    expect(markup).toContain('New research');
    expect(markup).toContain('Open decision');
    expect(markup.indexOf('Open decision')).toBeLessThan(markup.indexOf('New research'));
    expect(markup).not.toContain('quant-run-state');
    expect(markup).not.toContain('text-transform:uppercase');
  });

  it('exposes the primary research views as a keyboard-oriented tab set', () => {
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={quantFixtureSnapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(markup).toContain('role="tablist"');
    expect(markup).toContain('id="pq-workspace-tab-overview"');
    expect(markup).toContain('aria-selected="true"');
    expect(markup).toContain('id="pq-workspace-panel-overview"');
    expect(markup).toContain('aria-labelledby="pq-workspace-tab-overview"');
    expect(markup).toContain('class="quant-research-table"');
    expect(markup).toContain('Sort by Annual return');
  });

  it('moves the same Copilot hierarchy into the main column in compact layout', () => {
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={quantFixtureSnapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} compactLayout />);
    expect(markup).toContain('pq-copilot-content is-compact');
    expect(markup).toContain('>Current<');
    expect(markup).toContain('>Observation<');
    expect(markup).toContain('>Next<');
    expect(markup).not.toContain('aria-label="Research Copilot"');
  });

  it('distills the terminal Research Copilot into non-duplicative run context', () => {
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={quantFixtureSnapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(markup).toContain('>Current<');
    expect(markup).toContain('>Observation<');
    expect(markup).toContain('>Next<');
    expect(markup).toContain('Run details');
    expect(markup).toContain('pq-copilot is-context');
    expect(markup.match(/Sealed holdout pending/g)).toHaveLength(2);
    expect(markup.match(/>New research</g)).toHaveLength(1);
    expect(markup).toMatch(/pq-copilot-section is-current[\s\S]*pq-copilot-section is-observation[\s\S]*pq-copilot-section is-next/);
    expect(markup).not.toContain('Tool activity');
    expect(markup).not.toContain('<dt>Provider</dt>');
    expect(markup).not.toContain('immutable');
    expect(markup).not.toContain('Ask about this run…');
    expect(markup).not.toContain('pq-user-prompt');
  });

  it('shows the approved plan in the Overview before rail approval actions', () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.researchPlan = {
      candidateFamilies: ['sma_crossover', 'breakout'],
      selectionObjective: 'drawdown_control',
      completionCriteria: ['Backtest every candidate.', 'Compare completed candidates.'],
      objectiveSummary: 'Compare bounded trend candidates while controlling drawdown.',
    } as QuantWorkspaceSnapshot['researchPlan'];
    snapshot.run = {
      ...snapshot.run,
      state: 'waiting_plan_approval',
      legalCommands: ['approve_plan', 'request_plan_changes', 'cancel_run'],
    };
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(markup).toContain('Research plan awaiting approval');
    expect(markup).toContain('Plan for approval');
    expect(markup).toContain('Supported · Legacy plan');
    expect(markup).toContain('Legacy retained plan predates strategy-scope classification');
    expect(markup).toContain('Compare bounded trend candidates while controlling drawdown.');
    expect(markup).toContain(`${snapshot.dataset.symbol} · ${snapshot.scope.interval}`);
    expect(markup).toContain(`${snapshot.scope.dateRange.start} — ${snapshot.scope.dateRange.end}`);
    expect(markup).toContain('10 bps fee + 5 bps slippage per fill');
    expect(markup).toContain('Moving-average trend · Price breakout');
    expect(markup).toContain('Drawdown control');
    expect(markup).toContain('Backtest every candidate. Compare completed candidates.');
    expect(markup).toContain(`${snapshot.run.maxAgentIterations} Agent actions`);
    expect(markup).toContain(`${snapshot.limits.maxExperiments} experiments`);
    expect(markup).toContain(`${snapshot.limits.maxRepairAttempts} repairs per experiment`);
    expect(markup.indexOf('Research plan awaiting approval')).toBeLessThan(markup.indexOf('>Approve &amp; run<'));
    expect(markup.indexOf('Research plan awaiting approval')).toBeLessThan(markup.indexOf('>Request changes<'));
  });

  it('makes a bounded proxy explicit and requires confirmation before Qurio runs experiments', () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.researchPlan = {
      candidateFamilies: ['rsi_mean_reversion'],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Backtest every candidate.', 'Compare completed candidates.'],
      objectiveSummary: 'Test the requested momentum idea through a bounded registered proxy.',
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'bounded_proxy',
        reason: 'The exact MACD and volatility-filter request is not available as a registered strategy.',
        proxyDescription: 'Use RSI mean reversion as a bounded momentum proxy on the selected OHLCV bars.',
        excludedBehaviors: ['Exact MACD signal parity', 'ATR-sized positions'],
      },
    };
    snapshot.run = {
      ...snapshot.run,
      mode: 'auto_research',
      state: 'waiting_plan_approval',
      legalCommands: ['approve_plan', 'request_plan_changes', 'cancel_run'],
    };
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(markup).toContain('Strategy scope: Bounded proxy');
    expect(markup).toContain('Review the bounded proxy');
    expect(markup).toContain('Use RSI mean reversion as a bounded momentum proxy');
    expect(markup).toContain('Exact MACD signal parity');
    expect(markup).toContain('ATR-sized positions');
    expect(markup).toContain('Review this plan before Qurio runs experiments.');
    expect(markup).toContain('>Approve &amp; run<');
    expect(markup.indexOf('Bounded proxy')).toBeLessThan(markup.indexOf('>Approve &amp; run<'));
  });

  it('shows unsupported scope without exposing Approve or Ask even when a malformed command list includes them', () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.researchPlan = {
      candidateFamilies: [],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Revise the request before experiments begin.'],
      objectiveSummary: 'Rank a multi-asset long-short portfolio.',
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'unsupported',
        reason: 'The current runtime supports single-asset Long/Cash bar strategies only.',
        excludedBehaviors: ['Short positions', 'Cross-asset ranking'],
      },
    };
    snapshot.run = {
      ...snapshot.run,
      state: 'waiting_plan_approval',
      legalCommands: ['ask', 'approve_plan', 'request_plan_changes', 'cancel_run'],
    };
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(markup).toContain('Strategy scope: Not supported');
    expect(markup).toContain('Change the research request');
    expect(markup).toContain('None — the request is outside the registered strategy boundary');
    expect(markup).toContain('Short positions');
    expect(markup).toContain('Cross-asset ranking');
    expect(markup).toContain('>Request changes<');
    expect(markup).toContain('>Cancel run<');
    expect(markup).not.toContain('>Approve plan<');
    expect(markup).not.toContain('Ask about this run…');
  });

  it('shows only the compact prior-research count line in the existing context bar', () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.researchMemory = { sourceRunCount: 2, testedCandidateCount: 6 };
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(markup).toContain('Prior research: 2 runs · 6 strategies considered');
    expect(markup).not.toContain('sourceRunIds');
  });

  it('shows the evidence question composer only when ask is legal', () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.run = { ...snapshot.run, state: 'running_experiments', legalCommands: ['ask'] };
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(markup).toContain('Ask about this run…');
    expect(markup).toContain('Ask about retained evidence');
    expect(markup).toContain('>Ask<');
    expect(markup).toContain('pq-copilot is-interactive');
    expect(markup).not.toContain('This run is immutable');
    expect(markup.match(/Research is still in progress/g)).toHaveLength(1);
  });

  it('connects Copilot actions and Ask to the existing handlers and locks them while busy', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onCommand = vi.fn();
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.report = null;
    snapshot.run = { ...snapshot.run, state: 'waiting_plan_approval', legalCommands: ['approve_plan', 'request_plan_changes', 'cancel_run', 'ask'] };
    await act(async () => { root.render(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={onCommand} />); });
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('.pq-copilot-actions button')].find((button) => button.textContent === 'Approve & run')?.click(); });
    expect(onCommand).toHaveBeenCalledWith('approve_plan');
    const ask = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Ask about this run"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(ask, 'What changed in training?');
      ask.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { container.querySelector<HTMLFormElement>('.pq-copilot-composer')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    expect(onCommand).toHaveBeenCalledWith('ask', { question: 'What changed in training?' });
    await act(async () => { root.render(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={onCommand} busy />); });
    expect([...container.querySelectorAll<HTMLButtonElement>('.pq-copilot-actions button')].every((button) => button.disabled)).toBe(true);
    expect(container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Ask about this run"]')?.disabled).toBe(true);
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('collects an explicit plan change before requesting a revised plan', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onCommand = vi.fn();
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.report = null;
    snapshot.run = { ...snapshot.run, state: 'waiting_plan_approval', legalCommands: ['approve_plan', 'request_plan_changes', 'cancel_run'] };
    await act(async () => { root.render(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={onCommand} />); });
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('.pq-copilot-actions button')].find((button) => button.textContent === 'Request changes')?.click(); });
    const input = container.querySelector<HTMLTextAreaElement>('.pq-plan-change-form textarea')!;
    expect(input).not.toBeNull();
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(input, 'Focus on mean reversion.');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { container.querySelector<HTMLFormElement>('.pq-plan-change-form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    expect(onCommand).toHaveBeenCalledWith('request_plan_changes', { changeRequest: 'Focus on mean reversion.' });
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('keeps historical legacy and market workspaces mutation-free while preserving Return latest', () => {
    for (const contract of ['legacy-daily-v1', 'market-v2-public'] as const) {
      const snapshot = structuredClone(quantFixtureSnapshot);
      snapshot.run = { ...snapshot.run, contract, legalCommands: ['ask', 'approve_plan', 'cancel_run', 'retry_run'] };
      const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} onContinueResearch={vi.fn()} onReturnLatest={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} isHistorical />);
      expect(markup).toContain('Historical evidence is read-only');
      expect(markup).toContain('>Return to latest<');
      expect(markup).not.toContain('Ask about this run…');
      expect(markup).not.toContain('>Approve plan<');
      expect(markup).not.toContain('>Cancel run<');
      expect(markup).not.toContain('>Continue research<');
    }
  });

  it('keeps historical Evidence Focus local and mutation-free', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onCommand = vi.fn();
    const onEvidenceFocus = vi.fn();
    const snapshot = structuredClone(quantFixtureSnapshot);

    await act(async () => {
      root.render(<QuantOverviewWorkbench snapshot={snapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} onReturnLatest={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={onCommand} onEvidenceFocus={onEvidenceFocus} isHistorical />);
    });
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Open max drawdown')?.click();
    });
    expect(onEvidenceFocus).toHaveBeenCalledWith(expect.objectContaining({
      runId: snapshot.run.id,
      candidateId: 'candidate-b',
      destination: 'analysis',
      target: 'drawdown',
    }));
    expect(onCommand).not.toHaveBeenCalled();

    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('uses state-specific Overview actions instead of calling every state evidence review', () => {
    const renderState = (state: QuantWorkspaceSnapshot['run']['state'], legalCommands: QuantCommand[] = []) => renderToStaticMarkup(<QuantOverviewWorkbench snapshot={{ ...quantFixtureSnapshot, report: null, run: { ...quantFixtureSnapshot.run, state, legalCommands } }} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(renderState('draft', ['generate_plan'])).toContain('>Generate plan<');
    expect(renderState('running_experiments', ['cancel_run'])).toContain('>Cancel run<');
    expect(renderState('loading_data', ['cancel_run'])).toContain('>Cancel run<');
    expect(renderState('generating_candidates', ['cancel_run'])).toContain('>Cancel run<');
    expect(renderState('generating_report', ['cancel_run'])).toContain('>Open analysis<');
    expect(renderState('waiting_for_review', ['complete_review'])).toContain('>Complete review<');
    expect(renderState('failed', ['retry_run'])).toContain('>Retry run<');
    expect(renderState('cancelled', ['retry_run'])).toContain('>Retry run<');
    expect(renderState('draft')).not.toContain('>Open plan<');
  });

  it('shows stable domain progress for transient phases instead of generic skeleton bars', () => {
    const renderState = (state: 'loading_data' | 'generating_candidates' | 'generating_report') => renderToStaticMarkup(<QuantOverviewWorkbench snapshot={{ ...quantFixtureSnapshot, report: null, run: { ...quantFixtureSnapshot.run, state } }} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(renderState('loading_data')).toContain('Dataset verification');
    expect(renderState('generating_candidates')).toContain('Candidate preparation');
    expect(renderState('generating_report')).toContain('Report assembly');
    expect(renderState('loading_data')).toContain('aria-label="Current run progress"');
    expect(renderState('loading_data')).not.toContain('skeleton');
  });

  it('leads with persisted strategy performance and keeps market prices out of the result chart', () => {
    const markup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={quantFixtureSnapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(markup).toContain('Strategy vs benchmark');
    expect(markup).toContain('aria-label="SMA 50/200 equity compared with benchmark"');
    expect(markup).toContain('Key strategy comparison');
    expect(markup).toContain('Candidate snapshot');
    expect(markup).toContain('Positive-return folds');
    expect(markup).toContain('Sealed holdout');
    expect(markup).toContain('Vs benchmark');
    expect(markup).toContain('Sort by Sharpe');
    expect(markup).not.toContain('Pinned market path');
    expect(markup).not.toContain('Price change');
    expect(markup).not.toContain('market price and drawdown');
    expect(markup).not.toContain('<th>Provider</th>');
    expect(markup).not.toContain('pq-panel');
    expect(markup).not.toContain('Equity &amp; drawdown');
    expect(markup).not.toContain('Net return');
    expect(markup).not.toContain('Win rate');
    expect(markup).not.toContain('Research evaluation stages');
  });

  it('uses the shared candidate selection and switches the overview performance view', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onSelectCandidate = vi.fn();
    await act(async () => {
      root.render(<QuantOverviewWorkbench snapshot={quantFixtureSnapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={onSelectCandidate} onCommand={vi.fn()} />);
    });
    expect(container.querySelector('.pq-results-performance')?.textContent).toContain('SMA 50/200');
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('.pq-candidate-comparison button[aria-pressed="false"]')][0]?.click();
    });
    expect(onSelectCandidate).toHaveBeenCalledWith('candidate-a');
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('.pq-results-view-tabs button')].find((button) => button.textContent === 'Drawdown')?.click();
    });
    expect(container.querySelector('.pq-results-chart figure')?.getAttribute('aria-label')).toContain('drawdown compared with benchmark');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('inspects shared strategy performance by pointer and bounded keyboard selection', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const series = quantFixtureSnapshot.performanceSeries.find((item) => item.id === 'candidate-b')!;
    await act(async () => { root.render(<StrategyPerformanceChart snapshot={quantFixtureSnapshot} selectedCandidateId="candidate-b" view="equity" />); });
    const plot = container.querySelector<HTMLElement>('.pq-strategy-plot')!;
    const readout = container.querySelector<HTMLElement>('.pq-strategy-inspection')!;
    plot.getBoundingClientRect = () => ({ left: 0, top: 0, width: 760, height: 250, right: 760, bottom: 250, x: 0, y: 0, toJSON: () => ({}) });
    expect(plot.getAttribute('aria-label')).toContain('Use Left and Right arrows');
    expect(readout.textContent).toContain(series.points.at(-1)!.date);
    await act(async () => { plot.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: 0 })); });
    expect(readout.textContent).toContain(series.points[0]!.date);
    await act(async () => { plot.dispatchEvent(new MouseEvent('pointerout', { bubbles: true })); });
    expect(readout.textContent).toContain(series.points.at(-1)!.date);
    await act(async () => { plot.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Home' })); });
    expect(readout.textContent).toContain(series.points[0]!.date);
    await act(async () => { plot.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'ArrowRight' })); });
    expect(readout.textContent).toContain(series.points[1]!.date);
    await act(async () => { plot.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'ArrowLeft' })); });
    expect(readout.textContent).toContain(series.points[0]!.date);
    expect(readout.textContent).toContain('Difference');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('keeps a single candidate point readable without inventing a benchmark or line', () => {
    const candidateSeries = quantFixtureSnapshot.performanceSeries.find((item) => item.id === 'candidate-b')!;
    const candidateOnly = {
      ...quantFixtureSnapshot,
      performanceSeries: [{ ...candidateSeries, points: candidateSeries.points.slice(0, 1) }],
    };
    const markup = renderToStaticMarkup(<StrategyPerformanceChart snapshot={candidateOnly} selectedCandidateId="candidate-b" view="equity" />);
    expect(markup).toContain('aria-label="SMA 50/200 equity performance"');
    expect(markup).toContain('>Strategy<');
    expect(markup).not.toContain('>Benchmark<');
    expect(markup).not.toContain('>Difference<');
    expect(markup).not.toContain('pq-strategy-line is-candidate');
    expect(markup).toContain('pq-strategy-marker is-candidate');
  });

  it('degrades terminal outcomes without inventing a strategy curve', () => {
    const failed = liveFixtures['quant-failed-safe'] as unknown as QuantWorkspaceSnapshot;
    const failedMarkup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={failed} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(failedMarkup).toContain('Research stopped before a decision');
    expect(failedMarkup).toContain('No strategy result');
    expect(failedMarkup).toContain('Performance series unavailable');
    expect(failedMarkup).toContain('>New research<');
    expect(failedMarkup).not.toContain('pq-strategy-line is-candidate');

    const noViable = liveFixtures['quant-no-viable-candidate'] as unknown as QuantWorkspaceSnapshot;
    const noViableMarkup = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={noViable} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId={noViable.candidates[0]?.id ?? ''} onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(noViableMarkup).toContain('No candidate passed validation');
    expect(noViableMarkup).toContain('Candidate snapshot');
    expect(noViableMarkup).toContain('>New research<');
    expect(noViableMarkup).not.toContain('Retained candidate');
  });

  it('renders the strategy comparison from persisted metrics and performance series', () => {
    const markup = renderToStaticMarkup(<QuantStrategyLab snapshot={quantFixtureSnapshot} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} variant="experiments" />);
    expect(markup).toContain('Candidate comparison');
    expect(markup).toContain('SMA 50/200');
    expect(markup).toContain('Buy and hold');
    expect(markup).toContain('Strategy analysis views');
    expect(markup).toContain('aria-label="SMA 50/200 equity compared with benchmark"');
    expect(markup).toContain('pq-strategy-line is-candidate');
    expect(markup).toContain('pq-strategy-line is-benchmark');
  });

  it('renders the complete adaptation Decision Ledger without holdout evidence', () => {
    const feedbackSnapshot: QuantWorkspaceSnapshot = {
      ...quantFixtureSnapshot,
      report: quantFixtureSnapshot.report ? {
        ...quantFixtureSnapshot.report,
        selectionDecision: {
          basis: 'robustness_override',
          selectedCandidateId: 'candidate-c',
          reason: 'walk_forward_stability',
          referenceCandidateId: 'candidate-a',
        },
        generalization: {
          ...quantFixtureSnapshot.report.generalization!,
          selectedCandidateId: 'candidate-a',
          reason: 'SECRET HOLDOUT REASON',
        },
      } : null,
      candidates: quantFixtureSnapshot.candidates.map((candidate) => candidate.id === 'candidate-c' ? {
        ...candidate,
        evolution: {
          hypothesis: 'Reduce drawdown while preserving the breakout signal.',
          origin: 'training_feedback',
          changeRationale: 'Widen the slow window after the initial training comparison showed unstable turnover.',
          feedbackReferenceCandidateId: 'candidate-a',
          feedbackReferenceCandidateName: 'Candidate A · SMA 20/100',
          comparisonRank: 2,
          comparisonCandidateCount: 3,
          selectionReason: 'Selected by a server-validated walk-forward stability override after ranking 2 of 3.',
        },
      } : candidate),
    };
    const experiments = renderToStaticMarkup(<QuantStrategyLab snapshot={feedbackSnapshot} selectedCandidateId="candidate-c" onSelectCandidate={vi.fn()} variant="experiments" />);
    expect(experiments).toContain('Decision ledger');
    expect(experiments).toContain('A/B → Observation → Candidate C → Final choice');
    expect(experiments).toContain('SMA 20/100');
    expect(experiments).toContain('SMA 50/200');
    expect(experiments).toContain('Training observation → Candidate C');
    expect(experiments).toContain('Widen the slow window');
    expect(experiments).toContain('Final choice');
    expect(experiments).not.toContain('SECRET HOLDOUT REASON');
    const inspectingAlternative = renderToStaticMarkup(<QuantStrategyLab snapshot={feedbackSnapshot} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} variant="experiments" />);
    expect(inspectingAlternative).toContain('Inspecting strategy · SMA 50/200');
    expect(inspectingAlternative).toMatch(/<dt>Final choice<\/dt><dd>200-day breakout/);
    expect(inspectingAlternative).not.toMatch(/<dt>Final choice<\/dt><dd>SMA 50\/200/);
    const stoppedSnapshot = structuredClone(feedbackSnapshot);
    stoppedSnapshot.candidates = stoppedSnapshot.candidates.slice(0, 2);
    stoppedSnapshot.report = {
      ...stoppedSnapshot.report!,
      selectionDecision: {
        ...stoppedSnapshot.report!.selectionDecision!,
        selectedCandidateId: 'candidate-a',
      },
      generalization: {
        ...stoppedSnapshot.report!.generalization!,
        selectedCandidateId: 'candidate-a',
      },
      iterationStop: {
        reason: 'insufficient_action_budget',
        referenceCandidateId: 'candidate-a',
      },
    };
    const stopped = renderToStaticMarkup(<QuantStrategyLab snapshot={stoppedSnapshot} selectedCandidateId="candidate-a" onSelectCandidate={vi.fn()} variant="experiments" />);
    expect(stopped).toContain('A/B → Observation → Stop → Final choice');
    expect(stopped).toContain('Stopped before Candidate C');
    expect(stopped).toContain('remaining action budget');
    const reportSnapshot = {
      ...feedbackSnapshot,
      report: feedbackSnapshot.report ? { ...feedbackSnapshot.report, generalization: undefined } : null,
    };
    const report = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={reportSnapshot} candidates={presentQuantWorkspace(reportSnapshot).candidates} decision={presentQuantWorkspace(reportSnapshot).decision} selectedCandidateId="candidate-c" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(report).toContain('Research hypothesis');
    expect(report).toContain('Training selection basis');
    expect(report).toContain('walk-forward stability override');
    expect(report).toContain('Selected by a server-validated walk-forward stability override');
  });

  it('renders the verified replan repair row only for the adapted Candidate C', () => {
    const repairSnapshot: QuantWorkspaceSnapshot = {
      ...quantFixtureSnapshot,
      report: quantFixtureSnapshot.report ? {
        ...quantFixtureSnapshot.report,
        selectionDecision: {
          basis: 'approved_objective_rank',
          selectedCandidateId: 'candidate-c',
        },
        generalization: {
          ...quantFixtureSnapshot.report.generalization!,
          selectedCandidateId: 'candidate-a',
          reason: 'SECRET HOLDOUT REASON',
        },
      } : null,
      candidates: quantFixtureSnapshot.candidates.map((candidate) => candidate.id === 'candidate-c' ? {
        ...candidate,
        evolution: {
          hypothesis: 'Reduce drawdown while preserving the breakout signal.',
          origin: 'training_feedback',
          changeRationale: 'Widen the slow window after the initial training comparison showed unstable turnover.',
          feedbackReferenceCandidateId: 'candidate-a',
          feedbackReferenceCandidateName: 'Candidate A · SMA 20/100',
          comparisonRank: 1,
          comparisonCandidateCount: 3,
          selectionReason: 'Selected as rank 1 of 3 under the approved risk-adjusted return objective; sealed holdout evidence was not available at selection time.',
          replanRepair: {
            rejectedAction: 'refine_parameters',
            correctedAction: 'switch_approved_family',
            retainedInputs: true,
            outcome: 'candidate_created',
          },
        },
      } : candidate),
    };
    const experiments = renderToStaticMarkup(<QuantStrategyLab snapshot={repairSnapshot} selectedCandidateId="candidate-c" onSelectCandidate={vi.fn()} variant="experiments" />);
    expect(experiments).toContain('Agent request correction');
    expect(experiments).toContain('Refine parameters');
    expect(experiments).toContain('Switch approved family');
    expect(experiments).toContain('changed only the action');
    expect(experiments).not.toContain('SECRET HOLDOUT REASON');
    const withoutRepair: QuantWorkspaceSnapshot = {
      ...repairSnapshot,
      candidates: repairSnapshot.candidates.map((candidate) => candidate.id === 'candidate-c' ? {
        ...candidate,
        evolution: { ...candidate.evolution!, replanRepair: undefined },
      } : candidate),
    };
    const noRepairMarkup = renderToStaticMarkup(<QuantStrategyLab snapshot={withoutRepair} selectedCandidateId="candidate-c" onSelectCandidate={vi.fn()} variant="experiments" />);
    expect(noRepairMarkup).not.toContain('Agent request correction');
  });

  it('uses Strategy revisions for the repair budget and Holdout annual return in summaries', () => {
    const monitor = renderToStaticMarkup(<QuantRunMonitor snapshot={quantFixtureSnapshot} presentation={presentQuantWorkspace(quantFixtureSnapshot)} onAction={vi.fn()} isPolling={false} />);
    expect(monitor).toContain('Strategy revisions');
    expect(monitor).not.toContain('>Repairs<');

    const overview = renderToStaticMarkup(<QuantOverviewWorkbench snapshot={quantFixtureSnapshot} activeTab="overview" onTabChange={vi.fn()} onRunResearch={vi.fn()} onOpenAnalysis={vi.fn()} onOpenReport={vi.fn()} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onCommand={vi.fn()} />);
    expect(overview).toContain('Holdout annual return');
    expect(overview).not.toContain('>Holdout return<');

    const reportSnapshot = robustnessReportSnapshot();
    const report = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={reportSnapshot} candidates={presentQuantWorkspace(reportSnapshot).candidates} decision={presentQuantWorkspace(reportSnapshot).decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(report).toContain('Holdout annual return');
    expect(report).not.toContain('>Holdout return<');
  });

  it('shares candidate selection and exposes non-chart analysis views', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onSelectCandidate = vi.fn();
    await act(async () => {
      root.render(<QuantStrategyLab snapshot={quantFixtureSnapshot} selectedCandidateId="candidate-b" onSelectCandidate={onSelectCandidate} variant="experiments" />);
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>('button[aria-pressed="false"]')?.click();
    });
    expect(onSelectCandidate).toHaveBeenCalledTimes(1);
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((button) => button.textContent === 'Market')?.click();
    });
    expect(container.textContent).toContain('SMA 50/200 trade context');
    expect(container.textContent).toContain('Select a trade to inspect it against the retained market path');
    expect(container.querySelectorAll('.quant-trade-marker').length).toBe(4);
    expect(container.querySelectorAll('.quant-trade-marker.is-highlighted').length).toBe(2);
    expect(container.querySelector('.pq-market-trade-inspection')?.textContent).toContain('2018-10-09');
    await act(async () => {
      container.querySelectorAll<HTMLButtonElement>('.pq-market-trade-table .quant-table-link')[1]?.click();
    });
    expect(container.querySelector('.pq-market-trade-inspection')?.textContent).toContain('2020-08-17');
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((button) => button.textContent === 'Period returns')?.click();
    });
    expect(container.textContent).toContain('Calendar-period returns');
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((button) => button.textContent === 'Trades')?.click();
    });
    expect(container.textContent).toContain('SMA 50/200 trades');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it.each([
    ['quant-loading-data', 'Loading research data'],
    ['quant-generating-candidates', 'Generating candidates'],
    ['quant-running', 'Running experiments'],
    ['quant-repairing', 'Repairing candidate'],
    ['quant-validating', 'Validating results'],
    ['quant-generating-report', 'Building report'],
  ] as const)('renders a truthful live workbench for %s', (fixtureName, phaseLabel) => {
    const snapshot = liveFixtures[fixtureName] as unknown as QuantWorkspaceSnapshot;
    const markup = renderToStaticMarkup(<QuantStrategyLab snapshot={snapshot} selectedCandidateId="" onSelectCandidate={vi.fn()} variant="experiments" />);
    expect(markup).toContain(phaseLabel);
    expect(markup).toContain('Current experiment');
    expect(markup).toContain('Latest result');
    expect(markup).toContain('Candidate progress');
    expect(markup).toContain('Next step');
    expect(markup).not.toMatch(/0%/);
  });

  it('shows persisted running and completed candidate data without parsing activity copy', () => {
    const snapshot = liveFixtures['quant-running'] as unknown as QuantWorkspaceSnapshot;
    const markup = renderToStaticMarkup(<QuantStrategyLab snapshot={snapshot} selectedCandidateId="" onSelectCandidate={vi.fn()} variant="experiments" />);
    expect(markup).toContain('SMA 50/200');
    expect(markup).toContain('SMA 20/100');
    expect(markup).toContain('+20.6%');
    expect(markup).toContain('5.78');
    expect(markup).toContain('Running');
  });

  it('keeps utility pages task-specific instead of adding disabled chat surfaces', () => {
    const settings = renderToStaticMarkup(<QuantUtilityFrame destination="settings" snapshot={quantFixtureSnapshot}><div>Settings body</div></QuantUtilityFrame>);
    const research = renderToStaticMarkup(<QuantUtilityFrame destination="new_research" snapshot={quantFixtureSnapshot}><div>Research body</div></QuantUtilityFrame>);
    const data = renderToStaticMarkup(<QuantUtilityFrame destination="data" snapshot={quantFixtureSnapshot}><div>Data body</div></QuantUtilityFrame>);
    expect(settings).not.toContain('complementary');
    expect(settings).toContain('Settings');
    expect(settings).not.toContain('<textarea');
    expect(research).toContain('Research preflight');
    expect(research).toContain('aria-label="Research boundary"');
    expect(research).toContain('Expanding windows');
    expect(research).not.toContain('Before you start');
    expect(research).not.toContain('pq-utility-card');
    expect(research).not.toContain('<textarea');
    expect(data).toContain('Dataset inspector');
    expect(data).toContain('Immutable identity');
    expect(data).toContain('<dt>Digest</dt>');
    expect(data).toContain('<dt>Schema</dt>');
    expect(data).not.toContain('<dt>Rows</dt>');
    expect(data).not.toContain('<dt>Coverage</dt>');
    expect(data).not.toContain('<dt>Quality</dt>');
    expect(data).not.toContain('<textarea');
  });

  it('replaces the dataset inspector with import guidance during data entry', () => {
    const data = renderToStaticMarkup(<QuantUtilityFrame destination="data" snapshot={quantFixtureSnapshot} dataImporting><div>Import form</div></QuantUtilityFrame>);
    expect(data).toContain('Import guide');
    expect(data).toContain('Validate before selection');
    expect(data).toContain('Server owned');
    expect(data).toContain('The current dataset remains selected until validation succeeds.');
    expect(data).not.toContain('Open metadata record');
  });

  it('keeps new-run modes focused and exposes execution boundaries progressively', () => {
    const markup = renderToStaticMarkup(<QuantGoalComposer snapshot={quantFixtureSnapshot} large onSubmit={vi.fn()} />);
    expect(markup).not.toContain('>Ask<');
    expect(markup).toContain('Plan first');
    expect(markup).not.toContain('Auto Research');
    expect(markup).toContain('Execution limits');
    expect(markup).toContain('Minimum history met');
    expect(markup).toContain('Research data');
    expect(markup).toContain('Research objective');
    expect(markup).toContain('Research range');
    expect(markup).toContain('aria-label="Research setup"');
    expect(markup).toContain('Available coverage');
    expect(markup).not.toContain('Goal Composer');
    expect(markup).not.toContain('token');
    expect(markup).not.toContain('cost');
    expect(markup).toContain('maxLength="2000"');
  });

  it('locks the goal composer while a command is pending', () => {
    const markup = renderToStaticMarkup(<QuantGoalComposer snapshot={quantFixtureSnapshot} large busy onSubmit={vi.fn()} />);
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain('Generating plan…');
    expect(markup).toContain('disabled=""');
  });

  it('can render a genuinely blank new-research draft', () => {
    const markup = renderToStaticMarkup(<QuantGoalComposer snapshot={quantFixtureSnapshot} initialGoal="" large onSubmit={vi.fn()} onStartNewRun={vi.fn()} />);
    expect(markup).toContain('<textarea aria-label="Research goal"');
    expect(markup).not.toContain(quantFixtureSnapshot.project.goal);
    expect(markup).toContain('Enter a research objective to continue.');
  });

  it('renders a locked source dataset and an explicit reason for continuation', () => {
    const markup = renderToStaticMarkup(<QuantGoalComposer snapshot={quantFixtureSnapshot} large refinement={{ projectId: 'project-source', parentRunId: 'run-source', seedCandidateId: 'candidate-b', candidateName: 'Risk-adjusted trend', sourceQuestion: 'Original source question.', sourceDateRange: { ...quantFixtureSnapshot.scope.dateRange }, summary: '+12.4% annual return · sealed holdout fail', initialReason: 'Address the retained sealed holdout failure with one bounded parameter change.' }} onCancelRefinement={vi.fn()} onSubmit={vi.fn()} onStartNewRun={vi.fn()} />);
    expect(markup).toContain('Continuing from Risk-adjusted trend');
    expect(markup).toContain('Refinements keep the source dataset');
    expect(markup).toContain('What should change?');
    expect(markup).toContain('Address the retained sealed holdout failure with one bounded parameter change.');
    expect(markup).toContain('Cancel continuation');
    expect(markup).toContain('aria-label="Research dataset" disabled=""');
  });

  it('starts terminal research through a new API-owned Run and honors the requested mode', () => {
    const selected = { ...legacyFixtureDataset, id: 'selected-dataset', name: 'Selected Dataset' };
    const markup = renderToStaticMarkup(<QuantGoalComposer snapshot={quantFixtureSnapshot} selectedDataset={selected} initialMode="auto_research" large onSubmit={vi.fn()} onStartNewRun={vi.fn()} />);
    expect(markup).toContain('aria-pressed="true" title="Prepare a reviewable plan before any experiment runs"');
    expect(markup).toContain('Generate plan');
    expect(markup).toContain(`${selected.symbol} · ${selected.dateRange.start} to ${selected.dateRange.end}`);
  });

  it('renders and submits a research-eligible 4h dataset with editable bounded UTC controls', async () => {
    const marketDataset: DatasetSnapshot = {
      contract: 'market-v2', id: 'market-dataset-4h', name: 'BTCUSDT 4 hour', symbol: 'BTCUSDT', interval: '4h',
      dateRange: { start: '2024-01-01T00:00:00+00:00', end: '2025-12-31T20:00:00+00:00' }, barCount: 4386,
      schemaVersion: 'quant-market-bars-v2', parserVersion: 'fixture-market-bars-v2', digest: `sha256:${'a'.repeat(64)}`,
      authenticity: 'synthetic_fixture', researchEligible: true, periodsPerYear: 2190, marketCalendar: '24x7', marketSession: 'continuous', timeZone: 'UTC',
      source: { kind: 'provider_fetch', fileName: null, sourceName: 'Deterministic public-v2 fixture', sourceReference: 'fixture://BTCUSDT/4h', normalizerVersion: 'fixture-market-bars-v2', retrievedAtUtc: '2026-07-22T00:00:00+00:00', requestedBarCount: 4386, returnedBarCount: 4386, retainedBarCount: 4386, closedDroppedCount: 0, deduplicatedCount: 0, terminationReason: 'requested_limit', targetSatisfied: true },
      quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'Contiguous fixture bars.' },
    };
    const markup = renderToStaticMarkup(<QuantGoalComposer snapshot={quantFixtureSnapshot} selectedDataset={marketDataset} initialMode="auto_research" large onSubmit={vi.fn()} onStartNewRun={vi.fn()} />);
    expect(markup).toContain('BTCUSDT · BTCUSDT 4 hour · 4h');
    expect(markup).toContain('2,190 periods/year');
    expect(markup).toContain('aria-label="Research start UTC"');
    expect(markup).toContain('type="datetime-local"');
    expect(markup).toContain('2024-01-01T00:00:00+00:00');
    expect(markup).toContain('UTC bounds are pinned to stored 4h bars');
    expect(markup).not.toContain('aria-label="Research start UTC" value="2024-01-01T00:00" readOnly');

    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onStartNewRun = vi.fn();
    await act(async () => {
      root.render(<QuantGoalComposer snapshot={quantFixtureSnapshot} selectedDataset={marketDataset} initialMode="auto_research" large onSubmit={vi.fn()} onStartNewRun={onStartNewRun} />);
    });
    const start = container.querySelector<HTMLInputElement>('input[aria-label="Research start UTC"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(start, '2024-03-01T00:00');
      start.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Generate plan')?.click();
    });
    expect(onStartNewRun).toHaveBeenCalledWith(
      'plan',
      expect.any(String),
      marketDataset,
      { start: '2024-03-01T00:00:00Z', end: marketDataset.dateRange.end },
      undefined,
      undefined,
    );
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('keeps a root market plan bounded to one reviewed run', async () => {
    const marketDataset: DatasetSnapshot = {
      contract: 'market-v2', id: 'market-loop-v2', name: 'BTCUSDT 4 hour', symbol: 'BTCUSDT', interval: '4h',
      dateRange: { start: '2024-01-01T00:00:00Z', end: '2024-04-09T20:00:00Z' }, barCount: 600,
      schemaVersion: 'quant-market-bars-v2', parserVersion: 'fixture-market-bars-v2', digest: `sha256:${'c'.repeat(64)}`,
      authenticity: 'synthetic_fixture', researchEligible: true, periodsPerYear: 2190, marketCalendar: '24x7', marketSession: 'continuous', timeZone: 'UTC',
      source: { kind: 'provider_fetch', fileName: null, sourceName: 'Fixture', sourceReference: 'fixture://BTCUSDT/4h', normalizerVersion: 'fixture-market-bars-v2', retrievedAtUtc: '2026-07-22T00:00:00Z', requestedBarCount: 600, returnedBarCount: 600, retainedBarCount: 600, closedDroppedCount: 0, deduplicatedCount: 0, terminationReason: 'requested_limit', targetSatisfied: true },
      quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'Contiguous fixture bars.' },
    };
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onStartNewRun = vi.fn();
    await act(async () => {
      root.render(<QuantGoalComposer snapshot={quantFixtureSnapshot} selectedDataset={marketDataset} initialMode="auto_research" large onSubmit={vi.fn()} onStartNewRun={onStartNewRun} />);
    });
    expect(container.textContent).not.toContain('After this run');
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Generate plan')?.click();
    });
    expect(onStartNewRun).toHaveBeenCalledWith(
      'plan', expect.any(String), marketDataset, marketDataset.dateRange,
      undefined, undefined,
    );
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('renders interval-aware ineligible market-dataset guidance for new research', () => {
    const marketDataset: DatasetSnapshot = {
      contract: 'market-v2', id: 'market-short-4h', name: 'BTCUSDT short 4 hour', symbol: 'BTCUSDT', interval: '4h',
      dateRange: { start: '2024-01-01T00:00:00Z', end: '2024-04-01T16:00:00Z' }, barCount: 547,
      schemaVersion: 'quant-market-bars-v2', parserVersion: 'fixture-market-bars-v2', digest: `sha256:${'d'.repeat(64)}`,
      authenticity: 'imported', researchEligible: false, periodsPerYear: 2190, marketCalendar: '24x7', marketSession: 'continuous', timeZone: 'UTC',
      source: { kind: 'csv_upload', fileName: 'btcusdt-4h-short.csv', sourceName: 'Research CSV', sourceReference: 'upload:btc-4h-short', normalizerVersion: 'fixture-market-bars-v2', retrievedAtUtc: null, requestedBarCount: null, returnedBarCount: null, retainedBarCount: null, closedDroppedCount: null, deduplicatedCount: null, terminationReason: null, targetSatisfied: null, submittedCsvDigest: `sha256:${'e'.repeat(64)}` },
      quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'Contiguous but too short for autonomous research.' },
    };
    const markup = renderToStaticMarkup(<QuantGoalComposer snapshot={quantFixtureSnapshot} selectedDataset={marketDataset} initialMode="auto_research" large onSubmit={vi.fn()} onStartNewRun={vi.fn()} />);
    expect(markup).toContain('548 consecutive 4h bars');
    expect(markup).toContain('stored and previewable');
  });

  it('renders provenance for the selected dataset carried by the inspect target', () => {
    const selected = { ...legacyFixtureDataset, id: 'selected-dataset', name: 'Selected Dataset', symbol: 'QQQ', digest: 'sha256:selected-dataset' };
    const markup = renderToStaticMarkup(<QuantInspector snapshot={quantFixtureSnapshot} presentation={presentation} target={{ kind: 'dataset', dataset: selected }} onClose={vi.fn()} />);
    expect(markup).toContain('Selected Dataset');
    expect(markup).toContain('selected-dataset');
    expect(markup).not.toContain(`<dd>${quantFixtureSnapshot.dataset.name}</dd>`);
  });

  it('does not enable Auto Research for a quality-blocked dataset', () => {
    expect(quantDatasetReadyForAutoResearch({
      ...legacyFixtureDataset,
      quality: { ...datasetQuality, status: 'blocked', verificationStatus: 'rejected' },
    })).toBe(false);
    expect(quantDatasetReadyForAutoResearch({
      contract: 'market-v2', id: 'blocked-market', name: 'Blocked 4h', symbol: 'BTCUSDT', interval: '4h',
      dateRange: { start: '2024-01-01T00:00:00+00:00', end: '2024-12-31T20:00:00+00:00' }, barCount: 2190,
      schemaVersion: 'quant-market-bars-v2', parserVersion: 'fixture-market-bars-v2', digest: `sha256:${'b'.repeat(64)}`,
      authenticity: 'synthetic_fixture', researchEligible: false, periodsPerYear: 2190, marketCalendar: '24x7', marketSession: 'continuous', timeZone: 'UTC',
      source: { kind: 'provider_fetch', fileName: null, sourceName: 'Blocked fixture', sourceReference: 'fixture://blocked/4h', normalizerVersion: 'fixture-market-bars-v2', retrievedAtUtc: '2026-07-22T00:00:00+00:00', requestedBarCount: 2190, returnedBarCount: 2190, retainedBarCount: 2190, closedDroppedCount: 0, deduplicatedCount: 0, terminationReason: 'requested_limit', targetSatisfied: true },
      quality: { status: 'blocked', cadenceGapCount: 1, normalizationNote: 'A missing 4h period blocks research.' },
    })).toBe(false);
    expect(quantDatasetReadyForAutoResearch(quantFixtureSnapshot.dataset)).toBe(true);
  });

  it('renders discrete plan steps and artifacts without decorative owner glyphs or percentage progress', () => {
    const markup = renderToStaticMarkup(<QuantPlanRail steps={quantFixtureSnapshot.plan} currentStepId={quantFixtureSnapshot.run.currentStepId} completedStepCount={presentation.completedStepCount} />);
    expect(markup).toContain('Research plan');
    expect(markup).toContain('10/10 complete');
    expect(markup).toContain('Human review');
    expect(markup).toContain('01');
    expect(markup).not.toContain('Human gate');
    expect(markup).not.toContain('Validator');
    expect(markup).not.toMatch(/\d+%/);
  });

  it('renders safe activity copy and hides exact event names from the feed', () => {
    const markup = renderToStaticMarkup(<QuantActivityFeed snapshot={quantFixtureSnapshot} presentation={presentation} onInspect={vi.fn()} />);
    expect(markup).toContain('Candidate rejected by validator');
    expect(markup).toContain('independent of run health');
    expect(markup).not.toContain('candidate.rejected');
  });

  it('labels computed kernel research as synthetic and bounded', () => {
    const markup = renderToStaticMarkup(<QuantKernelCheckCard snapshot={quantFixtureSnapshot} />);
    expect(markup).toContain('Daily-bar kernel verified');
    expect(markup).toContain('1,564 synthetic weekday bars');
    expect(markup).toContain('metrics and trades are generated by this same kernel');
    expect(markup).toContain('No network · no broker · no arbitrary code');
  });

  it('does not compute indicators over a sparse run projection and keeps artifact authenticity separate', () => {
    const market = renderToStaticMarkup(<QuantMarketWorkspace snapshot={quantFixtureSnapshot} onInspect={vi.fn()} />);
    const artifacts = renderToStaticMarkup(<QuantArtifactCards artifacts={presentation.primaryArtifacts} onInspect={vi.fn()} />);
    expect(market).not.toContain('SMA 20');
    expect(market).not.toContain('SMA 50');
    expect(market).not.toContain('SMA 200');
    expect(market).toContain('no performance metric is recalculated here');
    expect(artifacts).toContain('Synthetic Demo Fixture');
    expect(artifacts).not.toContain('artifact-research-report');
  });

  it('shows candidate verdicts separately from the completed strategy report', () => {
    const markup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={quantFixtureSnapshot} candidates={presentation.candidates} decision={presentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(markup).toContain('Unavailable');
    expect(markup).toContain('Alternative candidate');
    expect(markup).toContain('without a sealed-holdout conclusion');
    expect(markup).not.toContain('Candidate for paper evaluation');
    expect(markup).not.toContain('Synthetic Demo Fixture');
    expect(markup).toContain('quant-tab-validation');
    expect(markup).not.toContain('quant-tab-performance');
    expect(markup).not.toContain('quant-tab-experiments');
    expect(markup).toContain('Strategy vs benchmark');
    expect(markup).toContain('aria-label="SMA 50/200 equity compared with benchmark"');
    expect(markup).toContain('Selected strategy key metrics');
    expect(markup).toContain('Vs benchmark');
    expect(markup).toContain('Final decision unavailable');
    expect(markup).not.toContain('Recommended next step');
    expect(markup).toContain('Limitations');
    expect(markup).toContain('Open analysis');
    expect(markup).toContain('View trades');
    expect(markup).not.toContain('quant-metric-cards');
    expect(markup).not.toContain('Start Paper Trading');
  });

  it('replaces terminal campaign prompts with one final-choice refinement action', async () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.candidates = snapshot.candidates.map((candidate) => candidate.id === 'candidate-b' ? { ...candidate, canSeedResearch: true } : candidate);
    snapshot.report = {
      ...snapshot.report!,
      selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' },
      generalization: {
        status: 'fail', reason: 'The strategy failed to preserve positive holdout return.', selectedCandidateId: 'candidate-b',
        split: { method: 'chronological', ruleVersion: 'chronological-v1', trainBarCount: 1200, holdoutBarCount: 300, cutoffDate: '2025-01-01', datasetId: snapshot.dataset.id, datasetDigest: snapshot.dataset.digest },
      },
    };
    const nextPresentation = presentQuantWorkspace(snapshot);
    const onRunAutopilot = vi.fn();
    const onContinueResearch = vi.fn();
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={snapshot} candidates={nextPresentation.candidates} decision={nextPresentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onRunAutopilot={onRunAutopilot} onContinueResearch={onContinueResearch} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    });
    expect(container.textContent).toContain('Final decision');
    expect(container.textContent).toContain('Refine the final choice');
    expect(container.textContent).toContain('Proposed change');
    expect(container.textContent).toContain('Evidence basis / Why');
    expect(container.textContent).toContain('Success / stop condition');
    expect(container.textContent).toContain('The strategy failed to preserve positive holdout return.');
    expect(container.textContent).not.toContain('Recommended next step');
    expect(container.textContent).not.toContain('Run one suggested refinement');
    const refineButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Review & refine research');
    await act(async () => { refineButton?.click(); });
    expect(onRunAutopilot).not.toHaveBeenCalled();
    expect(onContinueResearch).toHaveBeenCalledOnce();
    expect(onContinueResearch).toHaveBeenCalledWith('candidate-b', expect.stringContaining('one bounded parameter change'));
    await act(async () => { root.unmount(); });
  });

  it('keeps broker language out of the front-stage retained conclusion', () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.candidates = snapshot.candidates.map((candidate) => candidate.id === 'candidate-b' ? { ...candidate, canSeedResearch: true } : candidate);
    snapshot.report = {
      ...snapshot.report!,
      conclusion: 'None of the tested candidates are suitable for live trading.',
      selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' },
      generalization: {
        status: 'fail',
        reason: 'The strategy failed to preserve positive holdout return.',
        selectedCandidateId: 'candidate-b',
        split: {
          method: 'chronological',
          ruleVersion: 'chronological-v1',
          trainBarCount: 1200,
          holdoutBarCount: 300,
          cutoffDate: '2025-01-01',
          datasetId: snapshot.dataset.id,
          datasetDigest: snapshot.dataset.digest,
        },
      },
    };
    const markup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={snapshot} candidates={presentQuantWorkspace(snapshot).candidates} decision={presentQuantWorkspace(snapshot).decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(markup).toContain('None of the tested candidates are promotable within this research scope.');
    expect(markup).not.toContain('suitable for live trading');
  });

  it('labels unverified continuation and retry data as retained snapshot context', () => {
    const continued = structuredClone(quantFixtureSnapshot);
    continued.run = {
      ...continued.run,
      continuedFrom: {
        parentRunId: 'run-source', seedCandidateId: 'candidate-source', candidateName: 'Source trend', sourceQuestion: 'Reduce drawdown after holdout failure.', reason: 'Reduce drawdown.',
      },
    };
    const currentMarkup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={continued} candidates={presentation.candidates} decision={presentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(currentMarkup).toContain('Retained continuation context');
    expect(currentMarkup).not.toContain('Continued from source version');
    expect(currentMarkup).toContain('Source candidate: Source trend');
    expect(currentMarkup).toContain('Reason: Reduce drawdown.');
    expect(currentMarkup).toContain('Source question: Reduce drawdown after holdout failure.');
    expect(currentMarkup).toContain('Relationship unavailable');
    expect(currentMarkup).not.toContain('Open source version');

    const refinedRetry = structuredClone(continued);
    refinedRetry.run = { ...refinedRetry.run, attemptNumber: 3, retryOfRunId: 'run-refined-attempt-2' };
    const historicalMarkup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={refinedRetry} candidates={presentation.candidates} decision={presentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(historicalMarkup).toContain('Retained retry context · Attempt 3');
    expect(historicalMarkup).toContain('Retained continuation context');
    expect(historicalMarkup).not.toContain('Retry attempt 3');
    expect(historicalMarkup).not.toContain('Continued from source version');
    expect(historicalMarkup).toContain('Relationship unavailable');
    expect(historicalMarkup).not.toContain('Open prior attempt');
  });

  it('opens only directory-validated source and prior targets from Report', async () => {
    const source = structuredClone(quantFixtureSnapshot);
    source.run.id = 'run-source';
    source.run.attemptNumber = 1;
    delete source.run.continuedFrom;
    delete source.run.retryOfRunId;
    const continued = structuredClone(source);
    continued.run.id = 'run-continued';
    continued.run.continuedFrom = {
      parentRunId: source.run.id,
      seedCandidateId: 'candidate-b',
      candidateName: 'Candidate B · SMA 50/200',
      sourceQuestion: source.project.goal,
      reason: 'Test a lower drawdown objective.',
    };
    const retry = structuredClone(continued);
    retry.run.id = 'run-continued-retry';
    retry.run.attemptNumber = 2;
    retry.run.retryOfRunId = continued.run.id;
    const historyItem = (item: QuantWorkspaceSnapshot) => ({
      contract: 'legacy-daily-v1' as const,
      id: item.run.id,
      projectId: item.project.id,
      datasetId: item.dataset.id,
      state: item.run.state,
      mode: item.run.mode === 'auto_research' ? 'auto' as const : 'plan' as const,
      question: item.project.goal,
      attemptNumber: item.run.attemptNumber,
      parentRunId: item.run.continuedFrom?.parentRunId ?? null,
      seedCandidateId: item.run.continuedFrom?.seedCandidateId ?? null,
      refinementReason: item.run.continuedFrom?.reason ?? null,
      retryOfRunId: item.run.retryOfRunId ?? null,
      provider: item.run.provider,
      model: item.run.model,
      usedExperiments: item.run.usedExperiments,
      createdAt: item.run.startedAt,
      updatedAt: item.run.completedAt ?? item.run.startedAt,
    });
    const onOpenRun = vi.fn(async () => undefined);
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      listRuns: async () => [historyItem(source), historyItem(continued), historyItem(retry)],
      listMarketRuns: async () => [],
    };
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<QuantStrategyReport api={api} snapshot={retry} candidates={presentQuantWorkspace(retry).candidates} decision={presentQuantWorkspace(retry).decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenRun={onOpenRun} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
      await Promise.resolve();
    });
    const sourceButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Open source version');
    const priorButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Open prior attempt');
    expect(sourceButton).toBeTruthy();
    expect(priorButton).toBeTruthy();
    expect(container.textContent).not.toContain('Relationship unavailable');
    expect(container.textContent).toContain('Continued from source version');
    expect(container.textContent).toContain('Retry attempt 2');
    expect(container.textContent).not.toContain('Retained continuation context');
    expect(container.textContent).not.toContain('Retained retry context');
    await act(async () => { sourceButton!.click(); await Promise.resolve(); });
    await act(async () => { priorButton!.click(); await Promise.resolve(); });
    expect(onOpenRun).toHaveBeenNthCalledWith(1, source.run.id);
    expect(onOpenRun).toHaveBeenNthCalledWith(2, continued.run.id);

    const snapshotCalls: string[] = [];
    const runsApi: QuantApi = {
      ...api,
      getRunWorkspaceSnapshot: async (runId) => {
        snapshotCalls.push(runId);
        if (runId === source.run.id) return source;
        throw new Error('Unexpected comparison snapshot.');
      },
    };
    const differentRangeRetry = structuredClone(retry);
    differentRangeRetry.scope.dateRange = { start: '2021-01-04', end: retry.scope.dateRange.end };
    differentRangeRetry.dataset.dateRange = { ...differentRangeRetry.scope.dateRange };
    differentRangeRetry.candidates = differentRangeRetry.candidates.map((candidate) => candidate.id === 'candidate-b' ? { ...candidate, canSeedResearch: true } : candidate);
    const onRefineFromComparison = vi.fn();
    await act(async () => {
      root.render(<QuantRunsPage api={runsApi} snapshot={differentRangeRetry} onOpenRun={vi.fn()} onOpenReport={vi.fn()} onStartNewResearch={vi.fn()} onRefineFromComparison={onRefineFromComparison} />);
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    const compareSourceButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Compare with source');
    expect(compareSourceButton).toBeTruthy();
    await act(async () => {
      compareSourceButton!.click();
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    expect(snapshotCalls).toEqual([source.run.id]);
    expect(container.textContent).toContain('Compare research history');
    expect(container.textContent).toContain('Not directly comparable');
    expect(container.textContent).toContain('Different research range');
    expect(container.textContent).toContain('Test a lower drawdown objective.');
    expect(container.textContent).not.toContain('Change vs source');
    const refineButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Refine from this result');
    expect(refineButton).toBeTruthy();
    await act(async () => { refineButton!.click(); });
    expect(onRefineFromComparison).toHaveBeenCalledTimes(1);
    expect(onRefineFromComparison.mock.calls[0]?.[0].run.id).toBe(retry.run.id);
    expect(onRefineFromComparison.mock.calls[0]?.[1]).toBe('candidate-b');
    expect(onRefineFromComparison.mock.calls[0]?.[2]).toContain('Retain Candidate B · SMA 50/200');

    const invalidApi: QuantApi = {
      ...api,
      listRuns: async () => [historyItem(source), historyItem(continued), { ...historyItem(retry), question: 'Mismatched directory question.' }],
    };
    await act(async () => {
      root.render(<QuantStrategyReport api={invalidApi} snapshot={retry} candidates={presentQuantWorkspace(retry).candidates} decision={presentQuantWorkspace(retry).decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenRun={onOpenRun} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
      await Promise.resolve();
    });
    expect(container.textContent).toContain('Relationship unavailable');
    expect(container.textContent).toContain('Retained continuation context');
    expect(container.textContent).toContain('Retained retry context · Attempt 2');
    expect(container.textContent).not.toContain('Continued from source version');
    expect(container.textContent).not.toContain('Retry attempt 2');
    expect([...container.querySelectorAll('button')].some((button) => button.textContent === 'Open source version' || button.textContent === 'Open prior attempt')).toBe(false);
    await act(async () => {
      root.render(<QuantRunsPage api={invalidApi} snapshot={retry} onOpenRun={vi.fn()} onOpenReport={vi.fn()} onStartNewResearch={vi.fn()} />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.textContent).toContain('Relationship unavailable');
    expect(container.querySelector('.quant-run-series-navigation')).toBeNull();
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('opens typed source comparison only after exact directory validation and consumes forged focus once', async () => {
    const source = structuredClone(quantFixtureSnapshot);
    source.run.id = 'run-source-focus';
    source.project.goal = 'Source research question.';
    const current = structuredClone(quantFixtureSnapshot);
    current.run.id = 'run-current-focus';
    current.project.goal = 'Continued research question.';
    current.run.continuedFrom = {
      parentRunId: source.run.id,
      seedCandidateId: 'candidate-b',
      candidateName: 'SMA 50/200',
      sourceQuestion: source.project.goal,
      reason: 'Test one bounded change.',
    };
    const historyItem = (item: QuantWorkspaceSnapshot) => ({
      contract: 'legacy-daily-v1' as const,
      id: item.run.id,
      projectId: item.project.id,
      datasetId: item.dataset.id,
      state: item.run.state,
      mode: item.run.mode === 'auto_research' ? 'auto' as const : 'plan' as const,
      question: item.project.goal,
      attemptNumber: item.run.attemptNumber,
      parentRunId: item.run.continuedFrom?.parentRunId ?? null,
      seedCandidateId: item.run.continuedFrom?.seedCandidateId ?? null,
      refinementReason: item.run.continuedFrom?.reason ?? null,
      retryOfRunId: item.run.retryOfRunId ?? null,
      provider: item.run.provider,
      model: item.run.model,
      usedExperiments: item.run.usedExperiments,
      createdAt: item.run.startedAt,
      updatedAt: item.run.completedAt ?? item.run.startedAt,
    });
    const getRunWorkspaceSnapshot = vi.fn(async (runId: string) => {
      if (runId !== source.run.id) throw new Error('Unexpected source snapshot.');
      return source;
    });
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      listRuns: async () => [historyItem(source), historyItem(current)],
      listMarketRuns: async () => [],
      getRunWorkspaceSnapshot,
    };
    const focus: QuantEvidenceFocusIntent = {
      id: 'focus-source-comparison',
      runId: current.run.id,
      candidateId: 'candidate-b',
      destination: 'runs',
      target: 'source_comparison',
      sourceRunId: source.run.id,
    };
    const resolved = vi.fn();
    const onOpenRun = vi.fn();
    const onOpenReport = vi.fn();
    const onStartNewResearch = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(<StrictMode><QuantRunsPage api={api} snapshot={current} onOpenRun={onOpenRun} onOpenReport={onOpenReport} onStartNewResearch={onStartNewResearch} evidenceFocus={focus} onEvidenceFocusResolved={resolved} /></StrictMode>);
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    expect(container.textContent).toContain('Compare research history');
    expect(getRunWorkspaceSnapshot).toHaveBeenCalledTimes(1);
    expect(getRunWorkspaceSnapshot).toHaveBeenCalledWith(source.run.id);
    expect(resolved).toHaveBeenCalledTimes(1);
    expect(resolved).toHaveBeenCalledWith('focus-source-comparison', expect.objectContaining({
      status: 'opened',
      evidenceReference: expect.stringContaining(`${current.run.id} ↔ ${source.run.id}`),
    }));
    expect(onOpenRun).not.toHaveBeenCalled();
    expect(onOpenReport).not.toHaveBeenCalled();
    expect(onStartNewResearch).not.toHaveBeenCalled();

    await act(async () => {
      root.render(<StrictMode><QuantRunsPage api={api} snapshot={current} onOpenRun={onOpenRun} onOpenReport={onOpenReport} onStartNewResearch={onStartNewResearch} evidenceFocus={focus} onEvidenceFocusResolved={resolved} /></StrictMode>);
      await Promise.resolve();
    });
    expect(getRunWorkspaceSnapshot).toHaveBeenCalledTimes(1);
    expect(resolved).toHaveBeenCalledTimes(1);

    await act(async () => { root.unmount(); });
    const forgedRoot = createRoot(container);
    const forgedResolved = vi.fn();
    const forgedFocus: QuantEvidenceFocusIntent = { ...focus, id: 'focus-source-forged', sourceRunId: 'forged-source' };
    await act(async () => {
      forgedRoot.render(<StrictMode><QuantRunsPage api={api} snapshot={current} onOpenRun={onOpenRun} onOpenReport={onOpenReport} onStartNewResearch={onStartNewResearch} evidenceFocus={forgedFocus} onEvidenceFocusResolved={forgedResolved} /></StrictMode>);
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    expect(container.textContent).not.toContain('Compare research history');
    expect(getRunWorkspaceSnapshot).toHaveBeenCalledTimes(1);
    expect(forgedResolved).toHaveBeenCalledTimes(1);
    expect(forgedResolved).toHaveBeenCalledWith('focus-source-forged', expect.objectContaining({ status: 'unavailable' }));
    expect(onOpenRun).not.toHaveBeenCalled();
    expect(onOpenReport).not.toHaveBeenCalled();
    expect(onStartNewResearch).not.toHaveBeenCalled();

    await act(async () => { forgedRoot.unmount(); });
    container.remove();
  });

  it('keeps candidate selection linked across report summary, trades, and strategy', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onSelectCandidate = vi.fn();
    const onOpenAnalysis = vi.fn();
    const renderReport = (selectedCandidateId: string) => <QuantStrategyReport api={createFixtureQuantApi()} snapshot={quantFixtureSnapshot} candidates={presentation.candidates} decision={presentation.decision} selectedCandidateId={selectedCandidateId} onSelectCandidate={onSelectCandidate} onOpenAnalysis={onOpenAnalysis} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />;
    await act(async () => { root.render(renderReport('candidate-b')); });
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('.quant-report-actions button')].find((button) => button.textContent === 'Open analysis')?.click(); });
    expect(onOpenAnalysis).toHaveBeenCalledTimes(1);
    await act(async () => { container.querySelector<HTMLButtonElement>('#quant-tab-candidates')?.click(); });
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('.quant-candidate-table .quant-table-link')].find((button) => button.textContent === 'SMA 20/100')?.click(); });
    expect(onSelectCandidate).toHaveBeenCalledWith('candidate-a');
    await act(async () => { root.render(renderReport('candidate-a')); });
    await act(async () => { container.querySelector<HTMLButtonElement>('#quant-tab-summary')?.click(); });
    expect(container.querySelector('.quant-report-performance figure')?.getAttribute('aria-label')).toContain('SMA 20/100 equity compared with benchmark');
    await act(async () => { container.querySelector<HTMLButtonElement>('#quant-tab-trades')?.click(); });
    expect(container.querySelector('.quant-report-panel')?.textContent).toContain('SMA 20/100');
    await act(async () => { container.querySelector<HTMLButtonElement>('#quant-tab-strategy')?.click(); });
    expect(container.querySelector('.quant-spec')?.textContent).toContain(quantFixtureSnapshot.candidates[0]?.strategySpec ?? '');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('shows exact market holding bars and elapsed time in Analysis and Report', async () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.trades = [{
      id: 'market-trade-rsi',
      candidateId: 'candidate-b',
      entryDate: '2026-01-01T00:00:00+00:00',
      exitDate: '2026-01-04T16:00:00+00:00',
      returnPct: 4.2,
      holdingBars: 22,
      holdingElapsedSeconds: 316_800,
      reason: 'Persisted chronological training backtest trade.',
    }];
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(<QuantStrategyLab snapshot={snapshot} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} variant="analysis" />);
    });
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('.pq-analysis-tabs button')]
        .find((button) => button.textContent === 'Trades')?.click();
    });
    expect(container.querySelector('.pq-analysis-view')?.textContent).toContain('22 bars · 3d 16h');
    expect(container.querySelector('.pq-analysis-view table')?.classList.contains('pq-trades-table')).toBe(true);

    await act(async () => {
      root.render(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={snapshot} candidates={presentation.candidates} decision={presentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>('#quant-tab-trades')?.click();
    });
    expect(container.querySelector('.quant-report-panel')?.textContent).toContain('22 bars · 3d 16h');

    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('applies drawdown and retained-trade focus once inside existing Analysis views', async () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    const firstTrade = snapshot.trades.find((item) => item.candidateId === 'candidate-b')!;
    const secondTrade = {
      ...firstTrade,
      id: 'kernel-trade-second',
      entryDate: '2025-08-01',
      exitDate: '2025-08-14',
      returnPct: 1.7,
    };
    snapshot.trades.push(secondTrade);
    const consumed = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    function StatefulAnalysisHarness({ currentSnapshot, selectedCandidateId, initialFocus }: { currentSnapshot: QuantWorkspaceSnapshot; selectedCandidateId: string; initialFocus: QuantEvidenceFocusIntent }) {
      const [focus, setFocus] = useState<QuantEvidenceFocusIntent | null>(initialFocus);
      return <QuantStrategyLab snapshot={currentSnapshot} selectedCandidateId={selectedCandidateId} onSelectCandidate={vi.fn()} variant="analysis" evidenceFocus={focus} onEvidenceFocusConsumed={(id) => { consumed(id); setFocus(null); }} />;
    }
    const drawdownFocus: QuantEvidenceFocusIntent = {
      id: 'focus-drawdown',
      runId: snapshot.run.id,
      candidateId: 'candidate-b',
      destination: 'analysis',
      target: 'drawdown',
    };

    await act(async () => {
      root.render(<StrictMode><StatefulAnalysisHarness key="drawdown" currentSnapshot={snapshot} selectedCandidateId="candidate-b" initialFocus={drawdownFocus} /></StrictMode>);
    });
    expect([...container.querySelectorAll<HTMLButtonElement>('.pq-analysis-tabs button')].find((button) => button.textContent === 'Drawdown')?.getAttribute('aria-selected')).toBe('true');
    const lowestDrawdownPoint = snapshot.performanceSeries.find((series) => series.id === 'candidate-b')!.points
      .reduce((lowest, point) => point.drawdown < lowest.drawdown ? point : lowest);
    expect(container.querySelector('.pq-strategy-inspection')?.textContent).toContain(lowestDrawdownPoint.date);
    expect(consumed.mock.calls.filter(([id]) => id === 'focus-drawdown')).toHaveLength(1);

    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('.pq-analysis-tabs button')].find((button) => button.textContent === 'Equity')?.click();
      [...container.querySelectorAll<HTMLButtonElement>('.pq-analysis-tabs button')].find((button) => button.textContent === 'Drawdown')?.click();
    });
    const latestPoint = snapshot.performanceSeries.find((series) => series.id === 'candidate-b')!.points.at(-1)!;
    expect(container.querySelector('.pq-strategy-inspection')?.textContent).toContain(latestPoint.date);

    const tradeFocus: QuantEvidenceFocusIntent = {
      id: 'focus-trade',
      runId: snapshot.run.id,
      candidateId: 'candidate-b',
      destination: 'analysis',
      target: 'trade',
      tradeId: secondTrade.id,
    };
    await act(async () => {
      root.render(<StrictMode><StatefulAnalysisHarness key="trade" currentSnapshot={snapshot} selectedCandidateId="candidate-b" initialFocus={tradeFocus} /></StrictMode>);
    });
    expect([...container.querySelectorAll<HTMLButtonElement>('.pq-analysis-tabs button')].find((button) => button.textContent === 'Market')?.getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector('[aria-label="Selected trade context"]')?.textContent).toContain(secondTrade.entryDate);
    expect(container.querySelector('[aria-label="Selected trade context"]')?.textContent).toContain(secondTrade.exitDate);
    expect(consumed.mock.calls.filter(([id]) => id === 'focus-trade')).toHaveLength(1);

    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('.pq-analysis-tabs button')].find((button) => button.textContent === 'Equity')?.click();
      [...container.querySelectorAll<HTMLButtonElement>('.pq-analysis-tabs button')].find((button) => button.textContent === 'Market')?.click();
    });
    expect(container.querySelector('[aria-label="Selected trade context"]')?.textContent).toContain(firstTrade.entryDate);
    expect(container.querySelector('[aria-label="Selected trade context"]')?.textContent ?? '').not.toContain(secondTrade.entryDate);

    const nextRun = structuredClone(snapshot);
    nextRun.run.id = 'next-run-without-focus';
    await act(async () => {
      root.render(<StrictMode><StatefulAnalysisHarness key="trade" currentSnapshot={nextRun} selectedCandidateId="candidate-b" initialFocus={tradeFocus} /></StrictMode>);
      await Promise.resolve();
    });
    expect(container.querySelector('[aria-label="Selected trade context"]')?.textContent ?? '').not.toContain(secondTrade.entryDate);
    await act(async () => {
      root.render(<StrictMode><StatefulAnalysisHarness key="trade" currentSnapshot={nextRun} selectedCandidateId="candidate-a" initialFocus={tradeFocus} /></StrictMode>);
      await Promise.resolve();
    });
    expect(container.querySelector('[aria-label="Selected trade context"]')?.textContent ?? '').not.toContain(secondTrade.entryDate);

    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('opens retained validation locally without adding holdout evidence', async () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    const candidate = snapshot.candidates.find((item) => item.id === 'candidate-b')!.metrics;
    const benchmark = snapshot.benchmark!;
    snapshot.report = {
      ...snapshot.report!,
      selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' },
      generalization: {
        status: 'not_evaluated',
        reason: 'No fresh sealed holdout was evaluated.',
        selectedCandidateId: 'candidate-b',
        split: {
          method: 'chronological',
          ruleVersion: 'chronological-80-20-v1',
          trainBarCount: 800,
          holdoutBarCount: 200,
          cutoffDate: '2025-06-01',
          datasetId: snapshot.dataset.id,
          datasetDigest: snapshot.dataset.digest,
        },
        train: { candidate, benchmark },
      },
    };
    const focus: QuantEvidenceFocusIntent = {
      id: 'focus-validation',
      runId: snapshot.run.id,
      candidateId: 'candidate-b',
      destination: 'report',
      target: 'validation',
    };
    const consumed = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={snapshot} candidates={presentQuantWorkspace(snapshot).candidates} decision={presentQuantWorkspace(snapshot).decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} evidenceFocus={focus} onEvidenceFocusConsumed={consumed} />);
    });
    expect(container.querySelector<HTMLButtonElement>('#quant-tab-validation')?.getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector('.quant-report-panel')?.textContent).toContain('Not evaluated');
    expect(container.querySelector('.quant-report-panel')?.textContent).toContain('Training');
    expect(snapshot.report.generalization?.holdout).toBeUndefined();
    expect(consumed).toHaveBeenCalledWith('focus-validation');

    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('keeps parsed validation bound to the authoritative final candidate and renders insufficient regime diversity without a holdout claim', async () => {
    const raw = JSON.parse(JSON.stringify(quantFixtureSnapshot)) as Record<string, unknown>;
    const report = raw.report as Record<string, unknown>;
    const candidates = raw.candidates as Array<Record<string, unknown>>;
    const candidate = candidates[1]!.metrics;
    const benchmark = raw.benchmark;
    report.generalization = {
      status: 'not_evaluated',
      reason: 'No fresh sealed holdout was evaluated.',
      selectedCandidateId: 'candidate-b',
      split: { method: 'chronological', ruleVersion: 'chronological-80-20-v1', trainBarCount: 800, holdoutBarCount: 200, cutoffDate: '2025-06-01', datasetId: (raw.dataset as Record<string, unknown>).id, datasetDigest: (raw.dataset as Record<string, unknown>).digest },
      train: { candidate, benchmark },
    };
    report.selectionDecision = { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' };
    report.walkForward = {
      method: 'expanding', ruleVersion: 'expanding-3fold-20pct-v1', evaluationPartition: 'train', foldCount: 0, windowBarCount: 48,
      stateRuleVersion: 'market-state-v1', stateLookbackBars: 60, status: 'not_evaluated', reason: 'Training partition is too short for three walk-forward windows.', folds: [],
      aggregate: { evaluatedFolds: 0, candidatePositiveReturnFolds: 0, candidateLowerDrawdownFolds: 0, candidateMedianReturn: 0, benchmarkMedianReturn: 0, candidateMedianDrawdown: 0, benchmarkMedianDrawdown: 0, candidateMedianSharpe: 0, benchmarkMedianSharpe: 0, distinctMarketRegimes: 0, regimeDiversityStatus: 'insufficient_regime_diversity', byMarketRegime: [] },
    };
    const parsed = parseQuantWorkspaceSnapshot(raw).snapshot;
    expect(parsed).not.toBeNull();
    const snapshot = parsed!;
    const finalCandidate = snapshot.candidates.find((item) => item.id === 'candidate-b')!;
    const alternative = snapshot.candidates.find((item) => item.id === 'candidate-a')!;
    const focus: QuantEvidenceFocusIntent = { id: 'focus-final-validation', runId: snapshot.run.id, candidateId: alternative.id, destination: 'report', target: 'validation' };
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={snapshot} candidates={presentQuantWorkspace(snapshot).candidates} decision={presentQuantWorkspace(snapshot).decision} selectedCandidateId={alternative.id} onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} evidenceFocus={focus} onEvidenceFocusConsumed={vi.fn()} />);
    });
    const panelText = container.querySelector('.quant-report-panel')?.textContent ?? '';
    expect(panelText).toContain(candidateNameForTest(finalCandidate.name));
    expect(panelText).toContain('Final candidate findings');
    expect(panelText).toContain('Alternative candidate');
    expect(panelText).toContain(`${candidateNameForTest(alternative.name)} retains its own training evidence only and does not inherit final candidate sealed-holdout, cross-window, cost-sensitivity, or parameter-neighborhood conclusions.`);
    expect(panelText).toContain('Not evaluated');
    expect(panelText).toContain('Insufficient regime diversity');
    expect(panelText).not.toContain('Sealed holdout pass');

    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('renders final-candidate train-only cost and OAT evidence without a score or pass/fail claim', () => {
    const snapshot = robustnessReportSnapshot();
    const markup = renderToStaticMarkup(<QuantGeneralizationPanel generalization={snapshot.report!.generalization} robustnessSensitivity={snapshot.report!.robustnessSensitivity} selectedCandidateName={candidateNameForTest(snapshot.candidates.find((item) => item.id === 'candidate-b')!.name)} legacy />);
    expect(markup).toContain('Robustness sensitivity');
    expect(markup).toContain('Training only');
    expect(markup).toContain('baseline_1x');
    expect(markup).toContain('stressed_2x');
    expect(markup).toContain('stressed_4x');
    expect(markup).toContain('rowspan="2">0.1%</td><td class="is-numeric" rowspan="2">0.05%');
    expect(markup).toContain('rowspan="2">0.2%</td><td class="is-numeric" rowspan="2">0.1%');
    expect(markup).toContain('rowspan="2">0.4%</td><td class="is-numeric" rowspan="2">0.2%');
    expect(markup).toContain('fast_window');
    expect(markup).toContain(candidateNameForTest(snapshot.candidates.find((item) => item.id === 'candidate-b')!.name));
    expect(markup).toContain('does not establish global robustness and is not sealed holdout evidence');
    expect(markup).toContain('Sensitivity provenance');
    expect(markup).not.toContain('Sensitivity score');
    expect(markup).not.toContain('Sensitivity pass');
  });

  it('states when a final candidate retained no legal OAT neighbors or legacy sensitivity artifact', () => {
    const emptyNeighbors = robustnessReportSnapshot();
    emptyNeighbors.report!.robustnessSensitivity!.parameterNeighbors = [];
    emptyNeighbors.report!.robustnessSensitivity!.kernelCallCount = 6;
    const emptyMarkup = renderToStaticMarkup(<QuantGeneralizationPanel generalization={emptyNeighbors.report!.generalization} robustnessSensitivity={emptyNeighbors.report!.robustnessSensitivity} selectedCandidateName="SMA 50/200" legacy />);
    expect(emptyMarkup).toContain('No retained legal, in-range one-at-a-time neighbors were available. This does not establish stability.');

    const legacyMarkup = renderToStaticMarkup(<QuantGeneralizationPanel generalization={emptyNeighbors.report!.generalization} selectedCandidateName="SMA 50/200" legacy />);
    expect(legacyMarkup).toContain('No retained train-only cost or parameter sensitivity evidence is available for this legacy report.');
  });

  it('routes a Copilot drawdown focus through the workspace once without a mutation command', async () => {
    const sendCommand = vi.fn();
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      getWorkspaceSnapshot: async () => structuredClone(quantFixtureSnapshot),
      sendCommand,
    };
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(<QuantWorkspace api={api} />);
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined))));
    });
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Open max drawdown')?.click();
    });
    expect(container.querySelector<HTMLButtonElement>('#pq-workspace-tab-analysis')?.getAttribute('aria-selected')).toBe('true');
    expect([...container.querySelectorAll<HTMLButtonElement>('.pq-analysis-tabs button')].find((button) => button.textContent === 'Drawdown')?.getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector('.quant-notice')?.textContent).toContain('Evidence focus applied');
    expect(container.querySelector('.quant-notice')?.textContent).toContain('candidate-b');
    expect(sendCommand).not.toHaveBeenCalled();

    await act(async () => {
      container.querySelector<HTMLButtonElement>('#pq-workspace-tab-report')?.click();
    });
    expect(container.querySelector<HTMLButtonElement>('#pq-workspace-tab-report')?.getAttribute('aria-selected')).toBe('true');
    expect(sendCommand).not.toHaveBeenCalled();

    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('binds terminal Report actions to the authoritative final candidate, not an alternative', async () => {
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.candidates = snapshot.candidates.map((candidate) => ({
      ...candidate,
      canSeedResearch: candidate.id === 'candidate-b',
    }));
    snapshot.report = {
      ...snapshot.report!,
      selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' },
      generalization: { ...snapshot.report!.generalization!, status: 'fail', selectedCandidateId: 'candidate-b', reason: 'The retained holdout failed.' },
    };
    const onContinueResearch = vi.fn();
    const onOpenHistory = vi.fn();
    const previewStrategyReportExport = vi.fn().mockResolvedValue({
      exportType: 'strategy_report_markdown', runId: snapshot.run.id, candidateId: 'candidate-b', authenticity: 'synthetic_fixture',
      filename: 'final-report.md', mediaType: 'text/markdown', renderedContent: '# Final evidence\n', contentDigest: `sha256:${'f'.repeat(64)}`,
    });
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<QuantStrategyReport api={{ ...createFixtureQuantApi(), previewStrategyReportExport }} snapshot={snapshot} candidates={presentQuantWorkspace(snapshot).candidates} decision={presentQuantWorkspace(snapshot).decision} selectedCandidateId="candidate-a" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onContinueResearch={onContinueResearch} onOpenHistory={onOpenHistory} onStartNewResearch={vi.fn()} />);
    });

    expect(container.textContent).toContain('Final choice');
    expect(container.textContent).toContain('SMA 50/200');
    expect(container.textContent).toContain('Alternative candidate · training evidence');
    expect(container.textContent).not.toContain('Continue research');
    expect(container.textContent).toContain('Proposed change');
    expect(container.textContent).toContain('Evidence basis / Why');
    expect(container.textContent).toContain('Success / stop condition');
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Review & refine research')?.click(); });
    expect(onContinueResearch).toHaveBeenCalledWith('candidate-b', expect.stringContaining('Retain Candidate B'));
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Research history')?.click(); });
    expect(onOpenHistory).toHaveBeenCalledTimes(1);
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Export final evidence')?.click(); await Promise.resolve(); });
    expect(previewStrategyReportExport).toHaveBeenCalledWith(snapshot.run.id, 'candidate-b', 'strategy_report_markdown');
    expect(container.querySelector('option[value="strategy_evidence_bundle_json"]')).not.toHaveProperty('disabled', true);
    await act(async () => { root.unmount(); });
    container.remove();

    const historicalMarkup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={snapshot} candidates={presentQuantWorkspace(snapshot).candidates} decision={presentQuantWorkspace(snapshot).decision} selectedCandidateId="candidate-a" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(historicalMarkup).toContain('Read-only final decision');
    expect(historicalMarkup).toContain('Export final evidence');
    expect(historicalMarkup).not.toContain('Review & refine research');
    expect(historicalMarkup).not.toContain('Proposed change');

    const conflictingIdentity = structuredClone(snapshot);
    conflictingIdentity.report!.generalization = { ...conflictingIdentity.report!.generalization!, selectedCandidateId: 'candidate-a' };
    const unavailableMarkup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={conflictingIdentity} candidates={presentQuantWorkspace(conflictingIdentity).candidates} decision={presentQuantWorkspace(conflictingIdentity).decision} selectedCandidateId="candidate-a" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onContinueResearch={vi.fn()} onRunAutopilot={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(unavailableMarkup).toContain('Final decision unavailable');
    expect(unavailableMarkup).toContain('Sealed-holdout evidence is withheld');
    expect(unavailableMarkup).not.toContain('Review & refine research');
    expect(unavailableMarkup).not.toContain('Recommended next step');
    expect(unavailableMarkup).not.toContain('Run one suggested refinement');

    const unseedableFinal = structuredClone(snapshot);
    unseedableFinal.candidates = unseedableFinal.candidates.map((candidate) => ({ ...candidate, canSeedResearch: false }));
    const unseedableMarkup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={unseedableFinal} candidates={presentQuantWorkspace(unseedableFinal).candidates} decision={presentQuantWorkspace(unseedableFinal).decision} selectedCandidateId="candidate-a" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onContinueResearch={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(unseedableMarkup).toContain('Final choice');
    expect(unseedableMarkup).toContain('Sealed holdout');
    expect(unseedableMarkup).toContain('Read-only final decision');
    expect(unseedableMarkup).toContain('Export final evidence');
    expect(unseedableMarkup).not.toContain('Review & refine research');

    const retainedFallbackMarkup = renderToStaticMarkup(<QuantTerminalDecision decision={{ finalCandidateId: 'candidate-b', finalCandidateName: 'Candidate B · SMA 50/200', selectionReason: 'walk_forward_stability', selectionBasis: 'robustness_override', holdoutStatus: 'fail', holdoutReason: 'The retained holdout failed.', decision: 'refine', decisionDetail: 'Review one bounded change.', canRefine: false, refinementReason: '' }} onOpenHistory={vi.fn()} />);
    expect(retainedFallbackMarkup).toContain('Walk-forward stability');
    expect(retainedFallbackMarkup).not.toContain('walk_forward_stability');
  });

  it('hides continuation entry points for fixture and ineligible terminal states', () => {
    const fixtureSnapshot = structuredClone(quantFixtureSnapshot);
    fixtureSnapshot.candidates = fixtureSnapshot.candidates.map((candidate) => ({ ...candidate, canSeedResearch: false }));
    const fixtureMarkup = renderToStaticMarkup(
      <QuantStrategyReport
        api={createFixtureQuantApi()}
        snapshot={fixtureSnapshot}
        candidates={presentQuantWorkspace(fixtureSnapshot).candidates}
        decision={presentQuantWorkspace(fixtureSnapshot).decision}
        selectedCandidateId="candidate-b"
        onSelectCandidate={vi.fn()}
        onOpenAnalysis={vi.fn()}
        onOpenHistory={vi.fn()}
        onStartNewResearch={vi.fn()}
      />,
    );
    expect(fixtureMarkup).not.toContain('Continue research');

    const waitingSnapshot = structuredClone(quantFixtureSnapshot);
    waitingSnapshot.run = { ...waitingSnapshot.run, state: 'waiting_for_review' };
    waitingSnapshot.candidates = waitingSnapshot.candidates.map((candidate) => ({
      ...candidate,
      canSeedResearch: candidate.id === 'candidate-b',
    }));
    const waitingMarkup = renderToStaticMarkup(
      <QuantStrategyLab
        snapshot={waitingSnapshot}
        selectedCandidateId="candidate-b"
        onSelectCandidate={vi.fn()}
        onContinueResearch={vi.fn()}
        variant="analysis"
      />,
    );
    expect(waitingMarkup).not.toContain('Continue research');
  });

  it('previews, copies, and downloads the server-rendered selected-candidate report', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const selectedCandidateSnapshot = structuredClone(quantFixtureSnapshot);
    selectedCandidateSnapshot.candidates = selectedCandidateSnapshot.candidates.map((candidate) => ({ ...candidate, canSeedResearch: candidate.id === 'candidate-b' }));
    selectedCandidateSnapshot.report = {
      ...selectedCandidateSnapshot.report!,
      selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' },
      generalization: { ...selectedCandidateSnapshot.report!.generalization!, status: 'fail', selectedCandidateId: 'candidate-b', reason: 'The final candidate failed the retained holdout.' },
    };
    const selectedCandidateSnapshotPresentation = presentQuantWorkspace(selectedCandidateSnapshot);
    const previewStrategyReportExport = vi.fn().mockResolvedValue({
      exportType: 'strategy_report_markdown', runId: quantFixtureSnapshot.run.id, candidateId: 'candidate-a',
      authenticity: 'synthetic_fixture',
      filename: 'spy-strategy-report-55555555.md', mediaType: 'text/markdown',
      renderedContent: '# SPY Strategy Report\n\nCandidate A · SMA 20/100\n', contentDigest: `sha256:${'a'.repeat(64)}`,
    });
    const api = { ...createFixtureQuantApi(), previewStrategyReportExport };
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const createObjectURL = vi.fn(() => 'blob:report');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });
    let clickedFilename = '';
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { clickedFilename = this.download; });
    await act(async () => { root.render(<QuantStrategyReport api={api} snapshot={selectedCandidateSnapshot} candidates={selectedCandidateSnapshotPresentation.candidates} decision={selectedCandidateSnapshotPresentation.decision} selectedCandidateId="candidate-a" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />); });
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Export selected candidate report')?.click(); });
    await act(async () => { await Promise.resolve(); });
    expect(previewStrategyReportExport).toHaveBeenCalledWith(quantFixtureSnapshot.run.id, 'candidate-a', 'strategy_report_markdown');
    expect(container.querySelector('option[value="strategy_evidence_bundle_json"]')).toHaveProperty('disabled', true);
    expect(container.querySelector('[aria-label="Rendered Strategy Report Markdown"]')?.textContent).toContain('Candidate A · SMA 20/100');
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Copy Markdown')?.click(); });
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('Candidate A'));
    writeText.mockRejectedValueOnce(new Error('Clipboard permission blocked.'));
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Copy Markdown')?.click(); });
    expect(container.textContent).toContain('Copy failed: Clipboard permission blocked.');
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Download .md')?.click(); });
    expect(createObjectURL).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    expect(clickedFilename).toBe('spy-strategy-report-55555555.md');
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:report');
    anchorClick.mockRestore();
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('switches the final candidate export to the JSON evidence bundle and keeps stale Markdown out', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const finalSnapshot = structuredClone(quantFixtureSnapshot);
    finalSnapshot.candidates = finalSnapshot.candidates.map((candidate) => ({ ...candidate, canSeedResearch: candidate.id === 'candidate-b' }));
    finalSnapshot.report = {
      ...finalSnapshot.report!,
      selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' },
      generalization: { ...finalSnapshot.report!.generalization!, status: 'fail', selectedCandidateId: 'candidate-b', reason: 'The final candidate failed the retained holdout.' },
    };
    const finalPresentation = presentQuantWorkspace(finalSnapshot);
    const markdown = {
      exportType: 'strategy_report_markdown' as const, runId: quantFixtureSnapshot.run.id, candidateId: 'candidate-b',
      authenticity: 'synthetic_fixture' as const, filename: 'spy-strategy-report.md', mediaType: 'text/markdown' as const,
      renderedContent: '# Markdown that must not win\n', contentDigest: `sha256:${'c'.repeat(64)}`,
    };
    const json = {
      exportType: 'strategy_evidence_bundle_json' as const, runId: quantFixtureSnapshot.run.id, candidateId: 'candidate-b',
      authenticity: 'synthetic_fixture' as const, filename: 'qurio-spy-evidence-55555555.json', mediaType: 'application/json' as const,
      renderedContent: '{\n  "schema_version": "strategy_evidence_bundle_v1",\n  "candidate_id": "candidate-b"\n}\n', contentDigest: `sha256:${'d'.repeat(64)}`,
    };
    let resolveMarkdown: ((value: typeof markdown) => void) | undefined;
    let resolveJson: ((value: typeof json) => void) | undefined;
    const previewStrategyReportExport = vi.fn().mockImplementation((_runId: string, _candidateId: string, exportType: string) => exportType === 'strategy_evidence_bundle_json'
      ? new Promise<typeof json>((resolve) => { resolveJson = resolve; })
      : new Promise<typeof markdown>((resolve) => { resolveMarkdown = resolve; }));
    const api = { ...createFixtureQuantApi(), previewStrategyReportExport };
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const createObjectURL = vi.fn(() => 'blob:evidence');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });
    let clickedFilename = '';
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { clickedFilename = this.download; });
    await act(async () => { root.render(<QuantStrategyReport api={api} snapshot={finalSnapshot} candidates={finalPresentation.candidates} decision={finalPresentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />); });
    const format = container.querySelector<HTMLSelectElement>('[aria-label="Export format"]');
    expect(format).toBeNull();
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Export final evidence')?.click(); });
    const exportFormat = container.querySelector<HTMLSelectElement>('[aria-label="Export format"]');
    expect(exportFormat?.value).toBe('strategy_report_markdown');
    exportFormat!.value = 'strategy_evidence_bundle_json';
    await act(async () => { exportFormat!.dispatchEvent(new Event('change', { bubbles: true })); });
    await act(async () => { resolveJson?.(json); await Promise.resolve(); });
    await act(async () => { resolveMarkdown?.(markdown); await Promise.resolve(); });
    expect(previewStrategyReportExport).toHaveBeenNthCalledWith(1, quantFixtureSnapshot.run.id, 'candidate-b', 'strategy_report_markdown');
    expect(previewStrategyReportExport).toHaveBeenNthCalledWith(2, quantFixtureSnapshot.run.id, 'candidate-b', 'strategy_evidence_bundle_json');
    expect(container.querySelector('[aria-label="Rendered Strategy Evidence Bundle JSON"]')?.textContent).toContain('strategy_evidence_bundle_v1');
    expect(container.querySelector('[aria-label="Rendered Strategy Report Markdown"]')).toBeNull();
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Copy JSON')?.click(); });
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('candidate-b'));
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Download .json')?.click(); });
    expect(clickedFilename).toBe('qurio-spy-evidence-55555555.json');
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:evidence');
    anchorClick.mockRestore();
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('does not offer JSON when the report lacks an authoritative selection decision', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.report!.selectionDecision = undefined;
    const previewStrategyReportExport = vi.fn().mockResolvedValue({
      exportType: 'strategy_report_markdown', runId: snapshot.run.id, candidateId: 'candidate-b', authenticity: 'synthetic_fixture',
      filename: 'spy-strategy-report.md', mediaType: 'text/markdown', renderedContent: '# Report\n', contentDigest: `sha256:${'e'.repeat(64)}`,
    });
    const api = { ...createFixtureQuantApi(), previewStrategyReportExport };
    await act(async () => { root.render(<QuantStrategyReport api={api} snapshot={snapshot} candidates={presentation.candidates} decision={presentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />); });
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Export report')?.click(); await Promise.resolve(); });
    expect(container.querySelector('option[value="strategy_evidence_bundle_json"]')).toHaveProperty('disabled', true);
    expect(previewStrategyReportExport).toHaveBeenCalledWith(snapshot.run.id, 'candidate-b', 'strategy_report_markdown');
    expect(previewStrategyReportExport).not.toHaveBeenCalledWith(snapshot.run.id, 'candidate-b', 'strategy_evidence_bundle_json');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('keeps report preview failure local and retries the same run and candidate', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const finalSnapshot = structuredClone(quantFixtureSnapshot);
    finalSnapshot.candidates = finalSnapshot.candidates.map((candidate) => ({ ...candidate, canSeedResearch: candidate.id === 'candidate-b' }));
    finalSnapshot.report = { ...finalSnapshot.report!, selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' }, generalization: { ...finalSnapshot.report!.generalization!, status: 'fail', selectedCandidateId: 'candidate-b', reason: 'The final candidate failed the retained holdout.' } };
    const finalPresentation = presentQuantWorkspace(finalSnapshot);
    const preview = { exportType: 'strategy_report_markdown' as const, runId: finalSnapshot.run.id, candidateId: 'candidate-b', authenticity: 'synthetic_fixture' as const, filename: 'spy-report.md', mediaType: 'text/markdown' as const, renderedContent: '# Retried report\n', contentDigest: `sha256:${'b'.repeat(64)}` };
    const previewStrategyReportExport = vi.fn().mockRejectedValueOnce(new Error('Report renderer unavailable.')).mockResolvedValue(preview);
    const api = { ...createFixtureQuantApi(), previewStrategyReportExport };
    await act(async () => { root.render(<QuantStrategyReport api={api} snapshot={finalSnapshot} candidates={finalPresentation.candidates} decision={finalPresentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />); });
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Export final evidence')?.click(); await Promise.resolve(); });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('Report renderer unavailable.');
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Retry preview')?.click(); await Promise.resolve(); });
    expect(container.querySelector('[aria-label="Rendered Strategy Report Markdown"]')?.textContent).toContain('Retried report');
    expect(previewStrategyReportExport).toHaveBeenCalledTimes(2);
    expect(previewStrategyReportExport).toHaveBeenNthCalledWith(1, finalSnapshot.run.id, 'candidate-b', 'strategy_report_markdown');
    expect(previewStrategyReportExport).toHaveBeenNthCalledWith(2, finalSnapshot.run.id, 'candidate-b', 'strategy_report_markdown');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('renders a compact report fallback without zero KPIs or a fabricated curve', () => {
    const failed = liveFixtures['quant-failed-safe'] as unknown as QuantWorkspaceSnapshot;
    const failedPresentation = presentQuantWorkspace(failed);
    const markup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={failed} candidates={failedPresentation.candidates} decision={failedPresentation.decision} selectedCandidateId="" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(markup).toContain('Decision was not produced');
    expect(markup).toContain('run stopped before a decision could be produced');
    expect(markup).toContain('>New research<');
    expect(markup).not.toContain('Selected strategy key metrics');
    expect(markup).not.toContain('pq-strategy-line is-candidate');
    expect(markup).not.toMatch(/>0(?:\.0)?%?</);
  });

  it('renders a safe unavailable state when a report has no generalization result', () => {
    const markup = renderToStaticMarkup(<QuantGeneralizationPanel />);
    expect(markup).toContain('Validation evidence unavailable');
    expect(markup).toContain('does not include a chronological training and sealed-holdout evaluation');
  });

  it('renders chronological split provenance and train/holdout metrics', () => {
    const candidate = quantFixtureSnapshot.candidates[0]!.metrics;
    const benchmark = quantFixtureSnapshot.benchmark!;
    const markup = renderToStaticMarkup(<QuantGeneralizationPanel generalization={{
      status: 'pass',
      reason: 'The selected candidate remained ahead of the benchmark on holdout data.',
      selectedCandidateId: 'candidate-a',
      split: {
        method: 'chronological',
        ruleVersion: 'chronological-v1',
        trainBarCount: 1200,
        holdoutBarCount: 364,
        cutoffDate: '2024-01-02',
        datasetId: 'dataset-immutable-01',
        datasetDigest: 'sha256:generalization-fixture',
      },
      train: { candidate, benchmark },
      holdout: {
        candidate: { ...candidate, annualizedReturn: 9.4, trades: 5 },
        benchmark: { ...benchmark, annualizedReturn: 7.2, trades: 1 },
      },
    }} walkForward={{
      method: 'expanding',
      ruleVersion: 'expanding-3fold-20pct-v1',
      evaluationPartition: 'train',
      foldCount: 3,
      windowBarCount: 48,
      stateRuleVersion: 'market-state-v1',
      stateLookbackBars: 60,
      status: 'completed',
      reason: 'Fixed candidate evaluated in three expanding training-only windows.',
      folds: [1, 2, 3].map((foldIndex) => ({
        foldIndex,
        historyStart: '2023-01-01',
        historyEnd: '2023-04-06',
        evaluationStart: `2023-0${foldIndex + 3}-07`,
        evaluationEnd: `2023-0${foldIndex + 4}-24`,
        marketRegime: foldIndex < 3
          ? { label: 'uptrend_normal_volatility' as const, trend: 'uptrend' as const, volatility: 'normal_volatility' as const, historyStart: '2023-01-01', historyEnd: '2023-04-06', historyBarCount: 60, trailingReturn: 8, annualizedVolatility: 18 }
          : { label: 'sideways_high_volatility' as const, trend: 'sideways' as const, volatility: 'high_volatility' as const, historyStart: '2023-01-01', historyEnd: '2023-04-06', historyBarCount: 60, trailingReturn: 0.4, annualizedVolatility: 42 },
        candidate,
        benchmark,
        status: 'pass' as const,
      })),
      aggregate: {
        evaluatedFolds: 3,
        candidatePositiveReturnFolds: 3,
        candidateLowerDrawdownFolds: 2,
        candidateMedianReturn: 8,
        benchmarkMedianReturn: 7,
        candidateMedianDrawdown: -4,
        benchmarkMedianDrawdown: -6,
        candidateMedianSharpe: 1.2,
        benchmarkMedianSharpe: 1,
        distinctMarketRegimes: 2,
        regimeDiversityStatus: 'covered',
        byMarketRegime: [
          { label: 'uptrend_normal_volatility', foldCount: 2, candidateMedianReturn: 8, benchmarkMedianReturn: 7, candidateMedianDrawdown: -4, benchmarkMedianDrawdown: -6, candidateMedianSharpe: 1.2, benchmarkMedianSharpe: 1 },
          { label: 'sideways_high_volatility', foldCount: 1, candidateMedianReturn: 6, benchmarkMedianReturn: 5, candidateMedianDrawdown: -5, benchmarkMedianDrawdown: -7, candidateMedianSharpe: 0.8, benchmarkMedianSharpe: 0.7 },
        ],
      },
    }} datasetQuality={datasetQuality} />);
    expect(markup).toContain('Sealed holdout');
    expect(markup).toContain('The selected candidate remained ahead');
    expect(markup).toContain('chronological-v1');
    expect(markup).toContain('1,200');
    expect(markup).toContain('364');
    expect(markup).toContain('2024-01-02');
    expect(markup).toContain('candidate-a');
    expect(markup).toContain('dataset-immutable-01');
    expect(markup).toContain('sha256:generalization-fixture');
    expect(markup).toContain('Candidate and benchmark by evaluation partition');
    expect(markup).toContain('Training');
    expect(markup).toContain('9.4%');
    expect(markup).toContain('Walk-forward robustness');
    expect(markup).toContain('Training-only modeled windows are not sealed-holdout evidence.');
    expect(markup).toContain('uptrend_normal_volatility');
    expect(markup).toContain('Modeled-regime summary');
    expect(markup).toContain('Covered');
    expect(markup).toContain('No retained train-only cost or parameter sensitivity evidence is available for this report.');
    expect(markup).toContain('market-state-v1');
    expect(markup).toContain('expanding-3fold-20pct-v1');
    expect(markup).toContain('Walk-forward provenance');
    expect(markup).toContain('3 / 3');
    expect(markup).toContain('Dataset quality');
    expect(markup).toContain('1,564');
    expect(markup).toContain('Checks describe the pinned input, not strategy performance or market-data authenticity.');
  });

  it('uses imported provenance and symbol copy for imported evidence', () => {
    const importedSnapshot = {
      ...quantFixtureSnapshot,
      authenticity: 'imported' as const,
      scope: { ...quantFixtureSnapshot.scope, symbol: 'ACME' },
      dataset: { ...legacyFixtureDataset, symbol: 'ACME', authenticity: 'imported' as const },
    };
    const market = renderToStaticMarkup(<QuantMarketWorkspace snapshot={importedSnapshot} onInspect={vi.fn()} />);
    const importedPresentation = presentQuantWorkspace(importedSnapshot);
    const report = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={importedSnapshot} candidates={importedPresentation.candidates} decision={importedPresentation.decision} selectedCandidateId="candidate-b" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(market).toContain('ACME 1D price and volume chart');
    expect(market).toContain('workspace-imported dataset');
    expect(report).toContain('ACME evidence');
    expect(report).not.toContain('Imported Dataset');
    expect(report).not.toContain('Synthetic Demo Fixture');
  });

  it('falls back to the report-selected candidate for dynamic provider IDs', () => {
    const snapshot = {
      ...quantFixtureSnapshot,
      report: {
        ...quantFixtureSnapshot.report!,
        selectionDecision: { basis: 'approved_objective_rank' as const, selectedCandidateId: 'candidate-c' },
        generalization: {
          status: 'pass' as const,
          reason: 'Selected after comparison.',
          selectedCandidateId: 'candidate-c',
          split: {
            method: 'chronological' as const,
            ruleVersion: 'chronological-80-20-v1',
            trainBarCount: 1200,
            holdoutBarCount: 300,
            cutoffDate: '2024-01-01',
            datasetId: 'dataset-1',
            datasetDigest: 'sha256:selected-candidate',
          },
        },
      },
    };
    const snapshotPresentation = presentQuantWorkspace(snapshot);
    const markup = renderToStaticMarkup(<QuantStrategyReport api={createFixtureQuantApi()} snapshot={snapshot} candidates={snapshotPresentation.candidates} decision={snapshotPresentation.decision} selectedCandidateId="provider-specific-id" onSelectCandidate={vi.fn()} onOpenAnalysis={vi.fn()} onOpenHistory={vi.fn()} onStartNewResearch={vi.fn()} />);
    expect(markup).toContain('value="candidate-c" selected=""');
    expect(markup).toContain('16.3%');
  });

  it('renders one focused data-source form with CSV metadata progressively disclosed', () => {
    const markup = renderToStaticMarkup(<QuantDataPage api={createFixtureQuantApi()} snapshot={quantFixtureSnapshot} selectedDataset={quantFixtureSnapshot.dataset} onSelect={vi.fn()} initialView="import" initialSource="csv" />);
    expect(markup).toContain('Add market data');
    expect(markup).toContain('Market OHLCV CSV');
    expect(markup).toContain('OHLCV CSV file');
    expect(markup).toContain('Dataset interval');
    expect(markup).toContain('value="1h"');
    expect(markup).toContain('value="4h"');
    expect(markup).toContain('value="1D"');
    expect(markup).toContain('Import and validate');
    expect(markup).toContain('Source metadata');
    expect(markup).toContain('Dataset source provider');
    expect(markup).toContain('Dataset source reference');
    expect(markup).not.toContain('Binance Spot symbol');
    expect(markup).not.toContain('Nasdaq Equity symbol');
  });

  it('submits market-v2 CSV imports with an explicit supported interval', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const importedDataset = {
      contract: 'market-v2' as const,
      id: 'dataset-market-csv-4h',
      name: 'BTCUSDT CSV 4 hour',
      symbol: 'BTCUSDT',
      interval: '4h' as const,
      dateRange: { start: '2024-01-01T00:00:00Z', end: '2025-12-31T20:00:00Z' },
      barCount: 4386,
      schemaVersion: 'quant-market-bars-v2',
      parserVersion: 'quant-market-csv-v1',
      digest: `sha256:${'a'.repeat(64)}`,
      recordDigest: `sha256:${'b'.repeat(64)}`,
      authenticity: 'imported' as const,
      researchEligible: true,
      createdAt: '2026-07-22T00:00:00Z',
      periodsPerYear: 2190,
      marketCalendar: '24x7' as const,
      marketSession: 'continuous' as const,
      timeZone: 'UTC',
      source: {
        kind: 'csv_upload' as const,
        fileName: 'btcusdt-4h.csv',
        sourceName: 'Research CSV',
        sourceReference: 'upload:btc-4h',
        normalizerVersion: 'quant-market-csv-v1',
        retrievedAtUtc: null,
        requestedBarCount: null,
        returnedBarCount: null,
        retainedBarCount: null,
        closedDroppedCount: null,
        deduplicatedCount: null,
        terminationReason: null,
        targetSatisfied: null,
        submittedCsvDigest: `sha256:${'c'.repeat(64)}`,
      },
      quality: { status: 'accepted' as const, cadenceGapCount: 0, normalizationNote: 'Contiguous 4h UTC bars.' },
    };
    const onSelect = vi.fn();
    const importMarketDatasetCsv = vi.fn(async () => importedDataset);
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      listMarketDatasets: async () => [importedDataset],
      importMarketDatasetCsv,
    };
    await act(async () => {
      root.render(<QuantDataPage api={api} snapshot={quantFixtureSnapshot} selectedDataset={quantFixtureSnapshot.dataset} onSelect={onSelect} initialView="import" initialSource="csv" />);
    });
    const fileInput = container.querySelector<HTMLInputElement>('input[aria-label="OHLCV CSV file"]');
    const intervalSelect = container.querySelector<HTMLSelectElement>('select[aria-label="Dataset interval"]');
    const nameInput = container.querySelector<HTMLInputElement>('input[aria-label="Dataset name"]');
    const symbolInput = container.querySelector<HTMLInputElement>('input[aria-label="Dataset symbol"]');
    const providerInput = container.querySelector<HTMLInputElement>('input[aria-label="Dataset source provider"]');
    const referenceInput = container.querySelector<HTMLInputElement>('input[aria-label="Dataset source reference"]');
    const importButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.includes('Import and validate'));
    expect(fileInput && intervalSelect && nameInput && symbolInput && providerInput && referenceInput && importButton).toBeTruthy();
    const file = new File(['timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1,1,1,1,1'], 'btcusdt-4h.csv', { type: 'text/csv' });
    Object.defineProperty(file, 'text', { configurable: true, value: async () => 'timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1,1,1,1,1' });
    Object.defineProperty(fileInput!, 'files', { configurable: true, value: [file] });
    await act(async () => {
      fileInput!.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set;
      setValue?.call(intervalSelect!, '4h');
      intervalSelect!.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
      const inputSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      inputSetter?.call(nameInput!, 'BTCUSDT CSV 4 hour');
      nameInput!.dispatchEvent(new Event('input', { bubbles: true }));
      inputSetter?.call(symbolInput!, 'BTCUSDT');
      symbolInput!.dispatchEvent(new Event('input', { bubbles: true }));
      inputSetter?.call(providerInput!, 'Research CSV');
      providerInput!.dispatchEvent(new Event('input', { bubbles: true }));
      inputSetter?.call(referenceInput!, 'upload:btc-4h');
      referenceInput!.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      importButton!.click();
    });
    expect(importMarketDatasetCsv).toHaveBeenCalledWith(expect.objectContaining({
      name: 'BTCUSDT CSV 4 hour',
      symbol: 'BTCUSDT',
      interval: '4h',
      csvText: 'timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,1,1,1,1,1',
      fileName: 'btcusdt-4h.csv',
      sourceName: 'Research CSV',
      sourceReference: 'upload:btc-4h',
    }));
    expect(onSelect).not.toHaveBeenCalled();
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('submits market-v2 Binance fetches with an explicit supported interval', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const fetchedDataset = {
      contract: 'market-v2' as const,
      id: 'dataset-market-binance-1h',
      name: 'BTCUSDT Binance Spot 1 hour',
      symbol: 'BTCUSDT',
      interval: '1h' as const,
      dateRange: { start: '2024-01-01T00:00:00Z', end: '2024-07-27T07:00:00Z' },
      barCount: 5000,
      schemaVersion: 'quant-market-bars-v2',
      parserVersion: 'binance-market-bars-v2',
      digest: `sha256:${'d'.repeat(64)}`,
      recordDigest: `sha256:${'e'.repeat(64)}`,
      authenticity: 'synthetic_fixture' as const,
      researchEligible: true,
      createdAt: '2026-07-22T00:00:00Z',
      periodsPerYear: 8760,
      marketCalendar: '24x7' as const,
      marketSession: 'continuous' as const,
      timeZone: 'UTC',
      source: {
        kind: 'provider_fetch' as const,
        fileName: null,
        sourceName: 'Binance Spot deterministic API fixture',
        sourceReference: 'fixture://binance/BTCUSDT/1h/5000',
        normalizerVersion: 'binance-market-bars-v2',
        retrievedAtUtc: '2026-07-22T00:00:00Z',
        requestedBarCount: 5000,
        returnedBarCount: 5000,
        retainedBarCount: 5000,
        closedDroppedCount: 0,
        deduplicatedCount: 0,
        terminationReason: 'requested_limit' as const,
        targetSatisfied: true,
        batchDigest: `sha256:${'f'.repeat(64)}`,
      },
      quality: { status: 'accepted' as const, cadenceGapCount: 0, normalizationNote: 'Contiguous 1h UTC bars.' },
    };
    const onSelect = vi.fn();
    const fetchMarketBinanceDataset = vi.fn(async () => fetchedDataset);
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      listMarketDatasets: async () => [fetchedDataset],
      fetchMarketBinanceDataset,
    };
    await act(async () => {
      root.render(<QuantDataPage api={api} snapshot={quantFixtureSnapshot} selectedDataset={quantFixtureSnapshot.dataset} onSelect={onSelect} initialView="import" initialSource="binance" />);
    });
    const intervalSelect = container.querySelector<HTMLSelectElement>('select[aria-label="Binance Spot interval"]');
    const symbolInput = container.querySelector<HTMLInputElement>('input[aria-label="Binance Spot symbol"]');
    const limitInput = container.querySelector<HTMLInputElement>('input[aria-label="Binance Spot bar limit"]');
    const fetchButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.includes('Fetch and validate'));
    expect(intervalSelect && symbolInput && limitInput && fetchButton).toBeTruthy();
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set;
      setValue?.call(intervalSelect!, '1h');
      intervalSelect!.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(limitInput?.value).toBe('2190');
    await act(async () => {
      const inputSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      inputSetter?.call(symbolInput!, 'btcusdt');
      symbolInput!.dispatchEvent(new Event('input', { bubbles: true }));
      inputSetter?.call(limitInput!, '10');
      limitInput!.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      fetchButton!.click();
    });
    expect(fetchMarketBinanceDataset).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'BTCUSDT',
      interval: '1h',
      limit: 10,
    }));
    expect(onSelect).not.toHaveBeenCalled();
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('uses the server connector directory to fetch Kraken data into the existing catalog path', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const connector = {
      id: 'kraken-spot-ohlc-v1',
      provider: 'kraken_spot',
      displayName: 'Kraken Spot public OHLC',
      sourceKind: 'market_bars' as const,
      supportedSymbols: ['BTCUSD', 'BTCUSDT', 'ETHUSD', 'ETHUSDT'],
      supportedIntervals: ['4h', '1D'] as Array<'4h' | '1D'>,
      minimumRecentBars: { '4h': 548, '1D': 252 },
      maximumRecentBars: 719,
      fetchPath: '/v1/quant/connectors/kraken-spot-ohlc-v1/fetch',
      version: 'kraken-spot-ohlc-v1',
      sourceTermsUrl: 'https://www.kraken.com/legal',
      sourceDocumentationUrl: 'https://docs.kraken.com/api-reference/market-data/get-ohlc-data',
    };
    const fetchedDataset = {
      contract: 'market-v2' as const,
      id: 'fixture-connector-kraken-btcusd-4h-548',
      name: 'BTCUSD Kraken Spot 4 hour',
      symbol: 'BTCUSD',
      interval: '4h' as const,
      dateRange: { start: '2026-04-24T20:00:00Z', end: '2026-07-25T00:00:00Z' },
      barCount: 548,
      schemaVersion: 'quant-market-bars-v2',
      parserVersion: 'kraken-spot-ohlc-v1',
      digest: `sha256:${'1'.repeat(64)}`,
      recordDigest: `sha256:${'2'.repeat(64)}`,
      authenticity: 'synthetic_fixture' as const,
      researchEligible: true,
      createdAt: '2026-07-24T04:00:00Z',
      periodsPerYear: 2190,
      marketCalendar: '24x7' as const,
      marketSession: 'continuous' as const,
      timeZone: 'UTC',
      source: {
        kind: 'provider_fetch' as const,
        fileName: null,
        sourceName: 'Kraken Spot deterministic connector fixture',
        sourceReference: 'fixture://connector/kraken/BTCUSD/4h/548',
        normalizerVersion: 'kraken-spot-ohlc-v1',
        retrievedAtUtc: '2026-07-24T04:00:00Z',
        requestedBarCount: 548,
        returnedBarCount: 548,
        retainedBarCount: 548,
        closedDroppedCount: 0,
        deduplicatedCount: 0,
        terminationReason: 'requested_limit' as const,
        targetSatisfied: true,
        batchDigest: `sha256:${'3'.repeat(64)}`,
      },
      quality: { status: 'accepted' as const, cadenceGapCount: 0, normalizationNote: 'Contiguous 4h UTC bars.' },
    };
    const fetchConnectorDataset = vi.fn(async () => fetchedDataset);
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      listConnectors: async () => [connector],
      listMarketDatasets: async () => [],
      fetchConnectorDataset,
    };
    await act(async () => {
      root.render(<QuantDataPage api={api} snapshot={quantFixtureSnapshot} selectedDataset={quantFixtureSnapshot.dataset} onSelect={vi.fn()} />);
    });
    const connectionsTab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((button) => button.textContent === 'Connections');
    expect(connectionsTab).toBeTruthy();
    await act(async () => { connectionsTab!.click(); });
    expect(container.textContent).toContain('Kraken Spot public OHLC');
    expect(container.textContent).toContain('BTCUSD, BTCUSDT, ETHUSD, ETHUSDT');
    const openConnector = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Fetch data');
    await act(async () => { openConnector!.click(); });
    expect(container.querySelector('[role="tabpanel"][aria-labelledby="quant-data-source-kraken"]')).toBeTruthy();
    expect(container.querySelector<HTMLSelectElement>('select[aria-label="Kraken Spot symbol"]')?.value).toBe('BTCUSD');
    expect(container.querySelector<HTMLSelectElement>('select[aria-label="Kraken Spot interval"]')?.value).toBe('4h');
    expect(container.querySelector<HTMLInputElement>('input[aria-label="Kraken Spot bar limit"]')?.value).toBe('548');
    const fetch = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Fetch and validate');
    await act(async () => { fetch!.click(); });
    expect(fetchConnectorDataset).toHaveBeenCalledWith(expect.objectContaining({
      connectorId: 'kraken-spot-ohlc-v1',
      name: 'BTCUSD Kraken Spot 4 hour',
      symbol: 'BTCUSD',
      interval: '4h',
      limit: 548,
    }));
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('focuses the active data-source tab when the importer mounts directly', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<QuantDataPage api={createFixtureQuantApi()} snapshot={quantFixtureSnapshot} selectedDataset={quantFixtureSnapshot.dataset} onSelect={vi.fn()} initialView="import" initialSource="csv" />);
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined))));
    });
    expect(document.activeElement?.id).toBe('quant-data-source-csv');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('focuses the first invalid CSV field after local validation fails', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<QuantDataPage api={createFixtureQuantApi()} snapshot={quantFixtureSnapshot} selectedDataset={quantFixtureSnapshot.dataset} onSelect={vi.fn()} initialView="import" initialSource="csv" />);
    });
    const fileInput = container.querySelector<HTMLInputElement>('input[aria-label="OHLCV CSV file"]');
    const nameInput = container.querySelector<HTMLInputElement>('input[aria-label="Dataset name"]');
    const importButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.includes('Import and validate'));
    expect(fileInput).toBeTruthy();
    expect(nameInput).toBeTruthy();
    expect(importButton).toBeTruthy();
    const file = new File(['date,open,high,low,close,volume\n2024-01-01,1,1,1,1,1'], 'sample.csv', { type: 'text/csv' });
    Object.defineProperty(fileInput, 'files', { configurable: true, value: [file] });
    await act(async () => {
      fileInput!.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      setValue?.call(nameInput!, '');
      nameInput!.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      importButton!.click();
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined))));
    });
    expect((document.activeElement as HTMLInputElement | null)?.getAttribute('aria-label')).toBe('Dataset name');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('returns focus to the project workbench after a successful new research run', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      getWorkspaceSnapshot: async () => quantFixtureSnapshot,
      createProject: async () => ({ id: 'fixture-quant-project', rowVersion: 2 }),
      createRun: async () => ({ id: 'fixture-quant-run' }),
    };
    await act(async () => {
      root.render(<QuantWorkspace api={api} />);
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined))));
    });
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'New research')?.click();
    });
    const goal = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Research goal"]');
    const submit = [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Generate plan');
    expect(goal).toBeTruthy();
    expect(submit).toBeTruthy();
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      setValue?.call(goal!, 'Compare a bounded SPY trend hypothesis with synthetic evidence.');
      goal!.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      submit!.click();
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined))));
    });
    expect((document.activeElement as HTMLElement | null)?.id).toBe('pq-workspace-tab-overview');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('rejects a wrong-bound historical snapshot and keeps the current snapshot visible', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    let resolveRun: ((snapshot: QuantWorkspaceSnapshot) => void) | null = null;
    let openRunCalls = 0;
    const historicalRun = {
      contract: 'legacy-daily-v1' as const,
      id: 'run-historical',
      projectId: quantFixtureSnapshot.project.id,
      datasetId: quantFixtureSnapshot.dataset.id,
      state: 'completed' as const,
      mode: 'auto' as const,
      question: 'Historical run to open',
      attemptNumber: 2,
      parentRunId: null,
      seedCandidateId: null,
      refinementReason: null,
      retryOfRunId: 'run-source',
      provider: quantFixtureSnapshot.run.provider,
      model: quantFixtureSnapshot.run.model,
      usedExperiments: 3,
      createdAt: quantFixtureSnapshot.run.startedAt,
      updatedAt: quantFixtureSnapshot.run.startedAt,
    };
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      getWorkspaceSnapshot: async () => quantFixtureSnapshot,
      listProjects: async () => [{
        id: quantFixtureSnapshot.project.id,
        name: quantFixtureSnapshot.project.title,
        objective: quantFixtureSnapshot.project.goal,
        status: 'active',
        rowVersion: 1,
        createdAt: quantFixtureSnapshot.project.updatedAt,
        updatedAt: quantFixtureSnapshot.project.updatedAt,
      }],
      listRuns: async () => [historicalRun, {
        contract: 'legacy-daily-v1',
        id: quantFixtureSnapshot.run.id,
        projectId: quantFixtureSnapshot.project.id,
        datasetId: quantFixtureSnapshot.dataset.id,
        state: quantFixtureSnapshot.run.state,
        mode: quantFixtureSnapshot.run.mode === 'auto_research' ? 'auto' : 'plan',
        question: quantFixtureSnapshot.project.goal,
        attemptNumber: quantFixtureSnapshot.run.attemptNumber,
        parentRunId: quantFixtureSnapshot.run.continuedFrom?.parentRunId ?? null,
        seedCandidateId: quantFixtureSnapshot.run.continuedFrom?.seedCandidateId ?? null,
        refinementReason: quantFixtureSnapshot.run.continuedFrom?.reason ?? null,
        retryOfRunId: quantFixtureSnapshot.run.retryOfRunId ?? null,
        provider: quantFixtureSnapshot.run.provider,
        model: quantFixtureSnapshot.run.model,
        usedExperiments: quantFixtureSnapshot.run.usedExperiments,
        createdAt: quantFixtureSnapshot.run.startedAt,
        updatedAt: quantFixtureSnapshot.run.completedAt ?? quantFixtureSnapshot.run.startedAt,
      }],
      getRunWorkspaceSnapshot: async () => {
        openRunCalls += 1;
        return await new Promise<QuantWorkspaceSnapshot>((resolve) => { resolveRun = resolve; });
      },
    };
    await act(async () => {
      root.render(<QuantWorkspace api={api} />);
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined))));
    });
    await act(async () => {
      [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'History')?.click();
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined))));
    });
    const historicalButton = [...container.querySelectorAll<HTMLButtonElement>('.quant-run-list button')].find((button) => button.textContent?.includes('Historical run to open'));
    expect(historicalButton).toBeTruthy();
    await act(async () => {
      historicalButton!.click();
      historicalButton!.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(openRunCalls).toBe(1);
    expect(historicalButton?.getAttribute('aria-busy')).toBe('true');
    expect(historicalButton?.hasAttribute('disabled')).toBe(true);
    expect(container.textContent).toContain('Opening…');
    await act(async () => {
      resolveRun?.(quantFixtureSnapshot);
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(undefined))));
    });
    expect(container.textContent).toContain('Run could not be opened');
    expect(container.textContent).toContain(quantFixtureSnapshot.project.goal);
    expect(container.textContent).toContain('Historical run to open');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('searches questions and projects, filters outcomes, and sorts run history', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const baseRun = {
      contract: 'legacy-daily-v1' as const,
      projectId: 'project-spy', datasetId: quantFixtureSnapshot.dataset.id, parentRunId: null, seedCandidateId: null, refinementReason: null, retryOfRunId: null, mode: 'auto' as const, attemptNumber: 1, provider: 'fixture', model: null, usedExperiments: 3,
      createdAt: '2026-01-01T00:00:00Z',
    };
    const history = [
      { ...baseRun, id: 'run-new', state: 'completed', question: 'Newest SPY trend result', updatedAt: '2026-06-03T00:00:00Z' },
      { ...baseRun, id: 'run-review', state: 'waiting_for_review', question: 'SPY review decision', updatedAt: '2026-06-02T00:00:00Z' },
      { ...baseRun, id: 'run-qqq', projectId: 'project-qqq', state: 'failed', question: 'QQQ momentum failure', updatedAt: '2026-06-01T00:00:00Z' },
    ];
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      listProjects: async () => [
        { id: 'project-spy', name: 'SPY Regime Study', objective: '', status: 'active', rowVersion: 1, createdAt: baseRun.createdAt, updatedAt: history[0]!.updatedAt },
        { id: 'project-qqq', name: 'QQQ Momentum Review', objective: '', status: 'active', rowVersion: 1, createdAt: baseRun.createdAt, updatedAt: history[2]!.updatedAt },
      ],
      listRuns: async () => history,
    };
    await act(async () => { root.render(<QuantRunsPage api={api} snapshot={quantFixtureSnapshot} onOpenRun={vi.fn()} onOpenReport={vi.fn()} onStartNewResearch={vi.fn()} />); });
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); });

    const search = container.querySelector<HTMLInputElement>('input[type="search"]')!;
    const setSearch = (value: string) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(search, value); search.dispatchEvent(new Event('input', { bubbles: true })); };
    await act(async () => { setSearch('Momentum Review'); });
    expect(container.querySelectorAll('.quant-runs-table tbody tr')).toHaveLength(1);
    expect(container.textContent).toContain('QQQ momentum failure');

    const outcome = [...container.querySelectorAll<HTMLSelectElement>('select')].find((item) => item.previousElementSibling?.textContent === 'Outcome')!;
    await act(async () => { setSearch(''); outcome.value = 'review'; outcome.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(container.querySelectorAll('.quant-runs-table tbody tr')).toHaveLength(1);
    expect(container.textContent).toContain('SPY review decision');

    const sort = [...container.querySelectorAll<HTMLSelectElement>('select')].find((item) => item.previousElementSibling?.textContent === 'Sort')!;
    await act(async () => { outcome.value = 'all'; outcome.dispatchEvent(new Event('change', { bubbles: true })); sort.value = 'oldest'; sort.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(container.querySelector('.quant-runs-table tbody tr:first-child')?.textContent).toContain('QQQ momentum failure');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('limits comparison selection, lazily loads snapshots, retries partial failures, and marks incompatible context', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const runs = Array.from({ length: 5 }, (_, index) => ({
      contract: 'legacy-daily-v1' as const, id: `run-${index + 1}`, projectId: quantFixtureSnapshot.project.id, datasetId: quantFixtureSnapshot.dataset.id, parentRunId: null, seedCandidateId: null, refinementReason: null, retryOfRunId: null, state: 'completed', mode: 'auto' as const,
      question: `Historical comparison ${index + 1}`, attemptNumber: 1, provider: 'fixture', model: null, usedExperiments: 3,
      createdAt: `2026-06-0${index + 1}T00:00:00Z`, updatedAt: `2026-06-0${index + 1}T00:10:00Z`,
    }));
    const incompatible = structuredClone(quantFixtureSnapshot);
    incompatible.dataset.id = 'different-dataset';
    incompatible.dataset.symbol = 'QQQ';
    incompatible.scope.symbol = 'QQQ';
    incompatible.scope.dateRange = { start: '2020-01-02', end: '2023-12-29' };
    const snapshotCalls: string[] = [];
    let retryCount = 0;
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      listRuns: async () => runs,
      getRunWorkspaceSnapshot: async (runId) => {
        snapshotCalls.push(runId);
        if (runId === 'run-2' && retryCount++ === 0) throw new Error('Snapshot temporarily unavailable.');
        return runId === 'run-2' ? incompatible : quantFixtureSnapshot;
      },
    };
    await act(async () => { root.render(<QuantRunsPage api={api} snapshot={quantFixtureSnapshot} onOpenRun={vi.fn()} onOpenReport={vi.fn()} onStartNewResearch={vi.fn()} />); });
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    expect(snapshotCalls).toEqual([]);
    const checkboxes = [...container.querySelectorAll<HTMLInputElement>('.quant-runs-table input[type="checkbox"]')];
    for (const checkbox of checkboxes.slice(0, 4)) await act(async () => { checkbox.click(); });
    expect(checkboxes[4]?.disabled).toBe(true);
    expect(container.querySelector<HTMLButtonElement>('.quant-run-list>header .primary')?.disabled).toBe(false);
    await act(async () => { container.querySelector<HTMLButtonElement>('.quant-run-list>header .primary')?.click(); });
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    expect(snapshotCalls).toEqual(['run-5', 'run-4', 'run-3', 'run-2']);
    expect(container.textContent).toContain('Snapshot temporarily unavailable.');
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Retry')?.click(); });
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    expect(snapshotCalls.filter((id) => id === 'run-2')).toHaveLength(2);
    expect(container.textContent).toContain('Comparison context differs.');
    expect(container.textContent).toContain('Differs: dataset, symbol, research range');
    expect(container.textContent).toContain('Back to history');
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('keeps the data directory focused on selection without a redundant context bar', () => {
    const markup = renderToStaticMarkup(<QuantDataPage api={createFixtureQuantApi()} snapshot={quantFixtureSnapshot} selectedDataset={quantFixtureSnapshot.dataset} onSelect={vi.fn()} />);
    expect(markup).toContain('>Catalog<');
    expect(markup).toContain('>Connections<');
    expect(markup).toContain('Available research datasets');
    expect(markup).toContain('class="quant-research-table"');
    expect(markup).toContain('class="is-numeric">Bars');
    expect(markup).toContain('1 dataset');
    expect(markup).toContain('Current');
    expect(markup).not.toContain('Research datasets');
    expect(markup).not.toContain('quant-data-directory-context');
  });

  it('lazily previews the chosen catalog dataset and reuses its real selection action', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const btcDataset = { ...legacyFixtureDataset, id: 'dataset-btc', name: 'BTCUSDT stored daily', symbol: 'BTCUSDT', dateRange: { start: '2024-01-01', end: '2024-12-31' }, barCount: 365 };
    const bars = Array.from({ length: 60 }, (_, index) => ({ date: `2024-${String(Math.floor(index / 28) + 1).padStart(2, '0')}-${String(index % 28 + 1).padStart(2, '0')}`, open: 40_000 + index * 100, high: 40_200 + index * 100, low: 39_900 + index * 100, close: 40_100 + index * 100, volume: 10_000 + index }));
    const previewCalls: string[] = [];
    const onSelect = vi.fn();
    const api: QuantApi = {
      ...createFixtureQuantApi(),
      listDatasets: async () => [quantFixtureSnapshot.dataset, btcDataset],
      getDatasetPreview: async (datasetId) => {
        previewCalls.push(datasetId);
        return { contract: 'legacy-daily-v1', datasetId, symbol: 'BTCUSDT', interval: '1D', authenticity: 'imported', coveredStart: '2024-01-01', coveredEnd: '2024-12-31', totalBarCount: 365, returnedBarCount: bars.length, maxPoints: 240, samplingRule: 'latest_contiguous', bars };
      },
    };
    await act(async () => { root.render(<QuantDataPage api={api} snapshot={quantFixtureSnapshot} selectedDataset={quantFixtureSnapshot.dataset} onSelect={onSelect} />); });
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    expect(previewCalls).toEqual([]);
    const btcRow = [...container.querySelectorAll<HTMLTableRowElement>('tbody tr')].find((row) => row.textContent?.includes('BTCUSDT'))!;
    await act(async () => { [...btcRow.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Preview')?.click(); });
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    expect(previewCalls).toEqual(['dataset-btc']);
    expect(container.querySelector('.quant-dataset-preview')?.textContent).toContain('BTCUSDT · 1D');
    expect(container.querySelector('.quant-dataset-preview')?.textContent).toContain('SMA 20');
    expect(container.querySelector('.quant-dataset-preview')?.textContent).toContain('SMA 50');
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('.quant-dataset-preview button')].find((button) => button.textContent === 'Use for research')?.click(); });
    expect(onSelect).toHaveBeenCalledWith(btcDataset);
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('renders optional imported data quality without requiring it in legacy snapshots', () => {
    const snapshot = { ...quantFixtureSnapshot, dataset: { ...legacyFixtureDataset, quality: datasetQuality } };
    const markup = renderToStaticMarkup(<QuantInspector snapshot={snapshot} presentation={presentQuantWorkspace(snapshot)} target={{ kind: 'dataset', dataset: snapshot.dataset }} onClose={vi.fn()} />);
    expect(markup).toContain('warning · 1,564 checked bars · 2 zero-volume · 4 calendar gaps');
  });

  it('renders retained provider-fetch provenance without changing CSV compatibility', () => {
    const snapshot = {
      ...quantFixtureSnapshot,
      dataset: {
        ...legacyFixtureDataset,
        source: {
          kind: 'provider_fetch' as const,
          sourceName: 'Binance Spot public market data',
          sourceReference: 'binance-vision:/api/v3/klines',
          submittedCsvDigest: 'sha256:normalized-csv',
          marketCalendar: '24x7' as const,
          timeZone: 'UTC',
          priceAdjustment: 'unadjusted' as const,
          providerId: 'binance_spot',
          providerResponseAttestations: [{ kind: 'daily_bars', digest: 'sha256:provider-response', sourceReference: 'binance-vision:/api/v3/klines' }],
          retrievedAt: '2026-07-18T00:00:00Z',
          requestedLimit: 365,
          returnedBarCount: 364,
          droppedIncompleteCount: 1,
          normalizationNote: 'Dropped the incomplete current daily candle.',
          attestationStatus: 'provider_retrieved',
        },
      },
    };
    const markup = renderToStaticMarkup(<QuantInspector snapshot={snapshot} presentation={presentQuantWorkspace(snapshot)} target={{ kind: 'dataset', dataset: snapshot.dataset }} onClose={vi.fn()} />);
    expect(markup).toContain('binance_spot');
    expect(markup).toContain('364 bars from 365 response limit · 1 incomplete dropped · provider_retrieved');
    expect(markup).toContain('Dropped the incomplete current daily candle.');
  });

  it('renders Nasdaq corporate-action attestations and an explicit split-coverage warning', () => {
    const snapshot = {
      ...quantFixtureSnapshot,
      dataset: {
        ...legacyFixtureDataset,
        source: {
          kind: 'provider_fetch' as const,
          sourceName: 'Nasdaq Equity provider data',
          sourceReference: 'nasdaq-equity:AAPL',
          submittedCsvDigest: null,
          marketCalendar: 'XNAS' as const,
          timeZone: 'America/New_York',
          priceAdjustment: 'unadjusted' as const,
          providerId: 'nasdaq_equity',
          providerResponseAttestations: [
            { kind: 'daily_bars', digest: 'sha256:ohlcv', sourceReference: 'nasdaq-equity:AAPL:ohlcv' },
            { kind: 'instrument_info', digest: 'sha256:info', sourceReference: 'nasdaq-equity:AAPL:info' },
            { kind: 'dividends', digest: 'sha256:dividends', sourceReference: 'nasdaq-equity:AAPL:dividends' },
          ],
          retrievedAt: '2026-07-18T00:00:00Z',
          requestedLimit: 730,
          returnedBarCount: 500,
          droppedIncompleteCount: 0,
          normalizationNote: 'Normalized provider sessions to daily bars.',
          attestationStatus: 'provider_retrieved',
          priceAdjustmentVerificationStatus: 'not_applicable',
          corporateActionsAttestation: {
            dividendsStatus: 'retrieved_unverified',
            splitsStatus: 'unavailable',
            coverageStart: '2024-07-18',
            coverageEnd: '2026-07-18',
            dividendCoverageStart: '2024-07-18',
            dividendCoverageEnd: '2026-07-18',
            splitCoverageStart: '2026-01-01',
            splitCoverageEnd: '2026-07-18',
            splitSnapshotAsOf: '2026-07-18',
            splitCompletenessStatus: 'current_snapshot_only',
            splitReconciliationStatus: 'not_reconciled',
            splitEvents: [{ effectiveDate: '2026-06-15', ratioNumerator: 2, ratioDenominator: 1 }],
            dividendEventCount: 82,
            splitEventCount: null,
            note: 'Dividend coverage is retained; split coverage was unavailable.',
          },
        },
      },
    };
    const markup = renderToStaticMarkup(<QuantInspector snapshot={snapshot} presentation={presentQuantWorkspace(snapshot)} target={{ kind: 'dataset', dataset: snapshot.dataset }} onClose={vi.fn()} />);
    expect(markup).toContain('XNAS · America/New_York');
    expect(markup).toContain('not applicable');
    expect(markup).toContain('sha256:ohlcv');
    expect(markup).toContain('sha256:dividends');
    expect(markup).toContain('retrieved unverified · 82 events · 2024-07-18 – 2026-07-18');
    expect(markup).toContain('Warning: split coverage unavailable.');
    expect(markup).toContain('2026-01-01 – 2026-07-18 · snapshot 2026-07-18');
    expect(markup).toContain('current snapshot only · not reconciled · current snapshot only; not historical completeness.');
    expect(markup).toContain('2026-06-15: 2:1');
  });

  it('renders the Run Monitor with state, provider, trace reference, and pinned dataset digest', () => {
    const runningSnapshot = { ...quantFixtureSnapshot, run: { ...quantFixtureSnapshot.run, state: 'running_experiments' as const, legalCommands: ['cancel_run'] as QuantCommand[], provider: 'DeepSeek', model: 'deepseek-chat' } };
    const runningPresentation = presentQuantWorkspace(runningSnapshot);
    const markup = renderToStaticMarkup(<QuantRunMonitor snapshot={runningSnapshot} presentation={runningPresentation} onAction={vi.fn()} isPolling />);
    expect(markup).toContain('Run monitor');
    expect(markup).toContain('Evaluating approved candidates');
    expect(markup).toContain('DeepSeek · deepseek-chat');
    expect(markup).toContain('fixture-trace-spy-01');
    expect(markup).toContain(runningSnapshot.dataset.digest.slice(0, 19));
    expect(markup).toContain('Live · polling');
    expect(markup).toContain('Cancel Run');
    expect(markup).toContain('role="progressbar"');
    expect(markup).toContain('10 of 10 plan steps');
    expect(markup).toContain('Run details');
    expect(markup).not.toContain('>●<');
  });

  it('collects explicit feedback before the Run Monitor requests plan changes', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onAction = vi.fn();
    const snapshot = structuredClone(quantFixtureSnapshot);
    snapshot.report = null;
    snapshot.run = { ...snapshot.run, state: 'waiting_plan_approval', legalCommands: ['approve_plan', 'request_plan_changes', 'cancel_run'] };
    await act(async () => { root.render(<QuantRunMonitor snapshot={snapshot} presentation={presentQuantWorkspace(snapshot)} onAction={onAction} isPolling={false} />); });
    await act(async () => { [...container.querySelectorAll<HTMLButtonElement>('.quant-run-monitor-controls button')].find((button) => button.textContent === 'Request Changes')?.click(); });
    const input = container.querySelector<HTMLTextAreaElement>('#quant-monitor-plan-change')!;
    expect(input).not.toBeNull();
    expect(onAction).not.toHaveBeenCalled();
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(input, 'Prioritize a mean-reversion comparison.');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { container.querySelector<HTMLFormElement>('.quant-run-monitor-lower .pq-plan-change-form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ kind: 'request_plan_changes' }), { changeRequest: 'Prioritize a mean-reversion comparison.' });
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it('shows terminal/immutable state and hides live polling badge for completed runs', () => {
    const terminalPresentation = presentQuantWorkspace(quantFixtureSnapshot);
    const markup = renderToStaticMarkup(<QuantRunMonitor snapshot={quantFixtureSnapshot} presentation={terminalPresentation} onAction={vi.fn()} isPolling={false} />);
    expect(markup).toContain('Immutable');
    expect(markup).not.toContain('Live · polling');
    expect(markup).not.toContain('role="progressbar"');
    expect(markup).toContain('Run details');
  });

  it('distinguishes ready and review gates from active polling', () => {
    const readySnapshot = { ...quantFixtureSnapshot, report: null, run: { ...quantFixtureSnapshot.run, state: 'draft' as const } };
    const reviewSnapshot = { ...quantFixtureSnapshot, report: null, run: { ...quantFixtureSnapshot.run, state: 'waiting_for_review' as const } };
    const ready = renderToStaticMarkup(<QuantRunMonitor snapshot={readySnapshot} presentation={presentQuantWorkspace(readySnapshot)} onAction={vi.fn()} isPolling={false} />);
    const review = renderToStaticMarkup(<QuantRunMonitor snapshot={reviewSnapshot} presentation={presentQuantWorkspace(reviewSnapshot)} onAction={vi.fn()} isPolling={false} />);
    expect(ready).toContain('>Ready<');
    expect(ready).toContain('Awaiting start');
    expect(review).toContain('Awaiting review');
    expect(ready).not.toContain('Live · polling');
    expect(review).not.toContain('Live · polling');
  });

  it('gates Run Monitor controls to API-legal commands and omits unsupported pause/resume', () => {
    const repairSnapshot = { ...quantFixtureSnapshot, run: { ...quantFixtureSnapshot.run, state: 'repairing' as const, legalCommands: ['cancel_run'] as QuantCommand[], provider: 'Mock Agent', model: null } };
    const repairPresentation = presentQuantWorkspace(repairSnapshot);
    const markup = renderToStaticMarkup(<QuantRunMonitor snapshot={repairSnapshot} presentation={repairPresentation} onAction={vi.fn()} isPolling />);
    expect(markup).toContain('Cancel Run');
    expect(markup).not.toContain('Pause');
    expect(markup).not.toContain('Resume');
    expect(markup).not.toContain('Retry as New Attempt');
    expect(markup).toContain('Repairing candidate');
    expect(markup).toContain('Retrying a recoverable experiment');
  });

  it('freezes every Run Monitor action while one command is being submitted', () => {
    const runningSnapshot = { ...quantFixtureSnapshot, run: { ...quantFixtureSnapshot.run, state: 'running_experiments' as const, legalCommands: ['run_fixture', 'cancel_run'] as QuantCommand[] } };
    const markup = renderToStaticMarkup(<QuantRunMonitor snapshot={runningSnapshot} presentation={presentQuantWorkspace(runningSnapshot)} onAction={vi.fn()} isPolling busy />);
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain('Submitting command…');
    expect(markup.match(/disabled=""/g)).toHaveLength(2);
  });

  it('surfaces retry and report actions when legal for the current API snapshot', () => {
    const failedSnapshot = { ...quantFixtureSnapshot, run: { ...quantFixtureSnapshot.run, state: 'failed' as const, legalCommands: ['retry_run'] as QuantCommand[] } };
    const failedPresentation = presentQuantWorkspace(failedSnapshot);
    const markup = renderToStaticMarkup(<QuantRunMonitor snapshot={failedSnapshot} presentation={failedPresentation} onAction={vi.fn()} isPolling={false} />);
    expect(markup).toContain('Retry as New Attempt');
    expect(markup).toContain('Open Diagnostics');
  });
});
