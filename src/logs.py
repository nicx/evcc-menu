"""Logfile-Handling: Tail, Console.app öffnen, App-seitige Rotation.

Der launchd-Agent leitet StdOut/StdErr auf das feste evcc-Logfile um (siehe
:func:`src.lifecycle.write_agent_plist`). launchd rotiert nicht — daher rotiert die App
größenbasiert selbst.
"""

from __future__ import annotations

import logging
import subprocess
from collections import deque
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def tail(path: Path, lines: int = 50) -> str:
    """Gibt die letzten ``lines`` Zeilen einer Datei zurück (leer, wenn nicht vorhanden)."""
    path = Path(path)
    if not path.exists():
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return "".join(deque(fh, maxlen=lines))
    except OSError as exc:
        LOGGER.warning("Logfile nicht lesbar (%s): %s", path, exc)
        return ""


def open_in_console(path: Path) -> None:
    """Öffnet das Logfile in Console.app (natives Live-Tailing/Suche/Filter)."""
    path = Path(path)
    try:
        if path.exists():
            subprocess.run(["open", "-a", "Console", str(path)], check=False, timeout=10)
        else:
            # Datei noch nicht da -> übergeordneten Ordner zeigen.
            subprocess.run(["open", str(path.parent)], check=False, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.warning("Console.app konnte nicht geöffnet werden: %s", exc)


def rotate_if_needed(path: Path, max_size_mb: int, keep: int = 3) -> bool:
    """Rotiert das Logfile, wenn es ``max_size_mb`` überschreitet. True bei erfolgter Rotation.

    Verschiebt ``evcc.log`` → ``evcc.log.1`` → … → ``evcc.log.<keep>`` (ältestes fällt weg).
    Da launchd weiter in den ursprünglichen Pfad schreibt, sollte nach der Rotation der
    Agent neu gestartet werden (öffnet die Datei neu); das übernimmt die App.
    """
    path = Path(path)
    if max_size_mb <= 0 or not path.exists():
        return False
    try:
        if path.stat().st_size < max_size_mb * 1024 * 1024:
            return False
    except OSError:
        return False

    try:
        oldest = path.with_suffix(path.suffix + f".{keep}")
        if oldest.exists():
            oldest.unlink()
        for i in range(keep - 1, 0, -1):
            src = path.with_suffix(path.suffix + f".{i}")
            if src.exists():
                src.rename(path.with_suffix(path.suffix + f".{i + 1}"))
        path.rename(path.with_suffix(path.suffix + ".1"))
        LOGGER.info("Logfile rotiert: %s", path)
        return True
    except OSError as exc:
        LOGGER.warning("Logrotation fehlgeschlagen (%s): %s", path, exc)
        return False
