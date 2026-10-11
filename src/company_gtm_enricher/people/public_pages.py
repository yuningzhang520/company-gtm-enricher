"""Small, credential-free reader for explicitly allowed public HTML pages."""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from email.message import Message
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit


class PageFetchError(RuntimeError):
    """A page could not be read; messages never contain upstream content."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    html: str


def _hostname(value: str) -> str:
    try:
        host = value.rstrip(".").encode("idna").decode("ascii").lower()
        # IPv6 literals are allowed only when their resolved address is public.
        if ":" in host:
            return str(ipaddress.IPv6Address(host))
        if not host or len(host) > 253 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            raise ValueError
        return host
    except (AttributeError, UnicodeError, ValueError):
        raise PageFetchError("Public page host is invalid.") from None


def _checked_url(url: str, allowed_hosts: set[str]) -> tuple[str, str, str]:
    try:
        if not isinstance(url, str) or re.search(r"[\x00-\x20\x7f\\]", url):
            raise ValueError
        parsed = urlsplit(url)
        if (
            parsed.scheme.lower() != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)
        ):
            raise ValueError
        host = _hostname(parsed.hostname)
        if host == "linkedin.com" or host.endswith(".linkedin.com"):
            raise PageFetchError("LinkedIn pages cannot be fetched.")
        if host not in {_hostname(value) for value in allowed_hosts}:
            raise PageFetchError("Public page host is not allowed.")
        authority = f"[{host}]" if ":" in host else host
        path = parsed.path or "/"
        normalized = urlunsplit(("https", authority, path, parsed.query, ""))
        target = path + ("?" + parsed.query if parsed.query else "")
        return normalized, host, target
    except (TypeError, ValueError):
        raise PageFetchError("Public page URL must use HTTPS without credentials on port 443.") from None


def _public_ip(value: str) -> str:
    try:
        if "%" in value:
            raise ValueError
        address = ipaddress.ip_address(value)
        mapped = getattr(address, "ipv4_mapped", None)
        for item in (address, mapped) if mapped is not None else (address,):
            if (
                not item.is_global or item.is_multicast or item.is_reserved
                or item.is_unspecified or item.is_loopback or item.is_link_local
                or getattr(item, "is_site_local", False)
            ):
                raise ValueError
        return str(address)
    except (TypeError, ValueError):
        raise PageFetchError("Public page host must resolve only to public addresses.") from None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the checked IP without a second DNS lookup; verify host TLS."""

    def __init__(self, *, host: str, ip: str, timeout: float) -> None:
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        family = socket.AF_INET6 if ":" in self._ip else socket.AF_INET
        raw_socket = socket.socket(family, socket.SOCK_STREAM)
        try:
            raw_socket.settimeout(self.timeout)
            address = (self._ip, 443, 0, 0) if family == socket.AF_INET6 else (self._ip, 443)
            raw_socket.connect(address)
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


class PublicPageClient:
    """Read HTML with a per-call HTTP attempt cap, including redirects/failures.

    No ambient proxies, cookies, authentication, retries, or script execution are
    involved. DNS and connection factories are injectable for offline tests.
    """

    def __init__(
        self, timeout: float = 10, max_bytes: int = 2_000_000,
        *, resolver: Optional[Callable] = None, connection_factory: Optional[Callable] = None,
    ) -> None:
        if isinstance(timeout, bool) or not 0 < timeout <= 120:
            raise ValueError("Public page timeout must be between 0 and 120 seconds.")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("Public page size limit must be a positive integer.")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._resolve = resolver or socket.getaddrinfo
        self._connection = connection_factory or _PinnedHTTPSConnection
        self.usage: dict[str, int] = {"page_requests": 0}

    def _address(self, host: str) -> str:
        try:
            records = self._resolve(host, 443, type=socket.SOCK_STREAM)
            if not records:
                raise PageFetchError("Public page DNS lookup returned no addresses.")
            addresses = []
            for family, _, _, _, address in records:
                if family not in (socket.AF_INET, socket.AF_INET6):
                    raise PageFetchError("Public page DNS returned an unsupported address.")
                addresses.append(_public_ip(address[0]))
            return addresses[0]
        except PageFetchError:
            raise
        except Exception:
            raise PageFetchError("Public page DNS lookup failed.") from None

    def fetch(self, url: str, *, allowed_hosts: set[str], max_requests: int = 1) -> FetchedPage:
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError("Public page request limit must be a positive integer.")
        for attempt in range(max_requests):
            normalized, host, target = _checked_url(url, allowed_hosts)
            ip = self._address(host)
            connection = None
            try:
                connection = self._connection(host=host, ip=ip, timeout=self.timeout)
                self.usage["page_requests"] += 1
                connection.request("GET", target, headers={
                    "Accept": "text/html, application/xhtml+xml",
                    "Accept-Encoding": "identity",
                    "User-Agent": "CompanyGTMEnricher/0.1 (public company evidence)",
                    "Connection": "close",
                })
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location:
                        raise PageFetchError("Public page redirect has no destination.")
                    # Validate even when the request budget is exhausted.
                    url = _checked_url(urljoin(normalized, location), allowed_hosts)[0]
                    if attempt + 1 == max_requests:
                        raise PageFetchError("Public page redirect reached the request limit.")
                    continue
                if response.status != 200:
                    raise PageFetchError("Public page server did not return a successful response.")
                mime = Message()
                mime["Content-Type"] = response.getheader("Content-Type", "")
                if mime.get_content_type() not in ("text/html", "application/xhtml+xml"):
                    raise PageFetchError("Public page response is not HTML.")
                if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
                    raise PageFetchError("Public page response has unsupported content encoding.")
                body = response.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    raise PageFetchError("Public page response exceeded the size limit.")
                encoding = mime.get_content_charset() or "utf-8"
                return FetchedPage(normalized, body.decode(encoding, errors="replace"))
            except PageFetchError:
                raise
            except Exception:
                raise PageFetchError("Public page request failed.") from None
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
        raise AssertionError("Unreachable public page request state.")
