"""Okapi BM25 over the stored labor-case passages."""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter

from ph_sc_labor_juris.chunk import chunk_text

_TOKEN = re.compile(r"[a-z0-9]+")
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def build_index(connection: sqlite3.Connection) -> int:
    from ph_sc_labor_juris.store import clear_index, labor_cases

    clear_index(connection)
    written = 0
    term_df: Counter[str] = Counter()
    total_tokens = 0
    pending_postings: list[tuple[str, int, int]] = []

    for case in labor_cases(connection):
        header = f"{case['docket']} ({case['decided_on']}). {case['title']}."
        for position, passage in enumerate(chunk_text(case["text"] or "")):
            body = f"{header}\n\n{passage}"
            tokens = tokenize(body)
            if not tokens:
                continue
            cursor = connection.execute(
                """
                INSERT INTO chunks (gr_key, position, text, n_tokens)
                VALUES (?, ?, ?, ?)
                """,
                (case["gr_key"], position, body, len(tokens)),
            )
            chunk_id = int(cursor.lastrowid)
            counts = Counter(tokens)
            for term, tf in counts.items():
                pending_postings.append((term, chunk_id, tf))
                term_df[term] += 1
            total_tokens += len(tokens)
            written += 1

    if pending_postings:
        connection.executemany(
            "INSERT INTO postings (term, chunk_id, tf) VALUES (?, ?, ?)",
            pending_postings,
        )
    avgdl = (total_tokens / written) if written else 0.0
    connection.execute(
        "INSERT INTO meta (key, value) VALUES ('n_docs', ?), ('avgdl', ?)",
        (str(written), str(avgdl)),
    )
    connection.commit()
    return written


def search(connection: sqlite3.Connection, query: str, limit: int = 6) -> list[sqlite3.Row]:
    meta = dict(connection.execute("SELECT key, value FROM meta"))
    n_docs = int(meta.get("n_docs", "0"))
    avgdl = float(meta.get("avgdl", "0") or 0)
    if n_docs == 0 or avgdl == 0:
        return []

    scores: dict[int, float] = {}
    lengths: dict[int, int] = {}
    for term in set(tokenize(query)):
        rows = connection.execute(
            """
            SELECT p.chunk_id, p.tf, c.n_tokens
            FROM postings p
            JOIN chunks c ON c.id = p.chunk_id
            WHERE p.term = ?
            """,
            (term,),
        ).fetchall()
        df = len(rows)
        if df == 0:
            continue
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        for row in rows:
            chunk_id = int(row["chunk_id"])
            tf = int(row["tf"])
            doc_len = int(row["n_tokens"])
            lengths[chunk_id] = doc_len
            denom = tf + K1 * (1 - B + B * doc_len / avgdl)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + idf * (tf * (K1 + 1) / denom)

    if not scores:
        return []

    ranked = sorted(scores, key=scores.get, reverse=True)
    chosen: list[int] = []
    per_case: Counter[str] = Counter()
    case_of: dict[int, str] = {}
    if ranked:
        placeholders = ",".join("?" for _ in ranked[:200])
        for row in connection.execute(
            f"SELECT id, gr_key FROM chunks WHERE id IN ({placeholders})",
            ranked[:200],
        ):
            case_of[int(row["id"])] = row["gr_key"]
    for chunk_id in ranked:
        gr_key = case_of.get(chunk_id, "")
        if per_case[gr_key] >= 2:
            continue
        chosen.append(chunk_id)
        per_case[gr_key] += 1
        if len(chosen) >= limit:
            break

    placeholders = ",".join("?" for _ in chosen)
    rows = connection.execute(
        f"""
        SELECT c.id, c.text, c.gr_key, k.docket, k.title, k.decided_on, k.url
        FROM chunks c
        JOIN cases k ON k.gr_key = c.gr_key
        WHERE c.id IN ({placeholders})
        """,
        chosen,
    ).fetchall()
    order = {chunk_id: index for index, chunk_id in enumerate(chosen)}
    return sorted(rows, key=lambda row: order[int(row["id"])])
