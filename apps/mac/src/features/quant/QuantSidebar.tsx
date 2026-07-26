import type { QuantNavDestination, QuantWorkspaceSnapshot } from '../../quant-domain';
import { presentQuantWorkspace } from './quant-presentation';

const researchDestinations = [
  { id: 'projects', label: 'Workspace' },
  { id: 'new_research', label: 'New research' },
  { id: 'runs', label: 'History' },
  { id: 'data', label: 'Data' },
] satisfies Array<{ id: QuantNavDestination; label: string }>;

export function QuantSidebar({ snapshot, destination, onSelect, onSelectProject, guidedDemo }: {
  snapshot: QuantWorkspaceSnapshot;
  destination: QuantNavDestination;
  onSelect: (destination: QuantNavDestination) => void;
  onSelectProject?: (projectId: string, runId: string) => void;
  guidedDemo?: {
    label: string;
    busy: boolean;
    onOpen: () => void;
  };
}) {
  const lifecycle = presentQuantWorkspace(snapshot);
  const recentProjects = snapshot.recentProjects
    .filter((project) => project.id !== snapshot.project.id)
    .slice(0, 3);

  return <aside className="quant-sidebar" aria-label="Qurio navigation" data-testid="quant-sidebar">
    <div className="quant-brand"><img className="quant-brand-wordmark" src="/brand/qurio-wordmark-inverse.svg" alt="Qurio" /></div>
    <div className="quant-sidebar-body">
      <nav className="quant-main-nav" aria-label="Research">
        {researchDestinations.map(({ id, label }) => <button className={destination === id ? 'active' : ''} aria-current={destination === id ? 'page' : undefined} onClick={() => onSelect(id)} key={id}>{label}</button>)}
      </nav>
      {guidedDemo && <section className="quant-sidebar-guided" aria-labelledby="quant-guided-demo-heading">
        <p id="quant-guided-demo-heading" className="quant-sidebar-label">Guided demo</p>
        <button type="button" disabled={guidedDemo.busy} onClick={guidedDemo.onOpen}>
          <strong>{guidedDemo.busy ? 'Opening research…' : 'Open guided demo'}</strong>
          <span>{guidedDemo.label}</span>
        </button>
      </section>}
      <section className="quant-sidebar-current" aria-labelledby="quant-current-research-heading">
        <p id="quant-current-research-heading" className="quant-sidebar-label">Current research</p>
        <div className="quant-sidebar-current-research" title={snapshot.project.goal}>
          <strong>{snapshot.project.title}</strong>
          <span>{snapshot.scope.market} · {snapshot.scope.interval}</span>
          <small>{lifecycle.statusLabel}</small>
        </div>
      </section>
      {recentProjects.length > 0 && <section className="quant-sidebar-list quant-sidebar-recent" aria-labelledby="quant-recent-heading">
        <p id="quant-recent-heading" className="quant-sidebar-label">Recent research</p>
        {recentProjects.map((project) => <button key={project.id} className="quant-sidebar-project" title={project.goal} onClick={() => project.latestRunId && onSelectProject ? onSelectProject(project.id, project.latestRunId) : onSelect('runs')}>
          <strong>{project.title}</strong>
          <span>{project.symbol}</span>
        </button>)}
      </section>}
      <nav className="quant-main-nav quant-sidebar-secondary-nav" aria-label="Simulation">
        <button className={destination === 'paper' ? 'active' : ''} aria-current={destination === 'paper' ? 'page' : undefined} onClick={() => onSelect('paper')}>Paper Trading</button>
      </nav>
    </div>
    <nav className="quant-sidebar-footer" aria-label="Product settings">
      <button className={`quant-sidebar-settings${destination === 'settings' ? ' active' : ''}`} aria-current={destination === 'settings' ? 'page' : undefined} onClick={() => onSelect('settings')}>Settings</button>
    </nav>
  </aside>;
}
