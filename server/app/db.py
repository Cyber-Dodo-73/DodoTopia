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

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from fastapi import Request

from .config import Settings

log = logging.getLogger("dodo.db")

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
    # v2 (chantier 6.1 sécurité) : device-flow (code utilisateur, essais, user_id sur le ticket : plus jamais
    # de jeton de session en clair), compteur de téléchargements par asset, signature Ed25519 du manifeste,
    # index des tris de la bibliothèque et des nettoyages, et `songs.uploader_id` rendu nullable pour
    # l'anonymisation à la suppression d'un compte (SQLite ne sait pas retirer un NOT NULL : table reconstruite,
    # clés étrangères désactivées le temps de la migration, voir `migrate`).
    {
        "postgres": """
    ALTER TABLE login_tickets ADD COLUMN user_code TEXT;
    ALTER TABLE login_tickets ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE login_tickets ADD COLUMN user_id INTEGER;
    ALTER TABLE release_assets ADD COLUMN downloads INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE releases ADD COLUMN signature TEXT;
    ALTER TABLE songs ALTER COLUMN uploader_id DROP NOT NULL;
    CREATE INDEX songs_status_created ON songs(status, created_at);
    CREATE INDEX songs_status_downloads ON songs(status, downloads);
    CREATE INDEX sessions_expires ON sessions(expires_at);
    CREATE INDEX login_tickets_created ON login_tickets(created_at);
    """,
        "sqlite": """
    ALTER TABLE login_tickets ADD COLUMN user_code TEXT;
    ALTER TABLE login_tickets ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE login_tickets ADD COLUMN user_id INTEGER;
    ALTER TABLE release_assets ADD COLUMN downloads INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE releases ADD COLUMN signature TEXT;
    CREATE TABLE songs_new (
        id            {ID},
        sha256        TEXT NOT NULL UNIQUE,
        title         TEXT NOT NULL,
        artist        TEXT,
        original_name TEXT,
        size          INTEGER NOT NULL,
        duration_s    {REAL} NOT NULL,
        note_count    INTEGER NOT NULL,
        uploader_id   INTEGER REFERENCES users(id),
        status        TEXT NOT NULL DEFAULT 'pending',
        reject_reason TEXT,
        reviewed_by   INTEGER REFERENCES users(id),
        reviewed_at   TEXT,
        downloads     INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL
    );
    INSERT INTO songs_new (id, sha256, title, artist, original_name, size, duration_s, note_count, uploader_id,
                           status, reject_reason, reviewed_by, reviewed_at, downloads, created_at)
        SELECT id, sha256, title, artist, original_name, size, duration_s, note_count, uploader_id,
               status, reject_reason, reviewed_by, reviewed_at, downloads, created_at FROM songs;
    DROP TABLE songs;
    ALTER TABLE songs_new RENAME TO songs;
    CREATE INDEX songs_status ON songs(status);
    CREATE INDEX songs_status_created ON songs(status, created_at);
    CREATE INDEX songs_status_downloads ON songs(status, downloads);
    CREATE INDEX sessions_expires ON sessions(expires_at);
    CREATE INDEX login_tickets_created ON login_tickets(created_at);
    """,
    },
    # v3 (bibliothèque enrichie, galerie, annonces) : tags JSON, instrument, source et licence, compteur de likes
    # et `updated_at` sur `songs` ; tables `song_likes`, `drawings`, `drawing_likes` ; `releases.announced_at` ;
    # `reports` généralisé (`target_type` song|drawing, `song_id` nullable, `drawing_id`). SQLite reconstruit
    # `reports` (NOT NULL à retirer), clés étrangères désactivées pendant la migration.
    {
        "postgres": """
    ALTER TABLE songs ADD COLUMN tags TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE songs ADD COLUMN instrument TEXT;
    ALTER TABLE songs ADD COLUMN source_url TEXT;
    ALTER TABLE songs ADD COLUMN source_name TEXT;
    ALTER TABLE songs ADD COLUMN license TEXT NOT NULL DEFAULT 'unknown';
    ALTER TABLE songs ADD COLUMN likes INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE songs ADD COLUMN updated_at TEXT;
    UPDATE songs SET updated_at = created_at;
    CREATE INDEX songs_status_likes ON songs(status, likes);
    ALTER TABLE releases ADD COLUMN announced_at TEXT;
    CREATE TABLE song_likes (
        song_id    INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (song_id, user_id)
    );
    CREATE INDEX song_likes_user ON song_likes(user_id);
    CREATE TABLE drawings (
        id            {ID},
        uploader_id   INTEGER REFERENCES users(id),
        title         TEXT NOT NULL,
        w             INTEGER NOT NULL,
        h             INTEGER NOT NULL,
        png_sha256    TEXT NOT NULL UNIQUE,
        png_size      INTEGER NOT NULL,
        cells_json_gz TEXT,
        status        TEXT NOT NULL DEFAULT 'pending',
        reject_reason TEXT,
        likes         INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL,
        reviewed_at   TEXT,
        reviewed_by   INTEGER REFERENCES users(id)
    );
    CREATE INDEX drawings_status_created ON drawings(status, created_at);
    CREATE INDEX drawings_status_likes ON drawings(status, likes);
    CREATE TABLE drawing_likes (
        drawing_id INTEGER NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (drawing_id, user_id)
    );
    CREATE INDEX drawing_likes_user ON drawing_likes(user_id);
    ALTER TABLE reports ADD COLUMN target_type TEXT NOT NULL DEFAULT 'song';
    ALTER TABLE reports ALTER COLUMN song_id DROP NOT NULL;
    ALTER TABLE reports ADD COLUMN drawing_id INTEGER REFERENCES drawings(id) ON DELETE CASCADE;
    ALTER TABLE reports ADD CONSTRAINT reports_drawing_reporter UNIQUE (drawing_id, reporter_id);
    """,
        "sqlite": """
    ALTER TABLE songs ADD COLUMN tags TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE songs ADD COLUMN instrument TEXT;
    ALTER TABLE songs ADD COLUMN source_url TEXT;
    ALTER TABLE songs ADD COLUMN source_name TEXT;
    ALTER TABLE songs ADD COLUMN license TEXT NOT NULL DEFAULT 'unknown';
    ALTER TABLE songs ADD COLUMN likes INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE songs ADD COLUMN updated_at TEXT;
    UPDATE songs SET updated_at = created_at;
    CREATE INDEX songs_status_likes ON songs(status, likes);
    ALTER TABLE releases ADD COLUMN announced_at TEXT;
    CREATE TABLE song_likes (
        song_id    INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (song_id, user_id)
    );
    CREATE INDEX song_likes_user ON song_likes(user_id);
    CREATE TABLE drawings (
        id            {ID},
        uploader_id   INTEGER REFERENCES users(id),
        title         TEXT NOT NULL,
        w             INTEGER NOT NULL,
        h             INTEGER NOT NULL,
        png_sha256    TEXT NOT NULL UNIQUE,
        png_size      INTEGER NOT NULL,
        cells_json_gz TEXT,
        status        TEXT NOT NULL DEFAULT 'pending',
        reject_reason TEXT,
        likes         INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL,
        reviewed_at   TEXT,
        reviewed_by   INTEGER REFERENCES users(id)
    );
    CREATE INDEX drawings_status_created ON drawings(status, created_at);
    CREATE INDEX drawings_status_likes ON drawings(status, likes);
    CREATE TABLE drawing_likes (
        drawing_id INTEGER NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (drawing_id, user_id)
    );
    CREATE INDEX drawing_likes_user ON drawing_likes(user_id);
    CREATE TABLE reports_new (
        id          {ID},
        target_type TEXT NOT NULL DEFAULT 'song',
        song_id     INTEGER REFERENCES songs(id) ON DELETE CASCADE,
        drawing_id  INTEGER REFERENCES drawings(id) ON DELETE CASCADE,
        reporter_id INTEGER NOT NULL REFERENCES users(id),
        reason      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        resolved_at TEXT,
        resolved_by INTEGER REFERENCES users(id),
        resolution  TEXT,
        UNIQUE(song_id, reporter_id),
        UNIQUE(drawing_id, reporter_id)
    );
    INSERT INTO reports_new (id, target_type, song_id, reporter_id, reason, created_at, resolved_at, resolved_by,
                             resolution)
        SELECT id, 'song', song_id, reporter_id, reason, created_at, resolved_at, resolved_by, resolution FROM reports;
    DROP TABLE reports;
    ALTER TABLE reports_new RENAME TO reports;
    """,
    },
    # v4 (usage réel) : part des téléchargements qui sont des mises à jour automatiques (`?via=update`), et
    # installations actives : une ligne par jour et par empreinte d'installation (condensé salé de l'adresse IP,
    # jamais l'adresse), avec la version et la plateforme vues en dernier ce jour-là. Purgée après PINGS_KEEP_DAYS.
    """
    ALTER TABLE release_assets ADD COLUMN updates INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE install_pings (
        day      TEXT NOT NULL,
        fp       TEXT NOT NULL,
        version  TEXT NOT NULL,
        platform TEXT NOT NULL,
        PRIMARY KEY (day, fp)
    );
    CREATE INDEX install_pings_day ON install_pings(day);
    """,
]

