"""Download monthly lists and the decisions that are labor cases."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from ph_sc_labor_juris.corpus import CorpusWriter
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

# E-Library monthly lists are empty before about 1996. Lawphil covers 1990 onward.
ELIB_FIRST_YEAR = 1996


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
    writer: CorpusWriter | None = None,
    stop_at: int | None = None,
) -> int:
    rows = pending_cases(connection, None if titles_only else limit)
    fetched = 0
    for row in rows:
        if stop_at is not None and writer is not None and writer.count >= stop_at:
            break
        if titles_only and not title_is_candidate(row["title"]):
            # Leave it pending so a later full run can still read the decision.
            continue
        if limit is not None and fetched >= limit:
            break
        url = elib_friendly_url(row["elib_id"]) if row["elib_id"] else row["url"]
        print(f"  fetch {row['docket']}  {row['title'][:80]}")
        try:
            page = client.get(url)
        except FetchError as error:
            print(f"    skipped: {error}")
            continue
        text = html_to_text(page)
        if not looks_like_decision(text):
            print("    skipped: page did not look like a decision")
            continue
        is_labor, reason = classify(row["title"], text)
        save_decision(
            connection,
            row["gr_key"],
            text if is_labor else None,
            is_labor,
            reason,
        )
        if is_labor and text and writer is not None:
            writer.add(
                {
                    "gr_key": row["gr_key"],
                    "docket": row["docket"],
                    "title": row["title"],
                    "decided_on": row["decided_on"] or "",
                    "year": int(row["year"]),
                    "url": url,
                    "source": row["source"],
                    "text": text,
                }
            )
        connection.commit()
        fetched += 1
        label = "labor" if is_labor else "not labor"
        saved = f"  [{writer.count} labor files]" if writer is not None else ""
        print(f"    {label}: {reason}{saved}")
    return fetched


def collect(
    connection: sqlite3.Connection,
    client: HttpClient,
    *,
    start_year: int,
    end_year: int,
    only_month: int | None,
    refresh: bool,
    titles_only: bool,
    limit: int | None,
    cases_dir: Path | str | None = None,
    stop_at: int | None = None,
) -> int:
    """List each month, then download pending decisions before moving on.

    Listing both sources before the download prefers the E-Library text when
    the same G.R. number appears on both sites. A saved JSON file and the
    sqlite catalog let a later run continue after an interruption.
    """
    writer = CorpusWriter(cases_dir) if cases_dir is not None else None
    if writer is not None and stop_at is not None and writer.count >= stop_at:
        print(f"Already have {writer.count} labor decisions.")
        return 0
    today = date.today()
    fetched = 0
    for year in range(start_year, end_year + 1):
        months = [only_month] if only_month else range(1, 13)
        for month in months:
            if (year, month) > (today.year, today.month):
                return fetched
            closed = (year, month) < (today.year, today.month)
            print(f"{year}-{month:02d}")
            _collect_source(
                connection,
                client,
                source="lawphil",
                year=year,
                month=month,
                refresh=refresh or not closed,
            )
            if year >= ELIB_FIRST_YEAR:
                _collect_source(
                    connection,
                    client,
                    source="elibrary",
                    year=year,
                    month=month,
                    refresh=refresh or not closed,
                )
            connection.commit()
            remaining = None if limit is None else limit - fetched
            fetched += fetch_decisions(
                connection,
                client,
                titles_only=titles_only,
                limit=remaining,
                writer=writer,
                stop_at=stop_at,
            )
            if limit is not None and fetched >= limit:
                return fetched
            if stop_at is not None and writer is not None and writer.count >= stop_at:
                print(f"Stopped at {writer.count} labor decisions.")
                return fetched
    return fetched
