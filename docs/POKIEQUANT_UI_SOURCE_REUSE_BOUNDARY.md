# Qurio UI Source Reuse Boundary

Status: executable UI reuse plan and merge boundary

Verified: 2026-07-18 (Asia/Shanghai)

Owner: Qurio product/design/frontend

PokieQuant below refers to the repository and inherited implementation paths; Qurio is the
current product and UI brand.

## 1. Purpose and authority

This document answers four implementation questions for the PokieQuant desktop UI:

1. Which external products or repositories may inform each surface?
2. Which source, package, visual pattern, or interaction may actually be reused?
3. Where does that reuse land in the current React/Tauri codebase?
4. What evidence and tests are required before the change can merge?

It specializes, but does not replace, the repository-wide rules in:

- [`POKIEQUANT_REFERENCE_AUDIT.md`](./POKIEQUANT_REFERENCE_AUDIT.md)
- [`REUSE_MATRIX.md`](./REUSE_MATRIX.md)
- [`POKIEQUANT_REUSE_LEDGER.md`](./POKIEQUANT_REUSE_LEDGER.md)
- [`QUALITY_GATES.md`](./QUALITY_GATES.md)

If this document conflicts with a stricter repository-wide license, provenance, security, or data-rights rule, the stricter rule wins.

## 2. Current implementation baseline

Qurio is not a blank frontend. The production desktop surface is a React 18 + Vite + Tauri application with a first-party component package, resizable panels, API-owned snapshots, and typed Quant domain contracts.

| Area | Current authority | Boundary |
| --- | --- | --- |
| App shell and dependencies | `apps/mac/package.json` | Keep React 18, Vite, Tauri, `@glint/ui`, `cmdk`, and `react-resizable-panels`. |
| Workspace composition | `apps/mac/src/features/quant/QuantWorkspace.tsx` | Refactor incrementally; do not replace the shell with an external application. |
| Domain truth | `apps/mac/src/quant-domain.ts` | External components never define Run, Dataset, Artifact, Plan, or Event state. |
| Presentation projection | `apps/mac/src/features/quant/quant-presentation.ts` | Add pure adapters/view models here or in focused sibling modules. |
| Visual system | `packages/ui/src/index.tsx`, `apps/mac/src/features/quant/quant-workspace.css` | All reused patterns must be rendered in the PokieQuant component vocabulary and tokens. |

The current UI already owns `QuantSidebar`, `QuantPlanRail`, `QuantRunMonitor`, `QuantActivityFeed`, `QuantMarketWorkspace`, `QuantStrategyReport`, `QuantDataPage`, `QuantGoalComposer`, and `QuantInspector`. External references improve these components; they do not replace the domain or shell.

## 3. Reuse classes

Every UI reference must be assigned exactly one class before implementation.

| Class | Allowed | Not allowed | Required evidence |
| --- | --- | --- | --- |
| **A — First-party reuse** | Refactor inherited/current PokieQuant code with history preserved | Copying a parallel implementation that bypasses existing contracts | Source and destination paths, regression tests, diff review |
| **B — Reviewed package dependency** | Install an exact package artifact and call its public API | Floating ranges, vendoring package source, silent notice removal | Exact version, registry integrity, license, lockfile, notices, advisories, bundle/tests |
| **C — Selected source migration** | Copy a small named file/function from a permissively licensed fixed commit | Repository-wide copying, unrecorded snippets, EE/custom paths | Immutable commit, exact source/destination paths, license, notices, modification record, reviewer |
| **D — Independent pattern reimplementation** | Study public behavior/source, then implement against PokieQuant contracts and design tokens | Line-by-line translation, copied CSS/assets/copy, source-shaped state model | Fixed reference, written concept boundary, original tests and component API |
| **E — Product reference only** | Information architecture, workflow, density, generic interaction conventions | Source, assets, logos, proprietary copy, pixel-identical protected expression | Public product/docs URL and explicit prohibited list |
| **F — Blocked** | Discussion and recorded non-use only | Package, snippet, source, generated reproduction, vendoring | Blocking reason and owner decision required to reopen |

Default rule: use **B** for small headless/rendering libraries and **D** for full applications. **C** is exceptional and requires a separate, file-level approval row before code is copied.

## 4. Master source reuse boundary

### 4.1 Open-source code references

