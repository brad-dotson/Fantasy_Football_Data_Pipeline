"""Targeted checks for the league layer: snake ordering + config validation.

Plain-python (no pytest dependency yet). Run directly::

    python tests/test_leagues.py

Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import re
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

from fantasy_football.leagues import (
    Keeper,
    KeeperConfigError,
    LeagueConfig,
    LeagueConfigError,
    build_league_frame,
    load_league_configs,
    resolve_keepers,
    snake_pick_table,
    write_league_workbook,
)


def test_snake_12_team_first_rounds() -> None:
    """Round 1 forward, round 2 reversed, round 3 forward -- 12-team league."""

    table = snake_pick_table(num_teams=12, num_picks=36)

    # Round 1: overall 1..12 -> slot 1..12, pick_in_round 1..12
    r1 = table[0:12]
    assert [t["overall_pick"] for t in r1] == list(range(1, 13))
    assert all(t["round"] == 1 for t in r1)
    assert [t["pick_in_round"] for t in r1] == list(range(1, 13))
    assert [t["slot"] for t in r1] == list(range(1, 13)), "round 1 must run slot 1->12"

    # Round 2: overall 13..24 -> slot 12..1 (reversed)
    r2 = table[12:24]
    assert all(t["round"] == 2 for t in r2)
    assert [t["pick_in_round"] for t in r2] == list(range(1, 13))
    assert [t["slot"] for t in r2] == list(range(12, 0, -1)), "round 2 must reverse to slot 12->1"

    # Round 3: forward again
    r3 = table[24:36]
    assert all(t["round"] == 3 for t in r3)
    assert [t["slot"] for t in r3] == list(range(1, 13)), "round 3 must run slot 1->12 again"

    # Spot-check the classic snake identities for slot 3 in a 12-team league.
    assert r1[2]["overall_pick"] == 3          # slot 3, round 1 -> pick 3
    assert r2[9]["overall_pick"] == 22         # slot 3, round 2 -> 3rd from last -> pick 22
    assert r3[2]["overall_pick"] == 27         # slot 3, round 3 -> pick 27
    print("ok  test_snake_12_team_first_rounds")


def test_highlight_follows_snake_slot() -> None:
    """draft_position highlighting must alternate forward/reverse with the snake."""

    cfg = LeagueConfig(
        league_name="T",
        num_teams=12,
        draft_position=3,
        managers=tuple(f"M{i:02d}" for i in range(1, 13)),
    )
    checkpoint = pd.DataFrame({"player_id": range(1, 49), "player_name": [f"P{i}" for i in range(1, 49)]})
    frame, highlight_rows = build_league_frame(checkpoint, cfg)

    # league columns are prepended, shared columns preserved after them
    assert list(frame.columns[:4]) == ["overall_pick", "round", "pick_in_round", "manager"]
    assert list(frame.columns[4:]) == ["player_id", "player_name"]

    # slot 3 in a 12-team league is on the clock at overall picks 3, 22, 27, 46, ...
    got = [frame.loc[r, "overall_pick"] for r in highlight_rows]
    assert got[:4] == [3, 22, 27, 46], got
    # every highlighted row's manager is the slot-3 manager
    assert set(frame.loc[highlight_rows, "manager"]) == {"M03"}
    # and no non-highlighted row is that manager
    non = [r for r in range(len(frame)) if r not in set(highlight_rows)]
    assert "M03" not in set(frame.loc[non, "manager"])
    print("ok  test_highlight_follows_snake_slot")


def test_odd_team_count_snake() -> None:
    """Snake math holds for a non-12 league too (10 teams)."""

    table = snake_pick_table(num_teams=10, num_picks=30)
    assert [t["slot"] for t in table[0:10]] == list(range(1, 11))
    assert [t["slot"] for t in table[10:20]] == list(range(10, 0, -1))
    assert [t["slot"] for t in table[20:30]] == list(range(1, 11))
    # slot 5, round 2 -> pick_in_round 6 -> overall 16
    assert table[15]["slot"] == 5 and table[15]["overall_pick"] == 16
    print("ok  test_odd_team_count_snake")


def _write_yaml(text: str) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "leagues.yml"
    tmp.write_text(text, encoding="utf-8")
    return tmp


def test_config_validation_messages() -> None:
    """Each invalid-config rule fails with a clear, league-named message."""

    good = """
leagues:
  - league_name: "Alpha"
    num_teams: 4
    draft_position: 2
    managers: ["a", "b", "c", "d"]
