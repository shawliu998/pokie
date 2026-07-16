from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select

from services.api.app.core.auth import authenticate_authorization
from services.api.app.core.config import Settings
from services.api.app.core.errors import ApiError
from services.api.app.db.models import IdempotencyRecord
from services.api.app.db.session import get_session_factory

SECRET = "production-auth-test-secret-with-32-bytes"


def _settings() -> Settings:
    return Settings(
        environment="production",
        database_url="postgresql+psycopg://glint_api:password@localhost/glint",
        object_store_backend="s3",
        s3_endpoint_url="http://minio:9000",
        s3_bucket="glint",
        s3_access_key_id=SecretStr("access-id"),
        s3_secret_access_key=SecretStr("object-secret"),
        auth_hmac_secret=SecretStr(SECRET),
        auth_audience="glint-api",
        auth_issuer=None,
        allowed_origins=["http://localhost:3000"],
        create_schema_on_startup=False,
    )


def _segment(value: dict[str, object]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _decode_segment(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _token(
    subject: str,
    *,
    expiry: datetime,
    audience: str = "glint-api",
    issued_at: datetime | None = None,
    not_before: datetime | None = None,
) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    claims: dict[str, object] = {
        "sub": subject,
        "iat": (issued_at or datetime.now(UTC)).timestamp(),
        "exp": expiry.timestamp(),
        "aud": audience,
    }
    if not_before is not None:
        claims["nbf"] = not_before.timestamp()
    payload = _segment(claims)
    signature = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{payload}.{encoded_signature}"


def test_production_auth_verifies_signature_expiry_audience_and_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr("services.api.app.core.auth.get_settings", lambda: settings)
    subject = str(uuid4())
    future = datetime.now(UTC) + timedelta(minutes=5)
    assert authenticate_authorization(f"Bearer {_token(subject, expiry=future)}").user_id == subject

    valid = _token(subject, expiry=future)
    signing_input, encoded_signature = valid.rsplit(".", 1)
    forged_signature = ("A" if encoded_signature[0] != "A" else "B") + encoded_signature[1:]
    forged = f"{signing_input}.{forged_signature}"
    assert _decode_segment(forged_signature) != _decode_segment(encoded_signature)
    with pytest.raises(ApiError) as forged_error:
        authenticate_authorization(f"Bearer {forged}")
    assert forged_error.value.status_code == 401
    assert forged_error.value.code == "UNAUTHENTICATED"
    assert forged_error.value.message == "The access token signature is invalid."

    expired = _token(
        subject,
        issued_at=datetime.now(UTC) - timedelta(minutes=10),
        expiry=datetime.now(UTC) - timedelta(minutes=5),
    )
    wrong_audience = _token(subject, expiry=future, audience="some-other-api")
    for token in (expired, wrong_audience, subject):
        with pytest.raises(ApiError) as captured:
            authenticate_authorization(f"Bearer {token}")
        assert captured.value.status_code == 401


def test_production_auth_rejects_weak_secret_and_long_lived_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="32 bytes"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://glint_api:password@localhost/glint",
            object_store_backend="s3",
            s3_endpoint_url="http://minio:9000",
            s3_bucket="glint",
            s3_access_key_id=SecretStr("access-id"),
            s3_secret_access_key=SecretStr("object-secret"),
            auth_hmac_secret=SecretStr("weak-secret"),
            allowed_origins=["http://localhost:3000"],
        )
    with pytest.raises(ValidationError, match="high-entropy"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://glint_api:password@localhost/glint",
            object_store_backend="s3",
            s3_endpoint_url="http://minio:9000",
            s3_bucket="glint",
            s3_access_key_id=SecretStr("access-id"),
            s3_secret_access_key=SecretStr("object-secret"),
            auth_hmac_secret=SecretStr("a" * 32),
            allowed_origins=["http://localhost:3000"],
        )

    settings = _settings()
    monkeypatch.setattr("services.api.app.core.auth.get_settings", lambda: settings)
    subject = str(uuid4())
    now = datetime.now(UTC)
    invalid_tokens = (
        _token(subject, issued_at=now, expiry=now + timedelta(hours=1)),
        _token(
            subject,
            issued_at=now + timedelta(minutes=2),
            expiry=now + timedelta(minutes=7),
        ),
        _token(
            subject,
            issued_at=now,
            not_before=now + timedelta(minutes=2),
            expiry=now + timedelta(minutes=5),
        ),
    )
    for token in invalid_tokens:
        with pytest.raises(ApiError) as captured:
            authenticate_authorization(f"Bearer {token}")
        assert captured.value.status_code == 401


def test_invalid_signed_token_is_rejected_before_idempotency_claim(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    monkeypatch.setattr("services.api.app.core.auth.get_settings", lambda: settings)
    response = client.post(
        "/v1/workspaces",
        headers={
            "Authorization": "Bearer forged.token.value",
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "name": "Must not exist",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert response.status_code == 401
    with get_session_factory()() as db:
        assert db.scalar(select(func.count(IdempotencyRecord.id))) == 0


def test_auth_and_object_store_secrets_are_redacted_in_settings_repr() -> None:
    rendered = repr(_settings())
    assert SECRET not in rendered
    assert "object-secret" not in rendered
    assert "**********" in rendered


def test_production_worker_does_not_require_api_cors_or_auth_settings() -> None:
    settings = Settings(
        environment="production",
        service_role="worker",
        database_url="postgresql+psycopg://glint_worker:password@localhost/glint",
        object_store_backend="s3",
        s3_endpoint_url="http://minio:9000",
        s3_bucket="glint",
        s3_access_key_id=SecretStr("access-id"),
        s3_secret_access_key=SecretStr("object-secret"),
        allowed_origins=[],
        auth_hmac_secret=None,
    )
    assert settings.service_role == "worker"
    assert settings.allowed_origins == []
