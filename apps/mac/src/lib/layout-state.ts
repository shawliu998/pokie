import type { Layout } from 'react-resizable-panels';

export const WORKBENCH_LAYOUT_STORAGE_KEY = 'glint:workbench-layout:v1';
export const WORKBENCH_LAYOUT_IDS = ['sidebar', 'list', 'detail'] as const;

interface StoredWorkbenchLayout {
  version: 1;
  layout: Layout;
}

export function isWorkbenchLayout(value: unknown): value is Layout {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  return WORKBENCH_LAYOUT_IDS.every((id) => typeof candidate[id] === 'number' && Number.isFinite(candidate[id]) && candidate[id] >= 0 && candidate[id] <= 100)
    && Math.abs(WORKBENCH_LAYOUT_IDS.reduce((total, id) => total + (candidate[id] as number), 0) - 100) < 0.5;
}

export function loadWorkbenchLayout(storage: Pick<Storage, 'getItem'> = localStorage): Layout | undefined {
  try {
    const raw = storage.getItem(WORKBENCH_LAYOUT_STORAGE_KEY);
    if (!raw) return undefined;
    const stored = JSON.parse(raw) as Partial<StoredWorkbenchLayout>;
    return stored.version === 1 && isWorkbenchLayout(stored.layout) ? stored.layout : undefined;
  } catch {
    return undefined;
  }
}

export function saveWorkbenchLayout(layout: Layout, storage: Pick<Storage, 'setItem'> = localStorage): void {
  if (!isWorkbenchLayout(layout)) return;
  try {
    storage.setItem(WORKBENCH_LAYOUT_STORAGE_KEY, JSON.stringify({ version: 1, layout } satisfies StoredWorkbenchLayout));
  } catch {
    // Layout persistence is a convenience and must never prevent the workspace from rendering.
  }
}

export function isCompactWorkbenchWidth(width: number): boolean {
  return width < 1000;
}
