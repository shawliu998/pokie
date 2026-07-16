# Implementation Plan

Verification date: 2026-07-16

This plan replaces broad phase sprawl with a narrow production path: validate contracts and risks, then ship the thinnest real vertical loop from Watchlist to evidence-backed Decision Brief.

## Product Boundary

Glint is an Intelligence Workbench for small product, market, and research teams. It is not a general chat assistant, BI dashboard, social publishing tool, or autonomous multi-agent demo.

Primary user for MVP: product manager responsible for competitor and user research.

First fixed output: evidence-backed Product Decision Brief. PRD Research Input is a version-bound Preview/Markdown export from one DecisionBriefVersion, not a second output object.

Core loop:

```text
Watchlist
→ GitHub / RSS / CSV
→ Content Processing
→ Explainable Signal
→ Investigation
→ Supporting / Counter Evidence
→ ClaimVersion
→ Human Review
→ Reviewed intermediate synthesis
→ Product Decision Brief
→ Version-bound PRD Research Input export
```

## Phase Sequence

Current execution state:

- Phase 0: accepted as the contract and risk baseline.
- Phase 1: deterministic local acceptance complete on 2026-07-16.
- Phase 2: deterministic connector/scheduler/collected-lineage acceptance complete on 2026-07-16; live GitHub/RSS smoke remains unexecuted by policy.
- Phase 3 and Phase 4: not accepted and not implied by the P1/P2 result.

The executable evidence and limitations are in [PHASE1_P2_ACCEPTANCE.md](./PHASE1_P2_ACCEPTANCE.md). This status does not claim production, pilot, or GA validation.

### Phase 0: Contracts And Risk Validation

Goal: create executable engineering baseline without business code.

Deliverables:

| Deliverable | Purpose | Exit gate |
|---|---|---|
| Reuse matrix | Upstream/license/version/security decisions | Blocked projects cannot enter code paths |
| Risk register | Top product, legal, security, data, and delivery risks | Owners and validation method assigned |
| Project structure | Monorepo boundaries without scaffolding | Supports Tauri/React, FastAPI, worker, contracts, tests, infra |
| Quality gates | Definition of done across design, code, data, runtime | Gates cover lint/type/unit/contract/integration/e2e/eval/security/license/performance |
| Seed dataset spec | Eval/demo fixture contract | Covers true positive, false positive, repost, counter-evidence, source failure, content version changes, prompt injection |
| Implementation plan | Sequenced delivery path | No production code until these contracts are reviewed |

Exit criteria:

1. License blockers are documented.
2. Seed fixture schema and labels are reviewed.
3. API/event/domain contracts are stable enough for walking skeleton.
4. No third-party source code has been copied.

### Phase 1: Thinnest Real Walking Skeleton

Goal: prove the vertical architecture with the smallest real path, not a full UI shell.

Acceptance status: deterministic local exit criteria accepted on 2026-07-16; see [P1/P2 acceptance](./PHASE1_P2_ACCEPTANCE.md).

Scope:

1. Tauri app shows only the connected Inbox → Investigation → Decision Brief path plus the minimum Monitoring setup needed for Seed/Imported CSV.
2. FastAPI modular monolith exposes real Workspace, Watchlist, ImportSession/TransferConsentRecord/terminal ImportManifest, Imported Dataset, ContentVersion, Signal, Investigation, ResearchRun, Evidence, immutable ClaimVersion/ClaimReview, synthesis/SynthesisReview, singly grounded DecisionBriefVersion/DecisionBriefReadinessReview and terminal BriefExport contracts.
3. The Mac parses a selected CSV locally, creates a metadata/digest-only ImportSession pinned to the SourceConnection pointer/version, records an append-only exact-scope upload consent, uploads through a short-lived object-scoped grant, and reports completion for server-side effective-consent/object verification. A dedicated ImportFinalizationJob is the only worker allowed the session ID; it parses/normalizes and atomically creates visible content plus an immutable ImportManifest with a compare-and-set source pointer, while failure/cancel creates no manifest and cleans staging. Downstream jobs consume only that terminal manifest ID and frozen ContentVersions, starting at dedupe and deterministic Signal detection rather than normalizing twice; they never receive an ImportSession ID or Mac filesystem path. A typed deterministic ResearchRun may propose Evidence/ClaimVersions/synthesis through the same Domain Service; data_authenticity, suggestion_origin and generation_method/version are explicit, and no Phase 1 output is presented as an LLM capability.
4. Human review, DecisionReady completeness, immutable version references and Markdown export are real domain behavior; there is no “research placeholder” or generic Deliverable.
5. SSE emits durable RunEvents with sequence, reset recovery and resumability.
6. Phase 1 includes real workspace scope/RLS, Owner operator membership, minimal AuditLog, idempotency, optimistic concurrency, secret redaction, seed eval smoke and prompt-injection fixtures. Full role collaboration and Audit/Evaluation UI remain Later.
7. UI clearly labels Seed, Imported and generated data; design-complete but disconnected pages are not built as clickable entrances.

Non-goals:

1. No social platform connectors.
2. No autonomous publishing.
3. No general chat home.
4. No LangGraph, model orchestration or autonomous Agent in Phase 1; the deterministic ResearchRun provider exercises the same domain contract without pretending to be model research.

Exit criteria:

