# Qurio Capability Inventory

This is the planning source of truth for avoiding duplicate work. Update it when a capability is added, replaced or deliberately retired.

Status meanings:

- **Reuse:** the capability is structurally suitable; do not rebuild it.
- **Extend:** the foundation is useful, but a named product capability is missing.
- **Replace narrowly:** keep the surrounding workflow and replace only the invalid or insufficient implementation.
- **Missing:** no suitable product capability exists yet.

Current planning checkpoint: the bounded mainline gate is complete, including D0-lite, W1-lite,
interval-aware sufficiency, Research-Series holdout isolation and the focused Data → Research →
Compare → Analyze → Continue / History path. W2-lite Evidence Focus, W3 train-only robustness
sensitivity, R1/R2-lite verified repair learning, E0 machine-readable evidence export and the
focused P1-C visual proof are complete. P16–P19 remain the completed Agent-native v0.1 research
method, and R0 remains the frozen real-provider execution-repair baseline.

D1 provides one server-driven, fixed-host, read-only Kraken Spot OHLC connector for allowlisted
BTC/ETH USD/USDT pairs at `4h` and `1D`. Raw rows remain untrusted until native validation,
normalization and canonical persistence. Deterministic connector E2E and backend contract/API
tests pass; a live no-key read-only smoke on 2026-07-24 verified both intervals, the 721-row
response boundary and removal of the current uncommitted bar. The seven-tool Agent registry and
authoritative quantitative kernel remain unchanged.

S0 is complete as a **no-go / defer** decision for constrained strategy-execution SDK
implementation because retained evidence does not demonstrate a strategy-template gap. A separate
read-only Python SDK, JSON CLI and four-tool stdio MCP server expose the existing authoritative API
without accepting arbitrary strategies or creating another calculation path. V1 is complete with
one retained real Kraken-to-DeepSeek-to-E0 proof; S0-lite Strategy Scope Contract is complete.
R3–R5, broad Skills/MCP ecosystems, Broker/live trading, portfolio/ML expansion, strategy execution
SDKs and additional audit/security polish remain deferred. Target-user validation is not a delivery gate. The ordered roadmap,
conditional professional expansion and Research Playbook boundaries are specified in
[`POKIEQUANT_AUTONOMOUS_AGENT_PLAN.md`](./POKIEQUANT_AUTONOMOUS_AGENT_PLAN.md).

**W4-lite Workspace Legibility is complete.** The existing Overview, Qurio decision rail, Decision
Ledger, Run Monitor and Decision surface now expose the approved plan, latest material observation
and next legal research action without requiring raw-event inspection. Experiments also projects
the latest coherent persisted Agent decision → registered action → expected evidence → tool
observation, and Run Monitor distinguishes automatic runtime execution from the manual synthetic
fixture. The Workspace remains the product; the one autonomous Research Agent is its bounded,
verifiable execution layer. No further product surface is authorized by this completion record.

G2 intentionally narrows the historical P7–P10 post-holdout refinement behavior recorded below:
a user may approve a holdout-informed hypothesis, but overlapping evidence is then development
evidence and cannot be reused under a fresh sealed-holdout claim.

## Product shell and design system

| Capability | Status | Existing asset | Planning rule |
|---|---|---|---|
| Desktop application shell | Reuse | `QuantWorkspace.tsx`, Tauri/Vite app | Do not create another app shell. |
| Sidebar navigation | Reuse | `QuantSidebar.tsx` | Keep Workspace, New research, History, Data and Settings as the current destinations; revise labels only when page capability changes. Do not introduce Agents, Activity, Deployments or Portfolio destinations without a demonstrated distinct research job. |
| Workspace and utility frames | Reuse | `QuantOverviewWorkbench.tsx`, `QuantUtilityFrame` | Do not introduce another universal page container. |
| Brand assets | Reuse | [`apps/mac/public/brand/README.md`](../apps/mac/public/brand/README.md), `qurio-icon-color.svg`, `qurio-wordmark.svg`, `qurio-wordmark-inverse.svg` | Qurio is the only product/UI brand. Use the flat Q icon and canonical vector wordmark geometry; use the inverse wordmark on the dark shell. Never restore PokieQuant-named or raster wordmarks to the product-facing brand directory. |
| Tokens and component styling | Reuse | `DESIGN.md`, `quant-workspace.css`, `@glint/ui` | Extend existing tokens and control vocabulary. |
| Responsive panel infrastructure | Reuse | `react-resizable-panels` dependency and current shell layout | Do not add a second panel-layout library without a demonstrated gap. |
| Command surface | Reuse | `cmdk` | Keep existing text/native controls and the current command palette; add an icon dependency only for a demonstrated interaction gap. |

## User-facing pages

| Surface | Status | What already works | What remains |
|---|---|---|---|
| Workspace Overview | Reuse | Result headline, inspectable persisted strategy-vs-benchmark equity/drawdown, key comparison, linked candidate snapshot, validation decision, next actions, Copilot and truthful terminal fallbacks | Do not turn Overview into a second Analysis page. |
| New research | Reuse | `QuantGoalComposer` and the utility frame support legacy and public market-v2 dataset selection, synchronized market/source/interval/coverage context, objective templates, one Plan-first entry, cadence-aligned bounded UTC windows, and source-dataset-locked Continue / Refine prefill | Keep one meaningful plan confirmation; after approval the existing bounded workflow advances without extra routine gates. |
| Live run | Reuse | Active Experiments workspace shows the structured current experiment, latest completed metrics, candidate progress, next phase and the latest fail-closed Agent move from typed decision/tool events; Run Monitor retains controls while activity and artifacts remain collapsible secondary detail | Extend the existing typed projection only when the runtime gains genuinely new experiment evidence. |
| Agent-native workspace legibility | Reuse / complete | Overview, Qurio decision rail, Decision Ledger, Run Monitor and Decision retain the approved plan, material observations and legal commands. Run Monitor labels automatic runtime execution, user decision gates and the manual synthetic fixture separately. | Stop at the W4-lite boundary; add no Agent aggregate, route, table, execution surface or second metric path. |
| Research Contract and Decision Ledger | Reuse | Approved plan, A/B roles, train-only Observation, Candidate C rationale, final decision/stop and series outcome are projected through existing surfaces | Do not parse event prose, expose chain-of-thought or add a second decision page. |
| Experiments | Reuse/extend | Sortable candidate comparison, benchmark deltas, shared selection and linked performance analysis | Add filters only when candidate volume demonstrates the need. |
| Analysis | Reuse | Exact-value inspectable equity/drawdown, calendar-period returns, candidate-linked trades and a linked bounded market/trade view share the selected strategy | Keep Plan/Activity secondary; extend only for a newly demonstrated research-inspection job. |
| Decision | Reuse | Conclusion-led Summary, candidate-linked evidence tabs, a server-rendered deterministic Markdown preview/copy/download workflow, and one terminal failed/inconclusive-holdout proposal showing the bounded change, evidence basis and evidence/stop condition before entering the existing editable Refine composer | Extend the existing export and Continue / Refine contracts for decision content changes; do not create client-authored reports or a second decision surface. |
| History | Reuse | Project/question search, project and real-state outcome filters, newest/oldest sorting, dense history table, controlled 2–4 run comparison from lazily loaded historical snapshots, explicit context-compatibility warnings, master-detail summary and opening lock/error handling | Extend only when a new history decision requires it; do not add a second history surface. |
| Data Catalog | Reuse | Search, source/quality filters, selection, empty/error states, and an in-place stored OHLCV preview with coverage, source, quality and research selection | Extend the existing preview only when the dataset contract adds a real interval or statistic; do not add a second data page. |
| Data import | Reuse | Binance/CSV market-v2 creation supports explicit `1h`/`4h`/`1D`; legacy Nasdaq remains compatible; the Kraken connector enters the same Catalog, Preview and Use for research path | Do not add a second Data page or a provider-specific research runtime. |
| Settings | Reuse | Current connection and pinned Run provider/model summary plus packaged-runtime controls for offline deterministic, DeepSeek and one user-configured OpenAI-compatible HTTPS chat-completions provider. Model credentials use separate Keychain entries. | Extend only for another demonstrated provider protocol; do not turn Settings into an Agent builder, process console, preset marketplace or credential inventory. |
| Inspector and notifications | Freeze | Run/candidate/dataset/event/artifact detail, success/failure feedback, focus recovery | Do not continue micro-polishing without a reported usability defect. |

## Quantitative UI assets

| Asset | Status | Notes |
|---|---|---|
| `quant-research-table` | Reuse | Shared dense table vocabulary for candidates, datasets, trades and validation. |
| Candidate selection state | Reuse | `selectedCandidateId` already links Workspace and Report. Extend it to new comparison/analysis views. |
| Candidate metrics and benchmark | Reuse | Annualized return, drawdown, Sharpe and trades already exist in snapshots. |
| Trades | Reuse | Candidate-linked entry, exit, return, holding period and reason already render in Report. |
| Walk-forward and holdout summaries | Reuse | Existing tables and domain projections remain secondary robustness analysis. |
| Market OHLCV chart | Reuse | Shared `QuantMarketChart` renders dataset-specific stored bars with candlestick/line and available volume. True rolling SMA20/SMA50 are enabled only for contiguous Data Preview bars; sparse Run projections disable indicators and add retained trade markers without recalculating performance. |
| Overview market path chart | Reuse only as market context | It visualizes market price/drawdown, not strategy equity. Never relabel it as strategy performance. |
| Strategy equity/drawdown chart | Reuse | Shared by Overview, Analysis and Strategy Report; uses persisted candidate/benchmark series, date-aware alignment, pointer/touch selection, bounded keyboard inspection, exact readouts and truthful axis ticks; never uses market close prices. |
| Candidate comparison workbench | Reuse/extend | Sortable metrics, benchmark differences, outcome and shared candidate selection are implemented. |
| Evidence focus state | Reuse | One typed, read-only presentation intent links candidate, drawdown, trade, validation/report and source-version comparison in existing surfaces; it returns a receipt/reference without mutating a Run or becoming an eighth tool. |
| Robustness surface | Reuse | Existing walk-forward evidence is combined with retained train-only `1×`/`2×`/`4×` cost scenarios and deterministic one-at-a-time parameter neighbors. This does not establish global robustness or sealed-holdout success; do not add a second optimizer or metric path. |

## Backend and runtime

