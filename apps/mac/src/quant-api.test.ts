import { describe, expect, it } from 'vitest';
import { createFixtureQuantApi } from './quant-api';

describe('Quant fixture API adapter', () => {
  it('accepts only snapshot-legal commands without mutating run state', async () => {
    const api = createFixtureQuantApi();
    const before = (await api.getWorkspaceSnapshot()).run.state;
    const legal = await api.sendCommand({ command: 'start_new_run', expectedVersion: 12, idempotencyKey: 'test-legal' });
    const illegal = await api.sendCommand({ command: 'retry_run', expectedVersion: 12, idempotencyKey: 'test-illegal' });
    expect(legal.status).toBe('fixture_only');
    expect(illegal.status).toBe('rejected');
    expect((await api.getWorkspaceSnapshot()).run.state).toBe(before);
  });
});
