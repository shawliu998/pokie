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
10. Split each pinned dataset chronologically into 80% training and 20% sealed holdout bars. Expose
    only training metrics to Agent decisions, then compute the selected candidate's holdout result
    while freezing the final report.

## Bounded scope

Only SMA crossover, RSI mean reversion and trailing breakout templates are executable. Tools never
access the network or execute user/model code. Metrics always come from the local kernel over the
pinned dataset. Missing model credentials select the product-supported Mock provider.

The first external-data adapter accepts daily OHLCV as CSV text through the authenticated Quant API.
It performs no market-network retrieval and does not claim the imported rows are provider-verified.
Imports remain inspectable at any size, while autonomous runs require at least 252 ordered daily bars.

## Reuse note

Lumi's pinned `tools.py`, `models.py`, and `machine.py` were reviewed for their narrow registry,
router, and step-coordination interfaces. PokieQuant independently generalized those patterns with
Pydantic validation and its existing Store/lease lifecycle; it did not import Lumi phases, state,
SQLite EventStore, learning guardrails, or artifacts. The OpenAI-compatible transport was extracted
from the existing in-repository `model_research.py` implementation rather than copied from an
external runtime.
