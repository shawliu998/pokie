import { describe, expect, it } from 'vitest';
import { rollingSma } from './quant-market-math';

describe('rollingSma', () => {
  it('keeps warm-up values null and computes a known rolling sequence', () => {
    expect(rollingSma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });

  it('preserves input length when there are not enough observations', () => {
    expect(rollingSma([10, 20], 3)).toEqual([null, null]);
    expect(rollingSma([], 20)).toEqual([]);
  });

  it('rejects invalid periods and non-finite inputs', () => {
    expect(() => rollingSma([1, 2], 0)).toThrow('positive integer');
    expect(() => rollingSma([1, Number.NaN], 2)).toThrow('finite numbers');
  });
});
