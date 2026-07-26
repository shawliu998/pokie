#!/usr/bin/env python3
"""Run a persistent local Qurio API and Quant Agent worker without a UI server.

The supervisor owns only process lifetime and development bootstrap metadata.  Provider
credentials remain process-environment input and are never written to disk or stdout.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

FROZEN_RUNTIME = bool(getattr(sys, "frozen", False))
REPO_ROOT = (
    Path(sys.executable).resolve().parent
    if FROZEN_RUNTIME
    else Path(__file__).resolve().parents[1]
)
DEFAULT_RUNTIME_DIR = REPO_ROOT / ".run" / "qurio-local-runtime"
SESSION_FILE_NAME = "qurio-local-runtime.json"
DATABASE_FILE_NAME = "qurio-local.db"
OBJECT_DIR_NAME = "objects"
READY_PREFIX = "QURIO_RUNTIME_READY "
DEFAULT_MODEL = "deepseek-v4-flash"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=("mock", "deepseek", "openai_compatible"), default="mock"
    )
    parser.add_argument("--model", default=None, metavar="STRING")
    parser.add_argument("--base-url", default=None, metavar="HTTPS_URL")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR, metavar="PATH")
    parser.add_argument(
        "--child-role",
        choices=("api", "worker"),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--api-port", type=int, default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def resolve_runtime_dir(value: Path) -> Path:
    return value.expanduser().resolve()


def selected_model(provider: str, model: str | None) -> str | None:
    if provider == "mock":
        return None
    cleaned = (model or (DEFAULT_MODEL if provider == "deepseek" else "")).strip()
    if not cleaned or len(cleaned) > 128:
        raise ValueError("--model must contain between 1 and 128 characters.")
    return cleaned


def selected_base_url(provider: str, base_url: str | None) -> str | None:
    if provider != "openai_compatible":
        if base_url is not None:
            raise ValueError("--base-url is supported only for openai_compatible.")
        return None
    cleaned = (base_url or "").strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if (
        len(cleaned) > 2_048
        or parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(character.isspace() or ord(character) < 32 for character in cleaned)
    ):
        raise ValueError("--base-url must be a valid HTTPS provider URL.")
    return cleaned


def require_provider_key(provider: str, environ: dict[str, str] | None = None) -> None:
    if provider == "mock":
        return
    source = os.environ if environ is None else environ
    if not (source.get("POKIEQUANT_AGENT_API_KEY") or source.get("DEEPSEEK_API_KEY")):
        raise ValueError(
            "The selected provider requires POKIEQUANT_AGENT_API_KEY or DEEPSEEK_API_KEY."
        )


def runtime_paths(runtime_dir: Path) -> tuple[Path, Path, Path]:
    return (
        runtime_dir / DATABASE_FILE_NAME,
        runtime_dir / OBJECT_DIR_NAME,
        runtime_dir / SESSION_FILE_NAME,
    )


def _metadata_is_valid(value: Any, database_path: Path) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "principal_id", "workspace_id", "database_path"
    }:
        return False
    return all(isinstance(value[key], str) and value[key] for key in value) and value[
        "database_path"
    ] == str(database_path)


def read_metadata(session_path: Path, database_path: Path) -> dict[str, str] | None:
    if not session_path.exists():
        return None
    try:
        value = json.loads(session_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not _metadata_is_valid(value, database_path):
        return None
    return {key: str(item) for key, item in value.items()}


def write_metadata(session_path: Path, metadata: dict[str, str]) -> None:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(session_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
    os.chmod(session_path, 0o600)


def configure_bootstrap_environment(
    *,
    database_path: Path,
    object_root: Path,
    provider: str,
    model: str | None,
    base_url: str | None = None,
) -> None:
    os.environ.update(
        {
            "GLINT_ENVIRONMENT": "development",
            "GLINT_SERVICE_ROLE": "api",
            "GLINT_DATABASE_URL": f"sqlite:///{database_path}",
            "GLINT_OBJECT_STORE_BACKEND": "filesystem",
            "GLINT_OBJECT_STORE_ROOT": str(object_root),
            "GLINT_CREATE_SCHEMA_ON_STARTUP": "true",
            "GLINT_ALLOWED_ORIGINS": json.dumps(["tauri://localhost"]),
            "POKIEQUANT_AGENT_PROVIDER": provider,
            "POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK": "false",
        }
    )
    if model is None:
        os.environ.pop("POKIEQUANT_AGENT_MODEL", None)
    else:
        os.environ["POKIEQUANT_AGENT_MODEL"] = model
    if base_url is None:
        os.environ.pop("POKIEQUANT_AGENT_BASE_URL", None)
    else:
        os.environ["POKIEQUANT_AGENT_BASE_URL"] = base_url


def bootstrap_metadata(
    *, runtime_dir: Path, provider: str, model: str | None, base_url: str | None = None
) -> dict[str, str]:
    database_path, object_root, session_path = runtime_paths(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    object_root.mkdir(parents=True, exist_ok=True)
    existing = read_metadata(session_path, database_path)
    if existing is not None:
        return existing
    configure_bootstrap_environment(
        database_path=database_path,
        object_root=object_root,
        provider=provider,
        model=model,
        base_url=base_url,
    )
    from services.api.app.core.config import get_settings
    from services.api.app.db.session import reset_database_caches

    get_settings.cache_clear()
    reset_database_caches()
    from fastapi.testclient import TestClient

    from services.api.app.main import app

    principal_id = str(uuid4())
    with TestClient(app) as client:
        response = client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {principal_id}", "Idempotency-Key": str(uuid4())},
            json={
                "name": "Qurio local workspace",
                "data_region": "local",
                "retention_policy_version": "retention-v1",
            },
        )
        response.raise_for_status()
    metadata = {
        "principal_id": principal_id,
        "workspace_id": str(response.json()["workspace_id"]),
        "database_path": str(database_path),
    }
    write_metadata(session_path, metadata)
    return metadata


def build_process_env(
    *, role: Literal["api", "worker"], metadata: dict[str, str], database_path: Path,
    object_root: Path, provider: str, model: str | None, base_url: str | None = None,
) -> dict[str, str]:
    env = {
        **os.environ,
        "GLINT_ENVIRONMENT": "development",
        "GLINT_SERVICE_ROLE": role,
        "GLINT_DATABASE_URL": f"sqlite:///{database_path}",
        "GLINT_OBJECT_STORE_BACKEND": "filesystem",
        "GLINT_OBJECT_STORE_ROOT": str(object_root),
        "GLINT_CREATE_SCHEMA_ON_STARTUP": "false",
        "GLINT_ALLOWED_ORIGINS": json.dumps(["tauri://localhost"]),
        "POKIEQUANT_AGENT_PROVIDER": provider,
        "POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK": "false",
    }
    if role == "worker":
        env.update(
            {
                "GLINT_WORKSPACE_ID": metadata["workspace_id"],
                "GLINT_WORKER_POLL_INTERVAL_SECONDS": "1.0",
                "GLINT_WORKER_MODE": "dev",
                "GLINT_WORKER_DOMAIN_ADAPTER": (
                    "services.worker.app.repositories.sqlalchemy_adapter:create_adapter"
                ),
                "GLINT_WORKER_OBJECT_STORE": (
                    "services.api.app.core.object_store:get_object_store"
                ),
            }
        )
    if model is None:
        env.pop("POKIEQUANT_AGENT_MODEL", None)
    else:
        env["POKIEQUANT_AGENT_MODEL"] = model
    if base_url is None:
        env.pop("POKIEQUANT_AGENT_BASE_URL", None)
    else:
        env["POKIEQUANT_AGENT_BASE_URL"] = base_url
    return env


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def api_command(port: int) -> list[str]:
    if FROZEN_RUNTIME:
        return [sys.executable, "--child-role", "api", "--api-port", str(port)]
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "services.api.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]


def worker_command() -> list[str]:
    if FROZEN_RUNTIME:
        return [sys.executable, "--child-role", "worker"]
    return [
        sys.executable,
        "-m",
        "services.worker.app.main",
        "poll",
        "--kind",
        "quant-agent",
        "--interval-seconds",
        "1.0",
    ]


def start_child(command: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        command, cwd=REPO_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_health(
    api_url: str,
    timeout_seconds: float = 20.0,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    import httpx

    deadline = time.monotonic() + timeout_seconds
    with httpx.Client(trust_env=False, timeout=1.0) as client:
        while time.monotonic() < deadline:
            if should_stop is not None and should_stop():
                return False
            with contextlib.suppress(httpx.HTTPError):
                if client.get(f"{api_url}/healthz").status_code == 200:
                    return True
            time.sleep(0.2)
    if should_stop is not None and should_stop():
        return False
    raise RuntimeError("API did not become healthy.")


def terminate_children(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait(timeout=5)


def run_child(role: Literal["api", "worker"], api_port: int | None) -> int:
    if role == "api":
        if api_port is None or not 1 <= api_port <= 65535:
            raise ValueError("The bundled API child requires a valid loopback port.")
        import uvicorn

        from services.api.app.main import app

        uvicorn.run(app, host="127.0.0.1", port=api_port, log_level="warning")
        return 0
    from services.worker.app.main import main as worker_main

    return worker_main(
        ["poll", "--kind", "quant-agent", "--interval-seconds", "1.0"]
    )


def run(
    *,
    provider: str,
    model: str | None,
    runtime_dir: Path,
    base_url: str | None = None,
) -> int:
    require_provider_key(provider)
    metadata = bootstrap_metadata(
        runtime_dir=runtime_dir,
        provider=provider,
        model=model,
        base_url=base_url,
    )
    database_path, object_root, _ = runtime_paths(runtime_dir)
    port = free_loopback_port()
    api_url = f"http://127.0.0.1:{port}"
    processes: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous_term = signal.signal(signal.SIGTERM, stop)
    previous_int = signal.signal(signal.SIGINT, stop)
    try:
        api_env = build_process_env(
            role="api",
            metadata=metadata,
            database_path=database_path,
            object_root=object_root,
            provider=provider,
            model=model,
            base_url=base_url,
        )
        processes.append(start_child(api_command(port), api_env))
        if not wait_for_health(api_url, should_stop=lambda: stopping):
            return 0
        worker_env = build_process_env(
            role="worker",
            metadata=metadata,
            database_path=database_path,
            object_root=object_root,
            provider=provider,
            model=model,
            base_url=base_url,
        )
        processes.append(start_child(worker_command(), worker_env))
        if stopping:
            return 0
        ready = {
            "api_url": api_url,
            "workspace_id": metadata["workspace_id"],
            "principal_id": metadata["principal_id"],
            "provider": provider,
            "model": model,
            "base_url": base_url,
        }
        print(READY_PREFIX + json.dumps(ready, separators=(",", ":")), flush=True)
        while not stopping:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A local runtime child exited unexpectedly.")
            time.sleep(0.25)
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        terminate_children(processes)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.child_role is not None:
            return run_child(args.child_role, args.api_port)
        provider = str(args.provider)
        model = selected_model(provider, args.model)
        base_url = selected_base_url(provider, args.base_url)
        return run(
            provider=provider,
            model=model,
            runtime_dir=resolve_runtime_dir(args.runtime_dir),
            base_url=base_url,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
