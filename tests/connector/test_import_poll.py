from __future__ import annotations

from datetime import timedelta

from connectors.factory import SourceConnectorFactory
from connectors.shared.fixture_transport import FixtureTransport
from packages.domain.imports import import_payload_object_key
from services.worker.app.contracts import (
    ConsentDecision,
    DataAuthenticity,
    ImportFinalizationCommand,
    ImportSession,
    ImportSessionState,
    SourceConnection,
    SourceHealthStatus,
    StoredObject,
    TransferConsentRecord,
    UploadObjectScope,
    now_utc,
)
from services.worker.app.main import run_once
from services.worker.app.pipelines.digests import sha256_bytes
from services.worker.app.storage import InMemoryDomainAdapter, MemoryObjectStore

WORKSPACE = "22222222-2222-5222-8222-222222222222"
OTHER_WORKSPACE = "22222222-2222-5222-8222-222222222223"
SOURCE = "33333333-3333-5333-8333-333333333333"


def test_poll_continues_after_header_only_import_failure() -> None:
    domain = InMemoryDomainAdapter()
    object_store = MemoryObjectStore()
    connector_factory = SourceConnectorFactory(FixtureTransport({}), None)
    domain.sources[SOURCE] = SourceConnection(
        id=SOURCE,
        workspace_id=WORKSPACE,
        source_kind="local",
        runtime="worker",
        connector_type="csv",
        connector_version="csv-import-v1",
        status=SourceHealthStatus.HEALTHY,
        data_authenticity=DataAuthenticity.IMPORTED,
    )
    _enqueue_csv(domain, object_store, "session-bad", "command-1-bad", b"id,title,body\n")
    _enqueue_csv(
        domain,
        object_store,
        "session-good",
        "command-2-good",
        b"id,title,body,url,author,published_at\n1,Valid,Permission works,https://example.test/a,alice,2026-07-15T06:00:00+00:00\n",
    )

    assert run_once(
        domain=domain,
        object_store=object_store,
        connector_factory=connector_factory,
        worker_id="worker-a",
        lease_for=timedelta(seconds=120),
        kind="import-finalization",
    )
    bad_record = domain.import_finalization_jobs["command-1-bad"]
    bad_session = domain.import_sessions["session-bad"]
    assert bad_record.state == "failed"
    assert bad_record.failure_code == "VALIDATION_ERROR"
    assert bad_record.retryable is False
    assert bad_session.terminal_manifest_id is None
    assert domain.manifests == {}
    assert domain.raw_items == {}
    assert domain.content_items == {}
    assert domain.content_versions == {}

    assert run_once(
        domain=domain,
        object_store=object_store,
        connector_factory=connector_factory,
        worker_id="worker-a",
        lease_for=timedelta(seconds=120),
        kind="import-finalization",
    )
    good_record = domain.import_finalization_jobs["command-2-good"]
    good_session = domain.import_sessions["session-good"]
    assert good_record.state == "completed"
    assert good_record.result_manifest_id == good_session.terminal_manifest_id
    assert good_session.terminal_manifest_id is not None
    assert len(domain.manifests) == 1
    assert len(domain.raw_items) == 1
    assert len(domain.content_items) == 1
    assert len(domain.content_versions) == 1


