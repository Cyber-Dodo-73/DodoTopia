# -*- coding: utf-8 -*-
"""Client en ligne de DodoTopia : serveur HTTP (santé, compte Discord, mise à jour, bibliothèque MIDI).

Tout passe par `urllib.request` (stdlib) avec des délais courts ; aucun appel réseau n'est fait depuis
`status()`. Les opérations longues tournent dans des threads daemon et déposent leur résultat dans l'état
que `status()` recopie sous verrou.

Intégration dans app.py (à faire par l'application, ce module ne touche pas à Api) :

    import online
    self._online = online.OnlineService(self._cfg, self._player, log=self._log, notify=self._notify,
                                        logfile=os.path.join(core.DATA_DIR, "online.log"),
                                        minimize=<callable : réduit la fenêtre, comme multi_calibrate>,
                                        request_quit=<callable : Api.quit()>,
                                        import_file=<callable(path, meta) -> song_id : copie dans songs/,
                                                     applique meta {title, sha256, online_id}, refresh_songs>)
    self._room = self._online.room          # room.RoomSession
    self._player.room = self._room          # Player.stop() / frappe clavier -> room.on_player_stop(reason)
    ... après `api._window = window` :  api._online.start_background()
    ... dans quit() et à la fin de main() :  api._online.close()
    ... après save_settings (bloc online / multi) :  api._online.apply_config()

  Les callbacks peuvent aussi être posées après coup : `self._online.set_callbacks(minimize=..., ...)`.
  Sans `import_file`, un import par défaut (copie dans songs/ avec suffixe « (2) », titre, sha, online_id,
  refresh_songs) est utilisé.

  Méthodes Api à écrire (toutes attrapent OnlineError -> toast, et renvoient get_state()) :
    online_refresh()                -> self._online.refresh()
    online_login()                  -> url = self._online.login()  (OnlineError si serveur injoignable)
    online_login_cancel()           -> self._online.login_cancel()
    online_logout()                 -> self._online.logout()
    online_search(q, page, sort)    -> self._online.search(q, page, sort)          (thread)
    online_download(id)             -> self._online.download(id)                   (thread)
    online_share(song_id)           -> self._online.share(song_id, path, title)    (thread)
    online_pending(page)            -> self._online.pending(page)                  (thread)
    online_moderate(id, action)     -> self._online.moderate(id, action)           (thread)
    online_reports()                -> self._online.reports()                      (thread)
    update_check()                  -> self._online.updater.check_async(manual=True)
    update_download()               -> self._online.updater.download_async()
    update_install()                -> self._online.updater.install()
    update_dismiss()                -> self._online.updater.dismiss()
    update_open_folder()            -> self._online.updater.open_folder()
    get_state()["online"]           -> self._online.status()
    get_state()["settings"]["online"] -> {k: cfg["online"][k] for k in ("server_url", "check_updates")}
    get_state()["songs"][i]         -> + "online_id", "sha256" (meta.get("online_id"), meta.get("sha256"))

Contrat des endpoints (Partie A du plan) : GET /api/health {status, version, min_client}, GET /api/me,
DELETE /api/me -> {ok, songs_kept, songs_deleted}, GET /api/stats -> {downloads_total, songs_approved, users, rooms_open},
POST /api/auth/start {verifier_hash} -> {login_id, url, expires_in, user_code} (le code de 5 caracteres est a
recopier sur la page ouverte : protection anti-hameconnage), POST /api/auth/poll {login_id, verifier}
-> {status: pending|ok|error, token?, user?, error?} (error "code" = trop de mauvais codes), POST /api/auth/logout,
GET /api/songs?q&page&per_page&sort -> {items, total, page, pages}, GET /api/songs/{id}, GET /api/songs/{id}/download,
POST /api/songs (multipart file + title) -> 201 | 409 {existing_id}, GET /api/admin/songs?status=pending, POST
/api/admin/songs/{id}/approve | /reject {reason}, GET /api/admin/reports?open=1,
GET /api/releases/latest?current=&platform= -> {version, notes, mandatory, published_at, update_available,
asset{url, filename, sha256, size, downloads}, assets{platform: asset}, signature (base64 Ed25519 | null),
signed_payload (JSON canonique de {version, assets{platform:{sha256, size, filename}}, mandatory, published_at})}.

Manifeste signe : avec RELEASE_SIGNING_PUBLIC_KEY renseignee, `signature` doit signer `signed_payload` (Ed25519,
PyNaCl) et `signed_payload` doit decrire exactement le manifeste recu (version, mandatory, published_at, asset de la
plateforme courante) ; sinon aucune mise a jour n'est proposee. Cle vide : manifeste accepte tel quel (journalise).
"""
import base64
import hashlib
import json
import os
import re
import secrets
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import core
import deeplink
import i18n
from core import DATA_DIR, FROZEN
from version import VERSION

IS_WINDOWS = sys.platform == "win32"
DEFAULT_SERVER_URL = "https://dodotopia.cyber-dodo.fr"     # serveur DodoTopia (modifiable dans Reglages > En ligne)
DEFAULT_ONLINE = {"server_url": DEFAULT_SERVER_URL, "check_updates": True, "auto_update": True}
HEALTH_TIMEOUT = 3          # secondes : sante du serveur
API_TIMEOUT = 5             # secondes : appels API
DOWNLOAD_TIMEOUT = 60       # secondes par bloc de telechargement
SONG_MAX_BYTES = 8 * 1024 * 1024   # plafond d'un .mid telecharge (le serveur en accepte 2 Mo au depot)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LOGIN_POLL_S = 1.5          # >= 1,5 s : le serveur limite /api/auth/poll a 60 appels par minute
LOGIN_MAX_S = 600
# Erreurs de ticket renvoyees par /api/auth/poll ({status: "error", error: <cle>}) -> cle de traduction
LOGIN_ERRORS = {
    "code": "login.error.code",
    "denied": "login.error.denied",
    "discord": "login.error.discord",
    "banned": "login.error.banned",
    "expired": "login.error.expired",
    "session": "login.error.session",
}
I18N_KEYS = ["login.error.code", "login.error.denied", "login.error.discord", "login.error.banned",
             "login.error.expired", "login.error.session",
             # erreurs du serveur traduites par code (error_text) : import par lien, galerie, metadonnees
             "online.import.error.https_required", "online.import.error.bad_url",
             "online.import.error.host_not_allowed", "online.import.error.unsupported_url",
             "online.import.error.invalid_midi", "online.import.error.private_address", "online.import.error.too_large",
             "online.import.error.not_found", "online.import.error.upstream_error",
             "online.import.error.too_many_redirects", "online.import.error.dns_error", "online.import.error.timeout",
             "online.import.error.gone",
             "online.gallery.error.duplicate", "online.gallery.error.too_large", "online.gallery.error.invalid_png",
             "online.gallery.error.image_too_large", "online.gallery.error.bad_cells", "online.gallery.error.not_found",
             "online.gallery.error.no_cells", "online.gallery.error.forbidden", "online.gallery.error.not_approved",
             "online.gallery.error.already_reported", "online.gallery.error.bad_reason",
             "online.share.error.bad_tags", "online.share.error.bad_instrument", "online.share.error.bad_source_url",
             "online.share.error.bad_license"]


def login_error_text(key):
    """Message affiche pour une erreur de connexion du serveur ; une cle inconnue est montree telle quelle."""
    if key in LOGIN_ERRORS:
        return i18n.t(LOGIN_ERRORS[key])
    return key or i18n.t("login.error.refused")
# Cle publique Ed25519 (base64, 32 octets) qui signe les manifestes de mise a jour. Vide : les manifestes sont
# acceptes sans verification (journalise). A renseigner avec la cle publique imprimee par
# `py publish_release.py --gen-key` (la meme que RELEASE_SIGNING_PUBLIC_KEY du serveur).
RELEASE_SIGNING_PUBLIC_KEY = ""
SIGNED_ASSET_FIELDS = ("sha256", "size", "filename")
UPDATE_VERSION_RE = re.compile(r"\d+(?:\.\d+){1,3}")
PER_PAGE = 50
PLATFORM_NAME = "windows" if IS_WINDOWS else ("linux" if sys.platform.startswith("linux") else sys.platform)
# Chemins ecrits par ce module (lus a l'appel, jamais lies a l'import : les tests les redirigent vers un tmp)
ACCOUNT_PATH = os.path.join(DATA_DIR, "account.json")
UPDATES_DIR = os.path.join(DATA_DIR, "updates")
DOWNLOADS_DIR = os.path.join(DATA_DIR, "downloads")

# ---- bibliotheque partagee : metadonnees, galerie, import par lien. Listes recopiees du serveur
# (server/app/schemas.py SONG_TAGS / LICENSES, library.py SONG_SORTS, gallery.py, config.py) : elles servent a
# refuser tot une saisie impossible ; le serveur reste seul juge.
SONG_TAGS = ("piano", "flute", "lute", "violin", "harp", "percussion", "pop", "rock", "classique", "jeu-video",
             "anime", "film", "folk", "noel", "calme", "rapide", "facile", "difficile")
MAX_TAGS = 8
LICENSES = ("own", "public_domain", "cc", "unknown")
SONG_SORTS = ("recent", "popular", "trending", "likes", "title")
DRAWING_SORTS = ("recent", "popular")
GALLERY_PER_PAGE = 24
DRAWING_PNG_MAX_BYTES = 512 * 1024          # MAX_DRAWING_PNG_BYTES du serveur
DRAWING_TITLE_MAX = 60
DRAWING_CELL_SIDE_MAX = 1024
MAX_SOURCE_URL_LEN = 500
MAX_SOURCE_NAME_LEN = 60
IMPORT_TIMEOUT = 45                         # le serveur va chercher le fichier (10 s par requete, 2 redirections)
INSTRUMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
IMPORT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
CELLS_FORMAT_RE = re.compile(r"^[A-Za-z0-9 x_.:-]{1,32}$")
ERROR_DOMAINS = {
    "import": ("https_required", "bad_url", "host_not_allowed", "unsupported_url", "invalid_midi", "private_address",
               "too_large", "not_found", "upstream_error", "too_many_redirects", "dns_error", "timeout", "gone"),
    "gallery": ("duplicate", "too_large", "invalid_png", "image_too_large", "bad_cells", "not_found", "no_cells",
                "forbidden", "not_approved", "already_reported", "bad_reason"),
    "share": ("bad_tags", "bad_instrument", "bad_source_url", "bad_license"),
}

# ---- adresses publiques du site. Table recopiee de server/app/site.py (ROUTES["songs"], ROUTES["gallery"],
# ROOM_SLUGS) et de site_pages/songs.py (song_url : /{lang}/<slug>/{id}-{slugify(titre)}) : a tenir a jour
# ensemble. Langues sans slug traduit (zh-CN, ja, th, id, fil) : slug anglais, comme le serveur.
SITE_LANGS = ("fr", "en", "es", "de", "pt-BR", "zh-CN", "ja", "th", "id", "fil")
PUBLIC_SLUGS = {
    "songs": {"fr": "morceaux", "en": "songs", "es": "canciones", "de": "lieder", "pt-BR": "musicas"},
    "gallery": {"fr": "galerie", "en": "gallery", "es": "galeria", "de": "galerie", "pt-BR": "galeria"},
    "room": {"fr": "salon", "en": "room", "es": "sala", "de": "raum", "pt-BR": "sala"},
}


