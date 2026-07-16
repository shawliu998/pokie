# Glint Phase 0 API Contracts

## Contract principles

The API is a versioned REST resource API served under /v1. It exposes domain resources and commands, never raw LangGraph state, database rows, secret values or direct model/tool controls. The Mac client renders projections from these contracts; its SQLite cache and seed fixtures must use the same typed response shapes.

Every request is authenticated. The active workspace is resolved by the API from an explicit X-Workspace-ID membership context or a scoped route, not trusted merely because the client supplied an ID. Every resource response contains workspace_id, id, created_at, updated_at and row_version where it can be edited.

All timestamps are RFC 3339 UTC. IDs are UUIDs. JSON requests and responses use lower_snake_case. Unknown request fields are rejected. Server errors never expose stack traces, raw external bodies, secrets or authorization details.

## Common request semantics

| Concern | Contract |
|---|---|
| Authentication | Authorization: Bearer access token. The token identifies the person/device session, not a workspace role. |
| Workspace scope | X-Workspace-ID is required except workspace discovery/session endpoints. It must match an active membership. |
| Pagination | Cursor pagination: limit (1–100), cursor. Response has items and page: next_cursor/has_more. No client-side full collection assumption. |
| Filtering/sorting | Named allowlisted query parameters only. Invalid filters return 422. |
| Idempotency | Every POST/PATCH/DELETE command requires Idempotency-Key UUID. Server stores workspace, principal, route, normalized fingerprint, status and response for the retention window. Same key+same fingerprint replays original outcome; same key+different fingerprint returns 409. |
| Optimistic concurrency | PATCH and state/approval commands require If-Match: row_version or body expected_row_version. Stale writes return 412 with current resource version metadata. |
| Audit/correlation | X-Request-ID is accepted/generated and returned. Mutations produce an audit reference when applicable. trace_id may be returned for run diagnostics. |
| Long work | Commands enqueue durable work and return 202 with a resource/status URL; they do not hold a request open for collection or model execution. |

### Error envelope

~~~json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "The Decision Brief has changed; refresh before continuing.",
    "request_id": "uuid",
    "details": {
      "resource_id": "uuid",
      "current_row_version": 8
    }
  }
}
~~~

Representative codes are UNAUTHENTICATED (401), FORBIDDEN (403), NOT_FOUND (404), VERSION_CONFLICT (412), IDEMPOTENCY_CONFLICT (409), INVALID_STATE (409), ACTIVE_IMPORT_EXISTS (409), STALE_SOURCE_VERSION (412), CONSENT_EXPIRED_OR_REVOKED (409), OBJECT_SCOPE_MISMATCH (422), VALIDATION_ERROR (422), SOURCE_SCOPE_BLOCKED (422), APPROVAL_REQUIRED (409), RATE_LIMITED (429), and POLICY_BLOCKED (403). An unknown or expired SSE cursor is repaired inside the stream with a typed stream.reset control event, not a competing HTTP error contract.

## Typed shared representations

### Source connection summary

~~~json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "name": "GitHub public issues",
  "source_kind": "cloud",
  "runtime": "cloud",
  "connector_type": "github",
  "connector_version": "1.0.0",
  "status": "healthy",
  "freshness": {
    "last_success_at": "2026-07-15T05:00:00Z",
    "state": "current"
  },
  "capabilities": ["search", "fetch", "health"],
  "data_scope": "workspace_confidential",
  "row_version": 3
}
~~~

The shared schema reserves source_kind = cloud, local, imported_dataset and runtime = cloud, mac_device, static_import. Phase 1 accepts imported_dataset/runtime=static_import only; Phase 2 enables approved cloud/runtime=cloud GitHub/RSS. local/runtime=mac_device remains an ADR/schema seam and is rejected by the callable MVP API until a secure device protocol ships. It never serializes a credential reference. Imported Dataset has credential_ref=null, an import_manifest summary and no collection schedule. A connection response states status and scope, not whether a credential is valid in detail.

### Import session and terminal manifest

An import has two deliberately different resources. `ImportSession` is the mutable, row-versioned coordination resource; `ImportManifest` is created only after successful validation and is immutable. Neither resource accepts or returns a Mac filesystem path.

