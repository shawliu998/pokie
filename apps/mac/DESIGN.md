---
name: Qurio
description: An AI-native desktop workbench for autonomous quantitative research and strategy analysis.
colors:
  canvas: "#101114"
  surface: "#1a1a1f"
  surface-elevated: "#1d1d22"
  surface-subtle: "#151518"
  border: "#2c2c33"
  border-strong: "#3a3a42"
  text: "#f3f4f7"
  text-muted: "#b5b7bf"
  text-faint: "#92949d"
  primary: "#2145f5"
  info: "#4dacdb"
  positive: "#38b487"
  warning: "#e1a93e"
  danger: "#e36a75"
  focus: "#5c78ff"
typography:
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif"
    fontSize: "1.538462rem"
    fontWeight: 650
    lineHeight: "2rem"
    letterSpacing: "-0.01em"
  section:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif"
    fontSize: "1.076923rem"
    fontWeight: 600
    lineHeight: "1.538462rem"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: "1.384615rem"
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI, sans-serif"
    fontSize: "0.884615rem"
    fontWeight: 500
    lineHeight: "1.230769rem"
  mono:
    fontFamily: "SF Mono, ui-monospace, Menlo, Monaco, Consolas, monospace"
    fontSize: "0.884615rem"
    fontWeight: 400
    lineHeight: "1.230769rem"
rounded:
  control: "4px"
  panel: "6px"
  overlay: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "6px 12px"
    height: "32px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "6px 12px"
    height: "32px"
  input:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "6px 10px"
    height: "32px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "12px"
---

# Design System: Qurio

## Overview

**Creative North Star: “The AI-native Quantitative Research Workbench”**

Qurio is a dark Mac desktop workspace shaped around sustained analytical work. It uses a restrained neutral hierarchy, compact native typography, familiar financial charts, research tables and controls, and small areas of semantic color. The interface should disappear behind the task: define a market question, watch the Agent test it, compare strategies and understand the result.

This system rejects generic AI-dashboard grammar. It does not decorate every state with an icon, repeat one conclusion across several cards, or treat internal orchestration events as primary content. The Workspace leads with research context, comparative evidence and next decisions; the autonomous Research Agent is legible through concise plan, experiment and observation states, never through a trading-terminal or chat-first shell. Dense information is welcome when it supports market analysis and strategy comparison; provenance, safety boundaries and advanced configuration use progressive disclosure.

Key characteristics:

- Desktop-first density with stable alignment and tabular numerals.
- One decisive hierarchy: research question, comparative result, next action, then implementation detail.
- Flat tonal layers separated mainly by one-pixel borders.
- Semantic color reserved for actions, selection, focus, and actual status.
- Standard controls with complete hover, focus, active, disabled, loading, and error states.

## Brand assets

Qurio is the only current product and UI brand. PokieQuant remains a repository and implementation-history name only.

Canonical product assets:

- `public/brand/qurio-icon-color.svg` — the flat navy-and-blue Q icon used for favicon and application packaging.
- `public/brand/qurio-wordmark.svg` — navy wordmark for light backgrounds.
- `public/brand/qurio-wordmark-inverse.svg` — identical wordmark geometry in the light-on-dark product-shell colorway.

Do not use a raster wordmark as a source, reconstruct the name with a font, restore PokieQuant-named brand files to `public/brand`, or introduce another Q geometry. Detailed usage rules live in [`public/brand/README.md`](./public/brand/README.md).

## Colors

The palette is a graphite research environment with one electric-blue action color and quiet semantic status colors.

### Primary

- **Research Blue** (`#2145f5`): primary actions and committed selections only.
- **Evidence Blue** (`#4dacdb`): informational links and secondary evidence emphasis.

### Neutral

- **Night Canvas** (`#101114`): application background and input wells.
- **Workbench Surface** (`#1a1a1f`): primary content panels.
- **Raised Workbench** (`#1d1d22`): selected rows and structurally elevated regions.
- **Quiet Surface** (`#151518`): sidebars, headers, and secondary layers.
- **Primary Ink** (`#f3f4f7`): headings and decisive values.
- **Muted Ink** (`#b5b7bf`): supporting copy.
- **Faint Ink** (`#92949d`): metadata that still meets its required contrast target.
- **Divider** (`#2c2c33`) and **Strong Divider** (`#3a3a42`): structural separation.

