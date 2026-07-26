"""Tests für die Dateinamensbildung.

Die Beispiele stammen überwiegend aus echten Fehlern der Vorgängerversion, die
im mitgelieferten Verarbeitungsprotokoll dokumentiert sind.
"""

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from faxfinity.benennung import dateiname, freier_pfad, notnagelname
from faxfinity.models import Analyse

EINGANG = datetime(2026, 7, 25, 9, 34, 12)


def analyse(**werte) -> Analyse:
    grund = {"kategorie": "Befund", "absender_kurz": "Testabsender"}
    return Analyse(**{**grund, **werte})


class Grundschema(unittest.TestCase):
    def test_kategorie_absender_patient_datum(self):
        name = dateiname(
            analyse(
                kategorie="Rezeptanforderung",
                absender_kurz="Stadt-Apotheke",
                patient_nachname="Mustermann",
                patient_vorname="Erika",
            ),
            EINGANG,
        )
        self.assertEqual(
            name, "Rezeptanforderung_Stadt-Apotheke_Mustermann-Erika_2026-07-25.pdf"
        )

    def test_leerzeichen_werden_bindestriche_trenner_bleibt_unterstrich(self):
        # Damit ablesbar bleibt, wo der Absender endet und der Patient beginnt.
        name = dateiname(
            analyse(absender_kurz="MVZ für Labormedizin", patient_nachname="Beispiel"),
            EINGANG,
        )
        self.assertEqual(name, "Befund_MVZ-für-Labormedizin_Beispiel_2026-07-25.pdf")

    def test_fachrichtung_nur_beim_arztbrief(self):
        mit = dateiname(
            analyse(kategorie="Arztbrief", fachrichtung="Kardiologie", absender_kurz="Dr. Weber"),
            EINGANG,
        )
        self.assertEqual(mit, "Arztbrief_Kardiologie_Dr.Weber_2026-07-25.pdf")

        ohne = dateiname(
            analyse(kategorie="Befund", fachrichtung="Kardiologie", absender_kurz="Dr. Weber"),
            EINGANG,
        )
        self.assertNotIn("Kardiologie", ohne)

    def test_werbung_bekommt_keinen_patienten(self):
        name = dateiname(
            analyse(kategorie="Werbung", absender_kurz="4muster", patient_nachname="Müller"),
            EINGANG,
        )
        self.assertEqual(name, "Werbung_4muster_2026-07-25.pdf")

    def test_umlaute_umschreiben_auf_wunsch(self):
        name = dateiname(analyse(absender_kurz="Würzburg Süd"), EINGANG, umlaute_umschreiben=True)
        self.assertEqual(name, "Befund_Wuerzburg-Sued_2026-07-25.pdf")


class Notnagel(unittest.TestCase):
    def test_ohne_absender_und_patient_gibt_es_den_notnagelnamen(self):
        self.assertEqual(dateiname(analyse(absender_kurz=""), EINGANG), "FAX_2026-07-25_093412.pdf")

    def test_notnagelname_enthaelt_uhrzeit_bleibt_also_eindeutig(self):
        frueh = notnagelname(datetime(2026, 7, 25, 9, 0, 1))
        spaet = notnagelname(datetime(2026, 7, 25, 9, 0, 2))
        self.assertNotEqual(frueh, spaet)


class Saeuberung(unittest.TestCase):
    def test_typografische_anfuehrungszeichen_verschwinden(self):
        # Vorgängerversion erzeugte: Sturzprotokoll_Seniorenresidenz”,-312,-“Abendsonne”_...
        name = dateiname(
            analyse(kategorie="Sturzprotokoll", absender_kurz='Seniorenresidenz”, 312, “Abendsonne”'),
            EINGANG,
        )
        self.assertNotRegex(name, r"[”“\",]")

    def test_haengende_bindewoerter_werden_entfernt(self):
        # "Innere Medizin und Lungenzentrum" darf nicht als "...-und" enden.
        name = dateiname(
            analyse(kategorie="Arztbrief", fachrichtung="Innere Medizin und Pneumologie",
                    absender_kurz="Dr. Müller"),
            EINGANG,
        )
        self.assertNotIn("-und_", name)

    def test_mehrfache_punkte_werden_zusammengezogen(self):
        name = dateiname(analyse(absender_kurz="Dr.. Musterfirma"), EINGANG)
        self.assertNotIn("..", name)

    def test_verbotene_windows_zeichen_verschwinden(self):
        name = dateiname(analyse(absender_kurz='Praxis <A>: B/C\\D|E?F*G"H'), EINGANG)
        for zeichen in '<>:"/\\|?*':
            self.assertNotIn(zeichen, name)

    def test_reservierte_geraetenamen_werden_entschaerft(self):
        name = dateiname(Analyse(kategorie="CON", absender_kurz=""), EINGANG)
        self.assertFalse(name.lower().startswith("con."))

    def test_laenge_wird_eingehalten(self):
        name = dateiname(
            analyse(
                kategorie="Rezeptanforderung",
                absender_kurz="Alten- und Krankenpflege Gerontopsychiatrisches Zentrum Musterstadt",
                patient_nachname="Musterfrau-Bär",
                patient_vorname="Erika",
            ),
            EINGANG,
            max_laenge=90,
        )
        self.assertLessEqual(len(name), 90)
        # Trotz Kürzung müssen Kategorie und Patient erhalten bleiben.
        self.assertTrue(name.startswith("Rezeptanforderung_"))
        self.assertIn("Musterfrau-Bär", name)


class FreierPfad(unittest.TestCase):
    def test_bestehende_datei_wird_nie_ueberschrieben(self):
        with TemporaryDirectory() as ordner:
            ziel = Path(ordner)
            (ziel / "Befund_A_2026-07-25.pdf").write_bytes(b"erstes Fax")

            zweiter = freier_pfad(ziel, "Befund_A_2026-07-25.pdf")

            self.assertFalse(zweiter.exists())
            self.assertEqual(zweiter.name, "Befund_A_2026-07-25_2.pdf")
            self.assertEqual((ziel / "Befund_A_2026-07-25.pdf").read_bytes(), b"erstes Fax")

    def test_zaehlt_weiter_bei_mehreren_gleichnamigen(self):
        with TemporaryDirectory() as ordner:
            ziel = Path(ordner)
            (ziel / "X.pdf").touch()
            (ziel / "X_2.pdf").touch()
            self.assertEqual(freier_pfad(ziel, "X.pdf").name, "X_3.pdf")


if __name__ == "__main__":
    unittest.main()
