# Glint Phase 0 Architecture

## Decision summary

Glint is an intelligence workbench for a small product team, not a general-purpose chat product. The first production capability is a single, real vertical slice:

Watchlist → Seed/Imported CSV → normalized versioned content → explainable Signal → Investigation → one or more bounded Research Runs → Evidence and ClaimVersion proposals → human review → Investigation synthesis → Product Decision Brief → version-bound PRD Research Input export. Phase 2 replaces the input edge with continuous GitHub/RSS collection; it does not change the downstream aggregates.

Product Decision Brief is the only decision-level product object. Investigation is the PM's durable work container; ResearchRun is an execution attempt inside it; InvestigationSynthesisVersion is a reviewed intermediate snapshot, not a navigation destination or competing decision record. PRD Research Input is a deterministic export projection of one DecisionBriefVersion, never a separately editable document.

The deployment architecture is a modular monolith, one independent worker process, and a Mac client. This is intentionally smaller than the eventual product surface. Design artifacts may cover the complete core navigation, but a production client exposes only destinations, commands and states backed by the connected slice. No placeholder integration or dormant deep link may imply that a source is collecting data.

## System boundary

~~~mermaid
flowchart LR
  User["Team member on macOS"] --> Mac
  subgraph Mac["Mac client: Tauri 2 + React"]
    UI["Three-pane UI, local SQLite read cache, import staging"]
    Local["Local parser / optional Agent Reach sidecar"]
    Vault["Keychain / Stronghold"]
  end
  subgraph Cloud["Glint cloud: one deployable codebase"]
    API["FastAPI API and SSE"]
    Worker["Independent Dramatiq worker"]
    Scheduler["Scheduler"]
    DB[("PostgreSQL + pgvector")]
    Cache[("Redis")]
    Objects[("S3 / MinIO immutable snapshots")]
  end
  subgraph External["External systems"]
    GitHub["GitHub API"]
    RSS["RSS feeds"]
    Files["User-selected CSV / local documents"]
    Models["LLM / embedding providers"]
    Observe["Langfuse / telemetry"]
  end
  UI <--> API
  Vault --> Local
  Local --> Files
  API <--> DB
  API --> Cache
  Scheduler --> Worker
  Worker <--> DB
  Worker --> Objects
  Worker --> GitHub
  Worker --> RSS
  Local -. explicit upload only .-> API
  Worker --> Models
  Worker --> Observe
~~~

Glint owns the workspace domain, content lineage, detection, research proposals, approval history, and exports. It does not own GitHub/RSS source data, a model provider, or a user's device credential store. The Mac app is a trusted application surface for its signed-in user, not a second team database.

## Deployment and responsibilities

| Unit | Primary responsibilities | Does not own |
|---|---|---|
| mac-app | Native UI, read-only local cache, file selection/import parsing, consent prompts and secure credential storage; future local-connector seam | Collaborative truth, background cloud collection, final authorization, MVP offline editing |
| api | Authentication, workspace-scoped REST API, domain services, policy checks, SSE replay, optimistic-concurrency validation, read models | Long-running collection or LLM execution |
| worker | Collection, normalization, deduplication, detection, Research Runs, object writes, retries and backfills | Direct user-facing authorization decisions |
| scheduler | Enqueues due collection and maintenance jobs using durable schedules | Domain logic or data processing |
| postgres | Transactional source of truth, tenancy, lineage, events and projections | Raw object bodies and secrets |
| redis | Queue broker/result coordination, leases, rate limits and short-lived replay cache | Authoritative business state |
| object storage | Immutable raw snapshots and imported-file blobs addressed by content hash | Mutable business metadata |

FastAPI and worker import the same domain packages. They are separately deployable processes only so a long investigation or ingestion cannot starve the API. There are no per-domain services, Kafka, Kubernetes dependency, or workflow engine in Phase 0.

## Modular-monolith boundaries

The codebase will have explicit modules with public command/query interfaces; a module may not read another module's tables except through a documented repository/query service.