### Named Rules

**The Evidence Color Rule.** Green, amber, and red describe evidence state only; they never decorate navigation, headings, or arbitrary cards.

## Typography

**Display Font:** SF Pro Text through the native system stack
**Body Font:** SF Pro Text through the native system stack
**Label/Mono Font:** SF Mono through a standard monospace stack

The system uses one native sans family so typography remains familiar and compact. Weight, spacing, alignment, and numeric formatting establish hierarchy rather than dramatic scale changes.

### Hierarchy

- **Title** (650, `1.538462rem`, `2rem`): page and project titles only.
- **Section** (600, `1.076923rem`, `1.538462rem`): panel and report headings.
- **Body** (400, `1rem`, `1.384615rem`): instructions and decision copy, capped near 70 characters where prose is continuous.
- **Table** (400, `0.961538rem`): comparison and directory tables with tabular numerals.
- **Label** (500, `0.884615rem`, normal case): field names, state labels, metadata, and controls.
- **Metric** (600, `1.307692rem`): important numeric evidence, never a decorative hero number.

### Named Rules

**The Normal Case Rule.** Labels and headings use sentence case without wide tracking or repeated uppercase eyebrows.

## Elevation

Qurio is flat by default. Depth comes from tonal layering and one-pixel structural borders. Shadows are reserved for overlays such as the inspector, toast, dialog, or command surface; ordinary cards and buttons have no ambient shadow.

### Named Rules

**The Structural Depth Rule.** If a border or background layer can explain containment, do not add a shadow.

## Components

### Product surface priority

When capability is incomplete, build in this order:

1. Market and strategy visualization: price, equity, benchmark, drawdown and trade context.
2. Experiment comparison: sortable candidates, parameters, metrics and selection.
3. Research operation: objective composer, approved Agent plan, material experiment progress, evidence-led observation and user decisions.
4. Data and history: datasets, imports, filters, runs and report retrieval.
5. Provenance, audit, policy and rare error detail.

This is the general surface hierarchy. The repository's explicit current delivery order and
mainline completion gate override it for named packages such as D0-lite, W1-lite, G1 and G2.

Do not substitute safety copy, metadata cards, status rails or Agent logs for a missing quantitative surface. Do not polish secondary states while the primary page lacks the controls and visualizations expected of a financial research workbench.

### Buttons

- **Shape:** compact rectangle with a `4px` radius and a `32px` default height.
- **Primary:** Research Blue background, Primary Ink text, used once per decision area.
- **Hover / Focus:** brighter blue on hover; `2px` Focus Blue outline on keyboard focus; one-pixel active translation; no glow.
- **Secondary:** Workbench Surface with Strong Divider border.
- **Disabled / Loading:** neutral disabled surface with readable Faint Ink; labels describe the current operation.

### Chips

- **Style:** compact status or authenticity labels with minimal `2–4px` radius.
- **State:** status text accompanies color; chips do not serve as decoration.

### Cards / Containers

- **Corner Style:** `4–6px` depending on control or panel role.
- **Background:** Workbench Surface or Quiet Surface.
- **Shadow Strategy:** none at rest.
- **Border:** one-pixel Divider; avoid nested bordered cards.
- **Internal Padding:** normally `12–16px`, tighter in tables and dense monitors.

### Inputs / Fields

- **Style:** Night Canvas, Strong Divider border, `4px` radius, native typography.
- **Focus:** Focus Blue border and visible outline.
- **Error / Disabled:** semantic error copy associated with the field; disabled state remains readable and explains why where needed.

### Navigation

Side navigation uses 32px rows, a quiet tonal selected state, and no decorative icons where text is sufficient. Workspace and report tabs use a two-pixel bottom indicator, keyboard arrow navigation, and sentence-case labels.

### Research tables

