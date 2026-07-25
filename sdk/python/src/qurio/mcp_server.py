"""Read-only MCP projection over Qurio's retained research evidence."""

from __future__ import annotations

from typing import Any

from .client import QurioClient


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


class QurioReadTools:
    """Bounded MCP-facing operations with no research mutations."""

    def list_datasets(self) -> list[dict[str, Any]]:
        """List the retained datasets available for quantitative research."""

        with QurioClient.from_env() as client:
            return _dump(client.list_datasets())

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent retained research runs and their current states."""

        with QurioClient.from_env() as client:
            return _dump(client.list_runs(limit=limit))

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Get the typed contract for one retained research run."""

        with QurioClient.from_env() as client:
            return _dump(client.get_run(run_id))

    def get_run_evidence(self, run_id: str) -> dict[str, Any]:
        """Get the complete read-only evidence projection retained for a run."""

        with QurioClient.from_env() as client:
            return client.get_run_snapshot(run_id)


def create_server() -> Any:
    """Create the MCP server lazily so the base SDK has no MCP dependency."""

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "Qurio MCP support is not installed. Install qurio-sdk with the 'mcp' extra."
        ) from exc

    tools = QurioReadTools()
    server = FastMCP(
        "Qurio Research",
        instructions=(
            "Read retained Qurio quantitative datasets, runs and evidence. "
            "This server cannot start research, execute Python or place orders."
        ),
        json_response=True,
    )
    server.tool()(tools.list_datasets)
    server.tool()(tools.list_runs)
    server.tool()(tools.get_run)
    server.tool()(tools.get_run_evidence)
    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
