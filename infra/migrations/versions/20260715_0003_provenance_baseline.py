"""Persist source availability and ClaimVersion provenance/confidence.

Revision ID: 20260715_0003
Revises: 20260715_0002

All columns are additive on existing workspace-scoped tables, so the RLS
policies installed by 0001 continue to apply without replacement.
"""

from alembic import op
from sqlalchemy import JSON, Column, DateTime, Float, String, Text, inspect, text

revision = "20260715_0003"
down_revision = "20260715_0002"
branch_labels = None
depends_on = None

_LEGACY_DIGEST = "sha256:" + "0" * 64


def _column_names(table: str) -> set[str]:
    return {str(item["name"]) for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    content_columns = _column_names("content_versions")
    availability_added = "availability" not in content_columns
    if availability_added:
        op.add_column(
            "content_versions",
            Column("availability", String(24), nullable=False, server_default="captured"),
        )
    if "availability_last_checked_at" not in content_columns:
        op.add_column(
            "content_versions",
            Column("availability_last_checked_at", DateTime(timezone=True), nullable=True),
        )
        op.execute(
            text(
                "UPDATE content_versions "
                "SET availability_last_checked_at = captured_at "
                "WHERE availability_last_checked_at IS NULL"
            )
        )
        if dialect == "sqlite":
            with op.batch_alter_table("content_versions") as batch:
                batch.alter_column("availability_last_checked_at", nullable=False)
        else:
            op.alter_column("content_versions", "availability_last_checked_at", nullable=False)
    # The temporary default is only a legacy-row backfill aid. The frozen head
    # and the ORM intentionally require callers to provide the value.
    if availability_added:
        if dialect == "sqlite":
            with op.batch_alter_table("content_versions") as batch:
                batch.alter_column("availability", server_default=None)
        else:
            op.alter_column("content_versions", "availability", server_default=None)
    if "availability_reason" not in content_columns:
        op.add_column("content_versions", Column("availability_reason", Text(), nullable=True))
    if dialect == "postgresql":
        op.execute(
            "GRANT UPDATE (availability, availability_last_checked_at, "
            "availability_reason) ON TABLE content_versions TO glint_app"
        )

    signal_columns = _column_names("signals")
    disposition_added = "disposition_json" not in signal_columns
    if disposition_added:
        op.add_column(
            "signals",
            Column(
                "disposition_json",
                JSON(),
                nullable=False,
                server_default=text("'{}'"),
            ),
        )
        if dialect == "sqlite":
            with op.batch_alter_table("signals") as batch:
                batch.alter_column("disposition_json", server_default=None)
        else:
            op.alter_column("signals", "disposition_json", server_default=None)

    claim_columns = _column_names("claim_versions")
    additions = (
        ("confidence_score", Column("confidence_score", Float(), nullable=True)),
        (
            "confidence_policy_version",
            Column("confidence_policy_version", String(64), nullable=True),
        ),
        (
            "confidence_input_digest",
            Column("confidence_input_digest", String(96), nullable=True),
        ),
        ("generation_method", Column("generation_method", String(24), nullable=True)),
        ("generator_version", Column("generator_version", String(64), nullable=True)),
        ("suggestion_origin", Column("suggestion_origin", String(32), nullable=True)),
    )
    added_claim_columns: list[str] = []
    for name, column in additions:
        if name not in claim_columns:
            op.add_column("claim_versions", column)
            added_claim_columns.append(name)
    op.execute(
        text(
            "UPDATE claim_versions SET "
            "confidence_score = COALESCE(confidence_score, 0), "
            "confidence_policy_version = COALESCE("
            "confidence_policy_version, 'legacy-unreplayable-v0'), "
            "confidence_input_digest = COALESCE("
            "confidence_input_digest, :legacy_digest), "
            "generation_method = COALESCE(generation_method, CASE "
            "WHEN version_number > 1 THEN 'human' "
            "WHEN model_run_id IS NOT NULL THEN 'model' ELSE 'deterministic' END), "
            "generator_version = COALESCE(generator_version, CASE "
            "WHEN version_number > 1 THEN 'human-claim-revision-legacy' "
            "WHEN model_run_id IS NOT NULL THEN 'model-run-legacy' "
            "ELSE 'deterministic-research-legacy' END), "
            "suggestion_origin = COALESCE(suggestion_origin, CASE "
            "WHEN version_number > 1 THEN 'none' "
            "WHEN model_run_id IS NOT NULL THEN 'model' ELSE 'deterministic_rule' END)"
        ).bindparams(legacy_digest=_LEGACY_DIGEST)
    )
    if dialect == "sqlite" and added_claim_columns:
        with op.batch_alter_table("claim_versions") as batch:
            for name in added_claim_columns:
                batch.alter_column(name, nullable=False)
    else:
        for name in added_claim_columns:
            op.alter_column("claim_versions", name, nullable=False)


def downgrade() -> None:
    # Forward-only additive provenance. Dropping availability or confidence
    # columns would make immutable historical versions less replayable.
    pass
