# pyright: reportMissingParameterType=false, reportOptionalMemberAccess=false, reportUnknownParameterType=false
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from connectors.factory import EnvironmentSecretResolver, SourceConnectorFactory
from connectors.shared.contracts import (
    ConnectorCapabilities,
    ConnectorHealth,
    ConnectorInvalidCredential,
    ConnectorStatus,
    FetchResult,
    SearchPage,
)
from connectors.shared.contracts import (
    RawContentItem as ConnectorRawContentItem,
)
from connectors.shared.fixture_transport import FixtureTransport
from services.api.app.api import presenters
from services.api.app.db.models import (
    Base,
    CollectionRun,
    CollectionSchedule,
    ContentItem,
    ContentVersion,
    Evidence,
    Investigation,
    InvestigationScopeVersion,
    Project,
    RawContentItem,
    SignalEvidence,
    SourceConnection,
    SourceValidationJobRecord,
    Watchlist,
    Workspace,
)
from services.api.app.db.models import (
    Signal as DbSignal,
)
from services.api.app.modules.common import text_digest
from services.api.app.modules.sources.validation import SourceValidationJobRepository
from services.worker.app.contracts import (
    CollectionLeaseContext,
    DataAuthenticity,
    NonTerminalImportError,
    SourceHealthStatus,
)
from services.worker.app.contracts import (
    RawContentItem as WorkerRawContentItem,
)
from services.worker.app.contracts import (
    Signal as WorkerSignal,
)
from services.worker.app.contracts import (
    SourceConnection as WorkerSourceConnection,
)
from services.worker.app.jobs.collection import CollectionCommand, ConnectorCollectionJob
from services.worker.app.main import run_once
from services.worker.app.repositories.sqlalchemy_adapter import (
    ProductionAdapterError,
    SQLAlchemyWorkerDomainAdapter,
    create_object_store,
)
from services.worker.app.schedules.scheduler import RepositoryCollectionScheduler
from services.worker.app.storage import InMemoryDomainAdapter

WORKSPACE = "22222222-2222-5222-8222-222222222222"
SOURCE = "33333333-3333-5333-8333-333333333333"
SECOND_SOURCE = "33333333-3333-5333-8333-333333333334"
THIRD_SOURCE = "33333333-3333-5333-8333-333333333335"
WATCHLIST = "44444444-4444-5444-8444-444444444444"
PROJECT = "55555555-5555-5555-8555-555555555555"
NOW = datetime(2026, 7, 15, 6, tzinfo=UTC)


class FakeObjectStore:
    def get_object(self, key: str):  # pragma: no cover - not needed by this test
        raise AssertionError(key)

    def quarantine(
        self, key: str, reason: str
    ) -> None:  # pragma: no cover - not needed by this test
        raise AssertionError((key, reason))

    def put_json(self, key: str, payload: dict[str, object]) -> str:
        return f"object://{key}"


def test_production_adapter_uses_api_collection_schedule_repository_with_fencing() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with Session() as db:
        db.add(Workspace(id=WORKSPACE, name="Test", created_by="owner", data_authenticity="seed"))
        db.add(
            Project(
                id=PROJECT,
                workspace_id=WORKSPACE,
                name="Project",
                status="active",
                created_by="owner",
                data_authenticity="seed",
            )
        )
        db.add(
            SourceConnection(
                id=SOURCE,
                workspace_id=WORKSPACE,
                name="GitHub",
                source_kind="cloud",
                runtime="cloud",
                connector_type="github",
                connector_version="v1",
                status="healthy",
                credential_ref="github-token",
                approved_by="owner",
                data_authenticity="seed",
            )
        )
        db.add(
            Watchlist(
                id=WATCHLIST,
                workspace_id=WORKSPACE,
                project_id=PROJECT,
                name="Permission",
                objective="Track permission friction",
                status="active",
                rules_json={"source_connection_ids": [SOURCE]},
                owner_id="owner",
                data_authenticity="seed",
            )
        )
        db.add(
            CollectionSchedule(
                id="66666666-6666-5666-8666-666666666666",
                workspace_id=WORKSPACE,
                source_connection_id=SOURCE,
                watchlist_id=WATCHLIST,
                query_json={"query": "permission", "owner": "acme", "repo": "glint"},
                cadence_seconds=3600,
                timezone="UTC",
                misfire_policy="run_once",
                catch_up=False,
                overlap_policy="forbid",
                next_run_at=NOW,
                enabled=True,
                data_authenticity="seed",
            )
        )
        db.commit()

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    claim = adapter.claim_due_collection_schedule("worker-a", NOW, timedelta(seconds=120))
    assert claim is not None
    assert claim.command.collection_key
    assert claim.command.scheduled_for == NOW
    assert claim.command.connector_config["owner"] == "acme"

    with Session() as db:
        row = db.get(CollectionSchedule, claim.schedule_id)
        assert row.lease_owner_token == text_digest(claim.lease_token)
        assert row.lease_fencing_version == 1
        assert row.lease_attempt == 1

    adapter.heartbeat_collection_schedule(
        claim.schedule_id, claim.lease_token, NOW + timedelta(seconds=10), timedelta(seconds=120)
    )
    adapter.complete_collection_schedule(
        claim.schedule_id,
        claim.lease_token,
        True,
        NOW + timedelta(hours=1),
        NOW + timedelta(seconds=10),
    )
    with Session() as db:
        row = db.get(CollectionSchedule, claim.schedule_id)
        assert row.lease_owner_token is None
        assert row.next_run_at == NOW + timedelta(hours=1)


def test_collection_command_uses_watchlist_rules_and_adjacent_windows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    with Session() as db:
        watchlist = db.get(Watchlist, WATCHLIST)
        watchlist.rules_json = {
            "source_connection_ids": [SOURCE],
            "rules": {
                "schema_version": "watchlist-rules-v1",
                "entities": ["billing"],
                "topics": ["oauth"],
                "query_rules": {
                    "include_terms": ["consent", "outage"],
                    "exclude_terms": ["benign"],
                    "languages": ["en"],
                    "regions": ["us"],
                },
                "cadence": "daily",
                "current_window_days": 14,
                "baseline_window_days": 28,
                "notification_intent": False,
            },
        }
        schedule = db.query(CollectionSchedule).one()
        schedule.query_json = {"query": "legacy", "owner": "acme", "repo": "glint"}
        db.commit()

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    claim = adapter.claim_due_collection_schedule("worker-a", NOW, timedelta(seconds=120))
    assert claim is not None
    assert claim.command.terms == ("consent", "outage", "billing", "oauth")
    assert claim.command.exclude_terms == ("benign",)
    assert claim.command.languages == ("en",)
    assert claim.command.regions == ("us",)
    assert "legacy" not in claim.command.query
    assert "consent" in claim.command.query
    assert "-benign" in claim.command.query
    assert "language:en" in claim.command.query
    assert claim.command.current_window == (NOW - timedelta(days=14), NOW)
    assert claim.command.baseline_window == (NOW - timedelta(days=42), NOW - timedelta(days=14))


