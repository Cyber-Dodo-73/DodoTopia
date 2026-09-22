"""Pages publiques Morceaux, Galerie et Salon : listes, fiches (200/301/404/noindex), JSON-LD, images de partage,
sitemaps, lien d'invitation et `GET /api/rooms/{code}/exists`."""
import io
import json
import re

import pytest
from conftest import bearer, login, make_client, make_midi, make_settings
from PIL import Image

from app import db, i18n, site
from test_gallery import make_png

LANGS = i18n.LANGS


def approved_song(client, token, admin_token, n_notes=60, title="Für Élise", **fields):
    r = client.post("/api/songs", headers=bearer(token),
                    files={"file": (f"{n_notes}.mid", make_midi(n_notes=n_notes), "audio/midi")},
                    data={"title": title, "artist": "Beethoven", **fields})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    client.post(f"/api/admin/songs/{sid}/approve", headers=bearer(admin_token))
    return sid


def approved_drawing(client, token, admin_token, title="Chat roux", cells=True):
    data = {"title": title}
    if cells:
        data["cells"] = json.dumps({"format": "30x30", "w": 2, "h": 1, "cells": [1, 2]})
    r = client.post("/api/drawings", headers=bearer(token), data=data,
                    files={"png": ("d.png", make_png(640, 480, color=(len(title), 80, 90)), "image/png")})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    client.post(f"/api/admin/drawings/{did}/approve", headers=bearer(admin_token))
    return did


def ld_types(html):
    """Types des nœuds JSON-LD de la page (`@graph` aplati : le site et son éditeur partagent un script)."""
    types = []
    for raw in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        data = json.loads(raw)
        types.extend(node.get("@type") for node in data.get("@graph", [data]))
    return types


# --- Morceaux -----------------------------------------------------------------------------------------------------

def test_songs_list_empty_then_filled(client, user_token, admin_token):
    for lang in LANGS:
        r = client.get(site.url_for(lang, "songs"))
        assert r.status_code == 200 and '<meta name="robots" content="index, follow, max-image-preview:large">' in r.text
        assert "[site." not in r.text and r.text.count("<h1") == 1
    assert i18n.t("fr", "site.songs.empty_title") in client.get("/fr/morceaux").text
    sid = approved_song(client, user_token, admin_token, tags="piano,classique")
    site.invalidate(client.app)
    html = client.get("/fr/morceaux").text
    assert f'href="/fr/morceaux/{sid}-fur-elise"' in html and "Für Élise" in html
    assert 'href="/fr/morceaux?tag=piano"' in html and ">Classique<" in html
    en = client.get("/en/songs").text
    assert f'href="/en/songs/{sid}-fur-elise"' in en and ">Classical<" in en
    # nav et pied de page
    assert 'href="/de/lieder"' in client.get("/de/").text and 'href="/de/galerie"' in client.get("/de/").text


def test_songs_list_filters_are_noindex(client, user_token, admin_token):
    a = approved_song(client, user_token, admin_token, title="Alpha piano", tags="piano")
    b = approved_song(client, user_token, admin_token, n_notes=61, title="Beta rock", tags="rock")
    r = client.get("/fr/morceaux?tag=rock")
    assert r.status_code == 200 and '<meta name="robots" content="noindex, follow">' in r.text
    assert f"/fr/morceaux/{b}-beta-rock" in r.text and f"/fr/morceaux/{a}-" not in r.text
    assert '<link rel="canonical" href="http://testserver/fr/morceaux">' in r.text
    r = client.get("/fr/morceaux?q=alpha&sort=title")
    assert f"/fr/morceaux/{a}-alpha-piano" in r.text and f"/fr/morceaux/{b}-" not in r.text
    assert 'option value="title" selected' in r.text
    r = client.get("/fr/morceaux?q=zzz")
    assert i18n.t("fr", "site.songs.no_match_title") in r.text
    # paramètres inconnus ou invalides : page de base
    r = client.get("/fr/morceaux?tag=<script>&sort=drop&page=-3&utm_source=x")
    assert r.status_code == 200 and "<script>" not in r.text.split("<main", 1)[1]
    assert '<meta name="robots" content="index, follow, max-image-preview:large">' in r.text


