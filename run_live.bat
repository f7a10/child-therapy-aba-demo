@echo off
rem Double-click to start the ABA visual assistant; close this window to stop it.
rem Analysed sessions are kept in a library folder outside the repository
rem (default: %USERPROFILE%\ABA Visual Assistant\sessions). Extra arguments pass through, e.g.
rem   run_live.bat --library "D:\ABA sessions"
rem   run_live.bat --with-simulations      (engineering tests of the live-session shell)
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
