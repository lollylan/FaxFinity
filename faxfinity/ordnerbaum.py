"""Ordner durchblättern für die Auswahl in der Oberfläche.

Bewusst über die Schnittstelle statt über einen Windows-Auswahldialog: der
Dialog würde immer auf dem Rechner aufgehen, auf dem der Dienst läuft. Greift
jemand aus dem Praxisnetz auf die Oberfläche zu, sähe er nichts passieren --
während auf dem Server ein Fenster auf eine Eingabe wartet.
"""

from __future__ import annotations

import os
import string
from pathlib import Path

# Netzlaufwerke, deren Verbindung abgerissen ist, lassen jeden Zugriff in einen
# langen Zeitablauf laufen. Deshalb wird beim Auflisten grosszuegig weggefangen.
MAX_EINTRAEGE = 500


def laufwerke() -> list[str]:
    """Vorhandene Laufwerke, einschließlich verbundener Netzlaufwerke."""
    if hasattr(os, "listdrives"):  # ab Python 3.12
        try:
            return sorted(os.listdrives())
        except OSError:
            pass
    gefunden = []
    for buchstabe in string.ascii_uppercase:
        pfad = f"{buchstabe}:\\"
        try:
            if os.path.exists(pfad):
                gefunden.append(pfad)
        except OSError:
            continue
    return gefunden


def _lesbar(pfad: Path) -> bool:
    try:
        return pfad.is_dir()
    except OSError:  # etwa ein abgerissenes Netzlaufwerk
        return False


def auflisten(rohpfad: str = "") -> dict:
    """Unterordner eines Pfads auflisten.

    Ohne Pfad werden die Laufwerke und ein paar naheliegende Startpunkte
    zurückgegeben.
    """
    if not rohpfad.strip():
        return {
            "pfad": "",
            "eltern": None,
            "laufwerke": laufwerke(),
            "unterordner": _startpunkte(),
            "fehler": "",
        }

    pfad = Path(rohpfad.strip())
    if not _lesbar(pfad):
        return {
            "pfad": str(pfad),
            "eltern": str(pfad.parent) if pfad.parent != pfad else None,
            "laufwerke": laufwerke(),
            "unterordner": [],
            "fehler": f"Ordner nicht lesbar: {pfad}",
        }

    unterordner = []
    try:
        for eintrag in sorted(pfad.iterdir(), key=lambda e: e.name.lower()):
            if len(unterordner) >= MAX_EINTRAEGE:
                break
            try:
                if eintrag.is_dir() and not eintrag.name.startswith("$"):
                    unterordner.append({"name": eintrag.name, "pfad": str(eintrag)})
            except OSError:
                continue
    except OSError as fehler:
        return {
            "pfad": str(pfad),
            "eltern": str(pfad.parent) if pfad.parent != pfad else None,
            "laufwerke": laufwerke(),
            "unterordner": [],
            "fehler": f"Ordner nicht lesbar: {fehler}",
        }

    return {
        "pfad": str(pfad),
        "eltern": str(pfad.parent) if pfad.parent != pfad else None,
        "laufwerke": laufwerke(),
        "unterordner": unterordner,
        "fehler": "",
    }


def _startpunkte() -> list[dict]:
    """Orte, an denen die Suche üblicherweise beginnt."""
    kandidaten = [
        (Path.home() / "Documents", "Dokumente"),
        (Path.home() / "Desktop", "Desktop"),
        (Path.home(), "Benutzerordner"),
    ]
    return [
        {"name": beschriftung, "pfad": str(pfad)}
        for pfad, beschriftung in kandidaten
        if _lesbar(pfad)
    ]
