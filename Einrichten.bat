@echo off
rem Diese Datei muss reines ASCII bleiben. cmd.exe merkt sich beim Abarbeiten
rem die Byteposition in der Datei; Mehrbyte-Zeichen verschieben die Offsets und
rem cmd springt dann mitten in eine Zeile. Alle Ausgaben stehen deshalb in
rem werkzeuge\einrichten.py.
cd /d "%~dp0"
python werkzeuge\einrichten.py
if errorlevel 9009 echo Python wurde nicht gefunden. Bitte von python.org installieren und dabei "Add Python to PATH" ankreuzen.
pause
