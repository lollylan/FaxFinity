"""FaxFinity beim Anmelden mitstarten -- einrichten, prüfen, entfernen.

Angelegt wird eine Verknüpfung im Autostart-Ordner des angemeldeten Benutzers.
Bewusst nicht über die Registrierung und nicht für alle Benutzer: das ginge nur
mit Administratorrechten, und in einer Praxis meldet sich ohnehin jeder am
eigenen Konto an.

Die Verknüpfung zeigt auf das, womit FaxFinity gerade läuft -- auf die EXE, wenn
es als EXE läuft, sonst auf pythonw.exe mit dem Projektordner. Damit stimmt der
Autostart in beiden Fassungen, ohne dass jemand Pfade eintragen muss.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

VERKNUEPFUNG = (
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    / "FaxFinity.lnk"
)


def startbefehl() -> tuple[str, str, str]:
    """Ziel, Argumente und Arbeitsordner für die Verknüpfung."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return str(exe), "--ohne-browser", str(exe.parent)

    # pythonw.exe statt python.exe: sonst steht beim Anmelden ein schwarzes
    # Fenster auf dem Bildschirm, das niemand schließen darf.
    ohne_fenster = Path(sys.executable).with_name("pythonw.exe")
    interpreter = ohne_fenster if ohne_fenster.is_file() else Path(sys.executable)
    wurzel = Path(__file__).resolve().parent.parent
    return str(interpreter), "-m faxfinity --ohne-browser", str(wurzel)


def eingerichtet() -> bool:
    return VERKNUEPFUNG.is_file()


def _powershell(skript: str) -> bool:
    try:
        ergebnis = subprocess.run(  # noqa: S603 -- fester Befehl, Werte einfach hochkommagesichert
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", skript],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
            # Ohne dies blitzt beim Einrichten ein Konsolenfenster auf.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as fehler:
        logger.error("Autostart: PowerShell nicht ausführbar (%s)", fehler)
        return False
    if ergebnis.returncode != 0:
        logger.error("Autostart: %s", (ergebnis.stderr or "").strip()[:300])
        return False
    return True


def einrichten() -> bool:
    ziel, argumente, ordner = startbefehl()

    def hochkomma(wert: str) -> str:
        # In PowerShell schützt ein doppeltes Hochkomma ein einfaches. Ohne das
        # scheitert jeder Pfad, in dem ein Apostroph steckt.
        return wert.replace("'", "''")

    VERKNUEPFUNG.parent.mkdir(parents=True, exist_ok=True)
    erfolg = _powershell(
        "$w = New-Object -ComObject WScript.Shell; "
        f"$s = $w.CreateShortcut('{hochkomma(str(VERKNUEPFUNG))}'); "
        f"$s.TargetPath = '{hochkomma(ziel)}'; "
        f"$s.Arguments = '{hochkomma(argumente)}'; "
        f"$s.WorkingDirectory = '{hochkomma(ordner)}'; "
        "$s.Description = 'FaxFinity Hintergrunddienst'; "
        "$s.Save()"
    )
    return erfolg and eingerichtet()


def entfernen() -> bool:
    try:
        VERKNUEPFUNG.unlink(missing_ok=True)
    except OSError as fehler:
        logger.error("Autostart ließ sich nicht entfernen: %s", fehler)
        return False
    return True


def setzen(aktiv: bool) -> bool:
    return einrichten() if aktiv else entfernen()
