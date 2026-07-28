<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./apps/mac/public/brand/qurio-wordmark-inverse.svg">
    <source media="(prefers-color-scheme: light)" srcset="./apps/mac/public/brand/qurio-wordmark.svg">
    <img alt="Qurio" src="./apps/mac/public/brand/qurio-wordmark.svg" width="260">
  </picture>
</p>

<p align="center"><strong>Research a market idea, compare what survives, and keep the evidence.</strong></p>

<p align="center">
  A quantitative research workspace where plans, experiments, decisions, and evidence stay
  connected.
</p>

<p align="center">
  <a href="#what-is-qurio">What it is</a> ·
  <a href="#a-look-inside">Screens</a> ·
  <a href="#two-runs-worth-reading">Cases</a> ·
  <a href="#try-the-retained-demo">Demo</a> ·
  <a href="#build-qurio">Build</a>
</p>

[![Watch the 90-second Qurio demo](./docs/portfolio/qurio-90-second-preview.png)](./docs/portfolio/qurio-90-second-mainline.webm)

<p align="center"><em>A retained research run, from comparison to the next defensible action. Click to watch the 90-second demo.</em></p>

## What is Qurio?

Qurio is a macOS workspace for doing quantitative research as a sequence you can revisit:
bring in market data, state a bounded objective, approve a plan, compare experiments, inspect
the result, and continue from the retained evidence.

One Research Agent proposes a bounded plan, registered tools keep each action inside the approved
scope, and retained evidence determines the next legal step. One deterministic evaluator
calculates every quantitative metric, keeping each experiment and comparison on one authoritative
calculation path while the Agent adapts the research.

## What you do in Qurio

1. **Keep the dataset.** Import CSV data or use an allowlisted provider at `1h`, `4h`, or `1D`,
   with its source and assumptions attached.
2. **State the question.** Define a bounded objective, constraints, comparison rule, and action
   budget.
3. **Approve the plan.** See what the Agent intends to test before the run begins.
4. **Watch the research adapt.** Follow candidate experiments, observations, typed repairs, and
   the next research step.
5. **Compare before concluding.** Inspect candidates under the same research context and open the
   sealed holdout once.
6. **Continue without starting over.** Reopen history or create a linked research version from the
   evidence already retained.

## A look inside

<table>
  <tr>
    <td width="50%">
      <img src="./docs/assets/pokiequant/v1-final-183209-01-data-1440x960.png" alt="Qurio Data workspace showing a retained BTCUSD dataset">
      <br>
      <sub>Bring a dataset in, with its source and assumptions attached.</sub>
    </td>
    <td width="50%">
      <img src="./docs/assets/pokiequant/v1-final-183209-02-ledger-repair-1440x960.png" alt="Qurio candidate comparison and Decision Ledger">
      <br>
      <sub>Compare candidates with the same research context.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="./docs/assets/pokiequant/v1-final-183209-03-analysis-selection-1440x960.png" alt="Qurio analysis view comparing strategy and benchmark">
      <br>
      <sub>Inspect the result, the benchmark, and why the candidate was selected.</sub>
    </td>
    <td width="50%">
      <img src="./docs/assets/pokiequant/v1-final-183209-06-history-reopen-1440x960.png" alt="Qurio historical run reopened with retained evidence">
      <br>
      <sub>Keep the run, decisions, and evidence together.</sub>
    </td>
  </tr>
</table>

Every chart stays connected to the retained run, candidate, and research context behind it.

## How a research run unfolds

```text
Objective → Approved plan → Experiments → Observation → Adaptation
    ↑                                                     ↓
Continue / Revise ← Sealed holdout ← Decision ← Comparison
```

That loop lives inside the product flow:

```text
Data → Research → Compare → Analyze → Continue / History
```

- **Data** retains immutable CSV or allowlisted provider datasets.
- **Research** keeps the approved contract, action budget, experiments, repairs, and Decision
  Ledger together.
- **Compare** puts candidate identity, deterministic metrics, walk-forward evidence, and
  differences in one view.
- **Analyze** shows equity, drawdown, market context, trades, and the sealed-holdout conclusion.
- **Continue / History** creates a linked research version or reopens retained evidence read-only.

The Agent adapts from training evidence. After the final candidate is selected, Qurio opens one
fresh sealed holdout and retains the resulting decision as the basis for a clear stop or refine
action.