def test_song_detail_page(client, user_token, admin_token):
    sid = approved_song(client, user_token, admin_token, tags="piano", instrument="violin", license="public_domain",
                        source_url="https://onlinesequencer.net/1", source_name="Online Sequencer")
    path = f"/fr/morceaux/{sid}-fur-elise"
    r = client.get(path)
    assert r.status_code == 200, r.text
    html = r.text
    assert "<h1>Für Élise</h1>" in html and f'href="dodotopia://song/{sid}"' in html
    assert 'href="/fr/telecharger"' in html and "Ouvrir dans DodoTopia" in html
    assert '<meta name="robots" content="index, follow, max-image-preview:large">' in html
    assert f'<link rel="canonical" href="http://testserver{path}">' in html
    assert f'<link rel="alternate" hreflang="en" href="http://testserver/en/songs/{sid}-fur-elise">' in html
    assert f'<link rel="alternate" hreflang="x-default" href="http://testserver/en/songs/{sid}-fur-elise">' in html
    assert f'<meta property="og:image" content="http://testserver/og/song/{sid}.png">' in html
    assert "<title>Für Élise — MIDI pour Heartopia</title>" in html
    assert {"MusicComposition", "BreadcrumbList", "Organization"} <= set(ld_types(html))
    assert "Violon" in html and "Domaine public" in html and "Beethoven" in html
    assert 'href="https://onlinesequencer.net/1" rel="nofollow noopener ugc external"' in html
    assert 'href="/de/lieder/' in html              # sélecteur de langue vers la même fiche
    for lang in LANGS:
        url = f"/{lang}/{site.ROUTES['songs'][lang]}/{sid}-fur-elise"
        page = client.get(url)
        assert page.status_code == 200 and "[site." not in page.text, url
        assert page.text.count("<h1") == 1


def test_song_detail_redirects_and_404(client, user_token, admin_token, midi_bytes):
    sid = approved_song(client, user_token, admin_token)
    for wrong in (f"/fr/morceaux/{sid}", f"/fr/morceaux/{sid}-mauvais-slug", f"/fr/songs/{sid}-fur-elise"):
        r = client.get(wrong)
        assert r.status_code == 301 and r.headers["location"] == f"/fr/morceaux/{sid}-fur-elise", wrong
    r = client.get(f"/en/morceaux/{sid}-x")
    assert r.status_code == 301 and r.headers["location"] == f"/en/songs/{sid}-fur-elise"
    pending = client.post("/api/songs", headers=bearer(user_token), files={"file": ("p.mid", midi_bytes)}).json()["id"]
    for path in (f"/fr/morceaux/{pending}-morceau", "/fr/morceaux/9999-rien", "/fr/morceaux/abc", "/fr/morceaux/1/2"):
        r = client.get(path)
        assert r.status_code == 404 and "noindex" in r.text, path


def test_short_song_is_noindex_and_absent_from_sitemap(client, user_token, admin_token):
    short = approved_song(client, user_token, admin_token, n_notes=20, title="Court")
    long_ = approved_song(client, user_token, admin_token, n_notes=80, title="Long")
    html = client.get(f"/fr/morceaux/{short}-court").text
    assert '<meta name="robots" content="noindex, follow">' in html
    xml = client.get("/sitemap-songs.xml").text
    assert f"/fr/morceaux/{long_}-long</loc>" in xml and f"/{short}-court" not in xml
    assert xml.count("<url>") == len(LANGS) and xml.count("<xhtml:link") == len(LANGS) * (len(LANGS) + 1)


def test_hostile_song_title_is_escaped(client, user_token, admin_token, settings):
    sid = approved_song(client, user_token, admin_token, title='</script><img src=x onerror=alert(1)>"')
    site.invalidate(client.app)
    for path in ("/fr/morceaux", client.get(f"/fr/morceaux/{sid}").headers["location"]):
        html = client.get(path).text
        assert "<img src=x" not in html, path
        for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
            assert "</" not in block
            json.loads(block)


