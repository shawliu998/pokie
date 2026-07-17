# PokieQuant Phase 0 Information Architecture

Status: implementation contract

## 1. Product map

PokieQuant replaces the active Glint product-intelligence navigation with a Quant research hierarchy while retaining the underlying workbench infrastructure.

```text
New Research
Projects
  Project
    Goal and approved scope
    Runs
      Run attempt
        Plan
        Activity
        Market
        Strategy Report
        Artifacts
        Inspector
Runs
Data
Settings
```

`Inbox`, `Signals`, `Decisions`, `Monitoring`, `Product Decision Brief`, and `PRD Research Input` are not first-level PokieQuant destinations and do not appear in the main demonstration path. Their retained Glint code is historical/upstream implementation, not a financial-domain mapping.

## 2. Global shell

### Sidebar

Nominal width: 228px; resizable/collapsible using the existing `react-resizable-panels` approach.

```text
PokieQuant
[ New Research ]
Search                         ⌘K

Projects
Runs
Data
Settings

Recent projects
SPY · Trend Research
NVDA · News Reaction
BTC · Breakout Study

Data Mode · Demo Fixture
Runtime · Deterministic
Model · Not connected
Version
```

Each recent project row shows symbol, concise title, derived project/run status, last run time, and a visible needs-action marker when applicable.

### Global toolbar

Nominal height: 48–52px.

- left: project, symbol, market, interval, and authenticity;
- center: Ask / Plan / Auto Research segmented control;
- right: configured limits, data status, Inspector, context-valid Cancel/Retry, and More.

Example:

```text
SPY · US Equity · 1D · Synthetic Demo Fixture
Plan | Auto Research          3 experiments · 2 repairs · 5 min
```

No token, cost, or percentage-progress placeholder is shown.

## 3. Primary desktop workspace

At widths greater than 1320px:

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Global toolbar                                                       │
├──────────────┬────────────┬──────────────────┬───────────────────────┤
│ Projects /   │ Plan rail  │ Activity         │ Market workspace      │
│ Runs         │            │ Action center    │ Candlestick + volume  │
│              │            │ Artifacts        ├───────────────────────┤
│              │            │                  │ Strategy report       │
├──────────────┴────────────┴──────────────────┴───────────────────────┤
│ Goal composer / legal run controls                                  │
└──────────────────────────────────────────────────────────────────────┘
                                            ┌─────────────────────────┐
                                            │ Context inspector drawer│
                                            └─────────────────────────┘
