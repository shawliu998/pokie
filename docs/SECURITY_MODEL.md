# Glint Phase 0 Security Model

## Security posture

Glint processes potentially sensitive team research and untrusted external content. The primary security properties are: correct workspace isolation; explicit control of local-to-cloud movement; no exposure of credentials; evidence integrity; least-privilege tools; auditable approvals and high-risk actions; and resilience to hostile text, URLs and files.

Security is a release requirement for the walking skeleton, not a Phase 6 retrofit. An unavailable connector, untrusted page, unverifiable citation, or stale authorization state fails closed for writes and external actions.

## Trust zones and data classification

| Zone | Trust level | Permitted data |
|---|---|---|
| Mac UI and Keychain | User/device trust boundary | User session, device-scoped credential references, local-only source content and drafts |
| Cloud API/worker/database | Glint service boundary | Workspace-scoped approved cloud data, uploaded imports, provenance, derived metadata |
| Object storage | Restricted cloud boundary | Encrypted raw snapshots, imported blobs, immutable manifests |
| Connector/model provider | External processor | Minimum approved request content only |
| Untrusted content | Never instruction-bearing | Web/RSS/GitHub text, files, pasted text, tool responses and model text |

Data has a locality/sensitivity label: public, workspace-confidential, restricted, local-only or seed. A label travels from source/import manifest to ContentVersion, Evidence, run manifest, export checks and logs. Derived embeddings, snippets and model prompts inherit the most restrictive applicable label.

## Identity, tenancy, and authorization

The API authenticates every request and resolves a single active workspace. Authorization is enforced in three layers:

1. API policy checks the authenticated principal, workspace membership, role, object project and action.
2. Domain services repeat critical authorization and state checks before mutation, including worker-initiated commands.
3. PostgreSQL row-level security scopes workspace tables using a transaction-local workspace/principal context. Service accounts have narrowly scoped, audited roles.

The client must not be trusted to supply a workspace ID, a role, an approval state, a source kind, or an export eligibility flag. Object lookup enforces workspace scope before revealing whether it exists. Background jobs carry workspace and initiating-principal provenance; a worker cannot act as an unbounded superuser.

The first production experience is intentionally single-seat: one Owner PM can triage, start an Investigation, review ClaimVersions, verify the intermediate synthesis and mark a Brief DecisionReady. Workspace scope, deny-by-default authorization, RLS and AuditLog are still real from Phase 1. Invitations, separation-of-duty review UX and the full five-role collaboration matrix below are a Phase 4 policy target; non-Owner roles are not assignable or reachable through Phase 1 API/UI. “Reviewer” is a duty/assignment performed by an authorized Owner, Admin or Analyst, not a sixth WorkspaceMember.role.

| Action | Owner | Admin | Analyst | Contributor | Viewer |
|---|---:|---:|---:|---:|---:|
| Manage workspace/members/retention | yes | limited | no | no | no |
| Add/remove Cloud Source | yes | yes | no | no | no |
| Configure Local Source on own Mac | yes | yes | yes | limited | no |
| Create/edit Watchlist | yes | yes | yes | limited | no |
| Triage Signal/start Research | yes | yes | yes | yes | no |
| Review/verify ClaimVersion or Investigation synthesis | yes | yes | yes | no | no |
| Create/edit Draft Decision Brief | yes | yes | yes | yes | no |
| Approve external export | yes | policy-limited | no by default | no | no |
| Read AuditLog/Evaluation | yes | yes | limited | no | no |

Workspace policy can narrow this matrix, never broaden it. Production has no default “anyone can verify or export” setting.

## Approval semantics and integrity

An LLM or worker can only submit a typed proposal through a Domain Service. It cannot mark a ClaimVersion verified, an InvestigationSynthesisVersion verified, a Decision Brief DecisionReady, an export authorized, a source connection active, or a Signal assessment confirmed.

