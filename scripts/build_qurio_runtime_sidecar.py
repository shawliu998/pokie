#!/usr/bin/env python3
"""Freeze the Qurio local API and Agent worker into a relocatable macOS sidecar."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

RUNTIME_NAME = "qurio-runtime"
BUNDLE_PYTHON = "3.12.13"
BUNDLE_ENV_MARKER = "QURIO_BUNDLE_ENV"


def build_arguments(repo_root: Path) -> list[str]:
    output_root = repo_root / "apps" / "mac" / "src-tauri" / "resources"
    build_root = repo_root / ".run" / "pyinstaller" / RUNTIME_NAME
    return [
        str(repo_root / "scripts" / "run_qurio_local_runtime.py"),
        f"--name={RUNTIME_NAME}",
        "--onedir",
        "--noconfirm",
        "--clean",
        f"--distpath={output_root}",
        f"--workpath={build_root / 'work'}",
        f"--specpath={build_root / 'spec'}",
        f"--paths={repo_root}",
        "--hidden-import=services.worker.app.repositories.sqlalchemy_adapter",
        "--collect-submodules=services",
        "--collect-submodules=packages",
        "--collect-submodules=connectors",
        "--exclude-module=pytest",
        "--exclude-module=pyright",
        "--exclude-module=ruff",
    ]


def uv_executable(repo_root: Path) -> Path:
    candidates = (
        repo_root / ".venv" / "bin" / "uv",
        Path.home() / "Library" / "Python" / "3.12" / "bin" / "uv",
        Path.home() / ".local" / "bin" / "uv",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    discovered = shutil.which("uv")
    if discovered:
        return Path(discovered)
    raise RuntimeError("uv is required to build the standalone Qurio runtime.")


def run_in_bundle_environment(repo_root: Path) -> int:
    uv = uv_executable(repo_root)
    bundle_env = repo_root / ".run" / "qurio-bundle-venv"
    environment = {
        **os.environ,
        "UV_MANAGED_PYTHON": "1",
        "UV_PROJECT_ENVIRONMENT": str(bundle_env),
        "UV_PYTHON": BUNDLE_PYTHON,
    }
    subprocess.run(
        [str(uv), "python", "install", BUNDLE_PYTHON],
        cwd=repo_root,
        env=environment,
        check=True,
    )
    subprocess.run(
        [
            str(uv),
            "sync",
            "--locked",
            "--extra",
            "bundle",
            "--no-install-project",
        ],
        cwd=repo_root,
        env=environment,
        check=True,
    )
    bundled_python = bundle_env / "bin" / "python"
    child_environment = {**environment, BUNDLE_ENV_MARKER: "1"}
    return subprocess.run(
        [str(bundled_python), str(Path(__file__).resolve())],
        cwd=repo_root,
        env=child_environment,
        check=False,
    ).returncode


def main() -> int:
    if sys.platform != "darwin":
        print(
            "Qurio's distributable local runtime is currently built only on macOS.",
            file=sys.stderr,
        )
        return 2
    repo_root = Path(__file__).resolve().parents[1]
    if os.environ.get(BUNDLE_ENV_MARKER) != "1":
        try:
            return run_in_bundle_environment(repo_root)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"Could not prepare the Qurio bundle environment: {exc}", file=sys.stderr)
            return 2
    try:
        import PyInstaller.__main__
    except ImportError:
        print(
            "PyInstaller is missing. Run `.venv/bin/uv sync --locked --extra test --extra bundle`.",
            file=sys.stderr,
        )
        return 2

    output_dir = repo_root / "apps" / "mac" / "src-tauri" / "resources" / RUNTIME_NAME
    if output_dir.exists():
        shutil.rmtree(output_dir)
    PyInstaller.__main__.run(build_arguments(repo_root))
    executable = output_dir / RUNTIME_NAME
    if not executable.is_file():
        print("PyInstaller did not produce the Qurio runtime executable.", file=sys.stderr)
        return 1
    (output_dir / ".gitkeep").touch()
    manifest = {
        "architecture": platform.machine(),
        "format": "pyinstaller-onedir-v1",
        "python": platform.python_version(),
        "runtime": RUNTIME_NAME,
    }
    (output_dir / "qurio-runtime-build.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    size_bytes = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file())
    print(f"Built {executable} ({size_bytes / 1024 / 1024:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
