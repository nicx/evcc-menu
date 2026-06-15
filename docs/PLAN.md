# Plan: evcc Menübar-App für macOS

## Context

Eine native macOS-Menübar-App soll eine manuell installierte evcc-Instanz terminalfrei
verwalten (Install, Start/Stop/Restart, Updates mit Rollback, automatische SQLite-Backups,
Log-Einsicht, E-Mail-Alarm bei Problemen). Die vollständige Handoff-Spec liegt in
[evcc-menu-app-spec.md](evcc-menu-app-spec.md).

Zwei explizite Handoff-Vorgaben prägen diesen Plan:

1. **Portieren statt neu bauen** — die Bausteine Notifier, Config/Keychain, LaunchAgent,
   Menübar-Icon, py2app-Skelett werden aus dem Schwesterprojekt
   `/Users/timo/Git/icloud-sync/` übernommen und angepasst, nicht von Grund auf neu
   geschrieben.
2. **evcc-Syntax verifizieren statt raten** (§9) — erledigt, siehe nächster Abschnitt.

**Getroffene Entscheidungen (mit dem User abgestimmt):**
- Projektort: direkt in `/Users/timo/Git/evcc/`.
- Mail-Transport: über das lokale **MailRelay** (`127.0.0.1:2525`, klartext-SMTP, kein
  Auth/TLS) — `notify.send_mail` aus iCloud-Sync 1:1 portieren. Kein Keychain-Passwort für
  SMTP nötig (MailRelay übernimmt Upstream-Auth/TLS/Retry). **Abweichung von Spec §3.6**,
  die SMTP+SSL+Keychain beschreibt — bewusst verworfen zugunsten der Ökosystem-Konsistenz.

## Verifizierte evcc-Syntax (§9-Punkt — gegen aktuelle Doku geprüft)

Quelle: docs.evcc.io/en/reference/configuration/log, .../cli/evcc, .../configuration/database.

| Zweck | CLI-Flag (im Plist bevorzugt) | evcc.yaml-Äquivalent |
|---|---|---|
| DB-Pfad | `--database <pfad>` (Default `~/.evcc/evcc.db`) | `database:`<br>`  type: sqlite`<br>`  dsn: <pfad>` |
| Config-Datei | `-c, --config <pfad>` | — |
| Loglevel | `-l, --log <level>` (Default `info`) | global `log: <level>` + `levels:` je Komponente |
| Multi-DB-Warnung unterdrücken | `--ignore-db` | — |

Loglevel-Werte: `fatal | error | warn | info | debug | trace`.

→ Spec-Annahme `database.dsn` ist korrekt. **Im Plist die CLI-Flags verwenden**
(`--database`, `--log`) — deterministischer als yaml und ohne separate Config-Datei.
Loglevel-Wechsel im Menü = Plist-Argument `--log <level>` neu schreiben + `kickstart -k`.

## Projektstruktur (in /Users/timo/Git/evcc/)

Skelett gespiegelt von icloud-sync (`launcher.py` + `src/`-Paket + `build/setup.py`):

