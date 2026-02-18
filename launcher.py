"""
FaxFinity Launcher — Startet die Streamlit-App und oeffnet den Browser.
Wird von PyInstaller als EXE verpackt.
"""
import os
import sys
import subprocess
import webbrowser
import time
import threading
import socket
import traceback


def wait_and_open_browser(port, max_wait=30):
    """Warte bis der Server laeuft, dann oeffne den Browser."""
    url = f"http://localhost:{port}"
    for _ in range(max_wait * 4):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(("localhost", port))
                time.sleep(0.5)
                webbrowser.open(url)
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.25)
    webbrowser.open(url)


def find_python():
    """Finde den Python-Interpreter (nicht die EXE selbst!)."""
    if not getattr(sys, "frozen", False):
        return sys.executable

    import shutil
    for name in ["python", "python3", "py"]:
        path = shutil.which(name)
        if path:
            # Sicherstellen, dass es nicht die EXE selbst ist
            try:
                if os.path.samefile(path, sys.executable):
                    continue
            except (OSError, ValueError):
                pass
            return path

    return None


def main():
    # Bestimme den Pfad zum Skript
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    script_path = os.path.join(base_dir, "faxsort_ai.py")

    print("=" * 60)
    print("  FaxFinity v1.0")
    print("  Intelligente Fax-Archivierung fuer Arztpraxen")
    print("=" * 60)
    print()

    # Prüfe ob faxsort_ai.py vorhanden ist
    if not os.path.exists(script_path):
        print(f"  FEHLER: faxsort_ai.py nicht gefunden!")
        print(f"  Gesucht in: {base_dir}")
        print()
        print("  Stelle sicher, dass 'faxsort_ai.py' im selben")
        print("  Ordner wie die EXE liegt.")
        print()
        print("  Dateien im Ordner:")
        try:
            for f in os.listdir(base_dir):
                print(f"    - {f}")
        except Exception:
            print("    (Ordner konnte nicht gelesen werden)")
        return

    # Python finden
    python_exe = find_python()
    if python_exe is None:
        print("  FEHLER: Python wurde nicht gefunden!")
        print()
        print("  Bitte installiere Python 3.10+ von https://python.org")
        print("  WICHTIG: 'Add Python to PATH' aktivieren!")
        return

    print(f"  Skript:  {script_path}")
    print(f"  Python:  {python_exe}")
    print()

    # Prüfe ob Streamlit installiert ist
    print("  Pruefe Streamlit...")
    check = subprocess.run(
        [python_exe, "-c", "import streamlit; print(streamlit.__version__)"],
        capture_output=True, text=True, timeout=15,
    )
    if check.returncode != 0:
        print("  FEHLER: Streamlit ist nicht installiert!")
        print()
        print("  Bitte fuehre zuerst ERSTINSTALLATION.bat aus,")
        print("  oder installiere manuell:")
        print(f"    {python_exe} -m pip install -r requirements.txt")
        return

    st_version = check.stdout.strip()
    port = 8501

    print(f"  Streamlit v{st_version} gefunden")
    print(f"  Server:  http://localhost:{port}")
    print()
    print("  Der Browser oeffnet sich gleich automatisch...")
    print("  Zum Beenden: Dieses Fenster schliessen oder Strg+C")
    print("=" * 60)
    print()

    # Browser-Öffnung in Hintergrund-Thread
    browser_thread = threading.Thread(
        target=wait_and_open_browser,
        args=(port,),
        daemon=True,
    )
    browser_thread.start()

    # Streamlit starten
    result = subprocess.run(
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

    if result.returncode != 0:
        print()
        print(f"  Streamlit wurde mit Fehlercode {result.returncode} beendet.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nFaxFinity beendet.")
    except Exception:
        print("\n  UNERWARTETER FEHLER:")
        print("  " + "-" * 40)
        traceback.print_exc()
    finally:
        print()
        input("  Druecke Enter zum Schliessen...")
