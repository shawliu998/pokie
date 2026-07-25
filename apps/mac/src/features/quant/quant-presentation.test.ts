import { describe, expect, it } from 'vitest';
import type { QuantExecutableResearchPlan, QuantWorkspaceSnapshot } from '../../quant-domain';
import type { QuantRunHistoryItem } from '../../quant-api';
import { quantFixtureSnapshot } from './quant-fixtures';
import { canContinueResearch, formatTradeHolding, presentQuantWorkspace, presentResearchCopilot, presentStrategyScopeDecision, projectDecisionLedger, projectEvidenceFocusActions, projectNextResearchProposal, projectQuantRunRelationship, projectTerminalDecision, resolveEvidenceFocusIntent, quantRunHistoryMatchesSnapshot, quantRunRelationshipLabel } from './quant-presentation';

function fixture(overrides: Partial<QuantWorkspaceSnapshot> = {}): QuantWorkspaceSnapshot {
  return { ...structuredClone(quantFixtureSnapshot), ...overrides };
}

function retainValidation(snapshot: QuantWorkspaceSnapshot, status: 'pass' | 'not_evaluated', includeHoldout = false) {
  const candidate = snapshot.candidates.find((item) => item.id === 'candidate-b')!.metrics;
  const benchmark = snapshot.benchmark!;
  snapshot.report = {
    ...snapshot.report!,
    generalization: {
      status,
      reason: status === 'pass' ? 'The retained sealed holdout passed.' : 'No fresh sealed holdout was evaluated.',
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
      ...(includeHoldout ? { holdout: { candidate, benchmark } } : {}),
    },
  };
}

