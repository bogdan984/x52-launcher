# -*- coding: utf-8 -*-
"""
Ядро X52 AC8 Launcher 3.0 (без интерфейса и без pygame — чтобы всё можно было проверить тестами).

  * список действий игры (как в меню «Назначение клавиш» ACE COMBAT 8);
  * у каждого действия ДВЕ привязки X52 (основная/дополнительная): кнопка, хатка или
    направление ЛЮБОЙ оси (ручка, РУД, крутилки, слайдер, мини-стик) с порогом;
  * выход каждого действия — виртуальный геймпад Xbox 360 ИЛИ клавиша клавиатуры/мыши;
  * настраиваемый отклик ручки: мёртвая зона, компенсация мёртвой зоны игры,
    чувствительность, кривая, сглаживание (задержка);
  * рыскание (поворот рукояти): порог, удержание или импульсы пропорционально отклонению,
    задержка нажатия, сглаживание.
"""

import math
import os
import re
import time

IS_WIN = os.name == "nt"
DEFAULT_APPID = "2288340"  # ACE COMBAT 8: WINGS OF THEVE в Steam

# ----------------------------------------------------------------------
# Клавиши: имя -> (scan-код set 1, extended)
# Отправляются scan-кодами, поэтому раскладка (рус/англ) не важна.
# ----------------------------------------------------------------------
KEYS = {
    "ESC": (0x01, False), "1": (0x02, False), "2": (0x03, False), "3": (0x04, False),
    "4": (0x05, False), "5": (0x06, False), "6": (0x07, False), "7": (0x08, False),
    "8": (0x09, False), "9": (0x0A, False), "0": (0x0B, False), "MINUS": (0x0C, False),
    "EQUALS": (0x0D, False), "BACKSPACE": (0x0E, False), "TAB": (0x0F, False),
    "Q": (0x10, False), "W": (0x11, False), "E": (0x12, False), "R": (0x13, False),
    "T": (0x14, False), "Y": (0x15, False), "U": (0x16, False), "I": (0x17, False),
    "O": (0x18, False), "P": (0x19, False), "LBRACKET": (0x1A, False), "RBRACKET": (0x1B, False),
    "ENTER": (0x1C, False), "LCTRL": (0x1D, False), "A": (0x1E, False), "S": (0x1F, False),
    "D": (0x20, False), "F": (0x21, False), "G": (0x22, False), "H": (0x23, False),
    "J": (0x24, False), "K": (0x25, False), "L": (0x26, False), "SEMICOLON": (0x27, False),
    "APOSTROPHE": (0x28, False), "GRAVE": (0x29, False), "LSHIFT": (0x2A, False),
    "BACKSLASH": (0x2B, False), "Z": (0x2C, False), "X": (0x2D, False), "C": (0x2E, False),
    "V": (0x2F, False), "B": (0x30, False), "N": (0x31, False), "M": (0x32, False),
    "COMMA": (0x33, False), "PERIOD": (0x34, False), "SLASH": (0x35, False),
    "RSHIFT": (0x36, False), "NUM_MUL": (0x37, False), "LALT": (0x38, False),
    "SPACE": (0x39, False), "CAPSLOCK": (0x3A, False),
    "F1": (0x3B, False), "F2": (0x3C, False), "F3": (0x3D, False), "F4": (0x3E, False),
    "F5": (0x3F, False), "F6": (0x40, False), "F7": (0x41, False), "F8": (0x42, False),
    "F9": (0x43, False), "F10": (0x44, False), "F11": (0x57, False), "F12": (0x58, False),
    "NUM7": (0x47, False), "NUM8": (0x48, False), "NUM9": (0x49, False), "NUM_SUB": (0x4A, False),
    "NUM4": (0x4B, False), "NUM5": (0x4C, False), "NUM6": (0x4D, False), "NUM_ADD": (0x4E, False),
    "NUM1": (0x4F, False), "NUM2": (0x50, False), "NUM3": (0x51, False), "NUM0": (0x52, False),
    "NUM_DEC": (0x53, False),
    "RCTRL": (0x1D, True), "RALT": (0x38, True), "NUM_ENTER": (0x1C, True), "NUM_DIV": (0x35, True),
    "HOME": (0x47, True), "UP": (0x48, True), "PGUP": (0x49, True), "LEFT": (0x4B, True),
    "RIGHT": (0x4D, True), "END": (0x4F, True), "DOWN": (0x50, True), "PGDN": (0x51, True),
    "INSERT": (0x52, True), "DELETE": (0x53, True),
    # как в RS Mapper: Print Screen, Scroll Lock, Num Lock, Pause, Windows, «\» слева от Z
    "PRINTSCREEN": (0x37, True), "SCROLLLOCK": (0x46, False), "NUMLOCK": (0x45, True), "PAUSE": (0x45, False),
    "LWIN": (0x5B, True), "RWIN": (0x5C, True), "APPS": (0x5D, True), "OEM102": (0x56, False),
    "F13": (0x64, False), "F14": (0x65, False), "F15": (0x66, False), "F16": (0x67, False),
    "F17": (0x68, False), "F18": (0x69, False), "F19": (0x6A, False), "F20": (0x6B, False),
    "F21": (0x6C, False), "F22": (0x6D, False), "F23": (0x6E, False), "F24": (0x76, False),
}
MOUSE_KEYS = ("MOUSE_LEFT", "MOUSE_RIGHT", "MOUSE_MIDDLE", "MOUSE_X1", "MOUSE_X2")
# порядок в списках — как в RS Mapper: буквы, цифры, знаки, цифровой блок, F-клавиши, служебные, стрелки
KEY_ORDER = (list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + list("0123456789") +
             ["GRAVE", "MINUS", "EQUALS", "LBRACKET", "RBRACKET", "SEMICOLON", "APOSTROPHE", "BACKSLASH",
              "OEM102", "COMMA", "PERIOD", "SLASH"] +
             ["NUM%d" % _i for _i in range(10)] + ["NUM_DIV", "NUM_MUL", "NUM_SUB", "NUM_ADD", "NUM_ENTER",
                                                   "NUM_DEC"] +
             ["F%d" % _i for _i in range(1, 25)] +
             ["ESC", "PRINTSCREEN", "SCROLLLOCK", "PAUSE", "BACKSPACE", "NUMLOCK", "TAB", "ENTER", "CAPSLOCK",
              "LSHIFT", "RSHIFT", "LCTRL", "RCTRL", "SPACE", "LALT", "RALT", "LWIN", "RWIN", "APPS",
              "INSERT", "HOME", "PGUP", "DELETE", "END", "PGDN", "UP", "DOWN", "LEFT", "RIGHT"])
assert sorted(KEY_ORDER) == sorted(KEYS), "KEY_ORDER должен содержать все клавиши"
ALL_KEYS = KEY_ORDER + list(MOUSE_KEYS)

_RU = dict(zip("QWERTYUIOPASDFGHJKLZXCVBNM", "ЙЦУКЕНГШЩЗФЫВАПРОЛДЯЧСМИТЬ"))
# знаки — самим символом, в скобках — что на этой клавише в русской раскладке
_SYM = {"LBRACKET": "[ (Х)", "RBRACKET": "] (Ъ)", "SEMICOLON": "; (Ж)", "APOSTROPHE": "' (Э)",
        "COMMA": ", (Б)", "PERIOD": ". (Ю)", "GRAVE": "` (Ё)", "SLASH": "/ (.)", "MINUS": "-", "EQUALS": "=",
        "BACKSLASH": "\\ (правый)", "OEM102": "\\ (левый, у Z)"}
_KEY_TEXT = {
    "ESC": "Esc", "MINUS": "-", "EQUALS": "=", "BACKSPACE": "Backspace", "TAB": "Tab",
    "LBRACKET": "[", "RBRACKET": "]", "ENTER": "Enter", "LCTRL": "Ctrl (лев.)", "RCTRL": "Ctrl (прав.)",
    "SEMICOLON": ";", "APOSTROPHE": "'", "GRAVE": "`", "LSHIFT": "Shift (лев.)",
    "RSHIFT": "Shift (прав.)", "BACKSLASH": "\\", "COMMA": ",", "PERIOD": ".", "SLASH": "/",
    "NUM_MUL": "Num *", "LALT": "Alt (лев.)", "RALT": "Alt (прав.)", "SPACE": "Пробел",
    "CAPSLOCK": "CapsLock", "NUM_SUB": "Num -", "NUM_ADD": "Num +", "NUM_DEC": "Num .",
    "NUM_ENTER": "Num Enter", "NUM_DIV": "Num /", "HOME": "Home", "END": "End", "PGUP": "PgUp",
    "PGDN": "PgDn", "INSERT": "Insert", "DELETE": "Delete",
    "PRINTSCREEN": "Print Screen", "SCROLLLOCK": "Scroll Lock", "NUMLOCK": "Num Lock", "PAUSE": "Pause",
    "LWIN": "Windows (лев.)", "RWIN": "Windows (прав.)", "APPS": "Меню (Apps)",
    "UP": "Стрелка ↑", "DOWN": "Стрелка ↓", "LEFT": "Стрелка ←", "RIGHT": "Стрелка →",
    "MOUSE_LEFT": "Мышь: левая", "MOUSE_RIGHT": "Мышь: правая", "MOUSE_MIDDLE": "Мышь: средняя",
    "MOUSE_X1": "Мышь: X1 (назад)", "MOUSE_X2": "Мышь: X2 (вперёд)",
}
for _i in range(10):
    _KEY_TEXT["NUM%d" % _i] = "Num %d" % _i


def key_text(k):
    if k in _SYM:
        return _SYM[k]
    if k in _RU:
        return "%s (%s)" % (k, _RU[k])
    return _KEY_TEXT.get(k, k)


def keys_text(keys):
    return " + ".join(key_text(k) for k in keys) if keys else "—"


# Windows Virtual-Key -> имя (для захвата клавиши с клавиатуры ПК в окне лаунчера)
VK_TO_KEY = {0x1B: "ESC", 0x09: "TAB", 0x0D: "ENTER", 0x20: "SPACE", 0x08: "BACKSPACE",
             0x14: "CAPSLOCK", 0x21: "PGUP", 0x22: "PGDN", 0x23: "END", 0x24: "HOME",
             0x25: "LEFT", 0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN", 0x2D: "INSERT", 0x2E: "DELETE",
             0x6A: "NUM_MUL", 0x6B: "NUM_ADD", 0x6D: "NUM_SUB", 0x6E: "NUM_DEC", 0x6F: "NUM_DIV",
             0xBA: "SEMICOLON", 0xBB: "EQUALS", 0xBC: "COMMA", 0xBD: "MINUS", 0xBE: "PERIOD",
             0xBF: "SLASH", 0xC0: "GRAVE", 0xDB: "LBRACKET", 0xDC: "BACKSLASH", 0xDD: "RBRACKET",
             0xDE: "APOSTROPHE", 0xA0: "LSHIFT", 0xA1: "RSHIFT", 0xA2: "LCTRL", 0xA3: "RCTRL",
             0xA4: "LALT", 0xA5: "RALT", 0x2C: "PRINTSCREEN", 0x91: "SCROLLLOCK", 0x90: "NUMLOCK",
             0x13: "PAUSE", 0x5B: "LWIN", 0x5C: "RWIN", 0x5D: "APPS", 0xE2: "OEM102"}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    VK_TO_KEY[ord(_c)] = _c