An approval command contains actor, role, target version, decision, reason, policy version, request ID and timestamp. Claim verification also pins exact immutable ClaimEvidence/EvidenceReview IDs and a snapshot digest. It uses If-Match/row_version so an approval of an obsolete ClaimVersion, InvestigationSynthesisVersion or DecisionBriefVersion fails. Approval creates an immutable review record and AuditLog entry. Edit-after-verification creates a new version with a new review requirement; it never alters the approved evidence snapshot. Later evidence changes append an exact-version freshness record and cannot rewrite historic approval.

High-risk actions that always produce an AuditLog and, where configured, a confirmation UI are:

- adding/removing a source connection or changing source scope;
- activating or materially changing Watchlist/detector rules;
- transferring Local Source data to cloud;
- deleting data, changing retention, or exporting data;
- changing a verified Investigation synthesis or DecisionReady Brief, score/detector model, prompt or tool policy;
- overriding a Signal dimension;
- approving an external report or outbound notification.

## Secrets and session protection

Credentials, cookies, API keys and refresh tokens are never stored in PostgreSQL, Redis, SQLite, event payloads, logs, prompts or Langfuse traces. The Mac stores device credentials in macOS Keychain or Tauri Stronghold. The cloud uses a managed secret store; the database stores a non-secret credential reference, scope, expiration metadata and last health status only.

Secrets are redacted before telemetry/logging and detected by response scrubbers. Connector adapters receive the narrow credential needed for the requested capability. They cannot return it in a tool result. Rotation, revocation, expiry and invalid-credential responses are modelled explicitly. A local cookie is never uploaded to the cloud and cannot authorize a Cloud Source.

Use TLS for all network paths, encryption at rest for databases/object storage/backups, signed/short-lived object URLs, environment separation, least-privilege service accounts, dependency/SBOM scanning, and signed application updates. Session tokens are short-lived, audience-bound and stored using the platform secure storage rather than local SQLite.

## Prompt injection and hostile content

All external and user-provided content is untrusted data. Its presence cannot modify policy or instruction hierarchy.

- Prompts delimit source material as untrusted, quote it rather than concatenate it into instructions, and tell models to treat embedded commands as content.
- The model only sees a structured tool catalog selected by server policy. Tool inputs/outputs use Pydantic schemas, enum allowlists and maximum sizes.
- Agent tools are read-only capabilities: search or fetch approved content and read scoped metadata. A proposal is typed graph output, not a write-capable tool call; only a Domain Service may persist it after authorization and schema/policy validation. External export is a separate human command outside the graph.
- The graph validates source IDs, ContentVersion IDs and evidence offsets after each LLM node. It rejects citations to absent or out-of-scope content.
- Reviewer rules scan source and model outputs for instruction-injection indicators, policy bypass claims, unexpected tool requests and exfiltration attempts. A flagged run pauses or fails rather than auto-persisting.
- Users cannot use prompt text to change workspace policy, data scope, approval state, model configuration or tool allowlist.

Prompt injection testing uses adversarial content fixtures in the evaluation dataset and verifies both no unauthorized tool call and no unsupported claim.

## SSRF, web fetch and file safety

Connector fetches use an outbound egress policy, not arbitrary model-supplied URLs. DNS resolution and the final redirect target are validated; private, loopback, link-local, multicast and metadata-service ranges are blocked for IPv4 and IPv6. Only HTTPS is allowed by default, redirect count/response size/time are bounded, DNS rebinding is mitigated by connect-time validation, and connector-specific allowlists are preferred.

The initial scope uses GitHub API and configured RSS feeds; arbitrary web crawling is deferred. A URL inside a source item is data, not permission to fetch.

Imported files are selected locally, size/type limited, malware-scanned when available, and parsed in an isolated process with CPU/memory/time limits. Archive recursion, executable macros and remote external references are disabled. File parsers emit a digest and extracted content; they do not execute embedded code. CSV formula injection is neutralized before export. Raw local files stay local unless the user explicitly approves a session-, digest-, scope-, destination-, object-key-, byte-limit- and expiry-bound cloud upload.

