# -*- coding: utf-8 -*-
"""Tests de online.py : versions, compte, client HTTP contre un http.server local, mise à jour, connexion."""
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import online
from online import Account, LoginFlow, OnlineClient, OnlineError, Updater, parse_version

FILE_BYTES = b"DodoTopia " * 5000
FILE_SHA = hashlib.sha256(FILE_BYTES).hexdigest()


def _midi_bytes():
    import io
    import mido
    mid = mido.MidiFile(type=0)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    for n in (60, 64, 67, 72):
        tr.append(mido.Message("note_on", note=n, velocity=90, time=0))
        tr.append(mido.Message("note_off", note=n, velocity=0, time=240))
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


MIDI_BYTES = _midi_bytes()
MIDI_SHA = hashlib.sha256(MIDI_BYTES).hexdigest()
NOT_MIDI = b"<html>pas un midi</html>" * 4
NOT_MIDI_SHA = hashlib.sha256(NOT_MIDI).hexdigest()
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40
CELLS = {"format": "1:1", "w": 2, "h": 2, "cells": [0, 5, -1, 12]}


def _err(handler, code, err, message="refus", **extra):
    return handler._json(code, {"detail": dict({"code": err, "message": message}, **extra)})


def _multipart(headers, raw):
    m = re.search(r"boundary=(.+)$", headers.get("Content-Type", ""))
    assert m, headers.get("Content-Type")
    boundary = m.group(1).encode()
    fields, files = {}, {}
    for part in raw.split(b"--" + boundary):
        part = part.strip()
        if not part or part == b"--":
            continue
        head, _, content = part.partition(b"\r\n\r\n")
        head = head.decode()
        name = re.search(r'name="([^"]+)"', head).group(1)
        fname = re.search(r'filename="([^"]+)"', head)
        content = content[:-2] if content.endswith(b"\r\n") else content
        if fname:
            ctype = re.search(r"Content-Type: (\S+)", head)
            files[name] = (fname.group(1), content, ctype.group(1) if ctype else None)
        else:
            fields[name] = content.decode()
    return fields, files


# ---------------------------------------------------------------- serveur HTTP de test
class State:
    uploads = []
    login_polls = 0
    login_error = None          # valeur de `error` renvoyee par /api/auth/poll ({status: error})
    latest = {"version": "9.9.9", "notes": "test", "mandatory": False,
              "asset": {"url": "/dl/9.9.9/file.bin", "sha256": FILE_SHA, "size": len(FILE_BYTES)}}
    manifest = None             # manifeste complet (signe) servi a la place de `latest` s'il est defini
    deleted = []                # en-tetes Authorization recus par DELETE /api/me
    stats = {"downloads_total": 12, "songs_approved": 3, "users": 5, "rooms_open": 1}
    song_queries = []           # (query, Authorization) de GET /api/songs
    likes = []                  # (methode, chemin, Authorization)
    import_tokens = {}          # jeton -> octets servis une seule fois
    drawing_uploads = []
    drawing_reports = []
    deleted_drawings = []


def make_manifest(signing_key=None, version="9.9.9", mandatory=False, published_at="2026-09-16T10:00:00Z",
                  platforms=None, tamper=None):
    """Manifeste au format du serveur (assets{platform}, signature, signed_payload). `signing_key` (nacl
    SigningKey) signe le payload canonique ; `tamper` modifie le manifeste APRES signature (dict de champs)."""
    platforms = platforms or [Updater.platform_key()]
    assets = {p: {"url": f"/dl/{version}/file.bin", "filename": "file.bin", "sha256": FILE_SHA,
                  "size": len(FILE_BYTES), "downloads": 0} for p in platforms}
    doc = {"version": version, "mandatory": bool(mandatory), "published_at": published_at,
           "assets": {p: {"sha256": a["sha256"], "size": a["size"], "filename": a["filename"]}
                      for p, a in sorted(assets.items())}}
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    sig = None
    if signing_key is not None:
        import base64
        sig = base64.b64encode(signing_key.sign(payload.encode()).signature).decode()
    m = {"version": version, "notes": "signé", "mandatory": bool(mandatory), "published_at": published_at,
         "assets": assets, "signature": sig, "signed_payload": payload}
    m.update(tamper or {})
    return m


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/api/health":
            return self._json(200, {"status": "ok", "version": "0.1", "min_client": "1.0.0"})
        if u.path == "/api/echo":
            return self._json(200, {"method": "GET", "path": u.path, "query": q,
                                    "auth": self.headers.get("Authorization"), "ua": self.headers.get("User-Agent")})
        if u.path == "/api/err":
            return self._json(403, {"message": "interdit"})
        if u.path == "/api/slow":
            time.sleep(2.0)
            return self._json(200, {})
        if u.path == "/dl/9.9.9/file.bin":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(FILE_BYTES)))
            self.end_headers()
            for i in range(0, len(FILE_BYTES), 4096):
                self.wfile.write(FILE_BYTES[i:i + 4096])
            return
        if u.path == "/api/releases/latest":
            m = State.manifest if State.manifest is not None else State.latest
            if q.get("current") == m.get("version"):
                return self._json(200, dict(m, update_available=False))
            asset = (m.get("assets") or {}).get(q.get("platform")) if State.manifest is not None else None
            return self._json(200, dict(m, update_available=True, asset=asset or m.get("asset")))
        if u.path == "/api/stats":
            return self._json(200, dict(State.stats))
        if u.path == "/api/me":
            return self._json(200, {"id": 1, "username": "dodo", "is_admin": True})
        if u.path == "/api/songs":
            State.song_queries.append((q, self.headers.get("Authorization")))
            items = [{"id": 11, "title": "Für Élise", "sha256": "a" * 64, "tags": ["piano", "inconnu"], "likes": 3,
                      "liked_by_me": True},
                     {"id": 12, "title": "Rock", "sha256": "b" * 64, "tags": [], "likes": 0}]
            return self._json(200, {"items": items, "total": 2, "page": 1, "pages": 1})
        m = re.match(r"^/api/import/([A-Za-z0-9_-]+)$", u.path)
        if m:
            data = State.import_tokens.pop(m.group(1), None)
            if data is None:
                return _err(self, 404, "not_found")
            self.send_response(200)
            self.send_header("Content-Type", "audio/midi")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == "/api/drawings":
            items = [{"id": 5, "title": "Chat", "w": 2, "h": 2, "uploader_id": 1, "likes": 2, "liked_by_me": False,
                      "thumb_url": "http://127.0.0.1/api/drawings/5/thumb.png", "image_url": "javascript:alert(1)",
                      "has_cells": True, "status": "approved"},
                     {"id": 6, "title": "Chien", "w": 2, "h": 2, "uploader_id": 9, "likes": 0, "has_cells": True,
                      "status": "approved"}]
            return self._json(200, {"items": items, "total": 2, "page": int(q.get("page", 1)), "pages": 1,
                                    "sort": q.get("sort")})
        m = re.match(r"^/api/drawings/(\d+)/cells$", u.path)
        if m:
            did = int(m.group(1))
            if did == 5:
                return self._json(200, dict(CELLS))
            if did == 6:
                return self._json(200, {"format": "1:1", "w": 2, "h": 2, "cells": [0, 1, 2]})
            return _err(self, 404, "no_cells")
        m = re.match(r"^/api/drawings/(\d+)$", u.path)
        if m:
            return self._json(200, {"id": int(m.group(1)), "title": "Dessin " + m.group(1)})
        m = re.match(r"^/api/rooms/([A-Z0-9]+)/exists$", u.path)
        if m:
            code = m.group(1)
            return self._json(200, {"code": code, "exists": code in ("K7P2QD", "FULL22"), "full": code == "FULL22"})
        return self._json(404, {"message": "inconnu"})

    def _like(self, method, path):
        auth = self.headers.get("Authorization")
        if not auth:
            return _err(self, 401, "unauthorized")
        State.likes.append((method, path, auth))
        oid = int(path.split("/")[3])
        if oid == 2:
            return _err(self, 409, "not_approved")
        return self._json(200, {"ok": True, "id": oid, "liked": method == "POST", "likes": 4 if method == "POST" else 3})

    def do_DELETE(self):
        u = urllib.parse.urlsplit(self.path)
        if re.match(r"^/api/(songs|drawings)/\d+/like$", u.path):
            return self._like("DELETE", u.path)
        m = re.match(r"^/api/drawings/(\d+)$", u.path)
        if m:
            if int(m.group(1)) != 5:
                return _err(self, 403, "forbidden")
            State.deleted_drawings.append(int(m.group(1)))
            return self._json(200, {"ok": True})
        if u.path == "/api/me":
            auth = self.headers.get("Authorization")
            if not auth:
                return self._json(401, {"detail": {"code": "unauthorized", "message": "Connexion Discord requise."}})
            State.deleted.append(auth)
            return self._json(200, {"ok": True, "songs_kept": 2, "songs_deleted": 1})
        return self._json(404, {"message": "inconnu"})

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        raw = self._body()
        if u.path == "/api/echo":
            return self._json(200, {"method": "POST", "json": json.loads(raw.decode()),
                                    "ctype": self.headers.get("Content-Type")})
        if re.match(r"^/api/(songs|drawings)/\d+/like$", u.path):
            return self._like("POST", u.path)
        if u.path == "/api/import":
            if not self.headers.get("Authorization"):
                return _err(self, 401, "unauthorized")
            url = json.loads(raw.decode())["url"]
            if "private" in url:
                return _err(self, 403, "private_address", "Adresse non publique refusée.")
            if "lent" in url:
                return _err(self, 504, "timeout")
            data = NOT_MIDI if "pasmidi" in url else MIDI_BYTES
            token = "T" + hashlib.sha256(url.encode()).hexdigest()[:30]
            State.import_tokens[token] = data
            return self._json(200, {"ok": True, "filename": "Gymnopedie_No1-Satie.mid", "size": len(data),
                                    "sha256": hashlib.sha256(data).hexdigest(), "source_url": url,
                                    "source_name": "BitMidi", "source_author": None, "download_token": token,
                                    "download_url": "https://ailleurs.example/piege", "expires_in": 600})
        if u.path == "/api/drawings":
            fields, files = _multipart(self.headers, raw)
            State.drawing_uploads.append((fields, files, self.headers.get("Authorization")))
            if fields.get("title") == "doublon":
                return _err(self, 409, "duplicate", existing_id=3)
            return self._json(201, {"id": 8, "title": fields.get("title"), "w": 2, "h": 2, "status": "pending",
                                    "uploader_id": 1, "thumb_url": "http://127.0.0.1/api/drawings/8/thumb.png"})
        m = re.match(r"^/api/drawings/(\d+)/report$", u.path)
        if m:
            State.drawing_reports.append((int(m.group(1)), json.loads(raw.decode())))
            return self._json(201, {"id": 1, "drawing_id": int(m.group(1))})
        if u.path == "/api/songs":
            fields, files = _multipart(self.headers, raw)
            files = {k: v[:2] for k, v in files.items()}
            State.uploads.append((fields, files))
            if fields.get("title") == "doublon":
                return self._json(409, {"message": "déjà présent", "existing_id": 42})
            return self._json(201, {"id": 7, "title": fields.get("title"), "filename": files["file"][0],
                                    "size": len(files["file"][1]), "sha256": hashlib.sha256(files["file"][1]).hexdigest()})
        if u.path == "/api/auth/start":
            body = json.loads(raw.decode())
            State.verifier_hash = body["verifier_hash"]
            return self._json(200, {"login_id": "L1", "url": "http://example/auth?login_id=L1", "expires_in": 600,
                                    "user_code": "K7PQ2"})
        if u.path == "/api/auth/poll":
            body = json.loads(raw.decode())
            State.login_polls += 1
            if hashlib.sha256(body["verifier"].encode()).hexdigest() != State.verifier_hash:
                return self._json(403, {"message": "verifier"})
            if State.login_error:
                return self._json(200, {"status": "error", "error": State.login_error})
            if State.login_polls < 3:
                return self._json(200, {"status": "pending"})
            return self._json(200, {"status": "ok", "token": "TOK123", "user": {"id": 1, "username": "dodo"}})
        return self._json(404, {"message": "inconnu"})


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


# ---------------------------------------------------------------- versions
def test_parse_version():
    assert parse_version("1.7.0") == (1, 7, 0)
    assert parse_version("1.10.0") > parse_version("1.9.0")
    assert parse_version("1.7.0-beta") == (1, 7, 0)
    assert parse_version("") == ()
    assert parse_version("v2") == ()
    assert online.normalize_url("dodotopia.fr/") == "https://dodotopia.fr"
    assert online.normalize_url("http://localhost:8000") == "http://localhost:8000"


def test_ensure_defaults():
    cfg = {"online": {"server_url": "monserveur.fr/"}}
    o = online.ensure_defaults(cfg)
    assert o["server_url"] == "https://monserveur.fr" and o["check_updates"] is True
    cfg2 = {}
    online.ensure_defaults(cfg2)
    assert cfg2["online"]["server_url"] == online.DEFAULT_SERVER_URL


# ---------------------------------------------------------------- compte
def test_account_save_load_clear(tmp_path):
    path = str(tmp_path / "account.json")
    a = Account(path, "https://srv.example")
    assert not a.load() and not a.logged_in()
    a.save("tok", {"id": 1, "username": "dodo"})
    assert a.logged_in() and os.path.isfile(path)
    b = Account(path, "https://srv.example/")
    assert b.load() and b.token == "tok" and b.user["username"] == "dodo"
    c = Account(path, "https://autre.example")        # URL differente : jeton invalide
    assert not c.load() and c.token is None
    b.clear()
    assert not os.path.exists(path) and not b.logged_in()
    if not sys.platform.startswith("win"):
        a.save("tok", None)
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"


# ---------------------------------------------------------------- client HTTP
def test_request_get_post(server):
    c = OnlineClient(server, token_getter=lambda: "abc")
    r = c.get("/api/echo", {"q": "salut toi", "page": 2, "vide": ""})
    assert r["query"] == {"q": "salut toi", "page": "2"}
    assert r["auth"] == "Bearer abc"
    assert r["ua"].startswith("DodoTopia/")
    r = c.post("/api/echo", {"a": 1})
    assert r["json"] == {"a": 1} and r["ctype"] == "application/json"
    r = c.get("/api/echo", auth=False)
    assert r["auth"] is None
    assert c.ws_url() == server.replace("http://", "ws://") + "/ws"


def test_request_errors(server):
    c = OnlineClient(server)
    with pytest.raises(OnlineError) as e:
        c.get("/api/err")
    assert e.value.code == 403 and "interdit" in str(e.value)
    with pytest.raises(OnlineError) as e:
        c.get("/api/slow", timeout=0.3)
    assert "injoignable" in str(e.value)
    with pytest.raises(OnlineError):
        OnlineClient("http://127.0.0.1:1").get("/api/health", timeout=1)


def test_download_ok_and_bad_sha(server, tmp_path):
    c = OnlineClient(server)
    dest = str(tmp_path / "f.bin")
    seen = []
    sha = c.download("/dl/9.9.9/file.bin", dest, FILE_SHA, lambda d, t: seen.append((d, t)))
    assert sha == FILE_SHA and os.path.isfile(dest) and not os.path.exists(dest + ".part")
    assert seen and seen[-1][0] == len(FILE_BYTES) and seen[-1][1] == len(FILE_BYTES)
    with open(dest, "rb") as f:
        assert f.read() == FILE_BYTES
    dest2 = str(tmp_path / "g.bin")
    with pytest.raises(OnlineError) as e:
        c.download(server + "/dl/9.9.9/file.bin", dest2, "0" * 64)
    assert "corrompu" in str(e.value)
    assert not os.path.exists(dest2) and not os.path.exists(dest2 + ".part")


def test_upload_multipart(server, tmp_path):
    c = OnlineClient(server, token_getter=lambda: "abc")
    path = tmp_path / "ma musique.mid"
    data = b"MThd" + bytes(range(256)) * 10
    path.write_bytes(data)
    State.uploads.clear()
    r = c.upload("/api/songs", {"title": "Ma musique", "artist": None}, "file", str(path))
    assert r["_status"] == 201 and r["id"] == 7 and r["title"] == "Ma musique"
    assert r["filename"] == "ma musique.mid" and r["size"] == len(data)
    assert r["sha256"] == hashlib.sha256(data).hexdigest()
    fields, files = State.uploads[-1]
    assert fields == {"title": "Ma musique"} and files["file"][1] == data
    with pytest.raises(OnlineError) as e:
        c.upload("/api/songs", {"title": "doublon"}, "file", str(path))
    assert e.value.code == 409 and e.value.payload["existing_id"] == 42


# ---------------------------------------------------------------- mise a jour
def test_install_kind(monkeypatch, tmp_path):
    monkeypatch.setattr(online, "FROZEN", False)
    assert Updater.install_kind() == "source"
    monkeypatch.setattr(online, "FROZEN", True)
    monkeypatch.setattr(online, "IS_WINDOWS", True)
    exe = tmp_path / "DodoTopia.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))
    assert Updater.install_kind() == "portable" and Updater.platform_key() == "windows-portable"
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert Updater.install_kind() == "setup" and Updater.platform_key() == "windows-setup"
    monkeypatch.setattr(online, "IS_WINDOWS", False)
    assert Updater.install_kind() == "targz" and Updater.platform_key() == "linux-x64"


def test_mise_a_jour_silencieuse_au_demarrage(server, tmp_path, monkeypatch):
    """Comme Discord : au démarrage, la version se télécharge et s'installe sans fenêtre d'installeur
    (/VERYSILENT) et sans toast « Installer » à cliquer ; l'installeur relance l'application."""
    lances, annonces, quits = [], [], []
    monkeypatch.setattr(Updater, "install_kind", staticmethod(lambda: "setup"))
    monkeypatch.setattr(Updater, "platform_key", staticmethod(lambda: "windows-setup"))
    monkeypatch.setattr(online.subprocess, "Popen", lambda args, **kw: lances.append(list(args)))
    u = Updater(OnlineClient(server), {}, notify=lambda m, k="info": None, request_quit=lambda: quits.append(1),
                on_available=lambda msg, v: annonces.append(v), updates_dir=str(tmp_path / "updates"))
    u.auto = True
    u.install_pause_s = 0
    u._check(manual=False)
    assert u.state == "installing" and len(lances) == 1
    args = lances[0]
    assert args[0] == u.path and os.path.isfile(u.path)
    assert "/VERYSILENT" in args and "/SUPPRESSMSGBOXES" in args and "/CLOSEAPPLICATIONS" in args
    assert "/SILENT" not in args
    assert annonces == [], "pas de toast « Installer » quand tout se fait seul"
    # vérification manuelle : on annonce, on n'installe pas dans le dos de l'utilisateur
    u2 = Updater(OnlineClient(server), {}, notify=lambda m, k="info": None,
                 on_available=lambda msg, v: annonces.append(v), updates_dir=str(tmp_path / "updates2"))
    u2.auto = True
    u2._check(manual=True)
    assert annonces == ["9.9.9"] and len(lances) == 1


