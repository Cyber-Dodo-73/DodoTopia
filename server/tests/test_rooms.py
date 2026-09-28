"""Protocole des salons (WebSocket /ws) et fichier éphémère REST."""
import hashlib
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app.rooms import ALPHABET, normalize_code, parse_version, srv_ms
from conftest import bearer, login, make_client, make_settings

V = "1.7.0"
SHA = "a" * 64
SONG = {"type": "set_song", "sha256": SHA, "name": "Métronome", "duration_ms": 30000, "key_shift": 2,
        "source": "library", "online_id": 7}


def create(ws, token, name="A", **extra):
    ws.send_json({"type": "create", "token": token, "name": name, "instrument": "piano", "version": V, **extra})
    joined = ws.receive_json()
    assert joined["type"] == "joined", joined
    state = ws.receive_json()
    assert state["type"] == "state"
    return joined, state


def join(ws, token, code, name="B", **extra):
    ws.send_json({"type": "join", "token": token, "room_code": code, "name": name, "instrument": "flute",
                  "version": V, **extra})
    joined = ws.receive_json()
    assert joined["type"] == "joined", joined
    state = ws.receive_json()
    assert state["type"] == "state"
    return joined, state


def until(ws, kind, **match):
    """Lit jusqu'au premier message du type voulu dont les champs `match` correspondent."""
    for _ in range(50):
        msg = ws.receive_json()
        if msg["type"] == kind and all(msg.get(k) == v for k, v in match.items()):
            return msg
    raise AssertionError(f"message {kind} {match} jamais reçu")


def player(state, pid):
    return next(p for p in state["players"] if p["id"] == pid)


@pytest.fixture
def tokens(client):
    return login(client, "111")[0], login(client, "222")[0], login(client, "999")[0]


def test_helpers():
    assert parse_version("1.7.0") == (1, 7, 0) and parse_version("dev") == (0,)
    assert parse_version("1.10.0") > parse_version("1.9.9")
    assert normalize_code(" ab-cd 23 ") == "ABCD23"
    assert "O" not in ALPHABET and "0" not in ALPHABET and "I" not in ALPHABET and "1" not in ALPHABET


def test_create_join_broadcast_and_ping(client, tokens):
    a, b, _ = tokens
    with client.websocket_connect("/ws") as wa:
        joined, state = create(wa, a)
        code = joined["room_code"]
        assert len(code) == 6 and set(code) <= set(ALPHABET)
        assert joined["host"] is True and joined["player_id"] == 1 and joined["seat_token"]
        assert joined["min_version"] == "1.7.0"
        assert state["state"] == "lobby" and state["host_id"] == 1 and state["max_players"] == 8
        assert state["song"] is None and [p["id"] for p in state["players"]] == [1]
        assert state["players"][0]["name"] == "A" and state["players"][0]["connected"] is True
        assert state["players"][0]["avatar"].startswith("https://cdn.discordapp.com/")
        assert client.get("/api/health").json()["rooms"] == 1

        with client.websocket_connect("/ws") as wb:
            joined_b, state_b = join(wb, b, code.lower())
            assert joined_b["host"] is False and joined_b["player_id"] == 2
            assert [p["id"] for p in state_b["players"]] == [1, 2]
            # A reçoit le nouvel état (broadcast)
            st = until(wa, "state")
            assert st["seq"] == state_b["seq"] and len(st["players"]) == 2
            assert player(st, 2)["instrument"] == "flute" and player(st, 2)["host"] is False

            # ping/pong cohérent avec l'horloge serveur
            t0 = 123.5
            wb.send_json({"type": "ping", "t0": t0})
            pong = wb.receive_json()
            assert pong["type"] == "pong" and pong["t0"] == t0
            assert pong["t1"] <= pong["t2"] <= srv_ms() + 1
            assert abs(pong["t1"] - state_b["server_now_ms"]) < 5000

            # set_instrument diffusé
            wb.send_json({"type": "set_instrument", "instrument": "lute"})
            assert player(until(wb, "state"), 2)["instrument"] == "lute"
            assert player(until(wa, "state"), 2)["instrument"] == "lute"


