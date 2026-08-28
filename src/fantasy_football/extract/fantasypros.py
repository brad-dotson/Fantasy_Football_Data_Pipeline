"""FantasyPros Public API v2 extraction helpers.

This is the first production extraction module. Its only job is to *pull raw
data* from the FantasyPros API and *cache it locally*. It deliberately does
**no** transformation / reshaping of the payload -- that belongs in a separate
transformation layer (see the project's extraction-vs-transformation
principle in ``CLAUDE.md`` / ``README.md``).

Before changing anything here, read ``docs/fantasypros_api_notes.md``.

Key facts driving this module (from the API notes + notebook exploration):

* Endpoint: ``GET /nfl/<season>/consensus-rankings``
* Params used for the v1 draft dataset: ``position=ALL``, ``type=ADP``,
  ``scoring=HALF`` (half-PPR is the league scoring format).
* Auth: an API key passed in the ``x-api-key`` request header.
* The premium daily request limit is ~500, so callers should cache the raw
  response (via :func:`save_raw_response`) and develop against the cached
  JSON instead of re-calling the API.

A second endpoint -- ``GET /nfl/<season>/projections`` (2026 preseason /
season-long projections) -- is also supported via :func:`fetch_projections`.
It follows the same "pull + cache, no transformation" contract.

A third endpoint -- ``GET /nfl/<season>/player-points`` (2025 season-long
Half-PPR actual fantasy points) -- is supported via :func:`fetch_player_points`.
It defaults to the 2025 season because it is consumed only as prior-season
context for the 2026 draft dataset, and it follows the same "pull + cache, no
transformation" contract.

The module is designed to be callable from the command line for one-off pulls:
./.venv/bin/python -c "from fantasy_football.extract.fantasypros import fetch_consensus_adp, save_raw_response; save_raw_response(fetch_consensus_adp())"
./.venv/bin/python -c "from fantasy_football.extract.fantasypros import fetch_projections, save_raw_response, PROJECTIONS_RAW_FILENAME; save_raw_response(fetch_projections(), filename=PROJECTIONS_RAW_FILENAME)"
./.venv/bin/python -c "from fantasy_football.extract.fantasypros import fetch_player_points, save_raw_response, PLAYER_POINTS_RAW_FILENAME; save_raw_response(fetch_player_points(), filename=PLAYER_POINTS_RAW_FILENAME)"

"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

__all__ = [
    "FantasyProsConfigError",
    "API_KEY_ENV_VAR",
    "DEFAULT_SEASON",
    "DEFAULT_TIMEOUT",
    "DEFAULT_RAW_DIR",
    "PROJECTIONS_RAW_FILENAME",
    "PLAYER_POINTS_SEASON",
    "PLAYER_POINTS_RAW_FILENAME",
    "fetch_consensus_adp",
    "fetch_projections",
    "fetch_player_points",
    "save_raw_response",
]


class FantasyProsConfigError(RuntimeError):
    """Raised when required FantasyPros configuration is missing/invalid.

    Currently this only covers a missing API key, but keeping a dedicated
    exception type lets callers catch configuration problems distinctly from
    network / HTTP errors (which surface as ``requests`` exceptions).
    """


# --- Configuration constants -------------------------------------------------

#: Environment variable that must hold the FantasyPros API key. The key itself
#: is never hard-coded and never logged/printed by this module.
API_KEY_ENV_VAR = "FANTASYPROS_API_KEY"

#: Base URL for the v2 API. The ``/json`` segment selects the JSON response
#: format (matches the notebook exploration in ``notebooks/``).
BASE_URL = "https://api.fantasypros.com/public/v2/json"

#: NFL season we are building the draft dataset for.
DEFAULT_SEASON = 2026

#: Request timeout in seconds as a ``(connect, read)`` tuple. A short connect
#: timeout fails fast when the host is unreachable; the longer read timeout
#: gives the API time to assemble the full (~340 player) payload.
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 30.0)

#: Repo root, derived from this file's location:
#: ``<root>/src/fantasy_football/extract/fantasypros.py`` -> ``parents[3]``.
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Default local cache directory for raw API responses (git-ignored).
DEFAULT_RAW_DIR = _REPO_ROOT / "data" / "raw"

#: Query parameters for the half-PPR consensus ADP pull.
_CONSENSUS_ADP_PARAMS = {
    "position": "ALL",
    "type": "ADP",
    "scoring": "HALF",
}

#: Query parameters for the 2026 preseason (season-long) projections pull.
#:
#: * ``week=0`` selects preseason / season-long projections (a real week number
#:   would return that week's projection instead).
#: * ``position=ALL`` returns every position (QB/RB/WR/TE/K/DST) in one payload.
#:
#: No ``scoring`` param is sent on purpose. Per
#: ``docs/fantasypros_api_notes.md`` the endpoint's *top-level* ``scoring`` was
#: observed as ``STD`` regardless of what was requested, so it is not a
#: reliable Half-PPR signal. Every player record instead carries per-format
#: point fields under ``stats`` (``points``, ``points_ppr``, ``points_half``);
#: the transformation layer reads ``stats["points_half"]`` from there.
_PROJECTIONS_PARAMS = {
    "week": 0,
    "position": "ALL",
}

#: Production raw-cache filename for the projections pull. Mirrors the inline
#: default used by :func:`save_raw_response` for the consensus pull, but the
#: projections endpoint has no ``scoring`` suffix because Half-PPR points live
#: inside each player's ``stats`` rather than being selected per request.
PROJECTIONS_RAW_FILENAME = f"fantasypros_projections_{DEFAULT_SEASON}.json"

#: NFL season pulled by :func:`fetch_player_points`. This is *not*
#: :data:`DEFAULT_SEASON` (2026): the ``player-points`` endpoint returns actual
#: scored fantasy points, so it is only meaningful for a completed season and is
#: consumed purely as prior-season context for the 2026 draft board.
PLAYER_POINTS_SEASON = 2025

#: Query parameters for the 2025 season-long Half-PPR player-points pull.
#:
#: * ``position=ALL`` returns every position in one payload.
#: * ``scoring=HALF`` selects the half-PPR point totals (the league format).
#:   Unlike the projections endpoint, ``player-points`` honours this and echoes
#:   ``scoring=HALF`` back in the response.
#: * ``start=1`` / ``end=18`` covers the full 18-week NFL regular season so the
#:   totals are true season-long numbers.
_PLAYER_POINTS_PARAMS = {
    "position": "ALL",
    "scoring": "HALF",
    "start": 1,
    "end": 18,
}

#: Production raw-cache filename for the player-points pull. Carries the
#: ``_half`` suffix because scoring *is* chosen at request time for this
#: endpoint (contrast :data:`PROJECTIONS_RAW_FILENAME`).
PLAYER_POINTS_RAW_FILENAME = (
    f"fantasypros_player_points_{PLAYER_POINTS_SEASON}_half.json"
)


def _load_dotenv_if_available() -> None:
    """Best-effort load of a local ``.env`` file.

    The project stores secrets in ``.env``. ``python-dotenv`` is a project
    dependency, but we import it lazily and ignore its absence so this module
    still works in environments where the key is exported directly.
    """

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is normally installed
        return
    load_dotenv()


def _get_api_key() -> str:
    """Return the FantasyPros API key from the environment.

    Raises :class:`FantasyProsConfigError` with an actionable message if the
    variable is unset or blank. The key value is never included in the error.
    """

    _load_dotenv_if_available()
    api_key = os.environ.get(API_KEY_ENV_VAR, "").strip()
    if not api_key:
        raise FantasyProsConfigError(
            f"Missing FantasyPros API key: set the {API_KEY_ENV_VAR!r} "
            "environment variable (e.g. in your local .env file) before "
            "calling the API."
        )
    return api_key


def fetch_consensus_adp(
    season: int = DEFAULT_SEASON,
    *,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Call the ``consensus-rankings`` endpoint and return the parsed JSON.

    Uses ``position=ALL``, ``type=ADP``, ``scoring=HALF`` -- i.e. the
    half-PPR consensus ADP board for the full player universe.

    Parameters
    ----------
    season:
        NFL season year (path segment). Defaults to :data:`DEFAULT_SEASON`.
    timeout:
        ``requests`` timeout, in seconds. Either a single float or a
        ``(connect, read)`` tuple. Defaults to :data:`DEFAULT_TIMEOUT`.

    Returns
    -------
    dict
        The parsed JSON response body exactly as returned by the API. No
        transformation is applied.

    Raises
    ------
    FantasyProsConfigError
        If the API key environment variable is not set.
    requests.HTTPError
        If the API responds with a non-2xx status code.
    requests.RequestException
        For lower-level problems (connection errors, timeouts, etc.).

    Notes
    -----
    This performs a real, rate-limited API call (~500/day premium limit).
    Prefer calling it once and caching via :func:`save_raw_response`, then
    developing against the cached JSON.
    """

    api_key = _get_api_key()

    url = f"{BASE_URL}/nfl/{season}/consensus-rankings"
    # The key travels only in this header dict; we never log `headers`.
    headers = {"x-api-key": api_key}

    response = requests.get(
        url,
        headers=headers,
        params=_CONSENSUS_ADP_PARAMS,
        timeout=timeout,
    )

    # Turn any non-2xx response into a raised HTTPError. The generated message
    # contains the URL and status code but not the request headers, so the
    # API key is not exposed.
    response.raise_for_status()

    return response.json()


