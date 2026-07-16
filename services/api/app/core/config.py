from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GLINT_", extra="ignore")

    environment: str = "development"
    service_role: Literal["api", "worker"] = "api"
    database_url: str = "sqlite:///./glint.db"
    object_store_root: Path = Path("./.glint-objects")
    object_store_backend: str = "filesystem"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    auth_hmac_secret: SecretStr | None = None
    auth_audience: str = "glint-api"
    auth_issuer: str | None = None
    auth_max_token_lifetime_seconds: int = Field(default=900, ge=60, le=3_600)
    auth_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    idempotency_retention_seconds: int = Field(default=86_400, ge=60)
    upload_grant_ttl_seconds: int = Field(default=900, ge=60, le=3_600)
    max_import_bytes: int = Field(default=10_000_000, ge=1_024)
    allowed_origins: list[str] = Field(default_factory=list)
    create_schema_on_startup: bool = True
    sse_poll_interval_seconds: float = Field(default=0.1, ge=0.01, le=5)
    model_runtime_enabled: bool = False
    deepseek_model: str = Field(default="deepseek-v4-flash", min_length=1, max_length=128)

    @model_validator(mode="after")
    def production_requires_postgres(self) -> Settings:
        if self.environment == "production" and not self.database_url.startswith(
            ("postgresql://", "postgresql+psycopg://")
        ):
            raise ValueError("Production requires PostgreSQL so the RLS contract is enforceable")
        expected_database_role = {
            "api": "glint_api",
            "worker": "glint_worker",
        }[self.service_role]
        if (
            self.environment == "production"
            and make_url(self.database_url).username != expected_database_role
        ):
            raise ValueError(
                f"Production {self.service_role} must connect as the non-superuser "
                f"{expected_database_role} role"
            )
        is_production_api = self.environment == "production" and self.service_role == "api"
        if is_production_api and not self.allowed_origins:
            raise ValueError("Production requires an explicit GLINT_ALLOWED_ORIGINS list")
        if is_production_api and self.auth_hmac_secret is None:
            raise ValueError("Production requires GLINT_AUTH_HMAC_SECRET for signed access tokens")
        if is_production_api and self.auth_hmac_secret is not None:
            secret_bytes = self.auth_hmac_secret.get_secret_value().encode("utf-8")
            if len(secret_bytes) < 32 or len(set(secret_bytes)) < 8:
                raise ValueError(
                    "Production GLINT_AUTH_HMAC_SECRET must contain at least 32 bytes "
                    "of high-entropy secret material"
                )
        if self.service_role == "api" and "*" in self.allowed_origins:
            raise ValueError("Wildcard CORS origins are forbidden")
        if self.environment == "production" and (
            self.object_store_backend != "s3"
            or not self.s3_endpoint_url
            or not self.s3_bucket
            or self.s3_access_key_id is None
            or self.s3_secret_access_key is None
        ):
            raise ValueError("Production requires the configured S3-compatible object store")
        if (self.s3_access_key_id is None) != (self.s3_secret_access_key is None):
            raise ValueError("S3 access key ID and secret access key must be configured together")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
