"""Site public (vitrine + pages légales), rendu en HTML par de simples f-strings.

Aucun framework front, aucune ressource externe : la feuille de style, les polices, le logo et la favicon
sont servis depuis `server/static` par `StaticFiles` (monté dans `main.py`). Toute donnée dynamique passe
par `esc()` (= `html.escape`) avant d'entrer dans le gabarit.

La page d'accueil interroge la base (dernière version publiée) : le HTML rendu est gardé en cache sur
`app.state` pendant `HOME_TTL_S`, et `invalidate(app)` le jette dès qu'une version est publiée ou supprimée.
"""
from __future__ import annotations

import json
import mimetypes
import time
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from . import db, releases
from .config import SERVER_VERSION

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

PAGES = {
    "/": ("Accueil", "DodoTopia — jouer vos MIDI, dessiner et cuisiner dans Heartopia"),
    "/mentions-legales": ("Mentions légales", "Mentions légales"),
    "/confidentialite": ("Confidentialité", "Politique de confidentialité"),
    "/conditions": ("Conditions", "Conditions d'utilisation"),
}


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
    <a href="/#telecharger">Télécharger</a>
    <a href="/#questions">Questions fréquentes</a>
  </nav>
</div></header>
<main id="contenu">
"""


def foot(version_line: str) -> str:
    return f"""</main>
<footer class="site-footer"><div class="wrap">
  <ul class="footer-nav">
    <li><a href="/">Accueil</a></li>
    <li><a href="/mentions-legales">Mentions légales</a></li>
    <li><a href="/confidentialite">Confidentialité</a></li>
    <li><a href="/conditions">Conditions d'utilisation</a></li>
  </ul>
  <p>Contact : {todo("adresse de contact")}</p>
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

SVG_MUSIC = """<svg viewBox="0 0 320 150" role="img" aria-label="Une portée avec des notes de musique">
  <rect width="320" height="150" rx="18" fill="#dff6f4"/>
  <g stroke="#9ec9c6" stroke-width="2" stroke-linecap="round">
    <path d="M28 46h264M28 66h264M28 86h264M28 106h264"/>
  </g>
  <g fill="#e8a531">
    <circle cx="74" cy="106" r="13"/><rect x="84" y="46" width="5" height="62" rx="2.5"/>
    <circle cx="134" cy="86" r="13"/><rect x="144" y="26" width="5" height="62" rx="2.5"/>
    <circle cx="200" cy="96" r="13"/><rect x="210" y="36" width="5" height="62" rx="2.5"/>
    <path d="M84 46h66v12H84z" rx="3"/>
    <path d="M210 36c14 4 22 10 26 20V38c-4-8-12-13-26-16z"/>
  </g>
  <g fill="#46cbc4">
    <circle cx="258" cy="76" r="13"/><rect x="268" y="16" width="5" height="62" rx="2.5"/>
    <path d="M268 16c16 5 25 12 29 24V22c-5-9-14-15-29-19z"/>
  </g>
</svg>"""