def test_signal_candidate_query_filters_event_time_in_sql() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    claim = adapter.claim_due_collection_schedule("worker-a", NOW, timedelta(seconds=120))
    assert claim is not None
    _extend_schedule_lease(Session, claim)
    run_id = adapter.begin_collection_run(
        WORKSPACE,
        SOURCE,
        claim.command.collection_key,
        _collection_run_metadata(claim),
    )
    lease = CollectionLeaseContext(
        collection_run_id=run_id,
        schedule_id=claim.schedule_id,
        schedule_lease_token=claim.lease_token,
        schedule_fencing_version=claim.command.schedule_fencing_version,
    )
    adapter.upsert_collected_raw_items(
        WORKSPACE,
        SOURCE,
        [
            WorkerRawContentItem(
                id="raw-inside",
                workspace_id=WORKSPACE,
                source_connection_id=SOURCE,
                source_item_id="inside",
                title="Permission outage",
                body="Permission outage increased.",
                canonical_url="https://example.test/inside",
                author="inside-author",
                published_at=NOW - timedelta(hours=1),
                captured_at=NOW - timedelta(hours=1),
                content_digest="sha256:inside",
                data_authenticity=DataAuthenticity.COLLECTED,
                metadata={"raw_digest": "sha256:raw-inside", "connector_type": "github"},
            ),
            WorkerRawContentItem(
                id="raw-outside",
                workspace_id=WORKSPACE,
                source_connection_id=SOURCE,
                source_item_id="outside",
                title="Permission outage old",
                body="Permission outage old item.",
                canonical_url="https://example.test/outside",
                author="outside-author",
                published_at=NOW - timedelta(days=30),
                captured_at=NOW - timedelta(hours=1),
                content_digest="sha256:outside",
                data_authenticity=DataAuthenticity.COLLECTED,
                metadata={"raw_digest": "sha256:raw-outside", "connector_type": "github"},
            ),
        ],
        claim.command.collection_key,
        lease,
    )

    candidates = adapter.get_signal_candidate_versions(
        WORKSPACE,
        WATCHLIST,
        ("permission",),
        claim.command.current_window,
        claim.command.baseline_window,
        claim.command.collection_key,
        lease,
    )
    assert [candidate.metadata["source_item_id"] for candidate in candidates] == ["inside"]


def test_collection_adapter_fences_business_writes_and_replays_raw() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    claim = adapter.claim_due_collection_schedule("worker-a", NOW, timedelta(seconds=120))
    assert claim is not None
    run_id = adapter.begin_collection_run(
        WORKSPACE,
        SOURCE,
        claim.command.collection_key,
        {
            "watchlist_id": WATCHLIST,
            "scheduled_for": claim.command.scheduled_for.isoformat(),
            "schedule_id": claim.schedule_id,
            "schedule_lease_token": claim.lease_token,
            "schedule_fencing_version": claim.command.schedule_fencing_version,
            "lease_checked_at": NOW.isoformat(),
            "attempt": claim.command.schedule_attempt,
            "cadence": "manual",
            "timezone": "UTC",
            "current_start": NOW.isoformat(),
            "current_end": (NOW + timedelta(hours=1)).isoformat(),
        },
    )
    lease = CollectionLeaseContext(
        collection_run_id=run_id,
        schedule_id=claim.schedule_id,
        schedule_lease_token=claim.lease_token,
        schedule_fencing_version=claim.command.schedule_fencing_version,
    )
    raw = WorkerRawContentItem(
        id="raw-1",
        workspace_id=WORKSPACE,
        source_connection_id=SOURCE,
        source_item_id="item-1",
        title="Permission problem",
        body="Permission issue blocks onboarding.",
        canonical_url="https://example.test/item-1",
        author="author",
        published_at=NOW - timedelta(minutes=5),
        captured_at=NOW,
        content_digest="sha256:content-1",
        data_authenticity=DataAuthenticity.COLLECTED,
        metadata={"raw_digest": "sha256:raw-1", "connector_type": "github"},
    )
    with Session() as db:
        schedule = db.get(CollectionSchedule, claim.schedule_id)
        schedule.lease_expires_at = datetime.now(tz=UTC) + timedelta(seconds=120)
        db.commit()
    first = adapter.upsert_collected_raw_items(
        WORKSPACE, SOURCE, [raw], claim.command.collection_key, lease
    )
    second = adapter.upsert_collected_raw_items(
        WORKSPACE, SOURCE, [raw], claim.command.collection_key, lease
    )
    assert [item.id for item in first] == [item.id for item in second]
    with Session() as db:
        assert len(db.query(RawContentItem).all()) == 1
        assert len(db.query(ContentVersion).all()) == 1
        version = db.query(ContentVersion).one()
        assert version.metadata_json["published_at"] == raw.published_at.isoformat()
        assert version.metadata_json["author"] == raw.author
        assert version.metadata_json["source_connection_id"] == SOURCE

    adapter.update_source_health(
        SOURCE,
        SourceHealthStatus.RATE_LIMITED,
        {
            "freshness_state": "stale",
            "error": "rate_limited",
            "collection_key": claim.command.collection_key,
        },
        lease,
    )
    with Session() as db:
        source = db.get(SourceConnection, SOURCE)
        assert source.status == "degraded"
        assert source.health_state == "rate_limited"
        assert source.health_error_code == "rate_limited"

    with Session() as db:
        schedule = db.get(CollectionSchedule, claim.schedule_id)
        schedule.lease_expires_at = NOW - timedelta(seconds=1)
        db.commit()
    with pytest.raises(ProductionAdapterError, match="expired"):
        adapter.complete_collection_run(
            lease,
            "succeeded",
            {"fetched": 1, "created": 1, "updated": 0, "skipped": 0, "failed": 0},
            {"state": "current"},
        )


def test_schedule_to_collection_to_signal_integration_dedupes_repeated_signal() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)

    first_claim = scheduler.claim_one(NOW)
    assert first_claim is not None
    with Session() as db:
        schedule = db.get(CollectionSchedule, first_claim.schedule_id)
        schedule.lease_expires_at = datetime.now(tz=UTC) + timedelta(seconds=120)
        db.commit()
    first_result = ConnectorCollectionJob(
        adapter,
        _SignalFixtureConnector(NOW),
        heartbeat=lambda now: scheduler.heartbeat(
            first_claim.schedule_id, first_claim.lease_token, now
        ),
    ).run(first_claim.command)
    assert first_result.state == "succeeded"
    scheduler.complete(
        first_claim.schedule_id,
        first_claim.lease_token,
        True,
        NOW + timedelta(hours=1),
        datetime.now(tz=UTC),
    )

    with Session() as db:
        assert db.query(CollectionRun).count() == 1
        assert db.query(RawContentItem).count() == 3
        assert db.query(ContentVersion).count() == 3
        signal = db.query(DbSignal).one()
        assert signal.metrics_json["independent_source_count"] == 3
        assert signal.metrics_json["origin_independent_source_count"] == 3
        assert signal.metrics_json["duplicate_cluster_count"] == 3
        dedupe_assignments = signal.dimensions_json["dedupe_assignments"]
        assert dedupe_assignments
        assert all(item["independence_group_id"] for item in dedupe_assignments.values())
        assert {item.duplicate_cluster_id for item in db.query(ContentItem).all()}
        assert {row.independence_group_id for row in db.query(SignalEvidence).all()} == {
            item["independence_group_id"] for item in dedupe_assignments.values()
        }

    with Session() as db:
        schedule = db.get(CollectionSchedule, first_claim.schedule_id)
        schedule.next_run_at = NOW + timedelta(hours=1)
        db.commit()
    second_claim = scheduler.claim_one(NOW + timedelta(hours=1, seconds=1))
    assert second_claim is not None
    with Session() as db:
        schedule = db.get(CollectionSchedule, second_claim.schedule_id)
        schedule.lease_expires_at = datetime.now(tz=UTC) + timedelta(seconds=120)
        db.commit()
    second_result = ConnectorCollectionJob(
        adapter,
        _SignalFixtureConnector(NOW),
        heartbeat=lambda now: scheduler.heartbeat(
            second_claim.schedule_id, second_claim.lease_token, now
        ),
    ).run(second_claim.command)
    assert second_result.state == "succeeded"
    with Session() as db:
        assert db.query(CollectionRun).count() == 2
        assert db.query(DbSignal).count() == 1


