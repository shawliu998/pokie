# PokieQuant Autonomous Agent Plan

## Architecture

The Phase 1A execution path is:

```text
approved/auto Quant run
  -> fenced worker claim
  -> rebuild compact context from durable state
  -> provider returns one strict QuantAgentDecision
  -> persist user-visible decision
  -> execute one registered deterministic tool
  -> persist observation, experiment/artifact/event changes and budget
  -> release claim
```

The next worker poll rebuilds context and selects the next action. No in-memory conversation is
required for recovery.

## Delivery slices

1. Add closed Agent decision, context, plan, tool-argument and observation contracts.
2. Add a deterministic goal-aware Mock provider and an OpenAI-compatible DeepSeek provider.
3. Extend the existing durable Quant records with agent budget, provider and dynamic candidate data.
4. Implement a seven-tool registry over the existing pure daily-bar kernel.
5. Add a one-decision-per-claim runner and `quant-agent` worker kind while retaining the existing
   lease, heartbeat, fencing, cancel, retry and fixture paths.
6. Make Auto mode accept its generated plan immediately; keep Plan mode behind explicit approval.
7. Extend API and Mac presentation contracts with budgets, decisions and tool calls.
8. Verify contracts, goal differentiation, one-step execution, recovery, cancellation, API behavior,
   lint, type checking and UI build.
9. Add strict local CSV OHLCV normalization, immutable workspace dataset versions, and pin each Run
   to a dataset ID and canonical digest before its first Agent decision.

## Bounded scope

Only SMA crossover, RSI mean reversion and trailing breakout templates are executable. Tools never
access the network or execute user/model code. Metrics always come from the local kernel over the
pinned dataset. Missing model credentials select the product-supported Mock provider.

The first external-data adapter accepts daily OHLCV as CSV text through the authenticated Quant API.
It performs no market-network retrieval and does not claim the imported rows are provider-verified.
Imports remain inspectable at any size, while autonomous runs require at least 252 ordered daily bars.

## Reuse note

Lumi and other external agent runtimes are conceptual reference points only. Code provenance is
limited to modules actually present in this repository. Shared components were extracted from the
existing `model_research.py` and Quant agent provider implementations rather than imported from
outside sources.
