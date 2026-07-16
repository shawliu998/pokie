# pyright: reportMissingParameterType=false, reportUnknownParameterType=false
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.api.app.db.models import (
    Base,
    CollectionRun,
    ContentItem,
    ContentVersion,
    ImportManifest,
    ImportManifestContentVersion,
    ImportSession,
    Project,
    RawContentItem,
    ResearchRun,
    SourceConnection,
    Watchlist,
    Workspace,
)
from services.api.app.modules.common import digest
from services.worker.app.repositories.sqlalchemy_adapter import (
    ProductionAdapterError,
    SQLAlchemyWorkerDomainAdapter,
)

WORKSPACE = "22222222-2222-5222-8222-222222222222"
PROJECT = "55555555-5555-5555-8555-555555555555"
WATCHLIST = "44444444-4444-5444-8444-444444444444"
IMPORT_SOURCE = "33333333-3333-5333-8333-333333333333"
COLLECT_SOURCE = "77777777-7777-5777-8777-777777777777"
NOW = datetime(2026, 7, 15, 6, tzinfo=UTC)


class FakeObjectStore:
    def get_object(self, key: str):  # pragma: no cover - not used
        raise AssertionError(key)

    def quarantine(self, key: str, reason: str) -> None:  # pragma: no cover - not used
        raise AssertionError((key, reason))

    def put_json(self, key: str, payload: dict[str, object]) -> str:  # pragma: no cover
        del payload
        return f"object://{key}"


def test_research_lineage_accepts_v1_import_manifest_and_rejects_raw_tamper() -> None:
    Session = _session_factory()
    with Session() as db:
        _seed_base(db)
        manifest, raw, version = _seed_import_origin(db)
        run = _research_run(
            "research-v1",
            _v1_manifest(manifest, raw, version, raw_digest="sha256:raw-import"),
        )
        db.add(run)
        db.commit()

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    versions = adapter.get_content_versions_for_research_run("research-v1")
    assert [version.id for version in versions] == ["version-import"]

    with Session() as db:
        run = db.get(ResearchRun, "research-v1")
        assert run is not None
        tampered = _v1_manifest(manifest, raw, version, raw_digest="sha256:tampered")
        run.run_input_manifest_json = tampered
        run.run_input_manifest_digest = digest(tampered)
        db.commit()

    with pytest.raises(ProductionAdapterError, match="raw digest"):
        adapter.get_content_versions_for_research_run("research-v1")


def test_research_lineage_accepts_v2_mixed_import_and_collection() -> None:
    Session = _session_factory()
    with Session() as db:
        _seed_base(db)
        manifest, raw, imported_version = _seed_import_origin(db)
        collection_run, collected_raw, collected_version = _seed_collection_origin(db)
        run = _research_run(
            "research-mixed",
            _mixed_manifest(
                manifest, raw, imported_version, collection_run, collected_raw, collected_version
            ),
        )
        db.add(run)
        db.commit()

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    versions = adapter.get_content_versions_for_research_run("research-mixed")
    assert [version.id for version in versions] == ["version-import", "version-collection"]


@pytest.mark.parametrize(
    "override,match",
    [
        ({"source_connection_id": IMPORT_SOURCE}, "source"),
        ({"watchlist_id": "00000000-0000-5000-8000-000000000000"}, "watchlist"),
        ({"stable_key": "tampered"}, "stable key"),
        ({"attempt": 99}, "attempt"),
        ({"raw_digest": "sha256:tampered"}, "raw digest"),
        ({"state": "failed"}, "terminal|state"),
        ({"finished_at": "2026-07-15T07:00:00+00:00"}, "finished_at"),
    ],
)
def test_research_lineage_rejects_v2_collection_snapshot_tamper(
    override: dict[str, Any], match: str
) -> None:
    Session = _session_factory()
    with Session() as db:
        _seed_base(db)
        collection_run, raw, version = _seed_collection_origin(db)
        manifest = _collection_manifest(collection_run, raw, version, override=override)
        db.add(_research_run("research-collection-tamper", manifest))
        db.commit()

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    with pytest.raises(ProductionAdapterError, match=match):
        adapter.get_content_versions_for_research_run("research-collection-tamper")