"""
    cfgs = load_league_configs(_write_yaml(good))
    assert len(cfgs) == 1 and cfgs[0].num_teams == 4
    assert cfgs[0].draft_position_manager == "b"

    cases = {
        "manager count != num_teams": """
leagues:
  - league_name: "Bad Count"
    num_teams: 4
    draft_position: 2
    managers: ["a", "b", "c"]
""",
        "draft_position out of range": """
leagues:
  - league_name: "Bad Slot"
    num_teams: 4
    draft_position: 9
    managers: ["a", "b", "c", "d"]
""",
        "blank manager name": """
leagues:
  - league_name: "Blank Mgr"
    num_teams: 3
    draft_position: 1
    managers: ["a", "  ", "c"]
""",
        "missing key": """
leagues:
  - league_name: "No Teams"
    draft_position: 1
    managers: ["a"]
""",
    }
    for label, text in cases.items():
        try:
            load_league_configs(_write_yaml(text))
        except LeagueConfigError as exc:
            assert str(exc), f"{label}: empty error message"
            print(f"ok  config rejects: {label}  ->  {exc}")
        else:
            raise AssertionError(f"{label}: expected LeagueConfigError, none raised")


def test_repo_config_loads() -> None:
    """The checked-in config/leagues.yml loads and every entry is structurally valid.

    League names / counts are user-owned (hand-edited), so this asserts the
    invariants the code depends on, not specific names.
    """

    cfgs = load_league_configs()  # default path
    assert len(cfgs) >= 1
    for c in cfgs:
        assert c.league_name.strip()
        assert len(c.managers) == c.num_teams
        assert all(m.strip() for m in c.managers)
        assert 1 <= c.draft_position <= c.num_teams
    print(f"ok  test_repo_config_loads  ->  {[c.league_name for c in cfgs]}")


# --------------------------------------------------------------------------
# Keepers
# --------------------------------------------------------------------------

_MGRS_12 = tuple(f"M{i:02d}" for i in range(1, 13))


def _synthetic_board(n: int) -> pd.DataFrame:
    """Minimal checkpoint-shaped frame for keeper-resolution tests."""

    return pd.DataFrame(
        {
            "player_name": [f"Player {i:02d}" for i in range(1, n + 1)],
            "team": ["AAA"] * n,
            "position": (["RB", "WR", "QB", "TE"] * (n // 4 + 1))[:n],
            "pos_rank": [f"P{i}" for i in range(1, n + 1)],
        }
    )


def _cfg(keepers=(), *, name="L", num_teams=12, draft_position=3, managers=_MGRS_12) -> LeagueConfig:
    return LeagueConfig(name, num_teams, draft_position, managers, tuple(keepers))


def test_keepers_optional_absent_or_empty() -> None:
    """A league works with no `keepers` key and with an explicit empty list."""

    no_key = load_league_configs(
        _write_yaml(
            """
leagues:
  - league_name: "NoKeepers"
    num_teams: 4
    draft_position: 1
    managers: ["a", "b", "c", "d"]
"""
        )
    )[0]
    empty = load_league_configs(
        _write_yaml(
            """
leagues:
  - league_name: "EmptyKeepers"
    num_teams: 4
    draft_position: 1
    managers: ["a", "b", "c", "d"]
    keepers: []
"""
        )
    )[0]
    assert no_key.keepers == () and empty.keepers == ()
    assert resolve_keepers(_synthetic_board(20), no_key) == []
    print("ok  test_keepers_optional_absent_or_empty")


def test_keepers_partial_some_managers() -> None:
    """Only the managers explicitly listed get a keeper."""

    cfgs = load_league_configs(
        _write_yaml(
            """
leagues:
  - league_name: "Mixed"
    num_teams: 12
    draft_position: 3
    managers: ["M01","M02","M03","M04","M05","M06","M07","M08","M09","M10","M11","M12"]
    keepers:
      - manager: "M02"
        player_name: "Player 09"
        prior_draft_round: 5
      - manager: "M08"
        player_name: "Player 20"
        prior_draft_round: 3
