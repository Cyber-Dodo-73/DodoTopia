"""Connexion Discord (OAuth2 `identify`) par ticket + navigateur + polling, sessions et dépendances d'accès.

Flow (« device flow » : le code affiché dans l'app doit être recopié dans le navigateur, ce qui empêche un
tiers de faire connecter quelqu'un d'autre sur SON ticket en lui envoyant l'URL) :
  app  POST /api/auth/start {verifier_hash}     -> {login_id, url, expires_in, user_code}
  nav  GET  /auth/discord/start?login_id=...     -> page « saisis le code affiché dans DodoTopia »
  nav  POST /auth/discord/confirm (login_id, code) -> 302 discord.com/oauth2/authorize (5 essais, puis ticket en erreur)
  nav  GET  /auth/discord/callback?code&state    -> échange du code, upsert user, user_id sur le ticket, 302 /done
  app  POST /api/auth/poll {login_id, verifier}  -> pending | ok {token, user} (session créée ici, une seule fois) | error

Le ticket ne porte jamais de jeton de session : la session naît au `poll`, après vérification du `verifier`.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from html import escape
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import db
from .config import Settings
from .ratelimit import limit
from .schemas import AuthPoll, AuthStart, clean_text

router = APIRouter()

DISCORD_API = "https://discord.com/api/v10"
# Code à recopier : sans 0/O ni 1/I, 5 caractères (32^5 ≈ 33 millions, pour 5 essais par ticket).
USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
USER_CODE_LEN = 5


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
    """Utilisateur d'un token de session valide (expiration glissante), sinon None. Bannis exclus.

    `last_used_at`, `expires_at` et `last_seen_at` ne sont réécrits que si la dernière écriture date de plus
    de SESSION_TOUCH_S (1 h) : chaque requête authentifiée coûtait sinon deux UPDATE et un commit.
    """
    if not token:
        return None
    h = sha256_hex(token)
    row = conn.execute(
        """SELECT u.*, s.expires_at, s.last_used_at FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash=? AND s.expires_at > ?""",
        (h, db.now_iso()),
    ).fetchone()
    if row is None or row["banned"]:
        return None
    if row["last_used_at"] < db.iso_in(-settings.SESSION_TOUCH_S):
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

def new_user_code() -> str:
    return "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LEN))


def normalize_user_code(code: str) -> str:
    """Majuscules, sans espaces ni tirets (le joueur peut taper « ab c-de »)."""
    return re.sub(r"[^A-Za-z0-9]", "", code or "").upper()


@router.post("/api/auth/start", dependencies=[Depends(limit("auth_start", 10, 60))])
def auth_start(body: AuthStart, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    login_id = secrets.token_urlsafe(16)
    state = secrets.token_urlsafe(24)
    user_code = new_user_code()
    conn.execute(
        """INSERT INTO login_tickets (id, verifier_hash, state, status, user_code, attempts, created_at)
           VALUES (?, ?, ?, 'pending', ?, 0, ?)""",
        (login_id, body.verifier_hash, state, user_code, db.now_iso()),
    )
    conn.commit()
    return {
        "login_id": login_id,
        "url": f"{settings.public_url}/auth/discord/start?login_id={login_id}",
        "expires_in": settings.LOGIN_TICKET_S,
        "user_code": user_code,
    }


def _live_ticket(conn: db.Connection, settings: Settings, login_id: str) -> db.Row | None:
    row = conn.execute("SELECT * FROM login_tickets WHERE id=?", (login_id,)).fetchone()
    if row is None or row["created_at"] < db.iso_in(-settings.LOGIN_TICKET_S):
        return None
    return row


def _discord_authorize_url(settings: Settings, state: str) -> str:
    # Pas de `prompt=none` : Discord affiche son écran d'autorisation (le joueur voit ce qu'il accorde et
    # à quelle application), au lieu d'une approbation silencieuse.
    params = {
        "client_id": settings.DISCORD_CLIENT_ID,
        "redirect_uri": f"{settings.public_url}/auth/discord/callback",
        "response_type": "code",
        "scope": "identify",
        "state": state,
    }
    return f"https://discord.com/oauth2/authorize?{urlencode(params)}"


@router.get("/auth/discord/start")
def discord_start(login_id: str, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    t = _live_ticket(conn, settings, login_id)
    if t is None or t["status"] not in ("pending", "confirmed"):
        return _done_page("expired", status=404)
    return _code_page(login_id, remaining=settings.LOGIN_CODE_ATTEMPTS - int(t["attempts"] or 0))


@router.post("/auth/discord/confirm", dependencies=[Depends(limit("auth_confirm", 20, 60))])
def discord_confirm(request: Request, login_id: str = Form(""), code: str = Form(""),
                    conn: db.Connection = Depends(db.get_db)):
    """Vérifie le code recopié depuis l'app ; bon code -> Discord ; LOGIN_CODE_ATTEMPTS mauvais -> ticket en erreur."""
    settings = settings_of(request)
    login_id = (login_id or "")[:64]
    t = _live_ticket(conn, settings, login_id)
    if t is None or t["status"] not in ("pending", "confirmed"):
        return _done_page("expired", status=404)
    attempts = int(t["attempts"] or 0)
    if attempts >= settings.LOGIN_CODE_ATTEMPTS:
        return _done_page("code", status=403)
    given = normalize_user_code(code)[:USER_CODE_LEN * 2]
    if not hmac.compare_digest(given, t["user_code"] or ""):
        attempts += 1
        if attempts >= settings.LOGIN_CODE_ATTEMPTS:
            conn.execute("UPDATE login_tickets SET attempts=?, status='error', error='code' WHERE id=?",
                         (attempts, t["id"]))
            conn.commit()
            return _done_page("code", status=403)
        conn.execute("UPDATE login_tickets SET attempts=? WHERE id=?", (attempts, t["id"]))
        conn.commit()
        return _code_page(login_id, remaining=settings.LOGIN_CODE_ATTEMPTS - attempts, wrong=True, status=400)
    conn.execute("UPDATE login_tickets SET status='confirmed' WHERE id=?", (t["id"],))
    conn.commit()
    return RedirectResponse(_discord_authorize_url(settings, t["state"]), status_code=303)