def test_worker_rejects_cross_workspace_import_key_before_object_access() -> None:
    class TrackingObjectStore(MemoryObjectStore):
        def __init__(self) -> None:
            super().__init__()
            self.read_keys: list[str] = []

        def get_import_object(
            self,
            *,
            workspace_id: str,
            import_session_id: str,
            key: str,
        ) -> StoredObject:
            self.read_keys.append(key)
            return super().get_import_object(
                workspace_id=workspace_id,
                import_session_id=import_session_id,
                key=key,
            )

    domain = InMemoryDomainAdapter()
    object_store = TrackingObjectStore()
    connector_factory = SourceConnectorFactory(FixtureTransport({}), None)
    domain.sources[SOURCE] = SourceConnection(
        id=SOURCE,
        workspace_id=WORKSPACE,
        source_kind="local",
        runtime="worker",
        connector_type="csv",
        connector_version="csv-import-v1",
        status=SourceHealthStatus.HEALTHY,
        data_authenticity=DataAuthenticity.IMPORTED,
    )
    body = b"id,title,body\n1,Blocked,Cross workspace key\n"
    _enqueue_csv(domain, object_store, "session-cross", "command-cross", body)
    foreign_key = import_payload_object_key(OTHER_WORKSPACE, "session-cross")
    domain.import_sessions["session-cross"].uploaded_object_key = foreign_key
    domain.consents[0].upload_object_scope = UploadObjectScope(
        object_key=foreign_key,
        max_bytes=len(body),
        media_type="text/csv",
    )
    object_store.put_object(
        StoredObject(
            key=foreign_key,
            body=body,
            digest=sha256_bytes(body),
            size_bytes=len(body),
            media_type="text/csv",
        )
    )

    assert run_once(
        domain=domain,
        object_store=object_store,
        connector_factory=connector_factory,
        worker_id="worker-a",
        lease_for=timedelta(seconds=120),
        kind="import-finalization",
    )

    record = domain.import_finalization_jobs["command-cross"]
    assert record.state == "failed"
    assert record.failure_code == "OBJECT_SCOPE_MISMATCH"
    assert record.retryable is False
    assert object_store.read_keys == []
    assert object_store.quarantined == {}
    assert object_store.objects[foreign_key].body == body


def _enqueue_csv(
    domain: InMemoryDomainAdapter,
    object_store: MemoryObjectStore,
    session_id: str,
    command_id: str,
    body: bytes,
) -> None:
    digest = sha256_bytes(body)
    object_key = import_payload_object_key(WORKSPACE, session_id)
    domain.import_sessions[session_id] = ImportSession(
        id=session_id,
        workspace_id=WORKSPACE,
        source_connection_id=SOURCE,
        expected_source_row_version=1,
        expected_current_import_manifest_id=None,
        local_manifest_digest=f"sha256:local-{session_id}",
        file_digest=digest,
        expected_upload_digest=digest,
        client_file_name=f"{session_id}.csv",
        file_size_bytes=len(body),
        media_type="text/csv",
        parser_version="csv-import-v1",
        schema_version="csv-v1",
        selected_scope_json={"columns": ["id", "title", "body"]},
        selected_scope_digest=f"sha256:scope-{session_id}",
        state=ImportSessionState.UPLOADED,
        uploaded_object_key=object_key,
        uploaded_object_digest=digest,
        data_authenticity=DataAuthenticity.IMPORTED,
    )
    object_store.put_object(
        StoredObject(
            key=object_key,
            body=body,
            digest=digest,
            size_bytes=len(body),
            media_type="text/csv",
        )
    )
    domain.consents.append(
        TransferConsentRecord(
            id=f"consent-{session_id}",
            workspace_id=WORKSPACE,
            import_session_id=session_id,
            decision=ConsentDecision.GRANT,
            local_manifest_digest=f"sha256:local-{session_id}",
            file_digest=digest,
            expected_upload_digest=digest,
            selected_scope_digest=f"sha256:scope-{session_id}",
            destination_workspace_id=WORKSPACE,
            upload_object_scope=UploadObjectScope(
                object_key=object_key,
                max_bytes=max(len(body), 1),
                media_type="text/csv",
            ),
            model_egress_authorization="none",
            policy_version="test",
            actor_id="tester",
            recorded_at=now_utc(),
            expires_at=now_utc() + timedelta(hours=1),
            data_authenticity=DataAuthenticity.IMPORTED,
        )
    )
    domain.enqueue_import_finalization(
        ImportFinalizationCommand(
            workspace_id=WORKSPACE,
            import_session_id=session_id,
            finalize_command_id=command_id,
            expected_session_row_version=1,
            expected_source_row_version=1,
            expected_current_import_manifest_id=None,
        )
    )
