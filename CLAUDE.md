# CLAUDE.md — Projektkontext evcc-menu

Native macOS-**Menüleisten-App** zur terminalfreien Verwaltung einer manuell installierten
**evcc**-Instanz. Diese Datei fasst Architektur, Entscheidungen und Stolperfallen zusammen,
damit eine frische Claude-Session (auch auf einem anderen Mac) sofort produktiv ist.

- **Repo:** https://github.com/nicx/evcc-menu (public)
- **Spec (Original-Handoff):** [evcc-menu-app-spec.md](evcc-menu-app-spec.md)
- **Detaillierter Umsetzungsplan:** [docs/PLAN.md](docs/PLAN.md)
- **Stack:** Python 3.13 · rumps · py2app · launchd · SQLite · lokales MailRelay
- **Herkunft:** Bausteine (notify, keychain, settings, autostart, menubar_icon, py2app-Skelett)
  sind aus dem Schwesterprojekt `icloud-sync` **portiert**, nicht neu gebaut.

## Architektur

- Das **evcc-Binary** läuft als launchd-**LaunchAgent** `io.evcc.menu.agent` (nicht als Kind
  der App) → läuft bei App-Quit/-Crash weiter, Autostart bei Login, `KeepAlive=true`.
- Die App ist reines **Steuer-/Dashboard-Frontend** und kontrolliert den Agenten via
  `launchctl` (`bootstrap` / `bootout` / `kickstart -k`, Legacy `load/unload -w` als Fallback).
- DB-Pfad & Loglevel werden als **CLI-Flags ins Plist** geschrieben
  (`--database <pfad> --log <level>`), nicht über eine separate evcc.yaml.
- **2-Tier-Timer** in `app.py`: Health-Poll-Timer (Default 30 s) + 1-s-UI-Refresh-Timer;
  zusätzlich periodischer Update-Check-Timer (Default 24 h) und interner Backup-Scheduler.
- Langlaufendes läuft im Daemon-Thread (`_spawn`), serialisiert über `threading.Lock`.

### Modulübersicht (`src/`)
| Datei | Zweck |
|---|---|
| `app.py` | rumps.App: Menü (Spec §6), Timer, Threading, Dialoge, verdrahtet alle Module |
| `lifecycle.py` | Binary-Download/-Install, Tar-Extraktion, Quarantäne entfernen, Rollback, launchctl |
| `health.py` | HTTP-Poll `:7070` → `running|stopped|unreachable`, Fehler-Schwellwert |
| `backup.py` | `sqlite3.Connection.backup()` (WAL-sicher), Retention, `BackupScheduler` |
| `updater.py` | GitHub-Release-API, Versionsvergleich, Asset-Wahl, SHA256 |
| `logs.py` | Tail, Console.app öffnen, größenbasierte Rotation |
| `notify.py` | macOS-Notification + `send_mail` (klartext-SMTP an lokales Relay) — **PORT** |
| `notifier_state.py` | **State-Machine-Debounce**: Mail nur bei Zustandswechsel; `notify_event` für Update-Infos |
| `auth/keychain.py` | `keyring`-Wrapper (Service `evcc-menu`) — aktuell ohne Pflicht-Consumer |
| `config/settings.py` | verschachtelte Settings-Dataclasses + JSON (`config.json`), tolerant geladen |
| `paths.py` | zentrale Pfade + Label-Konstanten |
| `menubar_icon.py` | rendert 2 Template-PNGs (filled=läuft / outline=gestoppt) |
| `autostart.py` | Login-Autostart der **GUI-App** (Label `de.nicx.evcc-menu`, getrennt vom evcc-Agenten) |

### Laufzeit-Pfade
- Binary/Vorgänger: `~/Library/Application Support/evcc-menu/bin/evcc[.previous]`
- DB: `~/Library/Application Support/evcc-menu/evcc.db`
- App-Config: `~/Library/Application Support/evcc-menu/config.json`
- evcc-Logfile: `~/Library/Logs/evcc-menu/evcc.log`
- Agent-Plist: `~/Library/LaunchAgents/io.evcc.menu.agent.plist`

## Wichtige Entscheidungen
- **Mail-Transport über lokales MailRelay** (`127.0.0.1:2525`, klartext-SMTP, kein Auth/TLS).
  Bewusste **Abweichung von Spec §3.6** (SMTP+SSL+Keychain) zugunsten Ökosystem-Konsistenz.
