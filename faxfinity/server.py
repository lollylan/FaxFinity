"""Weboberfläche und Schnittstelle.

Die Oberfläche zeigt nur an und stellt ein -- verarbeitet wird ausschließlich im
Hintergrunddienst. Ein geschlossener Browser hält deshalb nichts auf, und zwei
geöffnete Fenster lösen keine doppelte Verarbeitung aus.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, fields
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__, ordnerbaum
from .config import Einstellungen
from .dienst import Dienst
from .journal import Journal
from .llm import Ollama
from .ocr import OcrNichtVerfuegbar, Tesseract

logger = logging.getLogger(__name__)

OBERFLAECHE = Path(__file__).resolve().parent / "web" / "index.html"


def anwendung_bauen(
    einstellungen: Einstellungen, protokoll: Journal, dienst: Dienst, konfigpfad: Path
) -> FastAPI:
    app = FastAPI(title="FaxFinity", docs_url=None, redoc_url=None)
    # Veränderlicher Behälter, damit gespeicherte Einstellungen sofort greifen.
    aktuell = {"einstellungen": einstellungen}

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
        dienst.einstellungen_uebernehmen(neu)
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
            "ocr": _ocr_zustand(einst),
            "ordner": _ordner_zustand(einst),
        }

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
