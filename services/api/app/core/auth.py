from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.config import get_settings
from services.api.app.core.errors import ApiError
from services.api.app.db.models import WorkspaceMember
from services.api.app.db.session import get_db, set_rls_context


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    workspace_id: str
    principal_id: str
    role: str


bearer_scheme = HTTPBearer(auto_error=False, scheme_name="GlintAccessToken")


def _parse_uuid(value: str, code: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ApiError(401, code, "A valid UUID bearer principal is required.") from exc


def _decode_json_segment(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        result = json.loads(decoded)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApiError(401, "UNAUTHENTICATED", "The access token is invalid.") from exc
    if not isinstance(result, dict):
        raise ApiError(401, "UNAUTHENTICATED", "The access token is invalid.")
    return result


def _verify_signed_token(token: str) -> str:
    settings = get_settings()
    secret = settings.auth_hmac_secret
    if secret is None:
        raise ApiError(401, "UNAUTHENTICATED", "Signed access tokens are not configured.")
    parts = token.split(".")
    if len(parts) != 3:
        raise ApiError(401, "UNAUTHENTICATED", "The access token is invalid.")
    header = _decode_json_segment(parts[0])
    payload = _decode_json_segment(parts[1])
    if header.get("alg") != "HS256" or header.get("typ") not in {None, "JWT"}:
        raise ApiError(401, "UNAUTHENTICATED", "The access token algorithm is invalid.")
    expected = hmac.new(
        secret.get_secret_value().encode(),
        f"{parts[0]}.{parts[1]}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
    except (ValueError, UnicodeError) as exc:
        raise ApiError(401, "UNAUTHENTICATED", "The access token is invalid.") from exc
    if not hmac.compare_digest(actual, expected):
        raise ApiError(401, "UNAUTHENTICATED", "The access token signature is invalid.")
    expiry = payload.get("exp")
    issued_at = payload.get("iat")
    if not isinstance(expiry, int | float) or isinstance(expiry, bool):
        raise ApiError(401, "UNAUTHENTICATED", "The access token expiry is invalid.")
    if not isinstance(issued_at, int | float) or isinstance(issued_at, bool):
        raise ApiError(401, "UNAUTHENTICATED", "The access token issued-at time is invalid.")
    expiry_value = float(expiry)
    issued_at_value = float(issued_at)
    if expiry_value <= issued_at_value:
        raise ApiError(401, "UNAUTHENTICATED", "The access token lifetime is invalid.")
    if expiry_value - issued_at_value > settings.auth_max_token_lifetime_seconds:
        raise ApiError(401, "UNAUTHENTICATED", "The access token lifetime is too long.")
    now = datetime.now(UTC).timestamp()
    skew = settings.auth_clock_skew_seconds
    if issued_at_value > now + skew:
        raise ApiError(401, "UNAUTHENTICATED", "The access token issued-at time is in the future.")
    not_before = payload.get("nbf")
    if not_before is not None:
        if not isinstance(not_before, int | float) or isinstance(not_before, bool):
            raise ApiError(401, "UNAUTHENTICATED", "The access token not-before time is invalid.")
        if float(not_before) > now + skew:
            raise ApiError(401, "UNAUTHENTICATED", "The access token is not active yet.")
    if expiry_value <= now - skew:
        raise ApiError(401, "UNAUTHENTICATED", "The access token expired.")
    audience = payload.get("aud")
    if isinstance(audience, str):
        audiences = {audience}
    elif isinstance(audience, list) and all(isinstance(item, str) for item in audience):
        audiences = set(audience)
    else:
        raise ApiError(401, "UNAUTHENTICATED", "The access token audience is invalid.")
    if settings.auth_audience not in audiences:
        raise ApiError(401, "UNAUTHENTICATED", "The access token audience is invalid.")
    if settings.auth_issuer is not None and payload.get("iss") != settings.auth_issuer:
        raise ApiError(401, "UNAUTHENTICATED", "The access token issuer is invalid.")
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise ApiError(401, "UNAUTHENTICATED", "The access token subject is invalid.")
    return _parse_uuid(subject, "UNAUTHENTICATED")


def authenticate_authorization(authorization: str | None) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")
    token = authorization.removeprefix("Bearer ").strip()
    settings = get_settings()
    if settings.environment in {"test", "development"}:
        try:
            return Principal(_parse_uuid(token, "UNAUTHENTICATED"))
        except ApiError:
            pass
    return Principal(_verify_signed_token(token))


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    authorization = (
        f"{credentials.scheme} {credentials.credentials}" if credentials is not None else None
    )
    return authenticate_authorization(authorization)


def get_workspace_context(
    principal: Principal = Depends(get_principal),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    db: Session = Depends(get_db),
) -> WorkspaceContext:
    if x_workspace_id is None:
        raise ApiError(422, "WORKSPACE_REQUIRED", "X-Workspace-ID is required.")
    try:
        workspace_id = str(UUID(x_workspace_id))
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "X-Workspace-ID must be a UUID.") from exc
    set_rls_context(db, workspace_id, principal.user_id)
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == principal.user_id,
            WorkspaceMember.status == "active",
        )
    )
    if member is None:
        raise ApiError(404, "NOT_FOUND", "Workspace was not found.")
    return WorkspaceContext(workspace_id, principal.user_id, member.role)


def require_owner(context: WorkspaceContext = Depends(get_workspace_context)) -> WorkspaceContext:
    if context.role != "owner":
        raise ApiError(403, "FORBIDDEN", "Owner permission is required.")
    return context
