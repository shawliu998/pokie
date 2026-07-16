import { describe, expect, it } from 'vitest';
import type { ResearchRun } from '../../domain';
import { researchMethodLabel, runProvenanceAvailable, runStateSummary, synthesisMethodLabel } from './research-presentation';

const run = (overrides: Partial<ResearchRun> = {}): ResearchRun => ({
  id: 'run-1', state: 'completed', rowVersion: 1, latestSequence: 8, attemptNumber: 1,
  graphVersion: 'bounded-model-v1', generationMethod: 'model', provider: 'deepseek', model: 'deepseek-chat',
  promptRefs: ['planner-v1'], traceRef: 'trace-opaque-1', usedCostUsd: '0.1200',
  budget: { maxCostUsd: '4.0000', maxDurationSeconds: 900 }, waitingForInputReason: null,
  ...overrides,
});

describe('research presentation labels', () => {
  it('uses the authoritative generation method instead of graph-name heuristics', () => {
    expect(researchMethodLabel('model')).toBe('Model-assisted research');
    expect(researchMethodLabel('deterministic')).toBe('Deterministic research');
    expect(synthesisMethodLabel('deterministic')).toBe('Deterministic synthesis');
  });

  it('keeps completed model output subordinate to human review', () => {
    expect(runStateSummary(run())).toMatch(/still require human review/);
    expect(runStateSummary(run({ state: 'failed' }))).toMatch(/No approval state was changed/);
  });

  it('requires provider, model, and prompt refs for complete model provenance', () => {
    expect(runProvenanceAvailable(run())).toBe(true);
    expect(runProvenanceAvailable(run({ promptRefs: [] }))).toBe(false);
    expect(runProvenanceAvailable(run({ generationMethod: 'deterministic', provider: 'deterministic', model: null, promptRefs: [] }))).toBe(true);
  });
});
