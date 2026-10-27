# -*- coding: utf-8 -*-
"""Чтение мини-стика X52 как оси обзора (Windows).

На X52/X52 Pro мини-джойстик на РУД прошивкой выставляется как HID-мышь
(VID_06A3): двигает курсор, но в HID-джойстике его нет. Модуль через
WinAPI RawInput подписывается на события мыши, фильтрует их по
device-handle Saitek-мышей и превращает dx/dy в значения осей cam_x /
cam_y в диапазоне [-1, +1]. Движение курсора при этом не блокируется.

На не-Windows и когда X52 не найден — возвращается заглушка, у которой
read() всегда (0.0, 0.0) и ok == False.
"""
import sys
import threading
import time


IS_WIN = sys.platform.startswith("win")
# Все известные VID для X52 / X52 Pro: Saitek, Mad Catz, Logitech-ветки.
# Если у пользователя VID отличается — в x52_error.log дампится список всех
# raw-input устройств, можно потом добавить сюда.
X52_VIDS = ("VID_06A3", "VID_0738", "VID_1BAD", "VID_046D")


def parse_ministick(buf, n):
    """HID-отчёт X52 non-Pro -> (x, y) мини-стика или None, если отчёт короткий.
    byte 14: lo = горизонталь (lo < 8 = влево), hi = вертикаль (hi < 8 = вверх).
    Байты 1..4 — упакованные оси основной ручки, по ним фильтровать нельзя."""
    if n < 15:
        return None
    v = buf[14]
    hi, lo = v >> 4, v & 0x0F
    xv = 0.0 if abs(lo - 8) <= 1 else max(-1.0, min(1.0, (lo - 8) / 7.0))
    yv = 0.0 if abs(hi - 8) <= 1 else max(-1.0, min(1.0, (8 - hi) / 7.0))
    return (xv, yv)


class MiniStickIntegrator(object):
    """dx/dy от HID-мыши -> значения осей в [-1, +1].

    В окне длительности `timeout_ms` накапливаются события; ось =
    clamp(sum * sens / scale). Нет событий дольше окна -> (0, 0).
    """

    def __init__(self, sens=0.5, timeout_ms=80, scale=30.0):
        self.sens = max(0.1, min(5.0, float(sens)))
        self.timeout = max(0.016, float(timeout_ms) / 1000.0)
        self.scale = max(1.0, float(scale))
        self._events = []
        self._lock = threading.Lock()

    def set_sens(self, s):
        self.sens = max(0.1, min(5.0, float(s)))

    def feed(self, dx, dy, now=None):
        now = time.perf_counter() if now is None else now
        with self._lock:
            cutoff = now - self.timeout
            if self._events and self._events[0][0] < cutoff:
                self._events = [e for e in self._events if e[0] >= cutoff]
            self._events.append((now, float(dx), float(dy)))

    def read(self, now=None):
        now = time.perf_counter() if now is None else now
        with self._lock:
            cutoff = now - self.timeout
            if self._events and self._events[0][0] < cutoff:
                self._events = [e for e in self._events if e[0] >= cutoff]
            if not self._events:
                return (0.0, 0.0)
            sx = sum(e[1] for e in self._events)
            sy = sum(e[2] for e in self._events)
            k = self.sens / self.scale
            x = max(-1.0, min(1.0, sx * k))
            y = max(-1.0, min(1.0, sy * k))
            return (x, y)


class _NullReader(object):
    def __init__(self, reason=""):
        self.ok = False
        self.status = reason or "мини-стик недоступен"
        self.device_name = ""
        self.integrator = MiniStickIntegrator()

    def start(self):
        return False

    def stop(self):
        pass

    def read(self, now=None):
        return (0.0, 0.0)

    def set_sens(self, s):
        self.integrator.set_sens(s)


