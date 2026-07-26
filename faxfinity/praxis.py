"""Erkennen, ob ein Textstück die eigene Praxis meint.

Der häufigste Fehler der Vorgängerversion war, den Empfänger als Absender zu
protokollieren -- im Log steht mehrfach die eigene Adresse im Absenderfeld. Der
Grund: die Praxis steht im Adressfeld jedes eingehenden Fax, oft direkt neben
dem Briefkopf des Absenders.

Die Vorgängerversion hat einen Treffer stumpf durch "Unbekannt" ersetzt und
damit die Information weggeworfen. Hier wird ein Treffer nur gemeldet -- was
stattdessen als Absender gilt, entscheidet die Verarbeitungskette.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Titel und Rechtsformen tragen nichts zur Unterscheidung bei.
FUELLWOERTER = {
    "dr", "med", "prof", "dipl", "herr", "frau", "herrn", "praxis", "arzt",
    "ärztin", "arztpraxis", "facharzt", "fachärztin", "allgemeinmedizin",
    "gmbh", "mbh", "kg", "ag", "ev", "e", "v", "co", "und", "für", "der",
    "die", "das", "am", "an", "im", "in", "zu", "str", "straße", "strasse",
    "weg", "platz", "allee",
}

MIN_TOKENLAENGE = 4
AEHNLICHKEIT_SCHWELLE = 0.82
# Einzelne Namensbestandteile werden unscharf verglichen, weil die
# Texterkennung sie verfälscht: aus "Rasche" wurde in einem echten Fax
# "Räsche", was einem exakten Vergleich entgeht -- und der eigene Name landete
# prompt als Patient im Dateinamen.
TOKEN_SCHWELLE = 0.85


def _normalisieren(text: str) -> str:
    text = text.lower()
    text = text.replace("ß", "ss")
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        text = text.replace(alt, neu)
    return re.sub(r"[^a-z0-9 ]+", " ", text)


def _tokens(text: str) -> set[str]:
    return {
        wort
        for wort in _normalisieren(text).split()
        if len(wort) >= MIN_TOKENLAENGE and wort not in FUELLWOERTER and not wort.isdigit()
    }


def _ziffern(text: str) -> str:
    return re.sub(r"\D", "", text)


class Praxisabgleich:
    """Vergleicht Textstücke gegen die eigenen Praxisdaten."""

    def __init__(self, name: str = "", strasse: str = "", faxnummer: str = ""):
        self.name = name
        self.strasse = strasse
        self.faxnummer = _ziffern(faxnummer)
        self._namenstokens = _tokens(name)
        self._strassentokens = _tokens(strasse)

    def __bool__(self) -> bool:
        return bool(self._namenstokens or self.faxnummer)

    def ist_eigene_praxis(self, kandidat: str) -> bool:
        """Bezeichnet dieser Text die eigene Praxis?"""
        if not kandidat or not self:
            return False

        # Die eigene Faxnummer ist ein eindeutiger Beleg.
        if self.faxnummer and self.faxnummer in _ziffern(kandidat):
            return True

        kandidatentokens = _tokens(kandidat)
        if not kandidatentokens:
            return False

        # Ein Namensbestandteil allein genügt: "Rasche" oder "Florian" im
        # Absenderfeld ist bei eingehender Post immer der Empfänger.
        if self._enthaelt_token(self._namenstokens, kandidatentokens):
            return True

        # Straße plus Ort ohne Namen kommt vor, wenn die Texterkennung den
        # Namen verschluckt hat.
        if len(self._strassentokens & kandidatentokens) >= 2:
            return True

        return (
            SequenceMatcher(None, _normalisieren(self.name), _normalisieren(kandidat)).ratio()
            >= AEHNLICHKEIT_SCHWELLE
        )

    @staticmethod
    def _enthaelt_token(eigene: set[str], kandidaten: set[str]) -> bool:
        """Unscharfer Vergleich einzelner Namensbestandteile."""
        if eigene & kandidaten:
            return True
        return any(
            SequenceMatcher(None, eigen, fremd).ratio() >= TOKEN_SCHWELLE
            for eigen in eigene
            for fremd in kandidaten
        )
