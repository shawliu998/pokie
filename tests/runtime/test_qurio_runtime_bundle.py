from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import scripts.build_qurio_runtime_sidecar as bundle
from scripts.build_qurio_runtime_sidecar import BUNDLE_PYTHON, RUNTIME_NAME, build_arguments


def test_sidecar_build_is_relocatable_and_excludes_test_tooling() -> None:
    root = Path("/repo")
    arguments = build_arguments(root)
    assert arguments[0] == "/repo/scripts/run_qurio_local_runtime.py"
    assert "--onedir" in arguments
    assert f"--name={RUNTIME_NAME}" in arguments
    assert "--collect-submodules=services" in arguments
    assert "--collect-submodules=packages" in arguments
    assert "--collect-submodules=connectors" in arguments
    assert "--hidden-import=services.worker.app.repositories.sqlalchemy_adapter" in arguments
    assert "--exclude-module=pytest" in arguments
    assert "--exclude-module=pyright" in arguments
    assert "--exclude-module=ruff" in arguments


def test_tauri_bundle_embeds_the_frozen_runtime() -> None:
    config = json.loads(Path("apps/mac/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert config["build"]["beforeBuildCommand"].endswith(
        "../../scripts/build_qurio_runtime_sidecar.py"
    )
    assert config["bundle"]["resources"] == {"resources/qurio-runtime/": "qurio-runtime/"}
    assert config["bundle"]["macOS"]["signingIdentity"] == "-"
    assert config["bundle"]["macOS"]["minimumSystemVersion"] == "11.0"


def test_bundle_environment_uses_managed_locked_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    uv = tmp_path / "uv"
    uv.touch()
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> mock.Mock:
        calls.append(command)
        result = mock.Mock()
        result.returncode = 0
        return result

    monkeypatch.setattr(bundle, "uv_executable", lambda _root: uv)
    monkeypatch.setattr(bundle.subprocess, "run", run)
    assert bundle.run_in_bundle_environment(tmp_path) == 0
    assert calls[0] == [str(uv), "python", "install", BUNDLE_PYTHON]
    assert calls[1][0:3] == [str(uv), "sync", "--locked"]
    assert "--extra" in calls[1]
    assert "bundle" in calls[1]
    assert calls[2][0] == str(tmp_path / ".run" / "qurio-bundle-venv" / "bin" / "python")
