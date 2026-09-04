"""Load the curated ``data/manual/`` CSVs and join them onto the shared board.

Two curated inputs are consumed, both keyed by exact ``player_name``:

* ``data/manual/<season>/espn_draft_order_<season>.csv`` -- a third-party proxy
  for the order players come off the board in ESPN drafts (``espn_order``).
* ``data/manual/<season>/positional_tiers_<season>.csv`` -- a long-form table of
  per-position draft tiers from multiple named sources. We expose two
  source-specific columns, ``hartman_tier`` and ``ringer_tier``; the FantasyPros
  ``tier`` column in the checkpoint is left untouched.

Design rules (from ``CLAUDE.md`` / the task brief):

* This layer is separate from FantasyPros extraction and makes no API calls.
* The curated files are *replaceable* inputs: a future scraper/agent can emit
  the same columns without any change here or downstream.
* Every join is a LEFT JOIN onto the shared checkpoint universe. Players are
  never dropped for missing curated data, and a missing value stays ``<NA>`` --
  never zero-filled, never inferred from another source.
* Curated source rows that do not match a checkpoint player are simply not
  joined; that is not an error (the ESPN file, for example, carries a handful of
  players outside the current checkpoint on purpose).
"""

from __future__ import annotations

from functools import reduce
from pathlib import Path

import pandas as pd
from pandas.errors import MergeError

__all__ = [
    "DEFAULT_MANUAL_DIR",
    "DEFAULT_SEASON",
    "ManualEnrichmentError",
    "TIER_SOURCE_COLUMNS",
    "apply_manual_enrichment",
    "build_tier_enrichment",
    "load_espn_draft_order",
    "load_positional_tiers",
]


# --- Locations ----------------------------------------------------------------

#: ``<repo>/src/fantasy_football/enrich/manual.py`` -> ``parents[3]`` == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Root of the curated manual inputs. ``data/manual/`` is intentionally NOT
#: ``data/raw/`` -- it holds human/AI-curated, source-attributed data.
DEFAULT_MANUAL_DIR = _REPO_ROOT / "data" / "manual"

#: Season subfolder used when no explicit season is passed.
DEFAULT_SEASON = 2026

#: ``tier_source`` value in the long-form tiers file -> the checkpoint column it
#: populates. Anything not listed here is ignored (kept out of the player board).
TIER_SOURCE_COLUMNS: dict[str, str] = {
    "David Hartman / Big Blue View": "hartman_tier",
    "The Ringer Fantasy Football Show": "ringer_tier",
}


class ManualEnrichmentError(RuntimeError):
    """A curated ``data/manual/`` input is missing, malformed, or ambiguous.

    The message is written to be shown directly to the user (no traceback).
    """


# --- Small helpers ----------------------------------------------------------


def _season_dir(manual_dir: str | Path | None, season: int) -> Path:
    base = Path(manual_dir) if manual_dir is not None else DEFAULT_MANUAL_DIR
    return base / str(season)


def _require_columns(df: pd.DataFrame, needed: set[str], where: str) -> None:
    missing = sorted(needed - set(df.columns))
    if missing:
        raise ManualEnrichmentError(f"{where}: missing required column(s): {', '.join(missing)}")


def _clean_str(series: pd.Series) -> pd.Series:
    """Trim whitespace, keep as pandas nullable ``string`` for exact joins."""

    return series.astype("string").str.strip()


# --- ESPN draft order -----------------------------------------------------


