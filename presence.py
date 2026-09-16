# -*- coding: utf-8 -*-
"""Discord Rich Presence : « Joue Clair de lune — Piano dans Heartopia » sur le profil Discord.

Tout est facultatif et silencieux : pas d'identifiant d'application, pypresence absent, Discord ferme ou
qui plante, et DodoTopia continue sans rien dire (chaque cause est journalisee une seule fois).

L'Api appelle `update(snapshot)` a chaque get_state() : l'appel ne fait que ranger l'activite voulue. Un fil
daemon se connecte au Discord local (reconnexion avec attente croissante jusqu'a 60 s) et n'envoie une mise a
jour que si l'activite a change, au plus une fois toutes les 15 s (limite de Discord : 5 mises a jour / 20 s).

Instantane attendu (voir Api._activity_snapshot) :
    {"kind": "play" | "draw" | "cook" | "room" | "idle", "title", "instrument", "started_at", "dishes",
     "room_code", "players", "max_players", "server_url"}
"""
import asyncio
import logging
import threading
import time

import deeplink
import i18n

log = logging.getLogger("presence")

# Identifiant de l'application Discord (Developer Portal > Applications > DodoTopia > Application ID).
# Vide = Rich Presence desactivee. Les images (cle `logo`) se declarent dans Rich Presence > Art Assets.
DISCORD_CLIENT_ID = ""
LARGE_IMAGE = "logo"
UPDATE_INTERVAL = 15.0
MIN_BACKOFF = 2.0
MAX_BACKOFF = 60.0
IDLE_WAIT = 1.0


def room_invite_url(server_url, code):
    """Page publique d'invitation d'un salon (`{server_url}/salon/{code}`) ; "" si l'adresse du serveur n'est
    pas en https ou si le code n'est pas un code de salon valide."""
    base = str(server_url or "").strip().rstrip("/")
    code = str(code or "").strip().upper()
    if not base.lower().startswith("https://") or not deeplink.parse(f"dodotopia://room/{code}"):
        return ""
    return f"{base}/salon/{code}"


def build_activity(snap):
    """Instantane -> arguments de pypresence `Presence.update()`, ou None (effacer la presence)."""
    if not isinstance(snap, dict):
        return None
    kind = snap.get("kind")
    title = str(snap.get("title") or "")[:100]
    inst = str(snap.get("instrument") or "")[:60]
    act = {"large_image": LARGE_IMAGE, "large_text": "DodoTopia"}
    if kind == "room":
        n = int(snap.get("players") or 0)
        mx = int(snap.get("max_players") or 8)
        act["state"] = i18n.t("integrations.presence.room", n=n, max=mx)
        if title:
            act["details"] = i18n.t("integrations.presence.playing", title=title)
        url = room_invite_url(snap.get("server_url"), snap.get("room_code"))
        if url:
            act["buttons"] = [{"label": i18n.t("integrations.presence.join"), "url": url}]
    elif kind == "play":
        act["details"] = i18n.t("integrations.presence.playing", title=title)
        act["state"] = i18n.t("integrations.presence.playing_state", instrument=inst)
    elif kind == "draw":
        act["details"] = i18n.t("integrations.presence.drawing")
    elif kind == "cook":
        act["details"] = i18n.t("integrations.presence.cooking")
        dishes = int(snap.get("dishes") or 0)
        if dishes > 0:
            act["state"] = i18n.t("integrations.presence.dishes", n=dishes)
    else:
        return None
    started = snap.get("started_at")
    if started and kind in ("play", "room", "draw", "cook"):
        act["start"] = int(started)
    # Discord refuse les champs de moins de 2 caracteres
    for k in ("details", "state"):
        if k in act and len(act[k]) < 2:
            act[k] = act[k].ljust(2)
    return act


def _freeze(act):
    if act is None:
        return None
    return repr(sorted((k, repr(v)) for k, v in act.items()))


