from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from connectors.github.connector import GitHubConnector, GitHubConnectorConfig
from connectors.rss.connector import RssConnector, RssConnectorConfig
from connectors.shared.contracts import ConnectorPartialFailure, ConnectorStatus
from connectors.shared.fixture_transport import FixtureTransport, json_route, xml_route
from services.worker.app.contracts import ContentVersion, DataAuthenticity
from services.worker.app.pipelines.dedupe import deduplicate_versions
from services.worker.app.pipelines.signals import SignalDetectionConfig, detect_signal

WORKSPACE = "workspace-runtime"
SOURCE = "source-runtime"
NOW = datetime(2026, 7, 15, 6, tzinfo=UTC)


RSS_BODY = """
<rss version="2.0"><channel><title>Glint fixture</title>
<item><title>Permission friction</title><link>https://example.test/items/1?utm_source=fixture</link>
<guid>item-1</guid><description>Users report permission friction in the admin
workflow.</description>
<pubDate>Wed, 15 Jul 2026 05:00:00 GMT</pubDate></item>
</channel></rss>
"""


def test_rss_connector_contract_normalizes_fixture_content() -> None:
    url = "https://feeds.example.test/glint.xml"
    transport = FixtureTransport({url: xml_route(RSS_BODY)})
    connector = RssConnector(
        RssConnectorConfig(
            source_connection_id=SOURCE, feed_url=url, resolver=lambda _: ["93.184.216.34"]
        ),
        transport,
    )
    page = connector.search("permission")
    assert page.health.status is ConnectorStatus.HEALTHY
    assert len(page.items) == 1
    assert page.items[0].connector_type == "rss"
    assert page.items[0].canonical_url == "https://example.test/items/1"
    assert connector.capabilities().supports_incremental


@pytest.mark.parametrize(
    "url",
    [
        "http://feeds.example.test/feed.xml",
        "https://127.0.0.1/feed.xml",
        "https://169.254.169.254/latest",
    ],
)
def test_rss_ssrf_policy_blocks_non_public_targets(url: str) -> None:
    connector = RssConnector(
        RssConnectorConfig(
            source_connection_id=SOURCE,
            feed_url=url,
            resolver=lambda _: ["127.0.0.1"],
        ),
        FixtureTransport({}),
    )
    with pytest.raises(ConnectorPartialFailure, match="egress policy|https"):
        connector.health()


def test_rss_ssrf_policy_rechecks_redirect_targets() -> None:
    source = "https://feeds.example.test/feed.xml"
    transport = FixtureTransport(
        {source: xml_route("", 302, {"location": "https://127.0.0.1/private"})}
    )
    connector = RssConnector(
        RssConnectorConfig(
            source_connection_id=SOURCE,
            feed_url=source,
            resolver=lambda host: ["93.184.216.34"] if host != "127.0.0.1" else ["127.0.0.1"],
        ),
        transport,
    )
    with pytest.raises(ConnectorPartialFailure, match="egress policy"):
        connector.search("")


def test_github_graphql_fixture_is_normalized_and_redacts_only_at_boundary() -> None:
    graphql_url = "https://api.github.com/graphql"
    body = {
        "data": {
            "repository": {
                "discussions": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "D_1",
                            "number": 7,
                            "title": "Permission friction",
                            "bodyText": "Admins cannot complete the workflow.",
                            "url": "https://github.com/acme/glint/discussions/7",
                            "updatedAt": "2026-07-15T05:00:00Z",
                            "publishedAt": "2026-07-15T04:00:00Z",
                            "author": {"login": "researcher"},
                        }
                    ],
                }
            }
        }
    }
    rest_routes = {
        "https://api.github.com/repos/acme/glint": json_route(
            json.dumps({"id": 1, "full_name": "acme/glint"})
        ),
        "https://api.github.com/repos/acme/glint/issues?state=all&per_page=100": json_route("[]"),
        "https://api.github.com/repos/acme/glint/releases?per_page=100": json_route("[]"),
    }
    transport = FixtureTransport(
        {**rest_routes, f"POST {graphql_url}": json_route(json.dumps(body))}
    )
    connector = GitHubConnector(
        GitHubConnectorConfig(
            source_connection_id=SOURCE,
            owner="acme",
            repo="glint",
            token_ref="github-token",
        ),
        transport,
        token_resolver=lambda ref: "fixture-secret" if ref == "github-token" else "",
    )
    page = connector.search("permission")
    assert page.health.status is ConnectorStatus.HEALTHY
    assert page.items[0].external_id.endswith(":discussion:7")
    assert transport.requests[0]["headers"]["authorization"] == "Bearer fixture-secret"


