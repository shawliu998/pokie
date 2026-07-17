from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from services.worker.app.pipelines.model_research import (
    DeepSeekConfig,
    DeepSeekResearchRunner,
    HttpxDeepSeekTransport,
    ModelProviderError,
)
from services.worker.app.providers import (
    HttpxOpenAICompatibleTransport,
    OpenAICompatibleConfig,
    OpenAICompatibleError,
)


def _clear_deepseek_env() -> None:
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        os.environ.pop(key, None)


def test_shared_config_rejects_http_origin() -> None:
    with pytest.raises(OpenAICompatibleError, match="HTTPS origin"):
        OpenAICompatibleConfig(SecretStr("key"), "http://api.example.com", "model")


def test_shared_config_rejects_invalid_model() -> None:
    with pytest.raises(OpenAICompatibleError, match="Model name is invalid"):
        OpenAICompatibleConfig(SecretStr("key"), "https://api.example.com", "")


def test_shared_config_strips_base_url() -> None:
    config = OpenAICompatibleConfig(
        SecretStr("key"), "https://api.example.com/", "model"
    )
    assert config.base_url == "https://api.example.com"


def test_shared_transport_returns_valid_envelope() -> None:
    config = OpenAICompatibleConfig(
        SecretStr("key"), "https://api.example.com", "model"
    )
    transport = HttpxOpenAICompatibleTransport(config)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = json.dumps(
        {"choices": [{"message": {"content": "hello"}}]}
    ).encode()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "hello"}}]
    }
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response

    target = "services.worker.app.providers.openai_compatible.httpx.Client"
    with patch(target, return_value=mock_client):
        envelope = transport.complete({"model": "model", "messages": []})

    assert envelope["choices"][0]["message"]["content"] == "hello"


def test_shared_transport_enforces_byte_limit() -> None:
    config = OpenAICompatibleConfig(
        SecretStr("key"), "https://api.example.com", "model"
    )
    transport = HttpxOpenAICompatibleTransport(config)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"x" * 100_001
    mock_response.json.return_value = {"choices": []}
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response

    target = "services.worker.app.providers.openai_compatible.httpx.Client"
    with patch(target, return_value=mock_client), pytest.raises(
        OpenAICompatibleError, match="byte limit"
    ):
        transport.complete({})


def test_model_research_config_uses_shared_validation() -> None:
    _clear_deepseek_env()
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    os.environ["DEEPSEEK_BASE_URL"] = "http://insecure.example.com"
    with pytest.raises(ModelProviderError, match="HTTPS origin"):
        DeepSeekConfig.from_env()
    _clear_deepseek_env()


def test_model_research_runner_accepts_shared_transport() -> None:
    _clear_deepseek_env()
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    config = DeepSeekConfig.from_env()
    shared_config = OpenAICompatibleConfig(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_tokens,
    )
    runner = DeepSeekResearchRunner(
        domain=MagicMock(), config=config, transport=HttpxOpenAICompatibleTransport(shared_config)
    )
    assert runner.transport is not None
    _clear_deepseek_env()


def test_legacy_deepseek_transport_maps_shared_errors() -> None:
    config = DeepSeekConfig(api_key=SecretStr("test-key"))
    transport = HttpxDeepSeekTransport(config)
    target = (
        "services.worker.app.providers.openai_compatible."
        "HttpxOpenAICompatibleTransport.complete"
    )
    with patch(target, side_effect=OpenAICompatibleError("provider unavailable")), pytest.raises(
        ModelProviderError, match="provider unavailable"
    ):
        transport.complete({})
