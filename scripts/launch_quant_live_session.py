#!/usr/bin/env python3
"""Launch a prepared local-live Qurio session.

Reads local session metadata, including its development bearer identity, from
the supplied owner-only JSON file, then starts the FastAPI server and Mac Vite
app. In normal mode it also starts a DeepSeek quant-agent worker. In
``--readonly-reopen`` mode it reopens a completed retained session for evidence
review only: no worker is started, no model is invoked, and the SQLite database
is opened in genuine read-only mode.

Credentials are read only from the process environment. The launcher fails
closed when required credentials are missing or inconsistent. Child processes
are cleanly terminated on Ctrl-C or child failure.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DIR = REPO_ROOT / ".run"
RUNTIME_DIR = (
    Path(os.environ.get("POKIEQUANT_LIVE_SESSION_DIR", str(DEFAULT_RUNTIME_DIR)))
    .expanduser()
    .resolve()
)
DEFAULT_SESSION_PATH = RUNTIME_DIR / "pokiequant-live-session.json"
DEFAULT_READONLY_SESSION_PATH = (
    RUNTIME_DIR / "v1-kraken-deepseek-20260724-183209" / "pokiequant-live-session.json"
)
PACKAGED_MAC_ORIGIN = "tauri://localhost"

# Process group termination grace period before force-kill.
_TERMINATE_TIMEOUT_SECONDS = 5.0


def _deepseek_key() -> str | None:
    return os.environ.get("POKIEQUANT_AGENT_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")


def _mac_access_token() -> str | None:
    return os.environ.get("VITE_GLINT_ACCESS_TOKEN")


def load_session(session_path: Path, *, readonly_reopen: bool = False) -> dict[str, str]:
    """Load and validate non-secret session metadata."""
    if not session_path.exists():
        if readonly_reopen:
            raise FileNotFoundError(
                f"Retained read-only session file not found: {session_path.resolve()}. "
                "Pass --session PATH for another completed retained session; no fixture will be created."
            )
        raise FileNotFoundError(
            f"Session file not found: {session_path.resolve()}. "
            "Run scripts/prepare_quant_live_session.py first."
        )
    raw = json.loads(session_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Session file must contain a JSON object.")
    allowed = {
        "principal_id",
        "workspace_id",
        "run_id",
        "dataset_id",
        "database_path",
        "model",
    }
    extra = set(raw) - allowed
    if extra:
        raise ValueError(f"Session file contains disallowed keys: {sorted(extra)}")
    missing = allowed - set(raw)
    if missing:
        raise ValueError(f"Session file is missing required keys: {sorted(missing)}")
    return {key: str(value) for key, value in raw.items()}


def validate_environment(session: dict[str, str], *, readonly_reopen: bool = False) -> None:
    """Fail closed when credentials are missing or inconsistent.

    Read-only reopen requires only the Mac access token, which must exactly
    match the session principal. Normal execution also requires a DeepSeek key.
    """
    access_token = _mac_access_token()
    if not access_token:
        raise SystemExit(
            "Error: VITE_GLINT_ACCESS_TOKEN must be set for the Mac dev session. "
            "Use the principal_id printed by prepare_quant_live_session.py."
        )
    expected_principal = session.get("principal_id")
    if expected_principal and access_token != expected_principal:
        raise SystemExit(
            "Error: VITE_GLINT_ACCESS_TOKEN does not match the session principal_id. "
            "Run prepare_quant_live_session.py again or update the environment variable."
        )
    if not readonly_reopen and not _deepseek_key():
        raise SystemExit("Error: DEEPSEEK_API_KEY or POKIEQUANT_AGENT_API_KEY must be set.")


def find_free_port(host: str = "127.0.0.1", start: int = 8123, attempts: int = 100) -> int:
    """Return the first available TCP port at or after ``start``."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free TCP port found on {host} in range {start}-{start + attempts}")


def _resolve_database_path(database_path: str, session_path: Path) -> Path:
    """Resolve the database path, supporting paths relative to the session file."""
    resolved = Path(database_path).expanduser()
    if resolved.is_absolute():
        return resolved.resolve()
    return (session_path.parent / resolved).resolve()


def _sqlite_url(database_path: str | Path) -> str:
    return f"sqlite:///{Path(database_path).resolve()}"