class RichPresence:
    def __init__(self, client_id=None, log_fn=None, clock=time.monotonic, loader=None):
        self.client_id = DISCORD_CLIENT_ID if client_id is None else str(client_id or "")
        self._log_fn = log_fn
        self._clock = clock
        self._loader = loader or self._import_pypresence
        self._module = None
        self._module_failed = False
        self._rpc = None
        self._loop = None
        self._desired = None
        self._desired_key = None
        self._sent_key = "__jamais__"       # rien n'a encore ete envoye (None = presence effacee)
        self._last_sent = None
        self._backoff = 0.0
        self._next_try = 0.0
        self._warned = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    # ---------------------------------------------------------------- journal (une fois par cause)
    def _log_once(self, key, msg):
        if key in self._warned:
            return
        self._warned.add(key)
        if self._log_fn:
            try:
                self._log_fn(msg)
                return
            except Exception:  # noqa
                pass
        log.info("%s", msg)

    @property
    def enabled(self):
        return bool(self.client_id)

    @property
    def connected(self):
        return self._rpc is not None

    # ---------------------------------------------------------------- cycle de vie
    def start(self):
        if not self.enabled:
            self._log_once("no_id", "Discord : identifiant d'application absent, Rich Presence désactivée")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="discord-presence", daemon=True)
        self._thread.start()
        return True

    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def update(self, snapshot):
        """Activite voulue (appele souvent, aucune E/S) ; le fil l'enverra quand il le pourra."""
        try:
            act = build_activity(snapshot)
        except Exception as e:  # noqa
            self._log_once("build", f"Discord : activité illisible ({e!r})")
            act = None
        key = _freeze(act)
        with self._lock:
            if key == self._desired_key:
                return
            self._desired, self._desired_key = act, key
        self._wake.set()

    def close(self):
        """Efface la presence et ferme la connexion (fermeture de DodoTopia ou reglage coupe)."""
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=3)
        self._thread = None
        if t is None:
            self._disconnect(clear=True)

    # ---------------------------------------------------------------- fil
    def _run(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        except Exception:  # noqa
            self._loop = None
        try:
            while not self._stop.is_set():
                wait = self.tick()
                self._wake.clear()
                self._wake.wait(max(0.05, wait))
        finally:
            self._disconnect(clear=True)
            if self._loop is not None:
                try:
                    self._loop.close()
                except Exception:  # noqa
                    pass
                self._loop = None

    def _import_pypresence(self):
        import pypresence
        return pypresence

    def _connect(self):
        if self._module is None:
            if self._module_failed:
                return False
            try:
                self._module = self._loader()
            except Exception as e:  # noqa : ImportError surtout
                self._module_failed = True
                self._log_once("import", f"Discord : pypresence indisponible ({e!r}), Rich Presence désactivée")
                return False
        try:
            kw = {"loop": self._loop} if self._loop is not None else {}
            rpc = self._module.Presence(self.client_id, **kw)
            rpc.connect()
        except Exception as e:  # noqa : Discord ferme, tube absent, identifiant refuse
            self._log_once("connect", f"Discord : connexion impossible ({type(e).__name__}), nouvel essai en arrière-plan")
            self._backoff = min(MAX_BACKOFF, max(MIN_BACKOFF, self._backoff * 2))
            self._next_try = self._clock() + self._backoff
            return False
        self._rpc = rpc
        self._backoff = 0.0
        self._sent_key = "__jamais__"
        self._last_sent = None
        self._warned.discard("connect")
        self._warned.discard("send")
        if "connected" not in self._warned:
            self._log_once("connected", "Discord : Rich Presence connectée")
        return True

    def _disconnect(self, clear=False):
        rpc, self._rpc = self._rpc, None
        if rpc is None:
            return
        if clear:
            try:
                rpc.clear()
            except Exception:  # noqa
                pass
        try:
            rpc.close()
        except Exception:  # noqa
            pass

    def tick(self):
        """Une etape : connexion si besoin, envoi si l'activite a change et que 15 s sont passees.
        Renvoie le delai conseille avant la prochaine etape (le fil l'utilise, les tests l'ignorent)."""
        if not self.enabled or self._module_failed:
            return MAX_BACKOFF
        now = self._clock()
        if self._rpc is None:
            if now < self._next_try:
                return self._next_try - now
            if not self._connect():
                return max(IDLE_WAIT, self._next_try - self._clock()) if not self._module_failed else MAX_BACKOFF
            now = self._clock()
        with self._lock:
            act, key = self._desired, self._desired_key
        if key == self._sent_key:
            return IDLE_WAIT
        if self._last_sent is not None and now - self._last_sent < UPDATE_INTERVAL:
            return UPDATE_INTERVAL - (now - self._last_sent)
        try:
            if act is None:
                self._rpc.clear()
            else:
                self._rpc.update(**act)
        except Exception as e:  # noqa : Discord ferme entre-temps
            self._log_once("send", f"Discord : envoi impossible ({type(e).__name__}), reconnexion")
            self._disconnect()
            self._backoff = min(MAX_BACKOFF, max(MIN_BACKOFF, self._backoff * 2))
            self._next_try = now + self._backoff
            return self._backoff
        self._sent_key = key
        self._last_sent = now
        return IDLE_WAIT
