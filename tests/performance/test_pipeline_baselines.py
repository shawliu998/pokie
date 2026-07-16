"""Deterministic P1/P2 pipeline performance guards.

Baseline date: 2026-07-15. Dataset versions are encoded by the constants below.
The thresholds are intentionally broad release-regression guards, not production
SLOs: they allow substantially slower shared CI hosts while still catching an
accidental per-row network/storage call or a major dedupe complexity regression.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO
from time import perf_counter

from services.worker.app.contracts import (
    ContentVersion,
    DataAuthenticity,
    ImportSession,
    ImportSessionState,
)
from services.worker.app.pipelines.csv_import import normalize_csv_import
from services.worker.app.pipelines.dedupe import deduplicate_versions
from services.worker.app.pipelines.digests import canonical_json_digest, deterministic_id

CSV_BASELINE_VERSION = "csv-normalization-v1-5000-rows"
CSV_ROW_COUNT = 5_000
CSV_MAX_SECONDS = 5.0

DEDUPE_BASELINE_VERSION = "signal-dedupe-v1-600-unique-150-reposts"
DEDUPE_UNIQUE_COUNT = 600
DEDUPE_REPOST_COUNT = 150
DEDUPE_MAX_SECONDS = 5.0


def _csv_body() -> bytes:
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("id", "title", "body", "url", "author", "published_at"))
    for index in range(CSV_ROW_COUNT):
        title = "=Formula must remain text" if index == 0 else f"Permission report {index}"
        writer.writerow(
            (
                f"row-{index}",
                title,
                f"Enterprise permission workflow failed at approval step {index}.",
                f"https://example.test/items/{index}?utm_source=performance-baseline",
                f"author-{index % 100}",
                "2026-07-15T06:00:00+00:00",
            )
        )
    return stream.getvalue().encode("utf-8")


def _import_session(body: bytes) -> ImportSession:
    return ImportSession(
        id="11111111-1111-5111-8111-111111111111",
        workspace_id="22222222-2222-5222-8222-222222222222",
        source_connection_id="33333333-3333-5333-8333-333333333333",
        expected_source_row_version=1,
        expected_current_import_manifest_id=None,
        local_manifest_digest="sha256:local",
        file_digest="sha256:file",
        expected_upload_digest="sha256:upload",
        client_file_name=f"{CSV_BASELINE_VERSION}.csv",
        file_size_bytes=len(body),
        media_type="text/csv",
        parser_version="csv-import-v1",
        schema_version="csv-v1",
        selected_scope_json={"columns": ["id", "title", "body"]},
        selected_scope_digest="sha256:scope",
        state=ImportSessionState.VALIDATING,
        uploaded_object_key="imports/performance-baseline.csv",
        uploaded_object_digest="sha256:upload",
        data_authenticity=DataAuthenticity.IMPORTED,
    )


def test_csv_import_normalizes_5000_rows_within_baseline() -> None:
    body = _csv_body()
    heartbeats = 0

    def heartbeat() -> None:
        nonlocal heartbeats
        heartbeats += 1

    started = perf_counter()
    raw_items, content_items, content_versions, payload_digest = normalize_csv_import(
        _import_session(body), body, heartbeat
    )
    elapsed = perf_counter() - started

    assert len(raw_items) == len(content_items) == len(content_versions) == CSV_ROW_COUNT
    assert len({item.id for item in content_items}) == CSV_ROW_COUNT
    assert len({version.id for version in content_versions}) == CSV_ROW_COUNT
    assert raw_items[0].title == "'=Formula must remain text"
    assert raw_items[-1].canonical_url == f"https://example.test/items/{CSV_ROW_COUNT - 1}"
    assert payload_digest.startswith("sha256:") and len(payload_digest) == 71
    assert heartbeats == 5
    assert elapsed < CSV_MAX_SECONDS, (
        f"{CSV_BASELINE_VERSION} took {elapsed:.3f}s; limit is {CSV_MAX_SECONDS:.1f}s"
    )


def _dedupe_version(index: int, *, repost_of: int | None = None) -> ContentVersion:
    content_index = index if repost_of is None else repost_of
    source_index = content_index % 20
    canonical_url = (
        f"https://source-{source_index}.example.test/items/{content_index}"
        if repost_of is None
        else f"https://mirror.example.test/reposts/{index}"
    )
    title = f"Permission workflow case {content_index}"
    body = (
        f"Enterprise permission request case {content_index} fails at approval boundary "
        f"code token{content_index}."
    )
    return ContentVersion(
        id=deterministic_id("performance-content-version", index, repost_of),
        workspace_id="performance-workspace",
        content_item_id=deterministic_id("performance-content-item", index, repost_of),
        version_number=1,
        content_digest=canonical_json_digest(
            {"index": index, "repost_of": repost_of, "title": title, "body": body}
        ),
        normalized_title=title,
        normalized_body=body,
        captured_at=datetime(2026, 7, 15, 6, tzinfo=UTC),
        parser_version=DEDUPE_BASELINE_VERSION,
        canonical_url=canonical_url,
        author=f"author-{content_index}",
        data_authenticity=DataAuthenticity.COLLECTED,
        metadata={"source_connection_id": f"source-{source_index}"},
    )


def test_signal_dedupe_groups_reposts_within_baseline() -> None:
    versions = [_dedupe_version(index) for index in range(DEDUPE_UNIQUE_COUNT)]
    versions.extend(
        _dedupe_version(DEDUPE_UNIQUE_COUNT + index, repost_of=index)
        for index in range(DEDUPE_REPOST_COUNT)
    )

    started = perf_counter()
    result = deduplicate_versions(versions)
    elapsed = perf_counter() - started

    assert len(result.assignments) == DEDUPE_UNIQUE_COUNT + DEDUPE_REPOST_COUNT
    assert len(result.duplicate_cluster_sizes) == DEDUPE_UNIQUE_COUNT
    assert sorted(result.duplicate_cluster_sizes.values()).count(2) == DEDUPE_REPOST_COUNT
    assert len(result.independence_group_sizes) == DEDUPE_UNIQUE_COUNT
    assert sorted(result.independence_group_sizes.values()).count(2) == DEDUPE_REPOST_COUNT
    assert elapsed < DEDUPE_MAX_SECONDS, (
        f"{DEDUPE_BASELINE_VERSION} took {elapsed:.3f}s; limit is {DEDUPE_MAX_SECONDS:.1f}s"
    )