def test_initial_baseline_gate_suppresses_first_run_then_allows_second_source_signal() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    _seed_cross_source_baseline_fixture(Session)
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)

    first_claim = scheduler.claim_one(NOW)
    assert first_claim is not None
    assert first_claim.command.source_connection_id == SOURCE
    _extend_schedule_lease(Session, first_claim)
    first_result = ConnectorCollectionJob(
        adapter,
        _ConfigurableSignalConnector(SOURCE, "github", NOW, item_count=2),
        heartbeat=lambda now: scheduler.heartbeat(
            first_claim.schedule_id, first_claim.lease_token, now
        ),
    ).run(first_claim.command)
    assert first_result.state == "succeeded"
    assert first_result.signal_count == 0
    scheduler.complete(
        first_claim.schedule_id,
        first_claim.lease_token,
        True,
        NOW + timedelta(hours=2),
        datetime.now(tz=UTC),
    )
    with Session() as db:
        assert db.query(DbSignal).count() == 0
        run = db.query(CollectionRun).one()
        assert run.freshness_json["signal_suppressed_reason"] == ("initial_baseline_insufficient")
        assert run.freshness_json["initial_baseline"]["status"] == "insufficient"
        assert run.freshness_json["initial_baseline"]["current_count"] == 2
        assert run.freshness_json["initial_baseline"]["required_count"] == 3
        watchlist = db.get(Watchlist, WATCHLIST)
        assert watchlist is not None
        projected = presenters.watchlist(db, watchlist)["initial_baseline"]
        assert projected["status"] == "insufficient"
        assert projected["current_count"] == 2
        assert projected["required_count"] == 3

    second_claim = scheduler.claim_one(NOW + timedelta(hours=1))
    assert second_claim is not None
    assert second_claim.command.source_connection_id == SECOND_SOURCE
    _extend_schedule_lease(Session, second_claim)
    second_result = ConnectorCollectionJob(
        adapter,
        _ConfigurableSignalConnector(SECOND_SOURCE, "rss", NOW + timedelta(hours=1), item_count=1),
        heartbeat=lambda now: scheduler.heartbeat(
            second_claim.schedule_id, second_claim.lease_token, now
        ),
    ).run(second_claim.command)
    assert second_result.state == "succeeded"
    assert second_result.signal_count == 1
    scheduler.complete(
        second_claim.schedule_id,
        second_claim.lease_token,
        True,
        NOW + timedelta(hours=2),
        datetime.now(tz=UTC),
    )
    with Session() as db:
        signal = db.query(DbSignal).one()
        assert signal.metrics_json["platform_count"] == 2
        assert signal.dimensions_json["source_coverage"]["cross_source_confirmed"] is True
        watchlist = db.get(Watchlist, WATCHLIST)
        assert watchlist is not None
        projected = presenters.watchlist(db, watchlist)["initial_baseline"]
        assert projected["status"] == "ready"
        assert projected["current_count"] == 3
        assert projected["required_count"] == 3


def test_in_memory_initial_baseline_projection_uses_membership_and_persisted_versions() -> None:
    domain = InMemoryDomainAdapter()
    command = CollectionCommand(
        workspace_id=WORKSPACE,
        watchlist_id=WATCHLIST,
        source_connection_id=SOURCE,
        query="permission",
        collection_key="memory-collection-key",
        terms=("permission",),
        current_window=(NOW - timedelta(days=1), NOW),
        baseline_window=(NOW - timedelta(days=8), NOW - timedelta(days=1)),
        scheduled_for=NOW,
        schedule_id="memory-schedule-1",
        schedule_lease_token="memory-token",
        schedule_fencing_version=1,
    )
    for index, source_id in enumerate((SOURCE, SECOND_SOURCE, THIRD_SOURCE), start=1):
        domain.collection_schedules[f"memory-schedule-{index}"] = {
            "enabled": True,
            "next_run_at": NOW,
            "command": replace(
                command,
                source_connection_id=source_id,
                schedule_id=f"memory-schedule-{index}",
            ),
            "lease": {
                "token": "memory-token" if index == 1 else f"other-token-{index}",
                "expires_at": datetime.now(tz=UTC) + timedelta(seconds=120),
            },
        }
    run_id = domain.begin_collection_run(
        WORKSPACE,
        SOURCE,
        command.collection_key,
        {
            "watchlist_id": WATCHLIST,
            "schedule_id": command.schedule_id,
            "schedule_lease_token": command.schedule_lease_token,
            "schedule_fencing_version": command.schedule_fencing_version,
        },
    )
    lease = CollectionLeaseContext(
        collection_run_id=run_id,
        schedule_id=command.schedule_id or "",
        schedule_lease_token=command.schedule_lease_token or "",
        schedule_fencing_version=command.schedule_fencing_version,
    )
    domain.upsert_collected_raw_items(
        WORKSPACE,
        SOURCE,
        [
            WorkerRawContentItem(
                id=f"memory-raw-{index}",
                workspace_id=WORKSPACE,
                source_connection_id=SOURCE,
                source_item_id=f"memory-{index}",
                title=f"Permission memory {index}",
                body="Permission memory baseline candidate.",
                canonical_url=f"https://example.test/memory/{index}",
                author=f"author-{index}",
                published_at=NOW - timedelta(minutes=index),
                captured_at=NOW,
                content_digest=f"sha256:memory-{index}",
                data_authenticity=DataAuthenticity.COLLECTED,
                metadata={
                    "raw_digest": f"sha256:memory-raw-{index}",
                    "connector_type": "github",
                    "source_connection_id": SOURCE,
                },
            )
            for index in range(2)
        ],
        command.collection_key,
        lease,
    )
    projection = domain.get_initial_baseline_projection(
        WORKSPACE, WATCHLIST, command.collection_key, lease, current_candidate_count=2
    )
    assert projection.status == "insufficient"
    assert projection.current_count == 2
    assert projection.required_count == 3
    assert projection.reason == "initial_baseline_insufficient"


def test_dedupe_persistence_does_not_mutate_append_only_content_versions() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    claim = adapter.claim_due_collection_schedule("worker-a", NOW, timedelta(seconds=120))
    assert claim is not None
    run_id = adapter.begin_collection_run(
        WORKSPACE,
        SOURCE,
        claim.command.collection_key,
        {
            "watchlist_id": WATCHLIST,
            "scheduled_for": claim.command.scheduled_for.isoformat(),
            "schedule_id": claim.schedule_id,
            "schedule_lease_token": claim.lease_token,
            "schedule_fencing_version": claim.command.schedule_fencing_version,
            "lease_checked_at": NOW.isoformat(),
            "attempt": claim.command.schedule_attempt,
            "cadence": "manual",
            "timezone": "UTC",
            "current_start": NOW.isoformat(),
            "current_end": (NOW + timedelta(hours=1)).isoformat(),
        },
    )
    lease = CollectionLeaseContext(
        collection_run_id=run_id,
        schedule_id=claim.schedule_id,
        schedule_lease_token=claim.lease_token,
        schedule_fencing_version=claim.command.schedule_fencing_version,
    )
    raw = WorkerRawContentItem(
        id="raw-dedupe-1",
        workspace_id=WORKSPACE,
        source_connection_id=SOURCE,
        source_item_id="item-dedupe-1",
        title="Permission problem",
        body="Permission issue blocks onboarding.",
        canonical_url="https://example.test/item-dedupe-1",
        author="author",
        published_at=NOW - timedelta(minutes=5),
        captured_at=NOW,
        content_digest="sha256:dedupe-content-1",
        data_authenticity=DataAuthenticity.COLLECTED,
        metadata={"raw_digest": "sha256:dedupe-raw-1", "connector_type": "github"},
    )
    with Session() as db:
        schedule = db.get(CollectionSchedule, claim.schedule_id)
        schedule.lease_expires_at = datetime.now(tz=UTC) + timedelta(seconds=120)
        db.commit()
    versions = adapter.upsert_collected_raw_items(
        WORKSPACE, SOURCE, [raw], claim.command.collection_key, lease
    )
    assert versions
    with Session() as db:
        before = [
            {
                "id": row.id,
                "workspace_id": row.workspace_id,
                "content_item_id": row.content_item_id,
                "source_connection_id": row.source_connection_id,
                "raw_content_item_id": row.raw_content_item_id,
                "version_number": row.version_number,
                "content_digest": row.content_digest,
                "normalized_title": row.normalized_title,
                "normalized_body": row.normalized_body,
                "metadata_json": dict(row.metadata_json or {}),
                "captured_at": row.captured_at,
                "raw_snapshot_uri": row.raw_snapshot_uri,
                "parser_version": row.parser_version,
                "data_authenticity": row.data_authenticity,
            }
            for row in db.query(ContentVersion).order_by(ContentVersion.id).all()
        ]
    expected_duplicate_cluster_id = "11111111-1111-5111-8111-111111111111"
    expected_independence_group_id = "22222222-2222-5222-8222-222222222222"
    adapter.persist_dedupe_assignments(
        WORKSPACE,
        {
            str(item["id"]): {
                "duplicate_cluster_id": expected_duplicate_cluster_id,
                "independence_group_id": expected_independence_group_id,
                "duplicate_reason": "test",
            }
            for item in before
        },
        claim.command.collection_key,
        lease,
    )
    with Session() as db:
        after = [
            {
                "id": row.id,
                "workspace_id": row.workspace_id,
                "content_item_id": row.content_item_id,
                "source_connection_id": row.source_connection_id,
                "raw_content_item_id": row.raw_content_item_id,
                "version_number": row.version_number,
                "content_digest": row.content_digest,
                "normalized_title": row.normalized_title,
                "normalized_body": row.normalized_body,
                "metadata_json": dict(row.metadata_json or {}),
                "captured_at": row.captured_at,
                "raw_snapshot_uri": row.raw_snapshot_uri,
                "parser_version": row.parser_version,
                "data_authenticity": row.data_authenticity,
            }
            for row in db.query(ContentVersion).order_by(ContentVersion.id).all()
        ]
        content_items = {
            row.id: {
                "duplicate_cluster_id": row.duplicate_cluster_id,
                "independence_group_id": row.independence_group_id,
            }
            for row in db.query(ContentItem)
            .where(ContentItem.id.in_({str(item["content_item_id"]) for item in before}))
            .all()
        }
    assert after == before
    assert content_items == {
        str(item["content_item_id"]): {
            "duplicate_cluster_id": expected_duplicate_cluster_id,
            "independence_group_id": expected_independence_group_id,
        }
        for item in before
    }


