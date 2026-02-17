"""
FaxFinity Launcher — Startet die Streamlit-App und öffnet den Browser.
Wird von PyInstaller als EXE verpackt.
"""
import os
import sys
import subprocess
import webbrowser
import time
import threading
import socket


def get_free_port():
    """Finde einen freien Port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def wait_and_open_browser(port, max_wait=30):
    """Warte bis der Server läuft, dann öffne den Browser."""
    url = f"http://localhost:{port}"
    for _ in range(max_wait * 4):  # Prüfe alle 250ms
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(("localhost", port))
                time.sleep(0.5)  # Kurz warten, damit Streamlit fertig initialisiert
                webbrowser.open(url)
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.25)
    # Trotzdem öffnen nach Timeout
    webbrowser.open(url)


def find_python():
    """Finde den Python-Interpreter (nicht die EXE selbst!)."""
    if not getattr(sys, "frozen", False):
        return sys.executable

    # Wenn als EXE: Python aus PATH suchen
    import shutil
    for name in ["python", "python3", "py"]:
        path = shutil.which(name)
        if path:
            return path

    return "python"  # Fallback, hoffend dass es im PATH ist


def main():
    # Bestimme den Pfad zum Skript
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    script_path = os.path.join(base_dir, "faxsort_ai.py")

    if not os.path.exists(script_path):
        print(f"FEHLER: {script_path} nicht gefunden!")
        print(f"Stelle sicher, dass 'faxsort_ai.py' im selben Ordner wie die EXE liegt.")
        input("Drücke Enter zum Beenden...")
        sys.exit(1)

    python_exe = find_python()
    port = 8501

    print("=" * 60)
    print("  FaxFinity v1.0")
    print("  Intelligente Fax-Archivierung fuer Arztpraxen")
    print("=" * 60)
    print()
    print(f"  Python: {python_exe}")
    print(f"  Server: http://localhost:{port}")
    print(f"  Der Browser oeffnet sich gleich automatisch...")
    print()
    print("  Zum Beenden: Dieses Fenster schliessen oder Strg+C")
    print("=" * 60)

    # Browser-Öffnung in Hintergrund-Thread
    browser_thread = threading.Thread(
        target=wait_and_open_browser,
        args=(port,),
        daemon=True,
    )
    browser_thread.start()

    # Streamlit starten
    try:
        subprocess.run(
            [
                python_exe, "-m", "streamlit", "run",
                script_path,
                "--server.headless", "true",
                "--server.port", str(port),
                "--browser.gatherUsageStats", "false",
                "--server.fileWatcherType", "none",
            ],
            cwd=base_dir,
        )
    except KeyboardInterrupt:
        print("\n\nFaxFinity beendet.")
    except FileNotFoundError:
        print(f"\nFEHLER: Python nicht gefunden unter: {python_exe}")
        print("Bitte installiere Python 3.10+ und stelle sicher,")
        print("dass 'Add Python to PATH' aktiviert ist.")
        input("\nDrücke Enter zum Beenden...")
        sys.exit(1)


if __name__ == "__main__":
    main()
