"""SQLite-Hot-Backup der evcc-DB, Retention und interner Scheduler.

Hot-Backup ohne Stop über ``sqlite3.Connection.backup()`` (WAL-sicher; bewusst **kein**
``cp``, das bei aktiver WAL inkonsistente Kopien liefern kann). Zusätzlich wird eine
vorhandene ``evcc.yaml`` mitkopiert.

Vor dem Schreiben wird die Erreichbarkeit/Schreibbarkeit des Ziels geprüft — ein nicht
gemountetes UNAS-Share o. Ä. führt zu :class:`BackupError`, den die App in den
Notifier-Fehlerpfad leitet.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

LOGGER = logging.getLogger(__name__)

# Dateinamen-Muster: evcc_2026-06-11_0830.db
_NAME_PREFIX = "evcc_"
_NAME_SUFFIX = ".db"
_TS_FORMAT = "%Y-%m-%d_%H%M"


class BackupError(Exception):
    """Backup konnte nicht durchgeführt werden (Ziel fehlt/voll/nicht schreibbar/SQLite-Fehler)."""


def check_target_writable(dest_dir: Path) -> None:
    """Stellt sicher, dass ``dest_dir`` existiert und beschreibbar ist; sonst :class:`BackupError`.

    Schreibt testweise eine winzige Datei und entfernt sie wieder — fängt damit sowohl
    "nicht gemountet" als auch "read-only"/"kein Platz" ab.
    """
    if not dest_dir:
        raise BackupError("Kein Backup-Ziel konfiguriert.")
    dest_dir = Path(dest_dir)
    if not dest_dir.exists():
        raise BackupError(f"Backup-Ziel nicht erreichbar (nicht gemountet?): {dest_dir}")
    if not dest_dir.is_dir():
        raise BackupError(f"Backup-Ziel ist kein Verzeichnis: {dest_dir}")
    probe = dest_dir / ".evcc-writetest"
    try:
        probe.write_bytes(b"ok")
    except OSError as exc:
        raise BackupError(f"Backup-Ziel nicht beschreibbar ({dest_dir}): {exc}") from exc
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _timestamped_name(when: datetime) -> str:
    return f"{_NAME_PREFIX}{when.strftime(_TS_FORMAT)}{_NAME_SUFFIX}"


def hot_backup(db_path: Path, dest_dir: Path,
               yaml_path: Optional[Path] = None,
               when: Optional[datetime] = None) -> Path:
    """Erstellt ein konsistentes Backup der DB in ``dest_dir`` und gibt den Zielpfad zurück.

    :param when: Zeitstempel für den Dateinamen (Default: jetzt) — injizierbar für Tests.
    :raises BackupError: Ziel nicht erreichbar/schreibbar oder SQLite-Backup schlägt fehl.
    """
    db_path = Path(db_path)
    dest_dir = Path(dest_dir)
    if not db_path.exists():
        raise BackupError(f"evcc-DB nicht gefunden: {db_path}")
    check_target_writable(dest_dir)

    when = when or datetime.now()
    target = dest_dir / _timestamped_name(when)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        # WAL-sicheres Online-Backup: Quelle read-only öffnen, in eine frische Ziel-DB sichern.
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as src, \
                sqlite3.connect(str(tmp)) as dst:
            src.backup(dst)
        tmp.replace(target)
    except (sqlite3.Error, OSError) as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise BackupError(f"SQLite-Backup fehlgeschlagen: {exc}") from exc

    # evcc.yaml best-effort mitsichern (timestamp-parallel zum DB-Backup).
    if yaml_path is not None and Path(yaml_path).exists():
        try:
            shutil.copy2(yaml_path, dest_dir / f"{_NAME_PREFIX}{when.strftime(_TS_FORMAT)}.yaml")
        except OSError as exc:
            LOGGER.warning("evcc.yaml-Mitsicherung fehlgeschlagen: %s", exc)

    LOGGER.info("Backup geschrieben: %s", target)
    return target


def apply_retention(dest_dir: Path, keep: int) -> list[Path]:
    """Behält die ``keep`` neuesten DB-Backups, löscht ältere. Gibt die gelöschten Pfade zurück."""
    dest_dir = Path(dest_dir)
    if keep < 1 or not dest_dir.is_dir():
        return []
    backups = sorted(
        (p for p in dest_dir.glob(f"{_NAME_PREFIX}*{_NAME_SUFFIX}") if p.is_file()),
        key=lambda p: p.name,  # Namensschema ist lexikografisch == chronologisch sortierbar
    )
    removed: list[Path] = []
    for old in backups[:-keep] if keep < len(backups) else []:
        try:
            old.unlink()
            removed.append(old)
            # zugehörige .yaml (gleicher Zeitstempel) mitlöschen, falls vorhanden
            yaml_sibling = old.with_suffix(".yaml")
            if yaml_sibling.exists():
                yaml_sibling.unlink()
        except OSError as exc:
            LOGGER.warning("Altes Backup nicht löschbar (%s): %s", old, exc)
    if removed:
        LOGGER.info("Retention: %d alte Backups gelöscht", len(removed))
    return removed


_SCHEDULE_HOURS = {"hourly": 1, "daily": 24, "weekly": 24 * 7}


def schedule_to_seconds(schedule: str) -> float:
    """Übersetzt ``hourly|daily|weekly`` in Sekunden (Default: täglich)."""
    return _SCHEDULE_HOURS.get(schedule, 24) * 3600.0


class BackupScheduler:
    """Einfacher interner Scheduler (``threading.Timer``), der ``run`` periodisch aufruft.

    Bewusst minimal: die App läuft permanent, daher reicht ein In-Process-Timer. Ein
    dedizierter launchd-Backup-Agent ist als robustere v2-Alternative vorgesehen (Spec §9).
    """

    def __init__(self, interval_seconds: float, run: Callable[[], None]) -> None:
        self.interval_seconds = max(60.0, interval_seconds)
        self._run = run
        self._timer: Optional[threading.Timer] = None
        self._stopped = False

    def start(self) -> None:
        self._stopped = False
        self._arm()

    def stop(self) -> None:
        self._stopped = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _arm(self) -> None:
        if self._stopped:
            return
        self._timer = threading.Timer(self.interval_seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _fire(self) -> None:
        try:
            self._run()
        except Exception:  # noqa: BLE001 - Scheduler darf nie sterben
            LOGGER.exception("Geplanter Backup-Lauf abgebrochen")
        finally:
            self._arm()
