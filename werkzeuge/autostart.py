"""FaxFinity beim Anmelden automatisch starten -- einrichten oder entfernen.

Wird von "Autostart einrichten.bat" aufgerufen. Die eigentliche Arbeit steht in
faxfinity/autostart.py, damit die EXE-Fassung dasselbe über einen Schalter in
der Oberfläche anbieten kann -- dort gibt es keine Eingabeaufforderung mehr.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faxfinity import autostart  # noqa: E402


def schreiben(zeile: str = "") -> None:
    try:
        print(zeile)
    except UnicodeEncodeError:
        print(zeile.encode("ascii", "replace").decode("ascii"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    schreiben()
    schreiben("FaxFinity beim Anmelden automatisch starten")
    schreiben("==========================================")
    schreiben()

    if autostart.eingerichtet():
        schreiben("  Der Autostart ist bereits eingerichtet:")
        schreiben(f"  {autostart.VERKNUEPFUNG}")
        schreiben()
        if input("  Wieder entfernen? [j/N] ").strip().lower().startswith("j"):
            schreiben("  Autostart entfernt." if autostart.entfernen()
                      else "  Entfernen fehlgeschlagen.")
        else:
            schreiben("  Unveraendert gelassen.")
        return 0

    if not autostart.einrichten():
        schreiben("  Einrichten fehlgeschlagen (Einzelheiten oben).")
        return 1

    ziel, argumente, _ = autostart.startbefehl()
    schreiben("  Autostart eingerichtet.")
    schreiben(f"  Gestartet wird: {ziel} {argumente}")
    schreiben()
    schreiben("  FaxFinity laeuft ab dem naechsten Anmelden im Hintergrund.")
    schreiben("  Die Oberflaeche ist dann erreichbar unter:")
    schreiben("    http://127.0.0.1:8757")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        schreiben("\nAbgebrochen.")
        raise SystemExit(1) from None
