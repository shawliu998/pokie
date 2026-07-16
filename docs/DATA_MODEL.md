# Glint Phase 0 Data Model

## Modeling rules

PostgreSQL is the cloud source of truth. SQLite is a replaceable Mac cache for read projections, synchronization cursors and local-source/import staging; it is not an alternate domain model and MVP does not support offline Brief editing. All IDs use valid UUID shapes, including deterministic UUIDv5 fixture IDs. Mutating records carry created_at, updated_at, created_by and row_version. Tables that hold workspace data include workspace_id and are protected by PostgreSQL row-level security plus application authorization. User-visible records also carry data_authenticity = seed, imported, collected, generated or human_authored as applicable.

IDs in references below are UUIDs. Timestamps are UTC. Enumerations are closed Pydantic/SQL enums. JSON fields require a versioned schema and are used only where a relational shape is not yet stable. All model-generated values record model_run_id and prompt_version_id when present.

## Relationship overview

~~~mermaid
erDiagram
  WORKSPACE ||--o{ WORKSPACE_MEMBER : has
  WORKSPACE ||--o{ PROJECT : has
  PROJECT ||--o{ WATCHLIST : scopes
  WORKSPACE ||--o{ SOURCE_CONNECTION : authorizes
  SOURCE_CONNECTION ||--o{ IMPORT_SESSION : coordinates
  IMPORT_SESSION ||--o{ TRANSFER_CONSENT_RECORD : authorizes
  IMPORT_SESSION ||--o| IMPORT_MANIFEST : finalizes_as
  IMPORT_MANIFEST ||--o{ RAW_CONTENT_ITEM : ingests
  WATCHLIST ||--o{ COLLECTION_RUN : requests
  SOURCE_CONNECTION ||--o{ COLLECTION_RUN : executes
  COLLECTION_RUN ||--o{ CONTENT_ITEM : discovers
  CONTENT_ITEM ||--o{ CONTENT_VERSION : has_immutable_versions
  WATCHLIST ||--o{ SIGNAL : detects
  SIGNAL ||--o{ SIGNAL_EVIDENCE : summarizes
  CONTENT_VERSION ||--o{ SIGNAL_EVIDENCE : supports
  SIGNAL ||--o{ INVESTIGATION : initiates
  INVESTIGATION ||--o{ INVESTIGATION_SCOPE_VERSION : scopes
  INVESTIGATION ||--o{ RESEARCH_RUN : contains
  RESEARCH_RUN ||--o{ RUN_EVENT : emits
  RESEARCH_RUN ||--o{ EVIDENCE : proposes
  CONTENT_VERSION ||--o{ EVIDENCE : anchors
  EVIDENCE ||--o{ EVIDENCE_REVIEW : reviewed_by
  RESEARCH_RUN ||--o{ CLAIM : proposes
  CLAIM ||--o{ CLAIM_VERSION : versions
  CLAIM_VERSION ||--o{ CLAIM_EVIDENCE : cites
  CLAIM_VERSION ||--o{ CLAIM_REVIEW : reviewed_by
  EVIDENCE ||--o{ CLAIM_EVIDENCE : links
  INVESTIGATION ||--o| INVESTIGATION_SYNTHESIS : synthesizes
  INVESTIGATION_SYNTHESIS ||--o{ INVESTIGATION_SYNTHESIS_VERSION : versions
  INVESTIGATION_SYNTHESIS_VERSION }o--o{ CLAIM_VERSION : includes
  INVESTIGATION_SYNTHESIS_VERSION ||--o{ SYNTHESIS_REVIEW : reviewed_by
  INVESTIGATION ||--o| DECISION_BRIEF : produces
  DECISION_BRIEF ||--o{ DECISION_BRIEF_VERSION : versions
  INVESTIGATION_SYNTHESIS_VERSION ||--o{ DECISION_BRIEF_VERSION : grounds
  DECISION_BRIEF_VERSION }o--o{ CLAIM_VERSION : cites
  DECISION_BRIEF_VERSION ||--o{ DECISION_BRIEF_READINESS_REVIEW : reviewed_by
  DECISION_BRIEF_VERSION ||--o{ DECISION_BRIEF_FRESHNESS_RECORD : assessed_by
  DECISION_BRIEF_VERSION ||--o{ BRIEF_EXPORT : exports
~~~

## Workspace and authorization objects

| Object | Key fields | Invariants |
|---|---|---|
| Workspace | id, name, status, data_region, retention_policy_version | Tenant root. A request has exactly one resolved workspace context. |
| WorkspaceMember | workspace_id, user_id, role, status | Unique workspace_id/user_id. Phase 1 creates only Owner/operator membership; Admin, Analyst, Contributor and Viewer are reserved enum values activated with Phase 4 role behavior/migration. |
| Project | workspace_id, name, status | A project belongs to one workspace; all child objects must resolve to the same workspace. |
| AuditLog | workspace_id, actor_id, action, target_type/id, before_digest, after_digest, reason, request_id, occurred_at | Append-only; sensitive values are redacted and never stored as plaintext secrets. |

Resource authorization checks the workspace first, then an optional project relationship. IDs from a different workspace must be indistinguishable from absent resources to callers without access.

## Watchlist and source objects

| Object | Key fields | Invariants |
|---|---|---|
| Watchlist | workspace_id, project_id, name, objective, status, rules_version, owner_id | Structured rules are validated before activation; free text is retained only as an explanation. |
| WatchlistRule | watchlist_id, rule_type, include/exclude values, languages, regions, cadence, baseline/window, alert policy | The normalized rule document is versioned; detector runs pin rules_version. |
| SourceConnection | workspace_id, source_kind, runtime, connector_type/version, status, credential_ref, data_scope, approved_by, current_import_manifest_id | source_kind is cloud, local or imported_dataset; runtime and kind must be compatible. current_import_manifest_id is used only by imported_dataset and may point only to a terminal manifest for the same connection/workspace. |
| ConnectorCapability | source_connection_id, capability, limits, checked_at, status | Health/capability is observed metadata, not a permission grant. |
| ImportSession | workspace_id, source_connection_id, expected_source_row_version, expected_current_import_manifest_id, local_manifest_digest, file_digest, expected_upload_digest, client_file_name, file_size_bytes, media_type, parser_version, schema_version, selected_scope_json/digest, state, uploaded_object_key/ref/digest, failure_code, retryable, row_version, created_by | Mutable coordination aggregate. It contains no Mac filesystem path or file body. One session uses one exact source snapshot, local manifest, selected scope and transfer payload; changing any pinned digest or source pointer requires a new session. Phase 1 permits at most one non-terminal session per SourceConnection. |
| TransferConsentRecord | workspace_id, import_session_id, decision, local_manifest_digest, file_digest, expected_upload_digest, selected_scope_json/digest, destination_workspace_id, upload_object_scope, model_egress_authorization, policy_version, actor_id, recorded_at, expires_at, supersedes_id | Append-only grant/revoke record. A grant authorizes only the exact digests/scope/destination/object key and byte limit. It does not authorize later model egress; finalize rejects expired or subsequently revoked grants. |
| ImportManifest | workspace_id, import_session_id, source_connection_id, file_digest, uploaded_object_key/ref/digest, parser_version, schema_version, selected_scope_json/digest, consent_record_id, normalized_payload_digest, content_count, finalized_at | Terminal immutable success record, created at most once per session only after digest/schema validation succeeds. It pins the exact effective grant, object key/bytes and normalized result; failure/cancellation creates no manifest. |
| CollectionRun | workspace_id, watchlist_id, source_connection_id, idempotency_key, state, input_window, counters, attempt_of, started/finished_at | Stable key prevents duplicate collection for the same connection/rule/window. |

SourceConnection semantics are strict:

- Cloud Source: runtime=cloud; a server-held credential reference is allowed; server scheduling is allowed.
- Local Source: runtime=mac_device; device_id is required; credential_ref resolves only on that Mac; content transfer requires a separate explicit consent record.
- Imported Dataset: runtime=static_import and credential_ref=null. Only a finalized static ImportManifest may become current and enter normalization/research. It has no scheduler/cadence and cannot claim freshness after import. Each successful re-import uses a new ImportSession and manifest; older manifests remain immutable provenance.

Import lifecycle is one state machine, separate from the immutable result:

- `draft → consented` appends an exact TransferConsentRecord grant and issues a short-lived object-scoped upload grant.
- `consented → uploaded` occurs only after the API resolves the same effective unexpired/unrevoked consent and verifies the object-store key, size, media type and digest; a client assertion or session state alone is insufficient.
- `uploaded → validating → finalized` is owned by a dedicated ImportFinalizationJob. It may reference the fixed ImportSession/finalize command, validates the pinned parser/schema/scope, stages parsing/normalization, then atomically creates visible RawContentItem/ContentItem/ContentVersion rows plus one ImportManifest and compare-and-sets SourceConnection.current_import_manifest_id against the session's expected source row/pointer.
- `draft|consented|uploaded|validating|failed → cancelled` is terminal and creates no manifest; a row-version check resolves a finalize/cancel race. If an effective grant exists, cancel atomically appends TransferConsentRecord(decision=revoke, supersedes_id=grant_id), invalidates its upload capability, quarantines/schedules deletion of staged bytes and writes AuditLog. Validation errors move to `failed`; retryable failures may re-enter `validating` only with the same pinned digests, source pointer and effective consent, otherwise the user cancels and creates a new session.
- The finalization job is the only background job allowed an ImportSession ID. Every downstream import/dedupe/detection/research job accepts only the terminal ImportManifest ID and its frozen ContentVersions, never an ImportSession ID, upload grant, client path or half-written object.

## Content lineage

| Object | Key fields | Invariants |
|---|---|---|
| RawContentItem | workspace_id, collection_run_id/import_manifest_id, source external ID, raw_snapshot_uri, raw_digest, received_at | Ingestion trace. Raw body is object storage only, encrypted and access-controlled. |
| ContentItem | workspace_id, source_connection_id, source_item_id, canonical_url, identity_key, current_version_id, duplicate_cluster_id | Logical identity. Unique on workspace/source_connection/identity_key. |
| ContentVersion | workspace_id, content_item_id, version_number, content_digest, normalized_title/body, metadata_json, captured_at, raw_snapshot_uri, parser_version | Immutable. Unique content_item/version_number and content digest/identity lineage. |
| DuplicateCluster | workspace_id, method/version, canonical_content_version_id, confidence | A cluster never deletes independent records; membership preserves method and score. |
| IndependenceGroup | workspace_id, grouping_method/version, event_key, rationale | Distinguishes copied/reshared items from independently authored evidence. |
| Entity / EntityAlias | workspace_id, type, canonical name; alias/handle/domain | Designed now; initial slice may use watchlist entities only. |
| Topic / Mention / MetricSnapshot | workspace_id, classifier/version, time bucket and measure | Deferred beyond the narrow slice except where detection requires a normalized topic/key. |

ContentItem is mutable only for its current_version pointer and non-evidentiary organization metadata. ContentVersion is append-only. A connector change, edit discovered upstream, or manual parsing correction creates a new version; it never mutates an evidentiary body. Content stored from a local source has locality and transfer-policy labels on both RawContentItem and ContentVersion.

## Signals and scores

| Object | Key fields | Invariants |
|---|---|---|
| Signal | workspace_id, watchlist_id, detector_version, detection_window, baseline_window, status, current_metrics, baseline_metrics, explanation, scoring_policy_version | A detector result is versioned and references exact aggregate/input versions. |
| SignalEvidence | signal_id, content_version_id, role, independence_group_id, contribution, added_by | role is trigger, supporting, counter or excluded; cross-workspace content is forbidden. |
| DetectionScore | signal_id, raw_inputs_json, algorithm_version, numeric_score, level, calibration_status | Detector-owned and read-only; historical versions are immutable. |
| SignalAssessment | signal_id, dimension, suggested_level/rationale, suggestion_origin, suggestion_version, confirmed_level, confirmed_by, confirmed_at, version | dimension is business_impact or urgency. suggestion_origin is deterministic_rule, model or none; model requires a pinned model/prompt reference in suggestion_version. Suggestions are never confirmations; every confirmation/revision is audited. |
| SignalPriority | signal_id, impact_assessment_version, urgency_assessment_version, policy_version, status, level | status is pending_confirmation until both assessments exist, insufficient_input if either confirmed value is Unknown, otherwise derived with P0–P3. It is immutable per input/policy versions and never directly overridden in MVP. |

The four separately presented Signal dimensions are:

| dimension | Interpretation | Never substitute for |
|---|---|---|
| detection_confidence | Whether an observed change is likely real | business impact, urgency or priority |
| business_impact | Likely consequence to the workspace target | detector reliability |
| urgency | Time sensitivity | queue priority |
| priority | Workspace ordering outcome, such as P0–P3 | a probability or severity fact |

Initial levels are heuristic. calibration_status is uncalibrated until a versioned EvaluationRun establishes a source-specific calibration result. UI wording must be “heuristic level” or an equivalent label while uncalibrated. Business Impact and Urgency retain suggested and confirmed values separately. Unknown is a valid confirmation but cannot enter the Priority matrix. Manual assessments are human judgments, not model probabilities; Priority is a transparent derived ordering value, not an independent score.

## Investigation, research, evidence, and claim objects

| Object | Key fields | Invariants |
|---|---|---|
| Investigation | workspace_id, project_id, signal_id, current_scope_version_id, status, owner_id, current_synthesis_id, decision_brief_id | User work aggregate. MVP requires one originating Signal; it may contain multiple ResearchRuns but owns no raw source body. |
| InvestigationScopeVersion | investigation_id, version_number, decision_question, source_scope_json, time_range, budget, stop_conditions, created_by, change_reason | Immutable. Editing question/scope/budget creates a new version; old ResearchRuns keep their pinned version. |
| ResearchRun | workspace_id, investigation_id, investigation_scope_version_id, state, graph_version, run_input_manifest_uri/digest, budget, used_cost, attempt_number, initiated_by | Execution attempt inside one Investigation. Manifest and scope version are immutable after queueing; one state transition at a time. |
| ResearchTask | research_run_id, node_key, task_type, state, input_digest, output_digest, retry_count | Represents a business task, not an exposed LangGraph state. |
| RunEvent | investigation_id, research_run_id, sequence, event_id, type, payload_json, trace_id, occurred_at | Append-only; unique run/sequence and globally unique event_id. investigation_id must equal the owning Run. |
| ToolExecution | research_run_id, task_id, tool_name/version, policy_version, request_digest, response_digest, latency, status, error_class | Secret-free trace. Tool output that is persisted as evidence must create a ContentVersion. |
| Evidence | workspace_id, investigation_id, research_run_id, content_version_id, quote_start/end, quote_text_digest, stance, relevance, reliability, independence, recency, specificity, extraction_method | Immutable evidentiary anchor. Quote range must be in the exact ContentVersion and text digest must match it; Investigation must equal the owning Run. Review state is never written onto this row. |
| EvidenceReview | evidence_id, decision, reviewer_id, reason, policy_version, reviewed_at | Append-only exact-Evidence decision; valid/weak/rejected is a derived projection. A later decision does not rewrite the review snapshot used by a verified ClaimVersion. |
| Claim | workspace_id, investigation_id, research_run_id, current_version_id, aggregate_status, owner_id | Mutable aggregate pointer and concurrency boundary only; Claim text never lives on this row; Investigation must equal the owning Run. |
| ClaimVersion | claim_id, version_number, claim_type, text, confidence_inputs_json, confidence_level, calibration_status, limitations, model_run_id, created_by | Immutable content/version row. Revise creates a new version; review state is derived from append-only ClaimReview records, never stored by rewriting this row. |
| ClaimEvidence | claim_version_id, evidence_id, stance, weight, rationale, linked_by | Append-only link. ClaimVersion, Evidence and their owning Run must resolve to the same Investigation. stance is supports, opposes or neutral. A terminal ClaimReview freezes the complete link set; no later link may be added, and any stance/weight/link change creates a new ClaimVersion and new rows. |
| ClaimReview | claim_version_id, decision, claim_evidence_snapshot_json, evidence_review_snapshot_json, snapshot_digest, reviewer_id, reason, policy_version, reviewed_at | Append-only review of one exact version. A verify decision pins the exact ClaimEvidence IDs and EvidenceReview IDs/digest used; later Evidence reviews cannot rewrite that historical basis. A later verified ClaimVersion may supersede an older one without altering it. |

Persistence/wire naming is deliberate and generated from one RunEvent mapping: `research_run_id → run_id`, `type → event_type`, `payload_json → payload`, and `occurred_at → timestamp`; `event_id`, `sequence`, and `trace_id` keep their names. `ToolExecution` is not exposed as a raw public row. Pydantic/OpenAPI mapping and contract tests must prove all aliases and exact values; no second identifier/event schema exists.

Evidence score can be computed from relevance, reliability, independence, recency and specificity. ClaimVersion confidence uses deterministic stored inputs such as supporting/opposing evidence, source diversity and sample factor. LLMs may explain the score but cannot invent its numeric value. Claim confidence is also uncalibrated until validated; it must not be presented as a calibrated probability. row_version on Claim is optimistic concurrency only and never substitutes for ClaimVersion.

## Synthesis, Decision Brief, and export objects

| Object | Key fields | Invariants |
|---|---|---|
| InvestigationSynthesis | workspace_id, investigation_id, current_version_id | Technical aggregate pointer owned by exactly one Investigation; no independent owner, navigation or long-term decision lifecycle. |
| InvestigationSynthesisVersion | synthesis_id, version_number, verified_claim_version_snapshot_json, claim_review_snapshot_json, generation_method, generator_version, model_prompt_refs_json, executive_summary, business_implications, limitations, provenance_digest, created_by | Immutable intermediate synthesis content. generation_method is deterministic or model; model_prompt_refs_json must be empty for deterministic output and pinned for model output. The non-empty snapshot pins unique same-Investigation ClaimVersion IDs plus their verifying ClaimReview IDs/digest. Its own review state is derived from SynthesisReview; editing creates a new Draft version and review requirement. |
| SynthesisReview | synthesis_version_id, decision, reviewer_id, reason, policy_version, reviewed_at | Append-only review of one exact InvestigationSynthesisVersion. |
| DecisionBrief | workspace_id, investigation_id, current_version_id, status, owner_id, decision_outcome, next_checkpoint_at | Sole decision-level product object. At most one active Brief per Investigation in MVP. |
| DecisionBriefVersion | decision_brief_id, version_number, synthesis_version_id, synthesis_review_id, block_document, reference_snapshot_json, template_version, human_edit_digest, created_by | Immutable. Exactly one same-Investigation InvestigationSynthesisVersion plus its exact verifying SynthesisReview grounds the version. Fact/Synthesis references must be a subset of that synthesis snapshot and pin exact ClaimVersion, Evidence and ContentVersion records. Synthesis blocks carry generation_method/generator_version and preserve origin after human edit. |
| DecisionBriefReadinessReview | decision_brief_version_id, decision, reviewer_id, reason, policy_version, checklist_digest, reviewed_at | Append-only readiness decision for one exact version. DecisionBrief.status is the projection for current_version_id; a later edit creates a new Draft version and never changes the old review. |
| DecisionBriefFreshnessRecord | decision_brief_version_id, status, affected_reference_snapshot_json, reason, policy_version, assessed_at | Append-only exact-version assessment. status is current or evidence_stale. It never changes frozen references or the historical readiness review; current UI freshness is the latest record for the selected version. |
| BriefExport | workspace_id, decision_brief_version_id, export_type, destination, selection_manifest_json, reference_digest, policy_version, template_version, rendered_snapshot_uri, output_digest, created_by, created_at | Terminal immutable successful export record. prd_research_input is a rendered view, never an editable sibling object. Failed validation/transport is an idempotent command/AuditLog outcome, not a mutable BriefExport row. |
| Feedback | workspace_id, target_type/id/version, feedback_type, value, rationale, actor_id | Feedback affects future evaluation; it does not rewrite historic scores. |

A DecisionBriefVersion can be created only from exactly one verified InvestigationSynthesisVersion owned by the same Investigation. Direct ClaimVersion/Evidence/ContentVersion references are frozen block-level provenance derived from that synthesis snapshot, not an alternate creation path. DecisionReady additionally requires exact EvidenceReview/ClaimReview snapshots, explicit PM Judgment and limitations/counter-evidence handling; an append-only DecisionBriefReadinessReview records the decision. Export is a separate policy-checked command against one readiness-reviewed version. A later Evidence review/source change appends DecisionBriefFreshnessRecord(status=evidence_stale), never revokes or rewrites the old synthesis/Brief. Starting a revision creates a new Draft DecisionBriefVersion (optionally grounded in a newer verified synthesis), moves current_version_id/status to that new version, and preserves the old ready version and exports.

## Canonical state contracts

Closed enum values are shared with OpenAPI and generated clients:

| Object | Allowed primary states | Notes |
|---|---|---|
| ImportSession | draft, consented, uploaded, validating, finalized, failed, cancelled | finalized/cancelled are terminal. failed may retry only when retryable=true and all pinned digests, source pointer/version and the effective grant remain unchanged; success creates exactly one immutable ImportManifest. |
| Signal | new, triaged, investigating, explained, monitoring, dismissed | No converted state. |
| Investigation | draft, active, needs_input, reviewing, completed, closed_insufficient, cancelled | queued/running/failed belong to ResearchRun. A failed Run does not fail the Investigation. |
| ResearchRun | queued, running, waiting_for_input, completed, failed, cancelled | waiting_for_input has a closed reason enum; scope/budget/manifest changes create a new attempt. |
| Evidence review projection | proposed, valid, weak, rejected | Derived from append-only EvidenceReview; Evidence remains bound to one ContentVersion. |
| ClaimVersion review projection | proposed, needs_review, verified, rejected, superseded | Derived from immutable ClaimReview/version records; revise creates a new version. |
| InvestigationSynthesisVersion review projection | draft, needs_review, verified, rejected, superseded | Derived from immutable SynthesisReview/version records; intermediate synthesis only. |
| DecisionBrief current aggregate | draft, decision_ready, decided, archived | start_revision from decision_ready creates a new Draft version/current projection; it never demotes the old version. |
| DecisionBriefVersion readiness projection | draft, decision_ready | Derived from immutable DecisionBriefReadinessReview for an exact version. |
| DecisionBriefVersion freshness projection | current, evidence_stale | Derived from immutable DecisionBriefFreshnessRecord and orthogonal to readiness. |
| BriefExport | terminal immutable record only | Created only after successful validation/render; command failure never changes Brief status. |

## Evaluation, prompt and provenance objects

| Object | Key fields | Invariants |
|---|---|---|
| PromptVersion | workspace_id/global scope, purpose, semantic version, content digest, approved_by, effective_at | Immutable after approval; runs pin one version. |
| EvaluationDataset | workspace_id, task_type, version, manifest_uri/digest, source consent, split policy | Dataset examples have immutable labels and provenance. |
| EvaluationCase | dataset_id/version, input_manifest, expected labels, rubric, sensitivity_class | Raw sensitive text is minimized and access-restricted. |
| EvaluationRun | dataset_id/version, target graph/prompt/model/detector versions, metrics_json, assessor version, status | Results cannot be compared without version metadata. |
| ModelRun | provider/model, parameters, response digest, cost, trace_id | Stores metadata/digests, not secret keys. |

## Physical data constraints

- Every workspace-owned foreign key is checked against the same workspace in the domain service and enforced with composite keys/triggers where useful.
- Append-only tables: TransferConsentRecord, ContentVersion, ImportManifest, InvestigationScopeVersion, RunEvent, AuditLog, Evidence, EvidenceReview, ClaimVersion, ClaimEvidence, ClaimReview, InvestigationSynthesisVersion, SynthesisReview, DecisionBriefVersion, DecisionBriefReadinessReview, DecisionBriefFreshnessRecord, BriefExport, PromptVersion and completed EvaluationRun results.
- High-volume tables partition by workspace and time as scale requires: RawContentItem, ContentVersion, CollectionRun, RunEvent and MetricSnapshot.
- Core indexes: ImportSession source_connection/state and local_manifest_digest; partial unique active ImportSession per source_connection where state in (draft, consented, uploaded, validating, failed); TransferConsentRecord import_session/recorded_at; unique ImportManifest import_session_id; ContentItem identity key; ContentVersion content digest; collection stable key; Signal watchlist/status/window; Investigation signal/status/owner; ResearchRun investigation/state; RunEvent research_run_id/sequence; Evidence content_version_id; EvidenceReview evidence_id/reviewed_at; ClaimReview claim_version_id/reviewed_at; DecisionBrief investigation/status; Brief freshness version/assessed_at; RLS workspace predicates.
- Vector embeddings are derived from a named ContentVersion and embedding model/version. They are deleted/rebuilt with the governed source version.
- Soft deletion is a tombstone with retained provenance reference; physical deletion follows retention policy and object-store lifecycle.

## Seed and mock policy

Seed data is created through the same Pydantic commands and database schema as live content. It has an explicit non-production seed workspace; fixture connections use source_kind=imported_dataset, connector_type=seed_fixture and data_authenticity=seed rather than inventing a fourth source kind. Seeds use valid UUIDs, immutable ContentVersions, normal Investigations, RunEvents, evidence links and DecisionBriefVersions. UI fixtures may only mirror API response schemas and must be generated from seed fixtures or schema factories; they must never define a separate front-end-only Signal, Claim, Investigation or Decision Brief shape.