def test_updater_check_and_download(server, tmp_path, monkeypatch):
    notes = []
    c = OnlineClient(server)
    u = Updater(c, {}, notify=lambda m, k="info": notes.append(m), updates_dir=str(tmp_path / "updates"))
    assert u.check_async()
    u._thread.join(5)
    assert u.state == "available" and u.latest == "9.9.9" and u.asset["sha256"] == FILE_SHA
    assert any("9.9.9" in n for n in notes)
    assert u.download_async()
    u._thread.join(10)
    assert u.state == "ready" and os.path.isfile(u.path) and u.progress == 1.0
    st = u.status()
    assert st["kind"] == "source" and st["current"] == online.VERSION
    assert u.install() is False          # depuis les sources : desactive
    u.dismiss()
    assert u.state == "idle"
    # a jour
    monkeypatch.setattr(online, "VERSION", "9.9.9")
    u2 = Updater(c, {}, notify=lambda m, k="info": notes.append(m))
    u2.check_async(manual=True)
    u2._thread.join(5)
    assert u2.state == "uptodate"


# ---------------------------------------------------------------- connexion Discord
def test_login_flow(server, tmp_path):
    opened = []
    notes = []
    acc = Account(str(tmp_path / "account.json"), server)
    c = OnlineClient(server, token_getter=lambda: acc.token)
    flow = LoginFlow(c, acc, lambda url: opened.append(url) or True, notify=lambda m, k="info": notes.append(m))
    flow.poll_s = 0.05
    State.login_polls = 0
    url = flow.start()
    assert url.startswith("http://example/auth") and opened == [url]
    assert flow.status()["state"] == "waiting" and flow.status()["expires_in"] > 0
    # code anti-hameconnage transmis a l'interface tant qu'on attend
    assert flow.status()["user_code"] == "K7PQ2"
    # rappeler start() pendant l'attente rouvre le navigateur sur le meme ticket (pas de nouveau code)
    assert flow.start() == url and opened == [url, url] and flow.status()["user_code"] == "K7PQ2"
    flow._thread.join(5)
    assert flow.status()["state"] == "ok" and acc.token == "TOK123" and acc.user["username"] == "dodo"
    assert flow.status()["user_code"] is None
    assert State.login_polls == 3
    assert c.get("/api/me")["username"] == "dodo"
    # annulation
    State.login_polls = -100
    flow2 = LoginFlow(c, acc, lambda url: True)
    flow2.poll_s = 0.05
    flow2.start()
    flow2.cancel()
    flow2._thread.join(2)
    assert flow2.status()["state"] == "idle"


def test_login_flow_too_many_bad_codes(server, tmp_path):
    """/api/auth/poll -> {status: error, error: "code"} : message clair, code efface, flux termine."""
    notes = []
    acc = Account(str(tmp_path / "account.json"), server)
    c = OnlineClient(server, token_getter=lambda: acc.token)
    flow = LoginFlow(c, acc, lambda url: True, notify=lambda m, k="info": notes.append((m, k)))
    flow.poll_s = 0.05
    State.login_polls = 0
    State.login_error = "code"
    try:
        flow.start()
        flow._thread.join(5)
    finally:
        State.login_error = None
    st = flow.status()
    assert st["state"] == "error" and st["error"] == "Trop de codes erronés : relance la connexion."
    assert st["user_code"] is None and st["url"] is None and not acc.logged_in()
    assert ("Trop de codes erronés : relance la connexion.", "warn") in notes
    assert online.LOGIN_POLL_S >= 1.5


# ---------------------------------------------------------------- manifeste signe
@pytest.fixture
def signing():
    import base64
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    return sk, pub


@pytest.fixture
def manifest_server():
    """Le faux serveur sert State.manifest pendant le test, puis revient au manifeste historique."""
    yield
    State.manifest = None


def _check(server, notes=None, log=None, auto=False, updates_dir=None):
    sink = notes if notes is not None else []
    u = Updater(OnlineClient(server), {}, log=log, notify=lambda m, k="info": sink.append((m, k)),
                updates_dir=updates_dir)
    u.auto = auto
    assert u.check_async()
    u._thread.join(5)
    return u


def test_manifest_signed_accepted(server, monkeypatch, signing, manifest_server):
    sk, pub = signing
    monkeypatch.setattr(online, "RELEASE_SIGNING_PUBLIC_KEY", pub)
    State.manifest = make_manifest(sk)
    ok, why = online.verify_release_manifest(State.manifest, Updater.platform_key())
    assert ok and why == ""
    notes, logs = [], []
    u = _check(server, notes, logs.append)
    assert u.state == "available" and u.latest == "9.9.9" and u.asset["sha256"] == FILE_SHA
    assert u.asset["filename"] == "file.bin" and not u.error
    assert any("9.9.9" in m for m, _ in notes) and not any("refusée" in m for m, _ in notes)


@pytest.mark.parametrize("case", ["bad_signature", "no_signature", "tampered_version", "tampered_sha",
                                  "tampered_mandatory", "other_key", "no_payload"])
def test_manifest_refused(server, monkeypatch, signing, manifest_server, case):
    import base64
    from nacl.signing import SigningKey
    sk, pub = signing
    monkeypatch.setattr(online, "RELEASE_SIGNING_PUBLIC_KEY", pub)
    pk = Updater.platform_key()
    if case == "bad_signature":
        m = make_manifest(sk, tamper={"signature": base64.b64encode(bytes([1]) * 64).decode()})
    elif case == "no_signature":
        m = make_manifest(sk, tamper={"signature": None})
    elif case == "tampered_version":
        m = make_manifest(sk, tamper={"version": "9.9.10"})
    elif case == "tampered_sha":
        m = make_manifest(sk)
        m["assets"][pk]["sha256"] = "0" * 64
    elif case == "tampered_mandatory":
        m = make_manifest(sk, tamper={"mandatory": True})
    elif case == "other_key":
        m = make_manifest(SigningKey.generate())
    else:
        m = make_manifest(sk, tamper={"signed_payload": None})
    ok, why = online.verify_release_manifest(m, pk)
    assert not ok and why
    State.manifest = m
    notes, logs = [], []
    u = _check(server, notes, logs.append)
    assert u.state == "error" and u.error == "Mise à jour refusée : signature invalide"
    assert u.latest is None and u.asset is None and u.mandatory is False
    assert ("Mise à jour refusée : signature invalide", "danger") in notes
    assert any("refusée" in line for line in logs)
    assert u.download_async() is False           # rien a telecharger


def test_manifest_accepted_without_key(server, monkeypatch, signing, manifest_server):
    """Cle publique vide : manifeste non signe accepte, mais journalise."""
    monkeypatch.setattr(online, "RELEASE_SIGNING_PUBLIC_KEY", "")
    State.manifest = make_manifest(None)
    logs = []
    u = _check(server, [], logs.append)
    assert u.state == "available" and u.latest == "9.9.9" and u.asset["sha256"] == FILE_SHA
    assert any("non signé accepté" in line and "clé publique non configurée" in line for line in logs)
    # module PyNaCl absent : refus si une cle est configuree, comportement actuel sinon
    import builtins
    real_import = builtins.__import__

    def no_nacl(name, *a, **k):
        if name.startswith("nacl"):
            raise ImportError("no nacl")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_nacl)
    assert online.verify_release_manifest(State.manifest, Updater.platform_key(), public_key="")[0]
    ok, why = online.verify_release_manifest(State.manifest, Updater.platform_key(), public_key=signing[1])
    assert not ok and "PyNaCl" in why


def test_mandatory_forces_install_in_setup_mode(server, monkeypatch, signing, manifest_server, tmp_path):
    sk, pub = signing
    monkeypatch.setattr(online, "RELEASE_SIGNING_PUBLIC_KEY", pub)
    State.manifest = make_manifest(sk, mandatory=True, platforms=["windows-setup", "linux-x64"])
    monkeypatch.setattr(Updater, "install_kind", staticmethod(lambda: "setup"))
    installed = []
    monkeypatch.setattr(Updater, "install", lambda self: installed.append(self.path) or True)
    notes = []
    u = Updater(OnlineClient(server), {}, notify=lambda m, k="info": notes.append((m, k)),
                updates_dir=str(tmp_path / "updates"))
    u.auto = False                      # mise a jour automatique desactivee : l'obligatoire passe quand meme
    u.install_pause_s = 0
    assert u.check_async()
    u._thread.join(15)
    assert u.mandatory and u.state == "ready" and os.path.isfile(u.path)
    assert installed == [u.path]
    assert any("obligatoire" in m for m, _ in notes)
    # pas d'installation forcee en portable (ni sur une verification manuelle)
    monkeypatch.setattr(Updater, "install_kind", staticmethod(lambda: "portable"))
    installed.clear()
    u2 = Updater(OnlineClient(server), {}, updates_dir=str(tmp_path / "updates"))
    u2.check_async()
    u2._thread.join(5)
    assert u2.state == "available" and u2.mandatory and installed == []
    monkeypatch.setattr(Updater, "install_kind", staticmethod(lambda: "setup"))
    u3 = Updater(OnlineClient(server), {}, updates_dir=str(tmp_path / "updates"))
    u3.check_async(manual=True)
    u3._thread.join(5)
    assert u3.state == "available" and u3.mandatory and installed == []


def test_updates_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(online, "VERSION", "1.9.0")
    d = tmp_path / "updates"
    d.mkdir()
    for name in ("DodoTopia-1.8.0-Setup.exe", "DodoTopia-1.9.0-Setup.exe", "DodoTopia-2.0.0-Setup.exe",
                 "DodoTopia-2.1.0-Setup.exe", "DodoTopia-2.1.0-Setup.exe.part", "notes.txt"):
        (d / name).write_bytes(b"x")
    u = Updater(OnlineClient("http://127.0.0.1:1"), {}, updates_dir=str(d))
    gone = set(u.cleanup())
    assert gone == {"DodoTopia-1.8.0-Setup.exe", "DodoTopia-1.9.0-Setup.exe", "DodoTopia-2.1.0-Setup.exe.part",
                    "notes.txt"}
    assert set(os.listdir(d)) == {"DodoTopia-2.0.0-Setup.exe", "DodoTopia-2.1.0-Setup.exe"}
    assert u.cleanup(keep="2.1.0") == ["DodoTopia-2.0.0-Setup.exe"]
    assert os.listdir(d) == ["DodoTopia-2.1.0-Setup.exe"]
    assert u.cleanup() == []            # deja propre : silencieux
    assert Updater(OnlineClient("http://127.0.0.1:1"), {}, updates_dir=str(tmp_path / "nope")).cleanup() == []


# ---------------------------------------------------------------- facade : compte, stats
def _service(server, tmp_path, **kw):
    from helpers import FakePlayer
    player = FakePlayer(str(tmp_path / "player"))
    cfg = {"online": {"server_url": server, "check_updates": False}, "multi": {}}
    return online.OnlineService(cfg, player, log=lambda m: None, open_url=lambda u: True,
                                open_folder=lambda p: None, **kw)


def test_delete_account(server, tmp_path):
    notes = []
    svc = _service(server, tmp_path, notify=lambda m, k="info": notes.append(m))
    try:
        with pytest.raises(OnlineError):
            svc.delete_account()                      # pas connecte
        svc.account.save("TOK123", {"id": 1, "username": "dodo"})
        assert os.path.isfile(svc.account.path)
        State.deleted.clear()
        r = svc.delete_account()
        assert r == {"ok": True, "songs_kept": 2, "songs_deleted": 1}
        assert State.deleted == ["Bearer TOK123"]
        assert not svc.account.logged_in() and not os.path.exists(svc.account.path)
        assert svc.status()["logged_in"] is False and svc.status()["user"] is None
        assert "Compte supprimé" in notes
    finally:
        svc.close()


def test_stats(server):
    c = OnlineClient(server)
    assert c.stats() == State.stats
    with pytest.raises(OnlineError):
        OnlineClient("http://127.0.0.1:1").stats(timeout=1)


