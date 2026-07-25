# Qurio Agent-Native Research Plan

Status: active product and implementation plan
Current checkpoint: the mainline through D0-lite, W1-lite, G1–G3, W2-lite, W3, R1/R2-lite, D1 and
E0 is complete. P16–P19 remain the Agent-native v0.1 research method, and R0 Agent Execution Repair
remains the frozen real-provider repair baseline. D1's deterministic browser/API gates and live
no-key Kraken `4h`/`1D` transport smoke pass. S0 has made a no-go / defer decision for constrained
strategy-execution SDK implementation because retained evidence does not yet demonstrate a
strategy-template gap. The separate `qurio-sdk` read-only client, CLI and four-tool MCP server
expose retained API evidence without adding strategy execution or another calculation path.
V1 real Connector → Evidence proof is complete through its accepted `A/B → C → decision` branch in
`.run/v1-kraken-deepseek-20260724-183209`. S0-lite
Strategy Scope Contract is complete and independently reviewed with no P0/P1 blocker. Target-user
validation is not a delivery gate in this plan.
Planning source of truth: [`POKIEQUANT_CAPABILITY_INVENTORY.md`](./POKIEQUANT_CAPABILITY_INVENTORY.md)

## 1. Product decision

Qurio is an **AI-native quant research workspace powered by a verifiable autonomous Research
Agent**, not a general-purpose self-modifying agent, Agent Builder or trading platform. The product
should autonomously turn one bounded market question into comparable evidence, explain what it
tested, and help the researcher continue or refine the work without replacing the authoritative
quantitative calculation path.

The target loop is:

```text
Idea
  → approved executable research plan
  → bounded candidate experiments
  → objective-aligned training comparison
  → one evidence-driven adjustment
  → final comparison
  → one sealed holdout
  → conclusion
  → Continue / Refine or revisit history
```

The Workspace remains the primary product surface and research record. The Agent is the bounded
execution mechanism within that Workspace, not a separately configured, deployed or traded user
object. The product is already beyond a chat shell or single-tool assistant. It has one Research Agent,
seven registered tools, durable plans, one-action execution, observations, repair, strict 2+1
experimentation, a sealed holdout, Research Series lineage, Retry attempts, retained evidence and
real plan revision. P16–P19 provide the level-three semantics. The next goal is to make those
semantics visible and dependable through the complete primary user loop. Cross-Run verified
learning follows only after the mainline and evidence surfaces are complete; one successful
backtest never becomes reusable truth. Open-ended self-modification is not a product goal.

### Maturity model

| Level | Meaning | Qurio decision |
|---|---|---|
| L0 | Chat interface over static answers | Rejected |
| L1 | Model can call an isolated tool | Superseded |
| L2 | Goal → plan → tools → observations → bounded correction → completion | Implemented |
| L3 | Objective-aligned decisions, structured research memory and controlled replanning | Implemented through P19 |
| L4 | Validator-backed cross-Run repair and research-method learning | Planned through R1–R4 |
| L5 | Offline model optimization behind frozen evaluations and rollback | Conditional R5 |
| L6 | Open-ended self-modification and long-running autonomy | Explicit non-goal |

### Positioning and service population

Product category:

> **An AI-native quant research workspace powered by a verifiable autonomous Research Agent.**

The Agent owns the bounded progression from goal to plan, tool use, observations, correction and
completion. The Workspace lets the researcher define, supervise, understand and continue research.
This keeps the research loop Agent-native without turning it into a chat shell, an Agent Builder or
a live-trading surface. The explicitly approved Paper Trading v1 is a separate local simulation
handoff from one final retained Research Report; it adds no Research Agent tool or live permission.

The initial service population is deliberately narrower than “all quants”:

| Segment | Decision | Product job |
|---|---|---|
| Quant-literate independent systematic researcher | Primary | Test a bounded rule-based hypothesis without maintaining notebooks, backtest glue and research records |
| Advanced individual trader who understands drawdown, costs and out-of-sample evidence | Primary | Compare transparent candidates and decide whether to stop or refine |
| Python-capable solo Quant or researcher | Secondary | Triage ideas and preserve evidence; not replace the programmable stack yet |
| Beginner seeking a buy/sell signal or guaranteed return | Exclude | The product produces research evidence, not investment instructions |
| Small institution or portfolio desk | Defer | Collaboration, entitlements and complex portfolio accounting are not current capabilities |
| Options, broad ML-alpha or high-frequency team | Exclude from current roadmap | These require different data, execution and validation architectures |

The most credible initial wedge is simple OHLCV research on retained Binance or CSV data, especially
`4h` and `1D`, because those paths have the strongest real end-to-end evidence. “No-code” describes
the interaction, not a novice-investor audience.

The competitive boundary is also explicit:

- OpenBB is a broad data, widget, dashboard and Agent workspace. Qurio may borrow proven
  workbench interaction patterns but does not compete to become a universal financial UI.
- QuantConnect/LEAN is a programmable multi-asset research, backtest, optimization and live-trading
  platform. Qurio currently automates a narrower intent-to-evidence job rather than replacing
  that engine and ecosystem.
- Composer combines AI/no-code strategy construction, backtesting and brokerage execution for
  retail automation. Qurio does not sell an automatic-trading or one-click-alpha promise.
- Engine may inform clarity of bounded Agent state and material activity, but it is not a product
  boundary to copy: Qurio does not adopt trading deployment, broker execution or runtime positions.

Primary references:

- <https://openbb.co/products/workspace/>
- <https://docs.openbb.co/workspace>
- <https://www.quantconnect.com/docs/v2>
- <https://www.quantconnect.com/docs/v2/lean-engine/getting-started>
- <https://www.composer.trade/>

## 2. Architectural rules

1. Keep one Research Agent with the existing seven registered tools. Specialized tools do not
   become user-visible agents.
2. Keep `Project + root Run`, Continue / Refine, Retry, candidates, artifacts and reports as the
   authoritative domain. Do not add Mission, Question, Iteration or Campaign aggregates.
3. Keep strategy identity as `template + parameters + canonical key`. Do not introduce arbitrary
   Python or a user-visible strategy DSL.
4. Keep every decisive metric on the existing deterministic runtime path. The model plans,
   chooses tools and explains; it does not calculate returns, ranking metrics or holdout outcomes.
5. Reuse Data, New Research, Overview, Experiments, Analysis, Runs and Report. Do not add a page for
   Agent memory, a chat shell, a fourth context column or a Library before a demonstrated job
   requires it.
6. Autonomy remains bounded by explicit action, experiment, repair, version and holdout limits.
7. Research Memory is structured retained evidence and lineage, not transcript history or hidden
   reasoning.
8. A new dependency or open-source subsystem is allowed only for a measured capability gap after
   license and architecture review. Do not replace the current runtime merely to imitate another
   agent framework.
9. Learning uses typed, validator-backed Run experience. Do not update model weights after each
   Run or promote one success into a global policy. Automatic context, memory and learning never
   receive prior sealed-holdout evidence. An explicit user-approved qualitative refinement reason
   may reference a prior result only when it is marked as development evidence and cannot support
   another fresh validation claim.
