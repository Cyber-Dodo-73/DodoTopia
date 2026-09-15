"""Site public (vitrine + pages légales), rendu en HTML par de simples f-strings.

Aucun framework front, aucune ressource externe : la feuille de style, les polices, le logo et la favicon
sont servis depuis `server/static` par `StaticFiles` (monté dans `main.py`). Toute donnée dynamique passe
par `esc()` (= `html.escape`) avant d'entrer dans le gabarit.

La page d'accueil interroge la base (dernière version publiée) : le HTML rendu est gardé en cache sur
`app.state` pendant `HOME_TTL_S`, et `invalidate(app)` le jette dès qu'une version est publiée ou supprimée.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import struct
import time
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from . import db, releases
from .config import SERVER_VERSION

log = logging.getLogger("dodo")
router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Windows ne connaît pas .woff2 dans la base de registre : sans ça StaticFiles renvoie
# application/octet-stream pour les polices.
mimetypes.add_type("font/woff2", ".woff2")

HOME_TTL_S = 300.0
PAGE_CACHE = "public, max-age=300"
DOC_CACHE = "public, max-age=3600"
LAST_UPDATE = "14 septembre 2026"

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")

# changefreq / priority du sitemap, par page (defaut : les pages legales, rarement modifiees).
SITEMAP_HINTS = {"/": ("weekly", "1.0"), "/instruments": ("monthly", "0.7")}
SITEMAP_DEFAULT = ("yearly", "0.4")

PAGES = {
    "/": ("Accueil", "DodoTopia — jouer vos MIDI, dessiner et cuisiner dans Heartopia"),
    "/instruments": ("Instruments", "Les instruments d'Heartopia pris en charge par DodoTopia"),
    "/mentions-legales": ("Mentions légales", "Mentions légales"),
    "/confidentialite": ("Confidentialité", "Politique de confidentialité"),
    "/conditions": ("Conditions", "Conditions d'utilisation"),
}


# --------------------------------------------------------------------------------------------------
# Identite de l'editeur et de l'hebergeur (mentions legales, confidentialite, conditions d'utilisation).
# Ces informations sont obligatoires : LCEN art. 6-III pour l'editeur et l'hebergeur, RGPD art. 13 pour
# le responsable de traitement. Un seul endroit a modifier si quelque chose change.
EDITEUR_NOM = "Dorian Breuillard"
EDITEUR_MARQUE = "Cyber-Dodo"
EDITEUR_STATUT = "entrepreneur individuel (micro-entreprise)"
EDITEUR_SIRET = "925 110 132 00022"
EDITEUR_TVA = "TVA non applicable, article 293 B du code général des impôts"
EDITEUR_ADRESSE = "718 chemin de la Cassine, 73000 Chambéry, France"
EDITEUR_COURRIEL = "contact@cyber-dodo.fr"
EDITEUR_TEL = "07 72 28 20 62"
HEBERGEUR_NOM = "OUIHEBERG SARL"
HEBERGEUR_ADRESSE = "9 rue des Colonnes, 75002 Paris, France"
HEBERGEUR_CONTACT = "RCS Paris 888 341 997 — ouiheberg.com"
HEBERGEUR_PAYS = "France, dans le centre de données de Marseille"
LICENCE = ("usage personnel gratuit. La redistribution, la modification, la décompilation et la "
           "commercialisation de l'application ne sont pas autorisées.")
DROIT = "français"


def esc(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def todo(what: str) -> str:
    """Marqueur bien visible pour une information que seul l'éditeur du site peut remplir."""
    return f'<span class="todo">[[À COMPLÉTER : {esc(what)}]]</span>'


def human_size(n: int) -> str:
    """Taille en Mo, avec une décimale sous 100 Mo (les binaires font entre 30 et 300 Mo)."""
    mo = max(0, int(n)) / (1024 * 1024)
    return f"{mo:.1f} Mo".replace(".", ",") if mo < 100 else f"{mo:.0f} Mo"


def human_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def dl_path(version: str, filename: str) -> str:
    """Chemin de téléchargement, chaque segment encodé (les données viennent de la base)."""
    return f"/dl/{quote(str(version), safe='')}/{quote(str(filename), safe='')}"


# --- Cache -------------------------------------------------------------------------

def invalidate(app) -> None:
    """Jette la page d'accueil en cache (publication / suppression d'une version)."""
    app.state.site_home = None


def _cached_home(request: Request) -> str:
    app = request.app
    entry = getattr(app.state, "site_home", None)
    if entry is not None and entry[0] > time.monotonic():
        return entry[1]
    html = render_home(app.state.settings)
    app.state.site_home = (time.monotonic() + HOME_TTL_S, html)
    return html


# --- Gabarit -----------------------------------------------------------------------

def head(settings, path: str, title: str, description: str, extra: str = "") -> str:
    base = settings.public_url
    url = f"{base}{path}"
    image = f"{base}/static/logo.png"
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(url)}">
<meta name="robots" content="index, follow">
<meta name="theme-color" content="#f4ead8">
<meta property="og:type" content="website">
<meta property="og:site_name" content="DodoTopia">
<meta property="og:locale" content="fr_FR">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:image" content="{esc(image)}">
<meta property="og:image:alt" content="Logo de DodoTopia : un dodo turquoise tenant une note de musique">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(description)}">
<meta name="twitter:image" content="{esc(image)}">
<link rel="icon" href="/static/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/static/logo.png">
<link rel="stylesheet" href="/static/site.css">
{extra}</head>
<body>
<a class="skip" href="#contenu">Aller au contenu</a>
<header class="site-header"><div class="wrap">
  <a class="brand" href="/">
    <img class="brand__logo" src="/static/logo.png" width="52" height="52"
         alt="Logo de DodoTopia : un dodo turquoise tenant une note de musique">
    <span class="brand__name">DodoTopia</span>
  </a>
  <nav class="header-nav" aria-label="Liens principaux">
    <a href="/#fonctionnalites">Fonctionnalités</a>
    <a href="/instruments"{' aria-current="page"' if path == '/instruments' else ''}>Instruments</a>
    <a href="/#demarrer">Comment ça marche</a>
    <a href="/#questions">Aide</a>
    <a class="header-nav__cta" href="/#telecharger">Télécharger</a>
  </nav>
</div></header>
<main id="contenu">
"""


def foot(version_line: str) -> str:
    return f"""</main>
<footer class="site-footer"><div class="wrap">
  <ul class="footer-nav">
    <li><a href="/">Accueil</a></li>
    <li><a href="/instruments">Instruments</a></li>
    <li><a href="/mentions-legales">Mentions légales</a></li>
    <li><a href="/confidentialite">Confidentialité</a></li>
    <li><a href="/conditions">Conditions d'utilisation</a></li>
  </ul>
  <p>Contact : <a href="mailto:{EDITEUR_COURRIEL}">{EDITEUR_COURRIEL}</a></p>
  <p>{version_line}</p>
  <p class="disclaimer">DodoTopia est un projet indépendant, sans aucun lien avec les éditeurs d'Heartopia.
     Heartopia et les marques citées appartiennent à leurs propriétaires respectifs.</p>
</div></footer>
</body>
</html>
"""


def page(settings, path: str, title: str, description: str, body: str,
         version_line: str = "", extra_head: str = "") -> str:
    line = version_line or f"Serveur {esc(SERVER_VERSION)}"
    return head(settings, path, title, description, extra_head) + body + foot(line)


# --- Illustrations (SVG en ligne, palette du site) -----------------------------------

# --- Captures de l'application ------------------------------------------------------
# Images produites a partir de l'interface reelle (donnees d'exemple). Dimensions reservees pour
# eviter tout decalage au chargement.
SHOT_W, SHOT_H = 1280, 812


def app_shot(name: str, alt: str, cls: str = "shot", eager: bool = False) -> str:
    """Capture de l'interface. `eager` pour l'image du heros (visible d'emblee), sinon chargement differe."""
    load = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<img class="{cls}" src="/static/app-{name}.png" width="{SHOT_W}" height="{SHOT_H}"'
            f' {load} decoding="async" alt="{esc(alt)}">')


def app_figure(name: str, alt: str, caption: str, cls: str = "shot", eager: bool = False) -> str:
    """Capture + legende + lien d'agrandissement : reduite dans la page, elle reste consultable en entier."""
    return (f'<figure class="shotfig">{app_shot(name, alt, cls, eager)}'
            f'<figcaption>{caption} · <a href="/static/app-{name}.png" target="_blank" rel="noopener">'
            f'ouvrir la capture en grand</a></figcaption></figure>')


# --- Catalogue d'instruments ----------------------------------------------------------
#
# Source de donnees : la MEME que l'application, `assets/instruments/catalogue.json` (+ `layouts.json`).
#
# Acces choisi : une COPIE BUILD-TIME sous `server/static/instruments/` (les deux JSON et une image PNG
# par type, reprise de `ui/instruments/`). Raison : le conteneur ne contient que `server/app` et
# `server/static` (voir `server/Dockerfile`), le dossier `assets/` du depot n'y est pas. La copie est donc
# la seule qui existe en production, et c'est elle que le site sert aux navigateurs : aucun hotlink, tout
# vient de /static.
#
# Anti-derive : `server/tests/test_site.py` compare octet par octet la copie et les fichiers du depot
# (`assets/instruments/*.json`, `ui/instruments/*.png`). Si le catalogue de l'application est mis a jour
# sans rafraichir la copie, les tests echouent. Hors conteneur, si la copie manque, on retombe sur les
# fichiers du depot pour que le site reste affichable.
#
# Mise a jour de la copie (depuis la racine du depot) :
#     cp assets/instruments/catalogue.json assets/instruments/layouts.json server/static/instruments/
#     cp ui/instruments/*.png server/static/instruments/

