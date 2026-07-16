# Glint P2.5 acceptance

Evidence snapshot: 2026-07-16 (Asia/Shanghai)

## Decision

**P2.5 Status: Conditionally Accepted**

The repository trust baseline, final-candidate remote CI, deterministic P1/P2
path, local unsigned Mac bundle, imported-demo vertical flow, and five reviewed
real-app captures have evidence. Final P2.5 acceptance is withheld because live
GitHub/RSS verification has not been authorized/recorded and no external pilot
has run.

Recommendation: **do not enter Phase 3 yet**. Complete the authorized live-data
verification and pilot evidence below first. No `Pending` item may be inferred
as passing.

## Candidate identity and repository

| Item | Evidence | Status |
| --- | --- | --- |
| Final implementation candidate SHA | `be6998d942cb0d1cc0f83f4c26ce1f02fd756eb6` | **Verified** |
| Branch | `feat/p2-5-pilot-workbench` | Recorded |
| Public repository/default branch | Public repository; default branch `main` | Verified in [repository audit](./P2_5_REPOSITORY_AUDIT.md) |
| Branch protection | Strict required `phase1`, `phase2`, `security-audit`, and `macos-native`; admin enforcement enabled | Verified in repository audit |
| Historical trusted baseline | Commit `82a206aceb6ad213582a33323708e0ee500b3dcd`; [Actions run 29468568771](https://github.com/shawliu998/Glint/actions/runs/29468568771), all four jobs successful | Accepted historical baseline |
| Final P2.5 remote evidence | Commit `be6998d942cb0d1cc0f83f4c26ce1f02fd756eb6`; [Actions run 29474562575](https://github.com/shawliu998/Glint/actions/runs/29474562575), `phase1`, `phase2`, `security-audit`, and `macos-native` all successful | **Verified** |

The final green run is real remote CI on the implementation candidate. It
accepts the deterministic and native-build boundaries; it does not convert
unrun live or pilot checks into passing evidence.

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

The local bundle exists and the final-candidate native gate covers real traffic lights, Keychain,
offline cache/restart, WebView startup, token scanning, and clean exit. The
artifact is explicitly built with `--no-sign`; local inspection reports only an
ad-hoc/linker signature, no Team Identifier. It is **not Developer ID signed and
not notarized**. Signing and notarization remain distribution blockers.

## Deterministic verification

The recorded 2026-07-16 combined gate and final remote Phase 1/Phase 2 jobs:

```bash
./scripts/verify_phase2.sh
```

exited `0` with no failed layers. The final implementation candidate also
passed both required remote jobs. Coverage includes locked dependencies, static checks,
contracts, RLS/security, deterministic GitHub/RSS fixtures, imported CSV,
API/worker/Postgres, Mac unit/build, fixture and external-API E2E, native runtime,
and the reviewed vertical path. Full commands and per-layer counts are in
[Phase 1 / Phase 2 deterministic acceptance](./PHASE1_P2_ACCEPTANCE.md).

This evidence accepts the deterministic boundary at the final implementation
candidate SHA only.

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
| `docs/assets/glint-inbox.png` | **Complete** — reviewed 1440×960 real-app render |
| `docs/assets/glint-signal-detail.png` | **Complete** — reviewed 1440×960 real-app render |
| `docs/assets/glint-investigation.png` | **Complete** — reviewed 1440×960 real-app render |
| `docs/assets/glint-decision-brief.png` | **Complete** — reviewed 1440×960 real-app render |
| `docs/assets/glint-monitoring.png` | **Complete** — reviewed 1440×960 real-app render |
| [90-second demo script](./DEMO_SCRIPT.md) | Complete; no video claimed |
| [Pilot plan](./PILOT_PLAN.md) | Complete; no sessions/results claimed |

The five captures came from one real local application render backed by the
API, worker, Postgres, and object store. The visible data mode is **Imported Demo
Fixture**; the run verified 2 supporting and 1 opposing Evidence records, a
`decision_ready` brief, and a terminal digest-bound export. No token, private
path, terminal, browser tooling, or private customer data is visible. See the
[asset manifest](./assets/README.md).

## Unresolved risks

1. GitHub and RSS live behavior, freshness, rate limits, and incremental cursors
   lack an authorized acceptance run.
2. Distribution is unsigned/not notarized; external pilot installation is not
   ready.
3. No external pilot, production SLO, operations exercise, disaster recovery,
   security certification, or GA evidence exists.
4. Source coverage remains limited, and model-assisted research is intentionally
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

- final implementation candidate SHA and successful, non-cancelled remote Actions URL (recorded);
- rebuilt `.app` path and successful native gate at that SHA;
- deterministic `verify_phase2.sh` result at that SHA;
- authorized GitHub and RSS live-smoke outcomes, including explicit skips or
  degraded checks (a skip cannot pass the corresponding requirement);
- one complete live-collected vertical-flow result, if required by the P2.5
  definition of done;
- five reviewed real-app screenshots (completed for the imported-demo boundary); and
- remaining risks plus the Phase 3 recommendation.
