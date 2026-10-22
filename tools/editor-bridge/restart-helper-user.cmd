@echo off
REM One-click elevated helper restart for the user.
REM Right-click -> Run as administrator (or double-click and approve the UAC prompt).
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\editor-bridge\start-elevated.ps1"
echo.
echo Done. If it printed no error, the elevated helper is starting.
echo The env owner will automatically run: discover - inspect - save - FLATTEN - verify.
pause
