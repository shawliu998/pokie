import { describe, expect, it } from 'vitest';
import type { StrategyPerformancePoint } from '../../quant-domain';
import { chartDomain, keyboardPointIndex, matchPointByDate, nearestPointIndex, seriesPath, xForDate, yForValue } from './strategy-performance-chart-math';

const bounds = { width: 760, height: 250, left: 54, right: 10, top: 12, bottom: 12 };
const points: StrategyPerformancePoint[] = [
  { date: '2024-01-01', equity: 100, drawdown: 0 },
  { date: '2024-01-03', equity: 104, drawdown: -2 },
  { date: '2024-01-10', equity: 108, drawdown: -1 },
];

describe('strategy performance chart math', () => {
  it('handles empty and single-point series without drawing a misleading line', () => {
    const domain = chartDomain([100], 'equity');
    expect(seriesPath([], 'equity', domain, bounds, '2024-01-01', '2024-01-01')).toBe('');
    expect(seriesPath([points[0]!], 'equity', domain, bounds, '2024-01-01', '2024-01-01')).toBe('');
    expect(nearestPointIndex([], 200, bounds)).toBe(-1);
    expect(nearestPointIndex([points[0]!], -500, bounds)).toBe(0);
  });

  it('maps values and dates into bounded plot coordinates', () => {
    const domain = chartDomain(points.map((point) => point.equity), 'equity');
    expect(xForDate('2023-01-01', points[0]!.date, points.at(-1)!.date, bounds)).toBe(bounds.left);
    expect(xForDate('2025-01-01', points[0]!.date, points.at(-1)!.date, bounds)).toBe(bounds.width - bounds.right);
    expect(yForValue(domain.max, domain, bounds)).toBe(bounds.top);
    expect(yForValue(domain.min, domain, bounds)).toBe(bounds.height - bounds.bottom);
  });

  it('preserves distinct RFC3339 UTC points on an intraday axis', () => {
    const intraday: StrategyPerformancePoint[] = [
      { date: '2024-01-01T00:00:00+00:00', equity: 100, drawdown: 0 },
      { date: '2024-01-01T04:00:00+00:00', equity: 101, drawdown: -1 },
      { date: '2024-01-01T08:00:00+00:00', equity: 102, drawdown: -.5 },
    ];
    const positions = intraday.map((point) => xForDate(point.date, intraday[0]!.date, intraday.at(-1)!.date, bounds));
    expect(positions[0]).toBe(bounds.left);
    expect(positions[1]).toBeGreaterThan(positions[0]!);
    expect(positions[2]).toBe(bounds.width - bounds.right);
    expect(matchPointByDate(intraday, '2024-01-01T05:00:00+00:00')?.date).toBe('2024-01-01T04:00:00+00:00');
  });

  it('selects the nearest candidate point for pointer bounds', () => {
    expect(nearestPointIndex(points, -100, bounds)).toBe(0);
    expect(nearestPointIndex(points, 10_000, bounds)).toBe(2);
    expect(nearestPointIndex(points, xForDate('2024-01-03', points[0]!.date, points.at(-1)!.date, bounds), bounds)).toBe(1);
  });

  it('matches unequal benchmark series by exact or nearest legal date', () => {
    const benchmark = [points[0]!, points[2]!];
    expect(matchPointByDate(benchmark, '2024-01-10')?.date).toBe('2024-01-10');
    expect(matchPointByDate(benchmark, '2024-01-04')?.date).toBe('2024-01-01');
    expect(matchPointByDate([], '2024-01-04')).toBeNull();
  });

  it('keeps keyboard navigation within the available point range', () => {
    expect(keyboardPointIndex(0, 'ArrowLeft', points.length)).toBe(0);
    expect(keyboardPointIndex(2, 'ArrowRight', points.length)).toBe(2);
    expect(keyboardPointIndex(1, 'Home', points.length)).toBe(0);
    expect(keyboardPointIndex(1, 'End', points.length)).toBe(2);
    expect(keyboardPointIndex(0, 'End', 0)).toBe(-1);
  });
});
