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


# ---------------------------------------------------------------- serveur HTTP de test
class State:
    uploads = []
    login_polls = 0
    latest = {"version": "9.9.9", "notes": "test", "mandatory": False,
              "asset": {"url": "/dl/9.9.9/file.bin", "sha256": FILE_SHA, "size": len(FILE_BYTES)}}


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
            if q.get("current") == "9.9.9":
                return self._json(200, dict(State.latest, update_available=False))
            return self._json(200, dict(State.latest, update_available=True, platform=q.get("platform")))
        if u.path == "/api/me":
            return self._json(200, {"id": 1, "username": "dodo", "is_admin": True})
        return self._json(404, {"message": "inconnu"})

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        raw = self._body()
        if u.path == "/api/echo":
            return self._json(200, {"method": "POST", "json": json.loads(raw.decode()),
                                    "ctype": self.headers.get("Content-Type")})
        if u.path == "/api/songs":
            ctype = self.headers.get("Content-Type", "")
            m = re.search(r"boundary=(.+)$", ctype)
            assert m, ctype
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
                    files[name] = (fname.group(1), content)
                else:
                    fields[name] = content.decode()
            State.uploads.append((fields, files))
            if fields.get("title") == "doublon":
                return self._json(409, {"message": "déjà présent", "existing_id": 42})
            return self._json(201, {"id": 7, "title": fields.get("title"), "filename": files["file"][0],
                                    "size": len(files["file"][1]), "sha256": hashlib.sha256(files["file"][1]).hexdigest()})
        if u.path == "/api/auth/start":
            body = json.loads(raw.decode())
            State.verifier_hash = body["verifier_hash"]
            return self._json(200, {"login_id": "L1", "url": "http://example/auth?login_id=L1", "expires_in": 600})
        if u.path == "/api/auth/poll":
            body = json.loads(raw.decode())
            State.login_polls += 1
            if hashlib.sha256(body["verifier"].encode()).hexdigest() != State.verifier_hash:
                return self._json(403, {"message": "verifier"})
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
    flow._thread.join(5)
    assert flow.status()["state"] == "ok" and acc.token == "TOK123" and acc.user["username"] == "dodo"
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
