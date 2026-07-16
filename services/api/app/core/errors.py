from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def error_response(error: ApiError, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": request_id,
                "details": error.details,
            }
        },
        headers={"X-Request-ID": request_id},
    )


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unavailable")
    return error_response(error, request_id)


def not_found(resource: str = "Resource") -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{resource} was not found.")


def invalid_state(message: str) -> ApiError:
    return ApiError(409, "INVALID_STATE", message)


def version_conflict(resource_id: str, current_row_version: int) -> ApiError:
    return ApiError(
        412,
        "VERSION_CONFLICT",
        "The resource has changed; refresh before continuing.",
        {"resource_id": resource_id, "current_row_version": current_row_version},
    )