INST_DIR = STATIC_DIR / "instruments"
REPO_ROOT = STATIC_DIR.parent.parent
REPO_INST_DIR = REPO_ROOT / "assets" / "instruments"
REPO_IMG_DIR = REPO_ROOT / "ui" / "instruments"

# Etats affiches par le site. Trois seulement, et aucun ne vaut « verifie » : la verification se fait sur
# l'ordinateur du joueur, dans l'application. Ne jamais ajouter ici un etat « confirme » alimente par le
# catalogue : le catalogue ne confirme rien.
INST_STATES = {
    "documented": (
        "Profil documenté, à vérifier",
        "Une table de touches publiée par un projet communautaire existe pour ce type. Elle n'a pas été "
        "testée dans le jeu depuis ce site : DodoTopia la propose, et c'est sur ton ordinateur qu'elle se "
        "vérifie.",
    ),
    "candidate": (
        "Correspondance candidate, test requis",
        "Les tables communautaires associent des notes à cet instrument de percussion, mais rien ne prouve "
        "que chaque frappe produit cette hauteur. DodoTopia demande un test adapté aux percussions avant "
        "de l'autoriser à jouer un morceau.",
    ),
    "unknown": (
        "Touches à relever",
        "Aucune table de touches documentée pour ce type. L'instrument est présent dans DodoTopia et ses "
        "touches peuvent être configurées à la main, mais il ne peut pas lancer un morceau tant que ce "
        "n'est pas fait.",
    ),
}
STATE_ORDER = ("documented", "candidate", "unknown")

# Pastille de repli quand l'image d'un type manque : generique par famille, jamais l'icone d'un autre
# instrument (une conque n'est pas un saxophone).
FAMILY_FALLBACK = {"strings": "🎻", "winds": "🎶", "keys": "🎹", "percussion": "🥁"}

SAFE_IMAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.png$")

_CATALOGUE: dict | None = None


def _png_size(path: Path) -> tuple[int, int] | None:
    """Dimensions reelles d'un PNG (entete IHDR) : la place est reservee, la grille ne saute pas."""
    try:
        head = path.read_bytes()[:24]
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return (w, h) if 0 < w <= 4096 and 0 < h <= 4096 else None


def _instrument_json(name: str) -> dict:
    """Copie servie d'abord (seule presente en production), fichier du depot en secours."""
    for base in (INST_DIR, REPO_INST_DIR):
        path = base / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(name)


def _state_of(inst: dict) -> str:
    """Trois etats, deduits du catalogue seul : documente / candidat (percussion) / a relever."""
    if not inst.get("supportedLayoutIds") or inst.get("mappingStatus") in (None, "", "unknown"):
        return "unknown"
    return "candidate" if inst.get("percussive") else "documented"


MAJOR_SCALE = {0, 2, 4, 5, 7, 9, 11}


def _describe_layout(layout: dict) -> dict:
    """Libelles d'affichage deduits des notes elles-memes.

    Les libelles de `layouts.json` sont ecrits sans accents (ils servent aussi de commentaires de donnees) :
    on ne les affiche pas tels quels sur le site. Tout ce qui est montre ici (registre, nombre de rangees,
    alterations) est recalcule a partir de la table de notes, donc toujours d'accord avec elle.
    """
    notes = layout.get("notes") or []
    midis = [n["midi"] for n in notes if isinstance(n.get("midi"), int)]
    count = layout.get("noteCount") or len(notes)
    rows = len(layout.get("rows") or []) or 1
    chromatic = len(midis) > 1 and all(b - a == 1 for a, b in zip(midis, midis[1:]))
    if chromatic:
        accidentals = "Toutes les altérations"
    elif midis and {m % 12 for m in midis} <= MAJOR_SCALE:
        accidentals = "Gamme de do majeur, sans altération"
    else:
        accidentals = "Gamme partielle"
    return {
        "range": f"{notes[0].get('solfege', '')} → {notes[-1].get('solfege', '')}" if notes else "",
        "rows": rows,
        "chromatic": chromatic,
        "accidentals": accidentals,
        "label": f"{count} notes, {'chromatique' if chromatic else 'diatonique'}",
        "rows_label": f"{rows} rangée{'s' if rows > 1 else ''}",
    }


def _build_catalogue() -> dict:
    """Prepare une fois les donnees d'affichage (les fichiers ne changent pas en cours d'execution)."""
    raw = _instrument_json("catalogue.json")
    layouts_raw = _instrument_json("layouts.json")
    layouts = {lay["layoutId"]: lay for lay in layouts_raw.get("layouts", [])}
    cat_labels = {c["id"]: c["labelFr"] for c in raw.get("categories", [])}

    types = []
    used: dict[str, int] = {}
    for inst in raw.get("instruments", []):
        name = Path(str(inst.get("image") or "")).name
        image = None
        if SAFE_IMAGE_NAME.match(name) and (INST_DIR / name).is_file():
            size = _png_size(INST_DIR / name) or (160, 160)
            image = {"url": f"/static/instruments/{quote(name)}", "w": size[0], "h": size[1]}
        layout = layouts.get(inst.get("defaultLayoutId") or "")
        if layout:
            info = _describe_layout(layout)
            summary = (f"{layout.get('noteCount') or len(layout.get('notes') or [])} notes · "
                       f"{info['range']} · {'chromatique' if info['chromatic'] else 'diatonique'}")
        else:
            summary = "Nombre de notes et registre à relever"
        for lid in inst.get("supportedLayoutIds") or []:
            used[lid] = used.get(lid, 0) + 1
        types.append({
            "id": inst["instrumentId"],
            "label_fr": inst.get("labelFr") or inst["instrumentId"],
            "label_en": inst.get("labelEn") or "",
            "category": inst.get("category") or "",
            "category_label": cat_labels.get(inst.get("category"), ""),
            "image": image,
            "state": _state_of(inst),
            "summary": summary,
            "variant_count": int(inst.get("variantCount") or 1),
            "item_url": next((u for u in (inst.get("sourceUrls") or [])
                              if str(u).startswith("https://build-heartopia.com/items/")), ""),
        })

    ordered_layouts = [{
        "id": lay["layoutId"],
        "note_count": lay.get("noteCount") or len(lay.get("notes") or []),
        "used_by": used.get(lay["layoutId"], 0),
        **_describe_layout(lay),
    } for lay in layouts_raw.get("layouts", [])]

    # Sources citees sur la page : celles du catalogue, puis celles des tables de touches, dedupliquees
    # en gardant l'ordre. Rien n'est ecrit en dur : une source ajoutee aux donnees apparait sur le site.
    sources: list[str] = []
    for url in list(raw.get("sourceUrls") or []) + [u for lay in layouts_raw.get("layouts", [])
                                                    for u in (lay.get("sourceUrls") or [])]:
        url = str(url)
        if url.startswith("https://") and url not in sources:
            sources.append(url)

    return {
        "types": types,
        "layouts": ordered_layouts,
        "counts": {state: sum(1 for t in types if t["state"] == state) for state in STATE_ORDER},
        "total": len(types),
        "categories": [(c["id"], c["labelFr"]) for c in raw.get("categories", [])],
        "retrieved_at": raw.get("retrievedAt") or "",
        "octave_convention": raw.get("octaveConvention") or "",
        "source_urls": sources,
    }


EMPTY_CATALOGUE = {"types": [], "layouts": [], "counts": dict.fromkeys(STATE_ORDER, 0), "total": 0,
                   "categories": [], "retrieved_at": "", "octave_convention": "", "source_urls": []}


def instrument_catalogue() -> dict:
    """Catalogue prepare, garde en memoire. Un fichier absent ou illisible ne doit pas tuer le site :
    on renvoie un catalogue vide (la section de l'accueil disparait, la page le dit) et on reessaie au
    coup suivant, pour qu'un deploiement repare se rattrape sans redemarrage."""
    global _CATALOGUE
    if _CATALOGUE is None:
        try:
            _CATALOGUE = _build_catalogue()
        except (OSError, ValueError, KeyError, TypeError):
            log.exception("catalogue d'instruments illisible")
            return dict(EMPTY_CATALOGUE)
    return _CATALOGUE


def inst_media(inst: dict) -> str:
    """Visuel d'un type : fichier local servi depuis /static, pastille de famille si l'image manque."""
    image = inst["image"]
    if not image:
        emoji = FAMILY_FALLBACK.get(inst["category"], "🎵")
        return (f'<span class="inst__media inst__media--none" role="img"'
                f' aria-label="Aucun visuel disponible pour {esc(inst["label_fr"])}">{emoji}</span>')
    alt = f"Icône de l'instrument {inst['label_fr']} dans Heartopia"
    return (f'<span class="inst__media"><img src="{esc(image["url"])}" width="{image["w"]}"'
            f' height="{image["h"]}" loading="lazy" decoding="async" alt="{esc(alt)}"></span>')


def state_pill(state: str) -> str:
    """Pastille d'etat : le texte porte l'information, la forme et la couleur ne font que l'appuyer."""
    return (f'<p class="pill pill--{state}"><span class="pill__dot" aria-hidden="true"></span>'
            f'{esc(INST_STATES[state][0])}</p>')


def inst_card(inst: dict) -> str:
    """Une carte par type. Jamais une carte par couleur ni par variante."""
    en = f' · <span class="inst__en">{esc(inst["label_en"])}</span>' if inst["label_en"] else ""
    return f"""<li class="inst">
        {inst_media(inst)}
        <h3>{esc(inst['label_fr'])}</h3>
        <p class="inst__meta">{esc(inst['category_label'])}{en}</p>
        {state_pill(inst['state'])}
        <p class="inst__sum">{esc(inst['summary'])}</p>
      </li>"""


