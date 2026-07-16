"""Deterministic Signal scoring for seed/imported/collected content."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from services.worker.app.contracts import ContentVersion, DataAuthenticity, Signal
from services.worker.app.pipelines.dedupe import DedupeAssignment, deduplicate_versions
from services.worker.app.pipelines.digests import deterministic_id


@dataclass(frozen=True, slots=True)
class SignalDetectionConfig:
    workspace_id: str
    watchlist_id: str
    terms: tuple[str, ...]
    current_window: tuple[datetime, datetime]
    baseline_window: tuple[datetime, datetime]
    exclude_terms: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    min_independent_sources: int = 2
    detector_version: str = "signal-v1"
    impact_rules_version: str = "impact-rules-v1"
    urgency_rules_version: str = "urgency-rules-v1"
    priority_policy_version: str = "priority-matrix-v1"
    require_current_mentions: bool = True
    min_growth_ratio: float = 1.5
    min_robust_z: float = 1.0
    max_duplicate_concentration: float = 0.75
    min_current_mentions: int = 1
    cooldown_seconds: int = 86_400
    baseline_bucket_days: int = 1


@dataclass(frozen=True, slots=True)
class SignalDetectionResult:
    signal: Signal | None
    suppressed: bool
    reason: str
    metrics: dict[str, float | int]


def _matches(
    version: ContentVersion, terms: tuple[str, ...], exclude_terms: tuple[str, ...] = ()
) -> bool:
    haystack = f"{version.normalized_title} {version.normalized_body}".lower()
    if any(re.search(rf"\b{re.escape(term.lower())}\b", haystack) for term in exclude_terms):
        return False
    return any(re.search(rf"\b{re.escape(term.lower())}\b", haystack) for term in terms)


def content_event_time(version: ContentVersion) -> tuple[datetime, bool]:
    value = version.metadata.get("published_at")
    if isinstance(value, str) and value:
        try:
            text = value[:-1] + "+00:00" if value.endswith("Z") else value
            return datetime.fromisoformat(text).astimezone(UTC), False
        except ValueError:
            pass
    return version.captured_at, True


def _in_window(version: ContentVersion, window: tuple[datetime, datetime]) -> bool:
    event_time, _ = content_event_time(version)
    return window[0] <= event_time < window[1]


def detect_signal(
    versions: list[ContentVersion], config: SignalDetectionConfig
) -> SignalDetectionResult:
    matched = [
        version for version in versions if _matches(version, config.terms, config.exclude_terms)
    ]
    current = [version for version in matched if _in_window(version, config.current_window)]
    baseline = [version for version in matched if _in_window(version, config.baseline_window)]
    dedupe = deduplicate_versions(current + baseline)

    current_clusters = [
        dedupe.assignments[version.id].duplicate_cluster_id
        for version in current
        if version.id in dedupe.assignments
    ]
    baseline_clusters = [
        dedupe.assignments[version.id].duplicate_cluster_id
        for version in baseline
        if version.id in dedupe.assignments
    ]
    current_origin_independence = {
        dedupe.assignments[version.id].independence_group_id
        for version in current
        if version.id in dedupe.assignments
    }
    largest_cluster = max(
        (current_clusters.count(cluster_id) for cluster_id in set(current_clusters)), default=0
    )
    duplicate_concentration = largest_cluster / max(len(current), 1)
    cluster_count = len(set(current_clusters))
    origin_count = len(current_origin_independence)
    effective_independent_count = min(cluster_count, origin_count)
    mention_count = len(set(current_clusters))
    baseline_count = len(set(baseline_clusters))
    current_days = _window_days(config.current_window)
    baseline_days = _window_days(config.baseline_window)
    current_rate = mention_count / current_days
    baseline_rate = baseline_count / baseline_days
    baseline_rate_floor = 1 / baseline_days
    growth_ratio = current_rate / max(baseline_rate, baseline_rate_floor)
    baseline_bucket_rates = _baseline_bucket_rates(
        baseline, dedupe.assignments, config.baseline_window, config.baseline_bucket_days
    )
    median_baseline_rate = median(baseline_bucket_rates) if baseline_bucket_rates else 0.0
    deviations = [abs(value - median_baseline_rate) for value in baseline_bucket_rates]
    mad = median(deviations) if deviations else 0.0
    if mad > 0:
        robust_z = (current_rate - median_baseline_rate) / (1.4826 * mad)
        zero_mad_applied = False
    else:
        denominator = math.sqrt(max(median_baseline_rate, 1 / current_days))
        robust_z = (current_rate - median_baseline_rate) / denominator
        zero_mad_applied = True
    captured_time_fallback_count = sum(1 for version in current if content_event_time(version)[1])
    platform_keys = {_platform_key(version) for version in current}
    source_keys = {_source_key(version) for version in current}
    platform_count = len(platform_keys)
    source_connection_count = len(source_keys)
    metrics = {
        "mention_count": mention_count,
        "raw_mention_count": len(current),
        "baseline_mention_count": baseline_count,
        "current_rate": round(current_rate, 3),
        "baseline_rate": round(baseline_rate, 3),
        "baseline_median_bucket_rate": round(median_baseline_rate, 3),
        "baseline_mad": round(mad, 3),
        "baseline_zero_mad_strategy_applied": int(zero_mad_applied),
        "independent_source_count": effective_independent_count,
        "origin_independent_source_count": origin_count,
        "duplicate_cluster_count": cluster_count,
        "platform_count": platform_count,
        "source_connection_count": source_connection_count,
        "growth_ratio": round(growth_ratio, 3),
        "robust_z": round(robust_z, 3),
        "duplicate_concentration": round(duplicate_concentration, 3),
        "captured_time_fallback_count": captured_time_fallback_count,
    }
    detector_policy = _detector_policy(config)
    trigger_rules = _trigger_rules(detector_policy)

    if config.require_current_mentions and len(current) == 0:
        return SignalDetectionResult(None, True, "no current-window matches", metrics)
    if len(current) < config.min_current_mentions:
        return SignalDetectionResult(None, True, "low current sample", metrics)
    if duplicate_concentration >= config.max_duplicate_concentration:
        return SignalDetectionResult(
            None, True, "duplicate or repost concentration too high", metrics
        )
    if cluster_count < config.min_independent_sources:
        return SignalDetectionResult(
            None, True, "insufficient independent content clusters", metrics
        )
    if origin_count < config.min_independent_sources:
        return SignalDetectionResult(None, True, "insufficient independent sources", metrics)
    if growth_ratio < config.min_growth_ratio and robust_z < config.min_robust_z:
        return SignalDetectionResult(None, True, "growth below deterministic threshold", metrics)

    confidence_level = (
        "high"
        if effective_independent_count >= 3
        and cluster_count >= 3
        and origin_count >= 3
        and duplicate_concentration < 0.6
        else "medium"
    )
    authenticity = _combined_authenticity(current)
    cross_source_confirmed = platform_count >= 2
    coverage_limitation = (
        "single_platform_coverage"
        if platform_count < 2
        else ("single_source_coverage" if source_connection_count < 2 else None)
    )
    limitations = ["event_time_missing_used_capture_time"] if captured_time_fallback_count else []
    if coverage_limitation:
        limitations.append(coverage_limitation)
    explanation = (
        f"{mention_count} de-duplicated matching mentions in the current window across "
        f"{effective_independent_count} effective independent sources "
        f"({cluster_count} content clusters, {origin_count} origin groups); "
        f"{platform_count} platform(s), {source_connection_count} source connection(s); "
        f"raw content versions {len(current)}; "
        f"duplicate concentration "
        f"{duplicate_concentration:.2f}; baseline rate {baseline_rate:.2f}/day."
    )
    signal = Signal(
        id=deterministic_id(
            "signal",
            config.workspace_id,
            config.watchlist_id,
            config.detector_version,
            tuple(sorted(v.id for v in current)),
        ),
        workspace_id=config.workspace_id,
        watchlist_id=config.watchlist_id,
        title=f"{', '.join(config.terms)} increased",
        detector_version=config.detector_version,
        detection_window=config.current_window,
        baseline_window=config.baseline_window,
        metrics=metrics,
        dimensions={
            "detection_confidence": {
                "level": confidence_level,
                "calibration_status": "uncalibrated",
                "explanation": explanation,
            },
            "business_impact": {
                "suggested_level": "medium",
                "suggested_explanation": "Matches deterministic watchlist risk terms.",
                "suggestion_origin": "deterministic_rule",
                "suggestion_version": config.impact_rules_version,
                "confirmed_level": None,
                "confirmed_by": None,
                "confirmed_at": None,
            },
            "urgency": {
                "suggested_level": "monitor",
                "suggested_explanation": "No deadline was detected by deterministic rules.",
                "suggestion_origin": "deterministic_rule",
                "suggestion_version": config.urgency_rules_version,
                "confirmed_level": None,
                "confirmed_by": None,
                "confirmed_at": None,
            },
            "priority": {
                "level": None,
                "status": "pending_confirmation",
                "policy_version": config.priority_policy_version,
                "explanation": "Confirm Business Impact and Urgency to derive Priority.",
            },
            "limitations": limitations,
            "source_coverage": {
                "platform_count": platform_count,
                "source_connection_count": source_connection_count,
                "origin_group_count": origin_count,
                "cross_source_confirmed": cross_source_confirmed,
                "platform_keys": sorted(platform_keys),
                "source_connection_ids": sorted(source_keys),
                "explanation": (
                    "Cross-source confirmation is present."
                    if cross_source_confirmed
                    else "Signal is supported by one platform; treat source coverage as limited."
                ),
            },
            "detector_policy": detector_policy,
            "trigger_rules": trigger_rules,
            "topic_key": deterministic_id(
                "signal-topic",
                config.workspace_id,
                config.watchlist_id,
                config.detector_version,
                tuple(sorted(term.lower() for term in config.terms)),
            ),
        },
        explanation=explanation,
        content_version_ids=tuple(version.id for version in current),
        data_authenticity=authenticity,
    )
    return SignalDetectionResult(signal, False, "triggered", metrics)


def _detector_policy(config: SignalDetectionConfig) -> dict[str, int | float | bool | str]:
    current_days = _window_days(config.current_window)
    baseline_days = _window_days(config.baseline_window)
    return {
        "policy_version": f"{config.detector_version}:policy-v1",
        "require_current_mentions": config.require_current_mentions,
        "min_current_mentions": config.min_current_mentions,
        "min_independent_sources": config.min_independent_sources,
        "min_independent_clusters": config.min_independent_sources,
        "min_independent_origins": config.min_independent_sources,
        "max_duplicate_concentration": config.max_duplicate_concentration,
        "min_growth_ratio": config.min_growth_ratio,
        "min_robust_z": config.min_robust_z,
        "cooldown_seconds": config.cooldown_seconds,
        "current_window_days": round(current_days, 6),
        "baseline_window_days": round(baseline_days, 6),
        "rate_normalization": "cluster_count_per_day",
        "robust_z_baseline_bucket_days": config.baseline_bucket_days,
        "robust_z_baseline_statistic": "median_mad",
        "robust_z_zero_mad_strategy": "poisson_sqrt_floor",
        "include_terms": ",".join(config.terms),
        "exclude_terms": ",".join(config.exclude_terms),
        "languages": ",".join(config.languages),
        "regions": ",".join(config.regions),
        "entities": ",".join(config.entities),
        "topics": ",".join(config.topics),
        "platform_coverage_rule": "platform_count >= 2 for cross_source_confirmation",
    }


def _trigger_rules(policy: dict[str, int | float | bool | str]) -> list[str]:
    return [
        f"detector_policy = {policy['policy_version']}",
        "mention_count > 0",
        f"duplicate_cluster_count >= {policy['min_independent_clusters']}",
        f"origin_independent_source_count >= {policy['min_independent_origins']}",
        f"duplicate_concentration < {policy['max_duplicate_concentration']}",
        "growth_ratio compares current and baseline de-duplicated mention rates",
        f"growth_ratio >= {policy['min_growth_ratio']} OR robust_z >= {policy['min_robust_z']}",
        str(policy["robust_z_zero_mad_strategy"]),
        f"cooldown_seconds = {policy['cooldown_seconds']}",
        str(policy["platform_coverage_rule"]),
    ]


def _platform_key(version: ContentVersion) -> str:
    value = (
        version.metadata.get("connector_type")
        or version.metadata.get("platform")
        or version.metadata.get("source_kind")
        or "unknown"
    )
    return str(value).strip().lower() or "unknown"


def _source_key(version: ContentVersion) -> str:
    value = version.metadata.get("source_connection_id") or version.metadata.get("source_id")
    return str(value).strip().lower() if value else _platform_key(version)


def _combined_authenticity(versions: list[ContentVersion]) -> DataAuthenticity:
    values = {version.data_authenticity for version in versions}
    if len(values) == 1:
        return next(iter(values))
    if DataAuthenticity.COLLECTED in values:
        return DataAuthenticity.COLLECTED
    if DataAuthenticity.IMPORTED in values:
        return DataAuthenticity.IMPORTED
    return DataAuthenticity.SEED


def _window_days(window: tuple[datetime, datetime]) -> float:
    seconds = max((window[1] - window[0]).total_seconds(), 1.0)
    return seconds / 86_400


def _baseline_bucket_rates(
    baseline: list[ContentVersion],
    assignments: dict[str, DedupeAssignment],
    baseline_window: tuple[datetime, datetime],
    bucket_days: int,
) -> list[float]:
    bucket_seconds = max(1, bucket_days) * 86_400
    start = baseline_window[0]
    end = baseline_window[1]
    bucket_count = max(1, math.ceil(max((end - start).total_seconds(), 1.0) / bucket_seconds))
    buckets: list[set[str]] = [set() for _ in range(bucket_count)]
    for version in baseline:
        assignment = assignments.get(version.id)
        if assignment is None:
            continue
        event_time, _ = content_event_time(version)
        offset = max(0, int((event_time - start).total_seconds() // bucket_seconds))
        index = min(offset, bucket_count - 1)
        buckets[index].add(assignment.duplicate_cluster_id)
    return [len(bucket) / max(1, bucket_days) for bucket in buckets]