def test_song_status_ready_start_cancel_stop(client, tokens):
    a, b, _ = tokens
    with client.websocket_connect("/ws") as wa, client.websocket_connect("/ws") as wb:
        code = create(wa, a)[0]["room_code"]
        join(wb, b, code)
        until(wa, "state")

        # seul le chef choisit le morceau
        wb.send_json(SONG)
        err = wb.receive_json()
        assert err["type"] == "error" and err["code"] == "not_host" and err["fatal"] is False

        wa.send_json(SONG)
        st = until(wa, "state")
        assert st["song"]["sha256"] == SHA and st["song"]["key_shift"] == 2 and st["song"]["online_id"] == 7
        assert all(p["have_song"] is False and p["status"] == "no_song" for p in st["players"])
        until(wb, "state", song=st["song"])

        # start refusé tant que tout le monde n'a pas le fichier
        wa.send_json({"type": "song_status", "sha256": SHA, "have": True})
        until(wa, "state")
        until(wb, "state")
        wa.send_json({"type": "start"})
        err = wa.receive_json()
        assert err["type"] == "error" and err["code"] == "not_all_have_song"

        wb.send_json({"type": "song_status", "sha256": SHA, "have": True})
        wb.send_json({"type": "ready", "ready": True})
        until(wa, "state")
        st = until(wa, "state")
        assert player(st, 2)["have_song"] is True and player(st, 2)["ready"] is True
        until(wb, "state")
        until(wb, "state")

        # start : reçu par tous avec start_at_ms ≈ now + countdown
        before = srv_ms()
        wa.send_json({"type": "start", "countdown_s": 4})
        sa = until(wa, "start")
        sb = until(wb, "start")
        assert sa["start_at_ms"] == sb["start_at_ms"] and sa["countdown_s"] == 4 and sa["by"] == 1
        assert before + 4000 - 50 <= sa["start_at_ms"] <= srv_ms() + 4000 + 50
        assert sa["song"]["sha256"] == SHA and [p["status"] for p in sa["players"]] == ["armed", "armed"]
        st = until(wa, "state")
        assert st["state"] == "countdown" and st["start_at_ms"] == sa["start_at_ms"] and st["countdown_s"] == 4
        until(wb, "state", state="countdown")

        # bad_state : pas de deuxième start ni de ready pendant le compte à rebours
        wa.send_json({"type": "start"})
        assert wa.receive_json()["code"] == "bad_state"
        wb.send_json({"type": "ready", "ready": False})
        assert wb.receive_json()["code"] == "bad_state"

        # cancel (chef seulement)
        wb.send_json({"type": "cancel"})
        assert wb.receive_json()["code"] == "not_host"
        wa.send_json({"type": "cancel"})
        c = until(wa, "cancelled")
        assert c["by"] == 1
        st = until(wa, "state")
        assert st["state"] == "lobby" and st["start_at_ms"] is None
        assert all(p["ready"] is False for p in st["players"])
        until(wb, "cancelled")
        until(wb, "state", state="lobby")

        # countdown bornés 3..15, défaut 5, puis stop synchronisé
        wa.send_json({"type": "start", "countdown_s": 99})
        assert until(wa, "start")["countdown_s"] == 15
        until(wb, "start")
        until(wa, "state")
        until(wb, "state")
        t = srv_ms()
        wa.send_json({"type": "stop"})
        s = until(wa, "stop")
        assert s["by"] == 1 and t + 200 <= s["at_ms"] <= srv_ms() + 300
        assert until(wa, "state")["state"] == "lobby"
        assert until(wb, "stop")["at_ms"] == s["at_ms"]
        until(wb, "state", state="lobby")
        wa.send_json({"type": "stop"})
        assert wa.receive_json()["code"] == "bad_state"

        wa.send_json({"type": "start", "force": False})
        assert until(wa, "start")["countdown_s"] == 5


def test_force_start_and_player_state_ends_round(client, tokens, app):
    a, b, _ = tokens
    with client.websocket_connect("/ws") as wa, client.websocket_connect("/ws") as wb:
        code = create(wa, a)[0]["room_code"]
        join(wb, b, code)
        until(wa, "state")
        wa.send_json(SONG)
        until(wa, "state")
        until(wb, "state")
        wa.send_json({"type": "song_status", "sha256": SHA, "have": True})
        until(wa, "state")
        until(wb, "state")
        wa.send_json({"type": "start", "force": True, "countdown_s": 3})
        s = until(wa, "start")
        assert [p["status"] for p in s["players"]] == ["armed", "no_song"]
        until(wb, "start")
        until(wa, "state")
        until(wb, "state")

        # on force l'état playing (sans attendre le compte à rebours) : tous les joueurs actifs ont fini -> lobby
        room = app.state.rooms.get(code)
        room.state = "playing"
        wa.send_json({"type": "player_state", "status": "playing"})
        assert player(until(wa, "state"), 1)["status"] == "playing"
        until(wb, "state")
        wa.send_json({"type": "player_state", "status": "ended"})
        st = until(wa, "state")
        assert st["state"] == "lobby" and player(st, 1)["status"] == "idle"
        until(wb, "state", state="lobby")


