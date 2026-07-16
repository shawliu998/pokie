import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from 'react';
import type { GlintApi } from '../../api';
import type { WorkspaceState } from '../../domain';
import { loadWorkspaceCache, storeWorkspaceCache } from '../../cache';
import { SessionExpiredError } from '../../session';
import { displayTime } from '../../lib/formatting';

export interface WorkspaceController {
  workspace: WorkspaceState | null;
  setWorkspace: Dispatch<SetStateAction<WorkspaceState | null>>;
  selectedId: string;
  setSelectedId: Dispatch<SetStateAction<string>>;
  loading: boolean;
  error: string | null;
  setError: Dispatch<SetStateAction<string | null>>;
  offline: boolean;
  reload: () => Promise<void>;
}

export function useWorkspace(api: GlintApi): WorkspaceController {
  const [workspace, setWorkspace] = useState<WorkspaceState | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(!navigator.onLine);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const next = await api.bootstrap();
      let cachedAt: string | null = null;
      try { cachedAt = await storeWorkspaceCache(next); }
      catch (reason) { setError(reason instanceof Error ? `Live workspace loaded, but the protected offline cache was not updated: ${reason.message}` : 'Live workspace loaded, but the protected offline cache was not updated.'); }
      setWorkspace({ ...next, cachedAt });
      setOffline(false);
      setSelectedId((current) => current || next.signals[0]?.id || next.investigations[0]?.id || next.briefs[0]?.id || '');
    } catch (reason) {
      if (reason instanceof SessionExpiredError) { setError(reason.message); return; }
      const cached = await loadWorkspaceCache(api.workspaceId).catch(() => null);
      if (cached) {
        setWorkspace(cached);
        setOffline(true);
        setSelectedId((current) => current || cached.signals[0]?.id || cached.investigations[0]?.id || cached.briefs[0]?.id || '');
        setError(`Live API unavailable. Protected read-only cache loaded from ${displayTime(cached.cachedAt)}.`);
      } else setError(reason instanceof Error ? reason.message : 'Unable to load the workspace.');
    } finally { setLoading(false); }
  }, [api]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    const online = () => { void reload(); };
    const offlineEvent = () => setOffline(true);
    window.addEventListener('online', online);
    window.addEventListener('offline', offlineEvent);
    return () => { window.removeEventListener('online', online); window.removeEventListener('offline', offlineEvent); };
  }, [reload]);

  return { workspace, setWorkspace, selectedId, setSelectedId, loading, error, setError, offline, reload };
}
