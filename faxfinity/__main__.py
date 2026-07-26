"""Startpunkt: Hintergrunddienst hochfahren, Weboberfläche bereitstellen.

    python -m faxfinity                 startet Dienst und Oberfläche
    python -m faxfinity --ohne-browser  ohne Browserfenster (für den Autostart)
    python -m faxfinity --nur-dienst    ganz ohne Oberfläche
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from . import __version__
from .config import JOURNAL_DATEI, KONFIG_DATEI, SPERR_DATEI, Einstellungen
from .dienst import Dienst
from .journal import Journal
from .server import anwendung_bauen

STANDARD_PORT = 8757  # außerhalb der üblichen Entwicklungsports


def protokollierung_einrichten(ausfuehrlich: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if ausfuehrlich else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def freier_port(gewuenscht: int, adresse: str) -> int:
    for kandidat in range(gewuenscht, gewuenscht + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as anschluss:
            try:
                anschluss.bind((adresse, kandidat))
                return kandidat
            except OSError:
                continue
    raise SystemExit(f"Kein freier Port ab {gewuenscht} gefunden")


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

    protokollierung_einrichten(gewaehlt.ausfuehrlich)
    logger = logging.getLogger("faxfinity")
    logger.info("FaxFinity %s", __version__)
    logger.info("Einstellungen: %s", KONFIG_DATEI)

    einstellungen = Einstellungen.laden(KONFIG_DATEI)
    if not KONFIG_DATEI.exists():
        einstellungen.speichern(KONFIG_DATEI)
        logger.info("Neue Einstellungsdatei angelegt -- bitte in der Oberfläche ausfüllen")

    protokoll = Journal(JOURNAL_DATEI)
    dienst = Dienst(einstellungen, protokoll, SPERR_DATEI)

    if not dienst.starten():
        logger.error(dienst.zustand.letzter_fehler)
        return 1

    try:
        if gewaehlt.nur_dienst:
            logger.info("Nur-Dienst-Betrieb, Strg+C beendet")
            while True:
                time.sleep(3600)

        # Ohne ausdrückliche Freigabe hört die Oberfläche nur auf diesem Gerät.
        adresse = "0.0.0.0" if einstellungen.netzwerkzugriff else "127.0.0.1"
        port = freier_port(gewaehlt.port, adresse)
        app = anwendung_bauen(einstellungen, protokoll, dienst, KONFIG_DATEI)

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

        uvicorn.run(app, host=adresse, port=port, log_level="warning")

    except KeyboardInterrupt:
        logger.info("Beendet")
    finally:
        dienst.stoppen()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
