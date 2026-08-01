"""Startpunkt: Hintergrunddienst hochfahren, Weboberfläche bereitstellen.

    python -m faxfinity                 startet Dienst und Oberfläche
    python -m faxfinity --ohne-browser  ohne Browserfenster (für den Autostart)
    python -m faxfinity --nur-dienst    ganz ohne Oberfläche

Als EXE gilt dasselbe; dort gibt es nur kein Konsolenfenster, in dem etwas
stünde. Alles, was sonst dort erschiene, landet in faxfinity.log neben der EXE.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import webbrowser

import requests
import uvicorn

from . import __version__
from .config import (
    JOURNAL_DATEI,
    KONFIG_DATEI,
    PROTOKOLL_DATEI,
    SPERR_DATEI,
    Einstellungen,
)
from .dienst import Dienst
from .einrichtung import Einrichtung
from .journal import Journal
from .server import anwendung_bauen

STANDARD_PORT = 8757  # außerhalb der üblichen Entwicklungsports
PORT_SPANNE = 20  # so viele Ports werden nach einem freien durchprobiert
PROTOKOLL_GROESSE = 2_000_000
PROTOKOLL_STAENDE = 3

# Die fensterlose EXE-Fassung läuft ganz ohne Standardausgabe: sys.stdout ist
# dort None. Festgehalten wird das beim Laden, weil die Ausgabe gleich darauf
# durch einen Papierkorb ersetzt wird.
OHNE_KONSOLE = sys.stdout is None


def ausgabe_absichern() -> None:
    """Dafür sorgen, dass sys.stdout und sys.stderr etwas sind.

    Fremde Bibliotheken verlassen sich darauf: uvicorn fragt beim Einrichten
    seiner Protokollierung `sys.stdout.isatty()` und bringt ohne Konsole den
    ganzen Start zu Fall. Statt jede solche Stelle einzeln zu umgehen, bekommt
    der Prozess einen Papierkorb -- geschrieben wird ohnehin in die Datei.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def protokollierung_einrichten(ausfuehrlich: bool) -> None:
    """Ins Konsolenfenster schreiben, wenn es eines gibt -- und immer in die Datei.

    Ohne Konsole ist die Datei die einzige Möglichkeit, hinterher nachzusehen,
    warum etwas nicht ging.

    Im Protokoll stehen Dateinamen und damit Patientennamen -- es gehört
    genauso geschützt wie der Zielordner.
    """
    form = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-22s %(message)s", datefmt="%H:%M:%S"
    )
    wurzel = logging.getLogger()
    wurzel.setLevel(logging.DEBUG if ausfuehrlich else logging.INFO)

    if not OHNE_KONSOLE:
        an_konsole = logging.StreamHandler(stream=sys.stdout)
        an_konsole.setFormatter(form)
        wurzel.addHandler(an_konsole)

    try:
        in_datei = logging.handlers.RotatingFileHandler(
            PROTOKOLL_DATEI, maxBytes=PROTOKOLL_GROESSE, backupCount=PROTOKOLL_STAENDE,
            encoding="utf-8",
        )
        in_datei.setFormatter(form)
        wurzel.addHandler(in_datei)
    except OSError as fehler:
        # Etwa ein schreibgeschützter Programmordner. Kein Grund, nicht zu starten.
        logging.getLogger("faxfinity").warning(
            "Protokolldatei %s nicht beschreibbar: %s", PROTOKOLL_DATEI, fehler
        )

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def hinweisfenster(text: str) -> None:
    """Ohne Konsole bleibt nur ein Fenster, um überhaupt etwas zu sagen."""
    if not OHNE_KONSOLE or sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, text, "FaxFinity", 0x40)
    except Exception:  # noqa: BLE001 -- ein misslungener Hinweis darf nichts auslösen
        pass


def freier_port(gewuenscht: int, adresse: str) -> int:
    for kandidat in range(gewuenscht, gewuenscht + PORT_SPANNE):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as anschluss:
            try:
                anschluss.bind((adresse, kandidat))
                return kandidat
            except OSError:
                continue
    raise SystemExit(f"Kein freier Port ab {gewuenscht} gefunden")


def laufende_instanz(ab_port: int) -> int:
    """Port eines bereits laufenden FaxFinity, sonst 0.

    Gebraucht beim zweiten Doppelklick auf die EXE: statt einer Fehlermeldung,
    mit der niemand etwas anfangen kann, wird die schon laufende Oberfläche
    geöffnet. Geprüft wird die Schnittstelle und nicht nur der offene Port --
    dort könnte auch etwas anderes lauschen.
    """
    for kandidat in range(ab_port, ab_port + PORT_SPANNE):
        try:
            antwort = requests.get(
                f"http://127.0.0.1:{kandidat}/api/zustand", timeout=1.0
            )
            if antwort.ok and "dienst" in antwort.json():
                return kandidat
        except (requests.RequestException, ValueError):
            continue
    return 0