def site_slugify(text, fallback="song", max_len=60):
    """Meme calcul que server/app/site_pages/_listing.py slugify : « Für Élise (piano) » -> fur-elise-piano."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = s[:max_len].rstrip("-")
    return s or fallback


def public_url(kind, lang, server_url=None, **ids):
    """Adresse publique d'une page du site, dans la langue de l'interface :
    song (id, title) -> {serveur}/{lang}/morceaux/{id}-{slug} ; drawing (id) -> /{lang}/galerie/{id} ;
    room (code) -> /{lang}/salon/{CODE} ; songs / gallery -> page d'index. None si un identifiant manque."""
    base = normalize_url(server_url) or DEFAULT_SERVER_URL
    lang = lang if lang in SITE_LANGS else "en"

    def slug(section):
        table = PUBLIC_SLUGS[section]
        return table.get(lang) or table["en"]
    try:
        if kind == "song":
            sid = int(ids["id"])
            return f"{base}/{lang}/{slug('songs')}/{sid}-{site_slugify(ids.get('title'), 'song')}" if sid > 0 else None
        if kind == "drawing":
            did = int(ids["id"])
            return f"{base}/{lang}/{slug('gallery')}/{did}" if did > 0 else None
        if kind == "room":
            code = re.sub(r"[^A-Z0-9]", "", str(ids.get("code") or "").upper())
            return f"{base}/{lang}/{slug('room')}/{code}" if len(code) == 6 else None
        if kind in ("songs", "gallery"):
            return f"{base}/{lang}/{slug(kind)}"
    except (KeyError, TypeError, ValueError):
        return None
    return None


def error_text(e, domain):
    """Message d'une OnlineError : traduit par code quand le serveur en donne un connu du domaine
    (import | gallery | share), sinon le message d'origine."""
    code = str((getattr(e, "payload", None) or {}).get("code") or "")
    if code in ERROR_DOMAINS.get(domain, ()):
        return i18n.t(f"online.{domain}.error.{code}")
    if getattr(e, "code", None) == 401:
        return i18n.t("online.error.login_required")
    return str(e)


def set_source(library, song_id, url, name):
    """Memorise dans library.json d'ou vient un morceau importe par lien (source_url https, source_name)."""
    url = str(url or "").strip()
    if not url.lower().startswith("https://") or len(url) > MAX_SOURCE_URL_LEN:
        return False
    with library._lock:
        m = library.meta(song_id)
        m["source_url"] = url
        name = core.clean_display_text(name, MAX_SOURCE_NAME_LEN)
        if name:
            m["source_name"] = name
        library.save()
    return True


def clean_song_meta(meta):
    """Metadonnees de partage {tags, instrument, source_url, source_name, license} nettoyees pour le depot.
    Leve OnlineError (message traduit) sur une valeur que le serveur refuserait."""
    meta = meta if isinstance(meta, dict) else {}
    raw = meta.get("tags") or []
    if isinstance(raw, str):
        raw = [raw]
    tags = []
    for tag in raw if isinstance(raw, (list, tuple)) else []:
        tag = str(tag or "").strip().lower()
        if tag not in SONG_TAGS:
            raise OnlineError(i18n.t("online.share.error.bad_tags"), code=422, payload={"code": "bad_tags"})
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise OnlineError(i18n.t("online.share.error.bad_tags"), code=422, payload={"code": "bad_tags"})
    inst = str(meta.get("instrument") or "").strip().lower()
    if inst and not INSTRUMENT_ID_RE.match(inst):
        raise OnlineError(i18n.t("online.share.error.bad_instrument"), code=422, payload={"code": "bad_instrument"})
    src = str(meta.get("source_url") or "").strip()
    if src:
        parts = urllib.parse.urlsplit(src) if len(src) <= MAX_SOURCE_URL_LEN else None
        if (parts is None or parts.scheme.lower() != "https" or not parts.hostname or "." not in parts.hostname
                or "@" in parts.netloc or re.search(r"[\s\x00-\x1f\x7f<>\"'`\\]", src)):
            raise OnlineError(i18n.t("online.share.error.bad_source_url"), code=422, payload={"code": "bad_source_url"})
    lic = str(meta.get("license") or "unknown").strip().lower()
    if lic not in LICENSES:
        raise OnlineError(i18n.t("online.share.error.bad_license"), code=422, payload={"code": "bad_license"})
    name = core.clean_display_text(meta.get("source_name"), MAX_SOURCE_NAME_LEN)
    return {"tags": tags, "instrument": inst, "source_url": src, "source_name": name, "license": lic}


def decode_png_data_url(data_url, max_bytes):
    """`data:image/png;base64,...` -> octets PNG verifies (prefixe, base64 strict, signature, taille).
    Leve ValueError avec un code court : prefix | base64 | png | size."""
    prefix = "data:image/png;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ValueError("prefix")
    body = data_url[len(prefix):]
    if len(body) > (max_bytes * 4) // 3 + 8:
        raise ValueError("size")
    try:
        data = base64.b64decode(body, validate=True)
    except (ValueError, TypeError):
        raise ValueError("base64") from None
    if len(data) > max_bytes:
        raise ValueError("size")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("png")
    return data


def clean_cells_job(job):
    """Grille {format, w, h, cells} verifiee (forme attendue par POST /api/drawings et set_draw_job) ; None sinon."""
    if not isinstance(job, dict):
        return None
    fmt = str(job.get("format") or "")
    try:
        w, h = int(job.get("w")), int(job.get("h"))
        cells = [int(c) for c in job.get("cells") or []]
    except (TypeError, ValueError):
        return None
    if not CELLS_FORMAT_RE.match(fmt) or not (1 <= w <= DRAWING_CELL_SIDE_MAX and 1 <= h <= DRAWING_CELL_SIDE_MAX):
        return None
    if len(cells) != w * h or any(c < -1 or c > 65535 for c in cells):
        return None
    return {"format": fmt, "w": w, "h": h, "cells": cells}


def ensure_defaults(cfg):
    """cfg["online"] complete avec les valeurs par defaut, URL normalisee (pattern sync.ensure_defaults)."""
    o = cfg.setdefault("online", {})
    for k, v in DEFAULT_ONLINE.items():
        o.setdefault(k, v)
    o["server_url"] = normalize_url(o.get("server_url")) or DEFAULT_SERVER_URL
    o["check_updates"] = bool(o.get("check_updates", True))
    o["auto_update"] = bool(o.get("auto_update", True))
    return o