| Capability | Status | Existing asset |
|---|---|---|
| Project and run lifecycle | Reuse | Create/list/get projects and runs; approve plan, request changes, cancel and retry. |
| Continue / Refine research | Replace narrowly in G2 | Legacy daily and public market-v2 research create an independent linked Run with `parent_run_id`, `seed_candidate_id` and `refinement_reason`; Retry remains another attempt of the same Run. The precommitted automatic child is train-only. A user-approved post-report Refine may retain a holdout-informed reason, but reused or overlapping evidence must not be presented as a fresh sealed validation. |
| Run research range | Replace narrowly in G1 | Legacy dates and public market-v2 cadence-aligned bounded UTC ranges are validated, pinned and applied to Agent/backtest bars. For new market-v2 research only, require `max(252, ceil(PPY/4))` bars and matching inclusive cadence coverage while keeping short stored data previewable. Preserve historical restore/Retry pins and the existing 252-bar split floor. |
| Historical run snapshots | Reuse | `/runs/{run_id}/workspace-snapshot` and protected UI navigation. An explicit History open uses this endpoint even when the selected ID is also the latest Run, renders the read-only banner and withholds the editable Refine proposal/action. |
| Dataset lifecycle | Reuse | CSV import, Binance Spot fetch, Nasdaq Equity fetch, list and run selection. |
| External connector contract | Reuse | A server-driven directory exposes one fixed-host Kraken Spot connector. Raw rows remain untrusted until native validation, normalization and canonical persistence; no arbitrary URL, credential, account, order, Broker or provider-authored quantitative metric is accepted. |
| Generic market-bar contract | Reuse | C1–C5 provide validated UTC `1h`/`4h`/`1D` market bars, v2 ingestion/persistence, cadence-aware evaluation, a public market-run contract, existing-page UI integration and real Binance `4h`/`1D` proof; legacy daily remains compatible. |
| Dataset preview bars | Reuse | Workspace-scoped legacy and v2 preview endpoints return bounded latest-contiguous stored OHLCV; production and fixture transports share discriminated typed contracts. |
| Agent runtime | Reuse | OpenAI-compatible DeepSeek provider, Mock provider, runner, context builder and tool registry. It plans and executes bounded research tools; it is not an order, position, deployment or trading runtime. |
| Desktop local runtime entry | Reuse | The Apple-silicon macOS 11+ app embeds a PyInstaller onedir sidecar built from locked managed Python 3.12. Tauri starts one persistent FastAPI plus Quant Agent worker, stores runtime data in Application Support, bootstraps a local workspace, retains provider-specific credentials in separate Keychain entries and exposes start/stop/restart without a terminal. Offline deterministic and DeepSeek keep their closed configuration; OpenAI-compatible accepts one explicit HTTPS Base URL and model. Provider/model changes require restart and are locked while the current Run is active; source builds keep a fixed development fallback. |
| External Agent access | Reuse / complete | `sdk/python` builds the lightweight `qurio-sdk` wheel with a typed, workspace-scoped Python client, JSON CLI and stable-v1 stdio MCP server over retained datasets, Runs, workspace projections and evidence. MCP registers exactly four read tools and has no research mutation, arbitrary Python, Broker or order capability. |
| Independent Paper Trading | Reuse / complete | `packages/contracts/paper`, `routes_paper.py`, `modules/paper`, `PaperTradingState` and `QuantPaperTradingPage` form a workspace-scoped local simulator. Only the candidate retained by a completed final Research Report can create a draft; submit, cancel, fill, position and reconcile state are versioned. No live host, credential, Broker account or live-order route exists. |
| Verified repair learning | Reuse | R1 retains digest-verified `learning_trace_v1` outcomes; R2 reuses only validator-proven, schema/tool-compatible repair memory. This is tool-contract repair learning, not alpha, hidden-reasoning, metric or holdout memory. |
| Structured Research Memory | Reuse | P17 pins at most five same-evidence terminal source Runs and fifteen canonical candidate identities on each new Run, verifies the canonical digest on restore, clones the exact pin for Retry, makes create/revise/Mock use the one pinned de-duplication set, and projects only source/candidate counts in existing Overview details. Real DeepSeek acceptance pinned one source Run and three tested keys, created two canonical-distinct candidates with zero overlap and retained no prohibited prior evidence. |
| Evidence-driven replan | Reuse | P18 forces the first A/B training comparison before another provider decision, binds candidate C to one typed refine-or-switch decision and the exact feedback artifact, and supports honest no-novelty or insufficient-budget A/B stops. Canonical identity, legacy restore markers, Research Series conflicts and zero-mutation failures are enforced server-side; the seven-tool UI contract is unchanged. |
| Structured research decision | Reuse | P19 binds the retained candidate to the latest train-only comparison. The Agent may approve the objective leader or cite one closed server-validated robustness override; ties fall back to rank one. The exact basis survives report, export, history reload, structured stop and the bounded Research Series child seed without adding a tool or page. |
| Autonomous research actions | Reuse | Candidate creation, deterministic backtest, repair, comparison and finish-report actions. |
| Executable Agent plan | Reuse | The generated candidate-family allowlist and completion criteria are persisted with the Run and plan artifact, included in every Agent decision context, retained by Retry/series follow-up and enforced by candidate creation. |
| Evaluation engine | Reuse | Benchmark, repeated expanding walk-forward, chronological holdout and report projections. |
| Events, artifacts and experiments | Reuse | API list/get routes, SSE event stream and workspace projections. Front-stage tool outcomes remain visible when they also reference internal learning artifacts, while internal artifact IDs are removed field-by-field. |
| Persistence | Reuse | Workspace-scoped Quant store and run/dataset/project records. |
| Candidate performance series | Reuse | Typed API/domain/parser/fixture contracts project persisted daily or timestamped intraday backtest equity and drawdown without client-side metric recomputation. |
| Strategy Report and evidence export | Reuse | The server-owned export path supports Markdown plus `strategy_evidence_bundle_v1` JSON for the final report-selected candidate, including retained identities, plan, candidates, comparison, curves/trades, validation, lineage, limitations and a content digest. The client does not recompute metrics. |

## Test and development infrastructure

| Capability | Status | Existing asset |
|---|---|---|
| Deterministic workspace states | Reuse | Generated Quant fixtures cover ready, transient, review, completed, failed, cancelled and other outcomes; the fixture lifecycle restores the exact configured Quant startup state before every browser test. |
| Delayed/offline/failure testing | Reuse | Fixture API supports slow responses, mutation delay/counting and provider failures. |
| Frontend tests | Reuse | Vitest component/presentation/API/parser coverage. |
| Browser workflow tests | Reuse | Playwright Quant workspace and layout specs plus deterministic lifecycle coverage. The retired Glint Investigation/Agent Workspace specs and their private state variants are not a supported product contract. |
| Golden mainline E2E | Reuse | P1-C deterministically verifies BTCUSDT `4h` Data → plan approval → live A/B → Observation/C → final JSON export → Refine/History reopen at 1440 and 1024. It is not a live-provider/model or alpha claim. |
| Real-provider verification | Reuse | Binance + DeepSeek and Nasdaq + DeepSeek verification scripts and live-session launcher; D1 has a live no-key Kraken `4h`/`1D` connector smoke; V1 retains a Kraken BTCUSD `4h` → DeepSeek V4 → A/B/C → E0 → History proof with Mock fallback disabled. `--readonly-reopen` defaults to that retained V1 session and starts only the API and Mac UI against genuine read-only SQLite. | Keep live proof opt-in, isolated and sanitized; do not turn it into a profitability or production-reliability claim. |
| Guided interview demo | Reuse/extend | `launch_quant_live_session.py --guided-demo` verifies the retained C5 Binance BTCUSDT `4h` + DeepSeek source digest, prepares a current-schema presentation copy, serves it read-only and injects one sidebar entry that opens the existing Experiments view. The Agent decision chain leads with Observation → Why Qurio changed → Next action. | Keep this a read-only entry into the normal product surfaces; do not add demo-only metrics, a second fixture path or a separate Agent page. |

### V1 — Live connector → evidence proof

Status: **Passed on 2026-07-24 through the accepted `A/B → C → decision` branch.**

- The fixed-host Kraken connector retained 548 closed BTCUSD `4h` bars and dropped the current
  uncommitted provider bar before canonical persistence.
- DeepSeek `deepseek-v4-flash` ran with Mock fallback disabled. Three experiments ran:
  A `sma_crossover_20_100`, B `breakout_20`, and C `sma_crossover_50_200`.
- The first Candidate C create call was rejected once with
  `ITERATION_REPLAN_TEMPLATE_RELATION_INVALID`; the next model turn received the exact rejected
  arguments, changed only `replan_decision.action` to `switch_approved_family`, and succeeded.
  Exactly one failed tool call was recorded, with no repetition and a durable
  `quant-learning-trace-v1` whose `correction_delta` contains only that action.
- Candidate C was backtested and included in a second train-only comparison. The final training
  ranking was C, B, A. Because C produced zero training trades, the structured
  `research_decision` selected B `breakout_20` via `robustness_override` / `minimum_trade_evidence`
  while referencing C. This is a minimum-trade evidence selection, not an alpha/profitability claim.
- B failed the fresh sealed holdout, so the retained next step is `revise_research`.
- Dataset/record, runtime/split, Run, selected-candidate and E0 JSON identities remained equal
  through current and historical snapshot/export reads.
- The retained run evidence is `.run/v1-kraken-deepseek-20260724-183209/v1-kraken-evidence.json`
  and the E0 bundle is
  `.run/v1-kraken-deepseek-20260724-183209/qurio-btcusd-evidence-6ad1c324.json`.
- An earlier rerun exposed a P1: strict action-only repair was impossible because the rejected
  arguments were not in model context. It was fixed by exposing only the correctly bound rejected
  call arguments for pending typed repair while the runner remains fail-closed.
- The final backend verifier reopens current and historical reads and checks dataset, Run,
  selected-candidate and E0 identities without fixture substitution. The accepted UI proof consists
  of six 1440×960 captures from a read-only SQLite reopen (API + Mac UI only, no worker/model call):
  Data, Decision Ledger with the optional Candidate C correction projection, Analysis, sealed
  holdout failure, E0 export and History reopen. The retained DB SHA-256 stayed exactly
  `9bc9986ba81496a14c862a7b23837bd8266b4766d73c2177578182c0569d90c0` across the reopen.
- The tightened verifier accepts only strict `A/B → C` or a bound structured stop; it rejects a
  plain two-candidate completion.

### S0-lite — Strategy Scope Contract

Status: **Complete; independently reviewed with P0/P1 = 0.**

- The existing executable plan carries one closed `supported`, `bounded_proxy` or `unsupported`
  scope decision. It adds no page, strategy family, tool, endpoint, table, DSL or evaluator.
- Twelve frozen probes cover exact SMA/RSI/breakout questions, three explicit bounded proxies,
  and six unsupported strategy shapes.
- Supported Auto runs retain the existing path. A bounded proxy always waits for explicit plan
  approval. Unsupported requests cannot be approved and retain zero experiments, quantitative
  comparisons or holdout evidence.
- Run, plan artifact, Agent context, Retry/series descendants, historical snapshot and E0 export
  retain the same scope. A pre-scope legacy Run is materialized as an explicit supported legacy
  plan only when both durable copies lack the field.
- A plan-external candidate call becomes one typed repair requiring both the template and matching
  parameters to change. A corrected call retains one resolved learning trace across a fresh Store
  restore; a partial correction stops before another tool execution.

## Next product direction — Research Series

Status: **P1A–P1C and P2–P10 are implemented. Research Series v0.1 and the structured Research home are frozen.** Runs and Report distinguish versions from attempts, public market research can use a bounded stored-data window, a validated comparison can start the next Refine, and the Report can execute one explicitly approved suggested Refine before returning to review. The UI no longer calls that user-triggered action a Campaign or Autopilot because no durable controller exists yet.

Existing assets to reuse:

- Project and root Run identity as the start of a research direction.
- Persisted `parent_run_id`, `seed_candidate_id` and `refinement_reason` for Continue / Refine lineage.
- Retry identity and attempt numbers for repeated execution of the same Run.
- Runs search/comparison/history hydration, historical workspace snapshots and selected-candidate identity.
- Strategy Report, Markdown export, candidate comparison and validation/holdout evidence.

Planned gaps, in order:

| Package | Planned capability | Reuse boundary |
|---|---|---|
| P1A — completed | Read-only Research Series projection identifies a root Run, linked Continue / Refine version and Retry attempt in the existing Runs and Report surfaces | Derived from existing Project/Run lineage and snapshots; no new table, endpoint, Mission aggregate, persisted series or execution behavior. |
| P1B — completed | Public market-v2 Continue / Refine | The existing composer and server-validated lineage contract retain the source dataset, interval, runtime/split pins and exact-full-coverage rule. |
| P1C — completed | Runs and Report expose fail-closed Open source version / Open prior attempt actions only for exact directory- and snapshot-validated relationships | Extends the current directory, historical hydration and Report actions; no second history or report page. |
| P2 — completed | Research home and structured Research Copilot refinement | Reuses Workspace/New Research and the existing right rail; typed Current / Observation / Next precede details and the optional Ask affordance. |
| P3 — completed | Bounded public market-v2 research windows | Reuses the existing dataset, composer, market-run contract, runtime descriptor and lineage. New research and Continue may select an aligned stored-data window; Retry remains an exact attempt of the same pinned Run. |
| P4 — completed | Direct source-version comparison | Reuses directory-validated lineage, retained workspace snapshots and the existing Runs comparison table. No new comparison calculation, endpoint, page or series model. |
| P5 — completed | Real bounded-window Continue verification | Reuses the retained C5 Binance dataset and source Run for one paid DeepSeek continuation; no duplicate fetch, root Run or Retry execution. |
| P6 — completed | Explain version change | Extends the existing Runs source comparison with retained refinement intent, strategy path, exact stored metric deltas and a fail-closed comparability verdict; no new model, endpoint or page. |
| P7 — completed | Comparison-to-Refine handoff | Reuses the existing comparison, continuation eligibility and Goal Composer to carry one eligible result into an editable next-run draft. |
| P8 — completed | Internal primary-loop task check | Reuses the existing component and fixture browser paths to check start, observe, compare, report, Refine and history actions; this is an internal regression pass, not an external usability study. |
| P9 — completed | Agent-guided Research Campaign v0.1 | Projects one structured next-run proposal from the retained Agent report, selected candidate and authoritative validation result; user review remains mandatory. |
| P10 — completed | One-round Campaign Autopilot v0.2 | Reuses the P9 proposal and existing Auto Research create path to start exactly one user-approved Refine with retained lineage, dataset/window and evidence context; no scheduler or campaign aggregate. |

Hard boundaries: no Research Series page, duplicate lineage table, ResearchMission/Question/Iteration model or Library destination is approved by this plan. Research Memory means the existing structured lineage, versions, attempts and retained evidence—not a transcript archive.

## Completed core implementation package

### Research Series P1A — read-only relationship projection

Primary user action: recognize a root research version, a Continue / Refine version and a Retry attempt in the existing Runs and Report views without opening rows one by one or treating a retry as a new version.

Implemented:

- The legacy and public market Run directories retain their separate contracts while exposing the existing dataset, parent and retry identities to one fail-closed frontend relationship helper. It labels only roots, resolved continued versions and exact next attempts; missing parents, incompatible identities, cycles, attempt gaps or conflicting lineage display `Relationship unavailable` rather than receiving a guessed version number.
- The dense Runs table reuses its attempt column as `Version / attempt`; no wide series column, card group, route or numeric version sequence was added. Historical open, search, filters, comparison and market/legacy hydration continue through their existing paths.
- Strategy Report reuses the persisted `continuedFrom` snapshot context and conditionally shows the source version, candidate, refinement reason, source question and retry attempt as compact text. Current and historical snapshots use the same identity; P1B extends the same projection to public market-v2 Continue without changing this surface.
- Store restore validates persisted Continue lineage before atomically replacing workspace caches: the three refinement fields are all-or-none; parent and child must share workspace, project, dataset and contract family; the parent must be terminal; the seed must be a completed non-fixture candidate with a valid structured strategy; and self or multi-node cycles fail closed without partially loading corrupted state.
- Component/parser/API tests cover root → Continue → retry, market root → retry, unresolved public relationships and additive legacy response compatibility. At the P1A boundary, fixture browser coverage verified historical Report identity, unchanged legacy Continue entry points, the then-closed market mutation boundary and no document overflow at 1440 or 1024.

Not implemented by P1A itself: persisted series aggregates, numeric version assignment, a Research Series page or richer cross-version navigation. Public market-v2 Continue / Refine is implemented by P1B below.

### Research Series P1B — public market-v2 Continue / Refine

Primary user action: continue from a retained candidate in a terminal public market-v2 Run, revise the objective through the existing Research Setup composer and create a new independently executed version without confusing it with Retry or ordinary New research.

Implemented:

- The existing Report, Experiments and Analysis actions use the same selected candidate and shared eligibility helper. Only completed, failed or cancelled public market Runs with a server-projected seedable non-fixture candidate can enter the composer; private market, active and unseedable Runs fail closed.
- The public market create contract accepts lineage only as a complete `parent_run_id` / `seed_candidate_id` / `refinement_reason` group. Client parsing and request construction reject partial or blank lineage before transport, while the server revalidates workspace/project ownership, terminal source state, candidate ownership and structured strategy identity before provider planning.
- A child retains the exact source market dataset, digest, symbol, interval, periods per year, UTC coverage, runtime descriptor, sealed split and authenticity. P1B does not claim arbitrary intraday range cropping.
- Agent refinement context is rebuilt from persisted source identity and seed template/parameters only; source metrics, benchmark deltas, validation/generalization, holdout and report recommendations do not enter the child context. The parent remains unchanged and the child executes independent candidates and evidence.
- Retry of a refined market Run remains attempt 2 of that version, keeps the same lineage and runtime pins, and starts without prior-attempt experiments, comparison feedback or result artifacts. Ordinary New research sends no lineage.
- The existing composer preserves objective, reason, locked dataset and source context after a create failure. Fixture browser coverage verifies all three entry points, historical rather than latest source identity, exact UTC submission, retryable failure, child history/Report identity and 1024-width long-text containment without adding a route, page, table or second composer.

Not implemented: public market range cropping, continuation from private internal market Runs, persisted series aggregates, guessed numeric version numbers or a separate Research Series surface. P1C completes the bounded Research Series v0.1 surface below.

### Research Series P1C — source version and prior attempt navigation

Primary user action: safely open the exact source version or previous Retry attempt from the existing Runs and Report surfaces.

Implemented:

- Legacy daily and public market-v2 history retain discriminated identities. Market relationships additionally require symbol, interval, periods per year, UTC coverage, dataset digest, runtime descriptor digest and sealed split digest to match.
- Continue parents and Retry sources must be terminal. Retry attempts also retain the same question, mode, provider, model, lineage and exact next-attempt number; missing, partial, duplicate, cyclic, forked, gapped or drifted relationships fail closed as `Relationship unavailable` with no navigation target.
- Runs and Report compare the directory record with the current or historical snapshot before trusting a relationship. State, normalized mode, question, project, dataset, attempt, lineage, provider/model and market runtime pins must agree.
- `Open source version` and `Open prior attempt` request the exact retained Run ID. The API adapter and Workspace both reject a historical response whose snapshot Run ID differs from the requested ID, leaving the current snapshot unchanged.
- Relationship directories refresh when the authoritative Run state changes, so a legitimate running-to-terminal transition does not leave stale identity data while strict validation remains enabled.
- Vitest, TypeScript, ESLint, production build, OpenAPI snapshot and diff checks pass. Fixture Playwright covers legacy and public-market root → Continue → Retry navigation, Continue regressions, run history comparison/reopen and 1024/1440 layout with no failures.

Not implemented: a separate Research Series page, persisted series aggregate, numeric version numbering, tree/timeline visualization or cross-series library. P2 completes the existing Research home below.

### P2 — structured Research home and Copilot

Primary user action: understand the current research state, the latest material observation and the next valid action within ten seconds of opening Overview.

Implemented:

- The existing Overview remains the Research home. Its result-led chart, comparison, Decision Gate and tabs were retained; no route, page, backend endpoint or domain model was added.
- A pure typed presentation projects `Current`, `Observation` and `Next` from retained Run, plan, candidate, live-research, report and legal-command fields. It does not parse event prose or expose incomplete holdout conclusions.
- Next actions reuse existing handlers and server-authorized commands: plan approval/change, review completion, retry/cancel, analysis/report, Continue / Refine, New research and Return to latest. The misleading Overview `Open plan` shortcut was removed.
- Historical legacy and public market Runs are read-only across Copilot, Report, Experiments and Analysis. Ask, Continue and lifecycle mutations are suppressed in the UI and rejected again in Workspace handlers.
- Failed and cancelled Runs always present a no-promotion outcome, even if a stale or malformed snapshot retains an older report/generalization payload.
- Details are collapsed by default and retain Run metadata, plan progress and UTC activity as supporting context. Ask appears last and only when the authoritative snapshot permits it.
- At desktop width the projection occupies the existing right rail. At 1024 it is rendered once as a compact block above the main evidence; the rail is not duplicated in the DOM and the page does not gain a fourth column.
- Unit coverage exercises the lifecycle matrix, stale-report protection, real actions, busy state and historical read-only behavior. Browser coverage verifies Ask payload/locking, legacy and market history, 1h/4h UTC and periods-per-year semantics, and 1024/1440 containment.

Not implemented: a conversational transcript product, autonomous page manipulation, a new home route, freeform canvas, Library destination or fourth Context column. The next package must be selected from a fresh primary-loop capability audit rather than assumed from this UI refinement.

### Phase 1B C1 — generic market-data contract

Primary user action: establish a trustworthy common bar contract before users can start or compare research on genuinely supported non-daily intervals.

Implemented:

- A separate `QuantMarketBarDataset` v2 contract now accepts UTC-aligned `1h`, `4h` and `1D` OHLCV bars with immutable digest coverage for interval, timestamps, calendar, session, timezone and per-bar `periods_per_year`.
- Calendar mapping is explicit: `24x7` requires UTC continuous session and 8,760/2,190/365 bars per year for `1h`/`4h`/`1D`. XNYS/XNAS require `America/New_York`, XSHG/XSHE require `Asia/Shanghai`; all four are regular-session `1D` only at 252 bars/year until a real intraday cadence exists. Generic weekday is likewise `1D` only at 252 but permits an explicit valid IANA timezone; `unknown` requires no annualization value and is never inferred.
- The deterministic v1 daily-to-v2 adapter preserves the original v1 reader and digest exactly, projecting unknown calendar/session/annualization rather than silently assigning 252.
- This is a contract-only package: no importer, store persistence, runtime, backtest, benchmark, walk-forward, holdout, regime-volatility calculation, fixture value, ranking, report, REST endpoint or UI currently consumes v2. Existing daily calculations retain their established 252 behavior until C3.

Next missing core capability: **C2 dataset ingestion and storage**—accept and persist real v2 interval data without changing the current research runtime or exposing an interval control prematurely.

### Phase 1B C2A — bounded v2 acquisition and parsing

Primary user action: establish a safe import boundary for real hourly and four-hour market bars before any dataset can be stored, previewed or used for research.

Implemented:

