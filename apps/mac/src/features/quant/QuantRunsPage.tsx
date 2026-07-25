import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button } from '@glint/ui';
import type { QuantApi, QuantProjectHistoryItem, QuantRunHistoryItem } from '../../quant-api';
import type { QuantCandidate, QuantWorkspaceSnapshot } from '../../quant-domain';
import { QuantDecisionGate } from './QuantDecisionGate';
import { QuantEvaluationPath } from './QuantEvaluationPath';
import { presentQuantWorkspace, projectNextResearchProposal, projectQuantRunRelationship, quantRunHistoryMatchesSnapshot, quantRunRelationshipLabel, type QuantEvidenceFocusIntent, type QuantEvidenceFocusResult } from './quant-presentation';

type OutcomeFilter = 'all' | 'active' | 'completed' | 'review' | 'failed_cancelled';
type SortOrder = 'newest' | 'oldest';
type CompareRecord = { status: 'loading' } | { status: 'ready'; snapshot: QuantWorkspaceSnapshot } | { status: 'error'; message: string };

function shortDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}

function projectLabel(name: string) {
  const separator = name.indexOf(' · ');
  return separator > 0 ? name.slice(0, separator) : name;
}

const runStateLabels: Record<string, string> = {
  draft: 'Ready', planning: 'Planning', waiting_plan_approval: 'Plan review', queued: 'Queued', loading_data: 'Verifying dataset',
  generating_candidates: 'Preparing candidates', running_experiments: 'Running experiments', repairing: 'Repairing candidate',
  validating: 'Validating evidence', generating_report: 'Building report', waiting_for_review: 'Review required', completed: 'Completed',
  failed: 'Failed', cancelled: 'Cancelled',
};

function runStateLabel(state: string) {
  return runStateLabels[state] ?? state.replaceAll('_', ' ');
}

function runStateTone(state: string) {
  if (state === 'failed' || state === 'cancelled') return 'danger';
  if (state === 'waiting_plan_approval' || state === 'waiting_for_review') return 'warning';
  if (state === 'completed') return 'complete';
  return 'active';
}

function outcomeForState(state: string): Exclude<OutcomeFilter, 'all'> {
  if (state === 'completed') return 'completed';
  if (state === 'waiting_plan_approval' || state === 'waiting_for_review') return 'review';
  if (state === 'failed' || state === 'cancelled') return 'failed_cancelled';
  return 'active';
}

function selectedCandidate(snapshot: QuantWorkspaceSnapshot): QuantCandidate | undefined {
  const selectedId = snapshot.report?.generalization?.selectedCandidateId;
  return snapshot.candidates.find((candidate) => candidate.id === selectedId)
    ?? snapshot.candidates.find((candidate) => candidate.verdict === 'promising')
    ?? snapshot.candidates[0];
}

function signedPercent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function decimal(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(2);
}

function signedNumber(value: number, digits = 1) {
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;
}

function sameTimeValue(left: string, right: string) {
  const leftTime = Date.parse(left);
  const rightTime = Date.parse(right);
  return Number.isFinite(leftTime) && Number.isFinite(rightTime) ? leftTime === rightTime : left === right;
}

function comparisonDifferences(reference: QuantWorkspaceSnapshot, snapshot: QuantWorkspaceSnapshot) {
  const differences: string[] = [];
  if (snapshot.dataset.id !== reference.dataset.id) differences.push('dataset');
  if (snapshot.dataset.symbol !== reference.dataset.symbol) differences.push('symbol');
  if (snapshot.dataset.interval !== reference.dataset.interval) differences.push('interval');
  if (!sameTimeValue(snapshot.scope.dateRange.start, reference.scope.dateRange.start) || !sameTimeValue(snapshot.scope.dateRange.end, reference.scope.dateRange.end)) differences.push('research range');
  return differences;
}

