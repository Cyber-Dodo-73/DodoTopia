# -*- coding: utf-8 -*-
"""Tests de room.py : ClockSync synthétique, RoomSession contre le faux serveur (en mémoire, puis derrière
un vrai serveur `websockets` avec websocket-client)."""
import os
import random
import time

import pytest

import room as roommod
from room import ClockSync, RoomSession
from helpers import (FakeClient, FakePlayer, FakeServer, WsServer, add_song, fake_ws_factory, import_into,
                     wait_for)


# ---------------------------------------------------------------- horloge
def test_clocksync_synthetic():
    rng = random.Random(1)
    true = [1.7e12]
    local = [50_000.0]          # ms
    cs = ClockSync(now=lambda: local[0] / 1000.0)

    def sample():
        t0 = local[0]
        up = 20.0 + rng.lognormvariate(0.0, 0.7)
        down = 20.0 + rng.lognormvariate(0.0, 0.7)
        if rng.random() < 0.05:
            down += 400.0
        t1 = t0 + up + true[0]
        t2 = t1 + 0.2
        t3 = t2 + down - true[0]
        cs.add(t0, t1, t2, t3)
        local[0] += 100.0

    for _ in range(3):
        sample()
    assert not cs.valid()
    for _ in range(100):
        sample()
    assert cs.valid() and abs(cs.offset_ms - true[0]) < 3.0, (cs.offset_ms - true[0], cs.err_ms)
    assert cs.rtt_min_ms < 46 and cs.err_ms is not None and cs.rejected == 0
    # saut de +2 s (veille / reprise) : remise a zero puis nouvelle estimation juste
    true[0] += 2000.0
    sample()
    assert cs.resets == 1 and len(cs.samples) == 1
    for _ in range(40):
        sample()
    assert abs(cs.offset_ms - true[0]) < 3.0, cs.offset_ms - true[0]
    assert cs.resets == 1
    # rtt aberrant rejete, expiration
    assert cs.add(0, 1e12, 1e12, 5000) is False and cs.rejected == 1
    assert abs(cs.to_local(true[0] + local[0]) * 1000 - local[0]) < 3.0
    local[0] += 200_000.0
    assert not cs.valid() and cs.offset_ms is None and cs.status()["samples"] == 0


# ---------------------------------------------------------------- sessions contre le faux serveur
class Env:
    """Deux joueurs (A chef, B) avec un faux serveur ; `delays` -> faux transport avec délais."""

    def __init__(self, tmp_path, server=None, ws_url=None, factory=None, play_duration=0.3, **delays):
        self.server = server or FakeServer()
        self.notes = {"A": [], "B": []}
        self.sessions = {}
        for name in ("A", "B"):
            root = str(tmp_path / name)
            os.makedirs(root, exist_ok=True)
            p = FakePlayer(root, play_duration=play_duration)
            client = FakeClient(self.server, ws_url or "ws://fake/ws")
            s = RoomSession(client, p, p.cfg, None, log=lambda m, n=name: None,
                            notify=lambda m, k="info", n=name: self.notes[n].append((k, m)),
                            logfile=os.path.join(root, "salon.log"),
                            import_file=import_into(p), get_player_name=lambda n=name: n,
                            ws_factory=factory if factory is not None else (
                                None if ws_url else fake_ws_factory(self.server, **delays)))
            s.backoff = [0.1, 0.2]
            p.room = s
            self.sessions[name] = s
        self.A, self.B = self.sessions["A"], self.sessions["B"]
        self.pA, self.pB = self.A.player, self.B.player
        self.song = add_song(self.pA, "morceau.mid")

    def lobby(self):
        assert self.A.create()
        wait_for(lambda: self.A.state == "lobby" and self.A.code, what="A lobby")
        assert self.B.join(self.A.code.lower())
        wait_for(lambda: self.B.state == "lobby", what="B lobby")
        wait_for(lambda: len(self.A.players) == 2 and len(self.B.players) == 2, what="2 joueurs")
        wait_for(lambda: self.A.clock.valid() and self.B.clock.valid(), timeout=5, what="horloges")
        return self.A.code

    def choose_song(self):
        assert self.A.set_song("morceau.mid")
        wait_for(lambda: self.A.status()["room"]["me"]["has_file"] and self.B.status()["room"]["me"]["has_file"],
                 timeout=5, what="fichier chez les deux")
        wait_for(lambda: all(p.get("have_song") for p in self.A.players) and self.A.status()["room"]["can_start"],
                 what="serveur : tous ont le fichier")

    def close(self):
        for s in self.sessions.values():
            s.close()


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


