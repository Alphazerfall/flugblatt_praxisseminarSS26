"""Central, easy-to-tune knobs for the flyer splitter.

Nothing else in this codebase should hardcode a render DPI — import from
here instead.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"

# --- Rendering --------------------------------------------------------------
THUMBNAIL_DPI = 110  # overridable per-request via ?dpi= (the frontend uses this
# for full-size cards and its own smaller PREVIEW_DPI constant for the overview panel)
