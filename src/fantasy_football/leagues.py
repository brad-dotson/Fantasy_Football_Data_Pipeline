"""League-specific draft sheets: config, snake-draft ordering, workbook output.

This layer is deliberately separate from FantasyPros extraction *and* from the
shared player transformation. It takes the ONE shared checkpoint dataframe
(built once by :mod:`fantasy_football.transform`) and, per league, prepends four
draft-context columns computed from a small YAML config:

    overall_pick | round | pick_in_round | manager | <shared checkpoint columns...>

Design rules (from the task brief):

* The shared player pipeline is *not* duplicated per league -- every league sheet
  is the same checkpoint dataframe with a different four-column snake-draft
  prefix.
* League config lives in ``config/leagues.yml`` and supports any number of
  leagues with no code change.
* No keeper logic yet -- that is the immediate next iteration.

Snake draft: round 1 goes ``managers[0] .. managers[-1]``; round 2 reverses;
odd rounds forward, even rounds reversed, for as many picks as there are rows in
the checkpoint dataframe. ``draft_position`` is the config owner's 1-based slot;
rows where that slot is on the clock are highlighted in the sheet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml

from fantasy_football.transform.draft_checkpoint import ColumnSpec, build_data_dictionary

__all__ = [
    "LeagueConfig",
    "LeagueConfigError",
    "LEAGUE_COLUMNS",
    "LEAGUE_COLUMN_SCHEMA",
    "DEFAULT_LEAGUE_CONFIG",
    "load_league_configs",
    "snake_pick_table",
    "build_league_frame",
    "write_league_workbook",
]


# --- Locations --------------------------------------------------------------

#: ``<repo>/src/fantasy_football/leagues.py`` -> ``parents[2]`` == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Default YAML league config. Hand-edited by the project owner.
DEFAULT_LEAGUE_CONFIG = _REPO_ROOT / "config" / "leagues.yml"

#: The four columns prepended to every league sheet (dataframe order, unchanged).
LEAGUE_COLUMNS = ["overall_pick", "round", "pick_in_round", "manager"]

# --- Excel-only presentation (does NOT touch dataframe column names/order) ---

#: Left-most column order shown in each league worksheet. Everything after
#: ``position`` keeps the shared checkpoint column order. The dataframe returned
#: by :func:`build_league_frame` is unaffected.
_LEAGUE_SHEET_LEAD_ORDER = [
    "manager",
    "overall_pick",
    "round",
    "pick_in_round",
    "player_name",
    "team",
    "position",
]

#: Header labels used in the Excel league sheets only (internal names unchanged).
_HEADER_DISPLAY_NAMES = {
    "overall_pick": "pick",
    "round": "rnd",
    "pick_in_round": "rnd_pick",
}

#: Last frozen column in a league sheet: through ``position`` inclusive (A:G).
_FREEZE_THROUGH = "position"

#: Simple, readable highlight fill for "your slot is on the clock" rows.
_HIGHLIGHT_COLOR = "#FFF2CC"  # pale amber

#: Pastel fills for the ``position`` cells (black text stays readable on all).
_POSITION_FILLS = {
    "RB": "#F8CBCB",   # red / pink
    "WR": "#FBF0B2",   # yellow
    "QB": "#CFE0F3",   # blue
    "TE": "#CDEBD6",   # green
    "DST": "#DCDCDC",  # grey
    "K": "#E4D3F0",    # purple
}

#: League-sheet header style: centered, bold, white-on-blue.
_HEADER_FILL = "#4472C4"


#: Data-dictionary metadata for the four league-specific columns. Kept beside
#: the checkpoint schema's :data:`~fantasy_football.transform.draft_checkpoint.CHECKPOINT_SCHEMA`
#: so the ``data_dictionary`` sheet also documents the league prefix.
LEAGUE_COLUMN_SCHEMA: tuple[ColumnSpec, ...] = (
    ColumnSpec(
        "overall_pick",
        "Draft context (league-specific)",
        "Overall draft pick number, 1..N -- one per checkpoint row, in the shared "
        "checkpoint ranking order.",
        "Derived per league from `config/leagues.yml` (`num_teams`).",
        "Shown in the Excel league sheets as `pick`.",
    ),
    ColumnSpec(
        "round",
        "Draft context (league-specific)",
        "Draft round number. Derived: `(overall_pick - 1) // num_teams + 1`.",
        "Derived per league from `config/leagues.yml` (`num_teams`).",
        "Shown in the Excel league sheets as `rnd`.",
    ),
    ColumnSpec(
        "pick_in_round",
        "Draft context (league-specific)",
        "Position within the round, 1..num_teams. Derived: "
        "`(overall_pick - 1) % num_teams + 1`.",
        "Derived per league from `config/leagues.yml` (`num_teams`).",
        "Shown in the Excel league sheets as `rnd_pick`.",
    ),
    ColumnSpec(
        "manager",
        "Draft context (league-specific)",
        "Manager on the clock for this pick under snake order: odd rounds go "
        "`managers[0]..managers[-1]`, even rounds reversed.",
        "Derived per league from `config/leagues.yml` (`managers`).",
        "Rows where the on-the-clock slot equals the league's `draft_position` "
        "are highlighted in the sheet.",
    ),
)


# --- Config model + loading + validation ---------------------------------


class LeagueConfigError(RuntimeError):
    """A league config entry is missing, blank, or internally inconsistent.

    The message is written to be shown directly to the user (no traceback).
    """


@dataclass(frozen=True)
class LeagueConfig:
    """One validated league entry from ``config/leagues.yml``."""

    league_name: str
    num_teams: int
    draft_position: int
    managers: tuple[str, ...]

    @property
    def draft_position_manager(self) -> str:
        """Name of the manager occupying the config owner's snake slot."""

        return self.managers[self.draft_position - 1]


