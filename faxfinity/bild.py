"""Bildaufbereitung vor der Texterkennung.

Faxe kommen schief eingezogen, kontrastarm und nicht selten kopfüber an. Was
hier passiert, ist billig gerechnet und hebt die OCR-Trefferquote deutlich --
deutlich mehr als jede Erhöhung der Auflösung.
"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Suchbereich für die Schieflage. Mehr als ein paar Grad zieht kein Faxgerät
# schief ein; größere Abweichungen sind echte Drehungen und Sache der OSD.
MAX_SCHRAEGE_GRAD = 4.0
SCHRITT_GRAD = 0.25
# Für die Schätzung reicht ein kleines Bild -- spart ein Vielfaches an Rechenzeit.
ANALYSE_BREITE = 800


def graustufen(bild: Image.Image) -> Image.Image:
    return bild if bild.mode == "L" else bild.convert("L")


def _projektionsschaerfe(maske: np.ndarray) -> float:
    """Kennzahl dafür, wie sauber Textzeilen waagerecht liegen.

    Bei geradem Text hat die zeilenweise Summe der Vordergrundpixel starke
    Ausschläge (Zeile / Zwischenraum). Bei schiefem Text verschmiert das.
    Die Summe der quadrierten Differenzen benachbarter Zeilen misst genau das.
    """
    profil = maske.sum(axis=1, dtype=np.float64)
    return float(np.square(np.diff(profil)).sum())


def schraege_schaetzen(bild: Image.Image) -> float:
    """Schieflage in Grad schätzen (positiv = gegen den Uhrzeigersinn drehen)."""
    klein = graustufen(bild)
    if klein.width > ANALYSE_BREITE:
        hoehe = round(klein.height * ANALYSE_BREITE / klein.width)
        klein = klein.resize((ANALYSE_BREITE, max(1, hoehe)), Image.BILINEAR)

    daten = np.asarray(klein, dtype=np.uint8)
    # Otsu-artige Trennung genügt hier nicht -- Faxe sind bereits bitonal.
    # Der Mittelwert trennt Vorder- von Hintergrund robust genug.
    schwelle = daten.mean()
    maske = (daten < schwelle).astype(np.uint8)

    if maske.sum() < 50:  # praktisch leere Seite
        return 0.0

    winkel = np.arange(-MAX_SCHRAEGE_GRAD, MAX_SCHRAEGE_GRAD + SCHRITT_GRAD, SCHRITT_GRAD)
    bester_winkel, bester_wert = 0.0, -1.0

    for w in winkel:
        if w == 0.0:
            gedreht = maske
        else:
            gedreht = np.asarray(
                Image.fromarray(maske * 255).rotate(
                    w, resample=Image.BILINEAR, fillcolor=0
                ),
                dtype=np.uint8,
            ) > 127
            gedreht = gedreht.astype(np.uint8)

        wert = _projektionsschaerfe(gedreht)
        if wert > bester_wert:
            bester_wert, bester_winkel = wert, float(w)

    return bester_winkel


def geraderichten(bild: Image.Image) -> tuple[Image.Image, float]:
    """Schieflage korrigieren. Gibt das Bild und den angewandten Winkel zurück."""
    winkel = schraege_schaetzen(bild)
    if abs(winkel) < 0.3:  # unter einem Drittel Grad lohnt das Drehen nicht
        return bild, 0.0
    gedreht = bild.rotate(winkel, resample=Image.BICUBIC, expand=True, fillcolor=255)
    logger.debug("Schieflage korrigiert: %.2f Grad", winkel)
    return gedreht, winkel


def drehen(bild: Image.Image, grad: int) -> Image.Image:
    """Um ein Vielfaches von 90 Grad drehen (verlustfrei)."""
    grad = grad % 360
    if grad == 0:
        return bild
    if grad == 90:
        return bild.transpose(Image.ROTATE_90)
    if grad == 180:
        return bild.transpose(Image.ROTATE_180)
    if grad == 270:
        return bild.transpose(Image.ROTATE_270)
    return bild.rotate(-grad, resample=Image.BICUBIC, expand=True, fillcolor=255)


def kontrast_anheben(bild: Image.Image) -> Image.Image:
    """Grauwerte spreizen. Hilft blassen Thermo- und Mehrfachkopie-Faxen."""
    grau = graustufen(bild)
    daten = np.asarray(grau)
    if daten.size == 0:
        return grau
    # Bitonale Faxe haben bereits vollen Kontrast -- dann nichts anfassen.
    if len(np.unique(daten)) <= 4:
        return grau
    return ImageOps.autocontrast(grau, cutoff=1)


def aufbereiten(bild: Image.Image) -> tuple[Image.Image, float]:
    """Vollständige Aufbereitung einer Seite für die Texterkennung."""
    fertig = kontrast_anheben(bild)
    fertig, winkel = geraderichten(fertig)
    return fertig, winkel
