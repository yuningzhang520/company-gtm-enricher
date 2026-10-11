import io
import socket
import ssl
from dataclasses import FrozenInstanceError

import pytest

from company_gtm_enricher.people.public_pages import (
    FetchedPage,
    PageFetchError,
    PublicPageClient,
    _PinnedHTTPSConnection,
)


def records(*addresses):
    return [
        (socket.AF_INET6 if ":" in value else socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 443))
        for value in addresses
    ]


class Response(io.BytesIO):
    def __init__(self, body=b"<h1>Company team</h1>", *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = {"content-type": "text/html; charset=utf-8"} if headers is None else {
            key.lower(): value for key, value in headers.items()
        }
        self.read_sizes = []

    def getheader(self, name, default=None):
        return self.headers.get(name.lower(), default)

    def read(self, amount=-1):
        self.read_sizes.append(amount)
        return super().read(amount)


class Connection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def request(self, method, target, *, headers):
        self.requests.append((method, target, headers))
        if isinstance(self.response, Exception):
            raise self.response

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.connections = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        connection = Connection(self.responses.pop(0))
        self.connections.append(connection)
        return connection


def client(*responses, resolver=None, **kwargs):
    transport = Transport(*responses)
    reader = PublicPageClient(
        resolver=resolver or (lambda *args, **kwargs: records("93.184.216.34")),
        connection_factory=transport, **kwargs,
    )
    return reader, transport


def test_public_html_fetch_is_literal_bounded_and_has_no_ambient_credentials(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://secret:password@proxy.example")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai-key")
    monkeypatch.setenv("SERPER_API_KEY", "secret-serper-key")
    response = Response(b'<p>Founder</p><script>alert("never executed")</script>')
    reader, transport = client(response, timeout=7, max_bytes=100)
    page = reader.fetch("https://COMPANY.example.:443/about?lang=en#team", allowed_hosts={"company.EXAMPLE"})
    assert page == FetchedPage("https://company.example/about?lang=en", response.getvalue().decode())
    assert response.read_sizes == [101]
    assert transport.calls == [{"host": "company.example", "ip": "93.184.216.34", "timeout": 7}]
    method, target, headers = transport.connections[0].requests[0]
    assert (method, target) == ("GET", "/about?lang=en")
    assert set(headers) == {"Accept", "Accept-Encoding", "User-Agent", "Connection"}
    assert "secret" not in str(headers)
    assert reader.usage == {"page_requests": 1}
    assert transport.connections[0].closed
    with pytest.raises(FrozenInstanceError):
        page.html = "changed"


@pytest.mark.parametrize("url", [
    "http://company.example/about", "ftp://company.example/about",
    "https://user:secret@company.example/about", "https://user@company.example/about",
    "https://company.example:444/about", "https://company.example:bad/about",
    "https://company.example\\@private.example/about", "https://company.example/\nsecret",
    " https://company.example/about", "https:///about", "not a URL",
    "https://other.example/about", "https://sub.company.example/about",
    "https://company.example.evil.example/about",
])
def test_unsafe_or_non_allowlisted_urls_fail_before_dns_or_requests(url):
    reader, transport = client(resolver=lambda *a, **kw: pytest.fail("unexpected DNS"))
    with pytest.raises(PageFetchError) as error:
        reader.fetch(url, allowed_hosts={"company.example"})
    assert "secret" not in str(error.value)
    assert transport.calls == []
    assert reader.usage == {"page_requests": 0}


@pytest.mark.parametrize("host", ["linkedin.com", "www.linkedin.com", "UK.LinkedIn.COM", "linkedin.com."])
def test_linkedin_is_never_fetched_even_when_explicitly_allowed(host):
    reader, _ = client(resolver=lambda *a, **kw: pytest.fail("unexpected DNS"))
    with pytest.raises(PageFetchError, match="LinkedIn"):
        reader.fetch(f"https://{host}/in/person", allowed_hosts={host})
    assert reader.usage["page_requests"] == 0


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
    "100.64.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "192.0.2.1",
    "::1", "::", "fc00::1", "fe80::1", "fec0::1", "ff02::1", "2001:db8::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "fe80::1%en0",
])
def test_all_dns_answers_must_be_public_not_only_the_first(address):
    reader, transport = client(resolver=lambda *a, **kw: records("93.184.216.34", address))
    with pytest.raises(PageFetchError, match="public addresses"):
        reader.fetch("https://company.example/about", allowed_hosts={"company.example"})
    assert transport.calls == []
    assert reader.usage["page_requests"] == 0


def test_dns_failure_is_sanitized_and_empty_answers_are_rejected():
    def failing_resolver(*args, **kwargs):
        raise OSError("upstream-secret")
    reader, _ = client(resolver=failing_resolver)
    with pytest.raises(PageFetchError, match="DNS lookup failed") as error:
        reader.fetch("https://company.example/about", allowed_hosts={"company.example"})
    assert "upstream-secret" not in str(error.value)
    reader, _ = client(resolver=lambda *a, **kw: [])
    with pytest.raises(PageFetchError, match="no addresses"):
        reader.fetch("https://company.example/about", allowed_hosts={"company.example"})


