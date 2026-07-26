"""Add the workspace-scoped simulation-only Paper Trading boundary.

Revision ID: 20260725_0011
Revises: 20260723_0010
"""

from alembic import op
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    inspect,
    text,
)

revision = "20260725_0011"
down_revision = "20260723_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "paper_trading_states" not in inspect(bind).get_table_names():
        op.create_table(
            "paper_trading_states",
            Column("workspace_id", String(36), ForeignKey("workspaces.id"), primary_key=True),
            Column(
                "contract_version",
                String(64),
                nullable=False,
                server_default=text("'qurio-paper-v1'"),
            ),
            Column("state_json", JSON(), nullable=False),
            Column("row_version", Integer(), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )

    if bind.dialect.name != "postgresql":
        return
    op.execute('GRANT SELECT, INSERT, UPDATE ON TABLE "paper_trading_states" TO glint_api')
    op.execute('ALTER TABLE "paper_trading_states" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "paper_trading_states" FORCE ROW LEVEL SECURITY')
    exists = bind.execute(
        text(
            "SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
            "AND tablename = 'paper_trading_states' "
            "AND policyname = 'paper_trading_states_workspace_scope'"
        )
    ).scalar()
    if exists is None:
        op.execute(
            'CREATE POLICY "paper_trading_states_workspace_scope" '
            'ON "paper_trading_states" '
            "USING (workspace_id::text = current_setting('app.workspace_id', true)) "
            "WITH CHECK (workspace_id::text = current_setting('app.workspace_id', true))"
        )


def downgrade() -> None:
    raise RuntimeError("Revision 20260725_0011 retains Paper Trading history and is irreversible.")
