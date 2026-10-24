@echo off
setlocal
title Himaya Hub
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto nopython

python -c "import fastapi, uvicorn, multipart" >nul 2>nul
if errorlevel 1 goto install
goto run

:install
echo Installing Himaya Hub requirements - this only happens on the first run...
python -m pip install -r requirements.txt
if errorlevel 1 goto failed

:run
echo.
python main.py
echo.
echo The hub has stopped.
pause
exit /b 0

:nopython
echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer, then run this file again.
pause
exit /b 1

:failed
echo Could not install the requirements. Check your internet connection and try again.
pause
exit /b 1
