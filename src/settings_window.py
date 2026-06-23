"""Natives Settings-Fenster (PyObjC/AppKit) statt der Popup-Dialogkette.

Erster Baustein der schrittweisen rumps→PyObjC-Vereinheitlichung (siehe CLAUDE.md):
dieses Modul ist **bewusst rumps-frei** und lebt unverändert in einer späteren reinen
AppKit-Shell weiter.

Aufteilung:

- :func:`build_settings` ist **reine Logik** (kein AppKit-Import) — Validierung/Coercion der
  Roh-Eingaben in ein neues :class:`Settings`. Dadurch unit-testbar.
- Die AppKit-Schicht (:func:`run_settings_window` + ``_SettingsController``) ist eine dünne
  Hülle: Werte aus den Controls einsammeln → :func:`build_settings` → Beep-oder-Commit.
  AppKit wird **lazy innerhalb der Funktionen** importiert, damit das Modul (und
  :func:`build_settings`) auch ohne GUI importierbar bleibt.

Die Modal-Strategie spiegelt den bestehenden ``NSOpenPanel``-Präzedenzfall in
:mod:`src.app` (``_native_directory_dialog``): application-modal via
``runModalForWindow_`` auf dem Main-Thread. Niemals aus einem Hintergrund-Thread aufrufen.
"""

from __future__ import annotations

import copy
import logging
from typing import Callable, Optional

from . import backup
from .config.settings import Settings

LOGGER = logging.getLogger(__name__)

# Gültige evcc-Loglevel (gegen Doku geprüft, siehe CLAUDE.md).
_LEVELS = ["fatal", "error", "warn", "info", "debug", "trace"]
# Backup-Zeitpläne aus der Single Source of Truth in :mod:`src.backup`.
_SCHEDULES = list(backup._SCHEDULE_HOURS)

# Feld-Definition als gemeinsame Quelle für Seed (AppKit) und Validierung (pure).
# (Label, kind, "section.attr"[, options]). kind ∈ text|int|folder|check|popup.
_SECTIONS: list[tuple[str, list[tuple]]] = [
    ("Backup", [
        ("Backup-Ziel", "folder", "backup.target_path"),
        ("Zeitplan", "popup", "backup.schedule", _SCHEDULES),
        ("Backups behalten", "int", "backup.retention"),
    ]),
    ("Health", [
        ("URL", "text", "health.url"),
        ("Intervall (s)", "int", "health.interval_seconds"),
        ("Fehler-Schwelle", "int", "health.failure_threshold"),
    ]),
    ("Updates", [
        ("Beim Start prüfen", "check", "updates.check_on_launch"),
        ("Check-Intervall (h, 0=aus)", "int", "updates.check_interval_hours"),
        ("Checksumme prüfen", "check", "updates.verify_checksum"),
        ("E-Mail bei Update", "check", "updates.notify_email"),
    ]),
    ("Mail", [
        ("Fehler-Mail aktiv", "check", "notifications.enabled"),
        ("Relay-Host", "text", "notifications.smtp_host"),
        ("Relay-Port", "int", "notifications.smtp_port"),
        ("Absender", "text", "notifications.sender"),
        ("Empfänger", "text", "notifications.recipient"),
    ]),
    ("Logging", [
        ("Log-Level", "popup", "logging.level", _LEVELS),
        ("Max. Loggröße (MB)", "int", "logging.max_size_mb"),
    ]),
]


def _get(settings: Settings, path: str):
    section, attr = path.split(".")
    return getattr(getattr(settings, section), attr)


def _set(settings: Settings, path: str, value) -> None:
    section, attr = path.split(".")
    setattr(getattr(settings, section), attr, value)


# Ganzzahl-Felder mit ihren Clamp-Regeln (Minimum) bzw. Bereichsprüfung.
_INT_MIN = {
    "backup.retention": ("Backups behalten", 1),
    "health.interval_seconds": ("Healthcheck-Intervall", 5),
    "health.failure_threshold": ("Fehler-Schwelle", 1),
    "updates.check_interval_hours": ("Update-Check-Intervall", 0),
    "logging.max_size_mb": ("Max. Loggröße", 1),
}


