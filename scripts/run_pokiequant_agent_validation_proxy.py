#!/usr/bin/env python3
"""Run an offline engineering proxy for PokieQuant Agent-native research.

This is deliberately not user research. It copies the retained C5 database,
migrates only the copy, imports retained real BTCUSDT bars into eight isolated
workspaces through the existing CSV v2 boundary, and runs eight bounded AUTO
Runs with either offline Mock dry-run decisions or Keychain-backed DeepSeek.
DeepSeek mode remains an engineering proxy, not evidence from eight users.

The fixed-wizard baseline is a preregistered interaction-cost model only. It is
not executed and no baseline evidence, timing, field count, or user effort is
fabricated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterable
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / ".run" / "c5-btc-multiinterval-20260722"
SOURCE_DB = SOURCE_DIR / "pokiequant-live.db"
SOURCE_EVIDENCE = SOURCE_DIR / "c5-evidence.json"
TARGET_DIR = REPO_ROOT / ".run" / "agent-native-validation-20260723"
EVIDENCE_NAME = "agent-native-validation-proxy.json"
REPORT_NAME = "agent-native-validation-proxy.md"
PRE_HEAD_REVISION = "20260722_0007"
SOURCE_WORKSPACE_ID = "3ac2822d-9220-4559-9f1b-644702e80123"
PRINCIPAL_ID = "66c54575-9e06-45cc-b874-9669d40d451f"
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
ALLOWED_OVERRIDE_REASONS = frozenset(
    {"walk_forward_stability", "regime_coverage", "minimum_trade_evidence"}
)

SOURCE_DATASETS = {
    "4h": "binance-BTCUSDT-4h-ec61e63b39a90e4f",
    "1D": "binance-BTCUSDT-1D-98dad35bb7632be9",
}

SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "id": "Q1",
        "interval": "4h",
        "intent": "trend",
        "expected_objective": "drawdown_control",
        "question": (
            "Test whether a BTCUSDT 4h SMA trend strategy can reduce drawdown rather "
            "than merely lift training Sharpe. Comparison objective: drawdown control."
        ),
    },
    {
        "id": "Q2",
        "interval": "4h",
        "intent": "breakout",
        "expected_objective": "risk_adjusted_return",
        "question": (
            "Test whether a BTCUSDT 4h breakout remains stable across high- and "
            "low-volatility regimes or only captures one segment. Comparison objective: "
            "risk-adjusted performance."
        ),
    },
    {
        "id": "Q3",
        "interval": "4h",
        "intent": "mean_reversion",
        "expected_objective": "total_return",
        "question": (
            "Test whether BTCUSDT 4h RSI mean reversion still adds total return after "
            "the existing fees and slippage; stop if it does not. Comparison objective: "
            "total return."
        ),
    },
    {
        "id": "Q4",
        "interval": "4h",
        "intent": "frequent_opportunity",
        "expected_objective": "risk_adjusted_return",
        "question": (
            "Do not continue tuning BTCUSDT 4h parameters. Choose the candidate with "
            "the strongest walk-forward stability rather than the highest training "
            "score. Comparison objective: risk-adjusted performance."
        ),
    },
    {
        "id": "Q5",
        "interval": "1D",
        "intent": "frequent_opportunity",
        "expected_objective": "drawdown_control",
        "question": (
            "Compare BTCUSDT 1D trend, breakout, and mean-reversion trading opportunities "
            "and decide which has the most credible drawdown-versus-reward tradeoff. "
            "Comparison objective: drawdown control."
        ),
    },
    {
        "id": "Q6",
        "interval": "1D",
        "intent": "frequent_opportunity",
        "expected_objective": "total_return",
        "question": (
            "Determine whether BTCUSDT 1D trading opportunities produce enough trades "
            "to support a total return conclusion; stop if the sample is too small. "
            "Comparison objective: total return."
        ),
    },
    {
        "id": "Q7",
        "interval": "1D",
        "intent": "frequent_opportunity",
        "expected_objective": "drawdown_control",
        "question": (
            "If the BTCUSDT 1D A/B evidence is unstable, use its failure reason to "
            "propose one canonical-distinct candidate C rather than merely renaming a "
            "parameter tweak. Comparison objective: drawdown control."
        ),
    },
    {
        "id": "Q8",
        "interval": "1D",
        "intent": "frequent_opportunity",
        "expected_objective": "total_return",
        "question": (
            "Under the fixed BTCUSDT 1D data and costs, decide whether any bounded "
            "strategy has enough total return evidence to enter another validation "
            "round; otherwise state that research should not advance."
        ),
    },
)

BASELINE = {
    "kind": "preregistered_strong_fixed_wizard_cost_model",
    "executed": False,
    "orchestration_actions_estimate": 5,
    "parameter_values_manually_entered": 0,
    "default_candidate_bundle_confirmation": 1,
    "manual_fields": None,
    "typed_characters": None,
    "time_to_first_evidence_seconds": None,
    "note": (
        "The wizard accepts one fixed default candidate bundle and is not executed. "
        "Only orchestration actions are compared."
    ),
}

AGENT_UI_PROXY = {
    "kind": "preregistered_real_ui_interaction_proxy",
    "orchestration_actions_estimate": 4,
    "manual_fields": None,
    "typed_characters": None,
    "active_human_seconds": None,
    "note": (
        "Four actions model dataset selection, objective entry, Auto mode selection, "
        "and Start. No person was timed."
    ),
}

THRESHOLDS = {
    "minimum_action_reduction_fraction": 0.25,
    "minimum_evidence_completion_runs": 7,
    "required_objective_adherence_runs": 8,
    "minimum_readiness_fraction": 0.90,
    "minimum_novel_feedback_c_runs": 4,
    "minimum_useful_feedback_c_runs": 3,
}


def _headers(workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {PRINCIPAL_ID}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _configure_environment(run_dir: Path, provider_name: str) -> tuple[Path, Path]:
    database = run_dir / "pokiequant-live.db"
    objects = run_dir / "pokiequant-live-objects"
    objects.mkdir(parents=True, exist_ok=True)
    os.environ["GLINT_ENVIRONMENT"] = "development"
    os.environ["GLINT_SERVICE_ROLE"] = "api"
    os.environ["GLINT_DATABASE_URL"] = f"sqlite:///{database.resolve()}"
    os.environ["GLINT_OBJECT_STORE_BACKEND"] = "filesystem"
    os.environ["GLINT_OBJECT_STORE_ROOT"] = str(objects.resolve())
    os.environ["GLINT_CREATE_SCHEMA_ON_STARTUP"] = "false"
    os.environ["POKIEQUANT_AGENT_PROVIDER"] = provider_name
    os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] = "false"
    return database, objects


def _load_deepseek_key_from_keychain() -> None:
    account = os.environ.get("USER")
    if not account:
        raise RuntimeError("USER is unavailable for the macOS Keychain lookup.")
    completed = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-w",
            "-a",
            account,
            "-s",
            "pokiequant.deepseek",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    secret = completed.stdout.strip()
    if completed.returncode != 0 or not secret:
        raise RuntimeError(
            "DeepSeek credential was not available from Keychain service pokiequant.deepseek."
        )
    os.environ["DEEPSEEK_API_KEY"] = secret


def _copy_runtime(run_dir: Path, provider_name: str) -> Path:
    if not SOURCE_DB.is_file():
        raise RuntimeError(f"Required retained C5 database is missing: {SOURCE_DB}")
    run_dir.mkdir(parents=True)
    database, objects = _configure_environment(run_dir, provider_name)
    shutil.copy2(SOURCE_DB, database)
    source_objects = SOURCE_DIR / "pokiequant-live-objects"
    if source_objects.is_dir():
        shutil.copytree(source_objects, objects, dirs_exist_ok=True)
    return database


def _migrate_copy(database: Path) -> None:
    from alembic import command
    from alembic.config import Config

    with sqlite3.connect(database) as connection:
        has_revision_table = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
            ).fetchone()
            is not None
        )
    config = Config(str(REPO_ROOT / "infra" / "migrations" / "alembic.ini"))
    config.attributes["database_url"] = os.environ["GLINT_DATABASE_URL"]
    if not has_revision_table:
        command.stamp(config, PRE_HEAD_REVISION)
    command.upgrade(config, "head")


@contextmanager
def _network_disabled() -> Iterable[None]:
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked_connect(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Network is disabled for the Agent validation engineering proxy.")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.create_connection = blocked_connect  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.create_connection = original_create_connection


def _csv_for_record(record: Any) -> str:
    rows = ["timestamp,open,high,low,close,volume"]
    for bar in record.dataset.bars:
        timestamp = bar.timestamp.isoformat().replace("+00:00", "Z")
        rows.append(
            ",".join(
                (
                    timestamp,
                    str(bar.open),
                    str(bar.high),
                    str(bar.low),
                    str(bar.close),
                    str(bar.volume),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _event_value(event: Any, key: str) -> Any:
    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key)


def _failure_modes(events: list[Any]) -> tuple[list[str], dict[str, int]]:
    error_counts: dict[str, int] = {}
    action_error_counts: dict[str, int] = {}
    provider_failures = 0
    strict_sequence_failures = 0
    for event in events:
        event_type = str(_event_value(event, "event_type"))
        payload = _event_value(event, "payload")
        payload = payload if isinstance(payload, dict) else {}
        if event_type == "agent.decision_failed":
            provider_failures += 1
        if event_type == "run.failed" and payload.get("reason_code") == (
            "strict_iteration_sequence_incomplete"
        ):
            strict_sequence_failures += 1
        if event_type != "tool.failed":
            continue
        error = str(payload.get("error_code") or "UNKNOWN")
        action = str(payload.get("action") or "unknown")
        error_counts[error] = error_counts.get(error, 0) + 1
        compound = f"{action}:{error}"
        action_error_counts[compound] = action_error_counts.get(compound, 0) + 1
    modes: list[str] = []
    if error_counts.get("INVALID_ARGUMENTS", 0) >= 2:
        modes.append("repeated_invalid_arguments")
    if any(
        key.startswith(("compare_candidates:", "finish_research:")) for key in action_error_counts
    ):
        modes.append("final_comparison_or_finish_failure")
    if provider_failures:
        modes.append("provider_response_validation_failure")
    if error_counts.get("EXPERIMENT_BUDGET_EXHAUSTED", 0):
        modes.append("experiment_budget_exhausted")
    if strict_sequence_failures:
        modes.append("strict_iteration_sequence_incomplete")
    counts = {
        **{f"error:{key}": value for key, value in sorted(error_counts.items())},
        **{f"action_error:{key}": value for key, value in sorted(action_error_counts.items())},
        "provider_decision_failure_events": provider_failures,
        "strict_sequence_failure_events": strict_sequence_failures,
    }
    return modes, counts


def _first_evidence_seconds(run: Any, events: list[Any]) -> float | None:
    for event in sorted(events, key=lambda item: int(_event_value(item, "sequence"))):
        payload = _event_value(event, "payload")
        if (
            _event_value(event, "event_type") == "tool.completed"
            and isinstance(payload, dict)
            and payload.get("action") == "run_backtest"
            and payload.get("success") is True
        ):
            occurred_at = _event_value(event, "occurred_at") or _event_value(event, "timestamp")
            if isinstance(occurred_at, datetime):
                return round(max(0.0, (occurred_at - run.created_at).total_seconds()), 6)
    return None


def _objective_adherent(
    *,
    run: Any,
    final_comparison: Any | None,
    report: Any | None,
    expected_objective: str,
) -> tuple[bool, str | None, str | None]:
    if final_comparison is None or report is None:
        return False, None, None
    comparison = final_comparison.content
    ranking = comparison.get("ranking")
    decision = report.content.get("research_decision")
    selected = report.content.get("selected_candidate_id")
    if (
        run.selection_objective != expected_objective
        or comparison.get("selection_objective") != expected_objective
        or not isinstance(ranking, list)
        or not ranking
        or not isinstance(decision, dict)
    ):
        return False, None, None
    basis = decision.get("decision_basis")
    deviation = decision.get("deviation")
    if basis == "approved_objective_rank":
        valid = selected == ranking[0] and deviation is None
        return valid, basis, None
    if basis == "robustness_override" and isinstance(deviation, dict):
        reason = deviation.get("reason")
        valid = (
            selected != ranking[0]
            and reason in ALLOWED_OVERRIDE_REASONS
            and deviation.get("reference_candidate_id") == ranking[0]
        )
        return valid, basis, str(reason) if reason is not None else None
    return False, str(basis) if basis is not None else None, None


def _readiness(
    *,
    run: Any,
    dataset: dict[str, Any],
    experiments: list[Any],
    artifacts: list[Any],
    final_comparison: Any | None,
    report: Any | None,
) -> tuple[int, dict[str, bool]]:
    kinds = {artifact.kind.value for artifact in artifacts}
    dataset_digest = dataset.get("digest") or dataset.get("dataset_digest")
    selected_id = report.content.get("selected_candidate_id") if report is not None else None
    selected_trade_log = any(
        artifact.kind.value == "trade_log" and artifact.content.get("candidate_id") == selected_id
        for artifact in artifacts
    )
    generalization = report.content.get("generalization") if report is not None else None
    checks = {
        "dataset_and_split_identity": bool(
            dataset_digest
            and run.runtime_descriptor_digest
            and run.runtime_split_digest
            and report is not None
            and report.content.get("dataset", {}).get("digest") == dataset_digest
        ),
        "three_candidate_final_comparison": bool(
            final_comparison is not None
            and len(final_comparison.content.get("candidates", [])) == 3
            and len(experiments) == 3
        ),
        "metrics_equity_drawdown": bool(
            experiments
            and all(item.metrics for item in experiments)
            and "equity_curve" in kinds
            and "backtest_result" in kinds
        ),
        "selected_trade_log": selected_trade_log,
        "walk_forward": bool(report is not None and report.content.get("walk_forward")),
        "sealed_holdout": bool(
            isinstance(generalization, dict)
            and generalization.get("status") in {"pass", "fail", "inconclusive"}
            and generalization.get("holdout")
        ),
        "limitations_decision_next_action": bool(
            report is not None
            and report.content.get("limitations")
            and report.content.get("research_decision")
            and report.content.get("next_step")
        ),
    }
    return sum(checks.values()), checks


def _safe_historical_sentinels() -> dict[str, Any]:
    if not SOURCE_EVIDENCE.is_file():
        return {"available": False}
    source = json.loads(SOURCE_EVIDENCE.read_text())
    safe_runs = []
    for run in source.get("runs", []):
        if run.get("state") != "completed":
            continue
        safe_runs.append(
            {
                "run_id": run.get("run_id"),
                "dataset_id": run.get("dataset_id"),
                "state": run.get("state"),
                "agent_iterations": run.get("agent_iterations"),
                "candidate_count": run.get("used_experiments"),
                "holdout_status": run.get("holdout_status"),
                "provider_fallback_events": run.get("provider_fallback_events"),
            }
        )
    return {
        "available": True,
        "historical_only": True,
        "new_deepseek_call": False,
        "source_evidence_path": str(SOURCE_EVIDENCE.relative_to(REPO_ROOT)),
        "source_evidence_digest": _file_digest(SOURCE_EVIDENCE),
        "recorded_provider": source.get("provider"),
        "recorded_model": source.get("model"),
        "completed_run_sentinels": safe_runs,
    }


def _assert_safe_payload(value: object, *, path: str = "$") -> None:
    forbidden_keys = {
        "api_key",
        "raw_provider_response",
        "raw_response",
        "provider_response",
        "secret",
        "token",
        "candidate_key",
        "candidate_keys",
        "tested_candidate_keys",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in forbidden_keys:
                raise RuntimeError(f"Unsafe evidence field at {path}.{key}")
            _assert_safe_payload(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_safe_payload(item, path=f"{path}[{index}]")


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = sum(row["state"] == "completed" for row in results)
    budget_exhausted_nonterminal = sum(
        bool(row.get("budget_exhausted_nonterminal")) for row in results
    )
    objective_adherent = sum(bool(row["objective_adherence"]) for row in results)
    novel_c = sum(bool(row["feedback_c"]["canonical_distinct"]) for row in results)
    useful_c = sum(bool(row["feedback_c"]["useful"]) for row in results)
    readiness_points = sum(int(row["readiness"]["score"]) for row in results)
    readiness_possible = len(results) * 7
    baseline_actions = int(BASELINE["orchestration_actions_estimate"])
    agent_actions = int(AGENT_UI_PROXY["orchestration_actions_estimate"])
    action_reduction = (baseline_actions - agent_actions) / baseline_actions
    provider_names = {str(row["configured_provider"]) for row in results}
    all_deepseek_terminal_within_budget = (
        all(row["state"] in TERMINAL_STATES for row in results)
        if provider_names == {"deepseek"}
        else None
    )
    failure_modes: dict[str, list[str]] = {}
    for row in results:
        for mode in row.get("failure_modes", []):
            failure_modes.setdefault(str(mode), []).append(str(row["scenario_id"]))
    gates: dict[str, bool | None] = {
        "action_reduction": (action_reduction >= THRESHOLDS["minimum_action_reduction_fraction"]),
        "evidence_completion": (completed >= THRESHOLDS["minimum_evidence_completion_runs"]),
        "objective_adherence": (
            objective_adherent >= THRESHOLDS["required_objective_adherence_runs"]
        ),
        "evidence_readiness": (
            readiness_points / readiness_possible >= THRESHOLDS["minimum_readiness_fraction"]
        ),
        "novel_feedback_c": (novel_c >= THRESHOLDS["minimum_novel_feedback_c_runs"]),
        "useful_feedback_c": (useful_c >= THRESHOLDS["minimum_useful_feedback_c_runs"]),
        "manual_input_reduction": None,
        "baseline_time_to_first_evidence": None,
        "real_user_effort": None,
        "all_deepseek_runs_terminal_within_budget": all_deepseek_terminal_within_budget,
    }
    measured_gates = [value for value in gates.values() if value is not None]
    if any(value is False for value in measured_gates):
        verdict = "FAIL"
    elif any(value is None for value in gates.values()):
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"
    return {
        "scenario_count": len(results),
        "completed_runs": completed,
        "budget_exhausted_nonterminal_runs": budget_exhausted_nonterminal,
        "objective_adherent_runs": objective_adherent,
        "novel_feedback_c_runs": novel_c,
        "useful_feedback_c_runs": useful_c,
        "readiness_points": readiness_points,
        "readiness_possible": readiness_possible,
        "readiness_fraction": round(readiness_points / readiness_possible, 6),
        "baseline_orchestration_actions_estimate": baseline_actions,
        "agent_orchestration_actions_estimate": agent_actions,
        "estimated_action_reduction_fraction": round(action_reduction, 6),
        "gates": gates,
        "proxy_verdict": verdict,
        "scope_cap": "engineering_proxy_only",
        "user_effort_claim": "INCONCLUSIVE",
        "failure_modes": {
            mode: {"scenario_count": len(ids), "scenario_ids": ids}
            for mode, ids in sorted(failure_modes.items())
        },
        "provider_evidence": {
            "configured_provider": next(iter(provider_names)) if len(provider_names) == 1 else None,
            "fresh_deepseek_engineering_run_count": sum(
                row["configured_provider"] == "deepseek" for row in results
            ),
            "provider_identity_consistent": len(provider_names) == 1
            and all(row["provider"] == row["configured_provider"] for row in results),
            "mock_fallback_event_count": sum(
                int(row["provider_fallback_event_count"]) for row in results
            ),
        },
        "reason": (
            "The proxy can fail or pass engineering gates, but it cannot establish user effort: "
            "the baseline was not executed and no person was timed."
        ),
    }


def _markdown(payload: dict[str, Any]) -> str:
    aggregate = payload["aggregate"]
    provider_name = payload["configured_provider"]
    rows = [
        "# PokieQuant Agent-native validation engineering proxy",
        "",
        f"> This is a {provider_name} engineering proxy, not eight users and not "
        "evidence that users save work.",
        "",
        f"- Verdict: **{aggregate['proxy_verdict']}** "
        f"({aggregate['scope_cap']}; user-effort claim: {aggregate['user_effort_claim']})",
        f"- Runs: {aggregate['completed_runs']}/{aggregate['scenario_count']} completed",
        f"- Budget exhausted but nonterminal at 12 actions: "
        f"{aggregate['budget_exhausted_nonterminal_runs']}/8",
        f"- Objective adherence: {aggregate['objective_adherent_runs']}/8",
        f"- Feedback-driven canonical-distinct C: {aggregate['novel_feedback_c_runs']}/8",
        f"- Useful C proxy: {aggregate['useful_feedback_c_runs']}/8",
        f"- Evidence readiness: {aggregate['readiness_points']}/"
        f"{aggregate['readiness_possible']} ({aggregate['readiness_fraction']:.1%})",
        f"- Preregistered orchestration estimate: Agent "
        f"{aggregate['agent_orchestration_actions_estimate']} vs fixed wizard "
        f"{aggregate['baseline_orchestration_actions_estimate']} "
        f"({aggregate['estimated_action_reduction_fraction']:.1%} reduction)",
        "",
        "## Scenario results",
        "",
        "| ID | Interval | Objective | State | Actions | Candidates | Novel C | "
        "Objective | Holdout | Ready | Wall s |",
        "|---|---|---|---|---:|---:|---|---|---|---:|---:|",
    ]
    for row in payload["results"]:
        rows.append(
            f"| {row['scenario_id']} | {row['interval']} | "
            f"{row['expected_objective']} | {row['state']} | "
            f"{row['agent_iterations']} | {row['candidate_count']} | "
            f"{'yes' if row['feedback_c']['canonical_distinct'] else 'no'} | "
            f"{'yes' if row['objective_adherence'] else 'no'} | "
            f"{row['holdout_status'] or '—'} | {row['readiness']['score']}/7 | "
            f"{row['wall_time_seconds']:.3f} |"
        )
    rows.extend(
        [
            "",
            "## Interpretation",
            "",
            "- The fixed wizard was not executed. Its five actions and zero manually entered "
            "parameter values are a preregistered strong-baseline estimate.",
            "- Agent UI work is also a four-action proxy. Manual fields, typed characters, "
            "active human time, and baseline time-to-first-evidence remain `null`.",
            "- Each question ran in an isolated workspace. Retained C5 bars entered through "
            "the CSV-upload contract, so the copied datasets are not described as fresh "
            "provider fetches.",
            (
                "- Network access was blocked and the explicit provider was Mock with fallback off."
                if provider_name == "mock"
                else "- Fresh DeepSeek calls used a Keychain-injected credential; the value was "
                "never printed or persisted, and Mock fallback was off."
            ),
            "- Historical DeepSeek sentinel IDs are read-only facts from retained C5 evidence.",
            "- Provider HTTP request count was not instrumented. The report records "
            "model-or-server decision events and provider failure events, not a claimed "
            "API request total.",
            f"- {aggregate['budget_exhausted_nonterminal_runs']} Runs remained nonterminal "
            "after the preregistered 12-action boundary. "
            "The next server-derived budget-finish action was not executed, because that "
            "would be a thirteenth action and would change the preregistered test.",
            "",
            "## Gate results",
            "",
        ]
    )
    for name, value in aggregate["gates"].items():
        rendered = "not measured" if value is None else ("PASS" if value else "FAIL")
        rows.append(f"- {name}: {rendered}")
    rows.extend(["", "## Failure modes", ""])
    for name, detail in aggregate["failure_modes"].items():
        rows.append(
            f"- {name}: {detail['scenario_count']} scenario(s) — "
            f"{', '.join(detail['scenario_ids'])}"
        )
    rows.append("")
    return "\n".join(rows)


def _run_proxy(run_dir: Path, *, provider_name: str, credential_source: str) -> dict[str, Any]:
    database = _copy_runtime(run_dir, provider_name)
    _migrate_copy(database)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from fastapi.testclient import TestClient

    from services.api.app.db.session import reset_database_caches
    from services.api.app.main import app
    from services.api.app.modules.quant.store import QuantStore
    from services.worker.app.pipelines.quant_agent import run_quant_agent_once
    from services.worker.app.quant_agent.provider import (
        DEFAULT_DEEPSEEK_MODEL,
        MockQuantAgentProvider,
        load_quant_agent_provider,
    )

    reset_database_caches()
    source_store = QuantStore()
    source_records = {
        interval: source_store.get_market_dataset_v2(
            workspace_id=SOURCE_WORKSPACE_ID, dataset_id=dataset_id
        )
        for interval, dataset_id in SOURCE_DATASETS.items()
    }
    source_csv = {interval: _csv_for_record(record) for interval, record in source_records.items()}
    source_dataset_facts = {
        interval: {
            "dataset_id": record.id,
            "dataset_digest": record.dataset.digest,
            "record_digest": record.record_digest,
            "interval": record.dataset.interval.value,
            "covered_start": record.dataset.covered_start.isoformat().replace("+00:00", "Z"),
            "covered_end": record.dataset.covered_end.isoformat().replace("+00:00", "Z"),
            "bar_count": len(record.dataset.bars),
            "retained_source_kind": record.evidence.source_kind.value,
        }
        for interval, record in source_records.items()
    }

    results: list[dict[str, Any]] = []
    provider = MockQuantAgentProvider() if provider_name == "mock" else load_quant_agent_provider()
    expected_deepseek_model = os.environ.get("POKIEQUANT_AGENT_MODEL", DEFAULT_DEEPSEEK_MODEL)
    if provider_name == "deepseek" and (
        provider.provider_name != "openai_compatible"
        or provider.model_name != expected_deepseek_model
    ):
        raise RuntimeError("Keychain-backed provider did not resolve to DeepSeek.")
    started = time.monotonic()
    network_context = _network_disabled() if provider_name == "mock" else nullcontext()
    with network_context, TestClient(app) as client:
        for scenario in SCENARIOS:
            scenario_started = time.monotonic()
            print(f"proxy: {scenario['id']} {scenario['interval']}", flush=True)
            workspace_response = client.post(
                "/v1/workspaces",
                headers=_headers(),
                json={
                    "name": f"Agent validation proxy {scenario['id']}",
                    "data_region": "local",
                    "retention_policy_version": "retention-v1",
                },
            )
            workspace_response.raise_for_status()
            workspace_id = str(workspace_response.json()["workspace_id"])
            interval = scenario["interval"]
            source_record = source_records[interval]
            import_response = client.post(
                "/v1/quant/datasets/v2/import-csv",
                headers=_headers(workspace_id),
                json={
                    "name": f"Retained C5 BTCUSDT {interval} for {scenario['id']}",
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "csv_text": source_csv[interval],
                    "file_name": f"retained-c5-btcusdt-{interval.lower()}-{scenario['id']}.csv",
                    "source_name": "Retained C5 provider data (offline CSV copy)",
                    "source_reference": (
                        "retained C5 provider data; offline CSV copy of "
                        f"{source_record.id}; no network fetch"
                    ),
                },
            )
            import_response.raise_for_status()
            dataset = import_response.json()
            if dataset["evidence"]["source_kind"] != "csv_upload":
                raise RuntimeError("Isolated validation data was not imported as csv_upload.")
            imported_record = QuantStore().get_market_dataset_v2(
                workspace_id=workspace_id, dataset_id=dataset["dataset_id"]
            )
            if imported_record.dataset.bars != source_record.dataset.bars:
                raise RuntimeError("Offline CSV import changed the retained market bars.")
            project_response = client.post(
                "/v1/quant/projects",
                headers=_headers(workspace_id),
                json={
                    "name": f"Validation proxy {scenario['id']}",
                    "objective": scenario["question"],
                },
            )
            project_response.raise_for_status()
            project = project_response.json()
            create_response = client.post(
                "/v1/quant/market-runs",
                headers=_headers(workspace_id),
                json={
                    "project_id": project["id"],
                    "mode": "auto",
                    "question": scenario["question"],
                    "expected_project_row_version": project["row_version"],
                    "dataset_id": dataset["dataset_id"],
                    "research_start_utc": dataset["covered_start"],
                    "research_end_utc": dataset["covered_end"],
                },
            )
            create_response.raise_for_status()
            run_id = str(create_response.json()["id"])

            actions = 0
            current_store = QuantStore()
            current = current_store.get_run(workspace_id=workspace_id, run_id=run_id)
            while current.state.value not in TERMINAL_STATES and actions < 12:
                did_work = run_quant_agent_once(
                    store=current_store,
                    provider=provider,
                    workspace_id=workspace_id,
                )
                if not did_work:
                    break
                actions += 1
                current = current_store.get_run(workspace_id=workspace_id, run_id=run_id)
            current = current_store.get_run(workspace_id=workspace_id, run_id=run_id)
            experiments = sorted(
                current_store.experiments_for_run(workspace_id=workspace_id, run_id=run_id),
                key=lambda item: item.ordinal,
            )
            artifacts = current_store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
            events = current_store.events_for_run(workspace_id=workspace_id, run_id=run_id)
            comparisons = sorted(
                (
                    item
                    for item in artifacts
                    if item.kind.value == "validation_report"
                    and item.content.get("evaluation_partition") == "train"
                ),
                key=lambda item: item.ordinal,
            )
            latest_training_comparison = comparisons[-1] if comparisons else None
            reports = [item for item in artifacts if item.kind.value == "research_report"]
            report = reports[0] if len(reports) == 1 else None
            feedback_artifacts = [
                item for item in artifacts if item.kind.value == "iteration_feedback"
            ]
            feedback_c = experiments[2] if len(experiments) >= 3 else None
            prior_keys = {
                item.candidate_key for item in experiments[:2] if item.candidate_key is not None
            }
            c_distinct = bool(
                feedback_c is not None
                and len(experiments) == 3
                and all(item.state == "completed" for item in experiments)
                and feedback_c.feedback_artifact_id
                and feedback_c.replan_decision is not None
                and feedback_c.candidate_key
                and feedback_c.candidate_key not in prior_keys
                and len(feedback_artifacts) == 1
                and feedback_c.feedback_artifact_id == feedback_artifacts[0].id
            )
            comparison_candidate_ids = (
                {
                    str(item.get("candidate_id"))
                    for item in latest_training_comparison.content.get("candidates", [])
                    if isinstance(item, dict) and item.get("candidate_id")
                }
                if latest_training_comparison is not None
                else set()
            )
            final_comparison = (
                latest_training_comparison
                if c_distinct and comparison_candidate_ids == {item.id for item in experiments}
                else None
            )
            ranking = (
                final_comparison.content.get("ranking", []) if final_comparison is not None else []
            )
            selected_id = (
                report.content.get("selected_candidate_id") if report is not None else None
            )
            c_useful = bool(
                c_distinct
                and feedback_c is not None
                and ranking
                and (ranking[0] == feedback_c.id or selected_id == feedback_c.id)
            )
            objective_adherence, decision_basis, override_reason = _objective_adherent(
                run=current,
                final_comparison=final_comparison,
                report=report,
                expected_objective=scenario["expected_objective"],
            )
            readiness_score, readiness_checks = _readiness(
                run=current,
                dataset=dataset,
                experiments=experiments,
                artifacts=artifacts,
                final_comparison=final_comparison,
                report=report,
            )
            event_types = [str(_event_value(event, "event_type")) for event in events]
            provider_failures = sum(
                event_type == "agent.decision_failed" for event_type in event_types
            )
            fallback_events = sum(
                event_type == "agent.provider_fallback" for event_type in event_types
            )
            action_events = [
                event
                for event in events
                if _event_value(event, "event_type") == "agent.action_selected"
            ]
            system_action_events = sum(
                str(_event_value(event, "payload").get("decision_summary", "")).startswith(
                    (
                        "Compare the two completed base candidates",
                        "Finish safely because the Agent iteration budget",
                    )
                )
                for event in action_events
            )
            selected_action_events = len(action_events)
            failure_modes, failure_event_counts = _failure_modes(events)
            generalization = report.content.get("generalization") if report is not None else None
            result = {
                "scenario_id": scenario["id"],
                "workspace_id": workspace_id,
                "run_id": run_id,
                "question": scenario["question"],
                "intent": scenario["intent"],
                "symbol": "BTCUSDT",
                "interval": interval,
                "expected_objective": scenario["expected_objective"],
                "actual_objective": current.selection_objective,
                "dataset": {
                    "dataset_id": dataset["dataset_id"],
                    "dataset_digest": dataset["digest"],
                    "record_digest": dataset["record_digest"],
                    "source_kind": dataset["evidence"]["source_kind"],
                    "source_name": dataset["evidence"]["source_name"],
                    "retained_source_dataset_id": source_record.id,
                    "retained_source_dataset_digest": source_record.dataset.digest,
                    "bar_count": dataset["bar_count"],
                    "covered_start": dataset["covered_start"],
                    "covered_end": dataset["covered_end"],
                },
                "provider": current.provider,
                "model": current.model,
                "configured_provider": provider_name,
                "provider_plan_call_count": 1,
                "provider_api_request_count": None,
                "model_or_server_decision_event_count": selected_action_events,
                "server_forced_decision_event_count": system_action_events,
                "mock_explicit": provider_name == "mock" and current.provider == "mock",
                "mock_fallback_allowed": False,
                "network_disabled": provider_name == "mock",
                "research_loop_enabled": current.research_loop_policy is not None,
                "state": current.state.value,
                "agent_iterations": current.agent_iteration,
                "bounded_action_polls": actions,
                "within_12_action_boundary": actions <= 12,
                "terminal_within_12_action_boundary": (
                    current.state.value in TERMINAL_STATES and actions <= 12
                ),
                "budget_exhausted_nonterminal": bool(
                    current.state.value not in TERMINAL_STATES
                    and current.agent_iteration >= current.max_agent_iterations
                ),
                "next_system_budget_finish_not_executed": bool(
                    current.state.value not in TERMINAL_STATES
                    and current.agent_iteration >= current.max_agent_iterations
                ),
                "candidate_count": len(experiments),
                "canonical_distinct_candidate_count": len(
                    {item.candidate_key for item in experiments if item.candidate_key}
                ),
                "final_comparison_present": final_comparison is not None,
                "final_comparison_candidate_count": (
                    len(final_comparison.content.get("candidates", []))
                    if final_comparison is not None
                    else 0
                ),
                "iteration_feedback_count": len(feedback_artifacts),
                "feedback_c": {
                    "present": feedback_c is not None,
                    "feedback_linked": bool(
                        feedback_c is not None and feedback_c.feedback_artifact_id
                    ),
                    "replan_decision_present": bool(
                        feedback_c is not None and feedback_c.replan_decision is not None
                    ),
                    "canonical_distinct": c_distinct,
                    "useful": c_useful,
                },
                "objective_adherence": objective_adherence,
                "decision_basis": decision_basis,
                "override_reason": override_reason,
                "selected_candidate_present": bool(selected_id),
                "holdout_status": (
                    generalization.get("status") if isinstance(generalization, dict) else None
                ),
                "unique_report": len(reports) == 1,
                "readiness": {
                    "score": readiness_score,
                    "possible": 7,
                    "checks": readiness_checks,
                },
                "provider_failure_count": provider_failures,
                "provider_fallback_event_count": fallback_events,
                "failure_modes": failure_modes,
                "failure_event_counts": failure_event_counts,
                "time_to_first_evidence_seconds": _first_evidence_seconds(current, events),
                "wall_time_seconds": round(time.monotonic() - scenario_started, 6),
                "manual_fields": None,
                "typed_characters": None,
                "active_human_seconds": None,
            }
            results.append(result)

    preregistration = {
        "scenarios": list(SCENARIOS),
        "baseline": BASELINE,
        "agent_ui_proxy": AGENT_UI_PROXY,
        "thresholds": THRESHOLDS,
        "source_datasets": SOURCE_DATASETS,
    }
    payload = {
        "schema_version": "pokiequant-agent-native-validation-engineering-proxy-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "classification": "engineering_proxy_only",
        "not_user_validation": True,
        "not_fresh_deepseek_verification": provider_name != "deepseek",
        "fresh_deepseek_engineering_runs": (
            sum(row["configured_provider"] == "deepseek" for row in results)
        ),
        "credential_source": credential_source,
        "credential_value_persisted": False,
        "configured_provider": provider_name,
        "mock_provider_explicit": provider_name == "mock",
        "mock_fallback_allowed": False,
        "network_disabled_during_api_and_agent_execution": provider_name == "mock",
        "source_database": {
            "path": str(SOURCE_DB.relative_to(REPO_ROOT)),
            "digest": _file_digest(SOURCE_DB),
            "modified": False,
            "copied_database_path": str((TARGET_DIR / "pokiequant-live.db").relative_to(REPO_ROOT)),
            "migration_baseline_stamp": PRE_HEAD_REVISION,
            "migration_target": "head",
        },
        "workspace_isolation": {
            "one_workspace_per_question": True,
            "research_memory_order_contamination": False,
            "copy_method": "existing v2 CSV import boundary",
            "copied_data_source_kind": "csv_upload",
            "fresh_provider_fetch": False,
        },
        "preregistration": preregistration,
        "preregistration_digest": _json_digest(preregistration),
        "source_dataset_facts": source_dataset_facts,
        "fixed_wizard_baseline": BASELINE,
        "agent_ui_proxy": AGENT_UI_PROXY,
        "historical_deepseek_sentinels": _safe_historical_sentinels(),
        "results": results,
        "aggregate": _aggregate(results),
        "total_wall_time_seconds": round(time.monotonic() - started, 6),
        "limitations": [
            "No target user supplied a question or data.",
            "No person used either workflow and no active human time was measured.",
            "The fixed wizard was not executed; only its preregistered orchestration "
            "cost was modeled.",
            (
                "The Agent used deterministic Mock decisions, not a fresh DeepSeek call."
                if provider_name == "mock"
                else "The Agent used fresh DeepSeek calls, but no human operated either path."
            ),
            "Time-to-first-evidence is an engine timestamp, not perceived UI latency.",
            "The same two retained BTCUSDT datasets were reused across isolated workspaces.",
        ],
    }
    _assert_safe_payload(payload)
    return payload


def _publish(staging_dir: Path, payload: dict[str, Any]) -> None:
    _atomic_write(
        staging_dir / EVIDENCE_NAME,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write(staging_dir / REPORT_NAME, _markdown(payload))
    backup = TARGET_DIR.with_name(TARGET_DIR.name + ".backup-" + uuid4().hex)
    if TARGET_DIR.exists():
        TARGET_DIR.replace(backup)
    try:
        staging_dir.replace(TARGET_DIR)
    except Exception:
        if backup.exists() and not TARGET_DIR.exists():
            backup.replace(TARGET_DIR)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def _refresh_existing_evidence() -> dict[str, Any]:
    evidence_path = TARGET_DIR / EVIDENCE_NAME
    if not evidence_path.is_file():
        raise RuntimeError("No completed validation evidence exists to refresh.")
    payload = json.loads(evidence_path.read_text())
    provider_name = str(payload.get("configured_provider") or "")
    if provider_name not in {"mock", "deepseek"}:
        raise RuntimeError("Existing validation evidence has an unknown provider.")
    _configure_environment(TARGET_DIR, provider_name)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from services.api.app.db.session import reset_database_caches
    from services.api.app.modules.quant.store import QuantStore

    reset_database_caches()
    for row in payload["results"]:
        store = QuantStore()
        run = store.get_run(workspace_id=row["workspace_id"], run_id=row["run_id"])
        events = store.events_for_run(workspace_id=row["workspace_id"], run_id=row["run_id"])
        experiments = sorted(
            store.experiments_for_run(workspace_id=row["workspace_id"], run_id=row["run_id"]),
            key=lambda item: item.ordinal,
        )
        artifacts = store.artifacts_for_run(workspace_id=row["workspace_id"], run_id=row["run_id"])
        comparisons = sorted(
            (
                item
                for item in artifacts
                if item.kind.value == "validation_report"
                and item.content.get("evaluation_partition") == "train"
            ),
            key=lambda item: item.ordinal,
        )
        latest_training_comparison = comparisons[-1] if comparisons else None
        feedback_artifacts = [item for item in artifacts if item.kind.value == "iteration_feedback"]
        feedback_c = experiments[2] if len(experiments) >= 3 else None
        prior_keys = {
            item.candidate_key for item in experiments[:2] if item.candidate_key is not None
        }
        c_distinct = bool(
            feedback_c is not None
            and len(experiments) == 3
            and all(item.state == "completed" for item in experiments)
            and feedback_c.feedback_artifact_id
            and feedback_c.replan_decision is not None
            and feedback_c.candidate_key
            and feedback_c.candidate_key not in prior_keys
            and len(feedback_artifacts) == 1
            and feedback_c.feedback_artifact_id == feedback_artifacts[0].id
        )
        comparison_candidate_ids = (
            {
                str(item.get("candidate_id"))
                for item in latest_training_comparison.content.get("candidates", [])
                if isinstance(item, dict) and item.get("candidate_id")
            }
            if latest_training_comparison is not None
            else set()
        )
        final_comparison = (
            latest_training_comparison
            if c_distinct and comparison_candidate_ids == {item.id for item in experiments}
            else None
        )
        reports = [item for item in artifacts if item.kind.value == "research_report"]
        report = reports[0] if len(reports) == 1 else None
        ranking = (
            final_comparison.content.get("ranking", []) if final_comparison is not None else []
        )
        selected_id = report.content.get("selected_candidate_id") if report is not None else None
        c_useful = bool(
            c_distinct
            and feedback_c is not None
            and ranking
            and (ranking[0] == feedback_c.id or selected_id == feedback_c.id)
        )
        action_events = [
            event
            for event in events
            if _event_value(event, "event_type") == "agent.action_selected"
        ]
        system_actions = sum(
            str(_event_value(event, "payload").get("decision_summary", "")).startswith(
                (
                    "Compare the two completed base candidates",
                    "Finish safely because the Agent iteration budget",
                )
            )
            for event in action_events
        )
        row.pop("provider_decision_call_count", None)
        row.pop("provider_successful_decision_count", None)
        row.pop("system_decision_count", None)
        row["provider_api_request_count"] = None
        row["model_or_server_decision_event_count"] = len(action_events)
        row["server_forced_decision_event_count"] = system_actions
        failure_modes, failure_event_counts = _failure_modes(events)
        row["failure_modes"] = failure_modes
        row["failure_event_counts"] = failure_event_counts
        row["feedback_c"] = {
            "present": feedback_c is not None,
            "feedback_linked": bool(feedback_c is not None and feedback_c.feedback_artifact_id),
            "replan_decision_present": bool(
                feedback_c is not None and feedback_c.replan_decision is not None
            ),
            "canonical_distinct": c_distinct,
            "useful": c_useful,
        }
        row["final_comparison_present"] = final_comparison is not None
        row["final_comparison_candidate_count"] = (
            len(final_comparison.content.get("candidates", []))
            if final_comparison is not None
            else 0
        )
        objective_adherence, decision_basis, override_reason = _objective_adherent(
            run=run,
            final_comparison=final_comparison,
            report=report,
            expected_objective=row["expected_objective"],
        )
        row["objective_adherence"] = objective_adherence
        row["decision_basis"] = decision_basis
        row["override_reason"] = override_reason
        readiness_score, readiness_checks = _readiness(
            run=run,
            dataset=row["dataset"],
            experiments=experiments,
            artifacts=artifacts,
            final_comparison=final_comparison,
            report=report,
        )
        row["readiness"] = {
            "score": readiness_score,
            "possible": 7,
            "checks": readiness_checks,
        }
        row["time_to_first_evidence_seconds"] = _first_evidence_seconds(run, events)
        row["terminal_within_12_action_boundary"] = bool(
            run.state.value in TERMINAL_STATES and row["bounded_action_polls"] <= 12
        )
        row["budget_exhausted_nonterminal"] = bool(
            run.state.value not in TERMINAL_STATES
            and run.agent_iteration >= run.max_agent_iterations
        )
        row["next_system_budget_finish_not_executed"] = row["budget_exhausted_nonterminal"]
    payload["aggregate"] = _aggregate(payload["results"])
    payload["derived_fields_refreshed_at_utc"] = datetime.now(UTC).isoformat()
    _assert_safe_payload(payload)
    _atomic_write(evidence_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _atomic_write(TARGET_DIR / REPORT_NAME, _markdown(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="rerun in staging and atomically replace prior completed evidence on success",
    )
    parser.add_argument(
        "--provider",
        choices=("mock", "deepseek"),
        default="mock",
        help="Mock is an offline dry-run; DeepSeek reads only Keychain service pokiequant.deepseek",
    )
    parser.add_argument(
        "--refresh-existing-evidence",
        action="store_true",
        help="recompute safe derived counts/timing from the existing copied database; run no Agent",
    )
    args = parser.parse_args()
    if args.refresh_existing_evidence:
        payload = _refresh_existing_evidence()
        print(
            json.dumps(
                {
                    "status": "refreshed_without_agent_execution",
                    "proxy_verdict": payload["aggregate"]["proxy_verdict"],
                    "completed_runs": payload["aggregate"]["completed_runs"],
                    "evidence": str(TARGET_DIR / EVIDENCE_NAME),
                },
                sort_keys=True,
            )
        )
        return 0
    existing_evidence = TARGET_DIR / EVIDENCE_NAME
    if TARGET_DIR.exists() and not args.reset:
        if existing_evidence.is_file():
            existing = json.loads(existing_evidence.read_text())
            if (
                existing.get("schema_version")
                == "pokiequant-agent-native-validation-engineering-proxy-v1"
                and len(existing.get("results", [])) == 8
            ):
                print(
                    json.dumps(
                        {
                            "status": "existing_complete_evidence",
                            "proxy_verdict": existing["aggregate"]["proxy_verdict"],
                            "scope_cap": existing["aggregate"]["scope_cap"],
                            "evidence": str(existing_evidence),
                        },
                        sort_keys=True,
                    )
                )
                return 0
        raise RuntimeError(f"Target exists without complete evidence: {TARGET_DIR}; use --reset.")

    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ.pop("POKIEQUANT_AGENT_API_KEY", None)
    credential_source = "none_mock_provider"
    if args.provider == "deepseek":
        _load_deepseek_key_from_keychain()
        credential_source = "macos_keychain:pokiequant.deepseek"
    staging_dir = TARGET_DIR.with_name(TARGET_DIR.name + ".staging-" + uuid4().hex)
    try:
        payload = _run_proxy(
            staging_dir,
            provider_name=args.provider,
            credential_source=credential_source,
        )
        _publish(staging_dir, payload)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ.pop("POKIEQUANT_AGENT_API_KEY", None)
    print(
        json.dumps(
            {
                "proxy_verdict": payload["aggregate"]["proxy_verdict"],
                "scope_cap": payload["aggregate"]["scope_cap"],
                "user_effort_claim": payload["aggregate"]["user_effort_claim"],
                "completed_runs": payload["aggregate"]["completed_runs"],
                "total_wall_time_seconds": payload["total_wall_time_seconds"],
                "evidence": str(TARGET_DIR / EVIDENCE_NAME),
                "report": str(TARGET_DIR / REPORT_NAME),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
