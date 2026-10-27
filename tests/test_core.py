# -*- coding: utf-8 -*-
import copy
import json
import math
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import x52_core as c  # noqa: E402


def cfg():
    return c.default_config()


def run(m, conf, axes, buttons=(), hats=(), t=0.0):
    return m.step(conf, list(axes), list(buttons), list(hats), now=t)


AX0 = [0.0] * 8


def axes_with(**kw):
    a = list(AX0)
    a[2] = 1.0   # РУД полностью назад по умолчанию -> всё равно нейтраль вычисляется калибровкой
    idx = {"roll": 0, "pitch": 1, "throttle": 2, "yaw": 5}
    for k, v in kw.items():
        a[idx[k]] = v
    return a


# ------------------------------------------------------------------ конфиг
class TestConfig:
    def test_default_is_self_consistent(self):
        d = cfg()
        assert c.sanitize_config(d) == c.sanitize_config(json.loads(json.dumps(d)))
        for aid in c.ACTION_IDS:
            assert len(d["bindings"][aid]) == 2
            o = d["outputs"][aid]
            assert o["via"] in ("pad", "key")
            assert all(k in c.ALL_KEYS for k in o["keys"]), aid
            if c.ACTION_PAD[aid] is None:
                assert o["via"] == "key" and o["keys"], aid

    def test_sanitize_idempotent(self):
        once = c.sanitize_config(cfg())
        assert c.sanitize_config(copy.deepcopy(once)) == once

    def test_garbage(self):
        for junk in (None, 5, "x", [], {"axes": 7, "bindings": "x", "response": {"roll": "q"},
                                         "outputs": {"gun": {"via": "zz", "keys": ["NOPE", 3]}}}):
            out = c.sanitize_config(junk)
            assert out["outputs"]["gun"]["via"] == "pad"
            assert out["outputs"]["gun"]["keys"] == ["J"]
            assert out["response"]["roll"]["sensitivity"] > 0

    def test_users_real_v2_config_migrates(self):
        with open(os.path.join(ROOT, "x52_config.json"), encoding="utf-8-sig") as f:
            old = json.load(f)
        new = c.sanitize_config(old)
        # 2.x ids переименованы
        assert new["bindings"]["next_weapon"] == [{"type": "button", "index": 2}, None]
        assert new["bindings"]["gun"] == [{"type": "button", "index": 0}, None]
        assert new["bindings"]["order_sp"][0] == {"type": "hat", "index": 0, "dir": "right"}
        # мёртвые зоны перенесены, оси и калибровка сохранены
        assert new["response"]["roll"]["deadzone"] == pytest.approx(0.04)
        assert new["axes"] == old["axes"]
        assert new["throttle_cal"]["raw_aft"] == 1.0
        # рыскание — новые отзывчивые значения
        assert new["response"]["yaw"]["threshold"] == pytest.approx(0.12)
        assert new["response"]["yaw"]["mode"] == "hold"
        assert new["camera"]["stick_speed"] == 3.0  # не было в файле -> по умолчанию

    def test_v1_ids(self):
        new = c.sanitize_config({"bindings": {"dpad_up": {"type": "hat", "index": 0, "dir": "up"},
                                              "accel_btn": {"type": "button", "index": 4}}})
        assert new["bindings"]["order_attack"][0]["dir"] == "up"
        assert new["bindings"]["throttle_up"][0]["index"] == 4

    def test_binding_pairs(self):
        b = {"type": "button", "index": 3}
        new = c.sanitize_config({"bindings": {"gun": [None, b], "missile": [b, b],
                                              "gear": [{"type": "axis", "index": 2, "dir": "+", "thr": 9}]}})
        assert new["bindings"]["gun"] == [b, None]           # дополнительная сдвигается в основную
        assert new["bindings"]["missile"] == [b, None]       # одинаковые — одна
        assert new["bindings"]["gear"][0]["thr"] == 0.95     # порог ограничен

    def test_keyboard_only_action_forced_to_key(self):
        new = c.sanitize_config({"outputs": {"gear": {"via": "pad", "keys": ["R"]}}})
        assert new["outputs"]["gear"]["via"] == "key"

    def test_internal_action_forced_to_pad(self):
        new = c.sanitize_config({"outputs": {"center_view": {"via": "key", "keys": ["F"]}}})
        assert new["outputs"]["center_view"]["via"] == "pad"

    def test_yaw_full_kept_above_threshold(self):
        new = c.sanitize_config({"response": {"yaw": {"threshold": 0.8, "full": 0.2}}})
        assert new["response"]["yaw"]["full"] >= new["response"]["yaw"]["threshold"] + 0.05 - 1e-9

    def test_keys_limited_and_deduped(self):
        new = c.sanitize_config({"outputs": {"gear": {"via": "key", "keys": ["R", "R", "A", "B", "C"]}}})
        assert new["outputs"]["gear"]["keys"] == ["R", "A", "B"]

    def test_default_keys_match_game_screenshots(self):
        k = {aid: c.ACTION_KEYS[aid] for aid in c.ACTION_IDS}
        assert k["pitch_up"] == ["S"] and k["pitch_down"] == ["W"]     # Ы / Ц
        assert k["roll_left"] == ["A"] and k["roll_right"] == ["D"]    # Ф / В
        assert k["yaw_left"] == ["Q"] and k["yaw_right"] == ["E"]      # Й / У
        assert k["gear"] == ["R"] and k["flare"] == ["X"]              # К / Ч
        assert k["target"] == ["T"] and k["map"] == ["M"]              # Е / Ь
        assert k["autopilot"] == ["Z"] and k["view"] == ["V"]          # Я / М
        assert k["std_missile"] == ["1"] and k["special1"] == ["2"] and k["special2"] == ["3"]
        assert k["cam_up"] == ["7"] and k["cam_right"] == ["0"]
        assert k["prev_weapon"] == ["I"] and k["next_weapon"] == ["K"]  # Ш / Л
        assert k["gun"] == ["J"] and k["missile"] == ["L"]              # О / Д
        assert k["throttle_up"] == ["SPACE"] and k["throttle_down"] == ["LCTRL"]


# ------------------------------------------------------------------ отклик ручки
class TestShape:
    R = {"deadzone": 0.05, "anti_deadzone": 0.2, "sensitivity": 1.0, "curve": 1.0, "smoothing_ms": 0}

    def test_zero_and_deadzone(self):
        assert c.shape_axis(0.0, self.R) == 0.0
        assert c.shape_axis(0.05, self.R) == 0.0
        assert c.shape_axis(-0.04, self.R) == 0.0

    def test_anti_deadzone_jump(self):
        v = c.shape_axis(0.051, self.R)
        assert 0.2 <= v < 0.21

    def test_full_and_symmetry(self):
        assert c.shape_axis(1.0, self.R) == pytest.approx(1.0)
        for x in (0.1, 0.3, 0.77):
            assert c.shape_axis(-x, self.R) == pytest.approx(-c.shape_axis(x, self.R))

    def test_monotonic_all_presets(self):
        for p in c.STICK_PRESETS.values():
            prev = -1.0
            for i in range(-100, 101):
                v = c.shape_axis(i / 100.0, p)
                assert v >= prev - 1e-12
                assert -1.0 <= v <= 1.0
                prev = v

    def test_sensitivity_saturates(self):
        r = dict(self.R, anti_deadzone=0.0, deadzone=0.0, sensitivity=2.0)
        assert c.shape_axis(0.25, r) == pytest.approx(0.5)
        assert c.shape_axis(0.6, r) == 1.0

    def test_curve(self):
        r = dict(self.R, anti_deadzone=0.0, deadzone=0.0)
        assert c.shape_axis(0.5, dict(r, curve=0.5)) > 0.5 > c.shape_axis(0.5, dict(r, curve=2.0))

    def test_bad_input(self):
        assert c.shape_axis(float("nan"), self.R) == 0.0
        assert c.shape_axis(5.0, self.R) == 1.0