<details>
<summary><strong>Open the Agent architecture</strong></summary>

![Qurio Agent architecture](./docs/portfolio/QURIO_AGENT_ARCHITECTURE.svg)

One Agent is intentional: the observation → adaptation → decision chain stays readable, while
registered tools and action budgets keep the approved scope explicit.

</details>

## Two runs worth reading

### Kraken / BTCUSD: evidence-led adaptation

This retained research run combines live Kraken market data with a DeepSeek decision provider.

| What happened | Retained evidence |
|---|---|
| Data | 548 closed Kraken Spot `BTCUSD · 4h` bars; the open bar was dropped |
| Experiments | SMA 20/100, breakout 20, then an evidence-led SMA 50/200 candidate |
| Typed repair | Candidate C received a contract response; the next model turn adjusted the action and continued |
| Selection | Deterministic minimum-trade evidence retained B after the final training comparison |
| Validation | The fresh sealed holdout decision was retained with the run and carried into the next research step |

[Read the case study](./docs/portfolio/QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md) ·
[Inspect the sanitized evidence](./docs/portfolio/evidence/qurio-v1-kraken-deepseek.json) ·
[See the holdout decision](./docs/assets/pokiequant/v1-final-183209-04-holdout-revise-1440x960.png)

The case shows the Agent/evaluator boundary, a typed repair, and a decision that remains
inspectable from the original experiment through history.

### Wind / CSI300: professional data, same retained path

An authorized Wind CSI300 daily export followed the same Data → Research → Continue / History
path with explicit `XSHG` session semantics, retained source identity, and DeepSeek decisions.

[Read the supplemental case](./docs/portfolio/QURIO_WIND_DEEPSEEK_CASE_STUDY.md) ·
[Inspect the sanitized evidence](./docs/portfolio/evidence/qurio-wind-csi300-deepseek.json)

## Available today

- Retain CSV and allowlisted market datasets at `1h`, `4h`, and `1D`.
- Define a bounded objective and approve the Agent's executable research plan.
- Run comparable candidate experiments with deterministic metrics and recorded decisions.
- Inspect equity, drawdown, benchmark, trades, validation, and the selected strategy together.
- Continue from a retained result or reopen an earlier research version from history.
- Run locally on Apple-silicon macOS with Offline, DeepSeek, Kimi K3, OpenAI, Qwen, or a custom
  OpenAI-compatible provider.

## Try the retained demo

Prerequisites: Python 3.12, Node.js 22, pnpm 10.28.0, and `uv` 0.11.28.

```bash
uv sync --locked --extra test
pnpm install --frozen-lockfile
.venv/bin/python scripts/launch_quant_live_session.py --guided-demo
```

Open the printed Mac UI URL and choose **Open guided demo**. Qurio verifies the retained database
digest, prepares a current-schema presentation copy, and serves that copy read-only. No provider
credential or new model call is required.

The guided-demo database contains no provider credential. Its SHA-256 is documented in
[the evidence README](./docs/portfolio/guided-demo/README.md).

The 90-second video uses a complementary Binance case where a real `deepseek-chat` run completed
the same bounded loop and passed one sealed holdout. The Kraken case focuses on evidence-led
adaptation, typed repair, and retained decision lineage.

## Build Qurio

Package the Apple-silicon macOS 11+ application:

```bash
pnpm package:mac
```

The application embeds its FastAPI API and Research Agent worker, stores optional provider
credentials in Keychain, and supports a no-key deterministic demo. The
[macOS beta release workflow](./docs/MACOS_BETA_RELEASE.md) packages Developer ID signing, Apple
notarization, DMG verification, and release checks when the project credentials are configured.

<details>
<summary><strong>Run the focused verification gates</strong></summary>

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

The full CI also exercises contract, integration, security, evaluation, license, E2E, Cargo, and
macOS-native application boundaries. Live provider credentials are not required.

</details>

## Documentation

- [90-second review guide](./docs/portfolio/QURIO_90_SECOND_DEMO.md)
- [Kraken / BTCUSD case study](./docs/portfolio/QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md)
- [Wind / CSI300 case study](./docs/portfolio/QURIO_WIND_DEEPSEEK_CASE_STUDY.md)
- [macOS beta release](./docs/MACOS_BETA_RELEASE.md)
- [Third-party notices](./THIRD_PARTY_NOTICES.md)
