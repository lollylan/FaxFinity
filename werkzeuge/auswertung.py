"""Die Verarbeitungskette gegen einen Ordner echter Faxe laufen lassen.

Arbeitet auf einer Kopie, damit der Testbestand unberührt bleibt.

    python werkzeuge/auswertung.py <ordner> [--modell qwen3:8b] [--anzahl 10]
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faxfinity.config import Einstellungen  # noqa: E402
from faxfinity.journal import Journal  # noqa: E402
from faxfinity.models import Ergebnis  # noqa: E402
from faxfinity.pipeline import Verarbeiter, VoruebergehenderFehler  # noqa: E402

PRAXIS = "Dr. med. Florian Rasche"
STRASSE = "Huttenstr. 6, 97072 Würzburg"
FAXNUMMER = "0931/76264"


def main() -> int:
    zerleger = argparse.ArgumentParser()
    zerleger.add_argument("ordner", type=Path)
    zerleger.add_argument("--modell", default="")
    zerleger.add_argument("--anzahl", type=int, default=0)
    zerleger.add_argument("--ausfuehrlich", action="store_true")
    argumente = zerleger.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if argumente.ausfuehrlich else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    quellen = sorted(argumente.ordner.glob("*.pdf"))
    if argumente.anzahl:
        quellen = quellen[: argumente.anzahl]
    if not quellen:
        print(f"Keine PDFs in {argumente.ordner}")
        return 1

    with tempfile.TemporaryDirectory(prefix="faxfinity_test_") as arbeitsordner:
        eingang = Path(arbeitsordner) / "Eingang"
        eingang.mkdir()
        for quelle in quellen:
            shutil.copy2(quelle, eingang / quelle.name)

        einstellungen = Einstellungen(
            eingangsordner=str(eingang),
            praxis_name=PRAXIS,
            praxis_strasse=STRASSE,
            praxis_faxnummer=FAXNUMMER,
            ollama_modell=argumente.modell,
            tesseract_pfad="",
        )
        # Sprachdaten liegen im Projektordner, nicht in Program Files.
        protokoll = Journal(Path(arbeitsordner) / "journal.jsonl")
        verarbeiter = Verarbeiter(einstellungen, protokoll)

        modell = verarbeiter.ollama.modell_waehlen()
        print(f"Modell: {modell}   Dateien: {len(quellen)}\n")
        print(f"{'Quelldatei':<34} {'s':>5}  {'Sich.':<7} Neuer Name")
        print("-" * 128)

        zaehler: dict[str, int] = {}
        gesamtzeit = 0.0

        for pdf in sorted(eingang.glob("*.pdf")):
            name = pdf.name
            start = time.time()
            try:
                ergebnis = verarbeiter.verarbeiten(pdf)
            except VoruebergehenderFehler as fehler:
                print(f"{name[:33]:<34} {'':>5}  WARTET   {fehler}")
                zaehler["voruebergehend"] = zaehler.get("voruebergehend", 0) + 1
                continue

            dauer = time.time() - start
            gesamtzeit += dauer
            protokoll.eintragen(ergebnis)
            zaehler[ergebnis.ergebnis.value] = zaehler.get(ergebnis.ergebnis.value, 0) + 1

            markierung = {
                Ergebnis.ERFOLG: "ok",
                Ergebnis.UNSICHER: "unsicher",
                Ergebnis.DUPLIKAT: "duplikat",
                Ergebnis.FEHLER: "FEHLER",
            }[ergebnis.ergebnis]

            print(
                f"{name[:33]:<34} {dauer:5.1f}  {ergebnis.analyse.sicherheit:<7} "
                f"{ergebnis.zieldatei}"
            )
            if ergebnis.meldung:
                print(f"{'':>34}  -> {markierung}: {ergebnis.meldung}")
            for hinweis in ergebnis.analyse.hinweise:
                print(f"{'':>34}  -> {hinweis}")

        print("-" * 128)
        anzahl = max(1, sum(zaehler.values()))
        print(
            f"{sum(zaehler.values())} Dateien in {gesamtzeit:.0f}s "
            f"({gesamtzeit / anzahl:.1f}s je Fax)"
        )
        for schluessel, wert in sorted(zaehler.items()):
            print(f"  {schluessel:<16} {wert}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
