import { useEffect, useState } from 'react';
import { Badge, Button, Status } from '@glint/ui';
import type { SourceViewer } from '../../api';
import type { Evidence, Investigation } from '../../domain';
import { authenticityLabel } from '../../domain';
import { CollaborationSummary, DetailHeader, Section } from '../../components/DetailPrimitives';
import { SourceViewerDialog } from '../evidence/SourceViewerDialog';
import { displayTime, incompleteCopy, label } from '../../lib/formatting';
import { researchMethodLabel, runProvenanceAvailable, runStateSummary, synthesisMethodLabel } from './research-presentation';

type InvestigationTab = 'overview' | 'evidence' | 'claims' | 'synthesis' | 'runs';

interface InvestigationDetailProps {
  investigation: Investigation;
  disabled: boolean;
  runConnection: 'connected' | 'reconnecting' | 'reset';
  onOpenEvidence: (evidence: Evidence) => Promise<SourceViewer>;
  onReviewEvidence: (evidence: Evidence, decision: 'valid' | 'weak' | 'rejected') => void;
  onReviewClaim: (id: string, decision: 'verify' | 'reject') => void;
  onCreateSynthesis: () => void;
  onReviseSynthesis: (summary: string) => void;
  onReviewSynthesis: (decision: 'verify' | 'reject') => void;
  onCreateBrief: () => void;
  onCancelRun: () => void;
  onRetryRun: () => void;
}

