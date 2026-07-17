import { Badge, Button, Status } from '@glint/ui';
import type { QuantArtifact, QuantWorkspaceSnapshot } from '../../quant-domain';
import { quantAuthenticityLabel } from '../../quant-domain';
import type { QuantActionPresentation, QuantActivityPresentation, QuantWorkspacePresentation } from './quant-presentation';

function displayTime(value: string): string {
  return new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}

export function QuantActionCenter({ presentation, onAction }: { presentation: QuantWorkspacePresentation; onAction: (action: QuantActionPresentation) => void }) {
  if (presentation.actions.length === 0) return null;
  return <section className={`quant-action-center tone-${presentation.statusTone}`} aria-labelledby="quant-action-title">
    <div><p className="quant-eyebrow">Action Center</p><h3 id="quant-action-title">{presentation.currentActionTitle}</h3><p>{presentation.currentActionPurpose}</p><small>Lifecycle controls come from the API snapshot; view actions open persisted artifacts.</small></div>
    <div className="quant-action-buttons">{presentation.actions.map((action) => <Button className={action.tone === 'primary' ? 'primary' : ''} key={action.kind} onClick={() => onAction(action)}>{action.label}</Button>)}</div>
  </section>;
}

export function QuantActivityFeed({ snapshot, presentation, onInspect }: {
  snapshot: QuantWorkspaceSnapshot;
  presentation: QuantWorkspacePresentation;
  onInspect: (event: QuantActivityPresentation) => void;
}) {
  return <section className="quant-activity" aria-label="Run activity">
    <article className={`quant-current-action tone-${presentation.statusTone}`}>
      <header><div><p className="quant-eyebrow">Current state</p><h3>{presentation.currentActionTitle}</h3></div><Status tone={presentation.statusTone}>{presentation.statusLabel}</Status></header>
      <p>{presentation.currentActionPurpose}</p>
      <dl><div><dt>Experiments</dt><dd>{snapshot.run.usedExperiments} recorded · max {snapshot.limits.maxExperiments}</dd></div><div><dt>Repairs</dt><dd>{snapshot.run.usedRepairAttempts} recorded · max {snapshot.limits.maxRepairAttempts}</dd></div><div><dt>Runtime limit</dt><dd>{snapshot.limits.maxRuntimeMinutes} minutes configured</dd></div></dl>
    </article>
    <div className="quant-panel-heading"><div><p className="quant-eyebrow">Activity</p><h3>Durable run events</h3></div><span>{presentation.activity.length} shown</span></div>
    <ol className="quant-activity-list">
      {presentation.activity.map((event) => <li key={event.id}><span className="quant-activity-dot" aria-hidden="true" /><div><div className="quant-event-title"><strong>{event.title}</strong><time dateTime={event.timestamp}>{displayTime(event.timestamp)}</time></div><p>{event.summary}</p><footer><Badge tone="neutral">{event.actorLabel}</Badge>{event.artifactId && <span>Artifact retained</span>}<button onClick={() => onInspect(event)} aria-label={`Inspect ${event.title}`}>Inspect</button></footer></div></li>)}
    </ol>
  </section>;
}

export function QuantArtifactCards({ artifacts, onInspect }: { artifacts: QuantArtifact[]; onInspect: (artifact: QuantArtifact) => void }) {
  return <section className="quant-artifacts" aria-labelledby="quant-artifact-title">
    <div className="quant-panel-heading"><div><p className="quant-eyebrow">Artifacts</p><h3 id="quant-artifact-title">Governed output</h3></div><span>{artifacts.length}</span></div>
    <div className="quant-artifact-grid">{artifacts.map((artifact) => <article key={artifact.id} className={`quant-artifact-card type-${artifact.type}`}>
      <header><div><p className="quant-eyebrow">{artifact.type.replaceAll('_', ' ')}</p><h4>{artifact.title}</h4></div><Status tone={artifact.status === 'reviewed' ? 'positive' : artifact.status === 'rejected' ? 'danger' : 'neutral'}>{artifact.status}</Status></header>
      <p>{artifact.summary}</p><div><Badge tone="neutral">{artifact.origin}</Badge><Badge tone="warning">{quantAuthenticityLabel(artifact.authenticity)}</Badge><span>{artifact.relatedLabel}</span></div><Button onClick={() => onInspect(artifact)}>Inspect artifact</Button>
    </article>)}</div>
  </section>;
}
