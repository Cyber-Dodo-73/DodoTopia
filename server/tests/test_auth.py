"""Flow de connexion Discord par ticket (code à recopier), sessions, /api/me, logout, suppression de compte."""
import hashlib
from urllib.parse import parse_qs, urlparse

from app import db
from app.auth import USER_CODE_ALPHABET, USER_CODE_LEN
from conftest import bearer, login


def _start(client, verifier="v1"):
    r = client.post("/api/auth/start", json={"verifier_hash": hashlib.sha256(verifier.encode()).hexdigest()})
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("http://testserver/auth/discord/start?login_id=")
    assert body["expires_in"] == 600
    assert len(body["user_code"]) == USER_CODE_LEN and set(body["user_code"]) <= set(USER_CODE_ALPHABET)
    return body["login_id"], body["user_code"]


def _confirm(client, login_id, code):
    return client.post("/auth/discord/confirm", data={"login_id": login_id, "code": code})


def _poll(client, login_id, verifier):
    return client.post("/api/auth/poll", json={"login_id": login_id, "verifier": verifier})


def test_full_flow_then_ticket_consumed(client):
    login_id, user_code = _start(client)
    r = _poll(client, login_id, "v1")
    assert r.json() == {"status": "pending"}

    # la page de départ demande le code affiché dans l'app, sans rediriger vers Discord
    r = client.get(f"/auth/discord/start?login_id={login_id}")
    assert r.status_code == 200 and "discord.com" not in r.text
    assert 'action="/auth/discord/confirm"' in r.text and "Recopie le code" in r.text
    assert user_code not in r.text          # le code ne vient que de l'app

    r = _confirm(client, login_id, user_code.lower())   # casse indifférente
    assert r.status_code == 303
    loc = urlparse(r.headers["location"])
    assert loc.netloc == "discord.com"
    q = parse_qs(loc.query)
    assert q["scope"] == ["identify"] and q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["http://testserver/auth/discord/callback"]
    assert "prompt" not in q                # plus de prompt=none : Discord affiche son écran d'autorisation
    state = q["state"][0]

    r = client.get(f"/auth/discord/callback?code=111&state={state}")
    assert r.status_code == 302 and r.headers["location"] == "/auth/discord/done"
    r = client.get("/auth/discord/done")
    assert r.status_code == 200 and "fermer cet onglet" in r.text

    r = _poll(client, login_id, "v1")
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
    login_id, _ = _start(client)
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "autre"})
    assert r.status_code == 403
    r = client.post("/api/auth/poll", json={"login_id": "inconnu", "verifier": "v1"})
    assert r.status_code == 404


def test_callback_bad_state_and_denied(client):
    r = client.get("/auth/discord/callback?code=111&state=faux")
    assert r.status_code == 302 and "error=expired" in r.headers["location"]

    login_id, code = _start(client, "v2")
    r = _confirm(client, login_id, code)
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
    assert _confirm(client, "nope", "ABCDE").status_code == 404


def test_wrong_code_five_times_puts_ticket_in_error(client):
    login_id, code = _start(client, "v3")
    wrong = "AAAAA" if code != "AAAAA" else "BBBBB"
    for remaining in (4, 3, 2, 1):
        r = _confirm(client, login_id, wrong)
        assert r.status_code == 400 and "Code incorrect" in r.text
        assert f"reste {remaining} essai" in r.text
        assert _poll(client, login_id, "v3").json() == {"status": "pending"}
    r = _confirm(client, login_id, wrong)
    assert r.status_code == 403 and "Trop de tentatives" in r.text
    # ticket en erreur : le bon code ne passe plus, l'app voit l'erreur
    assert _confirm(client, login_id, code).status_code == 404
    assert client.get(f"/auth/discord/start?login_id={login_id}").status_code == 404
    assert _poll(client, login_id, "v3").json() == {"status": "error", "error": "code"}


def test_callback_requires_confirmed_code(client, settings):
    """Le `state` d'un ticket non confirmé n'est jamais sorti du serveur ; s'il fuit, le callback le refuse."""
    login_id, code = _start(client, "v4")
    conn = db.connect(settings)
    try:
        state = conn.execute("SELECT state FROM login_tickets WHERE id=?", (login_id,)).fetchone()["state"]
    finally:
        conn.close()
    r = client.get(f"/auth/discord/callback?code=111&state={state}")
    assert r.status_code == 302 and "error=expired" in r.headers["location"]
    assert _poll(client, login_id, "v4").json() == {"status": "pending"}


