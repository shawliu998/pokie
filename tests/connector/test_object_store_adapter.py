from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from packages.domain.imports import import_payload_object_key
from services.api.app.core.object_store import FilesystemObjectStore, StoredObject
from services.worker.app.contracts import (
    ObjectNotFoundError,
    ObjectUnavailableError,
    ObjectVerificationError,
)
from services.worker.app.repositories.sqlalchemy_adapter import (
    ConfiguredApiObjectStore,
    ProductionAdapterError,
)

WORKSPACE = "22222222-2222-5222-8222-222222222222"
OTHER_WORKSPACE = "22222222-2222-5222-8222-222222222223"
IMPORT_SESSION = "33333333-3333-5333-8333-333333333333"
IMPORT_KEY = import_payload_object_key(WORKSPACE, IMPORT_SESSION)


@dataclass
class LegacyObject:
    key: str
    body: bytes | None
    digest: str
    size_bytes: int
    media_type: str


class LegacyObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, key: str, body: bytes, media_type: str) -> object:
        del media_type
        self.objects[key] = body
        return type("Result", (), {"uri": f"object://{key}"})()

    def get_object(self, key: str) -> LegacyObject:
        body = self.objects[key]
        return LegacyObject(key, body, "sha256:" + "0" * 64, len(body), "application/json")

    def quarantine(self, key: str, reason: str) -> None:
        del key, reason


def test_configured_object_store_adapts_api_get_put(tmp_path: Path) -> None:
    backend = FilesystemObjectStore(tmp_path)
    store = ConfiguredApiObjectStore(backend)
    uri = store.put_json("snapshots/item.json", {"id": "item"})
    assert uri == "object://snapshots/item.json"
    backend.put(IMPORT_KEY, b'{"id":"item"}', "application/json")
    item = store.get_import_object(
        workspace_id=WORKSPACE,
        import_session_id=IMPORT_SESSION,
        key=IMPORT_KEY,
    )
    assert item.body is not None
    assert item.media_type == "application/json"
    assert item.size_bytes == len(item.body)


def test_configured_object_store_rejects_api_get_without_body() -> None:
    class HeadOnlyStore:
        def get(self, key: str) -> StoredObject:
            return StoredObject(key, 0, "application/json", "sha256:" + "0" * 64, None)

        def quarantine(self, key: str, reason: str) -> None:
            del key, reason

    store = ConfiguredApiObjectStore(HeadOnlyStore())
    with pytest.raises(ProductionAdapterError, match="no body"):
        store.get_import_object(
            workspace_id=WORKSPACE,
            import_session_id=IMPORT_SESSION,
            key=IMPORT_KEY,
        )


def test_configured_object_store_still_accepts_legacy_names() -> None:
    backend = LegacyObjectStore()
    store = ConfiguredApiObjectStore(backend)
    assert store.put_json(IMPORT_KEY, {"id": "item"}) == f"object://{IMPORT_KEY}"
    assert store.get_import_object(
        workspace_id=WORKSPACE,
        import_session_id=IMPORT_SESSION,
        key=IMPORT_KEY,
    ).body


def test_configured_object_store_maps_s3_style_exceptions() -> None:
    class ClientErrorLike(Exception):
        def __init__(self, code: str) -> None:
            self.response = {"Error": {"Code": code}}

    class EndpointConnectionError(Exception):
        pass

    class MissingStore:
        def get(self, key: str):  # noqa: ANN001
            del key
            raise ClientErrorLike("NoSuchKey")

    class UnavailableStore:
        def get(self, key: str):  # noqa: ANN001
            del key
            raise EndpointConnectionError()

    with pytest.raises(ObjectNotFoundError):
        ConfiguredApiObjectStore(MissingStore()).get_import_object(
            workspace_id=WORKSPACE,
            import_session_id=IMPORT_SESSION,
            key=IMPORT_KEY,
        )
    with pytest.raises(ObjectUnavailableError):
        ConfiguredApiObjectStore(UnavailableStore()).get_import_object(
            workspace_id=WORKSPACE,
            import_session_id=IMPORT_SESSION,
            key=IMPORT_KEY,
        )


@pytest.mark.parametrize(
    "key",
    [
        import_payload_object_key(OTHER_WORKSPACE, IMPORT_SESSION),
        f"workspaces/{WORKSPACE}/imports/../{IMPORT_SESSION}/payload.csv",
        f"workspaces/{WORKSPACE}/imports/{IMPORT_SESSION}/../payload.csv",
        f"/workspaces/{WORKSPACE}/imports/{IMPORT_SESSION}/payload.csv",
    ],
)
def test_worker_import_store_rejects_cross_workspace_and_traversal_before_read(
    key: str,
) -> None:
    class RecordingStore:
        called = False

        def get(self, object_key: str) -> StoredObject:
            self.called = True
            return StoredObject(object_key, 0, "text/csv", "sha256:" + "0" * 64, b"")

    backend = RecordingStore()
    store = ConfiguredApiObjectStore(backend)

    with pytest.raises(ObjectVerificationError, match="outside the import workspace"):
        store.get_import_object(
            workspace_id=WORKSPACE,
            import_session_id=IMPORT_SESSION,
            key=key,
        )

    assert backend.called is False
