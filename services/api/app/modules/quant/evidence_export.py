"""Deterministic export of persisted Quant evidence; this module never evaluates a strategy."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any, NoReturn

from packages.contracts.quant.enums import QuantArtifactKind
from packages.contracts.quant.evidence_export import (
    STRATEGY_EVIDENCE_BUNDLE_MAX_BYTES,
    STRATEGY_EVIDENCE_BUNDLE_SCHEMA_VERSION,
)
from packages.domain.canonical import canonical_digest
from services.api.app.core.errors import invalid_state
from services.api.app.modules.quant.store import QuantStore


def _copy(value: Any) -> Any:
    """Copy JSON-persisted values without normalizing or calculating them."""

    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:  # pragma: no cover - persisted state is JSON
        raise invalid_state("Persisted evidence cannot be exported as JSON.") from exc


def _fail(message: str) -> NoReturn:
    raise invalid_state(f"The persisted evidence bundle is incomplete or inconsistent: {message}")


def _single(items: Iterable[Any], *, label: str) -> Any:
    values = list(items)
    if len(values) != 1:
        _fail(f"exactly one {label} is required")
    return values[0]


def _artifact_ref(artifact: Any) -> dict[str, str]:
    return {"artifact_id": artifact.id, "stored_digest": artifact.digest}


def _plan_ref(artifact: Any) -> dict[str, str]:
    """Plan digests predate canonical artifact digests; do not mislabel them."""

    return {"artifact_id": artifact.id}


def _manifest(role: str, artifact: Any, candidate_id: str | None = None) -> dict[str, str]:
    item = {
        "role": role,
        "kind": artifact.kind.value,
        "artifact_id": artifact.id,
        "stored_digest": artifact.digest,
    }
    if candidate_id is not None:
        item["candidate_id"] = candidate_id
    return item


def _safe_filename(symbol: str, run_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", symbol.lower()).strip("-")
    return f"qurio-{(normalized or 'market')[:72]}-evidence-{run_id[:8]}.json"


def _verify_artifact(artifact: Any, *, run: Any, kind: QuantArtifactKind, label: str) -> None:
    if (
        artifact.workspace_id != run.workspace_id
        or artifact.run_id != run.id
        or artifact.kind is not kind
        or artifact.digest != canonical_digest(artifact.content)
    ):
        _fail(f"{label} identity or digest does not match")


def _forbidden(value: Any) -> str | None:
    blocked = {
        "learning_trace",
        "repair_memory",
        "repair_memory_reuse",
        "reuse_receipt",
        "iteration_feedback",
        "feedback_artifact_id",
        "events",
        "event_id",
        "trace_id",
        "tool_args",
        "provider_output",
        "prompt",
        "raw_bars",
        "bars",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in blocked:
                return key
            nested = _forbidden(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _forbidden(item)
            if nested is not None:
                return nested
    return None


def build_strategy_evidence_bundle_export(
    *, workspace_id: str, run_id: str, candidate_id: str
) -> dict[str, Any]:
    """Return one final-candidate bundle copied solely from current Run records."""

    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    if run.state.value != "completed":
        _fail("a completed Run is required")
    artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
    candidates = sorted(
        store.experiments_for_run(workspace_id=workspace_id, run_id=run.id),
        key=lambda item: item.ordinal,
    )
    if any(item.workspace_id != workspace_id or item.run_id != run.id for item in candidates):
        _fail("candidate ownership does not match")

    plan = _single(
        (item for item in artifacts if item.id == run.plan_artifact_id), label="plan artifact"
    )
    if (
        plan.workspace_id != workspace_id
        or plan.run_id != run.id
        or plan.kind is not QuantArtifactKind.PLAN
        or plan.id != run.plan_artifact_id
    ):
        _fail("plan artifact identity does not match")
    report = _single(
        (item for item in artifacts if item.kind is QuantArtifactKind.RESEARCH_REPORT),
        label="research report",
    )
    _verify_artifact(
        report,
        run=run,
        kind=QuantArtifactKind.RESEARCH_REPORT,
        label="research report",
    )
    report_content = report.content
    selected_id = report_content.get("selected_candidate_id")
    if not isinstance(selected_id, str):
        _fail("report selected candidate is missing")
    if candidate_id != selected_id:
        # JSON is deliberately final-report-only; Markdown retains its alternative candidate view.
        _fail("JSON export is available only for the report-selected candidate")
    selected = next((item for item in candidates if item.id == selected_id), None)
    if selected is None:
        _fail("report selected candidate is not owned by this Run")

    completed = [item for item in candidates if item.state == "completed"]
    if not completed or selected not in completed:
        _fail("selected candidate has no completed persisted result")
    research_decision = report_content.get("research_decision")
    generalization = report_content.get("generalization")
    if (
        not isinstance(research_decision, dict)
        or research_decision.get("selected_candidate_id") != selected.id
        or not isinstance(generalization, dict)
        or generalization.get("selected_candidate_id") != selected.id
    ):
        _fail("report final-candidate identities do not match")
    comparison_id = research_decision.get("source_comparison_artifact_id")
    if not isinstance(comparison_id, str):
        _fail("report final comparison reference is missing")
    final_comparisons = []
    completed_ids = [item.id for item in completed]
    for item in artifacts:
        if item.kind is not QuantArtifactKind.VALIDATION_REPORT:
            continue
        if item.content.get("evaluation_partition") != "train":
            continue
        _verify_artifact(
            item,
            run=run,
            kind=QuantArtifactKind.VALIDATION_REPORT,
            label="comparison",
        )
        rows = item.content.get("candidates")
        ranking = item.content.get("ranking")
        if not isinstance(rows, list) or not isinstance(ranking, list):
            _fail("comparison rows or ranking are missing")
        row_ids = [row.get("candidate_id") for row in rows if isinstance(row, dict)]
        if (
            len(row_ids) == len(rows)
            and set(row_ids) == set(completed_ids)
            and len(row_ids) == len(completed_ids)
            and len(ranking) == len(completed_ids)
            and set(ranking) == set(completed_ids)
            and item.id == comparison_id
        ):
            final_comparisons.append(item)
    comparison = _single(final_comparisons, label="report-bound final training comparison")
    comparison_rows = comparison.content.get("candidates")
    if not isinstance(comparison_rows, list) or not all(
        isinstance(row, dict) and isinstance(row.get("candidate_id"), str)
        for row in comparison_rows
    ):
        _fail("final comparison candidate rows are invalid")
    comparison_by_id = {row["candidate_id"]: row for row in comparison_rows}
    if len(comparison_by_id) != len(completed_ids) or set(comparison_by_id) != set(completed_ids):
        _fail("final comparison candidate identities do not match")
    if (
        comparison.ordinal >= report.ordinal
        or comparison.content.get("benchmark") != report_content.get("benchmark")
        or comparison_by_id[selected.id].get("walk_forward") != report_content.get("walk_forward")
    ):
        _fail("report final comparison evidence does not match")

    specs: dict[str, Any] = {}
    backtests: dict[str, Any] = {}
    curves: dict[str, Any] = {}
    trades: dict[str, Any] = {}
    for candidate in completed:
        matching_specs = [
            item
            for item in artifacts
            if item.kind is QuantArtifactKind.STRATEGY_SPEC
            and item.content.get("template") == candidate.template
            and item.content.get("parameters") == candidate.parameters
        ]
        specs[candidate.id] = _single(matching_specs, label=f"strategy spec for {candidate.id}")
        backtests[candidate.id] = _single(
            (
                item
                for item in artifacts
                if item.kind is QuantArtifactKind.BACKTEST_RESULT
                and item.content.get("candidate_id") == candidate.id
            ),
            label=f"backtest result for {candidate.id}",
        )
        curves[candidate.id] = _single(
            (
                item
                for item in artifacts
                if item.kind is QuantArtifactKind.EQUITY_CURVE
                and item.content.get("candidate_id") == candidate.id
            ),
            label=f"equity curve for {candidate.id}",
        )
        trades[candidate.id] = _single(
            (
                item
                for item in artifacts
                if item.kind is QuantArtifactKind.TRADE_LOG
                and item.content.get("candidate_id") == candidate.id
            ),
            label=f"trade log for {candidate.id}",
        )
        for label, artifact, kind in (
            ("strategy spec", specs[candidate.id], QuantArtifactKind.STRATEGY_SPEC),
            ("backtest result", backtests[candidate.id], QuantArtifactKind.BACKTEST_RESULT),
            ("equity curve", curves[candidate.id], QuantArtifactKind.EQUITY_CURVE),
            ("trade log", trades[candidate.id], QuantArtifactKind.TRADE_LOG),
        ):
            _verify_artifact(artifact, run=run, kind=kind, label=label)
        backtest = backtests[candidate.id].content
        if (
            backtest.get("evaluation_partition") != "train"
            or backtest.get("candidate_id") != candidate.id
            or backtest.get("metrics") != candidate.metrics
            or comparison_by_id[candidate.id].get("candidate_id") != candidate.id
            or any(
                comparison_by_id[candidate.id].get(metric) != value
                for metric, value in candidate.metrics.items()
            )
        ):
            _fail(f"candidate {candidate.id} persisted metrics do not match")

    robustness_link = report_content.get("robustness_sensitivity")
    if not isinstance(robustness_link, dict):
        _fail("report robustness reference is missing")
    robustness = _single(
        (
            item
            for item in artifacts
            if item.kind is QuantArtifactKind.ROBUSTNESS_SENSITIVITY
            and item.id == robustness_link.get("artifact_id")
        ),
        label="robustness sensitivity artifact",
    )
    _verify_artifact(
        robustness,
        run=run,
        kind=QuantArtifactKind.ROBUSTNESS_SENSITIVITY,
        label="robustness sensitivity artifact",
    )
    if (
        robustness_link.get("artifact_digest") != robustness.digest
        or robustness.content.get("schema_version") != "robustness_sensitivity_v1"
        or robustness.content.get("run_id") != run.id
        or robustness.content.get("report_artifact_id") != report.id
        or robustness.content.get("candidate", {}).get("candidate_id") != selected.id
        or robustness.content.get("final_training_comparison", {}).get("artifact_id")
        != comparison.id
        or robustness.ordinal <= comparison.ordinal
        or robustness.ordinal >= report.ordinal
    ):
        _fail("robustness sensitivity identity does not match")

    dataset = report_content.get("dataset")
    if not isinstance(dataset, dict) or dataset.get("dataset_id") != run.dataset_id:
        _fail("report dataset identity does not match")
    if dataset.get("digest") != run.dataset_digest:
        _fail("report dataset digest does not match")
    runtime_projection = store.runtime_projection(run)
    runtime = runtime_projection.descriptor
    split = runtime_projection.split
    if runtime_projection.market_record is not None:
        if (
            dataset.get("symbol") != runtime.symbol
            or dataset.get("interval") != runtime.interval.value
            or dataset.get("periods_per_year") != runtime.periods_per_year
            or dataset.get("start") != runtime.coverage_start_utc.isoformat()
            or dataset.get("end") != runtime.coverage_end_utc.isoformat()
            or dataset.get("bars") != len(runtime.bars)
            or run.market_run_contract_version != "quant-market-run-v2"
            or dataset.get("runtime_descriptor_digest") != runtime.descriptor_digest
            or dataset.get("sealed_split_digest") != split.seal_digest
            or dataset.get("split")
            != {
                "method": split.metadata["method"],
                "rule_version": split.metadata["rule_version"],
                "train_bar_count": split.metadata["train_bar_count"],
                "train_start": split.metadata["train_start"],
                "train_end": split.metadata["train_end"],
                "dataset_id": split.metadata["dataset_id"],
                "dataset_digest": split.metadata["dataset_digest"],
                "interval": split.metadata["interval"],
                "periods_per_year": split.metadata["periods_per_year"],
            }
        ):
            _fail("report market dataset pins do not match")
    elif (
        run.market_run_contract_version is not None
        or runtime.interval.value != "1D"
        or dataset.get("symbol") != runtime.symbol
        or dataset.get("interval") != "1D"
        or dataset.get("start") != runtime.coverage_start_utc.date().isoformat()
        or dataset.get("end") != runtime.coverage_end_utc.date().isoformat()
        or dataset.get("bars") != len(runtime.bars)
        or dataset.get("periods_per_year") is not None
        or any(
            value is not None
            for value in (
                run.research_start_utc,
                run.research_end_utc,
                run.runtime_interval,
                run.runtime_periods_per_year,
                run.runtime_descriptor_digest,
                run.runtime_split_digest,
            )
        )
        or dataset.get("runtime_descriptor_digest") is not None
        or dataset.get("sealed_split_digest") is not None
        or dataset.get("split") != split.metadata
    ):
        _fail("report legacy dataset pins do not match")
    plan_content = plan.content
    required_plan = (
        "objective_summary",
        "candidate_families",
        "strategy_scope",
        "selection_objective",
        "completion_criteria",
    )
    if (
        any(key not in plan_content for key in required_plan)
        or plan_content.get("selection_objective") != run.selection_objective
    ):
        _fail("plan content is incomplete")
    if (
        plan_content.get("objective_summary") != run.plan_summary
        or plan_content.get("candidate_families") != run.planned_candidate_families
        or plan_content.get("strategy_scope") != run.strategy_scope.model_dump(mode="json")
        or plan_content.get("completion_criteria") != run.completion_criteria
        or plan_content.get("selection_objective") != run.selection_objective
    ):
        _fail("plan content does not match the Run")

    candidate_items: list[dict[str, Any]] = []
    manifest = [
        _manifest("research_report", report),
        _manifest("final_training_comparison", comparison),
    ]
    for candidate in completed:
        candidate_items.append(
            {
                "candidate_id": candidate.id,
                "ordinal": candidate.ordinal,
                "name": candidate.name,
                "hypothesis": candidate.hypothesis,
                "template": candidate.template,
                "parameters": _copy(candidate.parameters),
                "canonical_key": candidate.candidate_key,
                "state": candidate.state,
                "verdict": candidate.verdict.value,
                "metrics": _copy(candidate.metrics),
                "parent_candidate_id": candidate.parent_experiment_id,
                "change_rationale": candidate.change_rationale,
                "replan_decision": (
                    candidate.replan_decision.model_dump(mode="json")
                    if candidate.replan_decision is not None
                    else None
                ),
                "strategy_spec": _artifact_ref(specs[candidate.id]),
                "backtest_result": _artifact_ref(backtests[candidate.id]),
            }
        )
        manifest.extend(
            (
                _manifest("strategy_spec", specs[candidate.id], candidate.id),
                _manifest("backtest_result", backtests[candidate.id], candidate.id),
                _manifest("equity_curve", curves[candidate.id], candidate.id),
                _manifest("trade_log", trades[candidate.id], candidate.id),
            )
        )
    manifest.append(_manifest("robustness_sensitivity", robustness, selected.id))

    series_decision = None
    if run.research_series_decision is not None:
        decision = run.research_series_decision
        series_decision = {
            "schema_version": decision.schema_version,
            "evaluation_partition": decision.evaluation_partition,
            "action": decision.action,
            "source_comparison_artifact_id": decision.source_comparison_artifact_id,
            "seed_candidate_id": decision.seed_candidate_id,
        }
    retained_range = {
        "start": dataset.get("start"),
        "end": dataset.get("end"),
        "bar_count": dataset.get("bars"),
    }
    bundle = {
        "schema_version": STRATEGY_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "run": {
            "project_id": run.project_id,
            "run_id": run.id,
            "contract": run.market_run_contract_version or "quant-daily-run-v1",
            "attempt_number": run.attempt_number,
            "mode": run.mode.value,
            "question": run.question,
            "provider": run.provider,
            "model": run.model,
            "data_authenticity": run.data_authenticity.value,
            "created_at": run.created_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
        },
        "lineage": {
            "parent_run_id": run.parent_run_id,
            "seed_candidate_id": run.seed_candidate_id,
            "refinement_reason": run.refinement_reason,
            "retry_of_run_id": run.retry_of_run_id,
            "retry_child_run_id": run.retry_child_run_id,
            "root_run_id": run.research_series_root_run_id,
            "version_number": run.research_series_version,
            "child_run_id": run.research_series_child_run_id,
            "series_decision": series_decision,
        },
        "dataset": {
            "contract": run.market_run_contract_version or "quant-daily-run-v1",
            "dataset_id": run.dataset_id,
            "dataset_digest": run.dataset_digest,
            "symbol": dataset.get("symbol"),
            "interval": dataset.get("interval"),
            "periods_per_year": dataset.get("periods_per_year"),
            "retained_range": retained_range,
            "runtime_descriptor_digest": dataset.get("runtime_descriptor_digest"),
            "sealed_split_digest": dataset.get("sealed_split_digest"),
            "source_metadata": _copy(dataset.get("source_metadata")),
            "data_quality": _copy(dataset.get("data_quality")),
            "evaluation_split": _copy(dataset.get("split")),
        },
        "plan": {
            "artifact": _plan_ref(plan),
            "revision": run.plan_revision,
            **{key: _copy(plan_content[key]) for key in required_plan},
            "budgets": {
                "max_agent_iterations": run.max_agent_iterations,
                "max_experiments": run.max_experiments,
                "max_repairs": run.max_repairs,
            },
        },
        "candidates": candidate_items,
        "final_training_comparison": {
            "artifact": _artifact_ref(comparison),
            **_copy(comparison.content),
        },
        "selected_result": {
            "candidate_id": selected.id,
            "research_decision": _copy(research_decision),
            "replan_decision": _copy(report_content.get("replan_decision")),
            "conclusion": report_content.get("conclusion"),
            "next_step": report_content.get("next_step"),
            "report": _artifact_ref(report),
        },
        "candidate_curves": [
            {
                "candidate_id": item.id,
                "artifact": _artifact_ref(curves[item.id]),
                "points": _copy(curves[item.id].content.get("points")),
            }
            for item in completed
        ],
        "selected_candidate_trades": {
            "candidate_id": selected.id,
            "artifact": _artifact_ref(trades[selected.id]),
            "rows": _copy(trades[selected.id].content.get("trades")),
        },
        "validation": {
            "generalization": _copy(generalization),
            "walk_forward": _copy(report_content.get("walk_forward")),
            "robustness_sensitivity": {
                "artifact": _artifact_ref(robustness),
                "content": _copy(robustness.content),
            },
        },
        "limitations": _copy(report_content.get("limitations")),
        "artifact_manifest": sorted(manifest, key=lambda item: (item["role"], item["artifact_id"])),
    }
    forbidden = _forbidden(bundle)
    if forbidden is not None:
        _fail(f"forbidden {forbidden} content would leak")
    rendered = (
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    payload = rendered.encode("utf-8")
    if len(payload) > STRATEGY_EVIDENCE_BUNDLE_MAX_BYTES:
        _fail("bundle exceeds the 1 MiB JSON export limit")
    return {
        "export_type": "strategy_evidence_bundle_json",
        "run_id": run.id,
        "candidate_id": selected.id,
        "data_authenticity": run.data_authenticity.value,
        "filename": _safe_filename(str(dataset.get("symbol") or "market"), run.id),
        "media_type": "application/json",
        "rendered_content": rendered,
        "content_digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
    }
