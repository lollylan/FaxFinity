"""Konfiguration von FaxFinity.

Wird als JSON neben der Anwendung abgelegt. Unbekannte Schlüssel aus älteren
Versionen werden beim Laden gemappt, damit ein Update nichts zerschießt.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

logger = logging.getLogger(__name__)


def anwendungsordner() -> Path:
    """Ordner, in dem Konfiguration, Journal und Sperrdatei liegen.

    Als EXE der Ordner neben der EXE, sonst das Projektverzeichnis. Damit bleibt
    die Installation in sich geschlossen und lässt sich als Ganzes kopieren.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ressourcenordner() -> Path:
    """Ordner mit dem, was mitgeliefert wird: Sprachdaten und Tesseract.

    Das ist bewusst nicht derselbe Ordner wie oben. PyInstaller packt die
    mitgelieferten Dateien in einen eigenen Programmordner (bei der Einzeldatei
    sogar in ein Temporärverzeichnis, das nach dem Beenden verschwindet).
    Dorthin gehört nichts geschrieben -- Einstellungen und Protokoll bleiben
    deshalb neben der EXE.
    """
    gepackt = getattr(sys, "_MEIPASS", "")
    if gepackt:
        return Path(gepackt)
    return Path(__file__).resolve().parent.parent


KONFIG_DATEI = anwendungsordner() / "einstellungen.json"
JOURNAL_DATEI = anwendungsordner() / "journal.jsonl"
SPERR_DATEI = anwendungsordner() / "faxfinity.lock"
PROTOKOLL_DATEI = anwendungsordner() / "faxfinity.log"

# Kategorien, die das Modell wählen darf. Bewusst eine geschlossene Liste:
# frei erfundene Kategorien haben in der Vorgängerversion zu Dateinamen wie
# "Befreiung_von_Zuzahlungen_für_das_Jahr_2025_AOK_Bayern_..." geführt.
STANDARD_KATEGORIEN = [
    "Arztbrief",
    "Befund",
    "Labor",
    "Rezeptanforderung",
    "Medikationsplan",
    "Überweisung",
    "Bestellung",
    "Sturzprotokoll",
    "Krankenkasse",
    "Kommunikation",
    # Eine Praxis bekommt auch Post, die mit Patienten nichts zu tun hat --
    # Handwerker, Lieferanten, Wartungsverträge.
    "Rechnung",
    "Werbung",
    "Sonstiges",
]

# Kategorien, bei denen ein Patientenname weder erwartet noch in den Dateinamen
# übernommen wird.
KATEGORIEN_OHNE_PATIENT = {"Werbung", "Bestellung"}


