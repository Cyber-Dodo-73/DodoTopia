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
POST /api/auth/start {verifier_hash} -> {login_id, url, expires_in}, POST /api/auth/poll {login_id, verifier}
-> {status: pending|ok|error, token?, user?, error?}, POST /api/auth/logout, GET /api/songs?q&page&per_page&sort
-> {items, total, page, pages}, GET /api/songs/{id}, GET /api/songs/{id}/download, POST /api/songs
(multipart file + title) -> 201 | 409 {existing_id}, GET /api/admin/songs?status=pending, POST
/api/admin/songs/{id}/approve | /reject {reason}, GET /api/admin/reports?open=1,
GET /api/releases/latest?current=&platform= -> {version, notes, mandatory, update_available, asset{url, sha256, size}}.
"""
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
LOGIN_POLL_S = 1.5
LOGIN_MAX_S = 600
PER_PAGE = 50
PLATFORM_NAME = "windows" if IS_WINDOWS else ("linux" if sys.platform.startswith("linux") else sys.platform)
# Chemins ecrits par ce module (lus a l'appel, jamais lies a l'import : les tests les redirigent vers un tmp)
ACCOUNT_PATH = os.path.join(DATA_DIR, "account.json")
UPDATES_DIR = os.path.join(DATA_DIR, "updates")
DOWNLOADS_DIR = os.path.join(DATA_DIR, "downloads")


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
                    msg = f"Requête invalide ({first.get('msg', 'validation')})"
                else:
                    msg = payload.get("message") or detail or payload.get("error") or ""
                if isinstance(msg, (list, dict)):
                    msg = json.dumps(msg, ensure_ascii=False)[:200]
            else:
                payload = {}
            if e.code == 429:
                retry = e.headers.get("Retry-After") if e.headers else None
                msg = (msg or "Trop de requêtes") + (f" (réessaie dans {retry} s)" if retry else "")
            raise OnlineError(str(msg) or f"Erreur serveur {e.code}", code=e.code, payload=payload) from None
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise OnlineError(f"Serveur injoignable ({reason})") from None
        except (OSError, ValueError) as e:      # timeout (socket.timeout est un OSError), SSL, URL invalide
            raise OnlineError(f"Serveur injoignable ({e})") from None

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
            raise OnlineError("Réponse illisible du serveur", code=status) from None
        if isinstance(out, dict):
            out.setdefault("_status", status)
        return out

    def get(self, path, params=None, timeout=API_TIMEOUT, auth=True):
        return self.request("GET", path, params=params, timeout=timeout, auth=auth)

    def post(self, path, json_body=None, params=None, timeout=API_TIMEOUT, auth=True):
        return self.request("POST", path, json_body=json_body if json_body is not None else {}, params=params,
                            timeout=timeout, auth=auth)

    def upload(self, path, fields, filefield, filepath, timeout=DOWNLOAD_TIMEOUT, content_type="audio/midi"):
        """POST multipart/form-data (ecrit a la main) : champs texte + un fichier."""
        boundary = "----DodoTopia" + uuid.uuid4().hex
        crlf = b"\r\n"
        parts = []
        for k, v in (fields or {}).items():
            if v is None:
                continue
            parts.append(b"--" + boundary.encode() + crlf)
            parts.append(f'Content-Disposition: form-data; name="{k}"'.encode() + crlf + crlf)
            parts.append(str(v).encode("utf-8") + crlf)
        with open(filepath, "rb") as f:
            content = f.read()
        # Nom de partie multipart : liste blanche ASCII. Un nom local contenant un guillemet ou un
        # retour a la ligne casserait sinon l'en-tete Content-Disposition envoye au serveur.
        fname = re.sub(r"[^A-Za-z0-9 ._-]+", "", core.clean_display_text(os.path.basename(filepath), 120))
        fname = fname.strip(" .") or "morceau.mid"
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
                    raise OnlineError(f"Fichier trop gros ({total // 1024} Ko)")
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if max_bytes and done > max_bytes:
                        raise OnlineError(f"Fichier trop gros (plus de {max_bytes // 1024} Ko)")
                    if on_progress:
                        on_progress(done, total)
        except OnlineError:
            _unlink(part)
            raise
        except OSError as e:
            _unlink(part)
            raise OnlineError(f"Téléchargement interrompu ({e})") from None
        sha = h.hexdigest()
        if expected_sha256 and sha.lower() != str(expected_sha256).lower():
            _unlink(part)
            raise OnlineError("Fichier corrompu (empreinte différente de celle annoncée)")
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
class LoginFlow:
    """Ticket + navigateur + interrogation : POST /api/auth/start, ouverture de l'URL, POST /api/auth/poll
    toutes les 1,5 s pendant 10 min au plus."""

    def __init__(self, client, account, open_url, log=None, notify=None, on_done=None):
        self.client = client
        self.account = account
        self.open_url = open_url
        self.log = log or (lambda m: None)
        self.notify = notify or (lambda msg, kind="info": None)
        self.on_done = on_done
        self.state = "idle"         # idle | waiting | ok | error
        self.url = None
        self.error = ""
        self.expires_at = 0.0
        self.poll_s = LOGIN_POLL_S
        self._cancel = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        """Demande un ticket, ouvre le navigateur, lance l'interrogation. Renvoie l'URL (a afficher aussi
        dans l'interface avec un bouton Copier) ; leve OnlineError si le serveur refuse."""
        with self._lock:
            if self.state == "waiting" and self._thread and self._thread.is_alive():
                return self.url
            verifier = secrets.token_urlsafe(32)
            vh = hashlib.sha256(verifier.encode("ascii")).hexdigest()
            try:
                r = self.client.post("/api/auth/start", {"verifier_hash": vh}, auth=False)
            except OnlineError as e:
                self.state, self.error = "error", str(e)
                raise
            login_id, url = r.get("login_id"), r.get("url")
            if not login_id or not url:
                self.state, self.error = "error", "Réponse inattendue du serveur"
                raise OnlineError(self.error)
            expires_in = float(r.get("expires_in") or LOGIN_MAX_S)
            self.expires_at = time.time() + min(expires_in, LOGIN_MAX_S)
            self.url, self.error, self.state = url, "", "waiting"
            self._cancel.clear()
            self._thread = threading.Thread(target=self._poll, args=(login_id, verifier), name="login", daemon=True)
            self._thread.start()
        try:
            if not self.open_url(url):
                self.notify("Ouvre le lien de connexion dans un navigateur (bouton Copier)", "warn")
        except Exception as e:  # noqa
            self.log(f"navigateur : {e}")
        return url

    def cancel(self):
        self._cancel.set()
        if self.state == "waiting":
            self.state = "idle"
        self.url = None

    def _poll(self, login_id, verifier):
        while not self._cancel.is_set():
            if time.time() > self.expires_at:
                self.state, self.error = "error", "Connexion expirée : recommence"
                break
            try:
                r = self.client.post("/api/auth/poll", {"login_id": login_id, "verifier": verifier}, auth=False)
            except OnlineError as e:
                if e.code in (404, 410):
                    self.state, self.error = "error", "Connexion expirée : recommence"
                    break
                if e.code == 403:
                    self.state, self.error = "error", "Ticket de connexion refusé"
                    break
                self.log(f"connexion : {e}")
                r = {"status": "pending"}
            st = r.get("status")
            if st == "ok" and r.get("token"):
                self.account.save(str(r["token"]), r.get("user"))
                self.state, self.url = "ok", None
                name = (r.get("user") or {}).get("username") or "Discord"
                self.notify(f"Connecté : {name}", "ok")
                self.log(f"connecté : {name}")
                if self.on_done:
                    try:
                        self.on_done(True)
                    except Exception:  # noqa
                        pass
                return
            if st == "error":
                self.state, self.error = "error", str(r.get("error") or "Connexion refusée")
                break
            if self._cancel.wait(self.poll_s):
                return
        if self.state == "error":
            self.notify(self.error, "warn")
            self.url = None
            if self.on_done:
                try:
                    self.on_done(False)
                except Exception:  # noqa
                    pass

    def status(self):
        left = max(0, int(self.expires_at - time.time())) if self.state == "waiting" else None
        return {"state": self.state, "url": self.url, "error": self.error, "expires_in": left}


# ---------------------------------------------------------------- mise a jour
class Updater:
    """Verification, telechargement (DATA_DIR/updates/, sha256 verifie) et installation d'une version."""

    def __init__(self, client, cfg, log=None, notify=None, request_quit=None, open_folder=None, updates_dir=None):
        self.client = client
        self.cfg = cfg
        self.log = log or (lambda m: None)
        self.notify = notify or (lambda msg, kind="info": None)
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
        self._notified = None   # version deja annoncee par un toast (une fois par session)
        self._dismissed = None
        self._lock = threading.Lock()
        self._thread = None

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
                    self.notify(f"DodoTopia {VERSION} est à jour", "ok")
                return
            self.state, self.error = "error", str(e)
            if manual:
                self.notify(f"Vérification impossible : {e}", "warn")
            return
        self.checked_at = time.time()
        latest = str(r.get("version") or "")
        asset = r.get("asset")
        if not asset and isinstance(r.get("assets"), dict):
            asset = r["assets"].get(self.platform_key())
        newer = bool(latest) and parse_version(latest) > parse_version(VERSION)
        if r.get("update_available") is False:
            newer = False
        if not newer:
            self.state = "uptodate"
            self.latest = latest or VERSION
            if manual:
                self.notify(f"DodoTopia {VERSION} est à jour", "ok")
            return
        self.latest = latest
        self.notes = str(r.get("notes") or "")
        self.mandatory = bool(r.get("mandatory"))
        self.asset = asset if isinstance(asset, dict) and asset.get("url") else None
        if self.path and os.path.isfile(self.path) and self.asset and self._file_ok(self.path, self.asset):
            self.state = "ready"
        else:
            self.state = "available"
        if latest == self._dismissed and not manual:
            self.state = "idle"
            return
        self.log(f"mise à jour disponible : {latest} (installée : {VERSION})")
        if self._notified != latest or manual:
            self._notified = latest
            self.notify(f"Version {latest} disponible", "info")
        # Mise a jour automatique : seulement au demarrage (pas sur une verification manuelle) et seulement
        # pour une installation par installeur, qui sait fermer l'app, s'installer en silence et la relancer.
        # En portable ou sous Linux il faudrait remplacer des fichiers en cours d'usage : on s'en tient au toast.
        if self.auto and not manual and self.install_kind() == "setup" and self.asset:
            self._auto_install(latest)

    def _auto_install(self, latest):
        """Telecharge puis lance l'installeur sans rien demander : on est au demarrage, rien n'est en cours."""
        self.notify(f"Mise à jour vers {latest} : téléchargement…", "info")
        if self.state != "ready":
            self.state = "downloading"
            self.progress = self.done_mb = 0.0
            self.size_mb = float((self.asset or {}).get("size") or 0) / 1e6
            self._download()
        if self.state != "ready":
            return
        self.log(f"installation automatique de {latest}")
        self.notify(f"Installation de {latest} : DodoTopia va redémarrer", "info")
        time.sleep(1.5)                  # laisser le toast s'afficher avant la fermeture
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
                    self.notify("Aucun fichier de mise à jour pour cette plateforme", "warn")
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
            self.notify(f"Téléchargement de la mise à jour impossible : {e}", "warn")

    # ---- installation
    def install(self):
        kind = self.install_kind()
        if kind == "source":
            self.notify("Installation désactivée depuis les sources (git pull)", "warn")
            return False
        if self.state == "available":
            return self.download_async()
        if self.state != "ready" or not self.path or not os.path.isfile(self.path):
            self.notify("La mise à jour n'est pas encore téléchargée", "warn")
            return False
        if kind == "setup":
            self.state = "installing"
            try:
                flags = 0
                if IS_WINDOWS:
                    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                subprocess.Popen([self.path, "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART", "/SP-"],
                                 creationflags=flags, close_fds=True)
            except OSError as e:
                self.state, self.error = "error", str(e)
                self.notify(f"Lancement de l'installeur impossible : {e}", "warn")
                return False
            self.log(f"installation de {self.latest} lancée, fermeture")
            threading.Thread(target=self._quit_soon, name="update-quit", daemon=True).start()
            return True
        # portable / targz : v1 = ouvrir le dossier et expliquer
        self.open_folder()
        self.notify(f"Ferme DodoTopia et décompresse {os.path.basename(self.path)} par-dessus son dossier", "info")
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
                 get_player_name=None, ws_factory=None):
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
                               open_folder=self._open_folder)
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
        self.library = {"q": "", "sort": "recent", "page": 1, "pages": 0, "total": 0, "items": [],
                        "loading": False, "error": "", "at": 0}
        self.pending_q = {"page": 1, "pages": 0, "total": 0, "items": [], "loading": False, "error": "", "at": 0}
        self.reports_q = {"items": [], "loading": False, "error": "", "at": 0}
        self.jobs = {"downloads": {}, "uploads": {}}

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
        return (name or "Joueur")[:24]

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
        p.library.sha256(sid, dst)
        p.refresh_songs()
        return sid

    # ---- cycle de vie
    def start_background(self):
        """Thread de fond : sante (3 s) -> /api/me si jeton -> verification de mise a jour -> empreintes."""
        if self._bg and self._bg.is_alive():
            return
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
    def login(self):
        """Renvoie l'URL de connexion (aussi affichee dans l'interface). OnlineError si serveur injoignable."""
        return self.login_flow.start()

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
        self.notify("Déconnecté", "info")

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

    def search(self, q="", page=1, sort="recent"):
        q = str(q or "").strip()[:80]
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            page = 1
        sort = sort if sort in ("recent", "popular", "title") else "recent"
        with self._lock:
            self.library.update({"q": q, "sort": sort, "page": page, "loading": True, "error": ""})

        def do():
            try:
                r = self.client.get("/api/songs", {"q": q, "page": page, "per_page": PER_PAGE, "sort": sort}, auth=False)
                items = [dict(it, local=self._local_of(it)) for it in (r.get("items") or []) if isinstance(it, dict)]
                with self._lock:
                    self.library.update({"items": items, "total": int(r.get("total") or len(items)),
                                         "pages": int(r.get("pages") or 1), "page": int(r.get("page") or page),
                                         "loading": False, "error": "", "at": time.time()})
            except OnlineError as e:
                with self._lock:
                    self.library.update({"loading": False, "error": str(e), "at": time.time()})
        self._spawn("search", do)

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
                raise OnlineError("Le serveur n'annonce pas d'empreinte pour ce morceau")
            local = self.player.library.find_by_sha(sha)
            if local and os.path.isfile(os.path.join(self.player.songs_folder, local)):
                self.player.library.set_online(local, online_id=item.get("id"))
                self._set_job("downloads", oid, state="done", progress=1.0, song_id=local)
                self.notify("Déjà dans ta bibliothèque", "info")
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
                raise OnlineError("Fichier corrompu (empreinte differente de celle annoncee)")
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
            self.notify(f"Téléchargé : {meta['title'] or sid}", "ok")
            self.log(f"téléchargé {oid} -> {sid}")
        except OnlineError as e:
            self._set_job("downloads", oid, state="error", error=str(e))
            self.notify(f"Téléchargement impossible : {e}", "warn")
        except Exception as e:  # noqa
            self._set_job("downloads", oid, state="error", error=str(e))
            self.notify(f"Import impossible : {e}", "warn")
            self.log(f"téléchargement {oid} : {e}")
        finally:
            if tmp:
                _unlink(tmp)

    def share(self, song_id, path, title):
        """Depose une musique locale sur le serveur (file de moderation)."""
        if not self.account.token:
            self.notify("Connecte-toi avec Discord pour partager", "warn")
            return False
        if not path or not os.path.isfile(path):
            self.notify("Fichier introuvable", "warn")
            return False
        with self._lock:
            job = self.jobs["uploads"].get(song_id)
            if job and job.get("state") == "uploading":
                return False
            self.jobs["uploads"][song_id] = {"state": "uploading", "progress": 0.0, "error": "", "online_id": None}
        self._spawn("share", self._share_run, song_id, path, title)
        return True

    def _share_run(self, song_id, path, title):
        try:
            sha = self.player.library.sha256(song_id, path)
            r = self.client.upload("/api/songs", {"title": title}, "file", path)
            oid = r.get("id")
            self.player.library.set_online(song_id, online_id=oid, sha256=sha)
            self._set_job("uploads", song_id, state="done", progress=1.0, online_id=oid)
            self.notify("Envoyé : en attente de validation par un administrateur", "ok")
            self.log(f"partagé {song_id} -> {oid}")
        except OnlineError as e:
            if e.code == 409 and e.payload.get("existing_id") is not None:
                oid = e.payload["existing_id"]
                self.player.library.set_online(song_id, online_id=oid)
                self._set_job("uploads", song_id, state="done", progress=1.0, online_id=oid)
                self.notify("Cette musique est déjà en ligne", "info")
                return
            self._set_job("uploads", song_id, state="error", error=str(e))
            self.notify(f"Partage impossible : {e}", "warn")
        except Exception as e:  # noqa
            self._set_job("uploads", song_id, state="error", error=str(e))
            self.notify(f"Partage impossible : {e}", "warn")

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
                self.notify("Approuvée" if action == "approve" else "Rejetée", "ok")
                self.pending(self.pending_q.get("page", 1))
            except OnlineError as e:
                self.notify(f"Modération impossible : {e}", "warn")
        self._spawn("moderate", do)
        return True

    def resolve_report(self, report_id, action):
        """Clot un signalement : 'dismiss' (sans suite) ou 'remove_song' (retire le morceau)."""
        if action not in ("dismiss", "remove_song"):
            return False

        def do():
            try:
                self.client.post(f"/api/admin/reports/{report_id}/resolve", {"action": action})
                self.notify("Signalement classé" if action == "dismiss" else "Morceau retiré", "ok")
                self.reports()
            except OnlineError as e:
                self.notify(f"Signalement : {e}", "warn")
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
        })
        return base
