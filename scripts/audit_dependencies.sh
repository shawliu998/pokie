#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=verify_common.sh
source "$SCRIPT_DIR/verify_common.sh"
cd "$ROOT_DIR"

[[ -f uv.lock ]] || { printf 'uv.lock is required for dependency auditing\n' >&2; exit 2; }
[[ -n "$UV_BIN" && -x "$UV_BIN" ]] || {
  printf 'uv 0.11.28 is required for dependency auditing\n' >&2
  exit 2
}
uv_version=$("$UV_BIN" --version 2>/dev/null || true)
[[ "$uv_version" =~ ^uv[[:space:]]0\.11\.28([[:space:]]|$) ]] || {
  printf 'uv 0.11.28 is required for dependency auditing\n' >&2
  exit 2
}
uvx_bin=${UVX_BIN:-}
if [[ -z "$uvx_bin" && -x "$(dirname "$UV_BIN")/uvx" ]]; then
  uvx_bin="$(dirname "$UV_BIN")/uvx"
elif [[ -z "$uvx_bin" ]]; then
  uvx_bin=$(command -v uvx || true)
fi
[[ -n "$uvx_bin" && -x "$uvx_bin" ]] || {
  printf 'uvx is required for the pinned pip-audit gate\n' >&2
  exit 2
}

requirements_file=$(mktemp "${TMPDIR:-/tmp}/glint-audit-requirements.XXXXXX")
chmod 600 "$requirements_file"
cleanup() { rm -f "$requirements_file"; }
trap cleanup EXIT

printf '==> Python dependency export\n'
"$UV_BIN" export --locked --all-extras --no-dev --no-emit-project --no-hashes >"$requirements_file"
printf '==> Python dependency audit (pip-audit 2.10.1)\n'
"$uvx_bin" --from pip-audit==2.10.1 pip-audit \
  -r "$requirements_file" \
  --strict --no-deps --disable-pip -s pypi --progress-spinner off

command -v pnpm >/dev/null 2>&1 || {
  printf 'pnpm is required for npm dependency auditing\n' >&2
  exit 2
}
[[ -f pnpm-lock.yaml ]] || {
  printf 'pnpm-lock.yaml is required for dependency auditing\n' >&2
  exit 2
}
printf '==> npm lock dependency audit (official bulk endpoint)\n'
audit_status=0
if ! "$PYTHON_BIN" "$SCRIPT_DIR/audit_npm_lock.py" pnpm-lock.yaml \
  --scope full --audit-level moderate; then
  audit_status=1
fi
if ! "$PYTHON_BIN" "$SCRIPT_DIR/audit_npm_lock.py" pnpm-lock.yaml \
  --scope prod --audit-level moderate; then
  audit_status=1
fi

tauri_locks=()
while IFS= read -r lock_path; do
  tauri_locks+=("$lock_path")
done < <(find "$ROOT_DIR" -path '*/src-tauri/Cargo.lock' -type f -print | sort)
if ((${#tauri_locks[@]} == 0)); then
  printf 'No Tauri Cargo.lock files found\n' >&2
  exit 2
fi
cargo_audit_bin=${CARGO_AUDIT_BIN:-$(command -v cargo-audit || true)}
if [[ -z "$cargo_audit_bin" && -n "${CARGO_BIN:-}" && -x "$(dirname "$CARGO_BIN")/cargo-audit" ]]; then
  cargo_audit_bin="$(dirname "$CARGO_BIN")/cargo-audit"
fi
[[ -n "$cargo_audit_bin" && -x "$cargo_audit_bin" ]] || {
  printf 'cargo-audit 0.22.2 is required for Rust dependency auditing\n' >&2
  exit 2
}
version=$("$cargo_audit_bin" --version 2>/dev/null || true)
printf '%s\n' "$version" | grep -Eq '(^|[^0-9])0\.22\.2([^0-9]|$)' || {
  printf 'cargo-audit 0.22.2 is required; found: %s\n' "$version" >&2
  exit 2
}
for lock_path in "${tauri_locks[@]}"; do
  printf '==> Rust dependency audit: %s\n' "${lock_path#"$ROOT_DIR/"}"
  if ! "$cargo_audit_bin" audit --file "$lock_path"; then
    audit_status=1
  fi
done
exit "$audit_status"
