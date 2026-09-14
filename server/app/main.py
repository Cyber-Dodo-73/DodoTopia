"""Application FastAPI : assemblage des routeurs, tâches de fond, santé, page d'accueil.

Lancement : uvicorn app.main:app --host 0.0.0.0 --port 8000 (un seul worker : les salons vivent en mémoire).
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import auth, db, library, releases, rooms
from .config import SERVER_VERSION, Settings
from .ratelimit import RateLimiter
from .rooms import RoomManager

log = logging.getLogger("dodo")
CLEANUP_INTERVAL_S = 60


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

    app.include_router(auth.router)
    app.include_router(library.router)
    app.include_router(releases.router)
    app.include_router(rooms.router)

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

    @app.get("/", response_class=HTMLResponse)
    def index():
        conn = db.connect(settings)
        try:
            versions = releases.published_versions(conn)
            latest = releases.manifest(conn, settings, versions[0]) if versions else None
        finally:
            conn.close()
        if latest:
            links = "".join(f'<li><a href="{escape(a["url"])}">{escape(p)}</a> ({a["size"] // (1024 * 1024)} Mo)</li>'
                            for p, a in sorted(latest["assets"].items()))
            body = f"<p>Dernière version : <strong>{escape(latest['version'])}</strong></p><ul>{links}</ul>"
        else:
            body = "<p>Aucune version publiée pour l'instant.</p>"
        html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>DodoTopia</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;background:#fff7ee;color:#3b2a20;max-width:560px;margin:48px auto;
padding:0 16px}}a{{color:#1f8f88}}</style></head>
<body><h1>DodoTopia</h1><p>Serveur de mises à jour, bibliothèque MIDI et salons pour Heartopia.</p>{body}
<p><small>Serveur {SERVER_VERSION} · <a href="/api/health">état</a></small></p></body></html>"""
        return HTMLResponse(html)

    return app


app = create_app()
