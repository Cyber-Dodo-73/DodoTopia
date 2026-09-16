"""Bibliothèque enrichie : tags, instrument, source et licence validés, likes idempotents, tri tendance, filtres,
signalements généralisés et migration v2 -> v3."""
from datetime import datetime, timedelta, timezone

import pytest
from conftest import bearer, login, make_client, make_midi, make_settings

from app import db, social
from app.schemas import MetaError, normalize_source_url, normalize_tags


def upload(client, token, data, name="morceau.mid", **fields):
    return client.post("/api/songs", headers=bearer(token), files={"file": (name, data, "audio/midi")}, data=fields)


def approved_song(client, token, admin_token, n_notes=20, **fields):
    r = upload(client, token, make_midi(n_notes=n_notes), name=f"s{n_notes}-{len(fields)}.mid", **fields)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token)).status_code == 200
    return sid


# --- Validation des métadonnées ---------------------------------------------------------------------------------

def test_normalize_tags_unit():
    assert normalize_tags("Jeu vidéo, PIANO, piano , ") == ["jeu-video", "piano"]
    assert normalize_tags('["Noël", "calme"]') == ["noel", "calme"]
    assert normalize_tags(["Rock"]) == ["rock"]
    assert normalize_tags("") == [] and normalize_tags(None) == []
    for bad in ("metal", "piano,flute,lute,violin,harp,percussion,pop,rock,folk", "[1, 2]", "[pas du json",
                "x" * 30):
        with pytest.raises(MetaError):
            normalize_tags(bad)


def test_normalize_source_url_unit():
    assert normalize_source_url("https://onlinesequencer.net/123") == "https://onlinesequencer.net/123"
    assert normalize_source_url("  ") is None
    for bad in ("http://example.com/a", "javascript:alert(1)", "https://user:pw@example.com/", "https://exa mple.com",
                'https://example.com/"><script>', "https://localhost", "https://" + "a" * 600 + ".com"):
        with pytest.raises(MetaError):
            normalize_source_url(bad)


def test_upload_with_metadata(client, user_token, midi_bytes):
    r = upload(client, user_token, midi_bytes, tags="Piano, jeu vidéo", instrument="violin",
               source_url="https://onlinesequencer.net/42", source_name="Online Sequencer", license="cc")
    assert r.status_code == 201, r.text
    song = r.json()
    assert song["tags"] == ["piano", "jeu-video"] and song["instrument"] == "violin"
    assert song["source_url"] == "https://onlinesequencer.net/42" and song["source_name"] == "Online Sequencer"
    assert song["license"] == "cc" and song["likes"] == 0 and song["updated_at"] == song["created_at"]
    assert "liked_by_me" not in song


@pytest.mark.parametrize("field, value, code", [
    ("tags", "metal", "bad_tags"),
    ("instrument", "theremine", "bad_instrument"),
    ("source_url", "http://example.com/x.mid", "bad_source_url"),
    ("license", "gpl", "bad_license"),
])
def test_upload_rejects_bad_metadata(client, user_token, midi_bytes, settings, field, value, code):
    r = upload(client, user_token, midi_bytes, **{field: value})
    assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert not list(settings.songs_dir.glob("*.mid"))          # refus avant toute écriture


