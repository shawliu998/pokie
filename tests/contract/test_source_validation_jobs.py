from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.contracts.schemas import SourceValidationJobResponse


def _job(**changes: object) -> dict[str, object]:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "source_connection_id": str(uuid4()),
        "command": "health_check",
        "state": "queued",
        "expected_source_row_version": 2,
        "attempt": 0,
        "result_source_status": None,
        "failure_code": None,
        "failure_reason": None,
        "lease_expires_at": None,
        "created_at": now,
        "updated_at": now,
        "data_authenticity": "collected",
    }
    payload.update(changes)
    return payload


def test_source_validation_job_contract_closes_commands_and_terminal_statuses() -> None:
    completed = SourceValidationJobResponse.model_validate(
        _job(state="completed", command="reconnect", result_source_status="auth_required")
    )
    assert completed.result_source_status == "auth_required"

    with pytest.raises(ValidationError):
        SourceValidationJobResponse.model_validate(_job(command="validate"))
    with pytest.raises(ValidationError, match="terminal source status"):
        SourceValidationJobResponse.model_validate(
            _job(state="completed", result_source_status="validating")
        )


def test_claimed_source_validation_job_requires_lease_projection() -> None:
    with pytest.raises(ValidationError, match="active lease"):
        SourceValidationJobResponse.model_validate(_job(state="claimed", attempt=1))
    claimed = SourceValidationJobResponse.model_validate(
        _job(
            state="claimed",
            attempt=1,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=2),
        )
    )
    assert claimed.attempt == 1
