"""Hintergrunddienst: überwacht den Eingangsordner und arbeitet ihn ab.

Läuft in einem eigenen Thread und ist damit unabhängig davon, ob jemand die
Weboberfläche geöffnet hat. Die Vorgängerversion hatte die Scanschleife in der
Streamlit-Seite stehen (time.sleep plus rerun): sie lief nur bei geöffnetem
Browser-Tab, und zwei geöffnete Tabs ergaben zwei parallele Scanner. Genau
davon stammen die "Verschiebe-Fehler" im alten Protokoll -- zwei Durchläufe
griffen nach derselben Datei, einer kam zu spät.

Dagegen hilft hier eine Sperrdatei: es läuft immer höchstens ein Dienst.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Einstellungen
from .journal import Journal
from .models import Ergebnis
from .pipeline import Verarbeiter, VoruebergehenderFehler

logger = logging.getLogger(__name__)

# Eine Datei gilt erst als vollständig, wenn sich ihre Größe zwischen zwei
# Blicken nicht mehr ändert. Ein Fax, das gerade übers Netz hereinkopiert wird,
# darf nicht halb verarbeitet werden.
RUHEZEIT_SEKUNDEN = 3.0
# Nach so vielen vergeblichen Anläufen (Ollama aus, Netzlaufwerk weg) wird eine
# Datei nicht mehr endlos erneut versucht, sondern mit Notnagelnamen abgelegt.
MAX_VERSUCHE = 5
PAUSE_ZWISCHEN_DATEIEN = 0.5


@dataclass
class Zustand:
    """Was die Oberfläche über den Dienst wissen will."""

    laeuft: bool = False
    beschaeftigt: bool = False
    aktuelle_datei: str = ""
    letzter_lauf: str = ""
    letzter_fehler: str = ""
    wartende_dateien: int = 0
    verarbeitet_gesamt: int = 0
    naechster_lauf_in: int = 0

    def als_dict(self) -> dict:
        return {
            "laeuft": self.laeuft,
            "beschaeftigt": self.beschaeftigt,
            "aktuelle_datei": self.aktuelle_datei,
            "letzter_lauf": self.letzter_lauf,
            "letzter_fehler": self.letzter_fehler,
            "wartende_dateien": self.wartende_dateien,
            "verarbeitet_gesamt": self.verarbeitet_gesamt,
            "naechster_lauf_in": self.naechster_lauf_in,
        }


class Einzelinstanzsperre:
    """Verhindert, dass zwei Dienste denselben Ordner abarbeiten.

    Gesperrt wird über eine echte Dateisperre des Betriebssystems, nicht über
    das blosse Vorhandensein einer Datei mit Prozessnummer darin. Das hat zwei
    Gründe:

    Erstens gibt das Betriebssystem eine solche Sperre beim Prozessende von
    selbst wieder frei -- auch nach einem Absturz oder Stromausfall. Damit
    entfällt jede Erkennung verwaister Sperren.

    Zweitens gibt es unter Windows keine harmlose Lebendprüfung eines fremden
    Prozesses: `os.kill(pid, 0)` ruft dort `TerminateProcess` auf und beendet
    den geprüften Prozess, statt nur nachzusehen. Eine Sperre, die den
    rechtmässigen Inhaber abschiesst, wäre schlimmer als gar keine.
    """

    def __init__(self, pfad: Path):
        self.pfad = pfad
        self._datei = None

    @staticmethod
    def _sperren(datei) -> None:
        """Exklusiv sperren, ohne zu warten. Wirft OSError, wenn schon belegt."""
        datei.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(datei.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(datei.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _entsperren(datei) -> None:
        datei.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(datei.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(datei.fileno(), fcntl.LOCK_UN)

    def belegen(self) -> bool:
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        datei = os.fdopen(os.open(self.pfad, os.O_CREAT | os.O_RDWR), "r+")
        try:
            self._sperren(datei)
        except OSError:
            datei.close()
            return False

        # Die Prozessnummer dient nur der Fehlersuche, nicht der Sperrlogik.
        datei.seek(0)
        datei.truncate()
        datei.write(f"{os.getpid()}\n")
        datei.flush()
        self._datei = datei
        return True

    def freigeben(self) -> None:
        if self._datei is None:
            return
        try:
            self._entsperren(self._datei)
        except OSError:
            pass
        self._datei.close()
        self._datei = None
        # Die Datei darf liegenbleiben; sie sperrt nichts mehr.
        try:
            self.pfad.unlink(missing_ok=True)
        except OSError:
            pass


class Dienst:
    def __init__(self, einstellungen: Einstellungen, protokoll: Journal, sperre: Path):
        self.einstellungen = einstellungen
        self.journal = protokoll
        self.sperre = Einzelinstanzsperre(sperre)
        self.zustand = Zustand()

        self._thread: threading.Thread | None = None
        self._stoppen = threading.Event()
        self._sofort = threading.Event()
        self._verarbeiter: Verarbeiter | None = None
        self._versuche: dict[str, int] = {}

    # ── Steuerung ─────────────────────────────────────────────────────────
    def starten(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        if not self.sperre.belegen():
            self.zustand.letzter_fehler = (
                "Ein anderer FaxFinity-Dienst läuft bereits für diesen Ordner"
            )
            logger.error(self.zustand.letzter_fehler)
            return False

        self._stoppen.clear()
        self._thread = threading.Thread(target=self._schleife, name="faxfinity", daemon=True)
        self._thread.start()
        self.zustand.laeuft = True
        logger.info("Dienst gestartet")
        return True

    def stoppen(self) -> None:
        self._stoppen.set()
        self._sofort.set()
        if self._thread:
            self._thread.join(timeout=30)
        self.sperre.freigeben()
        self.zustand.laeuft = False
        logger.info("Dienst beendet")

    def jetzt_pruefen(self) -> None:
        """Den Wartetakt überspringen und sofort nachsehen."""
        self._sofort.set()

    def einstellungen_uebernehmen(self, neue: Einstellungen) -> None:
        self.einstellungen = neue
        self._verarbeiter = None  # beim nächsten Lauf mit neuen Werten aufbauen
        self._sofort.set()

    # ── Schleife ──────────────────────────────────────────────────────────
    def _schleife(self) -> None:
        while not self._stoppen.is_set():
            try:
                meldung = self.einstellungen.ordner_beanstanden()
                if meldung:
                    # Nur bei Änderung melden, sonst läuft das Protokoll voll.
                    if self.zustand.letzter_fehler != meldung:
                        logger.warning("%s -- es wird nichts verarbeitet", meldung)
                    self.zustand.letzter_fehler = meldung
                elif self.einstellungen.auto_scan:
                    self.zustand.letzter_fehler = ""
                    self._durchlauf()
            except Exception as fehler:  # noqa: BLE001 -- der Dienst darf nie sterben
                logger.exception("Unerwarteter Fehler im Dienst")
                self.zustand.letzter_fehler = str(fehler)

            takt = max(5, self.einstellungen.scan_intervall)
            self.zustand.naechster_lauf_in = takt
            self._sofort.wait(timeout=takt)
            self._sofort.clear()

    def _durchlauf(self) -> None:
        offen = self._bereite_dateien()
        self.zustand.wartende_dateien = len(offen)
        if not offen:
            self.zustand.letzter_lauf = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return

        logger.info("%d Fax(e) im Eingang", len(offen))
        verarbeiter = self._verarbeiter_holen()

        for pdf in offen:
            if self._stoppen.is_set():
                break
            self.zustand.beschaeftigt = True
            self.zustand.aktuelle_datei = pdf.name
            try:
                self._eine_datei(pdf, verarbeiter)
            finally:
                self.zustand.beschaeftigt = False
                self.zustand.aktuelle_datei = ""
            time.sleep(PAUSE_ZWISCHEN_DATEIEN)

        self.zustand.letzter_lauf = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.zustand.wartende_dateien = len(self._bereite_dateien())

    def _eine_datei(self, pdf: Path, verarbeiter: Verarbeiter) -> None:
        try:
            ergebnis = verarbeiter.verarbeiten(pdf)
        except VoruebergehenderFehler as fehler:
            versuche = self._versuche.get(pdf.name, 0) + 1
            self._versuche[pdf.name] = versuche
            self.zustand.letzter_fehler = f"{pdf.name}: {fehler}"

            if versuche < MAX_VERSUCHE:
                # Datei bleibt liegen und wird beim nächsten Takt erneut versucht.
                logger.warning(
                    "%s: %s -- Versuch %d von %d", pdf.name, fehler, versuche, MAX_VERSUCHE
                )
                return

            logger.error(
                "%s nach %d Versuchen aufgegeben, wird mit Notnagelnamen abgelegt",
                pdf.name, versuche,
            )
            ergebnis = verarbeiter.notablage(pdf, str(fehler))

        self._versuche.pop(pdf.name, None)
        self.journal.eintragen(ergebnis)
        self.zustand.verarbeitet_gesamt += 1
        if ergebnis.ergebnis is Ergebnis.FEHLER:
            self.zustand.letzter_fehler = f"{pdf.name}: {ergebnis.meldung}"

    # ── Hilfen ────────────────────────────────────────────────────────────
    def _verarbeiter_holen(self) -> Verarbeiter:
        if self._verarbeiter is None:
            self._verarbeiter = Verarbeiter(self.einstellungen, self.journal)
        return self._verarbeiter

    def _bereite_dateien(self) -> list[Path]:
        """PDFs im Eingang, die vollständig geschrieben sind.

        Unterordner bleiben außen vor -- dort liegen Archiv und Ablage.
        """
        eingang = self.einstellungen.eingang
        if not eingang.is_dir():
            return []

        fertig = []
        for eintrag in sorted(eingang.glob("*.pdf")):
            if not eintrag.is_file():
                continue
            try:
                erst = eintrag.stat()
                if time.time() - erst.st_mtime < RUHEZEIT_SEKUNDEN:
                    continue  # wird vermutlich gerade noch geschrieben
                if erst.st_size == 0:
                    continue
            except OSError:
                continue
            fertig.append(eintrag)
        return fertig
