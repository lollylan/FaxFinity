"""Tests für die Verarbeitungskette einer einzelnen Datei.

Der Schwerpunkt liegt auf der Zusicherung, die dem Auftraggeber am wichtigsten
ist: kein Fax darf verlorengehen. Ollama wird dabei durch eine Attrappe ersetzt,
damit die Tests ohne laufenden Modellserver durchlaufen.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz

from faxfinity.config import Einstellungen
from faxfinity.journal import Journal
from faxfinity.llm import OllamaFehler
from faxfinity.models import Analyse, Ergebnis, Quelle
from faxfinity.pipeline import Verarbeiter, VoruebergehenderFehler

FAXTEXT = (
    "0931 2001122 MVZ für Labormedizin Nord S. 01/01\n"
    "Ärztliche Laborgemeinschaft Nord, Musterstraße 12, 97080 Würzburg\n"
    "An: Dr. med. Florian Rasche, Huttenstr. 6, 97072 Würzburg\n"
    "Endbefund für Patient Beispiel, Max, geboren am 03.05.1961\n"
    "Kleines Blutbild, Leukozyten 7.2, Hämoglobin 14.1, Thrombozyten 250\n"
)


def fax_anlegen(ziel: Path, text: str = FAXTEXT) -> Path:
    """Ein PDF mit Textebene erzeugen -- so bleibt die OCR außen vor."""
    dokument = fitz.open()
    seite = dokument.new_page()
    seite.insert_text((60, 80), text, fontsize=10)
    dokument.save(ziel)
    dokument.close()
    return ziel


class AttrappenOllama:
    """Ersatz für den Modellserver.

    `gruendliche_analyse` steht für das Ergebnis des zweiten Durchgangs mit
    Denkmodus, den die Verarbeitungskette bei dürftiger Erkennung anstößt.
    """

    def __init__(
        self,
        analyse: Analyse | None = None,
        fehler: Exception | None = None,
        gruendliche_analyse: Analyse | None = None,
    ):
        self.analyse = analyse
        self.gruendliche_analyse = gruendliche_analyse
        self.fehler = fehler
        self.aufrufe = 0
        self.denkaufrufe = 0

    def auswerten(self, text, kopf, praxis, kategorien, denken: bool = False) -> Analyse:
        self.aufrufe += 1
        if self.fehler:
            raise self.fehler
        if denken:
            self.denkaufrufe += 1
            return self.gruendliche_analyse or self.analyse
        return self.analyse


class Grundgeruest(unittest.TestCase):
    def aufbauen(self, analyse: Analyse | None = None, fehler: Exception | None = None):
        self.ordner = TemporaryDirectory()
        wurzel = Path(self.ordner.name)
        self.eingang = wurzel / "Eingang"
        self.eingang.mkdir()

        self.einstellungen = Einstellungen(
            eingangsordner=str(self.eingang),
            praxis_name="Dr. med. Florian Rasche",
            praxis_strasse="Huttenstr. 6, 97072 Würzburg",
            praxis_faxnummer="0931/76264",
        )
        self.journal = Journal(wurzel / "journal.jsonl")
        self.verarbeiter = Verarbeiter(self.einstellungen, self.journal)
        self.verarbeiter.ollama = AttrappenOllama(
            analyse
            or Analyse(
                kategorie="Labor",
                absender="MVZ für Labormedizin Nord",
                absender_kurz="MVZ Labormedizin",
                patient_nachname="Beispiel",
                patient_vorname="Max",
                sicherheit="hoch",
                quelle=Quelle.LLM,
            ),
            fehler,
        )
        return wurzel

    def tearDown(self):
        if hasattr(self, "ordner"):
            self.ordner.cleanup()


class ErfolgreicheVerarbeitung(Grundgeruest):
    def test_fax_wird_benannt_abgelegt_und_archiviert(self):
        self.aufbauen()
        quelle = fax_anlegen(self.eingang / "FAX2026_07_25_093424.pdf")
        urspruenglich = quelle.read_bytes()

        ergebnis = self.verarbeiter.verarbeiten(quelle)

        self.assertIs(ergebnis.ergebnis, Ergebnis.ERFOLG)
        self.assertEqual(
            ergebnis.zieldatei, "Labor_MVZ-Labormedizin_Beispiel-Max_"
            f"{ergebnis.eingang_am:%Y-%m-%d}.pdf"
        )
        self.assertFalse(quelle.exists(), "Die Datei muss den Eingang verlassen")

        abgelegt = self.einstellungen.ziel / ergebnis.zieldatei
        self.assertTrue(abgelegt.exists())
        self.assertEqual(abgelegt.read_bytes(), urspruenglich, "Inhalt darf sich nicht ändern")

    def test_sicherungskopie_bleibt_unveraendert_im_archiv(self):
        self.aufbauen()
        quelle = fax_anlegen(self.eingang / "FAX001.pdf")
        urspruenglich = quelle.read_bytes()

        ergebnis = self.verarbeiter.verarbeiten(quelle)

        archiviert = self.einstellungen.archiv / ergebnis.archivdatei
        self.assertTrue(archiviert.exists())
        self.assertEqual(archiviert.read_bytes(), urspruenglich)
        self.assertIn("FAX001.pdf", ergebnis.archivdatei)

    def test_textebene_wird_genutzt_statt_ocr(self):
        self.aufbauen()
        quelle = fax_anlegen(self.eingang / "FAX001.pdf")
        self.verarbeiter.tesseract = None  # OCR steht bewusst nicht zur Verfügung

        ergebnis = self.verarbeiter.verarbeiten(quelle)

        self.assertIs(ergebnis.ergebnis, Ergebnis.ERFOLG)
        self.assertEqual(self.verarbeiter.ollama.aufrufe, 1)


class NichtsGehtVerloren(Grundgeruest):
    def test_unlesbares_pdf_wird_trotzdem_abgelegt(self):
        self.aufbauen()
        kaputt = self.eingang / "kaputt.pdf"
        kaputt.write_bytes(b"%PDF-1.4 das ist kein gueltiges PDF")

        ergebnis = self.verarbeiter.verarbeiten(kaputt)

        self.assertIs(ergebnis.ergebnis, Ergebnis.FEHLER)
        self.assertTrue(ergebnis.zieldatei.startswith("FAX_"))
        self.assertFalse(kaputt.exists())
        self.assertTrue((self.einstellungen.ziel / ergebnis.zieldatei).exists())

    def test_leeres_fax_bekommt_den_notnagelnamen(self):
        self.aufbauen()
        leer = fax_anlegen(self.eingang / "leer.pdf", text=" ")
        self.verarbeiter.tesseract = None

        ergebnis = self.verarbeiter.verarbeiten(leer)

        self.assertTrue((self.einstellungen.ziel / ergebnis.zieldatei).exists())
        self.assertFalse(leer.exists())

    def test_zwei_faxe_mit_gleichem_namen_ueberschreiben_sich_nicht(self):
        self.aufbauen()
        erstes = self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "a.pdf"))
        # Zweites Fax mit anderem Inhalt, das denselben Namen erzeugen würde.
        zweites_pdf = fax_anlegen(self.eingang / "b.pdf", text=FAXTEXT + "Zusatzbefund\n")
        zweites = self.verarbeiter.verarbeiten(zweites_pdf)

        self.assertNotEqual(erstes.zieldatei, zweites.zieldatei)
        self.assertTrue((self.einstellungen.ziel / erstes.zieldatei).exists())
        self.assertTrue((self.einstellungen.ziel / zweites.zieldatei).exists())

    def test_voruebergehender_fehler_laesst_die_datei_liegen(self):
        # Ollama aus: das Fax soll warten, nicht namenlos abgelegt werden.
        self.aufbauen(fehler=OllamaFehler("Ollama nicht erreichbar"))
        quelle = fax_anlegen(self.eingang / "FAX001.pdf")

        with self.assertRaises(VoruebergehenderFehler):
            self.verarbeiter.verarbeiten(quelle)

        self.assertTrue(quelle.exists(), "Die Datei muss für einen neuen Versuch liegenbleiben")
        # Gesichert ist sie trotzdem schon.
        self.assertEqual(len(list(self.einstellungen.archiv.glob("*.pdf"))), 1)

    def test_notablage_nach_endgueltigem_aufgeben(self):
        self.aufbauen(fehler=OllamaFehler("Ollama nicht erreichbar"))
        quelle = fax_anlegen(self.eingang / "FAX001.pdf")

        ergebnis = self.verarbeiter.notablage(quelle, "Ollama dauerhaft nicht erreichbar")

        self.assertIs(ergebnis.ergebnis, Ergebnis.FEHLER)
        self.assertTrue(ergebnis.zieldatei.startswith("FAX_"))
        self.assertFalse(quelle.exists())
        self.assertTrue((self.einstellungen.ziel / ergebnis.zieldatei).exists())


class EigenePraxisWirdNichtZumAbsender(Grundgeruest):
    def test_erkannter_absender_ist_die_eigene_praxis(self):
        self.aufbauen(
            Analyse(
                kategorie="Befund",
                absender="Dr. med. Florian Rasche",
                absender_kurz="Dr. med. Florian Rasche",
                patient_nachname="Beispiel",
                sicherheit="hoch",
            )
        )
        ergebnis = self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "FAX001.pdf"))

        self.assertNotIn("Rasche", ergebnis.zieldatei)
        self.assertEqual(ergebnis.analyse.sicherheit, "niedrig")
        self.assertTrue(any("eigene Praxis" in h for h in ergebnis.analyse.hinweise))
        # Ersatz kommt aus der Kopfzeile des sendenden Geräts.
        self.assertIn("Labormedizin", ergebnis.zieldatei)

    def test_eigener_name_im_patientenfeld_wird_verworfen(self):
        self.aufbauen(
            Analyse(
                kategorie="Befund",
                absender_kurz="Stadt-Apotheke",
                patient_nachname="",
                patient_vorname="Rasche Florian",  # Modelle legen ihn auch hier ab
                sicherheit="hoch",
            )
        )
        ergebnis = self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "FAX001.pdf"))

        self.assertNotIn("Rasche", ergebnis.zieldatei)
        self.assertIn("Stadt-Apotheke", ergebnis.zieldatei)


class ZweiterDurchgang(Grundgeruest):
    """Bei dürftiger Erkennung wird gründlich nachgefragt.

    Der schnelle Durchgang braucht wenige Sekunden, der gründliche etwa das
    Dreifache. Deshalb wird nur nachgefragt, wenn es sich lohnt.
    """

    def test_gute_erkennung_kostet_keinen_zweiten_durchgang(self):
        self.aufbauen()
        self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "a.pdf"))
        self.assertEqual(self.verarbeiter.ollama.denkaufrufe, 0)

    def test_kategorie_sonstiges_loest_nachfrage_aus(self):
        self.aufbauen(
            Analyse(kategorie="Sonstiges", absender_kurz="MediBedarf", sicherheit="niedrig")
        )
        self.verarbeiter.ollama.gruendliche_analyse = Analyse(
            kategorie="Werbung", absender_kurz="MediBedarf", sicherheit="hoch"
        )
        ergebnis = self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "a.pdf"))

        self.assertEqual(self.verarbeiter.ollama.denkaufrufe, 1)
        self.assertTrue(ergebnis.zieldatei.startswith("Werbung_"))

    def test_fehlender_absender_loest_nachfrage_aus(self):
        self.aufbauen(Analyse(kategorie="Labor", absender_kurz="", patient_nachname="Beispiel"))
        self.verarbeiter.ollama.gruendliche_analyse = Analyse(
            kategorie="Labor", absender_kurz="MVZ Labormedizin", patient_nachname="Beispiel"
        )
        ergebnis = self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "a.pdf"))

        self.assertEqual(self.verarbeiter.ollama.denkaufrufe, 1)
        self.assertIn("MVZ-Labormedizin", ergebnis.zieldatei)

    def test_eingriff_des_praxisfilters_loest_nachfrage_aus(self):
        self.aufbauen(
            Analyse(kategorie="Labor", absender_kurz="Dr. med. Florian Rasche",
                    patient_nachname="Beispiel")
        )
        self.verarbeiter.ollama.gruendliche_analyse = Analyse(
            kategorie="Labor", absender_kurz="MVZ Labormedizin", patient_nachname="Beispiel"
        )
        self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "a.pdf"))
        self.assertEqual(self.verarbeiter.ollama.denkaufrufe, 1)

    def test_schlechteres_zweitergebnis_wird_verworfen(self):
        self.aufbauen(
            Analyse(kategorie="Sonstiges", absender_kurz="MediBedarf", patient_nachname="Bauer")
        )
        self.verarbeiter.ollama.gruendliche_analyse = Analyse(
            kategorie="Sonstiges", absender_kurz="", patient_nachname=""
        )
        ergebnis = self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "a.pdf"))

        self.assertEqual(self.verarbeiter.ollama.denkaufrufe, 1)
        self.assertIn("MediBedarf", ergebnis.zieldatei, "Das bessere erste Ergebnis muss gewinnen")

    def test_abgeschalteter_denkmodus_verhindert_die_nachfrage(self):
        self.aufbauen(Analyse(kategorie="Sonstiges", absender_kurz=""))
        self.einstellungen.ollama_denkmodus = False
        self.verarbeiter.verarbeiten(fax_anlegen(self.eingang / "a.pdf"))
        self.assertEqual(self.verarbeiter.ollama.denkaufrufe, 0)


class Duplikate(Grundgeruest):
    def test_gleiches_fax_erbt_den_namen_und_wird_markiert(self):
        self.aufbauen()
        original = fax_anlegen(self.eingang / "a.pdf")
        # Bytegleiche Kopie: genau der Fall, der in Version 1 zur doppelten
        # Verarbeitung durch zwei parallele Scanner führte.
        kopie = self.eingang / "b.pdf"
        kopie.write_bytes(original.read_bytes())

        erstes = self.verarbeiter.verarbeiten(original)
        self.journal.eintragen(erstes)
        zweites = self.verarbeiter.verarbeiten(kopie)

        self.assertIs(zweites.ergebnis, Ergebnis.DUPLIKAT)
        self.assertTrue(zweites.zieldatei.startswith(Path(erstes.zieldatei).stem))
        self.assertNotEqual(zweites.zieldatei, erstes.zieldatei)
        self.assertTrue((self.einstellungen.ziel / zweites.zieldatei).exists())
        self.assertEqual(self.verarbeiter.ollama.aufrufe, 1, "Duplikat kostet keine Auswertung")


if __name__ == "__main__":
    unittest.main()
