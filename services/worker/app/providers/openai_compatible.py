"""Shared OpenAI-compatible /chat/completions HTTP transport.

This is the single implementation of the httpx chat-completions transport used by
bounded worker pipelines. It never exposes secrets or raw provider responses in
exception messages, validates HTTPS origins, enforces a response byte limit, and
returns the validated JSON envelope.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.deepseek.com"
DEFAULT_OPENAI_COMPATIBLE_MODEL = "deepseek-v4-flash"
MAX_RESPONSE_BYTES = 100_000


class OpenAICompatibleError(RuntimeError):
    """Public-safe provider failure that never includes response or secret text."""


class OpenAICompatibleConfig:
    """Validated configuration for an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        api_key: SecretStr,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 45.0,
        max_tokens: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise OpenAICompatibleError("Base URL must be an HTTPS origin.")
        if not self.model or len(self.model) > 128:
            raise OpenAICompatibleError("Model name is invalid.")

    @classmethod
    def from_env(
        cls,
        *,
        key_var: str,
        base_url_var: str | None = None,
        model_var: str | None = None,
        default_base_url: str = DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
        default_model: str = DEFAULT_OPENAI_COMPATIBLE_MODEL,
        timeout_seconds: float = 45.0,
        max_tokens: int | None = None,
    ) -> OpenAICompatibleConfig:
        raw_key = os.environ.get(key_var)
        if not raw_key:
            raise OpenAICompatibleError(f"{key_var} is not configured.")
        base_url = (
            os.environ.get(base_url_var, default_base_url)
            if base_url_var
            else default_base_url
        )
        if not base_url:
            base_url = default_base_url
        model = (
            os.environ.get(model_var, default_model) if model_var else default_model
        )
        if not model:
            model = default_model
        return cls(
            api_key=SecretStr(raw_key),
            base_url=base_url,
            model=model.strip(),
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
        )


class OpenAICompatibleTransport(Protocol):
    def complete(self, request: dict[str, Any]) -> dict[str, Any]: ...


class _ChoiceMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: _ChoiceMessage


class _ChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    choices: list[_Choice] = Field(min_length=1, max_length=1)


class HttpxOpenAICompatibleTransport:
    """Single httpx implementation of the OpenAI-compatible chat endpoint."""

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.config.timeout_seconds),
                follow_redirects=False,
            ) as client:
                response = client.post(
                    f"{self.config.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json=request,
                )
            if response.status_code != 200:
                raise OpenAICompatibleError(
                    f"Provider request failed with HTTP status {response.status_code}."
                )
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise OpenAICompatibleError("Provider response exceeded the configured byte limit.")
            value = response.json()
        except OpenAICompatibleError:
            raise
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            raise OpenAICompatibleError("Provider request failed safely.") from None
        if not isinstance(value, dict):
            raise OpenAICompatibleError("Provider response envelope is invalid.")
        try:
            _ChatResponse.model_validate(value)
        except ValidationError:
            raise OpenAICompatibleError("Provider response envelope failed validation.") from None
        return value
