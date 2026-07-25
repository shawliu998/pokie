"""Bind the Quant workspace worker lease to its exact Run identity.

Revision ID: 20260722_0007
Revises: 20260717_0006
"""

from alembic import op
from sqlalchemy import Column, Integer, String, inspect

revision = "20260722_0007"
down_revision = "20260717_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        item["name"] for item in inspect(bind).get_columns("quant_repository_states")
    }
    additions = (
        ("worker_lease_run_id", Column("worker_lease_run_id", String(36), nullable=True)),
        (
            "worker_lease_worker_id",
            Column("worker_lease_worker_id", String(96), nullable=True),
        ),
        (
            "worker_lease_attempt_number",
            Column("worker_lease_attempt_number", Integer(), nullable=True),
        ),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("quant_repository_states", column)

    if bind.dialect.name == "postgresql":
        op.execute(
            'GRANT UPDATE (worker_lease_run_id, worker_lease_worker_id, '
            'worker_lease_attempt_number) ON TABLE "quant_repository_states" TO glint_worker'
        )


def downgrade() -> None:
    # Lease ownership columns are retained so an active fence is never made ambiguous.
    pass