function versionComparisonSummary(selectedRuns: QuantRunHistoryItem[], runs: QuantRunHistoryItem[], records: Record<string, CompareRecord>) {
  if (selectedRuns.length !== 2) return null;
  const child = selectedRuns.find((run) => {
    const sourceId = projectQuantRunRelationship(run, runs).sourceRunId;
    return sourceId && selectedRuns.some((candidate) => candidate.id === sourceId);
  });
  if (!child) return null;
  const sourceId = projectQuantRunRelationship(child, runs).sourceRunId;
  const source = selectedRuns.find((run) => run.id === sourceId);
  const childRecord = records[child.id];
  const sourceRecord = source ? records[source.id] : undefined;
  if (!source || childRecord?.status !== 'ready' || sourceRecord?.status !== 'ready') return null;
  const childCandidate = selectedCandidate(childRecord.snapshot);
  const sourceCandidate = selectedCandidate(sourceRecord.snapshot);
  if (!childCandidate || !sourceCandidate) return null;
  const differences = comparisonDifferences(sourceRecord.snapshot, childRecord.snapshot);
  const proposal = projectNextResearchProposal(childRecord.snapshot, childCandidate, differences.length ? 'Not directly comparable' : undefined);
  if (differences.length) return {
    verdict: 'Not directly comparable',
    detail: `Different ${differences.join(', ')}. Stored metrics are shown independently below.`,
    reason: child.refinementReason ?? 'No refinement reason retained.',
    strategy: `${sourceCandidate.name} → ${childCandidate.name}`,
    metrics: null,
    refinementSource: childRecord.snapshot,
    candidateId: childCandidate.id,
    proposal,
  };
  const deltas = {
    annualReturn: childCandidate.metrics.annualizedReturn - sourceCandidate.metrics.annualizedReturn,
    sharpe: childCandidate.metrics.sharpe - sourceCandidate.metrics.sharpe,
    drawdown: childCandidate.metrics.maxDrawdown - sourceCandidate.metrics.maxDrawdown,
    trades: childCandidate.metrics.trades - sourceCandidate.metrics.trades,
  };
  const directional = [deltas.annualReturn, deltas.sharpe, deltas.drawdown];
  const improved = directional.filter((value) => value > 0.0001).length;
  const weakened = directional.filter((value) => value < -0.0001).length;
  const verdict = improved === 0 && weakened === 0 ? 'No material change' : improved >= 2 && weakened === 0 ? 'Improved' : weakened >= 2 && improved === 0 ? 'Weaker' : 'Mixed';
  return {
    verdict,
    detail: 'Same dataset, symbol, interval and research range. Positive drawdown delta means a shallower loss.',
    reason: child.refinementReason ?? 'No refinement reason retained.',
    strategy: `${sourceCandidate.name} → ${childCandidate.name}`,
    metrics: `Annual return ${signedNumber(deltas.annualReturn)} pts · Sharpe ${signedNumber(deltas.sharpe, 2)} · Max drawdown ${signedNumber(deltas.drawdown)} pts · Trades ${signedNumber(deltas.trades, 0)}`,
    refinementSource: childRecord.snapshot,
    candidateId: childCandidate.id,
    proposal: projectNextResearchProposal(childRecord.snapshot, childCandidate, verdict),
  };
}

