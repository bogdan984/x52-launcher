"""5.5.30: последовательность «по кругу» — каждое нажатие кнопки = следующий шаг."""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import x52_core as c  # noqa: E402

# у каждого шага свои клавиши (как выбор оружия 1 / 2 / 3)
STEPS = [{"keys": ["1"], "delay_ms": 0, "duration_ms": 50},
         {"keys": ["LSHIFT", "2"], "delay_ms": 100, "duration_ms": 80},
         {"keys": ["3"], "delay_ms": 200, "duration_ms": 30}]
S1, S2, S3 = frozenset({"1"}), frozenset({"LSHIFT", "2"}), frozenset({"3"})
E = frozenset()


def act(cid="w", b=0, **kw):
    a = {"id": cid, "name": "Оружие", "keys": [], "mode": "sequence", "steps": copy.deepcopy(STEPS),
         "seq_cycle": True, "bindings": [{"type": "button", "index": b}, None]}
    a.update(kw)
    return a


def prof(actions, name="DCS World", layers=False, sequences=()):
    d = c.new_profile_config(name, "custom", c.default_config())
    d["profile_name"] = name
    d["custom_actions"] = actions
    d["layers"]["enabled"] = layers
    d["sequences"] = list(sequences)
    return c.sanitize_config(d)


class Sim:
    """Прогон маппера по времени, шаг 5 мс; cfg можно менять (смена профиля)."""
    def __init__(self, cfg, m=None):
        self.cfg, self.m, self.t = cfg, m or c.Mapper(), 0.0
        self.btn = [0] * 32
        self.m.step(cfg, [0.0] * 8, self.btn, [], now=0.0)

    def run(self, ms, **press):
        for k, v in press.items():
            self.btn[int(k[1:])] = v
        seen = []
        for _ in range(int(round(ms / 5.0))):
            self.t += 0.005
            seen.append(frozenset(self.m.step(self.cfg, [0.0] * 8, self.btn, [], now=self.t)["keys"]))
        return seen

    def tap(self, hold_ms=20, b=0, after_ms=150):
        """Нажать на hold_ms, отпустить и подождать after_ms. Возвращает непустые наборы клавиш (без повторов)."""
        seen = self.run(hold_ms, **{"b%d" % b: 1}) + self.run(after_ms, **{"b%d" % b: 0})
        out = []
        for s in seen:
            if s and (not out or out[-1] != s):
                out.append(s)
        return out, seen


# ---------------------------------------------------------------- настройки
def test_sanitize_defaults_and_limits():
    d = prof([act(), act("x", 1, seq_cycle=False)])
    a, b = d["custom_actions"]
    assert a["seq_cycle"] is True and a["seq_cycle_reset_ms"] == 1000 and a["seq_cycle_profile_reset"] is True
    assert a["seq_cycle_reset"] is True
    assert b["seq_cycle"] is False
    # (значение) -> (галочка сброса, мс); 0 и меньше — так 5.5.30 хранил «без сброса»
    for raw, want in ((-5, (False, 1000)), (99999, (True, c.SEQ_CYCLE_RESET_MAX_MS)), ("abc", (True, 1000)),
                      (None, (True, 1000)), (True, (True, 1000)), (float("nan"), (True, 1000)),
                      ("750", (True, 750)), (0, (False, 1000)), (30, (True, c.SEQ_CYCLE_RESET_MIN_MS))):
        ca = prof([act(seq_cycle_reset_ms=raw)])["custom_actions"][0]
        assert (ca["seq_cycle_reset"], ca["seq_cycle_reset_ms"]) == want, raw
    ca = prof([act(seq_cycle_reset=False, seq_cycle_reset_ms=1500)])["custom_actions"][0]
    assert ca["seq_cycle_reset"] is False and ca["seq_cycle_reset_ms"] == 1500         # время сохраняется
    assert prof([act(seq_cycle_profile_reset=False)])["custom_actions"][0]["seq_cycle_profile_reset"] is False


def test_old_config_without_fields():
    a = act()
    del a["seq_cycle"]
    ca = prof([a])["custom_actions"][0]
    assert ca["seq_cycle"] is False and ca["seq_cycle_profile_reset"] is True


def test_cycle_and_hold_exclusive():
    ca = prof([act(seq_hold=True)])["custom_actions"][0]
    assert ca["seq_cycle"] is True and ca["seq_hold"] is False


