# PokieQuant Autonomous Agent — Phase 1A Implementation Report

This report describes Phase 1A implementation history through `76c6459` on branch
`codex/reuse-first-autonomous-agent`, together with the report-time shared-model and provenance
additions. The result is a runnable integration candidate, not a production quantitative-research
or trading system.

## Audit

The implementation started from PokieQuant Phase 0 at `990011b`. Phase 0 already owned the product
and governance spine: authenticated workspace-scoped projects and Runs, plan approval, durable
events/artifacts/experiments, optimistic concurrency, worker claims, leases, fencing, cancellation,
retry, SSE cursors, the React/Tauri workspace, and the pure daily-bar backtest kernel. Its normal
fixture worker called `build_quant_script()` and wrote a predetermined Candidate A/B/C sequence in
one operation.

Phase 1A retains that fixture path for deterministic regression and reviewed screenshots, but the
normal `quant-agent` path does not import or call `build_quant_script()`. It claims the same durable
Run, rebuilds context from the same store, obtains one closed decision, executes one registered tool,
persists the result, and releases the claim. A later worker poll repeats the process. React remains a
projection of API-owned state.

The source pins recorded for the reuse review on 2026-07-17 were:

| Repository | Reviewed ref | Reuse boundary |
| --- | --- | --- |
| Pokie | Phase 0 `990011bd944f4e8f3fbcc13fa77c925b83c516c2` | System of record and source of the existing kernel, worker/store boundaries, model-research transport, API, and Mac shell. |
| Lumi | `cd1ebcb17c53268725495e874b3f5980514781cc` (`refs/heads/main`) | Conceptual reference for typed tool registry/runtime coordination only. No Lumi phase machine, state, SQLite store, guardrails, or source code was copied. |
| Glint | `161c6075a9e73dbb344f15d58ef41b7c9834380e` (`refs/heads/main`) | Conceptual provenance reference. The shared HTTP transport was extracted from the Glint-derived implementation already present in Pokie, not copied from this external ref. |
| spark-agent | `f21158df7631e23f5be4481ea20e63c11e8389b1` (`refs/heads/main`) | Not integrated. No arbitrary Python, Jupyter, sandbox, or Spark runtime entered Phase 1A. |

No second event store, queue, scheduler, state machine, retry system, backtest framework, or Agent
framework was added. The dependency and notice-drift gate confirms that this slice added no
unreviewed dependency or third-party notice change.

## Reused Code

| Source repository / commit | Source file | Destination | Reused classes/functions or boundary | Modification |
| --- | --- | --- | --- | --- |
| Pokie `990011b` | `services/api/app/modules/quant/store.py`, `services/worker/app/pipelines/quant_fixture.py`, `services/worker/app/main.py` | Same store and worker entry point; `services/worker/app/pipelines/quant_agent.py` | `QuantStore`, durable aggregate, claim/heartbeat/lease/fencing, cancellation, retry, Event, Artifact, Experiment, worker polling | Added Agent records and `claim_agent_run()` while preserving the existing storage and ownership boundaries; one claim executes one decision/tool step. |
| Pokie `990011b` | `packages/domain/quant_backtest.py` | `services/api/app/modules/quant/store.py` Agent backtest methods | `DailyBar`, `StrategySpec`, `ExecutionConfig`, `run_backtest()`, `backtest_buy_and_hold()` | Added a narrow adapter from validated candidate templates and the Run-pinned dataset; metrics remain program-computed. |
| Pokie `990011b` | `services/worker/app/pipelines/model_research.py` | `services/worker/app/providers/openai_compatible.py` and the adapted original pipeline | HTTPS configuration, bounded `/chat/completions` request, timeout/error handling, response-byte limit | Generalized into `OpenAICompatibleConfig` and `HttpxOpenAICompatibleTransport`; legacy Model Research and Quant decisions share the single transport. Secrets and raw provider bodies are excluded from public errors. |
| Pokie `990011b` | `services/api/app/modules/quant/snapshot.py`, `apps/mac/src/features/quant/`, `apps/mac/src/quant-api.ts` | Same API projection and Mac workspace plus `QuantDataPage.tsx` | Server-owned workspace snapshot, command adapter, Plan/Activity/Market/Report/Inspector surfaces | Added dynamic Agent events, budget/provider/status, computed candidates, imported-dataset provenance, CSV import/list/select, and Run dataset binding without making React state-authoritative. |
| Lumi `cd1ebcb…` | `runtime/hermes_runtime/tools.py`, `models.py`, `machine.py` | `packages/agent_runtime/registry.py`, `packages/agent_runtime/models.py` | Conceptual shape of tool specs/registry, stateless model request/response/router, and one-step coordination | Independently implemented, Pydantic-validated closed tools and small dataclass/protocol model primitives. They have no Lumi phase mapping, persistence, guardrails, or EventStore. This is interface-pattern reuse, not a source copy. |
| Glint `161c607…` | `services/worker/app/pipelines/model_research.py` reference path | No direct external-code destination | OpenAI-compatible transport architecture | External ref was pinned for review only; the actual extraction source was the inherited Pokie file described above. |
| spark-agent `f21158d…` | Spark runtime/sandbox surface | None | None | Deliberately deferred. |

