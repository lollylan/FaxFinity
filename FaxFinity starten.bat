@echo off
rem Diese Datei muss reines ASCII bleiben, siehe Einrichten.bat.
title FaxFinity
cd /d "%~dp0"
echo.
echo   FaxFinity laeuft. Dieses Fenster bitte offen lassen.
echo   Zum Beenden: Fenster schliessen oder Strg+C druecken.
echo.
python -m faxfinity
if errorlevel 1 pause