10. Do not add an Agent aggregate, Agent Builder, deployment, replay session, position/order ledger
    or trading runtime. Any visible Agent activity is a structured projection of an existing Run,
    experiment, artifact or legal research action.

## 3. Target architecture

```text
User objective
  └─ Planner
       └─ approved executable plan
            ├─ candidate-family allowlist
            ├─ comparison objective
            ├─ bounded completion criteria
            └─ fixed budgets
                 ↓
Research Controller
  ├─ compact pinned Agent context
  ├─ seven-tool registry
  ├─ one decision per fenced claim
  ├─ deterministic evaluator
  ├─ structured Research Memory projection
  └─ bounded replan checkpoint
                 ↓
Evidence store
  ├─ candidates and canonical identities
  ├─ training comparisons and iteration feedback
  ├─ walk-forward and regime evidence
  ├─ one sealed holdout
  ├─ report and export
  └─ versions, attempts and history
                 ↓
Learning control plane
  ├─ typed learning traces derived from existing Run events and artifacts
  ├─ schema-versioned repair memory
  ├─ train-only research-method memory
  ├─ frozen engineering evaluations
  └─ versioned promotion, shadowing and rollback
                 ↓
Human decision
  ├─ Continue / Refine
  ├─ stop
  └─ revisit retained evidence
```

There is no separate LLM judge. Deterministic comparison and validation remain the evaluator. A
model may explain a decision or request a registered action, but it cannot create evidence.

## 4. Delivery sequence

### P16 — Objective-Aligned Comparison v1

Category: core-flow correctness.
Primary user action: approve how candidate evidence will be compared and have the runtime follow
that objective.

#### Problem

Before P16, the plan constrained which strategy families could be tested, while the authoritative
training ranking always used Sharpe, return and drawdown in that order. A user asking primarily for
drawdown control could therefore approve one objective and receive a differently optimized
comparison.

#### Contract

Add one closed plan field:

```json
{
  "selection_objective": "risk_adjusted_return"
}
```

Allowed values and deterministic ranking are:

| Objective | Ranking rule |
|---|---|
| `risk_adjusted_return` | Sharpe → total return → maximum drawdown |
| `total_return` | Total return → Sharpe → maximum drawdown |
| `drawdown_control` | Non-zero trades → maximum drawdown → Sharpe → total return |

The approved objective must be persisted on the Run and plan artifact, projected into every Agent
decision, used by the authoritative training comparison, and used to select the improvement
reference for the feedback-driven third candidate.

The comparison priority does not silently replace all robustness judgment. If a later package lets
the Agent select a candidate other than the first deterministic rank, that deviation must use the
structured P19 decision contract rather than free-form justification.

#### Reuse and compatibility

- Extend `QuantAgentPlan`, `QuantExecutablePlanContext`, `QuantRunRecord`, the existing comparison
  artifact and the existing `researchPlan` snapshot projection.
- Existing persisted Runs without the field default to `risk_adjusted_return`, preserving the
  established ranking.
- Retry and the one Research Series child retain the exact objective.
- Restore rejects unknown or mismatched objectives.
- Existing Run details add one `Comparison priority` row; no new page or card is created.

#### Acceptance

1. Drawdown, total-return and risk-adjusted goals produce distinct deterministic rankings.
2. Request changes can revise both strategy families and comparison objective.
3. The third-candidate improvement reference follows the approved ranking.
4. An unknown objective fails closed before Run mutation.
5. Retry, history reload and Research Series follow-up retain the objective.
6. One real DeepSeek plan returns the closed field with Mock fallback disabled.
7. Relevant backend, frontend, browser and compatibility regression suites pass.

#### Implementation state

P16 is complete in the working tree. The approved objective is persisted with the Run and current
plan artifact, controls deterministic comparison and the third-candidate improvement reference,
and survives Retry, Research Series follow-up and history reload. Restore cross-validates the Run,
current plan artifact, training comparisons and iteration feedback; unknown, missing or mismatched
objective state fails before cache replacement. Until P19 introduces a validated decision
contract, finish must select the first candidate in the final objective-aligned ranking and rejects
any free-form model override before series mutation, sealed holdout or report creation.

Focused Agent, API, runtime and migration regressions pass. Frontend parsing and the existing Run
details projection were already covered by the additive P16 contract; this final backend gate did
not change the frontend shape. The existing real DeepSeek planner compatibility check returned a
closed `selection_objective` with Mock fallback disabled; the final rank-one and restore fixes were
verified deterministically without another paid provider call.

### P17 — Structured Research Memory Retrieval v1

Category: core interface capability and core-flow correctness.
Primary user action: start or refine research without unknowingly repeating prior experiments.

#### Scope

Build a read-only memory projection from existing Projects, Runs, versions, attempts, candidate
canonical keys, training comparisons and retained limitations. Do not add a Research Memory table,
page or transcript store.

The initial context shape is:

```json
{
  "research_memory": {
    "source_run_ids": [],
    "tested_candidate_keys": [],
    "failed_hypotheses": [],
    "retained_training_findings": [],
    "comparability": "same_evidence"
  }
}
```

`comparability` is closed to:

- `same_evidence`: same dataset and split; use only to avoid duplicate work;
- `overlapping_evidence`: overlapping range or related dataset; present as prior context, never new
  validation;
- `fresh_evidence`: a distinct eligible evidence window that can inform a new hypothesis while the
  current Run still computes its own metrics.

#### Retrieval order

1. Current Research Series ancestors.
2. Retry source identity where applicable.
3. Other terminal Runs in the same workspace with compatible symbol, interval and strategy family.
4. At most five source Runs and a bounded number of canonical candidate keys.

#### Leakage boundary

Automatic Agent context may include:

- candidate template, parameters and canonical key;
- training rank and structured training failure category;
- dataset identity, cadence, range and comparability;
- explicit limitations required to avoid repeating invalid work.

It must not include:

- raw holdout metrics or generalization payloads;
- old report prose or chat history;
- hidden reasoning, raw provider responses, trades or bars;
- an old conclusion presented as new validation.

Same-evidence memory can prevent duplication but cannot support a new improvement claim.

#### Persistence and UI

- Pin the chosen source Run IDs and a canonical memory-context digest at Run start so the context
  cannot change midway through execution.
- Reuse the plan artifact or existing Run fields; do not add a database aggregate in v1.
- In existing Run details, show only a compact line such as `Prior research considered · 3 runs`.
  Source Runs remain accessible through Runs/history.

#### Acceptance

1. The Agent does not recreate an exact ancestor candidate.
2. Same-evidence memory contains no holdout/generalization fields.
3. No related history produces the same behavior as today.
4. Reload and Retry preserve the pinned memory digest.
5. Cross-workspace, nonterminal, incompatible-cadence and corrupted history is excluded.
6. A real DeepSeek refinement demonstrates that the memory prevents one duplicate candidate without
   fabricating prior evidence.

#### P17-A implementation state

