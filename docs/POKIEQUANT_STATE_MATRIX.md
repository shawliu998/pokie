# PokieQuant Phase 0 State Matrix

Status: contract and transition authority

## 1. State ownership

PokieQuant separates four kinds of state that must not be collapsed:

| State family | Owner | Purpose |
| --- | --- | --- |
| Project/scope/plan | API domain service | durable goal, immutable versions, approval history |
| Run lifecycle | API domain service; worker submits fenced transitions | attempt health and execution position |
| Candidate verdict | validator/result records | quality of one hypothesis under configured checks |
| Presentation | pure client projection | wording, tone, current action, visible legal controls |

The API is authoritative for every lifecycle transition. The worker may request only transitions allowed by its approved execution contract and current fenced lease. The UI sends commands; it never assigns a run state.

## 2. Closed Phase 0 enums

### Research mode

```typescript
type ResearchMode = 'ask' | 'plan' | 'auto_research';
```

Ask is read-only and does not create a run. Plan creates/revises a plan. Auto Research requires an approved plan.

### Run state

```typescript
type QuantRunState =
  | 'draft'
  | 'planning'
  | 'waiting_plan_approval'
  | 'queued'
  | 'loading_data'
  | 'generating_candidates'
  | 'running_experiments'
  | 'repairing'
  | 'validating'
  | 'generating_report'
  | 'waiting_for_review'
  | 'completed'
  | 'failed'
  | 'cancelled';
```

Execution approval is an orthogonal approval record while a run is `queued`. A queued run with `execution_approval=pending` presents as **Waiting for execution approval** and is not claimable. This preserves the required run-state vocabulary without treating an approval gate as worker execution.

### Step status

```typescript
type StepStatus =
  | 'pending'
  | 'active'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'skipped';
```

### Candidate verdict

```typescript
type CandidateVerdict =
  | 'promising'
  | 'inconclusive'
  | 'rejected'
  | 'invalid';
```

### Approval target and decision

```typescript
type ApprovalTarget =
  | 'plan'
  | 'execution_payload'
  | 'uploaded_code_execution'
  | 'simulated_deployment'
  | 'risk_limit_change'
  | 'external_network';

type ApprovalDecision = 'pending' | 'approved_once' | 'rejected' | 'changes_requested';
```

Only `plan` and deterministic `execution_payload` gates are actionable in the Phase 0 main flow. The other targets are contract placeholders with disabled capability and no execution path.

## 3. Primary presentation matrix

| Presentation state | Source condition | Current emphasis | Legal actions |
| --- | --- | --- | --- |
| Ready | no active run; project/scope draft exists | Goal Composer and limits | Generate Plan; Cancel draft |
| Planning | run `planning` | structured plan generation activity | Cancel |
| Waiting plan approval | `waiting_plan_approval`; latest plan pending | plan diff, limits, human gate | Approve Plan; Request Changes; Cancel |
| Waiting execution approval | `queued`; plan approved; execution approval pending | immutable payload and disabled policies | Review Payload; Approve Once; Reject; Cancel |
| Queued | `queued`; required approvals satisfied | awaiting deterministic worker claim | Cancel |
| Loading data | `loading_data` | dataset snapshot and authenticity | Cancel |
| Generating candidates | `generating_candidates` | candidate family/limit | Cancel |
| Running experiments | `running_experiments` | actual experiment counter and latest candidate | Cancel |
| Repairing | `repairing` | failed experiment, repair count, safe error | Cancel |
| Validating | `validating` | robustness checks and findings | Cancel |
| Generating report | `generating_report` | comparison and report artifact | Cancel when server permits |
| Waiting review | `waiting_for_review` | results, findings, report draft | Review Candidate; Review Findings; Open Draft |
| Completed | `completed` | final report and next research step | Open Report; Compare; Start New Run |
| Completed, no viable candidate | `completed`; all verdicts rejected/invalid/inconclusive | negative conclusion and limitations | Open Report; Compare; Start New Run |
| Failed safely | `failed` | retained events/artifacts and safe diagnostics | Retry; Open Diagnostics; Start New Run |
| Cancelled | `cancelled` | stop point and retained work | Retry as New Attempt; Start New Run |
| Offline | last API snapshot plus offline flag | cached/read-only warning | no writes; no retry/cancel/start |

Offline and SSE reconnect/reset are client connection conditions. They do not relabel a run as `failed`.

## 4. API-owned transition table

Every command requires authenticated workspace scope, an expected row version, and an idempotency key or equivalent replay key. Success writes the state change, command result, audit record, and associated event in one transaction where possible.

