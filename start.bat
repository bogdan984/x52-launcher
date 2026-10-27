@echo off
rem X52 AC8 Launcher - start
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo The launcher is not installed yet. Run install.bat first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0x52_ac8_launcher.py"
