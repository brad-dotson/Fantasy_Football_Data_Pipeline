# FantasyPros API Notes
Still troubleshooting the API as of 8/27/26 - these are the latest notes. 

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

## Caching strategy
- Save successful API responses under `data/raw/`.
- Develop transformations against cached JSON instead of repeatedly calling the API.