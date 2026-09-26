"""Command line for collecting decisions and asking questions."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from ph_sc_labor_juris.ask import format_passages, generate_answer
from ph_sc_labor_juris.collect import collect_lists, fetch_decisions
from ph_sc_labor_juris.http_client import HttpClient
from ph_sc_labor_juris.index import build_index, search
from ph_sc_labor_juris.store import connect, counts


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    _load_env(Path(".env"))
    parser = argparse.ArgumentParser(
        prog="ph-sc-labor-juris",
        description=(
            "Collect Philippine Supreme Court labor decisions from 1990 to the "
            "present and ask questions grounded in those decisions."
        ),
    )
    parser.add_argument(
        "--db",
        default="data/corpus.sqlite",
        help="SQLite file for the catalog and search index (default: data/corpus.sqlite)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Download and classify labor decisions")
    collect.add_argument("--start-year", type=int, default=1990)
    collect.add_argument("--end-year", type=int, default=date.today().year)
    collect.add_argument("--month", type=int, choices=range(1, 13))
    collect.add_argument("--delay", type=float, default=1.5, help="Seconds between requests")
    collect.add_argument(
        "--titles-only",
        action="store_true",
        help="Download only cases whose titles already look like labor cases",
    )
    collect.add_argument(
        "--limit",
        type=int,
        help="Stop after this many newly downloaded decisions",
    )
    collect.add_argument(
        "--refresh",
        action="store_true",
        help="Re-read monthly index pages that were already saved",
    )

    sub.add_parser("index", help="Build the search index from saved labor decisions")

    ask = sub.add_parser("ask", help="Ask a question against the local index")
    ask.add_argument("question")
    ask.add_argument("--limit", type=int, default=6, help="How many passages to retrieve")

    sub.add_parser("status", help="Show how many cases are listed, checked, and indexed")

    args = parser.parse_args(argv)
    connection = connect(args.db)
    try:
        if args.command == "collect":
            client = HttpClient(delay=args.delay)
            print(
                f"Listing G.R. decisions from {args.start_year} to {args.end_year} "
                f"(pause {args.delay:.1f}s between requests)"
            )
            collect_lists(
                connection,
                client,
                start_year=args.start_year,
                end_year=args.end_year,
                only_month=args.month,
                refresh=args.refresh,
            )
            mode = "title candidates only" if args.titles_only else "every listed G.R. decision"
            print(f"Reading decisions ({mode})")
            fetched = fetch_decisions(
                connection,
                client,
                titles_only=args.titles_only,
                limit=args.limit,
            )
            print(f"Downloaded {fetched} decisions.")
            _print_counts(connection)
            return 0
        if args.command == "index":
            written = build_index(connection)
            print(f"Indexed {written} passages.")
            return 0
        if args.command == "ask":
            rows = search(connection, args.question, limit=args.limit)
            answer = None
            if rows:
                try:
                    answer = generate_answer(args.question, rows)
                except Exception as error:  # network or API failure; still show passages
                    print(f"The model request failed ({error}). Showing the passages instead.\n")
            if answer:
                print(answer)
                print("\nSources:")
                for index, row in enumerate(rows, start=1):
                    print(f"[{index}] {row['docket']} ({row['decided_on']}) {row['url']}")
            else:
                if rows and not (os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")):
                    print(
                        "No GROQ_API_KEY or OPENAI_API_KEY is set, so this is the "
                        "retrieved text only.\n"
                    )
                print(format_passages(rows))
            return 0
        if args.command == "status":
            _print_counts(connection)
            return 0
    finally:
        connection.close()
    return 2


def _print_counts(connection) -> None:
    stats = counts(connection)
    print(
        f"Listed {stats['listed']} | checked {stats['checked']} | "
        f"labor {stats['labor']} | pending {stats['pending']} | "
        f"indexed passages {stats['chunks']}"
    )
