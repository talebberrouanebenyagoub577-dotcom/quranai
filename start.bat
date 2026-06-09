@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================
echo   منصة صحرا - Sahra AI
echo ==============================
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo [خطأ] Python غير مثبت
    echo حمّل Python من: https://www.python.org/downloads/
    pause
    exit /b 1
)

set "LOCAL_IP="
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -match '^192\\.168\\.' } | Select-Object -First 1 -ExpandProperty IPAddress)"') do set "LOCAL_IP=%%i"
if not defined LOCAL_IP (
    for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\\.|169\\.254\\.)' } | Select-Object -First 1 -ExpandProperty IPAddress)"') do set "LOCAL_IP=%%i"
)

netsh advfirewall firewall show rule name="Sahra AI Port 5000" >nul 2>&1
if errorlevel 1 (
    echo [تنبيه] المنفذ 5000 غير مفتوح للهاتف.
    echo         شغّل allow_phone.bat كمسؤول مرة واحدة.
    echo.
)

echo   الكمبيوتر: http://127.0.0.1:5000
if defined LOCAL_IP (
    echo   الهاتف:    http://!LOCAL_IP!:5000
) else (
    echo   الهاتف:    http://[IP-الكمبيوتر]:5000
)
echo.
echo   الهاتف والكمبيوتر على نفس الواي فاي
echo   لا تستخدم 127.0.0.1 على الهاتف
echo   اضغط Ctrl+C لإيقاف الخادم
echo.
start http://127.0.0.1:5000
python app.py
pause
