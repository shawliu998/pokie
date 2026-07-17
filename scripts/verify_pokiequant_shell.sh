#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_PYTHON="$SCRIPT_DIR/../.venv/bin/python"
DEFAULT_CODEX_PYTHON=/Users/a1-6/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
if [[ -z "${PYTHON_BIN:-}" && -x "$PROJECT_PYTHON" ]]; then
  export PYTHON_BIN=$PROJECT_PYTHON
elif [[ -z "${PYTHON_BIN:-}" && -x "$DEFAULT_CODEX_PYTHON" ]]; then
  export PYTHON_BIN=$DEFAULT_CODEX_PYTHON
fi
# shellcheck source=verify_common.sh
source "$SCRIPT_DIR/verify_common.sh"
cd "$ROOT_DIR"

assert_quant_truth_boundaries() {
  rg -q 'Synthetic Demo Fixture' \
    README.md \
    services/api/app/modules/quant/snapshot.py \
    apps/mac/src/features/quant
  rg -q '"internetAccess": False' services/api/app/modules/quant/snapshot.py
  rg -q '"arbitraryPython": False' services/api/app/modules/quant/snapshot.py
  rg -q '"paperTrading": False' services/api/app/modules/quant/snapshot.py
  rg -q '1,564.*synthetic' README.md
  rg -q 'Candidate metrics.*pure kernel' README.md
  rg -q 'Daily-bar kernel verified' apps/mac/src/features/quant/QuantActivity.tsx
  rg -q 'No network, broker, model, or arbitrary code execution' \
    services/api/app/modules/quant/kernel_check.py
  rg -qi 'no broker or paper-trading action' services/api/app/modules/quant/snapshot.py
  rg -q 'class QuantRepositoryState' services/api/app/db/models.py
  rg -q 'quant_repository_states' infra/migrations/versions/20260717_0006_quant_phase0_state.py
  rg -q 'build_quant_script' services/api/app/modules/quant/store.py
  rg -q 'claim_fixture_run' services/api/app/modules/quant/store.py
  rg -q 'quant-fixture' services/worker/app/main.py
}

assert_main_path_has_no_glint_product_copy() {
  local output
  if output=$(rg -n -i \
      'Inbox|Signals|Decisions|Monitoring|Product Decision Brief|PRD Research Input' \
      apps/mac/src/app/App.tsx \
      apps/mac/src/features/workbench/Workbench.tsx \
      apps/mac/src/features/quant \
      apps/mac/src/quant-api.ts \
      apps/mac/src/quant-domain.ts); then
    printf '%s\n' "$output" >&2
    return 1
  fi
}

assert_no_unreviewed_dependency_slice() {
  git diff --exit-code -- \
    apps/mac/package.json \
    pnpm-lock.yaml \
    THIRD_PARTY_NOTICES.md
}

assert_quant_screenshots() {
  "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import struct

root = Path("docs/assets/pokiequant")
required = (
    "quant-ready.png",
    "quant-plan-approval.png",
    "quant-running.png",
    "quant-repairing.png",
    "quant-completed.png",
    "quant-no-viable-candidate.png",
)
for name in required:
    path = root / name
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path}")
    width, height = struct.unpack(">II", data[16:24])
    if (width, height) != (1440, 960):
        raise AssertionError(f"unexpected screenshot size for {path}: {(width, height)}")
PY
}

layer "PokieQuant contracts, API, runtime, and OpenAPI" \
  run_required_pytest \
    tests/contract/test_quant_contracts.py \
    tests/contract/test_quant_daily_bar_dataset.py \
    tests/contract/test_quant_ohlcv_csv.py \
    tests/runtime/test_quant_fixture_runtime.py \
    tests/runtime/test_quant_backtest.py \
    tests/runtime/test_quant_research_evaluation.py \
    tests/integration/test_quant_api.py \
    tests/integration/test_quant_dataset_api.py \
    tests/contract/test_schema_export.py

layer "PokieQuant autonomous Agent and shared runtime" \
  run_required_pytest \
    tests/agent_runtime \
    tests/quant_agent \
    tests/eval/test_model_research.py

layer "PokieQuant key Mac unit and component tests" \
  pnpm --dir apps/mac exec vitest run \
    src/quant-api.test.ts \
    src/features/quant/quant-presentation.test.ts \
    src/features/quant/quant-components.test.tsx

layer "PokieQuant Mac lint" pnpm --dir apps/mac lint
layer "PokieQuant Mac typecheck" pnpm --dir apps/mac typecheck
layer "PokieQuant Mac build" pnpm --dir apps/mac build
layer "PokieQuant completed-state E2E" \
  env GLINT_E2E_API_MODE=fixture POKIEQUANT_E2E_RUN_STATE=quant-completed \
  pnpm --dir apps/mac exec playwright test e2e/quant-workspace.spec.ts --reporter=line
layer "PokieQuant API-owned command E2E" \
  env GLINT_E2E_API_MODE=fixture POKIEQUANT_E2E_RUN_STATE=quant-ready \
  pnpm --dir apps/mac exec playwright test e2e/quant-workspace.spec.ts --reporter=line
layer "PokieQuant reviewed screenshots" assert_quant_screenshots
layer "PokieQuant dependency license policy" \
  run_required_pytest tests/license/test_dependency_licenses.py
layer "PokieQuant fixture and disabled-capability truth" assert_quant_truth_boundaries
layer "PokieQuant main path excludes Glint product copy" assert_main_path_has_no_glint_product_copy
layer "PokieQuant adds no unreviewed dependency or notice drift" assert_no_unreviewed_dependency_slice
layer "PokieQuant diff whitespace" git diff --check

finish_layers
