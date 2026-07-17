# Agent Workspace State Matrix

The presentation model uses domain state and persisted artifacts; it does not add lifecycle values to `Investigation` or `ResearchRun`.

## Primary session states

| Presentation state | Source conditions | Current step | Visible emphasis | Available actions |
| --- | --- | --- | --- | --- |
| Ready to Start | `run = null`; scope and goal exist | Confirming approved scope | Header, expected plan, frozen scope | Start only when an existing start command is wired; otherwise no invented action |
| Preparing | Run `queued` | Confirming approved scope | Current action and queued activity | Cancel |
| Running | Run `running`; no proposals yet | Latest mapped event, defaulting to Preparing approved sources | Running status, live activity, Plan Rail | Cancel |
| Waiting for Evidence Review | Run complete or Investigation reviewing; proposed evidence exists | Review evidence (human gate) | Action Center and Evidence proposal cards | Review evidence |
| Waiting for Findings Review | Evidence reviewed; proposed/needs-review findings exist | Review findings (human gate) | Action Center and Finding proposal cards | Review findings |
| Waiting for Synthesis Review | Verified findings and synthesis needs review | Review synthesis (human gate) | Action Center and synthesis preview | Existing synthesis review actions |
| Completed | Verified synthesis or completed Investigation with completed review path | Approve/open Decision Brief | Result summary and handoff | Create/Open Decision Brief only when backed by existing state |
| Needs Input | Run `waiting_for_input` | Exact waiting step if mapped; otherwise human gate | Waiting reason, retained work | Cancel; no free-text Continue |
| Failed Safely | Run `failed` | Failed mapped step or latest safe activity | Safe failure summary and retained artifacts | Retry when existing API allows; Cancel only when valid |
| Cancelled | Run `cancelled` or Investigation `cancelled` | No active step | Cancelled status and retained artifacts | Retry when existing API allows |

## Run-state mapping

| `ResearchRun.state` | Agent status | Tone | Active control |
| --- | --- | --- | --- |
| `queued` | Preparing | info | Cancel |
| `running` | Running | info | Cancel |
| `waiting_for_input` | Needs input | warning | Cancel |
| `completed` with proposals awaiting review | Waiting for review | warning | Contextual review action |
| `completed` with verified synthesis | Completed | positive | Decision Brief handoff |
| `failed` | Failed | destructive | Retry |
| `cancelled` | Cancelled | neutral | Retry |
| no run | Ready to start | neutral/info | Start only where wired |

## Product-step mapping

| Internal event/node signal | Product step | Owner |
| --- | --- | --- |
| `validate_manifest`, `run.queued` | Confirming approved scope | System |
| `bound_content`, `run.started` before artifacts | Preparing approved sources | Agent |
| `propose_evidence`, `evidence.proposed` | Analyzing evidence | Agent |
| `validate_evidence` or persisted validated evidence | Verifying citations | System |
| `propose_claim`, `claim.version_proposed` | Drafting findings | Agent |
| `require_human_review`, completed run with proposals | Waiting for your review | Human |

Unknown event types never become invented steps. They are summarized as “Run activity recorded” and keep the original technical event name only in Advanced disclosure.

## Artifact and gate rules

| Condition | Pending human action | Gate status |
| --- | --- | --- |
| Any evidence is `proposed` | Review evidence | Waiting |
| All evidence reviewed and any finding is `proposed` or `needs_review` | Review findings | Waiting |
| Findings verified and no synthesis | Create synthesis through existing flow | Waiting |
| Synthesis `draft` or `needs_review` | Review synthesis | Waiting |
| Synthesis `verified` and no Decision Brief in current workspace | Create Decision Brief | Waiting |
| No pending review and verified synthesis/brief handoff exists | None | Completed |
| Evidence rejected/weak | It remains human-reviewed; it is never relabeled “verified evidence” | Completed review, non-positive outcome |

## Component visibility

| State | Header | Plan | Current action | Action Center | Activity | Artifacts | Inspector |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ready | yes | expected | yes | start only if wired | scope-created item | scope | run/scope |
| Running | yes | active | yes | no review action | live safe projection | persisted only | run |
| Waiting review | yes | human gate | yes | yes | safe projection | proposals | selected/run |
| Completed | yes | complete | yes | handoff if valid | full projection | reviewed outputs | result/run |
| Failed | yes | failed | yes | failure | retained projection | retained only | diagnostics |
| Offline | yes | last known | cached warning | no writes | last known | cached | run + offline |

## Model policy states

| Policy/data state | Presentation |
| --- | --- |
| Deterministic scope | “Deterministic research”; “No model egress” |
| Model allowed and run is model-assisted | “Model-assisted research” plus egress disclosure with available provider/model and run-scoped boundary |
| Model requested but provider provenance missing | Warning in Inspector; do not claim review readiness from generation method alone |
| Workspace policy disables model | Model option disabled in launch UI with policy explanation; no fake settings link |
| Imported-upload consent only | Does not imply model egress approval |

## Budget rules

- Always show configured maximum cost and duration when available.
- Show used cost only when a trustworthy API value is explicitly available and labeled as usage.
- A zero or absent usage value must not be converted into fabricated spend.
- Never derive a progress percentage from elapsed time, event count, or artifact count.

## Offline and connection rules

- Offline is a workspace condition, not a run failure.
- SSE reconnect/reset belongs in Run Inspector and must not relabel the Agent as failed.
- Cached artifacts remain readable and retain authenticity labels.
- All mutations, source fetches, retry/cancel commands requiring the API, and new runs remain disabled offline.