The backend and Agent core are implemented in the working tree. Every new root or Continue /
Refine Run receives one persisted canonical memory pin before execution; Retry deep-clones the
exact source pin and digest as part of attempt identity. Retrieval is stable and bounded to five
terminal source Runs and fifteen canonical candidate keys, with ancestors first and then compatible
same-workspace history. Create, revise, the legacy Research Series ancestor projection and the Mock
provider all consume the Run's one pinned tested-key set.

P17-A deliberately admits only `same_evidence`: exact dataset, symbol, cadence, range, runtime
descriptor and training split identity. `overlapping_evidence` and `fresh_evidence` remain deferred
instead of applying one misleading comparability label to a mixed pin. The retained payload is
whitelisted to source/data identity, template, parameters, canonical key, training rank, a closed
training-failure category and fixed limitations; it contains no prior holdout, generalization,
report prose, trades, bars, raw metrics or conversation history. P17-B projects only the validated
pin's source-Run and tested-candidate counts in the existing Overview context bar; it exposes no
source identities, candidate keys, digests, metrics, holdout/generalization, reports, trades, bars
or conclusions.

The real-provider acceptance completed on 2026-07-23 against a copied retained P5 database. Real
DeepSeek Run `a4bdac26-84f0-5543-aa33-3ea55f4c0c2e` received one same-evidence source Run and three
pinned tested candidate keys, then created two canonical-distinct candidates with zero overlap.
Mock fallback was disabled, no provider failure or fallback event was present, and the pinned
context passed the closed whitelist with no holdout/generalization or other prohibited evidence.
The sanitized evidence is retained at
`.run/p17-research-memory-20260723/p17-research-memory-evidence.json`.

This Run remained nonterminal after the provider repeatedly requested candidate C before producing
the required training feedback. It is valid P17 duplicate-avoidance evidence, but it is not claimed
as strict 2+1 terminal-flow or report evidence. That observed orchestration failure is an input to
P18 rather than being hidden behind a forced finish or a Mock rerun.

### P18 — Evidence-Driven Replan v2

Category: core-flow correctness.
Primary user action: let the Agent make the one remaining experiment materially responsive to the
evidence already produced.

P18 extends the current strict 2+1 sequence; it does not add another loop:

```text
candidate A + candidate B
  → training comparison
  → one structured observation
  → refine parameters | switch approved family | stop because no novel candidate
  → candidate C when eligible
  → final comparison
  → one sealed holdout
```

The third-candidate decision may use:

- the approved comparison objective;
- A/B training metrics and benchmark deltas;
- walk-forward stability and modeled regime coverage;
- tested canonical keys from current and eligible prior research;
- remaining experiment and action budget.

It may not use the current Run's sealed holdout, expand the strategy-family allowlist, add a fourth
candidate or create a new tool.

#### Acceptance

1. Candidate C cites the actual training comparison and an allowed structured replan action.
2. Candidate C is canonical-distinct from A, B and eligible ancestor candidates.
3. Insufficient budget or no valid novel candidate ends research truthfully without pretending the
   experiment ran.
4. Final comparison contains all completed eligible candidates before finish.
5. Sealed holdout is evaluated exactly once after selection is frozen.
6. Provider failure remains attributable and cannot silently become Mock success.

#### P18 implementation state

P18 is implemented without adding a tool, page, loop, strategy family or metric path. When the
default three-experiment Run has two completed base candidates, the runner now persists the
training comparison and iteration feedback before asking the provider for another decision. The
third candidate must carry one typed decision bound to that exact comparison and improvement
reference: `refine_parameters` keeps the selected family with materially different parameters,
while `switch_approved_family` uses another family already allowed by the executable plan.

Two typed terminal decisions cover the honest A/B-only boundary:
`stop_no_novel_candidate` must identify one bounded proposal whose canonical key is already present
in current or pinned Research Memory, and `stop_insufficient_budget` is accepted only when the
remaining action budget cannot pay for a candidate, backtest, final comparison and finish. Both
require a fresh A/B comparison, select its objective-ranked leader, produce no fictitious candidate
C, and cannot schedule a Research Series child. The server rejects conflicting or incomplete
payloads before state mutation.

Restore and persistence retain the decision on both the experiment and its strategy artifact,
recompute canonical strategy identity, verify feedback lineage and protect genuine pre-P18
feedback-linked candidates behind an explicit repository migration marker. A populated legacy
candidate and report restore successfully, the first subsequent write seals the marker, and marker
tampering fails before cache publication. The checked OpenAPI snapshot includes the additive
contract.

Focused Agent, Research Memory, Research Series, provider-failure, migration, OpenAPI and both
legacy/public market API integration suites pass, together with Ruff, Pyright and diff checks.
Independent semantic and compatibility reviews report P0/P1=0. No additional paid provider call
was used for the deterministic orchestration fix; the retained P17 DeepSeek Run remains the
truthful real-provider duplicate-avoidance evidence described above rather than being relabelled as
a terminal P18 run.

### P19 — Structured Research Decision v1

Category: core-flow correctness.
Primary user action: understand why the retained candidate follows—or deliberately deviates from—
the approved comparison objective.

Replace free-form final candidate choice with a small validated decision contract:

```json
{
  "selected_candidate_id": "candidate-c",
  "decision_basis": "approved_objective_rank",
  "deviation": null
}
```

A non-leading candidate requires one evidence-verifiable deviation:

```json
{
  "selected_candidate_id": "candidate-b",
  "decision_basis": "robustness_override",
  "deviation": {
    "reason": "walk_forward_stability",
    "reference_candidate_id": "candidate-c"
  }
}
```

Allowed deviation reasons are initially `walk_forward_stability`, `regime_coverage` and
`minimum_trade_evidence`. The server validates that the cited evidence actually supports the
deviation. Unsupported free-form overrides fail closed before holdout or report mutation.

The existing Candidate Evolution and Report surfaces render the structured basis. No LLM critic,
debate view or new decision page is added.

#### P19 implementation state

P19 is complete without adding a tool, page, loop, strategy family or metric path. The final
decision now binds the selected candidate to the latest train-only comparison and either approves
the deterministic objective leader or cites one closed, server-verifiable robustness deviation:
walk-forward stability, regime coverage or minimum trade evidence. Walk-forward and regime
overrides require a unique best supported candidate; ties fall back to the objective leader.

The provider receives only bounded train-only comparison evidence and may return the typed
decision. Mock and exhausted-budget paths use the same deterministic contract, while the server
remains authoritative and rejects unsupported choices before Research Series mutation, sealed
holdout or report creation. A legal non-leading choice survives structured stop, report creation,
fresh restore and one bounded Research Series follow-up whose seed is the validated selection.

The existing Candidate Evolution, Strategy Report and deterministic Markdown export explain the
exact basis and reference candidate. Persistence binds the report and its cited final comparison,
checks comparison content digests and requires nested walk-forward evidence to remain train-only.
Genuine pre-P19 data retains an explicit one-time compatibility boundary.

Focused P18/P19, Agent loop, Mock, Research Series, public market-run, migration and OpenAPI
regressions pass. The main window independently reran 130 backend tests and 279 frontend tests;
Ruff, formatting, Pyright, TypeScript typecheck, ESLint, production build and `git diff --check`
also passed across the implementation handoff. Independent semantic and compatibility reviews
report P0/P1=0. No paid provider call was required for this deterministic decision package.

