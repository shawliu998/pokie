# PokieQuant Product and Architecture Roadmap

Status: post-audit roadmap; phases after Phase 0 are not implemented

## 1. Roadmap principles

1. Preserve the Phase 0 contract/state shell while replacing fixture internals incrementally.
2. Keep API-owned transitions, immutable attempts, append-only events, approval records, and artifact hashes in every phase.
3. Treat candidate verdict as separate from system health; negative conclusions remain first-class results.
4. Add one bounded capability per phase with deterministic correctness tests before increasing autonomy.
5. Never enable network, arbitrary code, risk changes, or broker behavior through a UI-only flag.
6. Gate every external code/data source by repository, immutable commit/version, license, provenance, and security review.
7. PokieTicker remains pending repository/commit/license review; Spark remains pending the actual runtime repository and sandbox review.

## 2. Phase overview

| Phase | Outcome | New trust boundary | Explicit non-goal |
| --- | --- | --- | --- |
| 0 | deterministic Agent Workspace Shell | API-backed fixture worker | no real backtest/data/model/execution |
| 1 | small deterministic daily-bar backtester | financial calculation correctness | no arbitrary Python or network |
| 2 | reviewed Spark execution runtime | sandboxed code execution | no unrestricted packages/network |
| 3 | governed market-data adapters | external data/provider terms | no realtime trading signal claims |
| 4 | simulated paper broker and risk engine | order-intent/risk/fill state | no live broker or real orders |
| 5 | evaluation and replay system | eval datasets/behavior metrics | no self-certification of safety/profitability |

## 3. Phase 0 — Agent Workspace Shell

### Outcome

A real React/Tauri workbench runs the complete SPY research workflow from goal to report through deterministic API/worker fixtures. It supports plan approval, optional execution approval, safe activity, candidates, market/report views, cancellation, retry, inspector, and reproducible edge states.

### Required implementation

- independent Quant contracts/domain/API/events/artifacts;
- API-owned transitions and persisted refresh recovery;
- worker lease/fence/idempotency behavior;
- ten named fixture states and clear authenticity labels;
- canonical three-candidate scenario and no-viable-candidate scenario;
- responsive/accessibility/keyboard behavior;
- inherited and additive test/visual/license gates.

### Exit criteria

- main path contains no Glint product-intelligence destinations/semantics;
- every action is backed by a legal API command;
- cancel stops subsequent events and retry creates a new attempt;
- `completed + no viable candidate` is demonstrated and tested;
- no real market/model/backtest/trading capability is claimed;
- docs, screenshots, README, tests, and implementation agree.

## 4. Phase 1 — Deterministic Backtester

### Outcome

Replace fixture backtest results with a small, auditable engine while keeping Phase 0 contracts, states, UI, reports, and fixtures as regression references.

### Scope

- one asset per run;
- daily OHLCV bars from an immutable imported snapshot;
- Long/Cash only;
- next-bar-open execution to prevent same-bar lookahead;
- fixed commission and slippage;
- SMA crossover, RSI threshold, and breakout strategy families;
- buy-and-hold benchmark;
- deterministic trade ledger, equity/drawdown series, and metrics;
- validator for empty data, delay, benchmark, trade count/concentration, parameter/cost sensitivity, and simple in/out-of-sample split.

### Correctness gates

- hand-calculated golden cases for fills, fees, slippage, exposure, turnover, return, drawdown, and Sharpe conventions;
- no-lookahead and timestamp-alignment tests;
- identical input/engine/config produces identical hashes/results;
- dataset, engine, strategy, validator, and assumptions versions pinned to each artifact;
- rejected/inconclusive/invalid candidates do not fail the run;
- fixture and computed results are visibly distinguishable.

### Non-goals

No intraday data, shorting, leverage, corporate-action inference, portfolio optimization, arbitrary user code, package installation, or network access.

## 5. Phase 2 — Spark Runtime

### Entry gate

Obtain the actual Spark execution repository, immutable commit, license/notice obligations, architecture, file-level migration plan, and sandbox security review. The currently audited local scaffold is not eligible.

### Outcome

Implement `QuantExecutionRuntime` with an immutable execution payload and explicit approval. The existing deterministic engine remains the reference implementation and fallback.

### Scope

- immutable payload digest covering dataset/scope/strategy/environment/limits;
- execution approval bound to the exact digest;
- no-network container/Jupyter runtime;
- pinned environment and allowlisted packages only;
- CPU, memory, wall-clock, disk, output, and process limits;
- stdout/stderr redaction and safe error classification;
- content-addressed artifacts and hashes;
- at most two deterministic repair attempts;
- lease/fence, cancellation, recovery, and attempt isolation;
- execution provenance without prompt/source leakage.

### Exit criteria