```
evcc/
├── evcc-menu-app-spec.md        # bereits vorhanden
├── launcher.py                  # py2app-Entrypoint: from src.app import main
├── requirements.txt             # rumps==0.4.0, keyring==25.7.0, pync==2.0.3, requests
├── requirements-build.txt       # -r requirements.txt + py2app==0.28.10
├── src/
│   ├── __init__.py              # __version__
│   ├── app.py                   # rumps.App: Menü, 2-Tier-Timer, Threading, Dialoge
│   ├── lifecycle.py             # NEU: Binary-Download/-Install, Plist, launchctl
│   ├── health.py                # NEU: HTTP-Poll localhost:7070
│   ├── backup.py                # NEU: sqlite3.Connection.backup(), Retention, Scheduler
│   ├── updater.py               # NEU: GitHub-Release-Check, Swap, Rollback
│   ├── logs.py                  # NEU: Logfile/Rotation/Console.app
│   ├── notify.py                # PORT: aus icloud-sync (notify + send_mail)
│   ├── notifier_state.py        # NEU: State-Machine-Debounce (gibt's nirgends)
│   ├── autostart.py             # PORT: LaunchAgent für App-Login-Autostart
│   ├── menubar_icon.py          # PORT: Icon-Rendering (SF-Symbol tauschen)
│   ├── paths.py                 # NEU/adaptiert: zentrale evcc-menu-Pfade
│   ├── auth/
│   │   ├── __init__.py
│   │   └── keychain.py          # PORT: keyring-Wrapper (Service umbenennen)
│   └── config/
│       ├── __init__.py
│       └── settings.py          # PORT+erweitert: Settings-Dataclass + JSON
├── build/
│   ├── setup.py                 # py2app (LSUIElement, Bundle-ID, packages)
│   └── build.sh                 # Build + ad-hoc-codesign + verify
└── tests/
    └── test_*.py                # unittest, mock-basiert, standalone ausführbar
```

## Was aus icloud-sync portiert wird (real existierende Dateien)

| Quelle (icloud-sync) | Ziel | Anpassung |
|---|---|---|
| `src/notify.py` | `src/notify.py` | 1:1 — `notify()` (rumps→pync-Fallback) + `send_mail()` (klartext-SMTP an MailRelay). Stateless lassen. |
| `src/auth/keychain.py` | `src/auth/keychain.py` | `KEYCHAIN_SERVICE` → `"evcc-menu"`; Legacy-Migration entfernen. (Nur falls künftig Secrets nötig — aktuell kein SMTP-Passwort.) |
| `src/config/settings.py` | `src/config/settings.py` | `Settings`-Dataclass auf evcc-Felder umbauen (siehe §7 der Spec: backup/health/updates/notifications/logging). JSON-Atomic-Write + Forward-Compat-Parsing behalten. |
| `src/config/paths.py` | `src/paths.py` | `APP_DIR_NAME="evcc-menu"`; Pfade gem. Spec §2 (bin/, evcc.db, Logs, LaunchAgents-Label `io.evcc.menu.agent`). |
| `src/autostart.py` | `src/autostart.py` | `LABEL="de.nicx.evcc-menu"` (App-Autostart — **getrennt** vom evcc-Agent-Label `io.evcc.menu.agent`). plistlib + `launchctl load/unload -w`. |
| `src/menubar_icon.py` | `src/menubar_icon.py` | SF-Symbol `"icloud"` → `"bolt.car"`/`"bolt"`; Rendering-Logik unverändert. |
| `src/app.py` (Muster) | `src/app.py` | Skelett übernehmen: `rumps.App`-Subklasse, 2-Tier-`rumps.Timer` (langsamer Dispatch-Tick + 1s-UI-Tick), `_spawn()` Daemon-Thread + `threading.Lock`, `rumps.Window`/`NSOpenPanel`-Dialoge. Menü gem. Spec §6 neu. |
| `build/setup.py` (Muster) | `build/setup.py` | Bundle-ID `io.evcc.menu`, `LSUIElement: True`, `packages` ohne pyicloud (nicht gebraucht), dafür `requests`. |

## Neu zu bauende Module (kein Vorbild in beiden Repos)

- **`notifier_state.py`** — State-Machine-Debounce (Spec §3.6/§4). Pro Bedingung
  (`evcc_unreachable`, `backup_failed`, `update_failed`, `db_migration`) Zustand
  `healthy|problem` halten; nur bei Wechsel eine Problem- bzw. Recovery-Mail via
  `notify.send_mail`. Kein Dauerfeuer. Sende-Fehler loggen, begrenzt retryen.