SVG_IMAGE = """<svg viewBox="0 0 320 150" role="img" aria-label="Une grille de cases colorées, comme un dessin pixel par pixel">
  <rect width="320" height="150" rx="18" fill="#fbf5ea"/>
  <g>
    <rect x="30" y="24" width="22" height="22" rx="5" fill="#46cbc4"/>
    <rect x="56" y="24" width="22" height="22" rx="5" fill="#46cbc4"/>
    <rect x="82" y="24" width="22" height="22" rx="5" fill="#e8a531"/>
    <rect x="108" y="24" width="22" height="22" rx="5" fill="#e8a531"/>
    <rect x="134" y="24" width="22" height="22" rx="5" fill="#f2dcb3"/>
    <rect x="30" y="50" width="22" height="22" rx="5" fill="#46cbc4"/>
    <rect x="56" y="50" width="22" height="22" rx="5" fill="#e8a531"/>
    <rect x="82" y="50" width="22" height="22" rx="5" fill="#f28b8b"/>
    <rect x="108" y="50" width="22" height="22" rx="5" fill="#f28b8b"/>
    <rect x="134" y="50" width="22" height="22" rx="5" fill="#e8a531"/>
    <rect x="30" y="76" width="22" height="22" rx="5" fill="#9fb356"/>
    <rect x="56" y="76" width="22" height="22" rx="5" fill="#f28b8b"/>
    <rect x="82" y="76" width="22" height="22" rx="5" fill="#f28b8b"/>
    <rect x="108" y="76" width="22" height="22" rx="5" fill="#f2dcb3"/>
    <rect x="134" y="76" width="22" height="22" rx="5" fill="#9fb356"/>
    <rect x="30" y="102" width="22" height="22" rx="5" fill="#9fb356"/>
    <rect x="56" y="102" width="22" height="22" rx="5" fill="#9fb356"/>
    <rect x="82" y="102" width="22" height="22" rx="5" fill="#e4d4ba"/>
    <rect x="108" y="102" width="22" height="22" rx="5" fill="#e4d4ba"/>
    <rect x="134" y="102" width="22" height="22" rx="5" fill="#9fb356"/>
  </g>
  <g fill="none" stroke="#e4d4ba" stroke-width="2" stroke-dasharray="5 6">
    <path d="M176 28h116M176 62h116M176 96h116"/>
  </g>
  <g fill="#b56f3f">
    <path d="M232 118l52-52a12 12 0 0 1 17 17l-52 52-22 5z"/>
    <path d="M227 140l5-22 17 17z" fill="#6b5a52"/>
  </g>
</svg>"""

SVG_COOK = """<svg viewBox="0 0 320 150" role="img" aria-label="Une marmite sur le feu avec de la vapeur">
  <rect width="320" height="150" rx="18" fill="#eef2da"/>
  <g stroke="#9fb356" stroke-width="7" stroke-linecap="round" fill="none" opacity=".85">
    <path d="M136 42c0-10 12-10 12-20s-12-10-12-20"/>
    <path d="M166 38c0-11 13-11 13-22s-13-11-13-22"/>
    <path d="M196 42c0-10 12-10 12-20s-12-10-12-20"/>
  </g>
  <rect x="96" y="56" width="152" height="16" rx="8" fill="#c98644"/>
  <path d="M104 70h136l-12 54a14 14 0 0 1-14 12h-84a14 14 0 0 1-14-12z" fill="#e8a531"/>
  <path d="M120 84h104l-8 38h-88z" fill="#fbe7bd" opacity=".55"/>
  <path d="M84 62c-14 0-14 22 0 22h14V62z" fill="#c98644"/>
  <path d="M260 62c14 0 14 22 0 22h-14V62z" fill="#c98644"/>
  <g fill="#f28b8b">
    <path d="M130 140c0-8 8-10 8-18 6 5 8 11 8 18z"/>
    <path d="M168 140c0-8 8-10 8-18 6 5 8 11 8 18z"/>
    <path d="M206 140c0-8 8-10 8-18 6 5 8 11 8 18z"/>
  </g>
</svg>"""


# --- Accueil -------------------------------------------------------------------------

def latest_release(settings) -> dict | None:
    conn = db.connect(settings)
    try:
        versions = releases.published_versions(conn)
        return releases.manifest(conn, settings, versions[0]) if versions else None
    finally:
        conn.close()


