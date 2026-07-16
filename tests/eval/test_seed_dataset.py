from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from services.worker.app.contracts import (
    ContentVersion,
    DataAuthenticity,
    ResearchRun,
    ResearchRunState,
)
from services.worker.app.pipelines.dedupe import deduplicate_versions
from services.worker.app.pipelines.digests import canonical_json_digest, deterministic_id
from services.worker.app.pipelines.research import DeterministicResearchRunner
from services.worker.app.pipelines.signals import SignalDetectionConfig, detect_signal
from services.worker.app.storage import InMemoryDomainAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "seed_dataset_manifest.json"


def _manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text(encoding="utf-8")))


def _versions() -> list[ContentVersion]:
    manifest = _manifest()
    versions: list[ContentVersion] = []
    for case in manifest["cases"]:
        case = dict(case)
        content_item_key = str(case.get("content_item_key") or case["id"])
        content_digest = canonical_json_digest(
            {
                "id": case["id"],
                "title": case["title"],
                "body": case["body"],
                "canonical_url": case["canonical_url"],
            }
        )
        versions.append(
            ContentVersion(
                id=deterministic_id("seed-content-version", case["id"]),
                workspace_id=str(manifest["workspace_id"]),
                content_item_id=deterministic_id("seed-content-item", content_item_key),
                version_number=2 if str(case["id"]).endswith("_v2") else 1,
                content_digest=content_digest,
                normalized_title=str(case["title"]),
                normalized_body=str(case["body"]),
                captured_at=datetime.fromisoformat(str(case["captured_at"])).astimezone(UTC),
                parser_version="seed-fixture-v1",
                canonical_url=str(case["canonical_url"]),
                author=str(case["author"]),
                data_authenticity=DataAuthenticity.SEED,
                metadata={
                    "seed_id": case["id"],
                    "label": case["label"],
                    "source": case["source"],
                    "published_at": case.get("published_at"),
                },
            )
        )
    return versions


def test_seed_fixture_has_fixed_digest_and_required_cases() -> None:
    manifest = _manifest()
    digest_value = manifest.pop("dataset_digest")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert "sha256:" + hashlib.sha256(canonical.encode()).hexdigest() == digest_value
    assert manifest["dataset_version"] == "seed-dataset-v1.0.0-20260715"
    assert manifest["uuidv5_namespace"] == "019f6531-d58f-7860-a154-30c7a89f433d"
    case_ids = {case["id"] for case in manifest["cases"]}
    assert {
        "seed_tp_001",
        "seed_tp_002",
        "seed_fp_001",
        "seed_fp_002",
        "seed_repost_001",
        "seed_counter_001",
        "seed_counter_002",
        "seed_source_fail_001",
        "seed_source_fail_002",
        "seed_version_001",
        "seed_injection_001",
        "seed_injection_002",
        "seed_brief_001",
        "seed_review_001",
    }.issubset(case_ids)


def test_seed_manifest_cases_match_spec_semantics() -> None:
    cases = {case["id"]: case for case in _manifest()["cases"]}
    assert cases["seed_fp_001"]["label"] == "false_positive_repost_storm"
    assert cases["seed_fp_002"]["label"] == "false_positive_outage_backfill"
    assert cases["seed_source_fail_001"]["label"] == "source_failure_invalid_xml"
    assert cases["seed_source_fail_002"]["label"] == "source_deleted_refetch"
    assert cases["seed_review_001"]["label"] == "insufficient_independence_review"
    assert (
        cases["seed_version_001"]["content_item_key"]
        == cases["seed_version_001_v2"]["content_item_key"]
    )


