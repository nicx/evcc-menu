"""Tests für die Versions-/Release-Logik des Updaters (ohne Netz).

Standalone ausführen::

    .venv/bin/python tests/test_updater.py
"""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import updater  # noqa: E402


class VersionParseTest(unittest.TestCase):
    def test_parse_variants(self):
        self.assertEqual(updater.parse_version("v0.207.1"), (0, 207, 1))
        self.assertEqual(updater.parse_version("0.207.1"), (0, 207, 1))
        self.assertEqual(updater.parse_version("evcc version 1.2.3 (abc)"), (1, 2, 3))
        self.assertIsNone(updater.parse_version("kaputt"))
        self.assertIsNone(updater.parse_version(None))

    def test_is_newer(self):
        self.assertTrue(updater.is_newer("0.207.1", "0.207.0"))
        self.assertTrue(updater.is_newer("0.208.0", "0.207.9"))
        self.assertFalse(updater.is_newer("0.207.0", "0.207.0"))
        self.assertFalse(updater.is_newer("0.207.0", "0.207.1"))
        # Unbekannte installierte Version -> Update anbieten.
        self.assertTrue(updater.is_newer("0.207.0", None))
        # Unbekannte Latest-Version -> kein Update.
        self.assertFalse(updater.is_newer(None, "0.207.0"))


class AssetSelectTest(unittest.TestCase):
    def test_selects_macos_universal_tarball(self):
        # Reales Naming verwendet einen Bindestrich (macOS-all); Unterstrich-Variante
        # wird ebenfalls akzeptiert (siehe _ASSET_RE).
        release = {"assets": [
            {"name": "evcc_0.309.0_linux-amd64.tar.gz", "browser_download_url": "x"},
            {"name": "evcc_0.309.0_macOS-all.tar.gz", "browser_download_url": "y"},
            {"name": "evcc_0.309.0_windows-amd64.zip", "browser_download_url": "w"},
            {"name": "checksums.txt", "browser_download_url": "z"},
        ]}
        asset = updater.select_asset(release)
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], "evcc_0.309.0_macOS-all.tar.gz")

    def test_accepts_underscore_variant(self):
        release = {"assets": [{"name": "evcc_0.207.1_macOS_all.tar.gz", "browser_download_url": "y"}]}
        self.assertIsNotNone(updater.select_asset(release))

    def test_returns_none_when_no_match(self):
        self.assertIsNone(updater.select_asset({"assets": [{"name": "x.zip"}]}))

    def test_release_version(self):
        self.assertEqual(updater.release_version({"tag_name": "0.207.1"}), "0.207.1")
        self.assertEqual(updater.release_version({"name": "Release v0.208.0"}), "0.208.0")


class ChecksumTest(unittest.TestCase):
    def test_verify_sha256(self):
        tmp = Path(tempfile.mkdtemp(prefix="evcc_sum_")) / "f.bin"
        data = b"hello evcc"
        tmp.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.assertTrue(updater.verify_sha256(tmp, digest))
        self.assertTrue(updater.verify_sha256(tmp, digest.upper()))  # case-insensitive
        self.assertFalse(updater.verify_sha256(tmp, "0" * 64))


if __name__ == "__main__":
    unittest.main(verbosity=2)
