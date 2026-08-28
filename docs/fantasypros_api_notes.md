# FantasyPros API Notes
Current API implementation notes as of 8/28/26. Core FantasyPros extraction is working; platform-specific ADP remains under investigation.

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

## Caching strategy
- Save successful API responses under `data/raw/`.
- Develop transformations against cached JSON instead of repeatedly calling the API.
- Production projection cache:
  `fantasypros_projections_2026.json`

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