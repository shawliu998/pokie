# Phase 3 Scope Audit

> Historical Glint scope audit only. It records inherited repository provenance and does not define
> the current Qurio quantitative-research product or navigation.

Audit date: 2026-07-16  
Repository: `https://github.com/shawliu998/Glint`  
Audited branch: `codex/phase3-model-research`  
Audited commit: `6b9913493e5e442ef3d7cf33e8e8d2c94e955895`  
Comparison base: `origin/main` at `161c6075a9e73dbb344f15d58ef41b7c9834380e`

This document is an audit of the committed branch above. The working tree was clean when the audit
started. Phase 3.1 feature work must remain frozen until PR 0 is reviewed. The split procedure is in
[PHASE3_PR_SPLIT_PLAN.md](./PHASE3_PR_SPLIT_PLAN.md).

## Executive finding

The branch is not a reviewable Phase 3-only change. Relative to `origin/main`, it contains 20
commits, 121 changed files, 8,024 insertions, and 871 deletions. Its history combines three distinct
delivery units:

| Delivery unit | Commit boundary | Commits | Primary scope |
|---|---|---:|---|
| P2.5 Mac Workbench | `8563f7b..df01d50`, excluding `30a423d` | 18 | Mac/Tauri workbench, portfolio/demo, deterministic owner flow, P2.5 evidence |
| Live Connector Validation | `30a423d` | 1 | Opt-in GitHub/RSS network smoke and its controls |
| Phase 3 model proposals | `6b99134` | 1 | DeepSeek/LangGraph proposal runtime, model UI seam, synthetic replay evaluation |

The Phase 3 commit itself changes 42 files (3,011 insertions and 142 deletions). It is based on the
P2.5 branch tip, so opening the current branch directly against `main` would present all three units
as one PR.

## 1. Commit and file scope relative to main

The following commands were run after fetching `origin/main`, the current branch, and the P2.5
branch:

```bash
git fetch origin main codex/phase3-model-research feat/p2-5-pilot-workbench --prune
git rev-parse HEAD origin/main origin/codex/phase3-model-research
git log --oneline --no-merges origin/main..HEAD
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
```

Observed ancestry:

```text
origin/main 161c607
  -> 19 P2.5-lineage commits ending at df01d50
  -> 6b99134 feat(phase3): add bounded DeepSeek research
```

The 19 commits before `6b99134` are, in order:

```text
8563f7b  chore: verify repository and CI baseline
971df70  test: diagnose investigation startup failures
82a206a  ci: make cargo audit cache idempotent
af9414f  docs: record trusted remote CI baseline
d131186  refactor(mac): split workbench feature modules
c214d0c  fix(mac): reuse pinned investigation scope
5400c51  fix(mac): preserve brief placeholder guards
a14f993  feat(mac): add native application shell
30a423d  feat(connectors): add opt-in live GitHub and RSS smoke
e08e4ae  feat(demo): add export lineage metadata
ceadbec  feat(mac): add responsive resizable workbench layout
ab9b4a3  feat(mac): bind exports to server preview metadata
f35f747  docs: add portfolio README and pilot documentation
7281038  feat(demo): add pilot vertical-flow profile
ad4568e  feat(mac): add command palette and keyboard workflow
094bea1  feat(pilot): finalize workbench evidence and portfolio
4dba289  fix(ci): publish reviewed portfolio assets
be6998d  test(e2e): select the unreviewed imported signal
df01d50  docs: record final candidate acceptance evidence
```

File-scope summary:

| Area | Representative paths | Audit classification |
|---|---|---|
| Native application and workbench | `apps/mac/**`, including `src-tauri/**`, command palette, layout, session and portfolio E2E | P2.5, except the model-mode additions in `6b99134` |
| Deterministic demo and owner flow | `fixtures/demo/**`, `scripts/seed_runtime.py`, `scripts/verify_demo_flow.py`, deterministic decision/export changes | P2.5 |
| Portfolio and P2.5 evidence | `docs/P2_5_*`, `docs/DEMO_*`, `docs/PILOT_PLAN.md`, `docs/assets/**` | P2.5 |
| Live network validation | the eight files listed in the next section | Live Connector |
| Model runtime and quality | `services/worker/app/pipelines/model_research.py`, model/API contracts, DeepSeek configuration, Phase 3 scripts/tests/docs | Phase 3 |
| Shared files | `.env.example`, `README.md`, `docs/README.md`, lockfiles, contracts, selected Mac/API files | Must be resolved per-PR; file ownership cannot be inferred only from path |

## 2. P2.5 content

P2.5 comprises the 18 pre-Phase-3 commits other than `30a423d`. Its principal changes are:

- Mac workbench decomposition and the native Tauri shell;
- responsive/resizable layout, command palette, keyboard behavior, session and workspace seams;
- deterministic imported-data owner flow and export lineage;
- portfolio/demo fixtures, scripts, screenshots and E2E coverage;
- P2.5 audit, acceptance and pilot documentation;
- CI hardening needed for Tauri and dependency auditing.

Some P2.5 commits touch backend contracts and services because the workbench binds to deterministic
server metadata. Those files remain P2.5 when the change is not model-specific. In particular,
`e08e4ae` is deterministic export lineage, not Phase 3 model research.

## 3. Live Connector content

Live Connector Validation is isolated cleanly in `30a423d` and changes exactly eight files:

```text
.env.example
connectors/rss/connector.py
docs/LIVE_CONNECTOR_SMOKE.md
scripts/live_connector_smoke.py
scripts/verify_live_connectors.sh
scripts/verify_phase2.sh
tests/connector/test_github_rss_runtime.py
tests/smoke/test_live_connector_controls.py
```

This slice implements an explicit opt-in, read-only smoke path. It is not proof of a completed live
owner workflow. The committed P2.5 acceptance record still marks final GitHub and RSS live
acceptance evidence as Pending.

## 4. Phase 3 content

Commit `6b99134` changes the following 42 files:

```text
.env.example
README.md
THIRD_PARTY_NOTICES.md
(legacy Glint API-contract browser spec; retired during PokieQuant C4)
apps/mac/e2e/api-fixture.mjs
apps/mac/src/api.test.ts
apps/mac/src/api.ts
apps/mac/src/domain.ts
apps/mac/src/features/decisions/DecisionBriefDetail.tsx
apps/mac/src/features/investigations/InvestigationDetail.tsx
apps/mac/src/features/investigations/InvestigationPlanDialog.tsx
apps/mac/src/features/investigations/research-presentation.test.ts
apps/mac/src/features/investigations/research-presentation.ts
apps/mac/src/features/workbench/Workbench.tsx
apps/mac/src/mappers.test.ts
apps/mac/src/mappers.ts
apps/mac/src/styles.css
docs/MODEL_RESEARCH.md
docs/PHASE3_QUALITY_ACCEPTANCE.md
docs/README.md
infra/docker-compose.yml
packages/contracts/openapi/openapi.snapshot.json
packages/contracts/schemas/research.py
pyproject.toml
scripts/evaluate_phase3_model_quality.py
scripts/verify_live_model.py
scripts/verify_live_model.sh
scripts/verify_phase3_quality.sh
services/api/app/api/presenters.py
services/api/app/core/config.py
services/api/app/modules/research/service.py
services/worker/app/contracts.py
services/worker/app/main.py
services/worker/app/pipelines/model_research.py
services/worker/app/pipelines/research.py
services/worker/app/repositories/sqlalchemy_adapter.py
tests/eval/fixtures/phase3_model_quality_v1.json
tests/eval/test_model_research.py
tests/eval/test_phase3_model_quality.py
tests/integration/test_collected_research_lineage.py
tests/license/dependency_policy.json
uv.lock
```

The Mac files in this commit are model-mode presentation and consent seams built on P2.5; they are
not justification for carrying the unrelated P2.5 refactor into a Phase 3 PR. Phase 3 must instead
be reviewed on top of the separately merged P2.5 PR.

## 5. Current graph nodes versus real behavior

The fixed graph is linear:

```text
planner -> parallel_retrieval -> evidence_analyst -> claim_builder
        -> evidence_reviewer -> synthesis_writer
```

The names overstate the committed behavior:

| Current node | Actual committed behavior | Model call? | Honest PR 0 action |
|---|---|---:|---|
| `planner` | Validates non-empty question/content, maximum 20 versions, and exact immutable ContentVersion ordering | No | `validate_manifest` |
| `parallel_retrieval` | Copies each ContentVersion with only its first 6,000 characters, capped at 60,000 total; no query, ranking, lexical/vector retrieval, parallelism, diversity or frozen chunk manifest | No | `bound_content` |
| `evidence_analyst` | Builds one DeepSeek Chat Completions request and validates one JSON response containing both evidence selections and a claim | **Yes: one** | `propose_evidence`; document that the one response still carries a Claim |
| `claim_builder` | Deterministically validates exact/unique quote substrings, derives offsets/digests, copies model scores, constructs Evidence proposals and exactly one ClaimVersion | No | Split host work into `validate_evidence` then `propose_claim` |
| `evidence_reviewer` | Checks evidence count and requires at least one supporting span; sets a boolean human-review-required flag | No human review occurs | `require_human_review` |
| `synthesis_writer` | Verifies the boolean and returns an empty update; it does not generate or persist synthesis | No | Remove the no-op node; end after `require_human_review` |

