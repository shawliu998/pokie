import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Button } from '@glint/ui';
import { createApi, type GlintApi } from '../../api';
import { clearAccessToken, isNativeRuntime, SessionExpiredError, SessionFailure, storeAccessToken } from '../../session';
import { clearConnectionProfile, connectionDraft, storeConnectionProfile } from '../../connection';
import { sessionRecoveryMode } from '../../lib/workbench-state';
import { DEFAULT_LOCAL_RUNTIME_MODEL, getLocalRuntimeStatus, startLocalRuntime, type LocalRuntimeProvider, type LocalRuntimeStatus } from '../../local-runtime';

interface SessionBoundaryProps {
  children: (api: GlintApi) => ReactNode;
}

export function SessionBoundary({ children }: SessionBoundaryProps) {
  const [api, setApi] = useState<GlintApi | null>(null);
  const [failure, setFailure] = useState<SessionFailure | null>(null);
  const [loading, setLoading] = useState(true);
  const native = isNativeRuntime();
  const expire = useCallback(() => {
    setApi(null);
    setFailure(new SessionExpiredError());
    if (isNativeRuntime()) void clearAccessToken().catch(() => setFailure(new SessionFailure('unavailable', 'The expired session could not be cleared from macOS Keychain.')));
  }, []);
  const connect = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    try {
      const connected = await createApi(expire);
      setApi(connected.api);
    } catch (reason) {
      setApi(null);
      setFailure(reason instanceof SessionFailure ? reason : new SessionFailure('unavailable', 'Qurio could not connect to this workspace.'));
    } finally {
      setLoading(false);
    }
  }, [expire]);
  useEffect(() => { void connect(); }, [connect]);
  if (loading) return <div className="loading-shell" aria-live="polite"><div className="skeleton title" /><div className="skeleton wide" /><p>Connecting Qurio…</p></div>;
  if (!api) return <SessionRecovery failure={failure} native={native} onReconnect={connect} />;
  return children(api);
}

export function SessionRecovery({ failure, native, onReconnect }: { failure: SessionFailure | null; native: boolean; onReconnect: () => Promise<void> }) {
  const [token, setToken] = useState('');
  const [connection, setConnection] = useState(connectionDraft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<LocalRuntimeStatus | null>(null);
  const [runtimeProvider, setRuntimeProvider] = useState<LocalRuntimeProvider>('deepseek');
  const [runtimeModel, setRuntimeModel] = useState(DEFAULT_LOCAL_RUNTIME_MODEL);
  const [runtimeApiKey, setRuntimeApiKey] = useState('');
  const mode = sessionRecoveryMode(native);
  const tokenRequired = failure?.kind === 'expired' || /access token/i.test(failure?.message ?? '');
  useEffect(() => {
    if (!native) return;
    void getLocalRuntimeStatus().then(setRuntimeStatus).catch(() => undefined);
  }, [native]);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      storeConnectionProfile(connection);
      if (token.trim()) await storeAccessToken(token);
      setToken('');
      await onReconnect();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to save the Qurio connection.');
    } finally {
      setBusy(false);
    }
  };
  const clear = async () => {
    setBusy(true);
    setError(null);
    try {
      clearConnectionProfile();
      await clearAccessToken();
      setConnection({ apiUrl: '', workspaceId: '' });
      await onReconnect();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to clear the Qurio connection.');
    } finally {
      setBusy(false);
    }
  };
  const startLocal = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await startLocalRuntime({ provider: runtimeProvider, model: runtimeProvider === 'deepseek' ? runtimeModel.trim() : null, ...(runtimeApiKey.trim() ? { apiKey: runtimeApiKey.trim() } : {}) });
      setRuntimeStatus(next);
      setRuntimeApiKey('');
      if (!next.apiUrl || !next.workspaceId) throw new Error(next.message || 'The local runtime started without a workspace connection.');
      const profile = storeConnectionProfile({ apiUrl: next.apiUrl, workspaceId: next.workspaceId });
      setConnection(profile);
      await onReconnect();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to start the local runtime.');
    } finally {
      setBusy(false);
    }
  };
  return <main className="fatal"><section className="session-recovery" aria-labelledby="session-title"><p className="session-kicker">Qurio desktop</p><h1 id="session-title">Connect a research workspace</h1><p>Enter the local or hosted Qurio workspace you want to use on this Mac.</p>{failure && <p className="session-error" role="alert">{failure.message}</p>}{mode === 'native-keychain' ? <>{native && <><div className="session-runtime"><strong>Start local runtime</strong><p className="hint">Source-checkout runtime; requires this repository and its .venv.</p><div className="session-fields"><label>Provider<select value={runtimeProvider} disabled={busy} onChange={(event) => setRuntimeProvider(event.target.value as LocalRuntimeProvider)}><option value="deepseek">DeepSeek</option><option value="mock">Offline deterministic</option></select></label>{runtimeProvider === 'deepseek' && <label>Model<input value={runtimeModel} disabled={busy} onChange={(event) => setRuntimeModel(event.target.value)} /></label>}</div>{runtimeProvider === 'deepseek' && <label>API key <span className="hint">Optional; leave blank to reuse Keychain.</span><input type="password" autoComplete="off" value={runtimeApiKey} disabled={busy} onChange={(event) => setRuntimeApiKey(event.target.value)} /></label>}{runtimeStatus?.message && <p className="hint">{runtimeStatus.message}</p>}<Button className="primary" disabled={busy || (runtimeProvider === 'deepseek' && !runtimeModel.trim())} onClick={() => void startLocal()}>Start &amp; connect</Button></div><div className="session-divider" /></>}<div className="session-fields"><label>API URL<input type="url" autoComplete="url" placeholder="http://127.0.0.1:8135" value={connection.apiUrl} disabled={busy} onChange={(event) => setConnection((current) => ({ ...current, apiUrl: event.target.value }))} /></label><label>Workspace ID<input autoComplete="off" spellCheck={false} placeholder="Workspace UUID" value={connection.workspaceId} disabled={busy} onChange={(event) => setConnection((current) => ({ ...current, workspaceId: event.target.value }))} /></label></div><label>Access token<input type="password" autoComplete="off" spellCheck={false} value={token} disabled={busy} onChange={(event) => setToken(event.target.value)} /></label><p className="hint">The endpoint and workspace are saved on this Mac. The token stays in macOS Keychain; leave it blank only to reuse an existing Keychain session.</p>{error && <p className="session-error" role="alert">{error}</p>}<div className="actions"><Button className="primary" disabled={busy || (tokenRequired && !token.trim()) || !connection.apiUrl.trim() || !connection.workspaceId.trim()} onClick={() => void save()}>Save & connect</Button><Button disabled={busy} onClick={() => void clear()}>Clear connection</Button></div></> : <><p>Browser sessions are available only in development and API-mode E2E. Start Qurio with its development session configuration, then retry.</p><Button onClick={() => void onReconnect()}>Retry connection</Button></>}</section></main>;
}