- **`lifecycle.py`** — Binary aus GitHub-Release laden, entpacken, `chmod +x`,
  **`xattr -d com.apple.quarantine`** (Gatekeeper-Fallstrick §3.1). Plist mit
  `--database <pfad> --log <level>` ProgramArguments schreiben. launchctl moderne API:
  `bootstrap gui/$(id -u) <plist>` / `bootout` / `kickstart -k`, Legacy `load -w` als
  Fallback.
- **`health.py`** — Poll `http://localhost:7070` alle 30s, Zustand
  `running|stopped|unreachable`, speist Icon + State-Machine.
- **`backup.py`** — **`sqlite3.Connection.backup()`** (WAL-sicher, kein `cp`) gegen
  `evcc.db` + `evcc.yaml` mitkopieren. Mountpoint/Schreibbarkeit vorher prüfen → sonst
  Fehlerpfad → Notifier. Retention „letzte N" (Default 14). Interner Scheduler
  (`threading.Timer`). Vor jedem Update Backup erzwingen.
- **`updater.py`** — `api.github.com/repos/evcc-io/evcc/releases/latest`, Version vs.
  `evcc -v`. Asset `evcc_<version>_macOS_all.tar.gz`, optional SHA256. Ablauf:
  Backup→Stop→neues Binary+Quarantäne entfernen→altes nach `evcc.previous`→ersetzen→
  Start→Healthcheck. Rollback aus `evcc.previous`. App-Self-Update out of scope (v1).
- **`logs.py`** — Plist leitet StdOut/StdErr auf festes Logfile. Menü: „Log öffnen"
  (`open -a Console`), „Letzte 50 Zeilen" (rumps), „Log-Level"-Submenü (Plist neu +
  `kickstart -k`). App-seitige Rotation (Größen-/Altersgrenze).

## launchd-Plist (evcc-Agent) — konkretisiert

`~/Library/LaunchAgents/io.evcc.menu.agent.plist`, ProgramArguments:
```
<binary> --database <app-support>/evcc-menu/evcc.db --log info
```
`RunAtLoad=true`, `KeepAlive=true`, StdOut/StdErr → `~/Library/Logs/evcc-menu/evcc.log`.
(Spec §5-Template mit verifizierten Flags statt Platzhalter-Kommentar.)

## Dev/Build-Befehle (von icloud-sync übernommen)

```bash
# Setup
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Dev-Run (Menübar-App ohne .app-Bundle)
.venv/bin/python -m src.app
# Build
.venv/bin/pip install -r requirements-build.txt
.venv/bin/python build/setup.py py2app --dist-dir dist --bdist-base build/_py2app
codesign --force --deep --sign - "dist/evcc-menu.app"   # ad-hoc
# Tests (mock-basiert, kein Netz)
.venv/bin/python tests/test_backup.py
```

## Verifikation (End-to-End)

1. **Lifecycle:** App startet, lädt evcc-Binary, entfernt Quarantäne, schreibt Plist,
   `launchctl bootstrap` → `health.py` meldet `running`, Icon grün, Web-UI auf :7070
   erreichbar.
2. **Backup:** „Backup jetzt" erzeugt `evcc_YYYY-MM-DD_HHMM.db` am Ziel; Retention löscht
   ab N+1; Ziel unmounten → Notifier-Problem-Mail (genau eine), Recovery beim Remount.
3. **Update/Rollback:** simulierter Release → Backup erzwungen, Swap, Healthcheck grün;
   „Rollback" stellt `evcc.previous` wieder her.
4. **Notifier-State-Machine:** evcc killen → genau **eine** Problem-Mail trotz mehrerer
   fehlgeschlagener Polls; Neustart → genau **eine** Recovery-Mail (Mails landen via
   MailRelay; in Dev MailRelay auf `127.0.0.1:2525` mitlaufen lassen oder Transport mocken).
5. **Loglevel:** Submenü Debug → Plist-Arg `--log debug`, `kickstart -k`, Logfile zeigt
   Debug-Zeilen.
