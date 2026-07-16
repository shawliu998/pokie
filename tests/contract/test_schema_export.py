from __future__ import annotations

from pathlib import Path

import pytest

from packages.contracts.events import RunEvent
from packages.contracts.openapi import (
    assert_openapi_components_present,
    assert_openapi_snapshot,
    canonical_openapi_json,
    json_schema_bundle,
    openapi_components,
    write_contract_artifacts,
)
from packages.contracts.schemas import ImportSessionCreateRequest, SignalResponse
from services.api.app.main import app

OPENAPI_SNAPSHOT = (
    Path(__file__).parents[2] / "packages" / "contracts" / "openapi" / "openapi.snapshot.json"
)


def test_json_schema_and_openapi_export_use_serialization_contracts() -> None:
    bundle = json_schema_bundle([ImportSessionCreateRequest, SignalResponse])
    assert set(bundle["schemas"]) == {"ImportSessionCreateRequest", "SignalResponse"}

    document = openapi_components([ImportSessionCreateRequest, SignalResponse])
    schemas = document["components"]["schemas"]
    assert "ImportSessionCreateRequest" in schemas
    assert "SignalResponse" in schemas


def test_contract_artifacts_are_deterministic(tmp_path: Path) -> None:
    json_schema_file, openapi_file = write_contract_artifacts(tmp_path)
    first = (json_schema_file.read_bytes(), openapi_file.read_bytes())
    write_contract_artifacts(tmp_path)
    second = (json_schema_file.read_bytes(), openapi_file.read_bytes())
    assert first == second


def test_openapi_component_assertion_and_snapshot_helper(tmp_path: Path) -> None:
    document = {
        "openapi": "3.1.0",
        "components": {
            "schemas": {
                "ImportSessionCreateRequest": {},
                "SignalResponse": {},
            }
        },
    }
    assert_openapi_components_present(document, [ImportSessionCreateRequest, SignalResponse])

    snapshot = tmp_path / "openapi.snapshot.json"
    snapshot.write_text(canonical_openapi_json(document) + "\n", encoding="utf-8")
    assert_openapi_snapshot(document, snapshot)

    with pytest.raises(AssertionError, match="missing"):
        assert_openapi_components_present(
            document, [ImportSessionCreateRequest, SignalResponse, RunEvent]
        )


def test_fastapi_openapi_matches_checked_snapshot() -> None:
    document = app.openapi()
    assert_openapi_components_present(document)
    assert_openapi_snapshot(document, OPENAPI_SNAPSHOT)
