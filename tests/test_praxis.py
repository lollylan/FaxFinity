"""Tests für die Erkennung der eigenen Praxis.

Häufigster Fehler der Vorgängerversion: der Empfänger landete als Absender im
Dateinamen. Im alten Protokoll steht unter anderem
"ABS=Friedenstra. 41, 97072 Würzburg" und "PAT=Rasche, Florian".
"""

import unittest

from faxfinity.praxis import Praxisabgleich

ABGLEICH = Praxisabgleich(
    name="Dr. med. Florian Rasche",
    strasse="Huttenstr. 6, 97072 Würzburg",
    faxnummer="0931/76264",
)


class EigenePraxisWirdErkannt(unittest.TestCase):
    def test_voller_name(self):
        self.assertTrue(ABGLEICH.ist_eigene_praxis("Dr. med. Florian Rasche"))

    def test_umgedrehte_schreibweise(self):
        self.assertTrue(ABGLEICH.ist_eigene_praxis("Rasche, Florian"))

    def test_nachname_in_zusammengelaufener_ocr_zeile(self):
        # Zweispaltige Briefköpfe verschmelzen in der Texterkennung zu einer Zeile.
        self.assertTrue(ABGLEICH.ist_eigene_praxis("MI Seniorenheim St. Martin Rasche Dr. Musterarzt"))

    def test_ocr_verfaelschten_namen(self):
        # Echter Fall: aus "Rasche" wurde "Räsche" und der eigene Name landete
        # als Patient im Dateinamen.
        self.assertTrue(ABGLEICH.ist_eigene_praxis("Räsche"))
        self.assertTrue(ABGLEICH.ist_eigene_praxis("Rasche Florian"))

    def test_eigene_faxnummer_egal_wie_formatiert(self):
        self.assertTrue(ABGLEICH.ist_eigene_praxis("Fax 0931 76264"))
        self.assertTrue(ABGLEICH.ist_eigene_praxis("093176264"))

    def test_anschrift_ohne_namen(self):
        self.assertTrue(ABGLEICH.ist_eigene_praxis("Huttenstr. 6, 97072 Würzburg"))


class FremdeAbsenderBleibenErhalten(unittest.TestCase):
    def test_apotheke(self):
        self.assertFalse(ABGLEICH.ist_eigene_praxis("Stadt-Apotheke"))

    def test_labor(self):
        self.assertFalse(ABGLEICH.ist_eigene_praxis("MVZ für Labormedizin Nord"))

    def test_pflegeheim(self):
        self.assertFalse(ABGLEICH.ist_eigene_praxis("Seniorenresidenz Abendsonne"))

    def test_fremder_arzt(self):
        self.assertFalse(ABGLEICH.ist_eigene_praxis("Prof. Dr. med. Harald Weber"))

    def test_echter_patient(self):
        self.assertFalse(ABGLEICH.ist_eigene_praxis("Mustermann, Erika"))

    def test_gleiche_stadt_reicht_nicht(self):
        # Sonst gälte jeder Würzburger Absender als eigene Praxis.
        self.assertFalse(ABGLEICH.ist_eigene_praxis("Universitätsklinikum Würzburg"))

    def test_titel_allein_reicht_nicht(self):
        self.assertFalse(ABGLEICH.ist_eigene_praxis("Dr. med."))


class Randfaelle(unittest.TestCase):
    def test_leere_eingabe(self):
        self.assertFalse(ABGLEICH.ist_eigene_praxis(""))

    def test_ohne_konfigurierte_praxisdaten_wird_nichts_gefiltert(self):
        leer = Praxisabgleich()
        self.assertFalse(bool(leer))
        self.assertFalse(leer.ist_eigene_praxis("Dr. med. Florian Rasche"))


if __name__ == "__main__":
    unittest.main()