The generic package now includes `ModelTier`, `ModelRequest`, `ModelResponse`, `ModelProvider`, and a
stateless threshold-based `ModelRouter`. The current Quant decision path intentionally continues to
use its narrower `QuantAgentProvider` protocol and one configured endpoint; the generic router does
not own provider configuration, retry, persistence, or Run state.

## Implemented

### Shared runtime and provider

- Added a generic, deterministic `ToolRegistry` with versioned manifests, Pydantic input/output
  schemas, and duplicate/unknown/invalid tool rejection.
- Added provider-independent `ModelRequest`/`ModelResponse` records, three model tiers, a provider
  protocol, and a stateless `ModelRouter` with tested boundary and deterministic-light routing.
- Extracted the single OpenAI-compatible HTTP transport and kept the inherited Model Research path
  working through it.
- Added strict plan and single-action decision parsing for DeepSeek-compatible endpoints. Invalid
  JSON or schema output fails closed. Without a key, the supported path is the deterministic Mock
  provider; repeated provider failures either fall back to Mock or fail the Run according to
  configuration.

### Quant Agent

- Added contracts for plans, budgets, database-rebuilt context, candidates, decisions, tool
  arguments, and observations.
- Registered exactly seven tools: `inspect_research_context`, `list_strategy_templates`,
  `create_candidate`, `run_backtest`, `revise_candidate`, `compare_candidates`, and
  `finish_research`.
- Added goal-aware Mock plans and decisions. Drawdown, trading-opportunity, mean-reversion, and trend
  goals select different bounded candidate families/parameters.
- Added dynamic candidate creation, revision lineage, local SMA/RSI/breakout backtests, buy-and-hold
  comparison differences, final reports, and nullable selection for a no-suitable-candidate finish.
  The model chooses actions and parameters; it never supplies computed metrics.
- Added per-Run iteration, experiment, and repair budgets plus provider/model/status, last action,
  observation, and final conclusion. Every step persists decision, tool lifecycle, observation,
  artifact, and experiment changes before the next poll.
- Added `quant-agent` worker integration over the existing claim, heartbeat, lease, fencing,
  cancellation, and retry boundaries. Auto mode begins after plan creation; Plan mode still requires
  approval. Rebuilding `QuantStore` between polls recovers from durable state and avoids an
  in-memory conversation/checkpointer.

### Imported OHLCV adapter and Mac workspace

- Added strict daily CSV parsing for `date,open,high,low,close` with optional `volume`, ISO dates,
  positive finite prices, ordered unique bars, header normalization, and canonical digest identity.
- Added workspace-scoped import/list APIs and immutable content-addressed dataset versions. A Run
  pins both dataset ID and digest; changing a CSV produces a new version without mutating an
  existing Run. Cross-workspace/unknown dataset binding fails closed.
- Added immutable record-level source metadata: submitted filename/text digest, declared provider
  and reference, price-adjustment policy, parser version, and normalized market-content digest.
  Source labels do not alter the canonical OHLCV identity; the first import of identical normalized
  content remains the immutable provenance record for that version.
- Imported datasets remain inspectable at any length, while Auto Research requires at least 252
  daily bars.
- Added the Mac Data workspace to upload (10 MB client preflight), list, inspect, select, and bind a
  dataset to a new Auto Research command. The UI labels synthetic versus imported provenance and
  displays Agent decisions, tool calls, provider, budgets, dynamic candidates, kernel metrics, and
  the final report.
- Added `chronological-80-20-v1`: Agent tools receive only the first 80% training partition for
  candidate creation, revision, backtesting, and comparison. After the Agent selects a candidate,
  the Store evaluates it over the sealed 20% holdout partition and freezes both partitions into the
  final report. Historical bars may warm indicators, but cannot create pre-holdout positions or
  measured trades.
- Added `expanding-3fold-20pct-v1` inside the training partition. Each fixed candidate is measured
  with fresh cash over three expanding-history windows; later training bars and all sealed holdout
  bars are unavailable to the earlier fold. The comparison artifact and Mac Generalization view
  retain per-fold and aggregate evidence.

## Autonomous Demonstrations

