import { Badge } from '@glint/ui';
import type { QuantNavDestination, QuantWorkspaceSnapshot } from '../../quant-domain';
import { quantAuthenticityLabel } from '../../quant-domain';

const destinations: Array<[QuantNavDestination, string, string]> = [
  ['new_research', 'New Research', '+'],
  ['projects', 'Projects', 'P'],
  ['runs', 'Runs', 'R'],
  ['data', 'Data', 'D'],
  ['settings', 'Settings', 'S'],
];

export function QuantSidebar({ snapshot, destination, onSelect }: {
  snapshot: QuantWorkspaceSnapshot;
  destination: QuantNavDestination;
  onSelect: (destination: QuantNavDestination) => void;
}) {
  return <aside className="quant-sidebar" aria-label="PokieQuant navigation">
    <div className="quant-brand"><span aria-hidden="true">PQ</span><div><strong>PokieQuant</strong><small>Research workspace</small></div></div>
    <nav className="quant-main-nav" aria-label="Primary">
      {destinations.map(([id, label, icon]) => <button className={destination === id ? 'active' : ''} aria-current={destination === id ? 'page' : undefined} onClick={() => onSelect(id)} key={id}><span aria-hidden="true">{icon}</span>{label}{id === 'new_research' && <kbd>⌘N</kbd>}</button>)}
    </nav>
    <section className="quant-recents" aria-labelledby="quant-recent-heading">
      <div className="quant-section-heading"><span id="quant-recent-heading">Recent projects</span><small>{snapshot.recentProjects.length}</small></div>
      {snapshot.recentProjects.map((project) => <button key={project.id} className={project.id === snapshot.project.id ? 'selected' : ''} onClick={() => onSelect('projects')}>
        <span className="quant-project-symbol">{project.symbol}</span><span><strong>{project.title.replace(`${project.symbol} · `, '')}</strong><small>{project.statusLabel}</small></span>{project.needsAction && <i aria-label="Needs action" title="Needs action" />}
      </button>)}
    </section>
    <dl className="quant-runtime-summary">
      <div><dt>Data mode</dt><dd><Badge tone="warning">{quantAuthenticityLabel(snapshot.authenticity)}</Badge></dd></div>
      <div><dt>Runtime</dt><dd>{snapshot.runtimeLabel}</dd></div>
      <div><dt>Model</dt><dd>{snapshot.modelLabel}</dd></div>
      <div><dt>Version</dt><dd>{snapshot.version}</dd></div>
    </dl>
  </aside>;
}