for _i in range(10):
    VK_TO_KEY[0x60 + _i] = "NUM%d" % _i
for _i in range(24):
    VK_TO_KEY[0x70 + _i] = "F%d" % (_i + 1)

# Tk keysym -> имя (модификаторы различаются только по keysym; запасной путь вне Windows)
KEYSYM_TO_KEY = {"Escape": "ESC", "Tab": "TAB", "Return": "ENTER", "space": "SPACE",
                 "BackSpace": "BACKSPACE", "Caps_Lock": "CAPSLOCK", "Prior": "PGUP", "Next": "PGDN",
                 "End": "END", "Home": "HOME", "Left": "LEFT", "Up": "UP", "Right": "RIGHT",
                 "Down": "DOWN", "Insert": "INSERT", "Delete": "DELETE", "Shift_L": "LSHIFT",
                 "Shift_R": "RSHIFT", "Control_L": "LCTRL", "Control_R": "RCTRL", "Alt_L": "LALT",
                 "Alt_R": "RALT", "KP_Enter": "NUM_ENTER", "KP_Multiply": "NUM_MUL", "KP_Add": "NUM_ADD",
                 "KP_Subtract": "NUM_SUB", "KP_Decimal": "NUM_DEC", "KP_Divide": "NUM_DIV",
                 "minus": "MINUS", "equal": "EQUALS", "bracketleft": "LBRACKET",
                 "bracketright": "RBRACKET", "semicolon": "SEMICOLON", "apostrophe": "APOSTROPHE",
                 "grave": "GRAVE", "backslash": "BACKSLASH", "comma": "COMMA", "period": "PERIOD",
                 "slash": "SLASH"}
for _i in range(10):
    KEYSYM_TO_KEY["KP_%d" % _i] = "NUM%d" % _i
for _i in range(24):
    KEYSYM_TO_KEY["F%d" % (_i + 1)] = "F%d" % (_i + 1)
KEYSYM_TO_KEY.update({"Print": "PRINTSCREEN", "Scroll_Lock": "SCROLLLOCK", "Num_Lock": "NUMLOCK",
                      "Pause": "PAUSE", "Win_L": "LWIN", "Win_R": "RWIN", "Super_L": "LWIN", "Super_R": "RWIN",
                      "App": "APPS", "Menu": "APPS", "less": "OEM102"})
_CYR_KEYSYM = {"Cyrillic_" + n: k for n, k in (
    ("shorti", "Q"), ("tse", "W"), ("u", "E"), ("ka", "R"), ("ie", "T"), ("en", "Y"), ("ghe", "U"),
    ("sha", "I"), ("shcha", "O"), ("ze", "P"), ("ef", "A"), ("yeru", "S"), ("ve", "D"), ("a", "F"),
    ("pe", "G"), ("er", "H"), ("o", "J"), ("el", "K"), ("de", "L"), ("ya", "Z"), ("che", "X"),
    ("es", "C"), ("em", "V"), ("i", "B"), ("te", "N"), ("softsign", "M"), ("ha", "LBRACKET"),
    ("hardsign", "RBRACKET"), ("zhe", "SEMICOLON"), ("e", "APOSTROPHE"), ("be", "COMMA"),
    ("yu", "PERIOD"), ("io", "GRAVE"))}
for _k, _v in list(_CYR_KEYSYM.items()):   # заглавные: Cyrillic_TSE и т.п.
    _CYR_KEYSYM["Cyrillic_" + _k[len("Cyrillic_"):].upper()] = _v
KEYSYM_TO_KEY.update(_CYR_KEYSYM)

# keysym, которым нельзя верить по VK (Windows отдаёт одинаковый VK для левого и правого)
_SIDE_KEYSYMS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "KP_Enter"}


def key_from_tk_event(keysym, keycode, is_win=IS_WIN):
    """Имя клавиши по событию Tk. На Windows keycode = Virtual-Key (не зависит от раскладки)."""
    if keysym in _SIDE_KEYSYMS:
        return KEYSYM_TO_KEY[keysym]
    if is_win and keycode in VK_TO_KEY:
        return VK_TO_KEY[keycode]
    if keysym in KEYSYM_TO_KEY:
        return KEYSYM_TO_KEY[keysym]
    if isinstance(keysym, str) and len(keysym) == 1 and keysym.upper() in KEYS:
        return keysym.upper()
    return None


# ----------------------------------------------------------------------
# Действия: (id, категория, название, выходы геймпада или None, клавиши по умолчанию, выход по умолчанию)
# Выходы геймпада: A B X Y LB RB LS RS BACK START DPAD_* LT RT
#   CAM_* (правый стик), LSTICK_* (левый стик); CENTER и TOGGLE_HEAD — команды лаунчера.
# Клавиши по умолчанию — как на скриншотах «Назначение клавиш» игры (рус. раскладка показана в скобках).
# ----------------------------------------------------------------------
ACTIONS = [
    # Полёт
    ("pitch_up", "Полёт", "Нос вверх / набор высоты", ["LSTICK_DOWN"], ["S"], "key"),
    ("pitch_down", "Полёт", "Нос вниз / сброс высоты", ["LSTICK_UP"], ["W"], "key"),
    ("roll_left", "Полёт", "Поворот / крен влево", ["LSTICK_LEFT"], ["A"], "key"),
    ("roll_right", "Полёт", "Поворот / крен вправо", ["LSTICK_RIGHT"], ["D"], "key"),
    ("yaw_left", "Полёт", "Рыскание влево", ["LB"], ["Q"], "pad"),
    ("yaw_right", "Полёт", "Рыскание вправо", ["RB"], ["E"], "pad"),
    ("throttle_up", "Полёт", "Прибавить тягу (полный газ)", ["RT"], ["SPACE"], "pad"),
    ("throttle_down", "Полёт", "Убавить тягу (полный тормоз)", ["LT"], ["LCTRL"], "pad"),
    ("highg", "Полёт", "High-G разворот (газ + тормоз)", ["LT", "RT"], ["SPACE", "LCTRL"], "pad"),
    ("autopilot", "Полёт", "Автопилот", ["LB", "RB"], ["Z"], "pad"),
    ("gear", "Полёт", "Выпустить / убрать шасси", None, ["R"], "key"),
    # Оружие
    ("gun", "Оружие", "Выстрел из пулемёта (в меню — Подтвердить)", ["A"], ["J"], "pad"),
    ("missile", "Оружие", "Пуск ракеты / выстрел (в меню — Назад)", ["B"], ["L"], "pad"),
    ("next_weapon", "Оружие", "Следующее оружие", ["X"], ["K"], "pad"),
    ("prev_weapon", "Оружие", "Сменить оружие / предыдущее оружие", None, ["I"], "key"),
    ("std_missile", "Оружие", "Обычные ракеты", None, ["1"], "key"),
    ("special1", "Оружие", "Особое вооружение 1", None, ["2"], "key"),
    ("special2", "Оружие", "Особое вооружение 2", None, ["3"], "key"),
    ("target", "Оружие", "Сменить цель", ["Y"], ["T"], "pad"),
    ("flare", "Оружие", "Выпустить тепловые ловушки", ["LS", "RS"], ["X"], "pad"),
    # Обзор
    ("view", "Обзор", "Сменить ракурс", ["RS"], ["V"], "pad"),
    ("cam_mouse", "Обзор", "Управление камерой (мышь)", None, ["F"], "key"),
    ("cam_up", "Обзор", "Поднять камеру", ["CAM_UP"], ["7"], "pad"),
    ("cam_down", "Обзор", "Опустить камеру", ["CAM_DOWN"], ["8"], "pad"),
    ("cam_left", "Обзор", "Повернуть камеру влево", ["CAM_LEFT"], ["9"], "pad"),
    ("cam_right", "Обзор", "Повернуть камеру вправо", ["CAM_RIGHT"], ["0"], "pad"),
    # Ведомые
    ("order_attack", "Ведомые", "Приказ: лобовая атака", ["DPAD_UP"], ["UP"], "pad"),
    ("order_cover", "Ведомые", "Приказ: прикрытие", ["DPAD_DOWN"], ["DOWN"], "pad"),
    ("order_disperse", "Ведомые", "Приказ: рассредоточенная атака", ["DPAD_LEFT"], ["LEFT"], "pad"),
    ("order_sp", "Ведомые", "Приказ: вкл./откл. особое вооружение", ["DPAD_RIGHT"], ["RIGHT"], "pad"),
    # Интерфейс
    ("map", "Интерфейс", "Переключить карту радара", ["BACK"], ["M"], "pad"),
    ("pause", "Интерфейс", "Пауза / меню", ["START"], ["ESC"], "pad"),
    ("boresight", "Интерфейс", "Нажатие левого стика (L3)", ["LS"], [], "pad"),
    # Меню
    ("menu_up", "Меню", "Меню: вверх", ["LSTICK_UP"], ["UP"], "pad"),
    ("menu_down", "Меню", "Меню: вниз", ["LSTICK_DOWN"], ["DOWN"], "pad"),
    ("menu_left", "Меню", "Меню: влево", ["LSTICK_LEFT"], ["LEFT"], "pad"),
    ("menu_right", "Меню", "Меню: вправо", ["LSTICK_RIGHT"], ["RIGHT"], "pad"),
    ("menu_ok", "Меню", "Меню: подтвердить", ["A"], ["ENTER"], "pad"),
    ("menu_back", "Меню", "Меню: назад", ["B"], ["ESC"], "pad"),
    # Команды лаунчера
    ("center_view", "Лаунчер", "Центровка обзора (голова / «мышь»)", ["CENTER"], [], "pad"),
    ("toggle_head", "Лаунчер", "Вкл/выкл обзор головой (opentrack)", ["TOGGLE_HEAD"], [], "pad"),
]
CATEGORIES = ["Полёт", "Оружие", "Обзор", "Ведомые", "Интерфейс", "Меню", "Лаунчер"]
ACTION_IDS = [a[0] for a in ACTIONS]
ACTION_LABEL = {a[0]: a[2] for a in ACTIONS}
ACTION_PAD = {a[0]: a[3] for a in ACTIONS}
ACTION_KEYS = {a[0]: a[4] for a in ACTIONS}
ACTION_VIA = {a[0]: a[5] for a in ACTIONS}
INTERNAL = {"CENTER", "TOGGLE_HEAD"}
INTERNAL_ACTIONS = {aid for aid, outs in ACTION_PAD.items() if outs and set(outs) & INTERNAL}
PAD_BUTTONS = ("A", "B", "X", "Y", "LB", "RB", "LS", "RS", "BACK", "START",
               "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")

