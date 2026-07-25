import { describe, expect, it } from 'vitest';
import { parseQuantDatasetPreview } from './quant-dataset-preview-parser';

const rawPreview = {
  dataset_id: 'dataset-spy', symbol: 'SPY', interval: '1D', covered_start: '2023-01-03', covered_end: '2024-12-31',
  data_authenticity: 'imported',
  total_bar_count: 252, returned_bar_count: 2, max_points: 240, sampling_rule: 'latest_contiguous',
  bars: [
    { date: '2024-12-30', open: '100.0', high: '103.0', low: '99.0', close: '102.0', volume: 1000 },
    { date: '2024-12-31', open: '102.0', high: '104.0', low: '101.0', close: '103.0', volume: 1200 },
  ],
};

describe('parseQuantDatasetPreview', () => {
  it('parses bounded contiguous OHLCV without filling missing values', () => {
    expect(parseQuantDatasetPreview(rawPreview)).toMatchObject({ datasetId: 'dataset-spy', authenticity: 'imported', returnedBarCount: 2, bars: [{ close: 102 }, { close: 103 }] });
  });

  it('rejects count mismatches, invalid OHLC, and unsupported sampling', () => {
    expect(() => parseQuantDatasetPreview({ ...rawPreview, returned_bar_count: 3 })).toThrow('must match');
    expect(() => parseQuantDatasetPreview({ ...rawPreview, bars: [{ ...rawPreview.bars[0], high: 90 }] })).toThrow('invalid OHLC');
    expect(() => parseQuantDatasetPreview({ ...rawPreview, sampling_rule: 'sparse' })).toThrow('sampling rule');
    expect(() => parseQuantDatasetPreview({ ...rawPreview, data_authenticity: 'human_authored' })).toThrow('data_authenticity');
  });
});
