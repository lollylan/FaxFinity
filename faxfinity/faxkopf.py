"""Die Kopfzeile auswerten, die das sendende Faxgerät auf jede Seite druckt.

Diese Zeile ist der verlässlichste Hinweis auf den Absender, den ein Fax
mitbringt -- sie stammt vom Gerät der Gegenstelle und nicht aus dem Briefkopf.
Gerade bei zweispaltigen Briefköpfen, bei denen die Texterkennung Absender und
Empfänger in eine Zeile wirft, entscheidet sie den Zweifelsfall.

Beobachtete Varianten aus echten Faxen:
    02/01/2002 23:27 093100112233 STADTAPOTHEKE S. 01/01
    26-Nov-2025 14:28 MVZ für Labormedizin Nord 8931200112233
    (F4%X)0049 9310011223 17:33 Seniorenheim Sr, P.001/001
"""

from __future__ import annotations

import re

from .models import Faxkopf

# Nur die obersten Zeilen betrachten -- weiter unten beginnt der Briefkopf.
ZU_PRUEFENDE_ZEILEN = 3

MONATE = "Jan|Feb|Mar|Mär|Apr|Mai|May|Jun|Jul|Aug|Sep|Okt|Oct|Nov|Dez|Dec"

# Alles, was in einer Kopfzeile Beiwerk ist und vor der Namenssuche wegfällt.
STOERMUSTER = [
    re.compile(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"),              # 26.11.2025
    re.compile(rf"\d{{1,2}}[-. ](?:{MONATE})[a-z]*[-. ]\d{{2,4}}", re.I),  # 26-Nov-2025
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),                  # 14:28
    re.compile(r"\b(?:S|P|Seite|Page|Pg)[.,]?\s*\d{1,3}\s*(?:/|von|of)\s*\d{1,3}", re.I),
    re.compile(r"\b\d{3}\s*/\s*\d{3}\b"),                         # 001/001
    re.compile(r"\bSeite\s+\d+\s+von\s+\d+\b", re.I),
    # (FAX) und was die Texterkennung daraus macht: (F4%X), (FRX), (F X)
    re.compile(r"\(\s*F[^)]{0,4}X\s*\)", re.I),
    re.compile(r"\bTel(?:efon)?[.:]?|\bFax[.:]?|\bTelefax[.:]?", re.I),
]

# Ziffernfolgen, die als Ruf-/Faxnummer durchgehen.
NUMMER = re.compile(r"(?:\+49|0049|00\d{2})?[\d\s/()-]{7,}\d")

# Wörter, die allein noch keinen Absender ergeben.
UNBRAUCHBAR = {
    "fax", "telefax", "von", "from", "an", "to", "seite", "page", "gmbh",
    "tel", "telefon", "uhr", "nr", "no", "s", "p", "empfangen", "received",
}


def _zeile_saeubern(zeile: str) -> str:
    for muster in STOERMUSTER:
        zeile = muster.sub(" ", zeile)
    return zeile


def _nummer_finden(zeile: str) -> str:
    """Längste plausible Ruf-/Faxnummer aus der Zeile ziehen."""
    beste = ""
    for treffer in NUMMER.finditer(zeile):
        ziffern = re.sub(r"\D", "", treffer.group())
        # Unter 8 Ziffern ist es eher eine Zimmer- oder Belegnummer,
        # über 16 eher zusammengelaufener OCR-Müll.
        if 8 <= len(ziffern) <= 16 and len(ziffern) > len(beste):
            beste = ziffern
    return beste


def _name_finden(zeile: str) -> str:
    """Was nach Abzug von Datum, Uhrzeit, Seitenzähler und Nummern übrig bleibt."""
    rest = NUMMER.sub(" ", zeile)
    rest = re.sub(r"[^\wÄÖÜäöüß&.\- ]+", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" .-")

    woerter = [
        w for w in rest.split()
        if len(w) >= 2 and w.lower().strip(".") not in UNBRAUCHBAR and not w.isdigit()
    ]
    if not woerter:
        return ""

    name = " ".join(woerter)
    # Reine Großschreibung ist bei Faxköpfen die Regel und liest sich schlecht.
    if name.isupper() and len(name) > 4:
        name = name.title()
    return name if len(name) >= 3 else ""


def auslesen(text: str) -> Faxkopf:
    """Kopfzeile aus dem erkannten Seitentext bestimmen."""
    zeilen = [z for z in text.splitlines() if z.strip()][:ZU_PRUEFENDE_ZEILEN]

    beste = Faxkopf()
    for zeile in zeilen:
        gesaeubert = _zeile_saeubern(zeile)
        nummer = _nummer_finden(gesaeubert)
        name = _name_finden(gesaeubert)

        if not (nummer or name):
            continue

        # Eine Zeile mit Nummer *und* Name ist die typische Faxkopfzeile und
        # schlägt jeden Teiltreffer aus einer anderen Zeile.
        kandidat = Faxkopf(rohzeile=zeile.strip(), absender=name, faxnummer=nummer)
        if nummer and name:
            return kandidat
        if not beste:
            beste = kandidat

    return beste
