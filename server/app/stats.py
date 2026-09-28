"""Statistiques de l'espace admin : collecte sans cookie, agrégée par jour, et requêtes du tableau de bord.

Collecte
  - `StatsMiddleware` observe chaque réponse HTTP : pages vues du site (chemin, langue, référent externe, appareil,
    navigateur, système, heure × jour de semaine), robots, erreurs 4xx/5xx, appels d'API par famille, clients
    DodoTopia (User-Agent `DodoTopia/<version> (<plateforme>)`), latence (mémoire seulement).
  - `hit(app, key, dim)` est appelé par le code métier (téléchargements, connexions, dépôts, salons…).
  - Tout s'accumule en mémoire (`Recorder`) et part en base toutes les minutes (`flush`, tâche de fond de main.py) :
    une page vue ne coûte aucune écriture SQL. Un seul worker (salons en mémoire) : pas de perte entre processus.

Visiteurs uniques : empreinte sha256(sel du jour + IP + User-Agent), le sel est aléatoire, propre au jour et effacé
le lendemain ; les empreintes du jour sont alors comptées dans `stat_daily` (clé `u:<clé>`) puis supprimées. Rien ne
permet donc de relier deux jours ni de retrouver une IP : aucune donnée personnelle n'est conservée.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import threading
import time
from collections import Counter, deque
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from . import db

log = logging.getLogger("dodo.stats")

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Europe/Paris")
except Exception:  # noqa - base tz absente : heures en UTC
    TZ = timezone.utc

LANGS = {"fr", "en", "es", "de", "pt-br", "zh-cn", "ja", "th"}
MAX_DIM = 120                   # longueur maximale d'une dimension (chemin, référent…)
MAX_DIMS_PER_KEY_DAY = 400      # au-delà, les nouvelles valeurs du jour tombent dans « (autres) »
OTHER = "(autres)"
LATENCY_WINDOW = 2000           # dernières requêtes gardées pour les percentiles
LIVE_POINTS = 24 * 60           # une mesure par minute sur 24 h (salons, joueurs, requêtes)

# Clés « jauge » : on garde le maximum de la journée au lieu d'additionner.
GAUGE_PREFIX = "peak_"

BOT_RE = re.compile(r"bot|crawl|spider|slurp|bingpreview|facebookexternalhit|embedly|discordbot|twitterbot|"
                    r"telegrambot|whatsapp|curl|wget|python-requests|httpx|go-http|headless|lighthouse|monitor|"
                    r"uptime|scan|preview", re.I)
BOT_NAME_RE = re.compile(r"(googlebot|bingbot|yandex\w*|duckduckbot|baiduspider|applebot|ahrefsbot|semrushbot|"
                         r"mj12bot|discordbot|twitterbot|facebookexternalhit|petalbot|gptbot|claudebot|ccbot|"
                         r"bytespider|curl|wget|python-requests|httpx|uptime\w*)", re.I)
APP_UA_RE = re.compile(r"^DodoTopia/(\d+(?:\.\d+){1,3})(?:\s*\(([^)]{1,40})\))?")


def today() -> str:
    return datetime.now(TZ).date().isoformat()


def local_now() -> datetime:
    return datetime.now(TZ)


def clip(value: str) -> str:
    return (value or "")[:MAX_DIM]


# --- Classification du User-Agent -------------------------------------------------------------------------------

def browser_of(ua: str) -> str:
    u = ua.lower()
    if "edg/" in u:
        return "Edge"
    if "opr/" in u or "opera" in u:
        return "Opera"
    if "samsungbrowser" in u:
        return "Samsung Internet"
    if "firefox/" in u or "fxios" in u:
        return "Firefox"
    if "chrome/" in u or "crios" in u:
        return "Chrome"
    if "safari/" in u:
        return "Safari"
    return "Autre"


def os_of(ua: str) -> str:
    u = ua.lower()
    if "windows" in u:
        return "Windows"
    if "iphone" in u or "ipad" in u or "ios" in u:
        return "iOS"
    if "android" in u:
        return "Android"
    if "mac os" in u or "macintosh" in u:
        return "macOS"
    if "cros" in u:
        return "ChromeOS"
    if "linux" in u:
        return "Linux"
    return "Autre"


def device_of(ua: str) -> str:
    u = ua.lower()
    if "ipad" in u or "tablet" in u:
        return "Tablette"
    if "mobi" in u or "iphone" in u or "android" in u:
        return "Mobile"
    return "Ordinateur"


def bot_name(ua: str) -> str:
    m = BOT_NAME_RE.search(ua)
    return m.group(1).lower() if m else "autre robot"


def referrer_host(referer: str, own_host: str) -> str:
    """Domaine du référent externe (sans www.), "" si interne ou absent."""
    if not referer:
        return ""
    try:
        host = (urlsplit(referer).hostname or "").lower()
    except ValueError:
        return ""
    if not host or host == own_host:
        return ""
    return host[4:] if host.startswith("www.") else host


def api_family(path: str) -> str:
    """/api/songs/12/download -> songs ; /api/admin/songs -> admin/songs."""
    parts = [p for p in path.split("/") if p][1:3]
    if not parts:
        return "api"
    if parts[0] == "admin" and len(parts) > 1:
        return "admin/" + parts[1]
    return re.sub(r"\d+", "#", parts[0])


# --- Accumulateur ---------------------------------------------------------------------------------------------

class Recorder:
    """Compteurs, jauges et empreintes en mémoire, vidés en base par `flush`. Sûr entre threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts: Counter = Counter()           # (day, key, dim) -> n
        self._gauges: dict[tuple, int] = {}         # (day, key, dim) -> max
        self._uniques: set[tuple] = set()           # (day, key, dim, h) pas encore écrits
        self._dims_seen: dict[tuple, set] = {}      # (day, key) -> dimensions déjà vues ce jour (plafond)
        self._salts: dict[str, str] = {}
        self.latencies: deque = deque(maxlen=LATENCY_WINDOW)   # (monotonic, ms, status)
        self.live: deque = deque(maxlen=LIVE_POINTS)            # (iso minute, rooms, players, requests)
        self.requests_since_sample = 0
        self.started_at = time.time()
        self.errors: deque = deque(maxlen=50)                   # dernières erreurs 5xx (iso, méthode, chemin, statut)

    # --- dimensions plafonnées ---
    def _dim(self, day: str, key: str, dim: str) -> str:
        dim = clip(dim)
        seen = self._dims_seen.setdefault((day, key), set())
        if dim in seen:
            return dim
        if len(seen) >= MAX_DIMS_PER_KEY_DAY:
            return OTHER
        seen.add(dim)
        return dim

    def hit(self, key: str, dim: str = "", n: int = 1, day: str | None = None) -> None:
        day = day or today()
        with self._lock:
            self._counts[(day, key, self._dim(day, key, dim))] += n

    def gauge(self, key: str, value: int, dim: str = "", day: str | None = None) -> None:
        day = day or today()
        k = (day, GAUGE_PREFIX + key if not key.startswith(GAUGE_PREFIX) else key, clip(dim))
        with self._lock:
            if value > self._gauges.get(k, -1):
                self._gauges[k] = value

    def salt(self, day: str) -> str:
        s = self._salts.get(day)
        if s is None:
            s = self._salts[day] = secrets.token_hex(16)
        return s

    def unique(self, key: str, ident: str, dim: str = "", day: str | None = None) -> None:
        day = day or today()
        with self._lock:
            h = hashlib.sha256(f"{self.salt(day)}|{ident}".encode()).hexdigest()[:24]
            self._uniques.add((day, key, self._dim(day, "u:" + key, dim), h))

    def take(self) -> tuple[Counter, dict, set]:
        with self._lock:
            counts, gauges, uniques = self._counts, self._gauges, self._uniques
            self._counts, self._gauges, self._uniques = Counter(), {}, set()
            # Les dimensions vues des jours passés ne servent plus.
            d = today()
            self._dims_seen = {k: v for k, v in self._dims_seen.items() if k[0] >= d}
            return counts, gauges, uniques

    def give_back(self, counts: Counter, gauges: dict, uniques: set) -> None:
        """Remet en mémoire un lot dont l'écriture a échoué (base indisponible) : rien n'est perdu."""
        with self._lock:
            self._counts.update(counts)
            for k, v in gauges.items():
                if v > self._gauges.get(k, -1):
                    self._gauges[k] = v
            self._uniques |= uniques

    # --- latence / santé ---
    def observe(self, ms: float, status: int) -> None:
        self.latencies.append((time.monotonic(), ms, status))
        self.requests_since_sample += 1

    def latency_summary(self) -> dict:
        now = time.monotonic()
        recent = [(ms, st) for t, ms, st in self.latencies if now - t < 900]
        if not recent:
            return {"count": 0, "p50": None, "p95": None, "p99": None, "errors": 0}
        values = sorted(ms for ms, _ in recent)

        def pct(p):
            return round(values[min(len(values) - 1, int(p * len(values)))], 1)

        return {"count": len(values), "p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99),
                "errors": sum(1 for _, st in recent if st >= 500)}


