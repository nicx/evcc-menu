"""Tests für die Notifier-State-Machine (Debounce: Mail nur bei Zustandswechsel).

Standalone ausführen::

    .venv/bin/python tests/test_notifier_state.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import NotificationSettings  # noqa: E402
from src.notifier_state import NotifierState  # noqa: E402


class FakeMailer:
    """Sammelt Sendeaufrufe; konfigurierbar, wie oft das Senden fehlschlägt."""

    def __init__(self, fail_times=0):
        self.calls = []
        self._fail_times = fail_times

    def __call__(self, host, port, sender, recipient, subject, body):
        self.calls.append({"subject": subject, "body": body, "recipient": recipient})
        if self._fail_times > 0:
            self._fail_times -= 1
            return False
        return True


def _settings(enabled=True, recipient="ops@example.com"):
    return NotificationSettings(enabled=enabled, recipient=recipient,
                                smtp_host="127.0.0.1", smtp_port=2525)


def _make(mailer, settings):
    return NotifierState(
        settings_provider=lambda: settings,
        mailer=mailer,
        desktop_notify=None,      # keine echte macOS-Notification im Test
        sleep=lambda _s: None,    # kein echtes Warten beim Retry
    )


class DebounceTest(unittest.TestCase):
    def test_problem_sends_once_recovery_sends_once(self):
        mailer = FakeMailer()
        n = _make(mailer, _settings())

        n.problem("evcc_unreachable", "3 Polls fehlgeschlagen")
        n.problem("evcc_unreachable", "immer noch weg")  # Debounce -> keine zweite Mail
        n.problem("evcc_unreachable")                     # weiterhin unterdrückt
        self.assertEqual(len(mailer.calls), 1)
        self.assertIn("nicht erreichbar", mailer.calls[0]["subject"])

        n.healthy("evcc_unreachable")                     # Recovery -> genau eine Mail
        n.healthy("evcc_unreachable")                     # schon gesund -> nichts
        self.assertEqual(len(mailer.calls), 2)
        self.assertIn("wieder erreichbar", mailer.calls[1]["subject"])

    def test_healthy_without_prior_problem_is_silent(self):
        mailer = FakeMailer()
        n = _make(mailer, _settings())
        n.healthy("backup_failed")
        self.assertEqual(mailer.calls, [])

    def test_conditions_are_independent(self):
        mailer = FakeMailer()
        n = _make(mailer, _settings())
        n.problem("evcc_unreachable")
        n.problem("backup_failed")
        self.assertEqual(len(mailer.calls), 2)
        self.assertTrue(n.is_problem("evcc_unreachable"))
        self.assertTrue(n.is_problem("backup_failed"))

    def test_unknown_condition_ignored(self):
        mailer = FakeMailer()
        n = _make(mailer, _settings())
        n.problem("does_not_exist")
        self.assertEqual(mailer.calls, [])

    def test_disabled_or_no_recipient_sends_nothing(self):
        mailer = FakeMailer()
        n = _make(mailer, _settings(enabled=False))
        n.problem("evcc_unreachable")
        self.assertEqual(mailer.calls, [])

        mailer2 = FakeMailer()
        n2 = _make(mailer2, _settings(recipient=""))
        n2.problem("evcc_unreachable")
        self.assertEqual(mailer2.calls, [])

    def test_send_failure_retries_then_state_still_advances(self):
        # Erste zwei Sendeversuche scheitern, der dritte klappt -> 3 Aufrufe, eine logische Mail.
        mailer = FakeMailer(fail_times=2)
        n = _make(mailer, _settings())
        n.problem("evcc_unreachable")
        self.assertEqual(len(mailer.calls), 3)
        # Trotz Retrys gilt die Bedingung als gemeldet (kein erneutes Feuern bei nächstem problem()).
        n.problem("evcc_unreachable")
        self.assertEqual(len(mailer.calls), 3)


class NotifyEventTest(unittest.TestCase):
    def test_event_mails_when_enabled_and_returns_true(self):
        mailer = FakeMailer()
        n = _make(mailer, _settings())
        sent = n.notify_event("Update verfügbar: 0.309.0", "Details")
        self.assertTrue(sent)
        self.assertEqual(len(mailer.calls), 1)
        self.assertIn("Update verfügbar", mailer.calls[0]["subject"])

    def test_event_is_stateless_mails_every_call(self):
        # Anders als problem(): kein Debounce -> jeder Aufruf mailt (Dedup ist Sache des Aufrufers).
        mailer = FakeMailer()
        n = _make(mailer, _settings())
        n.notify_event("Update verfügbar: 0.309.0")
        n.notify_event("Update verfügbar: 0.309.0")
        self.assertEqual(len(mailer.calls), 2)

    def test_event_returns_false_when_disabled(self):
        mailer = FakeMailer()
        n = _make(mailer, _settings(enabled=False))
        self.assertFalse(n.notify_event("Update verfügbar: 0.309.0"))
        self.assertEqual(mailer.calls, [])

    def test_event_returns_false_when_all_sends_fail(self):
        mailer = FakeMailer(fail_times=99)
        n = _make(mailer, _settings())
        self.assertFalse(n.notify_event("Update verfügbar: 0.309.0"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
