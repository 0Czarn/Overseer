"""Test package. Modules import shared helpers as top-level `helpers` / `savebuilder`, so this
directory must be on sys.path both for `unittest discover -s tests` (done by unittest) and for
`python -m unittest tests.test_x` run from backend/ (done here)."""

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