1. One Watchlist produces one explainable Signal from Seed/CSV; the Owner PM creates an Investigation, completes one deterministic ResearchRun, reviews exact Evidence/ClaimVersions, verifies one InvestigationSynthesisVersion, marks its singly grounded DecisionBriefVersion DecisionReady and exports a version-bound Markdown PRD Research Input.
2. ContentVersion → Evidence → verified ClaimVersion → verified InvestigationSynthesisVersion → DecisionBriefVersion → DecisionBriefReadinessReview → BriefExport can be replayed without mutable-ID ambiguity.
3. All displayed data authenticity labels are correct; seed export cannot masquerade as real intelligence.
4. Contract, integration, one E2E, security and eval-smoke paths pass.
5. Runtime integrity is proven through local Docker Compose plus Tauri dev app.

### Phase 2: GitHub/RSS Continuous Collection

Goal: replace fixture-only input with real continuous collection for low-risk sources.

Acceptance status: deterministic contracts, fixtures, scheduler, collection, lineage, explanation and Compose Owner loop accepted on 2026-07-16. Live connector calls with real credentials remain a separate gate and were not run.

Scope:

1. GitHub connector: repositories, issues, discussions, releases where allowed by API and user config.
2. RSS connector: feeds, canonical URLs, content versions, source health.
3. Scheduler and worker collection runs with retry, rate-limit, idempotency, and source freshness.
4. Deduplication, source independence, baseline windows, and Signal scoring.
5. Source status UI: healthy, degraded, auth required, disabled, source failed.

Exit criteria:

1. Watchlist -> GitHub/RSS collection -> Signal Inbox runs on a schedule.
2. Repost and duplicate amplification do not trigger a high-confidence Signal in seed/eval cases.
3. Every Signal explains trigger rules, limitations, source counts, and source freshness.

### Phase 3: Model-Assisted Research And Decision Brief Quality

Goal: replace the deterministic Phase 1 ResearchRun provider with one bounded LangGraph and prove model-assisted evidence quality without changing the already-real Investigation/Brief contract.

Scope:

1. LangGraph Research Run inside an Investigation: planner, parallel retrieval, evidence analyst, ClaimVersion builder, evidence reviewer, synthesis writer and human review.
2. LangGraph proposals flow through the existing Phase 1 Evidence/ClaimVersion ledger and immutable ContentVersion contracts; Phase 3 does not introduce a second ledger.
3. Model-assisted retrieval expands supporting/opposing Evidence coverage while the same human review and Domain Service gates remain authoritative.
4. Tiptap-based Product Decision Brief editor with object-backed blocks.
5. Langfuse tracing with redaction and prompt versioning.
6. Eval suite for citation correctness, evidence coverage, unsupported claims, numerical accuracy, counter-evidence recall, prompt injection handling.

Exit criteria:

1. A verified intermediate synthesis cannot be created without reviewed ClaimVersions and Evidence links.
2. Brief blocks preserve ClaimVersion, Evidence and ContentVersion references.
3. Unsupported Claim Rate and Citation Correctness meet Phase 3 gates in `QUALITY_GATES.md`.

### Phase 4: Collaboration And Extension

Goal: add team workflow after the evidence loop is real.

Scope:

1. Activate roles beyond the Phase 1 Owner/operator: Admin, Analyst, Contributor, Viewer.
2. Comments, assignment, separation-of-duty review UX, activity and AuditLog UI. Reviewer is an assignment/duty performed by an authorized Owner/Admin/Analyst, not a sixth WorkspaceMember.role. The underlying authorization, RLS and append-only AuditLog already exist.
3. Evaluation dashboard for precision, recall, citation correctness, cost, latency, acceptance.
4. Agent Reach adapter spike only after ToS/license/security review.
5. Optional additional sources only after source-specific contract tests and legal review.

Exit criteria:

1. High-risk actions are permissioned and audited.
2. Collaboration does not create parallel product/market/research object models.
3. New connectors can be added through `SourceConnector` without changing Research or UI internals.

## Completion State Definitions

| State | Definition | What it is not |
|---|---|---|
| Design complete | Screen, states, object model, interactions, and copy are specified and reviewable | A working implementation |
| Production code complete | Code is typed, tested, observable, error-handled, permissioned, and deployable | A mock/demo path |
| Data authenticity complete | UI and APIs distinguish seed, imported, collected, stale, failed, and verified data | Real-looking sample content |
| Runtime integrity complete | The feature runs through the intended local/cloud services with health, retries, logs, and recovery | A static screenshot or isolated component |

## Critical User Flows

1. Phase 1: PM creates an AI Coding Agents Watchlist, takes Seed/Imported CSV through ImportSession → consent → upload verification → terminal ImportManifest and sees recovery-aware import health; Phase 2+: the same flow may enable GitHub/RSS and show cloud source health.
2. PM opens a Signal, reviews why it triggered, confirms Impact/Urgency, and starts an Investigation.
3. The same Owner PM reviews Evidence and ClaimVersions, verifies exactly one intermediate synthesis, creates a DecisionBriefVersion grounded by it, records exact-version readiness and exports its version-bound PRD Research Input.

## Delivery Rules

1. Do not scaffold future modules until their phase starts.
2. Do not create fake entrances for unsupported sources.
3. Do not make UI depend on LangGraph internal state formats.
4. Do not let Agent output write directly to database tables; route through schema and domain services.
5. Every phase must end with changed scope, test results, unresolved issues, and next-phase risks.