| Module | Owns |
|---|---|
| Identity and workspace | Workspace, membership, role resolution, workspace policy |
| Project and watchlist | Project, Watchlist and structured rules; assignments are Phase 4 |
| Source registry | SourceConnection, capability, credential reference, health |
| Content pipeline | CollectionRun, RawContentItem, ContentItem, ContentVersion, deduplication and import manifests |
| Detection | Aggregations, Signal, SignalEvidence, scoring explanations and cooldown |
| Investigation and research | Investigation, ResearchRun, ResearchTask, ToolExecution, graph checkpoint references and RunEvent |
| Evidence and claims | Immutable Evidence, EvidenceReview, Claim, ClaimVersion, append-only ClaimEvidence/ClaimReview, deterministic score inputs and review projections |
| Synthesis and decisions | InvestigationSynthesis, InvestigationSynthesisVersion, SynthesisReview, DecisionBrief, DecisionBriefVersion, DecisionBriefReadinessReview, DecisionBriefFreshnessRecord and BriefExport |
| Evaluation and audit | PromptVersion, evaluation datasets/runs, feedback, AuditLog |
| Notification | NotificationRule and Notification, after policy checks |

Cross-module writes run through domain services inside one database transaction when possible. For asynchronous work, a transaction writes an outbox record; the worker consumes it idempotently. Read models may join workspace-scoped projections but never bypass authorization.

## Source classes and data boundary

These are distinct product concepts, not labels for the same connector.

| Class | Execution and credentials | Storage/default sharing | Availability |
|---|---|---|---|
| Cloud Source | Server-side connector; workspace-approved service credential | Content and snapshots reside in the workspace cloud store | Continues when Macs are offline |
| Local Source | Runs on a named Mac through its sidecar/client; device credential remains in Keychain | Metadata/health may sync; content never leaves the Mac until the user approves a bounded upload | Requires that device and client are available |
| Imported Dataset | User selects a static file such as CSV, interview export, PDF or Markdown | Parse locally; create a mutable ImportSession, append exact TransferConsentRecord, upload to a scoped object key, then create an immutable ImportManifest only after validation | It does not refresh automatically |

Local source content is never silently sent to a cloud model or added to a cloud Research Run. A user chooses one of: keep local, import an approved subset to a workspace, or cancel. After upload it is an Imported Dataset in the cloud, not still a Local Source. A Cloud Source cannot use a local browser cookie.

The import boundary is executable, not a three-step mutation of an allegedly immutable object. The Mac sends metadata/digests but never its filesystem path when creating ImportSession. Phase 1 allows one non-terminal session per Imported Source and pins the expected SourceConnection row/current-manifest pointer. Consent is append-only and exact to the selected scope/destination/object limit; it does not grant model egress, and both upload completion and finalize resolve the same effective unexpired/unrevoked grant. A dedicated ImportFinalizationJob is the sole background job allowed the session ID: it verifies the object, parses/normalizes, then atomically creates visible content plus one terminal immutable ImportManifest and compare-and-sets the source pointer. Failed/cancelled/stale sessions create none and staging is cleaned. Downstream dedupe/detection/research workers accept only terminal manifest IDs and do not normalize twice.

Phase 1 supports Seed/Imported CSV only. Phase 2 enables GitHub and RSS as Cloud Sources. Local Source and sidecar stay as an ADR/schema adapter seam with no callable MVP OpenAPI or UI; cookie-dependent collection waits for a secure device-to-workspace protocol.

## Content-to-decision pipeline

~~~mermaid
flowchart LR
  C["Connector or import"] --> R["Raw snapshot"]
  R --> N["Parse, normalize, language"]
  N --> D["Exact/near duplicate and independence grouping"]
  D --> E["Entities, topics, mentions, aggregates"]
  E --> S["Deterministic Signal detection"]
  S --> H["Human triage / create Investigation"]
  H --> G["Bounded Research Run"]
  G --> V["Evidence / ClaimVersion proposals"]
  V --> A["Domain validation + human review"]
  A --> I["Reviewed Investigation synthesis"]
  I --> B["Decision Brief"]
  B --> X["Version-bound PRD export"]
~~~

Every stage has a run identifier, input/output counts, retry records, and a deterministic or immutable input reference. The worker may replay an ingestion or investigation from its persisted inputs. It never overwrites source text with a model output.

### Collection processing

