#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=verify_common.sh
source "$SCRIPT_DIR/verify_common.sh"
cd "$ROOT_DIR"

if has_python_module pytest; then
  layer "Phase 3 bounded model runtime" \
    run_required_pytest tests/eval/test_model_research.py
  layer "Phase 3 model policy integration" \
    run_required_pytest \
      tests/integration/test_collected_research_lineage.py::test_model_run_is_blocked_when_server_runtime_policy_is_disabled \
      tests/integration/test_collected_research_lineage.py::test_authorized_model_run_freezes_provider_and_exposes_redacted_metadata
  layer "Phase 3 reviewed model-quality replay tests" \
    run_required_pytest tests/eval/test_phase3_model_quality.py
  layer "Phase 3 reviewed model-quality replay gate" \
    "$PYTHON_BIN" scripts/evaluate_phase3_model_quality.py \
      --artifact-dir tests/artifacts
  layer "Phase 3 prompt-injection containment" \
    run_required_pytest tests/security/test_prompt_injection_containment.py
else
  layer "Phase 3 bounded model runtime" false
  layer "Phase 3 model policy integration" false
  layer "Phase 3 reviewed model-quality replay tests" false
  layer "Phase 3 reviewed model-quality replay gate" false
  layer "Phase 3 prompt-injection containment" false
fi

finish_layers
