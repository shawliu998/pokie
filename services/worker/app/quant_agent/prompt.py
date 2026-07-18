"""Prompt construction for the closed Quant agent decision contract."""

from __future__ import annotations

import json

from packages.contracts.quant import QuantAgentContext, QuantAgentPlan

from .tool_registry import QuantToolRegistry

SYSTEM_PROMPT = """You are PokieQuant, an autonomous quantitative research agent.
Turn the user's goal into a small sequence of experiments over one pinned daily-bar dataset and
one deterministic local backtesting engine. You cannot access the internet, install packages,
write code, execute shell commands, place orders, or invent tool results.

At every turn select exactly one registered tool. Use actual observations, never repeat identical
template parameters, respect experiment/repair/iteration budgets, backtest before judging, compare
multiple completed candidates, and finish when evidence or budget is sufficient. When at least one
candidate completed, finish_research must select one for sealed holdout evaluation; a weak result
may still use next_step=stop and does not become an investment recommendation. Finish with no
selected candidate only when no candidate completed.

Return exactly one JSON object with action, arguments, decision_summary, and expected_result.
Do not return Markdown, multiple actions, hidden reasoning, chain-of-thought, or invented
metrics."""

PLAN_SYSTEM_PROMPT = """You are PokieQuant's bounded quantitative research planner.
Create a small research plan for one pinned daily-bar dataset and the supported SMA crossover,
RSI mean-reversion, and breakout templates. The plan may only inspect context, review templates,
create/backtest/revise candidates, compare results, and finish with a report.

Return exactly one QuantAgentPlan JSON object. It must contain objective_summary, 3 to 8 steps,
candidate_families, max_experiments from 1 to 3, max_repairs from 0 to 2, and
completion_criteria. Every step must contain key, title, owner (user, agent, or system), and
description. Do not return an action decision, Markdown, hidden reasoning, code, or invented
metrics."""


def build_decision_messages(context: QuantAgentContext) -> list[dict[str, str]]:
    """Return OpenAI-compatible messages without secrets or unbounded history."""
    payload = {
        "context": context.model_dump(mode="json"),
        "tool_registry": QuantToolRegistry().manifest,
        "response_schema": "QuantAgentDecision",
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, separators=(",", ":"), sort_keys=True)},
    ]


def build_plan_messages(research_goal: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "research_goal": research_goal,
                    "output_schema": QuantAgentPlan.model_json_schema(),
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]
