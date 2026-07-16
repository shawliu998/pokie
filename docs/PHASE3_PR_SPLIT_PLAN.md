# Phase 3 PR Split Plan

Plan date: 2026-07-16  
Source branch: `codex/phase3-model-research` at `6b99134`  
Base: `origin/main` at `161c607`

## Objective and constraints

Split the published source branch into three reviewable delivery units without rewriting public
history:

```text
PR A — P2.5 Mac Workbench
PR B — Live Connector Validation
PR C — Phase 3 Bounded Model Proposals
```

The existing branches and commits remain untouched. Do not rebase, reset, amend, or force-push
`codex/phase3-model-research` or `feat/p2-5-pilot-workbench`. New branches are created from
`origin/main`; selected existing commits are cherry-picked in their original order. Conflict
resolutions, if necessary, become new commits on the extracted branch and are documented in the PR.

Before extraction, complete and review the exact PR 0 cleanup listed in `PHASE3_SCOPE_AUDIT.md` on
the source branch. That work records the plan, fixes the prompt/names/CI/status boundary, and adds no
model capability. No Phase 3.1 feature work (Frozen Hybrid Retrieval or later) begins during PR 0
or extraction.

## Dependency and merge order

```text
codex/phase3-model-research
  -> Phase 3.1 PR 0 cleanup commit and review (no new capability)
  -> extraction source

origin/main
  |-- PR A: P2.5 Mac Workbench -----------+
  |-- PR B: Live Connector Validation ----+--> updated main
                                           |
                                           +--> PR C: Phase 3 Bounded Model Proposals
                                                  + PR 0 Phase 3 cleanup
                                                  |
                                                  +--> Phase 3.1 PR 1 Frozen Hybrid Retrieval
```

PR B is logically and technically independent of PR A. PR C is based on updated `main` after PR A,
because its small model-mode UI seam intentionally extends the P2.5 workbench. It does not require
PR B for model execution, but creating it after both A and B merge minimizes shared-file conflicts
in `.env.example`, README and acceptance documentation.

Each extracted PR is independently testable and independently revertible at its merge boundary.
“Independent” does not mean PR C must duplicate the workbench it extends.

## Safety preparation

Before extraction:

```bash
git fetch origin --prune
git status --short --branch
git rev-parse origin/main origin/feat/p2-5-pilot-workbench \
  origin/codex/phase3-model-research
```

Record the expected source refs:

```text
origin/main                              161c6075a9e73dbb344f15d58ef41b7c9834380e
origin/feat/p2-5-pilot-workbench         df01d502c88215d30a8bf786e624b5a3ab0038e0
origin/codex/phase3-model-research       6b9913493e5e442ef3d7cf33e8e8d2c94e955895
```

`6b99134` is the audited pre-PR-0 Phase 3 source. After PR 0 is committed and reviewed, record that
new commit as `PR0_REF`; it is expected to advance the source branch. If `origin/main`, the P2.5
source, or the pre-PR-0 ancestry differs, repeat the scope audit before cherry-picking. Never use
the user's local `.env.local` during extraction or CI.

## PR A — P2.5 Mac Workbench

### Scope

Mac/Tauri workbench refactor, responsive layout, command/keyboard flow, deterministic imported-data
owner path, export lineage, demo/portfolio evidence and P2.5 acceptance documentation.

### Non-goals

- No live GitHub/RSS network smoke.
- No LangGraph, DeepSeek, model-mode consent, model proposal UI or model evaluation.
- No Phase 3.1 retrieval, counter-evidence, multi-claim or synthesis work.

### Construction

Create a new branch from the audited main ref:

```bash
git switch --create codex/p2-5-mac-workbench origin/main
```

Cherry-pick these 18 commits in order, deliberately excluding `30a423d`:

```text
8563f7b 971df70 82a206a af9414f d131186 c214d0c 5400c51 a14f993
e08e4ae ceadbec ab9b4a3 f35f747 7281038 ad4568e 094bea1 4dba289
be6998d df01d50
```

