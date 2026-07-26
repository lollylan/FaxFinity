"""PDF einlesen: Textebene prüfen, Seiten als Bild in sinnvoller Auflösung rendern.

Wichtig für Faxe: die Vorgängerversion hat stur mit 300 dpi gerendert. Ein Fax
kommt aber mit 1728 px Breite an (~204 dpi horizontal), oft mit halbierter
vertikaler Auflösung ("standard mode", 1728x1128 statt 1728x2330). Stures
Hochrechnen interpoliert nur, kostet Zeit und bringt kein einziges Zeichen mehr.

Hier wird stattdessen die native Auflösung des eingebetteten Bildes ermittelt und
die Seite genau so gerendert -- dadurch wird nebenbei die vertikale Stauchung
korrekt ausgeglichen, weil das PDF die Bildhöhe auf die Seitenhöhe streckt.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)

# Tesseract arbeitet am besten bei etwa 300 dpi. Unterhalb dieser Grenze wird
# hochskaliert, weil die Zeichenhöhe eines Fax sonst zu gering ist.
ZIEL_DPI = 300
MIN_DPI = 150
MAX_DPI = 400

# Unterhalb dieser Zeichenzahl gilt eine Textebene als nicht brauchbar
# (z.B. PDFs, die nur "Seite 1 von 2" als echten Text enthalten).
MIN_ZEICHEN_TEXTEBENE = 120


def seitenzahl(pdf: Path) -> int:
    with fitz.open(pdf) as doc:
        return doc.page_count


def textebene(pdf: Path, max_seiten: int) -> list[str]:
    """Eingebetteten Text je Seite lesen. Leere Liste, wenn nichts Brauchbares da ist.

    Am PC erzeugte Fax-PDFs (Praxissoftware, Word-Ausdruck als Fax) bringen den
    Text mit -- der ist fehlerfrei und jeder OCR überlegen.
    """
    seiten: list[str] = []
    with fitz.open(pdf) as doc:
        for nr in range(min(doc.page_count, max_seiten)):
            seiten.append(doc[nr].get_text("text").strip())

    gesamt = sum(len(s) for s in seiten)
    if gesamt < MIN_ZEICHEN_TEXTEBENE:
        return []
    return seiten


def _native_dpi(doc: fitz.Document, seite: fitz.Page) -> float:
    """Auflösung schätzen, mit der die Seite tatsächlich vorliegt.

    Grundlage ist die Breite des größten eingebetteten Bildes im Verhältnis zur
    Seitenbreite in Zoll. Die Höhe wird bewusst ignoriert: bei Faxen im
    Standardmodus ist sie halbiert, und genau die soll das Rendern korrigieren.
    """
    breite_zoll = seite.rect.width / 72.0
    if breite_zoll <= 0:
        return ZIEL_DPI

    pixelbreiten = []
    for bild in seite.get_images(full=True):
        try:
            info = doc.extract_image(bild[0])
        except Exception:  # beschädigtes Bildobjekt
            continue
        pixelbreiten.append(info["width"])

    if not pixelbreiten:
        return ZIEL_DPI  # reines Vektor-/Text-PDF

    return max(pixelbreiten) / breite_zoll


def seitenbilder(pdf: Path, max_seiten: int) -> list[Image.Image]:
    """Die ersten `max_seiten` Seiten als Graustufenbilder rendern."""
    bilder: list[Image.Image] = []

    with fitz.open(pdf) as doc:
        if doc.page_count == 0:
            raise ValueError("PDF enthält keine Seiten")

        for nr in range(min(doc.page_count, max_seiten)):
            seite = doc[nr]
            nativ = _native_dpi(doc, seite)

            # Ein Fax mit ~200 dpi wird auf 400 dpi verdoppelt (ganzzahlig, das
            # hält die Kanten sauber). Ein 300-dpi-Scan bleibt wie er ist.
            faktor = max(1, round(ZIEL_DPI / nativ)) if nativ > 0 else 1
            dpi = min(MAX_DPI, max(MIN_DPI, nativ * faktor))

            pix = seite.get_pixmap(dpi=round(dpi), colorspace=fitz.csGRAY)
            bild = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            bilder.append(bild)
            logger.debug(
                "Seite %d: nativ ~%.0f dpi, gerendert mit %.0f dpi (%dx%d)",
                nr + 1, nativ, dpi, bild.width, bild.height,
            )

    return bilder
