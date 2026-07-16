import { describe, expect, it } from 'vitest';
import { parseRfc4180, prepareCsvImport } from './imports';

describe('RFC4180 CSV parsing', () => {
  it('preserves commas, CRLFs, and escaped quotes inside quoted fields', () => {
    expect(parseRfc4180('id,quote\r\n1,"hello, world"\r\n2,"line one\r\nline ""two"""\r\n')).toEqual([
      ['id', 'quote'],
      ['1', 'hello, world'],
      ['2', 'line one\r\nline "two"'],
    ]);
  });

  it('rejects malformed quote placement and unterminated quotes', () => {
    expect(() => parseRfc4180('id,quote\r\n1,"closed"tail\r\n')).toThrow(/closing quote/);
    expect(() => parseRfc4180('id,quote\r\n1,"open')).toThrow(/unterminated/);
  });

  it('prepares only basename metadata and exact digests', async () => {
    const content = 'id,quote\r\n1,"hello, world"\r\n';
    const encoded = new TextEncoder().encode(content);
    const file = { name: 'feedback.csv', type: 'text/csv', size: encoded.byteLength, text: async () => content, arrayBuffer: async () => encoded.buffer } as File;
    const prepared = await prepareCsvImport(file);
    expect(prepared.fileName).toBe('feedback.csv');
    expect(prepared.rowCount).toBe(1);
    expect(prepared.selectedScope.columns).toEqual(['id', 'quote']);
    expect(prepared.fileDigest).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(prepared.expectedUploadDigest).toBe(prepared.fileDigest);
  });
});