def _sqlite_ro_url(database_path: str | Path) -> str:
    """Return a genuine read-only SQLAlchemy SQLite URI.

    SQLAlchemy passes the URI form through to sqlite3 only when the URL itself
    uses the ``file:`` scheme and includes ``uri=true``. This prevents the
    read-only API from mutating the retained database.
    """
    path = Path(database_path).resolve()
    return f"sqlite:///file:{path}?mode=ro&uri=true"


def _resolve_object_store_root(session_path: Path) -> Path:
    """Return the object-store root for this session.

    Default sessions placed directly in the runtime root continue to use the
    shared ``pokiequant-live-objects`` directory. Retained sessions in their own
    directory (e.g. ``.run/v1-.../pokiequant-live-session.json``) use the
    directory that contains the session file, so object paths stay paired with
    the retained database.
    """
    session_dir = session_path.resolve().parent
    if session_dir != RUNTIME_DIR.resolve():
        return session_dir / "pokiequant-live-objects"
    return RUNTIME_DIR / "pokiequant-live-objects"


def _run_identity_from_state(
    state: dict[str, Any], run_id: str, workspace_id: str
) -> dict[str, Any]:
    """Return the unique repository-state run matching ``run_id``.

    Raises ``ValueError`` if the run is missing or ambiguous.
    """
    runs = [run for run in state.get("runs", []) if run.get("id") == run_id]
    if len(runs) != 1:
        raise ValueError(
            f"Repository state must contain exactly one run for {run_id}, found {len(runs)}"
        )
    run = runs[0]
    if run.get("workspace_id") != workspace_id:
        raise ValueError("Run workspace_id does not match the session workspace_id.")
    return run


