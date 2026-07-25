import type { QuantPlanStep } from '../../quant-domain';

export function QuantPlanRail({ steps, currentStepId, completedStepCount }: { steps: QuantPlanStep[]; currentStepId: string; completedStepCount: number }) {
  return <aside className="quant-plan" aria-label="Research plan">
    <header className="quant-panel-heading"><h3>Research plan</h3><span>{completedStepCount}/{steps.length} complete</span></header>
    <ol>
      {steps.map((step, index) => {
        const isCurrent = step.id === currentStepId;
        const supporting = [step.humanGate ? 'Human review' : null, step.artifactCount ? `${step.artifactCount} artifact${step.artifactCount === 1 ? '' : 's'}` : null].filter(Boolean).join(' · ');
        return <li key={step.id} className={`status-${step.status}`} aria-current={isCurrent ? 'step' : undefined}>
          <span className="quant-plan-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
          <div><div className="quant-plan-title"><strong>{step.title}</strong>{isCurrent && step.status !== 'completed' && <span>{step.status}</span>}</div>{supporting && <small>{supporting}</small>}</div>
        </li>;
      })}
    </ol>
  </aside>;
}
