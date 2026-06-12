# evcc Menübar-App für macOS — Handoff-Spezifikation

**Ziel:** Eine native macOS-Menübar-App, die eine manuell installierte evcc-Instanz vollständig terminalfrei verwaltet: Installation, Start/Stop/Restart, Updates mit Rollback, automatische Backups, Log-Einsicht und E-Mail-Benachrichtigung bei Problemen.

**Stack:** Python · rumps · py2app · launchd · SQLite · smtplib — analog zum bestehenden iCloud-Sync-Projekt. Notifier- und Config-/Keychain-Bausteine von dort wiederverwenden.

---

## 1. Architektur-Entscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| evcc-Bezug | Manuelles Universal-Binary (`evcc_<version>_macOS_all.tar.gz`), kein Homebrew | Volle Kontrolle über Updates, terminalfrei; App kann Binary selbst laden |
| evcc-Prozess | launchd **LaunchAgent** (nicht Kind-Prozess der App) | Läuft weiter bei App-Quit/-Crash; Autostart bei Login; genau das, was `brew services` intern macht |
| Menübar-App | Reines Steuer-/Dashboard-Frontend, kontrolliert den Agent via `launchctl` | Trennung von Laufzeit (Agent) und UI |
| Backup-Scheduler | Interner Scheduler in der App (App läuft permanent) | Einfach; separater launchd-Backup-Agent als optionale v2-Alternative |
| Secrets | macOS **Keychain** (`keyring` o. `security`-CLI) | Keine Klartext-Credentials in der Config |
| DB-Pfad | **Explizit** setzen, nicht auf Default verlassen | Deterministische Backups |
| Code-Signing | Ad-hoc (Privatgebrauch), Gatekeeper-Hinweis einmal bestätigen | Notarisierung für v1 unnötig |

---

## 2. Projektstruktur (Vorschlag)

```
evcc-menu/
├── evccmenu/
│   ├── __init__.py
│   ├── app.py              # rumps-App, Menüaufbau, Event-Dispatch
│   ├── lifecycle.py        # Binary-Download/-Install, launchd plist, launchctl-Steuerung
│   ├── health.py           # HTTP-Healthcheck localhost:7070
│   ├── backup.py           # SQLite-Hot-Backup, Retention, Scheduler
│   ├── updater.py          # GitHub-Release-Check, Download, Checksum, Swap, Rollback
│   ├── logs.py             # Logfile-Handling, Rotation, Console.app-Öffnen
│   ├── notifier.py         # SMTP + State-Machine-Debounce  (aus iCloud-Projekt portieren)
│   ├── config.py           # JSON-Config + Keychain + Ordnerauswahl  (aus iCloud-Projekt portieren)
│   └── paths.py            # zentrale Pfaddefinitionen
├── resources/
│   └── icon_*.png          # Menübar-Icons (Status-Varianten)
├── setup.py                # py2app
└── README.md
```

**Pfade (Vorschlag):**
- Binary: `~/Library/Application Support/evcc-menu/bin/evcc`
- Vorgängerbinary (Rollback): `~/Library/Application Support/evcc-menu/bin/evcc.previous`
- DB: `~/Library/Application Support/evcc-menu/evcc.db`  *(explizit gesetzt)*
- evcc.yaml (optional): `~/Library/Application Support/evcc-menu/evcc.yaml`
- Logfile: `~/Library/Logs/evcc-menu/evcc.log`
- App-Config: `~/Library/Application Support/evcc-menu/config.json`
- LaunchAgent: `~/Library/LaunchAgents/io.evcc.menu.agent.plist`

---

## 3. Komponenten

### 3.1 Lifecycle (`lifecycle.py`)
- **Install/Download:** Binary aus GitHub-Release laden, entpacken, an Zielpfad legen, `chmod +x`.
  - **Fallstrick Quarantäne:** Heruntergeladene Datei trägt `com.apple.quarantine` → vor erster Ausführung `xattr -d com.apple.quarantine <binary>` (oder `xattr -c`). Sonst blockt Gatekeeper.
