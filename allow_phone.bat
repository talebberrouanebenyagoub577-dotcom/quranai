@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: يحتاج صلاحيات مسؤول لفتح المنفذ 5000
net session >nul 2>&1
if errorlevel 1 (
    echo يطلب صلاحيات المسؤول...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ==============================
echo   فتح الوصول من الهاتف
echo ==============================
echo.

netsh advfirewall firewall delete rule name="Sahra AI Port 5000" >nul 2>&1
netsh advfirewall firewall add rule name="Sahra AI Port 5000" dir=in action=allow protocol=TCP localport=5000
if errorlevel 1 (
    echo [خطأ] تعذر إضافة قاعدة الجدار الناري
    pause
    exit /b 1
)

set "LOCAL_IP="
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -match '^192\\.168\\.' } | Select-Object -First 1 -ExpandProperty IPAddress)"') do set "LOCAL_IP=%%i"
if not defined LOCAL_IP (
    for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\\.|169\\.254\\.)' } | Select-Object -First 1 -ExpandProperty IPAddress)"') do set "LOCAL_IP=%%i"
)

echo تم فتح المنفذ 5000 في جدار الحماية.
echo.
echo   الكمبيوتر: http://127.0.0.1:5000
if defined LOCAL_IP (
    echo   الهاتف:    http://%LOCAL_IP%:5000
) else (
    echo   الهاتف:    http://[IP-الكمبيوتر]:5000
)
echo.
echo   الهاتف والكمبيوتر على نفس شبكة الواي فاي
echo   لا تستخدم 127.0.0.1 على الهاتف
echo.
pause
