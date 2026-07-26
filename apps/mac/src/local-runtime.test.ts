import { describe, expect, it } from 'vitest';
import { getLocalRuntimeStatus, startLocalRuntime, stopLocalRuntime, type LocalRuntimeBoundary } from './local-runtime';

const status = { state: 'running' as const, apiUrl: 'http://127.0.0.1:8123', workspaceId: 'workspace-1', provider: 'mock' as const, model: null, baseUrl: null, message: null };

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

  it('passes only the explicit OpenAI-compatible endpoint, model, and write-only key', async () => {
    const calls: Array<[string, Record<string, unknown> | undefined]> = [];
    const native: LocalRuntimeBoundary = { isTauri: () => true, invoke: async <T,>(command: 'start_local_runtime' | 'stop_local_runtime' | 'get_local_runtime_status', args?: Record<string, unknown>) => {
      calls.push([command, args]);
      return { ...status, provider: 'openai_compatible', model: 'provider-model', baseUrl: 'https://provider.example/v1' } as T;
    } };
    await startLocalRuntime({ provider: 'openai_compatible', model: 'provider-model', baseUrl: 'https://provider.example/v1', apiKey: 'write-only' }, native);
    expect(calls).toEqual([['start_local_runtime', { request: { provider: 'openai_compatible', model: 'provider-model', baseUrl: 'https://provider.example/v1', apiKey: 'write-only' } }]]);
  });

  it('fails outside the native app', async () => {
    const browser: LocalRuntimeBoundary = { isTauri: () => false, invoke: async <T>() => status as T };
    await expect(startLocalRuntime({ provider: 'mock', model: null }, browser)).rejects.toThrow('native app');
  });
});
