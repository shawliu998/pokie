# pyright: reportPrivateUsage=false
from __future__ import annotations

import hmac
import json
from hashlib import sha256
from types import SimpleNamespace
from typing import cast

import pytest

from connectors.factory import (
    ConnectorFactoryError,
    EnvironmentSecretResolver,
    SourceConnectorFactory,
    create_connector_factory,
)
from connectors.github.connector import GitHubConnector, GitHubConnectorConfig
from connectors.rss.connector import RssConnector, RssConnectorConfig
from connectors.shared.contracts import ConnectorPartialFailure, ConnectorStatus
from connectors.shared.fixture_transport import FixtureTransport, json_route, xml_route
from connectors.shared.http_transport import ProductionHttpTransport
from connectors.shared.utils import canonicalize_url

SOURCE = "11111111-1111-5111-8111-111111111111"
CURSOR_SECRET = "test-cursor-secret-0123456789abcdef"


def test_github_composite_cursor_keeps_independent_resource_pagination() -> None:
    api = "https://api.github.com"
    graphql = "https://api.github.com/graphql"
    issues_1 = f"{api}/repos/acme/glint/issues?state=all&per_page=1"
    issues_2 = f"{api}/repos/acme/glint/issues?page=2"
    releases_1 = f"{api}/repos/acme/glint/releases?per_page=1"
    releases_2 = f"{api}/repos/acme/glint/releases?page=2"
    page_1 = {
        "data": {
            "repository": {
                "discussions": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "D1"},
                    "nodes": [
                        {
                            "number": 1,
                            "title": "Permission",
                            "bodyText": "Permission issue",
                            "url": "https://github.com/acme/glint/discussions/1",
                        }
                    ],
                }
            }
        }
    }
    page_2 = {
        "data": {
            "repository": {
                "discussions": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "number": 2,
                            "title": "Permission again",
                            "bodyText": "Permission follow-up",
                            "url": "https://github.com/acme/glint/discussions/2",
                        }
                    ],
                }
            }
        }
    }
    transport = FixtureTransport(
        {
            issues_1: json_route(
                json.dumps(
                    [
                        {
                            "number": 10,
                            "title": "Permission issue",
                            "body": "first",
                            "html_url": "https://github.com/acme/glint/issues/10",
                        }
                    ]
                ),
                headers={"link": f'<{issues_2}>; rel="next"'},
            ),
            issues_2: json_route(
                json.dumps(
                    [
                        {
                            "number": 11,
                            "title": "Permission issue",
                            "body": "second",
                            "html_url": "https://github.com/acme/glint/issues/11",
                        }
                    ]
                )
            ),
            releases_1: json_route(
                json.dumps(
                    [
                        {
                            "id": 20,
                            "name": "Permission release",
                            "body": "first",
                            "html_url": "https://github.com/acme/glint/releases/20",
                        }
                    ]
                ),
                headers={"link": f'<{releases_2}>; rel="next"'},
            ),
            releases_2: json_route(
                json.dumps(
                    [
                        {
                            "id": 21,
                            "name": "Permission release",
                            "body": "second",
                            "html_url": "https://github.com/acme/glint/releases/21",
                        }
                    ]
                )
            ),
            f"POST {graphql}": [json_route(json.dumps(page_1)), json_route(json.dumps(page_2))],
        }
    )
    connector = GitHubConnector(
        GitHubConnectorConfig(
            source_connection_id=SOURCE,
            owner="acme",
            repo="glint",
            token_ref="github-token",
            include_repository=False,
            per_page=1,
            cursor_secret=CURSOR_SECRET,
        ),
        transport,
        token_resolver=lambda ref: "fixture-token" if ref == "github-token" else "",
    )

    first = connector.search("permission")
    assert first.next_cursor and first.next_cursor.startswith("github:v1:")
    cursor_state = json.loads(first.next_cursor.removeprefix("github:v1:"))["state"]
    assert set(cursor_state) == {"issues", "releases", "discussions"}

    second = connector.search("permission", first.next_cursor)
    assert second.next_cursor is None
    assert {item.external_id.rsplit(":", 2)[-2] for item in second.items} == {
        "issue",
        "release",
        "discussion",
    }


def test_github_discussions_without_token_is_explicitly_degraded() -> None:
    transport = FixtureTransport({})
    connector = GitHubConnector(
        GitHubConnectorConfig(
            source_connection_id=SOURCE,
            owner="acme",
            repo="glint",
            include_repository=False,
            include_issues=False,
            include_releases=False,
            include_discussions=True,
        ),
        transport,
    )
    page = connector.search("permission")
    assert page.health.status is ConnectorStatus.DEGRADED
    assert page.health.details["degraded_reasons"] == ["discussions_require_graphql_token"]