def download_block(latest: dict | None) -> tuple[str, str]:
    """(HTML de la zone de téléchargement, ligne de version pour le pied de page)."""
    if not latest:
        html = """<div class="soon">
    <h2>Bientôt disponible</h2>
    <p>Aucune version n'est publiée pour l'instant. La première version téléchargeable arrive bientôt :
       revenez d'ici quelques jours, cette page proposera alors l'installeur Windows et l'archive Linux.</p>
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
        notes.append(f'Pas envie d\'installer ? <a href="{esc(dl_path(latest["version"], por["filename"]))}" '
                     f'download>Version portable pour Windows</a> ({esc(human_size(por["size"]))}), '
                     "à dézipper où vous voulez.")
    if not lin:
        notes.append("La version Linux n'est pas disponible pour cette publication.")
    notes.append(f"Version {version}{f' · publiée le {date}' if date else ''} · gratuit, sans compte obligatoire.")

    release_notes = ""
    raw_notes = (latest.get("notes") or "").strip()
    if raw_notes:
        body = "".join(f"<li>{esc(line.strip(' -•\t'))}</li>"
                       for line in raw_notes.splitlines()[:6] if line.strip())
        if body:
            release_notes = f'<div class="dl-note"><strong>Nouveautés :</strong><ul>{body}</ul></div>'

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
    downloads, version_line = download_block(latest)
    title = "DodoTopia — jouer vos MIDI, dessiner et cuisiner dans Heartopia"
    description = ("DodoTopia est une application gratuite qui joue vos fichiers MIDI, peint vos images et "
                   "refait vos recettes dans Heartopia, à votre place. Windows et Linux.")
    body = f"""<section class="section hero" id="telecharger"><div class="wrap"><div class="hero__grid">
  <div>
    <p class="eyebrow">Compagnon gratuit pour Heartopia</p>
    <h1>Votre dodo joue, dessine et cuisine à votre place</h1>
    <p class="lead">DodoTopia est une application gratuite qui joue vos fichiers MIDI sur les instruments
      d'Heartopia, transforme vos images en dessins case par case et refait vos recettes en boucle.</p>
    {downloads}
  </div>
  <div class="hero__art">
    <img src="/static/logo.png" width="300" height="300" alt="" aria-hidden="true">
  </div>
</div></div></section>

<section class="section"><div class="wrap">
  <h2>Trois outils, trois onglets</h2>
  <div class="cards">
    <article class="card">
      {SVG_MUSIC}
      <h3>Musique</h3>
      <p>Importez vos fichiers <code>.mid</code> : DodoTopia appuie sur les touches de l'instrument du jeu
         à votre place, au piano, à la flûte ou au luth.</p>
      <ul>
        <li>Écoute dans le logiciel avant de jouer dans le jeu</li>
        <li>Transposition automatique selon l'instrument</li>
        <li>Salons en ligne pour jouer à plusieurs, tous synchronisés sur le même top départ</li>
      </ul>
    </article>
    <article class="card">
      {SVG_IMAGE}
      <h3>Image</h3>
      <p>Choisissez une photo ou un dessin : DodoTopia le convertit sur les 126 nuances de la palette du jeu,
         puis le peint case par case dans l'outil de dessin.</p>
      <ul>
        <li>Aperçu fidèle avant de lancer, formats 16:9 à 9:16</li>
        <li>Contours au crayon puis remplissage au pot de peinture</li>
        <li>Relecture de l'écran et reprise des cases manquées</li>
      </ul>
    </article>
    <article class="card">
      {SVG_COOK}
      <h3>Cuisine</h3>
      <p>Placez-vous devant la cuisinière : DodoTopia refait la dernière recette en boucle, ajuste le feu
         au bon moment et récupère les plats.</p>
      <ul>
        <li>Jusqu'à quatre cuisinières enchaînées</li>
        <li>Nombre de plats réglable, ou boucle sans fin</li>
        <li>Arrêt immédiat dès que vous touchez au clavier ou à la souris</li>
      </ul>
    </article>
  </div>
</div></section>

<section class="section"><div class="wrap">
  <h2>Comment ça marche</h2>
  <div class="steps">
    <div class="step">
      <div class="step__num" aria-hidden="true">1</div>
      <h3>Installez DodoTopia</h3>
      <p>Téléchargez l'installeur Windows ou l'archive Linux, puis lancez l'application à côté du jeu.
         Vos musiques et vos réglages restent sur votre ordinateur.</p>
    </div>
    <div class="step">
      <div class="step__num" aria-hidden="true">2</div>
      <h3>Préparez l'onglet voulu</h3>
      <p>Importez vos fichiers MIDI ou votre image, choisissez l'instrument ou le format, et suivez
         l'assistant de calibrage une seule fois pour le dessin et la cuisine.</p>
    </div>
    <div class="step">
      <div class="step__num" aria-hidden="true">3</div>
      <h3>Appuyez sur F6 dans le jeu</h3>
      <p>DodoTopia joue, dessine ou cuisine à votre place. <kbd>F7</kbd>, une touche ou un clic
         arrêtent tout immédiatement et vous rendent la main.</p>
    </div>
  </div>
