# FaxFinity

Benennt und sortiert eingehende Faxe einer Arztpraxis. Läuft vollständig auf dem
eigenen Rechner — kein Patientendatum verlässt die Praxis.

Aus `FAX2026_07_25_093424.pdf` wird
`Rezeptanforderung_Stadtapotheke_Mustermann-Erika_2026-07-25.pdf`.

> ### **[▸ FaxFinity herunterladen](https://github.com/lollylan/FaxFinity/releases/latest)**
>
> Windows, kein Python nötig. Entpacken, `FaxFinity.exe` doppelklicken.
> Zusätzlich zu installieren ist nur [Ollama](https://ollama.com/download) —
> das Sprachmodell holt FaxFinity von selbst.

---

## Was passiert mit einem Fax

1. **Sichern** — unveränderte Kopie nach `Archiv/`, bevor irgendetwas anderes geschieht
2. **Lesen** — vorhandene Textebene nutzen, sonst Texterkennung (dreht kopfüber
   eingelegte Faxe automatisch richtig)
3. **Auswerten** — ein Sprachmodell bestimmt Kategorie, Absender und Patient
4. **Ablegen** — umbenannt nach `Umbenannt/`

Was nicht erkannt werden konnte, landet als `FAX_2026-07-25_093424.pdf` im
selben Zielordner. **Gelöscht wird nie etwas.**

### Benennungsschema

```
Kategorie_Absender_Patient_Eingangsdatum.pdf
```

| Beispiel |
|---|
| `Arztbrief_Kardiologie_Prof.Dr.med.Harald-Weber_Schmidt-Renate_2026-07-25.pdf` |
| `Rezeptanforderung_Stadtapotheke_Mustermann-Erika_2026-07-25.pdf` |
| `Labor_MVZ-für-Labormedizin-Nord_Beispiel_2026-07-25.pdf` |
| `Werbung_Bueromarkt-Musterversand_2026-07-25.pdf` |
| `FAX_2026-07-25_093424.pdf` ← nicht erkannt |

Innerhalb eines Bestandteils steht der Bindestrich, zwischen den Bestandteilen
der Unterstrich — so bleibt ablesbar, wo der Absender aufhört und der Patient
anfängt. Bei Werbung und Bestellungen entfällt der Patient.

Das Datum ist das **Eingangsdatum**, nicht das Dokumentdatum: die Uhren
sendender Faxgeräte gehen häufig falsch (in einem echten Testfax stand
`02/01/2002`).

### Kategorien

Das Modell darf ausschließlich aus einer festen Liste wählen — sonst erfindet es
Kategorien wie `Befreiung_von_Zuzahlungen_für_das_Jahr_2025`. Ab Werk:

`Arztbrief` · `Befund` · `Labor` · `Rezeptanforderung` · `Medikationsplan` ·
`Überweisung` · `Bestellung` · `Sturzprotokoll` · `Krankenkasse` ·
`Kommunikation` · `Rechnung` · `Werbung` · `Sonstiges`

Die Liste lässt sich in den Einstellungen anpassen; `Sonstiges` kommt immer
dazu. Eine Praxis bekommt auch Post, die mit Patienten nichts zu tun hat —
Handwerkerrechnungen, Lieferantenpost, Behördenschreiben. Für die sind
`Rechnung` und `Sonstiges` da.

---

## Einrichten

FaxFinity gibt es in zwei Fassungen. Für eine Praxis ist die erste gedacht.

### Fertige Fassung — nur eine Datei starten

[Neueste Fassung herunterladen](https://github.com/lollylan/FaxFinity/releases/latest)
(rund 110 MB), entpacken, den Ordner auf die Festplatte kopieren — nicht aus dem
ZIP heraus starten — und **`FaxFinity.exe`** doppelklicken. Der Browser öffnet
sich von selbst.

Python, Tesseract und die deutschen Sprachdaten stecken mit im Paket. Zu
installieren bleibt genau eines:

| | |
|---|---|
| **Ollama** | [ollama.com/download](https://ollama.com/download) — herunterladen, installieren, fertig |

**Das Sprachmodell holt FaxFinity selbst.** Fehlt es, steht das oben auf der
Seite, mit Fortschrittsbalken — rund 5 GB, einmalig eine Viertelstunde. Ist
Ollama installiert, läuft aber nicht, startet FaxFinity es. Ist es gar nicht
installiert, steht dort ein Knopf zur Bezugsquelle; danach geht es ohne weiteres
Zutun weiter.

Faxe, die während des Herunterladens eintreffen, bleiben unangetastet liegen und
werden verarbeitet, sobald das Modell da ist.

### Mit Python — für Entwicklung und Anpassungen

| | |
|---|---|
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) — bei der Installation **„Add Python to PATH"** ankreuzen |
| **Ollama** | [ollama.com](https://ollama.com) — danach `ollama pull qwen3:8b` |
| **Tesseract** | wird von `Einrichten.bat` automatisch mitinstalliert |

1. **`Einrichten.bat`** doppelklicken — prüft alles und installiert Fehlendes
2. **`FaxFinity starten.bat`** doppelklicken — der Browser öffnet sich von selbst

### In beiden Fassungen

In der Oberfläche unter **Einstellungen** eintragen:

- **Eingangsordner** — wo die Faxe ankommen, z. B. `Z:\PegaMed\FAX-Import`
- **Ausgangsordner** — wohin die umbenannten Faxe sollen (siehe unten)
- **Archivordner** — wohin die Sicherungskopien sollen
- **Name der Praxis** — z. B. `Dr. med. Florian Rasche`
- **Anschrift** und **eigene Faxnummer**

Bei den drei Ordnerfeldern führt der Knopf **Durchsuchen** zu einer
Ordnerauswahl, in der sich durch Laufwerke und Unterordner klicken lässt.

Name, Anschrift und Faxnummer der Praxis sind wichtig: an ihnen erkennt
FaxFinity den Empfängerblock und verhindert, dass die eigene Praxis als
Absender im Dateinamen landet.

Einmal gespeicherte Einstellungen bleiben erhalten und werden bei jedem Start
wieder geladen.

---

## Bedienung

Die Oberfläche liegt unter **http://127.0.0.1:8757** und zeigt

- was noch einzurichten ist, solange etwas fehlt,
- ob Eingangsordner, Texterkennung und Sprachmodell bereit sind,
- was gerade verarbeitet wird und wie viel noch wartet,
- die zuletzt abgelegten Faxe mit erkanntem Absender und Patient.

Verarbeitet wird im Hintergrund. Der Browser darf jederzeit geschlossen werden —
der Dienst läuft weiter. Ein zweiter Doppelklick auf `FaxFinity.exe` startet
nichts doppelt, sondern holt die schon laufende Oberfläche wieder nach vorn.

| Wo | Was |
|---|---|
| **beim Anmelden mitstarten** | Schalter unten im Kasten *Betrieb*. Legt eine Verknüpfung im Autostart-Ordner an; FaxFinity läuft dann ohne Fenster mit. In der Python-Fassung tut `Autostart einrichten.bat` dasselbe. |
| **FaxFinity beenden** | Knopf unten rechts im Kasten *Betrieb*. Die EXE-Fassung hat kein Konsolenfenster, das sich schließen ließe. |
| **Was schiefging** | `faxfinity.log` neben der Anwendung. Enthält Dateinamen und damit Patientennamen. |

### Ordner

Trägt man bei **Ausgangsordner** und **Archivordner** nichts ein, legt
FaxFinity beides als Unterordner des Eingangs an:

```
Z:\PegaMed\FAX-Import\
├── FAX2026_07_25_093424.pdf      ← eingehende Faxe
├── Archiv\                       ← unveränderte Sicherungskopien
└── Umbenannt\                    ← fertig benannte Faxe
```

Beide Felder nehmen aber genauso einen vollständigen Pfad — auch auf ein
anderes Laufwerk oder eine Netzwerkfreigabe:

| Eingabe | Ergebnis |
|---|---|
| *(leer)* | Unterordner `Umbenannt` bzw. `Archiv` im Eingang |
| `Fertig` | Unterordner `Fertig` im Eingang |
| `D:\Praxis\Faxe fertig` | genau dieser Ordner |
| `\\server\freigabe\Faxe` | Netzwerkfreigabe |

Nicht existierende Ordner werden beim Speichern angelegt.

> **Ausgang und Archiv dürfen nicht der Eingangsordner sein.** Die abgelegte
> Datei läge sonst wieder im Eingang und würde bei jedem Durchlauf erneut
> verarbeitet. FaxFinity lehnt eine solche Einstellung ab.

Einstellungen und Protokoll liegen dagegen im Programmordner, nicht bei den
Faxen:

```
FaxFinity\
├── FaxFinity.exe                 ← nur in der fertigen Fassung
├── einstellungen.json
├── faxfinity.log                 ← was zuletzt passiert ist
└── journal.jsonl                 ← lückenloses Protokoll (siehe unten)
```

### Wenn etwas nicht stimmt

| Anzeige | Ursache |
|---|---|
| *Ollama ist nicht installiert* | Der Knopf daneben führt zur Bezugsquelle. Danach geht es von selbst weiter. |
| *Ollama nicht erreichbar* | Ollama ist nicht gestartet. Faxe bleiben liegen und werden später erneut versucht — es geht nichts verloren. |
| *Sprachmodell … fehlt* | Wird beim Start von selbst geladen. Der Knopf **Jetzt laden** stößt es erneut an. |
| *Sprache „deu" fehlt* | Der Ordner `tessdata/best` fehlt oder ist unvollständig. |
| *Eingangsordner nicht erreichbar* | Netzlaufwerk nicht verbunden. |
| *Ausgangsordner darf nicht der Eingangsordner sein* | Ausgang und Eingang zeigen auf denselben Ordner. |
| Viele `FAX_…`-Dateien | Faxqualität zu schlecht für die Texterkennung, oder das Sprachmodell antwortet nicht. |
| Doppelklick tut nichts | FaxFinity läuft schon; der zweite Start öffnet nur die Oberfläche. Was sonst dagegenspricht, steht in `faxfinity.log`. |

---

## Warum nichts verlorengehen kann

- Die Sicherungskopie wird **vor** jeder Auswertung angelegt und danach auf
  Vollständigkeit geprüft.
- Verschoben wird nur, nachdem die Zieldatei nachweislich existiert und die
  richtige Größe hat.
- Eine bestehende Datei wird **nie** überschrieben — gleichnamige bekommen `_2`, `_3`.
- Jede Verarbeitung landet mit SHA-256-Prüfsumme im `journal.jsonl`. Diese Datei
  wird nur angehängt, nie gekürzt. Für jedes Fax lässt sich damit nachweisen,
  wohin es gegangen ist.
- Ist Ollama vorübergehend nicht erreichbar, bleibt das Fax im Eingang liegen
  und wird erneut versucht — bis zu fünfmal, danach wird es mit `FAX_…` abgelegt.
- Während das Sprachmodell heruntergeladen wird, ruht die Verarbeitung ganz.
  Sonst verbrauchte jedes eintreffende Fax seine fünf Versuche und landete
  ausgerechnet in den ersten Minuten nach der Installation unter `FAX_…`.
- Ein inhaltsgleiches Fax wird erkannt und bekommt denselben Namen mit `_2`,
  statt ein zweites Mal ausgewertet zu werden.

---

## Für Entwickler

```bash
pip install -r requirements.txt
python -m unittest discover        # 164 Tests
python -m faxfinity                # Dienst und Oberfläche
```

### Die weitergebbare Fassung bauen

```bash
python werkzeuge/exe_bauen.py
```

Ergebnis ist `dist/FaxFinity-<Fassung>-Windows.zip` — rund 280 MB, darin Python,
alle Pakete, die Weboberfläche, die deutschen Sprachdaten und Tesseract.

Tesseract wird aus der Installation des bauenden Rechners übernommen (Apache-2.0,
Weitergabe erlaubt). Mitgenommen wird nur, was `tesseract.exe` wirklich braucht:
die Importtabellen werden ausgelesen und ergeben 26 der 51 Bibliotheken im
Programmordner — der Rest gehört zu den Trainingswerkzeugen. Es landet **neben**
der EXE, nicht darin: gibt man es PyInstaller als Datenordner mit, legt der die
DLLs zusätzlich in den Programmordner, und alles steckt zweimal im Paket.

| Schalter | Wirkung |
|---|---|
| *(ohne)* | Programmordner mit `FaxFinity.exe` — startet am schnellsten |
| `--einzeldatei` | Python und Pakete in die EXE selbst; startet spürbar langsamer |
| `--ohne-tesseract` | ohne Texterkennung bauen, muss dann am Ziel installiert sein |
| `--kein-archiv` | kein ZIP erzeugen |

Ollama wird bewusst nicht mitgeliefert: es bringt über ein Gigabyte
Grafikkartenbibliotheken mit und hält sich selbst aktuell — eine mitgelieferte
Kopie wäre nach wenigen Monaten veraltet.

### Mitgelieferte Fremdsoftware

Im Paket stecken Tesseract OCR und Leptonica (Apache 2.0), die deutschen
Sprachdaten aus `tessdata_best` (Apache 2.0), Python samt der Pakete aus
`requirements.txt` sowie die Bibliotheken, die Tesseract zum Laufen braucht —
unter anderem zlib, libpng, libjpeg, libtiff, libwebp, OpenJPEG, libarchive,
OpenSSL und die Laufzeitbibliotheken von MinGW-w64.

Die Lizenztexte liegen dem Paket bei: `LICENSE-Tesseract.txt` und `HERKUNFT.txt`
im Ordner `tesseract`, die der Python-Pakete in `_internal` in den jeweiligen
`.dist-info`-Ordnern. Das Bauwerkzeug bricht ab, wenn es die Lizenz nicht
findet — ohne sie darf das Paket nicht weitergegeben werden.

### Aufbau

| Datei | Aufgabe |
|---|---|
| `config.py` | Einstellungen, Übernahme aus Version 1 |
| `pdfquelle.py` | PDF lesen, Seiten in nativer Auflösung rendern |
| `bild.py` | Schieflage und Kontrast korrigieren |
| `ordnerbaum.py` | Ordner für die Auswahl in der Oberfläche auflisten |
| `ocr.py` | Tesseract, Ausrichtungserkennung |
| `faxkopf.py` | Kopfzeile des sendenden Faxgeräts auswerten |
| `llm.py` | Ollama mit erzwungenem JSON-Schema |
| `praxis.py` | eigene Praxis erkennen und aus Absenderfeldern fernhalten |
| `benennung.py` | Dateinamen bilden |
| `pipeline.py` | Verarbeitung einer Datei |
| `dienst.py` | Ordnerüberwachung, Einzelinstanz-Sperre |
| `server.py` | Weboberfläche und Schnittstelle |
| `journal.py` | Protokoll und Duplikaterkennung |
| `einrichtung.py` | Ollama starten, Sprachmodell nachladen |
| `autostart.py` | Verknüpfung im Autostart-Ordner |

### Trefferquote messen

```bash
python werkzeuge/auswertung.py <Ordner mit Faxen> --modell qwen3:8b
```

Arbeitet auf einer Kopie; der Testbestand bleibt unberührt.

### Modellwahl

Getestet auf 30 echten Faxen der Praxis:

| Modell | Treffer | je Fax | Bemerkung |
|---|---|---|---|
| `qwen3:8b` | 15/15 | 8,5 s | Empfehlung, passt in 8 GB VRAM |
| `gemma3:4b` | ~6/15 | 7 s | verwechselt Kategorien deutlich häufiger |
| `gemma3:1b` | — | — | hält den Empfänger für den Absender, unbrauchbar |

Die Messung stammt vom Entwicklungsrechner (RTX 4090). Auf einer RTX 3070 ist
mit etwa dem Dreifachen zu rechnen.

Jedes Fax wird zunächst zügig ausgewertet. Nur wenn das Ergebnis dürftig
aussieht — kein Absender, Kategorie `Sonstiges`, oder der Praxisfilter musste
eingreifen — wird ein zweites Mal mit Denkmodus nachgefragt. Das betrifft rund
ein Fünftel der Faxe und holt genau die Fälle heraus, an denen der schnelle
Durchgang scheitert.

---

## Zugriff von anderen Rechnern

Standardmäßig hört die Oberfläche nur auf `127.0.0.1` und ist damit ausschließlich
auf dem Rechner erreichbar, auf dem FaxFinity läuft.

Soll sie auch von anderen Rechnern im Praxisnetz erreichbar sein, lässt sich in
den Einstellungen **Zugriff aus dem Netz** einschalten. Nach einem Neustart von
FaxFinity steht die erreichbare Adresse im Startprotokoll:

```
Oberfläche: http://127.0.0.1:8757
Aus dem Netz erreichbar: http://192.168.178.131:8757
```

> **Das ist eine bewusste Entscheidung.** Es gibt keine Anmeldung: Wer die
> Adresse kennt und im selben Netz ist, sieht das Verarbeitungsprotokoll mit
> Patientennamen, kann die Einstellungen ändern und durch die Ordner des
> Rechners blättern. In einem abgeschlossenen Praxisnetz ist das vertretbar --
> in einem Netz mit Gast-WLAN oder Fremdzugängen nicht.

---

## Datenschutz

Texterkennung und Sprachmodell laufen auf dem Praxisrechner. Im laufenden
Betrieb geht die einzige ausgehende Verbindung an Ollama unter
`localhost:11434`. Die Weboberfläche lädt keine Schriftarten, Skripte oder
Bilder aus dem Internet nach und funktioniert deshalb auch auf einem Rechner
ohne Internetzugang.

Die eine Ausnahme ist das Herunterladen des Sprachmodells: dabei holt Ollama
das Modell aus dem Netz. Übertragen wird nur, welches Modell gewünscht ist —
kein Fax, kein Name, kein Praxisdatum. Danach bleibt der Rechner wieder unter
sich.

Patientennamen stehen in den Dateinamen — der Zielordner gehört entsprechend
geschützt. Dasselbe gilt für `journal.jsonl` und `faxfinity.log` im
Programmordner: auch dort stehen Dateinamen und damit Patientennamen.