~~~json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "source_connection_id": "uuid",
  "expected_source_row_version": 1,
  "expected_current_import_manifest_id": null,
  "local_manifest_digest": "sha256:...",
  "file_digest": "sha256:...",
  "expected_upload_digest": "sha256:...",
  "client_file_name": "interviews.csv",
  "file_size_bytes": 48120,
  "media_type": "text/csv",
  "parser_version": "csv-v1",
  "schema_version": "interview-import-v1",
  "selected_scope_json": {"sheet": null, "columns": ["segment", "problem", "quote"]},
  "selected_scope_digest": "sha256:...",
  "state": "uploaded",
  "uploaded_object_key": "imports/uuid.csv",
  "uploaded_object_digest": "sha256:...",
  "terminal_manifest_id": null,
  "failure_code": null,
  "retryable": false,
  "row_version": 3
}
~~~

A successful finalize response resolves to a terminal manifest:

~~~json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "import_session_id": "uuid",
  "source_connection_id": "uuid",
  "file_digest": "sha256:...",
  "uploaded_object_key": "imports/uuid.csv",
  "uploaded_object_digest": "sha256:...",
  "parser_version": "csv-v1",
  "schema_version": "interview-import-v1",
  "selected_scope_digest": "sha256:...",
  "consent_record_id": "uuid",
  "normalized_payload_digest": "sha256:...",
  "content_count": 84,
  "finalized_at": "2026-07-15T05:00:00Z"
}
~~~

### Content and immutable version summary

~~~json
{
  "content_item_id": "uuid",
  "content_version_id": "uuid",
  "source_connection_id": "uuid",
  "title": "Example issue",
  "canonical_url": "https://github.com/org/repo/issues/42",
  "published_at": "2026-07-14T08:00:00Z",
  "captured_at": "2026-07-14T08:10:00Z",
  "version_number": 1,
  "content_digest": "sha256:...",
  "locality": "cloud",
  "availability": "captured",
  "duplicate_cluster_id": "uuid",
  "independence_group_id": "uuid"
}
~~~

The full source body is returned only to an authorized viewer through the version endpoint. A URL to an object snapshot is short-lived, authorized separately and never embedded in an SSE event.

### Signal

~~~json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "watchlist_id": "uuid",
  "title": "Permission complaints increased",
  "status": "new",
  "detector_version": "signal-v1",
  "window": {
    "current_start": "2026-07-08T00:00:00Z",
    "current_end": "2026-07-15T00:00:00Z",
    "baseline_start": "2026-06-10T00:00:00Z",
    "baseline_end": "2026-07-08T00:00:00Z"
  },
  "metrics": {
    "mention_count": 143,
    "independent_source_count": 42,
    "platform_count": 2
  },
  "dimensions": {
    "detection_confidence": {
      "level": "high",
      "calibration_status": "uncalibrated",
      "explanation": "Sufficient independent sources and stable cross-source change."
    },
    "business_impact": {
      "suggested_level": "medium",
      "suggested_explanation": "Matches an enterprise onboarding risk rule.",
      "suggestion_origin": "deterministic_rule",
      "suggestion_version": "impact-rules-v1",
      "confirmed_level": null,
      "confirmed_by": null,
      "confirmed_at": null
    },
    "urgency": {
      "suggested_level": "monitor",
      "suggested_explanation": "No immediate deadline or accelerating incident.",
      "suggestion_origin": "deterministic_rule",
      "suggestion_version": "urgency-rules-v1",
      "confirmed_level": null,
      "confirmed_by": null,
      "confirmed_at": null
    },
    "priority": {
      "level": null,
      "status": "pending_confirmation",
      "policy_version": "priority-matrix-v1",
      "explanation": "Confirm Business Impact and Urgency to derive Priority."
    }
  },
  "row_version": 5
}
~~~

The API never returns a single overloaded severity field. Detection Confidence is detector-owned and read-only. Business Impact and Urgency keep suggestions separate from human confirmations and always return suggestion_origin/suggestion_version; model origin is invalid before the Phase 3 policy-approved runtime. Priority is null/pending_confirmation until both are confirmed; if either confirmed_level is unknown it remains null/insufficient_input; only two rankable confirmed levels produce P0–P3/derived from their exact versions and policy_version. There is no direct Priority override in MVP. Numeric internal score inputs are available only in an authorized analysis endpoint and are labelled uncalibrated until evaluated.

