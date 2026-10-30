"""5.5.32: «непрерывно (держать) > N мс» — клавиша жмётся, только если кнопку держат дольше N мс."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import x52_core as c  # noqa: E402
import x52_rsview as rv  # noqa: E402
from test_seq_cycle import Sim, prof  # noqa: E402


def hold_act(**kw):
    a = {"id": "h", "name": "Огонь", "keys": ["SPACE"], "mode": "hold",
         "bindings": [{"type": "button", "index": 0}, None]}
    a.update(kw)
    return a


def test_hold_delay_short_press_nothing_long_press_holds():
    s = Sim(prof([hold_act(hold_delay_ms=1000)]))
    assert not any(s.run(900, b0=1))                       # меньше 1 с — клавиша не нажата
    seen = s.run(300, b0=1)
    assert seen[-1] == frozenset({"SPACE"})                # дольше 1 с — держится
    assert not any(s.run(50, b0=0)[2:])                    # отпустили — отпущена
    assert not any(s.run(500, b0=1) + s.run(50, b0=0))      # короткое нажатие — ничего


def test_hold_without_delay_unchanged():
    s = Sim(prof([hold_act()]))                            # старые профили: поля нет -> сразу
    assert prof([hold_act()])["custom_actions"][0]["hold_delay_ms"] == 0
    assert s.run(20, b0=1)[-1] == frozenset({"SPACE"})


def test_column_roundtrip_and_text():
    cfg = prof([])
    b = rv.btn_binding(3)
    off = {"enabled": False}
    col = rv.column_from_ca(c.sanitize_config(prof([hold_act()]))["custom_actions"][0])
    col.update(enabled=True, key="F", mods=[], continuous=True, hold_delay_ms=1500)
    rv.apply_slots(cfg, b, 0, {"single": col, "long": off, "release": off})
    ca = rv.find_slots(cfg, b)["single"]
    assert ca["mode"] == "hold" and ca["hold_delay_ms"] == 1500
    assert "держать > 1500 мс" in c.custom_out_text(ca)
    assert rv.column_from_ca(ca)["hold_delay_ms"] == 1500
    assert rv.ca_signature(dict(ca, hold_delay_ms=500)) != rv.ca_signature(ca)
    # новая кнопка в окне — по умолчанию 1000 мс
    assert rv.column_from_ca(dict(ca, mode="tap"))["hold_delay_ms"] == 1000
