# -*- coding: utf-8 -*-
"""Outils des tests du client : faux lecteur, faux client HTTP, faux serveur de salons (protocole de la
Partie C) utilisable en mémoire (fausse WebSocketApp injectée) ou derrière un vrai serveur `websockets`."""
import asyncio
import hashlib
import json
import os
import queue
import random
import secrets
import shutil
import threading
import time

import mido

import core

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def wait_for(cond, timeout=5.0, step=0.01, what="condition"):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    raise AssertionError(f"délai dépassé : {what}")


def make_midi(path, notes=(60, 62, 64, 65, 67, 69, 71, 72), dur_ticks=240):
    mid = mido.MidiFile(type=0)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    for n in notes:
        tr.append(mido.Message("note_on", note=n, velocity=90, time=0))
        tr.append(mido.Message("note_off", note=n, velocity=0, time=dur_ticks))
    mid.save(path)
    return path


# ---------------------------------------------------------------- faux lecteur
class FakeInstrument:
    def __init__(self, ident="piano"):
        self.id = ident
        self.name = ident


class FakePlayer:
    """Même surface que core.Player pour room.RoomSession : mémorise `started_at` (= deadline de play_at)."""

    def __init__(self, root, cfg=None, inst="piano", play_duration=0.3):
        self.cfg = cfg if cfg is not None else {"stop_on_input": False, "hold_time": 0.04, "hold_mode": "note",
                                                "multi": {}}
        self.instrument = FakeInstrument(inst)
        self.songs_folder = os.path.join(root, "songs")
        os.makedirs(self.songs_folder, exist_ok=True)
        self.library = core.Library(os.path.join(root, "library.json"))
        self.state = "stopped"
        self.target = "preview"
        self.speed = 1.0
        self.lock_speed = False
        self.last_stop_reason = ""
        self._lock = threading.RLock()
        self._expected = {}
        self._stop = threading.Event()
        self.room = None
        self.sync = None
        self.started_at = None
        self.play_calls = []
        self.stop_calls = []
        self.play_duration = play_duration
        self.songs = []
        self.index = 0
        self.refresh_songs()

    def refresh_songs(self):
        self.songs = sorted(os.path.join(self.songs_folder, f) for f in os.listdir(self.songs_folder)
                            if f.lower().endswith((".mid", ".midi")))

    def current(self):
        return self.songs[self.index] if self.songs else None

    def song_duration(self, path):
        return core.midi_duration(path)

    def prepare(self, song, inst, target, common_key=False, extra=None, skip_tracks=None, octave=0):
        return {"song": song, "inst": inst.id, "extra": extra, "events": [], "timeline": [],
                "duration": self.song_duration(song), "skip_tracks": skip_tracks, "octave": octave}

    def play_at(self, deadline, prepared, target="game", offset=0.0):
        with self._lock:
            self.started_at = deadline
            self.offset = offset
            self.play_calls.append((deadline, prepared, target, time.perf_counter()))
            self.state = "playing"
            self.target = target
            self.last_stop_reason = ""
            self._stop.clear()
        threading.Thread(target=self._run, args=(deadline,), daemon=True).start()

    def _run(self, deadline):
        end = deadline + self.play_duration
        while time.perf_counter() < end and not self._stop.is_set():
            time.sleep(0.005)
        with self._lock:
            self.state = "stopped"
        self.lock_speed = False

    def stop(self, join=False, reason=""):
        with self._lock:
            if self.state != "stopped":
                self.last_stop_reason = reason
                self.stop_calls.append((reason, time.perf_counter()))
                self._stop.set()
                self.state = "stopped"
        if self.room is not None and self.room.active():
            self.room.on_player_stop(reason or "stop")


def add_song(player, name="test.mid", notes=None):
    path = os.path.join(player.songs_folder, name)
    make_midi(path, notes or (60, 62, 64, 65, 67, 69, 71, 72))
    player.refresh_songs()
    player.library.meta(name)
    player.library.sha256(name, path)
    return path


