# -*- coding: utf-8 -*-
"""Интеграционные тесты: настоящий интерфейс Tk + рабочий поток pygame, эмулятор X52,
эмулятор виртуального геймпада (vgamepad) и клавиатуры. Запуск: xvfb-run python -m pytest tests"""
import json
import os
import sys
import time
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import x52_core as core  # noqa: E402


# ------------------------------------------------------------------ эмуляторы
class FakeX52:
    def __init__(self):
        self.axes = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -1.0, 0.0]
        self.buttons = [0] * 39
        self.hats = [(0, 0), (0, 0)]
        self.alive = True

    def _chk(self):
        if not self.alive:
            raise pygame.error("device lost")

    def get_name(self):
        self._chk()
        return "Saitek X52 Flight Control System"

    def get_instance_id(self):
        return 7

    def get_numaxes(self):
        self._chk()
        return len(self.axes)

    def get_axis(self, i):
        return self.axes[i]

    def get_numbuttons(self):
        return len(self.buttons)

    def get_button(self, i):
        return self.buttons[i]

    def get_numhats(self):
        return len(self.hats)

    def get_hat(self, i):
        return self.hats[i]


X52 = FakeX52()


class FakePad:
    instances = []

    def __init__(self):
        self.buttons = set()
        self.left = (0.0, 0.0)
        self.right = (0.0, 0.0)
        self.lt = self.rt = 0.0
        self.updates = 0
        FakePad.instances.append(self)

    def press_button(self, button):
        self.buttons.add(button)

    def release_button(self, button):
        self.buttons.discard(button)

    def left_joystick_float(self, x_value_float, y_value_float):
        self.left = (x_value_float, y_value_float)

    def right_joystick_float(self, x_value_float, y_value_float):
        self.right = (x_value_float, y_value_float)

    def left_trigger_float(self, value_float):
        self.lt = value_float

    def right_trigger_float(self, value_float):
        self.rt = value_float

    def update(self):
        self.updates += 1

    def reset(self):
        self.buttons.clear()
        self.left = self.right = (0.0, 0.0)
        self.lt = self.rt = 0.0


_B = types.SimpleNamespace(**{n: n for n in (
    "XUSB_GAMEPAD_A", "XUSB_GAMEPAD_B", "XUSB_GAMEPAD_X", "XUSB_GAMEPAD_Y",
    "XUSB_GAMEPAD_LEFT_SHOULDER", "XUSB_GAMEPAD_RIGHT_SHOULDER", "XUSB_GAMEPAD_LEFT_THUMB",
    "XUSB_GAMEPAD_RIGHT_THUMB", "XUSB_GAMEPAD_BACK", "XUSB_GAMEPAD_START", "XUSB_GAMEPAD_DPAD_UP",
    "XUSB_GAMEPAD_DPAD_DOWN", "XUSB_GAMEPAD_DPAD_LEFT", "XUSB_GAMEPAD_DPAD_RIGHT")})
sys.modules["vgamepad"] = types.SimpleNamespace(VX360Gamepad=FakePad, XUSB_BUTTON=_B)

