from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from scripts import audit_npm_lock

# pyright: reportPrivateUsage=false

LOCK_FIXTURE = """
lockfileVersion: '9.0'
importers:
  apps/mac:
    dependencies:
      '@scope/tool':
        specifier: 2.0.0
        version: 2.0.0(peer-lib@1.1.0)
      local-workspace:
        specifier: workspace:*
        version: link:../../packages/local
    devDependencies:
      dev-only:
        specifier: 9.0.0
        version: 9.0.0
packages:
  '@scope/tool@2.0.0':
    resolution: {integrity: sha512-tool}
  dev-only@9.0.0:
    resolution: {integrity: sha512-dev}
  local-workspace@file:../../packages/local: {}
  peer-lib@1.1.0:
    resolution: {integrity: sha512-peer}
snapshots:
  '@scope/tool@2.0.0(peer-lib@1.1.0)':
    dependencies:
      peer-lib: 1.1.0
  dev-only@9.0.0: {}
  peer-lib@1.1.0: {}
""".lstrip()

EMPTY_LOCK_FIXTURE = """
lockfileVersion: '9.0'
importers: {}
packages: {}
snapshots: {}
""".lstrip()

DEV_EXCEPTION_LOCK_FIXTURE = """
lockfileVersion: '9.0'
importers:
  apps/mac:
    dependencies:
      runtime-tool:
        specifier: 1.0.0
        version: 1.0.0
    devDependencies:
      eslint:
        specifier: 9.35.0
        version: 9.35.0
packages:
  brace-expansion@1.1.16:
    resolution: {integrity: sha512-brace-v1}
  brace-expansion@2.1.2:
    resolution: {integrity: sha512-brace-v2}
  eslint@9.35.0:
    resolution: {integrity: sha512-eslint}
  runtime-tool@1.0.0:
    resolution: {integrity: sha512-runtime}
snapshots:
  brace-expansion@1.1.16: {}
  brace-expansion@2.1.2: {}
  eslint@9.35.0:
    dependencies:
      brace-expansion: 1.1.16
  runtime-tool@1.0.0: {}
""".lstrip()


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class UrlOpenStub(Protocol):
    def __call__(self, request: Request, *, timeout: float) -> FakeResponse: ...


def _lockfile(tmp_path: Path, body: str = LOCK_FIXTURE) -> Path:
    path = tmp_path / "pnpm-lock.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _response(payload: object) -> UrlOpenStub:
    body = json.dumps(payload).encode("utf-8")

    def open_response(request: Request, *, timeout: float) -> FakeResponse:
        del request
        assert timeout == 45
        return FakeResponse(body)

    return open_response


def test_extracts_scoped_peer_and_production_graph_without_dev_or_local(
    tmp_path: Path,
) -> None:
    document = audit_npm_lock._load_lock(_lockfile(tmp_path))

    assert audit_npm_lock._registry_package_key("@scope/tool@2.0.0(peer-lib@1.1.0)") == (
        "@scope/tool",
        "2.0.0",
    )
    assert audit_npm_lock._full_packages(document) == {
        "@scope/tool": ["2.0.0"],
        "dev-only": ["9.0.0"],
        "peer-lib": ["1.1.0"],
    }
    assert audit_npm_lock._production_packages(document) == {
        "@scope/tool": ["2.0.0"],
        "peer-lib": ["1.1.0"],
    }


@pytest.mark.parametrize(
    "resolver",
    (audit_npm_lock._full_packages, audit_npm_lock._production_packages),
)
def test_empty_graph_is_fail_closed(
    tmp_path: Path,
    resolver: object,
) -> None:
    document = audit_npm_lock._load_lock(_lockfile(tmp_path, EMPTY_LOCK_FIXTURE))
    with pytest.raises(audit_npm_lock.AuditError, match="selected no registry packages"):
        assert callable(resolver)
        resolver(document)


@pytest.mark.parametrize("status", (410, 500))
def test_http_errors_are_nonzero_and_response_body_is_not_leaked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    def fail(request: Request, *, timeout: float) -> FakeResponse:
        assert timeout == 45
        raise HTTPError(
            request.full_url,
            status,
            "TOP_SECRET",
            hdrs=Message(),
            fp=BytesIO(b'{"error":"TOP_SECRET"}'),
        )

    monkeypatch.setattr(audit_npm_lock, "urlopen", fail)
    assert audit_npm_lock.main([str(_lockfile(tmp_path))]) == 2
    output = capsys.readouterr()
    assert f"HTTP {status}" in output.err
    assert "TOP_SECRET" not in output.out + output.err


