"""Decide whether a Supreme Court decision is a labor case."""

from __future__ import annotations

import re

# Titles that are labor cases even before the full text is read.
_STRONG_TITLE = re.compile(
    r"("
    r"national labor relations|"
    r"\bnlrc\b|"
    r"labor arbiter|"
    r"labor code|"
    r"department of labor|"
    r"secretary of labor|"
    r"sec\.?\s+of labor|"
    r"ministry of labor|"
    r"\bpoea\b|"
    r"\bdole\b|"
    r"illegal dismissal|"
    r"unfair labor"
    r")",
    re.I,
)

# Broader title hints. These still need support in the text.
_TITLE_HINT = re.compile(
    r"("
    r"employee|employer|\bunion\b|seafarer|seaman|seamen|"
    r"overseas filipino|\bofw\b|collective bargaining|"
    r"backwages|separation pay|security of tenure|"
    r"wage order|\bstrike\b|lockout|migrant worker|"
    r"workmen's compensation|employees' compensation|"
    r"recruitment agency|\bdole\b"
    r")",
    re.I,
)

_TEXT_SIGNALS: list[tuple[str, re.Pattern[str]]] = [
    ("nlrc", re.compile(r"national labor relations commission|\bnlrc\b", re.I)),
    ("labor-code", re.compile(r"labor code", re.I)),
    ("labor-arbiter", re.compile(r"labor arbiter", re.I)),
    ("illegal-dismissal", re.compile(r"illegal dismissal", re.I)),
    ("poea", re.compile(r"\bpoea\b|philippine overseas employment", re.I)),
    ("dole", re.compile(r"department of labor and employment|\bdole\b", re.I)),
    ("security-of-tenure", re.compile(r"security of tenure", re.I)),
    ("cba", re.compile(r"collective bargaining", re.I)),
    ("ulp", re.compile(r"unfair labor practice", re.I)),
    ("seafarer", re.compile(r"seafarer|seaman|seamen", re.I)),
    ("backwages", re.compile(r"backwages|separation pay", re.I)),
    (
        "labor-article",
        re.compile(r"article\s+(?:27[89]|28[0-9]|29[0-9]|30[0-2])\b", re.I),
    ),
]


def title_is_strong(title: str) -> bool:
    return bool(_STRONG_TITLE.search(title or ""))


def title_is_candidate(title: str) -> bool:
    return title_is_strong(title) or bool(_TITLE_HINT.search(title or ""))


def text_signals(text: str) -> list[str]:
    found = [name for name, pattern in _TEXT_SIGNALS if pattern.search(text or "")]
    return found


def classify(title: str, text: str) -> tuple[bool, str]:
    """Return whether the decision is a labor case, and a short reason."""
    signals = text_signals(text)
    if title_is_strong(title):
        return True, "title names a labor tribunal, statute, or doctrine"
    if title_is_candidate(title) and signals:
        return True, "title looks like labor and the text discusses " + ", ".join(signals)
    if len(signals) >= 2:
        return True, "text discusses " + ", ".join(signals)
    if signals:
        return False, "only a passing labor reference: " + ", ".join(signals)
    return False, "no labor doctrine in the title or text"
