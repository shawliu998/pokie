import { useEffect, useMemo, useState } from 'react';
import { Button } from '@glint/ui';
import { connectionDraft, storeConnectionProfile } from '../../connection';
import { DEFAULT_LOCAL_RUNTIME_MODEL, getLocalRuntimeStatus, startLocalRuntime, stopLocalRuntime, type LocalRuntimeProvider, type LocalRuntimeStatus } from '../../local-runtime';
import type { QuantWorkspaceSnapshot } from '../../quant-domain';
import { isNativeRuntime } from '../../session';

const terminalRunStates = new Set(['completed', 'failed', 'cancelled']);
const providerLabel = (provider: LocalRuntimeProvider | null) => provider === 'deepseek' ? 'DeepSeek' : provider === 'mock' ? 'Offline deterministic' : 'Not started';

function statusLabel(status: LocalRuntimeStatus | null) {
  if (!status) return 'Checking';
  if (status.state === 'running') return 'Running';
  if (status.state === 'failed') return 'Needs attention';
  return 'Stopped';
}

function hasConnection(status: LocalRuntimeStatus): status is LocalRuntimeStatus & { apiUrl: string; workspaceId: string } {
  return Boolean(status.apiUrl && status.workspaceId);
}

export function QuantRuntimeSettings({ snapshot, nativeRuntime = isNativeRuntime() }: { snapshot: QuantWorkspaceSnapshot; nativeRuntime?: boolean }) {
  const native = nativeRuntime;
  const [status, setStatus] = useState<LocalRuntimeStatus | null>(null);
  const [provider, setProvider] = useState<LocalRuntimeProvider>('deepseek');
  const [model, setModel] = useState(DEFAULT_LOCAL_RUNTIME_MODEL);
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRun = !terminalRunStates.has(snapshot.run.state);
  const connection = useMemo(() => connectionDraft(), []);

  const refreshStatus = async () => {
    if (!native) return;
    try {
      setStatus(await getLocalRuntimeStatus());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to read the local runtime status.');
    }
  };

  useEffect(() => { void refreshStatus(); }, [native]);

  const start = async (restart = false) => {
    setBusy(true);
    setError(null);
    try {
      if (restart) await stopLocalRuntime();
      const next = await startLocalRuntime({ provider, model: provider === 'deepseek' ? model.trim() : null, ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}) });
      setStatus(next);
      setApiKey('');
      if (!hasConnection(next)) throw new Error(next.message || 'The local runtime started without a workspace connection.');
      storeConnectionProfile({ apiUrl: next.apiUrl, workspaceId: next.workspaceId });
      window.location.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to start the local runtime.');
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await stopLocalRuntime());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to stop the local runtime.');
    } finally {
      setBusy(false);
    }
  };

  return <div className="quant-settings-page">
    <div className="quant-settings-content"><header><h1>Runtime and policy</h1><p>Review the connection and the model boundary retained with this research run.</p></header>
      <section><header><strong>Current connection</strong><small>This Mac’s selected research workspace</small></header><dl><div><dt>API URL</dt><dd>{connection.apiUrl || 'Not configured'}</dd></div><div><dt>Workspace</dt><dd>{connection.workspaceId || 'Not configured'}</dd></div></dl></section>
      <section><header><strong>Current run</strong><small>Frozen when this run was created</small></header><dl><div><dt>Provider</dt><dd>{snapshot.run.provider}</dd></div><div><dt>Model</dt><dd>{snapshot.run.model || snapshot.modelLabel}</dd></div><div><dt>Runtime status</dt><dd className="is-positive">{snapshot.runtimeLabel}</dd></div></dl></section>
      {native && <section><header><strong>Managed local runtime</strong><small>Source-checkout runtime; requires this repository and its .venv.</small></header><dl><div><dt>Status</dt><dd className={status?.state === 'running' ? 'is-positive' : status?.state === 'failed' ? 'is-warning' : ''}>{statusLabel(status)}</dd></div>{status?.state === 'running' && <><div><dt>Provider</dt><dd>{providerLabel(status.provider)}</dd></div><div><dt>Model</dt><dd>{status.model || '—'}</dd></div></>}</dl><div className="quant-runtime-control"><div className="quant-runtime-form"><label>Provider<select value={provider} disabled={busy || activeRun} onChange={(event) => setProvider(event.target.value as LocalRuntimeProvider)}><option value="deepseek">DeepSeek</option><option value="mock">Offline deterministic</option></select></label>{provider === 'deepseek' && <><label>Model<input value={model} disabled={busy || activeRun} onChange={(event) => setModel(event.target.value)} /></label><label>API key <small>Optional; leave blank to reuse Keychain.</small><input type="password" autoComplete="off" value={apiKey} disabled={busy || activeRun} onChange={(event) => setApiKey(event.target.value)} /></label></>}</div>{activeRun && <p className="quant-runtime-note">Finish, cancel, or open a terminal run before changing the local runtime.</p>}{error && <p className="quant-runtime-error" role="alert">{error}</p>}<div className="quant-runtime-actions">{status?.state === 'running' ? <><Button disabled={busy} onClick={() => void stop()}>Stop runtime</Button><Button className="primary" disabled={busy || activeRun} onClick={() => void start(true)}>Restart runtime</Button></> : <Button className="primary" disabled={busy || activeRun || (provider === 'deepseek' && !model.trim())} onClick={() => void start()}>Start local runtime</Button>}<Button disabled={busy} onClick={() => void refreshStatus()}>Refresh status</Button></div></div></section>}
      <section><header><strong>Research policy</strong><small>Pinned into every immutable run</small></header><dl><div><dt>Experiment budget</dt><dd>{snapshot.limits.maxExperiments} experiments</dd></div><div><dt>Repair budget</dt><dd>{snapshot.limits.maxRepairAttempts} repairs</dd></div><div><dt>Validation<small>Required before promotion</small></dt><dd className="is-warning">Sealed holdout</dd></div><div><dt>Execution<small>Arbitrary Python and broker actions</small></dt><dd>Disabled</dd></div></dl></section>
      <p className="quant-settings-note">Changing a managed runtime reconnects this Mac. Existing runs keep their recorded provider and model.</p>
    </div>
  </div>;
}
