from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

_TEST_RUN_ID = f"{os.getpid()}-{uuid4().hex}"
_TEST_DB_PATH = Path(f"/tmp/glint-pytest-{_TEST_RUN_ID}.db")
_TEST_OBJECT_ROOT = Path(f"/tmp/glint-pytest-objects-{_TEST_RUN_ID}")

os.environ["GLINT_ENVIRONMENT"] = "test"
os.environ["GLINT_DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["GLINT_OBJECT_STORE_ROOT"] = str(_TEST_OBJECT_ROOT)
os.environ["GLINT_OBJECT_STORE_BACKEND"] = "filesystem"

from services.api.app.core.object_store import get_object_store  # noqa: E402
from services.api.app.db.models import Base  # noqa: E402
from services.api.app.db.session import get_engine, reset_database_caches  # noqa: E402
from services.api.app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_runtime() -> None:
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    shutil.rmtree(_TEST_OBJECT_ROOT, ignore_errors=True)
    get_object_store.cache_clear()
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_runtime_paths() -> None:
    yield
    get_engine().dispose()
    reset_database_caches()
    get_object_store.cache_clear()
    _TEST_DB_PATH.unlink(missing_ok=True)
    shutil.rmtree(_TEST_OBJECT_ROOT, ignore_errors=True)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as value:
        yield value


@pytest.fixture
def principal_id() -> str:
    return str(uuid4())


def command_headers(
    principal_id: str, workspace_id: str | None = None, **extra: str
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
        **extra,
    }
    if workspace_id:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def query_headers(principal_id: str, workspace_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {principal_id}", "X-Workspace-ID": workspace_id}
