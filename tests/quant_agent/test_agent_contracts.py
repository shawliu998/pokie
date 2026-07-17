from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.contracts.quant import QuantAgentDecision, QuantToolObservation


def test_decision_is_closed_and_single_action() -> None:
    decision = QuantAgentDecision.model_validate(
        {
            "action": "inspect_research_context",
            "arguments": {},
            "decision_summary": "Inspect context.",
            "expected_result": "A context summary.",
        }
    )
    assert decision.action.value == "inspect_research_context"
    with pytest.raises(ValidationError):
        QuantAgentDecision.model_validate({**decision.model_dump(), "extra": True})


def test_observation_is_closed() -> None:
    observation = QuantToolObservation(
        action="create_candidate", success=True, safe_summary="Created."
    )
    assert observation.artifact_ids == []
