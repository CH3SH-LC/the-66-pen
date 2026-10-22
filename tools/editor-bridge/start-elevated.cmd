@echo off
REM Double-click this file to raise the resident elevated helper.
REM
REM Why a .cmd and not just the .ps1: double-clicking a .ps1 opens it in Notepad,
REM and an automated agent is not allowed to put a UAC prompt on screen by itself.
REM Starting the elevation from a shell the user opened keeps that decision with
REM the user, which is where it belongs for a privileged component.
REM
REM Expect exactly one Windows prompt. After that the helper stays up and nothing
REM else in this project asks for elevation again.
REM
REM To stop it early:  start-elevated.cmd -Stop
REM To check it:       start-elevated.cmd -Status
REM Optional: -QueueDir ".runtime/editor-bridge/session-queue" -ConfigPath "path-to-config.json"
REM Relative paths are resolved from the project root; reuse QueueDir for -Status/-Stop.

setlocal
if not defined MILIASTRA_POWERSHELL_HOST (
echo Set MILIASTRA_POWERSHELL_HOST to the explicitly approved absolute PowerShell host.
exit /b 2
)
set "PS=%MILIASTRA_POWERSHELL_HOST%"
"%PS%" -NoProfile -File "%~dp0start-elevated.ps1" %*
echo.
echo exit code: %ERRORLEVEL%
pause
