"""Deterministic JSON Schema/OpenAPI component and snapshot helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..registry import ALL_CONTRACT_MODELS


def _rewrite_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_refs(item) for item in value]
    if isinstance(value, str):
        return value.replace("#/$defs/", "#/components/schemas/")
    return value


def openapi_components(
    models: Iterable[type[BaseModel]] = ALL_CONTRACT_MODELS,
) -> dict[str, Any]:
    """Build reusable OpenAPI 3.1 components from serialization-mode schemas."""

    components: dict[str, Any] = {}
    for model in models:
        schema = model.model_json_schema(mode="serialization", by_alias=True)
        definitions = schema.pop("$defs", {})
        candidates = {model.__name__: schema, **definitions}
        for name, candidate in candidates.items():
            normalized = _rewrite_refs(candidate)
            previous = components.get(name)
            if previous is not None and previous != normalized:
                raise ValueError(f"conflicting schema component: {name}")
            components[name] = normalized
    return {"components": {"schemas": dict(sorted(components.items()))}}


def json_schema_bundle(
    models: Iterable[type[BaseModel]] = ALL_CONTRACT_MODELS,
) -> dict[str, Any]:
    """Build a deterministic review bundle without inventing a second schema."""

    schemas = {
        model.__name__: model.model_json_schema(mode="serialization", by_alias=True)
        for model in models
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Glint API contract schemas",
        "schemas": dict(sorted(schemas.items())),
    }


def canonical_openapi_json(document: Mapping[str, Any]) -> str:
    """Canonical form suitable for a checked OpenAPI snapshot."""

    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def assert_openapi_components_present(
    document: Mapping[str, Any],
    required_models: Iterable[type[BaseModel]] = ALL_CONTRACT_MODELS,
) -> None:
    """Fail if an application OpenAPI document omits a shared response/request model."""

    components = document.get("components", {})
    schemas = components.get("schemas", {}) if isinstance(components, Mapping) else {}
    missing = sorted(model.__name__ for model in required_models if model.__name__ not in schemas)
    if missing:
        raise AssertionError(f"OpenAPI is missing shared contract schemas: {', '.join(missing)}")


def assert_openapi_snapshot(document: Mapping[str, Any], snapshot_file: Path) -> None:
    """Compare a generated app OpenAPI document to a canonical checked snapshot."""

    expected = snapshot_file.read_text(encoding="utf-8").strip()
    actual = canonical_openapi_json(document)
    if actual != expected:
        raise AssertionError(f"OpenAPI snapshot changed: {snapshot_file}")


def write_contract_artifacts(output_directory: Path) -> tuple[Path, Path]:
    """Export reviewed JSON Schema and OpenAPI component artifacts."""

    output_directory.mkdir(parents=True, exist_ok=True)
    json_schema_file = output_directory / "contracts.schema.json"
    openapi_file = output_directory / "openapi-components.json"
    json_schema_file.write_text(
        json.dumps(json_schema_bundle(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    openapi_file.write_text(
        json.dumps(openapi_components(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return json_schema_file, openapi_file