def test_room_full_and_not_found(client, tokens):
    a, b, c = tokens
    with client.websocket_connect("/ws") as wa:
        code = create(wa, a, max_players=2)[0]["room_code"]
        with client.websocket_connect("/ws") as wb:
            join(wb, b, code)
            until(wa, "state")
            with client.websocket_connect("/ws") as wc:
                wc.send_json({"type": "join", "token": c, "room_code": code, "name": "C", "instrument": "piano",
                              "version": V})
                err = wc.receive_json()
                assert err["type"] == "error" and err["code"] == "room_full" and err["fatal"] is True
                with pytest.raises(WebSocketDisconnect):
                    wc.receive_json()
    with client.websocket_connect("/ws") as w:
        w.send_json({"type": "join", "token": a, "room_code": "ZZZZZZ", "name": "A", "instrument": "piano",
                     "version": V})
        assert w.receive_json()["code"] == "room_not_found"


def test_version_too_old_bad_token_bad_first_message(client, tokens):
    a, _, _ = tokens
    with client.websocket_connect("/ws") as w:
        w.send_json({"type": "create", "token": a, "name": "A", "instrument": "piano", "version": "1.6.1"})
        err = w.receive_json()
        assert err["code"] == "version_too_old" and err["fatal"] is True
        with pytest.raises(WebSocketDisconnect):
            w.receive_json()
    with client.websocket_connect("/ws") as w:
        w.send_json({"type": "create", "token": "faux", "name": "A", "instrument": "piano", "version": V})
        err = w.receive_json()
        assert err["code"] == "bad_token" and err["fatal"] is True
    with client.websocket_connect("/ws") as w:
        w.send_json({"type": "ping", "t0": 1})
        err = w.receive_json()
        assert err["code"] == "bad_message" and err["fatal"] is True
    with client.websocket_connect("/ws") as w:
        w.send_text("pas du json")
        assert w.receive_json()["code"] == "bad_message"


def test_bad_messages_are_not_fatal(client, tokens):
    a, _, _ = tokens
    with client.websocket_connect("/ws") as w:
        create(w, a)
        w.send_json({"type": "set_song", "sha256": "zz", "duration_ms": 10, "source": "library"})
        err = w.receive_json()
        assert err["code"] == "bad_message" and err["fatal"] is False
        w.send_json({"type": "inconnu"})
        assert w.receive_json()["code"] == "bad_message"
        w.send_text("{oops")
        assert w.receive_json()["code"] == "bad_message"
        w.send_json({"type": "ping", "t0": 5})
        assert w.receive_json()["type"] == "pong"


def test_leave_promotes_next_and_kick(client, tokens):
    a, b, c = tokens
    with client.websocket_connect("/ws") as wa, client.websocket_connect("/ws") as wb, \
            client.websocket_connect("/ws") as wc:
        code = create(wa, a)[0]["room_code"]
        join(wb, b, code)
        until(wa, "state")
        join(wc, c, code, name="C")
        until(wa, "state")
        until(wb, "state")

        # kick par un non-chef refusé ; le chef expulse C
        wb.send_json({"type": "kick", "player_id": 3})
        assert wb.receive_json()["code"] == "not_host"
        wa.send_json({"type": "kick", "player_id": 3})
        assert until(wc, "bye")["reason"] == "kicked"
        with pytest.raises(WebSocketDisconnect):
            wc.receive_json()
        st = until(wa, "state")
        assert [p["id"] for p in st["players"]] == [1, 2]
        until(wb, "state")

        # le chef part : B devient chef
        wa.send_json({"type": "leave"})
        assert until(wa, "bye")["reason"] == "left"
        with pytest.raises(WebSocketDisconnect):
            wa.receive_json()
        st = until(wb, "state")
        assert st["host_id"] == 2 and [p["id"] for p in st["players"]] == [2]
        assert player(st, 2)["host"] is True
        wb.send_json(SONG)
        assert until(wb, "state")["song"]["name"] == "Métronome"