def test_github_repository_404_is_failed_not_healthy_empty() -> None:
    api = "https://api.github.com"
    repository = f"{api}/repos/acme/missing"
    transport = FixtureTransport({repository: json_route("{}", status_code=404)})
    connector = GitHubConnector(
        GitHubConnectorConfig(
            source_connection_id=SOURCE,
            owner="acme",
            repo="missing",
            include_issues=False,
            include_releases=False,
            include_discussions=False,
            cursor_secret=CURSOR_SECRET,
        ),
        transport,
    )
    page = connector.search("permission")
    assert page.items == []
    assert page.health.status is ConnectorStatus.FAILED
    assert page.health.freshness_state == "failed"
    assert page.health.details["failed_reasons"] == ["repository:404"]


def test_rss_expanded_dc_creator_is_author() -> None:
    url = "https://feeds.example.test/rss.xml"
    xml = """
    <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <channel>
        <item>
          <title>Permission outage</title>
          <link>https://example.test/post</link>
          <description>Permission failure increased.</description>
          <dc:creator>Ada Lovelace</dc:creator>
        </item>
      </channel>
    </rss>
    """
    connector = RssConnector(
        RssConnectorConfig(
            source_connection_id=SOURCE,
            feed_url=url,
            resolver=lambda _: ["93.184.216.34"],
        ),
        FixtureTransport({url: xml_route(xml)}),
    )
    page = connector.search("permission language:en -benign")
    assert len(page.items) == 1
    assert page.items[0].author == "Ada Lovelace"


def test_rss_rejects_userinfo_and_oversized_response() -> None:
    with pytest.raises(ConnectorPartialFailure, match="userinfo"):
        RssConnector(
            RssConnectorConfig(
                source_connection_id=SOURCE,
                feed_url="https://user:pass@feeds.example.test/rss.xml",
                resolver=lambda _: ["93.184.216.34"],
            ),
            FixtureTransport({}),
        ).health()

    url = "https://feeds.example.test/rss.xml"
    transport = FixtureTransport({url: xml_route("<rss>" + ("x" * 32) + "</rss>")})
    connector = RssConnector(
        RssConnectorConfig(
            source_connection_id=SOURCE,
            feed_url=url,
            resolver=lambda _: ["93.184.216.34"],
            max_response_bytes=16,
        ),
        transport,
    )
    with pytest.raises(ConnectorPartialFailure, match="byte cap"):
        connector.search("")


def test_connector_factory_resolves_token_ref_without_inline_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GLINT_SECRET_GITHUB_TOKEN", "secret-value")
    source = SimpleNamespace(
        id=SOURCE, connector_type="github", credential_ref="env://github_token"
    )
    factory = SourceConnectorFactory(FixtureTransport({}), EnvironmentSecretResolver())
    connector = cast(GitHubConnector, factory.create(source, {"owner": "acme", "repo": "glint"}))
    assert connector.config.token_ref == "env://github_token"
    assert connector._headers()["authorization"] == "Bearer secret-value"


def test_environment_secret_resolver_rejects_raw_environment_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "should-not-be-token")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-be-token")
    resolver = EnvironmentSecretResolver()
    with pytest.raises(ConnectorFactoryError):
        resolver("PATH")
    with pytest.raises(ConnectorFactoryError):
        resolver("AWS_SECRET_ACCESS_KEY")
    with pytest.raises(ConnectorFactoryError):
        resolver("vault://github-token")
    with pytest.raises(ConnectorFactoryError):
        resolver("keychain://github-token")
    with pytest.raises(ConnectorFactoryError):
        resolver("env://user:pass@github_token")
    with pytest.raises(ConnectorFactoryError):
        resolver("env://github_token/path")
    with pytest.raises(ConnectorFactoryError):
        resolver("env://github_token?x=1")
    with pytest.raises(ConnectorFactoryError):
        resolver("env://github_token#frag")


def test_connector_factory_does_not_allow_schedule_token_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GLINT_SECRET_PERSISTED_TOKEN", "persisted-secret")
    monkeypatch.setenv("GLINT_SECRET_INLINE_TOKEN", "inline-secret")
    source = SimpleNamespace(
        id=SOURCE, connector_type="github", credential_ref="env://persisted-token"
    )
    factory = SourceConnectorFactory(FixtureTransport({}), EnvironmentSecretResolver())
    connector = cast(
        GitHubConnector,
        factory.create(
            source, {"owner": "acme", "repo": "glint", "token_ref": "env://inline-token"}
        ),
    )
    assert connector.config.token_ref == "env://persisted-token"
    assert connector._headers()["authorization"] == "Bearer persisted-secret"


def test_connector_factory_requires_schedule_within_source_config() -> None:
    source = SimpleNamespace(
        id=SOURCE,
        connector_type="github",
        credential_ref=None,
        freshness={
            "config": {
                "repositories": [
                    {
                        "owner": "acme",
                        "repository": "glint",
                        "include_issues": True,
                        "include_discussions": False,
                        "include_releases": True,
                    }
                ]
            }
        },
    )
    factory = SourceConnectorFactory(FixtureTransport({}), None)
    with pytest.raises(ConnectorFactoryError, match="approved"):
        factory.create(source, {"owner": "evil", "repo": "glint"})
    with pytest.raises(ConnectorFactoryError, match="capabilities"):
        factory.create(source, {"owner": "acme", "repo": "glint", "include_discussions": True})

    rss_source = SimpleNamespace(
        id=SOURCE,
        connector_type="rss",
        credential_ref=None,
        freshness={
            "config": {
                "feeds": [{"name": "Approved", "feed_url": "https://feeds.example.test/rss.xml"}]
            }
        },
    )
    with pytest.raises(ConnectorFactoryError, match="approved"):
        factory.create(rss_source, {"feed_url": "https://evil.example.test/rss.xml"})


