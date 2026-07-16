import { Button } from '@glint/ui';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';

const shortcuts = [
  ['⌘K', 'Open Command Palette'], ['⌘P', 'Open global object search'], ['J / ↓', 'Select next item'], ['K / ↑', 'Select previous item'], ['↵', 'Open selected item'], ['R', 'Start an Investigation from the selected Signal'], ['E', 'Open the selected item’s Source Viewer'], ['I', 'Dismiss the selected Signal'], ['Esc', 'Close the top overlay or return to the compact list'],
];

export function KeyboardShortcutsDialog({ onClose }: { onClose: () => void }) {
  useEscapeToClose(onClose);
  return <div className="modal-backdrop"><section className="modal shortcuts-dialog" role="dialog" aria-modal="true" aria-label="Keyboard Shortcuts"><h2>Keyboard Shortcuts</h2><p className="hint">Single-key actions pause while focus is in an editor. macOS and VoiceOver modifier chords remain available to the system.</p><dl>{shortcuts.map(([keys, description]) => <div key={keys}><dt><kbd>{keys}</kbd></dt><dd>{description}</dd></div>)}</dl><div className="modal-actions"><Button onClick={onClose}>Close</Button></div></section></div>;
}