def test_create_join_state(env):
    code = env.lobby()
    assert len(code) == 6 and env.A.is_host() and not env.B.is_host()
    st = env.A.status()
    assert st["mode"] == "room" and st["role"] == "host" and st["state"] == "lobby"
    assert st["room"]["code"] == code and st["room"]["connected"] and len(st["room"]["players"]) == 2
    assert st["room"]["clock"]["valid"] and abs(st["room"]["clock"]["offset_ms"] - env.server.true_offset_ms) < 5
    assert env.B.status()["role"] == "guest" and env.B.status()["room"]["start_blocker"] == ""
    assert env.A.status()["room"]["start_blocker"] == "Choisis d'abord une musique"
    assert env.pA.cfg["multi"]["last_room"] == code
    # ready
    env.B.set_ready(True)
    wait_for(lambda: env.A.me() and env.B.status()["room"]["me"]["ready"], what="B pret")
    wait_for(lambda: any(p["id"] == env.B.player_id and p["ready"] for p in env.A.players), what="A voit B pret")


def test_set_song_download_and_start(env):
    env.lobby()
    env.choose_song()
    song = env.A.song
    assert song["source"] == "room" and song["duration_ms"] > 0 and song["name"]
    assert env.B.client.downloads and env.pB.songs, "B a télécharge le fichier"
    assert env.pB.library.find_by_sha(song["sha256"]) is not None
    assert env.B.status()["room"]["song"]["sha256"] == song["sha256"]
    assert env.B.start() is False        # pas chef
    assert env.A.start()
    wait_for(lambda: env.A.state == "armed" and env.B.state == "armed", what="armes")
    assert env.pA.state == "sync" and env.pB.state == "sync"
    assert 0 < env.A.status()["seconds_left"] <= 1.0
    wait_for(lambda: env.pA.started_at is not None and env.pB.started_at is not None, timeout=3, what="depart")
    diff = abs(env.pA.started_at - env.pB.started_at)
    assert diff < 0.002, f"écart {diff * 1000:.2f} ms"
    assert abs(env.pA.started_at - env.A.clock.to_local(env.A.start_at_ms)) < 1e-3   # deadline figee a start ; l horloge continue d etre affinee
    assert env.pA.play_calls[0][1]["extra"] == song["key_shift"] and env.pA.play_calls[0][2] == "game"
    assert env.pA.speed == 1.0 and env.pA.lock_speed
    wait_for(lambda: env.A.state == "lobby" and env.B.state == "lobby", timeout=3, what="retour lobby")
    wait_for(lambda: env.server.room_of(env.A.code).state == "lobby", what="serveur lobby")
    assert env.pA.last_stop_reason == "" and not env.pA.lock_speed
    ended = {pid for pid, t, st in env.server.log if t == "player_state" and st == "ended"}
    assert ended == {env.A.player_id, env.B.player_id}


def test_net_offset_applied(env):
    env.lobby()
    env.choose_song()
    assert env.B.set_net_offset(-40) == -40
    assert env.B.set_net_offset("-999") == -300 and env.B.set_net_offset(-40) == -40
    assert env.A.start()
    wait_for(lambda: env.pA.started_at is not None and env.pB.started_at is not None, timeout=3, what="depart")
    diff = (env.pA.started_at - env.pB.started_at) * 1000
    assert 38 < diff < 42, f"écart {diff:.2f} ms"


