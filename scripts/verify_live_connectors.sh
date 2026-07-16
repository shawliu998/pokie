#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"

if [[ "${GLINT_ENABLE_LIVE_SMOKE:-0}" != "1" ]]; then
  printf 'SKIP live connector smoke: set GLINT_ENABLE_LIVE_SMOKE=1 to permit network egress\n'
  exit 0
fi

PYTHON_BIN=${PYTHON_BIN:-python3}
"$PYTHON_BIN" -m pytest -q tests/smoke/test_live_connector_controls.py
"$PYTHON_BIN" -m scripts.live_connector_smoke
