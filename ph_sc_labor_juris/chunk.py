"""Split a decision into overlapping passages for retrieval."""

from __future__ import annotations

import re

_PARAGRAPH = re.compile(r"\n\s*\n")


def _split_at(text: str, size: int) -> int:
    if len(text) <= size:
        return len(text)
    window = text[:size]
    space = window.rfind(" ")
    if space >= size // 2:
        return space
    return size


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    if 0 <= space < len(tail) - 1:
        tail = tail[space + 1 :]
    return tail.lstrip()


def chunk_text(text: str, size: int = 1400, overlap: int = 200) -> list[str]:
    paragraphs = [part.strip() for part in _PARAGRAPH.split(text or "") if part.strip()]
    if not paragraphs:
        compact = (text or "").strip()
        return [compact] if compact else []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = _overlap_tail(current, overlap)
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        else:
            current = paragraph
        while len(current) > size:
            cut = _split_at(current, size)
            piece = current[:cut].strip()
            if not piece:
                break
            chunks.append(piece)
            remainder = current[cut:].strip()
            tail = _overlap_tail(piece, overlap)
            current = f"{tail}\n\n{remainder}".strip() if tail else remainder
            if not remainder:
                break
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]
