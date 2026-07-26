"""Fast, Docker-free guarantees for the frozen Alembic history."""

from __future__ import annotations

import ast
import json
import re
import runpy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine.interfaces import ReflectedColumn

from services.api.app.db.models import Base

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "infra" / "migrations" / "alembic.ini"
VERSIONS_DIR = ROOT / "infra" / "migrations" / "versions"
BASELINE_PATH = VERSIONS_DIR / "20260715_0001_phase1.py"

REVISION_CHAIN = (
    ("20260715_0001", None),
    ("20260715_0002", "20260715_0001"),
    ("20260715_0003", "20260715_0002"),
    ("20260715_0004", "20260715_0003"),
    ("20260715_0005", "20260715_0004"),
    ("20260717_0006", "20260715_0005"),
    ("20260722_0007", "20260717_0006"),
    ("20260723_0008", "20260722_0007"),
    ("20260723_0009", "20260723_0008"),
    ("20260723_0010", "20260723_0009"),
    ("20260725_0011", "20260723_0010"),
)


def _config(database_url: str | None = None) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent))
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _upgrade(path: Path, target: str) -> Engine:
    url = _database_url(path)
    command.upgrade(_config(url), target)
    return create_engine(url)


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        value = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert isinstance(value, str)
    return value


def _baseline_constants() -> dict[str, Any]:
    return runpy.run_path(str(BASELINE_PATH))


def _normalized_sql(value: object) -> str:
    return re.sub(r"[\s\"'()]", "", str(value)).lower()


def _column_signature(column: sa.Column[Any], engine: Engine) -> tuple[str, bool, str | None]:
    server_default = column.server_default
    rendered_default = (
        None if server_default is None else str(getattr(server_default, "arg", server_default))
    )
    return (
        str(column.type.compile(dialect=engine.dialect)).lower(),
        bool(column.nullable),
        rendered_default,
    )


def _inspected_column_signature(column: ReflectedColumn, engine: Engine) -> tuple[str, bool, Any]:
    return (
        str(column["type"].compile(dialect=engine.dialect)).lower(),
        bool(column["nullable"]),
        column["default"],
    )


def _assert_critical_head_shape(engine: Engine) -> None:
    inspector = inspect(engine)

    content_item_columns = {row["name"] for row in inspector.get_columns("content_items")}
    assert "independence_group_id" in content_item_columns
    content_item_indexes = {
        row["name"]: tuple(row["column_names"]) for row in inspector.get_indexes("content_items")
    }
    assert content_item_indexes["ix_content_items_duplicate_cluster_id"] == (
        "duplicate_cluster_id",
    )
    assert content_item_indexes["ix_content_items_independence_group_id"] == (
        "independence_group_id",
    )

    signal_evidence_columns = {row["name"] for row in inspector.get_columns("signal_evidence")}
    assert "independence_group_id" in signal_evidence_columns
    signal_evidence_indexes = {
        row["name"]: tuple(row["column_names"]) for row in inspector.get_indexes("signal_evidence")
    }
    assert signal_evidence_indexes["ix_signal_evidence_independence_group_id"] == (
        "independence_group_id",
    )

    content_version_columns = {
        row["name"]: row for row in inspector.get_columns("content_versions")
    }
    assert content_version_columns["availability"]["nullable"] is False
    assert content_version_columns["availability_last_checked_at"]["nullable"] is False
    assert content_version_columns["availability_reason"]["nullable"] is True

    signal_columns = {row["name"]: row for row in inspector.get_columns("signals")}
    assert signal_columns["disposition_json"]["nullable"] is False

    claim_columns = {row["name"]: row for row in inspector.get_columns("claim_versions")}
    for name in (
        "confidence_score",
        "confidence_policy_version",
        "confidence_input_digest",
        "generation_method",
        "generator_version",
        "suggestion_origin",
    ):
        assert claim_columns[name]["nullable"] is False

    validation_columns = {row["name"] for row in inspector.get_columns("source_validation_jobs")}
    assert {
        "command",
        "state",
        "expected_source_row_version",
        "lease_owner_token",
        "fencing_version",
        "result_source_status",
    }.issubset(validation_columns)
    validation_uniques = {
        tuple(row["column_names"]): row["name"]
        for row in inspector.get_unique_constraints("source_validation_jobs")
    }
    assert validation_uniques[("workspace_id", "idempotency_key")] == (
        "uq_source_validation_idempotency"
    )
    validation_checks = " ".join(
        _normalized_sql(row["sqltext"])
        for row in inspector.get_check_constraints("source_validation_jobs")
    )
    assert "commandinhealth_check,reconnect" in validation_checks
    assert "stateinqueued,claimed,completed,failed" in validation_checks
    validation_indexes = {
        row["name"]: row for row in inspector.get_indexes("source_validation_jobs")
    }
    active_index = validation_indexes["uq_active_source_validation_job"]
    assert active_index["unique"] == 1
    assert tuple(active_index["column_names"]) == (
        "workspace_id",
        "source_connection_id",
    )
    sqlite_where = active_index.get("dialect_options", {}).get("sqlite_where")
    assert "stateinqueued,claimed" in _normalized_sql(sqlite_where)

    if "quant_repository_states" in inspector.get_table_names():
        quant_column_rows = inspector.get_columns("quant_repository_states")
        quant_columns = {row["name"] for row in quant_column_rows}
        assert {
            "workspace_id",
            "state_json",
            "fixture_state",
            "fixture_input_json",
            "fixture_row_version",
            "research_memory_contract_version",
            "evidence_replan_contract_marker",
            "research_decision_contract_marker",
            "worker_lease_token",
            "worker_lease_run_id",
            "worker_lease_worker_id",
            "worker_lease_attempt_number",
            "worker_lease_expires_at",
            "worker_heartbeat_at",
            "worker_fencing_version",
        }.issubset(quant_columns)
        decision_marker = next(
            row for row in quant_column_rows if row["name"] == "research_decision_contract_marker"
        )
        assert decision_marker["nullable"] is False
        assert "legacy-pre-p19" in str(decision_marker["default"])


