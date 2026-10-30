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



def test_cycle_kind_roundtrip():
    """5.5.31: «Перебор по кругу» — шаги прямо в колонке, у каждого шага своя клавиша."""
    cfg = prof()
    b = rv.btn_binding(6)
    rv.apply_slots(cfg, b, 0, {"single": col(name="Оружие", kind="cycle", cycle_steps=[["1"], ["LSHIFT", "2"], ["3"]],
                                             cycle_hold_ms=120, seq_cycle_reset=True, seq_cycle_reset_ms=1500,
                                             seq_cycle_profile_reset=False),
                               "long": OFF, "release": OFF})
    ca = rv.find_slots(cfg, b)["single"]
    assert ca["mode"] == "sequence" and ca["seq_cycle"] is True and ca["seq"] == "" and ca["seq_hold"] is False
    assert [st["keys"] for st in ca["steps"]] == [["1"], ["LSHIFT", "2"], ["3"]]       # порядок как в списке
    assert {st["duration_ms"] for st in ca["steps"]} == {120}
    assert ca["seq_cycle_reset"] is True and ca["seq_cycle_reset_ms"] == 1500 and ca["seq_cycle_profile_reset"] is False
    back = rv.column_from_ca(ca, cfg)
    assert back["kind"] == "cycle" and not back["special"]
    assert back["cycle_steps"] == [["1"], ["LSHIFT", "2"], ["3"]] and back["cycle_hold_ms"] == 120
    assert back["seq_cycle_reset"] is True and back["seq_cycle_reset_ms"] == 1500
    assert back["seq_cycle_profile_reset"] is False
    row = rv.mapped_rows(cfg, "X52")[0][2]
    assert row[6] == "по кругу" and "1 → Shift (лев.) + 2 → 3" in row
    assert c.custom_out_text(ca).startswith("Перебор по кругу: 1 → Shift (лев.) + 2 → 3")
    # повторное применение той же колонки ничего не меняет
    sig = rv.ca_signature(ca)
    rv.apply_slots(cfg, b, 0, {"single": back, "long": OFF, "release": OFF})
    assert rv.ca_signature(rv.find_slots(cfg, b)["single"]) == sig
    for k, v in (("seq_cycle", False), ("seq_cycle_reset", False), ("seq_cycle_reset_ms", 900),
                 ("seq_cycle_profile_reset", True)):
        assert rv.ca_signature(dict(ca, **{k: v})) != sig, k       # «Применить в профилях» видит разницу


def test_cycle_kind_reset_off_and_order_change():
    cfg = prof()
    b = rv.btn_binding(7)
    cyc = col(name="W", kind="cycle", cycle_steps=[["A"], ["B"]], seq_cycle_reset=False)
    rv.apply_slots(cfg, b, 0, {"single": cyc, "long": OFF, "release": OFF})
    ca = rv.find_slots(cfg, b)["single"]
    assert ca["seq_cycle_reset"] is False and ca["seq_cycle_reset_ms"] == 1000
    assert "к 1-му шагу" not in c.custom_out_text(ca)
    rv.apply_slots(cfg, b, 0, {"single": dict(cyc, cycle_steps=[["B"], ["A"]]), "long": OFF, "release": OFF})
    assert [st["keys"] for st in rv.find_slots(cfg, b)["single"]["steps"]] == [["B"], ["A"]]
    # переключили на обычную клавишу — «по кругу» снимается
    rv.apply_slots(cfg, b, 0, {"single": col(name="W", key="Z"), "long": OFF, "release": OFF})
    ca = rv.find_slots(cfg, b)["single"]
    assert ca["mode"] == "tap" and ca["seq_cycle"] is False and ca["steps"] == []


def test_cycle_kind_problem_without_steps():
    assert rv.column_problem(col(kind="cycle", cycle_steps=[])) == "добавьте шаги перебора («+ шаг»)"
    assert rv.column_problem(col(kind="cycle", cycle_steps=[["A"]])) is None


def test_cycle_from_library_sequence_shown_as_steps():
    """Сделанный в 5.5.30 «по кругу» из библиотечной последовательности открывается как перебор с её шагами."""
    cfg = prof()
    cfg["sequences"] = [{"name": "Оружие", "steps": [{"keys": ["1"], "delay_ms": 0, "duration_ms": 70},
                                                     {"keys": ["2"], "delay_ms": 100, "duration_ms": 70}]}]
    b = rv.btn_binding(8)
    cfg["custom_actions"].append({"id": "q1", "name": "Оружие", "keys": [], "mode": "sequence", "seq": "Оружие",
                                  "seq_cycle": True, "bindings": [b, None]})
    cfg = c.sanitize_config(cfg)
    ca = rv.find_slots(cfg, b)["single"]
    back = rv.column_from_ca(ca, cfg)
    assert back["kind"] == "cycle" and back["cycle_steps"] == [["1"], ["2"]] and back["cycle_hold_ms"] == 70
    rv.apply_slots(cfg, b, 0, {"single": back, "long": OFF, "release": OFF})
    ca = rv.find_slots(cfg, b)["single"]
    assert ca["seq"] == "" and [st["keys"] for st in ca["steps"]] == [["1"], ["2"]]   # теперь свои шаги
