import { invoke, isTauri } from '@tauri-apps/api/core';

const MAX_ACCESS_TOKEN_BYTES = 16 * 1024;

export type SessionFailureKind = 'missing' | 'expired' | 'unavailable';

export class SessionFailure extends Error {
  constructor(readonly kind: SessionFailureKind, message: string) {
    super(message);
    this.name = 'SessionFailure';
  }
}

export class SessionExpiredError extends SessionFailure {
  constructor() {
    super('expired', 'The Qurio session is missing, expired, or no longer authorized.');
    this.name = 'SessionExpiredError';
  }
}

export interface SessionEnvironment {
  dev: boolean;
  browserAccessToken?: string;
}

export interface NativeSessionBoundary {
  isTauri: () => boolean;
  invoke: <T>(command: 'get_access_token' | 'store_access_token' | 'clear_access_token', args?: { accessToken: string }) => Promise<T>;
}

const defaultBoundary: NativeSessionBoundary = {
  isTauri,
  invoke: (command, args) => invoke(command, args),
};

const defaultBrowserEnvironment = (): SessionEnvironment => ({
  dev: import.meta.env.DEV,
  browserAccessToken: import.meta.env.DEV ? import.meta.env.VITE_GLINT_ACCESS_TOKEN as string | undefined : undefined,
});

export function validateAccessToken(value: unknown): string {
  if (typeof value !== 'string') throw new SessionFailure('missing', 'No Qurio access token is stored in macOS Keychain.');
  const token = value.trim();
  if (!token) throw new SessionFailure('missing', 'No Qurio access token is stored in macOS Keychain.');
  if (new TextEncoder().encode(token).byteLength > MAX_ACCESS_TOKEN_BYTES || [...token].some((character) => character.charCodeAt(0) <= 31 || character.charCodeAt(0) === 127)) {
    throw new SessionFailure('unavailable', 'The stored Qurio access token has an invalid format.');
  }
  return token;
}

export function isNativeRuntime(boundary: NativeSessionBoundary = defaultBoundary): boolean {
  return boundary.isTauri();
}

export async function resolveAccessToken(
  boundary: NativeSessionBoundary = defaultBoundary,
  environment?: SessionEnvironment,
): Promise<string> {
  if (boundary.isTauri()) {
    try {
      return validateAccessToken(await boundary.invoke<string | null>('get_access_token'));
    } catch (reason) {
      if (reason instanceof SessionFailure) throw reason;
      throw new SessionFailure('unavailable', 'macOS Keychain could not provide the Qurio session.');
    }
  }
  const browserEnvironment = environment ?? defaultBrowserEnvironment();
  if (!browserEnvironment.dev) {
    throw new SessionFailure('unavailable', 'Browser production builds cannot load a compiled access token. Use the native Qurio app.');
  }
  try {
    return validateAccessToken(browserEnvironment.browserAccessToken);
  } catch (reason) {
    if (reason instanceof SessionFailure && reason.kind === 'missing') {
      throw new SessionFailure('missing', 'An access token is required only for browser development or API-mode E2E.');
    }
    throw reason;
  }
}

export async function storeAccessToken(accessToken: string, boundary: NativeSessionBoundary = defaultBoundary): Promise<void> {
  if (!boundary.isTauri()) throw new SessionFailure('unavailable', 'Secure session storage is only available in the native Qurio app.');
  const validated = validateAccessToken(accessToken);
  try {
    await boundary.invoke<void>('store_access_token', { accessToken: validated });
  } catch {
    throw new SessionFailure('unavailable', 'macOS Keychain could not store the Qurio session.');
  }
}

export async function clearAccessToken(boundary: NativeSessionBoundary = defaultBoundary): Promise<void> {
  if (!boundary.isTauri()) return;
  try {
    await boundary.invoke<void>('clear_access_token');
  } catch {
    throw new SessionFailure('unavailable', 'macOS Keychain could not clear the Qurio session.');
  }
}
