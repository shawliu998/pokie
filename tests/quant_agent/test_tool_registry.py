from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from packages.contracts.quant import QuantAgentAction
from services.api.app.modules.quant.store import QuantFixtureLease, QuantStore
from services.worker.app.quant_agent.tool_registry import (
    QuantToolExecutionContext,
    QuantToolRegistry,
    _CreateCandidateTool,
)


class _StoreThatMustNotMutate:
    def create_agent_candidate(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("invalid parameters must fail before persistence")


def test_invalid_candidate_parameters_fail_before_store_mutation() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observation = _CreateCandidateTool().execute(
        context=QuantToolExecutionContext(
            store=cast(QuantStore, _StoreThatMustNotMutate()),
            lease=lease,
        ),
        arguments={
            "name": "invalid SMA",
            "template": "sma_crossover",
            "hypothesis": "This must be rejected.",
            "parameters": {"fast_window": 50, "slow_window": 20},
        },
    )

    assert not observation.success
    assert observation.error_code == "INVALID_PARAMETERS"


def test_empty_argument_tool_rejects_unknown_fields() -> None:
    lease = QuantFixtureLease(
        workspace_id="workspace",
        run_id="run",
        token="token",
        fencing_version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observation = QuantToolRegistry().execute(
        action=QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
        context=QuantToolExecutionContext(
            store=cast(QuantStore, _StoreThatMustNotMutate()),
            lease=lease,
        ),
        arguments={"unexpected": True},
    )

    assert not observation.success
    assert observation.error_code == "INVALID_ARGUMENTS"
