import { Command } from 'cmdk';
import type { GlobalSearchResult } from '../../lib/commands';

export function GlobalSearchDialog({ results, onClose, onSelect }: { results: GlobalSearchResult[]; onClose: () => void; onSelect: (result: GlobalSearchResult) => void }) {
  const kinds: GlobalSearchResult['kind'][] = ['Signal', 'Investigation', 'Decision Brief', 'Source'];
  return <Command.Dialog open onOpenChange={(open) => { if (!open) onClose(); }} label="Global Search" loop vimBindings={false} overlayClassName="command-overlay" contentClassName="command-dialog">
    <Command.Input autoFocus aria-label="Search all workspace objects" placeholder="Search Signals, Investigations, Decision Briefs, and Sources…" />
    <Command.List label="Global search results">
      <Command.Empty>No workspace object matches this search.</Command.Empty>
      {kinds.map((kind) => <Command.Group heading={kind} key={kind}>{results.filter((result) => result.kind === kind).map((result) => <Command.Item
        key={`${result.kind}:${result.id}`}
        value={`${result.title} ${result.kind} ${result.id}`}
        keywords={result.keywords}
        onSelect={() => { onClose(); onSelect(result); }}
      ><span>{result.title}</span><small>{result.kind}</small></Command.Item>)}</Command.Group>)}
    </Command.List>
    <div className="command-footer"><span>Global object search</span><span>⌘P</span></div>
  </Command.Dialog>;
}
