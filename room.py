# -*- coding: utf-8 -*-
"""Salons en ligne : top départ partagé par le serveur (horloge commune sur la WebSocket, même fichier, même
tonalité). Le mode Multi audio (sync.py) reste le secours hors ligne.

Horloges : côté client `time.perf_counter()` (celle de `Player.play_at`) ; côté serveur `srv_ms()`.
`ClockSync` estime `offset_ms = srv_ms − local_ms` par des ping/pong sur la WebSocket (NTP simplifié) ;
`deadline = clock.to_local(start_at_ms) + net_offset_ms / 1000`, calculée une seule fois à `start`.

Machine à états du client : idle → connecting → lobby ⇄ downloading → armed → playing → lobby ;
`leave`, erreur fatale ou grâce de reconnexion expirée → idle. `player.state = "sync"` seulement de `armed`
à `play_at` (une frappe locale annule localement, comme le mode audio).

Intégration dans app.py (l'instance est créée par online.OnlineService : `self._room = self._online.room`,
`self._player.room = self._room`) :
    _music_toggle (F6) : si cfg["multi"]["mode"] == "room" -> self._room.on_f6()
    _bind_hotkeys.stop (F7) : p.stop() suffit (Player.stop -> room.on_player_stop) ; ou room.stop_local("stop")
    set_instrument / next_instrument : self._room.on_instrument_change(self._player.instrument)
    get_state()["multi"] : self._room.status() quand mode == "room" (mêmes clés que SyncSession.status()
                           + clé "room") ; aussi dans get_state()["online"]["room"]
    Méthodes Api (toutes attrapent OnlineError -> toast, renvoient get_state()) :
      room_create()            -> self._room.create()
      room_join(code)          -> self._room.join(code)
      room_leave()             -> self._room.leave()
      room_set_song(spec)      -> self._room.set_song(spec)   spec = song_id local | chemin | online_id (int)
      room_ready(on)           -> self._room.set_ready(bool(on))
      room_start()             -> self._room.start()
      room_cancel()            -> self._room.cancel()
      room_stop()              -> self._room.stop()
      room_set_offset(ms)      -> self._room.set_net_offset(ms)
    Callbacks fournies au constructeur : notify(msg, kind), log(msg), minimize(), import_file(path, meta)
    -> song_id, get_instrument_id() -> str, get_player_name() -> str, save() (écrit config.json ; posé par
    OnlineService = core.save_config(cfg)).

Messages (Partie C du plan) — client -> serveur : create, join, leave, ping, set_song, song_status,
set_instrument, ready, start, cancel, stop, player_state, kick ; serveur -> client : joined, state, start,
cancelled, stop, pong, error, bye.
Jetons dans le premier message : `token` = jeton de session Discord (obligatoire, jamais dans l'URL) ;
`seat_token` = jeton de siège reçu dans `joined` et renvoyé dans `join` pour reprendre son siège (reconnexion).
Après `start` / `cancelled` / `stop`, le serveur diffuse aussi un `state` complet : une deadline déjà armée
n'est jamais recalculée sur ce `state`. `stop` est réservé au chef ; `ready` est informatif.
"""
import json
import os
import shutil
import tempfile
import threading
import time
from collections import deque

import core
from platform_io import mouse_button_down
from sync import _Aborted, choose_common_extra, ensure_defaults
from version import VERSION

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def now_ms():
    return time.perf_counter() * 1000.0


def normalize_code(code):
    """Saisie du code de salon : majuscules, sans espaces ni tirets (l'alphabet du serveur n'a ni 0/O ni 1/I,
    le serveur répond room_not_found si le code est mal lu)."""
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())[:8]


