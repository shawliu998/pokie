"""Add an external P19 structured-research-decision migration boundary.

Revision ID: 20260723_0010
Revises: 20260723_0009
"""

from alembic import op
from sqlalchemy import Column, String, inspect, text

revision = "20260723_0010"
down_revision = "20260723_0009"
branch_labels = None
depends_on = None

LEGACY_MARKER = "legacy-pre-p19"


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("quant_repository_states")}
    if "research_decision_contract_marker" not in columns:
        op.add_column(
            "quant_repository_states",
            Column(
                "research_decision_contract_marker",
                String(64),
                nullable=False,
                server_default=text(f"'{LEGACY_MARKER}'"),
            ),
        )
    if bind.dialect.name == "postgresql":
        op.execute(
            "GRANT UPDATE (research_decision_contract_marker) "
            'ON TABLE "quant_repository_states" TO glint_worker'
        )


def downgrade() -> None:
    raise RuntimeError("Revision 20260723_0010 is an irreversible P19 research-decision boundary.")
