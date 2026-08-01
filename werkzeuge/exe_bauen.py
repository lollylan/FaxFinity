"""Aus FaxFinity eine EXE machen, die ohne Python und ohne Installation läuft.

    python werkzeuge/exe_bauen.py

Ergebnis ist `dist/FaxFinity/` mit einer einzigen sichtbaren Datei --
`FaxFinity.exe` -- und daneben, als ZIP verpackt, das, was an eine Praxis
weitergegeben wird. Doppelklick genügt; der Browser öffnet sich von selbst.

Mitgeliefert werden Python samt allen Paketen, die Weboberfläche, die deutschen
Sprachdaten und Tesseract. Übrig bleibt genau eine Voraussetzung: Ollama. Das
lässt sich nicht sinnvoll mitliefern -- es bringt über ein Gigabyte
Grafikkartenbibliotheken mit und hält sich selbst aktuell. Wer FaxFinity
startet, ohne dass Ollama da ist, bekommt in der Oberfläche einen Knopf zur
Bezugsquelle; das Sprachmodell holt FaxFinity danach von allein.

Tesseract wird aus der Installation dieses Rechners übernommen -- Apache-2.0,
die Weitergabe ist ausdrücklich erlaubt. Mitgenommen wird nur, was tesseract.exe
wirklich braucht: von 51 Bibliotheken im Programmordner sind es 26, der Rest
gehört zu den Trainingswerkzeugen.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from faxfinity import __version__  # noqa: E402
from faxfinity.ocr import finde_tesseract  # noqa: E402

BAU = WURZEL / "build"
MITGELIEFERT = BAU / "mitgeliefert"
ZIEL = WURZEL / "dist"
NAME = "FaxFinity"

OK, WARNUNG, FEHLER = "[ok]", "[!]", "[X]"

KURZANLEITUNG = """FaxFinity
=========

1. Diesen Ordner irgendwohin auf die Festplatte kopieren, zum Beispiel
   nach C:\\FaxFinity. (Aus dem ZIP heraus starten funktioniert nicht.)

2. FaxFinity.exe doppelklicken. Der Browser oeffnet sich von selbst.

3. Fehlt Ollama, steht das oben auf der Seite, mit einem Knopf zum
   Herunterladen. Nach dessen Installation holt FaxFinity das
   Sprachmodell selbstaendig -- das dauert je nach Leitung eine
   Viertelstunde und muss nur einmal sein.

4. Unter "Einstellungen" den Eingangsordner und die Praxisdaten
   eintragen, dann speichern. Fertig.

Das Fenster darf jederzeit geschlossen werden; FaxFinity laeuft weiter.
Wieder aufrufen laesst sich die Oberflaeche mit
http://127.0.0.1:8757 oder durch nochmaliges Doppelklicken der EXE.

