# -*- coding: utf-8 -*-
"""
X52 AC8 Launcher 3.0 — лаунчер для игры в ACE COMBAT 8 с Saitek/Logitech X52.

  * мост X52 -> виртуальный геймпад Xbox 360 (через драйвер ViGEmBus) + клавиатура/мышь;
  * назначение ВСЕХ действий игры (как в меню «Назначение клавиш») на кнопки, хатки
    и направления ЛЮБЫХ осей X52 (ручка, РУД, крутилки, слайдер, мини-стик) — по две привязки;
  * выход каждого действия — геймпад или клавиша (шасси, особое вооружение 1/2 и т.п.);
  * настраиваемый отклик ручки: мёртвая зона, компенсация мёртвой зоны игры, чувствительность,
    кривая, сглаживание; рыскание — порог, удержание/импульсы, задержка;
  * калибровка РУД (газ RT / тормоз LT / нейтраль);
  * обзор: головой через opentrack либо кнопками/мини-стиком X52;
  * вкладка «Установка» и кнопка «Играть».

Установка — install.bat, запуск — start.bat (или ярлык), удаление — uninstall.bat.
НЕ запускайте одновременно с x360ce — будет два виртуальных геймпада.
"""

import gc
import json
import math
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
# X52 читается через DirectInput. Драйверы геймпадов XInput / Windows.Gaming.Input / RawInput / HIDAPI
# лаунчеру не нужны: с ними SDL видел и постоянно опрашивал НАШ ЖЕ виртуальный Xbox-геймпад
# одновременно с игрой. Отключаем их до загрузки pygame.
for _hint in ("SDL_XINPUT_ENABLED", "SDL_JOYSTICK_WGI", "SDL_JOYSTICK_RAWINPUT", "SDL_JOYSTICK_HIDAPI"):
    os.environ.setdefault(_hint, "0")
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import pygame
except ImportError:
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror(
        "Нет pygame",
        "Не установлены библиотеки лаунчера.\n\nЗапустите install.bat из папки программы.")
    sys.exit(1)

try:
    import x52_dcs
    import x52_rsview
    import x52_core as _core_check
    del _core_check
except ImportError:
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror(
        "Нет x52_core.py",
        "Рядом с x52_ac8_launcher.py не найдены файлы x52_core.py / x52_dcs.py / x52_rsview.py.\n\n"
        "Распакуйте архив целиком, со всеми файлами.")
    sys.exit(1)

from x52_core import (  # noqa: E402
    ACTIONS, ACTION_LABEL, ACTION_PAD, ACTION_KEYS, ALL_KEYS, AXIS_ROLES,
    CAL_ROWS, CATEGORIES, EMPTY_OUT, HEAD_SCALES, INTERNAL_ACTIONS, IS_WIN,
    CUSTOM_PREFIX, SEQ_MAX_DELAY_MS, action_label, action_pair, all_action_ids,
    action_steps, clean_profile_name, find_custom, new_custom_id, new_profile_config,
    KeySender, Mapper, OutputLimiter, STICK_PARAMS, STICK_PRESETS, TOKEN_TEXT, YAW_PARAMS, binding_text,
    clamp, compose_camera, default_config, find_opentrack, head_to_stick, key_from_tk_event, key_text,
    keys_text, learn_axis_binding, make_splitter, output_text, sanitize_config, shape_axis,
    choose_profile, conflicting_actions, custom_out_text, _norm_list, analog_axis, GAME_TEMPLATES,
    DCS_CAM, DCS_CAM_LABEL)
import x52_ministick  # noqa: E402

APP_NAME = "X52 Launcher"
APP_VERSION = "5.5.27"
# Собранный exe (PyInstaller): программа в Program Files (только чтение), настройки — в %APPDATA%.
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME) if FROZEN else APP_DIR
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(DATA_DIR, "x52_config.json")
ERROR_LOG = os.path.join(DATA_DIR, "x52_error.log")
SEQ_LOG = os.path.join(DATA_DIR, "x52_seq.log")   # диагностика последовательностей
ICON_PATH = os.path.join(RES_DIR, "x52_launcher.ico")
SELF_EXE = os.path.basename(sys.executable).lower() if FROZEN else "pythonw.exe"   # сам лаунчер — не игра

HEAD_STALE_S = 0.2

VIGEM_REPO = "nefarius/ViGEmBus"
VIGEM_FALLBACK = "https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe"
OT_REPO = "opentrack/opentrack"
OT_FALLBACK = ("https://github.com/opentrack/opentrack/releases/download/opentrack-2026.1.0/"
               "opentrack-2026.1.0-win32-setup.exe")


def profiles_dir():
    return os.path.join(os.path.dirname(CONFIG_PATH), "profiles")


def profile_path(name):
    return os.path.join(profiles_dir(), clean_profile_name(name) + ".json")


def list_profiles():
    """Имена профилей из папки profiles (по полю profile_name внутри файла)."""
    names = []
    try:
        files = sorted(os.listdir(profiles_dir()))
    except OSError:
        return names
    for fn in files:
        if not fn.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(profiles_dir(), fn), encoding="utf-8") as f:
                n = json.load(f).get("profile_name")
        except Exception:  # noqa
            continue
        n = clean_profile_name(n or fn[:-5])
        if n not in names:
            names.append(n)
    return names