# Postgres seulement, hors numérotation : recherche par trigrammes (`LIKE '%mot%'` sur titre/artiste). L'extension
# pg_trgm est « trusted » (Postgres 13+) : le propriétaire de la base peut la créer. Si elle manque sur
# l'hébergement, l'API fonctionne quand même (LIKE séquentiel) : l'échec est journalisé, jamais bloquant.
POSTGRES_OPTIONAL = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS songs_title_trgm ON songs USING GIN (LOWER(title) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS songs_artist_trgm ON songs USING GIN (LOWER(artist) gin_trgm_ops)",
]

TABLES = ("install_pings", "release_assets", "releases", "song_likes", "drawing_likes", "reports", "drawings", "songs", "login_tickets",
          "sessions", "users", "schema_version")

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
            # Toute requete, meme un SELECT, ouvre une transaction : sans ce rollback la connexion
            # retourne au pool en etat INTRANS (psycopg le signale a chaque requete et la solde lui-meme),
            # ce qui garde un instantane ouvert cote PostgreSQL. Les ecritures ont deja appele commit().
            try:
                self._raw.rollback()
            except Exception:  # noqa - connexion deja cassee : le pool la remplacera
                pass
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
                    self.url, min_size=1, max_size=16, timeout=30, open=False,
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
        """Applique les migrations manquantes ; renvoie la version finale du schéma.

        Une migration est un script SQL, ou un dict {dialecte: script} quand les deux bases divergent.
        Sous SQLite les clés étrangères sont désactivées pendant les migrations : une table reconstruite
        (DROP + RENAME) déclencherait sinon les `ON DELETE CASCADE` des tables qui la référencent.
        """
        conn = self.connect()
        try:
            if self.dialect == "sqlite":
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=OFF")
            version = self.schema_version(conn)
            for i, mig in enumerate(MIGRATIONS[version:], start=version + 1):
                sql = mig[self.dialect] if isinstance(mig, dict) else mig
                script = ddl(sql, self.dialect)
                if self.dialect == "sqlite":
                    conn._raw.executescript(script)
                else:
                    conn._raw.execute(script)
                conn.execute("DELETE FROM schema_version")
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
                conn.commit()
                version = i
            if self.dialect == "sqlite":
                conn.execute("PRAGMA foreign_keys=ON")
            else:
                self._postgres_optional(conn)
            return version
        finally:
            conn.close()

    def _postgres_optional(self, conn: Connection) -> None:
        """Index facultatifs (pg_trgm) : chaque échec est journalisé et n'empêche pas le démarrage."""
        for sql in POSTGRES_OPTIONAL:
            try:
                conn.execute(sql)
                conn.commit()
            except Exception as e:  # noqa - extension absente ou droits insuffisants : LIKE sans index
                conn.rollback()
                log.warning("index optionnel ignoré (%s) : %s", sql.split(" ON ")[0], e)
                return

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
    for d in (settings.data_dir, settings.songs_dir, settings.tmp_dir, settings.releases_dir, settings.drawings_dir,
              settings.import_cache_dir, settings.og_cache_dir):
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
           "now_iso", "iso_in", "to_pg", "dialect", "MIGRATIONS", "POSTGRES_OPTIONAL", "TABLES"]
