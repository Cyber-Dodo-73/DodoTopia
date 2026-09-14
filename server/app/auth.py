"""Connexion Discord (OAuth2 `identify`) par ticket + navigateur + polling, sessions et dépendances d'accès.

Flow :
  app  POST /api/auth/start {verifier_hash}     -> {login_id, url, expires_in}
  nav  GET  /auth/discord/start?login_id=...     -> 302 discord.com/oauth2/authorize
  nav  GET  /auth/discord/callback?code&state    -> échange du code, upsert user, session, 302 /auth/discord/done
  app  POST /api/auth/poll {login_id, verifier}  -> pending | ok {token, user} (une seule fois) | error
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import db
from .config import Settings
from .ratelimit import limit
from .schemas import AuthPoll, AuthStart, clean_text

router = APIRouter()

DISCORD_API = "https://discord.com/api/v10"


def api_error(status: int, code: str, message: str, **extra) -> HTTPException:
    """Erreur JSON uniforme : {"detail": {"code", "message", ...}}."""
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def sha256_hex(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


# --- Discord (isolé pour être remplacé dans les tests) -------------------------

def discord_exchange_code(settings: Settings, code: str) -> str:
    """Échange le code OAuth2 contre un access_token (scope identify)."""
    r = httpx.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": settings.DISCORD_CLIENT_ID,
            "client_secret": settings.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{settings.public_url}/auth/discord/callback",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def discord_fetch_user(access_token: str) -> dict:
    """GET /users/@me -> {id, username, global_name, avatar}."""
    r = httpx.get(f"{DISCORD_API}/users/@me", headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    r.raise_for_status()
    return r.json()


def avatar_url(discord_user: dict) -> str | None:
    av = discord_user.get("avatar")
    if not av:
        return None
    ext = "gif" if str(av).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{discord_user['id']}/{av}.{ext}?size=64"


# --- Utilisateurs et sessions ----------------------------------------------------

def user_public(user: db.Row, settings: Settings) -> dict:
    return {
        "id": user["id"],
        "discord_id": user["discord_id"],
        "username": user["username"],
        "avatar_url": user["avatar_url"],
        "is_admin": bool(user["is_admin"]) or user["discord_id"] in settings.admin_ids,
    }


def upsert_user(conn: db.Connection, settings: Settings, du: dict) -> db.Row:
    """Crée ou met à jour l'utilisateur depuis le profil Discord ; is_admin recalculé à chaque login."""
    now = db.now_iso()
    discord_id = str(du["id"])
    # Le pseudo Discord est affiché (uploader_name, joueurs d'un salon) : nettoyé comme tout texte
    # d'utilisateur, sans quoi un pseudo à surcharge bidi déguise le nom du déposant d'un morceau.
    username = clean_text(du.get("global_name") or du.get("username"), 64) or "?"
    is_admin = 1 if discord_id in settings.admin_ids else 0
    conn.execute(
        """INSERT INTO users (discord_id, username, avatar_url, is_admin, created_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(discord_id) DO UPDATE SET username=excluded.username, avatar_url=excluded.avatar_url,
               is_admin=excluded.is_admin, last_seen_at=excluded.last_seen_at""",
        (discord_id, username, avatar_url(du), is_admin, now, now),
    )
    return conn.execute("SELECT * FROM users WHERE discord_id=?", (discord_id,)).fetchone()


def create_session(conn: db.Connection, settings: Settings, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = db.now_iso()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_used_at) VALUES (?, ?, ?, ?, ?)",
        (sha256_hex(token), user_id, now, db.iso_in(settings.SESSION_DAYS * 86400), now),
    )
    return token


def user_from_token(conn: db.Connection, settings: Settings, token: str | None) -> db.Row | None:
    """Utilisateur d'un token de session valide (expiration glissante), sinon None. Bannis exclus."""
    if not token:
        return None
    h = sha256_hex(token)
    row = conn.execute(
        """SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash=? AND s.expires_at > ?""",
        (h, db.now_iso()),
    ).fetchone()
    if row is None or row["banned"]:
        return None
    now = db.now_iso()
    conn.execute("UPDATE sessions SET last_used_at=?, expires_at=? WHERE token_hash=?",
                 (now, db.iso_in(settings.SESSION_DAYS * 86400), h))
    conn.execute("UPDATE users SET last_seen_at=? WHERE id=?", (now, row["id"]))
    conn.commit()
    return row


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def get_optional_user(request: Request, conn: db.Connection = Depends(db.get_db)) -> db.Row | None:
    return user_from_token(conn, settings_of(request), bearer_token(request))


def get_current_user(request: Request, conn: db.Connection = Depends(db.get_db)) -> db.Row:
    user = user_from_token(conn, settings_of(request), bearer_token(request))
    if user is None:
        raise api_error(401, "unauthorized", "Connexion Discord requise.")
    return user


def is_admin(user: db.Row, settings: Settings) -> bool:
    return bool(user["is_admin"]) or user["discord_id"] in settings.admin_ids


def require_admin(request: Request, user: db.Row = Depends(get_current_user)) -> db.Row:
    if not is_admin(user, settings_of(request)):
        raise api_error(403, "forbidden", "Réservé aux administrateurs.")
    return user


def require_publish_token(request: Request) -> None:
    """En-tête `X-Publish-Token` (ou `Authorization: Bearer`) égal à PUBLISH_TOKEN."""
    expected = settings_of(request).PUBLISH_TOKEN
    got = request.headers.get("X-Publish-Token") or bearer_token(request) or ""
    if not expected or not hmac.compare_digest(got, expected):
        raise api_error(403, "forbidden", "Jeton de publication invalide.")


