# -*- coding: utf-8 -*-
"""Partage : ouverture d'adresses externes (liste blanche) et export du dessin en PNG (api/integrations.py)."""
import base64
import os
import threading
from collections import deque

import pytest

import core
import platform_io
import terms

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def api(monkeypatch):
    import app
    a = object.__new__(app.Api)
    a._cfg = core.load_config()
    terms.accept(a._cfg, terms.TERMS_VERSION, "fr")          # les deux methodes sont gardees par les CGU
    a._logs = deque(maxlen=50)
    a._toasts = deque(maxlen=10)
    a._toast_seq = 0
    a._ui_lock = threading.RLock()
    a._window = None
    a.opened, a.folders = [], []
    monkeypatch.setattr(platform_io, "open_url", lambda url: a.opened.append(url) or True)
    monkeypatch.setattr(platform_io, "open_folder", lambda path: a.folders.append(path))
    return a


@pytest.mark.parametrize("url", [
    "https://x.com/intent/post?text=Salut&url=https%3A%2F%2Fdodotopia.cyber-dodo.fr%2Ffr%2Fsalon%2FK7P2QD",
    "https://twitter.com/intent/tweet?text=a",
    "https://bsky.app/intent/compose?text=%C3%A9coute",
    "https://discord.com/channels/1",
    "https://discord.gg/abc",
    "https://dodotopia.cyber-dodo.fr/fr/galerie/3",
    "https://onlinesequencer.net/123",
    "https://www.onlinesequencer.net/123",
    "https://x.com:443/intent/post",
])
def test_open_external_accepte_la_liste_blanche(api, url):
    assert api.open_external(url) == {"ok": True, "error": None}
    assert api.opened == [url]


@pytest.mark.parametrize("url", [
    "http://x.com/intent/post",                     # pas https
    "https://evil.com/?x.com",
    "https://x.com.evil.com/",
    "https://notx.com/",
    "https://x.com@evil.com/",
    "https://user:pass@x.com/",
    "https://x.com:8443/",
    "javascript:alert(1)",
    "file:///C:/Windows/System32/calc.exe",
    "https://x.com/a b",
    "https://x.com/\\..\\",
    "https://x.com/\nhttps://evil.com",
    "",
    None,
    12,
    "https://" + "a" * 5000 + ".x.com/",
])
def test_open_external_refuse_le_reste(api, url):
    r = api.open_external(url)
    assert r == {"ok": False, "error": "not_allowed"}
    assert api.opened == []
    assert any(t["kind"] == "warn" for t in api._toasts)


def test_open_external_serveur_configure(api):
    api._cfg.setdefault("online", {})["server_url"] = "https://mon-serveur.example"
    assert api.open_external("https://mon-serveur.example/fr/salon/K7P2QD")["ok"]
    api._cfg["online"]["server_url"] = "http://localhost:8000"          # http : jamais ouvert
    assert not api.open_external("https://localhost:8000/")["ok"]


def _data_url(data):
    return "data:image/png;base64," + base64.b64encode(data).decode()


def test_save_drawing_png_ecrit_dans_exports(api):
    r = api.save_drawing_png(_data_url(PNG), "Mon chat")
    exports = os.path.join(core.DATA_DIR, "exports")
    assert r["ok"] and r["name"] == "Mon chat.png"
    assert os.path.dirname(r["path"]) == os.path.realpath(exports)
    with open(r["path"], "rb") as f:
        assert f.read() == PNG
    assert api.folders == [exports]
    r2 = api.save_drawing_png(_data_url(PNG), "Mon chat.png")        # meme nom : suffixe, rien d'ecrase
    assert r2["ok"] and r2["name"] == "Mon chat (2).png"


@pytest.mark.parametrize("name", ["../../evil", "..\\..\\evil", "C:\\Windows\\evil", "/etc/passwd", "CON", "",
                                  "a" * 400, "nul.png", "é\u202egnp.exe"])
def test_save_drawing_png_chemin_confine(api, name):
    r = api.save_drawing_png(_data_url(PNG), name)
    exports = os.path.realpath(os.path.join(core.DATA_DIR, "exports"))
    assert r["ok"], r
    assert os.path.dirname(os.path.realpath(r["path"])) == exports
    assert r["name"].endswith(".png") and "\u202e" not in r["name"]


@pytest.mark.parametrize("data_url, why", [
    ("data:image/jpeg;base64,/9j/4AAQ", "prefix"),
    ("data:image/svg+xml;base64,PHN2Zz4=", "prefix"),
    ("  data:image/png;base64,AAAA", "prefix"),
    ("data:image/png;base64,***", "base64"),
    (_data_url(b"GIF89a" + b"\x00" * 20), "png"),
    (None, "prefix"),
])
def test_save_drawing_png_refuse_un_contenu_invalide(api, data_url, why):
    r = api.save_drawing_png(data_url, "x")
    assert r == {"ok": False, "path": None, "name": None, "error": why}
    assert not os.path.exists(os.path.join(core.DATA_DIR, "exports", "x.png"))


def test_save_drawing_png_taille_maximale(api, monkeypatch):
    import api.integrations as integ
    monkeypatch.setattr(integ, "EXPORT_MAX_BYTES", 100)
    r = api.save_drawing_png(_data_url(PNG + b"\x00" * 200), "gros")
    assert r["error"] == "size" and not r["ok"]
    assert any("5 Mo" in t["msg"] for t in api._toasts)
