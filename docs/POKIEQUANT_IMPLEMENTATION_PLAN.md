# PokieQuant Phase 0 Implementation Plan

Status: proposed implementation sequence; no product code implemented by this document set

Baseline: `glint-agent-workspace-baseline` / `eb9a4be58c4a16b790d0b7568735c53a3627fe51`

## 1. Delivery strategy

Implement one additive Quant vertical slice alongside retained Glint modules. Reuse the governed shell/runtime patterns, not the product-intelligence aggregates. Freeze contracts and transition semantics before UI, API, and worker work diverge.

The Phase 0 vertical slice is:

```text
Create project → freeze scope → generate/approve plan
→ approve deterministic payload → worker emits fixture events
→ compare candidates → review report → complete/cancel/retry
```

The slice must work through API snapshots after refresh. A frontend-only state machine or JSX-embedded script does not satisfy Phase 0.

## 2. Architectural decisions

### 2.1 Parallel Quant domain

Add Quant contracts and modules. Do not rename or reuse `Signal`, `Investigation`, `Evidence`, `ClaimVersion`, `InvestigationSynthesis`, or `DecisionBrief` as financial objects.

### 2.2 API as lifecycle authority

FastAPI owns authorization, workspace scoping, optimistic concurrency, idempotent commands, approval legality, audit, snapshots, and SSE/cursor replay. The worker may transition only an approved attempt with a valid lease/fence. React submits commands and projects results.

### 2.3 Durable runtime and fixture boundary

The normal local Phase 0 path persists Quant lifecycle records/events in additive PostgreSQL tables. The E2E fixture server may use an isolated deterministic repository, but it must implement the same contracts, command guards, idempotency, cursor behavior, refresh recovery, and authenticity labels. Browser memory/local storage is not authoritative.

### 2.4 Presentation boundary

`quant-presentation.ts` is a pure projection from Quant snapshots/events/artifacts to component models. Components do not parse raw event strings, choose verdicts, or infer lifecycle state.

### 2.5 Spark and market adapters

Define narrow future ports only:

```text
QuantExecutionRuntime
MarketDataAdapter
MarketEventAdapter
```

No Spark runtime or PokieTicker code enters Phase 0. PokieTicker remains pending repository, immutable commit, file-path, license, modification, and notice review.

## 3. Directory-by-directory implementation order

The order below is a dependency order, not a suggestion to perform a repository-wide rename.

### Step 0 — Foundation documents

Owned paths:

```text
docs/POKIEQUANT_*.md
```

Freeze product language, IA, state matrix, reference boundary, roadmap, baseline SHA, and do-not-touch zones. Review these before product-code work. Keep the upstream tag immutable.

Exit: documents agree on enums, commands, fixture labels, negative-result semantics, and API ownership.

### Step 1 — Contract kernel

Owned paths:

```text
packages/contracts/quant/
packages/contracts/schemas/__init__.py        # one designated owner
packages/contracts/registry.py                # one designated owner
packages/contracts/openapi/openapi.snapshot.json
tests/contract/test_quant_*.py
```

Add closed Quant enums and Pydantic schemas for projects, scopes, plans, runs, approvals, events, datasets, experiments, metrics, trades, findings, artifacts, reports, commands, pages, and stream reset. Define one persistence-to-wire alias map and secret-free event payload union. Register schemas and regenerate the OpenAPI snapshot.

Exit:

- enum and schema drift tests pass;
- invalid event payloads fail closed;
- candidate verdict and run state are separate;
- no Glint product-intelligence type is used as a Quant alias.

### Step 2 — API domain and persistence

Owned paths:

```text
services/api/app/modules/quant/
services/api/app/api/routes_quant.py
services/api/app/db/models.py                 # one designated owner
services/api/app/main.py                      # one designated owner
infra/migrations/versions/*quant*.py
tests/integration/test_quant_*.py
tests/security/test_quant_*.py
```

