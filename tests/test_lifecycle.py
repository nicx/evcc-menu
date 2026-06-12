"""Tests für sicherheitsrelevante Helfer in lifecycle (ohne Netz/launchd).

Standalone ausführen::

    .venv/bin/python tests/test_lifecycle.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import lifecycle  # noqa: E402


class DownloadGuardTest(unittest.TestCase):
    def test_rejects_non_https(self):
        dest = Path(tempfile.mkdtemp(prefix="evcc_dl_")) / "x"
        for bad in ("http://example.com/evcc.tar.gz", "file:///etc/passwd", "ftp://h/x"):
            with self.assertRaises(ValueError):
                lifecycle.download_file(bad, dest)
        self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
