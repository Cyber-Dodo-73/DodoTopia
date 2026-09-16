"""Import par lien (Online Sequencer, BitMidi, URL .mid) : résolution, anti-SSRF, taille, validation, cache, jeton à
usage unique. Aucun appel réseau réel : `importer.TRANSPORT` est un `httpx.MockTransport` et la résolution DNS est
remplacée."""
import hashlib
import os
import time

import httpx
import pytest
from conftest import bearer, login, make_client, make_midi, make_settings

from app import importer

PUBLIC_IP = "93.184.216.34"


class FakeWeb:
    """Serveurs simulés : URL -> (statut, en-têtes, corps) ; journal des requêtes reçues."""

    def __init__(self):
        self.routes: dict[str, tuple[int, dict, bytes]] = {}
        self.requests: list[httpx.Request] = []

    def add(self, url, body=b"", status=200, headers=None):
        self.routes[url] = (status, headers or {}, body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, headers, body = self.routes.get(str(request.url), (404, {}, b"introuvable"))
        return httpx.Response(status, headers=headers, content=body)


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(importer, "TRANSPORT", httpx.MockTransport(fake.handler))
    hosts = {"internal.example.org": "10.0.0.5", "rebind.example.org": "127.0.0.1", "v6.example.org": "::1"}
    monkeypatch.setattr(importer, "resolve_host", lambda host: [hosts.get(host, PUBLIC_IP)])
    return fake


def do_import(client, token, url):
    return client.post("/api/import", headers=bearer(token), json={"url": url})


def test_online_sequencer_nominal_and_single_use_token(client, user_token, web, midi_bytes):
    web.add("https://onlinesequencer.net/app/midi.php?id=12345", midi_bytes)
    assert client.post("/api/import", json={"url": "12345"}).status_code == 401
    r = do_import(client, user_token, "https://onlinesequencer.net/12345")
    assert r.status_code == 200, r.text
    body = r.json()
    sha = hashlib.sha256(midi_bytes).hexdigest()
    assert body["ok"] is True and body["size"] == len(midi_bytes) and body["sha256"] == sha
    assert body["source_url"] == "https://onlinesequencer.net/12345"
    assert body["source_name"] == "Online Sequencer" and body["source_author"] is None
    assert body["filename"].endswith(".mid") and body["download_token"]
    ua = web.requests[0].headers["user-agent"]
    assert ua.startswith("DodoTopia/") and "(+https://dodotopia.cyber-dodo.fr)" in ua
    r = client.get(f"/api/import/{body['download_token']}")
    assert r.status_code == 200 and r.content == midi_bytes
    assert r.headers["content-type"] == "audio/midi" and r.headers["x-sha256"] == sha
    assert "attachment;" in r.headers["content-disposition"]
    assert client.get(f"/api/import/{body['download_token']}").status_code == 404      # une seule fois
    assert client.get("/api/songs").json()["total"] == 0                                # rien n'est publié
    assert client.get("/api/admin/songs?status=pending",
                      headers=bearer(login(client, "999")[0])).json()["total"] == 0


def test_bare_id_and_app_url(client, user_token, web, midi_bytes):
    web.add("https://onlinesequencer.net/app/midi.php?id=77", midi_bytes)
    assert do_import(client, user_token, "77").status_code == 200
    assert do_import(client, user_token, "https://onlinesequencer.net/app/sequencer.php?id=77").status_code == 200


def test_bitmidi_page_then_file(client, user_token, web, midi_bytes):
    page = (b'<html><h1>Never Gonna Give You Up</h1><a href="/uploads/4242.mid" download>Download MIDI</a>'
            b'<script>evil()</script></html>')
    web.add("https://bitmidi.com/never-gonna-give-you-up-mid", page)
    web.add("https://bitmidi.com/uploads/4242.mid", midi_bytes)
    r = do_import(client, user_token, "https://bitmidi.com/never-gonna-give-you-up-mid")
    assert r.status_code == 200, r.text
    assert r.json()["source_name"] == "BitMidi" and r.json()["filename"] == "Never Gonna Give You Up.mid"
    assert r.json()["source_url"] == "https://bitmidi.com/never-gonna-give-you-up-mid"
    web.add("https://bitmidi.com/sans-fichier", b"<html>rien</html>")
    r = do_import(client, user_token, "https://bitmidi.com/sans-fichier")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"


def test_direct_url(client, user_token, web, midi_bytes):
    web.add("https://files.example.net/midi/Ma%20Chanson.mid", midi_bytes)
    r = do_import(client, user_token, "https://files.example.net/midi/Ma%20Chanson.mid")
    assert r.status_code == 200, r.text
    assert r.json()["filename"] == "Ma Chanson.mid" and r.json()["source_name"] == "files.example.net"


@pytest.mark.parametrize("url, status, code", [
    ("http://onlinesequencer.net/1", 422, "https_required"),
    ("ftp://files.example.net/a.mid", 422, "https_required"),
    ("https://example.com/page.html", 422, "host_not_allowed"),
    ("https://onlinesequencer.net/forum/thread", 422, "unsupported_url"),
    ("https://user:pw@files.example.net/a.mid", 422, "bad_url"),
    ("https://files.example.net:8443/a.mid", 422, "bad_url"),
    ("https://internal.example.org/a.mid", 403, "private_address"),
    ("https://rebind.example.org/a.mid", 403, "private_address"),
    ("https://v6.example.org/a.mid", 403, "private_address"),
    ("https://127.0.0.1/a.mid", 403, "private_address"),
    ("https://169.254.169.254/latest.mid", 403, "private_address"),
    ("https://[::ffff:10.0.0.1]/a.mid", 403, "private_address"),
    ("pas un lien", 422, "bad_url"),
    ("onlinesequencer.net/12", 422, "https_required"),
])
def test_refused_urls_never_reach_the_network(client, user_token, web, url, status, code):
    r = do_import(client, user_token, url)
    assert r.status_code == status and r.json()["detail"]["code"] == code, r.text
    assert web.requests == []


def test_redirects_are_checked_hop_by_hop(client, user_token, web, midi_bytes):
    web.add("https://files.example.net/a.mid", status=302, headers={"location": "https://internal.example.org/a.mid"})
    r = do_import(client, user_token, "https://files.example.net/a.mid")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "private_address"
    assert [str(q.url) for q in web.requests] == ["https://files.example.net/a.mid"]

    web.add("https://files.example.net/b.mid", status=301, headers={"location": "http://files.example.net/b.mid"})
    assert do_import(client, user_token, "https://files.example.net/b.mid").json()["detail"]["code"] == "https_required"

    # un site sur liste blanche ne peut pas rediriger ailleurs
    web.add("https://onlinesequencer.net/app/midi.php?id=5", status=302,
            headers={"location": "https://files.example.net/c.mid"})
    assert do_import(client, user_token, "5").json()["detail"]["code"] == "host_not_allowed"

    # deux redirections acceptées, pas trois
    web.add("https://files.example.net/r1.mid", status=302, headers={"location": "/r2.mid"})
    web.add("https://files.example.net/r2.mid", status=307, headers={"location": "https://cdn.example.net/r3.mid"})
    web.add("https://cdn.example.net/r3.mid", midi_bytes)
    assert do_import(client, user_token, "https://files.example.net/r1.mid").status_code == 200
    web.add("https://files.example.net/r0.mid", status=302, headers={"location": "/r1.mid"})
    r = do_import(client, user_token, "https://files.example.net/r0.mid")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "too_many_redirects"


def test_direct_hosts_whitelist(tmp_path, web, midi_bytes):
    with make_client(make_settings(tmp_path, IMPORT_DIRECT_HOSTS="files.example.net")) as c:
        tok, _ = login(c, "111")
        web.add("https://files.example.net/a.mid", midi_bytes)
        assert do_import(c, tok, "https://files.example.net/a.mid").status_code == 200
        r = do_import(c, tok, "https://other.example.net/a.mid")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "host_not_allowed"


def test_too_large_and_not_midi(tmp_path, web):
    big = make_midi(n_notes=200)
    with make_client(make_settings(tmp_path, MAX_MIDI_BYTES=1000)) as c:
        tok, _ = login(c, "111")
        web.add("https://files.example.net/big.mid", big)
        r = do_import(c, tok, "https://files.example.net/big.mid")
        assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"
        web.add("https://files.example.net/fake.mid", b"MThd" + b"\x00" * 100)
        r = do_import(c, tok, "https://files.example.net/fake.mid")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_midi"
        web.add("https://files.example.net/html.mid", b"<html>pas un midi</html>")
        assert do_import(c, tok, "https://files.example.net/html.mid").json()["detail"]["code"] == "invalid_midi"
        assert not list(c.app.state.settings.import_cache_dir.glob("*.mid"))       # rien d'invalide en cache


def test_streamed_body_is_cut_without_content_length(tmp_path, monkeypatch):
    def handler(request):
        return httpx.Response(200, stream=httpx.ByteStream(b"MThd" + b"\x00" * 5000))
    monkeypatch.setattr(importer, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setattr(importer, "resolve_host", lambda host: [PUBLIC_IP])
    with make_client(make_settings(tmp_path, MAX_MIDI_BYTES=1000)) as c:
        tok, _ = login(c, "111")
        r = do_import(c, tok, "https://files.example.net/s.mid")
        assert r.status_code == 413


def test_upstream_errors(client, user_token, web, monkeypatch):
    web.add("https://files.example.net/500.mid", status=500)
    assert do_import(client, user_token, "https://files.example.net/500.mid").json()["detail"]["code"] == "upstream_error"
    assert do_import(client, user_token, "https://files.example.net/absent.mid").status_code == 404

    def slow(request):
        raise httpx.ReadTimeout("trop lent", request=request)
    monkeypatch.setattr(importer, "TRANSPORT", httpx.MockTransport(slow))
    r = do_import(client, user_token, "https://files.example.net/slow.mid")
    assert r.status_code == 504 and r.json()["detail"]["code"] == "timeout"


def test_cache_is_used_for_seven_days(client, user_token, web, midi_bytes, settings):
    web.add("https://onlinesequencer.net/app/midi.php?id=9", midi_bytes)
    first = do_import(client, user_token, "https://onlinesequencer.net/9").json()
    assert len(web.requests) == 1
    second = do_import(client, user_token, "9").json()           # même source, autre écriture : cache
    assert len(web.requests) == 1
    assert second["sha256"] == first["sha256"] and second["download_token"] != first["download_token"]
    assert client.get(f"/api/import/{second['download_token']}").content == midi_bytes
    cached = list(settings.import_cache_dir.glob("onlinesequencer-*.mid"))
    assert len(cached) == 1
    old = time.time() - 8 * 86400
    os.utime(cached[0], (old, old))
    do_import(client, user_token, "9")
    assert len(web.requests) == 2                               # périmé : téléchargé de nouveau
    for p in settings.import_cache_dir.glob("*"):
        os.utime(p, (old, old))
    importer.purge_cache(settings)
    assert not list(settings.import_cache_dir.glob("*"))


def test_token_expires(client, user_token, web, midi_bytes, monkeypatch):
    web.add("https://onlinesequencer.net/app/midi.php?id=3", midi_bytes)
    token = do_import(client, user_token, "3").json()["download_token"]
    client.app.state.import_tokens[token]["expires"] = time.monotonic() - 1
    assert client.get(f"/api/import/{token}").status_code == 404
    assert client.get("/api/import/n-importe-quoi").status_code == 404


def test_import_rate_limited_10_per_min(tmp_path, web, midi_bytes):
    web.add("https://onlinesequencer.net/app/midi.php?id=1", midi_bytes)
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as c:
        tok, _ = login(c, "111")
        codes = [do_import(c, tok, "1").status_code for _ in range(11)]
        assert codes[:10] == [200] * 10 and codes[10] == 429


def test_is_public_ip_unit():
    for ip in ("10.1.2.3", "172.16.0.1", "192.168.1.1", "127.0.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1",
               "fc00::1", "::ffff:192.168.0.1", "100.64.0.1", "224.0.0.1", "pas une ip"):
        assert importer.is_public_ip(ip) is False, ip
    for ip in (PUBLIC_IP, "1.1.1.1", "2606:4700:4700::1111"):
        assert importer.is_public_ip(ip) is True, ip
