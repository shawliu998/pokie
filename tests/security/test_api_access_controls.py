from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.db.models import WorkspaceMember
from services.api.app.db.session import get_session_factory
from tests.conftest import command_headers, query_headers
from tests.security.helpers import create_project, create_source, create_workspace


def test_owner_authorization_distinguishes_non_owner_from_unknown_member(
    client: TestClient,
) -> None:
    owner_id = str(uuid4())
    viewer_id = str(uuid4())
    outsider_id = str(uuid4())
    workspace = create_workspace(client, owner_id)

    with get_session_factory()() as db:
        db.add(
            WorkspaceMember(
                workspace_id=workspace["id"],
                user_id=viewer_id,
                role="viewer",
                status="active",
            )
        )
        db.commit()

    owner = client.get(
        f"/v1/workspaces/{workspace['id']}",
        headers=query_headers(owner_id, workspace["id"]),
    )
    viewer = client.get(
        f"/v1/workspaces/{workspace['id']}",
        headers=query_headers(viewer_id, workspace["id"]),
    )
    outsider = client.get(
        f"/v1/workspaces/{workspace['id']}",
        headers=query_headers(outsider_id, workspace["id"]),
    )
    unauthenticated = client.get(
        f"/v1/workspaces/{workspace['id']}",
        headers={"X-Workspace-ID": workspace["id"]},
    )

    assert owner.status_code == 200
    assert viewer.status_code == 403
    assert viewer.json()["error"]["code"] == "FORBIDDEN"
    assert outsider.status_code == 404
    assert outsider.json()["error"]["code"] == "NOT_FOUND"
    assert unauthenticated.status_code == 401


def test_resource_ids_and_list_queries_are_isolated_by_active_workspace(client: TestClient) -> None:
    principal_id = str(uuid4())
    workspace_a = create_workspace(client, principal_id, "Workspace A")
    workspace_b = create_workspace(client, principal_id, "Workspace B")
    project_a = create_project(client, principal_id, workspace_a["id"], "Project A")
    project_b = create_project(client, principal_id, workspace_b["id"], "Project B")
    source_a = create_source(client, principal_id, workspace_a["id"], "Source A")
    source_b = create_source(client, principal_id, workspace_b["id"], "Source B")

    cross_read = client.get(
        f"/v1/sources/{source_a['id']}",
        headers=query_headers(principal_id, workspace_b["id"]),
    )
    cross_mutation = client.post(
        f"/v1/sources/{source_a['id']}/activate",
        headers=command_headers(principal_id, workspace_b["id"]),
        json={
            "expected_row_version": source_a["row_version"],
            "reason": "Must not cross the active workspace",
        },
    )
    projects_a = client.get("/v1/projects", headers=query_headers(principal_id, workspace_a["id"]))
    projects_b = client.get("/v1/projects", headers=query_headers(principal_id, workspace_b["id"]))
    sources_a = client.get("/v1/sources", headers=query_headers(principal_id, workspace_a["id"]))
    sources_b = client.get("/v1/sources", headers=query_headers(principal_id, workspace_b["id"]))

    assert cross_read.status_code == 404
    assert cross_mutation.status_code == 404
    assert {item["id"] for item in projects_a.json()["items"]} == {project_a["id"]}
    assert {item["id"] for item in projects_b.json()["items"]} == {project_b["id"]}
    assert {item["id"] for item in sources_a.json()["items"]} == {source_a["id"]}
    assert {item["id"] for item in sources_b.json()["items"]} == {source_b["id"]}
    source_a_after = client.get(
        f"/v1/sources/{source_a['id']}",
        headers=query_headers(principal_id, workspace_a["id"]),
    ).json()
    assert source_a_after["row_version"] == source_a["row_version"]
