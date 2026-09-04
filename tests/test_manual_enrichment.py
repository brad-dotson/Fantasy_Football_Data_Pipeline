"""Targeted checks for the curated ``data/manual/`` enrichment layer.

Covers:

* the ESPN draft-order + positional-tier loaders (happy path + failure modes),
* the LEFT-JOIN enrichment onto the shared checkpoint board,
* platform-specific league ordering (ESPN sorts by ``espn_order``; other
  platforms keep the shared checkpoint order),
* that snake pick metadata is assigned AFTER the platform reorder.

Plain-python (no pytest dependency), matching ``tests/test_leagues.py``. Run::

    python tests/test_manual_enrichment.py

Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

from fantasy_football.enrich.manual import (
    ManualEnrichmentError,
    apply_manual_enrichment,
    build_tier_enrichment,
    load_espn_draft_order,
    load_positional_tiers,
)
from fantasy_football.transform.draft_checkpoint import build_draft_checkpoint
from fantasy_football.leagues import (
    LeagueConfig,
    build_league_frame,
    load_league_configs,
    order_board_for_platform,
    snake_pick_table,
)

_MGRS_12 = tuple(f"M{i:02d}" for i in range(1, 13))


def _espn_cfg(num_teams: int = 12, draft_position: int = 3) -> LeagueConfig:
    return LeagueConfig(
        "ESPN L", num_teams, draft_position, tuple(f"M{i:02d}" for i in range(1, num_teams + 1)),
        (), "espn",
    )


def _sleeper_cfg(num_teams: int = 12, draft_position: int = 2) -> LeagueConfig:
    return LeagueConfig(
        "Sleeper L", num_teams, draft_position,
        tuple(f"M{i:02d}" for i in range(1, num_teams + 1)), (), "sleeper",
    )


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------


def test_espn_source_loads() -> None:
    """The checked-in ESPN draft-order file loads and is well-formed."""

    espn = load_espn_draft_order()
    assert list(espn.columns) == ["player_name", "espn_order"]
    assert espn["espn_order"].notna().all(), "every source row must carry an order"
    assert espn["player_name"].is_unique, "source player_name must be unique"
    assert espn["espn_order"].min() == 1
    # ordering column is a nullable integer, ascending, no dup ranks
    assert espn["espn_order"].is_unique
    print(f"ok  test_espn_source_loads  ->  {len(espn)} rows, order 1..{int(espn['espn_order'].max())}")


def test_espn_duplicate_player_fails_clearly() -> None:
    """A repeated player_name in the ESPN source is rejected with a clear message."""

    tmp = Path(tempfile.mkdtemp()) / "2026"
    tmp.mkdir()
    (tmp / "espn_draft_order_2026.csv").write_text(
        "espn_order,player_name\n1,Jahmyr Gibbs\n2,Bijan Robinson\n3,Jahmyr Gibbs\n",
        encoding="utf-8",
    )
    try:
        load_espn_draft_order(tmp.parent)
    except ManualEnrichmentError as exc:
        assert "duplicate player_name" in str(exc) and "Jahmyr Gibbs" in str(exc)
        print(f"ok  test_espn_duplicate_player_fails_clearly  ->  {exc}")
    else:
        raise AssertionError("expected ManualEnrichmentError for duplicate ESPN player_name")


def test_tiers_source_loads_and_splits_by_source() -> None:
    """Long-form tiers load; Hartman and Ringer rows stay separate."""

    long = load_positional_tiers()
    srcs = set(long["tier_source"].unique())
    assert srcs == {"David Hartman / Big Blue View", "The Ringer Fantasy Football Show"}, srcs
    wide = build_tier_enrichment(long)
    assert "hartman_tier" in wide.columns and "ringer_tier" in wide.columns
    assert wide["player_name"].is_unique
    print(f"ok  test_tiers_source_loads_and_splits_by_source  ->  {len(long)} long rows")


def test_tiers_conflicting_tier_fails() -> None:
    """One player/source mapping to two different tiers is rejected."""

    tmp = Path(tempfile.mkdtemp()) / "2026"
    tmp.mkdir()
    (tmp / "positional_tiers_2026.csv").write_text(
        "player_name,position,tier_source,tier,source_tier_label\n"
        "Josh Allen,QB,The Ringer Fantasy Football Show,1,Tier 1\n"
        "Josh Allen,QB,The Ringer Fantasy Football Show,2,Tier 2\n",
        encoding="utf-8",
    )
    try:
        load_positional_tiers(tmp.parent)
    except ManualEnrichmentError as exc:
        assert "more than one tier" in str(exc)
        print(f"ok  test_tiers_conflicting_tier_fails  ->  {exc}")
    else:
        raise AssertionError("expected ManualEnrichmentError for conflicting tier")


# --------------------------------------------------------------------------
# Enrichment onto the board (LEFT JOIN semantics)
# --------------------------------------------------------------------------


def test_enrichment_is_left_join_not_inner() -> None:
    """apply_manual_enrichment keeps the full checkpoint universe and order."""

    # An inner join on any curated file would drop the ~150 checkpoint players
    # with no ESPN order and the WR-heavy set with no Ringer tier. A left join
    # keeps all 365 rows and marks the gaps <NA>.
    enriched = build_draft_checkpoint()
    assert len(enriched) == 365, len(enriched)
    assert enriched["player_id"].is_unique
    for col in ("espn_order", "hartman_tier", "ringer_tier"):
        assert col in enriched.columns
        # some matched, some missing -> proves left join (inner would drop rows)
        assert 0 < enriched[col].notna().sum() < len(enriched)
    # a player far outside ESPN coverage is retained with <NA> espn_order
    tail = enriched.iloc[-1]
    assert pd.isna(tail["espn_order"])
    print("ok  test_enrichment_is_left_join_not_inner")


def test_enrichment_row_count_guard() -> None:
    """A curated file that would fan out a checkpoint row is rejected."""

    board = pd.DataFrame(
        {"player_name": ["Jahmyr Gibbs", "Bijan Robinson"], "position": ["RB", "RB"], "player_id": [1, 2]}
    )
    tmp = Path(tempfile.mkdtemp()) / "2026"
    tmp.mkdir()
    # duplicate name -> load_espn_draft_order already blocks this; assert it does
    (tmp / "espn_draft_order_2026.csv").write_text(
        "espn_order,player_name\n1,Jahmyr Gibbs\n2,Jahmyr Gibbs\n", encoding="utf-8"
    )
    (tmp / "positional_tiers_2026.csv").write_text(
        "player_name,position,tier_source,tier\n", encoding="utf-8"
    )
    try:
        apply_manual_enrichment(board, manual_dir=tmp.parent)
    except ManualEnrichmentError as exc:
        assert "duplicate" in str(exc).lower()
        print(f"ok  test_enrichment_row_count_guard  ->  {exc}")
    else:
        raise AssertionError("expected ManualEnrichmentError for fan-out join")


def test_hartman_and_ringer_do_not_collapse() -> None:
    """hartman_tier / ringer_tier / tier are independent columns."""

    df = build_draft_checkpoint()
    # Ja'Marr Chase: Hartman WR tier 1, no Ringer WR rows exist at all
    chase = df.loc[df["player_name"] == "Ja'Marr Chase"].iloc[0]
    assert chase["hartman_tier"] == 1
    assert pd.isna(chase["ringer_tier"]), "Ringer WR tiers are not published -> must stay null"
    # Jahmyr Gibbs: both sources, both tier 1, but still two distinct columns
    gibbs = df.loc[df["player_name"] == "Jahmyr Gibbs"].iloc[0]
    assert gibbs["hartman_tier"] == 1 and gibbs["ringer_tier"] == 1
    # FantasyPros `tier` column is untouched (still empty in the current pull)
    assert df["tier"].notna().sum() == 0
    print("ok  test_hartman_and_ringer_do_not_collapse")


def test_missing_ringer_tier_stays_null() -> None:
    """No inference: a Hartman-only player keeps ringer_tier == <NA>."""

    df = build_draft_checkpoint()
    hartman_only = df[df["hartman_tier"].notna() & df["ringer_tier"].isna()]
    assert len(hartman_only) > 0
    assert hartman_only["ringer_tier"].isna().all()
    print(f"ok  test_missing_ringer_tier_stays_null  ->  {len(hartman_only)} Hartman-only players")


# --------------------------------------------------------------------------
# Platform-specific league ordering
# --------------------------------------------------------------------------


def _fallback_board() -> pd.DataFrame:
    """Tiny checkpoint-shaped board exercising every fallback branch.

    Expected ESPN sort key -> order:
      A espn_order=1                  -> 1.0
      B espn_order=<NA> adp=1.5       -> 1.5   (fallback, interleaves A..C)
      C espn_order=2   adp=3.0        -> 2.0
      F espn_order=4   adp=9.0        -> 4.0
      D espn_order=<NA> adp=<NA>      -> last, checkpoint order
      E espn_order=<NA> adp=<NA>      -> last, after D
    => [A, B, C, F, D, E]
    """

    return pd.DataFrame(
        {
            "player_name": ["A", "B", "C", "D", "E", "F"],
            "player_id": [1, 2, 3, 4, 5, 6],
            "position": ["RB", "WR", "RB", "TE", "QB", "RB"],
            "espn_order": pd.array([1, None, 2, None, None, 4], dtype="Int64"),
            "consensus_adp_half": [1.0, 1.5, 3.0, None, None, 9.0],
        }
    )


def test_espn_fallback_to_consensus_adp() -> None:
    """Missing espn_order falls back to consensus_adp_half for ordering only."""

    board = _fallback_board()
    ordered = order_board_for_platform(board, _espn_cfg(num_teams=2, draft_position=1))

    # fallback player B interleaves between espn_order 1 (A) and 2 (C)
    assert list(ordered["player_name"]) == ["A", "B", "C", "F", "D", "E"]
    # both-missing players keep their checkpoint relative order at the tail
    assert list(ordered["player_name"])[-2:] == ["D", "E"]
    # espn_order is NEVER imputed: it is still <NA> exactly where the source was
    src_na = {"B", "D", "E"}
    for _, row in ordered.iterrows():
        if row["player_name"] in src_na:
            assert pd.isna(row["espn_order"]), f"{row['player_name']} espn_order must stay <NA>"
        else:
            assert not pd.isna(row["espn_order"])
    # the sourced values themselves are unchanged
    assert dict(zip(ordered["player_name"], ordered["espn_order"]))["C"] == 2
    print("ok  test_espn_fallback_to_consensus_adp")


def test_espn_sort_key_is_monotonic_on_real_board() -> None:
    """On the real board the effective key is non-decreasing until the tail."""

    df = build_draft_checkpoint()
    frame, _ = build_league_frame(df, _espn_cfg())

    key = frame["espn_order"].astype("Float64").fillna(frame["consensus_adp_half"].astype("Float64"))
    have_key = key.notna()
    # every row with a usable key comes before every row with neither value
    last_keyed = have_key[have_key].index.max()
    assert have_key.iloc[: last_keyed + 1].all(), "keyed rows must be contiguous at the top"
    # and that keyed prefix is sorted ascending
    kv = list(key.iloc[: last_keyed + 1])
    assert kv == sorted(kv), "fallback sort key must be ascending"

    # espn_order column still only holds sourced values (209 non-null, unchanged)
    assert frame["espn_order"].notna().sum() == df["espn_order"].notna().sum()
    tail_missing = frame.loc[~have_key, "player_name"].tolist()
    checkpoint_missing = [
        n for n in df["player_name"]
        if n in set(tail_missing)
    ]
    assert tail_missing == checkpoint_missing, "both-missing tail keeps checkpoint order"
    print(f"ok  test_espn_sort_key_is_monotonic_on_real_board  ->  "
          f"{int(have_key.sum())} keyed, {len(tail_missing)} both-missing tail")


def test_non_espn_league_preserves_checkpoint_order_exactly() -> None:
    """Draft Queens (sleeper) must show the shared board in checkpoint order."""

    df = build_draft_checkpoint()
    cfgs = {c.league_name: c for c in load_league_configs()}
    dq = cfgs["Draft Queens"]
    assert dq.draft_platform == "sleeper"
    frame, _ = build_league_frame(df, dq)
    assert list(frame["player_name"]) == list(df["player_name"])
    # order_board_for_platform is the identity for non-espn
    assert list(order_board_for_platform(df, dq)["player_name"]) == list(df["player_name"])
    print("ok  test_non_espn_league_preserves_checkpoint_order_exactly")


def test_snake_metadata_assigned_after_reorder() -> None:
    """Snake pick metadata is generated against the FINAL fallback-sorted board."""

    # synthetic board: exercised order is [A, B, C, F, D, E] (see _fallback_board)
    board = _fallback_board()
    cfg = _espn_cfg(num_teams=2, draft_position=1)
    frame, highlight_rows = build_league_frame(board, cfg)

    assert list(frame["player_name"]) == ["A", "B", "C", "F", "D", "E"]
    # overall_pick is a fresh 1..N over the sorted order
    assert list(frame["overall_pick"]) == [1, 2, 3, 4, 5, 6]
    table = snake_pick_table(cfg.num_teams, len(frame))
    assert [t["round"] for t in table] == list(frame["round"])
    assert [t["pick_in_round"] for t in table] == list(frame["pick_in_round"])
    # 2-team snake: manager order M01,M02 / M02,M01 / M01,M02
    assert list(frame["manager"]) == ["M01", "M02", "M02", "M01", "M01", "M02"]
    # draft_position 1 is on the clock at picks 1, 4, 5 (rows 0, 3, 4)
    assert highlight_rows == [0, 3, 4]

    # real board: pick numbering stays a clean 1..N over the reordered rows
    df = build_draft_checkpoint()
    big_cfg = _espn_cfg(num_teams=12, draft_position=3)
    big_frame, big_hl = build_league_frame(df, big_cfg)
    assert list(big_frame["overall_pick"]) == list(range(1, len(big_frame) + 1))
    big_table = snake_pick_table(big_cfg.num_teams, len(big_frame))
    assert [t["pick_in_round"] for t in big_table] == list(big_frame["pick_in_round"])
    assert [big_frame.loc[r, "overall_pick"] for r in big_hl][:4] == [3, 22, 27, 46]
    print("ok  test_snake_metadata_assigned_after_reorder")


def test_unknown_platform_rejected() -> None:
    """config parsing rejects an unrecognised draft_platform value."""

    import tempfile as _t

    p = Path(_t.mkdtemp()) / "leagues.yml"
    p.write_text(
        'leagues:\n'
        '  - league_name: "X"\n'
        '    num_teams: 4\n'
        '    draft_position: 1\n'
        '    draft_platform: yahoo\n'
        '    managers: ["a","b","c","d"]\n',
        encoding="utf-8",
    )
    try:
        load_league_configs(p)
    except Exception as exc:  # LeagueConfigError
        assert "draft_platform" in str(exc) and "yahoo" in str(exc)
        print(f"ok  test_unknown_platform_rejected  ->  {exc}")
    else:
        raise AssertionError("expected LeagueConfigError for unknown draft_platform")


def test_repo_config_has_platforms() -> None:
    """The checked-in config assigns a recognised platform to every league."""

    cfgs = load_league_configs()
    plats = {c.league_name: c.draft_platform for c in cfgs}
    assert plats.get("The Boys") == "espn"
    assert plats.get("Cherri") == "espn"
    assert plats.get("Draft Queens") == "sleeper"
    print(f"ok  test_repo_config_has_platforms  ->  {plats}")


def main() -> int:
    test_espn_source_loads()
    test_espn_duplicate_player_fails_clearly()
    test_tiers_source_loads_and_splits_by_source()
    test_tiers_conflicting_tier_fails()
    test_enrichment_is_left_join_not_inner()
    test_enrichment_row_count_guard()
    test_hartman_and_ringer_do_not_collapse()
    test_missing_ringer_tier_stays_null()
    test_espn_fallback_to_consensus_adp()
    test_espn_sort_key_is_monotonic_on_real_board()
    test_non_espn_league_preserves_checkpoint_order_exactly()
    test_snake_metadata_assigned_after_reorder()
    test_unknown_platform_rejected()
    test_repo_config_has_platforms()
    print("\nALL MANUAL-ENRICHMENT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
