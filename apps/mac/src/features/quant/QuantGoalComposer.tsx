import { useState, type KeyboardEvent } from 'react';
import { Button } from '@glint/ui';
import type { DatasetSnapshot, QuantCommand, QuantResearchMode, QuantWorkspaceSnapshot } from '../../quant-domain';

const modeCopy: Array<[QuantResearchMode, string, string]> = [
  ['ask', 'Ask', 'Read-only fixture answer'],
  ['plan', 'Plan', 'Generate a reviewable plan'],
  ['auto_research', 'Auto Research', 'The Agent may run up to three local experiments'],
];

const modeCommand: Record<QuantResearchMode, QuantCommand> = {
  ask: 'ask', plan: 'generate_plan', auto_research: 'start_auto_research',
};

export function QuantGoalComposer({ snapshot, selectedDataset = snapshot.dataset, large = false, onSubmit }: {
  snapshot: QuantWorkspaceSnapshot;
  selectedDataset?: DatasetSnapshot;
  large?: boolean;
  onSubmit: (command: QuantCommand, payload: Record<string, unknown>) => void;
}) {
  const [mode, setMode] = useState<QuantResearchMode>('plan');
  const [goal, setGoal] = useState(snapshot.project.goal);
  const command = modeCommand[mode];
  const effectiveGoal = goal;
  const legal = snapshot.composerLegalCommands.includes(command) || snapshot.run.legalCommands.includes(command);
  const datasetReady = selectedDataset.barCount >= 252;
  const canSubmit = Boolean(effectiveGoal.trim()) && legal && (mode !== 'auto_research' || datasetReady);
  const unavailableCopy = mode === 'auto_research'
    ? !datasetReady
      ? 'Auto Research requires at least 252 ordered daily bars in the selected dataset.'
      : 'Auto Research is available only before a run starts or after creating a new attempt.'
    : snapshot.run.state === 'running_experiments'
      ? 'This run already has an approved plan. Use Action Center or choose Auto Research to start the Agent.'
      : snapshot.run.state === 'completed'
        ? 'This attempt is complete and immutable. Start a new run to investigate another goal.'
        : `${mode === 'ask' ? 'Ask' : 'Plan'} is not legal in the current API-owned run state.`;
  const submit = () => {
    if (!canSubmit) return;
    onSubmit(command, {
      goal: goal.trim(),
      symbol: selectedDataset.symbol,
      interval: selectedDataset.interval,
      dateRange: selectedDataset.dateRange,
      benchmark: `${selectedDataset.symbol} Buy and Hold`,
      ...(mode === 'auto_research' ? { dataset_id: selectedDataset.id } : {}),
    });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); submit(); }
  };

  return <section className={`quant-composer${large ? ' is-large' : ''}`} aria-labelledby="quant-composer-title">
    <div className="quant-composer-heading"><div><p className="quant-eyebrow">Goal Composer</p><h2 id="quant-composer-title">What market outcome should PokieQuant investigate?</h2></div><div className="quant-mode-switch" role="group" aria-label="Research mode">{modeCopy.map(([id, label, description]) => <button key={id} aria-pressed={mode === id} title={description} onClick={() => setMode(id)}>{label}</button>)}</div></div>
    <div className="quant-composer-form">
      <label className="quant-goal-field"><span>Research goal</span><textarea value={effectiveGoal} onChange={(event) => setGoal(event.target.value)} onKeyDown={onKeyDown} rows={large ? 4 : 2} /></label>
      <label><span>Asset</span><select value={selectedDataset.symbol} disabled aria-label="Asset"><option>{selectedDataset.symbol}</option></select></label>
      <label><span>Interval</span><select value="1D" disabled aria-label="Interval"><option>1D</option></select></label>
      <label><span>Date range</span><input value={`${selectedDataset.dateRange.start} → ${selectedDataset.dateRange.end}`} readOnly /></label>
      <Button className="primary quant-submit" disabled={!canSubmit} onClick={submit}>{mode === 'ask' ? 'Ask fixture' : mode === 'plan' ? 'Generate plan' : 'Start research'}</Button>
    </div>
    <div className="quant-composer-foot"><span>Dataset · {selectedDataset.name}</span><span>Benchmark · {selectedDataset.symbol} Buy and Hold</span><span>{snapshot.limits.maxExperiments} experiments · {snapshot.limits.maxRepairAttempts} repairs · {snapshot.limits.maxRuntimeMinutes} min</span><span>Internet disabled · Python disabled · Paper trading disabled</span><kbd>⌘ Enter</kbd></div>
    {(!legal || (mode === 'auto_research' && !datasetReady)) && <p className="quant-inline-note" role="status">{unavailableCopy}</p>}
  </section>;
}
