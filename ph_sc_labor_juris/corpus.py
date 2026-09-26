"""Kept labor decisions as JSON files under cases/<year>/<gr_key>.json."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

CASE_FIELDS = (
    "gr_key",
    "docket",
    "title",
    "decided_on",
    "year",
    "url",
    "source",
    "text",
)
MANIFEST_FIELDS = (
    "gr_key",
    "docket",
    "title",
    "decided_on",
    "year",
    "url",
)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _record(data: dict) -> dict:
    year = data.get("year")
    return {
        "gr_key": data.get("gr_key") or "",
        "docket": data.get("docket") or "",
        "title": data.get("title") or "",
        "decided_on": data.get("decided_on") or "",
        "year": int(year) if year else 0,
        "url": data.get("url") or "",
        "source": data.get("source") or "",
        "text": data.get("text") or "",
    }


class CaseCorpus:
    """On-disk labor decisions and the manifest that lists them."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*/*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            record = _record(data)
            if not record["gr_key"] or not record["text"]:
                continue
            self.entries[record["gr_key"]] = record

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, gr_key: str) -> bool:
        return gr_key in self.entries

    def write(self, data: dict) -> None:
        record = _record(data)
        if not record["gr_key"] or not record["text"] or not record["year"]:
            raise ValueError(f"incomplete case record for {record['gr_key'] or data!r}")
        path = self.root / str(record["year"]) / f"{record['gr_key']}.json"
        previous = self._path_for(record["gr_key"])
        atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        if previous is not None and previous != path and previous.exists():
            previous.unlink()
        self.entries[record["gr_key"]] = record
        self.write_manifest()

    def _path_for(self, gr_key: str) -> Path | None:
        if not self.root.exists():
            return None
        matches = list(self.root.glob(f"*/{gr_key}.json"))
        return matches[0] if matches else None

    def write_manifest(self) -> None:
        ordered = sorted(self.entries.values(), key=lambda row: (row["year"], row["gr_key"]))
        manifest = {
            "count": len(ordered),
            "cases": [{field: row[field] for field in MANIFEST_FIELDS} for row in ordered],
        }
        atomic_write(
            self.root / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )


def case_file_count(cases_dir: Path | str) -> int:
    root = Path(cases_dir)
    if not root.exists():
        return 0
    return sum(1 for _ in root.glob("*/*.json"))


def sync_corpus(connection: sqlite3.Connection, corpus: CaseCorpus) -> int:
    """Copy case files into SQLite, and write any stored labor text that has no file yet."""
    from ph_sc_labor_juris.store import replace_case

    loaded = 0
    for record in corpus.entries.values():
        replace_case(
            connection,
            gr_key=record["gr_key"],
            docket=record["docket"],
            title=record["title"],
            decided_on=record["decided_on"],
            year=int(record["year"]),
            url=record["url"],
            source=record["source"] or "lawphil",
            text=record["text"],
        )
        loaded += 1

    rows = connection.execute(
        """
        SELECT gr_key, docket, title, decided_on, year, url, source, text
        FROM cases
        WHERE is_labor = 1 AND text IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        if row["gr_key"] in corpus:
            continue
        if not row["text"] or not row["year"]:
            continue
        corpus.write(
            {
                "gr_key": row["gr_key"],
                "docket": row["docket"],
                "title": row["title"],
                "decided_on": row["decided_on"] or "",
                "year": int(row["year"]),
                "url": row["url"],
                "source": row["source"] or "",
                "text": row["text"],
            }
        )
    connection.commit()
    if corpus.entries and not (corpus.root / "manifest.json").exists():
        corpus.write_manifest()
    return loaded


def load_case_files(connection: sqlite3.Connection, cases_dir: Path | str) -> int:
    """Load kept decisions from JSON so the search index can be built from them."""
    root = Path(cases_dir)
    if not root.exists():
        return 0
    return sync_corpus(connection, CaseCorpus(root))