</div></section>

<section class="section" id="questions"><div class="wrap">
  <h2>Questions fréquentes</h2>
  <div class="faq">
    <details>
      <summary>Est-ce que c'est gratuit ?</summary>
      <div class="faq__body">
        <p>Oui, entièrement. DodoTopia est gratuit, sans publicité, sans achat intégré, sans abonnement et
           sans version payante cachée. Un compte Discord n'est demandé que si vous voulez utiliser la
           bibliothèque partagée ou les salons en ligne ; tout le reste — musique, dessin, cuisine —
           fonctionne sans compte et sans connexion.</p>
      </div>
    </details>
    <details>
      <summary>Est-ce que c'est un logiciel espion ?</summary>
      <div class="faq__body">
        <p>Non. Mais soyons francs sur ce que fait l'application, parce que c'est inhabituel : DodoTopia
           <strong>envoie des appuis de touches et des clics de souris</strong> à la fenêtre du jeu, et
           <strong>lit l'image de votre écran</strong>. C'est exactement ce que vous lui demandez de faire :
           on ne peut pas jouer d'un instrument, peindre un dessin case par case ou surveiller une cuisinière
           à votre place sans appuyer sur des touches et sans regarder ce qui s'affiche.</p>
        <p>Ces deux comportements sont aussi ceux d'un enregistreur de frappe : c'est précisément pour cela que
           Windows SmartScreen ou un antivirus peuvent afficher un avertissement au premier lancement. Ce que
           DodoTopia ne fait pas : enregistrer ce que vous tapez ailleurs, fouiller vos autres fenêtres, toucher
           à vos mots de passe, ni envoyer vos captures d'écran où que ce soit — elles sont analysées en mémoire
           sur votre machine puis jetées.</p>
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
        <p>Honnêtement : c'est possible, et nous ne pouvons rien vous garantir. DodoTopia est un
           <strong>outil non officiel</strong>, sans aucun lien avec les éditeurs d'Heartopia. L'usage d'un
           logiciel d'automatisation peut être contraire aux conditions d'utilisation du jeu, et l'éditeur reste
           libre de sanctionner un compte comme il l'entend.</p>
        <p>DodoTopia n'injecte rien dans le jeu, ne modifie aucun fichier du jeu et ne lit pas sa mémoire :
           il se contente d'appuyer sur des touches et de regarder l'écran, comme le ferait une personne très
           rapide. Cela réduit le risque, mais ne l'élimine pas. <strong>Vous l'utilisez à vos propres
           risques.</strong></p>
      </div>
    </details>
    <details>
      <summary>Quelles données sont collectées ?</summary>
      <div class="faq__body">
        <p>Hors ligne, aucune : vos fichiers MIDI, vos images, vos réglages et vos journaux restent sur votre
           ordinateur. L'application contacte ce serveur uniquement pour vérifier s'il existe une mise à jour
           (elle transmet alors la version installée et la plateforme), et, si vous vous connectez avec Discord,
           pour la bibliothèque partagée et les salons en ligne.</p>
        <p>Dans ce cas, le serveur conserve votre identifiant Discord, votre pseudo, l'adresse de votre avatar,
           vos sessions et les fichiers que vous déposez. Le détail complet est dans la
           <a href="/confidentialite">politique de confidentialité</a>.</p>
      </div>
    </details>
    <details>
      <summary>Comment signaler un problème ?</summary>
      <div class="faq__body">
        <p>Écrivez à {todo("adresse de courriel de contact / support")} en décrivant ce que vous faisiez, ce qui
           s'est passé et votre version de l'application. Joignez les journaux : ils se trouvent dans le dossier
           <code>%APPDATA%\\DodoTopia</code> sous les noms <code>dessin.log</code>, <code>cuisine.log</code> et
           <code>multi.log</code>, et se rouvrent depuis les liens en bas de chaque onglet.</p>
        <p>Pour un contenu déposé dans la bibliothèque partagée, le plus simple est le bouton de signalement
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
    <li>Nom ou raison sociale : {todo("nom et prénom, ou raison sociale de l'éditeur")}</li>
    <li>Statut : {todo("statut juridique — particulier, auto-entrepreneur, association loi 1901, SAS…")}</li>
    <li>Numéro d'immatriculation, le cas échéant :
        {todo("SIREN / SIRET / RCS, ou numéro RNA pour une association ; « sans objet » si particulier")}</li>
    <li>Numéro de TVA intracommunautaire, le cas échéant : {todo("numéro de TVA, ou « non assujetti »")}</li>
    <li>Adresse : {todo("adresse postale complète de l'éditeur")}</li>
    <li>Courriel : {todo("adresse de courriel de contact")}</li>
    <li>Téléphone : {todo("numéro de téléphone, ou « sans objet » si l'éditeur est un particulier")}</li>
  </ul>

  <h2>Directeur de la publication</h2>
  <p>{todo("nom et prénom du directeur de la publication (en général l'éditeur lui-même)")}</p>

  <h2>Hébergeur</h2>
  <p>Le site et le serveur de DodoTopia sont hébergés par :</p>
  <ul>
    <li>Raison sociale : {todo("raison sociale de l'hébergeur")}</li>
    <li>Adresse : {todo("adresse postale de l'hébergeur")}</li>
    <li>Téléphone : {todo("numéro de téléphone de l'hébergeur")}</li>
    <li>Pays d'hébergement des serveurs : {todo("pays où sont physiquement hébergées les données")}</li>
  </ul>

  <h2>Contact</h2>
  <p>Pour toute question sur le site, l'application, une anomalie technique ou un contenu publié dans la
     bibliothèque partagée, écrivez à l'adresse suivante :</p>
  <p>{todo("adresse de courriel de contact")}</p>

  <h2>Propriété intellectuelle</h2>
  <p>L'application DodoTopia, son code source, ses éléments graphiques et sa documentation sont la propriété de
     l'éditeur et sont protégés par le droit d'auteur. Le code source n'est pas public.
     {todo("conditions de licence de l'application — par exemple « usage personnel gratuit, sans droit de redistribution, de modification ni de décompilation », ou le nom d'une licence si vous en adoptez une")}</p>
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
    <li>Responsable : {todo("nom et prénom, ou raison sociale du responsable de traitement")}</li>
    <li>Adresse : {todo("adresse postale du responsable de traitement")}</li>
    <li>Contact : {todo("adresse de courriel pour les demandes relatives aux données personnelles")}</li>
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
    <li><strong>l'hébergeur</strong> du serveur : {todo("raison sociale de l'hébergeur")}, dont les serveurs se
        situent en {todo("pays d'hébergement des données")}.</li>
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
        {todo("adresse de courriel pour les demandes relatives aux données personnelles")} en précisant votre
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
     d'auteur, écrivez à {todo("adresse de courriel de contact / modération")} en précisant le morceau concerné,
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
     {todo("droit applicable — par exemple « français », selon le pays de l'éditeur")}. En cas de litige, et à
     défaut de résolution amiable, compétence est attribuée aux tribunaux
     {todo("juridiction compétente — par exemple « français », ou le ressort du siège de l'éditeur")}, sous
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
    urls = "".join(
        f"  <url><loc>{esc(base + path)}</loc>"
        f"<changefreq>{'weekly' if path == '/' else 'yearly'}</changefreq>"
        f"<priority>{'1.0' if path == '/' else '0.4'}</priority></url>\n"
        for path in PAGES
    )
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
