from __future__ import annotations

import hashlib
from typing import Any

import pytest

from packages.domain.errors import ObjectScopeMismatch
from packages.domain.imports import import_payload_object_key
from services.api.app.core.object_store import (
    S3ObjectStore,
    StoredObject,
    WorkspaceImportObjectStore,
)

WORKSPACE = "22222222-2222-5222-8222-222222222222"
OTHER_WORKSPACE = "22222222-2222-5222-8222-222222222223"
IMPORT_SESSION = "33333333-3333-5333-8333-333333333333"


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self) -> bytes:
        return self.value


class _FakeS3Client:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def head_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "ContentLength": len(self.body),
            "ContentType": "text/csv",
            "Metadata": {},
        }

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Body": _Body(self.body), "ContentType": "text/csv"}


def test_s3_uses_explicit_credentials_and_computes_missing_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    body = b"canonical object bytes"

    def client_factory(_service: str, **kwargs: Any) -> _FakeS3Client:
        captured.update(kwargs)
        return _FakeS3Client(body)

    monkeypatch.setattr("services.api.app.core.object_store.boto3.client", client_factory)
    store = S3ObjectStore(
        "http://minio:9000",
        "glint",
        "us-east-1",
        "explicit-access-key",
        "explicit-secret-key",
    )
    observed = store.head("workspace/import.csv")
    assert captured["aws_access_key_id"] == "explicit-access-key"
    assert captured["aws_secret_access_key"] == "explicit-secret-key"
    assert observed.digest == f"sha256:{hashlib.sha256(body).hexdigest()}"
    assert observed.digest != f"sha256:{'0' * 64}"


@pytest.mark.parametrize(
    "key",
    [
        "../escaped.csv",
        "nested/../../escaped.csv",
        "/absolute.csv",
        "workspaces//imports/payload.csv",
        "workspaces\\foreign\\payload.csv",
    ],
)
@pytest.mark.parametrize("operation", ["put", "head", "get", "delete", "quarantine"])
def test_s3_rejects_unsafe_keys_before_any_client_operation(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    operation: str,
) -> None:
    class NoCallsClient:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"unexpected S3 call: {name}")

    monkeypatch.setattr(
        "services.api.app.core.object_store.boto3.client",
        lambda *_args, **_kwargs: NoCallsClient(),
    )
    store = S3ObjectStore("http://minio:9000", "glint", "us-east-1", "key", "secret")

    with pytest.raises(ValueError, match="safe relative path"):
        if operation == "put":
            store.put(key, b"payload", "text/csv")
        elif operation == "head":
            store.head(key)
        elif operation == "get":
            store.get(key)
        elif operation == "delete":
            store.delete(key)
        else:
            store.quarantine(key, "test")


def test_workspace_import_store_cannot_swap_objects_between_workspaces() -> None:
    first_key = import_payload_object_key(WORKSPACE, IMPORT_SESSION)
    second_key = import_payload_object_key(OTHER_WORKSPACE, IMPORT_SESSION)

    class RecordingStore:
        def __init__(self) -> None:
            self.objects = {
                first_key: StoredObject(first_key, 5, "text/csv", "sha256:" + "1" * 64, b"first"),
                second_key: StoredObject(
                    second_key, 6, "text/csv", "sha256:" + "2" * 64, b"second"
                ),
            }
            self.calls: list[tuple[str, str]] = []

        def put(self, key: str, body: bytes, media_type: str) -> StoredObject:
            self.calls.append(("put", key))
            stored = StoredObject(key, len(body), media_type, "sha256:" + "3" * 64, body)
            self.objects[key] = stored
            return stored

        def head(self, key: str) -> StoredObject:
            self.calls.append(("head", key))
            return self.objects[key]

        def get(self, key: str) -> StoredObject:
            self.calls.append(("get", key))
            return self.objects[key]

        def delete(self, key: str) -> None:
            self.calls.append(("delete", key))

        def quarantine(self, key: str, reason: str) -> None:
            del reason
            self.calls.append(("quarantine", key))

    backend = RecordingStore()
    first = WorkspaceImportObjectStore(backend, WORKSPACE, IMPORT_SESSION)
    second = WorkspaceImportObjectStore(backend, OTHER_WORKSPACE, IMPORT_SESSION)

    assert first.get().body == b"first"
    assert second.get().body == b"second"
    with pytest.raises(ObjectScopeMismatch, match="outside its workspace scope"):
        first.require_key(second_key)
    with pytest.raises(ObjectScopeMismatch, match="outside its workspace scope"):
        first.require_key(f"workspaces/{WORKSPACE}/imports/../payload.csv")
    first.put(b"replacement", "text/csv")
    first.head()
    first.quarantine("test")
    first.delete()

    assert all(
        key == first_key
        for operation, key in backend.calls
        if operation != "get" or key != second_key
    )