export function InvestigationDetail({ investigation, disabled, runConnection, onOpenEvidence, onReviewEvidence, onReviewClaim, onCreateSynthesis, onReviseSynthesis, onReviewSynthesis, onCreateBrief, onCancelRun, onRetryRun }: InvestigationDetailProps) {
  const [tab, setTab] = useState<InvestigationTab>('overview');
  const [summary, setSummary] = useState(investigation.synthesis?.executiveSummary ?? '');
  const [viewer, setViewer] = useState<SourceViewer | null>(null);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [viewerLoadingId, setViewerLoadingId] = useState<string | null>(null);
  const [viewedEvidenceIds, setViewedEvidenceIds] = useState<Set<string>>(() => new Set());
  useEffect(() => setSummary(investigation.synthesis?.executiveSummary ?? ''), [investigation.synthesis?.versionId, investigation.synthesis?.executiveSummary]);

  const openEvidence = async (evidence: Evidence) => {
    setViewerError(null);
    setViewerLoadingId(evidence.id);
    try {
      const loaded = await onOpenEvidence(evidence);
      setViewer(loaded);
      setViewedEvidenceIds((current) => new Set(current).add(evidence.id));
    } catch (reason) {
      setViewerError(reason instanceof Error ? reason.message : 'Source Viewer could not load the immutable content.');
    } finally {
      setViewerLoadingId(null);
    }
  };

  const run = investigation.run;
  const synthesis = investigation.synthesis;
  const reviewable = synthesis?.status === 'draft' || synthesis?.status === 'needs_review';
  const counterEvidenceReviewed = investigation.evidence.some((evidence) => evidence.stance === 'opposes' && evidence.latestReviewId !== null);
  const evidenceGroups = (['supports', 'opposes', 'neutral'] as const).map((stance) => ({ stance, items: investigation.evidence.filter((item) => item.stance === stance) }));
  const stages = [
    ['Scope defined', true, `${investigation.sourceConnectionIds.length} source${investigation.sourceConnectionIds.length === 1 ? '' : 's'}`],
    ['Evidence retrieved', investigation.evidence.length > 0, `${investigation.evidence.length} item${investigation.evidence.length === 1 ? '' : 's'}`],
    ['Claims proposed', investigation.claims.length > 0, `${investigation.claims.length} claim${investigation.claims.length === 1 ? '' : 's'}`],
    ['Counter-evidence reviewed', counterEvidenceReviewed, `${investigation.evidence.filter((item) => item.stance === 'opposes').length} opposing`],
    ['Synthesis proposed', Boolean(synthesis), synthesis ? synthesisMethodLabel(synthesis.generationMethod) : 'Not created'],
    [synthesis?.status === 'verified' ? 'Human review completed' : 'Human review required', synthesis?.status === 'verified', synthesis?.status === 'verified' ? 'Verified' : 'Pending'],
  ] as const;
  const businessTimeline = <ol className="business-timeline">{stages.map(([name, complete, detail]) => <li className={complete ? 'complete' : 'pending'} key={name}><span aria-hidden="true">{complete ? '✓' : '○'}</span><div><strong>{name}</strong><small>{complete ? 'Complete' : 'Pending'} · {detail}</small></div></li>)}</ol>;
  const latestActivity = investigation.events.at(-1)?.message ?? 'Scope is defined; no research activity has started.';
  const runMethod = run ? researchMethodLabel(run.generationMethod) : investigation.allowCloudModel ? 'Model-assisted research requested' : 'Deterministic research';

  return <div className="detail-body">
    <DetailHeader title={investigation.question} status={<><Badge tone="info">{authenticityLabel(investigation.authenticity)}</Badge><Badge tone={run?.generationMethod === 'model' ? 'warning' : 'neutral'}>{runMethod}</Badge><Status tone={investigation.status === 'completed' ? 'positive' : 'info'}>{label(investigation.status)}</Status></>} />
    {run?.state === 'waiting_for_input' && <section className="needs-input" role="region" aria-label="Research needs input"><div><h3>Research needs human input</h3><Status tone="warning">Paused</Status></div><p>{run.waitingForInputReason ? label(run.waitingForInputReason) : 'The run did not provide a structured waiting reason. Review the event stream before deciding whether to cancel.'}</p><p className="hint">No model or deterministic step may approve evidence or continue beyond this gate without an authorized action.</p><Button disabled={disabled} onClick={onCancelRun}>Cancel run</Button></section>}
    <div className="tabs" role="tablist">{(['overview', 'evidence', 'claims', 'synthesis', 'runs'] as const).map((item) => <button role="tab" aria-selected={tab === item} onClick={() => setTab(item)} key={item}>{label(item)}</button>)}</div>

    {tab === 'overview' && <>
      <Section title="Pinned scope"><p>{investigation.sourceConnectionIds.length || 'No'} source connection{investigation.sourceConnectionIds.length === 1 ? '' : 's'} and {investigation.contentVersionIds.length} immutable content version{investigation.contentVersionIds.length === 1 ? '' : 's'} pinned{investigation.timeRange ? ` from ${displayTime(investigation.timeRange.start)} to ${displayTime(investigation.timeRange.end)}` : ''}.</p>{investigation.allowCloudModel ? <p><Badge tone="warning">Run-scoped model egress</Badge> Selected source excerpts may be sent to the configured DeepSeek provider for this scope. Imported-upload consent alone does not grant this access.</p> : <p><Badge tone="neutral">No model egress</Badge> This scope is deterministic.</p>}</Section>
      <Section title="Business timeline">{businessTimeline}<p className="hint">Latest activity: {latestActivity}</p></Section>
      {run && <Section title="Research authority"><p>{runStateSummary(run)}</p><p className="hint">Glint can propose research artifacts. Only an authorized human can validate Evidence, verify ClaimVersions and synthesis, mark a Brief Decision-ready, or export it.</p></Section>}
      <details className="progressive-disclosure"><summary>Technical details</summary><dl><dt>Scope version</dt><dd><code>{investigation.scopeVersionId}</code></dd><dt>Run attempt</dt><dd>{run?.attemptNumber ?? 'Not started'}</dd><dt>Run state</dt><dd>{run?.state ?? 'No run'}</dd><dt>Latest sequence</dt><dd>{run?.latestSequence ?? 'None'}</dd>{run && <><dt>Graph version</dt><dd><code>{run.graphVersion}</code></dd><dt>Budget</dt><dd>${run.budget.maxCostUsd} / {run.budget.maxDurationSeconds}s</dd></>}</dl></details>
    </>}

    {tab === 'evidence' && <Section title="Evidence review"><p className="hint">Every item is a proposal until a human opens its immutable ContentVersion and appends an EvidenceReview.</p><div className="evidence-summary">{evidenceGroups.map(({ stance, items }) => <Badge key={stance} tone={stance === 'supports' ? 'positive' : stance === 'opposes' ? 'warning' : 'neutral'}>{label(stance)} {items.length}</Badge>)}</div>{viewerError && <p role="alert">{viewerError}</p>}{evidenceGroups.map(({ stance, items }) => items.length > 0 && <section className="evidence-group" key={stance}><h4>{label(stance)} evidence</h4>{items.map((evidence) => { const viewed = viewedEvidenceIds.has(evidence.id) || evidence.status !== 'proposed'; const modelProposed = run?.id === evidence.researchRunId && run.generationMethod === 'model'; return <article className="evidence" key={evidence.id}><div className="proposal-heading"><Badge tone={stance === 'supports' ? 'positive' : stance === 'opposes' ? 'warning' : 'neutral'}>{label(stance)}</Badge><Badge tone={modelProposed ? 'warning' : 'neutral'}>{modelProposed ? 'Model proposal' : 'Research proposal'}</Badge><Status tone={evidence.status === 'valid' ? 'positive' : evidence.status === 'proposed' ? 'warning' : 'neutral'}>{label(evidence.status)}</Status></div><blockquote>“{evidence.quote}”</blockquote><small>Immutable source reference retained · {evidence.provenance.extractionMethod}</small><details><summary>Exact reference</summary><dl><dt>ContentVersion</dt><dd><code>{evidence.contentVersionId}</code></dd><dt>Quote offsets</dt><dd>{evidence.quoteStart}–{evidence.quoteEnd}</dd><dt>ResearchRun</dt><dd><code>{evidence.researchRunId}</code></dd></dl></details><div><Button disabled={viewerLoadingId === evidence.id} onClick={() => void openEvidence(evidence)}>{viewerLoadingId === evidence.id ? 'Loading source…' : viewed ? 'Reopen source' : 'Open source'}</Button><Button disabled={disabled || !viewed} onClick={() => onReviewEvidence(evidence, 'valid')}>Valid</Button><Button disabled={disabled || !viewed} onClick={() => onReviewEvidence(evidence, 'weak')}>Weak</Button><Button disabled={disabled || !viewed} onClick={() => onReviewEvidence(evidence, 'rejected')}>Reject</Button></div></article>; })}</section>)}</Section>}

    {tab === 'claims' && <Section title="Claim review"><p className="hint">Claims are versioned proposals, not chat messages. Verification freezes reviewed evidence references; it does not make a universal guarantee.</p>{investigation.claims.map((claim) => { const supports = claim.evidenceLinks.filter((link) => link.stance === 'supports').length; const opposes = claim.evidenceLinks.filter((link) => link.stance === 'opposes').length; const modelProposed = run?.id === claim.researchRunId && run.generationMethod === 'model'; return <article className="claim" key={claim.id}><div className="proposal-heading"><Badge tone={modelProposed ? 'warning' : 'neutral'}>{modelProposed ? 'Model proposal' : 'Research proposal'}</Badge><Status tone={claim.status === 'verified' ? 'positive' : claim.status === 'rejected' ? 'danger' : 'warning'}>{label(claim.status)}</Status></div><h3>{claim.text}</h3><p>Supporting {supports} · Opposing {opposes}</p>{claim.limitations.length > 0 ? <><h4>Limitations</h4><ul>{claim.limitations.map((item) => <li key={item}>{item}</li>)}</ul></> : <p className="hint">No limitations were supplied; verification should remain blocked by backend policy if required.</p>}<details><summary>Exact references</summary><p><code>{claim.versionId}</code></p><ul>{claim.evidenceLinks.map((link) => <li key={link.id}><code>{link.evidenceId}</code> · {label(link.stance)}</li>)}</ul></details><div><Button disabled={disabled || claim.status === 'verified'} onClick={() => onReviewClaim(claim.id, 'verify')}>Verify</Button><Button disabled={disabled || claim.status === 'rejected'} onClick={() => onReviewClaim(claim.id, 'reject')}>Reject</Button></div></article>; })}</Section>}

    {tab === 'synthesis' && <Section title="Investigation synthesis">{synthesis ? <><Badge tone={synthesis.generationMethod === 'model' ? 'warning' : 'neutral'}>{synthesisMethodLabel(synthesis.generationMethod)}</Badge><p className="hint">This is generated interpretation. Human verification is required before a Decision Brief can be created.</p><label>Executive summary<textarea aria-label="Synthesis executive summary" disabled={disabled || synthesis.status === 'verified'} value={summary} onChange={(event) => setSummary(event.target.value)} /></label><h4>Business implications</h4><ul>{synthesis.businessImplications.map((item) => <li key={item}>{item}</li>)}</ul><h4>Limitations</h4><ul>{synthesis.limitations.map((item) => <li key={item}>{item}</li>)}</ul><p><Status tone={synthesis.status === 'verified' ? 'positive' : synthesis.status === 'rejected' ? 'danger' : 'warning'}>{label(synthesis.status)}</Status></p><details><summary>Provenance</summary><dl><dt>Generation method</dt><dd>{synthesisMethodLabel(synthesis.generationMethod)}</dd><dt>Generator version</dt><dd><code>{synthesis.generatorVersion}</code></dd><dt>Prompt refs</dt><dd>{synthesis.modelPromptRefs.length ? synthesis.modelPromptRefs.map((item) => <code key={item}>{item} </code>) : 'Not applicable / unavailable'}</dd><dt>Verified ClaimVersions</dt><dd>{synthesis.verifiedClaimVersionIds.map((item) => <code key={item}>{item} </code>)}</dd></dl></details><div className="actions"><Button disabled={disabled || synthesis.status === 'verified' || incompleteCopy(summary) || summary === synthesis.executiveSummary} onClick={() => onReviseSynthesis(summary)}>Save revision</Button><Button disabled={disabled || !reviewable} onClick={() => onReviewSynthesis('verify')}>Verify synthesis</Button><Button disabled={disabled || !reviewable} onClick={() => onReviewSynthesis('reject')}>Reject synthesis</Button></div></> : <><p>Create a reviewable deterministic synthesis from the exact verified ClaimVersions. Creation never approves it.</p><Button disabled={disabled || !investigation.claims.some((claim) => claim.status === 'verified')} onClick={onCreateSynthesis}>Create synthesis</Button></>}<Button className="primary" disabled={disabled || synthesis?.status !== 'verified'} onClick={onCreateBrief}>Create Decision Brief</Button></Section>}

    {tab === 'runs' && <>
      <Section title="Run status">{run ? <><div className="run-status-heading"><Badge tone={run.generationMethod === 'model' ? 'warning' : 'neutral'}>{researchMethodLabel(run.generationMethod)}</Badge><Status tone={run.state === 'completed' ? 'positive' : run.state === 'failed' ? 'danger' : 'warning'}>{label(run.state)}</Status></div><p>{runStateSummary(run)}</p>{run.generationMethod === 'model' && !runProvenanceAvailable(run) && <p role="alert">Model provenance is incomplete. Do not treat this run as review-ready until provider, model, and prompt references are available.</p>}<div className="sse"><Status tone={runConnection === 'connected' ? 'positive' : 'warning'}>{runConnection === 'connected' ? 'SSE connected' : runConnection === 'reconnecting' ? 'SSE reconnecting — run is not failed' : 'SSE cursor reset — snapshot reloaded'}</Status>{['queued', 'running', 'waiting_for_input'].includes(run.state) && <Button disabled={disabled} onClick={onCancelRun}>Cancel run</Button>}{['failed', 'cancelled'].includes(run.state) && <Button disabled={disabled} onClick={onRetryRun}>Retry pinned scope</Button>}</div><details className="progressive-disclosure"><summary>Technical provenance</summary><dl><dt>Graph version</dt><dd><code>{run.graphVersion}</code></dd><dt>Provider</dt><dd>{run.provider ?? 'Unavailable'}</dd><dt>Model</dt><dd>{run.model ?? 'Not applicable / unavailable'}</dd><dt>Prompt refs</dt><dd>{run.promptRefs.length ? run.promptRefs.map((item) => <code key={item}>{item} </code>) : 'Not applicable / unavailable'}</dd><dt>Trace ref</dt><dd>{run.traceRef ? <code>{run.traceRef}</code> : 'Unavailable'}</dd><dt>Used / maximum cost</dt><dd>${run.usedCostUsd} / ${run.budget.maxCostUsd}</dd><dt>Maximum duration</dt><dd>{run.budget.maxDurationSeconds}s</dd></dl></details></> : <p>No ResearchRun has started.</p>}</Section>
      <Section title="Business timeline">{businessTimeline}<p className="hint">Latest activity: {latestActivity}</p></Section>
      <details className="progressive-disclosure"><summary>Advanced / Debug event stream</summary>{investigation.events.map((event) => <p className="run-event" key={event.id}><code>{event.sequence}</code> {event.type} · {event.message} <small>{displayTime(event.timestamp)}</small></p>)}</details>
    </>}

    <CollaborationSummary activity={latestActivity} statusReason={`Investigation is ${label(investigation.status)}; ${run ? `research run is ${label(run.state)}` : 'research has not started'}.`} responsibility="Workspace owner controls scope and model egress; an authorized human validates evidence, claims, and synthesis." reviewed={investigation.claims.some((claim) => claim.status === 'verified') || synthesis?.status === 'verified'} />
    {viewer && <SourceViewerDialog viewer={viewer} onClose={() => setViewer(null)} />}
  </div>;
}
