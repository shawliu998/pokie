from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import seed_runtime
from scripts.runtime_fixture_connector import AcceptanceConnector


class _ScheduleCaptured(Exception):
    pass


def test_verify_invokes_seed_as_repo_module_and_loads_brief_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    verify_script = (repo_root / "scripts" / "verify_phase1.sh").read_text()

    assert '"$PYTHON_BIN" -m scripts.seed_runtime' in verify_script
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from scripts.seed_runtime import brief_document_digest; "
                "print(brief_document_digest({"
                "'schema_version':'decision-brief-blocks-v1',"
                "'blocks':[{'id':'recommendation','type':'recommendation',"
                "'body':'Prototype the preview.',"
                "'recommendation_status':'accepted'}]}))"
            ),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.startswith("sha256:")


def test_acceptance_connector_publishes_inside_the_due_schedule_window() -> None:
    item = AcceptanceConnector("github-source", "github", "first").search("permission").items[0]

    assert item.published_at is not None
    assert item.captured_at - item.published_at == timedelta(hours=1)


def test_cloud_collection_uses_isolated_watchlist_and_defers_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = {
        "github": {"id": "github-source", "connector_type": "github"},
        "rss": {"id": "rss-source", "connector_type": "rss"},
    }
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_source(
        _base_url: str,
        _principal: str,
        _workspace: str,
        _name: str,
        connector_type: str,
    ) -> dict[str, Any]:
        return sources[connector_type]

    def fake_request(
        _base_url: str,
        method: str,
        path: str,
        *,
        principal: str,
        workspace: str,
        payload: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        del principal, workspace
        calls.append((method, path, payload))
        if method == "GET" and path == "/v1/watchlists":
            return 200, {}, {"items": []}
        if method == "POST" and path == "/v1/watchlists":
            assert payload is not None
            return (
                201,
                {},
                {
                    "id": "cloud-watchlist",
                    "project_id": payload["project_id"],
                    "status": "draft",
                    "row_version": 1,
                    "source_connection_ids": payload["source_connection_ids"],
                },
            )
        if method == "POST" and path == "/v1/watchlists/cloud-watchlist/activate":
            return (
                200,
                {},
                {
                    "id": "cloud-watchlist",
                    "project_id": "project-1",
                    "status": "active",
                    "row_version": 2,
                    "source_connection_ids": ["github-source", "rss-source"],
                },
            )
        if method == "GET" and path == "/v1/collection-schedules":
            return 200, {}, {"items": []}
        if method == "POST" and path == "/v1/collection-schedules":
            raise _ScheduleCaptured
        raise AssertionError(f"Unexpected seed request: {method} {path}")

    monkeypatch.setattr(seed_runtime, "ensure_cloud_source", fake_source)
    monkeypatch.setattr(seed_runtime, "request_json", fake_request)

    with pytest.raises(_ScheduleCaptured):
        seed_runtime.ensure_cloud_collection(
            "http://api.test",
            "owner-1",
            "workspace-1",
            {
                "id": "watchlist-1",
                "project_id": "project-1",
                "status": "active",
                "row_version": 3,
                "source_connection_ids": ["csv-source"],
            },
        )

    watchlist_payload = next(
        payload for method, path, payload in calls if method == "POST" and path == "/v1/watchlists"
    )
    assert watchlist_payload is not None
    assert watchlist_payload["project_id"] == "project-1"
    assert watchlist_payload["source_connection_ids"] == ["github-source", "rss-source"]
    assert not any(
        method == "PATCH" and path == "/v1/watchlists/watchlist-1" for method, path, _ in calls
    )

    schedule_payload = next(
        payload
        for method, path, payload in calls
        if method == "POST" and path == "/v1/collection-schedules"
    )
    assert schedule_payload is not None
    assert schedule_payload["watchlist_id"] == "cloud-watchlist"
    assert "current_window" not in schedule_payload["query_json"]
    assert "baseline_window" not in schedule_payload["query_json"]


def test_cloud_collection_reads_public_cross_source_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = {
        "github": {"id": "github-source", "connector_type": "github"},
        "rss": {"id": "rss-source", "connector_type": "rss"},
    }
    signal = {
        "id": "signal-1",
        "watchlist_id": "cloud-watchlist",
        "data_authenticity": "collected",
        "total_source_count": 2,
        "metrics": {"platform_count": 2},
        "dimensions": {},
        "cross_source_confirmation": True,
        "per_source_freshness": [
            {"source_connection_id": "github-source"},
            {"source_connection_id": "rss-source"},
        ],
        "trigger_rules": [
            "mention_count > 0",
            "duplicate_concentration < 0.75",
            "platform_count >= 2 for cross_source_confirmation",
        ],
    }

    def fake_source(
        _base_url: str,
        _principal: str,
        _workspace: str,
        _name: str,
        connector_type: str,
    ) -> dict[str, Any]:
        return sources[connector_type]

    def fake_request(
        _base_url: str,
        method: str,
        path: str,
        *,
        principal: str,
        workspace: str,
        payload: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        del principal, workspace, payload
        if method == "GET" and path == "/v1/watchlists":
            return (
                200,
                {},
                {
                    "items": [
                        {
                            "id": "cloud-watchlist",
                            "name": "P2 Acceptance Watchlist",
                            "project_id": "project-1",
                            "status": "active",
                            "row_version": 1,
                            "source_connection_ids": ["github-source", "rss-source"],
                        }
                    ]
                },
            )
        if method == "GET" and path == "/v1/collection-schedules":
            return 200, {}, {"items": []}
        if method == "POST" and path == "/v1/collection-schedules":
            return 201, {}, {"enabled": True}
        if method == "GET" and path == "/v1/collection-runs":
            return (
                200,
                {},
                {
                    "items": [
                        {
                            "source_connection_id": source["id"],
                            "watchlist_id": "cloud-watchlist",
                            "scheduled_for": "2999-01-01T00:00:00Z",
                            "state": "succeeded",
                            "counters": {"fetched": 1},
                            "freshness": {"state": "current"},
                        }
                        for source in sources.values()
                    ]
                },
            )
        if method == "GET" and path == "/v1/content-items":
            return (
                200,
                {},
                {
                    "items": [
                        {
                            "source_connection_id": source["id"],
                            "current_version_id": f"version-{source['id']}",
                        }
                        for source in sources.values()
                    ]
                },
            )
        if method == "GET" and path.startswith("/v1/content-versions/"):
            return 200, {}, {"data_authenticity": "collected"}
        if method == "GET" and path == "/v1/signals":
            return 200, {}, {"items": [signal]}
        if method == "GET" and path == "/v1/signals/signal-1/evidence":
            return (
                200,
                {},
                {
                    "items": [
                        {"independence_group_id": "github-group"},
                        {"independence_group_id": "rss-group"},
                    ]
                },
            )
        raise AssertionError(f"Unexpected seed request: {method} {path}")

    monkeypatch.setattr(seed_runtime, "ensure_cloud_source", fake_source)
    monkeypatch.setattr(seed_runtime, "request_json", fake_request)

    returned_sources, returned_signal = seed_runtime.ensure_cloud_collection(
        "http://api.test",
        "owner-1",
        "workspace-1",
        {"project_id": "project-1"},
    )

    assert {source["id"] for source in returned_sources} == {"github-source", "rss-source"}
    assert returned_signal == signal
