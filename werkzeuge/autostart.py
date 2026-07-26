"""FaxFinity beim Anmelden automatisch starten -- einrichten oder entfernen.

Legt eine Verknüpfung im Autostart-Ordner an, die den Dienst ohne Fenster und
ohne Browser startet. Die Oberfläche ist danach jederzeit unter
http://127.0.0.1:8757 erreichbar.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
VERKNUEPFUNG = (
    Path(os.environ["APPDATA"])
    / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    / "FaxFinity.lnk"
)


def schreiben(zeile: str = "") -> None:
    try:
        print(zeile)
    except UnicodeEncodeError:
        print(zeile.encode("ascii", "replace").decode("ascii"))


def pythonw() -> str:
    """Der Interpreter ohne Konsolenfenster, damit nichts im Weg steht."""
    ohne_fenster = Path(sys.executable).with_name("pythonw.exe")
    return str(ohne_fenster if ohne_fenster.is_file() else sys.executable)


def anlegen() -> bool:
    skript = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$s = $w.CreateShortcut('{VERKNUEPFUNG}'); "
        f"$s.TargetPath = '{pythonw()}'; "
        "$s.Arguments = '-m faxfinity --ohne-browser'; "
        f"$s.WorkingDirectory = '{WURZEL}'; "
        "$s.Description = 'FaxFinity Hintergrunddienst'; "
        "$s.Save()"
    )
    ergebnis = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", skript],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if ergebnis.returncode != 0:
        schreiben("  Fehler beim Anlegen der Verknuepfung:")
        schreiben("  " + (ergebnis.stderr or "").strip()[:300])
        return False
    return VERKNUEPFUNG.is_file()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    schreiben()
    schreiben("FaxFinity beim Anmelden automatisch starten")
    schreiben("==========================================")
    schreiben()

    if VERKNUEPFUNG.is_file():
        schreiben(f"  Der Autostart ist bereits eingerichtet:")
        schreiben(f"  {VERKNUEPFUNG}")
        schreiben()
        antwort = input("  Wieder entfernen? [j/N] ").strip().lower()
        if antwort.startswith("j"):
            VERKNUEPFUNG.unlink()
            schreiben("  Autostart entfernt.")
        else:
            schreiben("  Unveraendert gelassen.")
        return 0

    if not anlegen():
        return 1

    schreiben("  Autostart eingerichtet.")
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
