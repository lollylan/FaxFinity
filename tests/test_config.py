"""Tests für Einstellungen und die Übernahme aus FaxFinity 1.x."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from faxfinity.config import Einstellungen

# Wortgleich die config.json der Vorgängerversion.
ALTE_KONFIGURATION = {
    "eingangsordner": "Z:\\PegaMed\\FAX-Import",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "granite3.2-vision:latest",
    "eigener_name": "Dr. med. Florian Rasche, Huttenstr. 6",
    "scan_interval": 120,
    "poppler_path": "",
    "auto_scan_active": True,
    "ollama_timeout": 180,
    "ollama_num_ctx": 4096,
    "max_pages_to_scan": 2,
    "dokumenten_kategorien": "Arztbrief, Labor, Medikationsplan, Werbung",
}


class UebernahmeAusVersion1(unittest.TestCase):
    def laden(self, daten: dict) -> Einstellungen:
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "config.json"
            pfad.write_text(json.dumps(daten), encoding="utf-8")
            return Einstellungen.laden(pfad)

    def test_umbenannte_schluessel_werden_uebernommen(self):
        e = self.laden(ALTE_KONFIGURATION)
        self.assertEqual(e.ollama_modell, "granite3.2-vision:latest")
        self.assertEqual(e.praxis_name, "Dr. med. Florian Rasche, Huttenstr. 6")
        self.assertEqual(e.scan_intervall, 120)
        self.assertEqual(e.max_seiten, 2)
        self.assertTrue(e.auto_scan)

    def test_kategorien_werden_aus_der_kommaliste_gelesen(self):
        e = self.laden(ALTE_KONFIGURATION)
        self.assertEqual(e.kategorien, ["Arztbrief", "Labor", "Medikationsplan", "Werbung"])

    def test_unbekannte_schluessel_stoeren_nicht(self):
        # poppler_path gibt es nicht mehr -- pdf2image wird nicht mehr verwendet.
        e = self.laden(ALTE_KONFIGURATION)
        self.assertEqual(e.eingangsordner, "Z:\\PegaMed\\FAX-Import")

    def test_neue_einstellungen_bekommen_ihre_vorgabe(self):
        e = self.laden(ALTE_KONFIGURATION)
        self.assertEqual(e.ollama_keep_alive, "30m")
        self.assertTrue(e.ollama_denkmodus)

    def test_fruehere_unterordnernamen_werden_uebernommen(self):
        e = self.laden({**ALTE_KONFIGURATION, "unterordner_ziel": "Fertig"})
        self.assertEqual(e.zielordner, "Fertig")
        self.assertEqual(e.ziel.name, "Fertig")


class Robustheit(unittest.TestCase):
    def test_fehlende_datei_ergibt_vorgaben(self):
        with TemporaryDirectory() as ordner:
            e = Einstellungen.laden(Path(ordner) / "gibtsnicht.json")
            self.assertEqual(e.eingangsordner, "")
            self.assertEqual(e.ollama_url, "http://localhost:11434")

    def test_beschaedigte_datei_ergibt_vorgaben_statt_absturz(self):
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "config.json"
            pfad.write_text("{kein gültiges JSON", encoding="utf-8")
            self.assertEqual(Einstellungen.laden(pfad).ollama_url, "http://localhost:11434")

    def test_von_notepad_gespeicherte_datei_bleibt_lesbar(self):
        # Windows-Editoren stellen eine Bytefolge (BOM) voran. Ohne Nachsicht
        # dafür verlöre FaxFinity nach jedem Bearbeiten von Hand alle Angaben.
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "einstellungen.json"
            pfad.write_text(
                json.dumps({"eingangsordner": "Z:\\FAX-Import", "praxis_name": "Dr. Müller"}),
                encoding="utf-8-sig",
            )
            geladen = Einstellungen.laden(pfad)
            self.assertEqual(geladen.eingangsordner, "Z:\\FAX-Import")
            self.assertEqual(geladen.praxis_name, "Dr. Müller")


class SpeichernUndLesen(unittest.TestCase):
    def test_gespeichertes_kommt_unveraendert_zurueck(self):
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "einstellungen.json"
            original = Einstellungen(
                eingangsordner="C:\\Faxeingang",
                praxis_name="Dr. med. Florian Rasche",
                kategorien=["Arztbrief", "Werbung"],
                ollama_denkmodus=False,
            )
            original.speichern(pfad)
            self.assertEqual(Einstellungen.laden(pfad), original)

    def test_umlaute_bleiben_lesbar_in_der_datei(self):
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "einstellungen.json"
            Einstellungen(praxis_strasse="Huttenstr. 6, 97072 Würzburg").speichern(pfad)
            self.assertIn("Würzburg", pfad.read_text(encoding="utf-8"))


class Kategorien(unittest.TestCase):
    def test_sonstiges_ist_immer_dabei(self):
        e = Einstellungen(kategorien=["Arztbrief", "Labor"])
        self.assertIn("Sonstiges", e.gueltige_kategorien)

    def test_sonstiges_wird_nicht_verdoppelt(self):
        e = Einstellungen(kategorien=["Arztbrief", "Sonstiges"])
        self.assertEqual(e.gueltige_kategorien.count("Sonstiges"), 1)

    def test_leere_eintraege_fallen_weg(self):
        e = Einstellungen(kategorien=["Arztbrief", "  ", ""])
        self.assertEqual(e.gueltige_kategorien, ["Arztbrief", "Sonstiges"])


class AbgeleitetePfade(unittest.TestCase):
    def test_ohne_angabe_unterordner_im_eingang(self):
        e = Einstellungen(eingangsordner="C:\\Faxeingang")
        self.assertEqual(e.archiv.name, "Archiv")
        self.assertEqual(e.ziel.name, "Umbenannt")
        self.assertEqual(e.archiv.parent, e.eingang)

    def test_name_wird_zum_unterordner(self):
        e = Einstellungen(eingangsordner="C:\\Faxeingang", zielordner="Fertig")
        self.assertEqual(e.ziel, Path("C:\\Faxeingang") / "Fertig")

    def test_vollstaendiger_pfad_wird_uebernommen(self):
        e = Einstellungen(eingangsordner="C:\\Faxeingang", zielordner="D:\\Praxis\\Faxe fertig")
        self.assertEqual(e.ziel, Path("D:\\Praxis\\Faxe fertig"))
        self.assertNotEqual(e.ziel.parent, e.eingang)

    def test_netzwerkfreigabe_als_ziel(self):
        e = Einstellungen(eingangsordner="C:\\Faxeingang", zielordner=r"\\server\freigabe\Faxe")
        self.assertEqual(e.ziel, Path(r"\\server\freigabe\Faxe"))

    def test_ordner_werden_angelegt(self):
        with TemporaryDirectory() as ordner:
            e = Einstellungen(eingangsordner=ordner)
            e.ordner_anlegen()
            self.assertTrue(e.archiv.is_dir())
            self.assertTrue(e.ziel.is_dir())

    def test_ziel_ausserhalb_wird_angelegt(self):
        with TemporaryDirectory() as wurzel:
            eingang = Path(wurzel) / "Eingang"
            eingang.mkdir()
            e = Einstellungen(
                eingangsordner=str(eingang), zielordner=str(Path(wurzel) / "Fertig")
            )
            e.ordner_anlegen()
            self.assertTrue((Path(wurzel) / "Fertig").is_dir())

    def test_nicht_vorhandener_eingang_wird_erkannt(self):
        self.assertFalse(Einstellungen(eingangsordner="Z:\\gibt\\es\\nicht").eingang_ist_nutzbar())
        self.assertFalse(Einstellungen().eingang_ist_nutzbar())


class OrdnerBeanstandung(unittest.TestCase):
    """Ein Ziel gleich dem Eingang wäre eine Endlosschleife."""

    def eingang(self, wurzel: str) -> Path:
        pfad = Path(wurzel) / "Eingang"
        pfad.mkdir(exist_ok=True)
        return pfad

    def test_gueltige_einstellung_wird_nicht_beanstandet(self):
        with TemporaryDirectory() as wurzel:
            e = Einstellungen(eingangsordner=str(self.eingang(wurzel)))
            self.assertEqual(e.ordner_beanstanden(), "")

    def test_ziel_gleich_eingang_wird_abgelehnt(self):
        with TemporaryDirectory() as wurzel:
            eingang = self.eingang(wurzel)
            e = Einstellungen(eingangsordner=str(eingang), zielordner=str(eingang))
            self.assertIn("Eingangsordner sein", e.ordner_beanstanden())

    def test_ziel_gleich_eingang_auch_bei_anderer_schreibweise(self):
        # "Z:\Fax" und "Z:\Fax\." sind derselbe Ordner.
        with TemporaryDirectory() as wurzel:
            eingang = self.eingang(wurzel)
            e = Einstellungen(eingangsordner=str(eingang), zielordner=str(eingang) + "\\.")
            self.assertNotEqual(e.ordner_beanstanden(), "")

    def test_archiv_gleich_eingang_wird_abgelehnt(self):
        with TemporaryDirectory() as wurzel:
            eingang = self.eingang(wurzel)
            e = Einstellungen(eingangsordner=str(eingang), archivordner=str(eingang))
            self.assertIn("Archivordner", e.ordner_beanstanden())

    def test_ziel_gleich_archiv_wird_abgelehnt(self):
        with TemporaryDirectory() as wurzel:
            e = Einstellungen(
                eingangsordner=str(self.eingang(wurzel)),
                zielordner="Ablage",
                archivordner="Ablage",
            )
            self.assertIn("unterscheiden", e.ordner_beanstanden())

    def test_fehlender_eingang_wird_benannt(self):
        self.assertIn("kein Eingangsordner", Einstellungen().ordner_beanstanden())

    def test_unerreichbarer_eingang_wird_benannt(self):
        e = Einstellungen(eingangsordner="Z:\\gibt\\es\\nicht")
        self.assertIn("nicht erreichbar", e.ordner_beanstanden())


if __name__ == "__main__":
    unittest.main()
