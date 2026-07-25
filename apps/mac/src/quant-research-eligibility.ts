import type { QuantBarInterval } from './quant-domain';

const MARKET_PERIODS_PER_YEAR: Record<QuantBarInterval, number> = {
  '1h': 8760,
  '4h': 2190,
  '1D': 365,
};

export function requiredMarketResearchBars(
  interval: QuantBarInterval,
  periodsPerYear: number | null | undefined,
): number {
  const effectivePeriodsPerYear = periodsPerYear ?? MARKET_PERIODS_PER_YEAR[interval];
  return Math.max(252, Math.ceil(effectivePeriodsPerYear / 4));
}

export function defaultMarketFetchLimit(interval: QuantBarInterval): number {
  return interval === '1h' ? 2190 : interval === '4h' ? 548 : 365;
}

export function marketResearchRequirementLabel(
  interval: QuantBarInterval,
  periodsPerYear: number | null | undefined,
): string {
  return `${requiredMarketResearchBars(interval, periodsPerYear).toLocaleString()} consecutive ${interval} bars`;
}
