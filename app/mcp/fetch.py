"""The `fetch_page` tool: read the text of a web page a search result pointed to.

A search snippet is two sentences. The Analyst can do far more with the page it
came from, so the web researcher follows the top results through this tool.

The URLs come from a search engine, i.e. from the open internet, so this is the
one place in the app where the server makes a request to an address it does not
control. Hence the guards: http(s) only, public addresses only (no localhost,
private ranges, or cloud metadata endpoints), every redirect hop re-checked,
and hard caps on time and size. Known limit: the host is resolved here and again
by `requests` when it connects, so a DNS-rebinding attacker could in principle
swap the answer in between; pinning the resolved IP would close that and is not
done here.
"""

import ipaddress
import json
import logging
import re
import socket
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from app.config import get_settings

log = logging.getLogger("agentdesk.fetch")

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
MAX_CHARS_CEILING = 20_000
ALLOWED_PORTS = (None, 80, 443)
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
STRIP_SELECTORS = (
    ".mw-editsection, .reference, .navbox, .infobox, .hatnote, .sidebar, .ambox, .mw-empty-elt"
)
STRIP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg")
USER_AGENT = "Mozilla/5.0 (compatible; AgentDesk/1.0)"


class FetchError(Exception):
    """A page that should not, or could not, be read."""


def _is_public_ip(raw: str) -> bool:
    ip = ipaddress.ip_address(raw.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


def check_url(url: str) -> None:
    """Raise FetchError unless `url` is an http(s) URL on a public host."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"unsupported scheme {parts.scheme!r}")
    if not parts.hostname:
        raise FetchError("URL has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise FetchError("URL has an invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise FetchError(f"port {port} is not allowed")
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror as exc:
        raise FetchError(f"cannot resolve {parts.hostname!r}") from exc
    if not infos or not all(_is_public_ip(info[4][0]) for info in infos):
        raise FetchError(f"{parts.hostname!r} does not resolve to a public address")


def _read_capped(resp: requests.Response) -> bytes:
    body = bytearray()
    for chunk in resp.iter_content(chunk_size=16_384):
        body.extend(chunk)
        if len(body) >= MAX_BYTES:
            break
    return bytes(body[:MAX_BYTES])


def extract_text(html: str, max_chars: int) -> tuple[str, str]:
    """(title, readable text) from an HTML document, truncated to `max_chars`."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for tag in soup(STRIP_TAGS):
        tag.decompose()
    for noise in soup.select(STRIP_SELECTORS):
        noise.decompose()
    # On a MediaWiki page the article body is the content; the rest is site chrome.
    root = soup.select_one("#mw-content-text") or soup.body or soup
    text = re.sub(r"\s+", " ", root.get_text(" ", strip=True)).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "..."
    return title, text


def fetch_page_impl(url: str, max_chars: int | None = None) -> str:
    """Fetch `url` and return JSON: {url, title, text} or {url, error}."""
    settings = get_settings()
    max_chars = settings.fetch_max_chars if max_chars is None else max_chars
    max_chars = max(200, min(max_chars, MAX_CHARS_CEILING))
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current)
            resp = requests.get(
                current,
                headers={"User-Agent": USER_AGENT},
                timeout=settings.tool_timeout,
                allow_redirects=False,
                stream=True,
            )
            try:
                if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if not location:
                        raise FetchError("redirect without a Location header")
                    current = urljoin(current, location)
                    continue
                resp.raise_for_status()
                ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if ctype not in TEXT_TYPES:
                    raise FetchError(f"not a text page ({ctype or 'unknown type'})")
                body = _read_capped(resp)
                encoding = resp.encoding or "utf-8"
            finally:
                resp.close()
            title, text = extract_text(body.decode(encoding, errors="replace"), max_chars)
            if not text:
                raise FetchError("page had no readable text")
            return json.dumps({"url": current, "title": title, "text": text}, ensure_ascii=False)
        raise FetchError("too many redirects")
    except FetchError as exc:
        return json.dumps({"url": url, "error": str(exc)})
    except Exception as exc:
        log.warning("fetch failed for %r: %s", url, exc)
        return json.dumps({"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]})
