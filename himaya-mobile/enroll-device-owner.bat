@echo off
setlocal
title Himaya - Device Owner enrollment
cd /d "%~dp0"

echo ========================================================
echo   Himaya Android agent - Device Owner enrollment
echo   Optional and advanced. Read docs\ANDROID.md first.
echo ========================================================
echo.
echo What this does: makes Himaya the Device Owner of the phone. Android then
echo does not let the phone's user uninstall or disable Himaya from Settings.
echo Only a factory reset removes it.
echo.
echo What it does NOT do: hide Himaya. The notification and the app stay visible,
echo and the child should be told. It is meant for a child's phone that you set
echo up yourself.
echo.
echo Requirements:
echo   1. The phone is connected by USB with USB debugging turned on.
echo   2. The phone has NO Google or other accounts yet. Do this right after a
echo      factory reset or unboxing.
echo   3. You built the app: app\build\outputs\apk\debug\app-debug.apk
echo.
pause

where adb >nul 2>nul
if errorlevel 1 goto noadb

if not exist "app\build\outputs\apk\debug\app-debug.apk" goto noapk

echo.
echo Checking the phone is connected...
adb devices
echo.
echo Installing Himaya Agent...
adb install -r "app\build\outputs\apk\debug\app-debug.apk"
if errorlevel 1 goto failed

echo.
echo Making Himaya the Device Owner...
adb shell dpm set-device-owner com.himaya.agent/.DeviceAdminReceiver
if errorlevel 1 goto failed

echo.
echo ========================================================
echo   Done. Himaya is now the Device Owner of this phone.
echo   Open the Himaya app on the phone and connect it to your hub.
echo ========================================================
pause
exit /b 0

:noadb
echo adb was not found. Install the Android platform-tools and add them to PATH.
pause
exit /b 1

:noapk
echo The app has not been built yet. See docs\ANDROID.md, section "Build".
pause
exit /b 1

:failed
echo.
echo ========================================================
echo   That did not work. The usual cause is that the phone already has
echo   an account on it. Remove the accounts or factory reset the phone and
echo   try again, or skip this script: the app also works with the normal
echo   "Lock and erase" switch, without Device Owner.
echo ========================================================
pause
exit /b 1
