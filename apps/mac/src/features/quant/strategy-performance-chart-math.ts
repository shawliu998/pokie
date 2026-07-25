import type { StrategyPerformancePoint } from '../../quant-domain';

export interface ChartBounds {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface ChartDomain {
  min: number;
  max: number;
  ticks: number[];
}

function timestamp(date: string): number {
  const value = Date.parse(date.includes('T') ? date : `${date}T00:00:00Z`);
  return Number.isFinite(value) ? value : 0;
}

export function chartDomain(values: readonly number[], view: 'equity' | 'drawdown', tickCount = 5): ChartDomain {
  const finite = values.filter(Number.isFinite);
  let min = finite.length ? Math.min(...finite) : view === 'equity' ? 100 : -1;
  let max = finite.length ? Math.max(...finite) : view === 'equity' ? 101 : 0;
  if (view === 'drawdown') max = Math.max(0, max);
  if (min === max) {
    const padding = Math.max(1, Math.abs(min) * .01);
    min -= padding;
    if (view === 'equity') max += padding;
  }
  const count = Math.max(2, Math.floor(tickCount));
  return {
    min,
    max,
    ticks: Array.from({ length: count }, (_, index) => max - (index / (count - 1)) * (max - min)),
  };
}

export function xForDate(date: string, startDate: string, endDate: string, bounds: ChartBounds): number {
  const start = timestamp(startDate);
  const end = timestamp(endDate);
  const ratio = end === start ? .5 : Math.min(1, Math.max(0, (timestamp(date) - start) / (end - start)));
  return bounds.left + ratio * (bounds.width - bounds.left - bounds.right);
}

export function yForValue(value: number, domain: Pick<ChartDomain, 'min' | 'max'>, bounds: ChartBounds): number {
  const ratio = (value - domain.min) / Math.max(Number.EPSILON, domain.max - domain.min);
  return bounds.height - bounds.bottom - Math.min(1, Math.max(0, ratio)) * (bounds.height - bounds.top - bounds.bottom);
}

export function seriesPath(points: readonly StrategyPerformancePoint[], key: 'equity' | 'drawdown', domain: ChartDomain, bounds: ChartBounds, startDate: string, endDate: string): string {
  if (points.length < 2) return '';
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'}${xForDate(point.date, startDate, endDate, bounds).toFixed(1)} ${yForValue(point[key], domain, bounds).toFixed(1)}`).join(' ');
}

export function nearestPointIndex(points: readonly StrategyPerformancePoint[], pointerX: number, bounds: ChartBounds): number {
  if (points.length === 0) return -1;
  if (points.length === 1) return 0;
  const startDate = points[0]!.date;
  const endDate = points.at(-1)!.date;
  let nearest = 0;
  let distance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < points.length; index += 1) {
    const nextDistance = Math.abs(xForDate(points[index]!.date, startDate, endDate, bounds) - pointerX);
    if (nextDistance < distance) {
      distance = nextDistance;
      nearest = index;
    }
  }
  return nearest;
}

export function matchPointByDate(points: readonly StrategyPerformancePoint[], date: string): StrategyPerformancePoint | null {
  if (points.length === 0) return null;
  const target = timestamp(date);
  return points.reduce((best, point) => Math.abs(timestamp(point.date) - target) < Math.abs(timestamp(best.date) - target) ? point : best, points[0]!);
}

export function keyboardPointIndex(current: number, key: 'ArrowLeft' | 'ArrowRight' | 'Home' | 'End', length: number): number {
  if (length <= 0) return -1;
  const bounded = Math.min(length - 1, Math.max(0, current));
  if (key === 'Home') return 0;
  if (key === 'End') return length - 1;
  return Math.min(length - 1, Math.max(0, bounded + (key === 'ArrowLeft' ? -1 : 1)));
}
