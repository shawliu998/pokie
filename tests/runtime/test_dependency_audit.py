from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.error import HTTPError

import pytest

from scripts import audit_npm_lock


def test_bulk_adapter_fails_closed_on_http_410(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> object:
        raise HTTPError(audit_npm_lock.ENDPOINT, 410, "gone", {}, None)

    monkeypatch.setattr(audit_npm_lock, "urlopen", unavailable)
    with pytest.raises(audit_npm_lock.AuditError, match="HTTP 410"):
        audit_npm_lock._request_batch({"vite": ["7.0.0"]})


def test_bulk_adapter_fails_closed_on_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audit_npm_lock,
        "_request_batch",
        lambda packages: {"error": "registry unavailable"},
    )
    with pytest.raises(audit_npm_lock.AuditError, match="unexpected shape"):
        audit_npm_lock._bulk_advisories({"vite": ["7.0.0"]})


def test_production_scope_follows_only_runtime_dependency_graph() -> None:
    document = {
        "importers": {
            ".": {
                "dependencies": {"runtime-package": {"version": "1.0.0"}},
                "devDependencies": {"test-package": {"version": "9.0.0"}},
            }
        },
        "packages": {
            "runtime-package@1.0.0": {"resolution": {"integrity": "sha512-runtime"}},
            "runtime-child@2.0.0": {"resolution": {"integrity": "sha512-child"}},
            "test-package@9.0.0": {"resolution": {"integrity": "sha512-test"}},
        },
        "snapshots": {
            "runtime-package@1.0.0": {"dependencies": {"runtime-child": "2.0.0"}},
            "runtime-child@2.0.0": {},
        },
    }
    assert audit_npm_lock._production_packages(document) == {
        "runtime-child": ["2.0.0"],
        "runtime-package": ["1.0.0"],
    }


def test_rust_audit_uses_cargo_audit_subcommand() -> None:
    script = Path("scripts/audit_dependencies.sh").read_text(encoding="utf-8")
    assert '"$cargo_audit_bin" audit --file "$lock_path"' in script


def test_uv_discovery_includes_macos_user_install_path() -> None:
    script = Path("scripts/verify_common.sh").read_text(encoding="utf-8")
    assert '"$HOME/Library/Python/3.12/bin/uv"' in script


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("uv 0.11.28", True),
        ("uv 0.11.28 (ebf0f43d7 aarch64-apple-darwin)", True),
        ("uv 0.11.27", False),
    ],
)
def test_uv_gate_accepts_only_pinned_version_with_optional_metadata(
    reported: str, expected: bool
) -> None:
    expression = r"^uv[[:space:]]0\.11\.28([[:space:]]|$)"
    result = subprocess.run(
        ["bash", "-c", '[[ "$1" =~ $2 ]]', "uv-version-check", reported, expression],
        check=False,
    )
    assert (result.returncode == 0) is expected
