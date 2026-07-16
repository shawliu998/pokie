from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = Path(__file__).with_name("dependency_policy.json")
NOTICE_PATH = ROOT / "THIRD_PARTY_NOTICES.md"

DEPENDENCY_GROUPS = ("dependencies", "devDependencies", "peerDependencies")
RUST_DEPENDENCY_GROUPS = ("dependencies", "dev-dependencies", "build-dependencies")
WORKSPACE_SPECIFIERS = ("workspace:", "link:", "file:")
SPDX_OPERATORS = {"AND", "OR", "WITH"}


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _policy() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(POLICY_PATH.read_text(encoding="utf-8")))


def _records(ecosystem: str) -> dict[str, dict[str, Any]]:
    records = [
        cast(dict[str, Any], item)
        for item in cast(list[object], _policy()["dependencies"])
        if cast(dict[str, Any], item)["ecosystem"] == ecosystem
    ]
    return {_canonical_name(str(record["name"])): record for record in records}


def _python_requirement(specifier: str) -> tuple[str, frozenset[str]]:
    match = re.fullmatch(r"\s*([A-Za-z0-9_.-]+)(?:\[([A-Za-z0-9_., -]+)\])?.*", specifier)
    assert match is not None, f"cannot parse Python dependency: {specifier}"
    extras = frozenset(
        item.strip().casefold() for item in (match.group(2) or "").split(",") if item.strip()
    )
    return _canonical_name(match.group(1)), extras


def _python_declared() -> dict[str, frozenset[str]]:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = manifest["project"]
    specs = list(project["dependencies"])
    for group in project.get("optional-dependencies", {}).values():
        specs.extend(group)
    return dict(_python_requirement(str(specifier)) for specifier in specs)


def _locked_python_packages() -> dict[str, dict[str, Any]]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {
        _canonical_name(str(package["name"])): cast(dict[str, Any], package)
        for package in lock["package"]
    }


def _external_javascript_dependencies(
    manifest_path: Path,
) -> dict[str, str]:
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    dependencies: dict[str, str] = {}
    for group in DEPENDENCY_GROUPS:
        for raw_name, raw_specifier in cast(dict[str, object], manifest.get(group, {})).items():
            name = str(raw_name)
            specifier = str(raw_specifier)
            if specifier.startswith(WORKSPACE_SPECIFIERS):
                continue
            previous = dependencies.setdefault(_canonical_name(name), specifier)
            assert previous == specifier, f"conflicting direct versions for {name}"
    return dependencies


def _strip_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _pnpm_importers(text: str) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    """Parse only pnpm's stable importer mapping without a YAML dependency."""

    importers: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    active = False
    importer: str | None = None
    group: str | None = None
    dependency: str | None = None
    for line in text.splitlines():
        if line == "importers:":
            active = True
            continue
        if not active:
            continue
        if line and not line.startswith(" "):
            break
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == 2 and stripped.endswith(":"):
            importer = _strip_yaml_scalar(stripped[:-1])
            importers[importer] = {}
            group = dependency = None
        elif indent == 4 and stripped[:-1] in DEPENDENCY_GROUPS and stripped.endswith(":"):
            assert importer is not None
            group = stripped[:-1]
            importers[importer][group] = {}
            dependency = None
        elif indent == 6 and stripped.endswith(":") and group is not None:
            assert importer is not None
            dependency = _strip_yaml_scalar(stripped[:-1])
            importers[importer][group][dependency] = {}
        elif indent == 8 and ":" in stripped and dependency is not None and group is not None:
            assert importer is not None
            key, value = stripped.split(":", 1)
            if key in {"specifier", "version"}:
                importers[importer][group][dependency][key] = _strip_yaml_scalar(value)
    return importers


