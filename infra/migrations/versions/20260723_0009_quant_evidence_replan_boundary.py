"""Add an external P18 evidence-replan migration boundary.

Revision ID: 20260723_0009
Revises: 20260723_0008
"""

from alembic import op
from sqlalchemy import Column, String, inspect, text

revision = "20260723_0009"
down_revision = "20260723_0008"
branch_labels = None
depends_on = None

LEGACY_MARKER = "legacy-pre-p18"


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("quant_repository_states")}
    if "evidence_replan_contract_marker" not in columns:
        op.add_column(
            "quant_repository_states",
            Column(
                "evidence_replan_contract_marker",
                String(64),
                nullable=False,
                server_default=text(f"'{LEGACY_MARKER}'"),
            ),
        )
    if bind.dialect.name == "postgresql":
        op.execute(
            "GRANT UPDATE (evidence_replan_contract_marker) "
            'ON TABLE "quant_repository_states" TO glint_worker'
        )


def downgrade() -> None:
    raise RuntimeError("Revision 20260723_0009 is an irreversible P18 evidence-replan boundary.")