def instruments_teaser() -> str:
    """Section « Choisis ton instrument » de l'accueil : quelques vrais visuels et un lien vers la liste.

    Les nombres viennent du catalogue : rien n'est ecrit en dur, rien ne peut mentir apres une mise a jour.
    """
    cat = instrument_catalogue()
    if not cat["types"]:
        return ""                       # catalogue illisible : pas de section plutot qu'une section vide
    by_id = {t["id"]: t for t in cat["types"]}
    # Un echantillon volontairement melange : les quatre familles, et un type dont les touches restent
    # a relever (ocarina) pour ne pas laisser croire que tout est pret.
    sample = [by_id[i] for i in ("piano", "violin", "lute", "recorder", "conga", "ocarina") if i in by_id]
    if not sample:
        sample = cat["types"][:6]
    icons = "".join(f'<li class="insttease__item">{inst_media(t)}'
                    f'<span class="insttease__name">{esc(t["label_fr"])}</span></li>' for t in sample)
    c = cat["counts"]
    return f"""<section class="section" id="choisir-instrument"><div class="wrap">
  <h2>Choisis ton instrument</h2>
  <p class="lead">DodoTopia connaît {cat['total']} types d'instruments d'Heartopia : une carte par type,
     jamais une carte par couleur. Tu choisis celui que tu as ouvert dans le jeu, et DodoTopia utilise sa
     table de touches — pas celle du piano.</p>
  <ul class="insttease">{icons}</ul>
  <p>Sur ces {cat['total']} types, {c['documented']} ont un <strong>profil de touches documenté</strong> par
     un projet communautaire, restant à vérifier ; {c['candidate']} sont des percussions dont la
     correspondance est <strong>candidate</strong> et demande un test ; {c['unknown']} attendent encore le
     <strong>relevé de leurs touches</strong>. Aucun profil n'est confirmé tant que tu ne l'as pas vérifié
     sur ton ordinateur : la vérification se fait dans l'application, pas ici.</p>
  <p><a class="btn btn--quiet" href="/instruments">Voir la liste des instruments</a></p>
</div></section>
"""


def render_instruments(settings) -> str:
    cat = instrument_catalogue()
    c = cat["counts"]
    total = cat["total"]
    if not cat["types"]:
        # Catalogue illisible (fichier manquant ou abime) : page honnete, pas de trace technique.
        return page(settings, "/instruments", "Instruments pris en charge — DodoTopia",
                    "Liste des instruments d'Heartopia pris en charge par DodoTopia.",
                    """<section class="section"><div class="wrap">
  <h1>Les instruments pris en charge</h1>
  <div class="notice"><p>La liste des instruments n'est pas consultable pour le moment. Elle revient
     d'elle-même ; la liste complète reste disponible dans l'application, activité Musique.</p></div>
</div></section>
""")

    legend = "".join(
        f'<li class="statecard statecard--{state}">{state_pill(state)}'
        f'<p class="statecard__n">{c[state]} type{"s" if c[state] > 1 else ""} sur {total}</p>'
        f'<p class="statecard__txt">{esc(INST_STATES[state][1])}</p></li>'
        for state in STATE_ORDER)

    groups = []
    for cat_id, cat_label in cat["categories"]:
        items = [t for t in cat["types"] if t["category"] == cat_id]
        if not items:
            continue
        cards = "".join(inst_card(t) for t in items)
        groups.append(f"""<h2 id="famille-{esc(cat_id)}">{esc(cat_label)}"""
                      f""" <span class="h2count">{len(items)} type{'s' if len(items) > 1 else ''}</span></h2>
  <ul class="instgrid">{cards}</ul>""")

    rows = "".join(
        f'<tr><td data-label="Disposition"><strong>{esc(lay["label"])}</strong><br>'
        f'<span class="mono">{esc(lay["id"])}</span></td>'
        f'<td data-label="Notes">{esc(lay["note_count"])}</td>'
        f'<td data-label="Registre">{esc(lay["range"])}</td>'
        f'<td data-label="Altérations">{esc(lay["accidentals"])}</td>'
        f'<td data-label="Rangées">{esc(lay["rows_label"])}</td>'
        f'<td data-label="Types concernés">{esc(lay["used_by"])} sur {cat["total"]}</td></tr>'
        for lay in cat["layouts"])

    sources = "".join(f'<li><a href="{esc(u)}" rel="nofollow noopener" target="_blank">{esc(u)}</a></li>'
                      for u in cat["source_urls"])
    # Provenance du visuel : la fiche d'objet du catalogue public d'ou vient l'icone. Les tables de touches
    # sont citees une fois pour toutes juste au-dessus, inutile de les repeter 19 fois.
    per_type = "".join(
        f'<li><strong>{esc(t["label_fr"])}</strong> — '
        + (f'<a href="{esc(t["item_url"])}" rel="nofollow noopener" target="_blank">fiche de l\'objet sur '
           "build-heartopia.com</a>" if t["item_url"] else "provenance du visuel non retenue")
        + (f' · {t["variant_count"]} variantes esthétiques regroupées en un seul type'
           if t["variant_count"] > 1 else " · une seule entrée au catalogue")
        + "</li>"
        for t in cat["types"])

    title = "Instruments pris en charge — DodoTopia"
    description = (f"Les {total} types d'instruments d'Heartopia connus de DodoTopia, avec pour chacun "
                   "l'état réel de son profil de touches : documenté, candidat ou à relever.")
    body = f"""<section class="section"><div class="wrap">
  <h1>Les instruments pris en charge</h1>
  <p class="lead">Retrouve ton instrument parmi {total} types et vérifie son profil de touches
     avant de jouer. Choisis ensuite le même instrument dans DodoTopia et dans Heartopia.</p>
  <div class="notice notice--soft">
    <p><strong>Présent au catalogue n'est pas lecture vérifiée.</strong> Être dans cette liste signifie que
       DodoTopia connaît le type d'instrument et lui réserve une place. Cela ne veut pas dire que ses
       touches ont été testées dans le jeu : aucune des tables présentées ici n'a été validée dans
       Heartopia depuis ce site. La vérification se fait sur ton ordinateur, instrument par instrument,
       avec l'assistant de l'application — c'est lui qui fait passer un profil de « documenté » à
       « confirmé sur cet ordinateur ».</p>
  </div>
  <ul class="states">{legend}</ul>
  <nav class="family-nav" aria-label="Familles d'instruments">
    {''.join(f'<a href="#famille-{esc(key)}">{esc(label)}</a>' for key, label in cat['categories'] if any(t['category'] == key for t in cat['types']))}
  </nav>
</div></section>

<section class="section"><div class="wrap">
  {"".join(groups)}
  <p class="dl-note">Une seule carte par type : les variantes de couleur et de style du catalogue du jeu
     partagent le même son et les mêmes touches, elles sont regroupées et n'apparaissent pas séparément.
     Les noms français sont des traductions proposées, pas les libellés officiels du jeu ; les noms
     anglais restent utilisables dans la recherche de l'application.</p>
</div></section>

<section class="section"><div class="wrap">
  <h2>Les dispositions de touches</h2>
  <p>Un type d'instrument peut accepter plusieurs dispositions : ce sont des réglages de sa fiche, pas
     des instruments différents. Il faut choisir dans DodoTopia <strong>la même disposition que celle
     affichée dans le jeu</strong>.</p>
  <div class="table-scroll">
  <table class="layouts">
    <thead><tr><th>Disposition</th><th>Notes</th><th>Registre</th><th>Altérations</th>
      <th>Rangées</th><th>Types concernés</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
  <p class="dl-note">Attention : les deux dispositions à 15 notes ne diffèrent pas seulement par leur
     présentation, leurs touches physiques ne sont pas les mêmes. Le nombre de rangées ne permet pas de
     deviner le nombre de notes. Convention d'octave : {esc(cat['octave_convention'])}, écrit
     <strong>Do4</strong> dans les libellés français de cette page.</p>
</div></section>

<section class="section section--tight"><div class="wrap">
  <h2>D'où viennent ces informations</h2>
  <p>Catalogue relevé le {esc(human_date(cat['retrieved_at']) or cat['retrieved_at'])}. Ce n'est pas une
     liste officielle et elle n'est pas
     forcément exhaustive : un type confirmé par une source fiable peut s'y ajouter, avec son propre état.
     Les tables de touches viennent de projets communautaires publics, cités ci-dessous ; elles décrivent
     ce que ces projets ont publié, rien de plus.</p>
  <ul>{sources}</ul>
  <details class="news">
    <summary>Provenance des visuels, type par type</summary>
    <div class="faq__body">
      <p>Les icônes affichées sur cette page sont servies depuis ce serveur, à partir des fichiers
         embarqués dans DodoTopia : aucune image n'est chargée depuis un site tiers. Elles proviennent du
         catalogue public d'objets d'Heartopia recensé par Build Heartopia. Leur présence publique ne vaut
         pas licence de réutilisation libre : si un ayant droit souhaite le retrait d'un visuel, il suffit
         d'écrire à {EDITEUR_COURRIEL} — l'image est retirée et remplacée par une pastille générique, sans
         que l'instrument disparaisse de la liste ni que ses touches changent.</p>
      <ul class="prov">{per_type}</ul>
    </div>
  </details>
</div></section>

<section class="section section--tight"><div class="wrap">
  <div class="notice">
    <p><strong>Ce que cette page ne dit pas.</strong> Elle ne dit pas que tous les instruments sont
       compatibles, ni qu'un instrument documenté jouera juste du premier coup. Elle ne dit rien non plus
       du son : DodoTopia envoie des touches au jeu, c'est Heartopia qui produit la musique. Choisir un
       instrument ici, ou dans l'application, ne l'équipe pas dans le jeu : c'est à toi de l'ouvrir.</p>
  </div>
</div></section>
"""
    return page(settings, "/instruments", title, description, body)


