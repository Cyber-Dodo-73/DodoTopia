"""Site public multilingue : gabarit, routes, cache, sitemap, en-têtes de sécurité.

- Le contenu des pages vit dans `site_pages/<page>.py` (un `render(settings, lang, ctx) -> body` par page) ;
  les textes viennent des catalogues `locales/<lang>.json` via `i18n.t()`. Toute donnée dynamique passe par
  `esc()` avant d'entrer dans le HTML.
- URL : `/{lang}/{slug}` pour toutes les langues (français compris), `/` redirige (302) selon
  `Accept-Language`, les anciennes URL françaises à la racine redirigent (301) vers `/fr/...`.
- Chaque page rendue est gardée en cache mémoire par `(page_id, lang)` pendant `SITE_PAGE_TTL_S`, avec le
  marqueur `__NONCE__` à la place du nonce CSP, substitué à l'envoi ; `invalidate(app)` vide tout.
- Aucune ressource externe (sauf Plausible si `PLAUSIBLE_SCRIPT_URL` est défini) : feuille de style, polices,
  images et JSON-LD sont servis d'ici.
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import secrets
import struct
import time
from datetime import datetime
from functools import cached_property
from html import escape
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, i18n, legal_md, mobile_releases, releases
from .config import SERVER_VERSION
from .i18n import DEFAULT_LANG, LANG_INFO, LANGS, t

log = logging.getLogger("dodo")
router = APIRouter()
static_router = APIRouter()      # monté AVANT /static : la feuille de style au nom haché

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
OG_DIR = STATIC_DIR / "og"

# Windows ne connaît pas .woff2 dans la base de registre : sans ça StaticFiles renvoie
# application/octet-stream pour les polices.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/x-icon", ".ico")     # même type pour /favicon.ico et /static/favicon.ico

NONCE = "__NONCE__"                     # marqueur dans le HTML en cache, remplacé à chaque envoi
LAST_UPDATE_ISO = "2026-09-28"          # dernière mise à jour du contenu rédigé (légal, aide) ; sitemap lastmod
LAST_UPDATE = {"fr": "28 septembre 2026", "en": "September 28, 2026"}
STATIC_IMMUTABLE = "public, max-age=31536000, immutable"
STATIC_SHORT = "public, max-age=86400"
FAVICON_CACHE = "public, max-age=604800"
# Robots : indexable, et aperçu d'image de grande taille autorisé dans les résultats (sans cette directive,
# Google peut se limiter à une vignette minuscule de la capture d'écran). Les pages `noindex` la remplacent.
ROBOTS_INDEX = "index, follow, max-image-preview:large"
REDIRECT_CACHE = "public, max-age=3600"
# Pages HTML : toujours revalidées (ETag -> 304, quelques octets). Avec « max-age=3600 », un navigateur gardait
# une heure l'ancienne version d'une page déjà visitée : après la refonte, le propriétaire voyait encore l'ancien
# site sur Dessin, Cuisine et Aide. Le cache du rendu reste côté serveur (SITE_PAGE_TTL_S).
HTML_CACHE = "public, max-age=0, must-revalidate"

MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre")
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")
MONTHS = {
    "fr": MONTHS_FR, "en": MONTHS_EN,
    "es": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"),
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"),
    "pt-BR": ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
              "novembro", "dezembro"),
    "th": ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน",
           "ตุลาคม", "พฤศจิกายน", "ธันวาคม"),
    "id": ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
           "November", "Desember"),
    "fil": ("Enero", "Pebrero", "Marso", "Abril", "Mayo", "Hunyo", "Hulyo", "Agosto", "Setyembre", "Oktubre",
            "Nobyembre", "Disyembre"),
}

# --------------------------------------------------------------------------------------------------
# Identité de l'éditeur et de l'hébergeur (mentions légales, confidentialité). LCEN art. 6-III, RGPD art. 13.
EDITEUR_NOM = "Dorian Breuillard"
EDITEUR_MARQUE = "Cyber-Dodo"
EDITEUR_SIRET = "925 110 132 00022"
EDITEUR_ADRESSE = "718 chemin de la Cassine, 73000 Chambéry, France"
EDITEUR_COURRIEL = "contact@cyber-dodo.fr"
EDITEUR_TEL = "07 72 28 20 62"
EDITEUR_TEL_INTL = "+33 7 72 28 20 62"
HEBERGEUR_NOM = "OUIHEBERG SARL"
HEBERGEUR_ADRESSE = "9 rue des Colonnes, 75002 Paris, France"
HEBERGEUR_CONTACT = "RCS Paris 888 341 997 — ouiheberg.com"
SITE_HOST = "dodotopia.cyber-dodo.fr"
SITE_NAME = "DodoTopia"                  # nom du site (marque du produit) ; l'éditeur est EDITEUR_MARQUE

# Icônes du site (générées par .tools/make_favicons.py depuis logo.png) : (chemin public, rel, type, sizes).
# URL stables, sans empreinte `?v=` : Google et les navigateurs veulent une adresse de favicon qui ne change pas.
ICONS = (
    ("/favicon.ico", "icon", "image/x-icon", "16x16 32x32 48x48"),
    ("/static/favicon-96.png", "icon", "image/png", "96x96"),
    ("/static/favicon-192.png", "icon", "image/png", "192x192"),
    ("/static/apple-touch-icon.png", "apple-touch-icon", "image/png", "180x180"),
)

# --------------------------------------------------------------------------------------------------
# Registre des pages : identifiant -> slug par langue (ASCII ; traduit pour fr/en/es/de/pt-BR, anglais pour
# zh-CN/ja/th/id/fil). L'accueil a le slug vide (`/{lang}/`).
ROUTES: dict[str, dict[str, str]] = {
    "home": {"fr": "", "en": "", "es": "", "de": "", "pt-BR": ""},
    "music": {"fr": "musique", "en": "music", "es": "musica", "de": "musik", "pt-BR": "musica"},
    "draw": {"fr": "dessin", "en": "drawing", "es": "dibujo", "de": "zeichnen", "pt-BR": "desenho"},
    "cook": {"fr": "cuisine", "en": "cooking", "es": "cocina", "de": "kochen", "pt-BR": "cozinha"},
    "creations": {"fr": "mes-creations", "en": "my-creations", "es": "mis-creaciones", "de": "meine-kreationen",
                  "pt-BR": "minhas-criacoes"},
    "together": {"fr": "jouer-ensemble", "en": "play-together", "es": "tocar-juntos", "de": "zusammen-spielen",
                 "pt-BR": "tocar-juntos"},
    "download": {"fr": "telecharger", "en": "download", "es": "descargar", "de": "herunterladen",
                 "pt-BR": "baixar"},
    "instruments": {"fr": "instruments", "en": "instruments", "es": "instrumentos", "de": "instrumente",
                    "pt-BR": "instrumentos"},
    "news": {"fr": "nouveautes", "en": "whats-new", "es": "novedades", "de": "neuigkeiten", "pt-BR": "novidades"},
    "community": {"fr": "communaute", "en": "community", "es": "comunidad", "de": "community",
                  "pt-BR": "comunidade"},
    "help": {"fr": "aide", "en": "help", "es": "ayuda", "de": "hilfe", "pt-BR": "ajuda"},
    "legal": {"fr": "mentions-legales", "en": "legal-notice", "es": "aviso-legal", "de": "impressum",
              "pt-BR": "aviso-legal"},
    "privacy": {"fr": "confidentialite", "en": "privacy", "es": "privacidad", "de": "datenschutz",
                "pt-BR": "privacidade"},
    "terms": {"fr": "conditions", "en": "terms", "es": "condiciones", "de": "nutzungsbedingungen",
              "pt-BR": "termos"},
    "songs": {"fr": "morceaux", "en": "songs", "es": "canciones", "de": "lieder", "pt-BR": "musicas"},
    "gallery": {"fr": "galerie", "en": "gallery", "es": "galeria", "de": "galerie", "pt-BR": "galeria"},
    # L'appli Android : « android » se dit pareil partout, un seul slug pour toutes les langues.
    "android": {"fr": "android", "en": "android", "es": "android", "de": "android", "pt-BR": "android"},
}
# Pages sans page d'index : lien d'invitation vers un salon (`/{lang}/<slug>/<CODE>`, `noindex`).
ROOM_SLUGS = {"fr": "salon", "en": "room", "es": "sala", "de": "raum", "pt-BR": "sala"}
for _slugs in (*ROUTES.values(), ROOM_SLUGS):
    for _lang in LANGS:
        _slugs.setdefault(_lang, _slugs["en"])
PAGE_IDS = tuple(ROUTES)
_FR_SLUGS = {slugs["fr"]: page_id for page_id, slugs in ROUTES.items()}

# Ambiance de couleur par rubrique : classe `theme-<nom>` sur <body> (et sur les sections de l'accueil), lue par
# la feuille de style à travers les variables `--t-*`. Tout le reste est « neutral ».
THEMES = {"music": "music", "draw": "draw", "cook": "cook", "creations": "draw", "together": "rooms",
          "songs": "music", "gallery": "draw"}


def theme_of(page_id: str) -> str:
    return THEMES.get(page_id, "neutral")


# Pages dont le contenu vient de la base (dernière version, morceaux, dessins) : TTL court.
DB_PAGES = frozenset({"home", "download", "news", "songs", "gallery", "android"})
# Hints du sitemap (changefreq, priority).
SITEMAP_HINTS = {"home": ("weekly", "1.0"), "download": ("weekly", "0.9"), "news": ("weekly", "0.6"),
                 "music": ("monthly", "0.8"), "draw": ("monthly", "0.8"), "cook": ("monthly", "0.8"),
                 "creations": ("monthly", "0.8"),
                 "together": ("monthly", "0.7"), "instruments": ("monthly", "0.7"), "help": ("monthly", "0.7"),
                 "community": ("monthly", "0.5"), "songs": ("daily", "0.8"), "gallery": ("daily", "0.7"),
                 "android": ("weekly", "0.8")}
ANDROID_PAGE_ISO = "2026-10-03"         # mise en ligne de la page Android ; son lastmod suit ensuite les APK publiés
SITE_CACHE_MAX = 2000               # entrées du cache de pages (fiches de morceaux et de dessins comprises)
SITEMAP_DEFAULT = ("yearly", "0.3")

# Anciennes URL (site monolingue) : slug français à la racine -> 301 vers /fr/<slug>.
LEGACY_SLUGS = {slugs["fr"]: page_id for page_id, slugs in ROUTES.items() if slugs["fr"]}
# Adresses courtes sans langue, nées après le site monolingue : 302 vers la langue du navigateur.
SHORT_SLUGS = {LEGACY_SLUGS.pop("android"): "android"}

# Plateformes de `/telecharger/go/<platform>` -> identifiants d'asset de releases.PLATFORMS.
GO_PLATFORMS = {"windows": "windows-setup", "windows-setup": "windows-setup",
                "portable": "windows-portable", "windows-portable": "windows-portable",
                "linux": "linux-x64", "linux-x64": "linux-x64"}
GO_ANDROID = ("android", "apk")         # même lien compteur, mais canal à part (mobile_releases.py)


def esc(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def human_size(n: int, lang: str = "fr") -> str:
    """Taille en Mo, avec une décimale sous 100 Mo (les binaires font entre 30 et 300 Mo)."""
    mo = max(0, int(n)) / (1024 * 1024)
    txt = f"{mo:.1f}" if mo < 100 else f"{mo:.0f}"
    if lang == "fr":
        return txt.replace(".", ",") + " Mo"
    return txt + " MB"


def human_date(iso: str | None, lang: str = "fr") -> str:
    """Date lisible : « 14 septembre 2026 » (fr), « 14 September 2026 » (en), ISO ailleurs."""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    month = d.month - 1
    if lang == "fr":
        return f"{d.day} {MONTHS_FR[month]} {d.year}"
    if lang == "en":
        return f"{MONTHS_EN[month]} {d.day}, {d.year}"
    if lang in ("es", "pt-BR"):
        return f"{d.day} de {MONTHS[lang][month]} de {d.year}"
    if lang == "de":
        return f"{d.day}. {MONTHS['de'][month]} {d.year}"
    if lang in ("zh-CN", "ja"):
        return f"{d.year}年{d.month}月{d.day}日"
    if lang in ("th", "id"):
        return f"{d.day} {MONTHS[lang][month]} {d.year}"
    if lang == "fil":
        return f"{MONTHS['fil'][month]} {d.day}, {d.year}"
    return d.strftime("%Y-%m-%d")


def dl_path(version: str, filename: str) -> str:
    """Chemin de téléchargement, chaque segment encodé (les données viennent de la base)."""
    return f"/dl/{quote(str(version), safe='')}/{quote(str(filename), safe='')}"


_QUOTE_MARK = chr(0xE000)               # zone à usage privé : remplace `"` le temps de la conversion Markdown
_NOTES_HEADING = re.compile(r"<(/?)h[1-3]>")
_NOTES_DEEP_HEADING = re.compile(r"^#{4,6}(?=\s)")


def notes_line_count(raw: str | None) -> int:
    """Nombre de lignes non vides des notes d'une version (ce que compte `max_items` de `notes_html`)."""
    return sum(1 for line in (raw or "").splitlines() if line.strip())


