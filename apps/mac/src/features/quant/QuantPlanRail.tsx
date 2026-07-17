import type { QuantPlanStep } from '../../quant-domain';

const ownerMarker: Record<QuantPlanStep['owner'], string> = { user: 'U', system: 'S', agent: 'A', validator: 'V' };

export function QuantPlanRail({ steps, currentStepId, completedStepCount }: { steps: QuantPlanStep[]; currentStepId: string; completedStepCount: number }) {
  return <aside className="quant-plan" aria-label="Research plan">
    <header className="quant-panel-heading"><div><p className="quant-eyebrow">Plan Rail</p><h3>Approved workflow</h3></div><span>{completedStepCount} of {steps.length} steps</span></header>
    <ol>
      {steps.map((step) => <li key={step.id} className={`owner-${step.owner} status-${step.status}`} aria-current={step.id === currentStepId ? 'step' : undefined}>
        <span className="quant-plan-marker" aria-hidden="true">{ownerMarker[step.owner]}</span>
        <div><div className="quant-plan-title"><strong>{step.title}</strong><span>{step.status}</span></div><p>{step.description}</p><small>{step.owner} · {step.artifactCount ? `${step.artifactCount} artifact${step.artifactCount === 1 ? '' : 's'}` : 'No artifact'}{step.humanGate ? ' · Human gate' : ''}</small></div>
      </li>)}
    </ol>
    <footer><span><i>U</i>User</span><span><i>A</i>Agent</span><span><i>S</i>System</span><span><i>V</i>Validator</span></footer>
  </aside>;
}
