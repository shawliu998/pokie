from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts import seed_runtime
from services.worker.app.contracts import (
    DataAuthenticity,
    ImportSession,
    ResearchRun,
    ResearchRunState,
)
from services.worker.app.pipelines.csv_import import normalize_csv_import
from services.worker.app.pipelines.dedupe import deduplicate_versions
from services.worker.app.pipelines.research import DeterministicResearchRunner
from services.worker.app.storage import InMemoryDomainAdapter

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "demo"


def _demo_versions():
    profile = seed_runtime.DEMO_PROFILE
    session = ImportSession(
        id="demo-import",
        workspace_id="demo-workspace",
        source_connection_id="demo-source",
        expected_source_row_version=1,
        expected_current_import_manifest_id=None,
        local_manifest_digest=seed_runtime.digest(profile.csv_body),
        file_digest=seed_runtime.digest(profile.csv_body),
        expected_upload_digest=seed_runtime.digest(profile.csv_body),
        client_file_name=profile.csv_file_name,
        file_size_bytes=len(profile.csv_body),
        media_type="text/csv",
        parser_version="csv-v1",
        schema_version=profile.csv_schema_version,
        selected_scope_json={"columns": list(profile.csv_columns)},
        selected_scope_digest=seed_runtime.digest(",".join(profile.csv_columns).encode()),
    )
    _, _, versions, _ = normalize_csv_import(session, profile.csv_body)
    return versions


def test_demo_profile_is_explicitly_imported_and_keeps_acceptance_defaults() -> None:
    profile = seed_runtime.DEMO_PROFILE
    assert seed_runtime.SEED_PROFILES["acceptance"] is seed_runtime.ACCEPTANCE_PROFILE
    assert seed_runtime.ACCEPTANCE_PROFILE.workspace_name is None
    assert seed_runtime.ACCEPTANCE_PROFILE.project_name == "P1 Acceptance"
    assert profile.workspace_name == "Glint Demo"
    assert profile.project_name == profile.watchlist_name == "AI Coding Agents"
    assert set(profile.entities) == {"Cursor", "Claude Code", "Codex", "Windsurf", "Zed"}
    assert set(profile.topics) == {
        "Permissions",
        "Pricing",
        "Reliability",
        "Context",
        "Enterprise",
        "Migration",
        "Integrations",
    }
    manifest = json.loads((FIXTURE_ROOT / "ai-coding-agents-manifest.json").read_text())
    assert manifest["authenticity"] == "Imported Demo Fixture"
    assert manifest["captured_fixture"] is False
    assert "does not call these URLs" in manifest["source_catalog_policy"]


def test_demo_fixture_runs_through_normalization_dedupe_and_research_stance_rules() -> None:
    versions = _demo_versions()
    assert len(versions) == 3
    assert all(version.data_authenticity is DataAuthenticity.IMPORTED for version in versions)
    dedupe = deduplicate_versions(versions)
    assert len(dedupe.assignments) == 3
    assert len({row.independence_group_id for row in dedupe.assignments.values()}) == 3

    domain = InMemoryDomainAdapter()
    run_id = str(uuid4())
    run = ResearchRun(
        id=run_id,
        workspace_id=str(uuid4()),
        investigation_id=str(uuid4()),
        investigation_scope_version_id=str(uuid4()),
        state=ResearchRunState.QUEUED,
        graph_version="deterministic-import-v1",
        run_input_manifest_digest="sha256:demo",
        source_manifest_id=str(uuid4()),
        content_version_ids=tuple(version.id for version in versions),
        data_authenticity=DataAuthenticity.IMPORTED,
    )
    domain.research_runs[run.id] = run
    domain.content_versions.update({version.id: version for version in versions})
    result = DeterministicResearchRunner(domain).run(run.id, versions)
    stances = [evidence.stance for evidence in result.evidence]
    assert stances.count("supports") >= 2
    assert stances.count("opposes") >= 1
    assert result.claims[0].confidence_inputs["opposition_count"] >= 1


def test_demo_artifact_schema_rejects_content_or_secret_fields(tmp_path: Path) -> None:
    artifact = {
        "profile": "demo",
        "fixture_kind": "imported_demo_fixture",
        "data_authenticity": "imported",
        "workspace_id": "workspace-id",
        "workspace_status": "active",
        "project_id": "project-id",
        "watchlist_id": "watchlist-id",
        "watchlist_status": "active",
        "source_ids": ["source-id"],
        "import_job_id": "job-id",
        "import_manifest_id": "manifest-id",
        "signal_id": "signal-id",
        "signal_status": "triaged",
        "investigation_id": "investigation-id",
        "research_run_id": "run-id",
        "research_run_status": "completed",
        "evidence_counts": {"supports": 2, "opposes": 1},
        "evidence_review_count": 3,
        "claim_id": "claim-id",
        "claim_status": "verified",
        "synthesis_id": "synthesis-id",
        "synthesis_status": "verified",
        "decision_brief_id": "brief-id",
        "decision_brief_version_id": "brief-version-id",
        "decision_brief_status": "decision_ready",
        "export_id": "export-id",
        "export_status": "terminal",
        "export_reference_digest": f"sha256:{'a' * 64}",
        "export_output_digest": f"sha256:{'b' * 64}",
        "rendered_markdown_digest": f"sha256:{'b' * 64}",
    }
    destination = tmp_path / "demo.json"
    seed_runtime.write_demo_artifact(str(destination), artifact)
    assert json.loads(destination.read_text()) == artifact

    artifact["rendered_content"] = "must never enter the artifact"
    with pytest.raises(seed_runtime.SeedError, match="reviewed"):
        seed_runtime.validate_demo_artifact(artifact)