def notes_html(raw: str | None, max_items: int | None = None) -> str:
    """Notes de version (Markdown du CHANGELOG : listes, **gras**, `code`, liens https) -> HTML sûr.

    Le rendu est celui de `legal_md.markdown_to_html`, qui échappe tout le texte avant d'ajouter son balisage ;
    les guillemets sont échappés en plus (`&quot;`, y compris dans l'adresse d'un lien : pas d'attribut injecté),
    les titres sont rétrogradés en <h4> (la page a déjà son <h1> et un <h2> par version), et `max_items` garde les
    N premières lignes non vides AVANT la conversion (couper du HTML laisserait des balises ouvertes)."""
    lines: list[str] = []
    kept = 0
    for line in (raw or "").replace(_QUOTE_MARK, "").strip().splitlines():
        if line.strip():
            if max_items is not None and kept >= max_items:
                break
            kept += 1
            line = _NOTES_DEEP_HEADING.sub("###", line)
            if line.lstrip().startswith("•"):
                line = line.replace("•", "-", 1)
        lines.append(line)
    if not kept:
        return ""
    html = legal_md.markdown_to_html("\n".join(lines).replace('"', _QUOTE_MARK))
    return _NOTES_HEADING.sub(r"<\1h4>", html).replace(_QUOTE_MARK, "&quot;")


def last_update(lang: str) -> str:
    """Date de dernière mise à jour du contenu rédigé, dans le format de la langue."""
    return human_date(LAST_UPDATE_ISO, lang) or LAST_UPDATE_ISO


def url_for(lang: str, page_id: str, anchor: str = "") -> str:
    slug = ROUTES[page_id][lang]
    url = f"/{lang}/{slug}"
    return f"{url}#{anchor}" if anchor else url


def _resolve_fr_link(lang: str, fr_slug: str) -> str | None:
    page_id = _FR_SLUGS.get(fr_slug)
    return url_for(lang, page_id) if page_id else None


i18n.set_link_resolver(_resolve_fr_link)