KEYLOG = core._NullInput()


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cfg")
    import x52_ac8_launcher as L
    L.CONFIG_PATH = str(tmp / "x52_config.json")
    L.ERROR_LOG = str(tmp / "x52_error.log")
    L.SEQ_LOG = str(tmp / "x52_seq.log")
    # старый конфиг пользователя (версия 2.0) — проверяем перенос
    with open(os.path.join(ROOT, "x52_config.json"), encoding="utf-8-sig") as f:
        old = json.load(f)
    old["launcher"]["autostart_bridge"] = False
    with open(L.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(old, f)
    L.KeySender = lambda: core.KeySender(backend=KEYLOG)
    pygame.joystick.get_count = lambda: 1 if X52.alive else 0
    pygame.joystick.Joystick = lambda i: X52
    pygame.joystick.init = lambda: None
    pygame.joystick.quit = lambda: None
    L.App.refresh_setup_status = lambda self: None    # без PowerShell/реестра
    a = L.App()
    a.L = L
    a.tmp = tmp
    pump(a, 0.6)
    yield a
    if not getattr(a, "_closing", False):
        a.on_close()


def pump(a, sec=0.15):
    end = time.time() + sec
    while time.time() < end:
        a.update()
        time.sleep(0.005)


def wait(a, cond, sec=2.0):
    end = time.time() + sec
    while time.time() < end:
        a.update()
        if cond():
            return True
        time.sleep(0.005)
    return False


def pad():
    return FakePad.instances[-1]


# ------------------------------------------------------------------ тесты
def test_starts_and_finds_x52(app):
    assert app.worker.state["name"].startswith("Saitek X52")
    assert len(app.nb.tabs()) == 8
    assert len(app.raw_axis_bars) == 8
    assert app.cfg["bindings"]["next_weapon"][0] == {"type": "button", "index": 2}   # перенос 2.x
    for aid in core.ACTION_IDS:
        assert app.tree.exists(aid)


def test_500_profile_dialog_game_template(app):
    prev = app.cfg["profile_name"]
    assert app.glob["auto_switch"] is False

    def fill(dlg):
        dlg.tmpl.set("dcs")
        dlg.name_var.set("DCS Шаблон")
        dlg._ok()
    app.after(300, lambda: fill(app._dlg))
    orig = app.L.ProfileDialog

    def mk(master):
        app._dlg = orig(master)
        return app._dlg
    app.L.ProfileDialog = mk
    try:
        app.profile_new()
    finally:
        app.L.ProfileDialog = orig
    assert app.cfg["profile_name"] == "DCS Шаблон"
    assert app.cfg["auto"]["processes"] == ["DCS.exe", "DCS_mt.exe"]
    assert app.cfg["game"]["virtual_pad"] is False
    assert app.glob["auto_switch"] is True          # шаблон игры включает автопереключение
    app.auto_var.set(False)
    app.on_auto_toggle()
    assert app.switch_profile(prev)                 # остальные тесты ждут исходный профиль
    os.remove(app.L.profile_path("DCS Шаблон"))
    app.refresh_profiles()


def test_501_last_game_seen_with_auto_switch_off(app):
    assert app.glob["auto_switch"] is False
    prof, fg = app.cfg["profile_name"], app._fg_func
    app._fg_func = lambda: "DCS.exe"
    try:
        app._auto_tick()
    finally:
        app._fg_func = fg
    assert app.last_proc == "DCS.exe"                  # видно и без автопереключения
    assert app.cfg["profile_name"] == prof            # но профиль не трогаем
    app.last_proc = None

def test_502_joycpl_option(app, monkeypatch):
    L = app.L
    calls = []
    monkeypatch.setattr(L, "IS_WIN", True)
    monkeypatch.setattr(L, "open_joycpl", lambda: (calls.append("open") or 4242, "ok"))
    monkeypatch.setattr(L, "close_joycpl", lambda pid: calls.append(("close", pid)))
    assert app.glob["joycpl"] is False
    app.joycpl_var.set(True)
    app.on_joycpl()
    assert wait(app, lambda: app._joycpl_pid == 4242)
    assert L.load_global()["joycpl"] is True
    app.joycpl_var.set(False)
    app.on_joycpl()
    assert app._joycpl_pid is None and ("close", 4242) in calls
    assert L.load_global()["joycpl"] is False

def test_530_ministick_tab_rows_and_preview(app):
    app.nb.select(app.T_RS)
    app.rs.nb.select(3)
    pump(app, 0.2)
    assert app.rs.nb.tab(3, "text") == "Мини-стик"
    assert set(app.rs.ms_bind_lbl) == {"up", "down", "left", "right"}
    for lb in app.rs.ms_bind_lbl.values():
        assert lb.winfo_ismapped()
    # превью показывает итоговый обзор (после «как стик»/«как мышь»)
    app.rs.tick_ministick({"cam_x": 1.0, "cam_y": 0.0})
    x0, y0, x1, y1 = app.rs.ministick_canvas.coords(app.rs._ms_dot)
    assert (x0 + x1) / 2 > app.rs._ms_mid + 50
    # «Очистить» и порог пишут в конфиг
    app.cfg["ministick"]["bindings"]["up"] = ["W"]
    app.on_ms_bind_clear("up")
    assert app.cfg["ministick"]["bindings"]["up"] == []
    assert app.rs.ms_bind_lbl["up"].cget("text") == "—"
    # блок клавиш виден без горизонтальной прокрутки
    tab = app.rs.ministick_tab
    lb = app.rs.ms_bind_lbl["right"]
    assert lb.winfo_rootx() + lb.winfo_width() <= tab.winfo_rootx() + tab.winfo_width()


def test_531_ministick_cam_mode_same_as_view_tab(app):
    sent = []
    orig = app.worker.send
    app.worker.send = lambda *a: sent.append(a[0])
    try:
        app.rs.ms_mode_var.set("mouse")
        app.on_cam_mode_from_ms()
        assert app.cfg["camera"]["mode"] == "mouse" and app.cam_mode_var.get() == "mouse"
        assert "center" in sent                      # как при переключении на вкладке «Обзор»
        app.cam_mode_var.set("stick")
        app.on_cam_mode()
        assert app.rs.ms_mode_var.get() == "stick"
        app.on_cam_val("max", 0.5)
        assert app.rs.ms_cam_max.get() == 0.5 and app.cfg["camera"]["max"] == 0.5
    finally:
        app.worker.send = orig


def test_540_ministick_shared_across_profiles(app):
    app.create_profile("Взлёт", "dcs")
    app.rs.ministick_var.set(True)
    app.on_ministick_toggle()
    app.cfg["ministick"]["sens"] = 1.0
    app.cfg["camera"]["mode"] = "mouse"
    app.save_cfg()
    assert app.cfg["game"]["virtual_pad"]               # мини-стик сам включил геймпад
    assert "Взлёт" in app.glob["ministick"]["profiles"]
    app.create_profile("Полёт", "dcs")
    assert app.cfg["ministick"]["sens"] == 1.0 and app.cfg["camera"]["mode"] == "mouse"   # общие настройки
    assert not app.cfg["ministick"]["enabled"] and not app.rs.ministick_var.get()
    assert set(app.rs.ms_prof_vars) >= {"Взлёт", "Полёт"} and app.rs.ms_prof_vars["Взлёт"].get()
    app.rs.ms_prof_vars["Полёт"].set(True)             # отметили «Полёт» галочкой
    app.on_ms_profile("Полёт")
    assert app.cfg["ministick"]["enabled"] and app.cfg["game"]["virtual_pad"]
    app.switch_profile("Взлёт")
    app.rs.ms_prof_vars["Взлёт"].set(False)            # сняли галочку у другого профиля
    app.switch_profile("Полёт")
    assert app.cfg["ministick"]["enabled"]
    app.switch_profile("Взлёт")
    assert app.cfg["ministick"]["enabled"]              # у текущего снятая галочка = выключение
    app.rs.ministick_var.set(False)
    app.on_ministick_toggle()
    app.switch_profile("Полёт")
    assert app.glob["ministick"]["profiles"] == ["Полёт"] and app.cfg["ministick"]["enabled"]
    app.profile_rename("Полёт 2")
    assert app.glob["ministick"]["profiles"] == ["Полёт 2"]
    # уборка: остальные тесты ждут профиль ACE COMBAT 8 и мини-стик выключенным
    app.rs.ministick_var.set(False)
    app.on_ministick_toggle()
    app.switch_profile("ACE COMBAT 8")
    for n in ("Взлёт", "Полёт 2"):
        os.remove(app.L.profile_path(n))
    app.refresh_profiles()
    assert app.glob["ministick"]["profiles"] == []


def test_554_zoom_tab(app):
    app.create_profile("Зум-тест", "dcs")
    app.cfg["game"]["virtual_pad"] = False
    app.pad_var.set(False)
    app.nb.select(app.T_RS)
    app.rs.nb.select(4)
    assert app.rs.nb.tab(4, "text") == "Зум"
    app.rs.zoom_var.set(True)
    app.on_zoom_toggle()
    app.on_zoom_val("axis", 6)
    assert app.cfg["game"]["virtual_pad"] and app.pad_var.get()      # зум сам включил геймпад
    X52.axes[6] = 0.5
    try:
        assert wait(app, lambda: (app.worker.out.get("zoom") or 0) > 0.45)
        assert wait(app, lambda: "ползунок +0.50" in app.rs.zoom_vals_lbl.cget("text"))
        app.save_cfg()
        app.rs.zoom_var.set(False)
        app.on_zoom_toggle()
        assert wait(app, lambda: app.worker.out.get("zoom") is None)
    finally:
        X52.axes[6] = -1.0
        app.rs.nb.select(0)
        app.switch_profile("ACE COMBAT 8")          # уборка: остальные тесты ждут прежний список профилей
        os.remove(app.L.profile_path("Зум-тест"))
        app.refresh_profiles()


def test_555_ministick_curve_slider(app):
    app.on_ministick_val("curve", 1.8)
    app.rs.apply_ministick_cfg(app.cfg["ministick"])
    assert abs(app.rs.ministick_curve.get() - 1.8) < 1e-6
    app.save_cfg()
    assert app.glob["ministick"] is None or app.glob["ministick"]["settings"]["curve"] == 1.8
    app.on_ministick_val("curve", 1.0)
    app.rs.ministick_lock.set(True)
    app.on_ministick_val("axis_lock", True)
    app.rs.apply_ministick_cfg(app.cfg["ministick"])
    assert app.cfg["ministick"]["axis_lock"] and app.rs.ministick_lock.get()
    app.on_ministick_val("axis_lock", False)
    app.save_cfg()

def test_556_zoom_shared_across_profiles(app):
    app.create_profile("З-Взлёт", "dcs")
    app.rs.zoom_var.set(True)
    app.on_zoom_toggle()
    app.on_zoom_val("axis", 6)
    app.on_zoom_val("filter_thr", 0.04)
    app.save_cfg()
    assert app.glob["zoom"]["profiles"] == ["З-Взлёт"]
    app.create_profile("З-Полёт", "dcs")
    assert app.cfg["zoom"]["axis"] == 6 and app.cfg["zoom"]["filter_thr"] == 0.04     # общие настройки
    assert not app.cfg["zoom"]["enabled"] and not app.rs.zoom_var.get()
    assert app.rs.zoom_prof_vars["З-Взлёт"].get() and not app.rs.zoom_prof_vars["З-Полёт"].get()
    app.rs.zoom_prof_vars["З-Полёт"].set(True)                    # галочка у текущего = включить
    app.on_zoom_profile("З-Полёт")
    assert app.cfg["zoom"]["enabled"] and app.cfg["game"]["virtual_pad"]
    app.on_zoom_val("filter_thr", 0.03)
    app.switch_profile("З-Взлёт")
    assert app.cfg["zoom"]["enabled"] and app.cfg["zoom"]["filter_thr"] == 0.03
    app.rs.zoom_prof_vars["З-Полёт"].set(False)                   # галочка у другого профиля
    app.on_zoom_profile("З-Полёт")
    app.switch_profile("З-Полёт")
    assert not app.cfg["zoom"]["enabled"]
    app.switch_profile("З-Взлёт")
    app.profile_rename("З-Взлёт 2")
    assert app.glob["zoom"]["profiles"] == ["З-Взлёт 2"]
    app.profile_delete(confirm=False)
    assert app.glob["zoom"]["profiles"] == []
    # уборка: остальные тесты ждут профиль ACE COMBAT 8 и прежний список профилей
    app.switch_profile("ACE COMBAT 8")
    for n in list(app.L.list_profiles()):
        if n.startswith("З-"):
            os.remove(app.L.profile_path(n))
    app.refresh_profiles()

def test_551_button_assignment_to_several_profiles(app):
    import x52_rsview as rv
    app.create_profile("Общие-1", "dcs")
    app.create_profile("Общие-2", "dcs")
    app.switch_profile("Общие-1")
    b = rv.btn_binding(9)
    off = {"enabled": False, "name": "", "kind": "key", "mods": [], "key": "", "repeat": False,
           "repeat_ms": 100, "continuous": False, "seq": "", "profile": "", "special": False, "cam": "left"}
    cols = {"single": dict(off, enabled=True, name="Фонарь", mods=["LCTRL"], key="C"),
            "long": dict(off), "release": dict(off)}
    app.rs.open_dialog(b, cols=cols, profiles={"Общие-2"})
    other = app._load_config(app.L.profile_path("Общие-2"), silent=True)
    assert rv.find_slots(other, b)["single"]["keys"] == ["LCTRL", "C"]
    assert app.rs_profiles_same(b, 0) == ["Общие-2"]
    assert "ACE COMBAT 8" not in app.rs_profiles_same(b, 0)

    def profs_col():
        app.rs.refresh()
        return [app.rs.acts.item(i, "values")[9] for i in app.rs.acts.get_children()
                if app.rs.acts.item(i, "values")[2] == "Фонарь"]
    assert profs_col() == ["Общие-1, Общие-2"]
    app.rs.open_dialog(b, cols=cols, profiles=set())            # сняли галочку «Общие-2»
    other = app._load_config(app.L.profile_path("Общие-2"), silent=True)
    assert rv.find_slots(other, b) == {}
    assert profs_col() == ["Общие-1"]
    assert rv.find_slots(app.cfg, b)["single"]["keys"] == ["LCTRL", "C"]   # в текущем осталось
    app.switch_profile("ACE COMBAT 8")
    for n in ("Общие-1", "Общие-2"):
        os.remove(app.L.profile_path(n))
    app.refresh_profiles()


def test_559_profile_cycle_copied_to_profiles(app):
    import x52_rsview as rv
    for n in ("Круг-1", "Круг-2", "Круг-3"):
        app.create_profile(n, "dcs")
    app.switch_profile("Круг-1")
    b = rv.btn_binding(12)
    names = ["Круг-1", "Круг-2", "Круг-3"]
    app.cfg["custom_actions"].append(core.sanitize_config({"custom_actions": [{
        "id": core.new_custom_id(app.cfg), "name": "Профили по кругу", "mode": "profile", "trigger": "press",
        "layer": 0, "keys": [], "profile": {"kind": "cycle", "names": names},
        "bindings": [dict(b), None]}]})["custom_actions"][0])
    cols = {s: rv.column_from_ca(ca) for s, ca in rv.find_slots(app.cfg, b).items()}
    off = {"enabled": False, "special": False}
    for s in rv.SLOTS:
        cols.setdefault(s, dict(off))
    assert cols["single"]["special"]                      # «по кругу» окно не описывает целиком
    app.rs.open_dialog(b, cols=cols, profiles={"Круг-2", "Круг-3"})
    for n in ("Круг-2", "Круг-3"):
        other = app._load_config(app.L.profile_path(n), silent=True)
        ca = rv.find_slots(other, b)["single"]
        assert ca["mode"] == "profile" and ca["profile"] == {"kind": "cycle", "names": names}
    assert set(app.rs_profiles_same(b, 0)) == {"Круг-2", "Круг-3"}
    app.rs.open_dialog(b, cols=cols, profiles={"Круг-2", "Круг-3"})   # повторно — без дублей
    other = app._load_config(app.L.profile_path("Круг-2"), silent=True)
    assert sum(1 for ca in other["custom_actions"] if ca["mode"] == "profile") == 1
    off_cols = dict(cols, single=dict(cols["single"], enabled=False))   # сняли галочку колонки — убрать везде
    app.rs.open_dialog(b, cols=off_cols, profiles={"Круг-2", "Круг-3"})
    assert rv.find_slots(app.cfg, b) == {}
    for n in ("Круг-2", "Круг-3"):
        assert rv.find_slots(app._load_config(app.L.profile_path(n), silent=True), b) == {}
    app.switch_profile("ACE COMBAT 8")
    for n in names:
        os.remove(app.L.profile_path(n))
    app.refresh_profiles()

def test_560_sequence_button_in_assignment_dialog(app):
    import x52_rsview as rv
    off = {"enabled": False, "name": "", "kind": "key", "mods": [], "key": "", "repeat": False,
           "repeat_ms": 100, "continuous": False, "seq": "", "profile": "", "special": False, "cam": "left"}
    dlg = rv.RsActionDialog(app, "Тест", {s: dict(off) for s in rv.SLOTS}, [], [], app.rs.pick_key,
                            edit_seqs=app.rs.edit_sequences)
    col = dlg.cols["single"]
    col.en.set(True)
    col._state()
    seen = {}

    def create_and_close():
        mgr = next(w for w in dlg.winfo_children() if isinstance(w, rv.SequenceManager))
        seen["grab"] = app.grab_current() is mgr
        mgr.new_seq("Запуск-тест")
        mgr.destroy()
    app.after(300, create_and_close)
    dlg._edit_seqs(col)
    try:
        assert seen["grab"]                                      # окно последовательностей модальное
        assert col.seq.get() == "Запуск-тест" and col.kind.get() == "seq"
        assert "Запуск-тест" in dlg.cols["long"].seq.cget("values")
        assert app.grab_current() is dlg                         # окно назначения снова принимает ввод
    finally:
        dlg.destroy()
        app.cfg["sequences"] = [q for q in app.cfg["sequences"] if q["name"] != "Запуск-тест"]
        app.save_cfg()

def test_561_sequence_editor_keeps_selection_and_clears_mods(app):
    import x52_rsview as rv
    m = rv.SequenceManager(app, app.cfg, app.rs._seq_changed, app.rs.pick_key)
    try:
        m.new_seq("Т-ред")
        m.s_key.set(rv.key_text("L"))
        m.s_delay.set("0")
        m.add_step()
        m.mods["RCTRL"].set(True)
        m.s_key.set(rv.key_text("HOME"))
        m.s_delay.set("400")
        m.add_step()
        assert not any(v.get() for v in m.mods.values()) and m.s_key.get() == ""   # модификатор не переносится
        m.tv.selection_set("1")
        pump(app, 0.1)
        m.s_delay.set("40000")
        m.update_step()
        assert m._seq()["steps"][1]["delay_ms"] == 40000 and m.tv.selection() == ("1",)
        m.s_delay.set("45000")                    # второе изменение подряд — тоже сохраняется
        m.update_step()
        assert m._seq()["steps"][1]["delay_ms"] == 45000
    finally:
        m.destroy()
        app.cfg["sequences"] = [q for q in app.cfg["sequences"] if q["name"] != "Т-ред"]
    d = app.L.CustomActionDialog(app, "Тест")
    try:
        d.step_keys = ["RCTRL", "HOME"]
        d.delay_var.set("400")
        d._add_step()
        assert d.step_keys == []                  # следующий шаг — без прежних клавиш/модификаторов
        d.lb.selection_set(0)
        d.delay_var.set("40000")
        d.step_keys = ["RCTRL", "HOME"]
        d._update_step()
        assert d.steps[0]["delay_ms"] == 40000 and d.lb.curselection() == (0,)
    finally:
        d.destroy()

def test_bridge_and_analog_response(app):
    app.toggle_bridge() if app.worker.bridge_on else None
    app.cfg["throttle_cal"]["recorded"] = [k for k, _ in core.CAL_ROWS]   # без вопроса о калибровке
    app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on)
    X52.axes[0] = 0.5
    X52.axes[1] = -0.5
    r = app.cfg["response"]["roll"]
    expect = core.shape_axis(0.5, r)
    assert wait(app, lambda: abs(pad().left[0] - expect) < 1e-3)
    assert pad().left[1] == pytest.approx(core.shape_axis(0.5, app.cfg["response"]["pitch"]), abs=1e-3)
    X52.axes[0] = X52.axes[1] = 0.0
    assert wait(app, lambda: pad().left == (0.0, 0.0))


def test_worker_loop_rate(app):
    pump(app, 1.3)
    assert app.worker.loop_hz > 100


def test_learn_button_for_keyboard_only_action(app):
    app.tree.selection_set("gear")
    pump(app, 0.05)
    assert str(app.via_pad.cget("state")) == "disabled"      # у геймпада нет «шасси»
    app.learn_binding(0)
    X52.buttons[14] = 1
    assert wait(app, lambda: app.cfg["bindings"]["gear"][0] == {"type": "button", "index": 14})
    assert wait(app, lambda: ("R", True) in KEYLOG.log)
    X52.buttons[14] = 0
    assert wait(app, lambda: ("R", False) in KEYLOG.log)
    assert app.tree.item("gear", "values")[0] == "Кнопка 15"


def test_learn_axis_as_button_secondary(app):
    app.tree.selection_set("special1")
    app.learn_binding(1)
    X52.axes[6] = 0.9          # крутилка из -1 вправо
    assert wait(app, lambda: app.cfg["bindings"]["special1"][0] is not None)
    b = app.cfg["bindings"]["special1"][0]    # основной не было -> стала основной
    assert b["type"] == "axis" and b["index"] == 6 and b["dir"] == "+"
    assert wait(app, lambda: ("2", True) in KEYLOG.log)
    X52.axes[6] = -1.0
    assert wait(app, lambda: ("2", False) in KEYLOG.log)


def test_axis_threshold_dialog(app, monkeypatch):
    app.tree.selection_set("special1")
    monkeypatch.setattr(app.L.simpledialog, "askfloat", lambda *a, **k: 0.7)
    app.edit_axis_threshold()
    assert app.cfg["bindings"]["special1"][0]["thr"] == 0.7
    assert "+0.70" in app.tree.item("special1", "values")[0]


