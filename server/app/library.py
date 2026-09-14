"""Bibliothèque MIDI en ligne : dépôt par les connectés, modération admin, téléchargement public."""
from __future__ import annotations

import hashlib
import io
import math
import os
import re
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import mido
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from . import db
from .auth import api_error, get_current_user, get_optional_user, is_admin, require_admin, settings_of
from .config import Settings
from .ratelimit import limit
from .schemas import RejectIn, ReportIn, ResolveIn, SongPatch, clean_text

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


class Limits(NamedTuple):
    """Plafonds de validation d'un fichier MIDI (config.Settings ou valeurs par défaut du module)."""
    max_tracks: int = 64
    max_events: int = 100_000
    max_notes: int = 50_000
    min_notes: int = 10
    min_duration_s: float = 1.0
    max_duration_s: float = 30 * 60


DEFAULT_LIMITS = Limits()


def limits_of(settings: Settings | None) -> Limits:
    if settings is None:
        return DEFAULT_LIMITS
    return Limits(settings.MAX_MIDI_TRACKS, settings.MAX_MIDI_EVENTS, settings.MAX_MIDI_NOTES,
                  settings.MIN_MIDI_NOTES, settings.MIN_MIDI_DURATION_S, settings.MAX_MIDI_DURATION_S)


# Octets de données d'un message de canal, par quartet de statut (0x8..0xE).
_CHANNEL_DATA = {0x8: 2, 0x9: 2, 0xA: 2, 0xB: 2, 0xC: 1, 0xD: 1, 0xE: 2}
_SYSTEM_DATA = {0xF1: 1, 0xF2: 2, 0xF3: 1}


def _varlen(data: bytes, i: int, end: int) -> tuple[int, int]:
    """Entier à longueur variable du SMF (au plus 4 octets)."""
    value = 0
    for _ in range(4):
        if i >= end:
            raise MidiError("Fichier MIDI tronqué (nombre à longueur variable incomplet).")
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i
    raise MidiError("Fichier MIDI invalide (nombre à longueur variable trop long).")


def scan_midi(data: bytes, limits: Limits = DEFAULT_LIMITS) -> dict:
    """Analyse un SMF octet par octet, sans rien construire en mémoire, et abandonne dès qu'un plafond est
    dépassé : c'est ce qui borne le travail (temps et mémoire) avant de laisser `mido` toucher au fichier.

    Renvoie {type, tracks, division, event_count, note_count}. MidiError sur tout refus.
    """
    n = len(data)
    if n < 14 or data[:4] != b"MThd":
        raise MidiError("Ce n'est pas un fichier MIDI (en-tête « MThd » absent).")
    header_len = int.from_bytes(data[4:8], "big")
    if header_len < 6 or header_len > 1024 or 8 + header_len > n:
        raise MidiError("En-tête MIDI invalide (longueur aberrante).")
    fmt = int.from_bytes(data[8:10], "big")
    ntrks = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")
    if fmt not in (0, 1):
        raise MidiError(f"Seuls les fichiers MIDI de type 0 ou 1 sont acceptés (type {fmt}).")
    if ntrks < 1 or ntrks > limits.max_tracks:
        raise MidiError(f"Nombre de pistes invalide ({ntrks}, maximum {limits.max_tracks}).")
    if fmt == 0 and ntrks != 1:
        raise MidiError("Un fichier MIDI de type 0 ne contient qu'une piste.")
    if division & 0x8000:                      # code temporel SMPTE
        fps = 256 - (division >> 8)            # l'octet fort est un complément à deux : -24, -25, -29, -30
        ticks_per_frame = division & 0xFF
        if fps not in (24, 25, 29, 30) or not 1 <= ticks_per_frame <= 255:
            raise MidiError("Division SMPTE aberrante (images par seconde ou ticks invalides).")
    elif division == 0:
        raise MidiError("Division nulle : le fichier n'a pas de base de temps.")

    i = 8 + header_len
    tracks = events = notes = 0
    while i + 8 <= n:
        chunk_id = data[i:i + 4]
        length = int.from_bytes(data[i + 4:i + 8], "big")
        i += 8
        end = min(i + length, n)               # dernière piste tronquée : on s'arrête sur les octets présents
        if chunk_id == b"MTrk":
            tracks += 1
            if tracks > limits.max_tracks:
                raise MidiError(f"Trop de pistes (maximum {limits.max_tracks}).")
            ev, nt = _scan_track(data, i, end, limits, events, notes)
            events, notes = ev, nt
        i = end
    if tracks == 0:
        raise MidiError("Fichier MIDI sans piste.")
    if notes < limits.min_notes:
        raise MidiError(f"Trop peu de notes (au moins {limits.min_notes} notes hors percussions).")
    return {"type": fmt, "tracks": tracks, "division": division, "event_count": events, "note_count": notes}


