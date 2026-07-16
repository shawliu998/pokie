import { useEffect } from 'react';
import { isEditableKeyboardTarget, workbenchKeyboardIntent } from '../lib/commands';

interface WorkbenchKeyboardActions {
  overlayOpen: boolean;
  openCommandPalette: () => void;
  openGlobalSearch: () => void;
  closeOverlay: () => void;
  escape: () => boolean;
  moveSelection: (direction: 1 | -1) => boolean;
  openSelected: () => boolean;
  startInvestigation: () => boolean;
  openSourceViewer: () => boolean;
  dismissSignal: () => boolean;
}

export function useWorkbenchKeyboard(actions: WorkbenchKeyboardActions): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const intent = workbenchKeyboardIntent(event);
      if (!intent) return;
      if (intent === 'escape') {
        const handled = actions.overlayOpen ? (actions.closeOverlay(), true) : actions.escape();
        if (handled) event.preventDefault();
        return;
      }
      if (actions.overlayOpen) return;
      if (intent === 'command-palette' || intent === 'global-search') {
        event.preventDefault();
        if (intent === 'command-palette') actions.openCommandPalette();
        else actions.openGlobalSearch();
        return;
      }
      if (isEditableKeyboardTarget(event.target)) return;
      const handled = intent === 'next' ? actions.moveSelection(1)
        : intent === 'previous' ? actions.moveSelection(-1)
          : intent === 'open' ? actions.openSelected()
            : intent === 'start-investigation' ? actions.startInvestigation()
              : intent === 'open-source-viewer' ? actions.openSourceViewer()
                : intent === 'dismiss' ? actions.dismissSignal()
                  : false;
      if (handled) event.preventDefault();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [actions]);
}
