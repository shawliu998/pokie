from __future__ import annotations

import importlib
import importlib.util
import os
from types import ModuleType

import pytest

from packages.domain.errors import UnsafeValue
from packages.domain.redaction import REDACTED_SECRET, assert_safe_diagnostic, redact


def _api_module() -> ModuleType:
    for name in ("services.api.app.main", "services.api.main"):
        if importlib.util.find_spec(name) is not None:
            try:
                return importlib.import_module(name)
            except Exception as exc:  # pragma: no cover - enabled once API exists
                pytest.fail(f"API module is discoverable but failed to import: {exc}")
    pytest.fail("API FastAPI entrypoint is required for the P1 API smoke gate")


def _app(module: ModuleType):
    app = getattr(module, "app", None)
    if app is None and callable(getattr(module, "create_app", None)):
        app = module.create_app()
    if app is None:
        pytest.fail("API module must expose app or create_app()")
    return app


def test_api_health_and_bootstrap_routes_are_exposed() -> None:
    from fastapi.testclient import TestClient

    app = _app(_api_module())
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    health = next((path for path in ("/healthz", "/health", "/v1/health") if path in paths), None)
    assert health is not None, "API must expose /healthz, /health, or /v1/health"
    bootstrap = "/v1/sync/bootstrap"
    assert bootstrap in paths, "API must expose /v1/sync/bootstrap"

    response = TestClient(app).get(health)
    assert response.status_code == 200
    assert response.headers.get("x-request-id") is not None or "request_id" in response.text


def test_secret_redaction_never_returns_fixture_credentials_or_local_paths() -> None:
    payload = {
        "authorization": "Bearer fixture-secret-value",
        "nested": {
            "api_key": "ghp_fixture_secret_value",
            "local_path": "/Users/example/private.csv",
        },
        "message": "upload failed at /tmp/private.csv",
    }
    safe = redact(payload)
    assert safe["authorization"] == REDACTED_SECRET
    assert safe["nested"]["api_key"] == REDACTED_SECRET
    assert safe["nested"]["local_path"] == "[REDACTED_PATH]"
    assert "fixture-secret-value" not in repr(safe)
    with pytest.raises(UnsafeValue):
        assert_safe_diagnostic(payload)


def test_live_github_smoke_is_opt_in_and_secret_free() -> None:
    if os.environ.get("GLINT_ENABLE_LIVE_SMOKE") != "1":
        pytest.skip("set GLINT_ENABLE_LIVE_SMOKE=1 to enable live GitHub smoke")
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GLINT_GITHUB_REPOSITORY")
    if not token or not repository:
        pytest.skip("GITHUB_TOKEN and GLINT_GITHUB_REPOSITORY are required for live GitHub smoke")
    import httpx

    owner, separator, repo = repository.partition("/")
    if not separator or not owner or not repo:
        pytest.fail("GLINT_GITHUB_REPOSITORY must be owner/repository")
    response = httpx.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers={"authorization": f"Bearer {token}", "accept": "application/vnd.github+json"},
        timeout=10,
    )
    assert response.status_code < 400, response.status_code
    assert token not in response.text


def test_live_rss_smoke_is_opt_in_and_secret_free() -> None:
    if os.environ.get("GLINT_ENABLE_LIVE_SMOKE") != "1":
        pytest.skip("set GLINT_ENABLE_LIVE_SMOKE=1 to enable live RSS smoke")
    feed_url = os.environ.get("GLINT_RSS_SMOKE_URL")
    if not feed_url:
        pytest.skip("GLINT_RSS_SMOKE_URL is required for live RSS smoke")
    import httpx

    response = httpx.get(feed_url, timeout=10, follow_redirects=False)
    assert response.status_code < 400, response.status_code
    assert "authorization=" not in response.text.lower()
