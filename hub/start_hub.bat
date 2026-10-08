@echo off
title Himaya Hub - Family Safety Server
echo ========================================================
echo   Starting Himaya Hub (Local-First Safety Server)
echo ========================================================
echo.
cd /d "%~dp0"
echo Web Dashboard available at: http://localhost:8000/dashboard
echo REST & WebSocket API at:   http://localhost:8000
echo DNS Sinkhole listening on: UDP 5353
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