def test_service_status_exposes_user_code(server, tmp_path):
    svc = _service(server, tmp_path)
    try:
        svc.login_flow.poll_s = 0.05
        State.login_polls = -10 ** 6
        svc.login()
        st = svc.status()["login"]
        assert st["state"] == "waiting" and st["user_code"] == "K7PQ2" and st["url"].startswith("http://example/")
        svc.login_cancel()
        assert svc.status()["login"]["user_code"] is None
    finally:
        State.login_polls = 0
        svc.close()


# ---------------------------------------------------------------- adresses publiques
def test_public_url_par_langue():
    base = "https://dodotopia.cyber-dodo.fr"
    assert online.public_url("song", "fr", id=12, title="Für Élise (piano)") == f"{base}/fr/morceaux/12-fur-elise-piano"
    assert online.public_url("song", "de", id=12, title="Für Élise") == f"{base}/de/lieder/12-fur-elise"
    assert online.public_url("song", "ja", id=3, title="さくら") == f"{base}/ja/songs/3-song"
    assert online.public_url("drawing", "es", id=7) == f"{base}/es/galeria/7"
    assert online.public_url("drawing", "pt-BR", id=7) == f"{base}/pt-BR/galeria/7"
    assert online.public_url("room", "fr", code="k7p2qd") == f"{base}/fr/salon/K7P2QD"
    assert online.public_url("room", "de", code="K7P2QD") == f"{base}/de/raum/K7P2QD"
    assert online.public_url("room", "es", code="K7P2QD") == f"{base}/es/sala/K7P2QD"
    assert online.public_url("room", "th", code="K7P2QD") == f"{base}/th/room/K7P2QD"
    assert online.public_url("room", "xx", code="K7P2QD") == f"{base}/en/room/K7P2QD"
    assert online.public_url("gallery", "fr", "http://localhost:8000/") == "http://localhost:8000/fr/galerie"
    assert online.public_url("room", "fr", code=None) is None
    assert online.public_url("song", "fr", id="abc") is None and online.public_url("inconnu", "fr") is None


# ---------------------------------------------------------------- partage : j'aime, filtres, metadonnees
def _logged_service(server, tmp_path, **kw):
    svc = _service(server, tmp_path, **kw)
    svc.account.save("TOK123", {"id": 1, "username": "dodo"})
    return svc


def test_likes(server, tmp_path):
    svc = _service(server, tmp_path)
    try:
        with pytest.raises(OnlineError) as e:
            svc.like_song(1, True)                          # pas connecte : message clair, rien d'envoye
        assert e.value.code == 401 and "Connecte-toi" in str(e.value)
        svc.account.save("TOK123", {"id": 1, "username": "dodo"})
        svc.library["items"] = [{"id": 1, "likes": 3, "liked_by_me": False}]
        State.likes.clear()
        assert svc.like_song(1, True) == {"ok": True, "id": 1, "liked": True, "likes": 4}
        assert svc.status()["library"]["items"][0] == {"id": 1, "likes": 4, "liked_by_me": True}
        assert svc.like_drawing(5, False) == {"ok": True, "id": 5, "liked": False, "likes": 3}
        assert State.likes == [("POST", "/api/songs/1/like", "Bearer TOK123"),
                               ("DELETE", "/api/drawings/5/like", "Bearer TOK123")]
        with pytest.raises(OnlineError) as e:
            svc.like_song(2, True)
        assert e.value.code == 409 and "pas encore publié" in str(e.value)
    finally:
        svc.close()


def test_search_filters_and_public_urls(server, tmp_path):
    from helpers import wait_for
    svc = _logged_service(server, tmp_path)
    try:
        State.song_queries.clear()
        svc.search("elise", 1, "trending", "piano", "lute")
        wait_for(lambda: svc.status()["library"]["at"], what="recherche")
        q, auth = State.song_queries[-1]
        assert q == {"q": "elise", "page": "1", "per_page": str(online.PER_PAGE), "sort": "trending", "tag": "piano",
                     "instrument": "lute"}
        assert auth == "Bearer TOK123"                      # liked_by_me renvoye par le serveur
        lib = svc.status()["library"]
        assert lib["tag"] == "piano" and lib["instrument"] == "lute" and lib["sort"] == "trending"
        first = lib["items"][0]
        assert first["tags"] == ["piano"] and first["likes"] == 3 and first["liked_by_me"] is True
        assert first["page_url"].endswith("/fr/morceaux/11-fur-elise")
        svc.search("", 1, "n'importe", "tag-inconnu", "../x")
        wait_for(lambda: len(State.song_queries) == 2, what="seconde recherche")
        q, _ = State.song_queries[-1]
        assert q["sort"] == "recent" and "tag" not in q and "instrument" not in q
    finally:
        svc.close()


def test_share_with_metadata(server, tmp_path):
    from helpers import wait_for
    svc = _logged_service(server, tmp_path)
    try:
        path = tmp_path / "morceau.mid"
        path.write_bytes(MIDI_BYTES)
        State.uploads.clear()
        meta = {"tags": ["piano", "calme", "piano"], "instrument": "lute", "source_url": "https://onlinesequencer.net/1",
                "source_name": "Online\u202eSequencer", "license": "cc"}
        assert svc.share("morceau.mid", str(path), "Morceau", meta)
        wait_for(lambda: State.uploads, what="depot")
        fields, files = State.uploads[-1]
        assert json.loads(fields["tags"]) == ["piano", "calme"] and fields["instrument"] == "lute"
        assert fields["source_url"] == "https://onlinesequencer.net/1" and fields["source_name"] == "OnlineSequencer"
        assert fields["license"] == "cc" and files["file"][1] == MIDI_BYTES
        for bad, code in (({"tags": ["jazz"]}, "bad_tags"), ({"tags": online.SONG_TAGS[:9]}, "bad_tags"),
                          ({"source_url": "http://x.fr"}, "bad_source_url"), ({"license": "gpl"}, "bad_license"),
                          ({"instrument": "Piano Droit"}, "bad_instrument")):
            with pytest.raises(OnlineError) as e:
                online.clean_song_meta(bad)
            assert e.value.payload["code"] == code
            assert online.error_text(e.value, "share") == str(e.value)
    finally:
        svc.close()