class TestMapperSticks:
    def test_invert_pitch_and_roll_passthrough(self):
        d = cfg()
        for r in ("roll", "pitch"):
            d["response"][r] = {"deadzone": 0.0, "anti_deadzone": 0.0, "sensitivity": 1.0, "curve": 1.0,
                                "smoothing_ms": 0}
        out = run(c.Mapper(), d, axes_with(roll=0.5, pitch=-0.4))
        assert out["roll"] == pytest.approx(0.5)
        assert out["pitch"] == pytest.approx(0.4)   # pitch инвертирован по умолчанию

    def test_no_smoothing_is_instant(self):
        d = cfg()
        m = c.Mapper()
        run(m, d, axes_with(roll=0.0), t=0.0)
        out = run(m, d, axes_with(roll=1.0), t=0.004)
        assert out["roll"] == pytest.approx(1.0)

    def test_smoothing_time_constant(self):
        d = cfg()
        d["response"]["roll"].update(smoothing_ms=50, deadzone=0, anti_deadzone=0, sensitivity=1, curve=1)
        m = c.Mapper()
        run(m, d, axes_with(roll=0.0), t=0.0)
        t = 0.0
        out = None
        for _ in range(50):           # 50 шагов по 1 мс = одна постоянная времени
            t += 0.001
            out = run(m, d, axes_with(roll=1.0), t=t)
        assert out["roll"] == pytest.approx(1 - math.exp(-1), abs=0.01)

    def test_missing_axes_safe(self):
        out = run(c.Mapper(), cfg(), [], [], [])
        assert out["roll"] == 0 and out["pitch"] == 0 and not out["actions"]

    def test_nan_axis(self):
        out = run(c.Mapper(), cfg(), [float("nan")] * 8)
        assert out["roll"] == 0.0 and out["lt"] == 0.0 and out["rt"] == 0.0


# ------------------------------------------------------------------ рыскание
class TestYaw:
    def conf(self, **kw):
        d = cfg()
        d["response"]["yaw"].update(kw)
        return d

    def test_hold_threshold(self):
        d = self.conf(mode="hold", threshold=0.12)
        m = c.Mapper()
        assert "yaw_right" not in run(m, d, axes_with(yaw=0.10))["actions"]
        o = run(m, d, axes_with(yaw=0.13), t=0.001)
        assert "yaw_right" in o["actions"] and "RB" in o["pressed"]
        o = run(c.Mapper(), d, axes_with(yaw=-0.5))
        assert "yaw_left" in o["actions"] and "LB" in o["pressed"]

    def test_hysteresis(self):
        d = self.conf(mode="hold", threshold=0.2)
        m = c.Mapper()
        assert "yaw_right" in run(m, d, axes_with(yaw=0.21), t=0.0)["actions"]
        assert "yaw_right" in run(m, d, axes_with(yaw=0.19), t=0.01)["actions"]     # держится
        assert "yaw_right" not in run(m, d, axes_with(yaw=0.17), t=0.02)["actions"]

    def test_delay(self):
        d = self.conf(mode="hold", delay_ms=50)
        m = c.Mapper()
        assert not run(m, d, axes_with(yaw=0.8), t=0.000)["actions"] & {"yaw_right"}
        assert not run(m, d, axes_with(yaw=0.8), t=0.049)["actions"] & {"yaw_right"}
        assert "yaw_right" in run(m, d, axes_with(yaw=0.8), t=0.051)["actions"]

    def test_pulse_duty_proportional(self):
        d = self.conf(mode="pulse", threshold=0.1, full=0.9, period_ms=100, min_pulse_ms=10)
        for yaw, expect in ((0.3, 0.25), (0.5, 0.5), (0.7, 0.75)):
            m = c.Mapper()
            on = 0
            n = 2000
            for i in range(n):           # 2 секунды по 1 мс
                if "yaw_right" in run(m, d, axes_with(yaw=yaw), t=i * 0.001)["actions"]:
                    on += 1
            assert on / n == pytest.approx(expect, abs=0.03), yaw

    def test_pulse_min_width_and_full(self):
        d = self.conf(mode="pulse", threshold=0.1, full=0.9, period_ms=100, min_pulse_ms=25)
        m = c.Mapper()
        on = sum("yaw_right" in run(m, d, axes_with(yaw=0.101), t=i * 0.001)["actions"] for i in range(1000))
        assert on / 1000 == pytest.approx(0.25, abs=0.02)
        m = c.Mapper()
        assert all("yaw_right" in run(m, d, axes_with(yaw=0.95), t=i * 0.001)["actions"] for i in range(300))

    def test_pulse_first_press_is_immediate(self):
        d = self.conf(mode="pulse", threshold=0.1, full=0.9)
        assert "yaw_right" in run(c.Mapper(), d, axes_with(yaw=0.3), t=5.0)["actions"]

    def test_yaw_via_keyboard(self):
        d = cfg()
        d["outputs"]["yaw_left"] = {"via": "key", "keys": ["Q"]}
        o = run(c.Mapper(), d, axes_with(yaw=-0.9))
        assert o["keys"] == {"Q"} and "LB" not in o["pressed"]

    def test_no_yaw_axis(self):
        d = cfg()
        d["axes"]["yaw"] = None
        assert not run(c.Mapper(), d, axes_with(yaw=1.0))["actions"]


