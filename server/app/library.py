"""Bibliothèque MIDI en ligne : dépôt par les connectés, modération admin, téléchargement public."""
from __future__ import annotations

import hashlib
import io
import math
import os
import re
from pathlib import Path

import mido
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from . import db
from .auth import api_error, get_current_user, get_optional_user, is_admin, require_admin, settings_of
from .config import Settings
from .ratelimit import limit
from .schemas import RejectIn, ReportIn, ResolveIn, SongPatch

router = APIRouter()

CHUNK = 64 * 1024

# Même nettoyage de titre que core.clean_title dans l'app.
_JUNK = re.compile(r"\[.*?\]|\(.*?\)|\b(?:www\.)?[a-z0-9]+\.(?:com|net|org|fr|io)\b|"
                   r"\b(?:anonymous|midi|mid|karaoke|k|converted by \w+)\b|\b\d{8,}\b", re.I)


def clean_title(filename: str) -> str:
    """'The-Weeknd-Blinding-Lights-Anonymous-2020...-nonstop2k.com.mid' -> 'The Weeknd Blinding Lights'."""
    name = os.path.basename(filename.replace("\\", "/"))
    while True:
        base, ext = os.path.splitext(name)
        if ext.lower() in (".mid", ".midi") and base:
            name = base
        else:
            break
    name = re.sub(r"[_\-–—]+", " ", name)
    name = _JUNK.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" -_.,")
    return name or os.path.splitext(os.path.basename(filename))[0] or "Sans titre"


class MidiError(ValueError):
    pass


def validate_midi(data: bytes) -> dict:
    """Vérifie un fichier MIDI et renvoie {duration_s, note_count}. MidiError si refusé."""
    try:
        mid = mido.MidiFile(file=io.BytesIO(data))
    except Exception as e:  # mido lève un peu de tout
        raise MidiError(f"Fichier MIDI illisible ({type(e).__name__}).")
    if mid.type not in (0, 1):
        raise MidiError("Seuls les fichiers MIDI de type 0 ou 1 sont acceptés.")
    try:
        duration = float(mid.length)
    except Exception:
        raise MidiError("Durée du fichier illisible.")
    if not math.isfinite(duration) or duration < 1:
        raise MidiError("Morceau trop court (moins d'une seconde).")
    if duration > 30 * 60:
        raise MidiError("Morceau trop long (plus de 30 minutes).")
    notes = 0
    for track in mid.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel != 9:
                notes += 1
    if notes < 10:
        raise MidiError("Trop peu de notes (au moins 10 notes hors percussions).")
    return {"duration_s": round(duration, 2), "note_count": notes}