TOKEN_TEXT = {
    "DPAD_UP": "D-pad ↑", "DPAD_DOWN": "D-pad ↓", "DPAD_LEFT": "D-pad ←", "DPAD_RIGHT": "D-pad →",
    "CAM_UP": "Прав. стик ↑", "CAM_DOWN": "Прав. стик ↓", "CAM_LEFT": "Прав. стик ←", "CAM_RIGHT": "Прав. стик →",
    "LSTICK_UP": "Лев. стик ↑", "LSTICK_DOWN": "Лев. стик ↓", "LSTICK_LEFT": "Лев. стик ←",
    "LSTICK_RIGHT": "Лев. стик →", "LS": "LS (нажатие)", "RS": "RS (нажатие)",
    "BACK": "View/Back", "START": "Menu/Start", "CENTER": "команда лаунчера", "TOGGLE_HEAD": "команда лаунчера",
}
ARROW = {"up": "↑", "down": "↓", "left": "←", "right": "→",
         # точные 8 направлений (как в RSMapper): срабатывают только в своём положении хатки
         "n": "↑", "ne": "↗", "e": "→", "se": "↘", "s": "↓", "sw": "↙", "w": "←", "nw": "↖"}
HAT8 = {"n": (0, 1), "ne": (1, 1), "e": (1, 0), "se": (1, -1), "s": (0, -1), "sw": (-1, -1),
        "w": (-1, 0), "nw": (-1, 1)}
HAT8_ORDER = ["nw", "n", "ne", "w", None, "e", "sw", "s", "se"]     # сетка 3×3 плитки хатки
HAT8_NAME = {"n": "N", "ne": "NE", "e": "E", "se": "SE", "s": "S", "sw": "SW", "w": "W", "nw": "NW"}
MODIFIER_KEYS = ["LCTRL", "LSHIFT", "LALT", "RCTRL", "RSHIFT", "RALT"]

AXIS_ROLES = [
    ("roll", "Крен (ручка влево-вправо)"),
    ("pitch", "Тангаж (ручка вперёд-назад)"),
    ("yaw", "Рыскание (поворот рукояти)"),
    ("throttle", "РУД (газ / тормоз)"),
    ("cam_x", "Обзор X (мини-стик, необяз.)"),
    ("cam_y", "Обзор Y (мини-стик, необяз.)"),
]
CAL_ROWS = [
    ("raw_aft", "Полностью назад"),
    ("raw_forward", "Полностью вперёд"),
    ("neutral_low_raw", "Нейтраль — задняя граница"),
    ("neutral_high_raw", "Нейтраль — передняя граница"),
]
HEAD_SCALES = [
    ("yaw_full", "Поворот головы для полного обзора, °", 10, 150, 1),
    ("pitch_full", "Наклон головы для полного обзора, °", 3, 60, 1),
    ("deadzone", "Мёртвая зона, °", 0, 10, 0.5),
    ("yaw_exp", "Кривая влево/вправо (1 = линейно)", 0.5, 3.0, 0.1),
    ("pitch_exp", "Кривая вверх/вниз (1 = линейно)", 0.5, 3.0, 0.1),
    ("smoothing_ms", "Сглаживание, мс (0 = выкл.)", 0, 300, 5),
    ("max_stick", "Максимальное отклонение стика", 0.2, 1.0, 0.05),
]

# Отклик ручки (крен/тангаж): ключ, подпись, мин, макс, шаг
STICK_PARAMS = [
    ("deadzone", "Мёртвая зона X52", 0.0, 0.30, 0.01),
    ("anti_deadzone", "Компенсация мёртвой зоны игры", 0.0, 0.40, 0.01),
    ("sensitivity", "Чувствительность (усиление)", 0.5, 3.0, 0.05),
    ("curve", "Кривая (1 = линейно, <1 — резче в центре)", 0.3, 3.0, 0.05),
    ("smoothing_ms", "Сглаживание / задержка, мс (0 = нет)", 0, 200, 1),
]
YAW_PARAMS = [
    ("threshold", "Порог срабатывания", 0.03, 0.90, 0.01),
    ("full", "Отклонение для непрерывного нажатия", 0.10, 1.00, 0.01),
    ("period_ms", "Период импульсов, мс", 30, 400, 5),
    ("min_pulse_ms", "Мин. длительность импульса, мс", 10, 100, 1),
    ("delay_ms", "Задержка нажатия, мс (0 = сразу)", 0, 300, 1),
    ("smoothing_ms", "Сглаживание, мс (0 = нет)", 0, 200, 1),
]
STICK_PRESETS = {
    "smooth": {"deadzone": 0.05, "anti_deadzone": 0.0, "sensitivity": 1.0, "curve": 1.4, "smoothing_ms": 40},
    "standard": {"deadzone": 0.04, "anti_deadzone": 0.10, "sensitivity": 1.15, "curve": 1.0, "smoothing_ms": 0},
    "fast": {"deadzone": 0.03, "anti_deadzone": 0.20, "sensitivity": 1.35, "curve": 0.85, "smoothing_ms": 0},
}
AXIS_BIND_HYST = 0.04   # гистерезис для привязок «ось как кнопка»


DEFAULT_PROFILE = "ACE COMBAT 8"
CUSTOM_PREFIX = "custom:"
CUSTOM_MODES = {"hold": "удерживать", "toggle": "переключатель", "sequence": "последовательность",
                "repeat": "автоповтор", "profile": "смена профиля", "tap": "одно нажатие",
                "camera": "обзор DCS"}
# Обзор DCS из своих действий: правый стик виртуального геймпада (в DCS — оси «… (абсолют)»)
DCS_CAM = (
    ("left", "Камера в кабине, горизонталь (абсолют) — влево", "CAM_LEFT"),
    ("right", "Камера в кабине, горизонталь (абсолют) — вправо", "CAM_RIGHT"),
    ("up", "Камера в кабине, вертикаль (абсолют) — вверх", "CAM_UP"),
    ("down", "Камера в кабине, вертикаль (абсолют) — вниз", "CAM_DOWN"),
    ("center", "Центровка обзора (для режима «как мышь»)", "CENTER"),
)
DCS_CAM_LABEL = {k: t for k, t, _p in DCS_CAM}
DCS_CAM_PAD = {k: p for k, _t, p in DCS_CAM}
CUSTOM_TRIGGERS = {"press": "обычное нажатие", "short": "короткое нажатие", "long": "долгое нажатие",
                   "release": "отпускание"}
PROFILE_KINDS = ("name", "cycle", "next", "prev")
LAYER_NAMES = {0: "все слои", 1: "слой 1", 2: "слой 2", 3: "слой 3"}
TAP_MS = 60            # длительность «тапа» клавиши для короткого нажатия
TAP_GAP_MS = 30        # пауза между тапами из очереди (игра должна увидеть отпускание модификаторов)
MAX_STEPS = 50
SEQ_MAX_DELAY_MS = 300000   # шаг последовательности может начаться до 5 мин от нажатия
MAX_CUSTOM = 200
_BAD_NAME = re.compile('[<>:"/\\\\|?*\\x00-\\x1f]')   # символы, запрещённые в именах файлов Windows


def clean_profile_name(name):
    """Имя профиля, пригодное и для показа, и для имени файла."""
    name = _BAD_NAME.sub("_", str(name or "")).strip().strip(".")
    return name[:60] or DEFAULT_PROFILE


# Готовые профили игр, которые сами видят X52: шаблон 'custom' + программы для автопереключения.
GAME_TEMPLATES = {
    "dcs": ("DCS World", ["DCS.exe", "DCS_mt.exe"]),
    "wt": ("War Thunder", ["aces.exe"]),
    "il2": ("IL-2 Sturmovik", ["Il-2.exe"]),
}


def new_profile_config(name, template, base=None):
    """Новый профиль. template: 'ac8' — действия ACE COMBAT 8 и виртуальный геймпад;
    'custom' — только свои клавиши, без геймпада (War Thunder и др.);
    ключ GAME_TEMPLATES — как 'custom', плюс exe игры для автопереключения.
    Из base берутся устройство, назначение и инверсия осей (тот же X52)."""
    d = default_config()
    d["profile_name"] = clean_profile_name(name)
    if template == "custom" or template in GAME_TEMPLATES:
        d["game"] = {"builtin_actions": False, "virtual_pad": False, "launch_type": "none", "exe_path": ""}
        d["launcher"]["steam_appid"] = ""
    if template in GAME_TEMPLATES:
        d["auto"]["processes"] = list(GAME_TEMPLATES[template][1])
    if base:
        d["device_name"] = base.get("device_name", "")
        d["axes"] = dict(base.get("axes", d["axes"]))
        d["invert"] = dict(base.get("invert", d["invert"]))
    return sanitize_config(d)


def clean_steps(raw):
    steps = []
    for st in (raw if isinstance(raw, list) else [])[:MAX_STEPS]:
        if not isinstance(st, dict):
            continue
        sk = st.get("keys") if isinstance(st.get("keys"), list) else []
        sk = [k for i, k in enumerate(sk) if isinstance(k, str) and k in ALL_KEYS and k not in sk[:i]][:3]
        if not sk:
            continue
        stp = {"keys": sk, "delay_ms": int(_num(st.get("delay_ms"), 0, 0, SEQ_MAX_DELAY_MS)),
               "duration_ms": int(_num(st.get("duration_ms"), 100, 10, 10000))}
        if isinstance(st.get("name"), str) and st["name"].strip():
            stp["name"] = st["name"].strip()[:40]
        steps.append(stp)
    steps.sort(key=lambda st: st["delay_ms"])
    return steps


def action_steps(cfg, ca):
    """Шаги последовательности: из библиотеки профиля (по имени), иначе свои."""
    nm = ca.get("seq")
    if nm:
        for sq in cfg.get("sequences", []):
            if sq["name"] == nm:
                return sq["steps"]
    return ca["steps"]


def default_layers():
    # колесо режимов X52: положения 1/2/3 — обычно кнопки 24/25/26 (проверьте на «Главной»)
    return {"enabled": False, "buttons": [{"type": "button", "index": i} for i in (23, 24, 25)]}


