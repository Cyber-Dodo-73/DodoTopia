"""Salons de jeu synchronisés (Partie C du plan) : une WebSocket `/ws`, salons en mémoire, horloge serveur.

Premier message : `create{token, name, instrument, version, max_players?}` ou
`join{token, room_code, name, instrument, version, seat_token?}` où `token` est le token de session Discord
(obligatoire) et `seat_token` le jeton de siège reçu dans `joined` (reprise après coupure, pendant ROOM_GRACE_S).

Serveur -> client : `joined`, `state` (instantané complet, `seq` croissant), `start`, `cancelled`, `stop`, `pong`,
`error{code, message, fatal}`, `bye{reason}`.
Machine à états : lobby -start(chef)-> countdown -timer-> playing -> lobby (cancel, stop, tous `ended`, ou
start_at + duration + 10 s).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time

from fastapi import APIRouter, Depends, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from . import db, notify, stats
from .auth import api_error, get_current_user, user_from_token
from .config import Settings
from .library import MidiError, read_upload, validate_midi
from .ratelimit import TokenBucket, client_ip, limit
from .schemas import WS_MODELS

log = logging.getLogger("dodo.rooms")
router = APIRouter()

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 6
MAX_MSG_BYTES = 16 * 1024
WS_MSGS_PER_S = 20
FIRST_MSG_TIMEOUT_S = 10.0      # create/join attendu dans ce délai, sinon fermeture 1008 (connexions muettes)
WS_OPEN_PER_MIN = 20            # ouvertures de WebSocket par IP et par minute, refusées avant accept()
ROOM_CREATE_PER_MIN = 10
ROOM_JOIN_PER_MIN = 20
STOP_LEAD_MS = 250
END_MARGIN_S = 10
COUNTDOWN_MIN, COUNTDOWN_MAX, COUNTDOWN_DEFAULT = 3, 15, 5

# Horloge serveur : perf_counter (haute résolution, monotone ; time.monotonic() n'a que 15,6 ms sous Windows)
# ancré sur l'heure réelle au démarrage (ne saute jamais ensuite).
_EPOCH0_MS = time.time() * 1000.0
_PERF0 = time.perf_counter()


def srv_ms() -> float:
    return round(_EPOCH0_MS + (time.perf_counter() - _PERF0) * 1000.0, 1)


def parse_version(s: str) -> tuple[int, ...]:
    """Tolérant : '1.7.0' -> (1, 7, 0), 'dev' -> (0,)."""
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums) or (0,)


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


class RoomError(Exception):
    def __init__(self, code: str, message: str, fatal: bool = False):
        super().__init__(message)
        self.code, self.message, self.fatal = code, message, fatal


class Seat:
    """Un joueur dans un salon (survit ROOM_GRACE_S à la perte de sa WebSocket)."""

    def __init__(self, sid: int, user, name: str, instrument: str, version: str):
        self.id = sid
        self.token = secrets.token_urlsafe(24)
        self.user_id = user["id"]
        self.username = user["username"]
        self.avatar = user["avatar_url"]
        self.name = name or user["username"]
        self.instrument = instrument
        self.version = version
        self.ws: WebSocket | None = None
        self.connected = False
        self.disconnected_at = time.monotonic()
        self.last_msg_at = time.monotonic()
        self.have_song = False
        self.ready = False
        self.status = "idle"
        self.bucket = TokenBucket(WS_MSGS_PER_S, WS_MSGS_PER_S)

    def attach(self, ws: WebSocket) -> None:
        self.ws = ws
        self.connected = True
        self.last_msg_at = time.monotonic()

    def detach(self) -> None:
        self.ws = None
        self.connected = False
        self.disconnected_at = time.monotonic()

    def public(self, host_id: int | None) -> dict:
        return {"id": self.id, "name": self.name, "avatar": self.avatar, "instrument": self.instrument,
                "host": self.id == host_id, "connected": self.connected, "have_song": self.have_song,
                "ready": self.ready, "status": self.status, "version": self.version}


class Room:
    def __init__(self, code: str, max_players: int):
        self.code = code
        self.max_players = max_players
        self.seats: dict[int, Seat] = {}
        self.next_id = 1
        self.host_id: int | None = None
        self.state = "lobby"
        self.countdown_s = COUNTDOWN_DEFAULT
        self.start_at_ms: int | None = None
        self.song: dict | None = None
        # Orchestre : {"enabled": bool, "parts": {id de siège: {"tracks": [...], "octave": int|None}}} ou None
        self.parts: dict | None = None
        self.files: set[str] = set()    # sha256 des fichiers éphémères déposés pour CE salon
        self.seq = 0
        self.empty_since: float | None = time.monotonic()
        self.timer: asyncio.Task | None = None
        self.created_at = time.time()          # âge affiché dans l'espace admin

    # --- composition ---
    def add_seat(self, user, name: str, instrument: str, version: str) -> Seat:
        seat = Seat(self.next_id, user, name, instrument, version)
        self.next_id += 1
        self.seats[seat.id] = seat
        self.empty_since = None
        if self.host_id is None:
            self.host_id = seat.id
        return seat

    def remove_seat(self, seat: Seat) -> None:
        self.seats.pop(seat.id, None)
        if self.parts:
            self.parts["parts"].pop(seat.id, None)
        if not self.seats:
            self.empty_since = time.monotonic()
        self.promote()

    def promote(self) -> None:
        """Chef = créateur ; s'il est parti, le plus petit id connecté (sinon le plus petit id)."""
        cur = self.seats.get(self.host_id)
        if cur is not None and cur.connected:
            return
        ordered = sorted(self.seats.values(), key=lambda s: s.id)
        connected = [s for s in ordered if s.connected]
        pick = (connected or ordered or [None])[0]
        self.host_id = pick.id if pick else None

    def seat_of_user(self, user_id: int) -> Seat | None:
        return next((s for s in self.seats.values() if s.user_id == user_id), None)

    def seat_by_token(self, token: str | None) -> Seat | None:
        if not token:
            return None
        return next((s for s in self.seats.values() if secrets.compare_digest(s.token, token)), None)

    def connected_seats(self) -> list[Seat]:
        return [s for s in self.seats.values() if s.connected]

    # --- messages ---
    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def players(self) -> list[dict]:
        return [s.public(self.host_id) for s in sorted(self.seats.values(), key=lambda s: s.id)]

    def snapshot(self) -> dict:
        return {"type": "state", "seq": self.next_seq(), "room_code": self.code, "state": self.state,
                "host_id": self.host_id, "countdown_s": self.countdown_s, "start_at_ms": self.start_at_ms,
                "max_players": self.max_players, "server_now_ms": srv_ms(), "song": self.song,
                "players": self.players(), "parts": self.parts_public()}

    def parts_public(self) -> dict | None:
        """Parties de l'Orchestre, clés de siège en texte (JSON)."""
        if not self.parts:
            return None
        return {"enabled": bool(self.parts.get("enabled")),
                "parts": {str(k): dict(v) for k, v in sorted(self.parts["parts"].items())}}

    async def broadcast(self, msg: dict) -> None:
        for seat in list(self.seats.values()):
            if seat.connected and seat.ws is not None:
                try:
                    await seat.ws.send_json(msg)
                except Exception:
                    seat.detach()

    async def push_state(self) -> None:
        await self.broadcast(self.snapshot())

    # --- machine à états ---
    def cancel_timer(self) -> None:
        t, self.timer = self.timer, None
        if t is not None and t is not asyncio.current_task() and not t.done():
            t.cancel()

    def to_lobby(self) -> None:
        self.cancel_timer()
        self.state = "lobby"
        self.start_at_ms = None
        for s in self.seats.values():
            s.ready = False
            s.status = "idle" if s.have_song else "no_song"

    def all_finished(self) -> bool:
        active = [s for s in self.connected_seats() if s.have_song]
        return bool(active) and all(s.status in ("ended", "aborted") for s in active)


class RoomManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.rooms: dict[str, Room] = {}
        self._reaper: asyncio.Task | None = None
        self.stats_app = None                  # app FastAPI (statistiques et notifications), posée par main.py

    def _hit(self, key: str, dim: str = "") -> None:
        if self.stats_app is not None:
            stats.hit(self.stats_app, key, dim)

    # --- cycle de vie ---
    def start(self) -> None:
        self._reaper = asyncio.create_task(self._reap_loop())

    async def stop(self) -> None:
        if self._reaper:
            self._reaper.cancel()
            self._reaper = None
        for room in list(self.rooms.values()):
            room.cancel_timer()
            await room.broadcast({"type": "bye", "reason": "room_closed"})
            for seat in room.connected_seats():
                await _safe_close(seat.ws)
        self.rooms.clear()

    def new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
            if code not in self.rooms:
                return code

    def create(self, max_players: int | None) -> Room:
        cap = self.settings.ROOM_MAX_PLAYERS
        mp = cap if max_players is None else max(2, min(cap, int(max_players)))
        room = Room(self.new_code(), mp)
        self.rooms[room.code] = room
        return room

    def get(self, code: str) -> Room | None:
        return self.rooms.get(normalize_code(code))

    # --- nettoyage périodique ---
    async def _reap_loop(self) -> None:
        s = self.settings
        interval = max(0.05, min(1.0, s.ROOM_GRACE_S / 2, s.ROOM_EMPTY_TTL_S / 2))
        while True:
            await asyncio.sleep(interval)
            try:
                await self.reap()
            except Exception:
                log.exception("reaper")

    async def reap(self) -> None:
        """Ferme les connexions muettes, libère les sièges hors délai de grâce, supprime les salons vides."""
        s = self.settings
        now = time.monotonic()
        for room in list(self.rooms.values()):
            changed = False
            for seat in list(room.seats.values()):
                if seat.connected and now - seat.last_msg_at > s.ROOM_IDLE_S:
                    ws = seat.ws
                    seat.detach()
                    await _safe_close(ws)
                    changed = True
                if not seat.connected and now - seat.disconnected_at > s.ROOM_GRACE_S:
                    room.remove_seat(seat)
                    changed = True
            if not room.seats:
                if room.empty_since is None:
                    room.empty_since = now
                if now - room.empty_since > s.ROOM_EMPTY_TTL_S:
                    room.cancel_timer()
                    del self.rooms[room.code]
                continue
            if changed:
                room.promote()
                if room.state == "playing" and room.all_finished():
                    room.to_lobby()
                await room.push_state()

    # --- premier message : create / join ---
    async def attach(self, ws: WebSocket, msg: dict) -> tuple[Room, Seat]:
        kind = msg.get("type")
        if kind not in ("create", "join"):
            raise RoomError("bad_message", "Le premier message doit être create ou join.", fatal=True)
        body = _validate(kind, msg)
        s = self.settings
        if parse_version(body.version) < parse_version(s.MIN_CLIENT_VERSION):
            raise RoomError("version_too_old", f"Mets DodoTopia à jour (version {s.MIN_CLIENT_VERSION} minimum).",
                            fatal=True)
        conn = db.connect(s)
        try:
            user = user_from_token(conn, s, body.token)
        finally:
            conn.close()
        if user is None:
            raise RoomError("bad_token", "Connexion Discord requise (session invalide ou expirée).", fatal=True)
        name = body.name.strip()[:24]
        limiter = ws.app.state.ratelimiter
        ip = client_ip(ws)

        if kind == "create":
            if limiter.check("room_create", ip, ROOM_CREATE_PER_MIN, 60) > 0:
                raise RoomError("rate_limited", "Trop de salons créés, patiente une minute.", fatal=True)
            room = self.create(body.max_players)
            seat = room.add_seat(user, name, body.instrument, body.version)
            self._hit("room_create")
        else:
            if limiter.check("room_join", ip, ROOM_JOIN_PER_MIN, 60) > 0:
                raise RoomError("rate_limited", "Trop de tentatives, patiente une minute.", fatal=True)
            room = self.get(body.room_code)
            if room is None:
                raise RoomError("room_not_found", "Salon introuvable.", fatal=True)
            seat = room.seat_by_token(body.seat_token) or room.seat_of_user(user["id"])
            if seat is not None:
                # reprise d'un siège (coupure) ou même compte déjà présent : l'ancienne connexion est remplacée
                old = seat.ws if seat.connected else None
                if old is not None:
                    seat.detach()
                    try:
                        await old.send_json({"type": "bye", "reason": "replaced"})
                    except Exception:
                        pass
                    await _safe_close(old)
                if name:
                    seat.name = name
                seat.instrument = body.instrument
                seat.version = body.version
            else:
                if len(room.seats) >= room.max_players:
                    raise RoomError("room_full", "Ce salon est complet.", fatal=True)
                seat = room.add_seat(user, name, body.instrument, body.version)
                self._hit("room_join")
                if room.song is not None:
                    seat.status = "no_song"
        seat.attach(ws)
        room.promote()
        await ws.send_json({"type": "joined", "room_code": room.code, "player_id": seat.id, "seat_token": seat.token,
                            "host": seat.id == room.host_id, "server_now_ms": srv_ms(),
                            "min_version": s.MIN_CLIENT_VERSION})
        await room.push_state()
        return room, seat

    # --- messages suivants ---
    async def handle(self, room: Room, seat: Seat, ws: WebSocket, msg: dict) -> bool:
        """Traite un message ; renvoie False si la connexion doit se terminer (leave)."""
        kind = msg.get("type")
        if kind == "ping":
            t1 = srv_ms()
            body = _validate(kind, msg)
            await ws.send_json({"type": "pong", "t0": body.t0, "t1": t1, "t2": srv_ms()})
            return True
        if kind in ("create", "join"):
            raise RoomError("bad_message", "Déjà dans un salon.")
        if kind not in WS_MODELS:
            raise RoomError("bad_message", f"Message inconnu : {kind!r}.")
        body = _validate(kind, msg)
        handler = getattr(self, f"_on_{kind}")
        return await handler(room, seat, ws, body) is not False

    def _require_host(self, room: Room, seat: Seat) -> None:
        if seat.id != room.host_id:
            raise RoomError("not_host", "Seul le chef du salon peut faire ça.")

    async def _on_leave(self, room, seat, ws, body):
        seat.detach()
        room.remove_seat(seat)
        try:
            await ws.send_json({"type": "bye", "reason": "left"})
        except Exception:
            pass
        await _safe_close(ws)
        if room.state == "playing" and room.all_finished():
            room.to_lobby()
        await room.push_state()
        return False

    async def _on_set_song(self, room, seat, ws, body):
        self._require_host(room, seat)
        if room.state != "lobby":
            raise RoomError("bad_state", "Impossible de changer de morceau pendant une partie.")
        room.song = {"sha256": body.sha256, "name": body.name, "duration_ms": body.duration_ms,
                     "key_shift": body.key_shift, "source": body.source, "online_id": body.online_id,
                     "tracks": [t.model_dump() for t in body.tracks]}
        room.parts = None           # nouvelles pistes : l'ancienne répartition ne veut plus rien dire
        for s in room.seats.values():
            s.have_song = False
            s.ready = False
            s.status = "no_song"
        await room.push_state()

    async def _on_set_parts(self, room, seat, ws, body):
        """Orchestre : le chef répartit les pistes du morceau entre les sièges (salon au repos seulement).
        Un siège dont la partie change n'est plus « prêt » : il doit réentendre ce qu'il va jouer."""
        self._require_host(room, seat)
        if room.state != "lobby":
            raise RoomError("bad_state", "Impossible de changer les parties pendant une partie.")
        if room.song is None:
            raise RoomError("bad_state", "Choisis d'abord un morceau.")
        known = {t["index"] for t in room.song.get("tracks") or []}
        parts = {}
        for key, part in body.parts.items():
            try:
                sid = int(key)
            except ValueError:
                raise RoomError("bad_message", f"Siège inconnu : {key!r}.")
            if sid not in room.seats:
                continue            # siège parti entre-temps : ignoré
            tracks = sorted(set(part.tracks))
            if known and any(i not in known for i in tracks):
                raise RoomError("bad_message", "Piste inconnue dans la répartition.")
            parts[sid] = {"tracks": tracks, "octave": part.octave}
        old = (room.parts or {}).get("parts") or {}
        was_on = bool((room.parts or {}).get("enabled"))
        room.parts = {"enabled": bool(body.enabled), "parts": parts}
        for sid, s in room.seats.items():
            if was_on != room.parts["enabled"] or old.get(sid) != parts.get(sid):
                s.ready = False
        await room.push_state()

    async def _on_song_status(self, room, seat, ws, body):
        if room.song is None or room.song["sha256"] != body.sha256:
            return
        seat.have_song = body.have
        if room.state == "lobby":
            seat.status = "idle" if body.have else "no_song"
        if not body.have:
            seat.ready = False
        await room.push_state()

    async def _on_set_instrument(self, room, seat, ws, body):
        seat.instrument = body.instrument
        await room.push_state()

    async def _on_ready(self, room, seat, ws, body):
        if room.state != "lobby":
            raise RoomError("bad_state", "Trop tard pour changer d'état.")
        seat.ready = body.ready
        await room.push_state()

    async def _on_start(self, room, seat, ws, body):
        self._require_host(room, seat)
        if room.state != "lobby":
            raise RoomError("bad_state", "Une partie est déjà en cours.")
        if room.song is None:
            raise RoomError("bad_state", "Choisis d'abord un morceau.")
        missing = [s.name for s in room.connected_seats() if not s.have_song]
        if missing and not body.force:
            raise RoomError("not_all_have_song", "Tout le monde n'a pas encore le morceau : " + ", ".join(missing))
        countdown = COUNTDOWN_DEFAULT if body.countdown_s is None else max(COUNTDOWN_MIN, min(COUNTDOWN_MAX, body.countdown_s))
        room.countdown_s = countdown
        room.state = "countdown"
        room.start_at_ms = int(srv_ms() + countdown * 1000)
        for s in room.seats.values():
            s.status = "armed" if s.have_song else "no_song"
        room.timer = asyncio.create_task(self._start_timer(room))
        await room.broadcast({"type": "start", "seq": room.next_seq(), "start_at_ms": room.start_at_ms,
                              "countdown_s": countdown, "song": room.song, "players": room.players(),
                              "parts": room.parts_public(), "by": seat.id})
        n = len(room.connected_seats())
        self._hit("room_start")
        self._hit("room_start_size", f"{n} joueur" + ("s" if n > 1 else ""))
        if self.stats_app is not None:
            notify.emit(self.stats_app, "room_started", f"Partie lancée dans le salon {room.code}",
                        f"{n} joueur(s) · {(room.song or {}).get('title') or 'morceau'}",
                        fields=[("Joueurs", ", ".join(s.name for s in room.connected_seats())[:900])])
        await room.push_state()

    async def _start_timer(self, room: Room) -> None:
        """countdown -> playing à start_at, puis retour au lobby à start_at + durée + marge."""
        try:
            await asyncio.sleep(max(0.0, (room.start_at_ms - srv_ms()) / 1000.0))
            if room.state != "countdown":
                return
            room.state = "playing"
            await room.push_state()
            await asyncio.sleep(room.song["duration_ms"] / 1000.0 + END_MARGIN_S)
            if room.state == "playing":
                room.to_lobby()
                await room.push_state()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("start_timer")

    async def _on_cancel(self, room, seat, ws, body):
        self._require_host(room, seat)
        if room.state != "countdown":
            raise RoomError("bad_state", "Rien à annuler.")
        room.to_lobby()
        await room.broadcast({"type": "cancelled", "seq": room.next_seq(), "by": seat.id, "reason": "host"})
        await room.push_state()

    async def _on_stop(self, room, seat, ws, body):
        self._require_host(room, seat)
        if room.state not in ("countdown", "playing"):
            raise RoomError("bad_state", "Rien à arrêter.")
        at_ms = int(srv_ms() + STOP_LEAD_MS)
        room.to_lobby()
        await room.broadcast({"type": "stop", "seq": room.next_seq(), "by": seat.id, "at_ms": at_ms})
        await room.push_state()

    async def _on_player_state(self, room, seat, ws, body):
        seat.status = body.status
        if body.status == "no_song":
            seat.have_song = False
        if room.state == "playing" and room.all_finished():
            room.to_lobby()
        await room.push_state()

    async def _on_kick(self, room, seat, ws, body):
        self._require_host(room, seat)
        target = room.seats.get(body.player_id)
        if target is None or target.id == seat.id:
            raise RoomError("bad_message", "Joueur introuvable.")
        old = target.ws if target.connected else None
        target.detach()
        room.remove_seat(target)
        if old is not None:
            try:
                await old.send_json({"type": "bye", "reason": "kicked"})
            except Exception:
                pass
            await _safe_close(old)
        await room.push_state()


# --- Aides ----------------------------------------------------------------------

def _validate(kind: str, msg: dict):
    try:
        return WS_MODELS[kind].model_validate(msg)
    except ValidationError as e:
        first = e.errors()[0] if e.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", ()))
        raise RoomError("bad_message", f"Message {kind} invalide ({loc}: {first.get('msg', '?')}).")


async def _safe_close(ws: WebSocket | None, code: int = 1000) -> None:
    if ws is None:
        return
    try:
        await ws.close(code=code)
    except Exception:
        pass


async def _send_error(ws: WebSocket, err: RoomError) -> None:
    try:
        await ws.send_json({"type": "error", "code": err.code, "message": err.message, "fatal": err.fatal})
    except Exception:
        pass


async def _recv(ws: WebSocket) -> dict:
    raw = await ws.receive_text()
    if len(raw) > MAX_MSG_BYTES:
        raise RoomError("bad_message", "Message trop long.")
    try:
        msg = json.loads(raw)
    except ValueError:
        raise RoomError("bad_message", "JSON invalide.")
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        raise RoomError("bad_message", "Un message est un objet JSON avec un champ type.")
    return msg


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    manager: RoomManager = websocket.app.state.rooms
    # Limitation par IP avant même la poignée de main : une rafale d'ouvertures n'occupe ni tâche ni tampon.
    if websocket.app.state.ratelimiter.check("ws_open", client_ip(websocket), WS_OPEN_PER_MIN, 60) > 0:
        await _safe_close(websocket, code=1008)
        return
    await websocket.accept()
    room: Room | None = None
    seat: Seat | None = None
    try:
        while True:
            try:
                if seat is None:
                    # Une connexion ouverte qui ne dit rien (scanner, client planté) est fermée sans attendre le
                    # ROOM_IDLE_S du reaper, qui ne s'applique qu'aux sièges.
                    msg = await asyncio.wait_for(_recv(websocket), timeout=FIRST_MSG_TIMEOUT_S)
                else:
                    msg = await _recv(websocket)
            except asyncio.TimeoutError:
                await _safe_close(websocket, code=1008)
                return
            except RoomError as e:
                await _send_error(websocket, e)
                if seat is None:
                    break   # pas encore dans un salon : on ne laisse pas traîner la connexion
                continue
            if seat is None:
                try:
                    room, seat = await manager.attach(websocket, msg)
                except RoomError as e:
                    e.fatal = True
                    await _send_error(websocket, e)
                    break
                continue
            seat.last_msg_at = time.monotonic()
            if manager.settings.RATE_LIMIT and seat.bucket.take() > 0:
                await _send_error(websocket, RoomError("rate_limited", "Trop de messages."))
                continue
            try:
                keep = await manager.handle(room, seat, websocket, msg)
            except RoomError as e:
                await _send_error(websocket, e)
                if e.fatal:
                    break
                continue
            if not keep or seat.ws is not websocket:
                break
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass   # WebSocket fermée par un autre handler (kick / replaced)
    except Exception:
        log.exception("ws")
    finally:
        if seat is not None and room is not None and seat.ws is websocket:
            seat.detach()   # début du délai de grâce
            room.promote()  # un autre joueur connecté prend la main si c'était le chef
            try:
                await room.push_state()
            except Exception:
                pass
        await _safe_close(websocket)


