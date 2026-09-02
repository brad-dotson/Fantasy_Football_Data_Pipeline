# FantasyPros API Notes
Current API implementation notes as of 8/28/26. Core FantasyPros extraction is working for consensus rankings, preseason projections, and historical player points. The injuries endpoint was evaluated and rejected for v1.

## Access
- HOF subscription enables premium API access.
- Existing API key upgraded in place.
- Premium daily request limit observed: 500.
- API key stored in `.env`; never commit credentials.

## Working endpoints

### Consensus rankings
`GET /nfl/2026/consensus-rankings`

Useful for:
- Full 2026 player universe
- Half-PPR ADP
- ECR-related fields
- Position rank
- Tier

Working parameters:
- `position=ALL`
- `type=ADP`
- `scoring=HALF`

Premium response:
- ~340 players
- `limit=None`
- `tier=premium`

Relevant player fields observed:
- `player_id`
- `player_name`
- `player_team_id`
- `player_position_id`
- `player_bye_week`
- `rank_ecr`
- `rank_min`
- `rank_max`
- `rank_ave`
- `rank_std`
- `pos_rank`
- `tier`

#### `rank_ecr` vs. consensus ADP semantics (important)

This pull uses `type=ADP`. In that mode FantasyPros reuses the `rank_ecr`
field name to hold the consensus **ADP ordinal** (a dense 1..N rank of players
by average draft slot); it is **not** a separate, non-ADP expert consensus
ranking. The only other consensus number in the same payload is `rank_ave`
(mean draft slot across the ADP sources), which `rank_min` / `rank_max` /
`rank_std` describe the spread of.

So a single `type=ADP` response does **not** contain two independent concepts
("expert ranking" vs. "market ADP"). The transformation layer maps `rank_ave`
to `consensus_adp_half` and passes `rank_ecr` through as the ADP ordinal, so
its `adp_vs_ecr` metric is currently a small residual, not a true
ADP-vs-ECR gap. A genuine ECR comparison would need a separate `type=ECR`
(or `/rankings`) pull, which is not yet cached.

#### `experts=show` drops the per-player `tier` field

When `experts=show` is supplied (the production pull, needed for
platform-specific ADP), the response adds the nested `experts` dict and
`rank_points` but **omits** the per-player `tier` field that the
`experts`-less pull returns. The consolidated checkpoint therefore keeps a
`tier` column but leaves it null for now.

## Platform-specific ADP

FantasyPros support confirmed that individual platform ADP values are included
within each player record returned by `consensus-rankings` when `experts=show`
is supplied.

The values are stored in each player's `experts` dictionary, keyed by
FantasyPros expert/source ID.

Confirmed source IDs:
- `236` = Yahoo
- `439` = RTSports
- `79` = ESPN
- `80` = CBS
- `624` = Fantrax
- `4350` = Sleeper

### Half-PPR platform ADP

`GET /nfl/2026/consensus-rankings`

Working parameters:
- `position=ALL`
- `type=ADP`
- `scoring=HALF`
- `experts=show`

Observed Half-PPR sources:
- `236` = Yahoo
- `439` = RTSports
- `4350` = Sleeper

Example player-level structure:

```python
"experts": {
    "236": "4",
    "439": "4",
    "4350": "6"
}
```

FantasyPros support confirmed:
- Yahoo ADP is available only as Half-PPR.
- Yahoo, RTSports, and Sleeper values from this response can therefore provide
  the desired Half-PPR platform-specific ADP fields.

Desired downstream fields:
- `Yahoo_ADP_HALF`
- `RTSports_ADP_HALF`
- `Sleeper_ADP_HALF`

### ESPN PPR ADP

ESPN uses PPR as its default scoring format and FantasyPros support confirmed
that ESPN ADP is available only under PPR scoring.

Working parameters:
- `position=ALL`
- `type=ADP`
- `scoring=PPR`
- `experts=show`

Observed PPR response:
- 699 players
- 5 sources
- Source IDs: `79,80,439,624,4350`

Observed player-level sources:
- `79` = ESPN
- `80` = CBS
- `439` = RTSports
- `624` = Fantrax
- `4350` = Sleeper

Use:
- `experts["79"]` → `ESPN_ADP_PPR`

Important:
- Do not substitute PPR RTSports or Sleeper values for their Half-PPR values.
- Use the existing Half-PPR response for Yahoo, RTSports, and Sleeper.
- Use the PPR response only to enrich the primary dataset with ESPN PPR ADP.

### Join / dataset strategy

The existing 2026 Half-PPR consensus-ranking dataset remains the primary
draft-board universe.

Platform-specific ADP should be treated as enrichment:
- Extract Yahoo, RTSports, and Sleeper ADP from the Half-PPR consensus response.
- Extract ESPN ADP from the PPR consensus response.
- Join ESPN PPR ADP onto the Half-PPR player universe using `player_id`.
- Do not expand the primary player universe to the larger PPR response.

