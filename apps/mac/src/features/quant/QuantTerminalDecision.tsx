import type { QuantTerminalDecisionProjection } from './quant-presentation';

type Props = {
  decision: QuantTerminalDecisionProjection | null;
  onExportFinalEvidence?: (candidateId: string) => void;
  onOpenHistory: () => void;
  onRefineFinalChoice?: (candidateId: string, reason: string) => void;
};

const candidateName = (value: string) => value.replace(/^Candidate [A-Z] · /, '');
const holdoutLabel = (status: QuantTerminalDecisionProjection['holdoutStatus']) => status === 'pass'
  ? 'Passed'
  : status === 'fail'
    ? 'Failed'
    : 'Inconclusive';
const selectionBasis = (basis: QuantTerminalDecisionProjection['selectionBasis']) => basis === 'robustness_override'
  ? 'Retained robustness decision'
  : 'Approved objective ranking';

const retainedDecisionLabels: Record<string, string> = {
  approved_objective_rank: 'Approved objective ranking',
  minimum_trade_evidence: 'Minimum trade evidence',
  regime_coverage: 'Regime coverage',
  robustness_override: 'Retained robustness decision',
  walk_forward_stability: 'Walk-forward stability',
};
const retainedDecisionLabel = (value: string) => retainedDecisionLabels[value] ?? value;

export function QuantTerminalDecision({ decision, onExportFinalEvidence, onOpenHistory, onRefineFinalChoice }: Props) {
  if (!decision) {
    return <section className="quant-terminal-decision is-unavailable" aria-labelledby="quant-terminal-decision-title">
      <header><div><span>Final decision</span><h4 id="quant-terminal-decision-title">Final decision unavailable</h4></div></header>
      <p>The retained final-selection and validation identities do not form one authoritative decision. Sealed-holdout evidence is withheld.</p>
      <div className="quant-terminal-actions"><button className="button" onClick={onOpenHistory}>Research history</button></div>
    </section>;
  }

  return <section className="quant-terminal-decision" aria-labelledby="quant-terminal-decision-title">
    <header><div><span>Final decision</span><h4 id="quant-terminal-decision-title">{decision.decision === 'stop' ? 'Stop this research series' : decision.canRefine ? 'Refine the final choice' : 'Final decision retained'}</h4></div></header>
    <dl>
      <div><dt>Final choice</dt><dd><strong>{candidateName(decision.finalCandidateName)}</strong></dd></div>
      <div><dt>Why</dt><dd>{retainedDecisionLabel(decision.selectionReason)}<small>{selectionBasis(decision.selectionBasis)}</small></dd></div>
      <div><dt>Sealed holdout</dt><dd><strong className={`is-${decision.holdoutStatus}`}>{holdoutLabel(decision.holdoutStatus)}</strong><small>{decision.holdoutReason}</small></dd></div>
      <div><dt>Decision</dt><dd>{decision.decision === 'stop'
        ? <><strong>Stop this research series</strong><small>{decision.decisionDetail}</small></>
        : decision.canRefine && onRefineFinalChoice
          ? <><button className="button primary" onClick={() => onRefineFinalChoice(decision.finalCandidateId, decision.refinementReason)}>Review &amp; refine research</button><small>{decision.decisionDetail}</small></>
          : <><strong>Read-only final decision</strong><small>{decision.decisionDetail}</small></>}</dd></div>
      <div><dt>Deliverable / Memory</dt><dd className="quant-terminal-actions">{onExportFinalEvidence && <button className="button" onClick={() => onExportFinalEvidence(decision.finalCandidateId)}>Export final evidence</button>}<button className="button" onClick={onOpenHistory}>Research history</button></dd></div>
    </dl>
    {decision.canRefine && decision.refinement && onRefineFinalChoice && <dl className="quant-terminal-refinement" aria-label="Refinement proposal">
      <div><dt>Proposed change</dt><dd>{decision.refinement.proposedChange}</dd></div>
      <div><dt>Evidence basis / Why</dt><dd>{decision.refinement.evidenceBasis}</dd></div>
      <div><dt>Success / stop condition</dt><dd><span>{decision.refinement.successCondition}</span><small>{decision.refinement.stopCondition}</small></dd></div>
    </dl>}
  </section>;
}
