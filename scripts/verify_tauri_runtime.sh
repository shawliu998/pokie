#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'Tauri native runtime gate is macOS-only; Linux CI uses the Vite/API gates.\n'
  exit 0
fi

command -v pnpm >/dev/null 2>&1 || { printf 'pnpm is required for the native Tauri gate\n' >&2; exit 2; }
command -v node >/dev/null 2>&1 || { printf 'node is required for the native Tauri gate\n' >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { printf 'curl is required for the native Tauri gate\n' >&2; exit 2; }
command -v rg >/dev/null 2>&1 || { printf 'ripgrep is required for the native artifact token scan\n' >&2; exit 2; }
command -v plutil >/dev/null 2>&1 || { printf 'macOS plutil is required for the app bundle gate\n' >&2; exit 2; }
command -v security >/dev/null 2>&1 || { printf 'macOS security CLI is required for the Keychain gate\n' >&2; exit 2; }
cargo_bin=${CARGO_BIN:-}
if [[ -z "$cargo_bin" && -x "/opt/homebrew/opt/rustup/bin/cargo" ]]; then
  cargo_bin=/opt/homebrew/opt/rustup/bin/cargo
fi
if [[ -z "$cargo_bin" ]]; then
  cargo_bin=$(command -v cargo || true)
fi
[[ -n "$cargo_bin" && -x "$cargo_bin" ]] || {
  printf 'cargo is required for the native Tauri gate\n' >&2
  exit 2
}
export PATH="$(dirname "$cargo_bin"):$PATH"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT_DIR/apps/mac/src-tauri/target}"

# The WebView must obtain credentials from Keychain. Capture only the inputs
# needed to mint a fresh acceptance token, then remove every token-bearing
# environment variable before any Tauri build or dev process starts.
provided_token=${GLINT_TAURI_ACCESS_TOKEN:-${GLINT_TAURI_FIXTURE_TOKEN:-}}
auth_secret=${GLINT_AUTH_HMAC_SECRET:-}
auth_audience=${GLINT_AUTH_AUDIENCE:-glint-api}
auth_issuer=${GLINT_AUTH_ISSUER:-glint-acceptance}
unset GLINT_TAURI_ACCESS_TOKEN GLINT_TAURI_FIXTURE_TOKEN VITE_GLINT_ACCESS_TOKEN
unset GLINT_AUTH_HMAC_SECRET GLINT_AUTH_ACCESS_TOKEN GLINT_AUTH_FORGED_TOKEN GLINT_AUTH_EXPIRED_TOKEN

printf '\n==> Tauri native build and Keychain unit boundary\n'
"$cargo_bin" test --locked --manifest-path apps/mac/src-tauri/Cargo.toml
pnpm --filter @glint/mac test -- --run
pnpm --filter @glint/mac exec tauri build --debug --bundles app --no-sign -- --locked
native_app="$CARGO_TARGET_DIR/debug/bundle/macos/Qurio.app"
native_app_plist="$native_app/Contents/Info.plist"
native_app_binary="$native_app/Contents/MacOS/glint"
[[ -d "$native_app" && -f "$native_app_plist" && -x "$native_app_binary" ]] || {
  printf 'Native gate did not produce a runnable Qurio.app bundle.\n' >&2
  exit 2
}
bundle_identifier=$(plutil -extract CFBundleIdentifier raw -o - "$native_app_plist")
[[ "$bundle_identifier" == "com.glint.workbench" && "$bundle_identifier" != *.app ]] || {
  printf 'Native Qurio.app bundle identifier is invalid.\n' >&2
  exit 2
}
if rg -n 'className="traffic"|>●[[:space:]]+●[[:space:]]+●<' apps/mac/src >/dev/null; then
  printf 'Native gate found fake React traffic lights.\n' >&2
  exit 2
fi

scan_native_artifacts() (
  local artifact
  local scan_status
  [[ -n "${native_scan_token:-}" ]] || return 0
  for artifact in apps/mac/dist "$CARGO_TARGET_DIR"; do
    [[ -d "$artifact" ]] || continue
    if printf '%s' "$native_scan_token" | rg -a -F -f - -- "$artifact" >/dev/null; then
      printf 'Native artifact token scan failed for %s.\n' "$artifact" >&2
      return 1
    else
      scan_status=$?
    fi
    if ((scan_status > 1)); then
      printf 'Native artifact token scan could not inspect %s.\n' "$artifact" >&2
      return 1
    fi
  done
)

