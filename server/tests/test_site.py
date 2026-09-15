"""Site public : accueil, instruments, pages légales, robots/sitemap, échappement, statiques."""
import hashlib
import re

import pytest

from app import db, site


def put_and_publish(client, publish_headers, version="1.7.0", notes="",
                    setup=b"S" * (3 * 1024 * 1024 + 7), linux=b"L" * (2 * 1024 * 1024 + 7),
                    portable=b"P" * (1024 * 1024 + 7)):
    """Dépose l'installeur Windows, l'archive Linux et le portable, puis publie. Renvoie les tailles."""
    for platform, data, name in (("windows-setup", setup, f"DodoTopia-{version}-Setup.exe"),
                                 ("linux-x64", linux, f"DodoTopia-{version}-linux-x64.tar.gz"),
                                 ("windows-portable", portable, f"DodoTopia-{version}-portable.zip")):
        r = client.put(f"/api/admin/releases/{version}/assets/{platform}", content=data,
                       headers={**publish_headers, "X-Sha256": hashlib.sha256(data).hexdigest(),
                                "X-Filename": name})
        assert r.status_code == 200, r.text
    r = client.post(f"/api/admin/releases/{version}/publish", headers=publish_headers, json={"notes": notes})
    assert r.status_code == 200, r.text
    return {"windows-setup": len(setup), "linux-x64": len(linux), "windows-portable": len(portable)}


# --- Accueil ----------------------------------------------------------------------