6. **Unit-Tests:** Backup-Retention, Updater-Versionsvergleich, State-Machine-Übergänge
   (mock-basiert, kein Netz/Account) grün.

---

## Nachtrag: Dienststatus über Icon-Variante (filled = läuft / outline = gestoppt)

**Context:** Bisher rendert die App ein einzelnes `bolt.car`-Template-Icon; running vs.
stopped sind optisch nicht unterscheidbar — nur „unreachable" zeigt ein rotes Badge `🔴`.
Die Swift-Schwesterprojekte **matter-server** und **homeassistant** lösen das per
SF-Symbol-Variante und sollen als Vorbild dienen.

**Verifizierte Konvention (beide Projekte identisch, `MenuBarLabel`-View):**
- läuft → **gefülltes** Symbol (`.fill`), z. B. `house.fill` / `point.3.filled.…`
- gestoppt / startet / stoppt → **Outline** (Basissymbol), z. B. `house`
- Crash → eigenes Alert-Symbol `exclamationmark.triangle.fill`
- Alle als **Template-Images** (auto-getönt für hell/dunkel) — keine Custom-Assets.

**Übertragung auf evcc-menu:**
- `RUNNING` → `bolt.car.fill` (gefüllt)
- `STOPPED` → `bolt.car` (outline)
- `UNREACHABLE` (Agent geladen, antwortet nicht) → `bolt.car` (outline) **+** bestehendes
  rotes Badge `🔴` (entspricht dem distinct Problem-Marker der Vorbilder)

**Änderungen:**

1. [src/menubar_icon.py](src/menubar_icon.py)
   - Symbol-**Paare** statt einzelner Liste:
     `_SYMBOL_PAIRS = [("bolt.car", "bolt.car.fill"), ("bolt", "bolt.fill")]` — erstes Paar,
     dessen beide Symbole verfügbar sind, gewinnt (via bestehendem `_sf_symbol_image`).
   - Neue API `ensure_menubar_icons() -> dict[str, Optional[str]]`, rendert **zwei**
     Template-PNGs (`menubar_running.png` = filled, `menubar_stopped.png` = outline) und
     gibt `{"running": pfad|None, "stopped": pfad|None}` zurück.
   - Drawn-Fallback `_draw_bolt_rep(filled: bool)`: `filled=True` → `fill()` (heute),
     `filled=False` → `stroke()` mit `setLineWidth_` ohne Füllung.
   - `ensure_menubar_icon()` (alt) als dünner Wrapper auf den running-Pfad belassen oder
     entfernen — einziger Consumer ist `app.py`.

2. [src/app.py](src/app.py)
   - `_setup_menubar_icon`: `ensure_menubar_icons()` aufrufen, `self._icon_running` /
     `self._icon_stopped` merken, `self.template = True`, Startsymbol = stopped. `self._has_icon`
     true, wenn mindestens beide Pfade vorhanden.
   - `_update_icon`: Icon nach `self._state` wählen (`RUNNING` → running-Icon, sonst
     stopped-Icon), `self.icon` **nur bei Pfadwechsel** setzen (zuletzt gesetzten Pfad
     cachen — vermeidet Flackern beim 1s-UI-Tick); Badge `🔴` weiter bei `UNREACHABLE`;
     Text-Fallback `evcc` / `evcc 🔴` wenn keine Icons gerendert wurden.

**Verifikation:**
- Bestehende 25 Unit-Tests müssen grün bleiben (kein logischer Bezug; `menubar_icon` braucht
  AppKit/GUI und wird daher nicht unit-getestet, sondern per Smoke-Test).
- Manuell nach `bash build/build.sh`: App starten → „Stop" ⇒ Outline-Icon; „Start" ⇒
  gefülltes Icon; evcc bei geladenem Agent killen ⇒ Outline + rotes `🔴`. Boot-Smoke wie gehabt.