# ------------------------------------------------------------------ привязки
class TestBindings:
    def test_axis_plus_minus_and_hysteresis(self):
        b = {"type": "axis", "index": 3, "dir": "+", "thr": 0.5}
        ax = [0, 0, 0, 0.49]
        assert not c.binding_active(b, [], [], ax)
        ax[3] = 0.5
        assert c.binding_active(b, [], [], ax)
        ax[3] = 0.47
        assert c.binding_active(b, [], [], ax, was_active=True)
        assert not c.binding_active(b, [], [], ax, was_active=False)
        bm = {"type": "axis", "index": 3, "dir": "-", "thr": -0.2}
        assert c.binding_active(bm, [], [], [0, 0, 0, -0.3])
        assert not c.binding_active(bm, [], [], [0, 0, 0, 0.0])
        assert not c.binding_active(b, [], [], [0, 0])               # индекс вне диапазона
        assert not c.binding_active(b, [], [], [0, 0, 0, float("nan")])

    def test_hat_diagonal(self):
        up = {"type": "hat", "index": 0, "dir": "up"}
        right = {"type": "hat", "index": 0, "dir": "right"}
        assert c.binding_active(up, [], [(1, 1)]) and c.binding_active(right, [], [(1, 1)])

    def test_mapper_axis_binding_with_hysteresis(self):
        d = cfg()
        d["bindings"]["gear"] = [{"type": "axis", "index": 6, "dir": "+", "thr": 0.5}, None]
        m = c.Mapper()
        a = axes_with()
        a[6] = 0.6
        assert run(m, d, a, t=0.0)["keys"] == {"R"}
        a[6] = 0.48
        assert run(m, d, a, t=0.01)["keys"] == {"R"}
        a[6] = 0.4
        assert run(m, d, a, t=0.02)["keys"] == set()

    def test_secondary_binding(self):
        d = cfg()
        d["bindings"]["special1"] = [{"type": "button", "index": 20}, {"type": "hat", "index": 2, "dir": "up"}]
        hats = [(0, 0), (0, 0), (0, 1)]
        assert run(c.Mapper(), d, axes_with(), [0] * 32, hats)["keys"] == {"2"}

    def test_learn_axis_binding(self):
        assert c.learn_axis_binding(0.0, 0.9) == {"type": "axis", "dir": "+", "thr": 0.5}
        assert c.learn_axis_binding(0.02, -0.8) == {"type": "axis", "dir": "-", "thr": -0.5}
        b = c.learn_axis_binding(-1.0, 0.6)       # рычаг из крайнего положения
        assert b["dir"] == "+" and b["thr"] == pytest.approx(-0.2)
        b = c.learn_axis_binding(1.0, -0.2)
        assert b["dir"] == "-" and b["thr"] == pytest.approx(0.4)

    def test_binding_text(self):
        assert c.binding_text({"type": "axis", "index": 2, "dir": "+", "thr": 0.5}) == "Ось 3 + (≥ +0.50)"
        assert c.binding_text({"type": "hat", "index": 0, "dir": "left"}) == "Хатка 1 ←"
        assert c.binding_text(None) == "—"


# ------------------------------------------------------------------ выходы
class TestOutputs:
    def test_pad_vs_key(self):
        d = cfg()
        btn = [0] * 32
        btn[0] = 1
        o = run(c.Mapper(), d, axes_with(), btn)
        assert "A" in o["pressed"] and not o["keys"]
        d["outputs"]["gun"] = {"via": "key", "keys": ["J"]}
        o = run(c.Mapper(), d, axes_with(), btn)
        assert "A" not in o["pressed"] and o["keys"] == {"J"}

    def test_highg_combo(self):
        d = cfg()
        btn = [0] * 32
        btn[5] = 1
        o = run(c.Mapper(), d, axes_with(), btn)
        assert o["lt"] == 1.0 and o["rt"] == 1.0
        d["outputs"]["highg"]["via"] = "key"
        o = run(c.Mapper(), d, axes_with(), btn)
        assert o["keys"] == {"SPACE", "LCTRL"}

    def test_internal_commands(self):
        btn = [0] * 32
        btn[11] = 1
        o = run(c.Mapper(), cfg(), axes_with(), btn)
        assert o["internal"] == {"CENTER"} and not o["keys"] and not o["pressed"]

    def test_digital_pitch_overrides_analog(self):
        d = cfg()
        d["bindings"]["pitch_up"] = [{"type": "button", "index": 30}, None]
        d["outputs"]["pitch_up"]["via"] = "pad"
        btn = [0] * 32
        btn[30] = 1
        o = run(c.Mapper(), d, axes_with(pitch=-1.0), btn)
        assert o["pitch"] == -1.0

    def test_throttle_split(self):
        d = cfg()
        o = run(c.Mapper(), d, axes_with(throttle=-1.0))
        assert o["rt"] == pytest.approx(1.0) and o["lt"] == 0.0
        o = run(c.Mapper(), d, axes_with(throttle=1.0))
        assert o["lt"] == pytest.approx(1.0) and o["rt"] == 0.0
        o = run(c.Mapper(), d, axes_with(throttle=0.0))
        assert o["lt"] == 0.0 and o["rt"] == 0.0


# ------------------------------------------------------------------ клавиатура
class TestKeys:
    def test_scancodes_unique(self):
        seen = {}
        for k, v in c.KEYS.items():
            assert v not in seen, (k, seen.get(v))
            seen[v] = k
            assert 0 < v[0] < 0x80

    def test_sender_diff(self):
        s = c.KeySender(backend=c._NullInput())
        s.apply({"W", "SPACE"})
        s.apply({"SPACE", "MOUSE_LEFT", "BOGUS"})
        s.apply({"SPACE", "MOUSE_LEFT"})          # без изменений — без событий
        s.release_all()
        log = s.backend.log
        assert log == [("SPACE", True), ("W", True), ("W", False), ("MOUSE_LEFT", True),
                       ("MOUSE_LEFT", False), ("SPACE", False)]
        assert s.down == set()

    def test_key_from_tk(self):
        assert c.key_from_tk_event("Cyrillic_tse", 0x57, is_win=True) == "W"   # рус. раскладка
        assert c.key_from_tk_event("Cyrillic_tse", 0, is_win=False) == "W"
        assert c.key_from_tk_event("Cyrillic_TSE", 0, is_win=False) == "W"
        assert c.key_from_tk_event("Control_R", 0x11, is_win=True) == "RCTRL"
        assert c.key_from_tk_event("Shift_L", 0x10, is_win=True) == "LSHIFT"
        assert c.key_from_tk_event("space", 0x20, is_win=True) == "SPACE"
        assert c.key_from_tk_event("KP_8", 0x68, is_win=True) == "NUM8"
        assert c.key_from_tk_event("Up", 0x26, is_win=True) == "UP"
        assert c.key_from_tk_event("Escape", 0x1B, is_win=True) == "ESC"
        assert c.key_from_tk_event("q", 0, is_win=False) == "Q"
        assert c.key_from_tk_event("weird", 0x07, is_win=True) is None

    def test_key_text(self):
        assert c.key_text("W") == "W (Ц)"
        assert c.key_text("M") == "M (Ь)"
        assert c.key_text("SPACE") == "Пробел"
        assert c.keys_text(["SPACE", "LCTRL"]) == "Пробел + Ctrl (лев.)"


# ------------------------------------------------------------------ скорость
def test_mapper_fast_enough_for_1000hz():
    d = cfg()
    d["response"]["roll"]["smoothing_ms"] = 20
    d["response"]["yaw"].update(mode="pulse", smoothing_ms=10)
    d["bindings"]["gear"] = [{"type": "axis", "index": 6, "dir": "+", "thr": 0.5}, None]
    m = c.Mapper()
    a = axes_with(roll=0.3, pitch=-0.2, yaw=0.4, throttle=-0.5)
    btn = [0] * 39
    hats = [(0, 0), (0, 0)]
    n = 5000
    t0 = time.perf_counter()
    for i in range(n):
        m.step(d, a, btn, hats, now=i * 0.001)
    per = (time.perf_counter() - t0) / n
    assert per < 0.0005, f"{per * 1e6:.0f} мкс на шаг"