def normalize_url(url):
    """'dodotopia.fr/' -> 'https://dodotopia.fr' ; chaine vide si rien."""
    url = str(url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def parse_version(s):
    """'1.7.0' -> (1, 7, 0) ; tolere un suffixe ('1.7.0-beta' -> (1, 7, 0)) ; () si illisible."""
    out = []
    for part in str(s or "").strip().split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


class OnlineError(Exception):
    """Erreur reseau ou reponse d'erreur du serveur (message lisible pour un toast)."""

    def __init__(self, message, code=None, payload=None):
        super().__init__(message)
        self.code = code
        self.payload = payload if isinstance(payload, dict) else {}


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa
        return ssl.create_default_context()


# ---------------------------------------------------------------- client HTTP
class OnlineClient:
    """Appels HTTP vers le serveur : JSON, Bearer, multipart, telechargement verifie."""

    def __init__(self, server_url, token_getter=None, log=None):
        self.server_url = normalize_url(server_url)
        self.token_getter = token_getter or (lambda: None)
        self.log = log or (lambda m: None)
        self.user_agent = f"DodoTopia/{VERSION} ({PLATFORM_NAME})"
        self._ctx = None

    def _context(self):
        if self._ctx is None:
            self._ctx = _ssl_context()
        return self._ctx

    def url(self, path, params=None):
        if path.lower().startswith(("http://", "https://")):
            u = path
        else:
            u = self.server_url + ("/" if not path.startswith("/") else "") + path
        if params:
            q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None and v != ""})
            if q:
                u += ("&" if "?" in u else "?") + q
        return u

    def ws_url(self, path="/ws"):
        """wss://<domaine>/ws (ws:// pour un serveur http)."""
        u = self.server_url
        if u.lower().startswith("https://"):
            u = "wss://" + u[8:]
        elif u.lower().startswith("http://"):
            u = "ws://" + u[7:]
        return u + path

    def _headers(self, extra=None, auth=True):
        h = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if auth:
            tok = self.token_getter()
            if tok:
                h["Authorization"] = f"Bearer {tok}"
        if extra:
            h.update(extra)
        return h

    def _open(self, req, timeout):
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=self._context())
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")
                payload = json.loads(body) if body else {}
            except Exception:  # noqa
                payload = {}
            msg = ""
            if isinstance(payload, dict):
                detail = payload.get("detail")
                if isinstance(detail, dict):          # format du serveur : {"detail": {"code", "message", ...}}
                    payload = dict(payload, **detail)
                    msg = detail.get("message") or detail.get("code") or ""
                elif isinstance(detail, list):        # erreur de validation FastAPI
                    first = detail[0] if detail and isinstance(detail[0], dict) else {}
                    msg = i18n.t("online.error.invalid_request", detail=first.get("msg", "validation"))
                else:
                    msg = payload.get("message") or detail or payload.get("error") or ""
                if isinstance(msg, (list, dict)):
                    msg = json.dumps(msg, ensure_ascii=False)[:200]
            else:
                payload = {}
            if e.code == 429:
                retry = e.headers.get("Retry-After") if e.headers else None
                msg = (msg or i18n.t("online.error.too_many")) + (i18n.t("online.error.retry_after", seconds=retry) if retry else "")
            raise OnlineError(str(msg) or i18n.t("online.error.server", code=e.code), code=e.code, payload=payload) from None
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise OnlineError(i18n.t("online.error.unreachable", reason=reason)) from None
        except (OSError, ValueError) as e:      # timeout (socket.timeout est un OSError), SSL, URL invalide
            raise OnlineError(i18n.t("online.error.unreachable", reason=e)) from None

    def request(self, method, path, json_body=None, params=None, headers=None, timeout=API_TIMEOUT,
                data=None, auth=True):
        """Requete JSON ; renvoie le corps decode (dict, ou {} si vide). Leve OnlineError."""
        h = self._headers(headers, auth)
        body = data
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url(path, params), data=body, method=method.upper(), headers=h)
        with self._open(req, timeout) as resp:
            raw = resp.read()
            status = getattr(resp, "status", 200)
        if not raw:
            return {"_status": status}
        try:
            out = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise OnlineError(i18n.t("online.error.bad_response"), code=status) from None
        if isinstance(out, dict):
            out.setdefault("_status", status)
        return out

    def get(self, path, params=None, timeout=API_TIMEOUT, auth=True):
        return self.request("GET", path, params=params, timeout=timeout, auth=auth)

    def post(self, path, json_body=None, params=None, timeout=API_TIMEOUT, auth=True):
        return self.request("POST", path, json_body=json_body if json_body is not None else {}, params=params,
                            timeout=timeout, auth=auth)

    def stats(self, timeout=API_TIMEOUT):
        """GET /api/stats -> {downloads_total, songs_approved, users, rooms_open} (chiffres publics du serveur)."""
        r = self.get("/api/stats", timeout=timeout, auth=False)
        r.pop("_status", None)
        return r

    def upload(self, path, fields, filefield, filepath, timeout=DOWNLOAD_TIMEOUT, content_type="audio/midi"):
        """POST multipart/form-data (ecrit a la main) : champs texte + un fichier."""
        with open(filepath, "rb") as f:
            content = f.read()
        return self.upload_bytes(path, fields, filefield, os.path.basename(filepath), content, timeout, content_type)

    def upload_bytes(self, path, fields, filefield, filename, content, timeout=DOWNLOAD_TIMEOUT,
                     content_type="application/octet-stream"):
        """POST multipart/form-data : champs texte + un fichier donne en memoire (octets)."""
        boundary = "----DodoTopia" + uuid.uuid4().hex
        crlf = b"\r\n"
        parts = []
        for k, v in (fields or {}).items():
            if v is None:
                continue
            parts.append(b"--" + boundary.encode() + crlf)
            parts.append(f'Content-Disposition: form-data; name="{k}"'.encode() + crlf + crlf)
            parts.append(str(v).encode("utf-8") + crlf)
        # Nom de partie multipart : liste blanche ASCII. Un nom local contenant un guillemet ou un
        # retour a la ligne casserait sinon l'en-tete Content-Disposition envoye au serveur.
        fname = re.sub(r"[^A-Za-z0-9 ._-]+", "", core.clean_display_text(os.path.basename(str(filename or "")), 120))
        fname = fname.strip(" .") or ("morceau.mid" if content_type == "audio/midi" else "fichier.bin")
        parts.append(b"--" + boundary.encode() + crlf)
        parts.append(f'Content-Disposition: form-data; name="{filefield}"; filename="{fname}"'.encode() + crlf)
        parts.append(f"Content-Type: {content_type}".encode() + crlf + crlf)
        parts.append(content + crlf)
        parts.append(b"--" + boundary.encode() + b"--" + crlf)
        body = b"".join(parts)
        return self.request("POST", path, data=body, timeout=timeout,
                            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                     "Content-Length": str(len(body))})

    def download(self, path, dest, expected_sha256=None, on_progress=None, timeout=DOWNLOAD_TIMEOUT,
                 max_bytes=None):
        """Telecharge dans `dest` via `dest.part`, sha256 calcule au fil de l'eau (verifie si attendu),
        on_progress(done_bytes, total_bytes|None). Renvoie le sha256 hex.

        `max_bytes` coupe net un serveur (ou un intermediaire) qui enverrait un flux sans fin : le fichier
        partiel est efface et rien n'est remis a l'appelant."""
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        part = dest + ".part"
        h = hashlib.sha256()
        done = 0
        req = urllib.request.Request(self.url(path), headers=self._headers({"Accept": "*/*"}))
        try:
            with self._open(req, timeout) as resp, open(part, "wb") as out:
                total = resp.headers.get("Content-Length")
                total = int(total) if total and total.isdigit() else None
                if max_bytes and total and total > max_bytes:
                    raise OnlineError(i18n.t("online.error.file_too_big", kb=total // 1024))
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if max_bytes and done > max_bytes:
                        raise OnlineError(i18n.t("online.error.file_too_big_over", kb=max_bytes // 1024))
                    if on_progress:
                        on_progress(done, total)
        except OnlineError:
            _unlink(part)
            raise
        except OSError as e:
            _unlink(part)
            raise OnlineError(i18n.t("online.error.download_interrupted", error=e)) from None
        sha = h.hexdigest()
        if expected_sha256 and sha.lower() != str(expected_sha256).lower():
            _unlink(part)
            raise OnlineError(i18n.t("online.error.corrupt"))
        _unlink(dest)
        os.replace(part, dest)
        return sha


def _unlink(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------- compte
class Account:
    """Jeton de session Discord dans DATA_DIR/account.json {server_url, token, user, saved_at} ; jamais dans
    config.json (expose a l'interface). Invalide (ignore) si l'URL du serveur a change."""

    def __init__(self, path=None, server_url=""):
        self.path = path or ACCOUNT_PATH
        self.server_url = normalize_url(server_url)
        self.token = None
        self.user = None
        self.saved_at = 0
        self._lock = threading.Lock()

    def load(self, server_url=None):
        if server_url is not None:
            self.server_url = normalize_url(server_url)
        with self._lock:
            self.token = None
            self.user = None
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    d = json.load(f) or {}
            except (OSError, ValueError):
                return False
            if normalize_url(d.get("server_url")) != self.server_url or not d.get("token"):
                return False
            self.token = str(d["token"])
            self.user = d.get("user") if isinstance(d.get("user"), dict) else None
            self.saved_at = d.get("saved_at", 0)
            return True

    def save(self, token, user):
        with self._lock:
            self.token = token
            self.user = user if isinstance(user, dict) else None
            self.saved_at = time.time()
            data = {"server_url": self.server_url, "token": token, "user": self.user, "saved_at": self.saved_at}
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                if not IS_WINDOWS:
                    os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

    def clear(self):
        with self._lock:
            self.token = None
            self.user = None
            _unlink(self.path)

    def set_user(self, user):
        if isinstance(user, dict):
            self.user = user
            if self.token:
                self.save(self.token, user)

    def logged_in(self):
        return bool(self.token)


# ---------------------------------------------------------------- connexion Discord
class LoopbackListener:
    """Petit serveur HTTP sur 127.0.0.1 (port libre choisi par le systeme) qui attend le retour du navigateur
    apres l'autorisation Discord : GET /dodotopia/login?login_id=<ticket>&grant=<bon>. Il ne repond qu'au ticket
    en cours, garde le bon, puis renvoie le navigateur sur la page « Connecte » du serveur. Tout le reste : 404.
    Rien n'est ecoute sur le reseau : l'adresse 127.0.0.1 n'est joignable que depuis cet ordinateur."""

    PATH = "/dodotopia/login"

    def __init__(self, done_url):
        import http.server
        self.login_id = None            # renseigne des que le serveur a cree le ticket
        self.grant = None
        self.event = threading.Event()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):   # noqa: N802 (nom impose par http.server)
                parts = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(parts.query)
                login_id = (q.get("login_id") or [""])[0]
                grant = (q.get("grant") or [""])[0]
                if (parts.path != outer.PATH or not outer.login_id or login_id != outer.login_id
                        or not grant or len(grant) > 128):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                outer.grant = grant
                outer.event.set()
                self.send_response(302)
                self.send_header("Location", done_url)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):   # pas de journal sur stderr (le bon est dans l'adresse)
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, name="login-loopback", daemon=True).start()

    def close(self):
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:  # noqa
            pass


class LoginFlow:
    """Ticket + navigateur + interrogation : POST /api/auth/start, ouverture de l'URL, POST /api/auth/poll
    toutes les 1,5 s pendant 10 min au plus.

    Par defaut, rien a recopier (mode « loopback ») : l'appli ecoute sur 127.0.0.1 (LoopbackListener), donne son
    port au serveur, et le navigateur lui rapporte un bon a usage unique apres l'autorisation Discord ; le serveur
    ne livre la session que contre ce bon. Un lien envoye par un tiers ne peut donc connecter personne sur SON
    ticket : le bon arriverait sur l'ordinateur de la victime.

    En secours (`with_code=True`, ecoute impossible, ou serveur plus ancien) : mode « code ». `user_code`
    (5 caracteres, ex. K7PQ2) est affiche dans l'app et la page ouverte le demande avant de rediriger vers
    Discord ; ce mode sert aussi a se connecter depuis un autre appareil (telephone)."""

    def __init__(self, client, account, open_url, log=None, notify=None, on_done=None):
        self.client = client
        self.account = account
        self.open_url = open_url
        self.log = log or (lambda m: None)
        self.notify = notify or (lambda msg, kind="info": None)
        self.on_done = on_done
        self.state = "idle"         # idle | waiting | ok | error
        self.url = None
        self.user_code = None       # code a recopier sur la page de connexion (mode « code », state == waiting)
        self.mode = None            # loopback | code (tant que state == waiting)
        self.error = ""
        self.expires_at = 0.0
        self.poll_s = LOGIN_POLL_S
        self._cancel = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self, with_code=False):
        """Demande un ticket, ouvre le navigateur, lance l'interrogation. Renvoie l'URL (a afficher aussi
        dans l'interface avec un bouton Copier) ; leve OnlineError si le serveur refuse. Rappele pendant
        l'attente, rouvre simplement le navigateur sur le meme ticket (bouton « Ouvrir le navigateur »).
        `with_code` : mode « code » demande (connexion depuis un autre appareil) ; un ticket sans code en
        attente est alors abandonne."""
        with self._lock:
            waiting = self.state == "waiting" and self._thread and self._thread.is_alive()
            if waiting and with_code and self.mode == "loopback":
                self._cancel.set()          # on repart sur un ticket a code
                waiting = False
            if waiting:
                url = self.url
            else:
                verifier = secrets.token_urlsafe(32)
                vh = hashlib.sha256(verifier.encode("ascii")).hexdigest()
                listener = None
                if not with_code:
                    try:
                        listener = LoopbackListener(self.client.url("/auth/discord/done"))
                    except OSError as e:    # ecoute locale impossible : on retombe sur le code
                        self.log(f"connexion : écoute locale impossible ({e})")
                payload = {"verifier_hash": vh}
                if listener is not None:
                    payload["loopback_port"] = listener.port
                try:
                    r = self.client.post("/api/auth/start", payload, auth=False)
                except OnlineError as e:
                    if listener is not None:
                        listener.close()
                    self.state, self.error = "error", str(e)
                    raise
                login_id, url = r.get("login_id"), r.get("url")
                if not login_id or not url:
                    if listener is not None:
                        listener.close()
                    self.state, self.error = "error", i18n.t("online.error.unexpected_response")
                    raise OnlineError(self.error)
                if listener is not None and r.get("mode") != "loopback":
                    listener.close()        # serveur plus ancien : il a ignore le port, il attend le code
                    listener = None
                if listener is not None:
                    listener.login_id = str(login_id)
                self.mode = "loopback" if listener is not None else "code"
                expires_in = float(r.get("expires_in") or LOGIN_MAX_S)
                self.expires_at = time.time() + min(expires_in, LOGIN_MAX_S)
                code = str(r.get("user_code") or "").strip().upper()
                self.user_code = code[:16] or None
                self.url, self.error, self.state = url, "", "waiting"
                # un evenement d'annulation par ticket : l'ancien fil s'arrete meme si un nouveau demarre aussitot
                self._cancel = threading.Event()
                self._thread = threading.Thread(target=self._poll, args=(login_id, verifier, listener, self._cancel),
                                                name="login", daemon=True)
                self._thread.start()
        try:
            if not self.open_url(url):
                self.notify(i18n.t("login.open_link"), "warn")
        except Exception as e:  # noqa
            self.log(f"navigateur : {e}")
        return url

    def cancel(self):
        self._cancel.set()
        if self.state == "waiting":
            self.state = "idle"
        self.url = None
        self.user_code = None
        self.mode = None

    def _poll(self, login_id, verifier, listener=None, cancel=None):
        cancel = cancel or self._cancel
        try:
            self._poll_loop(login_id, verifier, listener, cancel)
        finally:
            if listener is not None:
                listener.close()

    def _poll_loop(self, login_id, verifier, listener, cancel):
        while not cancel.is_set():
            if time.time() > self.expires_at:
                self.state, self.error = "error", i18n.t("login.error.expired")
                break
            body = {"login_id": login_id, "verifier": verifier}
            if listener is not None and listener.grant:
                body["grant"] = listener.grant      # le bon rapporte par le navigateur : la session suit
            try:
                r = self.client.post("/api/auth/poll", body, auth=False)
            except OnlineError as e:
                if e.code in (404, 410):
                    self.state, self.error = "error", i18n.t("login.error.expired")
                    break
                if e.code == 403:
                    self.state, self.error = "error", i18n.t("login.error.ticket_refused")
                    break
                self.log(f"connexion : {e}")
                r = {"status": "pending"}
            st = r.get("status")
            if st == "ok" and r.get("token"):
                self.account.save(str(r["token"]), r.get("user"))
                self.state, self.url, self.user_code, self.mode = "ok", None, None, None
                name = (r.get("user") or {}).get("username") or "Discord"
                self.notify(i18n.t("login.connected", name=name), "ok")
                self.log(f"connecté : {name}")
                if self.on_done:
                    try:
                        self.on_done(True)
                    except Exception:  # noqa
                        pass
                return
            if st == "error":
                key = str(r.get("error") or "")
                self.state, self.error = "error", login_error_text(key)
                self.log(f"connexion refusée ({key or 'sans motif'})")
                break
            if listener is not None and not listener.grant:
                listener.event.wait(self.poll_s)    # reveille des que le navigateur revient
                if cancel.is_set():
                    return
            elif cancel.wait(self.poll_s):
                return
        if cancel.is_set():
            return
        if self.state == "error":
            self.notify(self.error, "warn")
            self.url = None
            self.user_code = None
            self.mode = None
            if self.on_done:
                try:
                    self.on_done(False)
                except Exception:  # noqa
                    pass

    def status(self):
        left = max(0, int(self.expires_at - time.time())) if self.state == "waiting" else None
        return {"state": self.state, "url": self.url, "user_code": self.user_code if self.state == "waiting" else None,
                "mode": self.mode if self.state == "waiting" else None, "error": self.error, "expires_in": left}


# ---------------------------------------------------------------- mise a jour
def _b64(value):
    """base64 strict -> bytes ; None si absent ou illisible."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return base64.b64decode(value.strip(), validate=True)
    except (ValueError, TypeError):
        return None


def verify_release_manifest(manifest, platform_key, public_key=None, log=None):
    """Verifie un manifeste de /api/releases/… : renvoie (ok, motif).

    - cle publique vide : manifeste accepte tel quel (journalise « non signe accepté ») ;
    - cle renseignee : `signature` (base64, Ed25519) doit signer `signed_payload` ; puis `signed_payload`
      decode doit decrire exactement le manifeste recu : version, mandatory, published_at, et pour la
      plateforme courante sha256/size/filename de l'asset. Toute divergence, signature absente ou invalide,
      ou PyNaCl manquant -> (False, motif) : aucune mise a jour n'est proposee."""
    log = log or (lambda m: None)
    pub = RELEASE_SIGNING_PUBLIC_KEY if public_key is None else public_key
    pub = str(pub or "").strip()
    if not pub:
        log("mise à jour : manifeste non signé accepté (clé publique non configurée)")
        return True, ""
    try:
        from nacl.exceptions import BadSignatureError
        from nacl.signing import VerifyKey
    except ImportError:
        return False, "module PyNaCl absent : signature invérifiable"
    key = _b64(pub)
    if not key or len(key) != 32:
        return False, "clé publique de signature illisible"
    payload = manifest.get("signed_payload") if isinstance(manifest, dict) else None
    sig = _b64(manifest.get("signature")) if isinstance(manifest, dict) else None
    if not isinstance(payload, str) or not payload or sig is None:
        return False, "manifeste non signé"
    if len(sig) != 64:
        return False, "signature mal formée"
    try:
        VerifyKey(key).verify(payload.encode("utf-8"), sig)
    except BadSignatureError:
        return False, "signature invalide"
    except Exception as e:  # noqa
        return False, f"signature invérifiable ({e})"
    try:
        doc = json.loads(payload)
    except ValueError:
        return False, "contenu signé illisible"
    if not isinstance(doc, dict):
        return False, "contenu signé illisible"
    if str(doc.get("version")) != str(manifest.get("version")):
        return False, "version différente du contenu signé"
    if bool(doc.get("mandatory")) != bool(manifest.get("mandatory")):
        return False, "champ mandatory différent du contenu signé"
    if doc.get("published_at") != manifest.get("published_at"):
        return False, "published_at différent du contenu signé"
    assets = manifest.get("assets") if isinstance(manifest.get("assets"), dict) else {}
    got = assets.get(platform_key)
    if not isinstance(got, dict) and isinstance(manifest.get("asset"), dict):
        got = manifest["asset"]
    signed_assets = doc.get("assets") if isinstance(doc.get("assets"), dict) else {}
    want = signed_assets.get(platform_key)
    if got is None and want is None:
        return True, ""                       # pas de binaire pour cette plateforme : rien a proposer
    if not isinstance(got, dict) or not isinstance(want, dict):
        return False, "asset de la plateforme absent du contenu signé"
    for k in SIGNED_ASSET_FIELDS:
        a, b = got.get(k), want.get(k)
        if k == "sha256":
            a, b = str(a or "").lower(), str(b or "").lower()
        elif k == "size":
            try:
                a, b = int(a), int(b)
            except (TypeError, ValueError):
                return False, "taille de l'asset illisible"
        if a != b:
            return False, f"{k} de l'asset différent du contenu signé"
    return True, ""


class Updater:
    """Verification (manifeste signe), telechargement (DATA_DIR/updates/, sha256 verifie) et installation."""

    @staticmethod
    def refused_msg():
        return i18n.t("update.refused")

    def __init__(self, client, cfg, log=None, notify=None, request_quit=None, open_folder=None, updates_dir=None,
                 on_available=None):
        self.client = client
        self.cfg = cfg
        self.log = log or (lambda m: None)
        self.notify = notify or (lambda msg, kind="info": None)
        # on_available(message, version) : annonce d'une version disponible (toast persistant de l'application) ;
        # sans ce callback l'annonce passe par notify(). Jamais reconnue par son texte.
        self.on_available = on_available
        self.request_quit = request_quit or (lambda: None)
        self.open_folder_cb = open_folder
        self.updates_dir = updates_dir or UPDATES_DIR
        self.state = "idle"     # idle | checking | available | downloading | ready | installing | error | uptodate
        self.latest = None
        self.notes = ""
        self.mandatory = False
        self.asset = None       # {url, sha256, size}
        self.path = None
        self.error = ""
        self.progress = 0.0
        self.done_mb = 0.0
        self.size_mb = 0.0
        self.checked_at = 0
        self.auto = False       # installer seul au demarrage (Reglages > En ligne)
        self.install_pause_s = 1.5   # laisser le toast s'afficher avant la fermeture (0 dans les tests)
        self._notified = None   # version deja annoncee par un toast (une fois par session)
        self._dismissed = None
        self._lock = threading.Lock()
        self._thread = None

    # ---- dossier updates/
    def cleanup(self, keep=None):
        """Efface de updates/ les restes inutiles : fichiers .part, binaires d'une version deja installee ou
        plus ancienne, et, si `keep` est donne, ceux d'une autre version que `keep`. Renvoie les noms effaces."""
        removed = []
        try:
            names = os.listdir(self.updates_dir)
        except OSError:
            return removed
        cur = parse_version(VERSION)
        for name in names:
            path = os.path.join(self.updates_dir, name)
            if not os.path.isfile(path):
                continue
            m = UPDATE_VERSION_RE.search(name)
            ver = m.group(0) if m else None
            drop = name.endswith(".part") or ver is None
            if ver is not None:
                drop = drop or parse_version(ver) <= cur or (keep is not None and ver != str(keep))
            if not drop:
                continue
            if self.path and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(self.path)):
                if keep is None or ver == str(keep):
                    continue
                self.path = None
            _unlink(path)
            if not os.path.exists(path):
                removed.append(name)
        if removed:
            self.log(f"mises à jour : nettoyage de {', '.join(removed)}")
        return removed

    # ---- nature de l'installation
    @staticmethod
    def install_kind():
        """setup (installeur Inno : unins000.exe a cote de l'exe) | portable (zip) | targz (Linux) | source."""
        if not FROZEN:
            return "source"
        if IS_WINDOWS:
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            if os.path.isfile(os.path.join(exe_dir, "unins000.exe")):
                return "setup"
            return "portable"
        return "targz"

    @classmethod
    def platform_key(cls):
        kind = cls.install_kind()
        return {"setup": "windows-setup", "portable": "windows-portable", "targz": "linux-x64"}.get(
            kind, "windows-setup" if IS_WINDOWS else "linux-x64")

    # ---- verification
    def check_async(self, manual=False):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            if self.state in ("downloading", "installing"):
                return False
            self.state = "checking"
            self.error = ""
            self._thread = threading.Thread(target=self._check, args=(manual,), name="update-check", daemon=True)
            self._thread.start()
            return True

    def _check(self, manual):
        try:
            r = self.client.get("/api/releases/latest", {"current": VERSION, "platform": self.platform_key()},
                                auth=False)
        except OnlineError as e:
            if e.code == 404:                # aucune version publiée : rien à proposer
                self.checked_at = time.time()
                self.state, self.latest = "uptodate", VERSION
                if manual:
                    self.notify(i18n.t("update.uptodate", version=VERSION), "ok")
                return
            self.state, self.error = "error", str(e)
            if manual:
                self.notify(i18n.t("update.check_failed", error=e), "warn")
            return
        self.checked_at = time.time()
        latest = str(r.get("version") or "")
        pk = self.platform_key()
        asset = r.get("asset")
        if not asset and isinstance(r.get("assets"), dict):
            asset = r["assets"].get(pk)
        newer = bool(latest) and parse_version(latest) > parse_version(VERSION)
        if r.get("update_available") is False:
            newer = False
        if not newer:
            self.state = "uptodate"
            self.latest = latest or VERSION
            if manual:
                self.notify(i18n.t("update.uptodate", version=VERSION), "ok")
            return
        # Manifeste signe : rien n'est propose (ni telecharge, ni installe) si la signature ne couvre pas
        # exactement ce que le serveur annonce pour cette plateforme.
        ok, why = verify_release_manifest(r, pk, log=self.log)
        if not ok:
            self.log(f"mise à jour {latest} refusée : {why}")
            self.state, self.error = "error", self.refused_msg()
            self.latest, self.asset, self.notes, self.mandatory = None, None, "", False
            self.notify(self.error, "danger")
            return
        self.latest = latest
        self.notes = str(r.get("notes") or "")
        self.mandatory = bool(r.get("mandatory"))
        self.asset = asset if isinstance(asset, dict) and asset.get("url") else None
        self.cleanup(keep=latest)
        if self.path and os.path.isfile(self.path) and self.asset and self._file_ok(self.path, self.asset):
            self.state = "ready"
        else:
            self.state = "available"
        if latest == self._dismissed and not manual and not self.mandatory:
            self.state = "idle"
            return
        self.log(f"mise à jour disponible : {latest} (installée : {VERSION})"
                 + (" — obligatoire" if self.mandatory else ""))
        # installation automatique au demarrage : pas de toast « Installer » a cliquer, tout se fait seul
        will_auto = (not manual and self.install_kind() == "setup" and bool(self.asset)
                     and (self.auto or self.mandatory))
        if (self._notified != latest or manual) and not will_auto:
            self._notified = latest
            msg = i18n.t("update.available", version=latest, mandatory=bool(self.mandatory))
            if self.on_available:
                self.on_available(msg, latest)
            else:
                self.notify(msg, "info")
        # Mise a jour automatique : seulement au demarrage (pas sur une verification manuelle) et seulement
        # pour une installation par installeur, qui sait fermer l'app, s'installer en silence et la relancer.
        # En portable ou sous Linux il faudrait remplacer des fichiers en cours d'usage : on s'en tient au toast.
        # Une version obligatoire s'installe meme si l'installation automatique est desactivee.
        if will_auto:
            if self.mandatory and not self.auto:
                self.notify(i18n.t("update.mandatory_install", version=latest), "warn")
            self._auto_install(latest)

    def _auto_install(self, latest):
        """Telecharge puis lance l'installeur sans rien demander : on est au demarrage, rien n'est en cours."""
        self.notify(i18n.t("update.downloading", version=latest), "info")
        if self.state != "ready":
            self.state = "downloading"
            self.progress = self.done_mb = 0.0
            self.size_mb = float((self.asset or {}).get("size") or 0) / 1e6
            self._download()
        if self.state != "ready":
            return
        self.log(f"installation automatique de {latest}")
        self.notify(i18n.t("update.installing", version=latest), "info")
        if self.install_pause_s > 0:
            time.sleep(self.install_pause_s)     # laisser le toast s'afficher avant la fermeture
        self.install()

    def _file_ok(self, path, asset):
        try:
            return core.file_sha256(path).lower() == str(asset.get("sha256") or "").lower()
        except OSError:
            return False

    # ---- telechargement
    def download_async(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            if self.state not in ("available", "error", "ready") or not self.asset:
                if not self.asset:
                    self.notify(i18n.t("update.no_asset"), "warn")
                return False
            if self.state == "ready" and self.path and os.path.isfile(self.path):
                return True
            self.state = "downloading"
            self.error = ""
            self.progress = self.done_mb = 0.0
            self.size_mb = float(self.asset.get("size") or 0) / 1e6
            self._thread = threading.Thread(target=self._download, name="update-dl", daemon=True)
            self._thread.start()
            return True

    def _download(self):
        asset = self.asset
        url = str(asset["url"])
        name = os.path.basename(urllib.parse.urlparse(url).path) or f"DodoTopia-{self.latest}"
        name = "".join(ch for ch in name if ch.isalnum() or ch in "._-") or "update.bin"
        dest = os.path.join(self.updates_dir, name)

        def progress(done, total):
            tot = total or float(asset.get("size") or 0)
            self.done_mb = done / 1e6
            if tot:
                self.size_mb = tot / 1e6
                self.progress = min(1.0, done / tot)

        try:
            if os.path.isfile(dest) and self._file_ok(dest, asset):
                self.path, self.state, self.progress = dest, "ready", 1.0
                return
            self.client.download(url, dest, asset.get("sha256"), progress)
            self.path, self.state, self.progress = dest, "ready", 1.0
            self.log(f"mise à jour {self.latest} téléchargée : {dest}")
        except OnlineError as e:
            self.state, self.error = "error", str(e)
            self.notify(i18n.t("update.download_failed", error=e), "warn")

    # ---- installation
    def install(self):
        kind = self.install_kind()
        if kind == "source":
            self.notify(i18n.t("update.source_disabled"), "warn")
            return False
        if self.state == "available":
            return self.download_async()
        if self.state != "ready" or not self.path or not os.path.isfile(self.path):
            self.notify(i18n.t("update.not_downloaded"), "warn")
            return False
        if kind == "setup":
            self.state = "installing"
            try:
                flags = 0
                if IS_WINDOWS:
                    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                # /VERYSILENT : aucune fenetre d'installeur (ni assistant, ni barre de progression), comme
                # Discord ; /SUPPRESSMSGBOXES : aucune question. L'installeur ferme l'app, remplace les fichiers et
                # la relance avec --updated ([Run] ... skipifnotsilent dans installer.iss).
                subprocess.Popen([self.path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS",
                                  "/NORESTART", "/SP-"],
                                 creationflags=flags, close_fds=True)
            except OSError as e:
                self.state, self.error = "error", str(e)
                self.notify(i18n.t("update.installer_failed", error=e), "warn")
                return False
            self.log(f"installation de {self.latest} lancée, fermeture")
            threading.Thread(target=self._quit_soon, name="update-quit", daemon=True).start()
            return True
        # portable / targz : v1 = ouvrir le dossier et expliquer
        self.open_folder()
        self.notify(i18n.t("update.portable_hint", name=os.path.basename(self.path)), "info")
        return True

    def _quit_soon(self):
        time.sleep(0.6)
        try:
            self.request_quit()
        except Exception as e:  # noqa
            self.log(f"fermeture : {e}")

    def open_folder(self):
        os.makedirs(self.updates_dir, exist_ok=True)
        if self.open_folder_cb:
            try:
                self.open_folder_cb(self.updates_dir)
            except Exception as e:  # noqa
                self.log(f"dossier des mises à jour : {e}")

    def dismiss(self):
        if self.state in ("available", "ready", "error", "uptodate"):
            self._dismissed = self.latest
            self.state = "idle"

    def status(self):
        return {"state": self.state, "current": VERSION, "latest": self.latest, "notes": self.notes,
                "mandatory": self.mandatory, "kind": self.install_kind(), "progress": round(self.progress, 3),
                "done_mb": round(self.done_mb, 1), "size_mb": round(self.size_mb, 1), "path": self.path,
                "error": self.error, "checked_at": self.checked_at}


# ---------------------------------------------------------------- facade
class OnlineService:
    """Facade pour l'application : sante du serveur, compte, mise a jour, bibliotheque en ligne, salon."""

    def __init__(self, cfg, player, log=None, notify=None, logfile=None, open_url=None, open_folder=None,
                 request_quit=None, minimize=None, import_file=None, get_instrument_id=None,
                 get_player_name=None, ws_factory=None, on_update_available=None):
        self.cfg = cfg
        self.player = player
        self._ui_log = log or print
        self.notify = notify or (lambda msg, kind="info": None)
        self.logfile = logfile
        o = ensure_defaults(cfg)
        self.server_url = o["server_url"]
        self.account = Account(server_url=self.server_url)
        self.account.load()
        self.client = OnlineClient(self.server_url, token_getter=lambda: self.account.token, log=self.log)
        if open_url is None or open_folder is None:
            import platform_io
            open_url = open_url or platform_io.open_url
            open_folder = open_folder or platform_io.open_folder
        self.open_url = open_url
        self.open_folder = open_folder
        self.request_quit = request_quit or (lambda: None)
        self.minimize = minimize or (lambda: None)
        self.import_file = import_file or self._default_import
        self.get_instrument_id = get_instrument_id or (lambda: self.player.instrument.id)
        self.get_player_name = get_player_name or self._default_name
        self.login_flow = LoginFlow(self.client, self.account, self._open_url, log=self.log, notify=self.notify,
                                    on_done=self._on_login_done)
        self.updater = Updater(self.client, cfg, log=self.log, notify=self.notify, request_quit=self.request_quit,
                               open_folder=self._open_folder, on_available=on_update_available)
        self.updater.auto = bool(ensure_defaults(cfg).get("auto_update", True))
        from room import RoomSession
        self.room = RoomSession(self.client, player, cfg, self.account, log=self._ui_log, notify=self.notify,
                                logfile=os.path.join(os.path.dirname(logfile), "salon.log") if logfile else None,
                                save=lambda: core.save_config(cfg),
                                minimize=lambda: self.minimize(), import_file=lambda p, m: self.import_file(p, m),
                                get_instrument_id=lambda: self.get_instrument_id(),
                                get_player_name=lambda: self.get_player_name(), ws_factory=ws_factory)
        self._lock = threading.Lock()
        self._running = False
        self._closed = threading.Event()
        self._bg = None
        self._wake = threading.Event()
        self.server_ok = None       # None = pas encore verifie
        self.server_version = ""
        self.min_client = ""
        self.client_too_old = False
        self.offline_reason = ""
        self.checked_at = 0
        self.library = {"q": "", "sort": "recent", "tag": "", "instrument": "", "page": 1, "pages": 0, "total": 0,
                        "items": [], "loading": False, "error": "", "at": 0}
        # galerie de dessins (GET /api/drawings), depot en cours, grille recuperee pour l'activite Dessin
        self.gallery = {"sort": "recent", "page": 1, "pages": 0, "total": 0, "items": [], "loading": False,
                        "error": "", "at": 0}
        self.gallery_upload = {"state": "idle", "error": "", "item": None, "seq": 0}
        self.drawing_open = {"state": "idle", "id": None, "title": "", "error": "", "seq": 0}
        self._drawing_job = None          # grille recuperee, remise une fois a l'interface (take_drawing)
        self._import_seq = 0
        self.pending_q = {"page": 1, "pages": 0, "total": 0, "items": [], "loading": False, "error": "", "at": 0}
        self.reports_q = {"items": [], "loading": False, "error": "", "at": 0}
        self.jobs = {"downloads": {}, "uploads": {}, "imports": {}}

    # ---- journal
    def log(self, msg):
        self._ui_log(msg)
        if self.logfile:
            try:
                if os.path.exists(self.logfile) and os.path.getsize(self.logfile) > 512 * 1024:
                    os.remove(self.logfile)
                with open(self.logfile, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
            except Exception:  # noqa
                pass

    def set_callbacks(self, **kw):
        """Pose apres coup les callbacks de l'application : minimize, request_quit, import_file,
        get_instrument_id, get_player_name, open_url, open_folder."""
        for k, v in kw.items():
            if v is not None and k in ("minimize", "request_quit", "import_file", "get_instrument_id",
                                       "get_player_name", "open_url", "open_folder"):
                setattr(self, k, v)
        self.updater.request_quit = self.request_quit

    def _open_url(self, url):
        return self.open_url(url)

    def _open_folder(self, path):
        return self.open_folder(path)

    def _default_name(self):
        name = str(self.cfg.get("multi", {}).get("name") or "").strip()
        if not name and self.account.user:
            name = str(self.account.user.get("username") or "").strip()
        return (name or i18n.t("room.default_player_name"))[:24]

    def _default_import(self, path, meta):
        """Import par defaut d'un fichier telecharge : copie dans songs/ (suffixe « (2) » si le nom existe),
        titre, empreinte, identifiant en ligne, refresh_songs. Renvoie l'identifiant local (nom de fichier)."""
        import shutil
        p = self.player
        meta = meta or {}
        # Le nom vient d'un titre fourni par un autre joueur : core.safe_join l'assainit (ni separateur,
        # ni `..`, ni caractere reserve Windows, ni nom de peripherique) et verifie par realpath que le
        # chemin final reste bien dans songs/.
        title = core.clean_display_text(meta.get("title") or core.clean_title(path)) or core.clean_title(path)
        dst = core.safe_join(p.songs_folder, title)
        stem, ext = os.path.splitext(dst)
        n = 2
        while os.path.exists(dst):
            dst = f"{stem} ({n}){ext}"
            n += 1
        shutil.copy2(path, dst)
        sid = os.path.basename(dst)
        p.library.meta(sid)
        p.library.set_title(sid, title)
        p.library.set_online(sid, online_id=meta.get("online_id"), sha256=meta.get("sha256"))
        set_source(p.library, sid, meta.get("source_url"), meta.get("source_name"))
        p.library.sha256(sid, dst)
        p.refresh_songs()
        return sid

    # ---- cycle de vie
    def start_background(self):
        """Thread de fond : sante (3 s) -> /api/me si jeton -> verification de mise a jour -> empreintes.
        Au passage, updates/ est debarrasse des binaires d'autres versions (installee, plus ancienne, .part)."""
        if self._bg and self._bg.is_alive():
            return
        try:
            self.updater.cleanup()
        except Exception as e:  # noqa
            self.log(f"mises à jour : nettoyage impossible ({e})")
        self._running = True
        self._bg = threading.Thread(target=self._bg_run, name="online", daemon=True)
        self._bg.start()

    def _bg_run(self):
        first = True
        while self._running:
            self._check_server()
            if first:
                first = False
                if self.server_ok and self.cfg.get("online", {}).get("check_updates", True):
                    self.updater.check_async()
                self._backfill()
            # nouvelle verification : toutes les 60 s hors ligne, 5 min en ligne, ou sur demande
            self._wake.wait(60 if not self.server_ok else 300)
            self._wake.clear()

    def _check_server(self):
        try:
            h = self.client.get("/api/health", timeout=HEALTH_TIMEOUT, auth=False)
            with self._lock:
                self.server_ok = True
                self.server_version = str(h.get("version") or "")
                self.min_client = str(h.get("min_client") or "")
                self.client_too_old = bool(self.min_client) and parse_version(VERSION) < parse_version(self.min_client)
                self.offline_reason = ""
                self.checked_at = time.time()
        except OnlineError as e:
            with self._lock:
                was = self.server_ok
                self.server_ok = False
                self.offline_reason = str(e)
                self.checked_at = time.time()
            if was is not False:
                self.log(f"hors ligne : {e}")
            return
        if self.account.token:
            try:
                me = self.client.get("/api/me")
                me.pop("_status", None)
                self.account.set_user(me)
            except OnlineError as e:
                if e.code in (401, 403):
                    self.log("session Discord expirée : reconnecte-toi")
                    self.account.clear()
                else:
                    self.log(f"/api/me : {e}")

    def _backfill(self):
        """Empreintes sha256 des musiques locales (cache dans library.json)."""
        try:
            p = self.player
            for path in list(p.songs):
                if not self._running:
                    return
                p.library.sha256(os.path.basename(path), path)
        except Exception as e:  # noqa
            self.log(f"empreintes : {e}")

    def refresh(self):
        """Bouton Reessayer / actualiser : relance la verification du serveur."""
        self._wake.set()
        if not (self._bg and self._bg.is_alive()):
            self.start_background()

    def apply_config(self):
        """Apres modification des reglages en ligne : nouvelle URL -> nouveau client, compte recharge."""
        o = ensure_defaults(self.cfg)
        self.updater.auto = bool(o.get("auto_update", True))
        if o["server_url"] != self.server_url:
            self.server_url = o["server_url"]
            self.client.server_url = self.server_url
            self.account.load(self.server_url)
            self.login_flow.cancel()
            with self._lock:
                self.server_ok = None
                self.library.update({"items": [], "pages": 0, "total": 0, "page": 1})
        self.refresh()

    def close(self):
        self._running = False
        self._wake.set()
        try:
            self.login_flow.cancel()
        except Exception:  # noqa
            pass
        try:
            self.room.close()
        except Exception as e:  # noqa
            self.log(f"salon : {e}")

    # ---- compte
    def login(self, with_code=False):
        """Renvoie l'URL de connexion (aussi affichee dans l'interface). OnlineError si serveur injoignable.
        `with_code` : connexion par code a recopier (depuis un autre appareil) au lieu du retour automatique."""
        return self.login_flow.start(with_code=bool(with_code))

    def login_cancel(self):
        self.login_flow.cancel()

    def logout(self):
        tok = self.account.token
        self.account.clear()
        self.login_flow.cancel()
        if tok:
            def do():
                try:
                    self.client.request("POST", "/api/auth/logout", json_body={}, headers={"Authorization": f"Bearer {tok}"})
                except OnlineError as e:
                    self.log(f"déconnexion : {e}")
            self._spawn("logout", do)
        self.notify(i18n.t("online.logged_out"), "info")

    def delete_account(self):
        """Supprime le compte sur le serveur (DELETE /api/me, Bearer) puis efface account.json. Synchrone :
        renvoie {ok, songs_kept, songs_deleted} ; leve OnlineError (compte absent, serveur injoignable, refus).
        Les morceaux approuves restent en ligne, anonymises ; ceux en attente ou refuses sont effaces."""
        if not self.account.token:
            raise OnlineError(i18n.t("online.error.no_account"))
        r = self.client.request("DELETE", "/api/me")
        r.pop("_status", None)
        self.account.clear()
        self.login_flow.cancel()
        kept, gone = int(r.get("songs_kept") or 0), int(r.get("songs_deleted") or 0)
        self.log(f"compte supprimé : {kept} morceau(x) conservé(s) anonymement, {gone} effacé(s)")
        self.notify(i18n.t("online.account_deleted"), "info")
        return {"ok": bool(r.get("ok", True)), "songs_kept": kept, "songs_deleted": gone}

    def _on_login_done(self, ok):
        if ok:
            self._wake.set()

    # ---- bibliotheque en ligne
    def _spawn(self, name, fn, *args):
        t = threading.Thread(target=fn, args=args, name=f"online-{name}", daemon=True)
        t.start()
        return t

    def _local_of(self, item):
        lib = self.player.library
        return lib.find_by_sha(item.get("sha256")) or lib.find_by_online_id(item.get("id"))

    def _lang(self):
        try:
            return i18n.current_lang()
        except Exception:  # noqa
            return "fr"

    def _song_item(self, it, lang):
        """Element du catalogue pour l'interface : copie locale, tags filtres, adresse publique de la fiche."""
        out = dict(it, local=self._local_of(it))
        tags = it.get("tags") if isinstance(it.get("tags"), list) else []
        out["tags"] = [t for t in tags if t in SONG_TAGS][:MAX_TAGS]
        out["likes"] = int(it.get("likes") or 0) if str(it.get("likes") or "0").isdigit() else 0
        out["page_url"] = public_url("song", lang, self.server_url, id=it.get("id"), title=it.get("title"))
        return out

    def search(self, q="", page=1, sort="recent", tag="", instrument=""):
        q = str(q or "").strip()[:80]
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            page = 1
        sort = sort if sort in SONG_SORTS else "recent"
        tag = tag if tag in SONG_TAGS else ""
        instrument = str(instrument or "").strip().lower()
        instrument = instrument if INSTRUMENT_ID_RE.match(instrument) else ""
        with self._lock:
            self.library.update({"q": q, "sort": sort, "tag": tag, "instrument": instrument, "page": page,
                                 "loading": True, "error": ""})

        def do():
            try:
                # avec le jeton : le serveur ajoute liked_by_me a chaque morceau
                params = {"q": q, "page": page, "per_page": PER_PAGE, "sort": sort, "tag": tag,
                          "instrument": instrument}
                r = self._get_optional_auth("/api/songs", params)
                lang = self._lang()
                items = [self._song_item(it, lang) for it in (r.get("items") or []) if isinstance(it, dict)]
                with self._lock:
                    self.library.update({"items": items, "total": int(r.get("total") or len(items)),
                                         "pages": int(r.get("pages") or 1), "page": int(r.get("page") or page),
                                         "loading": False, "error": "", "at": time.time()})
            except OnlineError as e:
                with self._lock:
                    self.library.update({"loading": False, "error": str(e), "at": time.time()})
        self._spawn("search", do)

    def _get_optional_auth(self, path, params=None):
        """GET public avec le jeton s'il existe (champs liked_by_me) ; jeton refuse : on retente sans."""
        if not self.account.token:
            return self.client.get(path, params, auth=False)
        try:
            return self.client.get(path, params)
        except OnlineError as e:
            if e.code not in (401, 403):
                raise
            return self.client.get(path, params, auth=False)

    def download(self, online_id, import_cb=None):
        """Telecharge une musique de la bibliotheque en ligne (verifie le sha256) et l'importe."""
        oid = str(online_id)
        with self._lock:
            job = self.jobs["downloads"].get(oid)
            if job and job.get("state") in ("meta", "downloading", "importing"):
                return False
            self.jobs["downloads"][oid] = {"state": "meta", "progress": 0.0, "error": "", "song_id": None}
        self._spawn("download", self._download_run, oid, import_cb or self.import_file)
        return True

    def _set_job(self, kind, key, **kw):
        with self._lock:
            self.jobs[kind].setdefault(key, {}).update(kw)

    def _download_run(self, oid, import_cb):
        tmp = None
        try:
            item = next((it for it in self.library["items"] if str(it.get("id")) == oid), None)
            if not item or not item.get("sha256"):
                item = self.client.get(f"/api/songs/{oid}", auth=False)
            sha = str(item.get("sha256") or "").lower()
            # Empreinte obligatoire : sans elle le fichier recu ne serait verifie par rien, et le nom du
            # fichier temporaire ne serait plus derive d'une valeur sure.
            if not SHA256_RE.match(sha):
                raise OnlineError(i18n.t("online.error.no_sha"))
            local = self.player.library.find_by_sha(sha)
            if local and os.path.isfile(os.path.join(self.player.songs_folder, local)):
                self.player.library.set_online(local, online_id=item.get("id"))
                self._set_job("downloads", oid, state="done", progress=1.0, song_id=local)
                self.notify(i18n.t("online.already_local"), "info")
                return
            ddir = DOWNLOADS_DIR
            os.makedirs(ddir, exist_ok=True)
            tmp = os.path.join(ddir, f"{sha}.mid")   # nom derive du sha256, jamais d'un texte du serveur
            self._set_job("downloads", oid, state="downloading")

            def progress(done, total):
                if total:
                    self._set_job("downloads", oid, progress=min(1.0, done / total))
            got = self.client.download(f"/api/songs/{oid}/download", tmp, sha, progress,
                                       max_bytes=SONG_MAX_BYTES)
            if str(got).lower() != sha:             # ceinture et bretelles : download verifie deja
                raise OnlineError(i18n.t("online.error.corrupt"))
            self._set_job("downloads", oid, state="importing", progress=1.0)
            # Titre et artiste sont des textes d'un autre joueur, et le titre sert de nom de fichier a
            # l'import : nettoyes ici pour qu'aucun invisible ni bidi n'atteigne le disque.
            meta = {"title": core.safe_song_filename(core.clean_display_text(item.get("title")))[:-4],
                    "artist": core.clean_display_text(item.get("artist")),
                    "sha256": sha, "online_id": item.get("id", oid)}
            sid = import_cb(tmp, meta)
            if isinstance(sid, (list, tuple)):     # _import_files(paths, extra_meta) -> (added, skipped)
                sid = sid[0][0] if sid and sid[0] else None
            self._set_job("downloads", oid, state="done", song_id=sid)
            with self._lock:
                for it in self.library["items"]:
                    if str(it.get("id")) == oid:
                        it["local"] = sid
            self.notify(i18n.t("online.downloaded", title=meta["title"] or sid), "ok")
            self.log(f"téléchargé {oid} -> {sid}")
        except OnlineError as e:
            self._set_job("downloads", oid, state="error", error=str(e))
            self.notify(i18n.t("online.download_failed", error=e), "warn")
        except Exception as e:  # noqa
            self._set_job("downloads", oid, state="error", error=str(e))
            self.notify(i18n.t("online.import_failed", error=e), "warn")
            self.log(f"téléchargement {oid} : {e}")
        finally:
            if tmp:
                _unlink(tmp)

    def share(self, song_id, path, title, meta=None):
        """Depose une musique locale sur le serveur (file de moderation). meta : {tags, instrument, source_url,
        source_name, license} (clean_song_meta ; OnlineError si une valeur serait refusee)."""
        if not self.account.token:
            self.notify(i18n.t("online.share.login_first"), "warn")
            return False
        if not path or not os.path.isfile(path):
            self.notify(i18n.t("online.share.file_not_found"), "warn")
            return False
        meta = clean_song_meta(meta) if meta is not None else None
        with self._lock:
            job = self.jobs["uploads"].get(song_id)
            if job and job.get("state") == "uploading":
                return False
            self.jobs["uploads"][song_id] = {"state": "uploading", "progress": 0.0, "error": "", "online_id": None}
        self._spawn("share", self._share_run, song_id, path, title, meta)
        return True

    def _share_run(self, song_id, path, title, meta=None):
        try:
            sha = self.player.library.sha256(song_id, path)
            fields = {"title": title}
            if meta:
                fields.update({"tags": json.dumps(meta["tags"]), "instrument": meta["instrument"],
                               "source_url": meta["source_url"], "source_name": meta["source_name"],
                               "license": meta["license"]})
            r = self.client.upload("/api/songs", fields, "file", path)
            oid = r.get("id")
            self.player.library.set_online(song_id, online_id=oid, sha256=sha)
            self._set_job("uploads", song_id, state="done", progress=1.0, online_id=oid)
            self.notify(i18n.t("online.share.sent"), "ok")
            self.log(f"partagé {song_id} -> {oid}")
        except OnlineError as e:
            if e.code == 409 and e.payload.get("existing_id") is not None:
                oid = e.payload["existing_id"]
                self.player.library.set_online(song_id, online_id=oid)
                self._set_job("uploads", song_id, state="done", progress=1.0, online_id=oid)
                self.notify(i18n.t("online.share.already_online"), "info")
                return
            msg = error_text(e, "share")
            self._set_job("uploads", song_id, state="error", error=msg)
            self.notify(i18n.t("online.share.failed", error=msg), "warn")
        except Exception as e:  # noqa
            self._set_job("uploads", song_id, state="error", error=str(e))
            self.notify(i18n.t("online.share.failed", error=e), "warn")

    # ---- « j'aime »
    def like(self, kind, item_id, liked=True):
        """POST (aimer) / DELETE (retirer) /api/{songs|drawings}/{id}/like, synchrone. Met a jour le compteur de
        l'element deja affiche. Renvoie {ok, id, liked, likes} ; OnlineError (message traduit) sinon."""
        if kind not in ("song", "drawing"):
            raise ValueError(kind)
        if not self.account.token:
            raise OnlineError(i18n.t("online.like.login_first"), code=401)
        try:
            iid = int(item_id)
        except (TypeError, ValueError):
            raise OnlineError(i18n.t("online.error.bad_response")) from None
        path = f"/api/{'songs' if kind == 'song' else 'drawings'}/{iid}/like"
        try:
            r = self.client.request("POST" if liked else "DELETE", path)
        except OnlineError as e:
            if e.code == 401:
                raise OnlineError(i18n.t("online.like.login_first"), code=401) from None
            if e.payload.get("code") == "not_approved":
                raise OnlineError(i18n.t("online.like.not_approved"), code=409, payload=e.payload) from None
            raise
        now = bool(r.get("liked", bool(liked)))
        try:
            likes = max(0, int(r.get("likes") or 0))
        except (TypeError, ValueError):
            likes = 0
        store = self.library if kind == "song" else self.gallery
        with self._lock:
            for it in store["items"]:
                if str(it.get("id")) == str(iid):
                    it["liked_by_me"] = now
                    it["likes"] = likes
        return {"ok": True, "id": iid, "liked": now, "likes": likes}

    def like_song(self, song_id, liked=True):
        return self.like("song", song_id, liked)

    def like_drawing(self, drawing_id, liked=True):
        return self.like("drawing", drawing_id, liked)

    # ---- import par lien (BitMidi, lien .mid)
    def import_url(self, url, import_cb=None):
        """Le serveur va chercher le fichier (POST /api/import), le client le recupere une fois par son jeton
        (GET /api/import/{jeton}), verifie empreinte, taille et structure MIDI comme tout telechargement, puis
        l'importe avec un titre propre et la source memorisee. Travail dans un fil ; renvoie la cle du travail
        (status()["jobs"]["imports"][cle]). OnlineError tout de suite pour un lien refuse ou sans compte."""
        text = str(url or "").strip()
        if text and "://" not in text:
            text = "https://" + text
        if text.lower().startswith("http://"):
            raise OnlineError(i18n.t("online.import.error.https_required"), code=422,
                              payload={"code": "https_required"})
        checked = deeplink.validate_import_url(text)
        if not checked:
            raise OnlineError(i18n.t("online.import.error.bad_url"), code=422, payload={"code": "bad_url"})
        if not self.account.token:
            raise OnlineError(i18n.t("online.import.login_first"), code=401)
        norm, host = checked
        with self._lock:
            for key, job in self.jobs["imports"].items():
                if job.get("url") == norm and job.get("state") in ("fetching", "downloading", "importing"):
                    return key
            self._import_seq += 1
            key = str(self._import_seq)
            self.jobs["imports"][key] = {"state": "fetching", "url": norm, "host": host, "progress": 0.0,
                                         "error": "", "song_id": None, "title": ""}
        self._spawn("import", self._import_run, key, norm, import_cb or self.import_file)
        return key

    def _import_run(self, key, url, import_cb):
        tmp = None
        try:
            r = self.client.post("/api/import", {"url": url}, timeout=IMPORT_TIMEOUT)
            sha = str(r.get("sha256") or "").lower()
            token = str(r.get("download_token") or "")
            if not SHA256_RE.match(sha):
                raise OnlineError(i18n.t("online.error.no_sha"))
            if not IMPORT_TOKEN_RE.match(token):
                raise OnlineError(i18n.t("online.error.unexpected_response"))
            # nom du fichier distant : texte d'un site tiers, nettoye avant de devenir un titre et un nom de fichier
            stem = core.clean_title(core.clean_display_text(r.get("filename"), 200) or "")
            title = core.safe_song_filename(core.clean_display_text(stem) or "morceau")[:-4]
            src = str(r.get("source_url") or "")
            src = src if deeplink.validate_import_url(src) else url
            src_name = core.clean_display_text(r.get("source_name"), MAX_SOURCE_NAME_LEN)
            self._set_job("imports", key, title=title)
            lib = self.player.library
            local = lib.find_by_sha(sha)
            if local and os.path.isfile(os.path.join(self.player.songs_folder, local)):
                self._set_job("imports", key, state="done", progress=1.0, song_id=local)
                self.notify(i18n.t("online.already_local"), "info")
                return
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            tmp = os.path.join(DOWNLOADS_DIR, f"import-{sha}.mid")    # nom derive du sha256
            self._set_job("imports", key, state="downloading")

            def progress(done, total):
                if total:
                    self._set_job("imports", key, progress=min(1.0, done / total))
            got = self.client.download(f"/api/import/{token}", tmp, sha, progress, max_bytes=SONG_MAX_BYTES)
            if str(got).lower() != sha:
                raise OnlineError(i18n.t("online.error.corrupt"))
            core.midi_tracks(tmp)                   # structure MIDI et plafonds (MidiRefused)
            self._set_job("imports", key, state="importing", progress=1.0)
            meta = {"title": title, "sha256": sha, "source_url": src, "source_name": src_name}
            sid = import_cb(tmp, meta)
            if isinstance(sid, (list, tuple)):
                sid = sid[0][0] if sid and sid[0] else None
            self._set_job("imports", key, state="done", song_id=sid)
            self.notify(i18n.t("online.import.done", title=title or sid), "ok")
            self.log(f"importé depuis {url} -> {sid}")
        except OnlineError as e:
            msg = error_text(e, "import")
            self._set_job("imports", key, state="error", error=msg)
            self.notify(i18n.t("online.import.failed", error=msg), "warn")
        except Exception as e:  # noqa : MidiRefused, copie impossible
            self._set_job("imports", key, state="error", error=str(e))
            self.notify(i18n.t("online.import.failed", error=e), "warn")
            self.log(f"import par lien {url} : {e}")
        finally:
            if tmp:
                _unlink(tmp)

    # ---- galerie de dessins
    def _drawing_item(self, it, lang):
        out = dict(it)
        out["page_url"] = public_url("drawing", lang, self.server_url, id=it.get("id"))
        for k in ("thumb_url", "image_url"):
            if not str(out.get(k) or "").lower().startswith(("https://", "http://")):
                out[k] = None
        me = (self.account.user or {}).get("id") if self.account.token else None
        out["mine"] = me is not None and str(it.get("uploader_id")) == str(me)
        return out

    def drawings_list(self, page=1, sort="recent"):
        """GET /api/drawings (fil) -> status()["gallery"]."""
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            page = 1
        sort = sort if sort in DRAWING_SORTS else "recent"
        with self._lock:
            self.gallery.update({"sort": sort, "page": page, "loading": True, "error": ""})

        def do():
            try:
                r = self._get_optional_auth("/api/drawings", {"page": page, "per_page": GALLERY_PER_PAGE, "sort": sort})
                lang = self._lang()
                items = [self._drawing_item(it, lang) for it in (r.get("items") or []) if isinstance(it, dict)]
                with self._lock:
                    self.gallery.update({"items": items, "total": int(r.get("total") or len(items)),
                                         "pages": int(r.get("pages") or 1), "page": int(r.get("page") or page),
                                         "loading": False, "error": "", "at": time.time()})
            except OnlineError as e:
                with self._lock:
                    self.gallery.update({"loading": False, "error": str(e), "at": time.time()})
        self._spawn("gallery", do)

    def drawing_upload(self, png_bytes, title, cells=None):
        """Depot d'un dessin (PNG <= 512 Ko + grille facultative) dans la file de moderation. Fil ;
        status()["gallery_upload"] = {state: uploading|done|error, error, item, seq}. OnlineError tout de suite
        pour un fichier ou une grille invalide, ou sans compte."""
        if not self.account.token:
            raise OnlineError(i18n.t("online.gallery.login_first"), code=401)
        data = bytes(png_bytes or b"")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise OnlineError(i18n.t("online.gallery.error.invalid_png"), payload={"code": "invalid_png"})
        if len(data) > DRAWING_PNG_MAX_BYTES:
            raise OnlineError(i18n.t("online.gallery.error.too_large"), payload={"code": "too_large"})
        job = None
        if cells is not None:
            job = clean_cells_job(cells)
            if job is None:
                raise OnlineError(i18n.t("online.gallery.error.bad_cells"), payload={"code": "bad_cells"})
        title = core.clean_display_text(title, DRAWING_TITLE_MAX)
        with self._lock:
            if self.gallery_upload["state"] == "uploading":
                return False
            self.gallery_upload = {"state": "uploading", "error": "", "item": None,
                                   "seq": self.gallery_upload["seq"] + 1}
        self._spawn("drawing-upload", self._drawing_upload_run, data, title, job)
        return True

    def _drawing_upload_run(self, data, title, job):
        try:
            fields = {"title": title, "cells": json.dumps(job, separators=(",", ":")) if job else None}
            r = self.client.upload_bytes("/api/drawings", fields, "png", "dessin.png", data,
                                         content_type="image/png")
            r.pop("_status", None)
            item = self._drawing_item(r, self._lang())
            with self._lock:
                self.gallery_upload.update({"state": "done", "error": "", "item": item})
            self.notify(i18n.t("online.gallery.sent"), "ok")
            self.log(f"dessin déposé : {item.get('id')}")
        except OnlineError as e:
            msg = error_text(e, "gallery")
            with self._lock:
                self.gallery_upload.update({"state": "error", "error": msg})
            self.notify(i18n.t("online.gallery.upload_failed", error=msg), "warn")
        except Exception as e:  # noqa
            with self._lock:
                self.gallery_upload.update({"state": "error", "error": str(e)})
            self.notify(i18n.t("online.gallery.upload_failed", error=e), "warn")

    def drawing_cells(self, drawing_id):
        """GET /api/drawings/{id}/cells -> grille verifiee {format, w, h, cells} (synchrone)."""
        try:
            did = int(drawing_id)
        except (TypeError, ValueError):
            raise OnlineError(i18n.t("online.gallery.error.not_found"), code=404, payload={"code": "not_found"}) from None
        r = self._get_optional_auth(f"/api/drawings/{did}/cells")
        job = clean_cells_job(r)
        if job is None:
            raise OnlineError(i18n.t("online.gallery.error.bad_cells"), payload={"code": "bad_cells"})
        return job

    def open_drawing(self, drawing_id, on_loaded=None):
        """Recupere en fond la grille d'un dessin. status()["drawing_open"] passe a ready (la grille attend
        take_drawing(seq)) ; on_loaded(job, {id, title}) est appele avant. Renvoie le numero de la demande."""
        try:
            did = int(drawing_id)
        except (TypeError, ValueError):
            raise OnlineError(i18n.t("online.gallery.error.not_found"), code=404, payload={"code": "not_found"}) from None
        with self._lock:
            seq = self.drawing_open["seq"] + 1
            self.drawing_open = {"state": "loading", "id": did, "title": "", "error": "", "seq": seq}
            self._drawing_job = None

        def do():
            try:
                job = self.drawing_cells(did)
                with self._lock:
                    item = next((it for it in self.gallery["items"] if str(it.get("id")) == str(did)), None)
                if item is None:
                    try:
                        item = self._get_optional_auth(f"/api/drawings/{did}")
                    except OnlineError:
                        item = {}
                title = core.clean_display_text(item.get("title"), DRAWING_TITLE_MAX)
                if on_loaded:
                    on_loaded(job, {"id": did, "title": title})
                with self._lock:
                    if self.drawing_open["seq"] != seq:
                        return                          # une autre demande a pris la place
                    self._drawing_job = (seq, job, title)
                    self.drawing_open.update({"state": "ready", "title": title})
            except OnlineError as e:
                msg = error_text(e, "gallery")
                with self._lock:
                    if self.drawing_open["seq"] == seq:
                        self.drawing_open.update({"state": "error", "error": msg})
                self.notify(i18n.t("online.gallery.open_failed", error=msg), "warn")
        self._spawn("drawing-open", do)
        return seq

    def take_drawing(self, seq):
        """Grille recuperee par open_drawing, remise une seule fois : {id, title, job} ou None."""
        with self._lock:
            got = self._drawing_job
            try:
                same = got is not None and int(seq) == got[0]
            except (TypeError, ValueError):
                same = False
            if not same:
                return None
            self._drawing_job = None
            self.drawing_open["state"] = "taken"
            return {"id": self.drawing_open["id"], "title": got[2], "job": got[1]}

    def drawing_delete(self, drawing_id):
        """DELETE /api/drawings/{id} (auteur), synchrone ; retire le dessin de la liste affichee."""
        if not self.account.token:
            raise OnlineError(i18n.t("online.gallery.login_first"), code=401)
        did = int(drawing_id)
        try:
            self.client.request("DELETE", f"/api/drawings/{did}")
        except OnlineError as e:
            raise OnlineError(error_text(e, "gallery"), code=e.code, payload=e.payload) from None
        with self._lock:
            self.gallery["items"] = [it for it in self.gallery["items"] if str(it.get("id")) != str(did)]
            self.gallery["total"] = max(0, int(self.gallery.get("total") or 0) - 1)
        return True

    def drawing_report(self, drawing_id, reason):
        """POST /api/drawings/{id}/report {reason}, synchrone."""
        if not self.account.token:
            raise OnlineError(i18n.t("online.gallery.login_first"), code=401)
        did = int(drawing_id)
        reason = core.clean_display_text(reason, 500)
        if not reason:
            raise OnlineError(i18n.t("online.gallery.error.bad_reason"), code=422, payload={"code": "bad_reason"})
        try:
            self.client.post(f"/api/drawings/{did}/report", {"reason": reason})
        except OnlineError as e:
            raise OnlineError(error_text(e, "gallery"), code=e.code, payload=e.payload) from None
        return True

    # ---- salons
    def room_exists(self, code):
        """GET /api/rooms/{code}/exists -> {code, valid, exists, full} (synchrone, sans compte)."""
        norm = "".join(c for c in str(code or "").upper() if c in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")[:6]
        if len(norm) != 6:
            return {"code": norm, "valid": False, "exists": False, "full": False}
        r = self.client.get(f"/api/rooms/{norm}/exists", auth=False)
        return {"code": norm, "valid": True, "exists": bool(r.get("exists")), "full": bool(r.get("full"))}

    # ---- moderation (admin)
    def pending(self, page=1):
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            page = 1
        with self._lock:
            self.pending_q.update({"page": page, "loading": True, "error": ""})

        def do():
            try:
                r = self.client.get("/api/admin/songs", {"status": "pending", "page": page, "per_page": PER_PAGE})
                items = [it for it in (r.get("items") or []) if isinstance(it, dict)]
                with self._lock:
                    self.pending_q.update({"items": items, "total": int(r.get("total") or len(items)),
                                           "pages": int(r.get("pages") or 1), "loading": False, "at": time.time()})
            except OnlineError as e:
                with self._lock:
                    self.pending_q.update({"loading": False, "error": str(e), "at": time.time()})
        self._spawn("pending", do)

    def moderate(self, online_id, action, reason=""):
        if action not in ("approve", "reject"):
            return False

        def do():
            try:
                body = {"reason": str(reason or "")} if action == "reject" else {}
                self.client.post(f"/api/admin/songs/{online_id}/{action}", body)
                self.notify(i18n.t("online.moderation.approved" if action == "approve" else "online.moderation.rejected"), "ok")
                self.pending(self.pending_q.get("page", 1))
            except OnlineError as e:
                self.notify(i18n.t("online.moderation.failed", error=e), "warn")
        self._spawn("moderate", do)
        return True

    def resolve_report(self, report_id, action):
        """Clot un signalement : 'dismiss' (sans suite) ou 'remove_song' (retire le morceau)."""
        if action not in ("dismiss", "remove_song"):
            return False

        def do():
            try:
                self.client.post(f"/api/admin/reports/{report_id}/resolve", {"action": action})
                self.notify(i18n.t("online.report.dismissed" if action == "dismiss" else "online.report.removed"), "ok")
                self.reports()
            except OnlineError as e:
                self.notify(i18n.t("online.report.failed", error=e), "warn")
        self._spawn("resolve_report", do)
        return True

    def reports(self):
        with self._lock:
            self.reports_q.update({"loading": True, "error": ""})

        def do():
            try:
                r = self.client.get("/api/admin/reports", {"open": 1})
                items = r.get("items") if isinstance(r.get("items"), list) else []
                with self._lock:
                    self.reports_q.update({"items": items, "loading": False, "at": time.time()})
            except OnlineError as e:
                with self._lock:
                    self.reports_q.update({"loading": False, "error": str(e), "at": time.time()})
        self._spawn("reports", do)

    # ---- etat
    def status(self):
        """Copie de l'etat, sans aucune E/S (appele a chaque tick de l'interface)."""
        with self._lock:
            lib = dict(self.library)
            lib["items"] = [dict(it) for it in lib["items"]]
            pend = dict(self.pending_q)
            pend["items"] = list(pend["items"])
            reps = dict(self.reports_q)
            jobs = {k: {i: dict(j) for i, j in v.items()} for k, v in self.jobs.items()}
            gal = dict(self.gallery)
            gal["items"] = [dict(it) for it in gal["items"]]
            gal_up = dict(self.gallery_upload)
            dopen = dict(self.drawing_open)
            base = {"server_url": self.server_url, "server_ok": self.server_ok, "server_version": self.server_version,
                    "min_client": self.min_client, "client_too_old": self.client_too_old,
                    "offline_reason": self.offline_reason, "checked_at": self.checked_at}
        user = self.account.user
        room = self.room.status()
        base.update({
            "logged_in": self.account.logged_in(), "user": dict(user) if isinstance(user, dict) else None,
            "is_admin": bool(user and user.get("is_admin")),
            "login": self.login_flow.status(), "update": self.updater.status(),
            "library": lib, "pending": pend, "reports": reps, "jobs": jobs,
            "room": room, "clock": room.get("room", {}).get("clock", {}),
            "gallery": gal, "gallery_upload": gal_up, "drawing_open": dopen,
            # lien d'invitation public du salon en cours (page du site qui ouvre dodotopia://room/<CODE>)
            "room_url": public_url("room", self._lang(), self.server_url, code=(room.get("room") or {}).get("code")),
            "meta": {"tags": list(SONG_TAGS), "max_tags": MAX_TAGS, "licenses": list(LICENSES)},
        })
        return base
