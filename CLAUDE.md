# Claude Code Instructions

## Project context

Read README.md before making architectural changes.

This project serves two purposes:
1. Produce useful 2026 fantasy football draft data.
2. Help the project owner learn Python, APIs, data engineering, AWS, and Databricks.

## Working style

- `reference/fantasy_draft_prep_2024.xlsx` is a legacy example of the desired user-facing output; use it for context, not as a rigid schema specification.
- Prefer small, incremental changes over large refactors.
- Explain important implementation decisions.
- Update documentation appropriately as project evolves. 
- Do not modify unrelated files.
- Do not commit or push changes unless explicitly requested.
- Do not expose or hardcode credentials.
- Read secrets from environment variables.
- Minimize FantasyPros API calls because the API has a 50-request/day limit.
- Cache raw API responses locally before transformation.
- Reuse cached responses during development whenever possible.
- Keep extraction and transformation logic separate.
- During early exploration, notebooks are appropriate.
- Move stable/reusable logic into `src/` as the project matures.