- Use the `quant-research-table` class for comparable research evidence, datasets, experiments, and trades.
- Table headers are 40px high; data rows are 48px high. Cells use 12px horizontal padding and one-pixel dividers.
- Apply `is-numeric` to numeric columns and `is-action` to the final action/status column. Numeric values use tabular figures and align right.
- Hover uses Quiet Surface; selection uses Raised Workbench. Do not add colored rails, row icons, pills, or zebra striping unless the value itself carries a semantic status.
- Keep a real caption. Visually hide it only when the surrounding heading already names the table.

### Evaluation Path

The four-stage Training → Walk-forward → Sealed holdout → Promotion sequence is a compact text structure used only where the complete decision chain is necessary. It uses separators and status words rather than connected dots or a timeline illustration.

### Page frames

- **Workbench:** Overview uses the full available canvas. Charts, comparison tables and result analysis own the primary area; a narrower Copilot column explains and controls the research.
- **Directory and composer:** Data and New research use the same two-column utility frame when the inspector or preflight context is useful; the secondary column disappears below the desktop breakpoint.
- **Wide utility:** Runs uses the shared 44px utility header and one uninterrupted content column, capped at 1440px. It never reserves an empty Copilot column.
- **Reading utility:** Settings uses the same header and a centered 900px content sheet. Its narrower width is deliberate for label/value scanning, not a generic page constraint.
- **Paper utility:** Paper Trading uses one wide uninterrupted column. Account state, research handoff, order review and positions stay on this page; no live-trading or deployment controls appear.
- Page width follows the task. Do not force directory, master-detail, workspace, and settings surfaces into one universal maximum width.

### Research workspace layout boundary

- Preserve the current navigation + main work area + right rail structure. Do not add a fixed second left rail or a fourth Context column.
- Put research-series context in a compact strip at the top of the main work area when it materially helps the current decision. The strip may identify the source version, selected candidate and current objective; it must not become a metadata panel.
- The right rail may evolve into Research Copilot, but its primary structure is **Current research / Material observation / Next legal research action** derived from retained state. Chat is a secondary interaction inside that rail, not the page shell or the research record.
- Do not introduce an Agent console, deployment drawer, replay monitor, live position surface or independent Activity page. The independent Paper Trading destination may show only its simulation account, drafts, fills and positions; Agent activity explains a Run only when it changes a research decision.
- At 1440, keep the existing main + right-rail two-column workbench. At 1024, stack or collapse the rail so the main research evidence remains readable without document-level horizontal scrolling.

### Information hierarchy by page

- **Workspace:** question and market context → leading result → charts and comparisons → approved plan / material Agent observation / next action → audit detail.
- **New research:** market scope → objective → research mode and constraints → start action. Validation policy is supporting copy, not a feature panel.
- **Live run:** material research phase → current experiment and finding → legal research action → detailed event log.
- **Decision:** conclusion → comparative metrics → equity and drawdown → trades and robustness → limitations.
- **Data:** searchable catalog → coverage and quality → selection/import action → retained metadata.
- **History:** searchable/filterable runs → state and key outcome → open run. Audit identifiers stay inside details.
- **Settings:** current connection → current Run's pinned provider/model → packaged local-runtime controls → policy. Internal compatibility and the source-build fallback are secondary.
- **First-launch recovery:** offer the same familiar provider/model inputs before the manual endpoint fields. The recovery sheet must remain vertically scrollable on a 1200×760 viewport.

## Do's and Don'ts

### Do:

- **Do** lead completed-run surfaces with the research question, leading candidate, comparative result and one next action.
- **Do** show the market context and evaluation period where it changes interpretation.
- **Do** keep provenance and advanced settings one progressive-disclosure level below primary work.
- **Do** use standard desktop controls and preserve keyboard-visible focus.
- **Do** use `#2145f5` sparingly for primary actions and current selection.

### Don't:

- **Don't** assemble pages from repeated bordered cards, decorative icons, gradients, oversized copy, or chat surfaces without a task.
- **Don't** use colored side stripes, connected green-dot timelines, or repeated success badges.
- **Don't** expose every internal Agent event as equal-weight interface content.
- **Don't** let validation terminology dominate screens intended for strategy analysis.
- **Don't** fabricate strategy equity curves from market close data.
- **Don't** add an interaction pattern when it does not serve Qurio's autonomous research lifecycle.
