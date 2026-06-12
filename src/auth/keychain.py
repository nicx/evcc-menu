"""Credential-Storage via macOS-Keychain (``keyring``), portiert aus iCloud-Sync.

Aktuell verschickt der Notifier über das lokale MailRelay (kein SMTP-Passwort nötig),
daher gibt es noch keinen Pflicht-Consumer. Das Modul ist trotzdem vorhanden, damit
künftige Secrets (z. B. authentifiziertes SMTP oder ein GitHub-Token) sauber im Keychain
statt im Klartext landen. Service-Name ist konstant, der Account-Schlüssel benennt das Secret.
"""

from __future__ import annotations

from typing import Optional

import keyring

# Einheitlicher Keychain-Service. Stabil halten — Änderungen "verlieren" gespeicherte Secrets.
KEYCHAIN_SERVICE = "evcc-menu"


def set_secret(account: str, value: str) -> None:
    """Speichert ein Secret unter dem gegebenen Account-Schlüssel im Keychain."""
    keyring.set_password(KEYCHAIN_SERVICE, account, value)


def get_secret(account: str) -> Optional[str]:
    """Liest ein Secret aus dem Keychain (oder ``None``).

    Lesezugriffe sind abgesichert: Schlägt der Keychain-Zugriff fehl (z. B. wegen einer
    ACL für eine frühere App-Signatur), liefert die Funktion ``None`` statt zu werfen —
    so kippt ein Keychain-Problem nicht den Betrieb.
    """
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, account)
    except keyring.errors.KeyringError:
        return None


def delete_secret(account: str) -> None:
    """Entfernt ein Secret aus dem Keychain (idempotent)."""
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, account)
    except keyring.errors.PasswordDeleteError:
        # Kein Eintrag vorhanden -> nichts zu tun.
        pass
