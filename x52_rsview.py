# -*- coding: utf-8 -*-
"""
Вид «Карта кнопок» — компоновка как у RS Mapper (Rafal «Avantar» Szul), нарисована заново:
  слева — устройства; справа сверху — «Все назначенные действия»; ниже — вкладки «Кнопки» и
  «Хатки» с плитками (SP — нажатие, LP — долгое, RL — отпускание). Щелчок по кнопке плитки —
  окно «Выбор срабатывающего действия» с тремя колонками.
Всё хранится как обычные «свои действия» профиля, поэтому работают и все прежние функции лаунчера.
"""

import json
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from x52_core import (ALL_KEYS, AXIS_ROLES, CUSTOM_PREFIX, DCS_CAM, DCS_CAM_LABEL, HAT8, HAT8_NAME, HAT8_ORDER,
                      MODIFIER_KEYS, SEQ_MAX_DELAY_MS,
                      analog_axis, binding_text, clean_steps, find_custom, key_text, keys_text, new_custom_id,
                      sanitize_config)

SLOTS = ("single", "long", "release")
SEQ_TIME_HINT = ("1 секунда = 1000 мс. Задержка от начала — до %s мс (%d мин), длительность — до 10 000 мс (10 с)."
                 % (format(SEQ_MAX_DELAY_MS, ",").replace(",", " "), SEQ_MAX_DELAY_MS // 60000))
SLOT_TITLE = {"single": "Срабатывание при нажатии", "long": "Срабатывание при долгом нажатии",
              "release": "Срабатывание при отпускании"}
SLOT_SHORT = {"single": "SP", "long": "LP", "release": "RL"}
TRIG_TEXT = {"press": "Нажатие", "short": "Нажатие (короткое)", "long": "Долгое", "release": "Отпускание"}
NEXT_P, PREV_P = "(следующий профиль)", "(предыдущий профиль)"
PLAIN_KEYS = [k for k in ALL_KEYS if k not in MODIFIER_KEYS]
MOD_LABEL = {"LCTRL": "LCtrl", "LSHIFT": "LShift", "LALT": "LAlt", "RCTRL": "RCtrl", "RSHIFT": "RShift",
             "RALT": "RAlt"}
TILE_BG = "#ffffff"
ARROW8 = {"n": "↑", "ne": "↗", "e": "→", "se": "↘", "s": "↓", "sw": "↙", "w": "←", "nw": "↖"}


# ----------------------------------------------------------------------
# модель: входы X52 и «слоты» нажатие / долгое / отпускание
# ----------------------------------------------------------------------
def btn_binding(i):
    return {"type": "button", "index": i}


def hat_binding(i, d):
    return {"type": "hat", "index": i, "dir": d}


def axis_binding(i, d, thr):
    return {"type": "axis", "index": i, "dir": d, "thr": thr}


def default_thr(d):
    return 0.5 if d == "+" else -0.5


def axis_thr(cfg, i, d):
    return cfg.get("axis_thr", {}).get("a%d:%s" % (i, d), default_thr(d))


def name_key(b):
    if b["type"] == "button":
        return "b%d" % b["index"]
    if b["type"] == "axis":
        return "a%d:%s" % (b["index"], b["dir"])
    return "h%d:%s" % (b["index"], b["dir"])


def same_input(a, b):
    """Один и тот же вход X52. У оси порог не важен — это одно направление."""
    if not a or not b or a["type"] != b["type"] or a["index"] != b["index"]:
        return False
    return a.get("dir") == b.get("dir")


def axis_name(cfg, i):
    return cfg.get("button_names", {}).get("a%d" % i) or "Ось %d" % (i + 1)


def input_name(cfg, b):
    nm = cfg.get("button_names", {}).get(name_key(b))
    if nm:
        return nm
    if b["type"] == "axis":
        return "%s %s" % (axis_name(cfg, b["index"]), "+" if b["dir"] == "+" else "−")
    return binding_text(b)


def axis_roles(cfg, i):
    """Аналоговые роли, в которых сейчас работает ось i (крен, РУД…)."""
    return [r for r, _ in AXIS_ROLES if analog_axis(cfg, r) == i]


def set_axis_thr(cfg, i, d, thr):
    thr = round(max(-0.95, min(0.95, float(thr))), 3)
    cfg.setdefault("axis_thr", {})["a%d:%s" % (i, d)] = thr
    for ca in cfg["custom_actions"]:
        for b in ca["bindings"]:
            if b and b["type"] == "axis" and b["index"] == i and b["dir"] == d:
                b["thr"] = thr
    return thr


def slot_of(ca):
    return {"press": "single", "short": "single", "long": "long", "release": "release"}[ca["trigger"]]


def find_slots(cfg, b, layer=0):
    out = {}
    for ca in cfg["custom_actions"]:
        if any(same_input(x, b) for x in ca["bindings"]) and ca["layer"] == layer:
            out.setdefault(slot_of(ca), ca)
    return out


def column_from_ca(ca):
    """Своё действие -> поля колонки окна. special = настроено иначе (переключатель и т.п.)."""
    col = {"enabled": True, "name": ca["name"], "kind": "key", "mods": [], "key": "", "repeat": False,
           "repeat_ms": ca["repeat_ms"], "continuous": False, "seq": "", "profile": "", "special": False,
           "cam": ca.get("cam", "left")}
    m = ca["mode"]
    if m == "camera":
        col["kind"] = "cam"
    elif m == "profile":
        col["kind"] = "profile"
        pt = ca["profile"]
        if pt["kind"] == "name" and pt["names"]:
            col["profile"] = pt["names"][0]
        elif pt["kind"] == "next":
            col["profile"] = NEXT_P
        elif pt["kind"] == "prev":
            col["profile"] = PREV_P
        else:
            col["special"] = True             # «по кругу» — редактируется на вкладке «Назначение»
    elif m == "sequence":
        col["kind"] = "seq"
        col["seq"] = ca.get("seq", "")
        col["special"] = not ca.get("seq")    # шаги внутри действия — вкладка «Назначение»
    elif m == "toggle":
        col["special"] = True
    else:
        col["mods"] = [k for k in ca["keys"] if k in MODIFIER_KEYS]
        rest = [k for k in ca["keys"] if k not in MODIFIER_KEYS]
        col["key"] = rest[0] if rest else ""
        col["repeat"] = m == "repeat"
        col["continuous"] = m == "hold"
    return col


def ca_fields(col, slot, long_on):
    trig = {"single": "short" if long_on else "press", "long": "long", "release": "release"}[slot]
    f = {"name": (col.get("name") or "").strip()[:60] or "Действие", "trigger": trig, "keys": [],
         "steps": [], "seq": "", "repeat_ms": int(col.get("repeat_ms") or 100),
         "profile": {"kind": "cycle", "names": []}}
    if col["kind"] == "profile":
        f["mode"] = "profile"
        p = col.get("profile")
        f["profile"] = ({"kind": "next", "names": []} if p == NEXT_P else
                        {"kind": "prev", "names": []} if p == PREV_P else {"kind": "name", "names": [p]})
    elif col["kind"] == "seq":
        f["mode"] = "sequence"
        f["seq"] = col.get("seq", "")
    elif col["kind"] == "cam":
        f["mode"] = "camera"
        f["cam"] = col.get("cam") or "left"
    else:
        f["keys"] = [k for k in MODIFIER_KEYS if k in col.get("mods", [])] + ([col["key"]] if col.get("key") else [])
        f["mode"] = "repeat" if col.get("repeat") else ("hold" if col.get("continuous") else "tap")
    return f


def column_problem(col):
    if not col.get("enabled") or col.get("special"):
        return None
    if col["kind"] == "key" and not col.get("key"):
        return "выберите клавишу"
    if col["kind"] == "seq" and not col.get("seq"):
        return "выберите последовательность (меню «Последовательности»)"
    if col["kind"] == "profile" and not col.get("profile"):
        return "выберите профиль"
    return None


def apply_slots(cfg, b, layer, cols):
    """Записать три колонки окна в «свои действия» профиля для входа b."""
    have = find_slots(cfg, b, layer)
    long_on = bool(cols["long"].get("enabled"))
    for slot in SLOTS:
        col, ca = cols[slot], have.get(slot)
        if not col.get("enabled"):           # снятая галочка убирает и «особое» действие (по кругу, свои шаги)
            if ca is not None:
                pair = [x for x in ca["bindings"] if x and not same_input(x, b)]
                if pair:
                    ca["bindings"] = (pair + [None, None])[:2]
                else:
                    cfg["custom_actions"] = [x for x in cfg["custom_actions"] if x is not ca]
            continue
        if ca is not None and col.get("special"):
            if slot == "single" and ca["trigger"] in ("press", "short"):
                ca["trigger"] = "short" if long_on else "press"
            continue
        f = ca_fields(col, slot, long_on)
        if ca is None:
            ca = {"id": new_custom_id(cfg), "layer": layer, "bindings": [dict(b), None]}
            cfg["custom_actions"].append(ca)
        ca.update(f)
        tmp = sanitize_config(dict(cfg, custom_actions=[ca]))["custom_actions"][0]
        for k in ("name", "keys", "mode", "trigger", "repeat_ms", "seq", "profile", "steps", "cam"):
            ca[k] = tmp[k]


def slot_signature(cfg, b, layer=0):
    """Что назначено на вход b (по слотам) — для сравнения одной и той же кнопки в разных профилях."""
    return {slot: ca_signature(ca) for slot, ca in find_slots(cfg, b, layer).items()}


def ca_signature(ca):
    return json.dumps([ca["mode"], ca["keys"], ca["trigger"], ca.get("seq", ""), ca["profile"],
                       ca.get("cam", "left"), ca["repeat_ms"], ca["steps"]], sort_keys=True)


def profiles_with(cfg, ca, b, others):
    """Профили (текущий + из others: [(имя, cfg)]), где на входе b в том же слоте и слое назначено то же."""
    sig, slot = ca_signature(ca), slot_of(ca)
    out = [cfg.get("profile_name") or "?"]
    for name, c in others:
        o = find_slots(c, b, ca["layer"]).get(slot)
        if o is not None and ca_signature(o) == sig:
            out.append(name)
    return out


def mapped_rows(cfg, device, others=()):
    """Строки таблицы «Все назначенные действия» (как в RS Mapper)."""
    rows = []
    for ca in cfg["custom_actions"]:
        for b in ca["bindings"]:
            if not b:
                continue
            typ = {"button": "Кнопка", "hat": "Хатка", "axis": "Ось"}[b["type"]]
            key = rep = prof = seq = ""
            m = ca["mode"]
            if m == "profile":
                pt = ca["profile"]
                prof = {"name": (pt["names"] or ["?"])[0], "next": NEXT_P, "prev": PREV_P,
                        "cycle": " → ".join(pt["names"])}[pt["kind"]]
            elif m == "sequence":
                seq = ca.get("seq") or "(свои шаги)"
            elif m == "camera":
                key = "Обзор DCS: " + DCS_CAM_LABEL.get(ca.get("cam"), "?")
            else:
                key = keys_text(ca["keys"])
                if m == "repeat":
                    rep = "%d мс" % ca["repeat_ms"]
                elif m == "hold":
                    rep = "непрерывно"
                elif m == "toggle":
                    rep = "переключатель"
            trig = TRIG_TEXT[ca["trigger"]]
            if cfg["layers"]["enabled"] and ca["layer"]:
                trig += " · слой %d" % ca["layer"]
            name = input_name(cfg, b)
            profs = ", ".join(profiles_with(cfg, ca, b, others))
            rows.append((CUSTOM_PREFIX + ca["id"], b,
                         (typ, device or "—", ca["name"], name, trig, key, rep, prof, seq, profs)))
    return rows


# ----------------------------------------------------------------------
# плитки
# ----------------------------------------------------------------------
class SlotMarks(tk.Frame):
    """Три отметки SP / LP / RL (как три серых флажка в RS Mapper)."""
    def __init__(self, master, vertical=True):
        super().__init__(master, bg=TILE_BG)
        self.lbl = {}
        for i, s in enumerate(SLOTS):
            lb = tk.Label(self, text="☐ " + SLOT_SHORT[s], bg=TILE_BG, fg="#888", font=("Segoe UI", 8))
            lb.grid(row=i if vertical else 0, column=0 if vertical else i, sticky="w")
            self.lbl[s] = lb
        self.state = {s: False for s in SLOTS}

    def set(self, on):
        for s in SLOTS:
            v = bool(on.get(s))
            if v != self.state[s]:
                self.state[s] = v
                self.lbl[s].configure(text=("☑ " if v else "☐ ") + SLOT_SHORT[s], fg="#111" if v else "#888")


def draw_button_icon(cv, pressed):
    cv.delete("all")
    cv.create_rectangle(10, 26, 65, 34, fill="#c8c8c8", outline="#8a8a8a")
    if pressed:
        cv.create_rectangle(28, 14, 47, 26, fill="#22b14c", outline="#1d6b33")
    else:
        cv.create_rectangle(28, 5, 47, 26, fill="#22b14c", outline="#1d6b33")


class ButtonTile(tk.Frame):
    W, H = 200, 55

    def __init__(self, master, b, on_click, on_rename):
        super().__init__(master, width=self.W, height=self.H, bg=TILE_BG, highlightthickness=1,
                         highlightbackground="#d0d0d0")
        self.grid_propagate(False)
        self.b = b
        # название — в своей зоне слева от значка, длинное переносится на 2 строки
        self.name = tk.Label(self, text="", bg=TILE_BG, anchor="w", justify="left", font=("Segoe UI", 8),
                             wraplength=64)
        self.name.place(x=3, y=4, width=67, height=46)
        self.cv = tk.Canvas(self, width=75, height=37, bg="#f0f0f0", highlightthickness=1,
                            highlightbackground="#adadad", cursor="hand2")
        self.cv.place(x=72, y=8)
        self.marks = SlotMarks(self)
        self.marks.place(x=150, y=1)
        self.pressed = None
        self.set_pressed(False)
        for w in (self.cv,):
            w.bind("<Button-1>", lambda e: on_click(self.b))
        for w in (self, self.name, self.cv):
            w.bind("<Button-3>", lambda e: on_rename(self.b))

    def set_pressed(self, p):
        if p != self.pressed:
            self.pressed = p
            draw_button_icon(self.cv, p)


ARROW_PTS = [(-14, -5), (2, -5), (2, -14), (17, 0), (2, 14), (2, 5), (-14, 5)]
DIR_ANGLE = {"e": 0, "ne": -45, "n": -90, "nw": -135, "w": 180, "sw": 135, "s": 90, "se": 45}


def draw_arrow(cv, d, on):
    import math
    cv.delete("all")
    a = math.radians(DIR_ANGLE[d])
    pts = []
    for x, y in ARROW_PTS:
        pts += [22 + x * math.cos(a) - y * math.sin(a), 22 + x * math.sin(a) + y * math.cos(a)]
    cv.create_polygon(pts, fill="#22b14c" if on else "#ffffff", outline="#222", width=2)


class HatTile(tk.LabelFrame):
    def __init__(self, master, hat_index, on_click, on_rename):
        super().__init__(master, text="Хатка %d" % (hat_index + 1), bg=TILE_BG, font=("Segoe UI", 9, "bold"))
        self.cells = {}
        for pos, d in enumerate(HAT8_ORDER):
            if d is None:
                continue
            g = tk.LabelFrame(self, text=HAT8_NAME[d], bg=TILE_BG, width=112, height=110, font=("Segoe UI", 8))
            g.grid(row=pos // 3, column=pos % 3, padx=3, pady=3)
            g.grid_propagate(False)
            marks = SlotMarks(g, vertical=False)
            marks.place(x=2, y=0)
            cv = tk.Canvas(g, width=45, height=45, bg="#f0f0f0", highlightthickness=1,
                           highlightbackground="#adadad", cursor="hand2")
            cv.place(x=50, y=40)
            b = hat_binding(hat_index, d)
            cv.bind("<Button-1>", lambda e, bb=b: on_click(bb))
            for w in (g, cv):
                w.bind("<Button-3>", lambda e, bb=b: on_rename(bb))
            self.cells[d] = {"marks": marks, "cv": cv, "on": None, "frame": g, "b": b}
            self.set_on(d, False)

    def set_on(self, d, on):
        c = self.cells[d]
        if c["on"] != on:
            c["on"] = on
            draw_arrow(c["cv"], d, on)


class AxisTile(tk.LabelFrame):
    """Ось (крутилка, ползунок, РУД…): шкала положения и два направления «−» / «+» как кнопки."""
    BAR_W, BAR_H = 300, 22

    def __init__(self, master, index, view):
        super().__init__(master, text="", bg=TILE_BG, font=("Segoe UI", 9, "bold"))
        self.i, self.view = index, view
        top = tk.Frame(self, bg=TILE_BG)
        top.pack(fill="x", padx=4, pady=(2, 0))
        self.warn = tk.Label(top, text="", bg=TILE_BG, fg="#b45309", font=("Segoe UI", 8), wraplength=230,
                             justify="left", anchor="w")
        self.warn.pack(side="left", fill="x")
        self.off_btn = ttk.Button(top, text="Откл. аналог", width=12, command=self._analog_off)
        self.bar = tk.Canvas(self, width=self.BAR_W, height=self.BAR_H, bg="#f4f4f4", highlightthickness=1,
                             highlightbackground="#bbb")
        self.bar.pack(padx=6, pady=(2, 2))
        row = tk.Frame(self, bg=TILE_BG)
        row.pack(fill="x", padx=4, pady=(0, 4))
        self.dirs = {}
        for d, side in (("-", "left"), ("+", "right")):
            f = tk.Frame(row, bg=TILE_BG)
            f.pack(side=side, padx=4)
            cv = tk.Canvas(f, width=56, height=30, bg="#f0f0f0", highlightthickness=1,
                           highlightbackground="#adadad", cursor="hand2")
            cv.grid(row=0, column=0, rowspan=2)
            marks = SlotMarks(f, vertical=False)
            marks.grid(row=0, column=1, sticky="w", padx=4)
            thr = ttk.Button(f, text="", width=13, command=lambda dd=d: self.view.ask_thr(self.i, dd))
            thr.grid(row=1, column=1, sticky="w", padx=4)
            cv.bind("<Button-1>", lambda e, dd=d: self.view.open_dialog(self._binding(dd)))
            cv.bind("<Button-3>", lambda e, dd=d: self.view.rename(self._binding(dd)))
            self.dirs[d] = {"cv": cv, "marks": marks, "thr": thr, "on": None}
            self._draw_dir(d, False)
        for w in (self, self.bar):
            w.bind("<Button-3>", lambda e: self.view.rename_axis(self.i))
        self._v = None

    def _binding(self, d):
        return axis_binding(self.i, d, axis_thr(self.view.app.cfg, self.i, d))

    def _analog_off(self):
        self.view.disable_analog(self.i)

    def _draw_dir(self, d, on):
        cv = self.dirs[d]["cv"]
        cv.delete("all")
        pts = (44, 8, 18, 15, 44, 22) if d == "-" else (12, 8, 38, 15, 12, 22)
        cv.create_polygon(pts, fill="#22b14c" if on else "#ffffff", outline="#222", width=2)

    def refresh(self, cfg, layer):
        self.configure(text="%s  (ось %d)" % (axis_name(cfg, self.i), self.i + 1))
        roles = axis_roles(cfg, self.i)
        if roles:
            names = ", ".join(dict(AXIS_ROLES)[r].split(" (")[0] for r in roles)
            self.warn.configure(text="⚠ работает как %s — будет двойное срабатывание" % names)
            self.off_btn.pack(side="right")
        else:
            self.warn.configure(text="")
            self.off_btn.pack_forget()
        for d, c in self.dirs.items():
            c["marks"].set(find_slots(cfg, self._binding(d), layer))
            t = axis_thr(cfg, self.i, d)
            c["thr"].configure(text=("− : ≤ %+.2f" if d == "-" else "+ : ≥ %+.2f") % t)
        self._v = None

    def set_value(self, v, cfg):
        if self._v is not None and abs(v - self._v) < 0.01:
            return
        self._v = v
        W, H = self.BAR_W, self.BAR_H
        x = lambda val: 2 + (max(-1.0, min(1.0, val)) + 1) / 2 * (W - 4)
        b = self.bar
        b.delete("all")
        b.create_rectangle(min(x(0), x(v)), 4, max(x(0), x(v)), H - 4, fill="#3b82f6", width=0)
        b.create_line(x(0), 2, x(0), H - 2, fill="#999")
        for d in ("-", "+"):
            t = axis_thr(cfg, self.i, d)
            b.create_line(x(t), 0, x(t), H, fill="#ef4444", width=2)
        b.create_text(W - 4, H // 2, text="%+.2f" % v, anchor="e", font=("Consolas", 8))
        for d in ("-", "+"):
            t = axis_thr(cfg, self.i, d)
            on = v >= t if d == "+" else v <= t
            if on != self.dirs[d]["on"]:
                self.dirs[d]["on"] = on
                self._draw_dir(d, on)


# ----------------------------------------------------------------------
# окно «Выбор срабатывающего действия»
# ----------------------------------------------------------------------
class ActionColumn(tk.Frame):
    def __init__(self, master, slot, sequences, profiles, pick_key, edit_seqs=None):
        super().__init__(master)
        self.pick_key = pick_key
        self.en = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text=SLOT_TITLE[slot], variable=self.en, command=self._state).pack(anchor="w", pady=(4, 6))
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        b = self.body
        ttk.Label(b, text="Название:").pack(anchor="w")
        self.name = tk.StringVar()
        ttk.Entry(b, textvariable=self.name, width=26).pack(anchor="w", pady=(0, 6))
        self.kind = tk.StringVar(value="key")
        ttk.Radiobutton(b, text="Нажатие клавиши", variable=self.kind, value="key", command=self._state).pack(anchor="w")
        gk = ttk.LabelFrame(b, text="")
        gk.pack(fill="x", pady=(0, 6))
        ttk.Label(gk, text="Модификатор:").grid(row=0, column=0, columnspan=3, sticky="w", padx=4)
        self.mods = {}
        for i, k in enumerate(MODIFIER_KEYS):
            v = tk.BooleanVar()
            ttk.Checkbutton(gk, text=MOD_LABEL[k], variable=v).grid(row=1 + i // 3, column=i % 3, sticky="w", padx=2)
            self.mods[k] = v
        ttk.Label(gk, text="Клавиша:").grid(row=3, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 0))
        self.key = ttk.Combobox(gk, state="readonly", width=16, values=[key_text(k) for k in PLAIN_KEYS])
        self.key.grid(row=4, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Button(gk, text="…", width=3, command=self._capture).grid(row=4, column=2, sticky="w")
        self.rep = tk.BooleanVar()
        ttk.Checkbutton(gk, text="Повтор, мс", variable=self.rep).grid(row=5, column=0, columnspan=2, sticky="w", padx=2, pady=(4, 0))
        self.rep_ms = tk.StringVar(value="100")
        ttk.Spinbox(gk, from_=30, to=2000, increment=10, width=6, textvariable=self.rep_ms).grid(
            row=5, column=2, sticky="w", pady=(4, 0))
        self.cont = tk.BooleanVar()
        ttk.Checkbutton(gk, text="непрерывно (держать)", variable=self.cont).grid(
            row=6, column=0, columnspan=3, sticky="w", padx=2, pady=(0, 4))
        ttk.Radiobutton(b, text="Последовательность нажатий", variable=self.kind, value="seq",
                        command=self._state).pack(anchor="w")
        gs = ttk.LabelFrame(b, text="")
        gs.pack(fill="x", pady=(0, 6))
        ttk.Label(gs, text="Последовательность:").pack(anchor="w", padx=4)
        sr = ttk.Frame(gs)
        sr.pack(anchor="w", padx=4, pady=(0, 4))
        self.seq = ttk.Combobox(sr, state="readonly", width=22, values=list(sequences))
        self.seq.pack(side="left")
        if edit_seqs:
            ttk.Button(sr, text="Создать / изменить…", command=lambda: edit_seqs(self)).pack(side="left", padx=(4, 0))
        ttk.Radiobutton(b, text="Смена профиля", variable=self.kind, value="profile",
                        command=self._state).pack(anchor="w")
        gp = ttk.LabelFrame(b, text="")
        gp.pack(fill="x")
        ttk.Label(gp, text="Новый профиль:").pack(anchor="w", padx=4)
        self.prof = ttk.Combobox(gp, state="readonly", width=22, values=list(profiles) + [NEXT_P, PREV_P])
        self.prof.pack(anchor="w", padx=4, pady=(0, 4))
        ttk.Radiobutton(b, text="Обзор DCS (правый стик геймпада)", variable=self.kind, value="cam",
                        command=self._state).pack(anchor="w", pady=(6, 0))
        gc = ttk.LabelFrame(b, text="")
        gc.pack(fill="x")
        ttk.Label(gc, text="Команда DCS:").pack(anchor="w", padx=4)
        self.cam = ttk.Combobox(gc, state="readonly", width=46, values=[t for _k, t, _p in DCS_CAM])
        self.cam.pack(anchor="w", padx=4)
        ttk.Label(gc, foreground="#555", wraplength=330, justify="left", text=(
            "Нужен виртуальный геймпад (вкладка «Главная»). В DCS правый стик назначьте на "
            "«Камера в кабине, горизонталь (абсолют)» и «… вертикаль (абсолют)».")
            ).pack(anchor="w", padx=4, pady=(2, 4))
        self.special_lbl = ttk.Label(b, text="", foreground="#b45309", wraplength=180, justify="left")
        self.special_lbl.pack(anchor="w", pady=(6, 0))
        self.special = False
        self._state()

    def _capture(self):
        r = self.pick_key()
        if r:
            for k in r:
                if k in MODIFIER_KEYS:
                    self.mods[k].set(True)
            rest = [k for k in r if k not in MODIFIER_KEYS]
            if rest:
                self.key.set(key_text(rest[0]))

    def _state(self):
        st = "normal" if self.en.get() and not self.special else "disabled"

        def walk(w):
            for ch in w.winfo_children():
                try:
                    if isinstance(ch, ttk.Combobox):
                        ch.configure(state="readonly" if st == "normal" else "disabled")
                    elif not isinstance(ch, (ttk.Frame, ttk.LabelFrame, tk.Frame)):
                        ch.configure(state=st)
                except tk.TclError:
                    pass
                walk(ch)
        walk(self.body)
        self.special_lbl.configure(state="normal")

    def set(self, col):
        self.en.set(col.get("enabled", False))
        self.special = bool(col.get("special"))
        self.name.set(col.get("name", ""))
        self.kind.set(col.get("kind", "key"))
        for k, v in self.mods.items():
            v.set(k in col.get("mods", []))
        self.key.set(key_text(col["key"]) if col.get("key") else "")
        self.rep.set(col.get("repeat", False))
        self.rep_ms.set(str(col.get("repeat_ms", 100)))
        self.cont.set(col.get("continuous", False))
        self.seq.set(col.get("seq", ""))
        self.prof.set(col.get("profile", ""))
        self.cam.set(DCS_CAM_LABEL.get(col.get("cam") or "left", ""))
        self.special_lbl.configure(text="Это действие настроено особо (переключатель / профили по кругу / свои "
                                        "шаги) — меняется на вкладке «Назначение»." if self.special else "")
        self._state()

    def get(self):
        names = [key_text(k) for k in PLAIN_KEYS]
        kt = self.key.get()
        try:
            rep_ms = max(30, min(2000, int(float(self.rep_ms.get()))))
        except ValueError:
            rep_ms = 100
        return {"enabled": bool(self.en.get()), "special": self.special, "name": self.name.get(),
                "kind": self.kind.get(), "mods": [k for k, v in self.mods.items() if v.get()],
                "key": PLAIN_KEYS[names.index(kt)] if kt in names else "", "repeat": bool(self.rep.get()),
                "repeat_ms": rep_ms, "continuous": bool(self.cont.get()), "seq": self.seq.get(),
                "profile": self.prof.get(),
                "cam": next((k for k, t, _p in DCS_CAM if t == self.cam.get()), "left")}


class RsActionDialog(tk.Toplevel):
    def __init__(self, master, title, cols, sequences, profiles, pick_key, share=None, edit_seqs=None):
        super().__init__(master)
        self.title("Выбор срабатывающего действия — " + title)
        self._edit_seqs_cb = edit_seqs
        self.profiles = None
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=5, pady=5)
        self.cols = {}
        for i, s in enumerate(SLOTS):
            c = ActionColumn(body, s, sequences, profiles, pick_key,
                             edit_seqs=self._edit_seqs if edit_seqs else None)
            c.grid(row=0, column=i, sticky="n", padx=5)
            c.set(cols[s])
            self.cols[s] = c
        ttk.Label(self, foreground="#555", wraplength=600, justify="left", text=(
            "Если включено долгое нажатие, обычное срабатывает, только если отпустить кнопку раньше порога "
            "(«Режимы и автопрофиль» → «Долгое нажатие»). «Непрерывно» — клавиша держится, пока держите "
            "кнопку; без него — одно короткое нажатие.")).pack(anchor="w", padx=10)
        self.prof_vars = {}
        if share:                      # (все профили, текущий, где уже так же)
            names, cur, same = share
            pf = ttk.LabelFrame(self, text="Применить и в профилях (галочка — у этой кнопки там так же)")
            pf.pack(fill="x", padx=10, pady=(6, 0))
            row = ttk.Frame(pf)
            row.pack(fill="x", padx=6, pady=(2, 0))
            for i, n in enumerate(names):
                v = tk.BooleanVar(value=(n == cur or n in same))
                cb = ttk.Checkbutton(row, text=n + (" (текущий)" if n == cur else ""), variable=v)
                cb.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 14))
                if n == cur:
                    cb.state(["disabled"])
                else:
                    self.prof_vars[n] = v
            br = ttk.Frame(pf)
            br.pack(fill="x", padx=6, pady=(2, 6))
            ttk.Button(br, text="Все", command=lambda: [v.set(True) for v in self.prof_vars.values()]
                       ).pack(side="left")
            ttk.Button(br, text="Ни одного", command=lambda: [v.set(False) for v in self.prof_vars.values()]
                       ).pack(side="left", padx=4)
            ttk.Label(br, foreground="#555", text="Снятая галочка убирает это назначение кнопки в том профиле."
                      ).pack(side="left", padx=8)
        bf = ttk.Frame(self)
        bf.pack(fill="x", padx=10, pady=10)
        ttk.Button(bf, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="OK", command=self._ok).pack(side="right", padx=6)
        self.grab_set()

    def _edit_seqs(self, col):
        """Окно последовательностей прямо из колонки; после — обновить списки, новую выбрать в этой колонке."""
        before = list(col.seq.cget("values"))
        names = self._edit_seqs_cb()
        for c in self.cols.values():
            c.seq.configure(values=names)
            if c.seq.get() not in names:
                c.seq.set("")
        new = [n for n in names if n not in before]
        if new:
            col.seq.set(new[-1])
            col.kind.set("seq")

    def _ok(self):
        cols = {s: c.get() for s, c in self.cols.items()}
        for s, col in cols.items():
            p = column_problem(col)
            if p:
                messagebox.showwarning("Действие", f"{SLOT_TITLE[s]}: {p}.", parent=self)
                return
        self.result = cols
        self.profiles = {n for n, v in self.prof_vars.items() if v.get()}
        self.destroy()


# ----------------------------------------------------------------------
# менеджер последовательностей (как «Sequences management»)
# ----------------------------------------------------------------------
class SequenceManager(tk.Toplevel):
    def __init__(self, master, cfg, on_change, pick_key):
        super().__init__(master)
        self.title("Управление последовательностями")
        self.transient(master)
        self.cfg, self.on_change, self.pick_key = cfg, on_change, pick_key
        left = ttk.LabelFrame(self, text="Доступные последовательности")
        left.pack(side="left", fill="y", padx=6, pady=6)
        self.lb = tk.Listbox(left, width=28, height=18, exportselection=False)
        self.lb.pack(padx=6, pady=6)
        self.lb.bind("<<ListboxSelect>>", lambda e: self._load())
        bl = ttk.Frame(left)
        bl.pack(pady=(0, 6))
        ttk.Button(bl, text="Новая", command=self.new_seq).pack(side="left")
        ttk.Button(bl, text="Переименовать", command=self.rename_seq).pack(side="left", padx=4)
        ttk.Button(bl, text="Удалить", command=self.delete_seq).pack(side="left")
        right = ttk.LabelFrame(self, text="Действия в последовательности")
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        cols = ("name", "key", "delay", "dur")
        self.tv = ttk.Treeview(right, columns=cols, show="headings", height=10, selectmode="browse")
        for c, t, w in zip(cols, ("Название", "Клавиша", "Задержка от начала, мс", "Длительность, мс"),
                           (110, 150, 160, 110)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w)
        self.tv.pack(fill="both", expand=True, padx=6, pady=6)
        self.tv.bind("<<TreeviewSelect>>", lambda e: self._load_step())
        ed = ttk.LabelFrame(right, text="Действие")
        ed.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(ed, text="Название:").grid(row=0, column=0, sticky="w", padx=4)
        self.s_name = tk.StringVar()
        ttk.Entry(ed, textvariable=self.s_name, width=18).grid(row=0, column=1, sticky="w")
        ttk.Label(ed, text="Модификатор:").grid(row=1, column=0, sticky="w", padx=4)
        mf = ttk.Frame(ed)
        mf.grid(row=1, column=1, columnspan=4, sticky="w")
        self.mods = {}
        for k in MODIFIER_KEYS:
            v = tk.BooleanVar()
            ttk.Checkbutton(mf, text=MOD_LABEL[k], variable=v).pack(side="left")
            self.mods[k] = v
        ttk.Label(ed, text="Клавиша:").grid(row=2, column=0, sticky="w", padx=4)
        self.s_key = ttk.Combobox(ed, state="readonly", width=16, values=[key_text(k) for k in PLAIN_KEYS])
        self.s_key.grid(row=2, column=1, sticky="w")
        ttk.Button(ed, text="…", width=3, command=self._capture).grid(row=2, column=2, sticky="w")
        ttk.Label(ed, text="Задержка от начала, мс:").grid(row=3, column=0, sticky="w", padx=4)
        self.s_delay = tk.StringVar(value="0")
        f3 = ttk.Frame(ed)
        f3.grid(row=3, column=1, columnspan=6, sticky="w")
        ttk.Spinbox(f3, from_=0, to=SEQ_MAX_DELAY_MS, increment=100, width=8,
                    textvariable=self.s_delay).pack(side="left")
        ttk.Label(f3, foreground="#555", text="мс от нажатия кнопки X52 (а НЕ от предыдущего шага)").pack(
            side="left", padx=(6, 0))
        ttk.Label(ed, text="Длительность, мс:").grid(row=4, column=0, sticky="w", padx=4)
        self.s_dur = tk.StringVar(value="100")
        f4 = ttk.Frame(ed)
        f4.grid(row=4, column=1, columnspan=6, sticky="w")
        ttk.Spinbox(f4, from_=10, to=10000, increment=10, width=8, textvariable=self.s_dur).pack(side="left")
        ttk.Label(f4, foreground="#555", text="мс — сколько держать клавишу нажатой (обычно 100)").pack(
            side="left", padx=(6, 0))
        ttk.Label(ed, foreground="#555", text=SEQ_TIME_HINT).grid(row=5, column=0, columnspan=5, sticky="w", padx=4)
        be = ttk.Frame(ed)
        be.grid(row=6, column=0, columnspan=5, sticky="w", padx=4, pady=6)
        ttk.Button(be, text="Добавить", command=self.add_step).pack(side="left")
        ttk.Button(be, text="Сохранить изменения", command=self.update_step).pack(side="left", padx=4)
        ttk.Button(be, text="Удалить", command=self.delete_step).pack(side="left")
        ttk.Button(self, text="Закрыть", command=self.destroy).pack(side="bottom", anchor="e", padx=6, pady=6)
        self._refresh()

    def _seq(self):
        s = self.lb.curselection()
        return self.cfg["sequences"][s[0]] if s and s[0] < len(self.cfg["sequences"]) else None

    def _refresh(self, select=None):
        self.lb.delete(0, "end")
        for i, sq in enumerate(self.cfg["sequences"]):
            self.lb.insert("end", sq["name"])
            if sq["name"] == select:
                self.lb.selection_set(i)
        self._load()

    def _load(self):
        self.tv.delete(*self.tv.get_children())
        sq = self._seq()
        if sq:
            for i, st in enumerate(sq["steps"]):
                self.tv.insert("", "end", iid=str(i), values=(st.get("name", ""), keys_text(st["keys"]),
                                                              st["delay_ms"], st["duration_ms"]))

    def _changed(self, keep=None):
        self.on_change()
        self._refresh(keep)

    def new_seq(self, name=None):
        name = name or simpledialog.askstring("Новая последовательность", "Название:", parent=self)
        name = (name or "").strip()[:60]
        if not name:
            return
        if name in [s["name"] for s in self.cfg["sequences"]]:
            messagebox.showwarning("Последовательность", f"«{name}» уже есть.", parent=self)
            return
        self.cfg["sequences"].append({"name": name, "steps": []})
        self._changed(name)

    def rename_seq(self, new=None):
        sq = self._seq()
        if not sq:
            return
        new = new or simpledialog.askstring("Переименовать", "Новое название:", initialvalue=sq["name"], parent=self)
        new = (new or "").strip()[:60]
        if not new or new in [s["name"] for s in self.cfg["sequences"]]:
            return
        for ca in self.cfg["custom_actions"]:           # действия ссылаются по имени — обновить
            if ca.get("seq") == sq["name"]:
                ca["seq"] = new
        sq["name"] = new
        self._changed(new)

    def delete_seq(self, confirm=True):
        sq = self._seq()
        if not sq:
            return
        used = [ca["name"] for ca in self.cfg["custom_actions"] if ca.get("seq") == sq["name"]]
        msg = f"Удалить «{sq['name']}»?" + (f"\nЕё используют: {', '.join(used)}" if used else "")
        if confirm and not messagebox.askyesno("Удалить последовательность", msg, parent=self):
            return
        self.cfg["sequences"] = [s for s in self.cfg["sequences"] if s is not sq]
        self._changed()

    def _capture(self):
        r = self.pick_key()
        if r:
            for k in r:
                if k in MODIFIER_KEYS:
                    self.mods[k].set(True)
            rest = [k for k in r if k not in MODIFIER_KEYS]
            if rest:
                self.s_key.set(key_text(rest[0]))

    def _step_from_editor(self):
        names = [key_text(k) for k in PLAIN_KEYS]
        kt = self.s_key.get()
        keys = [k for k in MODIFIER_KEYS if self.mods[k].get()] + ([PLAIN_KEYS[names.index(kt)]] if kt in names else [])
        try:
            delay, dur = int(float(self.s_delay.get())), int(float(self.s_dur.get()))
        except ValueError:
            delay, dur = -1, -1
        st = clean_steps([{"keys": keys, "delay_ms": delay, "duration_ms": dur, "name": self.s_name.get()}])
        if not st or delay < 0:
            messagebox.showwarning("Действие", "Выберите клавишу и укажите время в мс.", parent=self)
            return None
        return st[0]

    def _load_step(self):
        sq, s = self._seq(), self.tv.selection()
        if not sq or not s:
            return
        st = sq["steps"][int(s[0])]
        self.s_name.set(st.get("name", ""))
        for k, v in self.mods.items():
            v.set(k in st["keys"])
        rest = [k for k in st["keys"] if k not in MODIFIER_KEYS]
        self.s_key.set(key_text(rest[0]) if rest else "")
        self.s_delay.set(str(st["delay_ms"]))
        self.s_dur.set(str(st["duration_ms"]))

    def add_step(self):
        sq = self._seq()
        if not sq:
            messagebox.showinfo("Последовательность", "Сначала создайте или выберите последовательность.", parent=self)
            return
        st = self._step_from_editor()
        if st:
            sq["steps"] = clean_steps(sq["steps"] + [st])
            self.s_delay.set(str(st["delay_ms"] + st["duration_ms"] + 100))
            self.s_name.set("")                   # следующий шаг — с чистого листа (модификаторы не переносятся)
            for v in self.mods.values():
                v.set(False)
            self.s_key.set("")
            self._changed(sq["name"])

    def update_step(self):
        sq, s = self._seq(), self.tv.selection()
        if not sq or not s:
            messagebox.showinfo("Последовательность", "Выберите в списке шаг, который нужно изменить, "
                                                       "поправьте поля и нажмите «Сохранить изменения».", parent=self)
            return
        st = self._step_from_editor()
        if st:
            steps = list(sq["steps"])
            steps[int(s[0])] = st
            sq["steps"] = clean_steps(steps)
            self._changed(sq["name"])
            i = next((i for i, x in enumerate(sq["steps"]) if x == st), None)
            if i is not None:                     # шаг остаётся выбранным — можно править дальше
                self.tv.selection_set(str(i))
                self.tv.see(str(i))

    def delete_step(self):
        sq, s = self._seq(), self.tv.selection()
        if sq and s:
            del sq["steps"][int(s[0])]
            self._changed(sq["name"])


# ----------------------------------------------------------------------
# главный вид
# ----------------------------------------------------------------------
class RsView(ttk.Frame):
    COLS = (("type", "Тип", 70), ("device", "Устройство", 170), ("name", "Название действия", 150),
            ("input", "Кнопка", 100), ("trig", "Срабатывание", 120), ("key", "Клавиша", 120),
            ("rep", "Повтор", 80), ("prof", "Новый профиль", 110), ("seq", "Последовательность", 120),
            ("profs", "Профили", 220))

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.pack(fill="both", expand=True)
        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True)
        left = ttk.Frame(pw)
        right = ttk.Frame(pw)
        pw.add(left, weight=1)
        pw.add(right, weight=3)
        self.dev = ttk.Treeview(left, columns=("name", "id"), show="headings", selectmode="browse")
        self.dev.heading("name", text="Имя устройства")
        self.dev.heading("id", text="ID")
        self.dev.column("name", width=190)
        self.dev.column("id", width=40, anchor="center")
        self.dev.pack(fill="both", expand=True)
        self.dev.bind("<<TreeviewSelect>>", lambda e: self._dev_selected())
        self._devs = None

        top = ttk.Frame(right)
        top.pack(fill="x")
        ttk.Label(top, text="Все назначенные действия:").pack(anchor="w", pady=(6, 2))
        tf = ttk.Frame(top)
        tf.pack(fill="x")
        self.acts = ttk.Treeview(tf, columns=[c[0] for c in self.COLS], show="headings", height=8,
                                 selectmode="browse")
        for c, t, w in self.COLS:
            self.acts.heading(c, text=t)
            self.acts.column(c, width=w, stretch=False)
        hs = ttk.Scrollbar(tf, orient="horizontal", command=self.acts.xview)
        vs = ttk.Scrollbar(tf, orient="vertical", command=self.acts.yview)
        self.acts.configure(xscrollcommand=hs.set, yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.acts.pack(fill="x")
        hs.pack(fill="x")
        self.acts.bind("<Double-1>", lambda e: self._open_from_list())
        self._row_input = {}

        lay = ttk.Frame(right)
        lay.pack(fill="x", pady=(6, 2))
        ttk.Label(lay, text="Щёлкните по кнопке на плитке, чтобы назначить действие; правый щелчок — название.",
                  foreground="#555").pack(side="left")
        self.layer_box = ttk.Frame(lay)
        ttk.Label(self.layer_box, text="Слой:").pack(side="left")
        self.layer = ttk.Combobox(self.layer_box, state="readonly", width=10,
                                  values=["все слои", "слой 1", "слой 2", "слой 3"])
        self.layer.current(0)
        self.layer.pack(side="left", padx=4)
        self.layer.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.follow = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.layer_box, text="за колесом", variable=self.follow,
                        command=lambda: setattr(self, "_seen_layer", None)).pack(side="left")
        self._seen_layer = None

        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)
        self._scroll_canvases = set()
        # колёсико мыши прокручивает область под курсором (над любой плиткой, а не только над полосой)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.app.bind_all(seq, self._on_wheel, add="+")
        self.btn_area = self._scroll_area("Кнопки")
        self.hat_area = self._scroll_area("Хатки")
        self.axis_area = self._scroll_area("Оси (крутилки, ползунок, РУД…)")
        self._build_ministick_tab()
        self._build_zoom_tab()
        self.btn_tiles = []
        self.hat_tiles = []
        self.axis_tiles = []
        self._cols = 0
        self._hat_title = "Хатки"

    def _build_ministick_tab(self):
        """Вкладка «Мини-стик»: 2D-превью + настройки (вкл., чувств.,
        мёртвая зона, инверсия X/Y) + статус."""
        fr = ttk.Frame(self.nb)
        self.nb.add(fr, text="Мини-стик")
        self.ministick_tab = fr
        app = self.app
        # прокручиваемая область: всё содержимое доступно при любой высоте окна
        bg = ttk.Style().lookup("TFrame", "background") or "#f0f0f0"
        cv = tk.Canvas(fr, highlightthickness=0, yscrollincrement=20, bg=bg)
        sb = ttk.Scrollbar(fr, orient="vertical", command=cv.yview)
        hsb = ttk.Scrollbar(fr, orient="horizontal", command=cv.xview)
        cv.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
        sb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        cv.pack(side="left", fill="both", expand=True)
        pw = ttk.Frame(cv)
        cv.create_window(0, 0, window=pw, anchor="nw")
        pw.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        self._scroll_canvases.add(cv)
        # три колонки: превью | основные настройки | режим обзора и клавиши
        left = ttk.Frame(pw)
        left.grid(row=0, column=0, padx=(12, 20), pady=10, sticky="n")
        right = ttk.Frame(pw)
        right.grid(row=0, column=1, padx=(0, 12), pady=10, sticky="n")

        size = 220
        self.ministick_canvas = tk.Canvas(left, width=size, height=size, bg="#eef2f6",
                                          highlightthickness=1, highlightbackground="#adadad")
        self.ministick_canvas.pack()
        c = self.ministick_canvas
        c.create_rectangle(2, 2, size, size, outline="#8898a6")
        mid = size // 2
        c.create_line(mid, 10, mid, size - 10, fill="#cfd6de")
        c.create_line(10, mid, size - 10, mid, fill="#cfd6de")
        c.create_oval(mid - 60, mid - 60, mid + 60, mid + 60, outline="#cfd6de")
        r = 7
        self._ms_dot = c.create_oval(mid - r, mid - r, mid + r, mid + r,
                                     fill="#ef4444", outline="#991111")
        self._ms_size = size
        self._ms_mid = mid
        self.ministick_vals_lbl = ttk.Label(left, text="X: +0.00    Y: +0.00",
                                            font=("TkDefaultFont", 10, "bold"))
        self.ministick_vals_lbl.pack(pady=(6, 0))

        ttk.Label(right, text="Мини-стик X52 (на РУДе)",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Label(right, wraplength=300, justify="left", foreground="#555", text=(
            "Прошивкой X52 non-Pro мини-стик выставлен как мышь, а не ось. Лаунчер читает его "
            "напрямую из HID-отчёта. Данные идут в cam_x / cam_y, если роли на вкладке «Оси» "
            "не назначены на реальную ось. Точность — 16 шагов на ось (ограничение X52).")
            ).pack(anchor="w", pady=(0, 10))

        self.ministick_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Включить мини-стик в текущем профиле",
                        variable=self.ministick_var,
                        command=app.on_ministick_toggle).pack(anchor="w", pady=2)
        pf = ttk.LabelFrame(right, text="Мини-стик работает в профилях")
        pf.pack(fill="x", pady=(4, 4))
        ttk.Label(pf, foreground="#555", wraplength=280, justify="left", text=(
            "Настройки этой вкладки — свои в каждом профиле. Отметьте профили, где мини-стик "
            "нужен — в них сам включится и виртуальный геймпад.")).pack(anchor="w", padx=6, pady=(2, 2))
        self.ms_prof_frame = ttk.Frame(pf)
        self.ms_prof_frame.pack(fill="x", padx=6, pady=(0, 4))
        self.ms_prof_vars = {}

        ttk.Label(right, text="Чувствительность").pack(anchor="w", pady=(10, 0))
        self.ministick_sens = tk.Scale(right, from_=0.1, to=3.0, resolution=0.1,
                                       orient="horizontal", length=260,
                                       command=lambda v: app.on_ministick_sens(float(v)))
        self.ministick_sens.pack(anchor="w")

        ttk.Label(right, text="Мёртвая зона").pack(anchor="w", pady=(6, 0))
        self.ministick_dz = tk.Scale(right, from_=0.0, to=0.40, resolution=0.01,
                                     orient="horizontal", length=260,
                                     command=lambda v: app.on_ministick_dz(float(v)))
        self.ministick_dz.pack(anchor="w")

        ttk.Label(right, text="Кривая (1 — линейно; больше — малые отклонения медленнее, точнее)",
                  wraplength=300, justify="left").pack(anchor="w", pady=(6, 0))
        self.ministick_curve = tk.Scale(right, from_=1.0, to=3.0, resolution=0.1,
                                        orient="horizontal", length=260,
                                        command=lambda v: app.on_ministick_val("curve", float(v)))
        self.ministick_curve.pack(anchor="w")
        self.ministick_lock = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Фиксация оси", variable=self.ministick_lock,
                        command=lambda: app.on_ministick_val("axis_lock", bool(self.ministick_lock.get()))
                        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(right, foreground="#555", wraplength=300, justify="left", text=(
            "Вбок — без вертикали, вверх/вниз — без горизонтали; диагональ — только при сильном "
            "отклонении в обе стороны.")).pack(anchor="w")

        self.ministick_inv_x = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Инвертировать X (горизонталь)",
                        variable=self.ministick_inv_x,
                        command=lambda: app.on_ministick_invert("x")).pack(anchor="w", pady=(8, 2))
        self.ministick_inv_y = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Инвертировать Y (вертикаль)",
                        variable=self.ministick_inv_y,
                        command=lambda: app.on_ministick_invert("y")).pack(anchor="w", pady=2)

        self.ministick_lbl = ttk.Label(right, text="", foreground="#555",
                                       wraplength=300, justify="left")
        self.ministick_lbl.pack(anchor="w", pady=(14, 0))

        # --- режим обзора: тот же cfg["camera"] и те же обработчики, что на вкладке «Обзор» ---
        xv = ttk.LabelFrame(left, text="Режим обзора (когда opentrack выключен)")
        xv.pack(fill="x", pady=(12, 0))
        self.ms_mode_var = tk.StringVar(value="stick")
        ttk.Radiobutton(xv, variable=self.ms_mode_var, value="stick",
                        text="Как стик — камера смотрит, пока держишь\nмини-стик, потом возвращается",
                        command=app.on_cam_mode_from_ms).pack(anchor="w", padx=8, pady=(6, 0))
        ttk.Radiobutton(xv, variable=self.ms_mode_var, value="mouse",
                        text="Как мышь — мини-стик поворачивает камеру,\nи она остаётся повёрнутой; возврат в центр —\n"
                             "кнопкой «Центровка обзора»",
                        command=app.on_cam_mode_from_ms).pack(anchor="w", padx=8)
        ttk.Label(xv, text="Скорость «мыши» (доля обзора в секунду):").pack(anchor="w", padx=8, pady=(6, 0))
        self.ms_cam_speed = tk.Scale(xv, from_=0.2, to=6.0, resolution=0.1,
                                     orient="horizontal", length=260,
                                     command=lambda v: app.on_cam_val_from_ms("speed", v))
        self.ms_cam_speed.pack(anchor="w", padx=8)
        ttk.Label(xv, text="Скорость поворота «как стик» (0 = мгновенно):").pack(anchor="w", padx=8, pady=(6, 0))
        self.ms_cam_stick_speed = tk.Scale(xv, from_=0.0, to=10.0, resolution=0.1,
                                           orient="horizontal", length=260,
                                           command=lambda v: app.on_cam_val_from_ms("stick_speed", v))
        self.ms_cam_stick_speed.pack(anchor="w", padx=8)
        ttk.Label(xv, text="Насколько далеко поворачивается обзор (1.0 = полностью):"
                  ).pack(anchor="w", padx=8, pady=(6, 0))
        self.ms_cam_max = tk.Scale(xv, from_=0.2, to=1.0, resolution=0.05,
                                   orient="horizontal", length=260,
                                   command=lambda v: app.on_cam_val_from_ms("max", v))
        self.ms_cam_max.pack(anchor="w", padx=8)
        ttk.Button(xv, text="Центровать обзор сейчас",
                   command=lambda: app.worker.send("center")).pack(anchor="w", padx=8, pady=(6, 8))

        # --- привязки клавиш к направлениям ---
        kb = ttk.LabelFrame(right, text="Клавиши на направления мини-стика")
        kb.pack(fill="x", pady=(14, 0))
        right = kb
        ttk.Label(right, foreground="#555", wraplength=380, justify="left", text=(
            "Когда мини-стик отклонён за порог в указанную сторону, "
            "лаунчер нажимает заданную клавишу. Нажмите «Задать…» и затем "
            "клавишу на клавиатуре.")).pack(anchor="w", padx=8, pady=(4, 4))
        self.ms_bind_lbl = {}
        for direction, label in (("up", "↑ Вверх"), ("down", "↓ Вниз"),
                                 ("left", "← Влево"), ("right", "→ Вправо")):
            row = ttk.Frame(right)
            row.pack(anchor="w", padx=8, pady=1, fill="x")
            ttk.Label(row, text=label, width=10).pack(side="left")
            lb = ttk.Label(row, text="—", width=16, foreground="#999",
                           relief="sunken", anchor="w")
            lb.pack(side="left", padx=4)
            self.ms_bind_lbl[direction] = lb
            ttk.Button(row, text="Задать…",
                       command=lambda d=direction: app.on_ms_bind_set(d)
                       ).pack(side="left", padx=2)
            ttk.Button(row, text="Очистить",
                       command=lambda d=direction: app.on_ms_bind_clear(d)
                       ).pack(side="left", padx=2)
        ttk.Label(right, text="Порог срабатывания").pack(anchor="w", padx=8, pady=(6, 0))
        self.ms_bind_thr = tk.Scale(right, from_=0.1, to=0.95, resolution=0.05,
                                    orient="horizontal", length=260,
                                    command=lambda v: app.on_ms_bind_thr(float(v)))
        self.ms_bind_thr.pack(anchor="w", padx=8, pady=(0, 8))

    def apply_ministick_cfg(self, ms):
        """Поставить состояние виджетов из конфига."""
        self.ministick_var.set(bool(ms.get("enabled", False)))
        self.ministick_sens.set(float(ms.get("sens", 0.5)))
        self.ministick_dz.set(float(ms.get("deadzone", 0.08)))
        self.ministick_curve.set(float(ms.get("curve", 1.0)))
        self.ministick_lock.set(bool(ms.get("axis_lock", False)))
        self.ministick_inv_x.set(bool(ms.get("invert_x", False)))
        self.ministick_inv_y.set(bool(ms.get("invert_y", False)))
        cam = self.app.cfg["camera"]
        self.ms_mode_var.set(cam["mode"])
        self.ms_cam_speed.set(cam["speed"])
        self.ms_cam_stick_speed.set(cam["stick_speed"])
        self.ms_cam_max.set(cam["max"])
        self.ms_bind_thr.set(ms.get("bind_threshold", 0.5))
        bind = ms.get("bindings") or {}
        for d, lb in self.ms_bind_lbl.items():
            ks = bind.get(d) or []
            if ks:
                try:
                    txt = keys_text(ks)
                except Exception:   # noqa
                    txt = " + ".join(ks)
                lb.config(text=txt, foreground="#1a6b1a")
            else:
                lb.config(text="—", foreground="#999")

    def set_ministick_profiles(self, names, on):
        for ch in self.ms_prof_frame.winfo_children():
            ch.destroy()
        self.ms_prof_vars = {}
        for n in names:
            v = tk.BooleanVar(value=n in on)
            ttk.Checkbutton(self.ms_prof_frame, text=n, variable=v,
                            command=lambda n=n: self.app.on_ms_profile(n)).pack(anchor="w")
            self.ms_prof_vars[n] = v

    def update_ministick_status(self, reader):
        if reader is None:
            self.ministick_lbl.config(text="", foreground="#555")
            return
        if reader.ok:
            self.ministick_lbl.config(text="Статус: " + reader.status, foreground="#1a6b1a")
        else:
            self.ministick_lbl.config(text="Статус: " + reader.status, foreground="#a44")

    def _build_zoom_tab(self):
        """Вкладка «Зум»: ось X52 (ползунок) -> левый стик X геймпада, с фильтром дрожания."""
        fr = ttk.Frame(self.nb)
        self.nb.add(fr, text="Зум")
        app = self.app
        bg = ttk.Style().lookup("TFrame", "background") or "#f0f0f0"
        cv = tk.Canvas(fr, highlightthickness=0, yscrollincrement=20, bg=bg)
        sb = ttk.Scrollbar(fr, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        pw = ttk.Frame(cv)
        cv.create_window(0, 0, window=pw, anchor="nw")
        pw.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        self._scroll_canvases.add(cv)
        left = ttk.Frame(pw)
        left.grid(row=0, column=0, padx=(12, 20), pady=10, sticky="n")
        right = ttk.Frame(pw)
        right.grid(row=0, column=1, padx=(0, 12), pady=10, sticky="n")

        ttk.Label(left, text="Плавный зум ползунком X52", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(left, wraplength=330, justify="left", foreground="#555", text=(
            "Лаунчер гасит дрожание ползунка и отдаёт зум в игру левым стиком X виртуального "
            "геймпада. В DCS: колонка «Controller (XBOX 360…)» → «Камера в кабине, общий вид - "
            "приблизить\\отдалить» → JOY_X (модификатор пустой). В колонке X52 ползунок на зум "
            "НЕ назначать, свои действия-клавиши на этот ползунок удалить. В колонке Controller "
            "на JOY_X не должно быть ничего другого (например, Крена).")).pack(anchor="w", pady=(2, 8))
        W, H = 300, 26
        self._zoom_w = W
        ttk.Label(left, text="Ползунок X52:").pack(anchor="w")
        self.zoom_raw_cv = tk.Canvas(left, width=W, height=H, bg="#eef2f6", highlightthickness=1,
                                     highlightbackground="#adadad")
        self.zoom_raw_cv.pack(anchor="w")
        ttk.Label(left, text="Зум в игре (после фильтра):").pack(anchor="w", pady=(6, 0))
        self.zoom_out_cv = tk.Canvas(left, width=W, height=H, bg="#eef2f6", highlightthickness=1,
                                     highlightbackground="#adadad")
        self.zoom_out_cv.pack(anchor="w")
        for c in (self.zoom_raw_cv, self.zoom_out_cv):
            c.create_line(W // 2, 2, W // 2, H, fill="#cfd6de")
        self._zoom_raw_dot = self.zoom_raw_cv.create_rectangle(0, 3, 6, H - 2, fill="#64748b", outline="")
        self._zoom_out_dot = self.zoom_out_cv.create_rectangle(0, 3, 6, H - 2, fill="#ef4444", outline="")
        self.zoom_vals_lbl = ttk.Label(left, text="", font=("TkDefaultFont", 10, "bold"))
        self.zoom_vals_lbl.pack(anchor="w", pady=(4, 0))

        self.zoom_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Включить зум в этом профиле", variable=self.zoom_var,
                        command=app.on_zoom_toggle).pack(anchor="w", pady=2)
        pf = ttk.LabelFrame(right, text="Зум работает в профилях")
        pf.pack(fill="x", pady=(4, 6))
        ttk.Label(pf, foreground="#555", wraplength=300, justify="left", text=(
            "Настройки этой вкладки — свои в каждом профиле. В отмеченных профилях сам включится "
            "виртуальный геймпад.")).pack(anchor="w", padx=6, pady=(2, 2))
        self.zoom_prof_frame = ttk.Frame(pf)
        self.zoom_prof_frame.pack(fill="x", padx=6, pady=(0, 4))
        self.zoom_prof_vars = {}
        self.zoom_warn = ttk.Label(right, text="", foreground="#b45309", wraplength=320, justify="left")
        self.zoom_warn.pack(anchor="w")
        ttk.Label(right, text="Ось X52 (подвигайте ползунок — его ось видна на подвкладке «Оси»):",
                  wraplength=320, justify="left").pack(anchor="w", pady=(6, 0))
        self.zoom_axis = ttk.Combobox(right, state="readonly", width=24)
        self.zoom_axis.pack(anchor="w")
        self.zoom_axis.bind("<<ComboboxSelected>>", lambda e: app.on_zoom_val(
            "axis", self.zoom_axis.current() - 1 if self.zoom_axis.current() > 0 else None))
        self.zoom_inv = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Инвертировать", variable=self.zoom_inv,
                        command=lambda: app.on_zoom_val("invert", bool(self.zoom_inv.get()))
                        ).pack(anchor="w", pady=(4, 0))
        f1 = ttk.LabelFrame(right, text="Фильтр дрожания")
        f1.pack(fill="x", pady=(8, 0))
        ttk.Label(f1, wraplength=300, justify="left", foreground="#555", text=(
            "Зум стоит на месте, пока ползунок не сдвинули больше порога. "
            "Дрожит — увеличьте порог; зум идёт ступеньками — уменьшите. 0 — фильтр выключен.")
                  ).pack(anchor="w", padx=6, pady=(4, 0))
        ttk.Label(f1, text="Порог, % хода:").pack(anchor="w", padx=6)
        self.zoom_thr = tk.Scale(f1, from_=0.0, to=10.0, resolution=0.5, orient="horizontal", length=260,
                                 command=lambda v: app.on_zoom_val("filter_thr", float(v) / 100.0))
        self.zoom_thr.pack(anchor="w", padx=6, pady=(0, 4))

    def apply_zoom_cfg(self, z, n_axes=8):
        self.zoom_var.set(bool(z["enabled"]))
        vals = ["— не выбрано"] + [axis_name(self.app.cfg, i) for i in range(max(n_axes, (z["axis"] or 0) + 1))]
        self.zoom_axis.configure(values=vals)
        self.zoom_axis.current(0 if z["axis"] is None else z["axis"] + 1)
        self.zoom_inv.set(bool(z["invert"]))
        self.zoom_thr.set(round(z["filter_thr"] * 100, 1))
        cfg = self.app.cfg
        roll_on = cfg["axes_enabled"].get("roll", True) and cfg["axes"].get("roll") is not None
        self.zoom_warn.config(text=(
            "Внимание: в этом профиле ручка X52 включена как Крен (левый стик X). При включённом зуме "
            "левый стик X занят зумом — Крен в игру не пойдёт." if z["enabled"] and roll_on else ""))

    def set_zoom_profiles(self, names, on):
        for ch in self.zoom_prof_frame.winfo_children():
            ch.destroy()
        self.zoom_prof_vars = {}
        for n in names:
            v = tk.BooleanVar(value=n in on)
            ttk.Checkbutton(self.zoom_prof_frame, text=n, variable=v,
                            command=lambda n=n: self.app.on_zoom_profile(n)).pack(anchor="w")
            self.zoom_prof_vars[n] = v

    def tick_zoom(self, axes, out):
        z = self.app.cfg["zoom"]
        if len(self.zoom_axis.cget("values")) != len(axes) + 1 and len(axes) >= 1:
            prev = self.app._building
            self.app._building = True
            self.apply_zoom_cfg(z, len(axes))
            self.app._building = prev
        W = self._zoom_w
        raw = axes[z["axis"]] if z["axis"] is not None and z["axis"] < len(axes) else 0.0
        raw = raw if raw == raw else 0.0
        zo = (out or {}).get("zoom")
        for cvs, dot, v in ((self.zoom_raw_cv, self._zoom_raw_dot, raw),
                            (self.zoom_out_cv, self._zoom_out_dot, zo or 0.0)):
            x = int((max(-1.0, min(1.0, v)) + 1) / 2 * (W - 8)) + 1
            cvs.coords(dot, x, 3, x + 6, 24)
        self.zoom_vals_lbl.config(text="ползунок %+.2f   зум %s" % (raw, "%+.2f" % zo if zo is not None else
                                                                   "— выключен"))

    def tick_ministick(self, out):
        """Точка превью = итоговый обзор после режима «как стик» / «как мышь»
        (то же, что показывает вкладка «Обзор»)."""
        if not out:
            return
        x = max(-1.0, min(1.0, out.get("cam_x", 0.0)))
        y = max(-1.0, min(1.0, out.get("cam_y", 0.0)))
        mid = self._ms_mid
        r = 7
        # экранный Y направлен ВНИЗ: cam_y+ (вверх в игре) -> точка вверх по экрану
        px = mid + int(x * (mid - 15))
        py = mid - int(y * (mid - 15))
        self.ministick_canvas.coords(self._ms_dot,
                                     px - r, py - r, px + r, py + r)
        self.ministick_vals_lbl.config(text=f"X: {x:+.2f}    Y: {y:+.2f}")

    def _scroll_area(self, title):
        fr = ttk.Frame(self.nb)
        self.nb.add(fr, text=title)
        cv = tk.Canvas(fr, bg=TILE_BG, highlightthickness=0, yscrollincrement=20)
        sb = ttk.Scrollbar(fr, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv, bg=TILE_BG)
        cv.create_window(0, 0, window=inner, anchor="nw")
        self._scroll_canvases.add(cv)
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: self._relayout())
        inner.canvas = cv
        return inner

    def _on_wheel(self, e):
        """Прокрутка «Кнопок» / «Хаток» / «Осей» колёсиком, где бы ни был курсор над областью."""
        try:
            w = self.app.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, KeyError):
            return None
        while w is not None and w not in self._scroll_canvases:
            try:
                w = w.master
            except AttributeError:
                return None
        if w is None:
            return None
        top, bottom = w.yview()
        if top <= 0.0 and bottom >= 1.0:
            return None                                  # всё и так видно
        num = getattr(e, "num", None)
        if num == 4:
            step = -1
        elif num == 5:
            step = 1
        else:
            d = getattr(e, "delta", 0) or 0
            step = -int(d / 120) if abs(d) >= 120 else (-1 if d > 0 else 1 if d < 0 else 0)
        if step:
            w.yview_scroll(step * 3, "units")             # 60 пикселей на деление колёсика
        return "break"

    # ---- слой, на котором редактируем
    def _follow_layer(self):
        """Поле «Слой» показывает слой, на который переключили колесом режимов."""
        cfg, m = self.app.cfg, self.app.worker.mapper
        if not cfg["layers"]["enabled"] or not self.follow.get():
            self._seen_layer = None
            return
        cur = m.layer if m.layer_known else None
        if cur is None or cur == self._seen_layer:
            return
        self._seen_layer = cur
        if self.layer.current() != cur:
            self.layer.current(cur)
            self.refresh()

    def cur_layer(self):
        return self.layer.current() if self.app.cfg["layers"]["enabled"] else 0

    # ---- плитки
    def ensure_tiles(self, n_buttons, n_hats, n_axes=None):
        if n_axes is not None and len(self.axis_tiles) != n_axes:
            for t in self.axis_tiles:
                t.destroy()
            self.axis_tiles = [AxisTile(self.axis_area, i, self) for i in range(n_axes)]
            for i, t in enumerate(self.axis_tiles):
                t.grid(row=i // 2, column=i % 2, padx=6, pady=4, sticky="nw")
        if len(self.btn_tiles) != n_buttons:
            for t in self.btn_tiles:
                t.destroy()
            self.btn_tiles = [ButtonTile(self.btn_area, btn_binding(i), self.open_dialog, self.rename)
                              for i in range(n_buttons)]
            self._cols = 0
        if len(self.hat_tiles) != n_hats:
            for t in self.hat_tiles:
                t.destroy()
            self.hat_tiles = [HatTile(self.hat_area, i, self.open_dialog, self.rename) for i in range(n_hats)]
            for i, t in enumerate(self.hat_tiles):
                t.grid(row=i // 2, column=i % 2, padx=6, pady=6, sticky="nw")
        self._relayout()
        self.refresh()

    def _relayout(self):
        w = max(self.btn_area.canvas.winfo_width(), ButtonTile.W + 10)
        cols = max(1, w // (ButtonTile.W + 6))
        if cols == self._cols:
            return
        self._cols = cols
        for i, t in enumerate(self.btn_tiles):
            t.grid(row=i // cols, column=i % cols, padx=3, pady=3)

    def refresh(self):
        cfg = self.app.cfg
        if cfg["layers"]["enabled"]:
            self.layer_box.pack(side="right")
        else:
            self.layer_box.pack_forget()
        layer = self.cur_layer()
        for t in self.btn_tiles:
            t.name.configure(text=input_name(cfg, t.b))
            t.marks.set(find_slots(cfg, t.b, layer))
        for t in self.axis_tiles:
            t.refresh(cfg, layer)
        for h in self.hat_tiles:
            for d, c in h.cells.items():
                c["marks"].set(find_slots(cfg, c["b"], layer))
                nm = cfg.get("button_names", {}).get(name_key(c["b"]))
                c["frame"].configure(text=(HAT8_NAME[d] + (" · " + nm if nm else ""))[:16])
        self.acts.delete(*self.acts.get_children())
        self._row_input = {}
        dev = self.app.worker.state.get("name") or cfg.get("device_name")
        for i, (aid, b, vals) in enumerate(mapped_rows(cfg, dev, self.app.rs_other_profiles())):
            iid = "r%d" % i
            self.acts.insert("", "end", iid=iid, values=vals)
            self._row_input[iid] = (aid, b)
        self._refresh_devices(force=True)

    def _refresh_devices(self, force=False):
        devs = list(self.app.worker.devices)
        cur = self.app.worker.state.get("name")
        key = (tuple(devs), cur)
        if key == self._devs and not force:
            return
        self._devs = key
        self.dev.delete(*self.dev.get_children())
        for i, n in enumerate(devs):
            self.dev.insert("", "end", iid="d%d" % i, values=(n, "%d" % (i + 1)))
            if n == cur:
                self.dev.selection_set("d%d" % i)

    def _dev_selected(self):
        s = self.dev.selection()
        if not s:
            return
        name = self.dev.item(s[0], "values")[0]
        if name != self.app.worker.state.get("name"):
            self.app.cfg["device_name"] = name
            self.app.worker.send("scan")
            self.app.mark_dirty()

    def tick(self, state):
        self._refresh_devices()
        self._follow_layer()
        btns, hats, axes = state["buttons"], state["hats"], state["axes"]
        if (len(self.btn_tiles) != len(btns) or len(self.hat_tiles) != len(hats)
                or len(self.axis_tiles) != len(axes)):
            self.ensure_tiles(len(btns), len(hats), len(axes))
        cur_tab = self.nb.index("current")
        if cur_tab == 2:                                   # оси рисуем, только когда их видно
            for i, t in enumerate(self.axis_tiles):
                v = axes[i]
                t.set_value(v if v == v else 0.0, self.app.cfg)
        elif cur_tab == 3:                                 # мини-стик
            w = getattr(self.app, "worker", None)
            if w is not None:
                self.tick_ministick(w.out)
                self.update_ministick_status(w.ministick)
        elif cur_tab == 4:                                 # зум
            w = getattr(self.app, "worker", None)
            self.tick_zoom(axes, w.out if w is not None else None)
        for i, t in enumerate(self.btn_tiles):
            t.set_pressed(bool(btns[i]))
        arrows = []
        for hi, h in enumerate(self.hat_tiles):
            x, y = hats[hi]
            sx, sy = (x > 0) - (x < 0), (y > 0) - (y < 0)
            for d, (hx, hy) in HAT8.items():
                on = (sx, sy) == (hx, hy)
                h.set_on(d, on)
                if on:
                    arrows.append(ARROW8[d])
        # хатки — на своей внутренней вкладке: показываем направление прямо в её названии
        title = "Хатки " + " ".join(arrows) if arrows else "Хатки"
        if title != self._hat_title:
            self._hat_title = title
            self.nb.tab(1, text=title)
            if arrows and self.nb.index("current") == 0:
                self.app.set_hint("Хатка нажата — её плитки на вкладке «Хатки» (рядом с «Кнопки»).")

    # ---- действия
    def _open_from_list(self):
        s = self.acts.selection()
        if s and s[0] in self._row_input:
            aid, b = self._row_input[s[0]]
            ca = find_custom(self.app.cfg, aid)
            if ca and self.app.cfg["layers"]["enabled"]:
                self.layer.current(ca["layer"])
            self.open_dialog(b)

    def open_dialog(self, b, cols=None, profiles=None):
        """profiles — в каких ещё профилях задать то же самое (None — только в текущем)."""
        app = self.app
        if app.learn or app.grab_current() is not None:
            return
        layer = self.cur_layer()
        same = app.rs_profiles_same(b, layer)
        have = find_slots(app.cfg, b, layer)
        start = {s: (column_from_ca(have[s]) if s in have else
                     {"enabled": False, "name": "", "kind": "key", "mods": [], "key": "", "repeat": False,
                      "repeat_ms": 100, "continuous": False, "seq": "", "profile": "", "special": False,
                      "cam": "left"})
                 for s in SLOTS}
        if cols is None:
            title = input_name(app.cfg, b) + ("" if not app.cfg["layers"]["enabled"] else
                                              " (%s)" % self.layer.get())
            dlg = RsActionDialog(app, title, start, [s["name"] for s in app.cfg["sequences"]],
                                 app._all_profile_names(), self.pick_key,
                                 share=(app._all_profile_names(), app.cfg["profile_name"], same),
                                 edit_seqs=self.edit_sequences)
            app.wait_window(dlg)
            cols, profiles = dlg.result, dlg.profiles
        if not cols:
            return
        apply_slots(app.cfg, b, layer, cols)
        app.refresh_tree()
        app.mark_dirty()
        done = app.rs_apply_to_profiles(b, layer, cols, set(profiles or ()), set(same) - set(profiles or ())
                                        if profiles is not None else set())
        app.set_hint(f"{input_name(app.cfg, b)}: действия сохранены" +
                     (" (и в профилях: %s)." % ", ".join(done) if done else "."))

    def pick_key(self):
        """Окно выбора клавиши поверх текущего диалога; после — вернуть диалогу модальность."""
        owner = self.app.grab_current()
        if owner is None:
            f = self.app.focus_get()
            owner = f.winfo_toplevel() if f is not None else self.app
        dlg = self.app.KeyDialogClass(owner, "Клавиша", [], [])
        self.app.wait_window(dlg)
        if owner is not self.app:
            try:
                owner.grab_set()
            except tk.TclError:
                pass
        return dlg.result

    def rename(self, b, name=None):
        cfg = self.app.cfg
        k = name_key(b)
        if name is None:
            name = simpledialog.askstring("Название", f"Название для «{binding_text(b)}»\n(пусто — по умолчанию):",
                                          initialvalue=cfg["button_names"].get(k, ""), parent=self.app)
            if name is None:
                return
        name = name.strip()[:40]
        if name:
            cfg["button_names"][k] = name
        else:
            cfg["button_names"].pop(k, None)
        self.app.mark_dirty()
        self.refresh()

    def rename_axis(self, i, name=None):
        cfg = self.app.cfg
        k = "a%d" % i
        if name is None:
            name = simpledialog.askstring("Название оси", f"Название для оси {i + 1} (например «Крутилка I», "
                                                          f"«Ползунок»; пусто — по умолчанию):",
                                          initialvalue=cfg["button_names"].get(k, ""), parent=self.app)
            if name is None:
                return
        name = name.strip()[:40]
        if name:
            cfg["button_names"][k] = name
        else:
            cfg["button_names"].pop(k, None)
        self.app.mark_dirty()
        self.refresh()

    def ask_thr(self, i, d, value=None):
        cfg = self.app.cfg
        if value is None:
            cond = "не больше" if d == "-" else "не меньше"
            value = simpledialog.askfloat(
                "Порог", f"{axis_name(cfg, i)}, направление «{'−' if d == '-' else '+'}»:\n"
                f"срабатывает, когда значение оси {cond} порога (от -0.95 до 0.95).\n"
                f"Текущее положение видно на шкале плитки.",
                initialvalue=axis_thr(cfg, i, d), minvalue=-0.95, maxvalue=0.95, parent=self.app)
            if value is None:
                return
        set_axis_thr(cfg, i, d, value)
        self.app.mark_dirty()
        self.app.refresh_tree()

    def disable_analog(self, i):
        app = self.app
        for r in axis_roles(app.cfg, i):
            app.cfg["axes_enabled"][r] = False
            if hasattr(app, "axen_var"):
                app.axen_var[r].set(False)
        app.mark_dirty()
        app.refresh_tree()
        app.set_hint(f"{axis_name(app.cfg, i)}: аналоговая работа выключена — ось работает как кнопки "
                     f"(включить обратно — «Оси и РУД»).")

    def open_sequences(self):
        SequenceManager(self.app, self.app.cfg, self._seq_changed, self.pick_key)

    def edit_sequences(self):
        """«Управление последовательностями» поверх окна назначения (модально); возвращает имена."""
        owner = self.app.grab_current()
        mgr = SequenceManager(owner or self.app, self.app.cfg, self._seq_changed, self.pick_key)
        mgr.grab_set()
        self.app.wait_window(mgr)
        if owner is not None and owner is not self.app:
            try:
                owner.grab_set()
            except tk.TclError:
                pass
        return [sq["name"] for sq in self.app.cfg["sequences"]]

    def _seq_changed(self):
        for sq in self.app.cfg["sequences"]:
            sq["steps"] = clean_steps(sq["steps"])
        self.app.refresh_tree()
        self.app.mark_dirty()
