# -*- coding: utf-8 -*-
"""Liens dodotopia:// : validation stricte (deeplink.parse), ligne de commande, et traitement par l'Api
(demande de confirmation, attente des CGU, confirmation, refus, protocole Windows)."""
import os
import sys
import threading
import types
from collections import deque

import pytest

import core
import deeplink
import terms


# ---------------------------------------------------------------- formes acceptees
@pytest.mark.parametrize("url, expected", [
    ("dodotopia://song/12", {"action": "song", "id": 12}),
    ("dodotopia://song/12/", {"action": "song", "id": 12}),
    ("DODOTOPIA://Song/7", {"action": "song", "id": 7}),
    ("dodotopia://song/9007199254740991", {"action": "song", "id": 9007199254740991}),
    ("dodotopia://room/K7P2QD", {"action": "room", "code": "K7P2QD"}),
    ("dodotopia://room/k7p2qd", {"action": "room", "code": "K7P2QD"}),
    ("dodotopia://drawing/3", {"action": "drawing", "id": 3}),
    ("dodotopia://import?url=https%3A%2F%2Fonlinesequencer.net%2F123456",
     {"action": "import", "url": "https://onlinesequencer.net/123456", "host": "onlinesequencer.net"}),
    ("dodotopia://import?url=https://bitmidi.com/toto-mid",
     {"action": "import", "url": "https://bitmidi.com/toto-mid", "host": "bitmidi.com"}),
    ("dodotopia://import/?url=https%3A%2F%2Fwww.bitmidi.com%2Fuploads%2F1.mid",
     {"action": "import", "url": "https://www.bitmidi.com/uploads/1.mid", "host": "www.bitmidi.com"}),
    ("dodotopia://import?url=https%3A%2F%2Fexample.org%2Fmusique%2Fclair%2520de%2520lune.MIDI",
     {"action": "import", "url": "https://example.org/musique/clair%20de%20lune.MIDI", "host": "example.org"}),
    ("dodotopia://import?url=https%3A%2F%2FExample.ORG%3A443%2Fa.mid%3Fv%3D2",
     {"action": "import", "url": "https://example.org/a.mid?v=2", "host": "example.org"}),
])
def test_formes_valides(url, expected):
    assert deeplink.parse(url) == expected


