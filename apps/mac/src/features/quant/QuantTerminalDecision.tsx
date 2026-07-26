import type { QuantTerminalDecisionProjection } from './quant-presentation';

type Props = {
  decision: QuantTerminalDecisionProjection | null;
  summary?: string;
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

export function QuantTerminalDecision({ decision, summary, onExportFinalEvidence, onOpenHistory, onRefineFinalChoice }: Props) {
  if (!decision) {
    return <section className="quant-terminal-decision is-unavailable" aria-labelledby="quant-terminal-decision-title">
      <header><div><span>Final decision</span><h4 id="quant-terminal-decision-title">Final decision unavailable</h4></div></header>
      <p>The retained final-selection and validation identities do not form one authoritative decision. Sealed-holdout evidence is withheld.</p>
      <div className="quant-terminal-actions"><button className="button" onClick={onOpenHistory}>Research history</button></div>
    </section>;
  }

  const headline = decision.holdoutStatus === 'pass'
    ? 'Evidence supports promotion review'
    : decision.holdoutStatus === 'fail'
      ? 'Evidence does not support promotion'
      : 'Evidence is not yet decisive';
  const refinementAvailable = Boolean(decision.canRefine && onRefineFinalChoice);
  const nextDecision = decision.decision === 'stop'
    ? 'Stop this research series'
    : refinementAvailable
      ? 'Refine one bounded parameter in the next version'
      : 'Keep this final decision read-only';

  return <section className={`quant-terminal-decision is-${decision.holdoutStatus}`} aria-labelledby="quant-terminal-decision-title">
    <header>
      <span>Final decision</span>
      <h2 id="quant-terminal-decision-title">{headline}</h2>
      <p>{summary ?? `${candidateName(decision.finalCandidateName)} was retained from training. ${decision.holdoutReason}`}</p>
    </header>
    <div className="quant-terminal-conclusion">
      <span>Qurio decision</span>
      <strong>{nextDecision}</strong>
      <small>{decision.decisionDetail}</small>
    </div>
    <dl className="quant-terminal-evidence">
      <div><dt>Final choice</dt><dd>{candidateName(decision.finalCandidateName)}</dd></div>
      <div><dt>Training selection</dt><dd>{retainedDecisionLabel(decision.selectionReason)}<small>{selectionBasis(decision.selectionBasis)}</small></dd></div>
      <div><dt>Sealed holdout</dt><dd><strong className={`is-${decision.holdoutStatus}`}>{holdoutLabel(decision.holdoutStatus)}</strong><small>{decision.holdoutReason}</small></dd></div>
    </dl>
    {refinementAvailable && decision.refinement && <dl className="quant-terminal-refinement" aria-label="Refinement proposal">
      <div><dt>Proposed change</dt><dd>{decision.refinement.proposedChange}</dd></div>
      <div><dt>Evidence basis</dt><dd>{decision.refinement.evidenceBasis}</dd></div>
      <div><dt>Success / stop condition</dt><dd><span>{decision.refinement.successCondition}</span><small>{decision.refinement.stopCondition}</small></dd></div>
    </dl>}
    <div className="quant-terminal-actions" aria-label="Final decision actions">
      {refinementAvailable && <button className="button primary" onClick={() => onRefineFinalChoice?.(decision.finalCandidateId, decision.refinementReason)}>Refine version</button>}
      {onExportFinalEvidence && <button className="button" onClick={() => onExportFinalEvidence(decision.finalCandidateId)}>Export evidence</button>}
      <button className="button" onClick={onOpenHistory}>Research history</button>
    </div>
  </section>;
}
