import { describe, expect, it } from 'vitest';
import type { Signal } from '../../domain';
import { signalChangeSummary } from './SignalInbox';

const signal = (currentCount: number, baselineCount: number) => ({ currentCount, baselineCount } as Signal);

describe('signalChangeSummary', () => {
  it('translates detector counts into a PM-readable current-versus-baseline change', () => {
    expect(signalChangeSummary(signal(18, 12))).toBe('18 current vs 12 baseline · +6 (50%)');
    expect(signalChangeSummary(signal(6, 12))).toBe('6 current vs 12 baseline · -6 (-50%)');
  });

  it('does not invent a percentage when there is no baseline', () => {
    expect(signalChangeSummary(signal(4, 0))).toBe('4 current vs 0 baseline · +4 (new activity)');
  });
});
