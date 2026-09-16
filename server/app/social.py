"""Likes (morceaux et dessins) et score « tendance », partagés par la bibliothèque et la galerie.

Un like = une ligne `<kind>_likes(target, user)` (clé primaire composite) ; le compteur `likes` de la cible est
tenu à jour dans la même transaction, seulement quand la ligne est réellement insérée ou supprimée : liker deux
fois ou retirer un like absent ne change rien (idempotent).
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import db

# kind -> (table cible, table des likes, colonne de la cible). Constantes : jamais construites depuis la requête.
LIKE_TABLES = {
    "song": ("songs", "song_likes", "song_id"),
    "drawing": ("drawings", "drawing_likes", "drawing_id"),
}
TRENDING_POOL = 500          # tri « tendance » calculé sur les N plus récents (borne le travail)


def set_like(conn: db.Connection, kind: str, target_id: int, user_id: int, liked: bool) -> int:
    """Pose (liked=True) ou retire un like ; renvoie le compteur à jour. Idempotent."""
    table, likes_table, fk = LIKE_TABLES[kind]
    try:
        if liked:
            cur = conn.execute(f"INSERT INTO {likes_table} ({fk}, user_id, created_at) VALUES (?, ?, ?) "
                               f"ON CONFLICT ({fk}, user_id) DO NOTHING", (target_id, user_id, db.now_iso()))
            if cur.rowcount == 1:
                conn.execute(f"UPDATE {table} SET likes = likes + 1 WHERE id=?", (target_id,))
        else:
            cur = conn.execute(f"DELETE FROM {likes_table} WHERE {fk}=? AND user_id=?", (target_id, user_id))
            if cur.rowcount == 1:
                conn.execute(f"UPDATE {table} SET likes = CASE WHEN likes > 0 THEN likes - 1 ELSE 0 END WHERE id=?",
                             (target_id,))
        row = conn.execute(f"SELECT likes FROM {table} WHERE id=?", (target_id,)).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return int(row["likes"]) if row else 0


def liked_ids(conn: db.Connection, kind: str, user_id: int, ids: list[int]) -> set[int]:
    """Parmi `ids`, ceux que l'utilisateur a likés (une requête)."""
    if not ids:
        return set()
    _, likes_table, fk = LIKE_TABLES[kind]
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT {fk} AS tid FROM {likes_table} WHERE user_id=? AND {fk} IN ({marks})",
                        [user_id, *ids]).fetchall()
    return {int(r["tid"]) for r in rows}


def remove_user_likes(conn: db.Connection, user_id: int) -> None:
    """Retire tous les likes d'un compte et recalcule les compteurs touchés (suppression de compte). Sans commit."""
    for kind, (table, likes_table, fk) in LIKE_TABLES.items():
        targets = [int(r["tid"]) for r in
                   conn.execute(f"SELECT {fk} AS tid FROM {likes_table} WHERE user_id=?", (user_id,)).fetchall()]
        conn.execute(f"DELETE FROM {likes_table} WHERE user_id=?", (user_id,))
        for tid in targets:
            conn.execute(f"UPDATE {table} SET likes = (SELECT COUNT(*) FROM {likes_table} WHERE {fk}=?) WHERE id=?",
                         (tid, tid))


def _parse_iso(value) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def trending_score(downloads: int, likes: int, created_at, now: datetime | None = None) -> float:
    """(téléchargements + 3 × likes) / (âge en heures + 2) ^ 1,5 — un morceau récent et aimé passe devant."""
    now = now or datetime.now(timezone.utc)
    created = _parse_iso(created_at) or now
    age_h = max(0.0, (now - created).total_seconds() / 3600)
    return (int(downloads or 0) + 3 * int(likes or 0)) / (age_h + 2) ** 1.5