def test_same_host_and_explicit_second_host_redirects_share_request_budget():
    reader, transport = client(
        Response(status=302, headers={"Location": "/team"}),
        Response(status=307, headers={"Location": "https://jobs.example/company"}),
        Response(b"<p>Company leaders</p>"),
    )
    page = reader.fetch("https://company.example/about", allowed_hosts={"company.example", "jobs.example"}, max_requests=3)
    assert page.url == "https://jobs.example/company"
    assert reader.usage["page_requests"] == 3
    assert [call["host"] for call in transport.calls] == ["company.example", "company.example", "jobs.example"]
    assert all(connection.closed for connection in transport.connections)


def test_redirect_limit_prevents_another_request_and_no_cookie_is_replayed():
    reader, transport = client(Response(status=302, headers={"Location": "/team", "Set-Cookie": "secret=value"}))
    with pytest.raises(PageFetchError, match="request limit"):
        reader.fetch("https://company.example/about", allowed_hosts={"company.example"})
    assert len(transport.calls) == 1
    assert reader.usage["page_requests"] == 1


@pytest.mark.parametrize("destination", [
    "https://evil.example/secret", "http://company.example/secret",
    "https://user:secret@company.example/about", "https://linkedin.com/in/person",
])
def test_redirect_is_revalidated_before_following(destination):
    reader, transport = client(Response(status=302, headers={"Location": destination}))
    with pytest.raises(PageFetchError) as error:
        reader.fetch("https://company.example/about", allowed_hosts={"company.example", "linkedin.com"}, max_requests=2)
    assert "secret" not in str(error.value)
    assert len(transport.calls) == 1
    assert reader.usage["page_requests"] == 1


def test_redirect_rechecks_dns_and_rejects_a_rebound_private_address():
    answers = iter([records("93.184.216.34"), records("127.0.0.1")])
    reader, transport = client(Response(status=302, headers={"Location": "/team"}), resolver=lambda *a, **kw: next(answers))
    with pytest.raises(PageFetchError, match="public addresses"):
        reader.fetch("https://company.example/about", allowed_hosts={"company.example"}, max_requests=2)
    assert len(transport.calls) == 1
    assert reader.usage["page_requests"] == 1


@pytest.mark.parametrize("response", [
    Response(status=403), Response(status=500), Response(status=302, headers={}),
    Response(headers={"Content-Type": "application/json"}), Response(headers={}),
    Response(headers={"Content-Type": "text/html", "Content-Encoding": "gzip"}),
    Response(headers={"Content-Type": "text/html; charset=invalid-encoding-secret"}),
    OSError("secret transport detail"), ssl.SSLCertVerificationError("secret certificate detail"),
])
def test_failed_responses_are_sanitized_closed_and_never_retried(response):
    reader, transport = client(response)
    with pytest.raises(PageFetchError) as error:
        reader.fetch("https://company.example/about", allowed_hosts={"company.example"}, max_requests=3)
    assert "secret" not in str(error.value)
    assert reader.usage["page_requests"] == 1
    assert len(transport.calls) == 1
    assert transport.connections[0].closed


def test_response_byte_limit_includes_one_overflow_byte():
    response = Response(b"123456")
    reader, _ = client(response, max_bytes=5)
    with pytest.raises(PageFetchError, match="size limit"):
        reader.fetch("https://company.example/about", allowed_hosts={"company.example"})
    assert response.read_sizes == [6]


def test_xhtml_and_declared_character_encoding_are_supported():
    reader, _ = client(Response("<p>André</p>".encode("iso-8859-1"), headers={"Content-Type": "application/xhtml+xml; charset=iso-8859-1"}))
    assert reader.fetch("https://company.example", allowed_hosts={"company.example"}).html == "<p>André</p>"


@pytest.mark.parametrize("ip,family,address", [
    ("93.184.216.34", socket.AF_INET, ("93.184.216.34", 443)),
    ("2606:4700:4700::1111", socket.AF_INET6, ("2606:4700:4700::1111", 443, 0, 0)),
])
def test_transport_pins_the_ip_but_verifies_the_original_tls_hostname(monkeypatch, ip, family, address):
    sockets = []
    wrapped = []
    class Socket:
        def __init__(self, *args):
            self.args = args
            sockets.append(self)
        def settimeout(self, timeout):
            self.timeout = timeout
        def connect(self, destination):
            self.destination = destination
        def close(self):
            pass
    monkeypatch.setattr(socket, "socket", Socket)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: pytest.fail("second DNS lookup"))
    def wrap(context, raw, *, server_hostname):
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        wrapped.append((raw, server_hostname))
        return raw
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    connection = _PinnedHTTPSConnection(host="company.example", ip=ip, timeout=9)
    connection.connect()
    assert sockets[0].args == (family, socket.SOCK_STREAM)
    assert sockets[0].destination == address
    assert sockets[0].timeout == 9
    assert wrapped == [(sockets[0], "company.example")]


@pytest.mark.parametrize("kwargs", [{"timeout": 0}, {"timeout": True}, {"timeout": 121}, {"max_bytes": 0}, {"max_bytes": True}, {"max_bytes": 1.5}])
def test_client_configuration_requires_bounded_valid_limits(kwargs):
    with pytest.raises(ValueError):
        PublicPageClient(**kwargs)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_request_budget_must_be_a_positive_integer(limit):
    reader, _ = client()
    with pytest.raises(ValueError):
        reader.fetch("https://company.example/about", allowed_hosts={"company.example"}, max_requests=limit)