Add additive tables/repositories for project, immutable scope/plan versions, run attempts, approvals, dataset snapshots, experiments, findings, artifacts, events, and audit links. Add `/v1/quant/...` routes and typed presenters.

Required commands:

```text
POST /v1/quant/projects
PATCH /v1/quant/projects/{project_id}
POST /v1/quant/projects/{project_id}/runs
POST /v1/quant/runs/{run_id}/generate-plan
POST /v1/quant/runs/{run_id}/approve-plan
POST /v1/quant/runs/{run_id}/request-plan-changes
POST /v1/quant/runs/{run_id}/approve-execution
POST /v1/quant/runs/{run_id}/reject-execution
POST /v1/quant/runs/{run_id}/complete-review
POST /v1/quant/runs/{run_id}/cancel
POST /v1/quant/runs/{run_id}/retry
```

Required queries:

```text
GET /v1/quant/projects
GET /v1/quant/projects/{project_id}
GET /v1/quant/runs/{run_id}
GET /v1/quant/runs/{run_id}/events
GET /v1/quant/runs/{run_id}/stream
GET /v1/quant/runs/{run_id}/artifacts
GET /v1/quant/runs/{run_id}/experiments
GET /v1/quant/artifacts/{artifact_id}
```

Every mutation uses workspace authorization, expected version, idempotency/replay protection, audit logging, and legal transition guards. Cancel invalidates the worker fence; retry creates a new attempt.

Exit:

- API transition matrix tests pass;
- refresh returns current state and complete event cursor;
- cancellation prevents post-cancel writes;
- no-viable-candidate completes normally;
- RLS/workspace and safe-error tests pass.

### Step 3 — Deterministic fixture worker

Owned paths:

```text
services/worker/app/pipelines/quant_fixture.py
services/worker/app/repositories/quant_*.py
services/worker/app/contracts.py              # agreed additive section/owner
services/worker/app/main.py                   # one designated owner
fixtures/quant/
tests/runtime/test_quant_*.py
tests/integration/test_quant_fixture_*.py
```

Implement a scripted runner behind a narrow `QuantExecutionRuntime`-shaped port. It claims only queued, approved attempts; pins the dataset/plan/payload; uses fenced leases/heartbeats; emits contract-valid events idempotently; persists candidate/artifact results; and checks cancellation before every emission.

Canonical sequence:

```text
run.created → plan.generated → review.required
→ plan.approved → data.load.started → data.load.completed
→ benchmark.generated
→ candidate.generated:A → backtest.started:A → backtest.completed:A
→ candidate.generated:B → backtest.started:B → backtest.failed:B
→ repair.started:B → repair.completed:B → backtest.completed:B
→ candidate.generated:C → backtest.started:C → backtest.completed:C
→ validation.started → candidate.rejected:A → candidate.promoted:B
→ validation.completed → report.generated → review.required
→ [human completes review] → run.completed
```

The worker pauses in `waiting_for_review` after `review.required`. The API appends `run.completed` only after the exact report/finding review contract is satisfied. Fixture snapshots must remain internally consistent. Candidate B’s backtest failure is recoverable and candidate-scoped, not `run.failed`.

Exit:

- normal, repair, no-viable, failed-safe, and cancellation scripts are deterministic;
- a replay never duplicates terminal events;
- old fences cannot write;
- normal demo delay is configurable at 400–900ms and E2E can advance immediately;
- all generated values carry fixture authenticity.

### Step 4 — Mac transport and state projection

Owned paths:

```text
apps/mac/src/quant-domain.ts
apps/mac/src/quant-api.ts
apps/mac/src/features/quant/quant-state.ts
apps/mac/src/features/quant/quant-presentation.ts
apps/mac/src/features/quant/__tests__/
```

Split/reuse the generic REST and run-stream behavior without expanding the existing 911-line product-specific `api.ts`. Add Quant DTO mapping, cursor recovery, duplicate suppression, snapshot reset, and pure presentation tests.

Projection tests cover every run state, plan step, known/unknown event, verdict, gate, button visibility, budgets, authenticity, safe errors, completed-with-no-viable-candidate, and negative-conclusion-versus-failure rule.

