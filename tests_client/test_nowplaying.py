# -*- coding: utf-8 -*-
"""Fichier « en cours de lecture » pour OBS : DATA_DIR/nowplaying.txt, ecrit seulement au changement."""
import os
import threading
import types
from collections import deque

import pytest

import core
import settings_schema


@pytest.fixture
def api():
    import app
    cfg = core.load_config()
    a = object.__new__(app.Api)
    a._cfg = cfg
    a._logs = deque(maxlen=50)
    a._toasts = deque(maxlen=10)
    a._toast_seq = 0
    a._ui_lock = threading.RLock()
    a._presence = None
    inst = types.SimpleNamespace(name="Piano", label_en="Piano")
    a._player = types.SimpleNamespace(state="stopped", target="preview", songs=["x/Clair.mid"], index=0,
                                      instrument=inst, current=lambda: "x/Clair.mid")
    return a


def _path():
    return os.path.join(core.DATA_DIR, "nowplaying.txt")


def _read():
    with open(_path(), encoding="utf-8") as f:
        return f.read()


def test_reglage_par_defaut_desactive(api):
    assert settings_schema.defaults()["online.now_playing_file"] is False
    assert settings_schema.defaults()["online.rich_presence"] is True
    assert settings_schema._spec("online.rich_presence")["after"] == "_on_rich_presence"
    songs = [{"name": "Clair de lune"}]
    api._player.state = "playing"
    api._integrations_tick(songs)
    assert not os.path.exists(_path())


def test_ecrit_pendant_la_lecture_et_vide_sinon(api, monkeypatch):
    settings_schema.set_value(api._cfg, "online.now_playing_file", True)
    api._on_now_playing_file()
    songs = [{"name": "Clair de lune"}]
    writes = []
    real = api._write_nowplaying
    monkeypatch.setattr(api, "_write_nowplaying", lambda text: (writes.append(text), real(text)))
    api._integrations_tick(songs)
    assert _read() == "" and writes == [""]
    api._player.state = "playing"
    for _ in range(10):
        api._integrations_tick(songs)
    assert _read() == "Clair de lune — Piano"
    assert writes == ["", "Clair de lune — Piano"], "écriture seulement au changement"
    api._player.state = "stopped"
    api._integrations_tick(songs)
    assert _read() == ""
    assert not [n for n in os.listdir(core.DATA_DIR) if ".tmp" in n], "fichier temporaire oublié"


def test_desactivation_vide_le_fichier(api):
    api._cfg.setdefault("online", {})["now_playing_file"] = True
    api._player.state = "playing"
    api._integrations_tick([{"name": "Clair de lune"}])
    assert _read() == "Clair de lune — Piano"
    api._cfg["online"]["now_playing_file"] = False
    api._on_now_playing_file()
    assert _read() == ""
    api._integrations_tick([{"name": "Autre"}])
    assert _read() == ""


def test_fermeture_vide_le_fichier(api):
    api._cfg.setdefault("online", {})["now_playing_file"] = True
    api._player.state = "paused"
    api._integrations_tick([{"name": "Clair de lune"}])
    assert _read() == "Clair de lune — Piano"
    api._integrations_close()
    assert _read() == ""
