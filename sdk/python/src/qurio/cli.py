"""Command-line access to Qurio research data and retained evidence."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pydantic import BaseModel

from .client import QurioApiError, QurioClient
from .config import QurioConfigurationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qurio",
        description="Inspect a Qurio workspace without changing research state.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("datasets", help="List retained market datasets.")
    runs = subcommands.add_parser("runs", help="List retained research runs.")
    runs.add_argument("--project-id")
    runs.add_argument("--limit", type=int, default=50)
    run = subcommands.add_parser("run", help="Get one retained research run.")
    run.add_argument("run_id")
    snapshot = subcommands.add_parser(
        "snapshot", help="Get the workspace or one run's complete projection."
    )
    snapshot.add_argument("--run-id")
    return parser


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with QurioClient.from_env() as client:
            if args.command == "datasets":
                result = client.list_datasets()
            elif args.command == "runs":
                result = client.list_runs(project_id=args.project_id, limit=args.limit)
            elif args.command == "run":
                result = client.get_run(args.run_id)
            else:
                result = (
                    client.get_run_snapshot(args.run_id)
                    if args.run_id
                    else client.get_workspace_snapshot()
                )
        print(json.dumps(_json_value(result), indent=2, sort_keys=True))
        return 0
    except (QurioConfigurationError, QurioApiError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
