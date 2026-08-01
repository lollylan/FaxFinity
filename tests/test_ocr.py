"""Tests für das Auffinden von Tesseract und den Sprachdaten.

In der EXE-Fassung liegt Tesseract mit im Paket. Griffe FaxFinity stattdessen
auf eine zufällig vorhandene Systeminstallation zurück, hinge die Texterkennung
einer Praxis an einer Fassung, die niemand geprüft hat -- und in einer Praxis
ohne Systeminstallation fiele sie ganz aus.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from faxfinity import ocr


def _tesseract_anlegen(ordner: Path) -> Path:
    ziel = ordner / "tesseract" / "tesseract.exe"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(b"")
    return ziel


def _sprachdaten_anlegen(ordner: Path, unterordner: str = "tessdata/best") -> Path:
    ziel = ordner / unterordner
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "deu.traineddata").write_bytes(b"")
    return ziel


class TesseractFinden(unittest.TestCase):
    def test_mitgeliefertes_schlaegt_die_systeminstallation(self):
        with TemporaryDirectory() as ordner:
            eigenes = _tesseract_anlegen(Path(ordner))
            with mock.patch.object(ocr, "ressourcenordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr, "anwendungsordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr.shutil, "which", return_value=r"C:\uralt\tesseract.exe"):
                self.assertEqual(ocr.finde_tesseract(), str(eigenes))

    def test_vorgabe_aus_den_einstellungen_schlaegt_alles(self):
        with TemporaryDirectory() as ordner:
            _tesseract_anlegen(Path(ordner))
            gewuenscht = Path(ordner) / "eigenes.exe"
            gewuenscht.write_bytes(b"")
            with mock.patch.object(ocr, "ressourcenordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr, "anwendungsordner", return_value=Path(ordner)):
                self.assertEqual(ocr.finde_tesseract(str(gewuenscht)), str(gewuenscht))

    def test_ohne_mitgeliefertes_greift_der_suchpfad(self):
        with TemporaryDirectory() as ordner:
            with mock.patch.object(ocr, "ressourcenordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr, "anwendungsordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr.shutil, "which", return_value=r"C:\woanders\tesseract.exe"):
                self.assertEqual(ocr.finde_tesseract(), r"C:\woanders\tesseract.exe")

    def test_neben_der_exe_wird_auch_gesucht(self):
        # Ein kaputtes mitgeliefertes Tesseract lässt sich so austauschen,
        # ohne die EXE neu zu bauen.
        with TemporaryDirectory() as programm, TemporaryDirectory() as daneben:
            eigenes = _tesseract_anlegen(Path(daneben))
            with mock.patch.object(ocr, "ressourcenordner", return_value=Path(programm)), \
                 mock.patch.object(ocr, "anwendungsordner", return_value=Path(daneben)), \
                 mock.patch.object(ocr.shutil, "which", return_value=None), \
                 mock.patch.object(ocr, "SUCHPFADE", []):
                self.assertEqual(ocr.finde_tesseract(), str(eigenes))

    def test_nirgends_vorhanden_ergibt_nichts(self):
        with TemporaryDirectory() as ordner:
            with mock.patch.object(ocr, "ressourcenordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr, "anwendungsordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr.shutil, "which", return_value=None), \
                 mock.patch.object(ocr, "SUCHPFADE", []):
                self.assertIsNone(ocr.finde_tesseract())


class SprachdatenFinden(unittest.TestCase):
    def test_im_programmordner_mitgeliefert(self):
        with TemporaryDirectory() as ordner:
            erwartet = _sprachdaten_anlegen(Path(ordner))
            with mock.patch.object(ocr, "ressourcenordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr, "anwendungsordner", return_value=Path(ordner) / "leer"):
                self.assertEqual(ocr.finde_sprachdaten(), str(erwartet))

    def test_nachgelegtes_neben_der_exe_hat_vorrang(self):
        # So lässt sich eine weitere Sprache ergänzen, ohne neu zu bauen.
        with TemporaryDirectory() as programm, TemporaryDirectory() as daneben:
            _sprachdaten_anlegen(Path(programm))
            eigenes = _sprachdaten_anlegen(Path(daneben))
            with mock.patch.object(ocr, "ressourcenordner", return_value=Path(programm)), \
                 mock.patch.object(ocr, "anwendungsordner", return_value=Path(daneben)):
                self.assertEqual(ocr.finde_sprachdaten(), str(eigenes))

    def test_ohne_deutsche_daten_kein_ordner(self):
        with TemporaryDirectory() as ordner:
            (Path(ordner) / "tessdata").mkdir()
            with mock.patch.object(ocr, "ressourcenordner", return_value=Path(ordner)), \
                 mock.patch.object(ocr, "anwendungsordner", return_value=Path(ordner)):
                self.assertIsNone(ocr.finde_sprachdaten())


if __name__ == "__main__":
    unittest.main()
