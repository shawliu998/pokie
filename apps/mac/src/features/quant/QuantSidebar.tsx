import { useMemo, useState } from 'react';
import type { QuantNavDestination, QuantWorkspaceSnapshot } from '../../quant-domain';

const destinations = [
  { id: 'projects', label: 'Workspace' },
  { id: 'new_research', label: 'New research' },
  { id: 'runs', label: 'Runs' },
  { id: 'data', label: 'Data' },
  { id: 'settings', label: 'Runtime & policy' },
] satisfies Array<{ id: QuantNavDestination; label: string }>;

const runStateLabels: Record<QuantWorkspaceSnapshot['run']['state'], string> = {
  draft: 'Draft',
  planning: 'Planning',
  waiting_plan_approval: 'Plan review',
  queued: 'Queued',
  loading_data: 'Verifying dataset',
  generating_candidates: 'Preparing candidates',
  running_experiments: 'Running experiments',
  repairing: 'Repairing candidate',
  validating: 'Validating evidence',
  generating_report: 'Building report',
  waiting_for_review: 'Review required',
  completed: 'Completed',
  failed: 'Failed safely',
  cancelled: 'Cancelled',
  unknown: 'Unknown state',
};

export function QuantSidebar({ snapshot, destination, onSelect, onSelectProject }: {
  snapshot: QuantWorkspaceSnapshot;
  destination: QuantNavDestination;
  onSelect: (destination: QuantNavDestination) => void;
  onSelectProject?: (projectId: string, runId: string) => void;
}) {
  const [query, setQuery] = useState('');
  const visibleProjects = useMemo(() => snapshot.recentProjects.filter((project) => `${project.title} ${project.symbol}`.toLowerCase().includes(query.trim().toLowerCase())), [query, snapshot.recentProjects]);

  return <aside className="quant-sidebar" aria-label="Qurio navigation" data-testid="quant-sidebar">
    <div className="quant-brand"><img className="quant-brand-wordmark" src="/brand/qurio-wordmark-inverse.svg" alt="Qurio" /></div>
    <div className="quant-sidebar-body">
      <p className="quant-sidebar-label">Research workspace</p>
      <label className="quant-sidebar-search"><input aria-label="Search research" placeholder="Search" value={query} onChange={(event) => setQuery(event.target.value)} /><kbd>⌘ K</kbd></label>
      <nav className="quant-main-nav" aria-label="Primary">
        {destinations.map(({ id, label }) => <button className={`${destination === id ? 'active' : ''}${id === 'settings' ? ' quant-sidebar-settings' : ''}`} aria-current={destination === id ? 'page' : undefined} onClick={() => onSelect(id)} key={id}>{label}</button>)}
      </nav>
      <section className="quant-sidebar-list" aria-labelledby="quant-workspaces-heading">
        <p id="quant-workspaces-heading" className="quant-sidebar-label">Workspaces</p>
        {visibleProjects.slice(0, 3).map((project) => <button key={project.id} className={destination === 'runs' && project.id === snapshot.project.id ? 'selected' : undefined} aria-current={destination === 'runs' && project.id === snapshot.project.id ? 'true' : undefined} title={project.title} onClick={() => project.latestRunId && onSelectProject ? onSelectProject(project.id, project.latestRunId) : onSelect('runs')}>{project.title.split(' · ')[0] || `${project.symbol} Research`}</button>)}
        {visibleProjects.length === 0 && <span className="quant-sidebar-empty">{query.trim() ? 'No matching projects' : 'No saved projects'}</span>}
      </section>
      <section className="quant-sidebar-list quant-sidebar-recent" aria-labelledby="quant-recent-heading">
        <p id="quant-recent-heading" className="quant-sidebar-label">Recent</p>
        <button title={`${snapshot.modelLabel} run · ${runStateLabels[snapshot.run.state]}`} onClick={() => onSelect('runs')}>{snapshot.modelLabel} run · {runStateLabels[snapshot.run.state]}{snapshot.report?.generalization?.status === 'fail' ? ' · holdout failed' : ''}</button>
      </section>
    </div>
    <footer className="quant-sidebar-footer"><span>Provider · {snapshot.run.provider}</span><small>{snapshot.runtimeLabel}</small></footer>
  </aside>;
}
