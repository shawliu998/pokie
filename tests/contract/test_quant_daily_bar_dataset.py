from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.quant.data import QuantDailyBarDataset
from packages.contracts.quant.fixture_data import (
    SPY_DAILY_FIXTURE,
    build_spy_daily_fixture,
)


def _payload() -> dict[str, object]:
    return SPY_DAILY_FIXTURE.model_dump(mode="json")


def test_spy_daily_fixture_is_frozen_deterministic_and_hash_verified() -> None:
    rebuilt = build_spy_daily_fixture()

    assert SPY_DAILY_FIXTURE.provenance == "synthetic_fixture"
    assert SPY_DAILY_FIXTURE.symbol == "SPY"
    assert SPY_DAILY_FIXTURE.interval == "1D"
    assert SPY_DAILY_FIXTURE.covered_start == date(2018, 1, 2)
    assert SPY_DAILY_FIXTURE.covered_end == date(2023, 12, 29)
    assert SPY_DAILY_FIXTURE.schema_version == "quant-daily-bars-v1"
    assert len(SPY_DAILY_FIXTURE.bars) == 1564
    assert SPY_DAILY_FIXTURE.bars[0].close == Decimal("100.036000")
    assert SPY_DAILY_FIXTURE.bars[-1].close == Decimal("365.251821")
    assert rebuilt == SPY_DAILY_FIXTURE
    assert rebuilt.digest == SPY_DAILY_FIXTURE.digest
    with pytest.raises(ValidationError, match="frozen"):
        SPY_DAILY_FIXTURE.symbol = "QQQ"  # type: ignore[misc]


@pytest.mark.parametrize("interval", ["1H", "5m", "daily"])
def test_daily_bar_dataset_rejects_unsupported_intervals(interval: str) -> None:
    payload = _payload()
    payload["interval"] = interval

    with pytest.raises(ValidationError, match="daily '1D'"):
        QuantDailyBarDataset.model_validate(payload)


def test_daily_bar_dataset_rejects_duplicate_or_unordered_bars() -> None:
    duplicate = _payload()
    duplicate["bars"] = [
        duplicate["bars"][0],
        duplicate["bars"][0],
        *duplicate["bars"][1:],
    ]
    with pytest.raises(ValidationError, match="strictly ordered"):
        QuantDailyBarDataset.model_validate(duplicate)

    unordered = _payload()
    unordered["bars"] = [
        unordered["bars"][1],
        unordered["bars"][0],
        *unordered["bars"][2:],
    ]
    unordered["covered_start"] = unordered["bars"][0]["trading_date"]
    with pytest.raises(ValidationError, match="strictly ordered"):
        QuantDailyBarDataset.model_validate(unordered)


def test_daily_bar_dataset_rejects_tampered_content_digest() -> None:
    payload = _payload()
    payload["bars"][0]["close"] = "100.030000"

    with pytest.raises(ValidationError, match="digest does not match"):
        QuantDailyBarDataset.model_validate(payload)


def test_daily_bar_dataset_requires_explicit_imported_or_synthetic_provenance() -> None:
    payload = _payload()
    payload.pop("digest")
    payload["provenance"] = "imported_fixture"
    payload["digest"] = QuantDailyBarDataset.digest_for(payload)

    imported = QuantDailyBarDataset.model_validate(payload)
    assert imported.provenance == "imported_fixture"


def test_daily_bar_boundary_has_no_network_or_execution_imports() -> None:
    root = Path(__file__).parents[2]
    source_paths = (
        root / "packages/contracts/quant/data.py",
        root / "packages/contracts/quant/fixture_data.py",
        root / "packages/domain/quant_fixture_data.py",
    )
    forbidden = {"asyncio", "httpx", "requests", "socket", "subprocess", "urllib"}

    imported_roots: set[str] = set()
    for source_path in source_paths:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_roots.update(
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imported_roots.update(
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
    assert imported_roots.isdisjoint(forbidden)