def test_switch_gun_to_keyboard(app):
    app.tree.selection_set("gun")
    pump(app, 0.05)
    app.via_var.set("key")
    app.on_via()
    assert app.cfg["outputs"]["gun"] == {"via": "key", "keys": ["J"]}
    X52.buttons[0] = 1
    assert wait(app, lambda: ("J", True) in KEYLOG.log)
    assert "XUSB_GAMEPAD_A" not in pad().buttons
    X52.buttons[0] = 0
    assert wait(app, lambda: ("J", False) in KEYLOG.log)
    app.via_var.set("pad")
    app.on_via()
    X52.buttons[0] = 1
    assert wait(app, lambda: "XUSB_GAMEPAD_A" in pad().buttons)
    X52.buttons[0] = 0
    assert wait(app, lambda: "XUSB_GAMEPAD_A" not in pad().buttons)


def test_key_dialog_capture(app):
    app.tree.selection_set("gear")
    seen = {}

    def drive():
        dlg = [w for w in app.winfo_children() if isinstance(w, app.L.KeyDialog)][0]
        try:
            dlg.focus_force()
            dlg.update()
            # в X11 keycode != Windows VK, поэтому здесь только keysym
            dlg.event_generate("<KeyPress>", keysym="g", when="now")
            dlg.update()
            seen["after_key"] = list(dlg.keys)
            dlg.combo_var.set(True)
            dlg.cb.current(core.ALL_KEYS.index("LSHIFT"))
            dlg._pick()
            seen["combo"] = list(dlg.keys)
            dlg._ok()
        finally:
            if dlg.winfo_exists():
                dlg.destroy()
    app.after(200, drive)
    app.edit_keys()
    assert seen["after_key"] == ["G"]
    assert app.cfg["outputs"]["gear"]["keys"] == ["G", "LSHIFT"]
    assert "G (П) + Shift (лев.)" in app.tree.item("gear", "values")[2]


def test_response_sliders_presets_and_curve(app):
    app.nb.select(app.T_RESP)          # вкладка «Отклик ручки» видна, как у пользователя
    pump(app, 0.1)
    app.resp_scales["roll"]["sensitivity"].set(2.0)
    pump(app, 0.1)
    assert app.cfg["response"]["roll"]["sensitivity"] == 2.0
    app.apply_stick_preset("fast")
    assert app.cfg["response"]["roll"] == core.STICK_PRESETS["fast"]
    assert app.cfg["response"]["pitch"] == core.STICK_PRESETS["fast"]
    pump(app, 0.1)
    assert float(app.resp_scales["pitch"]["anti_deadzone"].get()) == pytest.approx(0.20)
    X52.axes[0] = 0.3
    exp = core.shape_axis(0.3, core.STICK_PRESETS["fast"])
    assert wait(app, lambda: abs(pad().left[0] - exp) < 1e-3)
    assert exp > 0.3 + 0.15     # «быстро» действительно отзывчивее линейного
    X52.axes[0] = 0.0
    app.resp_scales["roll"]["smoothing_ms"].set(0)
    app.copy_roll_to_pitch()
    assert app.cfg["response"]["pitch"] == app.cfg["response"]["roll"]


def test_yaw_hold_and_pulse_live(app):
    app.yaw_mode_var.set("hold")
    app.on_yaw_mode()
    X52.axes[5] = 0.5
    assert wait(app, lambda: "XUSB_GAMEPAD_RIGHT_SHOULDER" in pad().buttons)
    assert wait(app, lambda: app.yaw_r_lbl.cget("bg") == "#22c55e")
    X52.axes[5] = 0.0
    assert wait(app, lambda: "XUSB_GAMEPAD_RIGHT_SHOULDER" not in pad().buttons)
    # импульсы: при половинном повороте кнопка то нажата, то отпущена
    app.yaw_mode_var.set("pulse")
    app.on_yaw_mode()
    assert str(app.yaw_scales["period_ms"].cget("state")) == "normal"
    X52.axes[5] = -0.36
    states = set()
    end = time.time() + 1.0
    while time.time() < end:
        app.update()
        states.add("XUSB_GAMEPAD_LEFT_SHOULDER" in pad().buttons)
        time.sleep(0.002)
    assert states == {True, False}
    X52.axes[5] = 0.0
    assert wait(app, lambda: "XUSB_GAMEPAD_LEFT_SHOULDER" not in pad().buttons)


def test_stop_bridge_releases_keys(app):
    X52.buttons[14] = 1       # шасси -> G+LSHIFT
    assert wait(app, lambda: app.worker.keys is not None and app.worker.keys.down == {"G", "LSHIFT"})
    app.toggle_bridge()
    assert wait(app, lambda: not app.worker.bridge_on)
    assert app.worker.keys.down == set()
    X52.buttons[14] = 0


def test_device_loss_releases_keys(app):
    app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on)
    X52.buttons[14] = 1
    assert wait(app, lambda: app.worker.keys.down == {"G", "LSHIFT"})
    X52.alive = False
    assert wait(app, lambda: app.worker.state["name"] is None)
    assert app.worker.keys.down == set()
    X52.alive = True
    X52.buttons[14] = 0
    assert wait(app, lambda: app.worker.state["name"] is not None, sec=4)


def test_profile_roundtrip(app):
    p = str(app.tmp / "profile.json")
    assert app.save_cfg(p)
    before = json.loads(json.dumps(app.cfg))
    app.apply_stick_preset("smooth")
    assert app.load_profile(p)
    assert app.cfg == core.sanitize_config(before)
    assert app.worker.cfg is app.cfg


def test_reset_bindings(app, monkeypatch):
    monkeypatch.setattr(app.L.messagebox, "askyesno", lambda *a, **k: True)
    app.reset_bindings()
    assert app.cfg["bindings"]["gear"] == [None, None]
    assert app.cfg["outputs"]["gear"]["keys"] == ["R"]


def test_profiles_and_custom_actions(app, monkeypatch):
    L = app.L
    if not app.worker.bridge_on:
        app.toggle_bridge()
        assert wait(app, lambda: app.worker.bridge_on)
    pads_before = len(FakePad.instances)
    # --- новый профиль для другой игры: без геймпада, без действий AC8
    app.create_profile("War Thunder", "custom")
    assert wait(app, lambda: app.worker.bridge_on and not app.worker.cfg["game"]["virtual_pad"])
    assert len(FakePad.instances) == pads_before
    assert app.cfg["profile_name"] == "War Thunder" and app.title().endswith("War Thunder")
    assert os.path.exists(L.profile_path("War Thunder")) and os.path.exists(L.profile_path("ACE COMBAT 8"))
    assert app.tree.get_children("") == ("cat:custom",)
    assert set(app.prof_combo.cget("values")) == {"ACE COMBAT 8", "War Thunder"}
    assert app.pad_var.get() is False and app.launch_var.get() == "none"
    # --- своё действие-переключатель
    ca = app.custom_add({"name": "Шасси", "keys": ["G"], "mode": "toggle"})
    assert app.tree.selection() == ("custom:" + ca["id"],)
    assert "переключатель" in app.tree.item("custom:" + ca["id"], "values")[2]
    app.learn_binding(0)
    X52.buttons[20] = 1
    assert wait(app, lambda: ca["bindings"][0] == {"type": "button", "index": 20})
    assert wait(app, lambda: app.worker.keys.down == {"G"})
    X52.buttons[20] = 0
    pump(app, 0.1)
    assert app.worker.keys.down == {"G"}               # переключатель держит
    X52.buttons[20] = 1
    assert wait(app, lambda: app.worker.keys.down == set())
    X52.buttons[20] = 0
    # --- своё действие «удерживать» на ось (крутилка)
    hold = app.custom_add({"name": "Закрылки", "keys": ["F", "LSHIFT"], "mode": "hold"})
    app.learn_binding(0)
    X52.axes[6] = 0.9
    assert wait(app, lambda: hold["bindings"][0] is not None and hold["bindings"][0]["type"] == "axis")
    assert wait(app, lambda: app.worker.keys.down == {"F", "LSHIFT"})
    X52.axes[6] = -1.0
    assert wait(app, lambda: app.worker.keys.down == set())
    # --- изменить и удалить
    app.tree.selection_set("custom:" + hold["id"])
    app.custom_edit({"name": "Закрылки+", "keys": ["V"], "mode": "hold"})
    assert hold["keys"] == ["V"] and app.tree.item("custom:" + hold["id"], "text") == "Закрылки+"
    app.custom_delete(confirm=False)
    assert not app.tree.exists("custom:" + hold["id"]) and len(app.cfg["custom_actions"]) == 1
    # --- запуск: «ничего» и несуществующая программа
    app.play_game()
    assert wait(app, lambda: "запустите игру сами" in app.hint.cget("text"))
    errors = []
    monkeypatch.setattr(L.messagebox, "showerror", lambda *a, **k: errors.append(a))
    app.launch_var.set("exe")
    app.on_launch_type()
    app.exe_var.set(str(app.tmp / "нет_такой.exe"))
    app.play_game()
    assert wait(app, lambda: errors)
    # --- обратно в ACE COMBAT 8: тот же геймпад снова работает (не переподключался), свои действия WT не видны
    app.save_cfg()
    app.switch_profile("ACE COMBAT 8")
    assert wait(app, lambda: app.worker.pad is not None and app.worker.cfg["game"]["virtual_pad"])
    assert len(FakePad.instances) == pads_before
    assert app.cfg["game"]["builtin_actions"] and app.cfg["custom_actions"] == []
    assert "cat:Полёт" in app.tree.get_children("")
    X52.buttons[0] = 1
    assert wait(app, lambda: "XUSB_GAMEPAD_A" in pad().buttons)
    X52.buttons[0] = 0
    # --- и снова War Thunder: всё сохранилось
    app.switch_profile("War Thunder")
    assert [c["name"] for c in app.cfg["custom_actions"]] == ["Шасси"]
    assert app.cfg["game"]["exe_path"].endswith("нет_такой.exe")
    # --- переименование и удаление
    app.profile_rename("WT Sim")
    assert not os.path.exists(L.profile_path("War Thunder")) and os.path.exists(L.profile_path("WT Sim"))
    assert set(L.list_profiles()) == {"ACE COMBAT 8", "WT Sim"}
    app.profile_delete(confirm=False)
    assert app.cfg["profile_name"] == "ACE COMBAT 8" and L.list_profiles() == ["ACE COMBAT 8"]
    assert wait(app, lambda: app.worker.pad is not None)


def test_dialog_sequence_editor(app):
    res = {}

    def drive():
        dlg = [w for w in app.winfo_children() if isinstance(w, app.L.CustomActionDialog)][0]
        try:
            dlg.name_var.set("Запуск двигателя")
            dlg.mode.set("sequence")
            dlg._mode_changed()
            dlg.trig.set("long")
            dlg.layer.set(2)
            for keys, d, dur in ((["RSHIFT", "HOME"], 0, 100), (["RCTRL", "HOME"], 2000, 150)):
                dlg.step_keys = keys
                dlg.delay_var.set(str(d))
                dlg.dur_var.set(str(dur))
                dlg._add_step()
            dlg.lb.selection_set(1)
            dlg._load_step()
            dlg.dur_var.set("200")
            dlg._update_step()
            res["steps"] = [dict(x) for x in dlg.steps]
            dlg._ok()
        finally:
            if dlg.winfo_exists():
                dlg.destroy()
    app.after(200, drive)
    ca = app.custom_add()
    assert ca["mode"] == "sequence" and ca["trigger"] == "long" and ca["layer"] == 2
    assert ca["steps"] == [{"keys": ["RSHIFT", "HOME"], "delay_ms": 0, "duration_ms": 100},
                           {"keys": ["RCTRL", "HOME"], "delay_ms": 2000, "duration_ms": 200}]
    assert "Последовательность: 2 шага" in app.tree.item("custom:" + ca["id"], "values")[2]
    app.tree.selection_set("custom:" + ca["id"])
    app.custom_delete(confirm=False)


