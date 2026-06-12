"""Tests für SQLite-Hot-Backup und Retention (mock-frei, nur Temp-Dateien).

Standalone ausführen::

    .venv/bin/python tests/test_backup.py
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import backup  # noqa: E402


def _make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (v) VALUES (?)", [("a",), ("b",), ("c",)])
    con.commit()
    con.close()


class HotBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="evcc_bk_"))
        self.db = self.tmp / "evcc.db"
        self.dest = self.tmp / "dest"
        self.dest.mkdir()
        _make_db(self.db)

    def test_hot_backup_creates_consistent_copy(self):
        when = datetime(2026, 6, 11, 8, 30)
        target = backup.hot_backup(self.db, self.dest, when=when)
        self.assertTrue(target.exists())
        self.assertEqual(target.name, "evcc_2026-06-11_0830.db")
        # Backup muss die Daten enthalten.
        con = sqlite3.connect(str(target))
        rows = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        con.close()
        self.assertEqual(rows, 3)

    def test_missing_db_raises(self):
        with self.assertRaises(backup.BackupError):
            backup.hot_backup(self.tmp / "nope.db", self.dest)

    def test_unwritable_target_raises(self):
        with self.assertRaises(backup.BackupError):
            backup.hot_backup(self.db, self.tmp / "does-not-exist")

    def test_yaml_is_copied_alongside(self):
        yaml = self.tmp / "evcc.yaml"
        yaml.write_text("site:\n  title: test\n")
        when = datetime(2026, 6, 11, 9, 0)
        backup.hot_backup(self.db, self.dest, yaml_path=yaml, when=when)
        self.assertTrue((self.dest / "evcc_2026-06-11_0900.yaml").exists())


class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.dest = Path(tempfile.mkdtemp(prefix="evcc_ret_"))

    def _seed(self, n):
        names = []
        for i in range(n):
            name = f"evcc_2026-06-{i + 1:02d}_0000.db"
            (self.dest / name).write_bytes(b"x")
            names.append(name)
        return names

    def test_keeps_newest_n_and_deletes_rest(self):
        self._seed(20)
        removed = backup.apply_retention(self.dest, keep=14)
        self.assertEqual(len(removed), 6)
        remaining = sorted(p.name for p in self.dest.glob("evcc_*.db"))
        self.assertEqual(len(remaining), 14)
        # Die ältesten 6 (Tag 01..06) müssen weg sein.
        self.assertNotIn("evcc_2026-06-01_0000.db", remaining)
        self.assertIn("evcc_2026-06-20_0000.db", remaining)

    def test_noop_when_under_limit(self):
        self._seed(5)
        self.assertEqual(backup.apply_retention(self.dest, keep=14), [])

    def test_deletes_matching_yaml_sibling(self):
        (self.dest / "evcc_2026-06-01_0000.db").write_bytes(b"x")
        (self.dest / "evcc_2026-06-01_0000.yaml").write_bytes(b"y")
        (self.dest / "evcc_2026-06-02_0000.db").write_bytes(b"x")
        backup.apply_retention(self.dest, keep=1)
        self.assertFalse((self.dest / "evcc_2026-06-01_0000.yaml").exists())


class ScheduleTest(unittest.TestCase):
    def test_schedule_to_seconds(self):
        self.assertEqual(backup.schedule_to_seconds("hourly"), 3600.0)
        self.assertEqual(backup.schedule_to_seconds("daily"), 86400.0)
        self.assertEqual(backup.schedule_to_seconds("weekly"), 604800.0)
        self.assertEqual(backup.schedule_to_seconds("unknown"), 86400.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
