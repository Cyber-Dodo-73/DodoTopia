"""Notifications d'administration sur un webhook Discord.

L'URL et les évènements à signaler se règlent depuis l'espace admin du site (table `admin_settings`) ; la variable
d'environnement `DISCORD_ADMIN_WEBHOOK` sert de valeur par défaut tant que rien n'est enregistré. Les envois partent
d'un thread dédié (file bornée) : une requête ne se bloque jamais sur Discord. Les 429 de Discord sont respectés
(`retry_after`), les erreurs serveur répétées sont regroupées (une alerte par chemin toutes les 10 minutes).
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time

import httpx

from . import db

log = logging.getLogger("dodo.notify")

WEBHOOK_RE = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d{5,30}/[\w-]{20,120}$")

# id -> (libellé, activé par défaut, couleur de l'embed)
EVENTS = {
    "new_user": ("Nouveau compte", True, 0x2A78D6),
    "song_pending": ("Morceau à valider", True, 0xEDA100),
    "drawing_pending": ("Dessin à valider", True, 0xEDA100),
    "report": ("Signalement", True, 0xE34948),
    "release": ("Version publiée", True, 0x1BAF7A),
    "server_error": ("Erreur serveur (5xx)", True, 0xD03B3B),
    "daily_summary": ("Résumé quotidien (9 h)", True, 0x4A3AA7),
    "room_started": ("Partie lancée dans un salon", False, 0x187A73),
    "admin_action": ("Action d'un admin", False, 0x898781),
    "login_web": ("Connexion à l'espace admin", True, 0x898781),
    "diag_report": ("Rapport de diagnostic reçu", True, 0x2A78D6),
}
ERROR_THROTTLE_S = 600
QUEUE_MAX = 200


def post_webhook(url: str, payload: dict) -> httpx.Response:
    """POST brut (isolé pour être remplacé dans les tests)."""
    return httpx.post(url, json=payload, timeout=10)


def valid_webhook(url: str) -> bool:
    return bool(WEBHOOK_RE.match((url or "").strip()))


def mask_webhook(url: str) -> str:
    """https://discord.com/api/webhooks/123…/abcd… -> …/webhooks/123/••••wxyz (jamais le jeton entier à l'écran)."""
    m = re.match(r"^(https://[^/]+/api/webhooks/\d+)/([\w-]+)$", url or "")
    if not m:
        return ""
    return f"{m.group(1)}/••••{m.group(2)[-4:]}"


# --- Réglages ------------------------------------------------------------------------------------------------