- **CLI-Flags statt evcc.yaml** für DB/Loglevel (deterministisch, keine zweite Konfigquelle).
- **Checksum fail-closed**: bei aktiver Prüfung ohne `sha256:`-Digest wird der Download abgelehnt.
- **Download nur über `https://`** (lifecycle.download_file erzwingt das Schema).

## Verifizierte evcc-Fakten (gegen Doku/echtes Release geprüft — nicht raten!)
- DB-Pfad: `--database <pfad>` · Loglevel: `-l/--log <level>` (`fatal|error|warn|info|debug|trace`).
- evcc.yaml-Äquivalent: `database: {type: sqlite, dsn: <pfad>}` bzw. global `log:` + `levels:`.
- Version auslesen: **`evcc -v`** funktioniert (liefert z. B. `0.309.0`).
- **Release-Asset heißt `evcc_<version>_macOS-all.tar.gz` mit BINDESTRICH** (`macOS-all`),
  nicht `macOS_all` wie in der Spec. Regex akzeptiert beide: `^evcc_.*_macOS[-_]all\.tar\.gz$`.

## Mail-Verhalten (wann kommt eine Mail?)
Nur wenn Fehler-Mail aktiviert + Empfänger gesetzt:
- **evcc_unreachable**: Agent geladen, antwortet `failure_threshold`× (Default 3) nicht → 1 Problem-Mail, später 1 Recovery.
- **backup_failed** / **update_failed**: je 1 Problem + 1 Recovery.
- **Update verfügbar**: 1 Mail pro Version (dedupliziert über `updates.last_notified_version`).
- **Manueller Stop = KEINE Mail** (Agent ausgeladen → Zustand `stopped`).
- **Bewusst NICHT umgesetzt** (vom User abgelehnt): dedizierte Crash-Mail, `db_migration`-Trigger
  (Bedingung existiert, ist aber nicht verdrahtet). Kein App-Self-Update (v1 out of scope).

## Status-Icon-Konvention (analog matter-server/homeassistant)
gefülltes SF-Symbol `bolt.car.fill` = läuft · Outline `bolt.car` = gestoppt ·
Outline + rotes Badge `🔴` = nicht erreichbar. Alles Template-Images (auto-getönt hell/dunkel).

## Entwicklung & Build
```bash
# venv (einmalig)
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Dev-Run (Menüleisten-App ohne Bundle)
.venv/bin/python -m src.app
# Tests (mock-basiert, kein Netz) — derzeit 26 grün
for t in tests/test_*.py; do .venv/bin/python "$t"; done
# Build der .app (py2app + ad-hoc-Signierung + verify)
.venv/bin/pip install -r requirements-build.txt
bash build/build.sh           # → dist/evcc-menu.app
```
Erststart der gebauten App: Rechtsklick → „Öffnen" (ad-hoc signiert → Gatekeeper).
Build/dist/venv/Logs/DB sind via `.gitignore` ausgeschlossen.

## Konventionen
- Code-Kommentare/Docstrings auf Deutsch (wie Bestand).
- Best-effort-Fehlerbehandlung in I/O/Subprozessen (loggen statt werfen), damit UI/Betrieb
  nie kippt — siehe vorhandene `try/except`-Muster.
- Bei Änderungen: Tests grün halten + `bash build/build.sh` + Boot-Smoke
  (`open dist/evcc-menu.app`, Prozess prüfen, beenden).

## Gotchas
- **py2app + `charset_normalizer`:** dessen mypyc-kompilierte `*__mypyc*.so` liegt im
  site-packages-Root und wird von py2app sonst nicht mitgenommen — `build/setup.py` kopiert
  sie explizit auf den Bundle-Python-Pfad. Bei „ModuleNotFoundError" im gebauten Bundle
  hier zuerst schauen.
- **Rollback nur bei kompatibler DB:** ein Binary-Downgrade nach einem Schema-Upgrade kann
  scheitern → im Zweifel zusätzlich das DB-Backup zurückspielen (im UI so kommuniziert).
- **GUI-Autostart nur im gebauten Bundle** (`sys.frozen`), nicht im Dev-Modus
  (`python -m src.app`) — `autostart` löst sonst keine sinnvollen ProgramArguments auf.
- **Menüleisten-Icons müssen quadratisch sein:** rumps zwingt das Icon auf 20×20, ein
  nicht-quadratisches Rep würde gestaucht — `menubar_icon` rendert daher ins Quadrat mit
  erhaltenem Seitenverhältnis.
