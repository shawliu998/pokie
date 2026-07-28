import { invoke, isTauri } from '@tauri-apps/api/core';
import presetSource from '../provider-presets.json';

export type LocalRuntimeProvider = 'mock' | 'deepseek' | 'openai_compatible';
export type LocalRuntimePresetId = 'mock' | 'deepseek' | 'kimi_k3' | 'openai' | 'qwen' | 'custom_openai_compatible';
export type LocalRuntimeRequestProfile = 'mock' | 'deepseek' | 'kimi_k3' | 'openai' | 'qwen' | 'custom';

export interface LocalRuntimePreset {
  id: LocalRuntimePresetId;
  label: string;
  transport: LocalRuntimeProvider;
  baseUrl: string | null;
  model: string | null;
  requestProfile: LocalRuntimeRequestProfile;
  verified: boolean;
}

export const LOCAL_RUNTIME_PRESETS = presetSource as LocalRuntimePreset[];
export const getLocalRuntimePreset = (id: LocalRuntimePresetId): LocalRuntimePreset => {
  const preset = LOCAL_RUNTIME_PRESETS.find((candidate) => candidate.id === id);
  if (!preset) throw new Error(`Unknown local runtime preset: ${id}`);
  return preset;
};

export const DEFAULT_LOCAL_RUNTIME_MODEL = 'deepseek-v4-flash';
export const DEFAULT_OPENAI_COMPATIBLE_BASE_URL = 'https://api.openai.com/v1';

export interface LocalRuntimeStatus {
  state: 'stopped' | 'running' | 'failed';
  apiUrl: string | null;
  workspaceId: string | null;
  provider: LocalRuntimeProvider | null;
  preset?: LocalRuntimePresetId | null;
  model: string | null;
  baseUrl: string | null;
  message: string | null;
}

export interface StartLocalRuntimeInput {
  preset?: LocalRuntimePresetId;
  provider: LocalRuntimeProvider;
  model: string | null;
  baseUrl?: string | null;
  apiKey?: string;
}

export type TestLocalRuntimeInput = StartLocalRuntimeInput;

export interface LocalRuntimeConnectionTest {
  provider: LocalRuntimePresetId;
  model: string | null;
  latencyMs: number;
  status: 'verified' | 'failed';
  message: string;
}

export interface LocalRuntimeBoundary {
  isTauri: () => boolean;
  invoke: <T>(command: 'start_local_runtime' | 'stop_local_runtime' | 'get_local_runtime_status' | 'test_local_runtime_provider', args?: Record<string, unknown>) => Promise<T>;
}

const boundary: LocalRuntimeBoundary = { isTauri, invoke: (command, args) => invoke(command, args) };

const unavailable = (): Error => new Error('Qurio local runtime is available only in the native app. Connect to an already-running API instead.');

export function localRuntimeInputForPreset(
  presetId: LocalRuntimePresetId,
  options: { apiKey?: string; customBaseUrl?: string; customModel?: string } = {},
): StartLocalRuntimeInput {
  const preset = getLocalRuntimePreset(presetId);
  const custom = preset.id === 'custom_openai_compatible';
  const model = custom ? (options.customModel ?? '').trim() : preset.model;
  const baseUrl = custom ? (options.customBaseUrl ?? '').trim() : preset.baseUrl;
  return {
    preset: preset.id,
    provider: preset.transport,
    model,
    ...(preset.transport === 'openai_compatible' ? { baseUrl } : {}),
    ...(options.apiKey?.trim() ? { apiKey: options.apiKey.trim() } : {}),
  };
}

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

export async function testLocalRuntimeProvider(input: TestLocalRuntimeInput, current: LocalRuntimeBoundary = boundary): Promise<LocalRuntimeConnectionTest> {
  return native(current, () => current.invoke<LocalRuntimeConnectionTest>('test_local_runtime_provider', { request: input }));
}