| Current | Command / actor | Guard | Next | Required event/audit effect |
| --- | --- | --- | --- | --- |
| none | `create_run` / user | current project and scope version | `draft` | `run.created`; immutable attempt 1 identity |
| `draft` | `generate_plan` / API fixture | valid frozen scope and budgets | `planning` | plan job/activity recorded |
| `planning` | plan generator completes | plan persisted and versioned | `waiting_plan_approval` | `plan.generated`, `review.required` |
| `waiting_plan_approval` | `approve_plan` / user | exact latest plan version | `queued` | approval record, `plan.approved`; create pending execution gate if configured |
| `waiting_plan_approval` | `request_plan_changes` / user | exact latest plan version and reason | `planning` | changes-request record; old plan retained |
| `queued` | `approve_execution` / user | plan approved; exact payload digest; gate pending | `queued` | one-time approval record; worker claim becomes legal |
| `queued` | worker claim | all required approvals satisfied; active lease/fence | `loading_data` | `data.load.started`; started timestamp |
| `loading_data` | fixture worker | dataset snapshot verified and pinned | `generating_candidates` | `data.load.completed`, `benchmark.generated` |
| `generating_candidates` | fixture worker | candidate artifact persisted | `running_experiments` | `candidate.generated`, `backtest.started` |
| `running_experiments` | fixture worker | another candidate remains | `generating_candidates` | `backtest.completed` or candidate-scoped failure event |
| `running_experiments` | fixture worker | recoverable candidate-scoped failure and repair budget remains | `repairing` | `backtest.failed`, `repair.started` |
| `repairing` | fixture worker | repair artifact persisted, fence valid | `running_experiments` | `repair.completed`, then new backtest event |
| `running_experiments` | fixture worker | experiment budget exhausted/completed | `validating` | `validation.started` |
| `validating` | fixture worker/validator | all findings and verdicts persisted | `generating_report` | candidate verdict events, `validation.completed` |
| `generating_report` | fixture worker | report artifact and hashes persisted | `waiting_for_review` | `report.generated`, `review.required` |
| `waiting_for_review` | `complete_review` / user/API | report/finding review contract satisfied | `completed` | review record, `run.completed` |
| any cancellable nonterminal | `cancel` / user | current version; not terminal | `cancelled` | lease invalidated, `run.cancelled`; no later events |
| `failed` or `cancelled` or `completed` | `retry` / user | source/scope still usable or explicitly repinned | new attempt `draft` or `queued` | previous attempt unchanged; new `run.created` |
| active execution state | safe worker failure | valid fence; safe error persisted | `failed` | `run.failed`; retained artifacts/events |

Idempotent replay returns the original command result and does not append a duplicate event. Concurrent stale commands return a version conflict. Terminal run records are immutable except for append-only review/audit metadata allowed by contract.

## 5. Cancel and retry rules

### Cancel

- legal from `draft` through `generating_report` and from approval-wait states when the API says cancellable;
- terminal states return the existing terminal result rather than create another cancellation;
- atomically marks the attempt cancelled and invalidates/advances the worker fence;
- a worker with an old lease cannot append events or artifacts afterward;
- already persisted events and artifacts remain visible.

### Retry

- creates `attempt_number + 1` with a new Run ID and event sequence beginning at 1;
- copies only explicitly permitted frozen inputs or repins current approved versions;
- never changes the prior attempt’s state, events, artifacts, verdicts, or hashes;
- reruns approval when the payload/scope/dataset/limits differ;
- has its own idempotency key and audit record.

## 6. Candidate verdict versus run outcome

| Candidate result | Candidate verdict | Run effect |
| --- | --- | --- |
| stable enough under configured checks | `promising` | may contribute to completed report |
| evidence insufficient or mixed | `inconclusive` | run continues/completes |
| robustness rule fails | `rejected` | run continues/completes |
| malformed inputs or non-comparable result | `invalid` | run continues if process remains healthy |
| candidate calculation throws but is isolated and recorded | `invalid` or no verdict | run may repair or continue within budget |
| worker/API/storage failure prevents contract completion | none required | run `failed` |

The canonical negative terminal result is:

```text
Run state: completed
Conclusion: No candidate passed validation
Artifact: Research Report retained
```

`completed` must not be styled as `promising`, and `rejected` must not be styled as a run failure.

## 7. Plan-step projection

| Plan step | Owner | Active source conditions | Completion evidence |
| --- | --- | --- | --- |
| Define research scope | User/System | `draft`, `planning`, `waiting_plan_approval` | approved plan/scope version |
| Load market dataset | System | `loading_data` | dataset snapshot artifact and `data.load.completed` |
| Build benchmark | System | end of loading | benchmark artifact/event |
| Generate candidates | Agent | `generating_candidates` | candidate/strategy-spec artifacts |
| Run experiments | Agent/System | `running_experiments` | terminal candidate backtest artifacts |
| Repair failures | Agent/System | `repairing` | repair event/artifact; skipped if no repair |
| Validate robustness | Validator | `validating` | validation report/findings |
| Compare candidates | Agent/System | after validation | comparison artifact/model |
| Generate report | Agent/System | `generating_report` | research report artifact |
| Human decision | User | `waiting_for_review` | review record; remains completed after decision |

