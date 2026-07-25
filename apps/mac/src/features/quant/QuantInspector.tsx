import { Fragment, useEffect, useRef } from 'react';
import { Badge, Status } from '@glint/ui';
import type { DatasetSnapshot, QuantArtifact, QuantCandidate, QuantWorkspaceSnapshot } from '../../quant-domain';
import { quantAuthenticityLabel, quantResearchModeLabel } from '../../quant-domain';
import type { QuantActivityPresentation, QuantWorkspacePresentation } from './quant-presentation';
import type { QuantMarketInspectTarget } from './QuantMarketWorkspace';

export type QuantInspectTarget =
  | { kind: 'run' }
  | { kind: 'event'; event: QuantActivityPresentation }
  | { kind: 'artifact'; artifact: QuantArtifact }
  | { kind: 'candidate'; candidate: QuantCandidate }
  | { kind: 'dataset'; dataset: DatasetSnapshot }
  | { kind: 'report' }
  | QuantMarketInspectTarget;

function DatasetInspector({ dataset }: { dataset: DatasetSnapshot }) {
  if (dataset.contract === 'market-v2') {
    return <>
      <dl><dt>Name</dt><dd>{dataset.name}</dd><dt>Symbol</dt><dd>{dataset.symbol}</dd><dt>Interval</dt><dd>{dataset.interval}</dd><dt>UTC range</dt><dd>{dataset.dateRange.start} – {dataset.dateRange.end}</dd><dt>Bars</dt><dd>{dataset.barCount.toLocaleString()}</dd><dt>Annualization</dt><dd>{dataset.periodsPerYear?.toLocaleString() ?? 'Unavailable'} periods / year</dd><dt>Quality</dt><dd>{dataset.quality.status} · {dataset.quality.cadenceGapCount} cadence gaps</dd></dl>
      <details><summary>Immutable identity</summary><dl><dt>Snapshot ID</dt><dd><code>{dataset.id}</code></dd><dt>Schema</dt><dd><code>{dataset.schemaVersion}</code></dd><dt>Parser</dt><dd><code>{dataset.parserVersion}</code></dd><dt>Digest</dt><dd><code>{dataset.digest}</code></dd><dt>Runtime descriptor</dt><dd><code>{dataset.runtimeDescriptorDigest ?? 'Unavailable'}</code></dd><dt>Sealed split</dt><dd><code>{dataset.sealedSplitDigest ?? 'Unavailable'}</code></dd></dl></details>
      <details><summary>Source record</summary><dl><dt>Source</dt><dd>{dataset.source.sourceName}</dd><dt>Reference</dt><dd>{dataset.source.sourceReference ?? 'Not provided'}</dd><dt>Calendar</dt><dd>{dataset.marketCalendar} · {dataset.marketSession} · {dataset.timeZone}</dd><dt>Retrieved</dt><dd>{dataset.source.retrievedAtUtc ?? 'Not applicable'}</dd><dt>Provider rows</dt><dd>{dataset.source.returnedBarCount?.toLocaleString() ?? 'Not applicable'}</dd><dt>Retained bars</dt><dd>{dataset.source.retainedBarCount?.toLocaleString() ?? dataset.barCount.toLocaleString()}</dd><dt>Normalization</dt><dd>{dataset.quality.normalizationNote}</dd></dl></details>
    </>;
  }
  const quality = dataset.quality;
  const source = dataset.source;
  return <>
    <dl><dt>Name</dt><dd>{dataset.name}</dd><dt>Symbol</dt><dd>{dataset.symbol}</dd><dt>Interval</dt><dd>{dataset.interval}</dd><dt>Date range</dt><dd>{dataset.dateRange.start} – {dataset.dateRange.end}</dd><dt>Bars</dt><dd>{dataset.barCount.toLocaleString()}</dd><dt>Quality</dt><dd>{quality ? `${quality.status} · ${quality.barCount.toLocaleString()} checked bars · ${quality.zeroVolumeBarCount} zero-volume · ${quality.calendarGapCount} calendar gaps` : 'Not checked'}</dd></dl>
    <details><summary>Immutable identity</summary><dl><dt>Snapshot ID</dt><dd><code>{dataset.id}</code></dd><dt>Schema</dt><dd><code>{dataset.schemaVersion}</code></dd><dt>Parser</dt><dd><code>{dataset.parserVersion}</code></dd><dt>Digest</dt><dd><code>{dataset.digest}</code></dd></dl></details>
    {source && <details><summary>Source record</summary><dl>
      <dt>Source</dt><dd>{source.sourceName}</dd>
      <dt>Reference</dt><dd>{source.sourceReference || 'Not provided'}</dd>
      <dt>Calendar</dt><dd>{source.marketCalendar ?? 'unknown'} · {source.timeZone ?? 'timezone unavailable'}</dd>
      <dt>Adjustment</dt><dd>{source.priceAdjustment.replaceAll('_', ' ')}{source.kind === 'provider_fetch' ? ` · ${(source.priceAdjustmentVerificationStatus ?? 'verification unavailable').replaceAll('_', ' ')}` : ''}</dd>
      {source.kind === 'provider_fetch' && <>
        <dt>Provider</dt><dd>{source.providerId}</dd>
        <dt>Retrieved</dt><dd>{source.retrievedAt || 'timestamp unavailable'}</dd>
        <dt>Provider evidence</dt><dd>{source.returnedBarCount} bars from {source.requestedLimit} response limit · {source.droppedIncompleteCount} incomplete dropped · {source.attestationStatus}</dd>
        <dt>Normalization</dt><dd>{source.normalizationNote}</dd>
        {source.providerResponseAttestations.map((attestation) => <Fragment key={`${attestation.kind}-${attestation.digest}`}><dt>{attestation.kind.replaceAll('_', ' ')}</dt><dd><code>{attestation.digest}</code> · {attestation.sourceReference || 'reference unavailable'}</dd></Fragment>)}
        {source.corporateActionsAttestation && <>
          <dt>Dividends</dt><dd>{source.corporateActionsAttestation.dividendsStatus.replaceAll('_', ' ')} · {source.corporateActionsAttestation.dividendEventCount ?? 'unknown'} events · {source.corporateActionsAttestation.dividendCoverageStart ?? 'start unavailable'} – {source.corporateActionsAttestation.dividendCoverageEnd ?? 'end unavailable'}</dd>
          <dt>Splits</dt><dd>{source.corporateActionsAttestation.splitsStatus.replaceAll('_', ' ')}{source.corporateActionsAttestation.splitEventCount == null ? '' : ` · ${source.corporateActionsAttestation.splitEventCount} events`} · {source.corporateActionsAttestation.splitCoverageStart ?? 'start unavailable'} – {source.corporateActionsAttestation.splitCoverageEnd ?? 'end unavailable'}{source.corporateActionsAttestation.splitSnapshotAsOf ? ` · snapshot ${source.corporateActionsAttestation.splitSnapshotAsOf}` : ''}</dd>
          <dt>Split assurance</dt><dd>{(source.corporateActionsAttestation.splitCompletenessStatus ?? 'completeness unavailable').replaceAll('_', ' ')} · {(source.corporateActionsAttestation.splitReconciliationStatus ?? 'reconciliation unavailable').replaceAll('_', ' ')} · current snapshot only; not historical completeness.</dd>
          {source.corporateActionsAttestation.splitEvents && source.corporateActionsAttestation.splitEvents.length > 0 && <><dt>Split events</dt><dd>{source.corporateActionsAttestation.splitEvents.map((event) => `${event.effectiveDate}: ${event.ratioNumerator}:${event.ratioDenominator}`).join(', ')}</dd></>}
          {source.corporateActionsAttestation.splitsStatus === 'unavailable' && <><dt>Split warning</dt><dd>Warning: split coverage unavailable.</dd></>}
          <dt>Corporate actions note</dt><dd>{source.corporateActionsAttestation.note}</dd>
        </>}
      </>}
    </dl></details>}
  </>;
}

