#!/bin/sh
set -eu

[ "$(id -u)" != "0" ] || {
  echo "compose smoke must not run as root" >&2
  exit 1
}

assert_runtime_role() {
  database_url="$1"
  expected_role="$2"
  psql "$database_url" -X -v ON_ERROR_STOP=1 -Atc \
    "select current_user || '|' || rolsuper || '|' || rolcreatedb || '|' || rolcreaterole || '|' || rolreplication || '|' || rolbypassrls || '|' || rolinherit || '|' || (select count(*) from pg_auth_members membership where membership.member = pg_roles.oid) from pg_roles where rolname = current_user" \
    | grep -Fx "${expected_role}|false|false|false|false|false|false|0"
}

expect_db_denied() {
  label="$1"
  statement="$2"
  if output=$(psql "$GLINT_WORKER_DATABASE_URL" -X -v ON_ERROR_STOP=1 -c "$statement" 2>&1); then
    echo "worker unexpectedly performed forbidden write: $label" >&2
    exit 1
  fi
  printf '%s\n' "$output" | grep -E "permission denied|row-level security" >/dev/null || {
    echo "unexpected PostgreSQL failure for $label: $output" >&2
    exit 1
  }
}

assert_runtime_role "$GLINT_API_DATABASE_URL" glint_api
assert_runtime_role "$GLINT_WORKER_DATABASE_URL" glint_worker
psql "$GLINT_API_DATABASE_URL" -X -v ON_ERROR_STOP=1 -Atc \
  "select rolcanlogin || '|' || rolsuper || '|' || rolbypassrls || '|' || rolinherit || '|' || (select count(*) from pg_auth_members membership where membership.member = pg_roles.oid) from pg_roles where rolname = 'glint_app'" \
  | grep -Fx "false|false|false|false|0"
psql "$GLINT_WORKER_DATABASE_URL" -X -v ON_ERROR_STOP=1 -Atc \
  "select has_column_privilege(current_user, 'source_connections', 'status', 'UPDATE') || '|' || has_column_privilege(current_user, 'source_connections', 'approved_by', 'UPDATE') || '|' || (has_table_privilege(current_user, 'brief_exports', 'INSERT') OR has_table_privilege(current_user, 'brief_exports', 'UPDATE') OR has_table_privilege(current_user, 'brief_exports', 'DELETE')) || '|' || has_table_privilege(current_user, 'audit_logs', 'INSERT') || '|' || (has_table_privilege(current_user, 'audit_logs', 'UPDATE') OR has_table_privilege(current_user, 'audit_logs', 'DELETE'))" \
  | grep -Fx "true|false|false|true|false"
expect_db_denied "BriefExport insert" "INSERT INTO brief_exports DEFAULT VALUES"
expect_db_denied "arbitrary AuditLog insert" \
  "SELECT set_config('app.workspace_id', '00000000-0000-0000-0000-000000000001', false); INSERT INTO audit_logs (id, workspace_id, actor_id, action, target_type, target_id, request_id, details_json, occurred_at, data_authenticity) VALUES ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'worker', 'worker.arbitrary', 'Workspace', '00000000-0000-0000-0000-000000000001', 'compose-smoke', '{}'::json, now(), 'generated')"
curl -fsS "http://api:8000/healthz" >/dev/null
/opt/glint-venv/bin/python -m services.worker.app.main health >/dev/null

/opt/glint-venv/bin/python - <<'PY'
from __future__ import annotations

import os
import uuid

import boto3
from botocore.exceptions import ClientError


def is_denied(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {
        "AccessDenied",
        "AllAccessDisabled",
        "InvalidAccessKeyId",
    }


bucket = os.environ["GLINT_S3_BUCKET"]
client = boto3.client(
    "s3",
    endpoint_url=os.environ["GLINT_S3_ENDPOINT_URL"],
    aws_access_key_id=os.environ["GLINT_S3_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["GLINT_S3_SECRET_ACCESS_KEY"],
    region_name=os.environ.get("GLINT_AWS_REGION", "us-east-1"),
)
key = f"compose-smoke/{uuid.uuid4()}.txt"
client.put_object(Bucket=bucket, Key=key, Body=b"ok")
try:
    if client.get_object(Bucket=bucket, Key=key)["Body"].read() != b"ok":
        raise SystemExit("S3 smoke object body mismatch")
finally:
    client.delete_object(Bucket=bucket, Key=key)

try:
    listed = client.list_buckets().get("Buckets", [])
except ClientError as exc:
    if not is_denied(exc):
        raise SystemExit("unexpected S3 list-buckets error") from exc
else:
    names = sorted(item["Name"] for item in listed)
    if names != [bucket] or "glint-private-canary" in names:
        raise SystemExit("S3 list-buckets exposed a bucket outside the app scope")

try:
    client.list_objects_v2(Bucket=bucket)
except ClientError as exc:
    if not is_denied(exc):
        raise SystemExit("unexpected S3 list-objects error") from exc
else:
    raise SystemExit("unexpected S3 permission: list bucket objects succeeded")

try:
    client.create_bucket(Bucket="glint-denied-smoke")
except ClientError as exc:
    if not is_denied(exc):
        raise SystemExit("unexpected S3 create-bucket error") from exc
else:
    raise SystemExit("unexpected S3 permission: create other bucket succeeded")
PY
