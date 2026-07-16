import { describe, expect, it, vi } from 'vitest';
import { completeLocalExport, TerminalAuditError } from './export-flow';

describe('local export and terminal audit ordering', () => {
  it('does not record a BriefExport when the local side effect rejects', async () => {
    const recordTerminal = vi.fn(async () => ({ id: 'export-1' }));
    await expect(completeLocalExport(async () => { throw new Error('clipboard rejected'); }, recordTerminal)).rejects.toThrow('clipboard rejected');
    expect(recordTerminal).not.toHaveBeenCalled();
  });

  it('records exactly one terminal BriefExport after a successful local side effect', async () => {
    const localSideEffect = vi.fn(async () => undefined);
    const recordTerminal = vi.fn(async () => ({ id: 'export-1' }));
    await expect(completeLocalExport(localSideEffect, recordTerminal)).resolves.toEqual({ id: 'export-1' });
    expect(localSideEffect).toHaveBeenCalledTimes(1);
    expect(recordTerminal).toHaveBeenCalledTimes(1);
  });

  it('distinguishes audit failure after local completion', async () => {
    await expect(completeLocalExport(async () => undefined, async () => { throw new Error('audit unavailable'); })).rejects.toBeInstanceOf(TerminalAuditError);
  });
});
