# Quality Gates

Verification date: 2026-07-16

Quality gates apply to every implementation phase. A feature is not complete unless its design, production code, data authenticity, and runtime integrity states are all explicitly reported.

## Current acceptance record

The combined deterministic P1/P2 gate, `./scripts/verify_phase2.sh`, exited `0` on 2026-07-16. Its final summaries reported no failed layers. The Phase 1 aggregate had no skipped layers; the Phase 2 summary recorded only the policy skip for live smoke because `GLINT_ENABLE_LIVE_SMOKE=1` was not set.

This result covers the repository's locked, local deterministic path, including Docker Compose/Postgres/RLS, fixture and local API E2E, and native Tauri runtime. It does not verify live GitHub/RSS credentials or network behavior, production deployment, pilot outcomes, or GA readiness. Counts, warnings and the precise boundary are recorded in [PHASE1_P2_ACCEPTANCE.md](./PHASE1_P2_ACCEPTANCE.md).

## Completion States

| State | Required evidence |
|---|---|
| Design complete | IA/state map, domain objects, permissions and accessibility notes; state coverage is required only for capabilities promised by the current slice. |
| Production code complete | Typed code, tests, error handling, observability, migrations, permissions, documented configuration, no mock-only paths hidden as production. |
| Data authenticity complete | Every object is labeled as seed/imported/collected/generated/verified/stale/failed/deleted-source; suggestions and Synthesis also expose deterministic_rule/deterministic/model origin/version; no seed or deterministic output can masquerade as live/model intelligence. |
| Runtime integrity complete | Feature runs through Tauri/API/worker/database/object store as designed, with health checks, retries, audit logs where needed, and recovery behavior. |

## Gate Matrix

| Gate | Minimum bar | Applies from |
|---|---|---|
| Lint | Frontend lint, Python lint, formatting, Markdown link sanity for docs | Phase 1 |
| Typecheck | TypeScript strict mode; Python static typing for domain/contracts; Pydantic schema validation | Phase 1 |
| Unit | Domain logic coverage for the current slice: ImportSession/consent/finalize state machine, dedupe, Signal dimensions/Priority, review projections, state machines, permissions, adapters and time windows; Later modules add their gates only when activated | Phase 1 |
| Contract | REST, import session/consent/upload/finalize schemas, SSE events, connector contracts, shared schemas, generated clients | Phase 1 |
| Integration | Phase 1: local CSV metadata/digest → ImportSession → exact TransferConsentRecord/effective-consent resolver → verified upload → dedicated finalization job → terminal ImportManifest + ContentVersion → downstream dedupe/Signal → Investigation → deterministic ResearchRun → EvidenceReview → immutable ClaimEvidence snapshot/ClaimReview → verified InvestigationSynthesisVersion → DecisionBriefVersion → readiness/freshness records → BriefExport; Phase 2 adds connector retries/partial failure; Phase 3 replaces only the run provider with LangGraph | Phase 1 |
| E2E | Single Owner PM path through the currently connected slice; no disconnected Shell routes | Phase 1 deterministic path, model-assisted path Phase 3 |
| Eval | Phase 1 fixed schema/safety/lineage smoke; Phase 3 quality evaluation for citation, coverage, unsupported claims, counter-evidence and actionability | Phase 1 smoke, full Phase 3 |
| Security | Prompt injection tests, Tauri permission review, secret redaction, dependency audit, unsafe HTML sanitization, high-risk action approval | Phase 1 |
| License | Lockfile scan, third-party notices, GPL/custom license block, shadcn provenance record | Phase 0 docs, Phase 1 code |
| Performance | Startup, list interaction, API P95, SSE latency, table pagination, chart downsampling, agent cost/latency budgets | Phase 1 baseline, strict Phase 2+ |

## Provisional targets and safety invariants

Except for the explicit safety invariants below, all numbers in this section are Phase 0 hypotheses for a named development dataset/hardware profile. They are not calibrated probabilities, production SLOs or release guarantees. Before a target becomes a release gate, its owner must record dataset/version, sample size, denominator, baseline date and calibration decision. A metric has one provisional pass line; separate stop rules live in PRODUCT_VALIDATION_PLAN.md and do not redefine this engineering target.