The pipeline is connector → raw snapshot → parsing → normalization → exact deduplication → near-duplicate candidate matching → independence/event grouping → language/spam checks → entity/topic/mention extraction → aggregation → detection. Deterministic algorithms handle URL normalization, hashes, windows, deduplication candidates, counts, baseline calculation, score calculation, and state transitions. An LLM may classify or disambiguate a low-confidence candidate, but its output is stored as a proposal with model/prompt provenance.

Write idempotency is based on workspace, source connection, external identifier and normalized content hash. Collection jobs use a stable collection-window key. A retry either returns the earlier successful result or creates a separately auditable attempt without duplicating ContentVersion or SignalEvidence.

### Explainable signal dimensions

Signal priority is not a single severity number. The record stores:

| Dimension | Meaning | Initial computation |
|---|---|---|
| Detection Confidence | Confidence that the observed change is real and not collection/duplicate/noise artifact | Sample sufficiency, source/author independence, cross-platform agreement, detector health and anomaly stability |
| Business Impact | Likely consequence if the change matters to the product/business | System may suggest with rationale; PM explicitly confirms Low/Medium/High/Unknown |
| Urgency | How quickly a decision or mitigation is needed | System may suggest from deadlines/acceleration; PM explicitly confirms Now/This week/Monitor/Unknown |
| Priority | Queue ordering for this workspace | null/pending until both assessments exist; null/insufficient_input if either confirmed value is Unknown; otherwise derived only through a versioned MVP matrix |

At launch, labels such as Low/Medium/High are heuristic levels, not calibrated probabilities. Numeric values remain internal score inputs unless a versioned evaluation proves calibration for the source population. Detection Confidence is detector-owned and read-only. Every Impact/Urgency suggestion carries suggestion_origin and suggestion_version: Phase 1 uses deterministic_rule, while model is legal only after the Phase 3 runtime/policy gate. MVP does not directly override Priority; changing Impact or Urgency creates an audited assessment version and deterministically recomputes Priority. Unknown is a confirmed human assessment but is not a matrix input, so Priority stays null with insufficient_input until both confirmed values are rankable.

## Research Run and bounded LangGraph

One typed, bounded LangGraph executes a Research Run beginning in Phase 3. Phase 1 uses a deterministic Seed/CSV run implementation under the same ResearchRun, proposal and Domain Service contracts; it is labelled by data_authenticity and never presented as model automation. Neither implementation is a set of autonomous agents, can create arbitrary subgraphs/tools, or can commit approved domain data directly.

~~~mermaid
flowchart TD
  Start["Validate command and immutable input manifest"] --> Plan["LLM: propose typed research plan"]
  Plan --> Gate1{"Human approval required?"}
  Gate1 -- yes --> WaitPlan["HUMAN_GATE: approve/edit/cancel"]
  Gate1 -- no --> Retrieve["Deterministic: bounded retrieval per allowlisted source"]
  WaitPlan --> Retrieve
  Retrieve --> Normalize["Deterministic: deduplicate, evidence candidates, stats"]
  Normalize --> Analyze["LLM: propose evidence analysis and claims"]
  Analyze --> Review["Deterministic reviewer: citations, counters, ranges, injection flags"]
  Review --> Gate2{"Claims need human review"}
  Gate2 -- yes --> WaitClaim["HUMAN_GATE: accept/reject/request more retrieval"]
  Gate2 -- no --> Persist["Domain service validates and persists proposals"]
  WaitClaim --> Persist
  Persist --> Synthesis["LLM: draft intermediate synthesis from verified ClaimVersions only"]
  Synthesis --> Gate3["HUMAN_GATE: verify synthesis or retain draft"]
  Gate3 --> End["Complete / cancelled / failed"]
~~~

Deterministic nodes validate scope, budget, source policy, query schema, deduplication, evidence offsets, score inputs, citation references, ClaimVersion state, and database writes. LLM nodes produce Pydantic-validated ResearchPlanProposal, EvidenceProposal, ClaimVersionProposal, or SynthesisDraft only. Model-visible tools are read-only; proposals are node outputs. Human gates are explicit persisted states, never an implicit model instruction. The final persistence node sends every proposal through a domain service, authorization check, schema validation, source policy check and audit writer.

