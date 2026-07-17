import { useState, type KeyboardEvent } from 'react';
import { Button } from '@glint/ui';
import type { QuantCommand, QuantResearchMode, QuantWorkspaceSnapshot } from '../../quant-domain';

const modeCopy: Array<[QuantResearchMode, string, string]> = [
  ['ask', 'Ask', 'Read-only fixture answer'],
  ['plan', 'Plan', 'Generate a reviewable plan'],
  ['auto_research', 'Auto Research', 'Requires an approved plan'],
];

const modeCommand: Record<QuantResearchMode, QuantCommand> = {
  ask: 'ask', plan: 'generate_plan', auto_research: 'run_fixture',
};

export function QuantGoalComposer({ snapshot, large = false, onSubmit }: {
  snapshot: QuantWorkspaceSnapshot;
  large?: boolean;
  onSubmit: (command: QuantCommand, payload: Record<string, unknown>) => void;
}) {
  const [mode, setMode] = useState<QuantResearchMode>('plan');
  const [goal, setGoal] = useState(snapshot.project.goal);
  const command = modeCommand[mode];
  const effectiveGoal = command === 'run_fixture' ? snapshot.project.goal : goal;
  const legal = snapshot.composerLegalCommands.includes(command) || snapshot.run.legalCommands.includes(command);
  const unavailableCopy = mode === 'auto_research'
    ? 'Auto Research becomes available after the API records plan approval.'
    : snapshot.run.state === 'running_experiments'
      ? 'This run already has an approved plan. Use Action Center or choose Auto Research to start the Agent.'
      : snapshot.run.state === 'completed'
        ? 'This attempt is complete and immutable. Start a new run to investigate another goal.'
        : `${mode === 'ask' ? 'Ask' : 'Plan'} is not legal in the current API-owned run state.`;
  const submit = () => {
    if (!effectiveGoal.trim() || !legal) return;
    onSubmit(command, command === 'run_fixture' ? {} : { goal: goal.trim(), symbol: snapshot.scope.symbol, interval: snapshot.scope.interval, dateRange: snapshot.scope.dateRange, benchmark: snapshot.scope.benchmark });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); submit(); }
  };

  return <section className={`quant-composer${large ? ' is-large' : ''}`} aria-labelledby="quant-composer-title">
    <div className="quant-composer-heading"><div><p className="quant-eyebrow">Goal Composer</p><h2 id="quant-composer-title">What market outcome should PokieQuant investigate?</h2></div><div className="quant-mode-switch" role="group" aria-label="Research mode">{modeCopy.map(([id, label, description]) => <button key={id} aria-pressed={mode === id} title={description} onClick={() => setMode(id)}>{label}</button>)}</div></div>
    <div className="quant-composer-form">
      <label className="quant-goal-field"><span>Research goal</span><textarea value={effectiveGoal} disabled={command === 'run_fixture'} onChange={(event) => setGoal(event.target.value)} onKeyDown={onKeyDown} rows={large ? 4 : 2} /></label>
      <label><span>Asset</span><select value="SPY" disabled aria-label="Asset"><option>SPY</option></select></label>
      <label><span>Interval</span><select value="1D" disabled aria-label="Interval"><option>1D</option></select></label>
      <label><span>Date range</span><input value={`${snapshot.scope.dateRange.start} → ${snapshot.scope.dateRange.end}`} readOnly /></label>
      <Button className="primary quant-submit" disabled={!effectiveGoal.trim() || !legal} onClick={submit}>{mode === 'ask' ? 'Ask fixture' : mode === 'plan' ? 'Generate plan' : 'Start research'}</Button>
    </div>
    <div className="quant-composer-foot"><span>Benchmark · {snapshot.scope.benchmark}</span><span>{snapshot.limits.maxExperiments} experiments · {snapshot.limits.maxRepairAttempts} repairs · {snapshot.limits.maxRuntimeMinutes} min</span><span>Internet disabled · Python disabled · Paper trading disabled</span><kbd>⌘ Enter</kbd></div>
    {!legal && <p className="quant-inline-note" role="status">{unavailableCopy}</p>}
  </section>;
}
