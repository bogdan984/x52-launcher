@echo off
rem X52 AC8 Launcher - uninstall
set "X52DIR=%~dp0"
cd /d "%TEMP%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%X52DIR%uninstall.ps1"
if errorlevel 10 exit /b 0
echo.
pause
