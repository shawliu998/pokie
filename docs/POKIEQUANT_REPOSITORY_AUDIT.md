# PokieQuant Phase 0 Repository Audit

Status: historical baseline and read-only architecture audit

> This preserves the Glint-to-PokieQuant fork boundary and remains architecture provenance. Current
> product authority is `apps/mac/PRODUCT.md`, `apps/mac/DESIGN.md` and the capability inventory.

Audit date: 2026-07-17 (Asia/Shanghai)

Implementation status: no product functionality implemented

## Executive conclusion

PokieQuant should remain a history-preserving fork of the Glint Agent Workspace, but it must not be implemented as a vocabulary swap over Glint's product-intelligence domain. The reusable asset is the governed workspace and run infrastructure: resizable desktop shell, pure presentation projection, safe event feed, human-gate action center, durable `ResearchRun`/`RunEvent` mechanics, SSE recovery, API policy middleware, worker leases, auditability, deterministic fixtures, and the existing test harness.

The financial layer must be new and explicit: Quant projects/scopes/runs, datasets, market bars, experiments, strategy specs, backtest results, trades, validation findings, artifacts, and reports. Glint `Signal`, `Investigation`, `Evidence`, `ClaimVersion`, `InvestigationSynthesis`, and `DecisionBrief` must not be aliased into financial objects. Doing so would preserve the wrong lifecycle and would make negative research results indistinguishable from system failures or review decisions.

Phase 0 should therefore add a parallel Quant vertical slice behind stable contracts and reuse the generic shell/runtime patterns without modifying Glint's ingestion, model-research, evidence/claim, decision/export, or live connector behavior.

## 1. Git baseline and repository topology

| Item | Audited value |
| --- | --- |
| Local branch | `codex/pokiequant-shell` |
| Exact `HEAD` | `eb9a4be58c4a16b790d0b7568735c53a3627fe51` |
| Upstream branch | `glint-upstream/codex/phase31-agent-workspace-ui` |
| Upstream branch SHA | `eb9a4be58c4a16b790d0b7568735c53a3627fe51` |
| Baseline tag | `glint-agent-workspace-baseline` |
| Tag target | `eb9a4be58c4a16b790d0b7568735c53a3627fe51` |
| Baseline subject | `Build Phase 3.1 Agent Workspace UI` |
| Baseline commit time | `2026-07-17T12:40:59+08:00` |
| Baseline parent | `0f2e583a40756d50a47e0c4d37be566451e68127` |
| History depth at baseline | 23 commits |
| `origin` | `https://github.com/shawliu998/pokie.git` |
| `glint-upstream` | `https://github.com/shawliu998/Glint.git` |
| `origin` state observed | no refs returned by `git ls-remote origin` (empty target repository) |
| Upstream history handling | fetched and checked out directly; no copy/export and no history rewrite |

The target repository's public visibility was accepted by the user. This audit did not alter repository visibility, push any refs, create a commit, or rewrite Glint `main`.

At audit start the target directory was an empty Git repository with no commits on `main`. The requested Glint branch was fetched, its SHA was checked against the supplied immutable SHA, the local PokieQuant branch was created at that commit, and the local baseline tag was added at the same commit.

## 2. Instructions and material read

No `AGENTS.md` exists anywhere in the checked-out PokieQuant/Glint worktree. The pre-checkout empty directory likewise contained none.

The complete 2,142-line requirement attachment was read:

- `/Users/a1-6/.codex/attachments/be2cf92b-239a-4a54-9e83-41a8cec71bee/pasted-text.txt`

The following required repository documents were read:

- `README.md`
- `docs/AGENT_WORKSPACE_PRODUCT_SPEC.md`
- `docs/AGENT_WORKSPACE_INFORMATION_ARCHITECTURE.md`
- `docs/AGENT_WORKSPACE_STATE_MATRIX.md`
- `docs/AGENT_WORKSPACE_IMPLEMENTATION_PLAN.md`
- `docs/AGENT_WORKSPACE_ACCEPTANCE.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/API_CONTRACTS.md`
- `docs/SECURITY_MODEL.md`
- `THIRD_PARTY_NOTICES.md`

The two required Mac boundary files were read:

- `apps/mac/src/domain.ts`
- `apps/mac/src/api.ts`

All files were enumerated and inspected under the required source roots:

| Required root | Files | Lines | Audit focus |
| --- | ---: | ---: | --- |
| `apps/mac/src/features/agent/` | 10 | 1,082 | shell components, pure projection, fixtures, unit/component tests |
| `apps/mac/src/features/workbench/` | 2 | 243 | global orchestration, responsive panels, navigation integration |
| `services/api/` | 40 | 11,458 | routes, presenters, auth, state transitions, audit, persistence |
| `services/worker/` | 24 | 7,963 | worker protocol, job loop, deterministic/model pipelines, leases |
| `packages/contracts/` | 21 | 3,112 including the generated OpenAPI snapshot | enums, Pydantic schemas, RunEvent wire contract, schema registry |

The required review set contains 110 unique files. The generated `packages/contracts/openapi/openapi.snapshot.json` was treated as generated contract evidence; its registry and generation/drift code were also inspected.

For test and quality-gate discovery, `package.json`, `apps/mac/package.json`, `pyproject.toml`, `.github/workflows/verify.yml`, and the repository `scripts/` and test trees were inventoried. No source outside this audit document was edited.

## 3. Current architecture in one view

The baseline is a modular monolith plus an independent worker and a Tauri/React Mac client:

1. The React workbench consumes typed domain projections from `domain.ts`, mapping and API adapters, and a durable run-event stream.
2. `AgentWorkspace` composes header, plan rail, activity, action center, artifacts, and inspector from one pure `AgentSessionPresentation` produced by `agent-presentation.ts`.
3. FastAPI owns authorization, idempotency, optimistic concurrency, lifecycle commands, audit records, cursor pagination, SSE replay/reset, and safe error envelopes.
4. PostgreSQL is authoritative; append-only reviews/events and immutable versions provide provenance. Redis is coordination, and object storage holds immutable imported/collected bodies.
5. The worker claims fenced leases through `WorkerDomainAdapter`, reads a frozen run manifest, emits validated events, and submits proposals through domain services. It does not approve artifacts or create Decision Briefs.
6. Contracts are centralized in Pydantic schemas/enums and an OpenAPI snapshot. Persistence-to-wire `RunEvent` naming has one canonical alias map.

This layering is the right foundation for an auditable quant-research shell. The existing product-intelligence aggregates are not.

## 4. Directly reusable without financial-domain semantics

“Directly reusable” means the code's responsibility remains true for PokieQuant. Branding, package names, and narrow prop labels may still need mechanical changes.

### 4.1 Mac shell and interaction infrastructure

- `apps/mac/src/features/workbench/WorkbenchLayout.tsx`: resizable panels, collapsible sidebar, compact list/detail behavior, and saved layout state.
- `react-resizable-panels` usage and the existing four-pixel-density visual system.
- Command palette, global search infrastructure, native-menu bridge, keyboard hook patterns, focus return, offline read-only handling, and reduced-motion/focus tokens elsewhere in the Mac app.
- Cache/session boundaries and the authenticated REST adapter's common request handling.
- `useRunStream`, SSE cursor persistence, duplicate suppression, reset-to-snapshot behavior, and connection-state presentation.

### 4.2 Agent Workspace component anatomy

The following component responsibilities are reusable if fed Quant presentation models rather than Glint domain objects:

- `AgentHeader`: goal/status/mode/authenticity/limits and valid controls.
- `AgentPlanRail`: discrete steps, owner, status, artifacts, and no fake percentage.
- `AgentActivityFeed`: safe chronological events with technical detail collapsed.
- `AgentActionCenter`: only currently legal user actions.
- `AgentArtifactCard`: stable artifact anatomy without default UUID exposure.
- `AgentInspector`: default summary plus closed Advanced provenance.
- `AgentWorkspace`: desktop/compact composition and segment behavior.

The strongest reuse seam is not the component names; it is that components consume a stable presentation model and do not parse raw runtime events in JSX.

### 4.3 API and runtime kernel

- Authentication/workspace context, deny-by-default authorization, RLS context installation, safe error envelopes, request correlation, idempotency, and optimistic concurrency.
- Cursor pagination and typed API presenters.
- Append-only AuditLog and safe redaction patterns.
- `ResearchRun` attempt semantics: immutable scope/manifest, independent attempts, cancellable terminal state, and a failed attempt not rewriting its parent project.
- `RunEvent` append-only sequence, single persistence-to-wire mapping, safe payload schema, SSE replay, heartbeat, duplicate handling, and `stream.reset` recovery.
- Worker claim/lease/fencing/heartbeat patterns and the `WorkerDomainAdapter` abstraction style.
- Contract registry, enum-compatibility checks, Pydantic validators, OpenAPI generation, and drift tests.

