"""Texterkennung per Tesseract.

Tesseract wird direkt als Prozess aufgerufen statt über pytesseract -- das spart
eine Abhängigkeit und macht das Verhalten bei Fehlern nachvollziehbar.

Die Ausrichtungserkennung ist der Grund, warum hier Tesseract und kein reines
Vision-Modell steht: kopfüber eingelegte Faxe sind bei uns Alltag, und
Tesseracts OSD ("orientation and script detection") erkennt das in einem
einzigen billigen Durchlauf.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import bild as bildhilfe

logger = logging.getLogger(__name__)

SUCHPFADE = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%USERPROFILE%\AppData\Local\Tesseract-OCR\tesseract.exe"),
]

# Unterhalb dieser OSD-Konfidenz ist die Ausrichtungsangabe wertlos; dann wird
# der teurere, aber verlässliche Vergleich 0 Grad gegen 180 Grad gefahren.
MIN_OSD_KONFIDENZ = 1.5
ZEITLIMIT = 120


class OcrNichtVerfuegbar(RuntimeError):
    pass


@dataclass
class OcrErgebnis:
    text: str
    konfidenz: float
    drehung: int = 0
    woerter: int = 0


def finde_tesseract(vorgabe: str = "") -> str | None:
    """Tesseract lokalisieren: Vorgabe, PATH, dann übliche Installationsorte."""
    if vorgabe and Path(vorgabe).is_file():
        return vorgabe

    imm_pfad = shutil.which("tesseract")
    if imm_pfad:
        return imm_pfad

    # Neben der Anwendung mitgeliefert (portable Variante)
    mitgeliefert = Path(__file__).resolve().parent.parent / "tools" / "tesseract" / "tesseract.exe"
    if mitgeliefert.is_file():
        return str(mitgeliefert)

    for pfad in SUCHPFADE:
        if pfad and Path(pfad).is_file():
            return pfad
    return None


def finde_sprachdaten(vorgabe: str = "") -> str | None:
    """Ordner mit den .traineddata-Dateien suchen.

    Die deutschen Sprachdaten liegen bewusst im Anwendungsordner und nicht unter
    "Program Files": so lässt sich FaxFinity ohne Administratorrechte einrichten,
    und die Installation von Tesseract selbst muss nicht angepasst werden.
    """
    if vorgabe and (Path(vorgabe) / "deu.traineddata").is_file():
        return vorgabe

    wurzel = Path(__file__).resolve().parent.parent
    for kandidat in (wurzel / "tessdata" / "best", wurzel / "tessdata"):
        if (kandidat / "deu.traineddata").is_file():
            return str(kandidat)
    return None  # dann greift Tesseracts eigener Suchpfad


class Tesseract:
    def __init__(self, pfad: str = "", sprache: str = "deu", sprachdaten: str = ""):
        gefunden = finde_tesseract(pfad)
        if not gefunden:
            raise OcrNichtVerfuegbar(
                "Tesseract wurde nicht gefunden. Installation: "
                "winget install UB-Mannheim.TesseractOCR"
            )
        self.pfad = gefunden
        self.sprache = sprache
        self.sprachdaten = finde_sprachdaten(sprachdaten)
        self._sprachen: set[str] | None = None

    # ── Basisinformationen ────────────────────────────────────────────────
    def version(self) -> str:
        ausgabe = self._starten(["--version"])
        return ausgabe.splitlines()[0] if ausgabe else "unbekannt"

    def sprachen(self) -> set[str]:
        if self._sprachen is None:
            zeilen = self._starten(
                ["--list-langs", *self._sprachdaten_argumente]
            ).splitlines()[1:]
            self._sprachen = {z.strip() for z in zeilen if z.strip()}
        return self._sprachen

    @property
    def sprache_verfuegbar(self) -> bool:
        return self.sprache in self.sprachen()

    @property
    def osd_verfuegbar(self) -> bool:
        return "osd" in self.sprachen()

    # ── Erkennung ─────────────────────────────────────────────────────────
    def ausrichtung(self, bild: Image.Image) -> int:
        """Nötige Drehung im Uhrzeigersinn in Grad (0/90/180/270)."""
        if not self.osd_verfuegbar:
            return 0
        try:
            ausgabe = self._auf_bild(bild, ["--psm", "0", "-l", "osd"])
        except subprocess.SubprocessError:
            return 0

        drehung = re.search(r"Rotate:\s*(\d+)", ausgabe)
        konfidenz = re.search(r"Orientation confidence:\s*([\d.]+)", ausgabe)
        if not drehung:
            return 0

        wert = int(drehung.group(1)) % 360
        sicher = float(konfidenz.group(1)) if konfidenz else 0.0
        if wert and sicher < MIN_OSD_KONFIDENZ:
            logger.debug("OSD zu unsicher (%.2f), Drehung %d verworfen", sicher, wert)
            return 0
        return wert

    def lesen(self, bild: Image.Image) -> OcrErgebnis:
        """Reine Texterkennung ohne Ausrichtungslogik."""
        sprache = self.sprache if self.sprache_verfuegbar else "eng"
        # TSV wird über die Konfigurationsvariable angefordert, nicht über den
        # Konfigurationsnamen "tsv": den würde Tesseract als Datei im
        # --tessdata-dir suchen und bei Nichtfinden kommentarlos Klartext
        # ausgeben. Die Variable funktioniert unabhängig davon.
        tsv = self._auf_bild(
            bild, ["-l", sprache, "--psm", "3", "-c", "tessedit_create_tsv=1"]
        )
        return self._tsv_auswerten(tsv)

    def lesen_mit_ausrichtung(self, bild: Image.Image) -> OcrErgebnis:
        """Text erkennen und dabei die Ausrichtung korrigieren.

        Bewusst nicht OSD-zuerst: OSD liegt bei kontrastarmen Faxen daneben und
        meldet dann etwa 270 Grad für eine aufrechte Seite -- das gedrehte Bild
        liefert danach Buchstabensalat statt einer Fehlermeldung.

        Deshalb wird zuerst ungedreht gelesen. Nur wenn dieses Ergebnis schlecht
        aussieht, werden weitere Ausrichtungen probiert und die beste gewinnt.
        Das kostet bei aufrechten Faxen -- also fast allen -- nur einen Durchlauf.
        """
        aufrecht = self.lesen(bild)
        if not self._verdaechtig(aufrecht):
            return aufrecht

        kandidaten = [(0, aufrecht)]
        # Der OSD-Vorschlag zuerst, danach die Gegenprobe kopfüber.
        for grad in dict.fromkeys([self.ausrichtung(bild), 180]):
            if grad == 0:
                continue
            versuch = self.lesen(bildhilfe.drehen(bild, grad))
            versuch.drehung = grad
            kandidaten.append((grad, versuch))

        grad, bestes = max(kandidaten, key=lambda eintrag: self._guete(eintrag[1]))
        if grad:
            logger.info(
                "Fax lag um %d Grad gedreht (Güte %.0f statt %.0f)",
                grad, self._guete(bestes), self._guete(aufrecht),
            )
        bestes.drehung = grad
        return bestes

    # ── Bewertung ─────────────────────────────────────────────────────────
    @staticmethod
    def _guete(ergebnis: OcrErgebnis) -> float:
        """Wie brauchbar ist ein Erkennungsergebnis?

        Wortzahl allein genügt nicht -- gedrehter Text liefert viele Wörter mit
        miserabler Konfidenz. Das Produkt entspricht der Zahl sicher erkannter
        Wörter und trennt beide Fälle zuverlässig.
        """
        return ergebnis.woerter * (ergebnis.konfidenz / 100.0)

    @staticmethod
    def _verdaechtig(ergebnis: OcrErgebnis) -> bool:
        """Sieht das Erkennungsergebnis nach unlesbarem Kauderwelsch aus?"""
        return ergebnis.woerter < 40 or ergebnis.konfidenz < 65

    @staticmethod
    def _tsv_auswerten(tsv: str) -> OcrErgebnis:
        zeilen: dict[tuple, list[str]] = {}
        konfidenzen: list[float] = []

        leser = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
        for eintrag in leser:
            wort = (eintrag.get("text") or "").strip()
            if not wort:
                continue
            try:
                konf = float(eintrag.get("conf", -1))
            except ValueError:
                continue
            if konf < 0:
                continue

            konfidenzen.append(konf)
            schluessel = (
                eintrag.get("block_num"),
                eintrag.get("par_num"),
                eintrag.get("line_num"),
            )
            zeilen.setdefault(schluessel, []).append(wort)

        text = "\n".join(" ".join(w) for w in zeilen.values())
        mittel = sum(konfidenzen) / len(konfidenzen) if konfidenzen else 0.0
        return OcrErgebnis(text=text, konfidenz=mittel, woerter=len(konfidenzen))

    # ── Prozessaufruf ─────────────────────────────────────────────────────
    @property
    def _sprachdaten_argumente(self) -> list[str]:
        return ["--tessdata-dir", self.sprachdaten] if self.sprachdaten else []

    def _starten(self, argumente: list[str]) -> str:
        ergebnis = subprocess.run(
            [self.pfad, *argumente],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ZEITLIMIT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ausgabe = ergebnis.stdout or ergebnis.stderr
        if ergebnis.returncode != 0:
            raise OcrNichtVerfuegbar(
                f"Tesseract meldet Fehler {ergebnis.returncode}: "
                f"{(ergebnis.stderr or ausgabe).strip()[:300]}"
            )
        return ausgabe

    def _auf_bild(self, bild: Image.Image, argumente: list[str]) -> str:
        # Reihenfolge ist zwingend: Tesseract behandelt jedes Argument nach dem
        # ersten Konfigurationsnamen (z.B. "tsv") selbst als Konfigurationsdatei.
        # Optionen, die dahinter stehen, werden kommentarlos verworfen.
        with tempfile.TemporaryDirectory(prefix="faxfinity_") as ordner:
            eingabe = Path(ordner) / "seite.png"
            bildhilfe.graustufen(bild).save(eingabe, format="PNG")
            return self._starten(
                [str(eingabe), "stdout", *self._sprachdaten_argumente, *argumente]
            )