# ---------------------------------------------------------------- horloge
class ClockSync:
    """NTP simplifié sur la WebSocket : ping{t0} -> pong{t0, t1, t2} -> t3.
    rtt = (t3−t0) − (t2−t1) ; offset = ((t1−t0) + (t2−t3)) / 2. Garde 32 échantillons, rejette rtt > 1000 ms,
    retient le quartile des plus petits RTT (au moins 8) filtré à rtt_min×1,5+5, offset = médiane ;
    err_ms = max(rtt_min/2, dispersion/2). Un saut > 50 ms sur un bon échantillon (veille/reprise) remet à
    zéro ; les échantillons expirent après 3 min."""
    MAXLEN = 32
    MAX_RTT_MS = 1000.0
    JUMP_MS = 50.0
    EXPIRE_S = 180.0
    MIN_SAMPLES = 4
    MIN_CANDIDATES = 8
    VALID_AGE_S = 60.0

    def __init__(self, now=None, log=None):
        self._now = now or time.perf_counter
        self.log = log or (lambda m: None)
        self.samples = deque(maxlen=self.MAXLEN)     # (rtt_ms, offset_ms, t_local_s)
        self.offset_ms = None
        self.rtt_min_ms = None
        self.err_ms = None
        self.updated_at = None
        self.resets = 0
        self.rejected = 0
        self._lock = threading.Lock()

    def add(self, t0, t1, t2, t3):
        """Ajoute un échantillon (ms). Renvoie False s'il est rejeté."""
        rtt = (t3 - t0) - (t2 - t1)
        if rtt < 0 or rtt > self.MAX_RTT_MS:
            self.rejected += 1
            return False
        offset = ((t1 - t0) + (t2 - t3)) / 2.0
        with self._lock:
            self._expire()
            if self.offset_ms is not None and self.rtt_min_ms is not None:
                good = rtt <= self.rtt_min_ms * 1.5 + 5
                if good and abs(offset - self.offset_ms) > self.JUMP_MS:
                    self.log(f"horloge : saut de {offset - self.offset_ms:+.0f} ms (veille ?), remise à zéro")
                    self.samples.clear()
                    self.resets += 1
            self.samples.append((rtt, offset, self._now()))
            self.updated_at = self._now()
            self._recompute()
        return True

    def _recompute(self):
        if not self.samples:
            self.offset_ms = self.rtt_min_ms = self.err_ms = None
            return
        by_rtt = sorted(self.samples, key=lambda s: s[0])
        rtt_min = by_rtt[0][0]
        # quartile des plus petits RTT, mais au moins 8 echantillons (toute la rafale de connexion) : la mediane
        # lisse la granularite de l'horloge serveur (15,6 ms sous Windows) et la gigue residuelle
        q = min(len(by_rtt), max(self.MIN_CANDIDATES, (len(by_rtt) + 3) // 4))
        cand = [s for s in by_rtt[:q] if s[0] <= rtt_min * 1.5 + 5] or [by_rtt[0]]
        offs = sorted(s[1] for s in cand)
        n = len(offs)
        median = offs[n // 2] if n % 2 else (offs[n // 2 - 1] + offs[n // 2]) / 2.0
        self.offset_ms = median
        self.rtt_min_ms = rtt_min
        self.err_ms = max(rtt_min / 2.0, (offs[-1] - offs[0]) / 2.0)

    def _expire(self):
        if self.updated_at is not None and self._now() - self.updated_at > self.EXPIRE_S:
            self.samples.clear()
            self._recompute()
            self.updated_at = None

    def expire(self):
        with self._lock:
            self._expire()

    def age_s(self):
        return None if self.updated_at is None else self._now() - self.updated_at

    def valid(self):
        with self._lock:
            self._expire()
            return (len(self.samples) >= self.MIN_SAMPLES and self.updated_at is not None
                    and self._now() - self.updated_at < self.VALID_AGE_S)

    def server_now_ms(self):
        if self.offset_ms is None:
            return None
        return self._now() * 1000.0 + self.offset_ms

    def to_local(self, srv_ms):
        """Instant perf_counter (secondes) correspondant à un instant serveur (ms)."""
        if self.offset_ms is None:
            raise RuntimeError("horloge non synchronisée")
        return (float(srv_ms) - self.offset_ms) / 1000.0

    def status(self):
        age = self.age_s()
        return {"offset_ms": None if self.offset_ms is None else round(self.offset_ms, 2),
                "rtt_ms": None if self.rtt_min_ms is None else round(self.rtt_min_ms, 1),
                "err_ms": None if self.err_ms is None else round(self.err_ms, 1),
                "age_s": None if age is None else round(age, 1),
                "samples": len(self.samples), "valid": self.valid(), "resets": self.resets}


# ---------------------------------------------------------------- session
class RoomSession:
    """Un salon : connexion WebSocket unique (websocket-client, import paresseux), horloge, fichier partagé,
    armement du départ, arrêt synchronisé, reconnexion avec reprise du siège."""
    BACKOFF = (1, 2, 4, 8, 10)
    RECONNECT_MAX_S = 90.0
    HEARTBEAT_S = 5.0
    PONG_TIMEOUT_S = 12.0
    BURST_GAP_S = 0.1
    STATES = ("idle", "connecting", "lobby", "downloading", "armed", "playing")

    def __init__(self, client, player, cfg, account=None, log=print, notify=None, logfile=None, minimize=None,
                 import_file=None, get_instrument_id=None, get_player_name=None, ws_factory=None, save=None):
        self.client = client
        self.player = player
        self.cfg = cfg
        self.account = account
        self._ui_log = log
        self.notify = notify or (lambda msg, kind="info": None)
        self.logfile = logfile
        self.minimize = minimize or (lambda: None)
        self.import_file = import_file
        self.get_instrument_id = get_instrument_id or (lambda: getattr(getattr(player, "instrument", None), "id", ""))
        self.get_player_name = get_player_name or (lambda: "Joueur")
        self._ws_factory = ws_factory
        self.save_cfg = save            # callable qui ecrit config.json (last_room, net_offset_ms) ; None = rien
        ensure_defaults(cfg)
        self.clock = ClockSync(log=self.log)
        self.backoff = list(self.BACKOFF)
        self.reconnect_max_s = self.RECONNECT_MAX_S
        self.heartbeat_s = self.HEARTBEAT_S
        self.pong_timeout_s = self.PONG_TIMEOUT_S
        self._t0 = time.perf_counter()
        self._lock = threading.RLock()
        self._leaving = threading.Event()
        self._abort = threading.Event()
        self._hb_stop = threading.Event()
        self._ws = None
        self._ws_thread = None
        self._hb_thread = None
        self._arm_thread = None
        self._first_msg = None
        self._fatal = False
        self._lost_at = None
        self._last_pong = 0.0
        self._stop_pending = False
        self._ensure_gen = 0
        self._prepared = None
        self._prep_key = None
        self._have = None           # (sha256, key_shift) du fichier prêt localement
        self._song_path = None
        self._reset_fields()

    def _reset_fields(self):
        self.state = "idle"
        self.room_state = "lobby"
        self.code = None
        self.player_id = None
        self.seat_token = None
        self.host_id = None
        self.players = []
        self.song = None
        self.countdown_s = None
        self.start_at_ms = None
        self.max_players = None
        self.seq = 0
        self.min_version = ""
        self.message = ""
        self.error = ""
        self.connected = False
        self.deadline = None
        self.armed_start_at = None
        self._aborted_start_at = None   # depart annule localement : ne pas se rearmer sur le state suivant
        self._pending_have = None       # song_status{have} a envoyer au retour au lobby (arrivee pendant la lecture)
        self._stop_pending = False

    # ---- journal
    def log(self, msg):
        """Journal de l'interface + fichier salon.log (horodaté depuis la connexion), comme multi.log."""
        self._ui_log(msg)
        if self.logfile:
            try:
                with open(self.logfile, "a", encoding="utf-8") as f:
                    f.write(f"[{time.perf_counter() - self._t0:8.3f}s] {msg}\n")
            except Exception:  # noqa
                pass

    def _log_header(self, what):
        if self.logfile:
            try:
                if os.path.exists(self.logfile) and os.path.getsize(self.logfile) > 512 * 1024:
                    os.remove(self.logfile)
            except Exception:  # noqa
                pass
        self._t0 = time.perf_counter()
        m = self.cfg.get("multi", {})
        self.log(f"DodoTopia salon {time.strftime('%Y-%m-%d %H:%M:%S')} {what} : version {VERSION}, "
                 f"avance/retard {m.get('net_offset_ms', 0)} ms, serveur {self.client.ws_url()}")

    def _save(self):
        """Ecrit config.json via le callback de l'application (jamais directement : les tests ont un cfg factice)."""
        if self.save_cfg is None:
            return
        try:
            self.save_cfg()
        except Exception as e:  # noqa
            self.log(f"salon : sauvegarde des réglages : {e}")

    # ---- API
    def active(self):
        return self.state != "idle"

    def is_host(self):
        return self.player_id is not None and self.host_id == self.player_id

    def me(self):
        for p in self.players:
            if p.get("id") == self.player_id:
                return p
        return {}

    def create(self, name=None, max_players=None):
        """Crée un salon (on en devient le chef)."""
        msg = {"type": "create", "name": self._name(name), "instrument": self._instrument(), "version": VERSION}
        if max_players:
            msg["max_players"] = int(max_players)
        return self._connect(msg, "création")

    def join(self, code, name=None):
        code = normalize_code(code)
        if len(code) < 4:
            self.notify("Code de salon invalide", "warn")
            return False
        msg = {"type": "join", "room_code": code, "name": self._name(name), "instrument": self._instrument(),
               "version": VERSION}
        return self._connect(msg, f"rejoint {code}")

    def leave(self):
        """Quitte le salon (aucune reconnexion) ; une lecture en cours continue localement."""
        if self.state == "idle" and not (self._ws_thread and self._ws_thread.is_alive()):
            return False
        self.log("salon : on quitte")
        self._leaving.set()
        self._send({"type": "leave"})
        self._disarm("salon quitté")
        self._close_ws()
        return True

    def set_song(self, spec):
        """Chef : choisit le fichier du salon (song_id local, chemin, ou identifiant en ligne). Calcule sha256,
        durée, tonalité commune ; dépose le fichier sur le serveur si nécessaire. Dans un thread."""
        if self.state == "idle":
            self.notify("Pas de salon", "warn")
            return False
        if not self.is_host():
            self.notify("Seul le chef du salon choisit la musique", "warn")
            return False
        if self.room_state != "lobby":
            self.notify("Attends la fin de la lecture", "warn")
            return False
        threading.Thread(target=self._set_song_run, args=(spec,), name="room-song", daemon=True).start()
        return True

    def set_instrument(self, inst_id):
        if self.state == "idle":
            return False
        self._send({"type": "set_instrument", "instrument": str(inst_id)})
        if self._have and self._song_path:
            sha, key_shift = self._have
            threading.Thread(target=self._safe_prepare, args=(self._song_path, sha, key_shift),
                             name="room-prepare", daemon=True).start()
        return True

    def on_instrument_change(self, inst):
        """Appelé par l'application quand l'instrument change (F12, clic)."""
        return self.set_instrument(getattr(inst, "id", inst))

    def set_ready(self, on):
        if self.state == "idle":
            return False
        return self._send({"type": "ready", "ready": bool(on)})

    def start(self, countdown_s=None, force=False):
        if not self.is_host():
            self.notify("Seul le chef lance le top départ", "warn")
            return False
        blocker = self._start_blocker()
        if blocker and not force:
            self.notify(blocker, "warn")
            return False
        msg = {"type": "start"}
        if countdown_s:
            msg["countdown_s"] = max(3, min(15, int(countdown_s)))
        if force:
            msg["force"] = True
        return self._send(msg)

    def cancel(self):
        if self.state == "idle":
            return False
        return self._send({"type": "cancel"})

    def stop(self):
        """Chef : arrêt synchronisé de tout le salon (le serveur fixe l'instant)."""
        if self.state == "idle":
            return False
        if not self.is_host():
            self.notify("Seul le chef arrête tout le monde (F7 : arrêt local)", "warn")
            return False
        return self._send({"type": "stop"})

    def set_net_offset(self, ms):
        m = ensure_defaults(self.cfg)
        try:
            m["net_offset_ms"] = max(-300, min(300, int(round(float(ms)))))
        except (TypeError, ValueError):
            return m["net_offset_ms"]
        self._save()
        return m["net_offset_ms"]

    def on_f6(self):
        """Raccourci F6 en mode salon : lobby -> chef : top départ (si possible), autres : bascule Prêt ;
        compte à rebours -> chef : annuler, autres : annulation locale ; lecture -> arrêt synchronisé."""
        st = self.state
        if st == "idle":
            self.notify("Crée ou rejoins un salon (onglet En ligne)", "warn")
            return False
        if st in ("connecting", "downloading"):
            self.notify("Connexion ou téléchargement en cours…", "info")
            return False
        if st == "armed":
            if self.is_host():
                return self.cancel()
            self._disarm("stop")
            return True
        if st == "playing":
            return self.stop() if self.is_host() else self.stop_local("stop")
        # lobby
        if self.room_state == "countdown":
            self.notify("Compte à rebours en cours (tu n'as pas le fichier)", "warn")
            return False
        if self.room_state == "playing":
            self.notify("Lecture en cours : attends la fin", "warn")
            return False
        if self.is_host():
            return self.start()
        return self.set_ready(not bool(self.me().get("ready")))

    def stop_local(self, reason="stop"):
        """F7 : arrêt local seulement (les autres continuent)."""
        if self.state == "armed":
            self._disarm(reason)
            return True
        if self.state == "playing":
            self.player.stop(reason=reason)
            return True
        return False

    def on_player_stop(self, reason=""):
        """Appelé par Player.stop() / une frappe clavier pendant l'attente : annulation locale."""
        if self.state == "armed":
            self._disarm(reason or "stop")
        # en lecture : _watch_end voit le Player s'arrêter et envoie player_state{aborted}

    def close(self):
        self.leave()
        self._hb_stop.set()
        t = self._ws_thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2)

    def status(self):
        now = time.perf_counter()
        left = None
        if self.state == "armed" and self.deadline is not None:
            left = max(0.0, self.deadline - now)
        elif self.room_state == "countdown" and self.start_at_ms and self.clock.offset_ms is not None:
            left = max(0.0, self.clock.to_local(self.start_at_ms) - now)
        m = self.cfg.get("multi", {})
        me = self.me()
        host = self.is_host()
        role = "host" if host else ("guest" if self.player_id is not None else "")
        blocker = self._start_blocker() if host else ""
        return {
            "enabled": m.get("mode") == "room", "state": self.state, "mode": "room", "role": role,
            "seconds_left": round(left, 1) if left is not None else None, "message": self.message,
            "player_id": self.player_id, "leader_id": self.host_id,
            "players": [p.get("id") for p in self.players],
            "room": {
                "code": self.code, "connected": self.connected, "state": self.room_state, "host_id": self.host_id,
                "song": dict(self.song) if self.song else None, "players": [dict(p) for p in self.players],
                "countdown_s": self.countdown_s, "start_at_ms": self.start_at_ms, "max_players": self.max_players,
                "seq": self.seq, "clock": self.clock.status(), "net_offset_ms": m.get("net_offset_ms", 0),
                "can_start": host and not blocker, "start_blocker": blocker,
                "me": {"id": self.player_id, "ready": bool(me.get("ready")), "has_file": self._have is not None,
                       "host": host, "name": me.get("name")},
                "error": self.error, "last_room": m.get("last_room", ""), "min_version": self.min_version,
            },
        }

    # ---- outils
    def _name(self, name=None):
        name = str(name or "").strip()
        if not name:
            try:
                name = str(self.get_player_name() or "").strip()
            except Exception:  # noqa
                name = ""
        return (name or "Joueur")[:24]

    def _instrument(self):
        try:
            return str(self.get_instrument_id() or "")
        except Exception:  # noqa
            return ""

    def _token(self):
        return getattr(self.account, "token", None) if self.account is not None else None

    def _start_blocker(self):
        if self.state == "idle":
            return "Pas de salon"
        if not self.is_host():
            return "Seul le chef lance le top départ"
        if self.room_state != "lobby":
            return "Déjà en cours"
        if not self.song:
            return "Choisis d'abord une musique"
        missing = [p.get("name") or str(p.get("id")) for p in self.players
                   if p.get("connected", True) and not p.get("have_song")]
        if missing:
            return "Fichier pas encore reçu : " + ", ".join(missing[:4])
        return ""

    def _sleep_until(self, t):
        while True:
            if self._abort.is_set():
                raise _Aborted()
            rem = t - time.perf_counter()
            if rem <= 0:
                return
            time.sleep(min(rem, 0.005))

    def _check_abort(self):
        if self._abort.is_set():
            raise _Aborted()

    def _send(self, msg):
        ws = self._ws
        if ws is None or not self.connected:
            return False
        try:
            ws.send(json.dumps(msg))
            return True
        except Exception as e:  # noqa
            self.log(f"salon : envoi {msg.get('type')} impossible ({e})")
            return False

    def _close_ws(self):
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa
                pass

    # ---- connexion
    def _connect(self, first_msg, what):
        with self._lock:
            if self.state != "idle" or (self._ws_thread and self._ws_thread.is_alive()):
                self.notify("Déjà dans un salon (quitte-le d'abord)", "warn")
                return False
            factory = self._ws_factory
            if factory is None:
                try:
                    import websocket
                except ImportError:
                    self.notify("Module websocket-client manquant : pip install websocket-client", "warn")
                    return False

                def factory(url, **cbs):
                    return websocket.WebSocketApp(url, **cbs)
            self._factory = factory
            self._reset_fields()
            tok = self._token()
            if self.account is not None and not tok:
                self.notify("Connecte-toi avec Discord (onglet En ligne) pour utiliser les salons", "warn")
                return False
            if tok:
                first_msg["token"] = tok      # jeton de session Discord ; `seat_token` = jeton de siège (reprise)
            self._first_msg = first_msg
            self._leaving.clear()
            self._abort.clear()
            self._hb_stop.clear()
            self._fatal = False
            self._lost_at = None
            self._have = None
            self._prepared = None
            self._prep_key = None
            self._song_path = None
            self.state = "connecting"
            self.message = "Connexion au serveur…"
            self._log_header(what)
            self._ws_thread = threading.Thread(target=self._ws_loop, name="room-ws", daemon=True)
            self._ws_thread.start()
            self._hb_thread = threading.Thread(target=self._heartbeat, name="room-hb", daemon=True)
            self._hb_thread.start()
            return True

    def _run_kwargs(self):
        if self._ws_factory is not None:
            return {}
        kw = {"ping_interval": 0}
        try:
            import certifi
            kw["sslopt"] = {"ca_certs": certifi.where()}
        except Exception:  # noqa
            pass
        return kw

    def _ws_loop(self):
        attempt = 0
        while not self._leaving.is_set():
            url = self.client.ws_url()
            try:
                ws = self._factory(url, on_open=self._on_open, on_message=self._on_message,
                                   on_error=self._on_ws_error, on_close=self._on_close)
                self._ws = ws
                ws.run_forever(**self._run_kwargs())
            except Exception as e:  # noqa
                self.log(f"salon : websocket : {e}")
            self.connected = False
            if self._leaving.is_set() or self._fatal:
                break
            if self.seat_token is None:
                self.notify("Serveur de salons injoignable", "warn")
                self.log("salon : connexion impossible")
                break
            if self._lost_at is None:
                self._lost_at = time.perf_counter()
                attempt = 0
            if time.perf_counter() - self._lost_at > self.reconnect_max_s:
                self.notify("Connexion au salon perdue", "warn")
                self.log("salon : reconnexion abandonnée")
                break
            delay = self.backoff[min(attempt, len(self.backoff) - 1)]
            attempt += 1
            self.message = f"Connexion perdue, nouvel essai dans {delay:g} s"
            self.log(f"salon : connexion perdue, nouvel essai dans {delay:g} s")
            if self._leaving.wait(delay):
                break
            self._first_msg = {"type": "join", "room_code": self.code, "name": self._name(),
                               "instrument": self._instrument(), "version": VERSION, "seat_token": self.seat_token}
            tok = self._token()
            if tok:
                self._first_msg["token"] = tok
        self._finish_session()

    def _finish_session(self):
        self._hb_stop.set()
        self._disarm("salon fermé")
        with self._lock:
            self._ws = None
            self.connected = False
            self._stop_pending = False
            if self.state != "idle":
                self.state = "idle"
            self.message = self.message or "Salon quitté"
        self.log("salon : session terminée")

    def _heartbeat(self):
        while not self._hb_stop.wait(self.heartbeat_s):
            if not self.connected:
                continue
            if time.perf_counter() - self._last_pong > self.pong_timeout_s:
                self.log(f"salon : pas de pong depuis {self.pong_timeout_s:g} s, reconnexion")
                self._close_ws()
                continue
            self._send(self._ping_msg())

    def _ping_msg(self):
        return {"type": "ping", "t0": now_ms()}

    def _burst(self, n):
        def run():
            for _ in range(n):
                if not self.connected or self._leaving.is_set():
                    return
                self._send(self._ping_msg())
                time.sleep(self.BURST_GAP_S)
        threading.Thread(target=run, name="room-ping", daemon=True).start()

    # ---- callbacks websocket
    def _on_open(self, ws, *args):
        self.connected = True
        self._last_pong = time.perf_counter()
        self._send(self._first_msg)

    def _on_close(self, ws, *args):
        self.connected = False

    def _on_ws_error(self, ws, err, *args):
        if not self._leaving.is_set():
            self.log(f"salon : {err}")

    def _on_message(self, ws, raw, *args):
        try:
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                return
            t = msg.get("type")
            handler = getattr(self, f"_on_{t}", None) if t and t != "message" else None
            if handler is None or t in ("open", "close", "ws_error"):
                self.log(f"salon : message inconnu {t!r}")
                return
            handler(msg)
        except Exception as e:  # noqa
            self.log(f"salon : erreur sur {raw[:80]!r} : {e}")

    def _on_joined(self, m):
        reconnect = self.seat_token is not None
        with self._lock:
            self.code = m.get("room_code") or self.code
            self.player_id = m.get("player_id", self.player_id)
            self.seat_token = m.get("seat_token") or m.get("token") or self.seat_token
            self.min_version = str(m.get("min_version") or "")
            if m.get("host") is not None:
                self.host_id = self.player_id if m.get("host") else self.host_id
            self._lost_at = None
            self.error = ""
            if self.state == "connecting":
                self.state = "lobby"
            self.message = f"Salon {self.code}"
            mm = ensure_defaults(self.cfg)
            if mm.get("last_room") != self.code:
                mm["last_room"] = self.code
                self._save()
        self.log(f"salon : {'reconnecté' if reconnect else 'entré'} dans {self.code} (joueur {self.player_id})")
        self._burst(8)
        if not reconnect:
            self.notify(f"Salon {self.code}", "ok")

    def _on_state(self, m):
        with self._lock:
            self.seq = int(m.get("seq") or self.seq)
            self.room_state = m.get("state") or "lobby"
            self.host_id = m.get("host_id", self.host_id)
            self.countdown_s = m.get("countdown_s")
            self.start_at_ms = m.get("start_at_ms")
            self.max_players = m.get("max_players")
            self.song = m.get("song") if isinstance(m.get("song"), dict) and m["song"].get("sha256") else None
            self.players = [p for p in (m.get("players") or []) if isinstance(p, dict)]
            if self.code is None:
                self.code = m.get("room_code")
            song = self.song
            want = (song["sha256"], int(song.get("key_shift") or 0)) if song else None
            st = self.state
        if want is None:
            self._have = None
            self._prepared = None
            self._prep_key = None
            self._song_path = None
        elif want != self._have:
            self._ensure_song(song)
        if self.room_state == "countdown" and self.start_at_ms and st in ("lobby", "downloading") and want and want == self._have:
            self._arm(self.start_at_ms)
        elif self.room_state == "lobby":
            if self._pending_have and want and self._pending_have == want[0]:
                self._pending_have = None
                self._send({"type": "song_status", "sha256": want[0], "have": True})
            if st == "armed":
                self._disarm("annulé")
            elif st == "playing" and not self._stop_pending:
                self.log("salon : le serveur est revenu au lobby, arrêt local")
                self.player.stop(reason="fin du salon")
        if st in ("lobby", "downloading"):
            if self.room_state == "playing":
                self.message = "Lecture en cours : attends la fin"
            elif st == "lobby":
                self.message = f"Salon {self.code} · {len(self.players)} joueur(s)"

    def _on_start(self, m):
        with self._lock:
            self.seq = int(m.get("seq") or self.seq)
            self.room_state = "countdown"
            self.start_at_ms = m.get("start_at_ms")
            self.countdown_s = m.get("countdown_s")
            self._aborted_start_at = None
            if isinstance(m.get("song"), dict):
                self.song = m["song"]
            if m.get("players"):
                self.players = [p for p in m["players"] if isinstance(p, dict)]
            song = self.song
        self._burst(4)
        want = (song["sha256"], int(song.get("key_shift") or 0)) if song else None
        if want and want == self._have and self.start_at_ms:
            self._arm(self.start_at_ms)
        else:
            self.message = "Pas le fichier : tu regardes"
            self._send({"type": "player_state", "status": "no_song"})
            self.log("salon : top départ reçu sans le fichier")

    def _on_cancelled(self, m):
        by = m.get("by")
        name = next((p.get("name") for p in self.players if p.get("id") == by), None) or "le chef"
        self.room_state = "lobby"
        self.start_at_ms = None
        self._disarm(f"annulé par {name}")
        self.notify(f"Top départ annulé par {name}", "warn")

    def _on_stop(self, m):
        at_ms = m.get("at_ms")
        self._stop_pending = True
        threading.Thread(target=self._stop_run, args=(at_ms,), name="room-stop", daemon=True).start()

    def _stop_run(self, at_ms):
        try:
            t = self.clock.to_local(at_ms) if at_ms is not None and self.clock.offset_ms is not None else time.perf_counter() + 0.25
            while time.perf_counter() < t and not self._leaving.is_set():
                time.sleep(min(0.005, max(0.0, t - time.perf_counter())))
            if self.state == "armed":
                self._disarm("stop du salon")
            elif self.state == "playing":
                self.player.stop(reason="stop du salon")
            self.log(f"salon : stop synchronisé (écart {(time.perf_counter() - t) * 1000:+.1f} ms)")
        finally:
            self._stop_pending = False
            self.room_state = "lobby"

    def _on_pong(self, m):
        t3 = now_ms()
        try:
            self.clock.add(float(m["t0"]), float(m["t1"]), float(m["t2"]), t3)
        except (KeyError, TypeError, ValueError):
            return
        self._last_pong = time.perf_counter()

    def _on_error(self, m):
        code, text, fatal = m.get("code", ""), m.get("message") or m.get("code") or "erreur", bool(m.get("fatal"))
        self.error = str(text)
        self.log(f"salon : erreur {code} : {text}" + (" (fatale)" if fatal else ""))
        self.notify(str(text), "warn")
        if fatal:
            self._fatal = True
            self.message = str(text)
            self._close_ws()

    def _on_bye(self, m):
        reason = m.get("reason") or "left"
        texts = {"left": "Salon quitté", "kicked": "Tu as été exclu du salon", "room_closed": "Salon fermé",
                 "replaced": "Connexion remplacée (ouverte ailleurs)"}
        self.message = texts.get(reason, f"Fin de session ({reason})")
        self.log(f"salon : bye ({reason})")
        if reason != "left":
            self.notify(self.message, "warn")
        self._fatal = True
        self._close_ws()

    # ---- fichier du salon
    def _ensure_song(self, song):
        self._ensure_gen += 1
        gen = self._ensure_gen
        threading.Thread(target=self._ensure_run, args=(dict(song), gen), name="room-file", daemon=True).start()

    def _ensure_run(self, song, gen):
        sha = str(song.get("sha256") or "")
        key_shift = int(song.get("key_shift") or 0)
        name = song.get("name") or "musique"
        tmpdir = None
        try:
            lib = self.player.library
            sid = lib.find_by_sha(sha)
            path = os.path.join(self.player.songs_folder, sid) if sid else None
            if not path or not os.path.isfile(path):
                if self.state == "lobby":
                    self.state = "downloading"
                self.message = f"Téléchargement de « {name} »…"
                self.log(f"salon : téléchargement de {name} ({sha[:12]}…)")
                tmpdir = tempfile.mkdtemp(prefix="dodotopia-salon-")
                tmp = os.path.join(tmpdir, sha + ".mid")
                if song.get("source") == "library" and song.get("online_id") is not None:
                    url = f"/api/songs/{song['online_id']}/download"
                else:
                    url = f"/api/rooms/{self.code}/song/{sha}"
                self.client.download(url, tmp, sha)
                if self.import_file is None:
                    raise RuntimeError("import de fichier indisponible")
                sid = self.import_file(tmp, {"title": name, "sha256": sha, "online_id": song.get("online_id")})
                if isinstance(sid, (list, tuple)):        # _import_files(paths) -> (added, skipped)
                    sid = sid[0][0] if sid and sid[0] else None
                if not sid:
                    raise RuntimeError("import du fichier refusé")
                path = os.path.join(self.player.songs_folder, sid)
                lib.set_online(sid, online_id=song.get("online_id"), sha256=sha)
                lib.sha256(sid, path)
            if gen != self._ensure_gen:
                return
            self._prepare(path, sha, key_shift)
            self._have = (sha, key_shift)
            self._song_path = path
            if self.state == "downloading":
                self.state = "lobby"
            self.message = f"Prêt : {name}"
            if self.room_state == "playing":
                self._pending_have = sha        # le serveur compterait sur notre `ended` pour finir la manche
                self.message += " · lecture en cours, attends la fin"
            else:
                self._send({"type": "song_status", "sha256": sha, "have": True})
            self.log(f"salon : fichier prêt ({name}, tonalité {key_shift:+d})")
            if self.room_state == "countdown" and self.start_at_ms:
                self._arm(self.start_at_ms)
        except Exception as e:  # noqa
            if gen != self._ensure_gen:
                return
            self._have = None
            self._prepared = None
            if self.state == "downloading":
                self.state = "lobby"
            self.message = f"Fichier indisponible : {e}"
            self.notify(f"Fichier du salon indisponible : {e}", "warn")
            self.log(f"salon : fichier : {e}")
            self._send({"type": "song_status", "sha256": sha, "have": False})
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

    def _prepare(self, path, sha, key_shift):
        """Chronologie prête à jouer, en cache par (sha256, instrument, tonalité, durée d'appui, mode d'appui)."""
        p = self.player
        inst = p.instrument
        key = (sha, getattr(inst, "id", ""), int(key_shift), p.cfg.get("hold_time", 0.04), p.cfg.get("hold_mode", "note"))
        if self._prep_key == key and self._prepared is not None:
            return self._prepared
        prepared = p.prepare(path, inst, "game", extra=int(key_shift))
        self._prepared, self._prep_key = prepared, key
        try:
            mine = choose_common_extra(self._notes_of(path))
            if mine != int(key_shift):
                self.log(f"salon : tonalité du chef {key_shift:+d}, calcul local {mine:+d} (on suit le chef)")
        except Exception:  # noqa
            pass
        return prepared

    def _safe_prepare(self, path, sha, key_shift):
        try:
            self._prepare(path, sha, key_shift)
        except Exception as e:  # noqa
            self.log(f"salon : préparation : {e}")

    def _notes_of(self, path):
        cfg = dict(self.cfg)
        cfg["ignore_drums"] = True
        return [n for _, ns in core.parse_midi(path, cfg) for n, _, _ in ns]

    def _set_song_run(self, spec):
        try:
            path, online_id = self._resolve_song(spec)
            sid = os.path.basename(path)
            lib = self.player.library
            sha = lib.sha256(sid, path)
            name = (lib.meta(sid).get("title") or core.clean_title(sid))[:120]
            duration_ms = max(1, int(round(float(self.player.song_duration(path)) * 1000)))
            key_shift = choose_common_extra(self._notes_of(path))
            if online_id is None:
                online_id = lib.meta(sid).get("online_id")
            source = "library" if online_id is not None else "room"
            if source == "room":
                self.message = "Envoi du fichier au salon…"
                self.client.upload(f"/api/rooms/{self.code}/song", {"title": name}, "file", path)
            msg = {"type": "set_song", "sha256": sha, "name": name, "duration_ms": duration_ms,
                   "key_shift": int(key_shift), "source": source}
            if online_id is not None:
                msg["online_id"] = online_id
            self._send(msg)
            self.log(f"salon : musique {name} ({source}, tonalité {key_shift:+d}, {duration_ms / 1000:.0f} s)")
        except Exception as e:  # noqa
            self.notify(f"Musique impossible à choisir : {e}", "warn")
            self.log(f"salon : set_song : {e}")

    def _resolve_song(self, spec):
        """-> (chemin local, online_id|None) ; télécharge depuis la bibliothèque en ligne si besoin."""
        p = self.player
        online_id = None
        path = None
        if isinstance(spec, dict):
            online_id = spec.get("online_id")
            path = spec.get("path") or spec.get("song_id")
        elif isinstance(spec, int):
            online_id = spec
        else:
            path = str(spec or "")
        if path:
            cand = path if os.path.isfile(path) else os.path.join(p.songs_folder, os.path.basename(path))
            if os.path.isfile(cand):
                return cand, online_id
            if online_id is None and str(path).isdigit():
                online_id = int(path)
        if online_id is None:
            raise RuntimeError("fichier introuvable")
        sid = p.library.find_by_online_id(online_id)
        if sid and os.path.isfile(os.path.join(p.songs_folder, sid)):
            return os.path.join(p.songs_folder, sid), online_id
        info = self.client.get(f"/api/songs/{online_id}", auth=False)
        sha = str(info.get("sha256") or "")
        tmpdir = tempfile.mkdtemp(prefix="dodotopia-salon-")
        try:
            tmp = os.path.join(tmpdir, (sha or str(online_id)) + ".mid")
            self.client.download(f"/api/songs/{online_id}/download", tmp, sha or None)
            if self.import_file is None:
                raise RuntimeError("import de fichier indisponible")
            sid = self.import_file(tmp, {"title": info.get("title"), "sha256": sha or core.file_sha256(tmp),
                                         "online_id": online_id})
            if isinstance(sid, (list, tuple)):
                sid = sid[0][0] if sid and sid[0] else None
            if not sid:
                raise RuntimeError("import du fichier refusé")
            p.library.set_online(sid, online_id=online_id, sha256=sha or None)
            return os.path.join(p.songs_folder, sid), online_id
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ---- armement et lecture
    def _arm(self, start_at_ms):
        p = self.player
        with self._lock:
            if self.state == "playing" or (self.state == "armed" and self.armed_start_at == start_at_ms):
                return False
            if start_at_ms == self._aborted_start_at:
                return False
            if self.state == "armed":
                self._disarm("nouveau départ")
            if self._have is None or self._song_path is None:
                self._send({"type": "player_state", "status": "no_song"})
                return False
            if self.clock.offset_ms is None:
                self.notify("Horloge non synchronisée : impossible de se caler", "warn")
                self._send({"type": "player_state", "status": "aborted", "reason": "horloge"})
                return False
            try:
                prepared = self._prepare(self._song_path, *self._have)
            except Exception as e:  # noqa
                self.notify(f"Fichier illisible : {e}", "warn")
                self._send({"type": "player_state", "status": "aborted", "reason": "fichier"})
                return False
            if p.state != "stopped":
                p.stop(join=True)
            m = ensure_defaults(self.cfg)
            net = float(m.get("net_offset_ms", 0) or 0) / 1000.0
            self.deadline = self.clock.to_local(start_at_ms) + net
            self.armed_start_at = start_at_ms
            self._abort.clear()
            with p._lock:
                p.state = "sync"
                p.target = "game"
                p._expected = {}
                p.last_stop_reason = ""
            self.state = "armed"
            left = self.deadline - time.perf_counter()
            self.message = f"Top départ dans {left:.1f} s"
            c = self.clock
            if not c.valid():
                self.log("salon : horloge peu fiable (moins de 4 échantillons ou trop ancienne)")
            self.log(f"salon : armé, start_at {start_at_ms:.0f}, deadline dans {left:.3f} s, offset "
                     f"{c.offset_ms:.1f} ± {c.err_ms:.1f} ms, rtt_min {c.rtt_min_ms:.1f} ms, avance/retard {net * 1000:+.0f} ms")
        try:
            self.minimize()
        except Exception:  # noqa
            pass
        self._send({"type": "player_state", "status": "armed", "clock": self.clock.status()})
        self._arm_thread = threading.Thread(target=self._arm_run, args=(prepared,), name="room-arm", daemon=True)
        self._arm_thread.start()
        return True

    def _arm_run(self, prepared):
        p = self.player
        try:
            stop_on_input = self.cfg.get("stop_on_input", True)
            mouse_check = 0.0
            while True:
                self._check_abort()
                now = time.perf_counter()
                if stop_on_input and now - mouse_check > 0.03:
                    mouse_check = now
                    if mouse_button_down():
                        raise _Aborted("clic souris")
                if now >= self.deadline - 0.12:
                    break
                time.sleep(0.005)
            with self._lock:
                self._check_abort()
                p.speed = 1.0
                p.lock_speed = True
                if self.deadline < time.perf_counter():
                    self.log("salon : départ déjà passé, rattrapage")
                p.play_at(self.deadline, prepared, "game")
                self.state = "playing"
                self.message = "Lecture synchronisée"
            self._send({"type": "player_state", "status": "playing"})
            self.log(f"salon : play_at({self.deadline:.3f})")
            self._watch_end()
        except _Aborted as e:
            self._disarm(str(e) or "stop")

    def _watch_end(self):
        p = self.player
        time.sleep(0.05)
        while p.state in ("playing", "paused") and not self._leaving.is_set():
            time.sleep(0.1)
        reason = getattr(p, "last_stop_reason", "") or ""
        with self._lock:
            if self.state == "playing":
                self.state = "lobby"
            self.deadline = None
            self.armed_start_at = None
            p.lock_speed = False
            self.message = "Lecture terminée" if not reason else f"Arrêt ({reason})"
        if reason and reason not in ("stop du salon", "fin du salon"):
            self._send({"type": "player_state", "status": "aborted", "reason": str(reason)[:200]})
        else:
            self._send({"type": "player_state", "status": "ended"})
        self.log(f"salon : lecture terminée ({reason or 'fin'})")

    def _disarm(self, reason):
        with self._lock:
            if self.state != "armed":
                return False
            self._abort.set()
            p = self.player
            with p._lock:
                if p.state == "sync":
                    p.state = "stopped"
                    p.last_stop_reason = reason
            self.state = "lobby"
            self.deadline = None
            self._aborted_start_at = self.armed_start_at
            self.armed_start_at = None
            self.message = f"Annulé ({reason})"
        self.log(f"salon : armement annulé ({reason})")
        self._send({"type": "player_state", "status": "aborted", "reason": str(reason)[:200]})
        return True