# --- Accueil -------------------------------------------------------------------------

def latest_release(settings) -> dict | None:
    conn = db.connect(settings)
    try:
        versions = releases.published_versions(conn)
        return releases.manifest(conn, settings, versions[0]) if versions else None
    finally:
        conn.close()


def hero_download(latest: dict | None) -> str:
    """Zone de telechargement du heros : une seule action principale, une ligne de version compacte."""
    if not latest:
        return """<div class="soon">
      <h2>Bientôt disponible</h2>
      <p>Aucune version n'est publiée pour l'instant. La première version téléchargeable arrive bientôt :
         reviens d'ici quelques jours, cette page proposera alors l'installeur Windows et l'archive Linux.</p>
    </div>"""
    version = esc(latest["version"])
    assets = latest.get("assets") or {}
    win = assets.get("windows-setup")
    lin = assets.get("linux-x64")
    main = ""
    if win:
        main = f"""<a class="btn btn--cta" href="{esc(dl_path(latest['version'], win['filename']))}"
         download data-platform="windows-setup">
        <span class="btn__ico" aria-hidden="true">⬇</span>
        <span class="btn__txt"><span>Télécharger pour Windows</span>
          <span class="btn__sub">Installeur · {esc(human_size(win['size']))}</span></span>
      </a>"""
    elif lin:
        main = f"""<a class="btn btn--cta" href="{esc(dl_path(latest['version'], lin['filename']))}"
         download data-platform="linux-x64">
        <span class="btn__ico" aria-hidden="true">⬇</span>
        <span class="btn__txt"><span>Télécharger pour Linux</span>
          <span class="btn__sub">Archive · {esc(human_size(lin['size']))}</span></span>
      </a>"""
    return (f'<div class="dl-row">{main}'
            '<a class="btn btn--quiet" href="#demarrer">Voir comment ça marche</a></div>'
            f'<p class="dl-note">Version {version} · gratuit, sans compte obligatoire · '
            f'<a href="#telecharger">autres téléchargements</a></p>')


def download_section(latest: dict | None) -> tuple[str, str]:
    """(HTML de la section Telechargement, ligne de version pour le pied de page).

    Toutes les donnees (version, taille, nom de fichier, notes) viennent des publications enregistrees :
    rien n'est ecrit en dur ici ni ailleurs dans la page.
    """
    if not latest:
        html = """<div class="soon">
    <h2>Bientôt disponible</h2>
    <p>Aucune version n'est publiée pour l'instant. La première version téléchargeable arrive bientôt :
       reviens d'ici quelques jours, cette page proposera alors l'installeur Windows et l'archive Linux.</p>
  </div>"""
        return html, f"Aucune version publiée pour l'instant · Serveur {esc(SERVER_VERSION)}"

    version = esc(latest["version"])
    date = esc(human_date(latest.get("published_at")))
    assets = latest.get("assets") or {}
    buttons = []

    win = assets.get("windows-setup")
    if win:
        buttons.append(f"""<a class="btn btn--cta" href="{esc(dl_path(latest['version'], win['filename']))}"
       download data-platform="windows-setup">
      <span class="btn__ico" aria-hidden="true">⬇</span>
      <span class="btn__txt"><span>Télécharger pour Windows</span>
        <span class="btn__sub">Installeur · {esc(human_size(win['size']))} · version {version}</span></span>
    </a>""")

    lin = assets.get("linux-x64")
    if lin:
        buttons.append(f"""<a class="btn" href="{esc(dl_path(latest['version'], lin['filename']))}"
       download data-platform="linux-x64">
      <span class="btn__ico" aria-hidden="true">⬇</span>
      <span class="btn__txt"><span>Télécharger pour Linux</span>
        <span class="btn__sub">Archive · {esc(human_size(lin['size']))} · version {version}</span></span>
    </a>""")

    notes = []
    por = assets.get("windows-portable")
    if por:
        notes.append("<strong>Installeur ou version portable ?</strong> L'installeur met DodoTopia dans le menu "
                     "Démarrer et se met à jour tout seul : c'est le choix conseillé. La "
                     f'<a href="{esc(dl_path(latest["version"], por["filename"]))}" download>version portable pour '
                     f'Windows</a> ({esc(human_size(por["size"]))}) se dézippe où tu veux, sans installation, '
                     "mais se met à jour à la main.")
    if not lin:
        notes.append("Aucune archive Linux n'accompagne cette publication.")
    notes.append("Sur macOS, sur téléphone ou sur tablette, DodoTopia ne fonctionne pas : il a besoin d'envoyer "
                 "des touches et de lire l'écran d'un ordinateur Windows ou Linux où tourne le jeu.")
    notes.append(f"Version {version}{f' · publiée le {date}' if date else ''} · "
                 "chaque fichier est vérifié par son empreinte SHA-256 au téléchargement.")

    release_notes = ""
    raw_notes = (latest.get("notes") or "").strip()
    if raw_notes:
        body = "".join(f"<li>{esc(line.strip(' -•	'))}</li>"
                       for line in raw_notes.splitlines()[:6] if line.strip())
        if body:
            release_notes = (f'<details class="news"><summary>Voir les nouveautés de la version {version}</summary>'
                             f'<div class="faq__body"><ul>{body}</ul></div></details>')

    html = (f'<div class="dl-row">{"".join(buttons)}</div>'
            + "".join(f'<p class="dl-note">{n}</p>' for n in notes) + release_notes)
    return html, f"Dernière version : {version}{f' ({date})' if date else ''} · Serveur {esc(SERVER_VERSION)}"


def json_ld(settings, latest: dict | None) -> str:
    base = settings.public_url
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "DodoTopia",
        "description": ("Boîte à outils gratuite pour Heartopia : jouer des fichiers MIDI dans le jeu, "
                        "transformer une image en dessin, refaire une recette en boucle."),
        "url": f"{base}/",
        "image": f"{base}/static/logo.png",
        "applicationCategory": "GameApplication",
        "applicationSubCategory": "Utilitaire de jeu",
        "operatingSystem": "Windows 10, Windows 11, Linux",
        "inLanguage": "fr",
        "isAccessibleForFree": True,
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
    # `</script>` et `<` sont neutralisés : le JSON-LD vit dans un élément <script>.
    body = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    return f'<script type="application/ld+json">{body}</script>\n'


