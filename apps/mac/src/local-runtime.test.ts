import { describe, expect, it } from 'vitest';
import { getLocalRuntimeStatus, startLocalRuntime, stopLocalRuntime, type LocalRuntimeBoundary } from './local-runtime';

const status = { state: 'running' as const, apiUrl: 'http://127.0.0.1:8123', workspaceId: 'workspace-1', provider: 'mock' as const, model: null, message: null };

describe('local runtime bridge', () => {
  it('uses only the fixed native commands and returns non-secret status', async () => {
    const calls: Array<[string, Record<string, unknown> | undefined]> = [];
    const native: LocalRuntimeBoundary = { isTauri: () => true, invoke: async <T,>(command: 'start_local_runtime' | 'stop_local_runtime' | 'get_local_runtime_status', args?: Record<string, unknown>) => { calls.push([command, args]); return status as T; } };
    await expect(startLocalRuntime({ provider: 'mock', model: null }, native)).resolves.toEqual(status);
    await expect(getLocalRuntimeStatus(native)).resolves.toEqual(status);
    await expect(stopLocalRuntime(native)).resolves.toEqual(status);
    expect(calls).toEqual([
      ['start_local_runtime', { request: { provider: 'mock', model: null } }],
      ['get_local_runtime_status', undefined],
      ['stop_local_runtime', undefined],
    ]);
    expect(JSON.stringify(status)).not.toContain('apiKey');
  });

  it('fails outside the native app', async () => {
    const browser: LocalRuntimeBoundary = { isTauri: () => false, invoke: async <T>() => status as T };
    await expect(startLocalRuntime({ provider: 'mock', model: null }, browser)).rejects.toThrow('native app');
  });
});