def page_for(lang: str, slug: str) -> str | None:
    for page_id, slugs in ROUTES.items():
        if slugs[lang] == slug:
            return page_id
    return None


def png_size(path: Path) -> tuple[int, int] | None:
    """Dimensions réelles d'un PNG (en-tête IHDR) : la place est réservée, rien ne saute au chargement."""
    try:
        head = path.read_bytes()[:24]
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return (w, h) if 0 < w <= 8192 and 0 < h <= 8192 else None


# --- Fichiers statiques versionnés ----------------------------------------------------------------

_STATIC_HASHES: dict[str, str] = {}


def static_hash(name: str) -> str:
    """Empreinte courte d'un fichier de /static, calculée une fois (au premier rendu après le démarrage)."""
    h = _STATIC_HASHES.get(name)
    if h is None:
        try:
            h = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:10]
        except OSError:
            h = "0"
        _STATIC_HASHES[name] = h
    return h


def static_url(name: str) -> str:
    """`/static/<name>?v=<hash>` : URL immuable, cache d'un an, renouvelée dès que le fichier change."""
    return f"/static/{quote(name)}?v={static_hash(name)}"


def css_href() -> str:
    return f"/static/site.{static_hash('site.css')}.css"


@static_router.get("/static/site.{digest}.css", include_in_schema=False)
def hashed_css(digest: str):
    """`site.<hash>.css` : le même fichier que /static/site.css, sous un nom qui change avec son contenu."""
    if digest != static_hash("site.css"):
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(STATIC_DIR / "site.css", media_type="text/css",
                        headers={"Cache-Control": STATIC_IMMUTABLE})


# --- Cache ------------------------------------------------------------------------------------------

def invalidate(app) -> None:
    """Jette toutes les pages en cache (publication / suppression d'une version)."""
    app.state.site_cache = {}


def _cache_get(app, key):
    cache = getattr(app.state, "site_cache", None)
    if cache is None:
        cache = app.state.site_cache = {}
    entry = cache.get(key)
    if entry is not None and entry[0] > time.monotonic():
        return entry
    return None


def _cache_put(app, key, ttl: float, html: str) -> tuple[str, str]:
    etag = 'W/"' + hashlib.sha1(html.encode("utf-8")).hexdigest()[:20] + '"'
    cache = app.state.site_cache
    if len(cache) >= SITE_CACHE_MAX:
        cache.clear()
    cache[key] = (time.monotonic() + ttl, html, etag)
    return html, etag


class Ctx:
    """Contexte de rendu d'une page : accès paresseux à la base (une requête au plus par donnée), nonce CSP
    (marqueur), et blocs à ajouter dans <head> (JSON-LD…).

    Pages dynamiques (listes filtrées, fiches) : `query` porte les paramètres d'URL, et le rendu peut fixer
    `title`, `description`, `paths` ({lang: chemin} pour canonical/hreflang), `og` ((url, l, h, alt)), `crumb`
    ((nom, chemin de la langue) : troisième niveau du fil d'Ariane) et `canonical` (False : ni canonical ni
    hreflang)."""

    nonce = NONCE

    def __init__(self, app, lang: str, page_id: str, query: dict | None = None):
        self.app = app
        self.settings = app.state.settings
        self.lang = lang
        self.page_id = page_id
        self.head: list[str] = []
        self.robots = ROBOTS_INDEX
        self.query = query or {}
        self.title: str | None = None
        self.description: str | None = None
        self.paths: dict[str, str] | None = None
        self.og: tuple | None = None
        self.crumb: tuple[str, str] | None = None
        self.canonical = True
        self.body_class: str | None = None      # remplace `page-<id> theme-<thème>` (404, salon)

    @cached_property
    def latest(self) -> dict | None:
        return latest_release(self.settings)

    @cached_property
    def mobile(self) -> dict | None:
        """Dernière version Android publiée (canal à part des versions PC), ou None."""
        return mobile_releases.latest_release(self.settings)

    @cached_property
    def releases(self) -> list[dict]:
        return published_releases(self.settings, limit=20)

    @cached_property
    def stats(self) -> dict:
        try:
            return releases.public_stats(self.app)
        except Exception:               # noqa - la base peut être indisponible : compteurs absents, page servie
            log.exception("stats du site")
            return {}


def latest_release(settings) -> dict | None:
    conn = db.connect(settings)
    try:
        versions = releases.published_versions(conn)
        return releases.manifest(conn, settings, versions[0]) if versions else None
    finally:
        conn.close()


def published_releases(settings, limit: int = 20) -> list[dict]:
    conn = db.connect(settings)
    try:
        versions = releases.published_versions(conn)[:limit]
        return [m for m in (releases.manifest(conn, settings, v) for v in versions) if m]
    finally:
        conn.close()


def render_page(app, page_id: str, lang: str, query: dict | None = None) -> tuple[str, str]:
    """(HTML avec marqueur de nonce, ETag faible) — depuis le cache si possible.

    Avec `query` (liste filtrée, page 2…) : cache par (page, langue, paramètres normalisés)."""
    key = (page_id, lang, tuple(sorted(query.items()))) if query else (page_id, lang)
    entry = _cache_get(app, key)
    if entry is not None:
        return entry[1], entry[2]
    settings = app.state.settings
    from . import site_pages                                   # import tardif : les pages utilisent ce module
    module = site_pages.MODULES[page_id]
    ctx = Ctx(app, lang, page_id, query)
    body = module.render(settings, lang, ctx)
    html = page(settings, lang, page_id, body, ctx)
    ttl = settings.SITE_PAGE_TTL_S if page_id in DB_PAGES else max(settings.SITE_PAGE_TTL_S, 3600)
    return _cache_put(app, key, ttl, html)


def render_dynamic(app, lang: str, page_id: str, key: tuple | None, builder) -> tuple[str, str] | None:
    """Fiche rendue par `builder(settings, lang, ctx) -> body | None` (None : introuvable). Mise en cache sous
    `key` (TTL des pages liées à la base) si `key` est fourni."""
    if key is not None:
        entry = _cache_get(app, key)
        if entry is not None:
            return entry[1], entry[2]
    settings = app.state.settings
    ctx = Ctx(app, lang, page_id)
    body = builder(settings, lang, ctx)
    if body is None:
        return None
    html = page(settings, lang, page_id, body, ctx)
    if key is None:
        etag = 'W/"' + hashlib.sha1(html.encode("utf-8")).hexdigest()[:20] + '"'
        return html, etag
    return _cache_put(app, key, settings.SITE_PAGE_TTL_S, html)


def render_not_found(app, lang: str) -> str:
    from .site_pages import errors
    settings = app.state.settings
    ctx = Ctx(app, lang, "home")
    ctx.robots = "noindex, nofollow"
    body = errors.render(settings, lang, ctx)
    return page(settings, lang, "home", body, ctx, title=t(lang, "site.errors.404.title"),
                description=t(lang, "site.errors.404.description"), canonical=False)


# --- Gabarit ----------------------------------------------------------------------------------------

def og_image(settings, page_id: str, lang: str) -> tuple[str, int, int, str]:
    """(URL, largeur, hauteur, alt) de l'image de partage : celle de la page si elle existe, sinon le logo."""
    base = settings.public_url
    name = f"og/{page_id}-{lang}.png"
    size = png_size(STATIC_DIR / name)
    if size:
        return f"{base}{static_url(name)}", size[0], size[1], t(lang, "site.meta.og_alt")
    return f"{base}{static_url('logo.png')}", 512, 512, t(lang, "site.brand.logo_alt")


def ld_script(data: dict, nonce: str = NONCE) -> str:
    """JSON-LD dans un <script> : `<`, `&` neutralisés (un `</script>` dans une donnée ne peut rien casser)."""
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    return f'<script type="application/ld+json" nonce="{nonce}">{body}</script>\n'


