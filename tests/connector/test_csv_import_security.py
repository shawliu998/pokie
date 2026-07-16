from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.worker.app.contracts import DataAuthenticity, ImportSession, ImportSessionState
from services.worker.app.pipelines.csv_import import normalize_csv_import


def _session() -> ImportSession:
    return ImportSession(
        id="11111111-1111-5111-8111-111111111111",
        workspace_id="22222222-2222-5222-8222-222222222222",
        source_connection_id="33333333-3333-5333-8333-333333333333",
        expected_source_row_version=1,
        expected_current_import_manifest_id=None,
        local_manifest_digest="sha256:local",
        file_digest="sha256:file",
        expected_upload_digest="sha256:upload",
        client_file_name="evil.csv",
        file_size_bytes=1,
        media_type="text/csv",
        parser_version="csv-import-v1",
        schema_version="csv-v1",
        selected_scope_json={"columns": ["id", "title", "body"]},
        selected_scope_digest="sha256:scope",
        state=ImportSessionState.VALIDATING,
        uploaded_object_key="uploads/evil.csv",
        uploaded_object_digest="sha256:upload",
        data_authenticity=DataAuthenticity.IMPORTED,
    )


@pytest.mark.parametrize(
    "body,match",
    [
        (b"id,title,body\n1,t,b,extra\n", "more cells"),
        (b"id,title,body\n", "no data rows"),
        (b"id,title,title\n1,a,b\n", "unique"),
        (b"id,,body\n1,a,b\n", "non-empty"),
        (b"id,title,body\n1,t," + (b"x" * 20_001) + b"\n", "cell exceeds"),
    ],
)
def test_csv_import_rejects_malicious_server_side_shapes(body: bytes, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        normalize_csv_import(_session(), body)


def test_csv_import_keeps_author_published_and_canonical_fields() -> None:
    raw, items, versions, _ = normalize_csv_import(
        _session(),
        b"id,title,body,url,author,published_at\n1,Title,Permission issue,https://Example.test/a?utm_source=x,alice,2026-07-15T06:00:00+00:00\n",
    )
    assert raw[0].canonical_url == "https://example.test/a"
    assert raw[0].author == "alice"
    assert raw[0].published_at == datetime(2026, 7, 15, 6, tzinfo=UTC)
    assert items[0].id == versions[0].content_item_id