def sequence_length_ms(steps):
    return max([st["delay_ms"] + st["duration_ms"] for st in steps] or [0])


def custom_out_text(ca, layers_enabled=True):
    if ca["mode"] == "profile":
        pt = ca["profile"]
        t = {"name": "Профиль: «%s»" % (pt["names"][0] if pt["names"] else "?"),
             "cycle": "Профили по кругу: " + " → ".join(pt["names"] or ["?"]),
             "next": "Следующий профиль", "prev": "Предыдущий профиль"}[pt["kind"]]
    elif ca["mode"] == "camera":
        t = "Обзор DCS: " + DCS_CAM_LABEL.get(ca.get("cam"), "?")
    elif ca["mode"] == "sequence" and ca.get("seq"):
        t = "Последовательность «%s»" % ca["seq"]
    elif ca["mode"] == "sequence":
        n = len(ca["steps"])
        t = "Последовательность: %d шаг%s, %.1f с" % (
            n, "" if n == 1 else ("а" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "ов"),
            sequence_length_ms(ca["steps"]) / 1000.0)
    else:
        t = "Клавиатура: " + keys_text(ca["keys"])
        if ca["mode"] == "toggle":
            t += " · переключатель"
        elif ca["mode"] == "repeat":
            t += " · повтор %d мс" % ca["repeat_ms"]
        elif ca["mode"] == "tap":
            t += " · одно нажатие"
    if ca["trigger"] != "press":
        t += " · " + {"short": "короткое", "long": "долгое", "release": "отпускание"}[ca["trigger"]]
    if layers_enabled and ca["layer"]:
        t += " · слой %d" % ca["layer"]
    return t


_CLASH = {frozenset(["press"]), frozenset(["short"]), frozenset(["long"]), frozenset(["release"]),
          frozenset(["press", "short"]), frozenset(["press", "long"])}


def _triggers_clash(a, b):
    """Срабатывают ли два действия на одном входе одновременно.
    Не конфликт: короткое+долгое, нажатие+отпускание, долгое+отпускание, короткое+отпускание
    (как в RS Mapper: «нажатие» при включённом «долгом» — короткое, и рядом может быть «отпускание»)."""
    return frozenset([a, b]) in _CLASH


def conflicting_actions(cfg):
    """Действия, у которых одинаковый вход X52 срабатывает одновременно (с учётом слоёв и
    короткого/долгого нажатия). Короткое и долгое на одной кнопке — не конфликт."""
    layers_on = cfg["layers"]["enabled"]
    items = []
    for aid in all_action_ids(cfg):
        ca = find_custom(cfg, aid)
        trig = ca["trigger"] if ca else "press"
        layer = ca["layer"] if (ca and layers_on) else 0
        for b in action_pair(cfg, aid):
            k = binding_key(b)
            if k:
                items.append((aid, k, trig, layer))
    bad = set()
    for i, (a1, k1, t1, l1) in enumerate(items):
        for a2, k2, t2, l2 in items[i + 1:]:
            if a1 != a2 and k1 == k2 and _triggers_clash(t1, t2) and (l1 == 0 or l2 == 0 or l1 == l2):
                bad.update((a1, a2))
    return bad


def _norm_list(v, limit=40):
    if isinstance(v, str):
        v = re.split(r"[,;\n]+", v)
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        x = str(x).strip()[:80] if isinstance(x, (str, int)) else ""
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out[:limit]


def choose_profile(rules, process=None, aircraft=None):
    """rules: {имя профиля: {"processes": [...], "aircraft": [...]}}.
    Самолёт DCS важнее программы. Возвращает имя профиля или None."""
    if aircraft:
        a = aircraft.strip().lower()
        for name, r in rules.items():
            if any(a == x.lower() for x in r.get("aircraft", [])):
                return name
    if process:
        p = os.path.basename(process.replace("\\", "/")).lower()
        for name, r in rules.items():
            for x in r.get("processes", []):
                x = x.lower()
                if p == x or (not x.endswith(".exe") and p == x + ".exe"):
                    return name
    return None


def analog_axis(cfg, role):
    """Номер оси X52 для аналоговой роли или None (не назначена или выключена галочкой)."""
    if not cfg.get("axes_enabled", {}).get(role, True):
        return None
    return cfg["axes"].get(role)


def custom_aid(ca):
    return CUSTOM_PREFIX + ca["id"]


def find_custom(cfg, aid):
    if not isinstance(aid, str) or not aid.startswith(CUSTOM_PREFIX):
        return None
    cid = aid[len(CUSTOM_PREFIX):]
    return next((ca for ca in cfg["custom_actions"] if ca["id"] == cid), None)


def new_custom_id(cfg):
    used = {ca["id"] for ca in cfg["custom_actions"]}
    i = 1
    while "c%d" % i in used:
        i += 1
    return "c%d" % i


def action_label(cfg, aid):
    ca = find_custom(cfg, aid)
    if ca is not None:
        return ca["name"]
    return ACTION_LABEL.get(aid, aid)


def action_pair(cfg, aid):
    ca = find_custom(cfg, aid)
    return ca["bindings"] if ca is not None else cfg["bindings"][aid]


def all_action_ids(cfg):
    """Все действия текущего профиля: свои + (если включены) встроенные действия ACE COMBAT 8."""
    ids = [custom_aid(ca) for ca in cfg["custom_actions"]]
    if cfg["game"]["builtin_actions"]:
        ids += ACTION_IDS
    return ids


def find_opentrack():
    for env in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        base = os.environ.get(env)
        if base:
            p = os.path.join(base, "opentrack", "opentrack.exe")
            if os.path.isfile(p):
                return p
    return ""


def default_outputs():
    return {aid: {"via": ACTION_VIA[aid], "keys": list(ACTION_KEYS[aid])} for aid in ACTION_IDS}


def default_config():
    b = lambda i: [{"type": "button", "index": i}, None]
    h = lambda i, d: [{"type": "hat", "index": i, "dir": d}, None]
    bind = {aid: [None, None] for aid in ACTION_IDS}
    bind.update({
        "gun": b(0), "missile": b(1), "next_weapon": b(2), "target": b(3), "boresight": b(4),
        "highg": b(5), "view": b(6), "map": b(7), "autopilot": b(8), "flare": b(9),
        "pause": b(10), "center_view": b(11), "toggle_head": b(12),
        "order_attack": h(0, "up"), "order_cover": h(0, "down"),
        "order_disperse": h(0, "left"), "order_sp": h(0, "right"),
        "cam_up": h(1, "up"), "cam_down": h(1, "down"), "cam_left": h(1, "left"), "cam_right": h(1, "right"),
    })
    stick = dict(STICK_PRESETS["standard"])
    return {
        "version": 3,
        "profile_name": DEFAULT_PROFILE,
        "game": {"builtin_actions": True, "virtual_pad": True, "launch_type": "steam", "exe_path": ""},
        "custom_actions": [],
        "sequences": [],
        "button_names": {},
        "axis_thr": {},
        "layers": default_layers(),
        "long_press_ms": 500,
        "auto": {"processes": [], "aircraft": []},
        "device_name": "",
        "poll_hz": 250,
        "axes": {"roll": 0, "pitch": 1, "yaw": 5, "throttle": 2, "cam_x": None, "cam_y": None},
        "invert": {"roll": False, "pitch": True, "yaw": False, "cam_x": False, "cam_y": False},
        "axes_enabled": {role: True for role, _ in AXIS_ROLES},
        "response": {
            "roll": dict(stick),
            "pitch": dict(stick),
            "yaw": {"mode": "hold", "threshold": 0.12, "full": 0.60, "period_ms": 120,
                    "min_pulse_ms": 25, "delay_ms": 0, "smoothing_ms": 0},
        },
        "cam_deadzone": 0.08,
        "output": {"max_hz": 125, "deadband": 0.01},
        "throttle_cal": {
            "raw_aft": 1.0, "raw_forward": -1.0, "neutral_low_raw": 0.15, "neutral_high_raw": -0.15,
            "recorded": [],
        },
        "bindings": bind,
        "outputs": default_outputs(),
        "camera": {"mode": "stick", "speed": 1.5, "stick_speed": 3.0, "max": 1.0},
        "head": {
            "enabled": False, "port": 4242, "opentrack_path": find_opentrack(), "manage_process": True,
            "yaw_full": 75.0, "pitch_full": 15.0, "deadzone": 0.0, "yaw_exp": 1.0, "pitch_exp": 1.0,
            "smoothing_ms": 80.0, "max_stick": 1.0, "invert_yaw": False, "invert_pitch": False,
        },
        "launcher": {"steam_appid": DEFAULT_APPID, "autostart_bridge": False, "minimize_on_play": True,
                     "low_priority": False},
        "ministick": {"enabled": False, "sens": 0.5, "timeout_ms": 80,
                      "deadzone": 0.08, "invert_x": False, "invert_y": False,
                      "bindings": {"up": [], "down": [], "left": [], "right": []},
                      "bind_threshold": 0.5, "curve": 1.0, "axis_lock": False},
        "zoom": {"enabled": False, "axis": None, "invert": False, "filter_thr": 0.02},
    }


# ----------------------------------------------------------------------
# Проверка и очистка конфигурации (в т.ч. перенос настроек из версий 1.x и 2.x)
# ----------------------------------------------------------------------
def _num(v, default, lo, hi):
    if isinstance(v, bool):
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return max(lo, min(hi, v))


def _int_index(v, limit=64):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v < limit


def valid_binding(x):
    if not isinstance(x, dict):
        return None
    i = x.get("index")
    if not _int_index(i, 256):
        return None
    t = x.get("type")
    if t == "button":
        return {"type": "button", "index": i}
    if t == "hat" and x.get("dir") in ARROW:
        return {"type": "hat", "index": i, "dir": x["dir"]}
    if t == "axis" and x.get("dir") in ("+", "-"):
        d = 0.5 if x["dir"] == "+" else -0.5
        return {"type": "axis", "index": i, "dir": x["dir"], "thr": round(_num(x.get("thr"), d, -0.95, 0.95), 3)}
    return None


# переименования действий: 1.x -> 2.x -> 3.x
OLD_ACTION_IDS = {"camera": "view", "dpad_up": "order_attack", "dpad_down": "order_cover",
                  "dpad_left": "order_disperse", "dpad_right": "order_sp",
                  "weapon": "next_weapon", "accel_btn": "throttle_up", "brake_btn": "throttle_down",
                  "yawl_btn": "yaw_left", "yawr_btn": "yaw_right"}


def _binding_pair(v):
    if isinstance(v, list):
        p = [valid_binding(v[0]) if len(v) > 0 else None, valid_binding(v[1]) if len(v) > 1 else None]
    else:
        p = [valid_binding(v), None]
    if p[0] is None and p[1] is not None:
        p = [p[1], None]
    if p[0] is not None and p[0] == p[1]:
        p[1] = None
    return p