def test_session_is_created_at_poll_and_never_stored_on_the_ticket(client, settings):
    """Le ticket ne porte que l'identité ; la session naît au poll et n'apparaît nulle part en clair."""
    login_id, code = _start(client, "v5")
    state = parse_qs(urlparse(_confirm(client, login_id, code).headers["location"]).query)["state"][0]
    assert client.get(f"/auth/discord/callback?code=111&state={state}").status_code == 302
    conn = db.connect(settings)
    try:
        t = conn.execute("SELECT * FROM login_tickets WHERE id=?", (login_id,)).fetchone()
        assert t["status"] == "ok" and t["user_id"] == 1 and t["token"] is None
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0     # rien avant le poll
        token = _poll(client, login_id, "v5").json()["token"]
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        t = conn.execute("SELECT * FROM login_tickets WHERE id=?", (login_id,)).fetchone()
        assert t["status"] == "used" and t["user_id"] is None and t["token"] is None
        assert token not in [r["token_hash"] for r in conn.execute("SELECT token_hash FROM sessions")]
    finally:
        conn.close()
    assert client.get("/api/me", headers=bearer(token)).status_code == 200


def test_session_is_not_rewritten_within_the_hour(client, settings):
    token, _ = login(client, "111")
    conn = db.connect(settings)
    try:
        before = conn.execute("SELECT last_used_at, expires_at FROM sessions").fetchone()
        old = db.iso_in(-2 * 3600)
        conn.execute("UPDATE sessions SET last_used_at=?", (old,))
        conn.commit()
        assert client.get("/api/me", headers=bearer(token)).status_code == 200
        touched = conn.execute("SELECT last_used_at, expires_at FROM sessions").fetchone()
        assert touched["last_used_at"] > old and touched["last_used_at"] >= before["last_used_at"]
        # dans l'heure : plus aucune écriture
        marker = db.iso_in(3600)
        conn.execute("UPDATE sessions SET expires_at=?", (marker,))
        conn.commit()
        for _ in range(3):
            assert client.get("/api/me", headers=bearer(token)).status_code == 200
        again = conn.execute("SELECT last_used_at, expires_at FROM sessions").fetchone()
        assert again["last_used_at"] == touched["last_used_at"] and again["expires_at"] == marker
    finally:
        conn.close()


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
    assert r.status_code == 302 and r.headers["location"] == "/en/"
    r = client.get("/en/")
    assert r.status_code == 200 and "DodoTopia" in r.text


def test_delete_account_anonymises_approved_songs(client, user_token, other_token, admin_token, midi_bytes, settings):
    from conftest import make_midi
    up = lambda tok, data, name: client.post("/api/songs", headers=bearer(tok),  # noqa: E731
                                             files={"file": (name, data, "audio/midi")}, data={"title": name})
    approved = up(user_token, midi_bytes, "garde.mid").json()["id"]
    pending = up(user_token, make_midi(n_notes=30), "attente.mid").json()
    rejected = up(user_token, make_midi(n_notes=40), "refuse.mid").json()
    client.post(f"/api/admin/songs/{approved}/approve", headers=bearer(admin_token))
    client.post(f"/api/admin/songs/{rejected['id']}/reject", headers=bearer(admin_token), json={"reason": "x"})
    other_song = up(other_token, make_midi(n_notes=50), "autre.mid").json()["id"]
    client.post(f"/api/admin/songs/{other_song}/approve", headers=bearer(admin_token))
    assert client.post(f"/api/songs/{other_song}/report", headers=bearer(user_token), json={"reason": "r"}).status_code == 201
    assert client.post(f"/api/songs/{approved}/report", headers=bearer(other_token), json={"reason": "r"}).status_code == 201

    assert client.delete("/api/me").status_code == 401
    r = client.delete("/api/me", headers=bearer(user_token))
    assert r.status_code == 200 and r.json() == {"ok": True, "songs_kept": 1, "songs_deleted": 2, "drawings_kept": 0,
                                          "drawings_deleted": 0}
    assert client.get("/api/me", headers=bearer(user_token)).status_code == 401

    kept = client.get(f"/api/songs/{approved}").json()
    assert kept["uploader_id"] is None and kept["uploader_name"] == "Compte supprimé"
    assert kept["title"] == "garde.mid" and client.get(f"/api/songs/{approved}/download").status_code == 200
    assert client.get("/api/songs").json()["total"] == 2
    for gone in (pending, rejected):
        assert client.get(f"/api/songs/{gone['id']}", headers=bearer(admin_token)).status_code == 404
        assert not (settings.songs_dir / f"{gone['sha256']}.mid").exists()
    assert (settings.songs_dir / f"{kept['sha256']}.mid").is_file()
    reports = client.get("/api/admin/reports?open=1", headers=bearer(admin_token)).json()["items"]
    assert [x["song_id"] for x in reports] == [approved]      # le signalement émis par le compte a disparu
    conn = db.connect(settings)
    try:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE id=1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=1").fetchone()[0] == 0
    finally:
        conn.close()
    # l'admin qui a validé peut lui aussi partir : les morceaux qu'il a relus restent
    assert client.delete("/api/me", headers=bearer(admin_token)).status_code == 200
    assert client.get(f"/api/songs/{approved}").status_code == 200
    # le même Discord se reconnecte : nouveau compte, vierge
    token, user = login(client, "111")
    assert user["id"] not in (1,) and client.get("/api/me", headers=bearer(token)).status_code == 200