### Coverage validation

Platform-specific ADP coverage was validated against the Half-PPR consensus
ranking dataset, which contained 365 players at the time of testing.

Overall coverage:
- Yahoo Half-PPR: 224 / 365 (61.4%)
- RTSports Half-PPR: 298 / 365 (81.6%)
- Sleeper Half-PPR: 320 / 365 (87.7%)
- ESPN PPR: 242 / 365 (66.3%)

The lower overall coverage reflects differences in how deeply each platform
ranks players rather than meaningful missingness among draft-relevant players.

Coverage by ECR:
- Top 50: 100% across all four platforms
- Top 100: 100% across all four platforms
- Top 150: 100% across all four platforms
- Top 200:
  - Yahoo: 100%
  - RTSports: 100%
  - Sleeper: 100%
  - ESPN: 96.5%

Conclusion:
- Platform-specific ADP coverage is sufficient for the v1 draft board.
- Missing ADP values should remain missing rather than being imputed.
- No additional investigation is required before productionizing the source.

## Rankings endpoint
`GET /nfl/2026/rankings`

Useful for:
- ECR
- Overall and positional rankings
- Expert counts / expert IDs
- Best Ball rankings

Observed ranking groups:
- `STD`
- `PPR`
- `HALF`
- `DYN`
- `BB-HALF`
- weekly equivalents

Not useful for current platform-ADP problem:
- Normal redraft Yahoo/Sleeper/RTSports ADP was not exposed directly.
- `ADP -> BB-HALF` appears to be Best Ball ADP.

## Preseason projections

### 2026 season-long projections
`GET /nfl/2026/projections`

Purpose:
- Season-long 2026 preseason projections
- Primary v1 field for the consolidated draft board: Half-PPR projected fantasy points
- Preserve the full raw projection payload for potential future position-specific analysis

Working parameters:
- `week=0` for preseason / season-long projections
- `position=ALL`

Observed response:
- ~603 players
- Positions include QB, RB, WR, TE, K, DST
- `tier=premium`
- Top-level `scoring` was observed as `STD` even when `scoring=HALF` was supplied
- Player records include separate scoring fields in `stats`, including:
  - `points`
  - `points_ppr`
  - `points_half`
- Use `stats["points_half"]` for the primary Half-PPR draft dataset

Important schema differences from consensus rankings:
- Consensus `player_id` corresponds to projection `fpid`
- Consensus `player_name` corresponds to projection `name`
- Consensus `player_team_id` corresponds to projection `team_id`
- Consensus `player_position_id` corresponds to projection `position_id`

Join validation:
- `player_id` / `fpid` was confirmed on individual players and across the dataset
- 301 of 340 consensus-ranking players (~88.5%) had a matching projection record
- Missing projection records were largely inactive/free-agent/non-relevant players from the broader ranking universe
- Use the consensus player dataset as the primary player universe and LEFT JOIN projections onto it
- Do not drop players with missing projections
- Do not fill missing projections with zero; missing means no projection was provided

Primary downstream field:
- `projected_points_half`

Potential future use:
- Raw projection records also contain position-specific projected stats
  (e.g. receptions, rushing attempts/yards, passing stats)
- Keep those in the raw cache for future position-specific tabs, but do not add
  them to the primary draft-day dataset yet

## Historical player points

### 2025 season-long Half-PPR player points
`GET /nfl/2025/player-points`

Purpose:
- Add prior-season performance context to the 2026 draft board
- Primary v1 fields:
  - `2025_games_played`
  - `2025_points_half`
  - `2025_ppg_half`

Working parameters:
- `position=ALL`
- `scoring=HALF`
- `start=1`
- `end=18`

Observed response:
- `season=2025`
- `scoring=HALF`
- ~2166 player records
- `tier=premium`

Relevant player fields observed:
- `player_id`
- `player_name`
- `position_id`
- `team_id`
- `games`
- `points`
- `average`
- `weeks`

Field mapping for the primary draft dataset:
- `games` → `2025_games_played`
- `points` → `2025_points_half`
- `average` → `2025_ppg_half`

Join validation:
- Join key is `player_id`
- 272 of 340 consensus-ranking players (80%) had matching 2025 player-points records
- Missing players were consistent with expected year-over-year turnover, especially:
  - 2026 rookies
  - players who did not produce applicable 2025 NFL fantasy data
  - fringe/free-agent players
- Known 2025 veteran stars were confirmed present
- Use the consensus player dataset as the primary player universe and LEFT JOIN 2025 player-points onto it
- Do not drop players with missing 2025 history
- Do not fill missing historical values with zero; missing means no applicable 2025 performance record was found

Notes:
- The endpoint returns a much broader historical universe (~2166 records) than the 2026 draft board.
- This is acceptable because the historical response is used as a lookup/enrichment source, not as the primary player universe.
- Weekly values under `weeks` should remain in the raw cache but are not needed in the primary season-long draft spreadsheet.