def organization_id(settings) -> str:
    return f"{settings.public_url}/#organization"


def organization_ld(settings) -> dict:
    """L'éditeur (Cyber-Dodo), distinct de la marque du site : nœud identifié, référencé par `WebSite.publisher` et
    `SoftwareApplication.author`. Sans `@context` : il vit dans le `@graph` de `site_ld`."""
    base = settings.public_url
    return {"@type": "Organization", "@id": organization_id(settings), "name": EDITEUR_MARQUE, "url": f"{base}/",
            "logo": f"{base}/static/logo.png", "email": EDITEUR_COURRIEL,
            "founder": {"@type": "Person", "name": EDITEUR_NOM}}


def website_ld(settings) -> dict:
    """Nom du site pour les moteurs (Google : « site names », lu sur la page d'accueil du domaine ou du
    sous-domaine). `url` est la racine du site, celle qui redirige vers une langue : le même nœud, identique, est
    servi sur toutes les pages, donc sur chaque accueil traduit où la redirection peut mener le robot."""
    base = settings.public_url
    return {"@type": "WebSite", "@id": f"{base}/#website", "name": SITE_NAME, "url": f"{base}/",
            "publisher": {"@id": organization_id(settings)}}


def site_ld(settings) -> dict:
    """Un seul script JSON-LD pour le site et son éditeur : jamais deux nœuds `WebSite` sur une page."""
    return {"@context": "https://schema.org", "@graph": [website_ld(settings), organization_ld(settings)]}


def breadcrumb_ld(settings, lang: str, page_id: str, crumb: tuple[str, str] | None = None) -> dict:
    base = settings.public_url
    items = [
        {"@type": "ListItem", "position": 1, "name": t(lang, "site.nav.home"), "item": f"{base}{url_for(lang, 'home')}"},
        {"@type": "ListItem", "position": 2, "name": t(lang, f"site.nav.{page_id}"),
         "item": f"{base}{url_for(lang, page_id)}"},
    ]
    if crumb:
        items.append({"@type": "ListItem", "position": 3, "name": crumb[0], "item": f"{base}{crumb[1]}"})
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


def software_ld(settings, lang: str, latest: dict | None) -> dict:
    base = settings.public_url
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "DodoTopia",
        "description": t(lang, "site.meta.home.description"),
        "url": f"{base}{url_for(lang, 'home')}",
        "image": f"{base}/static/logo.png",
        "applicationCategory": "GameApplication",
        "applicationSubCategory": t(lang, "site.meta.app_subcategory"),
        "operatingSystem": "Windows 10, Windows 11, Linux",
        "inLanguage": lang,
        "isAccessibleForFree": True,
        "author": {"@type": "Organization", "@id": organization_id(settings), "name": EDITEUR_MARQUE,
                   "url": f"{base}/"},
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR",
                   "availability": "https://schema.org/InStock"},
    }
    if latest:
        data["softwareVersion"] = latest["version"]
        date = (latest.get("published_at") or "")[:10]
        if date:
            data["datePublished"] = date
        win = (latest.get("assets") or {}).get("windows-setup")
        if win:
            data["downloadUrl"] = f"{base}{dl_path(latest['version'], win['filename'])}"
            data["fileSize"] = str(win["size"])
    return data


def android_ld(settings, lang: str, mobile: dict | None) -> dict:
    """L'appli Android : un `SoftwareApplication` à part de celui du PC (autre système, autre numérotation).
    Ni note ni avis : il n'y en a pas."""
    base = settings.public_url
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": t(lang, "site.android.app_name"),
        "description": t(lang, "site.meta.android.description"),
        "url": f"{base}{url_for(lang, 'android')}",
        "image": f"{base}/static/logo.png",
        "applicationCategory": "GameApplication",
        "applicationSubCategory": t(lang, "site.meta.app_subcategory"),
        "operatingSystem": "Android",
        "softwareRequirements": "Android 8.0+",
        "inLanguage": lang,
        "isAccessibleForFree": True,
        "author": {"@type": "Organization", "@id": organization_id(settings), "name": EDITEUR_MARQUE,
                   "url": f"{base}/"},
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
    }
    if mobile:
        data["offers"]["availability"] = "https://schema.org/InStock"
        data["softwareVersion"] = mobile["version"]
        date = (mobile.get("published_at") or "")[:10]
        if date:
            data["datePublished"] = date
        data["downloadUrl"] = f"{base}{mobile_releases.dl_path(mobile['version'], mobile['filename'])}"
        data["fileSize"] = str(mobile["size"])
    return data


def faq_ld(items: list[dict]) -> dict:
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": strip_tags(q["q"]),
         "acceptedAnswer": {"@type": "Answer", "text": strip_tags(q["a"])}} for q in items]}


def strip_tags(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html).strip()


def lang_switcher(lang: str, page_id: str, paths: dict[str, str] | None = None) -> str:
    """Sélecteur de langue : liens directs vers la même page, sans JavaScript (<details>)."""
    paths = paths or {code: url_for(code, page_id) for code in LANGS}
    items = "".join(
        f'<li><a href="{esc(paths[code])}" hreflang="{code}" lang="{code}"'
        + (' aria-current="true"' if code == lang else "")
        + f'>{esc(LANG_INFO[code]["name"])}</a></li>'
        for code in LANGS)
    label = f'{t(lang, "site.nav.language")}: {LANG_INFO[lang]["name"]}'
    return (f'<details class="langs"><summary aria-label="{esc(label)}">'
            f'<span class="langs__ico" aria-hidden="true"></span><span class="langs__code">{esc(lang.upper())}</span>'
            f'</summary><ul class="langs__menu">{items}</ul></details>')


def icon_links() -> str:
    """Balises d'icônes (`ICONS`) : chaque `sizes` correspond aux dimensions réelles du fichier."""
    return "".join(f'<link rel="{rel}" type="{mime}" sizes="{sizes}" href="{href}">\n'
                   for href, rel, mime, sizes in ICONS)


