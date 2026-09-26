"""Download monthly lists and the decisions that are labor cases."""

from __future__ import annotations

import sqlite3
from datetime import date

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
) -> int:
    rows = pending_cases(connection, None if titles_only else limit)
    fetched = 0
    for row in rows:
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
        fetched += 1
        label = "labor" if is_labor else "not labor"
        print(f"    {label}: {reason}")
        connection.commit()
    return fetched