def test_grace_rejoin_and_room_reaped(tmp_path):
    settings = make_settings(tmp_path, ROOM_GRACE_S=0.6, ROOM_EMPTY_TTL_S=0.6)
    with make_client(settings) as client:
        a, b = login(client, "111")[0], login(client, "222")[0]
        with client.websocket_connect("/ws") as wa:
            code = create(wa, a)[0]["room_code"]
            with client.websocket_connect("/ws") as wb:
                seat_b = join(wb, b, code)[0]
                until(wa, "state")
            # B a perdu sa connexion : siège gardé (connected=false)
            st = until(wa, "state")
            assert player(st, 2)["connected"] is False and len(st["players"]) == 2

            # reprise du siège par seat_token avant la fin du délai de grâce : même id
            with client.websocket_connect("/ws") as wb2:
                j, st = join(wb2, b, code, seat_token=seat_b["seat_token"])
                assert j["player_id"] == 2 and player(st, 2)["connected"] is True
                until(wa, "state")
                # même compte sans seat_token : remplace la connexion précédente
                with client.websocket_connect("/ws") as wb3:
                    j3, _ = join(wb3, b, code)
                    assert j3["player_id"] == 2
                    assert until(wb2, "bye")["reason"] == "replaced"
                    until(wa, "state")
                until(wa, "state")   # wb3 fermée -> connected=false

            # délai de grâce dépassé : le siège disparaît
            time.sleep(1.2)
            st = until(wa, "state")
            assert [p["id"] for p in st["players"]] == [1]
        # salon vide -> supprimé après grâce de A + ROOM_EMPTY_TTL_S
        time.sleep(2.0)
        assert client.get("/api/health").json()["rooms"] == 0


def test_host_disconnect_promotes_connected_player(tmp_path):
    settings = make_settings(tmp_path, ROOM_GRACE_S=0.5, ROOM_EMPTY_TTL_S=5)
    with make_client(settings) as client:
        a, b = login(client, "111")[0], login(client, "222")[0]
        with client.websocket_connect("/ws") as wb:
            with client.websocket_connect("/ws") as wa:
                code = create(wa, a)[0]["room_code"]
                join(wb, b, code)
                until(wa, "state")
            st = until(wb, "state")
            assert st["host_id"] == 2 and player(st, 1)["connected"] is False
            time.sleep(1.0)
            st = until(wb, "state")
            assert [p["id"] for p in st["players"]] == [2]


def test_room_song_rest(client, tokens, midi_bytes, bad_midi_bytes, settings):
    a, b, c = tokens
    with client.websocket_connect("/ws") as wa, client.websocket_connect("/ws") as wb:
        code = create(wa, a)[0]["room_code"]
        join(wb, b, code)
        until(wa, "state")
        files = {"file": ("m.mid", midi_bytes, "audio/midi")}
        assert client.post(f"/api/rooms/{code}/song", files=files).status_code == 401
        assert client.post(f"/api/rooms/{code}/song", headers=bearer(b), files=files).status_code == 403
        assert client.post(f"/api/rooms/{code}/song", headers=bearer(c), files=files).status_code == 403
        assert client.post("/api/rooms/ZZZZZZ/song", headers=bearer(a), files=files).status_code == 404
        r = client.post(f"/api/rooms/{code}/song", headers=bearer(a),
                        files={"file": ("m.mid", bad_midi_bytes, "audio/midi")})
        assert r.status_code == 422
        r = client.post(f"/api/rooms/{code}/song", headers=bearer(a), files=files)
        assert r.status_code == 201, r.text
        sha = hashlib.sha256(midi_bytes).hexdigest()
        assert r.json()["sha256"] == sha and r.json()["note_count"] == 20
        assert (settings.tmp_dir / f"{sha}.mid").is_file()

        r = client.get(f"/api/rooms/{code}/song/{sha}", headers=bearer(b))
        assert r.status_code == 200 and r.content == midi_bytes
        assert client.get(f"/api/rooms/{code}/song/{sha}", headers=bearer(c)).status_code == 403
        assert client.get(f"/api/rooms/{code}/song/{'b' * 64}", headers=bearer(b)).status_code == 404
        assert client.get(f"/api/rooms/{code}/song/../x", headers=bearer(b)).status_code == 404


def test_room_song_too_large(tmp_path, midi_bytes):
    settings = make_settings(tmp_path, ROOM_SONG_MAX_BYTES=100)
    with make_client(settings) as client:
        a = login(client, "111")[0]
        with client.websocket_connect("/ws") as wa:
            code = create(wa, a)[0]["room_code"]
            r = client.post(f"/api/rooms/{code}/song", headers=bearer(a), files={"file": ("m.mid", midi_bytes)})
            assert r.status_code == 413