def _market_dataset_from_state(state: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    """Return the unique market-v2 dataset matching ``dataset_id``.

    Raises ``ValueError`` if the dataset is missing or ambiguous.
    """
    datasets = [
        dataset
        for dataset in state.get("market_datasets_v2", [])
        if dataset.get("id") == dataset_id or dataset.get("dataset_id") == dataset_id
    ]
    if len(datasets) != 1:
        raise ValueError(
            f"Repository state must contain exactly one market-v2 dataset for {dataset_id}, "
            f"found {len(datasets)}"
        )
    return datasets[0]


def preflight_readonly_session(session_path: Path, session: dict[str, str]) -> None:
    """Validate that a read-only reopen target is complete and terminal.

    This check uses only the standard-library ``sqlite3`` module so it never
    initializes SQLAlchemy engines or the QuantStore. It fails closed before any
    child process starts.
    """
    db_path = _resolve_database_path(session["database_path"], session_path)
    if not db_path.exists():
        raise SystemExit(f"Error: retained database not found: {db_path}")

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise SystemExit(f"Error: cannot open retained database read-only: {exc}") from exc

    with contextlib.closing(conn):
        cursor = conn.cursor()
        cursor.execute(
            "SELECT state_json FROM quant_repository_states WHERE workspace_id = ?",
            (session["workspace_id"],),
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise SystemExit(
                f"Error: expected exactly one repository state for workspace "
                f"{session['workspace_id']}, found {len(rows)}"
            )

        try:
            state = json.loads(rows[0][0])
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Error: repository state is not valid JSON: {exc}") from exc
        if not isinstance(state, dict):
            raise SystemExit("Error: repository state must be a JSON object.")

        try:
            run = _run_identity_from_state(state, session["run_id"], session["workspace_id"])
            if run.get("state") != "completed":
                raise SystemExit(
                    f"Error: run {session['run_id']} is not completed (state={run.get('state')!r})."
                )

            required_identities = {
                "dataset_id": session["dataset_id"],
                "model": session["model"],
                "provider": "deepseek",
            }
            mismatches = [
                f"{key}: expected {expected!r}, found {run.get(key)!r}"
                for key, expected in required_identities.items()
                if run.get(key) != expected
            ]
            if mismatches:
                raise SystemExit(
                    "Error: run identity mismatch in repository state:\n  "
                    + "\n  ".join(mismatches)
                )

            _market_dataset_from_state(state, session["dataset_id"])
        except ValueError as exc:
            raise SystemExit(f"Error: {exc}") from exc


def build_api_env(
    session: dict[str, str],
    api_port: int,
    mac_origin: str,
    *,
    session_path: Path | None = None,
    readonly_reopen: bool = False,
) -> dict[str, str]:
    """Return the environment for the FastAPI process."""
    if session_path is None:
        session_path = DEFAULT_SESSION_PATH
    db_path = _resolve_database_path(session["database_path"], session_path)
    env: dict[str, str] = {
        **os.environ,
        "GLINT_ENVIRONMENT": "development",
        "GLINT_SERVICE_ROLE": "api",
        "GLINT_DATABASE_URL": (
            _sqlite_ro_url(db_path) if readonly_reopen else _sqlite_url(db_path)
        ),
        "GLINT_OBJECT_STORE_BACKEND": "filesystem",
        "GLINT_OBJECT_STORE_ROOT": str(_resolve_object_store_root(session_path).resolve()),
        "GLINT_CREATE_SCHEMA_ON_STARTUP": "false" if readonly_reopen else "true",
        "GLINT_ALLOWED_ORIGINS": json.dumps([mac_origin, PACKAGED_MAC_ORIGIN]),
        "POKIEQUANT_AGENT_PROVIDER": "deepseek",
        "POKIEQUANT_AGENT_MODEL": session["model"],
        "POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK": "false",
    }
    return env


def build_worker_env(
    session: dict[str, str], interval_seconds: float, *, session_path: Path | None = None
) -> dict[str, str]:
    """Return the environment for the DeepSeek quant-agent worker."""
    if session_path is None:
        session_path = DEFAULT_SESSION_PATH
    return {
        **os.environ,
        "GLINT_ENVIRONMENT": "development",
        "GLINT_SERVICE_ROLE": "worker",
        "GLINT_DATABASE_URL": _sqlite_url(
            _resolve_database_path(session["database_path"], session_path)
        ),
        "GLINT_OBJECT_STORE_BACKEND": "filesystem",
        "GLINT_OBJECT_STORE_ROOT": str(_resolve_object_store_root(session_path).resolve()),
        "GLINT_WORKSPACE_ID": session["workspace_id"],
        "GLINT_WORKER_MODE": "dev",
        "GLINT_WORKER_POLL_INTERVAL_SECONDS": str(interval_seconds),
        "POKIEQUANT_AGENT_PROVIDER": "deepseek",
        "POKIEQUANT_AGENT_MODEL": session["model"],
        "POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK": "false",
        # DeepSeek key is intentionally inherited from os.environ only.
    }


def build_mac_env(session: dict[str, str], api_port: int) -> dict[str, str]:
    """Return the environment for the Mac Vite dev server."""
    return {
        **os.environ,
        "VITE_GLINT_API_URL": f"http://127.0.0.1:{api_port}",
        "VITE_GLINT_WORKSPACE_ID": session["workspace_id"],
        # Access token is inherited from os.environ only.
    }


def build_api_command(api_port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "services.api.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(api_port),
        "--log-level",
        "info",
    ]


def build_worker_command(interval_seconds: float) -> list[str]:
    return [
        sys.executable,
        "-m",
        "services.worker.app.main",
        "poll",
        "--kind",
        "quant-agent",
        "--interval-seconds",
        str(interval_seconds),
    ]


def build_mac_command(mac_port: int) -> list[str]:
    return [
        "pnpm",
        "--filter",
        "@glint/mac",
        "exec",
        "vite",
        "--host",
        "127.0.0.1",
        "--port",
        str(mac_port),
        "--strictPort",
    ]


def wait_for_api_health(base_url: str, timeout_seconds: float = 30.0) -> None:
    """Poll the API health endpoint until it responds."""
    import httpx

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    # Loopback health must not inherit corporate/system HTTP proxy settings.
    with httpx.Client(trust_env=False, timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(f"{base_url}/healthz")
                if response.status_code == 200:
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"API did not become healthy within {timeout_seconds}s") from last_error


def start_process(
    command: list[str], env: dict[str, str], cwd: Path, label: str
) -> subprocess.Popen[str]:
    """Start a child process in its own process group for clean termination."""
    print(f"Starting {label}: {' '.join(command)}")
    return subprocess.Popen(
        command,
        env=env,
        cwd=cwd,
        text=True,
        start_new_session=True,
    )


def _terminate_process_group(proc: subprocess.Popen[str]) -> None:
    """Send SIGTERM to a process group, then SIGKILL if necessary."""
    # Do not re-terminate a process that has already been reaped.
    if proc.returncode is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pgid, signal.SIGKILL)
        proc.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)


def terminate_processes(processes: list[subprocess.Popen[str]]) -> None:
    """Cleanly terminate all tracked child processes."""
    for proc in processes:
        _terminate_process_group(proc)


