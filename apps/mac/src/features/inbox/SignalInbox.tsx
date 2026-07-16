import { useEffect, useState } from 'react';
import { Badge, Button, Status } from '@glint/ui';
import type { SignalSample, SourceViewer } from '../../api';
import type { Impact, Signal, SourceHealth, Urgency, WatchlistSummary } from '../../domain';
import { authenticityLabel, priorityLabel } from '../../domain';
import { CollaborationSummary, DetailHeader, Section } from '../../components/DetailPrimitives';
import { SourceViewerDialog } from '../evidence/SourceViewerDialog';
import { displayTime, label } from '../../lib/formatting';

export function signalChangeSummary(signal: Signal) {
  const delta = signal.currentCount - signal.baselineCount;
  const percent = signal.baselineCount > 0 ? `${Math.round((delta / signal.baselineCount) * 100)}%` : 'new activity';
  return `${signal.currentCount} current vs ${signal.baselineCount} baseline · ${delta >= 0 ? '+' : ''}${delta} (${percent})`;
}

export function SignalRow({ item, watchlist, sources, selected, onClick }: { item: Signal; watchlist?: WatchlistSummary; sources: SourceHealth[]; selected: boolean; onClick: () => void }) {
  const boundSourceIds = new Set([...(watchlist?.sourceConnectionIds ?? []), ...item.perSourceFreshness.map((freshness) => freshness.sourceConnectionId)]);
  const sourceTypes = [...new Set(sources.filter((source) => boundSourceIds.has(source.id)).map((source) => label(source.connectorType)))];
  const topic = watchlist?.rules.includeTerms[0] ?? watchlist?.rules.entities[0] ?? 'Topic not named';
  return <button className={selected ? 'signal-row selected' : 'signal-row'} onClick={onClick}>
    <div className="signal-row-main"><div className="signal-row-badges"><Status tone={item.status === 'new' ? 'warning' : 'info'}>{label(item.status)}</Status><Badge tone="info">{authenticityLabel(item.authenticity)}</Badge></div><strong>{item.title}</strong><small>{watchlist?.name ?? 'Watchlist unavailable'} · {topic}</small><small>Detection confidence: {item.confidence} · {signalChangeSummary(item)}</small><small>{item.independentSources} independent sources · {sourceTypes.length ? sourceTypes.join(' + ') : 'Source type unavailable'} · snapshot {displayTime(item.snapshotAt)}</small></div>
    <span className={item.priority ? 'priority assessed' : 'priority needs-triage'}>{item.priority ? priorityLabel(item) : 'Needs triage'}</span>
  </button>;
}