- **launchd-Plist erzeugen** (siehe §5), nach `~/Library/LaunchAgents` schreiben.
- **Steuerung via launchctl** (moderne API bevorzugen):
  - Laden:   `launchctl bootstrap gui/$(id -u) <plist>`
  - Entladen: `launchctl bootout gui/$(id -u)/io.evcc.menu.agent`
  - Restart:  `launchctl kickstart -k gui/$(id -u)/io.evcc.menu.agent`
  - *(Legacy `load -w` / `unload` als Fallback dokumentieren.)*
- **DB-/Config-Pfad:** evcc so starten, dass DB-Pfad fest vorgegeben ist. Exakte Flag- bzw. evcc.yaml-Syntax (`database.dsn` o. ä.) gegen `evcc --help` / aktuelle Doku **verifizieren**, bevor implementiert wird.

### 3.2 Health (`health.py`)
- Poll auf `http://localhost:7070` (HTTP-Status / Erreichbarkeit) in festem Intervall (z. B. 30 s).
- Liefert Zustand `running | stopped | unreachable`. Speist Status-Icon **und** Notifier-State-Machine.

### 3.3 Backup (`backup.py`)
- **Hot-Backup ohne Stop:** Python `sqlite3.Connection.backup()` gegen die evcc-DB (WAL-sicher; **kein** `cp`). Zusätzlich `evcc.yaml` kopieren, falls vorhanden.
- **Ziel:** konfigurierbarer Pfad (Default: UNAS-Pro-Share). Dateiname timestamped, z. B. `evcc_YYYY-MM-DD_HHMM.db`.
- **Erreichbarkeit prüfen:** Vor dem Schreiben Mountpoint/Schreibbarkeit testen. Nicht erreichbar / kein Platz → Fehlerpfad → Notifier.
- **Retention:** „letzte N behalten" (konfigurierbar, Default 14), ältere löschen.
- **Scheduler:** intern (`schedule`/`threading.Timer`), Intervall konfigurierbar (täglich/wöchentlich/Stunden). Manuelles „Backup jetzt" im Menü.
- **Vor jedem Update** automatisch ein Backup erzwingen (dieselbe Logik wiederverwenden).

### 3.4 Updater (`updater.py`)
- **Check:** `https://api.github.com/repos/evcc-io/evcc/releases/latest`, Version mit lokal installierter (`evcc -v`) vergleichen.
  - Unauthentifiziert 60 Requests/h — für gelegentlichen Check ausreichend.
- **Asset:** macOS-Universal-Tarball `evcc_<version>_macOS_all.tar.gz` aus dem Release wählen.
- **Checksum:** SHA256 des Assets verifizieren (optional, empfohlen).
- **Ablauf:** Backup erzwingen → Agent stoppen → neues Binary holen, Quarantäne entfernen → altes nach `evcc.previous` sichern → ersetzen → Agent starten → Healthcheck.
- **Rollback:** `evcc.previous` zurückspielen + Agent neu starten.
  - **Im UI klarstellen:** Binary-Rollback funktioniert nur bei kompatibler DB. Nach einem Schema-Upgrade kann ein Downgrade scheitern → im Zweifel zusätzlich das DB-Backup zurückspielen.
- **App-Self-Update** explizit **out of scope** für v1 (v2: Sparkle + EdDSA). Vorerst manueller `.app`-Rebuild.

### 3.5 Logs (`logs.py`)
- launchd-Plist leitet `StandardOutPath`/`StandardErrorPath` auf das feste Logfile um.
- Menü:
  - „Log öffnen" → `open -a Console <logfile>` (natives Live-Tailing, Suche, Filter).
  - „Letzte 50 Zeilen" → `rumps.alert`/Window für schnellen Peek.
  - Submenü „Log-Level" (z. B. debug/info) → setzt evcc-Loglevel und startet Agent neu.
- **Rotation:** App-seitig (Größen-/Altersgrenze), da launchd nicht rotiert.

### 3.6 Notifier (`notifier.py`) — aus iCloud-Projekt portieren
- **Transport:** `smtplib` + `ssl`. SMTP-Host/-Port/-User aus Config, **Passwort aus Keychain**.
- **State-Machine-Debounce:** Mail nur bei Zustandswechsel:
  - gesund → Problem: eine Problem-Mail.
  - Problem → gesund: eine Recovery-Mail.
  - Kein Dauerfeuer während anhaltender Störung.
