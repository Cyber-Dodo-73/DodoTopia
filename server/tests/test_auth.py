"""Flow de connexion Discord par ticket, sessions, /api/me, logout."""
import hashlib
from urllib.parse import parse_qs, urlparse

from conftest import bearer, login


def _start(client, verifier="v1"):
    r = client.post("/api/auth/start", json={"verifier_hash": hashlib.sha256(verifier.encode()).hexdigest()})
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("http://testserver/auth/discord/start?login_id=")
    assert body["expires_in"] == 600
    return body["login_id"]


def test_full_flow_then_ticket_consumed(client):
    login_id = _start(client)
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "v1"})
    assert r.json() == {"status": "pending"}

    r = client.get(f"/auth/discord/start?login_id={login_id}")
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    assert loc.netloc == "discord.com"
    q = parse_qs(loc.query)
    assert q["scope"] == ["identify"] and q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["http://testserver/auth/discord/callback"]
    state = q["state"][0]

    r = client.get(f"/auth/discord/callback?code=111&state={state}")
    assert r.status_code == 302 and r.headers["location"] == "/auth/discord/done"
    r = client.get("/auth/discord/done")
    assert r.status_code == 200 and "fermer cet onglet" in r.text

    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "v1"})
    body = r.json()
    assert body["status"] == "ok"
    assert body["user"] == {"id": 1, "discord_id": "111", "username": "Alice",
                            "avatar_url": "https://cdn.discordapp.com/avatars/111/abc.png?size=64", "is_admin": False}
    token = body["token"]

    # livré une seule fois
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "v1"})
    assert r.status_code == 410

    r = client.get("/api/me", headers=bearer(token))
    assert r.status_code == 200 and r.json()["discord_id"] == "111"


def test_poll_bad_verifier_and_unknown(client):
    login_id = _start(client)
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "autre"})
    assert r.status_code == 403
    r = client.post("/api/auth/poll", json={"login_id": "inconnu", "verifier": "v1"})
    assert r.status_code == 404


def test_callback_bad_state_and_denied(client):
    r = client.get("/auth/discord/callback?code=111&state=faux")
    assert r.status_code == 302 and "error=expired" in r.headers["location"]

    login_id = _start(client, "v2")
    r = client.get(f"/auth/discord/start?login_id={login_id}")
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = client.get(f"/auth/discord/callback?state={state}&error=access_denied")
    assert r.status_code == 302 and "error=denied" in r.headers["location"]
    r = client.get("/auth/discord/done?error=denied")
    assert r.status_code == 400
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "v2"})
    assert r.json() == {"status": "error", "error": "denied"}


def test_start_page_unknown_ticket(client):
    r = client.get("/auth/discord/start?login_id=nope")
    assert r.status_code == 404


def test_me_requires_token_and_logout_revokes(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=bearer("faux")).status_code == 401
    token, _ = login(client, "111")
    assert client.get("/api/me", headers=bearer(token)).status_code == 200
    assert client.post("/api/auth/logout", headers=bearer(token)).status_code == 200
    assert client.get("/api/me", headers=bearer(token)).status_code == 401


def test_admin_flag_and_relogin_updates_profile(client):
    token, user = login(client, "999")
    assert user["is_admin"] is True
    assert user["avatar_url"].endswith("a_gif.gif?size=64")
    # deuxième connexion : même utilisateur, nouvelle session, l'ancienne reste valable
    token2, user2 = login(client, "999")
    assert user2["id"] == user["id"] and token2 != token
    assert client.get("/api/me", headers=bearer(token)).status_code == 200
    assert client.get("/api/me", headers=bearer(token2)).status_code == 200


def test_health_and_time(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db"] == "ok" and body["rooms"] == 0 and body["min_client"] == "1.7.0"
    r = client.get("/api/time")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["server_now_ms"] > 1_600_000_000_000
    r = client.get("/")
    assert r.status_code == 200 and "DodoTopia" in r.text
