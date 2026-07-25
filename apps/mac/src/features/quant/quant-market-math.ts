export function rollingSma(values: readonly number[], period: number): Array<number | null> {
  if (!Number.isInteger(period) || period < 1) throw new Error('SMA period must be a positive integer.');
  const result: Array<number | null> = Array.from({ length: values.length }, () => null);
  let sum = 0;
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index]!;
    if (!Number.isFinite(value)) throw new Error('SMA values must be finite numbers.');
    sum += value;
    if (index >= period) sum -= values[index - period]!;
    if (index >= period - 1) result[index] = sum / period;
  }
  return result;
}
