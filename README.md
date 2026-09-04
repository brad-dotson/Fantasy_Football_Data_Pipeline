# Fantasy Football Data Pipeline

A personal data engineering project for collecting, transforming, and analyzing
fantasy football data.

The immediate goal is to generate a useful draft-preparation dataset for the
2026 NFL fantasy football season using half-PPR scoring data. The longer-term goal is to use the project
to practice modern data engineering and analytics workflows using Python,
APIs, AWS, databases, and Databricks.

## Current Goals - v1

Build a consolidated, player-level dataset for the 2026 fantasy football half-PPR scoring draft containing, where available:

- Player name
- Current NFL team
- Position and positional rank
- Bye week
- FantasyPros consensus / expert ranking
- Consensus ADP
- Platform-specific ADP:
  - Yahoo (Half-PPR)
  - Sleeper (Half-PPR)
  - RTSports (Half-PPR)
  - ESPN (PPR; explicitly labeled as such)
- 2025 fantasy points / points per game
- 2026 projected fantasy points
- FantasyPros Half-PPR ECR (expert consensus ranking)
- Consensus Half-PPR ADP
- ECR / ranking range and variability
- FantasyPros overall and positional tiers
- ADP vs. ECR
- Other useful draft-ranking or projection fields discovered during development

Manual / user-maintained fields (curated under `data/manual/`, joined by exact
player name — see "Manual enrichment layer" below):
- ESPN draft-room order (`espn_order`)
- Source-specific positional tiers (`hartman_tier`, `ringer_tier`), kept
  separate from the FantasyPros `tier` column
- League-specific draft tracking fields

The primary near-term output is one Excel workbook with **one worksheet per
configured league** (the shared player board plus that league's snake-draft
context columns) followed by a `data_dictionary` sheet. Separate
position-specific sheets are lower priority for v1.

## Reference Implementation

`reference/fantasy_draft_prep_2024.xlsx` is the output from the original 2024
version of this project, which relied primarily on web scraping. The new
implementation will use APIs instead, so the original dataset may not be
exactly reproducible.

Use the workbook as a reference for the types of data and draft-preparation
functionality that have historically been useful, but do not treat its exact
schema or workbook structure as a requirement.

The 2026 implementation should prioritize a consolidated, league-wide player
dataset and may improve, simplify, or replace elements of the 2024 workbook.

The configured leagues are "The Boys" (ESPN), "Cherri" (ESPN) and "Draft
Queens" (Sleeper); the first two correspond to the primary league-specific tabs
in the reference workbook. Leagues are defined entirely in `config/leagues.yml`
(any number, no code changes). The "ADP" tab is a good starting point for the
initial API dataset. League-specific and manually maintained fields are layered
on top for v1.

## Data Sources

Primary:
- FantasyPros Public API v2
    - Fantasy Pros API Docs: https://api.fantasypros.com/public/v2/docs 
    - We are using Half-PPR Fantasy scoring
    - Requires a paid HOF subscription on Fantasy Pros (~$23/month in 2026)

Consensus rankings define the primary draft-board universe, while other datasets enrich it via left joins.

Additional sources may be added where FantasyPros does not provide required
data.

Current FantasyPros ingestion status:
- 2026 consensus rankings / Half-PPR ADP: productionized
- 2026 preseason projections: productionized
- 2025 season-long Half-PPR player points: productionized
- 2026 injury data: explored and rejected for v1 due to sparse / low-value preseason coverage
- Platform-specific ADP: productionized for Yahoo Half-PPR, RTSports Half-PPR,
  Sleeper Half-PPR, and ESPN PPR

Transformation status:
- First reusable transformation layer exists at
  `src/fantasy_football/transform/`. It merges the cached raw payloads into one
  shared consolidated player-level board (`data_dictionary` metadata generated
  from the maintained column schema in `transform/draft_checkpoint.py`), then
  left-joins the curated `data/manual/` enrichment (see below).
- League-specific draft sheets live in `src/fantasy_football/leagues.py`,
  driven by `config/leagues.yml` (any number of leagues, no code changes). Each
  league sheet is the shared board with four snake-draft columns prepended
  (`overall_pick`, `round`, `pick_in_round`, `manager`) and the user's
  `draft_position` picks highlighted.
  - **Platform ordering** (`draft_platform` in `config/leagues.yml`): a
    `draft_platform: espn` league (The Boys, Cherri) sorts its sheet by the
    sourced `espn_order`. Where `espn_order` is missing, `consensus_adp_half` is
    used **only as an internal fallback sort key** — the exported `espn_order`
    field itself stays null when the source has no value, and is never imputed.
    Players missing both values stay after every usable-sort player, in stable
    checkpoint order. Snake metadata (`overall_pick` / `round` / `pick_in_round`
    / `manager`) is generated against the **final displayed ordering**. Any
    other platform (`sleeper` — Draft Queens) keeps the shared checkpoint order
    unchanged; Draft Queens doubles as the non-ESPN regression case.
  - **Keepers** are implemented and config-driven (optional, per league):
    `config/leagues.yml` `keepers: [{manager, player_name, prior_draft_round}]`.
    The keeper's pick is consumed one round earlier
    (`keeper_round = prior_draft_round - 1`); on that league's sheet the consumed
    pick cell and the kept player's name cell are blacked out. Other league
    sheets are unaffected.
  - **Tier cells** (`hartman_tier`, `ringer_tier`) carry persistent conditional
    formatting: one fixed colour per tier value 1–8, a green (better / low
    number) → yellow → orange → red (worse / high number) progression, applied
    to the tier cells only. Blank tier cells get no fill; typing a valid tier
    into a blank cell in Excel triggers the colour automatically. The FantasyPros
    `tier` column is independent and left as-is.
