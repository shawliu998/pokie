import { Command } from 'cmdk';
import type { WorkbenchCommand } from '../../lib/commands';

export function CommandPalette({ commands, onClose }: { commands: WorkbenchCommand[]; onClose: () => void }) {
  const groups: WorkbenchCommand['group'][] = ['Navigate', 'Current item', 'Workspace'];
  return <Command.Dialog open onOpenChange={(open) => { if (!open) onClose(); }} label="Command Palette" loop vimBindings={false} overlayClassName="command-overlay" contentClassName="command-dialog">
    <Command.Input autoFocus aria-label="Search commands" placeholder="Type a command…" />
    <Command.List label="Available commands">
      <Command.Empty>No executable command matches.</Command.Empty>
      {groups.map((group) => <Command.Group heading={group} key={group}>{commands.filter((command) => command.group === group).map((command) => <Command.Item
        key={command.id}
        value={`${command.label} ${command.id}`}
        keywords={command.keywords}
        onSelect={() => { onClose(); command.run(); }}
      ><span>{command.label}</span>{command.shortcut && <kbd>{command.shortcut}</kbd>}</Command.Item>)}</Command.Group>)}
    </Command.List>
    <div className="command-footer"><span>↑↓ Navigate</span><span>↵ Run</span><span>esc Close</span></div>
  </Command.Dialog>;
}
