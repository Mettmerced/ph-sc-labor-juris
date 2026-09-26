"""Normalize Supreme Court docket numbers so the two sources can be merged."""

from __future__ import annotations

import re

_DOCKET = re.compile(
    r"\b(G\.?\s*R\.?|A\.?\s*M\.?|A\.?\s*C\.?)\s*(?:Nos?\.?)?\s*((?:L\s*-\s*)?\d+)",
    re.I,
)


def gr_key(docket: str) -> str | None:
    """Return a stable key such as ``GR-72654`` or ``GR-L-4521``.

    Consolidated dockets (``G.R. Nos. 72654-61``) use the first number.
    """
    match = _DOCKET.search((docket or "").replace("\xa0", " "))
    if not match:
        return None
    kind = re.sub(r"[^A-Z]", "", match.group(1).upper())
    number = re.sub(r"\s+", "", match.group(2).upper())
    return f"{kind}-{number}"


def is_gr(docket: str) -> bool:
    key = gr_key(docket)
    return key is not None and key.startswith("GR-")