def test_layers_short_long_sequence_live(app):
    """Через настоящий рабочий поток: слои, короткое/долгое на одной кнопке, последовательность."""
    app.create_profile("DCS World", "custom")
    if not app.worker.bridge_on:
        app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on and not app.worker.cfg["game"]["virtual_pad"])
    app.nb.select(app.T_MODES)
    app.layers_var.set(True)
    app.on_layers_toggle()
    X52.buttons[30] = 1                         # колесо стоит в положении 2 = кнопка 31
    pump(app, 0.1)
    assert app.detect_wheel(1)                  # «Определить»
    assert app.cfg["layers"]["buttons"][1] == {"type": "button", "index": 30}
    assert app.glob["wheel"]["buttons"] == [23, 30, 25]       # одна настройка на оба раздела
    X52.buttons[30] = 0
    app.long_scale.set(300)
    pump(app, 0.1)
    assert app.cfg["long_press_ms"] == 300
    mk = lambda **k: app.custom_add(dict({"keys": [], "mode": "hold", "trigger": "press", "layer": 0,
                                          "steps": []}, **k))
    a1 = mk(name="Слой1", keys=["A"], layer=1)
    a2 = mk(name="Слой2", keys=["B"], layer=2)
    sh = mk(name="Коротко", keys=["S"], trigger="short")
    lg = mk(name="Долго", keys=["L"], trigger="long")
    sq = mk(name="Запуск", mode="sequence", steps=[{"keys": ["X"], "delay_ms": 0, "duration_ms": 60},
                                                   {"keys": ["Y"], "delay_ms": 150, "duration_ms": 60}])
    for ca, b in ((a1, 15), (a2, 15), (sh, 16), (lg, 16), (sq, 17)):
        ca["bindings"][0] = {"type": "button", "index": b}
    app.refresh_tree()
    assert not app.tree.item("custom:" + a1["id"], "tags")      # разные слои — не конфликт
    assert not app.tree.item("custom:" + sh["id"], "tags")      # короткое+долгое — не конфликт
    down = lambda: app.worker.keys.down
    # слои
    X52.buttons[15] = 1
    assert wait(app, lambda: down() == {"A"})                   # колесо не распознано = слой 1
    assert wait(app, lambda: "не распознано" in app.layer_now.cget("text"))
    X52.buttons[23] = 1                                         # колесо в положении 1
    assert wait(app, lambda: app.layer_now.cget("text") == "Сейчас: слой 1")
    X52.buttons[23] = 0
    X52.buttons[30] = 1
    assert wait(app, lambda: down() == {"B"})
    assert wait(app, lambda: app.layer_now.cget("text") == "Сейчас: слой 2")
    X52.buttons[15] = X52.buttons[30] = 0
    assert wait(app, lambda: down() == set())
    # короткое
    KEYLOG.log.clear()
    X52.buttons[16] = 1
    pump(app, 0.1)
    X52.buttons[16] = 0
    assert wait(app, lambda: ("S", False) in KEYLOG.log)
    assert ("S", True) in KEYLOG.log and ("L", True) not in KEYLOG.log
    # долгое
    KEYLOG.log.clear()
    X52.buttons[16] = 1
    assert wait(app, lambda: down() == {"L"}, sec=1.5)
    X52.buttons[16] = 0
    assert wait(app, lambda: down() == set())
    assert ("S", True) not in KEYLOG.log
    # последовательность
    KEYLOG.log.clear()
    X52.buttons[17] = 1
    pump(app, 0.03)
    X52.buttons[17] = 0
    assert wait(app, lambda: ("Y", False) in KEYLOG.log, sec=1.5)
    evs = [e for e in KEYLOG.log if e[0] in ("X", "Y")]
    assert evs == [("X", True), ("X", False), ("Y", True), ("Y", False)]
    assert app.detect_wheel(1, held=[24])        # вернуть стандартные 24/25/26
    assert app.glob["wheel"]["buttons"] == [23, 24, 25]


def test_auto_switch_process_and_dcs_aircraft(app, monkeypatch, tmp_path):
    L = app.L
    import socket as so
    s0 = so.socket(so.AF_INET, so.SOCK_DGRAM)
    s0.bind(("127.0.0.1", 0))
    port = s0.getsockname()[1]
    s0.close()
    app.glob["dcs_port"] = port
    # профили: DCS World (DCS.exe), DCS F-16 (самолёт), War Thunder (aces.exe)
    app.proc_var.set("DCS.exe")
    app.create_profile("DCS F-16", "custom")
    app.air_var.set("F-16C_50")
    app.create_profile("War Thunder", "custom")
    app.proc_var.set("aces.exe, WarThunder")
    app.save_cfg()
    app.switch_profile("ACE COMBAT 8")
    fg = {"p": "chrome.exe"}
    app._fg_func = lambda: fg["p"]
    app.auto_var.set(True)
    app.on_auto_toggle()
    assert L.load_global()["auto_switch"] is True
    assert wait(app, lambda: app.listener is not None and app.listener.sock is not None)
    pump(app, 1.2)
    assert app.cfg["profile_name"] == "ACE COMBAT 8"           # посторонняя программа — без изменений
    fg["p"] = "WarThunder.exe"
    assert wait(app, lambda: app.cfg["profile_name"] == "War Thunder", sec=3)
    assert app.last_proc == "WarThunder.exe"
    app.switch_profile("ACE COMBAT 8")                          # вручную — не перебивается
    pump(app, 1.3)
    assert app.cfg["profile_name"] == "ACE COMBAT 8"
    fg["p"] = "DCS.exe"
    assert wait(app, lambda: app.cfg["profile_name"] == "DCS World", sec=3)
    snd = so.socket(so.AF_INET, so.SOCK_DGRAM)
    snd.sendto(b"X52L aircraft F-16C_50", ("127.0.0.1", port))
    assert wait(app, lambda: app.cfg["profile_name"] == "DCS F-16", sec=3)
    assert "F-16C_50" in app.air_lbl.cget("text") or app.nb.index("current") != app.T_MODES
    snd.sendto(b"X52L aircraft A-10C_2", ("127.0.0.1", port))
    assert wait(app, lambda: app.cfg["profile_name"] == "DCS World", sec=3)  # самолёт без профиля -> по программе
    snd.close()
    app.auto_var.set(False)
    app.on_auto_toggle()
    assert app.listener is None


def test_dcs_script_install_and_lua_end_to_end(app, monkeypatch, tmp_path):
    import shutil
    import socket as so
    import subprocess
    import x52_dcs
    sg = tmp_path / "Saved Games"
    dcs = sg / "DCS.openbeta"
    (dcs / "Config").mkdir(parents=True)
    (dcs / "Scripts").mkdir()
    other = "-- Tacview\r\nlocal t=1\r\nLuaExportAfterNextFrame = function() tacview_calls = (tacview_calls or 0) + 1 end\r\n"
    (dcs / "Scripts" / "Export.lua").write_bytes(other.encode())
    monkeypatch.setattr(x52_dcs, "saved_games_dir", lambda: str(sg))
    msgs = []
    monkeypatch.setattr(app.L.messagebox, "showinfo", lambda *a, **k: msgs.append(a))
    s0 = so.socket(so.AF_INET, so.SOCK_DGRAM)
    s0.bind(("127.0.0.1", 0))
    port = s0.getsockname()[1]
    s0.close()
    app.glob["dcs_port"] = port
    app.dcs_install()
    app.dcs_install()                                     # повторно — без дублей
    exp = (dcs / "Scripts" / "Export.lua").read_bytes().decode()
    assert exp.startswith(other) and exp.count(x52_dcs.MARK) == 1 and exp.endswith("\r\n")
    assert (dcs / "Scripts" / "Export.lua.x52bak").read_bytes().decode() == other
    assert x52_dcs.is_installed(str(dcs)) and "установлен" in app.dcs_lbl.cget("text")
    assert app.listener is not None and app.listener.port == port
    assert wait(app, lambda: app.listener.sock is not None)
    # сквозная проверка в настоящем Lua 5.1: Export.lua -> наш скрипт -> UDP -> лаунчер
    if shutil.which("lua5.1"):
        run = tmp_path / "dcs_sim.lua"
        run.write_text(
            'package.preload["lfs"] = function() return { writedir = function() return [[%s/]] end } end\n'
            't = 0\nfunction LoGetModelTime() return t end\n'
            'function LoGetSelfData() return { Name = "F-16C_50" } end\n'
            'dofile([[%s]])\n'
            'for i = 1, 8 do t = t + 0.5; LuaExportAfterNextFrame() end\n'
            'print("tacview", tacview_calls)\n' % (str(dcs).replace("\\", "/"),
                                                  str(dcs / "Scripts" / "Export.lua").replace("\\", "/")),
            encoding="utf-8")
        r = subprocess.run(["lua5.1", str(run)], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr
        assert "tacview\t8" in r.stdout                   # чужой экспорт работает как раньше
        assert wait(app, lambda: app.listener.aircraft == "F-16C_50", sec=3)
    app.dcs_uninstall()
    assert (dcs / "Scripts" / "Export.lua").read_bytes().decode() == other   # вернулся байт в байт
    assert not (dcs / "Scripts" / x52_dcs.SCRIPT_NAME).exists()
    app.auto_var.set(False)
    app.on_auto_toggle()
    app.switch_profile("ACE COMBAT 8")


def test_press_release_repeat_live(app):
    app.create_profile("DCS Тест", "custom")
    if not app.worker.bridge_on:
        app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on)
    mk = lambda **k: app.custom_add(dict({"keys": [], "mode": "hold", "trigger": "press", "layer": 0,
                                          "steps": []}, **k))
    c1 = mk(name="Закрыть фонарь", keys=["LCTRL", "C"])
    c2 = mk(name="Запуск двигателя", keys=["RSHIFT", "HOME"], trigger="release")
    rp = mk(name="Пушка очередями", keys=["SPACE"], mode="repeat", repeat_ms=100)
    c1["bindings"][0] = c2["bindings"][0] = {"type": "button", "index": 18}
    rp["bindings"][0] = {"type": "button", "index": 19}
    app.refresh_tree()
    assert not app.tree.item("custom:" + c1["id"], "tags")          # не конфликт
    assert "отпускание" in app.tree.item("custom:" + c2["id"], "values")[2]
    KEYLOG.log.clear()
    X52.buttons[18] = 1
    assert wait(app, lambda: app.worker.keys.down == {"LCTRL", "C"})
    pump(app, 0.2)
    X52.buttons[18] = 0
    assert wait(app, lambda: ("HOME", False) in KEYLOG.log)
    seq = [e for e in KEYLOG.log if e[0] in ("C", "HOME")]
    assert seq == [("C", True), ("C", False), ("HOME", True), ("HOME", False)]
    KEYLOG.log.clear()
    X52.buttons[19] = 1
    pump(app, 0.55)
    X52.buttons[19] = 0
    assert wait(app, lambda: app.worker.keys.down == set())
    presses = KEYLOG.log.count(("SPACE", True))
    assert 4 <= presses <= 7, presses                               # ~каждые 100 мс


def test_profile_cycle_by_button_and_overlay(app, monkeypatch):
    L = app.L
    # «Взлёт» с кнопкой «по кругу», затем копии «Полёт» и «Посадка»
    app.create_profile("Взлёт", "custom")
    cyc = app.custom_add({"name": "Режим полёта", "mode": "profile", "trigger": "press", "layer": 0,
                          "keys": [], "steps": [],
                          "profile": {"kind": "cycle", "names": ["Взлёт", "Полёт", "Посадка"]}})
    cyc["bindings"][0] = {"type": "button", "index": 20}
    gear = app.custom_add({"name": "Шасси", "keys": ["G"], "mode": "hold", "trigger": "press",
                           "layer": 0, "steps": []})
    gear["bindings"][0] = {"type": "button", "index": 20}           # та же кнопка, обычное нажатие
    app.save_cfg()
    app.create_profile("Полёт", "copy")
    app.create_profile("Посадка", "copy")
    assert [c["name"] for c in app.cfg["custom_actions"]] == ["Режим полёта", "Шасси"]
    app.switch_profile("Взлёт")
    if not app.worker.bridge_on:
        app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on)
    app.nb.select(app.T_MODES)
    pump(app, 0.1)
    app.ov_en.set(True)
    app.ov_mode.set("change")
    app.ov_sec.set("1")
    app.on_overlay()
    assert L.load_global()["overlay"]["enabled"] is True
    order = []
    for _ in range(4):
        X52.buttons[20] = 1
        before = app.cfg["profile_name"]
        assert wait(app, lambda: app.cfg["profile_name"] != before, sec=2)
        order.append(app.cfg["profile_name"])
        pump(app, 0.3)                                              # держим: дальше не переключается
        assert app.cfg["profile_name"] == order[-1]
        X52.buttons[20] = 0
        pump(app, 0.15)
        assert wait(app, lambda: app.overlay.text == order[-1] and app.overlay.alpha > 0)
    assert order == ["Полёт", "Посадка", "Взлёт", "Полёт"]
    assert wait(app, lambda: app.overlay.alpha == 0.0, sec=2)      # «при смене, 1 с» — скрылся
    # «всегда» + слой
    app.layers_var.set(True)
    app.on_layers_toggle()
    app.ov_mode.set("always")
    app.on_overlay()
    assert wait(app, lambda: app.overlay.text == "Полёт  ·  слой ?" and app.overlay.alpha > 0.5)
    X52.buttons[23] = 1                                         # колесо в положении 1
    assert wait(app, lambda: app.overlay.text == "Полёт  ·  слой 1")
    X52.buttons[23] = 0
    X52.buttons[24] = 1
    assert wait(app, lambda: app.overlay.text == "Полёт  ·  слой 2")
    X52.buttons[24] = 0
    app.layers_var.set(False)
    app.on_layers_toggle()
    # профиль, которого нет
    app.handle_profile_event({"kind": "name", "names": ["Нет такого"]})
    assert "не найден" in app.hint.cget("text") and app.cfg["profile_name"] == "Полёт"
    app.handle_profile_event({"kind": "next", "names": []})
    assert app.cfg["profile_name"] != "Полёт"
    # и при выключенном мосте кнопка меняет профиль (раньше не меняла — путало)
    app.toggle_bridge()
    assert wait(app, lambda: not app.worker.bridge_on)
    app.switch_profile("Взлёт")
    pump(app, 0.1)
    X52.buttons[20] = 1
    assert wait(app, lambda: app.cfg["profile_name"] == "Полёт")
    X52.buttons[20] = 0
    pump(app, 0.1)
    # но не во время назначения кнопки
    app.switch_profile("Взлёт")
    app.tree.selection_set(app.tree.get_children("cat:custom")[0])
    app.learn_binding(1)
    X52.buttons[20] = 1
    pump(app, 0.4)
    assert app.cfg["profile_name"] == "Взлёт"
    app.cancel_learn()
    X52.buttons[20] = 0
    pump(app, 0.1)
    app.ov_en.set(False)
    app.on_overlay()
    assert app.overlay.alpha == 0.0
    app.switch_profile("ACE COMBAT 8")