def recorder_of(app) -> Recorder | None:
    return getattr(app.state, "stats", None)


def hit(app, key: str, dim: str = "", n: int = 1) -> None:
    """Compte un évènement métier (jamais bloquant, jamais d'exception)."""
    rec = recorder_of(app)
    if rec is not None:
        try:
            rec.hit(key, str(dim), n)
        except Exception:  # noqa - une statistique ne doit jamais casser une requête
            log.exception("stats.hit")


def unique(app, key: str, ident: str, dim: str = "") -> None:
    rec = recorder_of(app)
    if rec is not None:
        try:
            rec.unique(key, ident, str(dim))
        except Exception:  # noqa
            log.exception("stats.unique")


# --- Écriture en base -----------------------------------------------------------------------------------------

UPSERT_COUNT = ("INSERT INTO stat_daily (day, key, dim, n) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (day, key, dim) DO UPDATE SET n = stat_daily.n + excluded.n")
UPSERT_GAUGE = ("INSERT INTO stat_daily (day, key, dim, n) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (day, key, dim) DO UPDATE SET "
                "n = CASE WHEN excluded.n > stat_daily.n THEN excluded.n ELSE stat_daily.n END")
INSERT_UNIQUE = ("INSERT INTO stat_uniques (day, key, dim, h) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT (day, key, dim, h) DO NOTHING")


