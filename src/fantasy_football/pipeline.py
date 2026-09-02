"""End-to-end runner for the fantasy-football draft pipeline.

Usage::

    python -m fantasy_football.pipeline            # use cached raw JSON
    python -m fantasy_football.pipeline --refresh  # fetch fresh API data first

This module is deliberately thin. It wires four layers together in a fixed
order and holds no business logic of its own:

    extraction  ->  transformation  ->  validation / QA  ->  Excel output

Each layer's real logic stays in its own module:

* ``fantasy_football.extract.fantasypros``            -- API fetch + raw-cache writes
* ``fantasy_football.transform.draft_checkpoint``     -- dataframe business logic
* ``...draft_checkpoint.write_checkpoint_excel``      -- Excel-specific output

Nothing here imports Jupyter, and :func:`run_pipeline` makes no CLI or
filesystem assumptions beyond a raw-cache directory and an output path (both
overridable). A future AWS / Databricks job can import and call
:func:`run_pipeline` directly instead of going through :func:`main`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from fantasy_football.extract.fantasypros import (
    DEFAULT_RAW_DIR,
    FantasyProsConfigError,
    refresh_raw_caches,
)
from fantasy_football.transform.draft_checkpoint import (
    REQUIRED_RAW_FILES,
    CheckpointSchemaError,
    build_draft_checkpoint,
    checkpoint_coverage_report,
    validate_checkpoint_schema,
    write_checkpoint_excel,
)

#: Directory for generated Excel artifacts (``<repo>/outputs``). Derived from
#: the extraction layer's raw-dir constant so repo layout has one definition.
DEFAULT_OUTPUT_DIR = DEFAULT_RAW_DIR.parent.parent / "outputs"

#: Filename stem of the default checkpoint workbook, before the run-date suffix.
DEFAULT_OUTPUT_BASENAME = "fantasy_draft_checkpoint"


def default_output_path(run_date: dt.date | None = None) -> Path:
    """Dated default path for the Excel checkpoint.

    ``<repo>/outputs/fantasy_draft_checkpoint_YYYY_MM_DD.xlsx``, where the
    date is when the pipeline runs (today, unless ``run_date`` is given).

    This is the single place the default output filename is built. It is used
    only when the caller passes no explicit output path; an explicit
    ``--output`` / ``output_path`` is always honoured exactly as given.
    """

    run_date = run_date or dt.date.today()
    return DEFAULT_OUTPUT_DIR / f"{DEFAULT_OUTPUT_BASENAME}_{run_date:%Y_%m_%d}.xlsx"


class PipelineError(RuntimeError):
    """Base class for pipeline failures that should print cleanly (no traceback)."""


class PipelineInputError(PipelineError):
    """A required input is missing -- e.g. a raw cache file in cached mode."""


class PipelineValidationError(PipelineError):
    """QA found a true structural problem -- e.g. duplicate primary keys."""


@dataclass
class PipelineResult:
    """What :func:`run_pipeline` produced (for the CLI summary or a caller)."""

    output_path: Path
    row_count: int
    column_count: int
    refreshed: list[str]          # labels of caches refreshed this run ([] if none)
    coverage: dict[str, dict]     # enrichment coverage from checkpoint_coverage_report


def run_validation(players_df) -> dict:
    """Lightweight structural QA over the consolidated dataframe.

    Reuses :func:`checkpoint_coverage_report` (no duplicated logic) and turns
    only *structural* problems into failures. Normal enrichment missingness is
    returned for reporting, never raised.

    Raises
    ------
    PipelineValidationError
        If the frame is empty, ``player_id`` is non-unique, ``player_id``
        contains nulls, or the exported columns have drifted from the
        maintained data-dictionary schema (:data:`CHECKPOINT_SCHEMA`).
    """

    report = checkpoint_coverage_report(players_df)

    problems: list[str] = []
    if report["row_count"] == 0:
        problems.append("consolidated dataframe has 0 rows")
    if not report["player_id_unique"]:
        problems.append("player_id is not unique (duplicate primary keys)")
    if report["player_id_nulls"]:
        problems.append(f"player_id has {report['player_id_nulls']} null value(s)")

    # Every exported column must have exactly one data-dictionary entry, and no
    # dictionary entry may be stale. Keeps the Excel data_dictionary tab honest.
    try:
        validate_checkpoint_schema(players_df.columns)
    except CheckpointSchemaError as exc:
        problems.append(str(exc))

    if problems:
        raise PipelineValidationError("; ".join(problems))

    return report


def _require_caches(raw_dir: Path) -> None:
    """Raise a helpful :class:`PipelineInputError` if any required cache is absent."""

    missing = [name for name in REQUIRED_RAW_FILES if not (raw_dir / name).is_file()]
    if missing:
        listed = "\n  ".join(str(raw_dir / name) for name in missing)
        raise PipelineInputError(
            "cached-data run needs these raw files, but they are missing:\n  "
            f"{listed}\n"
            "run `python -m fantasy_football.pipeline --refresh` to fetch them."
        )


def run_pipeline(
    *,
    refresh: bool = False,
    raw_dir: str | Path | None = None,
    output_path: str | Path | None = None,
) -> PipelineResult:
    """Run extract (optional) -> transform -> validate -> Excel, in that order.

    Parameters
    ----------
    refresh:
        If ``True``, fetch fresh current-season data and overwrite the raw
        caches *before* building. If the refresh fails the exception
        propagates -- there is deliberately no fallback to stale cache.
    raw_dir:
        Raw-cache directory. Defaults to the extraction layer's
        ``DEFAULT_RAW_DIR``.
    output_path:
        Excel output path. Defaults to :func:`default_output_path` (a
        date-stamped file in ``<repo>/outputs``).

    Returns
    -------
    PipelineResult
    """

    raw_dir = Path(raw_dir) if raw_dir is not None else DEFAULT_RAW_DIR
    # An explicit path is used verbatim; only the default gets a date stamp.
    output_path = Path(output_path) if output_path is not None else default_output_path()

    refreshed: list[str] = []
    if refresh:
        # The extraction layer owns *what* is refreshable and *how*.
        refreshed = [label for label, _path in refresh_raw_caches(dest_dir=raw_dir)]
    else:
        _require_caches(raw_dir)

    # The transformation layer owns all dataframe business logic.
    players_df = build_draft_checkpoint(raw_dir=raw_dir)

    # Validation / QA (reuses the transform layer's coverage report).
    report = run_validation(players_df)

    # Output: Excel-specific behaviour lives in the transform package but
    # outside the dataframe-building function.
    written_path = write_checkpoint_excel(players_df, output_path)

    return PipelineResult(
        output_path=written_path,
        row_count=int(report["row_count"]),
        column_count=int(players_df.shape[1]),
        refreshed=refreshed,
        coverage=report["coverage"],
    )


def _print_summary(result: PipelineResult) -> None:
    """Concise human-readable summary to stdout."""

    print("fantasy-football pipeline: OK")
    if result.refreshed:
        print("  raw data: refreshed from the FantasyPros API")
        for label in result.refreshed:
            print(f"    - {label}")
    else:
        print("  raw data: existing local cache")
    print(f"  players (rows): {result.row_count}")
    print(f"  columns:        {result.column_count}")
    print("  enrichment coverage:")
    for col, cov in result.coverage.items():
        print(f"    {col:<24} {cov['non_null']:>4} / {result.row_count}  ({cov['pct']}%)")
    print(f"  excel output:   {result.output_path}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code (0 = OK, 2 = handled error)."""

    parser = argparse.ArgumentParser(
        prog="python -m fantasy_football.pipeline",
        description=(
            "Run the fantasy-football draft pipeline end to end: "
            "extract -> transform -> validate -> Excel checkpoint."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "fetch fresh current-season data from the FantasyPros API and "
            "overwrite the raw caches before running; without this flag the "
            "existing cached raw JSON is used"
        ),
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help=f"directory holding the raw cache JSON (default: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Excel output path, used exactly as given (default: "
            f"{DEFAULT_OUTPUT_DIR}/{DEFAULT_OUTPUT_BASENAME}_<YYYY_MM_DD>.xlsx)"
        ),
    )
    args = parser.parse_args(argv)

    try:
        result = run_pipeline(
            refresh=args.refresh,
            raw_dir=args.raw_dir,
            output_path=args.output,
        )
    except FantasyProsConfigError as exc:
        # e.g. missing API key on --refresh
        print(f"pipeline: error: {exc}", file=sys.stderr)
        return 2
    except requests.RequestException as exc:
        print(
            f"pipeline: error: FantasyPros API request failed: {exc}",
            file=sys.stderr,
        )
        return 2
    except PipelineError as exc:
        print(f"pipeline: error: {exc}", file=sys.stderr)
        return 2

    _print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
