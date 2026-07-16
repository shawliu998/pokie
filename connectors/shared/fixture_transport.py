"""Deterministic transport for connector contract tests and smoke runs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from connectors.shared.contracts import ConnectorTimeout, TransportResponse


@dataclass(slots=True)
class FixtureRoute:
    status_code: int
    body: bytes
    headers: dict[str, str]


class FixtureTransport:
    """A no-network transport with URL-keyed responses and call counters."""

    def __init__(
        self,
        routes: Mapping[str, FixtureRoute | list[FixtureRoute]],
        timeout_urls: set[str] | None = None,
    ) -> None:
        self._routes: dict[str, list[FixtureRoute]] = {}
        for url, route in routes.items():
            self._routes[url] = list(route) if isinstance(route, list) else [route]
        self._timeout_urls = timeout_urls or set()
        self.calls: dict[str, int] = defaultdict(int)
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
        expected_addresses: tuple[str, ...] | None = None,
    ) -> TransportResponse:
        del timeout_seconds, expected_addresses
        route_key = url
        if method.upper() == "POST" and body is not None:
            route_key = f"POST {url}"
        self.calls[route_key] += 1
        self.requests.append(
            {"method": method.upper(), "url": url, "headers": dict(headers or {}), "body": body}
        )
        if url in self._timeout_urls:
            raise ConnectorTimeout(f"fixture timeout for {url}")
        routes = self._routes.get(route_key) or self._routes.get(url)
        if not routes:
            return TransportResponse(status_code=404, headers={}, body=b"", url=url)
        index = min(self.calls[route_key] - 1, len(routes) - 1)
        route = routes[index]
        return TransportResponse(
            status_code=route.status_code, headers=route.headers, body=route.body, url=url
        )


def json_route(
    body: str, status_code: int = 200, headers: dict[str, str] | None = None
) -> FixtureRoute:
    return FixtureRoute(
        status_code=status_code,
        body=body.encode("utf-8"),
        headers={"content-type": "application/json", **(headers or {})},
    )


def xml_route(
    body: str, status_code: int = 200, headers: dict[str, str] | None = None
) -> FixtureRoute:
    return FixtureRoute(
        status_code=status_code,
        body=body.encode("utf-8"),
        headers={"content-type": "application/xml", **(headers or {})},
    )
