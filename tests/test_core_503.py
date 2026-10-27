# -*- coding: utf-8 -*-
"""Тесты мини-стика X52 (чистая математика интегратора + override в Mapper)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import x52_core as c  # noqa: E402
import x52_ministick as mst  # noqa: E402


def test_integrator_zero_on_no_feed():
    g = mst.MiniStickIntegrator(sens=1.0, timeout_ms=50)
    assert g.read(now=0.0) == (0.0, 0.0)


def test_integrator_signs_match_deltas():
    g = mst.MiniStickIntegrator(sens=1.0, timeout_ms=100, scale=10.0)
    g.feed(5, -5, now=0.0)
    x, y = g.read(now=0.001)
    assert x > 0.0 and y < 0.0
    assert abs(x) <= 1.0 and abs(y) <= 1.0


def test_integrator_decays_after_timeout():
    g = mst.MiniStickIntegrator(sens=1.0, timeout_ms=50, scale=10.0)
    g.feed(5, 5, now=0.0)
    assert g.read(now=1.0) == (0.0, 0.0)   # окно 50 мс - событие ушло


def test_integrator_saturates():
    g = mst.MiniStickIntegrator(sens=5.0, timeout_ms=100, scale=1.0)
    g.feed(1000, 0, now=0.0)
    x, _ = g.read(now=0.001)
    assert x == 1.0


def test_integrator_sens_clamped():
    g = mst.MiniStickIntegrator(sens=99.0, timeout_ms=50)
    assert g.sens <= 5.0
    g.set_sens(0.0)
    assert g.sens >= 0.1


def test_config_has_ministick_defaults():
    d = c.default_config()
    assert d["ministick"]["enabled"] is False
    assert 0.1 <= d["ministick"]["sens"] <= 5.0
    assert d["ministick"]["timeout_ms"] >= 16


def test_sanitize_fixes_garbage_ministick():
    d = c.sanitize_config({"ministick": {"enabled": "nope", "sens": 999, "timeout_ms": -5}})
    assert d["ministick"]["enabled"] is True       # bool("nope") -> True
    assert d["ministick"]["sens"] == 5.0
    assert d["ministick"]["timeout_ms"] == 16


def _run_step(mapper, cfg, axes=None, t=0.0):
    axes = axes if axes is not None else [0.0] * 8
    return mapper.step(cfg, axes, [], [], now=t)


def _ms_cfg(**overrides):
    """Конфиг с настройками мини-стика по умолчанию, без мёртвой зоны —
    чтобы assertions не зависели от rescaled_deadzone."""
    cfg = c.default_config()
    cfg["ministick"] = {"enabled": True, "sens": 1.0, "timeout_ms": 80,
                        "deadzone": 0.0, "invert_x": False, "invert_y": False}
    cfg["ministick"].update(overrides)
    cfg["axes"]["cam_x"] = None
    cfg["axes"]["cam_y"] = None
    return cfg


def test_mapper_uses_ministick_when_cam_unassigned():
    cfg = _ms_cfg()
    m = c.Mapper()
    m.ministick = (0.7, -0.4)
    out = _run_step(m, cfg)
    assert abs(out["cam_x"] - 0.7) < 1e-6
    assert abs(out["cam_y"] - (-0.4)) < 1e-6


def test_mapper_ignores_ministick_when_disabled():
    cfg = _ms_cfg(enabled=False)
    m = c.Mapper()
    m.ministick = (0.7, -0.4)
    out = _run_step(m, cfg)
    assert out["cam_x"] == 0.0
    assert out["cam_y"] == 0.0


def test_mapper_prefers_real_axis_over_ministick():
    cfg = _ms_cfg()
    cfg["axes"]["cam_x"] = 4         # реальная ось назначена
    cfg["axes"]["cam_y"] = None      # мини-стик только для Y
    m = c.Mapper()
    m.ministick = (0.9, 0.9)
    axes = [0.0] * 8
    axes[4] = 0.5
    out = _run_step(m, cfg, axes)
    assert out["cam_x"] != 0.9       # X берётся с оси 4, не с мини-стика
    assert abs(out["cam_y"] - 0.9) < 1e-6


def test_mapper_clamps_ministick():
    cfg = _ms_cfg()
    m = c.Mapper()
    m.ministick = (2.5, -3.0)   # за пределами [-1, +1]
    out = _run_step(m, cfg)
    assert out["cam_x"] == 1.0
    assert out["cam_y"] == -1.0


def test_mapper_applies_ministick_invert():
    cfg = _ms_cfg(invert_x=True, invert_y=True)
    m = c.Mapper()
    m.ministick = (0.5, -0.3)
    out = _run_step(m, cfg)
    assert abs(out["cam_x"] - (-0.5)) < 1e-6
    assert abs(out["cam_y"] - 0.3) < 1e-6


def test_mapper_applies_ministick_deadzone():
    cfg = _ms_cfg(deadzone=0.2)
    m = c.Mapper()
    m.ministick = (0.1, -0.1)      # внутри мёртвой зоны
    out = _run_step(m, cfg)
    assert out["cam_x"] == 0.0
    assert out["cam_y"] == 0.0


def test_sanitize_normalizes_ministick_invert_and_dz():
    d = c.sanitize_config({"ministick": {"deadzone": "nope", "invert_x": 1,
                                         "invert_y": None}})
    assert d["ministick"]["invert_x"] is True       # bool(1) == True
    assert d["ministick"]["invert_y"] is False      # bool(None) == False
    assert d["ministick"]["deadzone"] == 0.08       # вернулся дефолт


def test_ministick_direction_bindings_emit_keys():
    cfg = _ms_cfg()
    cfg["ministick"]["bindings"] = {"up": ["W"], "down": ["S"],
                                     "left": ["A"], "right": ["D"]}
    cfg["ministick"]["bind_threshold"] = 0.5
    m = c.Mapper()
    # right (cam_x > thr)
    m.ministick = (0.8, 0.0)
    out = _run_step(m, cfg)
    assert "D" in out["keys"] and "A" not in out["keys"]
    # left
    m.ministick = (-0.8, 0.0)
    out = _run_step(m, cfg, t=0.01)
    assert "A" in out["keys"] and "D" not in out["keys"]
    # up
    m.ministick = (0.0, 0.8)
    out = _run_step(m, cfg, t=0.02)
    assert "W" in out["keys"] and "S" not in out["keys"]
    # center -> no keys
    m.ministick = (0.0, 0.0)
    out = _run_step(m, cfg, t=0.03)
    assert not (set(["W", "S", "A", "D"]) & set(out["keys"]))


def test_ministick_direction_respects_invert():
    cfg = _ms_cfg(invert_x=True)
    cfg["ministick"]["bindings"] = {"up": [], "down": [], "left": ["A"], "right": ["D"]}
    m = c.Mapper()
    m.ministick = (0.8, 0.0)   # физически вправо, с инверсией — влево
    out = _run_step(m, cfg)
    assert "A" in out["keys"] and "D" not in out["keys"]


def test_ministick_direction_threshold():
    cfg = _ms_cfg()
    cfg["ministick"]["bindings"] = {"up": [], "down": [], "left": [], "right": ["D"]}
    cfg["ministick"]["bind_threshold"] = 0.7
    m = c.Mapper()
    m.ministick = (0.5, 0.0)   # ниже порога
    out = _run_step(m, cfg)
    assert "D" not in out["keys"]
    m.ministick = (0.8, 0.0)   # выше
    out = _run_step(m, cfg, t=0.01)
    assert "D" in out["keys"]


def test_make_reader_returns_object_with_api():
    r = mst.make_reader()
    # должен существовать и отвечать на базовое API вне зависимости от ОС
    assert hasattr(r, "read") and hasattr(r, "start") and hasattr(r, "stop")
    assert hasattr(r, "ok")
    assert r.read() == (0.0, 0.0) or isinstance(r.read(), tuple)


def test_parse_ministick_ignores_main_stick_bytes():
    rep = [0] * 16
    rep[14] = 0x8F                                    # мини-стик вправо, по вертикали центр
    for b2, b3 in ((0x04, 0x20), (0x07, 0x1F), (0xFF, 0x00)):   # ручка в центре и отклонена
        rep[2], rep[3] = b2, b3
        x, y = mst.parse_ministick(rep, 15)
        assert x == 1.0 and y == 0.0
    rep[14] = 0x88                                    # отпущен -> центр
    assert mst.parse_ministick(rep, 15) == (0.0, 0.0)
    rep[14] = 0x08                                    # вертикаль вверх
    assert mst.parse_ministick(rep, 15) == (0.0, 1.0)
    assert mst.parse_ministick(rep, 14) is None


def test_simultaneous_taps_go_one_by_one():
    """«Короткое» и «отпускание» на одной кнопке срабатывают в один момент — клавиши
    двух действий не должны смешиваться (LCtrl+C и RShift+L, а не LCtrl+RShift+C+L)."""
    b = {"type": "button", "index": 0}
    d = c.new_profile_config("DCS", "dcs", c.default_config())
    d["custom_actions"] = [
        {"id": "c1", "name": "Фонарь", "keys": ["LCTRL", "C"], "mode": "tap", "trigger": "short", "bindings": [b, None]},
        {"id": "c2", "name": "Закрылки", "keys": ["F"], "mode": "tap", "trigger": "long", "bindings": [b, None]},
        {"id": "c3", "name": "Питание", "keys": ["RSHIFT", "L"], "mode": "tap", "trigger": "release",
         "bindings": [b, None]}]
    d = c.sanitize_config(d)
    m = c.Mapper()
    btn = [0] * 32
    groups = []
    for i in range(80):
        btn[0] = 1 if 5 <= i < 25 else 0
        ks = sorted(m.step(d, [0] * 8, btn, [], now=i * 0.01)["keys"])
        if ks and (not groups or groups[-1] != ks):
            groups.append(ks)
    assert groups == [["C", "LCTRL"], ["L", "RSHIFT"]]


def _zoom_cfg(**z):
    cfg = c.default_config()
    cfg["zoom"].update({"enabled": True, "axis": 6, "filter_thr": 0.02}, **z)
    return cfg


def _zoom_run(m, cfg, seq, t0=0.0, dt=0.005):
    out = None
    for i, v in enumerate(seq):
        axes = [0.0] * 8
        axes[6] = v
        out = m.step(cfg, axes, [0] * 39, [(0, 0)], now=t0 + i * dt)
    return out


def test_zoom_filter_holds_noise_and_follows_move():
    cfg = _zoom_cfg()
    m = c.Mapper()
    out = _zoom_run(m, cfg, [0.70, 0.71, 0.69, 0.705, 0.695] * 40)   # шум ±1 % у края
    assert out["zoom"] == 0.70 and out["roll"] == 0.70
    out = _zoom_run(m, cfg, [0.40] * 200, t0=2.0)                    # реальный сдвиг — доходит
    assert abs(out["zoom"] - 0.40) < 1e-6


def test_zoom_off_leaves_roll_alone_and_invert():
    cfg = _zoom_cfg(enabled=False)
    out = _zoom_run(c.Mapper(), cfg, [0.8] * 5)
    assert out["zoom"] is None and out["roll"] == 0.0
    cfg = _zoom_cfg(invert=True, filter_thr=0.0)
    out = _zoom_run(c.Mapper(), cfg, [0.5] * 5)
    assert abs(out["roll"] + 0.5) < 1e-6


def test_sanitize_zoom():
    d = c.sanitize_config({"zoom": {"enabled": 1, "axis": True, "filter_thr": 5}})
    assert d["zoom"] == {"enabled": True, "axis": None, "invert": False, "filter_thr": 0.10}
    assert c.sanitize_config({})["zoom"]["enabled"] is False


def test_ministick_curve():
    cfg = _ms_cfg(deadzone=0.0, curve=2.0)
    m = c.Mapper()
    m.ministick = (0.5, -0.5)
    out = m.step(cfg, [0.0] * 8, [0] * 39, [(0, 0)], now=0.0)
    assert abs(out["cam_x"] - 0.25) < 1e-6 and abs(out["cam_y"] + 0.25) < 1e-6
    m.ministick = (1.0, 0.0)                              # полное отклонение — прежняя скорость, без задержки
    out = m.step(cfg, [0.0] * 8, [0] * 39, [(0, 0)], now=0.005)
    assert out["cam_x"] == 1.0 and out["cam_y"] == 0.0


def test_sanitize_ministick_curve():
    d = c.sanitize_config({"ministick": {"smooth_ms": 9999, "curve": 0.2}})
    assert d["ministick"]["curve"] == 1.0 and "smooth_ms" not in d["ministick"]
    assert c.sanitize_config({"ministick": {"curve": 9}})["ministick"]["curve"] == 3.0


def test_ministick_axis_lock():
    cfg = _ms_cfg(deadzone=0.0, axis_lock=True)
    m = c.Mapper()
    m.ministick = (1.0, 0.29)                 # вбок с побочным перекосом вниз-вверх — вертикаль гасится
    out = m.step(cfg, [0.0] * 8, [0] * 39, [(0, 0)], now=0.0)
    assert out["cam_x"] == 1.0 and out["cam_y"] == 0.0
    m.ministick = (-0.29, -0.86)              # вверх/вниз с перекосом вбок — горизонталь гасится
    out = m.step(cfg, [0.0] * 8, [0] * 39, [(0, 0)], now=0.005)
    assert out["cam_x"] == 0.0 and abs(out["cam_y"] + 0.86) < 1e-6
    m.ministick = (0.71, -0.57)               # сильная диагональ — обе оси живут
    out = m.step(cfg, [0.0] * 8, [0] * 39, [(0, 0)], now=0.01)
    assert abs(out["cam_x"] - 0.71) < 1e-6 and abs(out["cam_y"] + 0.57) < 1e-6
    cfg["ministick"]["axis_lock"] = False     # без галочки — как раньше
    m.ministick = (1.0, 0.29)
    out = m.step(cfg, [0.0] * 8, [0] * 39, [(0, 0)], now=0.015)
    assert abs(out["cam_y"] - 0.29) < 1e-6
    assert c.sanitize_config({})["ministick"]["axis_lock"] is False


def test_sequence_delay_up_to_5_minutes():
    st = c.clean_steps([{"keys": ["L"], "delay_ms": 120000, "duration_ms": 100},
                        {"keys": ["K"], "delay_ms": 999999, "duration_ms": 100}])
    assert [s["delay_ms"] for s in st] == [120000, c.SEQ_MAX_DELAY_MS] and c.SEQ_MAX_DELAY_MS == 300000
