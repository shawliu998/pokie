export class TerminalAuditError extends Error {
  constructor(readonly cause: unknown) {
    super(cause instanceof Error ? cause.message : 'Terminal export audit failed.');
    this.name = 'TerminalAuditError';
  }
}

export async function completeLocalExport<T>(localSideEffect: () => Promise<void> | void, recordTerminal: () => Promise<T>): Promise<T> {
  await localSideEffect();
  try {
    return await recordTerminal();
  } catch (cause) {
    throw new TerminalAuditError(cause);
  }
}
