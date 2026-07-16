import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';
import { projectRunEvent, type GlintApi } from '../api';
import type { Investigation, WorkspaceState } from '../domain';
import { emptyRunCursor, parseRunCursor, reconcileRunCursor } from '../lib/run-cursor';

export type RunConnection = 'connected' | 'reconnecting' | 'reset';

interface UseRunStreamOptions {
  api: GlintApi;
  offline: boolean;
  investigation?: Investigation;
  setWorkspace: Dispatch<SetStateAction<WorkspaceState | null>>;
}

const terminalStates = ['completed', 'failed', 'cancelled'];

export function useRunStream({ api, offline, investigation, setWorkspace }: UseRunStreamOptions): RunConnection {
  const [connection, setConnection] = useState<RunConnection>('connected');

  useEffect(() => {
    const run = investigation?.run;
    if (offline || !investigation || !run || (terminalStates.includes(run.state) && investigation.events.length > 0)) return;
    const controller = new AbortController();
    const storageKey = `glint:run-cursor:${run.id}`;
    const terminalReplay = terminalStates.includes(run.state) && investigation.events.length === 0;
    let cursor = terminalReplay ? emptyRunCursor() : parseRunCursor(localStorage.getItem(storageKey));
    let delay = 500;
    let recovery: Promise<void> | null = null;
    let resetRequested = false;

    const refresh = async (preserveEvents = true) => {
      const refreshed = await api.refreshInvestigation(investigation.id);
      setWorkspace((current) => current ? {
        ...current,
        investigations: current.investigations.map((item) => item.id === refreshed.id ? { ...refreshed, events: preserveEvents ? item.events : [] } : item),
      } : current);
    };

    const resetCursor = async () => {
      await api.runSnapshot(run.id);
      cursor = emptyRunCursor();
      localStorage.removeItem(storageKey);
      await refresh(false);
    };

    const connect = async (): Promise<void> => {
      setConnection('connected');
      try {
        await api.subscribeRun(run.id, cursor.eventId || undefined, controller.signal, (event) => {
          const decision = reconcileRunCursor(cursor, event);
          if (decision.kind === 'duplicate') return;
          if (decision.kind === 'gap') {
            setConnection('reset');
            recovery = resetCursor();
            throw new Error('Run event sequence gap; snapshot reset required.');
          }
          setWorkspace((current) => current ? {
            ...current,
            investigations: current.investigations.map((item) => item.id === investigation.id ? projectRunEvent(item, event) : item),
          } : current);
          if (/^(evidence|claim|synthesis)\.|^review\./.test(event.eventType) || event.eventType === 'run.completed') void refresh();
          cursor = decision.cursor;
          localStorage.setItem(storageKey, JSON.stringify(cursor));
        }, async (reset) => {
          resetRequested = true;
          setConnection('reset');
          await resetCursor();
          void reset.latestSequence;
        });
        const snapshot = await api.runSnapshot(run.id);
        if (!controller.signal.aborted && (resetRequested || !terminalStates.includes(snapshot.state))) {
          resetRequested = false;
          throw new Error('SSE stream requires replay or closed before the run reached a terminal state.');
        }
      } catch {
        if (!controller.signal.aborted) {
          if (recovery) { await recovery; recovery = null; }
          setConnection('reconnecting');
          await new Promise((resolve) => window.setTimeout(resolve, delay));
          delay = Math.min(delay * 2, 8000);
          if (!controller.signal.aborted) await connect();
        }
      }
    };

    void connect();
    return () => controller.abort();
  }, [api, investigation?.id, investigation?.run?.id, offline, setWorkspace]);

  return connection;
}
