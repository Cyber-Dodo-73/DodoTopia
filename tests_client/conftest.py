# -*- coding: utf-8 -*-
"""Les tests du client importent les modules de la racine du projet (online.py, room.py, core.py…).

Isolation : en mode source, core.DATA_DIR est le dossier du projet ; tout chemin écrit par les modules
(config.json, account.json, updates/, downloads/) est redirigé vers un dossier temporaire avant chaque test, et
config.json / library.json du projet sont vérifiés intacts après chaque test."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_GUARDED = ("config.json", "library.json", "account.json")


def _stamp(name):
    p = os.path.join(ROOT, name)
    try:
        st = os.stat(p)
        return st.st_size, st.st_mtime_ns
    except OSError:
        return None


@pytest.fixture(autouse=True)
def french_messages():
    """Les tests comparent des textes français : la langue de Python est fixée avant chaque test (un test
    peut l'avoir changée, et Api() la relit depuis le système)."""
    import i18n
    i18n.set_lang("fr")
    yield
    i18n.set_lang("fr")


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    import core
    import online
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(core, "DATA_DIR", str(data))
    monkeypatch.setattr(core, "CONFIG_PATH", str(data / "config.json"))
    # aucune fenetre de jeu pendant les tests : la verification « jeu au premier plan » est neutre
    import platform_io
    monkeypatch.setattr(platform_io, "foreground_process_name", lambda: None)
    monkeypatch.setattr(platform_io, "foreground_window", lambda: (None, None))
    monkeypatch.setattr(platform_io, "game_window_info",
                        lambda names, titles=(): {"found": None, "foreground": None, "elevated": None})
    platform_io._found_cache.update(at=0.0, key=None, found=None)
    monkeypatch.setattr(online, "ACCOUNT_PATH", str(data / "account.json"))
    monkeypatch.setattr(online, "UPDATES_DIR", str(data / "updates"))
    monkeypatch.setattr(online, "DOWNLOADS_DIR", str(data / "downloads"))
    before = {n: _stamp(n) for n in _GUARDED}
    yield
    after = {n: _stamp(n) for n in _GUARDED}
    assert after == before, f"un test a modifié un fichier du projet : {[n for n in _GUARDED if before[n] != after[n]]}"
