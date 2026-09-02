"""Targeted checks for the league layer: snake ordering + config validation.

Plain-python (no pytest dependency yet). Run directly::

    python tests/test_leagues.py

Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

from fantasy_football.leagues import (
    LeagueConfig,
    LeagueConfigError,
    build_league_frame,
    load_league_configs,
    snake_pick_table,
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


def main() -> int:
    test_snake_12_team_first_rounds()
    test_highlight_follows_snake_slot()
    test_odd_team_count_snake()
    test_config_validation_messages()
    test_repo_config_loads()
    print("\nALL LEAGUE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
