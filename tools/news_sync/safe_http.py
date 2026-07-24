"""SSRF-safe HTTP fetching with DNS-pinned connections."""

from __future__ import annotations

import http.client
import ipaddress
import socket
from dataclasses import dataclass
from email.message import Message
from typing import Mapping, Sequence
from urllib.parse import SplitResult, urljoin, urlsplit


REDIRECT_STATUSES = {301, 302, 303, 307, 308}
DEFAULT_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class PublicTarget:
    parsed: SplitResult
    host: str
    port: int
    addresses: tuple[str, ...]


def host_matches_allowed_domain(host: str, allowed_domains: Sequence[str]) -> bool:
    normalized_host = host.casefold().rstrip(".")
    return any(
        normalized_host == domain or normalized_host.endswith("." + domain)
        for value in allowed_domains
        if (domain := str(value).strip().casefold().rstrip("."))
    )


def is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return bool(address.is_global)


def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise RuntimeError(f"DNS resolution failed for {host}") from exc

    addresses: list[str] = []
    for record in records:
        value = str(record[4][0]).split("%", 1)[0]
        if value not in addresses:
            addresses.append(value)
    if not addresses:
        raise RuntimeError(f"DNS returned no addresses for {host}")
    if any(not is_public_ip(value) for value in addresses):
        raise RuntimeError(f"DNS returned a non-public address for {host}")

    # Cloud functions commonly have IPv4 egress even when IPv6 is unavailable.
    addresses.sort(key=lambda value: ipaddress.ip_address(value).version)
    return tuple(addresses)


def validate_public_target(
    url: str,
    *,
    allowed_domains: Sequence[str] = (),
    allow_any_public: bool = False,
) -> PublicTarget:
    value = str(url).strip()
    if not value or any(character in value for character in "\r\n\x00"):
        raise RuntimeError("article URL is invalid")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    except ValueError as exc:
        raise RuntimeError("article URL is invalid") from exc
    if parsed.scheme.casefold() not in {"http", "https"} or not host:
        raise RuntimeError("article URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError("article URL credentials are not allowed")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise RuntimeError("article URL host is not public")
    if not allow_any_public and not host_matches_allowed_domain(host, allowed_domains):
        raise RuntimeError("article URL host is not allowed")

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise RuntimeError("article URL host is invalid") from exc
    return PublicTarget(
        parsed=parsed,
        host=ascii_host,
        port=port,
        addresses=resolve_public_addresses(ascii_host, port),
    )


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection preserving original TLS SNI while using a pinned IP."""

    def __init__(self, host: str, pinned_ip: str, port: int, *, timeout: int) -> None:
        self.pinned_ip = pinned_ip
        super().__init__(host, port=port, timeout=timeout)

    def connect(self) -> None:
        self.sock = self._create_connection(
            (self.pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()
        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


def _host_header(target: PublicTarget) -> str:
    host = f"[{target.host}]" if ":" in target.host else target.host
    default_port = 443 if target.parsed.scheme.casefold() == "https" else 80
    return host if target.port == default_port else f"{host}:{target.port}"


def _request_target(parsed: SplitResult) -> str:
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    return target


def request_pinned(
    target: PublicTarget,
    *,
    timeout: int,
    headers: Mapping[str, str],
) -> tuple[http.client.HTTPResponse, http.client.HTTPConnection]:
    pinned_ip = target.addresses[0]
    if target.parsed.scheme.casefold() == "https":
        connection: http.client.HTTPConnection = PinnedHTTPSConnection(
            target.host,
            pinned_ip,
            target.port,
            timeout=timeout,
        )
    else:
        connection = http.client.HTTPConnection(pinned_ip, port=target.port, timeout=timeout)
    request_headers = dict(headers)
    request_headers["Host"] = _host_header(target)
    try:
        connection.request("GET", _request_target(target.parsed), headers=request_headers)
        return connection.getresponse(), connection
    except Exception:
        connection.close()
        raise


def response_charset(headers: Message) -> str:
    return headers.get_content_charset() or "utf-8"


def fetch_public_text(
    url: str,
    timeout: int,
    *,
    max_bytes: int,
    allowed_domains: Sequence[str] = (),
    allow_any_public: bool = False,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    headers: Mapping[str, str] | None = None,
) -> str:
    request_headers = dict(headers or {})
    current_url = url
    for redirect_count in range(max_redirects + 1):
        target = validate_public_target(
            current_url,
            allowed_domains=allowed_domains,
            allow_any_public=allow_any_public,
        )
        response, connection = request_pinned(target, timeout=timeout, headers=request_headers)
        try:
            if response.status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise RuntimeError(f"HTTP {response.status} redirect is missing Location")
                if redirect_count >= max_redirects:
                    raise RuntimeError("too many redirects")
                current_url = urljoin(current_url, location)
                continue
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"HTTP {response.status}")
            content_length = response.getheader("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise RuntimeError("response body exceeds the configured byte limit")
                except ValueError:
                    pass
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise RuntimeError("response body exceeds the configured byte limit")
            return raw.decode(response_charset(response.headers), errors="replace")
        finally:
            response.close()
            connection.close()
    raise RuntimeError("too many redirects")
