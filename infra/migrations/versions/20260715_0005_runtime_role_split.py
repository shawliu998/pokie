"""Split API and worker PostgreSQL privileges.

Revision ID: 20260715_0005
Revises: 20260715_0004

The deployment provisions the roles and credentials.  This migration owns the
object grants.  Worker UPDATE privileges are column-scoped and newly-created
tables receive no implicit runtime privileges.
"""

from alembic import op

revision = "20260715_0005"
down_revision = "20260715_0004"
branch_labels = None
depends_on = None


# Revision-local snapshots: never derive a historical privilege migration from
# mutable ORM metadata. New tables receive no grants until their own migration.
API_SELECT_TABLES = (
    "workspaces",
    "workspace_members",
    "projects",
    "watchlists",
    "source_connections",
    "source_validation_jobs",
    "collection_runs",
    "collection_schedules",
    "import_sessions",
    "transfer_consent_records",
    "upload_grants",
    "import_finalization_jobs",
    "import_manifests",
    "import_manifest_content_versions",
    "raw_content_items",
    "content_items",
    "content_versions",
    "signals",
    "signal_evidence",
    "investigations",
    "investigation_scope_versions",
    "research_runs",
    "run_events",
    "evidence",
    "evidence_reviews",
    "claims",
    "claim_versions",
    "claim_evidence",
    "claim_reviews",
    "investigation_syntheses",
    "investigation_synthesis_versions",
    "synthesis_reviews",
    "decision_briefs",
    "decision_brief_versions",
    "decision_brief_readiness_reviews",
    "decision_brief_freshness_records",
    "brief_exports",
    "audit_logs",
    "idempotency_records",
)

API_INSERT_TABLES = (
    "workspaces",
    "workspace_members",
    "projects",
    "watchlists",
    "source_connections",
    "source_validation_jobs",
    "collection_schedules",
    "import_sessions",
    "transfer_consent_records",
    "upload_grants",
    "import_finalization_jobs",
    "investigations",
    "investigation_scope_versions",
    "research_runs",
    "run_events",
    "evidence_reviews",
    "claim_versions",
    "claim_evidence",
    "claim_reviews",
    "investigation_syntheses",
    "investigation_synthesis_versions",
    "synthesis_reviews",
    "decision_briefs",
    "decision_brief_versions",
    "decision_brief_readiness_reviews",
    "decision_brief_freshness_records",
    "brief_exports",
    "audit_logs",
    "idempotency_records",
)

API_UPDATE_COLUMNS = {
    "workspaces": ("updated_at", "row_version", "name", "retention_policy_version"),
    "projects": ("updated_at", "row_version", "name", "status"),
    "watchlists": (
        "updated_at",
        "row_version",
        "name",
        "objective",
        "status",
        "rules_version",
        "rules_json",
    ),
    "source_connections": (
        "updated_at",
        "row_version",
        "name",
        "status",
        "credential_ref",
        "config_json",
        "cadence",
        "timezone",
        "health_state",
        "health_error_code",
        "approved_by",
        "data_scope",
    ),
    "collection_schedules": (
        "updated_at",
        "row_version",
        "query_json",
        "cadence_seconds",
        "timezone",
        "misfire_policy",
        "catch_up",
        "overlap_policy",
        "next_run_at",
        "enabled",
        "lease_owner_token",
        "lease_expires_at",
        "heartbeat_at",
    ),
    "import_sessions": (
        "updated_at",
        "row_version",
        "state",
        "uploaded_object_key",
        "uploaded_object_digest",
        "failure_code",
        "retryable",
    ),
    "upload_grants": (
        "revoked_at",
        "observed_size_bytes",
        "observed_media_type",
        "observed_digest",
        "uploaded_at",
    ),
    "import_finalization_jobs": (
        "updated_at",
        "expected_session_row_version",
        "expected_source_row_version",
        "expected_current_import_manifest_id",
        "consent_record_id",
        "actor_id",
        "request_id",
        "idempotency_key",
        "state",
        "attempt",
        "failure_code",
        "retryable",
        "claimed_by",
        "lease_acquired_at",
        "lease_expires_at",
    ),
    "signals": (
        "updated_at",
        "row_version",
        "status",
        "dimensions_json",
        "disposition_json",
    ),
    "investigations": (
        "updated_at",
        "row_version",
        "current_scope_version_id",
        "status",
        "current_synthesis_id",
        "decision_brief_id",
    ),
    "research_runs": ("updated_at", "row_version", "state", "latest_sequence"),
    "claims": (
        "updated_at",
        "row_version",
        "current_version_id",
        "aggregate_status",
    ),
    "investigation_syntheses": ("updated_at", "row_version", "current_version_id"),
    "decision_briefs": ("updated_at", "row_version", "current_version_id", "status"),
    "idempotency_records": (
        "updated_at",
        "state",
        "owner_token",
        "lease_expires_at",
        "response_status",
        "response_json",
    ),
}

