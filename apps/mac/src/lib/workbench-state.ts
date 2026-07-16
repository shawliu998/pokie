export type CompactPane = 'list' | 'detail';

export interface CompactWorkbenchState {
  pane: CompactPane;
  selectedId: string;
}

export type CompactWorkbenchAction =
  | { type: 'select'; id: string }
  | { type: 'show-list' }
  | { type: 'clear-selection' };

export function compactWorkbenchReducer(state: CompactWorkbenchState, action: CompactWorkbenchAction): CompactWorkbenchState {
  if (action.type === 'select') return { pane: 'detail', selectedId: action.id };
  if (action.type === 'show-list') return { ...state, pane: 'list' };
  return { pane: 'list', selectedId: '' };
}

export interface KeyboardCommandContext {
  defaultPrevented: boolean;
  tagName?: string;
  contentEditable?: boolean;
}

export function canHandleKeyboardCommand(context: KeyboardCommandContext, allowInEditable = false): boolean {
  if (context.defaultPrevented) return false;
  if (allowInEditable) return true;
  const tagName = context.tagName?.toLowerCase();
  return !context.contentEditable && tagName !== 'input' && tagName !== 'textarea' && tagName !== 'select';
}

export function canExecuteWrite(connectivity: { offline: boolean }): boolean {
  return !connectivity.offline;
}

export type SessionRecoveryMode = 'native-keychain' | 'browser-retry';

export function sessionRecoveryMode(native: boolean): SessionRecoveryMode {
  return native ? 'native-keychain' : 'browser-retry';
}
