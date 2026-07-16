"""Production HTTP transport for SourceConnector implementations."""

from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from http.client import HTTPSConnection
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from connectors.shared.contracts import (
    ConnectorError,
    ConnectorPartialFailure,
    ConnectorTimeout,
    ConnectorTransport,
    TransportResponse,
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(
        self,
        connect_host: str,
        port: int,
        tls_hostname: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(connect_host, port=port, timeout=timeout, context=context)
        self._tls_hostname = tls_hostname
        self._ssl_context = context

    def connect(self) -> None:
        address = ip_address(self.host)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.port))
        except Exception:
            sock.close()
            raise
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self._tls_hostname)


@dataclass(frozen=True, slots=True)
class ProductionHttpTransport(ConnectorTransport):
    """urllib-based transport with timeouts, byte caps, and no automatic redirects."""

    max_response_bytes: int = 2_000_000

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
        expected_addresses: tuple[str, ...] | None = None,
    ) -> TransportResponse:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise ConnectorPartialFailure("connector transport requires https URLs", [])
        if parts.username or parts.password:
            raise ConnectorPartialFailure("connector transport forbids URL userinfo", [])
        if expected_addresses is not None:
            return self._request_pinned_ip(
                method,
                url,
                parts.hostname,
                parts.port or 443,
                expected_addresses,
                headers,
                body,
                timeout_seconds,
            )
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers or {}),
            method=method.upper(),
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            response = opener.open(request, timeout=timeout_seconds)
            with response:
                payload = _read_capped(response, self.max_response_bytes)
                return TransportResponse(
                    status_code=int(response.status),
                    headers={str(key): str(value) for key, value in response.headers.items()},
                    body=payload,
                    url=response.url,
                )
        except urllib.error.HTTPError as exc:
            payload = _read_capped(exc, self.max_response_bytes)
            return TransportResponse(
                status_code=int(exc.code),
                headers={str(key): str(value) for key, value in exc.headers.items()},
                body=payload,
                url=exc.url,
            )
        except TimeoutError as exc:
            raise ConnectorTimeout(f"connector request timed out for {_redact_url(url)}") from exc
        except urllib.error.URLError as exc:
            reason = (
                exc.reason.__class__.__name__ if hasattr(exc, "reason") else exc.__class__.__name__
            )
            raise ConnectorError(
                f"connector request failed for {_redact_url(url)}: {reason}"
            ) from exc

    def _request_pinned_ip(
        self,
        method: str,
        url: str,
        hostname: str,
        port: int,
        expected_addresses: tuple[str, ...],
        headers: Mapping[str, str] | None,
        body: bytes | None,
        timeout_seconds: float,
    ) -> TransportResponse:
        connect_host = _select_expected_address(expected_addresses)
        parts = urlsplit(url)
        request_path = parts.path or "/"
        if parts.query:
            request_path = f"{request_path}?{parts.query}"
        host_header = _host_header(hostname, port)
        request_headers = {"Host": host_header, **dict(headers or {})}
        connection = _PinnedHTTPSConnection(
            connect_host,
            port,
            hostname,
            timeout_seconds,
            ssl.create_default_context(),
        )
        try:
            connection.request(method.upper(), request_path, body=body, headers=request_headers)
            response = connection.getresponse()
            payload = _read_capped(response, self.max_response_bytes)
            return TransportResponse(
                status_code=int(response.status),
                headers={str(key): str(value) for key, value in response.getheaders()},
                body=payload,
                url=url,
            )
        except TimeoutError as exc:
            raise ConnectorTimeout(f"connector request timed out for {_redact_url(url)}") from exc
        except OSError as exc:
            raise ConnectorError(
                f"connector request failed for {_redact_url(url)}: {exc.__class__.__name__}"
            ) from exc
        finally:
            connection.close()


def _read_capped(stream: Any, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = stream.read(min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > max_bytes:
        raise ConnectorPartialFailure("connector response exceeded byte cap", [])
    return payload


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = host
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _select_expected_address(expected_addresses: tuple[str, ...]) -> str:
    if not expected_addresses:
        raise ConnectorPartialFailure("connector expected address set is empty", [])
    try:
        return str(ip_address(expected_addresses[0]))
    except ValueError as exc:
        raise ConnectorPartialFailure("connector expected address is invalid", []) from exc


def _host_header(hostname: str, port: int) -> str:
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    return host if port == 443 else f"{host}:{port}"