def _version(
    version_id: str,
    source_id: str,
    body: str,
    captured_at: datetime,
    url: str | None = None,
    author: str | None = None,
) -> ContentVersion:
    return ContentVersion(
        id=version_id,
        workspace_id=WORKSPACE,
        content_item_id=f"item-{version_id}",
        version_number=1,
        content_digest=f"digest-{version_id}",
        normalized_title="Permission friction",
        normalized_body=body,
        captured_at=captured_at,
        parser_version="fixture-v1",
        canonical_url=url,
        author=author or source_id,
        data_authenticity=DataAuthenticity.COLLECTED,
        metadata={"source_id": source_id},
    )


def test_dedupe_repost_cluster_keeps_independent_groups_explicit() -> None:
    versions = [
        _version(
            "a", "source-a", "Permission friction is rising.", NOW, "https://example.test/story"
        ),
        _version(
            "b", "source-b", "Permission friction is rising.", NOW, "https://example.test/story"
        ),
    ]
    result = deduplicate_versions(versions)
    assert (
        result.assignments["a"].duplicate_cluster_id == result.assignments["b"].duplicate_cluster_id
    )
    assert (
        result.assignments["a"].independence_group_id
        != result.assignments["b"].independence_group_id
    )
    assert result.assignments["a"].duplicate_reason == "canonical_url"


def test_collection_signal_explanation_reports_repost_concentration() -> None:
    versions = [
        _version(
            "a", "source-a", "Permission friction is rising.", NOW, "https://example.test/story"
        ),
        _version(
            "b", "source-b", "Permission friction is rising.", NOW, "https://example.test/story"
        ),
        _version(
            "c",
            "source-c",
            "Permission friction is rising in a separate report.",
            NOW,
            "https://other.test/report",
        ),
    ]
    config = SignalDetectionConfig(
        workspace_id=WORKSPACE,
        watchlist_id="watchlist-runtime",
        terms=("permission",),
        current_window=(NOW - timedelta(hours=1), NOW + timedelta(hours=1)),
        baseline_window=(NOW - timedelta(days=7), NOW - timedelta(hours=1)),
        min_independent_sources=2,
    )
    result = detect_signal(versions, config)
    assert result.signal is not None
    assert "effective independent sources" in result.signal.explanation
    assert "origin groups" in result.signal.explanation
    assert "duplicate concentration" in result.signal.explanation


def test_signal_effective_independence_folds_cross_source_reposts() -> None:
    versions = [
        _version(
            "repost-a",
            "source-a",
            "Permission friction is rising.",
            NOW,
            "https://example.test/repost",
        ),
        _version(
            "repost-b",
            "source-b",
            "Permission friction is rising.",
            NOW,
            "https://example.test/repost",
        ),
        _version(
            "repost-c",
            "source-c",
            "Permission friction is rising.",
            NOW,
            "https://example.test/repost",
        ),
        _version(
            "independent-a",
            "source-d",
            "Permission review blocks onboarding.",
            NOW,
            "https://example.test/independent-a",
        ),
        _version(
            "independent-b",
            "source-e",
            "Permission setup creates approval delay.",
            NOW,
            "https://example.test/independent-b",
        ),
    ]
    config = SignalDetectionConfig(
        workspace_id=WORKSPACE,
        watchlist_id="watchlist-runtime",
        terms=("permission",),
        current_window=(NOW - timedelta(hours=1), NOW + timedelta(hours=1)),
        baseline_window=(NOW - timedelta(days=7), NOW - timedelta(hours=1)),
        min_independent_sources=4,
    )
    result = detect_signal(versions, config)
    assert result.signal is None
    assert result.reason == "insufficient independent content clusters"
    assert result.metrics["independent_source_count"] == 3


