import { invoke, isTauri } from '@tauri-apps/api/core';
import type { WorkspaceState } from './domain';

const CACHE_SCHEMA = 'glint-redacted-workspace-v1';

interface CacheEnvelope {
  schemaVersion: typeof CACHE_SCHEMA;
  workspaceId: string;
  principalId: string;
  cachedAt: string;
  projection: WorkspaceState;
}

export interface CacheBoundary {
  isTauri: () => boolean;
  invoke: <T>(command: 'store_offline_cache' | 'get_offline_cache' | 'clear_offline_cache', args?: Record<string, string>) => Promise<T>;
}

export interface CacheEnvironment { dev: boolean; principalId?: string }

const defaultBoundary: CacheBoundary = { isTauri, invoke: (command, args) => invoke(command, args) };
const defaultEnvironment = (): CacheEnvironment => ({ dev: import.meta.env.DEV, principalId: import.meta.env.DEV ? import.meta.env.VITE_GLINT_PRINCIPAL_ID as string | undefined : undefined });
const browserKey = (workspaceId: string, principalId: string) => `glint:dev-offline-cache:${workspaceId}:${principalId}`;

function redactedProjection(workspace: WorkspaceState, cachedAt: string): WorkspaceState {
  return {
    ...workspace,
    cachedAt,
    sources: workspace.sources.map((source) => ({ ...source, sourceConfig: null })),
    schedules: [],
  };
}

function parseEnvelope(raw: string, workspaceId: string, principalId?: string): CacheEnvelope | null {
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return null; }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const envelope = value as Partial<CacheEnvelope>;
  if (envelope.schemaVersion !== CACHE_SCHEMA || envelope.workspaceId !== workspaceId || typeof envelope.principalId !== 'string' || (principalId && envelope.principalId !== principalId) || typeof envelope.cachedAt !== 'string') return null;
  const projection = envelope.projection;
  if (!projection || projection.workspaceId !== workspaceId || projection.principalId !== envelope.principalId || projection.cachedAt !== envelope.cachedAt || !Array.isArray(projection.signals) || !Array.isArray(projection.investigations) || !Array.isArray(projection.briefs)) return null;
  if (Number.isNaN(new Date(envelope.cachedAt).getTime())) return null;
  return envelope as CacheEnvelope;
}

export async function storeWorkspaceCache(workspace: WorkspaceState, boundary: CacheBoundary = defaultBoundary, environment: CacheEnvironment = defaultEnvironment()): Promise<string> {
  if (!workspace.principalId) throw new Error('A principal-scoped online projection is required before caching.');
  const cachedAt = new Date().toISOString();
  const envelope: CacheEnvelope = { schemaVersion: CACHE_SCHEMA, workspaceId: workspace.workspaceId, principalId: workspace.principalId, cachedAt, projection: redactedProjection(workspace, cachedAt) };
  const serialized = JSON.stringify(envelope);
  if (boundary.isTauri()) {
    await boundary.invoke<void>('store_offline_cache', { workspaceId: workspace.workspaceId, principalId: workspace.principalId, cachedAt, projectionJson: serialized });
  } else {
    if (!environment.dev || environment.principalId !== workspace.principalId) throw new Error('Browser offline cache requires an explicit matching development principal scope.');
    localStorage.setItem(browserKey(workspace.workspaceId, workspace.principalId), serialized);
  }
  return cachedAt;
}

export async function loadWorkspaceCache(workspaceId: string, boundary: CacheBoundary = defaultBoundary, environment: CacheEnvironment = defaultEnvironment()): Promise<WorkspaceState | null> {
  let raw: string | null;
  if (boundary.isTauri()) {
    raw = await boundary.invoke<string | null>('get_offline_cache', { workspaceId });
  } else {
    if (!environment.dev || !environment.principalId) return null;
    raw = localStorage.getItem(browserKey(workspaceId, environment.principalId));
  }
  if (!raw) return null;
  return parseEnvelope(raw, workspaceId, boundary.isTauri() ? undefined : environment.principalId)?.projection ?? null;
}

export async function clearWorkspaceCache(workspaceId: string, boundary: CacheBoundary = defaultBoundary, environment: CacheEnvironment = defaultEnvironment()): Promise<void> {
  if (boundary.isTauri()) await boundary.invoke<void>('clear_offline_cache', { workspaceId });
  else if (environment.dev && environment.principalId) localStorage.removeItem(browserKey(workspaceId, environment.principalId));
}

export const cacheSchemaVersion = CACHE_SCHEMA;
