import { describe, expect, it, vi } from 'vitest';
import { isCompactWorkbenchWidth, isWorkbenchLayout, loadWorkbenchLayout, saveWorkbenchLayout, WORKBENCH_LAYOUT_STORAGE_KEY } from './layout-state';

describe('workbench layout persistence', () => {
  it('accepts only complete percentage layouts', () => {
    expect(isWorkbenchLayout({ sidebar: 20, list: 30, detail: 50 })).toBe(true);
    expect(isWorkbenchLayout({ sidebar: 20, list: 30 })).toBe(false);
    expect(isWorkbenchLayout({ sidebar: -1, list: 31, detail: 70 })).toBe(false);
    expect(isWorkbenchLayout({ sidebar: 20, list: 30, detail: 40 })).toBe(false);
  });

  it('round trips a versioned layout and ignores corrupt storage', () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
    };
    const layout = { sidebar: 19, list: 32, detail: 49 };
    saveWorkbenchLayout(layout, storage);
    expect(loadWorkbenchLayout(storage)).toEqual(layout);
    values.set(WORKBENCH_LAYOUT_STORAGE_KEY, '{broken');
    expect(loadWorkbenchLayout(storage)).toBeUndefined();
  });

  it('does not make storage availability a rendering requirement', () => {
    const storage = { getItem: vi.fn(() => { throw new Error('denied'); }), setItem: vi.fn(() => { throw new Error('denied'); }) };
    expect(loadWorkbenchLayout(storage)).toBeUndefined();
    expect(() => saveWorkbenchLayout({ sidebar: 20, list: 30, detail: 50 }, storage)).not.toThrow();
  });

  it('uses an explicit compact breakpoint', () => {
    expect(isCompactWorkbenchWidth(999)).toBe(true);
    expect(isCompactWorkbenchWidth(1000)).toBe(false);
  });
});
