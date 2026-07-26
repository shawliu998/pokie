import { useEffect, useMemo, useState, type KeyboardEvent } from 'react';
import { Button, Kbd } from '@glint/ui';
import type { QuantApi } from '../../quant-api';
import type { DatasetSnapshot, QuantCommand, QuantResearchMode, QuantWorkspaceSnapshot } from '../../quant-domain';
import { marketResearchRequirementLabel, requiredMarketResearchBars } from '../../quant-research-eligibility';

export type QuantRefinementContext = {
  projectId: string;
  parentRunId: string;
  seedCandidateId: string;
  candidateName: string;
  sourceQuestion: string;
  sourceDateRange: { start: string; end: string };
  summary: string;
  initialReason?: string;
};

export type QuantResearchFollowUp = 'stop_after_run' | 'one_train_only_follow_up';

const modeCopy: Array<[QuantResearchMode, string, string]> = [
  ['ask', 'Ask', 'Read-only research answer'],
  ['plan', 'Plan first', 'Prepare a reviewable plan before any experiment runs'],
  ['auto_research', 'Approved workflow', 'Run the bounded workflow after the plan has been approved'],
];

const modeCommand: Record<QuantResearchMode, QuantCommand> = {
  ask: 'ask', plan: 'generate_plan', auto_research: 'start_auto_research',
};

export function quantDatasetReadyForAutoResearch(dataset: DatasetSnapshot): boolean {
  if (!dataset.researchEligible) return false;
  return dataset.contract === 'market-v2' ? dataset.quality.status === 'accepted' : dataset.quality?.status !== 'blocked';
}

function datasetMarket(dataset: DatasetSnapshot): string {
  if (dataset.contract === 'market-v2') return dataset.marketCalendar === '24x7' ? '24x7 market' : 'Market data';
  if (dataset.source?.kind === 'provider_fetch' && dataset.source.providerId === 'binance_spot') return 'Crypto spot';
  if (dataset.source?.marketCalendar === 'XNAS' || dataset.source?.marketCalendar === 'XNYS') return 'US equity';
  return 'Imported market data';
}

function uniqueDatasets(current: DatasetSnapshot, catalog: DatasetSnapshot[]): DatasetSnapshot[] {
  return [...new Map([current, ...catalog].map((dataset) => [dataset.id, dataset])).values()];
}

const intervalMilliseconds: Record<DatasetSnapshot['interval'], number> = {
  '1h': 60 * 60 * 1_000,
  '4h': 4 * 60 * 60 * 1_000,
  '1D': 24 * 60 * 60 * 1_000,
};

function utcTime(value: string): number | null {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function utcDatetimeLocalValue(value: string): string {
  const parsed = utcTime(value);
  if (parsed === null) return '';
  return new Date(parsed).toISOString().slice(0, 16);
}

function datetimeLocalUtcValue(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const parsed = Date.parse(`${value}:00Z`);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString().replace('.000Z', 'Z') : null;
}

function marketRangeError(dataset: DatasetSnapshot, range: { start: string; end: string }): string | null {
  const start = utcTime(range.start);
  const end = utcTime(range.end);
  const coverageStart = utcTime(dataset.dateRange.start);
  const coverageEnd = utcTime(dataset.dateRange.end);
  if (start === null || end === null || coverageStart === null || coverageEnd === null) return 'Enter valid UTC timestamps.';
  if (start > end) return 'Research start must not be after the end.';
  if (start < coverageStart || end > coverageEnd) return 'Choose a range inside the stored dataset coverage.';
  if (dataset.contract === 'market-v2') {
    const step = intervalMilliseconds[dataset.interval];
    const requiredBars = requiredMarketResearchBars(dataset.interval, dataset.periodsPerYear);
    if ((start - coverageStart) % step !== 0 || (end - coverageStart) % step !== 0) return `Align both bounds to the stored ${dataset.interval} timestamps.`;
    if (Math.floor((end - start) / step) + 1 < requiredBars) {
      return `Choose at least ${marketResearchRequirementLabel(dataset.interval, dataset.periodsPerYear)} for autonomous research.`;
    }
  }
  return null;
}

const objectiveTemplates = [
  ['Trend & risk', (symbol: string) => `Test whether a daily ${symbol} trend strategy improves risk-adjusted return and drawdown versus buy and hold.`],
  ['Mean reversion', (symbol: string) => `Evaluate whether short-horizon mean reversion in ${symbol} remains robust across walk-forward periods.`],
  ['Regime test', (symbol: string) => `Compare ${symbol} strategy performance across trend and volatility regimes, prioritizing stable out-of-sample results.`],
] as const;

export function QuantGoalComposer({ api, snapshot, selectedDataset = snapshot.dataset, initialMode = 'plan', initialGoal = snapshot.project.goal, large = false, busy = false, refinement, onCancelRefinement, onSelectDataset, onAddData, onSubmit, onStartNewRun }: {
  api?: QuantApi;
  snapshot: QuantWorkspaceSnapshot;
  selectedDataset?: DatasetSnapshot;
  initialMode?: QuantResearchMode;
  initialGoal?: string;
  large?: boolean;
  busy?: boolean;
  refinement?: QuantRefinementContext | null;
  onCancelRefinement?: () => void;
  onSelectDataset?: (dataset: DatasetSnapshot) => void;
  onAddData?: () => void;
  onSubmit: (command: QuantCommand, payload: Record<string, unknown>) => void;
  onStartNewRun?: (mode: QuantResearchMode, goal: string, dataset: DatasetSnapshot, dateRange: { start: string; end: string }, refinement?: QuantRefinementContext, refinementReason?: string, followUp?: QuantResearchFollowUp) => void;
}) {
  const normalizedInitialMode = large ? 'plan' : initialMode;
  const [mode, setMode] = useState<QuantResearchMode>(normalizedInitialMode);
  const [goal, setGoal] = useState(initialGoal);
  const [catalog, setCatalog] = useState<DatasetSnapshot[]>([]);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState(refinement?.sourceDateRange ?? selectedDataset.dateRange);
  const [refinementReason, setRefinementReason] = useState(refinement?.initialReason ?? '');
  const [followUp, setFollowUp] = useState<QuantResearchFollowUp>('stop_after_run');
  useEffect(() => { setMode(large ? 'plan' : initialMode); }, [initialMode, large]);
  useEffect(() => { setGoal(initialGoal); }, [initialGoal]);
  useEffect(() => {
    setDateRange(refinement?.sourceDateRange ?? selectedDataset.dateRange);
  }, [selectedDataset.id, selectedDataset.dateRange.start, selectedDataset.dateRange.end, refinement?.parentRunId, refinement?.sourceDateRange?.start, refinement?.sourceDateRange?.end]);
  useEffect(() => { setRefinementReason(refinement?.initialReason ?? ''); }, [refinement?.parentRunId, refinement?.seedCandidateId, refinement?.initialReason]);
  useEffect(() => {
    if (!large || !api) return;
    let current = true;
    Promise.all([api.listDatasets(), api.listMarketDatasets()]).then(([legacy, market]) => {
      if (!current) return;
      const datasets = [...legacy, ...market];
      setCatalog(datasets);
      setCatalogError(null);
      const canonicalSelection = datasets.find((dataset) => dataset.id === selectedDataset.id);
      if (canonicalSelection) onSelectDataset?.(canonicalSelection);
    }).catch(() => { if (current) setCatalogError('Dataset catalog could not be loaded. The current dataset remains available.'); });
    return () => { current = false; };
  }, [api, large, onSelectDataset, selectedDataset.id]);
  const datasets = useMemo(() => uniqueDatasets(selectedDataset, catalog), [catalog, selectedDataset]);
  const command = modeCommand[mode];
  const effectiveGoal = goal;
  const legal = snapshot.composerLegalCommands.includes(command) || snapshot.run.legalCommands.includes(command);
  const createsNewRun = large && Boolean(onStartNewRun);
  const datasetReady = quantDatasetReadyForAutoResearch(selectedDataset);
  const availableModes = large ? modeCopy.filter(([id]) => id === 'plan') : modeCopy;
  const selectedModeDescription = modeCopy.find(([id]) => id === mode)?.[2] ?? '';
  const rangeError = marketRangeError(selectedDataset, dateRange);
  const rangeValid = rangeError === null;
  const marketRequirementLabel = selectedDataset.contract === 'market-v2'
    ? marketResearchRequirementLabel(selectedDataset.interval, selectedDataset.periodsPerYear)
    : null;
  const datasetState = selectedDataset.quality
    ? selectedDataset.quality.status === 'passed' || selectedDataset.quality.status === 'accepted'
      ? 'Quality verified'
      : selectedDataset.quality.status === 'warning'
        ? 'Quality warning'
        : 'Quality blocked'
    : datasetReady
      ? 'Minimum history met'
      : 'Insufficient history';
  const datasetStateClass = selectedDataset.quality?.status === 'passed' || selectedDataset.quality?.status === 'accepted'
    ? 'is-ready'
    : selectedDataset.quality?.status === 'blocked' || !datasetReady
      ? 'is-blocked'
      : undefined;
  const canSubmit = !busy && Boolean(effectiveGoal.trim()) && rangeValid && Boolean(!refinement || refinementReason.trim()) && (legal || createsNewRun) && ((mode !== 'auto_research' && !createsNewRun) || datasetReady);
  const unavailableCopy = (mode === 'auto_research' || createsNewRun)
    ? selectedDataset.quality?.status === 'blocked'
      ? 'A new research run is blocked by data-quality checks for the selected dataset.'
      : !datasetReady
      ? selectedDataset.contract === 'market-v2'
        ? `This market dataset is stored and previewable, but a new research run requires at least ${marketRequirementLabel} with contiguous UTC coverage.`
        : 'A new research run requires at least 252 ordered daily bars in the selected dataset.'
      : createsNewRun
        ? refinement
          ? 'Submitting creates an independent run in the source project with this dataset.'
          : 'Submitting creates a new API-owned Project and immutable Run with this dataset.'
        : 'The approved workflow becomes available after the plan is reviewed.'
    : snapshot.run.state === 'running_experiments'
      ? 'This run already has an approved plan. Review the plan before Qurio runs experiments.'
      : snapshot.run.state === 'completed'
        ? 'This attempt is complete and immutable. Start a new run to investigate another goal.'
        : `${mode === 'ask' ? 'Ask' : 'Plan'} is not legal in the current API-owned run state.`;
  const submit = () => {
    if (!canSubmit) return;
    if (createsNewRun && onStartNewRun) {
      const enabledFollowUp = selectedDataset.contract === 'market-v2'
        && mode === 'auto_research'
        && !refinement
        && followUp === 'one_train_only_follow_up'
        ? followUp
        : undefined;
      if (enabledFollowUp) {
        onStartNewRun(mode, goal.trim(), selectedDataset, dateRange, undefined, undefined, enabledFollowUp);
      } else {
        onStartNewRun(mode, goal.trim(), selectedDataset, dateRange, refinement ?? undefined, refinementReason.trim() || undefined);
      }
      return;
    }
    onSubmit(command, {
      goal: goal.trim(),
      symbol: selectedDataset.symbol,
      interval: selectedDataset.interval,
      dateRange,
      benchmark: `${selectedDataset.symbol} Buy and Hold`,
      ...(mode === 'auto_research' ? { dataset_id: selectedDataset.id } : {}),
    });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); submit(); }
  };

  return <section className={`quant-composer${large ? ' is-large' : ''}${refinement ? ' is-refinement' : ''}`} aria-label={large ? 'Research setup' : undefined} aria-labelledby={large ? undefined : 'quant-composer-title'} aria-busy={busy}>
    {!large && <div className="quant-composer-heading"><div><p className="quant-eyebrow">Goal Composer</p><h2 id="quant-composer-title">What market outcome should Qurio investigate?</h2></div><div className="quant-mode-switch" role="group" aria-label="Research mode">{availableModes.map(([id, label, description]) => <button key={id} disabled={busy} aria-pressed={mode === id} title={description} onClick={() => setMode(id)}>{label}</button>)}</div></div>}
    <div className="quant-composer-form">
      {large ? <>
        {refinement && <section className="quant-refinement-context" aria-labelledby="quant-refinement-title">
          <header><div><span>Next research version</span><h2 id="quant-refinement-title">Refine one bounded change</h2><p>Keep the retained research question and evidence visible while changing one testable assumption.</p></div><Button onClick={onCancelRefinement}>Cancel refinement</Button></header>
          <dl>
            <div><dt>Retained source</dt><dd><strong>{refinement.candidateName}</strong><span>{refinement.sourceQuestion}</span></dd></div>
            <div><dt>Evidence basis</dt><dd>{refinement.summary}</dd></div>
            <div><dt>What stays pinned</dt><dd>{selectedDataset.symbol} · {selectedDataset.interval} · source dataset identity, execution costs and validation policy</dd></div>
          </dl>
          <p>The research range remains editable inside stored coverage. The source version and its evidence will not change.</p>
        </section>}
        {refinement && <section className="quant-setup-section quant-refinement-change" aria-labelledby="quant-refinement-reason"><div className="quant-composer-field-heading"><span id="quant-refinement-reason">Proposed change</span><small>{refinementReason.length}/2,000</small></div><label className="quant-goal-field"><span className="sr-only">Refinement reason</span><textarea aria-label="Refinement reason" value={refinementReason} maxLength={2000} placeholder="Example: Test a slower trend filter to reduce the failed holdout drawdown." disabled={busy} onChange={(event) => setRefinementReason(event.target.value)} rows={3} /></label><p>{refinementReason.trim() ? 'Qurio will turn this bounded change into a new reviewable plan.' : 'Name one change and the weakness it should address before continuing.'}</p></section>}
        {!refinement && <section className="quant-setup-section quant-research-prompt" aria-labelledby="quant-research-objective"><div className="quant-composer-field-heading"><span id="quant-research-objective">What should Qurio investigate?</span><small>{goal.length}/2,000</small></div><label className="quant-goal-field"><span className="sr-only">Research objective</span><textarea aria-label="Research goal" aria-describedby="quant-objective-help" value={effectiveGoal} maxLength={2000} placeholder={`Example: Test whether a ${selectedDataset.interval} ${selectedDataset.symbol} trend signal improves drawdown without degrading out-of-sample return.`} disabled={busy} onChange={(event) => setGoal(event.target.value)} onKeyDown={onKeyDown} rows={5} /></label><p id="quant-objective-help">Describe the market behavior, comparison and risk outcome. Qurio will turn it into a plan for approval.</p><div className="quant-objective-templates" aria-label="Research objective templates">{objectiveTemplates.map(([label, template]) => <button type="button" key={label} disabled={busy} onClick={() => setGoal(template(selectedDataset.symbol).replace('daily', selectedDataset.interval))}>{label}</button>)}</div></section>}
        <section className="quant-setup-section" aria-labelledby="quant-research-data"><div className="quant-composer-field-heading"><span id="quant-research-data">Research data</span>{!refinement && <Button disabled={busy} onClick={onAddData}>Add data</Button>}</div><label className="quant-dataset-select"><span>Dataset</span><select aria-label="Research dataset" disabled={busy || Boolean(refinement)} value={selectedDataset.id} onChange={(event) => { const next = datasets.find((dataset) => dataset.id === event.target.value); if (next) onSelectDataset?.(next); }}>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id} disabled={!dataset.researchEligible}>{dataset.symbol} · {dataset.name} · {dataset.interval} · {dataset.dateRange.start} – {dataset.dateRange.end}{dataset.researchEligible ? '' : ' · unavailable'}</option>)}</select></label><div className="quant-data-context"><dl><div><dt>Market</dt><dd>{datasetMarket(selectedDataset)}</dd></div><div><dt>Source</dt><dd>{selectedDataset.source?.sourceName ?? 'Bundled fixture'}</dd></div><div><dt>Interval</dt><dd>{selectedDataset.interval}</dd></div><div><dt>Available coverage</dt><dd>{selectedDataset.dateRange.start} – {selectedDataset.dateRange.end}</dd></div>{selectedDataset.contract === 'market-v2' && <div><dt>Annualization</dt><dd>{selectedDataset.periodsPerYear?.toLocaleString() ?? '—'} periods/year</dd></div>}</dl><span className={datasetStateClass}>{datasetState}</span></div>{selectedDataset.authenticity === 'synthetic_fixture' && <p className="quant-inline-note"><strong>Offline demo data.</strong> These synthetic SPY bars demonstrate the research workflow; they are not live market evidence.</p>}{refinement && <p className="quant-inline-note">Refinements keep the source dataset and may test another valid research window inside its coverage.</p>}{catalogError && <p className="quant-field-error" role="status">{catalogError}</p>}</section>
        {refinement && <section className="quant-setup-section" aria-labelledby="quant-research-objective"><div className="quant-composer-field-heading"><span id="quant-research-objective">Research objective</span><small>{goal.length}/2,000</small></div><label className="quant-goal-field"><span className="sr-only">Research objective</span><textarea aria-label="Research goal" aria-describedby="quant-objective-help" value={effectiveGoal} maxLength={2000} placeholder={`Example: Test whether a ${selectedDataset.interval} ${selectedDataset.symbol} trend signal improves drawdown without degrading out-of-sample return.`} disabled={busy} onChange={(event) => setGoal(event.target.value)} onKeyDown={onKeyDown} rows={4} /></label><p id="quant-objective-help">State the market behavior, comparison and risk outcome you want the Agent to test.</p><div className="quant-objective-templates" aria-label="Research objective templates">{objectiveTemplates.map(([label, template]) => <button type="button" key={label} disabled={busy} onClick={() => setGoal(template(selectedDataset.symbol).replace('daily', selectedDataset.interval))}>{label}</button>)}</div></section>}
        <fieldset className="quant-composer-mode-field" disabled={busy}><legend>Research mode</legend><div className="quant-mode-switch" role="group" aria-label="Research mode">{availableModes.map(([id, label, description]) => <button type="button" key={id} aria-pressed={mode === id} title={description} onClick={() => setMode(id)}>{label}</button>)}</div><p>{selectedModeDescription}</p></fieldset>
        {selectedDataset.contract === 'market-v2' && mode === 'auto_research' && !refinement && <fieldset className="quant-composer-mode-field" disabled={busy}><legend>After this run</legend><div className="quant-mode-switch" role="group" aria-label="Research follow-up"><button type="button" aria-pressed={followUp === 'stop_after_run'} onClick={() => setFollowUp('stop_after_run')}>Stop for review</button><button type="button" aria-pressed={followUp === 'one_train_only_follow_up'} onClick={() => setFollowUp('one_train_only_follow_up')}>Allow one follow-up</button></div><p>{followUp === 'one_train_only_follow_up' ? 'The Agent may precommit one independent refinement from the final training comparison, then stops.' : 'Finish this run and return for review before creating another version.'}</p></fieldset>}
        <fieldset className="quant-research-range" disabled={busy}><legend>Research range</legend>{selectedDataset.contract === 'market-v2' ? <div><label><span>Start UTC</span><input type="datetime-local" step={selectedDataset.interval === '1h' ? 3600 : selectedDataset.interval === '4h' ? 14400 : 86400} aria-label="Research start UTC" min={utcDatetimeLocalValue(selectedDataset.dateRange.start)} max={utcDatetimeLocalValue(dateRange.end)} value={utcDatetimeLocalValue(dateRange.start)} onChange={(event) => { const value = datetimeLocalUtcValue(event.target.value); if (value) setDateRange((current) => ({ ...current, start: value })); }} /></label><label><span>End UTC</span><input type="datetime-local" step={selectedDataset.interval === '1h' ? 3600 : selectedDataset.interval === '4h' ? 14400 : 86400} aria-label="Research end UTC" min={utcDatetimeLocalValue(dateRange.start)} max={utcDatetimeLocalValue(selectedDataset.dateRange.end)} value={utcDatetimeLocalValue(dateRange.end)} onChange={(event) => { const value = datetimeLocalUtcValue(event.target.value); if (value) setDateRange((current) => ({ ...current, end: value })); }} /></label></div> : <div><label><span>Start</span><input type="date" aria-label="Research start date" min={selectedDataset.dateRange.start} max={dateRange.end} value={dateRange.start} onChange={(event) => setDateRange((current) => ({ ...current, start: event.target.value }))} /></label><label><span>End</span><input type="date" aria-label="Research end date" min={dateRange.start} max={selectedDataset.dateRange.end} value={dateRange.end} onChange={(event) => setDateRange((current) => ({ ...current, end: event.target.value }))} /></label></div>}<p className={rangeValid ? undefined : 'quant-field-error'}>{rangeValid ? selectedDataset.contract === 'market-v2' ? `UTC bounds are pinned to stored ${selectedDataset.interval} bars; the server requires at least ${marketRequirementLabel}.` : 'The API will pin this range and verify that it contains at least 252 daily bars.' : rangeError}</p></fieldset>
        <details className="quant-composer-advanced"><summary>Execution limits</summary><dl><div><dt>Agent iterations</dt><dd>{snapshot.run.maxAgentIterations}</dd></div><div><dt>Experiment budget</dt><dd>{snapshot.limits.maxExperiments}</dd></div><div><dt>Repair attempts</dt><dd>{snapshot.limits.maxRepairAttempts}</dd></div><div><dt>Validation</dt><dd>Sealed holdout</dd></div></dl></details>
        <div className="quant-composer-actions"><span className={datasetReady && rangeValid ? 'is-ready' : 'is-blocked'}>{busy ? 'Generating plan…' : !effectiveGoal.trim() ? 'Enter a research objective to continue.' : refinement && !refinementReason.trim() ? 'Explain what should change before continuing.' : !rangeValid ? 'Choose a valid research range.' : datasetReady ? `${selectedDataset.symbol} · ${dateRange.start} to ${dateRange.end}` : unavailableCopy}</span><div><Button disabled={busy || (!goal && dateRange.start === selectedDataset.dateRange.start && dateRange.end === selectedDataset.dateRange.end)} onClick={() => { setGoal(initialGoal); setDateRange(selectedDataset.dateRange); setRefinementReason(refinement?.initialReason ?? ''); }}>Reset</Button><Button className="primary quant-submit" disabled={!canSubmit} onClick={submit}>{busy ? 'Generating plan…' : refinement ? 'Generate next plan' : 'Generate plan'}</Button></div></div>
      </> : <>
        <label className="quant-goal-field"><span>Research goal</span><textarea aria-label="Research goal" value={effectiveGoal} maxLength={2000} disabled={busy} onChange={(event) => setGoal(event.target.value)} onKeyDown={onKeyDown} rows={2} /></label>
        <label><span>Asset</span><select value={selectedDataset.symbol} disabled aria-label="Asset"><option>{selectedDataset.symbol}</option></select></label>
        <label><span>Interval</span><select value={selectedDataset.interval} disabled aria-label="Interval"><option>{selectedDataset.interval}</option></select></label>
        <label><span>Date range</span><input value={`${selectedDataset.dateRange.start} → ${selectedDataset.dateRange.end}`} readOnly /></label>
        <Button className="primary quant-submit" disabled={!canSubmit} onClick={submit}>{busy ? 'Submitting…' : createsNewRun ? 'Start new run' : mode === 'ask' ? 'Ask' : mode === 'plan' ? 'Generate plan' : 'Start research'}</Button>
      </>}
    </div>
    {!large && <div className="quant-composer-foot"><span>Dataset · {selectedDataset.name}</span><span>Benchmark · {selectedDataset.symbol} Buy and Hold</span><span>{snapshot.limits.maxExperiments} experiments · {snapshot.limits.maxRepairAttempts} repairs · {snapshot.limits.maxRuntimeMinutes} min</span><span>Internet disabled · Python disabled · Paper trading disabled</span><Kbd>⌘ Enter</Kbd></div>}
    {!large && ((!legal && !createsNewRun) || ((mode === 'auto_research' || createsNewRun) && !datasetReady) || createsNewRun) && <p className="quant-inline-note" role="status">{unavailableCopy}</p>}
  </section>;
}