def test_revision_files_are_static_and_chain_is_linear() -> None:
    scripts = sorted(VERSIONS_DIR.glob("*.py"))
    assert scripts
    for path in scripts:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        compile(tree, str(path), "exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots = {alias.name.split(".", maxsplit=1)[0] for alias in node.names}
                assert "services" not in imported_roots, path.name
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".", maxsplit=1)[0] != "services", path.name
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"create_all", "drop_all"}, path.name
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == "metadata"
                and isinstance(node.value, ast.Name)
            ):
                assert node.value.id != "Base", path.name

    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["20260725_0011"]
    observed = tuple(
        (revision.revision, revision.down_revision)
        for revision in reversed(list(script.walk_revisions()))
    )
    assert observed == REVISION_CHAIN


def test_baseline_lists_are_literal_and_cover_every_frozen_table() -> None:
    tree = ast.parse(BASELINE_PATH.read_text(encoding="utf-8"), filename=str(BASELINE_PATH))
    assignments = {
        node.targets[0].id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    for name in ("SCHEMA_TABLES", "TENANT_TABLES", "APPEND_ONLY_TABLES"):
        value = assignments[name]
        assert isinstance(value, ast.Tuple)
        assert all(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts
        )

    constants = _baseline_constants()
    schema_tables = tuple(constants["SCHEMA_TABLES"])
    tenant_tables = tuple(constants["TENANT_TABLES"])
    append_only_tables = tuple(constants["APPEND_ONLY_TABLES"])
    assert len(schema_tables) == len(set(schema_tables)) == 39
    assert set(schema_tables) - set(tenant_tables) == {
        "idempotency_records",
        "workspaces",
        "workspace_members",
    }
    assert set(append_only_tables) < set(schema_tables)


@pytest.mark.parametrize(
    ("target", "expected_revision"),
    (
        ("20260715_0001", "20260715_0001"),
        ("20260715_0002", "20260715_0002"),
        ("20260715_0003", "20260715_0003"),
        ("20260715_0004", "20260715_0004"),
        ("head", "20260725_0011"),
    ),
)
def test_empty_sqlite_database_upgrades_to_every_revision(
    tmp_path: Path, target: str, expected_revision: str
) -> None:
    engine = _upgrade(tmp_path / f"empty-{expected_revision}.sqlite3", target)
    try:
        assert _current_revision(engine) == expected_revision
        actual_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
        expected_tables = set(_baseline_constants()["SCHEMA_TABLES"])
        if target == "head":
            expected_tables.update(("quant_repository_states", "paper_trading_states"))
        assert actual_tables == expected_tables
        _assert_critical_head_shape(engine)
    finally:
        engine.dispose()


def test_fresh_head_schema_matches_current_orm_metadata_on_sqlite(tmp_path: Path) -> None:
    engine = _upgrade(tmp_path / "fresh-head.sqlite3", "head")
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) - {"alembic_version"} == set(Base.metadata.tables)
        for name, table in Base.metadata.tables.items():
            actual_columns = {
                row["name"]: _inspected_column_signature(row, engine)
                for row in inspector.get_columns(name)
            }
            expected_columns = {
                column.name: _column_signature(column, engine) for column in table.columns
            }
            assert actual_columns == expected_columns, name

            actual_foreign_keys = {
                (
                    tuple(row["constrained_columns"]),
                    row["referred_table"],
                    tuple(row["referred_columns"]),
                )
                for row in inspector.get_foreign_keys(name)
            }
            expected_foreign_keys = {
                (
                    tuple(element.parent.name for element in constraint.elements),
                    constraint.elements[0].column.table.name,
                    tuple(element.column.name for element in constraint.elements),
                )
                for constraint in table.foreign_key_constraints
            }
            assert actual_foreign_keys == expected_foreign_keys, name

            actual_uniques = {
                (row["name"], tuple(row["column_names"]))
                for row in inspector.get_unique_constraints(name)
            }
            expected_uniques = {
                (constraint.name, tuple(column.name for column in constraint.columns))
                for constraint in table.constraints
                if isinstance(constraint, sa.UniqueConstraint)
            }
            assert actual_uniques == expected_uniques, name

            actual_indexes = {
                (row["name"], tuple(row["column_names"]), bool(row["unique"]))
                for row in inspector.get_indexes(name)
            }
            expected_indexes = {
                (index.name, tuple(column.name for column in index.columns), bool(index.unique))
                for index in table.indexes
            }
            assert actual_indexes == expected_indexes, name

            actual_checks = {
                (row["name"], _normalized_sql(row["sqltext"]))
                for row in inspector.get_check_constraints(name)
            }
            expected_checks = {
                (constraint.name, _normalized_sql(constraint.sqltext))
                for constraint in table.constraints
                if isinstance(constraint, sa.CheckConstraint)
            }
            assert actual_checks == expected_checks, name

        with engine.connect() as connection:
            migration_context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "compare_server_default": True,
                    "target_metadata": Base.metadata,
                },
            )
            assert compare_metadata(migration_context, Base.metadata) == []
    finally:
        engine.dispose()


def test_research_memory_migration_marks_existing_rows_legacy_and_new_rows_current(
    tmp_path: Path,
) -> None:
    path = tmp_path / "research-memory-boundary.sqlite3"
    url = _database_url(path)
    engine = _upgrade(path, "20260722_0007")
    now = datetime.now(tz=UTC)
    metadata = sa.MetaData()
    workspaces = sa.Table("workspaces", metadata, autoload_with=engine)
    repository = sa.Table("quant_repository_states", metadata, autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            workspaces.insert().values(
                id="workspace-pre-p17",
                name="Pre-P17 workspace",
                status="active",
                data_region="local",
                retention_policy_version="retention-v1",
                created_by="migration-test",
                created_at=now,
                updated_at=now,
                row_version=1,
                data_authenticity="human_authored",
            )
        )
        connection.execute(
            repository.insert().values(
                workspace_id="workspace-pre-p17",
                created_at=now,
                updated_at=now,
                row_version=1,
                data_authenticity="generated",
                state_json={},
                fixture_state=None,
                fixture_input_json={},
                fixture_row_version=8,
                worker_lease_token=None,
                worker_lease_run_id=None,
                worker_lease_worker_id=None,
                worker_lease_attempt_number=None,
                worker_lease_expires_at=None,
                worker_heartbeat_at=None,
                worker_fencing_version=0,
            )
        )
    engine.dispose()

    command.upgrade(_config(url), "head")
    engine = create_engine(url)
    try:
        assert _current_revision(engine) == "20260725_0011"
        columns = {
            row["name"]: row for row in inspect(engine).get_columns("quant_repository_states")
        }
        assert columns["research_memory_contract_version"]["nullable"] is False
        assert "quant-research-memory-v1" in str(
            columns["research_memory_contract_version"]["default"]
        )
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT research_memory_contract_version "
                        "FROM quant_repository_states "
                        "WHERE workspace_id = 'workspace-pre-p17'"
                    )
                )
                == "legacy-pre-p17"
            )
    finally:
        engine.dispose()