def test_collection_business_writes_reject_stale_attempt_after_reclaim() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)

    first_adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    first_claim = first_adapter.claim_due_collection_schedule(
        "worker-a", NOW, timedelta(seconds=120)
    )
    assert first_claim is not None
    first_run_id = first_adapter.begin_collection_run(
        WORKSPACE,
        SOURCE,
        first_claim.command.collection_key,
        _collection_run_metadata(first_claim),
    )
    stale_lease = CollectionLeaseContext(
        collection_run_id=first_run_id,
        schedule_id=first_claim.schedule_id,
        schedule_lease_token=first_claim.lease_token,
        schedule_fencing_version=first_claim.command.schedule_fencing_version,
    )
    with Session() as db:
        schedule = db.get(CollectionSchedule, first_claim.schedule_id)
        schedule.lease_expires_at = NOW - timedelta(seconds=1)
        db.commit()

    second_adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-b", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    second_claim = second_adapter.claim_due_collection_schedule(
        "worker-b", NOW + timedelta(seconds=121), timedelta(seconds=120)
    )
    assert second_claim is not None
    assert second_claim.lease_token != first_claim.lease_token
    assert (
        second_claim.command.schedule_fencing_version
        != first_claim.command.schedule_fencing_version
    )
    with Session() as db:
        schedule = db.get(CollectionSchedule, second_claim.schedule_id)
        schedule.lease_expires_at = datetime.now(tz=UTC) + timedelta(seconds=120)
        db.commit()

    raw = WorkerRawContentItem(
        id="raw-stale",
        workspace_id=WORKSPACE,
        source_connection_id=SOURCE,
        source_item_id="item-stale",
        title="Permission stale",
        body="Permission stale worker write.",
        canonical_url="https://example.test/stale",
        author="author",
        published_at=NOW,
        captured_at=NOW,
        content_digest="sha256:stale-content",
        data_authenticity=DataAuthenticity.COLLECTED,
        metadata={"raw_digest": "sha256:stale-raw", "connector_type": "github"},
    )
    with pytest.raises(ProductionAdapterError):
        first_adapter.upsert_collected_raw_items(
            WORKSPACE, SOURCE, [raw], first_claim.command.collection_key, stale_lease
        )
    with pytest.raises(ProductionAdapterError):
        first_adapter.update_source_health(
            SOURCE,
            SourceHealthStatus.HEALTHY,
            {"collection_key": first_claim.command.collection_key, "freshness_state": "current"},
            stale_lease,
        )
    with pytest.raises(ProductionAdapterError):
        first_adapter.create_signal(
            WorkerSignal(
                id="stale-signal",
                workspace_id=WORKSPACE,
                watchlist_id=WATCHLIST,
                title="stale",
                detector_version="signal-v1",
                detection_window=(NOW - timedelta(hours=1), NOW),
                baseline_window=(NOW - timedelta(days=7), NOW - timedelta(hours=1)),
                metrics={},
                dimensions={"collection_key": first_claim.command.collection_key},
                explanation="stale",
                content_version_ids=(),
                data_authenticity=DataAuthenticity.COLLECTED,
            ),
            stale_lease,
        )
    with pytest.raises(ProductionAdapterError):
        first_adapter.complete_collection_run(
            stale_lease,
            "succeeded",
            {"fetched": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0},
            {"state": "current"},
        )


def test_collection_missing_env_credential_marks_auth_required_and_releases_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    monkeypatch.delenv("GLINT_SECRET_MISSING", raising=False)
    with Session() as db:
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        source.credential_ref = "env://missing"
        db.commit()

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    factory = SourceConnectorFactory(
        FixtureTransport({}),
        EnvironmentSecretResolver(),
        cursor_secret="test-cursor-secret-0123456789abcdef",
    )
    assert run_once(
        domain=adapter,
        object_store=FakeObjectStore(),
        connector_factory=factory,
        worker_id="worker-a",
        lease_for=timedelta(seconds=120),
        kind="collection-schedule",
    )

    with Session() as db:
        run = db.query(CollectionRun).one()
        assert run.state == "failed"
        assert run.failure_code == "ConnectorInvalidCredential"
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.status == "auth_required"
        assert source.health_state == "auth_required"
        schedule = db.query(CollectionSchedule).one()
        assert schedule.lease_owner_token is None
        assert schedule.next_run_at > NOW


def test_failed_empty_connector_page_is_terminal_failed_and_preserves_history() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)
    history_claim = scheduler.claim_one(NOW)
    assert history_claim is not None
    _extend_schedule_lease(Session, history_claim)
    history = ConnectorCollectionJob(
        adapter,
        _SingleItemConnector(NOW),
        heartbeat=lambda now: scheduler.heartbeat(
            history_claim.schedule_id, history_claim.lease_token, now
        ),
    ).run(history_claim.command)
    assert history.state == "succeeded"
    scheduler.complete(
        history_claim.schedule_id,
        history_claim.lease_token,
        True,
        NOW + timedelta(hours=1),
        datetime.now(tz=UTC),
    )

    with Session() as db:
        schedule = db.get(CollectionSchedule, history_claim.schedule_id)
        schedule.next_run_at = NOW + timedelta(hours=1)
        db.commit()
    failed_claim = scheduler.claim_one(NOW + timedelta(hours=1, seconds=1))
    assert failed_claim is not None
    _extend_schedule_lease(Session, failed_claim)
    result = ConnectorCollectionJob(
        adapter,
        _EmptyFailedConnector(NOW + timedelta(hours=1)),
        heartbeat=lambda now: scheduler.heartbeat(
            failed_claim.schedule_id, failed_claim.lease_token, now
        ),
    ).run(failed_claim.command)
    assert result.state == "failed"
    assert result.error_class == "CONNECTOR_FAILED"
    scheduler.complete(
        failed_claim.schedule_id,
        failed_claim.lease_token,
        False,
        None,
        datetime.now(tz=UTC),
    )
    with Session() as db:
        runs = db.query(CollectionRun).order_by(CollectionRun.created_at).all()
        assert [run.state for run in runs] == ["succeeded", "failed"]
        assert runs[-1].failure_code == "CONNECTOR_FAILED"
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.status == "failed"
        assert source.freshness_state == "stale"
        assert db.query(ContentVersion).count() == 1


def test_failed_page_with_usable_items_is_partial_success_and_degraded() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)
    claim = scheduler.claim_one(NOW)
    assert claim is not None
    _extend_schedule_lease(Session, claim)
    result = ConnectorCollectionJob(
        adapter,
        _FailedWithItemsConnector(NOW),
        heartbeat=lambda now: scheduler.heartbeat(claim.schedule_id, claim.lease_token, now),
    ).run(claim.command)
    assert result.state == "partial_success"
    assert result.health_status == SourceHealthStatus.DEGRADED
    with Session() as db:
        run = db.query(CollectionRun).one()
        assert run.state == "partial_success"
        assert run.failure_code is None
        assert run.counters_json["failed"] == 1
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.status == "degraded"


def test_backfill_only_healthy_fetch_is_stale_warning_without_signal() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)
    claim = scheduler.claim_one(NOW)
    assert claim is not None
    _extend_schedule_lease(Session, claim)
    result = ConnectorCollectionJob(
        adapter,
        _BackfillConnector(NOW),
        heartbeat=lambda now: scheduler.heartbeat(claim.schedule_id, claim.lease_token, now),
    ).run(claim.command)
    assert result.state == "succeeded"
    assert result.signal_count == 0
    with Session() as db:
        run = db.query(CollectionRun).one()
        assert run.freshness_json["state"] == "stale"
        assert run.freshness_json["warning"] == "backfill_suppressed"
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.freshness_state == "stale"
        assert db.query(DbSignal).count() == 0


def test_signal_policy_snapshot_single_platform_limitation_and_cooldown() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    fake_now = datetime(2026, 7, 15, 7, tzinfo=UTC)
    current_time = {"now": fake_now}
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session,
        worker_id="worker-a",
        workspace_id=WORKSPACE,
        object_store=FakeObjectStore(),
        clock=lambda: current_time["now"],
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)
    first_claim = scheduler.claim_one(NOW)
    assert first_claim is not None
    _extend_schedule_lease(Session, first_claim)
    first_result = ConnectorCollectionJob(
        adapter,
        _SignalFixtureConnector(NOW),
        heartbeat=lambda now: scheduler.heartbeat(
            first_claim.schedule_id, first_claim.lease_token, now
        ),
    ).run(first_claim.command)
    assert first_result.signal_count == 1
    with Session() as db:
        signal = db.query(DbSignal).one()
        signal.created_at = fake_now
        db.commit()
        presented = presenters.signal(db, signal)
        assert presented["detector_version"] == "signal-v1"
        assert "policy snapshot unavailable" not in " ".join(presented["limitations"])
        assert any("cooldown_seconds" in rule for rule in presented["trigger_rules"])
        assert "single_platform_coverage" in presented["limitations"]
        assert presented["metrics"]["platform_count"] == 1
        assert {row.independence_group_id for row in db.query(SignalEvidence).all()}
    scheduler.complete(
        first_claim.schedule_id,
        first_claim.lease_token,
        True,
        NOW + timedelta(hours=1),
        datetime.now(tz=UTC),
    )

    with Session() as db:
        schedule = db.get(CollectionSchedule, first_claim.schedule_id)
        schedule.next_run_at = NOW + timedelta(hours=1)
        db.commit()
    second_claim = scheduler.claim_one(NOW + timedelta(hours=1, seconds=1))
    assert second_claim is not None
    _extend_schedule_lease(Session, second_claim)
    current_time["now"] = fake_now + timedelta(hours=1)
    second_result = ConnectorCollectionJob(
        adapter,
        _ChangingSignalFixtureConnector(NOW + timedelta(hours=1)),
        heartbeat=lambda now: scheduler.heartbeat(
            second_claim.schedule_id, second_claim.lease_token, now
        ),
    ).run(second_claim.command)
    assert second_result.signal_count == 0
    with Session() as db:
        assert db.query(DbSignal).count() == 1
        run = db.query(CollectionRun).order_by(CollectionRun.created_at.desc()).first()
        assert run.freshness_json["signal_suppressed_reason"] == "cooldown_active"


def test_run_once_consumes_api_enqueued_source_validation_job_to_healthy() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    _enqueue_source_validation(
        Session, SOURCE, "health_check", "aaaaaaaa-aaaa-5aaa-8aaa-000000000001"
    )

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    factory = _ValidationConnectorFactory(
        {SOURCE: ConnectorHealth("github", ConnectorStatus.HEALTHY, NOW, "current", {})}
    )
    assert run_once(
        domain=adapter,
        object_store=FakeObjectStore(),
        connector_factory=cast(SourceConnectorFactory, factory),
        worker_id="worker-a",
        lease_for=timedelta(seconds=120),
        kind="source-validation",
    )
    with Session() as db:
        job = db.query(SourceValidationJobRecord).one()
        assert job.state == "completed"
        assert job.result_source_status == "healthy"
        assert job.lease_owner_token is None
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.status == "healthy"
        assert source.health_state == "healthy"
        assert source.health_checked_at is not None
    assert factory.seen_configs == [
        {
            "owner": "acme",
            "repo": "glint",
            "include_repository": True,
            "include_issues": True,
            "include_discussions": True,
            "include_releases": True,
        }
    ]


def test_run_once_all_consumes_source_validation_job_to_degraded() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    _enqueue_source_validation(
        Session, SOURCE, "health_check", "aaaaaaaa-aaaa-5aaa-8aaa-000000000005"
    )

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    factory = _ValidationConnectorFactory(
        {
            SOURCE: ConnectorHealth(
                "github",
                ConnectorStatus.DEGRADED,
                NOW,
                "stale",
                {"error": "network_flaky"},
            )
        }
    )
    assert run_once(
        domain=adapter,
        object_store=FakeObjectStore(),
        connector_factory=cast(SourceConnectorFactory, factory),
        worker_id="worker-a",
        lease_for=timedelta(seconds=120),
        kind="all",
    )
    with Session() as db:
        job = db.query(SourceValidationJobRecord).one()
        assert job.state == "completed"
        assert job.result_source_status == "degraded"
        assert job.failure_code == "network_flaky"
        assert db.query(CollectionRun).count() == 0
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.status == "degraded"
        assert source.health_state == "degraded"
        assert source.health_error_code == "network_flaky"


def test_source_validation_invalid_credential_terminalizes_and_poll_continues() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    _seed_second_source(Session)
    _enqueue_source_validation(
        Session, SOURCE, "health_check", "aaaaaaaa-aaaa-5aaa-8aaa-000000000002"
    )
    _enqueue_source_validation(
        Session, SECOND_SOURCE, "reconnect", "aaaaaaaa-aaaa-5aaa-8aaa-000000000003"
    )

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    factory = _ValidationConnectorFactory(
        {
            SOURCE: ConnectorInvalidCredential("missing credential"),
            SECOND_SOURCE: ConnectorHealth("rss", ConnectorStatus.HEALTHY, NOW, "current", {}),
        }
    )
    assert run_once(
        domain=adapter,
        object_store=FakeObjectStore(),
        connector_factory=cast(SourceConnectorFactory, factory),
        worker_id="worker-a",
        lease_for=timedelta(seconds=120),
        kind="source-validation",
    )
    assert run_once(
        domain=adapter,
        object_store=FakeObjectStore(),
        connector_factory=cast(SourceConnectorFactory, factory),
        worker_id="worker-a",
        lease_for=timedelta(seconds=120),
        kind="source-validation",
    )
    with Session() as db:
        jobs = db.query(SourceValidationJobRecord).order_by(SourceValidationJobRecord.id).all()
        assert {job.state for job in jobs} == {"completed"}
        first = db.scalar(
            db.query(SourceValidationJobRecord)
            .where(SourceValidationJobRecord.source_connection_id == SOURCE)
            .statement
        )
        second = db.scalar(
            db.query(SourceValidationJobRecord)
            .where(SourceValidationJobRecord.source_connection_id == SECOND_SOURCE)
            .statement
        )
        assert first.result_source_status == "auth_required"
        assert first.failure_code == "ConnectorInvalidCredential"
        assert second.result_source_status == "healthy"
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.status == "auth_required"
        assert source.health_error_code == "ConnectorInvalidCredential"
        second_source = db.get(SourceConnection, SECOND_SOURCE)
        assert second_source is not None
        assert second_source.status == "healthy"


