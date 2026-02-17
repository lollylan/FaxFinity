"""
Build-Skript fuer FaxFinity Portable.
Erstellt einen Ordner 'FaxFinity_Portable' mit allem, was man braucht.
"""
import os
import sys
import shutil
import subprocess

# Windows-Konsole auf UTF-8 setzen
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DIST_DIR = "FaxFinity_Portable"
FILES_TO_COPY = [
    "faxsort_ai.py",
    "requirements.txt",
    "README.md",
]

def main():
    print("=" * 60)
    print("  📦 FaxFinity Portable Builder")
    print("=" * 60)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_path = os.path.join(base_dir, DIST_DIR)

    # 1. Alte Distribution löschen
    if os.path.exists(dist_path):
        print(f"\n🗑️  Lösche altes {DIST_DIR}...")
        shutil.rmtree(dist_path)

    # 2. PyInstaller installieren falls nicht vorhanden
    print("\n📥 Prüfe PyInstaller...")
    try:
        import PyInstaller
        print(f"   ✓ PyInstaller {PyInstaller.__version__} gefunden")
    except ImportError:
        print("   ⏳ Installiere PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 3. Launcher als EXE bauen
    print("\n🔨 Baue FaxFinity.exe...")
    launcher_path = os.path.join(base_dir, "launcher.py")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "FaxFinity",
        "--icon", "NONE",
        "--console",  # Konsole anzeigen für Logs
        "--noconfirm",
        "--clean",
        launcher_path,
    ]

    result = subprocess.run(cmd, cwd=base_dir)
    if result.returncode != 0:
        print("\n❌ PyInstaller Build fehlgeschlagen!")
        sys.exit(1)

    # 4. Distribution zusammenstellen
    print(f"\n📂 Erstelle {DIST_DIR}...")
    os.makedirs(dist_path, exist_ok=True)

    # EXE kopieren
    exe_src = os.path.join(base_dir, "dist", "FaxFinity.exe")
    if os.path.exists(exe_src):
        shutil.copy2(exe_src, dist_path)
        print(f"   ✓ FaxFinity.exe kopiert")
    else:
        print(f"   ❌ EXE nicht gefunden: {exe_src}")
        sys.exit(1)

    # Projektdateien kopieren
    for filename in FILES_TO_COPY:
        src = os.path.join(base_dir, filename)
        if os.path.exists(src):
            shutil.copy2(src, dist_path)
            print(f"   ✓ {filename} kopiert")

    # Batch-Installer erstellen
    installer_bat = os.path.join(dist_path, "ERSTINSTALLATION.bat")
    with open(installer_bat, "w", encoding="utf-8") as f:
        f.write('@echo off\n')
        f.write('chcp 65001 >nul\n')
        f.write('cd /d "%~dp0"\n')
        f.write('echo.\n')
        f.write('echo ============================================================\n')
        f.write('echo   FaxFinity - Erstinstallation\n')
        f.write('echo ============================================================\n')
        f.write('echo.\n')
        f.write('echo Pruefe Python-Installation...\n')
        f.write('python --version >nul 2>&1\n')
        f.write('if errorlevel 1 (\n')
        f.write('    echo.\n')
        f.write('    echo FEHLER: Python ist nicht installiert!\n')
        f.write('    echo Bitte installiere Python 3.10+ von https://python.org\n')
        f.write('    echo Aktiviere dabei "Add Python to PATH"!\n')
        f.write('    echo.\n')
        f.write('    pause\n')
        f.write('    exit /b 1\n')
        f.write(')\n')
        f.write('echo.\n')
        f.write('echo Installiere Abhaengigkeiten...\n')
        f.write('pip install -r requirements.txt\n')
        f.write('echo.\n')
        f.write('if errorlevel 1 (\n')
        f.write('    echo FEHLER bei der Installation!\n')
        f.write('    pause\n')
        f.write('    exit /b 1\n')
        f.write(')\n')
        f.write('echo.\n')
        f.write('echo ============================================================\n')
        f.write('echo   Installation abgeschlossen!\n')
        f.write('echo   Starte FaxFinity mit FaxFinity.exe\n')
        f.write('echo ============================================================\n')
        f.write('echo.\n')
        f.write('pause\n')
    print(f"   ✓ ERSTINSTALLATION.bat erstellt")

    # Cleanup
    print("\n🧹 Aufräumen...")
    for cleanup_dir in ["build", "dist"]:
        path = os.path.join(base_dir, cleanup_dir)
        if os.path.exists(path):
            shutil.rmtree(path)
    spec_file = os.path.join(base_dir, "FaxFinity.spec")
    if os.path.exists(spec_file):
        os.remove(spec_file)

    # Zusammenfassung
    exe_size = os.path.getsize(os.path.join(dist_path, "FaxFinity.exe"))
    total_files = len(os.listdir(dist_path))

    print("\n" + "=" * 60)
    print(f"  ✅ FaxFinity Portable fertig!")
    print(f"     Ordner: {dist_path}")
    print(f"     Dateien: {total_files}")
    print(f"     EXE-Größe: {exe_size / 1024 / 1024:.1f} MB")
    print("=" * 60)
    print()
    print("  Anleitung für Benutzer:")
    print("  1. Den Ordner 'FaxFinity_Portable' auf den Ziel-PC kopieren")
    print("  2. ERSTINSTALLATION.bat einmalig als Admin ausführen")
    print("  3. FaxFinity.exe starten")
    print()


if __name__ == "__main__":
    main()
