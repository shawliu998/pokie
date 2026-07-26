# Qurio — 90-second interview demo

The recorded cut is 90 seconds, but the walkthrough is modular rather than time-locked. Pause on
Experiments, Analysis, Trades or Decision when an interviewer wants a deeper product discussion.

This video uses the complementary Binance holdout-pass case because it gives a compact visual
tour of the complete product loop. For the primary reasoning, repair, and honest-failure case,
read [the retained Kraken/DeepSeek case study](QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md).

## Start

```bash
.venv/bin/python scripts/launch_quant_live_session.py --guided-demo
```

Open the printed Mac UI URL, then choose **Open guided demo** in the sidebar. On first launch,
Qurio verifies the retained source digest and prepares a current-schema presentation copy. The
source evidence remains unchanged. The demo does not call DeepSeek again and the copy is served
read-only.

## The retained proof

- **Data:** 1,000 closed Binance Spot `BTCUSDT · 4h` bars, `2026-02-05 12:00 UTC` to
  `2026-07-22 00:00 UTC`, zero cadence gaps.
- **Provider:** real DeepSeek `deepseek-chat`; Mock fallback disabled.
- **Agent:** 10 of 12 bounded iterations, three canonical-distinct candidates, one train-only
  feedback observation, one evidence-linked adaptation and one final comparison.
- **Decision:** RSI mean reversion was selected on training evidence and then passed the single
  sealed holdout.
- **Boundary:** this proves the product loop and evidence discipline. It is not a profitability or
  production-reliability claim.

## Shot list and narration

| Time | Screen | Say |
|---|---|---|
| 0–10s | Guided demo entry | “Qurio is a desktop quantitative-research workspace powered by one autonomous Research Agent. This is a retained real-data, real-provider run—not a scripted mock.” |
| 10–23s | Data | “The run pins 1,000 closed Binance BTCUSDT four-hour bars, with an explicit UTC range, 24/7 cadence and no gaps.” |
| 23–45s | Experiments, Agent decision | “The Agent can only use registered research tools. After each experiment, the product makes the causal chain legible: what it observed, why it changed course, and the next legal action.” |
| 45–60s | Candidate comparison | “DeepSeek proposed and adapted three distinct candidates. The deterministic evaluator—not the model—computed every metric and ranked the retained evidence.” |
| 60–76s | Analysis, Drawdown then Trades | “Every candidate is inspectable through equity, drawdown, market context and exact retained trades, with one shared candidate identity across views.” |
| 76–90s | Decision | “Only after training selection did Qurio open the sealed holdout. This RSI candidate passed; the conclusion, evidence export and next research version stay linked in structured Research Memory.” |

## Interview follow-up

Open [QURIO_AGENT_ARCHITECTURE.svg](QURIO_AGENT_ARCHITECTURE.svg) to explain the system, then use
[QURIO_TECHNICAL_TRADEOFFS.md](QURIO_TECHNICAL_TRADEOFFS.md) for the engineering discussion.
