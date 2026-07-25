from __future__ import annotations

import hashlib
import html
import re
from datetime import date
from typing import Any

from packages.contracts.quant.enums import QuantArtifactKind
from services.api.app.core.errors import invalid_state, not_found
from services.api.app.modules.quant.store import QuantStore, user_facing_report_text

MAX_REPORT_EXPORT_BYTES = 256_000
MAX_EXPORTED_TRADES = 200


def _elapsed_duration(seconds: int) -> str:
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")
    return " ".join(parts) or "0h"


def _text(value: Any) -> str:
    """Render retained values as Markdown text without allowing raw HTML."""

    normalized = " ".join(str(value).split())
    return html.escape(normalized, quote=False).replace("\\", "\\\\").replace("|", "\\|")


def _number(value: Any, digits: int = 1) -> str:
    if not isinstance(value, int | float):
        return "—"
    return f"{value:.{digits}f}"


def _percent(value: Any) -> str:
    if not isinstance(value, int | float):
        return "—"
    return f"{'+' if value > 0 else ''}{value:.1f}%"


def _metric(metrics: dict[str, Any], key: str) -> float | int | None:
    value = metrics.get(key)
    return value if isinstance(value, int | float) else None


def _filename(*, symbol: str, candidate_name: str, run_id: str) -> str:
    stem = re.sub(
        r"[^a-z0-9]+",
        "-",
        f"qurio-{symbol}-{candidate_name}-{run_id[:8]}".lower(),
    ).strip("-")
    return f"{(stem or 'qurio-strategy-report')[:116].rstrip('-')}.md"


def _strategy_spec(template: str, parameters: dict[str, Any]) -> list[str]:
    lines = [f"    template: {_text(template)}", "    parameters:"]
    if not parameters:
        lines.append("      {}")
    else:
        for key in sorted(parameters):
            lines.append(f"      {_text(key)}: {_text(parameters[key])}")
    return lines