def test_out_text():
    ca = prof([act()])["custom_actions"][0]
    assert c.custom_out_text(ca) == "Перебор по кругу: 1 → Shift (лев.) + 2 → 3 · к 1-му шагу: держать 1000 мс"
    ca = prof([act(seq_cycle_reset=False)])["custom_actions"][0]
    assert c.custom_out_text(ca) == "Перебор по кругу: 1 → Shift (лев.) + 2 → 3"
    ca = prof([act(steps=[], seq="Либ", seq_cycle_reset=False)])["custom_actions"][0]
    assert c.custom_out_text(ca) == "Последовательность «Либ» · по кругу"


def test_sanitize_roundtrip_stable():
    d = prof([act(seq_cycle_reset_ms=1500, seq_cycle_profile_reset=False)])
    assert c.sanitize_config(copy.deepcopy(d))["custom_actions"] == d["custom_actions"]


# ---------------------------------------------------------------- без сброса (0 мс): шаг сразу при нажатии
def test_no_reset_fires_on_press_and_cycles():
    s = Sim(prof([act(seq_cycle_reset_ms=0)]))
    got = [s.tap()[0] for _ in range(7)]
    assert got == [[S1], [S2], [S3], [S1], [S2], [S3], [S1]]   # по кругу, у каждого шага свои клавиши


def test_no_reset_fires_immediately_on_press():
    s = Sim(prof([act(seq_cycle_reset_ms=0)]))
    assert s.run(5, b0=1) == [S1]                                  # первый же кадр нажатия


def test_step_held_for_its_duration_not_button_time():
    s = Sim(prof([act(seq_cycle_reset_ms=0)]))
    seen = s.run(500, b0=1)                                        # держим кнопку долго
    assert 10 <= seen.count(S1) <= 11 and seen[11:] == [E] * 89    # 50 мс шага 1 (±кадр), потом тишина
    s.run(50, b0=0)
    seen = s.run(500, b0=1)
    assert 16 <= seen.count(S2) <= 17 and set(seen) == {S2, E}     # 80 мс шага 2, без повтора


def test_long_hold_without_reset_does_not_repeat_or_reset():
    s = Sim(prof([act(seq_cycle_reset_ms=0)]))
    s.tap()
    s.run(3000, b0=1)                                              # это шаг 2, долгое удержание — не сброс
    s.run(50, b0=0)
    assert s.tap()[0] == [S3]


def test_reset_checkbox_off_keeps_time_but_fires_on_press():
    s = Sim(prof([act(seq_cycle_reset=False, seq_cycle_reset_ms=300)]))
    assert s.run(5, b0=1) == [S1]                                  # без галочки — шаг сразу при нажатии
    s.run(600, b0=1)                                               # долгое удержание — не сброс
    s.run(50, b0=0)
    assert s.tap()[0] == [S2]


# ---------------------------------------------------------------- со сбросом удержанием
def test_with_reset_fires_on_release():
    s = Sim(prof([act(seq_cycle_reset_ms=1000)]))
    assert set(s.run(300, b0=1)) == {E}                            # пока держим — ничего
    seen = s.run(100, b0=0)
    assert seen[0] == S1 and 10 <= seen.count(S1) <= 11            # отпустили — шаг 1 на 50 мс
    assert [s.tap()[0] for _ in range(3)] == [[S2], [S3], [S1]]


def test_hold_resets_to_first_step():
    s = Sim(prof([act(seq_cycle_reset_ms=1000)]))
    assert [s.tap()[0] for _ in range(2)] == [[S1], [S2]]
    out, seen = s.tap(hold_ms=1200)                                # держим дольше порога — сброс
    assert out == [] and set(seen) == {E}                          # при сбросе клавиши не жмутся
    assert [s.tap()[0] for _ in range(4)] == [[S1], [S2], [S3], [S1]]


def test_reset_threshold_boundary():
    s = Sim(prof([act(seq_cycle_reset_ms=700)]))
    s.tap()                                                        # шаг 1 → следующий 2
    assert s.tap(hold_ms=690)[0] == [S2]                           # чуть меньше порога — обычный шаг
    assert s.tap(hold_ms=710)[0] == []                             # чуть больше — сброс
    assert s.tap()[0] == [S1]