def test_research_lineage_requires_unchanged_cv_to_freeze_actual_old_collection_origin() -> None:
    Session = _session_factory()
    with Session() as db:
        _seed_base(db)
        old_run, raw, version = _seed_collection_origin(db)
        new_run = CollectionRun(
            id="collection-run-new",
            workspace_id=WORKSPACE,
            watchlist_id=WATCHLIST,
            source_connection_id=COLLECT_SOURCE,
            stable_key="collection:new",
            state="succeeded",
            cadence="daily",
            timezone="UTC",
            scheduled_for=NOW,
            attempt=2,
            input_window_json={},
            counters_json={},
            freshness_json={},
            started_at=NOW,
            finished_at=NOW,
            data_authenticity="collected",
        )
        db.add(new_run)
        db.add(
            _research_run(
                "research-old-origin-tamper",
                _collection_manifest(
                    new_run, raw, version, override={"raw_digest": raw.raw_digest}
                ),
            )
        )
        db.commit()

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    with pytest.raises(ProductionAdapterError, match="actual origin"):
        adapter.get_content_versions_for_research_run("research-old-origin-tamper")
    assert old_run.id == "collection-run-old"


def _session_factory():  # noqa: ANN202
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _seed_base(db) -> None:  # noqa: ANN001
    db.add(Workspace(id=WORKSPACE, name="Test", created_by="owner", data_authenticity="seed"))
    db.add(
        Project(
            id=PROJECT,
            workspace_id=WORKSPACE,
            name="Project",
            status="active",
            created_by="owner",
            data_authenticity="seed",
        )
    )
    db.add(
        Watchlist(
            id=WATCHLIST,
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            name="Watch",
            objective="Track permission friction",
            status="active",
            rules_json={"source_connection_ids": [IMPORT_SOURCE, COLLECT_SOURCE]},
            owner_id="owner",
            data_authenticity="seed",
        )
    )
    db.add(
        SourceConnection(
            id=IMPORT_SOURCE,
            workspace_id=WORKSPACE,
            name="Import",
            source_kind="imported_dataset",
            runtime="static_import",
            connector_type="csv",
            connector_version="csv-v1",
            status="healthy",
            approved_by="owner",
            data_authenticity="imported",
        )
    )
    db.add(
        SourceConnection(
            id=COLLECT_SOURCE,
            workspace_id=WORKSPACE,
            name="GitHub",
            source_kind="cloud",
            runtime="cloud",
            connector_type="github",
            connector_version="github-v1",
            status="healthy",
            approved_by="owner",
            data_authenticity="collected",
        )
    )


