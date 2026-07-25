from __future__ import annotations

import json
from typing import Any

import pytest

from qurio import cli


class FakeClient:
    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def list_datasets(self) -> list[dict[str, Any]]:
        return [{"dataset_id": "dataset-v2", "symbol": "BTCUSD"}]

    def list_runs(
        self, *, project_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        return [{"id": "run-1", "project_id": project_id, "limit": limit}]

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {"id": run_id}

    def get_workspace_snapshot(self) -> dict[str, Any]:
        return {"scope": "workspace"}

    def get_run_snapshot(self, run_id: str) -> dict[str, Any]:
        return {"scope": "run", "run_id": run_id}


def test_cli_lists_runs_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.QurioClient, "from_env", lambda: FakeClient())
    assert cli.main(["runs", "--limit", "7", "--project-id", "project-1"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"id": "run-1", "limit": 7, "project_id": "project-1"}
    ]


def test_cli_selects_workspace_or_run_snapshot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.QurioClient, "from_env", lambda: FakeClient())
    assert cli.main(["snapshot"]) == 0
    assert json.loads(capsys.readouterr().out) == {"scope": "workspace"}
    assert cli.main(["snapshot", "--run-id", "run-2"]) == 0
    assert json.loads(capsys.readouterr().out) == {"scope": "run", "run_id": "run-2"}