ImportSession carries metadata/digests plus expected SourceConnection pointer/version only and never a Mac path. Each TransferConsentRecord is append-only; effective consent means the exact grant is unexpired and has no later revoke that supersedes it, and upload consent never implies model-provider egress. Upload credentials are short-lived and single-object scoped. Both `upload-complete` and finalize resolve that effective grant; upload-complete verifies object-store key/size/type/digest server-side. A dedicated, signed ImportFinalizationJob is the sole worker allowed an ImportSession ID; it rechecks all pinned values and compare-and-sets the source pointer before atomically creating a terminal ImportManifest and visible imported content. Every downstream worker rejects ImportSession IDs/non-terminal objects and accepts only manifest/version references. Digest mismatch, expiry/revoke, stale pointer, cancellation or validation failure produces no manifest/visible content; staged bytes are quarantined and deleted under the short staging-retention policy.

## Data egress and model policy

Before an LLM/tool call, the policy engine evaluates workspace, source label, provider region/contract, task purpose, user approval, content minimization and tool scope. Default policy:

- Local-only content cannot leave the Mac; cloud research and remote model calls are blocked.
- Restricted content requires an approved provider and explicit workspace policy; it may be redacted or require human confirmation.
- Cloud/Imported content is sent only as selected evidence excerpts and metadata needed for the typed task, not full workspace history.
- Seed data is never mixed with production reporting.

The UI presents a scope/egress preview before a local upload or a research plan that would use a model provider. Export requires an explicit destination, one readiness-reviewed and currently non-stale frozen DecisionBriefVersion, an allowlisted selection manifest and a preview reference digest; Synthesis/model text is excluded from PRD Research Input, and the terminal BriefExport stores selection/reference/render digests. The system does not automatically publish a Brief, send email/Slack, or invoke a webhook in the first slice.

## Agent and worker security

The LangGraph process has a bounded graph version, per-node time/cost budget, concurrency cap and a fixed tool allowlist. Shell execution is absent from the cloud graph. A future local sidecar uses an explicit command allowlist, no user-supplied shell strings, restricted working directory, timeouts and captured redacted output. Tools cannot directly access arbitrary files, network destinations, databases or credentials.

Workers use signed/validated queue payloads, persistent idempotency keys, database leases and workspace-scoped service identity. They call domain services rather than writing approval-bearing tables directly. ToolExecution and RunEvent traces record digests and safety decisions without recording secret/raw sensitive payloads.

## Audit, detection, and response

Audit logs are append-only, access controlled, clocked in UTC and include request/trace correlation. Log events cover authentication changes, access-denied decisions, source and policy changes, Local→Cloud transfer consent, approvals/rejections, exports, prompt/detector updates, manual score overrides, retention deletes, suspicious tool attempts and administrative actions.

Security telemetry alerts on repeated authorization failures, cross-workspace access attempts, unusual export volume, SSRF rejections, secret-redaction hits, injection flags, source credential failures and worker policy violations. Incident procedure: revoke affected credentials/session, disable the source/export policy, preserve minimal forensic audit evidence, scope affected versions/exports, notify the workspace owner as required, rotate secrets, remediate, and record a post-incident decision.

## Minimum security verification

Before a real data pilot, automated tests must verify:

- RLS/API/domain authorization blocks cross-workspace reads and writes;
- stale approval/version and idempotency replay behavior;
- no credential value appears in API, event, trace or log fixtures;
- Local Source cannot silently upload or invoke cloud models; import tests prove exact consent scope/expiry/revocation, server-observed digest, no-path serialization and terminal-manifest-only worker input;
- SSRF blocking survives redirects, IPv4/IPv6 and DNS rebinding cases;
- file parser rejects unsafe/oversized inputs;
- injection fixtures cannot alter tool policy or create approved records;
- Evidence quote ranges/hashes point to the exact immutable ContentVersion;
- role checks protect source configuration, verification, export and audit access.