def test_reset_threshold_user_value():
    for ms in (300, 2500):
        s = Sim(prof([act(seq_cycle_reset_ms=ms)]))
        s.tap()
        s.tap(hold_ms=ms + 20)
        assert s.tap()[0] == [S1], ms


def test_reset_when_already_at_first_step():
    s = Sim(prof([act()]))
    assert s.tap(hold_ms=1100)[0] == []
    assert s.tap()[0] == [S1]


def test_reset_stops_running_step():
    # шаг 2 держится 80 мс; сброс короче не бывает — но длинный шаг обрывается сбросом
    st = copy.deepcopy(STEPS)
    st[0]["duration_ms"] = 5000
    s = Sim(prof([act(steps=st, seq_cycle_reset_ms=300)]))
    s.run(20, b0=1)
    assert s.run(5, b0=0) == [S1]                                  # шаг 1 начат (держать 5 с)
    s.run(100, b0=0)
    s.run(20, b0=1)
    assert s.run(400, b0=1)[-1] == E                               # сброс: шаг 1 больше не держится
    s.run(50, b0=0)
    assert s.tap()[0] == [S1]


def test_highlight_on_reset():
    s = Sim(prof([act(seq_cycle_reset_ms=300)]))
    s.run(310, b0=1)
    out = s.m.step(s.cfg, [0.0] * 8, s.btn, [], now=s.t + 0.005)
    assert c.CUSTOM_PREFIX + "w" in out["actions"] and not out["keys"]


def test_new_press_replaces_running_step():
    st = copy.deepcopy(STEPS)
    for x in st:
        x["duration_ms"] = 1000
    s = Sim(prof([act(steps=st, seq_cycle_reset_ms=0)]))
    s.run(20, b0=1)
    s.run(20, b0=0)
    seen = s.run(20, b0=1)                                         # нажали снова, пока шаг 1 ещё держится
    assert seen[0] == S2 and S1 not in seen                        # шаг 1 отпущен, шаг 2 вместо него


def test_single_step_sequence():
    s = Sim(prof([act(steps=[STEPS[0]], seq_cycle_reset_ms=0)]))
    assert [s.tap()[0] for _ in range(3)] == [[S1]] * 3


def test_two_cycle_actions_independent():
    other = [{"keys": ["A"], "delay_ms": 0, "duration_ms": 50}, {"keys": ["B"], "delay_ms": 10, "duration_ms": 50}]
    s = Sim(prof([act(seq_cycle_reset_ms=0), act("z", 1, name="Ракеты", steps=other, seq_cycle_reset_ms=0)]))
    assert s.tap(b=0)[0] == [S1]
    assert s.tap(b=1)[0] == [{"A"}]
    assert s.tap(b=0)[0] == [S2]
    assert s.tap(b=1)[0] == [{"B"}]
    assert s.tap(b=1)[0] == [{"A"}]


def test_library_sequence_by_name():
    lib = {"name": "Оружие-круг", "steps": copy.deepcopy(STEPS)}
    s = Sim(prof([act(steps=[], seq="Оружие-круг", seq_cycle_reset_ms=0)], sequences=[lib]))
    assert [s.tap()[0] for _ in range(4)] == [[S1], [S2], [S3], [S1]]


def test_missing_library_sequence_is_silent():
    s = Sim(prof([act(steps=[], seq="нет такой", seq_cycle_reset_ms=0)]))
    assert s.tap()[0] == []


def test_layers_respected():
    a = act(seq_cycle_reset_ms=0, layer=2)
    s = Sim(prof([a], layers=True))
    s.btn[23] = 1                                                  # колесо в положении 1
    assert s.tap()[0] == []
    s.btn[23], s.btn[24] = 0, 1                                    # положение 2
    assert s.tap()[0] == [S1]
    assert s.tap()[0] == [S2]


def test_normal_sequence_unchanged():
    s = Sim(prof([act(seq_cycle=False)]))
    seen = s.run(5, b0=1) + s.run(300, b0=0)
    assert seen[0] == S1 and S2 in seen and S3 in seen             # обычная: все шаги по времени


def test_joystick_loss_keeps_counter():
    s = Sim(prof([act(seq_cycle_reset_ms=0)]))
    s.tap()
    s.m.reset()                                                    # потеря джойстика / остановка моста
    s.run(5)
    assert s.tap()[0] == [S2]


