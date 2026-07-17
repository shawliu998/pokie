# PokieQuant Phase 0 Product Specification

Status: implementation contract

Audience: product, design, Mac frontend, API, worker, QA, security, and repository reviewers

Baseline: Glint `codex/phase31-agent-workspace-ui` at `eb9a4be58c4a16b790d0b7568735c53a3627fe51`

## 1. Product outcome

PokieQuant is a desktop Agent workspace that turns a natural-language market-research goal into a bounded, reproducible, reviewable, and auditable research process.

Phase 0 delivers an interactive product shell, not a production quantitative execution system. It uses API-backed deterministic fixtures and a scripted worker to demonstrate the complete governed workflow. An additive pure daily-bar kernel computes the canonical candidate metrics, trades, and report projection from 1,564 deterministic synthetic weekday bars:

```text
Goal → Approved scope → Plan → Human approval → Deterministic run
     → Candidate experiments → Validation → Comparison → Research Report
```

The product promise is **Auditable Autonomous Market Research**. In Phase 0, “autonomous” means that a previously approved deterministic script advances within explicit experiment, repair, runtime, network, and execution limits. It does not mean arbitrary code execution, unrestricted model use, live trading, or autonomous risk expansion.

## 2. Users and jobs

The primary user is a financially literate researcher, product builder, or portfolio analyst who needs a transparent research workflow rather than a chat transcript.

Their jobs are:

- define an outcome-oriented research goal and freeze its asset, date range, benchmark, assumptions, and limits;
- inspect and approve the plan before any simulated execution begins;
- understand the current step, recent safe activity, and required human action in one scan;
- compare candidate strategies against a benchmark and against robustness checks;
- distinguish an invalid candidate, a rejected hypothesis, an inconclusive result, and a system failure;
- open artifacts and reproduction metadata without seeing secrets, hidden reasoning, or invented tool activity;
- cancel, retry, or start a new attempt without rewriting prior run history.

## 3. Phase 0 demo contract

The accepted main demonstration uses SPY daily data and visibly labeled fixture results. A user can:

1. open PokieQuant and browse existing projects;
2. create a project and enter a research goal;
3. select SPY, the fixed daily interval, a supported date range, and Ask, Plan, or Auto Research mode;
4. inspect the generated plan and its limits;
5. approve the plan or request a new version;
6. review and approve the simulated execution payload where that gate is configured;
7. start and observe a deterministic run through data loading, benchmark construction, candidate generation, one repair, validation, comparison, and reporting;
8. inspect the market chart, trades, metrics, robustness findings, logs, and three candidates;
9. see Candidate A rejected for parameter sensitivity, Candidate B labeled “Candidate for paper evaluation,” and Candidate C marked inconclusive;
10. open the Research Report and Run Inspector;
11. cancel a cancellable attempt, retry as a new attempt, and preserve prior events and artifacts;
12. replay a completed run where no candidate passes validation without presenting it as a system failure.

The experience must be rendered by the real React workbench from fixture API data. Static screenshots are evidence of acceptance only; they are not the implementation.

## 4. Truth and authenticity contract

Every Phase 0 dataset, metric, event, artifact, report, chart marker, and preset answer carries one of these visible labels:

- `Synthetic Demo Fixture`: generated specifically for the demonstration;
- `Imported Demo Fixture`: derived from a bundled, immutable demonstration input.

The label appears in the global/header context and again on relevant Dataset, Backtest, Validation, and Report details. It must survive compact layouts and screenshots.

Phase 0 must not imply that it performed any of the following:

- live or historical market-data retrieval from a network provider;
- a real model call, web search, hidden chain of thought, or arbitrary tool call;
- a backtest over real market observations, or any verified future performance calculation (all computed results use generated synthetic weekdays);
- token use, provider cost, or percentage progress when no trusted value exists;
- paper trading, broker connection, order placement, or investment advice.

UI state must come from an API snapshot, a durable event, or a named fixture projection. React timers may animate a transition already owned by the fixture server, but may not decide or persist a run transition.

