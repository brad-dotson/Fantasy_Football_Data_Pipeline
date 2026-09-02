"""Build the 2026 half-PPR draft *checkpoint* board from cached raw payloads.

This is the first reusable transformation module. It reads the raw JSON that
``fantasy_football.extract.fantasypros`` has already cached under ``data/raw/``
and merges it into one player-level dataframe suitable for a quick Excel
review. It is deliberately small: load -> normalize each source -> left join ->
derive a couple of columns -> return.

Design rules (from ``CLAUDE.md`` / the task brief):

* The 2026 **half-PPR consensus ADP** response is the primary player universe
  (the "spine"). Every enrichment is a LEFT JOIN onto it, keyed by
  ``player_id``. Players are never dropped for missing enrichment data, and
  missing numeric enrichment stays ``NaN`` / ``<NA>`` -- never zero-filled.
* Extraction and transformation stay separate: nothing here calls the API.

Raw caches consumed (all written by the extraction module):

* ``fantasypros_consensus_adp_2026_half.json``  -- spine + Yahoo/RTSports/Sleeper ADP
* ``fantasypros_consensus_adp_2026_ppr.json``   -- ESPN PPR ADP only
* ``fantasypros_projections_2026.json``          -- 2026 projected half-PPR points
* ``fantasypros_player_points_2025_half.json``   -- 2025 actual half-PPR production

------------------------------------------------------------------------------
``rank_ecr`` vs. ``consensus_adp_half`` -- known ambiguity (read before relying
on ``adp_vs_ecr``):

The half-PPR cache is a ``type=ADP`` consensus-rankings pull. In that payload
FantasyPros reuses the ``rank_ecr`` field name to hold the consensus **ADP
ordinal** (a dense 1..N rank of players by average draft slot) -- it is *not* a
separate, non-ADP expert consensus ranking. The only other consensus number in
the same payload is ``rank_ave`` (the mean draft slot across the three ADP
sources), which ``rank_min`` / ``rank_max`` / ``rank_std`` describe the spread
of.

So this single cached response does **not** contain two independent concepts
("expert ranking" vs. "market ADP"). This module therefore:

* maps the raw ``rank_ecr`` straight through to ``rank_ecr`` (the ADP ordinal),
* maps the raw ``rank_ave`` to ``consensus_adp_half`` (the averaged ADP value)
  *and* to ``rank_avg`` -- in this payload they are the same source field,
* computes ``adp_vs_ecr = consensus_adp_half - rank_ecr``, which here compares
  the mean ADP slot to the ADP ordinal (a small residual), **not** market ADP
  vs. a true ECR.

Nothing is fabricated: both columns are populated from real fields. A genuine
ECR-vs-ADP comparison would need a separate ``type=ECR`` (or ``/rankings``)
pull that has not been cached yet. See ``RANK_ECR_VS_ADP_NOTE``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

__all__ = [
    "CHECKPOINT_COLUMNS",
    "RANK_ECR_VS_ADP_NOTE",
    "DEFAULT_RAW_DIR",
    "REQUIRED_RAW_FILES",
    "build_draft_checkpoint",
    "checkpoint_coverage_report",
    "write_checkpoint_excel",
]


# --- Locations -------------------------------------------------------------

#: Repo root, derived from this file's location:
#: ``<root>/src/fantasy_football/transform/draft_checkpoint.py`` -> ``parents[3]``.
#: Mirrors the same trick in the extraction module so the two layers agree on
#: where ``data/raw/`` lives without any config.
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Default local cache directory holding the raw API payloads.
DEFAULT_RAW_DIR = _REPO_ROOT / "data" / "raw"

# Raw-cache filenames (kept in sync with the extraction module's constants).
_HALF_CONSENSUS_FILE = "fantasypros_consensus_adp_2026_half.json"
_PPR_CONSENSUS_FILE = "fantasypros_consensus_adp_2026_ppr.json"
_PROJECTIONS_FILE = "fantasypros_projections_2026.json"
_PLAYER_POINTS_2025_FILE = "fantasypros_player_points_2025_half.json"

#: Raw cache files :func:`build_draft_checkpoint` reads. Exposed so callers
#: (e.g. the pipeline runner) can check the inputs exist before building in
#: cached mode, without reaching into this module's private constants.
REQUIRED_RAW_FILES: tuple[str, ...] = (
    _HALF_CONSENSUS_FILE,
    _PPR_CONSENSUS_FILE,
    _PROJECTIONS_FILE,
    _PLAYER_POINTS_2025_FILE,
)

# FantasyPros ``experts`` dict keys -> platform ADP columns.
# 236 = Yahoo, 439 = RTSports, 4350 = Sleeper are the half-PPR sources;
# 79 = ESPN is only present in the PPR response.
_HALF_ADP_SOURCES = {"236": "yahoo_adp_half", "439": "rtsports_adp_half", "4350": "sleeper_adp_half"}
_ESPN_PPR_SOURCE_KEY = "79"


#: One-line summary of the ranking/ADP ambiguity, re-exported so the notebook
#: and completion summary can surface it without re-deriving the explanation.
RANK_ECR_VS_ADP_NOTE = (
    "The 2026 half-PPR cache is a type=ADP consensus-rankings pull. Its "
    "'rank_ecr' field is the consensus ADP ordinal, not a separate expert "
    "ranking; 'rank_ave' is the averaged ADP value. consensus_adp_half is "
    "mapped from rank_ave (same source as rank_avg), so adp_vs_ecr here is "
    "(mean ADP slot - ADP ordinal), NOT market-ADP-vs-true-ECR. A real ECR "
    "comparison needs a separate type=ECR / /rankings pull that is not cached."
)


#: Final column order for the checkpoint dataframe / Excel sheet. ``tier`` is
#: intentionally kept even though the current half-PPR cache does not carry it
#: (see :func:`_load_half_consensus`).
CHECKPOINT_COLUMNS = [
    # identity / context
    "player_name",
    "team",
    "position",
    "pos_rank",
    "bye_wk",
    # fantasypros ranking / consensus
    "rank_ecr",
    "consensus_adp_half",
    "tier",
    "rank_min",
    "rank_max",
    "rank_avg",
    "rank_std",
    "rank_range",
    # platform-specific adp
    "yahoo_adp_half",
    "rtsports_adp_half",
    "sleeper_adp_half",
    "espn_adp_ppr",
    # prior-season performance (2025 half-PPR)
    "2025_games_played",
    "2025_points_half",
    "2025_ppg_half",
    # 2026 projections
    "projected_points_half",
    # derived draft metrics
    "adp_vs_ecr",
    # optional / review before final dataset
    "eligible_positions",
    # merge / reference keys
    "player_id",
    "sportsdata_id",
    "player_yahoo_id",
    "cbs_player_id",
]


# --- Small helpers -------------------------------------------------------------


def _load_json(raw_dir: Path, filename: str) -> dict[str, Any]:
    """Read one cached JSON payload from ``raw_dir``."""

    with (raw_dir / filename).open("r", encoding="utf-8") as f:
        return json.load(f)


def _num(series: pd.Series) -> pd.Series:
    """Safe numeric coercion.

    Many FantasyPros numeric fields arrive as strings ("105.67", "113"). Bad /
    missing values become ``NaN`` rather than raising -- we never want to drop a
    player or invent a value just because one cell will not parse.
    """

    return pd.to_numeric(series, errors="coerce")


def _int_nullable(series: pd.Series) -> pd.Series:
    """Numeric coercion to pandas' nullable ``Int64`` (whole-number fields).

    Used for counts like bye week / games played so the Excel sheet shows ``7``
    rather than ``7.0`` while still allowing a true missing value (``<NA>``).
    """

    return _num(series).round().astype("Int64")


def _experts_value(experts: Any, key: str) -> Any:
    """Pull ``experts[key]`` defensively (the dict may be missing / partial)."""

    if isinstance(experts, dict):
        return experts.get(key)
    return None


# --- Per-source normalizers -------------------------------------------------


def _load_half_consensus(raw_dir: Path) -> pd.DataFrame:
    """Normalize the half-PPR consensus ADP payload into the spine dataframe.

    Produces one row per player in the primary universe with: identity fields,
    the consensus ranking/ADP block, the three half-PPR platform ADPs, and the
    reference ID columns. All ranking/ADP values are coerced to numeric.
    """

    payload = _load_json(raw_dir, _HALF_CONSENSUS_FILE)
    raw = pd.DataFrame(payload["players"])

    df = pd.DataFrame()

    # identity / context
    df["player_id"] = raw["player_id"].astype("int64")
    df["player_name"] = raw["player_name"]
    df["team"] = raw["player_team_id"]  # player_team_id -> team
    df["position"] = raw["player_position_id"]  # player_position_id -> position
    df["pos_rank"] = raw["pos_rank"]
    df["bye_wk"] = _int_nullable(raw["player_bye_week"])  # player_bye_week -> bye_wk

    # fantasypros ranking / consensus block
    df["rank_ecr"] = _num(raw["rank_ecr"])  # ADP ordinal in a type=ADP pull
    # consensus_adp_half: mapped from rank_ave. This payload has no field that
    # is a *separate* consensus ADP number, so we use the averaged ADP slot.
    # This is the same source as rank_avg below (documented, not fabricated).
    df["consensus_adp_half"] = _num(raw["rank_ave"])
    # tier: not present once experts=show is requested (the current production
    # pull). Keep the column so the review schema is stable; leave it missing
    # rather than sourcing it from the legacy/sandbox cache.
    df["tier"] = raw["tier"] if "tier" in raw.columns else pd.Series(pd.NA, index=raw.index, dtype="Int64")
    df["rank_min"] = _num(raw["rank_min"])
    df["rank_max"] = _num(raw["rank_max"])
    df["rank_avg"] = _num(raw["rank_ave"])  # rank_ave -> rank_avg
    df["rank_std"] = _num(raw["rank_std"])

    # half-PPR platform ADP from the nested experts dict (values are strings)
    for src_key, col in _HALF_ADP_SOURCES.items():
        df[col] = _num(raw["experts"].apply(lambda e, k=src_key: _experts_value(e, k)))

    # optional / review
    df["eligible_positions"] = raw["player_eligibility"]  # player_eligibility -> eligible_positions

    # merge / reference keys (kept as-is; these are string IDs)
    df["sportsdata_id"] = raw["sportsdata_id"]
    df["player_yahoo_id"] = raw["player_yahoo_id"]
    df["cbs_player_id"] = raw["cbs_player_id"]

    return df


def _load_espn_ppr_adp(raw_dir: Path) -> pd.DataFrame:
    """Extract just ``player_id`` + ESPN PPR ADP from the PPR consensus payload.

    The PPR response is a broader universe (~700 players); we take nothing from
    it except ESPN's ADP (``experts["79"]``) and let the caller LEFT JOIN it
    onto the half-PPR spine by ``player_id``.
    """

    payload = _load_json(raw_dir, _PPR_CONSENSUS_FILE)
    raw = pd.DataFrame(payload["players"])

    out = pd.DataFrame({"player_id": raw["player_id"].astype("int64")})
    out["espn_adp_ppr"] = _num(
        raw["experts"].apply(lambda e: _experts_value(e, _ESPN_PPR_SOURCE_KEY))
    )
    # Only rows that actually carry an ESPN value are useful enrichment.
    out = out.dropna(subset=["espn_adp_ppr"])
    return out.drop_duplicates(subset="player_id", keep="first")


def _load_projections(raw_dir: Path) -> pd.DataFrame:
    """Extract ``player_id`` + 2026 projected half-PPR points.

    Join key note: consensus ``player_id`` == projections ``fpid``. Only
    ``stats["points_half"]`` is taken; the rest of the projection payload stays
    in the raw cache for future position-specific work.
    """

    payload = _load_json(raw_dir, _PROJECTIONS_FILE)
    raw = pd.DataFrame(payload["players"])

    out = pd.DataFrame({"player_id": raw["fpid"].astype("int64")})  # fpid -> player_id
    out["projected_points_half"] = _num(
        raw["stats"].apply(lambda s: s.get("points_half") if isinstance(s, dict) else None)
    )
    return out.drop_duplicates(subset="player_id", keep="first")


def _load_player_points_2025(raw_dir: Path) -> pd.DataFrame:
    """Extract 2025 actual half-PPR production, joined on ``player_id``.

    Renames: ``games`` -> ``2025_games_played``, ``points`` -> ``2025_points_half``,
    ``average`` -> ``2025_ppg_half``. The weekly breakdown stays in the raw cache.
    """

    payload = _load_json(raw_dir, _PLAYER_POINTS_2025_FILE)
    raw = pd.DataFrame(payload["players"])

    out = pd.DataFrame({"player_id": raw["player_id"].astype("int64")})
    out["2025_games_played"] = _int_nullable(raw["games"])
    out["2025_points_half"] = _num(raw["points"])
    out["2025_ppg_half"] = _num(raw["average"])
    return out.drop_duplicates(subset="player_id", keep="first")


# --- Public API -----------------------------------------------------------


def build_draft_checkpoint(raw_dir: str | Path | None = None) -> pd.DataFrame:
    """Build the consolidated 2026 half-PPR draft checkpoint dataframe.

    Parameters
    ----------
    raw_dir:
        Directory holding the cached raw JSON payloads. Defaults to
        :data:`DEFAULT_RAW_DIR` (``<repo>/data/raw``).

    Returns
    -------
    pandas.DataFrame
        One row per player in the half-PPR consensus universe, columns in
        :data:`CHECKPOINT_COLUMNS` order. Enrichment is LEFT JOINed on
        ``player_id``; missing enrichment values stay ``NaN`` / ``<NA>``.
    """

    raw_dir = Path(raw_dir) if raw_dir is not None else DEFAULT_RAW_DIR

    # 1. spine = primary player universe
    df = _load_half_consensus(raw_dir)

    # 2. left-join each enrichment on player_id. validate="m:1" would also pass
    #    (spine keys are unique), but "1:1" documents + enforces the intent:
    #    exactly one enrichment row per player, so no join can duplicate a player.
    for enrich in (
        _load_espn_ppr_adp(raw_dir),
        _load_projections(raw_dir),
        _load_player_points_2025(raw_dir),
    ):
        df = df.merge(enrich, on="player_id", how="left", validate="1:1")

    # 3. derived metrics
    #    rank_range: width of the expert ADP range for the player.
    df["rank_range"] = df["rank_max"] - df["rank_min"]
    #    adp_vs_ecr: per the brief's formula. See RANK_ECR_VS_ADP_NOTE for why
    #    this is a small residual here rather than a true market-vs-ECR gap.
    df["adp_vs_ecr"] = df["consensus_adp_half"] - df["rank_ecr"]

    # 4. lock column order (every name in CHECKPOINT_COLUMNS is now present)
    return df[CHECKPOINT_COLUMNS].copy()


def checkpoint_coverage_report(df: pd.DataFrame) -> dict[str, Any]:
    """Lightweight QA summary for the checkpoint dataframe.

    Returns row/uniqueness checks plus non-null enrichment coverage counts, so
    the notebook can print a compact validation block without duplicating logic.
    """

    enrichment_cols = [
        "espn_adp_ppr",
        "yahoo_adp_half",
        "rtsports_adp_half",
        "sleeper_adp_half",
        "projected_points_half",
        "2025_games_played",
        "2025_points_half",
        "2025_ppg_half",
        "tier",
    ]
    n = len(df)
    return {
        "row_count": n,
        "player_id_unique": bool(df["player_id"].is_unique),
        "player_id_nulls": int(df["player_id"].isna().sum()),
        "coverage": {
            col: {"non_null": int(df[col].notna().sum()), "pct": round(df[col].notna().mean() * 100, 1)}
            for col in enrichment_cols
        },
        # zero-fill guard: enrichment "missing" must read as NaN, not 0.
        "min_projected_points_half": (
            None if df["projected_points_half"].notna().sum() == 0
            else float(df["projected_points_half"].min())
        ),
    }


def write_checkpoint_excel(df: pd.DataFrame, out_path: str | Path) -> Path:
    """Write ``df`` to a single-sheet Excel review workbook.

    Minimal formatting only: frozen header row, autofilter, and sane column
    widths. No colors / conditional formatting / charts -- this is a review
    checkpoint, not the final draft-day workbook. Internal column names are
    kept as-is (not relabeled for presentation).
    """

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        sheet = "checkpoint"
        df.to_excel(writer, sheet_name=sheet, index=False)
        worksheet = writer.sheets[sheet]

        n_rows, n_cols = df.shape
        worksheet.freeze_panes(1, 0)  # keep the header visible while scrolling
        worksheet.autofilter(0, 0, n_rows, n_cols - 1)

        # width = longest of (header, a sample of cell values), clamped to a
        # readable band so long ID strings do not blow the layout out.
        sample = df.head(150)
        for i, col in enumerate(df.columns):
            longest = max(
                [len(str(col))] + [len(str(v)) for v in sample[col].tolist() if v is not None]
            )
            worksheet.set_column(i, i, max(10, min(longest + 2, 40)))

    return out_path