function RunsComparison({ selectedIds, runs, projectNames, records, onClose, onRetry, onRefine }: {
  selectedIds: string[];
  runs: QuantRunHistoryItem[];
  projectNames: Map<string, string>;
  records: Record<string, CompareRecord>;
  onClose: () => void;
  onRetry: (runId: string) => void;
  onRefine?: (source: QuantWorkspaceSnapshot, candidateId: string, reason: string) => void;
}) {
  const selectedRuns = selectedIds.map((id) => runs.find((run) => run.id === id)).filter((run): run is QuantRunHistoryItem => Boolean(run));
  const reference = selectedIds.map((id) => records[id]).find((record): record is { status: 'ready'; snapshot: QuantWorkspaceSnapshot } => record?.status === 'ready')?.snapshot;
  const readySnapshots = selectedIds.flatMap((id) => records[id]?.status === 'ready' ? [records[id].snapshot] : []);
  const hasDifferences = Boolean(reference && readySnapshots.some((item) => comparisonDifferences(reference, item).length > 0));
  const versionSummary = versionComparisonSummary(selectedRuns, runs, records);
  const canRefine = versionSummary?.proposal?.recommendation === 'refine';
  const resultCell = (run: QuantRunHistoryItem, render: (item: QuantWorkspaceSnapshot) => ReactNode, className?: string) => {
    const record = records[run.id];
    if (!record || record.status === 'loading') return <td key={run.id} className={className}><span className="quant-compare-pending">Loading stored snapshot…</span></td>;
    if (record.status === 'error') return <td key={run.id} className={className}><span className="quant-compare-failure">{record.message}</span><Button onClick={() => onRetry(run.id)}>Retry</Button></td>;
    return <td key={run.id} className={className}>{render(record.snapshot)}</td>;
  };

  return <section className="quant-runs-compare" aria-labelledby="quant-runs-compare-title">
    <header>
      <div><h2 id="quant-runs-compare-title">Compare research history</h2><p>{selectedIds.length} selected · Metrics are shown from each run’s stored result.</p></div>
      <Button onClick={onClose}>Back to history</Button>
    </header>
    {versionSummary && <section className="quant-version-comparison" aria-label="Research version change"><div><span>Version change</span><strong>{versionSummary.verdict}</strong><p>{versionSummary.detail}</p></div><dl><div><dt>Refinement reason</dt><dd>{versionSummary.reason}</dd></div><div><dt>Selected strategy</dt><dd>{versionSummary.strategy}</dd></div>{versionSummary.metrics && <div><dt>Change vs source</dt><dd>{versionSummary.metrics}</dd></div>}</dl>{onRefine && canRefine && versionSummary.proposal && <div className="quant-version-actions"><Button className="primary" onClick={() => onRefine(versionSummary.refinementSource, versionSummary.candidateId, versionSummary.proposal!.refinementReason)}>Refine from this result</Button><span>Uses the retained candidate and evidence as editable context for a new independent run.</span></div>}</section>}
    {hasDifferences && <p className="quant-compare-notice" role="status"><strong>Comparison context differs.</strong> Dataset, symbol, interval, or research-range differences are identified per row; interpret performance metrics independently.</p>}
    <div className="quant-run-compare-scroll" tabIndex={0} aria-label="Run comparison table, horizontally scrollable">
      <table className="quant-research-table quant-run-compare-table">
        <caption>Stored strategy results for selected historical research runs</caption>
        <thead><tr><th>Metric</th>{selectedRuns.map((run) => <th key={run.id}><strong>{projectLabel(projectNames.get(run.projectId) ?? 'Research project')}</strong><small>{run.question}</small></th>)}</tr></thead>
        <tbody>
          <tr><th scope="row">Comparison context</th>{selectedRuns.map((run) => resultCell(run, (item) => { const differences = reference ? comparisonDifferences(reference, item) : []; return <span className={differences.length ? 'is-warning' : 'is-compatible'}>{differences.length ? `Differs: ${differences.join(', ')}` : 'Comparable context'}</span>; }))}</tr>
          <tr><th scope="row">Dataset</th>{selectedRuns.map((run) => resultCell(run, (item) => <><strong>{item.dataset.name}</strong><small>{item.dataset.symbol} · {item.dataset.interval}</small></>))}</tr>
          <tr><th scope="row">Research range</th>{selectedRuns.map((run) => resultCell(run, (item) => <>{item.scope.dateRange.start}<small>to {item.scope.dateRange.end}</small></>))}</tr>
          <tr><th scope="row">Selected candidate</th>{selectedRuns.map((run) => resultCell(run, (item) => { const candidate = selectedCandidate(item); return candidate ? <><strong>{candidate.name}</strong><small>{candidate.parameters}</small></> : '—'; }))}</tr>
          <tr><th scope="row">Annual return</th>{selectedRuns.map((run) => resultCell(run, (item) => signedPercent(selectedCandidate(item)?.metrics.annualizedReturn), 'is-numeric'))}</tr>
          <tr><th scope="row">Sharpe</th>{selectedRuns.map((run) => resultCell(run, (item) => decimal(selectedCandidate(item)?.metrics.sharpe), 'is-numeric'))}</tr>
          <tr><th scope="row">Max drawdown</th>{selectedRuns.map((run) => resultCell(run, (item) => signedPercent(selectedCandidate(item)?.metrics.maxDrawdown), 'is-numeric'))}</tr>
          <tr><th scope="row">Trades</th>{selectedRuns.map((run) => resultCell(run, (item) => selectedCandidate(item)?.metrics.trades ?? '—', 'is-numeric'))}</tr>
          <tr><th scope="row">Benchmark delta</th>{selectedRuns.map((run) => resultCell(run, (item) => { const candidate = selectedCandidate(item); return signedPercent(candidate && item.benchmark ? candidate.metrics.annualizedReturn - item.benchmark.annualizedReturn : null); }, 'is-numeric'))}</tr>
          <tr><th scope="row">Validation / holdout / outcome</th>{selectedRuns.map((run) => resultCell(run, (item) => { const generalization = item.report?.generalization; const holdout = generalization?.holdout?.candidate.annualizedReturn; return <><strong>{generalization ? generalization.status.replaceAll('_', ' ') : 'Not evaluated'}</strong><small>{holdout == null ? runStateLabel(run.state) : `Holdout ${signedPercent(holdout)} · ${runStateLabel(run.state)}`}</small></>; }))}</tr>
        </tbody>
      </table>
    </div>
  </section>;
}