- The pipeline exports a date-stamped workbook
  (`outputs/fantasy_draft_checkpoint_YYYY_MM_DD.xlsx`): one worksheet per
  configured league, then `data_dictionary`. This is the draft-day workbook, but
  it is regenerated from scratch on every run — edits made directly in a
  generated file are lost the next time the pipeline runs, so keep a separate
  live draft copy.

## Manual enrichment layer

Some draft-prep fields are not (yet) produced by an automated ingestion. They
live as curated, source-attributed CSVs under `data/manual/` and are loaded by
`src/fantasy_football/enrich/manual.py`, which is deliberately separate from the
FantasyPros API extraction:

- `data/manual/2026/espn_draft_order_2026.csv` → `espn_order` (third-party proxy
  for ESPN draft-room order; drives ESPN league sheet ordering).
- `data/manual/2026/positional_tiers_2026.csv` → `hartman_tier` and
  `ringer_tier` (long-form, multi-source; each source stays in its own column,
  and the FantasyPros `tier` column is left untouched).

Everything joins onto the shared board by **exact `player_name`** as a LEFT
JOIN: no checkpoint player is dropped, missing values stay `<NA>` (never zero,
never inferred across sources). `data/manual/` is treated as *replaceable* —
a future scraper/agent can emit the same columns without changing downstream
code. See `data/manual/README.md` for source provenance and caveats.

## Architecture

Initial:

API → raw JSON (`data/raw/`) ─┐
                              ├─→ transformation layer (`src/fantasy_football/transform/`) → consolidated board → league sheets (`src/fantasy_football/leagues.py`) → Excel checkpoint (`outputs/`)
curated `data/manual/` ───────┘  (via `src/fantasy_football/enrich/`)

Future:

APIs → raw storage / AWS → transformation layer → Databricks → analytics

## Project Structure

- `config/` - user-editable configuration (`leagues.yml`)
- `docs/` - project and API documentation
- `notebooks/` - exploratory analysis and API experimentation
- `reference/` - historical/reference artifacts from prior implementations
- `src/` - reusable Python pipeline code (`extract/`, `transform/`, `enrich/`,
  `leagues.py`, `pipeline.py`)
- `data/raw/` - cached raw API responses (not committed)
- `data/manual/` - human/AI-curated, source-attributed enrichment CSVs
  (version-controlled — unlike `data/raw/` — as replaceable inputs, not
  machine-ingested raw)
- `data/processed/` - transformed datasets
- `outputs/` - generated draft-preparation files (not committed)

## Setup

The pipeline code lives in `src/` (src layout). Install it in editable mode so
`import fantasy_football...` works from notebooks, scripts, and tests:

```
python -m pip install -e .
```

Packaging metadata is in `pyproject.toml`. `requirements.txt` is kept for
convenience but the editable install already pulls the runtime dependencies.

## Running the pipeline locally

The whole pipeline runs from one command — no Jupyter required:

```
python -m fantasy_football.pipeline
```

This uses the **existing cached raw JSON** in `data/raw/`, builds the
consolidated player board, runs the lightweight QA checks, writes a
date-stamped workbook `outputs/fantasy_draft_checkpoint_YYYY_MM_DD.xlsx`,
and prints a short summary (row count, enrichment coverage, output path). It
fails clearly if a required cache file is missing.

To pull fresh current-season data first:

```
python -m fantasy_football.pipeline --refresh
```

`--refresh` fetches the 2026 Half-PPR consensus / platform ADP, the 2026 PPR
consensus (ESPN ADP source), and 2026 projections from the FantasyPros API,
overwrites those raw caches, then runs the **same** downstream
transform → validate → Excel path. It needs `FANTASYPROS_API_KEY` set in `.env`
(a FantasyPros premium / Hall of Fame key — the free-tier sample responses lack
the required fields; see `HOW_TO_USE.md`). The completed 2025 player-points
cache is not refreshed. If a refresh fetch fails, the command fails — it does
not fall back to stale cache. The default (no `--refresh`) run makes no API
calls and needs no key.

Optional flags: `--raw-dir DIR` and `--output PATH` override the defaults
(an explicit `--output` path is used verbatim, without date stamping).

For a task-oriented walkthrough see [`HOW_TO_USE.md`](HOW_TO_USE.md).

The notebooks in `notebooks/` stay useful for API exploration, data
inspection, and prototyping new metrics, but are **not** required to produce
the Excel output. The transformation functions
(`fantasy_football.transform`) and `run_pipeline()` are plain importable
Python, so the same logic can later run from an AWS or Databricks job.

## Development Principles

- Never commit API keys or credentials.
- Store secrets in `.env`.
- Cache raw API responses to minimize unnecessary API calls.
- Separate extraction from transformation.
- Prefer APIs and structured sources over HTML scraping.
- Preserve raw source data before transforming it.
- Keep exploratory work in notebooks and move reusable logic into `src/`.