def render_home(settings) -> str:
    latest = latest_release(settings)
    downloads, version_line = download_section(latest)
    hero = hero_download(latest)
    title = "DodoTopia — jouer vos MIDI, dessiner et cuisiner dans Heartopia"
    description = ("DodoTopia est une application gratuite qui joue tes fichiers MIDI, peint tes images et "
                   "refait tes recettes dans Heartopia, à ta place. Windows et Linux.")
    body = f"""<section class="section hero"><div class="wrap">
  <div class="hero__txt">
    <p class="eyebrow">Application gratuite pour Heartopia</p>
    <h1>Musique, dessin et cuisine dans Heartopia, avec ton dodo à tes côtés.</h1>
    <p class="lead">Importe un morceau MIDI ou une image, prépare ton activité dans DodoTopia, puis lance
      l'automatisation : le jeu reçoit les touches et les clics à ta place, pendant que tu regardes.</p>
    {hero}
  </div>
  {app_figure("musique", "L'application DodoTopia, activité Musique : la bibliothèque des morceaux à gauche, le lecteur, le choix de l'instrument et le bouton « Jouer dans Heartopia » à droite.", "L'application, activité Musique", "shot shot--hero", eager=True)}
</div></section>

<section class="section" id="fonctionnalites"><div class="wrap">
  <h2>Trois activités</h2>
  <div class="cards">
    <article class="card">
      {app_figure("musique", "Activité Musique : liste des morceaux importés, instrument, vitesse et bouton de lancement.", "Activité Musique")}
      <h3>Musique</h3>
      <p class="card__lead">Joue tes partitions sur les instruments du jeu sans apprendre le doigté.</p>
      <p>Importe un fichier <code>.mid</code>, choisis l'instrument ouvert dans Heartopia et lance :
         DodoTopia appuie sur les touches au bon moment. Tu peux préécouter le morceau sur ton ordinateur
         avant de le jouer dans le jeu, et jouer à plusieurs, chacun sur son instrument.</p>
      <p class="card__need"><strong>Il te faut :</strong> un fichier MIDI, et un instrument ouvert dans le jeu.</p>
    </article>
    <article class="card">
      {app_figure("dessin", "Activité Dessin : aperçu de l'image convertie case par case, réglages de format et de couleurs.", "Activité Dessin")}
      <h3>Dessin</h3>
      <p class="card__lead">Reproduis une image sur la toile du jeu, case par case.</p>
      <p>Choisis une photo ou un dessin : DodoTopia le convertit sur les couleurs de la palette d'Heartopia,
         te montre le rendu exact avant de commencer, puis le peint au crayon et au pot de peinture.</p>
      <p class="card__need"><strong>Il te faut :</strong> une image, et une configuration à faire une fois pour
         montrer où sont la toile, la palette et les outils à l'écran.</p>
    </article>
    <article class="card">
      {app_figure("cuisine", "Activité Cuisine : quantité de plats, nombre de cuisinières et suivi de la boucle.", "Activité Cuisine")}
      <h3>Cuisine</h3>
      <p class="card__lead">Refais la même recette en boucle pendant que tu fais autre chose.</p>
      <p>Place-toi devant la cuisinière : DodoTopia relance la dernière recette cuisinée, clique la spatule
         quand l'anneau vert apparaît et récupère le plat. Choisis un nombre de plats, ou laisse tourner en continu.</p>
      <p class="card__need"><strong>Il te faut :</strong> les ingrédients de la recette, et une configuration à
         faire une fois devant la cuisinière.</p>
    </article>
  </div>
  <div class="notice notice--soft">
    <p><strong>Jouer ensemble.</strong> Deux façons de démarrer au même instant : le <em>salon en ligne</em>,
       où un code à six caractères réunit les joueurs et où le chef choisit le morceau et donne le départ, et la
       <em>synchronisation par le son</em>, sans réseau, où le premier joueur joue une note repère que les autres
       détectent. Chacun garde son instrument. Le résultat dépend de ta machine et de ta connexion : les départs
       sont calés au mieux, pas parfaits.</p>
  </div>
</div></section>

{instruments_teaser()}
<section class="section" id="demarrer"><div class="wrap">
  <h2>Comment ça marche</h2>
  <div class="steps">
    <div class="step">
      <div class="step__num" aria-hidden="true">1</div>
      <h3>Installe DodoTopia</h3>
      <p>Télécharge l'installeur Windows ou l'archive Linux, puis lance l'application à côté du jeu.
         Tes musiques, tes images et tes réglages restent sur ton ordinateur.</p>
    </div>
    <div class="step">
      <div class="step__num" aria-hidden="true">2</div>
      <h3>Choisis une activité</h3>
      <p>Musique, Dessin ou Cuisine, en haut de la fenêtre. Chaque activité te dit ce qui lui manque
         et quelle est la prochaine chose à faire.</p>
    </div>
    <div class="step">
      <div class="step__num" aria-hidden="true">3</div>
      <h3>Prépare Heartopia</h3>
      <p>Ouvre l'instrument, la toile, ou place-toi devant la cuisinière. Pour le dessin et la cuisine,
         une configuration guidée te demande une fois où se trouvent les éléments à l'écran.</p>
    </div>
    <div class="step">
      <div class="step__num" aria-hidden="true">4</div>
      <h3>Lance, et reprends la main quand tu veux</h3>
      <p>Le bouton de lancement de l'activité, ou son raccourci clavier — <kbd>F6</kbd> par défaut, modifiable
         dans les réglages. Pour tout arrêter : <kbd>F7</kbd>, n'importe quelle touche, ou un clic.</p>
    </div>
  </div>
  <div class="examples">
    <details open>
      <summary>Un exemple en musique</summary>
      <div class="faq__body">
        <ol>
          <li>Importe un fichier <code>.mid</code> dans « Ma bibliothèque », ou récupères-en un dans
              « Découvrir des morceaux ».</li>
          <li>Dans Heartopia, ouvre ton instrument.</li>
          <li>Choisis le même instrument dans DodoTopia, puis appuie sur <kbd>F6</kbd>.</li>
        </ol>
        <p>Vérifie le profil de ton instrument avant de jouer : certains demandent de configurer
           leurs touches ou de faire un test guidé dans l'application.</p>
      </div>
    </details>
    <details>
      <summary>Un exemple en dessin</summary>
      <div class="faq__body">
        <ol>
          <li>Importe une image : DodoTopia montre le rendu case par case et le format retenu.</li>
          <li>Dans Heartopia, ouvre une toile vide à ce format, finesse des détails au maximum, grille activée.</li>
          <li>La première fois, suis « Configurer la zone du jeu » : treize positions à survoler, une par une.</li>
          <li>Appuie sur <kbd>F6</kbd> et ne touche plus à la souris jusqu'à la fin.</li>
        </ol>
        <p>Un dessin interrompu ne peut pas être repris là où il s'est arrêté.</p>
      </div>
    </details>
    <details>
      <summary>Un exemple en cuisine</summary>
      <div class="faq__body">
        <ol>
          <li>Cuisine une fois toi-même la recette voulue : DodoTopia refait la dernière recette du jeu,
              il ne la choisit pas.</li>
          <li>Place-toi devant la cuisinière, bulle visible, puis suis « Configurer la cuisine ».</li>
          <li>Choisis un nombre de plats — ou « en continu » — puis appuie sur <kbd>F6</kbd>.</li>
        </ol>
        <p>Un mouvement de souris ou une touche arrêtent la boucle et te rendent la main.</p>
      </div>
    </details>
  </div>
</div></section>

<section class="section" id="telecharger"><div class="wrap">
  <h2>Télécharger</h2>
  {downloads}
</div></section>

<section class="section" id="questions"><div class="wrap">
  <h2>Questions fréquentes</h2>
  <div class="faq">
    <details>
      <summary>Est-ce que c'est gratuit ?</summary>
      <div class="faq__body">
        <p>Oui, entièrement. DodoTopia est gratuit, sans publicité, sans achat intégré, sans abonnement et
           sans version payante cachée. Un compte Discord n'est demandé que si tu veux partager tes morceaux
           ou jouer en salon ; tout le reste — musique, dessin, cuisine — fonctionne sans compte et sans
           connexion.</p>
      </div>
    </details>
    <details>
      <summary>Sur quoi est-ce que ça fonctionne ?</summary>
      <div class="faq__body">
        <p>Sur un ordinateur Windows 10 ou 11, et sur Linux quand une archive est publiée pour la version en
           cours (la zone de téléchargement ci-dessus le dit). Il n'y a pas de version macOS, ni pour téléphone
           ou tablette : DodoTopia doit envoyer des touches et lire l'écran de la machine où tourne le jeu.</p>
      </div>
    </details>
    <details>
      <summary>Quels fichiers puis-je utiliser ?</summary>
      <div class="faq__body">
        <p>Pour la musique, des fichiers MIDI : <code>.mid</code> et <code>.midi</code>. Pour le dessin, des
           images <code>.png</code>, <code>.jpg</code>, <code>.gif</code>, <code>.bmp</code> et
           <code>.webp</code>. Les fichiers importés sont copiés dans ton dossier DodoTopia ; l'original
           n'est pas modifié.</p>
      </div>
    </details>
    <details>
      <summary>Faut-il que le jeu soit ouvert ?</summary>
      <div class="faq__body">
        <p>Oui. DodoTopia ne joue pas tout seul dans le vide : il appuie sur des touches et clique dans la
           fenêtre d'Heartopia, qui doit être ouverte et active au moment du lancement. Tu peux en revanche
           préécouter un morceau sur ton ordinateur sans lancer le jeu : dans ce cas, rien n'est envoyé nulle
           part.</p>
      </div>
    </details>
    <details>
      <summary>Y a-t-il une configuration à faire au début ?</summary>
      <div class="faq__body">
        <p>Pour la musique, non : choisis l'instrument et lance. Pour le dessin et la cuisine, oui, une fois :
           DodoTopia a besoin de savoir où se trouvent, sur ton écran, la toile, la palette, les outils ou la
           bulle de la cuisinière. Un assistant te guide position par position, et la configuration est
           conservée. Elle est à refaire si tu changes de résolution ou de disposition de fenêtre.</p>
      </div>
    </details>
    <details>
      <summary>Comment arrêter une automatisation en cours ?</summary>
      <div class="faq__body">
        <p><kbd>F7</kbd> par défaut arrête tout, et le raccourci est modifiable. Pendant un dessin ou une
           cuisine, n'importe quelle touche ou un mouvement de souris suffisent aussi ; pendant une lecture
           dans le jeu, une touche ou un clic gauche arrêtent la lecture. L'écran affiche à chaque instant
           l'état réel et le bouton d'arrêt.</p>
      </div>
    </details>
    <details>
      <summary>Est-ce que c'est un logiciel espion ?</summary>
      <div class="faq__body">
        <p>Non. Mais soyons francs sur ce que fait l'application, parce que c'est inhabituel : DodoTopia
           <strong>envoie des appuis de touches et des clics de souris</strong> à la fenêtre du jeu, et
           <strong>lit l'image de ton écran</strong>. C'est exactement ce que tu lui demandes de faire :
           on ne peut pas jouer d'un instrument, peindre un dessin case par case ou surveiller une cuisinière
           à ta place sans appuyer sur des touches et sans regarder ce qui s'affiche.</p>
        <p>Ces deux comportements sont aussi ceux d'un enregistreur de frappe : c'est précisément pour cela que
           Windows SmartScreen ou un antivirus peuvent afficher un avertissement au premier lancement. Ce que
           DodoTopia ne fait pas : enregistrer ce que tu tapes ailleurs, fouiller tes autres fenêtres, toucher
           à tes mots de passe, ni envoyer tes captures d'écran où que ce soit — elles sont analysées en mémoire
           sur ta machine puis jetées.</p>
        <p>Sans compte, la seule chose que l'application envoie sur le réseau est la
           <strong>vérification de mise à jour</strong> : elle demande à ce serveur s'il existe une version plus
           récente, en indiquant la version installée et la plateforme. Chaque version publiée est vérifiée par
           son <strong>empreinte sha256</strong> au téléchargement, ce qui garantit que le fichier reçu est bien
           celui qui a été publié. Le détail complet de ce qui est collecté est sur la page
           <a href="/confidentialite">Confidentialité</a>.</p>
      </div>
    </details>
    <details>
      <summary>Est-ce que je risque quelque chose sur mon compte de jeu ?</summary>
      <div class="faq__body">
        <p>Honnêtement : c'est possible, et nous ne pouvons rien te garantir. DodoTopia est un
           <strong>outil non officiel</strong>, sans aucun lien avec les éditeurs d'Heartopia. L'usage d'un
           logiciel d'automatisation peut être contraire aux conditions d'utilisation du jeu, et l'éditeur reste
           libre de sanctionner un compte comme il l'entend.</p>
        <p>DodoTopia n'injecte rien dans le jeu, ne modifie aucun fichier du jeu et ne lit pas sa mémoire :
           il se contente d'appuyer sur des touches et de regarder l'écran, comme le ferait une personne très
           rapide. Cela réduit le risque, mais ne l'élimine pas. <strong>Tu l'utilises à tes propres
           risques.</strong></p>
      </div>
    </details>
    <details>
      <summary>Quelles données sont collectées ?</summary>
      <div class="faq__body">
        <p>Hors ligne, aucune : tes fichiers MIDI, tes images, tes réglages et tes journaux restent sur ton
           ordinateur. L'application contacte ce serveur uniquement pour vérifier s'il existe une mise à jour
           (elle transmet alors la version installée et la plateforme), et, si tu te connectes avec Discord,
           pour le catalogue partagé et les salons en ligne.</p>
        <p>Dans ce cas, le serveur conserve ton identifiant Discord, ton pseudo, l'adresse de ton avatar,
           tes sessions et les fichiers que tu déposes. Le détail complet est dans la
           <a href="/confidentialite">politique de confidentialité</a>.</p>
      </div>
    </details>
    <details>
      <summary>Quelque chose ne marche pas : que faire ?</summary>
      <div class="faq__body">
        <p>Si le jeu ne reçoit pas les touches, vérifie qu'Heartopia est bien la fenêtre active, puis relance
           DodoTopia en administrateur. Si les notes sont fausses, vérifie que l'instrument choisi dans
           DodoTopia est celui ouvert dans le jeu. Si un dessin est décalé, refais la configuration de la zone
           du jeu pour ce format. Si la bulle de la cuisinière n'est pas reconnue, lance le test de détection
           devant elle, puis recapture ses icônes.</p>
        <p>Pour signaler un problème, écris à {EDITEUR_COURRIEL} en décrivant ce que tu faisais, ce qui s'est
           passé et ta version de l'application. Joins les journaux : ils se trouvent dans le dossier
           <code>%APPDATA%\\DodoTopia</code> sous les noms <code>dessin.log</code>, <code>cuisine.log</code> et
           <code>multi.log</code>, et s'ouvrent depuis Réglages › À propos et mises à jour.</p>
        <p>Pour un contenu déposé dans le catalogue partagé, le plus simple est le bouton de signalement
           prévu dans l'application ; sinon, la même adresse de contact convient.</p>
      </div>
    </details>
  </div>
</div></section>

<section class="section section--tight"><div class="wrap">
  <div class="notice">
    <p><strong>Projet indépendant.</strong> DodoTopia n'est ni développé, ni soutenu, ni validé par les
       éditeurs d'Heartopia. L'utilisation d'un outil d'automatisation peut être contraire aux conditions
       d'utilisation du jeu : chacun l'utilise à ses propres risques.</p>
  </div>
</div></section>
"""
    return page(settings, "/", title, description, body, version_line, json_ld(settings, latest))