## Injuries endpoint

### 2026 preseason exploration
`GET /nfl/injuries`

Purpose explored:
- Determine whether FantasyPros injury data could provide useful preseason
  draft-day injury / availability context for the 2026 player universe

Parameters tested:
- `year=2026`
- `week=0`

Observed response:
- 17 injury records
- `tier=premium`
- Relevant fields included:
  - `player_id`
  - `name`
  - `team_id`
  - `position_id`
  - `status`
  - `status_short`
  - `injury_type`
  - `comment`
  - `injury_update_date`
  - `ir_weeks`
  - `probability_of_playing`
  - practice-report fields

Observed limitations:
- Coverage was very sparse for preseason draft purposes
- Many records represented recently retired or free-agent players rather than
  actionable fantasy draft injuries
- Other records captured high-profile players already known to be out for most
  or all of the season
- `probability_of_playing` was not populated in the explored response
- The endpoint did not provide broader draft-availability context such as suspensions
- Overall, the endpoint behaved more like a narrow player-unavailability /
  status feed than a comprehensive preseason injury-risk dataset

Decision:
- Do not productionize this endpoint for v1
- Do not add injury fields to the primary draft board from this source
- Current injury / suspension context can be handled through manual research
  closer to draft time unless a better structured source is identified later

## Transformation layer

`src/fantasy_football/transform/draft_checkpoint.py` is the first reusable
transformation module. It consumes the four cached payloads below (no API
calls), treats the Half-PPR consensus response as the primary player universe,
LEFT JOINs the others on `player_id` (consensus `player_id` == projections
`fpid`), derives `rank_range` and `adp_vs_ecr`, and returns one consolidated
player-level dataframe. `write_checkpoint_excel(df, path)` writes it to the
given path (single sheet, frozen header, autofilter) as a review checkpoint.
The pipeline runner's default path is date-stamped
(`outputs/fantasy_draft_checkpoint_YYYY_MM_DD.xlsx`). Demonstrated in
`notebooks/02_transform_consensus_adp.ipynb`.

## Pipeline runner

`python -m fantasy_football.pipeline` (`src/fantasy_football/pipeline.py`)
orchestrates extraction -> transformation -> validation -> Excel in one
command. By default it runs entirely off the cached raw JSON.

`--refresh` calls `refresh_raw_caches()` in `extract/fantasypros.py`, which
rebuilds the current-season caches listed in `REFRESHABLE_SOURCES`:

- `fantasypros_consensus_adp_2026_half.json` (`fetch_consensus_adp`)
- `fantasypros_consensus_adp_2026_ppr.json` (`fetch_consensus_adp_ppr`)
- `fantasypros_projections_2026.json` (`fetch_projections`)

`fantasypros_player_points_2025_half.json` is intentionally excluded (2025 is
complete). Add a source later by appending a `RefreshableSource` to that
tuple. A failed refresh propagates; the runner never falls back to stale cache.

## Caching strategy
- Save successful API responses under `data/raw/`.
- Develop transformations against cached JSON instead of repeatedly calling the API.
- Production projection cache:
  `fantasypros_projections_2026.json`
- Production 2025 player-points cache:
  `fantasypros_player_points_2025_half.json`

### Raw cache filenames
- Production extraction code (`src/fantasy_football/extract/fantasypros.py`) writes the
  Half-PPR consensus ADP pull to `fantasypros_consensus_adp_2026_half.json`.
  This pull now also sends `experts=show`, so the cached payload carries the
  nested per-player `experts` dict (Yahoo `236`, RTSports `439`, Sleeper `4350`).
- The same module writes the PPR consensus ADP pull (`scoring=PPR`,
  `experts=show`) to `fantasypros_consensus_adp_2026_ppr.json`
  (exported as `CONSENSUS_ADP_PPR_RAW_FILENAME`). The `_ppr` suffix keeps it
  beside the Half-PPR cache; scoring is chosen at request time for this
  endpoint. This response exists only to supply ESPN PPR ADP (`experts["79"]`)
  during transformation; it is not merged with the Half-PPR universe in the
  extraction layer.
- The same module writes the preseason projections pull to
  `fantasypros_projections_2026.json` (exported as `PROJECTIONS_RAW_FILENAME`).
  No `_half` suffix: the projections payload carries `points`, `points_ppr` and
  `points_half` together under each player's `stats`, so scoring is not chosen
  at request time.
- `fantasypros_adp_2026_half.json` is a legacy/sandbox name from notebook
  experimentation. Do not rely on it for production; it can be removed later.
  - The same module writes the 2025 Half-PPR player-points pull to
  `fantasypros_player_points_2025_half.json`
  (exported as `PLAYER_POINTS_RAW_FILENAME`).
  The `_half` suffix is retained because scoring is selected at request time
  for the player-points endpoint.