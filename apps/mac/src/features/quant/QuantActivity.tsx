import { useState } from 'react';
import { Button } from '@glint/ui';
import type { QuantArtifact, QuantWorkspaceSnapshot } from '../../quant-domain';
import { quantAuthenticityLabel } from '../../quant-domain';
import type { QuantActionPresentation, QuantActivityPresentation, QuantWorkspacePresentation } from './quant-presentation';

function displayTime(value: string): string {
  return new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}

const terminalStates: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled']);

export function QuantRunMonitor({ snapshot, presentation, onAction, isPolling, busy = false }: {
  snapshot: QuantWorkspaceSnapshot;
  presentation: QuantWorkspacePresentation;
  onAction: (action: QuantActionPresentation, payload?: Record<string, unknown>) => void;
  isPolling: boolean;
  busy?: boolean;
}) {
  const [showPlanChange, setShowPlanChange] = useState(false);
  const [planChange, setPlanChange] = useState('');
  const isTerminal = terminalStates.has(snapshot.run.state);
  const progressPercent = snapshot.plan.length > 0
    ? Math.round((presentation.completedStepCount / snapshot.plan.length) * 100)
    : 0;
  const currentStep = snapshot.plan.find((step) => step.id === snapshot.run.currentStepId);
  const providerLine = snapshot.run.model
    ? `${snapshot.run.provider} · ${snapshot.run.model}`
    : snapshot.run.provider;
  const connectionLabel = isTerminal
    ? 'Immutable'
    : isPolling
      ? 'Live · polling'
      : snapshot.run.state === 'waiting_for_review' || snapshot.run.state === 'waiting_plan_approval'
        ? 'Awaiting review'
        : snapshot.run.state === 'draft'
          ? 'Awaiting start'
          : 'Ready';
  return <section className={`quant-run-monitor tone-${presentation.statusTone}`} aria-labelledby="quant-run-monitor-title">
    <header className="quant-run-monitor-header">
      <div>
        <span className="quant-run-monitor-label">Run monitor</span>
        <h3 id="quant-run-monitor-title">{presentation.currentActionTitle}</h3>
        <p>{presentation.currentActionPurpose}</p>
      </div>
      <div className="quant-run-monitor-state"><strong className={`is-${presentation.statusTone}`}>{presentation.statusLabel}</strong><span>{connectionLabel}</span><span>Attempt {snapshot.run.attemptNumber}</span></div>
    </header>
    {!isTerminal && <div className="quant-run-monitor-progress" role="progressbar" aria-valuenow={progressPercent} aria-valuemin={0} aria-valuemax={100} aria-label="Approved plan completion">
      <div className="quant-run-progress-track" aria-hidden="true"><div className="quant-run-monitor-progress-bar" style={{ width: `${progressPercent}%` }} /></div>
      <span>{presentation.completedStepCount} of {snapshot.plan.length} plan steps{currentStep ? ` · current: ${currentStep.title}` : ''}</span>
    </div>}
    <dl className="quant-run-monitor-meta">
      <div><dt>Provider</dt><dd>{providerLine}</dd></div>
      <div><dt>Plan</dt><dd>{presentation.completedStepCount} / {snapshot.plan.length} complete</dd></div>
      <div><dt>Experiments</dt><dd>{snapshot.run.usedExperiments} / {snapshot.limits.maxExperiments}</dd></div>
      <div><dt>Strategy revisions</dt><dd>{snapshot.run.usedRepairAttempts} / {snapshot.limits.maxRepairAttempts}</dd></div>
    </dl>
    {presentation.actions.length > 0 && <div className="quant-run-monitor-lower"><div className="quant-run-monitor-controls" role="group" aria-label="Run controls" aria-busy={busy}>
      {presentation.actions.map((action) => <Button disabled={busy} className={action.tone === 'primary' ? 'primary' : ''} key={action.kind} onClick={() => action.kind === 'request_plan_changes' ? setShowPlanChange(true) : onAction(action)}>{action.label}</Button>)}
      {busy && <span className="quant-command-pending" role="status">Submitting command…</span>}
    </div>{showPlanChange && <form className="pq-plan-change-form" onSubmit={(event) => {
      event.preventDefault();
      const changeRequest = planChange.trim();
      const action = presentation.actions.find((item) => item.kind === 'request_plan_changes');
      if (!action || !changeRequest || busy) return;
      onAction(action, { changeRequest });
    }}>
      <label htmlFor="quant-monitor-plan-change">What should change in the plan?</label>
      <textarea id="quant-monitor-plan-change" value={planChange} maxLength={1000} disabled={busy} autoFocus onChange={(event) => setPlanChange(event.target.value)} />
      <div><button type="button" disabled={busy} onClick={() => { setShowPlanChange(false); setPlanChange(''); }}>Cancel</button><button type="submit" className="primary" disabled={!planChange.trim() || busy}>{busy ? 'Working…' : 'Generate revised plan'}</button></div>
    </form>}</div>}
    <details className="quant-run-monitor-audit"><summary>Run details</summary><dl><div><dt>Iteration</dt><dd>{snapshot.run.agentIteration} / {snapshot.run.maxAgentIterations}</dd></div><div><dt>Dataset digest</dt><dd><code title={snapshot.dataset.digest}>{snapshot.dataset.digest}</code></dd></div><div><dt>Trace reference</dt><dd><code>{snapshot.run.traceRef}</code></dd></div></dl></details>
  </section>;
}

