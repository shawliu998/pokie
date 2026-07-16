import { useEffect, useState } from 'react';
import { Badge, Button, Status } from '@glint/ui';
import type { SignalSample, SourceViewer } from '../../api';
import type { Impact, Signal, SourceHealth, Urgency } from '../../domain';
import { authenticityLabel, priorityLabel } from '../../domain';
import { DetailHeader, Section } from '../../components/DetailPrimitives';
import { SourceViewerDialog } from '../evidence/SourceViewerDialog';
import { displayTime } from '../../lib/formatting';

export function SignalRow({ item, selected, onClick }: { item: Signal; selected: boolean; onClick: () => void }) {
  return <button className={selected ? 'signal-row selected' : 'signal-row'} onClick={onClick}><div><Badge tone="info">{authenticityLabel(item.authenticity)}</Badge> <Status tone="info">Detected: {item.confidence}</Status><strong>{item.title}</strong><small>Watchlist {item.watchlistId} · {item.triggerRules.join(', ')}</small><small>{item.independentSources} independent sources · snapshot {displayTime(item.snapshotAt)}</small></div><span className="priority">{priorityLabel(item)}</span></button>;
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
    <Section title="What changed"><p>{signal.confidenceExplanation}</p><dl><dt>Current window</dt><dd>{displayTime(signal.window.currentStart)} → {displayTime(signal.window.currentEnd)} · {signal.currentCount} current / {signal.mentionCount} mentions</dd><dt>Baseline window</dt><dd>{displayTime(signal.window.baselineStart)} → {displayTime(signal.window.baselineEnd)} · {signal.baselineCount} baseline</dd><dt>Growth / robust z</dt><dd>{signal.growthRatio.toFixed(2)}× / {signal.robustZ.toFixed(2)}</dd><dt>Cross-source</dt><dd>{signal.crossSourceConfirmation ? 'Yes' : 'No'} · {signal.independentSources} independent / {signal.totalSourceCount} total sources</dd><dt>Platforms</dt><dd>{signal.platformCount}</dd></dl></Section>
    <Section title="Why detected"><ul>{signal.triggerRules.map((rule) => <li key={rule}>{rule}</li>)}</ul><p className="hint">Detection confidence is detector-owned and is not a fact-correctness score.</p></Section>
    <Section title="Representative samples">{sampleError && <p role="alert">{sampleError}</p>}{!sampleError && !disabled && samples.length === 0 && <p>Loading exact SignalEvidence samples…</p>}{disabled && <p>Representative bodies are not retained in the redacted offline cache.</p>}{samples.map((sample) => <article className="evidence" key={sample.contentVersionId}><Badge tone={sample.role === 'trigger' ? 'warning' : 'info'}>{sample.role}</Badge><h4>{sample.viewer.title}</h4><p>“{sample.viewer.highlightedQuote}”</p><small>{sample.viewer.source.name} · {sample.viewer.author ?? 'author unavailable'} · published {displayTime(sample.viewer.publishedAt)} · captured {displayTime(sample.viewer.capturedAt)} · independence {sample.viewer.independenceGroupId ?? 'not assigned'} · contribution {sample.contribution}</small><div><Button onClick={() => setViewer(sample.viewer)}>Open Source Viewer</Button></div></article>)}</Section>
    <Section title="Data quality & limitations"><ul>{signal.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></Section>
    <Section title="Per-source freshness">{signal.perSourceFreshness.length === 0 ? <p>No source freshness projection was attached.</p> : signal.perSourceFreshness.map((freshness) => { const source = sources.find((item) => item.id === freshness.sourceConnectionId); return <p key={freshness.sourceConnectionId}><Status tone={freshness.state === 'current' ? 'positive' : 'warning'}>{freshness.state}</Status> {source?.name ?? freshness.sourceConnectionId} · last success {displayTime(freshness.lastSuccessAt)}</p>; })}</Section>
    <Section title="Triage"><p className="hint">Confirm both human assessments to derive Priority.</p><div className="triage-grid"><label>Business Impact<select value={impact ?? ''} onChange={(event) => setImpact((event.target.value || null) as Impact)} disabled={disabled}><option value="">Unassessed</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="unknown">Unknown</option></select></label><label>Urgency<select value={urgency ?? ''} onChange={(event) => setUrgency((event.target.value || null) as Urgency)} disabled={disabled}><option value="">Unassessed</option><option value="now">Now</option><option value="this_week">This week</option><option value="monitor">Monitor</option><option value="unknown">Unknown</option></select></label><div><span>Derived Priority</span><strong>{impact === signal.impact && urgency === signal.urgency ? priorityLabel(signal) : impact === 'unknown' || urgency === 'unknown' ? 'Unranked · insufficient input' : 'Calculated on confirmation'}</strong><small>Policy: priority-matrix-v1</small></div></div><Button disabled={disabled || !impact || !urgency} onClick={() => onTriage(impact, urgency)}>Confirm Impact & Urgency</Button></Section>
    <div className="actions"><Button className="primary" disabled={disabled || signal.status === 'new' || signal.status === 'dismissed'} onClick={onStart}>Start Investigation</Button><Button disabled={disabled || !['new', 'triaged', 'explained', 'monitoring'].includes(signal.status)} onClick={onDismiss}>Dismiss Signal</Button></div>
    {viewer && <SourceViewerDialog viewer={viewer} onClose={() => setViewer(null)} />}
  </div>;
}
