# -*- coding: utf-8 -*-
"""Модель вида «Карта кнопок» (как RS Mapper): колонки нажатие / долгое / отпускание."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import x52_core as c  # noqa: E402
import x52_rsview as rv  # noqa: E402


def col(**k):
    d = {"enabled": True, "name": "", "kind": "key", "mods": [], "key": "", "repeat": False, "repeat_ms": 100,
         "continuous": False, "seq": "", "profile": "", "special": False}
    d.update(k)
    return d


OFF = col(enabled=False)


def prof():
    return c.new_profile_config("DCS", "custom", c.default_config())


def test_apply_and_read_back():
    cfg = prof()
    b = rv.btn_binding(4)
    rv.apply_slots(cfg, b, 0, {"single": col(name="Фонарь", mods=["LCTRL"], key="C"),
                               "long": col(name="Свет", key="L", continuous=True),
                               "release": col(name="Двигатель", mods=["RSHIFT"], key="HOME")})
    s = rv.find_slots(cfg, b)
    assert s["single"]["trigger"] == "short" and s["single"]["mode"] == "tap"   # есть долгое -> короткое
    assert s["single"]["keys"] == ["LCTRL", "C"]
    assert s["long"]["mode"] == "hold" and s["release"]["trigger"] == "release"
    back = rv.column_from_ca(s["single"])
    assert back["mods"] == ["LCTRL"] and back["key"] == "C" and not back["continuous"]
    assert c.conflicting_actions(cfg) == set()
    # выключили долгое — нажатие снова обычное, действие «Свет» удалено
    rv.apply_slots(cfg, b, 0, {"single": rv.column_from_ca(s["single"]), "long": OFF,
                               "release": rv.column_from_ca(s["release"])})
    s = rv.find_slots(cfg, b)
    assert set(s) == {"single", "release"} and s["single"]["trigger"] == "press"
    assert len(cfg["custom_actions"]) == 2


def test_dcs_camera_kind():
    cfg = prof()
    b = rv.btn_binding(7)
    rv.apply_slots(cfg, b, 0, {"single": col(name="Обзор вправо", kind="cam", cam="right"),
                               "long": OFF, "release": OFF})
    s = rv.find_slots(cfg, b)
    assert s["single"]["mode"] == "camera" and s["single"]["cam"] == "right" and s["single"]["keys"] == []
    back = rv.column_from_ca(s["single"])
    assert back["kind"] == "cam" and back["cam"] == "right" and rv.column_problem(back) is None
    row = rv.mapped_rows(cfg, "X52")[0][2]
    assert "горизонталь (абсолют) — вправо" in row[5]


def test_repeat_seq_profile_kinds():
    cfg = prof()
    cfg["sequences"] = [{"name": "Запуск", "steps": [{"keys": ["A"], "delay_ms": 0, "duration_ms": 50}]}]
    b = rv.hat_binding(0, "ne")
    rv.apply_slots(cfg, b, 0, {"single": col(name="Огонь", key="SPACE", repeat=True, repeat_ms=80),
                               "long": col(name="Старт", kind="seq", seq="Запуск"),
                               "release": col(name="След.", kind="profile", profile=rv.NEXT_P)})
    s = rv.find_slots(cfg, b)
    assert s["single"]["mode"] == "repeat" and s["single"]["repeat_ms"] == 80
    assert s["long"]["mode"] == "sequence" and s["long"]["seq"] == "Запуск"
    assert s["release"]["profile"] == {"kind": "next", "names": []}
    assert rv.column_from_ca(s["release"])["profile"] == rv.NEXT_P
    rows = rv.mapped_rows(cfg, "X52")
    assert [r[2][4] for r in rows] == ["Нажатие (короткое)", "Долгое", "Отпускание"]
    assert rows[0][2][3] == "Хатка 1 ↗" and rows[0][2][6] == "80 мс" and rows[1][2][8] == "Запуск"


def test_seq_hold_column_roundtrip():
    cfg = prof()
    cfg["sequences"] = [{"name": "Запуск", "steps": [{"keys": ["A"], "delay_ms": 0, "duration_ms": 50}]}]
    b = {"type": "axis", "index": 5, "dir": "+", "thr": 0.5}
    rv.apply_slots(cfg, b, 0, {"single": col(name="Старт", kind="seq", seq="Запуск", seq_hold=True),
                               "long": col(enabled=False), "release": col(enabled=False)})
    ca = rv.find_slots(cfg, b)["single"]
    assert ca["mode"] == "sequence" and ca["seq_hold"] is True and ca["trigger"] == "press"
    assert rv.column_from_ca(ca)["seq_hold"] is True
    assert rv.mapped_rows(cfg, "X52")[0][2][6] == "пока держите"
    sig = rv.ca_signature(ca)
    ca["seq_hold"] = False
    assert rv.ca_signature(ca) != sig


def test_special_kept_and_shared_binding():
    cfg = prof()
    b, b2 = rv.btn_binding(1), rv.btn_binding(2)
    cfg["custom_actions"] = [{"id": "c1", "name": "Шасси", "keys": ["G"], "mode": "toggle",
                              "bindings": [b, None]},
                             {"id": "c2", "name": "Общая", "keys": ["X"], "mode": "tap", "trigger": "release",
                              "bindings": [b, b2]}]
    cfg = c.sanitize_config(cfg)
    s = rv.find_slots(cfg, b)
    assert rv.column_from_ca(s["single"])["special"]
    cols = {"single": rv.column_from_ca(s["single"]), "long": OFF, "release": OFF}
    rv.apply_slots(cfg, b, 0, cols)
    ids = {ca["id"]: ca for ca in cfg["custom_actions"]}
    assert ids["c1"]["mode"] == "toggle"                    # особое действие не тронуто
    assert ids["c2"]["bindings"] == [b2, None]              # общий: убрали только эту кнопку


def test_layers_separate():
    cfg = prof()
    cfg["layers"]["enabled"] = True
    b = rv.btn_binding(3)
    rv.apply_slots(cfg, b, 1, {"single": col(name="A", key="A"), "long": OFF, "release": OFF})
    rv.apply_slots(cfg, b, 2, {"single": col(name="B", key="B"), "long": OFF, "release": OFF})
    assert rv.find_slots(cfg, b, 1)["single"]["keys"] == ["A"]
    assert rv.find_slots(cfg, b, 2)["single"]["keys"] == ["B"]
    assert c.conflicting_actions(cfg) == set()


def test_column_problems():
    assert rv.column_problem(col(key="")) == "выберите клавишу"
    assert "последовательность" in rv.column_problem(col(kind="seq"))
    assert rv.column_problem(col(kind="profile")) == "выберите профиль"
    assert rv.column_problem(OFF) is None and rv.column_problem(col(key="A")) is None


def test_axis_inputs_threshold_and_names():
    cfg = prof()
    b = rv.axis_binding(3, "+", rv.axis_thr(cfg, 3, "+"))
    assert b["thr"] == 0.5 and rv.axis_thr(cfg, 3, "-") == -0.5
    rv.apply_slots(cfg, b, 0, {"single": col(name="Свет", key="L"), "long": OFF,
                               "release": col(name="Свет выкл", key="K")})
    assert set(rv.find_slots(cfg, rv.axis_binding(3, "+", 0.9))) == {"single", "release"}   # порог не важен
    assert rv.find_slots(cfg, rv.axis_binding(3, "-", -0.5)) == {}
    rv.set_axis_thr(cfg, 3, "+", 0.2)
    assert all(ca["bindings"][0]["thr"] == 0.2 for ca in cfg["custom_actions"])
    assert c.sanitize_config(cfg)["axis_thr"] == {"a3:+": 0.2}
    cfg["button_names"]["a3"] = "Крутилка I"
    assert rv.input_name(cfg, b) == "Крутилка I +"
    rows = rv.mapped_rows(cfg, "X52")
    assert rows[0][2][0] == "Ось" and rows[0][2][3] == "Крутилка I +"
    # выключили одно направление — действие удалено
    rv.apply_slots(cfg, b, 0, {"single": OFF, "long": OFF, "release": OFF})
    assert cfg["custom_actions"] == []
    # аналоговые роли
    d = c.default_config()
    assert rv.axis_roles(d, 2) == ["throttle"]
    d["axes_enabled"]["throttle"] = False
    assert rv.axis_roles(d, 2) == []