def import_into(player):
    """Callback import_file(path, meta) -> song_id : copie dans songs/ du joueur."""
    def import_file(path, meta):
        title = (meta or {}).get("title") or "musique"
        dst = os.path.join(player.songs_folder, f"{title}.mid")
        n = 2
        while os.path.exists(dst):
            dst = os.path.join(player.songs_folder, f"{title} ({n}).mid")
            n += 1
        shutil.copy2(path, dst)
        sid = os.path.basename(dst)
        player.library.meta(sid)
        player.library.set_online(sid, online_id=meta.get("online_id"), sha256=meta.get("sha256"))
        player.refresh_songs()
        return sid
    return import_file


# ---------------------------------------------------------------- faux client HTTP (fichiers du salon)
class FakeClient:
    """Remplace online.OnlineClient pour RoomSession : les fichiers vivent dans FakeServer.files."""

    def __init__(self, server, ws_url="ws://fake/ws"):
        self.server = server
        self._ws_url = ws_url
        self.token = None
        self.uploads = []
        self.downloads = []

    def ws_url(self, path="/ws"):
        return self._ws_url

    def upload(self, path, fields, filefield, filepath, timeout=60, content_type="audio/midi"):
        with open(filepath, "rb") as f:
            data = f.read()
        sha = hashlib.sha256(data).hexdigest()
        self.server.files[sha] = data
        self.uploads.append((path, fields, sha))
        return {"sha256": sha, "_status": 201}

    def download(self, path, dest, expected_sha256=None, on_progress=None, timeout=60, max_bytes=None):
        self.downloads.append(path)
        sha = path.rsplit("/", 1)[-1]
        data = self.server.files.get(sha)
        if data is None:
            for oid, info in self.server.online_songs.items():
                if f"/api/songs/{oid}/download" == path:
                    data = self.server.files[info["sha256"]]
        if data is None:
            from online import OnlineError
            raise OnlineError("introuvable", code=404)
        if max_bytes and len(data) > max_bytes:
            from online import OnlineError
            raise OnlineError("trop gros")
        with open(dest, "wb") as f:
            f.write(data)
        got = hashlib.sha256(data).hexdigest()
        if expected_sha256 and got != expected_sha256:
            from online import OnlineError
            raise OnlineError("empreinte différente")
        return got

    def get(self, path, params=None, timeout=5, auth=True):
        for oid, info in self.server.online_songs.items():
            if path == f"/api/songs/{oid}":
                return dict(info)
        from online import OnlineError
        raise OnlineError("introuvable", code=404)


# ---------------------------------------------------------------- faux serveur de salons
class Seat:
    def __init__(self, sid, name, instrument, conn):
        self.id = sid
        self.name = name
        self.instrument = instrument
        self.token = secrets.token_urlsafe(16)
        self.conn = conn
        self.connected = True
        self.have_song = False
        self.ready = False
        self.status = "idle"
        self.grace_timer = None

    def to_dict(self, host_id):
        return {"id": self.id, "name": self.name, "avatar": None, "instrument": self.instrument,
                "host": self.id == host_id, "connected": self.connected, "have_song": self.have_song,
                "ready": self.ready, "status": self.status}


class Room:
    def __init__(self, code, max_players=8):
        self.code = code
        self.max_players = max_players
        self.host_id = None
        self.state = "lobby"
        self.seats = {}
        self.song = None
        self.parts = None
        self.countdown_s = None
        self.start_at_ms = None
        self.seq = 0
        self.next_id = 1
        self.timer = None


class Conn:
    """Une connexion cliente vue du serveur ; `transport_send(dict)` envoie vers le client."""

    def __init__(self, server, transport_send):
        self.server = server
        self._send = transport_send
        self.room = None
        self.seat = None

    def send(self, msg):
        self._send(msg)

    def handle(self, msg):
        self.server.handle(self, msg)

    def closed(self):
        self.server.on_disconnect(self)