def flush(settings, rec: Recorder) -> None:
    """Écrit le lot en mémoire, puis fige les visiteurs uniques des jours révolus (compte + effacement)."""
    counts, gauges, uniques = rec.take()
    if counts or gauges or uniques:
        conn = db.connect(settings)
        try:
            with conn.transaction():
                for (day, key, dim), n in counts.items():
                    conn.execute(UPSERT_COUNT, (day, key, dim, n))
                for (day, key, dim), n in gauges.items():
                    conn.execute(UPSERT_GAUGE, (day, key, dim, n))
                for u in uniques:
                    conn.execute(INSERT_UNIQUE, u)
        except Exception:
            rec.give_back(counts, gauges, uniques)
            raise
        finally:
            conn.close()
    close_past_days(settings, rec)


def close_past_days(settings, rec: Recorder) -> None:
    d = today()
    conn = db.connect(settings)
    try:
        rows = conn.execute("SELECT day, key, dim, COUNT(*) AS n FROM stat_uniques WHERE day < ? "
                            "GROUP BY day, key, dim", (d,)).fetchall()
        if rows:
            with conn.transaction():
                for r in rows:
                    conn.execute(UPSERT_COUNT, (r["day"], "u:" + r["key"], r["dim"], int(r["n"])))
                conn.execute("DELETE FROM stat_uniques WHERE day < ?", (d,))
    finally:
        conn.close()
    for day in [k for k in rec._salts if k < d]:
        rec._salts.pop(day, None)


def sample_live(app) -> None:
    """Une mesure par minute : salons ouverts, joueurs connectés, requêtes servies ; pics du jour."""
    rec = recorder_of(app)
    if rec is None:
        return
    rooms = list(app.state.rooms.rooms.values())
    players = sum(len(r.connected_seats()) for r in rooms)
    playing = sum(1 for r in rooms if r.state in ("countdown", "playing"))
    reqs, rec.requests_since_sample = rec.requests_since_sample, 0
    rec.live.append((local_now().strftime("%Y-%m-%dT%H:%M"), len(rooms), players, reqs, playing))
    rec.gauge("rooms", len(rooms))
    rec.gauge("players", players)
    rec.gauge("rpm", reqs)


