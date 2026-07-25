import { invoke, isTauri } from '@tauri-apps/api/core';

export type LocalRuntimeProvider = 'mock' | 'deepseek';
export const DEFAULT_LOCAL_RUNTIME_MODEL = 'deepseek-v4-flash';

export interface LocalRuntimeStatus {
  state: 'stopped' | 'running' | 'failed';
  apiUrl: string | null;
  workspaceId: string | null;
  provider: LocalRuntimeProvider | null;
  model: string | null;
  message: string | null;
}

export interface StartLocalRuntimeInput {
  provider: LocalRuntimeProvider;
  model: string | null;
  apiKey?: string;
}

export interface LocalRuntimeBoundary {
  isTauri: () => boolean;
  invoke: <T>(command: 'start_local_runtime' | 'stop_local_runtime' | 'get_local_runtime_status', args?: Record<string, unknown>) => Promise<T>;
}

const boundary: LocalRuntimeBoundary = { isTauri, invoke: (command, args) => invoke(command, args) };

const unavailable = (): Error => new Error('Qurio local runtime is available only in the native app. Connect to an already-running API instead.');

function native<T>(current: LocalRuntimeBoundary, run: () => Promise<T>): Promise<T> {
  if (!current.isTauri()) return Promise.reject(unavailable());
  return run();
}

export async function startLocalRuntime(input: StartLocalRuntimeInput, current: LocalRuntimeBoundary = boundary): Promise<LocalRuntimeStatus> {
  return native(current, () => current.invoke<LocalRuntimeStatus>('start_local_runtime', { request: input }));
}

export async function stopLocalRuntime(current: LocalRuntimeBoundary = boundary): Promise<LocalRuntimeStatus> {
  return native(current, () => current.invoke<LocalRuntimeStatus>('stop_local_runtime'));
}

export async function getLocalRuntimeStatus(current: LocalRuntimeBoundary = boundary): Promise<LocalRuntimeStatus> {
  return native(current, () => current.invoke<LocalRuntimeStatus>('get_local_runtime_status'));
}
