<h1 align="center">
  <img src="./apps/mac/public/brand/qurio-wordmark.svg" alt="Qurio" width="176">
</h1>

<p align="center"><strong>Turn an investment idea into comparable evidence—and keep refining what works.</strong></p>

<p align="center">
  Qurio is a quantitative research workspace powered by one autonomous Research Agent.
  Working within an approved plan, it chooses registered actions, learns from retained
  evidence, compares candidates and keeps the research path available for review.
</p>

<p align="center">
  <a href="./docs/portfolio/qurio-90-second-mainline.webm">Watch the 90-second demo</a>
  ·
  <a href="./docs/portfolio/QURIO_AGENT_ARCHITECTURE.svg">See the Agent architecture</a>
  ·
  <a href="./docs/portfolio/QURIO_DEEPSEEK_APPLICATION_BRIEF_ZH.md">阅读中文项目说明</a>
</p>

[![Qurio autonomous research workspace](./docs/portfolio/qurio-90-second-preview.png)](./docs/portfolio/qurio-90-second-mainline.webm)

## What Qurio does

Qurio is built for an independent systematic researcher who has a market question but does
not want to rebuild the same notebook, prompt, backtest and reporting workflow every time.

You select retained market data, describe the objective and review the proposed plan. From
there, the Agent executes the approved research workflow: it chooses from registered tools,
tests candidate strategies, reads the evidence and decides what bounded action to take next.
The result is a comparison you can inspect, a conclusion you can trace and a research history
you can continue later.

```text
Select data → Define the objective → Approve the plan
            → Observe experiments → Compare evidence
            → Review the decision → Continue or revisit
```

## A research session, end to end

### Start from retained market data

Choose a stored dataset, interval and research range. Qurio keeps the selected data attached
to the run so later comparisons and reopened results refer to the same market context.

### Approve the work before it runs

The Agent turns the objective into a concrete research contract: candidate families,
comparison objective, completion criteria and action budget. The researcher can approve it
or request a change before execution.

![Qurio research plan ready for approval](./docs/assets/pokiequant/p1c-02-plan-approval-1440x960.png)

### Let evidence shape the next action

Experiments are not a hidden parameter sweep. After each comparison, the Agent receives the
retained training evidence and chooses the next registered action. The workbench shows the
observation, why the research path changed and what happens next.

### Compare the candidates, then keep the thread

Returns, drawdown, Sharpe, trades, benchmark differences and robustness evidence share one
calculation path. The selected result can be inspected in Analysis, exported, reopened from
History or used as the starting point for a new research version.

## How the Agent works

Qurio separates research decisions from quantitative evaluation: one Research Agent
determines the next research step, while deterministic evaluators produce the metrics and
evidence used for comparison.

1. The Agent proposes a plan within the selected data and research scope.
2. The researcher approves the plan.
3. The Agent takes one registered research action at a time.
4. Deterministic tools return the quantitative evidence for the next decision.
5. Qurio compares the candidates, evaluates the selected strategy and retains the complete
   research lineage.

![Qurio Research Agent architecture](./docs/portfolio/QURIO_AGENT_ARCHITECTURE.svg)

The model decides how to proceed within the approved plan; the evaluators own the numbers.
Each decision and result stays attached to the same research lineage.

## What is working today

| Area | Current capability |
|---|---|
| Market data | Retained CSV and allowlisted provider datasets at `1h`, `4h` and `1D` |
| Research | Plan approval, bounded experiments, evidence-led adaptation and final selection |
| Strategy evidence | Backtests, benchmark comparison, trades, walk-forward checks and sealed-holdout evaluation |
| Research memory | Run history, retry attempts, Continue / Refine versions and cross-run comparison |
| Review | Decision Ledger, Analysis, Strategy Report and JSON / Markdown evidence export |
| Local delivery | Apple-silicon macOS application, guided demo and an embedded local runtime |
| External access | Read-only Python SDK, CLI and four-tool MCP server over retained evidence |

## Built independently

Qurio is an independently designed and built portfolio project. I defined the product scope,
designed the Research Agent and evaluator boundary, planned the delivery sequence, implemented
the desktop and service layers, built the validation path and made the final acceptance decisions.

AI coding tools supported parts of the implementation workflow. The architecture, product
decisions, validation approach and release criteria remained my responsibility.

## Review it in 90 seconds

The fastest route is the [recorded end-to-end demo](./docs/portfolio/qurio-90-second-mainline.webm).
It follows a retained BTCUSDT research run through the approved plan, Agent decisions,
candidate comparison and final review.

To inspect the same workflow locally:

```bash
uv sync --locked --extra test
pnpm install --frozen-lockfile
.venv/bin/python scripts/launch_quant_live_session.py --guided-demo
```

Open the printed Mac UI URL and choose **Open guided demo**. Qurio verifies the retained
database, prepares a presentation copy and serves it read-only. No Provider credential or new
model call is required.

For a structured walkthrough, use the
[90-second review guide](./docs/portfolio/QURIO_90_SECOND_DEMO.md).

## Build and verify

Prerequisites: Python 3.12, Node.js 22, pnpm 10.28.0 and `uv` 0.11.28.

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
.venv/bin/pytest tests/runtime/test_migration_history.py
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Build the local Apple-silicon macOS application with:

```bash
pnpm package:mac
```

The packaged application embeds its FastAPI service and Research Agent worker, stores optional
Provider credentials in Keychain and includes a no-key guided path.

## Project notes

- [Product contract](./apps/mac/PRODUCT.md)
- [Interface contract](./apps/mac/DESIGN.md)
- [Capability inventory](./docs/POKIEQUANT_CAPABILITY_INVENTORY.md)
- [Technical tradeoffs](./docs/portfolio/QURIO_TECHNICAL_TRADEOFFS.md)
- [DeepSeek application and interview brief（中文）](./docs/portfolio/QURIO_DEEPSEEK_APPLICATION_BRIEF_ZH.md)
- [AGI application evidence index（中文）](./docs/portfolio/evidence/AGI_APPLICATION_EVIDENCE.md)
- [Portfolio release checklist](./docs/portfolio/QURIO_PORTFOLIO_RELEASE_CHECKLIST.md)
- [Third-party notices](./THIRD_PARTY_NOTICES.md)
