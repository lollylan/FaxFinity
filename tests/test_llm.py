"""Tests für die Aufbereitung der Modellantwort.

Die Vorgängerversion übernahm Antworten wie "nicht erkannt" wörtlich in den
Dateinamen -- im alten Protokoll steht
"Kommunikation_MediBedarf_Praxisversorgung_nicht_erkannt_...pdf".
"""

import unittest

from faxfinity.config import STANDARD_KATEGORIEN
from faxfinity.llm import Ollama, _schema


def auswerten(**felder) -> object:
    grund = {
        "kategorie": "Befund", "empfaenger": "", "absender_organisation": "",
        "absender_person": "", "absender_kurz": "", "fachrichtung": "",
        "patient_nachname": "", "patient_vorname": "", "sicherheit": "hoch",
    }
    return Ollama._zu_analyse({**grund, **felder}, STANDARD_KATEGORIEN)


class LeerantwortenWerdenVerworfen(unittest.TestCase):
    def test_platzhalter_landen_nicht_im_namen(self):
        for platzhalter in ["nicht erkannt", "Unbekannt", "keine Angabe", "N/A", "-", "unleserlich"]:
            with self.subTest(platzhalter=platzhalter):
                ergebnis = auswerten(absender_kurz=platzhalter, patient_nachname=platzhalter)
                self.assertEqual(ergebnis.absender_kurz, "")
                self.assertEqual(ergebnis.patient_nachname, "")

    def test_grussformel_ist_kein_patient(self):
        # Echter Fall: "PAT=Mit freundlichen Grüßen"
        self.assertEqual(auswerten(patient_nachname="Mit freundlichen Grüßen").patient_nachname, "")

    def test_feldbeschriftung_ist_kein_patient(self):
        # Echter Fall: "Vorname Mustermann Erika Geburtsdatum"
        self.assertEqual(auswerten(patient_vorname="Vorname").patient_vorname, "")


class AbsenderWirdBereinigt(unittest.TestCase):
    def test_seitenzaehler_aus_der_faxkopfzeile_faellt_weg(self):
        # Echter Fall: das Modell übernahm "Stadt-Apotheke S. 01/01".
        self.assertEqual(auswerten(absender_kurz="Stadt-Apotheke S. 01/01").absender_kurz,
                         "Stadt-Apotheke")

    def test_uhrzeit_faellt_weg(self):
        self.assertEqual(auswerten(absender_kurz="Seniorenheim 17:33").absender_kurz, "Seniorenheim")

    def test_verstuemmelter_seitenzaehler_faellt_weg(self):
        # Echter Fall: aus "STADTAPOTHEKE S. 01/01" las die Texterkennung
        # "STADTAPOTHEKE 5", woraus der Name "Stadtapotheke-5" wurde.
        self.assertEqual(auswerten(absender_kurz="Stadtapotheke 5").absender_kurz,
                         "Stadtapotheke")

    def test_ziffern_im_namen_bleiben_erhalten(self):
        self.assertEqual(auswerten(absender_kurz="4muster GmbH").absender_kurz, "4muster GmbH")
        self.assertEqual(auswerten(absender_kurz="Praxis 24h Notdienst").absender_kurz,
                         "Praxis 24h Notdienst")

    def test_kurzform_faellt_auf_organisation_zurueck(self):
        self.assertEqual(auswerten(absender_organisation="Markt-Apotheke").absender_kurz,
                         "Markt-Apotheke")


class FachrichtungWirdGekuerzt(unittest.TestCase):
    def test_vorspann_faellt_weg(self):
        self.assertEqual(auswerten(fachrichtung="Facharzt für Innere Medizin").fachrichtung,
                         "Innere Medizin")

    def test_ohne_vorspann_unveraendert(self):
        self.assertEqual(auswerten(fachrichtung="Kardiologie").fachrichtung, "Kardiologie")

    def test_zu_kurzer_rest_wird_nicht_gekuerzt(self):
        self.assertEqual(auswerten(fachrichtung="Praxis").fachrichtung, "Praxis")


class KategorieBleibtInDerListe(unittest.TestCase):
    def test_erfundene_kategorie_wird_zu_sonstiges(self):
        # Echter Fall: "Befreiung von Zuzahlungen für das Jahr 2025" als Kategorie.
        self.assertEqual(auswerten(kategorie="Befreiung von Zuzahlungen").kategorie, "Sonstiges")

    def test_gueltige_kategorie_bleibt(self):
        self.assertEqual(auswerten(kategorie="Arztbrief").kategorie, "Arztbrief")

    def test_ungueltige_sicherheit_wird_zur_vorsichtigen_annahme(self):
        self.assertEqual(auswerten(sicherheit="sehr sicher").sicherheit, "niedrig")


class SchemaErzwingtGueltigeAntwort(unittest.TestCase):
    def test_kategorie_ist_eine_aufzaehlung(self):
        schema = _schema(STANDARD_KATEGORIEN)
        self.assertEqual(schema["properties"]["kategorie"]["enum"], STANDARD_KATEGORIEN)

    def test_alle_felder_sind_pflicht(self):
        schema = _schema(STANDARD_KATEGORIEN)
        self.assertEqual(set(schema["required"]), set(schema["properties"]))


class Modellwahl(unittest.TestCase):
    def test_bevorzugtes_modell_gewinnt(self):
        kunde = Ollama()
        kunde.modelle = lambda: ["llama3.1:8b", "qwen3:8b", "zzz:1b"]  # type: ignore[method-assign]
        self.assertEqual(kunde.modell_waehlen(), "qwen3:8b")

    def test_eingestelltes_modell_hat_vorrang(self):
        kunde = Ollama(modell="llama3.1:8b")
        kunde.modelle = lambda: ["llama3.1:8b", "qwen3:8b"]  # type: ignore[method-assign]
        self.assertEqual(kunde.modell_waehlen(), "llama3.1:8b")

    def test_fehlendes_modell_faellt_auf_verfuegbares_zurueck(self):
        kunde = Ollama(modell="gibtsnicht:70b")
        kunde.modelle = lambda: ["qwen3:8b"]  # type: ignore[method-assign]
        self.assertEqual(kunde.modell_waehlen(), "qwen3:8b")


if __name__ == "__main__":
    unittest.main()
