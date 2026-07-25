# PokieQuant Agent Constraints

These instructions apply to the whole repository. Read `apps/mac/PRODUCT.md`, `apps/mac/DESIGN.md` and `docs/POKIEQUANT_CAPABILITY_INVENTORY.md` before planning product or UI work.

## Product priority

Qurio is an AI-native quantitative research workspace powered by one verifiable autonomous
Research Agent. The primary user loop is:

`select retained market data -> define a bounded research objective -> approve an Agent plan -> observe experiments and evidence-led adaptation -> compare and validate candidates -> conclude, refine or revisit history`

Current priority is **mainline completion**, followed by targeted interface capability parity. The
mainline is complete only when one retained dataset can move through Data → Research → Compare →
Analyze → Continue / History with authoritative evidence and no holdout leakage. Visual fidelity,
interaction polish, backend breadth, audit polish and rare edge cases follow after that gate.

## Research direction constraints

- The Workspace is the product surface. The single autonomous Research Agent powers approved planning, bounded experimentation, evidence-led adaptation and conclusion; it is not a separately configured, deployed or traded user object.
- Optimize the loop `Idea → Research → Candidate Experiments → Comparative Evidence → Conclusion → Continue / Refine`.
- Research Mission is a UX concept only. Do not add `ResearchMission`, `Question` or `Iteration` tables or contracts that duplicate the existing domain.
- Treat Project + root Run as the start of a research series, Continue / Refine as a new version, and Retry as another attempt of the same Run.
- Research Memory means structured lineage, versions, attempts and retained evidence; it is not chat history.
- Keep one Research Agent with specialized registered tools. Keep strategy identity in the existing `template + parameters + canonical key` contract; do not add a user-visible DSL or arbitrary Python.
- Do not add an Agent Builder, Agent marketplace, deployment model, replay session, position/order ledger, live/paper trading surface or Broker workflow. Visible Agent activity must remain structured research activity tied to an existing Run.
- Prioritize Research Series reuse before adding Library, a freeform canvas, an IDE, Broker workflows, a chat shell, a fourth fixed Context column or a broad collection of open-source surfaces.
- Add open-source code only for a demonstrated capability gap after checking license and architecture fit. Keep every decisive quantitative metric on one authoritative calculation path.

## Current delivery order

Finish the mainline before opening another product surface:

1. **D0-lite:** make market-v2 Add Data truthful for supported `1h`, `4h` and `1D` datasets.
2. **W1-lite:** expose the minimum Research Contract and Decision Ledger needed to understand the
   approved plan, A/B → Observation → C adaptation and final choice.
3. **Core correctness gate:** replace fixed-bar sufficiency assumptions with interval-aware rules
   and keep sealed holdout isolated across a Research Series.
4. **Golden mainline:** verify Data → Research → Compare → Analyze → Continue / History through one
   focused end-to-end path.

Only after that gate, execute enhancements in dependency order:

`W2-lite Evidence Focus → W3 Robustness → R1/R2-lite verified learning → D1 Connector → E0 Export → W4-lite Workspace Legibility → constrained SDK decision`

R3–R5, broad Skills/MCP ecosystems, Broker/live trading, portfolio/ML expansion, audit surfaces,
security hardening beyond the existing boundary and rare-edge polish remain deferred unless the
user explicitly changes priority.

Use multiple windows when it shortens the critical path, but keep one writer for each authoritative
file or contract path. Read-only preparation, independent review and tests may run in parallel.
Parallel writers require disjoint file ownership and frozen inputs; never concurrently edit shared
schemas, stores, snapshots, quantitative kernels or the same frontend domain projection.

## Mandatory planning rules

Before editing, classify the proposed work as one of:

1. Core interface capability
2. Core-flow correctness
3. Visual fidelity
4. Secondary reliability or accessibility
5. Audit, provenance, security or rare edge-case polish

Prefer the lowest-numbered unfinished category. Do not choose category 4 or 5 merely because it is easy to test while category 1 or 2 remains incomplete.
The explicit **Current delivery order** overrides the generic category ordering for the named
packages; in particular, do not pull W2-lite ahead of G1/G2 or the golden mainline.

For the active mainline, close P0/P1 blockers and the focused golden path, then stop. Record P2
polish without implementing it unless it blocks the primary loop.

Every UI task must name the primary user action it improves. If it does not materially help users start research, observe research, compare strategies, analyze results, manage data or revisit runs, treat it as out of scope unless the user explicitly requests it.

Before creating a page, component, API, fixture or interaction, check the capability inventory. Extend the named reusable asset when it is structurally suitable. Do not replace a working asset merely to achieve a different implementation style.

## Front-stage constraints

- The current product and UI brand is **Qurio**. PokieQuant is a repository and implementation-history name only. Product-facing UI, screenshots, packaging and new documentation must use the canonical assets in `apps/mac/public/brand/README.md`; do not recreate or restore an older logo or raster wordmark.
- Lead with market, strategy, experiment, comparison and result information.
- Treat local execution, immutability, digests, schemas, traces, attestations, validation policy and repair budgets as secondary detail.
- Do not repeat safety or reproducibility claims across primary pages.
- Agent conversation and logs support the workbench; approved plan, material observation and the next legal research action make the Agent legible without becoming a second surface.
- Do not use metadata panels, status rails or audit copy as substitutes for missing charts, tables, filters or actions.
- Do not add decorative icons, connected-dot timelines, colored side rails, repeated status badges, nested cards or large unexplained empty regions.
- Every visible control must work with live or fixture data, or be visibly disabled with an accurate reason.

## Reference and reuse

Reproduce proven information architecture, layout, interaction and component behavior from authorized competitor references when it fits the product. Use PokieQuant data, branding and implementation; respect third-party code licenses. Fidelity is judged by the complete screen and workflow, not by isolated decorative similarity.

## Stopping rules

- Do not continue micro-polishing focus, error copy, provenance or safety states after their core contract is covered by tests.
- Do not expand a focused mainline package into broad security, audit, provenance or rare-input
  coverage. Preserve existing boundaries and defer additional hardening.
- Do not broaden a bounded task into a design-system rewrite.
- Do not commit or push unless the user asks.
- After implementation, verify the affected workflow and report the next missing core capability rather than proposing another minor polish pass.
