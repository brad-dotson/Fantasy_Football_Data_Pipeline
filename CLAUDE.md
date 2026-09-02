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