"""Strict OpenAI-compatible and deterministic providers for Quant decisions."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Protocol, TypeVar, cast

from pydantic import BaseModel, SecretStr, ValidationError

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentContext,
    QuantAgentDecision,
    QuantAgentPlan,
    QuantAgentPlanStep,
    QuantStrategyScopeDecision,
)
from packages.domain.canonical import canonical_digest
from services.worker.app.providers import (
    HttpxOpenAICompatibleTransport,
    OpenAICompatibleConfig,
    OpenAICompatibleError,
)

from .prompt import build_decision_messages, build_plan_messages

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_QUANT_AGENT_MAX_TOKENS = 2_500
MAX_RESPONSE_BYTES = 100_000
_TRUE_VALUES = frozenset({"1", "true", "yes"})
_FALSE_VALUES = frozenset({"0", "false", "no"})
ContractT = TypeVar("ContractT", bound=BaseModel)
RequestProfile = Literal["deepseek", "kimi_k3", "openai", "qwen", "custom"]
_REQUEST_PROFILES = frozenset({"deepseek", "kimi_k3", "openai", "qwen", "custom"})


class QuantAgentProviderError(RuntimeError):
    """Public-safe provider failure."""

    def __init__(self, message: str, *, reason_code: str = "provider_error") -> None:
        self.reason_code = reason_code
        super().__init__(message)


def allow_mock_fallback() -> bool:
    """Return true only for an explicit, valid fallback opt-in."""

    raw = os.environ.get("POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK")
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise QuantAgentProviderError("POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK must be true or false.")


class QuantAgentProvider(Protocol):
    provider_name: str
    model_name: str | None

    def plan(self, research_goal: str) -> QuantAgentPlan: ...

    def decide(self, context: QuantAgentContext) -> QuantAgentDecision: ...


def final_research_selection(
    context: QuantAgentContext,
) -> tuple[str | None, dict[str, object] | None, str]:
    """Choose one deterministic typed decision from the exposed train-only evidence."""

    comparison = context.latest_comparison
    if comparison is None or not comparison.ranking:
        return None, None, "No fresh final training comparison was available."
    completed_ids = {
        candidate.candidate_id
        for candidate in context.candidates
        if candidate.state == "completed" and candidate.template != "fixture"
    }
    ranking = [candidate_id for candidate_id in comparison.ranking if candidate_id in completed_ids]
    if not ranking:
        return None, None, "No completed candidate was present in the final comparison."
    leader_id = ranking[0]
    evidence = {item.candidate_id: item for item in comparison.candidates}
    selected_id = leader_id
    deviation_reason: str | None = None
    if set(evidence) == set(ranking):
        pass_scores = {
            candidate_id: evidence[candidate_id].walk_forward_pass_folds for candidate_id in ranking
        }
        best_pass_score = max(pass_scores.values())
        pass_winners = [
            candidate_id for candidate_id in ranking if pass_scores[candidate_id] == best_pass_score
        ]
        if (
            len(pass_winners) == 1
            and pass_winners[0] != leader_id
            and best_pass_score > pass_scores[leader_id]
        ):
            selected_id = pass_winners[0]
            deviation_reason = "walk_forward_stability"
        else:
            regime_scores = {
                candidate_id: len(set(evidence[candidate_id].pass_regime_labels))
                for candidate_id in ranking
            }
            best_regime_score = max(regime_scores.values())
            regime_winners = [
                candidate_id
                for candidate_id in ranking
                if regime_scores[candidate_id] == best_regime_score
            ]
            if (
                len(regime_winners) == 1
                and regime_winners[0] != leader_id
                and best_regime_score >= 2
                and best_regime_score > regime_scores[leader_id]
            ):
                selected_id = regime_winners[0]
                deviation_reason = "regime_coverage"
            elif evidence[leader_id].trade_count == 0:
                trade_candidate = next(
                    (
                        candidate_id
                        for candidate_id in ranking
                        if evidence[candidate_id].trade_count >= 1
                    ),
                    None,
                )
                if trade_candidate is not None:
                    selected_id = trade_candidate
                    deviation_reason = "minimum_trade_evidence"
    decision: dict[str, object] = {
        "selected_candidate_id": selected_id,
        "source_comparison_artifact_id": comparison.artifact_id,
        "decision_basis": (
            "robustness_override" if deviation_reason is not None else "approved_objective_rank"
        ),
        "deviation": (
            {
                "reason": deviation_reason,
                "reference_candidate_id": leader_id,
            }
            if deviation_reason is not None
            else None
        ),
    }
    detail = (
        f"Selected {selected_id} with the closed {deviation_reason} robustness override "
        f"against objective leader {leader_id}."
        if deviation_reason is not None
        else f"Selected objective leader {leader_id}."
    )
    return selected_id, decision, detail


def _closed_validation_errors(error: ValueError) -> list[dict[str, object]]:
    if not isinstance(error, ValidationError):
        return [
            {
                "type": "invalid_json",
                "loc": [],
                "msg": "Return one valid JSON object matching the response schema.",
            }
        ]
    return [
        {
            "type": item["type"],
            "loc": list(item["loc"]),
            "msg": item["msg"],
        }
        for item in error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )[:12]
    ]


class OpenAICompatibleProvider:
    provider_name: str = "openai_compatible"

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        request_profile: RequestProfile = "deepseek",
        provider_name: str = "openai_compatible",
    ) -> None:
        self.config = config
        self.request_profile = request_profile
        self.provider_name = provider_name
        self.model_name: str | None = config.model
        self._transport = HttpxOpenAICompatibleTransport(config)

    def decide(self, context: QuantAgentContext) -> QuantAgentDecision:
        return self._validated_complete(
            messages=build_decision_messages(context),
            contract=QuantAgentDecision,
            failure_message="Quant agent response failed closed validation.",
        )

    def plan(self, research_goal: str) -> QuantAgentPlan:
        messages = build_plan_messages(research_goal)
        try:
            return self._validated_complete(
                messages=messages,
                contract=QuantAgentPlan,
                failure_message="Quant agent plan failed closed validation.",
            )
        except QuantAgentProviderError as error:
            if error.reason_code not in {"contract_invalid", "transport_failed"}:
                raise
            # Plan generation happens before a durable Run exists, so allow one
            # bounded fresh attempt instead of leaving no retained retry path.
            return self._validated_complete(
                messages=messages,
                contract=QuantAgentPlan,
                failure_message="Quant agent plan failed closed validation.",
            )

    def _validated_complete(
        self,
        *,
        messages: list[dict[str, str]],
        contract: type[ContractT],
        failure_message: str,
    ) -> ContractT:
        content = self._complete(messages)
        try:
            return contract.model_validate_json(content)
        except ValueError as error:
            repair_payload = {
                "instruction": (
                    f"Correct the previous output and return exactly one {contract.__name__} "
                    "JSON object. Do not add Markdown or explanation."
                ),
                "validation_errors": _closed_validation_errors(error),
                "response_schema": contract.model_json_schema(),
            }
            repair_messages = [
                *messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": json.dumps(
                        repair_payload,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                },
            ]
        try:
            return contract.model_validate_json(self._complete(repair_messages))
        except ValueError:
            raise QuantAgentProviderError(
                failure_message,
                reason_code="contract_invalid",
            ) from None

    def _request(
        self, messages: list[dict[str, str]], *, max_tokens: int | None = None
    ) -> dict[str, Any]:
        token_limit = self.config.max_tokens if max_tokens is None else max_tokens
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if self.request_profile == "deepseek":
            request["thinking"] = {"type": "disabled"}
            request["temperature"] = 0
            if token_limit is not None:
                request["max_tokens"] = token_limit
        elif self.request_profile == "kimi_k3":
            request["reasoning_effort"] = "max"
            if token_limit is not None:
                request["max_completion_tokens"] = token_limit
        elif self.request_profile == "openai":
            request["temperature"] = 0
            if token_limit is not None:
                request["max_completion_tokens"] = token_limit
        elif self.request_profile == "qwen":
            request["temperature"] = 0
            if token_limit is not None:
                request["max_tokens"] = token_limit
        elif token_limit is not None:
            request["max_tokens"] = token_limit
        return request

    def _complete(self, messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
        try:
            envelope = self._transport.complete(self._request(messages, max_tokens=max_tokens))
            return envelope["choices"][0]["message"]["content"]
        except OpenAICompatibleError as exc:
            raise QuantAgentProviderError(
                str(exc),
                reason_code="transport_failed",
            ) from None
        except (KeyError, TypeError, json.JSONDecodeError, ValueError):
            raise QuantAgentProviderError(
                "Quant agent response failed closed validation.",
                reason_code="contract_invalid",
            ) from None

    def test_connection(self) -> None:
        content = self._complete(
            [
                {
                    "role": "system",
                    "content": "Return exactly one JSON object and no Markdown.",
                },
                {"role": "user", "content": 'Return {"status":"ok"}.'},
            ],
            max_tokens=32,
        )
        try:
            value = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            raise QuantAgentProviderError(
                "Provider connection test returned invalid JSON.",
                reason_code="contract_invalid",
            ) from None
        if not isinstance(value, dict):
            raise QuantAgentProviderError(
                "Provider connection test returned an invalid envelope.",
                reason_code="contract_invalid",
            )


class MockQuantAgentProvider:
    provider_name: str = "mock"
    model_name: str | None = None

    def plan(self, research_goal: str) -> QuantAgentPlan:
        goal = research_goal.lower()
        scope, scoped_families = self._strategy_scope(goal)
        families: list[Literal["sma_crossover", "rsi_mean_reversion", "breakout"]]
        if scoped_families is not None:
            families = scoped_families
        elif any(token in goal for token in ("opportunit", "frequent", "交易机会", "频繁")):
            families = ["rsi_mean_reversion", "sma_crossover", "breakout"]
        elif any(token in goal for token in ("mean reversion", "均值回归")):
            families = ["rsi_mean_reversion", "sma_crossover"]
        else:
            families = ["sma_crossover", "breakout"]
        selection_objective: Literal["risk_adjusted_return", "total_return", "drawdown_control"]
        if any(token in goal for token in ("drawdown", "回撤", "downside")):
            selection_objective = "drawdown_control"
        elif any(token in goal for token in ("return", "收益", "growth")):
            selection_objective = "total_return"
        else:
            selection_objective = "risk_adjusted_return"
        steps = (
            [
                ("inspect", "Inspect research context"),
                ("scope", "Explain the unsupported strategy boundary"),
                ("revise", "Wait for a supported revision or cancellation"),
            ]
            if scope.status == "unsupported"
            else [
                ("inspect", "Inspect research context"),
                ("templates", "Review supported strategy templates"),
                ("experiments", "Create and backtest bounded candidates"),
                ("compare", "Compare completed candidates with buy and hold"),
                ("report", "Finish with an evidence-backed conclusion"),
            ]
        )
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
            strategy_scope=scope,
            selection_objective=selection_objective,
            max_experiments=3,
            max_repairs=2,
            completion_criteria=[
                "Backtest every judged candidate with the local kernel.",
                "Compare completed candidates before selecting one.",
                "Retain a report even when no candidate meets the goal.",
            ],
        )

    @staticmethod
    def _strategy_scope(
        goal: str,
    ) -> tuple[
        QuantStrategyScopeDecision,
        list[Literal["sma_crossover", "rsi_mean_reversion", "breakout"]] | None,
    ]:
        unsupported_patterns: tuple[tuple[tuple[str, ...], str], ...] = (
            (
                ("long/short", "long-short", "short selling", "go short", "做空", "多空"),
                "Short exposure is outside the current long-or-cash evaluator.",
            ),
            (
                (
                    "continuous sizing",
                    "continuous position",
                    "fractional position",
                    "target weight",
                    "连续仓位",
                    "连续头寸",
                ),
                (
                    "Continuous position sizing is outside the current binary "
                    "target-position contract."
                ),
            ),
            (
                (
                    "multi-asset",
                    "multi asset",
                    "multiasset",
                    "cross-sectional",
                    "rank assets",
                    "asset ranking",
                    "多资产",
                    "横截面",
                ),
                "Cross-asset ranking is outside the current single-dataset evaluator.",
            ),
            (
                (
                    "pairs trad",
                    "pair trad",
                    "statistical arbitrage",
                    "配对交易",
                    "统计套利",
                ),
                "Pairs research requires a multi-series execution and accounting contract.",
            ),
            (
                (
                    "xgboost",
                    "order book",
                    "order-book",
                    "level 2",
                    "订单簿",
                ),
                "Model training or order-book features are outside the registered OHLCV templates.",
            ),
        )
        for patterns, omission in unsupported_patterns:
            if any(pattern in goal for pattern in patterns):
                return (
                    QuantStrategyScopeDecision(
                        status="unsupported",
                        reason=(
                            "The requested behavior cannot be represented by the "
                            "registered templates."
                        ),
                        excluded_behaviors=[omission],
                    ),
                    [],
                )
        if "macd" in goal and any(
            token in goal
            for token in (
                "exact",
                "exactly",
                "no proxy",
                "without proxy",
                "精确",
                "不接受近似",
            )
        ):
            return (
                QuantStrategyScopeDecision(
                    status="unsupported",
                    reason="Exact MACD execution is not a registered strategy family.",
                    excluded_behaviors=[
                        "Exact MACD signal construction cannot be represented by SMA crossover."
                    ],
                ),
                [],
            )
        if "macd" in goal and any(
            token in goal
            for token in ("volume filter", "volatility filter", "vol filter", "成交量")
        ):
            return (
                QuantStrategyScopeDecision(
                    status="bounded_proxy",
                    reason=(
                        "A simple trend proxy can test directionality but not the exact request."
                    ),
                    proxy_description=(
                        "Use registered SMA crossover candidates as a trend-following proxy."
                    ),
                    excluded_behaviors=[
                        "Exact MACD signal construction is omitted.",
                        "The requested volume or volatility filter is omitted.",
                    ],
                ),
                ["sma_crossover"],
            )
        mentions_rsi = re.search(r"(?<![a-z0-9])rsi(?![a-z0-9])", goal) is not None
        if mentions_rsi and any(
            token in goal
            for token in ("sma200", "sma 200", "200-day sma", "200 day sma", "200日均线")
        ):
            return (
                QuantStrategyScopeDecision(
                    status="bounded_proxy",
                    reason=(
                        "RSI mean reversion is supported, but a combined SMA200 "
                        "regime filter is not."
                    ),
                    proxy_description=(
                        "Test registered RSI mean-reversion candidates without the SMA200 filter."
                    ),
                    excluded_behaviors=["The SMA200 regime filter is omitted."],
                ),
                ["rsi_mean_reversion"],
            )
        if "breakout" in goal and "atr" in goal:
            return (
                QuantStrategyScopeDecision(
                    status="bounded_proxy",
                    reason="Price breakout is supported, but ATR-based stop execution is not.",
                    proxy_description="Test the registered long-or-cash breakout template.",
                    excluded_behaviors=["The ATR-based stop-loss rule is omitted."],
                ),
                ["breakout"],
            )
        explicit_supported: list[Literal["sma_crossover", "rsi_mean_reversion", "breakout"]] = []
        if "sma" in goal or "moving average" in goal or "均线" in goal:
            explicit_supported.append("sma_crossover")
        if mentions_rsi:
            explicit_supported.append("rsi_mean_reversion")
        if "breakout" in goal or "突破" in goal:
            explicit_supported.append("breakout")
        return (
            QuantStrategyScopeDecision(
                status="supported",
                reason="The request fits the registered long-or-cash strategy templates.",
            ),
            explicit_supported or None,
        )

    def decide(self, context: QuantAgentContext) -> QuantAgentDecision:
        observed = {item.get("action") for item in context.recent_observations}
        if QuantAgentAction.INSPECT_RESEARCH_CONTEXT.value not in observed:
            return self._decision(QuantAgentAction.INSPECT_RESEARCH_CONTEXT, {})
        if QuantAgentAction.LIST_STRATEGY_TEMPLATES.value not in observed:
            return self._decision(QuantAgentAction.LIST_STRATEGY_TEMPLATES, {})
        pending = next((item for item in context.candidates if item.state == "created"), None)
        if pending is not None:
            return self._decision(
                QuantAgentAction.RUN_BACKTEST, {"candidate_id": pending.candidate_id}
            )
        completed = [
            item
            for item in context.candidates
            if item.state == "completed" and item.template != "fixture"
        ]
        completed_ids = {item.candidate_id for item in completed}
        latest_is_final = bool(
            context.latest_comparison
            and set(context.latest_comparison.candidate_ids) == completed_ids
        )
        feedback = context.iteration_feedback
        feedback_children = [item for item in context.candidates if item.feedback_artifact_id]
        if (
            feedback is not None
            and not feedback_children
            and context.budget.remaining_experiments > 0
            # Creation is followed by backtest, final comparison and finish.
            # Preserve all three actions rather than starting a candidate that
            # cannot be judged or reported within this bounded loop.
            and context.budget.remaining_iterations >= 4
        ):
            return self._create(context, feedback_driven=True)
        if feedback is not None:
            if completed and not latest_is_final:
                return self._decision(QuantAgentAction.COMPARE_CANDIDATES, {})
            return self._finish(
                context,
                "The retained training comparison is sufficient for this bounded run.",
            )
        opportunity_goal = any(
            token in context.research_goal.lower()
            for token in ("trading opportunit", "frequent", "交易机会", "频繁")
        )
        strict_default_loop = context.budget.max_experiments == 3
        if (
            opportunity_goal
            and not strict_default_loop
            and len(completed) >= 2
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
        if len(completed) >= 2 and context.budget.remaining_experiments > 0:
            return self._decision(QuantAgentAction.COMPARE_CANDIDATES, {})
        if context.budget.remaining_experiments > 0:
            return self._create(context)
        if (
            opportunity_goal
            and not strict_default_loop
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
        if completed and not latest_is_final:
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

    def _create(
        self, context: QuantAgentContext, *, feedback_driven: bool = False
    ) -> QuantAgentDecision:
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
        allowed_families = set(
            context.approved_plan.candidate_families
            if context.approved_plan is not None
            else ("sma_crossover", "rsi_mean_reversion", "breakout")
        )
        approved_sequence = [item for item in sequence if item[1] in allowed_families]
        if not approved_sequence:
            return self._finish(context, "The approved plan has no executable strategy family.")
        name, template, parameters = approved_sequence[min(index, len(approved_sequence) - 1)]
        tested_keys = set(
            context.research_memory.tested_candidate_keys
            if context.research_memory is not None
            else ()
        )
        tested_keys.update(
            canonical_digest({"template": item.template, "parameters": item.parameters})
            for item in context.candidates
            if item.template != "fixture"
        )
        selected_key = canonical_digest({"template": template, "parameters": parameters})
        if selected_key in tested_keys:
            distinct_sequence = (
                ("SMA 15/80", "sma_crossover", {"fast_window": 15, "slow_window": 80}),
                ("SMA 30/150", "sma_crossover", {"fast_window": 30, "slow_window": 150}),
                ("SMA 10/60", "sma_crossover", {"fast_window": 10, "slow_window": 60}),
                (
                    "RSI 28/58",
                    "rsi_mean_reversion",
                    {"period": 14, "entry_threshold": 28, "exit_threshold": 58},
                ),
                (
                    "RSI 20/50",
                    "rsi_mean_reversion",
                    {"period": 14, "entry_threshold": 20, "exit_threshold": 50},
                ),
                (
                    "RSI 35/65",
                    "rsi_mean_reversion",
                    {"period": 14, "entry_threshold": 35, "exit_threshold": 65},
                ),
                ("40-day breakout", "breakout", {"lookback_window": 40}),
                ("80-day breakout", "breakout", {"lookback_window": 80}),
                ("120-day breakout", "breakout", {"lookback_window": 120}),
            )
            available = [
                item
                for item in (*sequence, *distinct_sequence)
                if item[1] in allowed_families
                and canonical_digest({"template": item[1], "parameters": item[2]})
                not in tested_keys
            ]
            if available:
                name, template, parameters = available[0]
            else:
                duplicate = approved_sequence[0]
                return self._finish(
                    context,
                    "No canonical-distinct candidate remains in the bounded Mock strategy set.",
                    duplicate_proposal=(
                        duplicate[1],
                        cast(dict[str, int | float], duplicate[2]),
                    ),
                )
        arguments: dict[str, object] = {
            "name": name,
            "template": template,
            "hypothesis": hypothesis,
            "parameters": parameters,
        }
        if feedback_driven:
            feedback = context.iteration_feedback
            assert feedback is not None
            reference = next(
                item
                for item in feedback.completed_candidates
                if item.candidate_id == feedback.improvement_reference.candidate_id
            )
            arguments["change_rationale"] = (
                "Use the train-only comparison "
                f"{feedback.comparison_artifact_id} to test a distinct canonical strategy "
                "against the retained reference without using sealed holdout evidence."
            )
            arguments["replan_decision"] = {
                "action": (
                    "refine_parameters"
                    if template == reference.template
                    else "switch_approved_family"
                ),
                "source_comparison_artifact_id": feedback.comparison_artifact_id,
                "improvement_reference_candidate_id": reference.candidate_id,
            }
        return self._decision(QuantAgentAction.CREATE_CANDIDATE, arguments)

    def _finish(
        self,
        context: QuantAgentContext,
        conclusion: str,
        *,
        duplicate_proposal: tuple[str, dict[str, int | float]] | None = None,
    ) -> QuantAgentDecision:
        completed = {
            item.candidate_id: item for item in context.candidates if item.state == "completed"
        }
        selected_id, research_decision, decision_detail = final_research_selection(context)
        selected = completed.get(selected_id or "")
        if selected is None and context.iteration_feedback is not None:
            selected = completed.get(context.iteration_feedback.improvement_reference.candidate_id)
        objective = (
            context.approved_plan.selection_objective
            if context.approved_plan is not None
            else "risk_adjusted_return"
        )
        objective_label = {
            "risk_adjusted_return": "risk-adjusted return",
            "total_return": "total return",
            "drawdown_control": "drawdown control",
        }[objective]
        arguments: dict[str, object] = {
            "selected_candidate_id": selected.candidate_id if selected else None,
            "conclusion": conclusion
            if selected is None
            else (
                f"{conclusion} {selected.name} was selected for {objective_label}. "
                f"{decision_detail}"
            ),
            "next_step": "paper_evaluation" if selected else "stop",
        }
        if selected is not None and research_decision is not None:
            arguments["research_decision"] = research_decision
        feedback_children = [item for item in context.candidates if item.feedback_artifact_id]
        if context.iteration_feedback is not None and not feedback_children:
            feedback = context.iteration_feedback
            if duplicate_proposal is not None:
                arguments["replan_decision"] = {
                    "action": "stop_no_novel_candidate",
                    "source_comparison_artifact_id": feedback.comparison_artifact_id,
                    "improvement_reference_candidate_id": (
                        feedback.improvement_reference.candidate_id
                    ),
                    "proposed_template": duplicate_proposal[0],
                    "proposed_parameters": duplicate_proposal[1],
                }
                arguments["next_step"] = "stop"
            elif context.budget.remaining_iterations < 4:
                arguments["replan_decision"] = {
                    "action": "stop_insufficient_budget",
                    "source_comparison_artifact_id": feedback.comparison_artifact_id,
                    "improvement_reference_candidate_id": (
                        feedback.improvement_reference.candidate_id
                    ),
                }
                arguments["next_step"] = "stop"
        series = context.research_series
        if series is not None and context.latest_comparison is not None:
            if (
                "replan_decision" not in arguments
                and selected is not None
                and "precommit_one_refinement" in series.allowed_actions
            ):
                arguments["series_decision"] = {
                    "action": "refine_selected",
                    "source_comparison_artifact_id": context.latest_comparison.artifact_id,
                    "seed_candidate_id": selected.candidate_id,
                    "focus": "improve_walk_forward_stability",
                    "refinement_reason": (
                        "Use the final training comparison to test one bounded, canonical-distinct "
                        "refinement without using sealed holdout evidence."
                    ),
                }
            else:
                arguments["series_decision"] = {
                    "action": "stop",
                    "source_comparison_artifact_id": context.latest_comparison.artifact_id,
                }
        return self._decision(QuantAgentAction.FINISH_RESEARCH, arguments)


def load_quant_agent_provider() -> QuantAgentProvider:
    provider = os.environ.get("POKIEQUANT_AGENT_PROVIDER", "mock").strip().lower()
    if provider in {"", "mock"}:
        allow_mock_fallback()
        return MockQuantAgentProvider()
    if provider not in {"deepseek", "openai_compatible"}:
        raise QuantAgentProviderError("POKIEQUANT_AGENT_PROVIDER is invalid.")
    allow_mock_fallback()
    key = os.environ.get("POKIEQUANT_AGENT_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key or not key.strip():
        raise QuantAgentProviderError("The configured Quant Agent provider credential is missing.")
    base_url = os.environ.get("POKIEQUANT_AGENT_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL)
    model = os.environ.get("POKIEQUANT_AGENT_MODEL", DEFAULT_DEEPSEEK_MODEL)
    try:
        config = OpenAICompatibleConfig(
            SecretStr(key),
            base_url,
            model,
            timeout_seconds=(
                15.0 if os.environ.get("POKIEQUANT_AGENT_PROVIDER_TEST") == "true" else 45.0
            ),
            max_tokens=DEFAULT_QUANT_AGENT_MAX_TOKENS,
        )
    except OpenAICompatibleError:
        raise QuantAgentProviderError("Quant agent configuration is invalid.") from None
    default_profile = "deepseek" if provider == "deepseek" else "custom"
    profile = os.environ.get("POKIEQUANT_AGENT_REQUEST_PROFILE", default_profile).strip().lower()
    if profile not in _REQUEST_PROFILES:
        raise QuantAgentProviderError("Quant agent request profile is invalid.")
    identity = os.environ.get(
        "POKIEQUANT_AGENT_PROVIDER_IDENTITY",
        "deepseek" if provider in {"deepseek", "openai_compatible"} else provider,
    ).strip()
    if identity not in {
        "deepseek",
        "kimi_k3",
        "openai",
        "qwen",
        "custom_openai_compatible",
    }:
        raise QuantAgentProviderError("Quant agent provider identity is invalid.")
    return OpenAICompatibleProvider(
        config,
        request_profile=cast(RequestProfile, profile),
        provider_name=identity,
    )