# --- Middleware ---------------------------------------------------------------------------------------------

SKIP_PREFIXES = ("/static/", "/admin", "/og/", "/favicon", "/robots.txt", "/sitemap", "/api/health", "/api/time")


class StatsMiddleware:
    """Observe chaque réponse HTTP (ASGI pur, ne lit ni ne modifie le corps)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        info = {"status": 500, "ctype": b""}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                info["status"] = message.get("status", 200)
                for k, v in message.get("headers", []):
                    if k.lower() == b"content-type":
                        info["ctype"] = v
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            try:
                self.record(scope, info["status"], info["ctype"], (time.perf_counter() - started) * 1000)
            except Exception:  # noqa - jamais d'effet sur la réponse
                log.exception("stats middleware")

    def record(self, scope, status: int, ctype: bytes, ms: float) -> None:
        app = scope.get("app")
        rec = recorder_of(app) if app is not None else None
        if rec is None:
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        rec.observe(ms, status)
        if status >= 500:
            rec.hit("http_5xx", api_family(path) if path.startswith("/api/") else path)
            rec.errors.append((local_now().isoformat(timespec="seconds"), method, clip(path), status))
            notifier = getattr(app.state, "notifier", None)
            if notifier is not None:
                notifier.server_error(method, path, status)
        elif status >= 400 and status != 404:
            rec.hit("http_4xx", str(status))
        elif status == 404:
            rec.hit("http_404", "api" if path.startswith("/api/") else "site")
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        ua = headers.get(b"user-agent", b"").decode("latin-1", "replace")[:300]
        client = scope.get("client") or ("?", 0)
        ident = f"{client[0]}|{ua}"

        m = APP_UA_RE.match(ua)
        if m:   # le client DodoTopia (mises à jour, bibliothèque, salons…)
            version, platform = m.group(1), (m.group(2) or "?").strip()
            rec.unique("app_active", ident)
            rec.unique("app_version", ident, version)
            rec.unique("app_platform", ident, platform)
            if path.startswith("/api/"):
                rec.hit("app_api", api_family(path))
            return

        if path.startswith("/api/"):
            rec.hit("api", api_family(path))
            return
        if method != "GET" or status != 200 or not ctype.startswith(b"text/html") or path.startswith(SKIP_PREFIXES) \
                or path.startswith("/auth/"):
            return
        if BOT_RE.search(ua) or not ua:
            rec.hit("bot", bot_name(ua))
            return
        seg = path.strip("/").split("/", 1)[0].lower()
        lang = seg if seg in LANGS else "?"
        rec.hit("pv")
        rec.hit("pv_path", path)
        rec.hit("pv_lang", lang)
        rec.hit("pv_device", device_of(ua))
        rec.hit("pv_browser", browser_of(ua))
        rec.hit("pv_os", os_of(ua))
        now = local_now()
        rec.hit("pv_when", f"{now.weekday()}-{now.hour:02d}")
        host = headers.get(b"host", b"").decode("latin-1").split(":")[0].lower()
        ref = referrer_host(headers.get(b"referer", b"").decode("latin-1", "replace"), host)
        if ref:
            rec.hit("pv_ref", ref)
        rec.unique("visitors", ident)
        rec.unique("visitors_lang", ident, lang)


# --- Lecture ---------------------------------------------------------------------------------------------------

def day_range(days: int) -> list[str]:
    end = local_now().date()
    return [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def series(conn: db.Connection, key: str, days: list[str], dim: str | None = None) -> list[int]:
    """Totaux par jour (toutes dimensions confondues, ou une seule)."""
    args: list = [key, days[0], days[-1]]
    where = "key=? AND day BETWEEN ? AND ?"
    if dim is not None:
        where += " AND dim=?"
        args.append(dim)
    rows = conn.execute(f"SELECT day, SUM(n) AS n FROM stat_daily WHERE {where} GROUP BY day", args).fetchall()
    got = {r["day"]: int(r["n"] or 0) for r in rows}
    return [got.get(d, 0) for d in days]


def gauge_series(conn: db.Connection, key: str, days: list[str]) -> list[int]:
    rows = conn.execute("SELECT day, MAX(n) AS n FROM stat_daily WHERE key=? AND day BETWEEN ? AND ? GROUP BY day",
                        (GAUGE_PREFIX + key, days[0], days[-1])).fetchall()
    got = {r["day"]: int(r["n"] or 0) for r in rows}
    return [got.get(d, 0) for d in days]


def unique_series(conn: db.Connection, key: str, days: list[str]) -> list[int]:
    """Uniques par jour : jours révolus depuis `u:<clé>`, aujourd'hui en direct depuis `stat_uniques`."""
    values = series(conn, "u:" + key, days)
    t = today()
    if days[-1] == t:
        values[-1] += int(conn.execute("SELECT COUNT(DISTINCT h) FROM stat_uniques WHERE day=? AND key=?",
                                       (t, key)).fetchone()[0] or 0)
    return values


