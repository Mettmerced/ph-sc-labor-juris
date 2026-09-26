"""SQLite catalog of decisions, chunks, and the BM25 index."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path("data") / "corpus.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    gr_key TEXT PRIMARY KEY,
    docket TEXT NOT NULL,
    title TEXT NOT NULL,
    decided_on TEXT,
    year INTEGER,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    elib_id TEXT,
    text TEXT,
    is_labor INTEGER,
    reason TEXT,
    checked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS months (
    source TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    listed INTEGER NOT NULL,
    PRIMARY KEY (source, year, month)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    gr_key TEXT NOT NULL,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    n_tokens INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS postings (
    term TEXT NOT NULL,
    chunk_id INTEGER NOT NULL,
    tf INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS postings_term ON postings(term);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    return connection


def month_already_listed(connection: sqlite3.Connection, source: str, year: int, month: int) -> bool:
    row = connection.execute(
        "SELECT 1 FROM months WHERE source = ? AND year = ? AND month = ?",
        (source, year, month),
    ).fetchone()
    return row is not None


def mark_month(
    connection: sqlite3.Connection, source: str, year: int, month: int, listed: int
) -> None:
    connection.execute(
        """
        INSERT INTO months (source, year, month, listed)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source, year, month) DO UPDATE SET listed = excluded.listed
        """,
        (source, year, month, listed),
    )


def upsert_listing(
    connection: sqlite3.Connection,
    *,
    gr_key: str,
    docket: str,
    title: str,
    decided_on: str,
    year: int,
    url: str,
    source: str,
    elib_id: str | None,
) -> None:
    existing = connection.execute(
        "SELECT source, elib_id, url, checked FROM cases WHERE gr_key = ?",
        (gr_key,),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO cases (
                gr_key, docket, title, decided_on, year, url, source, elib_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (gr_key, docket, title, decided_on, year, url, source, elib_id),
        )
        return

    # Prefer the official e-Library copy when both sources list the same case.
    if source == "elibrary" and existing["source"] != "elibrary" and not existing["checked"]:
        connection.execute(
            """
            UPDATE cases
            SET docket = ?, title = ?, decided_on = ?, year = ?, url = ?, source = ?, elib_id = ?
            WHERE gr_key = ?
            """,
            (docket, title, decided_on, year, url, source, elib_id, gr_key),
        )
    elif elib_id and not existing["elib_id"]:
        connection.execute(
            "UPDATE cases SET elib_id = ? WHERE gr_key = ?",
            (elib_id, gr_key),
        )


def pending_cases(connection: sqlite3.Connection, limit: int | None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM cases WHERE checked = 0 ORDER BY year, gr_key"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return list(connection.execute(sql))


def replace_case(
    connection: sqlite3.Connection,
    *,
    gr_key: str,
    docket: str,
    title: str,
    decided_on: str,
    year: int,
    url: str,
    source: str,
    text: str,
) -> None:
    """Insert or replace a kept labor decision from a case file."""
    connection.execute(
        """
        INSERT INTO cases (
            gr_key, docket, title, decided_on, year, url, source, text, is_labor, reason, checked
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'case file', 1)
        ON CONFLICT(gr_key) DO UPDATE SET
            docket = excluded.docket,
            title = excluded.title,
            decided_on = excluded.decided_on,
            year = excluded.year,
            url = excluded.url,
            source = excluded.source,
            text = excluded.text,
            is_labor = 1,
            reason = 'case file',
            checked = 1
        """,
        (gr_key, docket, title, decided_on, year, url, source, text),
    )


def save_decision(
    connection: sqlite3.Connection,
    gr_key: str,
    text: str | None,
    is_labor: bool | None,
    reason: str,
) -> None:
    connection.execute(
        """
        UPDATE cases
        SET text = ?, is_labor = ?, reason = ?, checked = 1
        WHERE gr_key = ?
        """,
        (text, None if is_labor is None else int(is_labor), reason, gr_key),
    )


def labor_cases(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            SELECT gr_key, docket, title, decided_on, year, url, text
            FROM cases
            WHERE is_labor = 1 AND text IS NOT NULL
            ORDER BY year, gr_key
            """
        )
    )


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    def one(sql: str) -> int:
        return int(connection.execute(sql).fetchone()[0])

    return {
        "listed": one("SELECT COUNT(*) FROM cases"),
        "checked": one("SELECT COUNT(*) FROM cases WHERE checked = 1"),
        "labor": one("SELECT COUNT(*) FROM cases WHERE is_labor = 1"),
        "pending": one("SELECT COUNT(*) FROM cases WHERE checked = 0"),
        "chunks": one("SELECT COUNT(*) FROM chunks"),
    }


def clear_index(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM postings")
    connection.execute("DELETE FROM chunks")
    connection.execute("DELETE FROM meta")
