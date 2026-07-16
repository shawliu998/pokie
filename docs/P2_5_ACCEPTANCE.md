# Glint P2.5 acceptance

Evidence snapshot: 2026-07-16 (Asia/Shanghai)

## Decision

**P2.5 Status: Conditionally Accepted**

The repository trust baseline, deterministic P1/P2 path, and a local unsigned
Mac bundle have evidence. Final P2.5 acceptance is withheld because the exact
candidate commit has not completed remote CI, live GitHub/RSS verification and
the required real-app portfolio captures have not been recorded, and no external
pilot has run.

Recommendation: **do not enter Phase 3 yet**. Close the candidate CI, live-data,
vertical-flow, and portfolio evidence below first. This document must be updated
from the final published commit; no `Pending` item may be inferred as passing.

## Candidate identity and repository

| Item | Evidence | Status |
| --- | --- | --- |
| Final commit SHA | Pending; the workspace continued changing after the latest pushed connector commit | **Pending** |
| Branch | `feat/p2-5-pilot-workbench` | Recorded |
| Public repository/default branch | Public repository; default branch `main` | Verified in [repository audit](./P2_5_REPOSITORY_AUDIT.md) |
| Branch protection | Strict required `phase1`, `phase2`, `security-audit`, and `macos-native`; admin enforcement enabled | Verified in repository audit |
| Trusted remote baseline | Commit `82a206aceb6ad213582a33323708e0ee500b3dcd`; [Actions run 29468568771](https://github.com/shawliu998/Glint/actions/runs/29468568771), all four jobs successful | **Accepted baseline only** |
| Latest pushed P2.5 evidence at snapshot | Commit `30a423db94694467fac7c3474955c8351388b833`; [Actions run 29471470028](https://github.com/shawliu998/Glint/actions/runs/29471470028) was in progress when inspected | **Pending final result** |

The green run is a real remote CI baseline, but it predates later P2.5 commits
and therefore cannot accept the final candidate.

## Mac build

Command used by the native gate:

```bash
pnpm --filter @glint/mac exec tauri build --debug --bundles app --no-sign -- --locked
```

Observed local output:

```text
apps/mac/src-tauri/target/debug/bundle/macos/Glint.app
CFBundleIdentifier = com.glint.workbench
executable = Mach-O 64-bit arm64
```

The local bundle exists and the native gate covers real traffic lights, Keychain,
offline cache/restart, WebView startup, token scanning, and clean exit. The
artifact is explicitly built with `--no-sign`; local inspection reports only an
ad-hoc/linker signature, no Team Identifier. It is **not Developer ID signed and
not notarized**. Rebuild and rerun the native gate at the final SHA before
changing this item from conditional to accepted.

## Deterministic verification

The recorded 2026-07-16 combined gate:

```bash
./scripts/verify_phase2.sh
```

exited `0` with no failed layers. It covered locked dependencies, static checks,
contracts, RLS/security, deterministic GitHub/RSS fixtures, imported CSV,
API/worker/Postgres, Mac unit/build, fixture and external-API E2E, native runtime,
and the reviewed vertical path. Full commands and per-layer counts are in
[Phase 1 / Phase 2 deterministic acceptance](./PHASE1_P2_ACCEPTANCE.md).

This evidence accepts the deterministic boundary only. It must be rerun at the
final candidate SHA because later P2.5 work is not covered by the historical
record.

## Authenticity matrix

| Evidence class | Available evidence | Acceptance meaning |
| --- | --- | --- |
| **Imported** | Deterministic CSV import reaches terminal `ImportManifest`, Signal, review, Decision Brief, and audited Markdown export | Accepted for deterministic behavior, not external user data |
| **Deterministic** | Seed/import fixtures, connector fixtures, strict API fixture, unit/integration/security/E2E gates | Reproducible acceptance; not live network proof |
| **Captured Fixture** | No captured public payload is committed | **Pending / unavailable** |
| **Live verification** | Opt-in read-only runner exists; no authorized final result is recorded | **Pending** for both GitHub and RSS |
| **No LLM** | Current accepted research/synthesis path is deterministic; model egress is not authorized | Explicit current product boundary |

Domain `Collected` is a lineage value and does not, without a live-smoke record,
prove that a specific item was fetched during a live verification.

## Live GitHub verification

Required command (only with explicit authorization and secrets supplied through
the documented environment references):

```bash
GLINT_ENABLE_LIVE_SMOKE=1 ./scripts/verify_live_connectors.sh
```

Result: **Pending — not run for acceptance**. Pagination, incremental behavior,
rate-limit response, unavailable-item behavior, and secret-free output are
covered deterministically, but no real GitHub response is claimed.

## Live RSS verification

Result: **Pending — not run for acceptance**. RSS/Atom parsing, redirects, SSRF,
content type/body cap, stable versioning, and duplicate behavior are covered by
deterministic tests, but no real feed response is claimed. See [live connector
smoke](./LIVE_CONNECTOR_SMOKE.md) for the exact sources, redaction contract, and
degraded-result semantics.

## Vertical flow

| Stage | Deterministic imported path | Live-collected path |
| --- | --- | --- |
| `ContentVersion` → Signal | Verified | Pending live proof |
| Human triage → Investigation | Verified | Pending live proof |
| Supporting Evidence | Verified | Pending live proof |
| Counter Evidence / counter-search record | Verified by deterministic acceptance | Pending live proof |
| Claim review | Verified | Pending live proof |
| Synthesis review | Verified | Pending live proof |
| Decision Brief → DecisionReady | Verified | Pending live proof |
| Version-bound Markdown export and terminal audit | Verified | Pending live proof |

The deterministic path is real application/domain execution with fixture or
imported inputs; it is not proof that the whole flow completed from a real
GitHub/RSS collection on the final candidate.

## Portfolio artifacts

Required publishable paths and current state:

| Artifact | Status |
| --- | --- |
| `docs/assets/glint-inbox.png` | Pending |
| `docs/assets/glint-signal-detail.png` | Pending |
| `docs/assets/glint-investigation.png` | Pending |
| `docs/assets/glint-decision-brief.png` | Pending |
| `docs/assets/glint-monitoring.png` | Pending |
| [90-second demo script](./DEMO_SCRIPT.md) | Complete; no video claimed |
| [Pilot plan](./PILOT_PLAN.md) | Complete; no sessions/results claimed |

Existing files under `tests/artifacts/` are test evidence. They are not listed
as portfolio screenshots and must not be copied into `docs/assets/` without a
real-app capture and privacy/authenticity review.

## Unresolved risks

1. Final candidate remote CI and native rebuild are not recorded.
2. GitHub and RSS live behavior, freshness, rate limits, and incremental cursors
   lack an authorized acceptance run.
3. Distribution is unsigned/not notarized; external pilot installation is not
   ready.
4. There are no reviewed, secret-free real-app portfolio captures.
5. No external pilot, production SLO, operations exercise, disaster recovery,
   security certification, or GA evidence exists.
6. Source coverage remains limited, and model-assisted research is intentionally
   absent.

## Out of scope

- Phase 3 model-assisted/LangGraph research
- Full collaboration and RBAC UI
- Additional social/content connectors
- Automatic external publishing
- Production deployment, SLOs, on-call, disaster recovery, and GA certification

## Final acceptance checklist

Before changing the decision to `Accepted`, record all of the following in one
update from the final published SHA:

- final commit SHA and successful, non-cancelled remote Actions URL;
- rebuilt `.app` path and successful native gate at that SHA;
- deterministic `verify_phase2.sh` result at that SHA;
- authorized GitHub and RSS live-smoke outcomes, including explicit skips or
  degraded checks (a skip cannot pass the corresponding requirement);
- one complete live-collected vertical-flow result, if required by the P2.5
  definition of done;
- five reviewed real-app screenshots; and
- remaining risks plus the Phase 3 recommendation.