def load_espn_draft_order(
    manual_dir: str | Path | None = None, season: int = DEFAULT_SEASON
) -> pd.DataFrame:
    """Load the curated ESPN draft-room ordering as ``player_name`` + ``espn_order``.

    Returns one row per curated source entry (including the few flagged as not in
    the current checkpoint -- those simply will not join later). ``espn_order`` is
    a nullable ``Int64``.

    Raises
    ------
    ManualEnrichmentError
        If the file is absent, a required column is missing, a row has no
        numeric ``espn_order``, or a ``player_name`` appears more than once
        (which would make the downstream join ambiguous).
    """

    path = _season_dir(manual_dir, season) / f"espn_draft_order_{season}.csv"
    if not path.is_file():
        raise ManualEnrichmentError(f"ESPN draft-order file not found: {path}")

    raw = pd.read_csv(path)
    _require_columns(raw, {"espn_order", "player_name"}, path.name)

    out = pd.DataFrame(
        {
            "player_name": _clean_str(raw["player_name"]),
            "espn_order": pd.to_numeric(raw["espn_order"], errors="coerce").astype("Int64"),
        }
    )

    if out["espn_order"].isna().any():
        bad = out.loc[out["espn_order"].isna(), "player_name"].tolist()
        raise ManualEnrichmentError(
            f"{path.name}: {len(bad)} row(s) have a blank / non-numeric espn_order: {bad[:5]}"
        )

    dupes = sorted(out.loc[out["player_name"].duplicated(), "player_name"].dropna().tolist())
    if dupes:
        raise ManualEnrichmentError(
            f"{path.name}: duplicate player_name(s) would create ambiguous ESPN-order "
            f"matches: {dupes}"
        )

    return out


# --- Positional tiers ---------------------------------------------------


def load_positional_tiers(
    manual_dir: str | Path | None = None, season: int = DEFAULT_SEASON
) -> pd.DataFrame:
    """Load the long-form tiers file, filtered to the mapped sources.

    Returns the long-form rows (one per player/source) with cleaned
    ``player_name`` / ``position`` / ``tier_source`` and a nullable ``Int64``
    ``tier``. FantasyPros is not in this file; only the sources in
    :data:`TIER_SOURCE_COLUMNS` are kept.

    Raises
    ------
    ManualEnrichmentError
        If the file is absent, a required column is missing, a kept row has a
        blank / non-numeric ``tier``, or a single player/source resolves to more
        than one tier or more than one position.
    """

    path = _season_dir(manual_dir, season) / f"positional_tiers_{season}.csv"
    if not path.is_file():
        raise ManualEnrichmentError(f"positional-tiers file not found: {path}")

    raw = pd.read_csv(path)
    _require_columns(raw, {"player_name", "position", "tier_source", "tier"}, path.name)

    out = pd.DataFrame(
        {
            "player_name": _clean_str(raw["player_name"]),
            "position": _clean_str(raw["position"]),
            "tier_source": _clean_str(raw["tier_source"]),
            "tier": pd.to_numeric(raw["tier"], errors="coerce").astype("Int64"),
        }
    )

    # Keep only the sources we surface as columns; everything else is dropped.
    out = out[out["tier_source"].isin(TIER_SOURCE_COLUMNS)].reset_index(drop=True)

    if out["tier"].isna().any():
        bad = out.loc[out["tier"].isna(), ["player_name", "tier_source"]].to_dict("records")
        raise ManualEnrichmentError(
            f"{path.name}: {len(bad)} kept row(s) have a blank / non-numeric tier: {bad[:5]}"
        )

    # One player/source must resolve to exactly one tier and one position.
    grp = out.groupby(["tier_source", "player_name"], observed=True)
    multi_tier = grp["tier"].nunique()
    conflicts = multi_tier[multi_tier > 1]
    if len(conflicts):
        raise ManualEnrichmentError(
            f"{path.name}: player/source pair(s) with more than one tier: "
            f"{list(conflicts.index)[:5]}"
        )
    multi_pos = grp["position"].nunique()
    pos_conflicts = multi_pos[multi_pos > 1]
    if len(pos_conflicts):
        raise ManualEnrichmentError(
            f"{path.name}: player/source pair(s) with more than one position: "
            f"{list(pos_conflicts.index)[:5]}"
        )

    return out