# --- REST : fichier éphémère d'un salon ------------------------------------------

def _member(request: Request, code: str, user) -> tuple[Room, Seat]:
    room = request.app.state.rooms.get(code)
    if room is None:
        raise api_error(404, "room_not_found", "Salon introuvable.")
    seat = room.seat_of_user(user["id"])
    if seat is None:
        raise api_error(403, "not_member", "Tu n'es pas dans ce salon.")
    return room, seat


@router.post("/api/rooms/{code}/song", status_code=201,
             dependencies=[Depends(limit("room_song", 30, 3600, by="user"))])
async def room_upload_song(code: str, request: Request, file: UploadFile = File(...), user=Depends(get_current_user)):
    """Morceau éphémère d'un salon : même validation que la bibliothèque, plafond de taille propre au salon.

    `get_current_user` écarte déjà les bannis (user_from_token les exclut) ; seul le chef du salon dépose.
    """
    settings: Settings = request.app.state.settings
    room, seat = _member(request, code, user)
    if seat.id != room.host_id:
        raise api_error(403, "not_host", "Seul le chef peut envoyer le morceau.")
    data = await read_upload(file, settings.ROOM_SONG_MAX_BYTES)
    if not data:
        raise api_error(422, "invalid_midi", "Fichier vide.")
    try:
        info = validate_midi(data, settings)
    except MidiError as e:
        raise api_error(422, "invalid_midi", str(e))
    sha = hashlib.sha256(data).hexdigest()
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    path = settings.tmp_dir / f"{sha}.mid"     # nom dérivé du sha256, jamais du nom envoyé par le client
    tmp = settings.tmp_dir / f"{sha}.{secrets.token_hex(8)}.part"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)                  # pas de fichier à moitié écrit visible au téléchargement
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    room.files.add(sha)
    return {"sha256": sha, "size": len(data), **info}