export function SignalDetail({ signal, sources, disabled, onLoadSamples, onTriage, onStart, onDismiss }: { signal: Signal; sources: SourceHealth[]; disabled: boolean; onLoadSamples: () => Promise<SignalSample[]>; onTriage: (impact: Impact, urgency: Urgency) => void; onStart: () => void; onDismiss: () => void }) {
  const [impact, setImpact] = useState<Impact>(signal.impact);
  const [urgency, setUrgency] = useState<Urgency>(signal.urgency);
  const [samples, setSamples] = useState<SignalSample[]>([]);
  const [sampleError, setSampleError] = useState<string | null>(null);
  const [viewer, setViewer] = useState<SourceViewer | null>(null);
  useEffect(() => { setImpact(signal.impact); setUrgency(signal.urgency); }, [signal]);
  useEffect(() => {
    setSamples([]); setSampleError(null); setViewer(null);
    if (disabled) return;
    void onLoadSamples().then(setSamples).catch((reason: unknown) => setSampleError(reason instanceof Error ? reason.message : 'Representative samples are unavailable.'));
  }, [signal.id, disabled]);
  return <div className="detail-body">
    <DetailHeader title={signal.title} status={<><Badge tone="info">{authenticityLabel(signal.authenticity)}</Badge><Status tone="info">Detected: {signal.confidence}</Status></>} />
    <Section title="What changed"><p><strong>{signalChangeSummary(signal)}</strong> across {signal.independentSources} independent source{signal.independentSources === 1 ? '' : 's'}.</p></Section>
    <Section title="Why detected"><p>{signal.confidenceExplanation}</p><p>The detector rated this pattern {signal.confidence} confidence based on the monitored window and source agreement. This is a research lead, not a correctness judgment.</p></Section>
    <Section title="Why it matters"><p>{signal.impact && signal.impact !== 'unknown' ? `${label(signal.impact)} business impact` : 'Business impact needs assessment'} · {signal.urgency && signal.urgency !== 'unknown' ? `${label(signal.urgency)} urgency` : 'urgency needs assessment'}.</p><p>{signal.crossSourceConfirmation ? 'The change appears across independent sources, reducing single-source concentration risk.' : 'The change is not yet confirmed across independent sources; treat it as an investigation lead.'}</p></Section>
    <Section title="Supporting evidence">{sampleError && <p role="alert">{sampleError}</p>}{!sampleError && !disabled && samples.length === 0 && <p>Loading exact SignalEvidence samples…</p>}{disabled && <p>Representative bodies are not retained in the redacted offline cache.</p>}{samples.map((sample) => <article className="evidence" key={sample.contentVersionId}><Badge tone={sample.role === 'trigger' ? 'warning' : 'info'}>{sample.role === 'trigger' ? 'Detection evidence' : 'Context'}</Badge><h4>{sample.viewer.title}</h4><p>“{sample.viewer.highlightedQuote}”</p><small>{sample.viewer.source.name} · {sample.viewer.author ?? 'author unavailable'} · published {displayTime(sample.viewer.publishedAt)} · captured {displayTime(sample.viewer.capturedAt)} · independence {sample.viewer.independenceGroupId ?? 'not assigned'}</small><div><Button onClick={() => setViewer(sample.viewer)}>Open Source Viewer</Button></div></article>)}</Section>
    <Section title="Counter-evidence"><p>No counter-evidence review has been completed at the Signal stage. Start an Investigation to search and review opposing evidence.</p></Section>
    <Section title="Gaps & limitations"><ul>{signal.limitations.length ? signal.limitations.map((limitation) => <li key={limitation}>{limitation}</li>) : <li>No detector limitations were attached; verify scope before acting.</li>}</ul></Section>
    <Section title="Freshness">{signal.perSourceFreshness.length === 0 ? <p>No source freshness projection was attached.</p> : signal.perSourceFreshness.map((freshness) => { const source = sources.find((item) => item.id === freshness.sourceConnectionId); return <p key={freshness.sourceConnectionId}><Status tone={freshness.state === 'current' ? 'positive' : 'warning'}>{freshness.state}</Status> {source?.name ?? 'Source unavailable'} · last success {displayTime(freshness.lastSuccessAt)}</p>; })}</Section>
    <details className="progressive-disclosure"><summary>Detection details</summary><dl><dt>Current window</dt><dd>{displayTime(signal.window.currentStart)} → {displayTime(signal.window.currentEnd)} · {signal.currentCount} current / {signal.mentionCount} mentions</dd><dt>Baseline window</dt><dd>{displayTime(signal.window.baselineStart)} → {displayTime(signal.window.baselineEnd)} · {signal.baselineCount} baseline</dd><dt>Growth ratio</dt><dd>{signal.growthRatio.toFixed(2)}×</dd><dt>Robust z</dt><dd>{signal.robustZ.toFixed(2)}</dd><dt>Source counts</dt><dd>{signal.independentSources} independent / {signal.totalSourceCount} total · {signal.platformCount} platforms</dd><dt>Trigger rules</dt><dd>{signal.triggerRules.join(', ') || 'No rules attached'}</dd></dl><p className="hint">Detection confidence is detector-owned and is not a fact-correctness score.</p></details>
    <Section title="Triage"><p className="hint">Confirm both human assessments to derive Priority.</p><div className="triage-grid"><label>Business Impact<select value={impact ?? ''} onChange={(event) => setImpact((event.target.value || null) as Impact)} disabled={disabled}><option value="">Unassessed</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="unknown">Unknown</option></select></label><label>Urgency<select value={urgency ?? ''} onChange={(event) => setUrgency((event.target.value || null) as Urgency)} disabled={disabled}><option value="">Unassessed</option><option value="now">Now</option><option value="this_week">This week</option><option value="monitor">Monitor</option><option value="unknown">Unknown</option></select></label><div><span>Derived Priority</span><strong>{impact === signal.impact && urgency === signal.urgency ? priorityLabel(signal) : impact === 'unknown' || urgency === 'unknown' ? 'Unranked · insufficient input' : 'Calculated on confirmation'}</strong><small>Policy: priority-matrix-v1</small></div></div><Button disabled={disabled || !impact || !urgency} onClick={() => onTriage(impact, urgency)}>Confirm Impact & Urgency</Button></Section>
    <Section title="Next steps"><div className="actions"><Button className="primary" disabled={disabled || signal.status === 'new' || signal.status === 'dismissed'} onClick={onStart}>Start Investigation</Button><Button disabled={disabled || !['new', 'triaged', 'explained', 'monitoring'].includes(signal.status)} onClick={onDismiss}>Dismiss Signal</Button></div></Section>
    <CollaborationSummary activity={signal.disposition ? `Latest disposition: ${label(signal.disposition.action)}.` : 'Awaiting triage.'} statusReason={signal.disposition?.note ?? (signal.disposition?.dismissReason ? label(signal.disposition.dismissReason) : 'No status reason recorded.')} responsibility="Workspace owner decides whether this Signal advances to investigation." reviewed={signal.status !== 'new'} />
    {viewer && <SourceViewerDialog viewer={viewer} onClose={() => setViewer(null)} />}
  </div>;
}
