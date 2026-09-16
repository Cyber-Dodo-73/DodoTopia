# -*- coding: utf-8 -*-
"""Discord Rich Presence : faux module pypresence, horloge controlee. Au plus une mise a jour toutes les 15 s,
seulement au changement, effacement au repos, reconnexion avec attente croissante, Discord absent ou
pypresence absent sans exception ni journal repete ; construction de l'activite depuis l'Api."""
import logging
import sys
import types

import pytest

import presence


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakePresence:
    instances = []
    fail_connect = 0          # nombre de connexions a faire echouer
    fail_update = False

    def __init__(self, client_id, **kw):
        self.client_id = client_id
        self.kw = kw
        self.updates = []
        self.clears = 0
        self.closed = False
        FakePresence.instances.append(self)

    def connect(self):
        if FakePresence.fail_connect:
            FakePresence.fail_connect -= 1
            raise ConnectionRefusedError("Discord n'est pas lancé")

    def update(self, **kw):
        if FakePresence.fail_update:
            raise BrokenPipeError("tube fermé")
        self.updates.append(kw)

    def clear(self):
        self.clears += 1

    def close(self):
        self.closed = True


@pytest.fixture
def fake_pypresence(monkeypatch):
    FakePresence.instances = []
    FakePresence.fail_connect = 0
    FakePresence.fail_update = False
    mod = types.ModuleType("pypresence")
    mod.Presence = FakePresence
    monkeypatch.setitem(sys.modules, "pypresence", mod)
    return mod


PLAY = {"kind": "play", "title": "Clair de lune", "instrument": "Piano", "started_at": 1700000000}


def test_une_mise_a_jour_par_15_s_et_seulement_au_changement(fake_pypresence):
    clock = Clock()
    rp = presence.RichPresence(client_id="123", clock=clock)
    rp.update(PLAY)
    rp.tick()
    rpc = FakePresence.instances[0]
    assert rpc.client_id == "123"
    assert rpc.updates == [{"large_image": "logo", "large_text": "DodoTopia", "details": "Joue Clair de lune",
                            "state": "Piano dans Heartopia", "start": 1700000000}]
    for _ in range(20):                       # meme activite, appels repetes : rien
        rp.update(dict(PLAY))
        clock.t += 1
        rp.tick()
    assert len(rpc.updates) == 1
    clock.t = 2000.0
    rp.update(dict(PLAY, title="A"))
    rp.tick()
    rp.update(dict(PLAY, title="B"))
    clock.t += 5
    rp.tick()
    assert [u["details"] for u in rpc.updates] == ["Joue Clair de lune", "Joue A"]
    clock.t += 9.9
    rp.tick()
    assert len(rpc.updates) == 2, "moins de 15 s depuis la dernière mise à jour"
    clock.t += 0.2
    rp.tick()
    assert rpc.updates[-1]["details"] == "Joue B"


def test_effacement_au_repos(fake_pypresence):
    clock = Clock()
    rp = presence.RichPresence(client_id="123", clock=clock)
    rp.update(PLAY)
    rp.tick()
    rpc = FakePresence.instances[0]
    rp.update({"kind": "idle"})
    clock.t += 3
    rp.tick()
    assert rpc.clears == 0
    clock.t += 15
    rp.tick()
    assert rpc.clears == 1
    clock.t += 60
    rp.update(None)
    rp.tick()
    assert rpc.clears == 1, "déjà effacée : pas de nouvel envoi"
    rp.close()
    assert rpc.closed


def test_discord_absent_reconnexion_croissante_sans_spam(fake_pypresence, caplog):
    caplog.set_level(logging.INFO, logger="presence")
    clock = Clock()
    FakePresence.fail_connect = 100
    rp = presence.RichPresence(client_id="123", clock=clock)
    rp.update(PLAY)
    attempts = []
    for _ in range(600):                      # 10 minutes, une etape par seconde
        before = len(FakePresence.instances)
        rp.tick()
        if len(FakePresence.instances) != before:
            attempts.append(clock.t)
        clock.t += 1
    gaps = [b - a for a, b in zip(attempts, attempts[1:])]
    assert gaps[:5] == [2, 4, 8, 16, 32]
    assert max(gaps) == 60 and all(g <= 60 for g in gaps)
    assert len([r for r in caplog.records if r.name == "presence"]) == 1, "un seul message pour Discord absent"
    # Discord demarre : connexion et envoi immediat
    FakePresence.fail_connect = 0
    clock.t += 61
    rp.tick()
    assert FakePresence.instances[-1].updates and not rp._backoff


def test_discord_ferme_pendant_l_envoi(fake_pypresence):
    clock = Clock()
    rp = presence.RichPresence(client_id="123", clock=clock)
    rp.update(PLAY)
    rp.tick()
    FakePresence.fail_update = True
    rp.update(dict(PLAY, title="X"))
    clock.t += 20
    rp.tick()                                 # echec : deconnexion, pas d'exception
    assert not rp.connected and FakePresence.instances[0].closed
    FakePresence.fail_update = False
    clock.t += 3
    rp.tick()
    assert rp.connected and FakePresence.instances[-1].updates[-1]["details"] == "Joue X"


def test_pypresence_absent(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="presence")
    monkeypatch.setitem(sys.modules, "pypresence", None)     # import pypresence -> ImportError
    rp = presence.RichPresence(client_id="123", clock=Clock())
    rp.update(PLAY)
    for _ in range(50):
        rp.tick()
    assert not rp.connected
    assert len([r for r in caplog.records if r.name == "presence"]) == 1


