# Agent Workspace Product Spec

Status: UI PR 1 implementation contract
Audience: Product Intelligence teams, product managers, design, frontend, and reviewers
Scope: Investigation detail presentation only; no new Agent backend capability

## Product outcome

An Investigation becomes one evidence-first Agent session. Within ten seconds, a user should be able to identify the decision question, approved scope, research mode, current step, pending human action, proposal status, and path to a Decision Brief.

Glint remains a Signal-to-Decision Agent, not a chat assistant or an autonomous web-research system. The UI organizes real Investigation, ResearchRun, RunEvent, Evidence, Claim, Synthesis, and Decision Brief state into a legible workspace without changing those domain objects.

## Users and jobs to be done

Primary users are product managers and Product Intelligence researchers who must turn a signal into a defensible decision artifact.

Their jobs are:

- When a Signal warrants investigation, define the decision question and understand exactly which immutable material Glint may use.
- While research is running, understand what Glint is doing and why without reading graph nodes or event payloads.
- When Glint pauses, see the smallest valid human action needed to continue the governed workflow.
- Before trusting a finding, distinguish proposals, reviewed evidence, human-reviewed findings, and verified synthesis.
- When the work is complete, hand a version-bound synthesis into a Decision Brief without losing provenance.

## Current experience audit

The existing Investigation detail is truthful but fragmented:

- Five peer tabs split goal, scope, run state, evidence, claims, synthesis, and raw events. Users must reconstruct the workflow themselves.
- The Overview shows a generic business timeline, but it does not identify the current action or place the human gate in the main path.
- Run state and user responsibility are separated between Overview, Runs, and Collaboration disclosure.
- Technical labels such as ClaimVersion, Graph version, exact IDs, SSE state, and raw event names have more prominence than the product task requires.
- Proposal status is present inside artifact tabs, but there is no single Action Center that explains what needs review now.
- The header exposes Investigation status and generation method, but not a compact scope, budget-limit, or egress summary.
- The layout is readable at 1440px, but its single wide detail column leaves substantial unused horizontal space and makes relationships between plan, activity, and selected context harder to scan.

Strengths to preserve:

- Immutable source references and explicit human approval boundaries are already represented.
- Model egress is opt-in per run.
- Existing source, evidence, claim, synthesis, and Decision Brief actions map to real API operations.
- Progressive disclosure already exists for technical provenance.
- The application-level Sidebar, Investigation list, native density, and restrained visual system are appropriate for Glint.

## Core product problems

1. Users cannot see Goal → Plan → Activity → Artifacts → Human Gates → Decision as one coherent session.
2. The current screen does not answer “What is Glint doing, why, and what does it need from me?” in one scan.
3. Product language and internal runtime language are mixed.
4. Proposal and verified states are locally correct but not consistently summarized.
5. Empty, waiting, completed, and safely failed states do not share one predictable workspace model.

## Design principles

### Agent-first, not chat-first

The workspace is an operational research surface. It shows a goal, bounded plan, activity projection, governed artifacts, and human gates. It never simulates a conversation or hidden reasoning.

### Truth before theater

Only discrete steps, persisted events, existing artifacts, configured limits, and real review actions may be shown. No invented retrieval, sub-agents, costs, tokens, progress percentages, or counter-evidence loops.

### Proposals remain proposals

Artifact origin and review status are independent. “Agent proposal,” “Verified evidence,” “Human-reviewed finding,” and “Decision artifact” are stable labels. Generation method never implies approval.

### Business language by default

The default workspace says “Preparing approved sources” and “Drafting findings.” Exact nodes, IDs, digests, prompt references, provider metadata, trace references, and sequence numbers remain in Advanced disclosure.

### Human gates are first-class

Evidence, finding, synthesis, and Decision Brief approval are visibly human-owned steps. Glint pauses rather than implying autonomous approval.

### Dense, native, accessible

The design preserves the existing macOS workbench density, keyboard operation, light/dark tokens, visible focus, and reduced-motion support. Color is reinforced by shape, text, and structure.

## Agent autonomy boundary

Glint can accept a Decision Question, bind a frozen Investigation Scope, run deterministic or policy-approved bounded model research, persist Evidence and Claim proposals, emit Run Events, wait for review, create synthesis from verified findings, create a Decision Brief from verified synthesis, and export a version-bound PRD Research Input through existing workflows.

Glint cannot perform hybrid retrieval, expand scope, search the internet, use Browser/Shell/MCP tools, ask multi-turn clarification questions, approve evidence or findings, approve synthesis, mark a brief Decision Ready, publish, create parallel agents, or execute a genuine counter-evidence loop. UI PR 1 does not add any of those capabilities.

## UI PR 1 scope

- Agent Workspace shell inside Investigation detail.
- Agent Header with goal, business status, mode, scope, limit, and valid controls.
- Plan Rail derived from real run state, artifacts, and human gates.
- Activity Feed derived from safe Run Events and persisted artifacts.
- Action Center for real, currently available actions.
- Unified artifact previews.
- Ready, Running, Waiting for Review, and Completed fixture states.
- Presentation-model unit tests, focused E2E coverage, and four real-app screenshots.

## Non-goals

- No backend graph, API, database, retrieval, review-policy, or model changes.
- No new global navigation destination.
- No new chat input or clarification response input.
- No three-column Evidence or Finding review workspace in UI PR 1.
- No Synthesis structure redesign in UI PR 1.
- No production fixture switcher.
- No disabled controls for unsupported future actions.

## Success measures

Qualitative acceptance is a ten-second comprehension check: a new viewer can answer the goal, current step, source scope, model use, pending human action, proposal status, and next Decision Brief step.

Implementation measures:

- 100% of displayed activity items map to a real Run Event or persisted artifact.
- 0 fabricated cost, token, source-count, progress-percentage, or tool-call values.
- All visible primary actions pass the same real state and policy gates as the existing workflow.
- Ready, Running, Waiting Review, and Completed states render deterministically from fixture data.
- Existing lint, typecheck, unit, build, Phase 2, Phase 3 quality, runtime, and relevant E2E gates remain green.