class FakeServer:
    """Protocole des salons (Partie C), en mémoire, indépendant du transport."""

    def __init__(self, true_offset_ms=1.7e12, grace_s=60.0, default_countdown_s=1.0, min_version="0",
                 end_margin_s=10.0, require_token=False):
        self.true_offset_ms = float(true_offset_ms)
        self.grace_s = grace_s
        self.end_margin_s = end_margin_s
        self.require_token = require_token
        self.default_countdown_s = default_countdown_s
        self.min_version = min_version
        self.rooms = {}
        self.files = {}             # sha256 -> bytes (POST /api/rooms/{code}/song)
        self.online_songs = {}      # online_id -> {id, sha256, title}
        self.lock = threading.RLock()
        self.log = []
        self.rng = random.Random(7)

    def srv_ms(self):
        return time.perf_counter() * 1000.0 + self.true_offset_ms

    # ---- outils
    def _code(self):
        while True:
            c = "".join(self.rng.choice(CODE_ALPHABET) for _ in range(6))
            if c not in self.rooms:
                return c

    def _state_msg(self, room):
        room.seq += 1
        return {"type": "state", "seq": room.seq, "room_code": room.code, "state": room.state,
                "host_id": room.host_id, "countdown_s": room.countdown_s, "start_at_ms": room.start_at_ms,
                "max_players": room.max_players, "server_now_ms": self.srv_ms(), "song": room.song,
                "players": [s.to_dict(room.host_id) for s in room.seats.values()], "parts": room.parts}

    def _broadcast(self, room, msg):
        for s in list(room.seats.values()):
            if s.connected and s.conn is not None:
                try:
                    s.conn.send(msg)
                except Exception:  # noqa
                    pass

    def _error(self, conn, code, message, fatal=False):
        conn.send({"type": "error", "code": code, "message": message, "fatal": fatal})

    def _joined(self, conn, room, seat):
        conn.send({"type": "joined", "room_code": room.code, "player_id": seat.id, "seat_token": seat.token,
                   "host": seat.id == room.host_id, "server_now_ms": self.srv_ms(), "min_version": self.min_version})

    def _remove_seat(self, room, seat, reason="left"):
        room.seats.pop(seat.id, None)
        if seat.conn is not None:
            try:
                seat.conn.send({"type": "bye", "reason": reason})
            except Exception:  # noqa
                pass
            seat.conn.seat = None
            seat.conn.room = None
        if room.host_id == seat.id:
            room.host_id = min(room.seats) if room.seats else None
        if not room.seats:
            if room.timer:
                room.timer.cancel()
            self.rooms.pop(room.code, None)
        else:
            self._broadcast(room, self._state_msg(room))

    # ---- messages
    def handle(self, conn, msg):
        with self.lock:
            t = msg.get("type")
            self.log.append((conn.seat.id if conn.seat else None, t, msg.get("status")))
            fn = getattr(self, f"m_{t}", None)
            if fn is None:
                self._error(conn, "bad_message", f"type inconnu {t}")
                return
            if t not in ("create", "join") and conn.room is None:
                self._error(conn, "bad_state", "pas dans un salon", fatal=True)
                return
            fn(conn, msg)

    def _auth(self, conn, m):
        if self.require_token and not m.get("token"):
            self._error(conn, "bad_token", "Connexion Discord requise", fatal=True)
            return False
        return True

    def m_create(self, conn, m):
        if not self._auth(conn, m):
            return
        room = Room(self._code(), int(m.get("max_players") or 8))
        self.rooms[room.code] = room
        seat = Seat(room.next_id, m.get("name", "?"), m.get("instrument", ""), conn)
        room.next_id += 1
        room.seats[seat.id] = seat
        room.host_id = seat.id
        conn.room, conn.seat = room, seat
        self._joined(conn, room, seat)
        self._broadcast(room, self._state_msg(room))

    def m_join(self, conn, m):
        if not self._auth(conn, m):
            return
        room = self.rooms.get(str(m.get("room_code") or "").upper())
        if room is None:
            self._error(conn, "room_not_found", "Salon introuvable", fatal=True)
            return
        tok = m.get("seat_token")
        seat = next((s for s in room.seats.values() if tok and s.token == tok), None)
        if seat is not None:
            if seat.grace_timer:
                seat.grace_timer.cancel()
                seat.grace_timer = None
            if seat.conn is not None and seat.conn is not conn and seat.connected:
                try:
                    seat.conn.send({"type": "bye", "reason": "replaced"})
                except Exception:  # noqa
                    pass
                seat.conn.seat = None
            seat.conn, seat.connected = conn, True
        else:
            if len(room.seats) >= room.max_players:
                self._error(conn, "room_full", "Salon complet", fatal=True)
                return
            seat = Seat(room.next_id, m.get("name", "?"), m.get("instrument", ""), conn)
            room.next_id += 1
            room.seats[seat.id] = seat
            if room.song is not None:
                seat.status = "no_song"
        conn.room, conn.seat = room, seat
        self._joined(conn, room, seat)
        self._broadcast(room, self._state_msg(room))

    def m_leave(self, conn, m):
        self._remove_seat(conn.room, conn.seat, "left")

    def m_ping(self, conn, m):
        t1 = self.srv_ms()
        conn.send({"type": "pong", "t0": m.get("t0"), "t1": t1, "t2": self.srv_ms()})

    def m_set_song(self, conn, m):
        room = conn.room
        if conn.seat.id != room.host_id:
            self._error(conn, "not_host", "Seul le chef")
            return
        if room.state != "lobby":
            self._error(conn, "bad_state", "pas au lobby")
            return
        room.song = {k: m.get(k) for k in ("sha256", "name", "duration_ms", "key_shift", "source", "online_id",
                                           "tracks")}
        room.parts = None
        for s in room.seats.values():
            s.have_song = False
            s.status = "idle"
        self._broadcast(room, self._state_msg(room))

    def m_set_parts(self, conn, m):
        room = conn.room
        if conn.seat.id != room.host_id:
            self._error(conn, "not_host", "Seul le chef")
            return
        room.parts = {"enabled": bool(m.get("enabled")), "parts": dict(m.get("parts") or {})}
        self._broadcast(room, self._state_msg(room))

    def m_song_status(self, conn, m):
        room = conn.room
        if room.song is None or room.song.get("sha256") != m.get("sha256"):
            return
        conn.seat.have_song = bool(m.get("have"))
        if room.state == "lobby":
            conn.seat.status = "idle" if conn.seat.have_song else "no_song"
        if not conn.seat.have_song:
            conn.seat.ready = False
        self._broadcast(room, self._state_msg(room))

    def _to_lobby(self, room):
        if room.timer:
            room.timer.cancel()
        room.state = "lobby"
        room.start_at_ms = None
        for s in room.seats.values():
            s.ready = False
            s.status = "idle" if s.have_song else "no_song"

    def _all_finished(self, room):
        active = [s for s in room.seats.values() if s.connected and s.have_song]
        return bool(active) and all(s.status in ("ended", "aborted") for s in active)

    def m_set_instrument(self, conn, m):
        conn.seat.instrument = m.get("instrument", "")
        self._broadcast(conn.room, self._state_msg(conn.room))

    def m_ready(self, conn, m):
        conn.seat.ready = bool(m.get("ready"))
        self._broadcast(conn.room, self._state_msg(conn.room))

    def m_start(self, conn, m):
        room = conn.room
        if conn.seat.id != room.host_id:
            self._error(conn, "not_host", "Seul le chef")
            return
        if room.state != "lobby" or not room.song:
            self._error(conn, "bad_state", "pas au lobby / pas de musique")
            return
        missing = [s for s in room.seats.values() if s.connected and not s.have_song]
        if missing and not m.get("force"):
            self._error(conn, "not_all_have_song", "fichier manquant chez " + ", ".join(s.name for s in missing))
            return
        cd = float(m.get("countdown_s") or self.default_countdown_s)
        room.countdown_s = cd
        room.start_at_ms = self.srv_ms() + cd * 1000.0
        room.state = "countdown"
        for s in room.seats.values():
            s.status = "armed" if s.have_song else "no_song"
        room.seq += 1
        self._broadcast(room, {"type": "start", "seq": room.seq, "start_at_ms": room.start_at_ms, "countdown_s": cd,
                               "song": room.song, "players": [s.to_dict(room.host_id) for s in room.seats.values()],
                               "by": conn.seat.id})
        room.timer = threading.Timer(cd, self._playing, args=(room,))
        room.timer.daemon = True
        room.timer.start()
        self._broadcast(room, self._state_msg(room))      # comme le vrai serveur : state complet apres start

    def _playing(self, room):
        with self.lock:
            if room.state != "countdown":
                return
            room.state = "playing"
            self._broadcast(room, self._state_msg(room))
            dur = float((room.song or {}).get("duration_ms") or 0) / 1000.0
            room.timer = threading.Timer(dur + self.end_margin_s, self._end, args=(room,))
            room.timer.daemon = True
            room.timer.start()

    def _end(self, room):
        with self.lock:
            if room.state == "playing":
                self._to_lobby(room)
                self._broadcast(room, self._state_msg(room))

    def m_cancel(self, conn, m):
        room = conn.room
        if conn.seat.id != room.host_id:
            self._error(conn, "not_host", "Seul le chef")
            return
        if room.state != "countdown":
            self._error(conn, "bad_state", "pas de compte à rebours")
            return
        self._to_lobby(room)
        room.seq += 1
        self._broadcast(room, {"type": "cancelled", "seq": room.seq, "by": conn.seat.id, "reason": "host"})
        self._broadcast(room, self._state_msg(room))

    def m_stop(self, conn, m):
        room = conn.room
        if conn.seat.id != room.host_id:
            self._error(conn, "not_host", "Seul le chef")
            return
        if room.state not in ("countdown", "playing"):
            self._error(conn, "bad_state", "rien à arrêter")
            return
        room.seq += 1
        at = self.srv_ms() + 250.0
        self._to_lobby(room)
        self._broadcast(room, {"type": "stop", "seq": room.seq, "by": conn.seat.id, "at_ms": at})
        self._broadcast(room, self._state_msg(room))     # tout de suite : le client ne doit pas s'arreter avant at_ms

    def m_player_state(self, conn, m):
        room = conn.room
        conn.seat.status = m.get("status", "")
        if conn.seat.status == "no_song":
            conn.seat.have_song = False
        if room.state == "playing" and self._all_finished(room):
            self._to_lobby(room)
        self._broadcast(room, self._state_msg(room))

    def m_kick(self, conn, m):
        room = conn.room
        if conn.seat.id != room.host_id:
            self._error(conn, "not_host", "Seul le chef")
            return
        seat = room.seats.get(m.get("player_id"))
        if seat:
            self._remove_seat(room, seat, "kicked")

    def on_disconnect(self, conn):
        with self.lock:
            room, seat = conn.room, conn.seat
            if room is None or seat is None or seat.conn is not conn:
                return
            seat.connected = False
            seat.conn = None
            self._broadcast(room, self._state_msg(room))

            def expire():
                with self.lock:
                    if seat.id in room.seats and not seat.connected:
                        self._remove_seat(room, seat, "left")
            seat.grace_timer = threading.Timer(self.grace_s, expire)
            seat.grace_timer.daemon = True
            seat.grace_timer.start()

    # ---- pour les tests
    def room_of(self, code):
        return self.rooms.get(code)

    def drop_seat(self, code, player_id):
        """Coupe la connexion d'un joueur côté serveur (simule une perte réseau)."""
        with self.lock:
            seat = self.rooms[code].seats[player_id]
            conn = seat.conn
        if conn is not None and hasattr(conn, "transport"):
            conn.transport.drop()


