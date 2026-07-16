#!/usr/bin/env python3
"""Validate the redacted Glint Demo vertical-flow artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.seed_runtime import SeedError, validate_demo_artifact


def load_artifact(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SeedError(f"could not read demo artifact: {error}") from error
    if not isinstance(value, dict):
        raise SeedError("demo artifact must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    try:
        artifact = load_artifact(args.artifact)
        validate_demo_artifact(artifact)
    except SeedError as error:
        parser.exit(1, f"demo flow verification failed: {error}\n")
    counts = artifact["evidence_counts"]
    print(
        "demo flow verified "
        f"workspace_id={artifact['workspace_id']} "
        f"supports={counts['supports']} opposes={counts['opposes']} "
        f"brief_status={artifact['decision_brief_status']} "
        f"export_status={artifact['export_status']} "
        f"output_digest={artifact['export_output_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
