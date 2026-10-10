"""The fetch_page tool reads URLs that came from the open internet, so its guards matter."""

import json
import socket

import pytest

from app.mcp import fetch
from app.mcp.fetch import FetchError, check_url, extract_text, fetch_page_impl

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda host, port: PUBLIC)


class FakeResponse:
    def __init__(self, body=b"", status=200, headers=None, encoding="utf-8"):
        self._body = body
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.encoding = encoding
        self.is_redirect = status in (301, 302, 303, 307, 308)

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self):
        pass


def _serve(monkeypatch, responses):
    """Make requests.get return `responses` in order, recording each URL asked for."""
    asked = []
    queue = list(responses)

    def fake_get(url, **kwargs):
        asked.append(url)
        assert kwargs["allow_redirects"] is False, "redirects must be followed by hand"
        return queue.pop(0)

    monkeypatch.setattr(fetch.requests, "get", fake_get)
    return asked


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "https://example.com:8443/",
        "http:///nohost",
    ],
)
def test_check_url_rejects_non_public_targets(url):
    with pytest.raises(FetchError):
        check_url(url)


def test_check_url_rejects_a_host_that_resolves_to_a_private_address(monkeypatch):
    private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda host, port: private)

    with pytest.raises(FetchError, match="public address"):
        check_url("https://innocent-looking.example/")


def test_check_url_rejects_if_any_resolved_address_is_private(monkeypatch):
    mixed = PUBLIC + [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda host, port: mixed)

    with pytest.raises(FetchError):
        check_url("https://example.com/")


def test_check_url_accepts_a_public_https_url(public_dns):
    check_url("https://example.com/page")


def test_fetch_returns_title_and_readable_text(public_dns, monkeypatch):
    html = (
        b"<html><head><title>On-call</title><style>x{}</style></head><body>"
        b"<nav>Home | About</nav><script>alert(1)</script>"
        b"<main><h1>Rotations</h1><p>Weekly   rotation,\n handover Monday.</p></main>"
        b"<footer>(c) site</footer></body></html>"
    )
    _serve(monkeypatch, [FakeResponse(html)])

    out = json.loads(fetch_page_impl("https://example.com/oncall"))

    assert out["title"] == "On-call"
    assert out["text"] == "Rotations Weekly rotation, handover Monday."
    assert "alert" not in out["text"] and "Home" not in out["text"]


def test_fetch_truncates_to_max_chars_on_a_word_boundary(public_dns, monkeypatch):
    _serve(monkeypatch, [FakeResponse(b"<p>" + b"word " * 500 + b"</p>")])

    out = json.loads(fetch_page_impl("https://example.com/", max_chars=300))

    assert out["text"].endswith("...")
    assert 200 < len(out["text"]) <= 304


def test_fetch_follows_a_safe_redirect_and_reports_the_final_url(public_dns, monkeypatch):
    asked = _serve(
        monkeypatch,
        [
            FakeResponse(status=301, headers={"Location": "/new"}),
            FakeResponse(b"<p>Moved here.</p>"),
        ],
    )

    out = json.loads(fetch_page_impl("https://example.com/old"))

    assert asked == ["https://example.com/old", "https://example.com/new"]
    assert out["url"] == "https://example.com/new"
    assert out["text"] == "Moved here."


def test_fetch_refuses_a_redirect_into_a_private_address(monkeypatch):
    """The SSRF classic: a public page that bounces to the metadata endpoint."""
    asked = _serve(
        monkeypatch,
        [FakeResponse(status=302, headers={"Location": "http://169.254.169.254/latest/"})],
    )

    def resolve(host, port):
        if host == "example.com":
            return PUBLIC
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 0))]

    monkeypatch.setattr(fetch.socket, "getaddrinfo", resolve)

    out = json.loads(fetch_page_impl("https://example.com/redirect"))

    assert "error" in out and "text" not in out
    assert asked == ["https://example.com/redirect"], "the private hop must never be requested"


def test_fetch_gives_up_after_too_many_redirects(public_dns, monkeypatch):
    loop = [FakeResponse(status=302, headers={"Location": "/again"}) for _ in range(10)]
    _serve(monkeypatch, loop)

    out = json.loads(fetch_page_impl("https://example.com/"))

    assert out["error"] == "too many redirects"


@pytest.mark.parametrize("ctype", ["application/pdf", "image/png", "application/octet-stream"])
def test_fetch_skips_non_text_content(public_dns, monkeypatch, ctype):
    _serve(monkeypatch, [FakeResponse(b"%PDF", headers={"Content-Type": ctype})])

    out = json.loads(fetch_page_impl("https://example.com/file"))

    assert "not a text page" in out["error"]


def test_fetch_reports_http_errors_instead_of_raising(public_dns, monkeypatch):
    _serve(monkeypatch, [FakeResponse(b"nope", status=404)])

    out = json.loads(fetch_page_impl("https://example.com/missing"))

    assert "404" in out["error"]


def test_fetch_caps_how_much_it_downloads_and_returns(public_dns, monkeypatch):
    big = b"<p>" + b"a " * 2_000_000 + b"</p>"
    _serve(monkeypatch, [FakeResponse(big)])

    out = json.loads(fetch_page_impl("https://example.com/huge", max_chars=100_000_000))

    assert len(out["text"]) <= fetch.MAX_CHARS_CEILING + 3


def test_fetch_errors_on_a_page_with_no_text(public_dns, monkeypatch):
    _serve(monkeypatch, [FakeResponse(b"<html><script>x()</script></html>")])

    out = json.loads(fetch_page_impl("https://example.com/"))

    assert out["error"] == "page had no readable text"


def test_extract_text_without_a_title():
    title, text = extract_text("<p>Just text.</p>", 100)

    assert (title, text) == ("", "Just text.")


def test_a_mediawiki_page_yields_the_article_not_the_site_chrome():
    html = (
        "<html><head><title>SRE - Wikipedia</title></head><body>"
        "<div id='mw-navigation'>Jump to content Main menu</div>"
        "<div id='mw-content-text'>"
        "<div class='hatnote'>Not to be confused with X</div>"
        "<p>Site reliability engineering is a discipline.<sup class='reference'>[1]</sup></p>"
        "<span class='mw-editsection'>[edit]</span>"
        "<table class='infobox'><tr><td>Infobox</td></tr></table>"
        "<p>It applies software practice to operations.</p>"
        "</div></body></html>"
    )

    _, text = extract_text(html, 500)

    assert text == (
        "Site reliability engineering is a discipline. It applies software practice to operations."
    )
