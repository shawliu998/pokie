#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=verify_common.sh
source "$SCRIPT_DIR/verify_common.sh"
cd "$ROOT_DIR"

phase1_status=0
GLINT_ACCEPTANCE_CLOUD_OWNER_LOOP=1 "$SCRIPT_DIR/verify_phase1.sh" || phase1_status=$?
if ((phase1_status != 0)); then
  FAILED_LAYERS+=("Phase 1 aggregate")
fi
layer "P2 Compose collected owner loop" test "$phase1_status" -eq 0

if has_python_module pytest; then
  layer "P2 runtime and connector full tests" run_required_pytest tests/runtime tests/connector
  layer "connector contracts" run_required_pytest_selected tests/runtime/test_phase2_contracts.py -k 'connector or rss or github'
  layer "RSS SSRF policy" run_required_pytest_selected tests/runtime/test_phase2_contracts.py -k ssrf
  layer "GitHub GraphQL fixture" run_required_pytest_selected tests/runtime/test_phase2_contracts.py -k graphql
  layer "repository scheduler gate" run_required_pytest_selected tests/runtime/test_phase2_contracts.py -k repository_scheduler
  layer "scheduler unit" run_required_pytest_selected tests/runtime/test_phase2_contracts.py -k in_memory_scheduler_unit
  layer "collection tests" run_required_pytest_selected tests/runtime/test_phase2_contracts.py -k collection
  layer "cloud collected lineage integration" run_required_pytest_selected \
    tests/integration/test_cloud_sources_and_schedules.py -k collected_signal_response
  layer "collected research lineage" run_required_pytest tests/connector/test_research_lineage.py
  layer "collected owner loop integration" run_required_pytest tests/integration/test_collected_research_lineage.py
  layer "collected owner loop security" run_required_pytest tests/security/test_collected_research_lineage.py
  if command -v pnpm >/dev/null 2>&1; then
    layer "Mac strict API seam" pnpm --filter @glint/mac exec vitest run src/api.test.ts
  else
    layer "Mac strict API seam" false
  fi
  layer "dedupe/repost tests" run_required_pytest_selected tests/runtime/test_phase2_contracts.py -k 'dedupe or repost'
  layer "explanation tests" run_required_pytest_selected tests/runtime/test_phase2_contracts.py -k explanation
else
  layer "Phase 2 Python tests" false
fi

if [[ "${GLINT_ENABLE_LIVE_SMOKE:-0}" == "1" ]]; then
  if has_python_module pytest; then
    layer "explicit live smoke" env GLINT_ENABLE_LIVE_SMOKE=1 PYTHON_BIN="$PYTHON_BIN" \
      "$SCRIPT_DIR/verify_live_connectors.sh"
  else
    layer "explicit live smoke" false
  fi
else
  skip_layer "live smoke" "set GLINT_ENABLE_LIVE_SMOKE=1 to permit network calls"
fi

finish_layers
if ((phase1_status != 0)); then
  exit "$phase1_status"
fi
