import type {
  CandidateVerdict,
  QuantArtifact,
  QuantCommand,
  QuantRunEvent,
  QuantRunState,
  QuantWorkspaceSnapshot,
} from '../../quant-domain';

export type QuantTone = 'neutral' | 'info' | 'warning' | 'positive' | 'danger';
export type QuantViewAction = 'open_report' | 'compare_candidates' | 'open_diagnostics';

export interface QuantActivityPresentation {
  id: string;
  title: string;
  summary: string;
  timestamp: string;
  actorLabel: string;
  artifactId?: string;
  advanced: { eventType: string; sequence: number; safeSummary: string };
}

export interface QuantActionPresentation {
  kind: QuantCommand | QuantViewAction;
  label: string;
  tone: 'primary' | 'default';
}

export interface QuantCandidatePresentation {
  id: string;
  name: string;
  verdictLabel: string;
  verdictTone: QuantTone;
  reason: string;
}

export interface QuantWorkspacePresentation {
  statusLabel: string;
  statusTone: QuantTone;
  currentActionTitle: string;
  currentActionPurpose: string;
  completedStepCount: number;
  negativeConclusion: boolean;
  activity: QuantActivityPresentation[];
  actions: QuantActionPresentation[];
  candidates: QuantCandidatePresentation[];
  primaryArtifacts: QuantArtifact[];
}

const stateCopy: Record<QuantRunState, [string, QuantTone, string, string]> = {
  draft: ['Ready', 'neutral', 'Research scope is ready', 'Generate a plan from the bounded goal and configured limits.'],
  planning: ['Planning', 'info', 'Generating a structured plan', 'The fixture API owns this planning state.'],
  waiting_plan_approval: ['Waiting for plan approval', 'warning', 'Plan approval is required', 'Review the frozen scope and limits before execution.'],
  queued: ['Queued', 'info', 'Waiting for deterministic execution', 'Execution can begin only after the required approval record exists.'],
  loading_data: ['Loading data', 'info', 'Loading the approved dataset', 'The pinned fixture snapshot is being verified.'],
  generating_candidates: ['Generating candidates', 'info', 'Generating bounded candidates', 'Candidate count cannot exceed the approved experiment limit.'],
  running_experiments: ['Ready to run', 'info', 'Approved synthetic Agent is ready', 'Start the bounded deterministic run; all outputs remain synthetic and API-owned.'],
  repairing: ['Repairing', 'warning', 'Repairing a candidate-scoped failure', 'A recoverable candidate issue does not mean the run failed.'],
  validating: ['Validating', 'info', 'Validating robustness', 'The validator is assigning candidate verdicts independently from run health.'],
  generating_report: ['Generating report', 'info', 'Generating the Research Report', 'Persisted results and limitations are being assembled.'],
  waiting_for_review: ['Waiting for review', 'warning', 'Research results need review', 'Review findings and the report draft before completing the process.'],
  completed: ['Completed', 'positive', 'Research process completed', 'Candidate B is retained for paper-evaluation review; Candidate A was rejected without failing the run.'],
  failed: ['Failed safely', 'danger', 'The run stopped safely', 'Persisted artifacts remain available for diagnosis and a new attempt.'],
  cancelled: ['Cancelled', 'neutral', 'The run was cancelled', 'Events and artifacts recorded before cancellation remain immutable.'],
};

const eventCopy: Record<string, string> = {
  'run.created': 'Research attempt created',
  'plan.generated': 'Research plan generated',
  'review.required': 'Your review is required',
  'plan.approved': 'Plan approved',
  'data.load.started': 'Loading the approved dataset',
  'data.load.completed': 'Dataset snapshot loaded',
  'benchmark.generated': 'Benchmark prepared',
  'candidate.generated': 'Candidate generated',
  'backtest.started': 'Fixture experiment started',
  'backtest.completed': 'Fixture experiment completed',
  'backtest.failed': 'Candidate experiment stopped safely',
  'repair.started': 'Repair attempt started',
  'repair.completed': 'Repair attempt completed',
  'validation.started': 'Robustness validation started',
  'validation.completed': 'Robustness validation completed',
  'candidate.rejected': 'Candidate rejected by validator',
  'candidate.promoted': 'Candidate retained for paper evaluation',
  'report.generated': 'Research Report generated',
  'run.completed': 'Research process completed',
  'run.cancelled': 'Run cancelled; retained work remains',
  'run.failed': 'Run stopped safely',
};

