# Product

## Register

product

## Platform

web

## Users

Qurio is the current desktop product and UI brand in the PokieQuant repository. It is designed first for **quant-literate independent systematic researchers** working at a Mac desktop. They understand strategy parameters, benchmark comparison, drawdown, trading costs and out-of-sample evidence, but do not want to assemble and maintain notebooks, model prompts, backtest glue and research records for every question.

The initial credible user is an individual systematic trader or researcher working with simple rule-based OHLCV hypotheses on Binance or retained CSV data, especially at `4h` and `1D`. No-code is the interaction method, not a beginner-investing position. The user is expected to judge evidence rather than ask the product for an unexplained trading signal.

Python-capable solo quants are a secondary audience for rapid triage and retained evidence. Qurio does not yet replace their programmable research stack because the current runtime supports a bounded set of registered strategy families. Small institutional teams, complex portfolio desks, options researchers, ML-alpha platforms and high-frequency teams are not current target segments.

## Product Purpose

Qurio is an **AI-native quant research workspace powered by a verifiable autonomous research Agent**. Its core job is to turn an investment idea into comparable evidence, then preserve enough structure for the researcher to inspect, revisit and refine that work without rebuilding it from scratch.

External hero: **Turn an investment idea into comparable evidence—and keep refining what works.**

Internally, the product loop is:

`Idea → Research → Candidate Experiments → Comparative Evidence → Conclusion → Continue / Refine`

The user chooses a market, dataset, interval and objective; the Agent proposes bounded hypotheses, runs experiments, compares strategies and presents the result through professional charts, tables and reports. Success means the user can understand what was researched, which strategy performed best, why it was selected and what to do next without assembling notebooks, prompts and backtest scripts by hand.

## Positioning

Qurio is an **AI-native quant research workspace powered by a verifiable autonomous research Agent**. The Agent is the constrained research executor: it turns a bounded goal into an approved plan, selects registered tools, observes deterministic results, adapts within an explicit budget and stops with a reviewable conclusion. The Workspace is where research is defined, supervised, understood and continued.

External positioning:

> For independent systematic researchers, Qurio turns a bounded market hypothesis into comparable, reviewable and continuable strategy evidence through an Agent constrained by an approved plan and authoritative evaluation.

The current promise is deliberately scoped: within supported data, intervals and strategy families, Qurio advances an idea to evidence and a Continue / Refine or stop decision. It does not promise to discover alpha, research any arbitrary strategy or replace a complete professional Quant development platform.

It is not positioned as a local-runtime manager, security console, audit viewer, Agent trace inspector or generic chatbot. Reproducibility and safety remain implementation qualities, not the primary front-stage product story.

## Agent-native product behavior

Agent-native means the user does not manually assemble the research procedure. A credible primary flow must demonstrate all of the following:

1. The user supplies a market hypothesis, data scope, objective and budget.
2. The Agent proposes an executable plan whose strategy families, comparison objective and completion criteria constrain later actions.
3. The Agent chooses and invokes registered research tools one action at a time.
4. Tool observations change the next decision; candidate generation is not a fixed parameter sweep hidden behind conversational copy.
5. Structured Research Memory prevents exact repeated work without presenting prior holdout evidence as new validation.
6. The Agent stops when evidence, novelty or budget is insufficient rather than extending an optimization loop indefinitely.
7. Final selection follows the approved objective or carries a server-validated evidence-based deviation.
8. The user supervises through plan approval, quantitative evidence, report, Continue / Refine and history rather than a transcript-first chat surface.

The number of visible Agents is not a product metric. Planning, execution and review may later use different internal model calls when evaluation proves a benefit, but the user continues to work with one Research Agent and one authoritative quantitative evaluator. The product does not offer an Agent Builder, Agent marketplace, deployment model, replay session or live-trading surface. Paper Trading is a separate simulation-only handoff from one retained final Research Report; it is not part of the Research Agent loop and grants no live execution permission.

## Current Product Phase

The bounded mainline gate is complete: D0-lite market-v2 Add Data, W1-lite Research Contract and Decision Ledger, interval-aware sufficiency, Research-Series holdout isolation and the focused Data → Research → Compare → Analyze → Continue / History golden path are implemented. W2-lite Evidence Focus, W3 train-only robustness sensitivity, R1/R2-lite verified repair learning and E0 evidence export are also complete.