- An isolated Binance v2 client normalizes public `1h`, `4h` and `1d` klines to the C1 market-bar contract as `provider_fetch` `24x7` / continuous / UTC data. It pages backward with a maximum of five pages, 1,000 bars per page and 5,000 bars total; all requests have byte and timeout bounds.
- One captured canonical UTC retrieval time governs every page. Only bars whose close is strictly before that capture remain. Rows require exact Binance shape, integer aligned open/close times and `close = open + interval - 1`; economically identical overlaps deduplicate despite harmless Decimal string formatting, conflicting values fail closed, and non-advancing cursors stop safely.
- V2 price and base-asset volume are strict Decimal values (up to 30 total / 18 fractional digits) and remain canonicalized in the market-bar and dataset digests. Legacy v1 daily price/volume types, parser, digest and Binance daily importer are unchanged.
- The in-memory result carries minimal batch evidence: raw provider-row count, retained unique closed-bar count, an explicit `requested_limit` / `history_exhausted` / `page_cap` termination reason, target-satisfaction flag, source reference, retrieval time, ordered raw-page SHA-256 values and canonical batch digest. A five-page shortfall is explicitly not target-satisfied. Gaps are never filled and produce blocked quality.
- A separate v2 CSV parser emits `csv_upload` provenance, requires explicit interval and RFC3339 `Z` timestamps, accepts only 24x7/UTC source assumptions, and rejects date-only, naive, offset, unaligned, duplicate and unordered data.

At the end of C2A, not implemented: persistence, catalog listing, preview, versioned REST, a Run gate, UI controls, backtest annualization migration or any change to existing daily calculations.

### Phase 1B C2B — v2 persistence and preview transport

Primary user action: reliably retain and inspect multi-interval market data before it becomes eligible for research.

Implemented:

- An isolated workspace-scoped `market_datasets_v2` registry persists validated v2 market datasets without changing legacy daily records, list responses, digests or run paths. Restore fully parses and cross-validates every record family for one workspace before atomically replacing that workspace's cache; malformed, tampered, duplicate, mismatched-workspace or unknown-schema state leaves cache, storage version and loaded markers unchanged, and a failed write rolls back its in-memory record.
- Versioned authenticated v2 CSV and Binance-fetch routes provide separate list, get and bounded preview responses. They retain compact evidence and cadence-quality summaries, including a bounded CSV file name where supplied but never raw provider payloads, and use a record-level canonical digest covering the dataset digest, normalizer/parser version, evidence and quality.
- Preview returns only the latest contiguous tail when cadence gaps exist. At the C2B boundary, v2 data could be stored and previewed while research entry points still rejected it pending C3; legacy `/datasets` remained daily-only. Later C3–C5 packages supersede that temporary gate through the separate public market-run contract.

Not implemented: UI controls, research use, interval-aware backtests/annualization, benchmark/walk-forward/holdout changes or any modification of existing daily calculations.

At the end of C2B, the next missing core capability was **C3 cadence-aware runtime work**—establish interval-aware calculations before exposing stored v2 datasets to research.

### Phase 1B C3A — cadence-aware domain backtest kernel

Primary user action: make strategy and benchmark calculations scientifically consistent across supported hourly, four-hour and daily bar cadences before multi-interval research is enabled.

Implemented:

- The pure domain kernel now has an independent frozen UTC `MarketBar` type and explicit `BacktestCadence` for `1h`, `4h` and `1D`. It accepts only the modeled interval/annualization pairs (`1h`/8,760, `4h`/2,190, `1D`/252 or `1D`/365), validates each timestamp against its UTC interval boundary and provides the 24x7 8,760/2,190/365 cadence factory without importing the Pydantic market-data contract.
- Strategy and buy-and-hold paths share cadence-aware CAGR and Sharpe calculations, preserve next-bar-open execution and expose authoritative timestamps plus fill-index holding duration for timestamped trades.
- Legacy `DailyBar` calls remain default `1D` / 252 and accept only an equivalent explicit cadence. Existing daily execution, rounding, fees, slippage, strategy windows and fixture results remain unchanged.

Not implemented: v2 store/runtime adaptation, the research gate, interval-aware walk-forward/holdout/regime calculations, Agent/report/snapshot projection or UI selection.

Next missing core capability: **C3B runtime integration**—adapt validated stored v2 bars into the cadence-aware kernel and migrate the remaining evaluation stages before enabling v2 research.

### Phase 1B C3B1 — internal pinned runtime evaluation

Primary user action: make stored multi-interval data internally verifiable through the complete research calculation path before any public Run or UI control can select it.

Implemented:

- A private immutable runtime descriptor resolves either the existing v1 `DailyBar` / `1D` / 252 path or an isolated stored v2 dataset. The v2 descriptor pins dataset and record digests, interval, periods per year, complete UTC coverage, authenticity, accepted quality and finite normalized `MarketBar` values; blocked, gapped, unknown-annualization, partial-range and short inputs fail closed.
- Internal-only v2 run provisioning persists the descriptor identity plus a deterministic chronological 80/20 split seal covering dataset digest, interval, annualization, full UTC range, train/holdout boundaries and rule versions. Restore and internal retry revalidate and retain those pins without inheriting prior-attempt candidates or artifacts.
- Candidate training, buy-and-hold comparison, walk-forward folds and market-regime volatility now consume the same descriptor cadence. Training comparison and iteration feedback remain train-only; the final selected candidate receives one sealed holdout evaluation using the same fees, slippage and periods-per-year assumptions.
- Legacy daily runs retain their existing date range, public response and persisted shape, use `DailyBar` with the established 252 annualization, and preserve their existing calculation and Agent-loop results.

Not implemented: public v2 Run creation, versioned Run DTOs, snapshot/report-export/history projection, Agent prompt changes or any React interval/range control. Existing public create/command/retry paths continue to reject v2 datasets as stored and previewable but not research-enabled.

Next missing core capability: **C3B2 controlled enablement and projection**—expose the validated runtime identity through a versioned Run boundary and update snapshot/report/UI consumers before removing the public v2 research gate.

### Phase 1B C3B2a — private multi-interval result projection

Primary user action: accurately retain and read an internally verified multi-interval research result across Agent context, workspace evidence, report export and history before public Run creation is enabled.

Implemented:

- Durable snapshot construction now resolves one C3B1 runtime projection before reading dataset evidence. Private `1h`/`4h` runs project their real interval, periods per year, RFC3339 UTC coverage and bars, accepted cadence quality, timestamp-preserving strategy/benchmark performance, market-bar kernel identity and selected-candidate trade markers without calling daily-only dataset accessors or describing the input as daily data. Legacy v1 snapshot fields, fixture authenticity, dates and daily-kernel labels remain unchanged.
- The Agent contract treats any multi-interval, annualization, UTC-range, runtime/split or train-partition signal as a strict v2 dataset summary. It requires real UTC timestamps, matching top-level/split dataset identity, interval and periods per year, an in-coverage ordered train-only partition, accepted quality and both runtime identities; partial or sealed-evidence-shaped payloads fail closed while the existing v1 daily dataset-summary bytes remain unchanged through the worker prompt.
- Persisted reports and deterministic Markdown export obtain symbol, interval, range and annualization from the revalidated runtime projection. Market-run exports retain timestamped entries and bar-based holding periods; the REST response preserves the exact Markdown bytes used for its content digest.
- Current and historical snapshots, fresh-store reload and internal retry retain the same runtime/split identity. Holdout projection appears only after the single completed report; a clean internal retry has no prior report, candidates, performance or holdout evidence.

Not implemented: public v2 Run creation, public commands/retry, versioned Run request/response fields, React parsing, interval/range selection or UI controls. Private market snapshots expose no legal public command; shared store eligibility rejects explicit approve/plan-change/cancel/retry, workspace commands and create/continue boundaries before row-version, event, artifact or state mutation, so the public research gate remains closed.

Next missing core capability: **C3B2b controlled public contract**—add an explicit versioned Run boundary and compatible frontend projection before any Data Catalog action can start multi-interval research.

### Phase 1B C3B2b — controlled public market-run contract

Primary user action: start, control, retry and revisit cadence-aware research on a stored, validated v2 dataset through an unambiguous backend contract that C4 can wire into the existing workbench.

Implemented:

- A dedicated authenticated `/v1/quant/market-runs` resource now provides list, create, read, approve-plan, request-plan-changes, cancel and retry operations without changing or reinterpreting the legacy date-based `/runs` request/response. Create requires explicit RFC3339 UTC start/end values and the exact full stored coverage; the server derives and pins the dataset digest, symbol, interval, periods per year, runtime descriptor and sealed split rather than accepting client cadence overrides.
- Public market runs persist the explicit `quant-market-run-v2` contract identity. Restore rejects unknown versions, invalid pins, missing or conflicting retry children, one-way links, self/cyclic links and any workspace/project/dataset/contract/runtime mismatch before replacing the loaded workspace graph. Clean retry retains the same descriptor/split and creates a new attempt without prior candidates or result artifacts. Private C3B2a runtime records remain readable through their existing snapshot/report paths but are absent from the public market-run directory and return 409 for every market-run mutation.
- Shared store eligibility keeps the boundaries closed in both directions: public v2 runs cannot use legacy run or workspace-command mutations, legacy daily/private runs cannot use market-run endpoints, and blocked, gapped, short, cross-workspace, partial-range, naive/non-UTC or client-overridden inputs fail before provider planning or any Run/project/event/artifact mutation. The v2 dataset directory reports research eligibility only when the same runtime resolver accepts the complete dataset.
- Public market create, approve-plan, request-plan-changes, cancel and retry now persist as all-or-nothing workspace mutations. On a write exception the store compares a fresh durable payload with both the baseline and attempted canonical payload: an uncommitted write restores the exposed Run/project objects in place, a committed write reconciles memory and storage version as success, and any third state reloads durable truth and fails closed. The single workspace worker lease is explicitly bound to its Run, worker and attempt; cancelling or retrying cleanup for Run B can clear only B's matching lease and leaves an active or replacement Run A lease intact, while the owning worker safely refreshes unrelated durable workspace changes before its next write. Plan-change concurrency requires both the current Run row version and exact plan revision before any mutation; the legacy daily path keeps the same strengthened check.
- AUTO market runs are claimed by the existing worker and retain the seven-tool bounded 2+1 loop, train-only feedback, final comparison and one sealed holdout. For the default three-experiment contract, finish now requires exactly two completed base candidates, one completed feedback-linked and canonical-distinct third candidate, and a newer final training comparison whose rows and ranking cover all three; one candidate, two candidates or a failed third candidate cannot produce a completed report or holdout and instead converge through the bounded failure path. Restore and finish recompute candidate canonical keys and validate that the feedback artifact, source candidates, comparison and improvement reference all belong to the same Run. The default Mock integration remains the exact 11-action sequence; automatic repair remains available only outside that strict default sequence. Current/historical snapshots, performance, report, Markdown export and fresh-store reload remain bound to the same selected candidate and pinned cadence identity; running/create responses do not expose holdout bounds or results.
- Stale SSE cursors reset public market runs to their readable `/v1/quant/market-runs/{id}` resource, private market runs to the read-only workspace snapshot, and legacy daily runs to the unchanged legacy Run resource.

At the C3B2b boundary the backend deliberately required exact full coverage; C4 initially consumed that constraint. P3 below supersedes that historical limit without reinterpreting the legacy date request.

### Phase 1B C4 — existing-page multi-interval research integration