# ---------------------------------------------------------------- tout le reste est refuse
REFUSED = [
    None, 12, b"dodotopia://song/1", "", "dodotopia://", "dodotopia:song/1", "dodotopia:/song/1",
    "dodotopia:///song/1", "http://song/1", "javascript:alert(1)", "file:///C:/Windows/win.ini",
    "dodotopia://javascript:alert(1)", "dodotopia://song", "dodotopia://song/", "dodotopia://song/0",
    "dodotopia://song/-1", "dodotopia://song/012", "dodotopia://song/1.5", "dodotopia://song/1e3",
    "dodotopia://song/99999999999999999", "dodotopia://song/12//", "dodotopia://song/12/x",
    "dodotopia://song/%31%32", "dodotopia://song/12?x=1", "dodotopia://song/12#top", "dodotopia://song/12?",
    "dodotopia://song/ 12", "dodotopia://song/12 ", " dodotopia://song/12", "dodotopia://song/12\n",
    "dodotopia://song/\u0661\u0662", "dodotopia://song/１２", "dodotopia://song/../room/K7P2QD",
    "dodotopia://song/..", "dodotopia://song\\12", "dodotopia://user@song/12", "dodotopia://song:80/12",
    "dodotopia://room/K7P2Q", "dodotopia://room/K7P2QDX", "dodotopia://room/K7P2Q0", "dodotopia://room/K7P2QI",
    "dodotopia://room/K7P2Q1", "dodotopia://room/K7P2QO", "dodotopia://room/K7P2Q%44", "dodotopia://room/K7P-QD",
    "dodotopia://room/", "dodotopia://drawing/abc", "dodotopia://settings/1", "dodotopia://song/12/../../x",
    "dodotopia://SONG\u0130/1",
    # import
    "dodotopia://import", "dodotopia://import?", "dodotopia://import?url=",
    "dodotopia://import?url=http%3A%2F%2Fbitmidi.com%2Fa.mid",
    "dodotopia://import?url=javascript%3Aalert(1)",
    "dodotopia://import?url=file%3A%2F%2F%2FC%3A%2Fa.mid",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2Fpage.html",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2F",
    "dodotopia://import?url=https%3A%2F%2Fbitmidi.com.evil.org%2Fx",
    "dodotopia://import?url=https%3A%2F%2Fevilbitmidi.com%2Fx",
    "dodotopia://import?url=https%3A%2F%2Fbitmidi.com%40evil.org%2Fx",
    "dodotopia://import?url=https%3A%2F%2Fuser%3Apass%40bitmidi.com%2Fx",
    "dodotopia://import?url=https%3A%2F%2Fbitmidi.com%3A8443%2Fx",
    "dodotopia://import?url=https%3A%2F%2F127.0.0.1%2Fa.mid",
    "dodotopia://import?url=https%3A%2F%2Flocalhost%2Fa.mid",
    "dodotopia://import?url=https%3A%2F%2F%5B%3A%3A1%5D%2Fa.mid",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2F..%2Fa.mid",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2F%252e%252e%2Fa.mid",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2F%2e%2e%2Fa.mid",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2Fa%255cb.mid",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2Fa.mid%23frag",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2Fa%00.mid",
    "dodotopia://import?url=https%3A%2F%2Fexample.org%2F%C3%A9.mid",
    "dodotopia://import?url=https%3A%2F%2Fbitmidi.com%2Fa&url=https%3A%2F%2Fbitmidi.com%2Fb",
    "dodotopia://import?url=https%3A%2F%2Fbitmidi.com%2Fa&x=1",
    "dodotopia://import?src=https%3A%2F%2Fbitmidi.com%2Fa",
    "dodotopia://import/x?url=https%3A%2F%2Fbitmidi.com%2Fa",
    "dodotopia://import?url=https%3A%2F%2Fbitmidi.com%2Fa#x",
    "dodotopia://import?url=https%3A%2F%2Fbitmidi.com%2Fa b",
    "dodotopia://import?url=https%3A%5C%5Cbitmidi.com%5Ca.mid",
    "dodotopia://import?url=https%3A%2F%2F" + "a" * 64 + ".com%2Fa.mid",
]


@pytest.mark.parametrize("url", REFUSED)
def test_formes_refusees(url):
    assert deeplink.parse(url) is None


def test_longueur_maximale():
    base = "dodotopia://import?url=https%3A%2F%2Fexample.org%2F"
    ok = base + "a" * (deeplink.MAX_LEN - len(base) - 4) + ".mid"
    assert len(ok) == deeplink.MAX_LEN and deeplink.parse(ok)
    assert deeplink.parse(ok[:-4] + "a.mid") is None
    assert deeplink.parse("dodotopia://song/1" + "/" * 5000) is None


def test_alphabet_identique_a_room():
    import room
    assert deeplink.CODE_ALPHABET == room.CODE_ALPHABET


def test_urls_de_la_ligne_de_commande():
    argv = ["--debug", "--url", "dodotopia://song/1", "--url=dodotopia://room/K7P2QD", "dodotopia://drawing/2",
            "--updated", "--url"]
    assert deeplink.urls_from_argv(argv) == ["dodotopia://song/1", "dodotopia://room/K7P2QD", "dodotopia://drawing/2"]
    assert deeplink.urls_from_argv([]) == [] and deeplink.urls_from_argv(None) == []


# ---------------------------------------------------------------- traitement par l'Api
class FakeRoom:
    def __init__(self):
        self.code = None
        self.calls = []

    def active(self):
        return self.code is not None

    def leave(self):
        self.calls.append(("leave",))
        self.code = None

    def status(self):
        return {"room": {"code": self.code, "players": [], "max_players": 8}}


class FakeOnline:
    def __init__(self, songs_folder):
        self._lock = threading.Lock()
        self.jobs = {"downloads": {}}
        self.downloads = []
        self.songs_folder = songs_folder

    def download(self, oid, import_cb=None):
        self.downloads.append(oid)
        with self._lock:
            self.jobs["downloads"][oid] = {"state": "done", "song_id": "Clair.mid"}
        return True

    def import_url(self, url, import_cb=None):
        self.imports = getattr(self, "imports", []) + [url]
        return "1"

    def open_drawing(self, drawing_id, on_loaded=None):
        self.opened = getattr(self, "opened", []) + [(drawing_id, on_loaded)]
        return 1


