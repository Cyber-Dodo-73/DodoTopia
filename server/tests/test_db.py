"""Couche db : traduction des paramètres, Row, RETURNING, IntegrityError, migrations, dans les deux dialectes."""
import pytest
from conftest import DATABASE_URL, make_settings, requires_postgres

from app import db


def test_to_pg_translation():
    assert db.to_pg("SELECT * FROM t WHERE a=? AND b=?") == "SELECT * FROM t WHERE a=%s AND b=%s"
    assert db.to_pg("SELECT '?' AS q, x FROM t WHERE y=?") == "SELECT '?' AS q, x FROM t WHERE y=%s"
    assert db.ddl("id {ID}, v {REAL}", "postgres") == "id SERIAL PRIMARY KEY, v DOUBLE PRECISION"
    assert db.ddl("id {ID}, v {REAL}", "sqlite") == "id INTEGER PRIMARY KEY AUTOINCREMENT, v REAL"


def test_row_access():
    r = db.Row([("id", 3), ("n", 7)])
    assert r["id"] == 3 and r[0] == 3 and r[1] == 7 and dict(r) == {"id": 3, "n": 7} and "n" in r.keys()


def _exercise(settings):
    db.init(settings)
    db.init(settings)   # idempotent (schema_version déjà à jour)
    conn = db.connect(settings)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == len(db.MIGRATIONS)
        cur = conn.execute("INSERT INTO users (discord_id, username, created_at, last_seen_at) "
                           "VALUES (?, ?, ?, ?) RETURNING id", ("42", "Zed", db.now_iso(), db.now_iso()))
        uid = cur.fetchone()["id"]
        conn.commit()
        assert uid == 1
        with pytest.raises(db.IntegrityError):
            conn.execute("INSERT INTO users (discord_id, username, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                         ("42", "Dup", db.now_iso(), db.now_iso()))
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        row = conn.execute("SELECT * FROM users WHERE LOWER(username) LIKE LOWER(?)", ("%ZED%",)).fetchone()
        assert row["discord_id"] == "42" and row["banned"] == 0 and row["avatar_url"] is None
        with conn.transaction():
            conn.execute("UPDATE users SET banned=1 WHERE id=?", (uid,))
        assert conn.execute("SELECT banned FROM users WHERE id=?", (uid,)).fetchone()["banned"] == 1
        with pytest.raises(RuntimeError):
            with conn.transaction():
                conn.execute("UPDATE users SET banned=0 WHERE id=?", (uid,))
                raise RuntimeError("annule")
        assert conn.execute("SELECT banned FROM users WHERE id=?", (uid,)).fetchone()["banned"] == 1
        rows = [r["id"] for r in conn.execute("SELECT id FROM users")]
        assert rows == [uid]
    finally:
        conn.close()


def test_sqlite_layer(tmp_path):
    settings = make_settings(tmp_path, DATABASE_URL="")
    assert db.dialect(settings) == "sqlite"
    _exercise(settings)
    assert settings.db_path.is_file()


@requires_postgres
def test_postgres_layer(tmp_path):
    settings = make_settings(tmp_path)
    assert db.dialect(settings) == "postgres" and settings.DATABASE_URL == DATABASE_URL
    _exercise(settings)
    assert not settings.db_path.exists()


def test_bad_url():
    with pytest.raises(ValueError):
        db.Database("mysql://x", db.Path("x.db"))


def test_sqlite_migration_v1_to_v2_keeps_data_and_reports(tmp_path, monkeypatch):
    """Une base au schéma v1 (avant le chantier sécurité) migre sans perdre ni morceaux ni signalements :
    la reconstruction de `songs` ne doit pas déclencher le ON DELETE CASCADE de `reports`."""
    settings = make_settings(tmp_path, DATABASE_URL="")
    full = list(db.MIGRATIONS)
    monkeypatch.setattr(db, "MIGRATIONS", full[:1])
    db.init(settings)
    conn = db.connect(settings)
    try:
        now = db.now_iso()
        conn.execute("INSERT INTO users (discord_id, username, created_at, last_seen_at) VALUES ('1', 'a', ?, ?)",
                     (now, now))
        conn.execute("INSERT INTO users (discord_id, username, created_at, last_seen_at) VALUES ('2', 'b', ?, ?)",
                     (now, now))
        conn.execute("INSERT INTO songs (sha256, title, artist, size, duration_s, note_count, uploader_id, status, "
                     "downloads, created_at) VALUES (?, 'T', 'A', 10, 1.5, 12, 1, 'approved', 7, ?)", ("f" * 64, now))
        conn.execute("INSERT INTO reports (song_id, reporter_id, reason, created_at) VALUES (1, 2, 'r', ?)", (now,))
        conn.execute("INSERT INTO login_tickets (id, verifier_hash, state, created_at) VALUES ('t', 'h', 's', ?)",
                     (now,))
        conn.commit()
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 1
    finally:
        conn.close()
    monkeypatch.setattr(db, "MIGRATIONS", full)
    db.init(settings)
    conn = db.connect(settings)
    try:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == len(full)
        song = conn.execute("SELECT * FROM songs").fetchone()
        assert song["id"] == 1 and song["title"] == "T" and song["downloads"] == 7 and song["uploader_id"] == 1
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1
        t = conn.execute("SELECT * FROM login_tickets").fetchone()
        assert t["attempts"] == 0 and t["user_code"] is None and t["user_id"] is None
        # uploader_id est devenu nullable, les clés étrangères sont de nouveau actives
        conn.execute("UPDATE songs SET uploader_id=NULL WHERE id=1")
        conn.commit()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(db.IntegrityError):
            conn.execute("INSERT INTO songs (sha256, title, size, duration_s, note_count, uploader_id, created_at) "
                         "VALUES (?, 'X', 1, 1, 1, 999, ?)", ("e" * 64, db.now_iso()))
        conn.rollback()
        conn.execute("DELETE FROM songs WHERE id=1")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0     # cascade normale conservée
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"songs_status", "songs_status_created", "songs_status_downloads", "sessions_expires",
                "login_tickets_created"} <= names
    finally:
        conn.close()