Exit: component input models contain no raw runtime parsing requirement and no `any`.

### Step 5 — Workspace shell and navigation

Owned paths:

```text
apps/mac/src/features/quant/QuantWorkspace.tsx
apps/mac/src/features/quant/QuantHeader.tsx
apps/mac/src/features/quant/QuantModeSwitcher.tsx
apps/mac/src/features/quant/QuantGoalComposer.tsx
apps/mac/src/features/quant/QuantPlanRail.tsx
apps/mac/src/features/quant/QuantActivityFeed.tsx
apps/mac/src/features/quant/QuantActionCenter.tsx
apps/mac/src/features/quant/QuantArtifactCard.tsx
apps/mac/src/features/quant/QuantInspector.tsx
apps/mac/src/features/workbench/Workbench.tsx   # one integration owner
```

Generalize presentational primitives from the Glint Agent Workspace where semantics remain generic. Do not copy the full component tree or pass Glint Investigation/Evidence/DecisionBrief props into Quant components. Replace active navigation with New Research, Projects, Runs, Data, and Settings while leaving retained Glint modules untouched outside the main path.

Implement wide, medium, and compact compositions, legal controls, focus management, keyboard shortcuts, offline read-only behavior, and persistent pane preferences.

Exit: Ready, Plan Approval, Running, Repairing, Validating, Waiting Review, Completed, No Viable Candidate, Failed Safe, and Cancelled render from API/fixture snapshots.

### Step 6 — Market and strategy workspace

Owned paths:

```text
apps/mac/src/features/quant/QuantMarketWorkspace.tsx
apps/mac/src/features/quant/QuantMarketToolbar.tsx
apps/mac/src/features/quant/QuantCandlestickChart.tsx
apps/mac/src/features/quant/QuantStrategyReport.tsx
apps/mac/src/features/quant/QuantMetricsStrip.tsx
apps/mac/src/features/quant/QuantExperimentTable.tsx
apps/mac/src/features/quant/QuantTradeTable.tsx
apps/mac/src/features/quant/QuantRobustnessPanel.tsx
apps/mac/src/features/quant/QuantResearchReport.tsx
apps/mac/package.json
pnpm-lock.yaml
THIRD_PARTY_NOTICES.md
```

If selected after dependency review, pin `echarts@6.1.0` exactly, update the lockfile and notices in the same slice, and add license/tooltip-sanitization tests. Do not use a proprietary TradingView widget or copy TradingView assets/source.

Render the canonical metrics, market bars, indicators, trades, markers, findings, strategy spec, safe logs, and report. Chart data remains immutable fixture data.

Exit: chart interaction, table keyboard use, textual chart summary, benchmark comparison, and fixture labels pass component/E2E checks.

### Step 7 — Fixtures, E2E, screenshots, and integration

Owned paths:

```text
apps/mac/e2e/quant-*.spec.ts
docs/assets/pokiequant/
scripts/verify_pokiequant_shell.sh
tests/license/*
README.md
```

Add `POKIEQUANT_E2E_RUN_STATE` server-side fixture selection and all ten required states. Capture 1440×960 real-workbench screenshots for Ready, Plan Approval, Running, Repairing, Completed, and No Viable Candidate. Update README only after implementation reality is known.

The additive verification script must check Quant contracts, API, fixture worker, unit/component/build/E2E/screenshots, license policy, fixture labels, and absence of active Glint product-intelligence copy. It must not remove or weaken inherited gates.

Exit: complete demo flow and all required alternative flows pass from a clean environment.

## 4. Reuse and extraction rules

Reuse directly where responsibility remains generic:

- `WorkbenchLayout.tsx` resizable/collapsible layout and stored sizes;
- Agent Header/Plan/Activity/Action/Artifact/Inspector anatomy through shared presentational primitives;
- safe `RunEvent` mapping pattern and `useRunStream` cursor/reset behavior;
- FastAPI authentication, workspace context, errors, idempotency, optimistic concurrency, audit, RLS, and presenters;
- worker lease/fencing/heartbeat and repository-adapter style;
- Pydantic registry/OpenAPI drift testing;
- Vitest, Playwright, fixture server, screenshots, and quality gates.

