"""Erstmalige Einrichtung prüfen und Fehlendes nachinstallieren.

Wird von "Einrichten.bat" aufgerufen. Die Prüfungen stehen bewusst hier und
nicht in der Batchdatei: cmd.exe liest Batchdateien byteweise und merkt sich
nach jedem Befehl die Dateiposition. Enthält die Datei Mehrbyte-Zeichen --
schon ein Umlaut oder ein Rahmenstrich genügt --, verschieben sich die
Offsets und cmd springt mitten in eine Zeile. Das ergibt Fehlermeldungen über
Befehle wie "lse" oder "lent".
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MODELL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434"

OK, WARNUNG, FEHLER = "[ok]", "[!]", "[X]"


def schreiben(zeile: str = "") -> None:
    """Ausgeben, auch wenn die Konsole keine Umlaute darstellen kann."""
    try:
        print(zeile)
    except UnicodeEncodeError:
        print(zeile.encode("ascii", "replace").decode("ascii"))


def ueberschrift(text: str) -> None:
    schreiben()
    schreiben(text)
    schreiben("-" * len(text))


def laufen_lassen(befehl: list[str], zeitlimit: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(befehl, timeout=zeitlimit, text=True, encoding="utf-8", errors="replace")


def einfangen(befehl: list[str], zeitlimit: int = 30) -> str:
    try:
        ergebnis = subprocess.run(
            befehl, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=zeitlimit,
        )
        return ergebnis.stdout if ergebnis.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ── Einzelprüfungen ──────────────────────────────────────────────────────
def python_pruefen() -> bool:
    ueberschrift("Python")
    schreiben(f"  {OK} {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 10):
        schreiben(f"  {FEHLER} FaxFinity braucht Python 3.10 oder neuer.")
        return False
    return True


def pakete_installieren() -> bool:
    ueberschrift("Python-Pakete")
    schreiben("  Installiere aus requirements.txt ...")
    ergebnis = laufen_lassen([
        sys.executable, "-m", "pip", "install", "--quiet",
        "--disable-pip-version-check", "-r", str(WURZEL / "requirements.txt"),
    ])
    if ergebnis.returncode != 0:
        schreiben(f"  {FEHLER} Installation fehlgeschlagen.")
        return False
    schreiben(f"  {OK} Pakete installiert")
    return True


def tesseract_pruefen() -> bool:
    ueberschrift("Texterkennung (Tesseract)")

    sys.path.insert(0, str(WURZEL))
    from faxfinity.ocr import finde_sprachdaten, finde_tesseract  # noqa: PLC0415

    pfad = finde_tesseract()
    if not pfad:
        schreiben(f"  {WARNUNG} Nicht gefunden, wird installiert ...")
        if laufen_lassen([
            "winget", "install", "--id", "UB-Mannheim.TesseractOCR",
            "--accept-source-agreements", "--accept-package-agreements", "--silent",
        ]).returncode != 0:
            schreiben(f"  {FEHLER} Automatische Installation fehlgeschlagen.")
            schreiben("      Bitte von Hand: winget install UB-Mannheim.TesseractOCR")
            return False
        pfad = finde_tesseract()
        if not pfad:
            schreiben(f"  {FEHLER} Auch nach der Installation nicht gefunden.")
            schreiben("      Bitte den Rechner neu starten und noch einmal versuchen.")
            return False

    schreiben(f"  {OK} {pfad}")

    sprachdaten = finde_sprachdaten()
    if not sprachdaten or not (Path(sprachdaten) / "deu.traineddata").is_file():
        schreiben(f"  {FEHLER} Deutsche Sprachdaten fehlen.")
        schreiben(f"      Erwartet: {WURZEL / 'tessdata' / 'best' / 'deu.traineddata'}")
        schreiben("      Der Ordner 'tessdata' gehoert mit zur Auslieferung.")
        return False
    schreiben(f"  {OK} Deutsche Sprachdaten: {sprachdaten}")
    return True


def ollama_pruefen() -> bool:
    ueberschrift("Sprachmodell (Ollama)")

    if not shutil.which("ollama"):
        schreiben(f"  {WARNUNG} Ollama ist nicht installiert.")
        schreiben("      Von ollama.com herunterladen, danach dieses Skript erneut starten.")
        return False

    sys.path.insert(0, str(WURZEL))
    from faxfinity.llm import Ollama  # noqa: PLC0415

    kunde = Ollama(url=OLLAMA_URL)
    if not kunde.erreichbar():
        schreiben(f"  {WARNUNG} Ollama laeuft nicht ({OLLAMA_URL}).")
        schreiben("      Ollama starten, danach dieses Skript erneut ausfuehren.")
        return False
    schreiben(f"  {OK} Ollama laeuft")

    vorhanden = kunde.modelle()
    if MODELL in vorhanden:
        schreiben(f"  {OK} Modell {MODELL} vorhanden")
        return True

    schreiben(f"  {WARNUNG} Modell {MODELL} fehlt, wird geladen (rund 5 GB) ...")
    if laufen_lassen(["ollama", "pull", MODELL], zeitlimit=3600).returncode != 0:
        schreiben(f"  {FEHLER} Herunterladen fehlgeschlagen.")
        schreiben(f"      Bitte von Hand: ollama pull {MODELL}")
        return False
    schreiben(f"  {OK} Modell {MODELL} geladen")
    return True


# ── Ablauf ───────────────────────────────────────────────────────────────
def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    schreiben()
    schreiben("FaxFinity einrichten")
    schreiben("====================")

    if not python_pruefen() or not pakete_installieren():
        return 1

    # Ab hier sind Fehler nicht zwingend fatal: FaxFinity startet auch ohne
    # Ollama und meldet den Zustand dann in der Oberflaeche.
    bereit = tesseract_pruefen()
    bereit = ollama_pruefen() and bereit

    ueberschrift("Ergebnis")
    if bereit:
        schreiben(f"  {OK} Alles bereit.")
        schreiben()
        schreiben("  Jetzt 'FaxFinity starten.bat' ausfuehren.")
        schreiben("  Danach in der Oberflaeche den Eingangsordner und die")
        schreiben("  Praxisdaten eintragen.")
    else:
        schreiben(f"  {WARNUNG} Es fehlt noch etwas (siehe oben).")
        schreiben()
        schreiben("  FaxFinity laesst sich trotzdem starten und zeigt in der")
        schreiben("  Oberflaeche an, was noch fehlt.")
    schreiben()
    return 0 if bereit else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        schreiben("\nAbgebrochen.")
        raise SystemExit(1) from None
