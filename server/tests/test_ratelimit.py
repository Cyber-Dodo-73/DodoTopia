"""Limitation de débit : seau à jetons, 429 + Retry-After, WebSocket 20 msg/s, désactivation."""
import hashlib
import time

from app.ratelimit import TokenBucket
from conftest import login, make_client, make_settings


def test_token_bucket():
    now = 1000.0
    b = TokenBucket(3, 1.0, now=now)
    assert [b.take(now) for _ in range(3)] == [0.0, 0.0, 0.0]
    wait = b.take(now)
    assert 0 < wait <= 1.0
    assert b.take(now + 1.0) == 0.0          # un jeton par seconde
    assert b.take(now + 100.0) == 0.0        # plafonné à la capacité
    assert b.take(now + 100.0) == 0.0
    assert b.take(now + 100.0) == 0.0
    assert b.take(now + 100.0) > 0


def _start(client):
    return client.post("/api/auth/start", json={"verifier_hash": hashlib.sha256(b"x").hexdigest()})


def test_auth_start_limited_per_ip(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        for _ in range(10):
            assert _start(client).status_code == 200
        r = _start(client)
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1
        assert r.json()["detail"]["code"] == "rate_limited"


def test_disabled_when_zero(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=0)) as client:
        for _ in range(15):
            assert _start(client).status_code == 200


def test_websocket_burst_limited(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as client:
        token, _ = login(client, "111")
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create", "token": token, "name": "A", "instrument": "piano", "version": "1.7.0"})
            assert ws.receive_json()["type"] == "joined"
            assert ws.receive_json()["type"] == "state"
            for i in range(40):
                ws.send_json({"type": "ping", "t0": i})
            kinds = [ws.receive_json()["type"] for _ in range(40)]
            assert kinds.count("pong") >= 20
            assert "error" in kinds
            time.sleep(0.3)   # le seau se remplit (20 jetons/s) : leave passe de nouveau
            ws.send_json({"type": "leave"})
            assert ws.receive_json()["type"] == "bye"
