import { useMemo, useState } from 'react';
import type { SourceViewer } from '../../api';
import type { DecisionBrief, Evidence, Investigation, SourceHealth } from '../../domain';
import { InvestigationDetail, type InvestigationTab } from '../investigations/InvestigationDetail';
import { AgentActionCenter } from './AgentActionCenter';
import { AgentActivityFeed } from './AgentActivityFeed';
import { AgentArtifactCard } from './AgentArtifactCard';
import { AgentHeader } from './AgentHeader';
import { AgentInspector } from './AgentInspector';
import { AgentPlanRail } from './AgentPlanRail';
import { presentAgentSession, type AgentActionKind } from './agent-presentation';

interface AgentWorkspaceProps {
  investigation: Investigation;
  sources: SourceHealth[];
  brief: DecisionBrief | null;
  fixture: boolean;
  compact: boolean;
  disabled: boolean;
  runConnection: 'connected' | 'reconnecting' | 'reset';
  onOpenEvidence: (evidence: Evidence) => Promise<SourceViewer>;
  onReviewEvidence: (evidence: Evidence, decision: 'valid' | 'weak' | 'rejected') => void;
  onReviewClaim: (id: string, decision: 'verify' | 'reject') => void;
  onCreateSynthesis: () => void;
  onReviseSynthesis: (summary: string) => void;
  onReviewSynthesis: (decision: 'verify' | 'reject') => void;
  onCreateBrief: () => void;
  onOpenBrief: () => void;
  onStartRun: () => void;
  onCancelRun: () => void;
  onRetryRun: () => void;
}

type CompactSegment = 'plan' | 'activity' | 'review' | 'result';

export function AgentWorkspace(props: AgentWorkspaceProps) {
  const [reviewTab, setReviewTab] = useState<InvestigationTab | null>(null);
  const [segment, setSegment] = useState<CompactSegment>('activity');
  const presentation = useMemo(() => presentAgentSession(props.investigation, { sources: props.sources, brief: props.brief, fixture: props.fixture }), [props.investigation, props.sources, props.brief, props.fixture]);

  if (reviewTab) return <InvestigationDetail
    investigation={props.investigation}
    disabled={props.disabled}
    runConnection={props.runConnection}
    initialTab={reviewTab}
    onBackToWorkspace={() => setReviewTab(null)}
    onOpenEvidence={props.onOpenEvidence}
    onReviewEvidence={props.onReviewEvidence}
    onReviewClaim={props.onReviewClaim}
    onCreateSynthesis={props.onCreateSynthesis}
    onReviseSynthesis={props.onReviseSynthesis}
    onReviewSynthesis={props.onReviewSynthesis}
    onCreateBrief={props.onCreateBrief}
    onCancelRun={props.onCancelRun}
    onRetryRun={props.onRetryRun}
  />;

  const act = (kind: AgentActionKind) => {
    if (kind === 'start-run') props.onStartRun();
    else if (kind === 'review-evidence') setReviewTab('evidence');
    else if (kind === 'review-findings') setReviewTab('claims');
    else if (kind === 'create-synthesis') props.onCreateSynthesis();
    else if (kind === 'review-synthesis') setReviewTab('synthesis');
    else if (kind === 'create-brief') props.onCreateBrief();
    else if (kind === 'open-brief') props.onOpenBrief();
    else if (kind === 'retry') props.onRetryRun();
    else if (kind === 'cancel') props.onCancelRun();
  };

  const orderedArtifacts = [...presentation.artifacts].sort((left, right) => Number(Boolean(right.primaryAction)) - Number(Boolean(left.primaryAction)));
  const artifactCards = <section className="agent-artifacts" aria-label="Agent artifacts"><div className="agent-panel-heading"><div><p className="agent-eyebrow">Artifacts</p><h3>Governed output</h3></div><span>{presentation.artifacts.length}</span></div><div className="agent-artifact-grid">{orderedArtifacts.map((artifact) => <AgentArtifactCard artifact={artifact} disabled={props.disabled} onAction={act} key={artifact.id} />)}</div>{props.investigation.evidence.length === 0 ? <p className="agent-counter-empty"><strong>No evidence proposals yet.</strong> The Agent has not completed evidence analysis for this run.</p> : !props.investigation.evidence.some((item) => item.stance === 'opposes') && <p className="agent-counter-empty">No opposing evidence is currently attached to this Investigation. This does not mean opposing evidence does not exist.</p>}</section>;

  return <div className={`agent-workspace${props.compact ? ' is-compact' : ''}`}>
    <AgentHeader presentation={presentation} disabled={props.disabled} onCancel={props.onCancelRun} onRetry={props.onRetryRun} onCreateBrief={props.onCreateBrief} onOpenBrief={props.onOpenBrief} />
    {props.compact && <nav className="agent-segments" aria-label="Agent workspace sections">{(['plan', 'activity', 'review', 'result'] as const).map((item) => <button key={item} aria-current={segment === item ? 'page' : undefined} onClick={() => setSegment(item)}>{item}</button>)}</nav>}
    <div className="agent-workspace-grid">
      {(!props.compact || segment === 'plan') && <AgentPlanRail steps={presentation.planSteps} currentStepId={presentation.currentStepId} completedStepCount={presentation.completedStepCount} />}
      {(!props.compact || segment === 'activity' || segment === 'review' || segment === 'result') && <main className="agent-canvas">
        {!props.compact && <AgentActivityFeed presentation={presentation}><AgentActionCenter presentation={presentation} disabled={props.disabled} onAction={act} />{artifactCards}</AgentActivityFeed>}
        {props.compact && segment === 'activity' && <AgentActivityFeed presentation={presentation} />}
        {props.compact && segment === 'review' && <><AgentActionCenter presentation={presentation} disabled={props.disabled} onAction={act} />{artifactCards}</>}
        {props.compact && segment === 'result' && artifactCards}
      </main>}
      {!props.compact && <AgentInspector presentation={presentation} runConnection={props.runConnection} />}
    </div>
  </div>;
}
