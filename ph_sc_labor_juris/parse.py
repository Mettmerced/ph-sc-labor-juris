"""Turn Lawphil and Supreme Court E-Library HTML into case records."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import urljoin

LAWPHIL_MONTHS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)
ELIB_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# Later Lawphil months add a PDF column and extra spaces in the row tag.
_LAWPHIL_ROW = re.compile(
    r"<tr\s+class=\"xy\">\s*<td>\s*<a\s+href=\"([^\"]+)\"[^>]*>\s*([^<]+)</a>\s*<br\s*/?>\s*"
    r"(.*?)</td>\s*<td>(.*?)</td>(?:\s*<td\b[^>]*>.*?</td>)*\s*</tr>",
    re.I | re.S,
)
_ELIB_ITEM = re.compile(
    r"<li[^>]*text-align[^>]*>\s*<a href=['\"]([^'\"]+)['\"]>\s*"
    r"<(?:STRONG|b)>(.*?)</(?:STRONG|b)>\s*<br\s*/?>\s*"
    r"<small>(.*?)</small>\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
    re.I | re.S,
)
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)
_STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.I | re.S)
_CITE = re.compile(r"<cite\b[^>]*>.*?</cite>", re.I | re.S)
_REDACTION = re.compile(
    r"<span\b[^>]*background-color:\s*black[^>]*>\s*</span>",
    re.I | re.S,
)
_BREAK = re.compile(r"<br\s*/?>", re.I)
_BLOCK_END = re.compile(r"</(?:p|div|h\d|tr|li)>", re.I)
_SPACE = re.compile(r"[ \t]+\n")
_BLANK = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]{2,}")
_HEAD = re.compile(r"<head\b[^>]*>.*?</head>", re.I | re.S)
_BLOCKQUOTE = re.compile(r"<blockquote\b[^>]*>(.*)</blockquote>", re.I | re.S)
_DECISION_MARK = re.compile(
    r"D\s*E\s*C\s*I\s*S\s*I\s*O\s*N|R\s*E\s*S\s*O\s*L\s*U\s*T\s*I\s*O\s*N",
    re.I,
)


@dataclass(frozen=True)
class Listing:
    docket: str
    title: str
    decided_on: str
    url: str
    source: str
    elib_id: str | None = None


def lawphil_month_url(year: int, month: int) -> str:
    slug = LAWPHIL_MONTHS[month - 1]
    return f"https://lawphil.net/judjuris/juri{year}/{slug}{year}/{slug}{year}.html"


def elib_month_url(year: int, month: int) -> str:
    return (
        "https://elibrary.judiciary.gov.ph/thebookshelf/docmonth/"
        f"{ELIB_MONTHS[month - 1]}/{year}/1"
    )


def elib_friendly_url(elib_id: str) -> str:
    return f"https://elibrary.judiciary.gov.ph/thebookshelf/showdocsfriendly/1/{elib_id}"


def _clean_fragment(fragment: str) -> str:
    text = _TAG.sub(" ", fragment)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = _SPACES.sub(" ", text)
    return text.strip(" \t\r\n-")


def parse_lawphil_index(page_html: str, page_url: str) -> list[Listing]:
    listings: list[Listing] = []
    for match in _LAWPHIL_ROW.finditer(page_html):
        href, docket, decided_on, title_html = match.groups()
        listings.append(
            Listing(
                docket=_clean_fragment(docket),
                title=_clean_fragment(title_html),
                decided_on=_clean_fragment(decided_on),
                url=urljoin(page_url, href.strip()),
                source="lawphil",
            )
        )
    return listings


def parse_elib_index(page_html: str) -> list[Listing]:
    listings: list[Listing] = []
    for match in _ELIB_ITEM.finditer(page_html):
        href, docket, title_html, decided_on = match.groups()
        elib_id = None
        id_match = re.search(r"/showdocs/\d+/(\d+)", href)
        if id_match:
            elib_id = id_match.group(1)
        listings.append(
            Listing(
                docket=_clean_fragment(docket),
                title=_clean_fragment(title_html),
                decided_on=_clean_fragment(decided_on),
                url=href.strip(),
                source="elibrary",
                elib_id=elib_id,
            )
        )
    return listings


def _decision_fragment(page_html: str) -> str:
    """Return the HTML that holds the opinion.

    Lawphil wraps the whole decision in one blockquote. The E-Library printer
    page puts the opinion in the body and uses blockquote only for quotations,
    so the dispositive word already appears before the first quotation.
    """
    match = _BLOCKQUOTE.search(page_html)
    if not match or len(match.group(1)) < 400:
        return page_html
    before = _HEAD.sub(" ", page_html[: match.start()])
    before = _SCRIPT.sub(" ", before)
    before = _STYLE.sub(" ", before)
    before_text = _TAG.sub(" ", before)
    if _DECISION_MARK.search(before_text):
        return page_html
    return match.group(1)


def html_to_text(page_html: str) -> str:
    body = _HEAD.sub(" ", _decision_fragment(page_html))
    body = _SCRIPT.sub(" ", body)
    body = _STYLE.sub(" ", body)
    body = _CITE.sub(" ", body)
    body = _REDACTION.sub(" [redacted] ", body)
    body = _BREAK.sub("\n", body)
    body = _BLOCK_END.sub("\n\n", body)
    text = _TAG.sub(" ", body)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACE.sub("\n", text)
    text = _SPACES.sub(" ", text)
    text = _BLANK.sub("\n\n", text)
    text = text.strip()
    for marker in ("The Lawphil Project", "Source: Supreme Court E-Library"):
        footer = text.find(marker)
        if footer > 0:
            text = text[:footer].strip()
    return text


def looks_like_decision(text: str) -> bool:
    if len(text) < 400:
        return False
    folded = text.upper()
    return (
        "G.R." in text
        or "D E C I S I O N" in folded
        or "DECISION" in folded
        or "R E S O L U T I O N" in folded
    )