### Evidence and Claim

~~~json
{
  "evidence": {
    "id": "uuid",
    "investigation_id": "uuid",
    "research_run_id": "uuid",
    "content_version_id": "uuid",
    "quote_start": 120,
    "quote_end": 245,
    "quote_text": "The cited excerpt",
    "quote_text_digest": "sha256:...",
    "stance": "supports",
    "status": "valid",
    "provenance": {"research_run_id": "uuid", "extraction_method": "llm_proposal"}
  },
  "claim": {
    "id": "uuid",
    "claim_version_id": "uuid",
    "version_number": 2,
    "investigation_id": "uuid",
    "research_run_id": "uuid",
    "text": "A bounded conclusion.",
    "status": "needs_review",
    "confidence_level": "medium",
    "calibration_status": "uncalibrated",
    "limitations": ["Source coverage is limited to GitHub and RSS."],
    "evidence_links": [
      {"evidence_id": "uuid", "stance": "supports", "weight": 0.72}
    ],
    "row_version": 2
  }
}
~~~

Evidence creation is server-only through ingestion/research proposal validation or a human evidence command; clients cannot fabricate quote offsets, source body or provenance. The displayed Evidence status and Claim status are projections from latest immutable review records, not mutable fields on Evidence/ClaimVersion content. Claim confidence numeric inputs are not writable by an LLM/client endpoint.

## Workspace, project, and watchlist

| Method and path | Purpose | Role / notes |
|---|---|---|
| GET /v1/workspaces | List caller memberships | Authentication only |
| POST /v1/workspaces | Create workspace | Owner creator; audited |
| GET/PATCH /v1/workspaces/{id} | Read/update workspace settings | scope/role enforced |
| GET /v1/navigation-summary | Current workspace work counts/status for the Sidebar | Exact aggregate query; freshness timestamp; no pagination approximation |
| GET/POST /v1/projects | List/create projects | Owner operator in Phase 1; Analyst+ policy activates in Phase 4 |
| GET/PATCH /v1/projects/{id} | Project details/edit | project scope |
| GET/POST /v1/watchlists | List/create | Owner operator in Phase 1; rules are structured |
| GET/PATCH /v1/watchlists/{id} | Read/edit draft watchlist | If-Match on PATCH |
| POST /v1/watchlists/{id}/activate | Validate and activate rule version | Owner operator in Phase 1; source policy and audit |
| POST /v1/watchlists/{id}/pause | Pause future collection/detection | Owner operator in Phase 1; audit |

POST /v1/watchlists accepts objective, project_id, entities, query rules, source_connection_ids, cadence, time window/baseline and notification intent. Natural-language assistance, if available, is a proposal endpoint returning structured draft rules; it does not create or activate a Watchlist.

navigation-summary returns unreviewed_signal_count, investigation_needs_input_count, draft_decision_brief_count, monitoring_health and computed_at. Counts are authorization-scoped server aggregates (the client may display 99+), not totals inferred from a cursor page. A destination omitted by the current phase is also omitted from this summary.

## Sources and imports

| Method and path | Purpose | Notes |
|---|---|---|
| GET /v1/sources | List source health/scope | Does not expose credentials |
| POST /v1/sources | Create draft source connection | Phase-gated: Imported Dataset in Phase 1, approved Cloud source in Phase 2; local returns POLICY_BLOCKED |
| GET/PATCH /v1/sources/{id} | Read/edit non-secret config | Scope/kind changes require confirmation/audit |
| POST /v1/sources/{id}/validate | Queue capability/health check | 202; check uses least privilege |
| POST /v1/sources/{id}/activate | Enable an approved source | policy/role/state check |
| POST /v1/sources/{id}/disable | Disable collection | audited |
| POST /v1/imports | Create a draft ImportSession from local metadata/digests and expected SourceConnection pointer/version | No path/body transfer; one non-terminal session per source; returns the session and row_version |
| GET /v1/imports/{id} | Read ImportSession state, failure and terminal manifest link | Workspace scoped; never returns an upload credential |
| POST /v1/imports/{id}/upload-consent | Append an exact TransferConsentRecord grant and issue a short-lived upload grant | draft only; confirmation/audit required |
| POST /v1/imports/{id}/upload-complete | Resolve effective consent; verify object key/existence/size/type/digest; mark uploaded | consented plus effective unexpired/unrevoked grant; If-Match and idempotency required |
| POST /v1/imports/{id}/finalize | Validate and create Imported Dataset content plus terminal ImportManifest | uploaded or retryable failed only; 202 and idempotent |
| POST /v1/imports/{id}/cancel | Cooperatively cancel an unfinished session | If granted, append exact revoke record; invalidate capability, clean staging, create no manifest/content and audit |
| GET /v1/collection-runs | Collection history and counters | paginated |

