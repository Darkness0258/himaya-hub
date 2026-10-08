@echo off
echo ========================================================
echo   HIMAYA ANDROID AGENT — DEVICE OWNER ENROLLMENT
echo ========================================================
echo.
echo Requirements:
echo 1. Connect child Android device via USB with USB Debugging enabled.
echo 2. Device must have no Google or personal accounts registered yet
echo    (do this right after factory reset or unboxing).
echo.
pause
echo.
echo Checking ADB connection...
adb devices
echo.
echo Installing Himaya Agent APK...
adb install -r app/build/outputs/apk/debug/app-debug.apk
echo.
echo Enrolling Device Owner Mode...
adb shell dpm set-device-owner com.himaya.agent/.DeviceAdminReceiver
echo.
if %ERRORLEVEL% EQU 0 (
    echo ========================================================
    echo   SUCCESS: HIMAYA DEVICE OWNER ENROLLED!
    echo   - Protection survives app-kill and standard reset
    echo   - DISALLOW_CONFIG_VPN and remote lock enabled
    echo ========================================================
) else (
    echo ========================================================
    echo   NOTE: If set-device-owner failed because accounts exist,
    echo   enable Standard Device Admin inside the app instead.
    echo ========================================================
)
pause
