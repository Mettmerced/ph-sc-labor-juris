"""Download monthly lists and the decisions that are labor cases."""

from __future__ import annotations

import sqlite3
import time
from datetime import date
from pathlib import Path

from ph_sc_labor_juris.corpus import CaseCorpus, sync_corpus
from ph_sc_labor_juris.docket import gr_key, is_gr
from ph_sc_labor_juris.http_client import FetchError, HttpClient
from ph_sc_labor_juris.labor import classify, title_is_candidate
from ph_sc_labor_juris.parse import (
    elib_friendly_url,
    elib_month_url,
    html_to_text,
    lawphil_month_url,
    looks_like_decision,
    parse_elib_index,
    parse_lawphil_index,
)
from ph_sc_labor_juris.store import (
    mark_month,
    month_already_listed,
    pending_cases,
    save_decision,
    upsert_listing,
)

# E-Library monthly decision lists are empty before 1996.
ELIBRARY_FIRST_YEAR = 1996


def _year_of(decided_on: str, fallback: int) -> int:
    parts = (decided_on or "").split()
    if parts and parts[-1].isdigit() and len(parts[-1]) == 4:
        return int(parts[-1])
    return fallback


def collect_lists(
    connection: sqlite3.Connection,
    client: HttpClient,
    *,
    start_year: int,
    end_year: int,
    only_month: int | None,
    refresh: bool,
) -> None:
    today = date.today()
    for year in range(start_year, end_year + 1):
        months = [only_month] if only_month else range(1, 13)
        for month in months:
            if (year, month) > (today.year, today.month):
                continue
            closed = (year, month) < (today.year, today.month)
            _collect_source(
                connection,
                client,
                source="lawphil",
                year=year,
                month=month,
                refresh=refresh or not closed,
            )
            _collect_source(
                connection,
                client,
                source="elibrary",
                year=year,
                month=month,
                refresh=refresh or not closed,
            )
            connection.commit()


def _collect_source(
    connection: sqlite3.Connection,
    client: HttpClient,
    *,
    source: str,
    year: int,
    month: int,
    refresh: bool,
) -> None:
    if not refresh and month_already_listed(connection, source, year, month):
        return
    if source == "lawphil":
        url = lawphil_month_url(year, month)
        parser = lambda page: parse_lawphil_index(page, url)
    else:
        url = elib_month_url(year, month)
        parser = parse_elib_index
    try:
        page = client.get(url)
        listings = parser(page)
    except FetchError as error:
        if error.status == 404:
            print(f"  {source} {year}-{month:02d}: no index page")
            mark_month(connection, source, year, month, 0)
            return
        print(f"  {source} {year}-{month:02d}: {error}")
        return

    kept = 0
    for item in listings:
        if not is_gr(item.docket):
            continue
        key = gr_key(item.docket)
        if key is None:
            continue
        upsert_listing(
            connection,
            gr_key=key,
            docket=item.docket,
            title=item.title,
            decided_on=item.decided_on,
            year=_year_of(item.decided_on, year),
            url=item.url if source == "lawphil" else item.url,
            source=item.source,
            elib_id=item.elib_id,
        )
        kept += 1
    mark_month(connection, source, year, month, kept)
    print(f"  {source} {year}-{month:02d}: {kept} G.R. listings")


