"""Refonte visuelle « Cozy illustré » : garde-fous CSP (aucun style en ligne, SVG sans style), thèmes sur <body>,
captures en WebP, illustrations servies, seuils des compteurs, aperçus de l'accueil, budgets de poids."""
import re

import pytest

from app import db, i18n, site
from app.site_pages import home
from test_public_pages import approved_drawing, approved_song
from test_site import put_and_publish

ART_DIR = site.STATIC_DIR / "art"
INLINE_STYLE = re.compile(r"<[a-zA-Z][^>]*\sstyle\s*=", re.S)


def set_downloads(client, settings, n: int) -> str:
    """Fixe le compteur de téléchargements et renvoie l'accueil fraîchement rendu."""
    conn = db.connect(settings)
    try:
        conn.execute("UPDATE release_assets SET downloads=0")
        conn.execute("UPDATE release_assets SET downloads=? WHERE platform='windows-setup'", (n,))
        conn.commit()
    finally:
        conn.close()
    client.app.state.stats_cache = None
    site.invalidate(client.app)
    return client.get("/fr/").text


# --- Garde-fous CSP ---------------------------------------------------------------------------------------

def test_no_inline_style_anywhere(client, publish_headers, user_token, admin_token):
    """`style-src 'self'` : un attribut `style` ou une balise <style> serait ignoré par le navigateur (et signalé
    en console). Vérifié sur toutes les pages × 2 langues, avec une version, des morceaux et des dessins."""
    put_and_publish(client, publish_headers, "2.0.0", notes="## Titre\n- **point** `code`")
    sids = [approved_song(client, user_token, admin_token, n_notes=60 + i, title=f"Morceau {i}") for i in range(3)]
    # titres de longueurs différentes : `approved_drawing` en tire la couleur du PNG (un doublon serait refusé)
    dids = [approved_drawing(client, user_token, admin_token, title="Dessin " + "x" * i) for i in range(3)]
    site.invalidate(client.app)
    for lang in ("fr", "ja"):
        paths = [site.url_for(lang, page_id) for page_id in site.PAGE_IDS]
        paths += [f"/{lang}/{site.ROUTES['songs'][lang]}/{sids[0]}-morceau-0",
                  f"/{lang}/{site.ROUTES['gallery'][lang]}/{dids[0]}", f"/{lang}/{site.ROOM_SLUGS[lang]}/ABCDEF",
                  f"/{lang}/page-inconnue"]
        for path in paths:
            r = client.get(path)
            assert r.status_code in (200, 404), path
            assert not INLINE_STYLE.search(r.text), path
            assert "<style" not in r.text, path
            assert "style-src 'self';" in r.headers["content-security-policy"], path


def test_art_svgs_are_small_and_style_free():
    """La CSP vaut aussi pour /static : un SVG avec `style` perdrait ses couleurs. Budgets : 2 Ko pièce, 40 Ko."""
    files = sorted(ART_DIR.glob("*.svg"))
    names = {f.name for f in files}
    for expected in ("wave-1.svg", "wave-2.svg", "cloud.svg", "hills.svg", "note.svg", "note-double.svg", "star.svg",
                     "sparkle.svg", "brush.svg", "palette.svg", "pot.svg", "spoon.svg", "heart.svg", "bubble.svg",
                     "blob-1.svg", "blob-2.svg", "check.svg", "step-install.svg", "step-prepare.svg", "step-play.svg"):
        assert expected in names, expected
    total = 0
    for f in files:
        data = f.read_text(encoding="utf-8")
        total += len(data.encode("utf-8"))
        assert "style" not in data, f.name
        assert "<script" not in data and "href" not in data, f.name
        assert len(data.encode("utf-8")) <= 2048, f.name
        assert data.startswith("<svg xmlns="), f.name
    assert total < 40 * 1024
    css = (site.STATIC_DIR / "site.css").read_text(encoding="utf-8")
    for name in re.findall(r'url\("art/([^"?]+)', css):
        assert name in names, f"site.css cite art/{name}, absent"


def test_art_and_webp_are_served_with_their_types(client):
    r = client.get("/static/art/wave-1.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "style-src 'self'" in r.headers["content-security-policy"]
    assert "immutable" in client.get("/static/art/wave-1.svg?v=1").headers["cache-control"]
    for name in ("app-musique-730.webp", "app-musique-1460.webp", "app-dessin-730.webp", "app-cuisine-1460.webp",
                 "dodo-96.webp", "dodo-512.webp"):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp", name


# --- Gabarit ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("page_id, theme", [
    ("home", "neutral"), ("music", "music"), ("songs", "music"), ("draw", "draw"), ("gallery", "draw"),
    ("cook", "cook"), ("together", "rooms"), ("download", "neutral"), ("help", "neutral"), ("terms", "neutral"),
])
def test_body_carries_page_and_theme_classes(client, page_id, theme):
    html = client.get(site.url_for("en", page_id)).text
    assert f'<body class="page-{page_id} theme-{theme}">' in html
    assert '<meta name="theme-color" content="#fff9ef" media="(prefers-color-scheme: light)">' in html


