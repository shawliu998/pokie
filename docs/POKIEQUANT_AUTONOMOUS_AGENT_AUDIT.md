# PokieQuant Autonomous Agent Audit

## Baseline

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

The generic `packages/agent_runtime` and `services.worker.app.providers.openai_compatible`
extraction reuse code that already existed in this repository (`model_research.py` and
`services.worker.app.quant_agent.provider`). Lumi and any external agent frameworks are treated as
conceptual inspiration only; no unverified external code was copied. Provenance claims are limited
to files and modules that were actually inspected and refactored here.
