import { Badge, Status } from '@glint/ui';
import type { ReactNode } from 'react';
import { authenticityLabel } from '../../domain';
import { displayTime } from '../../lib/formatting';
import type { AgentSessionPresentation } from './agent-presentation';

export function AgentActivityFeed({ presentation, children }: { presentation: AgentSessionPresentation; children?: ReactNode }) {
  return <section className="agent-activity" aria-label="Agent activity">
    <article className={`agent-current-action state-${presentation.status}`}>
      <div className="agent-current-heading"><div><p className="agent-eyebrow">Current action</p><h3>{presentation.currentAction.title}</h3></div><Status tone={presentation.statusTone}>{presentation.statusLabel}</Status></div>
      <p>{presentation.currentAction.purpose}</p>
      <dl className="agent-current-metrics"><div><dt>Approved input</dt><dd>{presentation.currentAction.inputLabel}</dd></div><div><dt>Persisted output</dt><dd>{presentation.currentAction.outputLabel}</dd></div><div><dt>What Glint needs</dt><dd>{presentation.currentAction.userNeedLabel}</dd></div></dl>
    </article>
    {children}
    <div className="agent-panel-heading"><div><p className="agent-eyebrow">Activity</p><h3>What happened</h3></div><span>{presentation.activity.length} recorded</span></div>
    <ol className="agent-activity-list">
      {presentation.activity.map((item) => <li key={item.id}>
        <span className="agent-activity-dot" aria-hidden="true" />
        <div className="agent-activity-copy"><div><strong>{item.title}</strong>{item.timestamp && <time>{displayTime(item.timestamp)}</time>}</div><p>{item.summary}</p><div className="agent-activity-meta"><Badge tone="neutral">{authenticityLabel(item.authenticity)}</Badge>{item.artifactCount > 0 && <span>{item.artifactCount} artifact{item.artifactCount === 1 ? '' : 's'}</span>}</div>{item.eventType && <details><summary>Technical event</summary><dl><dt>Event</dt><dd><code>{item.eventType}</code></dd><dt>Sequence</dt><dd>{item.sequence ?? 'Unavailable'}</dd></dl></details>}</div>
      </li>)}
    </ol>
  </section>;
}
