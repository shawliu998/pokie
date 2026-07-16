"""Persist duplicate and origin-independence assignments.

Revision ID: 20260715_0002
Revises: 20260715_0001

The initial migration creates from current metadata for clean installations.  The
existence checks make this revision also upgrade databases that previously ran
the Phase 1 revision before these additive columns were introduced.
"""

from alembic import op
from sqlalchemy import Column, String, inspect

revision = "20260715_0002"
down_revision = "20260715_0001"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set[str]:
    return {str(item["name"]) for item in inspect(op.get_bind()).get_columns(table)}


def _index_names(table: str) -> set[str]:
    return {str(item["name"]) for item in inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "independence_group_id" not in _column_names("content_items"):
        op.add_column("content_items", Column("independence_group_id", String(36), nullable=True))
    if "ix_content_items_duplicate_cluster_id" not in _index_names("content_items"):
        op.create_index(
            "ix_content_items_duplicate_cluster_id",
            "content_items",
            ["duplicate_cluster_id"],
        )
    if "ix_content_items_independence_group_id" not in _index_names("content_items"):
        op.create_index(
            "ix_content_items_independence_group_id",
            "content_items",
            ["independence_group_id"],
        )
    if "independence_group_id" not in _column_names("signal_evidence"):
        op.add_column("signal_evidence", Column("independence_group_id", String(36), nullable=True))
    if "ix_signal_evidence_independence_group_id" not in _index_names("signal_evidence"):
        op.create_index(
            "ix_signal_evidence_independence_group_id",
            "signal_evidence",
            ["independence_group_id"],
        )


def downgrade() -> None:
    # Forward-only additive compatibility revision. The Phase 1 revision creates
    # from current metadata, so destructive downgrade cannot know which revision
    # originally introduced a column without risking data loss.
    pass