def test_home_is_html_with_expected_title(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["x-content-type-options"] == "nosniff"
    html = r.text
    assert "<title>DodoTopia — jouer vos MIDI, dessiner et cuisiner dans Heartopia</title>" in html
    assert html.count("<h1") == 1
    assert '<html lang="fr">' in html
    # les trois activités de l'app sont présentées, avec une capture de l'interface
    for tab in ("Musique", "Dessin", "Cuisine"):
        assert f"<h3>{tab}</h3>" in html
    for shot in ("app-musique", "app-dessin", "app-cuisine"):
        assert f'src="/static/{shot}.png"' in html, shot
    # les sections annoncées par la navigation existent
    for anchor in ("fonctionnalites", "demarrer", "telecharger", "questions"):
        assert f'id="{anchor}"' in html, anchor
        assert f'href="/#{anchor}"' in html or f'href="#{anchor}"' in html, anchor
    assert "Comment ça marche" in html and html.count("<details>") >= 5
    # la capture réduite reste consultable en entier
    assert "ouvrir la capture en grand" in html
    # mention obligatoire du pied de page
    assert "DodoTopia est un projet indépendant, sans aucun lien avec les éditeurs d'Heartopia." in html
    # SEO
    assert '<link rel="canonical" href="http://testserver/">' in html
    assert '<meta name="description"' in html
    assert '<meta property="og:image" content="http://testserver/static/logo.png">' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert '"@type": "SoftwareApplication"' in html


def test_home_without_release_has_no_dead_link(client):
    html = client.get("/").text
    assert "Bientôt disponible" in html
    assert "/dl/" not in html
    assert "Télécharger pour Windows" not in html


def test_home_with_release_links_to_dl_and_shows_size(client, publish_headers):
    sizes = put_and_publish(client, publish_headers, "1.7.0", notes="Cuisine à quatre cuisinières")
    html = client.get("/").text
    assert "Bientôt disponible" not in html
    assert 'href="/dl/1.7.0/DodoTopia-1.7.0-Setup.exe"' in html
    assert 'href="/dl/1.7.0/DodoTopia-1.7.0-linux-x64.tar.gz"' in html
    assert 'href="/dl/1.7.0/DodoTopia-1.7.0-portable.zip"' in html    # lien secondaire
    assert site.human_size(sizes["windows-setup"]) in html            # ex. « 4,8 Mo »
    assert site.human_size(sizes["linux-x64"]) in html
    assert "Cuisine à quatre cuisinières" in html          # nouveautés, hors de la première section
    assert html.index("Voir les nouveautés") > html.index('id="fonctionnalites"')
    assert '"downloadUrl": "http://testserver/dl/1.7.0/DodoTopia-1.7.0-Setup.exe"' in html
    assert '"softwareVersion": "1.7.0"' in html
    # chaque lien de téléchargement mène bien à un fichier servi
    for href in re.findall(r'href="(/dl/[^"]+)"', html):
        assert client.get(href).status_code == 200, href


def test_home_cache_is_invalidated_on_publish(client, publish_headers):
    assert "Bientôt disponible" in client.get("/").text
    put_and_publish(client, publish_headers, "1.7.0")
    assert "/dl/1.7.0/DodoTopia-1.7.0-Setup.exe" in client.get("/").text
    assert client.delete("/api/admin/releases/1.7.0", headers=publish_headers).status_code == 200
    assert "Bientôt disponible" in client.get("/").text


def test_hostile_release_data_is_escaped(client, settings):
    """Version, nom de fichier et notes viennent de la base : rien ne doit sortir en HTML brut."""
    conn = db.connect(settings)
    try:
        conn.execute("INSERT INTO releases (version, notes, mandatory, published_at) VALUES (?, ?, 0, ?)",
                     ("1.9.9", '<script>alert("xss")</script>', db.now_iso()))
        conn.execute("INSERT INTO release_assets (version, platform, filename, sha256, size) "
                     "VALUES (?, ?, ?, ?, ?)",
                     ("1.9.9", "windows-setup", '"><img src=x onerror=alert(1)>.exe', "0" * 64, 1234))
        conn.commit()
    finally:
        conn.close()
    html = client.get("/").text
    assert "<script>alert" not in html
    assert "<img src=x onerror" not in html
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in html
    # le nom de fichier hostile est encodé dans l'URL (percent-encoding), pas interprété
    assert 'href="/dl/1.9.9/%22%3E%3Cimg%20src%3Dx%20onerror%3Dalert%281%29%3E.exe"' in html


# --- Pages légales -----------------------------------------------------------------

def test_legal_pages(client):
    for path, h1 in (("/mentions-legales", "Mentions légales"),
                     ("/confidentialite", "Politique de confidentialité"),
                     ("/conditions", "Conditions d'utilisation")):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/html")
        html = r.text
        assert f"<h1>{h1}</h1>" in html
        assert html.count("<h1") == 1
        assert f'<link rel="canonical" href="http://testserver{path}">' in html
        # les mentions obligatoires sont renseignées : plus aucun marqueur ne doit subsister en ligne
        assert "[[À COMPLÉTER" not in html, f"marqueur non rempli sur {path}"


def test_legal_identity_is_published(client):
    """LCEN art. 6-III : éditeur identifiable et hébergeur nommé ; RGPD art. 13 : responsable joignable."""
    mentions = client.get("/mentions-legales").text
    for expected in ("Dorian Breuillard", "Cyber-Dodo", "925 110 132 00022", "Chambéry",
                     "contact@cyber-dodo.fr", "07 72 28 20 62", "293 B", "OUIHEBERG"):
        assert expected in mentions, expected
    conf = client.get("/confidentialite").text
    for expected in ("Dorian Breuillard", "contact@cyber-dodo.fr", "Marseille"):
        assert expected in conf, expected
    conditions = client.get("/conditions").text
    for expected in ("contact@cyber-dodo.fr", "français"):
        assert expected in conditions, expected


def test_privacy_describes_the_real_data(client):
    html = client.get("/confidentialite").text
    for expected in ("Identifiant Discord", "avatar", "SHA-256", "90 jours", "Signalements",
                     "en mémoire vive", "RGPD", "érification de mise à jour"):
        assert expected in html, expected


def test_no_external_resource_anywhere(client):
    """Aucune police, aucun script, aucune feuille de style servis par un tiers."""
    for path in ("/", "/instruments", "/mentions-legales", "/confidentialite", "/conditions"):
        html = client.get(path).text
        for bad in ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com",
                    "unpkg.com", "<script src"):
            assert bad not in html, f"{bad} dans {path}"


# --- Instruments ---------------------------------------------------------------------
#
# La page /instruments est alimentee par la copie servie de `assets/instruments/catalogue.json`
# (voir le commentaire en tete de `site.py`). Ces tests verifient ce qui doit rester vrai apres
# n'importe quelle mise a jour du catalogue : une carte par type, trois etats distincts, aucune
# promesse de compatibilite, aucune image externe, et la copie servie identique au depot.