def head(settings, lang: str, page_id: str, title: str, description: str, extra: str = "",
         robots: str = ROBOTS_INDEX, canonical: bool = True, paths: dict[str, str] | None = None,
         og: tuple | None = None, body_class: str | None = None) -> str:
    base = settings.public_url
    paths = paths or {code: url_for(code, page_id) for code in LANGS}
    url = f"{base}{paths[lang]}"
    image, img_w, img_h, img_alt = og or og_image(settings, page_id, lang)
    alternates = "".join(
        f'<link rel="alternate" hreflang="{code}" href="{esc(base + paths[code])}">\n' for code in LANGS)
    alternates += f'<link rel="alternate" hreflang="x-default" href="{esc(base + paths[DEFAULT_LANG])}">\n'
    og_alt = "".join(f'<meta property="og:locale:alternate" content="{LANG_INFO[c]["og"]}">\n'
                     for c in LANGS if c != lang)
    verif = ""
    if settings.SITE_VERIFICATION_GOOGLE:
        verif += f'<meta name="google-site-verification" content="{esc(settings.SITE_VERIFICATION_GOOGLE)}">\n'
    if settings.SITE_VERIFICATION_BING:
        verif += f'<meta name="msvalidate.01" content="{esc(settings.SITE_VERIFICATION_BING)}">\n'
    plausible = ""
    if settings.PLAUSIBLE_SCRIPT_URL:
        script_url = settings.PLAUSIBLE_SCRIPT_URL
        if "/js/pa-" in urlsplit(script_url).path:
            # Script Plausible nouvelle génération (pa-<id>.js) : le site est identifié par le fichier lui-même,
            # mais rien n'est mesuré sans l'appel plausible.init() (extrait fourni par Plausible, avec nonce CSP).
            plausible = (f'<script async nonce="{NONCE}" src="{esc(script_url)}"></script>\n'
                         f'<script nonce="{NONCE}">window.plausible=window.plausible||function(){{'
                         f'(plausible.q=plausible.q||[]).push(arguments)}},plausible.init=plausible.init||'
                         f'function(i){{plausible.o=i||{{}}}};plausible.init()</script>\n')
        else:
            domain = urlsplit(base).hostname or SITE_HOST
            plausible = (f'<script defer nonce="{NONCE}" data-domain="{esc(domain)}" '
                         f'src="{esc(script_url)}"></script>\n')
    canon = f'<link rel="canonical" href="{esc(url)}">\n{alternates}' if canonical else ""
    nav_items = "".join(
        f'<a href="{url_for(lang, pid)}"' + (f' class="nav--{pid}"' if pid in ("music", "draw", "cook") else "")
        + (' aria-current="page"' if pid == page_id else "")
        + f'>{esc(t(lang, f"site.nav.{pid}"))}</a>'
        for pid in ("music", "draw", "cook", "creations", "songs", "gallery", "help"))
    body_class = body_class or f"page-{page_id} theme-{theme_of(page_id)}"
    beta = ""
    if i18n.is_beta(lang):
        beta = (f'<div class="beta" role="note"><div class="wrap"><p>{t(lang, "site.common.beta_banner")} '
                f'<a href="{esc(paths["fr"])}" hreflang="fr" lang="fr">{esc(t(lang, "site.common.beta_link"))}</a>'
                f'</p></div></div>\n')
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{canon}<meta name="robots" content="{esc(robots)}">
<meta name="theme-color" content="#fff9ef" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1d1715" media="(prefers-color-scheme: dark)">
<meta name="color-scheme" content="light dark">
{verif}<meta property="og:type" content="website">
<meta property="og:site_name" content="DodoTopia">
<meta property="og:locale" content="{LANG_INFO[lang]["og"]}">
{og_alt}<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:image" content="{esc(image)}">
<meta property="og:image:width" content="{img_w}">
<meta property="og:image:height" content="{img_h}">
<meta property="og:image:alt" content="{esc(img_alt)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(description)}">
<meta name="twitter:image" content="{esc(image)}">
{icon_links()}<link rel="preload" href="/static/fonts/fredoka-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{css_href()}">
{plausible}{extra}</head>
<body class="{esc(body_class)}">
<a class="skip" href="#contenu">{esc(t(lang, "site.common.skip"))}</a>
{beta}<header class="site-header"><div class="wrap wrap--wide">
  <a class="brand" href="{url_for(lang, 'home')}" aria-label="DodoTopia — {esc(t(lang, 'site.nav.home'))}">
    {dodo_picture(lang, 48, "brand__logo", lazy=False, alt_key="site.brand.logo_alt")}
    <span class="brand__name">DodoTopia</span>
  </a>
  <nav class="header-nav" aria-label="{esc(t(lang, 'site.nav.main_label'))}">
    {nav_items}
    <a class="header-nav__cta" href="{url_for(lang, 'download')}">{esc(t(lang, 'site.nav.download'))}</a>
  </nav>
  {lang_switcher(lang, page_id, paths)}
</div></header>
<main id="contenu">
"""


def foot(settings, lang: str, page_id: str, version_line: str, paths: dict[str, str] | None = None) -> str:
    def link(pid: str) -> str:
        return f'<li><a href="{url_for(lang, pid)}">{esc(t(lang, f"site.nav.{pid}"))}</a></li>'
    paths = paths or {code: url_for(code, page_id) for code in LANGS}
    product = "".join(link(p) for p in ("music", "draw", "cook", "creations", "together", "songs", "gallery", "download",
                                        "android", "instruments", "news"))
    support = "".join(link(p) for p in ("help", "community"))
    support += f'<li><a href="mailto:{EDITEUR_COURRIEL}">{esc(t(lang, "site.footer.contact"))}</a></li>'
    legal = "".join(link(p) for p in ("legal", "privacy", "terms"))
    langs = "".join(f'<a href="{esc(paths[code])}" hreflang="{code}" lang="{code}"'
                    + (' aria-current="true"' if code == lang else "")
                    + f'>{esc(LANG_INFO[code]["name"])}</a>' for code in LANGS)
    return f"""</main>
<footer class="site-footer"><span class="site-footer__hills" aria-hidden="true"></span><div class="wrap">
  <div class="footer-top">
    <div class="footer-brand">
      {dodo_picture(lang, 72)}
      <p><strong>DodoTopia</strong><br>{t(lang, 'site.footer.tagline')}</p>
    </div>
    <p class="footer-trust">{esc(t(lang, 'site.footer.trust'))}</p>
  </div>
  <div class="footer-grid">
    <nav aria-label="{esc(t(lang, 'site.footer.product'))}"><h2 class="footer-h">{esc(t(lang, 'site.footer.product'))}</h2>
      <ul class="footer-nav footer-nav--cols">{product}</ul></nav>
    <nav aria-label="{esc(t(lang, 'site.footer.support'))}"><h2 class="footer-h">{esc(t(lang, 'site.footer.support'))}</h2>
      <ul class="footer-nav">{support}</ul></nav>
    <nav aria-label="{esc(t(lang, 'site.footer.legal'))}"><h2 class="footer-h">{esc(t(lang, 'site.footer.legal'))}</h2>
      <ul class="footer-nav">{legal}</ul></nav>
  </div>
  <p class="footer-langs" lang="">{langs}</p>
  <p class="disclaimer">{t(lang, 'site.footer.disclaimer')}</p>
  <p class="footer-version">{version_line}</p>
</div></footer>
</body>
</html>
"""


def page(settings, lang: str, page_id: str, body: str, ctx: Ctx, title: str | None = None,
         description: str | None = None, canonical: bool = True) -> str:
    """Page complète. `title`/`description` : texte brut (échappé ici). Les fiches dynamiques les passent par
    `ctx.title`, `ctx.description`, `ctx.paths`, `ctx.og`, `ctx.crumb`, `ctx.canonical`."""
    title = title or ctx.title or t(lang, f"site.meta.{page_id}.title")
    description = description or ctx.description or t(lang, f"site.meta.{page_id}.description")
    canonical = canonical and ctx.canonical
    extra = "".join(ctx.head)
    if page_id != "home" and canonical:
        extra += ld_script(breadcrumb_ld(settings, lang, page_id, ctx.crumb))
    extra += ld_script(site_ld(settings))
    version_line = f"{esc(t(lang, 'site.footer.server'))} {esc(SERVER_VERSION)}"
    return (head(settings, lang, page_id, title, description, extra, ctx.robots, canonical, ctx.paths, ctx.og,
                 ctx.body_class)
            + body + foot(settings, lang, page_id, version_line, ctx.paths))


# --- Captures de l'application ------------------------------------------------------------------------

SHOT_WIDTHS = (730, 1460)              # déclinaisons WebP produites par .tools/make_shots.py
SHOT_SIZES = "(max-width: 900px) 94vw, 760px"
DODO_SOURCES = ((160, "dodo-96.webp"), (10_000, "dodo-512.webp"))


def app_shot(name: str, alt: str, cls: str = "shot", eager: bool = False, sizes: str = SHOT_SIZES) -> str:
    """Capture de l'interface : WebP en deux largeurs dans `<source>`, le PNG d'origine en `src` (repli),
    dimensions réelles réservées. `eager` pour la seule image du héros."""
    file = f"app-{name}.png"
    w, h = png_size(STATIC_DIR / file) or (1460, 812)
    load = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    srcset = ", ".join(f"{static_url(f'app-{name}-{n}.webp')} {n}w" for n in SHOT_WIDTHS
                       if (STATIC_DIR / f"app-{name}-{n}.webp").is_file())
    source = f'<source type="image/webp" srcset="{srcset}" sizes="{esc(sizes)}">' if srcset else ""
    return (f'<picture>{source}<img class="{cls}" src="{static_url(file)}" width="{w}" height="{h}"'
            f' {load} decoding="async" alt="{esc(alt)}"></picture>')


def window_frame(inner: str, tilt: str = "", caption: str = "") -> str:
    """Cadre « fenêtre » autour d'une capture : barre de titre à trois pastilles (CSS), légère rotation
    (`tilt` : "l" ou "r", nulle sur petit écran et sans animation), légende facultative hors du cadre."""
    cls = "win" + (f" win--tilt-{tilt}" if tilt in ("l", "r") else "")
    cap = f"<figcaption>{caption}</figcaption>" if caption else ""
    return (f'<figure class="{cls}"><div class="win__frame"><span class="win__bar" aria-hidden="true"></span>'
            f'{inner}</div>{cap}</figure>')


def app_figure(lang: str, name: str, alt: str, caption: str, cls: str = "shot", eager: bool = False,
               tilt: str = "", sizes: str = SHOT_SIZES) -> str:
    """Capture dans son cadre fenêtre + légende + lien d'agrandissement : elle reste consultable en entier."""
    link = (f'{caption} · <a href="{static_url(f"app-{name}.png")}" target="_blank" rel="noopener">'
            f'{esc(t(lang, "site.common.open_shot"))}</a>')
    return window_frame(app_shot(name, alt, cls, eager, sizes), tilt, link)