def test_repository_collection_aggregates_watchlist_history_across_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from functools import partial

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    import services.worker.app.repositories.sqlalchemy_adapter as adapter_module
    from connectors.shared.contracts import (
        ConnectorCapabilities,
        ConnectorHealth,
        ConnectorStatus,
        FetchResult,
        RawContentItem,
        SearchPage,
    )
    from services.api.app.db.models import (
        Base,
        CollectionSchedule,
        ContentVersion,
        Signal,
        SignalEvidence,
        SourceConnection,
        Watchlist,
    )
    from services.worker.app.jobs.collection import ConnectorCollectionJob
    from services.worker.app.repositories.sqlalchemy_adapter import SQLAlchemyWorkerDomainAdapter
    from services.worker.app.schedules.scheduler import RepositoryCollectionScheduler
    from tests.connector.test_worker_adapter_scheduler import (
        SOURCE as FIRST_SOURCE,
    )
    from tests.connector.test_worker_adapter_scheduler import (
        WATCHLIST as SHARED_WATCHLIST,
    )
    from tests.connector.test_worker_adapter_scheduler import (
        WORKSPACE as SHARED_WORKSPACE,
    )
    from tests.connector.test_worker_adapter_scheduler import (
        FakeObjectStore,
        _seed_schedule_fixture,
    )

    second_source = "77777777-7777-5777-8777-777777777777"
    monkeypatch.setattr(adapter_module, "utcnow", lambda: NOW)

    class OneSourceFixture:
        connector_type = "github"

        def __init__(self, source_id: str) -> None:
            self.source_id = source_id

        def search(self, query: str, cursor: str | None = None) -> SearchPage:
            del query, cursor
            is_first_source = self.source_id == FIRST_SOURCE
            item = RawContentItem(
                connector_type="github",
                source_connection_id=self.source_id,
                external_id=f"{self.source_id}-permission",
                title=("Permission friction" if is_first_source else "Permission setup blockage"),
                body=(
                    "Admins cannot complete permission requests during enterprise onboarding."
                    if is_first_source
                    else "Workspace invites stall when permission grants are delayed for new teams."
                ),
                canonical_url=f"https://{self.source_id}.example.test/permission",
                author=self.source_id,
                published_at=NOW - timedelta(minutes=10),
                captured_at=NOW,
                content_version_digest=f"sha256:{self.source_id}",
                raw_digest=f"sha256:raw-{self.source_id}",
                metadata={"kind": "issue"},
            )
            return SearchPage(
                items=[item],
                next_cursor=None,
                health=ConnectorHealth("github", ConnectorStatus.HEALTHY, NOW, "current", {}),
            )

        def fetch(self, external_id: str) -> FetchResult:
            del external_id
            return FetchResult(None, self.health(), deleted=True)

        def health(self) -> ConnectorHealth:
            return ConnectorHealth("github", ConnectorStatus.HEALTHY, NOW, "current", {})

        def capabilities(self) -> ConnectorCapabilities:
            return ConnectorCapabilities("github", True, True, False, True, "fixture", ("issue",))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _seed_schedule_fixture(Session)
    with Session() as db:
        db.add(
            SourceConnection(
                id=second_source,
                workspace_id=SHARED_WORKSPACE,
                name="Second source",
                source_kind="cloud",
                runtime="cloud",
                connector_type="github",
                connector_version="v1",
                status="healthy",
                credential_ref="github-token-2",
                approved_by="owner",
                config_json={"repositories": [{"owner": "acme", "repository": "glint-2"}]},
                data_authenticity="seed",
            )
        )
        db.add(
            CollectionSchedule(
                id="88888888-8888-5888-8888-888888888888",
                workspace_id=SHARED_WORKSPACE,
                source_connection_id=second_source,
                watchlist_id=SHARED_WATCHLIST,
                query_json={"query": "permission", "owner": "acme", "repo": "glint-2"},
                cadence_seconds=3600,
                timezone="UTC",
                misfire_policy="run_once",
                catch_up=False,
                overlap_policy="skip",
                next_run_at=NOW,
                enabled=True,
                data_authenticity="seed",
            )
        )
        watchlist = db.get(Watchlist, SHARED_WATCHLIST)
        assert watchlist is not None
        watchlist.rules_json = {
            **(watchlist.rules_json or {}),
            "source_connection_ids": [FIRST_SOURCE, second_source],
        }
        db.commit()
    adapter = SQLAlchemyWorkerDomainAdapter(
        Session,
        worker_id="worker-a",
        workspace_id=SHARED_WORKSPACE,
        object_store=FakeObjectStore(),
    )
    scheduler = RepositoryCollectionScheduler(adapter, "worker-a", lease_seconds=120)
    connectors = {
        FIRST_SOURCE: OneSourceFixture(FIRST_SOURCE),
        second_source: OneSourceFixture(second_source),
    }
    for scheduled_at in (NOW, NOW + timedelta(seconds=2)):
        claim = scheduler.claim_one(scheduled_at)
        assert claim is not None
        claimed_schedule_id = claim.schedule_id
        claimed_lease_token = claim.lease_token

        result = ConnectorCollectionJob(
            adapter,
            connectors[claim.command.source_connection_id],
            clock=lambda: NOW,
            heartbeat=partial(scheduler.heartbeat, claimed_schedule_id, claimed_lease_token),
        ).run(claim.command)
        assert result.health_status.value == "healthy"
        scheduler.complete(
            claim.schedule_id, claim.lease_token, True, NOW + timedelta(hours=1), NOW
        )
    with Session() as db:
        sources = db.scalars(select(SourceConnection)).all()
        assert {source.health_state for source in sources} == {"healthy"}
        signal = db.query(Signal).one()
        evidence_sources = set(
            db.scalars(
                select(ContentVersion.source_connection_id)
                .join(
                    SignalEvidence,
                    SignalEvidence.content_version_id == ContentVersion.id,
                )
                .where(SignalEvidence.signal_id == signal.id)
            ).all()
        )
        evidence_independence_groups = db.scalars(
            select(SignalEvidence.independence_group_id).where(
                SignalEvidence.signal_id == signal.id
            )
        ).all()
        assert evidence_sources == {
            FIRST_SOURCE,
            second_source,
        }
        assert evidence_independence_groups
        assert all(evidence_independence_groups)
        assert signal.metrics_json["independent_source_count"] >= 2
        assert signal.metrics_json["mention_count"] >= 2