# Formulations interdites : le catalogue ne prouve ni compatibilite ni test en jeu.
FORBIDDEN = ("tous les instruments sont compatibles", "testé dans Heartopia", "testés dans Heartopia",
             "validé dans le jeu", "validés dans le jeu", "63 instruments")


def catalogue():
    return site.instrument_catalogue()


def test_instruments_page_lists_one_card_per_type(client):
    cat = catalogue()
    r = client.get("/instruments")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    assert html.count("<h1") == 1
    assert '<link rel="canonical" href="http://testserver/instruments">' in html
    # une carte par type, ni plus (pas de variante esthetique) ni moins
    assert html.count('<li class="inst">') == cat["total"] == len(cat["types"])
    assert html.count(">Piano</h3>") == 1
    for inst in cat["types"]:
        assert f">{inst['label_fr']}</h3>" in html, inst["id"]


def test_instruments_page_separates_catalogue_from_verification(client):
    """« Présent au catalogue » et « lecture configurée et vérifiée » ne doivent pas se confondre."""
    html = client.get("/instruments").text
    for bad in FORBIDDEN:
        assert bad not in html, bad
    assert "Présent au catalogue n'est pas lecture vérifiée." in html
    # les trois etats sont nommes, et aucun ne vaut « vérifié »
    for state, (label, _) in site.INST_STATES.items():
        assert label in html, state
    assert "La vérification se fait sur ton ordinateur" in html


def test_instruments_states_match_the_catalogue_data(client):
    """Les compteurs affiches viennent du fichier, pas d'un texte ecrit en dur."""
    cat = catalogue()
    counts = cat["counts"]
    assert sum(counts.values()) == cat["total"]
    # xylophone, saxophone, harpe, tambour a langues, ocarina, conque : touches a relever
    by_id = {t["id"]: t for t in cat["types"]}
    for missing in ("xylophone", "saxophone", "harp", "steel-tongue-drum", "ocarina", "conch"):
        assert by_id[missing]["state"] == "unknown", missing
    # conga et cajon : correspondance candidate, jamais « documente » tout court
    for perc in ("conga", "cajon"):
        assert by_id[perc]["state"] == "candidate", perc
    assert by_id["piano"]["state"] == "documented"
    html = client.get("/instruments").text
    for state, n in counts.items():
        assert f"{n} type" in html, state


def test_instruments_images_are_local_and_served(client):
    """Aucun hotlink : chaque visuel est un fichier de ce serveur, et il repond vraiment."""
    html = client.get("/instruments").text
    srcs = set(re.findall(r'<img[^>]+src="([^"]+)"', html))
    assert srcs, "aucune image sur la page"
    for src in srcs:
        assert src.startswith("/static/"), src
        r = client.get(src)
        assert r.status_code == 200, src
        assert r.headers["content-type"].startswith("image/"), src
    # au moins un vrai visuel d'instrument
    assert any(s.startswith("/static/instruments/") for s in srcs)


def test_missing_image_falls_back_to_a_family_badge():
    """Une image absente ne casse pas la grille : pastille generique de famille, place identique."""
    html = site.inst_media({"image": None, "category": "winds", "label_fr": "Conque"})
    assert "inst__media--none" in html and 'role="img"' in html
    assert site.FAMILY_FALLBACK["winds"] in html
    assert "saxophone" not in html.lower()      # jamais l'icone d'un autre instrument


def test_no_variant_pages(client):
    """Une seule page liste les types : pas de page par variante de couleur."""
    cat = catalogue()
    for inst in cat["types"][:3]:
        assert client.get(f"/instruments/{inst['id']}").status_code == 404


def test_served_catalogue_copy_matches_the_repository():
    """La copie servie doit rester identique aux fichiers que charge l'application.

    C'est le garde-fou de la copie build-time : si `assets/instruments/` ou `ui/instruments/` bouge sans
    que `server/static/instruments/` soit rafraichi, ce test echoue. Hors du depot (conteneur), il passe.
    """
    if not site.REPO_INST_DIR.is_dir():
        pytest.skip("hors du dépôt : seule la copie de server/static est disponible")
    for name in ("catalogue.json", "layouts.json"):
        served, origin = site.INST_DIR / name, site.REPO_INST_DIR / name
        assert served.is_file(), f"copie manquante : {served}"
        assert served.read_bytes() == origin.read_bytes(), f"copie périmée : {name}"
    for origin in sorted(site.REPO_IMG_DIR.glob("*.png")):
        served = site.INST_DIR / origin.name
        assert served.is_file(), f"visuel manquant dans la copie : {origin.name}"
        assert served.read_bytes() == origin.read_bytes(), f"visuel périmé : {origin.name}"


