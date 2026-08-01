"""Tests für den Autostart.

Die EXE-Fassung bietet den Autostart als Schalter in der Oberfläche an. Zeigte
die Verknüpfung auf das Falsche, merkte das niemand -- bis nach dem nächsten
Hochfahren die Faxe liegenblieben.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from faxfinity import autostart

NUR_WINDOWS = unittest.skipUnless(sys.platform == "win32", "Verknüpfungen gibt es nur unter Windows")


class Startbefehl(unittest.TestCase):
    def test_ohne_exe_wird_der_interpreter_ohne_fenster_genommen(self):
        ziel, argumente, ordner = autostart.startbefehl()
        self.assertIn("-m faxfinity", argumente)
        self.assertIn("--ohne-browser", argumente)
        # pythonw.exe zeigt kein schwarzes Fenster; python.exe wäre nur die
        # Notlösung, falls es die Variante nicht gibt.
        self.assertTrue(ziel.endswith(("pythonw.exe", "python.exe")), ziel)
        self.assertTrue(Path(ordner).is_dir())

    def test_als_exe_zeigt_die_verknuepfung_auf_die_exe_selbst(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", r"D:\Praxis\FaxFinity\FaxFinity.exe"):
            ziel, argumente, ordner = autostart.startbefehl()
        self.assertEqual(ziel, r"D:\Praxis\FaxFinity\FaxFinity.exe")
        self.assertEqual(argumente, "--ohne-browser")
        # Der Arbeitsordner muss der Ordner der EXE sein: dort liegen
        # Einstellungen und Protokoll.
        self.assertEqual(ordner, r"D:\Praxis\FaxFinity")


@NUR_WINDOWS
class VerknuepfungAnlegen(unittest.TestCase):
    """Legt eine echte Verknüpfung an -- aber in einem Wegwerfordner.

    Der Autostart-Ordner des angemeldeten Benutzers bleibt unangetastet.
    """

    @staticmethod
    def _ziel_auslesen(verknuepfung: Path) -> str:
        # Auch hier muss der Apostroph verdoppelt werden -- der Prüfstand hat
        # dieselbe Falle wie die geprüfte Stelle.
        geschuetzt = str(verknuepfung).replace("'", "''")
        skript = (
            "$w = New-Object -ComObject WScript.Shell; "
            f"$w.CreateShortcut('{geschuetzt}').TargetPath"
        )
        ergebnis = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", skript],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return (ergebnis.stdout or "").strip()

    def test_anlegen_pruefen_entfernen(self):
        with TemporaryDirectory() as ordner:
            # Ein Apostroph im Pfad hat die frühere Fassung zerlegt: in
            # PowerShell beendet er die Zeichenkette mitten im Befehl.
            ziel = Path(ordner) / "Praxis O'Brien" / "FaxFinity.lnk"
            with mock.patch.object(autostart, "VERKNUEPFUNG", ziel):
                self.assertFalse(autostart.eingerichtet())
                self.assertTrue(autostart.einrichten())
                self.assertTrue(autostart.eingerichtet())
                self.assertEqual(self._ziel_auslesen(ziel), autostart.startbefehl()[0])

                self.assertTrue(autostart.entfernen())
                self.assertFalse(autostart.eingerichtet())

    def test_entfernen_ohne_vorhandene_verknuepfung_ist_kein_fehler(self):
        with TemporaryDirectory() as ordner:
            with mock.patch.object(autostart, "VERKNUEPFUNG", Path(ordner) / "nix.lnk"):
                self.assertTrue(autostart.entfernen())


if __name__ == "__main__":
    unittest.main()
