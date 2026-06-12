"""HTTP-Healthcheck der evcc-Instanz (localhost:7070).

Stateless-Probe (:func:`probe`) plus ein kleiner Zähler-Wrapper (:class:`HealthMonitor`),
der aufeinanderfolgende Fehlversuche gegen einen Schwellwert hält. Der Schwellwert speist
die Notifier-State-Machine (erst nach N Fehlversuchen in Folge gilt es als "Problem").
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

LOGGER = logging.getLogger(__name__)

# Zustände
RUNNING = "running"          # HTTP-Antwort erhalten -> evcc lebt
UNREACHABLE = "unreachable"  # Verbindung verweigert/Timeout -> evcc antwortet nicht
STOPPED = "stopped"          # Agent gar nicht geladen (von außen gesetzt, nicht hier ermittelt)


def probe(url: str, timeout: float = 5.0) -> str:
    """Pollt ``url``. ``running`` bei beliebiger HTTP-Antwort, sonst ``unreachable``.

    Jede HTTP-Statuszeile (auch 4xx/5xx) bedeutet "Server lebt" — evcc kann je nach Pfad
    auch Redirects/Fehler liefern. Nur Verbindungsfehler/Timeout zählen als ``unreachable``.
    """
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "evcc-menu"})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return RUNNING
    except urllib.error.HTTPError:
        return RUNNING  # HTTP-Fehlerstatus = Server antwortet trotzdem
    except (urllib.error.URLError, OSError, ValueError) as exc:
        LOGGER.debug("Healthcheck %s nicht erreichbar: %s", url, exc)
        return UNREACHABLE


class HealthMonitor:
    """Hält den letzten Zustand und zählt Fehlversuche in Folge gegen einen Schwellwert."""

    def __init__(self, url: str, failure_threshold: int = 3) -> None:
        self.url = url
        self.failure_threshold = max(1, failure_threshold)
        self._consecutive_failures = 0
        self.last_state: str = RUNNING

    def check(self, timeout: float = 5.0) -> str:
        """Führt eine Probe aus, aktualisiert Zähler/Zustand und gibt den Zustand zurück."""
        state = probe(self.url, timeout=timeout)
        if state == RUNNING:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
        self.last_state = state
        return state

    @property
    def is_problem(self) -> bool:
        """True, sobald der Fehlversuch-Schwellwert erreicht/überschritten ist."""
        return self._consecutive_failures >= self.failure_threshold

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures
