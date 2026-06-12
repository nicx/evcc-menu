"""App-Settings als JSON in App Support persistiert (Schema gem. Spec §7).

Verschachtelte Abschnitte (backup/health/updates/notifications/logging) als Dataclasses.
Geladen wird tolerant: unbekannte Felder werden ignoriert, fehlende Felder/Abschnitte
fallen auf Defaults zurück — so brechen alte ``config.json`` nach einem Schema-Zuwachs nicht.

Secrets (SMTP-Passwort etc.) liegen NICHT hier. Der Notifier nutzt das lokale MailRelay
ohne Auth; falls künftig authentifiziertes SMTP nötig wird, gehört das Passwort in den
Keychain (siehe :mod:`src.auth.keychain`).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from ..paths import settings_file


@dataclass
class BackupSettings:
    """:param target_path: Backup-Ziel (z. B. UNAS-Pro-Share); leer = nicht gesetzt.
    :param schedule: ``daily`` | ``weekly`` | ``hourly``.
    :param retention: Anzahl zu behaltender Backups; ältere werden gelöscht.
    """

    target_path: str = ""
    schedule: str = "daily"
    retention: int = 14


@dataclass
class HealthSettings:
    """:param url: evcc-Web-UI/Healthcheck-Endpoint.
    :param interval_seconds: Poll-Intervall.
    :param failure_threshold: Fehlversuche in Folge bis "Problem" (Notifier-Trigger).
    """

    url: str = "http://localhost:7070"
    interval_seconds: int = 30
    failure_threshold: int = 3


@dataclass
class UpdateSettings:
    """:param check_on_launch: beim Start auf neue evcc-Version prüfen.
    :param check_interval_hours: periodischer Update-Check; 0 = nur beim Start/manuell.
    :param verify_checksum: SHA256 des Release-Assets verifizieren.
    :param notify_email: bei verfügbarem Update eine E-Mail schicken (nutzt die
        ``notifications``-Mailkonfiguration).
    :param last_notified_version: zuletzt per Mail gemeldete Version — verhindert, dass
        bei jedem Check/Neustart erneut für dieselbe Version gemailt wird.
    """

    check_on_launch: bool = True
    check_interval_hours: int = 24
    verify_checksum: bool = True
    notify_email: bool = True
    last_notified_version: str = ""


@dataclass
class NotificationSettings:
    """Fehler-E-Mail über lokales MailRelay (kein Auth/TLS hier).

    :param enabled: Mailversand aktiv.
    :param smtp_host/smtp_port: lokales Relay (Default MailRelay-Projekt 127.0.0.1:2525).
    :param sender: Absender; leer ⇒ es wird ``recipient`` genutzt.
    :param recipient: Empfänger der Fehler-/Recovery-Mails.
    """

    enabled: bool = False
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 2525
    sender: str = ""
    recipient: str = ""


@dataclass
class LoggingSettings:
    """:param level: evcc-Loglevel (fatal|error|warn|info|debug|trace).
    :param max_size_mb: Rotationsgrenze des evcc-Logfiles (App-seitige Rotation).
    """

    level: str = "info"
    max_size_mb: int = 20


@dataclass
class Settings:
    """Wurzel-Settings; jeder Abschnitt eine eigene Dataclass."""

    backup: BackupSettings = field(default_factory=BackupSettings)
    health: HealthSettings = field(default_factory=HealthSettings)
    updates: UpdateSettings = field(default_factory=UpdateSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)


def _section(cls, raw: object):
    """Baut eine Abschnitts-Dataclass tolerant aus einem Roh-Dict (unbekannte Keys ignoriert)."""
    if not isinstance(raw, dict):
        return cls()
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in known})


def load_settings() -> Settings:
    """Lädt die Settings; bei fehlender/kaputter Datei werden Defaults zurückgegeben."""
    path = settings_file()
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    return Settings(
        backup=_section(BackupSettings, raw.get("backup")),
        health=_section(HealthSettings, raw.get("health")),
        updates=_section(UpdateSettings, raw.get("updates")),
        notifications=_section(NotificationSettings, raw.get("notifications")),
        logging=_section(LoggingSettings, raw.get("logging")),
    )


def save_settings(settings: Settings) -> None:
    """Schreibt die Settings atomar-genug (write + replace) als JSON."""
    path = settings_file()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    tmp.replace(path)
