"""Tests für den Hintergrunddienst.

Schwerpunkt ist die Einzelinstanz-Sperre. In Version 1 lief die Scanschleife in
der Streamlit-Seite: zwei geöffnete Browser-Tabs ergaben zwei Scanner, die
nacheinander nach derselben Datei griffen. Im alten Protokoll stehen dazu zwei
"Verschiebe-Fehler" unmittelbar nach erfolgreichen Einträgen.
"""

import os
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from faxfinity.dienst import RUHEZEIT_SEKUNDEN, Dienst, Einzelinstanzsperre
from faxfinity.config import Einstellungen
from faxfinity.journal import Journal

WURZEL = Path(__file__).resolve().parent.parent


class Sperre(unittest.TestCase):
    def test_zweite_sperre_im_selben_prozess_scheitert(self):
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "faxfinity.lock"
            erste, zweite = Einzelinstanzsperre(pfad), Einzelinstanzsperre(pfad)

            self.assertTrue(erste.belegen())
            self.assertFalse(zweite.belegen(), "Zwei Dienste dürfen nicht gleichzeitig laufen")
            erste.freigeben()

    def test_nach_freigabe_wieder_belegbar(self):
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "faxfinity.lock"
            erste = Einzelinstanzsperre(pfad)
            self.assertTrue(erste.belegen())
            erste.freigeben()

            zweite = Einzelinstanzsperre(pfad)
            self.assertTrue(zweite.belegen())
            zweite.freigeben()

    def test_fremder_prozess_wird_ausgesperrt_und_ueberlebt(self):
        """Der Kern der Sache.

        Version dieses Codes vom 25.07.2026 prüfte mit os.kill(pid, 0), ob der
        Inhaber der Sperre noch lebt. Unter Windows ruft Python dafür
        TerminateProcess auf und beendet den geprüften Prozess. Der Test hält
        die Sperre daher in einem echten zweiten Prozess und prüft danach
        beides: dass ausgesperrt wurde und dass der Inhaber noch läuft.
        """
        with TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "faxfinity.lock"
            skript = textwrap.dedent(f"""
                import sys, time
                sys.path.insert(0, {str(WURZEL)!r})
                from pathlib import Path
                from faxfinity.dienst import Einzelinstanzsperre
                sperre = Einzelinstanzsperre(Path({str(pfad)!r}))
                assert sperre.belegen()
                print("belegt", flush=True)
                time.sleep(30)
            """)
            inhaber = subprocess.Popen(
                [sys.executable, "-c", skript], stdout=subprocess.PIPE, text=True
            )
            try:
                self.assertEqual(inhaber.stdout.readline().strip(), "belegt")

                self.assertFalse(
                    Einzelinstanzsperre(pfad).belegen(),
                    "Ein zweiter Dienst darf die Sperre nicht bekommen",
                )
                self.assertIsNone(
                    inhaber.poll(),
                    "Der Sperrinhaber muss den Versuch unbeschadet überstehen",
                )
            finally:
                inhaber.kill()
                inhaber.wait(timeout=10)
                inhaber.stdout.close()

            # Nach dem Ende des Inhabers ist die Sperre wieder frei -- ohne
            # dass jemand eine verwaiste Datei aufräumen müsste.
            nachfolger = Einzelinstanzsperre(pfad)
            self.assertTrue(nachfolger.belegen())
            nachfolger.freigeben()


class ZweiterDienstStartetNicht(unittest.TestCase):
    def test_start_scheitert_mit_meldung(self):
        with TemporaryDirectory() as ordner:
            wurzel = Path(ordner)
            eingang = wurzel / "Eingang"
            eingang.mkdir()
            einstellungen = Einstellungen(eingangsordner=str(eingang), auto_scan=False)
            protokoll = Journal(wurzel / "journal.jsonl")
            sperrdatei = wurzel / "faxfinity.lock"

            erster = Dienst(einstellungen, protokoll, sperrdatei)
            self.assertTrue(erster.starten())
            try:
                zweiter = Dienst(einstellungen, protokoll, sperrdatei)
                self.assertFalse(zweiter.starten())
                self.assertIn("bereits", zweiter.zustand.letzter_fehler)
            finally:
                erster.stoppen()


class BereiteDateien(unittest.TestCase):
    """Ein Fax, das gerade übers Netz hereinkopiert wird, darf nicht angefasst werden."""

    def dienst_mit_eingang(self, wurzel: Path) -> Dienst:
        eingang = wurzel / "Eingang"
        eingang.mkdir(exist_ok=True)
        return Dienst(
            Einstellungen(eingangsordner=str(eingang), auto_scan=False),
            Journal(wurzel / "journal.jsonl"),
            wurzel / "faxfinity.lock",
        )

    def test_frisch_geschriebene_datei_wird_uebersprungen(self):
        with TemporaryDirectory() as ordner:
            wurzel = Path(ordner)
            dienst = self.dienst_mit_eingang(wurzel)
            (wurzel / "Eingang" / "gerade_angekommen.pdf").write_bytes(b"%PDF-")
            self.assertEqual(dienst._bereite_dateien(), [])

    def test_abgelegene_datei_wird_genommen(self):
        with TemporaryDirectory() as ordner:
            wurzel = Path(ordner)
            dienst = self.dienst_mit_eingang(wurzel)
            datei = wurzel / "Eingang" / "fertig.pdf"
            datei.write_bytes(b"%PDF-")
            alt = time.time() - RUHEZEIT_SEKUNDEN - 5
            os.utime(datei, (alt, alt))
            self.assertEqual([p.name for p in dienst._bereite_dateien()], ["fertig.pdf"])

    def test_leere_datei_wird_uebersprungen(self):
        with TemporaryDirectory() as ordner:
            wurzel = Path(ordner)
            dienst = self.dienst_mit_eingang(wurzel)
            datei = wurzel / "Eingang" / "leer.pdf"
            datei.touch()
            alt = time.time() - RUHEZEIT_SEKUNDEN - 5
            os.utime(datei, (alt, alt))
            self.assertEqual(dienst._bereite_dateien(), [])

    def test_unterordner_werden_nicht_durchsucht(self):
        # Sonst würde das Archiv beim nächsten Durchlauf erneut verarbeitet.
        with TemporaryDirectory() as ordner:
            wurzel = Path(ordner)
            dienst = self.dienst_mit_eingang(wurzel)
            archiv = wurzel / "Eingang" / "Archiv"
            archiv.mkdir()
            datei = archiv / "sicherung.pdf"
            datei.write_bytes(b"%PDF-")
            alt = time.time() - RUHEZEIT_SEKUNDEN - 5
            os.utime(datei, (alt, alt))
            self.assertEqual(dienst._bereite_dateien(), [])


if __name__ == "__main__":
    unittest.main()