def _sanitize_stick(src, d):
    src = src if isinstance(src, dict) else {}
    return {k: _num(src.get(k), d[k], lo, hi) for k, _l, lo, hi, _s in STICK_PARAMS}


def sanitize_config(src):
    """Возвращает НОВЫЙ корректный конфиг; всё недостающее/битое берётся по умолчанию."""
    d = default_config()
    src = src if isinstance(src, dict) else {}
    g = lambda dct, key: dct.get(key) if isinstance(dct.get(key), dict) else {}
    out = {"version": 3}
    out["profile_name"] = clean_profile_name(src.get("profile_name") or DEFAULT_PROFILE)
    gm = g(src, "game")
    dg = d["game"]
    out["game"] = {
        "builtin_actions": bool(gm.get("builtin_actions", dg["builtin_actions"])),
        "virtual_pad": bool(gm.get("virtual_pad", dg["virtual_pad"])),
        "launch_type": gm.get("launch_type") if gm.get("launch_type") in ("steam", "exe", "none") else "steam",
        "exe_path": gm.get("exe_path") if isinstance(gm.get("exe_path"), str) else "",
    }
    cas = src.get("custom_actions") if isinstance(src.get("custom_actions"), list) else []
    out["custom_actions"] = []
    seen = set()
    for x in cas[:MAX_CUSTOM]:
        if not isinstance(x, dict):
            continue
        cid = x.get("id") if isinstance(x.get("id"), str) and re.fullmatch(r"[A-Za-z0-9_]{1,32}", x["id"]) else ""
        if not cid or cid in seen:
            cid = "c1"
            n = 1
            while cid in seen:
                n += 1
                cid = "c%d" % n
        seen.add(cid)
        name = str(x.get("name") or "").strip()[:60] or "Действие"
        ks = x.get("keys") if isinstance(x.get("keys"), list) else []
        ks = [k for i, k in enumerate(ks) if isinstance(k, str) and k in ALL_KEYS and k not in ks[:i]][:3]
        steps = clean_steps(x.get("steps"))
        layer = x.get("layer")
        pt = x.get("profile") if isinstance(x.get("profile"), dict) else {}
        pnames = []
        for n in (pt.get("names") if isinstance(pt.get("names"), list) else [])[:20]:
            if isinstance(n, str) and n.strip():
                n = clean_profile_name(n)
                if n not in pnames:
                    pnames.append(n)
        out["custom_actions"].append({
            "repeat_ms": int(_num(x.get("repeat_ms"), 100, 30, 2000)),
            "seq": x["seq"].strip()[:60] if isinstance(x.get("seq"), str) and x["seq"].strip() else "",
            "profile": {"kind": pt.get("kind") if pt.get("kind") in PROFILE_KINDS else "cycle", "names": pnames},
            "id": cid, "name": name, "keys": ks,
            "mode": x.get("mode") if x.get("mode") in CUSTOM_MODES else "hold",
            "cam": x.get("cam") if x.get("cam") in DCS_CAM_LABEL else "left",
            "trigger": x.get("trigger") if x.get("trigger") in CUSTOM_TRIGGERS else "press",
            "layer": layer if isinstance(layer, int) and not isinstance(layer, bool) and 0 <= layer <= 3 else 0,
            "steps": steps,
            "bindings": _binding_pair(x.get("bindings"))})
    ly = g(src, "layers")
    lb = ly.get("buttons") if isinstance(ly.get("buttons"), list) else []
    dl = default_layers()
    out["layers"] = {"enabled": bool(ly.get("enabled", False)),
                     "buttons": [(valid_binding(lb[i]) if i < len(lb) else None) if "buttons" in ly
                                 else dl["buttons"][i] for i in range(3)]}
    out["long_press_ms"] = int(_num(src.get("long_press_ms"), 500, 150, 3000))
    sqs = src.get("sequences") if isinstance(src.get("sequences"), list) else []
    out["sequences"] = []
    for sq in sqs[:100]:
        if isinstance(sq, dict) and isinstance(sq.get("name"), str) and sq["name"].strip():
            nm = sq["name"].strip()[:60]
            if nm not in [x["name"] for x in out["sequences"]]:
                out["sequences"].append({"name": nm, "steps": clean_steps(sq.get("steps"))})
    at = g(src, "axis_thr")
    out["axis_thr"] = {k: round(_num(v, 0.5, -0.95, 0.95), 3) for k, v in list(at.items())[:200]
                       if isinstance(k, str) and re.fullmatch(r"a\d{1,3}:[+-]", k)}
    bn = g(src, "button_names")
    out["button_names"] = {k: str(v).strip()[:40] for k, v in list(bn.items())[:300]
                           if isinstance(k, str) and re.fullmatch(r"(b|h|a)\d{1,3}(:([a-z]{1,2}|[+-]))?", k)
                           and isinstance(v, str) and v.strip()}
    au = g(src, "auto")
    out["auto"] = {"processes": _norm_list(au.get("processes")), "aircraft": _norm_list(au.get("aircraft"))}
    out["device_name"] = src["device_name"] if isinstance(src.get("device_name"), str) else ""
    out["poll_hz"] = int(_num(src.get("poll_hz"), d["poll_hz"], 30, 1000))

    axes = g(src, "axes")
    out["axes"] = {}
    for role, _ in AXIS_ROLES:
        if role in axes:
            v = axes[role]
            out["axes"][role] = None if v is None else (v if _int_index(v) else d["axes"][role])
        else:
            out["axes"][role] = d["axes"][role]
    inv = g(src, "invert")
    out["invert"] = {r: bool(inv.get(r, d["invert"][r])) for r in d["invert"]}
    en = g(src, "axes_enabled")
    out["axes_enabled"] = {r: bool(en.get(r, True)) for r, _ in AXIS_ROLES}

    # отклик ручки; из старых версий переносим мёртвые зоны и порог рыскания
    resp = g(src, "response")
    dr = d["response"]
    roll_src = dict(g(resp, "roll"))
    pitch_src = dict(g(resp, "pitch"))
    if "roll" not in resp and "roll_deadzone" in src:
        roll_src.setdefault("deadzone", src.get("roll_deadzone"))
    if "pitch" not in resp and "pitch_deadzone" in src:
        pitch_src.setdefault("deadzone", src.get("pitch_deadzone"))
    out["response"] = {"roll": _sanitize_stick(roll_src, dr["roll"]),
                       "pitch": _sanitize_stick(pitch_src, dr["pitch"])}
    y = dict(g(resp, "yaw"))
    dy = dr["yaw"]
    # из 2.x порог рыскания (0.2) НЕ переносим: новые значения по умолчанию отзывчивее
    oy = {"mode": y.get("mode") if y.get("mode") in ("hold", "pulse") else dy["mode"]}
    for k, _l, lo, hi, _s in YAW_PARAMS:
        oy[k] = _num(y.get(k), dy[k], lo, hi)
    if oy["full"] < oy["threshold"] + 0.05:
        oy["full"] = min(1.0, oy["threshold"] + 0.05)
    out["response"]["yaw"] = oy
    out["cam_deadzone"] = _num(src.get("cam_deadzone"), d["cam_deadzone"], 0.0, 0.9)
    so = g(src, "output")
    out["output"] = {"max_hz": int(_num(so.get("max_hz"), d["output"]["max_hz"], 30, 1000)),
                     "deadband": _num(so.get("deadband"), d["output"]["deadband"], 0.0, 0.05)}

    cal = g(src, "throttle_cal")
    dc = d["throttle_cal"]
    out["throttle_cal"] = {k: _num(cal.get(k), dc[k], -1.0, 1.0) for k, _ in CAL_ROWS}
    rec = cal.get("recorded") if isinstance(cal.get("recorded"), list) else []
    keys = [k for k, _ in CAL_ROWS]
    out["throttle_cal"]["recorded"] = [k for i, k in enumerate(rec)
                                       if isinstance(k, str) and k in keys and k not in rec[:i]]

    b = dict(g(src, "bindings"))
    for old, new in OLD_ACTION_IDS.items():
        if old in b and new not in b:
            b[new] = b[old]
    out["bindings"] = {aid: (_binding_pair(b[aid]) if aid in b else [x for x in d["bindings"][aid]])
                       for aid in ACTION_IDS}

    o = g(src, "outputs")
    out["outputs"] = {}
    for aid in ACTION_IDS:
        so = o.get(aid) if isinstance(o.get(aid), dict) else {}
        via = so.get("via") if so.get("via") in ("pad", "key") else ACTION_VIA[aid]
        if ACTION_PAD[aid] is None:
            via = "key"
        if aid in INTERNAL_ACTIONS:
            via = "pad"
        ks = so.get("keys") if isinstance(so.get("keys"), list) else ACTION_KEYS[aid]
        good = [k for i, k in enumerate(ks) if isinstance(k, str) and k in ALL_KEYS and k not in ks[:i]][:3]
        if ks and not good:      # были клавиши, но все битые -> по умолчанию; пустой список [] — осознанный
            good = list(ACTION_KEYS[aid])
        ks = good
        out["outputs"][aid] = {"via": via, "keys": ks}

    cam = g(src, "camera")
    out["camera"] = {"mode": cam.get("mode") if cam.get("mode") in ("stick", "mouse") else "stick",
                     "speed": _num(cam.get("speed"), d["camera"]["speed"], 0.2, 6.0),
                     "stick_speed": _num(cam.get("stick_speed"), d["camera"]["stick_speed"], 0.0, 10.0),
                     "max": _num(cam.get("max"), d["camera"]["max"], 0.2, 1.0)}

    h = g(src, "head")
    dh = d["head"]
    path = h.get("opentrack_path") if isinstance(h.get("opentrack_path"), str) else ""
    out["head"] = {
        "enabled": bool(h.get("enabled", dh["enabled"])),
        "port": int(_num(h.get("port"), dh["port"], 1024, 65535)),
        "opentrack_path": path or dh["opentrack_path"],
        "manage_process": bool(h.get("manage_process", h.get("autolaunch", dh["manage_process"]))),
        "invert_yaw": bool(h.get("invert_yaw", dh["invert_yaw"])),
        "invert_pitch": bool(h.get("invert_pitch", dh["invert_pitch"])),
    }
    for key, _label, lo, hi, _step in HEAD_SCALES:
        out["head"][key] = _num(h.get(key), dh[key], lo, hi)

    la = g(src, "launcher")
    appid = str(la.get("steam_appid", DEFAULT_APPID)).strip()
    out["launcher"] = {
        "steam_appid": appid if (appid.isdigit() and 0 < len(appid) <= 10) or appid == "" else DEFAULT_APPID,
        "autostart_bridge": bool(la.get("autostart_bridge", False)),
        "minimize_on_play": bool(la.get("minimize_on_play", True)),
        "low_priority": bool(la.get("low_priority", False)),
    }
    ms = g(src, "ministick")
    dm = d["ministick"]
    msb_src = ms.get("bindings") if isinstance(ms.get("bindings"), dict) else {}
    msb = {}
    for dr in ("up", "down", "left", "right"):
        lst = msb_src.get(dr) if isinstance(msb_src.get(dr), list) else []
        msb[dr] = [k for k in lst[:3] if isinstance(k, str) and k in ALL_KEYS]
    out["ministick"] = {
        "enabled": bool(ms.get("enabled", dm["enabled"])),
        "sens": _num(ms.get("sens"), dm["sens"], 0.1, 5.0),
        "timeout_ms": int(_num(ms.get("timeout_ms"), dm["timeout_ms"], 16, 500)),
        "deadzone": _num(ms.get("deadzone"), dm["deadzone"], 0.0, 0.40),
        "invert_x": bool(ms.get("invert_x", dm["invert_x"])),
        "invert_y": bool(ms.get("invert_y", dm["invert_y"])),
        "bindings": msb,
        "bind_threshold": _num(ms.get("bind_threshold"), dm["bind_threshold"], 0.1, 0.95),
        "curve": _num(ms.get("curve"), dm["curve"], 1.0, 3.0),
        "axis_lock": bool(ms.get("axis_lock", dm["axis_lock"])),
    }
    zm = g(src, "zoom")
    dz = d["zoom"]
    za = zm.get("axis")
    out["zoom"] = {
        "enabled": bool(zm.get("enabled", dz["enabled"])),
        "axis": za if isinstance(za, int) and not isinstance(za, bool) and 0 <= za < 64 else None,
        "invert": bool(zm.get("invert", dz["invert"])),
        "filter_thr": _num(zm.get("filter_thr"), dz["filter_thr"], 0.0, 0.10),
    }
    return out