Unknown events never activate a step. If snapshot state and known events disagree, the snapshot state controls status while the discrepancy is recorded in diagnostics.

## 8. Event-to-presentation matrix

| Event | Business copy | Step effect |
| --- | --- | --- |
| `run.created` | Research attempt created | scope pending/active |
| `plan.generated` | Research plan generated | scope waits |
| `review.required` | Your review is required | matching Human Gate waits |
| `plan.approved` | Plan approved | scope completed |
| `data.load.started` | Loading the approved dataset | data active |
| `data.load.completed` | Dataset snapshot loaded | data completed |
| `benchmark.generated` | Benchmark prepared | benchmark completed |
| `candidate.generated` | Candidate generated | candidate count updates |
| `backtest.started` | Fixture experiment started | experiments active |
| `backtest.completed` | Fixture experiment completed | candidate artifact available |
| `backtest.failed` | Candidate experiment stopped safely | candidate-scoped warning; run not failed |
| `repair.started` | Repair attempt started | repair active |
| `repair.completed` | Repair attempt completed | repair count updates |
| `validation.started` | Robustness validation started | validation active |
| `validation.completed` | Robustness validation completed | validation completed |
| `candidate.rejected` | Candidate rejected by validator | verdict only |
| `candidate.promoted` | Candidate retained for paper evaluation | verdict only; no broker action |
| `report.generated` | Research Report generated | report completed |
| `run.completed` | Research process completed | run completed |
| `run.cancelled` | Run cancelled; retained work remains | run cancelled |
| `run.failed` | Run stopped safely | run failed |
| unknown | Run activity recorded | no invented step/conclusion |

Events contain only a closed, secret-free payload. The wire mapping must have one source of truth, following Glint’s existing `RunEvent` alias/validation pattern.

## 9. Artifact state rules

| Artifact status | Meaning | Permitted transition |
| --- | --- | --- |
| `draft` | incomplete/reviewable version | `ready`, `rejected` via API |
| `ready` | immutable generated result available | `reviewed`, `rejected` via review record |
| `reviewed` | exact version reviewed | terminal for that version |
| `rejected` | exact version rejected | terminal; revision is a new version |

Artifact authenticity (`synthetic_fixture`, `imported`, `generated`) is independent from review status. Phase 0 results additionally map to the visible `Synthetic Demo Fixture` or `Imported Demo Fixture` label; `generated` alone must never be presented as live data.

## 10. Fixture states

`POKIEQUANT_E2E_RUN_STATE` selects fixture state only in development/E2E server configuration. It is never exposed in production UI.

| Fixture | Required snapshot assertion |
| --- | --- |
| `quant-ready` | goal/scope present; no active execution; fixture label visible |
| `quant-plan-approval` | plan version pending; Approve/Changes/Cancel visible |
| `quant-running` | active known step; Cancel only; no fake progress |
| `quant-repairing` | candidate-scoped failure plus repair count; run not failed |
| `quant-validating` | validation active and candidate results retained |
| `quant-waiting-review` | report/findings available and review action visible |
| `quant-completed` | Candidate B retained; report completed |
| `quant-no-viable-candidate` | run completed; no candidate passed; report retained |
| `quant-failed-safe` | run failed; safe diagnostics and Retry visible |
| `quant-cancelled` | run cancelled; no post-cancel events |

Each fixture includes deterministic IDs, timestamps, sequence numbers, hashes clearly identified as fixture values, and authenticity labels. Reloading the route reproduces the same API snapshot.

## 11. Stream and recovery rules

PokieQuant reuses Glint’s cursor/SSE semantics:

- unique `event_id` and monotonically increasing per-run `sequence`;
- client duplicate suppression;
- gap detection followed by snapshot recovery;
- `stream.reset` as transport control, not business activity;
- heartbeat consumes no sequence;
- reconnect/reset appears in Advanced Inspector and never changes run health;
- terminal snapshot plus durable events ends subscription cleanly.

## 12. Control visibility rules

- Show a control only when the API snapshot exposes the matching legal command.
- Disable all mutations offline; cached artifacts remain readable.
- Never show Plan approval during running states.
- Never show Retry for a currently healthy active attempt.
- Never show Pause in Phase 0.
- Never show Start Paper Trading.
- Never infer `canStart`, `canCancel`, or `canRetry` solely from a client timer or local click history.