## 5. Product principles

### Agent workspace, not chat

The central object is a continuing research session with Goal, Plan, Activity, Human Gates, Artifacts, Market Workspace, Result, and Inspector. The composer asks the user to describe an outcome. User goals, system events, and research conclusions have distinct visual treatment.

### Truth before theater

Display only persisted state, contract-valid fixture data, durable events, actual configured limits, and legal commands. Do not infer actions from elapsed time or invent progress from event counts.

### API-owned transitions

The API is the command and lifecycle authority. Create, plan approval, plan-change request, execution approval, cancel, and retry commands validate current state, expected version, workspace scope, and idempotency before writing state and an audit record. The client never patches `QuantRunState` directly.

### Negative conclusion is not system failure

Candidate verdict and run health are orthogonal:

- a candidate can be `rejected`, `invalid`, or `inconclusive` while the run continues;
- a run can complete successfully with zero viable candidates;
- negative conclusions and rejected artifacts remain reviewable and reproducible;
- `failed` is reserved for an execution/infrastructure failure that prevents the approved research process from reaching its terminal report contract.

### Human gates are first-class

Plan approval, execution approval, uploaded-code execution approval, simulated-deployment approval, risk-limit change approval, and external-network approval are explicit records. Phase 0 implements only deterministic gate states and UI. It never executes Python, accepts arbitrary uploaded code, deploys a strategy, changes risk limits, or enables the network.

### Dense, restrained, accessible

The product preserves Glint’s compact macOS workbench character: resizable panes, low-contrast surfaces, 1px borders, four-pixel spacing, tabular numbers, visible focus, reduced motion, and labels in addition to color.

## 6. Research modes

| Mode | Phase 0 behavior | Creates a run | Human boundary |
| --- | --- | ---: | --- |
| Ask | Returns a deterministic preset explanation with cited fixture artifacts | no | read-only |
| Plan | Creates or revises a structured plan and frozen scope | draft run/session only; never worker-claimable | approve, request changes, or cancel |
| Auto Research | Uses an approved plan and optional execution approval to start a deterministic attempt | yes | cancel while legal; review results |

The default Auto Research limits are:

```text
Maximum experiments: 3
Maximum repair attempts: 2
Maximum runtime: 5 minutes
Internet access: Disabled
Arbitrary Python: Disabled
Paper trading: Disabled
```

Used experiments and repairs may be shown only from persisted counters/events. Token and cost fields are omitted in Phase 0.

## 7. Domain language and invariants

PokieQuant adds a financial domain rather than renaming Glint objects:

- `QuantResearchProject`
- versioned `QuantResearchScope` and `QuantPlan`
- `QuantResearchRun` with independent attempt number
- immutable `DatasetSnapshot`
- bounded `MarketBarSeries`
- `QuantExperiment` and versioned `StrategySpec`
- `BacktestResult`, `BacktestMetrics`, and immutable `TradeRecord`
- `ValidationFinding` and `CandidateVerdict`
- `QuantArtifact` and final `ResearchReport`
- append-only `QuantRunEvent` and approval/audit records

Glint `Signal`, `Investigation`, `Evidence`, `ClaimVersion`, `InvestigationSynthesis`, and `DecisionBrief` are not substitutes for these objects. Existing Glint objects stay intact for retained upstream code and do not appear in the PokieQuant main path.

Required domain invariants:

1. Scope, plan, dataset snapshot, strategy spec, validator version, execution assumptions, and artifact hashes are pinned to an attempt.
2. Retry creates a new attempt; it never clears or rewrites the old attempt.
3. Events are append-only and uniquely sequenced per run.
4. Plan or scope changes create a new immutable version.
5. The worker cannot approve a plan, approve an execution payload, alter scope, or promote a result outside validator rules.
6. The UI cannot manufacture state, verdicts, artifacts, or activity.
7. Unknown events render as `Run activity recorded`; their raw name is visible only in Advanced Inspector.
8. `completed` describes process completion, not investment quality.