def test_source_validation_stale_fence_cannot_complete_job() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    _enqueue_source_validation(
        Session, SOURCE, "health_check", "aaaaaaaa-aaaa-5aaa-8aaa-000000000004"
    )

    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    claim = adapter.claim_next_source_validation_job("worker-a", timedelta(seconds=120))
    assert claim is not None
    with Session() as db:
        job = db.get(SourceValidationJobRecord, claim.job_id)
        assert job is not None
        job.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        db.commit()
    with pytest.raises(ProductionAdapterError, match="JOB_LEASE_EXPIRED"):
        adapter.complete_source_validation_job(claim, "healthy")
    with Session() as db:
        job = db.get(SourceValidationJobRecord, claim.job_id)
        assert job is not None
        assert job.state == "claimed"
        assert job.result_source_status is None
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.status == "validating"


@pytest.mark.parametrize("worker_outcome", ["complete", "fail"])
def test_in_memory_source_validation_fence_drift_requires_current_claim_and_terminalizes(
    worker_outcome: str,
) -> None:
    domain = InMemoryDomainAdapter()
    domain.sources[SOURCE] = WorkerSourceConnection(
        id=SOURCE,
        workspace_id=WORKSPACE,
        source_kind="cloud",
        runtime="cloud",
        connector_type="github",
        connector_version="v1",
        status=cast(SourceHealthStatus, "validating"),
        row_version=2,
    )
    job_id = f"memory-source-validation-{worker_outcome}"
    domain.source_validation_jobs[job_id] = {
        "workspace_id": WORKSPACE,
        "source_connection_id": SOURCE,
        "command": "health_check",
        "state": "queued",
        "expected_source_row_version": 2,
        "attempt": 0,
        "fencing_version": 0,
    }
    claim = domain.claim_next_source_validation_job("memory-worker", timedelta(seconds=120))
    assert claim is not None
    source = domain.sources[SOURCE]
    source.status = SourceHealthStatus.DISABLED
    source.row_version = 3
    stale_claim = replace(claim, attempt=claim.attempt + 1)

    with pytest.raises(NonTerminalImportError, match="attempt mismatch"):
        if worker_outcome == "complete":
            domain.complete_source_validation_job(stale_claim, "healthy")
        else:
            domain.fail_source_validation_job(stale_claim, "WORKER_FAILURE", "stale attempt")
    assert domain.source_validation_jobs[job_id]["state"] == "claimed"

    if worker_outcome == "complete":
        domain.complete_source_validation_job(claim, "healthy")
    else:
        domain.fail_source_validation_job(claim, "WORKER_FAILURE", "current attempt")
    terminal = domain.source_validation_jobs[job_id]
    assert terminal["state"] == "failed"
    assert terminal["result_source_status"] == "failed"
    assert terminal["failure_code"] == "SOURCE_VALIDATION_FENCE_DRIFT"
    assert terminal["lease_token"] is None
    assert terminal["lease_expires_at"] is None
    assert source.status == SourceHealthStatus.DISABLED
    assert source.row_version == 3


def test_source_validation_claim_uses_health_only_and_recovers_to_healthy() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    with Session() as db:
        source = db.get(SourceConnection, SOURCE)
        source.status = "validating"
        source.health_state = "unknown"
        db.commit()
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)
    claim = scheduler.claim_one(NOW)
    assert claim is not None
    assert claim.command.collection_kind == "source_validation"
    _extend_schedule_lease(Session, claim)
    result = ConnectorCollectionJob(
        adapter,
        _HealthOnlyConnector(NOW, ConnectorStatus.HEALTHY),
        heartbeat=lambda now: scheduler.heartbeat(claim.schedule_id, claim.lease_token, now),
    ).run(claim.command)
    assert result.state == "succeeded"
    with Session() as db:
        run = db.query(CollectionRun).one()
        assert run.input_window_json["kind"] == "source_validation"
        assert run.state == "succeeded"
        source = db.get(SourceConnection, SOURCE)
        assert source is not None
        assert source.status == "healthy"
        assert source.health_state == "healthy"


def test_deleted_refetch_creates_unavailable_version_without_rewriting_evidence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)
    first_claim = scheduler.claim_one(NOW)
    assert first_claim is not None
    _extend_schedule_lease(Session, first_claim)
    ConnectorCollectionJob(
        adapter,
        _SingleItemConnector(NOW),
        heartbeat=lambda now: scheduler.heartbeat(
            first_claim.schedule_id, first_claim.lease_token, now
        ),
    ).run(first_claim.command)
    scheduler.complete(
        first_claim.schedule_id,
        first_claim.lease_token,
        True,
        NOW + timedelta(hours=1),
        datetime.now(tz=UTC),
    )
    with Session() as db:
        schedule = db.get(CollectionSchedule, first_claim.schedule_id)
        schedule.query_json = {**schedule.query_json, "refetch_limit": 1}
        original_version = db.query(ContentVersion).one()
        _seed_evidence_for_version(db, original_version.id)
        schedule.next_run_at = NOW + timedelta(hours=1)
        db.commit()

    second_claim = scheduler.claim_one(NOW + timedelta(hours=1, seconds=1))
    assert second_claim is not None
    _extend_schedule_lease(Session, second_claim)
    ConnectorCollectionJob(
        adapter,
        _DeletedRefetchConnector(NOW + timedelta(hours=1)),
        heartbeat=lambda now: scheduler.heartbeat(
            second_claim.schedule_id, second_claim.lease_token, now
        ),
    ).run(second_claim.command)
    with Session() as db:
        versions = db.query(ContentVersion).order_by(ContentVersion.version_number).all()
        assert len(versions) == 2
        assert versions[0].id == original_version.id
        assert versions[0].availability == "captured"
        assert versions[1].normalized_body == ""
        assert versions[1].availability == "deleted"
        assert versions[1].availability_last_checked_at is not None
        assert versions[1].availability_reason == "source returned deleted during refetch"
        assert versions[1].metadata_json["availability"] == "deleted"
        evidence = db.query(Evidence).one()
        assert evidence.content_version_id == original_version.id
        item = db.query(ContentItem).one()
        assert item.current_version_id == versions[1].id
        projected = presenters.content_version(db, versions[1])
        assert projected["availability"] == "deleted"
        assert projected["availability_reason"] == "source returned deleted during refetch"


def test_misfire_skip_and_run_once_do_not_hammer_overdue_schedule() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    overdue = NOW - timedelta(hours=10)
    with Session() as db:
        schedule = db.query(CollectionSchedule).one()
        schedule.next_run_at = overdue
        schedule.misfire_policy = "skip"
        schedule.catch_up = False
        db.commit()
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session, worker_id="worker-a", workspace_id=WORKSPACE, object_store=FakeObjectStore()
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)
    assert scheduler.claim_one(NOW) is None
    with Session() as db:
        assert db.query(CollectionSchedule).one().next_run_at > NOW

    with Session() as db:
        schedule = db.query(CollectionSchedule).one()
        schedule.next_run_at = overdue
        schedule.misfire_policy = "run_once"
        schedule.catch_up = False
        db.commit()
    claim = scheduler.claim_one(NOW)
    assert claim is not None
    _extend_schedule_lease(Session, claim)
    scheduler.complete(
        claim.schedule_id, claim.lease_token, True, overdue + timedelta(hours=1), NOW
    )
    with Session() as db:
        assert db.query(CollectionSchedule).one().next_run_at > NOW


