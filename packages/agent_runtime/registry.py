"""Generic Pydantic-validated tool registry.

A registry owns a closed set of ToolSpec definitions, validates every input and
output model, rejects duplicate or unknown tools, and exposes a deterministic
manifest suitable for model prompts. It does not persist state, route models,
or schedule execution.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


class ToolError(RuntimeError):
    """Raised for unknown/duplicate tools or validation/execution failures."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ToolError("Tool name must be a non-empty string.")
        if not isinstance(self.version, str) or not self.version.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ToolError("Tool version must be a non-empty string.")
        if not (
            isinstance(self.input_model, type)  # pyright: ignore[reportUnnecessaryIsInstance]
            and issubclass(self.input_model, BaseModel)  # pyright: ignore[reportUnnecessaryIsInstance]
        ):
            raise ToolError(f"Tool {self.name} input_model must be a Pydantic BaseModel.")
        if not (
            isinstance(self.output_model, type)  # pyright: ignore[reportUnnecessaryIsInstance]
            and issubclass(self.output_model, BaseModel)  # pyright: ignore[reportUnnecessaryIsInstance]
        ):
            raise ToolError(f"Tool {self.name} output_model must be a Pydantic BaseModel.")

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.output_model.model_json_schema()


class ToolContext[T]:
    """Thin wrapper so tools receive a single typed context object."""

    def __init__(self, value: T) -> None:
        self.value = value


type ExecuteFn[T] = Callable[[T, BaseModel], BaseModel]


@dataclass(frozen=True, slots=True)
class _ToolEntry[T]:
    spec: ToolSpec
    execute: ExecuteFn[T]


class ToolRegistry[T]:
    """Closed tool registry with input/output validation and deterministic manifest."""

    def __init__(self, version: str = "1.0.0") -> None:
        self._version = version
        self._tools: dict[str, _ToolEntry[T]] = {}

    def register(self, spec: ToolSpec, execute: ExecuteFn[T]) -> None:
        if not callable(execute):
            raise ToolError(f"Tool {spec.name} execute must be callable.")
        if spec.name in self._tools:
            raise ToolError(f"Duplicate tool: {spec.name}")
        self._tools[spec.name] = _ToolEntry(spec, execute)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def execute(
        self,
        *,
        name: str,
        context: T,
        arguments: dict[str, Any],
    ) -> BaseModel:
        entry = self._tools.get(name)
        if entry is None:
            raise ToolError(f"Unknown tool: {name}")
        try:
            validated_input = entry.spec.input_model.model_validate(arguments)
        except Exception as exc:
            raise ToolError(f"Tool {name} input validation failed.") from exc
        output = entry.execute(context, validated_input)
        if not isinstance(output, entry.spec.output_model):
            raise ToolError(
                f"Tool {name} returned {type(output).__name__}, "
                f"expected {entry.spec.output_model.__name__}."
            )
        return output

    def manifest(self) -> dict[str, Any]:
        return {
            "registry_version": self._version,
            "tools": {
                name: {
                    "name": entry.spec.name,
                    "version": entry.spec.version,
                    "description": entry.spec.description,
                    "input_schema": entry.spec.input_schema,
                    "output_schema": entry.spec.output_schema,
                }
                for name, entry in sorted(self._tools.items())
            },
        }

    def manifest_json(self) -> str:
        return json.dumps(self.manifest(), sort_keys=True, separators=(",", ":"))
