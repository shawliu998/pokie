from __future__ import annotations

import os

import httpx
import pytest


def test_production_rejects_forged_and_expired_access_tokens() -> None:
    if os.environ.get("GLINT_PRODUCTION_AUTH_SMOKE") != "1":
        pytest.skip("production auth smoke is run after Compose seed")
    base_url = os.environ.get("GLINT_SMOKE_API_URL", "http://127.0.0.1:8000").rstrip("/")
    workspace = os.environ.get("GLINT_AUTH_WORKSPACE_ID")
    valid = os.environ.get("GLINT_AUTH_ACCESS_TOKEN")
    forged = os.environ.get("GLINT_AUTH_FORGED_TOKEN")
    expired = os.environ.get("GLINT_AUTH_EXPIRED_TOKEN")
    if not workspace or not valid or not forged or not expired:
        pytest.fail("production auth smoke requires GLINT_AUTH_* token fixtures and workspace")

    def get(token: str) -> httpx.Response:
        return httpx.get(
            f"{base_url}/v1/sync/bootstrap",
            headers={"Authorization": f"Bearer {token}", "X-Workspace-ID": workspace},
            timeout=10,
            # This acceptance URL is the loopback port published by the
            # ephemeral Compose stack. It must never be routed through a
            # user's desktop HTTP proxy.
            trust_env=False,
        )

    assert get(valid).status_code == 200
    assert get(forged).status_code == 401
    assert get(expired).status_code == 401
