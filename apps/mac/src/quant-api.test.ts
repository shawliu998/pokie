import { describe, expect, it } from 'vitest';
import { createFixtureQuantApi } from './quant-api';

describe('Quant fixture API adapter', () => {
  it('rejects commands absent from the completed snapshot without mutating run state', async () => {
    const api = createFixtureQuantApi();
    const before = (await api.getWorkspaceSnapshot()).run.state;
    const unsupported = await api.sendCommand({ command: 'start_new_run', expectedVersion: 12, idempotencyKey: 'test-unsupported' });
    const illegal = await api.sendCommand({ command: 'retry_run', expectedVersion: 12, idempotencyKey: 'test-illegal' });
    expect(unsupported.status).toBe('rejected');
    expect(illegal.status).toBe('rejected');
    expect((await api.getWorkspaceSnapshot()).run.state).toBe(before);
  });
});
