import { Badge, Status } from '@glint/ui';
import { displayTime } from '../../lib/formatting';
import type { AgentSessionPresentation } from './agent-presentation';

export function AgentInspector({ presentation, runConnection }: { presentation: AgentSessionPresentation; runConnection: 'connected' | 'reconnecting' | 'reset' }) {
  return <aside className="agent-inspector" aria-label="Agent inspector">
    <div className="agent-panel-heading"><div><p className="agent-eyebrow">Inspector</p><h3>Run</h3></div><Status tone={presentation.statusTone}>{presentation.statusLabel}</Status></div>
    <dl className="agent-inspector-list">
      <dt>Mode</dt><dd>{presentation.modeLabel}</dd>
      <dt>Scope</dt><dd>{presentation.scopeSummary.sourceLabel}<br /><small>{presentation.scopeSummary.contentVersionLabel}</small></dd>
      <dt>Window</dt><dd>{presentation.scopeSummary.timeRange ? `${displayTime(presentation.scopeSummary.timeRange.start)} – ${displayTime(presentation.scopeSummary.timeRange.end)}` : 'Unavailable'}</dd>
      <dt>Budget</dt><dd>{presentation.budgetLimitLabel ?? 'Unavailable'}</dd>
      <dt>Current step</dt><dd>{presentation.planSteps.find((step) => step.id === presentation.currentStepId)?.title ?? 'Unavailable'}</dd>
      <dt>Activity</dt><dd><Badge tone={runConnection === 'connected' ? 'positive' : 'warning'}>{runConnection === 'connected' ? 'Current' : runConnection === 'reconnecting' ? 'Reconnecting' : 'Snapshot reloaded'}</Badge></dd>
      {presentation.mode === 'model-assisted' && <><dt>Provider</dt><dd>{presentation.modelEgress.provider ?? 'Unavailable'}</dd><dt>Model</dt><dd>{presentation.modelEgress.model ?? 'Unavailable'}</dd></>}
    </dl>
    <details className="agent-advanced"><summary>Advanced</summary><dl>
      <dt>Run ID</dt><dd><code>{presentation.advanced.runId ?? 'Not started'}</code></dd>
      <dt>Scope Version</dt><dd><code>{presentation.advanced.scopeVersionId}</code></dd>
      <dt>Graph Version</dt><dd><code>{presentation.advanced.graphVersion ?? 'Unavailable'}</code></dd>
      <dt>Latest Sequence</dt><dd>{presentation.advanced.latestSequence ?? 'None'}</dd>
      <dt>Exact node</dt><dd><code>{presentation.advanced.currentInternalNode ?? 'Unavailable'}</code></dd>
      <dt>Trace</dt><dd><code>{presentation.advanced.traceRef ?? 'Unavailable'}</code></dd>
      <dt>Prompt refs</dt><dd>{presentation.advanced.promptRefs.length ? presentation.advanced.promptRefs.map((ref) => <code key={ref}>{ref} </code>) : 'Not applicable / unavailable'}</dd>
    </dl></details>
  </aside>;
}