def test_error_and_room_pages_have_their_own_body_class(client):
    assert '<body class="page-error theme-neutral">' in client.get("/fr/nulle-part").text
    assert '<body class="page-room theme-rooms">' in client.get("/fr/salon/ABCDEF").text


def test_shots_are_webp_with_png_fallback_in_a_window_frame(client):
    html = client.get("/fr/").text
    assert html.count('<source type="image/webp" srcset="/static/app-') == 5          # héros + quatre activités
    assert re.search(r'srcset="/static/app-musique-730\.webp\?v=\w+ 730w, /static/app-musique-1460\.webp\?v=\w+ 1460w"',
                     html)
    assert html.count('fetchpriority="high"') == 1 and html.count('loading="eager"') == 1
    assert html.count('<figure class="win win--tilt-') == 5
    for tag in re.findall(r'<img class="shot"[^>]*>', html):
        assert 'width="1460" height="812"' in tag, tag
    assert '<source type="image/webp" srcset="/static/dodo-96.webp?v=' in html
    assert '<source type="image/webp" srcset="/static/dodo-512.webp?v=' in html
    music = client.get("/fr/musique").text
    assert '<section class="pagehead pagehead--art">' in music and '<figure class="win win--tilt-r">' in music


def test_window_frame_and_page_header_helpers():
    assert site.window_frame("<b>x</b>") == ('<figure class="win"><div class="win__frame"><span class="win__bar" '
                                            'aria-hidden="true"></span><b>x</b></div></figure>')
    assert 'class="win win--tilt-l"' in site.window_frame("x", "l", "légende")
    assert "<figcaption>légende</figcaption>" in site.window_frame("x", "l", "légende")
    assert 'win--tilt' not in site.window_frame("x", "gauche")
    head = site.page_header("fr", "Sur-titre", "Titre", "Chapeau", actions="<p>a</p>", art="<figure></figure>")
    assert '<section class="pagehead pagehead--art">' in head and "<h1>Titre</h1>" in head
    assert '<p class="eyebrow">Sur-titre</p>' in head and '<p class="lead">Chapeau</p>' in head
    assert "<h1" not in site.page_header("fr", "Légal", "", "")
    assert site.theme_of("together") == "rooms" and site.theme_of("legal") == "neutral"


def test_decor_is_never_an_image(client):
    """Le décor passe par des <span aria-hidden> stylés en CSS : tout <img> garde un alt non vide."""
    html = client.get("/fr/").text
    assert 'class="hills" aria-hidden="true"' in html and 'class="cloud cloud--a" aria-hidden="true"' in html
    for tag in re.findall(r"<img[^>]*>", html):
        assert re.search(r'alt="[^"]+"', tag), tag
        assert "/art/" not in tag, tag


# --- Accueil : seuils des compteurs, aperçus -------------------------------------------------------------------

def test_stats_appear_only_above_their_threshold(client, publish_headers, settings):
    put_and_publish(client, publish_headers, "2.0.0")
    assert home.STAT_MIN == {"downloads_total": 100, "songs_approved": 50, "users": 25}
    html = set_downloads(client, settings, 99)
    assert 'id="preuve" hidden' in html
    assert 'data-stat="downloads_total" data-min="100" hidden>' in html
    html = set_downloads(client, settings, 100)
    assert 'id="preuve" hidden' not in html and 'id="preuve">' in html
    assert 'data-stat="downloads_total" data-min="100"><span class="stat__n">100</span>' in html
    assert 'data-stat="users" data-min="25" hidden>' in html                # toujours sous son seuil
    assert 'data-stat="songs_approved" data-min="50" hidden>' in html
    assert "li.dataset.min" in html and "v>=m" in html                     # même règle dans le script


