import type { MarketBar, QuantAuthenticity, QuantDatasetPreview } from './quant-domain';

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object.`);
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${label} must be a non-empty string.`);
  return value;
}

function integer(value: unknown, label: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw new Error(`${label} must be a non-negative integer.`);
  return Number(value);
}

function positiveNumber(value: unknown, label: string): number {
  const parsed = typeof value === 'string' ? Number(value) : value;
  if (typeof parsed !== 'number' || !Number.isFinite(parsed) || parsed <= 0) throw new Error(`${label} must be a positive number.`);
  return parsed;
}

function authenticity(value: unknown): QuantAuthenticity {
  if (value === 'generated' || value === 'synthetic_fixture') return 'synthetic_fixture';
  if (value === 'imported' || value === 'collected') return value;
  throw new Error('data_authenticity is unsupported.');
}

function parseBar(value: unknown, index: number): MarketBar {
  const item = record(value, `bars[${index}]`);
  const bar = {
    date: text(item.date, `bars[${index}].date`),
    open: positiveNumber(item.open, `bars[${index}].open`),
    high: positiveNumber(item.high, `bars[${index}].high`),
    low: positiveNumber(item.low, `bars[${index}].low`),
    close: positiveNumber(item.close, `bars[${index}].close`),
    volume: integer(item.volume, `bars[${index}].volume`),
  };
  if (bar.high < Math.max(bar.open, bar.close) || bar.low > Math.min(bar.open, bar.close)) throw new Error(`bars[${index}] has invalid OHLC bounds.`);
  return bar;
}

export function parseQuantDatasetPreview(value: unknown): QuantDatasetPreview {
  const item = record(value, 'Dataset preview');
  if (!Array.isArray(item.bars)) throw new Error('Dataset preview bars must be an array.');
  const bars = item.bars.map(parseBar);
  const returnedBarCount = integer(item.returned_bar_count, 'returned_bar_count');
  const maxPoints = integer(item.max_points, 'max_points');
  const totalBarCount = integer(item.total_bar_count, 'total_bar_count');
  if (bars.length !== returnedBarCount) throw new Error('returned_bar_count must match preview bars.');
  if (bars.length > maxPoints || maxPoints > 400) throw new Error('Dataset preview exceeds its bounded point limit.');
  if (bars.some((bar, index) => index > 0 && bars[index - 1]!.date >= bar.date)) throw new Error('Dataset preview bars must be strictly ordered by date.');
  if (item.interval !== '1D') throw new Error('Dataset preview interval is unsupported.');
  if (item.sampling_rule !== 'latest_contiguous') throw new Error('Dataset preview sampling rule is unsupported.');
  return {
    contract: 'legacy-daily-v1',
    datasetId: text(item.dataset_id, 'dataset_id'),
    symbol: text(item.symbol, 'symbol'),
    interval: '1D',
    authenticity: authenticity(item.data_authenticity),
    coveredStart: text(item.covered_start, 'covered_start'),
    coveredEnd: text(item.covered_end, 'covered_end'),
    totalBarCount,
    returnedBarCount,
    maxPoints,
    samplingRule: 'latest_contiguous',
    bars,
  };
}
