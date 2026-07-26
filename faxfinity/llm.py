"""Ollama-Anbindung mit erzwungenem JSON-Schema.

Der entscheidende Unterschied zur Vorgängerversion: Ollama bekommt über das
Feld `format` ein JSON-Schema und kann damit gar keine unparsebare Antwort mehr
erzeugen. Die drei Ebenen aus Regex-Reparaturversuchen, die vorher nötig waren,
entfallen ersatzlos -- ebenso frei erfundene Kategorien, weil die Kategorie als
Aufzählung im Schema steht.
"""

from __future__ import annotations

import json
import logging
import re

import requests

from .models import Analyse, Faxkopf, Quelle

logger = logging.getLogger(__name__)

# Nach Eignung sortiert: klein genug für 8 GB VRAM, gut genug im Deutschen.
BEVORZUGTE_MODELLE = [
    "qwen3:8b",
    "gemma3:4b",
    "qwen2.5:7b",
    "llama3.1:8b",
    "mistral:7b",
    "gemma3:12b",
]

# Antworten wie "nicht erkennbar" hat die Vorgängerversion wörtlich in die
# Dateinamen übernommen ("..._nicht_erkannt.pdf"). Hier fliegen sie raus.
LEERANTWORTEN = {
    "", "-", "--", "n/a", "na", "n.a.", "k.a.", "k. a.", "none", "null",
    "unbekannt", "unbekannter absender", "keine angabe", "keine angaben",
    "nicht erkennbar", "nicht erkannt", "nicht ersichtlich", "nicht angegeben",
    "nicht vorhanden", "nicht bekannt", "kein patient", "kein absender",
    "leer", "unklar", "unbestimmt", "unleserlich", "nicht lesbar",
}

# Formelhaftes, das gerne als Patientenname durchrutscht.
FLOSKELN = re.compile(
    r"mit freundlich|freundlichen gr|hochachtungsvoll|sehr geehrte|"
    r"betreff|anrede|vorname|nachname|geburtsdatum|geb\.?datum|patient",
    re.I,
)

# Reste der Fax-Kopfzeile, die das Modell gern in den Absender übernimmt --
# beobachtet: "Stadt-Apotheke S. 01/01".
KOPFZEILENRESTE = re.compile(
    r"\b(?:S|P|Seite|Page)[.,]?\s*\d{1,3}\s*(?:/|von|of)\s*\d{1,3}\b"
    r"|\b\d{1,3}\s*/\s*\d{1,3}\b"
    r"|\b\d{1,2}[:.]\d{2}(?::\d{2})?\b"
    r"|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
    re.I,
)

# Einleitungen einer Fachrichtung: "Facharzt für Innere Medizin" -> "Innere Medizin".
FACHRICHTUNG_VORSPANN = re.compile(
    r"^(?:fach)?(?:arzt|ärztin|arztpraxis|praxis|zentrum|abteilung|klinik)"
    r"\s*(?:für|fuer)?\s*",
    re.I,
)

# Absender, Empfänger, Betreff und Patient stehen im Geschäftsbrief oben. Der
# Rest kostet nur Zeit -- und bringt Denkmodelle aus dem Tritt: an einem echten
# Laborfax stieg die Antwortzeit von 8 auf 114 Sekunden, sobald die Laborwerte
# am Seitenende mitgeschickt wurden. Das Ergebnis war identisch.
ZEICHEN_LIMIT = 2500


class OllamaFehler(RuntimeError):
    pass


def _schema(kategorien: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "kategorie": {"type": "string", "enum": kategorien},
            "empfaenger": {
                "type": "string",
                "description": "An wen ist das Fax adressiert (die eigene Praxis)",
            },
            "absender_organisation": {
                "type": "string",
                "description": "Absendende Einrichtung, Firma, Klinik oder Apotheke",
            },
            "absender_person": {
                "type": "string",
                "description": "Absendende Person, falls genannt, z.B. 'Dr. Müller'",
            },
            "absender_kurz": {
                "type": "string",
                "description": (
                    "Kurzform des Absenders für einen Dateinamen, höchstens drei "
                    "Wörter, ohne Rechtsform, ohne Adresse, z.B. 'Uniklinik Würzburg' "
                    "oder 'Dr. Müller'"
                ),
            },
            "fachrichtung": {
                "type": "string",
                "description": "Medizinische Fachrichtung des Absenders, sonst leer",
            },
            "patient_nachname": {"type": "string"},
            "patient_vorname": {"type": "string"},
            "sicherheit": {"type": "string", "enum": ["hoch", "mittel", "niedrig"]},
        },
        "required": [
            "kategorie", "empfaenger", "absender_organisation", "absender_person",
            "absender_kurz", "fachrichtung", "patient_nachname", "patient_vorname",
            "sicherheit",
        ],
    }