| Reference and fixed evidence | Stack / coupling | PokieQuant target | Decision | Permitted use | Prohibited use |
| --- | --- | --- | --- | --- | --- |
| [FreqUI `41e172b…`](https://github.com/freqtrade/frequi/tree/41e172bce297ada23359a2e700941b88e1f7865f), [Backtesting route](https://github.com/freqtrade/frequi/blob/41e172bce297ada23359a2e700941b88e1f7865f/src/router/index.ts), [GPL-3.0](https://github.com/freqtrade/frequi/blob/41e172bce297ada23359a2e700941b88e1f7865f/LICENSE) | Vue 3, Nuxt UI, Pinia, ECharts, TanStack Vue Table; incompatible framework plus copyleft license | Market workspace, backtest configuration, trades/results comparison | **F — blocked for code; D — pattern only** | Study backtest flow, result hierarchy, chart/trade linkage, history selection, comparison behavior | No `.vue`, store, CSS, copy, assets, or generated translation in PokieQuant core |
| [Langfuse `1cb1bbc…`](https://github.com/langfuse/langfuse/tree/1cb1bbcf6b269fd887a6667796f1a15417cca336), [TraceTree](https://github.com/langfuse/langfuse/blob/1cb1bbcf6b269fd887a6667796f1a15417cca336/web/src/components/trace/components/TraceTree.tsx), [license boundary](https://github.com/langfuse/langfuse/blob/1cb1bbcf6b269fd887a6667796f1a15417cca336/LICENSE) | React 19/Next 16, Radix, TanStack, tRPC, app contexts; OSS outside `ee/`, `web/src/ee/`, `worker/src/ee/` | Trace tree, step details, token/cost/latency presentation | **D — independent reimplementation** | Reuse tree/row/detail responsibility split, virtualization concept, selection/collapse behavior, duration/cost heat cues | No EE paths; no Next/tRPC/server model; no direct `TraceTree` copy in this phase |
| [Dagster `3c0b7f1…`](https://github.com/dagster-io/dagster/tree/3c0b7f1c323c6714375bb04471f21c493c72a3ef), [RunTimeline](https://github.com/dagster-io/dagster/blob/3c0b7f1c323c6714375bb04471f21c493c72a3ef/js_modules/ui-core/src/runs/RunTimeline.tsx), [Apache-2.0](https://github.com/dagster-io/dagster/blob/3c0b7f1c323c6714375bb04471f21c493c72a3ef/LICENSE) | React plus Dagster UI components, GraphQL/domain types, repository/job assumptions | Plan Rail, Run Monitor, Runs timeline | **D — independent reimplementation** | Reuse status semantics, 32px dense timeline concept, grouping, virtualization, elapsed-time and retry disclosure patterns | No Dagster UI package import, GraphQL types, repository/sensor/schedule semantics, CSS modules, or source copy without a new C-row |
| [OpenMetadata `be446ea…`](https://github.com/open-metadata/OpenMetadata/tree/be446ea09cd5b07e220be9a83b82ccf7b9b7bcaa), [TableDetailsPageV1](https://github.com/open-metadata/OpenMetadata/blob/be446ea09cd5b07e220be9a83b82ccf7b9b7bcaa/openmetadata-ui/src/main/resources/ui/src/pages/TableDetailsPageV1/TableDetailsPageV1.tsx), [Apache-2.0](https://github.com/open-metadata/OpenMetadata/blob/be446ea09cd5b07e220be9a83b82ccf7b9b7bcaa/LICENSE) | React 18, Ant Design, React Flow/G6, large generated schema and governance backend | Data registry/detail, quality, provenance, lineage | **D — independent reimplementation** | Reuse asset header/tab anatomy, schema/quality/provenance grouping, upstream/downstream vocabulary | No Ant Design or OpenMetadata UI package; no owner/team/governance system; no source copy without a new C-row |
| [Aim `6e098e3…`](https://github.com/aimhubio/aim/tree/6e098e38065364c76b2bb7c028f266e53b647642), [Runs page](https://github.com/aimhubio/aim/blob/6e098e38065364c76b2bb7c028f266e53b647642/aim/web/ui/src/pages/Runs/Runs.tsx), [Apache-2.0](https://github.com/aimhubio/aim/blob/6e098e38065364c76b2bb7c028f266e53b647642/LICENSE) | React 17, MUI 4, Highcharts/Plotly, old routing/styling stack | Runs table, dynamic metric columns, baseline comparison | **D — independent reimplementation** | Reuse query/filter/compare workflow, selected-run action bar, baseline and metric grouping concepts | No MUI/Highcharts/Plotly stack import; no old store/model migration; no source copy without a new C-row |
| [OpenHands `11d4ecf…`](https://github.com/OpenHands/OpenHands/tree/11d4ecf21fc144d10a614ddba63b84de5c90bfd4), [CustomChatInput](https://github.com/OpenHands/OpenHands/blob/11d4ecf21fc144d10a614ddba63b84de5c90bfd4/frontend/src/components/features/chat/custom-chat-input.tsx), [license boundary](https://github.com/OpenHands/OpenHands/blob/11d4ecf21fc144d10a614ddba63b84de5c90bfd4/LICENSE) | React 19, HeroUI, Zustand, sandbox/conversation assumptions; MIT outside `enterprise/` | Goal Composer, submission states, resize and keyboard behavior | **D — independent reimplementation** | Reuse separation of input logic, resizing, actions, submission and focus handling | No `enterprise/`; no sandbox/conversation/file-tree domain; no HeroUI import; no direct source copy in this phase |
| [TradingView Lightweight Charts `871d2dd…`](https://github.com/tradingview/lightweight-charts/tree/871d2dd42d989f41aeecbfb05f19b14e0d825fce), [Apache-2.0](https://github.com/tradingview/lightweight-charts/blob/871d2dd42d989f41aeecbfb05f19b14e0d825fce/LICENSE), [NOTICE](https://github.com/tradingview/lightweight-charts/blob/871d2dd42d989f41aeecbfb05f19b14e0d825fce/NOTICE) | Small TypeScript Canvas package; package declares `5.2.0` and depends on `fancy-canvas` | Candlestick/equity/volume rendering candidate | **B candidate — not selected** | May enter a dedicated dependency decision against the already reviewed ECharts path | No install, source copy, TradingView branding, or claim of implementation before selection, exact artifact verification, notices and tests |

### 4.2 Closed-source/product references

| Product reference | PokieQuant target | Decision | Permitted | Prohibited |
| --- | --- | --- | --- | --- |
| OpenBB Workspace | Shell, dashboard hierarchy, contextual AI over visible widgets | **E — product reference only** | Public IA, widget/dashboard concepts, density and context behavior | Core Workspace source, assets, logo, exact copy, proprietary components; OpenBB confirms the core Workspace is proprietary |
| QuantConnect Cloud UI | Projects directory, backtest result organization, report/orders/trades/logs tabs | **E — product reference only** | Public workflow and information grouping | Cloud frontend source/assets; LEAN engine openness does not authorize Cloud UI copying |
| TradingView application | Symbol/interval toolbar, financial chart interaction conventions | **E — product reference only** | Generic chart controls, crosshair/time-range concepts | App source, branded colors, drawings, proprietary widgets, logo or exact visual clone |
| Codex/Claude-class agent consoles | Ask/Plan/Auto clarity, persistent task status, cancel/retry/review | **E — product reference only** | Generic mode and task-state conventions | Product source, unique copy, icons, branding or internal permission implementation |

The OpenBB Open Data Platform, OpenBB integration examples, and QuantConnect LEAN engine are separate open-source surfaces. They do not change the product-reference-only boundary for the Workspace and Cloud UIs.

## 5. Dependency decision boundary

The UI phase must not introduce a second component system. Package reuse is limited to headless behavior or specialized rendering.

| Dependency | Current repository decision | UI use | Rule |
| --- | --- | --- | --- |
| `@glint/ui` | Existing first-party package | Buttons, badges, statuses and future shared primitives | Extend first; do not bypass with another design system |
| Icon dependency | Not installed | None | Prefer text/native controls; add an icon package only for a demonstrated interaction gap |
| `react-resizable-panels` | Existing dependency | Shell/workbench resizing | Preserve current implementation |
| `@tanstack/react-table@8.21.3` | Approved exact artifact in `REUSE_MATRIX.md`; not automatically installed in each workspace | Projects, Runs and Data tables | Add only in a dependency slice with exact pin, lockfile and relevant tests |
| `echarts@6.1.0` | Approved proposal with explicit pre-install gate | General market/report charts | Default Phase 1 chart path unless a later decision explicitly replaces it |
| `lightweight-charts@5.2.0` | Candidate only; not selected | Specialized financial chart alternative | Mutually exclusive decision against the ECharts market-chart path; requires audit/ADR-style decision before install |
| Radix, Ant Design, MUI, HeroUI, Nuxt UI | Not selected | None | Do not add to reproduce reference applications |
| Highcharts/Plotly | Not selected | None | Do not add for Aim-like comparison; use the selected chart stack |

## 6. Component-level implementation map

| Work item | Current/future PokieQuant target | Reference responsibility | Reuse class | Required view model / seam | Acceptance |
| --- | --- | --- | --- | --- | --- |
| App shell and sidebar | `QuantWorkspace.tsx`, `QuantSidebar.tsx` | OpenBB shell hierarchy | A + E | `QuantNavDestination`, recent-project projection | One active location; no Run history tree in global nav; keyboard/focus preserved |
| Projects directory | new `QuantProjectsPage.tsx` | QuantConnect project directory + common dense-table conventions | A + E + optional B table | `QuantProjectRow` | Search/filter/sort, whole-row open, truthful empty/loading/error states |
| Runs directory | new `QuantRunsPage.tsx` | Aim run explorer + Dagster status density | D + optional B table | `QuantRunRow`, `QuantRunComparison` | Status filters, dynamic metric columns, selection/compare, immutable attempts |
| Run trace tree | new `QuantTraceTree.tsx`, integrate in `QuantActivity.tsx` | Langfuse tree/row/detail split | D | `buildQuantTraceTree(events)` | Collapse/select, virtualize when needed, tool/model/event details, no hidden chain of thought |
| Plan Rail | `QuantPlanRail.tsx` | Dagster step status/elapsed/retry conventions | A + D | `QuantPlanStepPresentation` | Pending/active/waiting/completed/failed/skipped all distinct; legal recovery only |
| Run Monitor | `QuantActivity.tsx` | Dagster timeline and Langfuse cost/duration metadata | A + D | `QuantRunMonitorPresentation` | Live polling state, budgets, model/runtime metadata, terminal immutability |
| Market Evidence | `QuantMarketWorkspace.tsx` | FreqUI workflow + selected chart package | D + B | `QuantEvidenceSeries` | Real data projection, interval boundaries, no fabricated values, tooltip tests |
| Strategy Report | `QuantStrategyReport.tsx` | QuantConnect/QuantStats information hierarchy; Aim comparison | A + D + E | `QuantReportPresentation`, `QuantCandidateComparison` | Overview/generalization/experiments/trades/robustness/logs with non-duplicated failure status |
| Data registry/detail | `QuantDataPage.tsx`, future `QuantDataDetail.tsx` | OpenMetadata asset detail anatomy | A + D + optional B table | `QuantDatasetRow`, `QuantDatasetDetailPresentation` | Quality/provenance/version/eligibility/used-by-runs; blocked data cannot start research |
| Goal Composer | `QuantGoalComposer.tsx` plus focused hooks/components | OpenHands input responsibility split + OpenBB contextual Agent concept | A + D + E | Existing `QuantCommand` and dataset selection | Ask/Plan/Auto, budget fields, resize, submit/disabled/loading/error, keyboard/focus tests |
| Inspector | `QuantInspector.tsx` | Langfuse metadata detail + OpenMetadata provenance | A + D | Existing inspect-target union extended only when needed | Never empty for a valid target; exact IDs/digests only in advanced disclosure |

## 7. Required adapter boundary

External repository types must never enter `QuantWorkspace.tsx` or API contracts. Add small pure adapters that consume existing PokieQuant domain objects:

```ts
buildQuantTraceTree(events: QuantRunEvent[]): QuantTraceNode[]
presentQuantRunRows(snapshot: QuantWorkspaceSnapshot): QuantRunRow[]
presentQuantRunComparison(runs: QuantResearchRun[]): QuantRunComparison
presentQuantDatasetDetail(dataset: DatasetSnapshot): QuantDatasetDetailPresentation
presentQuantEvidenceSeries(snapshot: QuantWorkspaceSnapshot): QuantEvidenceSeries
```

Rules:

- API snapshots/events remain the only business truth.
- UI timers may animate or poll; they may not invent state transitions.
- Reference-specific names such as Trace, Span, Asset, Materialization, Experiment, Bot, or Conversation are translated only where the PokieQuant domain has an equivalent.
- Raw provider prompts, chain of thought, secrets, unredacted payloads, or unavailable financial data must not be projected.
- Adapters are pure, typed and unit-tested before their visual component is integrated.

## 8. Visual consistency boundary

Reference projects provide task structure, not parallel visual systems.

All implementation slices must:

- use the existing system-sans typography and PokieQuant tokens;
- prefer text/native controls and the canonical Qurio brand assets; do not add a decorative icon system;
- use one button, badge, tab, input, table and drawer vocabulary;
- keep accent color for primary actions, selection and state;
- preserve compact desktop density and visible keyboard focus;
- implement default, hover, focus, active, disabled, loading and error states;
- avoid copied CSS, logos, screenshots, illustrations, fonts and unique product copy;
- avoid a generic KPI-card dashboard when a table, chart, timeline or report is the task surface.

## 9. Codex execution plan

### Slice 0 — Boundary and evidence

- Keep this file and the repository-wide reuse audit linked.
- For every later source/package change, add a fixed commit/version and source-to-target row before implementation.
- Do not download entire external repositories into the product tree.

Exit gate: no ambiguous `copy`, `reuse`, or `inspired by` claim remains; each reference has one class.

### Slice 1 — Shared presentation primitives

- Add/extend first-party table, status, tabs, empty state and disclosure primitives in `@glint/ui` only when reused by at least two surfaces.
- Add pure Run/Dataset/Trace presentation types.
- Add focused unit tests.

Exit gate: Projects, Runs and Data can share one table/status vocabulary without another component framework.

### Slice 2 — Projects and Runs directories

- Replace the current single-project/single-run projections with real directory components backed by API data.
- Add search, filtering, sorting, row navigation and compare selection.
- Keep full evidence in a page/workbench, not a quick drawer.

Exit gate: directory states are API-owned, keyboard accessible and covered by component/E2E tests.

### Slice 3 — Plan, Trace and Run Monitor

- Implement original `QuantTraceTree` from `QuantRunEvent[]`.
- Refine `QuantPlanRail` and `QuantRunMonitor` status/elapsed/recovery behavior.
- Use virtualization only after measured row volume justifies it.

Exit gate: one Run can be understood from plan to individual event without exposing private reasoning or fabricated activity.

### Slice 4 — Data registry and detail

- Implement registry rows and dataset detail presentation.
- Add Overview, Quality, Provenance, Versions and Used by Runs.
- Keep lineage simple until real upstream/downstream relations exist.

Exit gate: a user can decide whether a dataset is research-ready and understand why a dataset is blocked.

### Slice 5 — Market Evidence and Strategy Report

- Execute the already documented ECharts dependency gate, or first approve an explicit replacement decision for Lightweight Charts.
- Render candlestick/equity/volume/boundaries from real snapshot data.
- Reorganize report tabs and candidate/baseline comparison.

Exit gate: chart and report show the same immutable Run/dataset evidence and do not duplicate or contradict validation status.

### Slice 6 — Composer, Inspector and design QA

- Split `QuantGoalComposer` responsibilities without changing legal command semantics.
- Ensure Inspector is populated for Run, event, artifact, report and dataset targets.
- Capture source references and implementation at the same viewport/state; compare together and fix visible mismatches.
- Run lint, typecheck, unit, build, Playwright, accessibility, license and notice gates.

Exit gate: main workflow is functional end to end and all dependency/source evidence is current.

## 10. Merge gate

Reject a UI change when any of the following is true:

1. It copies FreqUI or another GPL/custom/unknown source into PokieQuant core.
2. It imports code from Langfuse EE paths or OpenHands `enterprise/`.
3. It adds an external UI framework to make one reference component easier to copy.
4. It adds a package without an exact version, lockfile, license evidence, notices and advisory review.
5. It translates a third-party component line by line but labels the result “independent”.
6. It imports external domain/store/API types into PokieQuant UI contracts.
7. It copies protected branding, icons, fonts, screenshots, CSS or unique copy.
8. It invents Run, Dataset, Artifact, validation, token, cost or market values in the frontend.
9. It removes existing authenticity, provenance, quality or legal-command constraints.
10. It claims a reference is integrated when only screenshots or source reading occurred.

## 11. File-level migration ledger template

No current external UI source migration is approved. If a future slice proposes class **C**, add one row per copied file or cohesive function before copying:

| Status | Source repo | Fixed commit | Source path/symbol | Destination path/symbol | License path | Why package/pattern reuse is insufficient | Modifications | Notices | Tests | Reviewer/date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pending | — | — | — | — | — | — | — | — | — | — |

An approval for one file does not authorize sibling files, CSS, assets, generated code, dependencies or future upstream versions.

## 12. Current decision summary

- Keep the existing PokieQuant React/Tauri shell and domain contracts.
- Use external full applications as behavior and information-architecture references, not embedded products.
- Keep FreqUI blocked for code reuse.
- Reimplement Langfuse, Dagster, OpenMetadata, Aim and OpenHands patterns independently against PokieQuant view models.
- Prefer the already reviewed TanStack Table and ECharts dependency paths when their implementation slices satisfy existing gates.
- Keep Lightweight Charts as an unselected alternative until an explicit chart-stack decision replaces or rejects the ECharts path.
- Do not add a second design system or icon family.
- Require a file-level ledger before any external UI source is copied.
