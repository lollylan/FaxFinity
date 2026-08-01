"""Weboberfläche und Schnittstelle.

Die Oberfläche zeigt nur an und stellt ein -- verarbeitet wird ausschließlich im
Hintergrunddienst. Ein geschlossener Browser hält deshalb nichts auf, und zwei
geöffnete Fenster lösen keine doppelte Verarbeitung aus.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, fields
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__, autostart, ordnerbaum
from .config import Einstellungen
from .dienst import Dienst
from .einrichtung import Einrichtung
from .journal import Journal
from .llm import Ollama
from .ocr import OcrNichtVerfuegbar, Tesseract

logger = logging.getLogger(__name__)

OBERFLAECHE = Path(__file__).resolve().parent / "web" / "index.html"
OCR_PUFFER_SEKUNDEN = 20


def anwendung_bauen(
    einstellungen: Einstellungen,
    protokoll: Journal,
    dienst: Dienst,
    konfigpfad: Path,
    einrichtung: Einrichtung | None = None,
    beenden=None,
) -> FastAPI:
    app = FastAPI(title="FaxFinity", docs_url=None, redoc_url=None)
    # Veränderlicher Behälter, damit gespeicherte Einstellungen sofort greifen.
    aktuell = {"einstellungen": einstellungen}
    einrichtung = einrichtung or Einrichtung(einstellungen)
    # Der Zustand der Texterkennung kostet zwei Tesseract-Aufrufe. Während des
    # Modell-Downloads fragt die Oberfläche im Sekundentakt nach -- so oft muss
    # dafür kein Prozess starten.
    ocr_puffer: dict = {"zeit": 0.0, "stand": None}

    def ocr_gepuffert() -> dict:
        jetzt = time.monotonic()
        if ocr_puffer["stand"] is None or jetzt - ocr_puffer["zeit"] > OCR_PUFFER_SEKUNDEN:
            ocr_puffer["stand"] = _ocr_zustand(aktuell["einstellungen"])
            ocr_puffer["zeit"] = jetzt
        return ocr_puffer["stand"]

    @app.get("/", response_class=HTMLResponse)
    def oberflaeche() -> str:
        return OBERFLAECHE.read_text(encoding="utf-8")

    @app.get("/api/zustand")
    def zustand() -> dict:
        return {
            "version": __version__,
            "dienst": dienst.zustand.als_dict(),
            "kennzahlen": protokoll.kennzahlen(),
        }

    @app.get("/api/protokoll")
    def protokoll_lesen(anzahl: int = 50) -> list[dict]:
        return protokoll.eintraege(min(max(anzahl, 1), 500))

    @app.get("/api/einstellungen")
    def einstellungen_lesen() -> dict:
        return asdict(aktuell["einstellungen"])

    @app.post("/api/einstellungen")
    def einstellungen_schreiben(daten: dict) -> JSONResponse:
        erlaubt = {f.name for f in fields(Einstellungen)}
        unbekannt = set(daten) - erlaubt
        if unbekannt:
            return JSONResponse(
                {"fehler": f"Unbekannte Einstellungen: {', '.join(sorted(unbekannt))}"},
                status_code=400,
            )

        if "kategorien" in daten:
            kategorien = daten["kategorien"]
            if not isinstance(kategorien, list) or not all(
                isinstance(k, str) for k in kategorien
            ):
                return JSONResponse(
                    {"fehler": "Kategorien müssen eine Liste von Begriffen sein"},
                    status_code=400,
                )
            if not [k for k in kategorien if k.strip()]:
                return JSONResponse(
                    {"fehler": "Es muss mindestens eine Kategorie übrigbleiben"},
                    status_code=400,
                )

        neu = Einstellungen(**{**asdict(aktuell["einstellungen"]), **daten})

        # Ein leerer Eingangsordner ist zulässig: beim ersten Start ist noch
        # nichts eingetragen, und die Angaben sollen trotzdem speicherbar sein.
        if neu.eingangsordner.strip():
            beanstandung = neu.ordner_beanstanden()
            if beanstandung:
                return JSONResponse({"fehler": beanstandung}, status_code=400)
            try:
                neu.ordner_anlegen()
            except OSError as fehler:
                return JSONResponse(
                    {"fehler": f"Ordner konnten nicht angelegt werden: {fehler}"},
                    status_code=400,
                )

        neu.speichern(konfigpfad)
        aktuell["einstellungen"] = neu
        ocr_puffer["stand"] = None  # der Tesseract-Pfad kann sich geändert haben
        dienst.einstellungen_uebernehmen(neu)
        einrichtung.einstellungen_uebernehmen(neu)
        logger.info("Einstellungen gespeichert")
        return JSONResponse({"gespeichert": True})

    @app.post("/api/pruefen")
    def sofort_pruefen() -> dict:
        dienst.jetzt_pruefen()
        return {"angestossen": True}

    @app.get("/api/ordner")
    def ordner_auflisten(pfad: str = "") -> dict:
        """Ordner zum Durchblättern in der Auswahl der Oberfläche."""
        return ordnerbaum.auflisten(pfad)

    @app.get("/api/system")
    def systemzustand() -> dict:
        einst = aktuell["einstellungen"]
        return {
            "ollama": _ollama_zustand(einst),
            "ocr": ocr_gepuffert(),
            "ordner": _ordner_zustand(einst),
        }

    # ── Einrichtung ───────────────────────────────────────────────────────
    # Diese Schnittstelle beantwortet eine andere Frage als /api/system: nicht
    # "läuft alles?", sondern "was muss ich noch tun, und was kann FaxFinity
    # davon selbst erledigen?".
    @app.get("/api/einrichtung")
    def einrichtung_lesen() -> dict:
        stand = einrichtung.zustand()
        stand["ocr"] = ocr_gepuffert()
        stand["autostart"] = autostart.eingerichtet()
        stand["fertig"] = (
            stand["ollama"]["bereit"] and stand["modell"]["bereit"] and stand["ocr"]["bereit"]
        )
        return stand

    @app.post("/api/einrichtung/ollama-starten")
    def ollama_starten() -> JSONResponse:
        if einrichtung.ollama_starten():
            return JSONResponse({"gestartet": True})
        return JSONResponse(
            {"fehler": "Ollama ließ sich nicht starten. Läuft es vielleicht auf einem anderen Rechner?"},
            status_code=400,
        )

    @app.post("/api/einrichtung/modell-laden")
    def modell_laden(daten: dict | None = None) -> JSONResponse:
        # Ein zweiter Anstoß bei laufendem Download ist kein Fehler, sondern
        # ein zweiter Klick -- der Fortschritt steht ohnehin in der Oberfläche.
        return JSONResponse(
            {"angestossen": einrichtung.modell_laden((daten or {}).get("modell", ""))}
        )

    @app.post("/api/autostart")
    def autostart_setzen(daten: dict) -> JSONResponse:
        aktiv = bool(daten.get("aktiv"))
        if not autostart.setzen(aktiv):
            return JSONResponse(
                {"fehler": "Der Autostart ließ sich nicht ändern"}, status_code=400
            )
        logger.info("Autostart %s", "eingerichtet" if aktiv else "entfernt")
        return JSONResponse({"aktiv": autostart.eingerichtet()})

    @app.post("/api/beenden")
    def anwendung_beenden() -> JSONResponse:
        """FaxFinity ganz beenden.

        In der EXE-Fassung gibt es kein Konsolenfenster mehr, das sich
        schließen ließe -- ohne diesen Knopf käme man nicht mehr heraus.
        """
        if beenden is None:
            return JSONResponse(
                {"fehler": "Beenden ist in dieser Betriebsart nicht möglich"},
                status_code=400,
            )
        logger.info("Beenden über die Oberfläche angefordert")
        beenden()
        return JSONResponse({"beendet": True})

    return app


def _ollama_zustand(einstellungen: Einstellungen) -> dict:
    kunde = Ollama(
        url=einstellungen.ollama_url,
        modell=einstellungen.ollama_modell,
        denkmodus=einstellungen.ollama_denkmodus,
    )
    if not kunde.erreichbar():
        return {
            "bereit": False,
            "meldung": f"Ollama unter {einstellungen.ollama_url} nicht erreichbar",
            "modelle": [],
        }

    modelle = kunde.modelle()
    try:
        gewaehlt = kunde.modell_waehlen()
    except Exception as fehler:  # noqa: BLE001
        return {"bereit": False, "meldung": str(fehler), "modelle": modelle}

    return {
        "bereit": True,
        "meldung": f"Modell {gewaehlt}",
        "modell": gewaehlt,
        "modelle": modelle,
    }


def _ocr_zustand(einstellungen: Einstellungen) -> dict:
    try:
        tess = Tesseract(
            einstellungen.tesseract_pfad,
            einstellungen.ocr_sprache,
            einstellungen.ocr_sprachdaten,
        )
    except OcrNichtVerfuegbar as fehler:
        return {"bereit": False, "meldung": str(fehler)}

    if not tess.sprache_verfuegbar:
        return {
            "bereit": False,
            "meldung": (
                f"Sprache '{einstellungen.ocr_sprache}' fehlt. "
                f"Vorhanden: {', '.join(sorted(tess.sprachen())) or 'keine'}"
            ),
        }
    return {"bereit": True, "meldung": f"{tess.version()} ({einstellungen.ocr_sprache})"}


def _ordner_zustand(einstellungen: Einstellungen) -> dict:
    beanstandung = einstellungen.ordner_beanstanden()
    if beanstandung:
        return {"bereit": False, "meldung": beanstandung}
    return {
        "bereit": True,
        "meldung": f"Eingang {einstellungen.eingang} → Ausgang {einstellungen.ziel}",
    }