## 5. Total roadmap after Agent-native v0.1

This roadmap replaces target-user validation as the next delivery gate. It uses frozen engineering
questions, real-provider regression, deterministic validators and retained evidence to decide
whether a package advances. It does not claim that engineering completion proves market demand or
user productivity.

The mainline and its ordered W2/W3/R1/R2/D1/E0 enhancements are complete. This is not a claim of
feature breadth; it establishes the minimum trustworthy loop in which a researcher can add data,
authorize research, compare experiments, inspect results, export evidence and continue or revisit
the exact retained work.

### Mainline completion gate

The gate is ordered and deliberately small:

1. **D0-lite:** truthful market-v2 Add Data for supported `1h`, `4h` and `1D` datasets.
2. **W1-lite:** minimum authoritative Research Contract and Decision Ledger in existing surfaces.
3. **Interval-aware sufficiency:** research eligibility reflects interval and required coverage,
   not one fixed bar-count assumption.
4. **Series-level holdout isolation:** automatic continuation remains train-only. If an explicit
   user-approved Refine uses post-holdout evidence, that evidence becomes development evidence and
   cannot be presented again as a fresh sealed validation.
5. **Golden mainline:** one focused Data → Research → Compare → Analyze → Continue / History E2E
   passes with retained dataset, strategy, comparison and lineage identities.

The gate closes P0/P1 blockers. P2 polish, broad audit/provenance presentation, extra security
hardening, rare inputs and exhaustive cross-browser matrices are recorded and deferred.

### Frozen R0 baseline

The first eight-question real-DeepSeek engineering run is retained as the immutable before state:

- one Run completed;
- one Run failed;
- six Runs exhausted the twelve-action boundary without reaching a terminal state;
- thirty-three `INVALID_ARGUMENTS` observations occurred;
- thirty-one of those errors were the same nested Candidate C contract conflict;
- four Runs created a legal, feedback-linked and canonical-distinct Candidate C.

The baseline questions, data, provider, budgets, raw results, report and hashes must not be rewritten
after a repair. Every real-provider rerun writes to a new evidence directory and reports the exact
before/after delta.

### Ordered execution roadmap

| Order | Package | Category | Outcome | Entry gate |
|---:|---|---|---|---|
| 0 | R0 — Agent Execution Repair | Core-flow correctness | Invalid tool calls become repairable or terminate honestly | Complete |
| 1 | D0-lite — market-v2 Add Data | Core interface capability | A user can create and select `1h`, `4h` or `1D` data in the existing Data page | Complete |
| 2 | W1-lite — Research Contract and Decision Ledger | Core interface capability | Users can see authorization, A/B/C adaptation and final choice in existing surfaces | Complete |
| 3 | G1 — Interval-Aware Sufficiency | Core-flow correctness | Research eligibility reflects interval and usable coverage | Complete |
| 4 | G2 — Series Holdout Isolation | Core-flow correctness | Continue / Refine cannot relabel used holdout evidence as fresh validation | Complete |
| 5 | G3 — Golden Mainline | Core-flow acceptance | Data → Research → Compare → Analyze → Continue / History works end to end | Complete |
| 6 | W2-lite — Evidence Focus | Interface enhancement | Existing candidate, metric, drawdown, trade and report evidence can be focused together | Complete |
| 7 | W3 — Robustness Surface | Core interface enhancement | Users can inspect cross-window, parameter-neighborhood and cost sensitivity without a second metric path | Complete |
| 8 | R1/R2-lite — Verified Learning | Core-flow enhancement | Typed traces and compatible known repairs reduce repeated tool failures | Complete |
| 9 | D1 — Connector Contract | Conditional data expansion | Approved read-only sources enter the canonical dataset path | Complete |
| 10 | E0 — Evidence Export | Conditional workflow expansion | Stored evidence and lineage export without client recalculation | Complete |
| 11 | S0 — Constrained SDK Decision | Conditional product decision | Decide whether registered templates leave a proven professional research gap | No-go / defer |
| 12 | V1 — Live Connector → Evidence Proof | Core-flow acceptance | Real Kraken data retains identity through Research, E0 export and History | Complete |
| 13 | S0-lite — Strategy Scope Contract | Core-flow correctness | Unsupported research goals stop before experiments instead of being forced into three templates | Complete |
| 14 | W4-lite — Workspace Legibility | Core interface capability | Existing Workspace makes the approved plan, material observation and next legal research action easy to identify | Complete |
| 15 | R3–R5 and E1–E4 | Deferred | SDK, broader learning, policy/model optimization, portfolio and ML remain optional | Separate explicit approval |

### W4-lite — Workspace Legibility

Primary user action: open an existing Research Workspace and identify the approved plan, latest
material observation, decisive evidence and one legal next research action without reading raw
events.

W4-lite reuses Overview, the Qurio decision rail, Decision Ledger, Run Monitor and Decision. Its
typed presentation and navigation changed without adding an Agent aggregate, route, table, tool,
execution surface, strategy family or authoritative calculation path. The package stops at this
scanability boundary; it does not expand into an Agent Builder, replay, paper/live trading or a
design-system rewrite.

Use parallel windows for read-only preparation, focused tests and independent review. A single
authoritative file or contract path has one writer. Parallel writers are allowed only for disjoint
files with frozen inputs; shared schemas, stores, snapshots, quantitative kernels and frontend
domain projections are never edited concurrently. A following package writes only after its input
contract is stable and the preceding package has no P0/P1 blocker.

### R0 — Agent Execution Repair

R0 fixes the real-provider failure without changing the strategy allowlist, budgets, tool count or
quantitative kernel.

Required behavior:

1. A tool failure returns a typed repair contract with the error code, invalid field paths, expected
   shape, allowed values or constraints, failed-action fingerprint and remaining budget.
2. The next provider decision receives that exact repair contract rather than flattened prose.
3. An equivalent invalid call cannot execute twice.
4. After a repairable failure, the Agent must correct the failed action. It cannot escape the guard
   by calling an unrelated tool.
5. A valid correction records the material argument delta. An invalid correction or exhausted
   repair allowance ends in a structured failure/stop state.
6. Action-budget exhaustion cannot leave a Run in `running_experiments`.

Acceptance — complete:

- focused red tests reproduce the nested Candidate C failure before the fix;
- contract, provider, runner, store, migration and public API regressions pass;
- a `4h` and a `1D` real-DeepSeek sentinel pass with Mock fallback disabled;
- the same frozen eight questions all reach a terminal state within the same budget;
- equivalent repeated invalid tool executions equal zero;
- each Run either completes a legal 2+1 sequence or records a legal structured stop;
- sealed holdout remains unavailable before selection and occurs at most once;
- the report records completed, failed, stopped, budget-exhausted, legal-C, invalid-action and
  provider-call counts without estimating user effort.

R0 is complete after independent semantic and compatibility review reported P0/P1=0.

### D0-lite — market-v2 Add Data

Category: core interface capability.
Primary user action: create and select a supported multi-interval dataset from the application,
then start research without a provisioning script.

