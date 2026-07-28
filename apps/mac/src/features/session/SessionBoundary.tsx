import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Button, Field, FieldDescription, FieldError, FieldLabel, Skeleton } from '@glint/ui';
import { createApi, type GlintApi } from '../../api';
import { clearAccessToken, isNativeRuntime, SessionExpiredError, SessionFailure, storeAccessToken } from '../../session';
import { clearConnectionProfile, connectionDraft, storeConnectionProfile } from '../../connection';
import { sessionRecoveryMode } from '../../lib/workbench-state';
import {
  DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
  getLocalRuntimePreset,
  getLocalRuntimeStatus,
  LOCAL_RUNTIME_PRESETS,
  localRuntimeInputForPreset,
  startLocalRuntime,
  testLocalRuntimeProvider,
  type LocalRuntimeConnectionTest,
  type LocalRuntimePresetId,
  type LocalRuntimeStatus,
} from '../../local-runtime';

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
  if (loading) return <div className="loading-shell" aria-live="polite"><Skeleton className="title" /><Skeleton className="wide" /><p>Connecting Qurio…</p></div>;
  if (!api) return <SessionRecovery failure={failure} native={native} onReconnect={connect} />;
  return children(api);
}

export function SessionRecovery({ failure, native, onReconnect }: { failure: SessionFailure | null; native: boolean; onReconnect: () => Promise<void> }) {
  const [token, setToken] = useState('');
  const [connection, setConnection] = useState(connectionDraft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<LocalRuntimeStatus | null>(null);
  const [runtimePreset, setRuntimePreset] = useState<LocalRuntimePresetId>('mock');
  const [compatibleBaseUrl, setCompatibleBaseUrl] = useState(DEFAULT_OPENAI_COMPATIBLE_BASE_URL);
  const [compatibleModel, setCompatibleModel] = useState('');
  const [runtimeApiKey, setRuntimeApiKey] = useState('');
  const [connectionTest, setConnectionTest] = useState<LocalRuntimeConnectionTest | null>(null);
  const [startupStep, setStartupStep] = useState<'idle' | 'starting' | 'connecting'>('idle');
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
    setStartupStep('starting');
    setError(null);
    try {
      const next = await startLocalRuntime({
        ...localRuntimeInputForPreset(runtimePreset, {
          apiKey: runtimeApiKey,
          customBaseUrl: compatibleBaseUrl,
          customModel: compatibleModel,
        }),
      });
      setRuntimeStatus(next);
      setRuntimeApiKey('');
      if (!next.apiUrl || !next.workspaceId) throw new Error(next.message || 'The local runtime started without a workspace connection.');
      const profile = storeConnectionProfile({ apiUrl: next.apiUrl, workspaceId: next.workspaceId });
      setConnection(profile);
      setStartupStep('connecting');
      await onReconnect();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to start the local runtime.');
    } finally {
      setBusy(false);
      setStartupStep('idle');
    }
  };
  const testProvider = async () => {
    setBusy(true);
    setError(null);
    setConnectionTest(null);
    try {
      setConnectionTest(await testLocalRuntimeProvider(localRuntimeInputForPreset(runtimePreset, {
        apiKey: runtimeApiKey,
        customBaseUrl: compatibleBaseUrl,
        customModel: compatibleModel,
      })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to test this model provider.');
    } finally {
      setBusy(false);
    }
  };
  const selectedPreset = getLocalRuntimePreset(runtimePreset);
  const customPreset = runtimePreset === 'custom_openai_compatible';
  const validPreset = runtimePreset === 'mock' || (customPreset
    ? Boolean(compatibleModel.trim() && compatibleBaseUrl.trim())
    : Boolean(selectedPreset.model));
  return <main className="fatal">
    <section className="session-recovery" aria-labelledby="session-title">
      <img className="session-brand" src="/brand/qurio-wordmark.svg" alt="Qurio" />
      <h1 id="session-title">{native ? 'Start Qurio on this Mac' : 'Connect Qurio'}</h1>
      <p>{native ? 'Choose a model provider. Qurio will prepare the included local runtime and open a ready research workspace.' : 'Connect to a development research workspace.'}</p>
      {failure && <p className={failure.kind === 'missing' ? 'session-notice' : 'session-error'} role={failure.kind === 'missing' ? 'status' : 'alert'}>{failure.message}</p>}
      {mode === 'native-keychain' ? <>
        {native && <div className="session-runtime">
          <div className="session-fields">
            <Field><FieldLabel>Model provider
              <select value={runtimePreset} disabled={busy} onChange={(event) => { setRuntimePreset(event.target.value as LocalRuntimePresetId); setConnectionTest(null); }}>
                {LOCAL_RUNTIME_PRESETS.filter((preset) => preset.verified).map((preset) => <option key={preset.id} value={preset.id}>{preset.id === 'mock' ? `${preset.label} — no API key` : preset.label}</option>)}
                <option value="custom_openai_compatible">Custom OpenAI-compatible — advanced</option>
              </select>
            </FieldLabel></Field>
            {runtimePreset !== 'mock' && !customPreset && <Field><FieldLabel>Model
              <input value={selectedPreset.model ?? ''} disabled readOnly />
            </FieldLabel></Field>}
            {customPreset && <Field><FieldLabel>Model
              <input placeholder="Provider model ID" value={compatibleModel} disabled={busy} onChange={(event) => setCompatibleModel(event.target.value)} />
            </FieldLabel></Field>}
          </div>
          {runtimePreset !== 'mock' && !customPreset && <Field>
            <FieldLabel>Endpoint<input type="url" value={selectedPreset.baseUrl ?? ''} disabled readOnly /></FieldLabel>
            <FieldDescription>Qurio’s reviewed endpoint and request profile for this preset.</FieldDescription>
          </Field>}
          {customPreset && <Field>
            <FieldLabel>Base URL
              <input type="url" autoComplete="url" placeholder="https://provider.example/v1" value={compatibleBaseUrl} disabled={busy} onChange={(event) => setCompatibleBaseUrl(event.target.value)} />
            </FieldLabel>
            <FieldDescription>HTTPS only. Custom endpoints are not a verified preset.</FieldDescription>
          </Field>}
          {runtimePreset !== 'mock' && <Field>
            <FieldLabel>{selectedPreset.label} API key
              <input type="password" autoComplete="off" value={runtimeApiKey} disabled={busy} onChange={(event) => setRuntimeApiKey(event.target.value)} />
            </FieldLabel>
            <FieldDescription>Stored separately for this provider in macOS Keychain. Leave blank to reuse a saved key.</FieldDescription>
          </Field>}
          {connectionTest && <p className={connectionTest.status === 'verified' ? 'session-notice' : 'session-error'} role="status">
            {connectionTest.status === 'verified' ? 'Connection verified' : 'Connection failed'} · {connectionTest.provider} · {connectionTest.model ?? 'offline'} · {connectionTest.latencyMs} ms
          </p>}
          {startupStep !== 'idle'
            ? <p className="session-progress" role="status">{startupStep === 'starting' ? 'Starting the local runtime…' : 'Opening your research workspace…'}</p>
            : runtimeStatus?.message && <p className="hint">{runtimeStatus.message}</p>}
          {error && <FieldError className="session-error">{error}</FieldError>}
          <div className="actions">
            <Button disabled={busy || !validPreset} onClick={() => void testProvider()}>Test connection</Button>
            <Button className="primary session-start" disabled={busy || !validPreset} onClick={() => void startLocal()}>
              {busy ? 'Preparing Qurio…' : 'Start Qurio'}
            </Button>
          </div>
          <p className="session-contained">The runtime is included. No Python, terminal, or repository setup is required.</p>
        </div>}
        <details className="session-advanced">
          <summary>Connect an existing workspace</summary>
          <p className="hint">For hosted or separately managed Qurio workspaces.</p>
          <div className="session-fields">
            <Field><FieldLabel>API URL<input type="url" autoComplete="url" placeholder="http://127.0.0.1:8135" value={connection.apiUrl} disabled={busy} onChange={(event) => setConnection((current) => ({ ...current, apiUrl: event.target.value }))} /></FieldLabel></Field>
            <Field><FieldLabel>Workspace ID<input autoComplete="off" spellCheck={false} placeholder="Workspace UUID" value={connection.workspaceId} disabled={busy} onChange={(event) => setConnection((current) => ({ ...current, workspaceId: event.target.value }))} /></FieldLabel></Field>
          </div>
          <Field><FieldLabel>Access token<input type="password" autoComplete="off" spellCheck={false} value={token} disabled={busy} onChange={(event) => setToken(event.target.value)} /></FieldLabel></Field>
          <p className="hint">The endpoint and workspace stay on this Mac. The token stays in macOS Keychain.</p>
          <div className="actions">
            <Button className="primary" disabled={busy || (tokenRequired && !token.trim()) || !connection.apiUrl.trim() || !connection.workspaceId.trim()} onClick={() => void save()}>Save &amp; connect</Button>
            <Button disabled={busy} onClick={() => void clear()}>Clear connection</Button>
          </div>
        </details>
      </> : <>
        <p>Browser sessions are available only in development and API-mode E2E. Start Qurio with its development session configuration, then retry.</p>
        <Button onClick={() => void onReconnect()}>Retry connection</Button>
      </>}
    </section>
  </main>;
}
