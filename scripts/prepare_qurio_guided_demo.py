#!/usr/bin/env python3
"""Prepare a current-schema, presentation-only copy of the retained C5 golden research.

The source database and its evidence remain untouched. The generated copy is migrated,
materializes only compatibility markers required by the current reader, and is then
opened read-only by ``launch_quant_live_session.py --guided-demo``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "docs" / "portfolio" / "guided-demo"
SOURCE_SESSION_PATH = SOURCE_DIR / "qurio-guided-demo-session.json"
TARGET_DIR = REPO_ROOT / ".run" / "qurio-guided-demo-portfolio"
TARGET_SESSION_PATH = TARGET_DIR / "pokiequant-live-session.json"
TARGET_MANIFEST_PATH = TARGET_DIR / "guided-demo-manifest.json"
PRE_MIGRATION_REVISION = "20260722_0007"
PREPARATION_VERSION = 3


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _migration_head() -> str:
    config = Config(str(REPO_ROOT / "infra" / "migrations" / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Guided demo requires one migration head; found {heads}.")
    return heads[0]


def _source_database(session: dict[str, Any]) -> Path:
    raw = Path(str(session["database_path"])).expanduser()
    return raw.resolve() if raw.is_absolute() else (SOURCE_SESSION_PATH.parent / raw).resolve()


def _cache_is_current(*, source_digest: str, migration_head: str) -> bool:
    if not TARGET_SESSION_PATH.is_file() or not TARGET_MANIFEST_PATH.is_file():
        return False
    manifest = _read_object(TARGET_MANIFEST_PATH)
    target_database = TARGET_DIR / "pokiequant-live.db"
    return (
        target_database.is_file()
        and manifest.get("source_database_sha256") == source_digest
        and manifest.get("migration_head") == migration_head
        and manifest.get("preparation_version") == PREPARATION_VERSION
        and manifest.get("prepared_database_sha256") == _digest(target_database)
    )


def _migrate_copy(database_path: Path) -> None:
    database_url = f"sqlite:///{database_path.resolve()}"
    with sqlite3.connect(database_path) as connection:
        has_version_table = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
            ).fetchone()
            is not None
        )
    config = Config(str(REPO_ROOT / "infra" / "migrations" / "alembic.ini"))
    config.attributes["database_url"] = database_url
    if not has_version_table:
        command.stamp(config, PRE_MIGRATION_REVISION)
    command.upgrade(config, "head")


def _materialize_reader_compatibility(
    *, database_path: Path, object_store_root: Path, workspace_id: str, run_id: str
) -> None:
    os.environ.update(
        {
            "GLINT_ENVIRONMENT": "development",
            "GLINT_SERVICE_ROLE": "api",
            "GLINT_DATABASE_URL": f"sqlite:///{database_path.resolve()}",
            "GLINT_OBJECT_STORE_BACKEND": "filesystem",
            "GLINT_OBJECT_STORE_ROOT": str(object_store_root.resolve()),
            "GLINT_CREATE_SCHEMA_ON_STARTUP": "false",
        }
    )
    from services.api.app.core.config import get_settings
    from services.api.app.db.session import reset_database_caches
    from services.api.app.modules.quant.store import get_quant_store
    from packages.contracts.quant.enums import QuantArtifactKind
    from packages.domain.canonical import canonical_digest

    get_settings.cache_clear()
    reset_database_caches()
    store = get_quant_store()
    runs = store.list_runs(workspace_id=workspace_id)
    if not any(run.id == run_id for run in runs):
        raise RuntimeError("The retained golden Run is missing after compatibility preparation.")
    artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
    reports = [
        artifact for artifact in artifacts if artifact.kind is QuantArtifactKind.RESEARCH_REPORT
    ]
    comparisons = sorted(
        (
            artifact
            for artifact in artifacts
            if artifact.kind is QuantArtifactKind.VALIDATION_REPORT
            and artifact.content.get("evaluation_partition") == "train"
        ),
        key=lambda artifact: artifact.ordinal,
    )
    if len(reports) != 1 or not comparisons:
        raise RuntimeError("The retained golden Run is missing its final report or comparison.")
    report = reports[0]
    selected_candidate_id = report.content.get("selected_candidate_id")
    latest_comparison = comparisons[-1]
    ranking = latest_comparison.content.get("ranking")
    if (
        not isinstance(selected_candidate_id, str)
        or not isinstance(ranking, list)
        or not ranking
        or ranking[0] != selected_candidate_id
    ):
        raise RuntimeError("The retained golden Run cannot be upgraded to a rank-bound decision.")
    if report.content.get("research_decision") is None:
        # P19 made the already-retained final choice explicit. This compatibility
        # enrichment binds the old report to its own final train-only comparison;
        # it does not rerun, re-rank, or reveal holdout evidence to the Agent.
        report.content["research_decision"] = {
            "selected_candidate_id": selected_candidate_id,
            "source_comparison_artifact_id": latest_comparison.id,
            "decision_basis": "approved_objective_rank",
            "deviation": None,
        }
        report.digest = canonical_digest(report.content)
    # The one-time legacy Research Memory load rewrites the copied state. Persist
    # once more so the independent P18/P19 repository markers match that state;
    # this changes compatibility metadata only, never the retained experiments.
    store._persist_workspace(workspace_id)  # noqa: SLF001
    verified_runs = get_quant_store().list_runs(workspace_id=workspace_id)
    if not any(run.id == run_id for run in verified_runs):
        raise RuntimeError("The prepared golden Run failed its current-reader verification.")
    reset_database_caches()
    get_settings.cache_clear()


def prepare() -> Path:
    if not SOURCE_SESSION_PATH.is_file():
        raise RuntimeError(f"Retained guided-demo session is missing: {SOURCE_SESSION_PATH}")
    session = _read_object(SOURCE_SESSION_PATH)
    source_database = _source_database(session)
    if not source_database.is_file():
        raise RuntimeError(f"Retained C5 database is missing: {source_database}")
    source_digest = _digest(source_database)
    migration_head = _migration_head()
    if _cache_is_current(source_digest=source_digest, migration_head=migration_head):
        return TARGET_SESSION_PATH

    TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=".qurio-guided-demo-", dir=TARGET_DIR.parent)
    ).resolve()
    try:
        target_database = temporary_dir / "pokiequant-live.db"
        target_objects = temporary_dir / "pokiequant-live-objects"
        shutil.copy2(source_database, target_database)
        source_objects = SOURCE_DIR / "pokiequant-live-objects"
        if source_objects.is_dir():
            shutil.copytree(source_objects, target_objects)
        else:
            target_objects.mkdir()

        _migrate_copy(target_database)
        _materialize_reader_compatibility(
            database_path=target_database,
            object_store_root=target_objects,
            workspace_id=str(session["workspace_id"]),
            run_id=str(session["run_id"]),
        )

        prepared_session = {
            **session,
            "database_path": "pokiequant-live.db",
        }
        (temporary_dir / "pokiequant-live-session.json").write_text(
            json.dumps(prepared_session, indent=2) + "\n"
        )
        (temporary_dir / "guided-demo-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "qurio-guided-demo-manifest-v1",
                    "preparation_version": PREPARATION_VERSION,
                    "source_database_sha256": source_digest,
                    "source_database_bytes": source_database.stat().st_size,
                    "migration_head": migration_head,
                    "prepared_database_sha256": _digest(target_database),
                    "workspace_id": session["workspace_id"],
                    "run_id": session["run_id"],
                    "provider": "deepseek",
                    "model": session["model"],
                    "mock_fallback_allowed": False,
                    "presentation_copy_only": True,
                },
                indent=2,
            )
            + "\n"
        )
        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR)
        temporary_dir.rename(TARGET_DIR)
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise
    return TARGET_SESSION_PATH


def main() -> int:
    prepared = prepare()
    print(f"Prepared read-only Guided Demo: {prepared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
