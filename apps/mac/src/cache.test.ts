import { afterEach, describe, expect, it } from 'vitest';
import type { WorkspaceState } from './domain';
import { loadWorkspaceCache, storeWorkspaceCache, type CacheBoundary } from './cache';

const workspace = { workspaceId: 'workspace-1', principalId: 'principal-1', workspaceName: 'Glint', cachedAt: null, authenticity: 'human_authored', signals: [], investigations: [], briefs: [], sources: [{ sourceConfig: { connectorType: 'rss', feeds: [{ name: 'Public', feedUrl: 'https://example.com/feed' }] } }], watchlists: [], schedules: [{ id: 'schedule-1' }], navigation: { unreviewedSignalCount: 0, investigationNeedsInputCount: 0, draftDecisionBriefCount: 0, monitoringHealth: 'healthy', computedAt: '2026-07-15T05:00:00Z' } } as unknown as WorkspaceState;

describe('scoped redacted offline cache boundary', () => {
  afterEach(() => localStorage.clear());

  it('stores only a versioned redacted projection and reloads the exact native scope', async () => {
    let stored = '';
    const boundary: CacheBoundary = { isTauri: () => true, invoke: async <T,>(command: 'store_offline_cache' | 'get_offline_cache' | 'clear_offline_cache', args?: Record<string, string>) => {
      if (command === 'store_offline_cache') { stored = args?.projectionJson ?? ''; return undefined as T; }
      if (command === 'get_offline_cache') return stored as T;
      return undefined as T;
    } };
    await storeWorkspaceCache(workspace, boundary, { dev: false });
    expect(stored).not.toContain('https://example.com/feed');
    expect(stored).not.toMatch(/access[_-]?token|credential_ref/i);
    const loaded = await loadWorkspaceCache('workspace-1', boundary, { dev: false });
    expect(loaded?.principalId).toBe('principal-1');
    expect(loaded?.cachedAt).toMatch(/Z$/);
    expect(loaded?.sources[0]?.sourceConfig).toBeNull();
    expect(loaded?.schedules).toEqual([]);
  });

  it('fails closed for browser principal mismatches and unsupported historical cache versions', async () => {
    await expect(storeWorkspaceCache(workspace, { isTauri: () => false, invoke: async <T,>() => undefined as T }, { dev: true, principalId: 'other-principal' })).rejects.toThrow(/matching development principal/i);
    const old = JSON.stringify({ schemaVersion: 'glint-redacted-workspace-v0', workspaceId: 'workspace-1', principalId: 'principal-1', cachedAt: '2026-07-15T05:00:00Z', projection: workspace });
    const native: CacheBoundary = { isTauri: () => true, invoke: async <T,>() => old as T };
    await expect(loadWorkspaceCache('workspace-1', native, { dev: false })).resolves.toBeNull();
  });
});