def dodo_picture(lang: str, px: int, cls: str = "", lazy: bool = True, alt_key: str = "site.brand.dodo_alt") -> str:
    """Le dodo du logo : WebP (96 ou 512 px selon la taille affichée), `logo.png` en repli."""
    webp = next(name for limit, name in DODO_SOURCES if px <= limit)
    source = f'<source type="image/webp" srcset="{static_url(webp)}">' if (STATIC_DIR / webp).is_file() else ""
    cls_attr = f' class="{cls}"' if cls else ""
    load = ' loading="lazy"' if lazy else ""
    return (f'<picture>{source}<img{cls_attr} src="{static_url("logo.png")}" width="{px}" height="{px}"{load}'
            f' decoding="async" alt="{esc(t(lang, alt_key))}"></picture>')


def dodo(lang: str, px: int, cls: str = "") -> str:
    """Dodo flottant (animation `float` en CSS). Pas de bulle ni de halo derrière : la tuile du logo a déjà son
    contour, elle se suffit (demande du propriétaire, 2026-09-21)."""
    return f'<span class="dodo {cls}">{dodo_picture(lang, px)}</span>'


def decor(*names: str) -> str:
    """Motifs décoratifs en CSS (masques SVG colorés par le thème) : jamais d'<img alt="">."""
    return "".join(f'<span class="{name}" aria-hidden="true"></span>' for name in names)


SKY = ("cloud cloud--a", "cloud cloud--b", "motif motif--a", "motif motif--b", "motif motif--c")


def page_header(lang: str, eyebrow: str, h1: str, lead: str, actions: str = "", art: str = "",
                back: str = "", cls: str = "") -> str:
    """En-tête coloré des pages intérieures (`--t-*` du thème de la page) : nuages, motifs de la rubrique, vague
    basse. `eyebrow`, `h1`, `lead`, `actions`, `art`, `back` : HTML déjà sûr. Sans `h1` (pages légales, dont le
    titre est dans le document) : simple bandeau décoratif."""
    parts = [back,
             f'<p class="eyebrow">{eyebrow}</p>' if eyebrow else "",
             f"<h1>{h1}</h1>" if h1 else "",
             f'<p class="lead">{lead}</p>' if lead else "",
             actions]
    classes = "pagehead" + (" pagehead--art" if art else "") + (f" {cls}" if cls else "")
    return f"""<section class="{classes}"><span class="sky" aria-hidden="true">{decor(*SKY)}</span>
<div class="wrap pagehead__grid">
  <div class="pagehead__txt">{"".join(x for x in parts if x)}</div>
  {art}
</div><span class="wave" aria-hidden="true"></span></section>
"""


# --- Routes ---------------------------------------------------------------------------------------------

