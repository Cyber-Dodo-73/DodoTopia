"""Site public : accueil (avec et sans version publiée), pages légales, robots/sitemap, échappement, statiques."""
import hashlib
import re

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
    # les trois onglets de l'app sont présentés
    for tab in ("Musique", "Image", "Cuisine"):
        assert f"<h3>{tab}</h3>" in html
    assert "Comment ça marche" in html and html.count("<details>") >= 5
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
    assert "Cuisine à quatre cuisinières" in html
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
    for path in ("/", "/mentions-legales", "/confidentialite", "/conditions"):
        html = client.get(path).text
        for bad in ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com",
                    "unpkg.com", "<script src"):
            assert bad not in html, f"{bad} dans {path}"


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
    for path in ("/", "/mentions-legales", "/confidentialite", "/conditions"):
        assert f"<loc>http://testserver{path}</loc>" in r.text


def test_static_files(client):
    r = client.get("/static/site.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "max-age" in r.headers["cache-control"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "--amber:#e8a531" in r.text
    for path in ("/static/logo.png", "/static/favicon.ico",
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
