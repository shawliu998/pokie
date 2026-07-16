import { describe, expect, it } from 'vitest';
import { canExecuteWrite, canHandleKeyboardCommand, compactWorkbenchReducer, sessionRecoveryMode } from './workbench-state';

describe('workbench UI policies', () => {
  it('moves compact navigation between list and detail deterministically', () => {
    const selected = compactWorkbenchReducer({ pane: 'list', selectedId: '' }, { type: 'select', id: 'signal-1' });
    expect(selected).toEqual({ pane: 'detail', selectedId: 'signal-1' });
    expect(compactWorkbenchReducer(selected, { type: 'show-list' })).toEqual({ pane: 'list', selectedId: 'signal-1' });
  });

  it('guards global keyboard commands while the user is editing', () => {
    expect(canHandleKeyboardCommand({ defaultPrevented: false, tagName: 'input' })).toBe(false);
    expect(canHandleKeyboardCommand({ defaultPrevented: false, tagName: 'div', contentEditable: true })).toBe(false);
    expect(canHandleKeyboardCommand({ defaultPrevented: false, tagName: 'button' })).toBe(true);
    expect(canHandleKeyboardCommand({ defaultPrevented: true, tagName: 'button' })).toBe(false);
  });

  it('disables all writes offline and selects the correct session recovery boundary', () => {
    expect(canExecuteWrite({ offline: true })).toBe(false);
    expect(canExecuteWrite({ offline: false })).toBe(true);
    expect(sessionRecoveryMode(true)).toBe('native-keychain');
    expect(sessionRecoveryMode(false)).toBe('browser-retry');
  });
});