The backend already exposes market-v2 CSV import, Binance fetch, list and preview for supported
`1h`, `4h` and `1D` intervals. The current Data page lists and previews market-v2 records but its
creation actions still use the legacy daily endpoints. This leaves the primary research loop
dependent on pre-provisioned multi-interval datasets.

D0 extends the existing `QuantApi` and `QuantDataPage`; it does not add a page, connection model or
data engine.

Acceptance:

1. Binance Add Data offers only the supported `1h`, `4h` and `1D` intervals and calls the market-v2
   endpoint.
2. CSV import requires an explicit supported interval and calls the market-v2 import endpoint.
3. A created dataset appears in the existing Catalog, preview and Use for research flows.
4. Research retains the same dataset digest, interval, periods-per-year and bounded UTC range.
5. Legacy daily Nasdaq and compatible stored datasets continue to work.
6. API, parser, component and focused Playwright coverage passes at the existing desktop sizes.

### W1-lite — Research Contract and Decision Ledger

Category: core interface capability.
Primary user action: inspect the Agent's authorization, evidence-responsive change and stopping
basis without reading raw activity logs.

W1-lite makes the minimum existing Agent-native contract visible without creating a new page,
chat shell, table or tool.

- The existing plan approval surface shows the interpreted hypothesis, data/cost assumptions,
  candidate-family allowlist, comparison objective, completion criteria and budgets.
- `QuantStrategyLab` shows explicit A/B roles, the train-only observation, Candidate C rationale
  and the final train decision or structured stop.
- Existing Report and Runs surfaces show the selected candidate, selection basis, Research Series
  version and retained follow-up or terminal reason.
- Existing Current / Observation / Next remains the compact supervision layer.

All values come from existing typed projections. The UI does not parse event prose, expose
chain-of-thought or calculate a second metric. Exact claim-to-chart/trade anchors, broad provenance
presentation and secondary inspector detail are deferred to W2-lite or E0.

### G1 — Interval-Aware Data Sufficiency

Category: core-flow correctness.
Primary user action: know whether a selected dataset contains enough usable history for its
interval before starting research.

G1 replaces one fixed **new-research admission** threshold with a closed rule derived from the
already validated cadence:

```text
required_bars = max(252, ceil(periods_per_year / 4))
inclusive_coverage = (last_open - first_open) + interval_delta
eligible = bar_count >= required_bars
           and inclusive_coverage >= required_bars * interval_delta
```

This gives `1h = 2,190`, `4h = 548` and `1D = 252` usable bars. It does not add another
quality system. Short data may remain stored and previewable while clearly ineligible for
research.

The rule applies only to current dataset eligibility and creation of a new root or user-approved
Continue / Refine range. Do not place it inside the reusable runtime descriptor or chronological
split constructor: historical reopen, Retry and an already-authorized automatic child retain their
exact pinned ranges. The existing 252-bar structural floor for an 80/20 split remains unchanged.

### G2 — Research-Series Sealed-Holdout Isolation

Category: core-flow correctness.
Primary user action: continue or refine a research series without silently training on evidence
that was previously presented as sealed validation.

G2 keeps candidate generation, comparison and automatic continuation train-only across every
version. The existing precommitted one-follow-up Research Loop remains valid because it commits the
child before opening the root holdout and excludes holdout evidence from child context.

An explicit user may instead start a new Refine after reading a completed report. If its reason
uses prior sealed-holdout evidence, the exact evidence and overlapping bars are thereafter
development evidence: the child must validate on a non-overlapping untouched holdout or make no
fresh sealed-generalization claim. Reports and history retain the original result, but the runtime
must never silently relabel reused evidence as new validation.

### G3 — Golden Mainline

Category: core-flow acceptance.
Primary user action: complete and revisit one real research loop without reconstructing state
across pages.

G3 is one focused end-to-end acceptance path over existing surfaces:

`Data → Research → Compare → Analyze → Continue / Refine → History`

It verifies exact dataset, interval, candidate, comparison, version and attempt identities. It
does not create a new test matrix, page or release process.

### W2-lite — Evidence Focus

Category: interface enhancement.
Primary user action: ask the Agent to open the decisive retained evidence in the existing
workbench instead of manually reconstructing the navigation path.

W2-lite shares one typed selection/focus state across existing workbench surfaces:

- select a candidate;
- open the relevant Analysis or Report subsection;
- filter an existing trade/date range;
- locate maximum-drawdown evidence;
- open sealed-holdout evidence;
- compare with a source version.

The Agent returns a short action receipt and evidence reference. It cannot recalculate a metric,
mutate a completed Run, create an arbitrary chart or bypass a server-authorized command. These are
client presentation intents, not an eighth registered research tool.

### W3 — Robustness Surface

Category: core interface enhancement.
Primary user action: judge whether a candidate remains credible outside one favorable parameter
or training window.

W3 reuses authoritative stored evidence to show bounded cross-window consistency, cost sensitivity,
parameter-neighborhood stability and failure regions. It does not add a second optimizer or metric
path. If bounded parameter sampling is later required, the sampler proposes candidates while the
existing kernel remains the only evaluator.

### R1 — Typed Learning Trace

R1 lets the product retain experience without adding a chat archive or a new learning aggregate.
It derives one immutable `learning_trace_v1` artifact from existing Run events, decisions, tool
observations and authoritative outcomes.

The trace contains:

```text
Run and context digest
provider/model and tool-schema versions
approved objective and current phase
failed action fingerprint
error code, invalid field paths and allowed constraints
material correction delta
resolved | stopped | failed outcome
authoritative evidence references
```

The trace never contains API credentials, hidden reasoning, report prose, prior holdout metrics,
trades or unverified model self-critique.

Acceptance:

- a successful repair and an honest stop produce different typed outcomes;
- fresh restore verifies the artifact digest and referenced Run/tool identities;
- Retry retains the same pinned source trace while recording a new attempt outcome;
- malformed, truncated, cross-workspace or future-schema traces fail before cache publication;
- the original eight-question baseline can be replayed into the trace parser without mutation.

### R2 — Schema-Versioned Repair Memory

R2 retrieves a validator-proven repair before asking the model to rediscover it. Retrieval order is:

1. exact tool version and failed-action fingerprint;
2. exact tool version, error code and invalid-field set;
3. an activated R4 Repair Policy.

Only a correction that passed the authoritative tool contract and reached its declared outcome can
enter Repair Memory. Every entry retains source Run IDs, success/failure counts, last validation
time, tool/model compatibility and explicit invalidation conditions.

Acceptance:

- a known repair hit does not repeat the stored invalid call;
- incompatible tool-schema versions never retrieve the repair;
- conflicting repairs lower confidence and remain examples rather than becoming policy;
- an unknown error still follows the bounded repair/stop path;
- repair retrieval changes no quantitative metric, strategy identity or holdout rule.

R1/R2-lite stops here for the current roadmap. Research-method memory, policy promotion and model
optimization remain deferred R3–R5 packages.

### D1 — Connector Contract

D1 adds one approved read-only external source only after a demonstrated data gap. A connector
returns untrusted raw records into the existing import boundary; native validation, normalization,
dataset identity and research eligibility remain authoritative.