def fetch_projections(
    season: int = DEFAULT_SEASON,
    *,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Call the ``projections`` endpoint and return the parsed JSON.

    Uses ``week=0`` (preseason / season-long) and ``position=ALL`` -- i.e. the
    full 2026 preseason projection set for every position in a single payload.

    Parameters
    ----------
    season:
        NFL season year (path segment). Defaults to :data:`DEFAULT_SEASON`.
    timeout:
        ``requests`` timeout, in seconds. Either a single float or a
        ``(connect, read)`` tuple. Defaults to :data:`DEFAULT_TIMEOUT`.

    Returns
    -------
    dict
        The parsed JSON response body exactly as returned by the API. No
        transformation, flattening, renaming, filtering or merging is applied.

    Raises
    ------
    FantasyProsConfigError
        If the API key environment variable is not set.
    requests.HTTPError
        If the API responds with a non-2xx status code.
    requests.RequestException
        For lower-level problems (connection errors, timeouts, etc.).

    Notes
    -----
    * The response's *top-level* ``scoring`` field is **not** authoritative for
      Half-PPR -- it has been observed as ``STD`` regardless of request
      params. Each player's ``stats`` dict carries ``points``, ``points_ppr``
      and ``points_half``; downstream code should read
      ``stats["points_half"]`` for the Half-PPR draft dataset.
    * Like :func:`fetch_consensus_adp`, this performs a real, rate-limited API
      call (~500/day premium limit). Call it once and cache via
      :func:`save_raw_response` (pass
      ``filename=PROJECTIONS_RAW_FILENAME``), then develop against the cache.
    """

    api_key = _get_api_key()

    url = f"{BASE_URL}/nfl/{season}/projections"
    # The key travels only in this header dict; we never log `headers`.
    headers = {"x-api-key": api_key}

    response = requests.get(
        url,
        headers=headers,
        params=_PROJECTIONS_PARAMS,
        timeout=timeout,
    )

    # Non-2xx -> raised HTTPError. Message carries the URL + status code but
    # not the request headers, so the API key is not exposed.
    response.raise_for_status()

    return response.json()


def fetch_player_points(
    season: int = PLAYER_POINTS_SEASON,
    *,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Call the ``player-points`` endpoint and return the parsed JSON.

    Uses ``position=ALL``, ``scoring=HALF``, ``start=1``, ``end=18`` -- i.e. the
    full-season half-PPR *actual* fantasy points for every position in a single
    payload.

    Parameters
    ----------
    season:
        NFL season year (path segment). Defaults to
        :data:`PLAYER_POINTS_SEASON` (2025), **not** :data:`DEFAULT_SEASON`.
        This endpoint returns points that were actually scored, so it is only
        meaningful for a completed season; the 2026 draft board consumes it as
        prior-season context.
    timeout:
        ``requests`` timeout, in seconds. Either a single float or a
        ``(connect, read)`` tuple. Defaults to :data:`DEFAULT_TIMEOUT`.

    Returns
    -------
    dict
        The parsed JSON response body exactly as returned by the API. No
        transformation, flattening, renaming, filtering or merging is applied --
        including the per-week values under each player's ``weeks`` key, which
        are preserved verbatim in the cache.

    Raises
    ------
    FantasyProsConfigError
        If the API key environment variable is not set.
    requests.HTTPError
        If the API responds with a non-2xx status code.
    requests.RequestException
        For lower-level problems (connection errors, timeouts, etc.).

    Notes
    -----
    * The response echoes ``season`` and ``scoring`` (observed as ``2025`` /
      ``HALF``) and carries a much broader universe (~2166 players) than the
      2026 consensus draft board. That is expected: it is an enrichment /
      lookup source joined on ``player_id``, not the primary player universe.
    * Like the other ``fetch_*`` helpers this performs a real, rate-limited API
      call (~500/day premium limit). Call it once and cache via
      :func:`save_raw_response` (pass ``filename=PLAYER_POINTS_RAW_FILENAME``),
      then develop against the cache.
    """

    api_key = _get_api_key()

    url = f"{BASE_URL}/nfl/{season}/player-points"
    # The key travels only in this header dict; we never log `headers`.
    headers = {"x-api-key": api_key}

    response = requests.get(
        url,
        headers=headers,
        params=_PLAYER_POINTS_PARAMS,
        timeout=timeout,
    )

    # Non-2xx -> raised HTTPError. Message carries the URL + status code but
    # not the request headers, so the API key is not exposed.
    response.raise_for_status()

    return response.json()


def save_raw_response(
    payload: Any,
    *,
    filename: str | None = None,
    dest_dir: str | Path = DEFAULT_RAW_DIR,
    add_timestamp: bool = False,
) -> Path:
    """Write a raw API response to ``data/raw/`` as pretty-printed JSON.

    This is intentionally dumb: it persists whatever it is given so the raw
    source data is preserved before any transformation.

    Parameters
    ----------
    payload:
        The object to serialize (typically the ``dict`` returned by
        :func:`fetch_consensus_adp`). Must be JSON-serializable.
    filename:
        Output file name. Defaults to
        ``fantasypros_consensus_adp_<season>_half.json`` using
        :data:`DEFAULT_SEASON`.
    dest_dir:
        Target directory. Created if it does not exist. Defaults to
        :data:`DEFAULT_RAW_DIR` (``<repo>/data/raw``).
    add_timestamp:
        If ``True``, insert a UTC ``YYYYMMDDTHHMMSSZ`` stamp before the file
        extension so successive pulls are kept side by side instead of
        overwriting the previous cache.

    Returns
    -------
    pathlib.Path
        The full path the file was written to.
    """

    if filename is None:
        filename = f"fantasypros_consensus_adp_{DEFAULT_SEASON}_half.json"

    if add_timestamp:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem, dot, suffix = filename.rpartition(".")
        filename = f"{stem}_{stamp}.{suffix}" if dot else f"{filename}_{stamp}"

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    out_path = dest_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return out_path