def _scan_track(data: bytes, i: int, end: int, limits: Limits, events: int, notes: int) -> tuple[int, int]:
    """Parcourt une piste (running status compris) en comptant évènements et notes."""
    status = None
    while i < end:
        _, i = _varlen(data, i, end)           # delta-temps
        if i >= end:
            break
        b = data[i]
        if b & 0x80:
            i += 1
            if b == 0xFF:                      # méta-évènement
                if i >= end:
                    raise MidiError("Fichier MIDI tronqué (méta-évènement incomplet).")
                meta_type = data[i]
                i += 1
                length, i = _varlen(data, i, end)
                i += length
                status = None
                if meta_type == 0x2F:          # fin de piste
                    events += 1
                    break
            elif b in (0xF0, 0xF7):            # sysex
                length, i = _varlen(data, i, end)
                i += length
                status = None
            elif b >= 0xF1:                    # message système temps réel / commun
                i += _SYSTEM_DATA.get(b, 0)
                status = None
            else:
                status = b
                i = _consume_channel(data, i, end, status)
                if status >> 4 == 0x9 and data[i - 1] > 0 and (status & 0x0F) != 9:
                    notes += 1
        else:
            if status is None:
                raise MidiError("Fichier MIDI invalide (octet de données sans statut courant).")
            i = _consume_channel(data, i, end, status)
            if status >> 4 == 0x9 and data[i - 1] > 0 and (status & 0x0F) != 9:
                notes += 1
        if i > end:
            raise MidiError("Fichier MIDI tronqué (évènement débordant de sa piste).")
        events += 1
        if events > limits.max_events:
            raise MidiError(f"Fichier MIDI trop chargé (plus de {limits.max_events} évènements).")
        if notes > limits.max_notes:
            raise MidiError(f"Fichier MIDI trop chargé (plus de {limits.max_notes} notes).")
    return events, notes


def _consume_channel(data: bytes, i: int, end: int, status: int) -> int:
    size = _CHANNEL_DATA.get(status >> 4)
    if size is None:
        raise MidiError("Fichier MIDI invalide (statut inconnu).")
    if i + size > end:
        raise MidiError("Fichier MIDI tronqué (message de canal incomplet).")
    return i + size


def validate_midi(data: bytes, settings: Settings | None = None) -> dict:
    """Vérifie un fichier MIDI et renvoie {duration_s, note_count}. MidiError si refusé.

    Ordre volontaire : `scan_midi` (bornée) d'abord, `mido` ensuite. Un fichier hostile n'atteint jamais le
    parseur générique tant que sa structure et son volume ne sont pas déjà connus et acceptables.
    """
    limits = limits_of(settings)
    info = scan_midi(data, limits)
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
    if not math.isfinite(duration) or duration < limits.min_duration_s:
        raise MidiError("Morceau trop court (moins d'une seconde).")
    if duration > limits.max_duration_s:
        raise MidiError(f"Morceau trop long (plus de {int(limits.max_duration_s // 60)} minutes).")
    return {"duration_s": round(duration, 2), "note_count": info["note_count"]}


