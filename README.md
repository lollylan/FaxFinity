# 📠 FaxFinity

**Intelligente Fax-Archivierung für Arztpraxen** — powered by Vision-LLM (Ollama)

---

## 🎯 Was macht FaxFinity?

FaxFinity überwacht einen Eingangsordner auf neue Fax-PDFs und verarbeitet diese vollautomatisch:

1. **📂 Backup** → Sofortige Sicherung ins Archiv mit Zeitstempel
2. **🤖 KI-Analyse** → Vision-LLM erkennt Kategorie, Absender und Patient
3. **✏️ Umbenennung** → Intelligente Namensgebung nach Schema
4. **📁 Sortierung** → Ablage im Zielordner

### Benennungsschema

| Kategorie | Dateiname |
|---|---|
| Arztbrief | `Arztbrief_Pneumologe_Dr._Müller_Wagner_20240115.pdf` |
| Rezeptanforderung | `Rezeptanforderung_Blindeninstitut_Neubauer_20240115.pdf` |
| Kommunikation | `Kommunikation_Seniorenresidenz_Abendsonne_20240115.pdf` |
| Werbung | `Werbung_20240115.pdf` |

---

## � Schnellstart (Portable)

### Für Endanwender (ohne Programmierkenntnisse)

1. **Lade das Paket herunter** (`FaxFinity_Portable.zip` aus Releases)
2. **Entpacke** den Ordner an einen beliebigen Ort
3. **Einmalig:** `ERSTINSTALLATION.bat` als Administrator ausführen
4. **Starten:** `FaxFinity.exe` doppelklicken → Browser öffnet sich automatisch

> **Voraussetzungen:**
> - [Python 3.10+](https://python.org) (bei Installation ✅ "Add Python to PATH" aktivieren!)
> - [Ollama](https://ollama.ai) mit einem Vision-Modell

---

## 🛠️ Installation (Entwickler)

### Voraussetzungen

- **Python 3.10+**
- **Ollama** mit einem Vision-Modell (z.B. `llama3.2-vision`)

### 1. Ollama vorbereiten

```bash
# Ollama installieren: https://ollama.ai
# Vision-Modell herunterladen:
ollama pull llama3.2-vision
```

### 2. FaxFinity installieren

```bash
git clone https://github.com/lollylan/FaxFinity.git
cd FaxFinity
pip install -r requirements.txt
```

### 3. Starten

```bash
# Per Launcher (öffnet Browser automatisch):
python launcher.py

# Oder direkt per Streamlit:
streamlit run faxsort_ai.py
```

Die Anwendung öffnet sich im Browser unter `http://localhost:8501`.

### 4. Portable EXE bauen (optional)

```bash
python build_portable.py
```

Erstellt den Ordner `FaxFinity_Portable/` mit EXE und allen Dateien.

---

## ⚙️ Konfiguration

Alle Einstellungen sind über die **Sidebar** im Webinterface erreichbar:

| Einstellung | Beschreibung | Default |
|---|---|---|
| 📂 Eingangsordner | Ordner mit eingehenden Fax-PDFs | - |
| 🤖 Ollama URL | Server-Adresse | `http://localhost:11434` |
| 🧠 Vision-Modell | Ollama-Modell für Bildanalyse | `llama3.2-vision` |
| 👤 Eigener Name | Empfänger (wird im Dateinamen ignoriert) | - |
| ⏱️ Scan-Intervall | Auto-Scan Prüfintervall in Sekunden | `120` |

---

## 📁 Ordnerstruktur

```
Eingangsordner/
├── Fax001.pdf              ← Eingehende Faxe
├── Archiv/                 ← Unveränderte Backups mit Zeitstempel
│   └── 20240115_143022_Fax001.pdf
├── Umbenannt/              ← Fertig verarbeitete & umbenannte PDFs
│   └── Arztbrief_Pneumologe_Dr._Müller_Wagner_20240115.pdf
└── Fehler/                 ← Nicht verarbeitbare Dateien
    └── ANALYSE_20240115_144000_Fax003.pdf
```

---

## 🔒 Sicherheit & Datenschutz

- **Backup-First**: Jede Datei wird *vor* der Verarbeitung archiviert
- **100% Lokal**: Alle Analysen laufen auf dem eigenen PC (Ollama) — keine Cloud!
- **Keine Datenverluste**: Eindeutige Zeitstempel verhindern Kollisionen
- **Fehlertoleranz**: Fehlerhafte Dateien landen in `/Fehler`, nicht im Nirwana
- **Empfänger-Filter**: Der eigene Name wird automatisch aus Dateinamen gefiltert

---

## 🤖 Unterstützte Kategorien

Das LLM erkennt u.a. folgende Kategorien — und kann bei Bedarf eigene erfinden:

`Arztbrief` · `Labor` · `Medikationsplan` · `Sturzprotokoll` · `Rezeptanforderung` · `Bestellung` · `Werbung` · `Kommunikation` · `Überweisung` · `Befund`

---

## 📝 Lizenz

MIT License