def build_tier_enrichment(tiers_long: pd.DataFrame) -> pd.DataFrame:
    """Pivot the long-form tiers into one row per ``player_name``.

    Columns: ``player_name``, then for each mapped source its tier column
    (``hartman_tier`` / ``ringer_tier``) and a private ``<col>_position`` used
    only for the position cross-check in :func:`apply_manual_enrichment` (dropped
    before the board is returned). Sources are kept fully independent -- a player
    with only a Hartman tier gets ``<NA>`` for ``ringer_tier`` and vice versa.
    """

    frames: list[pd.DataFrame] = []
    for src, col in TIER_SOURCE_COLUMNS.items():
        sub = (
            tiers_long.loc[tiers_long["tier_source"] == src, ["player_name", "position", "tier"]]
            .drop_duplicates(subset=["player_name"])
            .rename(columns={"tier": col, "position": f"{col}_position"})
            .reset_index(drop=True)
        )
        frames.append(sub)

    # Outer merge so a player in either source (or both) survives.
    merged = reduce(
        lambda left, right: left.merge(right, on="player_name", how="outer"), frames
    )
    return merged


# --- Public entry point -----------------------------------------------------


def apply_manual_enrichment(
    checkpoint_df: pd.DataFrame,
    *,
    manual_dir: str | Path | None = None,
    season: int = DEFAULT_SEASON,
) -> pd.DataFrame:
    """LEFT JOIN the curated ESPN order + source tiers onto the checkpoint board.

    Adds three columns -- ``espn_order``, ``hartman_tier``, ``ringer_tier`` --
    keyed by exact ``player_name``. The checkpoint row universe and order are
    preserved exactly; unmatched players keep ``<NA>``.

    Raises
    ------
    ManualEnrichmentError
        If a curated input is bad (see the loaders), if a join would duplicate a
        checkpoint row, or if a matched tier row's source position disagrees with
        the checkpoint position.
    """

    df = checkpoint_df.copy()
    n_before = len(df)
    # Exact string join keys: normalise the board side the same way the loaders
    # normalise the curated side (nullable string, trimmed).
    join_key = _clean_str(df["player_name"])
    df["_join_name"] = join_key

    # --- ESPN draft-room order -------------------------------------------
    espn = load_espn_draft_order(manual_dir, season).rename(columns={"player_name": "_join_name"})
    try:
        df = df.merge(espn, on="_join_name", how="left", validate="m:1")
    except MergeError as exc:  # pragma: no cover - guarded upstream, kept explicit
        raise ManualEnrichmentError(f"ESPN draft-order join is not unique per player: {exc}") from exc

    # --- source-specific positional tiers ------------------------------
    tiers_long = load_positional_tiers(manual_dir, season)
    tier_wide = build_tier_enrichment(tiers_long).rename(columns={"player_name": "_join_name"})
    try:
        df = df.merge(tier_wide, on="_join_name", how="left", validate="m:1")
    except MergeError as exc:  # pragma: no cover - guarded upstream, kept explicit
        raise ManualEnrichmentError(f"positional-tier join is not unique per player: {exc}") from exc

    # Position cross-check on matched rows (where both sides have a position).
    board_pos = df["position"].astype("string").str.upper()
    for col in TIER_SOURCE_COLUMNS.values():
        pos_col = f"{col}_position"
        src_pos = df[pos_col].astype("string").str.upper()
        mismatch = df[df[col].notna() & src_pos.notna() & board_pos.notna() & (src_pos != board_pos)]
        if len(mismatch):
            sample = mismatch[["player_name", "position", pos_col]].head(5).to_dict("records")
            raise ManualEnrichmentError(
                f"{col}: curated source position disagrees with the checkpoint for "
                f"{len(mismatch)} matched player(s): {sample}"
            )

    df = df.drop(columns=["_join_name", *[f"{c}_position" for c in TIER_SOURCE_COLUMNS.values()]])

    if len(df) != n_before:
        raise ManualEnrichmentError(
            f"manual enrichment changed the checkpoint row count ({n_before} -> {len(df)})"
        )
    return df