Graph input is a versioned RunInputManifest containing InvestigationScopeVersion, Signal version, Watchlist rules version, allowed source/version identifiers, tool-policy version, prompt versions, model/provider configuration, budget and locale/time range. Checkpoints support resume only with the same manifest or an explicit new attempt. Editing the Decision Question, source scope, time range or budget creates a new InvestigationScopeVersion and a new Run. The UI consumes domain RunEvent records, not LangGraph internal state.

## Core state machines

~~~text
Signal:
new → triaged → investigating → explained
  ├──────────────→ monitoring
  └──────────────→ dismissed

Investigation:
draft → active → reviewing → completed
          ├──→ needs_input → active | reviewing
          └──────────────→ closed_insufficient
draft | active | needs_input | reviewing → cancelled

ResearchRun:
queued → running → completed
            ├──→ waiting_for_input → running
            ├──→ failed
            └──→ cancelled

Evidence review projection:
proposed → valid | weak | rejected

ClaimVersion review projection:
proposed → needs_review → verified | rejected
verified → superseded

InvestigationSynthesisVersion review projection:
draft → needs_review → verified | rejected
verified → superseded

DecisionBrief:
draft → decision_ready → decided → archived
draft | decision_ready ─────────→ archived
decision_ready -- start_revision/new current version --> draft
The old ready version never changes state.

DecisionBriefVersion readiness projection:
draft → decision_ready

DecisionBriefVersion freshness projection:
current | evidence_stale (derived from append-only freshness records; orthogonal to readiness)

BriefExport: terminal immutable record after successful validation/render; no mutable lifecycle.
~~~

Transitions are commands with role and state preconditions. Evidence, Claim, synthesis and Brief-readiness state changes append immutable review records and update aggregate/read projections; they never rewrite evidentiary/version content. In the MVP, an Investigation starts from a Signal and may contain multiple Research Runs; queued/running/failed are Run states, so one failed Run leaves its Investigation active or needs_input and a later Run never replaces it. waiting_for_input carries a closed reason enum; a changed scope, budget or manifest creates a new Run/attempt instead of resuming the old manifest. Editing a verified ClaimVersion or synthesis creates a new immutable version. Editing a ready Brief requires start_revision, which creates a new Draft version/current pointer; the old readiness, freshness and exports remain pinned. Evidence changes append freshness records rather than mutating a Brief. A rejected or cancelled run retains its events and provenance. The MVP UI implements decision_ready plus Markdown export; decided is reserved for the later decision-recording capability.

## RunEvent and SSE recovery

RunEvent is an append-only table keyed by the database FK `research_run_id` and a strictly increasing sequence number. One generated persistence-to-wire mapping uses `research_run_id → run_id`, `type → event_type`, `payload_json → payload`, and `occurred_at → timestamp`; all values are identical rather than parallel fields. Its event_id is globally unique, while its sequence is monotonic within the run. The API commits the event before publishing it to SSE, so a client can reconnect without trusting a transient broker message.

1. The client first fetches the run snapshot, including latest_sequence.
2. It connects to GET /v1/research-runs/{run_id}/events with Last-Event-ID set to the most recently persisted event_id.
3. The server maps that ID to the run sequence, replays all later committed events in order, then tails new events.
4. Duplicate events are safe: clients de-duplicate by event_id and apply only a greater sequence.
5. A missing/expired cursor yields a typed stream.reset control event with an authoritative snapshot URL; the client replaces its local projection and reconnects. stream.reset, snapshot fetches and heartbeats do not consume the RunEvent business sequence.
6. Heartbeats do not advance sequence. Terminal events are durable and replayable.

SSE is the default server-to-client channel. WebSocket is not introduced until a real bidirectional collaboration requirement exists.

## Concurrency, retries, and consistency

All mutation requests require a client-generated idempotency key. The API stores the request fingerprint and outcome per workspace/principal/action. Repeating an accepted request returns the original status and resource. User edits include version or ETag preconditions; a stale write receives 412 with current version metadata rather than a last-write-wins overwrite.

The worker uses leases for scheduled work, connector rate limits and graph concurrency. A job's stable key is unique at the database level. Outbox delivery is at-least-once; consumers are idempotent. External calls record a ToolExecution attempt, timeout, result digest and retry count. Retry policy is bounded by connector capability and run budget. Cancellation is cooperative and checked before each tool and persistence boundary.

## Reproducibility, provenance, and retention

A completed Research Run can be reproduced from immutable versions rather than from a mutable latest view:

- Each immutable Evidence points to one immutable ContentVersion and a quote range/hash; EvidenceReview appends exact-Evidence decisions.
- Each ResearchRun pins one immutable InvestigationScopeVersion and RunInputManifest.
- Each ClaimVersion and ClaimEvidence graph is append-only and same-Investigation. ClaimReview pins the exact ClaimEvidence/EvidenceReview snapshot and digest used for verification. Claim aggregate row_version is only a concurrency mechanism.
- InvestigationSynthesisVersion records the exact verified ClaimVersion and verifying ClaimReview IDs/digests plus synthesis-template/generator version; SynthesisReview records its exact-version decision.
- Every DecisionBriefVersion is grounded by exactly one verified InvestigationSynthesisVersion in the same Investigation. Its direct ClaimVersion/Evidence/ContentVersion references are a frozen subset of that synthesis provenance, it separates Fact, origin-labelled Synthesis, PM Judgment and Recommendation blocks, and it never silently rewrites human text. generation_method/generator_version prevent deterministic output from masquerading as AI; DecisionBriefReadinessReview records readiness and DecisionBriefFreshnessRecord records current/stale for that exact version.
- A successful BriefExport references exactly one readiness-reviewed DecisionBriefVersion plus selection manifest, reference digest, rendered snapshot/output digest and export policy/template versions; PRD Research Input is rendered from that frozen reference. Failed commands create no export record.
- PromptVersion, model/provider parameters, tool-policy version, graph version, connector version, dataset/import manifest and run event sequence are retained with the run.

Some external URLs may later disappear; Glint preserves the legally permitted collected snapshot and labels availability changes. Retention/deletion policy is workspace-configured and applies to object snapshots, vector representations and derived data together. User deletion requests create tombstones and audit records; legal/contractual retention exceptions are explicit.

## First walking skeleton versus deferred objects

The first real implementation contains Workspace, WorkspaceMember, Project, Watchlist, SourceConnection, CollectionRun, ContentItem, ContentVersion, Signal, SignalEvidence, Investigation, ResearchRun, RunEvent, ToolExecution, Evidence, EvidenceReview, Claim, ClaimVersion, ClaimEvidence, ClaimReview, InvestigationSynthesis, InvestigationSynthesisVersion, SynthesisReview, DecisionBrief, DecisionBriefVersion, DecisionBriefReadinessReview, DecisionBriefFreshnessRecord, BriefExport, PromptVersion, Feedback, EvaluationDataset, EvaluationRun and AuditLog. Phase 1 implements only the subset required by its real Seed/CSV vertical slice; it does not scaffold empty future modules.

Entity/alias, topic, mention, metric snapshot, notification rule/notification, comments, assignments, saved views, Share Links and full collaboration activity are designed now but deferred. Phase 1 exposes Seed/Imported CSV only; GitHub/RSS Cloud Sources begin Phase 2, and Local Source remains a non-callable seam. Source-health, workspace scope, authorization and audit are still real. No frontend-specific Mock model is allowed: seed fixtures enter through the same API schemas and are marked data_authenticity=seed in a non-production workspace.

## Operational targets and failure behavior

The client displays stale/offline/local source state instead of inventing freshness. Initial development targets are normal API P95 under 500 ms excluding runs, cached Signal navigation under 150 ms, and SSE publication under one second after event commit; these become production SLOs only after target hardware and pilot telemetry establish a baseline. Lists paginate at the API and never require 100k ContentItems in the client.

Connector failure produces an auditable CollectionRun failure and source-health update, not a deceptive empty result. Partial research remains a partial draft with a limitation; it cannot become Verified merely because some retrieval failed. Each implemented slice must represent the states it can actually produce. Phase 1 requires loading, empty, source degraded, authorization/session failure and cached-read-only states; needs input, cancellation, insufficient evidence and edit conflict become mandatory only when their owning capabilities ship.

## Out of scope for this phase

The following are deliberately not first-slice capabilities: social platforms requiring a browser cookie, automatic external publishing, arbitrary web crawling, general chat, multi-agent autonomy, full offline conflict-free sync, enterprise SSO/SCIM, complex notification delivery, and broad BI dashboards. Their future addition must preserve the source boundary, approval gate and immutable evidence contract above.
