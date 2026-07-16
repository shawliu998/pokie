#!/bin/sh
set -eu

: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"

cat > /tmp/glint-app-policy.json <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":["arn:aws:s3:::glint-objects/workspaces/*/imports/*","arn:aws:s3:::glint-objects/quarantine/workspaces/*/imports/*","arn:aws:s3:::glint-objects/workspaces/*/collections/*","arn:aws:s3:::glint-objects/workspaces/*/brief-exports/*","arn:aws:s3:::glint-objects/compose-smoke/*"]}]}
JSON

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing local/glint-objects
mc mb --ignore-existing local/glint-private-canary
(mc admin policy create local glint-app-object-rw-v2 /tmp/glint-app-policy.json || mc admin policy info local glint-app-object-rw-v2 >/dev/null)
(mc admin user add local glint_app_minio glint_app_minio_password || true)
(mc admin policy detach local glint-app-rw --user glint_app_minio || true)
mc admin policy attach local glint-app-object-rw-v2 --user glint_app_minio