export function QuantInspector({ snapshot, presentation, target, onClose }: {
  snapshot: QuantWorkspaceSnapshot;
  presentation: QuantWorkspacePresentation;
  target: QuantInspectTarget;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, []);
  const report = snapshot.report;
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
      {target.kind === 'run' && <><dl><dt>State</dt><dd><Status tone={presentation.statusTone}>{presentation.statusLabel}</Status></dd><dt>Attempt</dt><dd>{snapshot.run.attemptNumber}</dd><dt>Mode</dt><dd>{quantResearchModeLabel(snapshot.run.mode)}</dd><dt>Provider</dt><dd>{snapshot.run.provider}</dd><dt>Model</dt><dd>{snapshot.run.model ?? 'Deterministic Mock Agent'}</dd><dt>Current step</dt><dd>{snapshot.plan.find((step) => step.id === snapshot.run.currentStepId)?.title}</dd><dt>Iteration</dt><dd>{snapshot.run.agentIteration} / {snapshot.run.maxAgentIterations}</dd><dt>Experiments</dt><dd>{snapshot.run.usedExperiments} / {snapshot.limits.maxExperiments}</dd><dt>Repairs</dt><dd>{snapshot.run.usedRepairAttempts} / {snapshot.limits.maxRepairAttempts}</dd></dl><details><summary>Advanced</summary><dl><dt>Run ID</dt><dd><code>{snapshot.run.id}</code></dd><dt>Row version</dt><dd>{snapshot.run.rowVersion}</dd><dt>Latest sequence</dt><dd>{snapshot.run.latestSequence}</dd><dt>Trace reference</dt><dd><code>{snapshot.run.traceRef}</code></dd><dt>Scope version</dt><dd>{snapshot.scope.version}</dd><dt>Dataset digest</dt><dd><code>{snapshot.dataset.digest}</code></dd></dl></details></>}
      {target.kind === 'event' && <><dl><dt>Actor</dt><dd>{target.event.actorLabel}</dd><dt>Timestamp</dt><dd>{target.event.timestamp}</dd><dt>Artifact</dt><dd>{target.event.artifactId ? 'Retained artifact available' : 'None linked'}</dd></dl><details><summary>Advanced event</summary><dl><dt>Event name</dt><dd><code>{target.event.advanced.eventType}</code></dd><dt>Sequence</dt><dd>{target.event.advanced.sequence}</dd><dt>Safe payload</dt><dd>{target.event.advanced.safeSummary}</dd></dl></details></>}
      {target.kind === 'artifact' && <><p>{target.artifact.summary}</p><dl><dt>Type</dt><dd>{target.artifact.type}</dd><dt>Status</dt><dd>{target.artifact.status}</dd><dt>Origin</dt><dd>{target.artifact.origin}</dd><dt>Related</dt><dd>{target.artifact.relatedLabel}</dd></dl><details><summary>Advanced provenance</summary><dl><dt>Artifact ID</dt><dd><code>{target.artifact.id}</code></dd><dt>Digest</dt><dd><code>{target.artifact.digest}</code></dd></dl></details></>}
      {target.kind === 'candidate' && <><p>{target.candidate.verdictReason}</p><dl><dt>Verdict</dt><dd>{target.candidate.verdict}</dd><dt>Return</dt><dd>{target.candidate.metrics.annualizedReturn}%</dd><dt>Drawdown</dt><dd>{target.candidate.metrics.maxDrawdown}%</dd><dt>Sharpe</dt><dd>{target.candidate.metrics.sharpe}</dd><dt>Trades</dt><dd>{target.candidate.metrics.trades}</dd></dl><details><summary>Advanced</summary><dl><dt>Candidate ID</dt><dd><code>{target.candidate.id}</code></dd><dt>Strategy version</dt><dd><code>{target.candidate.strategySpecVersion}</code></dd></dl></details></>}
      {target.kind === 'dataset' && <DatasetInspector dataset={target.dataset} />}
      {target.kind === 'report' && (report ? <><p>{report.conclusion}</p><h3>Proposed next step</h3><p>{report.proposedNextStep}</p><h3>Limitations</h3><ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul><p className="quant-disclaimer">{report.disclaimer}</p><details><summary>Audit and reproduction metadata</summary><dl><dt>Report ID</dt><dd><code>{report.id}</code></dd><dt>Validator</dt><dd><code>{report.validatorVersion}</code></dd><dt>Generation</dt><dd>{report.generationMethod}</dd><dt>Review</dt><dd>{report.humanReviewStatus}</dd></dl></details></> : <p>The API has not generated a report for this state.</p>)}
      {target.kind === 'market_event' && <><dl><dt>Marker</dt><dd>{target.bar.marker}</dd><dt>Timestamp</dt><dd>{target.bar.date}</dd><dt>Open</dt><dd>{target.bar.open}</dd><dt>High</dt><dd>{target.bar.high}</dd><dt>Low</dt><dd>{target.bar.low}</dd><dt>Close</dt><dd>{target.bar.close}</dd><dt>Volume</dt><dd>{target.bar.volume.toLocaleString()}</dd></dl><p>This marker belongs to the selected persisted market series.</p></>}
    </aside>
  </div>;
}