# ---------------------------------------------------------------- import par lien
def _wait_import(svc, key):
    from helpers import wait_for
    return wait_for(lambda: (lambda j: j if j.get("state") in ("done", "error") else None)(
        svc.status()["jobs"]["imports"].get(key) or {}), what="import")


def test_import_url_ok(server, tmp_path):
    notes = []
    svc = _logged_service(server, tmp_path, notify=lambda m, k="info": notes.append((m, k)))
    try:
        key = svc.import_url("bitmidi.com/gymnopedie-mid")          # https:// ajoute
        job = _wait_import(svc, key)
        assert job["state"] == "done", job
        sid = job["song_id"]
        songs = svc.player.songs_folder
        assert sid == "Gymnopedie No1 Satie.mid" and os.path.isfile(os.path.join(songs, sid))
        with open(os.path.join(songs, sid), "rb") as f:
            assert f.read() == MIDI_BYTES
        m = svc.player.library.meta(sid)
        assert m["source_url"] == "https://bitmidi.com/gymnopedie-mid" and m["source_name"] == "BitMidi"
        assert m["sha256"] == MIDI_SHA and m["title"] == "Gymnopedie No1 Satie"
        assert ("Importé : Gymnopedie No1 Satie", "ok") in notes
        assert not os.listdir(online.DOWNLOADS_DIR)                 # fichier temporaire efface
        # meme fichier une seconde fois : deja dans la bibliotheque, rien n'est copie
        job2 = _wait_import(svc, svc.import_url("https://bitmidi.com/autre-lien-mid"))
        assert job2["state"] == "done" and job2["song_id"] == sid
        assert sorted(os.listdir(songs)) == [sid]
    finally:
        svc.close()


def test_import_url_errors(server, tmp_path):
    notes = []
    svc = _service(server, tmp_path, notify=lambda m, k="info": notes.append((m, k)))
    try:
        with pytest.raises(OnlineError) as e:
            svc.import_url("https://bitmidi.com/x")                     # sans compte
        assert e.value.code == 401
        svc.account.save("TOK123", {"id": 1, "username": "dodo"})
        for url, code in (("http://bitmidi.com/x", "https_required"), ("https://example.com/page", "bad_url"),
                          ("https://127.0.0.1/a.mid", "bad_url"), ("", "bad_url")):
            with pytest.raises(OnlineError) as e:
                svc.import_url(url)
            assert e.value.payload["code"] == code, url
        job = _wait_import(svc, svc.import_url("https://example.com/private.mid"))
        assert job["state"] == "error" and job["error"] == "Adresse refusée : le serveur ne va chercher que des sites publics."
        job = _wait_import(svc, svc.import_url("https://example.com/lent.mid"))
        assert job["state"] == "error" and "trop de temps" in job["error"]
        # le serveur annonce un fichier qui n'est pas un MIDI : refuse localement, rien dans la bibliotheque
        job = _wait_import(svc, svc.import_url("https://example.com/pasmidi.mid"))
        assert job["state"] == "error" and job["song_id"] is None
        assert os.listdir(svc.player.songs_folder) == []
        assert any(k == "warn" and m.startswith("Import par lien impossible") for m, k in notes)
    finally:
        svc.close()


# ---------------------------------------------------------------- galerie
def test_gallery_list_open_delete_report(server, tmp_path):
    from helpers import wait_for
    svc = _logged_service(server, tmp_path)
    try:
        svc.drawings_list(1, "popular")
        wait_for(lambda: svc.status()["gallery"]["at"], what="galerie")
        g = svc.status()["gallery"]
        assert g["sort"] == "popular" and [it["id"] for it in g["items"]] == [5, 6]
        chat = g["items"][0]
        assert chat["page_url"].endswith("/fr/galerie/5") and chat["mine"] is True and g["items"][1]["mine"] is False
        assert chat["thumb_url"].startswith("http://") and chat["image_url"] is None    # schema refuse
        assert svc.drawing_cells(5) == CELLS
        with pytest.raises(OnlineError) as e:
            svc.drawing_cells(6)                                        # 3 cases pour 2 x 2
        assert e.value.payload["code"] == "bad_cells"
        loaded = []
        seq = svc.open_drawing(5, on_loaded=lambda job, info: loaded.append((job, info)))
        wait_for(lambda: svc.status()["drawing_open"]["state"] == "ready", what="grille")
        assert loaded == [(CELLS, {"id": 5, "title": "Chat"})]
        assert svc.take_drawing(seq + 1) is None
        assert svc.take_drawing(seq) == {"id": 5, "title": "Chat", "job": CELLS}
        assert svc.take_drawing(seq) is None                            # remise une seule fois
        svc.open_drawing(99)
        wait_for(lambda: svc.status()["drawing_open"]["state"] == "error", what="grille absente")
        assert svc.status()["drawing_open"]["error"] == online.i18n.t("online.gallery.error.no_cells")
        State.drawing_reports.clear()
        with pytest.raises(OnlineError):
            svc.drawing_report(5, "   ")
        assert svc.drawing_report(5, "contenu\ninapproprie") is True
        assert State.drawing_reports == [(5, {"reason": "contenu inapproprie"})]
        assert svc.drawing_delete(5) is True and State.deleted_drawings[-1] == 5
        assert [it["id"] for it in svc.status()["gallery"]["items"]] == [6]
        with pytest.raises(OnlineError) as e:
            svc.drawing_delete(6)
        assert str(e.value) == "Ce dessin ne t'appartient pas."
    finally:
        svc.close()