def test_song_og_image(client, user_token, admin_token, settings, midi_bytes):
    sid = approved_song(client, user_token, admin_token)
    r = client.get(f"/og/song/{sid}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
    files = list(settings.og_cache_dir.glob(f"song-{sid}-*.png"))
    assert len(files) == 1
    assert client.get(f"/og/song/{sid}.png").content == r.content          # servi depuis le cache disque
    client.patch(f"/api/songs/{sid}", headers=bearer(admin_token), json={"title": "Nouveau titre"})
    client.get(f"/og/song/{sid}.png")
    assert len(list(settings.og_cache_dir.glob(f"song-{sid}-*.png"))) == 1 and not files[0].exists()
    pending = client.post("/api/songs", headers=bearer(user_token), files={"file": ("p.mid", midi_bytes)}).json()["id"]
    assert client.get(f"/og/song/{pending}.png").status_code == 404
    assert client.get("/og/song/424242.png").status_code == 404


# --- Galerie ---------------------------------------------------------------------------------------------------------

def test_gallery_list_and_detail(client, user_token, admin_token):
    assert i18n.t("fr", "site.gallery.empty_title") in client.get("/fr/galerie").text
    did = approved_drawing(client, user_token, admin_token)
    site.invalidate(client.app)
    html = client.get("/fr/galerie").text
    assert f'<img src="/api/drawings/{did}/thumb.png" width="400" height="300"' in html
    assert f'href="/fr/galerie/{did}"' in html
    r = client.get(f"/fr/galerie/{did}")
    assert r.status_code == 200
    page = r.text
    assert "<h1>Chat roux</h1>" in page and f'href="dodotopia://drawing/{did}"' in page
    assert "Reproduire ce dessin dans DodoTopia" in page
    assert f'<meta property="og:image" content="http://testserver/api/drawings/{did}/thumb.png">' in page
    assert '<meta property="og:image:width" content="400">' in page
    assert {"VisualArtwork", "BreadcrumbList"} <= set(ld_types(page))
    assert f'<link rel="alternate" hreflang="ja" href="http://testserver/ja/gallery/{did}">' in page
    for lang in LANGS:
        p = client.get(f"/{lang}/{site.ROUTES['gallery'][lang]}/{did}")
        assert p.status_code == 200 and "[site." not in p.text
    assert client.get(f"/fr/galerie/{did}-chat").headers["location"] == f"/fr/galerie/{did}"
    assert client.get(f"/en/galerie/{did}").headers["location"] == f"/en/gallery/{did}"
    assert client.get("/fr/galerie/9999").status_code == 404
    assert client.get("/fr/galerie?sort=popular").status_code == 200


def test_gallery_drawing_without_cells_and_pending(client, user_token, admin_token):
    did = approved_drawing(client, user_token, admin_token, title="Sans grille", cells=False)
    html = client.get(f"/fr/galerie/{did}").text
    assert "dodotopia://drawing/" not in html and i18n.t("fr", "site.gallery.no_cells") in html
    r = client.post("/api/drawings", headers=bearer(user_token), data={"title": "attente"},
                    files={"png": ("d.png", make_png(color=(5, 5, 5)), "image/png")})
    assert client.get(f"/fr/galerie/{r.json()['id']}").status_code == 404


def test_sitemaps(client, user_token, admin_token):
    # Index : un sitemap enfant vide n'est pas listé (Google et Bing le signalent en erreur), mais il répond 200.
    r = client.get("/sitemap.xml")
    assert "<loc>http://testserver/sitemap-pages.xml</loc>" in r.text
    assert "sitemap-songs.xml" not in r.text and "sitemap-gallery.xml" not in r.text
    empty = client.get("/sitemap-gallery.xml")
    assert empty.status_code == 200 and "<urlset" in empty.text and empty.text.count("<url>") == 0
    assert client.get("/sitemap-songs.xml").status_code == 200
    did = approved_drawing(client, user_token, admin_token)
    index = client.get("/sitemap.xml").text
    assert "<loc>http://testserver/sitemap-gallery.xml</loc>" in index and "sitemap-songs.xml" not in index
    xml = client.get("/sitemap-gallery.xml")
    assert xml.status_code == 200 and xml.headers["content-type"].startswith("application/xml")
    assert f"<loc>http://testserver/pt-BR/galeria/{did}</loc>" in xml.text and xml.text.count("<url>") == len(LANGS)
    assert re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", xml.text)
    pages = client.get("/sitemap-pages.xml").text
    assert "<loc>http://testserver/fr/morceaux</loc>" in pages and "<loc>http://testserver/en/gallery</loc>" in pages
    assert "Allow: /api/drawings/*.png$" in client.get("/robots.txt").text


# --- Salons ------------------------------------------------------------------------------------------------------------

def test_room_invitation_page(client):
    r = client.get("/fr/salon/ABCDEF")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    html = r.text
    assert '<meta name="robots" content="noindex, nofollow">' in html and 'rel="canonical"' not in html
    assert 'href="dodotopia://room/ABCDEF"' in html and "Rejoindre le salon ABCDEF" in html
    nonce = re.search(r"'nonce-([^']+)'", r.headers["content-security-policy"]).group(1)
    scripts = re.findall(r"<script[^>]*>", html)
    assert scripts and all(f'nonce="{nonce}"' in tag for tag in scripts)
    assert "/api/rooms/" in html and 'href="/fr/telecharger"' in html
    assert client.get("/fr/salon/abcdef").headers["location"] == "/fr/salon/ABCDEF"
    assert client.get("/en/salon/ABCDEF").headers["location"] == "/en/room/ABCDEF"
    assert client.get("/ja/room/ABCDEF").status_code == 200
    for bad in ("/fr/salon/ABC", "/fr/salon/ABCDE0", "/fr/salon/<script>", "/fr/salon/ABCDEFG"):
        assert client.get(bad).status_code == 404, bad


def test_room_exists_endpoint(client):
    r = client.get("/api/rooms/ABCDEF/exists")
    assert r.status_code == 200 and r.json() == {"code": "ABCDEF", "exists": False, "full": False}
    room = client.app.state.rooms.create(2)
    body = client.get(f"/api/rooms/{room.code.lower()}/exists").json()
    assert body == {"code": room.code, "exists": True, "full": False}
    assert client.get("/api/rooms/x/exists").json()["exists"] is False


def test_room_exists_limited_30_per_min(tmp_path):
    with make_client(make_settings(tmp_path, RATE_LIMIT=1)) as c:
        codes = [c.get("/api/rooms/ABCDEF/exists").status_code for _ in range(31)]
        assert codes[:30] == [200] * 30 and codes[30] == 429