def test_dialog_profile_and_repeat(app):
    res = {}

    def drive():
        dlg = [w for w in app.winfo_children() if isinstance(w, app.L.CustomActionDialog)][0]
        try:
            assert "Взлёт" in dlg.pcombo.cget("values")
            dlg.name_var.set("Режимы")
            dlg.mode.set("profile")
            dlg._mode_changed()
            dlg.trig.set("release")
            for n in ("Посадка", "Взлёт", "Полёт"):
                dlg.pcombo.set(n)
                dlg._p_add()
            dlg.plb.selection_set(0)
            dlg._p_move(1)                                  # Посадка вниз
            res["list"] = list(dlg.plb.get(0, "end"))
            dlg._ok()
        finally:
            if dlg.winfo_exists():
                dlg.destroy()
    app.after(200, drive)
    ca = app.custom_add()
    assert res["list"] == ["1. Взлёт", "2. Посадка", "3. Полёт"]
    assert ca["mode"] == "profile" and ca["trigger"] == "release"
    assert ca["profile"] == {"kind": "cycle", "names": ["Взлёт", "Посадка", "Полёт"]}
    app.tree.selection_set("custom:" + ca["id"])
    app.custom_delete(confirm=False)

    def drive2():
        dlg = [w for w in app.winfo_children() if isinstance(w, app.L.CustomActionDialog)][0]
        try:
            dlg.name_var.set("Очередь")
            dlg.mode.set("repeat")
            dlg._mode_changed()
            dlg.keys = ["SPACE"]
            dlg.rep_var.set("80")
            dlg._ok()
        finally:
            if dlg.winfo_exists():
                dlg.destroy()
    app.after(200, drive2)
    ca = app.custom_add()
    assert ca["mode"] == "repeat" and ca["repeat_ms"] == 80 and ca["keys"] == ["SPACE"]
    app.tree.selection_set("custom:" + ca["id"])
    app.custom_delete(confirm=False)


def _find(app, cls):
    for w in app.winfo_children():
        if isinstance(w, cls):
            return w
        for ch in w.winfo_children():
            if isinstance(ch, cls):
                return ch
    return None


def test_key_dialog_list_selection_is_kept(app):
    """Регресс: выбор в списке + сразу OK терял клавишу."""
    L = app.L
    d = L.KeyDialog(app, "t", ["R"], ["R"])
    d.cb.current(core.ALL_KEYS.index("G"))
    d.cb.event_generate("<<ComboboxSelected>>")
    d.update()
    assert d.keys == ["G"] and d.lbl.cget("text") == "G (П)"
    d.cb.focus_set()                                   # фокус на списке — нажатие всё равно ловится
    d.update()
    d.cb.event_generate("<KeyPress>", keysym="h", when="now")
    d.update()
    assert d.keys == ["H"]
    d.event_generate("<KeyPress>", keysym="space", when="now")   # пробел — клавиша, не кнопка
    d.update()
    assert d.keys == ["SPACE"] and d.winfo_exists()
    d.combo_var.set(True)
    d.cb.current(core.ALL_KEYS.index("MOUSE_LEFT"))
    d.cb.event_generate("<<ComboboxSelected>>")
    d.update()
    d._ok()
    assert d.result == ["SPACE", "MOUSE_LEFT"]


def test_custom_action_key_full_path_saved(app):
    """Своё действие: «Выбрать…» -> список -> OK -> OK -> клавиша в профиле и на диске."""
    L = app.L
    done = {}

    def in_keydlg():
        kd = _find(app, L.KeyDialog)
        try:
            kd.cb.current(core.ALL_KEYS.index("F5"))
            kd.cb.event_generate("<<ComboboxSelected>>")
            kd.update()
            kd._ok()
        finally:
            if kd.winfo_exists():
                kd.destroy()

    def in_dialog():
        dlg = _find(app, L.CustomActionDialog)
        try:
            dlg.name_var.set("Карта")
            app.after(150, in_keydlg)
            dlg._pick()                                 # «Выбрать…» (ждёт окно клавиши)
            done["shown"] = dlg.key_lbl.cget("text")
            dlg._ok()
        finally:
            if dlg.winfo_exists():
                dlg.destroy()
    app.after(200, in_dialog)
    ca = app.custom_add()
    assert done["shown"] == "F5" and ca is not None and ca["keys"] == ["F5"]
    # изменить клавишу через «Клавиша…» на вкладке (KeyDialog напрямую)
    app.tree.selection_set("custom:" + ca["id"])

    def in_keydlg2():
        kd = _find(app, L.KeyDialog)
        try:
            kd.cb.current(core.ALL_KEYS.index("F6"))
            kd.cb.event_generate("<<ComboboxSelected>>")
            kd.update()
            kd._ok()
        finally:
            if kd.winfo_exists():
                kd.destroy()
    app.after(200, in_keydlg2)
    app.edit_keys()
    assert ca["keys"] == ["F6"]
    assert app.save_cfg()
    with open(L.CONFIG_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    assert [c["keys"] for c in saved["custom_actions"] if c["id"] == ca["id"]] == [["F6"]]
    with open(L.profile_path(app.cfg["profile_name"]), encoding="utf-8") as f:
        assert [c["keys"] for c in json.load(f)["custom_actions"] if c["id"] == ca["id"]] == [["F6"]]
    app.custom_delete(confirm=False)


def test_builtin_action_key_saved(app):
    L = app.L
    app.switch_profile("ACE COMBAT 8")
    assert app.cfg["game"]["builtin_actions"]
    app.tree.selection_set("gear")
    assert app._selected_action() == "gear"

    def in_keydlg():
        kd = _find(app, L.KeyDialog)
        try:
            kd.cb.current(core.ALL_KEYS.index("B"))
            kd.cb.event_generate("<<ComboboxSelected>>")
            kd.update()
            kd._ok()
        finally:
            if kd.winfo_exists():
                kd.destroy()
    app.after(200, in_keydlg)
    app.edit_keys()
    assert app.cfg["outputs"]["gear"] == {"via": "key", "keys": ["B"]}
    assert "B (И)" in app.tree.item("gear", "values")[2]


def test_axis_enable_checkbox(app):
    app.switch_profile("ACE COMBAT 8")
    if not app.worker.bridge_on:
        app.cfg["throttle_cal"]["recorded"] = [k for k, _ in core.CAL_ROWS]
        app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on and app.worker.pad is not None)
    # ось крена (1) назначена как кнопка у своего действия -> ⚠, пока ось аналоговая
    ca = app.custom_add({"name": "Крен как клавиша", "keys": ["F9"], "mode": "hold", "trigger": "press",
                         "layer": 0, "steps": []})
    ca["bindings"][0] = {"type": "axis", "index": 0, "dir": "+", "thr": 0.5}
    app.refresh_tree()
    assert "⚠" in app.tree.item("custom:" + ca["id"], "values")[0]
    X52.axes[0] = 0.8
    assert wait(app, lambda: pad().left[0] > 0.5 and app.worker.keys.down == {"F9"})   # двойное
    X52.axes[0] = 0.0
    assert wait(app, lambda: pad().left[0] == 0.0 and app.worker.keys.down == set())
    # снимаем галочку крена
    app.nb.select(app.T_AXES)
    pump(app, 0.05)
    app.axen_var["roll"].set(False)
    app.on_axis_enable("roll")
    assert app.cfg["axes_enabled"]["roll"] is False and app.cfg["axes"]["roll"] == 0
    assert "⚠" not in app.tree.item("custom:" + ca["id"], "values")[0]
    X52.axes[0] = 0.8
    assert wait(app, lambda: app.worker.keys.down == {"F9"})
    pump(app, 0.1)
    assert pad().left[0] == 0.0                                 # в стик не уходит
    X52.axes[0] = 0.0
    assert wait(app, lambda: app.worker.keys.down == set())
    # сохраняется и восстанавливается
    app.save_cfg()
    with open(app.L.CONFIG_PATH, encoding="utf-8") as f:
        assert json.load(f)["axes_enabled"]["roll"] is False
    app.axen_var["roll"].set(True)
    app.on_axis_enable("roll")
    X52.axes[0] = 0.8
    assert wait(app, lambda: pad().left[0] > 0.5)
    X52.axes[0] = 0.0
    app.tree.selection_set("custom:" + ca["id"])
    app.custom_delete(confirm=False)