# ----------------------------------------------------------------------
# Математика
# ----------------------------------------------------------------------
def clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def rescaled_deadzone(value, size):
    value = clamp(value)
    if abs(value) <= size:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - size) / (1.0 - size)


def shape_axis(v, r):
    """Отклик ручки: мёртвая зона -> кривая -> чувствительность -> компенсация мёртвой зоны игры."""
    if not math.isfinite(v):
        return 0.0
    v = clamp(v)
    a = abs(v)
    dz = r["deadzone"]
    if a <= dz:
        return 0.0
    n = (a - dz) / (1.0 - dz) if dz < 1.0 else 0.0
    n = n ** r["curve"]
    n = min(1.0, n * r["sensitivity"])
    if n <= 0.0:
        return 0.0
    ad = r["anti_deadzone"]
    n = ad + (1.0 - ad) * n
    return math.copysign(min(1.0, n), v)


def ema_alpha(dt, ms):
    """Коэффициент экспоненциального сглаживания за шаг dt (с) при постоянной времени ms (мс)."""
    if ms <= 0:
        return 1.0
    return 1.0 - math.exp(-max(0.0, dt) / (ms / 1000.0))


_splitter_cache = {}


def make_splitter(cal):
    """raw РУД -> (LT, RT). Направление оси определяется автоматически."""
    key = (cal["raw_aft"], cal["raw_forward"], cal["neutral_low_raw"], cal["neutral_high_raw"])
    if key in _splitter_cache:
        return _splitter_cache[key]
    if len(_splitter_cache) > 256:
        _splitter_cache.clear()
    aft, fwd = cal["raw_aft"], cal["raw_forward"]
    span = fwd - aft
    if abs(span) < 1e-3:
        _splitter_cache[key] = None
        return None

    def pos(raw):
        return clamp((raw - aft) / span, 0.0, 1.0)

    n_lo, n_hi = sorted((pos(cal["neutral_low_raw"]), pos(cal["neutral_high_raw"])))
    n_lo, n_hi = max(n_lo, 0.01), min(n_hi, 0.99)
    if n_hi < n_lo:
        n_lo = n_hi = (n_lo + n_hi) / 2

    def split(raw):
        p = pos(raw)
        if p < n_lo:
            return clamp((n_lo - p) / n_lo, 0.0, 1.0), 0.0
        if p > n_hi:
            return 0.0, clamp((p - n_hi) / (1.0 - n_hi), 0.0, 1.0)
        return 0.0, 0.0

    _splitter_cache[key] = split
    return split


def head_to_stick(angle, full_scale, deadzone, exponent):
    a = abs(angle)
    if a <= deadzone or not math.isfinite(a):
        return 0.0
    span = max(full_scale - deadzone, 1e-6)
    n = min(1.0, (a - deadzone) / span)
    return math.copysign(n ** exponent, angle)


def ramp(cur, target, rate, dt):
    """Плавно ведёт значение к цели: не быстрее rate (доля хода в секунду). rate=0 — мгновенно."""
    if rate <= 0:
        return target
    step = rate * dt
    if abs(target - cur) <= step:
        return target
    return cur + step if target > cur else cur - step


def compose_camera(cfg, manual, head_cam, look, dt, stick_pos=(0.0, 0.0)):
    """Итоговый правый стик. Возвращает ((x, y), новый look, источник, новый stick_pos)."""
    c = cfg["camera"]
    dt = min(max(dt, 0.0), 0.1)
    mx, my = manual
    lim = c["max"]
    mx, my = mx * lim, my * lim
    sp = (ramp(stick_pos[0], mx, c["stick_speed"], dt), ramp(stick_pos[1], my, c["stick_speed"], dt))
    if cfg["head"]["enabled"]:
        if mx or my or sp[0] or sp[1]:
            return sp, look, "x52", sp
        if head_cam[0] or head_cam[1]:
            return head_cam, look, "head", sp
        return (0.0, 0.0), look, None, sp
    if c["mode"] == "mouse":
        lx = clamp(look[0] + mx * c["speed"] * dt, -lim, lim)
        ly = clamp(look[1] + my * c["speed"] * dt, -lim, lim)
        new = (lx, ly)
        return new, new, ("mouse" if (lx or ly) else None), (0.0, 0.0)
    return sp, look, ("x52" if (sp[0] or sp[1]) else None), sp


# ----------------------------------------------------------------------
# Привязки X52
# ----------------------------------------------------------------------
def binding_key(b):
    """Хэшируемый идентификатор входа X52 (для поиска дублей)."""
    if not b:
        return None
    if b["type"] == "axis":
        return ("axis", b["index"], b["dir"])
    if b["type"] == "hat":
        return ("hat", b["index"], b["dir"])
    return ("button", b["index"])


def binding_active(b, buttons, hats, axes=(), was_active=False):
    if not b:
        return False
    t = b["type"]
    i = b["index"]
    if t == "button":
        return i < len(buttons) and bool(buttons[i])
    if t == "hat":
        if i >= len(hats):
            return False
        x, y = hats[i]
        d = b["dir"]
        if d in HAT8:
            hx, hy = HAT8[d]
            return (x > 0) - (x < 0) == hx and (y > 0) - (y < 0) == hy
        return (d == "up" and y > 0) or (d == "down" and y < 0) or \
               (d == "left" and x < 0) or (d == "right" and x > 0)
    if t == "axis":
        if i >= len(axes):
            return False
        v = axes[i]
        if not math.isfinite(v):
            return False
        thr = b["thr"]
        h = AXIS_BIND_HYST if was_active else 0.0
        return v >= thr - h if b["dir"] == "+" else v <= thr + h
    return False


def binding_text(b):
    if not b:
        return "—"
    if b["type"] == "button":
        return "Кнопка %d" % (b["index"] + 1)
    if b["type"] == "hat":
        return "Хатка %d %s" % (b["index"] + 1, ARROW[b["dir"]])
    if b["type"] == "axis":
        sign = "≥" if b["dir"] == "+" else "≤"
        return "Ось %d %s (%s %+.2f)" % (b["index"] + 1, b["dir"], sign, b["thr"])
    return "—"


def output_text(cfg, aid):
    o = cfg["outputs"][aid]
    outs = ACTION_PAD[aid]
    if aid in INTERNAL_ACTIONS:
        return "команда лаунчера"
    if o["via"] == "key":
        return "Клавиатура: " + keys_text(o["keys"])
    return "Геймпад: " + " + ".join(TOKEN_TEXT.get(t, t) for t in outs)


def learn_axis_binding(v0, v):
    """Привязка «ось как кнопка» по начальному и конечному положению оси."""
    sign = "+" if v > v0 else "-"
    if abs(v0) < 0.3:   # ось с центром (ручка, мини-стик): половина хода от центра
        thr = 0.5 if sign == "+" else -0.5
    else:               # рычаг/крутилка из крайнего положения: середина пройденного пути
        thr = (v0 + v) / 2.0
    return {"type": "axis", "dir": sign, "thr": round(clamp(thr, -0.95, 0.95), 2)}


# ----------------------------------------------------------------------
# Маппер: X52 -> выход геймпада + клавиши. Хранит состояние (сглаживание, импульсы рыскания).
# ----------------------------------------------------------------------
EMPTY_OUT = {"roll": 0.0, "pitch": 0.0, "cam_x": 0.0, "cam_y": 0.0, "lt": 0.0, "rt": 0.0,
             "pressed": frozenset(), "internal": frozenset(), "keys": frozenset(),
             "actions": frozenset(), "yaw": 0.0, "yaw_level": 0.0, "cam_src": None}


MS_AXIS_LOCK = 0.5   # «Фиксация оси» мини-стика: вторая ось живёт, только если она не меньше половины первой


class ZoomAxis(object):
    """Ось X52 (ползунок) -> зум. Значение меняется, только если ползунок сдвинули больше чем на
    filter_thr (шум датчика не проходит); затем короткое сглаживание, чтобы шаг фильтра не был рывком."""
    SMOOTH_MS = 60

    def __init__(self):
        self.held = None
        self.out = 0.0
        self.t = None

    def step(self, z, raw, now):
        if raw is None or not math.isfinite(raw):
            return self.out
        raw = clamp(-raw if z["invert"] else raw)
        dt = 0.0 if self.t is None else max(0.0, now - self.t)
        self.t = now
        if self.held is None:
            self.held = self.out = raw
        elif abs(raw - self.held) >= max(z["filter_thr"], 1e-4):
            self.held = raw
        self.out += ema_alpha(dt, self.SMOOTH_MS) * (self.held - self.out) if dt > 0 else 0.0
        if abs(self.out - self.held) < 1e-3:
            self.out = self.held
        return self.out


