#!/usr/bin/env python3
"""Seed the smallest repeatable API-mode acceptance workspace through HTTP."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_PRINCIPAL = "22222222-2222-5222-8222-222222222222"
DEFAULT_WORKSPACE = "11111111-1111-5111-8111-111111111111"
CSV_BODY = (
    b"problem,quote\n"
    b"Permissions,Permission friction is rising across imported feedback\n"
    b"Pricing,Team plan is expensive\n"
)


class SeedError(RuntimeError):
    """Raised when the live API seed cannot establish an acceptance fixture."""


SOURCE_VALIDATION_ARTIFACTS: list[dict[str, Any]] = []


def digest(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def canonical_digest(value: Any) -> str:
    return digest(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    )


def api_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def brief_document_digest(value: dict[str, Any]) -> str:
    from packages.contracts.schemas.decisions import DecisionBriefBlockDocument

    normalized = DecisionBriefBlockDocument.model_validate(value).model_dump(mode="json")
    return canonical_digest(normalized)


def signed_token(
    subject: str,
    secret: str,
    audience: str,
    issuer: str | None,
    issued_at: int,
    expiry: int,
) -> str:
    def segment(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = segment({"alg": "HS256", "typ": "JWT"})
    claims: dict[str, Any] = {"aud": audience, "exp": expiry, "iat": issued_at, "sub": subject}
    if issuer is not None:
        claims["iss"] = issuer
    payload = segment(claims)
    signing_input = f"{header}.{payload}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    principal: str,
    workspace: str | None = None,
    payload: Any | None = None,
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], Any]:
    headers = {"Accept": "application/json"}
    if principal:
        headers["Authorization"] = f"Bearer {principal}"
    if workspace:
        headers["X-Workspace-ID"] = workspace
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    if body is not None and "Content-Type" not in headers:
        headers["Content-Type"] = "application/octet-stream"
    if method not in {"GET", "HEAD", "OPTIONS"}:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    headers.update(extra_headers or {})
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            if not raw:
                return response.status, response_headers, None
            return response.status, response_headers, json.loads(raw.decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SeedError(f"{method} {path} returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise SeedError(f"{method} {path} could not reach API: {error}") from error


def request_text(base_url: str, path: str, *, token: str, workspace: str) -> str:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
            "X-Workspace-ID": workspace,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode(errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise SeedError(f"GET {path} SSE stream failed: {error}") from error


def find_named(items: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(items, dict):
        return None
    rows = items.get("items")
    if not isinstance(rows, list):
        return None
    return next((row for row in rows if isinstance(row, dict) and row.get("name") == name), None)


def ensure_project(base_url: str, principal: str, workspace: str) -> dict[str, Any]:
    _, _, current = request_json(
        base_url, "GET", "/v1/projects", principal=principal, workspace=workspace
    )
    project = find_named(current, "P1 Acceptance")
    if project:
        return project
    _, _, project = request_json(
        base_url,
        "POST",
        "/v1/projects",
        principal=principal,
        workspace=workspace,
        payload={"name": "P1 Acceptance"},
    )
    return project


def ensure_source(base_url: str, principal: str, workspace: str) -> dict[str, Any]:
    _, _, current = request_json(
        base_url, "GET", "/v1/sources", principal=principal, workspace=workspace
    )
    source = find_named(current, "P1 Acceptance CSV")
    if source is None:
        _, _, source = request_json(
            base_url,
            "POST",
            "/v1/sources",
            principal=principal,
            workspace=workspace,
            payload={
                "name": "P1 Acceptance CSV",
                "source_kind": "imported_dataset",
                "runtime": "static_import",
                "connector_type": "csv",
                "connector_version": "1.0.0",
                "data_scope": "workspace_confidential",
            },
        )
    if source.get("status") == "draft":
        _, _, source = request_json(
            base_url,
            "POST",
            f"/v1/sources/{source['id']}/activate",
            principal=principal,
            workspace=workspace,
            payload={
                "expected_row_version": source["row_version"],
                "reason": "P1 runtime acceptance",
            },
        )
    return source


def ensure_watchlist(
    base_url: str, principal: str, workspace: str, project: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    _, _, current = request_json(
        base_url, "GET", "/v1/watchlists", principal=principal, workspace=workspace
    )
    watchlist = find_named(current, "P1 Acceptance Watchlist")
    if watchlist:
        if watchlist.get("status") == "draft":
            _, _, watchlist = request_json(
                base_url,
                "POST",
                f"/v1/watchlists/{watchlist['id']}/activate",
                principal=principal,
                workspace=workspace,
                payload={
                    "expected_row_version": watchlist["row_version"],
                    "reason": "P1 runtime acceptance",
                },
            )
        return watchlist
    _, _, watchlist = request_json(
        base_url,
        "POST",
        "/v1/watchlists",
        principal=principal,
        workspace=workspace,
        payload={
            "project_id": project["id"],
            "name": "P1 Acceptance Watchlist",
            "objective": (
                "Verify the API-mode runtime path from imported feedback to a terminal brief."
            ),
            "source_connection_ids": [source["id"]],
            "rules": {
                "entities": ["Permission"],
                "query_rules": {
                    "include_terms": ["permission"],
                    "exclude_terms": [],
                    "languages": [],
                    "regions": [],
                },
                "cadence": "manual",
                "current_window_days": 7,
                "baseline_window_days": 28,
            },
        },
    )
    if watchlist.get("status") in {"draft", "paused"}:
        _, _, watchlist = request_json(
            base_url,
            "POST",
            f"/v1/watchlists/{watchlist['id']}/activate",
            principal=principal,
            workspace=workspace,
            payload={
                "expected_row_version": watchlist["row_version"],
                "reason": "P1 runtime acceptance",
            },
        )
    return watchlist


def process_import(
    base_url: str, principal: str, workspace: str, source: dict[str, Any]
) -> dict[str, Any]:
    body_digest = digest(CSV_BODY)
    _, _, session = request_json(
        base_url,
        "POST",
        "/v1/imports",
        principal=principal,
        workspace=workspace,
        payload={
            "source_connection_id": source["id"],
            "expected_source_row_version": source["row_version"],
            "expected_current_import_manifest_id": (
                source.get("current_import_manifest", {}) or {}
            ).get("id"),
            "local_manifest_digest": body_digest,
            "file_digest": body_digest,
            "expected_upload_digest": body_digest,
            "client_file_name": "p1-acceptance.csv",
            "file_size_bytes": len(CSV_BODY),
            "media_type": "text/csv",
            "parser_version": "csv-v1",
            "schema_version": "p1-acceptance-v1",
            "selected_scope_json": {"columns": ["problem", "quote"]},
            "selected_scope_digest": digest(b"problem,quote"),
        },
    )
    _, _, preview = request_json(
        base_url,
        "GET",
        f"/v1/imports/{session['id']}/upload-consent/preview"
        f"?expected_row_version={session['row_version']}",
        principal=principal,
        workspace=workspace,
    )
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    _, consent_headers, consent = request_json(
        base_url,
        "POST",
        f"/v1/imports/{session['id']}/upload-consent",
        principal=principal,
        workspace=workspace,
        payload={
            "preview_scope": preview["preview_scope"],
            "scope_digest": preview["scope_digest"],
            "expires_at": expires_at,
            "confirmation": True,
        },
    )
    grant = consent_headers.get("x-upload-grant")
    if not grant:
        raise SeedError("upload consent did not return X-Upload-Grant")
    session = consent["import_session"]
    _, _, uploaded = request_json(
        base_url,
        "PUT",
        f"/v1/imports/{session['id']}/object",
        principal=principal,
        workspace=workspace,
        body=CSV_BODY,
        extra_headers={"X-Upload-Grant": grant, "Content-Type": "text/csv"},
    )
    object_key = uploaded.get("object_key")
    if object_key != consent["upload"]["object_key"]:
        raise SeedError("uploaded object key does not match the consent scope")
    _, _, session = request_json(
        base_url,
        "POST",
        f"/v1/imports/{session['id']}/upload-complete",
        principal=principal,
        workspace=workspace,
        payload={
            "expected_row_version": session["row_version"],
            "object_key": object_key,
        },
    )
    _, _, job = request_json(
        base_url,
        "POST",
        f"/v1/imports/{session['id']}/finalize",
        principal=principal,
        workspace=workspace,
        payload={"expected_row_version": session["row_version"]},
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        _, _, current = request_json(
            base_url,
            "GET",
            f"/v1/import-finalization-jobs/{job['id']}",
            principal=principal,
            workspace=workspace,
        )
        if current["state"] == "completed":
            if not current.get("result_manifest_id"):
                raise SeedError("worker completed import job without a result manifest")
            return current
        if current["state"] == "failed":
            raise SeedError(f"worker failed import job: {current.get('failure_code')}")
        time.sleep(2)
    raise SeedError(f"worker did not process import job {job['id']} within 120 seconds")


def ensure_cloud_source(
    base_url: str, principal: str, workspace: str, name: str, connector_type: str
) -> dict[str, Any]:
    _, _, current = request_json(
        base_url, "GET", "/v1/sources", principal=principal, workspace=workspace
    )
    source = find_named(current, name)
    if source is None:
        source_config = (
            {
                "connector_type": "github",
                "repositories": [
                    {
                        "owner": "openai",
                        "repository": "glint",
                        "include_issues": True,
                        "include_discussions": False,
                        "include_releases": True,
                    }
                ],
            }
            if connector_type == "github"
            else {
                "connector_type": "rss",
                "feeds": [
                    {
                        "name": "P2 Acceptance RSS",
                        "feed_url": "https://example.test/glint-acceptance.xml",
                    }
                ],
            }
        )
        _, _, source = request_json(
            base_url,
            "POST",
            "/v1/sources",
            principal=principal,
            workspace=workspace,
            payload={
                "name": name,
                "source_kind": "cloud",
                "runtime": "cloud",
                "connector_type": connector_type,
                "connector_version": "acceptance-fixture-v1",
                "data_scope": "workspace_confidential",
                "credential_ref": "env://acceptance-github",
                "cadence": "daily",
                "timezone": "UTC",
                "source_config": source_config,
            },
        )
    if source.get("status") == "draft":
        _, _, source = request_json(
            base_url,
            "POST",
            f"/v1/sources/{source['id']}/activate",
            principal=principal,
            workspace=workspace,
            payload={
                "expected_row_version": source["row_version"],
                "reason": "Deterministic P2 collection fixture",
            },
        )
    if source.get("status") not in {"validating", "healthy", "degraded"}:
        raise SeedError(f"cloud source {name} is not schedulable: {source.get('status')}")
    _, _, validation_job = request_json(
        base_url,
        "POST",
        f"/v1/sources/{source['id']}/health-check",
        principal=principal,
        workspace=workspace,
        payload={
            "expected_row_version": source["row_version"],
            "reason": "Deterministic P2 source validation before scheduling",
        },
    )
    validation_job_id = validation_job.get("id")
    if not validation_job_id:
        raise SeedError(f"source validation for {name} did not return a job id")
    deadline = time.monotonic() + 120
    terminal_job: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        _, _, current_job = request_json(
            base_url,
            "GET",
            f"/v1/source-validation-jobs/{validation_job_id}",
            principal=principal,
            workspace=workspace,
        )
        state = current_job.get("state")
        if state in {"completed", "failed"}:
            terminal_job = current_job
            break
        time.sleep(2)
    if terminal_job is None:
        raise SeedError(
            f"source validation job {validation_job_id} for {name} did not reach a terminal state"
        )
    SOURCE_VALIDATION_ARTIFACTS.append(
        {
            "source_id": source["id"],
            "source_name": name,
            "job_id": validation_job_id,
            "state": terminal_job.get("state"),
            "result_source_status": terminal_job.get("result_source_status"),
        }
    )
    write_source_validation_artifact()
    if (
        terminal_job.get("state") != "completed"
        or terminal_job.get("result_source_status") != "healthy"
    ):
        raise SeedError(
            f"source validation job {validation_job_id} for {name} did not complete healthy"
        )
    _, _, refreshed_source = request_json(
        base_url,
        "GET",
        f"/v1/sources/{source['id']}",
        principal=principal,
        workspace=workspace,
    )
    health = refreshed_source.get("health") or {}
    if (
        refreshed_source.get("status") != "healthy"
        or health.get("state") != "healthy"
        or not health.get("checked_at")
    ):
        raise SeedError(
            f"source {name} did not refresh to healthy after validation job {validation_job_id}"
        )
    return refreshed_source


def write_source_validation_artifact() -> None:
    artifact_dir = os.environ.get("GLINT_ACCEPTANCE_ARTIFACT_DIR")
    if not artifact_dir:
        return
    os.makedirs(artifact_dir, mode=0o700, exist_ok=True)
    artifact_path = os.path.join(artifact_dir, "source-validation-jobs.json")
    with open(artifact_path, "w", encoding="utf-8") as output:
        json.dump(SOURCE_VALIDATION_ARTIFACTS, output, indent=2, sort_keys=True)
        output.write("\n")


def ensure_cloud_watchlist(
    base_url: str,
    principal: str,
    workspace: str,
    project_id: str,
    source_ids: list[str],
) -> dict[str, Any]:
    _, _, current = request_json(
        base_url, "GET", "/v1/watchlists", principal=principal, workspace=workspace
    )
    watchlist = find_named(current, "P2 Acceptance Watchlist")
    if watchlist is None:
        _, _, watchlist = request_json(
            base_url,
            "POST",
            "/v1/watchlists",
            principal=principal,
            workspace=workspace,
            payload={
                "project_id": project_id,
                "name": "P2 Acceptance Watchlist",
                "objective": (
                    "Verify cross-platform cloud collection without mixing the imported "
                    "P1 acceptance scope."
                ),
                "source_connection_ids": source_ids,
                "rules": {
                    "entities": ["Permission"],
                    "query_rules": {
                        "include_terms": ["permission"],
                        "exclude_terms": [],
                        "languages": [],
                        "regions": [],
                    },
                    "cadence": "daily",
                    "current_window_days": 7,
                    "baseline_window_days": 28,
                },
            },
        )
    elif set(watchlist.get("source_connection_ids", [])) != set(source_ids):
        _, _, watchlist = request_json(
            base_url,
            "PATCH",
            f"/v1/watchlists/{watchlist['id']}",
            principal=principal,
            workspace=workspace,
            payload={
                "source_connection_ids": source_ids,
                "expected_row_version": watchlist["row_version"],
            },
        )
    if watchlist.get("status") == "draft":
        _, _, watchlist = request_json(
            base_url,
            "POST",
            f"/v1/watchlists/{watchlist['id']}/activate",
            principal=principal,
            workspace=workspace,
            payload={
                "expected_row_version": watchlist["row_version"],
                "reason": "P2 runtime acceptance",
            },
        )
    if watchlist.get("status") != "active":
        raise SeedError("P2 acceptance Watchlist is not active")
    return watchlist


def ensure_cloud_collection(
    base_url: str,
    principal: str,
    workspace: str,
    watchlist: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sources = [
        ensure_cloud_source(base_url, principal, workspace, "P2 Acceptance GitHub", "github"),
        ensure_cloud_source(base_url, principal, workspace, "P2 Acceptance RSS", "rss"),
    ]
    source_ids = [source["id"] for source in sources]
    project_id = watchlist.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise SeedError("P1 acceptance Watchlist has no Project binding")
    watchlist = ensure_cloud_watchlist(base_url, principal, workspace, project_id, source_ids)
    now = datetime.now(UTC)
    due_at = now - timedelta(seconds=1)
    for source in sources:
        _, _, schedules = request_json(
            base_url, "GET", "/v1/collection-schedules", principal=principal, workspace=workspace
        )
        existing = next(
            (
                row
                for row in (schedules.get("items") or [])
                if row.get("source_connection_id") == source["id"]
                and row.get("watchlist_id") == watchlist["id"]
            ),
            None,
        )
        query_json = (
            {
                "owner": "openai",
                "repo": "glint",
                "query": "permission",
                "terms": ["permission"],
                "detector_version": "signal-v1",
                "max_pages": 1,
            }
            if source["connector_type"] == "github"
            else {
                "feed_url": "https://example.test/glint-acceptance.xml",
                "feed_title": "P2 Acceptance RSS",
                "query": "permission",
                "terms": ["permission"],
                "detector_version": "signal-v1",
                "max_pages": 1,
            }
        )
        schedule_payload = {
            "query_json": query_json,
            "cadence_seconds": 3600,
            "timezone": "UTC",
            "misfire_policy": "run_once",
            "catch_up": False,
            "overlap_policy": "skip",
            "next_run_at": due_at.isoformat(),
            "enabled": True,
        }
        if existing is None:
            _, _, schedule = request_json(
                base_url,
                "POST",
                "/v1/collection-schedules",
                principal=principal,
                workspace=workspace,
                payload={
                    "workspace_id": workspace,
                    "source_connection_id": source["id"],
                    "watchlist_id": watchlist["id"],
                    **schedule_payload,
                },
            )
        else:
            _, _, schedule = request_json(
                base_url,
                "PATCH",
                f"/v1/collection-schedules/{existing['id']}",
                principal=principal,
                workspace=workspace,
                payload={
                    **schedule_payload,
                    "expected_row_version": existing["row_version"],
                },
            )
        if not schedule.get("enabled"):
            raise SeedError(f"cloud collection schedule for {source['id']} is disabled")

    deadline = time.monotonic() + 120
    successful_runs: dict[str, dict[str, Any]] = {}
    while time.monotonic() < deadline:
        _, _, runs = request_json(
            base_url, "GET", "/v1/collection-runs", principal=principal, workspace=workspace
        )
        for row in runs.get("items") or []:
            source_id = row.get("source_connection_id")
            if (
                source_id in source_ids
                and row.get("watchlist_id") == watchlist["id"]
                and (api_datetime(row.get("scheduled_for")) or datetime.min.replace(tzinfo=UTC))
                >= due_at
                and row.get("state") in {"succeeded", "partial_success"}
                and row.get("counters", {}).get("fetched", 0) > 0
                and row.get("freshness", {}).get("state") == "current"
            ):
                successful_runs[source_id] = row
        if len(successful_runs) == len(source_ids):
            break
        time.sleep(2)
    if len(successful_runs) != len(source_ids):
        raise SeedError(
            "production worker did not complete both cloud CollectionRuns: "
            f"{sorted(successful_runs)} / {sorted(source_ids)}"
        )

    _, _, content_page = request_json(
        base_url, "GET", "/v1/content-items", principal=principal, workspace=workspace
    )
    cloud_items = [
        item
        for item in content_page.get("items") or []
        if item.get("source_connection_id") in source_ids and item.get("current_version_id")
    ]
    if {item["source_connection_id"] for item in cloud_items} != set(source_ids):
        raise SeedError(
            "cloud collection did not persist raw/content-version rows for both sources"
        )
    for item in cloud_items:
        _, _, version = request_json(
            base_url,
            "GET",
            f"/v1/content-versions/{item['current_version_id']}",
            principal=principal,
            workspace=workspace,
        )
        if version.get("data_authenticity") != "collected":
            raise SeedError("cloud ContentVersion was not marked collected")

    _, _, signal_page = request_json(
        base_url, "GET", "/v1/signals", principal=principal, workspace=workspace
    )
    signal = next(
        (
            row
            for row in signal_page.get("items") or []
            if row.get("data_authenticity") == "collected"
            and row.get("watchlist_id") == watchlist["id"]
            and row.get("total_source_count") == 2
            and row.get("metrics", {}).get("platform_count") == 2
            and {
                freshness.get("source_connection_id")
                for freshness in row.get("per_source_freshness", [])
            }
            >= set(source_ids)
        ),
        None,
    )
    if signal is None:
        raise SeedError(
            "cloud worker did not persist a cross-platform collected Signal "
            "with source_count=2 and platform_count=2"
        )
    if signal.get("cross_source_confirmation") is not True:
        raise SeedError("collected Signal did not expose cross_source_confirmation=true")
    required_trigger_rules = {
        "mention_count > 0",
        "duplicate_concentration < 0.75",
        "platform_count >= 2 for cross_source_confirmation",
    }
    if not required_trigger_rules.issubset(set(signal.get("trigger_rules") or [])):
        raise SeedError("collected Signal trigger policy is incomplete")
    _, _, evidence = request_json(
        base_url,
        "GET",
        f"/v1/signals/{signal['id']}/evidence",
        principal=principal,
        workspace=workspace,
    )
    evidence_items = evidence.get("items") or []
    if len(evidence_items) < 2 or any(
        not row.get("independence_group_id") for row in evidence_items
    ):
        raise SeedError("cloud SignalEvidence is missing independent lineage assignments")
    return sources, signal


def seed_terminal_brief(
    base_url: str,
    token: str,
    workspace: str,
    source: dict[str, Any],
    bootstrap: dict[str, Any],
    *,
    preferred_signal_id: str | None = None,
    source_scope_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    signals = bootstrap.get("signals") or []
    signal = next(
        (
            item
            for item in reversed(signals)
            if source["id"]
            in {row["source_connection_id"] for row in item.get("per_source_freshness", [])}
            and (preferred_signal_id is None or item.get("id") == preferred_signal_id)
        ),
        None,
    )
    if not signal:
        raise SeedError("cannot create terminal brief without an imported signal")
    if signal.get("status") == "new":
        dimensions = signal["dimensions"]
        _, _, signal = request_json(
            base_url,
            "POST",
            f"/v1/signals/{signal['id']}/triage",
            principal=token,
            workspace=workspace,
            payload={
                "expected_signal_row_version": signal["row_version"],
                "business_impact": {
                    "confirmed_level": "high",
                    "reason": "P1 runtime acceptance",
                    "expected_assessment_version": dimensions["business_impact"].get("version", 0),
                },
                "urgency": {
                    "confirmed_level": "this_week",
                    "reason": "P1 runtime acceptance",
                    "expected_assessment_version": dimensions["urgency"].get("version", 0),
                },
            },
        )
    _, _, content_page = request_json(
        base_url, "GET", "/v1/content-items", principal=token, workspace=workspace
    )
    scope_source_ids = {item["id"] for item in (source_scope_sources or [source])}
    version_ids = [
        item["current_version_id"]
        for item in content_page.get("items", [])
        if item.get("source_connection_id") in scope_source_ids and item.get("current_version_id")
    ]
    if not version_ids:
        raise SeedError("cannot create terminal brief without content versions")
    start = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    end = datetime.now(UTC).isoformat()
    common = {
        "source_scope": {
            "source_connection_ids": sorted(scope_source_ids),
            "content_version_ids": version_ids,
            "allow_cloud_model": False,
        },
        "time_range": {"start": start, "end": end},
        "budget": {"max_cost_usd": "4.0000", "max_duration_seconds": 900},
    }
    _, _, investigation = request_json(
        base_url,
        "POST",
        "/v1/investigations",
        principal=token,
        workspace=workspace,
        payload={
            "signal_id": signal["id"],
            "decision_question": "Should permission preview be prioritized?",
            **common,
            "stop_conditions": ["one verified claim"],
        },
    )
    active = investigation
    _, _, run = request_json(
        base_url,
        "POST",
        "/v1/research-runs",
        principal=token,
        workspace=workspace,
        payload={
            "investigation_id": active["id"],
            "investigation_scope_version_id": active["current_scope_version_id"],
            "question": active["decision_question"],
            **common,
            "expected_investigation_row_version": active["row_version"],
        },
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        _, _, current_run = request_json(
            base_url,
            "GET",
            f"/v1/research-runs/{run['id']}",
            principal=token,
            workspace=workspace,
        )
        if current_run["state"] == "completed":
            break
        if current_run["state"] in {"failed", "cancelled"}:
            raise SeedError(f"worker failed research run: {current_run['state']}")
        time.sleep(2)
    else:
        raise SeedError("worker did not complete the research run within 120 seconds")
    events = request_text(
        base_url,
        f"/v1/research-runs/{run['id']}/events",
        token=token,
        workspace=workspace,
    )
    if "run.completed" not in events or 'state":"completed"' not in events:
        raise SeedError("research SSE stream did not contain the terminal completed event")
    _, _, claim_page = request_json(
        base_url,
        "GET",
        f"/v1/claims?investigation_id={active['id']}",
        principal=token,
        workspace=workspace,
    )
    claim = (claim_page.get("items") or [None])[0]
    if not claim or not claim.get("evidence_links"):
        raise SeedError("completed research run did not produce a grounded claim")
    review_ids: list[str] = []
    for link in claim["evidence_links"]:
        _, _, review = request_json(
            base_url,
            "POST",
            f"/v1/evidence/{link['evidence_id']}/review",
            principal=token,
            workspace=workspace,
            payload={
                "decision": "valid",
                "reason": "P1 runtime acceptance",
                "policy_version": "evidence-review-v1",
            },
        )
        review_ids.append(review["id"])
    _, _, claim = request_json(
        base_url,
        "GET",
        f"/v1/claims/{claim['id']}",
        principal=token,
        workspace=workspace,
    )
    version = claim["current_version"]
    snapshot = {
        "claim_version_id": version["id"],
        "claim_evidence_ids": sorted(link["id"] for link in claim["evidence_links"]),
        "evidence_review_ids": sorted(review_ids),
    }
    request_json(
        base_url,
        "POST",
        f"/v1/claims/{claim['id']}/versions/{version['id']}/review",
        principal=token,
        workspace=workspace,
        payload={
            "claim_version_id": version["id"],
            "expected_claim_row_version": claim["row_version"],
            "decision": "verify",
            "evidence_review_ids": review_ids,
            "expected_claim_evidence_snapshot_digest": canonical_digest(snapshot),
            "reason": "P1 runtime acceptance",
        },
    )
    _, _, synthesis = request_json(
        base_url,
        "POST",
        f"/v1/investigations/{active['id']}/synthesis",
        principal=token,
        workspace=workspace,
        payload={"verified_claim_version_ids": [version["id"]]},
    )
    synthesis_version = synthesis["current_version"]
    request_json(
        base_url,
        "POST",
        f"/v1/investigations/{active['id']}/synthesis/versions/{synthesis_version['id']}/review",
        principal=token,
        workspace=workspace,
        payload={
            "synthesis_version_id": synthesis_version["id"],
            "expected_row_version": synthesis["row_version"],
            "decision": "verify",
            "reason": "P1 runtime acceptance",
            "policy_version": "synthesis-review-v1",
        },
    )
    _, _, brief = request_json(
        base_url,
        "POST",
        f"/v1/investigations/{active['id']}/decision-brief",
        principal=token,
        workspace=workspace,
        payload={
            "synthesis_version_id": synthesis_version["id"],
            "template_version": "decision-brief-v1",
        },
    )
    brief_version = brief["current_version"]
    document = brief_version["block_document"]
    for block in document["blocks"]:
        if block["type"] == "pm_judgment":
            block["body"] = "Prioritize a permission preview in the next planning cycle."
        elif block["type"] == "recommendation":
            block["body"] = "Prototype the permission preview."
            block["recommendation_status"] = "accepted"
    document["no_counter_evidence_search"] = {
        "queries": [
            "permission preview counter evidence",
            "permission execution onboarding objections",
        ],
        "source_connection_ids": sorted(scope_source_ids),
        "window_start": start,
        "window_end": end,
        "exclusion_criteria": ["Records outside the approved source scope."],
        "limitations": ["The acceptance fixture contains only the approved deterministic scope."],
    }
    _, _, brief = request_json(
        base_url,
        "PATCH",
        f"/v1/decision-briefs/{brief['id']}",
        principal=token,
        workspace=workspace,
        payload={
            "block_document": document,
            "expected_row_version": brief["row_version"],
            "human_edit_digest": brief_document_digest(document),
        },
    )
    brief_version = brief["current_version"]
    readiness_digest = canonical_digest(
        {
            "decision_brief_version_id": brief_version["id"],
            "block_document": brief_version["block_document"],
            "reference_snapshot": brief_version["reference_snapshot_json"],
            "policy_version": "decision-readiness-v1",
        }
    )
    request_json(
        base_url,
        "POST",
        f"/v1/decision-briefs/{brief['id']}/mark-decision-ready",
        principal=token,
        workspace=workspace,
        payload={
            "decision_brief_version_id": brief_version["id"],
            "expected_row_version": brief["row_version"],
            "decision": "mark_decision_ready",
            "reason": "P1 runtime acceptance",
            "policy_version": "decision-readiness-v1",
            "checklist_digest": readiness_digest,
        },
    )
    selected = [
        block["id"]
        for block in brief_version["block_document"]["blocks"]
        if block["type"] in {"fact", "pm_judgment", "recommendation"}
    ]
    _, _, preview = request_json(
        base_url,
        "POST",
        f"/v1/decision-briefs/{brief['id']}/exports/preview",
        principal=token,
        workspace=workspace,
        payload={
            "decision_brief_version_id": brief_version["id"],
            "export_type": "prd_research_input_markdown",
            "selection_manifest": {"block_ids": selected, "include_citations": True},
        },
    )
    _, _, export = request_json(
        base_url,
        "POST",
        f"/v1/decision-briefs/{brief['id']}/exports",
        principal=token,
        workspace=workspace,
        payload={
            "decision_brief_version_id": brief_version["id"],
            "export_type": "prd_research_input_markdown",
            "selection_manifest": {"block_ids": selected, "include_citations": True},
            "destination": "local_download",
            "reference_digest": preview["reference_digest"],
        },
    )
    if not export.get("id") or export.get("decision_brief_version_id") != brief_version["id"]:
        raise SeedError("terminal BriefExport did not bind to the exact ready brief version")
    return export


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--principal", default=os.environ.get("GLINT_AUTH_PRINCIPAL_ID", DEFAULT_PRINCIPAL)
    )
    parser.add_argument(
        "--workspace", default=os.environ.get("GLINT_AUTH_WORKSPACE_ID", DEFAULT_WORKSPACE)
    )
    parser.add_argument("--access-token", default=os.environ.get("GLINT_AUTH_ACCESS_TOKEN"))
    parser.add_argument("--auth-output", required=True)
    args = parser.parse_args()

    try:
        secret = os.environ.get("GLINT_AUTH_HMAC_SECRET")
        audience = os.environ.get("GLINT_AUTH_AUDIENCE", "glint-api")
        issuer = os.environ.get("GLINT_AUTH_ISSUER")
        token_ttl = int(os.environ.get("GLINT_AUTH_TOKEN_TTL_SECONDS", "300"))
        issued_at = int(datetime.now(UTC).timestamp())
        access_token = args.access_token
        if access_token is None:
            if not secret:
                raise SeedError(
                    "GLINT_AUTH_HMAC_SECRET is required to create the acceptance access token"
                )
            access_token = signed_token(
                args.principal,
                secret,
                audience,
                issuer,
                issued_at,
                issued_at + token_ttl,
            )
        if secret:
            expired_token = signed_token(
                args.principal,
                secret,
                audience,
                issuer,
                issued_at - token_ttl - 60,
                issued_at - 60,
            )
        else:
            expired_token = "expired-token-fixture"
        forged_parts = access_token.split(".")
        if len(forged_parts) == 3:
            replacement = "A" if forged_parts[2][:1] != "A" else "B"
            forged_token = f"{forged_parts[0]}.{forged_parts[1]}.{replacement}{forged_parts[2][1:]}"
        else:
            forged_token = f"{access_token}.forged"
        status, _, health = request_json(args.base_url, "GET", "/healthz", principal="")
        if status != 200 or not isinstance(health, dict) or health.get("status") != "ok":
            raise SeedError(f"API healthz is not ready: {health!r}")
        status, _, bootstrap = request_json(
            args.base_url,
            "GET",
            "/v1/sync/bootstrap",
            principal=access_token,
            workspace=args.workspace,
        )
        if status != 200 or not isinstance(bootstrap, dict):
            raise SeedError("API bootstrap did not return a workspace document")
        project = ensure_project(args.base_url, access_token, args.workspace)
        source = ensure_source(args.base_url, access_token, args.workspace)
        ensure_watchlist(args.base_url, access_token, args.workspace, project, source)
        job = process_import(args.base_url, access_token, args.workspace, source)
        _, _, final_bootstrap = request_json(
            args.base_url,
            "GET",
            "/v1/sync/bootstrap",
            principal=access_token,
            workspace=args.workspace,
        )
        sources = final_bootstrap.get("sources", [])
        signals = final_bootstrap.get("signals", [])
        seeded_source = next((item for item in sources if item.get("id") == source["id"]), None)
        if not seeded_source or not seeded_source.get("current_import_manifest"):
            raise SeedError("bootstrap has no terminal imported manifest after worker processing")
        if not signals:
            raise SeedError("bootstrap has no signal after worker processing")
        cloud_sources: list[dict[str, Any]] = []
        cloud_signal: dict[str, Any] | None = None
        if os.environ.get("GLINT_ACCEPTANCE_CLOUD_OWNER_LOOP") == "1":
            cloud_sources, cloud_signal = ensure_cloud_collection(
                args.base_url,
                access_token,
                args.workspace,
                watchlist=ensure_watchlist(
                    args.base_url, access_token, args.workspace, project, source
                ),
            )
            _, _, final_bootstrap = request_json(
                args.base_url,
                "GET",
                "/v1/sync/bootstrap",
                principal=access_token,
                workspace=args.workspace,
            )
            write_source_validation_artifact()
        export = seed_terminal_brief(
            args.base_url,
            access_token,
            args.workspace,
            cloud_sources[0] if cloud_sources else seeded_source,
            final_bootstrap,
            preferred_signal_id=cloud_signal.get("id") if cloud_signal else None,
            source_scope_sources=cloud_sources or None,
        )
        with open(args.auth_output, "w", encoding="utf-8") as output:
            json.dump(
                {
                    "access_token": access_token,
                    "forged_token": forged_token,
                    "expired_token": expired_token,
                    "principal": args.principal,
                    "workspace": args.workspace,
                    "cloud_signal": cloud_signal["id"] if cloud_signal else None,
                    "cloud_sources": [item["id"] for item in cloud_sources],
                },
                output,
                sort_keys=True,
            )
        print(
            f"seeded workspace={args.workspace} job={job['id']} "
            f"manifest={job['result_manifest_id']} export={export['id']}"
        )
        return 0
    except SeedError as error:
        print(f"runtime seed failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