Primary user action: select a stored, research-eligible `1h`/`4h`/`1D` market dataset in Data, start PLAN or AUTO research in the existing composer, inspect timestamp-preserving results and reopen the same Run from history.

Implemented:

- The Data Catalog merges the unchanged legacy directory with the dedicated v2 market directory using a discriminated frontend domain. Rows and the existing Preview master-detail surface show the server-owned symbol, interval, UTC coverage, bar count, authenticity, cadence quality and research eligibility; v2 Preview reads its bounded Decimal OHLCV/timestamp contract while legacy Preview keeps its original endpoint and number shape. Blocked datasets remain previewable but cannot be used for research.
- `Use for research` opens the existing Goal Composer with the selected market dataset, interval, periods per year and exact stored UTC coverage. Eligible market submissions call `/v1/quant/market-runs` with explicit RFC3339 UTC bounds and PLAN/AUTO mode; legacy daily submissions keep the existing `/runs` request. Server 409/422/transport failures retain the form and use the shared error presentation.
- Snapshot hydration resolves the public market-run identity from the dedicated directory before enabling controls. PLAN approve/change/cancel and terminal retry dispatch to the market-run mutation endpoints, private market snapshots stay read-only, and legacy controls continue to use their existing transport. Runs merges the two server directories without coercing either DTO and reopens both through the existing historical workspace-snapshot flow.
- Overview, Analysis and Strategy Report consume the generic cadence projection: interval, periods per year, RFC3339 UTC coverage, market-bar kernel identity, performance points and trade timestamps stay intact through current/history/reload/export. The shared chart math now accepts both legacy dates and RFC3339 timestamps, so intraday points retain distinct horizontal positions and date matching rather than collapsing to one day or one x-coordinate.
- Strict parsers route every explicit market contract/schema, intraday interval, UTC range, cadence, runtime or pin signal through the market snapshot contract; incomplete or mixed legacy/market identity fails closed and remains read-only rather than silently becoming daily or enabling legacy mutations. Calendar/session/timezone/annualization validation mirrors C1 exactly: 24x7 continuous UTC uses 8,760/2,190/365 for `1h`/`4h`/`1D`, while supported exchange daily calendars use their declared exchange timezone, regular session and 252. The bundled v1 fixtures remain parser-compatible and retain their daily values and request path.
- Deterministic public-v2 Playwright fixtures cover research-eligible BTCUSDT `1h` and `4h` datasets, running-to-completed AUTO flow, dedicated PLAN mutations, report Markdown copy/download and historical reopen. The `1h` proof keyboard-inspects two distinct observations at 00:00 and 01:00 on the same UTC day through Analysis and reopens the identical hourly Run from History; the baseline history assertion remains exact at four Runs/five table rows including the 4h identity and all legacy rows. These fixtures are explicitly labelled synthetic and make no live-provider claim. The closed workflows pass at 1440, check page overflow at 1024, and retain the existing legacy daily research and preview regressions.
- Browser isolation uses one authenticated reset boundary that restores the configured Quant fixture only after all startup initialization. Every retained Quant state, including ready and waiting-for-review, has an exact lifecycle baseline test; the retired Glint Investigation variants and obsolete page specs were removed rather than skipped or redirected to a non-product page.
- The complete 13-state Quant browser matrix verifies that dataset loading, candidate generation and report assembly open on an accessible, state-specific current-progress view with working detail navigation, while a cancelled Run retains a direct `Inspect run` action into its existing read-only Analysis and Run Monitor evidence. Both paths remain free of page overflow at 1440 and 1024.

Historical C4 limit: market research initially used the exact full stored UTC coverage required by C3B2b. P3 below adds bounded stored-window selection; C4 still does not add new pages or client-side metric calculations.

### P3 — bounded public market-v2 research windows

Primary user action: choose the relevant stored-data period for a public `1h`/`4h`/`1D` research Run, then use a different valid period in Continue / Refine without importing a duplicate dataset.

Implemented:

- The existing market-run request accepts strict aware UTC bounds inside the selected dataset coverage. Both bounds must match stored bar timestamps, preserve dataset cadence and leave at least 252 inclusive bars; naive, non-UTC, reversed, out-of-coverage, misaligned and too-short ranges fail before Run or provider mutation.
- The authoritative runtime descriptor crops the immutable stored bars to the selected window and derives new descriptor/split identities from the source record, selected UTC bounds and retained bar count. Dataset and record digests remain source identities; snapshots, reports, performance timestamps and history expose the selected range and cropped bar count.
- New research and Continue / Refine reuse `QuantGoalComposer` with native UTC datetime inputs, stored coverage limits and cadence steps. Continue keeps project, dataset, symbol, cadence, annualization, contract and authenticity while allowing a different valid window and therefore different runtime/split pins.
- Retry remains another attempt of the same Run and must retain the exact selected bounds, runtime descriptor and sealed split. Relationship parsing distinguishes this from a valid Continue version and fails closed on mixed or partial identity.
- Integration coverage proves an aligned `4h` subrange end to end, rejects invalid ranges without provider planning or state mutation, reloads exact pins, and verifies Continue with a different range followed by an exact Retry. Vitest covers composer submission and relationship identity; fixture Playwright covers Data → bounded `4h` AUTO → Analysis → Report/export → Runs reopen at 1440 and checks 1024 overflow.

Not implemented: freeform resampling, sparse/non-contiguous windows, multiple disjoint windows in one Run, arbitrary client-provided cadence/annualization, or client-side metric recomputation.

### P4 — direct source-version comparison

Primary user action: from a validated Continue / Refine version in Runs, compare the current stored result with its source version without returning to the list and manually selecting both rows.

- The existing Research path now exposes `Compare with source` only when the current snapshot matches its directory record and the source relationship passes the same fail-closed lineage projection used by Open source version.
- The action reuses the existing stored-snapshot comparison table. The current snapshot is reused in memory and only the source snapshot is fetched; loading and failure behavior remain on the established comparison path.
- Dataset, symbol, interval and research-range differences continue to be listed explicitly. A Continue that deliberately changed its P3 window is therefore comparable as two retained outcomes but is not labelled equal-context evidence.
- Component coverage verifies the validated direct action and absence on a mismatched relationship. Playwright verifies the one-click source comparison and the existing 1024-width horizontally scrollable table.

Not implemented: automatic causal attribution between versions, metric normalization across different windows, a separate Research Series dashboard, or new persisted series summaries.

### Phase 1B C5 — real Binance multi-interval verification

Status: **Passed for the requested `4h` and `1D` paths on 2026-07-22.** Both runs used real Binance Spot BTCUSDT provider fetches and DeepSeek `deepseek-chat` with mock fallback disabled.

- The `4h` dataset `binance-BTCUSDT-4h-ec61e63b39a90e4f` retained 1,000 closed bars from `2026-02-05T12:00:00Z` through `2026-07-22T00:00:00Z`, dropped one current unclosed candle, reported zero cadence gaps, and pinned 24x7/continuous/UTC with 2,190 periods per year. Public Run `c5a33be3-16df-5b65-8187-25abfcf466b8` completed in 10 Agent iterations with three canonical-distinct candidates, exactly one train-only feedback artifact, a feedback-linked third candidate and final three-row comparison. Its final RSI candidate passed the single sealed holdout.
- The `1D` dataset `binance-BTCUSDT-1D-98dad35bb7632be9` retained 1,000 closed bars from `2023-10-26T00:00:00Z` through `2026-07-21T00:00:00Z`, dropped one current unclosed candle, reported zero cadence gaps, and pinned 24x7/continuous/UTC with 365 periods per year. Attempt 1 (`297b6851-5ef6-58d6-8751-4803818e1ed7`) stopped honestly after bounded provider decision failures with no candidate or fallback. The existing Retry action created clean attempt 2 (`feace1aa-b2e5-5bee-96ba-213c36c5887d`) with identical dataset/runtime/split pins; it completed the same strict three-candidate chain in 10 iterations and retained a sealed-holdout failure with `revise_research` rather than fabricating promotion.
- Real React verification covered Data Preview, market-run creation, live Experiments, timestamp-preserving Analysis, Report, server-rendered Markdown copy and Runs history. Opening the non-current retained `4h` Run after the `1D` result issued `/v1/quant/runs/c5a33be3-16df-5b65-8187-25abfcf466b8/workspace-snapshot` and then hydrated its public market identity from `/v1/quant/market-runs`; the restored Report remained `4h`, 2,190 periods/year and bound to the original RSI candidate.
- C5 exposed and closed two frontend contract bugs: public-run hydration now compares equivalent RFC3339 UTC instants rather than raw `Z`/`+00:00` spellings, and completed market reports parse the v2 cadence-quality contract instead of coercing it into the legacy daily-quality shape.
- Legacy and market Runs share the store's single UUID namespace and generic historical snapshot resource. The live union contained one legacy and three market Run ids with no collision; Runs therefore continues to use the globally unique id rather than introducing a redundant `(contract, id)` UI identity.

Current limit: real-provider proof covers `4h`, `1D` and the P5 bounded `4h` Continue below; the already implemented `1h` contract and deterministic UI flow were not separately exercised against Binance/DeepSeek. C5's historical exact-full-coverage boundary is superseded by P3 and its real P5 proof.

### P5 — real bounded-window Continue verification

Status: **Passed on 2026-07-22** with one paid DeepSeek continuation and no additional Binance fetch, root research Run or Mock fallback.

- Source Run `c5a33be3-16df-5b65-8187-25abfcf466b8` and its collected dataset `binance-BTCUSDT-4h-ec61e63b39a90e4f` were reused. Continue Run `a7bd7568-3cd5-51bc-bdb1-a655dd3d4515` retained the source dataset digest and `4h`/2,190-PPY cadence while changing the source's 1,000-bar range to the aligned 600-bar range `2026-04-13T04:00:00+00:00` through `2026-07-22T00:00:00+00:00`; runtime descriptor and sealed split identities changed accordingly.
- Real DeepSeek `deepseek-chat` completed in 9 of 12 allowed Agent iterations with three canonical-distinct candidates, one train-only feedback artifact, a feedback-linked third candidate, a final three-candidate comparison and one sealed report. No provider fallback event was present.
- The selected candidate's 120-bar sealed holdout was honestly `inconclusive` because it had no market exposure; the reported next step is `collect_more_evidence`, not a fabricated promotion.
- Current snapshot hydration verified 600 bars and the bounded UTC range. Server-rendered Markdown export retained `BTCUSDT · 4h` and the same range. The source and child remain eligible for the existing P4 comparison, which must label their research ranges as different contexts.
- Sanitized machine-readable evidence is retained at `.run/p5-bounded-continue-20260722/p5-evidence.json`. Retry execution was deliberately skipped to avoid a second paid run; exact child-window Retry pins remain covered by integration tests.

Not claimed: real `1h` provider verification, like-for-like performance improvement across different windows, or promotion of the inconclusive strategy.

### P6 — explain version change

Primary user action: understand within the existing source comparison what a Continue / Refine version changed, why it was created and whether its retained result is meaningfully comparable with the source.