def write_json_atomic(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


OVERLAY_DEFAULT = {"enabled": False, "mode": "change", "seconds": 3, "position": "top-right", "size": 22,
                   "color": "#33ff99", "opacity": 0.85, "show_layer": True}
OVERLAY_POS = {"top-left": "Сверху слева", "top-center": "Сверху по центру", "top-right": "Сверху справа",
               "bottom-left": "Снизу слева", "bottom-right": "Снизу справа"}


def sanitize_overlay(o):
    o = o if isinstance(o, dict) else {}
    d = OVERLAY_DEFAULT

    def num(k, lo, hi):
        v = o.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return max(lo, min(hi, v))
        return d[k]
    col = o.get("color")
    return {"enabled": bool(o.get("enabled", d["enabled"])),
            "mode": o.get("mode") if o.get("mode") in ("change", "always") else d["mode"],
            "seconds": int(num("seconds", 1, 30)), "size": int(num("size", 10, 72)),
            "position": o.get("position") if o.get("position") in OVERLAY_POS else d["position"],
            "color": col if isinstance(col, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", col) else d["color"],
            "opacity": float(num("opacity", 0.2, 1.0)),
            "show_layer": bool(o.get("show_layer", d["show_layer"]))}


class GameOverlay(object):
    """Надпись поверх игры: прозрачный фон, клики проходят насквозь, фокус не забирает.
    Окно создаётся один раз и потом не прячется/не показывается заново (это могло бы отнять фокус
    у игры): «скрыть» = полная прозрачность."""
    KEY = "#010203"

    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=self.KEY)
        try:
            self.win.attributes("-transparentcolor", self.KEY)    # только Windows
        except tk.TclError:
            pass
        self.lbl = tk.Label(self.win, text="", bg=self.KEY, fg="#33ff99", font=("Segoe UI", 22, "bold"),
                            padx=10, pady=4)
        self.lbl.pack()
        self.alpha = 0.0
        self._set_alpha(0.0)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.win.update_idletasks()
        self._clickthrough()
        self._hide_job = None
        self.text = ""

    def _hwnd(self):
        try:
            return int(self.win.wm_frame(), 16)
        except (tk.TclError, ValueError):
            return None

    def _clickthrough(self):
        if not IS_WIN:
            return
        try:
            import ctypes
            u32 = ctypes.WinDLL("user32")
            h = self._hwnd()
            if not h:
                return
            u32.GetWindowLongW.restype = ctypes.c_long
            ex = u32.GetWindowLongW(h, -20)                       # GWL_EXSTYLE
            # LAYERED | TRANSPARENT (клики насквозь) | TOOLWINDOW (нет в панели задач) | NOACTIVATE
            ex |= 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000
            u32.SetWindowLongW(h, -20, ex)
        except Exception:  # noqa
            pass

    def _topmost(self):
        if not IS_WIN:
            return
        try:
            import ctypes
            h = self._hwnd()
            if h:   # HWND_TOPMOST; SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
                ctypes.WinDLL("user32").SetWindowPos(h, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        except Exception:  # noqa
            pass

    def _set_alpha(self, a):
        self.alpha = a
        try:
            self.win.attributes("-alpha", a)
        except tk.TclError:
            pass

    def show(self, text, o, sticky):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        self.text = text
        self.lbl.configure(text=text, fg=o["color"], font=("Segoe UI", o["size"], "bold"))
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        m = 24
        x = {"left": m, "center": (sw - w) // 2, "right": sw - w - m}[o["position"].split("-")[1]]
        y = m if o["position"].startswith("top") else sh - h - m - 40
        self.win.geometry(f"+{x}+{y}")
        self._set_alpha(o["opacity"])
        self._topmost()
        if not sticky:
            self._hide_job = self.root.after(int(o["seconds"] * 1000), self.hide)

    def hide(self):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
        self._hide_job = None
        self._set_alpha(0.0)

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


def global_path():
    return os.path.join(os.path.dirname(CONFIG_PATH), "x52_global.json")


def sanitize_shared_ministick(ms):
    """profiles — в каких профилях включён мини-стик. Сами настройки мини-стика и обзора с 5.5.27 хранятся
    в каждом профиле; settings/camera (общие, до 5.5.27) остаются только до переноса в профили. None — ещё нет."""
    if not isinstance(ms, dict):
        return None
    st = ms.get("settings") if isinstance(ms.get("settings"), dict) else {}
    cam = ms.get("camera") if isinstance(ms.get("camera"), dict) else {}
    tmp = sanitize_config({"ministick": st, "camera": cam})
    prof = ms.get("profiles") if isinstance(ms.get("profiles"), list) else []
    names = []
    for p in prof[:200]:
        if isinstance(p, str) and p.strip() and clean_profile_name(p) not in names:
            names.append(clean_profile_name(p))
    if "settings" not in ms:
        return {"profiles": names}
    return {"settings": {k: v for k, v in tmp["ministick"].items() if k != "enabled"},
            "camera": tmp["camera"], "profiles": names}


SETTINGS_MAX_BYTES = 5 * 1024 * 1024


def export_all_settings(path):
    """Все настройки одним zip: x52_config.json, x52_global.json, profiles/*.json. Возвращает число профилей."""
    n = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("x52_config.json", "x52_global.json"):
            src = os.path.join(os.path.dirname(CONFIG_PATH), name)
            if os.path.isfile(src):
                z.write(src, name)
        pd = profiles_dir()
        for fn in sorted(os.listdir(pd)) if os.path.isdir(pd) else []:
            if fn.lower().endswith(".json") and os.path.isfile(os.path.join(pd, fn)):
                z.write(os.path.join(pd, fn), "profiles/" + fn)
                n += 1
    return n


def import_all_settings(path):
    """Zip из export_all_settings -> папка настроек. Берёт только файлы настроек (корректный JSON-объект),
    остальное в архиве игнорирует. Возвращает число профилей; ValueError — архив не подходит."""
    files = {}
    try:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or ".." in name.split("/"):
                    continue
                if name in ("x52_config.json", "x52_global.json"):
                    dest = os.path.join(os.path.dirname(CONFIG_PATH), name)
                elif re.fullmatch(r"profiles/[^/]+\.json", name):
                    stem = name[len("profiles/"):-len(".json")]
                    if not stem.strip() or stem.startswith("."):
                        continue
                    dest = profile_path(stem)
                else:
                    continue
                if info.file_size > SETTINGS_MAX_BYTES:
                    raise ValueError(f"файл {name} слишком большой")
                data = json.loads(z.read(info).decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError(f"файл {name} — не настройки лаунчера")
                files[dest] = data
    except zipfile.BadZipFile:
        raise ValueError("это не zip-архив")
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"повреждённый файл настроек ({e})")
    n = sum(1 for d in files if os.path.dirname(d) == profiles_dir())
    if not n and CONFIG_PATH not in files:
        raise ValueError("в архиве нет настроек X52 Launcher")
    for dest, data in files.items():
        write_json_atomic(dest, data)
    return n


def sanitize_shared_zoom(z):
    """profiles — где включён зум. Настройки зума с 5.5.27 — в каждом профиле; settings (общие, до 5.5.27)
    остаются только до переноса в профили."""
    if not isinstance(z, dict):
        return None
    st = z.get("settings") if isinstance(z.get("settings"), dict) else {}
    tmp = sanitize_config({"zoom": st})
    prof = z.get("profiles") if isinstance(z.get("profiles"), list) else []
    names = []
    for p in prof[:200]:
        if isinstance(p, str) and p.strip() and clean_profile_name(p) not in names:
            names.append(clean_profile_name(p))
    if "settings" not in z:
        return {"profiles": names}
    return {"settings": {k: v for k, v in tmp["zoom"].items() if k != "enabled"}, "profiles": names}


def load_global():
    """Настройки лаунчера, общие для всех профилей."""
    g = {"auto_switch": False, "dcs_port": x52_dcs.DCS_PORT, "overlay": dict(OVERLAY_DEFAULT),
         "wheel": {"enabled": False, "buttons": [23, 24, 25], "profiles": ["", "", ""], "last": None},
         "autostart_bridge": None, "joycpl": False, "ministick": None, "zoom": None}
    try:
        with open(global_path(), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            g["ministick"] = sanitize_shared_ministick(d.get("ministick"))
            g["zoom"] = sanitize_shared_zoom(d.get("zoom"))
            g["auto_switch"] = bool(d.get("auto_switch", False))
            g["joycpl"] = bool(d.get("joycpl", False))
            p = d.get("dcs_port")
            if isinstance(p, int) and not isinstance(p, bool) and 1024 <= p <= 65535:
                g["dcs_port"] = p
            g["overlay"] = sanitize_overlay(d.get("overlay"))
            w = d.get("wheel") if isinstance(d.get("wheel"), dict) else {}
            bt = w.get("buttons") if isinstance(w.get("buttons"), list) else []
            pr = w.get("profiles") if isinstance(w.get("profiles"), list) else []
            ab = d.get("autostart_bridge")
            g["autostart_bridge"] = bool(ab) if isinstance(ab, bool) else None
            g["wheel"] = {
                "last": w.get("last") if (isinstance(w.get("last"), int) and not isinstance(w.get("last"), bool)
                                          and w.get("last") in (0, 1, 2)) else None,
                "enabled": bool(w.get("enabled", False)),
                "buttons": [bt[i] if i < len(bt) and isinstance(bt[i], int) and not isinstance(bt[i], bool)
                            and 0 <= bt[i] < 128 else (23, 24, 25)[i] for i in range(3)],
                "profiles": [clean_profile_name(pr[i]) if i < len(pr) and isinstance(pr[i], str) and pr[i].strip()
                             else "" for i in range(3)]}
    except (OSError, ValueError):
        pass
    return g


def set_low_priority(low):
    """Приоритет процесса лаунчера: «ниже обычного» отдаёт процессор игре. Возвращает True при успехе."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        cls = 0x00004000 if low else 0x00000020   # BELOW_NORMAL / NORMAL_PRIORITY_CLASS
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), cls))
    except Exception:  # noqa
        return False


def log_error(text, path=None):
    try:
        with open(path or ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except OSError:
        pass


# ----------------------------------------------------------------------
# Рабочий поток: владелец pygame, UDP-сокета и виртуального геймпада
# ----------------------------------------------------------------------
class Worker(threading.Thread):
    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.cmds = queue.Queue()
        self.alive = True
        self.joy = None
        self.devices = []
        self.state = {"axes": [], "buttons": [], "hats": [], "name": None}
        self.out = dict(EMPTY_OUT)
        self.bridge_on = False
        self.pad = None
        self.xb = {}
        self.error = None
        self.loop_error = None
        self.events = queue.Queue()   # сообщения для интерфейса (переключение головы и т.п.)
        self._last_frame = None
        self._prev_internal = set()
        self.mapper = Mapper()
        self._seq_log = {}               # aid -> [имя, сколько шагов уже записано в лог] (диагностика)
        self.ministick = None            # x52_ministick reader, запускается в _run
        self.profile_q = queue.Queue()  # «смена профиля» кнопкой X52 -> окно лаунчера
        self.open_count = 0             # сколько раз открывали джойстик
        self._cfg_seen = None
        self.limiter = OutputLimiter()
        self.send_hz = 0.0            # сколько обновлений в секунду реально уходит в игру
        self._sent_n0 = 0
        self.keys = None              # KeySender создаётся при включении моста
        self.loop_hz = 0.0            # фактическая частота цикла (для интерфейса)
        self._hz_n = 0
        self._hz_t = time.perf_counter()
        self.look = (0.0, 0.0)
        self.stick_pos = (0.0, 0.0)
        self._poll_t = time.perf_counter()
        # opentrack
        self.sock = None
        self.sock_key = None
        self._sock_fail_t = 0.0
        self.head_center = (0.0, 0.0)
        self._head_raw = None
        self._head_t = 0.0
        self._pkt = 0
        self._rate_t0 = time.time()
        self._rate = 0.0
        self._cam_s = [0.0, 0.0]
        self._cam_t = time.perf_counter()
        self.head_cam = (0.0, 0.0)
        self.head = {"raw": None, "rate": 0.0, "fresh": False, "listening": False, "error": None}

    def send(self, cmd):
        self.cmds.put(cmd)

    def run(self):
        timer_set = False
        if IS_WIN:
            try:   # точность sleep 1 мс вместо 15.6 мс (иначе реальный опрос ~64 Гц)
                import ctypes
                timer_set = ctypes.WinDLL("winmm").timeBeginPeriod(1) == 0
            except Exception:  # noqa
                pass
        try:
            self._run()
        finally:
            if timer_set:
                try:
                    import ctypes
                    ctypes.WinDLL("winmm").timeEndPeriod(1)
                except Exception:  # noqa
                    pass

    def _run(self):
        try:
            # только то, что нужно: окно событий + джойстики. pygame.init() открывал ещё и звуковое
            # устройство — лишний аудиопоток, работающий всё время игры.
            pygame.display.init()
            pygame.joystick.init()
        except Exception as e:  # noqa
            self.error = f"Не удалось инициализировать pygame: {e}"
            return
        self._scan()
        ms_cfg = self.cfg.get("ministick") or {}
        self.ministick = x52_ministick.make_reader(
            sens=ms_cfg.get("sens", 0.5), timeout_ms=ms_cfg.get("timeout_ms", 80),
            log_cb=log_error)
        if ms_cfg.get("enabled"):
            self.ministick.start()
        last_scan = time.time()
        last_err = None
        while self.alive:
            t0 = time.perf_counter()
            try:
                self._handle_cmds()
                self._head_socket()
                self._head_read()
                self._events()
                if self.joy is None:
                    if time.time() - last_scan > 2.0:
                        last_scan = time.time()
                        self._scan()
                    time.sleep(0.02)
                    continue
                self._poll()
                self.loop_error = None
            except Exception as e:  # noqa
                msg = f"{type(e).__name__}: {e}"
                self.loop_error = msg
                if msg != last_err:
                    last_err = msg
                    log_error(traceback.format_exc())
                time.sleep(0.05)
                continue
            period = 1.0 / max(30, min(1000, int(self.cfg.get("poll_hz", 250))))
            dt = time.perf_counter() - t0
            if dt < period:
                time.sleep(period - dt)
            self._hz_n += 1
            now = time.perf_counter()
            if now - self._hz_t >= 1.0:
                self.loop_hz = self._hz_n / (now - self._hz_t)
                self.send_hz = (self.limiter.sent - self._sent_n0) / (now - self._hz_t) if self.bridge_on else 0.0
                self._sent_n0 = self.limiter.sent
                self._hz_n, self._hz_t = 0, now
        self._stop_bridge()
        self._close_sock()
        if self.ministick:
            try:
                self.ministick.stop()
            except Exception:  # noqa
                pass
        try:
            pygame.quit()
        except Exception:  # noqa
            pass

    def _handle_cmds(self):
        while True:
            try:
                cmd = self.cmds.get_nowait()
            except queue.Empty:
                break
            if cmd == "scan":
                self._scan()
            elif cmd == "start":
                self._start_bridge()
            elif cmd == "stop":
                self._stop_bridge()
            elif cmd == "restart":        # смена профиля: геймпад мог включиться/выключиться
                self._reset_mapper("смена профиля")
                want_pad = bool(self.cfg["game"]["virtual_pad"])
                if self.bridge_on and want_pad and self.pad is None:
                    self._create_pad()
                # уже подключённый геймпад не отключаем (игра увидела бы «геймпад отключён»):
                # в профиле без геймпада он просто стоит в нейтрали
                if self.pad is not None and not want_pad:
                    try:
                        self.pad.reset()
                        self.pad.update()
                    except Exception:  # noqa
                        pass
                if self.keys is not None:     # отпустить клавиши прежнего профиля; ручку/РУД не трогаем
                    try:
                        self.keys.release_all()
                    except Exception:  # noqa
                        pass
                self._last_frame = None
                self._sync_ministick()
            elif cmd == "ms_sync":
                self._sync_ministick()
            elif cmd == "center":
                self.center_view()
            elif cmd == "quit":
                self.alive = False

    def _sync_ministick(self):
        """Чтение мини-стика — по настройкам текущего профиля (вкл./выкл., чувствительность)."""
        r = self.ministick
        if r is None:
            return
        ms = self.cfg.get("ministick") or {}
        r.set_sens(ms.get("sens", 0.5))
        if ms.get("enabled"):
            if not r.ok:
                r.start()
        else:
            r.stop()
        self.mapper.ministick = (0.0, 0.0)

    def _events(self):
        try:
            events = pygame.event.get()
        except pygame.error:
            return
        for ev in events:
            if ev.type == pygame.JOYDEVICEREMOVED and self.joy is not None:
                try:
                    iid = self.joy.get_instance_id()
                except pygame.error:
                    iid = None
                if iid is None or getattr(ev, "instance_id", None) == iid:
                    self._lose_device()

    # ---- устройства
    def _scan(self):
        try:
            pygame.joystick.quit()
            pygame.joystick.init()
        except pygame.error:
            pass
        objs = []
        for i in range(pygame.joystick.get_count()):
            try:
                j = pygame.joystick.Joystick(i)
                name = j.get_name()
            except pygame.error:
                continue
            if "xbox" in name.lower():
                self._close_joy(j)      # свой виртуальный геймпад не держим открытым
                continue
            objs.append(j)
        self.devices = [j.get_name() for j in objs]
        wanted = self.cfg.get("device_name") or ""
        if wanted:
            chosen = next((j for j in objs if j.get_name() == wanted), None)
        else:
            chosen = next((j for j in objs if "x52" in j.get_name().lower()), None)
            if chosen is None and objs:
                chosen = objs[0]
        for j in objs:                  # открытым остаётся только выбранный X52
            if j is not chosen:
                self._close_joy(j)
        self.joy = chosen
        if chosen is not None:
            self.open_count += 1                # джойстик (пере)открыт: зажатые кнопки Windows сообщит не сразу
            self.mapper.wheel_seen = False
        if chosen is None:
            self._publish_empty()

    @staticmethod
    def _close_joy(j):
        try:
            j.quit()
        except Exception:  # noqa
            pass

    def _publish_empty(self):
        self.state = {"axes": [], "buttons": [], "hats": [], "name": None}
        self.out = dict(EMPTY_OUT)
        self._prev_internal = set()
        self._reset_mapper("джойстик потерян или не найден")

    def _reset_mapper(self, why):
        for name, n, _ in self._seq_log.values():
            log_error(f"Последовательность «{name}»: ПРЕРВАНА после шага {n} — {why}", SEQ_LOG)
        self._seq_log = {}
        self.mapper.reset()

    def _log_seq(self, sent):
        """Диагностика в x52_error.log: старт последовательности, каждый шаг (и куда ушли клавиши), конец."""
        m = self.mapper
        for aid in [a for a in self._seq_log if a not in m.seq_start]:
            log_error(f"Последовательность «{self._seq_log.pop(aid)[0]}»: завершена", SEQ_LOG)
        for aid, t0 in m.seq_start.items():
            ca = find_custom(self.cfg, aid)
            if ca is None:
                continue
            steps = action_steps(self.cfg, ca)
            if aid not in self._seq_log:
                self._seq_log[aid] = [ca.get("seq") or aid, 0, set()]
                log_error(f"Последовательность «{self._seq_log[aid][0]}»: старт, шагов {len(steps)}, "
                          f"мост {'вкл' if self.bridge_on else 'ВЫКЛ'}", SEQ_LOG)
            rec = self._seq_log[aid]
            el = (time.perf_counter() - t0) * 1000.0
            while rec[1] < len(steps) and steps[rec[1]]["delay_ms"] <= el:
                st = steps[rec[1]]
                rec[1] += 1
                rec[2] = set()
                log_error(f"  шаг {rec[1]}: {keys_text(st['keys'])} ({st['delay_ms']} мс, держать "
                          f"{st['duration_ms']} мс) → окно {x52_dcs.foreground_process() or '?'}", SEQ_LOG)
            # клавиши других действий, нажатые одновременно с шагом: игра видит их одной комбинацией
            cur = [st for st in steps if st["delay_ms"] <= el < st["delay_ms"] + st["duration_ms"]]
            if cur:
                extra = set(sent) - set().union(*(st["keys"] for st in cur)) - rec[2]
                if extra:
                    rec[2] |= extra
                    log_error(f"    вместе с шагом {rec[1]} нажаты ещё: {keys_text(sorted(extra))}", SEQ_LOG)

    def _lose_device(self):
        self.joy = None
        self._publish_empty()
        self._neutral()

    def center_view(self):
        """Центровка: «мышиный» обзор в центр; голова — текущее положение становится центром."""
        self.look = (0.0, 0.0)
        self.stick_pos = (0.0, 0.0)
        raw = self._head_raw
        if raw is not None and self.head.get("fresh"):
            self.head_center = (raw[3], raw[4])
        self.events.put(("center", None))

    def _poll(self):
        j = self.joy
        try:
            axes = [j.get_axis(i) for i in range(j.get_numaxes())]
            buttons = [j.get_button(i) for i in range(j.get_numbuttons())]
            hats = [tuple(j.get_hat(i)) for i in range(j.get_numhats())]
            name = j.get_name()
        except pygame.error:
            self._lose_device()
            return
        self.state = {"axes": axes, "buttons": buttons, "hats": hats, "name": name}
        if self.cfg is not self._cfg_seen:      # новый профиль: состояние маппера с нуля
            self._cfg_seen = self.cfg
            self._reset_mapper("смена профиля на «%s»" % self.cfg.get("profile_name"))
        if self.ministick is not None and self.ministick.ok:
            self.mapper.ministick = self.ministick.read()
        out = self.mapper.step(self.cfg, axes, buttons, hats)
        self._log_seq(out["keys"])
        if self.mapper.profile_events:
            evs, self.mapper.profile_events = self.mapper.profile_events, []
            for ev in evs:                     # и при выключенном мосте (блок — только во время назначения)
                self.profile_q.put(ev)

        # команды лаунчера — по нажатию (фронт)
        new = out["internal"] - self._prev_internal
        self._prev_internal = set(out["internal"])
        if "TOGGLE_HEAD" in new:
            en = not self.cfg["head"]["enabled"]
            self.cfg["head"]["enabled"] = en
            self.events.put(("head_toggled", en))
        if "CENTER" in new:
            self.center_view()

        t = time.perf_counter()
        dt, self._poll_t = t - self._poll_t, t
        cam, self.look, src, self.stick_pos = compose_camera(self.cfg, (out["cam_x"], out["cam_y"]), self.head_cam,
                                             self.look, dt, self.stick_pos)
        out["cam_x"], out["cam_y"] = clamp(cam[0]), clamp(cam[1])
        out["cam_src"] = src
        self.out = out
        if self.bridge_on:
            self._apply(out)

    # ---- opentrack (UDP over network: 6 little-endian double: x, y, z, yaw, pitch, roll)
    def _close_sock(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _head_socket(self):
        h = self.cfg["head"]
        key = (bool(h["enabled"]), int(h["port"]))
        retry = key[0] and self.sock is None and time.time() - self._sock_fail_t > 3.0
        if key == self.sock_key and not retry:
            return
        self._close_sock()
        self.sock_key = key
        err = None
        if key[0]:
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.bind(("127.0.0.1", key[1]))
                s.setblocking(False)
                self.sock = s
            except OSError as e:
                if s is not None:
                    s.close()
                self._sock_fail_t = time.time()
                err = (f"Не удалось открыть порт {key[1]} (занят другой программой?). "
                       f"Смените порт здесь и в opentrack. [{e}]")
        self._head_raw = None
        self.head = {"raw": None, "rate": 0.0, "fresh": False,
                     "listening": self.sock is not None, "error": err}

    def _head_read(self):
        now = time.time()
        s = self.sock
        if s is not None:
            for _ in range(500):
                try:
                    data = s.recv(4096)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                if len(data) >= 48:
                    v = struct.unpack_from("<6d", data, 0)
                    if all(math.isfinite(x) for x in v):
                        self._head_raw = v
                        self._head_t = now
                        self._pkt += 1
        if now - self._rate_t0 >= 1.0:
            self._rate = self._pkt / (now - self._rate_t0)
            self._pkt = 0
            self._rate_t0 = now
        h = self.cfg["head"]
        fresh = s is not None and self._head_raw is not None and now - self._head_t < HEAD_STALE_S
        tx = ty = 0.0
        if fresh and h["enabled"]:
            _x, _y, _z, yaw, pitch, _roll = self._head_raw
            yaw -= self.head_center[0]
            pitch -= self.head_center[1]
            if h["invert_yaw"]:
                yaw = -yaw
            if h["invert_pitch"]:
                pitch = -pitch
            tx = head_to_stick(yaw, h["yaw_full"], h["deadzone"], h["yaw_exp"]) * h["max_stick"]
            ty = head_to_stick(pitch, h["pitch_full"], h["deadzone"], h["pitch_exp"]) * h["max_stick"]
        t = time.perf_counter()
        dt = min(0.25, max(0.0, t - self._cam_t))
        self._cam_t = t
        tau = h["smoothing_ms"] / 1000.0
        a = 1.0 if tau <= 0 else 1.0 - math.exp(-dt / tau)
        self._cam_s[0] += a * (tx - self._cam_s[0])
        self._cam_s[1] += a * (ty - self._cam_s[1])
        self.head_cam = tuple(0.0 if abs(v) < 1e-3 else clamp(v) for v in self._cam_s)
        self.head = {"raw": self._head_raw, "rate": self._rate if s is not None else 0.0,
                     "fresh": fresh, "listening": s is not None, "error": self.head.get("error")}

    # ---- виртуальный геймпад
    def _start_bridge(self):
        if self.bridge_on:
            return
        if not self.cfg["game"]["virtual_pad"]:
            self.pad = None          # профиль без геймпада (War Thunder и т.п.): только клавиатура
        else:
            if not self._create_pad():
                return
        if self.keys is None:
            try:
                self.keys = KeySender()
            except Exception as e:  # noqa
                self.keys = None
                log_error(f"Клавиатурный вывод недоступен: {e}")
        self._last_frame = None
        self.bridge_on = True
        self._neutral()

    def _create_pad(self):
        try:
            import vgamepad as vg
            B = vg.XUSB_BUTTON
            self.xb = {
                "A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B, "X": B.XUSB_GAMEPAD_X,
                "Y": B.XUSB_GAMEPAD_Y,
                "LB": B.XUSB_GAMEPAD_LEFT_SHOULDER, "RB": B.XUSB_GAMEPAD_RIGHT_SHOULDER,
                "LS": B.XUSB_GAMEPAD_LEFT_THUMB, "RS": B.XUSB_GAMEPAD_RIGHT_THUMB,
                "BACK": B.XUSB_GAMEPAD_BACK, "START": B.XUSB_GAMEPAD_START,
                "DPAD_UP": B.XUSB_GAMEPAD_DPAD_UP, "DPAD_DOWN": B.XUSB_GAMEPAD_DPAD_DOWN,
                "DPAD_LEFT": B.XUSB_GAMEPAD_DPAD_LEFT, "DPAD_RIGHT": B.XUSB_GAMEPAD_DPAD_RIGHT,
            }
            if self.pad is None:
                self.pad = vg.VX360Gamepad()
        except Exception as e:  # noqa
            self.pad = None
            self.error = (
                "Не удалось создать виртуальный Xbox 360 геймпад.\n\n"
                f"{type(e).__name__}: {e}\n\n"
                "Скорее всего не установлен драйвер ViGEmBus. Откройте вкладку «Установка» "
                "и нажмите «Установить ViGEmBus», затем перезагрузите ПК.")
            return False
        return True

    def _stop_bridge(self):
        self._neutral()
        self.bridge_on = False
        self.pad = None
        self._last_frame = None

    def _neutral(self):
        """Отпустить всё: геймпад в ноль, все клавиши вверх."""
        if self.pad is not None:
            try:
                self.pad.reset()
                self.pad.update()
            except Exception:  # noqa
                pass
        if self.keys is not None:
            try:
                self.keys.release_all()
            except Exception:  # noqa
                pass
        self._last_frame = None

    def _apply(self, out):
        now = time.perf_counter()
        if self._last_frame is None:      # после старта/нейтрали — отправить состояние заново
            self.limiter.reset()
            self._last_frame = True
        oc = self.cfg["output"]
        if not self.limiter.decide(out, now, oc["max_hz"], oc["deadband"]):
            return
        self.limiter.mark_sent(out, now)
        if self.keys is not None:
            try:
                self.keys.apply(out["keys"])
            except Exception as e:  # noqa
                log_error(f"Ошибка отправки клавиш: {e}")
        pad = self.pad
        if pad is None or not self.cfg["game"]["virtual_pad"]:
            return
        try:
            for name, const in self.xb.items():
                if name in out["pressed"]:
                    pad.press_button(button=const)
                else:
                    pad.release_button(button=const)
            pad.left_joystick_float(x_value_float=out["roll"], y_value_float=out["pitch"])
            pad.right_joystick_float(x_value_float=out["cam_x"], y_value_float=out["cam_y"])
            pad.left_trigger_float(value_float=out["lt"])
            pad.right_trigger_float(value_float=out["rt"])
            pad.update()
        except Exception as e:  # noqa
            self.error = f"Ошибка отправки в виртуальный геймпад: {e}"
            self._stop_bridge()


# ----------------------------------------------------------------------
# Windows: процессы, реестр, загрузка, ярлыки
# ----------------------------------------------------------------------
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def process_running(image):
    """True/False на Windows, None если проверить нельзя."""
    if not IS_WIN:
        return None
    try:
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                           capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW)
        return image.lower() in (r.stdout or "").lower()
    except Exception:  # noqa
        return None


def uninstall_entries(pattern):
    """Записи «Приложения и возможности», имя которых содержит pattern (без учёта регистра)."""
    if not IS_WIN:
        return []
    import winreg
    res = []
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for root, path in roots:
        try:
            k = winreg.OpenKey(root, path)
        except OSError:
            continue
        with k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                except OSError:
                    continue
                with sub:
                    def val(n):
                        try:
                            return str(winreg.QueryValueEx(sub, n)[0])
                        except OSError:
                            return ""
                    name = val("DisplayName")
                    if name and pattern.lower() in name.lower():
                        res.append({"name": name, "version": val("DisplayVersion"),
                                    "uninstall": val("UninstallString"),
                                    "location": val("InstallLocation")})
    return res


def _find_module(name):
    """importlib.util.find_spec без исключений (модуль может быть уже загружен без __spec__)."""
    import importlib.util
    try:
        return importlib.util.find_spec(name)
    except (ValueError, ImportError):
        mod = sys.modules.get(name)
        return getattr(mod, "__spec__", None) or (mod and type("Spec", (), {"origin": getattr(mod, "__file__", None)})())


def vigem_entries():
    """ViGEmBus записывается под разными именами: «ViGEm Bus Driver» (новые версии)
    или «Nefarius Virtual Gamepad Emulation Bus Driver» (старые MSI, в т.ч. из vgamepad)."""
    seen, res = set(), []
    for e in uninstall_entries("vigem") + uninstall_entries("virtual gamepad emulation"):
        key = (e["name"], e["version"], e["uninstall"])
        if key not in seen:
            seen.add(key)
            res.append(e)
    return res


def driver_selftest(python_exe=None):
    """Пробует создать виртуальный геймпад в отдельном процессе. (ok, сообщение)."""
    if FROZEN and python_exe is None:      # в exe нет python -c: запускаем себя с ключом проверки
        fd, res = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            r = subprocess.run([sys.executable, SELFTEST_ARG, res], timeout=30, creationflags=NO_WINDOW)
            with open(res, encoding="utf-8") as f:
                out = f.read().strip()
        except Exception as e:  # noqa
            return False, f"не удалось запустить проверку: {e}"
        finally:
            try:
                os.remove(res)
            except OSError:
                pass
        if r.returncode == 0 and out == "OK":
            return True, "виртуальный геймпад создаётся — драйвер работает"
        return False, out or f"код {r.returncode}"
    exe = python_exe or sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(cand):
            exe = cand
    code = "import vgamepad,time;p=vgamepad.VX360Gamepad();p.reset();p.update();time.sleep(0.2);print('OK')"
    try:
        r = subprocess.run([exe, "-c", code], capture_output=True, text=True, timeout=30,
                           creationflags=NO_WINDOW)
    except Exception as e:  # noqa
        return False, f"не удалось запустить проверку: {e}"
    if r.returncode == 0 and "OK" in r.stdout:
        return True, "виртуальный геймпад создаётся — драйвер работает"
    err = (r.stderr or r.stdout or "").strip().splitlines()
    return False, (err[-1] if err else f"код {r.returncode}")


SELFTEST_ARG = "--selftest-pad"


def run_selftest(res_path):
    """Режим exe с ключом SELFTEST_ARG: создать геймпад, результат — в файл (у оконного exe нет stdout)."""
    try:
        import vgamepad
        p = vgamepad.VX360Gamepad()
        p.reset()
        p.update()
        time.sleep(0.2)
        msg, code = "OK", 0
    except Exception as e:  # noqa
        msg, code = f"{type(e).__name__}: {e}", 1
    with open(res_path, "w", encoding="utf-8") as f:
        f.write(msg)
    return code


def github_latest_asset(repo, regex, fallback, opener=None):
    """URL последнего релиза на GitHub, имя файла которого подходит под regex."""
    op = opener or urllib.request.urlopen
    hdr = {"User-Agent": "X52-AC8-Launcher"}
    try:   # 1) API
        with op(urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                       headers=hdr), timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        for a in data.get("assets", []):
            if re.search(regex, a.get("name", ""), re.I):
                return a["browser_download_url"]
    except Exception:  # noqa
        pass
    try:   # 2) страница релиза (без лимита API)
        with op(urllib.request.Request(f"https://github.com/{repo}/releases/latest", headers=hdr),
                timeout=15) as r:
            tag = r.geturl().rstrip("/").split("/")[-1]
        with op(urllib.request.Request(f"https://github.com/{repo}/releases/expanded_assets/{tag}",
                                       headers=hdr), timeout=15) as r:
            html = r.read().decode("utf-8", "replace")
        for href in re.findall(r'href="(/[^"]+/releases/download/[^"]+)"', html):
            if re.search(regex, href.rsplit("/", 1)[-1], re.I):
                return "https://github.com" + href
    except Exception:  # noqa
        pass
    return fallback


def download(url, dest_dir, progress=None, opener=None):
    op = opener or urllib.request.urlopen
    name = url.rsplit("/", 1)[-1] or "download.bin"
    dest = os.path.join(dest_dir, name)
    with op(urllib.request.Request(url, headers={"User-Agent": "X52-AC8-Launcher"}), timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        last = 0
        with open(dest + ".part", "wb") as f:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress and total and got - last > total / 10:
                    last = got
                    progress(f"   загружено {got * 100 // total}%")
    if total and got != total:
        raise IOError(f"файл загружен не полностью ({got} из {total} байт)")
    os.replace(dest + ".part", dest)
    return dest


def run_powershell(script, env_extra=None, timeout=60):
    env = dict(os.environ)
    env.update(env_extra or {})
    # вывод в UTF-8: иначе PowerShell пишет в кодировке консоли (cp866) и русский текст в логе ломается
    script = "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + script
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env=env, creationflags=NO_WINDOW)


SHORTCUT_PS = r"""
$ErrorActionPreference = 'Stop'
$desk = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desk ($env:X52_NAME + '.lnk')
# установщик старых версий клал ярлык на общий рабочий стол (C:\Users\Public\Desktop)
$pub = [Environment]::GetFolderPath('CommonDesktopDirectory')
$plnk = if ($pub) { Join-Path $pub ($env:X52_NAME + '.lnk') } else { '' }
$have = (Test-Path -LiteralPath $lnk) -or ($plnk -and (Test-Path -LiteralPath $plnk))
if ($env:X52_ACTION -eq 'remove') {
    if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force }
    if ($plnk -and (Test-Path -LiteralPath $plnk)) {
        try { Remove-Item -LiteralPath $plnk -Force } catch { 'ERR:public'; exit 1 }
    }
    'removed'; exit 0
}
if ($env:X52_ACTION -eq 'check') { if ($have) { 'yes' } else { 'no' }; exit 0 }
if ($have) { 'exists'; exit 0 }
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $env:X52_TARGET
if ($env:X52_SCRIPT) { $s.Arguments = '"' + $env:X52_SCRIPT + '"' }
$s.WorkingDirectory = $env:X52_DIR
if (Test-Path -LiteralPath $env:X52_ICON) { $s.IconLocation = $env:X52_ICON }
$s.Description = 'Saitek/Logitech X52: профили для игр'
$s.Save()
'created'
"""


def pythonw_path():
    exe = sys.executable
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.isfile(cand) else exe


# Драйвер Saitek/Logitech X52 у части пользователей отдаёт колесо режимов как кнопки только пока
# открыты «Свойства» X52 в joy.cpl. Открываем их сами (Win32 через ctypes) и уводим окна за край экрана.
# Раньше это делал PowerShell с Add-Type: C# компилировался во временную DLL, и антивирусы удаляли её как троян.
JOYCPL_ERRORS = {"nox52": "X52 нет в списке игровых устройств",
                 "nobtn": "кнопка «Свойства» не найдена"}
_W32 = None


def _w32():
    global _W32
    if _W32 is None:
        import ctypes
        from ctypes import wintypes as W
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        enum_proc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        for fn, args, res in (
                (u32.EnumWindows, (enum_proc, W.LPARAM), W.BOOL),
                (u32.EnumChildWindows, (W.HWND, enum_proc, W.LPARAM), W.BOOL),
                (u32.GetClassNameW, (W.HWND, W.LPWSTR, ctypes.c_int), ctypes.c_int),
                (u32.GetWindowTextW, (W.HWND, W.LPWSTR, ctypes.c_int), ctypes.c_int),
                (u32.IsWindowVisible, (W.HWND,), W.BOOL),
                (u32.GetWindowThreadProcessId, (W.HWND, ctypes.POINTER(W.DWORD)), W.DWORD),
                (u32.SendMessageW, (W.HWND, W.UINT, ctypes.c_size_t, ctypes.c_ssize_t), ctypes.c_ssize_t),
                (u32.PostMessageW, (W.HWND, W.UINT, ctypes.c_size_t, ctypes.c_ssize_t), W.BOOL),
                (u32.SetWindowPos, (W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    W.UINT), W.BOOL),
                (k32.OpenProcess, (W.DWORD, W.BOOL, W.DWORD), W.HANDLE),
                (k32.VirtualAllocEx, (W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD, W.DWORD),
                 ctypes.c_void_p),
                (k32.VirtualFreeEx, (W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD), W.BOOL),
                (k32.WriteProcessMemory, (W.HANDLE, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
                                          ctypes.c_void_p), W.BOOL),
                (k32.ReadProcessMemory, (W.HANDLE, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
                                         ctypes.c_void_p), W.BOOL),
                (k32.CloseHandle, (W.HANDLE,), W.BOOL)):
            fn.argtypes, fn.restype = args, res
        _W32 = (ctypes, W, u32, k32, enum_proc)
    return _W32


def _windows(parent=None):
    ctypes, W, u32, k32, enum_proc = _w32()
    res = []
    cb = enum_proc(lambda h, l: res.append(h) or True)
    if parent is None:
        u32.EnumWindows(cb, 0)
    else:
        u32.EnumChildWindows(parent, cb, 0)
    return res


def _wclass(h):
    ctypes, W, u32, k32, _ = _w32()
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(h, buf, 256)
    return buf.value


def _wtext(h):
    ctypes, W, u32, k32, _ = _w32()
    buf = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(h, buf, 512)
    return buf.value


def _wpid(h):
    ctypes, W, u32, k32, _ = _w32()
    pid = W.DWORD()
    u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value


def _lv_remote(lv, select=-1):
    """Строки SysListView32 чужого процесса (или выделить строку select): UI Automation видит их не у всех.
    LVITEMW кладём в память процесса списка (той же разрядности, что и мы), текст — по смещению 0x100."""
    ctypes, W, u32, k32, _ = _w32()
    ptr = ctypes.sizeof(ctypes.c_void_p)

    def item(state, text):
        it = bytearray(88 if ptr == 8 else 60)
        struct.pack_into("<ii", it, 12, state, state)              # state, stateMask
        off = 24 if ptr == 8 else 20                               # pszText
        struct.pack_into("<Qi" if ptr == 8 else "<Ii", it, off, text, 512)   # + cchTextMax
        return bytes(it)

    pid = _wpid(lv)
    proc = k32.OpenProcess(0x38, False, pid)                       # VM_OPERATION | VM_READ | VM_WRITE
    if not proc:
        raise OSError(f"OpenProcess {pid}")
    mem = k32.VirtualAllocEx(proc, None, 0x1000, 0x3000, 0x04)
    try:
        if not mem:
            raise OSError(f"VirtualAllocEx {pid}")
        if select >= 0:                                            # LVM_SETITEMSTATE: выделить и сфокусировать
            it = item(3, 0)
            k32.WriteProcessMemory(proc, mem, it, len(it), None)
            u32.SendMessageW(lv, 0x102B, select, mem)
            return []
        res = []
        for i in range(u32.SendMessageW(lv, 0x1004, 0, 0)):        # LVM_GETITEMCOUNT
            it = item(0, mem + 0x100)
            k32.WriteProcessMemory(proc, mem, it, len(it), None)
            n = u32.SendMessageW(lv, 0x1073, i, mem)               # LVM_GETITEMTEXTW
            buf = ctypes.create_string_buffer(n * 2)
            k32.ReadProcessMemory(proc, mem + 0x100, buf, n * 2, None)
            res.append(buf.raw.decode("utf-16-le"))
        return res
    finally:
        if mem:
            k32.VirtualFreeEx(proc, mem, 0, 0x8000)
        k32.CloseHandle(proc)


def _away(h):
    _w32()[2].SetWindowPos(h, None, -32000, -32000, 0, 0, 0x15)


def open_joycpl():
    """Открыть «Свойства» X52 в joy.cpl за краем экрана. (pid joy.cpl или None, сообщение)."""
    if not IS_WIN:
        return None, "доступно только в Windows"
    try:
        u32 = _w32()[2]
        # окна joy.cpl, открытые до нас (вручную), не трогаем: иначе уведём их за экран и убьём при выходе
        before = {h for h in _windows() if _wclass(h) == "#32770"}
        p = subprocess.Popen(["rundll32.exe", "shell32.dll,Control_RunDLL", "joy.cpl"])
    except Exception as e:  # noqa
        return None, str(e)

    def find_x52():
        # окно ищем по содержимому (список со строкой X52), а не по PID: диалог joy.cpl
        # может оказаться в другом процессе, чем запущенный rundll32
        for w in _windows():
            if w in before or _wclass(w) != "#32770" or not u32.IsWindowVisible(w):
                continue
            for lv in _windows(w):
                if _wclass(lv) != "SysListView32":
                    continue
                try:
                    names = _lv_remote(lv)
                except OSError:
                    continue
                for i, name in enumerate(names):
                    if "X52" in name:
                        return w, lv, i
        return None

    clicked = False
    try:
        found = None
        for _ in range(150):
            found = find_x52()
            if found:
                break
            time.sleep(0.1)
        if not found:
            mine = [w for w in _windows() if _wpid(w) == p.pid and u32.IsWindowVisible(w)]
            tree = [f"{_wclass(c)}:{_wtext(c)}" for w in mine for c in _windows(w)]
            items = []
            for w in mine:
                for c in _windows(w):
                    if _wclass(c) == "SysListView32":
                        try:
                            items += _lv_remote(c)
                        except OSError as e:
                            items.append(f"ошибка чтения: {e}")
            diag = (f"rundll32={p.pid} windows={'; '.join(f'{_wclass(w)}:{_wtext(w)}' for w in mine)} "
                    f"tree={'; '.join(tree)} items={'; '.join(items)}")
            raise RuntimeError("nox52", diag)
        main, lv, idx = found
        dlg_pid = _wpid(main)
        _lv_remote(lv, idx)
        time.sleep(0.3)
        btn = next((c for c in _windows(main) if _wclass(c) == "Button"
                    and re.search("Свойства|Properties", _wtext(c).replace("&", ""))), None)
        if not btn:
            raise RuntimeError("nobtn")
        # BM_CLICK через PostMessage: SendMessage ждал бы закрытия модального окна свойств
        u32.PostMessageW(btn, 0xF5, 0, 0)
        clicked = True
        # окно свойств — модальное окно процесса joy.cpl; берём видимые окна верхнего уровня процесса
        # (при показе окно свойств само встаёт по центру экрана)
        sheets = []
        for _ in range(150):
            sheets = [w for w in _windows() if w != main and _wpid(w) == dlg_pid and u32.IsWindowVisible(w)]
            if sheets:
                break
            time.sleep(0.1)
        _away(main)
        for h in sheets:
            _away(h)
        time.sleep(0.5)     # и ещё раз — на случай, если окно встало по центру уже после нас
        for h in sheets:
            _away(h)
    except Exception as e:  # noqa
        # после нажатия «Свойства» процесс не убиваем: принудительное завершение ломает колесо до переподключения X52
        if not clicked:
            p.kill()
        err = e.args[0] if isinstance(e, RuntimeError) and e.args else str(e)
        diag = e.args[1] if isinstance(e, RuntimeError) and len(e.args) > 1 else ""
        return None, JOYCPL_ERRORS.get(err, err) + (f" [{diag}]" if diag else "")
    if not sheets:
        log_error(f"joy.cpl: окно свойств X52 не найдено [joy.cpl={dlg_pid}]")
        return dlg_pid, "окно свойств X52 не найдено"
    return dlg_pid, "свойства X52 открыты (окно за краем экрана)"


def close_joycpl(pid):
    # Сначала закрываем окна (WM_CLOSE): после принудительного завершения страницы свойств драйвер Saitek
    # перестаёт отдавать колесо, пока X52 не переподключат. Первый WM_CLOSE закрывает свойства, второй — joy.cpl.
    if IS_WIN and pid:
        try:
            for force in ([], [], [], ["/F"]):
                r = subprocess.run(["taskkill", "/PID", str(pid), "/T"] + force, capture_output=True,
                                   timeout=10, creationflags=NO_WINDOW)
                if r.returncode == 128:     # процесса уже нет
                    break
                time.sleep(0.5)
        except Exception:  # noqa
            pass


def shortcut(action):
    if not IS_WIN:
        return False, "доступно только в Windows"
    try:
        r = run_powershell(SHORTCUT_PS, {
            "X52_ACTION": action, "X52_NAME": APP_NAME, "X52_TARGET": sys.executable if FROZEN else pythonw_path(),
            "X52_SCRIPT": "" if FROZEN else os.path.abspath(__file__), "X52_DIR": APP_DIR,
            "X52_ICON": sys.executable if FROZEN else ICON_PATH})
    except Exception as e:  # noqa
        return False, str(e)
    out = (r.stdout or "").strip()
    if out.endswith("ERR:public"):
        return False, ("ярлык на общем рабочем столе (для всех пользователей) удаляется только с правами "
                       "администратора — удалите его вручную")
    return r.returncode == 0, {"created": "создан", "exists": "уже есть", "removed": "удалён"}.get(
        out, out or (r.stderr or "").strip())


class TaskRunner(threading.Thread):
    """Выполняет долгие операции (загрузки, проверки) в фоне; лог — через очередь."""
    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.log = queue.Queue()
        self.busy = False

    def submit(self, title, fn):
        self.q.put((title, fn))

    def run(self):
        while True:
            title, fn = self.q.get()
            if fn is None:
                return
            self.busy = True
            self.log.put(("start", title))
            try:
                fn(lambda msg: self.log.put(("line", msg)))
                self.log.put(("done", title))
            except Exception as e:  # noqa
                log_error(traceback.format_exc())
                self.log.put(("fail", f"{title}: {type(e).__name__}: {e}"))
            self.busy = False


# ----------------------------------------------------------------------
# Виджеты
# ----------------------------------------------------------------------
class AxisBar(tk.Canvas):
    def __init__(self, master, width=200, height=16, bipolar=True, color="#3b82f6"):
        super().__init__(master, width=width, height=height, highlightthickness=1,
                         highlightbackground="#999", bg="#f4f4f4")
        self.w, self.h, self.bipolar = width, height, bipolar
        self.rect = self.create_rectangle(0, 0, 0, height, fill=color, width=0)
        if bipolar:
            self.create_line(width / 2, 0, width / 2, height, fill="#888")
        self.txt = self.create_text(width - 4, height / 2, anchor="e", text="",
                                    font=("Consolas", 8), fill="#222")
        self._last = None

    def set(self, v):
        if not math.isfinite(v):
            v = 0.0
        if self._last is not None and abs(v - self._last) < 0.003:
            return
        self._last = v
        if self.bipolar:
            v = clamp(v)
            x0, x1 = sorted((self.w / 2, self.w / 2 + v * self.w / 2))
        else:
            v = clamp(v, 0.0, 1.0)
            x0, x1 = 0, v * self.w
        self.coords(self.rect, x0, 0, x1, self.h)
        self.itemconfigure(self.txt, text=f"{v:+.2f}" if self.bipolar else f"{v:.2f}")


class StickView(tk.Canvas):
    def __init__(self, master, size=84):
        super().__init__(master, width=size, height=size, bg="#f4f4f4",
                         highlightthickness=1, highlightbackground="#999")
        self.s = size
        self.create_line(size / 2, 0, size / 2, size, fill="#ccc")
        self.create_line(0, size / 2, size, size / 2, fill="#ccc")
        self.dot = self.create_oval(0, 0, 10, 10, fill="#ef4444", width=0)
        self._last = None
        self.set(0.0, 0.0)

    def set(self, x, y):
        if (x, y) == self._last:
            return
        self._last = (x, y)
        cx = self.s / 2 + clamp(x) * (self.s / 2 - 6)
        cy = self.s / 2 - clamp(y) * (self.s / 2 - 6)
        self.coords(self.dot, cx - 5, cy - 5, cx + 5, cy + 5)


class CurveView(tk.Canvas):
    """График отклика оси: по X — отклонение X52, по Y — что получает игра. Точка — текущее положение."""
    def __init__(self, master, size=150):
        super().__init__(master, width=size, height=size, bg="#f4f4f4",
                         highlightthickness=1, highlightbackground="#999")
        self.s = size
        self.p = 8
        w = size - 2 * self.p
        for k in range(1, 4):
            x = self.p + w * k / 4
            self.create_line(x, self.p, x, size - self.p, fill="#e2e2e2")
            self.create_line(self.p, x, size - self.p, x, fill="#e2e2e2")
        self.create_line(self.p, size - self.p, size - self.p, self.p, fill="#bbb", dash=(3, 3))
        self.curve = self.create_line(0, 0, 0, 0, fill="#2563eb", width=2)
        self.dot = self.create_oval(0, 0, 0, 0, fill="#ef4444", width=0)
        self._key = None
        self._dot = None

    def _xy(self, x, y):
        w = self.s - 2 * self.p
        return self.p + clamp(x, 0, 1) * w, self.s - self.p - clamp(y, 0, 1) * w

    def set_params(self, r):
        key = tuple(sorted(r.items()))
        if key == self._key:
            return
        self._key = key
        pts = []
        for i in range(0, 101):
            x = i / 100.0
            pts.extend(self._xy(x, shape_axis(x, r)))
        self.coords(self.curve, *pts)

    def set_point(self, x, y):
        k = (round(x, 3), round(y, 3))
        if k == self._dot:
            return
        self._dot = k
        cx, cy = self._xy(x, y)
        self.coords(self.dot, cx - 4, cy - 4, cx + 4, cy + 4)


class WheelWizard(tk.Toplevel):
    """«Определить колесо автоматически»: колесо в положении 1 -> «Начать» -> повернуть в 2 и 3.
    Записываются кнопки, которые были ЕДИНСТВЕННЫМИ зажатыми не меньше STABLE секунд —
    кратковременные нажатия при проходе через среднее положение не считаются."""
    STABLE = 0.25

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Колесо режимов X52")
        self.resizable(False, False)
        self.transient(app)
        self.found = []
        self.running = False
        self._cand, self._since = None, 0.0
        ttk.Label(self, wraplength=430, justify="left", text=(
            "1. Поставьте колесо режимов X52 в положение 1.\n"
            "2. Нажмите «Начать».\n"
            "3. Медленно поверните колесо в положение 2, затем в положение 3.\n\n"
            "Другие кнопки X52 при этом не нажимайте.")).pack(padx=14, pady=(12, 6), anchor="w")
        self.now = ttk.Label(self, text="", foreground="#555")
        self.now.pack(padx=14, anchor="w")
        self.res = tk.Label(self, text="", font=("Segoe UI", 11, "bold"), fg="#1d4ed8", justify="left")
        self.res.pack(padx=14, pady=8, anchor="w")
        bf = ttk.Frame(self)
        bf.pack(fill="x", padx=14, pady=(0, 12))
        self.start_btn = ttk.Button(bf, text="Начать", command=self.start)
        self.start_btn.pack(side="left")
        self.save_btn = ttk.Button(bf, text="Сохранить", command=self.save, state="disabled")
        self.save_btn.pack(side="left", padx=6)
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right")
        self._show()
        self.grab_set()
        self.after(30, self._poll)

    def held(self):
        btns = self.app.worker.state.get("buttons") or []
        return [k for k, v in enumerate(btns) if v]

    def start(self):
        self.found, self.running = [], True
        self._cand = None
        self.start_btn.configure(text="Заново")
        self.save_btn.configure(state="disabled")
        self._show()

    def _show(self):
        if not self.running:
            txt = "Нажмите «Начать», когда колесо в положении 1."
        elif not self.found:
            txt = "Жду: колесо в положении 1…"
        else:
            txt = "\n".join(f"Положение {i + 1} = кнопка {k + 1}" for i, k in enumerate(self.found))
            if len(self.found) < 3:
                txt += f"\nПоверните колесо в положение {len(self.found) + 1}…"
            else:
                txt += "\nГотово — нажмите «Сохранить»."
        self.res.configure(text=txt)

    def step(self, now=None):
        """Один шаг опроса (вызывается таймером; в тестах — напрямую)."""
        now = time.time() if now is None else now
        h = self.held()
        self.now.configure(text="Сейчас нажаты кнопки X52: " + (", ".join(str(k + 1) for k in h) or "—"))
        if not self.running or len(self.found) >= 3:
            return
        cand = h[0] if len(h) == 1 else None
        if cand != self._cand:
            self._cand, self._since = cand, now
            return
        if cand is None or now - self._since < self.STABLE:
            return
        if cand not in self.found:
            self.found.append(cand)
            self._show()
            if len(self.found) == 3:
                self.save_btn.configure(state="normal")

    def _poll(self):
        if not self.winfo_exists():
            return
        try:
            self.step()
        except tk.TclError:
            return
        self.after(30, self._poll)

    def save(self):
        if len(self.found) == 3:
            self.app.set_wheel_buttons(self.found)
            self.destroy()


class ProfileDialog(tk.Toplevel):
    """Новый профиль: имя и шаблон."""
    def __init__(self, master):
        super().__init__(master)
        self.title("Новый профиль")
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        ttk.Label(self, text="Название игры / профиля:").pack(padx=12, pady=(12, 2), anchor="w")
        self.name_var = tk.StringVar(value="War Thunder")
        e = ttk.Entry(self, textvariable=self.name_var, width=40)
        e.pack(padx=12, anchor="w")
        self.tmpl = tk.StringVar(value="wt")
        for key, (game, procs) in GAME_TEMPLATES.items():
            ttk.Radiobutton(self, variable=self.tmpl, value=key,
                            text=f"{game} — игра сама видит X52; автопрофиль по {', '.join(procs)}",
                            command=lambda g=game: self.name_var.set(g)
                            ).pack(padx=12, pady=(10 if key == "dcs" else 2, 2), anchor="w")
        ttk.Radiobutton(self, variable=self.tmpl, value="custom", text=(
            "Другая игра — только свои клавиши, без виртуального геймпада\n"
            "(War Thunder, DCS, Il-2 и т.п.: игра сама видит X52, лаунчер добавляет клавиши)")
            ).pack(padx=12, pady=2, anchor="w")
        ttk.Radiobutton(self, variable=self.tmpl, value="ac8", text=(
            "ACE COMBAT 8 — действия игры и виртуальный геймпад (как сейчас)"),
            command=lambda: self.name_var.set("ACE COMBAT 8")).pack(padx=12, pady=2, anchor="w")
        ttk.Radiobutton(self, variable=self.tmpl, value="copy", text=(
            "Копия текущего профиля — все действия и привязки\n"
            "(для режимов одной игры: «Взлёт», «Полёт», «Посадка» с переключением кнопкой)")
            ).pack(padx=12, pady=2, anchor="w")
        ttk.Label(self, foreground="#555", wraplength=420, justify="left", text=(
            "Назначение осей и выбранный джойстик копируются из текущего профиля.")
            ).pack(padx=12, pady=(6, 0), anchor="w")
        bf = ttk.Frame(self)
        bf.pack(padx=12, pady=12, fill="x")
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="Создать", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda ev: self._ok())
        self.grab_set()
        e.focus_set()
        e.select_range(0, "end")

    def _ok(self):
        n = self.name_var.get().strip()
        if not n:
            return
        self.result = (n, self.tmpl.get())
        self.destroy()


class CustomActionDialog(tk.Toplevel):
    """Своё действие: название, тип (удерживать / переключатель / последовательность),
    срабатывание (обычное / короткое / долгое), слой и клавиши или шаги последовательности."""
    def __init__(self, master, title, ca=None, long_ms=500, layers_on=False, profiles=()):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        ca = ca or {}
        self.keys = list(ca.get("keys", []))
        self.steps = [dict(st, keys=list(st["keys"])) for st in ca.get("steps", [])]
        self.step_keys = []
        pt = ca.get("profile") or {"kind": "cycle", "names": []}
        self.pnames = list(pt.get("names", []))
        self.all_profiles = list(profiles)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=(12, 4))
        ttk.Label(top, text="Название:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=ca.get("name", ""))
        e = ttk.Entry(top, textvariable=self.name_var, width=46)
        e.grid(row=0, column=1, columnspan=3, sticky="w", padx=6)

        ttk.Label(top, text="Тип:").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.mode = tk.StringVar(value=ca.get("mode", "hold"))
        mf = ttk.Frame(top)
        mf.grid(row=1, column=1, columnspan=3, sticky="w", pady=(8, 0))
        for i, (m, t) in enumerate((("hold", "Удерживать"), ("toggle", "Переключатель"),
                                    ("repeat", "Автоповтор"), ("sequence", "Последовательность"),
                                    ("profile", "Смена профиля"), ("camera", "Обзор DCS"))):
            ttk.Radiobutton(mf, text=t, variable=self.mode, value=m, command=self._mode_changed).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 12))
        ttk.Label(top, text="Срабатывание:").grid(row=2, column=0, sticky="nw", pady=(4, 0))
        self.trig = tk.StringVar(value=ca.get("trigger", "press"))
        tf = ttk.Frame(top)
        tf.grid(row=2, column=1, columnspan=3, sticky="w", pady=(4, 0))
        for i, (m, t) in enumerate((("press", "Нажатие"), ("release", "Отпускание"),
                                    ("short", "Короткое нажатие"), ("long", f"Долгое (≥ {long_ms} мс)"))):
            ttk.Radiobutton(tf, text=t, variable=self.trig, value=m).grid(row=i // 2, column=i % 2, sticky="w",
                                                                           padx=(0, 12))
        ttk.Label(top, text="Слой (колесо режимов):").grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.layer = tk.IntVar(value=ca.get("layer", 0))
        lf = ttk.Frame(top)
        lf.grid(row=3, column=1, columnspan=3, sticky="w", pady=(4, 0))
        for v, t in ((0, "Все"), (1, "1"), (2, "2"), (3, "3")):
            ttk.Radiobutton(lf, text=t, variable=self.layer, value=v).pack(side="left", padx=(0, 10))
        if not layers_on:
            ttk.Label(lf, text="(слои выключены — вкладка «Режимы и автопрофиль»)", foreground="#888").pack(side="left")
        ttk.Label(top, foreground="#555", wraplength=520, justify="left", text=(
            "Нажатие — сразу. Отпускание — когда отпустили кнопку (на одну кнопку можно повесить действие на "
            "нажатие и другое на отпускание). Короткое — при отпускании, если держали меньше порога; "
            "долгое — когда держите дольше порога.")
            ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # клавиша (для удерживать/переключатель)
        self.key_frame = ttk.Frame(self)
        ttk.Label(self.key_frame, text="Клавиша в игре:").pack(side="left")
        self.key_lbl = ttk.Label(self.key_frame, text="", font=("Segoe UI", 10, "bold"))
        self.key_lbl.pack(side="left", padx=8)
        ttk.Button(self.key_frame, text="Выбрать…", command=self._pick).pack(side="left")
        self.rep_frame = ttk.Frame(self)
        ttk.Label(self.rep_frame, text="Повторять нажатие каждые, мс:").pack(side="left")
        self.rep_var = tk.StringVar(value=str(ca.get("repeat_ms", 100)))
        ttk.Spinbox(self.rep_frame, from_=30, to=2000, increment=10, width=7,
                    textvariable=self.rep_var).pack(side="left", padx=6)
        ttk.Label(self.rep_frame, text="(пока держите кнопку)", foreground="#555").pack(side="left")

        self.prof_frame = ttk.LabelFrame(self, text="Какой профиль включить")
        self.pkind = tk.StringVar(value=pt.get("kind", "cycle"))
        kf = ttk.Frame(self.prof_frame)
        kf.pack(anchor="w", padx=6, pady=(4, 2))
        for i, (k, t) in enumerate((("cycle", "По кругу из списка"), ("name", "Конкретный профиль"),
                                    ("next", "Следующий (все профили)"), ("prev", "Предыдущий"))):
            ttk.Radiobutton(kf, text=t, variable=self.pkind, value=k, command=self._refresh).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        pr = ttk.Frame(self.prof_frame)
        pr.pack(anchor="w", padx=6, pady=2)
        self.pcombo = ttk.Combobox(pr, state="readonly", values=self.all_profiles, width=30)
        self.pcombo.pack(side="left")
        if self.all_profiles:
            self.pcombo.current(0)
        ttk.Button(pr, text="Добавить", command=self._p_add).pack(side="left", padx=4)
        self.plb = tk.Listbox(self.prof_frame, height=5, width=46, exportselection=False)
        self.plb.pack(anchor="w", padx=6, pady=2)
        pb = ttk.Frame(self.prof_frame)
        pb.pack(anchor="w", padx=6, pady=(0, 6))
        ttk.Button(pb, text="Убрать", command=self._p_del).pack(side="left")
        ttk.Button(pb, text="↑", width=3, command=lambda: self._p_move(-1)).pack(side="left", padx=4)
        ttk.Button(pb, text="↓", width=3, command=lambda: self._p_move(1)).pack(side="left")
        ttk.Label(pb, text="  порядок = порядок переключения", foreground="#555").pack(side="left")

        self.cam_frame = ttk.LabelFrame(self, text="Команда обзора DCS (правый стик виртуального геймпада)")
        self.cam_combo = ttk.Combobox(self.cam_frame, state="readonly", width=52, values=[t for _k, t, _p in DCS_CAM])
        self.cam_combo.pack(anchor="w", padx=6, pady=(4, 2))
        self.cam_combo.set(DCS_CAM_LABEL.get(ca.get("cam") or "left"))
        ttk.Label(self.cam_frame, foreground="#555", wraplength=520, justify="left", text=(
            "Нужен виртуальный геймпад (вкладка «Главная»). В DCS правый стик назначьте на "
            "«Камера в кабине, горизонталь (абсолют)» и «Камера в кабине, вертикаль (абсолют)». "
            "Поведение «как стик» / «как мышь» — как у мини-стика (вкладка «Обзор»).")
            ).pack(anchor="w", padx=6, pady=(0, 6))

        # шаги последовательности
        self.seq_frame = ttk.LabelFrame(self, text="Шаги последовательности (время от нажатия кнопки)")
        self.lb = tk.Listbox(self.seq_frame, height=8, width=64, exportselection=False)
        self.lb.grid(row=0, column=0, columnspan=6, padx=6, pady=6, sticky="we")
        self.lb.bind("<<ListboxSelect>>", lambda ev: self._load_step())
        ttk.Label(self.seq_frame, text="Клавиша:").grid(row=1, column=0, sticky="w", padx=6)
        self.step_key_lbl = ttk.Label(self.seq_frame, text="—", width=22)
        self.step_key_lbl.grid(row=1, column=1, sticky="w")
        ttk.Button(self.seq_frame, text="Выбрать…", command=self._pick_step).grid(row=1, column=2, sticky="w")
        ttk.Label(self.seq_frame, text="Начало, мс (от нажатия кнопки X52):").grid(row=2, column=0, sticky="w", padx=6)
        self.delay_var = tk.StringVar(value="0")
        ttk.Spinbox(self.seq_frame, from_=0, to=SEQ_MAX_DELAY_MS, increment=100, width=8,
                    textvariable=self.delay_var).grid(row=2, column=1, sticky="w")
        ttk.Label(self.seq_frame, text="Держать, мс:").grid(row=2, column=2, sticky="w")
        self.dur_var = tk.StringVar(value="100")
        ttk.Spinbox(self.seq_frame, from_=10, to=10000, increment=10, width=8,
                    textvariable=self.dur_var).grid(row=2, column=3, sticky="w")
        ttk.Label(self.seq_frame, foreground="#555", text=x52_rsview.SEQ_TIME_HINT).grid(
            row=3, column=0, columnspan=4, sticky="w", padx=6)
        bf = ttk.Frame(self.seq_frame)
        bf.grid(row=4, column=0, columnspan=6, sticky="w", padx=6, pady=6)
        ttk.Button(bf, text="Добавить шаг", command=self._add_step).pack(side="left")
        ttk.Button(bf, text="Изменить выбранный", command=self._update_step).pack(side="left", padx=4)
        ttk.Button(bf, text="Удалить выбранный", command=self._del_step).pack(side="left")

        self.btns = ttk.Frame(self)
        ttk.Button(self.btns, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(self.btns, text="OK", command=self._ok).pack(side="right", padx=6)
        self._refresh()
        self._mode_changed()
        self.grab_set()
        e.focus_set()

    def _mode_changed(self):
        for w in (self.key_frame, self.rep_frame, self.seq_frame, self.prof_frame, self.cam_frame, self.btns):
            w.pack_forget()
        m = self.mode.get()
        if m == "camera":
            self.cam_frame.pack(fill="x", padx=12, pady=(8, 2))
        elif m == "sequence":
            self.seq_frame.pack(fill="x", padx=12, pady=(8, 2))
        elif m == "profile":
            self.prof_frame.pack(fill="x", padx=12, pady=(8, 2))
        else:
            self.key_frame.pack(fill="x", padx=12, pady=(10, 2))
            if m == "repeat":
                self.rep_frame.pack(fill="x", padx=12, pady=(4, 2))
        self.btns.pack(fill="x", padx=12, pady=12)

    def _p_add(self):
        n = self.pcombo.get()
        if not n:
            return
        if self.pkind.get() == "name":
            self.pnames = [n]
        elif n not in self.pnames and len(self.pnames) < 20:
            self.pnames.append(n)
        self._refresh()

    def _p_del(self):
        s = self.plb.curselection()
        if s:
            del self.pnames[s[0]]
            self._refresh()

    def _p_move(self, d):
        s = self.plb.curselection()
        if not s:
            return
        i, j = s[0], s[0] + d
        if 0 <= j < len(self.pnames):
            self.pnames[i], self.pnames[j] = self.pnames[j], self.pnames[i]
            self._refresh()
            self.plb.selection_set(j)

    def _refresh(self):
        self.key_lbl.configure(text=keys_text(self.keys) if self.keys else "— не выбрана —")
        self.lb.delete(0, "end")
        for st in self.steps:
            self.lb.insert("end", f"{st['delay_ms']:>6} мс:  {keys_text(st['keys'])}  — держать {st['duration_ms']} мс")
        self.step_key_lbl.configure(text=keys_text(self.step_keys) if self.step_keys else "—")
        self.plb.delete(0, "end")
        kind = self.pkind.get()
        if kind == "name" and len(self.pnames) > 1:
            self.pnames = self.pnames[:1]
        for i, n in enumerate(self.pnames):
            self.plb.insert("end", (f"{i + 1}. " if kind == "cycle" else "") + n)
        st = "normal" if kind in ("cycle", "name") else "disabled"
        self.plb.configure(state=st)

    def _ask_keys(self, keys):
        dlg = KeyDialog(self, "Клавиша", keys, [])
        self.wait_window(dlg)
        self.grab_set()
        return dlg.result

    def _pick(self):
        r = self._ask_keys(self.keys)
        if r is not None:
            self.keys = r
            self._refresh()

    def _pick_step(self):
        r = self._ask_keys(self.step_keys)
        if r is not None:
            self.step_keys = r
            self._refresh()

    def _step_from_inputs(self):
        if not self.step_keys:
            messagebox.showwarning("Шаг", "Выберите клавишу шага.", parent=self)
            return None
        try:
            delay = int(float(self.delay_var.get()))
            dur = int(float(self.dur_var.get()))
        except ValueError:
            messagebox.showwarning("Шаг", "Время — целое число миллисекунд.", parent=self)
            return None
        return {"keys": list(self.step_keys), "delay_ms": max(0, min(SEQ_MAX_DELAY_MS, delay)),
                "duration_ms": max(10, min(10000, dur))}

    def _add_step(self):
        st = self._step_from_inputs()
        if st and len(self.steps) < 50:
            self.steps.append(st)
            self.steps.sort(key=lambda x: x["delay_ms"])
            nxt = st["delay_ms"] + st["duration_ms"] + 100     # подсказка времени следующего шага
            self.delay_var.set(str(nxt))
            self.step_keys = []                                 # клавиша и модификаторы не переносятся
            self._refresh()

    def _sel(self):
        s = self.lb.curselection()
        return s[0] if s else None

    def _load_step(self):
        i = self._sel()
        if i is not None:
            st = self.steps[i]
            self.step_keys = list(st["keys"])
            self.delay_var.set(str(st["delay_ms"]))
            self.dur_var.set(str(st["duration_ms"]))
            self.step_key_lbl.configure(text=keys_text(self.step_keys))

    def _update_step(self):
        i = self._sel()
        if i is None:
            messagebox.showinfo("Шаг", "Выберите в списке шаг, который нужно изменить, поправьте поля и "
                                       "нажмите «Изменить выбранный».", parent=self)
            return
        st = self._step_from_inputs()
        if st:
            self.steps[i] = st
            self.steps.sort(key=lambda x: x["delay_ms"])
            self._refresh()
            j = self.steps.index(st)                            # шаг остаётся выбранным
            self.lb.selection_set(j)
            self.lb.see(j)

    def _del_step(self):
        i = self._sel()
        if i is not None:
            del self.steps[i]
            self._refresh()

    def _ok(self):
        n = self.name_var.get().strip()
        if not n:
            messagebox.showwarning("Своё действие", "Введите название.", parent=self)
            return
        mode = self.mode.get()
        if mode == "sequence" and not self.steps:
            messagebox.showwarning("Своё действие", "Добавьте хотя бы один шаг.", parent=self)
            return
        if mode == "profile":
            if self.pkind.get() in ("cycle", "name") and not self.pnames:
                messagebox.showwarning("Своё действие", "Добавьте профиль (или несколько — для «по кругу»).",
                                       parent=self)
                return
        elif mode not in ("sequence", "camera") and not self.keys:
            messagebox.showwarning("Своё действие", "Выберите клавишу.", parent=self)
            return
        try:
            rep_ms = int(float(self.rep_var.get()))
        except ValueError:
            rep_ms = 100
        self.result = {"name": n[:60], "keys": list(self.keys), "mode": mode, "trigger": self.trig.get(),
                       "layer": int(self.layer.get()), "steps": [dict(st) for st in self.steps],
                       "repeat_ms": max(30, min(2000, rep_ms)),
                       "profile": {"kind": self.pkind.get(), "names": list(self.pnames)},
                       "cam": next((k for k, t, _p in DCS_CAM if t == self.cam_combo.get()), "left")}
        self.destroy()


class KeyDialog(tk.Toplevel):
    """Выбор клавиши (или комбинации до 3 клавиш) для выхода действия."""
    def __init__(self, master, title, keys, default):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.keys = list(keys)
        self.default = list(default)
        ttk.Label(self, wraplength=430, justify="left", text=(
            "Нажмите клавишу на клавиатуре ПК — или выберите её в списке ниже (там же кнопки мыши). "
            "Выбранная клавиша сразу появится крупно ниже; затем нажмите OK. "
            "Раскладка (рус/англ) не важна: клавиша посылается по положению на клавиатуре.\n\n"
            "Клавиша должна совпадать с назначенной в игре (Настройки → Управление → Назначение клавиш).")
            ).pack(padx=12, pady=(12, 6), anchor="w")
        self.combo_var = tk.BooleanVar(value=len(self.keys) > 1)
        ttk.Checkbutton(self, text="Комбинация (несколько клавиш одновременно, до 3)",
                        variable=self.combo_var, takefocus=0).pack(padx=12, anchor="w")
        self.lbl = ttk.Label(self, text="", font=("Segoe UI", 12, "bold"))
        self.lbl.pack(padx=12, pady=8)
        row = ttk.Frame(self)
        row.pack(padx=12, pady=4, fill="x")
        self.names = [key_text(k) for k in ALL_KEYS]
        ttk.Label(row, text="Список:").pack(side="left")
        self.cb = ttk.Combobox(row, state="readonly", values=self.names, width=26, takefocus=0)
        self.cb.pack(side="left", padx=6)
        # выбор в списке применяется сразу (раньше требовалась отдельная кнопка — выбор терялся)
        self.cb.bind("<<ComboboxSelected>>", lambda e: self._pick())
        bf = ttk.Frame(self)
        bf.pack(padx=12, pady=(8, 12), fill="x")
        # кнопки не берут фокус клавиатуры: Пробел/Enter назначаются как клавиши, а не жмут кнопку
        ttk.Button(bf, text="Очистить", takefocus=0, command=lambda: self._set([])).pack(side="left")
        ttk.Button(bf, text="По умолчанию", takefocus=0,
                   command=lambda: self._set(list(self.default))).pack(side="left", padx=6)
        ttk.Button(bf, text="Отмена", takefocus=0, command=self.destroy).pack(side="right")
        ttk.Button(bf, text="OK", takefocus=0, command=self._ok).pack(side="right", padx=6)
        self.bind("<KeyPress>", self._on_key)
        self.cb.bind("<KeyPress>", self._on_key)          # и когда фокус на списке
        self._refresh()
        self.grab_set()
        self.focus_force()

    def _refresh(self):
        self.lbl.configure(text=keys_text(self.keys) if self.keys else "— (нет клавиши) —")

    def _set(self, keys):
        self.keys = keys
        self._refresh()

    def _add(self, k):
        if not k:
            return
        if self.combo_var.get():
            if k not in self.keys:
                self.keys = (self.keys + [k])[-3:]
        else:
            self.keys = [k]
        self._refresh()

    def _pick(self):
        i = self.cb.current()
        if i >= 0:
            self._add(ALL_KEYS[i])

    def _on_key(self, e):
        self._add(key_from_tk_event(e.keysym, e.keycode))
        self.focus_set()
        return "break"

    def _ok(self):
        self.result = list(self.keys)
        self.destroy()


CAM_SRC_TEXT = {"head": "обзор: голова (opentrack)", "mouse": "обзор: X52 «как мышь»",
                "x52": "обзор: X52"}


# ----------------------------------------------------------------------
# Приложение
# ----------------------------------------------------------------------
class App(tk.Tk):
    # режим назначения кнопки: запоминаем, когда он закончился (см. _drain_profile_events)
    @property
    def learn(self):
        return self.__dict__.get("_learn_state")

    @learn.setter
    def learn(self, v):
        if v is None and self.__dict__.get("_learn_state") is not None:
            self.__dict__["_learn_end"] = time.time()
        self.__dict__["_learn_state"] = v

    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION} — Saitek/Logitech X52")
        self.geometry("1240x820")
        self.minsize(1180, 760)
        if IS_WIN and os.path.isfile(ICON_PATH):
            try:
                self.iconbitmap(ICON_PATH)
            except tk.TclError:
                pass

        cfg = self._load_config(CONFIG_PATH, silent=True)
        self.cfg = cfg if cfg is not None else default_config()

        self.worker = Worker(self.cfg)
        self.worker.start()
        self.tasks = TaskRunner()
        self.tasks.start()

        self.learn = None
        self.ot_proc = None
        self._save_job = None
        self._n_axes = -1
        self._n_buttons = -1
        self._last_devices = None
        self._last_loop_err = None
        self._play_pending = None
        self._autostart_done = False
        self._conflict_t = 0.0
        self.conflict = None
        self._building = True
        self._wcache = {}
        # Сборка мусора — только в главном потоке. Иначе она может сработать в потоке опроса X52 и
        # удалять там переменные Tk закрытых окон: такой вызов ждёт главный поток, и опрос X52 /
        # отправка в игру на это время останавливаются.
        gc.disable()
        self._gc_t = time.time()
        self._gc_n = 0
        self.glob = load_global()
        self.cfg["layers"]["buttons"] = [{"type": "button", "index": k} for k in self.glob["wheel"]["buttons"]]
        self.listener = None
        self._joycpl_pid = None
        self.last_proc = None
        self._auto_last = None
        self._auto_t = 0.0
        self._rules = {}
        if self.glob["autostart_bridge"] is None:
            on = bool(self.cfg["launcher"].get("autostart_bridge"))
            for n in list_profiles():
                try:
                    with open(profile_path(n), encoding="utf-8") as f:
                        on = on or bool(json.load(f).get("launcher", {}).get("autostart_bridge"))
                except Exception:  # noqa
                    pass
            self.glob["autostart_bridge"] = on
            self.save_global()
        self._fg_func = x52_dcs.foreground_process
        self._wheel_last = self.glob["wheel"].get("last")
        self._wheel_seen = False
        self._open_seen = 0
        self._ms_shared_init()
        self._ms_shared_apply(self.cfg)
        self._zoom_shared_init()
        self._zoom_shared_apply(self.cfg)
        self.worker.send("ms_sync")
        if self._wheel_last is not None:       # слои сразу знают положение колеса с прошлого запуска
            self.worker.mapper.wheel_last = self._wheel_last + 1
        self._wheel_save_t = None
        self._wheel_pos = None
        self.overlay = None
        self._ov_key = None
        self._ov_top_t = 0.0

        style = ttk.Style(self)
        for th in ("vista", "clam"):
            if th in style.theme_names():
                style.theme_use(th)
                break
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"))
        style.configure("Play.TButton", font=("Segoe UI", 12, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Head.TCheckbutton", font=("Segoe UI", 10, "bold"))

        self._build_menu()
        sb = tk.Frame(self, bg="#e5e7eb")
        sb.pack(fill="x", side="bottom")
        self.prof_status = tk.Label(sb, text="Текущий профиль: ", anchor="w", bg="#e5e7eb", padx=8, pady=4,
                                    font=("Segoe UI", 9, "bold"))
        self.prof_status.pack(side="left")
        ttk.Separator(sb, orient="vertical").pack(side="left", fill="y", pady=3)
        self.hint = tk.Label(sb, text="Готово.", anchor="w", bg="#e5e7eb", padx=8, pady=4)
        self.hint.pack(side="left", fill="x", expand=True)
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        names = ("  Карта кнопок  ", "  Главная  ", "  Оси и РУД  ", "  Отклик ручки  ",
                 "  Назначение (как в игре)  ", "  Режимы и автопрофиль  ", "  Обзор (голова / X52)  ",
                 "  Установка  ")
        tabs = [ttk.Frame(self.nb) for _ in names]
        for t, n in zip(tabs, names):
            self.nb.add(t, text=n)
        (self.T_RS, self.T_MAIN, self.T_AXES, self.T_RESP, self.T_ASSIGN, self.T_MODES, self.T_VIEW,
         self.T_SETUP) = range(8)
        self.tab_setup = tabs[self.T_SETUP]
        self.tab_assign = tabs[self.T_ASSIGN]
        self.head_en_var = tk.BooleanVar()   # одна галочка на двух вкладках
        self.KeyDialogClass = KeyDialog
        self._build_main(tabs[self.T_MAIN])
        self._build_axes(tabs[self.T_AXES])
        self._build_response(tabs[self.T_RESP])
        self._build_buttons(tabs[self.T_ASSIGN])
        self._build_modes(tabs[self.T_MODES])
        self._build_view(tabs[self.T_VIEW])
        self._build_setup(tabs[self.T_SETUP])
        self.rs = x52_rsview.RsView(tabs[self.T_RS], self)   # вид «как RS Mapper» — первая вкладка

        self.bind("<Escape>", lambda e: self.cancel_learn())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.sync_widgets_from_cfg()
        self._building = False
        if not os.path.exists(profile_path(self.cfg["profile_name"])):
            try:   # первый запуск 3.3: текущие настройки становятся профилем «ACE COMBAT 8»
                write_json_atomic(profile_path(self.cfg["profile_name"]), self.cfg)
            except OSError as e:
                log_error(f"Не удалось создать файл профиля: {e}")
        self.refresh_profiles()
        self._restart_listener()
        # окно оверлея создаётся сразу (пока игра не запущена): новое окно во время игры
        # могло бы отнять у неё фокус. Невидимо, пока не нужно.
        try:
            self.overlay = GameOverlay(self)
        except tk.TclError as e:
            log_error(f"Оверлей недоступен: {e}")
        if self.glob["overlay"]["enabled"] and self.glob["overlay"]["mode"] == "always":
            self.after(300, lambda: self.overlay_update(changed=True))
        self.nb.select(self.T_RS)
        self.after(50, self.tick)
        self._status_job = self.after(600, self.refresh_setup_status)
        if self.glob["joycpl"]:
            self.start_joycpl()

    # ------------------------------------------------------------ конфиг
    def _load_config(self, path, silent=False):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:  # noqa
            if silent:
                try:
                    shutil.copyfile(path, path + ".broken")
                except OSError:
                    pass
                log_error(f"Повреждённый конфиг {path}: {e}")
            else:
                messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")
            return None
        return sanitize_config(data)

    def _replace_cfg(self, new_cfg):
        self._ms_shared_apply(new_cfg)
        self._zoom_shared_apply(new_cfg)
        self.cfg = new_cfg
        self.wheel_buttons_to_layers()
        self.worker.cfg = new_cfg
        self.worker.send("restart")
        # джойстик заново открываем, только если в новом профиле выбран ДРУГОЙ или его сейчас нет:
        # повторное открытие на миг «роняет» ручку/РУД и теряет уже зажатую кнопку колеса режимов
        cur, want = self.worker.state.get("name"), new_cfg.get("device_name")
        if not cur or (want and want != cur):
            self.worker.send("scan")
        self.sync_widgets_from_cfg()
        self.mark_dirty()

    # ---- мини-стик и зум: настройки в каждом профиле, общий только список профилей, где они включены
    def _ms_shared_init(self):
        sh = self.glob.get("ministick")
        if sh is None:
            profs = [n for n in list_profiles() if self._profile_flag(n, "ministick")]
            if self.cfg["ministick"]["enabled"] and self.cfg["profile_name"] not in profs:
                profs.append(self.cfg["profile_name"])
            self.glob["ministick"] = {"profiles": profs}
            self.save_global()
        elif "settings" in sh:              # до 5.5.27 настройки были общими: раздать их всем профилям
            self._migrate_shared(lambda c: (c["ministick"].update(json.loads(json.dumps(sh["settings"]))),
                                            c["camera"].update(sh["camera"])))
            self.glob["ministick"] = {"profiles": sh["profiles"]}
            self.save_global()

    def _profile_flag(self, name, key):
        try:
            with open(profile_path(name), encoding="utf-8") as f:
                return sanitize_config(json.load(f))[key]["enabled"]
        except Exception:  # noqa
            return False

    def _migrate_shared(self, fill):
        """Записать бывшие общие настройки в каждый профиль (и в текущий), чтобы после обновления ничего
        не поменялось."""
        for n in list_profiles():
            try:
                with open(profile_path(n), encoding="utf-8") as f:
                    c = sanitize_config(json.load(f))
                fill(c)
                write_json_atomic(profile_path(n), c)
            except Exception as e:  # noqa
                log_error(f"Перенос общих настроек в профиль «{n}»: {e}")
        fill(self.cfg)

    def _ms_shared_apply(self, cfg):
        sh = self.glob.get("ministick")
        if not sh:
            return
        cfg["ministick"]["enabled"] = cfg["profile_name"] in sh["profiles"]
        if cfg["ministick"]["enabled"]:
            cfg["game"]["virtual_pad"] = True       # мини-стик идёт в игру через правый стик геймпада

    def _ms_shared_capture(self):
        sh = self.glob.get("ministick")
        if sh is None:
            return
        name = self.cfg["profile_name"]
        profs = list(sh["profiles"])
        if self.cfg["ministick"]["enabled"] and name not in profs:
            profs.append(name)
        elif not self.cfg["ministick"]["enabled"] and name in profs:
            profs.remove(name)
        if profs != sh["profiles"]:
            sh["profiles"] = profs
            self.save_global()

    def _zoom_shared_init(self):
        sh = self.glob.get("zoom")
        if sh is None:
            profs = [n for n in list_profiles() if self._profile_flag(n, "zoom")]
            if self.cfg["zoom"]["enabled"] and self.cfg["profile_name"] not in profs:
                profs.append(self.cfg["profile_name"])
            self.glob["zoom"] = {"profiles": profs}
            self.save_global()
        elif "settings" in sh:              # до 5.5.27 настройки зума были общими
            self._migrate_shared(lambda c: c["zoom"].update(sh["settings"]))
            self.glob["zoom"] = {"profiles": sh["profiles"]}
            self.save_global()

    def _zoom_shared_apply(self, cfg):
        sh = self.glob.get("zoom")
        if not sh:
            return
        cfg["zoom"]["enabled"] = cfg["profile_name"] in sh["profiles"]
        if cfg["zoom"]["enabled"]:
            cfg["game"]["virtual_pad"] = True       # зум идёт в игру через левый стик геймпада

    def _zoom_shared_capture(self):
        sh = self.glob.get("zoom")
        if sh is None:
            return
        name = self.cfg["profile_name"]
        profs = list(sh["profiles"])
        if self.cfg["zoom"]["enabled"] and name not in profs:
            profs.append(name)
        elif not self.cfg["zoom"]["enabled"] and name in profs:
            profs.remove(name)
        if profs != sh["profiles"]:
            sh["profiles"] = profs
            self.save_global()

    def save_cfg(self, path=None):
        self._save_job = None
        self._ms_shared_capture()
        self._zoom_shared_capture()
        try:
            if path:
                write_json_atomic(path, self.cfg)
            else:
                write_json_atomic(CONFIG_PATH, self.cfg)
                write_json_atomic(profile_path(self.cfg["profile_name"]), self.cfg)
            return True
        except Exception as e:  # noqa
            self.set_hint(f"Не удалось сохранить настройки: {e}")
            return False

    def mark_dirty(self):
        if self._building:
            return
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self.save_cfg)

    def _build_menu(self):
        """Меню как у RS Mapper: Файл / Правка / Последовательности / Профиль / Справка."""
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Новый профиль…", command=self.profile_new)
        fm.add_command(label="Импорт в текущий профиль…", command=self.menu_load_profile)
        fm.add_separator()
        fm.add_command(label="Сохранить", command=lambda: self.save_cfg() and self.set_hint("Сохранено."))
        fm.add_command(label="Экспорт профиля в файл…", command=self.menu_save_profile)
        fm.add_command(label="Открыть папку профилей", command=lambda: (
            os.makedirs(profiles_dir(), exist_ok=True), self.open_path(profiles_dir())))
        fm.add_separator()
        fm.add_command(label="Сбросить профиль по умолчанию", command=self.menu_reset)
        fm.add_command(label="Открыть папку настроек", command=lambda: self.open_path(DATA_DIR))
        fm.add_command(label="Перенести настройки из старой версии…", command=self.menu_import_old)
        fm.add_command(label="Сохранить все настройки в файл…", command=self.menu_export_all)
        fm.add_command(label="Загрузить все настройки из файла…", command=self.menu_import_all)
        fm.add_separator()
        fm.add_command(label="Выход", command=self.on_close)
        m.add_cascade(label="Файл", menu=fm)
        em = tk.Menu(m, tearoff=0)
        em.add_command(label="Выбор устройства", command=lambda: (self.nb.select(self.T_RS), self.rs.dev.focus_set()))
        em.add_separator()
        em.add_command(label="Настройки (мост, запуск, приоритет)", command=lambda: self.nb.select(self.T_MAIN))
        em.add_command(label="Оси и РУД", command=lambda: self.nb.select(self.T_AXES))
        em.add_command(label="Слои, долгое нажатие, оверлей, автопрофиль", command=lambda: self.nb.select(self.T_MODES))
        m.add_cascade(label="Правка", menu=em)
        sm = tk.Menu(m, tearoff=0)
        sm.add_command(label="Просмотр последовательностей…", command=lambda: self.rs.open_sequences())
        m.add_cascade(label="Последовательности", menu=sm)
        self.profile_menu = tk.Menu(m, tearoff=0, postcommand=self._fill_profile_menu)
        m.add_cascade(label="Профиль", menu=self.profile_menu)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="Быстрая справка", command=self.menu_help)
        hm.add_command(label="О программе", command=lambda: messagebox.showinfo(
            "О программе", f"{APP_NAME} {APP_VERSION}\nSaitek/Logitech X52 → виртуальный Xbox 360 + клавиатура.\n"
                           f"Вид «Карта кнопок» сделан по образцу RS Mapper (Rafal «Avantar» Szul).\n"
                           f"Программа: {APP_DIR}\nНастройки: {DATA_DIR}"))
        m.add_cascade(label="Справка", menu=hm)
        self.config(menu=m)
        self.prof_menu_var = tk.StringVar()

    def _fill_profile_menu(self):
        pm = self.profile_menu
        pm.delete(0, "end")
        pm.add_command(label="Новый профиль…", command=self.profile_new)
        if hasattr(self, "ov_en"):
            pm.add_checkbutton(label="Показывать оверлей", variable=self.ov_en, command=self.on_overlay)
        pm.add_separator()
        self.prof_menu_var.set(self.cfg["profile_name"])
        for n in self._all_profile_names():
            pm.add_radiobutton(label=n, value=n, variable=self.prof_menu_var,
                               command=lambda nn=n: self.switch_profile(nn))
        pm.add_separator()
        pm.add_command(label="Переименовать текущий…", command=self.profile_rename)
        pm.add_command(label="Удалить текущий", command=self.profile_delete)

    def menu_save_profile(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", initialdir=DATA_DIR,
                                         filetypes=[("Профиль", "*.json")], initialfile="x52_profile.json")
        if p and self.save_cfg(p):
            self.set_hint(f"Профиль сохранён: {p}")

    def menu_load_profile(self):
        p = filedialog.askopenfilename(initialdir=DATA_DIR, filetypes=[("Профиль", "*.json")])
        if p:
            self.load_profile(p)

    def menu_import_old(self):
        """Папка старой версии (с x52_config.json) -> настройки и профили сюда; затем перезапуск."""
        src = filedialog.askdirectory(title="Папка старой версии лаунчера (где лежит x52_config.json)")
        if not src:
            return
        if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(DATA_DIR)):
            messagebox.showinfo("Перенос настроек", "Это и есть текущая папка настроек.")
            return
        if not os.path.isfile(os.path.join(src, "x52_config.json")):
            messagebox.showerror("Перенос настроек", f"В папке нет x52_config.json:\n{src}")
            return
        if not messagebox.askyesno("Перенос настроек",
                                   "Текущие настройки и профили будут заменены настройками из\n"
                                   f"{src}\n\nЛаунчер закроется — запустите его снова. Продолжить?"):
            return
        try:
            for name in ("x52_config.json", "x52_global.json"):
                if os.path.isfile(os.path.join(src, name)):
                    shutil.copy2(os.path.join(src, name), os.path.join(DATA_DIR, name))
            if os.path.isdir(os.path.join(src, "profiles")):
                shutil.copytree(os.path.join(src, "profiles"), profiles_dir(), dirs_exist_ok=True)
        except OSError as e:
            messagebox.showerror("Перенос настроек", f"Не удалось скопировать: {e}")
            return
        self._skip_save = True          # не затирать перенесённое текущими настройками при закрытии
        self.on_close()

    def menu_export_all(self):
        """Профили + общие настройки (мини-стик, зум, галочки, мост, колесо…) одним файлом."""
        path = filedialog.asksaveasfilename(
            title="Сохранить все настройки", defaultextension=".zip",
            initialfile="X52_Launcher_настройки_" + time.strftime("%Y-%m-%d") + ".zip",
            filetypes=[("Архив настроек", "*.zip")])
        if not path:
            return
        self.save_cfg()
        self.save_global()
        try:
            n = export_all_settings(path)
        except OSError as e:
            messagebox.showerror("Сохранение настроек", f"Не удалось сохранить:\n{e}")
            return
        messagebox.showinfo("Сохранение настроек", f"Сохранено: профилей — {n}, плюс общие настройки.\n{path}\n\n"
                                                   "В новой версии: «Файл → Загрузить все настройки из файла…».")

    def menu_import_all(self):
        path = filedialog.askopenfilename(title="Загрузить все настройки",
                                          filetypes=[("Архив настроек", "*.zip"), ("Все файлы", "*.*")])
        if not path:
            return
        if not messagebox.askyesno("Загрузка настроек",
                                   "Общие настройки и профили с теми же именами будут заменены настройками "
                                   "из файла. Лаунчер закроется — запустите его снова. Продолжить?"):
            return
        try:
            n = import_all_settings(path)
        except (ValueError, OSError) as e:
            messagebox.showerror("Загрузка настроек", f"Не удалось загрузить:\n{e}")
            return
        messagebox.showinfo("Загрузка настроек", f"Загружено профилей: {n}. Запустите лаунчер снова.")
        self._skip_save = True          # не затирать загруженное текущими настройками при закрытии
        self.on_close()

    def load_profile(self, p):
        """Импорт настроек из файла В ТЕКУЩИЙ профиль (имя профиля сохраняется)."""
        cfg = self._load_config(p)
        if cfg is not None:
            cfg["profile_name"] = self.cfg["profile_name"]
            self._replace_cfg(cfg)
            self.set_hint(f"Профиль загружен: {p}")
            return True
        return False

    def menu_reset(self):
        if messagebox.askyesno("Сброс", "Сбросить ВСЕ настройки текущего профиля по умолчанию?"):
            tmpl = "ac8" if self.cfg["game"]["builtin_actions"] else "custom"
            self._replace_cfg(new_profile_config(self.cfg["profile_name"], tmpl, self.cfg))

    def menu_help(self):
        messagebox.showinfo(
            "Быстрая справка",
            "1. «Установка»: всё должно быть зелёным (драйвер ViGEmBus обязателен).\n"
            "2. «Оси и РУД»: «Определить» для каждой оси, затем калибровка РУД.\n"
            "3. «Отклик ручки»: если самолёт реагирует вяло — «Быстро» или подстройте "
            "компенсацию мёртвой зоны и чувствительность; рыскание — порог и режим.\n"
            "4. «Назначение»: выберите действие → «Назначить основную/дополнительную» → нажмите "
            "кнопку/хатку X52 или отклоните ось. Выход — геймпад или клавиша (как в игре).\n"
            "5. «Обзор»: галочка opentrack — обзор головой; без неё — кнопками X52 "
            "(«как стик» или «как мышь» с кнопкой центровки).\n"
            "6. «Главная» → «Играть»: запустится мост, opentrack (если включён) и игра.\n"
            "7. В игре: режим управления Expert; Steam Input для игры выключить. Клавиши в "
            "лаунчере должны совпадать с «Назначением клавиш» игры.\n\n"
            "Во время игры окно лаунчера должно оставаться открытым (можно свернуть).")

    # ------------------------------------------------------------ вкладка «Главная»
    def _build_main(self, tab):
        pf = ttk.LabelFrame(tab, text="Игра (профиль настроек)")
        pf.pack(fill="x", padx=8, pady=(6, 0))
        p1 = ttk.Frame(pf)
        p1.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(p1, text="Профиль:").pack(side="left")
        self.prof_combo = ttk.Combobox(p1, state="readonly", width=32)
        self.prof_combo.pack(side="left", padx=6)
        self.prof_combo.bind("<<ComboboxSelected>>", lambda e: self.switch_profile(self.prof_combo.get()))
        ttk.Button(p1, text="Новый…", command=self.profile_new).pack(side="left", padx=2)
        ttk.Button(p1, text="Переименовать…", command=self.profile_rename).pack(side="left", padx=2)
        ttk.Button(p1, text="Удалить", command=self.profile_delete).pack(side="left", padx=2)
        p0 = ttk.Frame(pf)
        p0.pack(fill="x", padx=8, pady=(0, 2))
        self.pad_var = tk.BooleanVar()
        ttk.Checkbutton(p0, text="Виртуальный геймпад Xbox 360 (для ACE COMBAT; для War Thunder и др. — "
                                 "выключить: игра сама видит X52)", variable=self.pad_var,
                        command=self.on_pad_toggle).pack(side="left")
        self.builtin_var = tk.BooleanVar()
        ttk.Checkbutton(p0, text="Действия ACE COMBAT 8", variable=self.builtin_var,
                        command=self.on_builtin_toggle).pack(side="left", padx=14)
        p2 = ttk.Frame(pf)
        p2.pack(fill="x", padx=8, pady=(2, 6))
        ttk.Label(p2, text="Кнопка «ИГРАТЬ» запускает:").pack(side="left")
        self.launch_var = tk.StringVar(value="steam")
        ttk.Radiobutton(p2, text="Steam, App ID", variable=self.launch_var, value="steam",
                        command=self.on_launch_type).pack(side="left", padx=(8, 2))
        self.appid_var = tk.StringVar()
        ttk.Entry(p2, textvariable=self.appid_var, width=10).pack(side="left")
        self.appid_var.trace_add("write", lambda *a: self.on_appid())
        ttk.Radiobutton(p2, text="Программу", variable=self.launch_var, value="exe",
                        command=self.on_launch_type).pack(side="left", padx=(14, 2))
        self.exe_var = tk.StringVar()
        ttk.Entry(p2, textvariable=self.exe_var, width=30).pack(side="left")
        self.exe_var.trace_add("write", lambda *a: self.on_exe_path())
        ttk.Button(p2, text="Обзор…", command=self.browse_exe).pack(side="left", padx=2)
        ttk.Radiobutton(p2, text="Ничего (только мост)", variable=self.launch_var, value="none",
                        command=self.on_launch_type).pack(side="left", padx=(14, 2))

        top = ttk.LabelFrame(tab, text="Устройство, мост и запуск игры")
        top.pack(fill="x", padx=8, pady=6)
        r1 = ttk.Frame(top)
        r1.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(r1, text="Джойстик:").pack(side="left")
        self.dev_combo = ttk.Combobox(r1, state="readonly", width=46)
        self.dev_combo.pack(side="left", padx=6)
        self.dev_combo.bind("<<ComboboxSelected>>", self.on_device_selected)
        ttk.Button(r1, text="Обновить", command=self.rescan).pack(side="left")

        r2 = ttk.Frame(top)
        r2.pack(fill="x", padx=8, pady=4)
        self.play_btn = ttk.Button(r2, text="▶▶  ИГРАТЬ", style="Play.TButton", command=self.play_game, width=16)
        self.play_btn.pack(side="left")
        self.start_btn = ttk.Button(r2, text="▶  Запустить мост", style="Big.TButton",
                                    command=self.toggle_bridge, width=20)
        self.start_btn.pack(side="left", padx=8)
        self.status_lbl = ttk.Label(r2, text="", style="Status.TLabel")
        self.status_lbl.pack(side="left", padx=8)

        r3 = ttk.Frame(top)
        r3.pack(fill="x", padx=8, pady=(4, 8))
        ttk.Checkbutton(r3, text="Обзор головой через opentrack", variable=self.head_en_var,
                        style="Head.TCheckbutton", command=self.on_head_toggle).pack(side="left")
        self.autostart_var = tk.BooleanVar()
        ttk.Checkbutton(r3, text="Включать мост при открытии лаунчера", variable=self.autostart_var,
                        command=self.on_autostart
                        ).pack(side="left", padx=16)
        self.min_var = tk.BooleanVar()
        ttk.Checkbutton(r3, text="Сворачивать лаунчер при запуске игры", variable=self.min_var,
                        command=lambda: self.on_launcher_var("minimize_on_play", self.min_var.get())
                        ).pack(side="left")
        self.prio_var = tk.BooleanVar()
        ttk.Checkbutton(r3, text="Отдавать приоритет игре", variable=self.prio_var,
                        command=self.on_priority).pack(side="left", padx=16)
        self.conflict_lbl = ttk.Label(top, text="", foreground="#b91c1c")
        self.conflict_lbl.pack(anchor="w", padx=8)

        mid = ttk.Frame(tab)
        mid.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        left = ttk.LabelFrame(mid, text="Физический X52 (в реальном времени)")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.raw_axes_frame = ttk.Frame(left)
        self.raw_axes_frame.pack(fill="x", padx=8, pady=6)
        self.raw_axis_bars = []
        ttk.Label(left, text="Кнопки (подсвечиваются при нажатии):").pack(anchor="w", padx=8)
        self.raw_buttons_frame = tk.Frame(left)
        self.raw_buttons_frame.pack(fill="x", padx=8, pady=4)
        self.raw_btn_labels = []
        self.raw_btn_state = []
        self.hats_lbl = ttk.Label(left, text="Хатки: —")
        self.hats_lbl.pack(anchor="w", padx=8, pady=(2, 8))

        right = ttk.LabelFrame(mid, text="Что видит игра (виртуальный Xbox 360)")
        right.pack(side="left", fill="y")
        sticks = ttk.Frame(right)
        sticks.pack(padx=10, pady=8)
        c1 = ttk.Frame(sticks)
        c1.pack(side="left", padx=6)
        ttk.Label(c1, text="Левый стик").pack()
        self.lstick = StickView(c1)
        self.lstick.pack()
        c2 = ttk.Frame(sticks)
        c2.pack(side="left", padx=6)
        ttk.Label(c2, text="Правый стик (обзор)").pack()
        self.rstick = StickView(c2)
        self.rstick.pack()
        self.cam_src_lbl = ttk.Label(right, text="", foreground="#555")
        self.cam_src_lbl.pack()
        trig = ttk.Frame(right)
        trig.pack(padx=10, pady=4)
        ttk.Label(trig, text="LT (тормоз)").grid(row=0, column=0, sticky="w")
        self.lt_bar = AxisBar(trig, width=170, bipolar=False, color="#ef4444")
        self.lt_bar.grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(trig, text="RT (газ)").grid(row=1, column=0, sticky="w")
        self.rt_bar = AxisBar(trig, width=170, bipolar=False, color="#22c55e")
        self.rt_bar.grid(row=1, column=1, padx=6, pady=2)
        ttk.Label(right, text="Нажато:").pack(anchor="w", padx=10, pady=(8, 0))
        self.pressed_lbl = ttk.Label(right, text="—", wraplength=250, justify="left")
        self.pressed_lbl.pack(anchor="w", padx=10, pady=(0, 4))
        self.send_lbl = ttk.Label(right, text="", foreground="#555", wraplength=250, justify="left")
        self.send_lbl.pack(anchor="w", padx=10, pady=(0, 10))

    def _rebuild_raw_axes(self, n):
        for w in self.raw_axes_frame.winfo_children():
            w.destroy()
        self.raw_axis_bars = []
        for i in range(n):
            ttk.Label(self.raw_axes_frame, text=f"Ось {i + 1}").grid(row=i // 2, column=(i % 2) * 2,
                                                                    sticky="w", padx=(0, 4))
            bar = AxisBar(self.raw_axes_frame, width=150, height=14)
            bar.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=(0, 14), pady=1)
            self.raw_axis_bars.append(bar)

    def _rebuild_raw_buttons(self, n):
        for w in self.raw_buttons_frame.winfo_children():
            w.destroy()
        self.raw_btn_labels = []
        self.raw_btn_state = [False] * n
        for i in range(n):
            lb = tk.Label(self.raw_buttons_frame, text=str(i + 1), width=3, relief="groove",
                          bg="#eeeeee", font=("Segoe UI", 8))
            lb.grid(row=i // 16, column=i % 16, padx=1, pady=1)
            self.raw_btn_labels.append(lb)

    # ------------------------------------------------------------ вкладка «Оси и РУД»
    def _build_axes(self, tab):
        right = ttk.Frame(tab)
        right.pack(side="right", fill="y", padx=(0, 8), pady=6)
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        roles = ttk.LabelFrame(left, text="Назначение осей")
        roles.pack(fill="x")
        self.axis_combo, self.axis_bar, self.inv_var, self.axen_var = {}, {}, {}, {}
        for r, (role, label) in enumerate(AXIS_ROLES):
            ev = tk.BooleanVar(value=True)
            ttk.Checkbutton(roles, text=label, variable=ev, width=31,
                            command=lambda k=role: self.on_axis_enable(k)).grid(row=r, column=0, sticky="w",
                                                                                padx=8, pady=3)
            self.axen_var[role] = ev
            cb = ttk.Combobox(roles, state="readonly", width=5, values=["—"])
            cb.grid(row=r, column=1, padx=4)
            cb.bind("<<ComboboxSelected>>", lambda e, k=role: self.on_axis_selected(k))
            self.axis_combo[role] = cb
            ttk.Button(roles, text="Определить", width=10,
                       command=lambda k=role: self.learn_axis(k)).grid(row=r, column=2, padx=4)
            if role != "throttle":
                v = tk.BooleanVar(value=False)
                ttk.Checkbutton(roles, text="Инверсия", variable=v,
                                command=lambda k=role: self.on_invert(k)).grid(row=r, column=3, padx=4)
                self.inv_var[role] = v
            else:
                ttk.Label(roles, text="(авто)", foreground="#777").grid(row=r, column=3, padx=4)
            bar = AxisBar(roles, width=96, height=14)
            bar.grid(row=r, column=4, padx=(4, 8))
            self.axis_bar[role] = bar

        ttk.Label(roles, foreground="#555", wraplength=560, justify="left", text=(
            "Галочка снята — ось НЕ работает как ручка/РУД/рыскание (в игру как стик или триггер не уходит), "
            "но её номер запоминается. Так ось можно назначить на клавиши («Назначение» → привязка «Ось …») "
            "без двойного срабатывания.")).grid(row=len(AXIS_ROLES), column=0, columnspan=5, sticky="w",
                                                padx=8, pady=(2, 6))

        sl = ttk.LabelFrame(left, text="Прочее")
        sl.pack(fill="x", pady=(8, 0))
        self.scales = {}
        ttk.Label(sl, text="Мёртвая зона мини-стика", width=26).grid(row=0, column=0, sticky="w", padx=8, pady=2)
        sc = tk.Scale(sl, from_=0.0, to=0.40, resolution=0.01, orient="horizontal", length=240,
                      command=lambda v: self.on_scale("cam_deadzone", v))
        sc.grid(row=0, column=1, padx=4)
        self.scales["cam_deadzone"] = sc
        ttk.Label(sl, text="Мини-стик X52 (включение, чувствительность, инверсия) — "
                            "раздел «Карта кнопок» → вкладка «Мини-стик».",
                  foreground="#555", wraplength=560, justify="left"
                  ).grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(sl, text="Частота опроса, Гц", width=26).grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.poll_var = tk.StringVar(value="250")
        sp = ttk.Spinbox(sl, from_=60, to=1000, increment=50, width=7, textvariable=self.poll_var,
                         command=self.on_poll)
        sp.grid(row=1, column=1, sticky="w", padx=4)
        sp.bind("<FocusOut>", lambda e: self.on_poll())
        sp.bind("<Return>", lambda e: self.on_poll())
        self.hz_lbl = ttk.Label(sl, text="", foreground="#555")
        self.hz_lbl.grid(row=1, column=2, sticky="w", padx=6)
        ttk.Label(sl, text="Макс. обновлений в игру, в секунду", width=30).grid(row=3, column=0, sticky="w",
                                                                              padx=8, pady=2)
        sc = tk.Scale(sl, from_=30, to=500, resolution=5, orient="horizontal", length=240,
                      command=lambda v: self.on_output("max_hz", int(float(v))))
        sc.grid(row=3, column=1, padx=4)
        self.out_scales = {"max_hz": sc}
        ttk.Label(sl, text="меньше — легче для игры (125 хватает)", foreground="#555").grid(
            row=3, column=2, sticky="w", padx=6)
        ttk.Label(sl, text="Фильтр дрожания осей", width=30).grid(row=4, column=0, sticky="w", padx=8, pady=2)
        sc = tk.Scale(sl, from_=0.0, to=0.05, resolution=0.002, orient="horizontal", length=240,
                      command=lambda v: self.on_output("deadband", float(v)))
        sc.grid(row=4, column=1, padx=4)
        self.out_scales["deadband"] = sc
        ttk.Label(sl, text="0 = выкл.; 0.01 — шум X52 не уходит в игру", foreground="#555").grid(
            row=4, column=2, sticky="w", padx=6)
        ttk.Label(sl, wraplength=560, justify="left", foreground="#555", text=(
            "Чувствительность, кривая, задержка ручки и рыскания — на вкладке «Отклик ручки». "
            "Любую ось можно также назначить как кнопку на вкладке «Назначение».")
            ).grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))

        cal = ttk.LabelFrame(right, text="Калибровка РУД")
        cal.pack(fill="y")
        ttk.Label(cal, wraplength=330, justify="left", foreground="#444",
                  text="Газ — это RT, торможение — LT, нейтраль — ни то ни другое. "
                       "Ось РУД должна быть назначена слева. Поставьте РУД в нужное положение "
                       "и нажмите «Записать».").pack(padx=8, pady=(8, 4), anchor="w")
        self.cal_val = {}
        grid = ttk.Frame(cal)
        grid.pack(padx=8, pady=4, fill="x")
        for r, (key, label) in enumerate(CAL_ROWS):
            ttk.Label(grid, text=label, width=26).grid(row=r, column=0, sticky="w", pady=3)
            v = ttk.Label(grid, text="", width=8)
            v.grid(row=r, column=1)
            self.cal_val[key] = v
            ttk.Button(grid, text="Записать", width=10,
                       command=lambda k=key: self.record_cal(k)).grid(row=r, column=2, padx=4)
        ttk.Button(cal, text="Сбросить калибровку", command=self.reset_cal).pack(padx=8, pady=4, anchor="w")
        self.cal_state = ttk.Label(cal, text="", wraplength=330, justify="left")
        self.cal_state.pack(padx=8, pady=2, anchor="w")
        live = ttk.LabelFrame(cal, text="Проверка")
        live.pack(fill="x", padx=8, pady=8)
        ttk.Label(live, text="Ось РУД").grid(row=0, column=0, sticky="w", padx=6)
        self.cal_raw_bar = AxisBar(live, width=190)
        self.cal_raw_bar.grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(live, text="LT (тормоз)").grid(row=1, column=0, sticky="w", padx=6)
        self.cal_lt_bar = AxisBar(live, width=190, bipolar=False, color="#ef4444")
        self.cal_lt_bar.grid(row=1, column=1, padx=6, pady=2)
        ttk.Label(live, text="RT (газ)").grid(row=2, column=0, sticky="w", padx=6)
        self.cal_rt_bar = AxisBar(live, width=190, bipolar=False, color="#22c55e")
        self.cal_rt_bar.grid(row=2, column=1, padx=6, pady=(2, 6))

    # ------------------------------------------------------------ вкладка «Отклик ручки»
    def _build_response(self, tab):
        ttk.Label(tab, wraplength=1180, justify="left", foreground="#444", text=(
            "Если самолёт реагирует с запозданием и поворачивает вяло: увеличьте «Компенсацию мёртвой зоны игры» "
            "(игра сама не реагирует на первые ~10–25 % хода стика), затем «Чувствительность». Кривая < 1 — резче "
            "у центра, > 1 — точнее у центра. «Сглаживание» добавляет задержку: для быстрой реакции — 0. "
            "Изменения действуют сразу, в том числе во время игры.")).pack(anchor="w", padx=10, pady=(8, 2))
        pr = ttk.Frame(tab)
        pr.pack(fill="x", padx=10, pady=(2, 4))
        ttk.Label(pr, text="Готовые настройки для крена и тангажа:").pack(side="left")
        for key, label in (("smooth", "Плавно"), ("standard", "Стандарт"), ("fast", "Быстро")):
            ttk.Button(pr, text=label, command=lambda k=key: self.apply_stick_preset(k)).pack(side="left", padx=3)
        ttk.Button(pr, text="Крен → Тангаж (скопировать)", command=self.copy_roll_to_pitch).pack(side="left", padx=12)

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, padx=6)
        self.resp_scales = {"roll": {}, "pitch": {}}
        self.curve_view = {}
        self.resp_out = {}
        for role, title in (("roll", "Крен (ручка влево-вправо)"), ("pitch", "Тангаж (ручка вперёд-назад)")):
            fr = ttk.LabelFrame(body, text=title)
            fr.pack(side="left", fill="y", padx=4, pady=4)
            grid = ttk.Frame(fr)
            grid.pack(padx=6, pady=4)
            for r, (key, label, lo, hi, step) in enumerate(STICK_PARAMS):
                ttk.Label(grid, text=label, wraplength=170, justify="left").grid(row=r, column=0, sticky="w")
                sc = tk.Scale(grid, from_=lo, to=hi, resolution=step, orient="horizontal", length=170,
                              command=lambda v, ro=role, k=key: self.on_resp(ro, k, v))
                sc.grid(row=r, column=1, padx=4)
                self.resp_scales[role][key] = sc
            cv = CurveView(fr, size=150)
            cv.pack(pady=(4, 2))
            self.curve_view[role] = cv
            lb = ttk.Label(fr, text="", font=("Consolas", 9))
            lb.pack(pady=(0, 6))
            self.resp_out[role] = lb

        yf = ttk.LabelFrame(body, text="Рыскание (поворот рукояти)")
        yf.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        ttk.Label(yf, wraplength=330, justify="left", foreground="#555", text=(
            "В игре рыскание — это кнопка (LB/RB на геймпаде, Q/E на клавиатуре), его скорость задаёт игра. "
            "Лаунчер делает так, чтобы кнопка срабатывала раньше и без задержки, а в режиме импульсов — "
            "пропорционально повороту рукояти.")).pack(anchor="w", padx=8, pady=(6, 4))
        self.yaw_mode_var = tk.StringVar(value="hold")
        ttk.Radiobutton(yf, text="Удержание — нажато, пока рукоять дальше порога (быстрее всего)",
                        variable=self.yaw_mode_var, value="hold", command=self.on_yaw_mode).pack(anchor="w", padx=8)
        ttk.Radiobutton(yf, text="Импульсы — чем сильнее поворот, тем дольше нажато (точнее)",
                        variable=self.yaw_mode_var, value="pulse", command=self.on_yaw_mode).pack(anchor="w", padx=8)
        grid = ttk.Frame(yf)
        grid.pack(padx=8, pady=4, anchor="w")
        self.yaw_scales = {}
        for r, (key, label, lo, hi, step) in enumerate(YAW_PARAMS):
            ttk.Label(grid, text=label, wraplength=190, justify="left").grid(row=r, column=0, sticky="w")
            sc = tk.Scale(grid, from_=lo, to=hi, resolution=step, orient="horizontal", length=180,
                          command=lambda v, k=key: self.on_yaw(k, v))
            sc.grid(row=r, column=1, padx=4)
            self.yaw_scales[key] = sc
        live = ttk.Frame(yf)
        live.pack(padx=8, pady=6, anchor="w")
        ttk.Label(live, text="Рукоять:").grid(row=0, column=0, sticky="w")
        self.yaw_bar = AxisBar(live, width=220)
        self.yaw_bar.grid(row=0, column=1, columnspan=2, padx=6, pady=2)
        self.yaw_l_lbl = tk.Label(live, text="◀ влево", width=12, relief="groove", bg="#eeeeee")
        self.yaw_l_lbl.grid(row=1, column=1, pady=2)
        self.yaw_r_lbl = tk.Label(live, text="вправо ▶", width=12, relief="groove", bg="#eeeeee")
        self.yaw_r_lbl.grid(row=1, column=2, pady=2)
        self.yaw_out_lbl = ttk.Label(yf, text="", foreground="#555", wraplength=330, justify="left")
        self.yaw_out_lbl.pack(anchor="w", padx=8, pady=(0, 6))

    def _resp_ui_refresh(self):
        for role in ("roll", "pitch"):
            self.curve_view[role].set_params(self.cfg["response"][role])
        mode = self.cfg["response"]["yaw"]["mode"]
        for key in ("period_ms", "min_pulse_ms", "full"):
            self.yaw_scales[key].configure(state="normal" if mode == "pulse" else "disabled",
                                           fg="#000" if mode == "pulse" else "#999")
        self.yaw_out_lbl.configure(text=(
            "Выход: влево — " + output_text(self.cfg, "yaw_left").split(": ", 1)[-1] +
            ", вправо — " + output_text(self.cfg, "yaw_right").split(": ", 1)[-1] +
            " (меняется на вкладке «Назначение»)."))

    def on_resp(self, role, key, v):
        if self._building:
            return
        self.cfg["response"][role][key] = float(v)
        self.curve_view[role].set_params(self.cfg["response"][role])
        self.mark_dirty()

    def on_yaw(self, key, v):
        if self._building:
            return
        y = self.cfg["response"]["yaw"]
        y[key] = float(v)
        if key == "threshold" and y["full"] < y["threshold"] + 0.05:
            y["full"] = min(1.0, y["threshold"] + 0.05)
            self._building = True
            self.yaw_scales["full"].set(y["full"])
            self._building = False
        self.mark_dirty()

    def on_yaw_mode(self):
        if self._building:
            return
        self.cfg["response"]["yaw"]["mode"] = self.yaw_mode_var.get()
        self._resp_ui_refresh()
        self.mark_dirty()

    def apply_stick_preset(self, key):
        for role in ("roll", "pitch"):
            self.cfg["response"][role] = dict(STICK_PRESETS[key])
        self.sync_widgets_from_cfg()
        self.mark_dirty()
        self.set_hint("Отклик ручки: " + {"smooth": "плавно", "standard": "стандарт", "fast": "быстро"}[key])

    def copy_roll_to_pitch(self):
        self.cfg["response"]["pitch"] = dict(self.cfg["response"]["roll"])
        self.sync_widgets_from_cfg()
        self.mark_dirty()
        self.set_hint("Настройки крена скопированы в тангаж.")

    # ------------------------------------------------------------ вкладка «Режимы и автопрофиль»
    def _build_modes(self, tab):
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True, padx=(8, 4), pady=8)
        right = ttk.Frame(tab)
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        lf = ttk.LabelFrame(left, text="Слои по колесу режимов X52 (для «Своих действий» этого профиля)")
        lf.pack(fill="x")
        self.layers_var = tk.BooleanVar()
        ttk.Checkbutton(lf, text="Включить слои: одна кнопка X52 — разные действия в режимах 1 / 2 / 3",
                        variable=self.layers_var, command=self.on_layers_toggle).pack(anchor="w", padx=8, pady=(6, 2))
        g = ttk.Frame(lf)
        g.pack(anchor="w", padx=8, pady=2)
        self.layer_lbl = []
        for i in range(3):
            ttk.Label(g, text=f"Положение {i + 1} колеса:").grid(row=i, column=0, sticky="w", pady=2)
            lb = ttk.Label(g, text="—", width=16)
            lb.grid(row=i, column=1, sticky="w", padx=6)
            self.layer_lbl.append(lb)
            ttk.Button(g, text="Определить", command=lambda k=i: self.learn_layer(k)).grid(row=i, column=2, padx=4)
        ttk.Button(lf, text="Определить колесо автоматически…", command=self.open_wheel_wizard).pack(
            anchor="w", padx=8, pady=(2, 0))
        self.layer_now = tk.Label(lf, text="Сейчас: —", font=("Segoe UI", 12, "bold"), fg="#1d4ed8",
                                  wraplength=560, justify="left")
        self.layer_now.pack(anchor="w", padx=8, pady=(4, 0))
        self.layer_btns = ttk.Label(lf, text="", foreground="#555")
        self.layer_btns.pack(anchor="w", padx=8, pady=(0, 2))
        ttk.Label(lf, foreground="#555", wraplength=560, justify="left", text=(
            "Колесо режимов X52 — это кнопки (обычно 24, 25, 26). Чтобы указать их: поставьте колесо в "
            "положение и нажмите «Определить» у этого положения (другие кнопки не нажимайте). Кнопки колеса "
            "общие — для слоёв и для «Профиля по колесу». Слой задаётся своему действию в окне «Изменить…»: "
            "«Все» — работает в любом положении."
            )).pack(anchor="w", padx=8, pady=(0, 8))

        pf = ttk.LabelFrame(left, text="Короткое и долгое нажатие")
        pf.pack(fill="x", pady=(8, 0))
        r = ttk.Frame(pf)
        r.pack(anchor="w", padx=8, pady=6)
        ttk.Label(r, text="Долгое нажатие — дольше, мс:").pack(side="left")
        self.long_scale = tk.Scale(r, from_=150, to=3000, resolution=50, orient="horizontal", length=260,
                                   command=lambda v: self.on_long_ms(v))
        self.long_scale.pack(side="left", padx=6)
        ttk.Label(pf, foreground="#555", wraplength=560, justify="left", text=(
            "Короткое срабатывает при отпускании кнопки, если держали меньше порога; долгое — как только "
            "порог пройден (клавиша держится, пока держите кнопку). Тип срабатывания и последовательности "
            "задаются в «Назначение» → «Своё действие» → «Добавить…» / «Изменить…».")
            ).pack(anchor="w", padx=8, pady=(0, 8))

        of = ttk.LabelFrame(left, text="Оверлей в игре: название активного профиля")
        of.pack(fill="x", pady=(8, 0))
        o = self.glob["overlay"]
        self.ov_en = tk.BooleanVar(value=o["enabled"])
        ttk.Checkbutton(of, text="Показывать поверх игры", variable=self.ov_en,
                        command=self.on_overlay).pack(anchor="w", padx=8, pady=(6, 2))
        r1 = ttk.Frame(of)
        r1.pack(anchor="w", padx=8, pady=2)
        self.ov_mode = tk.StringVar(value=o["mode"])
        ttk.Radiobutton(r1, text="Всегда", variable=self.ov_mode, value="always",
                        command=self.on_overlay).pack(side="left")
        ttk.Radiobutton(r1, text="При смене, секунд:", variable=self.ov_mode, value="change",
                        command=self.on_overlay).pack(side="left", padx=(10, 2))
        self.ov_sec = tk.StringVar(value=str(o["seconds"]))
        sp = ttk.Spinbox(r1, from_=1, to=30, width=4, textvariable=self.ov_sec, command=self.on_overlay)
        sp.pack(side="left")
        sp.bind("<FocusOut>", lambda e: self.on_overlay())
        ttk.Label(r1, text="   Место:").pack(side="left")
        self.ov_pos = ttk.Combobox(r1, state="readonly", width=17, values=list(OVERLAY_POS.values()))
        self.ov_pos.set(OVERLAY_POS[o["position"]])
        self.ov_pos.pack(side="left", padx=4)
        self.ov_pos.bind("<<ComboboxSelected>>", lambda e: self.on_overlay())
        r2 = ttk.Frame(of)
        r2.pack(anchor="w", padx=8, pady=2)
        ttk.Label(r2, text="Размер:").pack(side="left")
        self.ov_size = tk.StringVar(value=str(o["size"]))
        sp = ttk.Spinbox(r2, from_=10, to=72, width=4, textvariable=self.ov_size, command=self.on_overlay)
        sp.pack(side="left", padx=4)
        sp.bind("<FocusOut>", lambda e: self.on_overlay())
        ttk.Button(r2, text="Цвет…", command=self.pick_overlay_color).pack(side="left", padx=6)
        ttk.Label(r2, text="Непрозрачность:").pack(side="left")
        self.ov_op = tk.Scale(r2, from_=0.2, to=1.0, resolution=0.05, orient="horizontal", length=120,
                              command=lambda v: self.on_overlay())
        self.ov_op.set(o["opacity"])
        self.ov_op.pack(side="left")
        r3 = ttk.Frame(of)
        r3.pack(anchor="w", padx=8, pady=(2, 6))
        self.ov_layer = tk.BooleanVar(value=o["show_layer"])
        ttk.Checkbutton(r3, text="Показывать и слой колеса", variable=self.ov_layer,
                        command=self.on_overlay).pack(side="left")
        ttk.Button(r3, text="Показать для проверки", command=lambda: self.overlay_update(force=True)).pack(
            side="left", padx=10)
        ttk.Label(of, foreground="#555", wraplength=560, justify="left", text=(
            "Виден, если игра в оконном режиме или «полноэкранном без рамки» (borderless). В эксклюзивном "
            "полноэкранном режиме Windows не даёт рисовать поверх игры никакой программе. Мышь и фокус "
            "оверлей не перехватывает.")).pack(anchor="w", padx=8, pady=(0, 8))

        wf = ttk.LabelFrame(right, text="Профиль по колесу режимов X52 (общее для всех профилей)")
        wf.pack(fill="x", pady=(0, 8))
        wv = self.glob["wheel"]
        self.wheel_en = tk.BooleanVar(value=wv["enabled"])
        ttk.Checkbutton(wf, text="Поворот колеса включает профиль:", variable=self.wheel_en,
                        command=self.on_wheel).pack(anchor="w", padx=8, pady=(6, 2))
        wg = ttk.Frame(wf)
        wg.pack(anchor="w", padx=8, pady=(0, 2))
        self.wheel_combo, self.wheel_btn_lbl = [], []
        for i in range(3):
            ttk.Label(wg, text=f"Положение {i + 1}").grid(row=i, column=0, sticky="w", pady=1)
            lb = ttk.Label(wg, text="", width=11, foreground="#555")
            lb.grid(row=i, column=1, sticky="w", padx=4)
            self.wheel_btn_lbl.append(lb)
            ttk.Button(wg, text="Определить", command=lambda k=i: self.learn_wheel(k)).grid(row=i, column=2, padx=2)
            cb = ttk.Combobox(wg, state="readonly", width=26)
            cb.grid(row=i, column=3, padx=(6, 0), pady=1)
            cb.bind("<<ComboboxSelected>>", lambda e: self.on_wheel())
            self.wheel_combo.append(cb)
        wr = ttk.Frame(wf)
        wr.pack(anchor="w", padx=8)
        ttk.Button(wr, text="Определить колесо автоматически…", command=self.open_wheel_wizard).pack(side="left")
        ttk.Label(wr, foreground="#555", text="  (общие со слоями)").pack(side="left")
        self.joycpl_var = tk.BooleanVar(value=self.glob["joycpl"])
        ttk.Checkbutton(wf, variable=self.joycpl_var, command=self.on_joycpl, text=(
            "Открывать «Свойства» X52 (joy.cpl) при запуске — если колесо видно только при открытом окне"
            )).pack(anchor="w", padx=8, pady=(4, 0))
        self.wheel_now = ttk.Label(wf, text="", foreground="#1d4ed8")
        self.wheel_now.pack(anchor="w", padx=8, pady=(0, 6))

        af = ttk.LabelFrame(right, text="Автопереключение профиля")
        af.pack(fill="x")
        self.auto_var = tk.BooleanVar(value=self.glob["auto_switch"])
        ttk.Checkbutton(af, text="Автоматически включать профиль нужной игры / самолёта",
                        variable=self.auto_var, command=self.on_auto_toggle).pack(anchor="w", padx=8, pady=(6, 4))
        self.auto_title = ttk.Label(af, text="", font=("Segoe UI", 9, "bold"))
        self.auto_title.pack(anchor="w", padx=8)
        ttk.Label(af, text="Программы игры (exe, через запятую):").pack(anchor="w", padx=8, pady=(4, 0))
        row = ttk.Frame(af)
        row.pack(fill="x", padx=8)
        self.proc_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.proc_var, width=44).pack(side="left")
        self.proc_var.trace_add("write", lambda *a: self.on_auto_lists())
        ttk.Button(row, text="+ последняя игра", command=self.add_last_process).pack(side="left", padx=4)
        self.last_proc_lbl = ttk.Label(af, text="", foreground="#555")
        self.last_proc_lbl.pack(anchor="w", padx=8)
        ttk.Label(af, text="Самолёты DCS (через запятую, как их называет DCS, например F-16C_50):").pack(
            anchor="w", padx=8, pady=(6, 0))
        row = ttk.Frame(af)
        row.pack(fill="x", padx=8)
        self.air_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.air_var, width=44).pack(side="left")
        self.air_var.trace_add("write", lambda *a: self.on_auto_lists())
        ttk.Button(row, text="+ текущий самолёт", command=self.add_current_aircraft).pack(side="left", padx=4)
        self.air_lbl = ttk.Label(af, text="", foreground="#555")
        self.air_lbl.pack(anchor="w", padx=8, pady=(0, 4))
        ttk.Label(af, foreground="#555", wraplength=560, justify="left", text=(
            "Самолёт важнее программы: можно сделать профиль «DCS World» (программа DCS.exe) и отдельные "
            "профили под самолёты. Переключение — когда меняется игра или самолёт; выбранный вручную "
            "профиль не перебивается, пока вы в той же игре.")).pack(anchor="w", padx=8, pady=(0, 8))

        df = ttk.LabelFrame(right, text="DCS World: скрипт определения самолёта")
        df.pack(fill="x", pady=(8, 0))
        self.dcs_lbl = ttk.Label(df, text="", wraplength=560, justify="left")
        self.dcs_lbl.pack(anchor="w", padx=8, pady=(6, 4))
        br = ttk.Frame(df)
        br.pack(anchor="w", padx=8, pady=(0, 4))
        ttk.Button(br, text="Установить в DCS", command=self.dcs_install).pack(side="left")
        ttk.Button(br, text="Удалить из DCS", command=self.dcs_uninstall).pack(side="left", padx=4)
        ttk.Button(br, text="Открыть папку Scripts", command=self.dcs_open).pack(side="left")
        ttk.Label(df, foreground="#555", wraplength=560, justify="left", text=(
            "Добавляет одну строку в Saved Games\\DCS…\\Scripts\\Export.lua (копия старого файла — "
            "Export.lua.x52bak). SRS, Tacview, DCS-BIOS продолжают работать. Скрипт отправляет только имя "
            "вашего самолёта на этот компьютер (127.0.0.1). Некоторые серверы запрещают экспорт данных "
            "своего самолёта — тогда работает переключение по программе.")).pack(anchor="w", padx=8, pady=(0, 8))
        self._refresh_dcs_status()

    def _tick_modes(self):
        w = self.worker
        pos = self._wheel_position()
        prob = self.wheel_problem()
        self._set_text(self.wheel_now, prob or "Колесо сейчас: " + (
            f"положение {pos + 1}" if pos is not None else
            "положение не распознано — нажмите «Определить» у этого положения"),
            "#b91c1c" if prob else "#1d4ed8")
        ly = self.cfg["layers"]
        for i, lb in enumerate(self.layer_lbl):
            self._set_text(lb, binding_text(ly["buttons"][i]))
        if not ly["enabled"]:
            self._set_text(self.layer_now, "Слои выключены", )
        elif self.wheel_problem():
            self._set_text(self.layer_now, self.wheel_problem())
        elif w.mapper.layer_known or not w.state.get("name"):
            self._set_text(self.layer_now, "Сейчас: слой %d" % w.mapper.layer)
        else:
            self._set_text(self.layer_now, "Положение колеса не распознано — действует слой 1. "
                                           "Нажмите «Определить» у этого положения")
        btns = w.state.get("buttons") or []
        held = [str(i + 1) for i, v in enumerate(btns) if v]
        self._set_text(self.layer_btns, "Сейчас нажаты кнопки X52: " + (", ".join(held) if held else "—") +
                       "   (у колеса нажата одна кнопка в каждом положении)")
        self._set_text(self.last_proc_lbl, "Последняя активная игра: " + (self.last_proc or "—"))
        ac = self.listener.aircraft if self.listener else None
        if self.listener and self.listener.error:
            txt = "Приёмник DCS: " + self.listener.error
        elif not self.glob["auto_switch"]:
            txt = "DCS: автопереключение выключено"
        else:
            txt = "DCS сейчас: " + (ac or "нет данных (DCS не запущен или вы не в кабине)")
        self._set_text(self.air_lbl, txt)
        self._set_text(self.auto_title, f"Профиль «{self.cfg['profile_name']}» включается, когда:")

    # ---- профиль по колесу
    NO_PROFILE = "— не переключать —"

    def _wheel_ui_refresh(self):
        names = [self.NO_PROFILE] + self._all_profile_names()
        w = self.glob["wheel"]
        for i, cb in enumerate(self.wheel_combo):
            cb.configure(values=names)
            cb.set(w["profiles"][i] or self.NO_PROFILE)
            self.wheel_btn_lbl[i].configure(text=f"Кнопка {w['buttons'][i] + 1}")

    def on_wheel(self):
        w = self.glob["wheel"]
        w["enabled"] = bool(self.wheel_en.get())
        w["profiles"] = ["" if cb.get() == self.NO_PROFILE else cb.get() for cb in self.wheel_combo]
        self.save_global()
        self._wheel_pos = None                  # сразу применить текущее положение колеса
        if w["enabled"] and self.cfg["layers"]["enabled"]:
            self.set_hint("Внимание: колесо режимов сейчас и меняет профиль, и переключает слои этого профиля.")
        else:
            self.set_hint("Профиль по колесу режимов: " + ("включено" if w["enabled"] else "выключено"))

    def learn_wheel(self, i):
        self.detect_wheel(i)

    # ---- кнопки колеса режимов: ОДНА настройка для слоёв и для «Профиля по колесу»
    def wheel_buttons_to_layers(self):
        """Колесо физически одно: кнопки слоёв профиля = общие кнопки колеса."""
        self.cfg["layers"]["buttons"] = [{"type": "button", "index": k} for k in self.glob["wheel"]["buttons"]]

    def detect_wheel(self, i, held=None, confirm=True):
        """«Определить»: колесо уже стоит в положении i+1 — берём кнопку X52, зажатую СЕЙЧАС
        (раньше ловилось первое новое нажатие, и при повороте через среднее положение
        записывалась не та кнопка)."""
        if held is None:
            btns = self.worker.state.get("buttons") or []
            if not self.worker.state.get("name"):
                messagebox.showwarning("Колесо режимов", "X52 не найден.")
                return False
            held = [k for k, v in enumerate(btns) if v]
        if len(held) != 1:
            if not held:
                msg = (f"Сейчас не нажата ни одна кнопка X52.\n\nПоставьте колесо режимов в положение {i + 1} "
                       f"и снова нажмите «Определить». Другие кнопки при этом не нажимайте.")
            else:
                msg = (f"Сейчас нажато несколько кнопок X52: {', '.join(str(k + 1) for k in held)}.\n\n"
                       f"Отпустите все кнопки, оставьте колесо в положении {i + 1} и снова нажмите «Определить».")
            messagebox.showinfo("Колесо режимов", msg)
            return False
        k = held[0]
        wb = self.glob["wheel"]["buttons"]
        if k in wb and wb.index(k) != i and confirm:
            j = wb.index(k)
            if not messagebox.askyesno(
                    "Колесо режимов",
                    f"Сейчас зажата кнопка {k + 1} — она уже записана для положения {j + 1}.\n\n"
                    f"Колесо точно стоит в положении {i + 1}?\n\n"
                    f"«Нет» — ничего не менять: поверните колесо в положение {i + 1} и нажмите «Определить» "
                    f"ещё раз (или «Определить автоматически…»)."):
                return False
        if k in wb and wb.index(k) != i:            # эта кнопка была у другого положения — поменять местами
            wb[wb.index(k)] = wb[i]
        wb[i] = k
        self.save_global()
        self.wheel_buttons_to_layers()
        self.mark_dirty()
        self._wheel_ui_refresh()
        self._wheel_pos = None
        self.set_hint(f"Колесо режимов: положение {i + 1} = кнопка {k + 1}")
        return True

    def open_wheel_wizard(self):
        WheelWizard(self)

    def set_wheel_buttons(self, btns):
        self.glob["wheel"]["buttons"] = list(btns)
        self.save_global()
        self.wheel_buttons_to_layers()
        self.mark_dirty()
        self._wheel_ui_refresh()
        self._wheel_pos = None
        self.set_hint("Колесо режимов: " + ", ".join(f"положение {i + 1} = кнопка {k + 1}"
                                                    for i, k in enumerate(btns)))

    def wheel_problem(self):
        wb = self.glob["wheel"]["buttons"]
        if len(set(wb)) < 3:
            same = [str(i + 1) for i, k in enumerate(wb) if wb.count(k) > 1]
            return (f"⚠ У положений {' и '.join(same)} одна кнопка — нажмите «Определить колесо "
                    f"автоматически…»")
        return ""

    # ---- оверлей
    def on_overlay(self):
        if self._building:
            return
        rev = {v: k for k, v in OVERLAY_POS.items()}
        try:
            secs, size = int(float(self.ov_sec.get())), int(float(self.ov_size.get()))
        except ValueError:
            secs, size = self.glob["overlay"]["seconds"], self.glob["overlay"]["size"]
        self.glob["overlay"] = sanitize_overlay({
            "enabled": self.ov_en.get(), "mode": self.ov_mode.get(), "seconds": secs, "size": size,
            "position": rev.get(self.ov_pos.get(), "top-right"), "color": self.glob["overlay"]["color"],
            "opacity": float(self.ov_op.get()), "show_layer": self.ov_layer.get()})
        self.save_global()
        self.overlay_update(changed=True)

    def pick_overlay_color(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(color=self.glob["overlay"]["color"], parent=self, title="Цвет оверлея")
        if c and c[1]:
            self.glob["overlay"]["color"] = c[1]
            self.on_overlay()

    # ---- слои / долгое нажатие
    def on_layers_toggle(self):
        if self._building:
            return
        self.cfg["layers"]["enabled"] = bool(self.layers_var.get())
        self.mark_dirty()
        self.refresh_tree()

    def learn_layer(self, i):
        self.detect_wheel(i)

    def on_long_ms(self, v):
        if self._building:
            return
        self.cfg["long_press_ms"] = int(float(v))
        self.mark_dirty()

    # ---- автопереключение
    def save_global(self):
        try:
            write_json_atomic(global_path(), self.glob)
        except OSError as e:
            log_error(f"Не удалось сохранить x52_global.json: {e}")

    def on_joycpl(self):
        self.glob["joycpl"] = bool(self.joycpl_var.get())
        self.save_global()
        if self.glob["joycpl"]:
            self.start_joycpl()
        else:
            close_joycpl(self._joycpl_pid)
            self._joycpl_pid = None
            self.set_hint("Свойства X52 (joy.cpl) закрыты")

    def start_joycpl(self):
        if not IS_WIN:
            self.set_hint("Открытие свойств X52 доступно только в Windows")
            return

        def task(log):
            close_joycpl(self._joycpl_pid)
            for attempt in range(3):    # после включения ПК список устройств joy.cpl заполняется не сразу
                pid, msg = open_joycpl()
                if pid or getattr(self, "_closing", False):
                    break
                time.sleep(5)
            self._joycpl_pid = pid
            log(("✔ " if pid else "✖ ") + "joy.cpl: " + msg)
            if not pid:
                log_error("joy.cpl: " + msg)
        self.tasks.submit("Открытие свойств X52 (joy.cpl)", task)

    def on_auto_toggle(self):
        self.glob["auto_switch"] = bool(self.auto_var.get())
        self.save_global()
        self._auto_last = None
        self._restart_listener()
        self.set_hint("Автопереключение профиля " + ("включено" if self.glob["auto_switch"] else "выключено"))

    def _restart_listener(self):
        if self.listener:
            self.listener.stop()
            self.listener.join(1.0)
            self.listener = None
        if self.glob["auto_switch"]:
            self.listener = x52_dcs.AircraftListener(self.glob["dcs_port"])
            self.listener.start()

    def on_auto_lists(self):
        if self._building:
            return
        self.cfg["auto"] = {"processes": _norm_list(self.proc_var.get()), "aircraft": _norm_list(self.air_var.get())}
        self._rules[self.cfg["profile_name"]] = self.cfg["auto"]
        self.mark_dirty()

    def _append_entry(self, var, value):
        items = _norm_list(var.get())
        if value and value.lower() not in [x.lower() for x in items]:
            items.append(value)
            var.set(", ".join(items))

    def add_last_process(self):
        if not self.last_proc:
            messagebox.showinfo("Автопрофиль", "Сначала включите автопереключение, переключитесь в игру "
                                               "(Alt+Tab) и вернитесь сюда — лаунчер запомнит её программу.")
            return
        self._append_entry(self.proc_var, self.last_proc)

    def add_current_aircraft(self):
        ac = self.listener.aircraft if self.listener else None
        if not ac:
            messagebox.showinfo("Автопрофиль", "Нет данных от DCS. Включите автопереключение, установите "
                                               "скрипт в DCS и сядьте в кабину.")
            return
        self._append_entry(self.air_var, ac)

    def rs_other_profiles(self):
        """[(имя, cfg)] остальных профилей; файл перечитывается только после изменения."""
        cache = self.__dict__.setdefault("_other_cfgs", {})
        out = []
        for n in list_profiles():
            if n == self.cfg["profile_name"]:
                continue
            p = profile_path(n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            key = (st.st_mtime_ns, st.st_size)
            if n not in cache or cache[n][0] != key:
                cache[n] = (key, self._load_config(p, silent=True))
            if cache[n][1] is not None:
                out.append((n, cache[n][1]))
        return out

    def rs_profiles_same(self, b, layer):
        """Другие профили, где у входа X52 b назначено то же самое, что в текущем."""
        mine = x52_rsview.slot_signature(self.cfg, b, layer)
        if not mine:
            return []
        out = []
        for n in list_profiles():
            if n == self.cfg["profile_name"]:
                continue
            c = self._load_config(profile_path(n), silent=True)
            if c is not None and x52_rsview.slot_signature(c, b, layer) == mine:
                out.append(n)
        return out

    def rs_apply_to_profiles(self, b, layer, cols, to_set, to_clear):
        """Записать назначение входа b в профили to_set; в профилях to_clear — убрать его. Возвращает имена."""
        off = {"enabled": False, "special": False}
        done = []
        for n in list_profiles():
            if n == self.cfg["profile_name"] or (n not in to_set and n not in to_clear):
                continue
            c = self._load_config(profile_path(n), silent=True)
            if c is None:
                continue
            c["profile_name"] = n
            if n in to_set:
                for col in cols.values():          # последовательность по имени — скопировать, если её там нет
                    if col.get("enabled") and col.get("kind") == "seq" and col.get("seq"):
                        if col["seq"] not in [q["name"] for q in c["sequences"]]:
                            c["sequences"] += [json.loads(json.dumps(q)) for q in self.cfg["sequences"]
                                               if q["name"] == col["seq"]]
                self._copy_special_slots(c, b, layer, cols)
                x52_rsview.apply_slots(c, b, layer, cols)
            else:
                x52_rsview.apply_slots(c, b, layer, {s: dict(off) for s in x52_rsview.SLOTS})
            try:
                write_json_atomic(profile_path(n), sanitize_config(c))
                done.append(n)
            except OSError as e:
                log_error(f"Не удалось записать профиль {n}: {e}")
        return done

    def _copy_special_slots(self, c, b, layer, cols):
        """Особые колонки окна (смена профиля «по кругу», шаги внутри действия) окно не описывает целиком —
        копируем само действие текущего профиля в профиль c (apply_slots такие колонки не трогает)."""
        src = x52_rsview.find_slots(self.cfg, b, layer)
        dst = x52_rsview.find_slots(c, b, layer)
        for slot, col in cols.items():
            if not (col.get("enabled") and col.get("special")) or slot not in src:
                continue
            fields = {k: json.loads(json.dumps(src[slot][k])) for k in
                      ("name", "keys", "mode", "trigger", "repeat_ms", "seq", "profile", "steps", "cam")
                      if k in src[slot]}
            ca = dst.get(slot)
            if ca is None:
                ca = {"id": new_custom_id(c), "layer": layer, "bindings": [dict(b), None]}
                c["custom_actions"].append(ca)
            ca.update(fields)

    def _all_profile_names(self):
        names = list_profiles()
        if self.cfg["profile_name"] not in names:
            names.append(self.cfg["profile_name"])
        return names

    def _wheel_position(self):
        """Положение колеса режимов. Если ни одна кнопка колеса сейчас не видна (Windows после
        открытия джойстика сообщает только изменения), берём последнее известное положение."""
        btns = self.worker.state.get("buttons") or []
        for i, idx in enumerate(self.glob["wheel"]["buttons"]):
            if idx < len(btns) and btns[idx]:
                if self._wheel_last != i:
                    self._wheel_last = i
                    self.glob["wheel"]["last"] = i
                    self._wheel_save_t = time.time()
                self.worker.mapper.wheel_last = i + 1
                self.worker.mapper.wheel_seen = True     # колесо видели живьём — память больше не нужна
                self._wheel_seen = True
                return i
        # до первого живого сигнала после открытия джойстика — последнее известное положение
        return None if self._wheel_seen else self._wheel_last

    def _wheel_tick(self):
        """Профиль по колесу режимов X52: положение колеса -> свой профиль (для всех профилей)."""
        w = self.glob["wheel"]
        if not w["enabled"]:
            self._wheel_pos = None
            return
        pos = self._wheel_position()
        if pos is None or pos == self._wheel_pos:
            return
        if self.learn or self.grab_current() is not None:
            return                                   # повторим, когда закроется окно
        self._wheel_pos = pos
        target = w["profiles"][pos]
        if not target:
            return
        if target not in self._all_profile_names():
            self.set_hint(f"Колесо, положение {pos + 1}: профиль «{target}» не найден")
            return
        if target != self.cfg["profile_name"] and self.switch_profile(target):
            self.set_hint(f"Колесо режимов, положение {pos + 1}: профиль «{target}»")

    def _drain_profile_events(self):
        q = self.worker.profile_q
        while True:
            try:
                ev = q.get_nowait()
            except queue.Empty:
                return
            # во время назначения кнопки и полсекунды после — не переключать: нажатие было для назначения
            if self.learn or self.grab_current() is not None or \
                    time.time() - self.__dict__.get("_learn_end", 0.0) < 0.5:
                continue
            self.handle_profile_event(ev)

    def handle_profile_event(self, ev):
        """«Смена профиля» кнопкой X52."""
        cur = self.cfg["profile_name"]
        allp = self._all_profile_names()
        kind = ev.get("kind")
        names = [n for n in ev.get("names", []) if n in allp]
        target = None
        if kind == "name":
            target = names[0] if names else None
        elif kind == "cycle":
            if names:
                target = names[(names.index(cur) + 1) % len(names)] if cur in names else names[0]
        elif kind in ("next", "prev") and len(allp) > 1:
            i = allp.index(cur) if cur in allp else 0
            target = allp[(i + (1 if kind == "next" else -1)) % len(allp)]
        if not target:
            missing = [n for n in ev.get("names", []) if n not in allp]
            if missing:
                self.set_hint("Смена профиля: не найден профиль «" + "», «".join(missing) + "»")
            return
        if target != cur and self.switch_profile(target):
            self.set_hint(f"Профиль (кнопкой X52): {target}")

    def overlay_text(self):
        t = self.cfg["profile_name"]
        if self.glob["overlay"]["show_layer"] and self.cfg["layers"]["enabled"]:
            m = self.worker.mapper
            t += f"  ·  слой {m.layer or 1}" if m.layer_known else "  ·  слой ?"
        return t

    def overlay_update(self, changed=True, force=False):
        o = self.glob["overlay"]
        if not o["enabled"]:
            if self.overlay:
                self.overlay.hide()
            return
        if self.overlay is None:
            return
        text = self.overlay_text()
        if o["mode"] == "always":
            self.overlay.show(text, o, sticky=True)
        elif changed or force:
            self.overlay.show(text, o, sticky=False)

    def _overlay_tick(self):
        """Смена профиля/слоя -> оверлей; раз в 3 с вернуть его поверх игры."""
        m = self.worker.mapper
        key = (self.cfg["profile_name"], (m.layer, m.layer_known) if self.cfg["layers"]["enabled"] else 0)
        if key != self._ov_key:
            first = self._ov_key is None
            self._ov_key = key
            if not first:
                self.overlay_update(changed=True)
        if self.overlay and self.overlay.alpha > 0 and time.time() - self._ov_top_t > 3:
            self._ov_top_t = time.time()
            self.overlay._topmost()

    def _load_rules(self):
        rules = {}
        for name in list_profiles():
            if name == self.cfg["profile_name"]:
                continue
            try:
                with open(profile_path(name), encoding="utf-8") as f:
                    rules[name] = sanitize_config(json.load(f))["auto"]
            except Exception:  # noqa
                continue
        rules[self.cfg["profile_name"]] = self.cfg["auto"]
        self._rules = rules

    def _auto_tick(self):
        proc = self._fg_func()     # и при выключенном автопереключении — для «+ последняя игра»
        if proc and proc.lower() not in ("python.exe", "pythonw.exe", "py.exe", "explorer.exe", SELF_EXE):
            self.last_proc = proc
        if not self.glob["auto_switch"]:
            return
        ac = self.listener.aircraft if self.listener else None
        target = choose_profile(self._rules, proc, ac)
        if not target or target == self._auto_last:
            return
        if self.learn or self.grab_current() is not None:
            return                                  # открыт диалог — не мешаем
        self._auto_last = target
        if target != self.cfg["profile_name"] and target in list_profiles():
            if self.switch_profile(target):
                self.set_hint(f"Автопрофиль: {target}" + (f" (самолёт {ac})" if ac else f" ({proc})"))

    # ---- DCS
    def _refresh_dcs_status(self):
        dirs = x52_dcs.find_dcs_dirs()
        if not dirs:
            txt = "Папка DCS в «Сохранённых играх» не найдена (запустите DCS хотя бы раз)."
        else:
            txt = "\n".join(f"{os.path.basename(d)}: " + ("✔ скрипт установлен" if x52_dcs.is_installed(d)
                                                          else "скрипт не установлен") for d in dirs)
        self.dcs_lbl.configure(text=txt)

    def dcs_install(self):
        dirs = x52_dcs.find_dcs_dirs()
        if not dirs:
            messagebox.showwarning("DCS", "Не найдена папка Saved Games\\DCS. Запустите DCS хотя бы раз.")
            return
        done = []
        for d in dirs:
            try:
                x52_dcs.install(d, self.glob["dcs_port"])
                done.append(os.path.basename(d))
            except OSError as e:
                messagebox.showerror("DCS", f"{d}:\n{e}")
        self._refresh_dcs_status()
        if done:
            if not self.glob["auto_switch"]:
                self.auto_var.set(True)
                self.on_auto_toggle()
            messagebox.showinfo("DCS", "Скрипт установлен: " + ", ".join(done) +
                                "\n\nПерезапустите DCS (если запущен) и сядьте в кабину — имя самолёта появится здесь.")

    def dcs_uninstall(self):
        dirs = x52_dcs.find_dcs_dirs()
        n = 0
        for d in dirs:
            try:
                n += bool(x52_dcs.uninstall(d))
            except OSError as e:
                messagebox.showerror("DCS", f"{d}:\n{e}")
        self._refresh_dcs_status()
        messagebox.showinfo("DCS", "Скрипт удалён." if n else "Скрипт не был установлен.")

    def dcs_open(self):
        dirs = x52_dcs.find_dcs_dirs()
        if dirs:
            p = os.path.join(dirs[0], "Scripts")
            os.makedirs(p, exist_ok=True)
            self.open_path(p)
        else:
            messagebox.showinfo("DCS", "Папка DCS не найдена.")

    # ------------------------------------------------------------ вкладка «Назначение»
    def _build_buttons(self, tab):
        ttk.Label(tab, wraplength=1180, justify="left", foreground="#444", text=(
            "Все действия игры — как в её меню «Назначение клавиш». У каждого две привязки X52: основная и "
            "дополнительная. Привязать можно кнопку, направление хатки или направление ЛЮБОЙ оси (ручка, РУД, "
            "крутилки, слайдер, мини-стик) — она сработает как кнопка при переходе порога. Выход в игру — "
            "виртуальный геймпад или клавиша клавиатуры/мыши (для шасси, обычных ракет, особого вооружения 1/2, "
            "предыдущего оружия — только клавиатура). Двойной щелчок — назначить основную. Жёлтым — одинаковые "
            "привязки. Аналоговые крен, тангаж, РУД — на вкладке «Оси и РУД». Для других игр (War Thunder и др.) "
            "создайте профиль на «Главной» и добавьте «Свои действия» с клавишами этой игры."
            )).pack(anchor="w", padx=10, pady=(8, 4))
        cols = ("primary", "secondary", "output")
        tf = ttk.Frame(tab)
        tf.pack(fill="both", expand=True, padx=10, pady=4)
        self.tree = ttk.Treeview(tf, columns=cols, show="tree headings", height=20, selectmode="browse")
        self.tree.heading("#0", text="Действие в игре")
        self.tree.heading("primary", text="Основная (X52)")
        self.tree.heading("secondary", text="Дополнительная (X52)")
        self.tree.heading("output", text="Выход в игру")
        self.tree.column("#0", width=400)
        self.tree.column("primary", width=190)
        self.tree.column("secondary", width=190)
        self.tree.column("output", width=330)
        self.tree.tag_configure("dup", background="#fff3cd")
        self.tree.tag_configure("cat", font=("Segoe UI", 9, "bold"))
        vs = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.insert("", "end", iid="cat:custom", text="Свои действия (клавиши)", open=True, tags=("cat",))
        for cat in CATEGORIES:
            self.tree.insert("", "end", iid="cat:" + cat, text=cat, open=True, tags=("cat",))
        for aid, cat, label, _p, _k, _v in ACTIONS:
            self.tree.insert("cat:" + cat, "end", iid=aid, text=label, values=("—", "—", ""))
        self.tree.bind("<Double-1>", lambda e: self.learn_binding(0))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._sync_out_controls())

        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=10, pady=(2, 2))
        ttk.Label(bar, text="X52:").pack(side="left")
        ttk.Button(bar, text="Назначить основную…", command=lambda: self.learn_binding(0)).pack(side="left", padx=3)
        ttk.Button(bar, text="Назначить дополнительную…",
                   command=lambda: self.learn_binding(1)).pack(side="left", padx=3)
        ttk.Button(bar, text="Очистить основную", command=lambda: self.clear_binding(0)).pack(side="left", padx=3)
        ttk.Button(bar, text="Очистить дополнительную",
                   command=lambda: self.clear_binding(1)).pack(side="left", padx=3)
        ttk.Button(bar, text="Порог оси…", command=self.edit_axis_threshold).pack(side="left", padx=3)
        ttk.Button(bar, text="Все по умолчанию", command=self.reset_bindings).pack(side="right")

        bar0 = ttk.Frame(tab)
        bar0.pack(fill="x", padx=10, pady=(2, 2), before=bar)
        ttk.Label(bar0, text="Своё действие (клавиша игры):").pack(side="left")
        ttk.Button(bar0, text="Добавить…", command=self.custom_add).pack(side="left", padx=3)
        ttk.Button(bar0, text="Изменить…", command=self.custom_edit).pack(side="left", padx=3)
        ttk.Button(bar0, text="Удалить", command=self.custom_delete).pack(side="left", padx=3)
        ttk.Label(bar0, foreground="#555", text="  затем «Назначить основную…» и нажмите кнопку X52"
                  ).pack(side="left")

        bar2 = ttk.Frame(tab)
        bar2.pack(fill="x", padx=10, pady=(2, 2))
        ttk.Label(bar2, text="Выход в игру:").pack(side="left")
        self.via_var = tk.StringVar(value="pad")
        self.via_pad = ttk.Radiobutton(bar2, text="Геймпад", variable=self.via_var, value="pad",
                                       command=self.on_via)
        self.via_pad.pack(side="left", padx=4)
        self.via_key = ttk.Radiobutton(bar2, text="Клавиатура / мышь", variable=self.via_var, value="key",
                                       command=self.on_via)
        self.via_key.pack(side="left", padx=4)
        self.key_btn = ttk.Button(bar2, text="Клавиша…", command=self.edit_keys)
        self.key_btn.pack(side="left", padx=6)
        self.out_info = ttk.Label(bar2, text="", foreground="#555")
        self.out_info.pack(side="left", padx=6)
        self.now_pressed = ttk.Label(tab, text="Сейчас на X52: —", foreground="#1d4ed8")
        self.now_pressed.pack(anchor="w", padx=10, pady=(0, 8))
        self._sync_out_controls()

    # ------------------------------------------------------------ вкладка «Обзор»
    def _build_view(self, tab):
        right = ttk.Frame(tab)
        right.pack(side="right", fill="y", padx=(0, 8), pady=6)
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        ot = ttk.LabelFrame(left, text="Обзор головой — opentrack")
        ot.pack(fill="x")
        r0 = ttk.Frame(ot)
        r0.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Checkbutton(r0, text="Включить обзор головой (opentrack)", variable=self.head_en_var,
                        style="Head.TCheckbutton", command=self.on_head_toggle).pack(side="left")
        self.manage_var = tk.BooleanVar()
        ttk.Checkbutton(r0, text="Запускать и закрывать opentrack вместе с галочкой", variable=self.manage_var,
                        command=lambda: self.on_head_var("manage_process", self.manage_var.get())
                        ).pack(side="left", padx=14)
        r1 = ttk.Frame(ot)
        r1.pack(fill="x", padx=8, pady=4)
        ttk.Label(r1, text="opentrack.exe:").pack(side="left")
        self.ot_path_var = tk.StringVar()
        ttk.Entry(r1, textvariable=self.ot_path_var, width=34).pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(r1, text="Обзор…", command=self.browse_opentrack).pack(side="left")
        self.ot_btn = ttk.Button(r1, text="Запустить opentrack", command=self.toggle_opentrack, width=20)
        self.ot_btn.pack(side="left", padx=(6, 0))
        self.ot_path_var.trace_add("write", lambda *a: self.on_head_var("opentrack_path", self.ot_path_var.get()))
        self.ot_status = ttk.Label(ot, text="", foreground="#555")
        self.ot_status.pack(anchor="w", padx=8)
        r3 = ttk.Frame(ot)
        r3.pack(fill="x", padx=8, pady=4)
        ttk.Label(r3, text="Порт UDP (127.0.0.1):").pack(side="left")
        self.head_port_var = tk.StringVar(value="4242")
        sp = ttk.Spinbox(r3, from_=1024, to=65535, increment=1, width=7, textvariable=self.head_port_var,
                         command=self.on_head_port)
        sp.pack(side="left", padx=4)
        sp.bind("<FocusOut>", lambda e: self.on_head_port())
        sp.bind("<Return>", lambda e: self.on_head_port())
        ttk.Label(r3, text="  ← в opentrack: Output «UDP over network», этот порт",
                  foreground="#555").pack(side="left")
        self.head_status = ttk.Label(ot, text="", wraplength=700, justify="left")
        self.head_status.pack(anchor="w", padx=8, pady=2)
        vals = ttk.Frame(ot)
        vals.pack(fill="x", padx=8, pady=2)
        self.head_vals = {}
        for i, (k, label) in enumerate((("yaw", "Поворот"), ("pitch", "Наклон"), ("roll", "Крен"),
                                        ("x", "X, см"), ("y", "Y, см"), ("z", "Z, см"))):
            ttk.Label(vals, text=label + ":").grid(row=0, column=i * 2, sticky="w", padx=(0, 2))
            lb = ttk.Label(vals, text="—", width=7, font=("Consolas", 10))
            lb.grid(row=0, column=i * 2 + 1, sticky="w", padx=(0, 10))
            self.head_vals[k] = lb

        xv = ttk.LabelFrame(left, text="Обзор кнопками X52 (когда opentrack выключен)")
        xv.pack(fill="x", pady=(8, 0))
        self.cam_mode_var = tk.StringVar(value="stick")
        ttk.Radiobutton(xv, text="Как стик — камера смотрит, пока держишь хатку/мини-стик, потом возвращается",
                        variable=self.cam_mode_var, value="stick", command=self.on_cam_mode).pack(anchor="w", padx=8, pady=(6, 0))
        ttk.Radiobutton(xv, text="Как мышь — хатка/мини-стик поворачивает камеру, и она остаётся повёрнутой;\n"
                                 "возврат в центр — кнопкой «Центровка обзора»",
                        variable=self.cam_mode_var, value="mouse", command=self.on_cam_mode).pack(anchor="w", padx=8)
        r5 = ttk.Frame(xv)
        r5.pack(fill="x", padx=8, pady=4)
        ttk.Label(r5, text="Скорость «мыши» (доля полного обзора в секунду):").pack(side="left")
        self.cam_speed = tk.Scale(r5, from_=0.2, to=6.0, resolution=0.1, orient="horizontal", length=220,
                                  command=lambda v: self.on_cam_speed(v))
        self.cam_speed.pack(side="left", padx=6)
        r7 = ttk.Frame(xv)
        r7.pack(fill="x", padx=8, pady=2)
        ttk.Label(r7, text="Скорость поворота «как стик» (0 = мгновенно):").pack(side="left")
        self.cam_stick_speed = tk.Scale(r7, from_=0.0, to=10.0, resolution=0.1, orient="horizontal", length=220,
                                        command=lambda v: self.on_cam_val("stick_speed", v))
        self.cam_stick_speed.pack(side="left", padx=6)
        ttk.Label(r7, text="меньше — плавнее", foreground="#555").pack(side="left")
        r8 = ttk.Frame(xv)
        r8.pack(fill="x", padx=8, pady=2)
        ttk.Label(r8, text="Насколько далеко поворачивается обзор X52:").pack(side="left")
        self.cam_max = tk.Scale(r8, from_=0.2, to=1.0, resolution=0.05, orient="horizontal", length=220,
                                command=lambda v: self.on_cam_val("max", v))
        self.cam_max.pack(side="left", padx=6)
        ttk.Label(r8, text="1.0 = полностью", foreground="#555").pack(side="left")
        ttk.Label(xv, wraplength=700, justify="left", foreground="#555", text=(
            "Хатки/кнопки обзора и «Центровка обзора» назначаются на вкладке «Кнопки» (группа «Обзор»), "
            "мини-стик — на вкладке «Карта кнопок» → «Мини-стик».Кнопка «Центровка обзора» работает в обоих режимах: с "
            "opentrack она делает текущее положение головы «прямо». Кнопка «Вкл/выкл обзор головой» "
            "переключает эту галочку прямо из игры.")).pack(anchor="w", padx=8, pady=(0, 6))
        r6 = ttk.Frame(xv)
        r6.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(r6, text="Центровать обзор сейчас", command=lambda: self.worker.send("center")).pack(side="left")
        self.center_lbl = ttk.Label(r6, text="", foreground="#555")
        self.center_lbl.pack(side="left", padx=8)

        st = ttk.LabelFrame(right, text="Отклик на голову")
        st.pack(fill="x")
        self.head_scales = {}
        for r, (key, label, lo, hi, step) in enumerate(HEAD_SCALES):
            ttk.Label(st, text=label, wraplength=190, justify="left").grid(row=r, column=0, sticky="w",
                                                                          padx=8, pady=1)
            sc = tk.Scale(st, from_=lo, to=hi, resolution=step, orient="horizontal", length=170,
                          command=lambda v, k=key: self.on_head_var(k, float(v)))
            sc.grid(row=r, column=1, padx=4)
            self.head_scales[key] = sc
        inv = ttk.Frame(st)
        inv.grid(row=len(HEAD_SCALES), column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self.head_inv_yaw = tk.BooleanVar()
        self.head_inv_pitch = tk.BooleanVar()
        ttk.Checkbutton(inv, text="Инверсия влево/вправо", variable=self.head_inv_yaw,
                        command=lambda: self.on_head_var("invert_yaw", self.head_inv_yaw.get())).pack(side="left")
        ttk.Checkbutton(inv, text="Инверсия вверх/вниз", variable=self.head_inv_pitch,
                        command=lambda: self.on_head_var("invert_pitch", self.head_inv_pitch.get())
                        ).pack(side="left", padx=8)
        pv = ttk.LabelFrame(right, text="Правый стик (обзор) — итог")
        pv.pack(fill="x", pady=(6, 0))
        self.view_stick = StickView(pv, size=110)
        self.view_stick.pack(pady=6)
        self.view_src = ttk.Label(pv, text="", foreground="#555")
        self.view_src.pack(pady=(0, 2))
        ttk.Label(pv, wraplength=300, justify="left", foreground="#555", text=(
            "Точка — правый стик (обзор). Ручка полёта двигает левый стик — он на «Главной». "
            "Точка движется от кнопок/хаток «Обзор» и мини-стика, игра для этого не нужна.")
            ).pack(padx=8, pady=(0, 6))

    # ------------------------------------------------------------ вкладка «Установка»
    def _build_setup(self, tab):
        ttk.Label(tab, wraplength=1150, justify="left", foreground="#444", text=(
            "Здесь проверяется всё, что нужно для игры. Обязательны библиотеки, а драйвер ViGEmBus — для игр, "
            "которые понимают только геймпад (ACE COMBAT 8). opentrack нужен только для обзора головой. Установщики драйвера и opentrack попросят "
            "подтверждение администратора (UAC) — это нормально.")).pack(anchor="w", padx=10, pady=(8, 4))
        g = ttk.Frame(tab)
        g.pack(fill="x", padx=10, pady=4)
        self.setup_lbl = {}
        rows = [
            ("libs", "Python и библиотеки", [("Подробнее", self.show_libs_info)]),
            ("vigem", "Драйвер ViGEmBus (обязателен)", [("Проверить", self.check_driver),
                                                       ("Установить / обновить", self.install_vigem)]),
            ("ot", "opentrack (обзор головой)", [("Скачать и установить", self.install_opentrack),
                                                ("Указать путь…", self.browse_opentrack)]),
            ("shortcut", "Ярлык на рабочем столе", [("Создать", lambda: self.do_shortcut("create")),
                                                   ("Удалить", lambda: self.do_shortcut("remove"))]),
            ("conflict", "Конфликтующие программы", [("Проверить", self.refresh_setup_status)]),
        ]
        for r, (key, title, btns) in enumerate(rows):
            ttk.Label(g, text=title, width=30, font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w", pady=4)
            lb = ttk.Label(g, text="проверяю…", width=70, wraplength=520, justify="left")
            lb.grid(row=r, column=1, sticky="w", padx=6)
            self.setup_lbl[key] = lb
            bf = ttk.Frame(g)
            bf.grid(row=r, column=2, sticky="w")
            for txt, cmd in btns:
                ttk.Button(bf, text=txt, command=cmd).pack(side="left", padx=2)
        r = len(rows)
        ttk.Label(g, text="Запуск игры", width=30, font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w", pady=4)
        ttk.Label(g, text="Steam App ID или программа — на «Главной», отдельно для каждого профиля "
                          "(ACE COMBAT 8: WINGS OF THEVE = 2288340).", foreground="#555").grid(
            row=r, column=1, columnspan=2, sticky="w", padx=6)

        lf = ttk.LabelFrame(tab, text="Журнал операций")
        lf.pack(fill="both", expand=True, padx=10, pady=8)
        self.log_txt = tk.Text(lf, height=12, wrap="word", font=("Consolas", 9), state="disabled")
        sb = ttk.Scrollbar(lf, command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_txt.pack(fill="both", expand=True)
        bf = ttk.Frame(tab)
        bf.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Button(bf, text="Обновить статус", command=self.refresh_setup_status).pack(side="left")
        ttk.Button(bf, text="Открыть папку настроек", command=lambda: self.open_path(DATA_DIR)).pack(side="left", padx=6)
        ttk.Button(bf, text="Открыть журнал ошибок", command=self.open_error_log).pack(side="left")

    def log(self, text):
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", time.strftime("%H:%M:%S  ") + text + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def open_error_log(self):
        if not os.path.exists(ERROR_LOG):
            messagebox.showinfo("Журнал ошибок",
                                "Ошибок не было — журнал пуст.\n\n"
                                "Файл x52_error.log создаётся автоматически только при первой ошибке.")
            return
        self.open_path(ERROR_LOG)

    def open_path(self, p):
        if not os.path.exists(p):
            messagebox.showinfo("Нет файла", f"Не найдено:\n{p}")
            return
        try:
            if IS_WIN:
                os.startfile(p)  # noqa
            else:
                webbrowser.open("file://" + p)
        except Exception as e:  # noqa
            messagebox.showerror("Ошибка", str(e))

    def _set_setup(self, key, state, text):
        col = {True: "#15803d", False: "#b91c1c", None: "#b45309"}[state]
        mark = {True: "✔ ", False: "✖ ", None: "• "}[state]
        self.setup_lbl[key].configure(text=mark + text, foreground=col)

    def libs_status(self):
        parts = [f"Python {sys.version.split()[0]}"]
        ok = True
        try:
            parts.append(f"pygame {pygame.version.ver}")
        except Exception:  # noqa
            ok = False
        if _find_module("vgamepad") is None:
            parts.append("vgamepad НЕ установлен — " + ("переустановите программу" if FROZEN else "запустите install.bat"))
            ok = False
        else:
            parts.append("vgamepad установлен")
        return ok, ", ".join(parts)

    def show_libs_info(self):
        ok, txt = self.libs_status()
        messagebox.showinfo("Python и библиотеки", f"{txt}\n\nИнтерпретатор:\n{sys.executable}")

    def refresh_setup_status(self):
        ok, txt = self.libs_status()
        self._set_setup("libs", ok, txt)

        def task(log):
            res = {}
            if IS_WIN:
                ent = vigem_entries()
                res["vigem_reg"] = ent[0] if ent else None
                res["x360ce"] = process_running("x360ce.exe")
                res["shortcut"] = shortcut("check")
            else:
                res["vigem_reg"] = None
                res["x360ce"] = None
                res["shortcut"] = (False, "доступно только в Windows")
            if not self.worker.bridge_on and IS_WIN:
                res["selftest"] = driver_selftest()
            self._setup_result = res
        self._setup_result = None
        self.tasks.submit("Проверка компонентов", task)

    def _apply_setup_result(self, res):
        reg = res.get("vigem_reg")
        st = res.get("selftest")
        if self.worker.bridge_on:
            self._set_setup("vigem", True, "работает (мост включён)")
        elif st is not None:
            ver = f" (версия {reg['version']})" if reg and reg.get("version") else ""
            self._set_setup("vigem", st[0], ("установлен, " if st[0] else "") + st[1] + ver)
        elif not IS_WIN:
            self._set_setup("vigem", None, "проверка доступна только в Windows")
        else:
            self._set_setup("vigem", bool(reg), f"найден: {reg['name']} {reg['version']}" if reg else "не найден")
        self._refresh_ot_setup()
        ok, txt = res.get("shortcut", (False, ""))
        if not IS_WIN:
            self._set_setup("shortcut", None, txt)
        else:
            self._set_setup("shortcut", ok and txt == "yes", "есть" if txt == "yes" else "нет")
        x = res.get("x360ce")
        self.conflict = x
        if x:
            self._set_setup("conflict", False, "запущен x360ce — закройте его (два геймпада мешают друг другу)")
        elif x is None:
            self._set_setup("conflict", None, "проверка доступна только в Windows")
        else:
            self._set_setup("conflict", True, "конфликтов нет (x360ce не запущен)")

    def _refresh_ot_setup(self):
        p = self.cfg["head"]["opentrack_path"].strip().strip('"')
        if p and os.path.isfile(p):
            self._set_setup("ot", True, f"найден: {p}")
        else:
            self._set_setup("ot", None, "не найден (нужен только для обзора головой)")

    def check_driver(self):
        if self.worker.bridge_on:
            self._set_setup("vigem", True, "работает (мост включён)")
            return
        if not IS_WIN:
            self._set_setup("vigem", None, "проверка доступна только в Windows")
            return

        def task(log):
            ok, msg = driver_selftest()
            log(("✔ " if ok else "✖ ") + "ViGEmBus: " + msg)
            self._setup_result = {"selftest": (ok, msg), "vigem_reg": (vigem_entries() or [None])[0],
                                  "x360ce": process_running("x360ce.exe"), "shortcut": shortcut("check")}
        self._set_setup("vigem", None, "проверяю…")
        self.tasks.submit("Проверка драйвера ViGEmBus", task)

    def _run_installer_wait(self, path, log, msi=False):
        log("Запускаю установщик — подтвердите запрос администратора (UAC) и пройдите шаги установки…")
        if msi:
            script = "Start-Process msiexec.exe -ArgumentList @('/i', ('\"' + $env:X52_FILE + '\"')) -Wait"
        else:
            script = "Start-Process -FilePath $env:X52_FILE -Wait"
        r = run_powershell(script, {"X52_FILE": path}, timeout=3600)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "").strip() or f"код {r.returncode}")
        log("Установщик закрыт.")

    def install_vigem(self):
        if not IS_WIN:
            messagebox.showinfo("ViGEmBus", "Установка доступна только в Windows.")
            return
        if self.worker.bridge_on:
            messagebox.showinfo("ViGEmBus", "Сначала остановите мост.")
            return

        def task(log):
            try:
                url = github_latest_asset(VIGEM_REPO, r"^ViGEmBus_.*\.exe$", VIGEM_FALLBACK)
                log("Загружаю " + url)
                path = download(url, tempfile.gettempdir(), log)
                self._run_installer_wait(path, log)
            except Exception as e:  # noqa
                log(f"Загрузка с GitHub не удалась ({e}). Пробую установщик из пакета vgamepad…")
                spec = _find_module("vgamepad")
                if spec is None or not getattr(spec, "origin", None):
                    raise RuntimeError("vgamepad не установлен — " + ("переустановите программу" if FROZEN else "запустите install.bat"))
                msi = os.path.join(os.path.dirname(spec.origin), "win", "vigem", "install", "x64",
                                   "ViGEmBusSetup_x64.msi")
                if not os.path.isfile(msi):
                    raise RuntimeError("установщик в пакете vgamepad не найден")
                self._run_installer_wait(msi, log, msi=True)
            ok, msg = driver_selftest()
            log(("✔ " if ok else "✖ ") + "Проверка драйвера: " + msg +
                ("" if ok else " — если установка прошла, перезагрузите ПК и нажмите «Проверить»."))
            self._setup_result = {"selftest": (ok, msg), "vigem_reg": (vigem_entries() or [None])[0],
                                  "x360ce": process_running("x360ce.exe"), "shortcut": shortcut("check")}
        self.nb.select(self.tab_setup)
        self.tasks.submit("Установка драйвера ViGEmBus", task)

    def install_opentrack(self):
        if not IS_WIN:
            messagebox.showinfo("opentrack", "Установка доступна только в Windows.")
            return

        def task(log):
            url = github_latest_asset(OT_REPO, r"win32-setup\.exe$", OT_FALLBACK)
            log("Загружаю " + url)
            path = download(url, tempfile.gettempdir(), log)
            self._run_installer_wait(path, log)
            found = find_opentrack()
            if found:
                self._found_ot = found
                log("✔ opentrack установлен: " + found)
            else:
                log("opentrack не найден в Program Files — укажите путь кнопкой «Указать путь…».")
        self._found_ot = None
        self.nb.select(self.tab_setup)
        self.tasks.submit("Установка opentrack", task)

    def do_shortcut(self, action):
        if not IS_WIN:
            messagebox.showinfo("Ярлык", "Доступно только в Windows.")
            return

        def task(log):
            ok, msg = shortcut(action)
            log(("✔ " if ok else "✖ ") + f"Ярлык: {msg}")
            self._setup_result = {"shortcut": shortcut("check"), "vigem_reg": (vigem_entries() or [None])[0],
                                  "x360ce": process_running("x360ce.exe")}
        self.tasks.submit("Ярлык на рабочем столе", task)

    # ------------------------------------------------------------ синхронизация виджетов
    def sync_widgets_from_cfg(self):
        prev = self._building
        self._building = True
        n = max(len(self.worker.state["axes"]), 8)
        vals = ["—"] + [str(i + 1) for i in range(n)]
        for role, cb in self.axis_combo.items():
            cb.configure(values=vals)
            idx = self.cfg["axes"].get(role)
            cb.set("—" if idx is None else str(idx + 1))
        for role, v in self.inv_var.items():
            v.set(bool(self.cfg["invert"].get(role)))
        for role, v in self.axen_var.items():
            v.set(bool(self.cfg["axes_enabled"].get(role, True)))
        for key, sc in self.scales.items():
            sc.set(self.cfg[key])
        for key, sc in self.out_scales.items():
            sc.set(self.cfg["output"][key])
        for role, scs in self.resp_scales.items():
            for key, sc in scs.items():
                sc.set(self.cfg["response"][role][key])
        for key, sc in self.yaw_scales.items():
            sc.set(self.cfg["response"]["yaw"][key])
        self.yaw_mode_var.set(self.cfg["response"]["yaw"]["mode"])
        self.poll_var.set(str(int(self.cfg["poll_hz"])))
        self.rs.apply_ministick_cfg(self.cfg["ministick"])
        self.rs.apply_zoom_cfg(self.cfg["zoom"], len(self.worker.state["axes"]) or 8)
        h = self.cfg["head"]
        self.ot_path_var.set(h["opentrack_path"])
        self.manage_var.set(h["manage_process"])
        self.head_en_var.set(h["enabled"])
        self.head_port_var.set(str(h["port"]))
        for key, sc in self.head_scales.items():
            sc.set(h[key])
        self.head_inv_yaw.set(h["invert_yaw"])
        self.head_inv_pitch.set(h["invert_pitch"])
        self.cam_mode_var.set(self.cfg["camera"]["mode"])
        self.cam_speed.set(self.cfg["camera"]["speed"])
        self.cam_stick_speed.set(self.cfg["camera"]["stick_speed"])
        self.cam_max.set(self.cfg["camera"]["max"])
        la = self.cfg["launcher"]
        self.autostart_var.set(bool(self.glob["autostart_bridge"]))
        self.min_var.set(la["minimize_on_play"])
        self.prio_var.set(la["low_priority"])
        self.layers_var.set(self.cfg["layers"]["enabled"])
        self.long_scale.set(self.cfg["long_press_ms"])
        self.proc_var.set(", ".join(self.cfg["auto"]["processes"]))
        self.air_var.set(", ".join(self.cfg["auto"]["aircraft"]))
        gm = self.cfg["game"]
        self.pad_var.set(gm["virtual_pad"])
        self.builtin_var.set(gm["builtin_actions"])
        self.launch_var.set(gm["launch_type"])
        self.exe_var.set(gm["exe_path"])
        set_low_priority(la["low_priority"])
        self.appid_var.set(la["steam_appid"])
        self.refresh_cal()
        self.refresh_tree()
        self._resp_ui_refresh()
        self._building = prev

    def refresh_cal(self):
        cal = self.cfg["throttle_cal"]
        for key, _ in CAL_ROWS:
            done = key in cal["recorded"]
            self.cal_val[key].configure(text=f"{cal[key]:+.3f}" + ("" if done else " *"),
                                        foreground="#000" if done else "#888")
        if make_splitter(cal) is None:
            self.cal_state.configure(text="Ошибка: «назад» и «вперёд» совпадают — перезапишите их.",
                                     foreground="#b91c1c")
        elif len(cal["recorded"]) == 4:
            self.cal_state.configure(text="Калибровка выполнена.", foreground="#15803d")
        else:
            self.cal_state.configure(text="* — значение по умолчанию. Запишите все 4 положения.",
                                     foreground="#b45309")

    def refresh_tree(self):
        builtin = self.cfg["game"]["builtin_actions"]
        for i, cat in enumerate(CATEGORIES):            # встроенные действия AC8 — только если включены
            if builtin:
                self.tree.move("cat:" + cat, "", i + 1)
            else:
                self.tree.detach("cat:" + cat)
        sel = self.tree.selection()
        for ch in self.tree.get_children("cat:custom"):
            self.tree.delete(ch)
        for ca in self.cfg["custom_actions"]:
            self.tree.insert("cat:custom", "end", iid=CUSTOM_PREFIX + ca["id"], text=ca["name"])
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
        ids = all_action_ids(self.cfg)
        bad = conflicting_actions(self.cfg)
        analog = set()
        if self.cfg["game"]["virtual_pad"] or builtin:
            analog = {("axis", analog_axis(self.cfg, r)) for r in self.cfg["axes"]
                      if analog_axis(self.cfg, r) is not None and r != "throttle"}
        for aid in ids:
            pair = action_pair(self.cfg, aid)
            dup = aid in bad
            texts = []
            for b in pair:
                t = binding_text(b)
                if b and b["type"] == "axis" and ("axis", b["index"]) in analog:
                    t += " ⚠"
                texts.append(t)
            ca = find_custom(self.cfg, aid)
            if ca is not None:
                out_t = custom_out_text(ca, self.cfg["layers"]["enabled"])
            else:
                out_t = output_text(self.cfg, aid)
            self.tree.item(aid, values=(texts[0], texts[1], out_t), tags=("dup",) if dup else ())
        if hasattr(self, "yaw_out_lbl"):
            self._resp_ui_refresh()
        if hasattr(self, "via_var"):
            self._sync_out_controls()
        if hasattr(self, "rs"):
            self.rs.refresh()

    # ------------------------------------------------------------ обработчики
    def set_hint(self, text, learn=False):
        self.hint.configure(text=text, bg="#fde68a" if learn else "#e5e7eb")

    def rescan(self):
        self.worker.send("scan")

    def on_device_selected(self, _e=None):
        self.cfg["device_name"] = self.dev_combo.get()
        self.worker.send("scan")
        self.mark_dirty()

    def _calib_ok_or_ask(self):
        if (self.cfg["game"]["virtual_pad"] and len(self.cfg["throttle_cal"]["recorded"]) < 4
                and analog_axis(self.cfg, "throttle") is not None):
            return messagebox.askyesno(
                "РУД не откалиброван",
                "Калибровка РУД не завершена — газ и торможение могут работать неверно.\n"
                "(вкладка «Оси и РУД»)\n\nПродолжить всё равно?")
        return True

    def toggle_bridge(self):
        if self.worker.bridge_on:
            self.worker.send("stop")
            return
        if not self.worker.state["name"]:
            messagebox.showwarning("Нет устройства", "X52 не найден. Подключите джойстик и нажмите «Обновить».")
            return
        if not self._calib_ok_or_ask():
            return
        self.worker.send("start")

    def play_game(self):
        if not self.worker.state["name"]:
            messagebox.showwarning("Нет устройства", "X52 не найден. Подключите джойстик и нажмите «Обновить».")
            return
        if self.conflict:
            if not messagebox.askyesno("x360ce запущен", "Запущен x360ce — в игре будет два геймпада и "
                                                       "управление может сбиваться.\nВсё равно продолжить?"):
                return
        if not self.worker.bridge_on:
            if not self._calib_ok_or_ask():
                return
            self.worker.send("start")
        if self.cfg["head"]["enabled"] and self.cfg["head"]["manage_process"]:
            self.launch_opentrack(quiet=True)
        self._play_pending = time.time()
        self.set_hint("Включаю мост…")

    def _launch_game(self):
        g = self.cfg["game"]
        kind = g["launch_type"]
        appid = self.cfg["launcher"]["steam_appid"]
        try:
            if kind == "steam":
                if not appid:
                    raise RuntimeError("не указан Steam App ID (поле на «Главной»)")
                url = f"steam://rungameid/{appid}"
                if IS_WIN:
                    os.startfile(url)  # noqa
                else:
                    webbrowser.open(url)
                what = f"игра запускается через Steam ({appid})"
            elif kind == "exe":
                path = g["exe_path"]
                if not path or not os.path.exists(path):
                    raise RuntimeError("не найден файл игры — укажите его на «Главной» («Обзор…»)")
                if IS_WIN:
                    os.startfile(path)  # noqa  (работает и для .exe, и для ярлыков)
                else:
                    subprocess.Popen([path], cwd=os.path.dirname(path) or None)
                what = "игра запускается: " + os.path.basename(path)
            else:
                what = "запустите игру сами"
        except Exception as e:  # noqa
            messagebox.showerror("Запуск игры", f"Не удалось запустить игру:\n{e}\n\n"
                                                "Мост работает — можно запустить игру вручную.")
            return False
        self.set_hint(f"Мост работает, {what}. Не закрывайте лаунчер.")
        if self.cfg["launcher"]["minimize_on_play"]:
            self.iconify()
        return True

    def on_autostart(self):
        """«Включать мост при открытии лаунчера» — общая настройка, не профиля."""
        if self._building:
            return
        self.glob["autostart_bridge"] = bool(self.autostart_var.get())
        self.save_global()

    def on_launcher_var(self, key, value):
        if self._building:
            return
        self.cfg["launcher"][key] = value
        self.mark_dirty()

    def on_priority(self):
        low = bool(self.prio_var.get())
        self.cfg["launcher"]["low_priority"] = low
        self.mark_dirty()
        ok = set_low_priority(low)
        if low:
            self.set_hint("Приоритет лаунчера: ниже обычного — процессор в первую очередь у игры." if ok else
                          "Приоритет можно менять только в Windows.")
        else:
            self.set_hint("Приоритет лаунчера: обычный.")

    def on_appid(self):
        if self._building:
            return
        v = self.appid_var.get().strip()
        if (v.isdigit() and 0 < len(v) <= 10) or v == "":
            self.cfg["launcher"]["steam_appid"] = v
            self.mark_dirty()

    def on_launch_type(self):
        if self._building:
            return
        self.cfg["game"]["launch_type"] = self.launch_var.get()
        self.mark_dirty()

    def on_exe_path(self):
        if self._building:
            return
        self.cfg["game"]["exe_path"] = self.exe_var.get().strip().strip('"')
        self.mark_dirty()

    def browse_exe(self):
        p = filedialog.askopenfilename(title="Программа или ярлык игры",
                                       filetypes=[("Программы и ярлыки", "*.exe *.lnk *.bat *.url"),
                                                  ("Все файлы", "*.*")])
        if p:
            self.exe_var.set(os.path.normpath(p))
            self.launch_var.set("exe")
            self.on_launch_type()

    def on_pad_toggle(self):
        if self._building:
            return
        self.cfg["game"]["virtual_pad"] = bool(self.pad_var.get())
        self.mark_dirty()
        self.worker.send("restart")
        self.set_hint("Виртуальный геймпад: " + ("включён" if self.cfg["game"]["virtual_pad"] else
                      "выключен — в игру идут только клавиши (игра сама видит X52)"))

    def on_builtin_toggle(self):
        if self._building:
            return
        self.cfg["game"]["builtin_actions"] = bool(self.builtin_var.get())
        self.mark_dirty()
        self.refresh_tree()

    # ---- профили
    def refresh_profiles(self):
        self._load_rules()
        names = list_profiles()
        cur = self.cfg["profile_name"]
        if cur not in names:
            names.append(cur)
        self.prof_combo.configure(values=names)
        self.prof_combo.set(cur)
        self.title(f"{APP_NAME} {APP_VERSION} — {cur}")
        self.prof_status.configure(text=f"Текущий профиль: {cur}")
        if hasattr(self, "wheel_combo"):
            self._wheel_ui_refresh()
        if hasattr(self, "rs"):
            self.rs.refresh()
            sh = self.glob.get("ministick") or {"profiles": []}
            self.rs.set_ministick_profiles(names, sh["profiles"])
            zs = self.glob.get("zoom") or {"profiles": []}
            self.rs.set_zoom_profiles(names, zs["profiles"])

    def switch_profile(self, name):
        name = clean_profile_name(name)
        if name == self.cfg["profile_name"]:
            return True
        self.save_cfg()
        cfg = self._load_config(profile_path(name), silent=True)
        if cfg is None:
            messagebox.showerror("Профиль", f"Не удалось прочитать профиль «{name}».")
            self.refresh_profiles()
            return False
        cfg["profile_name"] = name
        self.cancel_learn()
        self._replace_cfg(cfg)
        self.refresh_profiles()
        self.set_hint(f"Профиль: {name}")
        return True

    def profile_new(self):
        dlg = ProfileDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        name, tmpl = dlg.result
        name = clean_profile_name(name)
        if name in list_profiles() or name == self.cfg["profile_name"]:
            messagebox.showwarning("Профиль", f"Профиль «{name}» уже есть.")
            return
        self.create_profile(name, tmpl)

    def create_profile(self, name, tmpl):
        self.save_cfg()
        if tmpl == "copy":
            cfg = sanitize_config(json.loads(json.dumps(self.cfg)))
            cfg["profile_name"] = clean_profile_name(name)
            cfg["auto"] = {"processes": list(self.cfg["auto"]["processes"]), "aircraft": []}
            for key in ("ministick", "zoom"):       # копия: мини-стик / зум включены, как в исходном
                sh = self.glob.get(key)
                if sh is not None and cfg[key]["enabled"] and cfg["profile_name"] not in sh["profiles"]:
                    sh["profiles"].append(cfg["profile_name"])
                    self.save_global()
        else:
            cfg = new_profile_config(name, tmpl, self.cfg)
        write_json_atomic(profile_path(cfg["profile_name"]), cfg)
        self.cancel_learn()
        self._replace_cfg(cfg)
        self.save_cfg()
        self.refresh_profiles()
        if tmpl in GAME_TEMPLATES and not self.glob["auto_switch"]:
            self.auto_var.set(True)         # шаблон игры без автопереключения бесполезен
            self.on_auto_toggle()
        if tmpl == "custom" or tmpl in GAME_TEMPLATES:
            self.nb.select(self.T_ASSIGN)
            self.set_hint(f"Профиль «{cfg['profile_name']}» создан. Добавьте свои действия: "
                          f"«Назначение» → «Добавить…».")
        return cfg

    def profile_rename(self, new=None):
        old = self.cfg["profile_name"]
        if new is None:
            new = simpledialog.askstring("Переименовать профиль", "Новое имя профиля:", initialvalue=old,
                                         parent=self)
        if not new:
            return
        new = clean_profile_name(new)
        if new == old:
            return
        if new in list_profiles():
            messagebox.showwarning("Профиль", f"Профиль «{new}» уже есть.")
            return
        try:
            os.remove(profile_path(old))
        except OSError:
            pass
        for key in ("ministick", "zoom"):
            sh = self.glob.get(key)
            if sh and old in sh["profiles"]:
                sh["profiles"] = [new if p == old else p for p in sh["profiles"]]
                self.save_global()
        self.cfg["profile_name"] = new
        self.save_cfg()
        self.refresh_profiles()

    def profile_delete(self, confirm=True):
        cur = self.cfg["profile_name"]
        others = [n for n in list_profiles() if n != cur]
        if not others:
            messagebox.showinfo("Профиль", "Это единственный профиль — удалить нельзя.")
            return
        if confirm and not messagebox.askyesno("Удалить профиль", f"Удалить профиль «{cur}»?\n"
                                                                  f"Будет открыт «{others[0]}»."):
            return
        cfg = self._load_config(profile_path(others[0]), silent=True)
        if cfg is None:
            messagebox.showerror("Профиль", f"Не удалось прочитать профиль «{others[0]}».")
            return
        try:
            os.remove(profile_path(cur))
        except OSError:
            pass
        for key in ("ministick", "zoom"):
            sh = self.glob.get(key)
            if sh and cur in sh["profiles"]:
                sh["profiles"].remove(cur)
                self.save_global()
        cfg["profile_name"] = others[0]
        self.cancel_learn()
        self._replace_cfg(cfg)
        self.save_cfg()
        self.refresh_profiles()

    def on_axis_selected(self, role):
        t = self.axis_combo[role].get()
        self.cfg["axes"][role] = None if t == "—" else int(t) - 1
        self.mark_dirty()

    def on_axis_enable(self, role):
        if self._building:
            return
        on = bool(self.axen_var[role].get())
        self.cfg["axes_enabled"][role] = on
        self.mark_dirty()
        self.refresh_tree()
        name = dict(AXIS_ROLES)[role].split(" (")[0]
        self.set_hint(f"{name}: " + ("ось снова работает аналогово" if on else
                                     "аналоговая работа выключена — ось можно назначать на клавиши"))

    def on_invert(self, role):
        self.cfg["invert"][role] = bool(self.inv_var[role].get())
        self.mark_dirty()

    def on_scale(self, key, value):
        if self._building:
            return
        self.cfg[key] = float(value)
        self.mark_dirty()

    def on_output(self, key, value):
        if self._building:
            return
        self.cfg["output"][key] = value
        self.mark_dirty()

    def on_poll(self):
        try:
            v = int(float(self.poll_var.get()))
        except (tk.TclError, ValueError):
            self.poll_var.set(str(self.cfg["poll_hz"]))
            return
        self.cfg["poll_hz"] = max(30, min(1000, v))
        self.poll_var.set(str(self.cfg["poll_hz"]))
        self.mark_dirty()

    def on_ministick_toggle(self):
        if self._building:
            return
        en = bool(self.rs.ministick_var.get())
        self.cfg["ministick"]["enabled"] = en
        if en and not self.cfg["game"]["virtual_pad"]:     # без геймпада мини-стик в игру не попадёт
            self.cfg["game"]["virtual_pad"] = True
            self.pad_var.set(True)
            self.worker.send("restart")
        self._ms_shared_capture()
        v = self.rs.ms_prof_vars.get(self.cfg["profile_name"])
        if v is not None:
            v.set(en)
        self.mark_dirty()
        w = getattr(self, "worker", None)
        if w and w.ministick is not None:
            if en:
                w.ministick.start()
            else:
                w.ministick.stop()
        self.rs.update_ministick_status(w.ministick if w else None)

    def on_zoom_toggle(self):
        if self._building:
            return
        en = bool(self.rs.zoom_var.get())
        self.cfg["zoom"]["enabled"] = en
        if en and not self.cfg["game"]["virtual_pad"]:     # зум идёт в игру через геймпад
            self.cfg["game"]["virtual_pad"] = True
            self.pad_var.set(True)
            self.worker.send("restart")
        self._zoom_shared_capture()
        v = self.rs.zoom_prof_vars.get(self.cfg["profile_name"])
        if v is not None:
            v.set(en)
        self.rs.apply_zoom_cfg(self.cfg["zoom"], len(self.worker.state["axes"]) or 8)
        self.mark_dirty()

    def on_zoom_profile(self, name):
        """Галочка профиля в блоке «Зум работает в профилях»."""
        on = bool(self.rs.zoom_prof_vars[name].get())
        if name == self.cfg["profile_name"]:
            self.rs.zoom_var.set(on)
            self.on_zoom_toggle()
            return
        sh = self.glob["zoom"]
        sh["profiles"] = [p for p in sh["profiles"] if p != name] + ([name] if on else [])
        self.save_global()

    def on_zoom_val(self, key, v):
        if self._building:
            return
        self.cfg["zoom"][key] = v
        self.mark_dirty()

    def on_ms_profile(self, name):
        """Галочка профиля в блоке «Мини-стик работает в профилях»."""
        on = bool(self.rs.ms_prof_vars[name].get())
        if name == self.cfg["profile_name"]:
            self.rs.ministick_var.set(on)
            self.on_ministick_toggle()
            return
        sh = self.glob["ministick"]
        sh["profiles"] = [p for p in sh["profiles"] if p != name] + ([name] if on else [])
        self.save_global()

    def on_ministick_sens(self, value):
        if self._building:
            return
        v = max(0.1, min(5.0, float(value)))
        self.cfg["ministick"]["sens"] = v
        w = getattr(self, "worker", None)
        if w and w.ministick is not None:
            w.ministick.set_sens(v)
        self.mark_dirty()

    def on_ministick_dz(self, value):
        if self._building:
            return
        v = max(0.0, min(0.40, float(value)))
        self.cfg["ministick"]["deadzone"] = v
        self.mark_dirty()

    def on_ministick_val(self, key, v):
        if self._building:
            return
        self.cfg["ministick"][key] = v
        self.mark_dirty()

    def on_ministick_invert(self, axis):
        if self._building:
            return
        var = self.rs.ministick_inv_x if axis == "x" else self.rs.ministick_inv_y
        self.cfg["ministick"]["invert_" + axis] = bool(var.get())
        self.mark_dirty()

    def on_cam_mode_from_ms(self):
        if self._building:
            return
        self.cam_mode_var.set(self.rs.ms_mode_var.get())
        self.on_cam_mode()

    def on_cam_val_from_ms(self, key, v):
        if self._building:
            return
        self.cfg["camera"][key] = float(v)
        {"speed": self.cam_speed, "stick_speed": self.cam_stick_speed, "max": self.cam_max}[key].set(float(v))
        self.mark_dirty()

    def on_ms_bind_set(self, direction):
        if self.learn or self.grab_current() is not None:
            return
        r = self.rs.pick_key()
        if not r:
            return
        self.cfg["ministick"]["bindings"][direction] = list(r)[:3]
        self.rs.apply_ministick_cfg(self.cfg["ministick"])
        self.mark_dirty()

    def on_ms_bind_clear(self, direction):
        self.cfg["ministick"]["bindings"][direction] = []
        self.rs.apply_ministick_cfg(self.cfg["ministick"])
        self.mark_dirty()

    def on_ms_bind_thr(self, v):
        if self._building:
            return
        self.cfg["ministick"]["bind_threshold"] = max(0.1, min(0.95, float(v)))
        self.mark_dirty()

    def on_head_var(self, key, value):
        if self._building:
            return
        self.cfg["head"][key] = value
        self.mark_dirty()

    def on_head_toggle(self):
        en = bool(self.head_en_var.get())
        self.cfg["head"]["enabled"] = en
        self.mark_dirty()
        if self.cfg["head"]["manage_process"]:
            if en:
                self.launch_opentrack(quiet=True)
            else:
                self.close_opentrack()
        self.set_hint("Обзор головой (opentrack): " + ("включён" if en else "выключен — обзор кнопками X52"))

    def on_cam_mode(self):
        if self._building:
            return
        self.cfg["camera"]["mode"] = self.cam_mode_var.get()
        self.rs.ms_mode_var.set(self.cfg["camera"]["mode"])
        self.worker.send("center")
        self.mark_dirty()

    def on_cam_val(self, key, v):
        if self._building:
            return
        self.cfg["camera"][key] = float(v)
        {"stick_speed": self.rs.ms_cam_stick_speed, "max": self.rs.ms_cam_max}[key].set(float(v))
        self.mark_dirty()

    def on_cam_speed(self, v):
        if self._building:
            return
        self.cfg["camera"]["speed"] = float(v)
        self.rs.ms_cam_speed.set(float(v))
        self.mark_dirty()

    def on_head_port(self):
        try:
            v = int(float(self.head_port_var.get()))
        except (tk.TclError, ValueError):
            self.head_port_var.set(str(self.cfg["head"]["port"]))
            return
        v = max(1024, min(65535, v))
        self.head_port_var.set(str(v))
        if v != self.cfg["head"]["port"]:
            self.cfg["head"]["port"] = v
            self.mark_dirty()

    def record_cal(self, key):
        ti = self.cfg["axes"].get("throttle")
        axes = self.worker.state["axes"]
        if ti is None or ti >= len(axes):
            messagebox.showinfo("РУД", "Сначала назначьте ось РУД (кнопка «Определить»).")
            return
        cal = dict(self.cfg["throttle_cal"])
        cal["recorded"] = list(cal["recorded"])
        cal[key] = round(axes[ti], 4)
        if key not in cal["recorded"]:
            cal["recorded"].append(key)
        self.cfg["throttle_cal"] = cal
        self.refresh_cal()
        self.mark_dirty()
        self.set_hint(f"Записано: {dict(CAL_ROWS)[key]} = {cal[key]:+.3f}")

    def reset_cal(self):
        self.cfg["throttle_cal"] = default_config()["throttle_cal"]
        self.refresh_cal()
        self.mark_dirty()

    # ---- opentrack
    def browse_opentrack(self):
        p = filedialog.askopenfilename(title="Выберите opentrack.exe",
                                       filetypes=[("opentrack", "opentrack.exe"), ("Программы", "*.exe"),
                                                  ("Все файлы", "*.*")])
        if p:
            self.ot_path_var.set(os.path.normpath(p))

    def _ot_alive(self):
        return self.ot_proc is not None and self.ot_proc.poll() is None

    def toggle_opentrack(self):
        if self._ot_alive():
            self.close_opentrack()
        else:
            self.launch_opentrack()

    def launch_opentrack(self, quiet=False):
        path = self.cfg["head"]["opentrack_path"].strip().strip('"')
        if self._ot_alive():
            return True
        if not path or not os.path.isfile(path):
            if not quiet:
                messagebox.showwarning("opentrack", "Файл opentrack.exe не найден.\n"
                                                    "Укажите путь или установите opentrack на вкладке «Установка».")
            else:
                self.set_hint("opentrack не запущен: не найден opentrack.exe (вкладка «Установка»).")
            return False
        if process_running("opentrack.exe"):
            self.set_hint("opentrack уже запущен.")
            return True
        try:
            self.ot_proc = subprocess.Popen([path], cwd=os.path.dirname(path) or None)
        except OSError as e:
            if not quiet:
                messagebox.showerror("opentrack", f"Не удалось запустить opentrack:\n{e}")
            self.set_hint(f"Не удалось запустить opentrack: {e}")
            return False
        self.set_hint("opentrack запущен. Нажмите в нём Start.")
        return True

    def close_opentrack(self):
        if self._ot_alive():
            self.ot_proc.terminate()
            try:
                self.ot_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.ot_proc.kill()
        self.ot_proc = None

    # ---- режим обучения
    def start_learn(self, kind, hint, on_done):
        if not self.worker.state["name"]:
            messagebox.showinfo("Нет устройства", "X52 не найден. Подключите джойстик и нажмите «Обновить».")
            return
        st = self.worker.state
        self.learn = {"kind": kind, "on_done": on_done, "t0": time.time(),
                      "axes0": list(st["axes"]), "btn0": list(st["buttons"]),
                      "hat0": [tuple(h) for h in st["hats"]]}
        self.set_hint(hint, learn=True)

    def cancel_learn(self, msg="Отменено."):
        if self.learn:
            self.learn = None
            self.set_hint(msg)

    def learn_axis(self, role):
        label = dict(AXIS_ROLES)[role]
        self.start_learn("axis", f"Подвигайте нужную ось X52: «{label}»… (Esc — отмена)",
                         lambda idx: self._axis_learned(role, idx))

    def _axis_learned(self, role, idx):
        self.cfg["axes"][role] = idx
        self.axis_combo[role].set(str(idx + 1))
        self.mark_dirty()
        self.set_hint(f"«{dict(AXIS_ROLES)[role]}» → ось {idx + 1}")

    def _selected_action(self):
        sel = self.tree.selection()
        if not sel:
            return None
        if sel[0] in ACTION_LABEL or find_custom(self.cfg, sel[0]) is not None:
            return sel[0]
        return None

    def learn_binding(self, slot=0):
        aid = self._selected_action()
        if not aid:
            messagebox.showinfo("Назначение", "Сначала выберите действие в списке (не название группы).")
            return
        which = "основной" if slot == 0 else "дополнительной"
        self.start_learn("button",
                         f"«{action_label(self.cfg, aid)}» ({which}): нажмите кнопку / хатку X52 или отклоните ось "
                         f"(ручку, РУД, крутилку) до нужного положения… (Esc — отмена)",
                         lambda b: self._binding_learned(aid, slot, b))

    def _set_pair(self, aid, pair):
        ca = find_custom(self.cfg, aid)
        if ca is not None:
            ca["bindings"] = pair
        else:
            self.cfg["bindings"][aid] = pair

    def _binding_learned(self, aid, slot, b):
        if find_custom(self.cfg, aid) is None and aid not in ACTION_LABEL:
            return          # действие удалили, пока ждали нажатия
        pair = list(action_pair(self.cfg, aid))
        pair[slot] = b
        if pair[1 - slot] == b:
            pair[1 - slot] = None
        if pair[0] is None and pair[1] is not None:
            pair = [pair[1], None]
        self._set_pair(aid, pair)
        self.refresh_tree()
        self.mark_dirty()
        msg = f"«{action_label(self.cfg, aid)}» → {binding_text(b)}"
        if b["type"] == "axis":
            msg += " (порог можно изменить кнопкой «Порог оси…»)"
        self.set_hint(msg)

    def clear_binding(self, slot=0):
        aid = self._selected_action()
        if aid:
            pair = list(action_pair(self.cfg, aid))
            pair[slot] = None
            if pair[0] is None and pair[1] is not None:
                pair = [pair[1], None]
            self._set_pair(aid, pair)
            self.refresh_tree()
            self.mark_dirty()

    def edit_axis_threshold(self):
        aid = self._selected_action()
        if not aid:
            messagebox.showinfo("Порог оси", "Сначала выберите действие в списке.")
            return
        pair = action_pair(self.cfg, aid)
        changed = False
        for slot, b in enumerate(pair):
            if not b or b["type"] != "axis":
                continue
            which = "основной" if slot == 0 else "дополнительной"
            cond = "не меньше" if b["dir"] == "+" else "не больше"
            v = simpledialog.askfloat(
                "Порог оси", f"«{action_label(self.cfg, aid)}», {which} привязка — ось {b['index'] + 1}.\n"
                f"Срабатывает, когда значение оси {cond} порога.\n"
                f"Значения оси: от -1 до +1 (смотрите полоски на «Главной»).\n\nПорог (-0.95 … 0.95):",
                initialvalue=b["thr"], minvalue=-0.95, maxvalue=0.95, parent=self)
            if v is not None:
                nb = dict(b)
                nb["thr"] = round(v, 3)
                pair[slot] = nb
                changed = True
        if not any(b and b["type"] == "axis" for b in pair):
            messagebox.showinfo("Порог оси", "У этого действия нет привязки к оси.")
        if changed:
            self.refresh_tree()
            self.mark_dirty()

    def _sync_out_controls(self):
        aid = self._selected_action()
        ca = find_custom(self.cfg, aid) if aid else None
        if ca is not None:
            self.via_var.set("key")
            self.via_pad.configure(state="disabled")
            self.via_key.configure(state="normal")
            self.key_btn.configure(state="normal")
            self.out_info.configure(text="своё действие — " + custom_out_text(ca, self.cfg["layers"]["enabled"]))
            return
        if not aid or aid in INTERNAL_ACTIONS:
            for w in (self.via_pad, self.via_key, self.key_btn):
                w.configure(state="disabled")
            self.out_info.configure(text="команда лаунчера — выход не нужен" if aid else "")
            return
        o = self.cfg["outputs"][aid]
        self.via_var.set(o["via"])
        self.via_pad.configure(state="normal" if ACTION_PAD[aid] else "disabled")
        self.via_key.configure(state="normal")
        self.key_btn.configure(state="normal")
        if not ACTION_PAD[aid]:
            info = "у геймпада нет такого действия — только клавиатура"
        elif o["via"] == "key" and not o["keys"]:
            info = "⚠ клавиша не выбрана — нажмите «Клавиша…»"
        else:
            info = output_text(self.cfg, aid)
        self.out_info.configure(text=info)

    def on_via(self):
        aid = self._selected_action()
        if not aid or aid in INTERNAL_ACTIONS or find_custom(self.cfg, aid) is not None:
            return
        via = self.via_var.get()
        if via == "pad" and not ACTION_PAD[aid]:
            via = "key"
        self.cfg["outputs"][aid]["via"] = via
        if via == "key" and not self.cfg["outputs"][aid]["keys"]:
            self.cfg["outputs"][aid]["keys"] = list(ACTION_KEYS[aid])
        self.refresh_tree()
        self.mark_dirty()

    def edit_keys(self):
        aid = self._selected_action()
        if not aid or aid in INTERNAL_ACTIONS:
            return
        ca = find_custom(self.cfg, aid)
        if ca is not None and ca["mode"] in ("sequence", "profile", "camera"):
            self.custom_edit()
            return
        if ca is not None:
            dlg = KeyDialog(self, f"Клавиша: {ca['name']}", ca["keys"], ca["keys"])
            self.wait_window(dlg)
            if dlg.result:
                ca["keys"] = dlg.result
                self.refresh_tree()
                self.mark_dirty()
            return
        o = self.cfg["outputs"][aid]
        dlg = KeyDialog(self, f"Клавиша: {ACTION_LABEL[aid]}", o["keys"], ACTION_KEYS[aid])
        self.wait_window(dlg)
        if dlg.result is not None:
            o["keys"] = dlg.result
            if dlg.result:
                o["via"] = "key"
            elif ACTION_PAD[aid]:
                o["via"] = "pad"
            self.refresh_tree()
            self.mark_dirty()
            self.set_hint(f"«{ACTION_LABEL[aid]}» → {output_text(self.cfg, aid)}")

    # ---- свои действия
    def custom_add(self, data=None):
        if len(self.cfg["custom_actions"]) >= 200:
            messagebox.showinfo("Своё действие", "Достигнут предел — 200 своих действий.")
            return None
        if data is None:
            dlg = CustomActionDialog(self, "Новое действие", None, self.cfg["long_press_ms"],
                                     self.cfg["layers"]["enabled"], self._all_profile_names())
            self.wait_window(dlg)
            data = dlg.result
        if not data:
            return None
        ca = {"id": new_custom_id(self.cfg), "name": data["name"], "keys": list(data.get("keys", [])),
              "mode": data.get("mode", "hold"), "trigger": data.get("trigger", "press"),
              "layer": int(data.get("layer", 0)), "steps": [dict(st) for st in data.get("steps", [])],
              "repeat_ms": data.get("repeat_ms", 100), "profile": data.get("profile"),
              "cam": data.get("cam"), "bindings": [None, None]}
        tmp = sanitize_config(dict(self.cfg, custom_actions=[ca]))["custom_actions"][0]
        ca.update(steps=tmp["steps"], keys=tmp["keys"], mode=tmp["mode"], trigger=tmp["trigger"],
                  layer=tmp["layer"], repeat_ms=tmp["repeat_ms"], profile=tmp["profile"], cam=tmp["cam"])
        self.cfg["custom_actions"].append(ca)
        self.refresh_tree()
        self.mark_dirty()
        aid = CUSTOM_PREFIX + ca["id"]
        self.tree.selection_set(aid)
        self.tree.see(aid)
        self.set_hint(f"Добавлено «{ca['name']}» → {custom_out_text(ca)}. "
                      f"Теперь «Назначить основную…» и нажмите кнопку X52.")
        return ca

    def custom_edit(self, data=None):
        aid = self._selected_action()
        ca = find_custom(self.cfg, aid) if aid else None
        if ca is None:
            messagebox.showinfo("Своё действие", "Выберите своё действие в группе «Свои действия».")
            return
        if data is None:
            dlg = CustomActionDialog(self, "Изменить действие", ca, self.cfg["long_press_ms"],
                                     self.cfg["layers"]["enabled"], self._all_profile_names())
            self.wait_window(dlg)
            data = dlg.result
        if data:
            tmp = sanitize_config(dict(self.cfg, custom_actions=[dict(ca, **data)]))["custom_actions"][0]
            ca.update(name=tmp["name"], keys=tmp["keys"], mode=tmp["mode"], trigger=tmp["trigger"],
                      layer=tmp["layer"], steps=tmp["steps"], repeat_ms=tmp["repeat_ms"], profile=tmp["profile"],
                      cam=tmp["cam"])
            self.refresh_tree()
            self.mark_dirty()

    def custom_delete(self, confirm=True):
        aid = self._selected_action()
        ca = find_custom(self.cfg, aid) if aid else None
        if ca is None:
            messagebox.showinfo("Своё действие", "Выберите своё действие в группе «Свои действия».")
            return
        if confirm and not messagebox.askyesno("Удалить", f"Удалить действие «{ca['name']}»?"):
            return
        self.cfg["custom_actions"] = [x for x in self.cfg["custom_actions"] if x is not ca]
        self.refresh_tree()
        self.mark_dirty()

    def reset_bindings(self):
        if messagebox.askyesno("Назначение", "Сбросить привязки X52 и клавиши действий ACE COMBAT 8 по умолчанию?\n"
                                             "(«Свои действия» не изменятся)"):
            d = default_config()
            self.cfg["bindings"] = d["bindings"]
            self.cfg["outputs"] = d["outputs"]
            self.refresh_tree()
            self.mark_dirty()

    def poll_learn(self):
        L = self.learn
        if not L:
            return
        if time.time() - L["t0"] > 15:
            self.cancel_learn("Время ожидания истекло.")
            return
        st = self.worker.state
        if not st["name"]:
            self.cancel_learn("Устройство отключено — назначение отменено.")
            return
        if L["kind"] == "axis":
            best, bd = None, 0.45
            for i, v in enumerate(st["axes"]):
                if i < len(L["axes0"]):
                    d = abs(v - L["axes0"][i])
                    if d > bd:
                        best, bd = i, d
            if best is not None:
                self.learn = None
                L["on_done"](best)
            return
        for i, v in enumerate(st["buttons"]):
            if i >= len(L["btn0"]):
                continue
            if v and not L["btn0"][i]:
                self.learn = None
                L["on_done"]({"type": "button", "index": i})
                return
            if not v:
                L["btn0"][i] = 0
        for hi, (x, y) in enumerate(st["hats"]):
            if hi >= len(L["hat0"]):
                continue
            if (x or y) and not any(L["hat0"][hi]):
                d = "up" if y > 0 else "down" if y < 0 else "left" if x < 0 else "right"
                self.learn = None
                L["on_done"]({"type": "hat", "index": hi, "dir": d})
                return
            if not (x or y):
                L["hat0"][hi] = (0, 0)
        # ось как кнопка: отклонение от начального положения больше чем на полхода
        best, bd = None, 0.5
        for i, v in enumerate(st["axes"]):
            if i < len(L["axes0"]) and math.isfinite(v):
                d = abs(v - L["axes0"][i])
                if d > bd:
                    best, bd = i, d
        if best is not None:
            b = learn_axis_binding(L["axes0"][best], st["axes"][best])
            b["index"] = best
            self.learn = None
            L["on_done"](b)

    # ------------------------------------------------------------ цикл обновления
    def tick(self):
        if getattr(self, "_closing", False):
            return
        try:
            light = self.state() == "iconic"
        except tk.TclError:
            light = False
        if light and self.learn:
            self.cancel_learn()
        try:
            self._tick(light)
        except Exception:  # noqa
            log_error(traceback.format_exc())
        # свёрнуто: 4 раза в секунду (только служебное), открыто: ~30 раз в секунду
        # свёрнуто: 10 раз в секунду (смена профиля кнопкой, оверлей, автопрофиль), открыто: ~30
        self._tick_job = self.after(100 if light else 33, self.tick)

    def _tick(self, light=False):
        w = self.worker
        if w.error:
            msg, w.error = w.error, None
            self._play_pending = None
            messagebox.showerror("Ошибка", msg)
        if w.loop_error != self._last_loop_err:
            self._last_loop_err = w.loop_error
            if w.loop_error:
                self.set_hint(f"Внутренняя ошибка (подробности в x52_error.log): {w.loop_error}")

        # события от рабочего потока (кнопки X52)
        while True:
            try:
                ev, val = w.events.get_nowait()
            except queue.Empty:
                break
            if ev == "head_toggled":
                self.head_en_var.set(val)
                self.mark_dirty()
                self.set_hint("Кнопка X52: обзор головой " + ("включён" if val else "выключен"))
            elif ev == "center":
                self.center_lbl.configure(text="обзор отцентрован " + time.strftime("%H:%M:%S"))

        # журнал фоновых задач
        while True:
            try:
                kind, text = self.tasks.log.get_nowait()
            except queue.Empty:
                break
            self.log({"start": "▶ ", "done": "✔ Готово: ", "fail": "✖ Ошибка: ", "line": ""}[kind] + text)
        res = getattr(self, "_setup_result", None)
        if res:
            self._setup_result = None
            self._apply_setup_result(res)
        found = getattr(self, "_found_ot", None)
        if found:
            self._found_ot = None
            if not self.cfg["head"]["opentrack_path"] or not os.path.isfile(self.cfg["head"]["opentrack_path"]):
                self.ot_path_var.set(found)
            self._refresh_ot_setup()

        # запуск игры после включения моста
        if self._play_pending is not None:
            if w.bridge_on:
                self._play_pending = None
                self._launch_game()
            elif time.time() - self._play_pending > 5:
                self._play_pending = None
                self.set_hint("Мост не включился — игра не запущена.")

        # автозапуск моста
        if not self._autostart_done and self.glob["autostart_bridge"] and w.state["name"]:
            self._autostart_done = True
            if not w.bridge_on:
                w.send("start")

        st = w.state
        name = st["name"]
        axes, buttons, hats = st["axes"], st["buttons"], st["hats"]

        # x360ce проверяется только когда мост выключен и окно открыто (запуск tasklist во время
        # игры даёт рывки); перед «Играть» проверка уже прошла.
        if (IS_WIN and not w.bridge_on and not light and time.time() - self._conflict_t > 10
                and not self.tasks.busy and self.tasks.q.empty()):
            self._conflict_t = time.time()

            def chk():
                self.conflict = process_running("x360ce.exe")
            threading.Thread(target=chk, daemon=True).start()

        self._drain_profile_events()
        if self.worker.open_count != self._open_seen:
            self._open_seen = self.worker.open_count
            self._wheel_seen = False
        self._wheel_tick()
        if self._wheel_save_t and time.time() - self._wheel_save_t > 1.0:
            self._wheel_save_t = None
            self.save_global()
        self._overlay_tick()
        if time.time() - self._gc_t >= 1.0:
            # младшее поколение — каждую секунду (доли мс), среднее — раз в 10 с, полная — раз в минуту
            self._gc_t = time.time()
            self._gc_n += 1
            gc.collect(2 if self._gc_n % 60 == 0 else 1 if self._gc_n % 10 == 0 else 0)
        if time.time() - self._auto_t >= 1.0:
            self._auto_t = time.time()
            try:
                self._auto_tick()
            except Exception:  # noqa
                log_error(traceback.format_exc())

        if light:          # окно свёрнуто — ничего не рисуем
            return

        devs = list(w.devices)
        if devs != self._last_devices:
            self._last_devices = devs
            self.dev_combo.configure(values=devs)
        if name and self.dev_combo.get() != name:
            self.dev_combo.set(name)
        elif not name and self.dev_combo.get() and not devs:
            self.dev_combo.set("")
        if len(axes) != self._n_axes:
            self._n_axes = len(axes)
            self._rebuild_raw_axes(len(axes))
            vals = ["—"] + [str(i + 1) for i in range(max(len(axes), 8))]
            for cb in self.axis_combo.values():
                cb.configure(values=vals)
        if len(buttons) != self._n_buttons:
            self._n_buttons = len(buttons)
            self._rebuild_raw_buttons(len(buttons))

        out = w.out
        cur = self.nb.index("current")
        if cur == self.T_RS:       # «Карта кнопок» (как RS Mapper)
            self.rs.tick(st)
        elif cur == self.T_MAIN:     # «Главная»
            for i, bar in enumerate(self.raw_axis_bars):
                if i < len(axes):
                    bar.set(axes[i])
            for i, lb in enumerate(self.raw_btn_labels):
                on = bool(buttons[i]) if i < len(buttons) else False
                if on != self.raw_btn_state[i]:
                    self.raw_btn_state[i] = on
                    lb.configure(bg="#22c55e" if on else "#eeeeee")
            self._set_text(self.hats_lbl, "Хатки: " + (
                "   ".join(f"{i + 1}: " + self._hat_arrow(h) for i, h in enumerate(hats)) if hats else "—"))
            pad_on = self.cfg["game"]["virtual_pad"]     # без геймпада игра получает только клавиши
            self.lstick.set(out["roll"] if pad_on else 0.0, out["pitch"] if pad_on else 0.0)
            self.rstick.set(out["cam_x"] if pad_on else 0.0, out["cam_y"] if pad_on else 0.0)
            self._set_text(self.cam_src_lbl, CAM_SRC_TEXT.get(out.get("cam_src"), "") if pad_on else
                           "виртуальный геймпад выключен")
            self.lt_bar.set(out["lt"] if pad_on else 0.0)
            self.rt_bar.set(out["rt"] if pad_on else 0.0)
            shown = [TOKEN_TEXT.get(t, t) for t in sorted(out["pressed"])] if pad_on else []
            shown += ["клав. " + key_text(k) for k in sorted(out.get("keys", ()))]
            self._set_text(self.pressed_lbl, ", ".join(shown) or "—")
            self._set_text(self.send_lbl, (f"Обновлений в игру: {w.send_hz:.0f} в секунду "
                                           f"(опрос X52 {w.loop_hz:.0f} Гц)") if w.bridge_on else "")
        elif cur == self.T_AXES:     # «Оси и РУД»
            for role, bar in self.axis_bar.items():
                idx = self.cfg["axes"].get(role)
                bar.set(axes[idx] if idx is not None and idx < len(axes) else 0.0)
            ti = self.cfg["axes"].get("throttle")
            self.cal_raw_bar.set(axes[ti] if ti is not None and ti < len(axes) else 0.0)
            self.cal_lt_bar.set(out["lt"])
            self.cal_rt_bar.set(out["rt"])
            if w.loop_hz:
                self._set_text(self.hz_lbl, f"фактически: {w.loop_hz:.0f} Гц, в игру: {w.send_hz:.0f}/с")
        elif cur == self.T_RESP:     # «Отклик ручки»
            self._tick_response(axes, out)
        elif cur == self.T_ASSIGN:     # «Назначение»
            now = [f"Кнопка {i + 1}" for i, v in enumerate(buttons) if v]
            for hi, (x, y) in enumerate(hats):
                if x or y:
                    now.append(f"Хатка {hi + 1} {self._hat_arrow((x, y))}")
            acts = [action_label(self.cfg, a) for a in all_action_ids(self.cfg) if a in out.get("actions", ())]
            self._set_text(self.now_pressed, "Сейчас на X52: " + (", ".join(now) if now else "—") +
                           ("   →   " + "; ".join(acts) if acts else ""))
        elif cur == self.T_MODES:     # «Режимы и автопрофиль»
            self._tick_modes()
        elif cur == self.T_VIEW:     # «Обзор»
            self.view_stick.set(out["cam_x"], out["cam_y"])
            self._set_text(self.view_src, CAM_SRC_TEXT.get(out.get("cam_src"), "") or "в центре")
        self._tick_head(full=(cur == self.T_VIEW))

        self._set_text(self.conflict_lbl, "⚠ Запущен x360ce — закройте его, иначе в игре будет два геймпада."
                       if self.conflict else "")
        if w.bridge_on:
            self._set_text(self.start_btn, "■  Остановить мост")
            self._set_text(self.status_lbl, "● Мост работает — игра видит виртуальный Xbox 360"
                           if self.cfg["game"]["virtual_pad"] else
                           "● Мост работает — X52 → клавиатура (без виртуального геймпада)", "#15803d")
        else:
            self._set_text(self.start_btn, "▶  Запустить мост")
            if name:
                self._set_text(self.status_lbl, f"Мост выключен. Найдено: {name}", "#555")
            else:
                self._set_text(self.status_lbl, "⚠ X52 не найден — подключите джойстик", "#b91c1c")

        self.poll_learn()

    def _set_text(self, widget, text, color=None):
        """configure только при изменении: каждая перенастройка виджета стоит перерисовки."""
        key = (text, color)
        if self._wcache.get(widget) == key:
            return
        self._wcache[widget] = key
        if color is None:
            widget.configure(text=text)
        else:
            widget.configure(text=text, foreground=color)

    def _tick_response(self, axes, out):
        for role in ("roll", "pitch"):
            idx = self.cfg["axes"].get(role)
            raw = axes[idx] if idx is not None and idx < len(axes) else 0.0
            if not math.isfinite(raw):
                raw = 0.0
            if self.cfg["invert"].get(role):
                raw = -raw
            r = self.cfg["response"][role]
            self.curve_view[role].set_point(abs(clamp(raw)), abs(shape_axis(raw, r)))
            f2 = lambda v: f"{0.0 if abs(v) < 0.005 else v:+.2f}"
            self.resp_out[role].configure(text=f"X52 {f2(raw)}  →  игра {f2(out[role])}")
        self.yaw_bar.set(out.get("yaw", 0.0))
        acts = out.get("actions", ())
        for lbl, aid in ((self.yaw_l_lbl, "yaw_left"), (self.yaw_r_lbl, "yaw_right")):
            on = aid in acts
            col = "#22c55e" if on else "#eeeeee"
            if lbl.cget("bg") != col:
                lbl.configure(bg=col)

    def _tick_head(self, full=True):
        hd = self.worker.head
        h = self.cfg["head"]
        if bool(self.head_en_var.get()) != h["enabled"]:
            self.head_en_var.set(h["enabled"])
        if not full:
            if self.ot_proc is not None and not self._ot_alive():
                self.ot_proc = None
            return
        if not h["enabled"]:
            mode = "«как мышь»" if self.cfg["camera"]["mode"] == "mouse" else "«как стик»"
            txt, col = f"Выключено — обзор кнопками X52 ({mode}).", "#555"
        elif hd.get("error"):
            txt, col = "✖ " + hd["error"], "#b91c1c"
        elif hd.get("fresh"):
            rate = hd.get("rate", 0)
            txt = "● Данные идут" + (f": {rate:.0f} пакетов/с" if rate >= 1 else "")
            col = "#15803d"
        elif hd.get("listening"):
            txt, col = (f"○ Жду данные на 127.0.0.1:{h['port']} — в opentrack нажмите Start "
                        f"(Output = «UDP over network»)."), "#b45309"
        else:
            txt, col = "Открываю порт…", "#555"
        self.head_status.configure(text=txt, foreground=col)
        raw = hd.get("raw")
        for i, k in enumerate(("x", "y", "z", "yaw", "pitch", "roll")):
            self.head_vals[k].configure(text=f"{raw[i]:+6.1f}" if raw and hd.get("fresh") else "—")
        if self._ot_alive():
            self.ot_btn.configure(text="Закрыть opentrack")
            self.ot_status.configure(text=f"opentrack запущен лаунчером (PID {self.ot_proc.pid}).",
                                     foreground="#15803d")
        else:
            if self.ot_proc is not None:
                self.ot_proc = None
            self.ot_btn.configure(text="Запустить opentrack")
            p = h["opentrack_path"]
            if p and os.path.isfile(p.strip().strip('"')):
                self.ot_status.configure(text="opentrack найден, не запущен лаунчером.", foreground="#555")
            else:
                self.ot_status.configure(text="opentrack.exe не найден — установите на вкладке «Установка» "
                                              "или укажите путь.", foreground="#b45309")

    @staticmethod
    def _hat_arrow(h):
        table = {(0, 0): "·", (0, 1): "↑", (0, -1): "↓", (-1, 0): "←", (1, 0): "→",
                 (-1, 1): "↖", (1, 1): "↗", (-1, -1): "↙", (1, -1): "↘"}
        return table.get(tuple(h), str(tuple(h)))

    def on_close(self):
        self._closing = True
        if self.listener:
            self.listener.stop()
        skip = getattr(self, "_skip_save", False)
        if self._wheel_save_t and not skip:
            self.save_global()
        if self.overlay:
            self.overlay.destroy()
        for job in (getattr(self, "_tick_job", None), getattr(self, "_status_job", None)):
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        if self._save_job:
            self.after_cancel(self._save_job)
            self._save_job = None
        if not skip:
            self.save_cfg()
        if self.cfg["head"]["manage_process"]:
            try:
                self.close_opentrack()
            except Exception:  # noqa
                pass
        close_joycpl(self._joycpl_pid)
        self.worker.send("quit")
        self.worker.join(timeout=2.0)
        gc.enable()
        self.tasks.q.put(("", None))
        self.destroy()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == SELFTEST_ARG:
        sys.exit(run_selftest(sys.argv[2]))
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa
            pass
        # один экземпляр лаунчера — иначе будет два виртуальных геймпада
        try:
            import ctypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            global _MUTEX
            _MUTEX = k32.CreateMutexW(None, False, "Local\\X52_AC8_Launcher_single")
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                r = tk.Tk()
                r.withdraw()
                messagebox.showinfo(APP_NAME, "Лаунчер уже запущен — посмотрите на панели задач.")
                return
        except Exception:  # noqa
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
