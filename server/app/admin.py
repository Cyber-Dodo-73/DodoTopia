"""Espace admin du site : connexion Discord dans le navigateur, tableau de bord et API JSON d'administration.

Pages : `/admin/login` (bouton « Se connecter avec Discord »), `/admin` (application d'une page : `static/admin.js`
dessine les sections à partir des routes `/api/admin/*`). Accès : `ADMIN_DISCORD_IDS` (ou `users.is_admin`), par
le cookie de session web (voir auth.py) ou par un jeton Bearer d'administrateur (app).

Les routes de modération existantes (morceaux, dessins, signalements, bannissement) restent dans library.py et
gallery.py ; celles-ci ajoutent les statistiques, le direct, les comptes, le journal et les réglages du webhook.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import platform
import secrets
import shutil
import sys
import time
from html import escape

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from . import auth, db, notify, social, stats
from .auth import (_discord_authorize_url, announce_new_user, api_error, create_session, get_optional_user, is_admin,
                   require_admin, settings_of, sha256_hex, upsert_user)
from .config import SERVER_VERSION, Settings

log = logging.getLogger("dodo.admin")
router = APIRouter()

STATE_COOKIE = "dodo_admin_state"
CONFIRM_COOKIE = "dodo_admin_confirm"      # confirmation dans un autre navigateur : voir web_callback
CONFIRM_MAX_AGE = 300
STATE_MAX_AGE = 600
NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}


# --- Journal ----------------------------------------------------------------------------------------------------

def audit(request: Request, conn: db.Connection, admin: db.Row, action: str, target: str = "", detail: str = "") \
        -> None:
    """Trace une action d'administration (et la notifie si l'évènement « admin_action » est activé). Sans commit."""
    conn.execute("INSERT INTO admin_log (admin_id, admin_name, action, target, detail, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?)", (admin["id"], admin["username"], action, target[:200] or None,
                                               detail[:500] or None, db.now_iso()))
    notify.emit(request.app, "admin_action", f"{admin['username']} : {ACTION_LABELS.get(action, action)}",
                (target + (f" — {detail}" if detail else ""))[:500])


ACTION_LABELS = {
    "song_approve": "morceau validé", "song_reject": "morceau refusé", "song_delete": "morceau supprimé",
    "drawing_approve": "dessin validé", "drawing_reject": "dessin refusé", "report_resolve": "signalement traité",
    "user_ban": "compte banni", "user_unban": "compte débanni", "settings": "réglages modifiés",
    "sessions_revoke": "sessions révoquées", "webhook_test": "webhook testé",
}


# --- Pages HTML ---------------------------------------------------------------------------------------------------

def _asset(name: str) -> str:
    from .site import static_url   # import tardif : site importe beaucoup de modules
    return static_url(name)


def _page(request: Request, title: str, body: str, status: int = 200, extra_head: str = "") -> HTMLResponse:
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{escape(title)} · DodoTopia Admin</title>
<link rel="icon" href="/static/favicon.ico" sizes="any">
<link rel="stylesheet" href="{_asset('admin.css')}">{extra_head}
</head><body>{body}</body></html>"""
    return HTMLResponse(html, status_code=status, headers=NO_STORE)


def _login_page(request: Request, error: str = "", status: int = 200) -> HTMLResponse:
    messages = {
        "forbidden": "Ce compte Discord n'a pas accès à l'espace admin.",
        "denied": "Autorisation Discord refusée.",
        "expired": "La connexion a expiré, recommence.",
        "discord": "Discord n'a pas répondu correctement, réessaie dans un instant.",
        "banned": "Ce compte est bloqué.",
        "config": "Connexion Discord non configurée sur ce serveur (DISCORD_CLIENT_ID).",
    }
    err = f'<p class="login-err" role="alert">{escape(messages.get(error, messages["discord"]))}</p>' if error else ""
    body = f"""<main class="login">
<img src="/static/logo.png" width="72" height="72" alt="">
<h1>Espace admin</h1>
<p class="muted">Réservé aux administrateurs de DodoTopia. La connexion passe par Discord (identité seulement).</p>
{err}
<form method="post" action="/admin/login"><button class="btn btn-discord" type="submit">
<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M19.3 5.3A16.6 16.6 0 0 0 15.2 4l-.5 1a15.4 15.4 0 0 0-4.6 0L9.6 4a16.5 16.5 0 0 0-4.1 1.3C2.9 9.2 2.2 13 2.5 16.8a16.7 16.7 0 0 0 5 2.6l1.1-1.7a10.8 10.8 0 0 1-1.7-.8l.4-.3a11.9 11.9 0 0 0 10.2 0l.4.3-1.7.8 1.1 1.7a16.6 16.6 0 0 0 5-2.6c.4-4.4-.7-8.2-3-11.5ZM9.3 14.5c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm5.4 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>
Se connecter avec Discord</button></form>
<p class="small"><a href="/">Retour au site</a></p>
</main>"""
    return _page(request, "Connexion", body, status=status)


def current_admin(request: Request, conn: db.Connection) -> db.Row | None:
    user = get_optional_user(request, conn)
    if user is None or not is_admin(user, settings_of(request)):
        return None
    return user


@router.get("/admin/login", include_in_schema=False)
def login_page(request: Request, error: str = "", conn: db.Connection = Depends(db.get_db)):
    if not error and current_admin(request, conn) is not None:
        return RedirectResponse("/admin", status_code=302, headers=NO_STORE)
    return _login_page(request, error[:20], status=200 if not error else 400)


