"""Galerie de dessins : dépôt par les connectés (PNG + grille de cases facultative), modération admin calquée sur la
bibliothèque, likes, signalements, affichage public.

Un PNG déposé n'est jamais servi tel quel : signature et dimensions lues dans l'en-tête avant tout décodage,
décodage complet par Pillow (bombe de décompression, fichier tronqué, APNG refusés), puis **ré-encodage** depuis
les pixels seuls dans une image neuve — métadonnées, profils, blocs de texte et données collées après `IEND`
disparaissent. Le fichier s'appelle `<sha256 du PNG ré-encodé>.png` (+ `.thumb.png`, 400 px au plus).
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import math
import re
import struct
import warnings
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import db, indexnow, social
from .auth import api_error, get_current_user, get_optional_user, is_admin, require_admin, settings_of
from .config import Settings
from .library import DELETED_UPLOADER_NAME, read_upload
from .ratelimit import limit
from .schemas import RejectIn, ReportIn, clean_text

router = APIRouter()

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DRAWING_SORTS = ("recent", "popular")
_CELLS_FORMAT_RE = re.compile(r"^[A-Za-z0-9 x_.:-]{1,32}$")
MAX_CELL_SIDE = 1024
MAX_CELL_VALUE = 65535


class DrawingError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


# --- Fichiers ----------------------------------------------------------------------------------------

def drawing_path(settings: Settings, sha: str) -> Path:
    return settings.drawings_dir / f"{sha}.png"


def thumb_path(settings: Settings, sha: str) -> Path:
    return settings.drawings_dir / f"{sha}.thumb.png"


def drawing_files(settings: Settings, sha: str) -> tuple[Path, Path]:
    return drawing_path(settings, sha), thumb_path(settings, sha)


def thumb_size(w: int, h: int, max_px: int = 400) -> tuple[int, int]:
    """Dimensions de la vignette (même calcul que `Image.thumbnail`, jamais agrandie)."""
    if w <= max_px and h <= max_px:
        return w, h
    scale = min(max_px / w, max_px / h)
    return max(1, round(w * scale)), max(1, round(h * scale))


# --- Validation ----------------------------------------------------------------------------------------

def process_png(data: bytes, settings: Settings) -> tuple[bytes, bytes, int, int]:
    """PNG déposé -> (PNG ré-encodé, vignette, largeur, hauteur). DrawingError sur tout refus."""
    from PIL import Image  # import tardif : Pillow n'est chargé qu'au premier dépôt

    if not data.startswith(PNG_SIGNATURE):
        raise DrawingError(422, "invalid_png", "Ce n'est pas une image PNG (signature absente).")
    if len(data) < 33 or data[12:16] != b"IHDR":
        raise DrawingError(422, "invalid_png", "Image PNG invalide (en-tête IHDR absent).")
    w, h = struct.unpack(">II", data[16:24])
    limit_px = settings.MAX_DRAWING_PX
    if not (1 <= w <= limit_px and 1 <= h <= limit_px):
        raise DrawingError(422, "image_too_large", f"Image trop grande (au plus {limit_px}×{limit_px} pixels).")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format != "PNG" or img.size != (w, h):
                raise DrawingError(422, "invalid_png", "Image PNG invalide.")
            if getattr(img, "n_frames", 1) != 1:
                raise DrawingError(422, "invalid_png", "Les PNG animés ne sont pas acceptés.")
            img.load()                                      # décodage complet : un fichier tronqué échoue ici
            mode = img.mode if img.mode in ("RGB", "RGBA") else "RGBA"
            pixels = img.convert(mode) if img.mode != mode else img
            clean = Image.frombytes(mode, (w, h), pixels.tobytes())  # image neuve : aucune métadonnée ne survit
    except DrawingError:
        raise
    except Exception:  # noqa - Pillow lève OSError, ValueError, SyntaxError, DecompressionBomb*, struct.error…
        raise DrawingError(422, "invalid_png", "Image PNG illisible ou corrompue.")
    out = io.BytesIO()
    clean.save(out, "PNG", optimize=True)
    thumb = clean.copy()
    thumb.thumbnail((settings.DRAWING_THUMB_PX, settings.DRAWING_THUMB_PX), Image.Resampling.BOX)
    tout = io.BytesIO()
    thumb.save(tout, "PNG", optimize=True)
    return out.getvalue(), tout.getvalue(), w, h


def parse_cells(text: str | None, settings: Settings) -> str | None:
    """Grille `{format, w, h, cells:[int]}` -> JSON normalisé compressé (gzip, base64) ; None si absente."""
    if text is None or not text.strip():
        return None
    raw = text.encode("utf-8")
    if len(raw) > settings.MAX_DRAWING_CELLS_BYTES:
        raise DrawingError(413, "too_large", f"Grille trop lourde (max {settings.MAX_DRAWING_CELLS_BYTES // 1024} Ko).")
    try:
        obj = json.loads(raw)
    except ValueError:
        raise DrawingError(422, "bad_cells", "Grille illisible (JSON attendu).")
    if not isinstance(obj, dict):
        raise DrawingError(422, "bad_cells", "Grille invalide : objet {format, w, h, cells} attendu.")
    fmt, cw, ch, cells = obj.get("format"), obj.get("w"), obj.get("h"), obj.get("cells")
    if not isinstance(fmt, str) or not _CELLS_FORMAT_RE.match(fmt):
        raise DrawingError(422, "bad_cells", "Grille invalide : format manquant ou mal formé.")
    for side in (cw, ch):
        if not isinstance(side, int) or isinstance(side, bool) or not 1 <= side <= MAX_CELL_SIDE:
            raise DrawingError(422, "bad_cells", "Grille invalide : dimensions hors limites.")
    if not isinstance(cells, list) or len(cells) != cw * ch:
        raise DrawingError(422, "bad_cells", "Grille invalide : le nombre de cases ne correspond pas à w × h.")
    for v in cells:
        if not isinstance(v, int) or isinstance(v, bool) or not -1 <= v <= MAX_CELL_VALUE:
            raise DrawingError(422, "bad_cells", "Grille invalide : chaque case est un entier (-1 = vide).")
    normalized = json.dumps({"format": fmt, "w": cw, "h": ch, "cells": cells}, separators=(",", ":"))
    return base64.b64encode(gzip.compress(normalized.encode("ascii"), mtime=0)).decode("ascii")


def load_cells(stored: str | None) -> dict | None:
    if not stored:
        return None
    try:
        return json.loads(gzip.decompress(base64.b64decode(stored)))
    except (ValueError, OSError, EOFError):
        return None


# --- Lignes ---------------------------------------------------------------------------------------------

DRAWING_COLUMNS = ("d.id, d.uploader_id, d.title, d.w, d.h, d.png_sha256, d.png_size, d.status, d.reject_reason, "
                   "d.likes, d.created_at, d.reviewed_at, d.reviewed_by, "
                   "CASE WHEN d.cells_json_gz IS NULL THEN 0 ELSE 1 END AS has_cells")
DRAWING_SELECT = (f"SELECT {DRAWING_COLUMNS}, COALESCE(u.username, '{DELETED_UPLOADER_NAME}') AS uploader_name "
                  "FROM drawings d LEFT JOIN users u ON u.id = d.uploader_id")


def fetch_drawing_row(conn: db.Connection, drawing_id: int) -> db.Row | None:
    return conn.execute(f"{DRAWING_SELECT} WHERE d.id=?", (drawing_id,)).fetchone()


def fetch_drawing(conn: db.Connection, drawing_id: int) -> db.Row:
    row = fetch_drawing_row(conn, drawing_id)
    if row is None:
        raise api_error(404, "not_found", "Dessin introuvable.")
    return row


def can_see(row: db.Row, user: db.Row | None, settings: Settings) -> bool:
    if row["status"] == "approved":
        return True
    return user is not None and (user["id"] == row["uploader_id"] or is_admin(user, settings))


def drawing_public(row: db.Row, settings: Settings, liked: bool | None = None) -> dict:
    base = f"{settings.public_url}/api/drawings/{row['id']}"
    tw, th = thumb_size(row["w"], row["h"], settings.DRAWING_THUMB_PX)
    body = {
        "id": row["id"],
        "title": row["title"],
        "w": row["w"],
        "h": row["h"],
        "thumb_w": tw,
        "thumb_h": th,
        "sha256": row["png_sha256"],
        "png_size": row["png_size"],
        "has_cells": bool(row["has_cells"]),
        "uploader_id": row["uploader_id"],
        "uploader_name": row["uploader_name"],
        "status": row["status"],
        "reject_reason": row["reject_reason"],
        "likes": int(row["likes"] or 0),
        "created_at": row["created_at"],
        "image_url": f"{base}.png",
        "thumb_url": f"{base}/thumb.png",
        "cells_url": f"{base}/cells" if row["has_cells"] else None,
        "app_url": f"dodotopia://drawing/{row['id']}",
    }
    if liked is not None:
        body["liked_by_me"] = bool(liked)
    return body


def query_drawings(conn: db.Connection, sort: str = "recent", page: int = 1, per_page: int = 24,
                   status: str = "approved") -> tuple[list[db.Row], int]:
    order = "d.likes DESC, d.id DESC" if sort == "popular" else "d.created_at DESC, d.id DESC"
    total = conn.execute("SELECT COUNT(*) FROM drawings d WHERE d.status=?", (status,)).fetchone()[0]
    rows = conn.execute(f"{DRAWING_SELECT} WHERE d.status=? ORDER BY {order} LIMIT ? OFFSET ?",
                        (status, per_page, (page - 1) * per_page)).fetchall()
    return rows, int(total)


def delete_drawing(conn: db.Connection, settings: Settings, row: db.Row) -> None:
    conn.execute("DELETE FROM drawings WHERE id=?", (row["id"],))
    conn.commit()
    for path in drawing_files(settings, row["png_sha256"]):
        try:
            path.unlink()
        except OSError:
            pass


def _page_args(page: int, per_page: int) -> tuple[int, int]:
    return max(1, min(page, 10_000)), max(1, min(100, per_page))


# --- Public ----------------------------------------------------------------------------------------------

@router.get("/api/drawings")
def list_drawings(request: Request, page: int = 1, per_page: int = 24, sort: str = "recent",
                  user=Depends(get_optional_user), conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    page, per_page = _page_args(page, per_page)
    rows, total = query_drawings(conn, sort, page, per_page)
    liked = social.liked_ids(conn, "drawing", user["id"], [r["id"] for r in rows]) if user is not None else None
    items = [drawing_public(r, settings, (r["id"] in liked) if liked is not None else None) for r in rows]
    return {"items": items, "page": page, "per_page": per_page, "total": total,
            "pages": max(1, math.ceil(total / per_page))}


def _image_response(row: db.Row, path: Path) -> FileResponse:
    if not path.is_file():
        raise api_error(404, "not_found", "Fichier manquant sur le serveur.")
    cache = "public, max-age=86400" if row["status"] == "approved" else "private, no-store"
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": cache, "ETag": f'"{row["png_sha256"]}"',
                                 "X-Content-Type-Options": "nosniff",
                                 "Content-Disposition": f'inline; filename="drawing-{int(row["id"])}.png"'})


@router.get("/api/drawings/{drawing_id}.png")
def drawing_png(drawing_id: int, request: Request, user=Depends(get_optional_user),
                conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_drawing(conn, drawing_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Dessin introuvable.")
    return _image_response(row, drawing_path(settings, row["png_sha256"]))


@router.get("/api/drawings/{drawing_id}/thumb.png")
def drawing_thumb(drawing_id: int, request: Request, user=Depends(get_optional_user),
                  conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_drawing(conn, drawing_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Dessin introuvable.")
    return _image_response(row, thumb_path(settings, row["png_sha256"]))


@router.get("/api/drawings/{drawing_id}/cells")
def drawing_cells(drawing_id: int, request: Request, user=Depends(get_optional_user),
                  conn: db.Connection = Depends(db.get_db)):
    """Grille de cases pour rejouer le dessin (`dodotopia://drawing/{id}`) : {format, w, h, cells}."""
    settings = settings_of(request)
    row = fetch_drawing(conn, drawing_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Dessin introuvable.")
    stored = conn.execute("SELECT cells_json_gz FROM drawings WHERE id=?", (drawing_id,)).fetchone()
    cells = load_cells(stored["cells_json_gz"] if stored else None)
    if cells is None:
        raise api_error(404, "no_cells", "Ce dessin n'a pas de grille de cases.")
    cache = "public, max-age=86400" if row["status"] == "approved" else "private, no-store"
    return JSONResponse(cells, headers={"Cache-Control": cache})


@router.get("/api/drawings/{drawing_id}")
def get_drawing(drawing_id: int, request: Request, user=Depends(get_optional_user),
                conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_drawing(conn, drawing_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Dessin introuvable.")
    liked = bool(social.liked_ids(conn, "drawing", user["id"], [drawing_id])) if user is not None else None
    return drawing_public(row, settings, liked)


# --- Connectés ---------------------------------------------------------------------------------------------

@router.post("/api/drawings", status_code=201, dependencies=[Depends(limit("drawing_upload", 5, 3600, by="user"))])
async def upload_drawing(request: Request, png: UploadFile = File(...), title: str = Form(""),
                         cells: str | None = Form(None), user=Depends(get_current_user),
                         conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    title = clean_text(title, settings.MAX_DRAWING_TITLE_LEN) or "Sans titre"
    try:
        cells_blob = parse_cells(cells, settings)
    except DrawingError as e:
        raise api_error(e.status, e.code, str(e))
    data = await read_upload(png, settings.MAX_DRAWING_PNG_BYTES)
    if not data:
        raise api_error(422, "invalid_png", "Fichier vide.")
    try:
        clean, thumb, w, h = process_png(data, settings)
    except DrawingError as e:
        raise api_error(e.status, e.code, str(e))
    sha = hashlib.sha256(clean).hexdigest()
    existing = conn.execute("SELECT id, status FROM drawings WHERE png_sha256=?", (sha,)).fetchone()
    if existing is not None:
        raise api_error(409, "duplicate", "Ce dessin existe déjà dans la galerie.", existing_id=existing["id"],
                        existing_status=existing["status"])
    settings.drawings_dir.mkdir(parents=True, exist_ok=True)
    png_file, thumb_file = drawing_files(settings, sha)
    png_file.write_bytes(clean)
    thumb_file.write_bytes(thumb)
    try:
        cur = conn.execute(
            """INSERT INTO drawings (uploader_id, title, w, h, png_sha256, png_size, cells_json_gz, status, likes,
                                     created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?) RETURNING id""",
            (user["id"], title, w, h, sha, len(clean), cells_blob, db.now_iso()))
        new_id = cur.fetchone()["id"]
        conn.commit()
    except Exception:
        conn.rollback()
        for path in (png_file, thumb_file):
            path.unlink(missing_ok=True)
        raise
    return drawing_public(fetch_drawing(conn, new_id), settings)


def _like_drawing(drawing_id: int, request: Request, user, conn: db.Connection, liked: bool) -> dict:
    settings = settings_of(request)
    row = fetch_drawing(conn, drawing_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Dessin introuvable.")
    if row["status"] != "approved":
        raise api_error(409, "not_approved", "Seul un dessin publié peut être aimé.")
    likes = social.set_like(conn, "drawing", drawing_id, user["id"], liked)
    return {"ok": True, "id": drawing_id, "liked": liked, "likes": likes}


@router.post("/api/drawings/{drawing_id}/like", dependencies=[Depends(limit("like", 60, 60, by="user"))])
def like_drawing(drawing_id: int, request: Request, user=Depends(get_current_user),
                 conn: db.Connection = Depends(db.get_db)):
    return _like_drawing(drawing_id, request, user, conn, True)


@router.delete("/api/drawings/{drawing_id}/like", dependencies=[Depends(limit("like", 60, 60, by="user"))])
def unlike_drawing(drawing_id: int, request: Request, user=Depends(get_current_user),
                   conn: db.Connection = Depends(db.get_db)):
    return _like_drawing(drawing_id, request, user, conn, False)


@router.delete("/api/drawings/{drawing_id}")
def remove_drawing(drawing_id: int, request: Request, user=Depends(get_current_user),
                   conn: db.Connection = Depends(db.get_db)):
    """L'auteur retire son dessin à tout moment (publié ou non) ; un administrateur aussi."""
    settings = settings_of(request)
    row = fetch_drawing(conn, drawing_id)
    if not is_admin(user, settings) and row["uploader_id"] != user["id"]:
        if not can_see(row, user, settings):
            raise api_error(404, "not_found", "Dessin introuvable.")
        raise api_error(403, "forbidden", "Ce dessin ne t'appartient pas.")
    delete_drawing(conn, settings, row)
    return {"ok": True}


