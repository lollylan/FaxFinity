"""Verarbeitungskette für ein einzelnes Fax.

Reihenfolge ist Absicht: gesichert wird als Allererstes, ausgewertet danach.
Was auch immer in der Auswertung schiefgeht -- die unveränderte Kopie liegt
bereits im Archiv.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from . import benennung, faxkopf, journal, pdfquelle
from . import bild as bildhilfe
from .config import Einstellungen
from .llm import Ollama, OllamaFehler
from .models import (
    Analyse,
    Dokumenttext,
    Ergebnis,
    Faxkopf,
    Quelle,
    Seiteninhalt,
    Verarbeitung,
)
from .ocr import OcrNichtVerfuegbar, Tesseract
from .praxis import Praxisabgleich

logger = logging.getLogger(__name__)

# Unterhalb dieser Zeichenzahl ist die Texterkennung gescheitert -- ein leeres
# Deckblatt oder ein unleserliches Fax.
MIN_ZEICHEN = 60


class VoruebergehenderFehler(RuntimeError):
    """Ollama nicht erreichbar o.ä. -- die Datei bleibt liegen und wird erneut versucht."""


class Verarbeiter:
    def __init__(self, einstellungen: Einstellungen, protokoll: journal.Journal):
        self.einstellungen = einstellungen
        self.journal = protokoll
        self.abgleich = Praxisabgleich(
            einstellungen.praxis_name,
            einstellungen.praxis_strasse,
            einstellungen.praxis_faxnummer,
        )
        self.ollama = Ollama(
            url=einstellungen.ollama_url,
            modell=einstellungen.ollama_modell,
            timeout=einstellungen.ollama_timeout,
            num_ctx=einstellungen.ollama_num_ctx,
            keep_alive=einstellungen.ollama_keep_alive,
            denkmodus=einstellungen.ollama_denkmodus,
        )
        try:
            self.tesseract: Tesseract | None = Tesseract(
                einstellungen.tesseract_pfad,
                einstellungen.ocr_sprache,
                einstellungen.ocr_sprachdaten,
            )
        except OcrNichtVerfuegbar as fehler:
            logger.warning("%s -- gescannte Faxe können nicht gelesen werden", fehler)
            self.tesseract = None

    # ── Öffentlicher Einstiegspunkt ───────────────────────────────────────
    def verarbeiten(self, pdf: Path) -> Verarbeitung:
        beginn = datetime.now()
        streuwert = journal.sha256(pdf)
        ergebnis = journal.neue_verarbeitung(pdf, streuwert)

        try:
            if self.journal.schon_verarbeitet(streuwert):
                # Inhaltlich identisches Fax kam schon einmal an. Trotzdem
                # archivieren und ablegen, damit nichts unbemerkt verschwindet --
                # eine erneut geschickte Rezeptanforderung will die MFA sehen.
                ergebnis.archivdatei = self._archivieren(pdf, beginn).name
                frueher = self.journal.frueherer_zielname(streuwert)
                ergebnis.zieldatei = self._ablegen(
                    pdf, frueher or benennung.notnagelname(beginn)
                ).name
                ergebnis.ergebnis = Ergebnis.DUPLIKAT
                ergebnis.meldung = "Inhaltsgleiches Fax wurde bereits verarbeitet"
                return ergebnis

            ergebnis.archivdatei = self._archivieren(pdf, beginn).name

            dokument = self._text_gewinnen(pdf)
            kopf = faxkopf.auslesen(dokument.text)
            analyse = self._analysieren(dokument, kopf)

            ergebnis.analyse = analyse
            name = benennung.dateiname(
                analyse,
                beginn,
                self.einstellungen.umlaute_umschreiben,
                self.einstellungen.max_dateiname_laenge,
            )
            ergebnis.zieldatei = self._ablegen(pdf, name).name
            ergebnis.ergebnis = (
                Ergebnis.ERFOLG if analyse.ist_verwertbar else Ergebnis.UNSICHER
            )

        except VoruebergehenderFehler as fehler:
            # Datei bleibt im Eingang liegen und wird beim nächsten Lauf erneut
            # versucht. Nichts wird verschoben.
            ergebnis.ergebnis = Ergebnis.FEHLER
            ergebnis.meldung = str(fehler)
            raise

        except Exception as fehler:  # noqa: BLE001 -- kein Fax darf hängenbleiben
            logger.exception("Verarbeitung von %s fehlgeschlagen", pdf.name)
            ergebnis.ergebnis = Ergebnis.FEHLER
            ergebnis.meldung = str(fehler)
            try:
                ergebnis.zieldatei = self._ablegen(pdf, benennung.notnagelname(beginn)).name
            except OSError as verschiebefehler:
                ergebnis.meldung += f" | Ablegen fehlgeschlagen: {verschiebefehler}"

        finally:
            ergebnis.dauer_sekunden = (datetime.now() - beginn).total_seconds()

        return ergebnis

    def notablage(self, pdf: Path, grund: str) -> Verarbeitung:
        """Fax mit Notnagelnamen ablegen, nachdem alle Versuche gescheitert sind.

        Damit bleibt kein Fax dauerhaft im Eingang liegen -- es wird abgelegt und
        die MFA sieht es beim Durchsehen, auch wenn niemand es benennen konnte.
        """
        jetzt = datetime.now()
        streuwert = journal.sha256(pdf)
        ergebnis = journal.neue_verarbeitung(pdf, streuwert)
        ergebnis.meldung = f"Nach mehreren Versuchen aufgegeben: {grund}"
        ergebnis.ergebnis = Ergebnis.FEHLER
        try:
            ergebnis.archivdatei = self._archivieren(pdf, jetzt).name
            ergebnis.zieldatei = self._ablegen(pdf, benennung.notnagelname(jetzt)).name
        except OSError as fehler:
            ergebnis.meldung += f" | Ablegen fehlgeschlagen: {fehler}"
        return ergebnis

    # ── Dateioperationen ──────────────────────────────────────────────────
    def _archivieren(self, pdf: Path, zeitpunkt: datetime) -> Path:
        """Unveränderte Sicherungskopie anlegen. Muss vor allem anderen laufen."""
        self.einstellungen.ordner_anlegen()
        ziel = benennung.freier_pfad(
            self.einstellungen.archiv, f"{zeitpunkt:%Y-%m-%d_%H%M%S}_{pdf.name}"
        )
        shutil.copy2(pdf, ziel)
        if ziel.stat().st_size != pdf.stat().st_size:
            raise OSError(f"Sicherungskopie unvollständig: {ziel.name}")
        logger.debug("Archiviert: %s", ziel.name)
        return ziel

    def _ablegen(self, pdf: Path, name: str) -> Path:
        """Datei in den Zielordner verschieben und den Erfolg nachprüfen."""
        self.einstellungen.ordner_anlegen()
        ziel = benennung.freier_pfad(self.einstellungen.ziel, name)
        groesse = pdf.stat().st_size
        shutil.move(str(pdf), str(ziel))
        if not ziel.exists() or ziel.stat().st_size != groesse:
            raise OSError(f"Verschieben nach {ziel.name} nicht bestätigt")
        logger.info("Abgelegt: %s", ziel.name)
        return ziel

    # ── Texterkennung ─────────────────────────────────────────────────────
    def _text_gewinnen(self, pdf: Path) -> Dokumenttext:
        """Text der ersten Seiten beschaffen -- vorhandene Textebene bevorzugt."""
        max_seiten = max(1, self.einstellungen.max_seiten)

        eingebettet = pdfquelle.textebene(pdf, max_seiten)
        if eingebettet:
            logger.debug("%s bringt eine Textebene mit, keine OCR nötig", pdf.name)
            return Dokumenttext(
                seiten=[
                    Seiteninhalt(seite=nr + 1, text=text, quelle=Quelle.TEXTEBENE)
                    for nr, text in enumerate(eingebettet)
                ]
            )

        if not self.tesseract:
            raise RuntimeError(
                "Fax enthält keinen Text und Tesseract ist nicht verfügbar"
            )

        dokument = Dokumenttext()
        for nr, rohbild in enumerate(pdfquelle.seitenbilder(pdf, max_seiten), start=1):
            aufbereitet, _ = bildhilfe.aufbereiten(rohbild)
            erkannt = self.tesseract.lesen_mit_ausrichtung(aufbereitet)
            dokument.seiten.append(
                Seiteninhalt(
                    seite=nr,
                    text=erkannt.text,
                    quelle=Quelle.OCR,
                    ocr_konfidenz=erkannt.konfidenz,
                    drehung=erkannt.drehung,
                )
            )
        return dokument

    # ── Auswertung ────────────────────────────────────────────────────────
    def _analysieren(self, dokument: Dokumenttext, kopf: Faxkopf) -> Analyse:
        if dokument.zeichen < MIN_ZEICHEN:
            return self._nur_aus_faxkopf(kopf, "Zu wenig lesbarer Text erkannt")

        # Erster Durchgang ohne Denkmodus: wenige Sekunden, reicht für den
        # Großteil der Post.
        analyse = self._befragen(dokument, kopf, denken=False)

        if self.einstellungen.ollama_denkmodus and self._schwach(analyse):
            logger.info("Erkennung dürftig -- zweiter Durchgang mit Denkmodus")
            gruendlich = self._befragen(dokument, kopf, denken=True)
            if self._besser(gruendlich, analyse):
                gruendlich.hinweise.append("Im gründlichen Durchgang erkannt")
                analyse = gruendlich

        if dokument.konfidenz is not None and dokument.konfidenz < 60:
            analyse.sicherheit = "niedrig"
            analyse.hinweise.append(
                f"Texterkennung unsicher ({dokument.konfidenz:.0f}%)"
            )
        return analyse

    def _befragen(self, dokument: Dokumenttext, kopf: Faxkopf, denken: bool) -> Analyse:
        try:
            analyse = self.ollama.auswerten(
                dokument.text,
                kopf,
                self.einstellungen.praxis_name,
                self.einstellungen.gueltige_kategorien,
                denken=denken,
            )
        except OllamaFehler as fehler:
            raise VoruebergehenderFehler(str(fehler)) from fehler

        self._absender_pruefen(analyse, kopf)
        self._patient_pruefen(analyse)
        return analyse

    @staticmethod
    def _schwach(analyse: Analyse) -> bool:
        """Lohnt sich ein zweiter, gründlicher Durchgang?

        Drei Anzeichen dafür, dass der schnelle Durchgang danebenlag: kein
        Absender, das Auffangbecken 'Sonstiges' als Kategorie, oder der
        Praxisfilter musste eingreifen -- dann hat das Modell Absender und
        Empfänger verwechselt und liegt vermutlich auch sonst daneben.
        """
        return (
            not analyse.absender_kurz
            or analyse.kategorie == "Sonstiges"
            or bool(analyse.hinweise)
        )

    @staticmethod
    def _besser(neu: Analyse, alt: Analyse) -> bool:
        if not neu.ist_verwertbar:
            return False
        if not alt.ist_verwertbar:
            return True
        # Ein Ergebnis ohne Eingriff des Praxisfilters und mit konkreter
        # Kategorie schlägt eines mit Beanstandungen.
        punkte = lambda a: (  # noqa: E731
            bool(a.absender_kurz) + bool(a.patient_nachname)
            + (a.kategorie != "Sonstiges") - len(a.hinweise)
        )
        return punkte(neu) > punkte(alt)

    def _absender_pruefen(self, analyse: Analyse, kopf: Faxkopf) -> None:
        """Verhindern, dass die eigene Praxis als Absender im Dateinamen landet."""
        if not self.abgleich.ist_eigene_praxis(analyse.absender_kurz):
            return

        logger.info(
            "Erkannter Absender '%s' ist die eigene Praxis -- verworfen",
            analyse.absender_kurz,
        )
        analyse.hinweise.append(
            f"Absender '{analyse.absender_kurz}' war die eigene Praxis"
        )

        # Die Kopfzeile des sendenden Geräts als Ersatz, sofern sie nicht
        # ebenfalls auf die eigene Praxis zeigt.
        if kopf.absender and not self.abgleich.ist_eigene_praxis(kopf.absender):
            analyse.absender = kopf.absender
            analyse.absender_kurz = kopf.absender
            analyse.quelle = Quelle.FAXKOPF
        else:
            analyse.absender = ""
            analyse.absender_kurz = ""
        analyse.sicherheit = "niedrig"

    def _patient_pruefen(self, analyse: Analyse) -> None:
        """Den eigenen Namen nicht als Patient übernehmen.

        Geprüft wird der zusammengesetzte Name: Modelle legen den vollständigen
        Namen gelegentlich komplett ins Vornamensfeld, ein Test allein auf den
        Nachnamen ginge dann ins Leere.
        """
        if analyse.patient and self.abgleich.ist_eigene_praxis(analyse.patient):
            analyse.hinweise.append(
                f"Patient '{analyse.patient}' war die eigene Praxis"
            )
            analyse.patient_nachname = ""
            analyse.patient_vorname = ""

    def _nur_aus_faxkopf(self, kopf: Faxkopf, grund: str) -> Analyse:
        """Rückfallebene, wenn kein auswertbarer Text vorliegt."""
        absender = ""
        if kopf.absender and not self.abgleich.ist_eigene_praxis(kopf.absender):
            absender = kopf.absender
        return Analyse(
            kategorie="Sonstiges",
            absender=absender,
            absender_kurz=absender,
            sicherheit="niedrig",
            quelle=Quelle.FAXKOPF if absender else Quelle.FALLBACK,
            hinweise=[grund],
        )
