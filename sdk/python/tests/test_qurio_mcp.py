from __future__ import annotations

from typing import Any

import pytest

from qurio import mcp_server


class FakeClient:
    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def list_datasets(self) -> list[dict[str, Any]]:
        return [{"dataset_id": "dataset-v2"}]

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [{"id": "run-1", "limit": limit}]

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {"id": run_id}

    def get_run_snapshot(self, run_id: str) -> dict[str, Any]:
        return {"run": {"id": run_id}, "evidence": []}


def test_read_tools_delegate_only_to_read_client_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_server.QurioClient, "from_env", lambda: FakeClient()
    )
    tools = mcp_server.QurioReadTools()
    assert tools.list_datasets() == [{"dataset_id": "dataset-v2"}]
    assert tools.list_runs(8) == [{"id": "run-1", "limit": 8}]
    assert tools.get_run("run-2") == {"id": "run-2"}
    assert tools.get_run_evidence("run-2")["run"]["id"] == "run-2"


def test_mcp_server_registers_only_bounded_read_tools() -> None:
    server = mcp_server.create_server()
    assert {tool.name for tool in server._tool_manager.list_tools()} == {
        "list_datasets",
        "list_runs",
        "get_run",
        "get_run_evidence",
    }
