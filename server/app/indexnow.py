"""IndexNow : signale aux moteurs (Bing, Yandex, Seznam…) les URL nouvelles ou modifiées, sans attendre leur passage.

Actif seulement si `INDEXNOW_KEY` est défini : la clé est servie sur `/<clé>.txt` (preuve de propriété, route dans
`site.py`) et `submit()` est appelé en tâche de fond à la publication d'une version et à l'approbation d'un morceau
ou d'un dessin. Un échec (réseau, 4xx/5xx) est journalisé et rien d'autre : la requête d'origine a déjà répondu.
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

import httpx

from .config import Settings

log = logging.getLogger("dodo.indexnow")

ENDPOINT = "https://api.indexnow.org/indexnow"
MAX_URLS = 10_000                       # limite du protocole par requête
RELEASE_PAGES = ("home", "download", "news")


def key_location(settings: Settings) -> str:
    return f"{settings.public_url}/{settings.indexnow_key}.txt"


def payload(settings: Settings, urls: list[str]) -> dict:
    return {"host": urlsplit(settings.public_url).netloc, "key": settings.indexnow_key,
            "keyLocation": key_location(settings), "urlList": urls[:MAX_URLS]}


def submit(settings: Settings, urls: list[str]) -> bool:
    """POST des URL à IndexNow. True si la requête est partie et a été acceptée ; ne lève jamais."""
    if not settings.indexnow_key or not urls:
        return False
    try:
        r = httpx.post(ENDPOINT, json=payload(settings, urls), timeout=10,
                       headers={"Content-Type": "application/json; charset=utf-8"})
        r.raise_for_status()
    except Exception as e:  # noqa - réseau, 4xx/5xx : l'indexation attendra le passage normal des robots
        log.warning("IndexNow : envoi de %d URL échoué (%s)", len(urls), type(e).__name__)
        return False
    log.info("IndexNow : %d URL signalées", len(urls))
    return True


# Imports tardifs ci-dessous : `site` et ses pages importent `releases`, `library` et `gallery`, qui importent ce module.

def release_urls(settings: Settings) -> list[str]:
    """Pages qui changent à chaque version publiée : accueil, téléchargement et nouveautés, dans toutes les langues."""
    from . import site
    return [f"{settings.public_url}{site.url_for(lang, page_id)}" for page_id in RELEASE_PAGES for lang in site.LANGS]


def song_urls(settings: Settings, song_id: int, title: str) -> list[str]:
    from . import site
    from .site_pages.songs import song_url
    return [f"{settings.public_url}{song_url(lang, song_id, title)}" for lang in site.LANGS]


def drawing_urls(settings: Settings, drawing_id: int) -> list[str]:
    from . import site
    from .site_pages.gallery import drawing_url
    return [f"{settings.public_url}{drawing_url(lang, drawing_id)}" for lang in site.LANGS]
