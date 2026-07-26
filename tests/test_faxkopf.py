"""Tests für den Kopfzeilenleser.

Alle Beispiele sind Texterkennungsergebnisse echter Faxe aus dem Testbestand.
"""

import unittest

from faxfinity.faxkopf import auslesen


class EchteKopfzeilen(unittest.TestCase):
    def test_nummer_vor_name(self):
        kopf = auslesen("82/01/2002 23:27 093100112233 STADTAPOTHEKE 5\nMusterinstitut Musterstadt")
        self.assertEqual(kopf.faxnummer, "093100112233")
        self.assertEqual(kopf.absender, "Stadtapotheke")

    def test_name_vor_nummer(self):
        kopf = auslesen("26-Nov-2025 14:28 MVZ für Labormedizin Nord 8931200112233")
        self.assertEqual(kopf.faxnummer, "8931200112233")
        self.assertIn("Labormedizin", kopf.absender)

    def test_grossschreibung_wird_lesbar_gemacht(self):
        self.assertEqual(auslesen("093100112233 STADTAPOTHEKE").absender, "Stadtapotheke")


class StoerendesWirdEntfernt(unittest.TestCase):
    def test_seitenzaehler(self):
        for zeile in ["0123456789 Musterheim S. 01/01", "0123456789 Musterheim P,001/001"]:
            with self.subTest(zeile=zeile):
                self.assertEqual(auslesen(zeile).absender, "Musterheim")

    def test_datum_und_uhrzeit(self):
        kopf = auslesen("26.11.2025 17:07 0931001122 Seniorenheim")
        self.assertEqual(kopf.absender, "Seniorenheim")
        self.assertEqual(kopf.faxnummer, "0931001122")

    def test_fax_kennzeichnung(self):
        self.assertEqual(auslesen("(F4%X)0049 9310011223 Seniorenheim").absender, "Seniorenheim")


class KeinFehlalarm(unittest.TestCase):
    def test_seite_ohne_kopfzeile(self):
        kopf = auslesen("Sehr geehrte Damen und Herren,\nanbei der Befund.")
        self.assertEqual(kopf.faxnummer, "")

    def test_leerer_text(self):
        self.assertFalse(bool(auslesen("")))

    def test_nur_ziffern_ohne_namen_ergibt_keinen_absender(self):
        self.assertEqual(auslesen("0123456789").absender, "")

    def test_zu_kurze_ziffernfolge_ist_keine_faxnummer(self):
        # Zimmernummern und Belegnummern sollen nicht als Rufnummer durchgehen.
        self.assertEqual(auslesen("Zimmer 106 Musterheim").faxnummer, "")

    def test_nur_die_obersten_zeilen_werden_betrachtet(self):
        text = "\n".join(["Befund", "Ergebnis", "Anhang", "0123456789 Spätzeile GmbH"])
        self.assertNotIn("Spätzeile", auslesen(text).absender)


if __name__ == "__main__":
    unittest.main()
