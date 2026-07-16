# Phase 1 / Phase 2 Deterministic Acceptance

Acceptance date: 2026-07-16

Command: `./scripts/verify_phase2.sh`

Result: exit `0`; failed layers: none

## Accepted boundary

The combined gate accepted the repository's deterministic local P1/P2 implementation:

- locked Python/npm/Rust dependencies, lint, formatting and static typing;
- Seed/Imported CSV contracts, object-store and consent boundaries, research lineage, review/readiness/freshness and version-bound export behavior;
- GitHub/RSS connector contracts and deterministic fixtures, SSRF policy, scheduler/collection behavior, dedupe/repost and explanation behavior;
- Docker Compose services, Postgres/RLS, cloud scheduler-to-collected-Signal Owner loop and production-auth token smoke;
- Mac lint/type/build/unit checks, fixture E2E, local Compose API E2E, and native Tauri/Keychain/cache/offline-restart/WebView/clean-exit checks.

The Phase 1 aggregate summary reported `failed layers: none` and `skipped layers: none`. The final Phase 2 summary reported `failed layers: none`; live smoke was the sole policy skip because `GLINT_ENABLE_LIVE_SMOKE=1` was not set.

## Key counts from the accepted log

Counts are listed per logged layer and must not be summed as unique tests because several focused P2 layers intentionally rerun subsets.

| Layer | Logged result |
|---|---:|
| Contract | 67 passed |
| Runtime contract | 10 passed |
| npm audit adapter | 8 passed |
| Migration history | 9 passed |
| P1 connector security/import/object store | 24 passed |
| Smoke | 2 passed |
| Integration | 50 passed |
| Security excluding separately executed Postgres/RLS | 57 passed |
| Eval | 11 passed |
| License | 15 passed |
| Performance | 2 passed |
| OpenAPI drift | 1 passed |
| Mac unit | 38 passed across 9 files |
| Fixture E2E | 1 passed |
| Postgres/RLS acceptance | 23 passed |
| Rust native unit boundary | 4 passed |
| Local Compose API E2E | 1 passed |
| P2 runtime and connector full layer | 123 passed |
| Mac strict API seam | 15 passed |

Focused P2 gates also passed for connector contracts (`6`), RSS SSRF (`4`), GitHub GraphQL fixture (`1`), repository scheduler (`1`), scheduler unit (`1`), collection (`2`), cloud collected lineage (`1`), collected research lineage (`10`), Owner-loop integration (`4`), Owner-loop security (`5`), dedupe/repost (`3`) and explanation (`1`).

## Dependency and warning record

- Python dependency audit: no known vulnerabilities.
- npm lock audit: 324 full-scope and 5 production-scope registry artifacts checked; policy passed at level `moderate`.
- Rust audit: 420 locked dependencies scanned; no blocking vulnerability result, with 17 policy-allowed warnings (16 unmaintained crates and one `glib` unsoundness advisory).
- Pyright reported 0 errors and 0 warnings; Ruff checks and formatting checks passed.
- Pytest emitted the known Starlette `httpx` deprecation warning. Playwright emitted `NO_COLOR`/`FORCE_COLOR` environment warnings. These did not fail the gate.
- Native Accessibility scraping was intentionally disabled; the gate instead required the app-native cache/counter, Mac unit, Keychain boundary, offline restart, WebView and clean-exit checks.

The Rust advisories and deprecation warnings remain maintenance risks. Their acceptance here means they were non-blocking under the repository's current deterministic gate policy, not that they are resolved.

## Explicitly not accepted

This result does **not** verify:

- live GitHub/RSS calls, real external credentials, provider rate limits or changing network responses;
- a production environment, production observability/SLOs, disaster recovery or operational support;
- model-assisted Phase 3 research quality;
- external user validation, pilot success, security certification, or GA readiness.

To authorize the separate networked smoke layer, configure its credentials and run with `GLINT_ENABLE_LIVE_SMOKE=1`. A passing live smoke would still not, by itself, establish production, pilot, or GA acceptance.
