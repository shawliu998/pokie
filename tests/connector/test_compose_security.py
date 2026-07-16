# pyright: reportMissingTypeStubs=false
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())


def _env(service: str) -> dict[str, str]:
    return dict(_compose()["services"][service]["environment"])


def _command(service: str) -> str:
    command = _compose()["services"][service]["command"]
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command)


def test_compose_keeps_api_auth_secret_out_of_worker_and_smoke() -> None:
    api_env = _env("api")
    assert {
        "GLINT_AUTH_HMAC_SECRET",
        "GLINT_AUTH_ISSUER",
        "GLINT_AUTH_AUDIENCE",
    }.issubset(api_env)
    assert api_env["GLINT_SERVICE_ROLE"] == "api"
    assert "GLINT_CONNECTOR_CURSOR_SECRET" not in api_env

    for service in ("worker", "smoke"):
        service_env = _env(service)
        assert service_env["GLINT_SERVICE_ROLE"] == "worker"
        assert "GLINT_CONNECTOR_CURSOR_SECRET" in service_env
        assert not any(key.startswith("GLINT_AUTH_") for key in service_env)


def test_compose_exposes_only_bucket_scoped_minio_credentials_to_app_services() -> None:
    for service in ("api", "worker", "smoke"):
        service_env = _env(service)
        assert service_env["GLINT_S3_ACCESS_KEY_ID"] == "glint_app_minio"
        assert service_env["GLINT_S3_SECRET_ACCESS_KEY"] == "glint_app_minio_password"
        assert all("glint_minio_root" not in str(value) for value in service_env.values())

    minio_env = _env("minio")
    assert minio_env["MINIO_ROOT_USER"] == "glint_minio_root"
    assert minio_env["MINIO_ROOT_PASSWORD"] == "glint_minio_root_password"


def test_minio_init_creates_bucket_scoped_app_user_and_policy() -> None:
    command = _command("minio-init")
    assert "glint-objects" in command
    assert "arn:aws:s3:::glint-objects/workspaces/*/imports/*" in command
    assert "arn:aws:s3:::glint-objects/quarantine/workspaces/*/imports/*" in command
    assert "arn:aws:s3:::glint-objects/workspaces/*/collections/*" in command
    assert "arn:aws:s3:::glint-objects/workspaces/*/brief-exports/*" in command
    assert "s3:ListBucket" not in command
    assert "mc admin user add local glint_app_minio" in command
    assert "mc admin policy detach local glint-app-rw --user glint_app_minio" in command
    assert "mc admin policy attach local glint-app-object-rw-v2 --user glint_app_minio" in command
    assert "glint_minio_root glint_minio_root_password" in command

    acceptance_init = (ROOT / "scripts/minio-acceptance-init.sh").read_text()
    assert "glint-private-canary" in acceptance_init
    assert "mc mb --ignore-existing local/glint-private-canary" in acceptance_init


def test_python_app_image_runs_as_non_root_user() -> None:
    dockerfile = (ROOT / "infra/docker/python-app/Dockerfile").read_text()
    assert "groupadd --system --gid 10001 glint" in dockerfile
    assert "useradd --system --uid 10001 --gid glint" in dockerfile
    assert "chown -R glint:glint /workspace /opt/glint-venv /home/glint" in dockerfile
    assert "USER glint" in dockerfile


def test_compose_smoke_checks_runtime_identity_and_bucket_scope() -> None:
    script = (ROOT / "scripts/compose-smoke-acceptance.sh").read_text()
    assert 'id -u)" != "0"' in script
    assert "put_object(Bucket=bucket" in script
    assert "get_object(Bucket=bucket" in script
    assert "delete_object(Bucket=bucket" in script
    assert "list_buckets" in script
    assert "list_objects_v2" in script
    assert "glint-private-canary" in script
    assert "names != [bucket]" in script
    assert "AccessDenied" in script
    assert 'create_bucket(Bucket="glint-denied-smoke")' in script


def test_base_compose_publishes_runtime_ports_on_loopback_only() -> None:
    compose = _compose()
    assert compose["services"]["postgres"]["ports"] == ["127.0.0.1:5432:5432"]
    assert compose["services"]["redis"]["ports"] == ["127.0.0.1:6379:6379"]
    assert compose["services"]["minio"]["ports"] == [
        "127.0.0.1:9000:9000",
        "127.0.0.1:9001:9001",
    ]
    assert compose["services"]["api"]["ports"] == ["127.0.0.1:8000:8000"]


def test_acceptance_overlay_runs_canary_aware_smoke() -> None:
    overlay = (ROOT / "scripts/compose-acceptance.yml").read_text()
    assert 'command: ["/bin/sh", "scripts/compose-smoke-acceptance.sh"]' in overlay