- **Sende-Fehler** (z. B. kein Netz) loggen, begrenzt retryen.

### 3.7 Config (`config.py`) — aus iCloud-Projekt portieren
- `config.json` für nicht-sensible Werte; Secrets in Keychain.
- Ordnerauswahl für Backup-Ziel via `NSOpenPanel` (PyObjC) oder als einfacher Fallback `osascript` Folder-Chooser.

---

## 4. Benachrichtigungs-Trigger (Notifier)

| Bedingung | Auslöser |
|---|---|
| evcc nicht erreichbar | Healthcheck schlägt N-mal in Folge fehl (Zustandswechsel) |
| Backup fehlgeschlagen | Ziel nicht gemountet / nicht beschreibbar / kein Platz / sqlite-backup-Fehler |
| Update fehlgeschlagen | Download/Checksum/Swap-Fehler oder Healthcheck nach Update rot |
| DB-Migration auffällig | evcc startet nach Update nicht / Logfile zeigt Migrationsfehler |
| Wiederherstellung | evcc nach Störung wieder erreichbar (Recovery-Mail) |

---

## 5. launchd-Plist (Template, evcc-Agent)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.evcc.menu.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/USERNAME/Library/Application Support/evcc-menu/bin/evcc</string>
        <!-- DB-Pfad-Argument bzw. -c evcc.yaml hier ergänzen (Syntax verifizieren) -->
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/USERNAME/Library/Logs/evcc-menu/evcc.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/USERNAME/Library/Logs/evcc-menu/evcc.log</string>
</dict>
</plist>
```

*Optionaler separater Backup-Agent (v2): zweites Plist mit `StartCalendarInterval`, das ein Backup-Script kalendergesteuert ausführt — entkoppelt Backups vom Laufen der GUI-App.*

---

## 6. Menüstruktur (rumps)

```
● evcc — läuft            (Status-Icon: grün/grau/rot)
─────────────────
Web-UI öffnen
─────────────────
Start
Stop
Neu starten
─────────────────
Auf Update prüfen…
Update installieren…       (nur aktiv, wenn neuere Version vorhanden)
Rollback auf vorherige Version…
─────────────────
Backup jetzt
Backup-Ziel wählen…
Logs ▸
   Log öffnen (Console)
   Letzte 50 Zeilen
   Log-Level ▸  (Info / Debug)
─────────────────
Einstellungen…             (Intervalle, Retention, SMTP)
─────────────────
Beenden
```

---

## 7. Konfigurationsschema (`config.json`, Beispiel)

```json
{
  "backup": {
    "target_path": "/Volumes/UNAS-Pro/backups/evcc",
    "schedule": "daily",
    "retention": 14
  },
  "health": {
    "url": "http://localhost:7070",
    "interval_seconds": 30,
    "failure_threshold": 3
  },
  "updates": {
    "check_on_launch": true,
    "verify_checksum": true
  },
  "notifications": {
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_user": "evcc-monitor@example.com",
    "recipient": "you@example.com"
  },
  "logging": {
    "logfile": "~/Library/Logs/evcc-menu/evcc.log",
    "max_size_mb": 20,
    "level": "info"
  }
}
```
*SMTP-Passwort liegt im Keychain, nicht in dieser Datei.*

---

## 8. Sicherheit
- SMTP-Passwort und sonstige Secrets ausschließlich im macOS-Keychain.
- Heruntergeladene Binaries: Quarantäne entfernen, optional SHA256 verifizieren.
- Ad-hoc-Signing für py2app-Build; Gatekeeper-Erstfreigabe dokumentieren.

## 9. Offene Punkte / v2
- App-Self-Update (Sparkle + EdDSA-Signatur).
- Dedizierter Log-Viewer im eigenen Fenster statt Console.app.
- Separater launchd-Backup-Agent als robustere Scheduling-Alternative.
- Exakte evcc-Flags/yaml-Keys für DB-Pfad und Loglevel gegen aktuelle evcc-Doku verifizieren.
