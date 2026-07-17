"""Add durable workspace-scoped PokieQuant Phase 0 repository state.

Revision ID: 20260717_0006
Revises: 20260715_0005
"""

from alembic import op
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, inspect, text

revision = "20260717_0006"
down_revision = "20260715_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "quant_repository_states" not in inspect(bind).get_table_names():
        op.create_table(
            "quant_repository_states",
            Column("workspace_id", String(36), ForeignKey("workspaces.id"), primary_key=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("row_version", Integer(), nullable=False),
            Column("data_authenticity", String(24), nullable=False),
            Column("state_json", JSON(), nullable=False),
            Column("fixture_state", String(48), nullable=True),
            Column("fixture_input_json", JSON(), nullable=False),
            Column("fixture_row_version", Integer(), nullable=False),
            Column("worker_lease_token", String(96), nullable=True),
            Column("worker_lease_expires_at", DateTime(timezone=True), nullable=True),
            Column("worker_heartbeat_at", DateTime(timezone=True), nullable=True),
            Column("worker_fencing_version", Integer(), nullable=False),
        )

    if bind.dialect.name != "postgresql":
        return
    op.execute(
        'GRANT SELECT, INSERT, UPDATE ON TABLE "quant_repository_states" TO glint_api'
    )
    op.execute(
        'GRANT SELECT, UPDATE (state_json, updated_at, row_version, worker_lease_token, '
        'worker_lease_expires_at, worker_heartbeat_at, worker_fencing_version) '
        'ON TABLE "quant_repository_states" TO glint_worker'
    )
    op.execute('ALTER TABLE "quant_repository_states" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "quant_repository_states" FORCE ROW LEVEL SECURITY')
    exists = bind.execute(
        text(
            "SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
            "AND tablename = 'quant_repository_states' "
            "AND policyname = 'quant_repository_states_workspace_scope'"
        )
    ).scalar()
    if exists is None:
        op.execute(
            'CREATE POLICY "quant_repository_states_workspace_scope" '
            'ON "quant_repository_states" '
            "USING (workspace_id::text = current_setting('app.workspace_id', true)) "
            "WITH CHECK (workspace_id::text = current_setting('app.workspace_id', true))"
        )


def downgrade() -> None:
    # Phase 0 state is audit/recovery evidence and is intentionally retained.
    pass
