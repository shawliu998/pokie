import { describe, expect, it } from 'vitest';
import { clearConnectionProfile, connectionDraft, readStoredConnectionProfile, resolveConnectionProfile, storeConnectionProfile } from './connection';

const storage = () => {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    dump: () => [...values.entries()],
  };
};

describe('Qurio connection profile', () => {
  it('stores only a validated endpoint and workspace ID', () => {
    const local = storage();
    expect(storeConnectionProfile({ apiUrl: ' https://qurio.example.test/ ', workspaceId: ' workspace-a ' }, local)).toEqual({ apiUrl: 'https://qurio.example.test', workspaceId: 'workspace-a' });
    expect(readStoredConnectionProfile(local)).toEqual({ apiUrl: 'https://qurio.example.test', workspaceId: 'workspace-a' });
    expect(JSON.stringify(local.dump())).not.toContain('token');
  });

  it('uses a complete build-time connection before the saved profile', () => {
    const local = storage();
    storeConnectionProfile({ apiUrl: 'http://127.0.0.1:8135', workspaceId: 'saved-workspace' }, local);
    expect(resolveConnectionProfile({ apiUrl: 'https://configured.example.test', workspaceId: 'configured-workspace' }, local)).toEqual({ apiUrl: 'https://configured.example.test', workspaceId: 'configured-workspace' });
    expect(connectionDraft({ apiUrl: 'https://configured.example.test' }, local)).toEqual({ apiUrl: 'https://configured.example.test', workspaceId: 'saved-workspace' });
  });

  it('rejects malformed endpoints and clears the local connection profile', () => {
    const local = storage();
    expect(() => storeConnectionProfile({ apiUrl: 'qurio.example.test', workspaceId: 'workspace-a' }, local)).toThrow('valid Qurio API URL');
    expect(() => storeConnectionProfile({ apiUrl: 'http://qurio.example.test', workspaceId: 'workspace-a' }, local)).toThrow('valid Qurio API URL');
    storeConnectionProfile({ apiUrl: 'http://127.0.0.1:8135', workspaceId: 'workspace-a' }, local);
    clearConnectionProfile(local);
    expect(readStoredConnectionProfile(local)).toBeNull();
    expect(() => resolveConnectionProfile({}, local)).toThrow('Connect this Mac');
  });
});
