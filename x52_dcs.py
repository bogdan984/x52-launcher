# -*- coding: utf-8 -*-
"""
Автопереключение профиля:
  * по активной программе Windows (любая игра) — foreground_process();
  * по самолёту в DCS World — маленький скрипт экспорта DCS отправляет лаунчеру имя самолёта по UDP
    на 127.0.0.1. Скрипт подключается одной строкой в Saved Games\\DCS*\\Scripts\\Export.lua и
    вызывает прежние обработчики экспорта (SRS, Tacview, DCS-BIOS и т.п. продолжают работать).
"""

import glob
import os
import re
import socket
import threading
import time

IS_WIN = os.name == "nt"
DCS_PORT = 7778
SCRIPT_NAME = "x52launcher_export.lua"
MARK = "-- X52 Launcher: определение самолёта для автопереключения профиля"
DOFILE_LINE = ("local x52l_lfs = require('lfs'); dofile(x52l_lfs.writedir() .. 'Scripts/%s')  %s"
               % (SCRIPT_NAME, MARK))

LUA_SCRIPT = r'''-- X52 Launcher: сообщает лаунчеру, на каком самолёте вы летите (для автопереключения профиля).
-- Отправляет только имя своего самолёта на 127.0.0.1 (ваш компьютер). Удаляется из лаунчера.
local X52L_PORT = %PORT%
local x52l = { last = nil, t = -1000, sent_t = -1000 }

do
  local ok = pcall(function()
    package.path  = package.path  .. ";.\\LuaSocket\\?.lua"
    package.cpath = package.cpath .. ";.\\LuaSocket\\?.dll"
    local socket = require("socket")
    x52l.udp = socket.udp()
    x52l.udp:settimeout(0)
    x52l.udp:setpeername("127.0.0.1", X52L_PORT)
  end)
  if not ok then x52l.udp = nil end
end

local function x52l_send(name)
  if x52l.udp then pcall(function() x52l.udp:send("X52L aircraft " .. (name or "")) end) end
end

local function x52l_tick()
  local now = (LoGetModelTime and LoGetModelTime()) or 0
  if now < x52l.t then x52l.t = -1000; x52l.sent_t = -1000 end      -- новая миссия
  if now - x52l.t < 1 then return end
  x52l.t = now
  local d = LoGetSelfData and LoGetSelfData()
  local name = d and d.Name or ""
  if name ~= x52l.last or now - x52l.sent_t >= 5 then                -- раз в 5 с повтор
    x52l.last = name
    x52l.sent_t = now
    x52l_send(name)
  end
end

-- цепочка: сначала прежние обработчики (SRS, Tacview, DCS-BIOS...), затем наш — в pcall
local x52l_prev_after = LuaExportAfterNextFrame
LuaExportAfterNextFrame = function()
  if x52l_prev_after then x52l_prev_after() end
  pcall(x52l_tick)
end

local x52l_prev_stop = LuaExportStop
LuaExportStop = function()
  if x52l_prev_stop then x52l_prev_stop() end
  pcall(function()
    x52l_send("")
    if x52l.udp then x52l.udp:close(); x52l.udp = nil end
  end)
end
'''


def lua_script(port=DCS_PORT):
    return LUA_SCRIPT.replace("%PORT%", str(int(port)))


# ----------------------------------------------------------------------
# Поиск папок DCS в «Сохранённых играх»
# ----------------------------------------------------------------------
def saved_games_dir():
    if IS_WIN:
        try:
            import ctypes
            import uuid
            guid = uuid.UUID("{4C5C32FF-BB9D-43b0-B5B4-2D72E54EAAA4}")   # FOLDERID_SavedGames

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                            ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]
            g = GUID(guid.fields[0], guid.fields[1], guid.fields[2],
                     (ctypes.c_ubyte * 8).from_buffer_copy(guid.bytes[8:]))
            p = ctypes.c_wchar_p()
            shell = ctypes.WinDLL("shell32")
            if shell.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                path = p.value
                ctypes.WinDLL("ole32").CoTaskMemFree(p)
                if path:
                    return path
        except Exception:  # noqa
            pass
    return os.path.join(os.path.expanduser("~"), "Saved Games")


