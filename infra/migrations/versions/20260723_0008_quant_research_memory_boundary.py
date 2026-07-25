"""Add an external Research Memory migration boundary.

Revision ID: 20260723_0008
Revises: 20260722_0007
"""

from alembic import op
from sqlalchemy import Column, String, inspect, text

revision = "20260723_0008"
down_revision = "20260722_0007"
branch_labels = None
depends_on = None

CURRENT_VERSION = "quant-research-memory-v1"
LEGACY_VERSION = "legacy-pre-p17"


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("quant_repository_states")}
    if "research_memory_contract_version" not in columns:
        op.add_column(
            "quant_repository_states",
            Column(
                "research_memory_contract_version",
                String(64),
                nullable=False,
                server_default=text(f"'{CURRENT_VERSION}'"),
            ),
        )
        # Rows that existed before this migration are the only records allowed
        # through the one-time legacy materialization path. New rows retain the
        # current server default.
        op.execute(
            text(
                "UPDATE quant_repository_states "
                "SET research_memory_contract_version = :legacy_version"
            ).bindparams(legacy_version=LEGACY_VERSION)
        )

    if bind.dialect.name == "postgresql":
        op.execute(
            "GRANT UPDATE (research_memory_contract_version) "
            'ON TABLE "quant_repository_states" TO glint_worker'
        )


def downgrade() -> None:
    # The external boundary is retained so current state cannot be downgraded
    # into the permissive legacy parser by deleting fields inside state_json.
    raise RuntimeError(
        "Revision 20260723_0008 is an irreversible Research Memory contract boundary."
    )
