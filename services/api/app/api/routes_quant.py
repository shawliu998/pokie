from __future__ import annotations

from typing import Annotated, Any, Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from packages.contracts.quant import (
    QuantArtifactResponse,
    QuantExperimentResponse,
    QuantFixtureCommandRequest,
    QuantPlanApproveRequest,
    QuantPlanChangesRequest,
    QuantProjectCreateRequest,
    QuantProjectResponse,
    QuantRunCancelRequest,
    QuantRunCreateRequest,
    QuantRunEvent,
    QuantRunResponse,
    QuantRunRetryRequest,
    QuantStreamResetEvent,
    decode_quant_event,
    encode_quant_sse,
)
from services.api.app.core.auth import WorkspaceContext, require_owner
from services.api.app.core.errors import invalid_state
from services.api.app.modules.quant.store import get_quant_store
from services.api.app.modules.quant.snapshot import apply_fixture_command, quant_workspace_fixture

router = APIRouter(prefix="/v1/quant")
Ctx = Annotated[WorkspaceContext, Depends(require_owner)]


def _store():
    return get_quant_store()


@router.get("/workspace-snapshot")
def get_workspace_snapshot(context: Ctx) -> dict[str, Any]:
    # Dependency resolution is intentional: the fixture is still scoped behind
    # the authenticated workspace API even though its content is deterministic.
    return quant_workspace_fixture(workspace_id=context.workspace_id)


@router.post("/workspace-snapshot/commands")
def command_workspace_snapshot(
    body: QuantFixtureCommandRequest, context: Ctx
) -> dict[str, Any]:
    try:
        return apply_fixture_command(
            workspace_id=context.workspace_id,
            command=body.command,
            expected_row_version=body.expected_row_version,
        )
    except ValueError as exc:
        raise invalid_state(str(exc)) from exc


@router.post("/projects", response_model=QuantProjectResponse, status_code=201)
def create_project(body: QuantProjectCreateRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    project = store.create_project(
        workspace_id=context.workspace_id,
        name=body.name,
        objective=body.objective,
    )
    return QuantProjectResponse.model_validate(store.to_project_response(project)).model_dump(
        mode="json"
    )


@router.get("/projects", response_model=list[QuantProjectResponse])
def list_projects(context: Ctx) -> list[dict[str, Any]]:
    store = _store()
    return [
        QuantProjectResponse.model_validate(store.to_project_response(project)).model_dump(mode="json")
        for project in store.list_projects(workspace_id=context.workspace_id)
    ]


@router.get("/projects/{project_id}", response_model=QuantProjectResponse)
def get_project(project_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    project = store.get_project(workspace_id=context.workspace_id, project_id=str(project_id))
    return QuantProjectResponse.model_validate(store.to_project_response(project)).model_dump(
        mode="json"
    )


@router.post("/runs", response_model=QuantRunResponse, status_code=201)
def create_run(body: QuantRunCreateRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.create_run(
        workspace_id=context.workspace_id,
        project_id=str(body.project_id),
        question=body.question,
        mode=body.mode,
        expected_project_row_version=body.expected_project_row_version,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.get("/runs", response_model=list[QuantRunResponse])
def list_runs(
    context: Ctx,
    project_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    store = _store()
    runs = store.list_runs(workspace_id=context.workspace_id, project_id=str(project_id) if project_id else None)
    return [
        QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")
        for run in runs[:limit]
    ]


@router.get("/runs/{run_id}", response_model=QuantRunResponse)
def get_run(run_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.get_run(workspace_id=context.workspace_id, run_id=str(run_id))
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.post("/runs/{run_id}/approve-plan", response_model=QuantRunResponse)
def approve_plan(
    run_id: UUID, body: QuantPlanApproveRequest, context: Ctx
) -> dict[str, Any]:
    store = _store()
    run = store.approve_plan(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        plan_revision=body.plan_revision,
        reason=body.reason,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.post("/runs/{run_id}/request-plan-changes", response_model=QuantRunResponse)
def request_plan_changes(
    run_id: UUID, body: QuantPlanChangesRequest, context: Ctx
) -> dict[str, Any]:
    store = _store()
    run = store.request_plan_changes(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        plan_revision=body.plan_revision,
        change_request=body.change_request,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.post("/runs/{run_id}/cancel", response_model=QuantRunResponse)
def cancel_run(run_id: UUID, body: QuantRunCancelRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.cancel_run(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        reason=body.reason,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.post("/runs/{run_id}/retry", response_model=QuantRunResponse, status_code=201)
def retry_run(run_id: UUID, body: QuantRunRetryRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.retry_run(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        reason=body.reason,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.get("/runs/{run_id}/events")
def stream_run_events(
    run_id: UUID,
    context: Ctx,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    store = _store()
    run = store.get_run(workspace_id=context.workspace_id, run_id=str(run_id))
    after_sequence = 0
    if last_event_id:
        try:
            after_sequence = next(
                event["sequence"]
                for event in store.events_for_run(
                    workspace_id=context.workspace_id, run_id=str(run_id)
                )
                if event["event_id"] == last_event_id
            )
        except StopIteration:
            reset = QuantStreamResetEvent(
                snapshot_url=f"/v1/quant/runs/{run.id}",
                latest_sequence=run.latest_sequence,
            )
            return StreamingResponse(iter([encode_quant_sse(reset)]), media_type="text/event-stream")

    def generate() -> Iterator[str]:
        for event in store.events_for_run(
            workspace_id=context.workspace_id, run_id=str(run_id), after_sequence=after_sequence
        ):
            yield encode_quant_sse(decode_quant_event(event))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/artifacts", response_model=list[QuantArtifactResponse])
def list_artifacts(run_id: UUID, context: Ctx) -> list[dict[str, Any]]:
    store = _store()
    artifacts = store.artifacts_for_run(workspace_id=context.workspace_id, run_id=str(run_id))
    return [
        QuantArtifactResponse.model_validate(store.to_artifact_response(artifact)).model_dump(
            mode="json"
        )
        for artifact in artifacts
    ]


@router.get("/artifacts/{artifact_id}", response_model=QuantArtifactResponse)
def get_artifact(artifact_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    artifact = store.get_artifact(workspace_id=context.workspace_id, artifact_id=str(artifact_id))
    return QuantArtifactResponse.model_validate(store.to_artifact_response(artifact)).model_dump(
        mode="json"
    )


@router.get("/runs/{run_id}/experiments", response_model=list[QuantExperimentResponse])
def list_experiments(run_id: UUID, context: Ctx) -> list[dict[str, Any]]:
    store = _store()
    experiments = store.experiments_for_run(workspace_id=context.workspace_id, run_id=str(run_id))
    return [
        QuantExperimentResponse.model_validate(store.to_experiment_response(experiment)).model_dump(
            mode="json"
        )
        for experiment in experiments
    ]


@router.get("/experiments/{experiment_id}", response_model=QuantExperimentResponse)
def get_experiment(experiment_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    experiment = store.get_experiment(
        workspace_id=context.workspace_id, experiment_id=str(experiment_id)
    )
    return QuantExperimentResponse.model_validate(store.to_experiment_response(experiment)).model_dump(
        mode="json"
    )
