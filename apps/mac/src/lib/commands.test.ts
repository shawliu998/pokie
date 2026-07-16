import { describe, expect, it, vi } from 'vitest';
import type { WorkspaceState } from '../domain';
import { adjacentItemId, buildGlobalSearchResults, buildWorkbenchCommands, destinationItemIds, isEditableKeyboardTarget, workbenchKeyboardIntent } from './commands';

const actions = {
  goTo: vi.fn(), openSelected: vi.fn(), startInvestigation: vi.fn(), openSourceViewer: vi.fn(), dismissSignal: vi.fn(), exportBrief: vi.fn(), reloadWorkspace: vi.fn(), showDataStatus: vi.fn(), toggleSidebar: vi.fn(), showKeyboardShortcuts: vi.fn(),
};

describe('workbench command policies', () => {
  it('registers only commands that can execute in the current context', () => {
    const commands = buildWorkbenchCommands({ canOpenSelected: true, canStartInvestigation: false, canOpenSourceViewer: false, canDismissSignal: false, canExportBrief: true, canToggleSidebar: false }, actions);
    expect(commands.map((command) => command.id)).toEqual(['go-inbox', 'go-investigations', 'go-decisions', 'go-monitoring', 'open-selected', 'export-brief', 'reload-workspace', 'show-data-status', 'show-keyboard-shortcuts']);
    commands.find((command) => command.id === 'go-decisions')?.run();
    expect(actions.goTo).toHaveBeenCalledWith('decisions');
  });

  it('maps exact Mac shortcuts and rejects modified navigation or VoiceOver chords', () => {
    const event = (key: string, overrides: Partial<Parameters<typeof workbenchKeyboardIntent>[0]> = {}) => ({ key, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false, isComposing: false, ...overrides });
    expect(workbenchKeyboardIntent(event('k', { metaKey: true }))).toBe('command-palette');
    expect(workbenchKeyboardIntent(event('p', { metaKey: true }))).toBe('global-search');
    expect(workbenchKeyboardIntent(event('j'))).toBe('next');
    expect(workbenchKeyboardIntent(event('ArrowUp'))).toBe('previous');
    expect(workbenchKeyboardIntent(event('i'))).toBe('dismiss');
    expect(workbenchKeyboardIntent(event('e', { ctrlKey: true, altKey: true }))).toBeNull();
    expect(workbenchKeyboardIntent(event('r', { metaKey: true }))).toBeNull();
    expect(workbenchKeyboardIntent(event('j', { repeat: true }))).toBeNull();
    expect(workbenchKeyboardIntent(event('j', { isComposing: true }))).toBeNull();
  });

  it('keeps selection bounded and protects every editable target shape', () => {
    expect(adjacentItemId(['a', 'b', 'c'], 'b', 1)).toBe('c');
    expect(adjacentItemId(['a', 'b', 'c'], 'c', 1)).toBe('c');
    expect(adjacentItemId(['a', 'b', 'c'], '', -1)).toBe('c');
    const input = document.createElement('input');
    const editor = document.createElement('div');
    editor.setAttribute('contenteditable', 'true');
    const customTextbox = document.createElement('div');
    customTextbox.setAttribute('role', 'textbox');
    expect(isEditableKeyboardTarget(input)).toBe(true);
    expect(isEditableKeyboardTarget(editor)).toBe(true);
    expect(isEditableKeyboardTarget(customTextbox)).toBe(true);
    expect(isEditableKeyboardTarget(document.createElement('button'))).toBe(false);
  });

  it('builds shallow global search records without conflating the list filter', () => {
    const workspace = {
      signals: [{ id: 'signal-1', title: 'Permission signal', status: 'new', authenticity: 'collected' }],
      investigations: [{ id: 'investigation-1', question: 'Why permissions?', status: 'active', authenticity: 'generated' }],
      briefs: [{ id: 'brief-1', question: 'What should we ship?', status: 'draft', authenticity: 'human_authored' }],
      sources: [{ id: 'source-1', name: 'Customer feedback', connectorType: 'csv', status: 'healthy' }],
    } as unknown as WorkspaceState;
    expect(buildGlobalSearchResults(workspace).map(({ id, destination, kind, title }) => ({ id, destination, kind, title }))).toEqual([
      { id: 'signal-1', destination: 'inbox', kind: 'Signal', title: 'Permission signal' },
      { id: 'investigation-1', destination: 'investigations', kind: 'Investigation', title: 'Why permissions?' },
      { id: 'brief-1', destination: 'decisions', kind: 'Decision Brief', title: 'What should we ship?' },
      { id: 'source-1', destination: 'monitoring', kind: 'Source', title: 'Customer feedback' },
    ]);
    expect(destinationItemIds(workspace, 'inbox', 'permission')).toEqual(['signal-1']);
    expect(destinationItemIds(workspace, 'inbox', 'not visible')).toEqual([]);
  });
});