export function QuantActivityFeed({ snapshot, presentation, onInspect }: {
  snapshot: QuantWorkspaceSnapshot;
  presentation: QuantWorkspacePresentation;
  onInspect: (event: QuantActivityPresentation) => void;
}) {
  return <section className="quant-activity" aria-label="Run activity">
    <div className="quant-panel-heading"><h3>Run activity</h3><span>{presentation.activity.length} events · Attempt {snapshot.run.attemptNumber}</span></div>
    <ol className="quant-activity-list">
      {presentation.activity.map((event) => <li key={event.id} className={`quant-activity-${event.kind}`}><time dateTime={event.timestamp}>{displayTime(event.timestamp)}</time><div><div className="quant-event-title"><strong>{event.title}</strong></div>{event.action && <dl><div><dt>Action</dt><dd><code>{event.action}</code></dd></div>{event.expectedResult && <div><dt>Expected result</dt><dd>{event.expectedResult}</dd></div>}</dl>}<p>{event.summary}</p><footer><span>{event.actorLabel}{event.artifactId ? ' · Artifact retained' : ''}</span><button onClick={() => onInspect(event)} aria-label={`Inspect ${event.title}`}>Inspect</button></footer></div></li>)}
    </ol>
  </section>;
}

export function QuantKernelCheckCard({ snapshot }: { snapshot: QuantWorkspaceSnapshot }) {
  const check = snapshot.kernelCheck;
  const verified = check.status === 'verified' && check.benchmark !== null;
  const splitAware = check.limitations.some((item) => item.includes('training partition'));
  const datasetLabel = snapshot.authenticity === 'synthetic_fixture' ? 'synthetic weekday' : 'workspace-imported';
  const kernelLabel = snapshot.dataset.contract === 'market-v2' ? `${snapshot.scope.interval} market-bar kernel` : 'Daily-bar kernel';
  return <article className="quant-kernel-check" aria-label={`${kernelLabel} verification`}>
    <header><div><h3>{kernelLabel} {verified ? 'verified' : 'ready'}</h3><p>Execution assumptions and reproducibility checks</p></div><strong className={verified ? 'is-positive' : ''}>{check.status}</strong></header>
    <p>{verified ? splitAware ? `Pure local research from the ${check.barCount.toLocaleString()}-bar ${datasetLabel} dataset. Candidate selection metrics use only the training partition; sealed holdout evidence is retained in Generalization.` : `Pure local research run over ${check.barCount.toLocaleString()} ${datasetLabel} bars. Candidate metrics and trades are generated by this same kernel.` : `The digest-pinned ${check.barCount.toLocaleString()}-bar ${datasetLabel} dataset and fixed strategy specs are ready. Results remain hidden until the API advances the run.`}</p>
    <dl><div><dt>{verified ? splitAware ? 'Training benchmark annualized' : 'Benchmark annualized' : 'Results'}</dt><dd>{verified && check.benchmark ? `${check.benchmark.annualizedReturnPct >= 0 ? '+' : ''}${check.benchmark.annualizedReturnPct.toFixed(2)}%` : 'Pending Agent run'}</dd></div><div><dt>Strategies</dt><dd>{verified ? `${check.strategies.length} computed specs` : '3 fixed specs'}</dd></div><div><dt>Execution</dt><dd>Close signal → next open</dd></div><div><dt>Costs</dt><dd>{check.feeRateBps} bps fee · {check.slippageRateBps} bps slippage</dd></div></dl>
    <footer><span>No network · no broker · no arbitrary code</span><code title={check.datasetDigest}>{check.datasetDigest.slice(0, 19)}…</code></footer>
  </article>;
}

export function QuantArtifactCards({ artifacts, onInspect }: { artifacts: QuantArtifact[]; onInspect: (artifact: QuantArtifact) => void }) {
  return <section className="quant-artifacts" aria-labelledby="quant-artifact-title">
    <div className="quant-panel-heading"><h3 id="quant-artifact-title">Retained artifacts</h3><span>{artifacts.length}</span></div>
    <div className="quant-artifact-grid">{artifacts.map((artifact) => <article key={artifact.id} className={`quant-artifact-card type-${artifact.type}`}>
      <header><div><span>{artifact.type.replaceAll('_', ' ')}</span><h4>{artifact.title}</h4></div><strong className={`is-${artifact.status}`}>{artifact.status}</strong></header>
      <p>{artifact.summary}</p><footer><span>{artifact.origin} · {quantAuthenticityLabel(artifact.authenticity)} · {artifact.relatedLabel}</span><Button onClick={() => onInspect(artifact)}>Inspect</Button></footer>
    </article>)}</div>
  </section>;
}
