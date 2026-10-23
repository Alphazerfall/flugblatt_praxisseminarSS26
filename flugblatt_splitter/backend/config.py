"""Central, easy-to-tune knobs for the flyer splitter.

Nothing else in this codebase should hardcode a render DPI — import from
here instead.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
ORGANIZATIONS_PATH = REPO_ROOT / "docs" / "korpus" / "findmittel" / "organizations.draft.json"
# Prüfliste verdächtiger Segmentgrenzen aus pipelines/01_pdf/check_boundaries.py
BOUNDARIES_PATH = REPO_ROOT / "docs" / "korpus" / "segmentgrenzen.tsv"

# --- Rendering --------------------------------------------------------------
THUMBNAIL_DPI = 110  # overridable per-request via ?dpi= (the frontend uses this
# for full-size cards and its own smaller PREVIEW_DPI constant for the overview panel)
