from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

import boto3

from packages.domain.errors import InvariantViolation, ObjectScopeMismatch
from packages.domain.imports import (
    import_payload_object_key,
    require_import_payload_object_key,
    require_safe_object_key,
)
from services.api.app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    media_type: str
    digest: str
    body: bytes | None = None


class ObjectStore(Protocol):
    def put(self, key: str, body: bytes, media_type: str) -> StoredObject: ...
    def head(self, key: str) -> StoredObject: ...
    def get(self, key: str) -> StoredObject: ...
    def delete(self, key: str) -> None: ...
    def quarantine(self, key: str, reason: str) -> None: ...


def _safe_key(key: str) -> str:
    try:
        return require_safe_object_key(key)
    except InvariantViolation as exc:
        raise ValueError(
            "object key escaped the configured scope or is not a safe relative path"
        ) from exc


@dataclass(frozen=True, slots=True)
class WorkspaceImportObjectStore:
    """Exact workspace/session-scoped access to one staged import payload."""

    backend: ObjectStore
    workspace_id: str
    import_session_id: str

    @property
    def object_key(self) -> str:
        return import_payload_object_key(self.workspace_id, self.import_session_id)

    def require_key(self, key: str) -> str:
        return require_import_payload_object_key(
            self.workspace_id,
            self.import_session_id,
            key,
        )

    def _require_observed(self, stored: StoredObject) -> StoredObject:
        self.require_key(stored.key)
        if stored.key != self.object_key:
            raise ObjectScopeMismatch("The object store returned an out-of-scope object key.")
        return stored

    def put(self, body: bytes, media_type: str) -> StoredObject:
        return self._require_observed(self.backend.put(self.object_key, body, media_type))

    def head(self) -> StoredObject:
        return self._require_observed(self.backend.head(self.object_key))

    def get(self) -> StoredObject:
        return self._require_observed(self.backend.get(self.object_key))

    def delete(self) -> None:
        self.backend.delete(self.object_key)

    def quarantine(self, reason: str) -> None:
        self.backend.quarantine(self.object_key, reason)


def _digest(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


class FilesystemObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        key = _safe_key(key)
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("object key escaped the configured root")
        return path

    def put(self, key: str, body: bytes, media_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        metadata = {"size_bytes": len(body), "media_type": media_type, "digest": _digest(body)}
        path.with_suffix(path.suffix + ".meta.json").write_text(
            json.dumps(metadata, sort_keys=True), encoding="utf-8"
        )
        return StoredObject(key, len(body), media_type, str(metadata["digest"]))

    def head(self, key: str) -> StoredObject:
        path = self._path(key)
        metadata = json.loads(
            path.with_suffix(path.suffix + ".meta.json").read_text(encoding="utf-8")
        )
        return StoredObject(
            key,
            int(metadata["size_bytes"]),
            str(metadata["media_type"]),
            str(metadata["digest"]),
        )

    def get(self, key: str) -> StoredObject:
        metadata = self.head(key)
        body = self._path(key).read_bytes()
        return StoredObject(key, len(body), metadata.media_type, _digest(body), body)

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".meta.json").unlink(missing_ok=True)

    def quarantine(self, key: str, reason: str) -> None:
        path = self._path(key)
        if not path.exists():
            return
        quarantine = self._path(f"quarantine/{key}")
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        path.replace(quarantine)
        metadata = path.with_suffix(path.suffix + ".meta.json")
        if metadata.exists():
            metadata.replace(quarantine.with_suffix(quarantine.suffix + ".meta.json"))
        quarantine.with_suffix(quarantine.suffix + ".reason.txt").write_text(
            reason, encoding="utf-8"
        )


class S3ObjectStore:
    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        region: str,
        access_key_id: str | None,
        secret_access_key: str | None,
    ) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def put(self, key: str, body: bytes, media_type: str) -> StoredObject:
        key = _safe_key(key)
        value = _digest(body)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=media_type,
            Metadata={"sha256": value.removeprefix("sha256:")},
        )
        return StoredObject(key, len(body), media_type, value)

    def head(self, key: str) -> StoredObject:
        key = _safe_key(key)
        result = self.client.head_object(Bucket=self.bucket, Key=key)
        value = result.get("Metadata", {}).get("sha256")
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in string.hexdigits for character in value)
        ):
            fetched = self.get(key)
            return StoredObject(
                key,
                fetched.size_bytes,
                fetched.media_type,
                fetched.digest,
            )
        return StoredObject(
            key,
            int(result["ContentLength"]),
            result.get("ContentType") or "application/octet-stream",
            f"sha256:{value.lower()}",
        )

    def get(self, key: str) -> StoredObject:
        key = _safe_key(key)
        result = self.client.get_object(Bucket=self.bucket, Key=key)
        body = cast(bytes, result["Body"].read())
        return StoredObject(
            key,
            len(body),
            result.get("ContentType") or "application/octet-stream",
            _digest(body),
            body,
        )

    def delete(self, key: str) -> None:
        key = _safe_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def quarantine(self, key: str, reason: str) -> None:
        key = _safe_key(key)
        target = f"quarantine/{key}"
        self.client.copy_object(
            Bucket=self.bucket,
            Key=target,
            CopySource={"Bucket": self.bucket, "Key": key},
            Metadata={"quarantine-reason": reason[:200]},
            MetadataDirective="REPLACE",
        )
        self.delete(key)


@lru_cache
def get_object_store() -> ObjectStore:
    settings = get_settings()
    if settings.object_store_backend == "filesystem":
        if settings.environment == "production":
            raise RuntimeError("Filesystem object store is forbidden in production")
        return FilesystemObjectStore(settings.object_store_root)
    if settings.object_store_backend == "s3" and settings.s3_endpoint_url and settings.s3_bucket:
        access_key = (
            settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None
        )
        secret_key = (
            settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key
            else None
        )
        return S3ObjectStore(
            settings.s3_endpoint_url,
            settings.s3_bucket,
            settings.s3_region,
            access_key,
            secret_key,
        )
    raise RuntimeError("Object store adapter is not configured")
