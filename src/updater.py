"""evcc-Update-Logik: GitHub-Release-Check, Versionsvergleich, Asset-Wahl, Checksum.

Reine Release-/Versionslogik — die eigentlichen Datei-Operationen (Download, Extraktion,
Binary-Swap, Rollback) liegen in :mod:`src.lifecycle`. Die App verdrahtet beides plus
ein erzwungenes Backup zum Update-Ablauf.

Unauthentifiziert erlaubt die GitHub-API 60 Requests/h — für gelegentliche Checks reicht das.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

LATEST_RELEASE_URL = "https://api.github.com/repos/evcc-io/evcc/releases/latest"

# Universal-macOS-Tarball. Reales Naming (gegen die GitHub-Releases geprüft) ist
# evcc_<version>_macOS-all.tar.gz (Bindestrich) — nicht macOS_all wie in der Spec.
# Beide Trennzeichen werden akzeptiert, falls sich das Naming wieder ändert.
_ASSET_RE = re.compile(r"^evcc_.*_macOS[-_]all\.tar\.gz$")
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_version(text: Optional[str]) -> Optional[tuple[int, int, int]]:
    """Extrahiert ein ``major.minor.patch`` aus beliebigem Text (z. B. ``v0.207.1`` ⇒ (0,207,1))."""
    if not text:
        return None
    m = _VERSION_RE.search(text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_newer(latest: Optional[str], current: Optional[str]) -> bool:
    """True, wenn ``latest`` eine höhere Version als ``current`` ist.

    Lässt sich ``current`` nicht parsen (z. B. Binary fehlt), gilt ``latest`` als neuer —
    ein Update wird dann angeboten statt fälschlich unterdrückt.
    """
    lv = parse_version(latest)
    if lv is None:
        return False
    cv = parse_version(current)
    if cv is None:
        return True
    return lv > cv


def installed_version(binary_path: Path, timeout: float = 10.0) -> Optional[str]:
    """Liest die installierte evcc-Version über ``evcc -v`` (oder ``None``, wenn nicht ermittelbar)."""
    binary_path = Path(binary_path)
    if not binary_path.exists():
        return None
    try:
        res = subprocess.run([str(binary_path), "-v"], check=False,
                             capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.debug("evcc -v fehlgeschlagen: %s", exc)
        return None
    out = (res.stdout or b"").decode(errors="replace") + (res.stderr or b"").decode(errors="replace")
    v = parse_version(out)
    return ".".join(map(str, v)) if v else None


def fetch_latest_release(timeout: float = 15.0) -> dict:
    """Holt das jüngste Release als JSON-Dict von der GitHub-API. Wirft bei Netz-/HTTP-Fehler."""
    import requests  # lazy: hält die reinen Funktionen dieses Moduls dependency-frei (testbar)

    resp = requests.get(
        LATEST_RELEASE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "evcc-menu"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def release_version(release: dict) -> Optional[str]:
    """Liest die Version aus ``tag_name``/``name`` eines Release-Dicts."""
    v = parse_version(release.get("tag_name")) or parse_version(release.get("name"))
    return ".".join(map(str, v)) if v else None


def select_asset(release: dict) -> Optional[dict]:
    """Wählt das macOS-Universal-Tarball-Asset (``evcc_<version>_macOS_all.tar.gz``)."""
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if _ASSET_RE.match(name):
            return asset
    return None


def verify_sha256(file_path: Path, expected_hex: str) -> bool:
    """Vergleicht den SHA256 von ``file_path`` mit ``expected_hex`` (case-insensitive)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hex.strip().lower()
