@echo off
title Himaya Windows Agent
echo ========================================================
echo   Starting Himaya Windows Safety Agent...
echo ========================================================
cd /d "%~dp0"
python himaya_windows_agent.py
pause
