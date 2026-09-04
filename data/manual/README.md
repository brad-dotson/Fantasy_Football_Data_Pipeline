# Manual / Curated Data Sources

This directory contains structured external data that is useful to the draft workbook but is not yet produced by an automated ingestion pipeline.

These files are deliberately separated from `data/raw/`:
- `raw/` is for machine-ingested API/source responses.
- `manual/` is for human/AI-curated, source-attributed structured data.

The downstream code should treat these files as replaceable inputs so that a future scraper/agent/RAG workflow can produce the same schema without changing the workbook logic.

## 2026/espn_draft_order_2026.csv

Purpose: approximate the player order shown to ESPN drafters.

Source: Hashtag Football's ESPN ADP page.
Source page states that it includes ESPN draft order and positional rankings and was updated 2026-08-31.

Coverage:
- ESPN order 1-216 (18 full rounds in a 12-team league).
- 209 of those 216 names match the project's 365-row checkpoint as of 2026-09-03.
- Seven source entries are not in that checkpoint; they are retained and flagged rather than silently dropped.

Important:
- This is a third-party representation of ESPN order, not an official ESPN export.
- `player_name` is normalized where needed to match this project's canonical naming.
- `source_player_name` preserves the source display name.
- If used for sorting, checkpoint players without a known ESPN order should sort after the known-order players, not be dropped.

## 2026/positional_tiers_2026.csv

Long-form tier table so multiple tier sources can coexist.

### David Hartman / Big Blue View

Final 2026 positional rankings from Big Blue View / SB Nation.
- RB, WR, and TE articles explicitly use Half-PPR scoring.
- QB article uses four points per passing TD.
- The file includes all tiered players from the current QB/RB/WR articles and all TE players that match the project checkpoint.

TE source anomaly:
- The published TE article repeats the heading `Tier IV` for two consecutive groups and then labels the final group `Tier V`.
- This file preserves the published heading in `source_tier_label` but normalizes those sequential groups to numeric tiers 5 and 6 in `tier`.
- The source also lists Pat Freiermuth twice; this curated file keeps one row and records that normalization in `notes`.

### The Ringer Fantasy Football Show

The Ringer rows intentionally contain only player/tier assignments that are explicitly supported by the publicly visible episode summaries.
- RB: verified Tiers 1-3 from the July 28 episode summary.
- QB: verified named players from Tiers 1-4 from the July 15 episode summary.
- TE: verified Tier 1 and the two clearly identified Tier 2 second-year players from the July 13 episode summary.
- WR: no rows were created because the public episode summary names tier categories but does not map individual receivers to exact tiers.
- Tucker Kraft is not assigned a Ringer tier because the TE summary describes him as a possible Tier 2 player rather than a confirmed assignment.

Missing Ringer values should remain missing. Do not infer or fill them from another source.

## Future replacement

A future automated workflow can replace these manually curated files as long as it produces equivalent stable fields. The current manual layer is intentionally a short-term, transparent bridge for the 2026 draft.
