from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest

import scripts.launch_quant_live_session as launcher
import scripts.prepare_quant_live_session as bootstrap
from services.worker.app.quant_agent.provider import (
    MockQuantAgentProvider,
    OpenAICompatibleProvider,
    load_quant_agent_provider,
)


@pytest.fixture
def valid_session(tmp_path: Path) -> dict[str, str]:
    return {
        "principal_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "run_id": str(uuid4()),
        "dataset_id": str(uuid4()),
        "database_path": str(tmp_path / "pokiequant-live.db"),
        "model": "deepseek-v4-flash",
    }


@pytest.fixture
def session_file(tmp_path: Path, valid_session: dict[str, str]) -> Path:
    path = tmp_path / "pokiequant-live-session.json"
    path.write_text(json.dumps(valid_session))
    return path


def _write_repository_state(
    db_path: Path,
    session: dict[str, str],
    *,
    run_state: str = "completed",
    dataset_key: str = "dataset_id",
) -> None:
    """Create a minimal SQLite DB with a repository state matching ``session``.

    This lets preflight tests exercise the actual repository-state query shape
    without depending on any retained production database.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quant_repository_states (
                workspace_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL
            )
            """
        )
        state = {
            "runs": [
                {
                    "id": session["run_id"],
                    "workspace_id": session["workspace_id"],
                    "dataset_id": session["dataset_id"],
                    "model": session["model"],
                    "provider": "deepseek",
                    "state": run_state,
                }
            ],
            "market_datasets_v2": [
                {dataset_key: session["dataset_id"], "symbol": "BTCUSD", "interval": "4h"}
            ],
        }
        conn.execute(
            "INSERT OR REPLACE INTO quant_repository_states "
            "(workspace_id, state_json) VALUES (?, ?)",
            (session["workspace_id"], json.dumps(state)),
        )
    conn.close()


class TestBootstrapSessionMetadata:
    def test_live_bootstrap_requests_a_multi_year_binance_window(self) -> None:
        assert bootstrap.LIVE_BTCUSDT_BAR_LIMIT == 1000

    def test_validate_session_metadata_accepts_allowed_keys(
        self, valid_session: dict[str, str]
    ) -> None:
        sanitized = bootstrap.validate_session_metadata(valid_session)
        assert sanitized == valid_session

    def test_validate_session_metadata_rejects_secret_keys(
        self, valid_session: dict[str, str]
    ) -> None:
        with pytest.raises(ValueError, match="disallowed keys"):
            bootstrap.validate_session_metadata({**valid_session, "api_key": "secret"})

    def test_validate_session_metadata_rejects_missing_keys(
        self, valid_session: dict[str, str]
    ) -> None:
        incomplete = {k: v for k, v in valid_session.items() if k != "model"}
        with pytest.raises(ValueError, match="missing required keys"):
            bootstrap.validate_session_metadata(incomplete)

    def test_model_reads_environment_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POKIEQUANT_AGENT_MODEL", "custom-model")
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        assert bootstrap.resolve_model() == "custom-model"

    def test_model_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POKIEQUANT_AGENT_MODEL", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        assert bootstrap.resolve_model() == "deepseek-v4-flash"


