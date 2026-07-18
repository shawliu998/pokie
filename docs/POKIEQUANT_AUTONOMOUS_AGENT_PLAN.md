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
11. Persist user-declared CSV source/provider, reference, adjustment policy, submitted-text digest,
    parser version, and normalized dataset digest without changing content-addressed dataset identity.
12. Evaluate each compared candidate over three deterministic expanding windows inside the training
    partition, keeping the final 20% holdout sealed until selection is frozen.
13. Verify the complete imported-data lifecycle with the real DeepSeek provider, mock fallback
    disabled, and persisted provider/model/fallback evidence.
14. Generate a frozen, digest-verified data-quality report for every imported dataset. Retain
    rejected imports for inspection while preventing blocking calendar/timezone or long-gap findings
    from entering autonomous execution.
15. Classify every expanding fold from only the preceding training history, persist deterministic
    trend/volatility regime evidence, and report insufficient regime diversity instead of implying
    coverage that the data does not contain.
16. Verify a blocked dirty import and a completed quality-passed import in one real DeepSeek run,
    with Mock fallback disabled and quality/regime evidence retained in the Mac report.
17. Add one fixed-host public Binance Spot daily-kline adapter. Hash the raw provider response,
    normalize only closed UTC candles into the existing immutable dataset contract, apply 24×7
    calendar quality rules, retain provider attestation in API/Mac projections, and verify the full
    Binance-to-DeepSeek Run without exposing network access to the Agent tool registry.

## Bounded scope

Only SMA crossover, RSI mean reversion and trailing breakout templates are executable. Tools never
access the network or execute user/model code. Metrics always come from the local kernel over the
pinned dataset. Missing model credentials select the product-supported Mock provider.

Manual imports accept daily OHLCV as CSV text through the authenticated Quant API and remain
user-attested. The first real-provider adapter retrieves 252–1,000 public Binance Spot daily klines
from one fixed host, drops an unfinished current candle, and retains distinct raw-response and
normalized-dataset digests. Imports remain inspectable at any size, while autonomous runs require
at least 252 ordered daily bars.

## Reuse note

Lumi's pinned `tools.py`, `models.py`, and `machine.py` were reviewed for their narrow registry,
router, and step-coordination interfaces. PokieQuant independently generalized those patterns with
Pydantic validation and its existing Store/lease lifecycle; it did not import Lumi phases, state,
SQLite EventStore, learning guardrails, or artifacts. The OpenAI-compatible transport was extracted
from the existing in-repository `model_research.py` implementation rather than copied from an
external runtime.
