#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=verify_common.sh
source "$SCRIPT_DIR/verify_common.sh"
cd "$ROOT_DIR"

layer "Python 3.12" "$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
layer "Python compile" "$PYTHON_BIN" -m compileall -q connectors packages services tests infra/migrations

if [[ -f uv.lock ]]; then
  if [[ -n "$UV_BIN" ]]; then
    layer "Python lock check" "$UV_BIN" lock --check
    layer "Python locked sync" "$UV_BIN" sync --locked --extra test --no-install-project
    if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
      PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    fi
  else
    layer "Python lock check" false
    layer "Python locked sync" false
  fi
else
  layer "Python lock check" false
  layer "Python locked sync" false
fi

uv_exact_version() {
  local version
  [[ -n "$UV_BIN" ]] || return 1
  version=$("$UV_BIN" --version 2>/dev/null || true)
  [[ "$version" =~ ^uv[[:space:]]0\.11\.28([[:space:]]|$) ]]
}
layer "uv exact version" uv_exact_version

if [[ -n "$UV_BIN" ]]; then
  layer "Python dependency environment" "$UV_BIN" pip check --python "$PYTHON_BIN"
else
  layer "Python dependency environment" false
fi

layer "Dependency vulnerability audit (Python/npm/Rust)" "$SCRIPT_DIR/audit_dependencies.sh"