Because some later documentation was authored after the live-smoke commit existed in the source
lineage, audit the resulting tree for live-smoke references:

```bash
rg -n "verify_live_connectors|LIVE_CONNECTOR_SMOKE|GLINT_ENABLE_LIVE_SMOKE" \
  README.md docs scripts .env.example
```

Remove only dangling PR B references in an explicit cleanup commit; do not silently fold changes
into a cherry-pick.

### Required tests

```bash
./scripts/verify_phase2.sh
./scripts/verify_tauri_runtime.sh
pnpm --filter @glint/mac lint
pnpm --filter @glint/mac typecheck
pnpm --filter @glint/mac test
GLINT_E2E_API_MODE=fixture GLINT_E2E_FIXTURE_MODE=1 pnpm test:e2e
```

Required remote jobs: `phase1`, `phase2`, `security-audit`, and `macos-native`. Review the uploaded
Mac bundle and portfolio asset checks separately from live-network claims.

### Rollback

Revert PR A's merge commit (or the squash commit, according to repository merge policy). The slice
has no new model runtime and no new database migration. Revert frontend/backend deterministic
contract changes together; do not retain a workbench client expecting reverted API metadata. Run
Phase 1 after the revert to prove the pre-P2.5 deterministic path remains intact.

## PR B — Live Connector Validation

### Scope

Opt-in, read-only GitHub/RSS smoke validation, RSS runtime hardening, bounded/redacted result
reporting, and deterministic tests for the live-smoke controls.

### Exact source commit and files

Cherry-pick only `30a423d` onto a new branch from updated `origin/main`:

```bash
git switch --create codex/live-connector-validation origin/main
git cherry-pick 30a423d
```

Expected file set:

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

Reject the cherry-pick if unrelated Mac, portfolio, model or lockfile changes appear.

### Non-goals

- No credential provisioning or committed live secret.
- No required network call in PR CI.
- No claim that fixtures or a successful adapter call prove a live owner workflow.
- No model research changes.

### Required tests

```bash
uv run pytest tests/connector/test_github_rss_runtime.py \
  tests/smoke/test_live_connector_controls.py
./scripts/verify_phase2.sh
```

The default/CI path must make zero live calls. A maintainer may separately run the documented
manual smoke with `GLINT_ENABLE_LIVE_SMOKE=1`; its result is acceptance evidence only when source,
time, freshness, terminal status and redaction are recorded. A manual live smoke is not a required
PR check.

### Rollback

Disable the opt-in flag first, then revert PR B's merge/squash commit. No schema or persistent data
migration is introduced. Re-run connector contract and SSRF tests after the revert. Existing
deterministic connector fixtures remain the fallback validation path.

## PR C — Phase 3 Bounded Model Proposals

### Prerequisite

Base this PR on updated `main` after PR A. Prefer waiting for PR B as well to avoid shared-file
conflicts, although the model runtime has no functional dependency on live connector smoke.

### Scope

The current bounded DeepSeek adapter and fixed graph, immutable model-run metadata, Evidence and
single-Claim proposals, explicit cloud-model consent, model-specific workbench presentation,
synthetic replay evaluator, mocked provider tests, and opt-in live-model smoke.

### Construction

```bash
git switch --create codex/phase3-bounded-proposals origin/main
git cherry-pick 6b99134
git cherry-pick "$PR0_REF"
```

The source commit's parent is the P2.5 tip, so conflicts are expected when applying it to the merged
tree. Resolve them by preserving only the 42-file model-specific delta documented in
`PHASE3_SCOPE_AUDIT.md`. Do not copy the whole source tree and do not reintroduce unrelated P2.5
history. Put conflict resolution in a separate commit and review it with:

```bash
git diff --stat origin/main...HEAD
git range-diff df01d50..6b99134 origin/main...HEAD
```

Keep PR 0's scope audit, prompt fix, honest graph naming, independent CI job and status alignment as
a distinct commit when it is carried into the extracted Phase 3 branch. If cherry-picking the whole
PR 0 commit conflicts with status documents already resolved in A/B, resolve only those shared
documents and preserve the exact PR 0 code/CI behavior. Do not include unrelated concurrent edits.

