"""Couche base de données à deux dialectes derrière une même API.

- `DATABASE_URL` vide (défaut)                 -> SQLite fichier `DATA_DIR/dodo.db` (développement, tests locaux).
- `DATABASE_URL=postgres://…` / `postgresql://…` -> PostgreSQL via psycopg 3 (pool `psycopg_pool`).

Règles pour les modules :
- paramètres écrits avec `?` (traduits en `%s` pour psycopg) ;
- les lignes sont des `Row` (dict avec accès positionnel `row[0]`) ;
- `INSERT … RETURNING id` puis `fetchone()["id"]` au lieu de `lastrowid` ;
- booléens stockés en entiers 0/1 dans les deux dialectes ; horodatages en texte ISO 8601 UTC (comparables) ;
- `LOWER(col) LIKE LOWER(?)` pour les recherches insensibles à la casse ;
- migrations dans `MIGRATIONS`, version courante dans la table `schema_version`.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from fastapi import Request

from .config import Settings

# --- Schéma ------------------------------------------------------------------------
# {ID} : clé primaire auto-incrémentée ; {REAL} : flottant double précision.

MIGRATIONS = [
    # v1 : schéma initial
    """
    CREATE TABLE users (
        id           {ID},
        discord_id   TEXT NOT NULL UNIQUE,
        username     TEXT NOT NULL,
        avatar_url   TEXT,
        is_admin     INTEGER NOT NULL DEFAULT 0,
        banned       INTEGER NOT NULL DEFAULT 0,
        created_at   TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );
    CREATE TABLE sessions (
        token_hash   TEXT PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at   TEXT NOT NULL,
        expires_at   TEXT NOT NULL,
        last_used_at TEXT NOT NULL
    );
    CREATE INDEX sessions_user ON sessions(user_id);
    CREATE TABLE login_tickets (
        id            TEXT PRIMARY KEY,
        verifier_hash TEXT NOT NULL,
        state         TEXT NOT NULL UNIQUE,
        status        TEXT NOT NULL DEFAULT 'pending',   -- pending | ok | error | used
        token         TEXT,
        error         TEXT,
        created_at    TEXT NOT NULL
    );
    CREATE TABLE songs (
        id            {ID},
        sha256        TEXT NOT NULL UNIQUE,
        title         TEXT NOT NULL,
        artist        TEXT,
        original_name TEXT,
        size          INTEGER NOT NULL,
        duration_s    {REAL} NOT NULL,
        note_count    INTEGER NOT NULL,
        uploader_id   INTEGER NOT NULL REFERENCES users(id),
        status        TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
        reject_reason TEXT,
        reviewed_by   INTEGER REFERENCES users(id),
        reviewed_at   TEXT,
        downloads     INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL
    );
    CREATE INDEX songs_status ON songs(status);
    CREATE TABLE reports (
        id          {ID},
        song_id     INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
        reporter_id INTEGER NOT NULL REFERENCES users(id),
        reason      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        resolved_at TEXT,
        resolved_by INTEGER REFERENCES users(id),
        resolution  TEXT,
        UNIQUE(song_id, reporter_id)
    );
    CREATE TABLE releases (
        version      TEXT PRIMARY KEY,
        notes        TEXT,
        mandatory    INTEGER NOT NULL DEFAULT 0,
        published_at TEXT                                -- NULL tant que non publiée
    );
    CREATE TABLE release_assets (
        version  TEXT NOT NULL REFERENCES releases(version) ON DELETE CASCADE,
        platform TEXT NOT NULL,
        filename TEXT NOT NULL,
        sha256   TEXT NOT NULL,
        size     INTEGER NOT NULL,
        PRIMARY KEY (version, platform)
    );
    """,
]

TABLES = ("release_assets", "releases", "reports", "songs", "login_tickets", "sessions", "users", "schema_version")

_DDL_TYPES = {
    "sqlite": {"ID": "INTEGER PRIMARY KEY AUTOINCREMENT", "REAL": "REAL"},
    "postgres": {"ID": "SERIAL PRIMARY KEY", "REAL": "DOUBLE PRECISION"},
}


def ddl(sql: str, dialect: str) -> str:
    return sql.replace("{ID}", _DDL_TYPES[dialect]["ID"]).replace("{REAL}", _DDL_TYPES[dialect]["REAL"])


# --- Horodatages -------------------------------------------------------------------

def now_iso() -> str:
    """Horodatage UTC ISO 8601 à la seconde (comparable comme texte)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso_in(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


# --- Lignes, erreurs ------------------------------------------------------------------

class Row(dict):
    """Ligne = dict {colonne: valeur} ; `row[0]` accepté pour les agrégats (`SELECT COUNT(*)`)."""
    __slots__ = ()

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return dict.__getitem__(self, key)


class IntegrityError(Exception):
    """Contrainte UNIQUE / clé étrangère violée (même exception pour les deux dialectes)."""


def _sqlite_row(cursor: sqlite3.Cursor, values: tuple) -> Row:
    return Row(zip((d[0] for d in cursor.description), values))


def _pg_row_factory(cursor):
    desc = cursor.description
    if desc is None:
        return lambda values: Row()
    names = [d.name for d in desc]
    return lambda values: Row(zip(names, values))


@lru_cache(maxsize=512)
def to_pg(sql: str) -> str:
    """`?` -> `%s` hors des chaînes entre apostrophes."""
    out, in_str = [], False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
        if ch == "?" and not in_str:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


# --- Connexion ----------------------------------------------------------------------

class Cursor:
    def __init__(self, raw):
        self._c = raw

    def fetchone(self) -> Row | None:
        return self._c.fetchone()

    def fetchall(self) -> list[Row]:
        return list(self._c.fetchall())

    def __iter__(self) -> Iterator[Row]:
        return iter(self._c.fetchall())

    @property
    def rowcount(self) -> int:
        return self._c.rowcount


class Connection:
    """Connexion unifiée : `execute(sql, params)` avec `?`, `commit`, `rollback`, `transaction()`, `close`."""

    def __init__(self, raw, dialect: str, release=None):
        self._raw = raw
        self.dialect = dialect
        self._release = release      # rend la connexion au pool (Postgres) ou la ferme (SQLite)
        self._closed = False

    def execute(self, sql: str, params: tuple | list = ()) -> Cursor:
        params = tuple(params)
        try:
            if self.dialect == "postgres":
                cur = self._raw.execute(to_pg(sql), params or None)
            else:
                cur = self._raw.execute(sql, params)
        except sqlite3.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        except Exception as e:  # psycopg importé paresseusement : on teste par le nom de la classe
            if _is_pg_integrity_error(e):
                raise IntegrityError(str(e)) from e
            raise
        return Cursor(cur)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    @contextmanager
    def transaction(self):
        """`with conn.transaction(): …` -> commit à la sortie, rollback si exception."""
        try:
            yield self
        except BaseException:
            self.rollback()
            raise
        else:
            self.commit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._release is not None:
            self._release(self._raw)
        else:
            self._raw.close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _is_pg_integrity_error(e: Exception) -> bool:
    for klass in type(e).__mro__:
        if klass.__module__.startswith("psycopg") and klass.__name__ == "IntegrityError":
            return True
    return False


# --- Base ---------------------------------------------------------------------------

class Database:
    """Une base (SQLite fichier ou Postgres + pool). Une instance par URL / chemin, partagée par les apps."""

    def __init__(self, url: str, sqlite_path: Path):
        self.url = (url or "").strip()
        if self.url.startswith(("postgres://", "postgresql://")):
            self.dialect = "postgres"
        elif self.url:
            raise ValueError(f"DATABASE_URL non reconnue : {self.url!r} (attendu postgresql://… ou vide pour SQLite)")
        else:
            self.dialect = "sqlite"
        self.sqlite_path = sqlite_path
        self._pool = None
        self._lock = threading.Lock()

    # --- connexions ---
    def _pg_pool(self):
        with self._lock:
            if self._pool is None:
                import psycopg_pool  # import paresseux : SQLite fonctionne sans psycopg

                self._pool = psycopg_pool.ConnectionPool(
                    self.url, min_size=1, max_size=8, timeout=30, open=False,
                    kwargs={"row_factory": _pg_row_factory},
                )
                self._pool.open(wait=True, timeout=30)
            return self._pool

    def connect(self) -> Connection:
        if self.dialect == "postgres":
            pool = self._pg_pool()
            return Connection(pool.getconn(), "postgres", release=pool.putconn)
        raw = sqlite3.connect(self.sqlite_path, timeout=10, check_same_thread=False)
        raw.row_factory = _sqlite_row
        raw.execute("PRAGMA foreign_keys=ON")
        return Connection(raw, "sqlite")

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None

    # --- migrations ---
    def schema_version(self, conn: Connection) -> int:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        conn.commit()
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return int(row["version"]) if row else 0

    def migrate(self) -> int:
        """Applique les migrations manquantes ; renvoie la version finale du schéma."""
        conn = self.connect()
        try:
            if self.dialect == "sqlite":
                conn.execute("PRAGMA journal_mode=WAL")
            version = self.schema_version(conn)
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                script = ddl(sql, self.dialect)
                if self.dialect == "sqlite":
                    conn._raw.executescript(script)
                else:
                    conn._raw.execute(script)
                conn.execute("DELETE FROM schema_version")
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
                conn.commit()
                version = i
            return version
        finally:
            conn.close()

    def drop_all(self) -> None:
        """Supprime toutes les tables (tests uniquement)."""
        conn = self.connect()
        try:
            for t in TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {t}" + (" CASCADE" if self.dialect == "postgres" else ""))
            conn.commit()
        finally:
            conn.close()


_DATABASES: dict[str, Database] = {}
_DATABASES_LOCK = threading.Lock()


def database(settings: Settings) -> Database:
    """Base associée aux réglages (une instance par URL Postgres ou par fichier SQLite)."""
    key = settings.DATABASE_URL.strip() or f"sqlite:{settings.db_path}"
    with _DATABASES_LOCK:
        d = _DATABASES.get(key)
        if d is None:
            d = _DATABASES[key] = Database(settings.DATABASE_URL, settings.db_path)
        return d


def connect(settings: Settings) -> Connection:
    return database(settings).connect()


def init(settings: Settings) -> None:
    """Crée les dossiers du volume et applique les migrations manquantes."""
    for d in (settings.data_dir, settings.songs_dir, settings.tmp_dir, settings.releases_dir):
        d.mkdir(parents=True, exist_ok=True)
    database(settings).migrate()


def get_db(request: Request) -> Iterator[Connection]:
    """Dépendance FastAPI : une connexion par requête, rendue/fermée à la fin."""
    conn = connect(request.app.state.settings)
    try:
        yield conn
    finally:
        conn.close()


def dialect(settings: Settings) -> str:
    return database(settings).dialect


__all__ = ["Connection", "Cursor", "Row", "IntegrityError", "Database", "database", "connect", "init", "get_db",
           "now_iso", "iso_in", "to_pg", "dialect", "MIGRATIONS", "TABLES"]