class TestLauncherSessionLoading:
    def test_load_session_reads_valid_file(self, session_file: Path) -> None:
        loaded = launcher.load_session(session_file)
        assert set(loaded) == {
            "principal_id",
            "workspace_id",
            "run_id",
            "dataset_id",
            "database_path",
            "model",
        }

    def test_load_session_rejects_secret_keys(self, session_file: Path) -> None:
        raw = json.loads(session_file.read_text())
        raw["api_key"] = "secret"
        session_file.write_text(json.dumps(raw))
        with pytest.raises(ValueError, match="disallowed keys"):
            launcher.load_session(session_file)

    def test_load_session_requires_json_object(self, session_file: Path) -> None:
        session_file.write_text(json.dumps(["not", "an", "object"]))
        with pytest.raises(ValueError, match="JSON object"):
            launcher.load_session(session_file)

    def test_readonly_missing_session_fails_without_creating_a_fixture(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        missing = tmp_path / "retained" / "pokiequant-live-session.json"
        start = mock.Mock()
        monkeypatch.setattr(launcher, "start_process", start)

        assert launcher.main(["--readonly-reopen", "--session", str(missing)]) == 1
        assert not missing.exists()
        assert not missing.parent.exists()
        start.assert_not_called()


class TestLauncherArgumentParsing:
    def test_readonly_main_defaults_to_retained_v1_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = mock.Mock(return_value=0)
        monkeypatch.setattr(launcher, "run", run)

        assert launcher.main(["--readonly-reopen"]) == 0

        assert run.call_args.kwargs["session_path"] == launcher.DEFAULT_READONLY_SESSION_PATH
        assert run.call_args.kwargs["readonly_reopen"] is True

    def test_normal_main_preserves_prepared_session_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = mock.Mock(return_value=0)
        monkeypatch.setattr(launcher, "run", run)

        assert launcher.main([]) == 0

        assert run.call_args.kwargs["session_path"] == launcher.DEFAULT_SESSION_PATH
        assert run.call_args.kwargs["readonly_reopen"] is False

    def test_explicit_session_overrides_readonly_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        run = mock.Mock(return_value=0)
        monkeypatch.setattr(launcher, "run", run)
        explicit = tmp_path / "another-retained-session.json"

        assert launcher.main(["--readonly-reopen", "--session", str(explicit)]) == 0

        assert run.call_args.kwargs["session_path"] == explicit


class TestLauncherEnvironmentValidation:
    def test_validate_environment_fails_closed_without_deepseek_key(
        self, monkeypatch: pytest.MonkeyPatch, valid_session: dict[str, str]
    ) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("POKIEQUANT_AGENT_API_KEY", raising=False)
        monkeypatch.setenv("VITE_GLINT_ACCESS_TOKEN", valid_session["principal_id"])
        with pytest.raises(SystemExit, match="DEEPSEEK_API_KEY"):
            launcher.validate_environment(valid_session, readonly_reopen=False)

    def test_validate_environment_allows_missing_deepseek_key_in_readonly(
        self, monkeypatch: pytest.MonkeyPatch, valid_session: dict[str, str]
    ) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("POKIEQUANT_AGENT_API_KEY", raising=False)
        monkeypatch.setenv("VITE_GLINT_ACCESS_TOKEN", valid_session["principal_id"])
        # Should not raise.
        launcher.validate_environment(valid_session, readonly_reopen=True)

    def test_missing_key_starts_no_child_process(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_file: Path,
        valid_session: dict[str, str],
    ) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("POKIEQUANT_AGENT_API_KEY", raising=False)
        monkeypatch.setenv("VITE_GLINT_ACCESS_TOKEN", valid_session["principal_id"])
        start = mock.Mock()
        monkeypatch.setattr(launcher, "start_process", start)

        with pytest.raises(SystemExit, match="DEEPSEEK_API_KEY"):
            launcher.run(session_file, 8123, 5173, 0, 1, readonly_reopen=False)

        start.assert_not_called()

    def test_missing_access_token_starts_no_child_process_in_readonly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_file: Path,
        valid_session: dict[str, str],
    ) -> None:
        monkeypatch.delenv("VITE_GLINT_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("POKIEQUANT_AGENT_API_KEY", raising=False)
        _write_repository_state(Path(valid_session["database_path"]), valid_session)
        start = mock.Mock()
        monkeypatch.setattr(launcher, "start_process", start)

        with pytest.raises(SystemExit, match="VITE_GLINT_ACCESS_TOKEN"):
            launcher.run(session_file, 8123, 5173, 0, 1, readonly_reopen=True)

        start.assert_not_called()

    def test_access_token_mismatch_starts_no_child_process_in_readonly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_file: Path,
        valid_session: dict[str, str],
    ) -> None:
        monkeypatch.setenv("VITE_GLINT_ACCESS_TOKEN", str(uuid4()))
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("POKIEQUANT_AGENT_API_KEY", raising=False)
        _write_repository_state(Path(valid_session["database_path"]), valid_session)
        start = mock.Mock()
        monkeypatch.setattr(launcher, "start_process", start)

        with pytest.raises(SystemExit, match="does not match"):
            launcher.run(session_file, 8123, 5173, 0, 1, readonly_reopen=True)

        start.assert_not_called()

    def test_validate_environment_fails_closed_without_access_token(
        self, monkeypatch: pytest.MonkeyPatch, valid_session: dict[str, str]
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        monkeypatch.delenv("VITE_GLINT_ACCESS_TOKEN", raising=False)
        with pytest.raises(SystemExit, match="VITE_GLINT_ACCESS_TOKEN"):
            launcher.validate_environment(valid_session, readonly_reopen=False)

    def test_validate_environment_fails_on_token_mismatch(
        self, monkeypatch: pytest.MonkeyPatch, valid_session: dict[str, str]
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        monkeypatch.setenv("VITE_GLINT_ACCESS_TOKEN", str(uuid4()))
        with pytest.raises(SystemExit, match="does not match"):
            launcher.validate_environment(valid_session, readonly_reopen=False)


class TestLauncherCommandConstruction:
    def test_build_api_command(self) -> None:
        command = launcher.build_api_command(8123)
        assert command == [
            sys.executable,
            "-m",
            "uvicorn",
            "services.api.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8123",
            "--log-level",
            "info",
        ]

    def test_build_worker_command(self) -> None:
        command = launcher.build_worker_command(0.5)
        assert command[:4] == [
            sys.executable,
            "-m",
            "services.worker.app.main",
            "poll",
        ]
        assert command[command.index("--kind") + 1] == "quant-agent"
        assert command[command.index("--interval-seconds") + 1] == "0.5"

    def test_build_mac_command_uses_strict_port(self) -> None:
        command = launcher.build_mac_command(5173)
        assert command == [
            "pnpm",
            "--filter",
            "@glint/mac",
            "exec",
            "vite",
            "--host",
            "127.0.0.1",
            "--port",
            "5173",
            "--strictPort",
        ]


class TestLauncherEnvironmentConstruction:
    def test_build_api_env_sets_database_and_cors(
        self, monkeypatch: pytest.MonkeyPatch, valid_session: dict[str, str]
    ) -> None:
        monkeypatch.setenv("GLINT_ALLOWED_ORIGINS", "")  # ensure overwritten
        env = launcher.build_api_env(
            valid_session,
            api_port=8123,
            mac_origin="http://127.0.0.1:5173",
            session_path=Path(valid_session["database_path"]),
            readonly_reopen=False,
        )
        assert env["GLINT_ENVIRONMENT"] == "development"
        assert env["GLINT_SERVICE_ROLE"] == "api"
        assert env["GLINT_CREATE_SCHEMA_ON_STARTUP"] == "true"
        assert env["GLINT_ALLOWED_ORIGINS"] == json.dumps(
            ["http://127.0.0.1:5173", "tauri://localhost"]
        )
        assert env["POKIEQUANT_AGENT_PROVIDER"] == "deepseek"
        assert env["POKIEQUANT_AGENT_MODEL"] == valid_session["model"]
        assert env["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] == "false"
        assert "sqlite" in env["GLINT_DATABASE_URL"]
        assert valid_session["database_path"] in env["GLINT_DATABASE_URL"]

    def test_build_api_env_uses_read_only_url_and_disables_schema_creation(
        self, valid_session: dict[str, str]
    ) -> None:
        env = launcher.build_api_env(
            valid_session,
            api_port=8123,
            mac_origin="http://127.0.0.1:5173",
            session_path=Path(valid_session["database_path"]),
            readonly_reopen=True,
        )
        assert env["GLINT_CREATE_SCHEMA_ON_STARTUP"] == "false"
        assert "mode=ro" in env["GLINT_DATABASE_URL"]
        assert "uri=true" in env["GLINT_DATABASE_URL"]
        assert valid_session["database_path"] in env["GLINT_DATABASE_URL"]

    def test_build_worker_env_uses_deepseek_provider_and_session_model(
        self, valid_session: dict[str, str]
    ) -> None:
        env = launcher.build_worker_env(
            valid_session, interval_seconds=1.5, session_path=Path(valid_session["database_path"])
        )
        assert env["GLINT_ENVIRONMENT"] == "development"
        assert env["GLINT_SERVICE_ROLE"] == "worker"
        assert env["GLINT_WORKSPACE_ID"] == valid_session["workspace_id"]
        assert env["POKIEQUANT_AGENT_PROVIDER"] == "deepseek"
        assert env["POKIEQUANT_AGENT_MODEL"] == valid_session["model"]
        assert env["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] == "false"
        assert env["GLINT_WORKER_POLL_INTERVAL_SECONDS"] == "1.5"

    def test_build_mac_env_uses_api_port_and_workspace(self, valid_session: dict[str, str]) -> None:
        env = launcher.build_mac_env(valid_session, api_port=8123)
        assert env["VITE_GLINT_API_URL"] == "http://127.0.0.1:8123"
        assert env["VITE_GLINT_WORKSPACE_ID"] == valid_session["workspace_id"]

    def test_build_api_env_legacy_three_positional_args_uses_default_session_path(
        self, monkeypatch: pytest.MonkeyPatch, valid_session: dict[str, str]
    ) -> None:
        monkeypatch.setenv("GLINT_ALLOWED_ORIGINS", "")
        env = launcher.build_api_env(valid_session, 8123, "http://127.0.0.1:5173")
        assert env["GLINT_ALLOWED_ORIGINS"] == json.dumps(
            ["http://127.0.0.1:5173", "tauri://localhost"]
        )
        assert env["GLINT_CREATE_SCHEMA_ON_STARTUP"] == "true"
        assert "sqlite" in env["GLINT_DATABASE_URL"]
        assert valid_session["database_path"] in env["GLINT_DATABASE_URL"]

    def test_build_worker_env_legacy_two_positional_args_uses_default_session_path(
        self, valid_session: dict[str, str]
    ) -> None:
        env = launcher.build_worker_env(valid_session, 1.5)
        assert env["GLINT_WORKER_POLL_INTERVAL_SECONDS"] == "1.5"
        assert "sqlite" in env["GLINT_DATABASE_URL"]
        assert valid_session["database_path"] in env["GLINT_DATABASE_URL"]

    def test_validate_environment_defaults_to_normal_mode(
        self, monkeypatch: pytest.MonkeyPatch, valid_session: dict[str, str]
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        monkeypatch.setenv("VITE_GLINT_ACCESS_TOKEN", valid_session["principal_id"])
        # Should not raise when called without readonly_reopen keyword.
        launcher.validate_environment(valid_session)

    def test_api_and_worker_env_load_the_same_real_provider(
        self, monkeypatch: pytest.MonkeyPatch, valid_session: dict[str, str]
    ) -> None:
        monkeypatch.setenv("POKIEQUANT_AGENT_API_KEY", "test-placeholder")
        api_env = launcher.build_api_env(
            valid_session,
            api_port=8123,
            mac_origin="http://127.0.0.1:5173",
            session_path=Path(valid_session["database_path"]),
            readonly_reopen=False,
        )
        worker_env = launcher.build_worker_env(
            valid_session, interval_seconds=1.0, session_path=Path(valid_session["database_path"])
        )

        for env in (api_env, worker_env):
            with mock.patch.dict(os.environ, env, clear=True):
                provider = load_quant_agent_provider()
            assert isinstance(provider, OpenAICompatibleProvider)
            assert not isinstance(provider, MockQuantAgentProvider)
            assert provider.model_name == valid_session["model"]
            assert env["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] == "false"


class TestLauncherReadOnlyPreflight:
    def test_preflight_accepts_completed_run_with_matching_state(
        self, valid_session: dict[str, str], session_file: Path
    ) -> None:
        _write_repository_state(Path(valid_session["database_path"]), valid_session)
        # Should not raise.
        launcher.preflight_readonly_session(session_file, valid_session)

    def test_preflight_rejects_missing_database(
        self, valid_session: dict[str, str], session_file: Path
    ) -> None:
        with pytest.raises(SystemExit, match="retained database not found"):
            launcher.preflight_readonly_session(session_file, valid_session)

    def test_preflight_rejects_non_terminal_run(
        self, valid_session: dict[str, str], session_file: Path
    ) -> None:
        _write_repository_state(
            Path(valid_session["database_path"]), valid_session, run_state="running"
        )
        with pytest.raises(SystemExit, match="not completed"):
            launcher.preflight_readonly_session(session_file, valid_session)

    def test_preflight_rejects_run_with_mismatched_dataset(
        self, valid_session: dict[str, str], session_file: Path
    ) -> None:
        _write_repository_state(Path(valid_session["database_path"]), valid_session)
        tampered = {**valid_session, "dataset_id": str(uuid4())}
        with pytest.raises(SystemExit, match="dataset_id"):
            launcher.preflight_readonly_session(session_file, tampered)

    def test_preflight_rejects_run_with_mismatched_model(
        self, valid_session: dict[str, str], session_file: Path
    ) -> None:
        _write_repository_state(Path(valid_session["database_path"]), valid_session)
        tampered = {**valid_session, "model": "different-model"}
        with pytest.raises(SystemExit, match="model"):
            launcher.preflight_readonly_session(session_file, tampered)

    def test_preflight_rejects_ambiguous_run_state(
        self, valid_session: dict[str, str], session_file: Path
    ) -> None:
        db_path = Path(valid_session["database_path"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS quant_repository_states ("
                "workspace_id TEXT PRIMARY KEY, state_json TEXT NOT NULL)"
            )
            state = {
                "runs": [
                    {
                        "id": valid_session["run_id"],
                        "workspace_id": valid_session["workspace_id"],
                        "dataset_id": valid_session["dataset_id"],
                        "model": valid_session["model"],
                        "provider": "deepseek",
                        "state": "completed",
                    },
                    {
                        "id": valid_session["run_id"],
                        "workspace_id": valid_session["workspace_id"],
                        "dataset_id": valid_session["dataset_id"],
                        "model": valid_session["model"],
                        "provider": "deepseek",
                        "state": "completed",
                    },
                ],
                "market_datasets_v2": [
                    {
                        "dataset_id": valid_session["dataset_id"],
                        "symbol": "BTCUSD",
                        "interval": "4h",
                    }
                ],
            }
            conn.execute(
                "INSERT OR REPLACE INTO quant_repository_states "
                "(workspace_id, state_json) VALUES (?, ?)",
                (valid_session["workspace_id"], json.dumps(state)),
            )
        conn.close()

        with pytest.raises(SystemExit, match="exactly one run"):
            launcher.preflight_readonly_session(session_file, valid_session)

    def test_read_only_url_rejects_writes(
        self, valid_session: dict[str, str], session_file: Path
    ) -> None:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError

        _write_repository_state(Path(valid_session["database_path"]), valid_session)
        db_path = launcher._resolve_database_path(valid_session["database_path"], session_file)
        engine = create_engine(launcher._sqlite_ro_url(db_path))
        with pytest.raises(OperationalError), engine.connect() as conn:
            conn.execute(text("CREATE TABLE _pq_ro_probe (id INTEGER PRIMARY KEY)"))
            conn.commit()


class TestLauncherReadOnlyStartup:
    @pytest.fixture
    def _no_signal_handlers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keep signal-handler setup from touching pytest's own handlers."""

        def _noop_handler(*args: object) -> None:
            return None

        def _noop_signal(signum: int, handler: Any) -> Any:
            return _noop_handler

        monkeypatch.setattr(signal, "signal", _noop_signal)

    @pytest.fixture
    def _fake_valid_readonly_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        valid_session: dict[str, str],
        session_file: Path,
    ) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("POKIEQUANT_AGENT_API_KEY", raising=False)
        monkeypatch.setenv("VITE_GLINT_ACCESS_TOKEN", valid_session["principal_id"])
        _write_repository_state(Path(valid_session["database_path"]), valid_session)

        def _fixed_port(**_: Any) -> int:
            return 9999

        def _healthy(*_: Any) -> None:
            return None

        monkeypatch.setattr(launcher, "find_free_port", _fixed_port)
        monkeypatch.setattr(launcher, "wait_for_api_health", _healthy)

    def _make_fake_popen(
        self, fail_at_label: str
    ) -> tuple[list[str], Any, list[list[subprocess.Popen[str]]], Any]:
        started_labels: list[str] = []
        terminated_calls: list[list[subprocess.Popen[str]]] = []

        def fake_start_process(
            command: list[str], env: dict[str, str], cwd: Path, label: str
        ) -> subprocess.Popen[str]:
            if label == fail_at_label:
                raise RuntimeError(f"{label} failed")
            proc = mock.Mock(spec=subprocess.Popen)
            proc.pid = 1000 + len(started_labels) + 1
            proc.returncode = None
            proc.poll.return_value = None
            started_labels.append(label)
            return proc

        def fake_terminate_processes(procs: list[subprocess.Popen[str]]) -> None:
            terminated_calls.append(list(procs))

        return started_labels, fake_start_process, terminated_calls, fake_terminate_processes

    def test_readonly_starts_api_and_mac_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_file: Path,
        _no_signal_handlers: None,
        _fake_valid_readonly_run: None,
    ) -> None:
        started, fake_start, terminated, fake_terminate = self._make_fake_popen("never")
        monkeypatch.setattr(launcher, "start_process", fake_start)
        monkeypatch.setattr(launcher, "terminate_processes", fake_terminate)
        monkeypatch.setattr(launcher, "time", mock.Mock())
        launcher.time.sleep.side_effect = RuntimeError("readonly polling started")

        with pytest.raises(RuntimeError, match="readonly polling started"):
            launcher.run(session_file, 8123, 5173, 0.0, 1.0, readonly_reopen=True)

        assert started == ["API", "Mac UI"]
        assert len(terminated) == 1
        assert [p.pid for p in terminated[0]] == [1001, 1002]

    def test_readonly_mac_failure_terminates_api(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_file: Path,
        _no_signal_handlers: None,
        _fake_valid_readonly_run: None,
    ) -> None:
        started, fake_start, terminated, fake_terminate = self._make_fake_popen("Mac UI")
        monkeypatch.setattr(launcher, "start_process", fake_start)
        monkeypatch.setattr(launcher, "terminate_processes", fake_terminate)

        with pytest.raises(RuntimeError, match="Mac UI failed"):
            launcher.run(session_file, 8123, 5173, 0.0, 1.0, readonly_reopen=True)

        assert started == ["API"]
        assert len(terminated) == 1
        assert [p.pid for p in terminated[0]] == [1001]


class TestBootstrapLiveEnvironment:
    def test_config_forces_dedicated_sqlite_and_object_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GLINT_DATABASE_URL", "sqlite:////tmp/unrelated.db")
        monkeypatch.setenv("GLINT_OBJECT_STORE_ROOT", "/tmp/unrelated-objects")
        monkeypatch.setenv("GLINT_ENVIRONMENT", "production")
        monkeypatch.setenv("POKIEQUANT_AGENT_PROVIDER", "mock")
        bootstrap._configure_live_environment()  # pyright: ignore[reportPrivateUsage]
        assert ".run/pokiequant-live.db" in os.environ["GLINT_DATABASE_URL"]
        assert ".run/pokiequant-live-objects" in os.environ["GLINT_OBJECT_STORE_ROOT"]
        assert os.environ["GLINT_ENVIRONMENT"] == "development"
        assert os.environ["GLINT_OBJECT_STORE_BACKEND"] == "filesystem"
        assert os.environ["POKIEQUANT_AGENT_PROVIDER"] == "deepseek"


class TestLauncherStartupCleanup:
    @pytest.fixture
    def _no_signal_handlers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keep signal-handler setup from touching pytest's own handlers."""

        def _noop_handler(*args: object) -> None:
            return None

        def _noop_signal(signum: int, handler: Any) -> Any:
            return _noop_handler

        monkeypatch.setattr(signal, "signal", _noop_signal)

    @pytest.fixture
    def _fake_valid_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        valid_session: dict[str, str],
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        monkeypatch.setenv("VITE_GLINT_ACCESS_TOKEN", valid_session["principal_id"])

        def _fixed_port(**_: Any) -> int:
            return 9999

        def _healthy(*_: Any) -> None:
            return None

        monkeypatch.setattr(launcher, "find_free_port", _fixed_port)
        monkeypatch.setattr(launcher, "wait_for_api_health", _healthy)

    def _make_fake_popen(
        self, fail_at_label: str
    ) -> tuple[list[str], Any, list[list[subprocess.Popen[str]]], Any]:
        started_labels: list[str] = []
        terminated_calls: list[list[subprocess.Popen[str]]] = []

        def fake_start_process(
            command: list[str], env: dict[str, str], cwd: Path, label: str
        ) -> subprocess.Popen[str]:
            if label == fail_at_label:
                raise RuntimeError(f"{label} failed")
            proc = mock.Mock(spec=subprocess.Popen)
            proc.pid = 1000 + len(started_labels) + 1
            proc.returncode = None
            proc.poll.return_value = None
            started_labels.append(label)
            return proc

        def fake_terminate_processes(procs: list[subprocess.Popen[str]]) -> None:
            terminated_calls.append(list(procs))

        return started_labels, fake_start_process, terminated_calls, fake_terminate_processes

    def test_mac_start_failure_terminates_api(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_file: Path,
        _no_signal_handlers: None,
        _fake_valid_run: None,
    ) -> None:
        started, fake_start, terminated, fake_terminate = self._make_fake_popen("Mac UI")
        monkeypatch.setattr(launcher, "start_process", fake_start)
        monkeypatch.setattr(launcher, "terminate_processes", fake_terminate)

        with pytest.raises(RuntimeError, match="Mac UI failed"):
            launcher.run(session_file, 8123, 5173, 0.0, 1.0)

        assert started == ["API"]
        assert len(terminated) == 1
        assert [p.pid for p in terminated[0]] == [1001]

    def test_worker_start_failure_terminates_api_and_mac(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_file: Path,
        _no_signal_handlers: None,
        _fake_valid_run: None,
    ) -> None:
        started, fake_start, terminated, fake_terminate = self._make_fake_popen("worker")
        monkeypatch.setattr(launcher, "start_process", fake_start)
        monkeypatch.setattr(launcher, "terminate_processes", fake_terminate)

        with pytest.raises(RuntimeError, match="worker failed"):
            launcher.run(session_file, 8123, 5173, 0.0, 1.0)

        assert started == ["API", "Mac UI"]
        assert len(terminated) == 1
        assert [p.pid for p in terminated[0]] == [1001, 1002]


class TestLauncherObjectStoreResolution:
    def test_default_session_uses_runtime_object_store(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path)
        session_path = tmp_path / "pokiequant-live-session.json"
        root = launcher._resolve_object_store_root(session_path)
        assert root == tmp_path / "pokiequant-live-objects"

    def test_retained_session_uses_own_object_store(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / "ignored-runtime")
        retained_dir = tmp_path / "v1-retained"
        retained_dir.mkdir()
        session_path = retained_dir / "pokiequant-live-session.json"
        root = launcher._resolve_object_store_root(session_path)
        assert root == retained_dir / "pokiequant-live-objects"