### Non-goals

- No unrelated workbench refactor, portfolio screenshots or demo-fixture expansion.
- No live connector implementation.
- No hybrid retrieval, autonomous planner, counter-evidence loop, multi-claim generation, reviewed
  synthesis or external pilot claim.
- No additional provider, executable tool or conversational multi-Agent design.

### Required tests

```bash
./scripts/verify_phase3_quality.sh
uv run pytest tests/integration/test_collected_research_lineage.py \
  tests/eval/test_model_research.py tests/eval/test_phase3_model_quality.py
pnpm --filter @glint/mac lint
pnpm --filter @glint/mac typecheck
pnpm --filter @glint/mac test
./scripts/verify_phase2.sh
```

At PR C tip, `phase3-quality` must be a distinct required CI job and upload the four bounded JSON
artifacts. It must not receive a provider secret. The live model smoke remains manual, explicit
opt-in, non-blocking, and body-free.

### Rollback

First set `GLINT_MODEL_RUNTIME_ENABLED=false` so new model runs fail closed. Then revert PR C's
merge/squash commit, including the LangGraph dependency/lockfile and the model-mode Mac/API seam.
Deterministic research remains the fallback. Existing model-generated proposals already written to
the ledger must retain their provenance and audit history; rollback must not delete or rewrite
those records. Verify the deterministic Phase 2 owner loop after the revert.

## Shared-file conflict policy

The following files are expected conflict points and must be resolved semantically, not with
“ours/theirs” wholesale selection:

| File group | Ownership rule |
|---|---|
| `.env.example` | A owns deterministic/runtime examples, B owns live-connector opt-in, C owns model-runtime/provider names; no secret values |
| `README.md`, `docs/README.md` | Each PR documents only its layer; status vocabulary must distinguish fixture, adapter smoke, held-out, owner path and pilot |
| `.github/workflows/verify.yml` | A owns existing platform/native gates; PR 0 owns the independent secret-free `phase3-quality` job |
| `scripts/verify_phase2.sh` | B owns live-connector opt-in wiring; Phase 3 quality does not hide inside this script |
| Mac investigation files | A owns workbench structure; C owns only model mode, consent, provenance and review presentation |
| research contracts/services | A owns deterministic export/owner-path changes; C owns additive provider/model/prompt/trace metadata and model dispatch |
| dependency notices and locks | Include only dependencies used by the PR; C owns LangGraph additions |

Any conflict resolution that changes runtime behavior requires a targeted regression test in the
same extracted PR.

## Verification of scope before opening each PR

For every extracted branch:

```bash
git status --short --branch
git log --oneline --no-merges origin/main..HEAD
git diff --check origin/main...HEAD
git diff --name-status origin/main...HEAD
git grep -n -E '(DEEPSEEK_API_KEY=.{8,}|Authorization: Bearer|sk-[A-Za-z0-9])' -- . \
  ':(exclude)pnpm-lock.yaml' ':(exclude)uv.lock'
```

The credential scan is a guard, not permission to print `.env.local`; that ignored file must never
be staged or read into an artifact.

Open each PR with the reporting sections required by Phase 3.1: Scope, Non-goals, Architecture,
Files Changed, Tests, Evaluation, UI Evidence, Risks, and Next PR. Report actual commands and
remaining Pending items.

## Roll-forward after extraction

Once PR 0 is reviewed, carried into PR C, and A, B and C are merged and independently green:

1. Confirm PR C's four Phase 3 artifacts exist and contain no prompt/source/secret bodies.
2. Confirm the merged graph still has PR 0's honest names and conflict-free prompt.
3. Confirm Phase 3 acceptance remains Pending.
4. Start PR 1 Frozen Hybrid Retrieval from the updated `main`.

Do not combine PRs 1-6 back into a single branch or PR. The original public source branch remains a
historical integration reference, not the merge vehicle.