A local import begins by posting only file metadata, file_digest, expected_upload_digest, local_manifest_digest, parser/schema versions, selected_scope_json/digest, expected_source_row_version and expected_current_import_manifest_id. The local manifest canonically covers the content values. The response ID is an ImportSession ID, not a draft ImportManifest. A partial unique constraint allows only one draft/consented/uploaded/validating/failed session per SourceConnection; creating another returns ACTIVE_IMPORT_EXISTS until the user finishes or cancels the earlier one. Changing source file bytes, transfer payload bytes, parser/schema version, selected scope or expected source pointer requires a new session.

Upload consent pins the session ID, exact source-file/expected-upload/local-manifest/scope digests, destination workspace, object key, maximum bytes, media type, policy version and expiry in an append-only TransferConsentRecord. Phase 1 sets model_egress_authorization=none: upload consent authorizes workspace storage only and cannot silently authorize a later model provider. The short-lived upload grant is scoped to that object key and expires with the consent. The effective-consent resolver requires the exact grant, current time before expires_at, all pinned values unchanged and no later TransferConsentRecord(decision=revoke, supersedes_id=grant_id). Both upload-complete and finalize call that resolver; session state alone is never authorization.

`upload-complete` trusts the object store's observed key/length/media type/digest, not a client claim, and requires the digest to equal expected_upload_digest. Mismatch moves the session to non-retryable failed, quarantines/schedules deletion of the object and creates no visible content. `finalize` moves uploaded → validating and returns a status URL for a dedicated ImportFinalizationJob whose internal payload pins workspace_id, import_session_id, finalize_command_id, expected session/source row versions and expected source manifest pointer. That job is the sole worker allowed to resolve an ImportSession: it revalidates effective consent and pinned inputs, stages parsing/normalization, then in one domain transaction creates imported RawContentItem/ContentItem/ContentVersion rows, exactly one terminal ImportManifest, compare-and-sets SourceConnection.current_import_manifest_id, and marks the session finalized. A stale source pointer fails without visible rows/manifest. Validation/cancellation failure writes session/AuditLog, revokes and cleans staged bytes as applicable, but creates no manifest or visible content. A retryable failure may repeat finalize only when every pinned value and consent remain unchanged; otherwise the user cancels and creates a new session.

After that commit, downstream dedupe/detection/research jobs receive only import_manifest_id plus frozen ContentVersion references and never normalize the upload again. Cancel is the executable revoke command: when an effective grant exists, its transaction appends decision=revoke with supersedes_id=grant_id before invalidating the object capability and transitioning the session. A cancel/finalize race is resolved by If-Match/row-version compare-and-set; only one terminal outcome wins.

The server refuses content bearing locality=local_only. The app must not use a generic file upload endpoint for local source data, and no request may serialize a Mac path.

## Content, signals and actions

| Method and path | Purpose |
|---|---|
| GET /v1/content-items | Search/paginate content summaries |
| GET /v1/content-items/{id}/versions | List captured versions |
| GET /v1/content-versions/{id} | Authorized version viewer, quote-capable body |
| GET /v1/signals | Signal Inbox query with allowlisted filters |
| GET /v1/signals/{id} | Detail, explanations, samples, state |
| GET /v1/signals/{id}/evidence | SignalEvidence and immutable content references |
| POST /v1/signals/{id}/triage | Atomically confirm Impact/Urgency, derive Priority status/value and transition New → Triaged |
| POST /v1/signals/{id}/transitions | State change command |
| POST /v1/signals/{id}/assessments | Confirm or revise Business Impact / Urgency |

Atomic triage request:

~~~json
{
  "expected_signal_row_version": 5,
  "business_impact": {
    "confirmed_level": "high",
    "reason": "Matches the enterprise onboarding risk currently under review.",
    "expected_assessment_version": 0
  },
  "urgency": {
    "confirmed_level": "this_week",
    "reason": "Quarterly priority review closes this week.",
    "expected_assessment_version": 0
  }
}
~~~