D1 implements a server-driven, fixed-host, read-only Kraken Spot connector for allowlisted BTC/ETH USD/USDT pairs at `4h` and `1D`. Raw provider rows remain untrusted until native validation, normalization and canonical market-v2 persistence. Contract, API and deterministic browser gates pass; a live no-key read-only smoke on 2026-07-24 verified both intervals, the 721-row response boundary and removal of the current uncommitted bar.

V1 is complete with one retained Kraken BTCUSD `4h` → DeepSeek `deepseek-v4-flash` → E0 →
History proof in `.run/v1-kraken-deepseek-20260724-183209` and Mock fallback disabled. The Run
completed through the accepted `A/B → C → decision` branch: three experiments ran
(A `sma_crossover_20_100`, B `breakout_20`, C `sma_crossover_50_200`). The first Candidate C create
call was rejected once with `ITERATION_REPLAN_TEMPLATE_RELATION_INVALID`; the next model turn
received the exact rejected arguments, changed only `replan_decision.action` to
`switch_approved_family`, and succeeded. Exactly one failed tool call was recorded. The final
training ranking was C, B, A; because C produced zero training trades, the structured
`research_decision` selected B `breakout_20` via `robustness_override` / `minimum_trade_evidence`
while referencing C. B then failed the sealed holdout and recommended `revise_research`. The same
dataset, runtime/split, selected candidate and E0 identities survived historical reopen. This is
engineering evidence of one bounded negative research outcome, not an alpha, profitability,
production-reliability or user-demand claim.

Completed in this order:

1. Add a read-only Research Series projection over existing lineage and attempt identities.
2. Extend Continue / Refine to the public market-v2 path without adding a second composer or lineage model.
3. Make Runs and Report clearly distinguish versions from attempts and preserve parent comparison context.
4. Refine the Research home and Copilot around typed Current / Observation / Next once the series flow works end to end.
5. Let public market-v2 New research and Continue / Refine select a cadence-aligned UTC window inside one validated stored dataset without changing Retry identity.
6. Add a direct Compare with source action for a directory-validated Continue / Refine version, reusing the existing Runs comparison instead of adding a Research Series page.
7. Verify one real DeepSeek Continue on a narrower stored Binance `4h` window with no Mock fallback before choosing another interface capability.
8. Explain the change from a Continue / Refine version to its source inside the existing Runs comparison, and prohibit improvement claims when the research context differs.
9. Let an eligible compared version start the next Refine directly, prefilled with its retained candidate, research context and validation-driven follow-up reason.
10. Add an Agent-guided next-step recommendation: Refine after failed or inconclusive evidence, stop after a passed sealed holdout, and never create another Run without user confirmation.
11. Add one suggested refinement: one explicit user action starts one independent Auto Research version with retained lineage and evidence context, then returns to the next report for review.
12. Add an opt-in Agent-native Research Loop: a root market-v2 Auto Research Run may precommit exactly one train-only, comparison-driven Refine version before opening the root sealed holdout, then the series stops for review.
13. Link the selected candidate's retained trades to its bounded market path inside Analysis, so a researcher can inspect entry, exit, return and holding context without leaving the result workspace or triggering a second metric path.
14. Explain each candidate's hypothesis, initial or training-feedback origin, material change and final training-comparison decision inside the existing Experiments and Report surfaces.
15. Make the approved Agent plan executable: persist its candidate families and completion criteria, expose them to each decision, and reject plan-external candidate creation without adding a tool, page or strategy DSL.
16. Make Request changes a real replan: collect explicit user feedback, ask the configured planner for a revised executable plan, and publish it atomically without mutating the Run when planning fails.

The primary-loop audit is complete. **P19 Structured Research Decision v1 is implemented and
independently reviewed with P0/P1=0; P17 retains the real DeepSeek duplicate-avoidance evidence.**
P16–P19 complete the Agent-native v0.1 research method, and R0 closes the frozen real-provider
execution-repair baseline.