@pytest.fixture
def api(tmp_path):
    import app
    cfg = core.load_config()
    a = object.__new__(app.Api)
    a._cfg = cfg
    a._logs = deque(maxlen=50)
    a._toasts = deque(maxlen=10)
    a._toast_seq = 0
    a._ui_lock = threading.RLock()
    a._window = None
    a._tab = "image"
    songs = tmp_path / "songs"
    songs.mkdir()
    a._player = types.SimpleNamespace(state="stopped", songs=[str(songs / "Autre.mid"), str(songs / "Clair.mid")],
                                      songs_folder=str(songs), index=0)
    a._player.select = lambda i: setattr(a._player, "index", i)
    a._room = FakeRoom()
    a._online = FakeOnline(str(songs))
    a.joined = []
    a.modes = []
    a.get_state = lambda: {"deeplink": a._deeplink_state()}
    a.set_play_mode = lambda m: (a.modes.append(m), cfg["multi"].__setitem__("mode", m))
    a.room_join = lambda code: (a.joined.append(code), setattr(a._room, "code", code), a.get_state())[-1]
    return a


def _accept(cfg):
    terms.accept(cfg, terms.TERMS_VERSION, "fr")


def test_lien_invalide_toast_et_aucune_demande(api):
    _accept(api._cfg)
    r = api.handle_deeplink("javascript:alert(1)")
    assert r["ok"] is False and r["error"] == "invalid"
    assert api._deeplink_state() is None
    assert any(t["kind"] == "warn" for t in api._toasts)


def test_demande_de_confirmation_puis_salon(api):
    _accept(api._cfg)
    r = api.handle_deeplink("dodotopia://room/K7P2QD")
    req = r["deeplink"]
    assert r["ok"] and req["action"] == "room" and req["params"] == {"code": "K7P2QD"}
    assert req["label"] == "Rejoindre le salon K7P2QD ?"
    assert api.get_state()["deeplink"] == req
    assert api.joined == [], "un lien ne doit rien faire sans confirmation"
    api.deeplink_confirm(req["id"] + 1)                   # mauvaise demande : rien
    assert api.joined == [] and api.get_state()["deeplink"] == req
    st = api.deeplink_confirm(req["id"])
    assert api.joined == ["K7P2QD"] and api.modes == [] and st["deeplink"] is None, "le salon se déduit du salon rejoint"
    # deja dans ce salon : pas de nouvelle connexion
    req2 = api.handle_deeplink("dodotopia://room/K7P2QD")["deeplink"]
    api.deeplink_confirm(req2["id"])
    assert api.joined == ["K7P2QD"]
    # autre salon : on quitte d'abord
    req3 = api.handle_deeplink("dodotopia://room/ABCDEF")["deeplink"]
    api.deeplink_confirm(str(req3["id"]))
    assert ("leave",) in api._room.calls and api.joined[-1] == "ABCDEF"


def test_libelles_traduits(api):
    _accept(api._cfg)
    assert api.handle_deeplink("dodotopia://song/12")["deeplink"]["label"] == \
        "Ouvrir le morceau n° 12 de la bibliothèque partagée ?"
    assert api.handle_deeplink("dodotopia://import?url=https%3A%2F%2Fonlinesequencer.net%2F1")["deeplink"]["label"] == \
        "Importer un fichier MIDI depuis onlinesequencer.net ?"
    import i18n
    i18n.set_lang("en")
    assert api.get_state()["deeplink"]["label"] == "Import a MIDI file from onlinesequencer.net?"


def test_refus(api):
    _accept(api._cfg)
    req = api.handle_deeplink("dodotopia://drawing/4")["deeplink"]
    assert api.deeplink_dismiss(req["id"])["deeplink"] is None
    api.deeplink_confirm(req["id"])                       # demande deja retiree
    assert any("plus d'actualité" in t["msg"] for t in api._toasts)