def _systemtext(praxis: str, kategorien: list[str]) -> str:
    return (
        "Du wertest eingehende Faxe einer Allgemeinarztpraxis aus und gibst "
        "ausschließlich Werte zurück, die wörtlich im Text stehen.\n\n"
        f"EMPFÄNGER DIESER PRAXIS: {praxis}\n"
        "Diese Praxis ist immer der Empfänger und niemals der Absender. Trage sie "
        "in 'empfaenger' ein und halte sie aus allen Absenderfeldern heraus.\n\n"
        "Der Absender ist die Einrichtung, die das Fax geschickt hat: Klinik, "
        "Apotheke, Pflegeheim, Labor, Praxis oder Firma. Bei zweispaltigen "
        "Briefköpfen steht der Absender links, der Empfänger rechts.\n\n"
        "Der Patient ist die Person, um die es im Dokument geht, nicht der "
        "Unterzeichner und nicht der Absender.\n\n"
        f"Erlaubte Kategorien: {', '.join(kategorien)}.\n"
        "Zur Abgrenzung der leicht zu verwechselnden:\n"
        "- 'Arztbrief': ein Arzt schreibt der Praxis über einen Patienten. "
        "Sicherstes Merkmal ist die Anrede an den Kollegen ('Sehr geehrter Herr "
        "Kollege', 'wir danken für die Zuweisung'). Auch Konsiliarbericht, "
        "Entlassungsbrief und Befundbericht in Briefform sind Arztbriefe -- das "
        "Wort 'Bericht' im Betreff ändert daran nichts.\n"
        "- 'Befund': ein reines Ergebnisdokument ohne Briefform, etwa ein "
        "Laborausdruck oder ein Messprotokoll, ohne Anrede und Unterschrift.\n"
        "- 'Rechnung' bleibt eine Rechnung, auch wenn der Absender aus dem "
        "Gesundheitswesen kommt.\n"
        "- 'Werbung' ist unverlangte Reklame, auch wenn sie wie ein Angebot "
        "aussieht.\n"
        "Wähle 'Sonstiges', sobald keine der übrigen Kategorien wirklich passt. "
        "'Sonstiges' ist eine richtige Antwort und kein Eingeständnis: eine "
        "Arztpraxis bekommt auch Post, die mit Patienten nichts zu tun hat -- "
        "von Handwerkern, Lieferanten, Behörden. Eine erzwungene medizinische "
        "Kategorie richtet mehr Schaden an als 'Sonstiges'.\n\n"
        "Steht etwas nicht im Text, lass das Feld leer. Rate nicht und erfinde "
        "nichts. Setze 'sicherheit' auf 'niedrig', wenn der Text zu lückenhaft ist."
    )


def _benutzertext(text: str, kopf: Faxkopf) -> str:
    teile = []
    if kopf:
        hinweis = "Kopfzeile des sendenden Faxgeräts"
        if kopf.absender:
            hinweis += f" nennt als Absender: '{kopf.absender}'"
        if kopf.faxnummer:
            hinweis += f" (Nummer {kopf.faxnummer})"
        teile.append(
            hinweis + ". Das ist ein starker Hinweis, aber prüfe ihn am Text."
        )
    teile.append("Texterkennung des Fax (kann Fehler enthalten):\n\n" + text)
    return "\n\n".join(teile)


def _saeubern(wert) -> str:
    if not isinstance(wert, str):
        return ""
    wert = re.sub(r"\s+", " ", wert).strip(" .,;:-")
    if wert.lower() in LEERANTWORTEN:
        return ""
    return wert


def _absender_saeubern(wert) -> str:
    """Zusätzlich die Überbleibsel der Fax-Kopfzeile entfernen."""
    wert = _saeubern(wert)
    if not wert:
        return ""
    wert = KOPFZEILENRESTE.sub(" ", wert)
    # Einzelne Ziffern am Ende sind Reste des Seitenzählers, den die
    # Texterkennung verstümmelt hat: aus "STADTAPOTHEKE S. 01/01" wurde
    # "STADTAPOTHEKE 5" und daraus der Name "Stadtapotheke-5".
    wert = re.sub(r"\s+\d{1,2}\s*$", "", wert)
    wert = re.sub(r"\s+", " ", wert).strip(" .,;:-")
    return "" if wert.lower() in LEERANTWORTEN else wert


def _fachrichtung_saeubern(wert) -> str:
    wert = _saeubern(wert)
    gekuerzt = FACHRICHTUNG_VORSPANN.sub("", wert).strip()
    # Nur übernehmen, wenn nach dem Kürzen noch etwas Aussagekräftiges steht.
    return gekuerzt if len(gekuerzt) >= 4 else wert