The first contract is deliberately narrow:

- fixed provider identity and allowlisted endpoints;
- explicit symbol, interval and bounded range;
- source request/version evidence and applicable data-use terms;
- no account, order, Broker, supplier metric or arbitrary query surface;
- canonical dataset creation before the Research Agent can use the data.

MCP may implement the isolated connector process, but it does not become an eighth Research Agent
tool and cannot return authoritative Sharpe, ranking or strategy decisions.

### E0 — Evidence Export

E0 exports retained research evidence without recalculation. It extends the existing report/export
path with a versioned machine-readable bundle containing dataset identity, plan, candidates,
comparison, selected result, stored curves/trades, validation, series lineage and declared
limitations.

The server serializes authoritative snapshots and artifacts. The client does not rebuild metrics,
and E0 does not introduce a second report surface.

### V1 — Live Connector → Evidence Proof

Category: core-flow acceptance.
Primary user action: take one real connector dataset through the complete retained research loop
and reopen the same evidence without a fixture or identity substitution.

V1 reuses D1, the existing DeepSeek worker, W1–W3, E0 and the golden-path browser procedure. It
does not add a provider, page, tool, model role or metric. The bounded proof is:

`Kraken BTCUSD 4h → Catalog/Preview → Research → A/B → C or legal stop → Compare/Analyze/Report → E0 JSON → History reopen`

Acceptance:

1. Mock fallback is disabled and the exact provider/model outcome is recorded.
2. Connector request digest, dataset/record digest, runtime/split identity, candidate identity,
   report selection and export digest remain consistent through history reopen.
3. The current uncommitted provider bar never enters research evidence.
4. A provider or Agent failure stops honestly and still produces sanitized terminal evidence; the
   proof does not require a profitable result.
5. Any retained UI captures and the sanitized machine-readable evidence state exactly which parts
   are live and make no alpha or production-reliability claim.

Retained result: **Passed on 2026-07-24 through `A/B → C → decision`.** Kraken supplied 548
closed BTCUSD `4h` bars and the current uncommitted bar was dropped. DeepSeek `deepseek-v4-flash`
ran with Mock fallback disabled. Three experiments ran: A `sma_crossover_20_100`, B `breakout_20`,
and C `sma_crossover_50_200`. The first Candidate C create call was rejected once with
`ITERATION_REPLAN_TEMPLATE_RELATION_INVALID`; the next model turn received the exact rejected
arguments, changed only `replan_decision.action` to `switch_approved_family`, and succeeded,
producing a durable `quant-learning-trace-v1` whose `correction_delta` contains only that action.
Candidate C was backtested and included in a second train-only comparison; the final training
ranking was C, B, A. Because C produced zero training trades, the structured `research_decision`
selected B `breakout_20` via `robustness_override` / `minimum_trade_evidence` while referencing C.
B then failed sealed holdout validation and recommended `revise_research`. Current and historical
reads retained equal dataset, Run, runtime/split, selected-candidate and E0 identities. An earlier
rerun exposed a P1: strict action-only repair was impossible because the rejected arguments were
not in model context; the fix exposes only the correctly bound rejected call arguments for pending
typed repair while the runner remains fail-closed. The verifier now rejects a plain A/B completion
and accepts only strict A/B/C or a comparison-bound legal structured stop.

### S0-lite — Strategy Scope Contract

Category: core-flow correctness.
Primary user action: know before execution whether Qurio can research the requested hypothesis
faithfully, approximate it only through an explicit bounded proxy, or cannot support it.

S0-lite extends the existing plan contract and Research Setup/Plan Review. It does not add a
strategy family, SDK, page, tool or model. A closed scope decision is one of:

```text
supported       exact request fits the approved registered templates
bounded_proxy   a named, user-visible simplification fits the templates
unsupported     execution must stop before any experiment or holdout
```

Acceptance:

1. Ten to twelve frozen scope probes include supported SMA/RSI/breakout questions plus MACD with
   filters, shorting, continuous sizing and multi-asset requests.
2. `unsupported` creates zero experiments, zero quantitative comparison and zero holdout.
3. `bounded_proxy` names the omitted behavior and requires explicit plan approval.
4. Supported questions retain the existing seven-tool action sequence and authoritative evaluator.
5. One dominant repeated unsupported pattern may justify one later registered template; several
   heterogeneous causal strategy gaps are required before S0 can reconsider E1.

Implementation result:

- Twelve frozen probes cover three supported goals, three named bounded proxies and six
  unsupported strategy shapes.
- Scope identity is retained through the plan artifact, Run context, Retry/series descendants,
  snapshot, restore and E0 export. Unsupported scope retains no quantitative evidence.
- Public market command hydration only narrows server-authoritative legal commands. It never
  recreates approval from lifecycle state.
- Plan-external candidate creation returns a coupled template/parameter typed repair. A complete
  correction persists one resolved learning trace across fresh Store restore; a partial correction
  terminates without a second tool execution.
- The one-Agent, seven-tool and single-evaluator boundaries are unchanged.

### R3 — Train-Only Research Method Memory

R3 learns procedures, not alpha. It projects normalized observations from current and eligible
same-evidence training results, such as:

- `insufficient_trades`;
- `worse_drawdown`;
- `no_benchmark_edge`;
- `parameter_instability`;
- `canonical_duplicate`;
- `insufficient_budget`.

The memory may suggest one already-legal action—refine approved parameters, switch to another
approved family or stop—but it cannot copy winning parameters, inject a prior report conclusion,
expand the plan or use any sealed-holdout/generalization payload.

Acceptance:

- the recalled method cites compatible source Runs and training evidence classes;
- Candidate C remains feedback-linked and canonical-distinct;
- objective adherence and within-budget terminal rate improve or remain unchanged on the frozen
  evaluation set;
- current and prior sealed-holdout leakage violations equal zero;
- incompatible dataset/runtime/objective contexts do not retrieve the method.

### R4 — Policy Promotion and Frozen Evals

R4 turns repeated verified experience into a reversible policy lifecycle:

```text
eligible traces
  → draft repair or research-method policy
  → frozen offline evaluation
  → shadow execution
  → explicit activation
  → monitored version
  → retain | roll back | retire
```

Initial promotion requires at least three comparable independent engineering Runs, including
failures, and zero regression on the frozen scenario matrix. A policy stores applicability,
prohibited evidence, source traces, evaluation results, version and rollback target. It cannot add
tools, permissions, packages, strategy families or execution budget.

Research Playbook drafts in Section 7 use this lifecycle. One successful backtest never produces an
active Playbook.

### R5 — Offline Model Optimization

R5 is not approved for immediate implementation. It becomes eligible only when R1–R4 have a
sufficient corpus of verified repair pairs and full trajectories, frozen evaluations are stable,
and retrieval/policy improvements have plateaued.

Permitted experiments are offline supervised fine-tuning of invalid-to-valid tool calls and bounded
preference/reinforcement optimization for contract adherence, efficient repair and honest stopping.
Research sealed-holdout content is categorically excluded from the training corpus. Every candidate
model must replay old engineering scenarios, run the full frozen evaluation and retain a rollback
model. A frozen model-engineering evaluation item is retired and replaced before release if its
content was exposed during training or tuning.