def _seed_import_origin(db) -> tuple[ImportManifest, RawContentItem, ContentVersion]:  # noqa: ANN001
    session = ImportSession(
        id="import-session",
        workspace_id=WORKSPACE,
        source_connection_id=IMPORT_SOURCE,
        expected_source_row_version=1,
        expected_current_import_manifest_id=None,
        local_manifest_digest="sha256:local",
        file_digest="sha256:file",
        expected_upload_digest="sha256:upload",
        client_file_name="seed.csv",
        file_size_bytes=12,
        media_type="text/csv",
        parser_version="csv-import-v1",
        schema_version="csv-v1",
        selected_scope_json={"columns": ["body"]},
        selected_scope_digest="sha256:scope",
        state="finalized",
        uploaded_object_key="uploads/seed.csv",
        uploaded_object_digest="sha256:upload",
        terminal_manifest_id="import-manifest",
        created_by="owner",
        data_authenticity="imported",
    )
    manifest = ImportManifest(
        id="import-manifest",
        workspace_id=WORKSPACE,
        import_session_id=session.id,
        source_connection_id=IMPORT_SOURCE,
        file_digest=session.file_digest,
        uploaded_object_key=session.uploaded_object_key,
        uploaded_object_digest=session.uploaded_object_digest,
        parser_version=session.parser_version,
        schema_version=session.schema_version,
        selected_scope_json=session.selected_scope_json,
        selected_scope_digest=session.selected_scope_digest,
        consent_record_id="consent",
        normalized_payload_digest="sha256:normalized",
        content_count=1,
        finalized_at=NOW,
        data_authenticity="imported",
    )
    raw = RawContentItem(
        id="raw-import",
        workspace_id=WORKSPACE,
        import_manifest_id=manifest.id,
        source_connection_id=IMPORT_SOURCE,
        source_external_id="row-1",
        raw_snapshot_uri="s3://glint/import/raw.json",
        raw_digest="sha256:raw-import",
        received_at=NOW,
        data_authenticity="imported",
    )
    item = ContentItem(
        id="item-import",
        workspace_id=WORKSPACE,
        source_connection_id=IMPORT_SOURCE,
        source_item_id="row-1",
        identity_key="import:row-1",
        title="Imported permission",
        data_authenticity="imported",
    )
    version = ContentVersion(
        id="version-import",
        workspace_id=WORKSPACE,
        content_item_id=item.id,
        source_connection_id=IMPORT_SOURCE,
        raw_content_item_id=raw.id,
        version_number=1,
        content_digest="sha256:version-import",
        normalized_title="Imported permission",
        normalized_body="Permission import evidence.",
        metadata_json={"author": "import"},
        captured_at=NOW,
        raw_snapshot_uri=raw.raw_snapshot_uri,
        parser_version="csv-import-v1",
        data_authenticity="imported",
    )
    item.current_version_id = version.id
    db.add_all([session, manifest, raw, item, version])
    db.flush()
    db.add(
        ImportManifestContentVersion(
            workspace_id=WORKSPACE,
            import_manifest_id=manifest.id,
            content_version_id=version.id,
            ordinal=0,
            data_authenticity="imported",
        )
    )
    return manifest, raw, version


def _seed_collection_origin(db) -> tuple[CollectionRun, RawContentItem, ContentVersion]:  # noqa: ANN001
    collection_run = CollectionRun(
        id="collection-run-old",
        workspace_id=WORKSPACE,
        watchlist_id=WATCHLIST,
        source_connection_id=COLLECT_SOURCE,
        stable_key="collection:old",
        state="succeeded",
        cadence="daily",
        timezone="UTC",
        scheduled_for=NOW,
        attempt=1,
        input_window_json={},
        counters_json={},
        freshness_json={},
        started_at=NOW,
        finished_at=NOW,
        data_authenticity="collected",
    )
    raw = RawContentItem(
        id="raw-collection",
        workspace_id=WORKSPACE,
        collection_run_id=collection_run.id,
        source_connection_id=COLLECT_SOURCE,
        source_external_id="issue-1",
        raw_snapshot_uri="s3://glint/collection/raw.json",
        raw_digest="sha256:raw-collection",
        received_at=NOW,
        data_authenticity="collected",
    )
    item = ContentItem(
        id="item-collection",
        workspace_id=WORKSPACE,
        source_connection_id=COLLECT_SOURCE,
        source_item_id="issue-1",
        identity_key="github:issue-1",
        title="Collected permission",
        data_authenticity="collected",
    )
    version = ContentVersion(
        id="version-collection",
        workspace_id=WORKSPACE,
        content_item_id=item.id,
        source_connection_id=COLLECT_SOURCE,
        raw_content_item_id=raw.id,
        version_number=1,
        content_digest="sha256:version-collection",
        normalized_title="Collected permission",
        normalized_body="Permission collection evidence.",
        metadata_json={"author": "github"},
        captured_at=NOW,
        raw_snapshot_uri=raw.raw_snapshot_uri,
        parser_version="github-v1",
        data_authenticity="collected",
    )
    item.current_version_id = version.id
    db.add_all([collection_run, raw, item, version])
    return collection_run, raw, version