def build_settings(base: Settings, raw: dict) -> tuple[Optional[Settings], list[str]]:
    """Baut aus ``base`` + Roh-Eingaben ``raw`` ein neues, validiertes :class:`Settings`.

    ``base`` wird tief kopiert (interne Felder wie ``updates.last_notified_version`` bleiben
    erhalten). ``raw`` ist nach ``"section.attr"`` verschlüsselt; Werte sind ``str`` (text/
    int/folder/popup) bzw. ``bool`` (check). Gibt ``(settings, [])`` bei Erfolg oder
    ``(None, [Fehlertexte])`` zurück. Strings werden wie in der alten Dialogkette getrimmt.
    """
    s = copy.deepcopy(base)
    errors: list[str] = []

    # Strings
    for key in ("backup.target_path", "health.url", "notifications.smtp_host",
                "notifications.sender", "notifications.recipient"):
        if key in raw:
            _set(s, key, str(raw[key]).strip())

    # Booleans
    for key in ("updates.check_on_launch", "updates.verify_checksum",
                "updates.notify_email", "notifications.enabled"):
        if key in raw:
            _set(s, key, bool(raw[key]))

    # Popups mit Whitelist
    if "backup.schedule" in raw:
        val = str(raw["backup.schedule"]).strip()
        if val in backup._SCHEDULE_HOURS:
            _set(s, "backup.schedule", val)
        else:
            errors.append(f"Backup-Zeitplan ungültig: {val}")
    if "logging.level" in raw:
        val = str(raw["logging.level"]).strip()
        if val in _LEVELS:
            _set(s, "logging.level", val)
        else:
            errors.append(f"Log-Level ungültig: {val}")

    # Ganzzahlen
    def _parse_int(key: str, label: str) -> Optional[int]:
        try:
            return int(str(raw[key]).strip())
        except (ValueError, TypeError):
            errors.append(f"{label}: keine ganze Zahl")
            return None

    for key, (label, minimum) in _INT_MIN.items():
        if key in raw:
            v = _parse_int(key, label)
            if v is not None:
                _set(s, key, max(minimum, v))

    if "notifications.smtp_port" in raw:
        v = _parse_int("notifications.smtp_port", "Relay-Port")
        if v is not None:
            if 1 <= v <= 65535:
                _set(s, "notifications.smtp_port", v)
            else:
                errors.append("Relay-Port muss zwischen 1 und 65535 liegen")

    if errors:
        return None, errors
    return s, []


# -- AppKit-Schicht ----------------------------------------------------------
# NSObject lazy/guarded importieren: hält das Modul (und build_settings) auch ohne
# AppKit importierbar; die ObjC-Klasse wird nur einmal registriert.
try:  # pragma: no cover - umgebungsabhängig
    from Foundation import NSObject
    _APPKIT = True
except Exception:  # pragma: no cover
    NSObject = object  # type: ignore[assignment,misc]
    _APPKIT = False

_OK_CODE = 1000
_CANCEL_CODE = 0


class _SettingsController(NSObject):  # type: ignore[misc]
    """Hält die Controls am Leben und bedient OK/Abbrechen/Ordnerwahl (Target/Action).

    Lebt für die gesamte synchrone :func:`run_settings_window`-Stackframe → die PyObjC-
    Target/Action-Referenzen bleiben gültig, solange das Fenster modal läuft.
    """

    def ok_(self, _sender) -> None:
        import AppKit

        raw = {}
        for key, (kind, control) in self._controls.items():  # type: ignore[attr-defined]
            if kind == "check":
                raw[key] = control.state() == 1
            elif kind == "popup":
                raw[key] = control.titleOfSelectedItem()
            else:  # text | int | folder
                raw[key] = control.stringValue()
        result, errs = build_settings(self._base, raw)  # type: ignore[attr-defined]
        if errs:
            LOGGER.info("Settings-Validierung fehlgeschlagen: %s", "; ".join(errs))
            AppKit.NSBeep()
            return  # Modal offen lassen, damit der Nutzer korrigieren kann
        self._result = result  # type: ignore[attr-defined]
        AppKit.NSApplication.sharedApplication().stopModalWithCode_(_OK_CODE)

    def cancel_(self, _sender) -> None:
        import AppKit

        AppKit.NSApplication.sharedApplication().stopModalWithCode_(_CANCEL_CODE)

    def pickFolder_(self, _sender) -> None:
        current = self._folder_control.stringValue()  # type: ignore[attr-defined]
        chosen = self._choose_dir(  # type: ignore[attr-defined]
            "Backup-Ziel wählen (z. B. UNAS-Pro-Share):", current or None)
        if chosen:
            self._folder_control.setStringValue_(chosen)  # type: ignore[attr-defined]