describe('presentQuantWorkspace', () => {
  it('projects and validates only retained, run-bound evidence focus intents', () => {
    const snapshot = fixture();
    retainValidation(snapshot, 'pass', true);
    snapshot.run.continuedFrom = {
      parentRunId: 'source-run',
      seedCandidateId: 'candidate-b',
      candidateName: 'SMA 50/200',
      sourceQuestion: 'Source research question.',
      reason: 'Test one bounded change.',
    };
    const actions = projectEvidenceFocusActions(snapshot, 'candidate-b');

    expect(actions).toEqual(expect.arrayContaining([
      expect.objectContaining({ runId: snapshot.run.id, candidateId: 'candidate-b', destination: 'analysis', target: 'drawdown' }),
      expect.objectContaining({ runId: snapshot.run.id, candidateId: 'candidate-b', destination: 'analysis', target: 'trade' }),
      expect.objectContaining({ runId: snapshot.run.id, candidateId: 'candidate-b', destination: 'report', target: 'validation' }),
      expect.objectContaining({ runId: snapshot.run.id, candidateId: 'candidate-b', destination: 'runs', target: 'source_comparison', sourceRunId: 'source-run' }),
    ]));

    const drawdown = {
      id: 'evidence-focus-1',
      ...actions.find((action) => action.target === 'drawdown')!,
    };
    expect(resolveEvidenceFocusIntent(snapshot, drawdown)).toMatchObject({
      destination: 'analysis',
      target: 'drawdown',
      candidateId: 'candidate-b',
      evidenceReference: expect.stringContaining('candidate-b'),
    });
    expect(resolveEvidenceFocusIntent(snapshot, { ...drawdown, id: 'evidence-focus-2', runId: 'other-run' })).toBeNull();
    expect(resolveEvidenceFocusIntent(snapshot, { ...drawdown, id: 'evidence-focus-3', candidateId: 'missing-candidate' })).toBeNull();
    const sourceComparison = actions.find((action) => action.target === 'source_comparison')!;
    expect(resolveEvidenceFocusIntent(snapshot, { id: 'evidence-focus-source', ...sourceComparison })).toMatchObject({
      destination: 'runs',
      target: 'source_comparison',
      candidateId: 'candidate-b',
      evidenceReference: expect.stringContaining('source-run'),
    });
    expect(resolveEvidenceFocusIntent(snapshot, { id: 'evidence-focus-forged-source', ...sourceComparison, sourceRunId: 'forged-source' })).toBeNull();

    const withoutTrades = fixture();
    withoutTrades.trades = withoutTrades.trades.filter((trade) => trade.candidateId !== 'candidate-b');
    expect(projectEvidenceFocusActions(withoutTrades, 'candidate-b').some((action) => action.target === 'trade')).toBe(false);
    expect(resolveEvidenceFocusIntent(withoutTrades, {
      id: 'evidence-focus-4',
      runId: withoutTrades.run.id,
      candidateId: 'candidate-b',
      destination: 'analysis',
      target: 'trade',
      tradeId: 'missing-trade',
    })).toBeNull();

    const trade = snapshot.trades.find((item) => item.candidateId === 'candidate-b')!;
    expect(resolveEvidenceFocusIntent(snapshot, {
      id: 'evidence-focus-report-trades',
      runId: snapshot.run.id,
      candidateId: 'candidate-b',
      destination: 'report',
      target: 'trades',
      tradeId: trade.id,
    })).toMatchObject({
      destination: 'report',
      target: 'trades',
      evidenceReference: expect.stringContaining(trade.id),
    });
  });

  it('focuses a retained validation status without manufacturing holdout metrics', () => {
    const snapshot = fixture();
    retainValidation(snapshot, 'not_evaluated');
    const validation = projectEvidenceFocusActions(snapshot, 'candidate-b')
      .find((action) => action.target === 'validation');

    expect(validation).toMatchObject({
      runId: snapshot.run.id,
      candidateId: 'candidate-b',
      destination: 'report',
      target: 'validation',
      label: 'Open validation status',
    });
    expect(resolveEvidenceFocusIntent(snapshot, { id: 'evidence-focus-validation', ...validation! })).toMatchObject({
      destination: 'report',
      target: 'validation',
    });
    expect(snapshot.report?.generalization?.holdout).toBeUndefined();
  });

  it('projects adaptation and structured-stop decision ledgers without holdout evidence', () => {
    const adapted = fixture();
    const adaptedCandidate = {
      ...adapted.candidates[2]!,
      evolution: {
        ...adapted.candidates[2]!.evolution!,
        origin: 'training_feedback' as const,
        changeRationale: 'Widen the breakout window after the initial training comparison.',
        feedbackReferenceCandidateId: 'candidate-a',
        feedbackReferenceCandidateName: 'Candidate A · SMA 20/100',
        selectionReason: 'Selected by the approved training objective after the adaptation.',
      },
    };
    adapted.candidates = [adapted.candidates[0]!, adapted.candidates[1]!, adaptedCandidate];
    adapted.report = {
      ...adapted.report!,
      selectionDecision: {
        basis: 'approved_objective_rank',
        selectedCandidateId: adaptedCandidate.id,
      },
      generalization: {
        ...adapted.report!.generalization!,
        reason: 'SECRET HOLDOUT REASON',
        selectedCandidateId: 'candidate-a',
      },
    };

    const adaptedLedger = projectDecisionLedger(adapted);
    expect(adaptedLedger).toMatchObject({
      path: 'adapted_candidate',
      initialCandidates: [{ id: 'candidate-a' }, { id: 'candidate-b' }],
      observation: { referenceCandidateId: 'candidate-a' },
      outcome: {
        kind: 'candidate',
        candidateId: 'candidate-c',
        rationale: 'Widen the breakout window after the initial training comparison.',
      },
      finalChoice: {
        candidateId: 'candidate-c',
        basis: 'approved_objective_rank',
        selectionReason: 'Selected by the approved training objective after the adaptation.',
      },
    });
    expect(JSON.stringify(adaptedLedger)).not.toContain('SECRET HOLDOUT');

    const stopped = fixture();
    stopped.candidates = stopped.candidates.slice(0, 2);
    stopped.report = {
      ...stopped.report!,
      selectionDecision: {
        basis: 'approved_objective_rank',
        selectedCandidateId: 'candidate-a',
      },
      generalization: {
        ...stopped.report!.generalization!,
        reason: 'ANOTHER SECRET HOLDOUT REASON',
        selectedCandidateId: 'candidate-b',
      },
      iterationStop: {
        reason: 'insufficient_action_budget',
        referenceCandidateId: 'candidate-a',
      },
    } as NonNullable<QuantWorkspaceSnapshot['report']>;

    const stoppedLedger = projectDecisionLedger(stopped);
    expect(stoppedLedger).toMatchObject({
      path: 'structured_stop',
      observation: { referenceCandidateId: 'candidate-a' },
      outcome: {
        kind: 'stop',
        reason: 'insufficient_action_budget',
        referenceCandidateId: 'candidate-a',
      },
      finalChoice: { candidateId: 'candidate-a', basis: 'approved_objective_rank' },
    });
    expect(JSON.stringify(stoppedLedger)).not.toContain('SECRET HOLDOUT');

    const repairSnapshot = structuredClone(adapted);
    const repairCandidate = repairSnapshot.candidates.find((candidate) => candidate.id === 'candidate-c')!;
    repairCandidate.evolution = {
      ...repairCandidate.evolution!,
      replanRepair: {
        rejectedAction: 'refine_parameters',
        correctedAction: 'switch_approved_family',
        retainedInputs: true,
        outcome: 'candidate_created',
      },
    };
    const repairLedger = projectDecisionLedger(repairSnapshot);
    expect(repairLedger?.outcome).toMatchObject({
      kind: 'candidate',
      candidateId: 'candidate-c',
      replanRepair: {
        rejectedAction: 'refine_parameters',
        correctedAction: 'switch_approved_family',
        retainedInputs: true,
        outcome: 'candidate_created',
      },
    });

    const legacyDecision = fixture();
    legacyDecision.candidates = adapted.candidates;
    legacyDecision.report = {
      ...adapted.report,
      selectionDecision: { basis: 'approved_objective_rank' },
    };
    expect(projectDecisionLedger(legacyDecision)).toBeNull();
  });

  it('projects only one identity-consistent terminal decision from retained evidence', () => {
    const base = fixture();
    base.candidates = base.candidates.map((candidate) => ({ ...candidate, canSeedResearch: candidate.id === 'candidate-b' }));
    base.report = {
      ...base.report!,
      selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' },
      generalization: { ...base.report!.generalization!, status: 'pass', selectedCandidateId: 'candidate-b', reason: 'The final candidate passed the retained sealed holdout.' },
    };
    const passed = projectTerminalDecision(base);
    expect(passed).toMatchObject({
      finalCandidateId: 'candidate-b',
      holdoutStatus: 'pass',
      decision: 'stop',
      canRefine: false,
      selectionReason: expect.any(String),
    });

    const unseedablePass = structuredClone(base);
    unseedablePass.candidates = unseedablePass.candidates.map((candidate) => ({ ...candidate, canSeedResearch: false }));
    expect(projectTerminalDecision(unseedablePass)).toMatchObject({ finalCandidateId: 'candidate-b', holdoutStatus: 'pass', decision: 'stop', canRefine: false });

    for (const status of ['fail', 'inconclusive'] as const) {
      const refinement = structuredClone(base);
      refinement.report!.generalization = { ...refinement.report!.generalization!, status, reason: `Retained ${status} evidence.` };
      expect(projectTerminalDecision(refinement)).toMatchObject({
        finalCandidateId: 'candidate-b',
        holdoutStatus: status,
        decision: 'refine',
        canRefine: true,
        refinement: {
          proposedChange: expect.any(String),
          evidenceBasis: `Retained ${status} evidence.`,
          successCondition: expect.any(String),
          stopCondition: expect.any(String),
        },
      });
    }

    const unseedableRefinement = structuredClone(base);
    unseedableRefinement.candidates = unseedableRefinement.candidates.map((candidate) => ({ ...candidate, canSeedResearch: false }));
    unseedableRefinement.report!.generalization = { ...unseedableRefinement.report!.generalization!, status: 'fail', reason: 'The retained final choice cannot seed another run.' };
    expect(projectTerminalDecision(unseedableRefinement)).toMatchObject({ finalCandidateId: 'candidate-b', holdoutStatus: 'fail', decision: 'refine', canRefine: false });
    expect(projectTerminalDecision(unseedableRefinement)?.refinement).toBeUndefined();

    const conflictingIdentity = structuredClone(base);
    conflictingIdentity.report!.generalization = { ...conflictingIdentity.report!.generalization!, selectedCandidateId: 'candidate-a' };
    expect(projectTerminalDecision(conflictingIdentity)).toBeNull();

    const legacyReasonFallback = structuredClone(base);
    legacyReasonFallback.candidates = legacyReasonFallback.candidates.map((candidate) => candidate.id === 'candidate-b'
      ? { ...candidate, evolution: { ...candidate.evolution!, selectionReason: '   ' } }
      : candidate);
    expect(projectTerminalDecision(legacyReasonFallback)).toMatchObject({ selectionReason: 'approved_objective_rank', decision: 'stop' });

    const historicalState = structuredClone(base);
    historicalState.run = { ...historicalState.run, state: 'failed' };
    expect(projectTerminalDecision(historicalState)).toBeNull();
  });

  it('projects Current, Observation and one legal primary Next action across the lifecycle', () => {
    const cases: Array<[QuantWorkspaceSnapshot['run']['state'], QuantWorkspaceSnapshot['run']['legalCommands'], string]> = [
      ['draft', ['generate_plan', 'start_auto_research'], 'Generate plan'],
      ['planning', ['cancel_run'], 'Cancel run'],
      ['waiting_plan_approval', ['approve_plan', 'request_plan_changes', 'cancel_run'], 'Approve & run'],
      ['queued', ['approve_execution', 'cancel_run'], 'Approve execution'],
      ['loading_data', ['cancel_run'], 'Cancel run'],
      ['generating_candidates', ['cancel_run'], 'Cancel run'],
      ['running_experiments', ['cancel_run'], 'Cancel run'],
      ['repairing', ['cancel_run'], 'Cancel run'],
      ['validating', ['cancel_run'], 'Cancel run'],
      ['generating_report', ['cancel_run'], 'Cancel run'],
      ['waiting_for_review', ['complete_review'], 'Complete review'],
      ['failed', ['retry_run'], 'Retry run'],
      ['cancelled', ['retry_run'], 'Retry run'],
      ['unknown', [], 'New research'],
    ];
    for (const [state, legalCommands, primaryLabel] of cases) {
      const snapshot = fixture();
      snapshot.report = ['waiting_for_review'].includes(state) ? snapshot.report : null;
      snapshot.run = { ...snapshot.run, state, legalCommands };
      const copilot = presentResearchCopilot(snapshot, { selectedCandidateId: 'candidate-b' });
      expect(copilot.current.question).toBe(snapshot.project.goal);
      expect(copilot.current.title).toBeTruthy();
      expect(copilot.observation.detail).toBeTruthy();
      if (['draft', 'planning', 'waiting_plan_approval', 'queued'].includes(state)) {
        expect(copilot.observation.title).toBe('No experiment evidence yet');
      }
      expect(copilot.next.actions.filter((action) => action.tone === 'primary')).toEqual([
        expect.objectContaining({ label: primaryLabel }),
      ]);
    }

    const completed = fixture();
    completed.candidates = completed.candidates.map((candidate) => ({ ...candidate, canSeedResearch: candidate.id === 'candidate-a' }));
    completed.report = {
      ...completed.report!,
      selectionDecision: { basis: 'approved_objective_rank', selectedCandidateId: 'candidate-b' },
      generalization: { ...completed.report!.generalization!, status: 'pass', selectedCandidateId: 'candidate-b', reason: 'The final choice passed the retained holdout.' },
    };
    const completedCopilot = presentResearchCopilot(completed, { selectedCandidateId: 'candidate-a' });
    expect(completedCopilot.next.actions.filter((action) => action.tone === 'primary')).toEqual([
      expect.objectContaining({ kind: 'open_report', label: 'Open decision' }),
    ]);
    expect(completedCopilot.next.actions.map((action) => action.kind)).not.toContain('continue_research');
  });

  it('projects strategy scope without inventing commands and blocks unsupported approval', () => {
    const supportedPlan: QuantExecutableResearchPlan = {
      candidateFamilies: ['sma_crossover'],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Compare completed candidates.'],
    };
    expect(presentStrategyScopeDecision(supportedPlan)).toMatchObject({
      status: 'supported',
      label: 'Supported · Legacy plan',
      legacy: true,
      blocksApproval: false,
    });
    const restoredLegacyPlan: QuantExecutableResearchPlan = {
      ...supportedPlan,
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'supported',
        reason: 'Legacy retained plan predates strategy-scope classification and is treated as supported.',
        excludedBehaviors: [],
      },
    };
    expect(presentStrategyScopeDecision(restoredLegacyPlan)).toMatchObject({
      status: 'supported',
      label: 'Supported · Legacy plan',
      legacy: true,
      blocksApproval: false,
    });
    const currentSupportedPlan: QuantExecutableResearchPlan = {
      ...supportedPlan,
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'supported',
        reason: 'The request fits the registered long-or-cash strategy templates.',
        excludedBehaviors: [],
      },
    };
    expect(presentStrategyScopeDecision(currentSupportedPlan)).toMatchObject({
      status: 'supported',
      label: 'Supported',
      legacy: false,
      blocksApproval: false,
    });
    const malformedLegacyMarker: QuantExecutableResearchPlan = {
      ...restoredLegacyPlan,
      strategyScope: {
        ...restoredLegacyPlan.strategyScope!,
        excludedBehaviors: ['Unexpected exclusion'],
      },
    };
    expect(presentStrategyScopeDecision(malformedLegacyMarker)).toMatchObject({
      status: 'supported',
      label: 'Supported',
      legacy: false,
    });

    const bounded = fixture();
    bounded.researchPlan = {
      ...supportedPlan,
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'bounded_proxy',
        reason: 'The requested rule needs a registered proxy.',
        proxyDescription: 'Use a bounded moving-average proxy.',
        excludedBehaviors: ['Exact MACD parity'],
      },
    };
    bounded.run = {
      ...bounded.run,
      mode: 'auto_research',
      state: 'waiting_plan_approval',
      legalCommands: ['approve_plan', 'request_plan_changes', 'cancel_run'],
    };
    const boundedCopilot = presentResearchCopilot(bounded);
    expect(boundedCopilot.next.detail).toContain('before Qurio runs experiments');
    expect(boundedCopilot.next.actions.map((action) => action.kind)).toEqual([
      'approve_plan',
      'request_plan_changes',
      'cancel_run',
    ]);

    const unsupported = fixture();
    unsupported.researchPlan = {
      candidateFamilies: [],
      selectionObjective: 'risk_adjusted_return',
      completionCriteria: ['Revise the request before experiments begin.'],
      strategyScope: {
        schemaVersion: 'quant-strategy-scope-v1',
        status: 'unsupported',
        reason: 'The request requires long-short portfolio logic.',
        excludedBehaviors: ['Short positions', 'Cross-asset ranking'],
      },
    };
    unsupported.run = {
      ...unsupported.run,
      state: 'waiting_plan_approval',
      legalCommands: ['ask', 'approve_plan', 'request_plan_changes', 'cancel_run'],
    };
    const unsupportedCopilot = presentResearchCopilot(unsupported);
    expect(unsupportedCopilot.canAsk).toBe(false);
    expect(unsupportedCopilot.next.actions).toEqual([
      { kind: 'request_plan_changes', label: 'Request changes', tone: 'primary' },
      { kind: 'cancel_run', label: 'Cancel run', tone: 'default' },
    ]);
    expect(presentQuantWorkspace(unsupported).actions.map((action) => action.kind)).toEqual([
      'request_plan_changes',
      'cancel_run',
    ]);

    unsupported.run = {
      ...unsupported.run,
      state: 'running_experiments',
      legalCommands: [
        'ask',
        'approve_plan',
        'approve_execution',
        'run_fixture',
        'request_plan_changes',
        'cancel_run',
      ],
    };
    const malformedStateCopilot = presentResearchCopilot(unsupported);
    expect(malformedStateCopilot.canAsk).toBe(false);
    expect(malformedStateCopilot.next.actions.map((action) => action.kind)).toEqual([
      'cancel_run',
    ]);
    expect(presentQuantWorkspace(unsupported).actions.map((action) => action.kind)).toEqual([
      'request_plan_changes',
      'cancel_run',
    ]);
  });

  it('keeps provisional validation free of retained holdout conclusions', () => {
    const snapshot = fixture();
    snapshot.run = { ...snapshot.run, state: 'validating', legalCommands: ['cancel_run'] };
    snapshot.report = { ...snapshot.report!, conclusion: 'SECRET HOLDOUT CONCLUSION', proposedNextStep: 'SECRET HOLDOUT NEXT' };
    const copilot = presentResearchCopilot(snapshot);
    expect(JSON.stringify(copilot)).not.toContain('SECRET HOLDOUT');
    expect(copilot.observation.detail).toContain('provisional');
  });

  it('never presents stale holdout evidence as the result of a failed or cancelled run', () => {
    for (const state of ['failed', 'cancelled'] as const) {
      const snapshot = fixture();
      snapshot.run = { ...snapshot.run, state, legalCommands: ['retry_run'] };
      snapshot.report = {
        ...snapshot.report!,
        conclusion: 'STALE HOLDOUT CONCLUSION',
        proposedNextStep: 'STALE HOLDOUT NEXT STEP',
        generalization: {
          ...snapshot.report!.generalization!,
          status: 'pass',
          reason: 'STALE HOLDOUT PASSED 99.9%',
        },
      };

      const overview = presentQuantWorkspace(snapshot);
      const copilot = presentResearchCopilot(snapshot);
      expect(overview.decision.title).toBe(state === 'failed' ? 'Research failed safely' : 'Research was cancelled');
      expect(overview.candidates.map((candidate) => candidate.verdictLabel)).not.toContain('Passed sealed holdout');
      expect(JSON.stringify(overview)).not.toContain('STALE HOLDOUT');
      expect(copilot.observation.title).toBe(overview.decision.title);
      expect(JSON.stringify(copilot)).not.toContain('STALE HOLDOUT');
    }
  });

  it('makes both legacy and market historical projections read-only', () => {
    for (const contract of ['legacy-daily-v1', 'market-v2-public'] as const) {
      const snapshot = fixture();
      snapshot.run = { ...snapshot.run, contract, legalCommands: ['ask', 'approve_plan', 'cancel_run', 'retry_run'] };
      const copilot = presentResearchCopilot(snapshot, { selectedCandidateId: 'candidate-b', isHistorical: true });
      expect(copilot.canAsk).toBe(false);
      expect(copilot.readOnly).toBe(true);
      expect(copilot.next.actions[0]).toEqual({ kind: 'return_latest', label: 'Return to latest', tone: 'primary' });
      expect(copilot.next.actions.map((action) => action.kind)).not.toEqual(expect.arrayContaining(['approve_plan', 'cancel_run', 'retry_run', 'continue_research']));
    }
  });

  it('preserves intraday UTC and annualization context without recomputing it', () => {
    for (const [interval, periodsPerYear] of [['1h', 8760], ['4h', 2190]] as const) {
      const snapshot = fixture();
      snapshot.scope = { ...snapshot.scope, interval, dateRange: { start: '2026-01-01T00:00:00Z', end: '2026-02-01T00:00:00Z' } };
      snapshot.kernelCheck = { ...snapshot.kernelCheck, interval, periodsPerYear };
      const copilot = presentResearchCopilot(snapshot);
      expect(copilot.current.question).toBe(snapshot.project.goal);
      expect(snapshot.scope.dateRange.start).toMatch(/Z$/);
      expect(snapshot.kernelCheck.periodsPerYear).toBe(periodsPerYear);
    }
  });

  it('projects root, continuation and retry relationships only from compatible loaded history', () => {
    const base = {
      contract: 'legacy-daily-v1' as const,
      projectId: 'project-1', datasetId: 'dataset-1', state: 'completed', mode: 'auto' as const,
      question: 'Test retained evidence.', provider: 'fixture', model: null, usedExperiments: 3,
      seedCandidateId: null, refinementReason: null,
      createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
    };
    const root: QuantRunHistoryItem = { ...base, id: 'root', attemptNumber: 1, parentRunId: null, retryOfRunId: null };
    const continued: QuantRunHistoryItem = { ...base, id: 'continued', attemptNumber: 1, parentRunId: root.id, seedCandidateId: 'candidate-a', refinementReason: 'Test a revised risk constraint.', retryOfRunId: null };
    const rootRetry: QuantRunHistoryItem = { ...base, id: 'root-retry', attemptNumber: 2, parentRunId: null, retryOfRunId: root.id };
    const refinedRetry: QuantRunHistoryItem = { ...base, id: 'continued-retry', attemptNumber: 2, parentRunId: root.id, seedCandidateId: 'candidate-a', refinementReason: 'Test a revised risk constraint.', retryOfRunId: continued.id };
    const marketBase = {
      ...base,
      contract: 'market-v2-public' as const,
      datasetId: 'market-dataset-4h',
      symbol: 'BTCUSDT', interval: '4h' as const, periodsPerYear: 2190,
      researchStartUtc: '2024-01-01T00:00:00Z', researchEndUtc: '2024-12-31T20:00:00Z',
      datasetDigest: `sha256:${'a'.repeat(64)}`,
      runtimeDescriptorDigest: `sha256:${'b'.repeat(64)}`,
      sealedSplitDigest: `sha256:${'c'.repeat(64)}`,
    };
    const marketParent: QuantRunHistoryItem = { ...marketBase, id: 'market-continued', attemptNumber: 1, parentRunId: 'market-root', seedCandidateId: 'candidate-b', refinementReason: 'Retain the pinned market cadence.', retryOfRunId: null };
    const marketRoot: QuantRunHistoryItem = { ...marketBase, id: 'market-root', attemptNumber: 1, parentRunId: null, retryOfRunId: null };
    const marketRetry: QuantRunHistoryItem = { ...marketBase, id: 'market-continued-retry', attemptNumber: 2, parentRunId: marketRoot.id, seedCandidateId: 'candidate-b', refinementReason: 'Retain the pinned market cadence.', retryOfRunId: marketParent.id };
    const loaded = [root, continued, rootRetry, refinedRetry, marketParent, marketRoot, marketRetry];

    expect(quantRunRelationshipLabel(projectQuantRunRelationship(root, loaded))).toBe('Root version');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship(continued, loaded))).toBe('Continued version');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship(rootRetry, loaded))).toBe('Root version · Retry attempt 2');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship(refinedRetry, loaded))).toBe('Continued version · Retry attempt 2');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship(marketParent, loaded))).toBe('Continued version');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship(marketRetry, loaded))).toBe('Continued version · Retry attempt 2');
    expect(projectQuantRunRelationship(continued, loaded)).toMatchObject({ sourceRunId: root.id });
    expect(projectQuantRunRelationship(rootRetry, loaded)).toMatchObject({ priorAttemptRunId: root.id });
    expect(projectQuantRunRelationship(refinedRetry, loaded)).toMatchObject({ sourceRunId: root.id, priorAttemptRunId: continued.id });
    expect(projectQuantRunRelationship(marketParent, loaded)).toMatchObject({ sourceRunId: marketRoot.id });
    expect(projectQuantRunRelationship(marketRetry, loaded)).toMatchObject({ sourceRunId: marketRoot.id, priorAttemptRunId: marketParent.id });

    expect(quantRunRelationshipLabel(projectQuantRunRelationship({ ...continued, datasetId: 'other-dataset' }, loaded))).toBe('Relationship unavailable');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship({ ...rootRetry, attemptNumber: 3 }, loaded))).toBe('Relationship unavailable');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship({ ...refinedRetry, parentRunId: null }, loaded))).toBe('Relationship unavailable');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship({ ...root, parentRunId: 'continued' }, [root, continued]))).toBe('Relationship unavailable');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship({ ...marketParent, periodsPerYear: 365 }, loaded))).toBe('Relationship unavailable');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship({ ...marketParent, researchEndUtc: '2024-12-31T16:00:00Z', runtimeDescriptorDigest: `sha256:${'d'.repeat(64)}`, sealedSplitDigest: `sha256:${'e'.repeat(64)}` }, loaded))).toBe('Continued version');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship({ ...marketRetry, researchEndUtc: '2024-12-31T16:00:00Z' }, loaded))).toBe('Relationship unavailable');
    expect(quantRunRelationshipLabel(projectQuantRunRelationship({ ...continued, refinementReason: '  Test a revised risk constraint.' }, loaded))).toBe('Relationship unavailable');

    const parentCycleA: QuantRunHistoryItem = { ...continued, id: 'cycle-a', parentRunId: 'cycle-b' };
    const parentCycleB: QuantRunHistoryItem = { ...continued, id: 'cycle-b', parentRunId: 'cycle-a' };
    const duplicateRoot: QuantRunHistoryItem = { ...root, question: 'Duplicate retained id.' };
    const forkedRootRetry: QuantRunHistoryItem = { ...rootRetry, id: 'root-retry-fork' };
    const legacyRetryQuestionDrift: QuantRunHistoryItem = { ...rootRetry, question: 'Forged retry question.' };
    const legacyRetryModeDrift: QuantRunHistoryItem = { ...rootRetry, mode: 'plan' };
    const legacyRetryProviderDrift: QuantRunHistoryItem = { ...rootRetry, provider: 'other-provider' };
    const legacyRetryModelDrift: QuantRunHistoryItem = { ...rootRetry, model: 'other-model' };
    const marketRetryQuestionDrift: QuantRunHistoryItem = { ...marketRetry, question: 'Forged market retry question.' };
    const unresolvedCases: Array<{ run: QuantRunHistoryItem; directory: QuantRunHistoryItem[] }> = [
      { run: continued, directory: [continued] },
      { run: continued, directory: [{ ...root, state: 'running_experiments' }, continued] },
      { run: { ...continued, seedCandidateId: null }, directory: loaded },
      { run: root, directory: [root, duplicateRoot] },
      { run: parentCycleA, directory: [parentCycleA, parentCycleB] },
      { run: rootRetry, directory: [root, rootRetry, forkedRootRetry] },
      { run: rootRetry, directory: [{ ...root, state: 'waiting_for_review' }, rootRetry] },
      { run: legacyRetryQuestionDrift, directory: [root, legacyRetryQuestionDrift] },
      { run: legacyRetryModeDrift, directory: [root, legacyRetryModeDrift] },
      { run: legacyRetryProviderDrift, directory: [root, legacyRetryProviderDrift] },
      { run: legacyRetryModelDrift, directory: [root, legacyRetryModelDrift] },
      { run: { ...rootRetry, attemptNumber: 4 }, directory: loaded },
      { run: { ...refinedRetry, parentRunId: null }, directory: loaded },
      { run: { ...refinedRetry, seedCandidateId: 'candidate-drift' }, directory: loaded },
      { run: { ...refinedRetry, refinementReason: 'A different retained reason.' }, directory: loaded },
      { run: { ...marketParent, datasetDigest: `sha256:${'d'.repeat(64)}` }, directory: loaded },
      { run: { ...marketParent, runtimeDescriptorDigest: `sha256:${'d'.repeat(64)}` }, directory: loaded },
      { run: { ...marketParent, sealedSplitDigest: `sha256:${'d'.repeat(64)}` }, directory: loaded },
      { run: marketParent, directory: [{ ...marketRoot, state: 'running_experiments' }, marketParent] },
      { run: marketRetry, directory: [marketRoot, { ...marketParent, state: 'running_experiments' }, marketRetry] },
      { run: marketRetryQuestionDrift, directory: [marketRoot, marketParent, marketRetryQuestionDrift] },
    ];
    for (const item of unresolvedCases) {
      expect(projectQuantRunRelationship(item.run, item.directory)).toEqual({ relationship: 'unresolved' });
    }
  });

  it('matches a directory record to the exact current or historical snapshot identity', () => {
    const snapshot = fixture();
    const legacy: QuantRunHistoryItem = {
      contract: 'legacy-daily-v1', id: snapshot.run.id, projectId: snapshot.project.id, datasetId: snapshot.dataset.id,
      state: snapshot.run.state, mode: 'auto', question: snapshot.project.goal, attemptNumber: snapshot.run.attemptNumber,
      parentRunId: null, seedCandidateId: null, refinementReason: null, retryOfRunId: null,
      provider: snapshot.run.provider, model: snapshot.run.model, usedExperiments: snapshot.run.usedExperiments,
      createdAt: snapshot.run.startedAt, updatedAt: snapshot.run.completedAt ?? snapshot.run.startedAt,
    };
    expect(quantRunHistoryMatchesSnapshot(legacy, snapshot)).toBe(true);
    for (const drifted of [
      { ...legacy, state: 'running_experiments' },
      { ...legacy, mode: 'plan' as const },
      { ...legacy, question: 'A different directory question.' },
      { ...legacy, provider: 'other-provider' },
      { ...legacy, model: 'other-model' },
      { ...legacy, attemptNumber: legacy.attemptNumber + 1 },
    ]) expect(quantRunHistoryMatchesSnapshot(drifted, snapshot)).toBe(false);

    const market = fixture();
    market.run.contract = 'market-v2-public';
    market.run.id = 'market-run';
    market.project.id = 'market-project';
    market.scope = { ...market.scope, symbol: 'BTCUSDT', interval: '4h', dateRange: { start: '2024-01-01T00:00:00+00:00', end: '2024-12-31T20:00:00+00:00' } };
    market.dataset = {
      contract: 'market-v2', id: 'market-dataset', name: 'BTCUSDT 4h', symbol: 'BTCUSDT', interval: '4h',
      dateRange: { ...market.scope.dateRange }, barCount: 2190, schemaVersion: 'quant-market-bars-v2', parserVersion: 'fixture-v2',
      digest: `sha256:${'a'.repeat(64)}`, authenticity: 'synthetic_fixture', researchEligible: true, periodsPerYear: 2190,
      marketCalendar: '24x7', marketSession: 'continuous', timeZone: 'UTC',
      runtimeDescriptorDigest: `sha256:${'b'.repeat(64)}`, sealedSplitDigest: `sha256:${'c'.repeat(64)}`,
      recordDigest: `sha256:${'d'.repeat(64)}`,
      source: { kind: 'csv_upload', fileName: 'market.csv', sourceName: 'Fixture', sourceReference: null, normalizerVersion: 'fixture-v2', retrievedAtUtc: null, requestedBarCount: null, returnedBarCount: null, retainedBarCount: null, closedDroppedCount: null, deduplicatedCount: null, terminationReason: null, targetSatisfied: null },
      quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'Contiguous.' },
    };
    const marketHistory: QuantRunHistoryItem = {
      ...legacy, contract: 'market-v2-public', id: market.run.id, projectId: market.project.id, datasetId: market.dataset.id,
      symbol: 'BTCUSDT', interval: '4h', periodsPerYear: 2190, researchStartUtc: '2024-01-01T00:00:00Z', researchEndUtc: '2024-12-31T20:00:00Z',
      datasetDigest: market.dataset.digest, runtimeDescriptorDigest: market.dataset.runtimeDescriptorDigest, sealedSplitDigest: market.dataset.sealedSplitDigest,
    };
    expect(quantRunHistoryMatchesSnapshot(marketHistory, market)).toBe(true);
    for (const drifted of [
      { ...marketHistory, state: 'running_experiments' },
      { ...marketHistory, mode: 'plan' as const },
      { ...marketHistory, question: 'A different market directory question.' },
      { ...marketHistory, provider: 'other-provider' },
      { ...marketHistory, model: 'other-model' },
      { ...marketHistory, sealedSplitDigest: `sha256:${'e'.repeat(64)}` },
    ]) expect(quantRunHistoryMatchesSnapshot(drifted, market)).toBe(false);
  });

  it('formats market elapsed time without losing intraday precision and preserves daily copy', () => {
    expect(formatTradeHolding({
      id: 'market-trade', candidateId: 'rsi', entryDate: '2026-01-01T00:00:00+00:00', exitDate: '2026-01-04T16:00:00+00:00',
      returnPct: 1.2, holdingBars: 22, holdingElapsedSeconds: 316_800, reason: 'Retained trade.',
    })).toBe('22 bars · 3d 16h');
    expect(formatTradeHolding({
      id: 'daily-trade', candidateId: 'sma', entryDate: '2024-01-01', exitDate: '2024-01-04',
      returnPct: 1.2, holdingDays: 3, reason: 'Retained trade.',
    })).toBe('3 days');
    expect(formatTradeHolding({
      id: 'daily-trade', candidateId: 'sma', entryDate: '2024-01-01', exitDate: '2024-01-04',
      returnPct: 1.2, holdingDays: 3, reason: 'Retained trade.',
    }, 'compact')).toBe('3d');
  });

  it('exposes only completed terminal candidates with an explicit seedability projection', () => {
    const completed = fixture();
    expect(canContinueResearch(completed, completed.candidates[1])).toBe(false);

    const seedable = fixture();
    seedable.candidates = seedable.candidates.map((candidate, index) => ({
      ...candidate,
      canSeedResearch: index === 1,
    }));
    expect(canContinueResearch(seedable, seedable.candidates[1])).toBe(true);

    const marketSeedable = fixture();
    marketSeedable.run.contract = 'market-v2-public';
    marketSeedable.dataset = {
      contract: 'market-v2',
      id: 'market-dataset-4h',
      name: 'BTCUSDT 4 hour',
      symbol: 'BTCUSDT',
      interval: '4h',
      dateRange: { start: '2024-01-01T00:00:00Z', end: '2024-12-31T20:00:00Z' },
      barCount: 2196,
      schemaVersion: 'quant-market-bars-v2',
      parserVersion: 'fixture-market-bars-v2',
      digest: `sha256:${'a'.repeat(64)}`,
      authenticity: 'imported',
      researchEligible: true,
      periodsPerYear: 2190,
      marketCalendar: '24x7',
      marketSession: 'continuous',
      timeZone: 'UTC',
      recordDigest: `sha256:${'b'.repeat(64)}`,
      source: {
        kind: 'csv_upload', fileName: 'btcusdt-4h.csv', sourceName: 'Market test data',
        sourceReference: null, normalizerVersion: 'fixture-market-bars-v2', retrievedAtUtc: null,
        requestedBarCount: null, returnedBarCount: null, retainedBarCount: null,
        closedDroppedCount: null, deduplicatedCount: null, terminationReason: null,
        targetSatisfied: null,
      },
      quality: { status: 'accepted', cadenceGapCount: 0, normalizationNote: 'Contiguous.' },
    };
    marketSeedable.candidates = marketSeedable.candidates.map((candidate, index) => ({
      ...candidate,
      canSeedResearch: index === 1,
    }));
    for (const state of ['completed', 'failed', 'cancelled'] as const) {
      marketSeedable.run.state = state;
      expect(canContinueResearch(marketSeedable, marketSeedable.candidates[1])).toBe(true);
    }
    for (const state of ['queued', 'running_experiments', 'waiting_for_review'] as const) {
      marketSeedable.run.state = state;
      expect(canContinueResearch(marketSeedable, marketSeedable.candidates[1])).toBe(false);
    }
    marketSeedable.run.state = 'completed';
    marketSeedable.run.contract = 'market-v2-private';
    expect(canContinueResearch(marketSeedable, marketSeedable.candidates[1])).toBe(false);

    const waiting = fixture({
      run: { ...quantFixtureSnapshot.run, state: 'waiting_for_review' },
    });
    waiting.candidates = waiting.candidates.map((candidate, index) => ({
      ...candidate,
      canSeedResearch: index === 1,
    }));
    expect(canContinueResearch(waiting, waiting.candidates[1])).toBe(false);
  });

  it('keeps rejected and inconclusive candidates independent from completed run health', () => {
    const presentation = presentQuantWorkspace(fixture());
    expect(presentation.statusLabel).toBe('Completed');
    expect(presentation.statusTone).toBe('positive');
    expect(presentation.candidates).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'candidate-a', verdictLabel: 'Rejected', reason: 'Parameter sensitivity · 6.33 pp range' }),
      expect.objectContaining({ id: 'candidate-c', verdictLabel: 'Inconclusive' }),
    ]));
  });

  it('falls back to generic business copy for unknown events and retains the raw name only in advanced data', () => {
    const snapshot = fixture({ events: [{ id: 'unknown-1', sequence: 99, type: 'provider.private.changed', timestamp: '2026-07-17T10:25:00+08:00', actor: 'system', safeSummary: 'Safe diagnostic summary.' }] });
    const event = presentQuantWorkspace(snapshot).activity[0];
    expect(event).toMatchObject({ title: 'Run activity recorded', summary: expect.not.stringContaining('provider.private.changed') });
    expect(event?.advanced.eventType).toBe('provider.private.changed');
  });

  it('shows view actions plus only commands declared legal by the API snapshot', () => {
    const presentation = presentQuantWorkspace(fixture());
    expect(presentation.actions.map((action) => action.kind)).toEqual(['open_report', 'compare_candidates']);
    expect(presentation.actions.map((action) => action.kind)).not.toContain('retry_run');
    expect(presentation.actions.map((action) => action.kind)).not.toContain('cancel_run');
  });

  it('presents no-viable-candidate as a completed negative research conclusion', () => {
    const snapshot = fixture();
    snapshot.candidates = snapshot.candidates.map((candidate) => ({ ...candidate, verdict: candidate.id === 'candidate-a' ? 'rejected' : 'inconclusive' }));
    const presentation = presentQuantWorkspace(snapshot);
    expect(presentation.negativeConclusion).toBe(true);
    expect(presentation.statusLabel).toBe('Completed');
    expect(presentation.decision).toMatchObject({
      title: 'No candidate passed validation',
      tone: 'danger',
    });
    expect(presentation.actions.some((action) => action.kind === 'open_report')).toBe(true);
  });

  it('lets sealed holdout evidence override a training-only promising label', () => {
    const snapshot = fixture();
    snapshot.report = {
      ...snapshot.report!,
      proposedNextStep: 'Start paper evaluation immediately.',
      generalization: {
        status: 'fail',
        reason: 'The selected candidate failed on holdout data.',
        selectedCandidateId: 'candidate-b',
        split: {
          method: 'chronological', ruleVersion: 'chronological-v1', trainBarCount: 1200,
          holdoutBarCount: 300, cutoffDate: '2025-01-01', datasetId: snapshot.dataset.id,
          datasetDigest: snapshot.dataset.digest,
        },
      },
    };

    const presentation = presentQuantWorkspace(snapshot);

    expect(presentation.negativeConclusion).toBe(true);
    expect(presentation.decision.title).toBe('Sealed holdout failed');
    expect(presentation.decision.nextStep).toBe('Revise the hypothesis and start a new immutable research run.');
    expect(presentation.decision.nextStep).not.toContain('paper evaluation');
    expect(presentation.currentActionPurpose).toContain('failed on holdout data');
    expect(presentation.candidates).toContainEqual(expect.objectContaining({
      id: 'candidate-b', verdictLabel: 'Failed sealed holdout', verdictTone: 'danger',
    }));
  });

  it('projects one bounded next-research proposal and recommends stopping after a pass', () => {
    const failed = fixture();
    failed.candidates = failed.candidates.map((candidate) => candidate.id === 'candidate-b' ? { ...candidate, canSeedResearch: true } : candidate);
    failed.report = {
      ...failed.report!,
      generalization: {
        status: 'fail', reason: 'The retained strategy failed to preserve positive holdout return.', selectedCandidateId: 'candidate-b',
        split: { method: 'chronological', ruleVersion: 'chronological-v1', trainBarCount: 1200, holdoutBarCount: 300, cutoffDate: '2025-01-01', datasetId: failed.dataset.id, datasetDigest: failed.dataset.digest },
      },
    };
    const candidate = failed.candidates.find((item) => item.id === 'candidate-b');
    expect(projectNextResearchProposal(failed, candidate)).toMatchObject({
      recommendation: 'refine',
      execution: 'one_bounded_auto_run',
      rationale: 'The retained strategy failed to preserve positive holdout return.',
    });
    expect(projectNextResearchProposal(failed, candidate)?.refinementReason).toContain('one bounded parameter change');

    failed.report.generalization = { ...failed.report.generalization!, status: 'pass' };
    expect(projectNextResearchProposal(failed, candidate)).toMatchObject({
      recommendation: 'stop',
      execution: 'none',
      change: 'Do not create another research version by default.',
      refinementReason: '',
    });
  });

  it('contains discrete counters but no token/provider-cost fields or inferred percentage progress', () => {
    const serialized = JSON.stringify(presentQuantWorkspace(fixture()));
    expect(serialized).not.toMatch(/token|usedCost|providerCost/i);
    expect(serialized).not.toMatch(/\d+%/);
  });

  it('exposes the API-owned synthetic Agent start only after plan approval', () => {
    const snapshot = fixture();
    snapshot.run = {
      ...snapshot.run,
      state: 'running_experiments',
      legalCommands: ['run_fixture', 'cancel_run'],
    };
    snapshot.candidates = [];
    const presentation = presentQuantWorkspace(snapshot);
    expect(presentation.statusLabel).toBe('Running experiments');
    expect(presentation.actions).toEqual([
      { kind: 'run_fixture', label: 'Run Synthetic Agent', tone: 'primary' },
      { kind: 'cancel_run', label: 'Cancel Run', tone: 'default' },
    ]);
  });

  it('uses task language for repair and validation without presenting either as a failed run', () => {
    const repairing = fixture();
    repairing.report = null;
    repairing.run = { ...repairing.run, state: 'repairing' };
    expect(presentQuantWorkspace(repairing)).toMatchObject({
      statusLabel: 'Repairing candidate',
      statusTone: 'warning',
      currentActionTitle: 'Retrying a recoverable experiment',
      decision: { title: 'Research is still in progress' },
    });

    const validating = fixture();
    validating.report = null;
    validating.run = { ...validating.run, state: 'validating' };
    expect(presentQuantWorkspace(validating)).toMatchObject({
      statusLabel: 'Validating evidence',
      statusTone: 'info',
      currentActionTitle: 'Running robustness checks',
      decision: { title: 'Research is still in progress' },
    });
  });

  it('presents transient execution phases with concrete work and no invented percentage', () => {
    const cases = [
      ['loading_data', 'Verifying dataset', 'Verifying the pinned dataset'],
      ['generating_candidates', 'Preparing candidates', 'Preparing bounded candidates'],
      ['generating_report', 'Building report', 'Assembling the research report'],
    ] as const;
    for (const [state, statusLabel, currentActionTitle] of cases) {
      const snapshot = fixture();
      snapshot.report = null;
      snapshot.run = { ...snapshot.run, state };
      const presentation = presentQuantWorkspace(snapshot);
      expect(presentation).toMatchObject({ statusLabel, currentActionTitle, statusTone: 'info' });
      expect(JSON.stringify(presentation)).not.toMatch(/\d+%/);
    }
  });

  it('distinguishes failed, cancelled, and review-waiting runs from in-progress research', () => {
    const failed = fixture();
    failed.report = null;
    failed.run = { ...failed.run, state: 'failed' };
    expect(presentQuantWorkspace(failed).decision).toMatchObject({ title: 'Research failed safely', tone: 'danger' });

    const cancelled = fixture();
    cancelled.report = null;
    cancelled.run = { ...cancelled.run, state: 'cancelled' };
    expect(presentQuantWorkspace(cancelled).decision).toMatchObject({ title: 'Research was cancelled', tone: 'neutral' });

    const waiting = fixture();
    waiting.report = null;
    waiting.run = { ...waiting.run, state: 'waiting_for_review' };
    expect(presentQuantWorkspace(waiting).decision).toMatchObject({ title: 'Research evidence is ready for review', tone: 'warning' });
  });
});