def _research_run(run_id: str, manifest: dict[str, Any]) -> ResearchRun:
    return ResearchRun(
        id=run_id,
        workspace_id=WORKSPACE,
        investigation_id="99999999-9999-5999-8999-999999999999",
        investigation_scope_version_id="aaaaaaaa-aaaa-5aaa-8aaa-aaaaaaaaaaaa",
        state="queued",
        graph_version="deterministic-research-v1",
        run_input_manifest_json=manifest,
        run_input_manifest_digest=digest(manifest),
        budget_json={},
        initiated_by="owner",
        trace_id=f"trace-{run_id}",
        data_authenticity="collected",
    )


def _v1_manifest(
    manifest: ImportManifest,
    raw: RawContentItem,
    version: ContentVersion,
    *,
    raw_digest: str,
) -> dict[str, Any]:
    return {
        "schema_version": "run-input-manifest-v1",
        "source_scope": {
            "content_version_ids": [version.id],
            "source_connection_ids": [IMPORT_SOURCE],
        },
        "terminal_import_manifests": [_import_snapshot(manifest)],
        "content_versions": [
            {
                "content_version_id": version.id,
                "content_digest": version.content_digest,
                "import_manifest_id": manifest.id,
                "raw_digest": raw_digest,
                "origin_type": "import_manifest",
            }
        ],
        "provider": "deterministic",
    }


def _mixed_manifest(
    manifest: ImportManifest,
    raw: RawContentItem,
    imported_version: ContentVersion,
    collection_run: CollectionRun,
    collected_raw: RawContentItem,
    collected_version: ContentVersion,
) -> dict[str, Any]:
    collection_manifest = _collection_manifest(collection_run, collected_raw, collected_version)
    return {
        "schema_version": "run-input-manifest-v2",
        "source_scope": {
            "content_version_ids": [imported_version.id, collected_version.id],
            "source_connection_ids": [IMPORT_SOURCE, COLLECT_SOURCE],
            "watchlist_id": WATCHLIST,
        },
        "terminal_import_manifests": [_import_snapshot(manifest)],
        "terminal_collection_runs": collection_manifest["terminal_collection_runs"],
        "content_versions": [
            {
                "content_version_id": imported_version.id,
                "content_digest": imported_version.content_digest,
                "import_manifest_id": manifest.id,
                "raw_digest": raw.raw_digest,
                "origin_type": "import_manifest",
            },
            *collection_manifest["content_versions"],
        ],
        "provider": "deterministic",
    }


def _import_snapshot(manifest: ImportManifest) -> dict[str, Any]:
    return {
        "import_manifest_id": manifest.id,
        "source_connection_id": manifest.source_connection_id,
        "file_digest": manifest.file_digest,
        "uploaded_object_digest": manifest.uploaded_object_digest,
        "normalized_payload_digest": manifest.normalized_payload_digest,
    }


def _collection_manifest(
    collection_run: CollectionRun,
    raw: RawContentItem,
    version: ContentVersion,
    *,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = {
        "collection_run_id": collection_run.id,
        "source_connection_id": collection_run.source_connection_id,
        "watchlist_id": collection_run.watchlist_id,
        "stable_key": collection_run.stable_key,
        "attempt": collection_run.attempt,
        "scheduled_for": collection_run.scheduled_for.isoformat(),
        "finished_at": collection_run.finished_at.isoformat()
        if collection_run.finished_at
        else None,
        "state": collection_run.state,
        "raw_digest": raw.raw_digest,
    }
    if override:
        snapshot.update(override)
    return {
        "schema_version": "run-input-manifest-v2",
        "source_scope": {
            "content_version_ids": [version.id],
            "source_connection_ids": [collection_run.source_connection_id],
            "watchlist_id": WATCHLIST,
        },
        "terminal_collection_runs": [snapshot],
        "content_versions": [
            {
                "content_version_id": version.id,
                "content_digest": version.content_digest,
                "origin_type": "collection_run",
                "origin": snapshot,
            }
        ],
        "provider": "deterministic",
    }
