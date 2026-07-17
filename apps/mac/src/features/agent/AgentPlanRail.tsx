import { displayTime } from '../../lib/formatting';
import type { AgentPlanStepPresentation } from './agent-presentation';

function markerLabel(step: AgentPlanStepPresentation): string {
  if (step.owner === 'human') return 'H';
  if (step.owner === 'system') return 'S';
  return 'A';
}
export function AgentPlanRail({ steps, currentStepId, completedStepCount }: { steps: AgentPlanStepPresentation[]; currentStepId: string; completedStepCount: number }) {
  return <aside className="agent-plan-rail" aria-label="Agent plan">
    <div className="agent-panel-heading"><div><p className="agent-eyebrow">Plan</p><h3>Investigation workflow</h3></div><span>{completedStepCount} of {steps.length}</span></div>
    <ol className="agent-plan-list">
      {steps.map((step) => <li className={`agent-plan-step owner-${step.owner} step-${step.status}`} aria-current={step.id === currentStepId ? 'step' : undefined} key={step.id}>
        <span className="agent-step-marker" aria-hidden="true">{markerLabel(step)}</span>
        <div>
          <div className="agent-step-title"><strong>{step.title}</strong><span>{step.status}</span></div>
          <p>{step.description}</p>
          <small>{step.artifactCount > 0 ? `${step.artifactCount} artifact${step.artifactCount === 1 ? '' : 's'}` : 'No artifact yet'}{step.timestamp ? ` · ${displayTime(step.timestamp)}` : ''}</small>
          {step.needsAction && <small className="agent-step-action">Your action is required</small>}
        </div>
      </li>)}
    </ol>
    <div className="agent-plan-legend" aria-label="Plan ownership legend"><span><i className="owner-system">S</i> System</span><span><i className="owner-agent">A</i> Agent</span><span><i className="owner-human">H</i> Human</span></div>
  </aside>;
}
