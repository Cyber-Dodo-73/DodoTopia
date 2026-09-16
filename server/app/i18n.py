"""Catalogues de traduction du site public : `server/app/locales/<lang>.json`, clés plates `site.*`.

- `fr` est la langue source (tout y est), `en` est rédigé avec soin ; les autres langues sont des catalogues
  partiels, générés depuis l'anglais (qualité « bêta ») : une clé absente retombe sur `en`, puis sur `fr`.
- Les textes des catalogues sont des fichiers du dépôt, donc de confiance : ils peuvent contenir un peu de
  balisage HTML (`<strong>`, `<code>`, `<kbd>`, `<a>`). Les paramètres interpolés (`{name}`) sont eux toujours
  échappés : c'est par là qu'entrent les données dynamiques.
- `t(lang, key, **params)` ; une clé introuvable partout renvoie `[key]`, marqueur que le lint SEO détecte.
"""
from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"

LANGS = ("fr", "en", "es", "de", "pt-BR", "zh-CN", "ja", "th")
SOURCE_LANG = "fr"          # langue de référence : toutes les clés y existent
DEFAULT_LANG = "en"         # langue servie quand rien ne correspond
FALLBACK = ("en", "fr")

# Locale Open Graph, nom natif (sélecteur de langue), code BCP 47 du <html lang>.
LANG_INFO = {
    "fr": {"og": "fr_FR", "name": "Français"},
    "en": {"og": "en_US", "name": "English"},
    "es": {"og": "es_ES", "name": "Español"},
    "de": {"og": "de_DE", "name": "Deutsch"},
    "pt-BR": {"og": "pt_BR", "name": "Português (Brasil)"},
    "zh-CN": {"og": "zh_CN", "name": "简体中文"},
    "ja": {"og": "ja_JP", "name": "日本語"},
    "th": {"og": "th_TH", "name": "ไทย"},
}

_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Liens internes écrits en français dans les catalogues (`href="/fr/telecharger#x"`) : réécrits vers la même
# page dans la langue demandée par le résolveur que `site.py` installe (i18n ne connaît pas les routes).
_FR_LINK = re.compile(r'href="/fr/([a-z0-9-]*)(#[A-Za-z0-9_-]+)?"')
_link_resolver = None
_CATALOGUES: dict[str, dict] = {}


def set_link_resolver(fn) -> None:
    """`fn(lang, fr_slug) -> chemin | None` : traduit un lien interne français vers la langue affichée."""
    global _link_resolver
    _link_resolver = fn


def _localize_links(lang: str, value: str) -> str:
    if lang == SOURCE_LANG or _link_resolver is None or 'href="/fr/' not in value:
        return value

    def repl(m):
        path = _link_resolver(lang, m.group(1))
        return f'href="{path}{m.group(2) or ""}"' if path else m.group(0)
    return _FR_LINK.sub(repl, value)


def catalogue(lang: str) -> dict:
    """Catalogue d'une langue (chargé une fois ; vide si le fichier manque)."""
    cat = _CATALOGUES.get(lang)
    if cat is None:
        path = LOCALES_DIR / f"{lang}.json"
        try:
            cat = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cat = {}
        _CATALOGUES[lang] = cat
    return cat


def reload() -> None:
    _CATALOGUES.clear()


def lookup(lang: str, key: str) -> str | None:
    """Valeur brute avec repli lang → en → fr ; None si la clé n'existe nulle part."""
    for candidate in (lang, *FALLBACK):
        value = catalogue(candidate).get(key)
        if isinstance(value, str):
            return value
    return None


def has(lang: str, key: str, strict: bool = False) -> bool:
    """La clé existe (dans cette langue seulement si `strict`)."""
    if strict:
        return isinstance(catalogue(lang).get(key), str)
    return lookup(lang, key) is not None


def t(lang: str, key: str, **params) -> str:
    """Texte traduit, paramètres `{name}` échappés. Clé inconnue : `[key]` (visible, détecté par le lint)."""
    value = lookup(lang, key)
    if value is None:
        return f"[{key}]"
    value = _localize_links(lang, value)
    if not params:
        return value
    return _PARAM.sub(lambda m: escape(str(params[m.group(1)]), quote=True) if m.group(1) in params
                      else m.group(0), value)


def t_items(lang: str, prefix: str, fields: tuple[str, ...] = ("q", "a")) -> list[dict]:
    """Groupes numérotés `prefix.1.q`, `prefix.1.a`, `prefix.2.q`… ; le nombre vient de la langue source."""
    items = []
    n = 1
    while has(SOURCE_LANG, f"{prefix}.{n}.{fields[0]}", strict=True):
        items.append({f: t(lang, f"{prefix}.{n}.{f}") for f in fields})
        n += 1
    return items


def is_beta(lang: str) -> bool:
    """Langue à bandeau « traduction automatique » : tout sauf le français (source) et l'anglais (relu)."""
    meta = catalogue(lang).get("_meta") or {}
    return bool(meta.get("beta", lang not in ("fr", "en")))


def completeness(lang: str) -> float:
    """Part des clés de la langue source présentes dans ce catalogue (0..1)."""
    source = [k for k in catalogue(SOURCE_LANG) if not k.startswith("_")]
    if not source:
        return 0.0
    cat = catalogue(lang)
    return sum(1 for k in source if isinstance(cat.get(k), str)) / len(source)


# --- Négociation Accept-Language --------------------------------------------------------

_LANG_BY_LOWER = {code.lower(): code for code in LANGS}
_LANG_BY_BASE = {}
for _code in LANGS:
    _LANG_BY_BASE.setdefault(_code.split("-")[0].lower(), _code)


def negotiate(accept_language: str | None) -> str:
    """Langue du site pour un en-tête Accept-Language : correspondance exacte (pt-BR), sinon par langue de base
    (pt-PT → pt-BR, zh-TW → zh-CN, fr-CA → fr) ; `en` si rien ne correspond."""
    if not accept_language:
        return DEFAULT_LANG
    ranked = []
    for i, part in enumerate(accept_language.split(",")):
        piece = part.strip()
        if not piece:
            continue
        tag, _, rest = piece.partition(";")
        q = 1.0
        m = re.search(r"q\s*=\s*([0-9.]+)", rest)
        if m:
            try:
                q = float(m.group(1))
            except ValueError:
                q = 0.0
        if q > 0 and tag.strip():
            ranked.append((-q, i, tag.strip().lower()))
    for _, _, tag in sorted(ranked):
        if tag == "*":
            return DEFAULT_LANG
        if tag in _LANG_BY_LOWER:
            return _LANG_BY_LOWER[tag]
        base = tag.split("-")[0]
        if base in _LANG_BY_BASE:
            return _LANG_BY_BASE[base]
    return DEFAULT_LANG
