"""Opt-in integration checks for the production PostgreSQL RLS contract."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from services.api.app.core.errors import ApiError
from services.api.app.db.models import (
    Base,
    Claim,
    ClaimEvidence,
    ClaimReview,
    ClaimVersion,
    CollectionRun,
    ContentItem,
    ContentVersion,
    DecisionBrief,
    DecisionBriefReadinessReview,
    DecisionBriefVersion,
    Evidence,
    EvidenceReview,
    Investigation,
    InvestigationScopeVersion,
    InvestigationSynthesis,
    InvestigationSynthesisVersion,
    Project,
    RawContentItem,
    ResearchRun,
    SourceConnection,
    SourceValidationJobRecord,
    SynthesisReview,
)
from services.api.app.db.session import set_rls_context
from services.api.app.modules.common import digest, text_digest
from services.api.app.modules.decisions.service import (
    latest_freshness,
    mark_ready,
    render_export_preview,
    revise_brief,
)
from services.api.app.modules.evidence.service import latest_evidence_review, review_evidence
from services.api.app.modules.sources.validation import SourceValidationJobRepository

TEST_DATABASE_ENV = "GLINT_TEST_POSTGRES_URL"
NIL_UUID = "00000000-0000-0000-0000-000000000000"
ROLE_PASSWORD_ENV = {
    "glint_api": "GLINT_TEST_API_PASSWORD",
    "glint_worker": "GLINT_TEST_WORKER_PASSWORD",
}
ROLE_DEFAULT_PASSWORD = {
    "glint_api": "glint_api_dev_password",
    "glint_worker": "glint_worker_dev_password",
}
WORKER_PROTECTED_TABLES = (
    "transfer_consent_records",
    "upload_grants",
    "evidence_reviews",
    "claim_reviews",
    "investigation_syntheses",
    "investigation_synthesis_versions",
    "synthesis_reviews",
    "decision_briefs",
    "decision_brief_versions",
    "decision_brief_readiness_reviews",
    "decision_brief_freshness_records",
    "brief_exports",
    "idempotency_records",
)
WORKER_AUDIT_ALLOWLIST = {
    ("import.finalized", "ImportManifest"),
    ("import.finalization_failed", "ImportFinalizationJob"),
    ("research_run.completed", "ResearchRun"),
    ("source.validation_completed", "SourceValidationJob"),
    ("source.validation_failed", "SourceValidationJob"),
}
API_PIPELINE_IMMUTABLE_TABLES = (
    "collection_runs",
    "import_manifests",
    "import_manifest_content_versions",
    "raw_content_items",
    "content_items",
    "content_versions",
    "signal_evidence",
    "evidence",
)
API_RUN_EVENT_ALLOWLIST = {
    "investigation.started_from_signal",
    "run.queued",
    "run.cancelled",
    "evidence.reviewed",
    "claim.version_reviewed",
}
WORKER_RUN_EVENT_ALLOWLIST = {
    "run.started",
    "task.started",
    "task.completed",
    "evidence.proposed",
    "claim.version_proposed",
    "review.required",
    "run.completed",
}


def _postgres_url() -> str:
    raw = os.getenv(TEST_DATABASE_ENV)
    if not raw:
        pytest.skip(f"{TEST_DATABASE_ENV} is not set; PostgreSQL RLS tests are opt-in")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail(f"{TEST_DATABASE_ENV} must identify a disposable PostgreSQL database")
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def _set_context(connection: Connection, workspace_id: str, principal_id: str) -> None:
    connection.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": workspace_id},
    )
    connection.execute(
        text("SELECT set_config('app.principal_id', :principal_id, true)"),
        {"principal_id": principal_id},
    )


def _become_runtime(connection: Connection) -> None:
    connection.execute(text("SET LOCAL ROLE glint_api"))


def _role_password(role: str) -> str:
    return os.getenv(ROLE_PASSWORD_ENV[role], ROLE_DEFAULT_PASSWORD[role])


def _runtime_url(role: str = "glint_api") -> str:
    return (
        make_url(_postgres_url())
        .set(username=role, password=_role_password(role))
        .render_as_string(hide_password=False)
    )


def _wait_for_confirmed_postgres_lock(
    engine: Engine,
    *,
    waiting_pid: int,
    blocking_pid: int,
    timeout: float = 5.0,
) -> None:
    """Require PostgreSQL itself to confirm the expected lock dependency."""

    deadline = monotonic() + timeout
    last_observation: dict[str, object] | None = None
    while monotonic() < deadline:
        with engine.connect() as observer:
            row = (
                observer.execute(
                    text(
                        "SELECT wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers "
                        "FROM pg_stat_activity WHERE pid = :waiting_pid"
                    ),
                    {"waiting_pid": waiting_pid},
                )
                .mappings()
                .one_or_none()
            )
        if row is not None:
            last_observation = dict(row)
            blockers = {int(value) for value in row["blockers"] or []}
            if row["wait_event_type"] == "Lock" and blocking_pid in blockers:
                return
        sleep(0.02)
    pytest.fail(
        "PostgreSQL did not confirm the expected lock wait: "
        f"waiting_pid={waiting_pid}, blocking_pid={blocking_pid}, "
        f"last_observation={last_observation}"
    )


@dataclass(frozen=True, slots=True)
class SeededTenants:
    workspace_a: str
    workspace_b: str
    principal_a: str
    principal_b: str
    project_a: str
    project_b: str
    watchlist_a: str
    watchlist_b: str
    source_a: str
    source_b: str


@dataclass(frozen=True, slots=True)
class SeededGuardRows:
    signal_id: str
    schedule_id: str
    import_session_id: str
    consent_id: str
    import_job_id: str
    investigation_id: str
    scope_id: str


def _bootstrap_workspace(
    connection: Connection,
    *,
    workspace_id: str,
    principal_id: str,
    project_id: str,
    watchlist_id: str,
    source_id: str,
) -> None:
    _set_context(connection, workspace_id, principal_id)
    connection.execute(
        text(
            "INSERT INTO workspaces "
            "(id, name, status, data_region, retention_policy_version, created_by, "
            "created_at, updated_at, row_version, data_authenticity) "
            "VALUES (:id, :name, 'active', 'local', 'retention-v1', :principal, "
            "now(), now(), 1, 'human_authored')"
        ),
        {"id": workspace_id, "name": f"RLS {workspace_id}", "principal": principal_id},
    )
    connection.execute(
        text(
            "INSERT INTO workspace_members "
            "(id, workspace_id, user_id, role, status, created_at, updated_at, "
            "data_authenticity) "
            "VALUES (:id, :workspace, :principal, 'owner', 'active', now(), now(), "
            "'human_authored')"
        ),
        {
            "id": str(uuid4()),
            "workspace": workspace_id,
            "principal": principal_id,
        },
    )
    connection.execute(
        text(
            "INSERT INTO projects "
            "(id, workspace_id, name, status, created_by, created_at, updated_at, "
            "row_version, data_authenticity) "
            "VALUES (:id, :workspace, 'RLS project', 'active', :principal, now(), "
            "now(), 1, 'human_authored')"
        ),
        {"id": project_id, "workspace": workspace_id, "principal": principal_id},
    )
    connection.execute(
        text(
            "INSERT INTO watchlists "
            "(id, workspace_id, project_id, name, objective, status, rules_version, "
            "rules_json, owner_id, created_at, updated_at, row_version, data_authenticity) "
            "VALUES (:id, :workspace, :project, 'RLS watchlist', 'RLS objective', "
            "'active', 1, '{}'::json, :principal, now(), now(), 1, 'human_authored')"
        ),
        {
            "id": watchlist_id,
            "workspace": workspace_id,
            "project": project_id,
            "principal": principal_id,
        },
    )
    connection.execute(
        text(
            "INSERT INTO source_connections "
            "(id, workspace_id, name, source_kind, runtime, connector_type, "
            "connector_version, status, config_json, freshness_state, health_state, "
            "data_scope, approved_by, created_at, updated_at, row_version, "
            "data_authenticity) VALUES (:id, :workspace, 'RLS source', 'cloud', "
            "'cloud', 'rss', 'rss-v1', 'healthy', '{}'::json, 'current', 'healthy', "
            "'workspace_confidential', :principal, now(), now(), 1, 'human_authored')"
        ),
        {"id": source_id, "workspace": workspace_id, "principal": principal_id},
    )


def _provision_test_roles(connection: Connection) -> None:
    allow_role_changes = os.getenv("GLINT_TEST_ALLOW_ROLE_CREATE") == "1"
    existing = set(
        connection.execute(
            text(
                "SELECT rolname FROM pg_roles "
                "WHERE rolname IN ('glint_app', 'glint_api', 'glint_worker')"
            )
        ).scalars()
    )
    missing = {"glint_app", "glint_api", "glint_worker"} - existing
    if missing and not allow_role_changes:
        pytest.fail(
            "PostgreSQL test roles are absent; role creation is allowed only in an "
            "isolated cluster with GLINT_TEST_ALLOW_ROLE_CREATE=1: "
            f"{sorted(missing)}"
        )
    if allow_role_changes:
        if "glint_app" not in existing:
            connection.execute(
                text(
                    "CREATE ROLE glint_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOBYPASSRLS NOINHERIT"
                )
            )
        else:
            connection.execute(
                text(
                    "ALTER ROLE glint_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOBYPASSRLS NOINHERIT"
                )
            )
        for role in ("glint_api", "glint_worker"):
            password = _role_password(role)
            command = "CREATE" if role not in existing else "ALTER"
            ddl = connection.scalar(
                text(
                    f"SELECT format('{command} ROLE {role} LOGIN PASSWORD %L "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT', "
                    "CAST(:password AS text))"
                ),
                {"password": password},
            )
            connection.execute(text(str(ddl)))
    database_name = connection.scalar(text("SELECT current_database()"))
    escaped_database_name = str(database_name).replace('"', '""')
    connection.execute(
        text(f'GRANT CONNECT ON DATABASE "{escaped_database_name}" TO glint_api, glint_worker')
    )


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    database_url = _postgres_url()
    owner_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with owner_engine.connect() as connection:
        _provision_test_roles(connection)
    owner_engine.dispose()
    config = Config("infra/migrations/alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.dialect.name == "postgresql"
        connection.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def seeded_tenants(postgres_engine: Engine) -> SeededTenants:
    tenants = SeededTenants(*(str(uuid4()) for _ in range(10)))
    with postgres_engine.begin() as connection:
        _become_runtime(connection)
        _bootstrap_workspace(
            connection,
            workspace_id=tenants.workspace_a,
            principal_id=tenants.principal_a,
            project_id=tenants.project_a,
            watchlist_id=tenants.watchlist_a,
            source_id=tenants.source_a,
        )
        _bootstrap_workspace(
            connection,
            workspace_id=tenants.workspace_b,
            principal_id=tenants.principal_b,
            project_id=tenants.project_b,
            watchlist_id=tenants.watchlist_b,
            source_id=tenants.source_b,
        )
    return tenants


@pytest.fixture(scope="session")
def seeded_guard_rows(postgres_engine: Engine, seeded_tenants: SeededTenants) -> SeededGuardRows:
    rows = SeededGuardRows(*(str(uuid4()) for _ in range(7)))
    dimensions = {
        "trigger_rules": ["detector-owned"],
        "detector_policy": {"minimum_mentions": 3},
        "business_impact": {
            "suggested_level": "medium",
            "suggested_explanation": "detector output",
            "suggestion_origin": "deterministic_rule",
            "suggestion_version": "impact-rules-v1",
            "confirmed_level": None,
            "confirmed_by": None,
            "confirmed_at": None,
            "version": 0,
        },
        "urgency": {
            "suggested_level": "monitor",
            "suggested_explanation": "detector output",
            "suggestion_origin": "deterministic_rule",
            "suggestion_version": "urgency-rules-v1",
            "confirmed_level": None,
            "confirmed_by": None,
            "confirmed_at": None,
            "version": 0,
        },
        "priority": {
            "level": None,
            "status": "pending_confirmation",
            "policy_version": "priority-matrix-v1",
        },
    }
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO signals (id, workspace_id, watchlist_id, title, "
                "detector_version, status, window_json, metrics_json, dimensions_json, "
                "disposition_json, explanation, created_at, updated_at, row_version, "
                "data_authenticity) VALUES (:id, :workspace, :watchlist, 'Guard signal', "
                "'guard-detector-v1', 'new', '{}'::json, '{\"mention_count\": 3}'::json, "
                "CAST(:dimensions AS json), '{}'::json, 'guard fixture', now(), now(), 1, "
                "'generated')"
            ),
            {
                "id": rows.signal_id,
                "workspace": seeded_tenants.workspace_a,
                "watchlist": seeded_tenants.watchlist_a,
                "dimensions": json.dumps(dimensions),
            },
        )
        connection.execute(
            text(
                "INSERT INTO collection_schedules (id, workspace_id, "
                "source_connection_id, watchlist_id, query_json, cadence_seconds, "
                "timezone, misfire_policy, catch_up, overlap_policy, next_run_at, enabled, "
                "lease_owner_token, lease_expires_at, heartbeat_at, lease_attempt, "
                "lease_fencing_version, created_at, updated_at, row_version, "
                "data_authenticity) VALUES (:id, :workspace, :source, :watchlist, "
                "'{}'::json, 3600, 'UTC', 'skip', false, 'skip', now(), true, "
                "'worker:fixture', now() + interval '5 minutes', now(), 1, 1, now(), "
                "now(), 1, 'generated')"
            ),
            {
                "id": rows.schedule_id,
                "workspace": seeded_tenants.workspace_a,
                "source": seeded_tenants.source_a,
                "watchlist": seeded_tenants.watchlist_a,
            },
        )
        connection.execute(
            text(
                "INSERT INTO import_sessions (id, workspace_id, source_connection_id, "
                "expected_source_row_version, expected_current_import_manifest_id, "
                "local_manifest_digest, file_digest, expected_upload_digest, "
                "client_file_name, file_size_bytes, media_type, parser_version, "
                "schema_version, selected_scope_json, selected_scope_digest, state, "
                "uploaded_object_key, uploaded_object_digest, terminal_manifest_id, "
                "failure_code, retryable, created_by, created_at, updated_at, row_version, "
                "data_authenticity) VALUES (:id, :workspace, :source, 1, NULL, "
                "'sha256:local', 'sha256:file', 'sha256:upload', 'fixture.json', 100, "
                "'application/json', 'fixture-parser-v1', 'fixture-schema-v1', '{}'::json, "
                "'sha256:scope', 'failed', 'imports/fixture', 'sha256:upload', NULL, "
                "'TEMPORARY_FAILURE', true, :principal, now(), now(), 2, 'human_authored')"
            ),
            {
                "id": rows.import_session_id,
                "workspace": seeded_tenants.workspace_a,
                "source": seeded_tenants.source_a,
                "principal": seeded_tenants.principal_a,
            },
        )
        connection.execute(
            text(
                "INSERT INTO transfer_consent_records (id, workspace_id, "
                "import_session_id, decision, local_manifest_digest, file_digest, "
                "expected_upload_digest, selected_scope_json, selected_scope_digest, "
                "destination_workspace_id, upload_object_scope, model_egress_authorization, "
                "policy_version, actor_id, recorded_at, expires_at, supersedes_id, "
                "data_authenticity) VALUES (:id, :workspace, :session, 'granted', "
                "'sha256:local', 'sha256:file', 'sha256:upload', '{}'::json, "
                "'sha256:scope', :workspace, '{}'::json, 'none', 'transfer-v1', "
                ":principal, now(), now() + interval '1 day', NULL, 'human_authored')"
            ),
            {
                "id": rows.consent_id,
                "workspace": seeded_tenants.workspace_a,
                "session": rows.import_session_id,
                "principal": seeded_tenants.principal_a,
            },
        )
        connection.execute(
            text(
                "INSERT INTO import_finalization_jobs (id, workspace_id, import_session_id, "
                "expected_session_row_version, expected_source_row_version, "
                "expected_current_import_manifest_id, consent_record_id, actor_id, "
                "request_id, idempotency_key, state, attempt, result_manifest_id, "
                "failure_code, retryable, claimed_by, lease_acquired_at, lease_expires_at, "
                "created_at, updated_at, data_authenticity) VALUES (:id, :workspace, "
                ":session, 2, 1, NULL, :consent, :principal, 'fixture-request', "
                ":idempotency_key, 'failed', 2, NULL, 'TEMPORARY_FAILURE', true, "
                "'worker:fixture', now() - interval '10 minutes', "
                "now() - interval '5 minutes', now(), now(), 'generated')"
            ),
            {
                "id": rows.import_job_id,
                "workspace": seeded_tenants.workspace_a,
                "session": rows.import_session_id,
                "consent": rows.consent_id,
                "principal": seeded_tenants.principal_a,
                "idempotency_key": str(uuid4()),
            },
        )
        connection.execute(
            text(
                "INSERT INTO investigations (id, workspace_id, project_id, signal_id, "
                "current_scope_version_id, status, owner_id, current_synthesis_id, "
                "decision_brief_id, created_at, updated_at, row_version, data_authenticity) "
                "VALUES (:id, :workspace, :project, :signal, NULL, 'active', :principal, "
                "NULL, NULL, now(), now(), 1, 'human_authored')"
            ),
            {
                "id": rows.investigation_id,
                "workspace": seeded_tenants.workspace_a,
                "project": seeded_tenants.project_a,
                "signal": rows.signal_id,
                "principal": seeded_tenants.principal_a,
            },
        )
        connection.execute(
            text(
                "INSERT INTO investigation_scope_versions (id, workspace_id, "
                "investigation_id, version_number, decision_question, source_scope_json, "
                "time_range_json, budget_json, stop_conditions, created_by, change_reason, "
                "created_at, data_authenticity) VALUES (:id, :workspace, :investigation, 1, "
                "'Guard question?', '{}'::json, '{}'::json, '{}'::json, '[]'::json, "
                ":principal, 'initial guard scope', now(), 'human_authored')"
            ),
            {
                "id": rows.scope_id,
                "workspace": seeded_tenants.workspace_a,
                "investigation": rows.investigation_id,
                "principal": seeded_tenants.principal_a,
            },
        )
        connection.execute(
            text(
                "UPDATE investigations SET current_scope_version_id = :scope "
                "WHERE id = :investigation"
            ),
            {"scope": rows.scope_id, "investigation": rows.investigation_id},
        )
    return rows


def test_runtime_roles_are_not_migration_owners_or_rls_bypass(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        roles = {
            row["rolname"]: row
            for row in connection.execute(
                text(
                    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolreplication, rolbypassrls, rolinherit FROM pg_roles WHERE "
                    "rolname IN ('glint_app', 'glint_api', 'glint_worker')"
                )
            ).mappings()
        }
        assert set(roles) == {"glint_app", "glint_api", "glint_worker"}
        assert roles["glint_app"]["rolcanlogin"] is False
        for role_name in ("glint_api", "glint_worker"):
            assert roles[role_name]["rolcanlogin"] is True
        for role in roles.values():
            assert role["rolsuper"] is False
            assert role["rolcreatedb"] is False
            assert role["rolcreaterole"] is False
            assert role["rolreplication"] is False
            assert role["rolbypassrls"] is False
            assert role["rolinherit"] is False

        memberships = connection.execute(
            text(
                "SELECT member_role.rolname AS member_role, granted_role.rolname AS "
                "granted_role FROM pg_auth_members membership "
                "JOIN pg_roles member_role ON member_role.oid = membership.member "
                "JOIN pg_roles granted_role ON granted_role.oid = membership.roleid "
                "WHERE member_role.rolname IN ('glint_app', 'glint_api', 'glint_worker')"
            )
        ).all()
        assert memberships == []

        expected_tenant_tables = {
            table.name for table in Base.metadata.sorted_tables if "workspace_id" in table.c
        } | {"workspaces", "workspace_members", "idempotency_records"}
        rows = list(
            connection.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "pg_get_userbyid(c.relowner) AS table_owner, "
                    "count(p.policyname) AS policy_count "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "LEFT JOIN pg_policies p ON p.schemaname = n.nspname "
                    "AND p.tablename = c.relname "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' AND ("
                    "EXISTS (SELECT 1 FROM information_schema.columns col WHERE "
                    "col.table_schema = n.nspname AND col.table_name = c.relname "
                    "AND col.column_name = 'workspace_id') OR "
                    "c.relname IN ('workspaces', 'workspace_members', 'idempotency_records')) "
                    "GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity, c.relowner"
                )
            ).mappings()
        )
        assert {row["relname"] for row in rows} == expected_tenant_tables
        assert all(row["relrowsecurity"] is True for row in rows)
        assert all(row["relforcerowsecurity"] is True for row in rows)
        assert all(int(row["policy_count"]) >= 1 for row in rows)
        assert all(
            row["table_owner"] not in {"glint_app", "glint_api", "glint_worker"} for row in rows
        )

    with postgres_engine.begin() as connection:
        _become_runtime(connection)
        identity = connection.execute(text("SELECT current_user, session_user")).one()
        assert identity.current_user == "glint_api"
        assert identity.session_user != "glint_api"

    for role_name in ("glint_api", "glint_worker"):
        runtime_engine = create_engine(_runtime_url(role_name), pool_pre_ping=True)
        try:
            with runtime_engine.begin() as connection:
                identity = connection.execute(text("SELECT current_user, session_user")).one()
                assert identity.current_user == role_name
                assert identity.session_user == role_name
                with pytest.raises(DBAPIError, match="permission denied to set role"):
                    connection.execute(text("SET ROLE glint_app"))
        finally:
            runtime_engine.dispose()


def test_alembic_uses_migration_owner_url_without_runtime_settings_validation(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    del postgres_engine
    monkeypatch.setenv("GLINT_ENVIRONMENT", "production")
    monkeypatch.setenv("GLINT_DATABASE_URL", _runtime_url())
    monkeypatch.setenv("GLINT_MIGRATION_DATABASE_URL", _postgres_url())
    config = Config("infra/migrations/alembic.ini")
    command.upgrade(config, "head")


def test_session_restores_rls_context_after_service_commit(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    del postgres_engine
    runtime_engine = create_engine(_runtime_url(), pool_pre_ping=True)
    factory = sessionmaker(bind=runtime_engine, expire_on_commit=False)
    try:
        with factory() as db:
            set_rls_context(db, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            before_commit = db.scalar(select(Project).where(Project.id == seeded_tenants.project_a))
            assert before_commit is not None
            db.commit()
            after_commit = db.scalar(select(Project).where(Project.id == seeded_tenants.project_a))
            cross_workspace = db.scalar(
                select(Project).where(Project.id == seeded_tenants.project_b)
            )
            assert after_commit is not None
            assert cross_workspace is None
    finally:
        runtime_engine.dispose()


def test_same_workspace_succeeds_and_cross_workspace_read_is_invisible(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    with postgres_engine.begin() as connection:
        _become_runtime(connection)
        _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM workspaces WHERE id = :id"),
                {"id": seeded_tenants.workspace_a},
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM projects WHERE id = :id"),
                {"id": seeded_tenants.project_a},
            )
            == 1
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM workspace_members "
                    "WHERE workspace_id = :workspace AND user_id = :principal"
                ),
                {
                    "workspace": seeded_tenants.workspace_a,
                    "principal": seeded_tenants.principal_a,
                },
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM workspaces WHERE id = :id"),
                {"id": seeded_tenants.workspace_b},
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM projects WHERE id = :id"),
                {"id": seeded_tenants.project_b},
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM workspace_members WHERE workspace_id = :id"),
                {"id": seeded_tenants.workspace_b},
            )
            == 0
        )


def test_cross_workspace_write_is_rejected(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    with (
        pytest.raises(DBAPIError, match="row-level security"),
        postgres_engine.begin() as connection,
    ):
        _become_runtime(connection)
        _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, workspace_id, name, status, created_by, created_at, "
                "updated_at, row_version, data_authenticity) "
                "VALUES (:id, :foreign_workspace, 'forbidden', 'active', "
                ":principal, now(), now(), 1, 'human_authored')"
            ),
            {
                "id": str(uuid4()),
                "foreign_workspace": seeded_tenants.workspace_b,
                "principal": seeded_tenants.principal_a,
            },
        )


def test_workspace_bootstrap_and_principal_membership_listing(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    workspace_id = str(uuid4())
    principal_id = str(uuid4())
    project_id = str(uuid4())
    watchlist_id = str(uuid4())
    source_id = str(uuid4())
    with postgres_engine.begin() as connection:
        _become_runtime(connection)
        _bootstrap_workspace(
            connection,
            workspace_id=workspace_id,
            principal_id=principal_id,
            project_id=project_id,
            watchlist_id=watchlist_id,
            source_id=source_id,
        )

    with postgres_engine.begin() as connection:
        _become_runtime(connection)
        _set_context(connection, "", seeded_tenants.principal_a)
        memberships = (
            connection.execute(
                text("SELECT workspace_id FROM workspace_members ORDER BY workspace_id")
            )
            .scalars()
            .all()
        )
        assert memberships == [seeded_tenants.workspace_a]
        assert connection.scalar(text("SELECT count(*) FROM workspaces")) == 0

        _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM workspaces WHERE id = :id"),
                {"id": seeded_tenants.workspace_a},
            )
            == 1
        )


def test_idempotency_records_are_workspace_and_principal_scoped(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    record_id = str(uuid4())
    with postgres_engine.begin() as connection:
        _become_runtime(connection)
        _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
        connection.execute(
            text(
                "INSERT INTO idempotency_records "
                "(id, workspace_scope, principal_id, route, idempotency_key, "
                "request_fingerprint, state, owner_token, lease_expires_at, "
                "response_status, response_json, created_at, updated_at) "
                "VALUES (:id, :workspace, :principal, 'POST /v1/projects', :key, "
                "'sha256:test', 'completed', :owner_token, now() + interval '1 minute', "
                "201, CAST(:response AS json), now(), now())"
            ),
            {
                "id": record_id,
                "workspace": seeded_tenants.workspace_a,
                "principal": seeded_tenants.principal_a,
                "key": str(uuid4()),
                "owner_token": str(uuid4()),
                "response": '{"ok": true}',
            },
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM idempotency_records WHERE id = :id"),
                {"id": record_id},
            )
            == 1
        )

        _set_context(connection, seeded_tenants.workspace_b, seeded_tenants.principal_b)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM idempotency_records WHERE id = :id"),
                {"id": record_id},
            )
            == 0
        )

    with (
        pytest.raises(DBAPIError, match="row-level security"),
        postgres_engine.begin() as connection,
    ):
        _become_runtime(connection)
        _set_context(connection, NIL_UUID, seeded_tenants.principal_a)
        connection.execute(
            text(
                "INSERT INTO idempotency_records "
                "(id, workspace_scope, principal_id, route, idempotency_key, "
                "request_fingerprint, state, owner_token, lease_expires_at, "
                "response_status, response_json, created_at, updated_at) "
                "VALUES (:id, :foreign_workspace, :principal, 'POST /v1/projects', "
                ":key, 'sha256:test', 'completed', :owner_token, "
                "now() + interval '1 minute', 201, CAST(:response AS json), now(), now())"
            ),
            {
                "id": str(uuid4()),
                "foreign_workspace": seeded_tenants.workspace_a,
                "principal": seeded_tenants.principal_a,
                "key": str(uuid4()),
                "owner_token": str(uuid4()),
                "response": '{"ok": true}',
            },
        )

    root_record_id = str(uuid4())
    with postgres_engine.begin() as connection:
        _become_runtime(connection)
        _set_context(connection, NIL_UUID, seeded_tenants.principal_a)
        connection.execute(
            text(
                "INSERT INTO idempotency_records "
                "(id, workspace_scope, principal_id, route, idempotency_key, "
                "request_fingerprint, state, owner_token, lease_expires_at, "
                "response_status, response_json, created_at, updated_at) "
                "VALUES (:id, :workspace, :principal, 'POST /v1/workspaces', :key, "
                "'sha256:test', 'completed', :owner_token, now() + interval '1 minute', "
                "201, CAST(:response AS json), now(), now())"
            ),
            {
                "id": root_record_id,
                "workspace": NIL_UUID,
                "principal": seeded_tenants.principal_a,
                "key": str(uuid4()),
                "owner_token": str(uuid4()),
                "response": '{"ok": true}',
            },
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM idempotency_records WHERE id = :id"),
                {"id": root_record_id},
            )
            == 1
        )


def test_runtime_cannot_mutate_or_delete_append_only_audit_rows(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    audit_id = str(uuid4())
    with postgres_engine.begin() as connection:
        _become_runtime(connection)
        _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
        connection.execute(
            text(
                "INSERT INTO audit_logs "
                "(id, workspace_id, actor_id, action, target_type, target_id, "
                "request_id, details_json, occurred_at, data_authenticity) "
                "VALUES (:id, :workspace, :principal, 'rls.test', 'Workspace', "
                ":workspace, :request_id, '{}'::json, now(), 'human_authored')"
            ),
            {
                "id": audit_id,
                "workspace": seeded_tenants.workspace_a,
                "principal": seeded_tenants.principal_a,
                "request_id": str(uuid4()),
            },
        )

    with (
        pytest.raises(DBAPIError, match="permission denied"),
        postgres_engine.begin() as connection,
    ):
        _become_runtime(connection)
        _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
        connection.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"),
            {"id": audit_id},
        )

    with (
        pytest.raises(DBAPIError, match="permission denied"),
        postgres_engine.begin() as connection,
    ):
        _become_runtime(connection)
        _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
        connection.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": audit_id})


def test_worker_privilege_catalog_is_frozen_to_pipeline_writes(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT has_schema_privilege('glint_worker', 'public', 'USAGE')")
        )
        assert not connection.scalar(
            text("SELECT has_schema_privilege('glint_worker', 'public', 'CREATE')")
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege('glint_app', 'projects', 'SELECT')")
        )
        for table_name in WORKER_PROTECTED_TABLES:
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege('glint_worker', :table_name, :privilege)"),
                    {"table_name": table_name, "privilege": privilege},
                ), f"glint_worker unexpectedly has {privilege} on {table_name}"

        assert connection.scalar(
            text("SELECT has_table_privilege('glint_worker', 'audit_logs', 'INSERT')")
        )
        assert connection.scalar(
            text("SELECT has_table_privilege('glint_worker', 'evidence_reviews', 'SELECT')")
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege('glint_worker', 'audit_logs', 'UPDATE')")
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege('glint_worker', 'audit_logs', 'DELETE')")
        )
        assert connection.scalar(
            text(
                "SELECT has_column_privilege("
                "'glint_worker', 'source_connections', 'status', 'UPDATE')"
            )
        )
        for forbidden_column in ("approved_by", "credential_ref", "config_json"):
            assert not connection.scalar(
                text(
                    "SELECT has_column_privilege("
                    "'glint_worker', 'source_connections', :column_name, 'UPDATE')"
                ),
                {"column_name": forbidden_column},
            )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.role_usage_grants "
                    "WHERE grantee = 'glint_worker' AND object_type = 'SEQUENCE'"
                )
            )
            == 0
        )

        audit_policies = {
            row["policyname"]: row
            for row in connection.execute(
                text(
                    "SELECT policyname, cmd, roles, with_check FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename = 'audit_logs'"
                )
            ).mappings()
        }
        assert set(audit_policies) == {
            "audit_logs_api_workspace_scope",
            "audit_logs_worker_operational_insert",
        }
        assert audit_policies["audit_logs_api_workspace_scope"]["roles"] == ["glint_api"]
        worker_policy = audit_policies["audit_logs_worker_operational_insert"]
        assert worker_policy["cmd"] == "INSERT"
        assert worker_policy["roles"] == ["glint_worker"]
        policy_check = str(worker_policy["with_check"])
        for action, target_type in WORKER_AUDIT_ALLOWLIST:
            assert action in policy_check
            assert target_type in policy_check


def test_api_privilege_catalog_cannot_forge_pipeline_outputs(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:
        for table_name in API_PIPELINE_IMMUTABLE_TABLES:
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege('glint_api', :table_name, :privilege)"),
                    {"table_name": table_name, "privilege": privilege},
                ), f"glint_api unexpectedly has {privilege} on {table_name}"

        for table_name in ("signals", "claims"):
            for privilege in ("INSERT", "DELETE"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege('glint_api', :table_name, :privilege)"),
                    {"table_name": table_name, "privilege": privilege},
                )
        assert connection.scalar(
            text("SELECT has_column_privilege('glint_api', 'signals', 'status', 'UPDATE')")
        )
        for column_name in ("title", "metrics_json", "detector_version"):
            assert not connection.scalar(
                text("SELECT has_column_privilege('glint_api', 'signals', :column_name, 'UPDATE')"),
                {"column_name": column_name},
            )
        assert not connection.scalar(
            text(
                "SELECT has_column_privilege("
                "'glint_api', 'source_connections', 'current_import_manifest_id', 'UPDATE')"
            )
        )
        assert not connection.scalar(
            text(
                "SELECT has_column_privilege("
                "'glint_api', 'research_runs', 'worker_attempt_id', 'UPDATE')"
            )
        )
        assert connection.scalar(
            text("SELECT has_table_privilege('glint_api', 'run_events', 'INSERT')")
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege('glint_api', 'run_events', 'UPDATE')")
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege('glint_api', 'run_events', 'DELETE')")
        )
        assert connection.scalar(
            text("SELECT has_table_privilege('glint_api', 'source_validation_jobs', 'INSERT')")
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege('glint_api', 'source_validation_jobs', 'UPDATE')")
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.role_usage_grants "
                    "WHERE grantee = 'glint_api' AND object_type = 'SEQUENCE'"
                )
            )
            == 0
        )

        run_event_policies = {
            row["policyname"]: row
            for row in connection.execute(
                text(
                    "SELECT policyname, cmd, roles, with_check FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename = 'run_events'"
                )
            ).mappings()
        }
        assert set(run_event_policies) == {
            "run_events_api_select",
            "run_events_api_insert",
            "run_events_worker_insert",
            "run_events_worker_workspace_scope",
        }
        api_insert = run_event_policies["run_events_api_insert"]
        assert api_insert["cmd"] == "INSERT"
        assert api_insert["roles"] == ["glint_api"]
        api_check = str(api_insert["with_check"])
        for event_type in API_RUN_EVENT_ALLOWLIST:
            assert event_type in api_check
        assert "task.started" not in api_check
        assert "task.completed" not in api_check
        assert "evidence.proposed" not in api_check
        worker_insert = run_event_policies["run_events_worker_insert"]
        assert worker_insert["cmd"] == "INSERT"
        assert worker_insert["roles"] == ["glint_worker"]
        worker_check = str(worker_insert["with_check"])
        for event_type in WORKER_RUN_EVENT_ALLOWLIST:
            assert event_type in worker_check
        for event_type in API_RUN_EVENT_ALLOWLIST:
            assert event_type not in worker_check

        guard_triggers = set(
            connection.execute(
                text(
                    "SELECT trigger_name FROM information_schema.triggers WHERE "
                    "trigger_schema = 'public' AND trigger_name LIKE 'glint_guard_api_%'"
                )
            ).scalars()
        )
        assert guard_triggers == {
            "glint_guard_api_import_retry",
            "glint_guard_api_import_retry_insert",
            "glint_guard_api_research_run_insert",
            "glint_guard_api_research_run_state",
            "glint_guard_api_schedule_lease",
            "glint_guard_api_schedule_lease_insert",
            "glint_guard_api_signal_dimensions",
            "glint_guard_api_source_validation_insert",
        }


def test_api_real_login_guards_worker_leases_and_detector_output(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
    seeded_guard_rows: SeededGuardRows,
) -> None:
    del postgres_engine
    api_engine = create_engine(_runtime_url("glint_api"), pool_pre_ping=True)
    try:
        with (
            pytest.raises(DBAPIError, match="cannot mutate detector-owned Signal dimensions"),
            api_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "UPDATE signals SET dimensions_json = jsonb_set(dimensions_json::jsonb, "
                    "'{business_impact,suggested_level}', '\"critical\"'::jsonb)::json "
                    "WHERE id = :id"
                ),
                {"id": seeded_guard_rows.signal_id},
            )

        with (
            pytest.raises(DBAPIError, match="may clear but not acquire a collection lease"),
            api_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "UPDATE collection_schedules SET lease_owner_token = 'api:forged' "
                    "WHERE id = :id"
                ),
                {"id": seeded_guard_rows.schedule_id},
            )

        with (
            pytest.raises(DBAPIError, match="may only clear a failed import lease during retry"),
            api_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "UPDATE import_finalization_jobs SET state = 'claimed', "
                    "claimed_by = 'api:forged', lease_expires_at = now() + interval '5 minutes' "
                    "WHERE id = :id"
                ),
                {"id": seeded_guard_rows.import_job_id},
            )

        with (
            pytest.raises(DBAPIError, match="may only enqueue an unclaimed source validation"),
            api_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "INSERT INTO source_validation_jobs (id, workspace_id, "
                    "source_connection_id, command, state, expected_source_row_version, "
                    "actor_id, request_id, idempotency_key, attempt, lease_owner_token, "
                    "lease_expires_at, heartbeat_at, fencing_version, result_source_status, "
                    "failure_code, failure_reason, created_at, updated_at, data_authenticity) "
                    "VALUES (:id, :workspace, :source, 'health_check', 'completed', 1, "
                    ":principal, 'api-forgery', :idempotency_key, 1, 'api:forged', now(), "
                    "now(), 1, 'healthy', NULL, NULL, now(), now(), 'generated')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_a,
                    "source": seeded_tenants.source_a,
                    "principal": seeded_tenants.principal_a,
                    "idempotency_key": str(uuid4()),
                },
            )

        with api_engine.begin() as connection:
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "UPDATE signals SET status = 'triaged', row_version = row_version + 1, "
                    "dimensions_json = jsonb_set(jsonb_set(dimensions_json::jsonb, "
                    "'{business_impact,confirmed_level}', '\"high\"'::jsonb), "
                    '\'{priority}\', \'{"level":"high","status":"confirmed",'
                    '"policy_version":"priority-matrix-v1"}\'::jsonb)::json '
                    "WHERE id = :signal_id"
                ),
                {"signal_id": seeded_guard_rows.signal_id},
            )
            connection.execute(
                text(
                    "UPDATE collection_schedules SET enabled = false, "
                    "lease_owner_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL, "
                    "row_version = row_version + 1 WHERE id = :schedule_id"
                ),
                {"schedule_id": seeded_guard_rows.schedule_id},
            )
            connection.execute(
                text(
                    "UPDATE import_finalization_jobs SET expected_session_row_version = 3, "
                    "state = 'queued', attempt = attempt + 1, failure_code = NULL, "
                    "retryable = false, claimed_by = NULL, lease_acquired_at = NULL, "
                    "lease_expires_at = NULL, updated_at = now() WHERE id = :job_id"
                ),
                {"job_id": seeded_guard_rows.import_job_id},
            )
            signal_dimensions = connection.scalar(
                text("SELECT dimensions_json FROM signals WHERE id = :id"),
                {"id": seeded_guard_rows.signal_id},
            )
            assert signal_dimensions["business_impact"]["suggested_level"] == "medium"
            assert signal_dimensions["business_impact"]["confirmed_level"] == "high"
            assert signal_dimensions["priority"]["status"] == "confirmed"
            assert connection.execute(
                text(
                    "SELECT enabled, lease_owner_token, lease_expires_at, heartbeat_at "
                    "FROM collection_schedules WHERE id = :id"
                ),
                {"id": seeded_guard_rows.schedule_id},
            ).one() == (False, None, None, None)
            assert connection.execute(
                text(
                    "SELECT state, attempt, failure_code, retryable, claimed_by, "
                    "lease_acquired_at, lease_expires_at FROM import_finalization_jobs "
                    "WHERE id = :id"
                ),
                {"id": seeded_guard_rows.import_job_id},
            ).one() == ("queued", 3, None, False, None, None, None)
    finally:
        api_engine.dispose()


def test_api_real_login_can_create_queued_research_run_and_human_event(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
    seeded_guard_rows: SeededGuardRows,
) -> None:
    del postgres_engine
    api_engine = create_engine(_runtime_url("glint_api"), pool_pre_ping=True)
    run_id = str(uuid4())
    try:
        with (
            pytest.raises(DBAPIError, match="only create an unclaimed queued Research Run"),
            api_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "INSERT INTO research_runs (id, workspace_id, investigation_id, "
                    "investigation_scope_version_id, state, graph_version, "
                    "run_input_manifest_json, run_input_manifest_digest, budget_json, "
                    "used_cost, attempt_number, initiated_by, trace_id, latest_sequence, "
                    "worker_claimed_by, worker_attempt_id, worker_lease_expires_at, "
                    "worker_heartbeat_at, worker_fencing_version, created_at, updated_at, "
                    "row_version, data_authenticity) VALUES (:id, :workspace, "
                    ":investigation, :scope, 'running', 'guard-v1', '{}'::json, "
                    "'sha256:forged', '{}'::json, 1, 1, :principal, 'guard-forged', 0, "
                    "'api:forged', 'api-attempt', now() + interval '5 minutes', now(), 1, "
                    "now(), now(), 1, 'generated')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_a,
                    "investigation": seeded_guard_rows.investigation_id,
                    "scope": seeded_guard_rows.scope_id,
                    "principal": seeded_tenants.principal_a,
                },
            )

        with api_engine.begin() as connection:
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "INSERT INTO research_runs (id, workspace_id, investigation_id, "
                    "investigation_scope_version_id, state, graph_version, "
                    "run_input_manifest_json, run_input_manifest_digest, budget_json, "
                    "used_cost, attempt_number, initiated_by, trace_id, latest_sequence, "
                    "worker_claimed_by, worker_attempt_id, worker_lease_expires_at, "
                    "worker_heartbeat_at, worker_fencing_version, created_at, updated_at, "
                    "row_version, data_authenticity) VALUES (:id, :workspace, "
                    ":investigation, :scope, 'queued', 'guard-v1', '{}'::json, "
                    "'sha256:manifest', '{}'::json, 0, 1, :principal, 'guard-positive', 0, "
                    "NULL, NULL, NULL, NULL, 0, now(), now(), 1, 'human_authored')"
                ),
                {
                    "id": run_id,
                    "workspace": seeded_tenants.workspace_a,
                    "investigation": seeded_guard_rows.investigation_id,
                    "scope": seeded_guard_rows.scope_id,
                    "principal": seeded_tenants.principal_a,
                },
            )
            connection.execute(
                text("UPDATE research_runs SET latest_sequence = 1 WHERE id = :id"),
                {"id": run_id},
            )
            connection.execute(
                text(
                    "INSERT INTO run_events (id, workspace_id, investigation_id, "
                    "research_run_id, sequence, event_id, idempotency_key, type, "
                    "payload_json, trace_id, occurred_at, data_authenticity) VALUES "
                    "(:id, :workspace, :investigation, :run, 1, :event_id, :stable_key, "
                    "'run.queued', '{}'::json, 'guard-positive', now(), 'human_authored')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_a,
                    "investigation": seeded_guard_rows.investigation_id,
                    "run": run_id,
                    "event_id": str(uuid4()),
                    "stable_key": f"sha256:{uuid4().hex}",
                },
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM run_events WHERE research_run_id = :run "
                        "AND type = 'run.queued'"
                    ),
                    {"run": run_id},
                )
                == 1
            )

        for forged_state in ("completed", "failed"):
            with (
                pytest.raises(DBAPIError, match="may only cancel an unfinished Research Run"),
                api_engine.begin() as connection,
            ):
                _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
                connection.execute(
                    text("UPDATE research_runs SET state = :state WHERE id = :run"),
                    {"state": forged_state, "run": run_id},
                )

        with api_engine.begin() as connection:
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            cancelled = connection.execute(
                text(
                    "UPDATE research_runs SET state = 'cancelled', "
                    "row_version = row_version + 1 WHERE id = :run RETURNING state"
                ),
                {"run": run_id},
            ).scalar()
            assert cancelled == "cancelled"

        with (
            pytest.raises(DBAPIError, match="row-level security"),
            api_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "INSERT INTO run_events (id, workspace_id, investigation_id, "
                    "research_run_id, sequence, event_id, idempotency_key, type, "
                    "payload_json, trace_id, occurred_at, data_authenticity) VALUES "
                    "(:id, :workspace, :investigation, :run, 2, :event_id, :stable_key, "
                    "'task.started', '{}'::json, 'guard-forged', now(), 'generated')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_a,
                    "investigation": seeded_guard_rows.investigation_id,
                    "run": run_id,
                    "event_id": str(uuid4()),
                    "stable_key": f"sha256:{uuid4().hex}",
                },
            )
    finally:
        api_engine.dispose()


def test_worker_real_login_cannot_forge_human_review_event(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
    seeded_guard_rows: SeededGuardRows,
) -> None:
    run_id = str(uuid4())
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO research_runs (id, workspace_id, investigation_id, "
                "investigation_scope_version_id, state, graph_version, "
                "run_input_manifest_json, run_input_manifest_digest, budget_json, "
                "used_cost, attempt_number, initiated_by, trace_id, latest_sequence, "
                "worker_claimed_by, worker_attempt_id, worker_lease_expires_at, "
                "worker_heartbeat_at, worker_fencing_version, created_at, updated_at, "
                "row_version, data_authenticity) VALUES (:id, :workspace, :investigation, "
                ":scope, 'running', 'guard-v1', '{}'::json, 'sha256:worker-event', "
                "'{}'::json, 0, 1, :principal, 'worker-event-guard', 0, NULL, NULL, "
                "NULL, NULL, 0, now(), now(), 1, 'generated')"
            ),
            {
                "id": run_id,
                "workspace": seeded_tenants.workspace_a,
                "investigation": seeded_guard_rows.investigation_id,
                "scope": seeded_guard_rows.scope_id,
                "principal": seeded_tenants.principal_a,
            },
        )

    worker_engine = create_engine(_runtime_url("glint_worker"), pool_pre_ping=True)
    try:
        with (
            pytest.raises(DBAPIError, match="row-level security"),
            worker_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, "glint-worker-test")
            connection.execute(
                text(
                    "INSERT INTO run_events (id, workspace_id, investigation_id, "
                    "research_run_id, sequence, event_id, idempotency_key, type, "
                    "payload_json, trace_id, occurred_at, data_authenticity) VALUES "
                    "(:id, :workspace, :investigation, :run, 1, :event_id, :stable_key, "
                    "'evidence.reviewed', '{}'::json, 'worker-event-forgery', now(), "
                    "'generated')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_a,
                    "investigation": seeded_guard_rows.investigation_id,
                    "run": run_id,
                    "event_id": str(uuid4()),
                    "stable_key": f"sha256:{uuid4().hex}",
                },
            )
    finally:
        worker_engine.dispose()


def test_api_real_login_pipeline_mutations_are_denied(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    del postgres_engine
    api_engine = create_engine(_runtime_url("glint_api"), pool_pre_ping=True)
    forbidden_statements = (
        "INSERT INTO collection_runs DEFAULT VALUES",
        "INSERT INTO signals DEFAULT VALUES",
        "INSERT INTO evidence DEFAULT VALUES",
        "UPDATE signals SET title = title",
        "UPDATE content_versions SET availability = availability",
        "UPDATE research_runs SET worker_attempt_id = 'forged'",
        "UPDATE source_connections SET current_import_manifest_id = NULL",
        "UPDATE source_validation_jobs SET state = 'completed'",
        "DELETE FROM projects",
    )
    try:
        for statement in forbidden_statements:
            with (
                pytest.raises(DBAPIError, match="permission denied"),
                api_engine.begin() as connection,
            ):
                _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
                connection.execute(text(statement))

        with api_engine.begin() as connection:
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            updated = connection.execute(
                text(
                    "UPDATE source_connections SET status = status "
                    "WHERE id = :source_id RETURNING id"
                ),
                {"source_id": seeded_tenants.source_a},
            ).scalar()
            assert updated == seeded_tenants.source_a

        with (
            pytest.raises(DBAPIError, match="row-level security"),
            api_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            connection.execute(
                text(
                    "INSERT INTO run_events (id, workspace_id, investigation_id, "
                    "research_run_id, sequence, event_id, idempotency_key, type, "
                    "payload_json, trace_id, occurred_at, data_authenticity) VALUES "
                    "(:id, :workspace, :investigation_id, :run_id, 1, :event_id, "
                    ":stable_key, 'task.started', '{}'::json, 'api-forgery-test', now(), "
                    "'generated')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_a,
                    "investigation_id": str(uuid4()),
                    "run_id": str(uuid4()),
                    "event_id": str(uuid4()),
                    "stable_key": f"sha256:{uuid4().hex}",
                },
            )
    finally:
        api_engine.dispose()


def test_worker_real_login_is_workspace_scoped_and_can_write_pipeline_signal(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    del postgres_engine
    worker_engine = create_engine(_runtime_url("glint_worker"), pool_pre_ping=True)
    signal_id = str(uuid4())
    try:
        with worker_engine.begin() as connection:
            _set_context(connection, seeded_tenants.workspace_a, "glint-worker-test")
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM source_connections WHERE id = :source_id"),
                    {"source_id": seeded_tenants.source_a},
                )
                == 1
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM source_connections WHERE id = :source_id"),
                    {"source_id": seeded_tenants.source_b},
                )
                == 0
            )
            connection.execute(
                text(
                    "INSERT INTO signals (id, workspace_id, watchlist_id, title, "
                    "detector_version, status, window_json, metrics_json, dimensions_json, "
                    "disposition_json, explanation, created_at, updated_at, row_version, "
                    "data_authenticity) VALUES (:id, :workspace, :watchlist, 'Worker signal', "
                    "'rls-test-v1', 'new', '{}'::json, '{}'::json, '{}'::json, '{}'::json, "
                    "'least privilege positive control', now(), now(), 1, 'generated')"
                ),
                {
                    "id": signal_id,
                    "workspace": seeded_tenants.workspace_a,
                    "watchlist": seeded_tenants.watchlist_a,
                },
            )

        with (
            pytest.raises(DBAPIError, match="row-level security"),
            worker_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, "glint-worker-test")
            connection.execute(
                text(
                    "INSERT INTO signals (id, workspace_id, watchlist_id, title, "
                    "detector_version, status, window_json, metrics_json, dimensions_json, "
                    "disposition_json, explanation, created_at, updated_at, row_version, "
                    "data_authenticity) VALUES (:id, :workspace, :watchlist, 'Forbidden', "
                    "'rls-test-v1', 'new', '{}'::json, '{}'::json, '{}'::json, '{}'::json, "
                    "'cross workspace', now(), now(), 1, 'generated')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_b,
                    "watchlist": seeded_tenants.watchlist_b,
                },
            )
    finally:
        worker_engine.dispose()


def test_worker_real_login_cannot_write_human_authority_tables(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    del postgres_engine
    worker_engine = create_engine(_runtime_url("glint_worker"), pool_pre_ping=True)
    try:
        for table_name in WORKER_PROTECTED_TABLES:
            with (
                pytest.raises(DBAPIError, match="permission denied"),
                worker_engine.begin() as connection,
            ):
                _set_context(connection, seeded_tenants.workspace_a, "glint-worker-test")
                connection.execute(text(f'INSERT INTO "{table_name}" DEFAULT VALUES'))
    finally:
        worker_engine.dispose()


def test_worker_audit_insert_is_exactly_allowlisted_and_append_only(
    postgres_engine: Engine, seeded_tenants: SeededTenants
) -> None:
    worker_engine = create_engine(_runtime_url("glint_worker"), pool_pre_ping=True)
    audit_ids: list[str] = []
    try:
        with worker_engine.begin() as connection:
            _set_context(connection, seeded_tenants.workspace_a, "glint-worker-test")
            for action, target_type in sorted(WORKER_AUDIT_ALLOWLIST):
                audit_id = str(uuid4())
                audit_ids.append(audit_id)
                connection.execute(
                    text(
                        "INSERT INTO audit_logs (id, workspace_id, actor_id, action, "
                        "target_type, target_id, request_id, details_json, occurred_at, "
                        "data_authenticity) VALUES (:id, :workspace, :actor, :action, "
                        ":target_type, :target_id, :request_id, '{}'::json, now(), 'generated')"
                    ),
                    {
                        "id": audit_id,
                        "workspace": seeded_tenants.workspace_a,
                        "actor": "glint-worker-test",
                        "action": action,
                        "target_type": target_type,
                        "target_id": str(uuid4()),
                        "request_id": str(uuid4()),
                    },
                )

        with postgres_engine.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM audit_logs WHERE id = ANY(:audit_ids)"),
                {"audit_ids": audit_ids},
            ) == len(WORKER_AUDIT_ALLOWLIST)

        with (
            pytest.raises(DBAPIError, match="row-level security"),
            worker_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, "glint-worker-test")
            connection.execute(
                text(
                    "INSERT INTO audit_logs (id, workspace_id, actor_id, action, "
                    "target_type, target_id, request_id, details_json, occurred_at, "
                    "data_authenticity) VALUES (:id, :workspace, 'worker', "
                    "'worker.arbitrary', 'Workspace', :workspace, :request_id, "
                    "'{}'::json, now(), 'generated')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_a,
                    "request_id": str(uuid4()),
                },
            )

        with (
            pytest.raises(DBAPIError, match="row-level security"),
            worker_engine.begin() as connection,
        ):
            _set_context(connection, seeded_tenants.workspace_a, "glint-worker-test")
            connection.execute(
                text(
                    "INSERT INTO audit_logs (id, workspace_id, actor_id, action, "
                    "target_type, target_id, request_id, details_json, occurred_at, "
                    "data_authenticity) VALUES (:id, :workspace, 'worker', "
                    "'research_run.completed', 'ResearchRun', :target_id, :request_id, "
                    "'{}'::json, now(), 'generated')"
                ),
                {
                    "id": str(uuid4()),
                    "workspace": seeded_tenants.workspace_b,
                    "target_id": str(uuid4()),
                    "request_id": str(uuid4()),
                },
            )

        for statement in (
            "UPDATE audit_logs SET action = 'tampered' WHERE id = :audit_id",
            "DELETE FROM audit_logs WHERE id = :audit_id",
        ):
            with (
                pytest.raises(DBAPIError, match="permission denied"),
                worker_engine.begin() as connection,
            ):
                _set_context(connection, seeded_tenants.workspace_a, "glint-worker-test")
                connection.execute(text(statement), {"audit_id": audit_ids[0]})
    finally:
        worker_engine.dispose()


def _seed_decision_brief_lock_fixture(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
    seeded_guard_rows: SeededGuardRows,
) -> tuple[DecisionBrief, dict[str, object]]:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as db:
        investigation = Investigation(
            workspace_id=seeded_tenants.workspace_a,
            project_id=seeded_tenants.project_a,
            signal_id=seeded_guard_rows.signal_id,
            status="reviewing",
            owner_id=seeded_tenants.principal_a,
            data_authenticity="human_authored",
        )
        db.add(investigation)
        db.flush()
        synthesis = InvestigationSynthesis(
            workspace_id=seeded_tenants.workspace_a,
            investigation_id=investigation.id,
            data_authenticity="human_authored",
        )
        db.add(synthesis)
        db.flush()
        synthesis_version = InvestigationSynthesisVersion(
            workspace_id=seeded_tenants.workspace_a,
            synthesis_id=synthesis.id,
            version_number=1,
            verified_claim_version_snapshot_json=[],
            claim_review_snapshot_json=[],
            generation_method="deterministic",
            generator_version="decision-lock-test-v1",
            model_prompt_refs_json=[],
            executive_summary="Pinned summary for command locking.",
            business_implications=["Serialize exact-version commands."],
            limitations=["Concurrency fixture."],
            provenance_digest="sha256:decision-lock-fixture",
            created_by=seeded_tenants.principal_a,
            data_authenticity="human_authored",
        )
        db.add(synthesis_version)
        db.flush()
        synthesis_review = SynthesisReview(
            workspace_id=seeded_tenants.workspace_a,
            synthesis_version_id=synthesis_version.id,
            decision="verify",
            reviewer_id=seeded_tenants.principal_a,
            reason="Concurrency fixture synthesis review.",
            policy_version="synthesis-review-v1",
            data_authenticity="human_authored",
        )
        db.add(synthesis_review)
        db.flush()
        brief = DecisionBrief(
            workspace_id=seeded_tenants.workspace_a,
            investigation_id=investigation.id,
            status="draft",
            owner_id=seeded_tenants.principal_a,
            data_authenticity="human_authored",
        )
        db.add(brief)
        db.flush()
        document: dict[str, object] = {
            "schema_version": "decision-brief-blocks-v1",
            "blocks": [
                {
                    "id": "synthesis-1",
                    "type": "synthesis",
                    "body": synthesis_version.executive_summary,
                    "synthesis_version_id": synthesis_version.id,
                    "generation_method": "deterministic",
                    "generator_version": synthesis_version.generator_version,
                    "model_prompt_refs": [],
                },
                {
                    "id": "judgment-1",
                    "type": "pm_judgment",
                    "body": "PM judgment pending",
                    "actor_id": seeded_tenants.principal_a,
                },
                {
                    "id": "recommendation-1",
                    "type": "recommendation",
                    "body": "Recommendation pending",
                    "recommendation_status": "proposed",
                },
            ],
            "no_counter_evidence_search": None,
        }
        snapshot = {
            "synthesis_version_id": synthesis_version.id,
            "synthesis_review_id": synthesis_review.id,
            "claim_version_ids": [],
            "claim_review_ids": [],
            "claim_evidence_ids": [],
            "evidence_review_ids": [],
            "evidence_ids": [],
            "content_version_ids": [],
        }
        brief_version = DecisionBriefVersion(
            workspace_id=seeded_tenants.workspace_a,
            decision_brief_id=brief.id,
            version_number=1,
            synthesis_version_id=synthesis_version.id,
            synthesis_review_id=synthesis_review.id,
            block_document=document,
            reference_snapshot_json=snapshot,
            template_version="decision-brief-v1",
            human_edit_digest=digest(document),
            created_by=seeded_tenants.principal_a,
            data_authenticity="human_authored",
        )
        db.add(brief_version)
        db.flush()
        synthesis.current_version_id = synthesis_version.id
        investigation.current_synthesis_id = synthesis.id
        investigation.decision_brief_id = brief.id
        brief.current_version_id = brief_version.id
        db.commit()
        stale = DecisionBrief(
            id=brief.id,
            workspace_id=brief.workspace_id,
            investigation_id=brief.investigation_id,
            current_version_id=brief_version.id,
            status="draft",
            owner_id=brief.owner_id,
            row_version=1,
            data_authenticity=brief.data_authenticity,
        )
    return stale, document


@pytest.mark.parametrize("command_name", ["revise", "mark_ready"])
def test_decision_brief_commands_lock_before_version_checks(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
    seeded_guard_rows: SeededGuardRows,
    command_name: str,
) -> None:
    stale, document = _seed_decision_brief_lock_fixture(
        postgres_engine, seeded_tenants, seeded_guard_rows
    )
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    waiting_pids: Queue[int] = Queue()

    def invoke_stale_command() -> ApiError | None:
        with factory() as db:
            waiting_pids.put(int(db.scalar(text("SELECT pg_backend_pid()"))))
            try:
                if command_name == "revise":
                    revise_brief(
                        db,
                        brief=stale,
                        actor_id=stale.owner_id,
                        block_document=document,
                        expected_row_version=1,
                        human_edit_digest=digest(document),
                        request_id=str(uuid4()),
                    )
                else:
                    mark_ready(
                        db,
                        brief=stale,
                        actor_id=stale.owner_id,
                        payload={
                            "decision_brief_version_id": stale.current_version_id,
                            "expected_row_version": 1,
                            "decision": "mark_decision_ready",
                            "reason": "Stale concurrent readiness command.",
                            "policy_version": "decision-readiness-v1",
                            "checklist_digest": f"sha256:{'0' * 64}",
                        },
                        request_id=str(uuid4()),
                    )
            except ApiError as error:
                return error
        return None

    with factory() as locker:
        locked = locker.scalar(
            select(DecisionBrief).where(DecisionBrief.id == stale.id).with_for_update()
        )
        assert locked is not None
        blocking_pid = int(locker.scalar(text("SELECT pg_backend_pid()")))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(invoke_stale_command)
            waiting_pid = waiting_pids.get(timeout=5)
            _wait_for_confirmed_postgres_lock(
                postgres_engine,
                waiting_pid=waiting_pid,
                blocking_pid=blocking_pid,
            )
            locked.row_version = 2
            locker.commit()
            error = future.result(timeout=5)

    assert isinstance(error, ApiError)
    assert error.status_code == 412
    assert error.code == "VERSION_CONFLICT"
    assert error.details == {"resource_id": stale.id, "current_row_version": 2}
    with factory() as db:
        current = db.get(DecisionBrief, stale.id)
        versions = db.scalars(
            select(DecisionBriefVersion).where(DecisionBriefVersion.decision_brief_id == stale.id)
        ).all()
        assert current is not None
        assert current.row_version == 2
        assert current.current_version_id == stale.current_version_id
        assert current.status == "draft"
        assert len(versions) == 1


@dataclass(frozen=True, slots=True)
class SeededExactLineage:
    investigation_id: str
    evidence_id: str
    brief_id: str
    brief_version_id: str
    owner_id: str
    expected_brief_row_version: int
    checklist_digest: str
    selection_manifest: dict[str, object]


def _seed_exact_lineage_lock_fixture(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
    seeded_guard_rows: SeededGuardRows,
) -> SeededExactLineage:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as db:
        collection = CollectionRun(
            workspace_id=seeded_tenants.workspace_a,
            watchlist_id=seeded_tenants.watchlist_a,
            source_connection_id=seeded_tenants.source_a,
            stable_key=f"exact-lineage:{uuid4()}",
            state="completed",
            cadence="manual",
            timezone="UTC",
            scheduled_for=datetime.now(UTC),
            input_window_json={},
            counters_json={"accepted": 1},
            freshness_json={},
            data_authenticity="collected",
        )
        db.add(collection)
        db.flush()
        body = "Exact lineage review must serialize before readiness and export."
        raw = RawContentItem(
            workspace_id=seeded_tenants.workspace_a,
            collection_run_id=collection.id,
            source_connection_id=seeded_tenants.source_a,
            source_external_id=f"exact-lineage-{uuid4()}",
            raw_snapshot_uri=f"object://exact-lineage/{uuid4()}.txt",
            raw_digest=text_digest(body),
            data_authenticity="collected",
        )
        item = ContentItem(
            workspace_id=seeded_tenants.workspace_a,
            source_connection_id=seeded_tenants.source_a,
            source_item_id=f"exact-lineage-{uuid4()}",
            identity_key=f"exact-lineage-{uuid4()}",
            title="Exact lineage concurrency",
            data_authenticity="collected",
        )
        db.add_all([raw, item])
        db.flush()
        content = ContentVersion(
            workspace_id=seeded_tenants.workspace_a,
            content_item_id=item.id,
            source_connection_id=seeded_tenants.source_a,
            raw_content_item_id=raw.id,
            version_number=1,
            content_digest=text_digest(body),
            normalized_title=item.title,
            normalized_body=body,
            metadata_json={},
            raw_snapshot_uri=raw.raw_snapshot_uri,
            parser_version="exact-lineage-test-v1",
            data_authenticity="collected",
        )
        db.add(content)
        db.flush()
        item.current_version_id = content.id

        investigation = Investigation(
            workspace_id=seeded_tenants.workspace_a,
            project_id=seeded_tenants.project_a,
            signal_id=seeded_guard_rows.signal_id,
            status="reviewing",
            owner_id=seeded_tenants.principal_a,
            data_authenticity="collected",
        )
        db.add(investigation)
        db.flush()
        window = {"start": "2026-01-01", "end": "2026-06-30"}
        scope = InvestigationScopeVersion(
            workspace_id=seeded_tenants.workspace_a,
            investigation_id=investigation.id,
            version_number=1,
            decision_question="Should exact lineage commands serialize?",
            source_scope_json={"source_connection_ids": [seeded_tenants.source_a]},
            time_range_json=window,
            budget_json={},
            stop_conditions=["one reviewed exact lineage"],
            created_by=seeded_tenants.principal_a,
            change_reason="Concurrency fixture scope.",
            data_authenticity="collected",
        )
        db.add(scope)
        db.flush()
        investigation.current_scope_version_id = scope.id
        run_manifest = {"content_version_ids": [content.id]}
        run = ResearchRun(
            workspace_id=seeded_tenants.workspace_a,
            investigation_id=investigation.id,
            investigation_scope_version_id=scope.id,
            state="completed",
            graph_version="exact-lineage-test-v1",
            run_input_manifest_json=run_manifest,
            run_input_manifest_digest=digest(run_manifest),
            budget_json={},
            initiated_by=seeded_tenants.principal_a,
            trace_id=f"exact-lineage-{uuid4()}",
            data_authenticity="collected",
        )
        db.add(run)
        db.flush()
        evidence = Evidence(
            workspace_id=seeded_tenants.workspace_a,
            investigation_id=investigation.id,
            research_run_id=run.id,
            content_version_id=content.id,
            quote_start=0,
            quote_end=len(body),
            quote_text=body,
            quote_text_digest=text_digest(body),
            stance="supports",
            relevance=1.0,
            reliability=1.0,
            independence=1.0,
            recency=1.0,
            specificity=1.0,
            extraction_method="exact-lineage-test-v1",
            data_authenticity="collected",
        )
        claim = Claim(
            workspace_id=seeded_tenants.workspace_a,
            investigation_id=investigation.id,
            research_run_id=run.id,
            aggregate_status="verified",
            owner_id=seeded_tenants.principal_a,
            data_authenticity="collected",
        )
        db.add_all([evidence, claim])
        db.flush()
        evidence_review = EvidenceReview(
            workspace_id=seeded_tenants.workspace_a,
            evidence_id=evidence.id,
            decision="valid",
            reviewer_id=seeded_tenants.principal_a,
            reason="Initial exact review.",
            policy_version="evidence-review-v1",
            data_authenticity="collected",
        )
        claim_version = ClaimVersion(
            workspace_id=seeded_tenants.workspace_a,
            claim_id=claim.id,
            version_number=1,
            claim_type="observation",
            text="Exact lineage mutations serialize on the Investigation root.",
            confidence_inputs_json={"supporting_evidence_count": 1},
            confidence_score=1.0,
            confidence_level="high",
            confidence_input_digest=digest({"supporting_evidence_count": 1}),
            calibration_status="uncalibrated",
            limitations=["One deterministic concurrency fixture."],
            generation_method="deterministic",
            generator_version="exact-lineage-test-v1",
            suggestion_origin="deterministic_rule",
            created_by=seeded_tenants.principal_a,
            data_authenticity="collected",
        )
        db.add_all([evidence_review, claim_version])
        db.flush()
        claim.current_version_id = claim_version.id
        link = ClaimEvidence(
            workspace_id=seeded_tenants.workspace_a,
            claim_version_id=claim_version.id,
            evidence_id=evidence.id,
            stance="supports",
            weight=1.0,
            rationale="Exact reviewed support.",
            linked_by=seeded_tenants.principal_a,
            data_authenticity="collected",
        )
        db.add(link)
        db.flush()
        claim_snapshot = {
            "claim_version_id": claim_version.id,
            "claim_evidence_ids": [link.id],
            "evidence_review_ids": [evidence_review.id],
        }
        claim_review = ClaimReview(
            workspace_id=seeded_tenants.workspace_a,
            claim_version_id=claim_version.id,
            decision="verify",
            claim_evidence_snapshot_json=[link.id],
            evidence_review_snapshot_json=[evidence_review.id],
            snapshot_digest=digest(claim_snapshot),
            reviewer_id=seeded_tenants.principal_a,
            reason="Exact claim lineage verified.",
            policy_version="claim-review-v1",
            data_authenticity="collected",
        )
        synthesis = InvestigationSynthesis(
            workspace_id=seeded_tenants.workspace_a,
            investigation_id=investigation.id,
            data_authenticity="collected",
        )
        db.add_all([claim_review, synthesis])
        db.flush()
        synthesis_version = InvestigationSynthesisVersion(
            workspace_id=seeded_tenants.workspace_a,
            synthesis_id=synthesis.id,
            version_number=1,
            verified_claim_version_snapshot_json=[claim_version.id],
            claim_review_snapshot_json=[claim_review.id],
            generation_method="deterministic",
            generator_version="exact-lineage-test-v1",
            model_prompt_refs_json=[],
            executive_summary="Exact lineage commands serialize before readiness and export.",
            business_implications=["Preserve one authoritative ordering."],
            limitations=["One deterministic concurrency fixture."],
            provenance_digest=digest(claim_snapshot),
            created_by=seeded_tenants.principal_a,
            data_authenticity="collected",
        )
        db.add(synthesis_version)
        db.flush()
        synthesis.current_version_id = synthesis_version.id
        investigation.current_synthesis_id = synthesis.id
        synthesis_review = SynthesisReview(
            workspace_id=seeded_tenants.workspace_a,
            synthesis_version_id=synthesis_version.id,
            decision="verify",
            reviewer_id=seeded_tenants.principal_a,
            reason="Exact synthesis verified.",
            policy_version="synthesis-review-v1",
            data_authenticity="collected",
        )
        db.add(synthesis_review)
        db.flush()
        reference_snapshot = {
            "synthesis_version_id": synthesis_version.id,
            "synthesis_review_id": synthesis_review.id,
            "claim_version_ids": [claim_version.id],
            "claim_review_ids": [claim_review.id],
            "claim_evidence_ids": [link.id],
            "evidence_review_ids": [evidence_review.id],
            "evidence_ids": [evidence.id],
            "content_version_ids": [content.id],
        }
        document: dict[str, object] = {
            "schema_version": "decision-brief-blocks-v1",
            "blocks": [
                {
                    "id": "fact-1",
                    "type": "fact",
                    "body": claim_version.text,
                    "claim_version_ids": [claim_version.id],
                    "evidence_ids": [evidence.id],
                    "content_version_ids": [content.id],
                },
                {
                    "id": "synthesis-1",
                    "type": "synthesis",
                    "body": synthesis_version.executive_summary,
                    "synthesis_version_id": synthesis_version.id,
                    "generation_method": synthesis_version.generation_method,
                    "generator_version": synthesis_version.generator_version,
                    "model_prompt_refs": [],
                },
                {
                    "id": "judgment-1",
                    "type": "pm_judgment",
                    "body": "Require exact lineage serialization for release.",
                    "actor_id": seeded_tenants.principal_a,
                },
                {
                    "id": "recommendation-1",
                    "type": "recommendation",
                    "body": "Use the Investigation as the shared lineage lock root.",
                    "recommendation_status": "accepted",
                },
            ],
            "no_counter_evidence_search": {
                "queries": ["exact lineage concurrency counter evidence"],
                "source_connection_ids": [seeded_tenants.source_a],
                "window_start": window["start"],
                "window_end": window["end"],
                "exclusion_criteria": ["duplicate records"],
                "limitations": ["One deterministic source was searched."],
            },
        }
        brief = DecisionBrief(
            workspace_id=seeded_tenants.workspace_a,
            investigation_id=investigation.id,
            status="draft",
            owner_id=seeded_tenants.principal_a,
            data_authenticity="collected",
        )
        db.add(brief)
        db.flush()
        brief_version = DecisionBriefVersion(
            workspace_id=seeded_tenants.workspace_a,
            decision_brief_id=brief.id,
            version_number=1,
            synthesis_version_id=synthesis_version.id,
            synthesis_review_id=synthesis_review.id,
            block_document=document,
            reference_snapshot_json=reference_snapshot,
            template_version="decision-brief-v1",
            human_edit_digest=digest(document),
            created_by=seeded_tenants.principal_a,
            data_authenticity="collected",
        )
        db.add(brief_version)
        db.flush()
        brief.current_version_id = brief_version.id
        investigation.decision_brief_id = brief.id
        checklist_digest = digest(
            {
                "decision_brief_version_id": brief_version.id,
                "block_document": document,
                "reference_snapshot": reference_snapshot,
                "policy_version": "decision-readiness-v1",
            }
        )
        db.commit()
        return SeededExactLineage(
            investigation_id=investigation.id,
            evidence_id=evidence.id,
            brief_id=brief.id,
            brief_version_id=brief_version.id,
            owner_id=seeded_tenants.principal_a,
            expected_brief_row_version=brief.row_version,
            checklist_digest=checklist_digest,
            selection_manifest={
                "block_ids": ["fact-1", "judgment-1", "recommendation-1"],
                "include_citations": True,
            },
        )


def _readiness_payload(fixture: SeededExactLineage) -> dict[str, object]:
    return {
        "decision_brief_version_id": fixture.brief_version_id,
        "expected_row_version": fixture.expected_brief_row_version,
        "decision": "mark_decision_ready",
        "reason": "Exact lineage concurrency fixture is ready.",
        "policy_version": "decision-readiness-v1",
        "checklist_digest": fixture.checklist_digest,
    }


def test_mark_then_evidence_review_stales_freshness_before_export(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
    seeded_guard_rows: SeededGuardRows,
) -> None:
    fixture = _seed_exact_lineage_lock_fixture(postgres_engine, seeded_tenants, seeded_guard_rows)
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory() as db:
        brief = db.get(DecisionBrief, fixture.brief_id)
        assert brief is not None
        mark_ready(
            db,
            brief=brief,
            actor_id=fixture.owner_id,
            payload=_readiness_payload(fixture),
            request_id=str(uuid4()),
        )

    waiting_pids: Queue[int] = Queue()

    def invoke_export() -> ApiError | None:
        with factory() as db:
            waiting_pids.put(int(db.scalar(text("SELECT pg_backend_pid()"))))
            brief = db.get(DecisionBrief, fixture.brief_id)
            version = db.get(DecisionBriefVersion, fixture.brief_version_id)
            assert brief is not None and version is not None
            try:
                render_export_preview(
                    db,
                    brief=brief,
                    version=version,
                    export_type="prd_research_input_markdown",
                    selection_manifest=fixture.selection_manifest,
                )
            except ApiError as error:
                return error
        return None

    with factory() as reviewer:
        locked = reviewer.scalar(
            select(Investigation)
            .where(Investigation.id == fixture.investigation_id)
            .with_for_update()
        )
        assert locked is not None
        blocking_pid = int(reviewer.scalar(text("SELECT pg_backend_pid()")))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(invoke_export)
            _wait_for_confirmed_postgres_lock(
                postgres_engine,
                waiting_pid=waiting_pids.get(timeout=5),
                blocking_pid=blocking_pid,
            )
            evidence = reviewer.get(Evidence, fixture.evidence_id)
            assert evidence is not None
            changed_review = review_evidence(
                reviewer,
                evidence=evidence,
                actor_id=fixture.owner_id,
                decision="weak",
                reason="A later exact EvidenceReview changes the frozen lineage.",
                policy_version="evidence-review-v1",
                request_id=str(uuid4()),
            )
            export_error = future.result(timeout=5)

    assert isinstance(export_error, ApiError)
    assert export_error.status_code == 409
    assert export_error.code == "APPROVAL_REQUIRED"
    with factory() as db:
        freshness = latest_freshness(db, fixture.brief_version_id)
        latest_review = latest_evidence_review(db, fixture.evidence_id)
        assert freshness is not None and freshness.status == "evidence_stale"
        assert latest_review is not None and latest_review.id == changed_review.id
        assert freshness.affected_reference_snapshot_json == [
            {
                "evidence_id": fixture.evidence_id,
                "latest_evidence_review_id": changed_review.id,
                "decision": "weak",
            }
        ]


def test_evidence_review_then_mark_ready_observes_new_exact_review(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
    seeded_guard_rows: SeededGuardRows,
) -> None:
    fixture = _seed_exact_lineage_lock_fixture(postgres_engine, seeded_tenants, seeded_guard_rows)
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    waiting_pids: Queue[int] = Queue()

    def invoke_mark_ready() -> ApiError | None:
        with factory() as db:
            waiting_pids.put(int(db.scalar(text("SELECT pg_backend_pid()"))))
            brief = db.get(DecisionBrief, fixture.brief_id)
            assert brief is not None
            try:
                mark_ready(
                    db,
                    brief=brief,
                    actor_id=fixture.owner_id,
                    payload=_readiness_payload(fixture),
                    request_id=str(uuid4()),
                )
            except ApiError as error:
                return error
        return None

    with factory() as reviewer:
        locked = reviewer.scalar(
            select(Investigation)
            .where(Investigation.id == fixture.investigation_id)
            .with_for_update()
        )
        assert locked is not None
        blocking_pid = int(reviewer.scalar(text("SELECT pg_backend_pid()")))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(invoke_mark_ready)
            _wait_for_confirmed_postgres_lock(
                postgres_engine,
                waiting_pid=waiting_pids.get(timeout=5),
                blocking_pid=blocking_pid,
            )
            evidence = reviewer.get(Evidence, fixture.evidence_id)
            assert evidence is not None
            changed_review = review_evidence(
                reviewer,
                evidence=evidence,
                actor_id=fixture.owner_id,
                decision="weak",
                reason="Review wins the Investigation lineage lock.",
                policy_version="evidence-review-v1",
                request_id=str(uuid4()),
            )
            readiness_error = future.result(timeout=5)

    assert isinstance(readiness_error, ApiError)
    assert readiness_error.status_code == 409
    assert readiness_error.code == "APPROVAL_REQUIRED"
    with factory() as db:
        brief = db.get(DecisionBrief, fixture.brief_id)
        latest_review = latest_evidence_review(db, fixture.evidence_id)
        readiness_count = db.scalar(
            select(DecisionBriefReadinessReview).where(
                DecisionBriefReadinessReview.decision_brief_version_id == fixture.brief_version_id
            )
        )
        assert brief is not None
        assert brief.status == "draft"
        assert brief.row_version == fixture.expected_brief_row_version
        assert latest_review is not None and latest_review.id == changed_review.id
        assert readiness_count is None


def _seed_postgres_source_validation_job(
    api_engine: Engine,
    seeded_tenants: SeededTenants,
) -> tuple[str, str]:
    source_id = str(uuid4())
    factory = sessionmaker(bind=api_engine, expire_on_commit=False, autoflush=False)
    with factory() as db:
        set_rls_context(db, seeded_tenants.workspace_a, seeded_tenants.principal_a)
        db.add(
            SourceConnection(
                id=source_id,
                workspace_id=seeded_tenants.workspace_a,
                name="Source validation locking fixture",
                source_kind="cloud",
                runtime="cloud",
                connector_type="rss",
                connector_version="rss-v1",
                status="healthy",
                config_json={"feed_url": "https://example.test/feed.xml"},
                cadence="daily",
                timezone="UTC",
                freshness_state="current",
                health_state="healthy",
                data_scope="workspace_confidential",
                approved_by=seeded_tenants.principal_a,
                data_authenticity="human_authored",
            )
        )
        db.commit()
        job = SourceValidationJobRepository.enqueue(
            db,
            workspace_id=seeded_tenants.workspace_a,
            source_connection_id=source_id,
            command="health_check",
            expected_source_row_version=1,
            actor_id=seeded_tenants.principal_a,
            request_id=str(uuid4()),
            idempotency_key=str(uuid4()),
            reason="PostgreSQL source validation fixture",
        )
        return source_id, job.id


def test_source_lifecycle_checks_active_validation_under_source_row_lock(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
) -> None:
    api_engine = create_engine(_runtime_url("glint_api"), pool_pre_ping=True)
    try:
        source_id, _job_id = _seed_postgres_source_validation_job(api_engine, seeded_tenants)
        owner_factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
        api_factory = sessionmaker(bind=api_engine, expire_on_commit=False)
        started = Event()

        def invoke_lifecycle_lock() -> ApiError | None:
            with api_factory() as db:
                set_rls_context(db, seeded_tenants.workspace_a, seeded_tenants.principal_a)
                started.set()
                try:
                    SourceValidationJobRepository.lock_source_for_lifecycle_command(
                        db,
                        workspace_id=seeded_tenants.workspace_a,
                        source_connection_id=source_id,
                    )
                except ApiError as error:
                    return error
            return None

        with owner_factory() as locker:
            locked = locker.scalar(
                select(SourceConnection).where(SourceConnection.id == source_id).with_for_update()
            )
            assert locked is not None
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(invoke_lifecycle_lock)
                assert started.wait(timeout=5)
                blocked_on_source_lock = False
                try:
                    future.result(timeout=0.25)
                except FutureTimeoutError:
                    blocked_on_source_lock = True
                finally:
                    locker.commit()
                error = future.result(timeout=5)

        assert blocked_on_source_lock is True
        assert isinstance(error, ApiError)
        assert error.status_code == 409
        assert error.code == "SOURCE_VALIDATION_IN_PROGRESS"
        with owner_factory() as db:
            source = db.get(SourceConnection, source_id)
            assert source is not None
            assert source.status == "validating"
            assert source.row_version == 2
    finally:
        api_engine.dispose()


def test_worker_real_login_terminalizes_source_fence_drift_and_releases_queue(
    postgres_engine: Engine,
    seeded_tenants: SeededTenants,
) -> None:
    api_engine = create_engine(_runtime_url("glint_api"), pool_pre_ping=True)
    worker_engine = create_engine(_runtime_url("glint_worker"), pool_pre_ping=True)
    try:
        source_id, job_id = _seed_postgres_source_validation_job(api_engine, seeded_tenants)
        worker_factory = sessionmaker(bind=worker_engine, expire_on_commit=False, autoflush=False)
        with worker_factory() as db:
            set_rls_context(db, seeded_tenants.workspace_a, "source-validation-worker")
            claimed = SourceValidationJobRepository.claim(
                db,
                workspace_id=seeded_tenants.workspace_a,
                job_id=job_id,
                owner_token="postgres-fence-drift-worker",
            )
            assert claimed is not None

        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE source_connections SET status = 'disabled', "
                    "health_state = 'disabled', row_version = row_version + 1 "
                    "WHERE id = :source_id"
                ),
                {"source_id": source_id},
            )

        with worker_factory() as db:
            set_rls_context(db, seeded_tenants.workspace_a, "source-validation-worker")
            terminal = SourceValidationJobRepository.complete(
                db,
                workspace_id=seeded_tenants.workspace_a,
                job_id=job_id,
                owner_token="postgres-fence-drift-worker",
                expected_attempt=claimed.attempt,
                expected_fencing_version=claimed.fencing_version,
                source_status="healthy",
            )
            assert terminal.state == "failed"
            assert terminal.failure_code == "SOURCE_VALIDATION_FENCE_DRIFT"
            assert terminal.lease_owner_token is None

        owner_factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
        with owner_factory() as db:
            source = db.get(SourceConnection, source_id)
            terminal = db.get(SourceValidationJobRecord, job_id)
            assert source is not None
            assert terminal is not None
            assert source.status == "disabled"
            assert source.health_state == "disabled"
            assert source.row_version == 3
            assert terminal.state == "failed"
            assert terminal.result_source_status == "failed"
            assert terminal.lease_expires_at is None

        api_factory = sessionmaker(bind=api_engine, expire_on_commit=False, autoflush=False)
        with api_factory() as db:
            set_rls_context(db, seeded_tenants.workspace_a, seeded_tenants.principal_a)
            requeued = SourceValidationJobRepository.enqueue(
                db,
                workspace_id=seeded_tenants.workspace_a,
                source_connection_id=source_id,
                command="health_check",
                expected_source_row_version=3,
                actor_id=seeded_tenants.principal_a,
                request_id=str(uuid4()),
                idempotency_key=str(uuid4()),
                reason="Retry after PostgreSQL fence drift",
            )
            assert requeued.id != job_id
            assert requeued.state == "queued"
            assert requeued.expected_source_row_version == 4
    finally:
        worker_engine.dispose()
        api_engine.dispose()