The triage command requires both human decisions (each rankable level or unknown), reasons, expected assessment versions and expected Signal row_version; expected_assessment_version=0 asserts that no prior revision exists. In one transaction it appends both assessment revisions, writes the derived/pending Priority projection, transitions New to Triaged and writes AuditLog; retries are covered by Idempotency-Key. Unknown is a valid confirmation but produces null/insufficient_input, never a fabricated P0–P3. The separate assessment endpoint accepts only one business_impact or urgency revision on an already-triaged Signal, then recomputes Priority from both latest exact versions. General transitions handle non-assessment actions such as investigate, explain, monitor or dismiss. Detection Confidence and Priority have no write endpoint in MVP.

Assignments, invitations, separation-of-duty review routes and role-management commands are not exposed in the Phase 1 API. They begin in Phase 4 against the same workspace-scoped objects. Reviewer is an assignment/duty for an authorized Owner/Admin/Analyst, never a sixth WorkspaceMember.role.

## Investigations, Research Runs, and proposal lifecycle

Investigation is the user-facing aggregate. MVP Investigations start from a Signal, retain the Decision Question and scope, contain one or more Research Runs, and produce at most one active Decision Brief. ResearchRun remains an execution record and is never exposed as a competing top-level PM object.

| Method and path | Purpose | Notes |
|---|---|---|
| POST /v1/investigations | Create draft and InvestigationScopeVersion 1 from one Signal | Owner PM path in MVP; idempotent; derives initial authorized scope |
| GET /v1/investigations | List/filter by status/signal/project | Paginated |
| GET/PATCH /v1/investigations/{id} | Read/edit Decision Question and bounded scope | PATCH only while draft or needs_input; creates a new immutable scope version; If-Match required |
| GET /v1/investigations/{id}/scope-versions | List immutable Decision Question/scope/budget history | Run snapshots identify their pinned version |
| POST /v1/investigations/{id}/transitions | Activate, provide input, review, complete, close insufficient or cancel | Canonical state machine below |
| GET /v1/investigations/{id}/research-runs | Execution attempts and summaries | Not a top-level navigation contract |

Canonical Investigation states are draft, active, needs_input, reviewing, completed, closed_insufficient and cancelled. The transition endpoint accepts only activate, request_input, provide_input, start_review, complete, close_insufficient and cancel when their documented preconditions hold. It never accepts queued, running or failed; those are ResearchRun states. A failed Run leaves the Investigation active or needs_input.

| Method and path | Purpose | Notes |
|---|---|---|
| POST /v1/research-runs | Create and queue a bounded run inside an Investigation | 202; authorized owner; investigation and approved scope required |
| GET /v1/research-runs | List/filter by state/investigation/signal/project | paginated |
| GET /v1/research-runs/{id} | Snapshot: state, tasks, budget, manifest summary, latest sequence | hides graph internals by default |
| POST /v1/research-runs/{id}/cancel | Cooperative cancellation | state/version checked |
| POST /v1/research-runs/{id}/plan-approval | Approve/edit/reject a model-proposed plan | Phase 3; not registered/callable in Phase 1 |
| POST /v1/research-runs/{id}/claim-review | Batch review typed ClaimVersion proposals | Human gate |
| GET /v1/research-runs/{id}/events | SSE durable event stream | See SSE section |
| GET /v1/research-runs/{id}/trace | Authorized redacted diagnostic trace | Owner operator under Phase 1 debug policy; Analyst+ policy activates in Phase 4 |

Canonical ResearchRun states are queued, running, waiting_for_input, completed, failed and cancelled. waiting_for_input.reason is one of scope_clarification, plan_change, budget_change, claim_review or source_policy. Resume is valid only against the same immutable manifest/checkpoint; a scope, budget or manifest change creates a new attempt.

Create request:

~~~json
{
  "investigation_id": "uuid",
  "investigation_scope_version_id": "uuid",
  "question": "What is driving the change and what should the product team decide?",
  "source_scope": {
    "source_connection_ids": ["uuid"],
    "content_version_ids": ["uuid"],
    "allow_cloud_model": false
  },
  "time_range": {
    "start": "2026-07-08T00:00:00Z",
    "end": "2026-07-15T00:00:00Z"
  },
  "budget": {"max_cost_usd": 4.00, "max_duration_seconds": 900},
  "expected_investigation_row_version": 5
}
~~~

