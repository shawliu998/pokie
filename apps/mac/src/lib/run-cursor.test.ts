import { describe, expect, it } from 'vitest';
import { parseRunCursor, reconcileRunCursor } from './run-cursor';

describe('run cursor recovery policy', () => {
  it('recovers malformed persisted cursors without leaving the run disconnected', () => {
    expect(parseRunCursor('{not-json')).toEqual({ eventId: '', sequence: 0 });
    expect(parseRunCursor('{"eventId":"event-4","sequence":4}')).toEqual({ eventId: 'event-4', sequence: 4 });
  });

  it('drops replay duplicates and requests a snapshot for sequence gaps', () => {
    const cursor = { eventId: 'event-4', sequence: 4 };
    expect(reconcileRunCursor(cursor, { eventId: 'event-4', sequence: 4 })).toEqual({ kind: 'duplicate' });
    expect(reconcileRunCursor(cursor, { eventId: 'event-6', sequence: 6 })).toEqual({ kind: 'gap' });
    expect(reconcileRunCursor(cursor, { eventId: 'event-5', sequence: 5 })).toEqual({ kind: 'advance', cursor: { eventId: 'event-5', sequence: 5 } });
  });
});
