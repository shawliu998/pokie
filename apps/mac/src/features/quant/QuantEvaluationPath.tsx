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

export function QuantEvaluationPath({ snapshot, compact = false }: { snapshot: QuantWorkspaceSnapshot; compact?: boolean }) {
  const walkForward = snapshot.report?.walkForward;
  const generalization = snapshot.report?.generalization;
  const hasTrainingEvidence = snapshot.candidates.length > 0;
  const holdoutState: StageState = generalization?.status === 'pass'
    ? 'pass'
    : generalization?.status === 'fail'
      ? 'fail'
      : generalization?.status === 'inconclusive'
        ? 'inconclusive'
        : 'pending';
  const promotionState: StageState = generalization?.status === 'pass' ? 'pass' : generalization ? 'blocked' : 'pending';
  const stages: Array<{ title: string; detail: string; state: StageState }> = [
    { title: 'Training screen', detail: hasTrainingEvidence ? `${snapshot.candidates.length} candidate${snapshot.candidates.length === 1 ? '' : 's'} compared` : 'No candidate evidence', state: hasTrainingEvidence ? 'complete' : 'pending' },
    { title: 'Walk-forward', detail: walkForward ? `${walkForward.aggregate.evaluatedFolds} training windows` : 'Not evaluated', state: walkForward?.status === 'completed' ? 'complete' : 'pending' },
    { title: 'Sealed holdout', detail: generalization?.reason ?? 'Not evaluated', state: holdoutState },
    { title: 'Promotion', detail: generalization?.status === 'pass' ? 'Eligible for human review' : generalization ? 'Blocked by validation policy' : 'Awaiting holdout evidence', state: promotionState },
  ];

  return <ol className={`pq-evaluation-path${compact ? ' is-compact' : ''}`} aria-label="Research evaluation stages">
    {stages.map((stage) => <li key={stage.title} className={`is-${stage.state}`}>
      <span>{stage.title}</span>
      <strong>{stageLabel(stage.state)}</strong>
      {!compact && <small>{stage.detail}</small>}
    </li>)}
  </ol>;
}
