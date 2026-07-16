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

The fixed LangGraph has planner, frozen-input retrieval, evidence analysis, ClaimVersion building,
evidence validation and synthesis-gate nodes. It exposes no executable tools. Source text is marked
as untrusted data, response JSON is schema validated, and every verbatim quote must occur exactly
once in the model-visible frozen ContentVersion. A deterministic node derives its character range
and digest before the existing domain service revalidates and persists it.
Evidence and model ClaimVersion proposals still require human review.

The synthesis-gate node intentionally does not persist model synthesis before EvidenceReview and
ClaimReview. Model-assisted synthesis from reviewed ClaimVersions is a remaining Phase 3 increment;
this implementation alone does not satisfy full Phase 3 acceptance or live-provider quality
acceptance. The separate synthetic replay gate is recorded in
[PHASE3_QUALITY_ACCEPTANCE.md](./PHASE3_QUALITY_ACCEPTANCE.md).
