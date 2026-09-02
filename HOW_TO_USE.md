# How to use this project

A quick operational guide for running the fantasy football pipeline. For
architecture and API details see `README.md` and `docs/`.

## What it produces

One consolidated **half-PPR draft board** as a single-sheet Excel workbook:
~365 players (the FantasyPros consensus universe) with consensus ranking /
ADP, per-platform ADP (Yahoo, RTSports, Sleeper, ESPN), 2026 projected points,
2025 actual points, and a few derived draft columns. It's a review checkpoint,
not a polished draft-day workbook yet.

## Environment

Use the project virtualenv:

```
source .venv/bin/activate
```

First time only (or after dependency changes):

```
python -m pip install -e .
```

You can also just call `.venv/bin/python` directly instead of activating.

## Run the pipeline

Using the existing cached data (no network, no API key needed):

```
python -m fantasy_football.pipeline
```

Using fresh data pulled from the FantasyPros API first:

```
python -m fantasy_football.pipeline --refresh
```

Either way it builds the board, runs QA checks, writes the Excel file, and
prints a summary (row count, enrichment coverage, output path).

### What `--refresh` does

1. Fetches current-season data from FantasyPros and overwrites the raw caches:
   - 2026 Half-PPR consensus / platform ADP
   - 2026 PPR consensus (source for ESPN ADP)
   - 2026 projections
2. Runs the exact same transform → validate → Excel steps as the cached run.

The 2025 player-points cache is **not** refreshed (that season is finished).
If a fetch fails, the command fails — it never silently falls back to stale
data. Requires `FANTASYPROS_API_KEY` in `.env`. Note the FantasyPros API has a
~500 request/day limit, so only use `--refresh` when you actually want new
numbers.

### Optional flags

- `--output PATH` — write the workbook to exactly this path (used verbatim, no
  date stamping).
- `--raw-dir DIR` — read/write raw caches somewhere other than `data/raw/`.

## Where things live

| What | Location |
| --- | --- |
| Raw API caches (JSON) | `data/raw/` |
| Generated Excel outputs | `outputs/` |

Both directories are git-ignored.

The default output filename is date-stamped with the day you run it:

```
outputs/fantasy_draft_checkpoint_YYYY_MM_DD.xlsx
```

e.g. `fantasy_draft_checkpoint_2026_09_01.xlsx`. Each day's run produces a
new file; older ones are left in place.

## Notebooks

`notebooks/` is optional — it's for API exploration, data inspection, and
prototyping new metrics before they go into `src/`. You do **not** need to run
any notebook to produce the Excel output.

## Typical iteration loop

1. Change extraction / transform / config / output code in `src/`.
2. Re-run `python -m fantasy_football.pipeline`.
3. Open the new dated workbook in `outputs/` and review.
4. Repeat.
