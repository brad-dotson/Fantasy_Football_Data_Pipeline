# How to use this project

A quick operational guide for running the fantasy football pipeline. For
architecture and API details see `README.md` and `docs/`.

## What it produces

One Excel workbook: **one sheet per configured league**, then a
`data_dictionary` sheet.

- **League sheets** (one per entry in `config/leagues.yml`, in file order) —
  the shared ~365-player half-PPR board (FantasyPros consensus universe:
  consensus ranking / ADP, per-platform ADP for Yahoo, RTSports, Sleeper, ESPN,
  2026 projected points, 2025 actual points, a few derived columns) with four
  **snake-draft context columns prepended**, shown left-to-right as
  `manager | pick | rnd | rnd_pick` then `player_name | team | position` (those
  three headers are display labels for the internal `overall_pick`, `round`,
  `pick_in_round`). Columns A:G and the header row are frozen. Rows where *your*
  configured `draft_position` slot is on the clock are highlighted (pale amber),
  following the forward/reverse snake order; `position` cells are pastel-shaded
  by slot (RB/WR/QB/TE/DST/K). The player board itself is identical across
  league sheets — only the prefix, freeze, and highlight differ.
- **`data_dictionary`** — one row per output column (shared columns + the four
  league columns): definition, source, notes (missing-value meaning, scoring
  format, known caveats). Generated from maintained metadata in code, so it
  always matches the columns actually exported.

It's a review checkpoint, not a polished draft-day workbook yet. Keeper picks
are **not** modelled yet — that's the next iteration.

## League configuration

`config/leagues.yml` defines the leagues. Add or remove leagues by editing that
file only — no code changes. Each entry needs:

| Field | Meaning |
| --- | --- |
| `league_name` | Display name; also the worksheet name. |
| `num_teams` | Number of draft slots. |
| `draft_position` | **Your** snake slot, `1..num_teams`; drives row highlighting. |
| `managers` | Ordered list = round-1 pick order. Length **must** equal `num_teams`; no blank names. |

The checked-in file has three leagues — **The Boys**, **Cherri**, and a
**Placeholder League** — with placeholder manager names (`Manager 01…`, and
`You` marking your slot). Edit them by hand with the real names/slots. The
pipeline validates the config on every run and fails with a clear,
league-named message if a rule is broken.

## Setup / prerequisites

### Cached mode (default — no key, no network)

`python -m fantasy_football.pipeline` runs entirely off the raw JSON already in
`data/raw/`. It makes **no API calls** and needs **no API key**, as long as the
required raw cache files are present (the command fails clearly naming any that
are missing).

### Fresh-data mode (`--refresh`)

To pull fresh numbers you need a **FantasyPros Public API key**:

- The project reads it from the environment variable **`FANTASYPROS_API_KEY`**.
- Store it with the project's existing `.env` approach (a `FANTASYPROS_API_KEY=...`
  line in `.env` at the repo root). Never commit the key or paste it into docs.
- The key must have **FantasyPros premium / Hall of Fame API access**. This
  workflow depends on the full premium responses; the restricted free-tier /
  sample responses do not contain the fields the transform needs.

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
- `--league-config PATH` — use a league YAML other than `config/leagues.yml`.

## Where things live

| What | Location |
| --- | --- |
| Raw API caches (JSON) | `data/raw/` |
| League config (YAML) | `config/leagues.yml` |
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
