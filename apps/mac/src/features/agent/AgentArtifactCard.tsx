import { Badge, Button, Status } from '@glint/ui';
import { authenticityLabel } from '../../domain';
import type { AgentActionKind, AgentArtifactPresentation } from './agent-presentation';

const actionLabel: Partial<Record<AgentActionKind, string>> = {
  'review-evidence': 'Review evidence',
  'review-findings': 'Review findings',
  'review-synthesis': 'Review synthesis',
  'create-brief': 'Create Decision Brief',
  'open-brief': 'Open Decision Brief',
};

export function AgentArtifactCard({ artifact, disabled, onAction }: { artifact: AgentArtifactPresentation; disabled: boolean; onAction: (kind: AgentActionKind) => void }) {
  const reviewState = /review|Needs/.test(artifact.statusLabel);
  return <article className={`agent-artifact-card artifact-${artifact.type}`}>
    <div className="agent-artifact-heading"><div><p className="agent-eyebrow">{artifact.typeLabel}</p><h4>{artifact.title}</h4></div><Status tone={artifact.statusLabel === 'Verified' || artifact.statusLabel.includes('Verified') || artifact.statusLabel.includes('Human-reviewed') ? 'positive' : reviewState ? 'warning' : 'neutral'}>{artifact.statusLabel}</Status></div>
    <p>{artifact.body}</p>
    <div className="agent-artifact-meta"><Badge tone="neutral">{artifact.originLabel}</Badge><Badge tone="info">{authenticityLabel(artifact.authenticity)}</Badge>{artifact.relationshipLabel && <span>{artifact.relationshipLabel}</span>}</div>
    {artifact.primaryAction && actionLabel[artifact.primaryAction] && <Button disabled={disabled} onClick={() => onAction(artifact.primaryAction!)}>{actionLabel[artifact.primaryAction]}</Button>}
  </article>;
}