const actorCopy: Record<QuantRunEvent['actor'], string> = {
  user: 'User', system: 'System', agent: 'Agent', validator: 'Validator',
};

const verdictCopy: Record<CandidateVerdict, [string, QuantTone]> = {
  promising: ['Candidate for paper evaluation', 'positive'],
  inconclusive: ['Inconclusive', 'warning'],
  rejected: ['Rejected', 'danger'],
  invalid: ['Invalid candidate', 'neutral'],
};

const commandLabels: Partial<Record<QuantCommand, string>> = {
  approve_plan: 'Approve Plan',
  run_fixture: 'Run Synthetic Agent',
  request_plan_changes: 'Request Changes',
  approve_execution: 'Approve Once',
  cancel_run: 'Cancel Run',
  retry_run: 'Retry as New Attempt',
  complete_review: 'Complete Review',
  start_new_run: 'Start New Run',
};

function presentActivity(event: QuantRunEvent): QuantActivityPresentation {
  const knownTitle = eventCopy[event.type];
  return {
    id: event.id,
    title: knownTitle ?? 'Run activity recorded',
    summary: knownTitle ? event.safeSummary : 'A durable run event was recorded. Open Advanced Inspector for its safe diagnostic fields.',
    timestamp: event.timestamp,
    actorLabel: actorCopy[event.actor],
    artifactId: event.artifactId,
    advanced: { eventType: event.type, sequence: event.sequence, safeSummary: event.safeSummary },
  };
}

function presentActions(snapshot: QuantWorkspaceSnapshot): QuantActionPresentation[] {
  const actions: QuantActionPresentation[] = [];
  if (snapshot.run.state === 'waiting_for_review') {
    actions.push({ kind: 'open_report', label: 'Open Report Draft', tone: 'primary' });
    actions.push({ kind: 'compare_candidates', label: 'Review Validation Findings', tone: 'default' });
  }
  if (snapshot.run.state === 'completed') {
    actions.push({ kind: 'open_report', label: 'Open Report', tone: 'primary' });
    actions.push({ kind: 'compare_candidates', label: 'Compare Candidates', tone: 'default' });
  }
  if (snapshot.run.state === 'failed') actions.push({ kind: 'open_diagnostics', label: 'Open Diagnostics', tone: 'default' });
  for (const command of snapshot.run.legalCommands) {
    const label = commandLabels[command];
    if (label) actions.push({ kind: command, label, tone: actions.length === 0 ? 'primary' : 'default' });
  }
  return actions;
}

export function presentQuantWorkspace(snapshot: QuantWorkspaceSnapshot): QuantWorkspacePresentation {
  const [statusLabel, statusTone, currentActionTitle, currentActionPurpose] = stateCopy[snapshot.run.state];
  const negativeConclusion = snapshot.candidates.every((candidate) => candidate.verdict !== 'promising');
  return {
    statusLabel,
    statusTone,
    currentActionTitle,
    currentActionPurpose,
    completedStepCount: snapshot.plan.filter((step) => step.status === 'completed').length,
    negativeConclusion,
    activity: [...snapshot.events].sort((left, right) => right.sequence - left.sequence).map(presentActivity),
    actions: presentActions(snapshot),
    candidates: snapshot.candidates.map((candidate) => {
      const [verdictLabel, verdictTone] = verdictCopy[candidate.verdict];
      return { id: candidate.id, name: candidate.name, verdictLabel, verdictTone, reason: candidate.verdictReason };
    }),
    primaryArtifacts: [...snapshot.artifacts].sort((left, right) => Number(right.type === 'research_report') - Number(left.type === 'research_report')),
  };
}