class Mapper(object):
    def __init__(self):
        self.wheel_last = 0          # последнее положение колеса (1..3); переживает смену профиля
        self.wheel_seen = False      # колесо видели живьём с момента открытия джойстика
        self.reset()

    def reset(self):
        self.t = None
        self.sm = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        self.zoom = ZoomAxis()
        self.ministick = (0.0, 0.0)  # dx/dy мини-стика X52, приходит из RawInput на Windows
        self.axis_active = set()     # (aid, slot) привязок-осей, активных на прошлом шаге
        self.yaw_side = 0            # -1/0/+1 — в какую сторону отклонена рукоять
        self.yaw_since = 0.0         # когда началось отклонение (для задержки)
        self.yaw_phase_t = 0.0       # начало текущего периода импульсов
        self.custom_prev = set()     # свои действия, у которых вход был активен на прошлом шаге
        self.toggled = set()         # свои действия-переключатели, сейчас «включённые»
        self.press_t = {}            # aid -> когда нажали (для короткого/долгого)
        self.long_fired = set()      # aid, у которых долгое нажатие уже сработало
        self.tap_until = {}          # aid -> до какого времени держать «тап»
        self.seq_start = {}          # aid -> время старта идущей последовательности
        self.layer = 0               # текущий слой (0 — слои выключены / неизвестен)
        self.layer_known = True      # распознано ли положение колеса
        self.rep_start = {}          # aid -> начало автоповтора
        self.fresh = True            # первый шаг после сброса/смены профиля
        self.suppressed = set()      # зажаты в момент смены профиля: молчат до отпускания
        self.profile_events = []     # сработавшие «смены профиля» (забирает рабочий поток)
        self.tap_queue = []          # одиночные нажатия, ждущие своей очереди
        self.tap_cur = None          # (клавиши, до какого времени держать) — текущий тап
        self.tap_gap_until = 0.0

    def _axis(self, cfg, axes, role):
        i = analog_axis(cfg, role)
        if i is None or i >= len(axes):
            return None
        v = axes[i]
        if not math.isfinite(v):
            return 0.0
        return -v if cfg["invert"].get(role) else v

    def _yaw_state(self, r, yaw, now):
        """Возвращает (-1/0/+1, уровень 0..1) — нажата ли кнопка рыскания и насколько отклонена рукоять."""
        a = abs(yaw)
        side = 0
        thr = r["threshold"]
        hold_thr = thr - 0.02 if self.yaw_side else thr   # небольшой гистерезис против дребезга
        if a >= hold_thr:
            side = 1 if yaw > 0 else -1
        if side != self.yaw_side:
            self.yaw_side = side
            self.yaw_since = now
            self.yaw_phase_t = now + r["delay_ms"] / 1000.0
        if not side:
            return 0, 0.0
        if now - self.yaw_since < r["delay_ms"] / 1000.0:
            return 0, 0.0
        full = max(r["full"], thr + 1e-3)
        level = clamp((a - thr) / (full - thr), 0.0, 1.0)
        if r["mode"] == "hold" or level >= 1.0:
            return side, 1.0 if r["mode"] == "hold" else level
        period = r["period_ms"] / 1000.0
        on = max(r["min_pulse_ms"] / 1000.0, level * period)
        if on >= period:
            return side, level
        phase = (now - self.yaw_phase_t) % period
        return (side if phase < on else 0), level

    def _custom(self, cfg, held, buttons, hats, axes, now, active):
        """Свои действия: слои, обычное/короткое/долгое нажатие, удержание/переключатель/последовательность."""
        ly = cfg["layers"]
        if ly["enabled"]:
            cur = 0
            for i, b in enumerate(ly["buttons"]):
                if b and binding_active(b, buttons, hats, axes):
                    cur = i + 1
                    break
            if cur:
                self.wheel_last = cur
                self.wheel_seen = True
            elif self.wheel_last and not self.wheel_seen:
                # джойстик только что открыт, Windows ещё не сообщила уже зажатую кнопку колеса —
                # до первого живого сигнала берём последнее известное положение
                cur = self.wheel_last
            self.layer_known = bool(cur)   # False — положение ни разу не видели (не те номера кнопок?)
            self.layer = cur or 1          # для срабатывания действий считаем слоем 1
        else:
            self.layer = 0
        long_s = cfg["long_press_ms"] / 1000.0
        if self.fresh:
            # после смены профиля зажатые кнопки — «старые»: без нажатия/короткого/долгого,
            # но отпускание сработает (схема «нажал — профиль 2, отпустил — профиль 1»)
            self.fresh = False
            for ca in cfg["custom_actions"]:
                aid = custom_aid(ca)
                if aid in held and (not ly["enabled"] or ca["layer"] in (0, self.layer)):
                    self.custom_prev.add(aid)
                    self.press_t[aid] = now
                    self.long_fired.add(aid)
                    self.suppressed.add(aid)
        keys = set()
        live = set()
        raw_now = set()
        self.custom_cam = set()
        for ca in cfg["custom_actions"]:
            aid = custom_aid(ca)
            live.add(aid)
            raw = aid in held and (not ly["enabled"] or ca["layer"] in (0, self.layer))
            if raw:
                raw_now.add(aid)
            was = aid in self.custom_prev
            if aid in self.suppressed:
                if raw:
                    continue                  # всё ещё держат кнопку, нажатую до смены профиля
                self.suppressed.discard(aid)  # отпустили — дальше сработает только «отпускание»
            if raw and not was:
                self.press_t[aid] = now
                self.long_fired.discard(aid)
            trig = ca["trigger"]
            event = False
            level = False
            if trig == "press":
                event = raw and not was
                level = raw
            elif trig == "short":
                if was and not raw and aid not in self.long_fired:
                    event = now - self.press_t.get(aid, now) < long_s
            elif trig == "release":
                event = was and not raw
            else:   # long
                if raw and aid not in self.long_fired and now - self.press_t.get(aid, now) >= long_s:
                    self.long_fired.add(aid)
                    event = True
                level = raw and aid in self.long_fired
            if trig == "short" and was and not raw:
                self.long_fired.discard(aid)
            if trig != "long" and raw and now - self.press_t.get(aid, now) >= long_s:
                self.long_fired.add(aid)   # для короткого: держали дольше порога — уже не короткое

            mode = ca["mode"]
            on = False
            if mode == "profile":
                if event:
                    self.profile_events.append(dict(ca["profile"], names=list(ca["profile"]["names"])))
                    self.tap_until[aid] = now + 0.3          # подсветка «сработало» в интерфейсе
                on = now < self.tap_until.get(aid, 0.0)
            elif mode == "repeat":
                if trig in ("short", "release"):
                    if event:                                 # одиночный тап
                        self.tap_until[aid] = now + TAP_MS / 1000.0
                        self.tap_queue.append(list(ca["keys"]))
                    on = now < self.tap_until.get(aid, 0.0)
                elif level:
                    st0 = self.rep_start.setdefault(aid, now)
                    period = ca["repeat_ms"] / 1000.0
                    tap = min(TAP_MS / 1000.0, period / 2.0)
                    on = True
                    if (now - st0) % period < tap:
                        keys.update(ca["keys"])
                else:
                    self.rep_start.pop(aid, None)
            elif mode == "toggle":
                if event:
                    self.toggled ^= {aid}
                on = aid in self.toggled
                if on:
                    keys.update(ca["keys"])
            elif mode == "tap":
                if event:                                     # одно короткое нажатие клавиши
                    self.tap_until[aid] = now + TAP_MS / 1000.0
                    self.tap_queue.append(list(ca["keys"]))
                on = now < self.tap_until.get(aid, 0.0)
            elif mode == "sequence":
                steps = action_steps(cfg, ca)
                if event and aid not in self.seq_start:
                    self.seq_start[aid] = now
                if aid in self.seq_start:
                    el = (now - self.seq_start[aid]) * 1000.0
                    if el >= sequence_length_ms(steps):
                        del self.seq_start[aid]
                    else:
                        on = True
                        for st in steps:
                            if st["delay_ms"] <= el < st["delay_ms"] + st["duration_ms"]:
                                keys.update(st["keys"])
            else:   # hold, camera
                tapped = trig in ("short", "release")
                if tapped:
                    if event:
                        self.tap_until[aid] = now + TAP_MS / 1000.0
                        if mode != "camera":
                            self.tap_queue.append(list(ca["keys"]))
                    on = now < self.tap_until.get(aid, 0.0)
                else:
                    on = level
                if on and mode == "camera":
                    self.custom_cam.add(DCS_CAM_PAD.get(ca.get("cam"), "CAM_LEFT"))
                elif on and not tapped:
                    keys.update(ca["keys"])
            if on:
                active.add(aid)
        # одиночные нажатия, сработавшие в один момент (например «короткое» и «отпускание» на одной
        # кнопке), идут по очереди: иначе клавиши и модификаторы разных действий смешались бы
        if self.tap_cur is not None and now >= self.tap_cur[1]:
            self.tap_cur = None
            self.tap_gap_until = now + TAP_GAP_MS / 1000.0
        if self.tap_cur is None and self.tap_queue and now >= self.tap_gap_until:
            self.tap_cur = (self.tap_queue.pop(0), now + TAP_MS / 1000.0)
        if self.tap_cur is not None:
            keys.update(self.tap_cur[0])
        self.custom_prev = raw_now
        self.toggled &= live
        for d in (self.press_t, self.tap_until, self.seq_start, self.rep_start):
            for k in [k for k in d if k not in live]:
                del d[k]
        self.long_fired &= live
        self.suppressed &= live
        return keys

    def step(self, cfg, axes, buttons, hats, now=None):
        now = time.perf_counter() if now is None else now
        dt = 0.0 if self.t is None else clamp(now - self.t, 0.0, 0.25)
        self.t = now
        resp = cfg["response"]

        vals = {}
        for role in ("roll", "pitch"):
            v = self._axis(cfg, axes, role)
            v = 0.0 if v is None else shape_axis(v, resp[role])
            a = ema_alpha(dt, resp[role]["smoothing_ms"]) if dt > 0 else 1.0
            self.sm[role] += a * (v - self.sm[role])
            if abs(self.sm[role]) < 1e-4:
                self.sm[role] = 0.0
            vals[role] = self.sm[role]
        roll, pitch = vals["roll"], vals["pitch"]

        cam_x = rescaled_deadzone(self._axis(cfg, axes, "cam_x") or 0.0, cfg["cam_deadzone"])
        cam_y = rescaled_deadzone(self._axis(cfg, axes, "cam_y") or 0.0, cfg["cam_deadzone"])
        ms = cfg.get("ministick")
        if ms and ms.get("enabled"):
            dz = ms.get("deadzone", 0.0)
            curve = ms.get("curve", 1.0)
            raw = [clamp(self.ministick[0]), clamp(self.ministick[1])]
            if ms.get("axis_lock"):          # побочное отклонение по второй оси гасится; диагональ — от половины
                ax, ay = abs(raw[0]), abs(raw[1])
                if ay < MS_AXIS_LOCK * ax:
                    raw[1] = 0.0
                elif ax < MS_AXIS_LOCK * ay:
                    raw[0] = 0.0
            msv = []
            for i, inv in enumerate(("invert_x", "invert_y")):
                v = rescaled_deadzone(raw[i], dz)
                v = math.copysign(abs(v) ** curve, v) if v else 0.0
                msv.append(-v if ms.get(inv) else v)
            if cfg["axes"].get("cam_x") is None:
                cam_x = msv[0]
            if cfg["axes"].get("cam_y") is None:
                cam_y = msv[1]

        active = set()
        # рыскание с рукояти -> действия yaw_left / yaw_right
        builtin = cfg["game"]["builtin_actions"]
        yaw_raw = self._axis(cfg, axes, "yaw") if builtin else None
        yaw_level = 0.0
        if yaw_raw is not None:
            ry = resp["yaw"]
            a = ema_alpha(dt, ry["smoothing_ms"]) if dt > 0 else 1.0
            self.sm["yaw"] += a * (clamp(yaw_raw) - self.sm["yaw"])
            side, yaw_level = self._yaw_state(ry, self.sm["yaw"], now)
            if side < 0:
                active.add("yaw_left")
            elif side > 0:
                active.add("yaw_right")
        else:
            self.sm["yaw"] = 0.0
            self.yaw_side = 0

        # привязки X52 (две на действие)
        new_axis_active = set()
        sources = [(aid, cfg["bindings"].get(aid) or (None, None)) for aid in ACTION_IDS] if builtin else []
        sources += [(custom_aid(ca), ca["bindings"]) for ca in cfg["custom_actions"]]
        held = set()
        for aid, pair in sources:
            for slot, b in enumerate(pair):
                if not b:
                    continue
                was = (aid, slot) in self.axis_active
                if binding_active(b, buttons, hats, axes, was):
                    held.add(aid)
                    if b["type"] == "axis":
                        new_axis_active.add((aid, slot))
        self.axis_active = new_axis_active

        custom_keys = self._custom(cfg, held, buttons, hats, axes, now, active)
        active.update(a for a in held if not a.startswith(CUSTOM_PREFIX))

        lt = rt = 0.0
        ti = analog_axis(cfg, "throttle")
        if ti is not None and ti < len(axes) and math.isfinite(axes[ti]):
            split = make_splitter(cfg["throttle_cal"])
            if split:
                lt, rt = split(axes[ti])

        pressed, internal, keys = set(), set(), set(custom_keys)
        if ms and ms.get("enabled"):
            msb = ms.get("bindings") or {}
            if any(msb.get(d) for d in ("up", "down", "left", "right")):
                mxr, myr = self.ministick
                if ms.get("invert_x"):
                    mxr = -mxr
                if ms.get("invert_y"):
                    myr = -myr
                thr = ms.get("bind_threshold", 0.5)
                if mxr > thr:
                    keys.update(msb.get("right", ()))
                elif mxr < -thr:
                    keys.update(msb.get("left", ()))
                if myr > thr:
                    keys.update(msb.get("up", ()))
                elif myr < -thr:
                    keys.update(msb.get("down", ()))
        for aid in ACTION_IDS:
            if aid not in active:
                continue
            o = cfg["outputs"][aid]
            if o["via"] == "key" and aid not in INTERNAL_ACTIONS:
                keys.update(o["keys"])
                continue
            for tok in ACTION_PAD[aid] or ():
                if tok == "LT":
                    lt = 1.0
                elif tok == "RT":
                    rt = 1.0
                elif tok == "CAM_UP":
                    cam_y = 1.0
                elif tok == "CAM_DOWN":
                    cam_y = -1.0
                elif tok == "CAM_LEFT":
                    cam_x = -1.0
                elif tok == "CAM_RIGHT":
                    cam_x = 1.0
                elif tok == "LSTICK_UP":
                    pitch = 1.0
                elif tok == "LSTICK_DOWN":
                    pitch = -1.0
                elif tok == "LSTICK_LEFT":
                    roll = -1.0
                elif tok == "LSTICK_RIGHT":
                    roll = 1.0
                elif tok in INTERNAL:
                    internal.add(tok)
                else:
                    pressed.add(tok)
        for tok in self.custom_cam:
            if tok == "CAM_UP":
                cam_y = 1.0
            elif tok == "CAM_DOWN":
                cam_y = -1.0
            elif tok == "CAM_LEFT":
                cam_x = -1.0
            elif tok == "CAM_RIGHT":
                cam_x = 1.0
            else:
                internal.add(tok)
        z = cfg.get("zoom")
        zoom = None
        if z and z["enabled"] and z["axis"] is not None:      # зум идёт левым стиком X геймпада
            zi = z["axis"]
            zoom = self.zoom.step(z, axes[zi] if zi < len(axes) else None, now)
            roll = zoom

        return {"zoom": zoom, "roll": clamp(roll), "pitch": clamp(pitch), "cam_x": clamp(cam_x), "cam_y": clamp(cam_y),
                "lt": lt, "rt": rt, "pressed": pressed, "internal": internal, "keys": keys,
                "actions": active, "yaw": self.sm["yaw"] if yaw_raw is not None else 0.0,
                "yaw_level": yaw_level, "cam_src": None}


