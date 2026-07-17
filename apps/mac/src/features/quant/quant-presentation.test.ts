import { describe, expect, it } from 'vitest';
import type { QuantWorkspaceSnapshot } from '../../quant-domain';
import { quantFixtureSnapshot } from './quant-fixtures';
import { presentQuantWorkspace } from './quant-presentation';

function fixture(overrides: Partial<QuantWorkspaceSnapshot> = {}): QuantWorkspaceSnapshot {
  return { ...structuredClone(quantFixtureSnapshot), ...overrides };
}

describe('presentQuantWorkspace', () => {
  it('keeps rejected and inconclusive candidates independent from completed run health', () => {
    const presentation = presentQuantWorkspace(fixture());
    expect(presentation.statusLabel).toBe('Completed');
    expect(presentation.statusTone).toBe('positive');
    expect(presentation.candidates).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'candidate-a', verdictLabel: 'Rejected', reason: 'Parameter sensitivity' }),
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
    expect(presentation.actions.map((action) => action.kind)).toEqual(['open_report', 'compare_candidates', 'start_new_run']);
    expect(presentation.actions.map((action) => action.kind)).not.toContain('retry_run');
    expect(presentation.actions.map((action) => action.kind)).not.toContain('cancel_run');
  });

  it('presents no-viable-candidate as a completed negative research conclusion', () => {
    const snapshot = fixture();
    snapshot.candidates = snapshot.candidates.map((candidate) => ({ ...candidate, verdict: candidate.id === 'candidate-a' ? 'rejected' : 'inconclusive' }));
    const presentation = presentQuantWorkspace(snapshot);
    expect(presentation.negativeConclusion).toBe(true);
    expect(presentation.statusLabel).toBe('Completed');
    expect(presentation.actions.some((action) => action.kind === 'open_report')).toBe(true);
  });

  it('contains discrete counters but no token/provider-cost fields or inferred percentage progress', () => {
    const serialized = JSON.stringify(presentQuantWorkspace(fixture()));
    expect(serialized).not.toMatch(/token|usedCost|providerCost/i);
    expect(serialized).not.toMatch(/\d+%/);
  });
});
