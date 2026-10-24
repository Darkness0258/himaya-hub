@echo off
title Himaya Windows Agent
cd /d "%~dp0"
echo ========================================================
echo   Himaya Windows agent (visible, with a tray icon)
echo   Logs appear below. Close this window to stop it.
echo ========================================================
where python >nul 2>nul
if errorlevel 1 goto nopython
python himaya_windows_agent.py --console
echo.
pause
exit /b 0

:nopython
echo Python was not found. Install Python 3.9 or newer from https://www.python.org/downloads/
pause
exit /b 1