# ---------------------------------------------------------------- connexion sans code (retour local)
def sha256_hex(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _start_loopback(client, port=54321, verifier="v1"):
    r = client.post("/api/auth/start", json={"verifier_hash": sha256_hex(verifier), "loopback_port": port})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "loopback" and body["user_code"] is None
    return body["login_id"]


def test_loopback_flow_needs_no_code_and_delivers_only_with_the_grant(client):
    login_id = _start_loopback(client)
    # la page de départ part tout de suite chez Discord : rien à recopier
    r = client.get(f"/auth/discord/start?login_id={login_id}")
    assert r.status_code == 303 and urlparse(r.headers["location"]).netloc == "discord.com"
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]

    r = client.get(f"/auth/discord/callback?code=111&state={state}")
    loc = urlparse(r.headers["location"])
    assert r.status_code == 302 and loc.scheme == "http" and loc.netloc == "127.0.0.1:54321"
    assert loc.path == "/dodotopia/login"
    q = parse_qs(loc.query)
    assert q["login_id"] == [login_id] and len(q["grant"][0]) >= 32

    # sans le bon (celui qui a créé le ticket mais n'a pas reçu le retour local) : toujours « en attente »
    assert _poll(client, login_id, "v1").json() == {"status": "pending"}
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "v1", "grant": "faux"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "bad_grant"
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "autre", "grant": q["grant"][0]})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "bad_verifier"

    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "v1", "grant": q["grant"][0]})
    body = r.json()
    assert body["status"] == "ok" and body["user"]["discord_id"] == "111"
    assert client.get("/api/me", headers=bearer(body["token"])).status_code == 200
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": "v1", "grant": q["grant"][0]})
    assert r.status_code == 410                                    # livré une seule fois


def test_loopback_ticket_cannot_use_the_code_form_and_port_is_bounded(client, settings):
    login_id = _start_loopback(client)
    assert _confirm(client, login_id, "").status_code == 404         # pas de code : la page de saisie est fermée
    assert _confirm(client, login_id, "AAAAA").status_code == 404
    for port in (80, 1023, 70000, 0):
        r = client.post("/api/auth/start", json={"verifier_hash": sha256_hex("v"), "loopback_port": port})
        assert r.status_code == 422 or r.json().get("mode") == "code", port
    # le bon n'est jamais stocké en clair
    conn = db.connect(settings)
    try:
        r = client.get(f"/auth/discord/start?login_id={login_id}")
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        loc = client.get(f"/auth/discord/callback?code=111&state={state}").headers["location"]
        grant = parse_qs(urlparse(loc).query)["grant"][0]
        row = conn.execute("SELECT grant_hash, user_code FROM login_tickets WHERE id=?", (login_id,)).fetchone()
        assert row["grant_hash"] == sha256_hex(grant) and grant not in str(dict(row)) and row["user_code"] is None
    finally:
        conn.close()


def test_code_flow_is_unchanged_and_ignores_a_grant(client):
    login_id, user_code = _start(client)
    assert client.get(f"/auth/discord/start?login_id={login_id}").status_code == 200      # page du code
    r = _confirm(client, login_id, user_code)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = client.get(f"/auth/discord/callback?code=111&state={state}")
    assert r.headers["location"] == "/auth/discord/done"
    assert _poll(client, login_id, "v1").json()["status"] == "ok"
