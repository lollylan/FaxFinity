"""Tests für Protokoll und Duplikaterkennung.

Das Journal ist die Zusicherung, dass kein Fax unbemerkt verschwindet: nur
anhängen, nie kürzen, und für jede Datei die Prüfsumme.
"""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from faxfinity.journal import Journal, neue_verarbeitung, sha256
from faxfinity.models import Ergebnis, Verarbeitung


def eintrag(name: str, streuwert: str, ergebnis: Ergebnis, ziel: str = "") -> Verarbeitung:
    v = Verarbeitung(quelldatei=name, sha256=streuwert, eingang_am=datetime(2026, 7, 25, 9, 0, 0))
    v.ergebnis = ergebnis
    v.zieldatei = ziel or f"Befund_{name}"
    return v


class Pruefsumme(unittest.TestCase):
    def test_gleicher_inhalt_gleiche_summe(self):
        with TemporaryDirectory() as ordner:
            a, b = Path(ordner) / "a.pdf", Path(ordner) / "b.pdf"
            a.write_bytes(b"identischer Faxinhalt")
            b.write_bytes(b"identischer Faxinhalt")
            self.assertEqual(sha256(a), sha256(b))

    def test_andere_inhalte_andere_summe(self):
        with TemporaryDirectory() as ordner:
            a, b = Path(ordner) / "a.pdf", Path(ordner) / "b.pdf"
            a.write_bytes(b"Fax eins")
            b.write_bytes(b"Fax zwei")
            self.assertNotEqual(sha256(a), sha256(b))


class Duplikate(unittest.TestCase):
    def test_abgelegtes_fax_gilt_als_verarbeitet(self):
        with TemporaryDirectory() as ordner:
            protokoll = Journal(Path(ordner) / "journal.jsonl")
            protokoll.eintragen(eintrag("fax1.pdf", "abc123", Ergebnis.ERFOLG))
            self.assertTrue(protokoll.schon_verarbeitet("abc123"))
            self.assertFalse(protokoll.schon_verarbeitet("xyz789"))

    def test_fehlversuch_darf_erneut_verarbeitet_werden(self):
        with TemporaryDirectory() as ordner:
            protokoll = Journal(Path(ordner) / "journal.jsonl")
            protokoll.eintragen(eintrag("fax1.pdf", "abc123", Ergebnis.FEHLER))
            self.assertFalse(protokoll.schon_verarbeitet("abc123"))

    def test_duplikat_erbt_den_namen_des_originals(self):
        with TemporaryDirectory() as ordner:
            protokoll = Journal(Path(ordner) / "journal.jsonl")
            protokoll.eintragen(
                eintrag("fax1.pdf", "abc123", Ergebnis.ERFOLG, ziel="Arztbrief_Weber_2026-07-25.pdf")
            )
            self.assertEqual(
                protokoll.frueherer_zielname("abc123"), "Arztbrief_Weber_2026-07-25.pdf"
            )
            self.assertEqual(protokoll.frueherer_zielname("unbekannt"), "")

    def test_erkennung_ueberlebt_einen_neustart(self):
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "journal.jsonl"
            Journal(pfad).eintragen(eintrag("fax1.pdf", "abc123", Ergebnis.ERFOLG))
            self.assertTrue(Journal(pfad).schon_verarbeitet("abc123"))


class Bestand(unittest.TestCase):
    def test_es_wird_nur_angehaengt(self):
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "journal.jsonl"
            protokoll = Journal(pfad)
            for nummer in range(120):
                protokoll.eintragen(eintrag(f"fax{nummer}.pdf", f"h{nummer}", Ergebnis.ERFOLG))

            zeilen = pfad.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(zeilen), 120, "Das Journal darf nichts wegwerfen")
            self.assertTrue(protokoll.schon_verarbeitet("h0"), "Auch der erste Eintrag zählt noch")

    def test_neueste_zuerst(self):
        with TemporaryDirectory() as ordner:
            protokoll = Journal(Path(ordner) / "journal.jsonl")
            protokoll.eintragen(eintrag("alt.pdf", "h1", Ergebnis.ERFOLG))
            protokoll.eintragen(eintrag("neu.pdf", "h2", Ergebnis.ERFOLG))
            self.assertEqual(protokoll.eintraege()[0]["quelldatei"], "neu.pdf")

    def test_kaputte_zeile_stoppt_das_lesen_nicht(self):
        # Nach einem Stromausfall kann die letzte Zeile abgeschnitten sein.
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "journal.jsonl"
            protokoll = Journal(pfad)
            protokoll.eintragen(eintrag("gut.pdf", "h1", Ergebnis.ERFOLG))
            with open(pfad, "a", encoding="utf-8") as datei:
                datei.write('{"quelldatei": "abgeschnit\n')
            protokoll._bekannte_hashes = None

            self.assertEqual(len(protokoll.eintraege()), 1)
            self.assertTrue(protokoll.schon_verarbeitet("h1"))

    def test_kennzahlen_zaehlen_je_ergebnis(self):
        with TemporaryDirectory() as ordner:
            protokoll = Journal(Path(ordner) / "journal.jsonl")
            protokoll.eintragen(eintrag("a.pdf", "h1", Ergebnis.ERFOLG))
            protokoll.eintragen(eintrag("b.pdf", "h2", Ergebnis.ERFOLG))
            protokoll.eintragen(eintrag("c.pdf", "h3", Ergebnis.UNSICHER))
            protokoll.eintragen(eintrag("d.pdf", "h4", Ergebnis.FEHLER))

            zahlen = protokoll.kennzahlen()
            self.assertEqual(zahlen["gesamt"], 4)
            self.assertEqual(zahlen["erfolg"], 2)
            self.assertEqual(zahlen["unsicher"], 1)
            self.assertEqual(zahlen["fehler"], 1)

    def test_eintrag_ist_gueltiges_json_mit_pruefsumme(self):
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "journal.jsonl"
            Journal(pfad).eintragen(eintrag("fax.pdf", "abc123", Ergebnis.ERFOLG))
            daten = json.loads(pfad.read_text(encoding="utf-8").strip())
            self.assertEqual(daten["sha256"], "abc123")
            self.assertEqual(daten["quelldatei"], "fax.pdf")


class NeueVerarbeitung(unittest.TestCase):
    def test_uebernimmt_dateinamen_und_pruefsumme(self):
        vorgang = neue_verarbeitung(Path("/tmp/FAX2026.pdf"), "abc")
        self.assertEqual(vorgang.quelldatei, "FAX2026.pdf")
        self.assertEqual(vorgang.sha256, "abc")
        self.assertIs(vorgang.ergebnis, Ergebnis.FEHLER)  # bis das Gegenteil feststeht


if __name__ == "__main__":
    unittest.main()