# ------------------------------------------------------------------ Windows SendInput (структуры и флаги)
def test_win_sendinput_structures(monkeypatch):
    import ctypes
    sent = []

    class FakeFn:
        def __call__(self, n, ptr, size):
            inp = ptr._obj
            sent.append((n, size, inp.type, inp.ki.wScan, inp.ki.dwFlags, inp.mi.dwFlags, inp.mi.mouseData))
            return 1

    class FakeUser32:
        SendInput = FakeFn()

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: FakeUser32(), raising=False)
    w = c._WinInput()
    assert ctypes.sizeof(w.INPUT) == 40   # как sizeof(INPUT) в 64-битной Windows
    w.send("W", True)
    w.send("UP", False)
    w.send("MOUSE_LEFT", True)
    w.send("MOUSE_X2", False)
    # W: scan 0x11, KEYEVENTF_SCANCODE
    assert sent[0][2:5] == (1, 0x11, 0x0008)
    # стрелка вверх: extended + keyup
    assert sent[1][2:5] == (1, 0x48, 0x0008 | 0x0001 | 0x0002)
    # мышь: LEFTDOWN; X2 up с mouseData = XBUTTON2
    assert sent[2][2] == 0 and sent[2][5] == 0x0002
    assert sent[3][2] == 0 and sent[3][5] == 0x0100 and sent[3][6] == 2
    assert all(s[1] == ctypes.sizeof(w.INPUT) for s in sent)


# ------------------------------------------------------------------ фильтр выхода
def _o(roll=0.0, pressed=(), keys=(), **kw):
    d = {"roll": roll, "pitch": 0.0, "cam_x": 0.0, "cam_y": 0.0, "lt": 0.0, "rt": 0.0,
         "pressed": set(pressed), "keys": set(keys)}
    d.update(kw)
    return d


class TestOutputLimiter:
    def run(self, lim, seq, max_hz=125, db=0.01):
        sent = []
        for t, o in seq:
            if lim.decide(o, t, max_hz, db):
                lim.mark_sent(o, t)
                sent.append((t, o["roll"]))
        return sent

    def test_noise_suppressed(self):
        import random
        lim = c.OutputLimiter()
        rnd = random.Random(1)
        seq = [(i * 0.004, _o(roll=0.5 + rnd.uniform(-0.004, 0.004))) for i in range(1000)]   # 4 с шума
        assert len(self.run(lim, seq)) == 1          # только первое состояние

    def test_rate_limited_and_final_value_arrives(self):
        lim = c.OutputLimiter()
        seq = [(i * 0.004, _o(roll=min(1.0, i * 0.004))) for i in range(300)]   # плавно 0 -> 1 за 1 с
        sent = self.run(lim, seq)
        gaps = [b[0] - a[0] for a, b in zip(sent, sent[1:])]
        assert min(gaps) >= 1 / 125 - 1e-6
        assert len(sent) <= 1.2 * 125 + 2
        assert sent[-1][1] == 1.0                    # упор доходит обязательно

    def test_return_to_zero_always(self):
        lim = c.OutputLimiter()
        self.run(lim, [(0.0, _o(roll=0.005))], db=0.01)
        assert self.run(lim, [(1.0, _o(roll=0.0))], db=0.01) == [(1.0, 0.0)]

    def test_buttons_and_keys_immediate(self):
        lim = c.OutputLimiter()
        self.run(lim, [(0.0, _o(roll=0.3))])
        assert self.run(lim, [(0.0005, _o(roll=0.3, pressed={"A"}))])        # сразу, без ожидания интервала
        assert self.run(lim, [(0.0010, _o(roll=0.3, pressed={"A"}, keys={"R"}))])
        assert self.run(lim, [(0.0015, _o(roll=0.3, pressed={"A"}))])

    def test_slow_drift_accumulates(self):
        lim = c.OutputLimiter()
        seq = [(i * 0.01, _o(roll=0.2 + i * 0.001)) for i in range(100)]    # 0.001 за шаг < фильтра
        sent = self.run(lim, seq)
        assert len(sent) >= 9 and sent[-1][1] >= 0.29 - 1e-9

    def test_config_output_sanitized(self):
        out = c.sanitize_config({"output": {"max_hz": 99999, "deadband": -1}})
        assert out["output"] == {"max_hz": 1000, "deadband": 0.0}
        assert c.sanitize_config({})["output"] == {"max_hz": 125, "deadband": 0.01}


def test_low_priority_option():
    assert c.sanitize_config({})["launcher"]["low_priority"] is False
    assert c.sanitize_config({"launcher": {"low_priority": True}})["launcher"]["low_priority"] is True


