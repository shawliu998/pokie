# PokieQuant

PokieQuant is a governed desktop workspace for bounded, auditable quantitative-research workflows.

Phase 0 is a deterministic shell and contract integration. Every displayed bar, metric, trade, candidate verdict, event, and report is a **Synthetic Demo Fixture**. Phase 0 does not retrieve market data, call a model, run a real backtest, execute arbitrary Python or shell commands, connect to a broker, place orders, or provide investment advice.

## Phase 0 status

The current working tree is an integration candidate, not a production release.

Implemented:

- independent Quant contracts, enums, safe event payloads, SSE encoding, and OpenAPI registration;
- authenticated, workspace-scoped `/v1/quant` project/run, approval, cancellation, retry, event, artifact, and experiment routes;
- a server-owned deterministic workspace fixture with ten named E2E states;
- a canonical deterministic runtime script covering Candidate B's recoverable candidate-scoped failure and repair, no-viable-candidate, failed-safe, and cancellation paths;
- PostgreSQL/SQLAlchemy-backed, workspace-scoped Phase 0 aggregate and fixture snapshot state, including refresh/restart recovery and optimistic concurrency;
- a registered `quant-fixture` worker path with lease, heartbeat, fencing, stale-claim rejection, and cancellation fence invalidation;
- Mac navigation, Plan/Activity/Market/Strategy Report/Inspector surfaces, visible authenticity labels, and read-only policy status;
- Mac lifecycle commands routed through the authenticated API snapshot adapter; React does not assign run state;
- tests that keep candidate rejection separate from run failure and assert that the fixture runtime imports no network, process, or arbitrary-execution facilities.

Still intentionally not implemented:

- real or provider-sourced OHLCV/news data;
- a quantitative backtesting or optimization engine;
- Spark/Jupyter/sandbox or uploaded-code execution;
- model/provider calls, web search, or external network access;
- paper or live trading, broker credentials, order routing, or portfolio execution;
- PokieTicker or Spark code migration (both remain blocked on repository, immutable commit, license, and security review);
- a normalized production Quant research schema, multi-worker throughput/SLO validation, and long-running lease cadence. Phase 0 intentionally persists its synthetic aggregate in one workspace-scoped JSON document; it is durable but is not presented as the future market/backtest schema.

The retained Glint modules remain in the repository as inherited infrastructure, but the main Mac path is PokieQuant and does not map Signals, Investigations, Evidence, Claims, Synthesis, or Decision Briefs into financial objects.

## Fixture states

`POKIEQUANT_E2E_RUN_STATE` is server-side development/E2E configuration only. It is not exposed as a production UI control.

```text
quant-ready
quant-plan-approval
quant-running
quant-repairing
quant-validating
quant-waiting-review
quant-completed
quant-no-viable-candidate
quant-failed-safe
quant-cancelled
```

The canonical negative result is a healthy completed process with a retained Research Report:

```text
Run state: completed
Conclusion: No candidate passed validation
```

A rejected candidate or a recoverable candidate experiment failure does not make the run `failed`.

## Reviewed workbench captures

Playwright captures the real 1440×960 React workbench against the loopback fixture API. The checked evidence set covers Ready, Plan Approval, Running, Repairing, Completed, and No Viable Candidate.

![PokieQuant completed synthetic fixture](./docs/assets/pokiequant/quant-completed.png)

![PokieQuant completed with no viable candidate](./docs/assets/pokiequant/quant-no-viable-candidate.png)

## Local setup

Prerequisites: Python 3.12, Node.js, pnpm 10.28.0, and the dependencies already locked by this repository.

```bash
uv sync --locked --extra test
pnpm install --frozen-lockfile
```

The Mac client requires the inherited secure session configuration and an API process:

```bash
VITE_GLINT_API_URL=http://127.0.0.1:8000 \
VITE_GLINT_WORKSPACE_ID=<workspace-uuid> \
VITE_GLINT_ACCESS_TOKEN=<development-token> \
pnpm --filter @glint/mac dev
```

The `VITE_GLINT_*` environment names and `@glint/*` package identifiers are retained compatibility names; they are not product-domain aliases.

## Verification

Run the additive Phase 0 gate:

```bash
./scripts/verify_pokiequant_shell.sh
```

The gate checks Quant contracts, API, runtime fixtures, OpenAPI drift, Mac lint/typecheck/unit/build, license/provenance boundaries, fixture labels, disabled capability claims, and removal of active Glint product-intelligence copy from the main path. It does not enable live connector or model smoke tests.

To reproduce the six reviewed screenshots:

```bash
mkdir -p docs/assets/pokiequant
for state in quant-ready quant-plan-approval quant-running quant-repairing quant-completed quant-no-viable-candidate; do
  GLINT_E2E_API_MODE=fixture \
  POKIEQUANT_E2E_RUN_STATE="$state" \
  POKIEQUANT_CAPTURE_SCREENSHOTS=1 \
  pnpm --dir apps/mac exec playwright test e2e/quant-workspace.spec.ts \
    -g 'captures a real workbench screenshot'
done
```

Inherited gates remain available and are not weakened:

```bash
./scripts/verify_phase1.sh
./scripts/verify_phase2.sh
./scripts/verify_phase3_quality.sh
./scripts/verify_tauri_runtime.sh
```

## Architecture boundary

```text
authenticated workspace session
  -> FastAPI /v1/quant snapshot and commands
  -> durable workspace-scoped fixture repository
  -> fenced deterministic fixture worker/runtime
  -> typed Quant transport and pure presentation projection
  -> React/Tauri workspace
```

The API owns lifecycle and legal commands. The worker owns only the approved deterministic fixture script. The Mac client owns selection, layout, disclosure, and other presentation preferences.

See `docs/POKIEQUANT_PRODUCT_SPEC.md`, `docs/POKIEQUANT_STATE_MATRIX.md`, and `docs/POKIEQUANT_REFERENCE_AUDIT.md` for the product, state, provenance, and license contracts.