def test_signal_scoring_uses_window_normalized_rates() -> None:
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)

    def version(kind: str, index: int, published_at: datetime) -> ContentVersion:
        return ContentVersion(
            id=deterministic_id("rate-version", kind, index),
            workspace_id="seed-workspace",
            content_item_id=deterministic_id("rate-item", kind, index),
            version_number=1,
            content_digest=canonical_json_digest({"kind": kind, "index": index}),
            normalized_title=f"Permission rate {kind} {index}",
            normalized_body=f"Permission failure rate sample {kind} {index}.",
            captured_at=published_at + timedelta(minutes=5),
            parser_version="seed-rate-test",
            canonical_url=f"https://rate.example.test/{kind}/{index}",
            author=f"{kind}-author-{index}",
            data_authenticity=DataAuthenticity.COLLECTED,
            metadata={"published_at": published_at.isoformat(), "connector_type": "github"},
        )

    baseline = [version("baseline", index, now - timedelta(days=35 - index)) for index in range(28)]
    current = [version("current", index, now - timedelta(hours=index + 1)) for index in range(14)]
    result = detect_signal(
        baseline + current,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=(now - timedelta(days=7), now),
            baseline_window=(now - timedelta(days=35), now - timedelta(days=7)),
            min_independent_sources=2,
            min_growth_ratio=1.5,
        ),
    )
    assert result.signal is not None
    assert result.metrics["current_rate"] == 2.0
    assert result.metrics["baseline_rate"] == 1.0
    assert result.metrics["growth_ratio"] == 2.0
    policy = result.signal.dimensions["detector_policy"]
    assert policy["rate_normalization"] == "cluster_count_per_day"
    assert policy["robust_z_zero_mad_strategy"] == "poisson_sqrt_floor"


def test_seed_version_change_uses_one_content_item_and_pins_v1_evidence() -> None:
    versions = {
        version.metadata["seed_id"]: version
        for version in _versions()
        if str(version.metadata["seed_id"]).startswith("seed_version_001")
    }
    v1 = versions["seed_version_001"]
    v2 = versions["seed_version_001_v2"]
    assert v1.content_item_id == v2.content_item_id
    assert v1.id != v2.id
    assert v1.content_digest != v2.content_digest
    evidence_snapshot = {"content_version_id": v1.id, "content_digest": v1.content_digest}
    assert evidence_snapshot["content_version_id"] == v1.id
    assert evidence_snapshot["content_digest"] != v2.content_digest


def test_seed_repost_suppression_and_signal_explanation() -> None:
    versions = [version for version in _versions() if version.metadata["label"] == "repost_cluster"]
    now = datetime(2026, 7, 15, 6, tzinfo=UTC)
    result = detect_signal(
        versions,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=(now - timedelta(hours=2), now + timedelta(hours=1)),
            baseline_window=(now - timedelta(days=7), now - timedelta(hours=2)),
            min_independent_sources=2,
        ),
    )
    assert result.suppressed
    assert result.reason == "duplicate or repost concentration too high"
    dedupe = deduplicate_versions(versions)
    assert len(set(item.duplicate_cluster_id for item in dedupe.assignments.values())) == 1

    mixed = versions + [
        version for version in _versions() if version.metadata["seed_id"] == "seed_tp_001"
    ]
    result = detect_signal(
        mixed,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=(now - timedelta(hours=2), now + timedelta(hours=1)),
            baseline_window=(now - timedelta(days=7), now - timedelta(hours=2)),
            min_independent_sources=2,
        ),
    )
    assert result.signal is not None
    assert "independent sources" in result.signal.explanation
    assert "duplicate concentration" in result.signal.explanation


def test_repost_cluster_with_three_authors_is_suppressed() -> None:
    now = datetime(2026, 7, 15, 6, tzinfo=UTC)
    versions = []
    body = "Permission error blocks onboarding for enterprise users."
    for index, author in enumerate(("alice", "bob", "carol")):
        versions.append(
            ContentVersion(
                id=deterministic_id("repost-negative", author),
                workspace_id="seed-workspace",
                content_item_id=deterministic_id("repost-item", author),
                version_number=1,
                content_digest=canonical_json_digest({"body": body, "author": author}),
                normalized_title="Permission outage",
                normalized_body=body,
                captured_at=now,
                parser_version="test",
                canonical_url=f"https://repost.example.test/{index}",
                author=author,
                data_authenticity=DataAuthenticity.COLLECTED,
                metadata={"published_at": (now - timedelta(minutes=10)).isoformat()},
            )
        )
    result = detect_signal(
        versions,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=(now - timedelta(hours=1), now + timedelta(hours=1)),
            baseline_window=(now - timedelta(days=7), now - timedelta(hours=1)),
            min_independent_sources=2,
        ),
    )
    assert result.suppressed
    assert result.reason == "duplicate or repost concentration too high"


