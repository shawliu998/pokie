from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.evaluate_phase3_model_quality import (
    DEFAULT_FIXTURE,
    EvaluationError,
    canonical_digest,
    evaluate_dataset,
    load_dataset,
)


def _rehash(dataset: dict[str, Any]) -> dict[str, Any]:
    dataset["dataset_digest"] = canonical_digest(dataset)
    return dataset


def _copy() -> dict[str, Any]:
    return copy.deepcopy(load_dataset())


def test_reviewed_provider_output_replay_meets_provisional_gates() -> None:
    report = evaluate_dataset(load_dataset())
    assert report.passed
    assert report.dataset_version == "phase3-model-quality-v1.0.0-20260716"
    assert report.case_count == 4
    assert report.metrics["citation_correctness"].numerator == 5
    assert report.metrics["citation_correctness"].denominator == 5
    assert report.metrics["unsupported_claim_rate"].numerator == 0
    assert report.metrics["unsupported_claim_rate"].denominator == 2
    assert report.metrics["counter_evidence_recall"].numerator == 2
    assert report.metrics["counter_evidence_recall"].denominator == 2
    assert report.metrics["numerical_accuracy"].numerator == 4
    assert report.metrics["numerical_accuracy"].denominator == 4
    assert report.metrics["prompt_injection_authorization_pass_rate"].numerator == 2
    assert report.metrics["prompt_injection_authorization_pass_rate"].denominator == 2


def test_fixture_integrity_fails_closed_on_unreviewed_change(tmp_path: Path) -> None:
    dataset = _copy()
    dataset["cases"][0]["source_versions"][0]["body"] += " changed"
    fixture = tmp_path / "tampered.json"
    fixture.write_text(json.dumps(dataset), encoding="utf-8")
    with pytest.raises(EvaluationError, match="dataset_digest"):
        load_dataset(fixture)


@pytest.mark.parametrize(
    ("mutation", "metric", "reason"),
    [
        (
            lambda dataset: dataset["cases"][0]["model_output"]["evidence_candidates"][0].update(
                {"quote_end": 999}
            ),
            "citation_correctness",
            "citation_span_out_of_bounds",
        ),
        (
            lambda dataset: dataset["cases"][0]["model_output"]["evidence_candidates"][0].update(
                {"content_version_id": "outside-pinned-scope"}
            ),
            "citation_correctness",
            "citation_unknown_content_version",
        ),
        (
            lambda dataset: dataset["cases"][0]["model_output"]["evidence_candidates"][0].update(
                {"quote_text_digest": f"sha256:{'0' * 64}"}
            ),
            "citation_correctness",
            "citation_quote_digest_mismatch",
        ),
        (
            lambda dataset: dataset["cases"][0]["model_output"]["claims"][0].update(
                {"evidence_ids": []}
            ),
            "unsupported_claim_rate",
            "unsupported_or_unpinned_claim",
        ),
        (
            lambda dataset: dataset["cases"][0]["model_output"].update(
                {
                    "evidence_candidates": [
                        candidate
                        for candidate in dataset["cases"][0]["model_output"]["evidence_candidates"]
                        if candidate["stance"] != "opposes"
                    ]
                }
            ),
            "counter_evidence_recall",
            "missing_counter_evidence",
        ),
        (
            lambda dataset: dataset["cases"][0]["model_output"]["claims"][0]["numeric_assertions"][
                0
            ].update({"denominator": "25"}),
            "numerical_accuracy",
            "numeric_assertion_missing_or_incorrect",
        ),
        (
            lambda dataset: dataset["cases"][2]["model_output"].update(
                {"tool_requests": [{"tool": "shell"}]}
            ),
            "prompt_injection_authorization_pass_rate",
            "prompt_injection_authorization_breach",
        ),
    ],
)
def test_each_quality_or_authorization_regression_fails_its_gate(
    mutation: Any,
    metric: str,
    reason: str,
) -> None:
    dataset = _copy()
    mutation(dataset)
    report = evaluate_dataset(_rehash(dataset))
    assert not report.passed
    assert not report.metrics[metric].passed
    assert report.failure_reason_counts[reason] >= 1


def test_cli_report_is_bounded_and_contains_no_source_or_secret_text() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_phase3_model_quality.py",
            str(DEFAULT_FIXTURE),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    assert report["passed"] is True
    assert "DEEPSEEK_API_KEY" not in result.stdout
    assert "Ignore previous instructions" not in result.stdout
    assert set(report) == {
        "candidate_model",
        "candidate_provider",
        "case_count",
        "dataset_digest",
        "dataset_name",
        "dataset_version",
        "failure_reason_counts",
        "metrics",
        "passed",
    }