def build_strategy_report_export(
    *, workspace_id: str, run_id: str, candidate_id: str
) -> dict[str, Any]:
    """Render one deterministic report from workspace-owned persisted Quant records."""

    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    project = store.get_project(workspace_id=workspace_id, project_id=run.project_id)
    artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
    reports = [
        artifact
        for artifact in artifacts
        if artifact.kind is QuantArtifactKind.RESEARCH_REPORT and artifact.content
    ]
    if not reports:
        raise invalid_state("This run has no completed strategy report to export.")
    report = max(reports, key=lambda item: item.ordinal).content
    candidate = next(
        (
            item
            for item in store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
            if item.id == candidate_id
        ),
        None,
    )
    if candidate is None:
        raise not_found("QuantCandidate")
    if not candidate.metrics:
        raise invalid_state("The selected candidate has no completed metrics to export.")

    runtime_projection = store.runtime_projection(run)
    runtime = runtime_projection.descriptor
    is_market_runtime = runtime_projection.market_record is not None
    dataset = report.get("dataset")
    if not isinstance(dataset, dict):
        dataset = store.agent_dataset_summary(run)
    benchmark = report.get("benchmark")
    if not isinstance(benchmark, dict):
        benchmark = store.agent_benchmark_summary(run)
    metrics = candidate.metrics
    candidate_return = _metric(metrics, "annualized_return_pct")
    benchmark_return = _metric(benchmark, "annualized_return_pct")
    return_delta = (
        candidate_return - benchmark_return
        if candidate_return is not None and benchmark_return is not None
        else None
    )
    candidate_sharpe = _metric(metrics, "sharpe_ratio")
    benchmark_sharpe = _metric(benchmark, "sharpe_ratio")
    sharpe_delta = (
        candidate_sharpe - benchmark_sharpe
        if candidate_sharpe is not None and benchmark_sharpe is not None
        else None
    )
    candidate_drawdown = _metric(metrics, "maximum_drawdown_pct")
    benchmark_drawdown = _metric(benchmark, "maximum_drawdown_pct")
    drawdown_delta = (
        candidate_drawdown - benchmark_drawdown
        if candidate_drawdown is not None and benchmark_drawdown is not None
        else None
    )
    candidate_trades = _metric(metrics, "trade_count")
    benchmark_trades = _metric(benchmark, "trade_count")
    trades_delta = (
        candidate_trades - benchmark_trades
        if candidate_trades is not None and benchmark_trades is not None
        else None
    )

    symbol = runtime.symbol
    interval = runtime.interval.value
    periods_per_year = runtime.periods_per_year
    start = (
        runtime.coverage_start_utc.isoformat()
        if is_market_runtime
        else run.research_start.isoformat()
    )
    end = (
        runtime.coverage_end_utc.isoformat() if is_market_runtime else run.research_end.isoformat()
    )
    parameters = candidate.parameters
    parameter_text = (
        ", ".join(f"{_text(key)}={_text(parameters[key])}" for key in sorted(parameters)) or "None"
    )
    generalization = report.get("generalization")
    report_candidate_id = (
        generalization.get("selected_candidate_id") if isinstance(generalization, dict) else None
    )
    is_final_candidate = report_candidate_id == candidate.id
    conclusion = (
        _text(
            user_facing_report_text(
                report.get("conclusion") or run.final_conclusion,
                fallback=(
                    f"The final training comparison selected {candidate.name} for sealed "
                    "holdout evaluation."
                ),
            )
        )
        if is_final_candidate
        else (
            "This candidate was not the Run's final selection; its metrics and trades are "
            "retained here without a sealed-holdout conclusion."
        )
    )
    recommendation = (
        _text(str(report.get("next_step") or "No recommendation retained.").replace("_", " "))
        if is_final_candidate
        else (
            "Compare this candidate with the selected strategy or continue research "
            "from this candidate."
        )
    )
    selection_lines: list[str] = []
    research_decision = report.get("research_decision")
    if is_final_candidate and isinstance(research_decision, dict):
        basis = research_decision.get("decision_basis")
        deviation = research_decision.get("deviation")
        if basis == "approved_objective_rank":
            selection_lines = [
                "",
                "## Selection Decision",
                "",
                "- Selection basis: Approved objective rank",
                "- Deviation: None",
                "- Reference candidate: —",
            ]
        elif basis == "robustness_override" and isinstance(deviation, dict):
            reason = deviation.get("reason")
            reference_id = deviation.get("reference_candidate_id")
            reason_label = {
                "walk_forward_stability": "Walk-forward stability",
                "regime_coverage": "Regime coverage",
                "minimum_trade_evidence": "Minimum trade evidence",
            }.get(str(reason))
            reference = next(
                (
                    item
                    for item in store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
                    if item.id == reference_id
                ),
                None,
            )
            if reason_label is not None and isinstance(reference_id, str):
                selection_lines = [
                    "",
                    "## Selection Decision",
                    "",
                    "- Selection basis: Server-validated robustness override",
                    f"- Deviation: {_text(reason_label)}",
                    (
                        f"- Reference candidate: {_text(reference.name)} ({_text(reference_id)})"
                        if reference is not None
                        else f"- Reference candidate: {_text(reference_id)}"
                    ),
                ]
    lines = [
        f"# {_text(symbol)} Strategy Report",
        "",
        "## Research Context",
        "",
        f"- Project: {_text(project.name)}",
        f"- Research question: {_text(run.question)}",
        f"- Dataset: {_text(symbol)} · {_text(interval)}",
        f"- Research range: {_text(start)} to {_text(end)}",
        f"- Annualization: {_text(periods_per_year)} periods per year",
        "",
        "## Selected Strategy",
        "",
        f"- Strategy: {_text(candidate.name)}",
        f"- Parameters: {parameter_text}",
        *selection_lines,
        "",
        "## Strategy vs Benchmark",
        "",
        "| Metric | Strategy | Benchmark | Difference |",
        "|---|---:|---:|---:|",
        "| Annual return | "
        f"{_percent(candidate_return)} | {_percent(benchmark_return)} | "
        f"{_percent(return_delta)} |",
        "| Sharpe | "
        f"{_number(candidate_sharpe, 2)} | {_number(benchmark_sharpe, 2)} | "
        f"{_number(sharpe_delta, 2)} |",
        "| Maximum drawdown | "
        f"{_percent(candidate_drawdown)} | {_percent(benchmark_drawdown)} | "
        f"{_percent(drawdown_delta)} |",
        "| Trades | "
        f"{_number(candidate_trades, 0)} | {_number(benchmark_trades, 0)} | "
        f"{_number(trades_delta, 0)} |",
        "",
        "## Run Conclusion and Recommendation",
        "",
        conclusion,
        "",
        "**Recommendation:** " + recommendation,
        "",
        "## Validation",
        "",
    ]

    if isinstance(generalization, dict) and report_candidate_id == candidate.id:
        split_value = generalization.get("split")
        split = split_value if isinstance(split_value, dict) else {}
        holdout_status = str(generalization.get("status", "not evaluated"))
        lines.extend(
            [
                f"- Holdout outcome: {_text(holdout_status.replace('_', ' '))}",
                f"- Holdout reason: {_text(generalization.get('reason', 'Not retained.'))}",
                f"- Training bars: {_text(split.get('train_bar_count', '—'))}",
                f"- Holdout bars: {_text(split.get('holdout_bar_count', '—'))}",
                (
                    f"- Cutoff timestamp: {_text(split.get('cutoff_timestamp_utc', '—'))}"
                    if is_market_runtime
                    else f"- Cutoff date: {_text(split.get('cutoff_date', '—'))}"
                ),
            ]
        )
        holdout = generalization.get("holdout")
        if isinstance(holdout, dict):
            candidate_value = holdout.get("candidate")
            benchmark_value = holdout.get("benchmark")
            holdout_candidate = candidate_value if isinstance(candidate_value, dict) else {}
            holdout_benchmark = benchmark_value if isinstance(benchmark_value, dict) else {}
            lines.extend(
                [
                    "",
                    "| Holdout metric | Strategy | Benchmark |",
                    "|---|---:|---:|",
                    "| Annual return | "
                    f"{_percent(_metric(holdout_candidate, 'annualized_return_pct'))} | "
                    f"{_percent(_metric(holdout_benchmark, 'annualized_return_pct'))} |",
                    "| Sharpe | "
                    f"{_number(_metric(holdout_candidate, 'sharpe_ratio'), 2)} | "
                    f"{_number(_metric(holdout_benchmark, 'sharpe_ratio'), 2)} |",
                    "| Maximum drawdown | "
                    f"{_percent(_metric(holdout_candidate, 'maximum_drawdown_pct'))} | "
                    f"{_percent(_metric(holdout_benchmark, 'maximum_drawdown_pct'))} |",
                ]
            )
        walk_forward = report.get("walk_forward")
        if isinstance(walk_forward, dict):
            aggregate_value = walk_forward.get("aggregate")
            aggregate = aggregate_value if isinstance(aggregate_value, dict) else {}
            fold_count = _text(walk_forward.get("fold_count", "—"))
            lines.extend(
                [
                    "",
                    "### Walk-forward",
                    "",
                    "- Evaluated windows: "
                    f"{_text(aggregate.get('evaluated_folds', '—'))} of {fold_count}",
                    "- Positive-return windows: "
                    f"{_text(aggregate.get('candidate_positive_return_folds', '—'))} "
                    f"of {fold_count}",
                    "- Lower-drawdown windows: "
                    f"{_text(aggregate.get('candidate_lower_drawdown_folds', '—'))} "
                    f"of {fold_count}",
                ]
            )
    else:
        lines.append("- Holdout outcome: Not evaluated for this selected export candidate.")

    limitations = report.get("limitations")
    lines.extend(["", "## Limitations", ""])
    if isinstance(limitations, list) and limitations:
        lines.extend(
            "- "
            + _text(
                user_facing_report_text(item, fallback="A retained limitation requires review.")
            )
            for item in limitations
            if isinstance(item, str)
        )
    else:
        lines.append("No limitations were retained.")

    trades: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact.kind is not QuantArtifactKind.TRADE_LOG:
            continue
        if artifact.content.get("candidate_id") != candidate.id:
            continue
        rows = artifact.content.get("trades")
        if isinstance(rows, list):
            trades.extend(item for item in rows if isinstance(item, dict))
    lines.extend(["", "## Trades", ""])
    if trades:
        lines.extend(
            [
                "| Entry | Exit | Return | Holding period |",
                "|---|---|---:|---:|",
            ]
        )
        for trade in trades[:MAX_EXPORTED_TRADES]:
            entry = str(trade.get("entry_timestamp") or trade.get("entry_date") or "")
            exit_date = str(trade.get("exit_timestamp") or trade.get("exit_date") or "")
            holding_bars = trade.get("holding_bars")
            holding_elapsed_seconds = trade.get("holding_elapsed_seconds")
            if (
                is_market_runtime
                and isinstance(holding_bars, int)
                and isinstance(holding_elapsed_seconds, int)
            ):
                holding_period = (
                    f"{holding_bars} bars · {_elapsed_duration(holding_elapsed_seconds)}"
                )
            elif is_market_runtime:
                holding_period = "—"
            else:
                try:
                    holding_day_count = max(
                        0,
                        (date.fromisoformat(exit_date) - date.fromisoformat(entry)).days,
                    )
                    holding_period = f"{holding_day_count} days"
                except ValueError:
                    holding_period = "—"
            lines.append(
                f"| {_text(entry or '—')} | {_text(exit_date or '—')} | "
                f"{_percent(trade.get('return_pct'))} | {_text(holding_period)} |"
            )
        if len(trades) > MAX_EXPORTED_TRADES:
            lines.extend(
                [
                    "",
                    f"_{len(trades) - MAX_EXPORTED_TRADES} additional retained trades "
                    "omitted by the export size limit._",
                ]
            )
    else:
        lines.append("No retained closed trades for this candidate.")

    lines.extend(["", "## Strategy Specification", ""])
    lines.extend(_strategy_spec(candidate.template, parameters))
    rendered = "\n".join(lines).rstrip() + "\n"
    if len(rendered.encode("utf-8")) > MAX_REPORT_EXPORT_BYTES:
        raise invalid_state("The strategy report is too large for Markdown export.")
    digest = f"sha256:{hashlib.sha256(rendered.encode('utf-8')).hexdigest()}"
    return {
        "export_type": "strategy_report_markdown",
        "run_id": run.id,
        "candidate_id": candidate.id,
        "data_authenticity": runtime.data_authenticity.value,
        "filename": _filename(symbol=symbol, candidate_name=candidate.name, run_id=run.id),
        "media_type": "text/markdown",
        "rendered_content": rendered,
        "content_digest": digest,
    }