# ---------------------------------------------------------------- смена профиля
def _switch(s, cfg):
    s.cfg = cfg
    s.m.reset()             # как Worker при смене профиля (_reset_mapper)
    s.run(20)


def test_profile_switch_resets_when_checked():
    a, b = prof([act(seq_cycle_reset_ms=0)], "A"), prof([], "B")
    s = Sim(a)
    s.tap(), s.tap()
    _switch(s, b)
    _switch(s, a)
    assert s.tap()[0] == [S1]


def test_profile_switch_keeps_when_unchecked():
    a = prof([act(seq_cycle_reset_ms=0, seq_cycle_profile_reset=False)], "A")
    s = Sim(a)
    s.tap(), s.tap()
    _switch(s, prof([], "B"))
    _switch(s, a)
    assert s.tap()[0] == [S3]


def test_profile_switch_without_mapper_reset():
    # смена cfg без reset() маппера — галочка работает так же
    a = prof([act(seq_cycle_reset_ms=0)], "A")
    keep = prof([act("k", 1, name="Другое", seq_cycle_reset_ms=0, seq_cycle_profile_reset=False)], "A")
    for cfg, want in ((a, [S1]), (keep, [S2])):
        s = Sim(cfg)
        s.tap(b=1 if cfg is keep else 0)
        s.cfg = prof([], "B")
        s.run(20)
        s.cfg = cfg
        s.run(20)
        assert s.tap(b=1 if cfg is keep else 0)[0] == want


def test_same_action_in_two_profiles_shares_counter():
    kw = dict(seq_cycle_reset_ms=0, seq_cycle_profile_reset=False)
    a, b = prof([act(**kw)], "A"), prof([act("c7", **kw)], "B")   # копия действия в другом профиле
    s = Sim(a)
    s.tap()
    _switch(s, b)
    assert s.tap()[0] == [S2]
    _switch(s, a)
    assert s.tap()[0] == [S3]


def test_same_action_in_two_profiles_resets_when_checked():
    a, b = prof([act(seq_cycle_reset_ms=0)], "A"), prof([act(seq_cycle_reset_ms=0)], "B")
    s = Sim(a)
    s.tap()
    _switch(s, b)
    assert s.tap()[0] == [S1]


def test_different_action_same_id_other_profile_not_shared():
    other = [{"keys": ["A"], "delay_ms": 0, "duration_ms": 50}, {"keys": ["B"], "delay_ms": 10, "duration_ms": 50}]
    kw = dict(seq_cycle_reset_ms=0, seq_cycle_profile_reset=False)
    a, b = prof([act(**kw)], "A"), prof([act(name="Другое", steps=other, **kw)], "B")
    s = Sim(a)
    s.tap(), s.tap()
    _switch(s, b)
    assert s.tap()[0] == [{"A"}]                                   # у другого действия свой счётчик
    _switch(s, a)
    assert s.tap()[0] == [S3]


def test_same_profile_reload_does_not_reset():
    a = prof([act(seq_cycle_reset_ms=0)], "A")
    s = Sim(a)
    s.tap()
    _switch(s, copy.deepcopy(a))                                   # сохранили/перечитали тот же профиль
    assert s.tap()[0] == [S2]


def test_button_held_through_profile_switch_does_not_step():
    for rs in (0, 1000):
        a = prof([act(seq_cycle_reset_ms=rs)], "A")
        s = Sim(prof([], "B"))
        s.run(20, b0=1)                                            # кнопка зажата ещё в профиле B
        _switch(s, a)
        assert set(s.run(100, b0=1)) == {E}
        assert set(s.run(100, b0=0)) == {E}, rs                    # отпустили — шага нет
        assert s.tap()[0] == [S1], rs                              # следующее нажатие — шаг 1


def test_edit_steps_restarts_counter():
    a = prof([act(seq_cycle_reset_ms=0)], "A")
    s = Sim(a)
    s.tap(), s.tap()
    st = copy.deepcopy(STEPS) + [{"keys": ["4"], "delay_ms": 300, "duration_ms": 30}]
    s.cfg = prof([act(steps=st, seq_cycle_reset_ms=0)], "A")      # изменили шаги — новый счётчик
    assert s.tap()[0] == [S1]