@dataclass
class Einstellungen:
    # ── Ordner ────────────────────────────────────────────────────────────
    # Ziel und Archiv nehmen entweder einen vollständigen Pfad ("D:\Faxe\Fertig",
    # "\\\\server\\freigabe\\Faxe") oder einen Namen, der dann als Unterordner
    # des Eingangs gilt. Leer bedeutet "Umbenannt" beziehungsweise "Archiv".
    eingangsordner: str = ""
    zielordner: str = ""
    archivordner: str = ""

    # ── Eigene Praxis (Empfänger — darf nie als Absender erkannt werden) ──
    praxis_name: str = ""
    praxis_strasse: str = ""
    praxis_faxnummer: str = ""

    # ── Ollama ────────────────────────────────────────────────────────────
    ollama_url: str = "http://localhost:11434"
    ollama_modell: str = ""  # leer = beim Start automatisch wählen
    ollama_timeout: int = 120
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "30m"  # Modell im VRAM halten, nicht pro Fax neu laden
    # Denkmodelle (qwen3 u.a.) erzeugen vor der Antwort Gedankengänge. Das kostet
    # etwa die doppelte Zeit je Fax, traf im Test an den echten Faxen aber
    # spürbar besser -- Kategorie und Patient stimmten häufiger. Abschaltbar,
    # wenn der Durchsatz wichtiger ist als die Trefferquote.
    ollama_denkmodus: bool = True

    # ── OCR ───────────────────────────────────────────────────────────────
    tesseract_pfad: str = ""  # leer = automatisch suchen
    ocr_sprachdaten: str = ""  # leer = Ordner "tessdata" neben der Anwendung
    ocr_sprache: str = "deu"
    max_seiten: int = 2

    # ── Oberfläche ────────────────────────────────────────────────────────
    # Standardmäßig hört die Oberfläche nur auf 127.0.0.1 und ist damit vom
    # Netz aus nicht erreichbar. Wird das eingeschaltet, kann jeder im
    # Praxisnetz die Oberfläche öffnen -- samt Patientennamen im Protokoll und
    # ohne Anmeldung. Bewusst abschaltbar und standardmäßig aus.
    netzwerkzugriff: bool = False

    # ── Verarbeitung ──────────────────────────────────────────────────────
    scan_intervall: int = 60
    auto_scan: bool = True
    kategorien: list[str] = field(default_factory=lambda: list(STANDARD_KATEGORIEN))
    umlaute_umschreiben: bool = False  # True → "Müller" wird zu "Mueller"
    max_dateiname_laenge: int = 120

    # ── Alte Schlüsselnamen → neue (Migration von FaxFinity 1.x) ──────────
    _MIGRATION = {
        "ollama_model": "ollama_modell",
        "eigener_name": "praxis_name",
        "scan_interval": "scan_intervall",
        "auto_scan_active": "auto_scan",
        "max_pages_to_scan": "max_seiten",
        "unterordner_ziel": "zielordner",
        "unterordner_archiv": "archivordner",
    }

    @classmethod
    def laden(cls, pfad: Path) -> "Einstellungen":
        if not pfad.exists():
            return cls()
        try:
            # utf-8-sig statt utf-8: Windows-Editoren wie Notepad setzen beim
            # Speichern eine Bytefolge an den Dateianfang (BOM), an der ein
            # strenger JSON-Leser scheitert. Ohne diese Nachsicht verlöre
            # FaxFinity nach jedem Bearbeiten von Hand alle Einstellungen.
            rohdaten = json.loads(pfad.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as fehler:
            # Lautlos auf Vorgaben zurückzufallen wäre die schlechteste Variante:
            # der Dienst liefe scheinbar normal, nur ohne Eingangsordner.
            logger.error(
                "Einstellungen in %s sind nicht lesbar (%s). Es gelten die "
                "Vorgabewerte -- bitte in der Oberfläche neu eintragen.",
                pfad, fehler,
            )
            return cls()

        for alt, neu in cls._MIGRATION.items():
            if alt in rohdaten and neu not in rohdaten:
                rohdaten[neu] = rohdaten.pop(alt)

        # Alte Kategorien lagen als Komma-String vor.
        kat = rohdaten.get("kategorien") or rohdaten.get("dokumenten_kategorien")
        if isinstance(kat, str):
            rohdaten["kategorien"] = [k.strip() for k in kat.split(",") if k.strip()]

        erlaubt = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in rohdaten.items() if k in erlaubt})

    def speichern(self, pfad: Path) -> None:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        # Atomar schreiben, damit ein Absturz die Konfiguration nicht zerstört.
        temp = pfad.with_suffix(".tmp")
        temp.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temp, pfad)

    # ── Abgeleitete Pfade ─────────────────────────────────────────────────
    @property
    def eingang(self) -> Path:
        return Path(self.eingangsordner)

    def _ordner(self, angabe: str, vorgabe: str) -> Path:
        """Vollständigen Pfad übernehmen, einen Namen als Unterordner deuten."""
        pfad = Path(angabe.strip() or vorgabe)
        return pfad if pfad.is_absolute() else self.eingang / pfad

    @property
    def archiv(self) -> Path:
        return self._ordner(self.archivordner, "Archiv")

    @property
    def ziel(self) -> Path:
        return self._ordner(self.zielordner, "Umbenannt")

    def ordner_anlegen(self) -> None:
        for ordner in (self.archiv, self.ziel):
            ordner.mkdir(parents=True, exist_ok=True)

    def eingang_ist_nutzbar(self) -> bool:
        return bool(self.eingangsordner) and self.eingang.is_dir()

    def ordner_beanstanden(self) -> str:
        """Ordnereinstellungen prüfen. Leerer Text heißt: alles in Ordnung.

        Der wichtigste Fall ist ein Ziel- oder Archivordner, der auf den
        Eingang zeigt: die abgelegte Datei läge dann wieder im Eingang und
        würde bei jedem Durchlauf erneut verarbeitet -- endlos.
        """
        if not self.eingangsordner.strip():
            return "Es ist kein Eingangsordner eingetragen"
        if not self.eingang.is_dir():
            return f"Eingangsordner nicht erreichbar: {self.eingangsordner}"

        def gleich(a: Path, b: Path) -> bool:
            # Windows unterscheidet keine Groß-/Kleinschreibung in Pfaden, und
            # der Eingang kann als "Z:\Fax" oder "Z:\Fax\." eingetragen sein.
            return os.path.normcase(os.path.normpath(a.resolve())) == os.path.normcase(
                os.path.normpath(b.resolve())
            )

        if gleich(self.ziel, self.eingang):
            return (
                "Der Ausgangsordner darf nicht der Eingangsordner sein -- "
                "umbenannte Faxe würden sonst endlos erneut verarbeitet"
            )
        if gleich(self.archiv, self.eingang):
            return (
                "Der Archivordner darf nicht der Eingangsordner sein -- "
                "Sicherungskopien würden sonst erneut verarbeitet"
            )
        if gleich(self.ziel, self.archiv):
            return "Ausgangs- und Archivordner müssen sich unterscheiden"
        return ""

    @property
    def gueltige_kategorien(self) -> list[str]:
        """Kategorienliste, die garantiert 'Sonstiges' als Auffangbecken enthält."""
        kats = [k for k in self.kategorien if k.strip()]
        if "Sonstiges" not in kats:
            kats.append("Sonstiges")
        return kats