def test_rs_view_tiles_dialog_and_live(app, monkeypatch):
    import x52_rsview as rv
    L = app.L
    app.create_profile("RS Тест", "custom")
    if not app.worker.bridge_on:
        app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on)
    app.nb.select(app.T_RS)
    assert wait(app, lambda: len(app.rs.btn_tiles) == len(X52.buttons) and len(app.rs.hat_tiles) == 2)
    assert app.rs.dev.get_children() and "X52" in app.rs.dev.item(app.rs.dev.get_children()[0], "values")[0]
    assert app.prof_status.cget("text") == "Текущий профиль: RS Тест"
    # плитки показывают нажатия X52
    X52.buttons[6] = 1
    assert wait(app, lambda: app.rs.btn_tiles[6].pressed is True)
    X52.buttons[6] = 0
    assert wait(app, lambda: app.rs.btn_tiles[6].pressed is False)
    app.rs.nb.select(0)                                          # открыта внутренняя вкладка «Кнопки»
    X52.hats[0] = (1, 1)
    assert wait(app, lambda: app.rs.hat_tiles[0].cells["ne"]["on"] and not app.rs.hat_tiles[0].cells["n"]["on"])
    assert wait(app, lambda: app.rs.nb.tab(1, "text") == "Хатки ↗")   # направление видно в названии
    assert "вкладке «Хатки»" in app.hint.cget("text")
    cv = app.rs.hat_tiles[0].cells["ne"]["cv"]
    assert cv.itemcget(cv.find_all()[0], "fill") == "#22b14c"          # стрелка реально зелёная
    X52.hats[0] = (0, 0)
    assert wait(app, lambda: app.rs.nb.tab(1, "text") == "Хатки")
    # окно «Выбор срабатывающего действия»: заполняем как пользователь
    res = {}

    def drive():
        dlg = [w for w in app.winfo_children() if isinstance(w, rv.RsActionDialog)][0]
        try:
            sp, rl = dlg.cols["single"], dlg.cols["release"]
            sp.en.set(True)
            sp._state()
            sp.name.set("Закрыть фонарь")
            sp.mods["LCTRL"].set(True)
            sp.key.set(core.key_text("C"))
            rl.en.set(True)
            rl._state()
            rl.name.set("Запуск двигателя")
            app.after(150, lambda: _keydlg_pick("HOME"))
            rl._capture()                                    # «…» -> окно выбора клавиши
            rl.mods["RSHIFT"].set(True)
            res["key"] = rl.key.get()
            dlg._ok()
        finally:
            if dlg.winfo_exists():
                dlg.destroy()

    def _keydlg_pick(k):
        kd = [w for w in app.winfo_children() + [x for y in app.winfo_children() for x in y.winfo_children()]
              if isinstance(w, L.KeyDialog)][0]
        kd.cb.current(core.ALL_KEYS.index(k))
        kd.cb.event_generate("<<ComboboxSelected>>")
        kd.update()
        kd._ok()
    app.after(200, drive)
    tile = app.rs.btn_tiles[6]
    app.rs.open_dialog(tile.b)
    assert res["key"] == core.key_text("HOME")
    s = rv.find_slots(app.cfg, tile.b)
    assert s["single"]["keys"] == ["LCTRL", "C"] and s["release"]["keys"] == ["RSHIFT", "HOME"]
    assert tile.marks.state == {"single": True, "long": False, "release": True}
    assert len(app.rs.acts.get_children()) == 2
    # через рабочий поток: нажал — тап Ctrl+C, отпустил — тап RShift+Home
    KEYLOG.log.clear()
    X52.buttons[6] = 1
    assert wait(app, lambda: ("C", False) in KEYLOG.log)
    pump(app, 0.2)
    assert ("HOME", True) not in KEYLOG.log
    X52.buttons[6] = 0
    assert wait(app, lambda: ("HOME", False) in KEYLOG.log)
    # хатка: точная диагональ
    app.rs.open_dialog(rv.hat_binding(0, "ne"), cols={
        "single": {"enabled": True, "name": "Вверх-вправо", "kind": "key", "mods": [], "key": "F7",
                   "repeat": False, "repeat_ms": 100, "continuous": True, "seq": "", "profile": "", "special": False},
        "long": {"enabled": False}, "release": {"enabled": False}})
    X52.hats[0] = (0, 1)
    pump(app, 0.15)
    assert "F7" not in app.worker.keys.down
    X52.hats[0] = (1, 1)
    assert wait(app, lambda: "F7" in app.worker.keys.down)
    X52.hats[0] = (0, 0)
    assert wait(app, lambda: "F7" not in app.worker.keys.down)
    # переименование кнопки
    app.rs.rename(tile.b, "Фонарь/двигатель")
    assert app.cfg["button_names"]["b6"] == "Фонарь/двигатель"
    assert "Фонарь" in tile.name.cget("text")
    assert any(app.rs.acts.item(i, "values")[3] == "Фонарь/двигатель" for i in app.rs.acts.get_children())
    app.rs.rename(tile.b, "")
    assert "b6" not in app.cfg["button_names"]
    # последовательности: менеджер + действие из библиотеки
    app.rs.open_sequences()
    sm = [w for w in app.winfo_children() if isinstance(w, rv.SequenceManager)][0]
    sm.new_seq("Запуск ВСУ")
    sm.lb.selection_set(0)
    sm._load()
    for key, delay in (("A", 0), ("B", 120)):
        sm.s_key.set(core.key_text(key))
        sm.s_delay.set(str(delay))
        sm.s_dur.set("50")
        sm.add_step()
    assert [st["keys"] for st in app.cfg["sequences"][0]["steps"]] == [["A"], ["B"]]
    sm.destroy()
    app.rs.open_dialog(rv.btn_binding(7), cols={
        "single": {"enabled": True, "name": "ВСУ", "kind": "seq", "seq": "Запуск ВСУ", "mods": [], "key": "",
                   "repeat": False, "repeat_ms": 100, "continuous": False, "profile": "", "special": False},
        "long": {"enabled": False}, "release": {"enabled": False}})
    KEYLOG.log.clear()
    X52.buttons[7] = 1
    pump(app, 0.03)
    X52.buttons[7] = 0
    assert wait(app, lambda: ("B", False) in KEYLOG.log)
    assert [e for e in KEYLOG.log if e[0] in "AB"] == [("A", True), ("A", False), ("B", True), ("B", False)]
    # переименование последовательности обновляет ссылки действий
    app.rs.open_sequences()
    sm = [w for w in app.winfo_children() if isinstance(w, rv.SequenceManager)][0]
    sm.lb.selection_set(0)
    sm.rename_seq("Запуск APU")
    sm.destroy()
    assert rv.find_slots(app.cfg, rv.btn_binding(7))["single"]["seq"] == "Запуск APU"
    # меню «Профиль»: радиокнопки профилей, переключение
    app._fill_profile_menu()
    labels = [app.profile_menu.entrycget(i, "label") for i in range(app.profile_menu.index("end") + 1)
              if app.profile_menu.type(i) == "radiobutton"]
    assert "RS Тест" in labels and "ACE COMBAT 8" in labels
    i = labels.index("ACE COMBAT 8")
    radios = [k for k in range(app.profile_menu.index("end") + 1) if app.profile_menu.type(k) == "radiobutton"]
    app.profile_menu.invoke(radios[i])
    assert app.cfg["profile_name"] == "ACE COMBAT 8"
    assert app.prof_status.cget("text") == "Текущий профиль: ACE COMBAT 8"
    app.switch_profile("RS Тест")
    assert len(app.rs.acts.get_children()) == 4                  # сохранилось в профиле
    app.switch_profile("ACE COMBAT 8")


def test_wheel_profiles(app, monkeypatch):
    L = app.L
    for n in ("Колесо А", "Колесо Б", "Колесо В"):
        app.create_profile(n, "custom")
    for i in (23, 24, 25):
        X52.buttons[i] = 0
    X52.buttons[24] = 1                                         # колесо в положении 2
    app.nb.select(app.T_MODES)
    pump(app, 0.1)
    assert "Колесо Б" in app.wheel_combo[0].cget("values")
    app.wheel_en.set(True)
    for i, n in enumerate(("Колесо А", "Колесо Б", "Колесо В")):
        app.wheel_combo[i].set(n)
    app.on_wheel()
    gw = L.load_global()["wheel"]
    assert {k: gw[k] for k in ("enabled", "buttons", "profiles")} == {
        "enabled": True, "buttons": [23, 24, 25], "profiles": ["Колесо А", "Колесо Б", "Колесо В"]}
    assert wait(app, lambda: app.cfg["profile_name"] == "Колесо Б")          # сразу по положению
    assert wait(app, lambda: app.wheel_now.cget("text") == "Колесо сейчас: положение 2")

    def turn(p):
        for i in (23, 24, 25):
            X52.buttons[i] = 0
        X52.buttons[22 + p] = 1
    turn(3)
    assert wait(app, lambda: app.cfg["profile_name"] == "Колесо В")
    turn(1)
    assert wait(app, lambda: app.cfg["profile_name"] == "Колесо А")
    # свёрнутое окно — тоже работает
    app.iconify()
    monkeypatch.setattr(app, "state", lambda *a: "iconic")
    turn(2)
    assert wait(app, lambda: app.cfg["profile_name"] == "Колесо Б")
    monkeypatch.undo()
    app.deiconify()
    # пока открыт диалог — ждёт, после закрытия переключает
    dlg = L.KeyDialog(app, "t", [], [])
    turn(3)
    pump(app, 0.4)
    assert app.cfg["profile_name"] == "Колесо Б"
    dlg.destroy()
    assert wait(app, lambda: app.cfg["profile_name"] == "Колесо В")
    # «не переключать» и несуществующий профиль
    app.wheel_combo[0].set(app.NO_PROFILE)
    app.on_wheel()
    turn(1)
    pump(app, 0.4)
    assert app.cfg["profile_name"] == "Колесо В"
    app.glob["wheel"]["profiles"][1] = "Нет такого"
    turn(2)
    assert wait(app, lambda: "не найден" in app.hint.cget("text"))
    # «Определить»: другая кнопка для положения 3
    for i in (23, 24, 25):
        X52.buttons[i] = 0
    X52.buttons[33] = 1
    pump(app, 0.1)
    app.learn_wheel(2)
    assert app.glob["wheel"]["buttons"][2] == 33 and app.cfg["layers"]["buttons"][2]["index"] == 33
    X52.buttons[33] = 0
    assert app.wheel_btn_lbl[2].cget("text") == "Кнопка 34"
    # выключили — не трогает профиль
    app.glob["wheel"]["buttons"][2] = 25
    app.wheel_en.set(False)
    app.on_wheel()
    turn(3)
    pump(app, 0.4)
    assert app.cfg["profile_name"] == "Колесо В"
    for i in (23, 24, 25):
        X52.buttons[i] = 0
    app.switch_profile("ACE COMBAT 8")


def test_wheel_position_not_recognized_and_relearn(app):
    """Положение 2 колеса у этого X52 — другая кнопка (31): лаунчер не выдаёт это за слой 1."""
    app.create_profile("Колесо-слои", "custom")
    app.layers_var.set(True)
    app.on_layers_toggle()
    app.ov_en.set(True)
    app.ov_mode.set("always")
    app.on_overlay()
    app.nb.select(app.T_MODES)
    pos_btn = {1: 23, 2: 30, 3: 25}                    # «настоящие» кнопки этого X52

    def turn(p):
        for b in pos_btn.values():
            X52.buttons[b] = 0
        X52.buttons[pos_btn[p]] = 1
    turn(1)
    assert wait(app, lambda: app.layer_now.cget("text") == "Сейчас: слой 1")
    turn(2)
    assert wait(app, lambda: "не распознано" in app.layer_now.cget("text"))
    assert wait(app, lambda: "31" in app.layer_btns.cget("text"))
    assert wait(app, lambda: app.overlay.text.endswith("слой ?"))
    # «Определить», когда колесо стоит в положении 2 — берётся зажатая сейчас кнопка 31
    app.learn_layer(1)
    assert app.cfg["layers"]["buttons"][1] == {"type": "button", "index": 30}
    assert app.glob["wheel"]["buttons"] == [23, 30, 25]
    assert wait(app, lambda: app.layer_now.cget("text") == "Сейчас: слой 2")
    assert wait(app, lambda: app.overlay.text.endswith("слой 2"))
    turn(3)
    assert wait(app, lambda: app.layer_now.cget("text") == "Сейчас: слой 3")
    # ошибки «Определить»: ничего не нажато / нажато несколько
    msgs = []
    import x52_ac8_launcher as L
    orig = L.messagebox.showinfo
    L.messagebox.showinfo = lambda *a, **k: msgs.append(a[1])
    try:
        for b in pos_btn.values():
            X52.buttons[b] = 0
        pump(app, 0.1)
        assert app.detect_wheel(0) is False and "ни одна" in msgs[-1]
        X52.buttons[23] = X52.buttons[5] = 1
        pump(app, 0.1)
        assert app.detect_wheel(0) is False and "6" in msgs[-1] and "24" in msgs[-1]
        X52.buttons[5] = 0
    finally:
        L.messagebox.showinfo = orig
    # кнопка положения 1 зажата, а «Определить» нажали у положения 3 (колесо не повернули):
    # лаунчер спрашивает; «Нет» — ничего не меняется, «Да» — меняются местами, дублей нет
    asked = []
    L.messagebox.askyesno, orig_ask = (lambda *a, **k: asked.append(a[1]) or False), L.messagebox.askyesno
    try:
        assert app.detect_wheel(2, held=[23]) is False and app.glob["wheel"]["buttons"] == [23, 30, 25]
        assert "уже записана для положения 1" in asked[-1]
        L.messagebox.askyesno = lambda *a, **k: True
        assert app.detect_wheel(2, held=[23]) and app.glob["wheel"]["buttons"] == [25, 30, 23]
    finally:
        L.messagebox.askyesno = orig_ask
    # дубль (старый конфиг) — красное предупреждение
    app.glob["wheel"]["buttons"] = [23, 23, 25]
    app.wheel_buttons_to_layers()
    assert wait(app, lambda: "одна кнопка" in app.layer_now.cget("text")
                and "одна кнопка" in app.wheel_now.cget("text"))
    for k, p in ((23, 0), (24, 1), (25, 2)):
        app.detect_wheel(p, held=[k], confirm=False)
    assert app.glob["wheel"]["buttons"] == [23, 24, 25] and not app.wheel_problem()
    # кнопки колеса одинаковы во всех профилях
    app.switch_profile("ACE COMBAT 8")
    assert [b["index"] for b in app.cfg["layers"]["buttons"]] == [23, 24, 25]
    app.switch_profile("Колесо-слои")
    for b in pos_btn.values():
        X52.buttons[b] = 0
    X52.buttons[23] = 0
    app.ov_en.set(False)
    app.on_overlay()
    app.switch_profile("ACE COMBAT 8")


