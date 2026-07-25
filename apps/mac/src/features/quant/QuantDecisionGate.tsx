import type { ReactNode } from 'react';
import type { QuantDecisionPresentation } from './quant-presentation';

export function QuantDecisionGate({ decision, action, className = '' }: {
  decision: QuantDecisionPresentation;
  action?: ReactNode;
  className?: string;
}) {
  return <section className={`quant-decision-gate is-${decision.tone} ${className}`.trim()} aria-label="Promotion decision">
    <div className="quant-decision-outcome">
      <span>{decision.label}</span>
      <strong>{decision.title}</strong>
      <p>{decision.summary}</p>
    </div>
    <div className="quant-decision-next">
      <span>Next</span>
      <p>{decision.nextStep}</p>
      {action}
    </div>
  </section>;
}