@router.post("/admin/login", include_in_schema=False)
def login_start(request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    if not settings.DISCORD_CLIENT_ID:
        return _login_page(request, "config", status=503)
    state = "w" + secrets.token_urlsafe(24)
    conn.execute("INSERT INTO web_logins (state, created_at) VALUES (?, ?)", (state, db.now_iso()))
    conn.commit()
    resp = RedirectResponse(_discord_authorize_url(settings, state), status_code=303, headers=NO_STORE)
    # Lax : le cookie doit revenir avec la navigation de retour depuis discord.com (GET de premier niveau).
    resp.set_cookie(STATE_COOKIE, sha256_hex(state), max_age=STATE_MAX_AGE, httponly=True,
                    secure=settings.secure_cookies, samesite="lax", path="/auth/discord/callback")
    return resp


def web_callback(request: Request, conn: db.Connection, state: str, code: str, error: str) -> Response:
    """Retour de Discord pour une connexion à l'espace admin (appelé par auth.discord_callback)."""
    settings = settings_of(request)
    row = conn.execute("SELECT * FROM web_logins WHERE state=?", (state,)).fetchone()
    conn.execute("DELETE FROM web_logins WHERE state=?", (state,))
    conn.commit()

    def back(reason: str) -> Response:
        r = RedirectResponse(f"/admin/login?error={reason}", status_code=302, headers=NO_STORE)
        r.delete_cookie(STATE_COOKIE, path="/auth/discord/callback")
        return r

    cookie = request.cookies.get(STATE_COOKIE, "")
    if row is None or row["created_at"] < db.iso_in(-STATE_MAX_AGE):
        return back("expired")
    # Même navigateur qu'au départ : le cookie posé par POST /admin/login est revenu avec la navigation.
    same_browser = secrets.compare_digest(cookie, sha256_hex(state))
    if error or not code:
        return back("denied")
    try:
        du = auth.discord_fetch_user(auth.discord_exchange_code(settings, code))
    except Exception:
        return back("discord")
    user = upsert_user(conn, settings, du)
    conn.commit()
    if user["just_created"]:
        announce_new_user(request, user)
    if user["banned"]:
        return back("banned")
    if not is_admin(user, settings):
        log.warning("espace admin : connexion refusée pour %s (%s)", user["username"], user["discord_id"])
        return back("forbidden")
    if not same_browser:
        # Le retour arrive dans un autre navigateur que celui du départ : sur mobile, l'appli Discord autorise puis
        # rouvre le lien dans le navigateur par défaut, qui n'a pas le cookie. Aucune session ici : une page nomme
        # le compte et demande un clic. Un lien de retour envoyé par un tiers ne connecte donc personne en
        # silence, et le POST de confirmation exige un cookie SameSite=Strict posé par cette page (un formulaire
        # soumis depuis un autre site ne l'emporte pas).
        confirm = secrets.token_urlsafe(24)
        conn.execute("INSERT INTO web_logins (state, created_at, user_id) VALUES (?, ?, ?)",
                     ("c" + sha256_hex(confirm), db.now_iso(), user["id"]))
        conn.commit()
        return _confirm_page(request, user["username"], confirm)
    return _open_admin_session(request, conn, user)


def _open_admin_session(request: Request, conn: db.Connection, user: db.Row, status: int = 302) -> Response:
    settings = settings_of(request)
    token = create_session(conn, settings, user["id"], kind="web")
    conn.commit()
    stats.hit(request.app, "login", "web")
    notify.emit(request.app, "login_web", f"{user['username']} s'est connecté à l'espace admin",
                thumbnail=user["avatar_url"])
    resp = RedirectResponse("/admin", status_code=status, headers=NO_STORE)
    resp.delete_cookie(STATE_COOKIE, path="/auth/discord/callback")
    resp.delete_cookie(CONFIRM_COOKIE, path="/admin/login")
    resp.set_cookie(settings.admin_cookie, token, max_age=settings.ADMIN_SESSION_DAYS * 86400, httponly=True,
                    secure=settings.secure_cookies, samesite="lax", path="/")
    return resp


def _confirm_page(request: Request, username: str, confirm: str) -> Response:
    settings = settings_of(request)
    name = escape(username or "Discord")
    body = f"""<main class="login">
<img src="/static/logo.png" width="72" height="72" alt="">
<h1>Continuer ici ?</h1>
<p class="muted">Discord t'a renvoyé dans un autre navigateur que celui où tu as commencé (c'est courant sur
téléphone, quand l'appli Discord ouvre le lien). Tu peux terminer la connexion à l'espace admin dans celui-ci.</p>
<form method="post" action="/admin/login/confirm"><input type="hidden" name="token" value="{escape(confirm, quote=True)}">
<button class="btn btn-discord" type="submit">Continuer en tant que {name}</button></form>
<p class="small">Si tu n'as pas lancé cette connexion toi-même, ferme cette page.</p>
<p class="small"><a href="/admin/login">Annuler</a></p>
</main>"""
    resp = _page(request, "Confirmer la connexion", body)
    resp.delete_cookie(STATE_COOKIE, path="/auth/discord/callback")
    resp.set_cookie(CONFIRM_COOKIE, sha256_hex(confirm), max_age=CONFIRM_MAX_AGE, httponly=True,
                    secure=settings.secure_cookies, samesite="strict", path="/admin/login")
    return resp


@router.post("/admin/login/confirm", include_in_schema=False)
def login_confirm(request: Request, token: str = Form(""), conn: db.Connection = Depends(db.get_db)):
    """Clic « Continuer en tant que … » de la page de confirmation : ouvre la session dans CE navigateur."""
    settings = settings_of(request)
    token = (token or "")[:128]
    key = "c" + sha256_hex(token)
    row = conn.execute("SELECT * FROM web_logins WHERE state=?", (key,)).fetchone() if token else None
    conn.execute("DELETE FROM web_logins WHERE state=?", (key,))
    conn.commit()

    def back(reason: str) -> Response:
        r = RedirectResponse(f"/admin/login?error={reason}", status_code=303, headers=NO_STORE)
        r.delete_cookie(CONFIRM_COOKIE, path="/admin/login")
        return r

    cookie = request.cookies.get(CONFIRM_COOKIE, "")
    if (row is None or row["created_at"] < db.iso_in(-CONFIRM_MAX_AGE) or not row["user_id"]
            or not secrets.compare_digest(cookie, sha256_hex(token))):
        return back("expired")
    user = conn.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
    if user is None or user["banned"]:
        return back("banned")
    if not is_admin(user, settings):
        return back("forbidden")
    return _open_admin_session(request, conn, user, status=303)


@router.post("/admin/logout", include_in_schema=False)
def logout(request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    token = request.cookies.get(settings.admin_cookie)
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash=? AND kind='web'", (sha256_hex(token),))
        conn.commit()
    resp = RedirectResponse("/admin/login", status_code=303, headers=NO_STORE)
    resp.delete_cookie(settings.admin_cookie, path="/")
    return resp


@router.get("/admin", include_in_schema=False)
@router.get("/admin/", include_in_schema=False)
def admin_home(request: Request, conn: db.Connection = Depends(db.get_db)):
    admin = current_admin(request, conn)
    if admin is None:
        return RedirectResponse("/admin/login", status_code=302, headers=NO_STORE)
    me = {"id": admin["id"], "username": admin["username"], "avatar_url": admin["avatar_url"],
          "public_url": settings_of(request).public_url}
    body = f"""<div id="app" data-me="{escape(json.dumps(me), quote=True)}">
<noscript><p class="panel">L'espace admin a besoin de JavaScript.</p></noscript></div>
<script src="{_asset('admin.js')}" defer></script>"""
    return _page(request, "Tableau de bord", body)


# --- Aperçu ---------------------------------------------------------------------------------------------------------

def _count(conn: db.Connection, sql: str, args: tuple = ()) -> int:
    return int(conn.execute(sql, args).fetchone()[0] or 0)


def live_rooms(app) -> dict:
    rooms = list(app.state.rooms.rooms.values())
    return {"rooms": len(rooms), "players": sum(len(r.connected_seats()) for r in rooms),
            "playing": sum(1 for r in rooms if r.state in ("countdown", "playing"))}


@router.get("/api/admin/overview", dependencies=[Depends(require_admin)])
def overview(request: Request, conn: db.Connection = Depends(db.get_db)):
    d1, d7, d30 = stats.iso_days_ago(1), stats.iso_days_ago(7), stats.iso_days_ago(30)
    t = stats.today()
    notifier = notify.notifier_of(request.app)
    cfg = notifier.config() if notifier else {"url": ""}
    latest = conn.execute("SELECT r.version, r.published_at, COALESCE(SUM(a.downloads), 0) AS downloads "
                          "FROM releases r LEFT JOIN release_assets a ON a.version = r.version "
                          "WHERE r.published_at IS NOT NULL GROUP BY r.version, r.published_at "
                          "ORDER BY r.published_at DESC LIMIT 1").fetchone()
    today_row = {r["key"]: int(r["n"] or 0) for r in conn.execute(
        "SELECT key, SUM(n) AS n FROM stat_daily WHERE day=? GROUP BY key", (t,)).fetchall()}
    rec = stats.recorder_of(request.app)
    return {
        "users": {"total": _count(conn, "SELECT COUNT(*) FROM users"),
                  "new_24h": _count(conn, "SELECT COUNT(*) FROM users WHERE created_at >= ?", (d1,)),
                  "new_7d": _count(conn, "SELECT COUNT(*) FROM users WHERE created_at >= ?", (d7,)),
                  "new_30d": _count(conn, "SELECT COUNT(*) FROM users WHERE created_at >= ?", (d30,)),
                  "active_24h": _count(conn, "SELECT COUNT(*) FROM users WHERE last_seen_at >= ?", (d1,)),
                  "active_7d": _count(conn, "SELECT COUNT(*) FROM users WHERE last_seen_at >= ?", (d7,)),
                  "active_30d": _count(conn, "SELECT COUNT(*) FROM users WHERE last_seen_at >= ?", (d30,)),
                  "banned": _count(conn, "SELECT COUNT(*) FROM users WHERE banned=1")},
        "songs": {s: _count(conn, "SELECT COUNT(*) FROM songs WHERE status=?", (s,))
                  for s in ("approved", "pending", "rejected")},
        "drawings": {s: _count(conn, "SELECT COUNT(*) FROM drawings WHERE status=?", (s,))
                     for s in ("approved", "pending", "rejected")},
        "likes": _count(conn, "SELECT COUNT(*) FROM song_likes") + _count(conn, "SELECT COUNT(*) FROM drawing_likes"),
        "song_downloads": _count(conn, "SELECT COALESCE(SUM(downloads), 0) FROM songs"),
        "reports_open": _count(conn, "SELECT COUNT(*) FROM reports WHERE resolved_at IS NULL"),
        "app_downloads": _count(conn, "SELECT COALESCE(SUM(downloads), 0) FROM release_assets"),
        "today": {"pv": today_row.get("pv", 0) + (rec._counts.get((t, "pv", ""), 0) if rec else 0),
                  "visitors": stats.today_unique(conn, "visitors"),
                  "app_active": stats.today_unique(conn, "app_active"),
                  "dl_app": today_row.get("dl_app", 0), "logins": today_row.get("login", 0),
                  "signups": today_row.get("signup", 0)},
        "live": live_rooms(request.app),
        "latest_release": dict(latest) if latest else None,
        "webhook": {"configured": bool(cfg.get("url")), "sent": notifier.sent if notifier else 0,
                    "failed": notifier.failed if notifier else 0},
    }


# --- Statistiques ----------------------------------------------------------------------------------------------

def _days_param(days: int) -> int:
    return max(7, min(365, int(days)))


def _likes_series(conn, days):
    a = stats.created_series(conn, "song_likes", days)
    b = stats.created_series(conn, "drawing_likes", days)
    return [x + y for x, y in zip(a, b)]


def collect_series(conn: db.Connection, days: list[str]) -> dict[str, list[int]]:
    return {
        "pv": stats.series(conn, "pv", days),
        "visitors": stats.unique_series(conn, "visitors", days),
        "app_active": stats.unique_series(conn, "app_active", days),
        "dl_app": stats.series(conn, "dl_app", days),
        "dl_song": stats.series(conn, "dl_song", days),
        "signups": stats.created_series(conn, "users", days),
        "logins": stats.series(conn, "login", days),
        "songs_uploaded": stats.created_series(conn, "songs", days),
        "drawings_uploaded": stats.created_series(conn, "drawings", days),
        "likes": _likes_series(conn, days),
        "reports": stats.created_series(conn, "reports", days),
        "room_create": stats.series(conn, "room_create", days),
        "room_join": stats.series(conn, "room_join", days),
        "room_start": stats.series(conn, "room_start", days),
        "peak_players": stats.gauge_series(conn, "players", days),
        "peak_rooms": stats.gauge_series(conn, "rooms", days),
        "peak_rpm": stats.gauge_series(conn, "rpm", days),
        "imports": stats.series(conn, "import", days),
        "bots": stats.series(conn, "bot", days),
        "api": stats.series(conn, "api", days),
        "app_api": stats.series(conn, "app_api", days),
        "http_5xx": stats.series(conn, "http_5xx", days),
        "http_4xx": stats.series(conn, "http_4xx", days),
        "http_404": stats.series(conn, "http_404", days),
    }


def _titles(conn: db.Connection, table: str, ids: list[str]) -> dict[str, str]:
    clean = [int(i) for i in ids if str(i).isdigit()]
    if not clean:
        return {}
    marks = ",".join("?" for _ in clean)
    return {str(r["id"]): r["title"] for r in conn.execute(f"SELECT id, title FROM {table} WHERE id IN ({marks})",
                                                          clean).fetchall()}


def _histogram(values: list[float], edges: list[float], labels: list[str]) -> list[dict]:
    counts = [0] * len(labels)
    for v in values:
        for i, edge in enumerate(edges):
            if v < edge:
                counts[i] += 1
                break
        else:
            counts[-1] += 1
    return [{"label": lab, "value": c} for lab, c in zip(labels, counts)]


def content_stats(conn: db.Connection) -> dict:
    top_dl = conn.execute("SELECT id, title, artist, downloads, likes FROM songs WHERE status='approved' "
                          "ORDER BY downloads DESC, id LIMIT 10").fetchall()
    top_liked = conn.execute("SELECT id, title, artist, downloads, likes FROM songs WHERE status='approved' "
                             "ORDER BY likes DESC, downloads DESC, id LIMIT 10").fetchall()
    top_drawings = conn.execute("SELECT id, title, likes, w, h FROM drawings WHERE status='approved' "
                                "ORDER BY likes DESC, id LIMIT 10").fetchall()
    uploaders = conn.execute(
        """SELECT * FROM (SELECT u.id, u.username, u.avatar_url,
                  (SELECT COUNT(*) FROM songs s WHERE s.uploader_id=u.id AND s.status='approved') AS songs,
                  (SELECT COUNT(*) FROM drawings d WHERE d.uploader_id=u.id AND d.status='approved') AS drawings,
                  (SELECT COALESCE(SUM(s.downloads), 0) FROM songs s WHERE s.uploader_id=u.id) AS downloads
           FROM users u) t ORDER BY songs + drawings DESC, downloads DESC LIMIT 10""").fetchall()
    instruments = conn.execute("SELECT COALESCE(instrument, '(aucun)') AS label, COUNT(*) AS value FROM songs "
                               "WHERE status='approved' GROUP BY COALESCE(instrument, '(aucun)') "
                               "ORDER BY value DESC LIMIT 12").fetchall()
    licenses = conn.execute("SELECT license AS label, COUNT(*) AS value FROM songs WHERE status='approved' "
                            "GROUP BY license ORDER BY value DESC").fetchall()
    sources = conn.execute("SELECT COALESCE(source_name, '(non précisée)') AS label, COUNT(*) AS value FROM songs "
                           "WHERE status='approved' GROUP BY COALESCE(source_name, '(non précisée)') "
                           "ORDER BY value DESC LIMIT 10").fetchall()
    tag_counts: dict[str, int] = {}
    durations, notes = [], []
    for r in conn.execute("SELECT tags, duration_s, note_count FROM songs WHERE status='approved'").fetchall():
        try:
            for tag in json.loads(r["tags"] or "[]"):
                tag_counts[str(tag)] = tag_counts.get(str(tag), 0) + 1
        except ValueError:
            pass
        durations.append(float(r["duration_s"] or 0))
        notes.append(int(r["note_count"] or 0))
    reviewed = conn.execute("SELECT created_at, reviewed_at, status FROM songs WHERE reviewed_at IS NOT NULL "
                            "UNION ALL SELECT created_at, reviewed_at, status FROM drawings "
                            "WHERE reviewed_at IS NOT NULL").fetchall()
    delays = []
    approved = 0
    for r in reviewed:
        a, b = social._parse_iso(r["created_at"]), social._parse_iso(r["reviewed_at"])
        if a and b:
            delays.append((b - a).total_seconds() / 3600)
        approved += r["status"] == "approved"
    delays.sort()
    reports = conn.execute("SELECT resolution AS label, COUNT(*) AS value FROM reports WHERE resolved_at IS NOT NULL "
                           "GROUP BY resolution").fetchall()
    return {
        "top_songs_downloads": [dict(r) for r in top_dl],
        "top_songs_likes": [dict(r) for r in top_liked],
        "top_drawings": [dict(r) for r in top_drawings],
        "top_uploaders": [dict(r) for r in uploaders if (r["songs"] or r["drawings"])],
        "instruments": [dict(r) for r in instruments],
        "licenses": [dict(r) for r in licenses],
        "sources": [dict(r) for r in sources],
        "tags": [{"label": k, "value": v} for k, v in sorted(tag_counts.items(), key=lambda kv: -kv[1])[:15]],
        "durations": _histogram(durations, [60, 120, 180, 300, 600], ["< 1 min", "1–2 min", "2–3 min", "3–5 min",
                                                                        "5–10 min", "10 min +"]),
        "note_counts": _histogram(notes, [200, 500, 1000, 2000, 5000], ["< 200", "200–500", "500–1 k", "1–2 k",
                                                                        "2–5 k", "5 k +"]),
        "moderation": {"reviewed": len(reviewed), "approved": approved,
                       "approval_rate": round(approved * 100 / len(reviewed), 1) if reviewed else None,
                       "median_delay_h": round(delays[len(delays) // 2], 1) if delays else None,
                       "p90_delay_h": round(delays[int(len(delays) * 0.9)], 1) if delays else None,
                       "report_outcomes": [dict(r) for r in reports]},
    }


@router.get("/api/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats(request: Request, days: int = 30, conn: db.Connection = Depends(db.get_db)):
    rec = stats.recorder_of(request.app)
    if rec is not None:   # les chiffres de la dernière minute aussi
        try:
            stats.flush(settings_of(request), rec)
        except Exception:  # noqa
            log.exception("flush avant lecture")
    n = _days_param(days)
    rng = stats.day_range(n)
    series = collect_series(conn, rng)
    top_song_dl = stats.breakdown(conn, "dl_song", rng, 10)
    names = _titles(conn, "songs", [x["label"] for x in top_song_dl])
    for x in top_song_dl:
        x["id"] = x["label"]
        x["label"] = names.get(x["label"], f"#{x['label']} (supprimé)")
    return {
        "days": rng,
        "series": series,
        "totals": {k: stats.compare(v) for k, v in series.items()},
        "breakdowns": {
            "pages": stats.breakdown(conn, "pv_path", rng, 20),
            "langs": stats.breakdown(conn, "pv_lang", rng),
            "referrers": stats.breakdown(conn, "pv_ref", rng, 15),
            "devices": stats.breakdown(conn, "pv_device", rng),
            "browsers": stats.breakdown(conn, "pv_browser", rng),
            "os": stats.breakdown(conn, "pv_os", rng),
            "bots": stats.breakdown(conn, "bot", rng, 12),
            "app_versions": stats.unique_breakdown(conn, "app_version", rng, 12),
            "app_platforms": stats.unique_breakdown(conn, "app_platform", rng),
            "visitors_lang": stats.unique_breakdown(conn, "visitors_lang", rng),
            "dl_platforms": stats.breakdown(conn, "dl_app", rng),
            "dl_versions": stats.breakdown(conn, "dl_app_version", rng, 12),
            "dl_sources": stats.breakdown(conn, "dl_app_via", rng),
            "logins": stats.breakdown(conn, "login", rng),
            "imports": stats.breakdown(conn, "import", rng),
            "api": stats.breakdown(conn, "api", rng, 15),
            "app_api": stats.breakdown(conn, "app_api", rng, 15),
            "http_5xx": stats.breakdown(conn, "http_5xx", rng, 10),
            "http_4xx": stats.breakdown(conn, "http_4xx", rng, 10),
            "room_sizes": stats.breakdown(conn, "room_start_size", rng),
            "top_song_downloads": top_song_dl,
        },
        "heatmap": stats.heatmap(conn, rng),
        "content": content_stats(conn),
    }


@router.get("/api/admin/stats.csv", dependencies=[Depends(require_admin)])
def admin_stats_csv(days: int = 90, conn: db.Connection = Depends(db.get_db)):
    rng = stats.day_range(_days_param(days))
    series = collect_series(conn, rng)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["jour", *series.keys()])
    for i, d in enumerate(rng):
        w.writerow([d, *(v[i] for v in series.values())])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="dodotopia-stats-{rng[-1]}.csv"',
                             **NO_STORE})


# --- Direct -------------------------------------------------------------------------------------------------------

_DISK_CACHE: dict[str, tuple[float, dict]] = {}


def _dir_size(path) -> tuple[int, int]:
    total = files = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
                files += 1
            elif entry.is_dir(follow_symlinks=False):
                t, f = _dir_size(entry.path)
                total += t
                files += f
    except OSError:
        pass
    return total, files


def storage(settings: Settings, conn: db.Connection) -> dict:
    cached = _DISK_CACHE.get(str(settings.data_dir))
    if cached and cached[0] > time.monotonic():
        return cached[1]
    folders = {}
    for name, path in (("Morceaux", settings.songs_dir), ("Dessins", settings.drawings_dir),
                       ("Versions", settings.releases_dir), ("Import (cache)", settings.import_cache_dir),
                       ("Images de partage", settings.og_cache_dir), ("Temporaire", settings.tmp_dir)):
        size, files = _dir_size(path)
        folders[name] = {"bytes": size, "files": files}
    try:
        du = shutil.disk_usage(settings.data_dir)
        disk = {"total": du.total, "used": du.used, "free": du.free}
    except OSError:
        disk = None
    try:
        if conn.dialect == "postgres":
            db_bytes = int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])
        else:
            db_bytes = settings.db_path.stat().st_size
    except Exception:  # noqa
        db_bytes = None
    body = {"folders": folders, "disk": disk, "db_bytes": db_bytes}
    _DISK_CACHE[str(settings.data_dir)] = (time.monotonic() + 300, body)
    return body


