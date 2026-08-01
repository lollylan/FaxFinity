"""Tests für die selbsttätige Einrichtung.

Diese Entscheidungen trifft niemand mehr von Hand: die EXE-Fassung läuft in
Praxen, in denen keine Eingabeaufforderung geöffnet wird. Ein Fehlgriff hier
bedeutet entweder fünf Gigabyte ungefragter Download oder eine Praxis, die
wartet, während gar nichts geladen wird.
"""

import unittest
from unittest import mock

from faxfinity.einrichtung import (
    Ladefortschritt,
    benoetigtes_modell,
    phase_uebersetzen,
)
from faxfinity.llm import EMPFOHLENES_MODELL, Ollama, OllamaFehler, passendes_modell


class ModellwahlBeimEinrichten(unittest.TestCase):
    def test_ohne_modelle_wird_das_empfohlene_geholt(self):
        self.assertEqual(benoetigtes_modell("", []), EMPFOHLENES_MODELL)

    def test_vorhandenes_geeignetes_modell_genuegt(self):
        # Wer sich bewusst für gemma3:4b entschieden hat, soll beim nächsten
        # Start nicht ungefragt fünf Gigabyte nachgeladen bekommen.
        self.assertEqual(benoetigtes_modell("", ["gemma3:4b"]), "")

    def test_unbrauchbares_modell_zaehlt_nicht(self):
        # gemma3:1b hält den Empfänger für den Absender -- damit ist die Praxis
        # nicht eingerichtet, auch wenn "ein Modell da ist".
        self.assertEqual(benoetigtes_modell("", ["gemma3:1b"]), EMPFOHLENES_MODELL)

    def test_ausdruecklich_gewaehltes_modell_wird_geholt(self):
        self.assertEqual(benoetigtes_modell("mixtral:8x7b", ["qwen3:8b"]), "mixtral:8x7b")

    def test_ausdruecklich_gewaehltes_vorhandenes_modell_bleibt(self):
        self.assertEqual(benoetigtes_modell("qwen3:8b", ["qwen3:8b"]), "")

    def test_name_ohne_kennung_meint_latest(self):
        # Ollama führt "ollama pull qwen3" als "qwen3:latest". Ohne diese
        # Gleichsetzung gälte das Modell als fehlend und würde bei jedem
        # Start erneut geholt.
        self.assertEqual(benoetigtes_modell("qwen3", ["qwen3:latest"]), "")

    def test_leerzeichen_im_eintrag_stoeren_nicht(self):
        self.assertEqual(benoetigtes_modell("  qwen3:8b  ", ["qwen3:8b"]), "")

    def test_quantisierung_gilt_als_dasselbe_modell(self):
        self.assertEqual(passendes_modell(["qwen3:8b-q4_K_M"]), "qwen3:8b-q4_K_M")


class FortschrittBleibtMonoton(unittest.TestCase):
    """Ollama lädt ein Modell in mehreren Schichten und meldet je Schicht.

    Zeigte man nur die aktuelle Schicht an, spränge der Balken nach der großen
    Schicht wieder auf null -- das sieht aus, als finge alles von vorn an.
    """

    def test_mehrere_schichten_werden_zusammengezaehlt(self):
        stand = Ladefortschritt()
        stand.uebernehmen({"status": "pulling a", "digest": "a", "completed": 100, "total": 100})
        stand.uebernehmen({"status": "pulling b", "digest": "b", "completed": 0, "total": 100})
        self.assertEqual(stand.geladen, 100)
        self.assertEqual(stand.gesamt, 200)
        self.assertEqual(stand.prozent, 50)

    def test_spaetere_meldung_derselben_schicht_ersetzt_die_fruehere(self):
        stand = Ladefortschritt()
        stand.uebernehmen({"status": "pulling a", "digest": "a", "completed": 10, "total": 100})
        stand.uebernehmen({"status": "pulling a", "digest": "a", "completed": 90, "total": 100})
        self.assertEqual(stand.geladen, 90)
        self.assertEqual(stand.prozent, 90)

    def test_meldung_ohne_groesse_veraendert_den_balken_nicht(self):
        stand = Ladefortschritt()
        stand.uebernehmen({"status": "pulling a", "digest": "a", "completed": 50, "total": 100})
        stand.uebernehmen({"status": "verifying sha256 digest"})
        self.assertEqual(stand.prozent, 50)
        self.assertEqual(stand.phase, "Wird auf Vollständigkeit geprüft")

    def test_ohne_angaben_kein_teilen_durch_null(self):
        self.assertEqual(Ladefortschritt().prozent, 0)