- no command executes before exact-payload approval;
- cancel and expired fences prevent new writes;
- escape/network/secret/package-install tests fail closed;
- same payload is replayable or explicitly records unavoidable nondeterminism;
- repairs create immutable versions and never silently expand scope/limits.

### Non-goals

No unrestricted shell, arbitrary package installation, host filesystem access, internet access, multi-agent execution, or autonomous approval.

## 6. Phase 3 — Market Data

### Entry gate

Complete separate code and data-license reviews. PokieTicker capabilities are candidates only until its repository, commit, paths, license, modifications, notices, and data rights are approved.

### Outcome

Replace imported demo bars/events with governed provider snapshots behind stable adapters while preserving Phase 0/1 artifact and authenticity contracts.

### Scope

- `MarketDataAdapter` and `MarketEventAdapter` ports;
- symbol search;
- daily OHLCV snapshot import;
- event/news timeline and chart markers;
- immutable data snapshots with source/provider/license/fetch/schema/digest metadata;
- freshness and missing/corporate-action warnings;
- rate limiting, retry, safe provider errors, and caching;
- interval-event explanation and similar-history lookup only after their data/methodology contracts are defined.

### Exit criteria

- fixture/imported/provider data are unambiguously labeled;
- reports pin the exact dataset snapshot, not a mutable symbol query;
- provider terms allow storage, transformation, display, screenshots, and report reproduction as implemented;
- adapter failure is separate from negative research outcome;
- no secrets/provider raw responses leak to events or logs.

### Non-goals

No realtime subscription, tick/order-book data, autonomous web search, or claim that news causally explains performance.

## 7. Phase 4 — Paper Broker

### Outcome

Add a deterministic simulated broker workflow for research follow-up. It remains isolated from live brokerage and real orders.

### Scope

- immutable `OrderIntent` from a reviewed strategy/spec version;
- explicit simulated-deployment approval;
- deterministic pre-trade risk engine;
- simulated fills with declared timing, spread/slippage, and rejection rules;
- paper portfolio, positions, cash, P&L, and event ledger;
- kill/cancel semantics and reconciliation;
- Agent explanation linked to rule/result records, not hidden reasoning.

### Exit criteria

- no broker credential or live endpoint exists in the runtime;
- every simulated order is linked to approved strategy/risk versions;
- risk-limit changes require a new approval and never mutate history;
- fills, positions, and P&L reconcile from the immutable ledger;
- UI always says simulated/paper and never implies executable advice.

### Non-goals

No live trading, real order routing, margin, options, shorting, capital allocation, or autonomous risk override.

## 8. Phase 5 — Evaluation and Replay

### Outcome

Measure system behavior, backtest correctness, policy compliance, and human-review quality across versioned datasets and exact replays.

### Scope

- Agent behavior evaluation cases and rubrics;
- deterministic backtest correctness suites and metamorphic tests;
- prompt/runtime/strategy/validator version registry;
- exact run replay and event/artifact comparison;
- human review dataset with consent/provenance;
- failure taxonomy, regression thresholds, and release gates;
- calibration research for verdict/quality language.

### Exit criteria

- releases pin and report evaluation dataset and target versions;
- a regression blocks release rather than being hidden by aggregate scores;
- model/runtime changes remain distinguishable from data/engine changes;
- replay verifies event order, approvals, inputs, and artifact hashes;
- evaluation claims are scoped and do not imply future profitability.

## 9. Cross-phase invariants

These must remain true after every phase:

- project is durable; retry is a new run attempt;
- scope/plan/data/strategy/validator/runtime/artifact versions are immutable or versioned;
- API owns lifecycle; workers are fenced; UI is a projection;
- events and audits are append-only, secret-free, and replayable;
- unknown events degrade safely;
- negative conclusion is not system failure;
- completed does not mean recommended or profitable;
- human approvals bind exact versions/digests;
- data and result authenticity are visible;
- no closed-source code/assets/copy are imported;
- external code/data migration requires an approved provenance/license ledger entry;
- security and quality gates are additive.

## 10. Release sequencing and decision points

```text
Phase 0 shell/contracts
  ↓ preserve UI/state contracts
Phase 1 deterministic engine
  ↓ require real Spark repo/license/security approval
Phase 2 sandbox runtime
  ↓ require provider/PokieTicker code+data approval
Phase 3 governed market data
  ↓ require simulated risk/order design review
Phase 4 paper broker
  ↓ accumulate consented versioned evaluation evidence
Phase 5 evaluation/replay
```

Phases do not automatically authorize their successors. A missing repository/license, provider term, security boundary, test oracle, or approval policy is a release blocker for that capability, not a reason to simulate it as implemented.

## 11. Near-term next slice

After Phase 0 is fully implemented and verified, the only recommended next slice is:

> Replace deterministic backtest fixtures with a small deterministic daily-bar backtesting engine while preserving all current contracts and UI states.