def test_sans_identifiant_rien_ne_demarre(fake_pypresence):
    rp = presence.RichPresence(client_id="")
    assert rp.start() is False and not rp.running()
    rp.update(PLAY)
    rp.tick()
    assert FakePresence.instances == []
    assert presence.DISCORD_CLIENT_ID == "" or presence.DISCORD_CLIENT_ID.isdigit()


def test_fil_demarre_et_s_arrete(fake_pypresence):
    rp = presence.RichPresence(client_id="123")
    assert rp.start() and rp.running()
    rp.update(PLAY)
    import time
    end = time.monotonic() + 3
    while time.monotonic() < end and not (FakePresence.instances and FakePresence.instances[0].updates):
        time.sleep(0.02)
    assert FakePresence.instances[0].updates
    loop = FakePresence.instances[0].kw.get("loop")
    assert loop is not None, "boucle asyncio propre au fil (pypresence hors du fil principal)"
    rp.close()
    assert not rp.running() and FakePresence.instances[0].clears == 1 and FakePresence.instances[0].closed


# ---------------------------------------------------------------- activites
def test_activites():
    b = presence.build_activity
    assert b({"kind": "idle"}) is None and b(None) is None
    assert b({"kind": "draw", "started_at": 5})["details"] == "Dessine dans Heartopia"
    cook = b({"kind": "cook", "dishes": 3})
    assert cook["details"] == "Cuisine dans Heartopia" and cook["state"] == "3 plats cuisinés"
    assert "state" not in b({"kind": "cook", "dishes": 0})
    room = b({"kind": "room", "players": 3, "max_players": 8, "room_code": "K7P2QD",
              "server_url": "https://dodotopia.cyber-dodo.fr/"})
    assert room["state"] == "Dans un salon (3/8)"
    assert room["buttons"] == [{"label": "Rejoindre", "url": "https://dodotopia.cyber-dodo.fr/salon/K7P2QD"}]
    no_btn = b({"kind": "room", "players": 1, "room_code": "K7P2QD", "server_url": "http://localhost:8000"})
    assert "buttons" not in no_btn
    import i18n
    i18n.set_lang("en")
    assert b(PLAY)["details"] == "Playing Clair de lune"


def test_url_d_invitation():
    f = presence.room_invite_url
    assert f("https://site.fr", "k7p2qd") == "https://site.fr/salon/K7P2QD"
    assert f("https://site.fr/", "K7P2QD") == "https://site.fr/salon/K7P2QD"
    assert f("http://site.fr", "K7P2QD") == ""
    assert f("https://site.fr", "K7P2Q0") == "" and f("https://site.fr", "../x") == "" and f("", "K7P2QD") == ""


# ---------------------------------------------------------------- branchement dans l'Api
def _api_stub(monkeypatch):
    import threading
    from collections import deque

    import app
    import core
    cfg = core.load_config()
    a = object.__new__(app.Api)
    a._cfg = cfg
    a._logs = deque(maxlen=50)
    a._toasts = deque(maxlen=10)
    a._toast_seq = 0
    a._ui_lock = threading.RLock()
    inst = types.SimpleNamespace(name="Piano", label_en="Piano (en)")
    a._player = types.SimpleNamespace(state="stopped", target="preview", songs=["x/Clair.mid"], index=0,
                                      instrument=inst, current=lambda: "x/Clair.mid")
    a._room = types.SimpleNamespace(active=lambda: False, status=lambda: {"room": {}})
    a._drawer = types.SimpleNamespace(state="idle")
    a._cook = types.SimpleNamespace(state="idle", dishes=0)
    return a


def test_instantane_de_l_api(monkeypatch):
    a = _api_stub(monkeypatch)
    songs = [{"name": "Clair de lune"}]
    assert a._activity_snapshot(songs)["kind"] == "idle"
    a._player.state = "playing"
    assert a._activity_snapshot(songs)["kind"] == "idle", "l'écoute dans le logiciel n'est pas une activité de jeu"
    a._player.target = "game"
    snap = a._activity_snapshot(songs)
    assert snap["kind"] == "play" and snap["title"] == "Clair de lune" and snap["instrument"] == "Piano"
    started = snap["started_at"]
    assert started and a._activity_snapshot(songs)["started_at"] == started
    a._player.state = "stopped"
    a._cook.state, a._cook.dishes = "cooking", 4
    snap = a._activity_snapshot(songs)
    assert snap["kind"] == "cook" and snap["dishes"] == 4
    a._room = types.SimpleNamespace(active=lambda: True, status=lambda: None)
    snap = a._activity_snapshot(songs, {"room": {"code": "K7P2QD", "players": [{}, {}], "max_players": 8}})
    assert snap["kind"] == "room" and snap["players"] == 2 and snap["room_code"] == "K7P2QD"


def test_reglage_demarre_et_arrete(monkeypatch, fake_pypresence):
    a = _api_stub(monkeypatch)
    a._presence = None
    monkeypatch.setattr(presence, "DISCORD_CLIENT_ID", "")
    a._on_rich_presence()
    assert a._presence is None, "identifiant vide : désactivé"
    monkeypatch.setattr(presence, "DISCORD_CLIENT_ID", "42")
    a._cfg.setdefault("online", {})["rich_presence"] = True
    a._on_rich_presence()
    assert a._presence is not None and a._presence.running()
    pres = a._presence
    a._cfg["online"]["rich_presence"] = False
    a._on_rich_presence()
    assert a._presence is None and not pres.running()
    a._integrations_close()