def breakdown(conn: db.Connection, key: str, days: list[str], limit: int = 15) -> list[dict]:
    rows = conn.execute("SELECT dim, SUM(n) AS n FROM stat_daily WHERE key=? AND day BETWEEN ? AND ? "
                        "GROUP BY dim ORDER BY n DESC, dim LIMIT ?", (key, days[0], days[-1], limit)).fetchall()
    return [{"label": r["dim"] or "—", "value": int(r["n"] or 0)} for r in rows]


def unique_breakdown(conn: db.Connection, key: str, days: list[str], limit: int = 15) -> list[dict]:
    """Uniques par dimension sur la période : somme des uniques journaliers (un visiteur revenu deux jours compte
    deux fois, faute de pouvoir relier les jours — c'est voulu)."""
    total: Counter = Counter()
    for r in conn.execute("SELECT dim, SUM(n) AS n FROM stat_daily WHERE key=? AND day BETWEEN ? AND ? GROUP BY dim",
                          ("u:" + key, days[0], days[-1])).fetchall():
        total[r["dim"]] += int(r["n"] or 0)
    t = today()
    if days[-1] == t:
        for r in conn.execute("SELECT dim, COUNT(DISTINCT h) AS n FROM stat_uniques WHERE day=? AND key=? "
                              "GROUP BY dim", (t, key)).fetchall():
            total[r["dim"]] += int(r["n"] or 0)
    return [{"label": k or "—", "value": v} for k, v in total.most_common(limit)]


def today_unique(conn: db.Connection, key: str) -> int:
    return int(conn.execute("SELECT COUNT(DISTINCT h) FROM stat_uniques WHERE day=? AND key=?",
                            (today(), key)).fetchone()[0] or 0)


def created_series(conn: db.Connection, table: str, days: list[str], where: str = "", column: str = "created_at") \
        -> list[int]:
    """Lignes créées par jour (UTC) d'une table métier. `table`, `column` et `where` sont des constantes du code."""
    start = days[0]
    rows = conn.execute(f"SELECT SUBSTR({column}, 1, 10) AS d, COUNT(*) AS n FROM {table} "
                        f"WHERE {column} >= ? {('AND ' + where) if where else ''} GROUP BY SUBSTR({column}, 1, 10)",
                        (start,)).fetchall()
    got = {r["d"]: int(r["n"]) for r in rows}
    return [got.get(d, 0) for d in days]


def heatmap(conn: db.Connection, days: list[str]) -> list[list[int]]:
    """Pages vues par jour de semaine (0 = lundi) × heure locale."""
    grid = [[0] * 24 for _ in range(7)]
    for r in conn.execute("SELECT dim, SUM(n) AS n FROM stat_daily WHERE key='pv_when' AND day BETWEEN ? AND ? "
                          "GROUP BY dim", (days[0], days[-1])).fetchall():
        try:
            wd, hh = r["dim"].split("-")
            grid[int(wd)][int(hh)] += int(r["n"] or 0)
        except (ValueError, IndexError):
            continue
    return grid


def total(values: list[int]) -> int:
    return int(sum(values))


def compare(values: list[int]) -> dict:
    """Total de la période et évolution par rapport à la première moitié (tendance simple)."""
    half = len(values) // 2
    a, b = sum(values[:half]), sum(values[half:])
    delta = None if a == 0 else round((b - a) * 100 / a, 1)
    return {"total": int(sum(values)), "delta_pct": delta}


def iso_days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat(timespec="seconds")


def parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