# --- Endpoints -------------------------------------------------------------------

@router.post("/api/auth/start", dependencies=[Depends(limit("auth_start", 10, 60))])
def auth_start(body: AuthStart, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    login_id = secrets.token_urlsafe(16)
    state = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO login_tickets (id, verifier_hash, state, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (login_id, body.verifier_hash, state, db.now_iso()),
    )
    conn.commit()
    return {
        "login_id": login_id,
        "url": f"{settings.public_url}/auth/discord/start?login_id={login_id}",
        "expires_in": settings.LOGIN_TICKET_S,
    }


def _live_ticket(conn: db.Connection, settings: Settings, login_id: str) -> db.Row | None:
    row = conn.execute("SELECT * FROM login_tickets WHERE id=?", (login_id,)).fetchone()
    if row is None or row["created_at"] < db.iso_in(-settings.LOGIN_TICKET_S):
        return None
    return row


@router.get("/auth/discord/start")
def discord_start(login_id: str, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    t = _live_ticket(conn, settings, login_id)
    if t is None or t["status"] != "pending":
        return _done_page("expired", status=404)
    params = {
        "client_id": settings.DISCORD_CLIENT_ID,
        "redirect_uri": f"{settings.public_url}/auth/discord/callback",
        "response_type": "code",
        "scope": "identify",
        "state": t["state"],
        "prompt": "none",
    }
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{urlencode(params)}", status_code=302)


@router.get("/auth/discord/callback")
def discord_callback(request: Request, state: str = "", code: str = "", error: str = "",
                     conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    t = conn.execute("SELECT * FROM login_tickets WHERE state=?", (state,)).fetchone() if state else None
    if t is None or t["status"] != "pending" or _live_ticket(conn, settings, t["id"]) is None:
        return RedirectResponse("/auth/discord/done?error=expired", status_code=302)

    def fail(reason: str):
        conn.execute("UPDATE login_tickets SET status='error', error=? WHERE id=?", (reason, t["id"]))
        conn.commit()
        return RedirectResponse(f"/auth/discord/done?error={reason}", status_code=302)

    if error or not code:
        return fail("denied")
    try:
        access = discord_exchange_code(settings, code)
        du = discord_fetch_user(access)
    except Exception:
        return fail("discord")
    user = upsert_user(conn, settings, du)
    if user["banned"]:
        return fail("banned")
    token = create_session(conn, settings, user["id"])
    conn.execute("UPDATE login_tickets SET status='ok', token=? WHERE id=?", (token, t["id"]))
    conn.commit()
    return RedirectResponse("/auth/discord/done", status_code=302)


_DONE_MESSAGES = {
    "": ("Connecté !", "Tu peux fermer cet onglet et retourner dans DodoTopia."),
    "expired": ("Lien expiré", "Relance la connexion depuis DodoTopia."),
    "denied": ("Connexion refusée", "Tu as refusé l'autorisation Discord. Relance la connexion depuis DodoTopia."),
    "discord": ("Erreur Discord", "Discord n'a pas répondu correctement. Réessaie dans un instant."),
    "banned": ("Compte bloqué", "Ce compte n'est pas autorisé sur ce serveur."),
}


def _done_page(error: str = "", status: int = 200) -> HTMLResponse:
    title, text = _DONE_MESSAGES.get(error, _DONE_MESSAGES["discord"])
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>DodoTopia – {title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;background:#fff7ee;color:#3b2a20;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0;padding:16px}}main{{background:#fff;border-radius:16px;padding:32px;
max-width:420px;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.08)}}h1{{margin:0 0 8px;font-size:22px}}</style></head>
<body><main><h1>{title}</h1><p>{text}</p></main></body></html>"""
    return HTMLResponse(html, status_code=status)


@router.get("/auth/discord/done")
def discord_done(error: str = ""):
    return _done_page(error, status=200 if not error else 400)


@router.post("/api/auth/poll")
def auth_poll(body: AuthPoll, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    t = _live_ticket(conn, settings, body.login_id)
    if t is None:
        raise api_error(404, "unknown_login", "Connexion inconnue ou expirée.")
    if not hmac.compare_digest(sha256_hex(body.verifier), t["verifier_hash"]):
        raise api_error(403, "bad_verifier", "Vérificateur incorrect.")
    if t["status"] == "pending":
        return {"status": "pending"}
    if t["status"] == "error":
        return {"status": "error", "error": t["error"]}
    if t["status"] == "used":
        raise api_error(410, "consumed", "Cette connexion a déjà été récupérée.")
    # ok : livré une seule fois
    conn.execute("UPDATE login_tickets SET status='used', token=NULL WHERE id=?", (t["id"],))
    conn.commit()
    user = user_from_token(conn, settings, t["token"])
    if user is None:
        return {"status": "error", "error": "session"}
    return {"status": "ok", "token": t["token"], "user": user_public(user, settings)}


@router.get("/api/me")
def me(request: Request, user: db.Row = Depends(get_current_user)):
    return user_public(user, settings_of(request))


@router.post("/api/auth/logout")
def logout(request: Request, conn: db.Connection = Depends(db.get_db)):
    token = bearer_token(request)
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (sha256_hex(token),))
        conn.commit()
    return {"ok": True}


def cleanup(conn: db.Connection, settings: Settings) -> None:
    """Tickets périmés et sessions expirées (tâche de fond)."""
    conn.execute("DELETE FROM login_tickets WHERE created_at < ?", (db.iso_in(-settings.LOGIN_TICKET_S),))
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now_iso(),))
    conn.commit()
