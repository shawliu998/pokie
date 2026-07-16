import type { RunStreamEvent } from '../sse';

export interface RunCursor {
  eventId: string;
  sequence: number;
}

export const emptyRunCursor = (): RunCursor => ({ eventId: '', sequence: 0 });

export function parseRunCursor(serialized: string | null): RunCursor {
  if (!serialized) return emptyRunCursor();
  try {
    const parsed = JSON.parse(serialized) as Partial<RunCursor>;
    if (typeof parsed.eventId !== 'string' || typeof parsed.sequence !== 'number' || !Number.isSafeInteger(parsed.sequence) || parsed.sequence < 0) return emptyRunCursor();
    return { eventId: parsed.eventId, sequence: parsed.sequence };
  } catch {
    return emptyRunCursor();
  }
}

export type CursorDecision =
  | { kind: 'duplicate' }
  | { kind: 'gap' }
  | { kind: 'advance'; cursor: RunCursor };

export function reconcileRunCursor(cursor: RunCursor, event: Pick<RunStreamEvent, 'eventId' | 'sequence'>): CursorDecision {
  if (event.eventId === cursor.eventId || event.sequence <= cursor.sequence) return { kind: 'duplicate' };
  if (cursor.sequence > 0 && event.sequence > cursor.sequence + 1) return { kind: 'gap' };
  return { kind: 'advance', cursor: { eventId: event.eventId, sequence: event.sequence } };
}
