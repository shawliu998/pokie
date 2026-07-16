import type { Destination, WorkspaceState } from '../domain';

export type WorkbenchCommandId =
  | `go-${Destination}`
  | 'open-selected'
  | 'start-investigation'
  | 'open-source-viewer'
  | 'dismiss-signal'
  | 'export-brief'
  | 'reload-workspace'
  | 'show-data-status'
  | 'toggle-sidebar'
  | 'show-keyboard-shortcuts';

export interface WorkbenchCommand {
  id: WorkbenchCommandId;
  label: string;
  group: 'Navigate' | 'Current item' | 'Workspace';
  keywords?: string[];
  shortcut?: string;
  run: () => void;
}

export interface WorkbenchCommandAvailability {
  canOpenSelected: boolean;
  canStartInvestigation: boolean;
  canOpenSourceViewer: boolean;
  canDismissSignal: boolean;
  canExportBrief: boolean;
  canToggleSidebar: boolean;
}

export interface WorkbenchCommandActions {
  goTo: (destination: Destination) => void;
  openSelected: () => void;
  startInvestigation: () => void;
  openSourceViewer: () => void;
  dismissSignal: () => void;
  exportBrief: () => void;
  reloadWorkspace: () => void;
  showDataStatus: () => void;
  toggleSidebar: () => void;
  showKeyboardShortcuts: () => void;
}

export function buildWorkbenchCommands(availability: WorkbenchCommandAvailability, actions: WorkbenchCommandActions): WorkbenchCommand[] {
  const commands: WorkbenchCommand[] = [
    { id: 'go-inbox', label: 'Go to Inbox', group: 'Navigate', keywords: ['signals'], run: () => actions.goTo('inbox') },
    { id: 'go-investigations', label: 'Go to Investigations', group: 'Navigate', keywords: ['research'], run: () => actions.goTo('investigations') },
    { id: 'go-decisions', label: 'Go to Decisions', group: 'Navigate', keywords: ['briefs'], run: () => actions.goTo('decisions') },
    { id: 'go-monitoring', label: 'Go to Monitoring', group: 'Navigate', keywords: ['sources'], run: () => actions.goTo('monitoring') },
  ];
  if (availability.canOpenSelected) commands.push({ id: 'open-selected', label: 'Open selected item', group: 'Current item', shortcut: '↵', run: actions.openSelected });
  if (availability.canStartInvestigation) commands.push({ id: 'start-investigation', label: 'Start Investigation', group: 'Current item', shortcut: 'R', run: actions.startInvestigation });
  if (availability.canOpenSourceViewer) commands.push({ id: 'open-source-viewer', label: 'Open Source Viewer', group: 'Current item', keywords: ['evidence'], shortcut: 'E', run: actions.openSourceViewer });
  if (availability.canDismissSignal) commands.push({ id: 'dismiss-signal', label: 'Dismiss selected Signal', group: 'Current item', shortcut: 'I', run: actions.dismissSignal });
  if (availability.canExportBrief) commands.push({ id: 'export-brief', label: 'Export current Decision Brief', group: 'Current item', run: actions.exportBrief });
  commands.push(
    { id: 'reload-workspace', label: 'Reload Workspace', group: 'Workspace', run: actions.reloadWorkspace },
    { id: 'show-data-status', label: 'Show Data Status', group: 'Workspace', run: actions.showDataStatus },
  );
  if (availability.canToggleSidebar) commands.push({ id: 'toggle-sidebar', label: 'Toggle Sidebar', group: 'Workspace', run: actions.toggleSidebar });
  commands.push({ id: 'show-keyboard-shortcuts', label: 'Show Keyboard Shortcuts', group: 'Workspace', run: actions.showKeyboardShortcuts });
  return commands;
}

export type GlobalSearchResultKind = 'Signal' | 'Investigation' | 'Decision Brief' | 'Source';

export interface GlobalSearchResult {
  id: string;
  destination: Destination;
  kind: GlobalSearchResultKind;
  title: string;
  keywords: string[];
}

export function buildGlobalSearchResults(workspace: WorkspaceState): GlobalSearchResult[] {
  return [
    ...workspace.signals.map((signal) => ({ id: signal.id, destination: 'inbox' as const, kind: 'Signal' as const, title: signal.title, keywords: [signal.status, signal.authenticity] })),
    ...workspace.investigations.map((investigation) => ({ id: investigation.id, destination: 'investigations' as const, kind: 'Investigation' as const, title: investigation.question, keywords: [investigation.status, investigation.authenticity] })),
    ...workspace.briefs.map((brief) => ({ id: brief.id, destination: 'decisions' as const, kind: 'Decision Brief' as const, title: brief.question, keywords: [brief.status, brief.authenticity] })),
    ...workspace.sources.map((source) => ({ id: source.id, destination: 'monitoring' as const, kind: 'Source' as const, title: source.name, keywords: [source.connectorType, source.status] })),
  ];
}

export function destinationItemIds(workspace: WorkspaceState, destination: Destination, filter = ''): string[] {
  const query = filter.trim().toLowerCase();
  if (destination === 'inbox') return workspace.signals.filter((item) => item.title.toLowerCase().includes(query)).map((item) => item.id);
  if (destination === 'investigations') return workspace.investigations.filter((item) => item.question.toLowerCase().includes(query)).map((item) => item.id);
  if (destination === 'decisions') return workspace.briefs.filter((item) => item.question.toLowerCase().includes(query)).map((item) => item.id);
  return [];
}

export function adjacentItemId(ids: string[], selectedId: string, direction: 1 | -1): string | undefined {
  if (ids.length === 0) return undefined;
  const current = ids.indexOf(selectedId);
  if (current < 0) return direction === 1 ? ids[0] : ids.at(-1);
  return ids[Math.max(0, Math.min(ids.length - 1, current + direction))];
}

export type WorkbenchKeyboardIntent = 'command-palette' | 'global-search' | 'next' | 'previous' | 'open' | 'start-investigation' | 'open-source-viewer' | 'dismiss' | 'escape';

export interface KeyboardIntentEvent {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  repeat: boolean;
  isComposing: boolean;
}

export function workbenchKeyboardIntent(event: KeyboardIntentEvent): WorkbenchKeyboardIntent | null {
  if (event.repeat || event.isComposing) return null;
  const key = event.key.toLowerCase();
  if (event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey) {
    if (key === 'k') return 'command-palette';
    if (key === 'p') return 'global-search';
    return null;
  }
  if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return null;
  if (event.key === 'Escape') return 'escape';
  if (key === 'j' || event.key === 'ArrowDown') return 'next';
  if (key === 'k' || event.key === 'ArrowUp') return 'previous';
  if (event.key === 'Enter') return 'open';
  if (key === 'r') return 'start-investigation';
  if (key === 'e') return 'open-source-viewer';
  if (key === 'i') return 'dismiss';
  return null;
}

export function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="searchbox"]'));
}