def _rust_dependency_tables(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield manifest
    for target in cast(dict[str, Any], manifest.get("target", {})).values():
        yield cast(dict[str, Any], target)


def _rust_declared() -> dict[str, str]:
    manifest = tomllib.loads((ROOT / "apps/mac/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    dependencies: dict[str, str] = {}
    for table in _rust_dependency_tables(manifest):
        for group in RUST_DEPENDENCY_GROUPS:
            for raw_name, raw_specifier in cast(dict[str, object], table.get(group, {})).items():
                specifier = (
                    str(cast(dict[str, object], raw_specifier)["version"])
                    if isinstance(raw_specifier, dict)
                    else str(raw_specifier)
                )
                name = _canonical_name(str(raw_name))
                previous = dependencies.setdefault(name, specifier)
                assert previous == specifier, f"conflicting direct versions for {raw_name}"
    return dependencies


def _spdx_ids(expression: str) -> set[str]:
    tokens = set(re.findall(r"[A-Za-z0-9.+-]+", expression))
    return tokens - SPDX_OPERATORS


def test_license_policy_is_allowlist_only_and_blocks_unapproved_projects() -> None:
    policy = _policy()
    assert policy["schema_version"] == 1
    allowed = set(cast(list[str], policy["allowed_spdx_licenses"]))
    assert allowed == {"Apache-2.0", "BSD-3-Clause", "LGPL-3.0-only", "MIT"}
    blocked = {_canonical_name(name) for name in policy["blocked_dependency_names"]}

    records = cast(list[dict[str, Any]], policy["dependencies"])
    assert records, "the license gate must never pass with an empty inventory"
    identities: set[tuple[str, str]] = set()
    for record in records:
        identity = (str(record["ecosystem"]), _canonical_name(str(record["name"])))
        assert identity not in identities, f"duplicate policy record: {identity}"
        identities.add(identity)
        assert identity[1] not in blocked, f"blocked project selected: {identity[1]}"

        license_ids = _spdx_ids(str(record["license"]))
        assert license_ids, f"missing SPDX license for {identity}"
        assert license_ids <= allowed, f"unapproved/custom license for {identity}: {license_ids}"
        assert not any(
            identifier.startswith(("GPL-", "AGPL-", "SSPL-")) for identifier in license_ids
        ), f"strong copyleft license is blocked for {identity}"
        assert str(record["version"]) and str(record["version"]) != "latest"
        assert str(record["source"]).startswith(
            ("https://pypi.org/", "https://www.npmjs.com/", "https://crates.io/")
        )


def test_python_direct_dependencies_are_in_policy_and_integrity_locked() -> None:
    declared = _python_declared()
    policy = _records("python")
    policy_manifest_names = {
        name for name, record in policy.items() if record["manifest_scope"] != "extra-artifact"
    }
    assert set(declared) == policy_manifest_names

    extras = {
        (str(record["parent"]), str(record["extra"])): name
        for name, record in policy.items()
        if record["manifest_scope"] == "extra-artifact"
    }
    for (parent, extra), artifact in extras.items():
        assert extra in declared[_canonical_name(parent)]
        assert artifact == _canonical_name(f"{parent}-{extra}")

    locked = _locked_python_packages()
    for name, record in policy.items():
        assert name in locked, f"Python direct dependency is absent from uv.lock: {name}"
        package = locked[name]
        assert package["version"] == record["version"]
        assert package.get("source") == {"registry": "https://pypi.org/simple"}
        artifacts = ([package["sdist"]] if "sdist" in package else []) + list(
            package.get("wheels", [])
        )
        assert artifacts, f"locked Python artifact has no integrity record: {name}"
        assert all(str(artifact["hash"]).startswith("sha256:") for artifact in artifacts)


def test_javascript_direct_dependencies_are_exact_and_integrity_locked() -> None:
    manifest_paths = (
        ROOT / "package.json",
        ROOT / "apps/mac/package.json",
        ROOT / "packages/ui/package.json",
    )
    declared_by_importer: dict[str, dict[str, str]] = {}
    for manifest_path in manifest_paths:
        importer = (
            "."
            if manifest_path.parent == ROOT
            else manifest_path.parent.relative_to(ROOT).as_posix()
        )
        declared_by_importer[importer] = _external_javascript_dependencies(manifest_path)

    declared_names = set().union(*(set(items) for items in declared_by_importer.values()))
    policy = _records("javascript")
    assert declared_names == set(policy)

    lock_text = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    importers = _pnpm_importers(lock_text)
    assert set(declared_by_importer) == set(importers)
    for importer, dependencies in declared_by_importer.items():
        locked_dependencies = {
            _canonical_name(name): metadata
            for group in importers[importer].values()
            for name, metadata in group.items()
        }
        for name, specifier in dependencies.items():
            assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", specifier), (
                f"JavaScript direct dependency must be exact: {name}={specifier}"
            )
            assert policy[name]["version"] == specifier
            metadata = locked_dependencies[name]
            assert metadata["specifier"] == specifier
            locked_version = metadata["version"]
            assert locked_version == specifier or locked_version.startswith(specifier + "(")

            package_key = re.escape(str(policy[name]["name"]) + "@" + specifier)
            package_record = re.search(
                rf"(?m)^  ['\"]?{package_key}['\"]?:\n(?P<body>(?:    .*\n|\n)*)",
                lock_text,
            )
            assert package_record is not None, f"missing pnpm package record: {name}@{specifier}"
            assert "integrity:" in package_record.group("body"), (
                f"pnpm package has no integrity digest: {name}@{specifier}"
            )


def test_rust_direct_dependencies_are_exact_and_checksum_locked() -> None:
    declared = _rust_declared()
    policy = _records("rust")
    assert set(declared) == set(policy)

    lock = tomllib.loads((ROOT / "apps/mac/src-tauri/Cargo.lock").read_text(encoding="utf-8"))
    locked = cast(list[dict[str, Any]], lock["package"])
    for name, specifier in declared.items():
        assert specifier.startswith("=") and len(specifier) > 1, (
            f"Rust direct dependency must be exact: {name}={specifier}"
        )
        version = specifier[1:]
        assert policy[name]["version"] == version
        matches = [
            package
            for package in locked
            if _canonical_name(str(package["name"])) == name and package["version"] == version
        ]
        assert len(matches) == 1, (
            f"Rust direct dependency is absent/ambiguous in Cargo.lock: {name}"
        )
        package = matches[0]
        assert str(package.get("source", "")).startswith("registry+")
        assert re.fullmatch(r"[0-9a-f]{64}", str(package.get("checksum", "")))


def test_third_party_notices_cover_policy_without_copying_license_bodies() -> None:
    notice = NOTICE_PATH.read_text(encoding="utf-8")
    records = cast(list[dict[str, Any]], _policy()["dependencies"])
    for record in records:
        row = (
            f"| {record['ecosystem']} | `{record['name']}` | `{record['version']}` | "
            f"`{record['license']}` | [source]({record['source']}) |"
        )
        assert row in notice, f"missing notice row for {record['ecosystem']}:{record['name']}"

    assert "LGPL-3.0-only" in notice and "replacement rights" in notice
    assert "No shadcn/ui component" in notice
    assert "Permission is hereby granted" not in notice
    assert len(notice.encode("utf-8")) < 20_000