def test_morceau_telecharge_puis_selectionne(api):
    _accept(api._cfg)
    req = api.handle_deeplink("dodotopia://song/12")["deeplink"]
    api.deeplink_confirm(req["id"])
    assert api._online.downloads == ["12"] and api._tab == "music"
    sid = api._select_when_downloaded("12", timeout=2, poll=0.01)
    assert sid == "Clair.mid" and api._player.index == 1


def test_import_et_dessin_branches(api):
    """import -> import par lien du client en ligne ; drawing -> grille recuperee pour l'activite Dessin."""
    _accept(api._cfg)
    req = api.handle_deeplink("dodotopia://import?url=https%3A%2F%2Fbitmidi.com%2Fx")["deeplink"]
    api.deeplink_confirm(req["id"])
    assert api._online.imports == ["https://bitmidi.com/x"] and api._tab == "music"
    req = api.handle_deeplink("dodotopia://drawing/2")["deeplink"]
    api.deeplink_confirm(req["id"])
    assert [d for d, _ in api._online.opened] == [2] and api._tab == "image"
    assert api._online.opened[0][1] == api._on_drawing_loaded
    msgs = [t["msg"] for t in api._toasts]
    assert "Import depuis bitmidi.com en cours…" in msgs and "Chargement du dessin partagé…" in msgs
    assert not any("bientôt" in m for m in msgs)


def test_liens_en_attente_des_cgu(api):
    assert terms.required(api._cfg)
    r = api.handle_deeplink("dodotopia://room/K7P2QD")
    assert r["pending"] is True and api._deeplink_state() is None
    for i in range(10):
        api.handle_deeplink(f"dodotopia://song/{i + 1}")
    assert len(api._pending_links) == 5
    # la confirmation elle-meme est gardee par les CGU
    assert api.deeplink_confirm(1)["error"] == "terms.required"
    api.accept_terms(terms.TERMS_VERSION, "fr")
    assert api._pending_links == []
    assert api.get_state()["deeplink"]["params"] == {"id": 10}      # le plus recent reste affiche


def test_arguments_relayes(api):
    _accept(api._cfg)
    calls = []

    class W:
        on_top = False

        def restore(self):
            calls.append("restore")

        def show(self):
            calls.append("show")

    api._window = W()
    api._on_forwarded_argv(["--url", "dodotopia://room/K7P2QD"])
    assert api.get_state()["deeplink"]["action"] == "room"
    assert calls == ["restore", "show"]


# ---------------------------------------------------------------- protocole Windows
class FakeWinreg(types.ModuleType):
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        super().__init__("winreg")
        self.values = {}

    class _Key:
        def __init__(self, reg, path):
            self.reg, self.path = reg, path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def CreateKey(self, root, path):
        return self._Key(self, path)

    def OpenKey(self, root, path):
        if not any(p == path for p, _ in self.values):
            raise OSError("absent")
        return self._Key(self, path)

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[(key.path, name)] = value

    def QueryValueEx(self, key, name):
        return self.values[(key.path, name)], self.REG_SZ


def test_enregistrement_du_protocole(api, monkeypatch):
    _accept(api._cfg)
    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert api.protocol_status() == {"registered": False, "command": "", "current": False}
    monkeypatch.setattr(core, "FROZEN", True)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\DodoTopia\DodoTopia.exe")
    assert api.register_protocol() == {"ok": True, "error": None}
    base = r"Software\Classes\dodotopia"
    assert fake.values[(base, "")] == "URL:DodoTopia"
    assert fake.values[(base, "URL Protocol")] == ""
    assert fake.values[(base + r"\DefaultIcon", "")] == r'"C:\Apps\DodoTopia\DodoTopia.exe",0'
    cmd = r'"C:\Apps\DodoTopia\DodoTopia.exe" --url "%1"'
    assert fake.values[(base + r"\shell\open\command", "")] == cmd
    assert api.protocol_status() == {"registered": True, "command": cmd, "current": True}


def test_commande_en_mode_sources(monkeypatch):
    import app
    monkeypatch.setattr(core, "FROZEN", False)
    cmd, icon = app.Api._protocol_command()
    assert cmd.endswith('app.py" --url "%1"') and os.path.join(core.RES_DIR, "app.py") in cmd
    assert icon.endswith("logo.ico")