def _html_response(request: Request, html: str, etag: str, cache: str = HTML_CACHE,
                   status: int = 200) -> Response:
    nonce = getattr(request.state, "csp_nonce", "") or secrets.token_urlsafe(16)
    headers = {"Cache-Control": cache, "ETag": etag}
    if status == 200 and etag in [x.strip() for x in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    return HTMLResponse(html.replace(NONCE, nonce), status_code=status, headers=headers)


@router.get("/", include_in_schema=False)
def root(request: Request):
    """Redirection selon la langue du navigateur (par défaut l'anglais). Jamais mise en cache."""
    lang = i18n.negotiate(request.headers.get("accept-language"))
    return RedirectResponse(url_for(lang, "home"), status_code=302,
                            headers={"Vary": "Accept-Language", "Cache-Control": "no-store"})


@router.get("/telecharger/go/{platform}", include_in_schema=False)
def download_go(platform: str, request: Request):
    """Lien de téléchargement de la page : compte le téléchargement puis renvoie vers le fichier (302)."""
    if platform.lower() in GO_ANDROID:
        return _download_go_android(request)
    asset_id = GO_PLATFORMS.get(platform.lower())
    settings = request.app.state.settings
    latest = latest_release(settings) if asset_id else None
    asset = (latest or {}).get("assets", {}).get(asset_id) if latest else None
    if not asset:
        return _not_found(request)
    conn = db.connect(settings)
    try:
        releases.count_download(conn, latest["version"], asset["filename"], request.app, "site")
    finally:
        conn.close()
    request.app.state.stats_cache = None
    return RedirectResponse(dl_path(latest["version"], asset["filename"]) + "?via=site", status_code=302,
                            headers={"Cache-Control": "no-store"})


def _download_go_android(request: Request) -> Response:
    """`/telecharger/go/android` : le dernier APK publié, compté dans son propre canal."""
    settings = request.app.state.settings
    mobile = mobile_releases.latest_release(settings)
    if not mobile:
        return _not_found(request)
    conn = db.connect(settings)
    try:
        mobile_releases.count_download(conn, mobile["version"], request.app, "site")
    finally:
        conn.close()
    return RedirectResponse(mobile_releases.dl_path(mobile["version"], mobile["filename"]) + "?via=site",
                            status_code=302, headers={"Cache-Control": "no-store"})


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots(request: Request):
    base = request.app.state.settings.public_url
    txt = ("User-agent: *\n"
           "Allow: /\n"
           "Allow: /api/drawings/*.png$\n"
           "Disallow: /api/\n"
           "Disallow: /auth/\n"
           "Disallow: /dl/\n"
           "Disallow: /telecharger/go/\n"
           f"\nSitemap: {base}/sitemap.xml\n")
    return PlainTextResponse(txt, headers={"Cache-Control": STATIC_SHORT})


@router.get("/{name}.txt", include_in_schema=False)
def indexnow_key_file(name: str, request: Request):
    """`/<INDEXNOW_KEY>.txt` : preuve de propriété demandée par IndexNow (contenu = la clé). Rien sans clé."""
    key = request.app.state.settings.indexnow_key
    if not key or name != key:
        raise StarletteHTTPException(status_code=404)
    return PlainTextResponse(key, headers={"Cache-Control": STATIC_SHORT})


def _content_lastmod(app) -> str:
    """Date de dernière modification des pages liées à la base : celle de la dernière publication."""
    try:
        latest = latest_release(app.state.settings)
    except Exception:  # noqa
        latest = None
    date = ((latest or {}).get("published_at") or "")[:10]
    return max(date, LAST_UPDATE_ISO) if date else LAST_UPDATE_ISO


def _android_lastmod(app) -> str:
    """Date de dernière modification de la page Android : celle du dernier APK publié."""
    try:
        mobile = mobile_releases.latest_release(app.state.settings)
    except Exception:  # noqa
        mobile = None
    return max(((mobile or {}).get("published_at") or "")[:10], ANDROID_PAGE_ISO)


XML_MEDIA_TYPE = "application/xml; charset=utf-8"
SITEMAP_MAX_ITEMS = 5000            # × 8 langues : sous la limite de 50 000 URL par fichier
SITEMAP_DB_CACHE = "public, max-age=3600"


def _xml_response(xml: str, cache: str) -> Response:
    return Response(xml, media_type=XML_MEDIA_TYPE, headers={"Cache-Control": cache})


def _sitemap_children(settings) -> list[tuple[str, str]]:
    """(nom, lastmod) des sitemaps de contenu qui ont au moins une URL : un sitemap vide listé dans l'index est
    signalé en erreur par Google et Bing. `lastmod` : date du morceau / du dessin modifié le plus récemment."""
    children = []
    try:
        conn = db.connect(settings)
        try:
            song = conn.execute("SELECT COUNT(*) AS n, MAX(COALESCE(updated_at, created_at)) AS last FROM songs "
                                "WHERE status='approved' AND note_count >= ?",
                                (settings.SONG_INDEX_MIN_NOTES,)).fetchone()
            drawing = conn.execute("SELECT COUNT(*) AS n, MAX(COALESCE(reviewed_at, created_at)) AS last "
                                   "FROM drawings WHERE status='approved'").fetchone()
        finally:
            conn.close()
    except Exception:  # noqa - base indisponible : l'index garde au moins le sitemap des pages
        log.exception("index du sitemap")
        return children
    for name, row in (("sitemap-songs.xml", song), ("sitemap-gallery.xml", drawing)):
        if int(row["n"] or 0) > 0:
            children.append((name, str(row["last"] or "")[:10] or LAST_UPDATE_ISO))
    return children


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap_index(request: Request):
    settings = request.app.state.settings
    base = settings.public_url
    entries = [("sitemap-pages.xml", _content_lastmod(request.app)), *_sitemap_children(settings)]
    items = "".join(f"  <sitemap><loc>{esc(base)}/{name}</loc><lastmod>{esc(lastmod)}</lastmod></sitemap>\n"
                    for name, lastmod in entries)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{items}</sitemapindex>\n")
    return _xml_response(xml, SITEMAP_DB_CACHE)


def _urlset(base: str, entries: list[tuple[dict[str, str], str, str, str]]) -> Response:
    """entries : ({lang: chemin}, lastmod, changefreq, priority) -> une <url> par langue avec ses alternates.
    Sans entrée : un `urlset` vide, valide (l'index ne le liste pas, mais l'adresse répond toujours 200)."""
    urls = []
    for paths, lastmod, freq, prio in entries:
        links = "".join(f'<xhtml:link rel="alternate" hreflang="{code}" href="{esc(base + paths[code])}"/>'
                        for code in LANGS)
        links += f'<xhtml:link rel="alternate" hreflang="x-default" href="{esc(base + paths[DEFAULT_LANG])}"/>'
        mod = f"<lastmod>{esc(lastmod)}</lastmod>" if lastmod else ""
        for lang in LANGS:
            urls.append(f"  <url><loc>{esc(base + paths[lang])}</loc>{mod}"
                        f"<changefreq>{freq}</changefreq><priority>{prio}</priority>{links}</url>\n")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
           f"{''.join(urls)}</urlset>\n")
    return _xml_response(xml, SITEMAP_DB_CACHE)


@router.get("/sitemap-songs.xml", include_in_schema=False)
def sitemap_songs(request: Request):
    """Fiches des morceaux approuvés et indexables (au moins SONG_INDEX_MIN_NOTES notes)."""
    from .site_pages.songs import song_url
    settings = request.app.state.settings
    conn = db.connect(settings)
    try:
        rows = conn.execute("SELECT id, title, created_at, updated_at FROM songs WHERE status='approved' "
                            "AND note_count >= ? ORDER BY id DESC LIMIT ?",
                            (settings.SONG_INDEX_MIN_NOTES, SITEMAP_MAX_ITEMS)).fetchall()
    finally:
        conn.close()
    entries = [({lang: song_url(lang, r["id"], r["title"]) for lang in LANGS},
                str(r["updated_at"] or r["created_at"] or "")[:10], "weekly", "0.6") for r in rows]
    return _urlset(settings.public_url, entries)


@router.get("/sitemap-gallery.xml", include_in_schema=False)
def sitemap_gallery(request: Request):
    from .site_pages.gallery import drawing_url
    settings = request.app.state.settings
    conn = db.connect(settings)
    try:
        rows = conn.execute("SELECT id, created_at, reviewed_at FROM drawings WHERE status='approved' "
                            "ORDER BY id DESC LIMIT ?", (SITEMAP_MAX_ITEMS,)).fetchall()
    finally:
        conn.close()
    entries = [({lang: drawing_url(lang, r["id"]) for lang in LANGS},
                str(r["reviewed_at"] or r["created_at"] or "")[:10], "monthly", "0.5") for r in rows]
    return _urlset(settings.public_url, entries)


@router.get("/sitemap-pages.xml", include_in_schema=False)
def sitemap_pages(request: Request):
    base = request.app.state.settings.public_url
    db_lastmod = _content_lastmod(request.app)
    urls = []
    for page_id in PAGE_IDS:
        freq, prio = SITEMAP_HINTS.get(page_id, SITEMAP_DEFAULT)
        lastmod = db_lastmod if page_id in DB_PAGES else LAST_UPDATE_ISO
        if page_id == "android":
            lastmod = _android_lastmod(request.app)
        links = "".join(f'<xhtml:link rel="alternate" hreflang="{code}" href="{esc(base + url_for(code, page_id))}"/>'
                        for code in LANGS)
        links += f'<xhtml:link rel="alternate" hreflang="x-default" href="{esc(base + url_for(DEFAULT_LANG, page_id))}"/>'
        for lang in LANGS:
            urls.append(f"  <url><loc>{esc(base + url_for(lang, page_id))}</loc><lastmod>{lastmod}</lastmod>"
                        f"<changefreq>{freq}</changefreq><priority>{prio}</priority>{links}</url>\n")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
           f"{''.join(urls)}</urlset>\n")
    return _xml_response(xml, STATIC_SHORT)


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon",
                        headers={"Cache-Control": FAVICON_CACHE})


def lang_of_request(request: Request) -> str:
    """Langue d'une page d'erreur : celle du préfixe d'URL s'il est connu, sinon celle du navigateur."""
    parts = request.url.path.split("/")
    if len(parts) > 1 and parts[1] in LANGS:
        return parts[1]
    return i18n.negotiate(request.headers.get("accept-language"))


def not_found_response(request: Request) -> Response:
    """Page 404 du site dans la langue de l'URL ou du navigateur (aussi utilisée par main.py)."""
    lang = lang_of_request(request)
    html = render_not_found(request.app, lang)
    return _html_response(request, html, 'W/"404"', cache="no-store", status=404)


_not_found = not_found_response