if has_python_module ruff; then
  layer "ruff check" python_module ruff check connectors packages services tests
  layer "ruff format" python_module ruff format --check connectors packages services tests
  if compgen -G "infra/migrations/versions/*.py" >/dev/null; then
    layer "ruff check migration history" python_module ruff check --no-force-exclude infra/migrations/versions/*.py
    layer "ruff format migration history" python_module ruff format --check --no-force-exclude infra/migrations/versions/*.py
  else
    layer "ruff check migration history" false
    layer "ruff format migration history" false
  fi
else
  layer "ruff check" false
  layer "ruff format" false
  layer "ruff check migration history" false
  layer "ruff format migration history" false
fi

if has_python_module pyright; then
  layer "pyright" python_module pyright
else
  layer "pyright" false
fi

if has_python_module pytest; then
  layer "contract tests" run_required_pytest tests/contract
  layer "runtime contract tests" run_required_pytest tests/runtime/test_runtime_contracts.py
  layer "npm bulk audit adapter tests" run_required_pytest tests/runtime/test_dependency_audit.py
  layer "migration history tests" run_required_pytest tests/runtime/test_migration_history.py
  layer "P1 connector security/import/object-store tests" run_required_pytest \
    tests/connector/test_compose_security.py \
    tests/connector/test_csv_import_security.py \
    tests/connector/test_import_poll.py \
    tests/connector/test_object_store_adapter.py \
    tests/connector/test_research_lineage.py::test_research_lineage_accepts_v1_import_manifest_and_rejects_raw_tamper
  layer "smoke tests" run_required_pytest \
    tests/smoke/test_api_smoke.py::test_api_health_and_bootstrap_routes_are_exposed \
    tests/smoke/test_api_smoke.py::test_secret_redaction_never_returns_fixture_credentials_or_local_paths
  for test_layer in integration security eval license performance; do
    test_dir="tests/$test_layer"
    if [[ -d "$test_dir" ]] && find "$test_dir" -type f -name '*.py' -print -quit | grep -q .; then
      if [[ "$test_layer" == "security" ]]; then
        layer "$test_layer tests" run_existing_required_test_dir "$test_dir" \
          --ignore "$test_dir/test_postgres_rls.py"
      else
        layer "$test_layer tests" run_existing_required_test_dir "$test_dir"
      fi
    else
      layer "$test_layer tests" false
    fi
  done
  layer "OpenAPI drift" run_required_pytest \
    tests/runtime/test_runtime_contracts.py::test_openapi_contains_shared_contracts_when_api_exists
else
  layer "contract tests" false
  layer "runtime contract tests" false
  layer "npm bulk audit adapter tests" false
  layer "migration history tests" false
  layer "P1 connector security/import/object-store tests" false
  layer "smoke tests" false
  for test_layer in integration security eval license performance; do
    layer "$test_layer tests" false
  done
  layer "OpenAPI drift" false
fi

if command -v pnpm >/dev/null 2>&1; then
  layer "pnpm frozen install" pnpm install --frozen-lockfile
  layer "pnpm lint" pnpm lint
  layer "pnpm typecheck" pnpm typecheck
  layer "pnpm unit" pnpm test
  layer "pnpm build" pnpm build
  fixture_e2e() {
    env -u GLINT_E2E_API_URL -u GLINT_E2E_ACCESS_TOKEN -u GLINT_E2E_WORKSPACE_ID \
      GLINT_E2E_API_MODE=fixture GLINT_E2E_FIXTURE_MODE=1 pnpm test:e2e
  }
  printf '\nINFO: running explicit fixture E2E as a non-runtime UI smoke only\n'
  layer "pnpm E2E (fixture, non-runtime)" fixture_e2e
else
  layer "pnpm lint" false
  layer "pnpm typecheck" false
  layer "pnpm unit" false
  layer "pnpm build" false
  layer "pnpm E2E (fixture, non-runtime)" false
fi

TAURI_MANIFEST="$ROOT_DIR/apps/mac/src-tauri/Cargo.toml"
if [[ -f "$TAURI_MANIFEST" ]] && [[ -n "$CARGO_BIN" ]]; then
  CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-${TMPDIR:-/tmp}/glint-cargo-target}"
  export CARGO_TARGET_DIR
  layer "Tauri cargo check" "$CARGO_BIN" check --locked --manifest-path "$TAURI_MANIFEST"
else
  layer "Tauri cargo check" false
fi

COMPOSE_FILE="$ROOT_DIR/infra/docker-compose.yml"
export GLINT_AUTH_PRINCIPAL_ID="${GLINT_AUTH_PRINCIPAL_ID:-22222222-2222-5222-8222-222222222222}"
export GLINT_AUTH_WORKSPACE_ID="${GLINT_AUTH_WORKSPACE_ID:-11111111-1111-5111-8111-111111111111}"
random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    "$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(32))'
  fi
}
export GLINT_AUTH_HMAC_SECRET="${GLINT_AUTH_HMAC_SECRET:-$(random_secret)}"
export GLINT_AUTH_AUDIENCE="${GLINT_AUTH_AUDIENCE:-glint-api}"
export GLINT_AUTH_ISSUER="${GLINT_AUTH_ISSUER:-glint-acceptance}"
export GLINT_AUTH_TOKEN_TTL_SECONDS="${GLINT_AUTH_TOKEN_TTL_SECONDS:-900}"
export GLINT_CONNECTOR_CURSOR_SECRET="${GLINT_CONNECTOR_CURSOR_SECRET:-$(random_secret)}"
export GLINT_MIGRATION_DATABASE_URL="${GLINT_MIGRATION_DATABASE_URL:-postgresql+psycopg://glint_owner:glint_owner_dev_password@postgres:5432/glint}"
export GLINT_WORKSPACE_ID="$GLINT_AUTH_WORKSPACE_ID"
export VITE_GLINT_WORKSPACE_ID="$GLINT_AUTH_WORKSPACE_ID"
export VITE_GLINT_ACCESS_TOKEN="${VITE_GLINT_ACCESS_TOKEN:-}"
export COMPOSE_PROJECT_NAME="glint-p1-acceptance-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}-$$-$(date +%s)-${RANDOM}"

export GLINT_ACCEPTANCE_ARTIFACT_DIR="$ROOT_DIR/tests/artifacts/$COMPOSE_PROJECT_NAME"
compose=()
RUNTIME_AUTH_FILE=""
cleanup_compose() {
  local main_status=$?
  local cleanup_status=0
  if [[ -n "$RUNTIME_AUTH_FILE" ]]; then
    rm -f "$RUNTIME_AUTH_FILE"
  fi
  if ((${#compose[@]})); then
    if "${compose[@]}" down --remove-orphans -v >/dev/null 2>&1; then
      :
    else
      cleanup_status=$?
      printf 'Compose teardown failed; residual resources for %s:\n' "$COMPOSE_PROJECT_NAME" >&2
      docker ps -a --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
        --format 'container={{.Names}} status={{.Status}}' >&2 || true
      docker network ls --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
        --format 'network={{.Name}}' >&2 || true
      docker volume ls --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
        --format 'volume={{.Name}}' >&2 || true
    fi
  fi
  if ((main_status != 0)); then
    exit "$main_status"
  fi
  if ((cleanup_status != 0)); then
    exit "$cleanup_status"
  fi
}
trap cleanup_compose EXIT

compose_service_is() {
  local service=$1
  local expected=$2
  local container state health exit_code
  container=$("${compose[@]}" ps -aq "$service")
  [[ -n "$container" ]]
  state=$(docker inspect --format '{{.State.Status}}' "$container")
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")
  exit_code=$(docker inspect --format '{{.State.ExitCode}}' "$container")
  case "$expected" in
    healthy) [[ "$state" == "running" && "$health" == "healthy" ]] ;;
    running) [[ "$state" == "running" ]] ;;
    completed) [[ "$state" == "exited" && "$exit_code" == "0" ]] ;;
    *) return 2 ;;
  esac
}

redact_compose_output() {
  sed -E \
    -e 's/(Bearer[[:space:]]+)[^[:space:]]+/\1[REDACTED]/g' \
    -e 's/(GLINT_[A-Z0-9_]*(TOKEN|SECRET|PASSWORD)[=:][[:space:]]*)[^[:space:]]+/\1[REDACTED]/g' \
    -e 's#(postgres(ql)?\+?[a-z]*://[^:]+:)[^@[:space:]]+@#\1[REDACTED]@#g'
}

compose_health_diagnostics() {
  local service container
  for service in smoke api worker; do
    container=$("${compose[@]}" ps -aq "$service")
    if [[ -n "$container" ]]; then
      printf '\n--- %s logs (redacted tail) ---\n' "$service" >&2
      docker logs --tail 200 "$container" 2>&1 | redact_compose_output >&2 || true
    else
      printf '\n--- %s logs unavailable: container not created ---\n' "$service" >&2
    fi
  done
}

compose_health() {
  local output=""
  local smoke_container smoke_state smoke_exit_code
  local smoke_log
  for attempt in $(seq 1 60); do
    if ! output=$("${compose[@]}" ps -a 2>&1); then
      printf '%s\n' "$output" >&2
      return 1
    fi
    smoke_container=$("${compose[@]}" ps -aq smoke)
    if [[ -n "$smoke_container" ]]; then
      smoke_state=$(docker inspect --format '{{.State.Status}}' "$smoke_container")
      smoke_exit_code=$(docker inspect --format '{{.State.ExitCode}}' "$smoke_container")
      if [[ "$smoke_state" == "exited" && "$smoke_exit_code" != "0" ]]; then
        printf 'Compose smoke failed: exit_code=%s\n' "$smoke_exit_code" >&2
        compose_health_diagnostics
        return 1
      fi
    fi
    if compose_service_is postgres healthy \
      && compose_service_is redis healthy \
      && compose_service_is minio healthy \
      && compose_service_is minio-init completed \
      && compose_service_is api healthy \
      && compose_service_is worker healthy \
      && [[ -n "$smoke_container" ]] \
      && compose_service_is smoke completed; then
      smoke_log=$(docker logs "$smoke_container" 2>&1)
      if printf '%s\n' "$smoke_log" | grep -Fx 'glint_api|false|false|false|false|false|false|0' >/dev/null \
        && printf '%s\n' "$smoke_log" | grep -Fx 'glint_worker|false|false|false|false|false|false|0' >/dev/null \
        && printf '%s\n' "$smoke_log" | grep -Fx 'false|false|false|false|0' >/dev/null; then
        printf 'Compose smoke completed: exit_code=0, non_root_rls_log=present\n'
        return 0
      fi
    fi
    sleep 1
  done
  printf '%s\n' "$output" >&2
  compose_health_diagnostics
  return 1
}

seed_workspace() {
  "${compose[@]}" exec -T postgres psql -U glint_owner -d glint -v ON_ERROR_STOP=1 \
    -v acceptance_workspace="$GLINT_AUTH_WORKSPACE_ID" \
    -v acceptance_principal="$GLINT_AUTH_PRINCIPAL_ID" <<'SQL'
BEGIN;
SELECT set_config('app.workspace_id', :'acceptance_workspace', true);
SELECT set_config('app.principal_id', :'acceptance_principal', true);
INSERT INTO workspaces (
  id, created_at, updated_at, row_version, data_authenticity, name, status,
  data_region, retention_policy_version, created_by
)
VALUES (
  :'acceptance_workspace', now(), now(), 1, 'human_authored',
  'Glint P1 Acceptance', 'active', 'local', 'retention-v1', :'acceptance_principal'
)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  status = 'active',
  created_by = EXCLUDED.created_by,
  updated_at = now();
INSERT INTO workspace_members (
  id, created_at, updated_at, data_authenticity, workspace_id, user_id, role, status
)
VALUES (
  '33333333-3333-5333-8333-333333333333', now(), now(), 'human_authored',
  :'acceptance_workspace', :'acceptance_principal', 'owner', 'active'
)
ON CONFLICT (workspace_id, user_id) DO NOTHING;
COMMIT;
SQL
}

seed_runtime() {
  local auth_file
  local seed_status
  auth_file=$(umask 077; mktemp "${TMPDIR:-/tmp}/glint-runtime-auth.XXXXXX")
  RUNTIME_AUTH_FILE="$auth_file"
  chmod 600 "$auth_file"
  if ! seed_workspace; then
    return 1
  fi
  if "$PYTHON_BIN" -m scripts.seed_runtime \
      --base-url "${GLINT_SMOKE_API_URL:-http://127.0.0.1:8000}" \
      --principal "$GLINT_AUTH_PRINCIPAL_ID" \
      --workspace "$GLINT_AUTH_WORKSPACE_ID" \
      --auth-output "$auth_file"; then
    seed_status=0
  else
    seed_status=$?
  fi
  if [[ -s "$auth_file" ]]; then
    export GLINT_AUTH_ACCESS_TOKEN="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["access_token"])' "$auth_file")"
    export GLINT_AUTH_FORGED_TOKEN="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["forged_token"])' "$auth_file")"
    export GLINT_AUTH_EXPIRED_TOKEN="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["expired_token"])' "$auth_file")"
    export VITE_GLINT_ACCESS_TOKEN="$GLINT_AUTH_ACCESS_TOKEN"
  fi
  return "$seed_status"
}

postgres_rls() {
  local result
  result=$("${compose[@]}" exec -T postgres psql -U glint_owner -d glint -Atqc \
    "SELECT (
       (SELECT count(*) FROM pg_roles WHERE rolname = 'glint_app' AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit) = 1
       AND (SELECT count(*) FROM pg_roles WHERE rolname = 'glint_api' AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit) = 1
       AND (SELECT count(*) FROM pg_roles WHERE rolname = 'glint_worker' AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit) = 1
       AND (SELECT count(*) FROM pg_auth_members membership JOIN pg_roles member_role ON member_role.oid = membership.member WHERE member_role.rolname IN ('glint_app', 'glint_api', 'glint_worker')) = 0
       AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity) > 0
       AND (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity AND NOT c.relforcerowsecurity) = 0
     );" \
    | tr -d '\r')
  [[ "$result" == "t" ]]
}

postgres_rls_tests() {
  local database="glint_test_${COMPOSE_PROJECT_NAME//[^a-zA-Z0-9_]/_}"
  local database_url="postgresql+psycopg://glint_owner:glint_owner_dev_password@127.0.0.1:${GLINT_POSTGRES_PORT:?}/$database"
  local present
  present=$("${compose[@]}" exec -T postgres psql -U glint_owner -d postgres -Atqc \
    "SELECT 1 FROM pg_database WHERE datname = '$database'")
  if [[ -z "$present" ]]; then
    "${compose[@]}" exec -T postgres createdb -U glint_owner "$database"
  fi
  GLINT_TEST_POSTGRES_URL="$database_url" \
    GLINT_TEST_API_PASSWORD=glint_api_dev_password \
    GLINT_TEST_WORKER_PASSWORD=glint_worker_dev_password \
    run_required_pytest tests/security/test_postgres_rls.py
}

runtime_ports() {
  local api_endpoint postgres_endpoint
  if ! api_endpoint=$("${compose[@]}" port api 8000); then
    return 1
  fi
  if ! postgres_endpoint=$("${compose[@]}" port postgres 5432); then
    return 1
  fi
  [[ -n "$api_endpoint" && -n "$postgres_endpoint" ]]
  export GLINT_API_PORT="${api_endpoint##*:}"
  export GLINT_POSTGRES_PORT="${postgres_endpoint##*:}"
  export GLINT_SMOKE_API_URL="http://127.0.0.1:${GLINT_API_PORT}"
}

compose_up_retry() {
  local attempt
  local status
  for attempt in 1 2 3; do
    if "${compose[@]}" up -d --build; then
      return 0
    else
      status=$?
    fi
    printf 'Compose startup attempt %s failed (status %s); removing partial project before retry.\n' \
      "$attempt" "$status" >&2
    if "${compose[@]}" down --remove-orphans -v; then
      :
    else
      printf 'Compose retry cleanup failed; refusing to retry with residual resources.\n' >&2
      return 1
    fi
  done
  return "$status"
}

api_e2e() {
  local e2e_api_url="${GLINT_SMOKE_API_URL:-}"
  local e2e_access_token="${GLINT_AUTH_ACCESS_TOKEN:-}"
  local e2e_workspace="${GLINT_AUTH_WORKSPACE_ID:-}"
  local capture_dir="${GLINT_ACCEPTANCE_ARTIFACT_DIR:?}/ui"
  if [[ -z "$e2e_api_url" || -z "$e2e_access_token" || -z "$e2e_workspace" ]]; then
    printf 'The current Compose GLINT_SMOKE_API_URL/auth/workspace values are required for API-mode E2E\n' >&2
    return 2
  fi
  umask 077
  mkdir -p "$capture_dir"
  chmod 700 "$capture_dir"
  env -u GLINT_E2E_API_URL -u GLINT_E2E_ACCESS_TOKEN -u GLINT_E2E_WORKSPACE_ID \
    -u VITE_GLINT_API_URL -u VITE_GLINT_ACCESS_TOKEN -u VITE_GLINT_WORKSPACE_ID \
    GLINT_E2E_API_MODE=external \
    GLINT_E2E_API_URL="$e2e_api_url" \
    GLINT_E2E_ACCESS_TOKEN="$e2e_access_token" \
    GLINT_E2E_WORKSPACE_ID="$e2e_workspace" \
    GLINT_E2E_CAPTURE_DIR="$capture_dir" \
    VITE_GLINT_DATA_MODE=api \
    VITE_GLINT_API_URL="$e2e_api_url" \
    VITE_GLINT_WORKSPACE_ID="$e2e_workspace" \
    VITE_GLINT_ACCESS_TOKEN="$e2e_access_token" \
    pnpm test:e2e
}

compose_preflight() {
  local containers networks volumes
  containers=$(docker ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")
  networks=$(docker network ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")
  volumes=$(docker volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")
  [[ -z "$containers" && -z "$networks" && -z "$volumes" ]]
}

compose_up_ok=0
compose_health_ok=0
runtime_seed_ok=0
if [[ ! -f "$COMPOSE_FILE" ]]; then
  layer "Compose runtime required gate" false
elif ! command -v docker >/dev/null 2>&1; then
  layer "Compose runtime required gate" false
else
  compose=(docker compose -f "$COMPOSE_FILE" -f "$SCRIPT_DIR/compose-acceptance.yml")
  if layer_status "Compose project preflight" compose_preflight; then
    layer "docker compose config" "${compose[@]}" config --quiet
    if layer_status "docker compose up --build" compose_up_retry; then
      compose_up_ok=1
    fi
  else
    layer "docker compose config" false
    layer "docker compose up --build" false
  fi
  if ((compose_up_ok)); then
    layer "Compose runtime ports" runtime_ports
    if layer_status "docker compose health" compose_health; then
      compose_health_ok=1
    fi
    if ((compose_health_ok)); then
      layer "Postgres/RLS runtime" postgres_rls
      layer "Postgres/RLS acceptance tests" postgres_rls_tests
      seed_layer="API health/bootstrap and worker seed"
      if [[ "${GLINT_ACCEPTANCE_CLOUD_OWNER_LOOP:-0}" == "1" ]]; then
        seed_layer="P2 Compose scheduler→CollectionRun/raw/CV/Signal→collected owner loop"
      fi
      if layer_status "$seed_layer" seed_runtime; then
        runtime_seed_ok=1
      fi
      if ((runtime_seed_ok)); then
        export GLINT_PRODUCTION_AUTH_SMOKE=1
        export GLINT_SMOKE_API_URL="${GLINT_SMOKE_API_URL:-http://127.0.0.1:8000}"
        layer "production auth token smoke" run_required_pytest \
          tests/smoke/test_production_auth_smoke.py
        if [[ "$(uname -s)" == "Darwin" ]]; then
          GLINT_TAURI_API_URL="$GLINT_SMOKE_API_URL" \
            GLINT_TAURI_ACCESS_TOKEN="$GLINT_AUTH_ACCESS_TOKEN" \
            GLINT_TAURI_FIXTURE_PRINCIPAL="$GLINT_AUTH_PRINCIPAL_ID" \
            GLINT_TAURI_WORKSPACE_ID="$GLINT_AUTH_WORKSPACE_ID" \
            layer "Tauri native runtime" "$SCRIPT_DIR/verify_tauri_runtime.sh"
        fi
      else
        layer "production auth token smoke" false
        if [[ "$(uname -s)" == "Darwin" ]]; then
          layer "Tauri native runtime" false
        fi
      fi
    else
      layer "Postgres/RLS runtime" false
      layer "Postgres/RLS acceptance tests" false
      layer "API health/bootstrap and worker seed" false
      layer "production auth token smoke" false
      if [[ "$(uname -s)" == "Darwin" ]]; then
        layer "Tauri native runtime" false
      fi
    fi
  else
    layer "Compose runtime ports" false
    layer "docker compose health" false
    layer "Postgres/RLS runtime" false
    layer "Postgres/RLS acceptance tests" false
    layer "API health/bootstrap and worker seed" false
    layer "production auth token smoke" false
    if [[ "$(uname -s)" == "Darwin" ]]; then
      layer "Tauri native runtime" false
    fi
  fi
fi

if [[ "${GLINT_E2E_API_MODE:-external}" == "external" || "${GLINT_E2E_API_MODE:-external}" == "1" ]]; then
  if ((compose_up_ok && runtime_seed_ok)); then
    layer "pnpm E2E API mode" api_e2e
  else
    layer "pnpm E2E API mode" false
  fi
else
  layer "pnpm E2E API mode" false
fi

finish_layers
