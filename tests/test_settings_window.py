"""Tests für die reine Settings-Validierung (build_settings), mock-frei, ohne AppKit.

Standalone ausführen::

    .venv/bin/python tests/test_settings_window.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import Settings  # noqa: E402
from src.settings_window import build_settings  # noqa: E402


def _full_raw(**overrides) -> dict:
    """Ein vollständiges, gültiges Roh-Dict; einzelne Felder per kwargs überschreibbar."""
    raw = {
        "backup.target_path": "/Volumes/x",
        "backup.schedule": "daily",
        "backup.retention": "14",
        "health.url": "http://localhost:7070",
        "health.interval_seconds": "30",
        "health.failure_threshold": "3",
        "updates.check_on_launch": True,
        "updates.check_interval_hours": "24",
        "updates.verify_checksum": True,
        "updates.notify_email": True,
        "notifications.enabled": False,
        "notifications.smtp_host": "127.0.0.1",
        "notifications.smtp_port": "2525",
        "notifications.sender": "",
        "notifications.recipient": "",
        "logging.level": "info",
        "logging.max_size_mb": "20",
    }
    raw.update({k.replace("__", "."): v for k, v in overrides.items()})
    return raw


class BuildSettingsHappyPath(unittest.TestCase):
    def test_full_valid_input_applies(self):
        s, errs = build_settings(Settings(), _full_raw(
            backup__retention="7", health__interval_seconds="45",
            notifications__enabled=True, notifications__recipient=" me@example.com ",
            logging__level="debug", backup__schedule="weekly"))
        self.assertEqual(errs, [])
        self.assertIsNotNone(s)
        self.assertEqual(s.backup.retention, 7)
        self.assertEqual(s.backup.schedule, "weekly")
        self.assertEqual(s.health.interval_seconds, 45)
        self.assertTrue(s.notifications.enabled)
        self.assertEqual(s.notifications.recipient, "me@example.com")  # getrimmt
        self.assertEqual(s.logging.level, "debug")

    def test_does_not_mutate_base(self):
        base = Settings()
        base.backup.retention = 14
        s, errs = build_settings(base, _full_raw(backup__retention="99"))
        self.assertEqual(errs, [])
        self.assertEqual(base.backup.retention, 14)  # Original unverändert
        self.assertEqual(s.backup.retention, 99)

    def test_internal_field_preserved(self):
        base = Settings()
        base.updates.last_notified_version = "0.207.1"
        s, errs = build_settings(base, _full_raw())
        self.assertEqual(errs, [])
        self.assertEqual(s.updates.last_notified_version, "0.207.1")


class BuildSettingsClamps(unittest.TestCase):
    def test_interval_floor_5(self):
        s, _ = build_settings(Settings(), _full_raw(health__interval_seconds="1"))
        self.assertEqual(s.health.interval_seconds, 5)

    def test_retention_floor_1(self):
        s, _ = build_settings(Settings(), _full_raw(backup__retention="0"))
        self.assertEqual(s.backup.retention, 1)

    def test_failure_threshold_floor_1(self):
        s, _ = build_settings(Settings(), _full_raw(health__failure_threshold="0"))
        self.assertEqual(s.health.failure_threshold, 1)

    def test_check_interval_floor_0(self):
        s, _ = build_settings(Settings(), _full_raw(updates__check_interval_hours="-5"))
        self.assertEqual(s.updates.check_interval_hours, 0)

    def test_max_size_floor_1(self):
        s, _ = build_settings(Settings(), _full_raw(logging__max_size_mb="0"))
        self.assertEqual(s.logging.max_size_mb, 1)


class BuildSettingsErrors(unittest.TestCase):
    def test_non_integer_reports_error(self):
        s, errs = build_settings(Settings(), _full_raw(backup__retention="abc"))
        self.assertIsNone(s)
        self.assertTrue(any("Backups behalten" in e for e in errs))

    def test_port_out_of_range(self):
        s, errs = build_settings(Settings(), _full_raw(notifications__smtp_port="70000"))
        self.assertIsNone(s)
        self.assertTrue(any("Relay-Port" in e for e in errs))

    def test_port_in_range_ok(self):
        s, errs = build_settings(Settings(), _full_raw(notifications__smtp_port="587"))
        self.assertEqual(errs, [])
        self.assertEqual(s.notifications.smtp_port, 587)

    def test_invalid_schedule(self):
        s, errs = build_settings(Settings(), _full_raw(backup__schedule="monthly"))
        self.assertIsNone(s)
        self.assertTrue(any("Zeitplan" in e for e in errs))

    def test_invalid_level(self):
        s, errs = build_settings(Settings(), _full_raw(logging__level="loud"))
        self.assertIsNone(s)
        self.assertTrue(any("Log-Level" in e for e in errs))

    def test_multiple_errors_collected(self):
        s, errs = build_settings(Settings(), _full_raw(
            backup__retention="x", logging__max_size_mb="y"))
        self.assertIsNone(s)
        self.assertGreaterEqual(len(errs), 2)


class BuildSettingsPartialRaw(unittest.TestCase):
    def test_missing_keys_keep_base_values(self):
        base = Settings()
        base.health.url = "http://example:9000"
        s, errs = build_settings(base, {"backup.retention": "5"})
        self.assertEqual(errs, [])
        self.assertEqual(s.backup.retention, 5)
        self.assertEqual(s.health.url, "http://example:9000")  # nicht im raw → unverändert


if __name__ == "__main__":
    unittest.main(verbosity=2)
