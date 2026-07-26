import type { QuantWorkspaceSnapshot } from '../../quant-domain';

type StageState = 'complete' | 'pass' | 'fail' | 'blocked' | 'inconclusive' | 'pending';

function stageLabel(state: StageState) {
  if (state === 'complete') return 'Complete';
  if (state === 'pass') return 'Passed';
  if (state === 'fail') return 'Failed';
  if (state === 'blocked') return 'Blocked';
  if (state === 'inconclusive') return 'Inconclusive';
  return 'Pending';
}

function signedPercent(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

export function QuantEvaluationPath({ snapshot, compact = false }: { snapshot: QuantWorkspaceSnapshot; compact?: boolean }) {
  const walkForward = snapshot.report?.walkForward;
  const generalization = snapshot.report?.generalization;
  const selection = snapshot.report?.selectionDecision;
  const selectedCandidate = selection?.selectedCandidateId
    ? snapshot.candidates.find((candidate) => candidate.id === selection.selectedCandidateId)
    : undefined;
  const selectionIdentityConsistent = Boolean(
    selectedCandidate
    && generalization?.selectedCandidateId === selectedCandidate.id,
  );
  const hasTrainingEvidence = snapshot.candidates.length > 0;
  const comparisonRank = selectedCandidate?.evolution?.comparisonRank;
  const comparisonCount = selectedCandidate?.evolution?.comparisonCandidateCount;
  const trainingDetail = selectedCandidate && comparisonRank && comparisonCount
    ? `${selectedCandidate.name.replace(/^Candidate [A-Z] · /, '')} ranked #${comparisonRank} of ${comparisonCount}`
    : hasTrainingEvidence
      ? `${snapshot.candidates.length} candidate${snapshot.candidates.length === 1 ? '' : 's'} compared`
      : 'No candidate evidence';
  const walkForwardDetail = walkForward
    ? `${walkForward.aggregate.candidatePositiveReturnFolds} of ${walkForward.foldCount} positive-return windows`
    : 'Not evaluated';
  const holdoutMetrics = selectionIdentityConsistent ? generalization?.holdout?.candidate : undefined;
  const holdoutDetail = generalization && !selectionIdentityConsistent
    ? 'Final-selection identity conflicts with the retained holdout; evidence is withheld.'
    : holdoutMetrics
      ? `${signedPercent(holdoutMetrics.annualizedReturn)} annual return · ${holdoutMetrics.sharpe.toFixed(2)} Sharpe · ${signedPercent(holdoutMetrics.maxDrawdown)} drawdown · ${holdoutMetrics.trades} trades`
      : generalization?.reason ?? 'Not evaluated';
  const holdoutState: StageState = !selectionIdentityConsistent
    ? 'pending'
    : generalization?.status === 'pass'
      ? 'pass'
      : generalization?.status === 'fail'
        ? 'fail'
        : generalization?.status === 'inconclusive'
          ? 'inconclusive'
          : 'pending';
  const promotionState: StageState = generalization && !selectionIdentityConsistent
    ? 'blocked'
    : generalization?.status === 'pass'
      ? 'pass'
      : generalization
        ? 'blocked'
        : 'pending';
  const stages: Array<{ title: string; detail: string; state: StageState }> = [
    { title: 'Training selection', detail: trainingDetail, state: hasTrainingEvidence ? 'complete' : 'pending' },
    { title: 'Walk-forward', detail: walkForwardDetail, state: walkForward?.status === 'completed' ? 'complete' : 'pending' },
    { title: 'Sealed holdout', detail: holdoutDetail, state: holdoutState },
    {
      title: 'Promotion',
      detail: generalization && !selectionIdentityConsistent
        ? 'Blocked until final-selection and holdout identities agree'
        : generalization?.status === 'pass'
        ? 'Eligible for human promotion review'
        : generalization?.status === 'inconclusive'
          ? 'Blocked until evidence becomes decisive'
          : generalization
            ? 'Blocked by sealed-holdout evidence'
            : 'Awaiting sealed-holdout evidence',
      state: promotionState,
    },
  ];

  return <ol className={`pq-evaluation-path${compact ? ' is-compact' : ''}`} aria-label="Research evaluation stages">
    {stages.map((stage) => <li key={stage.title} className={`is-${stage.state}`}>
      <span>{stage.title}</span>
      <strong>{stageLabel(stage.state)}</strong>
      {!compact && <small>{stage.detail}</small>}
    </li>)}
  </ol>;
}
