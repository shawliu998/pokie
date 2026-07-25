"""Small typed client for Qurio's authoritative quantitative API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import httpx
from pydantic import TypeAdapter

from .config import QurioConnection
from .models import (
    JsonObject,
    QurioArtifact,
    QurioDataset,
    QurioRun,
    StrategyExportPreviewRequest,
    StrategyExportPreviewResponse,
)

_DATASET_LIST = TypeAdapter(list[QurioDataset])
_RUN_LIST = TypeAdapter(list[QurioRun])
_JSON_OBJECT = TypeAdapter(dict[str, Any])


class QurioApiError(RuntimeError):
    """An HTTP or contract error returned by Qurio without leaking credentials."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


class QurioClient:
    """Synchronous, typed access to retained Qurio research evidence."""

    def __init__(
        self,
        connection: QurioConnection,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.connection = connection
        self._client = httpx.Client(
            base_url=connection.api_url,
            headers={
                "Authorization": f"Bearer {connection.access_token}",
                "X-Workspace-ID": connection.workspace_id,
                "Accept": "application/json",
                "User-Agent": "qurio-python-sdk/0.1.0",
            },
            timeout=timeout,
            transport=transport,
            trust_env=False,
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> QurioClient:
        return cls(QurioConnection.from_env(), **kwargs)

    def __enter__(self) -> QurioClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def list_datasets(self) -> list[QurioDataset]:
        return _DATASET_LIST.validate_python(
            self._request("GET", "/v1/quant/datasets/v2")
        )

    def list_runs(
        self, *, project_id: UUID | str | None = None, limit: int = 50
    ) -> list[QurioRun]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        params: dict[str, str | int] = {"limit": limit}
        if project_id is not None:
            params["project_id"] = str(project_id)
        return _RUN_LIST.validate_python(
            self._request("GET", "/v1/quant/runs", params=params)
        )

    def get_run(self, run_id: UUID | str) -> QurioRun:
        return QurioRun.model_validate(
            self._request("GET", f"/v1/quant/runs/{run_id}")
        )

    def get_workspace_snapshot(self) -> JsonObject:
        return _JSON_OBJECT.validate_python(
            self._request("GET", "/v1/quant/workspace-snapshot")
        )

    def get_run_snapshot(self, run_id: UUID | str) -> JsonObject:
        return _JSON_OBJECT.validate_python(
            self._request("GET", f"/v1/quant/runs/{run_id}/workspace-snapshot")
        )

    def get_artifact(self, artifact_id: UUID | str) -> QurioArtifact:
        return QurioArtifact.model_validate(
            self._request("GET", f"/v1/quant/artifacts/{artifact_id}")
        )

    def preview_strategy_export(
        self, request: StrategyExportPreviewRequest
    ) -> StrategyExportPreviewResponse:
        return StrategyExportPreviewResponse.model_validate(
            self._request(
                "POST",
                "/v1/quant/strategy-report-exports/preview",
                json=request.model_dump(mode="json"),
            )
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: JsonObject | None = None,
    ) -> Any:
        try:
            response = self._client.request(method, path, params=params, json=json)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise self._api_error(exc.response) from None
        except (httpx.HTTPError, ValueError) as exc:
            raise QurioApiError(
                status_code=0,
                code="QURIO_CONNECTION_ERROR",
                message=str(exc),
            ) from None

    @staticmethod
    def _api_error(response: httpx.Response) -> QurioApiError:
        code = "QURIO_API_ERROR"
        message = f"Qurio returned HTTP {response.status_code}."
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                if isinstance(error.get("code"), str):
                    code = error["code"]
                if isinstance(error.get("message"), str):
                    message = error["message"]
        except ValueError:
            pass
        return QurioApiError(
            status_code=response.status_code,
            code=code,
            message=message,
        )
