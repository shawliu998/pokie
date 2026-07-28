#!/usr/bin/env python3
"""Verify the Plan-approval Agent loop on an authorized Wind CSI300 export.

The verifier creates a fresh isolated Qurio runtime, imports the supplied CSV through
the public market-v2 contract, creates a Plan-first Run, explicitly approves the one
bounded follow-up policy, and lets DeepSeek reach an honest terminal result with Mock
fallback disabled.

The original CSV and prior retained databases are read-only inputs. The generated E0
bundle and compact proof stay in the selected gitignored runtime directory. Credential
values are read from macOS Keychain only into this process and are never printed or
written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "qurio-wind-agent-loop-proof-v2"
MODEL = "deepseek-v4-flash"
SYMBOL = "000300.SH"
INTERVAL = "1D"
MARKET_CALENDAR = "XSHG"
EXPECTED_RAW_SHA256 = "99c6efb063e8668a0e043a3fd277725c7a58aa2042a4bd127a6ddd9ef8de1c1e"
RETRIEVED_AT = "2026-07-27T06:33:00Z"
SOURCE_REFERENCE = (
    "wind:000300.SH|get_index_kline|index_data|as_of=2026-07-24|"
    f"retrieved_at={RETRIEVED_AT}|sha256={EXPECTED_RAW_SHA256}"
)
APPROVAL_CONTRACT_VERSION = "quant-execution-boundary-approval-v1"
FOLLOW_UP_MODE = "one_train_only_follow_up"
MAX_VERSIONS = 2
MAX_EXPERIMENTS = 6
MAX_AGENT_ACTIONS = 24
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer",
        "csv_text",
        "database_path",
        "deepseek_api_key",
        "principal_id",
        "prompt",
        "provider_output",
        "raw_bars",
        "raw_csv",
        "secret",
        "token",
        "trace_id",
        "workspace_id",
    }
)


class ProofError(RuntimeError):
    """Closed verifier failure that does not contain provider or credential output."""

    def __init__(self, stage: str, code: str) -> None:
        self.stage = stage
        self.code = code
        super().__init__(f"{stage}: {code}")


def _fail(stage: str, code: str) -> NoReturn:
    raise ProofError(stage, code)


def _default_target() -> Path:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / ".run" / f"wind-agent-loop-deepseek-{stamp}"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(encoded)


def _prepare_target(target: Path) -> tuple[Path, Path, Path, Path]:
    resolved = target.expanduser().resolve()
    if resolved in {Path("/").resolve(), Path.home().resolve(), REPO_ROOT.resolve()}:
        _fail("target", "broad_target_refused")
    if resolved.exists():
        _fail("target", "target_already_exists")
    resolved.mkdir(parents=True, mode=0o700)
    objects = resolved / "objects"
    objects.mkdir(mode=0o700)
    return (
        resolved / "qurio-wind-agent-loop.db",
        objects,
        resolved / "strategy-evidence-bundle.json",
        resolved / "wind-agent-loop-proof.json",
    )


def _load_deepseek_key_from_keychain() -> None:
    account = os.environ.get("USER")
    if not account:
        _fail("credential", "user_unavailable")
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
        _fail("credential", "deepseek_keychain_entry_unavailable")
    os.environ["DEEPSEEK_API_KEY"] = secret


def _configure_runtime(
    *,
    database: Path,
    objects: Path,
    create_schema: bool,
    provider: str,
) -> None:
    os.environ.update(
        {
            "GLINT_ENVIRONMENT": "development",
            "GLINT_SERVICE_ROLE": "api",
            "GLINT_DATABASE_URL": f"sqlite:///{database}",
            "GLINT_OBJECT_STORE_BACKEND": "filesystem",
            "GLINT_OBJECT_STORE_ROOT": str(objects),
            "GLINT_CREATE_SCHEMA_ON_STARTUP": "true" if create_schema else "false",
            "GLINT_ALLOWED_ORIGINS": json.dumps(["tauri://localhost"]),
            "POKIEQUANT_AGENT_PROVIDER": provider,
            "POKIEQUANT_AGENT_MODEL": MODEL,
            "POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK": "false",
        }
    )
    os.environ.pop("POKIEQUANT_AGENT_BASE_URL", None)


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _response_json(response: Any, *, stage: str, status: int) -> Any:
    if response.status_code != status:
        code = f"http_{response.status_code}"
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                code = error["code"][:64]
    else:
        return response.json()
    _fail(stage, code)


def _find_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower()
            if normalized in FORBIDDEN_EVIDENCE_KEYS:
                return key
            nested = _find_forbidden_key(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_forbidden_key(item)
            if nested is not None:
                return nested
    elif isinstance(value, str) and (
        "/Users/" in value or "file://" in value or "Bearer " in value
    ):
        return "forbidden_string_value"
    return None


def _selected_candidate_id(snapshot: dict[str, Any]) -> str:
    report = snapshot.get("report")
    if not isinstance(report, dict):
        _fail("export", "report_missing")
    generalization = report.get("generalization")
    if isinstance(generalization, dict):
        selected = generalization.get("selectedCandidateId")
        if isinstance(selected, str) and selected:
            return selected
    selected = report.get("selectedCandidateId") or report.get("finalCandidateId")
    if isinstance(selected, str) and selected:
        return selected
    _fail("export", "selected_candidate_missing")


def _event_action_count(events: list[dict[str, Any]]) -> int:
    return sum(item.get("event_type") == "agent.action_selected" for item in events)


def _restore_probe(
    *,
    database: Path,
    objects: Path,
    workspace_id: str,
    root_run_id: str,
    expected_policy_digest: str,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--restore-only",
        "--database",
        str(database),
        "--objects",
        str(objects),
        "--workspace-id",
        workspace_id,
        "--root-run-id",
        root_run_id,
        "--expected-policy-digest",
        expected_policy_digest,
    ]
    environment = {**os.environ}
    environment.pop("DEEPSEEK_API_KEY", None)
    environment.pop("POKIEQUANT_AGENT_API_KEY", None)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if completed.returncode != 0:
        _fail("restore", "fresh_process_probe_failed")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        _fail("restore", "fresh_process_probe_invalid")
    if not isinstance(result, dict) or result.get("status") != "passed":
        _fail("restore", "fresh_process_probe_rejected")
    return result


def _run_restore_only(args: argparse.Namespace) -> int:
    if not all(
        (
            args.database,
            args.objects,
            args.workspace_id,
            args.root_run_id,
            args.expected_policy_digest,
        )
    ):
        _fail("restore", "restore_arguments_incomplete")
    database = args.database.expanduser().resolve()
    objects = args.objects.expanduser().resolve()
    _configure_runtime(
        database=database,
        objects=objects,
        create_schema=False,
        provider="mock",
    )
    from packages.contracts.quant import research_loop_policy_digest
    from services.api.app.modules.quant.store import QuantStore

    store = QuantStore()
    root = store.get_market_run(
        workspace_id=args.workspace_id,
        run_id=args.root_run_id,
    )
    if root.research_loop_policy is None:
        _fail("restore", "root_policy_missing")
    policy_digest = research_loop_policy_digest(root.research_loop_policy)
    if policy_digest != args.expected_policy_digest:
        _fail("restore", "root_policy_digest_changed")
    events = store.events_for_run(
        workspace_id=args.workspace_id,
        run_id=args.root_run_id,
    )
    approvals = [
        item
        for item in events
        if item["event_type"] == "plan.approved"
        and item["payload"].get("approval_contract_version") == APPROVAL_CONTRACT_VERSION
    ]
    if len(approvals) != 1:
        _fail("restore", "versioned_approval_event_missing")
    approval = approvals[0]["payload"]
    if (
        approval.get("execution_boundary") != "one_evidence_led_follow_up"
        or approval.get("research_loop_policy_digest") != policy_digest
    ):
        _fail("restore", "approval_projection_mismatch")
    plans = [
        item
        for item in store.artifacts_for_run(
            workspace_id=args.workspace_id,
            run_id=args.root_run_id,
        )
        if item.kind.value == "plan"
    ]
    if len(plans) != 1 or "research_loop" in plans[0].content:
        _fail("restore", "plan_artifact_execution_boundary_polluted")
    history = store.list_market_runs(workspace_id=args.workspace_id)
    if not 1 <= len(history) <= MAX_VERSIONS:
        _fail("restore", "history_version_budget_invalid")
    projected = [store.to_market_run_response(item) for item in history]
    root_projection = next(
        (item for item in projected if item["id"] == args.root_run_id),
        None,
    )
    if root_projection is None:
        _fail("restore", "root_history_projection_missing")
    if (
        root_projection["research_loop"]["follow_up_mode"] != FOLLOW_UP_MODE
        or root_projection["research_series"]["version_number"] != 1
        or root_projection["research_series"]["policy_digest"] != policy_digest
    ):
        _fail("restore", "root_history_projection_changed")
    versions = sorted(
        item["research_series"]["version_number"]
        for item in projected
        if item["research_series"] is not None
    )
    if versions not in ([1], [1, 2]):
        _fail("restore", "history_version_sequence_invalid")
    result = {
        "status": "passed",
        "approval_contract_version": approval["approval_contract_version"],
        "execution_boundary": approval["execution_boundary"],
        "history_count": len(history),
        "policy_digest": policy_digest,
        "series_versions": versions,
        "plan_artifact_unchanged": True,
    }
    sys.stdout.write(json.dumps(result, sort_keys=True))
    return 0


def _diagnose_provider() -> int:
    """Make one bounded Plan-contract diagnostic without retaining provider content."""

    _load_deepseek_key_from_keychain()
    os.environ.update(
        {
            "POKIEQUANT_AGENT_PROVIDER": "deepseek",
            "POKIEQUANT_AGENT_MODEL": MODEL,
            "POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK": "false",
        }
    )
    os.environ.pop("POKIEQUANT_AGENT_BASE_URL", None)
    from services.worker.app.quant_agent.provider import (
        QuantAgentProviderError,
        load_quant_agent_provider,
    )

    try:
        provider = load_quant_agent_provider()
        provider.plan(
            "Research simple interpretable CSI300 daily strategies under one bounded "
            "risk-adjusted comparison and return a valid executable plan."
        )
    except QuantAgentProviderError as exc:
        sys.stdout.write(
            json.dumps(
                {
                    "status": "failed",
                    "provider": "deepseek",
                    "model": MODEL,
                    "classification": exc.reason_code,
                },
                sort_keys=True,
            )
            + "\n"
        )
        return 1
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    sys.stdout.write(
        json.dumps(
            {
                "status": "passed",
                "provider": "deepseek",
                "model": MODEL,
                "classification": "plan_contract_compatible",
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def _diagnose_models_status() -> int:
    """Check only the authenticated model-directory HTTP status."""

    _load_deepseek_key_from_keychain()
    import httpx

    status_code = 0
    category = "transport_failed"
    try:
        response = httpx.get(
            "https://api.deepseek.com/models",
            headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
            timeout=10,
            trust_env=False,
        )
        status_code = response.status_code
        category = {
            200: "none",
            401: "authentication_failed",
            402: "billing_unavailable",
            403: "authentication_failed",
            429: "rate_limited",
        }.get(status_code, f"provider_http_{status_code}")
    except httpx.HTTPError:
        pass
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    sys.stdout.write(
        json.dumps(
            {
                "http_status": status_code,
                "error_category": category,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0 if status_code == 200 else 1


def run_proof(*, raw_csv: Path, target: Path) -> dict[str, Any]:
    raw_path = raw_csv.expanduser().resolve()
    if not raw_path.is_file():
        _fail("source", "raw_csv_missing")
    raw_bytes = raw_path.read_bytes()
    raw_digest = _sha256_bytes(raw_bytes)
    if raw_digest != EXPECTED_RAW_SHA256:
        _fail("source", "raw_csv_digest_mismatch")
    try:
        csv_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        _fail("source", "raw_csv_not_utf8")

    database, objects, bundle_path, proof_path = _prepare_target(target)
    _load_deepseek_key_from_keychain()
    _configure_runtime(
        database=database,
        objects=objects,
        create_schema=True,
        provider="deepseek",
    )

    from fastapi.testclient import TestClient

    from packages.contracts.quant import research_loop_policy_digest
    from services.api.app.core.config import get_settings
    from services.api.app.db.session import reset_database_caches
    from services.api.app.main import app
    from services.api.app.modules.quant.store import QuantStore
    from services.worker.app.pipelines.quant_agent import run_quant_agent_once

    get_settings.cache_clear()
    reset_database_caches()
    principal_id = str(uuid4())
    workspace_id = ""
    root_id = ""
    with TestClient(app) as client:
        workspace = _response_json(
            client.post(
                "/v1/workspaces",
                headers=_headers(principal_id),
                json={
                    "name": "Qurio Wind Agent-loop verification",
                    "data_region": "local",
                    "retention_policy_version": "retention-v1",
                },
            ),
            stage="workspace",
            status=201,
        )
        workspace_id = str(workspace["workspace_id"])
        dataset = _response_json(
            client.post(
                "/v1/quant/datasets/v2/import-csv",
                headers=_headers(principal_id, workspace_id),
                json={
                    "name": "CSI 300 · Wind daily",
                    "symbol": SYMBOL,
                    "interval": INTERVAL,
                    "market_calendar": MARKET_CALENDAR,
                    "csv_text": csv_text,
                    "file_name": raw_path.name,
                    "source_name": "Wind",
                    "source_reference": SOURCE_REFERENCE,
                },
            ),
            stage="dataset",
            status=201,
        )
        if (
            dataset["symbol"] != SYMBOL
            or dataset["interval"] != INTERVAL
            or dataset["bar_count"] != 619
            or dataset["periods_per_year"] != 252
            or dataset["quality"]["cadence_gap_count"] != 0
        ):
            _fail("dataset", "import_identity_mismatch")
        project = _response_json(
            client.post(
                "/v1/quant/projects",
                headers=_headers(principal_id, workspace_id),
                json={
                    "name": "Wind CSI300 bounded Agent-loop verification",
                    "objective": (
                        "Compare simple, interpretable long-or-cash strategies on retained "
                        "Wind CSI300 daily data and stop with an evidence-led conclusion."
                    ),
                },
            ),
            stage="project",
            status=201,
        )
        root = _response_json(
            client.post(
                "/v1/quant/market-runs",
                headers=_headers(principal_id, workspace_id),
                json={
                    "project_id": project["id"],
                    "mode": "plan",
                    "question": (
                        "Research simple trend, breakout, and mean-reversion candidates on "
                        "the pinned CSI300 daily dataset. Compare risk-adjusted return and "
                        "drawdown, permit at most one training-evidence-driven follow-up, "
                        "and stop honestly when evidence or novelty is insufficient."
                    ),
                    "expected_project_row_version": project["row_version"],
                    "dataset_id": dataset["dataset_id"],
                    "research_start_utc": dataset["covered_start"],
                    "research_end_utc": dataset["covered_end"],
                },
            ),
            stage="plan",
            status=201,
        )
        root_id = str(root["id"])
        if (
            root["mode"] != "plan"
            or root["state"] != "waiting_plan_approval"
            or root["research_loop"] is not None
            or root["research_series"] is not None
        ):
            _fail("plan", "unapproved_execution_boundary_invalid")
        approved = _response_json(
            client.post(
                f"/v1/quant/market-runs/{root_id}/approve-plan",
                headers=_headers(principal_id, workspace_id),
                json={
                    "expected_row_version": root["row_version"],
                    "plan_revision": root["plan_revision"],
                    "reason": "Approve one bounded training-evidence-led follow-up.",
                    "research_loop": {
                        "follow_up_mode": FOLLOW_UP_MODE,
                        "max_versions": MAX_VERSIONS,
                        "max_total_experiments": MAX_EXPERIMENTS,
                        "max_total_agent_actions": MAX_AGENT_ACTIONS,
                    },
                },
            ),
            stage="approval",
            status=200,
        )
        if (
            approved["mode"] != "auto"
            or approved["state"] != "running_experiments"
            or approved["research_loop"]["follow_up_mode"] != FOLLOW_UP_MODE
            or approved["research_series"]["version_number"] != 1
        ):
            _fail("approval", "approved_execution_boundary_invalid")
        expected_policy_digest = approved["research_series"]["policy_digest"]
        policy = QuantStore().get_market_run(
            workspace_id=workspace_id,
            run_id=root_id,
        ).research_loop_policy
        if policy is None or research_loop_policy_digest(policy) != expected_policy_digest:
            _fail("approval", "approved_policy_digest_invalid")

        worker_steps = 0
        while worker_steps < MAX_AGENT_ACTIONS:
            did_work = run_quant_agent_once(workspace_id=workspace_id)
            if not did_work:
                break
            worker_steps += 1
        runs = _response_json(
            client.get(
                "/v1/quant/market-runs",
                headers=_headers(principal_id, workspace_id),
            ),
            stage="history",
            status=200,
        )
        if not isinstance(runs, list) or not 1 <= len(runs) <= MAX_VERSIONS:
            _fail("history", "run_count_outside_budget")
        root_terminal = next((item for item in runs if item["id"] == root_id), None)
        if root_terminal is None or root_terminal["state"] != "completed":
            _fail("agent", "root_did_not_complete")
        if any(item["state"] not in TERMINAL_STATES for item in runs):
            _fail("agent", "series_not_terminal")
        children = [item for item in runs if item["parent_run_id"] == root_id]
        if len(children) > 1:
            _fail("agent", "more_than_one_follow_up")
        child = children[0] if children else None
        if child is not None and (
            child["state"] != "completed"
            or child["research_series"]["version_number"] != 2
            or child["research_series"]["remaining_versions"] != 0
        ):
            _fail("agent", "follow_up_identity_invalid")

        store = QuantStore()
        root_events = store.events_for_run(
            workspace_id=workspace_id,
            run_id=root_id,
        )
        child_events = (
            store.events_for_run(
                workspace_id=workspace_id,
                run_id=child["id"],
            )
            if child is not None
            else []
        )
        action_count = _event_action_count(root_events) + _event_action_count(child_events)
        if action_count > MAX_AGENT_ACTIONS or worker_steps > MAX_AGENT_ACTIONS:
            _fail("agent", "action_budget_exceeded")
        root_artifacts = store.artifacts_for_run(
            workspace_id=workspace_id,
            run_id=root_id,
        )
        root_plan = next((item for item in root_artifacts if item.kind.value == "plan"), None)
        root_report = next(
            (item for item in root_artifacts if item.kind.value == "research_report"),
            None,
        )
        if root_plan is None or "research_loop" in root_plan.content:
            _fail("approval", "plan_artifact_execution_boundary_polluted")
        if root_report is None:
            _fail("agent", "root_report_missing")
        generalization = root_report.content.get("generalization")
        if not isinstance(generalization, dict) or "holdout" not in generalization:
            _fail("agent", "root_holdout_missing")
        if child is not None:
            child_report = next(
                (
                    item
                    for item in store.artifacts_for_run(
                        workspace_id=workspace_id,
                        run_id=child["id"],
                    )
                    if item.kind.value == "research_report"
                ),
                None,
            )
            if child_report is None:
                _fail("agent", "child_report_missing")
            child_generalization = child_report.content.get("generalization")
            if (
                not isinstance(child_generalization, dict)
                or child_generalization.get("holdout_evidence_state") != "not_evaluated"
                or "holdout" in child_generalization
            ):
                _fail("agent", "child_holdout_boundary_invalid")

        snapshot = _response_json(
            client.get(
                f"/v1/quant/runs/{root_id}/workspace-snapshot",
                headers=_headers(principal_id, workspace_id),
            ),
            stage="snapshot",
            status=200,
        )
        selected_candidate_id = _selected_candidate_id(snapshot)
        export = _response_json(
            client.post(
                "/v1/quant/strategy-report-exports/preview",
                headers=_headers(principal_id, workspace_id),
                json={
                    "export_type": "strategy_evidence_bundle_json",
                    "run_id": root_id,
                    "candidate_id": selected_candidate_id,
                },
            ),
            stage="export",
            status=200,
        )
        try:
            bundle = json.loads(export["rendered_content"])
        except (KeyError, TypeError, json.JSONDecodeError):
            _fail("export", "e0_bundle_invalid")
        forbidden = _find_forbidden_key(bundle)
        if forbidden is not None:
            _fail("export", f"e0_forbidden_key_{forbidden[:32]}")
        if (
            bundle.get("run", {}).get("run_id") != root_id
            or bundle.get("selected_result", {}).get("candidate_id")
            != selected_candidate_id
        ):
            _fail("export", "e0_identity_mismatch")
        _write_json(bundle_path, bundle)

    restore = _restore_probe(
        database=database,
        objects=objects,
        workspace_id=workspace_id,
        root_run_id=root_id,
        expected_policy_digest=expected_policy_digest,
    )
    proof = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "claims": {
            "approval_time_agent_loop_verified": True,
            "fresh_deepseek_calls": True,
            "mock_fallback_used": False,
            "wind_api_connection": False,
            "live_market_feed": False,
            "alpha_claim": False,
            "investment_recommendation": False,
        },
        "dataset": {
            "source_provider": "Wind",
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "market_calendar": MARKET_CALENDAR,
            "periods_per_year": 252,
            "bar_count": 619,
            "raw_csv_sha256": raw_digest,
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["digest"],
            "record_digest": dataset["record_digest"],
            "cadence_gap_count": dataset["quality"]["cadence_gap_count"],
        },
        "approval": {
            "approval_contract_version": APPROVAL_CONTRACT_VERSION,
            "default_path_verified_before_approval": True,
            "execution_boundary": "one_evidence_led_follow_up",
            "follow_up_mode": FOLLOW_UP_MODE,
            "max_versions": MAX_VERSIONS,
            "max_total_experiments": MAX_EXPERIMENTS,
            "max_total_agent_actions": MAX_AGENT_ACTIONS,
            "policy_digest": expected_policy_digest,
            "plan_artifact_unchanged": True,
        },
        "outcome": {
            "provider": root_terminal["provider"],
            "model": root_terminal["model"],
            "root_run_id": root_id,
            "root_state": root_terminal["state"],
            "follow_up_selected": child is not None,
            "child_run_id": child["id"] if child is not None else None,
            "child_state": child["state"] if child is not None else None,
            "history_count": len(runs),
            "agent_action_count": action_count,
            "worker_step_count": worker_steps,
            "series_versions": restore["series_versions"],
        },
        "evidence_export": {
            "schema_version": bundle.get("schema_version"),
            "selected_candidate_id": selected_candidate_id,
            "content_sha256": _sha256_file(bundle_path),
            "forbidden_key_scan": "passed",
        },
        "fresh_restore": restore,
        "limitations": [
            "This is an authorized exported-dataset verification, not a direct Wind API.",
            "It is not a live feed, alpha, profitability, or investment-recommendation claim.",
            "The raw CSV, retained database, provider credential, prompt, and provider output "
            "are not included in this proof.",
            "A real provider may honestly stop without selecting the optional follow-up.",
        ],
    }
    forbidden = _find_forbidden_key(proof)
    if forbidden is not None:
        _fail("proof", f"sanitized_proof_forbidden_key_{forbidden[:32]}")
    _write_json(proof_path, proof)
    return proof


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-csv", type=Path)
    parser.add_argument("--target", type=Path, default=_default_target())
    parser.add_argument("--restore-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--diagnose-provider", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--diagnose-models-status", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--database", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--objects", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--workspace-id", help=argparse.SUPPRESS)
    parser.add_argument("--root-run-id", help=argparse.SUPPRESS)
    parser.add_argument("--expected-policy-digest", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.diagnose_models_status:
            return _diagnose_models_status()
        if args.diagnose_provider:
            return _diagnose_provider()
        if args.restore_only:
            return _run_restore_only(args)
        if args.raw_csv is None:
            _fail("source", "raw_csv_argument_required")
        proof = run_proof(raw_csv=args.raw_csv, target=args.target)
    except ProofError as exc:
        sys.stderr.write(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "failed",
                    "stage": exc.stage,
                    "code": exc.code,
                },
                sort_keys=True,
            )
            + "\n"
        )
        return 1
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    sys.stdout.write(
        json.dumps(
            {
                "schema_version": proof["schema_version"],
                "status": proof["status"],
                "follow_up_selected": proof["outcome"]["follow_up_selected"],
                "history_count": proof["outcome"]["history_count"],
                "agent_action_count": proof["outcome"]["agent_action_count"],
                "fresh_restore": proof["fresh_restore"]["status"],
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