def eigene_netzwerkadresse() -> str:
    """Die Adresse, unter der dieser Rechner im Praxisnetz erreichbar ist.

    Ermittelt über einen Testanschluss zu einer Adresse aus dem für
    Dokumentation reservierten Bereich -- es fließt kein Verkehr, aber das
    Betriebssystem verrät dabei, welche eigene Adresse es benutzen würde.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as anschluss:
        try:
            anschluss.connect(("192.0.2.1", 1))
            return anschluss.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def browser_oeffnen_wenn_bereit(port: int) -> None:
    ziel = f"http://127.0.0.1:{port}"
    for _ in range(80):  # bis zu 20 Sekunden
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as anschluss:
            anschluss.settimeout(0.3)
            if anschluss.connect_ex(("127.0.0.1", port)) == 0:
                webbrowser.open(ziel)
                return
        time.sleep(0.25)


def main(argumente: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(prog="faxfinity", description=__doc__)
    zerleger.add_argument("--port", type=int, default=STANDARD_PORT)
    zerleger.add_argument("--ohne-browser", action="store_true")
    zerleger.add_argument("--nur-dienst", action="store_true")
    zerleger.add_argument("--ausfuehrlich", action="store_true")
    gewaehlt = zerleger.parse_args(argumente)

    ausgabe_absichern()
    protokollierung_einrichten(gewaehlt.ausfuehrlich)
    logger = logging.getLogger("faxfinity")
    logger.info("FaxFinity %s", __version__)
    logger.info("Einstellungen: %s", KONFIG_DATEI)

    einstellungen = Einstellungen.laden(KONFIG_DATEI)
    if not KONFIG_DATEI.exists():
        einstellungen.speichern(KONFIG_DATEI)
        logger.info("Neue Einstellungsdatei angelegt -- bitte in der Oberfläche ausfüllen")

    protokoll = Journal(JOURNAL_DATEI)
    einrichtung = Einrichtung(einstellungen)
    dienst = Dienst(
        einstellungen,
        protokoll,
        SPERR_DATEI,
        warten_solange=lambda: (
            f"Sprachmodell {einrichtung.fortschritt.modell} wird geladen "
            f"({einrichtung.fortschritt.prozent} %) -- Faxe warten solange"
            if einrichtung.fortschritt.laeuft
            else ""
        ),
    )

    if not dienst.starten():
        # Ein zweiter Start ist kein Fehler, sondern der Wunsch, die Oberfläche
        # zu sehen. Also die schon laufende zeigen.
        andere = laufende_instanz(gewaehlt.port)
        if andere:
            logger.info("FaxFinity läuft bereits auf Port %d", andere)
            if not gewaehlt.ohne_browser:
                webbrowser.open(f"http://127.0.0.1:{andere}")
            return 0
        logger.error(dienst.zustand.letzter_fehler)
        hinweisfenster(dienst.zustand.letzter_fehler)
        return 1

    # Ollama starten und das Sprachmodell holen, während der Dienst schon läuft.
    einrichtung.im_hintergrund_starten()

    try:
        if gewaehlt.nur_dienst:
            logger.info("Nur-Dienst-Betrieb, Strg+C beendet")
            while True:
                time.sleep(3600)

        # Ohne ausdrückliche Freigabe hört die Oberfläche nur auf diesem Gerät.
        adresse = "0.0.0.0" if einstellungen.netzwerkzugriff else "127.0.0.1"
        port = freier_port(gewaehlt.port, adresse)

        # Der Server steht erst nach dem Bauen der Anwendung fest, die
        # Anwendung braucht aber schon einen Weg, ihn zu beenden.
        halter: dict = {}
        app = anwendung_bauen(
            einstellungen, protokoll, dienst, KONFIG_DATEI,
            einrichtung=einrichtung,
            beenden=lambda: setattr(halter["server"], "should_exit", True),
        )

        logger.info("Oberfläche: http://127.0.0.1:%d", port)
        if einstellungen.netzwerkzugriff:
            logger.info(
                "Aus dem Netz erreichbar: http://%s:%d", eigene_netzwerkadresse(), port
            )
            logger.warning(
                "Netzwerkzugriff ist eingeschaltet -- die Oberfläche ist ohne "
                "Anmeldung erreichbar und zeigt Patientennamen an."
            )

        if not gewaehlt.ohne_browser:
            threading.Thread(
                target=browser_oeffnen_wenn_bereit, args=(port,), daemon=True
            ).start()

        halter["server"] = uvicorn.Server(
            uvicorn.Config(
                app, host=adresse, port=port, log_level="warning",
                # Ohne dies richtet uvicorn seine eigene Protokollierung ein und
                # überschreibt damit die Datei-Ausgabe, die gerade aufgebaut
                # wurde. So laufen die Meldungen des Servers dort mit hinein.
                log_config=None,
            )
        )
        halter["server"].run()

    except KeyboardInterrupt:
        logger.info("Beendet")
    finally:
        dienst.stoppen()

    return 0


def start() -> int:
    """Wie main, meldet einen Absturz aber auch dort, wo keine Konsole ist."""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException as fehler:  # noqa: BLE001 -- letzte Instanz vor dem Nichts
        logging.getLogger("faxfinity").exception("FaxFinity ist abgestürzt")
        hinweisfenster(
            f"FaxFinity konnte nicht starten:\n\n{fehler}\n\n"
            f"Einzelheiten stehen in:\n{PROTOKOLL_DATEI}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(start())
