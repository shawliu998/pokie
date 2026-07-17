# PokieQuant Autonomous Agent Audit

## Baseline

The Phase 1A branch `codex/reuse-first-autonomous-agent` was created from
`990011bd944f4e8f3fbcc13fa77c925b83c516c2`. On 2026-07-17, the requested upstream `main`
references were verified with `git ls-remote`:

| Repository | Verified `main` SHA | Use in this implementation |
| --- | --- | --- |
| `shawliu998/lumi` | `cd1ebcb17c53268725495e874b3f5980514781cc` | `tools.py`, `models.py`, and `machine.py` were read at this revision; their narrow registry/router interfaces and step coordination were generalized without importing Lumi state, phases, store, or source verbatim |
| `shawliu998/Glint` | `161c6075a9e73dbb344f15d58ef41b7c9834380e` | Provenance reference; the shared transport was extracted from the existing Pokie/Glint-derived local module |
| `shawliu998/spark-agent` | `f21158df7631e23f5be4481ea20e63c11e8389b1` | Boundary review only; no integration or source import |

The Phase 0 Quant path is a durable deterministic fixture, not an autonomous loop. A run is
created by `POST /v1/quant/runs`; `QuantStore.create_run()` immediately publishes a fixed plan.
Plan approval changes the run to `running_experiments`. The `quant-fixture` worker then claims the
run through the existing workspace lease/fencing row and executes the entire
`build_quant_script()` sequence in one atomic write.

## Existing boundaries retained

- `QuantRepositoryState` owns workspace-scoped JSON persistence, optimistic versions, one worker
  lease, heartbeat and fencing version.
- Cancel invalidates the worker lease. Retry creates a new run attempt and retains old evidence.
- Events use durable sequence numbers and are exposed through the existing SSE cursor/reset API.
- Experiments and artifact metadata are part of the same durable aggregate.
- The Mac workspace renders a server-owned snapshot and presentation model; it never mutates run
  state directly.
- `packages/domain/quant_backtest.py` is a pure deterministic daily-bar kernel supporting SMA,
  RSI, breakout and buy-and-hold. The pinned 1,564-bar synthetic SPY dataset is in
  `packages/contracts/quant/fixture_data.py`.

## Fixed fixture path

`packages/contracts/quant/runtime.py` owns fixed plan steps and fixed Candidate A/B/C events.
`services/worker/app/pipelines/quant_fixture.py` claims an approved run and calls the store once;
`QuantStore._finish_run()` persists the complete script. Fixture metrics remain explicitly marked
as fixtures and do not invoke the local backtest kernel.

## Model path

`model_research.py` retains the bounded legacy content/evidence pipeline and its public DeepSeek
adapter, while the actual `/chat/completions` HTTP implementation now lives in the shared
`services/worker/app/providers/openai_compatible.py` transport. Model Research and Quant keep
separate prompts and response contracts while sharing only the fail-closed network boundary.

## Gaps addressed by Phase 1A

The normal Quant path needs strict one-action decisions, a database-rebuilt context, a fixed tool
registry, dynamic candidate state, real local-kernel results, incremental persistence, goal-aware
mock behavior, OpenAI-compatible DeepSeek decisions, and UI projections for decisions, tool calls,
budgets and provider identity. The fixture runner remains available for screenshots and regression.

## Reuse and provenance

At the pinned Lumi revision, `runtime/hermes_runtime/tools.py`, `models.py`, and `machine.py` were
inspected. PokieQuant generalized only the small closed-registry, model-routing, and one-step
coordination ideas. It replaced Lumi's handwritten schema subset with Pydantic contracts and did
not import `AgentState`, `Phase`, `PHASE_TO_TOOL`, guardrails, SQLite `EventStore`, learning
artifacts, or the multi-phase loop. No Lumi source was copied verbatim; its repository exposes no
root license file at the pinned revision, so the ledger intentionally limits reuse to independently
implemented interface patterns.

The shared `services.worker.app.providers.openai_compatible` transport was extracted from code
already present in this repository (`model_research.py`). Model Research and Quant now share this
transport while retaining separate prompts and response contracts. Provenance claims are limited
to the fixed revisions and files actually inspected.
