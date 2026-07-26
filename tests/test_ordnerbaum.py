"""Tests für das Durchblättern der Ordner in der Auswahl."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from faxfinity import ordnerbaum


class OhnePfad(unittest.TestCase):
    def test_zeigt_laufwerke_und_startpunkte(self):
        ergebnis = ordnerbaum.auflisten("")
        self.assertEqual(ergebnis["pfad"], "")
        self.assertIsNone(ergebnis["eltern"])
        self.assertTrue(ergebnis["laufwerke"], "Mindestens ein Laufwerk muss auftauchen")
        self.assertEqual(ergebnis["fehler"], "")

    def test_leerzeichen_gelten_als_kein_pfad(self):
        self.assertEqual(ordnerbaum.auflisten("   ")["pfad"], "")


class MitPfad(unittest.TestCase):
    def test_unterordner_werden_aufgelistet(self):
        with TemporaryDirectory() as ordner:
            wurzel = Path(ordner)
            (wurzel / "Eingang").mkdir()
            (wurzel / "Archiv").mkdir()
            (wurzel / "eine_datei.pdf").write_bytes(b"%PDF-")

            ergebnis = ordnerbaum.auflisten(str(wurzel))
            namen = [u["name"] for u in ergebnis["unterordner"]]

            self.assertEqual(namen, ["Archiv", "Eingang"], "alphabetisch, Dateien ausgelassen")
            self.assertEqual(ergebnis["fehler"], "")

    def test_pfade_sind_vollstaendig(self):
        with TemporaryDirectory() as ordner:
            (Path(ordner) / "Fertig").mkdir()
            eintrag = ordnerbaum.auflisten(ordner)["unterordner"][0]
            self.assertEqual(Path(eintrag["pfad"]), Path(ordner) / "Fertig")

    def test_elternordner_wird_angeboten(self):
        with TemporaryDirectory() as ordner:
            unterordner = Path(ordner) / "Tiefer"
            unterordner.mkdir()
            self.assertEqual(
                Path(ordnerbaum.auflisten(str(unterordner))["eltern"]), Path(ordner)
            )

    def test_leerer_ordner_ergibt_leere_liste_ohne_fehler(self):
        with TemporaryDirectory() as ordner:
            ergebnis = ordnerbaum.auflisten(ordner)
            self.assertEqual(ergebnis["unterordner"], [])
            self.assertEqual(ergebnis["fehler"], "")


class Fehlerfaelle(unittest.TestCase):
    def test_unerreichbarer_pfad_meldet_statt_abzustuerzen(self):
        ergebnis = ordnerbaum.auflisten("Z:\\gibt\\es\\nicht")
        self.assertIn("nicht lesbar", ergebnis["fehler"])
        self.assertEqual(ergebnis["unterordner"], [])
        # Die Laufwerksliste bleibt, damit man weiternavigieren kann.
        self.assertTrue(ergebnis["laufwerke"])

    def test_datei_statt_ordner_wird_gemeldet(self):
        with TemporaryDirectory() as ordner:
            datei = Path(ordner) / "fax.pdf"
            datei.write_bytes(b"%PDF-")
            self.assertIn("nicht lesbar", ordnerbaum.auflisten(str(datei))["fehler"])


class Laufwerke(unittest.TestCase):
    def test_liefert_gueltige_wurzeln(self):
        gefunden = ordnerbaum.laufwerke()
        self.assertTrue(gefunden)
        for laufwerk in gefunden:
            self.assertTrue(Path(laufwerk).is_absolute())


if __name__ == "__main__":
    unittest.main()