The server verifies that investigation_scope_version_id belongs to the Investigation and matches the explicitly selected/current scope, derives the originating Signal and Watchlist, then constructs the immutable RunInputManifest from authorized pinned versions. The client cannot submit tool calls, graph nodes, prompt text, raw local source content, a final claim or a final synthesis. source_scope is checked against the pinned InvestigationScopeVersion, locality, source status, workspace model-egress policy and user consent. Phase 1 requires allow_cloud_model=false and uses the deterministic provider; Phase 3 may accept true only when workspace policy, consent and the registered bounded graph permit it. A blocked request returns POLICY_BLOCKED or SOURCE_SCOPE_BLOCKED with safe remediation metadata.

Claim review request:

~~~json
{
  "expected_run_row_version": 7,
  "decisions": [
    {
      "claim_id": "uuid",
      "claim_version_id": "uuid",
      "expected_claim_row_version": 2,
      "decision": "verify",
      "evidence_review_ids": ["uuid"],
      "expected_claim_evidence_snapshot_digest": "sha256:...",
      "reason": "Support and counter evidence are correctly represented."
    },
    {
      "claim_id": "uuid",
      "claim_version_id": "uuid",
      "expected_claim_row_version": 1,
      "decision": "request_more_evidence",
      "reason": "Need independent sources outside the copied issue thread."
    }
  ]
}
~~~

A verify review decision transitions that exact ClaimVersion projection to verified only if role/policy permits and the server confirms immutable same-Investigation ClaimEvidence links plus the supplied exact EvidenceReview IDs/digest. It appends ClaimReview with the complete frozen link/review snapshots; after a terminal review the server rejects any new ClaimEvidence for that version and never rewrites ClaimVersion, ClaimEvidence or Evidence content. A later EvidenceReview may make current evidence weak/rejected and drive Brief freshness, but cannot alter the historical ClaimReview; using the changed basis requires a new ClaimVersion/review. Request_more_evidence returns the run to a bounded retrieval state; it cannot expand its source scope/budget without a new plan approval. Rejected proposals remain available as provenance but cannot feed a verified InvestigationSynthesisVersion or a DecisionReady Brief.

## SSE event contract and recovery

Endpoint:

~~~text
GET /v1/research-runs/{run_id}/events
Accept: text/event-stream
Last-Event-ID: {previous event_id}
X-Workspace-ID: {workspace}
~~~

The client first fetches the authoritative GET /v1/research-runs/{id} snapshot and stores latest_sequence. The SSE endpoint then sends only durable RunEvents after the supplied cursor in increasing sequence. It does not send a second run.snapshot event. Event IDs are UUIDs. The event data shape is:

~~~text
id: 6eb2e2b4-...
event: claim.version_proposed
data: {"event_id":"6eb2e2b4-...","run_id":"...","sequence":14,"timestamp":"2026-07-15T05:10:00Z","event_type":"claim.version_proposed","trace_id":"...","payload":{"claim_id":"...","claim_version_id":"...","status":"needs_review"}}

~~~

The closed business event_type enum is run.queued, run.started, run.waiting_for_input, run.resumed, run.completed, run.failed, run.cancelled; task.started, task.completed, task.failed; tool.started, tool.completed, tool.failed; evidence.proposed, evidence.reviewed; claim.version_proposed, claim.version_reviewed, claim.version_superseded; synthesis.proposed, synthesis.reviewed; and review.required. stream.reset is the only typed transport-control event and carries no business sequence. The generated persistence mapping is `research_run_id → run_id`, `type → event_type`, `payload_json → payload`, and `occurred_at → timestamp`; contract tests assert identical values and no second event schema. Payloads are event-specific schemas and contain IDs/safe summaries, never raw secrets, opaque tool requests, arbitrary model transcript or signed object URLs.

Recovery requirements:

1. Client persists event_id and sequence after applying an event.
2. On reconnect, it sends Last-Event-ID. The server replays committed events after that event in sequence order before tailing live events.
3. Client ignores duplicate event_id and any event whose sequence is not greater than its stored projection sequence.
4. If Last-Event-ID is unknown or outside the retained replay window, the authorized stream emits stream.reset with snapshot_url and latest_sequence, then closes. The client fetches that snapshot, replaces its projection and reconnects. stream.reset, snapshot fetches and heartbeat comments do not consume business sequence numbers.
5. heartbeat comments are sent at most every 15 seconds and do not have event_id/sequence.
6. On a detected gap, the client fetches GET /v1/research-runs/{id}, replaces its projection, and reconnects.

SSE is read-only. Review and cancellation always use normal REST commands with idempotency and version checks.

## Evidence, claims, synthesis, Decision Brief, and export

Canonical review projections match the domain model: Evidence is proposed, valid, weak or rejected; ClaimVersion is proposed, needs_review, verified, rejected or superseded; InvestigationSynthesisVersion is draft, needs_review, verified, rejected or superseded; DecisionBrief is draft, decision_ready, decided or archived. Evidence, Claim, synthesis and Brief readiness decisions append immutable exact-version review records; response states are derived projections, not mutations of evidentiary/version content. DecisionBriefFreshnessRecord separately derives current/evidence_stale for an exact BriefVersion. BriefExport has no lifecycle state: it is a terminal immutable record created only after successful validation and rendering.

| Method and path | Purpose |
|---|---|
| GET /v1/evidence/{id} | View exact version binding, quote and assessments |
| POST /v1/evidence/{id}/review | Append EvidenceReview(valid/weak/rejected) with reason; never mutate Evidence |
| GET /v1/claims | List claims by run/investigation/synthesis/status |
| GET /v1/claims/{id} | Detail, score inputs and evidence links |
| GET /v1/claims/{id}/versions | List immutable ClaimVersions |
| POST /v1/claims/{id}/versions | Revise by creating a new proposed ClaimVersion; never mutate reviewed text |
| POST /v1/claims/{id}/versions/{version_id}/review | Verify/reject/request more evidence for one immutable version |
| POST /v1/investigations/{id}/synthesis | Create the Investigation-owned synthesis Draft from verified ClaimVersions |
| GET/PATCH /v1/investigations/{id}/synthesis | Read/edit the Investigation-owned synthesis; PATCH creates a new version |
| POST /v1/investigations/{id}/synthesis/versions/{version_id}/review | Verify/reject one InvestigationSynthesisVersion |
| POST /v1/investigations/{id}/decision-brief | Create or return the Investigation's active Draft Decision Brief |
| GET /v1/decision-briefs | Paginated Decisions list filtered by status/investigation/project/freshness |
| GET/PATCH /v1/decision-briefs/{id} | Read/edit current Draft; PATCH creates a new immutable Draft version and is rejected once current version is ready |
| POST /v1/decision-briefs/{id}/revisions | Start a new Draft version from an exact ready base version and one verified synthesis version |
| POST /v1/decision-briefs/{id}/mark-decision-ready | Validate one exact version and append DecisionBriefReadinessReview |
| GET /v1/decision-briefs/{id}/versions/{version_id}/freshness | Read latest exact-version freshness projection/records |
| POST /v1/decision-briefs/{id}/versions/{version_id}/freshness/recheck | Re-evaluate references and append DecisionBriefFreshnessRecord |
| POST /v1/decision-briefs/{id}/record-decision | Record decision/outcome; designed now, not in first production slice |
| POST /v1/decision-briefs/{id}/exports/preview | Render a non-persisted PRD Research Input preview for one exact version |
| POST /v1/decision-briefs/{id}/exports | Execute policy-checked Markdown copy/download and create BriefExport |
| GET /v1/brief-exports/{id} | Read immutable export metadata; output retrieval is separately authorized |

Synthesis creation body contains a non-empty, duplicate-free verified_claim_version_ids list; the server rejects any ID whose exact version is not verified or does not belong to that same Investigation, resolves and pins each exact verifying ClaimReview ID/digest, then produces an immutable InvestigationSynthesisVersion. To verify, the review endpoint must include synthesis_version_id, expected_row_version, decision, reason and any limitations required by policy. There is no top-level /insights collection or independent owner/lifecycle, and synthesis cannot be exported as the decision artifact.

Decision Brief creation uses:

~~~json
{
  "synthesis_version_id": "uuid",
  "template_version": "decision-brief-v1"
}
~~~

