import { useEffect, useRef } from 'react';
import { Badge, Status } from '@glint/ui';
import type { QuantArtifact, QuantCandidate, QuantWorkspaceSnapshot } from '../../quant-domain';
import { quantAuthenticityLabel } from '../../quant-domain';
import type { QuantActivityPresentation, QuantWorkspacePresentation } from './quant-presentation';
import type { QuantMarketInspectTarget } from './QuantMarketWorkspace';

export type QuantInspectTarget =
  | { kind: 'run' }
  | { kind: 'event'; event: QuantActivityPresentation }
  | { kind: 'artifact'; artifact: QuantArtifact }
  | { kind: 'candidate'; candidate: QuantCandidate }
  | { kind: 'dataset' }
  | { kind: 'report' }
  | QuantMarketInspectTarget;

export function QuantInspector({ snapshot, presentation, target, onClose }: {
  snapshot: QuantWorkspaceSnapshot;
  presentation: QuantWorkspacePresentation;
  target: QuantInspectTarget;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, []);
  const title = target.kind === 'run' ? 'Run' : target.kind === 'event' ? target.event.title : target.kind === 'artifact' ? target.artifact.title : target.kind === 'candidate' ? target.candidate.name : target.kind === 'dataset' ? 'Dataset Snapshot' : target.kind === 'report' ? 'Research Report' : target.title;

  return <div className="quant-inspector-layer" onKeyDown={(event) => {
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
    if (event.key !== 'Tab' || !dialogRef.current) return;
    const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), summary, [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }}>
    <button className="quant-inspector-scrim" aria-label="Close Inspector" onClick={onClose} />
    <aside ref={dialogRef} className="quant-inspector" role="dialog" aria-modal="true" aria-labelledby="quant-inspector-title">
      <header><div><p className="quant-eyebrow">Inspector</p><h2 id="quant-inspector-title">{title}</h2></div><button ref={closeRef} className="quant-close" aria-label="Close Inspector" onClick={onClose}>×</button></header>
      <Badge tone="warning">{quantAuthenticityLabel(snapshot.authenticity)}</Badge>
      {target.kind === 'run' && <><dl><dt>State</dt><dd><Status tone={presentation.statusTone}>{presentation.statusLabel}</Status></dd><dt>Attempt</dt><dd>{snapshot.run.attemptNumber}</dd><dt>Mode</dt><dd>Auto Research</dd><dt>Current step</dt><dd>{snapshot.plan.find((step) => step.id === snapshot.run.currentStepId)?.title}</dd><dt>Experiments</dt><dd>{snapshot.run.usedExperiments} recorded · max {snapshot.limits.maxExperiments}</dd><dt>Repairs</dt><dd>{snapshot.run.usedRepairAttempts} recorded · max {snapshot.limits.maxRepairAttempts}</dd><dt>Runtime limit</dt><dd>{snapshot.limits.maxRuntimeMinutes} min</dd><dt>Network</dt><dd>Disabled</dd><dt>Python</dt><dd>Disabled</dd><dt>Paper trading</dt><dd>Disabled</dd></dl><details><summary>Advanced</summary><dl><dt>Run ID</dt><dd><code>{snapshot.run.id}</code></dd><dt>Row version</dt><dd>{snapshot.run.rowVersion}</dd><dt>Latest sequence</dt><dd>{snapshot.run.latestSequence}</dd><dt>Trace reference</dt><dd><code>{snapshot.run.traceRef}</code></dd><dt>Scope version</dt><dd>{snapshot.scope.version}</dd><dt>Dataset digest</dt><dd><code>{snapshot.dataset.digest}</code></dd></dl></details></>}
      {target.kind === 'event' && <><dl><dt>Actor</dt><dd>{target.event.actorLabel}</dd><dt>Timestamp</dt><dd>{target.event.timestamp}</dd><dt>Artifact</dt><dd>{target.event.artifactId ? 'Retained artifact available' : 'None linked'}</dd></dl><details><summary>Advanced event</summary><dl><dt>Event name</dt><dd><code>{target.event.advanced.eventType}</code></dd><dt>Sequence</dt><dd>{target.event.advanced.sequence}</dd><dt>Safe payload</dt><dd>{target.event.advanced.safeSummary}</dd></dl></details></>}
      {target.kind === 'artifact' && <><p>{target.artifact.summary}</p><dl><dt>Type</dt><dd>{target.artifact.type}</dd><dt>Status</dt><dd>{target.artifact.status}</dd><dt>Origin</dt><dd>{target.artifact.origin}</dd><dt>Related</dt><dd>{target.artifact.relatedLabel}</dd></dl><details><summary>Advanced provenance</summary><dl><dt>Artifact ID</dt><dd><code>{target.artifact.id}</code></dd><dt>Digest</dt><dd><code>{target.artifact.digest}</code></dd></dl></details></>}
      {target.kind === 'candidate' && <><p>{target.candidate.verdictReason}</p><dl><dt>Verdict</dt><dd>{target.candidate.verdict}</dd><dt>Return</dt><dd>{target.candidate.metrics.annualizedReturn}%</dd><dt>Drawdown</dt><dd>{target.candidate.metrics.maxDrawdown}%</dd><dt>Sharpe</dt><dd>{target.candidate.metrics.sharpe}</dd><dt>Trades</dt><dd>{target.candidate.metrics.trades}</dd></dl><details><summary>Advanced</summary><dl><dt>Candidate ID</dt><dd><code>{target.candidate.id}</code></dd><dt>Strategy version</dt><dd><code>{target.candidate.strategySpecVersion}</code></dd></dl></details></>}
      {target.kind === 'dataset' && <><dl><dt>Name</dt><dd>{snapshot.dataset.name}</dd><dt>Symbol</dt><dd>{snapshot.dataset.symbol}</dd><dt>Interval</dt><dd>{snapshot.dataset.interval}</dd><dt>Date range</dt><dd>{snapshot.dataset.dateRange.start} – {snapshot.dataset.dateRange.end}</dd><dt>Bars</dt><dd>{snapshot.dataset.barCount.toLocaleString()}</dd></dl><details><summary>Advanced provenance</summary><dl><dt>Snapshot ID</dt><dd><code>{snapshot.dataset.id}</code></dd><dt>Schema</dt><dd><code>{snapshot.dataset.schemaVersion}</code></dd><dt>Parser</dt><dd><code>{snapshot.dataset.parserVersion}</code></dd><dt>Digest</dt><dd><code>{snapshot.dataset.digest}</code></dd></dl></details></>}
      {target.kind === 'report' && <><p>{snapshot.report.conclusion}</p><h3>Proposed next step</h3><p>{snapshot.report.proposedNextStep}</p><h3>Limitations</h3><ul>{snapshot.report.limitations.map((item) => <li key={item}>{item}</li>)}</ul><p className="quant-disclaimer">{snapshot.report.disclaimer}</p><details><summary>Audit and reproduction metadata</summary><dl><dt>Report ID</dt><dd><code>{snapshot.report.id}</code></dd><dt>Validator</dt><dd><code>{snapshot.report.validatorVersion}</code></dd><dt>Generation</dt><dd>{snapshot.report.generationMethod}</dd><dt>Review</dt><dd>{snapshot.report.humanReviewStatus}</dd></dl></details></>}
      {target.kind === 'market_event' && <><dl><dt>Marker</dt><dd>{target.bar.marker}</dd><dt>Date</dt><dd>{target.bar.date}</dd><dt>Open</dt><dd>{target.bar.open}</dd><dt>High</dt><dd>{target.bar.high}</dd><dt>Low</dt><dd>{target.bar.low}</dd><dt>Close</dt><dd>{target.bar.close}</dd><dt>Volume</dt><dd>{target.bar.volume.toLocaleString()}</dd></dl><p>This event marker is part of the synthetic fixture and is not a live news or market-data retrieval.</p></>}
    </aside>
  </div>;
}