export function QuantRunsPage({ api, snapshot, openingRunId = null, openRunError = null, onOpenRun, onOpenReport, onStartNewResearch, onRefineFromComparison, evidenceFocus, onEvidenceFocusResolved }: {
  api: QuantApi;
  snapshot: QuantWorkspaceSnapshot;
  openingRunId?: string | null;
  openRunError?: string | null;
  onOpenRun: (runId: string) => Promise<void>;
  onOpenReport: () => void;
  onStartNewResearch: () => void;
  onRefineFromComparison?: (source: QuantWorkspaceSnapshot, candidateId: string, reason: string) => void;
  evidenceFocus?: QuantEvidenceFocusIntent | null;
  onEvidenceFocusResolved?: (id: string, result: QuantEvidenceFocusResult) => void;
}) {
  const [projects, setProjects] = useState<QuantProjectHistoryItem[]>([]);
  const [runs, setRuns] = useState<QuantRunHistoryItem[]>([]);
  const [projectId, setProjectId] = useState('all');
  const [query, setQuery] = useState('');
  const [outcome, setOutcome] = useState<OutcomeFilter>('all');
  const [sortOrder, setSortOrder] = useState<SortOrder>('newest');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [view, setView] = useState<'list' | 'compare'>('list');
  const [compareRecords, setCompareRecords] = useState<Record<string, CompareRecord>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const handledEvidenceFocusId = useRef<string | null>(null);
  const presentation = presentQuantWorkspace(snapshot);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.listProjects()
      .then(async (nextProjects) => {
        const filter = projectId === 'all' ? undefined : projectId;
        const [legacyRuns, marketRuns] = await Promise.all([api.listRuns(filter), api.listMarketRuns(filter)]);
        return { nextProjects, nextRuns: [...legacyRuns, ...marketRuns] };
      })
      .then(({ nextProjects, nextRuns }) => { if (active) { setProjects(nextProjects); setRuns(nextRuns); setError(null); } })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Run history could not be loaded.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, projectId, snapshot.run.id, snapshot.run.state]);

  const projectNames = useMemo(() => new Map(projects.map((item) => [item.id, item.name])), [projects]);
  const visibleRuns = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return runs.filter((run) => {
      const projectName = projectNames.get(run.projectId) ?? '';
      const matchesQuery = !normalizedQuery || `${run.question} ${projectName}`.toLocaleLowerCase().includes(normalizedQuery);
      return matchesQuery && (outcome === 'all' || outcomeForState(run.state) === outcome);
    }).sort((left, right) => {
      const delta = new Date(left.updatedAt || left.createdAt).getTime() - new Date(right.updatedAt || right.createdAt).getTime();
      return sortOrder === 'newest' ? -delta : delta;
    });
  }, [runs, projectNames, query, outcome, sortOrder]);

  const retained = selectedCandidate(snapshot);
  const snapshotHistoryRun = runs.find((run) => run.id === snapshot.run.id && quantRunHistoryMatchesSnapshot(run, snapshot));
  const snapshotRelationship = snapshotHistoryRun
    ? projectQuantRunRelationship(snapshotHistoryRun, runs)
    : null;
  const snapshotRelationshipLabel = snapshotRelationship
    ? quantRunRelationshipLabel(snapshotRelationship)
    : 'Relationship unavailable';
  const sourceRun = snapshotRelationship?.sourceRunId
    ? runs.find((run) => run.id === snapshotRelationship.sourceRunId)
    : undefined;
  const priorAttemptRun = snapshotRelationship?.priorAttemptRunId
    ? runs.find((run) => run.id === snapshotRelationship.priorAttemptRunId)
    : undefined;
  const generalization = snapshot.report?.generalization;
  const reportAvailable = Boolean(snapshot.report);
  const shouldStartAgain = presentation.decision.tone === 'danger' || snapshot.run.state === 'cancelled';
  const decisionAction = reportAvailable
    ? <div className="quant-run-decision-actions">{shouldStartAgain && <Button className="primary" onClick={onStartNewResearch}>New research</Button>}<Button className={shouldStartAgain ? '' : 'primary'} onClick={onOpenReport}>Open decision</Button>{!shouldStartAgain && snapshot.run.state === 'completed' && <Button onClick={onStartNewResearch}>New research</Button>}</div>
    : shouldStartAgain ? <Button className="primary" onClick={onStartNewResearch}>New research</Button> : undefined;

  function toggleComparison(runId: string) {
    setSelectedIds((current) => current.includes(runId) ? current.filter((id) => id !== runId) : current.length < 4 ? [...current, runId] : current);
  }

  const loadComparisonRun = useCallback((runId: string) => {
    setCompareRecords((current) => ({ ...current, [runId]: { status: 'loading' } }));
    void api.getRunWorkspaceSnapshot(runId)
      .then((nextSnapshot) => setCompareRecords((current) => ({ ...current, [runId]: { status: 'ready', snapshot: nextSnapshot } })))
      .catch((reason) => setCompareRecords((current) => ({ ...current, [runId]: { status: 'error', message: reason instanceof Error ? reason.message : 'Stored snapshot could not be loaded.' } })));
  }, [api]);

  function openComparison() {
    if (selectedIds.length < 2) return;
    setView('compare');
    selectedIds.forEach((runId) => {
      if (compareRecords[runId]?.status !== 'ready') loadComparisonRun(runId);
    });
  }

  const compareWithSource = useCallback(() => {
    if (!snapshotHistoryRun || !sourceRun) return;
    const comparisonIds = [sourceRun.id, snapshotHistoryRun.id];
    setSelectedIds(comparisonIds);
    setCompareRecords((current) => ({
      ...current,
      [snapshotHistoryRun.id]: { status: 'ready', snapshot },
    }));
    setView('compare');
    if (compareRecords[sourceRun.id]?.status !== 'ready') loadComparisonRun(sourceRun.id);
  }, [compareRecords, loadComparisonRun, snapshot, snapshotHistoryRun, sourceRun]);

  useEffect(() => {
    if (!evidenceFocus
      || evidenceFocus.destination !== 'runs'
      || evidenceFocus.target !== 'source_comparison'
      || handledEvidenceFocusId.current === evidenceFocus.id) return;
    if (loading) return;
    const evidenceReference = `${evidenceFocus.runId} ↔ ${evidenceFocus.sourceRunId}`;
    const reject = (receipt: string) => {
      handledEvidenceFocusId.current = evidenceFocus.id;
      onEvidenceFocusResolved?.(evidenceFocus.id, { status: 'unavailable', receipt, evidenceReference });
    };
    if (error) {
      reject('Run directory unavailable; source comparison was not opened');
      return;
    }
    if (evidenceFocus.runId !== snapshot.run.id
      || !snapshot.candidates.some((candidate) => candidate.id === evidenceFocus.candidateId)
      || !snapshotHistoryRun
      || !sourceRun
      || sourceRun.id !== evidenceFocus.sourceRunId) {
      reject('Source relationship did not match the validated Run directory');
      return;
    }
    handledEvidenceFocusId.current = evidenceFocus.id;
    compareWithSource();
    onEvidenceFocusResolved?.(evidenceFocus.id, {
      status: 'opened',
      receipt: 'Validated source comparison opened',
      evidenceReference,
    });
  }, [compareWithSource, error, evidenceFocus, loading, onEvidenceFocusResolved, snapshot.candidates, snapshot.run.id, snapshotHistoryRun, sourceRun]);

  const filtersActive = projectId !== 'all' || query.trim() !== '' || outcome !== 'all' || sortOrder !== 'newest';
  if (view === 'compare') return <div className="quant-runs-page"><RunsComparison selectedIds={selectedIds} runs={runs} projectNames={projectNames} records={compareRecords} onClose={() => setView('list')} onRetry={loadComparisonRun} onRefine={onRefineFromComparison} /></div>;

  return <div className="quant-runs-page">
    <header className="quant-runs-heading"><div><h1>Research history</h1><p>Find prior research, compare stored outcomes, or reopen the full result.</p></div></header>
    <section className="quant-runs-tools" aria-label="Run history filters">
      <label className="quant-run-search"><span>Search</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Question or project" /></label>
      <label><span>Project</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="all">All projects</option>{projects.map((project) => <option key={project.id} value={project.id}>{projectLabel(project.name)}</option>)}</select></label>
      <label><span>Outcome</span><select value={outcome} onChange={(event) => setOutcome(event.target.value as OutcomeFilter)}><option value="all">All</option><option value="active">Active</option><option value="completed">Completed</option><option value="review">Needs review</option><option value="failed_cancelled">Failed / Cancelled</option></select></label>
      <label><span>Sort</span><select value={sortOrder} onChange={(event) => setSortOrder(event.target.value as SortOrder)}><option value="newest">Newest</option><option value="oldest">Oldest</option></select></label>
      <Button disabled={!filtersActive} onClick={() => { setProjectId('all'); setQuery(''); setOutcome('all'); setSortOrder('newest'); }}>Clear filters</Button>
    </section>
    {openRunError && <p className="quant-runs-error" role="alert">{openRunError}</p>}
    {error && <p className="quant-runs-error" role="alert">{error}</p>}
    <div className="quant-runs-layout">
      <section className="quant-run-list" aria-label="Research run list">
        <header><div><strong>{loading ? 'Loading…' : `${visibleRuns.length} of ${runs.length} run${runs.length === 1 ? '' : 's'}`}</strong><span>{selectedIds.length} selected</span></div><Button className="primary" disabled={selectedIds.length < 2} onClick={openComparison}>Compare{selectedIds.length ? ` ${selectedIds.length}` : ''}</Button></header>
        <div className="quant-run-list-scroll">
          <table className="quant-research-table quant-runs-table">
            <caption>Searchable and filterable research run history</caption>
            <thead><tr><th className="is-select">Compare</th><th>Question</th><th>Project</th><th>State / outcome</th><th>Mode</th><th>Version / attempt</th><th>Updated</th><th className="is-action">Open</th></tr></thead>
            <tbody>{visibleRuns.map((run) => {
              const isOpening = openingRunId === run.id;
              const isPending = openingRunId !== null;
              const isSelected = selectedIds.includes(run.id);
              const selectionDisabled = !isSelected && selectedIds.length >= 4;
              const relationshipLabel = quantRunRelationshipLabel(projectQuantRunRelationship(run, runs));
              return <tr key={run.id} className={run.id === snapshot.run.id ? 'is-current' : ''}>
                <td className="is-select"><label><input type="checkbox" checked={isSelected} disabled={selectionDisabled} onChange={() => toggleComparison(run.id)} /><span className="quant-visually-hidden">Select {run.question} for comparison</span></label></td>
                <th scope="row"><button className="quant-run-question" aria-busy={isOpening} disabled={isPending} onClick={() => void onOpenRun(run.id)}>{run.question}</button>{run.contract === 'market-v2-public' && <small>{run.symbol} · {run.interval} · {run.researchStartUtc} – {run.researchEndUtc}</small>}</th>
                <td>{projectLabel(projectNames.get(run.projectId) ?? 'Research project')}</td>
                <td><strong className={`is-${runStateTone(run.state)}`}>{isOpening ? 'Opening…' : runStateLabel(run.state)}</strong></td>
                <td>{run.mode === 'auto' ? 'Agent run' : 'Plan first'}{run.contract === 'market-v2-public' && <small>{run.periodsPerYear?.toLocaleString()} periods/year</small>}</td>
                <td className="quant-series-cell">{relationshipLabel}</td>
                <td><time dateTime={run.updatedAt}>{shortDate(run.updatedAt || run.createdAt)}</time></td>
                <td className="is-action"><Button disabled={isPending} aria-busy={isOpening} onClick={() => void onOpenRun(run.id)}>{isOpening ? 'Opening…' : 'Open run'}</Button></td>
              </tr>;
            })}</tbody>
          </table>
          {!loading && runs.length === 0 && <div className="quant-runs-empty"><strong>No research runs yet</strong><p>Start a bounded research question to create the first run.</p><Button onClick={onStartNewResearch}>New research</Button></div>}
          {!loading && runs.length > 0 && visibleRuns.length === 0 && <div className="quant-runs-empty"><strong>No runs match these filters</strong><p>Clear the current search and outcome filters to restore the full history.</p><Button onClick={() => { setProjectId('all'); setQuery(''); setOutcome('all'); setSortOrder('newest'); }}>Clear filters</Button></div>}
        </div>
      </section>
      <article className="quant-run-summary">
        <QuantDecisionGate decision={presentation.decision} action={decisionAction} className="is-run-history" />
        <header><div><span>{runStateLabel(snapshot.run.state)} · {snapshotRelationshipLabel}</span><h2>{projectLabel(snapshot.project.title)}</h2><p>{snapshot.project.goal}</p></div></header>
        {(sourceRun || priorAttemptRun) && <div className="quant-run-series-navigation" aria-label="Related research runs"><span>Research path</span>{sourceRun && <Button disabled={openingRunId !== null} onClick={compareWithSource}>Compare with source</Button>}{sourceRun && <Button disabled={openingRunId !== null} onClick={() => void onOpenRun(sourceRun.id)}>Open source version</Button>}{priorAttemptRun && <Button disabled={openingRunId !== null} onClick={() => void onOpenRun(priorAttemptRun.id)}>Open prior attempt</Button>}</div>}
        <dl className="quant-run-summary-metrics"><div><dt>Training annual return</dt><dd>{signedPercent(retained?.metrics.annualizedReturn)}</dd></div><div><dt>Training max drawdown</dt><dd>{signedPercent(retained?.metrics.maxDrawdown)}</dd></div><div><dt>Walk-forward median</dt><dd>{signedPercent(snapshot.report?.walkForward?.aggregate.candidateMedianReturn)}</dd></div><div><dt>Holdout annual return</dt><dd className={generalization?.status === 'fail' ? 'is-danger' : ''}>{signedPercent(generalization?.holdout?.candidate.annualizedReturn)}</dd></div></dl>
        {retained && <div className="quant-run-candidate"><span>Selected candidate</span><strong>{retained.name}</strong><small>{retained.parameters}</small></div>}
        <QuantEvaluationPath snapshot={snapshot} />
        <details className="quant-run-audit"><summary>Run audit record</summary><dl className="quant-run-summary-meta"><div><dt>Run</dt><dd><code>{snapshot.run.id}</code></dd></div><div><dt>Provider</dt><dd>{snapshot.run.provider}{snapshot.run.model ? ` · ${snapshot.run.model}` : ''}</dd></div><div><dt>Dataset</dt><dd>{snapshot.dataset.symbol} · {snapshot.dataset.interval} · {snapshot.dataset.barCount.toLocaleString()} bars</dd></div><div><dt>Trace</dt><dd><code>{snapshot.run.traceRef}</code></dd></div></dl></details>
      </article>
    </div>
  </div>;
}
