# FantasyPros API Notes
Current API implementation notes as of 8/28/26. Core FantasyPros extraction is working for consensus rankings, preseason projections, and historical player points. The injuries endpoint was evaluated and rejected for v1; platform-specific ADP remains under investigation.

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

## ADP sources

Half-PPR consensus currently uses three provider IDs:
- `236`
- `439`
- `4350`

Known:
- `4350` = Sleeper (`SleeperHQ` metadata)

Expected Half-PPR website sources:
- Yahoo
- Sleeper
- RTSports

Open issue:
- `filters=<source_id>` on `consensus-rankings` did not isolate an individual provider.
- API returned all three source IDs regardless.
- Support contacted for source-specific ADP access.

Desired eventual fields:
- `FP_ADP_HALF`
- `Yahoo_ADP_HALF`
- `Sleeper_ADP_HALF`
- `RTSports_ADP_HALF`
- `ESPN_ADP_PPR`

Important scoring note:
- ESPN ADP is PPR.
- Yahoo ADP is Half-PPR.
- Prefer Half-PPR data for all other fields where available.

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

## Caching strategy
- Save successful API responses under `data/raw/`.
- Develop transformations against cached JSON instead of repeatedly calling the API.
- Production projection cache:
  `fantasypros_projections_2026.json`
- Production 2025 player-points cache:
  `fantasypros_player_points_2025_half.json`

### Raw cache filenames
- Production extraction code (`src/fantasy_football/extract/fantasypros.py`) writes the
  consensus ADP pull to `fantasypros_consensus_adp_2026_half.json`.
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