def test_same_repo_same_author_distinct_bodies_are_not_independent_sources() -> None:
    now = datetime(2026, 7, 15, 6, tzinfo=UTC)
    versions = [
        ContentVersion(
            id=deterministic_id("same-author-distinct", index),
            workspace_id="seed-workspace",
            content_item_id=deterministic_id("same-author-distinct-item", index),
            version_number=1,
            content_digest=canonical_json_digest({"body": f"permission body {index}"}),
            normalized_title=f"Permission report {index}",
            normalized_body=f"Permission workflow fails in distinct case {index}.",
            captured_at=now,
            parser_version="github-v1",
            canonical_url=f"https://github.com/acme/glint/issues/{index}",
            author="same-author",
            data_authenticity=DataAuthenticity.COLLECTED,
            metadata={
                "source_connection_id": "github-source",
                "published_at": (now - timedelta(minutes=index + 1)).isoformat(),
            },
        )
        for index in range(3)
    ]
    result = detect_signal(
        versions,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=(now - timedelta(hours=1), now + timedelta(hours=1)),
            baseline_window=(now - timedelta(days=7), now - timedelta(hours=1)),
            min_independent_sources=2,
        ),
    )
    assert result.suppressed
    assert result.reason == "insufficient independent sources"
    assert result.metrics["duplicate_cluster_count"] == 3
    assert result.metrics["origin_independent_source_count"] == 1
    assert result.metrics["independent_source_count"] == 1


def test_same_repo_two_authors_count_as_two_independent_sources() -> None:
    now = datetime(2026, 7, 15, 6, tzinfo=UTC)
    versions = [
        ContentVersion(
            id=deterministic_id("two-author", author),
            workspace_id="seed-workspace",
            content_item_id=deterministic_id("two-author-item", author),
            version_number=1,
            content_digest=canonical_json_digest({"body": author}),
            normalized_title=f"Permission report {author}",
            normalized_body=f"Permission workflow fails for {author}.",
            captured_at=now,
            parser_version="github-v1",
            canonical_url=f"https://github.com/acme/glint/issues/{index}",
            author=author,
            data_authenticity=DataAuthenticity.COLLECTED,
            metadata={
                "source_connection_id": "github-source",
                "published_at": (now - timedelta(minutes=index + 1)).isoformat(),
            },
        )
        for index, author in enumerate(("alice", "bob"))
    ]
    result = detect_signal(
        versions,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=(now - timedelta(hours=1), now + timedelta(hours=1)),
            baseline_window=(now - timedelta(days=7), now - timedelta(hours=1)),
            min_independent_sources=2,
        ),
    )
    assert result.signal is not None
    assert result.metrics["duplicate_cluster_count"] == 2
    assert result.metrics["origin_independent_source_count"] == 2
    assert result.metrics["independent_source_count"] == 2


def test_three_reposts_plus_two_independent_sources_do_not_become_high_confidence() -> None:
    now = datetime(2026, 7, 15, 6, tzinfo=UTC)
    versions: list[ContentVersion] = []
    repost_body = "Permission error blocks onboarding for enterprise users."
    for index, author in enumerate(("alice", "bob", "carol")):
        versions.append(
            ContentVersion(
                id=deterministic_id("repost-plus-independent", author),
                workspace_id="seed-workspace",
                content_item_id=deterministic_id("repost-plus-independent-item", author),
                version_number=1,
                content_digest=canonical_json_digest({"body": repost_body, "author": author}),
                normalized_title="Permission outage",
                normalized_body=repost_body,
                captured_at=now,
                parser_version="test",
                canonical_url=f"https://repost.example.test/{index}",
                author=author,
                data_authenticity=DataAuthenticity.COLLECTED,
                metadata={"published_at": (now - timedelta(minutes=10)).isoformat()},
            )
        )
    for index, body in enumerate(
        (
            "Permission approvals fail for billing export administrators.",
            "Permission setup blocks mobile workspace invites.",
        )
    ):
        versions.append(
            ContentVersion(
                id=deterministic_id("independent-current", index),
                workspace_id="seed-workspace",
                content_item_id=deterministic_id("independent-current-item", index),
                version_number=1,
                content_digest=canonical_json_digest({"body": body}),
                normalized_title=f"Permission independent {index}",
                normalized_body=body,
                captured_at=now,
                parser_version="test",
                canonical_url=f"https://independent.example.test/{index}",
                author=f"independent-{index}",
                data_authenticity=DataAuthenticity.COLLECTED,
                metadata={"published_at": (now - timedelta(minutes=20 + index)).isoformat()},
            )
        )
    result = detect_signal(
        versions,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=(now - timedelta(hours=1), now + timedelta(hours=1)),
            baseline_window=(now - timedelta(days=7), now - timedelta(hours=1)),
            min_independent_sources=2,
        ),
    )
    assert result.signal is not None
    assert result.signal.dimensions["detection_confidence"]["level"] == "medium"
    assert result.metrics["independent_source_count"] == 3
    assert result.metrics["origin_independent_source_count"] == 5
    assert result.metrics["duplicate_cluster_count"] == 3
    assert result.metrics["duplicate_concentration"] == 0.6


