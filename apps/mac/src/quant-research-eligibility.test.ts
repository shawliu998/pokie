import { describe, expect, it } from 'vitest';
import {
  defaultMarketFetchLimit,
  marketResearchRequirementLabel,
  requiredMarketResearchBars,
} from './quant-research-eligibility';

describe('quant research eligibility helpers', () => {
  it('computes the interval-aware market research thresholds', () => {
    expect(requiredMarketResearchBars('1h', 8760)).toBe(2190);
    expect(requiredMarketResearchBars('4h', 2190)).toBe(548);
    expect(requiredMarketResearchBars('1D', 365)).toBe(252);
  });

  it('falls back to the supported interval defaults when annualization is absent', () => {
    expect(requiredMarketResearchBars('1h', null)).toBe(2190);
    expect(requiredMarketResearchBars('4h', undefined)).toBe(548);
    expect(requiredMarketResearchBars('1D', null)).toBe(252);
  });

  it('keeps fetch defaults and guidance aligned with the supported intervals', () => {
    expect(defaultMarketFetchLimit('1h')).toBe(2190);
    expect(defaultMarketFetchLimit('4h')).toBe(548);
    expect(defaultMarketFetchLimit('1D')).toBe(365);
    expect(marketResearchRequirementLabel('4h', 2190)).toBe('548 consecutive 4h bars');
  });
});