Beenden ueber den Knopf unten rechts in der Oberflaeche.
"""


def schreiben(zeile: str = "") -> None:
    try:
        print(zeile)
    except UnicodeEncodeError:
        print(zeile.encode("ascii", "replace").decode("ascii"))


def ueberschrift(text: str) -> None:
    schreiben()
    schreiben(text)
    schreiben("-" * len(text))


# ── Tesseract einsammeln ─────────────────────────────────────────────────
def _eingebundene_dlls(datei: Path) -> list[str]:
    """Namen der DLLs, die eine EXE oder DLL unmittelbar braucht.

    Gelesen wird die Importtabelle des PE-Kopfes von Hand. Die Alternative wäre
    ein zusätzliches Paket nur für diesen einen Zweck; für das Bauwerkzeug ist
    das die schlechtere Abhängigkeit als sechzig Zeilen Strukturauspacken.
    """
    roh = datei.read_bytes()
    if roh[:2] != b"MZ":
        return []
    pe = struct.unpack_from("<I", roh, 0x3C)[0]
    if roh[pe:pe + 4] != b"PE\0\0":
        return []

    sektionen_anzahl = struct.unpack_from("<H", roh, pe + 6)[0]
    optionaler_kopf = struct.unpack_from("<H", roh, pe + 20)[0]
    opt = pe + 24
    # Bei 64 Bit (PE32+, Kennung 0x20B) stehen die Verzeichnisse 16 Byte weiter.
    verzeichnisse = opt + (112 if struct.unpack_from("<H", roh, opt)[0] == 0x20B else 96)
    import_rva = struct.unpack_from("<I", roh, verzeichnisse + 8)[0]
    if not import_rva:
        return []

    sektionen = []
    erste = opt + optionaler_kopf
    for i in range(sektionen_anzahl):
        kopf = erste + i * 40
        virt_groesse, virt_adresse, roh_groesse, roh_zeiger = struct.unpack_from(
            "<IIII", roh, kopf + 8
        )
        sektionen.append((virt_adresse, max(virt_groesse, roh_groesse), roh_zeiger))

    def zu_dateiposition(rva: int) -> int | None:
        for adresse, groesse, zeiger in sektionen:
            if adresse <= rva < adresse + groesse:
                return zeiger + (rva - adresse)
        return None

    namen: list[str] = []
    eintrag = zu_dateiposition(import_rva)
    while eintrag is not None:
        felder = struct.unpack_from("<IIIII", roh, eintrag)
        if not any(felder):  # Nullsatz beendet die Tabelle
            break
        position = zu_dateiposition(felder[3])
        if position is not None:
            namen.append(roh[position:roh.index(b"\0", position)].decode("ascii", "replace"))
        eintrag += 20
    return namen


HERKUNFT = """Mitgelieferte Fremdsoftware
===========================

Der Ordner "tesseract" enthaelt Tesseract OCR und die Bibliotheken, die es zum
Laufen braucht, uebernommen aus dem Windows-Paket von UB Mannheim:

    https://github.com/UB-Mannheim/tesseract/wiki

Tesseract und Leptonica stehen unter der Apache-Lizenz 2.0; deren vollstaendiger
Text steht in LICENSE-Tesseract.txt. Die uebrigen Bibliotheken (unter anderem
zlib, libpng, libjpeg, libtiff, libwebp, OpenJPEG, libarchive, OpenSSL sowie die
Laufzeitbibliotheken von MinGW-w64) stehen unter ihren jeweils eigenen freien
Lizenzen; die Quellen und Lizenztexte sind ueber die obige Adresse erreichbar.

Der Ordner "_internal" enthaelt Python samt der verwendeten Pakete. Deren
Lizenztexte liegen dort in den jeweiligen .dist-info-Ordnern.