- A directory-validated source/child pair now shows the retained refinement reason and selected strategy path above the existing comparison table. Unrelated, ambiguous or incomplete pairs do not receive a version explanation.
- When dataset, symbol, interval and research range are the same, the view computes exact deltas from the two retained snapshots for annualized return, Sharpe, maximum drawdown and trades. A deterministic verdict labels the directional outcome as improved, weaker, mixed or no material change; no model-generated causal claim is introduced.
- When any research context differs, the view says `Not directly comparable`, names the differing context and suppresses metric-delta and improvement language. Equivalent RFC3339 spellings such as `Z` and `+00:00` compare as the same UTC instant.
- The capability reuses Runs, the existing source action, stored workspace snapshots and current comparison table. It adds no backend calculation, persistence model, endpoint, page or provider call.
- Component coverage verifies both like-for-like and different-range behavior. Fixture Playwright verifies the one-click source explanation and retained refinement reason in the 1024-width Runs workflow.

Not implemented: causal attribution, cross-window normalization, model-written conclusions or a separate Research Series dashboard.

### P7 — comparison-to-Refine handoff

Primary user action: move directly from a source/version comparison into the next independent Refine run without reselecting the candidate or reconstructing why the prior result needs another iteration.

- `Refine from this result` appears only for a directory-validated source/child comparison whose child snapshot and selected candidate pass the existing continuation eligibility contract. Ineligible, ambiguous and strategy-incomplete results remain read-only.
- The handoff reuses the child Run as the parent, its selected canonical candidate as the seed, its project question, dataset, cadence and research range as retained context, and the existing Auto Research composer as the editable destination.
- The refinement reason is prefilled deterministically from retained sealed-holdout evidence when present, otherwise from the retained report next step or comparison outcome. It names the seed strategy and asks for one bounded change; the user can edit it before starting the new immutable Run.
- Existing market-v2 and legacy create paths, lineage pins and server validation remain authoritative. No new endpoint, model call, persistence aggregate, page or freeform strategy contract was added.
- Component coverage verifies prefill, eligibility and callback identity. Fixture Playwright covers `Compare with source → Refine from this result → Research setup` and verifies the carried objective and reason.

Not implemented: automatic submission without review, model-generated causal diagnosis, bulk branching from arbitrary unrelated comparisons or a graphical research tree.

### P8 — internal primary-loop task check

The existing component and browser workflows were reviewed against the five primary tasks: start bounded research, observe material progress, identify the selected result, compare versions, and carry one result into Refine/history. The comparison-to-composer regression and the shared Report/Experiments/Analysis continuation paths remain green. This is deliberately recorded as an internal capability check; no external user study, completion-time benchmark or user-behavior claim is made.

### P9 — Agent-guided next-step recommendation

Primary user action: review one evidence-backed next-research proposal after a terminal report, then either stop the sequence or open the existing composer with an editable bounded Refine draft.

- A pure typed projection combines the Agent-authored report recommendation, the report-selected canonical candidate and authoritative sealed-holdout status. It does not parse chat, call another model, create a new persistence aggregate or recalculate quantitative metrics in the client.
- Failed evidence proposes one bounded change aimed at positive return and shallower holdout drawdown. Inconclusive evidence proposes one bounded change aimed at sufficient holdout exposure. Both require a final comparison and one new sealed-holdout result.
- Passed sealed-holdout evidence recommends `Stop` and does not present another default Continue action. The explicit stop condition says not to extend the sequence without a materially different user hypothesis.
- A `Refine` proposal carries its reason, selected seed strategy, required evidence and stop condition into the existing Goal Composer. The user can edit it and must explicitly start the new independent Run; existing lineage, dataset/range pins and server validation remain authoritative.
- The same projection supplies P7's comparison-to-Refine reason, keeping one UI decision path instead of duplicating campaign logic. Component and presentation tests cover Refine and Stop; fixture Playwright keeps comparison handoff and the three existing continuation entry points green.

Current boundary: the recommendation is Agent-guided rather than a second post-holdout model call. It creates at most one reviewable draft and has no scheduler, campaign table, multi-Agent roles, automatic Run creation or infinite loop.

### P10 — one suggested refinement

Primary user action: approve the Agent's retained next-research decision once and immediately start one bounded independent Auto Research version without reconstructing or reviewing the composer fields.

- Failed or inconclusive P9 proposals expose `Run suggested refinement` alongside the existing editable `Continue research` path. The direct action uses the same selected candidate, project, dataset, cadence, research window, structured refinement reason and server-owned continuation validation.
- The created version runs in existing Auto Research mode. It is still a normal immutable Continue / Refine Run, appears in existing history and produces the same comparison, Analysis and Report evidence; no alternate execution path or client-side metric calculation was added.
- Autopilot is deliberately limited to one additional Run per explicit click. It stops at the next terminal report for user review, so a browser session cannot silently create a chain, retry failures or repeatedly optimize against sealed-holdout evidence.
- Passed sealed-holdout evidence remains `Stop` and never exposes the direct-run action. Historical snapshots remain read-only, and the existing command lock prevents duplicate starts while creation is pending.
- Presentation and component coverage verify the explicit one-run execution contract, shared proposal reason and retained manual review action.

Current boundary: there is no background scheduler, persisted series budget, unattended multi-round loop, post-holdout model call or Campaign table. A durable controller requires a server-owned contract and a training-only cross-run decision policy rather than session-local UI state.

### P11 — Agent-native Research Loop v1

Primary user action: opt into one bounded, training-evidence-driven follow-up version when starting research, then review the resulting series without manually reconstructing the next experiment.

Implemented:

- Strict `QuantResearchLoopPolicy`, `QuantResearchSeriesDecision`, `QuantResearchSeriesContext` and technical `QuantResearchSeriesControl` contracts define the only supported v1 shapes.
- `stop_after_run` is one version / three experiments / twelve Agent actions. `one_train_only_follow_up` is capped at two versions / six experiments / twenty-four Agent actions. Automatic Retry is forbidden and descriptor identity must remain exact.
- A Refine decision must name the final training-comparison artifact, selected seed, bounded focus and reason. Stop/review decisions cannot carry hidden refinement inputs. `FinishResearchArguments` can carry this typed decision without adding an eighth Agent tool.
- The dedicated market-v2 create contract accepts the policy only for a root Auto Research Run. New Research exposes `Stop for review` and `Allow one follow-up`; legacy daily, Plan and Continue / Refine requests cannot silently enable it.
- The Agent receives a strict train-only series context with remaining version budget and ancestor strategy identities. A follow-up decision must use the latest final training comparison, its selected seed and a canonical-distinct strategy; parent holdout, report, generalization and validation evidence are excluded from child context.
- Finishing the root atomically precommits exactly one independent Continue / Refine child before calculating the root sealed holdout. The child retains dataset, cadence, runtime, split, provider and source-candidate lineage, runs through the existing seven-tool strict 2+1 loop and cannot create a third version.
- Durable restore validates series root/version/child relationships, exact runtime pins, final comparison/seed identity, ancestor strategy novelty and typed policy/decision state. To keep the declared two-version, six-experiment and twenty-four-action budget truthful, Retry is unavailable inside an opted-in bounded series; ordinary Runs retain the existing Retry behavior. Failed evaluation or persistence restores durable workspace truth rather than leaving a ghost child.
- The existing Runs, Analysis and Report surfaces review both versions through existing lineage and evidence views; no Campaign page, new table, scheduler or alternate metric path was introduced.
- Integration coverage proves a root plus exactly one child completes in 22 Mock Agent actions, each version has three candidates, ancestor canonical keys are disjoint, the root report points to the child and a fresh store restores the same series.
- Fixture Playwright verifies the existing 4h Data → Research Setup → `Allow one follow-up` → market-run request → Experiments → Analysis/Report/export → Runs-history workflow at 1440 and 1024 widths, including the exact 2/6/24 request policy.
- A real Binance BTCUSDT `4h` + DeepSeek verification completed one root and one follow-up Run with three candidates in each version, 19 total Agent actions, no provider failure and no Mock fallback. An initial live attempt exposed that opaque ancestor hashes were insufficient for model planning; the retained series context now supplies exact ancestor template/parameter identities, after which the same strict live verification completed.

Current boundary: the automatic path is market-v2 Auto Research only, permits exactly one follow-up, has no Retry inside the bounded series and stops after the second report. It is not a scheduler, optimizer, arbitrary-code Agent or unbounded campaign controller.

### P12 — Strategy Evidence Inspection v1

Primary user action: inspect where the selected strategy entered and exited against the retained market path, then connect each trade's return and holding period to its market context without leaving Analysis.

Implemented:

- Analysis reuses the existing strategy tab set and shared `QuantMarketChart`; no page, shell, chart library or client-side performance calculation was added.
- The Market view shows the selected candidate's bounded stored price/volume projection, all retained entry/exit markers, and an exact selected-trade strip for entry, exit, return and holding duration.
- Selecting a trade in the shared dense table highlights its entry and exit markers. Candidate-linked trades remain the authority, and an eligible Run projection retains every candidate trade timestamp so switching candidates cannot silently lose an event from the chart sample.
- Existing report-selected bar markers remain unchanged for the general workspace chart. The added retained timestamps carry no extra candidate result or metric calculation.
- Sparse Run projections deliberately disable SMA overlays: rolling indicators remain available only on the latest-contiguous Data Preview contract. The Analysis chart states that it does not recalculate performance.
- Component coverage verifies Market navigation, marker count, selected-trade synchronization and holding context. API integration coverage verifies current and historical snapshots retain every projected candidate trade timestamp while marker identity remains tied to the report-selected candidate.
- Browser inspection at 1280 and 1024 verified four retained markers, two selected markers, exact trade context and no document or table overflow.

Current boundary: this is a bounded explanatory projection rather than a full charting terminal. It does not add zoom, drawing tools, arbitrary indicators, intrabar execution simulation or client-owned strategy signals.

### P13 — Candidate Evolution Explanation v1

Primary user action: understand why the Agent tested a candidate, whether it came from the initial research goal or retained training feedback, what changed, and why the final candidate was or was not selected.

Implemented:

- The completed candidate projection now carries one optional structured evolution record: hypothesis, initial versus training-feedback origin, change rationale, feedback reference candidate, final training-comparison rank and selection reason.
- The projection is derived from existing experiment records, the run-scoped train-only iteration-feedback artifact, the latest final training comparison and the retained report selection. It does not expose the internal feedback artifact or create a second decision store.
- A feedback-driven third candidate names the training reference candidate and retains the Agent-supplied change rationale. Initial candidates are labelled as initial rather than being presented as revisions.
- Selection copy reports the candidate's actual final training rank and explicitly states that sealed-holdout evidence was unavailable at selection time. A non-selected candidate is described as such even when its deterministic metric rank is higher than the Agent's retained selection.
- Experiments adds one compact Research path section below the existing comparison table for the currently selected candidate. Report Summary reuses the same structured fields for research hypothesis, iteration change and selection basis.
- Older snapshots remain readable because the evolution projection is optional; when present, the frontend parser validates its closed origin and field shape rather than silently treating unknown evidence as legacy data.
- Integration coverage verifies a strict real-runtime 2+1 Mock run projects candidate C's persisted feedback source and change rationale without holdout leakage. Frontend coverage verifies parsing and both existing presentation surfaces; focused Playwright verifies shared candidate selection and Report linkage.

Current boundary: this explains retained decisions; it does not add chain-of-thought, a chat transcript, post-holdout rationalization, an eighth Agent tool or another experiment round.

### P14 — Executable Research Plan v1

Primary user action: approve a bounded research plan and know that the Agent's later experiments will follow that plan rather than treating it as descriptive copy.

Implemented:

- The existing generated plan now persists its approved strategy-family allowlist and completion criteria on the Run and in the plan artifact; no new Mission, Question or Iteration model was added.
- Every Agent decision context receives the same approved plan beside the existing goal, tools, budget and retained evidence.
- Candidate creation fails closed with `CANDIDATE_OUTSIDE_APPROVED_PLAN` before any experiment, artifact, event or budget mutation when a provider requests a strategy family outside the approved plan.
- The plan contract accepts only the three registered strategy families and rejects duplicates. Persisted runs reject invalid or tampered plan policies during restore.
- Retry and the one bounded research-series follow-up retain the source plan policy exactly. A valid plan-change request replaces it only through the separately generated and validated P15 plan.
- The existing Research Copilot Run details show human-readable planned strategy families and completion criteria. Older fixture snapshots remain compatible because this additive projection is optional, while present values are parsed strictly.
- Contract, Agent-loop, parser and component coverage verifies the closed family set, plan context, zero-mutation rejection and existing-surface projection.

Current boundary: completion criteria are explicit Agent context and user-visible policy, while the existing strict 2+1/final-comparison/holdout gates remain the authoritative server-side completion checks. This package does not add arbitrary user-authored criteria, a strategy DSL, another tool or another page.

### P15 — Real Replan v1

Primary user action: tell the Agent what is wrong with a proposed plan and receive a genuinely revised executable plan before approval.

Implemented:

- Both existing `Request changes` entry points—Research Copilot and Run Monitor—collect an explicit bounded change request. Clicking the action alone does not submit fallback prose.
- Legacy daily, workspace-command and public market-v2 routes preflight state, identity, row version and plan revision before invoking the configured planner, so stale or illegal requests do not spend a provider call or mutate the Run.
- The planner receives the original research goal plus the user's requested change and must return the same closed executable plan contract used by initial planning.
- Store mutation revalidates after the provider call, then publishes the revised plan, policy, artifact and event together. Planner failure, invalid output or concurrent state drift leaves the prior Run and plan unchanged.
- Market-v2 plan changes retain the dedicated public contract and exact runtime pins; legacy daily behavior remains on its existing route.
- Integration coverage verifies a materially changed strategy-family policy and zero mutation on planner failure. Component and browser coverage verifies explicit feedback from both visible controls and the dedicated market-run request payload.

Current boundary: Real Replan revises the approved experiment policy; it does not add chat history, an unconstrained planning loop, automatic approval, arbitrary strategies or a plan-diff page.

### P16 — Objective-Aligned Comparison v1

Primary user action: approve how candidate evidence will be compared and receive a final candidate selected by that same objective.

Implemented:

- The executable plan carries one closed `selection_objective`: `risk_adjusted_return`, `total_return` or `drawdown_control`. It is persisted on the Run and current plan artifact, projected into every Agent decision and shown in the existing Run details.
- The authoritative training comparison uses the approved deterministic ranking. Its first candidate also becomes the train-only improvement reference for the feedback-driven third experiment.
- Retry and the bounded Research Series child retain the exact objective. Restore cross-validates the Run, current plan artifact, training comparison, iteration feedback and improvement reference; unknown, missing or mismatched policy fails before cache replacement.
- P19 now permits a non-leading selection only through its structured, server-verified robustness decision. Unsupported or ambiguous deviations still fail before Research Series mutation, sealed holdout, report or persistence.
- Legacy records in which both the Run and plan artifact predate the objective field default to `risk_adjusted_return`. One-sided absence or an explicit unknown value is rejected rather than silently normalized.
- Agent, API, runtime and migration regressions cover the three full ranking orders, deterministic tie-break, non-leading zero-mutation rejection, legacy restore and artifact-only tampering. The existing real DeepSeek planner compatibility check returned the closed field with Mock fallback disabled.

P19 subsequently implemented the bounded ranking override described above; free-form or
unverifiable deviations remain unsupported.

### Live Research Run Workbench

Primary user action: understand what an active research run is testing, which candidate is running, the latest measured result and what happens next without reading Agent logs.

Reuse:

- `QuantOverviewWorkbench`, Experiments/Analysis tabs and `QuantStrategyLab`.
- `QuantRunMonitor`, `QuantActivityFeed`, polling and existing run controls.
- Persisted run states, experiment records, candidate metrics, fixtures and workspace parser.

Implemented:

- Active runs open Experiments as the primary work area while leaving every workspace tab available.
- A typed `liveResearch` projection derives current experiment, latest completed result, candidate states and next phase from structured store records; it never parses event summary prose.
- Loading, candidate generation, experiment execution, repair, validation and report generation all have truthful phase-specific empty or populated states without invented percentages or metrics.
- Candidate progress uses the shared dense research table; completed runs continue to use Candidate Comparison and Analysis unchanged.
- Run Monitor remains visible with legal controls, while Activity and Artifacts are collapsed into secondary detail.

Next missing core capability: add multi-interval dataset support and research interval selection once the stored dataset contract exposes intervals beyond `1D`.

### Durable Strategy Report Markdown Export

Primary user action: preview the exact selected Strategy Report, copy its Markdown, or download a durable `.md` file for the current or opened historical run.

Reuse:

- Existing Strategy Report Summary, report tabs and shared `selectedCandidateId`.
- Persisted run, project, dataset, candidate, benchmark, validation, trades and strategy artifacts.
- Quant API transport/error handling and the existing modal/button vocabulary.
- Browser clipboard and Blob download mechanisms.

Implemented:

- Workspace-scoped `strategy_report_markdown` request and response contracts require explicit run and candidate identity and return a constrained server filename, media type, rendered content and SHA-256 digest.
- The backend verifies run ownership, candidate membership and a persisted report before rendering; metrics and Markdown content are never accepted from the client.
- Deterministic Markdown covers research context, selected strategy and parameters, strategy-vs-benchmark metrics, conclusion/recommendation, retained holdout/walk-forward evidence, limitations, selected-candidate trades and strategy specification.
- Report Summary opens a compact server-loaded preview with retry, copy failure and download failure states; candidate changes and historical run identity flow through the request.
- The frontend adapter rejects unsafe filenames, mismatched response identity, invalid media types, empty/oversized content and malformed digests.
- Backend, API adapter, component and Playwright coverage verifies determinism, workspace isolation, invalid/no-report states, candidate selection, preview/retry, copy/download and historical identity at 1440 and 1024 widths.

Next missing core capability: add multi-interval dataset support and research interval selection once the stored dataset contract exposes intervals beyond `1D`.

### Strategy Comparison & Performance Workbench

Primary user action: compare candidates, select a strategy and understand its return and risk relative to the benchmark.

Reuse:

- Current shell, tabs and Copilot column.
- `quant-research-table`.
- Existing candidate metrics, benchmark, trades and `selectedCandidateId`.
- Strategy Report tabs and selection behavior.
- Existing fixtures, parsers and E2E harness.

Implemented:

- Typed candidate and benchmark daily performance series: date, equity and drawdown.
- Deterministic fixture generation for at least three candidates plus benchmark.
- Sortable candidate comparison table with status, return, Sharpe, drawdown, trades and benchmark difference; parameters remain in the selected-strategy detail to avoid duplication.
- Linked Equity vs Benchmark, Drawdown, Period returns and Trades views.
- Shared candidate selection across Experiments, Analysis and Report.
- Results Overview now reuses the same persisted strategy and benchmark performance chart, exposes Equity/Drawdown switching, summarizes decisive metrics, and links candidate selection across Overview, Experiments, Analysis and Report.
- Strategy Report Summary now reuses persisted strategy-vs-benchmark performance, decisive metrics, validation/limitations and real Analysis/Trades/New research actions; candidate selection remains linked through Summary, Candidates, Trades and Strategy.
- Failed, cancelled and no-viable outcomes retain decision-first fallbacks; absent candidate performance produces an explicit empty state rather than a synthetic curve.

Next missing core capability: add multi-interval dataset support and research interval selection once the stored dataset contract exposes intervals beyond `1D`.

### Runs History & Comparison

Primary user action: find a prior research run, understand how its result differs, select 2–4 credible runs and compare their stored outcomes without opening each workspace.

Reuse:

- Existing `QuantRunsPage`, wide utility frame, project filter, master-detail summary and historical open-run lock/error flow.
- `QuantApi.listProjects`, `listRuns` and `getRunWorkspaceSnapshot`.
- `QuantWorkspaceSnapshot` dataset, scope, candidate, benchmark, report and generalization fields.
- Shared `quant-research-table`, controls, tokens, responsive shell and current notification handling.

Implemented:

- Search across research question and project name, real-state outcome filters, newest/oldest sorting, clear-filter and compact no-result states.
- A dense run directory showing question, project, outcome, mode, attempt, update time, comparison selection and the existing open-run action.
- Controlled comparison selection with a four-run maximum and a two-run minimum.
- Lazy historical snapshot loading after Compare, with per-run loading, failure and retry that do not affect historical opening.
- A transposed comparison table covering dataset/symbol/interval, research range, selected candidate, annual return, Sharpe, drawdown, trades, benchmark delta and validation/holdout/outcome.
- Explicit dataset, symbol, interval and research-range differences so stored metrics are never presented as fully comparable when their contexts differ.
- Deterministic server-owned E2E history fixtures for comparable and incompatible results, plus 1440 and 1024 layout coverage.

Next missing core capability: add multi-interval dataset support and research interval selection once the stored dataset contract exposes intervals beyond `1D`.

### Dataset Preview & Correct Market Chart

Primary user action: confirm a catalog dataset's coverage, stored price/volume path, source and quality before using it for research.

Reuse:

- Existing Data Catalog search, filters, selection, import actions and utility frame.
- `DatasetSnapshot`, stored OHLCV bars, source/quality metadata and current API error handling.
- `QuantMarketWorkspace` candlestick/line vocabulary and current chart tokens.

Implemented:

- A separate Preview action opens a responsive Catalog master-detail view without changing routes or conflating preview with dataset selection.
- A workspace-scoped, read-only dataset preview endpoint returns at most 240 latest-contiguous stored OHLCV bars by default, with an explicit bounded point-count contract and no frontend-generated prices.
- The shared `QuantMarketChart` now drives both workspace and catalog views so dataset-specific prices, volume and calculations cannot diverge.
- SMA20 and SMA50 use a tested rolling calculation with null warm-up and preserved output length; overlays are shown only when enough contiguous bars exist.
- Coverage, total bar count, returned-bar rule, source, quality, blocked eligibility and the real Use for research action are visible in the preview.
- Deterministic SPY and BTCUSDT preview fixtures verify symbol, range and price changes, plus loading, retry, selection and 1440/1024 responsive behavior.

Next missing core capability: add multi-interval dataset support and research interval selection once the stored dataset contract exposes intervals beyond `1D`.

### Strategy Performance Chart Inspection

Primary user action: read the selected strategy, benchmark, difference and drawdown at an exact retained date from Overview, Analysis or Strategy Report.

Reuse:

- Exported `StrategyPerformanceChart` and its three existing consumer locations.
- Typed candidate and benchmark `performanceSeries` points.
- Current SVG, Equity/Drawdown tabs, chart tokens and responsive workbench layouts.

Implemented:

- Candidate and benchmark paths now share date-based coordinates instead of assuming equal array indexes or lengths.
- Pointer movement selects the nearest candidate point; pointer/touch selection and keyboard navigation pin a retained date, while an unpinned pointer leave returns to the latest summary.
- A shared compact data strip exposes Date, Strategy, Benchmark and Difference in both Equity and Drawdown modes without live-announcing every pointer movement.
- Benchmark values use exact-date or nearest-retained-date matching; absent benchmark evidence omits benchmark and difference rather than inventing values.
- The focusable chart supports ArrowLeft/ArrowRight and Home/End with bounded selection and an explicit interaction label.
- Equity axes show normalized-return ticks; Drawdown includes 0% and negative ticks. Single-point series retain the readout and markers without drawing a misleading line.
- Pure chart math and shared component tests cover empty/single series, unequal lengths, missing dates, pointer bounds and keyboard bounds; Playwright covers inspection across Overview, Analysis and Report at 1440 and 1024 widths.

Next missing core capability: add multi-interval dataset support and research interval selection once the stored dataset contract exposes intervals beyond `1D`.

### Strategy Report Export

Primary user action: preview the exact selected-candidate Strategy Report and copy or download a durable Markdown file for later research and sharing.

Reuse:

- Existing Strategy Report Summary, shared candidate selection, persisted report artifact and run/project/dataset context.
- Candidate, benchmark, generalization, walk-forward, trade and strategy-spec records owned by the Quant store.
- Current Quant transport/error handling and browser Blob/clipboard mechanisms.

Implemented:

- A typed `strategy_report_markdown` request binds an explicit run and candidate; the server verifies workspace/run/candidate ownership and never accepts client-authored metrics or report content.
- Deterministic Markdown includes research context, selected parameters, strategy-versus-benchmark metrics, conclusion, validation, limitations, selected-candidate trades and strategy specification.
- The response supplies a server-constrained `.md` filename, media type, rendered content and SHA-256 content digest with a bounded 256 KiB payload.
- Report Summary opens a compact server-rendered preview with real loading, retry, copy failure and download failure states; closing restores focus to Export report.
- Candidate changes and historical run navigation are carried into the export request, preventing an alternate candidate or historical report from silently exporting latest-run evidence.
- API, parser, component, deterministic/scoping integration and browser-flow coverage verify preview, copy, filename-bound download, invalid candidate, absent report and historical identity.

Next missing core capability: add multi-interval dataset support and research interval selection once the stored dataset contract exposes intervals beyond `1D`.

### Continue / Refine Research

Primary user action: continue from a selected strategy in a terminal Run, revise the objective and research range, and create an independent next Run without rebuilding setup from scratch.

Implemented:

- Strategy Report Summary exposes Continue research for the currently selected retained candidate; Retry remains the same Run's next attempt, while ordinary New research has no source relationship.
- Experiments, Analysis and Report share the same selected-candidate Continue research action; the client rejects partial lineage before any create-run request, while the server remains the authority for seed eligibility.
- The existing Research Setup composer is prefilled with the source objective and compact candidate/result context, requires an explicit refinement reason, locks the source dataset/symbol/interval, and still permits a coverage-bounded date-range change plus Plan first or Auto Research.
- Browser-resilient `continueRun` and `seedCandidate` URL state reopens the historical source snapshot before allowing creation; cancellation and ordinary New research clear the continuation state.
- The API accepts lineage only as a complete `parent_run_id` / `seed_candidate_id` / `refinement_reason` group. It verifies workspace and project ownership, terminal source state, same dataset, candidate ownership and a usable persisted specification.
- The store reconstructs only seed name, template and parameters plus the source goal and explicit reason from persisted parent records. Parent metrics, benchmark deltas, validation/holdout, limitations and recommendations never enter child Agent context; client-provided strategy evidence is never accepted, and the child Run remains independently executed and reported.
- Child workspaces surface a compact “Continued from …” source line. Reopened historical workspaces remain read-only; a researcher reuses historical evidence through Runs comparison and `Refine from this result`, which binds the selected historical source rather than the latest workspace Run.
- Report, Experiments and Analysis expose the same Continue research entry point only for the current eligible terminal Run. Fixture E2E validates that shared gate, the read-only historical boundary, comparison-to-Refine source identity, the reason-required composer and 1024-width containment.

Next missing core capability: assess **Autonomous Iteration v1**—a bounded, user-approved way to act on retained validation evidence across a continuation sequence—before adding more strategy families or execution features.

### Autonomous Iteration v1 — Package A: train-only feedback contract

Primary user action: let a future bounded Agent decision use a trustworthy comparison of completed training candidates without leaking sealed-holdout evidence or confusing a refinement seed with a tested result.

Implemented:

- `QuantRefinementSeedContext` is a closed typed contract containing only parent/source identity, goal, reason and the persisted seed candidate name/template/parameters.
- `QuantIterationFeedback` is a closed, workspace/run-scoped `iteration_feedback` artifact: one round of training split, benchmark, completed-candidate metrics/deltas, aggregate-only walk-forward evidence, exact novelty keys, remaining budget and a deterministic improvement reference.
- Feedback is generated only after two completed non-fixture candidates while an experiment slot remains, is idempotent across repeated comparison/reload, and never contains holdout, generalization, validation detail, raw walk-forward folds, trades or equity curves.
- Agent context reads the persisted current-run feedback naturally through the existing serialized prompt; the existing seven-tool manifest and Mock action order remain unchanged. Retry retains refinement lineage but starts without prior attempt candidates, artifacts or feedback.
- Internal feedback stays off the front-stage snapshot and artifact/event surface; it is only reconstructed for Agent context.
- Contract, comparison, retry, prompt, enum/OpenAPI and fixture-transport tests cover the train-only boundary and feedback eligibility.

### Autonomous Iteration v1 — Package B: bounded 2+1 candidate loop

Primary user action: let a bounded Agent compare two completed training candidates, use the retained train-only feedback to test exactly one distinct third candidate, and finish from an explicit final comparison.

Implemented:

- The deterministic Mock loop now follows inspect → templates → create/backtest A → create/backtest B → compare → feedback-driven create/backtest C → final compare → finish in 11 actions under the default `max_experiments=3` and `max_agent_iterations=12` budget.
- The store rejects a third non-repair candidate before feedback with `ITERATION_FEEDBACK_REQUIRED`, requires a bounded non-empty change rationale after feedback, links C to the persisted feedback artifact, and prevents the same feedback batch from creating another exploration candidate.
- Training comparisons retain a deterministic ranking. A report can only select a completed candidate from a comparison covering the current completed candidate set, preventing first-completed budget fallback and ensuring C is present in the final comparison.
- Budget-exhausted polling now deterministically compares before finishing when the latest comparison is missing or stale, then finishes on the next poll once the persisted comparison covers the current completed candidate set.
- Final-report workspace snapshots keep the report-selected candidate's own trades and markers; they no longer borrow another candidate's trade log when the selected run has no trades.
- When fewer than four actions remain at feedback time, the Agent preserves the existing explicit comparison for final selection rather than starting a candidate it cannot backtest, compare and report.
- Mock/provider, store-gate, persistence/reload, final-comparison, retry/feedback-isolation and Agent-loop integration tests cover the bounded path; Package A's train-only, fixture-filtering, snapshot-isolation and seven-tool boundaries continue to pass.
- Real Binance provider verification established the core 2+1 chain on 2026-07-21 for run `150cf5b8-32d6-5543-a1a3-02b91d8f43e7`; later live QA found a post-C extra provider decision, so that run remains useful core-chain evidence but is superseded as strict-path proof by the rerun below.

Next missing core capability: validate the same bounded loop against a second real data source before expanding strategy families or execution features.

### Autonomous Iteration v1 — strict real-provider rerun and second source

Status: **Passed** on 2026-07-21 for strict run `31843e71-a873-5b31-a0a2-2c4b3bbe272b` using real SPY `1D` data (2,147 bars, 2018-01-02 to 2026-07-20), DeepSeek `deepseek-chat`, and mock fallback disabled. The requested Nasdaq Equity source returned an invalid upstream status on two bounded preflight attempts, so the session used an explicitly labelled Yahoo Finance public-chart CSV fallback rather than misrepresenting it as Nasdaq.

Validated:

- The source is pinned as an imported real dataset across Run, report dataset context, snapshot and UI; synthetic fixtures retain their synthetic label, while provider-fetched datasets project as collected rather than fixture/generated.
- After candidate C completed, the Runner bypassed the provider and deterministically executed final compare then finish. The live action sequence had exactly three creates and nine actions total; there was no fourth-create attempt, provider-decision failure, failed finish, or fallback.
- A/B produced exactly one train-only feedback artifact; C had a distinct canonical key, non-empty rationale and the persisted feedback id. The final comparison covered all three candidates and the selected strategy came from its ranking; exactly one sealed-holdout report followed.
- The UI showed real SPY Data Preview, live Experiments, completed Analysis, Report/Markdown preview and history list/reopen at 1440. The copy action was invoked; the controlled browser does not expose clipboard contents, while its Download action confirmed the server filename. At 1024, document scroll width equalled client width.
- Internal feedback remains hidden from snapshot artifacts/events and, after a deterministic report-copy boundary, from Report and Markdown export. Current and historical snapshots and the export all retain the selected-candidate identity.

Phase 1A can close: the bounded 2+1 loop now has strict real-provider proof across two independent market-data sources (Binance provider fetch and the documented SPY CSV fallback). The next core capability is a user-controlled multi-interval dataset and research-range extension, not another iteration loop variant.

### Real Binance + DeepSeek Vertical Validation

Primary user action: start a research run from real market data, follow the Agent to a truthful terminal result, inspect and export the retained strategy evidence, then reopen the same run from history.

Status: **Passed** on 2026-07-21 using a real Binance Spot BTCUSDT `1D` dataset and the configured DeepSeek `deepseek-chat` provider. The launcher now pins the session provider/model and disables mock fallback for both API-created UI Runs and the worker, so validation is not limited to the prepared initial Run. The launcher requests 1,000 bars (999 retained; 2023-10-26 to 2026-07-20), so the coverage-bounded research range is multi-year rather than a one-year sample.

Validated:

- Data Catalog Preview displayed stored Binance OHLCV, candlesticks, volume and true SMA20/SMA50 for BTCUSDT before the run.
- The exact production Quant API path created the Auto Research run, and the live UI showed DeepSeek while its bounded plan and experiments progressed.
- The completed run retained two distinct SMA specifications, persisted candidate metrics, strategy-vs-benchmark series, trades, repeated walk-forward evidence and a sealed-holdout failure without inventing a winner.
- Analysis, Report and server-rendered Markdown export agreed on the selected candidate and its metrics. Copy and server-named `.md` download both succeeded.
- Runs History found and reopened that same retained run.
- When sealed holdout is `fail` or `inconclusive`, the persisted report recommendation now overrides a training-only provider recommendation with `revise_research` or `collect_more_evidence`; a failed holdout can no longer suggest paper evaluation.

This validation gap is now closed by the shared legacy/public-market Continue / Refine flow above. **P1C deeper version-aware Runs and Report navigation is complete**, closing Research Series v0.1 on the existing pages.

Do not rebuild:

- Navigation, page frames, New research, Runs, Data, report tabs, Run Monitor, notifications or audit views.
- Existing data import or Agent execution pipeline.
- Existing candidate summary metrics solely to fit a new chart library.

Hard data rule: strategy performance visualizations must come from an explicit strategy performance contract. Market prices, sampled closes or fabricated offsets are not strategy equity.