def test_cancel_during_countdown(env):
    env.lobby()
    env.choose_song()
    assert env.A.start()
    wait_for(lambda: env.A.state == "armed" and env.B.state == "armed", what="armes")
    assert env.A.on_f6()          # chef pendant le compte a rebours : annule
    wait_for(lambda: env.A.state == "lobby" and env.B.state == "lobby", what="annule")
    assert env.pA.state == "stopped" and env.pB.state == "stopped"
    assert env.pB.last_stop_reason == "cancel" and env.pB.started_at is None
    time.sleep(1.2)
    assert env.pA.started_at is None and env.pB.started_at is None
    assert env.server.room_of(env.A.code).state == "lobby"
    assert env.A.status()["room"]["can_start"]


def test_synchronized_stop(tmp_path):
    e = Env(tmp_path, play_duration=5.0)
    try:
        e.lobby()
        e.choose_song()
        assert e.A.start()
        wait_for(lambda: e.A.state == "playing" and e.B.state == "playing", timeout=3, what="lecture")
        assert e.A.status()["state"] == "playing"
        assert e.B.stop() is False        # reserve au chef
        assert e.A.on_f6()                # chef en lecture : arret synchronise pour tout le monde
        wait_for(lambda: e.pA.stop_calls and e.pB.stop_calls, timeout=2, what="stops")
        assert abs(e.pA.stop_calls[0][1] - e.pB.stop_calls[0][1]) < 0.005
        assert e.pA.stop_calls[0][0] == "room_stop"
        wait_for(lambda: e.A.state == "lobby" and e.B.state == "lobby", what="lobby")
        assert e.server.room_of(e.A.code).state == "lobby"
    finally:
        e.close()


def test_local_abort_keystroke(env):
    env.lobby()
    env.choose_song()
    assert env.A.start()
    wait_for(lambda: env.B.state == "armed", what="B arme")
    env.pB.stop(reason="keyboard")     # Player.stop -> room.on_player_stop
    wait_for(lambda: env.B.state == "lobby", what="B annule localement")
    assert env.pB.state == "stopped" and env.pB.last_stop_reason == "keyboard"
    wait_for(lambda: env.pA.started_at is not None, timeout=3, what="A demarre quand meme")
    assert env.pB.started_at is None
    assert env.B.stop_local("stop") is False


def test_reconnect_keeps_seat_and_deadline(env):
    code = env.lobby()
    env.choose_song()
    pid = env.B.player_id
    assert env.A.start()
    wait_for(lambda: env.B.state == "armed", what="B arme")
    deadline = env.B.deadline
    env.server.drop_seat(code, pid)
    wait_for(lambda: not env.B.connected, what="B coupe")
    wait_for(lambda: env.B.connected and env.B.player_id == pid, timeout=5, what="B reconnecte")
    assert env.B.state == "armed" and env.B.deadline == deadline
    assert len(env.server.room_of(code).seats) == 2
    wait_for(lambda: env.pA.started_at is not None and env.pB.started_at is not None, timeout=3, what="depart")
    assert abs(env.pA.started_at - env.pB.started_at) < 0.002
    assert env.pB.started_at == deadline


def test_host_leaves_promotes(env):
    code = env.lobby()
    assert env.A.leave()
    wait_for(lambda: env.A.state == "idle", what="A parti")
    wait_for(lambda: env.B.is_host(), what="B promu")
    assert env.B.status()["role"] == "host" and len(env.B.players) == 1
    assert env.A.status()["state"] == "idle" and env.A.status()["room"]["last_room"] == code
    # A peut recreer un salon
    assert env.A.create()
    wait_for(lambda: env.A.state == "lobby" and env.A.code != code, what="nouveau salon")


def test_room_not_found_and_bad_state(env):
    assert env.B.join("zz") is False
    assert env.B.join("ZZZZZZ")
    wait_for(lambda: env.B.state == "idle" and env.notes["B"], what="refus")
    assert any("introuvable" in m for _, m in env.notes["B"])
    assert env.B.on_f6() is False and env.B.set_song("x") is False