def test_latest_irreversible_boundary_refuses_revision_downgrade(tmp_path: Path) -> None:
    path = tmp_path / "research-memory-irreversible.sqlite3"
    url = _database_url(path)
    engine = _upgrade(path, "head")
    engine.dispose()

    with pytest.raises(
        RuntimeError,
        match="Paper Trading history and is irreversible",
    ):
        command.downgrade(_config(url), "20260722_0007")

    engine = create_engine(url)
    try:
        assert _current_revision(engine) == "20260725_0011"
        columns = {
            row["name"]: row for row in inspect(engine).get_columns("quant_repository_states")
        }
        boundary = columns["research_memory_contract_version"]
        assert boundary["nullable"] is False
        assert "quant-research-memory-v1" in str(boundary["default"])
    finally:
        engine.dispose()


def _create_synthetic_legacy_0001(engine: Engine) -> None:
    """Create only the old objects needed to exercise additive compatibility paths."""

    metadata = sa.MetaData()
    sa.Table("workspaces", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "source_connections",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "content_items",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("duplicate_cluster_id", sa.String(36), nullable=True),
    )
    sa.Table("signal_evidence", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "content_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )
    sa.Table("signals", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "claim_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("model_run_id", sa.String(36), nullable=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO content_versions (id, captured_at) "
                "VALUES ('content-legacy', '2026-07-15 09:30:00')"
            )
        )
        connection.execute(text("INSERT INTO signals (id) VALUES ('signal-legacy')"))
        connection.execute(
            text(
                "INSERT INTO claim_versions (id, version_number, model_run_id) VALUES "
                "('claim-deterministic', 1, NULL), "
                "('claim-model', 1, 'model-run'), "
                "('claim-human', 2, NULL)"
            )
        )


def test_synthetic_legacy_0001_runs_additive_migrations_and_backfills(tmp_path: Path) -> None:
    """Synthetic is explicit: no historical production schema artifact exists pre-release."""

    path = tmp_path / "synthetic-legacy-0001.sqlite3"
    url = _database_url(path)
    engine = create_engine(url)
    _create_synthetic_legacy_0001(engine)
    engine.dispose()

    command.stamp(_config(url), "20260715_0001")
    command.upgrade(_config(url), "head")

    engine = create_engine(url)
    try:
        assert _current_revision(engine) == "20260725_0011"
        _assert_critical_head_shape(engine)
        synthetic_columns = {
            table: {row["name"]: row for row in inspect(engine).get_columns(table)}
            for table in ("content_versions", "signals", "source_validation_jobs")
        }
        assert synthetic_columns["content_versions"]["availability"]["default"] is None
        assert synthetic_columns["signals"]["disposition_json"]["default"] is None
        for name in ("state", "attempt", "fencing_version"):
            assert synthetic_columns["source_validation_jobs"][name]["default"] is None
        with engine.connect() as connection:
            content = connection.execute(
                text(
                    "SELECT captured_at, availability, availability_last_checked_at "
                    "FROM content_versions WHERE id = 'content-legacy'"
                )
            ).one()
            assert content.availability == "captured"
            assert content.availability_last_checked_at == content.captured_at
            disposition = connection.scalar(
                text("SELECT disposition_json FROM signals WHERE id = 'signal-legacy'")
            )
            assert json.loads(disposition) == {}
            claims = {
                row.id: (
                    row.confidence_score,
                    row.confidence_policy_version,
                    row.generation_method,
                    row.generator_version,
                    row.suggestion_origin,
                )
                for row in connection.execute(
                    text(
                        "SELECT id, confidence_score, confidence_policy_version, "
                        "generation_method, generator_version, suggestion_origin "
                        "FROM claim_versions"
                    )
                )
            }
        assert claims == {
            "claim-deterministic": (
                0.0,
                "legacy-unreplayable-v0",
                "deterministic",
                "deterministic-research-legacy",
                "deterministic_rule",
            ),
            "claim-model": (
                0.0,
                "legacy-unreplayable-v0",
                "model",
                "model-run-legacy",
                "model",
            ),
            "claim-human": (
                0.0,
                "legacy-unreplayable-v0",
                "human",
                "human-claim-revision-legacy",
                "none",
            ),
        }
    finally:
        engine.dispose()
