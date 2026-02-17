@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ============================================================
echo   FaxFinity - Erstinstallation
echo ============================================================
echo.
echo Pruefe Python-Installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo FEHLER: Python ist nicht installiert!
    echo Bitte installiere Python 3.10+ von https://python.org
    echo Aktiviere dabei "Add Python to PATH"!
    echo.
    pause
    exit /b 1
)
echo.
echo Installiere Abhaengigkeiten...
pip install -r requirements.txt
echo.
if errorlevel 1 (
    echo FEHLER bei der Installation!
    pause
    exit /b 1
)
echo.
echo ============================================================
echo   Installation abgeschlossen!
echo   Starte FaxFinity mit FaxFinity.exe
echo ============================================================
echo.
pause