def test_every_type_has_its_image_in_the_copy():
    """Une image par type, et le fichier existe vraiment (sinon la page tomberait sur la pastille)."""
    cat = catalogue()
    urls = [t["image"]["url"] for t in cat["types"] if t["image"]]
    assert len(urls) == cat["total"], "un type n'a pas de visuel servi"
    assert len(set(urls)) == cat["total"], "deux types partagent la même image"


def test_home_announces_the_instrument_choice(client):
    cat = catalogue()
    html = client.get("/").text
    assert 'id="choisir-instrument"' in html
    assert "<h2>Choisis ton instrument</h2>" in html
    assert 'href="/instruments"' in html
    assert f"{cat['total']} types d'instruments" in html
    for bad in FORBIDDEN:
        assert bad not in html, bad
    # quelques vrais visuels, servis localement
    assert html.count('src="/static/instruments/') >= 4


def test_unreadable_catalogue_does_not_break_the_site(client, monkeypatch):
    """Un catalogue absent ou abime ne doit ni casser l'accueil ni renvoyer une erreur serveur."""
    monkeypatch.setattr(site, "_CATALOGUE", dict(site.EMPTY_CATALOGUE))
    home = client.get("/")
    assert home.status_code == 200
    assert 'id="choisir-instrument"' not in home.text        # section retiree, pas une section vide
    r = client.get("/instruments")
    assert r.status_code == 200
    assert "n'est pas consultable pour le moment" in r.text
    assert r.text.count("<h1") == 1


def test_instrument_layouts_are_described_from_the_data(client):
    """Les quatre dispositions sont presentees, avec le nombre de notes reel."""
    cat = catalogue()
    html = client.get("/instruments").text
    assert [lay["note_count"] for lay in cat["layouts"]] == [15, 15, 22, 37]
    for lay in cat["layouts"]:
        assert lay["id"] in html, lay["id"]
    assert "les deux dispositions à 15 notes ne diffèrent pas seulement par leur" in html


def test_instruments_page_keeps_the_visual_credits(client):
    html = client.get("/instruments").text
    assert "Provenance des visuels" in html
    assert "build-heartopia.com" in html
    assert "licence de réutilisation libre" in html
    assert site.EDITEUR_COURRIEL in html          # marche a suivre pour un retrait


# --- robots / sitemap / statiques ----------------------------------------------------

def test_robots_txt(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "User-agent: *" in r.text and "Allow: /" in r.text
    assert "Sitemap: http://testserver/sitemap.xml" in r.text


def test_sitemap_xml(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    for path in ("/", "/instruments", "/mentions-legales", "/confidentialite", "/conditions"):
        assert f"<loc>http://testserver{path}</loc>" in r.text
    assert r.text.count("<url>") == len(site.PAGES)


def test_static_files(client):
    r = client.get("/static/site.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "max-age" in r.headers["cache-control"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "--amber:#e8a531" in r.text
    for path in ("/static/logo.png", "/static/favicon.ico", "/static/app-musique.png",
                 "/static/app-dessin.png", "/static/app-cuisine.png",
                 "/static/fonts/fredoka-latin.woff2", "/static/fonts/nunito-latin.woff2"):
        r = client.get(path)
        assert r.status_code == 200, path
    # les polices sont servies avec le bon type (sinon nosniff + type générique gêne certains proxys)
    assert client.get("/static/fonts/nunito-latin.woff2").headers["content-type"] == "font/woff2"
    assert client.get("/favicon.ico").status_code == 200


def test_helpers():
    assert site.human_size(5 * 1024 * 1024) == "5,0 Mo"
    assert site.human_size(210 * 1024 * 1024) == "210 Mo"
    assert site.human_date("2026-09-14T10:00:00+00:00") == "14 septembre 2026"
    assert site.human_date("pas une date") == ""
    assert site.dl_path("1.0.0", 'a"b.exe') == "/dl/1.0.0/a%22b.exe"
