"""Versions de l'application Android : canal à part des versions PC (`releases.py`).

L'appli mobile a sa propre numérotation et un seul fichier par version (l'APK) : rien ici ne touche à la table
`releases`, au manifeste signé ni à `GET /api/releases/latest`, que lit le client PC pour ses mises à jour. Même
jeton de publication, même dépôt en deux temps (fichier, puis publication) :

- `PUT  /api/admin/mobile/releases/{version}/apk`      corps brut, en-têtes `X-Sha256` et `X-Filename` ;
- `POST /api/admin/mobile/releases/{version}/publish`  `{notes}` : la version devient visible ;
- `DELETE /api/admin/mobile/releases/{version}` ;
- `GET /api/mobile/latest?current=`                    404 `no_release` tant que rien n'est publié ;
- `GET /dl/android/{version}/{filename}`               l'APK (`application/vnd.android.package-archive`), compté.

Les fichiers vivent dans `releases/android/<version>/` : « android » n'est pas un numéro de version valide, le
dossier ne peut donc pas entrer en collision avec celui d'une version PC. L'APK n'est pas signé par le serveur :
il porte la signature Android de l'éditeur, et Android refuse d'installer par-dessus l'appli un APK signé par
une autre clé.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse
from pydantic import Field

from . import db, indexnow, notify
from .auth import api_error, require_publish_token, settings_of
from .config import Settings
from .ratelimit import limit
from .releases import (FILENAME_RE, SHA_RE, _counts_as_download, check_version, invalidate_site, truncate_notes,
                       version_key)
from .schemas import Lenient
from .stats import hit as stat_hit

log = logging.getLogger("dodo.mobile")
router = APIRouter()

APK_MEDIA_TYPE = "application/vnd.android.package-archive"
STAT_PLATFORM = "android"           # dimension de `dl_app` : l'APK apparaît à côté des plateformes PC dans l'admin


class MobilePublishIn(Lenient):
    notes: str = Field("", max_length=20000)


def mobile_dir(settings: Settings, version: str) -> Path:
    return settings.releases_dir / "android" / version


def dl_path(version: str, filename: str) -> str:
    """Chemin de téléchargement de l'APK, chaque segment encodé (les données viennent de la base)."""
    return f"/dl/android/{quote(str(version), safe='')}/{quote(str(filename), safe='')}"


def manifest(settings: Settings, row) -> dict:
    return {"version": row["version"], "published_at": row["published_at"], "notes": row["notes"] or "",
            "filename": row["filename"], "sha256": row["sha256"], "size": row["size"],
            "downloads": row["downloads"],
            "url": f"{settings.public_url}{dl_path(row['version'], row['filename'])}"}


def latest_row(conn: db.Connection):
    """Version publiée la plus récente (tri par numéro, pas par date), ou None."""
    rows = conn.execute("SELECT * FROM mobile_releases WHERE published_at IS NOT NULL").fetchall()
    return max(rows, key=lambda r: version_key(r["version"])) if rows else None


def latest_release(settings: Settings) -> dict | None:
    """Manifeste de la dernière version Android publiée (pages du site), ou None."""
    conn = db.connect(settings)
    try:
        row = latest_row(conn)
        return manifest(settings, row) if row is not None else None
    finally:
        conn.close()


# --- Public ----------------------------------------------------------------------

@router.get("/api/mobile/latest", dependencies=[Depends(limit("mobile_latest", 30, 60))])
def latest(request: Request, current: str = "", conn: db.Connection = Depends(db.get_db)):
    row = latest_row(conn)
    if row is None:
        raise api_error(404, "no_release", "Aucune version publiée.")
    m = manifest(settings_of(request), row)
    update_available = False
    if current:
        try:
            update_available = version_key(m["version"]) > version_key(current)
        except ValueError:
            raise api_error(422, "bad_version", "Paramètre current invalide.")
    m["update_available"] = update_available
    return m


def count_download(conn: db.Connection, version: str, app=None, via: str = "direct") -> None:
    """Un téléchargement de plus pour cet APK (`mobile_releases.downloads`) ; avec `app`, aussi dans les
    statistiques du jour, sous les mêmes clés que les versions PC (plateforme « android »)."""
    conn.execute("UPDATE mobile_releases SET downloads = downloads + 1 WHERE version=?", (version,))
    conn.commit()
    if app is not None:
        stat_hit(app, "dl_app", STAT_PLATFORM)
        stat_hit(app, "dl_app_version", f"{STAT_PLATFORM} {version}")
        stat_hit(app, "dl_app_via", via)