def get_setting(conn: db.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM admin_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: db.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO admin_settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


def load_config(conn: db.Connection, settings) -> dict:
    url = get_setting(conn, "webhook_url", "") or (settings.DISCORD_ADMIN_WEBHOOK or "").strip()
    try:
        chosen = json.loads(get_setting(conn, "webhook_events", "") or "{}")
    except ValueError:
        chosen = {}
    events = {k: bool(chosen.get(k, default)) for k, (_, default, _) in EVENTS.items()}
    return {"url": url if valid_webhook(url) else "", "events": events,
            "mention": get_setting(conn, "webhook_mention", "")}


# --- Notificateur --------------------------------------------------------------------------------------------

class Notifier:
    """File d'envoi vers Discord. `sync=True` (tests) : envoi immédiat dans le thread appelant."""

    def __init__(self, settings, sync: bool = False):
        self.settings = settings
        self.sync = sync
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_error: dict[str, float] = {}
        self._cfg: tuple[float, dict] | None = None
        self.sent = 0
        self.failed = 0
        self.last_failure = ""

    # --- configuration (cache 30 s, invalidé à l'enregistrement) ---
    def config(self) -> dict:
        now = time.monotonic()
        if self._cfg and self._cfg[0] > now:
            return self._cfg[1]
        conn = db.connect(self.settings)
        try:
            cfg = load_config(conn, self.settings)
        finally:
            conn.close()
        self._cfg = (now + 30, cfg)
        return cfg

    def invalidate(self) -> None:
        self._cfg = None

    # --- cycle de vie ---
    def start(self) -> None:
        if self.sync or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dodo-notify", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            try:
                self.q.put_nowait(None)
            except queue.Full:
                pass
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self.q.get()
            if item is None:
                break
            self._deliver(*item)

    # --- envoi ---
    def _deliver(self, url: str, payload: dict) -> bool:
        for attempt in range(3):
            try:
                r = post_webhook(url, payload)
                status = getattr(r, "status_code", 204)
                if status == 429 and attempt < 2:
                    try:
                        wait = float(r.json().get("retry_after", 1))
                    except Exception:  # noqa
                        wait = 1.0
                    time.sleep(min(10.0, max(0.2, wait)))
                    continue
                if status >= 400:
                    raise RuntimeError(f"HTTP {status}")
                self.sent += 1
                return True
            except Exception as e:  # noqa - réseau, Discord indisponible : journalisé, jamais propagé
                if attempt == 2:
                    self.failed += 1
                    self.last_failure = f"{time.strftime('%Y-%m-%d %H:%M:%S')} — {type(e).__name__}: {e}"[:200]
                    log.warning("webhook admin : échec (%s)", e)
                    return False
                time.sleep(0.5 * (attempt + 1))
        return False

    def send_raw(self, url: str, payload: dict) -> bool:
        """Envoi direct (bouton « tester ») : renvoie le résultat au lieu de passer par la file."""
        return self._deliver(url, payload)

    def emit(self, event: str, title: str, description: str = "", fields: list[tuple[str, str]] | None = None,
             url: str | None = None, thumbnail: str | None = None, force: bool = False) -> bool:
        """Met une notification en file si l'évènement est activé. Jamais d'exception."""
        try:
            cfg = self.config()
            if not cfg["url"] or (not force and not cfg["events"].get(event)):
                return False
            payload = build_payload(self.settings, event, title, description, fields, url, thumbnail,
                                    cfg.get("mention", ""))
            if self.sync:
                return self._deliver(cfg["url"], payload)
            self.q.put_nowait((cfg["url"], payload))
            return True
        except queue.Full:
            log.warning("webhook admin : file pleine, notification « %s » abandonnée", event)
        except Exception:  # noqa
            log.exception("notify.emit")
        return False

    def server_error(self, method: str, path: str, status: int) -> None:
        key = re.sub(r"\d+", "#", path)[:80]
        now = time.monotonic()
        if now - self._last_error.get(key, -1e9) < ERROR_THROTTLE_S:
            return
        self._last_error[key] = now
        self.emit("server_error", f"Erreur {status}", f"`{method} {path[:150]}`",
                  fields=[("Regroupement", "une alerte par chemin toutes les 10 min")])


def build_payload(settings, event: str, title: str, description: str, fields, url, thumbnail, mention: str) -> dict:
    label, _, color = EVENTS.get(event, ("Notification", True, 0x898781))
    embed: dict = {"title": title[:250], "color": color, "footer": {"text": f"DodoTopia · {label}"},
                   "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if description:
        embed["description"] = description[:3500]
    if fields:
        embed["fields"] = [{"name": str(n)[:250], "value": (str(v) or "—")[:1000], "inline": True}
                           for n, v in fields[:20]]
    if url:
        embed["url"] = url
    if thumbnail:
        embed["thumbnail"] = {"url": thumbnail}
    payload: dict = {"username": "DodoTopia Admin", "embeds": [embed], "allowed_mentions": {"parse": []}}
    avatar = f"{settings.public_url}/static/logo.png"
    if avatar.startswith("https://"):
        payload["avatar_url"] = avatar
    # Mention facultative (rôle) pour ce qui demande une action : modération et signalements.
    if mention and re.fullmatch(r"\d{5,30}", mention) and event in ("song_pending", "drawing_pending", "report",
                                                                     "server_error"):
        payload["content"] = f"<@&{mention}>"
        payload["allowed_mentions"] = {"roles": [mention]}
    return payload


def notifier_of(app) -> Notifier | None:
    return getattr(app.state, "notifier", None)


def emit(app, event: str, title: str, description: str = "", **kw) -> None:
    n = notifier_of(app)
    if n is not None:
        n.emit(event, title, description, **kw)


def admin_url(settings, section: str = "") -> str:
    return f"{settings.public_url}/admin" + (f"#{section}" if section else "")
