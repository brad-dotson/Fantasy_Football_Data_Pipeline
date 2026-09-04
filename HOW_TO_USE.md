# How to use this project

A quick operational guide for running the fantasy football pipeline. For
architecture and API details see `README.md` and `docs/`.

## What it produces

One Excel workbook: **one sheet per configured league**, then a
`data_dictionary` sheet.

- **League sheets** (one per entry in `config/leagues.yml`, in file order) —
  the shared ~365-player half-PPR board (FantasyPros consensus universe:
  consensus ranking / ADP, per-platform ADP for Yahoo, RTSports, Sleeper, ESPN,
  2026 projected points, 2025 actual points, a few derived columns, plus the
  curated `espn_order` and the source-specific `hartman_tier` / `ringer_tier`
  columns) with four **snake-draft context columns prepended**, shown
  left-to-right as `manager | pick | rnd | rnd_pick` then
  `player_name | team | position | hartman_tier | ringer_tier | pos_rank | bye_wk`,
  then the remaining board columns in their existing order (`pick / rnd /
  rnd_pick` are display labels for the internal `overall_pick`, `round`,
  `pick_in_round`; `hartman_tier` / `ringer_tier` keep their independent meaning
  and are **not** the FantasyPros `tier` column, which stays further right).
  Columns A:G (through `position`) and the header row are frozen. Rows where
  *your* configured `draft_position` slot is on the clock are highlighted (pale
  amber), following the forward/reverse snake order; `position` cells are
  pastel-shaded by slot (RB/WR/QB/TE/DST/K).
  - **Row order** depends on the league's `draft_platform`. An `espn` league
    (The Boys, Cherri) sorts by the sourced `espn_order`; where that is missing,
    `consensus_adp_half` is used **only as an internal fallback sort key** so
    those players interleave by market ADP instead of dropping to the bottom.
    The `espn_order` value itself is never imputed — it stays blank where the
    source had none. Players missing both values stay after every usable-sort
    player, in stable checkpoint order. A `sleeper` league (Draft Queens) keeps
    the shared checkpoint order unchanged and is the standing non-ESPN
    regression case. The `pick / rnd / rnd_pick / manager` columns are numbered
    **after** this reordering.
  - **Tier colours:** `hartman_tier` and `ringer_tier` cells use persistent
    conditional formatting — one fixed colour per tier value 1–8, green (better /
    low number) → yellow → orange → red (worse / high number). Only the tier
    cells are coloured; blank tier cells get no fill. If you type a valid tier
    into a blank tier cell in Excel, the colour appears automatically.
  - Apart from row order + the snake prefix + freeze/highlight + tier colours,
    the player board is identical across league sheets.
- **`data_dictionary`** — one row per output column (shared columns + the four
  league columns): definition, source, notes (missing-value meaning, scoring
  format, known caveats). Generated from maintained metadata in code, so it
  always matches the columns actually exported.

This is the draft-day workbook. It is regenerated from scratch on every
pipeline run, so **any edits you make directly in a generated file (including
tiers you type into blank cells) are lost the next time you run the pipeline.**
For a live draft, work from a separate copy, or make lasting changes in the
source inputs (`config/leagues.yml`, `data/manual/`) and re-run.

## League configuration

`config/leagues.yml` defines the leagues. Add or remove leagues by editing that
file only — no code changes. Each entry needs:

| Field | Meaning |
| --- | --- |
| `league_name` | Display name; also the worksheet name. |
| `num_teams` | Number of draft slots. |
| `draft_position` | **Your** snake slot, `1..num_teams`; drives row highlighting. |
| `managers` | Ordered list = round-1 pick order. Length **must** equal `num_teams`; no blank names. |
| `draft_platform` | *Optional.* `espn` or `sleeper` (default `sleeper`). `espn` orders that sheet by `espn_order` (fallback: `consensus_adp_half`, internal only); `sleeper` keeps the shared checkpoint order. |
| `keepers` | *Optional.* List of kept players (see below). Omit the key or use `[]` for none. |

The pipeline validates the config on every run and fails with a clear,
league-named message if a rule is broken.

### Keepers (optional)

Each `keepers` entry is `{ manager, player_name, prior_draft_round }`:

```yaml
    keepers:
      - manager: "Brad"
        player_name: "Javonte Williams"
        prior_draft_round: 8
```

Rules: `manager` must exactly match one of that league's `managers`; at most one
keeper per manager; `prior_draft_round` is an integer `>= 2`; `player_name` must
exactly match one player on the board (no fuzzy matching). The keeper's pick is
consumed one round earlier — `keeper_round = prior_draft_round - 1` — and its
position within that round follows the normal snake reversal.

On that league's sheet only, two cells are blacked out (white text): the
manager's consumed pick cell in `keeper_round`, and the kept player's
`player_name` cell (the player stays normally draftable on every other league
sheet). Nothing else changes — snake order, amber user-slot highlighting, and
non-keeper leagues are untouched.

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
| Curated enrichment CSVs (ESPN order, positional tiers) | `data/manual/` |
| League config (YAML) | `config/leagues.yml` |
| Generated Excel outputs | `outputs/` |

`data/raw/` and `outputs/` are git-ignored; `data/manual/` is not (it is
curated input meant to be version-controlled, not machine-ingested raw). To
refresh the manual layer, edit the
CSVs under `data/manual/2026/` in place — no flag needed, the default run picks
them up. See `data/manual/README.md` for what each file is and its provenance.

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