# ---------------------------------------------------------------- transport A : en mémoire
class FakeWSApp:
    """Fausse websocket.WebSocketApp : run_forever bloque et livre les messages dans son thread (comme la
    vraie) ; send remet au serveur ; délai aller/retour simulé (ms) en option."""

    def __init__(self, server, url, on_open=None, on_message=None, on_error=None, on_close=None,
                 delay_up_ms=0.0, delay_down_ms=0.0, jitter_ms=0.0):
        self.server = server
        self.url = url
        self.on_open, self.on_message, self.on_error, self.on_close = on_open, on_message, on_error, on_close
        self.delay_up, self.delay_down, self.jitter = delay_up_ms / 1000.0, delay_down_ms / 1000.0, jitter_ms / 1000.0
        self.down_q = queue.Queue()
        self.up_q = queue.Queue()
        self.closed = threading.Event()
        self.conn = Conn(server, self._push)
        self.conn.transport = self
        self.rng = random.Random()

    def _delay(self, base):
        return base + (self.rng.random() * self.jitter if self.jitter else 0.0)

    def _push(self, msg):
        self.down_q.put((time.perf_counter() + self._delay(self.delay_down), json.dumps(msg)))

    def _uplink(self):
        while not self.closed.is_set():
            try:
                at, msg = self.up_q.get(timeout=0.05)
            except queue.Empty:
                continue
            rem = at - time.perf_counter()
            if rem > 0:
                time.sleep(rem)
            if not self.closed.is_set():
                self.conn.handle(msg)

    def run_forever(self, **kw):
        threading.Thread(target=self._uplink, daemon=True).start()
        if self.on_open:
            self.on_open(self)
        while not self.closed.is_set():
            try:
                at, raw = self.down_q.get(timeout=0.05)
            except queue.Empty:
                continue
            rem = at - time.perf_counter()
            if rem > 0:
                time.sleep(rem)
            if self.closed.is_set():
                break
            if self.on_message:
                self.on_message(self, raw)
        if self.on_close:
            self.on_close(self, None, None)

    def send(self, raw):
        if self.closed.is_set():
            raise ConnectionError("fermée")
        msg = json.loads(raw)
        if self.delay_up or self.jitter:
            self.up_q.put((time.perf_counter() + self._delay(self.delay_up), msg))
        else:
            self.conn.handle(msg)

    def close(self):
        if not self.closed.is_set():
            self.closed.set()
            self.conn.closed()

    def drop(self):
        """Coupure côté serveur : le client voit run_forever se terminer sans l'avoir demandé."""
        self.close()


