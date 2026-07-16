# Risk Register

Verification date: 2026-07-15

Phase 0 objective: validate contracts, risk boundaries, evidence integrity, and reuse posture before generating production code.

## Status Vocabulary

| Status | Meaning |
|---|---|
| Open | Known risk, mitigation not yet proven. |
| Mitigating | Controls defined and partially verified. |
| Blocked | Cannot proceed in the proposed direction without external confirmation or decision. |
| Accepted | Risk remains but is consciously accepted for the current phase. |
| Closed | Control has been implemented and verified. |

## Register

| ID | Risk | Impact | Likelihood | Owner | Current status | Mitigation | Phase 0 validation |
|---|---|---:|---:|---|---|---|---|
| R-001 | GPL/custom-licensed reference projects contaminate core code | High | Medium | Engineering governance | Open | Only reference TrendRadar/BettaFish conceptually; no code copy; license gate blocks PRs | `REUSE_MATRIX.md` marks blocked/needs verification and quality gate requires license scan |
| R-002 | Product drifts into chat-first super-agent instead of Signal Inbox workbench | High | Medium | Product + Design | Open | IA gate requires Inbox / Investigations / Decisions / Monitoring; ResearchRun and synthesis stay subordinate; chat is not navigation | Implementation plan defines the walking skeleton around Signal → Investigation → Decision Brief, not chat |
| R-003 | Seed/demo data is mistaken for real intelligence | High | Medium | Data + QA | Open | Seed namespace, visible labels, fixture-only IDs, disabled production export, eval-only provenance | `SEED_DATASET_SPEC.md` defines labels and non-authenticity rules |
| R-004 | LLM generates unsupported claims or fabricates citations | High | High | AI architecture | Open | Evidence ledger, immutable `ContentVersion`, claim schema, reviewer node, eval gates for citation correctness | Quality gates define unsupported-claim and citation thresholds |
| R-005 | Prompt injection from external content controls tools or output | High | High | Security | Open | Untrusted content containers, tool allowlists, schema validation, human approval for writes, reviewer checks | Seed dataset includes prompt injection cases; security gate requires tests |
| R-006 | Tauri sidecar/plugins expand local attack surface | High | Medium | Desktop engineering | Open | Least-privilege Tauri permissions, updater signing, sidecar allowlist, no shell passthrough | Tauri reuse row flags shell/updater/filesystem threat model |
| R-007 | Connector coupling makes sources hard to replace | Medium | High | Backend architecture | Open | `SourceConnector` protocol; domain services never call concrete CLI/API directly | Project structure reserves `connectors/` and contract tests |
| R-008 | Continuous collection violates platform ToS or privacy expectations | High | Medium | Legal + Data | Open | Start with GitHub/RSS/CSV; Agent Reach and social sources behind later legal review | Implementation plan defers social/local cookie sources |
| R-009 | False positives from repost storms or one influential source erode trust | High | High | Data science | Open | Independence scoring, duplicate clusters, minimum source thresholds, counter-evidence checks | Seed dataset includes repost-hotspot false positive |
| R-010 | Cross-platform signal score hides weak assumptions behind one number | Medium | Medium | Product + Data | Open | Separate Detection Confidence, Business Impact, Urgency, Priority | Quality gates require explainability and data limitation fields |
| R-011 | Langfuse traces leak sensitive content, credentials, or private files | High | Medium | AI + Security | Open | Redaction middleware, PII policy, no raw private files in traces, trace sampling controls | Reuse matrix restricts trace payloads |
| R-012 | Rich text editor stores unsafe HTML or stale source references | Medium | Medium | Frontend + Security | Open | Sanitize pasted HTML; each BriefVersion binds one verified synthesis and frozen ClaimEvidence/EvidenceReview snapshot; append freshness records; stale warnings never rewrite old versions | Quality gate tests exact-version readiness/freshness and allowlisted BriefExport selection/reference/render digests |
| R-013 | Runtime looks complete while backend is mock-only | High | Medium | Delivery | Open | Distinguish design complete, production code complete, data authenticity, runtime integrity in every milestone | `QUALITY_GATES.md` defines separate completion states |
| R-014 | Modular monolith devolves into unbounded shared state | Medium | Medium | Backend architecture | Open | Domain modules with service boundaries; explicit contracts; no direct UI dependency on LangGraph internals | Project structure defines modules and contract package |
| R-015 | Evaluation metrics are too late, so agent quality cannot be measured | High | Medium | Research + QA | Open | Seed eval dataset from Phase 0; eval gates start in walking skeleton even with fixtures | Seed spec and quality gates define eval categories |
| R-016 | Performance fails with 100k content items | Medium | Medium | Frontend + Backend | Open | Server-side pagination, virtualized tables, chart downsampling, API P95 budgets | Performance gate defines thresholds |
| R-017 | Product and engineering reintroduce parallel Insight/Deliverable models | High | Medium | Architecture + Product | Mitigating | ADR 0005 fixes Investigation and Decision Brief aggregates; schema/API/client vocabulary review blocks generic Deliverable | Cross-doc audit and generated contract tests must show no independently editable PRD Research Input |

## Blockers And Needs Verification

1. TrendRadar code reuse is blocked: the official repository `LICENSE` was verified as GPL-3.0 on 2026-07-15.
2. BettaFish is blocked for code reuse: license contains research/non-commercial restrictions incompatible with a commercial desktop product baseline.
3. DeerFlow license was verified as MIT on 2026-07-15, but current decision remains architecture reference only because its chat-first/super-agent product model conflicts with Glint MVP scope.
4. Agent Reach requires verification of distribution method, transitive tools, platform ToS, and credential handling before any adapter implementation.

## Top Five Assumptions To Validate First

1. A PM can trust a Signal faster when shown independent sources, counter-evidence, and limitations instead of a single severity score.
2. GitHub + RSS + CSV is enough to demonstrate a real vertical loop before adding social platforms.
3. LangGraph can express the Research Run with checkpointing and human review without forcing chat-first IA.
4. shadcn/ui plus custom tokens can achieve a dense Mac workbench rather than a generic dashboard look.
5. Seed cases can reliably catch false positives, unsupported claims, repost amplification, and prompt injection before real ingestion is available.