def fetch_decisions(
    connection: sqlite3.Connection,
    client: HttpClient,
    *,
    titles_only: bool,
    limit: int | None,
    corpus: CaseCorpus | None = None,
    labor_target: int | None = None,
    attempted: set[str] | None = None,
) -> int:
    rows = pending_cases(connection, None if titles_only else limit)
    seen = attempted if attempted is not None else set()
    fetched = 0
    network_failures = 0
    for row in rows:
        if labor_target is not None and corpus is not None and len(corpus) >= labor_target:
            break
        if titles_only and not title_is_candidate(row["title"]):
            # Leave it pending so a later full run can still read the decision.
            continue
        if limit is not None and fetched >= limit:
            break
        if row["gr_key"] in seen:
            continue
        if corpus is not None and row["gr_key"] in corpus:
            continue
        url = elib_friendly_url(row["elib_id"]) if row["elib_id"] else row["url"]
        seen.add(row["gr_key"])
        print(f"  fetch {row['docket']}  {row['title'][:80]}", flush=True)
        try:
            page = client.get(url)
        except FetchError as error:
            print(f"    skipped: {error}", flush=True)
            if error.status == 404:
                save_decision(connection, row["gr_key"], None, False, "page not found")
                connection.commit()
                fetched += 1
            else:
                # Leave it unchecked for the next run. Do not retry it again in this one.
                network_failures += 1
                if network_failures >= 5:
                    time.sleep(15)
                    network_failures = 0
            continue
        network_failures = 0
        text = html_to_text(page)
        if not looks_like_decision(text):
            print("    skipped: page did not look like a decision", flush=True)
            save_decision(
                connection,
                row["gr_key"],
                None,
                False,
                "page did not look like a decision",
            )
            connection.commit()
            fetched += 1
            continue
        is_labor, reason = classify(row["title"], text)
        if is_labor and corpus is not None:
            corpus.write(
                {
                    "gr_key": row["gr_key"],
                    "docket": row["docket"],
                    "title": row["title"],
                    "decided_on": row["decided_on"] or "",
                    "year": int(row["year"] or _year_of(row["decided_on"] or "", 0)),
                    "url": url,
                    "source": row["source"],
                    "text": text,
                }
            )
        save_decision(
            connection,
            row["gr_key"],
            text if is_labor else None,
            is_labor,
            reason,
        )
        fetched += 1
        label = "labor" if is_labor else "not labor"
        saved = f" ({len(corpus)} on disk)" if is_labor and corpus is not None else ""
        print(f"    {label}{saved}: {reason}", flush=True)
        connection.commit()
    return fetched


def run_collection(
    connection: sqlite3.Connection,
    client: HttpClient,
    *,
    start_year: int,
    end_year: int,
    only_month: int | None,
    refresh: bool,
    titles_only: bool,
    limit: int | None,
    cases_dir: Path | str,
    labor_target: int | None,
) -> int:
    """List each year, then download labor decisions until the target is met.

    Case files already on disk are treated as done, so a stopped run can continue.
    """
    corpus = CaseCorpus(cases_dir)
    sync_corpus(connection, corpus)
    print(f"Labor decisions already on disk: {len(corpus)}", flush=True)
    if labor_target is not None and len(corpus) >= labor_target:
        corpus.write_manifest()
        return 0

    today = date.today()
    fetched = 0
    attempted: set[str] = set()
    for year in range(start_year, end_year + 1):
        if labor_target is not None and len(corpus) >= labor_target:
            break
        if limit is not None and fetched >= limit:
            break
        months = [only_month] if only_month else range(1, 13)
        listed_any = False
        for month in months:
            if (year, month) > (today.year, today.month):
                continue
            listed_any = True
            closed = (year, month) < (today.year, today.month)
            _collect_source(
                connection,
                client,
                source="lawphil",
                year=year,
                month=month,
                refresh=refresh or not closed,
            )
            if year >= ELIBRARY_FIRST_YEAR:
                _collect_source(
                    connection,
                    client,
                    source="elibrary",
                    year=year,
                    month=month,
                    refresh=refresh or not closed,
                )
            elif not month_already_listed(connection, "elibrary", year, month):
                mark_month(connection, "elibrary", year, month, 0)
            connection.commit()
        if listed_any and year < ELIBRARY_FIRST_YEAR:
            print(f"  elibrary {year}: monthly lists are empty before 1996", flush=True)
        if not listed_any:
            continue
        fetched += fetch_decisions(
            connection,
            client,
            titles_only=titles_only,
            limit=None if limit is None else limit - fetched,
            corpus=corpus,
            labor_target=labor_target,
            attempted=attempted,
        )
        if labor_target is not None and len(corpus) >= labor_target:
            print(f"Reached {len(corpus)} labor decisions.", flush=True)
            break
    corpus.write_manifest()
    return fetched