def fake_ws_factory(server, **delays):
    def factory(url, **cbs):
        return FakeWSApp(server, url, **cbs, **delays)
    return factory


# ---------------------------------------------------------------- transport B : vrai serveur websockets
class WsServer:
    """FakeServer derrière un vrai serveur `websockets` (thread + boucle asyncio) pour tester websocket-client."""

    def __init__(self, server, host="127.0.0.1"):
        self.server = server
        self.host = host
        self.port = None
        self.loop = None
        self._ready = threading.Event()
        self._stop = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _run(self):
        import websockets
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._stop = self.loop.create_future()

        async def handler(ws):
            loop = self.loop

            def send(msg):
                asyncio.run_coroutine_threadsafe(ws.send(json.dumps(msg)), loop)
            conn = Conn(self.server, send)
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    conn.handle(msg)      # synchrone : conserve l'ordre des messages
            except Exception:  # noqa
                pass
            finally:
                conn.closed()

        async def main():
            async with websockets.serve(handler, self.host, 0) as srv:
                self.port = srv.sockets[0].getsockname()[1]
                self._ready.set()
                await self._stop
        try:
            self.loop.run_until_complete(main())
        finally:
            self.loop.close()

    @property
    def url(self):
        return f"ws://{self.host}:{self.port}/ws"

    def close(self):
        if self.loop and self._stop and not self._stop.done():
            self.loop.call_soon_threadsafe(self._stop.set_result, None)
        self._thread.join(timeout=3)