Generalize only behind tests. Avoid a repository-wide Glint-to-PokieQuant rename until the Quant vertical slice is stable. Compatibility aliases, if required, must be bounded and scheduled for removal.

## 5. Do-not-touch zones

Phase 0 should not modify except for a proven minimal shared extraction with regression tests:

- `connectors/` GitHub/RSS collection;
- imported CSV consent/upload/finalization/object-store lineage;
- Signal/Watchlist/detection and score semantics;
- Evidence/Claim/Synthesis/Decision Brief/export semantics;
- model-research/DeepSeek/prompt-provider paths;
- production auth, RLS, secret handling, SSRF, and append-only audit guarantees;
- existing migrations (new Quant migrations are additive);
- live connector/model smoke behavior;
- historical Glint screenshots and acceptance records.

Do not modify `THIRD_PARTY_NOTICES.md` until a dependency is actually added.

## 6. Conflict ownership

The following hotspots require one integration owner per slice:

- `apps/mac/src/features/workbench/Workbench.tsx`
- `apps/mac/src/domain.ts`
- `apps/mac/src/api.ts`
- global styles
- contract registry and OpenAPI snapshot
- API main/model registration
- worker main/contracts registration
- package manifests, lockfile, and third-party notices

Prefer new Quant modules over simultaneous edits to monolith files. Merge the contract kernel before parallel API/worker/UI work.

## 7. Test plan

### Unit/presentation

- all state and step projections;
- known/unknown event mapping;
- candidate verdict independent of run state;
- every human gate and legal control;
- no fake progress/cost/token use;
- fixture labels and budget formatting;
- completed with no viable candidate;
- failure versus negative conclusion.

### API/security

- create/list/get project and run;
- plan generation/approval/change request;
- invalid-state and stale-version commands;
- execution approval digest binding;
- cancel idempotency and worker fencing;
- retry attempt isolation;
- cursor pagination, SSE replay/reset, artifacts, fixtures;
- workspace authorization/RLS, redaction, and audit.

### E2E

1. full run through Candidate B and Research Report;
2. request plan changes, regenerate, approve;
3. cancel, assert no new events, retry as new attempt;
4. all candidates fail validation but run completes;
5. safe worker failure, diagnostics, retry.

### Visual/accessibility

- 1440×960 screenshots from the real workbench;
- minimum 960×720 segments;
- keyboard/focus/focus-return/reduced-motion;
- chart summary and non-color status;
- no secret, terminal, DevTools, private path, or unlabeled fixture.

## 8. Verification order

Run focused checks after each slice, then the full inherited/additive gates:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
GLINT_E2E_API_MODE=fixture pnpm test:e2e
./scripts/verify_pokiequant_shell.sh
./scripts/verify_phase2.sh
./scripts/verify_phase3_quality.sh
./scripts/verify_tauri_runtime.sh
git diff --check
```

Live connector/model checks remain opt-in and are not enabled to validate Phase 0 fixtures.

## 9. Rollback boundaries

- Contract/API additions are namespaced and can be disabled without changing Glint routes.
- Quant worker registration can be removed without touching existing research/model/collection pipelines.
- Quant navigation can be switched away from the main shell without deleting retained Glint modules.
- Market/report components are renderer-only consumers of stable presentation data.
- ECharts, if added, is isolated to the market slice and removable with its notice/lockfile changes.

## 10. Completion evidence

Phase 0 is complete only when code, tests, screenshots, README, notices, and implementation claims agree. A plan, scaffold, or static screenshot is not completion. The additive pure daily-bar kernel now derives the synthetic candidate/report projection from 1,564 generated weekday bars; the next slice is:

> Add a governed immutable imported-dataset path and split-sample validation while preserving the synthetic dataset as an exact regression oracle.
