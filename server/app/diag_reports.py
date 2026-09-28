"""Rapports de diagnostic envoyés depuis l'application (bouton « Envoyer un rapport »).

L'app rassemble ses journaux et captures dans un zip (sans jeton de compte), l'envoie ici et affiche un code
court que le joueur colle sur Discord ; l'administrateur retrouve le rapport par ce code dans l'espace admin.

- POST /api/diag-reports : public (un joueur sans compte doit pouvoir envoyer un rapport), limité par IP ;
  zip vérifié (nombre d'entrées, noms, taille décompressée) ; renvoie {code}.
- GET /api/admin/diag-reports, GET /api/admin/diag-reports/{code}, DELETE /api/admin/diag-reports/{code}.
- Purge automatique après DIAG_REPORT_TTL_DAYS (cleanup du serveur).

Table `diag_reports` (la table `reports` est celle des signalements de morceaux et de dessins).
"""
from __future__ import annotations

import io
import secrets
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from . import db, notify, stats
from .admin import audit
from .auth import api_error, get_optional_user, require_admin, settings_of
from .config import Settings
from .library import read_upload
from .ratelimit import limit
from .schemas import clean_text

router = APIRouter()
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # même alphabet que les salons (sans I, O, 0, 1)
CODE_LEN = 8
MAX_ENTRIES = 64
MAX_UNCOMPRESSED = 64 * 1024 * 1024


class ReportError(ValueError):
    pass


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def normalize_code(code: str) -> str:
    return "".join(c for c in str(code or "").upper() if c in CODE_ALPHABET)[:CODE_LEN]


def report_file(settings: Settings, code: str) -> Path:
    return settings.diag_reports_dir / f"{code}.zip"


def check_zip(data: bytes) -> list[str]:
    """Liste des fichiers d'un zip de rapport ; ReportError si ce n'est pas un rapport acceptable."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ReportError("Ce n'est pas un fichier zip.")
    infos = zf.infolist()
    if not infos:
        raise ReportError("Rapport vide.")
    if len(infos) > MAX_ENTRIES:
        raise ReportError("Trop de fichiers dans le rapport.")
    total = 0
    names = []
    for i in infos:
        n = i.filename
        if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/") or ":" in n:
            raise ReportError("Nom de fichier refusé dans le rapport.")
        total += i.file_size
        if total > MAX_UNCOMPRESSED:
            raise ReportError("Rapport trop volumineux une fois décompressé.")
        names.append(n)
    return names


def public(row) -> dict:
    return {"code": row["code"], "created_at": row["created_at"], "size": row["size"], "files": row["files"],
            "note": row["note"] or "", "version": row["version"] or "", "os": row["os"] or "",
            "user_id": row["user_id"], "username": row["username"] or ""}


@router.post("/api/diag-reports", status_code=201, dependencies=[Depends(limit("diag_report", 5, 3600, by="ip"))])
async def upload_report(request: Request, file: UploadFile = File(...), note: str = Form(""),
                        version: str = Form(""), os_name: str = Form("", alias="os"),
                        user=Depends(get_optional_user), conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    data = await read_upload(file, settings.MAX_DIAG_REPORT_BYTES)
    try:
        names = check_zip(data)
    except ReportError as e:
        raise api_error(422, "invalid_report", str(e))
    settings.diag_reports_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        code = new_code()
        if conn.execute("SELECT 1 FROM diag_reports WHERE code=?", (code,)).fetchone() is None:
            break
    path = report_file(settings, code)
    path.write_bytes(data)
    note = clean_text(note, 2000)
    try:
        conn.execute("INSERT INTO diag_reports (code, user_id, username, note, version, os, size, files, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (code, user["id"] if user else None, user["username"] if user else None, note or None,
                      clean_text(version, 32) or None, clean_text(os_name, 80) or None, len(data), len(names),
                      db.now_iso()))
        conn.commit()
    except Exception:
        conn.rollback()
        path.unlink(missing_ok=True)
        raise
    stats.hit(request.app, "upload", "diag_report")
    notify.emit(request.app, "diag_report", f"Rapport de diagnostic {code}",
                (note[:300] if note else "Sans description") + (f"\nEnvoyé par **{user['username']}**" if user else ""),
                fields=[("Version", clean_text(version, 32) or "?"), ("Fichiers", str(len(names)))],
                url=notify.admin_url(settings, f"diag/{code}"))
    return {"code": code}


@router.get("/api/admin/diag-reports")
def list_reports(request: Request, admin=Depends(require_admin), conn: db.Connection = Depends(db.get_db)):
    rows = conn.execute("SELECT * FROM diag_reports ORDER BY created_at DESC LIMIT 200").fetchall()
    return {"items": [public(r) for r in rows], "ttl_days": settings_of(request).DIAG_REPORT_TTL_DAYS}


def _fetch(conn, code):
    row = conn.execute("SELECT * FROM diag_reports WHERE code=?", (normalize_code(code),)).fetchone()
    if row is None:
        raise api_error(404, "not_found", "Rapport introuvable.")
    return row


@router.get("/api/admin/diag-reports/{code}")
def get_report(request: Request, code: str, admin=Depends(require_admin), conn: db.Connection = Depends(db.get_db)):
    row = _fetch(conn, code)
    path = report_file(settings_of(request), row["code"])
    if not path.is_file():
        raise api_error(404, "not_found", "Fichier du rapport disparu.")
    return FileResponse(path, media_type="application/zip", filename=f"dodotopia-rapport-{row['code']}.zip")


@router.get("/api/admin/diag-reports/{code}/files")
def report_files(request: Request, code: str, admin=Depends(require_admin), conn: db.Connection = Depends(db.get_db)):
    """Contenu du zip (noms et tailles) pour la fiche de l'espace admin."""
    row = _fetch(conn, code)
    path = report_file(settings_of(request), row["code"])
    if not path.is_file():
        raise api_error(404, "not_found", "Fichier du rapport disparu.")
    with zipfile.ZipFile(path) as zf:
        files = [{"name": i.filename, "size": i.file_size} for i in zf.infolist()]
    return {"report": public(row), "files": files}


@router.delete("/api/admin/diag-reports/{code}")
def delete_report(request: Request, code: str, admin=Depends(require_admin), conn: db.Connection = Depends(db.get_db)):
    row = _fetch(conn, code)
    conn.execute("DELETE FROM diag_reports WHERE code=?", (row["code"],))
    audit(request, conn, admin, "diag_report_delete", row["code"])
    conn.commit()
    report_file(settings_of(request), row["code"]).unlink(missing_ok=True)
    return {"ok": True}


def purge(settings: Settings, conn: db.Connection, now: float | None = None) -> int:
    """Efface les rapports plus vieux que DIAG_REPORT_TTL_DAYS (fichier et ligne). Renvoie le nombre effacé."""
    now = time.time() if now is None else now
    cutoff = datetime.fromtimestamp(now - settings.DIAG_REPORT_TTL_DAYS * 86400, timezone.utc)
    old = [r["code"] for r in conn.execute("SELECT code, created_at FROM diag_reports").fetchall()
           if _parse(r["created_at"]) < cutoff]
    for code in old:
        conn.execute("DELETE FROM diag_reports WHERE code=?", (code,))
        report_file(settings, code).unlink(missing_ok=True)
    if old:
        conn.commit()
    return len(old)


def _parse(iso: str) -> datetime:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
