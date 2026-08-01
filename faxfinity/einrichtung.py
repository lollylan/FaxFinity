"""Voraussetzungen selbst herrichten, statt sie vorauszusetzen.

Dieses Modul gibt es für die EXE-Fassung: dort richtet niemand mehr etwas an
der Eingabeaufforderung ein. Was sich ohne Zutun erledigen lässt, erledigt
FaxFinity beim Start von selbst --

* Ollama starten, falls es installiert ist, aber nicht läuft,
* das Sprachmodell herunterladen, falls keines vorhanden ist.

Was sich nicht ohne Zutun erledigen lässt -- Ollama installieren --, wird in
der Oberfläche in einem Satz erklärt, mit einem Knopf zur Bezugsquelle.

Ollama wird bewusst nicht mitgeliefert: es bringt CUDA-Bibliotheken von über
einem Gigabyte mit und aktualisiert sich selbst. Eine mitgelieferte Kopie wäre
nach wenigen Monaten veraltet.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Einstellungen
from .llm import EMPFOHLENES_MODELL, Ollama, OllamaFehler, passendes_modell

logger = logging.getLogger(__name__)

OLLAMA_BEZUGSQUELLE = "https://ollama.com/download"
TESSERACT_BEZUGSQUELLE = "https://github.com/UB-Mannheim/tesseract/wiki"

# Wo Ollama sich unter Windows einnistet. Die Installation läuft ohne
# Administratorrechte und landet deshalb im Benutzerprofil, nicht in
# "Program Files".
OLLAMA_SUCHPFADE = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Ollama\ollama.exe"),
]

# So lange wird nach dem Starten auf Ollama gewartet. Beim allerersten Start
# lädt es seine Grafikkartenbibliotheken nach und braucht spürbar länger.
WARTEN_AUF_OLLAMA = 40

# Ollamas Zwischenstände sind englisch und technisch. Für die Praxis übersetzt.
PHASEN = {
    "pulling manifest": "Verzeichnis wird abgerufen",
    "verifying sha256 digest": "Wird auf Vollständigkeit geprüft",
    "writing manifest": "Wird abgeschlossen",
    "removing any unused layers": "Wird abgeschlossen",
    "success": "Fertig",
}


def phase_uebersetzen(status: str) -> str:
    """Ollamas Zwischenstand in einen Satz, der in einer Praxis etwas sagt."""
    status = (status or "").strip()
    if status in PHASEN:
        return PHASEN[status]
    # "pulling 2af3b81862c6" und "downloading ..." sind der eigentliche Download.
    if status.startswith(("pulling", "downloading")):
        return "Wird heruntergeladen"
    return status


def benoetigtes_modell(gewuenscht: str, vorhanden: list[str]) -> str:
    """Welches Modell geladen werden muss. Leerer Text heißt: nichts zu tun.

    Ein ausdrücklich eingetragenes Modell wird geholt, wenn es fehlt -- wer in
    den Einstellungen einen Namen einträgt, will genau dieses Modell. Ohne
    Eintrag wird nur dann geladen, wenn überhaupt kein geeignetes da ist: eine
    Praxis, die sich bewusst für gemma3:4b entschieden hat, soll nicht beim
    nächsten Start ungefragt fünf Gigabyte nachladen.
    """
    if gewuenscht.strip():
        gewuenscht = gewuenscht.strip()
        # "qwen3" meint "qwen3:latest" -- sonst gälte ein vorhandenes Modell
        # als fehlend und würde bei jedem Start erneut geholt.
        voll = gewuenscht if ":" in gewuenscht else f"{gewuenscht}:latest"
        return "" if gewuenscht in vorhanden or voll in vorhanden else gewuenscht
    return "" if passendes_modell(vorhanden) else EMPFOHLENES_MODELL


def ollama_programm() -> str:
    """Pfad zu ollama.exe, leer wenn nicht installiert."""
    im_pfad = shutil.which("ollama")
    if im_pfad:
        return im_pfad
    for pfad in OLLAMA_SUCHPFADE:
        if pfad and Path(pfad).is_file():
            return pfad
    return ""


@dataclass
class Ladefortschritt:
    """Stand des Modell-Downloads, so wie die Oberfläche ihn anzeigt."""

    laeuft: bool = False
    modell: str = ""
    phase: str = ""
    fehler: str = ""
    fertig: bool = False
    # Fortschritt je Teilstück (Ollama lädt ein Modell in mehreren Schichten).
    # Nur die Summe ergibt einen Balken, der nicht mehrfach bei null anfängt.
    _teile: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def geladen(self) -> int:
        return sum(geladen for geladen, _ in self._teile.values())

    @property
    def gesamt(self) -> int:
        return sum(gesamt for _, gesamt in self._teile.values())

    @property
    def prozent(self) -> int:
        return round(100 * self.geladen / self.gesamt) if self.gesamt else 0

    def uebernehmen(self, stand: dict) -> None:
        self.phase = phase_uebersetzen(stand.get("status", ""))
        digest = stand.get("digest")
        gesamt = int(stand.get("total") or 0)
        if digest and gesamt:
            self._teile[digest] = (int(stand.get("completed") or 0), gesamt)

    def als_dict(self) -> dict:
        return {
            "laeuft": self.laeuft,
            "modell": self.modell,
            "phase": self.phase,
            "geladen": self.geladen,
            "gesamt": self.gesamt,
            "prozent": self.prozent,
            "fehler": self.fehler,
            "fertig": self.fertig,
        }


class Einrichtung:
    """Kümmert sich um alles, was vor dem ersten Fax bereitstehen muss."""

    def __init__(self, einstellungen: Einstellungen):
        self.einstellungen = einstellungen
        self.fortschritt = Ladefortschritt()
        self._sperre = threading.Lock()
        self._thread: threading.Thread | None = None

    def einstellungen_uebernehmen(self, neue: Einstellungen) -> None:
        self.einstellungen = neue

    def _kunde(self) -> Ollama:
        return Ollama(
            url=self.einstellungen.ollama_url, modell=self.einstellungen.ollama_modell
        )

    # ── Ollama starten ────────────────────────────────────────────────────
    def ollama_starten(self) -> bool:
        """Ollama hochfahren und warten, bis es antwortet."""
        programm = ollama_programm()
        if not programm:
            return False

        kunde = self._kunde()
        if kunde.erreichbar():
            return True

        # Die Hintergrundanwendung mit Infobereichs-Symbol ist der übliche Weg:
        # sie richtet ihren eigenen Autostart ein, so dass Ollama beim nächsten
        # Hochfahren schon läuft. Nur wenn sie fehlt, wird der reine Dienst
        # gestartet.
        anwendung = Path(programm).with_name("ollama app.exe")
        befehl = [str(anwendung)] if anwendung.is_file() else [programm, "serve"]

        try:
            logger.info("Ollama wird gestartet: %s", befehl[0])
            subprocess.Popen(  # noqa: S603 -- fester Pfad, keine Nutzereingabe
                befehl,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                # Losgelöst starten, damit Ollama weiterläuft, wenn FaxFinity
                # beendet wird -- und ohne Fenster, das niemand sehen will.
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as fehler:
            logger.warning("Ollama ließ sich nicht starten: %s", fehler)
            return False

        for _ in range(WARTEN_AUF_OLLAMA * 2):
            time.sleep(0.5)
            if kunde.erreichbar():
                logger.info("Ollama läuft")
                return True
        logger.warning("Ollama antwortet auch nach %d Sekunden nicht", WARTEN_AUF_OLLAMA)
        return False

    # ── Modell laden ──────────────────────────────────────────────────────
    def modell_laden(self, modell: str = "") -> bool:
        """Herunterladen im Hintergrund anstoßen.

        Falsch heißt: es läuft bereits eines. Scheitert der Download selbst,
        steht der Grund hinterher in `fortschritt.fehler` -- ein Fehler, der
        erst nach Minuten auftritt, lässt sich hier noch nicht melden.
        """
        with self._sperre:
            if self.fortschritt.laeuft:
                return False
            name = (modell or "").strip() or self.einstellungen.ollama_modell.strip()
            if not name:
                name = EMPFOHLENES_MODELL
            self.fortschritt = Ladefortschritt(laeuft=True, modell=name, phase="Wird vorbereitet")
            self._thread = threading.Thread(
                target=self._laden, args=(name,), name="modell-laden", daemon=True
            )
            self._thread.start()
        return True

    def _laden(self, modell: str) -> None:
        logger.info("Sprachmodell %s wird geladen", modell)
        try:
            self._kunde().herunterladen(modell, self.fortschritt.uebernehmen)
        except OllamaFehler as fehler:
            logger.error("Sprachmodell %s: %s", modell, fehler)
            self.fortschritt.fehler = str(fehler)
        except Exception as fehler:  # noqa: BLE001 -- ein Nebenlauf darf nie durchschlagen
            logger.exception("Unerwarteter Fehler beim Laden von %s", modell)
            self.fortschritt.fehler = str(fehler)
        else:
            self.fortschritt.fertig = True
            self.fortschritt.phase = "Fertig"
            logger.info("Sprachmodell %s steht bereit", modell)
        finally:
            self.fortschritt.laeuft = False

    # ── Beim Start ────────────────────────────────────────────────────────
    def automatisch(self) -> None:
        """Herrichten, was sich ohne Rückfrage herrichten lässt.

        Läuft in einem eigenen Thread und darf deshalb dauern: der Dienst und
        die Oberfläche stehen längst, während hier noch Gigabyte fließen. Faxe,
        die in der Zwischenzeit eintreffen, bleiben liegen und werden verarbeitet,
        sobald das Modell da ist -- der Dienst versucht es von selbst erneut.
        """
        try:
            kunde = self._kunde()
            if not kunde.erreichbar():
                if not ollama_programm():
                    logger.info(
                        "Ollama ist nicht installiert -- die Oberfläche zeigt, "
                        "woher es zu bekommen ist"
                    )
                    return
                if not self.ollama_starten():
                    return

            fehlend = benoetigtes_modell(
                self.einstellungen.ollama_modell, kunde.modelle()
            )
            if fehlend:
                self.modell_laden(fehlend)
        except Exception:  # noqa: BLE001 -- Einrichtung darf den Start nie verhindern
            logger.exception("Automatische Einrichtung fehlgeschlagen")

    def im_hintergrund_starten(self) -> None:
        threading.Thread(target=self.automatisch, name="einrichtung", daemon=True).start()

    # ── Zustand für die Oberfläche ────────────────────────────────────────
    def zustand(self) -> dict:
        """Was noch fehlt, in Sätzen, die auch ohne Vorkenntnisse etwas sagen."""
        laden = self.fortschritt
        # Während des Downloads wird Ollama nicht befragt: der Stand ist
        # bekannt, und die Oberfläche fragt im Sekundentakt nach.
        if laden.laeuft:
            return {
                "ollama": {"bereit": True, "installiert": True, "meldung": "Ollama läuft"},
                "modell": {
                    "bereit": False,
                    "meldung": f"{laden.modell} wird geladen",
                    "laden": laden.als_dict(),
                },
                "bezugsquellen": self._bezugsquellen(),
            }

        kunde = self._kunde()
        if not kunde.erreichbar():
            installiert = bool(ollama_programm())
            return {
                "ollama": {
                    "bereit": False,
                    "installiert": installiert,
                    "meldung": (
                        "Ollama ist installiert, läuft aber nicht"
                        if installiert
                        else "Ollama ist nicht installiert"
                    ),
                },
                "modell": {
                    "bereit": False,
                    "meldung": "Erst wenn Ollama läuft, prüfbar",
                    "laden": laden.als_dict(),
                },
                "bezugsquellen": self._bezugsquellen(),
            }

        vorhanden = kunde.modelle()
        fehlend = benoetigtes_modell(self.einstellungen.ollama_modell, vorhanden)
        return {
            "ollama": {"bereit": True, "installiert": True, "meldung": "Ollama läuft"},
            "modell": {
                "bereit": not fehlend,
                "meldung": (
                    f"Sprachmodell {fehlend} fehlt (rund 5 GB)"
                    if fehlend
                    else f"Modell {self.einstellungen.ollama_modell or passendes_modell(vorhanden)}"
                ),
                "fehlend": fehlend,
                "laden": laden.als_dict(),
            },
            "bezugsquellen": self._bezugsquellen(),
        }

    @staticmethod
    def _bezugsquellen() -> dict:
        return {"ollama": OLLAMA_BEZUGSQUELLE, "tesseract": TESSERACT_BEZUGSQUELLE}