@router.post("/api/drawings/{drawing_id}/report", status_code=201,
             dependencies=[Depends(limit("report", 20, 86400, by="user"))])
def report_drawing(drawing_id: int, body: ReportIn, request: Request, user=Depends(get_current_user),
                   conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    row = fetch_drawing(conn, drawing_id)
    if not can_see(row, user, settings):
        raise api_error(404, "not_found", "Dessin introuvable.")
    if not body.reason:
        raise api_error(422, "bad_reason", "Explique en quelques mots ce qui ne va pas.")
    try:
        cur = conn.execute("INSERT INTO reports (target_type, drawing_id, reporter_id, reason, created_at) "
                           "VALUES ('drawing', ?, ?, ?, ?) RETURNING id",
                           (drawing_id, user["id"], body.reason, db.now_iso()))
        report_id = cur.fetchone()["id"]
        conn.commit()
    except db.IntegrityError:
        conn.rollback()
        raise api_error(409, "already_reported", "Tu as déjà signalé ce dessin.")
    return {"id": report_id, "drawing_id": drawing_id, "target_type": "drawing", "target_id": drawing_id}


# --- Admin ----------------------------------------------------------------------------------------------------

@router.get("/api/admin/drawings", dependencies=[Depends(require_admin)])
def admin_drawings(request: Request, status: str = "pending", page: int = 1, per_page: int = 50,
                   conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    if status not in ("pending", "approved", "rejected"):
        raise api_error(422, "bad_status", "status doit valoir pending, approved ou rejected.")
    page, per_page = _page_args(page, per_page)
    total = conn.execute("SELECT COUNT(*) FROM drawings WHERE status=?", (status,)).fetchone()[0]
    rows = conn.execute(f"{DRAWING_SELECT} WHERE d.status=? ORDER BY d.created_at ASC, d.id ASC LIMIT ? OFFSET ?",
                        (status, per_page, (page - 1) * per_page)).fetchall()
    return {"items": [drawing_public(r, settings) for r in rows], "page": page, "per_page": per_page,
            "total": total, "pages": max(1, math.ceil(total / per_page))}


@router.post("/api/admin/drawings/{drawing_id}/approve")
def approve_drawing(drawing_id: int, request: Request, background_tasks: BackgroundTasks,
                    admin=Depends(require_admin), conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    before = fetch_drawing(conn, drawing_id)
    conn.execute("UPDATE drawings SET status='approved', reject_reason=NULL, reviewed_by=?, reviewed_at=? WHERE id=?",
                 (admin["id"], db.now_iso(), drawing_id))
    conn.commit()
    if settings.indexnow_key and before["status"] != "approved":        # IndexNow : la fiche devient publique
        background_tasks.add_task(indexnow.submit, settings, indexnow.drawing_urls(settings, drawing_id))
    return drawing_public(fetch_drawing(conn, drawing_id), settings)


@router.post("/api/admin/drawings/{drawing_id}/reject")
def reject_drawing(drawing_id: int, body: RejectIn, request: Request, admin=Depends(require_admin),
                   conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    fetch_drawing(conn, drawing_id)
    conn.execute("UPDATE drawings SET status='rejected', reject_reason=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                 (body.reason or None, admin["id"], db.now_iso(), drawing_id))
    conn.commit()
    return drawing_public(fetch_drawing(conn, drawing_id), settings)
