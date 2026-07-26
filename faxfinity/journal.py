"""Lückenloses Protokoll aller Verarbeitungen.

Das Journal ist die Antwort auf die Anforderung, dass kein Fax ungesehen
verschwinden darf. Es wird ausschließlich angehängt, nie überschrieben, und
enthält für jede Datei den SHA-256-Wert. Damit lässt sich im Nachhinein für
jedes Fax belegen, wohin es gegangen ist -- und ein doppelt eingegangenes Fax
wird als solches erkannt statt ein zweites Mal abgelegt.

Die Vorgängerversion hat ihr Log auf die letzten 50 Einträge gekürzt und dabei
die Historie fortlaufend weggeworfen.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from .models import Ergebnis, Verarbeitung

logger = logging.getLogger(__name__)

BLOCKGROESSE = 1024 * 1024


def sha256(pfad: Path) -> str:
    """Prüfsumme einer Datei bilden."""
    streuwert = hashlib.sha256()
    with open(pfad, "rb") as datei:
        while block := datei.read(BLOCKGROESSE):
            streuwert.update(block)
    return streuwert.hexdigest()


class Journal:
    def __init__(self, pfad: Path):
        self.pfad = pfad
        self._sperre = threading.Lock()
        self._bekannte_hashes: set[str] | None = None

    # ── Schreiben ─────────────────────────────────────────────────────────
    def eintragen(self, verarbeitung: Verarbeitung) -> None:
        zeile = json.dumps(verarbeitung.als_dict(), ensure_ascii=False)
        with self._sperre:
            self.pfad.parent.mkdir(parents=True, exist_ok=True)
            with open(self.pfad, "a", encoding="utf-8") as datei:
                datei.write(zeile + "\n")
                datei.flush()
            if self._bekannte_hashes is not None and verarbeitung.sha256:
                self._bekannte_hashes.add(verarbeitung.sha256)

    # ── Lesen ─────────────────────────────────────────────────────────────
    def eintraege(self, anzahl: int = 100) -> list[dict]:
        """Die jüngsten Einträge, neueste zuerst."""
        if not self.pfad.exists():
            return []
        with self._sperre:
            with open(self.pfad, "r", encoding="utf-8") as datei:
                zeilen = datei.readlines()

        ergebnis = []
        for zeile in reversed(zeilen):
            if len(ergebnis) >= anzahl:
                break
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                ergebnis.append(json.loads(zeile))
            except json.JSONDecodeError:
                continue  # abgebrochene Zeile nach Stromausfall
        return ergebnis

    def _hashes_laden(self) -> set[str]:
        if self._bekannte_hashes is not None:
            return self._bekannte_hashes

        hashes: set[str] = set()
        if self.pfad.exists():
            with open(self.pfad, "r", encoding="utf-8") as datei:
                for zeile in datei:
                    zeile = zeile.strip()
                    if not zeile:
                        continue
                    try:
                        eintrag = json.loads(zeile)
                    except json.JSONDecodeError:
                        continue
                    # Nur abgelegte Faxe zählen als bereits erledigt. Ein
                    # Fehlversuch soll erneut verarbeitet werden dürfen.
                    if eintrag.get("ergebnis") in (
                        Ergebnis.ERFOLG.value,
                        Ergebnis.UNSICHER.value,
                    ) and eintrag.get("sha256"):
                        hashes.add(eintrag["sha256"])
        self._bekannte_hashes = hashes
        return hashes

    def schon_verarbeitet(self, streuwert: str) -> bool:
        with self._sperre:
            return streuwert in self._hashes_laden()

    def frueherer_zielname(self, streuwert: str) -> str:
        """Wie hieß dieses Fax beim ersten Mal?

        Ein erneut eingehendes, inhaltsgleiches Fax bekommt denselben Namen --
        dann steht es in der Ablage direkt neben dem ersten Exemplar statt als
        namenloses 'FAX_...' daneben.
        """
        if not self.pfad.exists():
            return ""
        with self._sperre:
            with open(self.pfad, "r", encoding="utf-8") as datei:
                zeilen = datei.readlines()

        for zeile in reversed(zeilen):
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                eintrag = json.loads(zeile)
            except json.JSONDecodeError:
                continue
            if eintrag.get("sha256") == streuwert and eintrag.get("zieldatei"):
                return eintrag["zieldatei"]
        return ""

    # ── Auswertung für die Oberfläche ─────────────────────────────────────
    def kennzahlen(self) -> dict:
        zaehler = {ergebnis.value: 0 for ergebnis in Ergebnis}
        gesamt = 0
        letzter = ""

        if self.pfad.exists():
            with self._sperre:
                with open(self.pfad, "r", encoding="utf-8") as datei:
                    for zeile in datei:
                        zeile = zeile.strip()
                        if not zeile:
                            continue
                        try:
                            eintrag = json.loads(zeile)
                        except json.JSONDecodeError:
                            continue
                        gesamt += 1
                        schluessel = eintrag.get("ergebnis", "")
                        if schluessel in zaehler:
                            zaehler[schluessel] += 1
                        letzter = eintrag.get("zeitpunkt", letzter)

        return {"gesamt": gesamt, "letzter_eintrag": letzter, **zaehler}


def neue_verarbeitung(quelldatei: Path, streuwert: str) -> Verarbeitung:
    return Verarbeitung(
        quelldatei=quelldatei.name,
        sha256=streuwert,
        eingang_am=datetime.now(),
    )