# ------------------------------------------------------------------ профили и свои действия
class TestCustom:
    def wt(self, actions):
        d = c.new_profile_config("War Thunder", "custom", c.default_config())
        d["custom_actions"] = actions
        return c.sanitize_config(d)

    def test_old_config_becomes_ac8_profile(self):
        with open(os.path.join(ROOT, "x52_config.json"), encoding="utf-8-sig") as f:
            new = c.sanitize_config(json.load(f))
        assert new["profile_name"] == "ACE COMBAT 8"
        assert new["game"] == {"builtin_actions": True, "virtual_pad": True, "launch_type": "steam",
                               "exe_path": ""}
        assert new["custom_actions"] == []

    def test_new_custom_profile(self):
        base = c.default_config()
        base["axes"]["roll"] = 4
        base["device_name"] = "X52 Pro"
        d = c.new_profile_config("War/Thunder", "custom", base)
        assert d["profile_name"] == "War_Thunder"
        assert d["game"]["virtual_pad"] is False and d["game"]["builtin_actions"] is False
        assert d["game"]["launch_type"] == "none" and d["launcher"]["steam_appid"] == ""
        assert d["axes"]["roll"] == 4 and d["device_name"] == "X52 Pro"
        assert c.sanitize_config(d) == d

    def test_sanitize_custom(self):
        d = self.wt([{"id": "x", "name": "A", "keys": ["G", "BAD", "G"], "mode": "zzz", "bindings": None},
                     {"id": "x", "name": "", "keys": [], "bindings": [{"type": "button", "index": 1}]},
                     "junk", {"id": "bad id!", "name": "C" * 100, "keys": ["MOUSE_LEFT"]}])
        cas = d["custom_actions"]
        assert [ca["id"] for ca in cas] == ["x", "c1", "c2"]
        assert cas[0]["keys"] == ["G"] and cas[0]["mode"] == "hold"
        assert cas[1]["name"] == "Действие" and cas[1]["bindings"][0]["index"] == 1
        assert len(cas[2]["name"]) == 60 and cas[2]["keys"] == ["MOUSE_LEFT"]
        assert c.sanitize_config(copy.deepcopy(d)) == d

    def test_hold_toggle_axis(self):
        d = self.wt([
            {"id": "c1", "name": "Огонь", "keys": ["SPACE"], "mode": "hold",
             "bindings": [{"type": "button", "index": 0}, {"type": "hat", "index": 0, "dir": "up"}]},
            {"id": "c2", "name": "Шасси", "keys": ["G"], "mode": "toggle",
             "bindings": [{"type": "button", "index": 3}, None]},
            {"id": "c3", "name": "Закрылки", "keys": ["F", "LSHIFT"], "mode": "hold",
             "bindings": [{"type": "axis", "index": 6, "dir": "+", "thr": 0.5}, None]}])
        m = c.Mapper()
        ax = [0.0] * 8
        ax[6] = -1.0

        def k(b0=0, b3=0, hat=(0, 0), a6=-1.0, t=[0.0]):
            t[0] += 0.01
            b = [0] * 8
            b[0], b[3] = b0, b3
            ax[6] = a6
            return m.step(d, ax, b, [hat], now=t[0])["keys"]
        assert k() == set()
        assert k(b0=1) == {"SPACE"}
        assert k(hat=(0, 1)) == {"SPACE"}          # дополнительная привязка
        assert k(b3=1) == {"G"}                    # переключатель включился
        assert k() == {"G"}                        # и держится
        assert k(b3=1) == set()                    # выключился
        assert k(b3=1) == set()                    # удержание не переключает повторно
        assert k(a6=0.7) == {"F", "LSHIFT"}
        assert k(a6=0.48) == {"F", "LSHIFT"}       # гистерезис
        assert k(a6=0.2) == set()

    def test_builtin_off_ignores_ac8_and_pad(self):
        d = self.wt([])
        btn = [0] * 32
        btn[0] = 1                                 # «Пушка» в AC8 профиле
        o = c.Mapper().step(d, [0, 0, 0, 0, 0, 0.9, 0, 0], btn, [(0, 1)], now=0.0)
        assert not o["pressed"] and not o["keys"] and not o["actions"]   # и рыскание не сработало

    def test_custom_and_builtin_together(self):
        d = c.default_config()
        d["custom_actions"] = [{"id": "c1", "name": "Фото", "keys": ["F12"], "mode": "hold",
                                "bindings": [{"type": "button", "index": 0}, None]}]
        d = c.sanitize_config(d)
        m = c.Mapper()
        btn = [0] * 32
        m.step(d, [0] * 8, btn, [], now=0.0)          # старт без нажатий
        btn[0] = 1
        o = m.step(d, [0] * 8, btn, [], now=0.01)
        assert "A" in o["pressed"] and o["keys"] == {"F12"}
        assert c.all_action_ids(d)[0] == "custom:c1" and "gun" in c.all_action_ids(d)
        assert c.action_label(d, "custom:c1") == "Фото"

    def test_custom_dcs_camera(self):
        d = c.new_profile_config("DCS", "dcs", c.default_config())
        d["custom_actions"] = [
            {"id": "c1", "name": "Влево", "mode": "camera", "cam": "left",
             "bindings": [{"type": "button", "index": 0}, None]},
            {"id": "c2", "name": "Вверх", "mode": "camera", "cam": "up",
             "bindings": [{"type": "button", "index": 1}, None]},
            {"id": "c3", "name": "Центр", "mode": "camera", "cam": "center",
             "bindings": [{"type": "button", "index": 2}, None]},
            {"id": "c4", "name": "Битое", "mode": "camera", "cam": "zzz", "bindings": [None, None]}]
        d = c.sanitize_config(d)
        assert d["custom_actions"][3]["cam"] == "left"
        m = c.Mapper()
        btn = [0] * 32
        m.step(d, [0] * 8, btn, [], now=0.0)
        btn[0] = btn[1] = 1
        o = m.step(d, [0] * 8, btn, [], now=0.01)
        assert o["cam_x"] == -1.0 and o["cam_y"] == 1.0 and not o["keys"]
        btn[0] = btn[1] = 0
        btn[2] = 1
        o = m.step(d, [0] * 8, btn, [], now=0.02)
        assert o["cam_x"] == 0.0 and o["cam_y"] == 0.0 and "CENTER" in o["internal"]
        assert c.custom_out_text(d["custom_actions"][0]).startswith("Обзор DCS: Камера в кабине, горизонталь")

    def test_new_custom_id(self):
        d = self.wt([{"id": "c1", "name": "a", "keys": ["A"]}, {"id": "c3", "name": "b", "keys": ["B"]}])
        assert c.new_custom_id(d) == "c2"


# ------------------------------------------------------------------ слои, короткое/долгое, последовательности
def _prof(actions, layers=False, long_ms=500):
    d = c.new_profile_config("DCS World", "custom", c.default_config())
    d["custom_actions"] = actions
    d["layers"]["enabled"] = layers
    d["long_press_ms"] = long_ms
    return c.sanitize_config(d)


def _act(cid, keys, b, **kw):
    a = {"id": cid, "name": cid, "keys": keys, "bindings": [{"type": "button", "index": b}, None]}
    a.update(kw)
    return a


class Sim:
    """Прогон маппера по времени: шаг 5 мс."""
    def __init__(self, cfg):
        self.cfg, self.m, self.t = cfg, c.Mapper(), 0.0
        self.btn = [0] * 32
        self.m.step(cfg, [0.0] * 8, self.btn, [], now=0.0)   # старт: ничего не зажато

    def run(self, ms, **press):
        for k, v in press.items():
            self.btn[int(k[1:])] = v
        seen = []
        for _ in range(int(ms / 5)):
            self.t += 0.005
            seen.append(frozenset(self.m.step(self.cfg, [0.0] * 8, self.btn, [], now=self.t)["keys"]))
        return seen


class TestLayers:
    def cfg(self):
        return _prof([_act("a", ["A"], 0, layer=1), _act("b", ["B"], 0, layer=2),
                      _act("c", ["C"], 0, layer=0), _act("d", ["D"], 1, layer=3)], layers=True)

    def test_layer_selects_action(self):
        s = Sim(self.cfg())
        assert s.run(10, b23=1, b0=1)[-1] == {"A", "C"}      # режим 1 (кнопка 24)
        s.run(10, b0=0)
        s.btn[23] = 0
        assert s.run(10, b24=1, b0=1)[-1] == {"B", "C"}      # режим 2
        assert s.run(10, b1=1)[-1] == {"B", "C"}             # «D» только в слое 3
        s.btn[24] = 0
        assert s.run(10, b25=1)[-1] == {"C", "D"}            # повернули колесо при зажатой кнопке
        assert s.m.layer == 3

    def test_layers_off_all_fire(self):
        d = self.cfg()
        d["layers"]["enabled"] = False
        assert Sim(d).run(10, b0=1)[-1] == {"A", "B", "C"}

    def test_no_mode_button_means_layer1(self):
        s = Sim(self.cfg())
        assert s.run(10, b0=1)[-1] == {"A", "C"} and s.m.layer == 1

    def test_conflicts_respect_layers_and_triggers(self):
        d = _prof([_act("a", ["A"], 0, layer=1), _act("b", ["B"], 0, layer=2),
                   _act("s", ["S"], 5, trigger="short"), _act("l", ["L"], 5, trigger="long"),
                   _act("p", ["P"], 6), _act("q", ["Q"], 6, trigger="long")], layers=True)
        bad = c.conflicting_actions(d)
        assert bad == {"custom:p", "custom:q"}               # обычное+долгое на одной кнопке
        d["layers"]["enabled"] = False
        assert {"custom:a", "custom:b"} <= c.conflicting_actions(d)