async def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Lit le fichier par blocs et refuse (413) dès que la taille dépasse max_bytes, sans se fier au Content-Length.

    Le rempart en amont est `main.BodySizeLimitMiddleware` : sans lui, Starlette déverse tout le corps
    multipart dans un fichier temporaire avant même que cette fonction soit appelée.
    """
    buf = bytearray()
    while True:
        chunk = await upload.read(CHUNK)
        if not chunk:
            break
        buf += chunk
        if len(buf) > max_bytes:
            raise api_error(413, "too_large", f"Fichier trop gros (max {max_bytes // 1024} Ko).")
    return bytes(buf)


# --- Nom de fichier servi au téléchargement --------------------------------------

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9 ._-]+")
_RESERVED = {"CON", "PRN", "AUX", "NUL", "COM0", "LPT0",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_ascii_filename(title: str, fallback: str, ext: str = ".mid") -> str:
    """Nom ASCII strictement sur liste blanche : ni guillemet, ni retour à la ligne, ni séparateur, ni nom
    réservé Windows, ni point final. C'est ce qui rend l'en-tête Content-Disposition ininjectable."""
    name = _FILENAME_SAFE.sub("", clean_text(title, 120)).strip(" .")
    name = re.sub(r"\s+", " ", name)[:80].strip(" .")
    if not name or name.upper() in _RESERVED:
        name = fallback
    return name + ext


def content_disposition(title: str, sha: str) -> str:
    """`attachment; filename="ascii"; filename*=UTF-8''<percent-encodé>` (RFC 6266).

    Les deux formes sont dérivées d'un texte nettoyé puis, pour la forme étendue, intégralement
    percent-encodée : aucun octet fourni par l'utilisateur ne peut clore la chaîne ni couper l'en-tête.
    """
    ascii_name = safe_ascii_filename(title, fallback=sha[:16] or "song")
    utf8_name = clean_text(title, 120).strip(" .") or (sha[:16] or "song")
    utf8_name = utf8_name.replace("/", "-").replace("\\", "-") + ".mid"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(utf8_name, safe="")}'


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
    # `filename=` de FileResponse n'est pas utilisé : l'en-tête est construit ici, sur liste blanche.
    return FileResponse(path, media_type="audio/midi",
                        headers={"ETag": f'"{row["sha256"]}"', "X-Sha256": row["sha256"],
                                 "Content-Disposition": content_disposition(row["title"], row["sha256"]),
                                 "X-Content-Type-Options": "nosniff"})


# --- Connectés -------------------------------------------------------------------

@router.post("/api/songs", status_code=201, dependencies=[Depends(limit("upload", 10, 3600, by="user"))])
async def upload_song(request: Request, file: UploadFile = File(...), title: str = Form(""), artist: str = Form(""),
                      user=Depends(get_current_user), conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    data = await read_upload(file, settings.MAX_MIDI_BYTES)
    if not data:
        raise api_error(422, "invalid_midi", "Fichier vide.")
    try:
        info = validate_midi(data, settings)
    except MidiError as e:
        raise api_error(422, "invalid_midi", str(e))
    sha = hashlib.sha256(data).hexdigest()
    existing = conn.execute("SELECT id, status FROM songs WHERE sha256=?", (sha,)).fetchone()
    if existing is not None:
        raise api_error(409, "duplicate", "Ce morceau existe déjà dans la bibliothèque.", existing_id=existing["id"],
                        existing_status=existing["status"])
    # Le nom d'origine est un texte fourni par le client : jamais utilisé pour construire un chemin
    # (le fichier s'appelle <sha256>.mid), seulement stocké et affiché, donc nettoyé comme les autres.
    original = clean_text(os.path.basename((file.filename or "morceau.mid").replace("\\", "/")),
                          settings.MAX_TEXT_LEN) or "morceau.mid"
    title = clean_text(title, settings.MAX_TEXT_LEN) or clean_text(clean_title(original), settings.MAX_TEXT_LEN) \
        or "Sans titre"
    artist = clean_text(artist, settings.MAX_TEXT_LEN) or None
    path = song_path(settings, sha)
    path.write_bytes(data)
    try:
        cur = conn.execute(
            """INSERT INTO songs (sha256, title, artist, original_name, size, duration_s, note_count, uploader_id,
                                  status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?) RETURNING id""",
            (sha, title, artist, original, len(data), info["duration_s"], info["note_count"], user["id"],
             db.now_iso()),
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
    except Exception:
        conn.rollback()
        path.unlink(missing_ok=True)   # aucun fichier orphelin si l'insertion échoue
        raise
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
    if body.title is not None:      # SongPatch a déjà nettoyé (None si le titre ne contenait que de l'invisible)
        conn.execute("UPDATE songs SET title=? WHERE id=?", (body.title, song_id))
    if body.artist is not None:
        conn.execute("UPDATE songs SET artist=? WHERE id=?", (body.artist, song_id))
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
    if not body.reason:
        raise api_error(422, "bad_reason", "Explique en quelques mots ce qui ne va pas.")
    try:
        cur = conn.execute("INSERT INTO reports (song_id, reporter_id, reason, created_at) VALUES (?, ?, ?, ?) "
                           "RETURNING id", (song_id, user["id"], body.reason, db.now_iso()))
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
                 (body.reason or None, admin["id"], db.now_iso(), song_id))
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
