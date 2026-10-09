"""Locations owned by the debugger itself (never game files)."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Directory for the debugger's own logs and test reports.

    Override with HOI4DBG_DATA_DIR (used by tests). Defaults to
    %LOCALAPPDATA%\\HOI4Debugger on Windows, ~/.hoi4debugger elsewhere.
    """
    override = os.environ.get("HOI4DBG_DATA_DIR")
    if override:
        base = Path(override)
    elif os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / "HOI4Debugger"
    else:
        base = Path.home() / ".hoi4debugger"
    base.mkdir(parents=True, exist_ok=True)
    return base