def test_github_factory_validates_owner_repo_slugs() -> None:
    source = SimpleNamespace(id=SOURCE, connector_type="github", credential_ref=None)
    factory = SourceConnectorFactory(FixtureTransport({}), None)
    with pytest.raises(ConnectorFactoryError, match="owner/repo"):
        factory.create(source, {"owner": "acme", "repo": "../evil"})
    with pytest.raises(ConnectorFactoryError, match="owner/repo"):
        factory.create(source, {"owner": "acme/evil", "repo": "glint"})


@pytest.mark.parametrize(
    "cursor_state",
    [
        {"issues": "https://evil.example.test/repos/acme/glint/issues?page=2"},
        {"issues": "https://token@api.github.com/repos/acme/glint/issues?page=2"},
        {"issues": "http://api.github.com/repos/acme/glint/issues?page=2"},
        {"issues": "https://api.github.com/repos/other/glint/issues?page=2"},
        {"discussions": "https://api.github.com/graphql?after=leak"},
    ],
)
def test_github_composite_cursor_rejects_untrusted_urls_before_transport(
    cursor_state: dict[str, str],
) -> None:
    transport = FixtureTransport({})
    connector = GitHubConnector(
        GitHubConnectorConfig(
            source_connection_id=SOURCE,
            owner="acme",
            repo="glint",
            token_ref="github-token",
            cursor_secret=CURSOR_SECRET,
        ),
        transport,
        token_resolver=lambda ref: "fixture-token",
    )
    cursor = _signed_github_cursor(cursor_state)
    with pytest.raises(ValueError):
        connector.search("permission", cursor)
    assert transport.requests == []


def _signed_github_cursor(cursor_state: dict[str, str]) -> str:
    state = json.dumps(cursor_state, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(CURSOR_SECRET.encode(), state.encode(), sha256).hexdigest()
    return "github:v1:" + json.dumps(
        {"state": cursor_state, "sig": signature}, sort_keys=True, separators=(",", ":")
    )


def test_create_connector_factory_requires_production_cursor_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GLINT_WORKER_MODE", "production")
    monkeypatch.delenv("GLINT_CONNECTOR_CURSOR_SECRET", raising=False)
    with pytest.raises(ConnectorFactoryError, match="CURSOR_SECRET"):
        create_connector_factory()
    monkeypatch.setenv("GLINT_CONNECTOR_CURSOR_SECRET", "short")
    with pytest.raises(ConnectorFactoryError, match="32 bytes"):
        create_connector_factory()


def test_canonicalize_url_rejects_unsafe_schemes_and_userinfo() -> None:
    assert canonicalize_url("javascript:alert(1)") is None
    assert canonicalize_url("file:///etc/passwd") is None
    assert canonicalize_url("https://user:pass@example.test/a") is None
    assert canonicalize_url("example.test/path") is None
    assert (
        canonicalize_url("https://Example.Test/a/?utm_source=x&b=1") == "https://example.test/a?b=1"
    )


def test_rss_transport_uses_pinned_ip_without_hostname_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def fake_getaddrinfo(host: str, *_args: object) -> list[object]:
        calls.append(("dns", host))
        if host == "feeds.example.test":
            raise AssertionError("pinned-IP transport must not DNS-resolve hostname at connect")
        return []

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            calls.append(("timeout", timeout))

        def connect(self, address: tuple[str, int]) -> None:
            calls.append(("connect", address))

        def sendall(self, data: bytes) -> None:
            calls.append(("send", data))

        def makefile(self, _mode: str) -> object:
            from io import BytesIO

            return BytesIO(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\nok")

        def close(self) -> None:
            calls.append(("close", None))

    class FakeContext:
        def wrap_socket(self, sock: FakeSocket, server_hostname: str) -> FakeSocket:
            calls.append(("sni", server_hostname))
            return sock

    def fake_socket(_family: object, _kind: object) -> FakeSocket:
        return FakeSocket()

    monkeypatch.setattr("connectors.shared.http_transport.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("connectors.shared.http_transport.socket.socket", fake_socket)
    monkeypatch.setattr(
        "connectors.shared.http_transport.ssl.create_default_context", lambda: FakeContext()
    )
    transport = ProductionHttpTransport()
    response = transport.request(
        "GET", "https://feeds.example.test/rss.xml", expected_addresses=("93.184.216.34",)
    )
    assert response.body == b"ok"
    assert ("connect", ("93.184.216.34", 443)) in calls
    assert ("sni", "feeds.example.test") in calls
    assert not any(kind == "dns" for kind, _ in calls)