def find_dcs_dirs(base=None):
    """Папки DCS, DCS.openbeta, DCS.server и т.п. — где лежит (или может лежать) Config."""
    base = base or saved_games_dir()
    out = []
    for p in sorted(glob.glob(os.path.join(base, "DCS*"))):
        if os.path.isdir(p) and (os.path.isdir(os.path.join(p, "Config")) or
                                 os.path.isdir(os.path.join(p, "Scripts"))):
            out.append(p)
    return out


def _export_path(dcs_dir):
    return os.path.join(dcs_dir, "Scripts", "Export.lua")


def is_installed(dcs_dir):
    try:
        with open(_export_path(dcs_dir), encoding="utf-8", errors="replace") as f:
            return MARK in f.read() and os.path.isfile(os.path.join(dcs_dir, "Scripts", SCRIPT_NAME))
    except OSError:
        return False


def install(dcs_dir, port=DCS_PORT):
    """Кладёт скрипт и добавляет ОДНУ строку в конец Export.lua (остальное не трогает).
    Перед первым изменением делает копию Export.lua.x52bak."""
    sd = os.path.join(dcs_dir, "Scripts")
    os.makedirs(sd, exist_ok=True)
    with open(os.path.join(sd, SCRIPT_NAME), "w", encoding="utf-8", newline="\n") as f:
        f.write(lua_script(port))
    ep = _export_path(dcs_dir)
    text = ""
    if os.path.isfile(ep):
        with open(ep, encoding="utf-8", errors="replace", newline="") as f:
            text = f.read()
        bak = ep + ".x52bak"
        if not os.path.exists(bak):
            with open(bak, "w", encoding="utf-8", newline="") as f:
                f.write(text)
    if MARK in text:
        return False                  # уже подключено
    nl = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith(("\n", "\r")):
        text += nl
    text += DOFILE_LINE + nl
    with open(ep, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return True


def uninstall(dcs_dir):
    """Убирает только свою строку и свой файл; чужие строки Export.lua не трогает."""
    ep = _export_path(dcs_dir)
    changed = False
    if os.path.isfile(ep):
        with open(ep, encoding="utf-8", errors="replace", newline="") as f:
            lines = f.read().splitlines(True)
        keep = [ln for ln in lines if MARK not in ln]
        if len(keep) != len(lines):
            with open(ep, "w", encoding="utf-8", newline="") as f:
                f.write("".join(keep))
            changed = True
    sp = os.path.join(dcs_dir, "Scripts", SCRIPT_NAME)
    if os.path.isfile(sp):
        os.remove(sp)
        changed = True
    return changed


# ----------------------------------------------------------------------
# Приём имени самолёта от DCS
# ----------------------------------------------------------------------
_MSG = re.compile(r"^X52L aircraft (.*)$")


class AircraftListener(threading.Thread):
    def __init__(self, port=DCS_PORT):
        super().__init__(daemon=True)
        self.port = port
        self.aircraft = None       # имя или None (в DCS не летим / нет данных)
        self.updated = 0.0
        self.error = None
        self._halt = threading.Event()
        self.sock = None

    def run(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", self.port))
            self.sock.settimeout(0.3)
        except OSError as e:
            self.error = "порт %d занят или недоступен: %s" % (self.port, e)
            return
        while not self._halt.is_set():
            try:
                data, _addr = self.sock.recvfrom(512)
            except socket.timeout:
                if self.aircraft and time.time() - self.updated > 15:
                    self.aircraft = None         # DCS закрыт или вылетел — данных нет
                continue
            except OSError:
                break
            m = _MSG.match(data.decode("utf-8", "replace").strip())
            if m:
                name = m.group(1).strip()[:80]
                self.aircraft = name or None
                self.updated = time.time()
        try:
            self.sock.close()
        except OSError:
            pass

    def stop(self):
        self._halt.set()


# ----------------------------------------------------------------------
# Активная программа Windows
# ----------------------------------------------------------------------
def foreground_process():
    """Имя exe активного окна (например 'DCS.exe') или None."""
    if not IS_WIN:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.WinDLL("user32")
        k32 = ctypes.WinDLL("kernel32")
        u32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            k32.CloseHandle(h)
    except Exception:  # noqa
        return None
    return None