"""
        )
    )
    (cfg,) = cfgs
    assert [k.manager for k in cfg.keepers] == ["M02", "M08"]
    res = resolve_keepers(_synthetic_board(60), cfg)
    assert {r.keeper.manager for r in res} == {"M02", "M08"}
    print("ok  test_keepers_partial_some_managers")


def test_keeper_round_formula() -> None:
    """keeper_round == prior_draft_round - 1."""

    assert Keeper("M01", "X", 8).keeper_round == 7
    assert Keeper("M01", "X", 2).keeper_round == 1
    res = resolve_keepers(_synthetic_board(60), _cfg([Keeper("M05", "Player 05", 6)]))
    assert res[0].keeper_round == 5
    print("ok  test_keeper_round_formula")


def test_keeper_consumed_pick_odd_round() -> None:
    """Odd keeper_round: consumed pick uses the forward slot order."""

    # M07, prior 4 -> keeper_round 3 (odd). Slot 7, round 3 -> overall 24 + 7 = 31.
    (res,) = resolve_keepers(_synthetic_board(60), _cfg([Keeper("M07", "Player 05", 4)]))
    assert res.keeper_round == 3
    assert res.consumed_overall_pick == 31
    assert res.consumed_pick_row == 30  # 0-based frame row
    print("ok  test_keeper_consumed_pick_odd_round")


def test_keeper_consumed_pick_even_round() -> None:
    """Even keeper_round: consumed pick uses the reversed slot order."""

    # M03, prior 3 -> keeper_round 2 (even). Slot 3 in round 2 -> overall 12 + (12-3+1) = 22.
    (res,) = resolve_keepers(_synthetic_board(60), _cfg([Keeper("M03", "Player 12", 3)]))
    assert res.keeper_round == 2
    assert res.consumed_overall_pick == 22
    # cross-check against the generated schedule, not a hard-coded assumption
    table = snake_pick_table(12, 60)
    match = [t for t in table if t["round"] == 2 and t["slot"] == 3]
    assert len(match) == 1 and match[0]["overall_pick"] == res.consumed_overall_pick
    print("ok  test_keeper_consumed_pick_even_round")


def test_keeper_invalid_manager() -> None:
    try:
        load_league_configs(
            _write_yaml(
                """
leagues:
  - league_name: "BadMgr"
    num_teams: 4
    draft_position: 1
    managers: ["a", "b", "c", "d"]
    keepers:
      - manager: "zzz"
        player_name: "Player 01"
        prior_draft_round: 5
"""
            )
        )
    except KeeperConfigError as exc:
        assert "zzz" in str(exc)
        print(f"ok  keeper rejects invalid manager  ->  {exc}")
    else:
        raise AssertionError("expected KeeperConfigError for unknown manager")


def test_keeper_duplicate_manager() -> None:
    try:
        load_league_configs(
            _write_yaml(
                """
leagues:
  - league_name: "DupMgr"
    num_teams: 4
    draft_position: 1
    managers: ["a", "b", "c", "d"]
    keepers:
      - manager: "b"
        player_name: "Player 01"
        prior_draft_round: 5
      - manager: "b"
        player_name: "Player 02"
        prior_draft_round: 7
"""
            )
        )
    except KeeperConfigError as exc:
        assert "more than one keeper" in str(exc)
        print(f"ok  keeper rejects duplicate manager  ->  {exc}")
    else:
        raise AssertionError("expected KeeperConfigError for duplicate keeper manager")


def test_keeper_prior_round_too_low() -> None:
    for bad in (1, 0, -3):
        try:
            load_league_configs(
                _write_yaml(
                    f"""
leagues:
  - league_name: "LowRound"
    num_teams: 4
    draft_position: 1
    managers: ["a", "b", "c", "d"]
    keepers:
      - manager: "a"
        player_name: "Player 01"
        prior_draft_round: {bad}