def compute_output(cfg, axes, buttons, hats):
    """Однократный расчёт без состояния (для проверки и совместимости)."""
    return Mapper().step(cfg, axes, buttons, hats, now=0.0)


# ----------------------------------------------------------------------
# Фильтр выхода: не заваливать игру обновлениями от дрожания осей X52
# ----------------------------------------------------------------------
ANALOG_KEYS = ("roll", "pitch", "cam_x", "cam_y", "lt", "rt")


class OutputLimiter(object):
    """Решает, отправлять ли новое состояние в игру.
    * кнопки/клавиши изменились — сразу, без задержки;
    * аналог изменился меньше чем на deadband от последнего ОТПРАВЛЕННОГО — это шум, не отправлять
      (медленное движение копится и всё равно уйдёт);
    * возврат точно в 0 или в упор (±1) — отправляется всегда;
    * аналог — не чаще max_hz раз в секунду; отложенное уйдёт, как только пройдёт интервал."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.last = None
        self.last_t = -1e9
        self.sent = 0

    def decide(self, out, now, max_hz, deadband):
        if self.last is None:
            return True
        if set(out["pressed"]) != self.last["pressed"] or set(out["keys"]) != self.last["keys"]:
            return True
        significant = False
        for k in ANALOG_KEYS:
            v, lv = out[k], self.last[k]
            if v == lv:
                continue
            if abs(v - lv) >= deadband or v == 0.0 or abs(v) >= 1.0:
                significant = True
                break
        if not significant:
            return False
        return now - self.last_t >= 1.0 / max(1, max_hz) - 1e-6

    def mark_sent(self, out, now):
        self.last = {k: out[k] for k in ANALOG_KEYS}
        self.last["pressed"] = set(out["pressed"])
        self.last["keys"] = set(out["keys"])
        self.last_t = now
        self.sent += 1


# ----------------------------------------------------------------------
# Отправка клавиш (Windows SendInput, scan-коды). Вне Windows — пустышка для тестов.
# ----------------------------------------------------------------------
class KeySender(object):
    """Держит нажатыми ровно те клавиши, что переданы в apply(); остальные отпускает."""

    def __init__(self, backend=None):
        self.down = set()
        self.backend = backend if backend is not None else (_WinInput() if IS_WIN else _NullInput())

    # модификаторы: нажимаются ПЕРВЫМИ и отпускаются ПОСЛЕДНИМИ — как человек жмёт Ctrl+C.
    # (Раньше клавиши шли по алфавиту: для Ctrl+C игра видела сначала «C», потом Ctrl — другая команда.)
    MODIFIERS = ("LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT", "LWIN", "RWIN")

    @classmethod
    def _order(cls, keys, press):
        mods = [k for k in cls.MODIFIERS if k in keys]
        rest = sorted(k for k in keys if k not in cls.MODIFIERS)
        return mods + rest if press else rest + mods[::-1]

    def apply(self, keys):
        keys = set(k for k in keys if k in KEYS or k in MOUSE_KEYS)
        for k in self._order(self.down - keys, press=False):
            self.backend.send(k, False)
        for k in self._order(keys - self.down, press=True):
            self.backend.send(k, True)
        self.down = keys

    def release_all(self):
        self.apply(())


class _NullInput(object):
    def __init__(self):
        self.log = []

    def send(self, key, down):
        self.log.append((key, down))


class _WinInput(object):
    """SendInput со scan-кодами: игры на DirectInput/RawInput видят их как настоящую клавиатуру."""

    def __init__(self):
        import ctypes
        self.ctypes = ctypes
        # типы фиксированного размера = WORD/DWORD/LONG Windows (не зависят от платформы)
        WORD, DWORD, LONG, UINT = ctypes.c_uint16, ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32
        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                        ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                        ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", DWORD), ("u", _U)]

        self.INPUT, self.KEYBDINPUT, self.MOUSEINPUT = INPUT, KEYBDINPUT, MOUSEINPUT
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = (UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self.user32.SendInput.restype = UINT

    MOUSE_FLAGS = {"MOUSE_LEFT": (0x0002, 0x0004, 0), "MOUSE_RIGHT": (0x0008, 0x0010, 0),
                   "MOUSE_MIDDLE": (0x0020, 0x0040, 0), "MOUSE_X1": (0x0080, 0x0100, 1),
                   "MOUSE_X2": (0x0080, 0x0100, 2)}

    def send(self, key, down):
        inp = self.INPUT()
        if key in self.MOUSE_FLAGS:
            fd, fu, data = self.MOUSE_FLAGS[key]
            inp.type = 0  # INPUT_MOUSE
            inp.mi = self.MOUSEINPUT(0, 0, data, fd if down else fu, 0, 0)
        else:
            scan, ext = KEYS[key]
            flags = 0x0008  # KEYEVENTF_SCANCODE
            if ext:
                flags |= 0x0001  # KEYEVENTF_EXTENDEDKEY
            if not down:
                flags |= 0x0002  # KEYEVENTF_KEYUP
            inp.type = 1  # INPUT_KEYBOARD
            inp.ki = self.KEYBDINPUT(0, scan, flags, 0, 0)
        self.user32.SendInput(1, self.ctypes.byref(inp), self.ctypes.sizeof(inp))
