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

Manual / user-maintained fields may include:
- Ringer Tier
- League-specific draft tracking fields

The primary near-term output is one consolidated Excel sheet suitable for use
during a live fantasy draft. Separate position-specific sheets are lower priority for v1.

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

The current leagues are "The Boys" and "Cherri," corresponding to the two
primary league-specific tabs in the reference workbook. The "ADP" tab is a
good starting point for the initial API dataset. League-specific and manually
maintained fields can then be added for v1.

## Data Sources

Primary:
- FantasyPros Public API v2
    - Fantasy Pros API Docs: https://api.fantasypros.com/public/v2/docs 
    - We are using Half-PPR Fantasy scoring
    - Requires a paid HOF subscription on Fantasy Pros (~$23/month in 2026)

Additional sources may be added where FantasyPros does not provide required
data, particularly platform-specific ADP. Source-specific FantasyPros ADP
access is currently under investigation; see `docs/fantasypros_api_notes.md`.

## Architecture

Initial:

API → raw JSON → pandas transformations → processed dataset → Excel

Future:

APIs → raw storage / AWS → transformation layer → Databricks → analytics

## Project Structure

- `docs/` - project and API documentation
- `notebooks/` - exploratory analysis and API experimentation
- `reference/` - historical/reference artifacts from prior implementations
- `src/` - reusable Python pipeline code
- `data/raw/` - cached raw API responses (not committed)
- `data/processed/` - transformed datasets
- `outputs/` - generated draft-preparation files (not committed)

## Development Principles

- Never commit API keys or credentials.
- Store secrets in `.env`.
- Cache raw API responses to minimize unnecessary API calls.
- Separate extraction from transformation.
- Prefer APIs and structured sources over HTML scraping.
- Preserve raw source data before transforming it.
- Keep exploratory work in notebooks and move reusable logic into `src/`.

