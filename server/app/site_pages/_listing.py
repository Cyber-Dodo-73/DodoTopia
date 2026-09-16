"""Outils communs aux pages publiques alimentées par la base (morceaux, galerie, salons) : slugs, textes bruts pour
les balises <title>/<meta>, pagination, boutons « Ouvrir dans DodoTopia »."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlencode

from ..i18n import lookup, t
from ..site import esc, url_for


def slugify(text: str, fallback: str = "song", max_len: int = 60) -> str:
    """« Für Élise (piano) » -> `fur-elise-piano` : ASCII minuscule, tirets, 60 caractères au plus."""
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = s[:max_len].rstrip("-")
    return s or fallback


def plain(lang: str, key: str, **params) -> str:
    """Texte d'un catalogue avec paramètres **non échappés** : pour `ctx.title`/`ctx.description`, que le gabarit
    échappe lui-même (`t()` échapperait deux fois)."""
    value = lookup(lang, key)
    if value is None:
        return f"[{key}]"
    return re.sub(r"\{([A-Za-z_]\w*)\}", lambda m: str(params.get(m.group(1), m.group(0))), value)


def shorten(text: str, n: int) -> str:
    text = str(text or "")
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def duration(seconds) -> str:
    s = int(round(float(seconds or 0)))
    return f"{s // 60}:{s % 60:02d}"


def page_int(value, default: int = 1, maximum: int = 10_000) -> int:
    try:
        n = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(1, min(n, maximum))


def pager(lang: str, page_id: str, query: dict, page: int, pages: int) -> str:
    if pages <= 1:
        return ""
    base = url_for(lang, page_id)

    def href(n: int) -> str:
        q = {k: v for k, v in query.items() if k != "page"}
        if n > 1:
            q["page"] = n
        return f"{base}?{urlencode(q)}" if q else base

    prev = (f'<a class="btn btn--quiet" rel="prev" href="{esc(href(page - 1))}">{esc(t(lang, "site.listing.prev"))}</a>'
            if page > 1 else "")
    nxt = (f'<a class="btn btn--quiet" rel="next" href="{esc(href(page + 1))}">{esc(t(lang, "site.listing.next"))}</a>'
           if page < pages else "")
    label = t(lang, "site.listing.page_of", page=page, pages=pages)
    return (f'<nav class="pager" aria-label="{esc(t(lang, "site.listing.pagination"))}">{prev}'
            f'<span class="pager__pos">{label}</span>{nxt}</nav>')


def app_buttons(lang: str, deep_link: str, open_key: str, latest: dict | None) -> str:
    """Bouton principal vers le lien profond `dodotopia://…`, et repli « Télécharger DodoTopia » (page de
    téléchargement : jamais un lien mort, même sans version publiée)."""
    download = t(lang, "site.common.download_cta") if latest else t(lang, "site.common.soon_cta")
    return (f'<div class="actions">'
            f'<a class="btn btn--cta" href="{esc(deep_link)}">{esc(t(lang, open_key))}</a>'
            f'<a class="btn btn--quiet" href="{url_for(lang, "download")}">{esc(download)}</a></div>'
            f'<p class="dl-note">{t(lang, "site.listing.open_note")}</p>')
