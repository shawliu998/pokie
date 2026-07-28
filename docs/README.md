# Documentation index

## Current quantitative-research product authority

- [Product direction](../apps/mac/PRODUCT.md)
- [Design and layout boundaries](../apps/mac/DESIGN.md)
- [Capability inventory and Research Series plan](./POKIEQUANT_CAPABILITY_INVENTORY.md)
- [Repository entry point](../README.md)

The active Mac product is the AI-native quant research workspace described by those documents, powered by one verifiable autonomous Research Agent. C1–C5 implementation facts and the planned Research Series packages are deliberately separated in the capability inventory.

## Inherited Glint documentation

The remaining documents describe inherited Glint infrastructure and historical acceptance. They are retained for architecture compatibility and do not define the current quantitative-research information architecture.

> Historical status: Phase 0 accepted; Phase 1 and Phase 2 deterministic local acceptance complete; the first
> Phase 3 model-assisted Evidence/Claim slice is implemented but Phase 3 is not accepted.
>
> Historical verification date: 2026-07-16
>
> Boundary: live GitHub/RSS smoke, production deployment, pilot and GA are not verified.
> Acceptance evidence: [Phase 0 acceptance](./PHASE0_ACCEPTANCE.md), [P1/P2 acceptance](./PHASE1_P2_ACCEPTANCE.md), and [independent Phase 0 review](./PHASE0_REVIEW.md).

## Historical Glint product chain

Inbox Signal → Investigation → one or more ResearchRuns → Evidence → immutable ClaimVersions + ClaimReviews → one verified InvestigationSynthesisVersion → one grounded DecisionBriefVersion + readiness review → version-bound PRD Research Input Preview / terminal BriefExport.

Locked boundaries:

- The first user is one product manager responsible for competitor and user research.
- Inbox / Investigations / Decisions / Monitoring are the user-facing destinations.
- Investigation is the durable work aggregate; ResearchRun is one execution attempt.
- Product Decision Brief is the sole decision-level aggregate.
- PRD Research Input is a projection of one DecisionBriefVersion, never an editable sibling.
- Model-visible Research tools are read-only; proposals persist only through Domain Services.
- Phase 1 is a real Seed/Imported CSV vertical slice with workspace isolation, AuditLog and eval/security smoke. GitHub/RSS begin Phase 2; bounded LangGraph begins Phase 3.

## Product and experience

- [Product brief](./PRODUCT_BRIEF.md)
- [Jobs to be done](./JOBS_TO_BE_DONE.md)
- [Information architecture](./INFORMATION_ARCHITECTURE.md)
- [UI specification](./UI_SPEC.md)
- [User flows](./USER_FLOWS.md)
- [Product validation plan](./PRODUCT_VALIDATION_PLAN.md)

## Architecture and contracts

- [Architecture](./ARCHITECTURE.md)
- [Data model](./DATA_MODEL.md)
- [API contracts](./API_CONTRACTS.md)
- [Security model](./SECURITY_MODEL.md)
- [Evaluation plan](./EVALUATION_PLAN.md)

## Delivery and governance

- [Implementation plan](./IMPLEMENTATION_PLAN.md)
- [Project structure](./PROJECT_STRUCTURE.md)
- [Quality gates](./QUALITY_GATES.md)
- [Seed dataset specification](./SEED_DATASET_SPEC.md)
- [Risk register](./RISK_REGISTER.md)
- [Phase 0 acceptance](./PHASE0_ACCEPTANCE.md)
- [Phase 1 / Phase 2 deterministic acceptance](./PHASE1_P2_ACCEPTANCE.md)
- [P2.5 conditional acceptance](./P2_5_ACCEPTANCE.md)
- [Phase 3 model research runtime](./MODEL_RESEARCH.md)
- [Phase 3 model-quality provisional acceptance](./PHASE3_QUALITY_ACCEPTANCE.md)
- [P2.5 demo script](./DEMO_SCRIPT.md) (historical Glint phase)
- [Qurio 3–5 minute interview demo script](./QURIO_DEMO_3_TO_5_MIN.md)
- [P2.5 pilot plan](./PILOT_PLAN.md)
- [Live connector smoke](./LIVE_CONNECTOR_SMOKE.md)
- [Independent Phase 0 review](./PHASE0_REVIEW.md)

## Architecture decisions

- [ADR 0001 — Modular monolith](./ADR/0001-modular-monolith.md)
- [ADR 0002 — Evidence and immutable versions](./ADR/0002-evidence-versioning.md)
- [ADR 0003 — Bounded Research Graph](./ADR/0003-bounded-research-graph.md)
- [ADR 0004 — Local/cloud/import boundary](./ADR/0004-local-cloud-source-boundary.md)
- [ADR 0005 — Investigation and Decision Brief boundary](./ADR/0005-investigation-decision-brief-boundary.md)
