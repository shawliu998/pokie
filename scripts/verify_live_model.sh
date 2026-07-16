#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"

if [[ "${GLINT_ENABLE_LIVE_MODEL_SMOKE:-0}" != "1" ]]; then
  echo "SKIP: live model smoke — set GLINT_ENABLE_LIVE_MODEL_SMOKE=1 to permit a provider call"
  exit 0
fi

PYTHON_BIN=${PYTHON_BIN:-"$ROOT_DIR/.venv/bin/python"}
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "FAIL: Python environment is unavailable" >&2
  exit 1
fi

export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" scripts/verify_live_model.py
