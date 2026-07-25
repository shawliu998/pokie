from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.verify_quant_kraken_deepseek_run import (
    EVIDENCE_FILE_NAME,
    SESSION_KEYS,
    V1ProofError,
    _credential_name_is_present,
    _official_deepseek_origin_is_configured,
    _response_json,
    find_forbidden_evidence_key,
    prepare_target,
    validate_agent_decision_path,
    validate_session_payload,
    write_json,
)


def test_prepare_target_fails_closed_and_reset_preserves_old_directory(tmp_path: Path) -> None:
    target = tmp_path / "v1-proof"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("retained")

    with pytest.raises(V1ProofError, match="target_exists"):
        prepare_target(target, reset=False)

    paths, backup = prepare_target(target, reset=True)

    assert paths.target == target
    assert paths.objects.is_dir()
    assert backup is not None
    assert (backup / "keep.txt").read_text() == "retained"


def test_session_payload_is_exactly_the_launch_compatible_non_key_shape() -> None:
    payload = {
        "principal_id": "principal",
        "workspace_id": "workspace",
        "run_id": "run",
        "dataset_id": "dataset",
        "database_path": "/tmp/runtime.db",
        "model": "deepseek-chat",
    }

    assert set(validate_session_payload(payload)) == SESSION_KEYS
    with pytest.raises(V1ProofError, match="session_metadata_shape_invalid"):
        validate_session_payload({**payload, "api_key": "must-not-persist"})


def test_sanitized_evidence_writer_rejects_secret_and_runtime_fields(tmp_path: Path) -> None:
    safe = {
        "schema_version": "qurio-v1-live-connector-proof-v1",
        "dataset": {"dataset_id": "dataset", "source_request_digest": "sha256:abc"},
        "agent": {"provider": "deepseek", "mock_fallback_allowed": False},
    }
    assert find_forbidden_evidence_key(safe) is None
    write_json(tmp_path / EVIDENCE_FILE_NAME, safe)

    unsafe = {**safe, "configuration": {"authorization": "must-not-persist"}}
    assert find_forbidden_evidence_key(unsafe) == "authorization"
    with pytest.raises(V1ProofError, match="forbidden_evidence_field"):
        write_json(tmp_path / EVIDENCE_FILE_NAME, unsafe)


def test_credential_presence_requires_a_nonempty_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POKIEQUANT_AGENT_API_KEY", "  ")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert _credential_name_is_present() is False

    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    assert _credential_name_is_present() is True


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.deepseek.com", True),
        ("https://api.deepseek.com/v1", True),
        ("https://api.deepseek.com.evil.invalid", False),
        ("https://proxy.example.com", False),
        ("http://api.deepseek.com", False),
    ],
)
def test_live_model_claim_requires_official_deepseek_origin(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("POKIEQUANT_AGENT_BASE_URL", base_url)
    assert _official_deepseek_origin_is_configured() is expected


def test_response_failure_retains_only_the_closed_api_error_code() -> None:
    response = SimpleNamespace(
        status_code=409,
        json=lambda: {
            "error": {
                "code": "INVALID_STATE",
                "message": "Safe but intentionally not copied into the evidence code.",
            }
        },
    )

    with pytest.raises(V1ProofError, match="http_409_invalid_state"):
        _response_json(response, stage="market_run_create", expected_status=201)


def _decision_bundle(
    *,
    candidates: list[dict[str, object]],
    report_replan: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "plan": {
            "budgets": {
                "max_agent_iterations": 12,
                "max_experiments": 3,
                "max_repairs": 1,
            }
        },
        "selected_result": {"replan_decision": report_replan},
        "candidates": candidates,
    }


def _candidate(
    ordinal: int,
    *,
    replan_decision: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": f"candidate-{ordinal}",
        "canonical_key": f"sha256:{ordinal:064x}",
        "replan_decision": replan_decision,
    }


def test_decision_path_accepts_strict_two_plus_one() -> None:
    candidates = [
        _candidate(1),
        _candidate(2),
        _candidate(
            3,
            replan_decision={
                "action": "refine_parameters",
                "source_comparison_artifact_id": "comparison-a-b",
                "improvement_reference_candidate_id": "candidate-2",
            },
        ),
    ]

    result = validate_agent_decision_path(
        bundle=_decision_bundle(candidates=candidates, report_replan=None),
        candidates=candidates,
        run={"used_experiments": 3, "agent_iteration": 10},
        comparison_artifact={"artifact_id": "comparison-final"},
    )

    assert result == {
        "path": "A/B -> C",
        "completion_kind": "evidence_driven_iteration",
        "replan_action": "refine_parameters",
        "base_candidate_count": 2,
        "iteration_candidate_count": 1,
        "structured_stop": False,
    }


def test_decision_path_accepts_budget_bound_structured_stop() -> None:
    candidates = [_candidate(1), _candidate(2)]
    stop = {
        "action": "stop_insufficient_budget",
        "source_comparison_artifact_id": "comparison-final",
        "improvement_reference_candidate_id": "candidate-2",
        "proposed_template": None,
        "proposed_parameters": None,
    }

    result = validate_agent_decision_path(
        bundle=_decision_bundle(candidates=candidates, report_replan=stop),
        candidates=candidates,
        run={"used_experiments": 2, "agent_iteration": 9},
        comparison_artifact={"artifact_id": "comparison-final"},
    )

    assert result["path"] == "A/B -> Stop"
    assert result["replan_action"] == "stop_insufficient_budget"


def test_decision_path_rejects_plain_a_b_completion() -> None:
    candidates = [_candidate(1), _candidate(2)]

    with pytest.raises(V1ProofError, match="structured_stop_missing"):
        validate_agent_decision_path(
            bundle=_decision_bundle(candidates=candidates, report_replan=None),
            candidates=candidates,
            run={"used_experiments": 2, "agent_iteration": 12},
            comparison_artifact={"artifact_id": "comparison-final"},
        )


def test_decision_path_rejects_stop_while_action_budget_remains() -> None:
    candidates = [_candidate(1), _candidate(2)]
    stop = {
        "action": "stop_insufficient_budget",
        "source_comparison_artifact_id": "comparison-final",
        "improvement_reference_candidate_id": "candidate-1",
        "proposed_template": None,
        "proposed_parameters": None,
    }

    with pytest.raises(V1ProofError, match="structured_stop_budget_still_sufficient"):
        validate_agent_decision_path(
            bundle=_decision_bundle(candidates=candidates, report_replan=stop),
            candidates=candidates,
            run={"used_experiments": 2, "agent_iteration": 8},
            comparison_artifact={"artifact_id": "comparison-final"},
        )
