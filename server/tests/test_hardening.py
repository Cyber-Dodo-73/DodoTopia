"""Chantier 6.1 sécurité et distribution : limites de débit ajoutées, WebSocket muette, compteur de
téléchargements par asset, /api/stats, manifeste signé Ed25519, en-têtes de durcissement."""
import base64
import hashlib
import json
import re
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app import releases, rooms
from conftest import bearer, login, make_client, make_settings

V = "1.7.0"


def put_setup(client, publish_headers, version="1.7.0", data=b"SETUP" * 1000, filename=None):
    filename = filename or f"DodoTopia-{version}-Setup.exe"
    r = client.put(f"/api/admin/releases/{version}/assets/windows-setup", content=data,
                   headers={**publish_headers, "X-Sha256": hashlib.sha256(data).hexdigest(), "X-Filename": filename})
    assert r.status_code == 200, r.text
    return filename


# --- limites de débit --------------------------------------------------------------

def _poll(client):
    return client.post("/api/auth/poll", json={"login_id": "x", "verifier": "y"})


def test_poll_limited_60_per_min(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        codes = [_poll(client).status_code for _ in range(61)]
        assert codes[:60] == [404] * 60 and codes[60] == 429


def test_confirm_limited_20_per_min(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        codes = [client.post("/auth/discord/confirm", data={"login_id": "x", "code": "A"}).status_code
                 for _ in range(21)]
        assert codes[:20] == [404] * 20 and codes[20] == 429


def test_releases_latest_limited_30_per_min(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        codes = [client.get("/api/releases/latest").status_code for _ in range(31)]
        assert codes[:30] == [404] * 30 and codes[30] == 429


def test_dl_limited_10_per_min(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        codes = [client.get("/dl/1.7.0/absent.exe").status_code for _ in range(11)]
        assert codes[:10] == [404] * 10 and codes[10] == 429


def test_song_download_limited_60_per_min(tmp_path, midi_bytes):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        tok, _ = login(client, "111")
        adm, _ = login(client, "999")
        sid = client.post("/api/songs", headers=bearer(tok), files={"file": ("m.mid", midi_bytes)}).json()["id"]
        client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(adm))
        codes = [client.get(f"/api/songs/{sid}/download").status_code for _ in range(61)]
        assert codes[:60] == [200] * 60 and codes[60] == 429


def test_delete_me_limited_3_per_hour(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        codes = [client.delete("/api/me").status_code for _ in range(4)]
        assert codes == [401, 401, 401, 429]


def test_room_join_limited_20_per_min(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        tok, _ = login(client, "111")
        seen = []
        buckets = client.app.state.ratelimiter.buckets
        for _ in range(21):
            # seule la limite de join est testée ici : la limite d'ouverture (20/min) est remise à zéro
            for key in [k for k in buckets if k[0] == "ws_open"]:
                del buckets[key]
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "join", "token": tok, "room_code": "ZZZZZZ", "name": "A",
                              "instrument": "piano", "version": V})
                seen.append(ws.receive_json()["code"])
        assert seen[:20] == ["room_not_found"] * 20 and seen[20] == "rate_limited"


def test_websocket_open_limited_20_per_min(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        for _ in range(20):
            with client.websocket_connect("/ws") as ws:
                ws.send_text("{oops")
                assert ws.receive_json()["code"] == "bad_message"
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws"):
                pass
        assert exc.value.code == 1008


# --- WebSocket muette ----------------------------------------------------------------

def test_silent_websocket_is_closed_1008(client, monkeypatch):
    monkeypatch.setattr(rooms, "FIRST_MSG_TIMEOUT_S", 0.15)
    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008
    # une fois dans un salon, le délai ne s'applique plus (c'est ROOM_IDLE_S du reaper qui veille)
    tok, _ = login(client, "111")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create", "token": tok, "name": "A", "instrument": "piano", "version": V})
        assert ws.receive_json()["type"] == "joined"
        ws.receive_json()
        time.sleep(0.3)
        ws.send_json({"type": "ping", "t0": 1})
        assert ws.receive_json()["type"] == "pong"


# --- compteur par asset et /api/stats --------------------------------------------------

def test_asset_download_counter_ignores_partial_ranges(client, publish_headers):
    name = put_setup(client, publish_headers)
    client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers, json={"notes": ""})
    url = f"/dl/1.7.0/{name}"

    def count():
        return client.get("/api/releases/latest").json()["assets"]["windows-setup"]["downloads"]

    assert count() == 0
    assert client.get(url).status_code == 200
    assert count() == 1
    assert client.get(url, headers={"Range": "bytes=10-19"}).status_code == 206      # reprise : pas compté
    assert client.get(url, headers={"Range": "bytes=100-"}).status_code == 206
    assert count() == 1
    assert client.get(url, headers={"Range": "bytes=0-"}).status_code == 206         # depuis le début : compté
    assert count() == 2
    assert client.get("/dl/1.7.0/absent.exe").status_code == 404
    assert count() == 2


def test_stats_endpoint_is_cached(client, publish_headers, user_token, admin_token, midi_bytes, app):
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json() == {"downloads_total": 0, "songs_approved": 0, "users": 2, "rooms_open": 0}
    assert "max-age=60" in r.headers["cache-control"]

    name = put_setup(client, publish_headers)
    client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers, json={"notes": ""})
    client.get(f"/dl/1.7.0/{name}")
    sid = client.post("/api/songs", headers=bearer(user_token), files={"file": ("m.mid", midi_bytes)}).json()["id"]
    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create", "token": user_token, "name": "A", "instrument": "piano", "version": V})
        ws.receive_json()
        # la publication a vidé le cache ; ensuite les chiffres restent figés 60 s
        first = client.get("/api/stats").json()
        assert first["downloads_total"] == 1 and first["songs_approved"] == 1 and first["rooms_open"] == 1
        client.get(f"/dl/1.7.0/{name}")
        assert client.get("/api/stats").json() == first
        app.state.stats_cache = None
        assert client.get("/api/stats").json()["downloads_total"] == 2


# --- manifeste signé --------------------------------------------------------------------

def keypair():
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    return sk, base64.b64encode(bytes(sk.verify_key)).decode()


def sign(sk, payload: str) -> str:
    return base64.b64encode(sk.sign(payload.encode()).signature).decode()


def test_signed_payload_is_canonical_and_verifiable(client, publish_headers):
    sk, pk = keypair()
    name = put_setup(client, publish_headers)
    assets = {"windows-setup": {"sha256": hashlib.sha256(b"SETUP" * 1000).hexdigest(), "size": 5000,
                                "filename": name}}
    published_at = "2026-09-16T10:00:00+00:00"
    payload = releases.signed_payload("1.7.0", assets, True, published_at)
    assert payload == json.dumps({"assets": assets, "mandatory": True, "published_at": published_at,
                                  "version": "1.7.0"}, sort_keys=True, separators=(",", ":"))
    assert " " not in payload
    # sans clé configurée : signature facultative, stockée telle quelle, manifeste exposé pour le client
    r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers,
                    json={"notes": "n", "mandatory": True, "published_at": published_at,
                          "signature": sign(sk, payload)})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["signed_payload"] == payload and m["signature"] == sign(sk, payload)
    assert m["published_at"] == published_at and m["mandatory"] is True
    latest = client.get("/api/releases/latest?current=1.6.0").json()
    assert latest["mandatory"] is True and latest["signed_payload"] == payload
    assert latest["signature"] == m["signature"] and latest["update_available"] is True
    # le client vérifie : la signature colle au signed_payload servi
    from nacl.signing import VerifyKey
    VerifyKey(base64.b64decode(pk)).verify(latest["signed_payload"].encode(),
                                            base64.b64decode(latest["signature"]))
    # sans signature du tout : accepté aussi (rétro-compatibilité), published_at posé par le serveur
    r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers, json={"notes": "n"})
    assert r.status_code == 200 and r.json()["signature"] is None and r.json()["published_at"] != published_at
    # signature mal formée : refusée même sans clé
    r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers,
                    json={"notes": "n", "signature": "pas du base64!"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_signature"


def test_server_verifies_signature_when_key_is_configured(tmp_path, publish_headers):
    sk, pk = keypair()
    other, _ = keypair()
    with make_client(make_settings(tmp_path, RELEASE_SIGNING_PUBLIC_KEY=pk)) as client:
        name = put_setup(client, publish_headers)
        assets = {"windows-setup": {"sha256": hashlib.sha256(b"SETUP" * 1000).hexdigest(), "size": 5000,
                                    "filename": name}}
        published_at = "2026-09-16T10:00:00+00:00"
        payload = releases.signed_payload("1.7.0", assets, False, published_at)
        base = {"notes": "n", "mandatory": False, "published_at": published_at}

        # absente
        r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers, json=base)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "signature_required"
        # mauvaise clé
        r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers,
                        json={**base, "signature": sign(other, payload)})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_signature"
        # bonne clé, mais mandatory différent de ce qui a été signé
        r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers,
                        json={**base, "mandatory": True, "signature": sign(sk, payload)})
        assert r.status_code == 400
        # taille de signature invalide
        r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers,
                        json={**base, "signature": base64.b64encode(b"x" * 10).decode()})
        assert r.status_code == 400
        # published_at illisible
        r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers,
                        json={**base, "published_at": "hier", "signature": sign(sk, payload)})
        assert r.status_code == 422
        assert client.get("/api/releases/latest").status_code == 404      # toujours rien de publié
        # valide
        r = client.post("/api/admin/releases/1.7.0/publish", headers=publish_headers,
                        json={**base, "signature": sign(sk, payload)})
        assert r.status_code == 200, r.text
        assert r.json()["signed_payload"] == payload and r.json()["published_at"] == published_at
        assert client.get("/api/releases/latest").json()["signature"] == sign(sk, payload)


# --- en-têtes -----------------------------------------------------------------------------

def test_security_headers_on_every_response(client):
    for path in ("/", "/en/", "/api/health", "/api/releases/latest", "/static/site.css",
                 "/auth/discord/start?login_id=x"):
        h = client.get(path).headers
        assert h["strict-transport-security"] == "max-age=31536000; includeSubDomains", path
        assert h["referrer-policy"] == "strict-origin-when-cross-origin", path
        assert h["permissions-policy"] == "camera=(), microphone=(), geolocation=()", path
        assert h["x-frame-options"] == "DENY", path
        assert h["x-content-type-options"] == "nosniff", path
        # CSP partout : nonce par requête pour le site, variante sans script pour les pages /auth/
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp, path
        if path.startswith("/auth/"):
            assert "script-src 'none'" in csp, path
        else:
            assert re.search(r"script-src 'self' 'nonce-[A-Za-z0-9_-]{16,}'", csp), path
            assert "unsafe-inline" not in csp and "unsafe-eval" not in csp, path