class TestShortLong:
    def cfg(self, **kw):
        return _prof([_act("s", ["S"], 0, trigger="short", **kw), _act("l", ["L"], 0, trigger="long")])

    def test_short_tap_on_release(self):
        s = Sim(self.cfg())
        assert all(k == frozenset() for k in s.run(200, b0=1))   # пока держим — ничего
        seen = s.run(150, b0=0)
        on = [k for k in seen if "S" in k]
        assert seen[0] == {"S"} and 55 <= len(on) * 5 <= 70       # тап ~60 мс сразу после отпускания
        assert not any("L" in k for k in seen)

    def test_long_holds_until_release(self):
        s = Sim(self.cfg())
        seen = s.run(800, b0=1)
        first = next(i for i, k in enumerate(seen) if "L" in k)
        assert 495 <= (first + 1) * 5 <= 505 and seen[-1] == {"L"}
        after = s.run(100, b0=0)
        assert all(k == frozenset() for k in after)                # короткое не сработало

    def test_long_toggle_and_sequence(self):
        d = _prof([_act("t", ["T"], 0, trigger="long", mode="toggle"),
                   _act("q", [], 1, trigger="short", mode="sequence",
                        steps=[{"keys": ["X"], "delay_ms": 0, "duration_ms": 50},
                               {"keys": ["Y", "LSHIFT"], "delay_ms": 100, "duration_ms": 50}])])
        s = Sim(d)
        s.run(600, b0=1)
        assert s.run(50, b0=0)[-1] == {"T"}                         # долгое включило переключатель
        s.run(600, b0=1)
        assert s.run(50, b0=0)[-1] == frozenset()                   # и выключило

    def test_threshold_configurable(self):
        d = _prof([_act("l", ["L"], 0, trigger="long")], long_ms=200)
        seen = Sim(d).run(300, b0=1)
        assert 195 <= (next(i for i, k in enumerate(seen) if k) + 1) * 5 <= 205