def test_home_previews_need_three_items(client, user_token, admin_token):
    html = client.get("/fr/").text
    assert 'id="morceaux"' not in html and 'id="galerie"' not in html
    sids = [approved_song(client, user_token, admin_token, n_notes=60 + i, title=f"Air {i}") for i in range(2)]
    dids = [approved_drawing(client, user_token, admin_token, title="Croquis " + "x" * i) for i in range(2)]
    site.invalidate(client.app)
    html = client.get("/fr/").text
    assert 'id="morceaux"' not in html and 'id="galerie"' not in html       # deux entrées : encore trop peu
    sids.append(approved_song(client, user_token, admin_token, n_notes=70, title="Air 2"))
    dids.append(approved_drawing(client, user_token, admin_token, title="Croquis xxx"))
    site.invalidate(client.app)
    html = client.get("/fr/").text
    assert 'id="morceaux"' in html and 'id="galerie"' in html
    assert html.count('<li class="songcard">') == 3 and html.count('<li class="drawcard">') == 3
    for sid in sids:
        assert f'href="/fr/morceaux/{sid}-air-' in html
    for did in dids:
        assert f'<img src="/api/drawings/{did}/thumb.png"' in html and f'href="/fr/galerie/{did}"' in html
    assert "0 j'aime" not in html and "0 téléchargement" not in html          # jamais de compteur nul
    assert i18n.t("fr", "site.home.songs_more") in html and i18n.t("fr", "site.home.gallery_more") in html
    en = client.get("/en/").text
    assert 'href="/en/songs"' in en and 'href="/en/gallery"' in en
    assert re.findall(r'<img[^>]+src="(?!/static/|/api/drawings/)', html) == []


def test_home_structure(client, publish_headers):
    put_and_publish(client, publish_headers, "2.0.0")
    html = client.get("/fr/").text
    assert html.count("<section class=\"act theme-") == 4          # musique, dessin, cuisine, mes créations
    for theme in ("music", "draw", "cook"):
        assert f'<section class="act theme-{theme} wavy' in html
    assert '<section class="roomsband theme-rooms wavy">' in html
    assert html.count('<li class="trust__item trust__item--') == 4
    for art in ("install", "prepare", "play"):
        assert f'<span class="step__art step__art--{art}" aria-hidden="true"></span>' in html
    assert re.search(r'<div class="instrail reveal" tabindex="0" role="region" aria-label="[^"]+">', html)
    assert html.count('<li class="instrail__item">') == 12
    assert '<span class="vbadge">Version 2.0.0</span>' in html
    assert 'class="finalcta reveal"' in html and i18n.t("fr", "site.home.final_title") in html
    assert html.index('class="hero"') < html.index('class="trust"') < html.index('id="preuve"') \
        < html.index('class="act theme-music') < html.index('id="comment-ca-marche"') \
        < html.index('id="choisir-instrument"') < html.index('id="questions"') < html.index('class="finalcta')


def test_download_page_hierarchy(client, publish_headers):
    put_and_publish(client, publish_headers, "2.0.0", notes="- une note")
    html = client.get("/fr/telecharger").text
    assert html.count('<li class="dlcard') == 3 and html.count("dlcard--primary") == 1
    primary = html.split('<li class="dlcard dlcard--primary', 1)[1].split("</li>", 1)[0]
    assert i18n.t("fr", "site.download.recommended") in primary and 'href="/telecharger/go/windows"' in primary
    assert html.count('<details class="dlcard__tech">') == 3
    assert html.count('<details name="dl-more"') == 4 and 'class="faq__body" id="smartscreen"' in html
    assert '<span class="vbadge">' in html and 'class="pillnote"' in html
    news = client.get("/fr/nouveautes").text
    assert '<ol class="timeline">' in news and '<span class="timeline__v" aria-hidden="true">2.0.0</span>' in news


def test_new_locale_keys_are_translated_everywhere():
    keys = ["site.home.trust.free", "site.home.trust.no_account", "site.home.trust.langs", "site.home.trust.platforms",
            "site.home.version_badge", "site.home.songs_title", "site.home.songs_lead", "site.home.songs_more",
            "site.home.gallery_title", "site.home.gallery_lead", "site.home.gallery_more", "site.home.final_title",
            "site.home.final_text", "site.download.recommended", "site.download.tech_details",
            "site.download.more_title", "site.instruments.rail_label", "site.footer.trust", "site.brand.dodo_alt"]
    for lang in i18n.LANGS:
        for key in keys:
            assert i18n.has(lang, key, strict=True), (lang, key)
    assert "{version}" in i18n.catalogue("th")["site.home.version_badge"]


# --- Budgets de poids --------------------------------------------------------------------------------------------

def test_weight_budgets(client, publish_headers, user_token, admin_token):
    css = (site.STATIC_DIR / "site.css").read_bytes()
    assert len(css) <= 45 * 1024, f"site.css : {len(css)} octets"
    put_and_publish(client, publish_headers, "2.0.0", notes="- une note")
    for i in range(6):
        approved_song(client, user_token, admin_token, n_notes=60 + i, title=f"Morceau numéro {i}", tags="piano")
        approved_drawing(client, user_token, admin_token, title="Dessin numéro " + "x" * i)
    site.invalidate(client.app)
    for lang in ("fr", "th"):
        body = client.get(f"/{lang}/").content
        assert len(body) < 60 * 1024, f"accueil {lang} : {len(body)} octets"
