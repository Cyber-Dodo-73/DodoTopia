"""Fixtures communes : app isolée (DATA_DIR temporaire, limitation désactivée), Discord simulé, connexions.

Base : SQLite dans DATA_DIR par défaut. Si la variable d'environnement `DATABASE_URL` (postgresql://…) est définie,
toute la suite tourne sur ce Postgres (les tables sont supprimées et recréées à chaque app de test).
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import mido
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import auth, db  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

PUBLISH_TOKEN = "jeton-de-test"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
requires_postgres = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL (postgresql://…) non définie")

# Profils Discord renvoyés par le faux `discord_fetch_user` (le code OAuth = l'id Discord).
FAKE_USERS = {
    "111": {"id": "111", "username": "alice", "global_name": "Alice", "avatar": "abc"},
    "222": {"id": "222", "username": "bob", "global_name": None, "avatar": None},
    "999": {"id": "999", "username": "admin", "global_name": "Admin", "avatar": "a_gif"},
}


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(DATA_DIR=str(tmp_path / "data"), RATE_LIMIT=0, PUBLIC_URL="http://testserver",
                DISCORD_CLIENT_ID="cid", DISCORD_CLIENT_SECRET="secret", ADMIN_DISCORD_IDS="999",
                PUBLISH_TOKEN=PUBLISH_TOKEN, MIN_CLIENT_VERSION="1.7.0", DATABASE_URL=DATABASE_URL)
    base.update(overrides)
    s = Settings(_env_file=None, **base)
    if s.DATABASE_URL:
        db.database(s).drop_all()   # base partagée : repart d'un schéma vide (ids à 1) pour chaque app de test
    return s


def make_client(settings: Settings) -> TestClient:
    """Client de test sur une app fraîche (à utiliser en `with`), sans suivre les redirections vers Discord."""
    return TestClient(create_app(settings), follow_redirects=False)


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture(autouse=True)
def mock_discord(monkeypatch):
    monkeypatch.setattr(auth, "discord_exchange_code", lambda settings, code: f"access-{code}")
    monkeypatch.setattr(auth, "discord_fetch_user", lambda access: dict(FAKE_USERS[access.removeprefix("access-")]))


def login(client: TestClient, discord_id: str) -> tuple[str, dict]:
    """Déroule tout le flow ticket -> navigateur (code recopié) -> callback -> poll. Renvoie (token, user)."""
    verifier = f"verif-{discord_id}"
    r = client.post("/api/auth/start", json={"verifier_hash": hashlib.sha256(verifier.encode()).hexdigest()})
    assert r.status_code == 200, r.text
    login_id, user_code = r.json()["login_id"], r.json()["user_code"]
    r = client.get(f"/auth/discord/start?login_id={login_id}")
    assert r.status_code == 200, r.text
    r = client.post("/auth/discord/confirm", data={"login_id": login_id, "code": user_code})
    assert r.status_code == 303, r.text
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = client.get(f"/auth/discord/callback?code={discord_id}&state={state}")
    assert r.status_code == 302 and r.headers["location"] == "/auth/discord/done", r.text
    r = client.post("/api/auth/poll", json={"login_id": login_id, "verifier": verifier})
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    return r.json()["token"], r.json()["user"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_token(client):
    return login(client, "111")[0]


@pytest.fixture
def other_token(client):
    return login(client, "222")[0]


@pytest.fixture
def admin_token(client):
    return login(client, "999")[0]


@pytest.fixture
def publish_headers():
    return {"X-Publish-Token": PUBLISH_TOKEN}


def make_midi(n_notes: int = 20, tick: int = 240) -> bytes:
    """Petit fichier MIDI valide (type 1, 120 bpm) : n_notes noires successives ≈ n_notes/4 secondes."""
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    for i in range(n_notes):
        note = 60 + (i * 5) % 12
        track.append(mido.Message("note_on", note=note, velocity=80, time=0))
        track.append(mido.Message("note_off", note=note, velocity=0, time=tick))
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


@pytest.fixture
def midi_bytes():
    return make_midi()


@pytest.fixture
def bad_midi_bytes():
    return b"ceci n'est pas un fichier MIDI"