The following are reproduced Mock-provider Runs from the current code over the canonical pinned
synthetic SPY dataset (`1,564` daily bars, 2018-01-02 through 2023-12-29, digest
`sha256:b675da3aa6fac3c199ae8d8ab51968aff32e660d5b487a35e4da9e7e74edf919`). The local kernel computed
all metrics. These are deterministic implementation evidence, not real-market findings or
investment advice. The chronological split contains 1,251 training bars through 2022-10-18 and 313
sealed holdout bars beginning 2022-10-19. Agent decisions never receive holdout metrics.

### Goal A — reduce maximum drawdown

**Goal:** `Reduce maximum drawdown.`

**Plan:** inspect context; review templates; create and backtest bounded candidates; compare with
buy and hold; finish with an evidence-backed conclusion. Candidate families were SMA crossover and
breakout, with at most three experiments and two repairs.

**Persisted tool sequence (10 polls / 10 iterations):**

```text
inspect_research_context
→ list_strategy_templates
→ create_candidate → run_backtest
→ create_candidate → run_backtest
→ create_candidate → run_backtest
→ compare_candidates
→ finish_research
```

| Candidate | Parameters | Total return | Max drawdown | Sharpe | Trades | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| SMA 50/200 | `fast_window=50`, `slow_window=200` | 107.9760% | -11.1204% | 4.6766 | 2 | viable |
| SMA 20/100 | `fast_window=20`, `slow_window=100` | 142.7217% | -8.6852% | 5.7709 | 5 | viable |
| 200-day breakout | `lookback_window=200` | 86.5574% | -15.5030% | 3.8912 | 2 | viable |

**Persisted conclusion:** “Completed bounded candidates were compared with the benchmark. SMA
20/100 best reduced drawdown in the tested set.” The selected candidate was SMA 20/100. Only after
selection, its holdout evaluation returned `30.9220%`, maximum drawdown `-8.7998%`, Sharpe
`5.8239`, and two closed trades versus holdout buy-and-hold drawdown `-9.6269%`; the deterministic
generalization status was `pass`.

### Goal B — more trading opportunities without excessive drawdown

**Goal:** `Find more trading opportunities without excessive drawdown.`

**Plan:** the same governed research stages, but candidate families changed to RSI mean reversion,
fast SMA, and short breakout. The decision path also used the repair budget.

**Persisted tool sequence (12 polls / 12 iterations):**

```text
inspect_research_context
→ list_strategy_templates
→ create_candidate → run_backtest
→ create_candidate → run_backtest
→ create_candidate → run_backtest
→ revise_candidate → run_backtest
→ compare_candidates
→ finish_research
```

| Candidate | Parameters | Total return | Max drawdown | Sharpe | Trades | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| RSI 30/55 | `period=14`, `entry=30`, `exit=55` | -45.9480% | -47.2898% | -5.9909 | 7 | not viable; revised |
| SMA 10/50 | `fast_window=10`, `slow_window=50` | 236.0881% | -7.1666% | 7.9976 | 7 | viable |
| 20-day breakout | `lookback_window=20` | 347.2798% | -2.9481% | 10.4202 | 7 | viable |
| RSI 30/55 revision 1 | `period=14`, `entry=25`, `exit=55` | -45.3436% | -46.7004% | -5.9184 | 7 | not viable |

**Persisted conclusion:** “The bounded decision budget is exhausted. 20-day breakout best reduced
drawdown in the tested set.” The selected candidate was 20-day breakout. Its post-selection holdout
evaluation returned `54.7101%`, maximum drawdown `-2.4387%`, Sharpe `11.9486`, and two closed trades;
the deterministic status was `pass`. The Run still finished safely at its 12-iteration limit.

The candidate sets and sequences differ: Goal B introduces RSI and fast trend parameters and adds
`revise_candidate`; Goal A uses slower trend/drawdown controls and no revision. This is the key
evidence that the normal path is goal-aware rather than fixed Candidate A/B/C playback.

## Verification

The current additive gate was executed from the repository root:

```bash
./scripts/verify_pokiequant_shell.sh
```

Result: **all functional layers passed in one full-gate invocation**.

