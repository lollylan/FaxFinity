"""Aus einer Analyse einen Dateinamen bauen.

Schema:  Kategorie_[Fachrichtung]_Absender_Patient_Eingangsdatum.pdf

Innerhalb eines Bestandteils werden Leerzeichen zu Bindestrichen, zwischen den
Bestandteilen steht der Unterstrich. Dadurch bleibt ablesbar, wo der Absender
aufhört und der Patient anfängt -- in der Vorgängerversion lief beides zu einer
Unterstrichkette zusammen.

Das Datum ist bewusst das Eingangsdatum und nicht das Dokumentdatum: die Uhren
sendender Faxgeräte gehen oft falsch (in echten Faxen hier steht "02/01/2002").
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .config import KATEGORIEN_OHNE_PATIENT
from .models import Analyse

# Unter Windows verbotene Zeichen sowie Steuerzeichen.
VERBOTEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Gerätenamen, die Windows auch mit Endung nicht als Datei zulässt.
RESERVIERT = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

UMSCHRIFT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})

MAX_BESTANDTEIL = 40
NOTNAGEL_PRAEFIX = "FAX"

# Nur diese Zeichen dürfen in einem Bestandteil stehen. Die Texterkennung liefert
# regelmäßig typografische Anführungszeichen und Kommas mit, die vorher
# ungefiltert im Dateinamen landeten ('Seniorenresidenz”,-312,-“Abendsonne”').
NICHT_ERLAUBT = re.compile(r"[^\wÄÖÜäöüß.\-]+", re.UNICODE)

# Bindewörter, die nach dem Kürzen nicht am Ende stehen bleiben dürfen.
HAENGENDE_WOERTER = {
    "und", "oder", "für", "fuer", "der", "die", "das", "des", "dem", "den",
    "am", "an", "im", "in", "zu", "zur", "zum", "von", "vom", "mit", "bei",
    "e", "e.", "gmbh", "ggmbh", "kg", "ag", "mbh",
}


def _bestandteil(text: str, umschreiben: bool, grenze: int = MAX_BESTANDTEIL) -> str:
    """Einen einzelnen Namensbestandteil säubern und auf Länge bringen."""
    if not text:
        return ""
    if umschreiben:
        text = text.translate(UMSCHRIFT)
    text = VERBOTEN.sub(" ", text)
    text = NICHT_ERLAUBT.sub(" ", text)
    text = re.sub(r"[_\s]+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text)
    # Punktfolgen und Punkt-Bindestrich-Paare zusammenziehen ("Dr..Musterfirma").
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\.-|-\.", ".", text).strip("-.")

    if len(text) > grenze:
        # An einer Wortgrenze kürzen, sonst hart abschneiden.
        gekuerzt = text[:grenze].rsplit("-", 1)[0]
        text = gekuerzt if len(gekuerzt) >= grenze // 2 else text[:grenze]

    return _ohne_haengendes_bindewort(text.strip("-."))


def _ohne_haengendes_bindewort(text: str) -> str:
    """'Innere-Medizin-und' zu 'Innere-Medizin' machen."""
    woerter = text.split("-")
    while len(woerter) > 1 and woerter[-1].lower() in HAENGENDE_WOERTER:
        woerter.pop()
    return "-".join(woerter).strip("-.")


def notnagelname(zeitpunkt: datetime) -> str:
    """Name für Faxe, bei denen die Erkennung nichts Brauchbares ergeben hat."""
    return f"{NOTNAGEL_PRAEFIX}_{zeitpunkt:%Y-%m-%d_%H%M%S}.pdf"


def dateiname(
    analyse: Analyse,
    eingang_am: datetime,
    umlaute_umschreiben: bool = False,
    max_laenge: int = 120,
) -> str:
    """Dateinamen aus der Analyse erzeugen."""
    if not analyse.ist_verwertbar:
        return notnagelname(eingang_am)

    teile = [_bestandteil(analyse.kategorie, umlaute_umschreiben, 30) or "Sonstiges"]

    # Die Fachrichtung ist nur beim Arztbrief eine echte Hilfe beim Einsortieren.
    if analyse.kategorie == "Arztbrief" and analyse.fachrichtung:
        teile.append(_bestandteil(analyse.fachrichtung, umlaute_umschreiben, 25))

    absender = _bestandteil(analyse.absender_kurz, umlaute_umschreiben)
    if absender:
        teile.append(absender)

    if analyse.kategorie not in KATEGORIEN_OHNE_PATIENT:
        patient = _bestandteil(
            " ".join(t for t in (analyse.patient_nachname, analyse.patient_vorname) if t),
            umlaute_umschreiben,
        )
        if patient:
            teile.append(patient)

    teile.append(f"{eingang_am:%Y-%m-%d}")
    name = "_".join(t for t in teile if t)

    # Notfalls den Absender kürzen -- er ist der längste Bestandteil.
    if len(name) + 4 > max_laenge:
        ueberschuss = len(name) + 4 - max_laenge
        if absender and len(absender) - ueberschuss >= 8:
            teile[teile.index(absender)] = _bestandteil(
                absender, umlaute_umschreiben, len(absender) - ueberschuss
            )
            name = "_".join(t for t in teile if t)
        else:
            name = name[: max_laenge - 4].rstrip("-_")

    return _windowssicher(name) + ".pdf"


def _windowssicher(name: str) -> str:
    name = name.strip(" .")
    if not name:
        return NOTNAGEL_PRAEFIX
    if name.split(".")[0].lower() in RESERVIERT:
        name = "_" + name
    return name


def freier_pfad(ordner: Path, name: str) -> Path:
    """Pfad zurückgeben, der garantiert noch nicht existiert.

    Nie eine bestehende Datei überschreiben -- ein Fax, das dabei verloren geht,
    fällt niemandem auf.
    """
    ziel = ordner / name
    if not ziel.exists():
        return ziel
    stamm, endung = ziel.stem, ziel.suffix
    for nummer in range(2, 1000):
        kandidat = ordner / f"{stamm}_{nummer}{endung}"
        if not kandidat.exists():
            return kandidat
    # Praktisch unerreichbar, aber besser als eine Endlosschleife.
    return ordner / f"{stamm}_{datetime.now():%H%M%S%f}{endung}"
