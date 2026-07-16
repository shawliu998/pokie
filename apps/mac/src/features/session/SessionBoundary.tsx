import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Button } from '@glint/ui';
import { createApi, type GlintApi } from '../../api';
import { clearAccessToken, isNativeRuntime, SessionExpiredError, SessionFailure, storeAccessToken } from '../../session';
import { sessionRecoveryMode } from '../../lib/workbench-state';

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
      setFailure(reason instanceof SessionFailure ? reason : new SessionFailure('unavailable', reason instanceof Error ? reason.message : 'Secure session bootstrap failed.'));
    } finally {
      setLoading(false);
    }
  }, [expire]);
  useEffect(() => { void connect(); }, [connect]);
  if (loading) return <div className="loading-shell" aria-live="polite"><div className="skeleton title" /><div className="skeleton wide" /><p>Loading secure session…</p></div>;
  if (!api) return <SessionRecovery failure={failure} native={native} onReconnect={connect} />;
  return children(api);
}

function SessionRecovery({ failure, native, onReconnect }: { failure: SessionFailure | null; native: boolean; onReconnect: () => Promise<void> }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mode = sessionRecoveryMode(native);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await storeAccessToken(token);
      setToken('');
      await onReconnect();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to store the secure session.');
    } finally {
      setBusy(false);
    }
  };
  return <main className="fatal"><section className="session-recovery" aria-labelledby="session-title"><h1 id="session-title">Secure session required</h1><p role="alert">{failure?.message ?? 'Glint could not initialize its secure session.'}</p>{mode === 'native-keychain' ? <><p>Paste a current access token. It is sent directly to the native macOS Keychain command and is never written to localStorage.</p><label>Access token<input type="password" autoComplete="off" spellCheck={false} value={token} disabled={busy} onChange={(event) => setToken(event.target.value)} /></label>{error && <p role="alert">{error}</p>}<div className="actions"><Button className="primary" disabled={busy || !token.trim()} onClick={() => void save()}>Store in Keychain & reconnect</Button><Button disabled={busy} onClick={() => void clearAccessToken().then(onReconnect).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Unable to clear the secure session.'))}>Clear stored session</Button></div></> : <><p>Browser sessions are allowed only in development and API-mode E2E. Configure VITE_GLINT_ACCESS_TOKEN in that process and restart it.</p><Button onClick={() => void onReconnect()}>Retry secure bootstrap</Button></>}</section></main>;
}
