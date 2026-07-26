# Qurio — technical tradeoffs

Qurio optimizes for a research result that can be understood and re-opened, not for the widest
possible Agent surface. The product is one autonomous Research Agent operating inside a bounded
quantitative-research contract.

| Decision | Why it fits now | Cost accepted | Revisit when |
|---|---|---|---|
| **One Agent, specialized registered tools** | One decision-maker makes the evidence → adaptation chain legible and keeps the product focused on research. | Less parallel exploration than a multi-agent swarm. | Independent specialist loops demonstrate better retained outcomes at the same budget. |
| **Approved plan and hard action budget** | Autonomy remains meaningful while scope, cost and stopping conditions are inspectable. | The user approves once before execution; some novel paths stop early. | A reliable policy can infer limits without surprising cost or scope expansion. |
| **Deterministic evaluator owns metrics** | The model chooses research actions; one quantitative kernel computes returns, drawdown, trades and comparisons. | New strategy families require explicit implementation and tests. | A sandboxed extension contract can preserve the same authoritative metric path. |
| **Registered strategy templates, no arbitrary Python** | Canonical identity, comparable evidence and repeatable execution are available today. | Less expressive than a notebook or hosted IDE. | A constrained SDK can prove isolation, identity and metric equivalence without duplicating the kernel. |
| **Structured Research Memory, not chat history** | Runs, versions, attempts, candidate identities and retained evidence are queryable product state. | Free-form rationale is deliberately secondary. | Users need cross-series semantic retrieval beyond existing structured lineage. |
| **One sealed holdout after training selection** | The Agent cannot repeatedly optimize against test evidence; pass and fail conclusions remain honest. | Less iteration after the final validation result. | Nested walk-forward evaluation becomes a demonstrated user need. |
| **Local desktop runtime + user Provider** | Interviewers can install the product, keep credentials in Keychain and select Offline, DeepSeek or one OpenAI-compatible endpoint. | Packaging and local-service lifecycle are more complex than a hosted app. | Collaboration, scheduled compute or centrally managed data becomes primary. |
| **Read-only retained Guided Demo** | A reviewer reaches a complete real proof in one click without spending Provider tokens or mutating evidence. | It is a presentation path, not a new research workflow. | The normal first-run experience can produce a completed real research result inside the interview time budget. |

## Deliberate boundaries

No Broker, position ledger, live trading, arbitrary Python, Agent marketplace or broad Skills/MCP
surface is claimed. Those features would widen operational risk without making today’s core loop—
data → bounded research → comparative evidence → conclusion—more credible.

## What the golden proof establishes

The retained `BTCUSDT · 4h` run used 1,000 real Binance closed bars and real DeepSeek
`deepseek-chat`, with Mock fallback disabled. It completed three distinct candidate experiments,
adapted once from train-only evidence and passed one sealed holdout. It establishes full-stack
research-loop integrity; it does not establish future alpha.