native_scan_token=$provided_token
scan_native_artifacts

port_is_free() {
  local port=$1
  node - "$port" <<'NODE'
const net = require('node:net');
const port = Number(process.argv[2]);
const server = net.createServer();
server.once('error', () => process.exit(1));
server.listen({ host: '127.0.0.1', port }, () => server.close(() => process.exit(0)));
NODE
}

if [[ -n "${GLINT_TAURI_FIXTURE_PORT:-}" ]]; then
  fixture_port=$GLINT_TAURI_FIXTURE_PORT
else
  fixture_port=$(node <<'NODE'
const net = require('node:net');
const server = net.createServer();
server.listen({ host: '127.0.0.1', port: 0 }, () => {
  process.stdout.write(String(server.address().port));
  server.close(() => process.exit(0));
});
server.once('error', () => process.exit(1));
NODE
)
fi
port_is_free 1420 || {
  printf 'Tauri dev port 1420 is already occupied; refusing to test an unknown process.\n' >&2
  exit 2
}
port_is_free "$fixture_port" || {
  printf 'Native fixture port is already occupied; refusing to test an unknown process.\n' >&2
  exit 2
}
fixture_url="http://127.0.0.1:${fixture_port}"
api_url=${GLINT_TAURI_API_URL:-}
fixture_principal=${GLINT_TAURI_FIXTURE_PRINCIPAL:-00000000-0000-4000-8000-000000000002}
fixture_workspace=${GLINT_TAURI_WORKSPACE_ID:-00000000-0000-4000-8000-000000000001}
fixture_token="$provided_token"
if [[ -n "$auth_secret" ]]; then
  fixture_token=$(printf '%s\0%s\0%s\0%s' \
    "$auth_secret" "$auth_audience" "$auth_issuer" "$fixture_principal" | node -e '
    const crypto = require("node:crypto");
    const values = require("node:fs").readFileSync(0).toString("utf8").split("\0");
    const [secret, audience, issuer, principal] = values;
    const b64 = value => Buffer.from(JSON.stringify(value)).toString("base64url");
    const now = Math.floor(Date.now() / 1000);
    const header = b64({ alg: "HS256", typ: "JWT" });
    const payload = b64({ sub: principal, iat: now, exp: now + 900, aud: audience, iss: issuer });
    const input = `${header}.${payload}`;
    const signature = crypto.createHmac("sha256", secret).update(input).digest("base64url");
    process.stdout.write(`${input}.${signature}`);
  ')
elif [[ -z "$fixture_token" ]]; then
  fixture_token=$(printf '%s' "$fixture_principal" | node -e '
    const b64 = value => Buffer.from(JSON.stringify(value)).toString("base64url");
    const principal = require("node:fs").readFileSync(0, "utf8");
    const now = Math.floor(Date.now() / 1000);
    const expiry = now + 900;
    process.stdout.write(`${b64({ alg: "none", typ: "JWT" })}.${b64({ sub: principal, iat: now, exp: expiry, aud: "glint-api", iss: "glint-fixture" })}.fixture-signature`);
  ')
fi
printf '%s\0%s' "$fixture_token" "$fixture_principal" | node -e '
  const [rawToken, principal] = require("node:fs").readFileSync(0).toString("utf8").split("\0");
  const token = rawToken.split(".");
  if (token.length !== 3) process.exit(1);
  const claims = JSON.parse(Buffer.from(token[1], "base64url").toString("utf8"));
  if (claims.sub !== principal || !Number.isInteger(claims.exp) || claims.exp <= Math.floor(Date.now() / 1000)) process.exit(1);
' || {
  printf 'Native fixture token must be a three-segment JWT with subject and expiry claims\n' >&2
  exit 2
}
native_scan_token=$fixture_token
scan_native_artifacts
keychain_service=com.glint.app.session
keychain_account=access-token
original_default_keychain=$(security default-keychain -d user \
  | sed -E 's/^[[:space:]]*"(.*)"$/\1/')
original_keychains=()
while IFS= read -r line; do
  keychain_entry=$(printf '%s' "$line" | sed -E 's/^[[:space:]]*"(.*)"$/\1/')
  [[ -n "$keychain_entry" ]] && original_keychains+=("$keychain_entry")
done < <(security list-keychains -d user)
temporary_keychain_directory=""
temporary_keychain=""
temporary_keychain_password=""
temporary_keychain_created=0
keychain_state_modified=0
fixture_log=""
tauri_log=""
ready_marker=""
cors_headers=""
cache_path="$HOME/Library/Application Support/com.glint.workbench/offline-cache/workspace-${fixture_workspace}.json"
cache_backup=""
cache_had_value=0
cache_state_modified=0
fixture_pid=""
tauri_pid=""
expected_native_cdhash=""

keychain_state_matches_original() {
  local current_default
  local keychain_entry
  local line
  local index
  local current_keychains=()
  current_default=$(security default-keychain -d user \
    | sed -E 's/^[[:space:]]*"(.*)"$/\1/') || return 1
  [[ "$current_default" == "$original_default_keychain" ]] || return 1
  while IFS= read -r line; do
    keychain_entry=$(printf '%s' "$line" | sed -E 's/^[[:space:]]*"(.*)"$/\1/')
    [[ -n "$keychain_entry" ]] && current_keychains+=("$keychain_entry")
  done < <(security list-keychains -d user) || return 1
  ((${#current_keychains[@]} == ${#original_keychains[@]})) || return 1
  for index in "${!original_keychains[@]}"; do
    [[ "${current_keychains[$index]}" == "${original_keychains[$index]}" ]] || return 1
  done
}

cleanup() {
  local cleanup_status=0
  local keychain_restored=1
  local preserve_temporary_keychain=0
  if [[ -n "$tauri_pid" ]]; then
    if ! stop_tauri; then
      cleanup_status=1
    fi
  fi
  if [[ -n "$fixture_pid" ]]; then
    kill "$fixture_pid" 2>/dev/null || true
    wait "$fixture_pid" 2>/dev/null || true
  fi
  if ((keychain_state_modified)); then
    security list-keychains -d user -s "${original_keychains[@]}" \
      >/dev/null 2>&1 || keychain_restored=0
    security default-keychain -d user -s "$original_default_keychain" \
      >/dev/null 2>&1 || keychain_restored=0
    if ((keychain_restored)) && ! keychain_state_matches_original; then
      keychain_restored=0
    fi
    if ((keychain_restored)); then
      keychain_state_modified=0
    else
      cleanup_status=1
      preserve_temporary_keychain=1
    fi
  fi
  if ((temporary_keychain_created && !keychain_state_modified)); then
    if ! security delete-keychain "$temporary_keychain" >/dev/null 2>&1; then
      cleanup_status=1
      preserve_temporary_keychain=1
    fi
  elif ((temporary_keychain_created)); then
    preserve_temporary_keychain=1
  fi
  if ((cache_state_modified)); then
    if ((cache_had_value)); then
      mkdir -p "$(dirname "$cache_path")"
      cp "$cache_backup" "$cache_path"
    else
      rm -f "$cache_path"
    fi
  fi
  for cleanup_path in "$fixture_log" "$tauri_log" "$ready_marker" "$cors_headers" "$cache_backup"; do
    [[ -n "$cleanup_path" ]] && rm -f "$cleanup_path"
  done
  if ((preserve_temporary_keychain == 0)) && [[ -n "$temporary_keychain_directory" ]]; then
    rm -rf "$temporary_keychain_directory"
  fi
  if ((cleanup_status != 0)); then
    if ((preserve_temporary_keychain)); then
      printf 'Native cleanup failed; the temporary Keychain was preserved at %s because the original user Keychain state could not be proven restored.\n' "$temporary_keychain" >&2
    else
      printf 'Native cleanup failed: Tauri descendants, port 1420, cache, or Keychain cleanup remains incomplete.\n' >&2
    fi
    exit "$cleanup_status"
  fi
}
trap cleanup EXIT

temporary_keychain_directory=$(mktemp -d "${TMPDIR:-/tmp}/glint-native-keychain.XXXXXX")
temporary_keychain="$temporary_keychain_directory/native.keychain-db"
temporary_keychain_password=$(node -e \
  'process.stdout.write(require("node:crypto").randomBytes(32).toString("hex"))')
fixture_log=$(mktemp "${TMPDIR:-/tmp}/glint-tauri-fixture.XXXXXX")
tauri_log=$(mktemp "${TMPDIR:-/tmp}/glint-tauri-native.XXXXXX")
ready_marker=$(mktemp "${TMPDIR:-/tmp}/glint-tauri-ready.XXXXXX")
cors_headers=$(mktemp "${TMPDIR:-/tmp}/glint-tauri-cors.XXXXXX")
cache_backup=$(mktemp "${TMPDIR:-/tmp}/glint-tauri-cache.XXXXXX")
if [[ -f "$cache_path" ]]; then
  cp "$cache_path" "$cache_backup"
  cache_had_value=1
fi
cache_state_modified=1
rm -f "$cache_path" "$ready_marker"
native_binary="$CARGO_TARGET_DIR/debug/glint"
[[ -x "$native_binary" ]] || {
  printf 'Native gate did not build the Qurio debug binary.\n' >&2
  exit 2
}

if [[ -z "$api_url" ]]; then
  api_url="$fixture_url"
  printf '%s' "$fixture_token" | GLINT_FIXTURE_PORT="$fixture_port" \
    GLINT_FIXTURE_ACCESS_TOKEN_STDIN=1 \
    GLINT_FIXTURE_ALLOWED_ORIGIN=http://127.0.0.1:1420 \
    node apps/mac/e2e/api-fixture.mjs >"$fixture_log" 2>&1 &
  fixture_pid=$!
  for _ in $(seq 1 30); do
    if curl -fsS "$api_url/healthz" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi
curl -fsS "$api_url/healthz" >/dev/null

native_origin=http://127.0.0.1:1420
if ! curl -fsS -X OPTIONS "$api_url/v1/sync/bootstrap" \
  -H "Origin: $native_origin" \
  -H 'Access-Control-Request-Method: GET' \
  -H 'Access-Control-Request-Headers: Authorization,X-Workspace-ID' \
  -D "$cors_headers" -o /dev/null; then
  printf 'Native API CORS preflight failed before WebView startup.\n' >&2
  exit 1
fi
allowed_origin=$(awk \
  'tolower($0) ~ /^access-control-allow-origin:/ {\
    sub(/^[^:]*:[[:space:]]*/, "", $0); gsub(/\r/, "", $0); print $0\
  }' \
  "$cors_headers" | tail -1)
if [[ "$allowed_origin" != "$native_origin" || "$allowed_origin" == "*" ]]; then
  printf 'Native API CORS allow-origin does not exactly match the Tauri dev origin.\n' >&2
  exit 1
fi

binary_cdhash() {
  codesign -dv --verbose=4 "$native_binary" 2>&1 \
    | awk -F= '/^CDHash=/{print $2; exit}'
}

fixture_curl() {
  printf 'header = "Authorization: Bearer %s"\n' "$fixture_token" \
    | curl --config - "$@"
}

start_tauri() {
  local target_api=$1
  local vite_ready=0
  local current_cdhash
  port_is_free 1420 || {
    printf 'Tauri dev port 1420 became occupied before startup.\n' >&2
    return 1
  }
  : >"$tauri_log"
  rm -f "$ready_marker"
  VITE_GLINT_DATA_MODE=api VITE_GLINT_API_URL="$target_api" \
    VITE_GLINT_WORKSPACE_ID="$fixture_workspace" \
    VITE_GLINT_PRINCIPAL_ID="$fixture_principal" \
    pnpm --filter @glint/mac exec tauri dev --no-watch -- --locked >"$tauri_log" 2>&1 &
  tauri_pid=$!
  for _ in $(seq 1 45); do
    if ! kill -0 "$tauri_pid" 2>/dev/null; then
      printf 'Tauri dev process exited before the native ready marker.\n' >&2
      tail -40 "$tauri_log" >&2 || true
      return 1
    fi
    if curl -fsS http://127.0.0.1:1420 >/dev/null 2>&1; then
      vite_ready=1
      break
    fi
    sleep 1
  done
  if ((vite_ready == 0)); then
    printf 'Tauri WebView/Vite ready marker was not observed.\n' >&2
    tail -40 "$tauri_log" >&2 || true
    return 1
  fi
  for _ in $(seq 1 120); do
    if ! kill -0 "$tauri_pid" 2>/dev/null; then
      printf 'Tauri dev process exited before the native binary started.\n' >&2
      tail -80 "$tauri_log" >&2 || true
      return 1
    fi
    if rg -q 'Running.*target/debug/glint' "$tauri_log"; then
      current_cdhash=$(binary_cdhash)
      if [[ -n "$expected_native_cdhash" \
        && "$current_cdhash" != "$expected_native_cdhash" ]]; then
        printf 'Tauri dev rewrote the trusted native binary after Keychain ACL setup.\n' >&2
        return 1
      fi
      printf 'native-webview-ready\n' >"$ready_marker"
      return 0
    fi
    sleep 1
  done
  printf 'Tauri native binary start marker was not observed.\n' >&2
  tail -80 "$tauri_log" >&2 || true
  return 1
}

terminate_process_tree() {
  local root=$1
  local child
  for child in $(pgrep -P "$root" 2>/dev/null || true); do
    terminate_process_tree "$child"
  done
  kill -TERM "$root" 2>/dev/null || true
}

release_dev_port() {
  for _ in $(seq 1 50); do
    if port_is_free 1420; then
      return 0
    fi
    sleep 0.2
  done
  printf 'An owned Tauri descendant did not release port 1420; refusing to kill an unverified listener.\n' >&2
  return 1
}

stop_tauri() {
  [[ -n "$tauri_pid" ]] || return 0
  terminate_process_tree "$tauri_pid"
  wait "$tauri_pid" 2>/dev/null || true
  tauri_pid=""
  release_dev_port
}

activate_temporary_keychain() {
  security create-keychain -p "$temporary_keychain_password" "$temporary_keychain"
  temporary_keychain_created=1
  security set-keychain-settings -lut 3600 "$temporary_keychain"
  security unlock-keychain -p "$temporary_keychain_password" "$temporary_keychain"
  keychain_state_modified=1
  security list-keychains -d user -s "$temporary_keychain"
}

store_fixture_session() {
  local fixture_token_hex
  fixture_token_hex=$(printf '%s' "$fixture_token" | node -e '
    const chunks = [];
    process.stdin.on("data", chunk => chunks.push(chunk));
    process.stdin.on("end", () => process.stdout.write(Buffer.concat(chunks).toString("hex")));
  ')
  # `security -w` uses a short interactive-password buffer and truncates JWTs.
  # Feed an interactive `-X` command over stdin so the full secret reaches the
  # Keychain without ever appearing in a process argument or environment value.
  if ! printf 'add-generic-password -s %s -a %s -T "%s" -T /usr/bin/security -X %s "%s"\n' \
    "$keychain_service" "$keychain_account" "$native_binary" \
    "$fixture_token_hex" "$temporary_keychain" | security -i >/dev/null; then
    printf 'Native gate could not write the fixture session to its isolated Keychain.\n' >&2
    return 1
  fi
  if ! stored_keychain_value=$(security find-generic-password -s "$keychain_service" \
    -a "$keychain_account" -w "$temporary_keychain" 2>/dev/null); then
    printf 'Native gate could not read back the isolated fixture session.\n' >&2
    return 1
  fi
  if [[ "$stored_keychain_value" != "$fixture_token" ]]; then
    printf 'Native gate read back a mismatched isolated fixture session.\n' >&2
    return 1
  fi
}

activate_temporary_keychain
# Warm the exact `tauri dev` binary while the isolated Keychain is empty.  This
# prevents a build after SecTrustedApplication captured the binary CDHash.
start_tauri "$api_url"
stop_tauri
expected_native_cdhash=$(binary_cdhash)
[[ -n "$expected_native_cdhash" ]]
store_fixture_session
start_tauri "$api_url"
native_scan_token=$fixture_token
scan_native_artifacts
for _ in $(seq 1 45); do
  [[ -s "$cache_path" ]] && break
  sleep 1
done
[[ -s "$cache_path" ]] || {
  printf 'Native online bootstrap did not persist the protected offline cache.\n' >&2
  if [[ -n "$fixture_pid" ]]; then
    printf 'Sanitized native fixture request trace:\n' >&2
    tail -80 "$fixture_log" >&2 || true
  else
    printf 'Native external API mode has no local fixture request trace.\n' >&2
  fi
  printf 'Native process log tail:\n' >&2
  tail -80 "$tauri_log" >&2 || true
  exit 1
}
cache_mode=$(stat -f '%Lp' "$cache_path")
[[ "$cache_mode" == "600" ]] || {
  printf 'Native offline cache permissions are not 0600.\n' >&2
  exit 1
}
cache_contents=$(<"$cache_path")
[[ "$cache_contents" != *'"access_token"'* && "$cache_contents" != *'"credential_ref"'* \
  && "$cache_contents" != *'"secret"'* && "$cache_contents" != *"$fixture_token"* ]] || {
  printf 'Native offline cache contains a forbidden secret-bearing field.\n' >&2
  exit 1
}
printf '%s' "$cache_contents" | grep -Eq '"cached_at":"[^"]+"'
printf '%s' "$cache_contents" | grep -q 'cachedAt'
stored_keychain_value=$(security find-generic-password -s "$keychain_service" \
  -a "$keychain_account" -w "$temporary_keychain" 2>/dev/null)
[[ "$stored_keychain_value" == "$fixture_token" ]]
stop_tauri

offline_api_url=http://127.0.0.1:9
if [[ -n "$fixture_pid" ]]; then
  fixture_curl -fsS -X POST "$fixture_url/v1/fixture-control" \
    -H "X-Workspace-ID: $fixture_workspace" \
    -H 'Idempotency-Key: native-offline-control' \
    -H 'Content-Type: application/json' \
    -d '{"api_offline":true}' >/dev/null
  offline_api_url="$fixture_url"
fi
start_tauri "$offline_api_url"
scan_native_artifacts
sleep 5
kill -0 "$tauri_pid" 2>/dev/null
offline_cache_contents=$(<"$cache_path")
[[ "$offline_cache_contents" == "$cache_contents" ]] || {
  printf 'Native offline restart changed the protected cache unexpectedly.\n' >&2
  exit 1
}
if [[ -n "$fixture_pid" ]]; then
  fixture_state=$(fixture_curl -fsS "$fixture_url/v1/fixture-state" \
    -H "X-Workspace-ID: $fixture_workspace")
  [[ "$fixture_state" == *'"offline_mutation_request_count":0'* \
    && "$fixture_state" == *'"offline_sse_request_count":0'* \
    && "$fixture_state" == *'"offline_export_request_count":0'* ]] || {
    printf 'Native offline cache attempted a write, SSE, or export request.\n' >&2
    exit 1
  }
fi
if [[ "${GLINT_REQUIRE_NATIVE_UI_ACCESSIBILITY:-0}" == "1" ]]; then
  ui_text=$(osascript <<'APPLESCRIPT' 2>/dev/null || true
tell application "System Events"
  tell process "glint"
    set values to value of every static text of entire contents of front window
    return values as text
  end tell
end tell
APPLESCRIPT
  )
  [[ "$ui_text" == *"Offline cached read-only"* \
    && "$ui_text" == *"cached_at"* \
    && "$ui_text" == *"SSE, exports"* ]] || {
    printf 'Native offline window did not expose cached_at/read-only disabled state.\n' >&2
    exit 1
  }
else
  printf 'Native Accessibility scrape disabled; app-native cache/counter and @glint/mac unit gates are required.\n'
fi
stop_tauri
printf 'PASS: Tauri native build, JWT Keychain boundary, native cache store/load, offline restart, WebView, and clean exit\n'