def test_production_object_store_factory_fails_closed_without_api_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GLINT_WORKER_OBJECT_STORE", raising=False)
    monkeypatch.delenv("GLINT_API_OBJECT_STORE", raising=False)
    with pytest.raises(ProductionAdapterError, match="OBJECT_STORE|object store"):
        create_object_store()


def _extend_schedule_lease(Session, claim) -> None:  # noqa: ANN001
    with Session() as db:
        schedule = db.get(CollectionSchedule, claim.schedule_id)
        schedule.lease_expires_at = datetime.now(tz=UTC) + timedelta(seconds=120)
        db.commit()


def _seed_evidence_for_version(db, version_id: str) -> None:  # noqa: ANN001
    investigation = Investigation(
        id="77777777-7777-5777-8777-777777777777",
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        signal_id="88888888-8888-5888-8888-888888888888",
        status="active",
        owner_id="owner",
        data_authenticity="seed",
    )
    scope = InvestigationScopeVersion(
        id="99999999-9999-5999-8999-999999999999",
        workspace_id=WORKSPACE,
        investigation_id=investigation.id,
        version_number=1,
        decision_question="Should we act on permissions?",
        source_scope_json={},
        time_range_json={},
        budget_json={},
        stop_conditions=[],
        created_by="owner",
        change_reason="seed",
        data_authenticity="seed",
    )
    db.add(investigation)
    db.add(scope)
    db.flush()
    investigation.current_scope_version_id = scope.id
    from services.api.app.db.models import ResearchRun as DbResearchRun

    run = DbResearchRun(
        id="aaaaaaaa-aaaa-5aaa-8aaa-aaaaaaaaaaaa",
        workspace_id=WORKSPACE,
        investigation_id=investigation.id,
        investigation_scope_version_id=scope.id,
        state="completed",
        graph_version="deterministic-content-v2",
        run_input_manifest_json={"content_versions": []},
        run_input_manifest_digest="sha256:seed",
        budget_json={},
        initiated_by="owner",
        trace_id="trace",
        data_authenticity="seed",
    )
    db.add(run)
    db.add(
        Evidence(
            id="bbbbbbbb-bbbb-5bbb-8bbb-bbbbbbbbbbbb",
            workspace_id=WORKSPACE,
            investigation_id=investigation.id,
            research_run_id=run.id,
            content_version_id=version_id,
            quote_start=0,
            quote_end=10,
            quote_text="Permission",
            quote_text_digest=text_digest("Permission"),
            stance="supports",
            relevance=0.8,
            reliability=0.8,
            independence=0.8,
            recency=0.8,
            specificity=0.8,
            extraction_method="seed",
            data_authenticity="seed",
        )
    )


def _collection_run_metadata(claim) -> dict[str, object]:  # noqa: ANN001
    return {
        "watchlist_id": WATCHLIST,
        "scheduled_for": claim.command.scheduled_for.isoformat(),
        "schedule_id": claim.schedule_id,
        "schedule_lease_token": claim.lease_token,
        "schedule_fencing_version": claim.command.schedule_fencing_version,
        "lease_checked_at": NOW.isoformat(),
        "attempt": claim.command.schedule_attempt,
        "cadence": "manual",
        "timezone": "UTC",
        "current_start": NOW.isoformat(),
        "current_end": (NOW + timedelta(hours=1)).isoformat(),
    }


def _seed_schedule_fixture(Session) -> None:  # noqa: ANN001
    with Session() as db:
        db.add(Workspace(id=WORKSPACE, name="Test", created_by="owner", data_authenticity="seed"))
        db.add(
            Project(
                id=PROJECT,
                workspace_id=WORKSPACE,
                name="Project",
                status="active",
                created_by="owner",
                data_authenticity="seed",
            )
        )
        db.add(
            SourceConnection(
                id=SOURCE,
                workspace_id=WORKSPACE,
                name="GitHub",
                source_kind="cloud",
                runtime="cloud",
                connector_type="github",
                connector_version="v1",
                status="healthy",
                credential_ref="github-token",
                config_json={"repositories": [{"owner": "acme", "repository": "glint"}]},
                approved_by="owner",
                data_authenticity="seed",
            )
        )
        db.add(
            Watchlist(
                id=WATCHLIST,
                workspace_id=WORKSPACE,
                project_id=PROJECT,
                name="Permission",
                objective="Track permission friction",
                status="active",
                rules_json={"source_connection_ids": [SOURCE]},
                owner_id="owner",
                data_authenticity="seed",
            )
        )
        db.add(
            CollectionSchedule(
                id="66666666-6666-5666-8666-666666666666",
                workspace_id=WORKSPACE,
                source_connection_id=SOURCE,
                watchlist_id=WATCHLIST,
                query_json={"query": "permission", "owner": "acme", "repo": "glint"},
                cadence_seconds=3600,
                timezone="UTC",
                misfire_policy="run_once",
                catch_up=False,
                overlap_policy="forbid",
                next_run_at=NOW,
                enabled=True,
                data_authenticity="seed",
            )
        )
        db.commit()


def _seed_cross_source_baseline_fixture(Session) -> None:  # noqa: ANN001
    with Session() as db:
        db.add(
            SourceConnection(
                id=SECOND_SOURCE,
                workspace_id=WORKSPACE,
                name="RSS",
                source_kind="cloud",
                runtime="cloud",
                connector_type="rss",
                connector_version="v1",
                status="healthy",
                config_json={"feeds": [{"url": "https://feeds.example.test/glint.xml"}]},
                approved_by="owner",
                data_authenticity="seed",
            )
        )
        db.add(
            SourceConnection(
                id=THIRD_SOURCE,
                workspace_id=WORKSPACE,
                name="Partner RSS",
                source_kind="cloud",
                runtime="cloud",
                connector_type="rss",
                connector_version="v1",
                status="healthy",
                config_json={"feeds": [{"url": "https://feeds.example.test/partner.xml"}]},
                approved_by="owner",
                data_authenticity="seed",
            )
        )
        watchlist = db.get(Watchlist, WATCHLIST)
        watchlist.rules_json = {
            "source_connection_ids": [SOURCE, SECOND_SOURCE, THIRD_SOURCE],
            "rules": {
                "schema_version": "watchlist-rules-v1",
                "query_rules": {"include_terms": ["permission"]},
                "current_window_days": 1,
                "baseline_window_days": 7,
            },
        }
        db.add(
            CollectionSchedule(
                id="66666666-6666-5666-8666-666666666667",
                workspace_id=WORKSPACE,
                source_connection_id=SECOND_SOURCE,
                watchlist_id=WATCHLIST,
                query_json={
                    "query": "permission",
                    "feed_url": "https://feeds.example.test/glint.xml",
                },
                cadence_seconds=3600,
                timezone="UTC",
                misfire_policy="run_once",
                catch_up=False,
                overlap_policy="forbid",
                next_run_at=NOW + timedelta(hours=1),
                enabled=True,
                data_authenticity="seed",
            )
        )
        db.commit()


def _seed_second_source(Session) -> None:  # noqa: ANN001
    with Session() as db:
        db.add(
            SourceConnection(
                id=SECOND_SOURCE,
                workspace_id=WORKSPACE,
                name="RSS",
                source_kind="cloud",
                runtime="cloud",
                connector_type="rss",
                connector_version="v1",
                status="healthy",
                config_json={"feed_url": "https://feeds.example.test/glint.xml"},
                approved_by="owner",
                data_authenticity="seed",
            )
        )
        db.commit()


def _enqueue_source_validation(
    Session, source_connection_id: str, command: str, idempotency_key: str
) -> None:  # noqa: ANN001
    with Session() as db:
        source = db.get(SourceConnection, source_connection_id)
        assert source is not None
        SourceValidationJobRepository.enqueue(
            db,
            workspace_id=WORKSPACE,
            source_connection_id=source_connection_id,
            command=command,
            expected_source_row_version=source.row_version,
            actor_id="owner",
            request_id=f"request:{idempotency_key}",
            idempotency_key=idempotency_key,
            reason="test validation",
        )


