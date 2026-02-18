"""
╔═══════════════════════════════════════════════════════════════╗
║                      FaxFinity v1.0                          ║
║         Intelligente Fax-Archivierung für Arztpraxen         ║
╚═══════════════════════════════════════════════════════════════╝

Automatische Analyse, Klassifizierung und Umbenennung
eingehender Fax-PDFs mittels Vision-LLM (Ollama).

Entwickelt für: Praxis Dr. med. Florian Rasche
"""

import streamlit as st
import os
import json
import time
import shutil
import base64
import re
import uuid
import threading
import logging
from pathlib import Path
from datetime import datetime, timedelta
from io import BytesIO

import requests
from PIL import Image

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

# ──────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("FaxFinity")

# ──────────────────────────────────────────────────────────────
# CONSTANTS & DEFAULTS
# ──────────────────────────────────────────────────────────────
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "eingangsordner": "",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2-vision",
    "eigener_name": "Dr. med. Florian Rasche, Huttenstr. 6",
    "scan_interval": 120,  # Sekunden
    "poppler_path": "",  # Optional: Pfad zu Poppler/bin
}
LOG_MAX_ENTRIES = 50


# ──────────────────────────────────────────────────────────────
# CONFIG PERSISTENCE
# ──────────────────────────────────────────────────────────────
def load_config() -> dict:
    """Lade Konfiguration aus JSON-Datei oder erstelle Defaults."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Merge mit Defaults für neue Keys
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    """Speichere Konfiguration als JSON."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────
# PROCESSING LOG
# ──────────────────────────────────────────────────────────────
LOG_FILE = "processing_log.json"


def load_processing_log() -> list:
    """Lade Verarbeitungs-Log."""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_processing_log(log_entries: list):
    """Speichere Verarbeitungs-Log."""
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_entries[-LOG_MAX_ENTRIES:], f, indent=2, ensure_ascii=False)


def add_log_entry(
    original_name: str,
    new_name: str,
    status: str,
    kategorie: str = "",
    absender: str = "",
    patient: str = "",
    details: str = "",
):
    """Füge einen Eintrag zum Log hinzu."""
    entries = load_processing_log()
    entries.append(
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "original": original_name,
            "neu": new_name,
            "status": status,
            "kategorie": kategorie,
            "absender": absender,
            "patient": patient,
            "details": details,
        }
    )
    save_processing_log(entries)


# ──────────────────────────────────────────────────────────────
# HELPER: ORDNER ERSTELLEN
# ──────────────────────────────────────────────────────────────
def ensure_subdirs(base: str):
    """Erstelle Unterordner Archiv, Umbenannt, Fehler."""
    for sub in ["Archiv", "Umbenannt", "Fehler"]:
        p = os.path.join(base, sub)
        os.makedirs(p, exist_ok=True)
    return {
        "archiv": os.path.join(base, "Archiv"),
        "umbenannt": os.path.join(base, "Umbenannt"),
        "fehler": os.path.join(base, "Fehler"),
    }


# ──────────────────────────────────────────────────────────────
# HELPER: SICHERE DATEINAMEN
# ──────────────────────────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    """Entferne unerlaubte Zeichen aus Dateinamen."""
    # Erlaube nur Buchstaben, Zahlen, Unterstriche, Bindestriche, Punkte
    name = re.sub(r"[^\w\-.]", "_", name, flags=re.UNICODE)
    # Entferne doppelte Unterstriche
    name = re.sub(r"_+", "_", name)
    # Entferne führende/trailing Unterstriche
    name = name.strip("_")
    return name