API_DELETE_TABLES = ("idempotency_records",)

API_RUN_EVENT_TYPES = (
    "investigation.started_from_signal",
    "run.queued",
    "run.cancelled",
    "evidence.reviewed",
    "claim.version_reviewed",
)

WORKER_RUN_EVENT_TYPES = (
    "run.started",
    "task.started",
    "task.completed",
    "evidence.proposed",
    "claim.version_proposed",
    "review.required",
    "run.completed",
)


WORKER_SELECT_TABLES = (
    "watchlists",
    "source_connections",
    "source_validation_jobs",
    "collection_runs",
    "collection_schedules",
    "import_sessions",
    "transfer_consent_records",
    "upload_grants",
    "import_finalization_jobs",
    "import_manifests",
    "import_manifest_content_versions",
    "raw_content_items",
    "content_items",
    "content_versions",
    "signals",
    "signal_evidence",
    "research_runs",
    "run_events",
    "evidence",
    "evidence_reviews",
    "claims",
    "claim_versions",
    "claim_evidence",
)

WORKER_INSERT_TABLES = (
    "collection_runs",
    "import_manifests",
    "import_manifest_content_versions",
    "raw_content_items",
    "content_items",
    "content_versions",
    "signals",
    "signal_evidence",
    "run_events",
    "evidence",
    "claims",
    "claim_versions",
    "claim_evidence",
)

WORKER_UPDATE_COLUMNS = {
    "source_connections": (
        "updated_at",
        "row_version",
        "status",
        "current_import_manifest_id",
        "last_run_at",
        "last_success_at",
        "freshness_state",
        "health_state",
        "health_checked_at",
        "health_error_code",
    ),
    "source_validation_jobs": (
        "updated_at",
        "state",
        "attempt",
        "lease_owner_token",
        "lease_expires_at",
        "heartbeat_at",
        "fencing_version",
        "result_source_status",
        "failure_code",
        "failure_reason",
    ),
    "collection_runs": (
        "updated_at",
        "row_version",
        "state",
        "started_at",
        "input_window_json",
        "counters_json",
        "partial_success",
        "freshness_json",
        "failure_code",
        "finished_at",
    ),
    "collection_schedules": (
        "updated_at",
        "row_version",
        "next_run_at",
        "lease_owner_token",
        "lease_expires_at",
        "heartbeat_at",
        "lease_attempt",
        "lease_fencing_version",
    ),
    "import_sessions": (
        "updated_at",
        "row_version",
        "state",
        "terminal_manifest_id",
        "failure_code",
        "retryable",
    ),
    "import_finalization_jobs": (
        "updated_at",
        "expected_session_row_version",
        "state",
        "attempt",
        "result_manifest_id",
        "failure_code",
        "retryable",
        "claimed_by",
        "lease_acquired_at",
        "lease_expires_at",
    ),
    "content_items": (
        "updated_at",
        "row_version",
        "source_item_id",
        "canonical_url",
        "title",
        "current_version_id",
        "duplicate_cluster_id",
        "independence_group_id",
    ),
    "research_runs": (
        "updated_at",
        "row_version",
        "state",
        "latest_sequence",
        "worker_claimed_by",
        "worker_attempt_id",
        "worker_lease_expires_at",
        "worker_heartbeat_at",
        "worker_fencing_version",
    ),
    "claims": (
        "updated_at",
        "current_version_id",
    ),
}