def test_signal_uses_published_time_for_backfill_and_stable_identity() -> None:
    now = datetime(2026, 7, 15, 6, tzinfo=UTC)
    history = [
        ContentVersion(
            id=deterministic_id("history", index),
            workspace_id="seed-workspace",
            content_item_id=deterministic_id("history-item", index),
            version_number=1,
            content_digest=canonical_json_digest({"index": index}),
            normalized_title=f"Permission history {index}",
            normalized_body="Permission requests increased in old feedback.",
            captured_at=now,
            parser_version="test",
            canonical_url=f"https://history.example.test/{index}",
            author=f"author-{index}",
            data_authenticity=DataAuthenticity.COLLECTED,
            metadata={"published_at": (now - timedelta(days=3, hours=index)).isoformat()},
        )
        for index in range(1)
    ]
    current_window = (now - timedelta(hours=2), now + timedelta(hours=1))
    baseline_window = (now - timedelta(days=7), now - timedelta(hours=2))
    backfill = detect_signal(
        history,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=current_window,
            baseline_window=baseline_window,
            min_independent_sources=2,
        ),
    )
    assert backfill.suppressed
    assert backfill.reason == "no current-window matches"

    current = history + [
        ContentVersion(
            id=deterministic_id("current", index),
            workspace_id="seed-workspace",
            content_item_id=deterministic_id("current-item", index),
            version_number=1,
            content_digest=canonical_json_digest({"current": index}),
            normalized_title=f"Permission current {index}",
            normalized_body="Permission requests fail for new customers.",
            captured_at=now,
            parser_version="test",
            canonical_url=f"https://current.example.test/{index}",
            author=f"current-author-{index}",
            data_authenticity=DataAuthenticity.COLLECTED,
            metadata={"published_at": (now - timedelta(minutes=10 + index)).isoformat()},
        )
        for index in range(3)
    ]
    first = detect_signal(
        current,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=current_window,
            baseline_window=baseline_window,
            min_independent_sources=2,
        ),
    )
    second = detect_signal(
        current,
        SignalDetectionConfig(
            workspace_id="seed-workspace",
            watchlist_id="seed-watchlist",
            terms=("permission",),
            current_window=(now - timedelta(hours=1), now + timedelta(hours=2)),
            baseline_window=(now - timedelta(days=7), now - timedelta(hours=1)),
            min_independent_sources=2,
        ),
    )
    assert first.signal is not None
    assert second.signal is not None
    assert first.signal.id == second.signal.id


def test_seed_injection_markers_raise_review_events_and_no_brief() -> None:
    manifest = _manifest()
    versions = [
        version
        for version in _versions()
        if version.metadata["seed_id"] in manifest["expected"]["injection_cases"]
    ]
    domain = InMemoryDomainAdapter()
    run = ResearchRun(
        id=deterministic_id("seed-run", "injection"),
        workspace_id=str(manifest["workspace_id"]),
        investigation_id=deterministic_id("seed-investigation", "injection"),
        investigation_scope_version_id=deterministic_id("seed-scope", "injection"),
        state=ResearchRunState.QUEUED,
        graph_version="deterministic-import-v1",
        run_input_manifest_digest="sha256:seed",
        source_manifest_id=deterministic_id("seed-manifest", "injection"),
        content_version_ids=tuple(version.id for version in versions),
        data_authenticity=DataAuthenticity.SEED,
    )
    domain.research_runs[run.id] = run
    for version in versions:
        domain.content_versions[version.id] = version

    result = DeterministicResearchRunner(domain).run(run.id, versions)
    assert set(result.injection_flags) >= {"data_exfiltration", "tool_abuse"}
    review_events = [
        event for event in domain.run_events[run.id] if event.event_type == "review.required"
    ]
    assert any(event.payload["reason_code"] == "prompt_injection_marker" for event in review_events)
    assert len(domain.claims) == 1
    assert domain.syntheses == {}