@router.get("/{lang}/{slug:path}", include_in_schema=False)
def localized_page(lang: str, slug: str, request: Request):
    if lang not in LANGS:
        # Préfixe inconnu (`/api/…` compris) : le gestionnaire d'erreurs de main.py choisit JSON ou page 404.
        raise StarletteHTTPException(status_code=404)
    if slug.endswith("/") and slug != "":
        return RedirectResponse(f"/{lang}/{slug.rstrip('/')}", status_code=301,
                                headers={"Cache-Control": REDIRECT_CACHE})
    if "/" in slug:
        return _dynamic_page(request, lang, slug)
    page_id = page_for(lang, slug)
    if page_id in ("songs", "gallery") and request.url.query:
        from . import site_pages
        query = site_pages.MODULES[page_id].normalize_query(request.query_params)
        if query:
            html, etag = render_page(request.app, page_id, lang, query)
            ttl = int(request.app.state.settings.SITE_PAGE_TTL_S)
            return _html_response(request, html, etag, cache=HTML_CACHE)
    if page_id is None:
        # Slug d'une autre langue (lien recopié) : on renvoie vers la bonne adresse dans cette langue.
        for other in LANGS:
            pid = page_for(other, slug)
            if pid and slug:
                return RedirectResponse(url_for(lang, pid), status_code=301,
                                        headers={"Cache-Control": REDIRECT_CACHE})
        return _not_found(request)
    html, etag = render_page(request.app, page_id, lang)
    ttl = request.app.state.settings.SITE_PAGE_TTL_S if page_id in DB_PAGES else 3600
    return _html_response(request, html, etag, cache=HTML_CACHE)


_SONG_REST = re.compile(r"^(\d{1,10})(?:-[A-Za-z0-9-]*)?$")
_DRAWING_REST = re.compile(r"^(\d{1,10})(?:-[A-Za-z0-9-]*)?$")


def _redirect(url: str) -> Response:
    return RedirectResponse(url, status_code=301, headers={"Cache-Control": REDIRECT_CACHE})


def _dynamic_page(request: Request, lang: str, slug: str) -> Response:
    """`/{lang}/<morceaux>/{id}-{slug}`, `/{lang}/<galerie>/{id}`, `/{lang}/<salon>/{CODE}` (slugs de n'importe
    quelle langue acceptés : redirection 301 vers l'adresse canonique de la langue demandée)."""
    from .site_pages import gallery as gallery_page, room as room_page, songs as songs_page
    section, _, rest = slug.partition("/")
    app = request.app
    settings = app.state.settings
    if not rest or "/" in rest:
        return _not_found(request)
    ttl = int(settings.SITE_PAGE_TTL_S)
    if section in ROUTES["songs"].values():
        m = _SONG_REST.match(rest)
        row = songs_page.fetch_public_song(settings, int(m.group(1))) if m else None
        if row is None:
            return _not_found(request)
        canonical = songs_page.song_url(lang, row["id"], row["title"])
        if request.url.path != canonical:
            return _redirect(canonical)
        html, etag = render_dynamic(app, lang, "songs", ("song", int(row["id"]), lang, row["updated_at"]),
                                    lambda s, lg, ctx: songs_page.render_detail(s, lg, ctx, row))
        return _html_response(request, html, etag, cache=HTML_CACHE)
    if section in ROUTES["gallery"].values():
        m = _DRAWING_REST.match(rest)
        row = gallery_page.fetch_public_drawing(settings, int(m.group(1))) if m else None
        if row is None:
            return _not_found(request)
        canonical = gallery_page.drawing_url(lang, row["id"])
        if request.url.path != canonical:
            return _redirect(canonical)
        html, etag = render_dynamic(app, lang, "gallery", ("drawing", int(row["id"]), lang),
                                    lambda s, lg, ctx: gallery_page.render_detail(s, lg, ctx, row))
        return _html_response(request, html, etag, cache=HTML_CACHE)
    if section in ROOM_SLUGS.values():
        code = room_page.normalize_code(rest)
        if code is None:
            return _not_found(request)
        canonical = f"/{lang}/{ROOM_SLUGS[lang]}/{code}"
        if request.url.path != canonical:
            return _redirect(canonical)
        html, etag = render_dynamic(app, lang, "home", None,
                                    lambda s, lg, ctx: room_page.render_room(s, lg, ctx, code))
        return _html_response(request, html, etag, cache="no-store")
    return _not_found(request)


@router.get("/{segment}", include_in_schema=False)
def legacy_or_lang(segment: str, request: Request):
    """`/fr` -> `/fr/` ; anciennes URL françaises (`/instruments`, `/conditions`…) -> `/fr/<slug>` (301)."""
    if segment in LANGS:
        return RedirectResponse(f"/{segment}/", status_code=301, headers={"Cache-Control": REDIRECT_CACHE})
    if segment in SHORT_SLUGS:
        lang = i18n.negotiate(request.headers.get("accept-language"))
        return RedirectResponse(url_for(lang, SHORT_SLUGS[segment]), status_code=302,
                                headers={"Vary": "Accept-Language", "Cache-Control": "no-store"})
    page_id = LEGACY_SLUGS.get(segment)
    if page_id:
        return RedirectResponse(url_for("fr", page_id), status_code=301, headers={"Cache-Control": REDIRECT_CACHE})
    raise StarletteHTTPException(status_code=404)


# --- Middleware d'en-têtes -------------------------------------------------------------------------------

class SecurityHeadersMiddleware:
    """En-têtes de durcissement sur toute réponse HTTP (ASGI pur : ne touche pas au corps).

    HSTS (un an, sous-domaines compris), Referrer-Policy, Permissions-Policy, X-Frame-Options DENY, nosniff, et
    une CSP avec un nonce par requête : le nonce est déposé dans `scope["state"]["csp_nonce"]`, les pages du
    site remplacent le marqueur `__NONCE__` de leur HTML en cache par cette valeur. Les pages `/auth/` (gabarit
    minimal avec style en ligne, formulaire vers Discord) reçoivent une CSP sans nonce, styles en ligne
    autorisés. Cache long sur /static : immuable pour les URL versionnées (`?v=`, `site.<hash>.css`, polices),
    un jour sinon.
    """

    HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        (b"x-frame-options", b"DENY"),
    )
    AUTH_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'; "
                "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")

    def __init__(self, app, settings=None):
        self.app = app
        extra = ""
        url = getattr(settings, "PLAUSIBLE_SCRIPT_URL", "") if settings else ""
        if url:
            parts = urlsplit(url)
            if parts.scheme and parts.netloc:
                extra = f" {parts.scheme}://{parts.netloc}"
        self.csp_template = ("default-src 'self'; img-src 'self' data:; style-src 'self'; "
                             "script-src 'self' 'nonce-{nonce}'" + extra + "; connect-src 'self'" + extra + "; "
                             "font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
                             "object-src 'none'")

    def csp(self, nonce: str) -> str:
        return self.csp_template.format(nonce=nonce)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        is_static = path.startswith("/static/")
        is_auth = path.startswith("/auth/")
        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        query = scope.get("query_string", b"")
        versioned = (b"v=" in query or path.startswith("/static/fonts/")
                     or (path.startswith("/static/site.") and path.endswith(".css") and path != "/static/site.css"))

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                names = {k.lower() for k, _ in headers}
                for name, value in self.HEADERS:
                    if name not in names:
                        headers.append((name, value))
                # 304 : pas de nouvelle CSP. Le navigateur réutilise le corps en cache, dont les scripts portent
                # le nonce de la réponse d'origine ; une CSP au nonce neuf les bloquerait tous.
                if b"content-security-policy" not in names and message.get("status") != 304:
                    csp = self.AUTH_CSP if is_auth else self.csp(nonce)
                    headers.append((b"content-security-policy", csp.encode()))
                if is_static and b"cache-control" not in names:
                    headers.append((b"cache-control", (STATIC_IMMUTABLE if versioned else STATIC_SHORT).encode()))
            await send(message)

        return await self.app(scope, receive, send_wrapper)
