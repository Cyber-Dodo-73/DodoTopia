# -*- coding: utf-8 -*-
"""Tests du module Cuisine (cook.py) : ils importent les modules de la racine du projet.

Isolation : en mode source, core.DATA_DIR est le dossier du projet. Les tests ne doivent JAMAIS écrire
dans le projet — core.DATA_DIR / core.CONFIG_PATH sont redirigés vers un dossier temporaire avant chaque
test, les Cooker sont construits avec un cfg jetable et `save=lambda: None`, et config.json / library.json
du projet sont vérifiés intacts après chaque test."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_GUARDED = ("config.json", "library.json", "account.json", "cuisine.log")


def _stamp(name):
    p = os.path.join(ROOT, name)
    try:
        st = os.stat(p)
        return st.st_size, st.st_mtime_ns
    except OSError:
        return None


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    import core
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(core, "DATA_DIR", str(data))
    monkeypatch.setattr(core, "CONFIG_PATH", str(data / "config.json"))
    # aucune fenetre de jeu pendant les tests : la verification « jeu au premier plan » est neutre
    import platform_io
    monkeypatch.setattr(platform_io, "foreground_process_name", lambda: None)
    monkeypatch.setattr(platform_io, "game_window_info", lambda name: {"found": None, "foreground": None, "elevated": None})
    before = {n: _stamp(n) for n in _GUARDED}
    yield
    after = {n: _stamp(n) for n in _GUARDED}
    assert after == before, f"un test a modifié un fichier du projet : {[n for n in _GUARDED if before[n] != after[n]]}"
