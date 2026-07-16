#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-}
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  elif command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v python3.12)
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v python3)
  else
    PYTHON_BIN="python3.12"
  fi
fi

UV_BIN=${UV_BIN:-}
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/uv" ]]; then
    UV_BIN="$ROOT_DIR/.venv/bin/uv"
  elif [[ -x "$HOME/Library/Python/3.12/bin/uv" ]]; then
    UV_BIN="$HOME/Library/Python/3.12/bin/uv"
  elif command -v uv >/dev/null 2>&1; then
    UV_BIN=$(command -v uv)
  fi
fi

CARGO_BIN=${CARGO_BIN:-}
if [[ -z "$CARGO_BIN" ]]; then
  if [[ -x "/opt/homebrew/opt/rustup/bin/cargo" ]]; then
    CARGO_BIN="/opt/homebrew/opt/rustup/bin/cargo"
  elif command -v cargo >/dev/null 2>&1; then
    CARGO_BIN=$(command -v cargo)
  fi
fi

FAILED_LAYERS=()
SKIPPED_LAYERS=()

layer_status() {
  local name=$1
  shift
  printf '\n==> %s\n' "$name"
  if "$@"; then
    printf 'PASS: %s\n' "$name"
    return 0
  else
    local status=$?
    FAILED_LAYERS+=("$name")
    printf 'FAIL (%s): %s\n' "$status" "$name"
    return "$status"
  fi
}

layer() {
  layer_status "$@" || true
}

skip_layer() {
  local name=$1
  local reason=$2
  SKIPPED_LAYERS+=("$name: $reason")
  printf '\nSKIP: %s — %s\n' "$name" "$reason"
}

finish_layers() {
  printf '\n== verification summary ==\n'
  if ((${#FAILED_LAYERS[@]})); then
    printf 'failed layers:\n'
    printf '  - %s\n' "${FAILED_LAYERS[@]}"
  else
    printf 'failed layers: none\n'
  fi
  if ((${#SKIPPED_LAYERS[@]})); then
    printf 'skipped layers:\n'
    printf '  - %s\n' "${SKIPPED_LAYERS[@]}"
  else
    printf 'skipped layers: none\n'
  fi
  if ((${#FAILED_LAYERS[@]})); then
    return 1
  fi
}

python_module() {
  "$PYTHON_BIN" -m "$@"
}

has_python_module() {
  "$PYTHON_BIN" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$1') else 1)"
}

run_pytest() {
  python_module pytest "$@"
}

run_required_pytest() {
  local output status
  if output=$(env -u PYTEST_ADDOPTS "$PYTHON_BIN" -m pytest -q --strict-markers -o addopts='' "$@" 2>&1); then
    status=0
  else
    status=$?
  fi
  printf '%s\n' "$output"
  if ((status != 0)); then
    return "$status"
  fi
  if printf '%s\n' "$output" | grep -Eiq '([0-9]+ skipped|SKIPPED|[0-9]+ xfailed|XFAIL|[0-9]+ xpassed|XPASS|[0-9]+ deselected)'; then
    printf 'Required pytest layer contains skip/xfail/xpass/deselected tests\n' >&2
    return 1
  fi
}

run_required_pytest_selected() {
  local output status
  if output=$(env -u PYTEST_ADDOPTS "$PYTHON_BIN" -m pytest -q --strict-markers -o addopts='' "$@" 2>&1); then
    status=0
  else
    status=$?
  fi
  printf '%s\n' "$output"
  if ((status != 0)); then
    return "$status"
  fi
  if printf '%s\n' "$output" | grep -Eiq '([0-9]+ skipped|SKIPPED|[0-9]+ xfailed|XFAIL|[0-9]+ xpassed|XPASS)'; then
    printf 'Selected pytest layer contains skip/xfail/xpass tests\n' >&2
    return 1
  fi
}

run_existing_test_dir() {
  local directory=$1
  if [[ -d "$directory" ]] && find "$directory" -type f -name '*.py' -print -quit | grep -q .; then
    run_pytest "$directory"
  else
    printf 'No Python tests found in %s\n' "$directory" >&2
    return 2
  fi
}

run_existing_required_test_dir() {
  local directory=$1
  shift
  if [[ -d "$directory" ]] && find "$directory" -type f -name '*.py' -print -quit | grep -q .; then
    run_required_pytest "$directory" "$@"
  else
    printf 'No Python tests found in %s\n' "$directory" >&2
    return 2
  fi
}