Online per-Run weight updates, autonomous prompt rewriting and self-approved model promotion remain
prohibited.

## 6. Conditional professional expansion

Programmable expansion is not scheduled work. S0 reviewed the completed mainline, W2-lite, W3,
R1/R2-lite, D1 and E0 evidence and found no demonstrated need for arbitrary strategy code.
Expansion remains deferred until retained scope probes show that valuable approved research
questions cannot fit registered templates. Expansion decisions are ordered by how much of the
current runtime they can honestly reuse:

| Capability | Current architecture reuse | Relative difficulty | Entry gate | Decision |
|---|---:|---:|---|---|
| Constrained Python strategy research | High | Medium-high | E0 complete and an explicit product decision that approved research cannot fit registered templates | Preferred first programmable expansion |
| Agent-authored strategy changes | High after the SDK | High | SDK isolation, tests and identity are stable | Add only as a bounded mode |
| Small fixed-frequency portfolios | Medium | High | Single-asset semantics and SDK are stable | Separate later package |
| Narrow tabular ML research | Medium-low | Very high | Point-in-time data and leakage tests are proven | Conditional specialist package |
| Options research | Low | Very high | Dedicated data and derivatives-domain discovery | Separate product decision |
| High-frequency research | Near zero | Extreme | Requires a different event, simulation and infrastructure stack | Outside the foreseeable roadmap |

This order is a product constraint, not only an engineering estimate. Serving professional
programmers is adjacent to the current intent-to-evidence loop; options and high frequency solve
materially different jobs and should not distort the present product or interface.

### S0 / E1 — constrained Python Strategy SDK

S0's current decision is **no-go / defer**. E1 begins only after a later explicit decision backed
by retained Strategy Scope evidence that approved research questions cannot fit registered
templates. If that gate changes, E1 extends the existing evidence path rather than installing a
second backtest engine or exposing unrestricted Python.

The first SDK contract should contain:

```python
class QuantStrategy:
    parameter_schema = {...}

    def generate_target_positions(self, bars, parameters):
        ...
```

Required boundaries:

- a typed causal bar input in which each decision sees only history available at that timestamp,
  enforced by incremental execution or prefix-invariance/future-perturbation tests;
- an initial Long/Cash `{0, 1}` target-position output; continuous sizing waits for an
  authoritative rebalancing, turnover and partial-position contract;
- a declared parameter schema and stable code-plus-parameter canonical identity;
- a locked, versioned dependency environment;
- isolated execution with CPU, memory, wall-time and output limits;
- no network, shell, package installation or unrestricted filesystem access by default;
- deterministic fixtures and strategy unit tests before backtest eligibility;
- one authoritative fees, slippage, backtest, comparison, walk-forward and holdout path;
- Project/Run/Continue/Retry lineage retains the exact strategy-code version and evidence.

Do not add a public strategy DSL. Natural language, parameter controls and the Python SDK cover the
two useful interaction levels without requiring users to learn another proprietary language.

### E2 — code-capable Research Agent

After the SDK is stable, the Research Agent may gain a bounded professional mode:

```text
understand strategy workspace
  → propose executable research plan
  → patch one constrained strategy implementation
  → run unit tests
  → run authoritative backtest
  → inspect failure or comparison
  → revise within budget
  → freeze selection and evaluate holdout
```

This is the useful analogy to Codex, Claude Code or another coding Agent. The Agent acts on a typed
strategy workspace and quantitative tools, not a general local shell. Any new code tool must be
approved as a demonstrated research capability gap; the current seven-tool Agent remains unchanged
until S0 explicitly approves E1.

### E3 — bounded portfolio research

Portfolio support starts only after the strategy SDK and single-asset semantics are stable. The
first boundary is fixed-frequency target weights over a small synchronized asset set, not a broad
institutional portfolio system.

Required work includes synchronized calendars and missing data, cash and holdings accounting,
corporate actions, currencies, rebalancing, leverage and margin assumptions, portfolio transaction
costs, benchmark attribution, turnover and risk exposure. All decisive portfolio metrics need one
authoritative calculation path before the Agent can optimize or explain them.

### E4 — narrow ML research adapter

If an explicit later product decision approves ML research, begin with point-in-time tabular bar
features, a small supported model set and leakage-resistant time-series validation. Require
feature, label, dataset, code, model and random-seed identities; purged/embargoed splits where
applicable; and the same final strategy-level comparison and sealed holdout.

Do not begin with arbitrary PyTorch projects, GPU orchestration, AutoML, online inference or a
general feature store. A full ML-alpha platform is a separate product category.

### Separate-product boundaries

- **Options** require historical chains, expiries, exercise/assignment, Greeks, volatility surfaces,
  multi-leg semantics, margin, liquidity and specialist data. Treat this as a separate later
  product decision, not another strategy template.
- **High frequency** requires tick/order-book data, queue and matching semantics, partial fills,
  cancellation, microsecond event ordering, latency and market-impact models. It is not compatible
  with the current bar-based architecture and is outside the foreseeable roadmap.
- **Institutional platform work** such as team collaboration, permissions, entitlements and broker
  operations cannot be inferred from a successful single-user research loop.

## 7. Research Playbook lifecycle

Research Playbooks are the only recommended form of Hermes-like procedural skill learning for
Qurio. They follow R4's draft, frozen-evaluation, shadow, activation and rollback lifecycle.
They are not approved for implementation until R0–R3 are complete and repeated compatible
engineering Runs show the same bounded method.

### Why generic automatic skills are deferred

A generic personal agent can safely retain a procedural instruction such as how to operate a tool.
A quantitative research agent cannot treat one successful backtest as a reusable skill without
risking overfit, evidence leakage and a second methodology path. Automatic skill creation would be
performative rather than useful until repeated comparable research exists.

### Draft shape

```yaml
name: BTC 4h drawdown-controlled trend research
applies_to:
  market: crypto
  interval: 4h
required_data:
  calendar: 24x7
  timezone: UTC
candidate_families:
  - sma_crossover
  - breakout
comparison_objective: drawdown_control
validation:
  walk_forward_required: true
  sealed_holdout_once: true
known_failures:
  - zero_trade_candidate
  - excessive_turnover
source_runs:
  - run-id-1
status: draft
```

### Promotion rules

1. Require at least three comparable independent research versions and include failures, not only
   winners.
2. Never promote specific winning parameters as a default answer.
3. Generate a draft only; an authorized reviewer must approve activation.
4. Shadow-evaluate the draft against retained scenarios before promotion.
5. Every use reruns the authoritative kernel and validation path.
6. The draft cannot add code, tools, packages, network access or runtime permissions.
7. Version, disable and roll back playbooks independently.

If portability later becomes a real need, a reviewed Playbook may export to a compatible skills
document format. Qurio runtime semantics remain the closed internal contracts; it must not
depend on Hermes or a public skill marketplace.

## 8. Explicit non-goals

Do not add the following to make the product appear more agentic:

- multiple user-visible Agents or LLM debate;
- an LLM critic replacing deterministic comparison;
- unrestricted code, shell or package installation outside the conditional Strategy SDK boundary;
- automatic tool creation or an eighth tool without a demonstrated research gap;
- prompt self-modification;
- unlimited candidate or version loops;
- a generic Skill marketplace;
- broad MCP/tool integration without a concrete data or research job;
- automatic trading, Broker workflows or risk overrides;
- an Agent Builder, user-created Agent fleet, deployment model, replay session, position/order
  ledger or simulated fill surface;
- relabeling backtest or validation evidence as live, paper or replay trading performance;
- a freeform canvas, IDE or transcript-first chat product.

## 9. Verification strategy

### Scenario matrix

The retained P16–R0 baseline continues to cover objective adherence, plan enforcement, train-only
A/B → C adaptation, canonical novelty, retry/restore identity, bounded repair, legal terminal
states and real-provider `4h`/`1D` execution. It is regression coverage, not the current mainline
completion gate.

The closed mainline gate verifies:

1. **D0-lite:** the existing Data page creates, previews and selects valid `1h`, `4h` and `1D`
   market-v2 data with production-compatible identities and counts.
2. **W1-lite:** plan approval shows the minimum Research Contract, and completed or legally stopped
   Runs show the authoritative A/B → Observation → C/Stop → Final Decision Ledger.
3. **G1:** research eligibility differs truthfully by supported interval and usable coverage;
   insufficient data remains stored and previewable but cannot start research.
4. **G2:** an automatic child receives no prior holdout evidence; an explicit holdout-informed
   Refine is marked development evidence and cannot reuse overlapping bars as fresh sealed
   validation.
5. **G3:** one focused Data → Research → Compare → Analyze → Continue / History flow retains exact
   dataset, interval, candidate, comparison, version and attempt identities.

The completed R1/R2-lite gate also verifies:

6. A successful correction and an honest stop produce distinct, digest-verified learning traces.
7. A compatible known repair is reused while an incompatible tool-schema version is ignored.

Deferred R3/R4 adds only after explicit activation:

8. Research-method memory uses only normalized train evidence and never automatic prior holdout.
9. A promoted policy passes frozen and shadow evaluation, then survives activation and rollback.

### Product metrics

- **Objective Adherence Rate:** approved comparison objective equals the authoritative ranking rule.
- **Novel Candidate Rate:** share of created candidates that are canonical-distinct.
- **Duplicate Experiment Avoidance:** eligible repeats prevented before backtesting.
- **Evidence Completion Rate:** initiated Runs that produce an inspectable final comparison.
- **Agent Repair Success Rate:** recoverable experiment failures resolved within budget.
- **Within-Budget Terminal Rate:** initiated Runs that complete or stop legally before budget
  exhaustion.
- **Equivalent Invalid Repeat Rate:** invalid action fingerprints executed more than once; target
  is zero.
- **Known Repair Reuse Rate:** compatible known failures resolved without repeating the stored
  invalid action.
- **Learning Trace Coverage:** eligible repair and stop outcomes with a valid typed trace.
- **Policy Non-Regression Rate:** frozen scenarios preserved by an activated policy.
- **Evidence Leakage Violations:** raw or automatic current/prior sealed-holdout content entering
  Agent context, memory or learning without the explicit G2 development-evidence transition;
  target is zero.
- **Research Iteration Rate:** terminal results that lead to a meaningful Continue / Refine.
- **Cost per Completed Evidence Run:** provider cost for one complete, inspectable research result.

### Package gates

For an active mainline package:

- run only the affected contract/runtime/API or frontend tests;
- run one focused Playwright golden path when a primary action changes;
- run typecheck or build only when the changed layer requires it;
- run `git diff --check`;
- perform a short P0/P1 semantic review before advancing;
- stop when the primary action is truthful and green.

Broad lint matrices, secondary viewport permutations, provenance/audit polish, rare-input coverage,
frozen-evaluation reports and real-provider reruns are deferred unless the package changes that
specific boundary or a P0/P1 failure requires them.

## 10. Definitions of complete

### Agent-native v0.1

P16–P19 complete the v0.1 method and persistence semantics. The product must not describe that loop
as operationally reliable under real-provider execution until R0 also passes its frozen
eight-question regression.

Qurio may call the Agent-native v0.1 research loop complete when:

1. the approved plan controls strategy families, comparison objective and bounded completion;
2. Agent decisions are rebuilt from compact durable state and existing registered tools;
3. one evidence-driven candidate adjustment uses only training evidence;
4. structured Research Memory prevents repeated work without leaking current or prior holdout as
   new evidence;
5. final selection follows the approved objective or carries a server-verified robustness override;
6. one sealed holdout occurs only after selection is frozen;
7. Continue / Refine and Retry preserve their distinct version/attempt identities;
8. report, export and history retain the exact evidence and decision basis;
9. real DeepSeek 4h and 1D flows pass with Mock fallback disabled;
10. no new page, model, tool or dependency was added merely to imitate a general agent framework.

At that point the truthful product statement is:

> Qurio understands a bounded research goal, forms an executable plan, uses quantitative
> tools, adapts one experiment from training evidence, avoids repeated work through structured
> research memory, and completes a conclusion within deterministic validation boundaries.

### W4-lite Workspace Legibility

W4-lite is complete when a researcher opening the existing Workspace can identify the approved plan,
latest material observation, decisive evidence and one legal next research action without reading raw
events. Completion does not authorize a new Agent surface, trading simulation, replay, deployment
model or further visual-polish cycle.

### Continual-learning foundation

The continual-learning foundation is complete when:

1. every repairable tool failure produces a typed learning trace;
2. the same validated repair can be reused across compatible Runs without repeating the invalid
   call;
3. incompatible or stale memories fail closed;
4. train-only research-method memory improves or preserves objective adherence and terminal rate on
   the frozen evaluation set;
5. policy promotion requires repeated evidence, shadow evaluation, explicit activation and a
   working rollback;
6. no raw current or prior sealed-holdout payload enters automatic Agent context, learning trace or
   training corpus; an explicit G2 qualitative reason remains marked development evidence and is
   excluded from learning;
7. all eight frozen real-provider questions reach a terminal state within the unchanged budget;
8. the learning plane adds no second metric path, new strategy identity or hidden execution
   permission;
9. every activated policy and model version is attributable to source traces and evaluation
   results;
10. R5 remains optional: the product can continuously improve through verified memory and policies
    without changing model weights.

At that point the truthful continual-learning statement is:

> Qurio improves from validator-backed research experience: it reuses proven tool repairs and
> bounded research procedures, measures every promotion against frozen evaluations, and preserves
> evidence isolation, versioning and rollback.

## 11. External design reference

Hermes Agent's public Skills System is a useful reference for progressive disclosure, explicit
skill lifecycle and agent-managed procedural documents:

- <https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md>
- <https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/work-with-skills.md>

Qurio borrows only those lifecycle ideas for a possible future reviewed Research Playbook. It
does not adopt generic automatic skill promotion, self-modifying prompts or Hermes runtime
dependencies.
