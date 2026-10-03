@echo off
rem Double-click to start the local demo dashboard; close this window to stop it.
cd /d "%~dp0"
set PYTHONPATH=
set PYTHONHOME=
start "" http://127.0.0.1:8766/
".venv\Scripts\python.exe" -B -m aba_demo.server
pause