def test_late_joiner_waits(tmp_path):
    e = Env(tmp_path, play_duration=2.0)
    try:
        assert e.A.create()
        wait_for(lambda: e.A.state == "lobby", what="A lobby")
        wait_for(lambda: e.A.clock.valid(), what="horloge A")
        assert e.A.set_song(e.song)
        wait_for(lambda: e.A.status()["room"]["can_start"], what="pret")
        assert e.A.start()
        wait_for(lambda: e.server.room_of(e.A.code).state == "playing", timeout=3, what="serveur en lecture")
        assert e.B.join(e.A.code)
        wait_for(lambda: e.B.state == "lobby" and e.B.room_state == "playing", what="B attend")
        assert "attends" in e.B.message
        assert e.B.on_f6() is False
        wait_for(lambda: e.B.status()["room"]["me"]["has_file"], timeout=5, what="B a le fichier")
        assert not any(p["have_song"] for p in e.B.players if p["id"] == e.B.player_id), "song_status differe"
        wait_for(lambda: e.A.state == "lobby" and e.B.room_state == "lobby", timeout=5, what="fin")
        wait_for(lambda: any(p["have_song"] for p in e.B.players if p["id"] == e.B.player_id), what="B annonce le fichier")
        assert e.server.room_of(e.A.code).state == "lobby"
    finally:
        e.close()


def test_with_network_delay(tmp_path):
    """Delai 30 ms aller, 30 ms retour, gigue 0-20 ms : ecart < 8 ms."""
    e = Env(tmp_path, delay_up_ms=30, delay_down_ms=30, jitter_ms=20)
    try:
        e.lobby()
        e.choose_song()
        assert e.A.start()
        wait_for(lambda: e.pA.started_at is not None and e.pB.started_at is not None, timeout=4, what="depart")
        diff = abs(e.pA.started_at - e.pB.started_at) * 1000
        assert diff < 8, f"écart {diff:.2f} ms"
        for s in (e.A, e.B):
            st = s.clock.status()
            assert 55 <= st["rtt_ms"] <= 85 and abs(st["offset_ms"] - e.server.true_offset_ms) < 8
    finally:
        e.close()


def test_real_websockets_server(tmp_path):
    """Chaine complete : websocket-client (vrai) <-> serveur `websockets` local."""
    pytest.importorskip("websocket")
    pytest.importorskip("websockets")
    server = FakeServer()
    ws = WsServer(server)
    e = Env(tmp_path, server=server, ws_url=ws.url)
    try:
        e.lobby()
        e.choose_song()
        assert e.A.start()
        wait_for(lambda: e.pA.started_at is not None and e.pB.started_at is not None, timeout=4, what="depart")
        diff = abs(e.pA.started_at - e.pB.started_at) * 1000
        assert diff < 5, f"écart {diff:.2f} ms"
        wait_for(lambda: e.A.state == "lobby" and e.B.state == "lobby", timeout=3, what="lobby")
        assert e.B.leave()
        wait_for(lambda: e.B.state == "idle", what="B parti")
        wait_for(lambda: len(e.A.players) == 1, what="A seul")
    finally:
        e.close()
        ws.close()


def test_normalize_code():
    assert roommod.normalize_code(" ab-cd ef ") == "ABCDEF"
    assert roommod.normalize_code(None) == ""

def test_stop_request_host_stops_everyone(tmp_path):
    """F7 / bouton Arreter : le chef coupe tout le salon, un invite ne coupe que lui."""
    e = Env(tmp_path, play_duration=5.0)
    try:
        e.lobby()
        e.choose_song()
        assert e.A.start()
        wait_for(lambda: e.A.state == "playing" and e.B.state == "playing", timeout=3, what="lecture")

        # invite : arret local seulement, le chef continue
        assert e.B.stop_request("stop") is False       # pas de diffusion
        wait_for(lambda: e.pB.stop_calls, timeout=2, what="arret de B")
        assert not e.pA.stop_calls                     # le chef joue toujours
        assert e.A.state == "playing"

        # chef : arret diffuse (le Player n'est pas coupe par stop_request, le serveur fixe l'instant)
        assert e.A.stop_request("stop") is True
        wait_for(lambda: e.pA.stop_calls, timeout=2, what="arret de A")
        assert e.pA.stop_calls[0][0] == "room_stop"
        wait_for(lambda: e.A.state == "lobby", what="lobby")
    finally:
        e.close()