def test_in_memory_scheduler_unit_is_not_the_runtime_proof() -> None:
    from services.worker.app.schedules.scheduler import CollectionSchedule, CollectionScheduler

    schedule = CollectionSchedule(
        workspace_id=WORKSPACE,
        watchlist_id="watchlist-runtime",
        source_connection_id=SOURCE,
        query="permission",
        terms=("permission",),
        current_window=(NOW - timedelta(hours=1), NOW + timedelta(hours=1)),
        baseline_window=(NOW - timedelta(days=7), NOW - timedelta(hours=1)),
        cadence_seconds=3600,
        next_run_at=NOW,
    )
    commands = CollectionScheduler([schedule]).due_commands(NOW)
    assert len(commands) == 1
    assert schedule.lease_until is not None


def test_repository_scheduler_gate_uses_worker_and_api_repositories() -> None:
    from services.api.app.modules.sources.schedules import CollectionScheduleRepository
    from services.worker.app.schedules.scheduler import RepositoryCollectionScheduler

    assert callable(CollectionScheduleRepository.claim_due)
    assert callable(CollectionScheduleRepository.heartbeat)
    assert callable(CollectionScheduleRepository.release)
    assert callable(RepositoryCollectionScheduler.claim_one)
    assert callable(RepositoryCollectionScheduler.heartbeat)
    assert callable(RepositoryCollectionScheduler.complete)
    assert callable(RepositoryCollectionScheduler.release)
