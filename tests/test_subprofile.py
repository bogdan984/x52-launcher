"""5.6.0: подпрофили — пока ось (ползунок/крутилка) в положении, назначения подпрофиля заменяют кнопки профиля."""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import x52_core as c  # noqa: E402

AX = {"type": "axis", "index": 6, "dir": "+", "thr": 0.5}     # ползунок вперёд
BTN = {"type": "button", "index": 0}                          # кнопка A
CYC = [{"keys": ["1"], "delay_ms": 0, "duration_ms": 50}, {"keys": ["2"], "delay_ms": 1, "duration_ms": 50},
       {"keys": ["3"], "delay_ms": 2, "duration_ms": 50}]


def prof():
    d = c.new_profile_config("Полёт", "custom", c.default_config())
    d["profile_name"] = "Полёт"
    d["subprofiles"] = [{"name": "Выбор оружия", "icon": "↻", "color": "#ff0000", "size": 30}]
    d["custom_actions"] = [
        {"id": "fire", "name": "Огонь", "keys": ["SPACE"], "mode": "hold", "bindings": [dict(BTN), None]},
        {"id": "sw", "name": "Подпрофиль", "mode": "subprofile", "subprofile": "Выбор оружия",
         "bindings": [dict(AX), None]},
        {"id": "wpn", "name": "Оружие", "mode": "sequence", "seq_cycle": True, "seq_cycle_reset": False,
         "steps": copy.deepcopy(CYC), "sub": "Выбор оружия", "bindings": [dict(BTN), None]},
    ]
    return c.sanitize_config(d)


class Sim:
    def __init__(self, cfg):
        self.cfg, self.m, self.t = cfg, c.Mapper(), 0.0
        self.btn, self.axes = [0] * 32, [0.0] * 8
        self.m.step(cfg, self.axes, self.btn, [], now=0.0)

    def run(self, ms):
        keys = set()
        for _ in range(int(round(ms / 5.0))):
            self.t += 0.005
            keys |= self.m.step(self.cfg, self.axes, self.btn, [], now=self.t)["keys"]
        return keys

    def tap(self):
        self.btn[0] = 1
        k = self.run(30)
        self.btn[0] = 0
        return k | self.run(100)


def test_sanitize_subprofiles():
    d = prof()
    assert d["subprofiles"] == [{"name": "Выбор оружия", "icon": "↻", "color": "#ff0000", "size": 30}]
    by = {ca["id"]: ca for ca in d["custom_actions"]}
    assert by["sw"]["mode"] == "subprofile" and by["sw"]["subprofile"] == "Выбор оружия" and by["sw"]["sub"] == ""
    assert by["wpn"]["sub"] == "Выбор оружия" and by["fire"]["sub"] == ""
    bad = c.sanitize_config(dict(d, subprofiles=[{"name": "X", "icon": "★", "color": "red", "size": 999}, 5]))
    assert bad["subprofiles"] == [{"name": "X", "icon": "", "color": c.SUB_COLOR, "size": 72}]
    # подпрофиль удалён — его назначения не остаются в профиле, «Подпрофиль» ни на что не указывает
    ids = {ca["id"]: ca for ca in bad["custom_actions"]}
    assert "wpn" not in ids and ids["sw"]["subprofile"] == ""
    assert not c.conflicting_actions(d)                # A в профиле и A в подпрофиле — не конфликт


def test_button_replaced_while_axis_on_and_cycle_kept():
    s = Sim(prof())
    assert s.tap() == {"SPACE"} and s.m.subprofile == ""         # профиль: A стреляет
    s.axes[6] = 0.8                                                # ползунок вперёд — подпрофиль
    s.run(20)
    assert s.m.subprofile == "Выбор оружия"
    assert s.tap() == {"1"}                                        # A — перебор оружия, без стрельбы
    assert s.tap() == {"2"}
    s.axes[6] = 0.0                                                # ползунок назад — снова профиль
    s.run(20)
    assert s.m.subprofile == ""
    assert s.tap() == {"SPACE"}                                    # стреляет, выбор оружия не трогает
    s.axes[6] = 0.8
    s.run(20)
    assert s.tap() == {"3"}                                        # перебор продолжился с того же места


def test_held_button_during_switch_is_silent():
    s = Sim(prof())
    s.btn[0] = 1
    assert s.run(30) == {"SPACE"}
    s.axes[6] = 0.8                                                # A ещё зажата — подпрофиль включили
    assert s.run(50) == set()                                      # ни огня, ни шага перебора
    s.btn[0] = 0
    assert s.run(50) == set()
    assert s.tap() == {"1"}


def test_free_button_keeps_profile_action_and_builtin_blocked():
    d = prof()
    d["custom_actions"][0]["bindings"] = [{"type": "button", "index": 5}, None]   # огонь на другой кнопке
    s = Sim(d)
    s.axes[6] = 0.8
    s.run(20)
    s.btn[5] = 1
    assert "SPACE" in s.run(30)                                    # не занята подпрофилем — работает как в профиле
    s.btn[5] = 0
    s.run(30)
    # встроенное действие на кнопке, занятой подпрофилем, молчит
    d2 = prof()
    d2["game"]["builtin_actions"] = True
    gun = next(a for a in c.ACTION_IDS if (d2["bindings"].get(a) or [None])[0] == BTN)
    s2 = Sim(d2)
    s2.btn[0] = 1
    s2.run(30)
    assert gun in s2.m.step(d2, s2.axes, s2.btn, [], now=s2.t + 0.005)["actions"]
    s2.btn[0] = 0
    s2.run(30)
    s2.axes[6] = 0.8
    s2.run(20)
    s2.btn[0] = 1
    s2.run(30)
    assert gun not in s2.m.step(d2, s2.axes, s2.btn, [], now=s2.t + 0.005)["actions"]


def test_rsview_slots_per_subprofile():
    import x52_rsview as rv
    d = prof()
    assert set(rv.find_slots(d, BTN)) == {"single"} and rv.find_slots(d, BTN)["single"]["id"] == "fire"
    assert rv.find_slots(d, BTN, 0, "Выбор оружия")["single"]["id"] == "wpn"
    col = rv.column_from_ca(rv.find_slots(d, dict(AX))["single"], d)
    assert col["kind"] == "sub" and col["subprofile"] == "Выбор оружия"
    assert rv.column_problem(dict(col, subprofile="")) and not rv.column_problem(col)
    off = {"enabled": False}
    key = dict(rv.column_from_ca(d["custom_actions"][0], d), name="Ракеты", key="R")
    rv.apply_slots(d, {"type": "button", "index": 1}, 0, {"single": key, "long": off, "release": off},
                   "Выбор оружия")
    new = rv.find_slots(d, {"type": "button", "index": 1}, 0, "Выбор оружия")["single"]
    assert new["sub"] == "Выбор оружия" and new["keys"] == ["R"]
    assert not rv.find_slots(d, {"type": "button", "index": 1})                     # в профиле кнопка свободна
    assert rv.sub_label(d["subprofiles"][0]) == "↻ Выбор оружия"