class Ollama:
    def __init__(
        self,
        url: str = "http://localhost:11434",
        modell: str = "",
        timeout: int = 120,
        num_ctx: int = 8192,
        keep_alive: str = "30m",
        denkmodus: bool = False,
    ):
        self.url = url.rstrip("/")
        self.modell = modell
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.denkmodus = denkmodus

    # ── Serverzustand ─────────────────────────────────────────────────────
    def erreichbar(self) -> bool:
        try:
            requests.get(f"{self.url}/api/tags", timeout=5).raise_for_status()
            return True
        except requests.RequestException:
            return False

    def modelle(self) -> list[str]:
        try:
            antwort = requests.get(f"{self.url}/api/tags", timeout=10)
            antwort.raise_for_status()
            return sorted(m["name"] for m in antwort.json().get("models", []))
        except (requests.RequestException, KeyError, ValueError) as fehler:
            logger.warning("Modelliste nicht abrufbar: %s", fehler)
            return []

    def modell_waehlen(self) -> str:
        """Konfiguriertes Modell nehmen, sonst das beste installierte."""
        vorhanden = self.modelle()
        if self.modell and self.modell in vorhanden:
            return self.modell
        if self.modell:
            logger.warning("Modell '%s' ist nicht installiert", self.modell)

        for bevorzugt in BEVORZUGTE_MODELLE:
            for name in vorhanden:
                if name == bevorzugt or name.startswith(bevorzugt + "-"):
                    return name
        if vorhanden:
            return vorhanden[0]
        raise OllamaFehler("In Ollama ist kein Modell installiert")

    # ── Auswertung ────────────────────────────────────────────────────────
    def auswerten(
        self,
        text: str,
        kopf: Faxkopf,
        praxis: str,
        kategorien: list[str],
        denken: bool = False,
    ) -> Analyse:
        """Ein Fax auswerten.

        `denken` schaltet den Denkmodus zu: etwa dreifache Laufzeit, dafür
        deutlich zuverlässiger bei Kategorie und Patientenname. Wann sich das
        lohnt, entscheidet die Verarbeitungskette -- die sieht als Einzige, ob
        der Praxisfilter eingegriffen hat.
        """
        modell = self.modell_waehlen()
        anfrage = {
            "model": modell,
            "messages": [
                {"role": "system", "content": _systemtext(praxis, kategorien)},
                {"role": "user", "content": _benutzertext(text[:ZEICHEN_LIMIT], kopf)},
            ],
            "stream": False,
            "format": _schema(kategorien),
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
            "keep_alive": self.keep_alive,
            # Modelle ohne Denkmodus ignorieren das Feld.
            "think": denken,
        }

        try:
            antwort = requests.post(
                f"{self.url}/api/chat", json=anfrage, timeout=self.timeout
            )
            antwort.raise_for_status()
            inhalt = antwort.json()["message"]["content"]
        except requests.exceptions.Timeout as fehler:
            raise OllamaFehler(f"Zeitüberschreitung nach {self.timeout}s") from fehler
        except requests.exceptions.ConnectionError as fehler:
            raise OllamaFehler(f"Ollama unter {self.url} nicht erreichbar") from fehler
        except (requests.RequestException, KeyError, ValueError) as fehler:
            raise OllamaFehler(f"Ollama-Fehler: {fehler}") from fehler

        try:
            daten = json.loads(inhalt)
        except json.JSONDecodeError as fehler:
            # Kann bei erzwungenem Schema praktisch nicht auftreten.
            raise OllamaFehler(f"Antwort war kein JSON: {inhalt[:200]}") from fehler

        return self._zu_analyse(daten, kategorien)

    @staticmethod
    def _zu_analyse(daten: dict, kategorien: list[str]) -> Analyse:
        organisation = _absender_saeubern(daten.get("absender_organisation"))
        person = _absender_saeubern(daten.get("absender_person"))
        kurz = _absender_saeubern(daten.get("absender_kurz")) or organisation or person

        nachname = _saeubern(daten.get("patient_nachname"))
        vorname = _saeubern(daten.get("patient_vorname"))
        # Grußformeln und Feldbeschriftungen sind keine Namen.
        if FLOSKELN.search(nachname):
            nachname = ""
        if FLOSKELN.search(vorname):
            vorname = ""

        kategorie = _saeubern(daten.get("kategorie"))
        if kategorie not in kategorien:
            kategorie = "Sonstiges"

        sicherheit = _saeubern(daten.get("sicherheit")).lower()
        if sicherheit not in {"hoch", "mittel", "niedrig"}:
            sicherheit = "niedrig"

        return Analyse(
            kategorie=kategorie,
            absender=" ".join(t for t in (organisation, person) if t).strip(),
            absender_kurz=kurz,
            fachrichtung=_fachrichtung_saeubern(daten.get("fachrichtung")),
            patient_nachname=nachname,
            patient_vorname=vorname,
            sicherheit=sicherheit,
            quelle=Quelle.LLM,
        )