| Gate layer | Actual result |
| --- | --- |
| Quant contracts, daily-bar/CSV/quality contracts, API, dataset lifecycle, fixture runtime, kernel, research evaluation, OpenAPI drift | 87 Python tests passed |
| Shared registry/model primitives, autonomous Agent lifecycle, goal differentiation, revision lineage, cancellation, provider failure/fallback, comparison differences, transport, and inherited Model Research regression | 56 Python tests passed |
| Mac API/presentation/component tests | 22 Vitest tests across 3 files passed |
| Mac lint | ESLint passed with zero warnings |
| Mac typecheck | TypeScript compiler passed |
| Mac production build | Vite built 55 modules successfully |
| Completed-state browser E2E | 1 Playwright test passed; 2 conditionally skipped |
| API-owned ready-command browser E2E | 2 Playwright tests passed; 1 screenshot-only test skipped |
| Secret-gated DeepSeek verification | Rejected a retained blocked-gap dataset, then completed a quality-passed imported Run with regime-labelled training folds, 336/84 train/holdout split, no provider failure, no Mock fallback, and `pass` status |
| Reviewed workbench assets | Six required 1440×960 PNGs validated |
| Dependency-license policy | 5 tests passed |
| Truth/capability assertions, no active Glint product copy, dependency/notice drift, whitespace | All passed |

The Python runs emitted only the known Starlette `TestClient`/`httpx` deprecation warning. The gate
does not use secrets and intentionally does not make a live model or market-data network call; the
DeepSeek-compatible boundary is covered there with mocked transport and failure-path tests. The
inherited full Phase 1/2/3 and Tauri gates remain available but are not claimed as executed by this
report.

An additional secret-gated, complete DeepSeek Run was executed outside the gate on 2026-07-18 with
`scripts/verify_quant_deepseek_run.py`. The ignored local environment supplied the credential; it was
not printed or placed on the command line. The Phase 1B verification first retained a deliberately
gapped import with quality status `blocked` and proved that Run creation returned HTTP `409`. Provider
`deepseek`, model `deepseek-v4-flash`, then completed the quality-passed 420-bar Run in eight Agent
iterations with three created candidates, no provider failure, and no Mock fallback. The provider
received compact dataset/source/quality metadata, training benchmark, candidate metrics, budgets and
safe event summaries; it did not receive CSV/OHLCV rows or holdout metrics.

The accepted dataset retained quality report digest
`sha256:91a4bf3eaa1f0ab7cd870441a656b1a3b4837828dadb72ce8addef126b305d6e`.
The model selected a revised SMA 10/30 candidate. Its training metrics were `26.4031%` total return,
`-1.7851%` maximum drawdown and Sharpe `7.2014`. The three training-only expanding windows produced
three positive-return folds and two lower-drawdown folds. All three were classified from preceding
history as `uptrend_normal_volatility`, so the report truthfully retained
`insufficient_regime_diversity`. Only after selection, the sealed 84-bar
holdout produced `6.0533%` total return and `-1.3777%` maximum drawdown versus buy-and-hold
`5.3912%` and `-3.7909%`; the deterministic generalization status was `pass`. This demonstrates the
complete transport/decision/tool/persistence/report path, not strategy quality or investment merit.

## Known Gaps

- Imported CSV provenance remains user-supplied. Deterministic quality checks now detect declared
  calendar/timezone mismatches, weekday gaps, weekend sessions, price jumps and adjustment-policy
  limitations, but there is no live provider attestation, exchange-holiday reference feed,
  corporate-action reference feed, or news/web research.
- The demonstration metrics above use the synthetic pinned fixture. Even an imported real OHLCV
  Run would remain a local deterministic backtest, not independently verified market evidence.
- There is no arbitrary Python, shell, Jupyter, Spark runtime, uploaded-code execution, package
  installation, or unrestricted parameter search.
- There is no paper trading, live trading, broker credential, order routing, portfolio execution,
  or risk-management service. A report's `paper_evaluation` next-step label triggers no trading
  capability.
- There are three regime-labelled expanding windows inside training plus one sealed chronological
  20% holdout, but no nested cross-validation, guaranteed regime diversity, significance testing,
  survivorship assurance, robust optimization, or claim of profitability. A `pass` is an
  implementation verdict, not strategy certification.
- The optional decision provider is one DeepSeek/OpenAI-compatible endpoint plus Mock fallback. A
  generic stateless tier router exists, but no multi-provider selection/cost policy is wired into
  Quant execution.
- The workspace-scoped JSON aggregate is durable for this integration slice but is not a normalized
  production Quant schema. Multi-worker throughput, long-running heartbeat cadence, operational
  SLOs, migrations at scale, and production observability remain unvalidated.

## Next Slice

The imported-data slice now includes declared source metadata, immutable source/dataset/quality
digests, blocking correctness checks, regime-labelled training windows, a sealed final holdout, Mac
evidence, dirty-data rejection, and a complete DeepSeek Run. The next bounded slice should add
**independent source attestation**: one real historical market-data adapter, provider export IDs and
timestamps, an exchange-holiday reference calendar, and split/dividend reference events. It should
preserve the seven-tool loop, local kernel, Store/lease/fencing boundaries, compact model context,
and no-trading constraint.