class _ValidationConnectorFactory:
    def __init__(self, responses: dict[str, ConnectorHealth | Exception]) -> None:
        self.responses = responses
        self.seen_configs: list[dict[str, Any]] = []

    def create(self, source: Any, config: dict[str, Any]) -> _ValidationConnector:
        self.seen_configs.append(dict(config))
        response = self.responses[str(source.id)]
        return _ValidationConnector(str(source.connector_type), response)


class _ValidationConnector:
    def __init__(self, connector_type: str, response: ConnectorHealth | Exception) -> None:
        self.connector_type = connector_type
        self.response = response

    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        raise AssertionError((query, cursor))

    def fetch(self, external_id: str) -> FetchResult:
        raise AssertionError(external_id)

    def health(self) -> ConnectorHealth:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            self.connector_type, False, False, False, False, "fixture", ("health",)
        )


class _ConfigurableSignalConnector:
    def __init__(
        self, source_connection_id: str, connector_type: str, now: datetime, item_count: int
    ) -> None:
        self.source_connection_id = source_connection_id
        self.connector_type = connector_type
        self.now = now
        self.item_count = item_count

    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del query, cursor
        items = [
            ConnectorRawContentItem(
                connector_type=self.connector_type,
                source_connection_id=self.source_connection_id,
                external_id=f"{self.connector_type}-{index}",
                title=f"Permission {self.connector_type} {index}",
                body=(
                    "Permission failures are increasing for enterprise onboarding "
                    f"cohort {self.connector_type}-{index}."
                ),
                canonical_url=(f"https://{self.connector_type}.example.test/acme/glint/{index}"),
                author=f"{self.connector_type}-author-{index}",
                published_at=self.now - timedelta(minutes=10 + index),
                captured_at=self.now,
                content_version_digest=f"sha256:{self.connector_type}-content-{index}",
                raw_digest=f"sha256:{self.connector_type}-raw-{index}",
                metadata={"kind": "fixture"},
            )
            for index in range(self.item_count)
        ]
        return SearchPage(
            items=items,
            next_cursor=None,
            health=ConnectorHealth(
                self.connector_type, ConnectorStatus.HEALTHY, self.now, "current", {}
            ),
        )

    def fetch(self, external_id: str) -> FetchResult:
        del external_id
        return FetchResult(None, self.health(), deleted=True)

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            self.connector_type, ConnectorStatus.HEALTHY, self.now, "current", {}
        )

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            self.connector_type, True, True, False, True, "fixture", ("item",)
        )


class _SignalFixtureConnector:
    connector_type = "github"

    def __init__(self, now: datetime) -> None:
        self.now = now

    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del query, cursor
        items = [
            ConnectorRawContentItem(
                connector_type="github",
                source_connection_id=SOURCE,
                external_id=f"issue-{index}",
                title=f"Permission issue {index}",
                body="Permission requests fail for enterprise onboarding.",
                canonical_url=f"https://github.example.test/acme/glint/issues/{index}",
                author=f"author-{index}",
                published_at=self.now - timedelta(minutes=10 + index),
                captured_at=self.now,
                content_version_digest=f"sha256:signal-content-{index}",
                raw_digest=f"sha256:signal-raw-{index}",
                metadata={"kind": "issue"},
            )
            for index in range(3)
        ]
        return SearchPage(
            items=items,
            next_cursor=None,
            health=ConnectorHealth("github", ConnectorStatus.HEALTHY, self.now, "current", {}),
        )

    def fetch(self, external_id: str) -> FetchResult:
        del external_id
        return FetchResult(None, self.health(), deleted=True)

    def health(self) -> ConnectorHealth:
        return ConnectorHealth("github", ConnectorStatus.HEALTHY, self.now, "current", {})

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities("github", True, True, False, True, "fixture", ("issue",))


class _ChangingSignalFixtureConnector(_SignalFixtureConnector):
    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del query, cursor
        items = [
            ConnectorRawContentItem(
                connector_type="github",
                source_connection_id=SOURCE,
                external_id=f"changed-{index}",
                title=f"Permission changed {index}",
                body=f"Permission requests fail for changed enterprise cohort {index}.",
                canonical_url=f"https://github.example.test/acme/glint/issues/changed-{index}",
                author=f"changed-author-{index}",
                published_at=self.now - timedelta(minutes=10 + index),
                captured_at=self.now,
                content_version_digest=f"sha256:changed-content-{index}",
                raw_digest=f"sha256:changed-raw-{index}",
                metadata={"kind": "issue"},
            )
            for index in range(3)
        ]
        return SearchPage(
            items=items,
            next_cursor=None,
            health=ConnectorHealth("github", ConnectorStatus.HEALTHY, self.now, "current", {}),
        )


class _SingleItemConnector(_SignalFixtureConnector):
    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del query, cursor
        item = ConnectorRawContentItem(
            connector_type="github",
            source_connection_id=SOURCE,
            external_id="item-1",
            title="Permission existing",
            body="Permission issue remains available.",
            canonical_url="https://github.example.test/acme/glint/issues/1",
            author="author-1",
            published_at=self.now - timedelta(minutes=10),
            captured_at=self.now,
            content_version_digest="sha256:single-content-1",
            raw_digest="sha256:single-raw-1",
            metadata={"kind": "issue"},
        )
        return SearchPage(
            items=[item],
            next_cursor=None,
            health=ConnectorHealth("github", ConnectorStatus.HEALTHY, self.now, "current", {}),
        )


class _EmptyFailedConnector(_SignalFixtureConnector):
    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del query, cursor
        return SearchPage(
            items=[],
            next_cursor=None,
            health=ConnectorHealth(
                "rss",
                ConnectorStatus.FAILED,
                self.now,
                "stale",
                {"status_code": 500, "error": "invalid_xml"},
            ),
        )


class _FailedWithItemsConnector(_SignalFixtureConnector):
    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        page = _SingleItemConnector(self.now).search(query, cursor)
        return SearchPage(
            items=page.items,
            next_cursor=None,
            health=ConnectorHealth(
                "rss",
                ConnectorStatus.FAILED,
                self.now,
                "stale",
                {"status_code": 500, "error": "page_failed_after_items"},
            ),
        )


class _BackfillConnector(_SignalFixtureConnector):
    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del query, cursor
        items = [
            ConnectorRawContentItem(
                connector_type="rss",
                source_connection_id=SOURCE,
                external_id=f"backfill-{index}",
                title=f"Permission backfill {index}",
                body="Permission outage report from historical feed recovery.",
                canonical_url=f"https://feeds.example.test/backfill/{index}",
                author=f"rss-author-{index}",
                published_at=self.now - timedelta(days=4, hours=index),
                captured_at=self.now,
                content_version_digest=f"sha256:backfill-content-{index}",
                raw_digest=f"sha256:backfill-raw-{index}",
                metadata={"kind": "rss-entry"},
            )
            for index in range(3)
        ]
        return SearchPage(
            items=items,
            next_cursor=None,
            health=ConnectorHealth("rss", ConnectorStatus.HEALTHY, self.now, "current", {}),
        )


class _HealthOnlyConnector(_SignalFixtureConnector):
    def __init__(self, now: datetime, status: ConnectorStatus) -> None:
        super().__init__(now)
        self.status = status

    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        raise AssertionError("source validation must not collect content")

    def health(self) -> ConnectorHealth:
        return ConnectorHealth("github", self.status, self.now, "current", {})


class _DeletedRefetchConnector(_SignalFixtureConnector):
    def search(self, query: str, cursor: str | None = None) -> SearchPage:
        del query, cursor
        return SearchPage(
            items=[],
            next_cursor=None,
            health=ConnectorHealth("github", ConnectorStatus.HEALTHY, self.now, "current", {}),
        )

    def fetch(self, external_id: str) -> FetchResult:
        assert external_id == "item-1"
        return FetchResult(
            None,
            ConnectorHealth("github", ConnectorStatus.DEGRADED, self.now, "stale", {}),
            deleted=True,
        )
