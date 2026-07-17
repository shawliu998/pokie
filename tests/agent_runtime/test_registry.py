from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from packages.agent_runtime import ToolContext, ToolError, ToolRegistry, ToolSpec


class _AddInput(BaseModel):
    a: int
    b: int


class _AddOutput(BaseModel):
    result: int


class _MulInput(BaseModel):
    a: int
    b: int


class _MulOutput(BaseModel):
    result: int


def test_registry_rejects_duplicate_tools() -> None:
    registry = ToolRegistry[Any]()
    spec = ToolSpec(
        name="add",
        version="1.0.0",
        description="Add two numbers.",
        input_model=_AddInput,
        output_model=_AddOutput,
    )
    registry.register(spec, lambda _ctx, inp: _AddOutput(result=inp.a + inp.b))
    with pytest.raises(ToolError, match="Duplicate tool: add"):
        registry.register(spec, lambda _ctx, inp: _AddOutput(result=inp.a + inp.b))


def test_registry_rejects_unknown_tools() -> None:
    registry = ToolRegistry[Any]()
    with pytest.raises(ToolError, match="Unknown tool: missing"):
        registry.execute(name="missing", context=None, arguments={})


def test_registry_validates_input_model() -> None:
    registry = ToolRegistry[Any]()
    registry.register(
        ToolSpec(
            name="add",
            version="1.0.0",
            description="Add two numbers.",
            input_model=_AddInput,
            output_model=_AddOutput,
        ),
        lambda _ctx, inp: _AddOutput(result=inp.a + inp.b),
    )
    with pytest.raises(ToolError):
        registry.execute(name="add", context=None, arguments={"a": 1})


def test_registry_validates_output_model() -> None:
    registry = ToolRegistry[Any]()

    def bad_execute(_ctx: Any, _inp: BaseModel) -> BaseModel:
        return _MulOutput(result=0)

    registry.register(
        ToolSpec(
            name="add",
            version="1.0.0",
            description="Add two numbers.",
            input_model=_AddInput,
            output_model=_AddOutput,
        ),
        bad_execute,
    )
    with pytest.raises(ToolError, match="returned _MulOutput"):
        registry.execute(name="add", context=None, arguments={"a": 1, "b": 2})


def test_registry_executes_valid_tool() -> None:
    registry = ToolRegistry[Any]()
    registry.register(
        ToolSpec(
            name="add",
            version="1.0.0",
            description="Add two numbers.",
            input_model=_AddInput,
            output_model=_AddOutput,
        ),
        lambda _ctx, inp: _AddOutput(result=inp.a + inp.b),
    )
    output = registry.execute(name="add", context=None, arguments={"a": 2, "b": 3})
    assert isinstance(output, _AddOutput)
    assert output.result == 5


def test_manifest_is_deterministic_and_contains_schemas() -> None:
    registry = ToolRegistry[Any](version="1.2.3")
    registry.register(
        ToolSpec(
            name="add",
            version="1.0.0",
            description="Add two numbers.",
            input_model=_AddInput,
            output_model=_AddOutput,
        ),
        lambda _ctx, inp: _AddOutput(result=inp.a + inp.b),
    )
    registry.register(
        ToolSpec(
            name="mul",
            version="2.0.0",
            description="Multiply two numbers.",
            input_model=_MulInput,
            output_model=_MulOutput,
        ),
        lambda _ctx, inp: _MulOutput(result=inp.a * inp.b),
    )
    manifest = registry.manifest()
    dumped = json.dumps(manifest, sort_keys=True)
    assert manifest["registry_version"] == "1.2.3"
    assert list(manifest["tools"].keys()) == ["add", "mul"]
    assert "input_schema" in manifest["tools"]["add"]
    assert "output_schema" in manifest["tools"]["add"]
    assert manifest["tools"]["add"]["version"] == "1.0.0"
    assert json.dumps(registry.manifest(), sort_keys=True) == dumped


def test_tool_context_wraps_value() -> None:
    context = ToolContext({"workspace_id": "ws"})
    assert context.value == {"workspace_id": "ws"}