@router.get("/dl/android/{version}/{filename}", dependencies=[Depends(limit("dl", 10, 60))])
def download_apk(version: str, filename: str, request: Request, via: str = "",
                 conn: db.Connection = Depends(db.get_db)):
    """L'APK publié (FileResponse : Range/206 et ETag gérés par Starlette). Une version déposée mais pas encore
    publiée reste introuvable. `?via=site` : déjà compté par `/telecharger/go/android`."""
    check_version(version)
    if not FILENAME_RE.match(filename):
        raise api_error(404, "not_found", "Fichier inconnu.")
    row = conn.execute("SELECT filename FROM mobile_releases WHERE version=? AND published_at IS NOT NULL",
                       (version,)).fetchone()
    path = mobile_dir(settings_of(request), version) / filename
    if row is None or row["filename"] != filename or not path.is_file():
        raise api_error(404, "not_found", "Fichier inconnu.")
    if request.method != "HEAD" and via != "site" and _counts_as_download(request.headers.get("Range")):
        ua = request.headers.get("user-agent", "")
        count_download(conn, version, request.app, "app" if ua.startswith("DodoTopia") else "direct")
    return FileResponse(path, media_type=APK_MEDIA_TYPE, filename=filename,
                        headers={"Cache-Control": "public, max-age=3600"})


@router.head("/dl/android/{version}/{filename}", include_in_schema=False,
             dependencies=[Depends(limit("dl_head", 30, 60))])
def head_apk(version: str, filename: str, request: Request, conn: db.Connection = Depends(db.get_db)):
    """HEAD de l'APK : mêmes en-têtes que le GET, sans corps et sans compter de téléchargement."""
    return download_apk(version, filename, request, "", conn)


# --- Publication (jeton) ---------------------------------------------------------

@router.put("/api/admin/mobile/releases/{version}/apk", dependencies=[Depends(require_publish_token)])
async def put_apk(version: str, request: Request):
    """Corps brut streamé vers android/<version>/<filename>.part ; sha256 vérifié ; renommage atomique.
    Idempotent ; redéposer une version garde sa date de publication et son compteur."""
    settings = settings_of(request)
    check_version(version)
    sha = (request.headers.get("X-Sha256") or "").lower()
    filename = request.headers.get("X-Filename") or ""
    if not SHA_RE.match(sha):
        raise api_error(422, "bad_sha256", "En-tête X-Sha256 manquant ou invalide.")
    if not FILENAME_RE.match(filename) or not filename.lower().endswith(".apk"):
        raise api_error(422, "bad_filename", "En-tête X-Filename manquant ou invalide (attendu : un fichier .apk).")

    d = mobile_dir(settings, version)
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
        old = conn.execute("SELECT filename FROM mobile_releases WHERE version=?", (version,)).fetchone()
        if old is not None and old["filename"] != filename:
            try:
                (d / old["filename"]).unlink()
            except OSError:
                pass
        conn.execute(
            """INSERT INTO mobile_releases (version, filename, sha256, size) VALUES (?, ?, ?, ?)
               ON CONFLICT(version) DO UPDATE SET filename=excluded.filename, sha256=excluded.sha256,
               size=excluded.size""",
            (version, filename, sha, size),
        )
        conn.commit()
    finally:
        conn.close()
    invalidate_site(request)            # une version déjà publiée peut venir de changer de fichier
    return {"version": version, "filename": filename, "sha256": sha, "size": size,
            "url": f"{settings.public_url}{dl_path(version, filename)}"}


@router.post("/api/admin/mobile/releases/{version}/publish", dependencies=[Depends(require_publish_token)])
def publish(version: str, body: MobilePublishIn, request: Request, background_tasks: BackgroundTasks,
            conn: db.Connection = Depends(db.get_db)):
    """Publie une version Android déposée. Republier garde la date de la première publication."""
    settings = settings_of(request)
    check_version(version)
    row = conn.execute("SELECT * FROM mobile_releases WHERE version=?", (version,)).fetchone()
    if row is None:
        raise api_error(409, "missing_asset", "L'APK doit être déposé avant la publication.")
    conn.execute("UPDATE mobile_releases SET notes=?, published_at=? WHERE version=?",
                 (body.notes, row["published_at"] or db.now_iso(), version))
    conn.commit()
    invalidate_site(request)
    notify.emit(request.app, "release", f"DodoTopia Android {version} publiée",
                truncate_notes(body.notes or "", 800), url=f"{settings.public_url}/fr/android",
                fields=[("Fichier", row["filename"])])
    if settings.indexnow_key:
        background_tasks.add_task(indexnow.submit, settings, indexnow.mobile_urls(settings))
    return manifest(settings, conn.execute("SELECT * FROM mobile_releases WHERE version=?", (version,)).fetchone())


@router.delete("/api/admin/mobile/releases/{version}", dependencies=[Depends(require_publish_token)])
def delete_release(version: str, request: Request, conn: db.Connection = Depends(db.get_db)):
    settings = settings_of(request)
    check_version(version)
    if conn.execute("SELECT 1 FROM mobile_releases WHERE version=?", (version,)).fetchone() is None:
        raise api_error(404, "not_found", "Version inconnue.")
    conn.execute("DELETE FROM mobile_releases WHERE version=?", (version,))
    conn.commit()
    shutil.rmtree(mobile_dir(settings, version), ignore_errors=True)
    invalidate_site(request)
    return {"ok": True, "version": version}
