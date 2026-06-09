@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================
echo   إعادة تشغيل منصة صحرا
echo ==============================
echo.
echo إيقاف الخادم القديم...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

set "LOCAL_IP="
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -match '^192\\.168\\.' } | Select-Object -First 1 -ExpandProperty IPAddress)"') do set "LOCAL_IP=%%i"
if not defined LOCAL_IP (
    for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\\.|169\\.254\\.)' } | Select-Object -First 1 -ExpandProperty IPAddress)"') do set "LOCAL_IP=%%i"
)

netsh advfirewall firewall show rule name="Sahra AI Port 5000" >nul 2>&1
if errorlevel 1 (
    echo [تنبيه] شغّل allow_phone.bat كمسؤول لفتح الوصول من الهاتف.
    echo.
)

echo   الكمبيوتر: http://127.0.0.1:5000
if defined LOCAL_IP (
    echo   الهاتف:    http://!LOCAL_IP!:5000
) else (
    echo   الهاتف:    http://[IP-الكمبيوتر]:5000
)
echo.
echo تشغيل الخادم الجديد...
start http://127.0.0.1:5000
python app.py
pause