class TestSequence:
    STEPS = [{"keys": ["LCTRL", "HOME"], "delay_ms": 0, "duration_ms": 100},
             {"keys": ["RSHIFT", "HOME"], "delay_ms": 500, "duration_ms": 100},
             {"keys": ["RCTRL", "HOME"], "delay_ms": 600, "duration_ms": 50}]

    def test_timeline(self):
        d = _prof([_act("q", [], 0, mode="sequence", steps=self.STEPS)])
        s = Sim(d)
        seen = s.run(5, b0=1) + s.run(800, b0=0)        # нажали и отпустили — идёт до конца
        assert seen[0] == {"LCTRL", "HOME"}
        at = lambda ms: seen[ms // 5 - 1]
        assert at(50) == {"LCTRL", "HOME"} and at(300) == frozenset()
        assert at(550) == {"RSHIFT", "HOME"} and at(625) == {"RCTRL", "HOME"}
        assert at(700) == frozenset() and seen[-1] == frozenset()

    def test_no_restart_while_running_then_restart(self):
        d = _prof([_act("q", [], 0, mode="sequence", steps=self.STEPS)])
        s = Sim(d)
        s.run(5, b0=1)
        s.run(300, b0=0)
        seen = s.run(5, b0=1)                            # повторное нажатие на 305 мс — игнор
        assert seen[-1] == frozenset()
        s.run(500, b0=0)                                 # закончилась
        assert s.run(5, b0=1)[-1] == {"LCTRL", "HOME"}   # новое нажатие — заново

    def test_sanitize_steps(self):
        d = _prof([_act("q", [], 0, mode="sequence", steps=[
            {"keys": ["B"], "delay_ms": 900, "duration_ms": 5},
            {"keys": ["BAD"], "delay_ms": 0},
            {"keys": ["A"], "delay_ms": -5, "duration_ms": 99999}, "junk"])])
        st = d["custom_actions"][0]["steps"]
        assert st == [{"keys": ["A"], "delay_ms": 0, "duration_ms": 10000},
                      {"keys": ["B"], "delay_ms": 900, "duration_ms": 10}]
        assert c.sequence_length_ms(st) == 10000
        assert c.custom_out_text(d["custom_actions"][0]) == "Последовательность: 2 шага, 10.0 с"


class TestAutoProfile:
    RULES = {"DCS World": {"processes": ["DCS.exe"], "aircraft": []},
             "DCS F-16": {"processes": [], "aircraft": ["F-16C_50"]},
             "War Thunder": {"processes": ["aces", "WarThunder.exe"], "aircraft": []}}

    def test_choose(self):
        ch = lambda **k: c.choose_profile(self.RULES, **k)
        assert ch(process=r"C:\\Games\\DCS\\bin\\DCS.exe") == "DCS World"
        assert ch(process="dcs.EXE", aircraft="F-16C_50") == "DCS F-16"
        assert ch(process="DCS.exe", aircraft="A-10C_2") == "DCS World"
        assert ch(process="aces.exe") == "War Thunder"
        assert ch(process="chrome.exe") is None and ch() is None

    def test_sanitize_auto_layers(self):
        d = c.sanitize_config({"auto": {"processes": "DCS.exe, dcs.exe;\nWarThunder.exe", "aircraft": [1, "F-16C_50"]},
                               "layers": {"enabled": True, "buttons": [{"type": "button", "index": 30}, "x"]},
                               "long_press_ms": 10})
        assert d["auto"] == {"processes": ["DCS.exe", "WarThunder.exe"], "aircraft": ["1", "F-16C_50"]}
        assert d["layers"] == {"enabled": True, "buttons": [{"type": "button", "index": 30}, None, None]}
        assert d["long_press_ms"] == 150
        old = c.sanitize_config({})
        assert old["layers"] == c.default_layers() and old["auto"] == {"processes": [], "aircraft": []}


# ------------------------------------------------------------------ отпускание, автоповтор, смена профиля
class TestReleaseRepeatProfile:
    def test_press_and_release_on_same_button(self):
        d = _prof([_act("canopy", ["LCTRL", "C"], 0),
                   _act("engine", ["RSHIFT", "HOME"], 0, trigger="release")])
        assert c.conflicting_actions(d) == set()                 # нажатие + отпускание — не конфликт
        s = Sim(d)
        assert s.run(200, b0=1)[-1] == {"LCTRL", "C"}             # держим — закрытие фонаря
        seen = s.run(150, b0=0)
        assert seen[0] == {"RSHIFT", "HOME"}                     # отпустили — тап запуска двигателя
        on = sum(1 for k in seen if k == {"RSHIFT", "HOME"})
        assert 55 <= on * 5 <= 70 and seen[-1] == frozenset()

    def test_release_after_long_hold_still_fires(self):
        d = _prof([_act("r", ["R"], 0, trigger="release")])
        s = Sim(d)
        s.run(3000, b0=1)
        assert s.run(10, b0=0)[0] == {"R"}

    def test_clash_table(self):
        cl = c._triggers_clash
        assert cl("press", "press") and cl("press", "short") and cl("release", "release")
        assert not cl("press", "release") and not cl("short", "long") and not cl("long", "release")
        assert not cl("short", "release")            # как в RS Mapper: SP (при LP) + RL на одной кнопке

    def test_repeat(self):
        d = _prof([_act("fire", ["SPACE"], 0, mode="repeat", repeat_ms=100)])
        s = Sim(d)
        seen = s.run(1000, b0=1)
        presses = sum(1 for a, b in zip([frozenset()] + seen, seen) if "SPACE" in b and "SPACE" not in a)
        assert presses == 10                                       # 1 с / 100 мс
        assert all(k == frozenset() for k in s.run(100, b0=0))
        assert c.custom_out_text(d["custom_actions"][0]) == "Клавиатура: Пробел · повтор 100 мс"

    def test_profile_events(self):
        d = _prof([_act("p", [], 0, mode="profile", profile={"kind": "cycle", "names": ["Взлёт", "Полёт", "Взлёт"]}),
                   _act("q", [], 1, mode="profile", trigger="release", profile={"kind": "name", "names": ["Посадка"]})])
        assert d["custom_actions"][0]["profile"] == {"kind": "cycle", "names": ["Взлёт", "Полёт"]}
        s = Sim(d)
        s.run(50, b0=1)
        s.run(50, b0=0)
        assert s.m.profile_events == [{"kind": "cycle", "names": ["Взлёт", "Полёт"]}]
        s.m.profile_events.clear()
        s.run(50, b1=1)
        assert s.m.profile_events == []                            # по отпусканию
        s.run(10, b1=0)
        assert s.m.profile_events == [{"kind": "name", "names": ["Посадка"]}]
        assert c.custom_out_text(d["custom_actions"][0]) == "Профили по кругу: Взлёт → Полёт"
        assert c.custom_out_text(d["custom_actions"][1]) == "Профиль: «Посадка» · отпускание"

    def test_held_button_after_profile_switch_does_not_retrigger(self):
        d = _prof([_act("p", [], 0, mode="profile", profile={"kind": "next", "names": []}),
                   _act("s", ["S"], 0, trigger="short"), _act("l", ["L"], 0, trigger="long"),
                   _act("back", [], 0, mode="profile", trigger="release", profile={"kind": "prev", "names": []})])
        s = Sim(d)
        s.run(20, b0=1)
        assert len(s.m.profile_events) == 1
        s.m.profile_events.clear()
        s.m.reset()                                                # как при смене профиля
        seen = s.run(1000, b0=1)                                   # кнопку всё ещё держат
        assert s.m.profile_events == [] and all(k == frozenset() for k in seen)  # ни нажатия, ни долгого
        s.run(10, b0=0)
        assert s.m.profile_events == [{"kind": "prev", "names": []}]  # отпускание — работает (pinky)


# ------------------------------------------------------------------ выключение аналоговых осей галочкой
class TestAxesEnabled:
    def test_default_and_sanitize(self):
        assert all(c.default_config()["axes_enabled"].values())
        d = c.sanitize_config({"axes_enabled": {"roll": False, "bogus": False}})
        assert d["axes_enabled"]["roll"] is False and "bogus" not in d["axes_enabled"]
        assert c.sanitize_config({})["axes_enabled"]["throttle"] is True       # старые конфиги

    def test_disabled_axis_no_analog_but_key_binding_works(self):
        d = c.default_config()
        d["axes_enabled"]["throttle"] = False
        d["axes_enabled"]["yaw"] = False
        d["axes_enabled"]["roll"] = False
        d["custom_actions"] = [{"id": "c1", "name": "Газ на клавишу", "keys": ["SPACE"],
                                "bindings": [{"type": "axis", "index": 2, "dir": "-", "thr": -0.5}, None]}]
        d = c.sanitize_config(d)
        m = c.Mapper()
        m.step(d, [0.0] * 8, [0] * 32, [], now=0.0)
        o = m.step(d, [0.9, 0.0, -1.0, 0, 0, 0.9, 0, 0], [0] * 32, [], now=0.01)
        assert o["roll"] == 0.0                      # крен выключен
        assert o["lt"] == 0.0 and o["rt"] == 0.0     # РУД не уходит в триггеры
        assert "yaw_right" not in o["actions"]       # рыскание не жмёт RB
        assert o["keys"] == {"SPACE"}                # а как кнопка — работает
        assert c.analog_axis(d, "throttle") is None and d["axes"]["throttle"] == 2   # номер сохранён
        d["axes_enabled"]["roll"] = True
        assert c.Mapper().step(d, [0.9] + [0.0] * 7, [0] * 32, [], now=0.0)["roll"] > 0.5


# ------------------------------------------------------------------ RS-стиль: хатка 8 направлений, тап, библиотека
class TestRsCore:
    def test_hat8_exact(self):
        ba = lambda d, xy: c.binding_active({"type": "hat", "index": 0, "dir": d}, [], [xy])
        for d, xy in c.HAT8.items():
            for d2, xy2 in c.HAT8.items():
                assert ba(d, xy2) == (d == d2)
            assert not ba(d, (0, 0))
        assert ba("up", (1, 1)) and ba("right", (1, 1))          # старые направления — как раньше
        v = c.valid_binding({"type": "hat", "index": 1, "dir": "sw"})
        assert v == {"type": "hat", "index": 1, "dir": "sw"} and c.binding_text(v) == "Хатка 2 ↙"

    def test_tap_mode(self):
        d = _prof([_act("t", ["LCTRL", "C"], 0, mode="tap"), _act("l", ["L"], 0, mode="tap", trigger="long")])
        s = Sim(d)
        seen = s.run(1000, b0=1)
        on_c = sum(1 for k in seen if "C" in k)
        on_l = sum(1 for k in seen if "L" in k)
        assert 55 <= on_c * 5 <= 70 and 55 <= on_l * 5 <= 70       # по одному короткому нажатию
        assert seen[0] == {"LCTRL", "C"} and seen[-1] == frozenset()

    def test_sequence_library(self):
        d = _prof([_act("q", [], 0, mode="sequence", seq="Запуск",
                        steps=[{"keys": ["Z"], "delay_ms": 0, "duration_ms": 50}])])
        d["sequences"] = [{"name": "Запуск", "steps": [{"keys": ["A"], "delay_ms": 0, "duration_ms": 50,
                                                          "name": "ВСУ"},
                                                         {"keys": ["B"], "delay_ms": 100, "duration_ms": 50}]}]
        d = c.sanitize_config(d)
        s = Sim(d)
        seen = s.run(5, b0=1) + s.run(300, b0=0)
        assert seen[0] == {"A"} and seen[100 // 5] == {"B"} and not any("Z" in k for k in seen)
        assert c.custom_out_text(d["custom_actions"][0]) == "Последовательность «Запуск»"
        d["sequences"] = []                                          # нет в библиотеке — свои шаги
        s = Sim(d)
        assert s.run(5, b0=1)[0] == {"Z"}


# ------------------------------------------------------------------ клавиши: не меньше, чем в RS Mapper
RS_MAPPER_KEYS = (list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") +
                  ["`", "-", "=", "]", "[", ";", "'", "Left \\", "Right \\", ",", ".", "/"] +
                  ["NUMPAD %d" % i for i in range(10)] +
                  ["NUMPAD /", "NUMPAD *", "NUMPAD -", "NUMPAD +", "NUMPAD ENTER", "NUMPAD ."] +
                  ["F%d" % i for i in range(1, 13)] +
                  ["ESC", "PRINT SCREEN", "SCROLL LOCK", "BACKSPACE", "NUM LOCK", "TAB", "ENTER", "CAPS LOCK",
                   "LEFT SHIFT", "RIGHT SHIFT", "LEFT CONTROL", "RIGHT CONTROL", "SPACEBAR", "LEFT ALT",
                   "RIGHT ALT", "INSERT", "HOME", "PAGE UP", "DELETE", "END", "PAGE DOWN", "UP", "DOWN", "LEFT",
                   "RIGHT", "LEFT WINDOWS", "RIGHT WINDOWS", "PAUSE"])
RS_TO_OURS = {"`": "GRAVE", "-": "MINUS", "=": "EQUALS", "]": "RBRACKET", "[": "LBRACKET", ";": "SEMICOLON",
              "'": "APOSTROPHE", "Left \\": "OEM102", "Right \\": "BACKSLASH", ",": "COMMA", ".": "PERIOD",
              "/": "SLASH", "NUMPAD /": "NUM_DIV", "NUMPAD *": "NUM_MUL", "NUMPAD -": "NUM_SUB",
              "NUMPAD +": "NUM_ADD", "NUMPAD ENTER": "NUM_ENTER", "NUMPAD .": "NUM_DEC", "PRINT SCREEN": "PRINTSCREEN",
              "SCROLL LOCK": "SCROLLLOCK", "NUM LOCK": "NUMLOCK", "CAPS LOCK": "CAPSLOCK", "LEFT SHIFT": "LSHIFT",
              "RIGHT SHIFT": "RSHIFT", "LEFT CONTROL": "LCTRL", "RIGHT CONTROL": "RCTRL", "SPACEBAR": "SPACE",
              "LEFT ALT": "LALT", "RIGHT ALT": "RALT", "PAGE UP": "PGUP", "PAGE DOWN": "PGDN",
              "LEFT WINDOWS": "LWIN", "RIGHT WINDOWS": "RWIN"}


def test_all_rs_mapper_keys_present():
    assert len(RS_MAPPER_KEYS) == 104
    for k in RS_MAPPER_KEYS:
        ours = RS_TO_OURS.get(k) or ("NUM" + k[-1] if k.startswith("NUMPAD ") else k)
        assert ours in c.KEYS, k
    assert len(c.KEYS) >= 104 and sorted(c.ALL_KEYS) == sorted(list(c.KEYS) + list(c.MOUSE_KEYS))


def test_symbol_key_labels_and_capture():
    assert c.key_text("PERIOD") == ". (Ю)" and c.key_text("COMMA") == ", (Б)"
    assert c.key_text("OEM102").startswith("\\") and c.key_text("PAUSE") == "Pause"
    assert c.ALL_KEYS.index("A") == 0 and c.ALL_KEYS.index("COMMA") < c.ALL_KEYS.index("NUM0")
    assert c.key_from_tk_event("period", 0xBE, is_win=True) == "PERIOD"
    assert c.key_from_tk_event("comma", 0xBC, is_win=True) == "COMMA"
    assert c.key_from_tk_event("Pause", 0x13, is_win=True) == "PAUSE"
    assert c.key_from_tk_event("Win_L", 0x5B, is_win=True) == "LWIN"
    assert c.key_from_tk_event("F13", 0x7C, is_win=True) == "F13"
    assert c.key_from_tk_event("Num_Lock", 0, is_win=False) == "NUMLOCK"


# ------------------------------------------------------------------ 4.2.4: порядок модификаторов, память колеса
class TestModifierOrder:
    def log(self, *steps):
        s = c.KeySender(backend=c._NullInput())
        for st in steps:
            s.apply(set(st))
        return s.backend.log

    def test_ctrl_c_press_and_release_order(self):
        assert self.log({"LCTRL", "C"}, set()) == [("LCTRL", True), ("C", True), ("C", False), ("LCTRL", False)]

    def test_three_key_combo(self):
        assert self.log({"HOME", "RSHIFT", "RCTRL"}, set()) == [
            ("RCTRL", True), ("RSHIFT", True), ("HOME", True), ("HOME", False), ("RSHIFT", False), ("RCTRL", False)]

    def test_switch_ctrl_c_to_ctrl_v_keeps_ctrl(self):
        assert self.log({"LCTRL", "C"}, {"LCTRL", "V"}) == [("LCTRL", True), ("C", True), ("C", False), ("V", True)]

    def test_alt_win_shift_and_plain_keys(self):
        lg = self.log({"LALT", "LSHIFT", "LWIN", "F", "MOUSE_LEFT"} & set(c.ALL_KEYS) | {"F"}, set())
        downs = [k for k, d in lg if d]
        ups = [k for k, d in lg if not d]
        assert downs.index("F") > max(downs.index(m) for m in ("LSHIFT", "LALT") if m in downs)
        assert ups.index("F") < min(ups.index(m) for m in ("LSHIFT", "LALT") if m in ups)


class TestWheelMemory:
    def cfg(self):
        d = c.new_profile_config("DCS", "custom", c.default_config())
        d["layers"]["enabled"] = True
        return c.sanitize_config(d)

    def test_last_position_until_first_live_signal(self):
        d = self.cfg()
        m = c.Mapper()
        m.wheel_last = 2                                     # с прошлого запуска
        btn = [0] * 32
        m.step(d, [0.0] * 8, btn, [], now=0.0)
        assert m.layer == 2 and m.layer_known                # Windows ещё не сообщила кнопку — помним
        btn[25] = 1
        m.step(d, [0.0] * 8, btn, [], now=0.01)
        assert m.layer == 3 and m.wheel_last == 3
        m.reset()                                            # смена профиля — память остаётся
        btn[25] = 0
        m.step(d, [0.0] * 8, btn, [], now=0.02)
        assert not m.layer_known                             # колесо уже видели: «нет кнопки» — честно
        m.wheel_seen = False                                 # джойстик открыли заново
        m.step(d, [0.0] * 8, btn, [], now=0.03)
        assert m.layer == 3 and m.layer_known


def test_500_game_templates():
    for key, (game, procs) in c.GAME_TEMPLATES.items():
        d = c.new_profile_config(game, key)
        assert d["game"]["virtual_pad"] is False and d["game"]["builtin_actions"] is False
        assert d["auto"]["processes"] == procs
        assert c.choose_profile({game: d["auto"]}, "C:\\Games\\X\\bin\\" + procs[0].upper()) == game
    assert c.new_profile_config("Другая", "custom")["auto"]["processes"] == []
