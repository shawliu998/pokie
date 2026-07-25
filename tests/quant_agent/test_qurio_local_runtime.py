from __future__ import annotations

import json
import signal
import stat
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import scripts.run_qurio_local_runtime as runtime


def test_parse_arguments_and_provider_model_selection(tmp_path: Path) -> None:
    args = runtime.parse_args(
        ["--provider", "deepseek", "--model", "deepseek-v4", "--runtime-dir", str(tmp_path)]
    )
    assert args.provider == "deepseek"
    assert runtime.selected_model(args.provider, args.model) == "deepseek-v4"
    assert runtime.selected_model("mock", "ignored") is None
    with pytest.raises(ValueError, match="--model"):
        runtime.selected_model("deepseek", " ")


def test_deepseek_requires_only_environment_credential_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POKIEQUANT_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="POKIEQUANT_AGENT_API_KEY"):
        runtime.require_deepseek_key("deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-printed")
    runtime.require_deepseek_key("deepseek")


def test_metadata_is_owner_only_and_reused(tmp_path: Path) -> None:
    database_path, _, session_path = runtime.runtime_paths(tmp_path)
    metadata = {
        "principal_id": "principal-1",
        "workspace_id": "workspace-1",
        "database_path": str(database_path),
    }
    runtime.write_metadata(session_path, metadata)
    assert stat.S_IMODE(session_path.stat().st_mode) == 0o600
    assert runtime.read_metadata(session_path, database_path) == metadata
    session_path.write_text(json.dumps({**metadata, "api_key": "secret"}), encoding="utf-8")
    assert runtime.read_metadata(session_path, database_path) is None


def test_bootstrap_creates_one_empty_workspace_and_then_reuses_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created: list[dict[str, object]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"workspace_id": "workspace-1"}

    class Client:
        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, path: str, **kwargs: object) -> Response:
            created.append({"path": path, **kwargs})
            return Response()

    monkeypatch.setattr(runtime, "configure_bootstrap_environment", lambda **_kwargs: None)
    monkeypatch.setattr("fastapi.testclient.TestClient", lambda _app: Client())
    metadata = runtime.bootstrap_metadata(runtime_dir=tmp_path, provider="mock", model=None)
    assert metadata["workspace_id"] == "workspace-1"
    assert [item["path"] for item in created] == ["/v1/workspaces"]
    assert runtime.bootstrap_metadata(runtime_dir=tmp_path, provider="mock", model=None) == metadata
    assert len(created) == 1


def test_api_and_worker_environment_share_provider_model_and_cors(tmp_path: Path) -> None:
    database_path, object_root, _ = runtime.runtime_paths(tmp_path)
    metadata = {
        "principal_id": "principal-1",
        "workspace_id": "workspace-1",
        "database_path": str(database_path),
    }
    api = runtime.build_process_env(
        role="api", metadata=metadata, database_path=database_path, object_root=object_root,
        provider="deepseek", model="deepseek-v4",
    )
    worker = runtime.build_process_env(
        role="worker", metadata=metadata, database_path=database_path, object_root=object_root,
        provider="deepseek", model="deepseek-v4",
    )
    for env in (api, worker):
        assert env["POKIEQUANT_AGENT_PROVIDER"] == "deepseek"
        assert env["POKIEQUANT_AGENT_MODEL"] == "deepseek-v4"
        assert env["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] == "false"
        assert json.loads(env["GLINT_ALLOWED_ORIGINS"]) == ["tauri://localhost"]
    assert worker["GLINT_WORKSPACE_ID"] == "workspace-1"
    assert "GLINT_WORKSPACE_ID" not in api


def test_mock_ready_contract_uses_null_model(tmp_path: Path) -> None:
    assert runtime.selected_model("mock", "any-model") is None
    metadata = {
        "principal_id": "principal-1",
        "workspace_id": "workspace-1",
        "database_path": str(tmp_path / "qurio-local.db"),
    }
    database_path, object_root, _ = runtime.runtime_paths(tmp_path)
    env = runtime.build_process_env(
        role="api",
        metadata=metadata,
        database_path=database_path,
        object_root=object_root,
        provider="mock",
        model=None,
    )
    assert env["POKIEQUANT_AGENT_PROVIDER"] == "mock"
    assert "POKIEQUANT_AGENT_MODEL" not in env


def test_terminate_children_escalates_to_sigkill_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = mock.Mock()
    process.poll.return_value = None
    process.pid = 4321
    process.wait.side_effect = [subprocess.TimeoutExpired("worker", 5), None]
    monkeypatch.setattr(runtime.os, "getpgid", lambda _pid: 4321)
    killpg = mock.Mock()
    monkeypatch.setattr(runtime.os, "killpg", killpg)
    runtime.terminate_children([process])
    assert killpg.call_args_list == [
        mock.call(4321, signal.SIGTERM),
        mock.call(4321, signal.SIGKILL),
    ]
    assert process.wait.call_count == 2


def test_health_wait_stops_immediately_when_supervisor_is_terminating() -> None:
    assert runtime.wait_for_health(
        "http://127.0.0.1:1",
        timeout_seconds=20,
        should_stop=lambda: True,
    ) is False


def test_sigterm_during_health_wait_cleans_api_without_starting_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    metadata = {
        "principal_id": "principal-1",
        "workspace_id": "workspace-1",
        "database_path": str(tmp_path / "qurio-local.db"),
    }
    process = mock.Mock()
    process.poll.return_value = None
    process.pid = 4321
    process.wait.return_value = None
    handlers: dict[int, object] = {}
    started: list[list[str]] = []

    def install_handler(signum: int, handler: object) -> object:
        previous = handlers.get(signum, signal.SIG_DFL)
        handlers[signum] = handler
        return previous

    def stop_during_health(_api_url: str, **kwargs: object) -> bool:
        handler = handlers[signal.SIGTERM]
        assert callable(handler)
        handler(signal.SIGTERM, None)
        should_stop = kwargs["should_stop"]
        assert callable(should_stop)
        return not should_stop()

    monkeypatch.setattr(runtime, "bootstrap_metadata", lambda **_kwargs: metadata)
    monkeypatch.setattr(runtime, "free_loopback_port", lambda: 8123)
    monkeypatch.setattr(runtime, "build_process_env", lambda **_kwargs: {})
    def start_api(command: list[str], _env: dict[str, str]) -> mock.Mock:
        started.append(command)
        return process

    monkeypatch.setattr(runtime, "start_child", start_api)
    monkeypatch.setattr(runtime, "wait_for_health", stop_during_health)
    monkeypatch.setattr(runtime.signal, "signal", install_handler)
    monkeypatch.setattr(runtime.os, "getpgid", lambda _pid: 4321)
    monkeypatch.setattr(runtime.os, "killpg", mock.Mock())
    assert runtime.run(provider="mock", model=None, runtime_dir=tmp_path) == 0
    assert len(started) == 1


def test_main_reports_missing_key_without_echoing_its_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.delenv("POKIEQUANT_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert runtime.main(["--provider", "deepseek", "--runtime-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "API_KEY" in captured.err
    assert "QURIO_RUNTIME_READY" not in captured.out
