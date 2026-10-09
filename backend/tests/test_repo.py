"""Repository consistency: tests runnable one by one, no references to missing modules."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PACKAGE = BACKEND / "hoi4dbg"


class RepoTests(unittest.TestCase):
    def test_each_test_module_imports_standalone(self):
        """Regression: `python -m unittest tests.test_live` failed with `No module named 'helpers'`."""
        modules = sorted(p.stem for p in (BACKEND / "tests").glob("test_*.py"))
        code = "import importlib\nfor m in %r:\n    importlib.import_module('tests.' + m)" % modules
        res = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_referenced_python_files_exist(self):
        """Regression: memory.py pointed to a non-existent `livecal.py`."""
        missing = []
        for src in PACKAGE.rglob("*.py"):
            for ref in re.findall(r"\b([\w/]+\.py)\b", src.read_text(encoding="utf-8")):
                if not any((base / ref).exists() for base in (BACKEND, src.parent)):
                    missing.append(f"{src.relative_to(BACKEND)} -> {ref}")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
