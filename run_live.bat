@echo off
rem Double-click to start the live-session app; close this window to stop it.
rem Extra arguments are passed through, e.g. a recorded-session replay:
rem   run_live.bat --replay-video VIDEO.mp4 --replay-observations observations.pending.json ^
rem                --replay-channel posture.pending.json --replay-channel large_movement.pending.json
cd /d "%~dp0"
set PYTHONPATH=
set PYTHONHOME=
if not exist "live-ui\dist\index.html" (
  echo Building the interface once...
  pushd live-ui
  call npm ci --no-audit --no-fund
  call npm run build
  popd
)
start "" http://127.0.0.1:8767/
".venv\Scripts\python.exe" -B -m aba_demo.live %*
pause