def test_patch_metadata(client, user_token, admin_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    r = client.patch(f"/api/songs/{sid}", headers=bearer(user_token),
                     json={"tags": ["Calme", "piano"], "license": "own", "source_name": "Moi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tags"] == ["calme", "piano"] and body["license"] == "own" and body["source_name"] == "Moi"
    assert body["title"] == "morceau"                          # champs absents inchangés
    r = client.patch(f"/api/songs/{sid}", headers=bearer(user_token), json={"source_url": "ftp://x.org/a"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_source_url"
    r = client.patch(f"/api/songs/{sid}", headers=bearer(user_token), json={"tags": [], "instrument": ""})
    assert r.json()["tags"] == [] and r.json()["instrument"] is None
    assert client.patch(f"/api/songs/{sid}", headers=bearer(admin_token),
                        json={"tags": "x" * 25}).status_code == 422


# --- Likes ------------------------------------------------------------------------------------------------------------

def test_likes_are_idempotent_and_counted(client, user_token, other_token, admin_token):
    sid = approved_song(client, user_token, admin_token)
    assert client.post(f"/api/songs/{sid}/like").status_code == 401
    for _ in range(3):
        r = client.post(f"/api/songs/{sid}/like", headers=bearer(other_token))
        assert r.status_code == 200 and r.json() == {"ok": True, "id": sid, "liked": True, "likes": 1}
    assert client.post(f"/api/songs/{sid}/like", headers=bearer(user_token)).json()["likes"] == 2
    assert client.get(f"/api/songs/{sid}").json()["likes"] == 2
    assert "liked_by_me" not in client.get(f"/api/songs/{sid}").json()
    assert client.get(f"/api/songs/{sid}", headers=bearer(other_token)).json()["liked_by_me"] is True
    for _ in range(2):
        r = client.delete(f"/api/songs/{sid}/like", headers=bearer(other_token))
        assert r.status_code == 200 and r.json()["likes"] == 1 and r.json()["liked"] is False
    items = client.get("/api/songs", headers=bearer(other_token)).json()["items"]
    assert items[0]["liked_by_me"] is False and items[0]["likes"] == 1
    assert client.get("/api/songs", headers=bearer(user_token)).json()["items"][0]["liked_by_me"] is True
    assert client.post("/api/songs/999/like", headers=bearer(user_token)).status_code == 404


def test_pending_song_cannot_be_liked(client, user_token, other_token, midi_bytes):
    sid = upload(client, user_token, midi_bytes).json()["id"]
    assert client.post(f"/api/songs/{sid}/like", headers=bearer(other_token)).status_code == 404
    assert client.post(f"/api/songs/{sid}/like", headers=bearer(user_token)).status_code == 409


def test_like_rate_limited_60_per_min(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as c:
        tok, _ = login(c, "111")
        admin, _ = login(c, "999")
        sid = approved_song(c, tok, admin)
        codes = [c.post(f"/api/songs/{sid}/like", headers=bearer(tok)).status_code for _ in range(61)]
        assert codes[:60] == [200] * 60 and codes[60] == 429


def test_account_deletion_removes_likes(client, user_token, other_token, admin_token):
    sid = approved_song(client, user_token, admin_token)
    client.post(f"/api/songs/{sid}/like", headers=bearer(other_token))
    client.post(f"/api/songs/{sid}/like", headers=bearer(admin_token))
    assert client.delete("/api/me", headers=bearer(other_token)).status_code == 200
    assert client.get(f"/api/songs/{sid}").json()["likes"] == 1


# --- Tri et filtres ----------------------------------------------------------------------------------------------------

def _set(settings, sid, **cols):
    conn = db.connect(settings)
    try:
        conn.execute(f"UPDATE songs SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", [*cols.values(), sid])
        conn.commit()
    finally:
        conn.close()


def test_trending_sort(client, user_token, admin_token, settings):
    now = datetime.now(timezone.utc)
    old = approved_song(client, user_token, admin_token, n_notes=20)
    fresh = approved_song(client, user_token, admin_token, n_notes=21)
    middle = approved_song(client, user_token, admin_token, n_notes=22)
    _set(settings, old, downloads=50, likes=0, created_at=(now - timedelta(hours=100)).isoformat(timespec="seconds"))
    _set(settings, fresh, downloads=5, likes=2, created_at=(now - timedelta(hours=1)).isoformat(timespec="seconds"))
    _set(settings, middle, downloads=0, likes=0, created_at=(now - timedelta(hours=10)).isoformat(timespec="seconds"))
    ids = [s["id"] for s in client.get("/api/songs?sort=trending").json()["items"]]
    assert ids == [fresh, old, middle]
    assert [s["id"] for s in client.get("/api/songs?sort=popular").json()["items"]][0] == old
    page2 = client.get("/api/songs?sort=trending&per_page=2&page=2").json()
    assert [s["id"] for s in page2["items"]] == [middle] and page2["total"] == 3 and page2["pages"] == 2
    assert social.trending_score(5, 2, now - timedelta(hours=1), now) == pytest.approx(11 / 3 ** 1.5)


def test_tag_and_instrument_filters(client, user_token, admin_token):
    a = approved_song(client, user_token, admin_token, n_notes=20, tags="piano,calme", instrument="piano")
    b = approved_song(client, user_token, admin_token, n_notes=21, tags="rock", instrument="violin")
    approved_song(client, user_token, admin_token, n_notes=22)
    assert [s["id"] for s in client.get("/api/songs?tag=piano").json()["items"]] == [a]
    assert [s["id"] for s in client.get("/api/songs?tag=ROCK").json()["items"]] == [b]
    assert [s["id"] for s in client.get("/api/songs?instrument=violin").json()["items"]] == [b]
    assert client.get("/api/songs?tag=piano&instrument=violin").json()["total"] == 0
    assert client.get("/api/songs?tag=%25").json()["total"] == 0          # hors liste blanche : aucun résultat
    assert client.get("/api/songs?instrument=x'%20OR%201=1").json()["total"] == 0
    assert client.get("/api/songs?sort=likes").status_code == 200


# --- Signalements généralisés -------------------------------------------------------------------------------------------

def test_song_report_has_target_type(client, user_token, other_token, admin_token):
    sid = approved_song(client, user_token, admin_token)
    r = client.post(f"/api/songs/{sid}/report", headers=bearer(other_token), json={"reason": "doublon"})
    assert r.status_code == 201 and r.json()["target_type"] == "song" and r.json()["target_id"] == sid
    items = client.get("/api/admin/reports?target_type=song", headers=bearer(admin_token)).json()["items"]
    assert len(items) == 1 and items[0]["target_type"] == "song" and items[0]["target_id"] == sid
    assert items[0]["song_title"] == items[0]["target_title"]
    assert client.get("/api/admin/reports?target_type=drawing", headers=bearer(admin_token)).json()["items"] == []
    assert client.get("/api/admin/reports?target_type=user", headers=bearer(admin_token)).status_code == 422


# --- Migration ---------------------------------------------------------------------------------------------------------

def test_sqlite_migration_v2_to_v3_keeps_songs_and_reports(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, DATABASE_URL="")
    full = list(db.MIGRATIONS)
    monkeypatch.setattr(db, "MIGRATIONS", full[:2])
    db.init(settings)
    conn = db.connect(settings)
    try:
        now = db.now_iso()
        for did in ("1", "2"):
            conn.execute("INSERT INTO users (discord_id, username, created_at, last_seen_at) VALUES (?, 'u', ?, ?)",
                         (did, now, now))
        conn.execute("INSERT INTO songs (sha256, title, size, duration_s, note_count, uploader_id, status, downloads, "
                     "created_at) VALUES (?, 'T', 10, 1.5, 12, 1, 'approved', 3, ?)", ("f" * 64, now))
        conn.execute("INSERT INTO reports (song_id, reporter_id, reason, created_at) VALUES (1, 2, 'r', ?)", (now,))
        conn.execute("INSERT INTO releases (version, published_at) VALUES ('1.0.0', ?)", (now,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(db, "MIGRATIONS", full)
    db.init(settings)
    conn = db.connect(settings)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == len(full)
        song = conn.execute("SELECT * FROM songs").fetchone()
        assert song["tags"] == "[]" and song["license"] == "unknown" and song["likes"] == 0
        assert song["updated_at"] == now and song["downloads"] == 3
        rep = conn.execute("SELECT * FROM reports").fetchone()
        assert rep["target_type"] == "song" and rep["song_id"] == 1 and rep["drawing_id"] is None
        assert conn.execute("SELECT announced_at FROM releases").fetchone()["announced_at"] is None
        with pytest.raises(db.IntegrityError):          # unicité (morceau, signaleur) conservée
            conn.execute("INSERT INTO reports (target_type, song_id, reporter_id, reason, created_at) "
                         "VALUES ('song', 1, 2, 'x', ?)", (now,))
        conn.rollback()
        conn.execute("DELETE FROM songs WHERE id=1")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0       # cascade conservée
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"songs_status_likes", "drawings_status_created", "song_likes_user"} <= names
    finally:
        conn.close()