# --- Pages légales -------------------------------------------------------------------

def render_mentions(settings) -> str:
    body = f"""<section class="section"><div class="wrap"><article class="doc">
  <h1>Mentions légales</h1>
  <p class="updated">Dernière mise à jour : {LAST_UPDATE}</p>

  <h2>Éditeur du site et de l'application</h2>
  <p>Le site <strong>dodotopia.cyber-dodo.fr</strong> et l'application DodoTopia sont édités par :</p>
  <ul>
    <li>Nom ou raison sociale : {EDITEUR_NOM}, sous le nom commercial {EDITEUR_MARQUE}</li>
    <li>Statut : {EDITEUR_STATUT}</li>
    <li>Immatriculation : SIRET {EDITEUR_SIRET}</li>
    <li>TVA : {EDITEUR_TVA}</li>
    <li>Adresse : {EDITEUR_ADRESSE}</li>
    <li>Courriel : {EDITEUR_COURRIEL}</li>
    <li>Téléphone : {EDITEUR_TEL}</li>
  </ul>

  <h2>Directeur de la publication</h2>
  <p>{EDITEUR_NOM}</p>

  <h2>Hébergeur</h2>
  <p>Le site et le serveur de DodoTopia sont hébergés par :</p>
  <ul>
    <li>Raison sociale : {HEBERGEUR_NOM}</li>
    <li>Adresse : {HEBERGEUR_ADRESSE}</li>
    <li>Immatriculation et contact : {HEBERGEUR_CONTACT}</li>
    <li>Pays d'hébergement des serveurs : {HEBERGEUR_PAYS}</li>
  </ul>

  <h2>Contact</h2>
  <p>Pour toute question sur le site, l'application, une anomalie technique ou un contenu publié dans la
     bibliothèque partagée, écrivez à l'adresse suivante :</p>
  <p>{EDITEUR_COURRIEL}</p>

  <h2>Propriété intellectuelle</h2>
  <p>L'application DodoTopia, son code source, ses éléments graphiques et sa documentation sont la propriété de
     l'éditeur et sont protégés par le droit d'auteur. Le code source n'est pas public.
     L'application est mise à disposition pour un {LICENCE}</p>
  <p>Les textes, la mise en page, la charte graphique et le logo de ce site (le dodo turquoise) sont la
     propriété de l'éditeur. Toute reproduction, même partielle, nécessite son accord préalable.</p>
  <p>Les contenus déposés par les utilisateurs dans la bibliothèque partagée (fichiers MIDI, titres, noms
     d'artistes) restent la propriété de leurs auteurs respectifs. En les déposant, l'utilisateur accorde
     seulement le droit de les stocker et de les mettre à disposition des autres utilisateurs du service,
     et garantit disposer des droits nécessaires pour le faire.</p>

  <h2>Marques de tiers</h2>
  <p><strong>Heartopia</strong> et l'ensemble des noms, logos, images et marques cités sur ce site
     appartiennent à leurs propriétaires respectifs. DodoTopia est un projet indépendant, développé par des
     joueurs, <strong>sans aucun lien, partenariat, sponsoring ni validation</strong> des éditeurs d'Heartopia.
     Ces marques ne sont citées qu'à titre descriptif, pour indiquer avec quel jeu l'application est
     compatible.</p>
  <p>Si un ayant droit estime qu'un élément de ce site porte atteinte à ses droits, il peut en demander le
     retrait à l'adresse indiquée ci-dessus : la demande sera traitée dans les meilleurs délais.</p>

  <h2>Responsabilité</h2>
  <p>DodoTopia est un outil d'automatisation non officiel. Son utilisation peut être contraire aux conditions
     d'utilisation du jeu Heartopia ; l'éditeur du jeu demeure libre des mesures qu'il applique aux comptes de
     ses joueurs. L'éditeur de DodoTopia ne peut être tenu responsable des conséquences de l'utilisation de
     l'application sur un compte de jeu. Voir les <a href="/conditions">conditions d'utilisation</a>.</p>
</article></div></section>
"""
    return page(settings, "/mentions-legales", "Mentions légales — DodoTopia",
                "Éditeur, directeur de la publication, hébergeur, contact, propriété intellectuelle et "
                "marques citées par le site et l'application DodoTopia.", body)


