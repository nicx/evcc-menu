"""Zentrale Pfaddefinitionen für evcc-menu.

Alle persistenten Daten liegen unter ``~/Library/Application Support/evcc-menu/``
(überlebt App-Updates, im Gegensatz zum Bundle-Inneren). Das evcc-Logfile liegt
gem. macOS-Konvention separat unter ``~/Library/Logs/evcc-menu/``.

Secrets liegen NICHT hier, sondern im macOS-Keychain (siehe :mod:`src.auth.keychain`).
"""

from __future__ import annotations

from pathlib import Path

APP_DIR_NAME = "evcc-menu"

# Label des launchd-LaunchAgents, der das evcc-Binary betreibt (nicht zu verwechseln
# mit dem App-Login-Autostart-Label in :mod:`src.autostart`).
AGENT_LABEL = "io.evcc.menu.agent"


def app_support_dir() -> Path:
    """Basisverzeichnis der App in ``~/Library/Application Support`` (wird angelegt)."""
    base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def bin_dir() -> Path:
    """Verzeichnis für das evcc-Binary (wird angelegt)."""
    d = app_support_dir() / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def evcc_binary() -> Path:
    """Pfad zum installierten evcc-Binary."""
    return bin_dir() / "evcc"


def evcc_binary_previous() -> Path:
    """Pfad zum gesicherten Vorgänger-Binary (für Rollback)."""
    return bin_dir() / "evcc.previous"


def db_file() -> Path:
    """Explizit gesetzter SQLite-DB-Pfad (deterministische Backups)."""
    return app_support_dir() / "evcc.db"


def evcc_yaml() -> Path:
    """Optionaler Pfad zur ``evcc.yaml`` (falls genutzt)."""
    return app_support_dir() / "evcc.yaml"


def config_file() -> Path:
    """App-eigene Konfiguration (``config.json``)."""
    return app_support_dir() / "config.json"


# Alias: settings.py importiert ``settings_file`` analog zum iCloud-Projekt.
settings_file = config_file


def logs_dir() -> Path:
    """Verzeichnis für Logdateien unter ``~/Library/Logs/evcc-menu`` (wird angelegt)."""
    d = Path.home() / "Library" / "Logs" / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def evcc_log_file() -> Path:
    """Logfile, auf das der launchd-Agent StdOut/StdErr umleitet."""
    return logs_dir() / "evcc.log"


def app_log_file() -> Path:
    """Diagnose-Log der Menüleisten-App selbst (getrennt vom evcc-Log)."""
    return logs_dir() / "evcc-menu.log"


def agent_plist_path() -> Path:
    """Pfad des launchd-Plists für den evcc-Agenten."""
    return Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