### 4.4 Test and fixture infrastructure

- Vitest component/presentation tests and React static-markup tests.
- Playwright fixture API and real-workbench screenshot flow.
- Deterministic fixture-state selection through an environment variable rather than a production UI control.
- Existing API-contract, SSE, cache, session, import, authorization, RLS, license, and native-runtime gates as regression protection for retained Glint infrastructure.

## 5. Must be generalized or renamed

These elements are reusable in structure but currently leak Glint identity or its product-intelligence lifecycle.

| Current element | Required treatment | Reason |
| --- | --- | --- |
| `GlintApi`, `VITE_GLINT_*`, `GLINT_*`, `@glint/*`, app/bundle names | plan a controlled PokieQuant rename; keep compatibility aliases only during a bounded migration | mechanical identity is pervasive across JS, Python, Rust, fixtures, CI, and scripts |
| `AgentSessionPresentation` | extract a domain-neutral workspace-presentation core or create a parallel `QuantSessionPresentation` with shared primitives | current artifact/action unions encode evidence, findings, synthesis, and Decision Brief |
| `AgentWorkspace` props | replace direct `Investigation`, `Evidence`, and `DecisionBrief` dependencies with Quant presentation/callback contracts | current component falls back into Glint review tabs |
| `Workbench.tsx` | split destination orchestration and add the PokieQuant navigation model outside the large conditional render | it currently owns Inbox/Investigations/Decisions/Monitoring selection and product copy |
| `Destination` and navigation helpers | replace with `new_research`, `projects`, `runs`, `data`, `settings` | old first-level destinations are forbidden on the main demo path |
| `domain.ts` | keep existing types for retained Glint code; add dedicated Quant types/modules rather than renaming Signal/Claim types | a global rename would corrupt meaning and create a high-conflict file |
| `api.ts` | split common REST transport from product-specific commands; add a Quant client module | the current 911-line adapter mixes generic transport, imports, sources, research, reviews, and export |
| Research API routes | add a namespaced Quant resource surface, preferably `/v1/quant/...` to match the existing `/v1` convention | existing `/research-runs` requires an Investigation, Signal, Watchlist, and content lineage |
| Worker protocol | define a narrow `QuantExecutionRuntime`/Quant repository protocol rather than adding market methods to the already broad `WorkerDomainAdapter` | prevents connector/import/claim coupling and creates the Spark seam |
| fixture variables and copy | add `POKIEQUANT_E2E_RUN_STATE`/`VITE_POKIEQUANT_*` as required; do not silently reuse an `agent-*` variable with new meanings | fixture provenance and state selection must remain explicit |

Avoid a large first-pass repository-wide rename. The safer order is to establish the Quant contract/module boundary, put the new main path behind it, then retire Glint-only identifiers from active PokieQuant surfaces with tests guarding every step.

## 6. New financial domain required

The following are new domain concepts, not Glint aliases:

- `QuantResearchProject`
- versioned `QuantResearchScope`
- `QuantResearchRun` and attempt identity
- `QuantPlan`/plan approval record
- immutable `DatasetSnapshot` and authenticity/source metadata
- `MarketBarSeries` or another bounded OHLCV transport projection
- `QuantExperiment`/candidate, repair attempts, and execution assumptions
- versioned read-only `StrategySpec`
- `BacktestResult` and `BacktestMetrics`
- immutable `TradeRecord`/trade log artifact
- `ValidationFinding` and robustness result
- `CandidateVerdict` independent of system run state
- `QuantArtifact` with hash/authenticity/review status
- final `ResearchReport` plus reproduction/audit metadata
- Ask/Plan/Auto Research mode and explicit approval records

Required invariants:

1. A rejected or invalid candidate does not fail the run.
2. A run may complete with no viable candidate.
3. Negative research conclusions remain retained artifacts.
4. UI state comes from API/fixture state and events, never timers in React.
5. Plan approval, execution approval, cancellation, and retry are server-owned, idempotent commands.
6. Dataset, scope, strategy spec, validation versions, and artifact hashes are pinned to each attempt.
7. Every Phase 0 result is visibly `Synthetic Demo Fixture` or `Imported Demo Fixture`.
8. Unknown events degrade to safe generic copy and never invent a plan step.

Recommended module shape (subject to the contract slice):

```text
packages/contracts/quant/
services/api/app/modules/quant/
services/api/app/api/routes_quant.py
services/worker/app/pipelines/quant_fixture.py
services/worker/app/repositories/quant_*.py
apps/mac/src/features/quant/
apps/mac/src/quant-domain.ts
apps/mac/src/quant-api.ts
```

Whether Phase 0 persists Quant objects in new PostgreSQL tables or in a clearly isolated fixture repository is an implementation decision, but refresh recovery and API-owned transitions are acceptance requirements. A frontend-only state machine is not acceptable.

## 7. Phase 0 do-not-touch zones

The following code is mature, out of the Phase 0 product need, or carries security/provenance risk. It should remain unchanged unless a Quant contract demonstrably requires a small shared extraction with regression tests.

- `connectors/` and GitHub/RSS collection behavior.
- imported CSV consent, upload, finalization, object-store, and source-pointer lifecycle.
- Signal detection/scoring, Watchlists, source scheduling, and baseline detection.
- Evidence, EvidenceReview, ClaimVersion, ClaimReview, synthesis, Decision Brief readiness/freshness, and PRD export semantics.
- DeepSeek/model-research pipeline, model policy, prompt versions, and provider integration.
- production auth, RLS, secret handling, SSRF defenses, import security, and append-only audit behavior.
- existing migration history; any future Quant schema change must be additive.
- live connector smoke and production network behavior.
- existing Glint screenshots and acceptance records as historical evidence.
- `THIRD_PARTY_NOTICES.md` until an actual dependency is added. If ECharts is introduced later, pin `echarts@6.1.0`, update the lockfile and notice, and add tooltip sanitization/license tests in that same slice.

Product exclusions are also implementation exclusions: no broker connection, orders, paper trading, arbitrary Python or shell execution, package installation, live market/news fetch, realtime subscription, full backtester, model call, multi-agent system, autonomous scope/risk expansion, or financial-advice claims.

## 8. Existing tests and scripts

### 8.1 Test inventory

| Layer | Current inventory | Relevant protection |
| --- | ---: | --- |
| Python `test_*.py` files | 56 | contracts, integration, security, connector, runtime, eval, license, performance, smoke |
| Mac unit/component test files | 18 | API/mappers/domain, SSE/cursor, cache/session, commands/layout, Agent presentation/components |
| Playwright E2E specs | 4 | Agent Workspace, API contract, portfolio assets, workbench layout |

Especially relevant files include:

- `apps/mac/src/features/agent/agent-presentation.test.ts`
- `apps/mac/src/features/agent/agent-components.test.tsx`
- Retired Glint Agent Workspace and API-contract browser specs (historical audit inputs; removed during PokieQuant C4)
- `apps/mac/e2e/workbench-layout.spec.ts`
- `tests/contract/test_run_events.py`
- `tests/contract/test_schema_export.py`
- `tests/connector/test_research_lineage.py`
- `tests/integration/test_exact_version_replay.py`
- `tests/integration/test_history_and_audit_replay.py`
- `tests/security/test_api_command_safety.py`
- `tests/security/test_prompt_injection_containment.py`
- `tests/license/test_dependency_licenses.py`
- `tests/runtime/test_tauri_runtime_script.py`

### 8.2 Script and CI inventory

There are seven `verify_*.sh` scripts:

- `scripts/verify_common.sh`
- `scripts/verify_phase1.sh`
- `scripts/verify_phase2.sh`
- `scripts/verify_phase3_quality.sh`
- `scripts/verify_tauri_runtime.sh`
- `scripts/verify_live_connectors.sh`
- `scripts/verify_live_model.sh`

`verify_phase1.sh` is the broad gate: locked Python/JS environments, dependency audits, Ruff, Pyright, Python contract/runtime/integration/security/eval/license/performance tests, frontend lint/typecheck/unit/build/fixture E2E, Cargo, Compose, RLS, API/worker runtime, and acceptance artifacts. `verify_phase2.sh` layers cloud collection/scheduler/lineage checks over Phase 1. `verify_phase3_quality.sh` isolates model-quality and prompt-injection gates without provider credentials. `verify_tauri_runtime.sh` builds and exercises the native Mac boundary, Keychain, cache, offline restart, WebView, and clean exit. Live connector/model scripts are explicit opt-in gates and must remain separate.