The server requires exactly one verified synthesis_version_id owned by the same Investigation and pins its exact verifying synthesis_review_id. The response includes both IDs, a frozen reference manifest and typed blocks for Fact, Synthesis, PM Judgment and Recommendation. Each Synthesis block exposes generation_method and generator_version; model output additionally exposes pinned model/prompt references, while deterministic output must not be labelled AI. Every direct Fact/Synthesis reference must be a subset of the synthesis's verified ClaimVersion snapshot and resolve ClaimVersion → frozen ClaimEvidence/EvidenceReview snapshot → Evidence → ContentVersion; these block references are provenance, not a bypass around synthesis. Updating any ClaimVersion or InvestigationSynthesisVersion does not mutate a DecisionBriefVersion. mark-decision-ready requires decision_brief_version_id and expected_row_version, rejects unsupported factual blocks, missing limitations/counter-evidence handling, unresolved recommendation state or missing PM Judgment, and appends an immutable DecisionBriefReadinessReview plus current freshness record. Once ready, PATCH is rejected; start-revision explicitly supplies base_decision_brief_version_id and one verified synthesis_version_id, creates a new Draft version/current pointer and preserves the old readiness/freshness/export history. PRD Research Input is rendered from one DecisionBriefVersion; it has no create/edit endpoint. MVP export is Preview plus Copy Markdown / .md download, with role, readiness, current freshness, reference validity, locality and audit checks.

Both export commands require decision_brief_version_id, export_type and an explicit selection_manifest. Allowed PRD blocks are selected Facts, confirmed PM Judgment, accepted Recommendation and citations; Synthesis blocks, rejected/unverified content and internal run metadata are forbidden. Preview returns rendered content and a reference_digest without creating a content object. Execute also requires that reference_digest; after readiness/freshness/reference revalidation it returns 201 and creates one immutable BriefExport with the selection manifest, reference digest, rendered snapshot/output digest, actor, timestamp and policy/template versions. Validation or rendering failure creates no BriefExport row and is captured by the idempotent command outcome/AuditLog. Repeating the same Idempotency-Key replays the successful record or failure and never forks an editable PRD document.

## Evaluation, feedback, and audit

Phase 1 implements the fixed seed evaluation smoke, mutation AuditLog writes and the minimum authorized audit query needed for verification. General dataset/run management and richer evaluation/trace operations activate with the Phase 3 research runtime; broader team audit/evaluation UI and non-Owner role behavior remain Phase 4. Reserved routes do not imply a clickable or callable surface before their phase gate.

| Method and path | Purpose |
|---|---|
| GET/POST /v1/evaluation-datasets | Read/create versioned approved dataset manifests |
| POST /v1/evaluation-runs | Queue evaluation with candidate/dataset versions |
| GET /v1/evaluation-runs/{id} | Read results/raw counts/limitations |
| POST /v1/feedback | Record feedback for exact target version |
| GET /v1/audit-logs | Authorized filtered append-only audit view |
| GET /v1/sync/bootstrap | Fetch cached projections/cursors for a workspace |

sync/bootstrap is read-only. It returns authorized projections, freshness and cursors for cached browsing; it accepts no domain mutation. MVP has no offline operation queue, conflict merge or hidden write endpoint. Those capabilities require a later contract and UX review.

## Contract compatibility and testing

The API publishes OpenAPI from Pydantic models and maintains examples/JSON schema fixtures for each connector and core resource. Additive response fields are backward compatible; removing/renaming fields, changing enum semantics or changing approval/event meaning requires a versioned endpoint or explicit deprecation window.

Contract tests cover authorization/RLS, malformed schema, pagination, idempotency replay/conflict, If-Match conflict, source-kind boundary, Investigation/ResearchRun state transitions, immutable EvidenceReview/ClaimEvidence/ClaimReview/SynthesisReview/DecisionBriefReadinessReview/FreshnessRecord projections, explicit ready→new-Draft revision, SSE replay/reset/duplicate and persistence-wire aliases, exact Evidence offsets, the single verified synthesis prerequisite, PRD Synthesis exclusion, BriefExport version/selection/digest binding, connector Search/Fetch/Health error modes and seed/live schema parity. The Tauri client must test against the same generated contracts, not hand-maintained mock interfaces.