def test_transient_transport_error_retries_without_weakening_fail_closed_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = 0
    sleeps: list[float] = []
    success = _response({})

    def flaky(request: Request, *, timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls < audit_npm_lock.REQUEST_ATTEMPTS:
            raise URLError("TOP_SECRET")
        return success(request, timeout=timeout)

    monkeypatch.setattr(audit_npm_lock, "urlopen", flaky)
    monkeypatch.setattr(audit_npm_lock.time, "sleep", sleeps.append)

    assert audit_npm_lock.main([str(_lockfile(tmp_path))]) == 0
    assert calls == audit_npm_lock.REQUEST_ATTEMPTS
    assert sleeps == [0.25, 0.5]
    assert "TOP_SECRET" not in capsys.readouterr().out


def test_persistent_transport_error_remains_fail_closed_after_bounded_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = 0

    def fail(_request: Request, *, timeout: float) -> FakeResponse:
        nonlocal calls
        assert timeout == 45
        calls += 1
        raise URLError("TOP_SECRET")

    monkeypatch.setattr(audit_npm_lock, "urlopen", fail)
    monkeypatch.setattr(audit_npm_lock.time, "sleep", lambda _seconds: None)

    assert audit_npm_lock.main([str(_lockfile(tmp_path))]) == 2
    assert calls == audit_npm_lock.REQUEST_ATTEMPTS
    output = capsys.readouterr()
    assert "request failed: URLError" in output.err
    assert "TOP_SECRET" not in output.out + output.err


@pytest.mark.parametrize(
    "body,error",
    (
        (b"not-json", "invalid JSON"),
        (b'{"error":{"message":"TOP_SECRET"}}', "error payload"),
    ),
)
def test_invalid_or_error_payload_is_nonzero_without_leaking_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    body: bytes,
    error: str,
) -> None:
    def open_invalid(_request: Request, *, timeout: float) -> FakeResponse:
        assert timeout == 45
        return FakeResponse(body)

    monkeypatch.setattr(
        audit_npm_lock,
        "urlopen",
        open_invalid,
    )
    assert audit_npm_lock.main([str(_lockfile(tmp_path))]) == 2
    output = capsys.readouterr()
    assert error in output.err
    assert "TOP_SECRET" not in output.out + output.err


def test_critical_advisory_blocks_and_outputs_stable_ids_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit_npm_lock,
        "urlopen",
        _response(
            {
                "@scope/tool": [
                    {
                        "id": 1120126,
                        "url": "https://github.com/advisories/GHSA-5xrq-8626-4rwp",
                        "severity": "critical",
                        "title": "TOP_SECRET",
                    }
                ]
            }
        ),
    )
    assert (
        audit_npm_lock.main(
            [str(_lockfile(tmp_path)), "--scope", "prod", "--audit-level", "critical"]
        )
        == 1
    )
    output = capsys.readouterr()
    assert "GHSA-5xrq-8626-4rwp" in output.out
    assert "npm:1120126" in output.out
    assert "severity=critical" in output.out
    assert "TOP_SECRET" not in output.out + output.err


def test_configured_threshold_allows_lower_severity_and_empty_response_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lockfile = _lockfile(tmp_path)
    monkeypatch.setattr(
        audit_npm_lock,
        "urlopen",
        _response(
            {
                "dev-only": [
                    {
                        "id": 1103520,
                        "url": "https://github.com/advisories/GHSA-x574-m823-4x7w",
                        "severity": "moderate",
                    }
                ]
            }
        ),
    )
    assert audit_npm_lock.main([str(lockfile), "--audit-level", "high"]) == 0
    assert "blocked=false" in capsys.readouterr().out

    monkeypatch.setattr(audit_npm_lock, "urlopen", _response({}))
    assert audit_npm_lock.main([str(lockfile), "--audit-level", "moderate"]) == 0
    assert "passed at level moderate" in capsys.readouterr().out


def test_exact_reviewed_brace_expansion_advisory_is_exempt_only_when_dev_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit_npm_lock,
        "urlopen",
        _response(
            {
                "brace-expansion": [
                    {
                        "id": 1129999,
                        "url": "https://github.com/advisories/GHSA-mh99-v99m-4gvg",
                        "severity": "high",
                    }
                ]
            }
        ),
    )
    assert (
        audit_npm_lock.main(
            [
                str(_lockfile(tmp_path, DEV_EXCEPTION_LOCK_FIXTURE)),
                "--scope",
                "full",
                "--audit-level",
                "moderate",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "blocked=false" in output
    assert "reviewed_dev_only_exception=true" in output
