"""Polite HTTP fetches for public decision pages."""

from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = (
    "ph-sc-labor-juris/0.1 "
    "(personal research of public Philippine Supreme Court decisions)"
)

# The E-Library server omits this public GlobalSign intermediate from its chain.
_EXTRA_CA = Path(__file__).parent / "certs" / "globalsign_gcc_r3_ev_tls_ca_2025.pem"


class FetchError(Exception):
    def __init__(self, url: str, message: str, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.status = status


def decode_html(raw: bytes, charset: str | None, *, url: str = "") -> str:
    """Decode a decision page.

    Lawphil pages are Windows-1252 even when a header names another charset.
    E-Library pages are UTF-8.
    """
    host = url.lower()
    if "lawphil.net" in host:
        return raw.decode("cp1252", errors="replace")
    if "elibrary.judiciary.gov.ph" in host:
        return raw.decode("utf-8", errors="replace")
    if charset:
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            pass
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if _EXTRA_CA.exists():
        context.load_verify_locations(cafile=str(_EXTRA_CA))
    return context


class HttpClient:
    def __init__(self, delay: float = 0.8, timeout: float = 60.0):
        self.delay = delay
        self.timeout = timeout
        self._last_request = 0.0
        self._ssl = ssl_context()

    def get(self, url: str) -> str:
        self._pause()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=self._ssl) as response:
                    raw = response.read()
                    charset = response.headers.get_content_charset()
                self._last_request = time.time()
                return decode_html(raw, charset, url=url)
            except urllib.error.HTTPError as error:
                self._last_request = time.time()
                if error.code == 404:
                    raise FetchError(url, f"HTTP 404 for {url}", status=404) from error
                last_error = error
                if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise FetchError(
                    url, f"HTTP {error.code} for {url}", status=error.code
                ) from error
            except urllib.error.URLError as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise FetchError(url, f"Could not fetch {url}: {error.reason}") from error
        raise FetchError(url, f"Could not fetch {url}: {last_error}")

    def _pause(self) -> None:
        elapsed = time.time() - self._last_request
        remaining = self.delay - elapsed
        if self._last_request and remaining > 0:
            time.sleep(remaining)