def render_privacy(settings) -> str:
    days = esc(settings.SESSION_DAYS)
    body = f"""<section class="section"><div class="wrap"><article class="doc">
  <h1>Politique de confidentialité</h1>
  <p class="updated">Dernière mise à jour : {LAST_UPDATE}</p>

  <p>Cette page décrit exactement les données personnelles traitées par le service DodoTopia
     (site <strong>dodotopia.cyber-dodo.fr</strong> et serveur associé), pourquoi elles le sont, combien de
     temps elles sont conservées, et comment exercer vos droits. Elle décrit le fonctionnement réel du service,
     champ de base de données par champ de base de données.</p>

  <h2>1. Responsable du traitement</h2>
  <ul>
    <li>Responsable : {EDITEUR_NOM} ({EDITEUR_MARQUE})</li>
    <li>Adresse : {EDITEUR_ADRESSE}</li>
    <li>Contact : {EDITEUR_COURRIEL}</li>
  </ul>

  <h2>2. L'essentiel en trois phrases</h2>
  <ul>
    <li>L'application installée sur votre ordinateur fonctionne <strong>hors ligne</strong> : vos fichiers MIDI,
        vos images, vos réglages, vos calibrages et vos journaux ne quittent jamais votre machine.</li>
    <li>Le serveur ne traite de données personnelles que si vous <strong>vous connectez avec Discord</strong>,
        pour la bibliothèque partagée et les salons en ligne.</li>
    <li>Aucune donnée n'est vendue, louée, cédée à un tiers, ni utilisée à des fins publicitaires ou de
        profilage. Il n'y a <strong>aucun cookie de suivi</strong> et aucun outil de mesure d'audience.</li>
  </ul>

  <h2>3. Données traitées, finalité et base légale</h2>
  <div class="table-scroll">
  <table>
    <colgroup><col class="c-what"><col class="c-why"><col class="c-law"><col class="c-keep"></colgroup>
    <thead><tr><th>Donnée</th><th>Pourquoi</th><th>Base légale</th><th>Conservation</th></tr></thead>
    <tbody>
      <tr>
        <td data-label="Donnée"><strong>Identifiant Discord</strong> (numéro de compte), <strong>pseudo affiché</strong> et
            <strong>adresse de l'image d'avatar</strong> (une URL vers les serveurs de Discord)</td>
        <td data-label="Pourquoi">Vous identifier de façon stable, afficher qui a déposé un morceau et qui est présent dans un salon,
            appliquer les droits d'administration et les bannissements</td>
        <td data-label="Base légale">Exécution du service demandé (contrat)</td>
        <td data-label="Conservation">Tant que le compte existe ; supprimé sur demande</td>
      </tr>
      <tr>
        <td data-label="Donnée"><strong>Sessions</strong> : empreinte du jeton de connexion (le jeton lui-même n'est jamais
            enregistré, seulement son condensé SHA-256), date de création, date d'expiration, date de dernier
            usage</td>
        <td data-label="Pourquoi">Vous garder connecté d'une session à l'autre sans redemander Discord, et pouvoir révoquer un accès</td>
        <td data-label="Base légale">Exécution du service demandé (contrat)</td>
        <td data-label="Conservation"><strong>{days} jours</strong> glissants ; les sessions expirées sont effacées automatiquement
            par le nettoyage périodique du serveur</td>
      </tr>
      <tr>
        <td data-label="Donnée"><strong>Tickets de connexion</strong> temporaires (identifiant aléatoire, empreinte d'un vérifieur,
            état OAuth)</td>
        <td data-label="Pourquoi">Relier en toute sécurité la fenêtre du navigateur qui se connecte à Discord et l'application qui
            attend le résultat</td>
        <td data-label="Base légale">Sécurité du service (intérêt légitime)</td>
        <td data-label="Conservation">Quelques minutes ; effacés automatiquement après expiration</td>
      </tr>
      <tr>
        <td data-label="Donnée"><strong>Fichiers MIDI déposés</strong> dans la bibliothèque partagée, avec leur titre, l'artiste,
            le nom d'origine du fichier, sa taille, sa durée, son nombre de notes, son empreinte SHA-256,
            <strong>le compte qui l'a déposé</strong>, son état de modération, le motif d'un éventuel refus,
            le compte modérateur, la date d'examen et le nombre de téléchargements</td>
        <td data-label="Pourquoi">Mettre les morceaux à disposition des autres utilisateurs, permettre la modération et le retrait
            d'un contenu illicite</td>
        <td data-label="Base légale">Exécution du service demandé (contrat) et intérêt légitime pour la modération</td>
        <td data-label="Conservation">Tant que le morceau est en ligne ; supprimé par son auteur, par un modérateur ou sur demande</td>
      </tr>
      <tr>
        <td data-label="Donnée"><strong>Signalements</strong> : morceau visé, <strong>compte qui signale</strong>, motif écrit,
            date, et la suite donnée (date, modérateur, décision)</td>
        <td data-label="Pourquoi">Traiter les signalements de contenus illicites ou inappropriés et garder une trace des décisions</td>
        <td data-label="Base légale">Intérêt légitime (sécurité et légalité des contenus publiés)</td>
        <td data-label="Conservation">Jusqu'au traitement du signalement, puis une durée raisonnable pour prévenir les abus répétés</td>
      </tr>
      <tr>
        <td data-label="Donnée"><strong>Vérification de mise à jour</strong> : l'application interroge ce serveur en lui
            transmettant la <strong>version installée</strong> et la <strong>plateforme</strong>
            (Windows ou Linux)</td>
        <td data-label="Pourquoi">Savoir s'il existe une version plus récente et vous proposer le bon fichier</td>
        <td data-label="Base légale">Intérêt légitime (maintenir les installations à jour et sécurisées)</td>
        <td data-label="Conservation">Non conservée : la requête n'est pas enregistrée dans la base</td>
      </tr>
      <tr>
        <td data-label="Donnée"><strong>Adresse IP</strong>, présente dans les journaux techniques du serveur et de l'hébergeur, et
            utilisée en mémoire vive pour la limitation de débit</td>
        <td data-label="Pourquoi">Faire fonctionner la connexion réseau, empêcher les abus et les attaques par saturation</td>
        <td data-label="Base légale">Intérêt légitime (sécurité du service)</td>
        <td data-label="Conservation">Durée courte, conforme aux réglages de l'hébergeur ; les compteurs de limitation en mémoire sont
            oubliés au bout d'une heure d'inactivité et à chaque redémarrage</td>
      </tr>
    </tbody>
  </table>
  </div>

  <h2>4. Salons en ligne : rien n'est enregistré</h2>
  <p>Les salons synchronisés vivent <strong>uniquement en mémoire vive</strong> du serveur. Le code du salon,
     le pseudo affiché, l'instrument choisi, l'état de la partie et le morceau éphémère partagé pour la session
     ne sont écrits dans aucune base de données : ils disparaissent quand le salon se vide ou quand le serveur
     redémarre. Le fichier partagé dans un salon est stocké dans un dossier temporaire et supprimé
     automatiquement quelques heures après son dépôt.</p>

  <h2>5. Ce qui n'est pas collecté</h2>
  <ul>
    <li>Aucun contenu de votre écran, aucune capture d'écran, aucune frappe clavier : tout cela est analysé
        localement par l'application et n'est jamais transmis.</li>
    <li>Aucune adresse de courriel : la connexion Discord utilise la portée <code>identify</code>, qui ne donne
        accès ni à votre adresse de courriel, ni à vos serveurs, ni à vos messages.</li>
    <li>Aucun mot de passe : le service n'en crée aucun, et votre mot de passe Discord n'est jamais vu par
        DodoTopia.</li>
    <li>Aucun cookie publicitaire, aucun traceur tiers, aucun outil de mesure d'audience, aucune police ni
        aucun script chargé depuis un service externe : ce site ne charge que ses propres fichiers.</li>
  </ul>

  <h2>6. Destinataires</h2>
  <p>Les données ne sont accessibles qu'à l'éditeur et aux comptes d'administration désignés, pour les seuls
     besoins de la modération. Elles ne sont ni vendues, ni louées, ni cédées. Les seuls tiers techniques
     impliqués sont :</p>
  <ul>
    <li><strong>Discord</strong>, pour l'authentification : lorsque vous vous connectez, votre navigateur
        échange avec Discord selon
        <a href="https://discord.com/privacy" rel="noopener external nofollow">sa propre politique de
        confidentialité</a>. Les images d'avatar sont servies par les serveurs de Discord.</li>
    <li><strong>l'hébergeur</strong> du serveur : {HEBERGEUR_NOM}, dont les serveurs se
        situent en {HEBERGEUR_PAYS}.</li>
  </ul>

  <h2>7. Sécurité</h2>
  <p>Les échanges avec le serveur passent par HTTPS. Les jetons de session ne sont jamais stockés en clair :
     seule leur empreinte SHA-256 est conservée, ce qui rend le contenu de la base inutilisable pour se
     connecter à votre place. Les fichiers déposés sont analysés et plafonnés avant d'être acceptés. Les
     sessions d'un compte banni sont immédiatement supprimées.</p>

  <h2>8. Vos droits</h2>
  <p>Conformément au Règlement général sur la protection des données (RGPD) et à la loi « Informatique et
     Libertés », vous disposez des droits suivants sur vos données : <strong>accès</strong> (obtenir une copie
     des données vous concernant), <strong>rectification</strong> (corriger une donnée inexacte),
     <strong>effacement</strong>, <strong>limitation</strong> du traitement, <strong>opposition</strong> pour
     motif légitime, et <strong>portabilité</strong> des données que vous avez fournies.</p>
  <p>En pratique :</p>
  <ul>
    <li>vous pouvez supprimer vous-même, à tout moment et depuis l'application, les morceaux que vous avez
        déposés ;</li>
    <li>la déconnexion supprime immédiatement la session correspondante ;</li>
    <li>pour toute autre demande — copie de vos données, suppression complète de votre compte et des contenus
        associés — écrivez à
        {EDITEUR_COURRIEL} en précisant votre
        pseudo Discord. Une réponse vous sera apportée dans un délai maximal d'un mois.</li>
  </ul>
  <p>Si vous estimez, après nous avoir contactés, que vos droits ne sont pas respectés, vous pouvez introduire
     une réclamation auprès de l'autorité de contrôle compétente, en France la
     <a href="https://www.cnil.fr" rel="noopener external nofollow">CNIL</a>.</p>

  <h2>9. Enfants</h2>
  <p>La connexion passe par Discord, dont les conditions imposent un âge minimum. Le service n'est pas destiné
     aux enfants en dessous de cet âge et ne collecte sciemment aucune donnée les concernant.</p>

  <h2>10. Modifications</h2>
  <p>Cette politique peut évoluer si le service change. La date de dernière mise à jour figure en haut de la
     page ; en cas de modification substantielle, l'information sera relayée dans l'application.</p>
</article></div></section>
"""
    return page(settings, "/confidentialite", "Politique de confidentialité — DodoTopia",
                "Quelles données DodoTopia traite réellement : compte Discord, sessions, fichiers déposés, "
                "signalements. Finalités, bases légales, durées de conservation et droits RGPD.", body)


