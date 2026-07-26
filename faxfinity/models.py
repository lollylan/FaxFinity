"""Datenmodelle, die durch die Verarbeitungskette gereicht werden."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Quelle(str, Enum):
    """Woher stammt eine erkannte Information?"""

    TEXTEBENE = "textebene"  # PDF hatte eingebetteten Text
    OCR = "ocr"  # per Tesseract erkannt
    FAXKOPF = "faxkopf"  # aus der Fax-Kopfzeile gelesen
    LLM = "llm"
    FALLBACK = "fallback"  # nichts erkannt, Notnagel


class Ergebnis(str, Enum):
    ERFOLG = "erfolg"
    UNSICHER = "unsicher"  # verarbeitet, aber ohne verlässliche Erkennung
    DUPLIKAT = "duplikat"
    FEHLER = "fehler"


@dataclass
class Seiteninhalt:
    """Text einer einzelnen Seite plus wie er zustande kam."""

    seite: int
    text: str
    quelle: Quelle
    ocr_konfidenz: float | None = None
    drehung: int = 0  # angewandte Korrektur in Grad


@dataclass
class Dokumenttext:
    seiten: list[Seiteninhalt] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(s.text for s in self.seiten if s.text.strip())

    @property
    def zeichen(self) -> int:
        return len(self.text.strip())

    @property
    def quelle(self) -> Quelle:
        return self.seiten[0].quelle if self.seiten else Quelle.FALLBACK

    @property
    def konfidenz(self) -> float | None:
        werte = [s.ocr_konfidenz for s in self.seiten if s.ocr_konfidenz is not None]
        return sum(werte) / len(werte) if werte else None


@dataclass
class Faxkopf:
    """Die Zeile, die das sendende Faxgerät oben auf jede Seite druckt."""

    rohzeile: str = ""
    absender: str = ""
    faxnummer: str = ""

    def __bool__(self) -> bool:
        return bool(self.absender or self.faxnummer)


@dataclass
class Analyse:
    """Was aus dem Dokument herausgelesen wurde."""

    kategorie: str = "Sonstiges"
    absender: str = ""
    absender_kurz: str = ""
    fachrichtung: str = ""
    patient_nachname: str = ""
    patient_vorname: str = ""
    sicherheit: str = "niedrig"  # hoch | mittel | niedrig
    quelle: Quelle = Quelle.FALLBACK
    hinweise: list[str] = field(default_factory=list)

    @property
    def patient(self) -> str:
        teile = [t for t in (self.patient_nachname, self.patient_vorname) if t]
        return " ".join(teile)

    @property
    def ist_verwertbar(self) -> bool:
        """Reicht die Erkennung für einen sprechenden Dateinamen?"""
        return bool(self.absender_kurz or self.patient_nachname)


@dataclass
class Verarbeitung:
    """Vollständiges Protokoll der Verarbeitung einer Datei."""

    quelldatei: str
    sha256: str
    eingang_am: datetime
    ergebnis: Ergebnis = Ergebnis.FEHLER
    archivdatei: str = ""
    zieldatei: str = ""
    analyse: Analyse = field(default_factory=Analyse)
    dauer_sekunden: float = 0.0
    meldung: str = ""

    def als_dict(self) -> dict:
        return {
            "zeitpunkt": self.eingang_am.isoformat(timespec="seconds"),
            "quelldatei": self.quelldatei,
            "sha256": self.sha256,
            "ergebnis": self.ergebnis.value,
            "archivdatei": self.archivdatei,
            "zieldatei": self.zieldatei,
            "kategorie": self.analyse.kategorie,
            "absender": self.analyse.absender,
            "patient": self.analyse.patient,
            "sicherheit": self.analyse.sicherheit,
            "quelle": self.analyse.quelle.value,
            "dauer_sekunden": round(self.dauer_sekunden, 1),
            "meldung": self.meldung,
            "hinweise": self.analyse.hinweise,
        }
