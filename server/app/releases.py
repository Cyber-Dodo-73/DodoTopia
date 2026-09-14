"""Versions de l'app : manifeste public, dépôt des binaires par publish_release.py, publication."""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from . import db
from .auth import api_error, require_publish_token, settings_of
from .config import Settings
from .schemas import PublishIn

router = APIRouter()

PLATFORMS = ("windows-setup", "windows-portable", "linux-x64")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def version_key(v: str) -> tuple[int, ...]:
    """'1.10.0' -> (1, 10, 0) ; ValueError si le format est invalide. Partagé avec publish_release.py."""
    if not VERSION_RE.match(v or ""):
        raise ValueError(f"Version invalide : {v!r}")
    return tuple(int(x) for x in v.split("."))


def check_version(v: str) -> str:
    try:
        version_key(v)
    except ValueError:
        raise api_error(422, "bad_version", "Version invalide (attendu x.y.z).")
    return v


def release_dir(settings: Settings, version: str) -> Path:
    return settings.releases_dir / version


def manifest(conn: db.Connection, settings: Settings, version: str) -> dict | None:
    rel = conn.execute("SELECT * FROM releases WHERE version=?", (version,)).fetchone()
    if rel is None:
        return None
    assets = {}
    for a in conn.execute("SELECT * FROM release_assets WHERE version=?", (version,)):
        assets[a["platform"]] = {
            "url": f"{settings.public_url}/dl/{version}/{a['filename']}",
            "filename": a["filename"],
            "sha256": a["sha256"],
            "size": a["size"],
        }
    return {"version": version, "published_at": rel["published_at"], "notes": rel["notes"] or "",
            "mandatory": bool(rel["mandatory"]), "assets": assets}


def published_versions(conn: db.Connection) -> list[str]:
    rows = conn.execute("SELECT version FROM releases WHERE published_at IS NOT NULL").fetchall()
    return sorted((r["version"] for r in rows), key=version_key, reverse=True)


# --- Public ----------------------------------------------------------------------

@router.get("/api/releases/latest")
def latest(request: Request, current: str = "", platform: str = "", conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    versions = published_versions(conn)
    if not versions:
        raise api_error(404, "no_release", "Aucune version publiée.")
    m = manifest(conn, settings, versions[0])
    update_available = False
    if current:
        try:
            update_available = version_key(m["version"]) > version_key(current)
        except ValueError:
            raise api_error(422, "bad_version", "Paramètre current invalide.")
    m["update_available"] = update_available
    m["asset"] = m["assets"].get(platform) if platform else None
    return m


@router.get("/api/releases")
def list_releases(request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    return {"items": [manifest(conn, settings, v) for v in published_versions(conn)]}


@router.get("/api/releases/{version}")
def get_release(version: str, request: Request, conn: db.Connection = Depends(db.get_db)):
    check_version(version)
    m = manifest(conn, settings_of(request), version)
    if m is None or m["published_at"] is None:
        raise api_error(404, "not_found", "Version inconnue.")
    return m


@router.get("/dl/{version}/{filename}")
def download_asset(version: str, filename: str, request: Request):
    """Binaires publiés, servis par l'API (FileResponse : Range/206 et ETag gérés par Starlette)."""
    check_version(version)
    if not FILENAME_RE.match(filename):
        raise api_error(404, "not_found", "Fichier inconnu.")
    path = release_dir(settings_of(request), version) / filename
    if not path.is_file():
        raise api_error(404, "not_found", "Fichier inconnu.")
    return FileResponse(path, media_type="application/octet-stream", filename=filename,
                        headers={"Cache-Control": "public, max-age=3600"})


# --- Publication (jeton) ---------------------------------------------------------

@router.get("/api/admin/releases/check", dependencies=[Depends(require_publish_token)])
def check_token():
    """Permet à publish_release.py de vérifier le jeton avant d'envoyer des fichiers volumineux."""
    return {"ok": True}


@router.put("/api/admin/releases/{version}/assets/{platform}", dependencies=[Depends(require_publish_token)])
async def put_asset(version: str, platform: str, request: Request):
    """Corps brut streamé vers <version>/<filename>.part ; sha256 vérifié ; renommage atomique. Idempotent."""
    settings = settings_of(request)
    check_version(version)
    if platform not in PLATFORMS:
        raise api_error(422, "bad_platform", f"Plateforme inconnue (attendu : {', '.join(PLATFORMS)}).")
    sha = (request.headers.get("X-Sha256") or "").lower()
    filename = request.headers.get("X-Filename") or ""
    if not SHA_RE.match(sha):
        raise api_error(422, "bad_sha256", "En-tête X-Sha256 manquant ou invalide.")
    if not FILENAME_RE.match(filename) or filename.endswith(".part"):
        raise api_error(422, "bad_filename", "En-tête X-Filename manquant ou invalide.")

    d = release_dir(settings, version)
    d.mkdir(parents=True, exist_ok=True)
    part = d / (filename + ".part")
    h = hashlib.sha256()
    size = 0
    try:
        with open(part, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
        if h.hexdigest() != sha:
            raise api_error(400, "sha_mismatch", "Le sha256 reçu ne correspond pas au fichier.",
                            expected=sha, actual=h.hexdigest())
        if size == 0:
            raise api_error(400, "empty", "Fichier vide.")
        part.replace(d / filename)
    finally:
        if part.exists():
            part.unlink()

    conn = db.connect(settings)
    try:
        conn.execute("INSERT INTO releases (version) VALUES (?) ON CONFLICT (version) DO NOTHING", (version,))
        old = conn.execute("SELECT filename FROM release_assets WHERE version=? AND platform=?",
                           (version, platform)).fetchone()
        if old is not None and old["filename"] != filename:
            try:
                (d / old["filename"]).unlink()
            except OSError:
                pass
        conn.execute(
            """INSERT INTO release_assets (version, platform, filename, sha256, size) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(version, platform) DO UPDATE SET filename=excluded.filename, sha256=excluded.sha256,
               size=excluded.size""",
            (version, platform, filename, sha, size),
        )
        conn.commit()
    finally:
        conn.close()
    return {"version": version, "platform": platform, "filename": filename, "sha256": sha, "size": size,
            "url": f"{settings.public_url}/dl/{version}/{filename}"}


@router.post("/api/admin/releases/{version}/publish", dependencies=[Depends(require_publish_token)])
def publish(version: str, body: PublishIn, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    check_version(version)
    m = manifest(conn, settings, version)
    if m is None or "windows-setup" not in m["assets"]:
        raise api_error(409, "missing_asset", "L'installeur windows-setup doit être déposé avant la publication.")
    conn.execute("UPDATE releases SET notes=?, mandatory=?, published_at=? WHERE version=?",
                 (body.notes, 1 if body.mandatory else 0, db.now_iso(), version))
    conn.commit()
    return manifest(conn, settings, version)


@router.delete("/api/admin/releases/{version}", dependencies=[Depends(require_publish_token)])
def delete_release(version: str, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    check_version(version)
    if conn.execute("SELECT 1 FROM releases WHERE version=?", (version,)).fetchone() is None:
        raise api_error(404, "not_found", "Version inconnue.")
    conn.execute("DELETE FROM releases WHERE version=?", (version,))
    conn.commit()
    shutil.rmtree(release_dir(settings, version), ignore_errors=True)
    return {"ok": True, "version": version}