@router.get("/api/admin/live", dependencies=[Depends(require_admin)])
def admin_live(request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    rec = stats.recorder_of(request.app)
    rooms = []
    now = time.time()
    for r in request.app.state.rooms.rooms.values():
        rooms.append({
            "code": r.code, "state": r.state, "max_players": r.max_players,
            "age_s": int(now - getattr(r, "created_at", now)),
            "song": (r.song or {}).get("title") if r.song else None,
            "players": [{"name": s.name, "instrument": s.instrument, "connected": s.connected,
                         "host": s.id == r.host_id, "version": getattr(s, "version", "")}
                        for s in r.seats.values()],
        })
    notifier = notify.notifier_of(request.app)
    return {
        "rooms": sorted(rooms, key=lambda x: -len(x["players"])),
        "live": [{"t": t, "rooms": a, "players": b, "requests": c, "playing": p}
                 for t, a, b, c, p in (rec.live if rec else [])],
        "latency": rec.latency_summary() if rec else None,
        "errors": [{"at": a, "method": m, "path": p, "status": s} for a, m, p, s in reversed(rec.errors)] if rec else [],
        "server": {"version": SERVER_VERSION, "python": sys.version.split()[0], "platform": platform.platform(terse=True),
                   "db": conn.dialect, "uptime_s": int(now - rec.started_at) if rec else None,
                   "min_client": settings.MIN_CLIENT_VERSION, "public_url": settings.public_url,
                   "rate_limit": bool(settings.RATE_LIMIT), "indexnow": bool(settings.indexnow_key),
                   "announce_webhook": bool(settings.DISCORD_ANNOUNCE_WEBHOOK),
                   "notify_queue": notifier.q.qsize() if notifier else 0},
        "storage": storage(settings, conn),
        "sessions": {"app": _count(conn, "SELECT COUNT(*) FROM sessions WHERE kind='app' AND expires_at > ?",
                                   (db.now_iso(),)),
                     "web": _count(conn, "SELECT COUNT(*) FROM sessions WHERE kind='web' AND expires_at > ?",
                                   (db.now_iso(),))},
    }


# --- Comptes --------------------------------------------------------------------------------------------------------

# Tri appliqué sur la sous-requête `t` (PostgreSQL refuse un alias de colonne dans une expression d'ORDER BY).
USER_SORTS = {"recent": "created_at DESC, id DESC", "seen": "last_seen_at DESC, id DESC",
              "content": "songs + drawings DESC, id DESC", "name": "LOWER(username), id"}
USER_COLUMNS = """u.id, u.discord_id, u.username, u.avatar_url, u.is_admin, u.banned, u.created_at, u.last_seen_at,
    (SELECT COUNT(*) FROM songs s WHERE s.uploader_id=u.id) AS songs,
    (SELECT COUNT(*) FROM drawings d WHERE d.uploader_id=u.id) AS drawings,
    (SELECT COUNT(*) FROM song_likes l WHERE l.user_id=u.id) + (SELECT COUNT(*) FROM drawing_likes l
        WHERE l.user_id=u.id) AS likes_given,
    (SELECT COUNT(*) FROM reports r WHERE r.reporter_id=u.id) AS reports_made"""


def _user_out(r: db.Row, settings: Settings) -> dict:
    d = dict(r)
    d["is_admin"] = bool(r["is_admin"]) or r["discord_id"] in settings.admin_ids
    d["banned"] = bool(r["banned"])
    return d


@router.get("/api/admin/users", dependencies=[Depends(require_admin)])
def admin_users(request: Request, q: str = "", filter: str = "all", sort: str = "recent", page: int = 1,
                per_page: int = 50, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    where, args = ["1=1"], []
    if q.strip():
        where.append("(LOWER(u.username) LIKE LOWER(?) OR u.discord_id = ?)")
        args += [f"%{q.strip()[:64]}%", q.strip()[:32]]
    if filter == "banned":
        where.append("u.banned=1")
    elif filter == "admins":
        ids = sorted(settings.admin_ids)
        marks = ",".join("?" for _ in ids) or "''"
        where.append(f"(u.is_admin=1 OR u.discord_id IN ({marks}))")
        args += ids
    elif filter == "active":
        where.append("u.last_seen_at >= ?")
        args.append(stats.iso_days_ago(7))
    elif filter == "uploaders":
        where.append("EXISTS (SELECT 1 FROM songs s WHERE s.uploader_id=u.id UNION ALL "
                     "SELECT 1 FROM drawings d WHERE d.uploader_id=u.id)")
    page, per_page = max(1, page), max(1, min(100, per_page))
    total = _count(conn, f"SELECT COUNT(*) FROM users u WHERE {' AND '.join(where)}", tuple(args))
    rows = conn.execute(f"SELECT * FROM (SELECT {USER_COLUMNS} FROM users u WHERE {' AND '.join(where)}) t "
                        f"ORDER BY {USER_SORTS.get(sort, USER_SORTS['recent'])} LIMIT ? OFFSET ?",
                        [*args, per_page, (page - 1) * per_page]).fetchall()
    return {"items": [_user_out(r, settings) for r in rows], "total": total, "page": page,
            "pages": max(1, -(-total // per_page))}


@router.get("/api/admin/users/{user_id}", dependencies=[Depends(require_admin)])
def admin_user(user_id: int, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users u WHERE u.id=?", (user_id,)).fetchone()
    if row is None:
        raise api_error(404, "not_found", "Utilisateur introuvable.")
    songs = conn.execute("SELECT id, title, artist, status, downloads, likes, created_at FROM songs "
                         "WHERE uploader_id=? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()
    drawings = conn.execute("SELECT id, title, status, likes, w, h, created_at FROM drawings WHERE uploader_id=? "
                            "ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()
    reports = conn.execute("SELECT id, target_type, song_id, drawing_id, reason, created_at, resolution FROM reports "
                           "WHERE reporter_id=? ORDER BY created_at DESC LIMIT 50", (user_id,)).fetchall()
    sessions = conn.execute("SELECT kind, created_at, last_used_at, expires_at FROM sessions WHERE user_id=? "
                            "AND expires_at > ? ORDER BY last_used_at DESC", (user_id, db.now_iso())).fetchall()
    return {"user": _user_out(row, settings), "songs": [dict(r) for r in songs],
            "drawings": [dict(r) for r in drawings], "reports": [dict(r) for r in reports],
            "sessions": [dict(r) for r in sessions]}


@router.post("/api/admin/users/{user_id}/unban")
def unban_user(user_id: int, request: Request, admin=Depends(require_admin), conn: db.Connection = Depends(db.get_db)):
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if target is None:
        raise api_error(404, "not_found", "Utilisateur introuvable.")
    conn.execute("UPDATE users SET banned=0 WHERE id=?", (user_id,))
    audit(request, conn, admin, "user_unban", f"{target['username']} (#{user_id})")
    conn.commit()
    return {"ok": True, "user_id": user_id}


@router.post("/api/admin/users/{user_id}/revoke")
def revoke_sessions(user_id: int, request: Request, admin=Depends(require_admin),
                    conn: db.Connection = Depends(db.get_db)):
    """Déconnecte un compte partout (app et site) sans le bannir."""
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if target is None:
        raise api_error(404, "not_found", "Utilisateur introuvable.")
    n = conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,)).rowcount
    audit(request, conn, admin, "sessions_revoke", f"{target['username']} (#{user_id})", f"{n} session(s)")
    conn.commit()
    return {"ok": True, "revoked": n}


# --- Versions, journal ------------------------------------------------------------------------------------------

@router.get("/api/admin/releases-stats", dependencies=[Depends(require_admin)])
def releases_stats(conn: db.Connection = Depends(db.get_db)):
    rels = conn.execute("SELECT version, published_at, mandatory, announced_at, notes FROM releases "
                        "ORDER BY COALESCE(published_at, '9999') DESC").fetchall()
    assets = conn.execute("SELECT version, platform, filename, size, downloads FROM release_assets").fetchall()
    by_version: dict[str, list] = {}
    for a in assets:
        by_version.setdefault(a["version"], []).append(dict(a))
    return {"items": [{**dict(r), "notes": (r["notes"] or "")[:400], "assets": by_version.get(r["version"], []),
                       "downloads": sum(a["downloads"] for a in by_version.get(r["version"], []))} for r in rels]}


@router.get("/api/admin/log", dependencies=[Depends(require_admin)])
def admin_log(page: int = 1, per_page: int = 50, conn: db.Connection = Depends(db.get_db)):
    page, per_page = max(1, page), max(1, min(200, per_page))
    total = _count(conn, "SELECT COUNT(*) FROM admin_log")
    rows = conn.execute("SELECT * FROM admin_log ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                        (per_page, (page - 1) * per_page)).fetchall()
    return {"items": [{**dict(r), "label": ACTION_LABELS.get(r["action"], r["action"])} for r in rows],
            "total": total, "page": page, "pages": max(1, -(-total // per_page))}


# --- Réglages du webhook -------------------------------------------------------------------------------------------

class SettingsIn(BaseModel):
    webhook_url: str | None = None      # None : inchangé ; "" : effacé
    events: dict[str, bool] | None = None
    mention: str | None = None


def settings_view(request: Request, conn: db.Connection) -> dict:
    settings = settings_of(request)
    stored = notify.get_setting(conn, "webhook_url", "")
    env = (settings.DISCORD_ADMIN_WEBHOOK or "").strip()
    cfg = notify.load_config(conn, settings)
    n = notify.notifier_of(request.app)
    return {"webhook_set": bool(cfg["url"]), "webhook_masked": notify.mask_webhook(cfg["url"]),
            "source": "site" if stored else ("env" if env else ""),
            "events": [{"id": k, "label": label, "enabled": cfg["events"][k]}
                       for k, (label, _, _) in notify.EVENTS.items()],
            "mention": cfg["mention"],
            "delivery": {"sent": n.sent if n else 0, "failed": n.failed if n else 0,
                         "last_failure": n.last_failure if n else ""},
            "admins": sorted(settings.admin_ids)}


@router.get("/api/admin/settings", dependencies=[Depends(require_admin)])
def get_settings(request: Request, conn: db.Connection = Depends(db.get_db)):
    return settings_view(request, conn)


@router.put("/api/admin/settings")
def put_settings(body: SettingsIn, request: Request, admin=Depends(require_admin),
                 conn: db.Connection = Depends(db.get_db)):
    changes = []
    if body.webhook_url is not None:
        url = body.webhook_url.strip()
        if url and not notify.valid_webhook(url):
            raise api_error(422, "bad_webhook", "URL de webhook Discord invalide "
                                                "(https://discord.com/api/webhooks/<id>/<jeton>).")
        notify.set_setting(conn, "webhook_url", url)
        changes.append("webhook " + ("défini" if url else "effacé"))
    if body.events is not None:
        clean = {k: bool(v) for k, v in body.events.items() if k in notify.EVENTS}
        notify.set_setting(conn, "webhook_events", json.dumps(clean))
        changes.append("évènements")
    if body.mention is not None:
        m = body.mention.strip()
        if m and not m.isdigit():
            raise api_error(422, "bad_mention", "La mention doit être l'ID numérique d'un rôle Discord.")
        notify.set_setting(conn, "webhook_mention", m[:30])
        changes.append("mention")
    audit(request, conn, admin, "settings", ", ".join(changes))
    conn.commit()
    n = notify.notifier_of(request.app)
    if n:
        n.invalidate()
    return settings_view(request, conn)


@router.post("/api/admin/settings/test")
def test_webhook(request: Request, admin=Depends(require_admin), conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    cfg = notify.load_config(conn, settings)
    if not cfg["url"]:
        raise api_error(409, "no_webhook", "Aucun webhook enregistré.")
    n = notify.notifier_of(request.app)
    payload = notify.build_payload(settings, "admin_action", "Test du webhook ✅",
                                   f"Envoyé depuis l'espace admin par **{admin['username']}**.", None,
                                   notify.admin_url(settings), None, "")
    ok = n.send_raw(cfg["url"], payload) if n else False
    audit(request, conn, admin, "webhook_test", "", "réussi" if ok else "échec")
    conn.commit()
    if not ok:
        raise api_error(502, "webhook_failed", "Discord a refusé ou n'a pas répondu : vérifie l'URL du webhook.")
    return {"ok": True}


# --- Résumé quotidien (tâche de fond) -------------------------------------------------------------------------------

SUMMARY_HOUR = 9


def maybe_daily_summary(app) -> bool:
    """À partir de 9 h (Paris), une fois par jour : le bilan de la veille sur le webhook admin."""
    settings = app.state.settings
    now = stats.local_now()
    if now.hour < SUMMARY_HOUR:
        return False
    yesterday = stats.day_range(2)[0]
    conn = db.connect(settings)
    try:
        if notify.get_setting(conn, "summary_sent", "") >= yesterday:
            return False
        notify.set_setting(conn, "summary_sent", yesterday)
        conn.commit()
        day = [yesterday]
        s = collect_series(conn, day)
        pending = (_count(conn, "SELECT COUNT(*) FROM songs WHERE status='pending'")
                   + _count(conn, "SELECT COUNT(*) FROM drawings WHERE status='pending'"))
        reports_open = _count(conn, "SELECT COUNT(*) FROM reports WHERE resolved_at IS NULL")
        users = _count(conn, "SELECT COUNT(*) FROM users")
    finally:
        conn.close()
    v = {k: vals[0] for k, vals in s.items()}
    fields = [("Visiteurs", v["visitors"]), ("Pages vues", v["pv"]), ("Apps actives", v["app_active"]),
              ("Téléchargements app", v["dl_app"]), ("Morceaux téléchargés", v["dl_song"]),
              ("Nouveaux comptes", f"{v['signups']} (total {users})"), ("Connexions", v["logins"]),
              ("Dépôts", f"{v['songs_uploaded']} morceaux · {v['drawings_uploaded']} dessins"),
              ("Likes", v["likes"]), ("Parties en salon", v["room_start"]), ("Pic de joueurs", v["peak_players"]),
              ("Erreurs 5xx", v["http_5xx"]), ("À modérer", pending), ("Signalements ouverts", reports_open)]
    notify.emit(app, "daily_summary", f"Bilan du {yesterday}", fields=[(a, str(b)) for a, b in fields],
                url=notify.admin_url(settings))
    return True


def background_tick(app) -> None:
    """Appelé chaque minute par main.py : mesure du direct, écriture des stats, résumé quotidien."""
    stats.sample_live(app)
    rec = stats.recorder_of(app)
    if rec is not None:
        stats.flush(app.state.settings, rec)
    maybe_daily_summary(app)