WORKER_AUDIT_ACTIONS = (
    ("import.finalized", "ImportManifest"),
    ("import.finalization_failed", "ImportFinalizationJob"),
    ("research_run.completed", "ResearchRun"),
    ("source.validation_completed", "SourceValidationJob"),
    ("source.validation_failed", "SourceValidationJob"),
)


def _quoted_csv(values: tuple[str, ...]) -> str:
    return ", ".join(f'"{value}"' for value in values)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        "DO $$ BEGIN "
        "IF current_user IN ('glint_app','glint_api','glint_worker') THEN "
        "RAISE EXCEPTION 'Alembic must run as a migration owner, not a runtime role'; "
        "ELSIF EXISTS (SELECT 1 FROM unnest(ARRAY['glint_app','glint_api','glint_worker']) "
        "AS required(role_name) WHERE NOT EXISTS (SELECT 1 FROM pg_roles "
        "WHERE rolname = required.role_name)) THEN "
        "RAISE EXCEPTION 'Deployment must provision glint_app, glint_api and glint_worker'; "
        "ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE "
        "rolname IN ('glint_app','glint_api','glint_worker') AND "
        "(rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN "
        "RAISE EXCEPTION 'Glint runtime roles must not own or bypass database security'; "
        "ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE "
        "rolname IN ('glint_app','glint_api','glint_worker') AND rolinherit) THEN "
        "RAISE EXCEPTION 'Glint runtime roles must be NOINHERIT'; "
        "ELSIF EXISTS (SELECT 1 FROM pg_auth_members membership "
        "JOIN pg_roles member_role ON member_role.oid = membership.member "
        "WHERE member_role.rolname IN ('glint_app','glint_api','glint_worker')) THEN "
        "RAISE EXCEPTION 'Glint runtime roles must not be members of other roles'; "
        "ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'glint_app' AND rolcanlogin) THEN "
        "RAISE EXCEPTION 'glint_app must be a NOLOGIN compatibility role'; "
        "ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE "
        "rolname IN ('glint_api','glint_worker') AND NOT rolcanlogin) THEN "
        "RAISE EXCEPTION 'glint_api and glint_worker must be LOGIN roles'; "
        "END IF; END $$"
    )

    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC, glint_app, glint_api, glint_worker")
    op.execute("GRANT USAGE ON SCHEMA public TO glint_api, glint_worker")

    # Remove the former shared runtime role and fail closed for future objects.
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM glint_app")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM glint_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM glint_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM glint_app")
    for role in ("glint_api", "glint_worker"):
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {role}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {role}")

    # API owns only human/domain mutations. Pipeline outputs remain read-only.
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM glint_api")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM glint_api")
    op.execute(f"GRANT SELECT ON TABLE {_quoted_csv(API_SELECT_TABLES)} TO glint_api")
    op.execute(f"GRANT INSERT ON TABLE {_quoted_csv(API_INSERT_TABLES)} TO glint_api")
    for table, columns in API_UPDATE_COLUMNS.items():
        op.execute(f'GRANT UPDATE ({_quoted_csv(columns)}) ON TABLE "{table}" TO glint_api')
    op.execute(f"GRANT DELETE ON TABLE {_quoted_csv(API_DELETE_TABLES)} TO glint_api")

    # Worker receives only the reads and proposal/pipeline writes used by the
    # production SQLAlchemy adapter. It receives no DELETE or sequence grant.
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM glint_worker")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM glint_worker")
    op.execute(f"GRANT SELECT ON TABLE {_quoted_csv(WORKER_SELECT_TABLES)} TO glint_worker")
    op.execute(f"GRANT INSERT ON TABLE {_quoted_csv(WORKER_INSERT_TABLES)} TO glint_worker")
    for table, columns in WORKER_UPDATE_COLUMNS.items():
        op.execute(f'GRANT UPDATE ({_quoted_csv(columns)}) ON TABLE "{table}" TO glint_worker')

    # Human/API run events are a closed set. Worker events remain workspace-
    # scoped, while a compromised API cannot forge worker task/proposal events.
    op.execute('DROP POLICY IF EXISTS "run_events_workspace_scope" ON "run_events"')
    op.execute(
        'CREATE POLICY "run_events_api_select" ON "run_events" '
        "FOR SELECT TO glint_api USING ("
        "workspace_id::text = current_setting('app.workspace_id', true))"
    )
    api_event_values = ", ".join(f"'{event_type}'" for event_type in API_RUN_EVENT_TYPES)
    op.execute(
        'CREATE POLICY "run_events_api_insert" ON "run_events" '
        "FOR INSERT TO glint_api WITH CHECK ("
        "workspace_id::text = current_setting('app.workspace_id', true) "
        f"AND type IN ({api_event_values}))"
    )
    op.execute(
        'CREATE POLICY "run_events_worker_workspace_scope" ON "run_events" '
        "FOR SELECT TO glint_worker USING ("
        "workspace_id::text = current_setting('app.workspace_id', true))"
    )
    worker_event_values = ", ".join(f"'{event_type}'" for event_type in WORKER_RUN_EVENT_TYPES)
    op.execute(
        'CREATE POLICY "run_events_worker_insert" ON "run_events" '
        "FOR INSERT TO glint_worker WITH CHECK ("
        "workspace_id::text = current_setting('app.workspace_id', true) "
        f"AND type IN ({worker_event_values}))"
    )

    # Some human commands legitimately clear worker leases. Column grants alone
    # cannot express "clear, never acquire", so database triggers fence those
    # exceptional API updates without widening the worker contract.
    op.execute(
        "CREATE OR REPLACE FUNCTION glint_guard_api_schedule_lease() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF current_user = 'glint_api' THEN "
        "IF TG_OP = 'INSERT' AND (NEW.lease_owner_token IS NOT NULL "
        "OR NEW.lease_expires_at IS NOT NULL OR NEW.heartbeat_at IS NOT NULL "
        "OR NEW.lease_attempt <> 0 OR NEW.lease_fencing_version <> 0) THEN "
        "RAISE EXCEPTION 'glint_api cannot create an acquired collection lease' "
        "USING ERRCODE = '42501'; "
        "ELSIF TG_OP = 'UPDATE' AND ((NEW.lease_owner_token IS DISTINCT FROM "
        "OLD.lease_owner_token AND NEW.lease_owner_token IS NOT NULL) OR "
        "(NEW.lease_expires_at IS DISTINCT FROM OLD.lease_expires_at "
        "AND NEW.lease_expires_at IS NOT NULL) OR "
        "(NEW.heartbeat_at IS DISTINCT FROM OLD.heartbeat_at "
        "AND NEW.heartbeat_at IS NOT NULL)) THEN "
        "RAISE EXCEPTION 'glint_api may clear but not acquire a collection lease' "
        "USING ERRCODE = '42501'; END IF; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION glint_guard_api_schedule_lease() "
        "FROM PUBLIC, glint_api, glint_worker"
    )
    op.execute("DROP TRIGGER IF EXISTS glint_guard_api_schedule_lease ON collection_schedules")
    op.execute(
        "DROP TRIGGER IF EXISTS glint_guard_api_schedule_lease_insert ON collection_schedules"
    )
    op.execute(
        "CREATE TRIGGER glint_guard_api_schedule_lease_insert BEFORE INSERT "
        "ON collection_schedules FOR EACH ROW "
        "EXECUTE FUNCTION glint_guard_api_schedule_lease()"
    )
    op.execute(
        "CREATE TRIGGER glint_guard_api_schedule_lease BEFORE UPDATE OF "
        "lease_owner_token, lease_expires_at, heartbeat_at ON collection_schedules "
        "FOR EACH ROW EXECUTE FUNCTION glint_guard_api_schedule_lease()"
    )

    op.execute(
        "CREATE OR REPLACE FUNCTION glint_guard_api_import_retry() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF current_user = 'glint_api' THEN "
        "IF TG_OP = 'INSERT' AND NOT (NEW.state = 'queued' AND NEW.attempt = 1 "
        "AND NEW.result_manifest_id IS NULL AND NEW.failure_code IS NULL "
        "AND NEW.retryable IS FALSE AND NEW.claimed_by IS NULL "
        "AND NEW.lease_acquired_at IS NULL AND NEW.lease_expires_at IS NULL) THEN "
        "RAISE EXCEPTION 'glint_api may only create an unclaimed import command' "
        "USING ERRCODE = '42501'; "
        "ELSIF TG_OP = 'UPDATE' AND NOT (OLD.state = 'failed' AND OLD.retryable IS TRUE "
        "AND NEW.state = 'queued' AND NEW.attempt = OLD.attempt + 1 "
        "AND NEW.failure_code IS NULL AND NEW.retryable IS FALSE "
        "AND NEW.claimed_by IS NULL AND NEW.lease_acquired_at IS NULL "
        "AND NEW.lease_expires_at IS NULL) THEN "
        "RAISE EXCEPTION 'glint_api may only clear a failed import lease during retry' "
        "USING ERRCODE = '42501'; END IF; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION glint_guard_api_import_retry() FROM PUBLIC, glint_api, glint_worker"
    )
    op.execute("DROP TRIGGER IF EXISTS glint_guard_api_import_retry ON import_finalization_jobs")
    op.execute(
        "DROP TRIGGER IF EXISTS glint_guard_api_import_retry_insert ON import_finalization_jobs"
    )
    op.execute(
        "CREATE TRIGGER glint_guard_api_import_retry_insert BEFORE INSERT "
        "ON import_finalization_jobs FOR EACH ROW "
        "EXECUTE FUNCTION glint_guard_api_import_retry()"
    )
    op.execute(
        "CREATE TRIGGER glint_guard_api_import_retry BEFORE UPDATE OF "
        "expected_session_row_version, expected_source_row_version, "
        "expected_current_import_manifest_id, consent_record_id, actor_id, request_id, "
        "idempotency_key, state, attempt, failure_code, retryable, claimed_by, "
        "lease_acquired_at, lease_expires_at ON import_finalization_jobs "
        "FOR EACH ROW EXECUTE FUNCTION glint_guard_api_import_retry()"
    )

    # The API creates queued Research Runs, but worker ownership, cost, and
    # fencing fields must start empty and can only be advanced by the worker.
    op.execute(
        "CREATE OR REPLACE FUNCTION glint_guard_api_research_run_insert() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF current_user = 'glint_api' AND NOT (NEW.state = 'queued' "
        "AND NEW.used_cost = 0 AND NEW.latest_sequence = 0 "
        "AND NEW.worker_claimed_by IS NULL AND NEW.worker_attempt_id IS NULL "
        "AND NEW.worker_lease_expires_at IS NULL AND NEW.worker_heartbeat_at IS NULL "
        "AND NEW.worker_fencing_version = 0) THEN "
        "RAISE EXCEPTION 'glint_api may only create an unclaimed queued Research Run' "
        "USING ERRCODE = '42501'; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION glint_guard_api_research_run_insert() "
        "FROM PUBLIC, glint_api, glint_worker"
    )
    op.execute("DROP TRIGGER IF EXISTS glint_guard_api_research_run_insert ON research_runs")
    op.execute(
        "CREATE TRIGGER glint_guard_api_research_run_insert BEFORE INSERT "
        "ON research_runs FOR EACH ROW "
        "EXECUTE FUNCTION glint_guard_api_research_run_insert()"
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION glint_guard_api_research_run_state() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF current_user = 'glint_api' AND NEW.state IS DISTINCT FROM OLD.state "
        "AND NOT (OLD.state IN ('queued','running','waiting_for_input') "
        "AND NEW.state = 'cancelled') THEN "
        "RAISE EXCEPTION 'glint_api may only cancel an unfinished Research Run' "
        "USING ERRCODE = '42501'; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION glint_guard_api_research_run_state() "
        "FROM PUBLIC, glint_api, glint_worker"
    )
    op.execute("DROP TRIGGER IF EXISTS glint_guard_api_research_run_state ON research_runs")
    op.execute(
        "CREATE TRIGGER glint_guard_api_research_run_state BEFORE UPDATE OF state "
        "ON research_runs FOR EACH ROW "
        "EXECUTE FUNCTION glint_guard_api_research_run_state()"
    )

    op.execute(
        "CREATE OR REPLACE FUNCTION glint_guard_api_source_validation_insert() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF current_user = 'glint_api' AND NOT (NEW.state = 'queued' "
        "AND NEW.attempt = 0 AND NEW.lease_owner_token IS NULL "
        "AND NEW.lease_expires_at IS NULL AND NEW.heartbeat_at IS NULL "
        "AND NEW.fencing_version = 0 AND NEW.result_source_status IS NULL "
        "AND NEW.failure_code IS NULL AND NEW.failure_reason IS NULL) THEN "
        "RAISE EXCEPTION 'glint_api may only enqueue an unclaimed source validation' "
        "USING ERRCODE = '42501'; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION glint_guard_api_source_validation_insert() "
        "FROM PUBLIC, glint_api, glint_worker"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS glint_guard_api_source_validation_insert ON source_validation_jobs"
    )
    op.execute(
        "CREATE TRIGGER glint_guard_api_source_validation_insert BEFORE INSERT "
        "ON source_validation_jobs FOR EACH ROW "
        "EXECUTE FUNCTION glint_guard_api_source_validation_insert()"
    )

    # Signal detection metrics and detector-owned dimensions are worker output.
    # API triage may update only the human confirmation fields and derived
    # priority subtree inside dimensions_json.
    op.execute(
        "CREATE OR REPLACE FUNCTION glint_guard_api_signal_dimensions() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE "
        "human_keys text[] := ARRAY['confirmed_level','confirmed_by','confirmed_at','version']; "
        "BEGIN IF current_user = 'glint_api' THEN "
        "IF (NEW.dimensions_json::jsonb - ARRAY['business_impact','urgency','priority']) "
        "IS DISTINCT FROM "
        "(OLD.dimensions_json::jsonb - ARRAY['business_impact','urgency','priority']) "
        "OR (COALESCE(NEW.dimensions_json::jsonb -> 'business_impact', '{}'::jsonb) "
        "- human_keys) IS DISTINCT FROM "
        "(COALESCE(OLD.dimensions_json::jsonb -> 'business_impact', '{}'::jsonb) "
        "- human_keys) "
        "OR (COALESCE(NEW.dimensions_json::jsonb -> 'urgency', '{}'::jsonb) "
        "- human_keys) IS DISTINCT FROM "
        "(COALESCE(OLD.dimensions_json::jsonb -> 'urgency', '{}'::jsonb) "
        "- human_keys) THEN "
        "RAISE EXCEPTION 'glint_api cannot mutate detector-owned Signal dimensions' "
        "USING ERRCODE = '42501'; END IF; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION glint_guard_api_signal_dimensions() "
        "FROM PUBLIC, glint_api, glint_worker"
    )
    op.execute("DROP TRIGGER IF EXISTS glint_guard_api_signal_dimensions ON signals")
    op.execute(
        "CREATE TRIGGER glint_guard_api_signal_dimensions BEFORE UPDATE OF "
        "dimensions_json ON signals FOR EACH ROW "
        "EXECUTE FUNCTION glint_guard_api_signal_dimensions()"
    )

    # The existing domain repositories append five operational audit actions
    # inside the same transaction.  Give INSERT only and constrain it with a
    # role-specific RLS allowlist; arbitrary audit rows remain impossible.
    op.execute('GRANT INSERT ON TABLE "audit_logs" TO glint_worker')
    op.execute('DROP POLICY IF EXISTS "audit_logs_workspace_scope" ON "audit_logs"')
    op.execute(
        'CREATE POLICY "audit_logs_api_workspace_scope" ON "audit_logs" '
        "TO glint_api USING (workspace_id::text = current_setting('app.workspace_id', true)) "
        "WITH CHECK (workspace_id::text = current_setting('app.workspace_id', true))"
    )
    action_values = ", ".join(
        f"('{action}', '{target_type}')" for action, target_type in WORKER_AUDIT_ACTIONS
    )
    op.execute(
        'CREATE POLICY "audit_logs_worker_operational_insert" ON "audit_logs" '
        "FOR INSERT TO glint_worker WITH CHECK ("
        "workspace_id::text = current_setting('app.workspace_id', true) "
        f"AND (action, target_type) IN ({action_values}))"
    )


def downgrade() -> None:
    # Do not let Alembic move the revision marker back while leaving the split
    # privileges in place. Recombining runtime identities is an explicit
    # deployment migration, never an automatic downgrade.
    raise RuntimeError("The runtime-role split is a forward-only security migration")