def render_terms(settings) -> str:
    body = f"""<section class="section"><div class="wrap"><article class="doc">
  <h1>Conditions d'utilisation</h1>
  <p class="updated">Dernière mise à jour : {LAST_UPDATE}</p>

  <p>Les présentes conditions régissent l'utilisation du site <strong>dodotopia.cyber-dodo.fr</strong>, du
     serveur DodoTopia (bibliothèque partagée, salons en ligne, mises à jour) et de l'application DodoTopia.
     Utiliser le service vaut acceptation de ces conditions. Si vous ne les acceptez pas, n'utilisez pas le
     service.</p>

  <h2>1. Description du service</h2>
  <p>DodoTopia est une application gratuite destinée à automatiser certaines actions répétitives
     dans le jeu Heartopia : jouer un fichier MIDI sur un instrument du jeu, reproduire une image dans l'outil
     de dessin, refaire une recette de cuisine en boucle. Le serveur fournit en complément : la distribution des
     mises à jour, une bibliothèque de fichiers MIDI partagée entre utilisateurs, et des salons permettant de
     jouer à plusieurs de façon synchronisée.</p>
  <p>Le service est fourni gratuitement, sans engagement de disponibilité. L'éditeur peut le modifier,
     l'interrompre temporairement ou définitivement, en tout ou partie, sans préavis.</p>

  <h2>2. Outil non officiel et risques liés au jeu</h2>
  <p>DodoTopia n'est ni développé, ni soutenu, ni approuvé par les éditeurs d'Heartopia. <strong>L'utilisation
     d'un logiciel d'automatisation peut être contraire aux conditions d'utilisation du jeu.</strong> L'éditeur
     du jeu reste seul juge des mesures qu'il applique aux comptes de ses joueurs, y compris la suspension ou la
     suppression d'un compte. <strong>Vous utilisez DodoTopia en connaissance de cause et à vos propres
     risques.</strong></p>

  <h2>3. Compte et accès</h2>
  <p>L'application fonctionne sans compte. Un compte n'est nécessaire que pour la bibliothèque partagée et les
     salons ; il est créé à partir de votre compte Discord. Vous êtes responsable de l'usage fait de votre
     compte et de la confidentialité de l'appareil sur lequel votre session est ouverte. Vous pouvez vous
     déconnecter à tout moment depuis l'application.</p>

  <h2>4. Contenus que vous déposez</h2>
  <p>Vous ne pouvez déposer que des <strong>fichiers MIDI dont vous avez le droit de disposer</strong> :
     vos propres compositions, des œuvres du domaine public, ou des fichiers dont la licence autorise le
     partage. Vous garantissez disposer des droits nécessaires et être en mesure de le justifier.</p>
  <p>En déposant un fichier, vous autorisez le service à le stocker, le convertir techniquement si nécessaire,
     l'afficher et le mettre à disposition des autres utilisateurs, à titre gratuit et pour la durée de sa mise
     en ligne. Vous conservez tous vos droits sur le fichier et pouvez le retirer à tout moment.</p>
  <p>Il est interdit de déposer ou de diffuser via le service, notamment :</p>
  <ul>
    <li>un contenu portant atteinte au droit d'auteur, au droit des marques ou à tout autre droit de tiers ;</li>
    <li>un contenu illicite, haineux, injurieux, diffamatoire, violent, pornographique, ou portant atteinte à la
        dignité des personnes ;</li>
    <li>un contenu mettant en danger des mineurs ;</li>
    <li>un fichier volontairement malformé ou destiné à saturer, dégrader ou contourner les protections du
        service ;</li>
    <li>un titre, un nom d'artiste ou un pseudo trompeur, publicitaire, ou conçu pour usurper l'identité d'un
        tiers.</li>
  </ul>
  <p>Vous vous engagez également à ne pas automatiser d'appels au serveur au-delà de l'usage normal de
     l'application, à ne pas tenter d'accéder aux comptes d'autres utilisateurs, ni aux fonctions
     d'administration.</p>

  <h2>5. Modération et retrait</h2>
  <p>Les fichiers déposés sont soumis à modération avant d'être visibles par les autres utilisateurs. Tout
     utilisateur peut signaler un contenu depuis l'application, en indiquant un motif. L'éditeur peut refuser,
     masquer ou supprimer sans préavis tout contenu contraire aux présentes conditions ou à la loi, et
     conserver la trace de la décision.</p>
  <p>Pour signaler un contenu en dehors de l'application, ou pour toute demande de retrait fondée sur un droit
     d'auteur, écrivez à {EDITEUR_COURRIEL} en précisant le morceau concerné,
     le motif et, pour une demande de retrait, les éléments justifiant vos droits.</p>

  <h2>6. Suspension et suppression de compte</h2>
  <p>En cas de manquement grave ou répété aux présentes conditions, l'éditeur peut suspendre ou supprimer un
     compte. Dans ce cas, les sessions ouvertes sont immédiatement révoquées et les contenus déposés par ce
     compte sont retirés de la bibliothèque. Vous pouvez de votre côté demander la suppression de votre compte
     à tout moment (voir la <a href="/confidentialite">politique de confidentialité</a>).</p>

  <h2>7. Absence de garantie</h2>
  <p>Le service et l'application sont fournis « en l'état », sans garantie d'aucune sorte, expresse ou
     implicite : ni garantie de disponibilité, ni d'absence d'erreur, ni d'adéquation à un usage particulier,
     ni de compatibilité avec une version donnée du jeu, qui peut changer à tout moment et rendre l'outil
     inopérant. Les données stockées sur le serveur peuvent être perdues : conservez une copie de vos fichiers
     sur votre ordinateur.</p>

  <h2>8. Limitation de responsabilité</h2>
  <p>Dans la limite permise par la loi, l'éditeur ne pourra être tenu responsable des dommages indirects
     résultant de l'utilisation ou de l'impossibilité d'utiliser le service, notamment : sanction, suspension ou
     perte d'un compte de jeu, perte de données ou de progression dans le jeu, perte de temps, ou dommage causé
     par un contenu déposé par un autre utilisateur. Les dispositions légales impératives protégeant les
     consommateurs restent applicables.</p>

  <h2>9. Contenus des tiers</h2>
  <p>La connexion au service passe par Discord, service tiers soumis à ses propres conditions. L'éditeur n'a
     aucun contrôle sur ce service ni sur les autres sites tiers vers lesquels un lien pourrait renvoyer, et
     décline toute responsabilité quant à leur contenu et à leurs pratiques.</p>

  <h2>10. Modification des conditions</h2>
  <p>Ces conditions peuvent être modifiées à tout moment. La version en vigueur est celle publiée sur cette
     page, dont la date de mise à jour figure en haut. Continuer à utiliser le service après une modification
     vaut acceptation de la nouvelle version.</p>

  <h2>11. Droit applicable et juridiction</h2>
  <p>Les présentes conditions sont soumises au droit
     {DROIT}. En cas de litige, et à
     défaut de résolution amiable, compétence est attribuée aux tribunaux
     {DROIT}s, sous
     réserve des règles impératives applicables aux consommateurs.</p>
</article></div></section>
"""
    return page(settings, "/conditions", "Conditions d'utilisation — DodoTopia",
                "Règles d'usage du service DodoTopia : contenus autorisés dans la bibliothèque partagée, "
                "modération, suspension de compte, garanties et responsabilité.", body)


# --- Routes ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return HTMLResponse(_cached_home(request), headers={"Cache-Control": PAGE_CACHE})


@router.get("/instruments", response_class=HTMLResponse)
def instruments(request: Request):
    # Page statique (elle ne depend que des fichiers du catalogue) : cache long, comme les pages legales.
    return HTMLResponse(render_instruments(request.app.state.settings), headers={"Cache-Control": DOC_CACHE})


@router.get("/mentions-legales", response_class=HTMLResponse)
def mentions(request: Request):
    return HTMLResponse(render_mentions(request.app.state.settings), headers={"Cache-Control": DOC_CACHE})


@router.get("/confidentialite", response_class=HTMLResponse)
def confidentialite(request: Request):
    return HTMLResponse(render_privacy(request.app.state.settings), headers={"Cache-Control": DOC_CACHE})


@router.get("/conditions", response_class=HTMLResponse)
def conditions(request: Request):
    return HTMLResponse(render_terms(request.app.state.settings), headers={"Cache-Control": DOC_CACHE})


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    base = request.app.state.settings.public_url
    txt = ("User-agent: *\n"
           "Allow: /\n"
           "Disallow: /api/\n"
           "Disallow: /auth/\n"
           f"\nSitemap: {base}/sitemap.xml\n")
    return PlainTextResponse(txt, headers={"Cache-Control": DOC_CACHE})


@router.get("/sitemap.xml")
def sitemap(request: Request):
    base = request.app.state.settings.public_url
    urls = ""
    for path in PAGES:
        freq, prio = SITEMAP_HINTS.get(path, SITEMAP_DEFAULT)
        urls += (f"  <url><loc>{esc(base + path)}</loc>"
                 f"<changefreq>{freq}</changefreq><priority>{prio}</priority></url>\n")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{urls}</urlset>\n")
    return Response(xml, media_type="application/xml", headers={"Cache-Control": DOC_CACHE})


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon",
                        headers={"Cache-Control": "public, max-age=604800"})


# --- Middleware d'en-têtes ------------------------------------------------------------

class SecurityHeadersMiddleware:
    """`X-Content-Type-Options: nosniff` partout, cache long sur /static (ASGI pur : ne touche pas au corps)."""

    STATIC_CACHE = "public, max-age=86400"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_static = scope.get("path", "").startswith("/static/")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                names = {k.lower() for k, _ in headers}
                if b"x-content-type-options" not in names:
                    headers.append((b"x-content-type-options", b"nosniff"))
                if is_static and b"cache-control" not in names:
                    headers.append((b"cache-control", self.STATIC_CACHE.encode()))
            await send(message)

        return await self.app(scope, receive, send_wrapper)
