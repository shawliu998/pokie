#!/usr/bin/env python3
"""Export a minimal, sanitized Wind integration proof from a retained Qurio state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

RAW_DIGEST_PATTERN = re.compile(r"(?:^|\|)sha256=([0-9a-f]{64})(?:$|\|)")
RETRIEVED_AT_PATTERN = re.compile(r"(?:^|\|)retrieved_at=([^|]+)(?:$|\|)")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_state(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT state_json FROM quant_repository_states ORDER BY workspace_id"
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        raise ValueError("Expected exactly one retained quant repository state.")
    state = json.loads(rows[0][0])
    if not isinstance(state, dict):
        raise ValueError("Retained quant repository state must be a JSON object.")
    return state


def _run_summary(
    run: dict[str, Any],
    *,
    experiments: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    run_id = run["id"]
    run_experiments = [item for item in experiments if item["run_id"] == run_id]
    run_artifacts = [item for item in artifacts if item["run_id"] == run_id]
    run_events = [item for item in events if item["run_id"] == run_id]
    failure_codes = Counter(
        item.get("payload", {}).get("error_code", "unknown")
        for item in run_events
        if item["event_type"] == "tool.failed"
    )
    return {
        "run_id": run_id,
        "status": run["state"],
        "parent_run_id": run["parent_run_id"],
        "seed_candidate_id": run["seed_candidate_id"],
        "provider": run["provider"],
        "model": run["model"],
        "dataset_id": run["dataset_id"],
        "dataset_digest": run["dataset_digest"],
        "planned_candidate_families": run["planned_candidate_families"],
        "experiment_count": len(run_experiments),
        "candidate_count": len(run_experiments),
        "artifact_count": len(run_artifacts),
        "artifact_type_counts": dict(
            sorted(Counter(item["kind"] for item in run_artifacts).items())
        ),
        "event_count": len(run_events),
        "tool_failure_count": sum(failure_codes.values()),
        "tool_failure_code_counts": dict(sorted(failure_codes.items())),
        "provider_decision_failure_count": sum(
            item["event_type"] == "decision.failed" for item in run_events
        ),
    }


def build_evidence(*, database: Path, raw_csv: Path) -> dict[str, Any]:
    state = _load_state(database)
    datasets = state.get("market_datasets_v2", [])
    runs = state.get("runs", [])
    experiments = state.get("experiments", [])
    artifacts = state.get("artifacts", [])
    events = state.get("events", [])
    if len(datasets) != 1 or len(runs) != 2:
        raise ValueError("Expected one retained dataset and exactly two runs.")

    record = datasets[0]
    dataset = record["dataset"]
    source = record["evidence"]
    quality = record["quality"]
    root = next((run for run in runs if run["parent_run_id"] is None), None)
    if root is None:
        raise ValueError("Expected one root run.")
    children = [run for run in runs if run["parent_run_id"] == root["id"]]
    if len(children) != 1:
        raise ValueError("Expected exactly one Continue child.")
    continued = children[0]

    source_reference = source.get("source_reference") or ""
    raw_digest_match = RAW_DIGEST_PATTERN.search(source_reference)
    if raw_digest_match is None:
        raise ValueError("Wind source reference does not retain the raw export digest.")
    raw_csv_sha256 = _sha256(raw_csv)
    if raw_digest_match.group(1) != raw_csv_sha256:
        raise ValueError("Raw CSV digest does not match the retained source reference.")
    retrieved_at_match = RETRIEVED_AT_PATTERN.search(source_reference)
    if retrieved_at_match is None:
        raise ValueError("Wind source reference does not retain retrieval time.")

    expected_dataset_id = dataset["dataset_id"]
    expected_dataset_digest = dataset["digest"]
    if any(
        run["dataset_id"] != expected_dataset_id or run["dataset_digest"] != expected_dataset_digest
        for run in runs
    ):
        raise ValueError("Run lineage does not pin one retained dataset identity.")
    if root["state"] != "completed" or continued["state"] != "completed":
        raise ValueError("Both retained runs must be completed.")
    if continued["seed_candidate_id"] is None:
        raise ValueError("Continue run must retain a seed candidate.")
    if root["provider"] != continued["provider"] or root["model"] != continued["model"]:
        raise ValueError("Root and Continue provider identity must agree.")
    if root["planned_candidate_families"] != continued["planned_candidate_families"]:
        raise ValueError("Root and Continue plan scope must agree.")
    if source["source_name"] != "Wind" or dataset["symbol"] != "000300.SH":
        raise ValueError("The retained source is not the authorized Wind CSI300 export.")

    root_summary = _run_summary(root, experiments=experiments, artifacts=artifacts, events=events)
    continue_summary = _run_summary(
        continued, experiments=experiments, artifacts=artifacts, events=events
    )
    return {
        "schema_version": "qurio-wind-professional-data-integration-proof-v1",
        "status": "passed",
        "claims": {
            "professional_dataset_integration": True,
            "live_market_feed": False,
            "wind_api_connection": False,
            "alpha_claim": False,
            "investment_recommendation": False,
        },
        "dataset_provenance": {
            "source_provider": "Wind",
            "source_identifier": dataset["symbol"],
            "dataset_type": "index_ohlcv",
            "frequency": dataset["interval"],
            "market_calendar": dataset["market_calendar"],
            "market_session": dataset["market_session"],
            "time_zone": dataset["time_zone"],
            "periods_per_year": dataset["periods_per_year"],
            "covered_start": dataset["covered_start"],
            "covered_end": dataset["covered_end"],
            "bar_count": len(dataset["bars"]),
            "retrieved_at_utc": retrieved_at_match.group(1),
            "raw_csv_sha256": raw_csv_sha256,
            "submitted_csv_digest": source["submitted_csv_digest"],
            "dataset_id": expected_dataset_id,
            "dataset_digest": expected_dataset_digest,
            "record_digest": record["record_digest"],
            "normalizer_version": source["normalizer_version"],
            "quality_status": quality["status"],
            "cadence_gap_count": quality["cadence_gap_count"],
            "holiday_completeness_inferred": False,
        },
        "run_lineage": {
            "history_count": 2,
            "parent_run_link_verified": True,
            "plan_scope_consistent": True,
            "root": root_summary,
            "continue": continue_summary,
        },
        "limitations": [
            "This is an authorized exported-dataset integration proof, not a live market feed.",
            "It does not prove a direct Wind API connection or general multi-source coverage.",
            "Exchange holiday completeness is not inferred from weekday-consistent session labels.",
            "It is not an alpha, profitability, trading, or investment-recommendation claim.",
            "The raw Wind CSV and retained SQLite database are not published.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--raw-csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evidence = build_evidence(database=args.database, raw_csv=args.raw_csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
