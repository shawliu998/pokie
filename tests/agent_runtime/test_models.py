from __future__ import annotations

import pytest

from packages.agent_runtime import (
    ModelRequest,
    ModelResponse,
    ModelRouter,
    ModelTier,
)


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[ModelRequest, ModelTier]] = []

    def complete(self, request: ModelRequest, tier: ModelTier) -> ModelResponse:
        self.calls.append((request, tier))
        return ModelResponse(
            tier=tier,
            model=f"test-{tier}",
            content="ok",
            usage={"total_tokens": 3},
            latency_ms=12,
            cost=0.001,
        )


@pytest.mark.parametrize(
    ("complexity", "expected_tier", "expected_reason"),
    [
        (0.0, ModelTier.LIGHT, "complexity_low"),
        (0.25, ModelTier.LIGHT, "complexity_low"),
        (0.250001, ModelTier.BALANCED, "complexity_balanced"),
        (0.749999, ModelTier.BALANCED, "complexity_balanced"),
        (0.75, ModelTier.STRONG, "complexity_high"),
        (1.0, ModelTier.STRONG, "complexity_high"),
    ],
)
def test_router_selects_expected_tier_at_boundaries(
    complexity: float,
    expected_tier: ModelTier,
    expected_reason: str,
) -> None:
    router = ModelRouter(_RecordingProvider())

    tier, reason = router.choose(ModelRequest(task="research", prompt="go", complexity=complexity))

    assert tier is expected_tier
    assert reason == expected_reason


def test_deterministic_request_always_uses_light_tier() -> None:
    router = ModelRouter(_RecordingProvider())

    tier, reason = router.choose(
        ModelRequest(task="research", prompt="go", complexity=1.0, deterministic=True)
    )

    assert tier is ModelTier.LIGHT
    assert reason == "deterministic"


def test_router_calls_provider_and_returns_routing_reason() -> None:
    provider = _RecordingProvider()
    request = ModelRequest(task="research", prompt="go", complexity=0.5)

    response, reason = ModelRouter(provider).complete(request)

    assert provider.calls == [(request, ModelTier.BALANCED)]
    assert response.tier is ModelTier.BALANCED
    assert response.model == "test-balanced"
    assert reason == "complexity_balanced"


@pytest.mark.parametrize("complexity", [-0.001, 1.001])
def test_request_rejects_complexity_outside_unit_interval(complexity: float) -> None:
    with pytest.raises(ValueError, match="complexity"):
        ModelRequest(task="research", prompt="go", complexity=complexity)


@pytest.mark.parametrize(
    ("light_threshold", "strong_threshold"),
    [(-0.01, 0.75), (0.25, 1.01), (0.8, 0.7)],
)
def test_router_rejects_invalid_thresholds(
    light_threshold: float,
    strong_threshold: float,
) -> None:
    with pytest.raises(ValueError):
        ModelRouter(
            _RecordingProvider(),
            light_threshold=light_threshold,
            strong_threshold=strong_threshold,
        )