@router.get("/auth/discord/callback")
def discord_callback(request: Request, state: str = "", code: str = "", error: str = "",
                     conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    t = conn.execute("SELECT * FROM login_tickets WHERE state=?", (state,)).fetchone() if state else None
    # Seul un ticket dont le code a été confirmé a vu son `state` sortir du serveur.
    if t is None or t["status"] != "confirmed" or _live_ticket(conn, settings, t["id"]) is None:
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
    # Aucune session ici : le ticket ne porte que l'identité ; le jeton naît au poll, contre le vérifieur.
    conn.execute("UPDATE login_tickets SET status='ok', user_id=? WHERE id=?", (user["id"], t["id"]))
    conn.commit()
    return RedirectResponse("/auth/discord/done", status_code=302)


_DONE_MESSAGES = {
    "": ("Connecté !", "Tu peux fermer cet onglet et retourner dans DodoTopia."),
    "expired": ("Lien expiré", "Relance la connexion depuis DodoTopia."),
    "denied": ("Connexion refusée", "Tu as refusé l'autorisation Discord. Relance la connexion depuis DodoTopia."),
    "discord": ("Erreur Discord", "Discord n'a pas répondu correctement. Réessaie dans un instant."),
    "banned": ("Compte bloqué", "Ce compte n'est pas autorisé sur ce serveur."),
    "code": ("Code incorrect", "Trop de tentatives : ce lien n'est plus valable. Relance la connexion depuis DodoTopia."),
}

_PAGE_STYLE = """@font-face{font-family:"Fredoka";font-weight:300 700;font-display:swap;
src:url("/static/fonts/fredoka-latin.woff2") format("woff2")}
@font-face{font-family:"Nunito";font-weight:200 1000;font-display:swap;
src:url("/static/fonts/nunito-latin.woff2") format("woff2")}
:root{--bg:#fff9ef;--card:#fff;--ink:#4a3b34;--ink2:#6a584d;--line:#f1dfc6;--teal:#187a73;--teal-d:#0f5b56;
--amber:#e8a531;--err:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#1d1715;--card:#2a211d;--ink:#efe4d8;--ink2:#d8c9bb;--line:#3a2e28;
--teal:#2aa198;--teal-d:#1c7c75;--err:#ffb4ab}}
*{box-sizing:border-box}
body{font-family:"Nunito",system-ui,sans-serif;font-size:17px;line-height:1.55;color:var(--ink);margin:0;padding:16px;
min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--bg);
background-image:radial-gradient(60% 50% at 12% 0%,rgba(255,196,214,.55),transparent 70%),
radial-gradient(55% 45% at 95% 8%,rgba(255,214,160,.6),transparent 70%),
radial-gradient(70% 50% at 50% 100%,rgba(190,236,226,.55),transparent 70%)}
@media (prefers-color-scheme:dark){body{background-image:radial-gradient(60% 50% at 12% 0%,rgba(120,60,90,.35),transparent 70%),
radial-gradient(70% 50% at 50% 100%,rgba(30,90,85,.4),transparent 70%)}}
main{background:var(--card);border:1px solid var(--line);border-radius:32px;padding:40px 32px 32px;max-width:440px;
width:100%;text-align:center;box-shadow:0 24px 50px -24px rgba(90,60,40,.35)}
img{width:88px;height:88px;border-radius:24%;margin:0 0 16px;box-shadow:0 14px 24px -10px rgba(90,60,40,.4)}
h1{font-family:"Fredoka",system-ui,sans-serif;font-weight:600;font-size:26px;line-height:1.2;margin:0 0 10px}
p{margin:0 0 12px;color:var(--ink2)}
input.code{font:700 28px/1.2 ui-monospace,Consolas,monospace;letter-spacing:.35em;text-transform:uppercase;
text-align:center;width:9em;max-width:100%;padding:12px 0 12px .35em;margin:10px 0 16px;background:var(--bg);
border:2px solid var(--amber);border-radius:18px;color:var(--ink)}
input.code:focus{outline:3px solid rgba(232,165,49,.35);outline-offset:2px}
button{font:600 17px "Fredoka",system-ui,sans-serif;background:var(--teal);color:#fff;border:0;border-radius:999px;
padding:14px 28px;cursor:pointer;box-shadow:0 4px 0 var(--teal-d)}
button:hover{transform:translateY(-1px)}button:active{transform:translateY(2px);box-shadow:0 1px 0 var(--teal-d)}
button:focus-visible{outline:3px solid rgba(24,122,115,.4);outline-offset:3px}
p.err{color:var(--err);font-weight:700}
p.small{font-size:14px;margin:20px 0 0}"""


def _shell(title: str, inner: str, status: int) -> HTMLResponse:
    # Favicon et logo : l'onglet du navigateur rattache visuellement ces pages à DodoTopia, au moment le plus
    # sensible du parcours. Mêmes icônes que le site (import tardif : site.py importe releases, qui importe auth).
    from . import site
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>DodoTopia – {escape(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
{site.icon_links()}<style>{_PAGE_STYLE}</style></head>
<body><main><img src="/static/logo.png" width="72" height="72" alt="DodoTopia">{inner}</main></body></html>"""
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


def _done_page(error: str = "", status: int = 200) -> HTMLResponse:
    title, text = _DONE_MESSAGES.get(error, _DONE_MESSAGES["discord"])
    return _shell(title, f"<h1>{escape(title)}</h1><p>{escape(text)}</p>", status)


def _code_page(login_id: str, remaining: int, wrong: bool = False, status: int = 200) -> HTMLResponse:
    """Formulaire « saisis le code affiché dans DodoTopia » (POST /auth/discord/confirm)."""
    err = ""
    if wrong:
        essais = "essai" if remaining == 1 else "essais"
        err = f'<p class="err">Code incorrect. Il te reste {remaining} {essais}.</p>'
    inner = f"""<h1>Connexion à DodoTopia</h1>
<p>Recopie le code affiché dans la fenêtre de DodoTopia pour confirmer que c'est bien toi qui te connectes.</p>
<form method="post" action="/auth/discord/confirm" autocomplete="off">
<input type="hidden" name="login_id" value="{escape(login_id, quote=True)}">
<input class="code" name="code" inputmode="latin" autocapitalize="characters" spellcheck="false"
 maxlength="{USER_CODE_LEN + 2}" pattern="[A-Za-z0-9 -]*" required autofocus aria-label="Code affiché dans DodoTopia">
{err}
<div><button type="submit">Continuer avec Discord</button></div>
</form>
<p class="small">Si tu n'as pas lancé de connexion depuis DodoTopia, ferme cet onglet : ne saisis jamais un code
qu'on t'a envoyé.</p>"""
    return _shell("Connexion", inner, status)


@router.get("/auth/discord/done")
def discord_done(error: str = ""):
    return _done_page(error, status=200 if not error else 400)


@router.post("/api/auth/poll", dependencies=[Depends(limit("auth_poll", 60, 60))])
def auth_poll(body: AuthPoll, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    t = _live_ticket(conn, settings, body.login_id)
    if t is None:
        raise api_error(404, "unknown_login", "Connexion inconnue ou expirée.")
    if not hmac.compare_digest(sha256_hex(body.verifier), t["verifier_hash"]):
        raise api_error(403, "bad_verifier", "Vérificateur incorrect.")
    if t["status"] in ("pending", "confirmed"):
        return {"status": "pending"}
    if t["status"] == "error":
        return {"status": "error", "error": t["error"]}
    if t["status"] == "used":
        raise api_error(410, "consumed", "Cette connexion a déjà été récupérée.")
    # ok : la session est créée maintenant, contre le vérifieur, et livrée une seule fois
    conn.execute("UPDATE login_tickets SET status='used', user_id=NULL WHERE id=?", (t["id"],))
    user = conn.execute("SELECT * FROM users WHERE id=?", (t["user_id"],)).fetchone() if t["user_id"] else None
    if user is None or user["banned"]:
        conn.commit()
        return {"status": "error", "error": "banned" if user is not None else "session"}
    token = create_session(conn, settings, user["id"])
    conn.commit()
    return {"status": "ok", "token": token, "user": user_public(user, settings)}


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


@router.delete("/api/me", dependencies=[Depends(limit("delete_me", 3, 3600))])
def delete_me(request: Request, user: db.Row = Depends(get_current_user), conn: db.Connection = Depends(db.get_db)):
    """Suppression du compte : sessions, tickets et signalements effacés ; les morceaux approuvés restent dans la
    bibliothèque mais sont anonymisés (uploader_id NULL -> « Compte supprimé ») ; les morceaux en attente ou
    refusés disparaissent avec leurs fichiers ; puis la ligne `users` elle-même."""
    from . import social
    from .gallery import drawing_files  # imports tardifs (library et gallery dépendent de auth)
    from .library import song_path

    settings = settings_of(request)
    uid = user["id"]
    doomed = conn.execute("SELECT id, sha256 FROM songs WHERE uploader_id=? AND status<>'approved'", (uid,)).fetchall()
    kept = conn.execute("SELECT COUNT(*) FROM songs WHERE uploader_id=? AND status='approved'", (uid,)).fetchone()[0]
    doomed_drawings = conn.execute("SELECT id, png_sha256 FROM drawings WHERE uploader_id=? AND status<>'approved'",
                                   (uid,)).fetchall()
    kept_drawings = conn.execute("SELECT COUNT(*) FROM drawings WHERE uploader_id=? AND status='approved'",
                                 (uid,)).fetchone()[0]
    with conn.transaction():
        conn.execute("DELETE FROM reports WHERE reporter_id=?", (uid,))
        conn.execute("UPDATE reports SET resolved_by=NULL WHERE resolved_by=?", (uid,))
        social.remove_user_likes(conn, uid)
        for song in doomed:
            conn.execute("DELETE FROM songs WHERE id=?", (song["id"],))
        conn.execute("UPDATE songs SET uploader_id=NULL WHERE uploader_id=?", (uid,))
        conn.execute("UPDATE songs SET reviewed_by=NULL WHERE reviewed_by=?", (uid,))
        for drawing in doomed_drawings:
            conn.execute("DELETE FROM drawings WHERE id=?", (drawing["id"],))
        conn.execute("UPDATE drawings SET uploader_id=NULL WHERE uploader_id=?", (uid,))
        conn.execute("UPDATE drawings SET reviewed_by=NULL WHERE reviewed_by=?", (uid,))
        conn.execute("DELETE FROM login_tickets WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
    for song in doomed:
        try:
            song_path(settings, song["sha256"]).unlink()
        except OSError:
            pass
    for drawing in doomed_drawings:
        for path in drawing_files(settings, drawing["png_sha256"]):
            try:
                path.unlink()
            except OSError:
                pass
    return {"ok": True, "songs_kept": kept, "songs_deleted": len(doomed), "drawings_kept": kept_drawings,
            "drawings_deleted": len(doomed_drawings)}


def cleanup(conn: db.Connection, settings: Settings) -> None:
    """Tickets périmés et sessions expirées (tâche de fond)."""
    conn.execute("DELETE FROM login_tickets WHERE created_at < ?", (db.iso_in(-settings.LOGIN_TICKET_S),))
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now_iso(),))
    conn.commit()