# ---------------------------------------------------------------- Orchestre : parties par siège
SONG_TRACKS = dict(SONG, tracks=[
    {"index": 1, "name": "Mélodie", "notes": 120, "low": 67, "high": 88, "mean": 76.5},
    {"index": 2, "name": "Basse", "notes": 60, "low": 36, "high": 52, "mean": 43.0},
    {"index": 9, "name": "Batterie", "notes": 200, "drums": True}])


def test_orchestre_parties_par_siege(client, tokens):
    a, b, _ = tokens
    with client.websocket_connect("/ws") as wa, client.websocket_connect("/ws") as wb:
        code = create(wa, a)[0]["room_code"]
        _, st = join(wb, b, code)
        assert player(st, 2)["version"] == V
        until(wa, "state")

        # pas de parties sans morceau
        wa.send_json({"type": "set_parts", "enabled": True, "parts": {"1": {"tracks": [1]}}})
        assert wa.receive_json()["code"] == "bad_state"

        wa.send_json(SONG_TRACKS)
        st = until(wa, "state")
        assert [t["index"] for t in st["song"]["tracks"]] == [1, 2, 9] and st["parts"] is None
        until(wb, "state")

        # l'invité ne répartit pas
        wb.send_json({"type": "set_parts", "enabled": True, "parts": {}})
        assert wb.receive_json()["code"] == "not_host"

        wb.send_json({"type": "ready", "ready": True})
        until(wa, "state")
        until(wb, "state")

        # le chef répartit : siège inconnu ignoré, piste inconnue refusée
        wa.send_json({"type": "set_parts", "enabled": True, "parts": {"1": {"tracks": [1], "octave": None},
                                                                      "2": {"tracks": [2], "octave": -1},
                                                                      "7": {"tracks": [1]}}})
        st = until(wa, "state")
        assert st["parts"] == {"enabled": True, "parts": {"1": {"tracks": [1], "octave": None},
                                                          "2": {"tracks": [2], "octave": -1}}}
        assert player(st, 2)["ready"] is False, "sa partie a changé : il doit se remettre prêt"
        until(wb, "state", parts=st["parts"])
        wa.send_json({"type": "set_parts", "enabled": True, "parts": {"1": {"tracks": [5]}}})
        assert wa.receive_json()["code"] == "bad_message"

        # le départ transporte les parties
        wa.send_json({"type": "song_status", "sha256": SHA, "have": True})
        wb.send_json({"type": "song_status", "sha256": SHA, "have": True})
        until(wa, "state")
        until(wa, "state")
        wa.send_json({"type": "start", "countdown_s": 4})
        sa = until(wa, "start")
        assert sa["parts"]["parts"]["2"] == {"tracks": [2], "octave": -1}
        wa.send_json({"type": "cancel"})
        until(wa, "cancelled")

        # un nouveau morceau efface la répartition ; un siège qui part est retiré
        wa.send_json(SONG_TRACKS)
        st = until(wa, "state", parts=None)
        wa.send_json({"type": "set_parts", "enabled": True, "parts": {"1": {"tracks": [1]}, "2": {"tracks": [2]}}})
        until(wa, "state", parts={"enabled": True, "parts": {"1": {"tracks": [1], "octave": None},
                                                            "2": {"tracks": [2], "octave": None}}})
        wb.send_json({"type": "leave"})
        st = until(wa, "state", parts={"enabled": True, "parts": {"1": {"tracks": [1], "octave": None}}})


def test_orchestre_messages_invalides(client, tokens):
    a, _, _ = tokens
    with client.websocket_connect("/ws") as wa:
        create(wa, a)
        wa.send_json(SONG_TRACKS)
        until(wa, "state")
        for bad in ({"type": "set_parts", "parts": {"1": {"tracks": [1], "octave": 5}}},
                    {"type": "set_parts", "parts": {"abc": {"tracks": [1]}}},
                    {"type": "set_parts", "parts": {"1": {"tracks": [300]}}}):
            wa.send_json(bad)
            err = wa.receive_json()
            assert err["type"] == "error" and err["fatal"] is False, (bad, err)
        # le salon marche toujours
        wa.send_json({"type": "ping", "t0": 1.0})
        assert until(wa, "pong")["t0"] == 1.0
