import { describe, expect, it } from 'vitest';
import { incompleteCopy } from './formatting';

describe('workbench copy completeness', () => {
  it('rejects empty and placeholder wording at word boundaries', () => {
    for (const value of ['', '   ', 'Recommendation pending', 'TBD', 'todo: verify', 'Placeholder copy']) {
      expect(incompleteCopy(value)).toBe(true);
    }
    expect(incompleteCopy('Validate the permission preview with enterprise administrators.')).toBe(false);
    expect(incompleteCopy('A pendingly named internal identifier is still substantive.')).toBe(false);
  });
});