| Area | Provisional target or invariant |
|---|---|
| Main window interactive after cold start | < 3 seconds on target dev Mac after production build baseline is established |
| Cached Signal list navigation | < 150 ms perceived switch latency |
| Standard API P95 excluding agent runs | < 500 ms in local dev dataset; stricter production SLO to be set after telemetry |
| SSE event delivery | < 1 second from server event creation to UI receipt in local dev |
| Client list loading | Must use server pagination/virtualization for large datasets; no full client load of 100k `ContentItem` |
| Chart rendering | Downsample or aggregate large series before render; chart must expose table/text summary |
| Research concurrency | Explicit per-workspace and global caps; no unbounded parallel tool calls |
| Agent run cost | UI must show estimated and actual cost when model pricing is configured |
| Citation correctness eval | Provisional Phase 3 target >= 0.95 on the named reviewed eval set; calibrate after pilot labeling |
| Unsupported claim rate | Provisional Phase 3 target <= 0.05 on the same named reviewed eval set; calibrate after pilot labeling |
| Counter-evidence recall | Provisional Phase 3 target >= 0.80 on named cases containing adjudicated opposition |
| Safety invariants | 100% pass for workspace isolation, unauthorized approval/write blocking, secret non-disclosure, Local→Cloud consent and Evidence→ContentVersion/ClaimVersion/BriefVersion integrity |
| Prompt injection authorization invariant | 100% of seed injection cases must fail to change tool policy, perform an unauthorized call/write/export or create an approved record |

## Required Test Coverage By Domain

| Domain | Required tests |
|---|---|
| Import lifecycle | No local path/body on session create; exact-scope effective consent at upload-complete/finalize; append-only revoke; object key/size/type/digest mismatch and staging cleanup; one active session/source; stale source-pointer and finalize/cancel races; state/idempotency/concurrency; retryable versus cancel/new-session recovery; zero manifest/content on failure; exactly one terminal manifest; only the dedicated finalizer may receive session ID and all downstream jobs reject it |
| Deduplication | Canonical URL, source ID, content hash, title hash, near-duplicate text, repost cluster, independent same-event sources |
| Signal scoring | Baseline window, current window, robust z-score, growth, platform diversity, author independence, cooldown, low sample suppression |
| Claim confidence | Support/opposition weighting, evidence coverage, source diversity, sample factor, contradiction penalty |
| State/review projections | ImportSession, Signal, Investigation, ResearchRun, EvidenceReview, ClaimReview, SynthesisReview, DecisionBrief readiness/freshness/revision, SourceConnection; ImportManifest and successful BriefExport are terminal immutable |
| Permissions | Phase 1 real workspace/RLS + Owner operator + high-risk actions; full Owner/Admin/Analyst/Contributor/Viewer behavior begins Phase 4 |
| Connector adapters | Search, fetch, health, capabilities, timeout, pagination, rate limit, invalid credentials, source deletion |
| Research graph | Checkpoint, resume, cancellation, tool failure, human review, rejected claim, trace IDs |
| Decision Brief/export | Exactly one verified same-Investigation synthesis per DecisionBriefVersion; typed blocks are a provenance subset of frozen Evidence/Claim reviews; exact-version readiness/freshness and explicit revision; PRD selection forbids Synthesis; BriefExport binds version + selection/reference/render digests |
| Security | Prompt injection, untrusted content boundaries, HTML paste sanitization, secret redaction, shell allowlist |

## Pull Request Checklist For Future Code

1. Scope maps to current phase and does not scaffold future unsupported features.
2. All data shown in UI has authenticity labels.
3. New dependencies appear in reuse/license review.
4. New connector behavior has contract fixtures.
5. Model-visible tools remain read-only; proposal output is schema-validated and persisted only through an authorized Domain Service, while approval/export remain human REST commands.
6. New high-risk action has permission and audit log coverage.
7. Every state the current slice can actually produce has a recovery path. Phase 1 requires loading, empty, authorization/session failure, cached-read-only, source degraded and its explicit failure paths; later states become mandatory only with their owning capability.
8. Tests include at least one failure path, not only the happy path.

## License Gate

Blocked by default:

1. GPL, AGPL, SSPL, Commons Clause, custom non-commercial, research-only, or unclear licenses.
2. Projects with conflicting license evidence until resolved.
3. Code snippets copied from README/blog/docs unless license permits reuse and notice is preserved.
4. AI-generated code that materially reproduces a third-party codebase.

Allowed with review:

1. MIT, Apache-2.0, BSD-style dependencies through package managers.
2. shadcn/ui generated components with provenance and MIT notice tracking.
3. Architecture ideas described in original Glint docs without copying source or protected expression.