def _parse_one_league(index: int, entry: Any, source: Path) -> LeagueConfig:
    """Validate a single raw ``leagues[]`` mapping into a :class:`LeagueConfig`.

    Every failure raises :class:`LeagueConfigError` with a message that names the
    offending league so a hand-edited YAML is easy to fix.
    """

    where = f"{source.name}: leagues[{index}]"

    if not isinstance(entry, dict):
        raise LeagueConfigError(f"{where} must be a mapping, got {type(entry).__name__}")

    required = ("league_name", "num_teams", "draft_position", "managers")
    missing = [k for k in required if k not in entry]
    if missing:
        raise LeagueConfigError(f"{where} is missing required key(s): {', '.join(missing)}")

    # league_name -------------------------------------------------------
    name = entry["league_name"]
    if not isinstance(name, str) or not name.strip():
        raise LeagueConfigError(f"{where}.league_name must be a non-blank string")
    name = name.strip()
    where = f"{source.name}: league '{name}'"  # nicer label now that we have it

    # num_teams -------------------------------------------------------
    num_teams = entry["num_teams"]
    if isinstance(num_teams, bool) or not isinstance(num_teams, int) or num_teams < 1:
        raise LeagueConfigError(f"{where}: num_teams must be a positive integer, got {num_teams!r}")

    # managers -------------------------------------------------------
    managers = entry["managers"]
    if not isinstance(managers, list):
        raise LeagueConfigError(f"{where}: managers must be a list")
    if len(managers) != num_teams:
        raise LeagueConfigError(
            f"{where}: {len(managers)} manager(s) listed but num_teams is {num_teams} -- "
            "the manager list length must equal num_teams"
        )
    clean_managers: list[str] = []
    for j, m in enumerate(managers, start=1):
        if not isinstance(m, str) or not m.strip():
            raise LeagueConfigError(f"{where}: managers[{j}] is blank -- every manager name is required")
        clean_managers.append(m.strip())

    # draft_position -------------------------------------------------------
    draft_position = entry["draft_position"]
    if isinstance(draft_position, bool) or not isinstance(draft_position, int):
        raise LeagueConfigError(f"{where}: draft_position must be an integer, got {draft_position!r}")
    if not (1 <= draft_position <= num_teams):
        raise LeagueConfigError(
            f"{where}: draft_position must be between 1 and num_teams ({num_teams}), got {draft_position}"
        )

    return LeagueConfig(
        league_name=name,
        num_teams=num_teams,
        draft_position=draft_position,
        managers=tuple(clean_managers),
    )