Die deutschen Sprachdaten (tessdata) stammen aus dem Projekt tessdata_best und
stehen ebenfalls unter der Apache-Lizenz 2.0.
"""


def lizenz_beilegen(quelle: Path, ziel: Path) -> bool:
    """Lizenztext und Herkunftshinweis mit ins Paket legen.

    Apache 2.0 verlangt, dass der Lizenztext jeder Weitergabe beiliegt -- und
    weitergegeben wird hier tatsaechlich: das ZIP geht an andere Praxen und
    liegt oeffentlich auf GitHub. Der UB-Mannheim-Installer legt die Lizenz
    unter doc/ ab, nicht neben tesseract.exe.
    """
    for kandidat in (
        quelle / "doc" / "LICENSE", quelle / "LICENSE",
        quelle / "LICENSE.txt", quelle / "COPYING",
    ):
        if kandidat.is_file():
            shutil.copy2(kandidat, ziel / "LICENSE-Tesseract.txt")
            (ziel / "HERKUNFT.txt").write_text(HERKUNFT, encoding="cp1252")
            return True
    return False


def tesseract_einsammeln(ziel: Path) -> bool:
    ueberschrift("Tesseract einsammeln")

    gefunden = finde_tesseract()
    if not gefunden:
        schreiben(f"  {FEHLER} Tesseract ist auf diesem Rechner nicht installiert.")
        schreiben("      Ohne Tesseract kann die EXE keine Faxe lesen.")
        schreiben("      Entweder: winget install UB-Mannheim.TesseractOCR")
        schreiben("      Oder bewusst ohne bauen: --ohne-tesseract")
        return False

    quelle = Path(gefunden).parent
    schreiben(f"  Quelle: {quelle}")

    vorhanden = {p.name.lower(): p for p in quelle.glob("*.dll")}
    noetig: set[str] = set()
    offen = [Path(gefunden)]
    while offen:
        datei = offen.pop()
        for name in _eingebundene_dlls(datei):
            klein = name.lower()
            if klein in vorhanden and klein not in noetig:
                noetig.add(klein)
                offen.append(vorhanden[klein])

    if ziel.exists():
        shutil.rmtree(ziel)
    ziel.mkdir(parents=True)
    shutil.copy2(gefunden, ziel / "tesseract.exe")
    for name in sorted(noetig):
        shutil.copy2(vorhanden[name], ziel / vorhanden[name].name)

    if not lizenz_beilegen(quelle, ziel):
        schreiben(f"  {FEHLER} Keine Lizenzdatei gefunden -- Tesseract steht unter "
                  "Apache 2.0 und darf ohne sie nicht weitergegeben werden.")
        return False

    groesse = sum(p.stat().st_size for p in ziel.iterdir())
    schreiben(f"  {OK} {len(noetig)} von {len(vorhanden)} Bibliotheken, "
              f"zusammen {groesse / 1e6:.0f} MB")

    probe = subprocess.run(
        [str(ziel / "tesseract.exe"), "--version"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if probe.returncode != 0:
        schreiben(f"  {FEHLER} Die eingesammelte Fassung läuft nicht:")
        schreiben("      " + (probe.stderr or "").strip()[:200])
        return False
    schreiben(f"  {OK} Probelauf: {(probe.stdout or '').splitlines()[0]}")
    return True


# ── Symbol ───────────────────────────────────────────────────────────────
def symbol_erzeugen(ziel: Path) -> Path | None:
    """Ein Programmsymbol zeichnen -- ein Blatt Papier auf blauem Grund.

    Wer nur eine EXE bekommt, sucht sie am Symbol. Das Standardsymbol von
    PyInstaller sähe aus wie jedes andere unbekannte Programm.
    """
    try:
        from PIL import Image, ImageDraw  # noqa: PLC0415
    except ImportError:
        return None

    kante = 256
    bild = Image.new("RGBA", (kante, kante), (0, 0, 0, 0))
    stift = ImageDraw.Draw(bild)
    stift.rounded_rectangle([0, 0, kante - 1, kante - 1], radius=56, fill=(42, 109, 244, 255))

    links, oben, rechts, unten, ecke = 66, 50, 190, 206, 36
    stift.polygon(
        [(links, oben), (rechts - ecke, oben), (rechts, oben + ecke), (rechts, unten), (links, unten)],
        fill=(255, 255, 255, 255),
    )
    stift.polygon(
        [(rechts - ecke, oben), (rechts - ecke, oben + ecke), (rechts, oben + ecke)],
        fill=(186, 208, 250, 255),
    )
    for nummer, y in enumerate(range(oben + 60, unten - 20, 24)):
        ende = rechts - (60 if nummer % 3 == 2 else 22)
        stift.rounded_rectangle([links + 22, y, ende, y + 9], radius=4, fill=(42, 109, 244, 150))

    ziel.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ziel, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ziel


# ── Bauen ────────────────────────────────────────────────────────────────
def pyinstaller_sicherstellen() -> bool:
    ueberschrift("PyInstaller")
    try:
        import PyInstaller  # noqa: PLC0415, F401

        schreiben(f"  {OK} Fassung {PyInstaller.__version__}")
        return True
    except ImportError:
        pass

    schreiben(f"  {WARNUNG} Nicht vorhanden, wird installiert ...")
    ergebnis = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "pyinstaller"], timeout=900
    )
    if ergebnis.returncode != 0:
        schreiben(f"  {FEHLER} Installation fehlgeschlagen.")
        return False
    schreiben(f"  {OK} Installiert")
    return True


def starter_schreiben() -> Path:
    """PyInstaller braucht ein Startskript, kein Modul."""
    BAU.mkdir(parents=True, exist_ok=True)
    pfad = BAU / "starter.py"
    pfad.write_text(
        '"""Von werkzeuge/exe_bauen.py erzeugt -- nicht von Hand ändern."""\n'
        "from faxfinity.__main__ import start\n\n"
        "raise SystemExit(start())\n",
        encoding="utf-8",
    )
    return pfad


# Pakete, die nur an einer Stelle beiläufig vorkommen und die FaxFinity nie
# aufruft. PyMuPDF bietet an, Tabellen als pandas-Datensatz herauszugeben, und
# schon zieht die Abhängigkeitssuche pandas, pyarrow und scipy mit herein --
# zusammen über 160 MB, die in keiner Praxis je ausgeführt würden.
UNNOETIG = ["tkinter", "PyInstaller", "pandas", "pyarrow", "scipy", "matplotlib"]


def bauen(einzeldatei: bool) -> bool:
    ueberschrift("EXE bauen")

    symbol = symbol_erzeugen(BAU / "faxfinity.ico")
    daten = [
        (WURZEL / "faxfinity" / "web" / "index.html", "faxfinity/web"),
        (WURZEL / "tessdata" / "best", "tessdata/best"),
    ]

    befehl = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", NAME,
        # Kein Konsolenfenster: in einer Praxis stünde es den ganzen Tag im Weg,
        # und ein versehentliches Schließen beendete die Verarbeitung. Alles,
        # was dort stünde, geht in faxfinity.log neben der EXE.
        "--windowed",
        "--onefile" if einzeldatei else "--onedir",
        # Bei der Einzeldatei legt PyInstaller die EXE unmittelbar in den
        # Zielordner. Damit beide Fassungen denselben Aufbau ergeben, bekommt
        # sie einen Ordner tiefer als Ziel.
        "--distpath", str(ZIEL / NAME if einzeldatei else ZIEL),
        "--workpath", str(BAU / "pyinstaller"),
        "--specpath", str(BAU),
        "--paths", str(WURZEL),
        # uvicorn lädt seine Protokoll- und Ereignisschleifen erst zur Laufzeit
        # nach; ohne dies fehlen sie im Paket und der Server startet nicht.
        "--collect-submodules", "uvicorn",
    ]
    for paket in UNNOETIG:
        befehl += ["--exclude-module", paket]
    if symbol:
        befehl += ["--icon", str(symbol)]
    for quelle, unterordner in daten:
        befehl += ["--add-data", f"{quelle}{os.pathsep}{unterordner}"]
    befehl.append(str(starter_schreiben()))

    schreiben(f"  Fassung: {'eine Datei' if einzeldatei else 'Ordner (startet schneller)'}")
    schreiben("  Das dauert ein paar Minuten ...")
    ergebnis = subprocess.run(befehl, cwd=WURZEL, timeout=3600)
    if ergebnis.returncode != 0:
        schreiben(f"  {FEHLER} PyInstaller ist gescheitert (siehe Ausgabe oben).")
        return False
    schreiben(f"  {OK} Gebaut")
    return True


def tesseract_danebenlegen() -> bool:
    """Tesseract neben die EXE stellen statt hinein.

    Nicht über --add-data: PyInstaller erkennt die DLLs im mitgegebenen Ordner
    und legt sie zusätzlich in den Programmordner -- Tesseract wäre dann zweimal
    im Paket, 121 MB umsonst. Nebenbei lässt sich so eine kaputte Installation
    austauschen, ohne neu zu bauen.
    """
    ziel = ZIEL / NAME / "tesseract"
    if ziel.exists():
        shutil.rmtree(ziel)
    shutil.copytree(MITGELIEFERT / "tesseract", ziel)
    return (ziel / "tesseract.exe").is_file()


# Dateien, die beim Ausprobieren im Zielordner entstehen. Sie enthalten die
# Ordnerpfade und Patientennamen des Rechners, auf dem gebaut wurde -- in ein
# ZIP, das an eine andere Praxis geht, gehören sie unter keinen Umständen.
LAUFZEITDATEIEN = {"einstellungen.json", "journal.jsonl", "faxfinity.lock"}


def _ist_laufzeitdatei(datei: Path) -> bool:
    return datei.name in LAUFZEITDATEIEN or datei.name.startswith("faxfinity.log")


def verpacken() -> Path | None:
    ueberschrift("Verpacken")

    ordner = ZIEL / NAME
    if not (ordner / f"{NAME}.exe").is_file():
        schreiben(f"  {FEHLER} {ordner / (NAME + '.exe')} fehlt.")
        return None

    (ordner / "Bitte lesen.txt").write_text(KURZANLEITUNG, encoding="cp1252")

    archiv = ZIEL / f"{NAME}-{__version__}-Windows.zip"
    archiv.unlink(missing_ok=True)
    uebersprungen = []
    with zipfile.ZipFile(archiv, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zip_datei:
        for datei in sorted(ordner.rglob("*")):
            if not datei.is_file():
                continue
            if _ist_laufzeitdatei(datei):
                uebersprungen.append(datei.name)
                continue
            zip_datei.write(datei, Path(NAME) / datei.relative_to(ordner))
    if uebersprungen:
        schreiben(f"  {OK} Nicht mitverpackt: {', '.join(sorted(set(uebersprungen)))}")

    entpackt = sum(p.stat().st_size for p in ordner.rglob("*") if p.is_file())
    schreiben(f"  {OK} {ordner} -- {entpackt / 1e6:.0f} MB entpackt")
    schreiben(f"  {OK} {archiv.name} -- {archiv.stat().st_size / 1e6:.0f} MB zum Weitergeben")
    return archiv


def main() -> int:
    zerleger = argparse.ArgumentParser(prog="exe_bauen", description=__doc__)
    zerleger.add_argument(
        "--einzeldatei", action="store_true",
        help="Python und die Pakete in die EXE selbst packen statt in einen "
             "Programmordner daneben; startet spürbar langsamer, weil sie sich "
             "bei jedem Start auspackt. Tesseract liegt auch dann daneben.",
    )
    zerleger.add_argument(
        "--ohne-tesseract", action="store_true",
        help="Tesseract nicht mitliefern (muss dann auf dem Zielrechner installiert sein)",
    )
    zerleger.add_argument("--kein-archiv", action="store_true", help="kein ZIP erzeugen")
    gewaehlt = zerleger.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    schreiben()
    schreiben(f"FaxFinity {__version__} als EXE bauen")
    schreiben("=" * 34)

    if sys.platform != "win32":
        schreiben(f"\n  {FEHLER} Eine Windows-EXE lässt sich nur unter Windows bauen.")
        return 1

    if not pyinstaller_sicherstellen():
        return 1

    mit_tesseract = not gewaehlt.ohne_tesseract
    if mit_tesseract and not tesseract_einsammeln(MITGELIEFERT / "tesseract"):
        return 1
    if not mit_tesseract:
        schreiben(f"\n  {WARNUNG} Ohne Tesseract gebaut -- auf dem Zielrechner muss es "
                  "installiert sein.")

    if not bauen(gewaehlt.einzeldatei):
        return 1

    if mit_tesseract and not tesseract_danebenlegen():
        schreiben(f"  {FEHLER} Tesseract ließ sich nicht neben die EXE legen.")
        return 1

    ergebnis = None if gewaehlt.kein_archiv else verpacken()
    if not gewaehlt.kein_archiv and ergebnis is None:
        return 1

    ueberschrift("Fertig")
    schreiben(f"  Weitergeben: {ergebnis if ergebnis else ZIEL / NAME}")
    schreiben()
    schreiben("  Auf dem Zielrechner braucht es nur noch Ollama.")
    schreiben("  Das Sprachmodell holt FaxFinity beim ersten Start von selbst.")
    schreiben()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        schreiben("\nAbgebrochen.")
        raise SystemExit(1) from None
