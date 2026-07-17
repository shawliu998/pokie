"""Strict OpenAI-compatible and deterministic providers for Quant decisions."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from pydantic import SecretStr

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentContext,
    QuantAgentDecision,
    QuantAgentPlan,
    QuantAgentPlanStep,
)
from services.worker.app.providers import (
    HttpxOpenAICompatibleTransport,
    OpenAICompatibleConfig,
    OpenAICompatibleError,
)

from .prompt import build_decision_messages, build_plan_messages

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
MAX_RESPONSE_BYTES = 100_000


class QuantAgentProviderError(RuntimeError):
    """Public-safe provider failure."""


class QuantAgentProvider(Protocol):
    provider_name: str
    model_name: str | None

    def plan(self, research_goal: str) -> QuantAgentPlan: ...

    def decide(self, context: QuantAgentContext) -> QuantAgentDecision: ...


class OpenAICompatibleProvider:
    provider_name: str = "openai_compatible"

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config
        self.model_name: str | None = config.model
        self._transport = HttpxOpenAICompatibleTransport(config)

    def decide(self, context: QuantAgentContext) -> QuantAgentDecision:
        try:
            return QuantAgentDecision.model_validate_json(
                self._complete(build_decision_messages(context))
            )
        except ValueError:
            raise QuantAgentProviderError(
                "Quant agent response failed closed validation."
            ) from None

    def plan(self, research_goal: str) -> QuantAgentPlan:
        try:
            return QuantAgentPlan.model_validate_json(
                self._complete(build_plan_messages(research_goal))
            )
        except ValueError:
            raise QuantAgentProviderError(
                "Quant agent plan failed closed validation."
            ) from None

    def _complete(self, messages: list[dict[str, str]]) -> str:
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            envelope = self._transport.complete(request)
            return envelope["choices"][0]["message"]["content"]
        except OpenAICompatibleError as exc:
            raise QuantAgentProviderError(str(exc)) from None
        except (KeyError, TypeError, json.JSONDecodeError, ValueError):
            raise QuantAgentProviderError(
                "Quant agent response failed closed validation."
            ) from None


class MockQuantAgentProvider:
    provider_name: str = "mock"
    model_name: str | None = None

    def plan(self, research_goal: str) -> QuantAgentPlan:
        goal = research_goal.lower()
        if any(token in goal for token in ("opportunit", "frequent", "交易机会", "频繁")):
            families = ["rsi_mean_reversion", "sma_crossover", "breakout"]
        elif any(token in goal for token in ("mean reversion", "均值回归")):
            families = ["rsi_mean_reversion", "sma_crossover"]
        else:
            families = ["sma_crossover", "breakout"]
        steps = [
            ("inspect", "Inspect research context"),
            ("templates", "Review supported strategy templates"),
            ("experiments", "Create and backtest bounded candidates"),
            ("compare", "Compare completed candidates with buy and hold"),
            ("report", "Finish with an evidence-backed conclusion"),
        ]
        return QuantAgentPlan(
            objective_summary=f"Bounded autonomous research for: {research_goal}",
            steps=[
                QuantAgentPlanStep(
                    key=key,
                    title=title,
                    owner="agent",
                    description=f"{title} using only registered local Quant tools.",
                )
                for key, title in steps
            ],
            candidate_families=families,
            max_experiments=3,
            max_repairs=2,
            completion_criteria=[
                "Backtest every judged candidate with the local kernel.",
                "Compare completed candidates before selecting one.",
                "Retain a report even when no candidate meets the goal.",
            ],
        )

    def decide(self, context: QuantAgentContext) -> QuantAgentDecision:
        observed = {item.get("action") for item in context.recent_observations}
        if QuantAgentAction.INSPECT_RESEARCH_CONTEXT.value not in observed:
            return self._decision(QuantAgentAction.INSPECT_RESEARCH_CONTEXT, {})
        if QuantAgentAction.LIST_STRATEGY_TEMPLATES.value not in observed:
            return self._decision(QuantAgentAction.LIST_STRATEGY_TEMPLATES, {})
        if context.budget.remaining_iterations <= 1:
            return self._finish(context, "The bounded decision budget is exhausted.")
        pending = next(
            (item for item in context.candidates if item.state == "created"), None
        )
        if pending is not None:
            return self._decision(
                QuantAgentAction.RUN_BACKTEST, {"candidate_id": pending.candidate_id}
            )
        if context.budget.remaining_experiments > 0:
            return self._create(context)
        opportunity_goal = any(
            token in context.research_goal.lower()
            for token in ("trading opportunit", "frequent", "交易机会", "频繁")
        )
        if (
            opportunity_goal
            and context.budget.remaining_repairs > 0
            and QuantAgentAction.REVISE_CANDIDATE.value not in observed
        ):
            rsi = next(
                (
                    item
                    for item in context.candidates
                    if item.template == "rsi_mean_reversion" and item.state == "completed"
                ),
                None,
            )
            if rsi is not None:
                return self._decision(
                    QuantAgentAction.REVISE_CANDIDATE,
                    {
                        "candidate_id": rsi.candidate_id,
                        "reason": "Test whether a lower RSI entry threshold improves drawdown.",
                        "parameter_patch": {"entry_threshold": 25},
                    },
                )
        if QuantAgentAction.COMPARE_CANDIDATES.value not in observed:
            return self._decision(QuantAgentAction.COMPARE_CANDIDATES, {})
        return self._finish(
            context, "Completed bounded candidates were compared with the benchmark."
        )

    @staticmethod
    def _decision(action: QuantAgentAction, arguments: dict[str, object]) -> QuantAgentDecision:
        return QuantAgentDecision(
            action=action,
            arguments=arguments,
            decision_summary=f"Select {action.value} as the next bounded action.",
            expected_result="A persisted safe tool observation.",
        )

    def _create(self, context: QuantAgentContext) -> QuantAgentDecision:
        goal = context.research_goal.lower()
        index = len(context.candidates)
        if any(token in goal for token in ("trading opportunit", "frequent", "交易机会", "频繁")):
            sequence = (
                (
                    "RSI 30/55",
                    "rsi_mean_reversion",
                    {"period": 14, "entry_threshold": 30, "exit_threshold": 55},
                ),
                ("SMA 10/50", "sma_crossover", {"fast_window": 10, "slow_window": 50}),
                ("20-day breakout", "breakout", {"lookback_window": 20}),
            )
            hypothesis = "Seek more trading opportunities while bounding drawdown."
        elif any(token in goal for token in ("mean reversion", "均值回归")):
            sequence = (
                (
                    "RSI 25/55",
                    "rsi_mean_reversion",
                    {"period": 14, "entry_threshold": 25, "exit_threshold": 55},
                ),
                (
                    "RSI 30/60",
                    "rsi_mean_reversion",
                    {"period": 14, "entry_threshold": 30, "exit_threshold": 60},
                ),
                ("SMA 5/20", "sma_crossover", {"fast_window": 5, "slow_window": 20}),
            )
            hypothesis = "Test a bounded mean-reversion objective."
        elif "trend" in goal or "趋势" in goal:
            sequence = (
                ("SMA 20/100", "sma_crossover", {"fast_window": 20, "slow_window": 100}),
                ("SMA 50/200", "sma_crossover", {"fast_window": 50, "slow_window": 200}),
                ("55-day breakout", "breakout", {"lookback_window": 55}),
            )
            hypothesis = "Test simple trend filters over the pinned dataset."
        else:
            sequence = (
                ("SMA 50/200", "sma_crossover", {"fast_window": 50, "slow_window": 200}),
                ("SMA 20/100", "sma_crossover", {"fast_window": 20, "slow_window": 100}),
                ("200-day breakout", "breakout", {"lookback_window": 200}),
            )
            hypothesis = "Reduce drawdown versus buy and hold with a simple filter."
        name, template, parameters = sequence[min(index, len(sequence) - 1)]
        arguments: dict[str, object] = {
            "name": name,
            "template": template,
            "hypothesis": hypothesis,
            "parameters": parameters,
        }
        return self._decision(QuantAgentAction.CREATE_CANDIDATE, arguments)

    def _finish(self, context: QuantAgentContext, conclusion: str) -> QuantAgentDecision:
        viable = [
            item
            for item in context.candidates
            if item.state == "completed" and item.verdict == "viable"
        ]
        selected = max(
            viable,
            key=lambda item: float((item.metrics or {}).get("maximum_drawdown_pct", -1000)),
            default=None,
        )
        return self._decision(
            QuantAgentAction.FINISH_RESEARCH,
            {
                "selected_candidate_id": selected.candidate_id if selected else None,
                "conclusion": conclusion
                if selected is None
                else f"{conclusion} {selected.name} best reduced drawdown in the tested set.",
                "next_step": "paper_evaluation" if selected else "stop",
            },
        )


def load_quant_agent_provider() -> QuantAgentProvider:
    provider = os.environ.get("POKIEQUANT_AGENT_PROVIDER", "mock").strip().lower()
    if provider in {"", "mock"}:
        return MockQuantAgentProvider()
    if provider not in {"deepseek", "openai_compatible"}:
        raise QuantAgentProviderError("POKIEQUANT_AGENT_PROVIDER is invalid.")
    key = os.environ.get("POKIEQUANT_AGENT_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return MockQuantAgentProvider()
    base_url = os.environ.get("POKIEQUANT_AGENT_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL)
    model = os.environ.get("POKIEQUANT_AGENT_MODEL", DEFAULT_DEEPSEEK_MODEL)
    try:
        config = OpenAICompatibleConfig(SecretStr(key), base_url, model)
    except OpenAICompatibleError:
        raise QuantAgentProviderError("Quant agent configuration is invalid.") from None
    return OpenAICompatibleProvider(config)