CI currently runs Phase 1, Phase 2, Phase 3 quality, security audit, and macOS native jobs. The root pnpm commands are `lint`, `typecheck`, `test`, `build`, `test:e2e`, and `tauri:check`.

Phase 0 should add `scripts/verify_pokiequant_shell.sh` as an additive orchestrator. It must not weaken or delete existing gates.

## 9. SparkAgent and PokieTicker migration audit

### 9.1 Local SparkAgent finding

A local path was found at `/Users/a1-6/Documents/SparkAgent/2026-07-15-1812`.

Observed facts:

- Git commit: `259ed60847de5771bfb21ceecd066b45016ed9f6` (`Initialize workspace`).
- No Git remote is configured.
- No `LICENSE`, `COPYING`, or `NOTICE` file was found.
- The tracked content is an `evolve-agent` instruction/memory scaffold (`AGENTS.md`, `KNOWLEDGE.md`, `knowledge/`, `notes/`), not a Python sandbox, Jupyter runtime, immutable execution payload, artifact hashing service, or task recovery engine.
- Its working tree contains an unrelated untracked `.openscience/` directory; nothing was modified.

Conclusion: no code from this local SparkAgent is licensed or technically suitable for migration into Phase 0. It is not evidence for the Spark execution runtime described in the requirements. The only safe action is to define a future `QuantExecutionRuntime` boundary in PokieQuant documentation/contracts. Before any later migration, obtain the actual runtime repository, immutable commit, license, file list, and security review.

### 9.2 PokieTicker finding

No PokieTicker working tree was found locally, and no repository/commit/license was supplied for this audit. Therefore the following are requirements-level candidates only, not approved code migrations:

- symbol search;
- OHLC/candlestick and volume data adapters;
- news/event timeline and chart markers;
- imported market-data fixtures and dataset snapshot conventions;
- interval event explanation and similar-history lookup.

Phase 0 may reproduce only the required contract and deterministic fixture behavior. Any later PokieTicker migration must record source repository, exact commit, file paths, license, modifications, and required notices. Do not merge a full backend during Phase 0.

## 10. Recommended Phase 0 sequence

1. Review and commit the fork-baseline/audit documents on `codex/pokiequant-shell` as a user-owned foundation commit. This audit intentionally did not commit.
2. Freeze Quant contracts, state transitions, event vocabulary, fixture authenticity, and API command semantics before UI/backend work diverges.
3. Add a vertical deterministic slice: create project → create plan/run → approve plan → replay fixture events → inspect candidates/artifacts/report → cancel/retry.
4. Build `QuantSessionPresentation` and unit-test state/event/action mapping before composing the new workspace.
5. Add the Market Workspace and Strategy Report using fixture data only; add ECharts and its license work only in that slice.
6. Replace the active navigation/product identity after the vertical slice exists, while keeping old Glint modules out of the main demo path rather than deleting them.
7. Add PokieQuant E2E states/screenshots and an additive verification script, then run all inherited quality gates.

The next implementation slice should not begin with a repository-wide rename, a chart library, or a backend import. It should begin with the Quant contract/state kernel because that is the dependency boundary shared by every other slice.

## 11. Parallel code boundaries and worktree starting points

### 11.1 Required shared starting point

The immutable upstream reference is:

```text
glint-agent-workspace-baseline
= eb9a4be58c4a16b790d0b7568735c53a3627fe51
```

The recommended implementation worktree root is not the tag directly. First, after review, the repository owner should create one foundation commit on `codex/pokiequant-shell` containing the approved fork-baseline/audit documents and no product code. Call that future commit `<POKIEQUANT_FOUNDATION_SHA>`. All implementation worktrees should branch from that SHA so the audit is visible and the Glint baseline tag remains an immutable upstream marker.

Because this audit is currently uncommitted, creating worktrees from `codex/pokiequant-shell` now would not include this document. Worktrees must not be based on the uncommitted working-tree state.

### 11.2 Wave 0: contract kernel (short serial prerequisite)

Suggested branch/worktree: `codex/pokiequant-contracts`, based on `<POKIEQUANT_FOUNDATION_SHA>`.

Owned paths:

- new Quant contract package/module under `packages/contracts/`;
- Quant enums, schemas, RunEvent payloads, OpenAPI registry/snapshot;
- contract-only tests;
- an agreed TypeScript projection boundary (generated or manually mapped, but one source of truth).

This slice should be small and merged/rebased before the main parallel wave. It prevents UI, API, and worker teams from inventing incompatible run states or candidate verdicts.

### 11.3 Wave 1: parallel slices after the contract commit

| Slice | Suggested branch | Exclusive path ownership | Depends on | Avoid touching |
| --- | --- | --- | --- | --- |
| Quant API/domain | `codex/pokiequant-api` | `services/api/app/modules/quant/`, `routes_quant.py`, additive Quant models/migration, API tests | contract commit | frontend, connector/source modules, existing research/evidence services |
| Deterministic fixture worker | `codex/pokiequant-fixture-worker` | `services/worker/app/pipelines/quant_fixture.py`, narrow Quant repository/adapter, worker tests | contract commit and API repository interface | model research, collection/import pipelines, UI |
| Workspace UI shell | `codex/pokiequant-workspace-ui` | `apps/mac/src/features/quant/`, Quant presentation/tests, scoped navigation composition | contract commit; may use an API fixture | `domain.ts`/`api.ts` monolith except agreed extraction, backend services |
| Market/strategy workspace | `codex/pokiequant-market-ui` | Quant chart/report components, fixture chart data, chart tests, exact dependency/notice updates | contract commit plus stable UI container props | global navigation, API lifecycle code, worker |

The API and fixture-worker slices may proceed in parallel only after agreeing on a narrow repository/command protocol. The workspace and market UI slices may proceed in parallel if the workspace owns layout/container props and the market slice owns only the right-side renderer/components.

### 11.4 Conflict hotspots requiring one owner

These files should not be edited independently by multiple worktrees:

- `apps/mac/src/features/workbench/Workbench.tsx`
- `apps/mac/src/domain.ts`
- `apps/mac/src/api.ts`
- `apps/mac/src/styles.css` (or any current global stylesheet)
- `packages/contracts/schemas/__init__.py`
- `packages/contracts/registry.py`
- `packages/contracts/openapi/openapi.snapshot.json`
- `services/api/app/main.py`
- `services/api/app/db/models.py`
- `services/worker/app/main.py`
- `package.json`, `apps/mac/package.json`, `pnpm-lock.yaml`
- `THIRD_PARTY_NOTICES.md`

Assign the contract slice ownership of registries/snapshots, the API slice ownership of API/model registration, the worker slice ownership of worker registration, and a final integration owner for Workbench/navigation/package/notice/global-style changes. This keeps the parallel branches additive and makes rebases predictable.

## 12. Audit verification and current gaps

Performed for this audit:

- verified branch, `HEAD`, parent, commit subject/time, and history depth;
- verified both remotes;
- verified the exact upstream branch SHA;
- verified the local baseline tag target;
- verified the target origin currently advertises no refs;
- scanned for all repository `AGENTS.md` files (none);
- read the complete requirements attachment and required documents/files/directories;
- inventoried test, script, dependency, and CI entry points;
- inspected the only local SparkAgent candidate and searched for a local PokieTicker worktree.

Not performed because this phase changed no product code:

- dependency installation;
- lint, typecheck, unit, build, E2E, Compose, native runtime, or live-network gates;
- screenshots;
- migration or API execution.

After this document is written, the only proportional verification for the audit change is `git diff --check`, document-presence/content checks, and a final Git status/topology check. Full product gates belong to implementation slices.

Known audit gaps:

- no actual Spark execution-runtime repository/commit/license was supplied;
- no PokieTicker repository/commit/license was supplied;
- no Phase 0 Quant persistence decision has been made;
- no dependency/license decision beyond the requirement's proposed `echarts@6.1.0` has been made;
- target repository visibility was accepted by the user but not modified or independently queried through repository administration APIs.

## 13. Decision record

Proceed with a parallel Quant vertical slice that reuses Glint's governed shell and run mechanics. Do not repurpose Glint product-intelligence aggregates. Preserve the upstream baseline tag, keep `glint-upstream` for future selective synchronization, keep `origin` as the Pokie target, and make every future source migration provenance- and license-gated.

The recommended next implementation outcome is the contract/state kernel for one deterministic SPY research run, not the visual chart and not a live execution/runtime integration.
