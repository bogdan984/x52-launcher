# -*- coding: utf-8 -*-
"""Сохранение/загрузка всех настроек одним файлом и сообщения ярлыка."""
import json
import os
import shutil
import sys
import types
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import x52_ac8_launcher as L  # noqa: E402


@pytest.fixture
def data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    (d / "profiles").mkdir(parents=True)
    monkeypatch.setattr(L, "CONFIG_PATH", str(d / "x52_config.json"))
    return d


def _w(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_export_import_roundtrip(data, tmp_path):
    _w(data / "x52_config.json", {"profile_name": "Взлёт Су-27"})
    _w(data / "x52_global.json", {"zoom": {"settings": {"axis": 6}, "profiles": ["Взлёт Су-27"]}})
    _w(data / "profiles" / "Взлёт Су-27.json", {"profile_name": "Взлёт Су-27"})
    _w(data / "profiles" / "Полёт.json", {"profile_name": "Полёт"})
    arc = tmp_path / "all.zip"
    assert L.export_all_settings(str(arc)) == 2
    shutil.rmtree(data)
    (data / "profiles").mkdir(parents=True)
    assert L.import_all_settings(str(arc)) == 2
    g = json.loads((data / "x52_global.json").read_text(encoding="utf-8"))
    assert g["zoom"]["profiles"] == ["Взлёт Су-27"]
    assert sorted(os.listdir(data / "profiles")) == ["Взлёт Су-27.json", "Полёт.json"]
    assert json.loads((data / "x52_config.json").read_text(encoding="utf-8"))["profile_name"] == "Взлёт Су-27"


def test_import_rejects_bad_archives(data, tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ValueError):
        L.import_all_settings(str(bad))
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("readme.txt", "x")
        z.writestr("../x52_config.json", "{}")            # выход из папки — игнорируется
    with pytest.raises(ValueError):
        L.import_all_settings(str(empty))
    assert not (tmp_path / "x52_config.json").exists()
    nojson = tmp_path / "nojson.zip"
    with zipfile.ZipFile(nojson, "w") as z:
        z.writestr("profiles/A.json", "[1, 2]")
    with pytest.raises(ValueError):
        L.import_all_settings(str(nojson))
    assert os.listdir(data / "profiles") == []          # при ошибке ничего не записано


def test_shortcut_messages(monkeypatch):
    monkeypatch.setattr(L, "IS_WIN", True)
    for out, rc, want in (("exists", 0, (True, "уже есть")), ("created", 0, (True, "создан")),
                          ("yes", 0, (True, "yes")), ("ERR:public", 1, None)):
        monkeypatch.setattr(L, "run_powershell", lambda *a, **k: types.SimpleNamespace(
            stdout=out, stderr="", returncode=rc))
        r = L.shortcut("create")
        if want:
            assert r == want
        else:
            assert r[0] is False and "администратора" in r[1]
