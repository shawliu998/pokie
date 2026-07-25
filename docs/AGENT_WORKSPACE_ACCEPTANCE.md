# Agent Workspace UI PR 1 Acceptance

> Historical record only. The Glint Investigation workspace and its dedicated
> browser-fixture variants are retired from the supported PokieQuant product
> route. Their focused E2E contract was removed rather than skipped or adapted
> to the Quant workspace; current browser acceptance is recorded in the
> PokieQuant capability inventory.

Date: 2026-07-16
Branch: `codex/phase31-agent-workspace-ui`
Base: `codex/phase31-pr0-scope-cleanup`

## Product Design

Investigation detail is now organized as one Agent Workspace rather than five peer tabs. The default screen presents the Decision Question, business status, research mode, approved scope, egress boundary, configured budget limit, discrete plan, current action, human gate, governed artifacts, and Run Inspector in one workflow.

The design preserves Glint’s existing workbench navigation, list/detail hierarchy, typography, tokens, dark-mode variables, focus treatment, and restrained macOS density. It adds only a low-motion active-step pulse and disables it under reduced-motion preferences.

Evidence, finding, and synthesis review contracts remain unchanged. The Action Center enters the existing review panels; UI PR 2 will replace those transitional panels with dedicated three-column review workspaces.

## Current Capability Mapping

| UI behavior | Real capability/data |
| --- | --- |
| Ready goal and scope | Existing `Investigation` plus frozen ScopeVersion projection |
| Start investigation | Existing `POST /research-runs` contract against the exact draft Investigation and ScopeVersion |
| Preparing/Running/Waiting/Completed status | Existing `ResearchRun.state` plus pending review artifacts |
| Plan steps | Existing graph-node/event meanings projected through `agent-presentation.ts` |
| Scope summary | Existing source connection IDs, content version IDs, and time range |
| Budget | Existing maximum cost/duration only; used cost is deliberately not rendered |
| Model egress | Existing `allowCloudModel`, generation method, provider, and model metadata |
| Activity | Safe `RunEvent` projection; unknown events degrade to generic copy |
| Evidence proposal card | Existing Evidence record and immutable ContentVersion relationship |
| Finding proposal card | Existing Claim/ClaimVersion projection and Evidence links |
| Review evidence | Existing Source Viewer plus `Valid`, `Weak`, and `Reject` EvidenceReview operations |
| Review findings | Existing `Verify` and `Reject` Claim review operations |
| Synthesis handoff | Existing create/revise/verify/reject Synthesis operations |
| Decision Brief handoff | Existing verified Synthesis → Decision Brief creation/open behavior |
| Inspector Advanced data | Existing Run/Scope IDs, graph version, sequence, trace, prompt refs, and internal node mapping |

No UI behavior claims hybrid retrieval, web search, source-scope expansion, sub-agents, automatic review, automatic Decision Ready, publication, or tool use.

## Components

- `AgentWorkspace`: session composition, compact segments, and transition into existing review panels.
- `AgentHeader`: goal, truthful status, mode, scope, egress, budget limit, and valid controls.
- `AgentPlanRail`: Agent/System/Human ownership, discrete step state, artifact counts, and human-gate emphasis.
- `AgentActivityFeed`: current action plus safe, chronological activity projection.
- `AgentActionCenter`: Start, review, retry, and waiting/failure actions only when real state permits them.
- `AgentArtifactCard`: consistent Scope, Evidence, Finding, Synthesis, and Decision Brief previews without default UUID display.
- `AgentInspector`: run context and closed Advanced provenance.
- `agent-presentation.ts`: pure domain/event-to-product projection used by every component.

## States

Accepted fixture states:

- `agent-ready`: frozen goal/scope, expected plan, Start action, compact navigation, and `R` start behavior.
- `agent-running`: current step, safe activity, Cancel, no review action, and no percentage progress.
- `agent-waiting-review`: completed proposal steps, explicit Evidence human gate, Action Center, and proposal cards.
- `agent-completed`: completed plan, verified synthesis, Decision Brief artifact, and Open handoff.

Presentation-model tests also cover needs-input, failed, cancelled, Findings review, Synthesis review, model-assisted mode, unknown events, no fake cost, and no fake percentage progress.

## Verification

Passed:

```text
pnpm lint
pnpm typecheck
pnpm test                         18 files · 77 tests
pnpm build                        Vite production build
GLINT_E2E_API_MODE=fixture pnpm test:e2e
                                   2 passed · 2 intentionally skipped
The four historical Agent Workspace fixture captures passed when this record
was written. Those commands and variants are no longer part of the runnable
product contract.
./scripts/verify_phase2.sh
./scripts/verify_phase3_quality.sh
./scripts/verify_tauri_runtime.sh
git diff --check
```

`verify_phase2.sh` passed every required layer. Its optional live-network smoke was skipped because `GLINT_ENABLE_LIVE_SMOKE=1` was not authorized; fixture/API, Compose, native runtime, security, contract, integration, and collected-owner-loop layers passed. Rust audit emitted only repository-allowed maintenance/unsoundness warnings and passed its configured policy.

## Visual Acceptance

All four images are 1440×960, captured from the real React Workbench and fixture API, with no developer tools or Terminal. Each visibly carries `Imported Demo Fixture` and the Investigation authenticity label.

- Ready: `docs/assets/agent/glint-agent-ready.png`
- Running: `docs/assets/agent/glint-agent-running.png`
- Waiting Review: `docs/assets/agent/glint-agent-review.png`
- Completed: `docs/assets/agent/glint-agent-complete.png`

The before/after QA comparison confirmed that the redesign keeps the original navigation/list hierarchy while making goal, current step, approved scope, human gate, proposal state, and Decision Brief handoff simultaneously scannable.

## Ten-second Comprehension Check

The accepted Waiting Review screenshot answers:

1. Goal: prioritize permission preview for enterprise teams.
2. Current step: Review evidence.
3. Scope: three approved sources and twelve immutable content versions.
4. Model use: deterministic research; no model egress.
5. Required action: review one Evidence proposal.
6. Proposal state: Evidence and Finding cards are marked Needs review.
7. Next artifact path: reviewed findings → synthesis → Decision Brief in the Plan.

## Known Gaps

- Evidence and Finding review still use the existing review panels after Agent Workspace entry; the dedicated queue/detail/source and finding/evidence-map layouts are not in UI PR 1.
- Synthesis still uses the current Executive Summary, Business Implications, and Limitations UI; it is not yet the structured Synthesis Workspace.
- Contextual Agent commands beyond the existing global palette are reserved for UI PR 3.
- The default Run Inspector is implemented; item-selected Source/Evidence/Finding/Synthesis/Decision inspector modes are deferred with the review workspaces.
- Pre-run budget is not displayed when the current frontend Investigation projection has no ResearchRun budget. The UI does not fabricate it from fixture knowledge.
- No unsupported clarification response, request-more-evidence, wrong-stance, duplicate, not-independent, automatic approval, or publication control is rendered.

## Next UI PR

UI PR 2 should implement `EvidenceReviewWorkspace`, immutable Source Viewer composition, `FindingReviewWorkspace`, and the Evidence Map while preserving the current review DTOs and only activating Valid/Weak/Reject plus Verify/Reject. It should add queue navigation, J/K/Enter/E/F/Command+Enter/Escape behavior, focused component tests, and E2E from immutable-source open through finding verification.