"""
                )
            )
        except KeeperConfigError as exc:
            assert ">= 2" in str(exc)
        else:
            raise AssertionError(f"expected KeeperConfigError for prior_draft_round={bad}")
    print("ok  test_keeper_prior_round_too_low")


def test_keeper_player_zero_or_multi_match() -> None:
    board = _synthetic_board(60)
    # zero matches
    try:
        resolve_keepers(board, _cfg([Keeper("M01", "Nobody At All", 5)]))
    except KeeperConfigError as exc:
        assert "Nobody At All" in str(exc) and "no rows" in str(exc)
        print(f"ok  keeper rejects zero player match  ->  {exc}")
    else:
        raise AssertionError("expected KeeperConfigError for zero player match")
    # multiple matches
    dup = pd.concat([board, board.iloc[[3]]], ignore_index=True)
    try:
        resolve_keepers(dup, _cfg([Keeper("M01", "Player 04", 5)]))
    except KeeperConfigError as exc:
        assert "2 rows" in str(exc)
        print(f"ok  keeper rejects multi player match  ->  {exc}")
    else:
        raise AssertionError("expected KeeperConfigError for multiple player match")


# --- Excel formatting (inspect the generated .xlsx directly) --------------


def _sheet_xml(zf: zipfile.ZipFile, name: str) -> str:
    wb = zf.read("xl/workbook.xml").decode()
    rid = dict(re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb))[name]
    rels = zf.read("xl/_rels/workbook.xml.rels").decode()
    target = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))[rid]
    return zf.read("xl/" + target).decode()


def _style_lookups(zf: zipfile.ZipFile):
    styles = zf.read("xl/styles.xml").decode()
    cellxfs = re.search(r"<cellXfs count=\"\d+\">(.*?)</cellXfs>", styles, re.S).group(1)
    xfs = re.findall(r"<xf\b.*?(?:/>|</xf>)", cellxfs, re.S)
    fills = re.findall(r"<fill>(.*?)</fill>", styles, re.S)
    fonts = re.findall(r"<font>(.*?)</font>", styles, re.S)

    def _attr(s, k):
        m = re.search(rf'{k}="(\d+)"', s)
        return int(m.group(1)) if m else 0

    def fill_rgb(xf_idx: int):
        i = _attr(xfs[xf_idx], "fillId")
        m = re.search(r'<(?:fg|bg)Color rgb="([0-9A-Fa-f]{8})"', fills[i])
        return m.group(1) if m else None

    def font_white(xf_idx: int):
        i = _attr(xfs[xf_idx], "fontId")
        return "FFFFFFFF" in fonts[i]

    return fill_rgb, font_white


def _cell_xf(xml: str, ref: str) -> int:
    m = re.search(rf'<c r="{ref}"(?: s="(\d+)")?', xml)
    return int(m.group(1)) if m and m.group(1) else 0


def test_keeper_excel_formatting_and_isolation() -> None:
    """Black manager/player cells land only on the right cells, right league."""

    from fantasy_football.transform.draft_checkpoint import build_draft_checkpoint

    board = build_draft_checkpoint()
    kept_a = board["player_name"].iloc[4]    # -> excel row 6
    kept_b = board["player_name"].iloc[40]   # -> excel row 42

    league_a = _cfg(
        [Keeper("M07", kept_a, 4), Keeper("M03", kept_b, 3)],  # M03 is the slot-3 owner
        name="League A",
    )
    league_b = LeagueConfig("League B", 10, 5, tuple(f"N{i:02d}" for i in range(1, 11)), ())

    out = Path(tempfile.mkdtemp()) / "wb.xlsx"
    write_league_workbook(board, [league_a, league_b], out)
    zf = zipfile.ZipFile(out)
    fill_rgb, font_white = _style_lookups(zf)

    a = _sheet_xml(zf, "League A")
    # consumed picks: M07 odd r3 -> overall 31 -> row 32 ; M03 even r2 -> overall 22 -> row 23
    for ref in ("A32", "A23", "E6", "E42"):
        xf = _cell_xf(a, ref)
        assert fill_rgb(xf) == "FF000000", f"{ref} should be black, got {fill_rgb(xf)}"
        assert font_white(xf), f"{ref} should have white text"
    # nothing else in those rows is blacked out
    for ref in ("B32", "C32", "D32", "E32", "F6", "G6", "F42", "B23"):
        xf = _cell_xf(a, ref)
        assert fill_rgb(xf) != "FF000000", f"{ref} must not be black"
    # amber row highlighting preserved (slot-3 owner rows still custom-formatted)
    assert len(re.findall(r'<row r="\d+"[^>]*customFormat="1"', a)) == 31
    # the keeper cell overrides amber for that ONE cell: row 23 is an amber row,
    # A23 is black but a sibling in the same row keeps amber
    assert fill_rgb(_cell_xf(a, "D23")) == "FFFFF2CC"

    # League B has no keepers: the same players stay normal, no black manager cell
    b = _sheet_xml(zf, "League B")
    assert "FF000000" not in {fill_rgb(_cell_xf(b, r)) for r in ("A32", "A23", "E6", "E42")}
    print("ok  test_keeper_excel_formatting_and_isolation")


def main() -> int:
    test_snake_12_team_first_rounds()
    test_highlight_follows_snake_slot()
    test_odd_team_count_snake()
    test_config_validation_messages()
    test_repo_config_loads()
    test_keepers_optional_absent_or_empty()
    test_keepers_partial_some_managers()
    test_keeper_round_formula()
    test_keeper_consumed_pick_odd_round()
    test_keeper_consumed_pick_even_round()
    test_keeper_invalid_manager()
    test_keeper_duplicate_manager()
    test_keeper_prior_round_too_low()
    test_keeper_player_zero_or_multi_match()
    test_keeper_excel_formatting_and_isolation()
    print("\nALL LEAGUE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
