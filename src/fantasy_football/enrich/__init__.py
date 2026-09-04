"""Curated / manual enrichment inputs (``data/manual/``).

This package is deliberately separate from :mod:`fantasy_football.extract`
(FantasyPros API ingestion) and from the shared FantasyPros transform. It turns
the human/AI-curated CSVs under ``data/manual/`` into small, replaceable
enrichment frames that join onto the shared checkpoint board by exact
``player_name``.
"""

from fantasy_football.enrich.manual import (
    DEFAULT_MANUAL_DIR,
    DEFAULT_SEASON,
    ManualEnrichmentError,
    TIER_SOURCE_COLUMNS,
    apply_manual_enrichment,
    build_tier_enrichment,
    load_espn_draft_order,
    load_positional_tiers,
)

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