The current phase is post-mainline capability consolidation. **W4-lite Workspace Legibility is
complete**: the existing Overview, Qurio decision rail, Decision Ledger, Run Monitor and Decision
surface make the approved plan, latest material observation and next legal research action easier to
identify. It added no Agent aggregate, route, table, tool, execution surface or quantitative path.
**L1 Standalone Local Runtime is complete for Apple-silicon macOS 11+ builds**: Qurio.app embeds a
locked Python 3.12 sidecar containing the existing FastAPI and Quant Agent worker. First launch and
Settings can start, stop or restart it with DeepSeek, one explicitly configured
OpenAI-compatible HTTPS chat-completions provider, or the deterministic offline provider without
requiring the repository, Python or `.venv`. Runtime data lives in Application Support, provider
credentials remain in separate macOS Keychain entries, and existing Runs keep their recorded
provider/model identity. Source
builds retain the fixed-path development fallback; this packaging change adds no second research
runtime.
The next product expansion remains intentionally undecided until a demonstrated research-scope gap
justifies it.
**Paper Trading v1 is complete as an explicitly approved independent boundary.** One workspace-scoped
local simulator accepts only the candidate retained by a completed final Research Report, creates a
reviewable order draft, requires a separate submit action, records deterministic fills, positions
and account reconciliation, and exposes no live host, live credentials or live-order route.
S0 has made a **no-go / defer**
decision for constrained SDK implementation: retained evidence does not yet show that valuable
approved research questions require arbitrary strategy code, while a complete SDK would add a
new causal-execution and isolation boundary. V1 and the bounded S0-lite Strategy Scope Contract
are complete. Requests are labelled `supported`, `bounded proxy` or `unsupported` before
experiments begin; proxies require explicit approval and unsupported requests cannot enter the
quantitative path. Plan-external candidate calls now receive a typed coupled template/parameter
repair that survives durable restore. Target-user validation is not a delivery gate. The detailed
package sequence and stopping rules live in
[`docs/POKIEQUANT_AUTONOMOUS_AGENT_PLAN.md`](../../docs/POKIEQUANT_AUTONOMOUS_AGENT_PLAN.md).

Agent-native Research Loop v1 reuses Project, Run, Continue / Refine and the existing seven-tool Agent; it does not add a Campaign table, a new page, arbitrary code execution, automatic Retry or an unbounded loop. Retry remains available for ordinary Runs but is deliberately unavailable inside an opted-in bounded series so its declared total experiment and action budgets remain truthful.

The one-Agent, seven-tool and single authoritative quantitative-evaluator boundaries remain unchanged. Before each named package starts, check the capability inventory and extend the listed reusable assets. Paper Trading was explicitly activated as a separate local simulation boundary; R3–R5, broad Skills/MCP ecosystems, Broker/live trading and portfolio/ML expansion remain deferred.

Do not spend a development cycle polishing safety copy, provenance metadata, focus choreography or rare failure states while a primary research surface is still missing charts, comparison tools, tables or meaningful actions.

## Primary User Loop

1. Select market, symbol, dataset, interval and date range.
2. Describe a bounded research objective or choose a research template.
3. Approve an executable Agent plan, then let the Agent generate hypotheses and run bounded experiments.
4. Observe material progress, findings and decisions without reading orchestration internals.
5. Compare candidate strategies using metrics, equity, drawdown, trades and robustness views.
6. Read the validated report, refine the question, start another research version or revisit history.

The interface is successful when a user can identify the research question, leading strategy, decisive metrics and next action within ten seconds of opening a completed run.

## Research Memory

Research Memory is the structured history of one research direction: its root Run, Continue / Refine versions, Retry attempts, selected candidate identities and retained evidence. It is not a transcript archive and must not be modeled or presented as chat history.

The existing domain remains authoritative:

- A Project plus its root Run starts a research series.
- Continue / Refine creates a new version linked to a retained source Run and candidate.
- Retry creates a new attempt of the same Run; it is not a new version.
- Reports, comparisons, datasets and strategy evidence remain bound to their exact Run and attempt.

Research Series is initially a projection over those existing identities and relationships, not a new Mission, Question or Iteration aggregate.

## Research Agent and Strategy Boundary

Qurio uses one Research Agent with specialized, registered tools for planning, candidate creation, backtesting, comparison and reporting. Specialized tools do not become separate user-facing Agents.

`StrategySpec` remains the existing structured `template + parameters + canonical key` contract. The product does not introduce a user-visible strategy DSL, arbitrary Python editor or general-purpose coding environment.

This is the Agent-native v0.1 boundary, not a permanent claim that professional research requires only three templates. S0 found no retained evidence that approved research questions currently require a programmable strategy boundary, so the constrained Python Strategy SDK remains a design option rather than an implemented or approved capability. If later scope evidence establishes that several valuable causal strategies cannot fit registered templates, the preferred first programmable expansion would be:

- a typed market-data and target-position interface;
- locked dependencies and deterministic strategy identity;
- isolated execution with bounded CPU, memory and time;
- no network, shell, package installation or unrestricted filesystem access by default;
- mandatory tests before an Agent-authored change can enter a backtest;
- the existing authoritative fees, backtest, comparison, walk-forward and sealed-holdout path;
- retained code, parameter and evidence versions through the existing Project and Run lineage.

The advanced Agent may then inspect a strategy workspace, propose a patch, run tests and backtests, diagnose failures and revise within budget, analogous to a coding Agent operating on a closed quantitative contract. This is a separate post-v0.1 capability package, not permission to add arbitrary Python to the current loop.

Complex portfolio accounting, options semantics, broad ML-alpha infrastructure and high-frequency/order-book research require separate product decisions. In particular, high-frequency research is not an extension of the current bar-based `1h`/`4h`/`1D` engine and is outside the foreseeable product scope.

## Everyday Information Architecture

Reuse the current destinations:

- **Research:** the existing Workspace and New Research flow.
- **Runs:** research history, comparison and reopening.
- **Data:** dataset discovery, preview and selection.
- **Paper Trading:** isolated account, report-selected strategy handoff, order review, simulated fills and positions.
- **Settings:** runtime and product configuration.

A separate Library, Agents, Activity, Deployments or Portfolio destination is not planned until a demonstrated research job cannot be handled by Research, Runs or Data.

## Product Metrics

- **First Evidence Rate:** share of initiated research that produces at least one inspectable candidate result.
- **Time to Evidence:** elapsed time from starting research to the first inspectable candidate result.
- **Evidence Inspection Rate:** share of research results where the user inspects comparison, chart, trades, validation or report evidence.
- **Research Iteration Rate:** share of completed or terminal research that leads to Continue / Refine on retained evidence.
- **Plan-to-Evidence Completion Rate:** share of approved plans that reach a valid evidence-led conclusion, legal stop or explicit user review point.

## Front-stage Product Vocabulary

Lead with market and research language: symbol, interval, strategy, experiment, return, drawdown, Sharpe, trades, benchmark, comparison, result and report.

The following terms belong in secondary details, settings or audit drawers unless they directly block a decision: local execution, server-owned, immutable, digest, schema version, trace reference, provider attestation, validation policy and repair budget. Do not repeat them across page headers, cards, notices and buttons.

## Brand Personality

Disciplined, restrained, legible. The product should feel like a serious institutional research desk adapted for one researcher: calm under dense information, precise about uncertainty, and direct about failures. Its voice is concise and operational rather than conversational or promotional.

## Anti-references

- Generic AI dashboards assembled from repeated cards, decorative icons, status dots, gradients, oversized copy, or chat bubbles on every page.
- Dense trading terminals that expose every internal event without establishing a clear decision hierarchy.
- Decorative workflow rails, colored side stripes, connected green-dot timelines, and repeated success badges.
- Interfaces whose interaction model does not serve Qurio's autonomous research lifecycle.
- Interfaces that call training metrics “results,” imply paper-trading eligibility before sealed holdout review, or render synthetic curves as real evidence.

## Design Principles

1. Research results come first. Completed-run surfaces lead with the question, leading candidate, comparative metrics, charts and next action.
2. Agent activity supports the workbench. Approved plan, material observation and next legal research action explain the Agent without replacing financial analysis surfaces.
3. Comparative evidence beats isolated metrics. Users should be able to compare candidates, benchmarks, periods and risk before opening implementation detail.
4. Progressive disclosure beats dashboard accumulation. Provenance, diagnostics, validation detail and advanced settings live one level below the working surface.
5. Familiar controls earn trust. Standard financial charts, tables, tabs, fields, filters and desktop shortcuts take priority over invented Agent UI.
6. Safety is quiet until relevant. A blocked or consequential action must be explicit, but routine screens must not repeatedly advertise internal boundaries.

## Accessibility & Inclusion

Target WCAG 2.2 AA for contrast, keyboard navigation, focus visibility, names and roles, error association, and reduced-motion behavior. Status must never depend on color alone. Dense tables and charts must retain readable labels, keyboard-reachable controls, and textual alternatives for decisive evidence.
