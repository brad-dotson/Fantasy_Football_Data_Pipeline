# Claude Code Instructions

## Project context

Read README.md before making architectural changes.

This project serves two purposes:
1. Produce useful 2026 fantasy football draft data. Half-PPR scoring.
2. Help the project owner learn Python, APIs, data engineering, AWS, and Databricks.

## Working style

- `reference/fantasy_draft_prep_2024.xlsx` is a legacy example of the desired user-facing output; use it for context, not as a rigid schema specification.
- Prefer small, incremental changes over large refactors.
- Explain important implementation decisions.
- Include explanatory in-line code comments for all work.
- In jupyter notebook, include well-formatted markdown cells to explain and organize logic.
- Update documentation appropriately as project evolves. 
- Do not modify unrelated files.
- Do not commit or push changes unless explicitly requested.
- Do not expose or hardcode credentials.
- Read secrets from environment variables.
- Minimize FantasyPros API calls because the API has a 500-request/day limit.
- Cache raw API responses locally before transformation.
- Reuse cached responses during development whenever possible.
- Keep extraction and transformation logic separate.
- During early exploration, notebooks are appropriate.
- Move stable/reusable logic into `src/` as the project matures.
- Read `docs/fantasypros_api_notes.md` before changing FantasyPros ingestion logic.
- Treat the consensus rankings dataset as the primary player universe; enrich it with other FantasyPros datasets using left joins unless there is a strong reason to do otherwise.
- `HOW_TO_USE.md` is a living, user-facing operational guide for the project owner. Keep it current whenever a change affects how the project is run or used (commands, flags, environment setup, data/output locations).
- The checkpoint output schema is defined once in `CHECKPOINT_SCHEMA` (`src/fantasy_football/transform/draft_checkpoint.py`): it drives both the dataframe column order and the Excel `data_dictionary` worksheet. Whenever you add, remove, rename, or change the meaning of an output column, update its `ColumnSpec` in the same edit (definition, source, notes). `validate_checkpoint_schema` fails the pipeline if an exported column has no dictionary entry or a dictionary entry is stale. League-specific columns have their own `LEAGUE_COLUMN_SCHEMA` in `src/fantasy_football/leagues.py` — keep it updated the same way.
- League config + snake-draft ordering live in `src/fantasy_football/leagues.py` and `config/leagues.yml`, deliberately separate from FantasyPros extraction. The shared player board is built once and reused for every league sheet — do not duplicate the player pipeline per league.
- Optional per-league `keepers` (`manager` / `player_name` / `prior_draft_round`) are handled in `leagues.py` only: `keeper_round = prior_draft_round - 1`, consumed pick resolved via `snake_pick_table` (so even-round reversal is automatic), and the manager/player cells blacked out on that one league sheet in `write_league_workbook`. YAML is the source of truth — no waiver/trade/first-round/repeat-keeper rules, no keeper-rule engine. Keep it in the league layer; do not touch extraction or the shared checkpoint schema.


Manual draft-prep enrichment
- `data/manual/2026/espn_draft_order_2026.csv` is a curated third-party proxy for ESPN draft-room ordering.
- `data/manual/2026/positional_tiers_2026.csv` contains long-form tier records from multiple sources.
- Treat `data/manual/` as replaceable curated inputs, not `data/raw/`.
- Do not overwrite or collapse source-specific tier fields.
- Loading/joining of `data/manual/` lives only in `src/fantasy_football/enrich/manual.py`, kept separate from `extract/`. It exposes `apply_manual_enrichment(checkpoint_df)`, called once from `build_draft_checkpoint` as a LEFT JOIN on exact `player_name` (no player dropped, missing stays `<NA>`, nothing inferred across sources). `espn_order` / `hartman_tier` / `ringer_tier` are shared `CHECKPOINT_SCHEMA` columns; the FantasyPros `tier` column is never touched.
- Curated CSVs must not fan out a checkpoint row: the loaders reject duplicate `player_name` (ESPN) and multi-tier/multi-position player+source pairs (tiers).
- `write_league_workbook` gives the `hartman_tier` / `ringer_tier` cells persistent per-value conditional formatting (discrete rules for tiers 1–8, green → yellow/orange → red via `_TIER_FILLS`), so a tier typed into a blank cell in Excel colours itself; blank cells get no fill. Keep it as conditional formatting (not static per-cell fills) and keep the subtle grid border merged into each rule. Same mapping for both tier columns; never touch the FantasyPros `tier` column or the underlying values.

League platform ordering
- `LeagueConfig.draft_platform` (from `config/leagues.yml`, optional, default `sleeper`, validated against `DRAFT_PLATFORMS`) drives sheet ordering. `order_board_for_platform` in `leagues.py` is the single place: `espn` = stable sort on a LOCAL key of `espn_order` else `consensus_adp_half` else last (checkpoint order); every other platform = identity. The fallback key is never written back — `espn_order` stays `<NA>` where the source lacked it. Never branch on league name.
- Both `build_league_frame` and `resolve_keepers` order the board via `order_board_for_platform` BEFORE `snake_pick_table`, so `overall_pick`/`round`/`pick_in_round`/`manager` and keeper cells always align with the displayed row order.

League platforms
- The Boys: ESPN, Half-PPR
- Cherri: ESPN, Half-PPR
- Draft Queens: Sleeper
- ESPN ordering should only affect ESPN league sheets.
- Draft Queens (Sleeper) is the standing non-ESPN regression/test case — its sheet must always match shared checkpoint order.
- The generated workbook is the draft-day artifact but is regenerated from scratch on every run: any edits made directly in an `outputs/` file are lost on the next pipeline run.