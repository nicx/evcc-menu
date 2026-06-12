"""Erzeugt die Menüleisten-Icons als **Template-Images** (richtige Größe, system-getönt).

Portiert aus iCloud-Sync und erweitert: rendert **zwei** Varianten, um den Dienststatus
analog zu den Schwesterprojekten matter-server/homeassistant sichtbar zu machen —
**gefüllt = läuft, Outline = gestoppt** (SF-Symbol `.fill` vs. Basisvariante).

Template-Images füllen die Menüleistenhöhe wie echte System-Icons und passen sich
Hell/Dunkel automatisch an. Sie werden einmalig zur Laufzeit nach App Support gerendert
(kein Bundling nötig; gleich in Entwicklung und im .app-Bundle).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .paths import app_support_dir

LOGGER = logging.getLogger(__name__)

# Punktgröße in der Menüleiste (~22 pt nutzbare Höhe) bei 2× Pixeldichte.
_POINTS = 22
_SCALE = 2
_PX = _POINTS * _SCALE  # 44 px

# SF-Symbol-Paare (Outline, Filled) in Präferenzreihenfolge. Das erste Paar, dessen beide
# Symbole verfügbar sind, gewinnt. "bolt.car" passt zur Lade-Domäne; "bolt" als Fallback.
_SYMBOL_PAIRS = (("bolt.car", "bolt.car.fill"), ("bolt", "bolt.fill"))


def ensure_menubar_icons() -> dict[str, Optional[str]]:
    """Rendert die zwei Status-Icons und gibt ihre Pfade zurück.

    :returns: ``{"running": <pfad|None>, "stopped": <pfad|None>}`` — gefülltes Icon für
        „läuft", Outline-Icon für „gestoppt". ``None``, wenn das Rendering scheitert
        (die App fällt dann auf einen Text-Glyph zurück).
    """
    out: dict[str, Optional[str]] = {"running": None, "stopped": None}
    running_dest = app_support_dir() / "menubar_running.png"
    stopped_dest = app_support_dir() / "menubar_stopped.png"
    try:
        outline_sym, filled_sym = _pick_symbol_pair()
        # läuft = gefüllt
        if filled_sym is not None:
            _write_png(_bitmap_from_image(filled_sym), running_dest)
        else:
            _write_png(_draw_bolt_rep(filled=True), running_dest)
        out["running"] = str(running_dest)
        # gestoppt = Outline
        if outline_sym is not None:
            _write_png(_bitmap_from_image(outline_sym), stopped_dest)
        else:
            _write_png(_draw_bolt_rep(filled=False), stopped_dest)
        out["stopped"] = str(stopped_dest)
    except Exception as exc:  # noqa: BLE001 - ohne Icon fällt die App auf Textglyph zurück
        LOGGER.warning("Menüleisten-Icons konnten nicht erzeugt werden: %s", exc)
    return out


def ensure_menubar_icon() -> Optional[str]:
    """Rückwärtskompatibler Einzel-Icon-Helfer (liefert das „läuft"-Icon)."""
    return ensure_menubar_icons().get("running")


def _pick_symbol_pair():
    """Wählt das erste SF-Symbol-Paar, dessen **beide** Varianten verfügbar sind.

    :returns: ``(outline_image, filled_image)`` als NSImage-Paar oder ``(None, None)``,
        wenn kein Paar vollständig verfügbar ist (dann zeichnet die App den Fallback-Blitz).
    """
    for outline_name, filled_name in _SYMBOL_PAIRS:
        outline = _sf_symbol_image(outline_name)
        filled = _sf_symbol_image(filled_name)
        if outline is not None and filled is not None:
            return outline, filled
    return None, None


def _sf_symbol_image(name: str):
    """SF-Symbol als template NSImage in Menüleistengröße (oder None, falls nicht verfügbar)."""
    import AppKit

    fn = getattr(AppKit.NSImage, "imageWithSystemSymbolName_accessibilityDescription_", None)
    if fn is None:  # macOS < 11
        return None
    img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img is None:
        return None
    cfg_cls = getattr(AppKit, "NSImageSymbolConfiguration", None)
    if cfg_cls is not None:
        cfg = cfg_cls.configurationWithPointSize_weight_(float(_POINTS), 0.0)
        configured = img.imageWithSymbolConfiguration_(cfg)
        if configured is not None:
            img = configured
    img.setTemplate_(True)
    return img


def _bitmap_from_image(img):
    """Rendert ein NSImage zentriert in einen **quadratischen** Bitmap-Rep (schwarz/alpha, retina).

    Quadratisch ist wichtig: rumps zwingt das Menüleisten-Icon auf 20×20. Ein nicht-quadratisches
    Bild würde dadurch gestaucht. Im Quadrat mit erhaltenem Seitenverhältnis bleibt die Form korrekt.
    """
    import AppKit
    from Foundation import NSMakeRect, NSSize

    size = img.size()
    sw, sh = (size.width or _POINTS), (size.height or _POINTS)
    side = max(sw, sh)
    px = int(round(side * _SCALE))
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bitmapFormat_bytesPerRow_bitsPerPixel_(
        None, px, px, 8, 4, True, False, AppKit.NSCalibratedRGBColorSpace, 0, 0, 0
    )
    rep.setSize_(NSSize(side, side))
    ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(ctx)
    AppKit.NSColor.blackColor().set()
    img.drawInRect_(NSMakeRect((side - sw) / 2, (side - sh) / 2, sw, sh))  # zentriert
    AppKit.NSGraphicsContext.restoreGraphicsState()
    return rep


def _draw_bolt_rep(filled: bool = True):
    """Fallback: gezeichneter Blitz, falls kein SF-Symbol verfügbar ist.

    :param filled: ``True`` → gefüllt (läuft), ``False`` → nur Kontur/Outline (gestoppt).
    """
    import AppKit
    from Foundation import NSMakePoint, NSSize

    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bitmapFormat_bytesPerRow_bitsPerPixel_(
        None, _PX, _PX, 8, 4, True, False, AppKit.NSCalibratedRGBColorSpace, 0, 0, 0
    )
    rep.setSize_(NSSize(_POINTS, _POINTS))
    ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(ctx)
    AppKit.NSColor.blackColor().set()
    u = _PX / 44.0
    bolt = AppKit.NSBezierPath.bezierPath()
    # Blitz-Polygon in 44er-Koordinaten (x rechts, y oben).
    pts = [(26, 40), (12, 22), (21, 22), (18, 4), (32, 24), (23, 24)]
    bolt.moveToPoint_(NSMakePoint(pts[0][0] * u, pts[0][1] * u))
    for x, y in pts[1:]:
        bolt.lineToPoint_(NSMakePoint(x * u, y * u))
    bolt.closePath()
    if filled:
        bolt.fill()
    else:
        bolt.setLineWidth_(2.0 * u)  # Outline-Kontur in Menüleisten-tauglicher Strichstärke
        bolt.stroke()
    AppKit.NSGraphicsContext.restoreGraphicsState()
    return rep


def _write_png(rep, dest: Path) -> None:
    import AppKit

    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    png.writeToFile_atomically_(str(dest), True)