if IS_WIN:
    import ctypes
    from ctypes import wintypes

    WM_INPUT = 0x00FF
    WM_QUIT = 0x0012
    WM_DESTROY = 0x0002
    RID_INPUT = 0x10000003
    RIDI_DEVICENAME = 0x20000007
    RIM_TYPEMOUSE = 0
    RIM_TYPEKEYBOARD = 1
    RIM_TYPEHID = 2
    RIDEV_INPUTSINK = 0x00000100
    RIDEV_REMOVE = 0x00000001
    MOUSE_MOVE_ABSOLUTE = 0x01
    HWND_MESSAGE = -3
    ERROR_CLASS_ALREADY_EXISTS = 1410

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [("usUsagePage", wintypes.USHORT),
                    ("usUsage", wintypes.USHORT),
                    ("dwFlags", wintypes.DWORD),
                    ("hwndTarget", wintypes.HWND)]

    class RAWINPUTDEVICELIST(ctypes.Structure):
        _fields_ = [("hDevice", wintypes.HANDLE),
                    ("dwType", wintypes.DWORD)]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [("dwType", wintypes.DWORD),
                    ("dwSize", wintypes.DWORD),
                    ("hDevice", wintypes.HANDLE),
                    ("wParam", wintypes.WPARAM)]

    class _RAWMOUSE_U_S(ctypes.Structure):
        _fields_ = [("usButtonFlags", wintypes.USHORT),
                    ("usButtonData", wintypes.USHORT)]

    class _RAWMOUSE_U(ctypes.Union):
        _fields_ = [("ulButtons", wintypes.ULONG),
                    ("s", _RAWMOUSE_U_S)]

    class RAWMOUSE(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("usFlags", wintypes.USHORT),
                    ("u", _RAWMOUSE_U),
                    ("ulRawButtons", wintypes.ULONG),
                    ("lLastX", wintypes.LONG),
                    ("lLastY", wintypes.LONG),
                    ("ulExtraInformation", wintypes.ULONG)]

    class RAWINPUT(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER),
                    ("mouse", RAWMOUSE)]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR)]

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt_x", wintypes.LONG),
                    ("pt_y", wintypes.LONG)]

    _TYPE_NAME = {RIM_TYPEMOUSE: "MOUSE", RIM_TYPEKEYBOARD: "KBD", RIM_TYPEHID: "HID"}


    def _enumerate_raw_devices():
        """Вернуть [(hDevice, dwType, name), ...] для всех raw-input устройств."""
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetRawInputDeviceList.argtypes = (
            ctypes.POINTER(RAWINPUTDEVICELIST),
            ctypes.POINTER(wintypes.UINT),
            wintypes.UINT)
        user32.GetRawInputDeviceList.restype = wintypes.UINT
        user32.GetRawInputDeviceInfoW.argtypes = (
            wintypes.HANDLE, wintypes.UINT,
            ctypes.c_void_p, ctypes.POINTER(wintypes.UINT))
        user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
        n = wintypes.UINT(0)
        user32.GetRawInputDeviceList(None, ctypes.byref(n), ctypes.sizeof(RAWINPUTDEVICELIST))
        if not n.value:
            return []
        arr = (RAWINPUTDEVICELIST * n.value)()
        got = user32.GetRawInputDeviceList(arr, ctypes.byref(n), ctypes.sizeof(RAWINPUTDEVICELIST))
        if got == 0xFFFFFFFF:
            return []
        out = []
        for i in range(got):
            size = wintypes.UINT(0)
            user32.GetRawInputDeviceInfoW(arr[i].hDevice, RIDI_DEVICENAME, None, ctypes.byref(size))
            if not size.value or size.value > 2048:
                continue
            buf = ctypes.create_unicode_buffer(size.value)
            r = user32.GetRawInputDeviceInfoW(arr[i].hDevice, RIDI_DEVICENAME, buf, ctypes.byref(size))
            if r == 0xFFFFFFFF:
                continue
            out.append((arr[i].hDevice, arr[i].dwType, buf.value or ""))
        return out


    def _find_x52_mice(all_devs, extra_substr=""):
        """Фильтр: тип = MOUSE или HID, имя содержит один из известных VID
        (или пользовательскую подстроку из extra_substr)."""
        extra = (extra_substr or "").upper().strip()
        hits = []
        for h, t, name in all_devs:
            if t not in (RIM_TYPEMOUSE, RIM_TYPEHID):
                continue
            up = name.upper()
            if any(v in up for v in X52_VIDS) or (extra and extra in up):
                hits.append((h, t, name))
        return hits


    class OVERLAPPED(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p),
                    ("InternalHigh", ctypes.c_void_p),
                    ("Offset", wintypes.DWORD),
                    ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE)]


    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FILE_FLAG_OVERLAPPED = 0x40000000
    ERROR_IO_PENDING = 997
    WAIT_OBJECT_1 = 1
    INFINITE = 0xFFFFFFFF
    INVALID_HANDLE = ctypes.c_void_p(-1).value


    class _WinReader(object):
        """Чтение HID-отчёта X52 non-Pro: byte 14 = нибблы (hi=X, lo=Y),
        центр 8, диапазон 0..F. Нормализуется в [-1, +1] через (n-8)/7."""

        def __init__(self, integrator=None, log_cb=None, device_substring=""):
            self.integrator = integrator          # для API-совместимости
            self.log_cb = log_cb or (lambda _s: None)
            self.device_substring = device_substring or ""
            self.ok = False
            self.status = "не запущен"
            self.device_name = ""
            self.sens = integrator.sens if integrator is not None else 1.0
            self._cur = (0.0, 0.0)
            self._thread = None
            self._hfile = None
            self._stop_event = None
            self._ready = threading.Event()
            self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._setup_api()

        def _setup_api(self):
            k = self._k32
            k.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.HANDLE)
            k.CreateFileW.restype = wintypes.HANDLE
            k.ReadFile.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
            k.ReadFile.restype = wintypes.BOOL
            k.CloseHandle.argtypes = (wintypes.HANDLE,)
            k.CloseHandle.restype = wintypes.BOOL
            k.CancelIoEx.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
            k.CancelIoEx.restype = wintypes.BOOL
            k.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL,
                                       wintypes.BOOL, wintypes.LPCWSTR)
            k.CreateEventW.restype = wintypes.HANDLE
            k.SetEvent.argtypes = (wintypes.HANDLE,)
            k.SetEvent.restype = wintypes.BOOL
            k.ResetEvent.argtypes = (wintypes.HANDLE,)
            k.ResetEvent.restype = wintypes.BOOL
            k.WaitForMultipleObjects.argtypes = (wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.HANDLE),
                                                 wintypes.BOOL, wintypes.DWORD)
            k.WaitForMultipleObjects.restype = wintypes.DWORD
            k.GetOverlappedResult.argtypes = (wintypes.HANDLE, ctypes.c_void_p,
                                              ctypes.POINTER(wintypes.DWORD),
                                              wintypes.BOOL)
            k.GetOverlappedResult.restype = wintypes.BOOL

        def set_sens(self, s):
            self.sens = max(0.1, min(5.0, float(s)))
            if self.integrator is not None:
                self.integrator.set_sens(s)

        def read(self, now=None):
            x, y = self._cur
            s = self.sens
            if s == 1.0:
                return (x, y)
            return (max(-1.0, min(1.0, x * s)), max(-1.0, min(1.0, y * s)))

        def _run(self):
            try:
                devs = _enumerate_raw_devices()
                hits = _find_x52_mice(devs, self.device_substring)
                path = None
                for _h, t, name in hits:
                    if t == RIM_TYPEHID:
                        path = name
                        break
                if not path:
                    self.status = "X52 HID не найден (см. x52_error.log)"
                    dump = ["ministick: raw-input devices:"]
                    for _h, t, name in devs:
                        dump.append("  [%s] %s" % (_TYPE_NAME.get(t, str(t)), name))
                    self.log_cb("\n".join(dump))
                    self._ready.set()
                    return
                self.device_name = path
                self._hfile = self._k32.CreateFileW(
                    path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
                if not self._hfile or self._hfile == INVALID_HANDLE:
                    self.status = "CreateFileW err=%d" % ctypes.get_last_error()
                    self._hfile = None
                    self._ready.set()
                    return
                read_event = self._k32.CreateEventW(None, True, False, None)
                try:
                    ov = OVERLAPPED()
                    ov.hEvent = read_event
                    buf = (ctypes.c_ubyte * 64)()
                    nread = wintypes.DWORD(0)
                    self.ok = True
                    self.status = "работает (X52 non-Pro HID, byte 14 нибблы)"
                    self._ready.set()
                    handles_arr = (wintypes.HANDLE * 2)(read_event, self._stop_event)
                    while True:
                        self._k32.ResetEvent(read_event)
                        r = self._k32.ReadFile(self._hfile, buf, 64,
                                               ctypes.byref(nread), ctypes.byref(ov))
                        if not r:
                            err = ctypes.get_last_error()
                            if err != ERROR_IO_PENDING:
                                self.status = "ReadFile err=%d" % err
                                break
                        w = self._k32.WaitForMultipleObjects(2, handles_arr, False, INFINITE)
                        if w == WAIT_OBJECT_1:
                            self._k32.CancelIoEx(self._hfile, ctypes.byref(ov))
                            break
                        self._k32.GetOverlappedResult(self._hfile, ctypes.byref(ov),
                                                     ctypes.byref(nread), False)
                        p = parse_ministick(buf, nread.value)
                        if p is not None:
                            self._cur = p
                finally:
                    try:
                        self._k32.CloseHandle(read_event)
                    except Exception:   # noqa
                        pass
            except Exception as e:   # noqa
                self.status = "ошибка: %s" % e
                self._ready.set()
            finally:
                self.ok = False
                self._cur = (0.0, 0.0)

        def start(self):
            if self._thread and self._thread.is_alive():
                return self.ok
            self._ready.clear()
            self._stop_event = self._k32.CreateEventW(None, True, False, None)
            self._thread = threading.Thread(target=self._run,
                                            name="x52-ministick-hid", daemon=True)
            self._thread.start()
            self._ready.wait(timeout=2.0)
            return self.ok

        def stop(self):
            if self._stop_event:
                try:
                    self._k32.SetEvent(self._stop_event)
                except Exception:   # noqa
                    pass
            if self._hfile:
                try:
                    self._k32.CancelIoEx(self._hfile, None)
                except Exception:   # noqa
                    pass
            if self._thread:
                self._thread.join(timeout=1.0)
            if self._hfile:
                try:
                    self._k32.CloseHandle(self._hfile)
                except Exception:   # noqa
                    pass
                self._hfile = None
            if self._stop_event:
                try:
                    self._k32.CloseHandle(self._stop_event)
                except Exception:   # noqa
                    pass
                self._stop_event = None
            self.ok = False


if not IS_WIN:
    def dump_x52_hid(log_cb, frames=1000, warmup_s=2.0):
        msg = "hid-diag: диагностика доступна только на Windows"
        log_cb(msg)
        return False, msg


if IS_WIN:
    def dump_x52_hid(log_cb, frames=1000, warmup_s=2.0):
        """Открыть HID-устройство X52 и записать N сырых отчётов в лог
        с паузой warmup_s перед стартом (чтобы пользователь успел положить
        руку на мини-стик). В конце считает min..max для каждого байта
        отчёта — чтобы сразу видно, какие байты реально менялись.

        Возвращает (ok: bool, summary: str) — summary для messagebox."""
        try:
            devs = _enumerate_raw_devices()
        except Exception as e:   # noqa
            msg = "hid-diag: enum error: %s" % e
            log_cb(msg)
            return False, msg
        path = None
        for _h, t, name in devs:
            if t == RIM_TYPEHID and any(v in name.upper() for v in X52_VIDS):
                path = name
                break
        if not path:
            msg = "hid-diag: HID-устройство X52 не найдено"
            log_cb(msg)
            return False, msg

        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        OPEN_EXISTING = 3
        INVALID_HANDLE = ctypes.c_void_p(-1).value

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.HANDLE)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.ReadFile.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
        k32.ReadFile.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.CloseHandle.restype = wintypes.BOOL

        h = k32.CreateFileW(path, GENERIC_READ,
                            FILE_SHARE_READ | FILE_SHARE_WRITE,
                            None, OPEN_EXISTING, 0, None)
        if not h or h == INVALID_HANDLE:
            msg = "hid-diag: CreateFileW err=%d path=%s" % (ctypes.get_last_error(), path)
            log_cb(msg)
            return False, msg

        if warmup_s > 0:
            time.sleep(warmup_s)

        mins = [255] * 64
        maxs = [0] * 64
        rsize = 0
        try:
            lines = ["hid-diag: X52 HID dump, path=%s, frames=%d, warmup=%.1fs"
                     % (path, frames, warmup_s)]
            buf = (ctypes.c_ubyte * 64)()
            nread = wintypes.DWORD(0)
            got = 0
            for i in range(frames):
                r = k32.ReadFile(h, buf, 64, ctypes.byref(nread), None)
                if not r:
                    lines.append("  [%04d] ReadFile err=%d" % (i, ctypes.get_last_error()))
                    break
                n = nread.value
                if n > rsize:
                    rsize = n
                for j in range(n):
                    v = buf[j]
                    if v < mins[j]:
                        mins[j] = v
                    if v > maxs[j]:
                        maxs[j] = v
                hexs = " ".join("%02X" % buf[j] for j in range(n))
                lines.append("  [%04d](n=%d) %s" % (i, n, hexs))
                got += 1
            # сводка: по каждому байту — min, max, change-range
            summ_lines = ["hid-diag SUMMARY (%d кадров, размер отчёта %d байт):" % (got, rsize)]
            for j in range(rsize):
                lo, hi = mins[j], maxs[j]
                delta = hi - lo
                tag = ""
                if delta == 0:
                    tag = "const"
                elif delta <= 2:
                    tag = "шум"
                elif delta >= 32:
                    tag = "АКТИВНО"
                else:
                    tag = "движение"
                summ_lines.append("  byte %02d: %02X..%02X  Δ=%d  %s"
                                  % (j, lo, hi, delta, tag))
            summary = "\n".join(summ_lines)
            lines.append(summary)
            log_cb("\n".join(lines))
            return True, summary
        finally:
            k32.CloseHandle(h)


def make_reader(sens=0.5, timeout_ms=80, log_cb=None, device_substring=""):
    """На Windows создаёт реальный читатель; иначе — заглушку.

    log_cb — функция log_cb(str), сюда пишется список найденных raw-input
    устройств при неудачном автодетекте. device_substring — ручной фильтр
    (подстрока в device name, напр. 'VID_1234'); если задан, идёт поверх
    стандартных VID X52.
    """
    if not IS_WIN:
        return _NullReader("мини-стик X52: только Windows")
    try:
        integ = MiniStickIntegrator(sens=sens, timeout_ms=timeout_ms)
        return _WinReader(integ, log_cb=log_cb, device_substring=device_substring)
    except Exception as e:   # noqa
        return _NullReader("ошибка инициализации: %s" % e)
