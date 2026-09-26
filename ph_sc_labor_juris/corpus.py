"""Labor decisions stored as JSON files under cases/<year>/<gr_key>.json."""

from __future__ import annotations

import json
import re
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
_KEY = re.compile(r"^GR-(?:L-)?\d+$")


def _meta(record: dict) -> dict:
    return {
        "gr_key": record["gr_key"],
        "docket": record["docket"],
        "title": record["title"],
        "decided_on": record.get("decided_on") or "",
        "year": int(record["year"]),
        "url": record["url"],
    }


class CorpusWriter:
    """Write kept decisions and keep cases/manifest.json in step with them."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.entries: dict[str, dict] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*/*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("gr_key"):
                continue
            self.entries[data["gr_key"]] = _meta(data)

    @property
    def count(self) -> int:
        return len(self.entries)

    def add(self, record: dict) -> Path:
        key = record["gr_key"]
        if not _KEY.fullmatch(key):
            raise ValueError(f"unsafe docket key: {key}")
        year = int(record["year"])
        payload = {
            "gr_key": key,
            "docket": record["docket"],
            "title": record["title"],
            "decided_on": record.get("decided_on") or "",
            "year": year,
            "url": record["url"],
            "source": record["source"],
            "text": record["text"],
        }
        folder = self.root / str(year)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{key}.json"
        _atomic_json(path, payload)
        self.entries[key] = _meta(payload)
        self.flush()
        return path

    def flush(self) -> None:
        cases = sorted(self.entries.values(), key=lambda item: (item["year"], item["gr_key"]))
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.root / "manifest.json", {"count": len(cases), "cases": cases})


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def import_case_files(connection, root: Path | str) -> int:
    """Load cases/<year>/<gr_key>.json into the catalog so the index can be built."""
    from ph_sc_labor_juris.store import save_decision, upsert_listing

    folder = Path(root)
    if not folder.exists():
        return 0
    loaded = 0
    for path in sorted(folder.glob("*/*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        text = (data.get("text") or "").strip()
        key = data.get("gr_key")
        if not key or not text:
            continue
        upsert_listing(
            connection,
            gr_key=key,
            docket=data["docket"],
            title=data["title"],
            decided_on=data.get("decided_on") or "",
            year=int(data["year"]),
            url=data["url"],
            source=data.get("source") or "corpus",
            elib_id=None,
        )
        save_decision(connection, key, data["text"], True, "loaded from case file")
        loaded += 1
    connection.commit()
    return loaded