def test_wheel_wizard(app):
    """Мастер: колесо 1 -> «Начать» -> 2 -> 3; проход через среднее и дребезг не записываются."""
    L = app.L
    app.glob["wheel"]["buttons"] = [24, 23, 24]                  # испорчено, как у пользователя
    app.wheel_buttons_to_layers()
    app.glob["wheel"]["enabled"] = True
    app.glob["wheel"]["profiles"] = ["ACE COMBAT 8", "", ""]
    app._wheel_pos = None
    w = L.WheelWizard(app)
    held = {"v": [26]}                                           # у этого X52 колесо = 27/28/29
    w.held = lambda: list(held["v"])
    t = [100.0]

    def run(buttons, sec):
        held["v"] = buttons
        end = t[0] + sec
        while t[0] < end:
            t[0] += 0.03
            w.step(now=t[0])
    run([26], 0.5)
    assert w.found == []                                         # до «Начать» не пишет
    w.start()
    run([26], 0.4)                                               # положение 1
    run([], 0.05)                                                # между положениями
    run([27], 0.1)                                               # дребезг 2 (короче порога)
    run([], 0.05)
    run([27], 0.4)                                               # положение 2
    run([27, 5], 0.4)                                            # случайно нажата ещё кнопка — пропуск
    run([28], 0.06)                                              # проход…
    run([28], 0.4)                                               # положение 3
    assert w.found == [26, 27, 28]
    assert "Положение 3 = кнопка 29" in w.res.cget("text") and str(w.save_btn.cget("state")) == "normal"
    # пока мастер открыт, профиль колесом не переключается
    assert app.grab_current() is not None
    w.save()
    assert app.glob["wheel"]["buttons"] == [26, 27, 28]
    assert [b["index"] for b in app.cfg["layers"]["buttons"]] == [26, 27, 28]
    assert L.load_global()["wheel"]["buttons"] == [26, 27, 28] and not app.wheel_problem()
    # «Заново»
    w2 = L.WheelWizard(app)
    w2.held = lambda: [23]
    w2.start()
    w2.step(now=1.0)
    w2.step(now=1.5)
    assert w2.found == [23]
    w2.start()
    assert w2.found == [] and str(w2.save_btn.cget("state")) == "disabled"
    w2.destroy()
    app.set_wheel_buttons([23, 24, 25])
    app.glob["wheel"]["enabled"] = False
    app.save_global()


def test_rs_axes_tab_live(app):
    app.switch_profile("ACE COMBAT 8")
    if not app.worker.bridge_on:
        app.cfg["throttle_cal"]["recorded"] = [k for k, _ in core.CAL_ROWS]
        app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on)
    app.nb.select(app.T_RS)
    assert wait(app, lambda: len(app.rs.axis_tiles) == len(X52.axes))
    app.rs.nb.select(2)
    pump(app, 0.1)
    t3 = app.rs.axis_tiles[3]                                   # «крутилка»
    # крутилка вправо за порог: стрелка «+» загорается
    X52.axes[3] = 0.7
    assert wait(app, lambda: t3.dirs["+"]["on"] is True and t3.dirs["-"]["on"] is False)
    X52.axes[3] = 0.0
    assert wait(app, lambda: t3.dirs["+"]["on"] is False)
    # назначение: «+» — нажатие F8 (непрерывно), «−» — отпускание F9
    C = lambda **k: dict({"enabled": True, "name": "", "kind": "key", "mods": [], "key": "", "repeat": False,
                          "repeat_ms": 100, "continuous": False, "seq": "", "profile": "", "special": False}, **k)
    app.rs.open_dialog(t3._binding("+"), cols={"single": C(name="Свет", key="F8", continuous=True),
                                               "long": {"enabled": False}, "release": {"enabled": False}})
    app.rs.open_dialog(t3._binding("-"), cols={"single": {"enabled": False}, "long": {"enabled": False},
                                               "release": C(name="Свет-", key="F9")})
    assert t3.dirs["+"]["marks"].state["single"] and t3.dirs["-"]["marks"].state["release"]
    X52.axes[3] = 0.7
    assert wait(app, lambda: "F8" in app.worker.keys.down)
    X52.axes[3] = 0.0
    assert wait(app, lambda: "F8" not in app.worker.keys.down)
    KEYLOG.log.clear()
    X52.axes[3] = -0.8
    pump(app, 0.2)
    X52.axes[3] = 0.0
    assert wait(app, lambda: ("F9", False) in KEYLOG.log)               # отпускание «−»
    # порог «+» = 0.2: срабатывает раньше
    app.rs.ask_thr(3, "+", 0.2)
    assert "≥ +0.20" in t3.dirs["+"]["thr"].cget("text")
    X52.axes[3] = 0.3
    assert wait(app, lambda: "F8" in app.worker.keys.down)
    X52.axes[3] = 0.0
    assert wait(app, lambda: "F8" not in app.worker.keys.down)
    # название оси
    app.rs.rename_axis(3, "Крутилка I")
    assert t3.cget("text").startswith("Крутилка I")
    assert any(app.rs.acts.item(i, "values")[3] == "Крутилка I +" for i in app.rs.acts.get_children())
    # РУД (ось 3) работает аналогово — предупреждение и «Отключить аналог»
    t2 = app.rs.axis_tiles[2]
    assert "двойное" in t2.warn.cget("text") and t2.off_btn.winfo_manager() == "pack"
    t2._analog_off()
    assert app.cfg["axes_enabled"]["throttle"] is False and app.axen_var["throttle"].get() is False
    assert t2.warn.cget("text") == "" and t2.off_btn.winfo_manager() == ""
    app.axen_var["throttle"].set(True)
    app.on_axis_enable("throttle")
    app.rs.rename_axis(3, "")
    for ca in list(app.cfg["custom_actions"]):
        if ca["name"] in ("Свет", "Свет-"):
            app.cfg["custom_actions"].remove(ca)
    app.refresh_tree()
    app.rs.nb.select(0)


def test_rs_layer_follows_wheel(app):
    import x52_rsview as rv
    app.create_profile("Слои-карта", "custom")
    app.layers_var.set(True)
    app.on_layers_toggle()
    a2 = app.custom_add({"name": "Слой2", "keys": ["B"], "mode": "hold", "trigger": "press", "layer": 2,
                         "steps": []})
    a2["bindings"][0] = rv.btn_binding(7)
    app.refresh_tree()
    app.nb.select(app.T_RS)
    tile = None

    def turn(p):
        for i in (23, 24, 25):
            X52.buttons[i] = 0
        X52.buttons[22 + p] = 1
    turn(1)
    assert wait(app, lambda: app.rs.layer.get() == "слой 1")
    tile = app.rs.btn_tiles[7]
    assert not tile.marks.state["single"]
    turn(2)
    assert wait(app, lambda: app.rs.layer.get() == "слой 2")
    assert wait(app, lambda: tile.marks.state["single"])          # отметки слоя 2
    turn(3)
    assert wait(app, lambda: app.rs.layer.get() == "слой 3")
    # ручной выбор держится до следующего поворота
    app.rs.layer.current(2)
    app.rs.refresh()
    pump(app, 0.3)
    assert app.rs.layer.get() == "слой 2"
    turn(1)
    assert wait(app, lambda: app.rs.layer.get() == "слой 1")
    # «за колесом» снята — не следует
    app.rs.follow.set(False)
    turn(2)
    pump(app, 0.3)
    assert app.rs.layer.get() == "слой 1"
    app.rs.follow.set(True)
    assert wait(app, lambda: app.rs.layer.get() == "слой 2")
    for i in (23, 24, 25):
        X52.buttons[i] = 0
    app.switch_profile("ACE COMBAT 8")


def test_rs_mouse_wheel_scrolls_under_cursor(app):
    import types
    app.switch_profile("ACE COMBAT 8")
    app.nb.select(app.T_RS)
    app.rs.nb.select(0)
    assert wait(app, lambda: len(app.rs.btn_tiles) > 30)
    pump(app, 0.3)
    cv = app.rs.btn_area.canvas
    assert cv.yview()[1] < 1.0, "кнопок должно быть больше, чем помещается"

    def wheel(widget, delta=None, num=None):
        x, y = widget.winfo_rootx() + 5, widget.winfo_rooty() + 5
        ev = types.SimpleNamespace(x_root=x, y_root=y, delta=delta or 0, num=num)
        return app.rs._on_wheel(ev)
    tile = app.rs.btn_tiles[13]                                      # средний ряд — остаётся видимой
    assert cv.yview()[0] == 0.0
    assert wheel(tile.name, delta=-120) == "break"                  # над названием плитки
    pump(app, 0.05)
    y1 = cv.yview()[0]
    assert y1 > 0.0
    wheel(tile.cv, delta=-240)                                      # над значком — 2 деления
    pump(app, 0.05)
    assert cv.yview()[0] > y1
    wheel(tile.marks, num=4)                                        # колёсико вверх (Linux)
    wheel(tile.marks, num=4)
    wheel(tile.marks, num=4)
    pump(app, 0.05)
    assert cv.yview()[0] == 0.0
    # над таблицей «Все назначенные действия» холст не трогаем
    assert wheel(app.rs.acts, delta=-120) is None
    assert cv.yview()[0] == 0.0
    # настоящее событие колёсика X11 на плитке
    tile.update()
    tile.event_generate("<Button-5>", x=5, y=5, rootx=tile.winfo_rootx() + 5, rooty=tile.winfo_rooty() + 5)
    pump(app, 0.1)
    assert cv.yview()[0] > 0.0
    cv.yview_moveto(0)
    # вкладка «Оси»: прокрутка над шкалой
    app.rs.nb.select(2)
    pump(app, 0.3)
    acv = app.rs.axis_area.canvas
    if acv.yview()[1] < 1.0:
        wheel(app.rs.axis_tiles[0].bar, delta=-120)
        pump(app, 0.05)
        assert acv.yview()[0] > 0.0
        acv.yview_moveto(0)
    app.rs.nb.select(0)


def test_424_profile_switch_no_reopen_no_stick_drop(app, monkeypatch):
    """Смена профиля: джойстик не открывается заново, ручка не проваливается, клавиши отпускаются."""
    import x52_ac8_launcher as L
    calls = []
    orig = L.Worker._scan
    monkeypatch.setattr(L.Worker, "_scan", lambda self: (calls.append(1), orig(self))[1])
    app.switch_profile("ACE COMBAT 8")
    app.create_profile("424-А", "ac8")                       # оба — с виртуальным геймпадом
    app.cfg["throttle_cal"]["recorded"] = [k for k, _ in core.CAL_ROWS]
    app.create_profile("424-Б", "copy")
    ca = app.custom_add({"name": "держать", "keys": ["F11"], "mode": "hold", "trigger": "press", "layer": 0,
                         "steps": []})
    ca["bindings"][0] = {"type": "button", "index": 16}
    app.save_cfg()
    app.switch_profile("ACE COMBAT 8")
    if not app.worker.bridge_on:
        app.cfg["throttle_cal"]["recorded"] = [k for k, _ in core.CAL_ROWS]
        app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on and app.worker.pad is not None)
    X52.axes[0] = 0.6                                       # ручка держится вправо
    assert wait(app, lambda: pad().left[0] > 0.5)
    resets = []
    p = pad()
    monkeypatch.setattr(p, "reset", lambda: resets.append(1))
    lefts = []
    calls.clear()
    for n in ("424-А", "424-Б", "ACE COMBAT 8", "424-А", "ACE COMBAT 8"):
        app.switch_profile(n)
        for _ in range(10):
            app.update()
            lefts.append(pad().left[0])
            time.sleep(0.004)
    assert calls == [], "при смене профиля джойстик открывался заново"
    assert min(lefts) > 0.5, "ручка проваливалась в ноль при смене профиля"
    assert resets == [] and pad() is p
    X52.axes[0] = 0.0
    # клавиши старого профиля отпускаются при смене
    app.switch_profile("424-Б")
    X52.buttons[16] = 1
    assert wait(app, lambda: "F11" in app.worker.keys.down)
    app.switch_profile("ACE COMBAT 8")
    assert wait(app, lambda: "F11" not in app.worker.keys.down)
    X52.buttons[16] = 0
    # другой джойстик в профиле — тогда открываем заново
    app.cfg["device_name"] = "Другой джойстик"
    app.save_cfg()
    app.switch_profile("424-А")
    calls.clear()
    app.switch_profile("ACE COMBAT 8")
    app.cfg["device_name"] = ""
    app.switch_profile("424-А")
    pump(app, 0.2)
    app.switch_profile("ACE COMBAT 8")


def test_424_combo_keys_order_live(app):
    """Кнопка X52 -> Ctrl+C (фонарь): в игру сначала Ctrl, потом C; отпускание наоборот."""
    app.create_profile("424-фонарь", "custom")
    if not app.worker.bridge_on:
        app.toggle_bridge()
    assert wait(app, lambda: app.worker.bridge_on)
    for mode in ("tap", "hold"):
        ca = app.custom_add({"name": "Фонарь " + mode, "keys": ["LCTRL", "C"], "mode": mode, "trigger": "press",
                             "layer": 0, "steps": []})
        ca["bindings"][0] = {"type": "button", "index": 17}
        KEYLOG.log.clear()
        X52.buttons[17] = 1
        pump(app, 0.15)
        X52.buttons[17] = 0
        assert wait(app, lambda: ("LCTRL", False) in KEYLOG.log)
        ev = [e for e in KEYLOG.log if e[0] in ("LCTRL", "C")]
        assert ev == [("LCTRL", True), ("C", True), ("C", False), ("LCTRL", False)], (mode, ev)
        app.tree.selection_set("custom:" + ca["id"])
        app.custom_delete(confirm=False)
    app.switch_profile("ACE COMBAT 8")