class PhasenSindDeutsch(unittest.TestCase):
    def test_bekannte_phasen_werden_uebersetzt(self):
        self.assertEqual(phase_uebersetzen("pulling manifest"), "Verzeichnis wird abgerufen")
        self.assertEqual(phase_uebersetzen("success"), "Fertig")

    def test_der_download_selbst_heisst_immer_gleich(self):
        # Ollama hängt die Prüfsumme der Schicht an: "pulling 2af3b81862c6".
        self.assertEqual(phase_uebersetzen("pulling 2af3b81862c6"), "Wird heruntergeladen")

    def test_unbekanntes_wird_unveraendert_durchgereicht(self):
        self.assertEqual(phase_uebersetzen("etwas Neues"), "etwas Neues")


class Herunterladen(unittest.TestCase):
    """Der Download läuft als Strom von Zwischenständen, nicht als eine Antwort."""

    @staticmethod
    def _antwort(zeilen):
        antwort = mock.Mock()
        antwort.ok = True
        antwort.raise_for_status.return_value = None
        antwort.iter_lines.return_value = iter(zeilen)
        return antwort

    def test_zwischenstaende_werden_weitergereicht(self):
        zeilen = [
            '{"status":"pulling manifest"}',
            '{"status":"pulling abc","digest":"abc","completed":5,"total":10}',
            "",  # Ollama schickt zwischendurch Leerzeilen
            '{"status":"success"}',
        ]
        gesehen = []
        with mock.patch("faxfinity.llm.requests.post", return_value=self._antwort(zeilen)):
            Ollama().herunterladen("qwen3:8b", gesehen.append)

        self.assertEqual([s["status"] for s in gesehen],
                         ["pulling manifest", "pulling abc", "success"])

    def test_fehler_im_strom_wird_nicht_verschluckt(self):
        # Der Strom antwortet mit HTTP 200 und meldet den Fehler erst darin.
        # Übersähe man das, hielte FaxFinity ein fehlendes Modell für geladen.
        zeilen = ['{"status":"pulling manifest"}', '{"error":"model not found"}']
        with mock.patch("faxfinity.llm.requests.post", return_value=self._antwort(zeilen)):
            with self.assertRaises(OllamaFehler) as gefangen:
                Ollama().herunterladen("gibtsnicht:1b")
        self.assertIn("model not found", str(gefangen.exception))

    def test_unvollstaendige_zeile_bricht_nicht_ab(self):
        zeilen = ['{"status":"pulling manifest"}', "{kaputt", '{"status":"success"}']
        gesehen = []
        with mock.patch("faxfinity.llm.requests.post", return_value=self._antwort(zeilen)):
            Ollama().herunterladen("qwen3:8b", gesehen.append)
        self.assertEqual(len(gesehen), 2)

    def test_beide_schreibweisen_des_modellnamens_gehen_mit(self):
        # Ältere Ollama-Fassungen erwarten "name", neuere "model".
        with mock.patch("faxfinity.llm.requests.post", return_value=self._antwort([])) as post:
            Ollama().herunterladen("qwen3:8b")
        gesendet = post.call_args.kwargs["json"]
        self.assertEqual(gesendet["model"], "qwen3:8b")
        self.assertEqual(gesendet["name"], "qwen3:8b")


if __name__ == "__main__":
    unittest.main()
