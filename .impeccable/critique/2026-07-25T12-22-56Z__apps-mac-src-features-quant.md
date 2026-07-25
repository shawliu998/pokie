---
target: Qurio 全页面 AI 味与产品合理性审查
total_score: 19
p0_count: 1
p1_count: 1
timestamp: 2026-07-25T12-22-56Z
slug: apps-mac-src-features-quant
---
# Qurio UI critique

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of system status | 1 | “Research completed” conflicts with holdout pending and final decision unavailable. |
| 2 | Match system / real world | 2 | Digest, schema and policy often precede the market judgment users need. |
| 3 | User control and freedom | 3 | History, filters, previews and return paths are generally clear. |
| 4 | Consistency and standards | 2 | Main workbench and utility pages have inconsistent density and framing. |
| 5 | Error prevention | 0 | Paper Trading can become eligible without an authoritative sealed decision. |
| 6 | Recognition rather than recall | 2 | History/version meaning must be reconstructed across the table and right rail. |
| 7 | Flexibility and efficiency | 3 | Comparison, search and primary navigation are efficient. |
| 8 | Aesthetic and minimalist design | 1 | Repeated rounded panels and static governance rails add template-like weight. |
| 9 | Error recovery | 3 | Pending and failure copy is honest and usually offers a next step. |
| 10 | Help and documentation | 2 | Help frequently explains boundaries rather than advancing the current task. |
| **Total** | | **19/40** | **Needs focused correction** |

## Anti-Patterns Verdict

Qurio does not look like a wholesale AI-generated interface. Its charts, quantitative metrics, tables and bounded research composer are task-specific. The AI tell is the framing: repeated dark rounded cards, a fixed Current / Observation / Next rail, and policy text that repeats system control rather than helping the next research decision.

The deterministic scan reported five raw findings and four unique findings: two valid `bounce-easing` hits in `apps/mac/src/styles.css:9` and `apps/mac/src/features/quant/quant-workspace.css:2292`; one valid `side-tab` card accent in `apps/mac/src/styles.css:74`; and one boundary/false-positive navigation selection indicator in `apps/mac/src/styles.css:5`.

No visual overlay was injected. Browser checks covered Workspace, New research, Data, History and Paper Trading: no document-level horizontal overflow at tested desktop widths and no console warnings/errors.

## Overall Impression

The product already reads as a real quantitative research workspace, not a chat demo. Its largest opportunity is to make every page answer a research question before it explains governance, and to derive all “completed/eligible” states from one authoritative decision projection.

## What’s Working

- Strategy-versus-benchmark charts and metrics establish evidence-first hierarchy.
- History behaves like a research catalog rather than an activity feed.
- New research stays a structured objective-to-plan workflow instead of becoming a generic chat shell.

## Priority Issues

### P0 — Paper Trading can bypass sealed-holdout eligibility

`QuantPaperTradingPage.tsx` treats `run.state === "completed" && selectedCandidate !== null` as eligible even when the decision surface says sealed holdout is pending.

Fix: derive eligibility from the authoritative final-decision/holdout projection in both UI and draft creation; disable with an exact reason and an “Open decision” action.

Suggested command: `$impeccable harden`

### P1 — “Execution completed” is presented as “research completed”

Workspace, Decision and Paper Trading expose conflicting meanings of completion. This undermines trust in the core product contract.

Fix: introduce one shared terminal-state projection such as “Experiments complete — validation pending”; reserve “Research complete” for an available sealed decision.

Suggested command: `$impeccable clarify`

### P2 — Data prioritizes audit identity over market fitness

Digest, schema and provenance dominate the right rail while coverage, quality and price-path evidence are less prominent.

Fix: default the rail to selected-dataset coverage/quality and preview; move digest/schema behind “Open metadata record”.

Suggested command: `$impeccable distill`

### P2 — New research preflight behaves like a static policy template

The rail repeats Dataset / Quality / Validation / Holdout / Promotion before the objective exists, so much of it cannot respond to the current decision.

Fix: compress the initial state to dataset quality and sufficiency; reveal goal/range-specific preflight only after plan generation.

Suggested command: `$impeccable clarify`

### P2 — Rounded panels and overshoot motion create avoidable template character

Quant shell radii drift above the documented institutional 4–6px system, result areas are split into nested cards, and buttons use overshoot easing.

Fix: scope controls/panels to 4–8px, group evidence with spacing and rules, remove card side accents, and replace overshoot with restrained easing.

Suggested command: `$impeccable quieter`

## Persona Red Flags

- Quant expert: will interpret a paper draft without sealed validation as a broken research boundary, not a cosmetic inconsistency.
- Python-capable solo quant: will ask why Data leads with digest/schema instead of interval coverage, gaps, price path and hypothesis fitness.
- Cautious independent researcher: will doubt that Completed, Pending and Unavailable come from one authoritative calculation path.

## Minor Observations

- Brand rendering appears inconsistent across screenshots even though the sidebar source loads the same wordmark; verify capture/runtime behavior before changing the asset.
- Settings foregrounds API URL and workspace UUID; these read as diagnostics rather than daily research controls.
- The Paper Trading “no live route” boundary is valid but visually louder than source run, candidate and validation state.
- The active navigation border is a detector boundary case; the action-card side stripe is the actual conflict with Qurio’s own no-colored-rails rule.

## Questions to Consider

- Should Paper Trading require a sealed final decision, or explicitly support unvalidated sandbox drafts as a different product contract?
- Should Qurio’s tone be a restrained institutional research terminal, or a more expressive AI workspace?
- Should the next pass fix only the P0/P1 contract problems, or also remove the repeated governance rails and nested-card framing?