def test_close_saves_and_no_errors(app):
    app.on_close()
    with open(app.L.CONFIG_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["version"] == 3
    assert core.sanitize_config(saved) == saved
    assert not app.worker.is_alive()
    assert not os.path.exists(app.L.ERROR_LOG), open(app.L.ERROR_LOG, encoding="utf-8").read()


def test_zz_noise_light_mode_and_no_tasklist():
    """Отдельный запуск: дрожание X52 не уходит в игру, свёрнутое окно не рисует, tasklist не зовётся."""
    import random
    import threading
    import x52_ac8_launcher as L
    calls = []
    L.process_running = lambda img: calls.append(img) or False
    old_win = L.IS_WIN
    L.IS_WIN = True                    # включаем ветку проверки x360ce
    L.CONFIG_PATH = L.CONFIG_PATH + ".2"
    X52.alive = True
    a = L.App()
    try:
        pump(a, 0.6)
        a.cfg["throttle_cal"]["recorded"] = [k for k, _ in core.CAL_ROWS]
        a._conflict_t = 0
        a.toggle_bridge()
        ok = wait(a, lambda: a.worker.bridge_on)
        if not ok:
            import threading as _th
            print("\nDIAG alive=%s err=%r name=%r q=%d threads=%s" % (
                a.worker.is_alive(), a.worker.error, a.worker.state.get("name"), a.worker.cmds.qsize()
                if hasattr(a.worker, "cmds") else -1, [t.name for t in _th.enumerate()]))
            if os.path.exists(L.ERROR_LOG):
                print("LOG:", open(L.ERROR_LOG, encoding="utf-8").read()[-1500:])
            import traceback as _tb
            fr = sys._current_frames().get(a.worker.ident)
            print("STACK:\n" + "".join(_tb.format_stack(fr)[-8:]) if fr else "no frame")
        assert ok
        calls.clear()
        stop = []

        def noise():
            r = random.Random(3)
            while not stop:
                for i in (0, 1, 5):
                    X52.axes[i] = 0.4 + r.uniform(-0.003, 0.003)
                time.sleep(0.003)
        th = threading.Thread(target=noise, daemon=True)
        th.start()
        pump(a, 0.5)
        n0 = pad().updates
        pump(a, 2.0)
        assert pad().updates - n0 <= 2, "шум ушёл в игру"
        # реальное движение — не чаще max_hz
        stop.append(1)
        th.join()
        n0, t0 = pad().updates, time.time()
        for k in range(200):
            X52.axes[0] = -1 + k * 0.01
            a.update()
            time.sleep(0.005)
        rate = (pad().updates - n0) / (time.time() - t0)
        assert 10 < rate <= a.cfg["output"]["max_hz"] * 1.1
        # кнопка — сразу
        X52.buttons[0] = 1
        assert wait(a, lambda: "XUSB_GAMEPAD_A" in pad().buttons, sec=0.3)
        X52.buttons[0] = 0
        assert wait(a, lambda: "XUSB_GAMEPAD_A" not in pad().buttons, sec=0.3)
        # свёрнутое окно: виджеты не трогаются
        a.iconify()
        a.state = lambda *x: "iconic"     # в Xvfb нет оконного менеджера — сворачивание имитируем
        pump(a, 0.3)
        a._wcache.clear()
        seen = []
        orig = a._set_text
        a._set_text = lambda *x, **k: seen.append(x) or orig(*x, **k)
        pump(a, 1.0)
        assert seen == []
        assert calls == [], "tasklist запускался во время моста"
        a.deiconify()
        del a.state
        pump(a, 0.3)
        assert seen, "после разворачивания окно снова обновляется"
        X52.axes[0] = X52.axes[1] = X52.axes[5] = 0.0
    finally:
        L.IS_WIN = old_win
        a.on_close()
    assert not os.path.exists(L.ERROR_LOG)


def test_scan_closes_own_virtual_pad_and_other_devices(monkeypatch):
    import x52_ac8_launcher as L

    class Dev:
        def __init__(self, name):
            self.name, self.closed = name, False

        def get_name(self):
            return self.name

        def quit(self):
            self.closed = True

    devs = [Dev("Controller (XBOX 360 For Windows)"), Dev("Saitek X52 Flight Control System"),
            Dev("Some Wheel")]
    monkeypatch.setattr(pygame.joystick, "get_count", lambda: len(devs))
    monkeypatch.setattr(pygame.joystick, "Joystick", lambda i: devs[i])
    monkeypatch.setattr(pygame.joystick, "init", lambda: None)
    monkeypatch.setattr(pygame.joystick, "quit", lambda: None)
    w = L.Worker(core.default_config())
    w._scan()
    assert w.joy is devs[1] and not devs[1].closed
    assert devs[0].closed, "свой виртуальный геймпад остался открытым"
    assert devs[2].closed
    assert w.devices == ["Saitek X52 Flight Control System", "Some Wheel"]


def test_no_audio_and_sdl_hints():
    import x52_ac8_launcher as L
    assert L.APP_VERSION       # импорт выставляет переменные SDL
    for h in ("SDL_XINPUT_ENABLED", "SDL_JOYSTICK_WGI", "SDL_JOYSTICK_RAWINPUT", "SDL_JOYSTICK_HIDAPI"):
        assert os.environ.get(h) == "0", h
    assert pygame.mixer.get_init() is None, "звуковое устройство открыто"
    import ast
    tree = ast.parse(open(os.path.join(ROOT, "x52_ac8_launcher.py"), encoding="utf-8").read())
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "pygame.init" not in calls and "pygame.mixer.init" not in calls
    assert "pygame.display.init" in calls


def test_low_priority_winapi(monkeypatch):
    import ctypes
    import x52_ac8_launcher as L
    calls = []

    class Fn:
        def __init__(self, f):
            self.f = f

        def __call__(self, *a):
            return self.f(*a)

    class K32:
        GetCurrentProcess = Fn(lambda: 1234)
        SetPriorityClass = Fn(lambda h, c: calls.append((h, c)) or 1)

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: K32(), raising=False)
    monkeypatch.setattr(L, "IS_WIN", True)
    assert L.set_low_priority(True) and L.set_low_priority(False)
    assert calls == [(1234, 0x4000), (1234, 0x20)]
    monkeypatch.setattr(L, "IS_WIN", False)
    assert L.set_low_priority(True) is False


def test_restart_keeps_pad_when_setting_unchanged():
    import x52_ac8_launcher as L
    w = L.Worker(core.default_config())
    w.cfg["throttle_cal"]["recorded"] = []
    w._start_bridge()
    first = w.pad
    w.keys = core.KeySender(backend=core._NullInput())
    w.keys.apply({"G"})
    w.send("restart")
    w._handle_cmds()
    assert w.pad is first and w.bridge_on          # тот же геймпад, без переподключения
    assert w.keys.down == set()                     # клавиши прежнего профиля отпущены
    # профиль без геймпада: геймпад НЕ отключается (иначе игра пишет «отключён»), но и не получает данных
    w.cfg["game"]["virtual_pad"] = False
    w.send("restart")
    w._handle_cmds()
    assert w.pad is first and w.bridge_on
    sent = []
    first.left_joystick_float = lambda **k: sent.append(k)
    w._apply(dict(core.EMPTY_OUT, roll=0.5))
    assert sent == []
    w.cfg["game"]["virtual_pad"] = True
    w.send("restart")
    w._handle_cmds()
    assert w.pad is first and w.bridge_on
    w._stop_bridge()
    # мост запущен в профиле без геймпада -> переключились на профиль с геймпадом: геймпад появляется
    w.cfg["game"]["virtual_pad"] = False
    w._start_bridge()
    assert w.pad is None
    w.cfg["game"]["virtual_pad"] = True
    w.send("restart")
    w._handle_cmds()
    assert w.pad is not None and w.bridge_on
    w._stop_bridge()



def test_424_autostart_and_wheel_after_restart(tmp_path_factory, monkeypatch):
    """Новый запуск лаунчера: мост включается сам (галочка общая), колесо известно сразу,
    хотя Windows после открытия джойстика ещё не сообщила зажатую кнопку колеса."""
    import x52_ac8_launcher as L
    tmp = tmp_path_factory.mktemp("restart")
    monkeypatch.setattr(L, "CONFIG_PATH", str(tmp / "x52_config.json"))
    monkeypatch.setattr(L, "ERROR_LOG", str(tmp / "x52_error.log"))
    X52.alive = True
    X52.buttons = [0] * 39
    # --- первый запуск: галочка в профиле «А», колесо в положении 2, профили по колесу, слои
    a = L.App()
    try:
        pump(a, 0.5)
        a.cfg["throttle_cal"]["recorded"] = [k for k, _ in core.CAL_ROWS]
        for n in ("Р-взлёт", "Р-полёт", "Р-посадка"):
            a.create_profile(n, "custom")
            a.layers_var.set(True)
            a.on_layers_toggle()
            a.save_cfg()
        a.switch_profile("Р-взлёт")
        a.autostart_var.set(True)
        a.on_autostart()
        a.wheel_en.set(True)
        for i, n in enumerate(("Р-взлёт", "Р-полёт", "Р-посадка")):
            a.wheel_combo[i].set(n)
        a.on_wheel()
        X52.buttons[24] = 1                                     # положение 2
        assert wait(a, lambda: a.cfg["profile_name"] == "Р-полёт")
        assert a.cfg["launcher"]["autostart_bridge"] is False   # в этом профиле галочки нет — неважно
        pump(a, 1.3)                                            # последнее положение сохранилось
    finally:
        a.on_close()
    g = L.load_global()
    assert g["autostart_bridge"] is True and g["wheel"]["last"] == 1
    # --- второй запуск: как в Windows — зажатая кнопка колеса после открытия НЕ видна
    X52.buttons = [0] * 39
    b = L.App()
    try:
        assert wait(b, lambda: b.worker.bridge_on, sec=3), "мост не включился при открытии лаунчера"
        b.nb.select(b.T_MODES)
        assert wait(b, lambda: b.wheel_now.cget("text") == "Колесо сейчас: положение 2")
        assert wait(b, lambda: b.layer_now.cget("text") == "Сейчас: слой 2")
        assert b.cfg["profile_name"] == "Р-полёт"
        X52.buttons[25] = 1                                     # повернули в 3 — живой сигнал
        assert wait(b, lambda: b.cfg["profile_name"] == "Р-посадка")
        assert wait(b, lambda: b.wheel_now.cget("text") == "Колесо сейчас: положение 3")
        assert wait(b, lambda: b.layer_now.cget("text") == "Сейчас: слой 3")
        X52.buttons[25] = 0
        X52.buttons[33] = 1                                     # кнопка колеса неизвестна — честно
        assert wait(b, lambda: "не распознано" in b.wheel_now.cget("text"))
        X52.buttons[33] = 0
        b.autostart_var.set(False)
        b.on_autostart()
        b.wheel_en.set(False)
        b.on_wheel()
    finally:
        b.on_close()
    assert L.load_global()["autostart_bridge"] is False
    X52.buttons = [0] * 39


def test_424_autostart_migrates_from_profile(tmp_path_factory, monkeypatch):
    import x52_ac8_launcher as L
    tmp = tmp_path_factory.mktemp("migr")
    monkeypatch.setattr(L, "CONFIG_PATH", str(tmp / "x52_config.json"))
    monkeypatch.setattr(L, "ERROR_LOG", str(tmp / "x52_error.log"))
    os.makedirs(tmp / "profiles")
    prof = core.new_profile_config("Старый", "custom", core.default_config())
    prof["launcher"]["autostart_bridge"] = True                 # галочка была в профиле (4.2.3)
    with open(tmp / "profiles" / "Старый.json", "w", encoding="utf-8") as f:
        json.dump(prof, f)
    X52.alive = True
    a = L.App()
    try:
        assert a.glob["autostart_bridge"] is True and a.autostart_var.get() is True
        assert a.glob["auto_switch"] is False and a.auto_var.get() is False   # разные галочки
        assert wait(a, lambda: a.worker.bridge_on, sec=3)
    finally:
        a.on_close()


def test_500_selftest_mode_writes_result(tmp_path, monkeypatch):
    import x52_ac8_launcher as L
    res = tmp_path / "r.txt"
    assert L.run_selftest(str(res)) == 0 and res.read_text(encoding="utf-8") == "OK"
    monkeypatch.setitem(sys.modules, "vgamepad", types.SimpleNamespace(
        VX360Gamepad=lambda: (_ for _ in ()).throw(OSError("нет ViGEmBus")), XUSB_BUTTON=_B))
    assert L.run_selftest(str(res)) == 1 and "нет ViGEmBus" in res.read_text(encoding="utf-8")



