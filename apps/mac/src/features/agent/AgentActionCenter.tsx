import { Button, Status } from '@glint/ui';
import type { AgentActionKind, AgentSessionPresentation } from './agent-presentation';

interface AgentActionCenterProps {
  presentation: AgentSessionPresentation;
  disabled: boolean;
  onAction: (kind: AgentActionKind) => void;
}

export function AgentActionCenter({ presentation, disabled, onAction }: AgentActionCenterProps) {
  const pending = presentation.pendingHumanAction;
  if (!pending && !['ready', 'failed', 'needs-input'].includes(presentation.status)) return null;
  if (presentation.status === 'ready') return <section className="agent-action-center ready" aria-label="Agent action center"><div><p className="agent-eyebrow">Action Center</p><h3>Approved scope is ready</h3><p>Start the bounded Investigation when you are ready.</p><small>Glint will use only the frozen question, sources, content versions, window, and configured limits shown above.</small></div>{presentation.canStart && <Button className="primary" disabled={disabled} onClick={() => onAction('start-run')}>Start investigation</Button>}</section>;
  if (presentation.status === 'failed') return <section className="agent-action-center failure" aria-label="Agent action center"><div><p className="agent-eyebrow">Action Center</p><h3>The Agent stopped safely</h3><p>{presentation.currentAction.purpose}</p><small>Persisted artifacts remain visible. No proposal is relabeled as reviewed.</small></div>{presentation.canRetry && <Button className="primary" disabled={disabled} onClick={() => onAction('retry')}>Retry</Button>}</section>;
  if (presentation.status === 'needs-input') return <section className="agent-action-center" aria-label="Agent action center"><div><p className="agent-eyebrow">Action Center</p><h3>Authorized input is required</h3><p>{presentation.currentAction.purpose}</p><small>This version cannot accept a free-text continuation.</small></div>{presentation.canCancel && <Button disabled={disabled} onClick={() => onAction('cancel')}>Cancel</Button>}</section>;
  if (!pending) return null;
  return <section className="agent-action-center" aria-label="Agent action center">
    <div><p className="agent-eyebrow">Action Center</p><h3>{pending.title}</h3><p>{pending.body}</p><Status tone="warning">Human gate</Status></div>
    <Button className="primary" disabled={disabled} onClick={() => onAction(pending.kind)}>{pending.actionLabel}</Button>
  </section>;
}
