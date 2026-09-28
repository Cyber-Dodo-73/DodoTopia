# -*- coding: utf-8 -*-
"""Overlay au-dessus du jeu (api/overlay.py) : contenu selon l'activite, affichage seulement jeu devant +
musique ou dessin en cours, placement dans le coin choisi. La fenetre elle-meme (styles Windows : clics qui
traversent, jamais de focus, invisible aux captures) a ete verifiee a la main sur Windows 11 ; ici on teste la
logique, sans fenetre."""
import time
from types import SimpleNamespace as NS

import pytest

import i18n
import platform_io
from api import overlay as ov


class Idle:
    def active(self):
        return False


class FakeRoom(Idle):
    def __init__(self, state="idle", **kw):
        self.state = state
        self.code = "ABCD"
        self.song = {"name": "Valse", "duration_ms": 120000}
        self.deadline = None
        self.players = [{}, {}, {}]
        self.host = False
        self.rejoin = None
        self.__dict__.update(kw)

    def active(self):
        return self.state != "idle"

    def is_host(self):
        return self.host

    def rejoin_position(self):
        return self.rejoin


class FakePlayer:
    def __init__(self, state="stopped", target="game", pos=0.0, duration=100.0, start=None):
        self.state, self.target, self._pos, self.duration, self._start_time = state, target, pos, duration, start

    def position(self):
        return self._pos

    def current(self):
        return "C:/songs/Au clair de la lune.mid"


class FakeDrawer:
    def __init__(self, state="idle", countdown=0.0, done=0, total=0, progress_msg=""):
        self.state, self.countdown, self.done, self.total, self.progress_msg = state, countdown, done, total, progress_msg

    def status(self):
        return {"eta": 65.0, "elapsed": 10.0}


class O(ov.OverlayMixin):
    def __init__(self, player=None, drawer=None, room=None, sync=None):
        self._cfg = {"hotkeys": {"play_pause": "F6", "stop": "F7"}, "game_process": "xdt.exe"}
        self._player = player or FakePlayer()
        self._drawer = drawer or FakeDrawer()
        self._room = room or FakeRoom()
        self._sync = sync or Idle()

    def _log(self, msg):
        pass


@pytest.fixture(autouse=True)
def fr():
    i18n.set_lang("fr")


def test_rien_ne_tourne_rien_a_afficher():
    assert O()._overlay_content() is None
    # ecoute dans le logiciel : pas dans le jeu, pas d'overlay
    assert O(player=FakePlayer("playing", target="preview"))._overlay_content() is None


def test_musique_solo_dans_le_jeu():
    c = O(player=FakePlayer("playing", pos=30.0, duration=120.0))._overlay_content()
    assert c["kind"] == "music" and c["title"] == "Au clair de la lune"
    assert c["progress"]["left"] == "0:30" and c["progress"]["right"] == "2:00"
    assert abs(c["progress"]["pct"] - 25.0) < 0.01
    assert "F6" in c["meta"] and "F7" in c["meta"]
    # compte a rebours avant la premiere note
    c = O(player=FakePlayer("playing", start=time.perf_counter() + 2.2))._overlay_content()
    assert c["count"].startswith("3")


def test_dessin_compte_a_rebours_puis_progression():
    c = O(drawer=FakeDrawer("drawing", countdown=2.4))._overlay_content()
    assert c["kind"] == "draw" and c["count"].startswith("3") and c["progress"] is None
    c = O(drawer=FakeDrawer("drawing", done=250, total=1000, progress_msg="Couleur 2/5"))._overlay_content()
    assert c["title"] == "Couleur 2/5" and c["count"] == "25 %"
    assert "250" in c["progress"]["left"] and c["progress"]["right"] == "1:05"


def test_salon_depart_lecture_et_rejoindre():
    now = time.perf_counter()
    c = O(room=FakeRoom("armed", deadline=now + 4.5))._overlay_content()
    assert c["kind"] == "room" and "ABCD" in c["role"] and c["count"].startswith("5") and c["title"] == "Valse"
    c = O(room=FakeRoom("playing"), player=FakePlayer("playing", pos=60.0))._overlay_content()
    assert c["progress"]["right"] == "2:00" and abs(c["progress"]["pct"] - 50) < 0.01 and "3" in c["count"]
    c = O(room=FakeRoom("lobby", rejoin=30.0))._overlay_content()
    assert c["progress"]["left"] == "0:30" and "F6" in c["meta"]
    # dans le salon mais rien ne joue : rien
    assert O(room=FakeRoom("lobby"))._overlay_content() is None


def test_affiche_seulement_quand_le_jeu_est_devant(monkeypatch):
    o = O(player=FakePlayer("playing", pos=5.0))
    for front, shown in ((True, True), (False, False), (None, False)):
        monkeypatch.setattr(platform_io, "game_in_front", lambda gp, f=front: f)
        assert (o._overlay_visible_content() is not None) is shown, front
    monkeypatch.setattr(platform_io, "game_in_front", lambda gp: True)
    o._cfg["overlay"] = {"enabled": False}
    assert o._overlay_visible_content() is None
    # jeu devant mais rien ne tourne
    assert O()._overlay_visible_content() is None


def test_placement_dans_le_coin_de_la_fenetre_du_jeu():
    game = (100, 50, 2020, 1130)
    assert ov.overlay_rect(game, 1.0, "top-right") == (2020 - 340 - 16, 66, 340, 104)
    assert ov.overlay_rect(game, 1.0, "top-left") == (116, 66, 340, 104)
    assert ov.overlay_rect(game, 1.5, "bottom-left") == (124, 1130 - 156 - 24, 510, 156)
    x, y, w, h = ov.overlay_rect(game, 1.0, "top-center")
    assert x == (100 + 2020 - 340) // 2


def test_boucle_affiche_place_et_cache(monkeypatch):
    o = O(player=FakePlayer("playing", pos=5.0))
    o._cfg["overlay"] = {"enabled": True, "corner": "top-left"}
    calls = []
    monkeypatch.setattr(platform_io, "game_in_front", lambda gp: True)
    monkeypatch.setattr(platform_io, "foreground_rect", lambda: ((0, 0, 1920, 1080), 1.0))
    monkeypatch.setattr(platform_io, "overlay_show", lambda h, *r: calls.append(("show", r)))
    monkeypatch.setattr(platform_io, "overlay_hide", lambda h: calls.append(("hide",)))
    js = []
    o._ov_window = NS(run_js=js.append)
    o._ov_hwnd, o._ov_shown, o._ov_last, o._ov_place, o._ov_placed_at = 1, False, None, None, 0.0
    o._overlay_tick()
    assert calls == [("show", (16, 16, 340, 104))] and js and "render(" in js[0]
    assert js[1:] == ["window.appear && appear()"], "l'apparition est animee a chaque affichage"
    o._overlay_tick()                         # rien de change : ni nouveau rendu, ni nouveau placement
    assert len(js) == 2 and len(calls) == 1
    o._player.state = "stopped"
    o._overlay_tick()
    assert calls[-1] == ("hide",)
