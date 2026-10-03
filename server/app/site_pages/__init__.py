"""Contenu des pages du site public : un module par page, `render(settings, lang, ctx) -> body` (HTML de
<main>). Le gabarit, les routes et le cache sont dans `site.py` ; les textes dans `locales/<lang>.json`."""
from __future__ import annotations

from . import activities, android, community, download, errors, gallery, help, home, instruments, legal, news, room, songs

# page_id -> module. Les cinq activités partagent un module (même structure, textes différents).
MODULES = {
    "home": home,
    "music": activities.Music,
    "draw": activities.Draw,
    "cook": activities.Cook,
    "creations": activities.Creations,
    "together": activities.Together,
    "download": download,
    "instruments": instruments,
    "news": news,
    "community": community,
    "help": help,
    "legal": legal.Mentions,
    "privacy": legal.Privacy,
    "terms": legal.Terms,
    "songs": songs,
    "gallery": gallery,
    "android": android,
}

__all__ = ["MODULES", "errors", "room"]
