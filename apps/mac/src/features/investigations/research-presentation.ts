import type { ResearchGenerationMethod, ResearchRun } from '../../domain';

export function researchMethodLabel(method: ResearchGenerationMethod): string {
  if (method === 'model') return 'Model-assisted research';
  if (method === 'deterministic') return 'Deterministic research';
  return 'Research method unavailable';
}

export function synthesisMethodLabel(method: 'deterministic' | 'model'): string {
  return method === 'model' ? 'Model-assisted synthesis' : 'Deterministic synthesis';
}

export function runStateSummary(run: ResearchRun | null): string {
  if (!run) return 'No research run has started.';
  if (run.state === 'queued') return 'Research is queued within the pinned scope and budget.';
  if (run.state === 'running') return 'Research is running. Outputs remain proposals until human review.';
  if (run.state === 'waiting_for_input') return 'Research is paused for structured human input.';
  if (run.state === 'completed') return 'Research completed. Evidence, claims, and synthesis still require human review.';
  if (run.state === 'failed') return 'Research failed. No approval state was changed.';
  return 'Research was cancelled. No approval state was changed.';
}

export function runProvenanceAvailable(run: ResearchRun): boolean {
  if (run.generationMethod !== 'model') return true;
  return Boolean(run.model && run.promptRefs.length > 0);
}
