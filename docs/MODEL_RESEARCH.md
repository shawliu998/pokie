# Phase 3 Model Research Runtime

Phase 3 model research is opt-in and fail-closed. A run uses DeepSeek only when both conditions
are true:

1. the API runtime sets `GLINT_MODEL_RUNTIME_ENABLED=true`; and
2. the current immutable Investigation scope and matching ResearchRun request set
   `source_scope.allow_cloud_model=true`.

The client cannot choose a provider or model. The API freezes `deepseek`, the configured model,
prompt references, budget, no-tools policy, trace reference and exact ContentVersion lineage in
the RunInputManifest. The default model is `deepseek-v4-flash`; the default OpenAI-compatible base
URL is `https://api.deepseek.com`.

## Acceptance status

The validation layers are separate; a passed adapter smoke is not a passed live-quality or owner
workflow evaluation. The only acceptance statuses are `Passed`, `Provisionally Passed`, `Pending`,
`Failed`, and `Not Applicable`.

| Verification layer | Status | Meaning |
| --- | --- | --- |
| Deterministic reviewed replay gate | **Provisionally Passed** | Four repository-reviewed synthetic cases pass the mechanism gate. |
| Live provider adapter smoke | **Passed** | Three consecutive opt-in calls completed the bounded synthetic adapter path. |
| Live held-out quality evaluation | **Pending** | No approved 50-case held-out provider run is recorded. |
| Live Mac owner workflow | **Pending** | No complete model-assisted review-to-export owner run is recorded. |
| External PM pilot | **Pending** | No external participant result is recorded. |
| Phase 3 acceptance | **Pending** | The preceding pending layers and later Phase 3.1 increments remain open. |

## Configuration

The API needs only non-secret policy configuration:

```dotenv
GLINT_MODEL_RUNTIME_ENABLED=true
GLINT_DEEPSEEK_MODEL=deepseek-v4-flash
```

The worker receives provider configuration through its environment or secret manager:

```dotenv
DEEPSEEK_API_KEY=<secret-manager-value>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Do not commit the key. CI and the default Compose profile leave model mode disabled and use mocked
transport tests, so deterministic acceptance does not require provider credentials or network
access. Missing or invalid worker configuration terminalizes a claimed model run as failed with a
redacted event.

The independent `phase3-quality` CI job runs `./scripts/verify_phase3_quality.sh` with an empty
provider credential and model runtime disabled. It uploads only:

```text
tests/artifacts/phase3-quality-report.json
tests/artifacts/phase3-failure-reasons.json
tests/artifacts/phase3-prompt-manifest.json
tests/artifacts/phase3-eval-manifest.json
```

These artifacts contain digests, identifiers, counts, thresholds and status metadata. They exclude
prompt text, source bodies, provider responses and credentials.

## Opt-in live smoke

The live smoke sends only the repository-owned synthetic paragraph embedded in the verifier. It
prints counts and a terminal status, never the key, provider response, prompt, Claim text or source
body. Load the ignored local environment explicitly, then opt in:

```bash
set -a
source .env.local
set +a
GLINT_ENABLE_LIVE_MODEL_SMOKE=1 ./scripts/verify_live_model.sh
```

Without `GLINT_ENABLE_LIVE_MODEL_SMOKE=1`, the script exits successfully with an explicit policy
skip and makes no provider call.

## Safety and current boundary

The fixed LangGraph exposes six behavior-bounded nodes:
`validate_manifest -> bound_content -> propose_evidence -> validate_evidence -> propose_claim ->
require_human_review`. It exposes no executable tools. `bound_content` only applies the existing
per-version and total character caps; it is not retrieval, ranking, chunking, or a frozen chunk
manifest. The graph does not yet plan research or generate synthesis.

The one current provider call still returns Evidence selections and one Claim in the same JSON
response. The host then validates exact unique quote text, derives character ranges and digests,
materializes the proposals, and requires human review. The node split describes host execution
boundaries; it does not claim the later multi-stage model architecture is implemented.

Evidence/Claim model-call separation, Frozen Hybrid Retrieval, and model-assisted synthesis from
reviewed ClaimVersions are remaining Phase 3 increments. This implementation alone does not
satisfy full Phase 3 acceptance or live-provider quality acceptance. The separate synthetic replay
gate is recorded in
[PHASE3_QUALITY_ACCEPTANCE.md](./PHASE3_QUALITY_ACCEPTANCE.md).
