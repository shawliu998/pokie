from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from services.api.app.db.models import (
    CollectionRun,
    Investigation,
    InvestigationScopeVersion,
    ResearchRun,
    Signal,
)
from services.api.app.db.session import get_session_factory
from tests.conftest import command_headers, query_headers


def _workspace(client: TestClient, principal_id: str, name: str) -> dict[str, Any]:
    response = client.post(
        "/v1/workspaces",
        headers=command_headers(principal_id),
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _project(client: TestClient, principal_id: str, workspace_id: str) -> dict[str, Any]:
    response = client.post(
        "/v1/projects",
        headers=command_headers(principal_id, workspace_id),
        json={"name": "Pagination project"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _source(client: TestClient, principal_id: str, workspace_id: str, name: str) -> dict[str, Any]:
    response = client.post(
        "/v1/sources",
        headers=command_headers(principal_id, workspace_id),
        json={
            "name": name,
            "source_kind": "imported_dataset",
            "runtime": "static_import",
            "connector_type": "csv",
            "connector_version": "1.0.0",
            "data_scope": "workspace_confidential",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _watchlist(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    project_id: str,
    source_id: str,
) -> dict[str, Any]:
    response = client.post(
        "/v1/watchlists",
        headers=command_headers(principal_id, workspace_id),
        json={
            "project_id": project_id,
            "name": "Pagination watchlist",
            "objective": "Exercise stable pagination",
            "source_connection_ids": [source_id],
            "rules": {
                "entities": ["Glint"],
                "query_rules": {"include_terms": ["pagination"]},
                "cadence": "manual",
                "current_window_days": 7,
                "baseline_window_days": 28,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _all_pages(
    client: TestClient, path: str, headers: dict[str, str], *, limit: int = 2
) -> tuple[list[str], list[str]]:
    ids: list[str] = []
    cursors: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get(path, headers=headers, params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        ids.extend(item["id"] for item in page["items"])
        cursor = page["page"]["next_cursor"]
        if cursor is not None:
            cursors.append(cursor)
        if not page["page"]["has_more"]:
            assert cursor is None
            return ids, cursors


def test_source_keyset_pages_are_complete_and_workspace_bound(
    client: TestClient, principal_id: str
) -> None:
    first = _workspace(client, principal_id, "First workspace")
    second = _workspace(client, principal_id, "Second workspace")
    expected = {
        _source(client, principal_id, first["id"], f"Source {index}")["id"] for index in range(5)
    }
    _source(client, principal_id, second["id"], "Other tenant source")

    ids, cursors = _all_pages(client, "/v1/sources", query_headers(principal_id, first["id"]))
    assert len(ids) == len(set(ids)) == 5
    assert set(ids) == expected
    assert cursors

    cross_workspace = client.get(
        "/v1/sources",
        headers=query_headers(principal_id, second["id"]),
        params={"cursor": cursors[0], "limit": 2},
    )
    assert cross_workspace.status_code == 422
    assert cross_workspace.json()["error"]["code"] == "VALIDATION_ERROR"


def test_signal_collection_and_research_run_keysets_have_no_gaps(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, "Run pagination")
    workspace_id = workspace["id"]
    project = _project(client, principal_id, workspace_id)
    source = _source(client, principal_id, workspace_id, "Run input")
    watchlist = _watchlist(client, principal_id, workspace_id, project["id"], source["id"])
    tied_at = datetime.now(UTC).replace(microsecond=0)
    signal_ids = [f"00000000-0000-4000-8000-{index:012d}" for index in range(1, 6)]
    collection_ids = [f"10000000-0000-4000-8000-{index:012d}" for index in range(1, 6)]
    run_ids = [f"20000000-0000-4000-8000-{index:012d}" for index in range(1, 6)]
    with get_session_factory()() as db:
        signals = [
            Signal(
                id=signal_id,
                workspace_id=workspace_id,
                watchlist_id=watchlist["id"],
                title=f"Signal {index}",
                explanation="Stable pagination fixture.",
                created_at=tied_at,
                updated_at=tied_at,
            )
            for index, signal_id in enumerate(signal_ids, start=1)
        ]
        db.add_all(signals)
        investigation = Investigation(
            workspace_id=workspace_id,
            project_id=project["id"],
            signal_id=signal_ids[0],
            status="active",
            owner_id=principal_id,
            created_at=tied_at,
            updated_at=tied_at,
        )
        db.add(investigation)
        db.flush()
        scope = InvestigationScopeVersion(
            workspace_id=workspace_id,
            investigation_id=investigation.id,
            version_number=1,
            decision_question="Does pagination preserve every row?",
            source_scope_json={"source_connection_ids": [source["id"]]},
            time_range_json={
                "start": (tied_at - timedelta(days=7)).isoformat(),
                "end": tied_at.isoformat(),
            },
            budget_json={"max_cost_usd": "1.0000", "max_duration_seconds": 60},
            stop_conditions=["Every page is observed."],
            created_by=principal_id,
            change_reason="Initial scope",
            created_at=tied_at,
        )
        db.add(scope)
        db.flush()
        investigation.current_scope_version_id = scope.id
        db.add_all(
            [
                ResearchRun(
                    id=run_id,
                    workspace_id=workspace_id,
                    investigation_id=investigation.id,
                    investigation_scope_version_id=scope.id,
                    state="queued",
                    run_input_manifest_json={},
                    run_input_manifest_digest="sha256:" + "a" * 64,
                    budget_json={"max_cost_usd": "1.0000", "max_duration_seconds": 60},
                    initiated_by=principal_id,
                    trace_id=f"trace-{index}",
                    created_at=tied_at,
                    updated_at=tied_at,
                )
                for index, run_id in enumerate(run_ids, start=1)
            ]
        )
        db.add_all(
            [
                CollectionRun(
                    id=run_id,
                    workspace_id=workspace_id,
                    watchlist_id=watchlist["id"],
                    source_connection_id=source["id"],
                    stable_key=f"pagination-{index}",
                    state="scheduled",
                    cadence="manual",
                    timezone="UTC",
                    scheduled_for=tied_at,
                    input_window_json={
                        "start": (tied_at - timedelta(days=1)).isoformat(),
                        "end": tied_at.isoformat(),
                    },
                    counters_json={},
                    freshness_json={"state": "never"},
                    created_at=tied_at,
                    updated_at=tied_at,
                )
                for index, run_id in enumerate(collection_ids, start=1)
            ]
        )
        db.commit()

    headers = query_headers(principal_id, workspace_id)
    for path, expected in (
        ("/v1/signals", set(signal_ids)),
        ("/v1/collection-runs", set(collection_ids)),
        ("/v1/research-runs", set(run_ids)),
    ):
        ids, cursors = _all_pages(client, path, headers)
        assert len(ids) == len(set(ids)) == 5
        assert set(ids) == expected
        assert cursors

    signal_first_page = client.get("/v1/signals", headers=headers, params={"limit": 2}).json()
    wrong_resource = client.get(
        "/v1/research-runs",
        headers=headers,
        params={"cursor": signal_first_page["page"]["next_cursor"], "limit": 2},
    )
    assert wrong_resource.status_code == 422
