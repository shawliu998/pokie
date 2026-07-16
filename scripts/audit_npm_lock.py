#!/usr/bin/env python3
"""Fail-closed pnpm lock audit using npm's official bulk advisory endpoint."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://registry.npmjs.org/-/npm/v1/security/advisories/bulk"
LOCAL_REFERENCES = ("file:", "link:", "workspace:")
PRODUCTION_GROUPS = ("dependencies", "optionalDependencies")
SEVERITY_RANK = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
GHSA_ID = re.compile(r"^GHSA-[0-9A-Za-z-]+$")


class AuditError(RuntimeError):
    """Raised when dependency collection or the advisory service is not trustworthy."""


@dataclass(frozen=True, slots=True)
class AuditFinding:
    package: str
    severity: str
    advisory_ids: tuple[str, ...]


def _load_lock(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as error:
        raise AuditError("PyYAML is required to parse the pnpm lockfile") from error
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise AuditError("cannot read the pnpm lockfile") from error
    except yaml.YAMLError as error:
        raise AuditError("cannot parse the pnpm lockfile") from error
    if not isinstance(document, dict):
        raise AuditError("pnpm lockfile root is not an object")
    if not str(document.get("lockfileVersion", "")).startswith("9"):
        raise AuditError("pnpm lockfile has no supported lockfileVersion")
    return document


def _registry_package_key(raw_key: str) -> tuple[str, str]:
    """Return a package/version pair, removing pnpm peer-context suffixes."""

    key = raw_key.removeprefix("/")
    peer_offset = key.find("(")
    base = key if peer_offset < 0 else key[:peer_offset]
    separator = base.rfind("@")
    if separator <= 0:
        raise AuditError("pnpm registry package key has an unexpected shape")
    name = base[:separator]
    version = base[separator + 1 :]
    if (
        not name
        or (name.startswith("@") and "/" not in name)
        or not version
        or not version[0].isdigit()
        or any(character.isspace() for character in version)
    ):
        raise AuditError("pnpm registry package key has an unexpected shape")
    return name, version


def _registry_pairs(document: dict[str, Any]) -> set[tuple[str, str]]:
    packages = document.get("packages")
    if not isinstance(packages, dict):
        raise AuditError("pnpm lockfile has no packages graph")
    pairs: set[tuple[str, str]] = set()
    for raw_key, raw_metadata in packages.items():
        if not isinstance(raw_key, str) or not isinstance(raw_metadata, dict):
            raise AuditError("pnpm package record has an unexpected shape")
        resolution = raw_metadata.get("resolution")
        if not isinstance(resolution, dict):
            continue
        if not isinstance(resolution.get("integrity") or resolution.get("tarball"), str):
            continue
        pairs.add(_registry_package_key(raw_key))
    return pairs


def _as_reference(raw_value: object) -> str:
    if isinstance(raw_value, str):
        return raw_value
    if isinstance(raw_value, dict) and isinstance(raw_value.get("version"), str):
        return str(raw_value["version"])
    raise AuditError("pnpm dependency reference has an unexpected shape")


def _is_local_reference(reference: str) -> bool:
    return reference.startswith(LOCAL_REFERENCES)


def _package_map(pairs: set[tuple[str, str]]) -> dict[str, list[str]]:
    if not pairs:
        raise AuditError("pnpm lock audit selected no registry packages")
    packages: dict[str, set[str]] = {}
    for name, version in pairs:
        packages.setdefault(name, set()).add(version)
    return {name: sorted(versions) for name, versions in sorted(packages.items())}


def _full_packages(document: dict[str, Any]) -> dict[str, list[str]]:
    return _package_map(_registry_pairs(document))


def _production_packages(document: dict[str, Any]) -> dict[str, list[str]]:
    registry_pairs = _registry_pairs(document)
    importers = document.get("importers")
    snapshots = document.get("snapshots")
    if not isinstance(importers, dict) or not isinstance(snapshots, dict):
        raise AuditError("pnpm lockfile has no importer/snapshot graph")

    queue: list[tuple[str, str]] = []
    for importer in importers.values():
        if not isinstance(importer, dict):
            raise AuditError("pnpm importer has an unexpected shape")
        for group in PRODUCTION_GROUPS:
            dependencies = importer.get(group, {})
            if not isinstance(dependencies, dict):
                raise AuditError("pnpm importer dependency group has an unexpected shape")
            for raw_name, raw_reference in dependencies.items():
                if not isinstance(raw_name, str):
                    raise AuditError("pnpm dependency name is not a string")
                reference = _as_reference(raw_reference)
                if not _is_local_reference(reference):
                    queue.append((raw_name, reference))

    selected: set[tuple[str, str]] = set()
    visited_snapshots: set[str] = set()
    while queue:
        name, reference = queue.pop()
        snapshot_key = f"{name}@{reference}"
        if snapshot_key in visited_snapshots:
            continue
        snapshot = snapshots.get(snapshot_key)
        if not isinstance(snapshot, dict):
            raise AuditError("pnpm production dependency is absent from snapshots")
        visited_snapshots.add(snapshot_key)

        package_pair = _registry_package_key(snapshot_key)
        if package_pair not in registry_pairs:
            raise AuditError("pnpm production dependency has no integrity-locked package")
        selected.add(package_pair)

        for group in PRODUCTION_GROUPS:
            dependencies = snapshot.get(group, {})
            if not isinstance(dependencies, dict):
                raise AuditError("pnpm snapshot dependency group has an unexpected shape")
            for raw_name, raw_reference in dependencies.items():
                if not isinstance(raw_name, str):
                    raise AuditError("pnpm snapshot dependency name is not a string")
                child_reference = _as_reference(raw_reference)
                if not _is_local_reference(child_reference):
                    queue.append((raw_name, child_reference))

    return _package_map(selected)


def _advisory_ids(advisory: dict[str, Any]) -> tuple[str, ...]:
    identifiers: set[str] = set()
    raw_id = advisory.get("id")
    if isinstance(raw_id, (int, str)) and str(raw_id):
        identifiers.add(f"npm:{raw_id}")
    raw_url = advisory.get("url")
    if isinstance(raw_url, str):
        candidate = raw_url.rstrip("/").rsplit("/", 1)[-1]
        if GHSA_ID.fullmatch(candidate):
            identifiers.add(candidate)
    if not identifiers:
        raise AuditError("npm advisory has no stable identifier")
    return tuple(sorted(identifiers))


def _request_batch(packages: dict[str, list[str]], *, timeout: float = 45) -> dict[str, Any]:
    request = Request(
        ENDPOINT,
        data=json.dumps(packages, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "glint-lock-audit/1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise AuditError(f"npm bulk advisory endpoint returned HTTP {response.status}")
            raw_body = response.read()
    except HTTPError as error:
        raise AuditError(f"npm bulk advisory endpoint returned HTTP {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise AuditError(f"npm bulk advisory request failed: {type(error).__name__}") from error
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditError("npm bulk advisory endpoint returned invalid JSON") from error
    if not isinstance(payload, dict) or "error" in payload:
        raise AuditError("npm bulk advisory endpoint returned an error payload")
    return payload


def _bulk_advisories(
    packages: dict[str, list[str]], *, batch_size: int = 100
) -> list[AuditFinding]:
    if not packages:
        raise AuditError("npm lock audit selected no registry packages")
    if batch_size < 1:
        raise AuditError("npm audit batch size must be positive")

    findings: list[AuditFinding] = []
    names = sorted(packages)
    for offset in range(0, len(names), batch_size):
        batch_names = names[offset : offset + batch_size]
        batch = {name: packages[name] for name in batch_names}
        payload = _request_batch(batch)
        for name, advisories in payload.items():
            if name not in batch or not isinstance(advisories, list):
                raise AuditError("npm bulk advisory response has an unexpected shape")
            for advisory in advisories:
                if not isinstance(advisory, dict):
                    raise AuditError("npm bulk advisory entry is not an object")
                severity = advisory.get("severity")
                if not isinstance(severity, str) or severity not in SEVERITY_RANK:
                    raise AuditError("npm advisory has an unknown severity")
                findings.append(
                    AuditFinding(
                        package=name,
                        severity=severity,
                        advisory_ids=_advisory_ids(advisory),
                    )
                )
    return sorted(
        findings,
        key=lambda finding: (
            finding.package,
            -SEVERITY_RANK[finding.severity],
            finding.advisory_ids,
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit an integrity-locked pnpm graph using npm's official bulk API."
    )
    parser.add_argument("lockfile", nargs="?", default="pnpm-lock.yaml", type=Path)
    parser.add_argument("--scope", choices=("full", "prod"), default="full")
    parser.add_argument(
        "--audit-level",
        choices=tuple(SEVERITY_RANK),
        default="moderate",
        help="lowest advisory severity that fails the audit (default: moderate)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        document = _load_lock(arguments.lockfile)
        packages = (
            _full_packages(document)
            if arguments.scope == "full"
            else _production_packages(document)
        )
        findings = _bulk_advisories(packages)
    except AuditError as error:
        print(f"npm lock audit failed: {error}", file=sys.stderr)
        return 2

    artifact_count = sum(len(versions) for versions in packages.values())
    print(f"npm lock audit checked {artifact_count} registry artifacts in {arguments.scope} scope")
    threshold = SEVERITY_RANK[arguments.audit_level]
    blocked = False
    for finding in findings:
        is_blocking = SEVERITY_RANK[finding.severity] >= threshold
        blocked = blocked or is_blocking
        print(
            "npm advisory: "
            f"package={finding.package} severity={finding.severity} "
            f"blocked={str(is_blocking).lower()} "
            f"ids={','.join(finding.advisory_ids)}"
        )
    if blocked:
        print(f"npm lock audit blocked at level {arguments.audit_level}")
        return 1
    print(f"npm lock audit passed at level {arguments.audit_level}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