## 8. Deterministic fixture scenario

The canonical fixture contains:

| Result | Annualized return | Maximum drawdown | Sharpe | Trades | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| Buy and Hold | 23.2% | -23.8% | 5.30 | 1 | benchmark |
| Candidate A · SMA 20/100 | 20.6% | -8.8% | 5.78 | 7 | Rejected · >5 pp parameter sensitivity range |
| Candidate B · SMA 50/200 | 18.4% | -11.1% | 5.07 | 2 | Candidate for paper evaluation |
| Candidate C · 200-day breakout | 16.3% | -15.5% | 4.46 | 2 | Inconclusive · fewer than 3 closed trades |

These numbers are computed by the pure daily-bar kernel, but the input path is generated synthetic data without an exchange holiday calendar or corporate actions. The unusually high synthetic Sharpe values are not market evidence. “Candidate for paper evaluation” is a research workflow status, not a recommendation and not an enabled paper-trading action.

## 9. Research Report contract

The final `research_report` artifact contains:

1. Research Goal
2. Approved Scope
3. Dataset Snapshot
4. Benchmark
5. Candidate Summary
6. Experiment Comparison
7. Robustness Findings
8. Rejected Candidates
9. Limitations
10. Conclusion
11. Proposed Next Step
12. Audit and Reproduction Metadata

It displays the fixture label, Run ID, attempt, Dataset Snapshot ID, Strategy Spec version, Validator version, artifact hashes, generation method, human-review status, and this disclaimer:

> This product is a research interface. Demonstration results are synthetic and are not investment advice, a recommendation, or evidence of future performance.

For a no-viable-candidate run, the report is still generated and says that no candidate passed the configured validation. That conclusion is retained as a successful research result.

## 10. Phase 0 scope

Included:

- PokieQuant navigation, project/run lists, goal composer, and three modes;
- generalized Glint shell patterns for header, plan, activity, action center, artifacts, inspector, responsive panes, streams, and fixtures;
- independent Quant contracts, API surface, state projection, deterministic worker, fixture data, and artifacts;
- SPY/1D market workspace with candlesticks, volume, supported SMAs, event/strategy markers, and fixed fixture range;
- Strategy Report tabs for Overview, Performance, Experiments, Trades, Robustness, Strategy, and Logs;
- deterministic full, plan-change, cancellation/retry, no-viable-candidate, and safe-failure flows;
- contract, unit, component, API, E2E, screenshot, accessibility, authenticity, and license checks.

Excluded:

- broker connections, orders, paper or live trading;
- arbitrary Python, shell, package installation, Jupyter, or uploaded-code execution;
- live/realtime market data, news fetch, network search, or unrestricted external access;
- production backtest orchestration, parameter optimization, statistically useful research inputs, or a model provider; the bounded kernel path uses only deterministic synthetic evidence;
- multi-agent orchestration or autonomous expansion of scope/risk;
- login, paid plans, team RBAC, cloud deployment, or production SLOs;
- financial advice or claims of likely future profitability.

Unsupported future controls are not rendered as enabled actions. A future capability may appear only as clearly disabled explanatory text when required to explain a gate.

## 11. Success and acceptance

At 1440×960 a first-time viewer can answer within ten seconds:

- what the goal and asset are;
- which mode and authenticity label apply;
- which step is active and what the Agent is doing;
- whether a human action is required;
- the configured experiment/repair/runtime limits;
- which candidate was rejected and why;
- whether the run failed or reached a negative conclusion;
- what the proposed next step is.

Implementation acceptance additionally requires:

- refresh does not lose server-owned run state;
- cancel prevents subsequent worker events;
- retry creates a new attempt;
- completed events are not duplicated;
- no fixture selector appears in production UI;
- every active control corresponds to a legal API command;
- no Glint product-intelligence destination or vocabulary remains on the main demo path;
- no unreviewed code or dependency is migrated from PokieTicker or Spark Agent;
- inherited quality gates and the additive PokieQuant gate pass.
