# ruff: noqa: F401
# pyright: reportUnusedImport=false
"""Stable registry used by schema exporters and contract tests."""

from __future__ import annotations

from pydantic import BaseModel

from .events import RunEvent, StreamResetEvent
from .quant import *  # noqa: F403 - quant surface is part of the public contract registry
from .schemas import *  # noqa: F403 - registry intentionally covers the public schema surface


def _public_models() -> tuple[type[BaseModel], ...]:
    models: list[type[BaseModel]] = []
    for name, value in globals().items():
        if name.startswith("_") or not isinstance(value, type):
            continue
        if issubclass(value, BaseModel) and value is not BaseModel:
            models.append(value)
    return tuple(sorted(set(models), key=lambda model: model.__name__))


ALL_CONTRACT_MODELS = _public_models()
CONTRACT_MODEL_BY_NAME = {model.__name__: model for model in ALL_CONTRACT_MODELS}

__all__ = ["ALL_CONTRACT_MODELS", "CONTRACT_MODEL_BY_NAME"]
