# Philippine Supreme Court labor decisions, 1990 to present

This project collects labor decisions of the Philippine Supreme Court and answers questions from those decisions.

It reads the public monthly lists from two places:

- [Supreme Court E-Library](https://elibrary.judiciary.gov.ph/) for the official text, from the years that library lists (about 1996 onward)
- [Lawphil](https://lawphil.net/) for the earlier years, and for any month the E-Library list does not cover

A decision is kept when it is a labor case: the title names the NLRC, the Labor Code, the Labor Arbiter, DOLE, the Secretary or Ministry of Labor, POEA, or illegal dismissal, or the text itself discusses labor doctrine. Criminal and civil cases are left out. Each kept decision is written to `cases/<year>/<GR-key>.json`. `cases/manifest.json` lists those decisions without the full text. The local search index lives in `data/corpus.sqlite`, which is not part of the repository.

The search half is retrieval-augmented generation. A question is matched against passages from the saved decisions. If you set `GROQ_API_KEY` or `OPENAI_API_KEY`, the model writes an answer that is limited to those passages and cites the G.R. number. Without a key, the command prints the passages themselves.

This is a research aid. It is not legal advice, and a later decision can change an older doctrine.

## Setup

Python 3.11 or newer. No extra packages.

```powershell
cd C:\Users\Admin\Documents\GitHub\ph-sc-labor-juris
python -m ph_sc_labor_juris status
```

## Collect the decisions

A complete run reads every G.R. decision from 1990 through the current month, then keeps the labor cases. That is tens of thousands of pages. The default pause is 0.8 seconds between requests. Stop it whenever you want; the next run continues where it left off. `--labor-target 1000` stops once that many labor decisions are on disk.

```powershell
python -m ph_sc_labor_juris collect
```

Faster pass, using only titles that already look like labor cases. This misses labor cases whose titles are only the parties' names.

```powershell
python -m ph_sc_labor_juris collect --titles-only
```

Try a single month first:

```powershell
python -m ph_sc_labor_juris collect --start-year 1990 --end-year 1990 --month 1 --titles-only
```

Useful options:

- `--delay 1` slows the downloads further
- `--limit 20` stops after 20 newly downloaded decisions
- `--refresh` re-reads monthly index pages that were already saved

## Build the index and ask

```powershell
python -m ph_sc_labor_juris index
python -m ph_sc_labor_juris ask "When are fishermen-crew members employees of the boat owner?"
```

To get a written answer, copy `.env.example` to `.env` and set one key:

```
GROQ_API_KEY=your-key
```

`status` shows how many decisions are listed, checked, kept as labor, and indexed.

## Tests

```powershell
python -m unittest discover -s tests -t .
```
