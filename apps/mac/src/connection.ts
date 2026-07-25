import { SessionFailure } from './session';

const CONNECTION_PROFILE_KEY = 'qurio.connection-profile.v1';

export interface ConnectionProfile {
  apiUrl: string;
  workspaceId: string;
}

export interface ConnectionEnvironment {
  apiUrl?: string;
  workspaceId?: string;
}

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const defaultEnvironment = (): ConnectionEnvironment => ({
  apiUrl: import.meta.env.VITE_GLINT_API_URL as string | undefined,
  workspaceId: import.meta.env.VITE_GLINT_WORKSPACE_ID as string | undefined,
});

const defaultStorage = (): StorageLike | undefined => typeof localStorage === 'undefined' ? undefined : localStorage;

export function validateConnectionProfile(value: ConnectionProfile): ConnectionProfile {
  const apiUrl = value.apiUrl.trim();
  const workspaceId = value.workspaceId.trim();
  if (!apiUrl) throw new SessionFailure('missing', 'Enter the Qurio API URL.');
  if (!workspaceId) throw new SessionFailure('missing', 'Enter the Qurio workspace ID.');
  let parsed: URL;
  try {
    parsed = new URL(apiUrl);
  } catch {
    throw new SessionFailure('unavailable', 'Enter a valid Qurio API URL, including http:// or https://.');
  }
  const loopbackHttp = parsed.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname);
  if ((parsed.protocol !== 'https:' && !loopbackHttp) || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new SessionFailure('unavailable', 'Enter a valid Qurio API URL, including http:// or https://.');
  }
  return { apiUrl: parsed.toString().replace(/\/$/, ''), workspaceId };
}

export function readStoredConnectionProfile(storage: StorageLike | undefined = defaultStorage()): ConnectionProfile | null {
  const raw = storage?.getItem(CONNECTION_PROFILE_KEY);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<ConnectionProfile>;
    if (typeof value.apiUrl !== 'string' || typeof value.workspaceId !== 'string') return null;
    return validateConnectionProfile({ apiUrl: value.apiUrl, workspaceId: value.workspaceId });
  } catch {
    return null;
  }
}

export function connectionDraft(
  environment: ConnectionEnvironment = defaultEnvironment(),
  storage: StorageLike | undefined = defaultStorage(),
): ConnectionProfile {
  const stored = readStoredConnectionProfile(storage);
  return {
    apiUrl: environment.apiUrl?.trim() || stored?.apiUrl || '',
    workspaceId: environment.workspaceId?.trim() || stored?.workspaceId || '',
  };
}

export function resolveConnectionProfile(
  environment: ConnectionEnvironment = defaultEnvironment(),
  storage: StorageLike | undefined = defaultStorage(),
): ConnectionProfile {
  if (environment.apiUrl?.trim() && environment.workspaceId?.trim()) {
    return validateConnectionProfile({ apiUrl: environment.apiUrl, workspaceId: environment.workspaceId });
  }
  const stored = readStoredConnectionProfile(storage);
  if (stored) return stored;
  throw new SessionFailure('missing', 'Connect this Mac to a Qurio workspace to continue.');
}

export function storeConnectionProfile(profile: ConnectionProfile, storage: StorageLike | undefined = defaultStorage()): ConnectionProfile {
  const validated = validateConnectionProfile(profile);
  if (!storage) throw new SessionFailure('unavailable', 'This browser cannot save a Qurio workspace connection.');
  storage.setItem(CONNECTION_PROFILE_KEY, JSON.stringify(validated));
  return validated;
}

export function clearConnectionProfile(storage: StorageLike | undefined = defaultStorage()): void {
  storage?.removeItem(CONNECTION_PROFILE_KEY);
}
