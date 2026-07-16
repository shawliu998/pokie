"""Add durable, workspace-scoped cloud source validation jobs.

Revision ID: 20260715_0004
Revises: 20260715_0003
"""

from alembic import op
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
    text,
)

revision = "20260715_0004"
down_revision = "20260715_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "source_validation_jobs" not in inspect(bind).get_table_names():
        op.create_table(
            "source_validation_jobs",
            Column("id", String(36), primary_key=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("data_authenticity", String(24), nullable=False),
            Column("workspace_id", String(36), ForeignKey("workspaces.id"), nullable=False),
            Column(
                "source_connection_id",
                String(36),
                ForeignKey("source_connections.id"),
                nullable=False,
            ),
            Column("command", String(24), nullable=False),
            Column("state", String(24), nullable=False, server_default="queued"),
            Column("expected_source_row_version", Integer(), nullable=False),
            Column("actor_id", String(36), nullable=False),
            Column("request_id", String(64), nullable=False),
            Column("idempotency_key", String(36), nullable=False),
            Column("attempt", Integer(), nullable=False, server_default="0"),
            Column("lease_owner_token", String(96), nullable=True),
            Column("lease_expires_at", DateTime(timezone=True), nullable=True),
            Column("heartbeat_at", DateTime(timezone=True), nullable=True),
            Column("fencing_version", Integer(), nullable=False, server_default="0"),
            Column("result_source_status", String(32), nullable=True),
            Column("failure_code", String(80), nullable=True),
            Column("failure_reason", Text(), nullable=True),
            CheckConstraint(
                "command IN ('health_check', 'reconnect')",
                name="source_validation_command_closed",
            ),
            CheckConstraint(
                "state IN ('queued', 'claimed', 'completed', 'failed')",
                name="source_validation_state_closed",
            ),
            UniqueConstraint(
                "workspace_id", "idempotency_key", name="uq_source_validation_idempotency"
            ),
        )
        # Temporary defaults make the compatibility DDL safe to stage. Runtime
        # writes are explicit, and the frozen head/ORM have no server defaults.
        transient_defaults = ("state", "attempt", "fencing_version")
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("source_validation_jobs") as batch:
                for column_name in transient_defaults:
                    batch.alter_column(column_name, server_default=None)
        else:
            for column_name in transient_defaults:
                op.alter_column("source_validation_jobs", column_name, server_default=None)
        op.create_index(
            "ix_source_validation_jobs_workspace_id",
            "source_validation_jobs",
            ["workspace_id"],
        )
        op.create_index(
            "ix_source_validation_jobs_source_connection_id",
            "source_validation_jobs",
            ["source_connection_id"],
        )
        op.create_index("ix_source_validation_jobs_state", "source_validation_jobs", ["state"])
        op.create_index(
            "uq_active_source_validation_job",
            "source_validation_jobs",
            ["workspace_id", "source_connection_id"],
            unique=True,
            sqlite_where=text("state IN ('queued','claimed')"),
            postgresql_where=text("state IN ('queued','claimed')"),
        )

    if bind.dialect.name != "postgresql":
        return
    op.execute(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "source_validation_jobs" TO glint_app'
    )
    op.execute('ALTER TABLE "source_validation_jobs" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "source_validation_jobs" FORCE ROW LEVEL SECURITY')
    policy_exists = bind.execute(
        text(
            "SELECT 1 FROM pg_policies "
            "WHERE schemaname = current_schema() "
            "AND tablename = 'source_validation_jobs' "
            "AND policyname = 'source_validation_jobs_workspace_scope'"
        )
    ).scalar()
    if policy_exists is None:
        op.execute(
            'CREATE POLICY "source_validation_jobs_workspace_scope" '
            'ON "source_validation_jobs" '
            "USING (workspace_id::text = current_setting('app.workspace_id', true)) "
            "WITH CHECK (workspace_id::text = current_setting('app.workspace_id', true))"
        )


def downgrade() -> None:
    # Durable command history is operational audit evidence and is intentionally retained.
    pass
