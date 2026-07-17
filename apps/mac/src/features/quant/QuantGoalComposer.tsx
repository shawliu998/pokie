import { useState, type KeyboardEvent } from 'react';
import { Button } from '@glint/ui';
import type { QuantCommand, QuantResearchMode, QuantWorkspaceSnapshot } from '../../quant-domain';

const modeCopy: Array<[QuantResearchMode, string, string]> = [
  ['ask', 'Ask', 'Read-only fixture answer'],
  ['plan', 'Plan', 'Generate a reviewable plan'],
  ['auto_research', 'Auto Research', 'Requires an approved plan'],
];

const modeCommand: Record<QuantResearchMode, QuantCommand> = {
  ask: 'ask', plan: 'generate_plan', auto_research: 'start_auto_research',
};

export function QuantGoalComposer({ snapshot, large = false, onSubmit }: {
  snapshot: QuantWorkspaceSnapshot;
  large?: boolean;
  onSubmit: (command: QuantCommand, payload: Record<string, unknown>) => void;
}) {
  const [mode, setMode] = useState<QuantResearchMode>('plan');
  const [goal, setGoal] = useState(snapshot.project.goal);
  const command = modeCommand[mode];
  const legal = snapshot.composerLegalCommands.includes(command);
  const submit = () => {
    if (!goal.trim() || !legal) return;
    onSubmit(command, { goal: goal.trim(), symbol: snapshot.scope.symbol, interval: snapshot.scope.interval, dateRange: snapshot.scope.dateRange, benchmark: snapshot.scope.benchmark });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); submit(); }
  };

  return <section className={`quant-composer${large ? ' is-large' : ''}`} aria-labelledby="quant-composer-title">
    <div className="quant-composer-heading"><div><p className="quant-eyebrow">Goal Composer</p><h2 id="quant-composer-title">What market outcome should PokieQuant investigate?</h2></div><div className="quant-mode-switch" role="group" aria-label="Research mode">{modeCopy.map(([id, label, description]) => <button key={id} aria-pressed={mode === id} title={description} onClick={() => setMode(id)}>{label}</button>)}</div></div>
    <div className="quant-composer-form">
      <label className="quant-goal-field"><span>Research goal</span><textarea value={goal} onChange={(event) => setGoal(event.target.value)} onKeyDown={onKeyDown} rows={large ? 4 : 2} /></label>
      <label><span>Asset</span><select value="SPY" disabled aria-label="Asset"><option>SPY</option></select></label>
      <label><span>Interval</span><select value="1D" disabled aria-label="Interval"><option>1D</option></select></label>
      <label><span>Date range</span><input value={`${snapshot.scope.dateRange.start} → ${snapshot.scope.dateRange.end}`} readOnly /></label>
      <Button className="primary quant-submit" disabled={!goal.trim() || !legal} onClick={submit}>{mode === 'ask' ? 'Ask fixture' : mode === 'plan' ? 'Generate plan' : 'Start research'}</Button>
    </div>
    <div className="quant-composer-foot"><span>Benchmark · {snapshot.scope.benchmark}</span><span>{snapshot.limits.maxExperiments} experiments · {snapshot.limits.maxRepairAttempts} repairs · {snapshot.limits.maxRuntimeMinutes} min</span><span>Internet disabled · Python disabled · Paper trading disabled</span><kbd>⌘ Enter</kbd></div>
    {!legal && <p className="quant-inline-note" role="status">Auto Research is unavailable for a new goal until the API reports an approved plan and legal start command.</p>}
  </section>;
}