async def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Lit le fichier par blocs et refuse (413) dès que la taille dépasse max_bytes, sans se fier au Content-Length."""
    buf = bytearray()
    while True:
        chunk = await upload.read(CHUNK)
        if not chunk:
            break
        buf += chunk
        if len(buf) > max_bytes:
            raise api_error(413, "too_large", f"Fichier trop gros (max {max_bytes // 1024} Ko).")
    return bytes(buf)


def song_path(settings: Settings, sha: str) -> Path:
    return settings.songs_dir / f"{sha}.mid"


def song_public(row: db.Row, settings: Settings) -> dict:
    return {
        "id": row["id"],
        "sha256": row["sha256"],
        "title": row["title"],
        "artist": row["artist"],
        "original_name": row["original_name"],
        "size": row["size"],
        "duration_s": row["duration_s"],
        "note_count": row["note_count"],
        "uploader_id": row["uploader_id"],
        "uploader_name": row["uploader_name"] if "uploader_name" in row.keys() else None,
        "status": row["status"],
        "reject_reason": row["reject_reason"],
        "downloads": row["downloads"],
        "created_at": row["created_at"],
        "download_url": f"{settings.public_url}/api/songs/{row['id']}/download",
    }


SONG_SELECT = "SELECT s.*, u.username AS uploader_name FROM songs s JOIN users u ON u.id = s.uploader_id"


def fetch_song(conn: db.Connection, song_id: int) -> db.Row:
    row = conn.execute(f"{SONG_SELECT} WHERE s.id=?", (song_id,)).fetchone()
    if row is None:
        raise api_error(404, "not_found", "Morceau introuvable.")
    return row


def can_see(row: db.Row, user: db.Row | None, settings: Settings) -> bool:
    if row["status"] == "approved":
        return True
    return user is not None and (user["id"] == row["uploader_id"] or is_admin(user, settings))


# --- Public ----------------------------------------------------------------------

@router.get("/api/songs")
def list_songs(request: Request, q: str = "", page: int = 1, per_page: int = 50, sort: str = "recent",
               conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    page = max(1, page)
    per_page = max(1, min(100, per_page))
    order = {"recent": "s.created_at DESC, s.id DESC", "popular": "s.downloads DESC, s.id DESC",
             "title": "LOWER(s.title) ASC, s.id ASC"}.get(sort, "s.created_at DESC, s.id DESC")
    where, args = ["s.status='approved'"], []
    if q.strip():
        like = f"%{q.strip()}%"
        where.append("(LOWER(s.title) LIKE LOWER(?) OR LOWER(s.artist) LIKE LOWER(?) OR LOWER(s.original_name) LIKE LOWER(?))")
        args += [like, like, like]
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM songs s WHERE {w}", args).fetchone()[0]
    rows = conn.execute(f"{SONG_SELECT} WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?",
                        args + [per_page, (page - 1) * per_page]).fetchall()
    return {"items": [song_public(r, settings) for r in rows], "page": page, "per_page": per_page,
            "total": total, "pages": max(1, math.ceil(total / per_page))}


@router.get("/api/songs/{song_id}")
def get_song(song_id: int, request: Request, user=Depends(get_optional_user),
             conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_song(conn, song_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Morceau introuvable.")
    return song_public(row, settings)


@router.get("/api/songs/{song_id}/download")
def download_song(song_id: int, request: Request, user=Depends(get_optional_user),
                  conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_song(conn, song_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Morceau introuvable.")
    path = song_path(settings, row["sha256"])
    if not path.is_file():
        raise api_error(404, "not_found", "Fichier manquant sur le serveur.")
    if row["status"] == "approved":
        conn.execute("UPDATE songs SET downloads = downloads + 1 WHERE id=?", (song_id,))
        conn.commit()
    safe = re.sub(r"[^A-Za-z0-9 ._-]+", "", row["title"]).strip() or "song"
    return FileResponse(path, media_type="audio/midi", filename=f"{safe}.mid",
                        headers={"ETag": f'"{row["sha256"]}"', "X-Sha256": row["sha256"]})


# --- Connectés -------------------------------------------------------------------

@router.post("/api/songs", status_code=201, dependencies=[Depends(limit("upload", 10, 3600, by="user"))])
async def upload_song(request: Request, file: UploadFile = File(...), title: str = Form(""), artist: str = Form(""),
                      user=Depends(get_current_user), conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    data = await read_upload(file, settings.MAX_MIDI_BYTES)
    if not data:
        raise api_error(422, "invalid_midi", "Fichier vide.")
    try:
        info = validate_midi(data)
    except MidiError as e:
        raise api_error(422, "invalid_midi", str(e))
    sha = hashlib.sha256(data).hexdigest()
    existing = conn.execute("SELECT id, status FROM songs WHERE sha256=?", (sha,)).fetchone()
    if existing is not None:
        raise api_error(409, "duplicate", "Ce morceau existe déjà dans la bibliothèque.", existing_id=existing["id"],
                        existing_status=existing["status"])
    original = (file.filename or "morceau.mid")[:200]
    title = title.strip()[:120] or clean_title(original)
    artist = artist.strip()[:120] or None
    path = song_path(settings, sha)
    path.write_bytes(data)
    cur = conn.execute(
        """INSERT INTO songs (sha256, title, artist, original_name, size, duration_s, note_count, uploader_id,
                              status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?) RETURNING id""",
        (sha, title, artist, original, len(data), info["duration_s"], info["note_count"], user["id"], db.now_iso()),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    return song_public(fetch_song(conn, new_id), settings)


def _owner_or_admin(row: db.Row, user: db.Row, settings: Settings) -> None:
    if is_admin(user, settings):
        return
    if row["uploader_id"] != user["id"]:
        raise api_error(403, "forbidden", "Ce morceau ne t'appartient pas.")
    if row["status"] != "pending":
        raise api_error(403, "forbidden", "Un morceau déjà validé ne peut plus être modifié.")


@router.patch("/api/songs/{song_id}")
def patch_song(song_id: int, body: SongPatch, request: Request, user=Depends(get_current_user),
               conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_song(conn, song_id)
    _owner_or_admin(row, user, settings)
    if body.title is not None:
        conn.execute("UPDATE songs SET title=? WHERE id=?", (body.title.strip(), song_id))
    if body.artist is not None:
        conn.execute("UPDATE songs SET artist=? WHERE id=?", (body.artist.strip() or None, song_id))
    conn.commit()
    return song_public(fetch_song(conn, song_id), settings)


def delete_song(conn: db.Connection, settings: Settings, row: db.Row) -> None:
    conn.execute("DELETE FROM songs WHERE id=?", (row["id"],))
    conn.commit()
    try:
        song_path(settings, row["sha256"]).unlink()
    except OSError:
        pass


@router.delete("/api/songs/{song_id}")
def remove_song(song_id: int, request: Request, user=Depends(get_current_user),
                conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_song(conn, song_id)
    _owner_or_admin(row, user, settings)
    delete_song(conn, settings, row)
    return {"ok": True}


@router.post("/api/songs/{song_id}/report", status_code=201,
             dependencies=[Depends(limit("report", 20, 86400, by="user"))])
def report_song(song_id: int, body: ReportIn, request: Request, user=Depends(get_current_user),
                conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_song(conn, song_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Morceau introuvable.")
    try:
        cur = conn.execute("INSERT INTO reports (song_id, reporter_id, reason, created_at) VALUES (?, ?, ?, ?) "
                           "RETURNING id", (song_id, user["id"], body.reason.strip(), db.now_iso()))
        report_id = cur.fetchone()["id"]
        conn.commit()
    except db.IntegrityError:
        conn.rollback()
        raise api_error(409, "already_reported", "Tu as déjà signalé ce morceau.")
    return {"id": report_id, "song_id": song_id}


# --- Admin -----------------------------------------------------------------------

@router.get("/api/admin/songs", dependencies=[Depends(require_admin)])
def admin_songs(request: Request, status: str = "pending", page: int = 1, per_page: int = 50,
                conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    if status not in ("pending", "approved", "rejected"):
        raise api_error(422, "bad_status", "status doit valoir pending, approved ou rejected.")
    page, per_page = max(1, page), max(1, min(100, per_page))
    total = conn.execute("SELECT COUNT(*) FROM songs WHERE status=?", (status,)).fetchone()[0]
    rows = conn.execute(f"{SONG_SELECT} WHERE s.status=? ORDER BY s.created_at ASC, s.id ASC LIMIT ? OFFSET ?",
                        (status, per_page, (page - 1) * per_page)).fetchall()
    return {"items": [song_public(r, settings) for r in rows], "page": page, "per_page": per_page,
            "total": total, "pages": max(1, math.ceil(total / per_page))}


@router.post("/api/admin/songs/{song_id}/approve")
def approve_song(song_id: int, request: Request, admin=Depends(require_admin),
                 conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    fetch_song(conn, song_id)
    conn.execute("UPDATE songs SET status='approved', reject_reason=NULL, reviewed_by=?, reviewed_at=? WHERE id=?",
                 (admin["id"], db.now_iso(), song_id))
    conn.commit()
    return song_public(fetch_song(conn, song_id), settings)


@router.post("/api/admin/songs/{song_id}/reject")
def reject_song(song_id: int, body: RejectIn, request: Request, admin=Depends(require_admin),
                conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    fetch_song(conn, song_id)
    conn.execute("UPDATE songs SET status='rejected', reject_reason=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                 (body.reason.strip() or None, admin["id"], db.now_iso(), song_id))
    conn.commit()
    return song_public(fetch_song(conn, song_id), settings)


@router.get("/api/admin/reports", dependencies=[Depends(require_admin)])
def admin_reports(open: int = 1, conn: db.Connection = Depends(db.get_db)):
    where = "r.resolved_at IS NULL" if open else "1=1"
    rows = conn.execute(
        f"""SELECT r.*, s.title AS song_title, s.status AS song_status, u.username AS reporter_name
            FROM reports r JOIN songs s ON s.id = r.song_id JOIN users u ON u.id = r.reporter_id
            WHERE {where} ORDER BY r.created_at ASC""").fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/api/admin/reports/{report_id}/resolve")
def resolve_report(report_id: int, body: ResolveIn, request: Request, admin=Depends(require_admin),
                   conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    rep = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if rep is None:
        raise api_error(404, "not_found", "Signalement introuvable.")
    now = db.now_iso()
    if body.action == "remove_song":
        # Le morceau est supprimé (les signalements suivent en cascade) : on renvoie l'état final directement.
        row = conn.execute(f"{SONG_SELECT} WHERE s.id=?", (rep["song_id"],)).fetchone()
        if row is not None:
            delete_song(conn, settings, row)
        return {"id": report_id, "resolution": "remove_song", "resolved_at": now, "song_removed": row is not None}
    conn.execute("UPDATE reports SET resolved_at=?, resolved_by=?, resolution=? WHERE id=?",
                 (now, admin["id"], body.action, report_id))
    conn.commit()
    return {"id": report_id, "resolution": body.action, "resolved_at": now, "song_removed": False}


@router.post("/api/admin/users/{user_id}/ban")
def ban_user(user_id: int, request: Request, admin=Depends(require_admin),
             conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if target is None:
        raise api_error(404, "not_found", "Utilisateur introuvable.")
    if is_admin(target, settings):
        raise api_error(403, "forbidden", "Impossible de bannir un administrateur.")
    conn.execute("UPDATE users SET banned=1 WHERE id=?", (user_id,))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.execute("UPDATE songs SET status='rejected', reject_reason='ban', reviewed_by=?, reviewed_at=? "
                 "WHERE uploader_id=? AND status='pending'", (admin["id"], db.now_iso(), user_id))
    conn.commit()
    return {"ok": True, "user_id": user_id}
