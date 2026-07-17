"""Shared providers for model-facing workers."""

from __future__ import annotations

from .openai_compatible import (
    DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
    DEFAULT_OPENAI_COMPATIBLE_MODEL,
    MAX_RESPONSE_BYTES,
    HttpxOpenAICompatibleTransport,
    OpenAICompatibleConfig,
    OpenAICompatibleError,
    OpenAICompatibleTransport,
)

__all__ = [
    "DEFAULT_OPENAI_COMPATIBLE_BASE_URL",
    "DEFAULT_OPENAI_COMPATIBLE_MODEL",
    "MAX_RESPONSE_BYTES",
    "OpenAICompatibleConfig",
    "OpenAICompatibleError",
    "OpenAICompatibleTransport",
    "HttpxOpenAICompatibleTransport",
]
