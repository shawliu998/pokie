from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from packages.contracts.openapi import assert_openapi_components_present
from services.api.app.core.config import Settings
from services.api.app.db.models import Base
from services.api.app.db.session import set_rls_context
from services.worker.app.adapter_wiring import REQUIRED_ADAPTER_METHODS

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_CANDIDATES = (ROOT / "infra/docker-compose.yml", ROOT / "infra/compose.yml")


def _compose_file() -> Path | None:
    return next((path for path in COMPOSE_CANDIDATES if path.is_file()), None)


def _api_module() -> ModuleType:
    candidates = ("services.api.app.main", "services.api.main")
    for name in candidates:
        if importlib.util.find_spec(name) is not None:
            try:
                return importlib.import_module(name)
            except Exception as exc:  # pragma: no cover - only active once an app exists
                pytest.fail(f"API entrypoint {name} is discoverable but cannot import: {exc}")
    pytest.fail("API FastAPI entrypoint is required for the P1 runtime gate")


def _fastapi_app(module: ModuleType):
    app = getattr(module, "app", None)
    if app is None and callable(getattr(module, "create_app", None)):
        app = module.create_app()
    if app is None:
        pytest.fail("API entrypoint must expose app or create_app()")
    return app


def test_python_runtime_settings_reject_production_sqlite() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(
            environment="production",
            database_url="sqlite:///./glint.db",
            allowed_origins=["http://localhost"],
        )


def test_api_production_boundary_has_no_dev_adapter_name() -> None:
    api_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "services/api").rglob("*.py")
    ).lower()
    forbidden = ("devadapter", "mockadapter", "stubadapter", "inmemoryadapter")
    assert not any(name in api_source for name in forbidden)


def test_worker_production_wiring_points_at_sqlalchemy_adapter() -> None:
    wiring = (ROOT / "services/worker/app/adapter_wiring.py").read_text(encoding="utf-8")
    assert "GLINT_WORKER_MODE" in wiring
    assert "services.worker.app.repositories.sqlalchemy_adapter:create_adapter" in wiring
    production_branch = wiring.split('if not adapter_path and mode in {"test", "dev"}:', 1)[1]
    production_branch = production_branch.split("if not adapter_path:", 1)[1]
    assert "InMemoryDomainAdapter" not in production_branch.split("if mode not in", 1)[0]

    repository = importlib.import_module("services.worker.app.repositories.sqlalchemy_adapter")
    adapter = repository.SQLAlchemyWorkerDomainAdapter
    missing = [
        name for name in REQUIRED_ADAPTER_METHODS if not callable(getattr(adapter, name, None))
    ]
    assert not missing, f"production worker adapter is missing methods: {missing}"


def test_postgres_rls_boundary_is_present_in_model_and_session_contracts() -> None:
    assert hasattr(Base, "metadata")
    session_source = (ROOT / "services/api/app/db/session.py").read_text(encoding="utf-8")
    assert "set_config('app.workspace_id'" in session_source
    assert "set_config('app.principal_id'" in session_source
    assert callable(set_rls_context)

    if _compose_file() is None:
        pytest.fail("Compose/Postgres runtime is required for the P1 RLS gate")
    compose = _compose_file().read_text(encoding="utf-8").lower()
    assert "postgres" in compose


def test_compose_runtime_services_are_discoverable() -> None:
    compose_path = _compose_file()
    if compose_path is None:
        pytest.fail("infra/docker-compose.yml is required for the P1 runtime gate")
    compose = compose_path.read_text(encoding="utf-8").lower()
    assert "services:" in compose
    for service in ("api", "worker", "postgres"):
        assert service in compose, f"Compose is missing expected service: {service}"
    assert any(name in compose for name in ("minio", "object_store", "object-store", "s3"))
    assert any(name in compose for name in ("redis", "queue"))


def test_object_store_contract_is_server_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.api.app.core.config import get_settings
    from services.api.app.core.object_store import FilesystemObjectStore, get_object_store
    from services.worker.app.repositories.sqlalchemy_adapter import ConfiguredApiObjectStore

    workspace_id = "22222222-2222-5222-8222-222222222222"
    import_session_id = "33333333-3333-5333-8333-333333333333"
    object_key = f"workspaces/{workspace_id}/imports/{import_session_id}/payload.csv"
    filesystem = FilesystemObjectStore(tmp_path)
    stored = filesystem.put(object_key, b"id,quote\n1,hello\n", "text/csv")
    fetched = filesystem.get(stored.key)
    assert fetched.body == b"id,quote\n1,hello\n"
    assert fetched.digest == stored.digest
    filesystem.quarantine(stored.key, "contract test")
    assert not (tmp_path / object_key).exists()
    assert (tmp_path / f"quarantine/{object_key}.reason.txt").read_text() == "contract test"

    monkeypatch.setenv("GLINT_OBJECT_STORE_BACKEND", "s3")
    monkeypatch.delenv("GLINT_S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("GLINT_S3_BUCKET", raising=False)
    get_settings.cache_clear()
    get_object_store.cache_clear()
    with pytest.raises(RuntimeError, match="not configured"):
        get_object_store()
    get_settings.cache_clear()
    get_object_store.cache_clear()

    class Backend:
        def get_object(self, key: str) -> dict[str, object]:
            return {"key": key, "body": b"fixture", "digest": "sha256:fixture", "size_bytes": 7}

        def quarantine(self, key: str, reason: str) -> None:
            assert key == object_key
            assert reason == "contract test"

    worker_store = ConfiguredApiObjectStore(Backend())
    worker_object = worker_store.get_import_object(
        workspace_id=workspace_id,
        import_session_id=import_session_id,
        key=object_key,
    )
    assert worker_object.body == b"fixture"
    worker_store.quarantine_import_object(
        workspace_id=workspace_id,
        import_session_id=import_session_id,
        key=object_key,
        reason="contract test",
    )

    if _compose_file() is None:
        pytest.fail("external object-store Compose wiring is required for the P1 runtime gate")


def test_openapi_contains_shared_contracts_when_api_exists() -> None:
    module = _api_module()
    app = _fastapi_app(module)
    document = app.openapi()
    assert_openapi_components_present(document)


def test_license_gate_has_no_blocked_project_declarations() -> None:
    blocked = ("gpl", "agpl", "sspl", "commons clause", "non-commercial", "research-only")
    manifests = [ROOT / "pyproject.toml", ROOT / "package.json"]
    manifests.extend(ROOT.glob("apps/*/package.json"))
    manifests.extend(ROOT.glob("packages/*/package.json"))
    findings: list[str] = []
    for path in manifests:
        payload = path.read_text(encoding="utf-8").lower()
        if any(term in payload for term in blocked):
            findings.append(str(path.relative_to(ROOT)))
    assert not findings, f"blocked/unclear license declaration in: {', '.join(findings)}"


def test_performance_baseline_budget_is_explicit() -> None:
    quality_gates = (ROOT / "docs/QUALITY_GATES.md").read_text(encoding="utf-8")
    assert "API P95" in quality_gates
    assert "< 500 ms" in quality_gates


def test_runtime_configuration_does_not_expose_secrets_in_example() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "# GLINT_SECRET_GITHUB_TOKEN=" in example
    sensitive_prefixes = (
        "GITHUB_TOKEN=",
        "GLINT_SECRET_GITHUB_TOKEN=",
        "GLINT_RSS_FEEDS=",
    )
    for line in example.splitlines():
        if any(prefix in line for prefix in sensitive_prefixes):
            assert line.lstrip().startswith("#"), (
                f"sensitive example setting must be commented: {line}"
            )