def unique_filepath(directory: str, filename: str) -> str:
    """Stelle sicher, dass der Dateiname eindeutig ist."""
    filepath = os.path.join(directory, filename)
    if not os.path.exists(filepath):
        return filepath
    base, ext = os.path.splitext(filename)
    counter = 1
    while True:
        new_name = f"{base}_{counter}{ext}"
        new_path = os.path.join(directory, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1


# ──────────────────────────────────────────────────────────────
# OLLAMA API
# ──────────────────────────────────────────────────────────────
def fetch_ollama_models(ollama_url: str) -> list:
    """Hole verfügbare Modelle von Ollama."""
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        return sorted(models)
    except Exception as e:
        logger.warning(f"Ollama-Modelle konnten nicht geladen werden: {e}")
        return []


def analyze_image_with_ollama(
    image: Image.Image,
    ollama_url: str,
    model: str,
    eigener_name: str,
) -> dict | None:
    """
    Sende ein Bild an Ollama Vision und erhalte strukturierte Analyse.
    Gibt ein dict zurück: {'kategorie': ..., 'absender': ..., 'patient': ...}
    oder None bei Fehler.

    Nutzt /api/chat mit System-Prompt für saubere Kontext-Isolation
    zwischen aufeinanderfolgenden PDFs.
    """
    # Bild → Base64
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    # Eindeutige Request-ID verhindert Kontext-Vermischung
    request_id = uuid.uuid4().hex[:8]

    system_prompt = (
        f"Du bist ein Fax-Analyse-Assistent für eine Arztpraxis. "
        f"Dies ist eine NEUE, UNABHÄNGIGE Analyse (ID: {request_id}). "
        f"Vergiss alles aus vorherigen Analysen komplett. "
        f"Analysiere NUR das beigefügte Bild. "
        f"Der Empfänger ist '{eigener_name}' — dieser Name darf NIEMALS "
        f"als Absender oder Patient in deiner Antwort erscheinen. "
        f"Antworte AUSSCHLIESSLICH im JSON-Format. "
        f"Verwende KEINE Beispielnamen — nur das, was du tatsächlich im Dokument liest."
    )

    user_prompt = (
        f"Analysiere dieses Fax-Dokument (ID: {request_id}).\n\n"
        f"Lies das Dokument aufmerksam und identifiziere:\n\n"
        f"1. KATEGORIE — wähle die passendste:\n"
        f"   Arztbrief, Labor, Medikationsplan, Sturzprotokoll, "
        f"   Rezeptanforderung, Bestellung, Werbung, Kommunikation, "
        f"   Überweisung, Befund\n"
        f"   Falls keine passt, erfinde eine kurze treffende Kategorie.\n\n"
        f"2. ABSENDER — wer hat das Fax gesendet?\n"
        f"   Lies den tatsächlichen Namen und ggf. Fachrichtung aus dem Dokument.\n"
        f"   Der Empfänger '{eigener_name}' ist NICHT der Absender!\n\n"
        f"3. PATIENT — Nachname des Patienten, falls im Dokument erkennbar.\n\n"
        f"Antworte NUR mit diesem JSON, sonst nichts:\n"
        f'{{\"kategorie\": \"...\", \"absender\": \"...\", \"patient\": \"...\"}}'
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
                "images": [img_base64],
            },
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 4096,  # Genug für Bild-Tokens + Analyse
        },
        "keep_alive": "5s",  # Kurzes Behalten für Performance, aber schnelles Freigeben
    }

    try:
        resp = requests.post(
            f"{ollama_url}/api/chat",
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        response_data = resp.json()
        raw_response = response_data.get("message", {}).get("content", "")
        logger.info(f"Ollama Antwort [{request_id}]: {raw_response}")
        return parse_ollama_response(raw_response, eigener_name)
    except requests.exceptions.Timeout:
        logger.error("Ollama Timeout – Modell hat zu lange gebraucht.")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("Ollama nicht erreichbar. Ist der Server gestartet?")
        return None
    except Exception as e:
        logger.error(f"Ollama Fehler: {e}")
        return None


def parse_ollama_response(raw: str, eigener_name: str = "") -> dict | None:
    """Parse die JSON-Antwort von Ollama, auch wenn sie in Text eingebettet ist."""
    # Repariere doppelte Unicode-Escapes (z.B. \u\u00f6 → \u00f6)
    cleaned = re.sub(r'\\u\\u([0-9a-fA-F]{4})', r'\\u\1', raw)
    # Auch einfache Variante: \u\u → \u
    cleaned = re.sub(r'\\u(?=\\u[0-9a-fA-F]{4})', '', cleaned)

    # Versuche direktes JSON-Parsing
    for text in [cleaned, raw]:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return normalize_analysis(data, eigener_name)
        except json.JSONDecodeError:
            pass

    # Versuche JSON aus dem Text zu extrahieren
    json_patterns = [
        r"```json\s*(\{[^{}]*\})\s*```",  # Code-Block
        r"```\s*(\{[^{}]*\})\s*```",  # Code-Block ohne Sprache
        r"\{[^{}]*\}",  # Einfaches JSON-Objekt
    ]

    for text in [cleaned, raw]:
        for pattern in json_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    if isinstance(data, dict):
                        return normalize_analysis(data, eigener_name)
                except json.JSONDecodeError:
                    continue

    # ── FALLBACK: Markdown-/Freitext-Parsing ──────────────────
    # Ollama antwortet manchmal im Format:
    # **Kategorie:** Arztbrief
    # **Absender:** Dr. Müller
    logger.info("  ℹ JSON nicht gefunden, versuche Markdown-Parsing...")
    result = _parse_markdown_response(raw)
    if result:
        return normalize_analysis(result, eigener_name)

    logger.warning(f"Konnte Antwort nicht parsen: {raw[:200]}")
    return None


def _parse_markdown_response(raw: str) -> dict | None:
    """
    Fallback-Parser für Markdown-formatierte Antworten von Ollama.
    Erkennt Muster wie:
      **Kategorie:** Arztbrief
      Kategorie: Arztbrief
      - Kategorie: Arztbrief
    """
    result = {}
    patterns = {
        "kategorie": [
            r"\*\*Kategorie[:\*]*\*\*\s*:?\s*(.+?)(?:\n|$)",
            r"(?:^|\n)\s*[-•]?\s*Kategorie\s*:\s*(.+?)(?:\n|$)",
            r"Kategorie[:\s]+([A-ZÄÖÜ][a-zäöüß-]+)",
        ],
        "absender": [
            r"\*\*Absender[:\*]*\*\*\s*:?\s*(.+?)(?:\n|$)",
            r"(?:^|\n)\s*[-•]?\s*Absender\s*:\s*(.+?)(?:\n|$)",
        ],
        "patient": [
            r"\*\*Patient[:\*]*\*\*\s*:?\s*(.+?)(?:\n|$)",
            r"(?:^|\n)\s*[-•]?\s*Patient\s*:\s*(.+?)(?:\n|$)",
        ],
    }

    for key, key_patterns in patterns.items():
        for pattern in key_patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                value = match.group(1).strip().strip("*").strip()
                # Entferne Klammerbemerkungen am Ende
                value = re.sub(r"\s*\(.*\)\s*$", "", value)
                result[key] = value
                break

    if result.get("kategorie"):
        logger.info(f"  ✓ Markdown-Parsing erfolgreich: {result}")
        return result

    return None


def _contains_own_name(text: str, eigener_name: str) -> bool:
    """Prüfe ob der Text den eigenen Namen (Empfänger) enthält."""
    if not eigener_name or not text:
        return False
    text_lower = text.lower()
    # Prüfe den vollständigen Namen
    if eigener_name.lower() in text_lower:
        return True
    # Prüfe einzelne relevante Namensbestandteile (mind. 3 Buchstaben)
    # Ignoriere Titel, Abkürzungen und Adressen
    ignore_parts = {"dr", "dr.", "med", "med.", "prof", "prof.", "str", "str.",
                    "huttenstr", "huttenstr.", "praxis", "herr", "frau"}
    name_parts = [p.strip(".,") for p in eigener_name.split()]
    significant_parts = [p for p in name_parts
                         if len(p) >= 3 and p.lower() not in ignore_parts]
    for part in significant_parts:
        if part.lower() in text_lower:
            return True
    return False


def normalize_analysis(data: dict, eigener_name: str = "") -> dict:
    """Normalisiere die Analysedaten und filtere den Empfängernamen heraus."""
    result = {
        "kategorie": str(data.get("kategorie", data.get("Kategorie", "Befund"))).strip(),
        "absender": str(data.get("absender", data.get("Absender", "Unbekannt"))).strip(),
        "patient": str(data.get("patient", data.get("Patient", ""))).strip(),
    }

    # Leere Werte behandeln
    empty_values = ("", "none", "null", "n/a", "-", "unbekannt",
                    "nicht erkennbar", "nicht ersichtlich", "nicht angegeben",
                    "keine angabe", "keine", "k.a.", "k. a.", "n.a.",
                    "kein angabe", "nicht vorhanden", "nicht bekannt")
    if not result["kategorie"] or result["kategorie"].lower().strip() in empty_values:
        result["kategorie"] = "Befund"
    if not result["absender"] or result["absender"].lower().strip() in empty_values:
        result["absender"] = "Unbekannt"
    if not result["patient"] or result["patient"].lower().strip() in empty_values:
        result["patient"] = ""

    # ── EIGENER NAME FILTER ──────────────────────────────────
    # Wenn der Empfängername im Absender steht, wurde er fälschlich erkannt
    if eigener_name and _contains_own_name(result["absender"], eigener_name):
        logger.warning(f"  ⚠ Eigener Name im Absender erkannt: '{result['absender']}' → entfernt")
        result["absender"] = "Unbekannt"

    # Wenn der Empfängername im Patient steht, wurde er fälschlich erkannt
    if eigener_name and _contains_own_name(result["patient"], eigener_name):
        logger.warning(f"  ⚠ Eigener Name im Patient erkannt: '{result['patient']}' → entfernt")
        result["patient"] = ""

    return result


# ──────────────────────────────────────────────────────────────
# PDF → IMAGE
# ──────────────────────────────────────────────────────────────
def pdf_to_image(pdf_path: str, poppler_path: str = "") -> Image.Image | None:
    """
    Konvertiere die erste Seite einer PDF in ein Bild.
    Versucht zuerst PyMuPDF (braucht kein Poppler), dann pdf2image als Fallback.
    """
    # ── Methode 1: PyMuPDF (bevorzugt, keine externe Dependency) ──
    if PYMUPDF_AVAILABLE:
        try:
            doc = fitz.open(pdf_path)
            if len(doc) > 0:
                page = doc[0]
                # Hohe Auflösung: 300 DPI (Standard ist 72)
                mat = fitz.Matrix(300 / 72, 300 / 72)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                doc.close()
                logger.info(f"  ✓ PDF→Bild via PyMuPDF ({pix.width}x{pix.height}px)")
                return img
            doc.close()
        except Exception as e:
            logger.warning(f"  PyMuPDF Fehler: {e} – versuche pdf2image...")

    # ── Methode 2: pdf2image + Poppler (Fallback) ──
    if PDF2IMAGE_AVAILABLE:
        try:
            kwargs = {"first_page": 1, "last_page": 1, "dpi": 300}
            if poppler_path and os.path.isdir(poppler_path):
                kwargs["poppler_path"] = poppler_path
            images = convert_from_path(pdf_path, **kwargs)
            if images:
                logger.info(f"  ✓ PDF→Bild via pdf2image/Poppler")
                return images[0]
        except Exception as e:
            logger.warning(f"  pdf2image Fehler: {e}")

    logger.error(f"  ✗ PDF→Bild fehlgeschlagen für {pdf_path}. "
                 f"PyMuPDF={PYMUPDF_AVAILABLE}, pdf2image={PDF2IMAGE_AVAILABLE}")
    return None


# ──────────────────────────────────────────────────────────────
# DATEINAME GENERIEREN
# ──────────────────────────────────────────────────────────────
def generate_new_filename(analysis: dict, timestamp: str) -> str:
    """
    Generiere den neuen Dateinamen basierend auf der Analyse.
    Schema:
      - Werbung: Werbung_[Zeitstempel].pdf
      - Arztbrief: Arztbrief_[Fachrichtung]_[Absender]_[Patient]_[Zeitstempel].pdf
      - Sonstige: [Kategorie]_[Absender]_[Patient]_[Zeitstempel].pdf
    """
    kat = analysis.get("kategorie", "Sonstiges")
    absender = analysis.get("absender", "Unbekannt")
    patient = analysis.get("patient", "")

    if kat.lower() == "werbung":
        filename = f"Werbung_{timestamp}.pdf"
    elif kat.lower() == "arztbrief":
        # Fachrichtung aus Absender extrahieren (z.B. "Kardiologe Müller")
        parts = absender.split()
        if len(parts) >= 2:
            fachrichtung = parts[0]
            arzt_name = "_".join(parts[1:])
        else:
            fachrichtung = "Arzt"
            arzt_name = absender if absender != "Unbekannt" else ""

        components = ["Arztbrief", fachrichtung]
        if arzt_name:
            components.append(arzt_name)
        if patient:
            components.append(patient)
        components.append(timestamp)
        filename = "_".join(components) + ".pdf"
    else:
        components = [kat]
        if absender and absender != "Unbekannt":
            components.append(absender)
        if patient:
            components.append(patient)
        components.append(timestamp)
        filename = "_".join(components) + ".pdf"

    return sanitize_filename(filename)


# ──────────────────────────────────────────────────────────────
# HAUPTVERARBEITUNG EINER DATEI
# ──────────────────────────────────────────────────────────────
def process_single_pdf(pdf_path: str, cfg: dict, dirs: dict) -> dict:
    """
    Verarbeite eine einzelne PDF-Datei.
    Rückgabe: dict mit Ergebnis-Informationen.
    """
    original_name = os.path.basename(pdf_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = {"original": original_name, "status": "pending", "new_name": ""}

    logger.info(f"{'='*60}")
    logger.info(f"▶ Verarbeite: {original_name}")

    # ── SCHRITT 1: BACKUP (CRITICAL) ──────────────────────────
    try:
        archive_name = f"{timestamp}_{original_name}"
        archive_path = unique_filepath(dirs["archiv"], archive_name)
        shutil.copy2(pdf_path, archive_path)
        logger.info(f"  ✓ Backup: {os.path.basename(archive_path)}")
    except Exception as e:
        logger.error(f"  ✗ Backup fehlgeschlagen: {e}")
        result["status"] = "backup_error"
        result["details"] = str(e)
        add_log_entry(original_name, "", "❌ Backup-Fehler", details=str(e))
        return result

    # ── SCHRITT 2: PDF → BILD ─────────────────────────────────
    image = pdf_to_image(pdf_path, cfg.get("poppler_path", ""))
    if image is None:
        logger.error(f"  ✗ PDF konnte nicht in Bild konvertiert werden.")
        error_dest = unique_filepath(dirs["fehler"], f"KONVERTIERUNG_{timestamp}_{original_name}")
        try:
            shutil.move(pdf_path, error_dest)
        except Exception:
            pass
        result["status"] = "conversion_error"
        add_log_entry(original_name, "", "❌ Konvertierungsfehler",
                      details="PDF→Bild fehlgeschlagen")
        return result

    # ── SCHRITT 3: VISION-ANALYSE ─────────────────────────────
    logger.info(f"  ⏳ Sende an Ollama ({cfg['ollama_model']})...")
    analysis = analyze_image_with_ollama(
        image=image,
        ollama_url=cfg["ollama_url"],
        model=cfg["ollama_model"],
        eigener_name=cfg["eigener_name"],
    )

    if analysis is None:
        logger.warning(f"  ✗ Ollama-Analyse fehlgeschlagen → /Fehler")
        error_dest = unique_filepath(dirs["fehler"], f"ANALYSE_{timestamp}_{original_name}")
        try:
            shutil.move(pdf_path, error_dest)
        except Exception:
            pass
        result["status"] = "analysis_error"
        add_log_entry(original_name, os.path.basename(error_dest),
                      "⚠️ Analyse-Fehler → /Fehler",
                      details="Ollama nicht erreichbar oder Parsing fehlgeschlagen")
        return result

    logger.info(f"  ✓ Analyse: Kat={analysis['kategorie']}, "
                f"Abs={analysis['absender']}, Pat={analysis['patient']}")

    # ── SCHRITT 4: UMBENENNUNG ────────────────────────────────
    new_filename = generate_new_filename(analysis, timestamp)
    logger.info(f"  → Neuer Name: {new_filename}")

    # ── SCHRITT 5: VERSCHIEBEN & CLEANUP ──────────────────────
    dest_path = unique_filepath(dirs["umbenannt"], new_filename)
    try:
        shutil.move(pdf_path, dest_path)
        final_name = os.path.basename(dest_path)
        logger.info(f"  ✓ Verschoben nach: /Umbenannt/{final_name}")
        result["status"] = "success"
        result["new_name"] = final_name
        add_log_entry(
            original_name, final_name, "✅ Erfolgreich",
            kategorie=analysis["kategorie"],
            absender=analysis["absender"],
            patient=analysis["patient"],
        )
    except Exception as e:
        logger.error(f"  ✗ Verschieben fehlgeschlagen: {e}")
        result["status"] = "move_error"
        add_log_entry(original_name, new_filename, "❌ Verschiebe-Fehler", details=str(e))

    return result


# ──────────────────────────────────────────────────────────────
# ORDNER-SCAN
# ──────────────────────────────────────────────────────────────
def scan_and_process(cfg: dict) -> list:
    """
    Scanne den Eingangsordner und verarbeite alle PDFs.
    Rückgabe: Liste der Verarbeitungsergebnisse.
    """
    eingang = cfg["eingangsordner"]
    if not eingang or not os.path.isdir(eingang):
        logger.warning("Eingangsordner nicht konfiguriert oder existiert nicht.")
        return []

    dirs = ensure_subdirs(eingang)

    # Finde alle PDFs im Eingangsordner (nicht in Unterordnern)
    pdfs = sorted(
        [
            os.path.join(eingang, f)
            for f in os.listdir(eingang)
            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(eingang, f))
        ]
    )

    if not pdfs:
        logger.info("Keine neuen PDFs im Eingangsordner.")
        return []

    logger.info(f"📬 {len(pdfs)} neue PDF(s) gefunden.")
    results = []
    for pdf_path in pdfs:
        result = process_single_pdf(pdf_path, cfg, dirs)
        results.append(result)
        time.sleep(1)  # Kleine Pause zwischen Dateien

    return results


# ══════════════════════════════════════════════════════════════
#                      STREAMLIT UI
# ══════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="FaxFinity",
        page_icon="📠",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "Get help": None,
            "Report a bug": None,
            "About": "FaxFinity v1.0 – Intelligente Fax-Archivierung",
        },
    )

    # ── Custom CSS ──
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

        /* Global */
        .stApp {
            font-family: 'Inter', sans-serif;
        }

        /* Hide Streamlit deploy button & menu */
        .stDeployButton, [data-testid="stToolbar"] {
            display: none !important;
        }
        header[data-testid="stHeader"] {
            background: transparent !important;
        }

        /* Header */
        .main-header {
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            padding: 2rem 2.5rem;
            border-radius: 16px;
            margin-bottom: 1.5rem;
            color: white;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        .main-header h1 {
            margin: 0;
            font-size: 2.2rem;
            font-weight: 700;
            letter-spacing: -0.5px;
        }
        .main-header p {
            margin: 0.3rem 0 0 0;
            opacity: 0.75;
            font-size: 1rem;
            font-weight: 300;
        }

        /* Status Badge */
        .status-badge {
            display: inline-block;
            padding: 0.35rem 1rem;
            border-radius: 50px;
            font-weight: 600;
            font-size: 0.8rem;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }
        .status-online {
            background: linear-gradient(135deg, #00b09b, #96c93d);
            color: white;
        }
        .status-offline {
            background: linear-gradient(135deg, #e53935, #e35d5b);
            color: white;
        }
        .status-idle {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }

        /* Stat Cards */
        .stat-card {
            background: linear-gradient(145deg, #1e293b, #1a2332);
            border: 1px solid rgba(255,255,255,0.08);
            padding: 1.5rem;
            border-radius: 14px;
            text-align: center;
            color: white;
            box-shadow: 0 4px 20px rgba(0,0,0,0.2);
            transition: transform 0.2s ease;
        }
        .stat-card:hover {
            transform: translateY(-2px);
        }
        .stat-card .stat-number {
            font-size: 2.5rem;
            font-weight: 700;
            color: #ffffff;
            line-height: 1.2;
        }
        .stat-card .stat-label {
            font-size: 0.85rem;
            color: rgba(255,255,255,0.75);
            margin-top: 0.3rem;
            font-weight: 500;
        }

        /* Log Table */
        .log-entry {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            padding: 0.85rem 1.2rem;
            margin-bottom: 0.6rem;
            font-size: 0.88rem;
            color: rgba(255,255,255,0.85);
            transition: background 0.2s ease;
        }
        .log-entry:hover {
            background: rgba(255,255,255,0.08);
        }
        .log-time {
            color: rgba(255,255,255,0.55);
            font-size: 0.75rem;
            font-weight: 400;
        }
        .log-original {
            color: rgba(255,255,255,0.6);
            text-decoration: line-through;
            font-size: 0.82rem;
        }
        .log-new {
            color: #4ade80;
            font-weight: 600;
        }
        .log-status-ok {
            color: #4ade80;
        }
        .log-status-err {
            color: #f87171;
        }

        /* Info Boxes */
        .info-box {
            background: linear-gradient(145deg, #1e293b, #1a2332);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 10px;
            padding: 1rem 1.2rem;
            font-size: 0.9rem;
            color: #e2e8f0;
            margin-bottom: 1rem;
        }
        .info-box strong {
            color: #ffffff;
        }

        /* Sidebar Tweaks */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #1a1f2e 0%, #151a27 100%);
        }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stMarkdown p,
        [data-testid="stSidebar"] .stMarkdown span,
        [data-testid="stSidebar"] .stMarkdown li {
            color: #f1f5f9 !important;
            font-weight: 500 !important;
        }
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] h4 {
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] small,
        [data-testid="stSidebar"] .stTooltipIcon {
            color: #94a3b8 !important;
        }
        /* Force dark backgrounds on ALL input elements in sidebar */
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] [data-baseweb="input"] input,
        [data-testid="stSidebar"] [data-baseweb="base-input"] input,
        [data-testid="stSidebar"] .stTextInput input,
        [data-testid="stSidebar"] .stNumberInput input {
            color: #ffffff !important;
            background-color: #0f1219 !important;
            border-color: rgba(255,255,255,0.2) !important;
            caret-color: #ffffff !important;
        }
        [data-testid="stSidebar"] [data-baseweb="select"] > div,
        [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div {
            color: #ffffff !important;
            background-color: #0f1219 !important;
            border-color: rgba(255,255,255,0.2) !important;
        }
        [data-testid="stSidebar"] [data-baseweb="select"] span {
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] input::placeholder {
            color: rgba(255,255,255,0.35) !important;
        }
        [data-testid="stSidebar"] .stNumberInput button {
            color: #e2e8f0 !important;
            background-color: rgba(255,255,255,0.06) !important;
            border-color: rgba(255,255,255,0.2) !important;
        }
        /* Expander in sidebar */
        [data-testid="stSidebar"] .streamlit-expanderHeader p {
            color: #e2e8f0 !important;
        }

        /* Buttons */
        .stButton > button {
            border-radius: 10px;
            font-weight: 600;
            transition: all 0.2s ease;
        }

        /* Divider */
        .custom-divider {
            border: 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent);
            margin: 1.5rem 0;
        }
    </style>
    """, unsafe_allow_html=True)

    # ── Lade Config ──
    if "config" not in st.session_state:
        st.session_state.config = load_config()
    cfg = st.session_state.config

    if "processing" not in st.session_state:
        st.session_state.processing = False
    if "last_results" not in st.session_state:
        st.session_state.last_results = []

    # ── HEADER ──
    st.markdown("""
    <div class="main-header">
        <h1>📠 FaxFinity</h1>
        <p>Intelligente Fax-Archivierung für Arztpraxen • Vision-LLM powered</p>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════
    #                    SIDEBAR: EINSTELLUNGEN
    # ══════════════════════════════════════════════════════════
    with st.sidebar:
        st.markdown("### ⚙️ Einstellungen")
        st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

        # Eingangsordner
        eingang = st.text_input(
            "📂 Eingangsordner",
            value=cfg.get("eingangsordner", ""),
            help="Pfad zum Ordner, in dem die Fax-PDFs eingehen.",
            placeholder="C:\\Faxe\\Eingang",
        )
        cfg["eingangsordner"] = eingang

        st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

        # Ollama Settings
        st.markdown("#### 🤖 Ollama")
        ollama_url = st.text_input(
            "Server-URL",
            value=cfg.get("ollama_url", "http://localhost:11434"),
            help="URL des Ollama-Servers.",
        )
        cfg["ollama_url"] = ollama_url

        # Modell-Auswahl
        col_model, col_refresh = st.columns([4, 1])
        with col_refresh:
            st.markdown("<br>", unsafe_allow_html=True)
            refresh_models = st.button("🔄", help="Modelle neu laden")

        if "available_models" not in st.session_state or refresh_models:
            with st.spinner("Lade Modelle..."):
                st.session_state.available_models = fetch_ollama_models(ollama_url)

        available = st.session_state.get("available_models", [])
        with col_model:
            if available:
                current_model = cfg.get("ollama_model", "")
                idx = available.index(current_model) if current_model in available else 0
                model = st.selectbox(
                    "Vision-Modell",
                    options=available,
                    index=idx,
                    help="Wähle ein Vision-fähiges Modell.",
                )
            else:
                model = st.text_input(
                    "Vision-Modell (manuell)",
                    value=cfg.get("ollama_model", "llama3.2-vision"),
                    help="Keine Modelle gefunden. Manuelle Eingabe.",
                )
            cfg["ollama_model"] = model

        # Verbindungstest
        if st.button("🔌 Verbindung testen"):
            try:
                r = requests.get(f"{ollama_url}/api/tags", timeout=5)
                if r.status_code == 200:
                    model_count = len(r.json().get("models", []))
                    st.success(f"✅ Verbunden! {model_count} Modell(e) verfügbar.")
                else:
                    st.error(f"❌ Fehler: HTTP {r.status_code}")
            except Exception as e:
                st.error(f"❌ Nicht erreichbar: {e}")

        st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

        # Eigener Name
        eigener_name = st.text_input(
            "👤 Eigener Name / Empfänger",
            value=cfg.get("eigener_name", DEFAULT_CONFIG["eigener_name"]),
            help="Dieser Name wird im Prompt als zu ignorierender Empfänger verwendet.",
        )
        cfg["eigener_name"] = eigener_name

        # Scan-Intervall
        scan_interval = st.number_input(
            "⏱️ Scan-Intervall (Sekunden)",
            min_value=10,
            max_value=600,
            value=cfg.get("scan_interval", 120),
            step=10,
            help="Wie oft soll der Eingangsordner geprüft werden?",
        )
        cfg["scan_interval"] = scan_interval

        st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

        # Speichern
        if st.button("💾 Einstellungen speichern", use_container_width=True):
            save_config(cfg)
            st.success("✅ Gespeichert!")

    # ══════════════════════════════════════════════════════════
    #                    MAIN AREA
    # ══════════════════════════════════════════════════════════

    # ── Statistiken ──
    log_entries = load_processing_log()
    total = len(log_entries)
    success = sum(1 for e in log_entries if "✅" in e.get("status", ""))
    errors = sum(1 for e in log_entries if "❌" in e.get("status", "") or "⚠️" in e.get("status", ""))

    # Ordner-Statistiken
    pending_count = 0
    if cfg["eingangsordner"] and os.path.isdir(cfg["eingangsordner"]):
        pending_count = len([
            f for f in os.listdir(cfg["eingangsordner"])
            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(cfg["eingangsordner"], f))
        ])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{pending_count}</div>
            <div class="stat-label">📬 Wartend</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{success}</div>
            <div class="stat-label">✅ Erfolgreich</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{errors}</div>
            <div class="stat-label">⚠️ Fehler</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-number">{total}</div>
            <div class="stat-label">📊 Gesamt</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

    # ── Steuerung ──
    tab_control, tab_log, tab_details = st.tabs([
        "🎛️ Steuerung", "📋 Verarbeitungs-Log", "📁 Ordner-Übersicht"
    ])

    with tab_control:
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            # Validierung
            ready = True
            issues = []
            if not cfg["eingangsordner"]:
                issues.append("Kein Eingangsordner konfiguriert")
                ready = False
            elif not os.path.isdir(cfg["eingangsordner"]):
                issues.append("Eingangsordner existiert nicht")
                ready = False
            if not cfg["ollama_model"]:
                issues.append("Kein Ollama-Modell gewählt")
                ready = False

            if issues:
                for issue in issues:
                    st.warning(f"⚠️ {issue}")

            if ready:
                st.markdown(
                    '<span class="status-badge status-idle">⏸️ Bereit</span>',
                    unsafe_allow_html=True,
                )

        with col_b:
            if st.button(
                "▶️ Jetzt scannen & verarbeiten",
                disabled=not ready,
                use_container_width=True,
                type="primary",
            ):
                save_config(cfg)
                with st.spinner("🔍 Scanne Eingangsordner und verarbeite PDFs..."):
                    results = scan_and_process(cfg)
                    st.session_state.last_results = results
                if results:
                    successes = sum(1 for r in results if r["status"] == "success")
                    st.success(f"✅ Verarbeitung abgeschlossen: {successes}/{len(results)} erfolgreich.")
                else:
                    st.info("ℹ️ Keine neuen PDFs im Eingangsordner.")
                st.rerun()

        with col_c:
            if ready:
                if st.button("📂 Ordner erstellen", use_container_width=True):
                    ensure_subdirs(cfg["eingangsordner"])
                    st.success("✅ Unterordner erstellt (Archiv, Umbenannt, Fehler)")

        # ── Auto-Scan ──
        st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)
        st.markdown("#### 🔄 Auto-Scan")

        auto_col1, auto_col2 = st.columns([3, 1])
        with auto_col1:
            st.markdown(f"""
            <div class="info-box">
                📡 <strong>Auto-Scan</strong> prüft den Eingangsordner alle 
                <strong>{cfg['scan_interval']} Sekunden</strong> automatisch auf neue PDFs.
                Nutze den Schalter rechts, um den automatischen Modus zu starten/stoppen.
            </div>
            """, unsafe_allow_html=True)

        with auto_col2:
            # Auto-Scan Status aus Config laden (überlebt Browser-Reload)
            if "auto_scan_active" not in st.session_state:
                st.session_state.auto_scan_active = cfg.get("auto_scan_active", False)

            auto_scan = st.toggle(
                "Auto-Scan aktiv",
                value=st.session_state.auto_scan_active,
                key="auto_scan_toggle",
            )

            # Bei Änderung: sofort in Config speichern
            if auto_scan != st.session_state.auto_scan_active:
                st.session_state.auto_scan_active = auto_scan
                cfg["auto_scan_active"] = auto_scan
                save_config(cfg)
            else:
                st.session_state.auto_scan_active = auto_scan

        if auto_scan and ready:
            st.markdown(
                '<span class="status-badge status-online">🟢 Auto-Scan aktiv</span>',
                unsafe_allow_html=True,
            )

            # Zeitstempel für letzten Scan
            if "last_auto_scan" not in st.session_state:
                st.session_state.last_auto_scan = 0.0

            now = time.time()
            elapsed = now - st.session_state.last_auto_scan
            interval = cfg["scan_interval"]

            if elapsed >= interval:
                # Scan durchführen
                st.session_state.last_auto_scan = time.time()
                with st.spinner("🔍 Auto-Scan läuft..."):
                    results = scan_and_process(cfg)
                if results:
                    successes = sum(1 for r in results if r["status"] == "success")
                    st.success(f"✅ {successes}/{len(results)} verarbeitet um {datetime.now().strftime('%H:%M:%S')}")
                else:
                    st.info(f"Keine neuen PDFs ({datetime.now().strftime('%H:%M:%S')})")

            # Countdown bis zum nächsten Scan
            remaining = max(0, int(interval - (time.time() - st.session_state.last_auto_scan)))
            next_scan = datetime.now() + timedelta(seconds=remaining)
            st.markdown(
                f"⏳ Nächster Scan in **{remaining}s** "
                f"(um {next_scan.strftime('%H:%M:%S')}) — "
                f"Intervall: {interval}s"
            )

            # Auto-Rerun nach Intervall
            time.sleep(min(remaining + 1, interval))
            st.rerun()

    with tab_log:
        st.markdown("#### 📋 Letzte Verarbeitungen")
        log_entries = load_processing_log()

        if not log_entries:
            st.info("Noch keine Verarbeitungen durchgeführt.")
        else:
            # Zeige die letzten 10 (oder alle)
            show_all = st.checkbox("Alle Einträge anzeigen", value=False)
            display_entries = log_entries if show_all else log_entries[-10:]
            display_entries = list(reversed(display_entries))  # Neueste zuerst

            for entry in display_entries:
                status_class = "log-status-ok" if "✅" in entry.get("status", "") else "log-status-err"
                patient_info = f" | Patient: {entry['patient']}" if entry.get("patient") else ""
                kategorie_info = f" | {entry.get('kategorie', '')}" if entry.get("kategorie") else ""

                st.markdown(f"""
                <div class="log-entry">
                    <span class="log-time">{entry.get('timestamp', '')}</span>
                    <span class="{status_class}"> {entry.get('status', '')}</span>
                    {kategorie_info}
                    {patient_info}
                    <br>
                    <span class="log-original">{entry.get('original', '')}</span>
                    → <span class="log-new">{entry.get('neu', '')}</span>
                    {f'<br><small style="color:rgba(255,255,255,0.3)">{entry.get("details", "")}</small>' if entry.get("details") else ''}
                </div>
                """, unsafe_allow_html=True)

            # Log löschen
            st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)
            if st.button("🗑️ Log leeren", type="secondary"):
                save_processing_log([])
                st.success("Log wurde geleert.")
                st.rerun()

    with tab_details:
        st.markdown("#### 📁 Ordner-Übersicht")

        if not cfg["eingangsordner"] or not os.path.isdir(cfg["eingangsordner"]):
            st.warning("Kein gültiger Eingangsordner konfiguriert.")
        else:
            base = cfg["eingangsordner"]
            dirs_info = {
                "📬 Eingang": base,
                "🗄️ Archiv": os.path.join(base, "Archiv"),
                "✅ Umbenannt": os.path.join(base, "Umbenannt"),
                "❌ Fehler": os.path.join(base, "Fehler"),
            }

            for label, dir_path in dirs_info.items():
                if os.path.isdir(dir_path):
                    files = [
                        f for f in os.listdir(dir_path)
                        if os.path.isfile(os.path.join(dir_path, f))
                    ]
                    pdf_count = len([f for f in files if f.lower().endswith(".pdf")])
                    with st.expander(f"{label} — {pdf_count} PDF(s)", expanded=(label == "📬 Eingang")):
                        if pdf_count == 0:
                            st.caption("Leer.")
                        else:
                            for f in sorted(files):
                                if f.lower().endswith(".pdf"):
                                    size = os.path.getsize(os.path.join(dir_path, f))
                                    size_str = f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / (1024*1024):.1f} MB"
                                    st.text(f"  📄 {f}  ({size_str})")
                else:
                    with st.expander(f"{label} — nicht erstellt"):
                        st.caption("Ordner existiert noch nicht. Klicke 'Ordner erstellen'.")

            # Fehler-Ordner: Retry
            fehler_dir = os.path.join(base, "Fehler")
            if os.path.isdir(fehler_dir):
                fehler_pdfs = [f for f in os.listdir(fehler_dir) if f.lower().endswith(".pdf")]
                if fehler_pdfs and st.button("🔄 Fehler-Dateien erneut verarbeiten"):
                    # Verschiebe zurück in Eingang
                    moved = 0
                    for f in fehler_pdfs:
                        src = os.path.join(fehler_dir, f)
                        # Entferne Prefix
                        clean_name = re.sub(r"^(ANALYSE|KONVERTIERUNG)_\d{8}_\d{6}_", "", f)
                        dest = unique_filepath(base, clean_name)
                        try:
                            shutil.move(src, dest)
                            moved += 1
                        except Exception:
                            pass
                    st.success(f"✅ {moved} Datei(en) zurück in Eingang verschoben. Starte Scan neu.")
                    st.rerun()


if __name__ == "__main__":
    main()
