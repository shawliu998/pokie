"""Small, stateless model-routing primitives for bounded agent runtimes.

The router deliberately owns no provider configuration, retry policy, or
execution history.  Callers supply a provider and retain responsibility for
persisting any run-level decisions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ModelTier(StrEnum):
    """Relative capability and cost tiers available to a model provider."""

    LIGHT = "light"
    BALANCED = "balanced"
    STRONG = "strong"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A provider-independent model completion request."""

    task: str
    prompt: str
    complexity: float = 0.5
    deterministic: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.complexity <= 1.0:
            raise ValueError("complexity must be between 0.0 and 1.0.")


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """A normalized model completion result supplied by a provider."""

    tier: ModelTier
    model: str
    content: str
    usage: Mapping[str, int] = field(default_factory=dict)
    latency_ms: int | None = None
    cost: float | None = None


class ModelProvider(Protocol):
    """Provider seam used by :class:`ModelRouter`."""

    def complete(self, request: ModelRequest, tier: ModelTier) -> ModelResponse:
        """Complete ``request`` using the requested tier."""


class ModelRouter:
    """Choose a model tier from request complexity without retaining state."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        strong_threshold: float = 0.75,
        light_threshold: float = 0.25,
    ) -> None:
        if not 0.0 <= light_threshold <= 1.0:
            raise ValueError("light_threshold must be between 0.0 and 1.0.")
        if not 0.0 <= strong_threshold <= 1.0:
            raise ValueError("strong_threshold must be between 0.0 and 1.0.")
        if light_threshold > strong_threshold:
            raise ValueError("light_threshold must not exceed strong_threshold.")
        self._provider = provider
        self._strong_threshold = strong_threshold
        self._light_threshold = light_threshold

    def choose(self, request: ModelRequest) -> tuple[ModelTier, str]:
        """Return the selected tier and its deterministic routing reason."""
        if request.deterministic:
            return ModelTier.LIGHT, "deterministic"
        if request.complexity >= self._strong_threshold:
            return ModelTier.STRONG, "complexity_high"
        if request.complexity <= self._light_threshold:
            return ModelTier.LIGHT, "complexity_low"
        return ModelTier.BALANCED, "complexity_balanced"

    def complete(self, request: ModelRequest) -> tuple[ModelResponse, str]:
        """Complete a request and return the provider response with route reason."""
        tier, reason = self.choose(request)
        return self._provider.complete(request, tier), reason
