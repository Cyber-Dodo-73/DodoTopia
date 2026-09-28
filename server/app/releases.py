"""Versions de l'app : manifeste public (signé Ed25519), dépôt des binaires par publish_release.py, publication,
compteur de téléchargements par asset et `GET /api/stats`."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from . import db, indexnow, notify
from .stats import hit as stat_hit
from .auth import api_error, require_publish_token, settings_of
from .config import Settings
from .ratelimit import limit
from .schemas import PublishIn

log = logging.getLogger("dodo.releases")
router = APIRouter()

PLATFORMS = ("windows-setup", "windows-portable", "linux-x64")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}$")
# Doit commencer par un caractere alphanumerique : exclut ".", ".." et les noms caches, donc tout
# nom qui designerait le dossier de la version au lieu d'un fichier dedans.
FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
STATS_CACHE_S = 60.0


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


def invalidate_site(request: Request) -> None:
    """Jette la page d'accueil en cache : elle annonce la derniere version publiee.

    Import tardif : `site` a besoin de `releases` pour construire le bloc de telechargement.
    """
    from . import site

    site.invalidate(request.app)


# --- Manifeste signé --------------------------------------------------------------

def signed_payload(version: str, assets: dict, mandatory: bool, published_at: str | None) -> str:
    """Texte exact que signe publish_release.py et que vérifie le client : JSON canonique (clés triées, sans
    espace, ASCII) de {version, assets{platform:{sha256, size, filename}}, mandatory, published_at}."""
    doc = {
        "version": version,
        "assets": {p: {"sha256": a["sha256"], "size": a["size"], "filename": a["filename"]}
                   for p, a in sorted(assets.items())},
        "mandatory": bool(mandatory),
        "published_at": published_at,
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":"))


def _b64(value: str, what: str, size: int | None = None) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise api_error(400, "bad_signature", f"{what} : base64 invalide.")
    if size is not None and len(raw) != size:
        raise api_error(400, "bad_signature", f"{what} : {len(raw)} octets au lieu de {size}.")
    return raw


def verify_signature(public_key_b64: str, payload: str, signature_b64: str) -> bool:
    """Vrai si `signature_b64` (Ed25519, base64) signe `payload` avec la clé publique donnée."""
    from nacl.exceptions import BadSignatureError  # import tardif : PyNaCl n'est chargé qu'à la publication
    from nacl.signing import VerifyKey

    key = _b64(public_key_b64, "Clé publique", 32)
    sig = _b64(signature_b64, "Signature", 64)
    try:
        VerifyKey(key).verify(payload.encode("utf-8"), sig)
    except BadSignatureError:
        return False
    return True


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
            "downloads": a["downloads"],
        }
    mandatory = bool(rel["mandatory"])
    return {"version": version, "published_at": rel["published_at"], "notes": rel["notes"] or "",
            "mandatory": mandatory, "assets": assets,
            "signature": rel["signature"],
            "signed_payload": signed_payload(version, assets, mandatory, rel["published_at"])}


def published_versions(conn: db.Connection) -> list[str]:
    rows = conn.execute("SELECT version FROM releases WHERE published_at IS NOT NULL").fetchall()
    return sorted((r["version"] for r in rows), key=version_key, reverse=True)


# --- Public ----------------------------------------------------------------------

@router.get("/api/releases/latest", dependencies=[Depends(limit("releases_latest", 30, 60))])
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


def _counts_as_download(range_header: str | None) -> bool:
    """Un téléchargement = une requête entière ou reprise depuis l'octet 0 ; les reprises partielles (`Range`
    au milieu du fichier) prolongent le même téléchargement et ne comptent pas."""
    if not range_header:
        return True
    return re.sub(r"\s", "", range_header).lower() == "bytes=0-"


def count_download(conn: db.Connection, version: str, filename: str, app=None, via: str = "direct") -> None:
    """Un téléchargement de plus pour cet asset (compteur `release_assets.downloads`, publié par /api/stats) ;
    avec `app`, aussi dans les statistiques du jour (plateforme, version, origine)."""
    conn.execute("UPDATE release_assets SET downloads = downloads + 1 WHERE version=? AND filename=?",
                 (version, filename))
    conn.commit()
    if app is not None:
        row = conn.execute("SELECT platform FROM release_assets WHERE version=? AND filename=?",
                           (version, filename)).fetchone()
        stat_hit(app, "dl_app", row["platform"] if row else "?")
        stat_hit(app, "dl_app_version", version)
        stat_hit(app, "dl_app_via", via)


@router.get("/dl/{version}/{filename}", dependencies=[Depends(limit("dl", 10, 60))])
def download_asset(version: str, filename: str, request: Request, via: str = "",
                   conn: db.Connection = Depends(db.get_db)):
    """Binaires publiés, servis par l'API (FileResponse : Range/206 et ETag gérés par Starlette).

    `?via=site` : la page de téléchargement du site passe par `/telecharger/go/<plateforme>`, qui a déjà compté
    ce téléchargement avant de rediriger ici — on ne le compte pas deux fois.
    """
    check_version(version)
    if not FILENAME_RE.match(filename):
        raise api_error(404, "not_found", "Fichier inconnu.")
    path = release_dir(settings_of(request), version) / filename
    if not path.is_file():
        raise api_error(404, "not_found", "Fichier inconnu.")
    if request.method != "HEAD" and via != "site" and _counts_as_download(request.headers.get("Range")):
        ua = request.headers.get("user-agent", "")
        count_download(conn, version, filename, request.app, "app" if ua.startswith("DodoTopia/") else "direct")
    return FileResponse(path, media_type="application/octet-stream", filename=filename,
                        headers={"Cache-Control": "public, max-age=3600"})


@router.head("/dl/{version}/{filename}", include_in_schema=False, dependencies=[Depends(limit("dl_head", 30, 60))])
def head_asset(version: str, filename: str, request: Request, conn: db.Connection = Depends(db.get_db)):
    """HEAD d'un binaire (gestionnaires de téléchargement, vérificateurs de liens) : mêmes en-têtes que le GET
    (`Content-Length`, `Accept-Ranges`), sans corps (FileResponse) et sans compter de téléchargement."""
    return download_asset(version, filename, request, "", conn)


def public_stats(app) -> dict:
    """Chiffres publics {downloads_total, songs_approved, users, rooms_open}, mis en cache STATS_CACHE_S secondes
    (la page d'accueil du site et les curieux ne pèsent pas sur la base)."""
    cached = getattr(app.state, "stats_cache", None)
    now = time.monotonic()
    if cached is None or cached[0] <= now:
        conn = db.connect(app.state.settings)
        try:
            downloads = conn.execute("SELECT COALESCE(SUM(downloads), 0) FROM release_assets").fetchone()[0]
            songs = conn.execute("SELECT COUNT(*) FROM songs WHERE status='approved'").fetchone()[0]
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            conn.close()
        body = {"downloads_total": int(downloads or 0), "songs_approved": int(songs), "users": int(users),
                "rooms_open": len(app.state.rooms.rooms)}
        cached = app.state.stats_cache = (now + STATS_CACHE_S, body)
    return dict(cached[1])


@router.get("/api/stats")
def stats(request: Request):
    return JSONResponse(public_stats(request.app), headers={"Cache-Control": f"public, max-age={int(STATS_CACHE_S)}"})


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


def _published_at_of(body: PublishIn) -> str:
    """Horodatage de publication : celui qui a été signé (fourni), sinon maintenant."""
    if body.published_at is None:
        return db.now_iso()
    try:
        datetime.fromisoformat(body.published_at.replace("Z", "+00:00"))
    except ValueError:
        raise api_error(422, "bad_published_at", "published_at doit être une date ISO 8601.")
    return body.published_at


# --- Annonce Discord ---------------------------------------------------------------

ANNOUNCE_NOTES_MAX = 1500
ANNOUNCE_COLOR = 0xE8A531


def truncate_notes(notes: str, limit: int = ANNOUNCE_NOTES_MAX) -> str:
    notes = (notes or "").strip()
    if len(notes) <= limit:
        return notes
    return notes[:limit - 1].rstrip() + "…"


def announce_payload(settings: Settings, version: str, notes: str) -> dict:
    return {"username": "DodoTopia", "allowed_mentions": {"parse": []},
            "embeds": [{"title": f"DodoTopia {version}", "url": f"{settings.public_url}/fr/telecharger",
                        "description": truncate_notes(notes) or f"DodoTopia {version} est disponible.",
                        "color": ANNOUNCE_COLOR}]}


def post_webhook(url: str, payload: dict) -> None:
    """POST du webhook Discord (isolé pour être remplacé dans les tests)."""
    r = httpx.post(url, json=payload, timeout=10)
    r.raise_for_status()


def announce_release(settings: Settings, version: str) -> bool:
    """Annonce une version publiée sur le webhook Discord, une seule fois : `releases.announced_at` est posé avant
    l'envoi par un UPDATE conditionnel (deux publications concurrentes ne peuvent pas annoncer toutes les deux),
    et remis à NULL si l'envoi échoue (une nouvelle publication réessaiera). Renvoie True si un message est parti."""
    url = (settings.DISCORD_ANNOUNCE_WEBHOOK or "").strip()
    if not url.startswith("https://"):
        return False
    conn = db.connect(settings)
    try:
        cur = conn.execute("UPDATE releases SET announced_at=? WHERE version=? AND published_at IS NOT NULL "
                           "AND announced_at IS NULL", (db.now_iso(), version))
        conn.commit()
        if cur.rowcount != 1:
            return False
        rel = conn.execute("SELECT notes FROM releases WHERE version=?", (version,)).fetchone()
        try:
            post_webhook(url, announce_payload(settings, version, (rel or {}).get("notes") or ""))
        except Exception as e:  # noqa - réseau, 4xx/5xx de Discord : on libère l'annonce pour un prochain essai
            log.warning("annonce Discord de %s échouée : %s", version, type(e).__name__)
            conn.execute("UPDATE releases SET announced_at=NULL WHERE version=?", (version,))
            conn.commit()
            return False
        return True
    finally:
        conn.close()


@router.post("/api/admin/releases/{version}/publish", dependencies=[Depends(require_publish_token)])
def publish(version: str, body: PublishIn, request: Request, background_tasks: BackgroundTasks,
            conn: db.Connection = Depends(db.get_db)):
    """Publie une version. Avec RELEASE_SIGNING_PUBLIC_KEY configurée, `signature` (Ed25519, base64) doit
    signer le `signed_payload` construit avec les assets déposés, `mandatory` et `published_at` fournis."""
    settings = settings_of(request)
    check_version(version)
    m = manifest(conn, settings, version)
    if m is None or "windows-setup" not in m["assets"]:
        raise api_error(409, "missing_asset", "L'installeur windows-setup doit être déposé avant la publication.")
    published_at = _published_at_of(body)
    if settings.RELEASE_SIGNING_PUBLIC_KEY:
        if not body.signature:
            raise api_error(422, "signature_required", "Ce serveur n'accepte que des manifestes signés.")
        payload = signed_payload(version, m["assets"], body.mandatory, published_at)
        if not verify_signature(settings.RELEASE_SIGNING_PUBLIC_KEY, payload, body.signature):
            log.warning("publication %s refusée : signature invalide", version)
            raise api_error(400, "bad_signature", "La signature ne correspond pas au manifeste.")
    elif body.signature:
        _b64(body.signature, "Signature", 64)   # au moins bien formée, même si personne ne la vérifie ici
    conn.execute("UPDATE releases SET notes=?, mandatory=?, published_at=?, signature=? WHERE version=?",
                 (body.notes, 1 if body.mandatory else 0, published_at, body.signature, version))
    conn.commit()
    invalidate_site(request)
    request.app.state.stats_cache = None
    if settings.DISCORD_ANNOUNCE_WEBHOOK:
        background_tasks.add_task(announce_release, settings, version)
    notify.emit(request.app, "release", f"DodoTopia {version} publiée",
                truncate_notes(body.notes or "", 800), url=f"{settings.public_url}/fr/telecharger",
                fields=[("Fichiers", ", ".join(sorted(m["assets"]))), ("Obligatoire", "oui" if body.mandatory else "non")])
    if settings.indexnow_key:
        background_tasks.add_task(indexnow.submit, settings, indexnow.release_urls(settings))
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
    invalidate_site(request)
    request.app.state.stats_cache = None
    return {"ok": True, "version": version}