def run(
    session_path: Path,
    api_port: int | None,
    mac_port: int | None,
    worker_delay_seconds: float,
    worker_interval_seconds: float,
    *,
    readonly_reopen: bool = False,
) -> int:
    session = load_session(session_path, readonly_reopen=readonly_reopen)
    validate_environment(session, readonly_reopen=readonly_reopen)

    if readonly_reopen:
        preflight_readonly_session(session_path, session)

    api_port = api_port or find_free_port(start=8123)
    mac_port = mac_port or find_free_port(start=5173)
    mac_origin = f"http://127.0.0.1:{mac_port}"

    api_env = build_api_env(
        session, api_port, mac_origin, session_path=session_path, readonly_reopen=readonly_reopen
    )
    mac_env = build_mac_env(session, api_port)

    processes: list[subprocess.Popen[str]] = []

    def _shutdown(_signum: int, _frame: Any) -> None:
        # Let the finally block clean up already-started children; do not call
        # sys.exit here so that normal exception unwinding can run.
        raise KeyboardInterrupt

    previous_sigint = signal.signal(signal.SIGINT, _shutdown)
    previous_sigterm = signal.signal(signal.SIGTERM, _shutdown)

    try:
        api_proc = start_process(build_api_command(api_port), api_env, REPO_ROOT, "API")
        processes.append(api_proc)
        wait_for_api_health(f"http://127.0.0.1:{api_port}")

        mac_proc = start_process(build_mac_command(mac_port), mac_env, REPO_ROOT, "Mac UI")
        processes.append(mac_proc)

        if readonly_reopen:
            print("Read-only evidence reopen running:")
            print(f"  API:     http://127.0.0.1:{api_port}")
            print(f"  Mac UI:  {mac_origin}")
            print("Press Ctrl-C to stop.")
        else:
            if worker_delay_seconds > 0:
                print(
                    f"Waiting {worker_delay_seconds}s before starting worker so the UI can load..."
                )
                time.sleep(worker_delay_seconds)

            worker_env = build_worker_env(
                session, worker_interval_seconds, session_path=session_path
            )
            worker_proc = start_process(
                build_worker_command(worker_interval_seconds), worker_env, REPO_ROOT, "worker"
            )
            processes.append(worker_proc)

            print("Local-live session running:")
            print(f"  API:     http://127.0.0.1:{api_port}")
            print(f"  Mac UI:  {mac_origin}")
            print(f"  worker:  DeepSeek quant-agent (workspace {session['workspace_id']})")
            print("Press Ctrl-C to stop.")

        while True:
            for proc in processes:
                ret = proc.poll()
                if ret is not None:
                    print(f"Process exited with code {ret}; stopping remaining children.")
                    return ret
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nShutting down local-live session...")
        return 0
    finally:
        with contextlib.suppress(KeyboardInterrupt):
            terminate_processes(processes)
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help=(
            "Path to the session JSON file. Defaults to the prepared live session in normal mode "
            "and the retained V1 Kraken/DeepSeek session in --readonly-reopen mode."
        ),
    )
    parser.add_argument(
        "--readonly-reopen",
        action="store_true",
        help=(
            "Reopen a completed retained session for read-only evidence review. "
            "Requires VITE_GLINT_ACCESS_TOKEN but no DeepSeek key. Only API and Mac UI are started."
        ),
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=None,
        help="FastAPI port (default: first free port at or after 8123).",
    )
    parser.add_argument(
        "--mac-port",
        type=int,
        default=None,
        help="Mac Vite dev-server port (default: first free port at or after 5173).",
    )
    parser.add_argument(
        "--worker-delay-seconds",
        type=float,
        default=5.0,
        help="Delay before starting the worker so the UI can load first (normal mode only).",
    )
    parser.add_argument(
        "--worker-interval-seconds",
        type=float,
        default=1.0,
        help="Worker poll interval in seconds (normal mode only).",
    )
    args = parser.parse_args(argv)
    session_path = args.session or (
        DEFAULT_READONLY_SESSION_PATH if args.readonly_reopen else DEFAULT_SESSION_PATH
    )

    try:
        return run(
            session_path=session_path,
            api_port=args.api_port,
            mac_port=args.mac_port,
            worker_delay_seconds=args.worker_delay_seconds,
            worker_interval_seconds=args.worker_interval_seconds,
            readonly_reopen=args.readonly_reopen,
        )
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
