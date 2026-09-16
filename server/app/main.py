"""Application FastAPI : assemblage des routeurs, tâches de fond, santé, fichiers statiques.

Le site public (pages `/{lang}/…`, robots/sitemap, 404) vit dans `site.py` + `site_pages/` ; `server/static`
est servi sur /static (feuille de style, polices locales, logo, captures, images de partage).

Lancement : uvicorn app.main:app --host 0.0.0.0 --port 8000 (un seul worker : les salons vivent en mémoire).
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from . import auth, db, gallery, importer, library, og, releases, rooms, site
from .config import SERVER_VERSION, Settings
from .ratelimit import RateLimiter
from .rooms import RoomManager

log = logging.getLogger("dodo")
CLEANUP_INTERVAL_S = 60
# Envoi des binaires de release (jeton de publication) : corps volumineux streamé, exempté du plafond.
BIG_BODY_PREFIXES = ("/api/admin/releases/",)


class BodySizeLimitMiddleware:
    """Coupe une requête dès que son corps dépasse `max_bytes`, avant que quiconque le lise.

    Sans ce rempart, Starlette déverse la totalité d'un envoi multipart dans un fichier temporaire
    (SpooledTemporaryFile, sans plafond pour les parties « fichier ») avant d'appeler le handler : le
    compteur d'octets de `library.read_upload` arrive alors trop tard et le disque est déjà rempli.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith(BIG_BODY_PREFIXES):
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            return await self._too_large(send)
        seen = 0

        async def limited_receive():
            """Corps tronqué net dès le dépassement (cas `Transfer-Encoding: chunked`, sans Content-Length) :
            le parseur multipart s'arrête là et le handler répond 400 au lieu de remplir le disque."""
            nonlocal seen
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    log.warning("corps de requête tronqué (plus de %d octets) sur %s",
                                self.max_bytes, scope.get("path"))
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        return await self.app(scope, limited_receive, send)

    async def _too_large(self, send) -> None:
        body = (b'{"detail":{"code":"too_large","message":"Requ\\u00eate trop volumineuse."}}')
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def cleanup_once(settings: Settings, limiter: RateLimiter) -> None:
    """Tickets/sessions périmés, morceaux éphémères trop vieux, seaux de limitation inactifs."""
    conn = db.connect(settings)
    try:
        auth.cleanup(conn, settings)
    finally:
        conn.close()
    cutoff = time.time() - settings.TMP_SONG_TTL_S
    for p in settings.tmp_dir.glob("*.mid"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass
    importer.purge_cache(settings)
    og.purge_cache(settings)
    limiter.prune()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init(settings)
        app.state.rooms.start()

        async def cleanup_loop():
            while True:
                await asyncio.sleep(CLEANUP_INTERVAL_S)
                try:
                    await asyncio.to_thread(cleanup_once, settings, app.state.ratelimiter)
                except Exception:
                    log.exception("cleanup")

        task = asyncio.create_task(cleanup_loop())
        try:
            yield
        finally:
            task.cancel()
            await app.state.rooms.stop()

    app = FastAPI(title="DodoTopia", version=SERVER_VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.ratelimiter = RateLimiter(enabled=settings.RATE_LIMIT != 0)
    app.state.rooms = RoomManager(settings)
    app.state.site_cache = {}           # (page_id, lang) -> (expiration, html, etag) des pages du site
    app.state.stats_cache = None        # (expiration, dict) de GET /api/stats
    app.state.import_tokens = {}        # jeton -> fichier importé par lien (usage unique, 10 min)

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(site.SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(GZipMiddleware, minimum_size=1024)      # le plus externe : compresse après les en-têtes

    app.include_router(site.static_router)   # /static/site.<hash>.css, avant le montage de /static
    app.mount("/static", StaticFiles(directory=site.STATIC_DIR), name="static")

    app.include_router(auth.router)
    app.include_router(library.router)
    app.include_router(gallery.router)
    app.include_router(importer.router)
    app.include_router(og.router)
    app.include_router(releases.router)
    app.include_router(rooms.router)

    # Chemins de l'API et des fichiers : erreurs JSON (contrat du client). Tout le reste : page 404 du site,
    # traduite, `noindex`.
    api_prefixes = ("/api/", "/auth/", "/dl/", "/ws", "/static/", "/og/")

    @app.exception_handler(StarletteHTTPException)
    async def not_found_page(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and not request.url.path.startswith(api_prefixes):
            return site.not_found_response(request)
        return await http_exception_handler(request, exc)

    @app.get("/api/health")
    def health(request: Request):
        db_status = "ok"
        dialect = "?"
        try:
            conn = db.connect(settings)
            try:
                conn.execute("SELECT 1").fetchone()
                dialect = conn.dialect
            finally:
                conn.close()
        except Exception:
            db_status = "error"
        body = {"status": "ok" if db_status == "ok" else "degraded", "version": SERVER_VERSION,
                "min_client": settings.MIN_CLIENT_VERSION, "db": db_status, "db_dialect": dialect,
                "rooms": len(app.state.rooms.rooms)}
        return JSONResponse(body, status_code=200 if db_status == "ok" else 503,
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/time")
    def server_time():
        return JSONResponse({"server_now_ms": rooms.srv_ms()}, headers={"Cache-Control": "no-store"})

    # En dernier : '/', `/{lang}/…` et `/{segment}` attrapent tout chemin que personne d'autre n'a servi.
    app.include_router(site.router)

    return app


app = create_app()
