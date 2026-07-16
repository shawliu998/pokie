import { useEffect, useState } from 'react';
import { Badge, Button, Status } from '@glint/ui';
import type { NoCounterEvidenceSearchInput } from '../../api';
import type { DecisionBrief } from '../../domain';
import { authenticityLabel } from '../../domain';
import { createSerialMutationQueue } from '../../brief-mutations';
import { CollaborationSummary, ContentBlock, DetailHeader, Section } from '../../components/DetailPrimitives';
import { incompleteCopy } from '../../lib/formatting';
import { synthesisMethodLabel } from '../investigations/research-presentation';

export function DecisionBriefDetail({ brief, disabled, hasReviewedCounterEvidence, onUpdate, onSaveCounterEvidenceSearch, onReady, onExport }: { brief: DecisionBrief; disabled: boolean; hasReviewedCounterEvidence: boolean; onUpdate: (judgment: string, recommendationId: string, recommendationBody: string, status: 'accepted' | 'rejected') => Promise<void>; onSaveCounterEvidenceSearch: (input: NoCounterEvidenceSearchInput) => Promise<void>; onReady: () => Promise<void>; onExport: () => void }) {
  const judgmentBlock = brief.blockDocument.blocks.find((block) => block.type === 'pm_judgment');
  const recommendations = brief.blockDocument.blocks.filter((block): block is Extract<typeof block, { type: 'recommendation' }> => block.type === 'recommendation');
  const searchRecord = brief.blockDocument.noCounterEvidenceSearch;
  const [judgment, setJudgment] = useState(judgmentBlock?.body ?? '');
  const [recommendationBodies, setRecommendationBodies] = useState<Record<string, string>>(() => Object.fromEntries(recommendations.map((item) => [item.id, item.body])));
  const [searchQueries, setSearchQueries] = useState(() => searchRecord?.queries.join('\n') ?? '');
  const [exclusionCriteria, setExclusionCriteria] = useState(() => searchRecord?.exclusionCriteria.join('\n') ?? '');
  const [searchLimitations, setSearchLimitations] = useState(() => searchRecord?.limitations.join('\n') ?? '');
  const [mutationBusy, setMutationBusy] = useState(false);
  const [mutationQueue] = useState(() => createSerialMutationQueue(setMutationBusy));
  useEffect(() => () => mutationQueue.dispose(), [mutationQueue]);
  useEffect(() => setJudgment(judgmentBlock?.body ?? ''), [brief.versionId, judgmentBlock?.body]);
  useEffect(() => setRecommendationBodies(Object.fromEntries(recommendations.map((item) => [item.id, item.body]))), [brief.versionId]);
  useEffect(() => {
    setSearchQueries(searchRecord?.queries.join('\n') ?? '');
    setExclusionCriteria(searchRecord?.exclusionCriteria.join('\n') ?? '');
    setSearchLimitations(searchRecord?.limitations.join('\n') ?? '');
  }, [brief.versionId, searchRecord]);
  const lines = (value: string) => value.split('\n').map((item) => item.trim()).filter(Boolean);
  const parsedSearch = { queries: lines(searchQueries), exclusionCriteria: lines(exclusionCriteria), limitations: lines(searchLimitations) };
  const searchInputComplete = parsedSearch.queries.length > 0 && parsedSearch.exclusionCriteria.length > 0 && parsedSearch.limitations.length > 0;
  const ready = brief.readiness === 'decision_ready';
  const mutationDisabled = disabled || ready || mutationBusy;
  const acceptedComplete = recommendations.some((item) => item.recommendationStatus === 'accepted' && !incompleteCopy(item.body));
  const facts = brief.blockDocument.blocks.filter((block): block is Extract<typeof block, { type: 'fact' }> => block.type === 'fact');
  const syntheses = brief.blockDocument.blocks.filter((block): block is Extract<typeof block, { type: 'synthesis' }> => block.type === 'synthesis');
  return <div className="detail-body" aria-busy={mutationBusy}>
    <DetailHeader title={brief.question} status={<><Badge tone="info">{authenticityLabel(brief.authenticity)}</Badge><Status tone={ready ? 'positive' : 'warning'}>{ready ? 'Decision-ready' : 'Draft incomplete'}</Status><span>v{brief.version} · Evidence {brief.freshness}</span>{mutationBusy && <span role="status">Saving brief changes…</span>}</>} />
    <Section title="Decision Question"><p>{brief.question}</p></Section>
    <Section title="What Changed">{facts.length ? facts.map((block) => <ContentBlock type="Fact" title="Verified observation" key={block.id}><p>{block.body}</p><small>{block.contentVersionIds.length} exact content reference{block.contentVersionIds.length === 1 ? '' : 's'} retained</small></ContentBlock>) : <p>No verified facts have been added.</p>}</Section>
    <Section title="Why It Matters">{syntheses.length ? syntheses.map((block) => <ContentBlock type={synthesisMethodLabel(block.generationMethod)} title="Business interpretation" key={block.id}><p>{block.body}</p><small>{block.generatorVersion} · {synthesisMethodLabel(block.generationMethod)}{block.modelPromptRefs.length ? ` · ${block.modelPromptRefs.length} prompt reference${block.modelPromptRefs.length === 1 ? '' : 's'}` : ''}</small></ContentBlock>) : <p>No reviewed synthesis is available.</p>}</Section>
    <Section title="Evidence Summary"><p>{facts.length} fact block{facts.length === 1 ? '' : 's'} link {brief.referenceSnapshot.evidenceIds.length} reviewed evidence item{brief.referenceSnapshot.evidenceIds.length === 1 ? '' : 's'} to {brief.referenceSnapshot.contentVersionIds.length} immutable content version{brief.referenceSnapshot.contentVersionIds.length === 1 ? '' : 's'}.</p><p className="hint"><Badge tone="neutral">Fact</Badge> is a reviewed source-backed observation; it is not a guarantee of universal correctness. Generated synthesis remains interpretation even after human review.</p></Section>
    <section className="counter-evidence-search" role="region" aria-label="Counter-evidence search">
      <div className="counter-evidence-heading"><h3>Counter-evidence</h3><Status tone={searchRecord ? 'positive' : 'warning'}>{searchRecord ? 'Recorded' : 'Not recorded'}</Status>{hasReviewedCounterEvidence && <Badge tone="info">Reviewed opposing evidence present</Badge>}</div>
      <p className="hint">Only save this record after you actually performed the search. Glint records the method you enter; it does not run or infer a counter-evidence search.</p>
      {searchRecord && <dl><dt>Pinned sources</dt><dd>{searchRecord.sourceConnectionIds.length} source{searchRecord.sourceConnectionIds.length === 1 ? '' : 's'}</dd><dt>Pinned window</dt><dd>{searchRecord.windowStart} to {searchRecord.windowEnd}</dd></dl>}
      <label>Queries, one per line<textarea aria-label="Counter-evidence search queries" disabled={mutationDisabled} value={searchQueries} onChange={(event) => setSearchQueries(event.target.value)} /></label>
      <label>Exclusion criteria, one per line<textarea aria-label="Counter-evidence exclusion criteria" disabled={mutationDisabled} value={exclusionCriteria} onChange={(event) => setExclusionCriteria(event.target.value)} /></label>
      <label>Limitations, one per line<textarea aria-label="Counter-evidence search limitations" disabled={mutationDisabled} value={searchLimitations} onChange={(event) => setSearchLimitations(event.target.value)} /></label>
      <Button disabled={mutationDisabled || !searchInputComplete} onClick={() => void mutationQueue.run(() => onSaveCounterEvidenceSearch(parsedSearch))}>Save counter-evidence search</Button>
    </section>
    <Section title="Limitations">{searchRecord?.limitations.length ? <ul>{searchRecord.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : <p>No explicit limitations are recorded. Readiness may require a scoped counter-evidence search.</p>}</Section>
    {judgmentBlock
      ? <ContentBlock type="PM judgment" title="PM Judgment" key={judgmentBlock.id}>
        <textarea aria-label="PM Judgment" disabled={mutationDisabled} value={judgment} onChange={(event) => setJudgment(event.target.value)} />
        <small>Human-authored by the workspace owner · required for readiness</small>
      </ContentBlock>
      : <ContentBlock type="PM judgment" title="PM Judgment"><p>No PM judgment has been authored.</p></ContentBlock>}
    <Section title="Recommended Actions">{recommendations.length ? recommendations.map((block) => <ContentBlock type="Recommendation" title="Recommended action" key={block.id}>
          <textarea aria-label={`Recommendation ${block.id}`} disabled={mutationDisabled} value={recommendationBodies[block.id] ?? block.body} onChange={(event) => setRecommendationBodies((current) => ({ ...current, [block.id]: event.target.value }))} />
          <div>
            <Status tone={block.recommendationStatus === 'accepted' ? 'positive' : block.recommendationStatus === 'rejected' ? 'danger' : 'warning'}>{block.recommendationStatus}</Status>
            <Button disabled={mutationDisabled || incompleteCopy(judgment) || incompleteCopy(recommendationBodies[block.id] ?? block.body)} onClick={() => void mutationQueue.run(() => onUpdate(judgment, block.id, recommendationBodies[block.id] ?? block.body, 'accepted'))}>{block.recommendationStatus === 'accepted' ? 'Save accepted' : 'Accept'}</Button>
            <Button disabled={mutationDisabled || !judgment.trim() || !(recommendationBodies[block.id] ?? block.body).trim()} onClick={() => void mutationQueue.run(() => onUpdate(judgment, block.id, recommendationBodies[block.id] ?? block.body, 'rejected'))}>Reject</Button>
          </div>
        </ContentBlock>
        ) : <p>No recommended action has been proposed.</p>}</Section>
    <div className="readiness">
      <h3>Readiness</h3>
      <ul><li>{!incompleteCopy(judgment) ? '✓' : '○'} PM Judgment authored without placeholder wording</li><li>{acceptedComplete ? '✓' : '○'} At least one complete Recommendation accepted</li><li>{brief.blockDocument.blocks.some((item) => item.type === 'fact') ? '✓' : '○'} Verified facts with exact references</li><li>{hasReviewedCounterEvidence ? '✓ Reviewed opposing evidence is present' : searchRecord ? '✓ Explicit no-counter search scope recorded' : '○ No-counter search record may be required; the backend will make the final readiness decision'}</li></ul>
      <Button className="primary" disabled={mutationDisabled || incompleteCopy(judgment) || !acceptedComplete} onClick={() => void mutationQueue.run(onReady)}>Mark Decision-ready</Button>
      <Button disabled={!ready || disabled || mutationBusy || brief.freshness === 'evidence_stale'} onClick={onExport}>Export PRD Research Input</Button>
    </div>
    <Section title="Freshness"><p><Status tone={brief.freshness === 'current' ? 'positive' : 'warning'}>{brief.freshness === 'current' ? 'Evidence current' : 'Evidence stale'}</Status> The brief remains bound to Decision Brief v{brief.version}; export is blocked when its evidence snapshot is stale.</p></Section>
    <CollaborationSummary activity={`Decision Brief v${brief.version} is ${ready ? 'decision-ready' : 'in draft review'}.`} statusReason={ready ? 'The readiness checklist was completed.' : 'PM judgment, accepted action, and evidence review must satisfy readiness policy.'} responsibility="Workspace owner authors PM judgment; a workspace reviewer confirms readiness." reviewed={ready} />
  </div>;
}