PR 0 should use behavior-honest names. Implementing the aspirational planner, hybrid retrieval,
separate evidence/claim calls, counter-evidence loop, and synthesis is deliberately deferred to PRs
1-5. Renaming alone must not be described as new Agent capability.

## 6. Current model-call count and I/O

There is exactly one provider call per successfully attempted graph execution:

```text
DeepSeekResearchRunner.run
  -> evidence_analyst
     -> transport.complete(request)  # one call
```

There is no model call in planning, retrieval, claim building, review, or synthesis. There is no
retry loop or counter-evidence loop.

Model input contains:

- a system instruction that marks source bodies as untrusted and denies tools/policy changes;
- the immutable run question;
- up to 20 ContentVersions in manifest order;
- each title, content digest, ID and a body prefix of at most 6,000 characters;
- at most 60,000 source characters in total;
- a JSON output contract;
- `tool_choice=none`, streaming disabled, temperature 0, thinking disabled, and a 2,500-token output
  cap.

The HTTP request has a 45-second timeout and the response envelope/content is capped at 100,000
bytes. The API key is added only as an Authorization header by the transport.

The single model output contains 1-20 evidence selections and exactly one claim. Each evidence
selection currently includes `content_version_id`, `quote_text`, stance, relevance, reliability,
independence, recency and specificity. The claim includes text, confidence level and limitations.
The host then derives quote offsets/digest and persists proposals through the domain adapter only
after validation. Human Evidence and Claim review remain authoritative.

This contract violates the Phase 3.1 boundary in two ways beyond the naming issue: evidence and
claim are produced in one call, and the model supplies reliability/independence/recency values that
the deterministic domain layer should own.

## 7. Prompt-contract contradiction

The committed system prompt contains these adjacent instructions:

```text
Return exact character offsets into the provided content.
Copy quote_text verbatim from one source; do not calculate or return character offsets.
```

The JSON schema does not expose offset fields, so the first sentence is both contradictory and
unfulfillable. PR 0 must reduce this to one contract:

```text
The model must copy quote_text verbatim from a supplied chunk.
The model must not calculate or return character offsets.
The host derives and verifies offsets deterministically.
```

No committed test currently asserts that the rendered prompt is free of contradictory offset
instructions. Add a contract test in PR 0.

## 8. Evaluation-set scale and gaps

The current fixture is a repository-authored synthetic replay with four cases:

| Stratum | Cases | Evidence | Claims / hostile cases |
|---|---:|---:|---:|
| Citation, counter-evidence and numbers | 1 | 3 | 1 claim |
| Counter-evidence | 1 | 2 | 1 claim |
| Prompt injection | 2 | 0 persisted | 2 hostile cases |
| **Total** | **4** | **5** | **2 claims + 2 hostile cases** |

The recorded denominators are five citations, two claims, two counter-evidence items, four numeric
facts, and two injection cases. This is a deterministic mechanism test, not a held-out quality set.

Relative to Glint Product Intelligence Eval v1, the missing evidence includes:

- 46 additional cases to reach the Stage 1 minimum of 50;
- three runs per case with all runs retained;
- GitHub Issues/Discussions, RSS releases, interview CSV, bilingual, deletion/update, clarification,
  insufficient-evidence, duplicate/repost and single-large-account strata;
- Retrieval Recall@K/Precision@K, diversity, duplicate inflation and rank diagnostics;
- stance accuracy, quote exactness, claim redundancy and limitation coverage;
- deterministic keyword, current single-call and future hybrid/multi-stage baselines;
- token, provider cost, latency, human acceptance and time-to-reviewed-synthesis measures;
- live held-out DeepSeek execution and external PM labels.

The 4/4 replay pass may therefore be described only as Provisionally Passed.

## 9. Current CI gate

GitHub Actions run `29486021212` for `6b99134` completed successfully with four jobs: `phase1`,
`phase2`, `security-audit`, and `macos-native`. There is no independent `phase3-quality` job in
`.github/workflows/verify.yml`.

`phase1` runs the whole `tests/eval` directory, so Phase 3 pytest files are exercised indirectly.
However, CI does not directly invoke `./scripts/verify_phase3_quality.sh`, does not expose a
separately required Phase 3 status, and does not upload the four required Phase 3 artifacts:

```text
tests/artifacts/phase3-quality-report.json
tests/artifacts/phase3-failure-reasons.json
tests/artifacts/phase3-prompt-manifest.json
tests/artifacts/phase3-eval-manifest.json
```

The current evaluator prints a bounded report to stdout; it does not write those four artifacts.
The live-model smoke is correctly opt-in and not a required CI path.

## 10. Acceptance-state alignment required in PR 0

The following is the single vocabulary and current evidence-backed status to apply across README
and acceptance documents:

| Verification layer | Status | Meaning |
|---|---|---|
| Deterministic replay gate | Provisionally Passed | Four synthetic fixture cases validate the mechanism only |
| Live provider adapter smoke | Passed | Repository record says the final bounded synthetic smoke completed 3/3 on 2026-07-16 |
| Live held-out quality evaluation | Pending | No 50-case, three-run, retained live evaluation |
| Live Mac owner workflow | Pending | No full live source-to-reviewed-synthesis-to-export owner evidence |
| External PM pilot | Pending | No 3-5 target-PM study results |
| Phase 3 acceptance | Pending | Acceptance checklist is incomplete |

`README.md` currently says the live provider run is pending while
`docs/PHASE3_QUALITY_ACCEPTANCE.md` records the bounded adapter smoke as passed. These refer to
different layers but are phrased as if they conflict. `docs/P2_5_ACCEPTANCE.md` also uses
“Conditionally Accepted”, outside the required five-state vocabulary, and still states that live
connector acceptance and pilot evidence are missing.

## 11. Retain, modify, and remove

### Retain

- Provider/model/prompt pinning in the immutable ResearchRun manifest.
- Explicit workspace/run cloud-model consent and runtime feature gate.
- One-provider DeepSeek adapter, HTTPS-origin validation, no tools, response/schema limits and
  fail-closed redaction.
- Exact unique quote matching with host-derived offsets and digests.
- Domain-service persistence and human Evidence/Claim authority.
- Deterministic fixture digest, mutation tests and hostile-content failure tests.
- Opt-in live smoke that neither requires secrets in CI nor stores provider/source bodies.

### Modify

- Rename every graph node to its PR 0 behavior-honest name.
- Remove the offset contradiction and add a rendered-prompt contract test.
- Replace prefix truncation with deterministic frozen hybrid retrieval in PR 1.
- Split evidence and claim model stages, and move reliability/independence/recency fully into
  deterministic enrichment in PR 2.
- Support 1-5 non-redundant typed claims in PR 3.
- Replace the boolean-only review node and no-op synthesis node with real human gates and reviewed
  synthesis in PRs 4-5.
- Expand evaluation to 50+ held-out cases and all required baselines/operational metrics in PR 6.

### Remove from the current contract

- The contradictory “Return exact character offsets” prompt sentence.
- Misleading node labels that imply planning, parallel retrieval, evidence review or synthesis.
- Model-authored reliability, independence and recency values when deterministic enrichment lands.
- Documentation language describing prefix-bounded ContentVersions as retrieval or the no-op node as
  a synthesis writer.

Do not remove the fail-closed provider adapter, human-review requirement, audit lineage or existing
deterministic path. Do not add providers, executable tools or multiple conversational Agents.

## 12. Exact PR 0 file list

PR 0 adds no model capability. Its exact intended file set is:

| File | Required PR 0 change |
|---|---|
| `docs/PHASE3_SCOPE_AUDIT.md` | Add this committed-state audit |
| `docs/PHASE3_PR_SPLIT_PLAN.md` | Add non-rewriting A/B/C extraction plan |
| `README.md` | Align the six verification-layer statuses |
| `docs/MODEL_RESEARCH.md` | Correct graph behavior and status language |
| `docs/PHASE3_QUALITY_ACCEPTANCE.md` | Use the five-state vocabulary and separate smoke from held-out quality |
| `docs/P2_5_ACCEPTANCE.md` | Replace “Conditionally Accepted” with evidence-backed layer statuses |
| `services/worker/app/pipelines/model_research.py` | Fix prompt contradiction and rename nodes/functions only; do not add planning/retrieval/model calls |
| `tests/eval/test_model_research.py` | Assert honest node sequence and a conflict-free rendered prompt |
| `scripts/evaluate_phase3_model_quality.py` | Emit bounded report, reason, prompt-manifest and eval-manifest artifacts without source/prompt/secret bodies |
| `tests/eval/test_phase3_model_quality.py` | Test artifact schema, stable content, failure behavior and redaction |
| `scripts/verify_phase3_quality.sh` | Generate all four required artifacts in `tests/artifacts/` |
| `.github/workflows/verify.yml` | Add independent `phase3-quality`, invoke the script, upload four artifacts with `if: always()`, and provide no provider secret |

Generated JSON under `tests/artifacts/` remains ignored runtime output and is not committed. No
OpenAPI, database, Mac UI, connector, lockfile or provider dependency change belongs in PR 0.

## Audit decision

**Phase 3 acceptance: Pending.** The existing slice is useful bounded proposal infrastructure, but
its graph names, prompt contract, evaluation scale and CI boundary do not yet satisfy Phase 3.1 PR
0. Frozen Hybrid Retrieval must not begin until PR 0 is reviewed and its independent CI job passes.
