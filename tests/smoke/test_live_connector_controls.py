from __future__ import annotations

import pytest

from scripts.live_connector_smoke import (
    AUTHENTICITY_CAPTURED,
    AUTHENTICITY_LIVE,
    LiveSmokeInvariantError,
    SmokeSummary,
    github_prerequisites,
    live_smoke_enabled,
    redacted_json,
    run,
)


def test_live_smoke_requires_exact_opt_in_and_makes_no_network_call() -> None:
    messages: list[str] = []
    assert run({}, messages.append, github_repositories=(), rss_feeds=()) == 0
    assert messages == [
        "SKIP live connector smoke: set GLINT_ENABLE_LIVE_SMOKE=1 to permit network egress"
    ]
    assert not live_smoke_enabled({"GLINT_ENABLE_LIVE_SMOKE": "true"})
    assert live_smoke_enabled({"GLINT_ENABLE_LIVE_SMOKE": "1"})


def test_live_github_missing_credentials_is_an_explicit_skip() -> None:
    assert github_prerequisites({}) == (
        False,
        "missing secret reference GLINT_SECRET_GITHUB_TOKEN",
    )
    assert github_prerequisites({"GLINT_SECRET_GITHUB_TOKEN": "present"}) == (
        False,
        "missing 32-byte GLINT_CONNECTOR_CURSOR_SECRET",
    )


def test_live_summary_is_metadata_only_and_authenticity_is_unambiguous() -> None:
    token = "live-secret-that-must-never-be-rendered"
    summary = SmokeSummary(
        connector="github",
        source="openai/codex",
        authenticity=AUTHENTICITY_LIVE,
        outcome="passed",
        health="healthy",
        freshness="current",
        item_count=3,
        checks=("health", "search"),
    )
    payload = redacted_json(summary, (token,))
    assert AUTHENTICITY_LIVE in payload
    assert AUTHENTICITY_CAPTURED == "Captured Fixture"
    assert token not in payload
    assert "authorization" not in payload.lower()


def test_live_summary_fails_closed_if_a_secret_enters_metadata() -> None:
    token = "live-secret-that-must-never-be-rendered"
    summary = SmokeSummary(
        connector="github",
        source=token,
        authenticity=AUTHENTICITY_LIVE,
        outcome="failed",
        health="failed",
        freshness="unknown",
    )
    with pytest.raises(LiveSmokeInvariantError, match="secret value"):
        redacted_json(summary, (token,))
