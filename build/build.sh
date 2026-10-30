#!/usr/bin/env bash
# Сборка Windows-версии на Linux: Docker + Wine. tobix/pywine (Windows-Python 3.13) — PyInstaller,
# amake/innosetup — установщик (Inno Setup в pywine под Wine не ставится).
# Результат: dist/X52 Launcher/ (программа) и dist/X52_Launcher_Setup_<версия>.exe (установщик).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(grep -oP '^APP_VERSION = "\K[^"]+' "$ROOT/x52_ac8_launcher.py")"
VIGEM_URL="https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe"

mkdir -p "$ROOT/build/redist"
[ -f "$ROOT/build/redist/ViGEmBus_setup.exe" ] || curl -fsSL -o "$ROOT/build/redist/ViGEmBus_setup.exe" "$VIGEM_URL"

docker run --rm -v "$ROOT":/src -w /src tobix/pywine:3.13 bash -c "
set -e
export WINEDEBUG=-all
rm -rf dist build/work
wine python -m pip install -q --disable-pip-version-check pyinstaller==6.16.0 pygame==2.6.1 vgamepad==0.1.0
wine python -m PyInstaller --noconfirm --clean --windowed --onedir --noupx \
  --name 'X52 Launcher' --icon 'Z:\\src\\x52_launcher.ico' --add-data 'Z:\\src\\x52_launcher.ico;.' \
  --collect-all vgamepad --exclude-module pytest \
  --distpath dist --workpath build/work --specpath build/work \
  x52_ac8_launcher.py
chown -R $(id -u):$(id -g) dist build/work
"
chmod 777 "$ROOT/dist"          # в amake/innosetup другой пользователь
# LANG=C.UTF-8 — иначе Wine не видит файлы с русскими именами (ПРИМЕР_СУ-27.txt и т.п.)
docker run --rm -e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 -v "$ROOT":/work -w /work/build amake/innosetup /Q /DAppVersion=$VERSION installer.iss
chmod 755 "$ROOT/dist"
ls -la "$ROOT/dist"