def run_settings_window(settings: Settings,
                        choose_dir: Callable[[str, Optional[str]], Optional[str]]
                        ) -> Optional[Settings]:
    """Zeigt das modale Settings-Fenster, vorbelegt aus ``settings``.

    :param choose_dir: Ordnerwahl-Callback ``(message, default) -> Optional[str]`` (die App
        reicht hier ihren ``NSOpenPanel``-Dialog herein, damit er der einzige Owner bleibt).
    :returns: ein **neues** validiertes :class:`Settings` bei OK, sonst ``None`` (Abbrechen).
        Das übergebene ``settings`` wird nie mutiert.
    """
    import AppKit
    from Foundation import NSMakeRect, NSMakeSize

    controller = _SettingsController.alloc().init()
    controller._base = settings
    controller._choose_dir = choose_dir
    controller._result = None
    controller._controls = {}
    controller._folder_control = None

    def _label(text: str, bold: bool = False):
        lbl = AppKit.NSTextField.labelWithString_(text)
        if bold:
            lbl.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        return lbl

    pending_constraints = []

    def _make_control(kind: str, path: str, options):
        value = _get(settings, path)
        if kind == "check":
            btn = AppKit.NSButton.checkboxWithTitle_target_action_("", None, None)
            btn.setState_(1 if value else 0)
            return btn
        if kind == "popup":
            popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(0, 0, 200, 25), False)
            popup.addItemsWithTitles_(list(options))
            popup.selectItemWithTitle_(str(value))
            return popup
        # text | int | folder -> NSTextField mit Mindestbreite
        field = AppKit.NSTextField.alloc().init()
        field.setStringValue_("" if value is None else str(value))
        field.setTranslatesAutoresizingMaskIntoConstraints_(False)
        pending_constraints.append(
            field.widthAnchor().constraintGreaterThanOrEqualToConstant_(220))
        if kind == "folder":
            field.setEditable_(False)
            field.setSelectable_(True)
        return field

    # Vertikaler Stack mit je einem Header-Label + NSGridView pro Sektion.
    stack = AppKit.NSStackView.alloc().init()
    stack.setOrientation_(1)  # NSUserInterfaceLayoutOrientationVertical
    stack.setAlignment_(AppKit.NSLayoutAttributeLeading)
    stack.setSpacing_(10)
    stack.setTranslatesAutoresizingMaskIntoConstraints_(False)

    for si, (title, rows) in enumerate(_SECTIONS):
        if si > 0:
            sep = AppKit.NSBox.alloc().init()
            sep.setBoxType_(AppKit.NSBoxSeparator)
            stack.addArrangedSubview_(sep)
            pending_constraints.append(
                sep.widthAnchor().constraintEqualToAnchor_(stack.widthAnchor()))
        stack.addArrangedSubview_(_label(title, bold=True))

        grid_rows = []
        for row in rows:
            label, kind, path = row[0], row[1], row[2]
            options = row[3] if len(row) > 3 else None
            control = _make_control(kind, path, options)
            controller._controls[path] = (kind, control)
            if kind == "folder":
                controller._folder_control = control
                btn = AppKit.NSButton.buttonWithTitle_target_action_(
                    "Wählen…", controller, "pickFolder:")
                cell = AppKit.NSStackView.alloc().init()
                cell.setOrientation_(0)  # horizontal
                cell.setSpacing_(6)
                cell.addArrangedSubview_(control)
                cell.addArrangedSubview_(btn)
                grid_rows.append([_label(label + ":"), cell])
            else:
                grid_rows.append([_label(label + ":"), control])

        grid = AppKit.NSGridView.gridViewWithViews_(grid_rows)
        grid.setRowSpacing_(6)
        grid.setColumnSpacing_(8)
        grid.columnAtIndex_(0).setXPlacement_(AppKit.NSGridCellPlacementTrailing)
        stack.addArrangedSubview_(grid)

    # Button-Zeile (Abbrechen / OK).
    cancel_btn = AppKit.NSButton.buttonWithTitle_target_action_(
        "Abbrechen", controller, "cancel:")
    cancel_btn.setKeyEquivalent_("\x1b")  # Esc
    ok_btn = AppKit.NSButton.buttonWithTitle_target_action_("OK", controller, "ok:")
    ok_btn.setKeyEquivalent_("\r")  # Enter = Default
    button_row = AppKit.NSStackView.alloc().init()
    button_row.setOrientation_(0)
    button_row.setSpacing_(10)
    spacer = AppKit.NSView.alloc().init()
    spacer.setContentHuggingPriority_forOrientation_(1, 0)  # dehnt sich
    button_row.addArrangedSubview_(spacer)
    button_row.addArrangedSubview_(cancel_btn)
    button_row.addArrangedSubview_(ok_btn)
    button_row.setTranslatesAutoresizingMaskIntoConstraints_(False)
    stack.addArrangedSubview_(button_row)
    pending_constraints.append(
        button_row.widthAnchor().constraintEqualToAnchor_(stack.widthAnchor()))

    style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, 480, 520), style, AppKit.NSBackingStoreBuffered, False)
    window.setTitle_("Einstellungen")
    window.setReleasedWhenClosed_(False)
    controller._window = window

    content = window.contentView()
    content.addSubview_(stack)
    AppKit.NSLayoutConstraint.activateConstraints_([
        stack.leadingAnchor().constraintEqualToAnchor_constant_(content.leadingAnchor(), 16),
        stack.trailingAnchor().constraintEqualToAnchor_constant_(content.trailingAnchor(), -16),
        stack.topAnchor().constraintEqualToAnchor_constant_(content.topAnchor(), 16),
        stack.bottomAnchor().constraintEqualToAnchor_constant_(content.bottomAnchor(), -16),
    ] + pending_constraints)

    # Fenster an den Inhalt anpassen.
    content.layoutSubtreeIfNeeded()
    fitting = stack.fittingSize()
    window.setContentSize_(NSMakeSize(max(460, fitting.width + 32), fitting.height + 32))
    if grid_rows:
        window.setInitialFirstResponder_(controller._controls["health.url"][1])

    app = AppKit.NSApplication.sharedApplication()
    app.activateIgnoringOtherApps_(True)
    window.center()
    window.makeKeyAndOrderFront_(None)
    response = app.runModalForWindow_(window)
    window.orderOut_(None)
    return controller._result if response == _OK_CODE else None
