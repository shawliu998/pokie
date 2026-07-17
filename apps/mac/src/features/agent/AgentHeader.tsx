import { Badge, Button, Status } from '@glint/ui';
import { authenticityLabel } from '../../domain';
import { displayTime } from '../../lib/formatting';
import type { AgentSessionPresentation } from './agent-presentation';

interface AgentHeaderProps {
  presentation: AgentSessionPresentation;
  disabled: boolean;
  onCancel: () => void;
  onRetry: () => void;
  onCreateBrief: () => void;
  onOpenBrief: () => void;
}
export function AgentHeader({ presentation, disabled, onCancel, onRetry, onCreateBrief, onOpenBrief }: AgentHeaderProps) {
  const { scopeSummary } = presentation;
  return <header className="agent-header">
    <div className="agent-header-title">
      <p className="agent-eyebrow">Agent Workspace</p>
      <h2>{presentation.goal}</h2>
      <div className="agent-header-badges">
        <Status tone={presentation.statusTone}>{presentation.statusLabel}</Status>
        <Badge tone={presentation.mode === 'model-assisted' ? 'warning' : 'neutral'}>{presentation.modeLabel}</Badge>
        <Badge tone="info">{authenticityLabel(presentation.authenticity)}</Badge>
        {presentation.fixtureLabel && <Badge tone="warning">{presentation.fixtureLabel}</Badge>}
      </div>
    </div>
    <div className="agent-header-meta" aria-label="Agent run summary">
      <details className="agent-header-disclosure">
        <summary><strong>{scopeSummary.sourceLabel}</strong><span>{scopeSummary.contentVersionLabel}</span></summary>
        <div className="agent-popover">
          <h3>Approved scope</h3>
          <dl>
            <dt>Sources</dt><dd>{scopeSummary.sourceNames.length ? scopeSummary.sourceNames.join(', ') : scopeSummary.sourceLabel}</dd>
            <dt>Content</dt><dd>{scopeSummary.contentVersionLabel}</dd>
            <dt>Window</dt><dd>{scopeSummary.timeRange ? `${displayTime(scopeSummary.timeRange.start)} – ${displayTime(scopeSummary.timeRange.end)}` : 'Not supplied'}</dd>
          </dl>
        </div>
      </details>
      {presentation.modelEgress.approved
        ? <details className="agent-header-disclosure egress-disclosure"><summary><strong>Model egress approved for this run</strong><span>{presentation.modelEgress.provider ?? 'Provider unavailable'} · {presentation.modelEgress.model ?? 'Model unavailable'}</span></summary><div className="agent-popover"><h3>Run-scoped model egress</h3><dl><dt>Will be sent</dt><dd>{presentation.modelEgress.willSend}</dd><dt>Will not be sent</dt><dd>{presentation.modelEgress.willNotSend}</dd><dt>Provider</dt><dd>{presentation.modelEgress.provider ?? 'Unavailable'}</dd><dt>Model</dt><dd>{presentation.modelEgress.model ?? 'Unavailable'}</dd></dl></div></details>
        : <div className="agent-meta-item"><strong>No model egress</strong><span>Approved scope remains in deterministic research.</span></div>}
      {presentation.budgetLimitLabel && <div className="agent-meta-item"><strong>{presentation.budgetLimitLabel}</strong><span>Configured limit; actual spend is not inferred.</span></div>}
    </div>
    {(presentation.canCancel || presentation.canRetry || presentation.canCreateBrief || presentation.canOpenBrief) && <div className="agent-header-actions">
      {presentation.canCancel && <Button disabled={disabled} onClick={onCancel}>Cancel</Button>}
      {presentation.canRetry && <Button disabled={disabled} onClick={onRetry}>Retry</Button>}
      {presentation.canCreateBrief && <Button className="primary" disabled={disabled} onClick={onCreateBrief}>Create Decision Brief</Button>}
      {presentation.canOpenBrief && <Button className="primary" onClick={onOpenBrief}>Open Decision Brief</Button>}
    </div>}
  </header>;
}