@router.get("/api/rooms/{code}/song/{sha256}")
def room_download_song(code: str, sha256: str, request: Request, user=Depends(get_current_user)):
    """Servi aux seuls membres du salon, et seulement pour un fichier de CE salon (déposé ici ou morceau
    courant) : connaître un sha256 ne suffit pas à piocher dans les fichiers éphémères d'un autre salon."""
    settings: Settings = request.app.state.settings
    room, _seat = _member(request, code, user)
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise api_error(404, "not_found", "Fichier introuvable.")
    current = (room.song or {}).get("sha256")
    if sha256 not in room.files and sha256 != current:
        raise api_error(404, "not_found", "Fichier introuvable.")
    path = settings.tmp_dir / f"{sha256}.mid"
    if not path.is_file():
        raise api_error(404, "not_found", "Fichier introuvable.")
    return FileResponse(path, media_type="audio/midi",
                        headers={"ETag": f'"{sha256}"', "X-Sha256": sha256,
                                 "Content-Disposition": f'attachment; filename="{sha256[:12]}.mid"',
                                 "X-Content-Type-Options": "nosniff"})


@router.get("/api/rooms/{code}/exists", dependencies=[Depends(limit("room_exists", 30, 60))])
def room_exists(code: str, request: Request):
    """Le salon existe-t-il encore ? (page publique `/{lang}/salon/{code}`, lien d'invitation). Sans compte ; rien
    d'autre que l'existence et la place restante n'est révélé (ni pseudos, ni morceau)."""
    norm = normalize_code(code[:32])
    room = request.app.state.rooms.get(norm) if len(norm) == CODE_LEN else None
    if room is None:
        return JSONResponse({"code": norm, "exists": False, "full": False}, headers={"Cache-Control": "no-store"})
    return JSONResponse({"code": room.code, "exists": True, "full": len(room.seats) >= room.max_players},
                        headers={"Cache-Control": "no-store"})