def test_gallery_upload(server, tmp_path):
    from helpers import wait_for
    svc = _service(server, tmp_path)
    try:
        with pytest.raises(OnlineError):
            svc.drawing_upload(PNG_BYTES, "Chat", CELLS)                # sans compte
        svc.account.save("TOK123", {"id": 1, "username": "dodo"})
        with pytest.raises(OnlineError) as e:
            svc.drawing_upload(b"GIF89a", "Chat", CELLS)
        assert e.value.payload["code"] == "invalid_png"
        with pytest.raises(OnlineError) as e:
            svc.drawing_upload(PNG_BYTES + b"x" * online.DRAWING_PNG_MAX_BYTES, "Chat", CELLS)
        assert e.value.payload["code"] == "too_large"
        with pytest.raises(OnlineError) as e:
            svc.drawing_upload(PNG_BYTES, "Chat", {"format": "1:1", "w": 2, "h": 2, "cells": [0]})
        assert e.value.payload["code"] == "bad_cells"
        State.drawing_uploads.clear()
        assert svc.drawing_upload(PNG_BYTES, "Mon\u200b chat", CELLS) is True
        wait_for(lambda: svc.status()["gallery_upload"]["state"] == "done", what="depot")
        fields, files, auth = State.drawing_uploads[-1]
        assert auth == "Bearer TOK123" and fields["title"] == "Mon chat" and json.loads(fields["cells"]) == CELLS
        assert files["png"][0] == "dessin.png" and files["png"][1] == PNG_BYTES and files["png"][2] == "image/png"
        up = svc.status()["gallery_upload"]
        assert up["item"]["status"] == "pending" and up["item"]["page_url"].endswith("/fr/galerie/8") and up["seq"] == 1
        svc.drawing_upload(PNG_BYTES, "doublon", None)
        wait_for(lambda: svc.status()["gallery_upload"]["state"] == "error", what="doublon")
        assert svc.status()["gallery_upload"]["error"] == "Ce dessin est déjà dans la galerie."
        assert "cells" not in State.drawing_uploads[-1][0]
    finally:
        svc.close()


def test_room_exists(server, tmp_path):
    svc = _service(server, tmp_path)
    try:
        assert svc.room_exists("k7p2qd") == {"code": "K7P2QD", "valid": True, "exists": True, "full": False}
        assert svc.room_exists("FULL22") == {"code": "FULL22", "valid": True, "exists": True, "full": True}
        assert svc.room_exists("ABCDEF") == {"code": "ABCDEF", "valid": True, "exists": False, "full": False}
        assert svc.room_exists("../x")["valid"] is False
        st = svc.status()
        assert st["room_url"] is None and "piano" in st["meta"]["tags"] and st["meta"]["max_tags"] == 8
    finally:
        svc.close()


def test_decode_png_data_url():
    import base64
    ok = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()
    assert online.decode_png_data_url(ok, 1024) == PNG_BYTES
    for bad, why in (("data:image/jpeg;base64,AAAA", "prefix"), (None, "prefix"),
                     ("data:image/png;base64,@@@", "base64"),
                     ("data:image/png;base64," + base64.b64encode(b"GIF89a").decode(), "png"),
                     (ok, "size")):
        with pytest.raises(ValueError) as e:
            online.decode_png_data_url(bad, 10 if bad == ok else 1024)
        assert str(e.value) == why


# ---------------------------------------------------------------- connexion sans code (retour local)
class _LoopbackFake:
    """Serveur factice du mode « loopback » : la session n'est livree que contre le bon rapporte a l'appli."""

    def __init__(self, mode="loopback"):
        self.mode, self.grant, self.starts, self.polls = mode, "BON-123", [], []

    def url(self, path, params=None):
        return "http://example" + path

    def post(self, path, body=None, auth=True, **kw):
        if path == "/api/auth/start":
            self.starts.append(dict(body))
            loop = self.mode == "loopback" and body.get("loopback_port")
            return {"login_id": "L1", "url": "http://example/auth/discord/start?login_id=L1", "expires_in": 600,
                    "user_code": None if loop else "K7PQ2", "mode": "loopback" if loop else "code"}
        self.polls.append(dict(body))
        if body.get("grant") == self.grant:
            return {"status": "ok", "token": "tok", "user": {"username": "Dodo"}}
        return {"status": "pending"}


def _get_no_redirect(url):
    import urllib.error
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        return urllib.request.build_opener(NoRedirect).open(url, timeout=5).status, None
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location")


def test_login_sans_code_par_retour_local(tmp_path):
    fake = _LoopbackFake()
    acc = Account(str(tmp_path / "account.json"))
    flow = LoginFlow(fake, acc, lambda url: True)
    flow.poll_s = 0.05
    flow.start()
    st = flow.status()
    assert st["state"] == "waiting" and st["mode"] == "loopback" and st["user_code"] is None
    port = fake.starts[0]["loopback_port"]
    assert 1024 <= port <= 65535
    base = f"http://127.0.0.1:{port}"
    # ni un autre ticket, ni un autre chemin, ni un bon vide ne sont acceptes
    assert _get_no_redirect(base + "/dodotopia/login?login_id=AUTRE&grant=x")[0] == 404
    assert _get_no_redirect(base + "/autre?login_id=L1&grant=x")[0] == 404
    assert _get_no_redirect(base + "/dodotopia/login?login_id=L1")[0] == 404
    time.sleep(0.2)
    assert flow.status()["state"] == "waiting" and not acc.logged_in()
    assert all("grant" not in p for p in fake.polls)
    # le navigateur revient avec le bon : la session arrive, le navigateur part sur la page « Connecte »
    assert _get_no_redirect(base + f"/dodotopia/login?login_id=L1&grant={fake.grant}") == \
        (302, "http://example/auth/discord/done")
    for _ in range(100):
        if flow.status()["state"] == "ok":
            break
        time.sleep(0.05)
    assert flow.status()["state"] == "ok" and acc.logged_in() and flow.status()["mode"] is None
    assert fake.polls[-1]["grant"] == fake.grant


def test_login_code_en_secours(tmp_path):
    # serveur plus ancien : il ignore le port et renvoie un code -> l'appli affiche le code comme avant
    old = _LoopbackFake(mode="code")
    flow = LoginFlow(old, Account(str(tmp_path / "a.json")), lambda url: True)
    flow.poll_s = 0.05
    flow.start()
    assert flow.status()["mode"] == "code" and flow.status()["user_code"] == "K7PQ2"
    flow.cancel()
    # « depuis un autre appareil » : pas de port envoye, code affiche ; un ticket sans code en attente est abandonne
    fake = _LoopbackFake()
    flow = LoginFlow(fake, Account(str(tmp_path / "b.json")), lambda url: True)
    flow.poll_s = 0.05
    flow.start()
    assert flow.status()["mode"] == "loopback"
    flow.start(with_code=True)
    st = flow.status()
    assert st["mode"] == "code" and st["user_code"] == "K7PQ2" and "loopback_port" not in fake.starts[-1]
    flow.cancel()
    assert flow.status()["state"] == "idle" and flow.status()["mode"] is None