def load_league_configs(path: str | Path | None = None) -> list[LeagueConfig]:
    """Load + validate every league from a YAML config file.

    Parameters
    ----------
    path:
        YAML file with a top-level ``leagues:`` list. Defaults to
        :data:`DEFAULT_LEAGUE_CONFIG` (``config/leagues.yml``).

    Returns
    -------
    list[LeagueConfig]
        In file order.

    Raises
    ------
    LeagueConfigError
        On a missing file, malformed YAML, or any invalid league entry.
    """

    path = Path(path) if path is not None else DEFAULT_LEAGUE_CONFIG
    if not path.is_file():
        raise LeagueConfigError(f"league config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough of parser detail
        raise LeagueConfigError(f"{path.name}: could not parse YAML: {exc}") from exc

    if not isinstance(raw, dict) or "leagues" not in raw:
        raise LeagueConfigError(f"{path.name}: a top-level 'leagues:' list is required")
    entries = raw["leagues"]
    if not isinstance(entries, list) or not entries:
        raise LeagueConfigError(f"{path.name}: 'leagues' must be a non-empty list")

    configs = [_parse_one_league(i, entry, path) for i, entry in enumerate(entries)]

    names = [c.league_name for c in configs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise LeagueConfigError(f"{path.name}: duplicate league_name(s): {', '.join(dupes)}")

    return configs


# --- Snake-draft logic ----------------------------------------------------


def snake_pick_table(num_teams: int, num_picks: int) -> list[dict[str, int]]:
    """Enumerate a snake draft.

    Returns one dict per overall pick (``1..num_picks``) with keys:

    * ``overall_pick`` -- 1..num_picks
    * ``round`` -- ``(overall_pick - 1) // num_teams + 1``
    * ``pick_in_round`` -- 1..num_teams
    * ``slot`` -- the 1-based draft slot (config manager index + 1) on the clock,
      following the forward/reverse snake order (odd rounds forward, even
      rounds reversed).

    ``slot`` is what row highlighting compares against ``draft_position``; the
    manager *name* is looked up from it in :func:`build_league_frame`.
    """

    if num_teams < 1:
        raise ValueError("num_teams must be >= 1")

    rows: list[dict[str, int]] = []
    for overall in range(1, num_picks + 1):
        rnd = (overall - 1) // num_teams + 1
        pick_in_round = (overall - 1) % num_teams + 1
        # odd round -> forward slot order; even round -> reversed
        if rnd % 2 == 1:
            slot = pick_in_round
        else:
            slot = num_teams - pick_in_round + 1
        rows.append(
            {
                "overall_pick": overall,
                "round": rnd,
                "pick_in_round": pick_in_round,
                "slot": slot,
            }
        )
    return rows


def build_league_frame(
    checkpoint_df: pd.DataFrame, cfg: LeagueConfig
) -> tuple[pd.DataFrame, list[int]]:
    """Prefix the shared checkpoint dataframe with this league's snake columns.

    Returns
    -------
    (frame, highlight_rows)
        ``frame`` is ``checkpoint_df`` with :data:`LEAGUE_COLUMNS` prepended
        (all shared columns preserved, in order, after them).
        ``highlight_rows`` is the 0-based positional row indices where the
        config owner's ``draft_position`` slot is on the clock.
    """

    base = checkpoint_df.reset_index(drop=True)
    table = snake_pick_table(cfg.num_teams, len(base))

    lead = pd.DataFrame(
        {
            "overall_pick": [t["overall_pick"] for t in table],
            "round": [t["round"] for t in table],
            "pick_in_round": [t["pick_in_round"] for t in table],
            "manager": [cfg.managers[t["slot"] - 1] for t in table],
        }
    )
    frame = pd.concat([lead, base], axis=1)

    highlight_rows = [i for i, t in enumerate(table) if t["slot"] == cfg.draft_position]
    return frame, highlight_rows


# --- Workbook output ----------------------------------------------------


def _safe_sheet_name(name: str, used: set[str]) -> str:
    """Excel-legal, <=31 char, unique-within-workbook sheet name."""

    cleaned = "".join(c for c in name if c not in set("[]:*?/\\")).strip() or "league"
    cleaned = cleaned[:31]
    candidate = cleaned
    n = 2
    while candidate.lower() in used:
        suffix = f" ({n})"
        candidate = cleaned[: 31 - len(suffix)] + suffix
        n += 1
    used.add(candidate.lower())
    return candidate


def _autofit_compact(worksheet, frame: pd.DataFrame, headers: list[str]) -> None:
    """Size every column to its max content width (header + all values) + slim padding.

    Uses the full column, not a sample, so nothing is clipped. A small hard cap
    keeps one long free-text column from blowing out the sheet; in practice the
    league sheets have no such column.
    """

    _blank = {"", "nan", "<NA>", "None", "NaN", "NaT"}
    for i, (col, header) in enumerate(zip(frame.columns, headers)):
        # str(v) per element: Series.astype(str) leaves NA sentinels as floats
        # in recent pandas, so map explicitly and drop the blank renderings.
        rendered = [str(v) for v in frame[col].tolist()]
        longest = max([len(header)] + [len(v) for v in rendered if v not in _blank])
        worksheet.set_column(i, i, max(3, min(longest + 1, 48)))


def _league_dict_rows() -> pd.DataFrame:
    """The four league columns as data-dictionary rows (same shape as the checkpoint dict)."""

    return pd.DataFrame(
        [
            {
                "column_name": spec.name,
                "group": spec.group,
                "definition": spec.definition,
                "source": spec.source,
                "notes": spec.notes,
            }
            for spec in LEAGUE_COLUMN_SCHEMA
        ]
    )


def write_league_workbook(
    checkpoint_df: pd.DataFrame,
    leagues: Iterable[LeagueConfig],
    out_path: str | Path,
) -> Path:
    """Write one worksheet per league + a trailing ``data_dictionary`` sheet.

    Per league sheet (all of this is Excel-only presentation; the dataframe from
    :func:`build_league_frame` keeps its internal names and order):

    * left columns shown as ``manager | pick | rnd | rnd_pick | player_name |
      team | position``, then the remaining checkpoint columns in their existing
      order;
    * header row 1 styled bold, centred, white-on-blue, with autofilter;
    * freeze row 1 and columns A:G (through ``position``);
    * ``position`` cells pastel-filled by value (RB/WR/QB/TE/DST/K);
    * pale-amber fill on rows where the league's ``draft_position`` slot is on
      the clock;
    * every column sized to its max content width + slim padding.

    The ``data_dictionary`` sheet keeps its existing wrapped/readable formatting
    (no max-content autosizing) and comes last.
    """

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    leagues = list(leagues)

    # Build the dictionary once. Passing the columns validates schema/dict drift.
    data_dictionary = pd.concat(
        [build_data_dictionary(checkpoint_df.columns), _league_dict_rows()],
        ignore_index=True,
    )

    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        book = writer.book
        highlight_fmt = book.add_format({"bg_color": _HIGHLIGHT_COLOR})
        wrap_fmt = book.add_format({"text_wrap": True, "valign": "top"})
        header_fmt = book.add_format(
            {
                "bold": True,
                "align": "center",
                "valign": "vcenter",
                "bg_color": _HEADER_FILL,
                "font_color": "#FFFFFF",
            }
        )
        position_fmts = {
            pos: book.add_format({"bg_color": color})
            for pos, color in _POSITION_FILLS.items()
        }

        used_names: set[str] = set()
        for cfg in leagues:
            frame, highlight_rows = build_league_frame(checkpoint_df, cfg)
            sheet = _safe_sheet_name(cfg.league_name, used_names)

            # Excel-only: reorder the left columns, relabel three headers.
            display_cols = _LEAGUE_SHEET_LEAD_ORDER + [
                c for c in frame.columns if c not in _LEAGUE_SHEET_LEAD_ORDER
            ]
            display = frame[display_cols]
            headers = [_HEADER_DISPLAY_NAMES.get(c, c) for c in display_cols]
            n_rows, n_cols = display.shape

            # Write the body from row 1; row 0 is our styled header.
            display.to_excel(
                writer, sheet_name=sheet, index=False, header=False, startrow=1
            )
            ws = writer.sheets[sheet]
            for c, label in enumerate(headers):
                ws.write(0, c, label, header_fmt)

            # Freeze row 1 + columns through `position` inclusive (A:G).
            ws.freeze_panes(1, display_cols.index(_FREEZE_THROUGH) + 1)
            ws.autofilter(0, 0, n_rows, n_cols - 1)
            _autofit_compact(ws, display, headers)

            # Pastel fill on the `position` cells only, keyed by value.
            pos_idx = display_cols.index("position")
            for pos, fmt in position_fmts.items():
                ws.conditional_format(
                    1,
                    pos_idx,
                    n_rows,
                    pos_idx,
                    {"type": "cell", "criteria": "==", "value": f'"{pos}"', "format": fmt},
                )

            # Highlight every pick where the config owner's slot is on the clock
            # (+1 because Excel row 0 is the header).
            for r in highlight_rows:
                ws.set_row(r + 1, None, highlight_fmt)

        # --- data_dictionary sheet (last) -----------------------------
        dd_sheet = "data_dictionary"
        data_dictionary.to_excel(writer, sheet_name=dd_sheet, index=False)
        dd_ws = writer.sheets[dd_sheet]
        dd_rows, dd_cols = data_dictionary.shape
        dd_ws.freeze_panes(1, 0)
        dd_ws.autofilter(0, 0, dd_rows, dd_cols - 1)
        dd_widths = {"column_name": 24, "group": 30, "definition": 70, "source": 52, "notes": 60}
        wrapped = {"definition", "source", "notes"}
        for i, col in enumerate(data_dictionary.columns):
            dd_ws.set_column(i, i, dd_widths.get(col, 24), wrap_fmt if col in wrapped else None)

    return out_path