```

Nominal dimensions:

| Region | Default | Constraint |
| --- | ---: | --- |
| Global sidebar | 228px | collapsible |
| Plan rail | 220px | persistent on wide/medium |
| Activity canvas | 360px | 340–400px preferred |
| Market workspace | remainder | 560px minimum on wide layout |
| Inspector drawer | 320px | 300–340px; closed by default |
| Goal composer | 56–88px | expands for multiline goal |

Pane widths and collapse state persist through the same local-layout mechanism used by Glint. Persisted layout is a UI preference, not business truth.

## 4. Page and region hierarchy

### New Research

The central focus is `QuantGoalComposer`, not an empty chat stream.

Fields:

- outcome-oriented goal;
- asset selector (SPY only in Phase 0 execution fixtures);
- date range and 1D interval;
- benchmark;
- mode;
- attachment reference;
- experiment, repair, and runtime budget;
- submit command.

Shortcuts: `/` commands, `@` dataset/artifact reference, `⌘ Enter` submit, `Esc` close.

### Project detail

The page title is the project goal/title. It contains approved scope, latest run, previous attempts, authenticity, and the workspace. A project is durable; an attempt is replaceable only by creating another attempt.

### Run detail

The header answers goal, status, mode, limits, data authenticity, and whether action is required. The body maintains the process order:

```text
Plan → Activity / Action → Market evidence → Strategy report → Result
```

### Data

Phase 0 lists only named immutable fixture datasets and their source/authenticity metadata. It does not expose live-connection controls. Dataset detail shows snapshot ID, symbol, interval, date range, bar count, schema/parser version, digest, and related runs.

### Settings

Phase 0 shows truthful runtime and policy status: deterministic fixture runtime, network disabled, arbitrary code disabled, paper trading disabled, and model not connected. Controls that cannot change policy are informational rather than fake toggles.

## 5. Plan rail

The fixed product plan is:

1. Define research scope — User/System
2. Load market dataset — System
3. Build benchmark — System
4. Generate candidates — Agent
5. Run experiments — Agent/System
6. Repair recoverable failures — Agent/System
7. Validate robustness — Validator
8. Compare candidates — Agent/System
9. Generate report — Agent/System
10. Human decision — User

Each row shows owner, status, description, artifact count, and Human Gate marker. Permitted step status is Pending, Active, Waiting, Completed, Failed, or Skipped. Progress is expressed through discrete completed steps and real experiment/repair counters, never an inferred percentage.

## 6. Activity and Action Center

### Activity

The feed is a safe chronological projection of `QuantRunEvent` records. Each item shows timestamp, actor, business action, short result, optional artifact, and status label. Components never parse raw event names; `quant-presentation.ts` owns the mapping.

Unknown events display `Run activity recorded`. The exact event name and safe payload may be shown in closed Advanced Inspector disclosure. Secrets, prompts, provider output, private paths, and hidden reasoning never appear.

### Action Center

Only commands legal for the current API snapshot are visible:

| Presentation | Visible actions |
| --- | --- |
| Waiting plan approval | Approve Plan; Request Changes; Cancel |
| Waiting execution approval | Review Execution Payload; Approve Once; Reject |
| Running | Cancel Run |
| Waiting for review | Review Candidate; Review Validation Findings; Open Report Draft |
| Completed | Open Report; Compare Candidates; Start New Run; Candidate for Paper Testing (label/handoff only) |
| Failed safely | Retry Run; Open Diagnostics; Start New Run |
| Cancelled | Retry as New Attempt; Start New Run |

Pause and Start Paper Trading are not offered. “Candidate for Paper Testing” does not execute or connect to a broker.

## 7. Market workspace

### Market toolbar

Symbol, interval, date range, Candlestick/Line selector, indicators, events, compare, fullscreen, and reset. Phase 0 implements SPY, 1D, the fixed fixture range, candlesticks, volume, SMA 20/50/100/200, strategy markers, and fixture event markers.

### Chart

The chart provides crosshair, safe tooltip, zoom/brush, price axis, volume, entry/exit markers, and Market/Earnings/Policy/Macro fixture events. Selecting an event opens its Inspector context and repeats the authenticity label.

### Strategy Report

The bottom panel is vertically resizable and exposes:

- Overview: candidate plus benchmark metrics;
- Performance: equity, benchmark, drawdown, simplified monthly view;
- Experiments: candidate/parameters/metrics/robustness/verdict;
- Trades: entry/exit/return/holding period/reason;
- Robustness: sensitivity, costs, concentration, split, warnings;
- Strategy: versioned read-only YAML-like specification, never executable Python;
- Logs: safe worker/validator/artifact/retry/repair events.

## 8. Artifacts and Research Report

All artifact cards share type, status, origin, authenticity, concise summary, related objects, and one legal action. Default cards omit raw UUIDs; the Inspector contains exact identifiers.

Supported Phase 0 artifact types:

```text
research_scope
dataset_snapshot
strategy_spec
backtest_result
equity_curve
trade_log
validation_report
research_report
execution_log
```

The Research Report is the final research artifact. It remains available for rejected, inconclusive, no-viable-candidate, cancelled-with-retained-artifacts, and completed runs as permitted by actual persisted state. A report is not a Decision Brief and is not investment advice.

## 9. Inspector

The 320px context drawer is closed by default and can inspect Run, Plan, Event, Dataset, Candidate, Backtest, Validation Finding, Artifact, or Report.

The default Run view shows:

- Run ID, state, attempt, mode, timestamps, latest sequence, and current step;
- maximum experiments, repairs, and runtime;
- network, arbitrary-code, and paper-trading policy;
- provider/model only when truthful;
- trace reference and authenticity.

Advanced is closed by default and contains exact versions, digests, hashes, event name, and safe diagnostic references. Selecting a chart marker, event, candidate, or artifact opens the matching context. Closing returns focus to the invoking control.

## 10. Responsive behavior

| Width | Composition |
| --- | --- |
| >1320px | Sidebar, Plan, Activity, and Market visible; Inspector drawer |
| 1000–1320px | Collapsible Sidebar; Plan retained; Activity/Market resizable; Inspector drawer |
| 960–999px | Process segments: Plan / Activity / Market / Report; no infinite vertical stack |

The minimum supported window is 960×720. Compact segment shortcuts are `1–4`; `J/K` changes selection, `E` opens experiment, `I` opens Inspector, and `R` starts only when the API reports that start is legal. Single-key shortcuts are disabled in editable controls.

## 11. Accessibility and ten-second hierarchy

- every icon button has an accessible name;
- visible focus, Tab/Enter/Escape, focus trap, and focus return are required;
- status uses text/shape/icon in addition to color;
- charts expose a textual summary and tables remain keyboard-operable;
- tabular numeric values align; IDs/hashes use monospace;
- `prefers-reduced-motion` disables pulse and nonessential transitions.

The visual priority is: goal/asset → run status/mode/authenticity → current step → required action → market/result evidence → detailed provenance. A user must not need to navigate multiple pages to reconstruct these facts.

## 12. Data and presentation ownership

```text
PostgreSQL/API fixture repository
  → versioned Quant snapshot + append-only events
  → quant-api.ts transport/mappers
  → quant-presentation.ts pure projection
  → Quant components
```

The API owns lifecycle and mutation legality. The worker owns only approved scripted execution. The frontend owns selection, pane layout, disclosure, and view preference. The frontend does not own run state, verdict, approval, artifact status, event order, or authenticity.
