"""Site public multilingue : redirections, pages × langues, SEO (hreflang, sitemap, OG), en-têtes (CSP à nonce,
ETag), téléchargements, pages légales, échappement, instruments, statiques."""
import hashlib
import json
import re
import struct

import pytest

from app import db, i18n, legal_md, site
from app.site_pages import instruments as inst_page

LANGS = i18n.LANGS


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


def alternates(html: str) -> dict:
    return dict(re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', html))


# --- Redirections ------------------------------------------------------------------------

@pytest.mark.parametrize("accept, expected", [
    ("fr-FR,fr;q=0.9,en;q=0.8", "/fr/"),
    ("en-US,en;q=0.9", "/en/"),
    ("th-TH,th;q=0.9", "/th/"),
    ("pt-PT,pt;q=0.9", "/pt-BR/"),
    ("zh-TW", "/zh-CN/"),
    ("de;q=0.2, ja;q=0.8", "/ja/"),
    ("xx-YY, tlh", "/en/"),
    ("", "/en/"),
])
def test_root_redirects_by_accept_language(client, accept, expected):
    r = client.get("/", headers={"Accept-Language": accept} if accept else {})
    assert r.status_code == 302
    assert r.headers["location"] == expected
    assert "Accept-Language" in r.headers["vary"]
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("old, new", [
    ("/instruments", "/fr/instruments"),
    ("/mentions-legales", "/fr/mentions-legales"),
    ("/confidentialite", "/fr/confidentialite"),
    ("/conditions", "/fr/conditions"),
])
def test_legacy_urls_are_permanently_redirected(client, old, new):
    r = client.get(old)
    assert r.status_code == 301 and r.headers["location"] == new


def test_lang_without_slash_and_foreign_slug_redirect(client):
    assert client.get("/de").headers["location"] == "/de/"
    r = client.get("/en/telecharger")                 # slug français recopié sur la version anglaise
    assert r.status_code == 301 and r.headers["location"] == "/en/download"


def test_api_paths_keep_json_errors(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert client.get("/api/health").status_code == 200


# --- Toutes les pages, toutes les langues ------------------------------------------------------

def test_every_page_in_every_language(client):
    titles = set()
    for page_id in site.PAGE_IDS:
        for lang in LANGS:
            path = site.url_for(lang, page_id)
            r = client.get(path)
            assert r.status_code == 200, path
            assert r.headers["content-type"].startswith("text/html"), path
            html = r.text
            assert f'<html lang="{lang}">' in html, path
            assert html.count("<h1") == 1, path
            assert f'<link rel="canonical" href="http://testserver{path}">' in html, path
            assert "[site." not in html, path
            assert "__NONCE__" not in html, path
            title = re.search(r"<title>([^<]*)</title>", html).group(1)
            assert title not in titles, f"titre en double : {title}"
            titles.add(title)
            assert (f'<link rel="alternate" hreflang="x-default" href="http://testserver'
                    f'{site.url_for("en", page_id)}">') in html, path
            beta = 'class="beta"' in html
            assert beta == (lang not in ("fr", "en")), path


def test_hreflang_is_reciprocal(client):
    for page_id in ("home", "download", "help", "terms"):
        pages = {lang: client.get(site.url_for(lang, page_id)).text for lang in LANGS}
        expected = {lang: f"http://testserver{site.url_for(lang, page_id)}" for lang in LANGS}
        for lang, html in pages.items():
            alts = alternates(html)
            assert set(alts) == set(LANGS) | {"x-default"}, (page_id, lang)
            for code in LANGS:
                assert alts[code] == expected[code], (page_id, lang, code)


def test_language_switcher_links_to_same_page_without_js(client):
    html = client.get("/de/hilfe").text
    menu = html.split('<details class="langs">', 1)[1].split("</details>", 1)[0]
    for lang in LANGS:
        assert f'href="{site.url_for(lang, "help")}"' in menu
    assert 'href="/de/hilfe" hreflang="de" lang="de" aria-current="true"' in menu


def test_internal_links_from_catalogue_follow_the_language(client):
    """Les liens `/fr/…` écrits dans les textes pointent vers la même page dans la langue affichée."""
    html = client.get("/en/").text
    main = html.split("<main", 1)[1].split("</main>", 1)[0]
    assert 'href="/fr/' not in main
    assert 'href="/en/play-together"' in main


def test_catalogues_fr_and_en_have_the_same_keys():
    fr = {k for k in i18n.catalogue("fr") if not k.startswith("_")}
    en = {k for k in i18n.catalogue("en") if not k.startswith("_")}
    assert fr and fr == en
    params = re.compile(r"\{[A-Za-z_]\w*\}")
    for key in fr:
        assert sorted(params.findall(i18n.catalogue("fr")[key])) == sorted(params.findall(i18n.catalogue("en")[key])), key
    for lang in LANGS:
        cat = i18n.catalogue(lang)
        assert cat, lang
        assert not set(cat) - set(i18n.catalogue("fr")), f"clés inconnues dans {lang}"
        assert i18n.is_beta(lang) == (lang not in ("fr", "en"))


def test_missing_key_falls_back_to_en_then_fr(monkeypatch):
    monkeypatch.setitem(i18n._CATALOGUES, "de", {"site.nav.help": "Hilfe"})
    assert i18n.t("de", "site.nav.help") == "Hilfe"
    assert i18n.t("de", "site.nav.music") == i18n.catalogue("en")["site.nav.music"]
    monkeypatch.setitem(i18n._CATALOGUES, "en", {})
    assert i18n.t("de", "site.nav.music") == i18n.catalogue("fr")["site.nav.music"]
    assert i18n.t("de", "site.nope") == "[site.nope]"
    assert i18n.t("fr", "site.download.version_line", version="<b>") .count("&lt;b&gt;") == 1


def test_not_found_page_is_translated_and_noindex(client):
    for lang in ("fr", "ja"):
        r = client.get(f"/{lang}/nulle-part")
        assert r.status_code == 404
        assert f'<html lang="{lang}">' in r.text
        assert '<meta name="robots" content="noindex, nofollow">' in r.text
        assert i18n.t(lang, "site.errors.404.h1") in r.text
        assert 'rel="canonical"' not in r.text
    r = client.get("/nulle-part", headers={"Accept-Language": "fr"})
    assert r.status_code == 404 and '<html lang="fr">' in r.text


# --- En-têtes : CSP à nonce, ETag, cache -------------------------------------------------------

def test_csp_nonce_matches_inline_scripts(client):
    r = client.get("/fr/")
    csp = r.headers["content-security-policy"]
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    scripts = re.findall(r"<script[^>]*>", r.text)
    assert scripts, "au moins le JSON-LD"
    for tag in scripts:
        assert f'nonce="{nonce}"' in tag, tag
    assert "unsafe-inline" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    # un nonce neuf par requête, même page en cache
    r2 = client.get("/fr/")
    nonce2 = re.search(r"'nonce-([^']+)'", r2.headers["content-security-policy"]).group(1)
    assert nonce2 != nonce and f'nonce="{nonce2}"' in r2.text


def test_etag_and_conditional_get(client):
    r = client.get("/en/help")
    etag = r.headers["etag"]
    assert etag.startswith('W/"')
    assert "max-age" in r.headers["cache-control"]
    r2 = client.get("/en/help", headers={"If-None-Match": etag})
    assert r2.status_code == 304 and not r2.content


def test_gzip(client):
    r = client.get("/fr/aide", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_plausible_and_verification_only_when_configured(tmp_path):
    from conftest import make_client, make_settings
    html_off = None
    with make_client(make_settings(tmp_path / "a")) as c:
        html_off = c.get("/fr/").text
    assert "plausible" not in html_off and "google-site-verification" not in html_off
    s = make_settings(tmp_path / "b", PLAUSIBLE_SCRIPT_URL="https://plausible.io/js/script.js",
                      SITE_VERIFICATION_GOOGLE="g-123", SITE_VERIFICATION_BING="b-456")
    with make_client(s) as c:
        r = c.get("/fr/")
        assert '<meta name="google-site-verification" content="g-123">' in r.text
        assert '<meta name="msvalidate.01" content="b-456">' in r.text
        assert 'src="https://plausible.io/js/script.js"' in r.text
        assert "https://plausible.io" in r.headers["content-security-policy"]


# --- Accueil et téléchargement ------------------------------------------------------------------

def test_home_content_fr(client):
    html = client.get("/fr/").text
    for page_id in ("music", "draw", "cook"):
        assert f'<h3><a href="{site.url_for("fr", page_id)}">' in html
    for shot in ("app-musique", "app-dessin", "app-cuisine"):
        assert f'src="/static/{shot}.png?v=' in html, shot
    assert 'id="comment-ca-marche"' in html and html.count('<li class="step">') >= 3
    assert "Outil non officiel." in html
    assert "DodoTopia est un projet indépendant, sans aucun lien avec les éditeurs d'Heartopia." in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert '"@type": "SoftwareApplication"' in html and '"@type": "FAQPage"' in html
    assert '"@type": "Organization"' in html
    # preuve sociale masquée sans chiffres ; Discord absent sans COMMUNITY_DISCORD_URL
    assert 'id="preuve" hidden' in html
    assert 'id="communaute"' not in html


def test_home_shows_discord_when_configured(tmp_path):
    from conftest import make_client, make_settings
    with make_client(make_settings(tmp_path, COMMUNITY_DISCORD_URL="https://discord.gg/abc")) as c:
        html = c.get("/en/").text
    assert 'href="https://discord.gg/abc"' in html


def test_home_without_release_has_no_dead_link(client):
    for path in ("/fr/", "/fr/telecharger"):
        html = client.get(path).text
        assert "Bientôt disponible" in html, path
        assert "/dl/" not in html and "/telecharger/go/" not in html, path
    assert client.get("/telecharger/go/windows").status_code == 404


def test_download_page_with_release(client, publish_headers):
    sizes = put_and_publish(client, publish_headers, "1.7.0", notes="Cuisine à quatre cuisinières")
    html = client.get("/fr/telecharger").text
    assert "Bientôt disponible" not in html
    for go in ("windows", "portable", "linux"):
        assert f'href="/telecharger/go/{go}"' in html, go
    assert site.human_size(sizes["windows-setup"]) in html
    sha = hashlib.sha256(b"S" * (3 * 1024 * 1024 + 7)).hexdigest()
    assert sha in html
    assert f"https://www.virustotal.com/gui/file/{sha}" in html
    assert "Cuisine à quatre cuisinières" in html
    assert 'id="smartscreen"' in html
    assert '"softwareVersion": "1.7.0"' in html
    assert '"downloadUrl": "http://testserver/dl/1.7.0/DodoTopia-1.7.0-Setup.exe"' in html
    # nouveautés et accueil
    assert "Cuisine à quatre cuisinières" in client.get("/fr/nouveautes").text
    home = client.get("/en/").text
    assert 'href="/telecharger/go/windows"' in home and "Coming soon" not in home


def test_download_go_redirects_and_counts(client, publish_headers, settings):
    put_and_publish(client, publish_headers, "1.7.0")
    r = client.get("/telecharger/go/windows")
    assert r.status_code == 302
    assert r.headers["location"] == "/dl/1.7.0/DodoTopia-1.7.0-Setup.exe?via=site"
    assert r.headers["cache-control"] == "no-store"
    # le fichier est servi sans double comptage
    assert client.get(r.headers["location"]).status_code == 200
    client.get("/telecharger/go/linux")
    conn = db.connect(settings)
    try:
        rows = {row["platform"]: row["downloads"] for row in conn.execute("SELECT platform, downloads FROM release_assets").fetchall()}
    finally:
        conn.close()
    assert rows["windows-setup"] == 1 and rows["linux-x64"] == 1 and rows["windows-portable"] == 0
    assert client.get("/api/stats").json()["downloads_total"] == 2
    assert client.get("/telecharger/go/macos").status_code == 404


def test_home_cache_is_invalidated_on_publish(client, publish_headers):
    assert "Bientôt disponible" in client.get("/fr/").text
    put_and_publish(client, publish_headers, "1.7.0")
    assert "/telecharger/go/windows" in client.get("/fr/").text
    assert client.delete("/api/admin/releases/1.7.0", headers=publish_headers).status_code == 200
    assert "Bientôt disponible" in client.get("/fr/").text


def test_hostile_release_data_is_escaped(client, settings):
    """Version, nom de fichier et notes viennent de la base : rien ne doit sortir en HTML brut, ni casser le
    JSON-LD."""
    conn = db.connect(settings)
    try:
        conn.execute("INSERT INTO releases (version, notes, mandatory, published_at) VALUES (?, ?, 0, ?)",
                     ("1.9.9", '<script>alert("xss")</script>', db.now_iso()))
        conn.execute("INSERT INTO release_assets (version, platform, filename, sha256, size) "
                     "VALUES (?, ?, ?, ?, ?)",
                     ("1.9.9", "windows-setup", '"><img src=x onerror=alert(1)></script>.exe', "0" * 64, 1234))
        conn.commit()
    finally:
        conn.close()
    for path in ("/fr/telecharger", "/en/whats-new", "/fr/"):
        html = client.get(path).text
        assert "<script>alert" not in html, path
        assert "<img src=x onerror" not in html, path
    html = client.get("/fr/telecharger").text
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in html
    # JSON-LD : `<` neutralisé, le nom de fichier est percent-encodé dans l'URL
    for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        assert "</" not in block
        json.loads(block)
    assert "%22%3E%3Cimg%20src%3Dx" in html


# --- Pages légales ------------------------------------------------------------------------------

def test_legal_pages_fr(client):
    for page_id, h1 in (("legal", "Mentions légales"), ("privacy", "Politique de confidentialité")):
        html = client.get(site.url_for("fr", page_id)).text
        assert f"<h1>{h1}</h1>" in html
        assert "[[À COMPLÉTER" not in html


def test_legal_identity_is_published(client):
    """LCEN art. 6-III : éditeur identifiable et hébergeur nommé ; RGPD art. 13 : responsable joignable."""
    mentions = client.get("/fr/mentions-legales").text
    for expected in ("Dorian Breuillard", "Cyber-Dodo", "925 110 132 00022", "Chambéry",
                     "contact@cyber-dodo.fr", "07 72 28 20 62", "293 B", "OUIHEBERG"):
        assert expected in mentions, expected
    conf = client.get("/fr/confidentialite").text
    for expected in ("Dorian Breuillard", "contact@cyber-dodo.fr", "Marseille"):
        assert expected in conf, expected
    # les autres langues publient la même identité (texte anglais)
    assert "925 110 132 00022" in client.get("/ja/legal-notice").text


def test_privacy_describes_the_real_data(client):
    html = client.get("/fr/confidentialite").text
    for expected in ("Identifiant Discord", "avatar", "SHA-256", "90 jours", "Signalements", "en mémoire vive",
                     "RGPD", "érification de mise à jour", "Mesure d'audience", "premier plan",
                     "Compteur de téléchargements", site.last_update("fr")):
        assert expected in html, expected


def test_terms_fr_and_en_come_from_the_markdown(client):
    """/fr/conditions depuis app/legal/CGU-fr.md (copie exacte de legal/CGU-fr.md) ; /en/terms depuis CGU-en.md
    avec « la version française fait foi » ; les autres langues reçoivent l'anglais."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("fr", "en"):
        server_copy = os.path.join(here, "..", "app", "legal", f"CGU-{lang}.md")
        root_copy = os.path.join(here, "..", "..", "legal", f"CGU-{lang}.md")
        with open(server_copy, encoding="utf-8") as f:
            md = f.read()
        if os.path.isfile(root_copy):
            with open(root_copy, encoding="utf-8") as f:
                assert f.read() == md, f"CGU-{lang}.md diffère de la racine : lance py .tools/make_legal.py"
    fr = client.get("/fr/conditions").text
    doc_fr = legal_md.load("fr")
    assert doc_fr["html"] in fr
    assert f"Version : {doc_fr['version']}" in fr
    assert "<!--" not in fr.split("<main", 1)[-1].split("</main>", 1)[0]
    assert f'<strong>{i18n.t("fr", "site.terms.prevails_title")}</strong>' not in fr   # pas de bandeau en français
    en = client.get("/en/terms").text
    assert legal_md.load("en")["html"] in en
    assert i18n.t("en", "site.terms.prevails_title") in en
    assert 'href="/fr/conditions"' in en
    th = client.get("/th/terms").text
    assert legal_md.load("en")["html"] in th


def test_no_external_resource_anywhere(client):
    """Aucune police, aucun script, aucune feuille de style servis par un tiers."""
    for lang in ("fr", "en", "ja"):
        for page_id in site.PAGE_IDS:
            html = client.get(site.url_for(lang, page_id)).text
            head = html.split("</head>", 1)[0]
            for bad in ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com",
                        "unpkg.com", "<script src", 'rel="stylesheet" href="http'):
                assert bad not in html, f"{bad} dans {page_id}/{lang}"
            # images locales seulement : /static, ou les vignettes de la galerie (aperçu de l'accueil compris)
            assert re.findall(r'<img[^>]+src="(?!/static/|/api/drawings/)', html) == [], page_id
            assert "http" not in "".join(re.findall(r'<link rel="(?:stylesheet|preload|icon)"[^>]*>', head))


def test_images_have_dimensions_and_alt(client):
    for lang in ("fr", "th"):
        for page_id in ("home", "music", "instruments"):
            html = client.get(site.url_for(lang, page_id)).text
            for tag in re.findall(r"<img[^>]*>", html):
                for attr in ("width=", "height=", "alt="):
                    assert attr in tag, (page_id, tag)


# --- SEO : sitemap, robots, images de partage -------------------------------------------------

def test_robots_txt(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "User-agent: *" in r.text and "Allow: /" in r.text and "Disallow: /api/" in r.text
    assert "Sitemap: http://testserver/sitemap.xml" in r.text


def test_sitemap_index_and_pages(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert "<sitemapindex" in r.text
    assert "<loc>http://testserver/sitemap-pages.xml</loc>" in r.text
    assert re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", r.text)
    r = client.get("/sitemap-pages.xml")
    assert r.status_code == 200
    urls = re.findall(r"<url>(.*?)</url>", r.text)
    assert len(urls) == len(site.PAGE_IDS) * len(LANGS)
    for page_id in site.PAGE_IDS:
        for lang in LANGS:
            assert f"<loc>http://testserver{site.url_for(lang, page_id)}</loc>" in r.text
    for u in urls:
        assert re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", u)
        assert u.count("<xhtml:link") == len(LANGS) + 1
    assert 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in r.text


def _png_size(path):
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", head[16:24])


def test_og_images_exist_for_every_page_and_language(client):
    for page_id in site.PAGE_IDS:
        for lang in LANGS:
            path = site.OG_DIR / f"{page_id}-{lang}.png"
            assert path.is_file(), path
            assert _png_size(path) == (1200, 630), path
    html = client.get("/de/herunterladen").text
    assert '<meta property="og:image" content="http://testserver/static/og/download-de.png?v=' in html
    assert '<meta property="og:image:width" content="1200">' in html
    assert '<meta property="og:image:height" content="630">' in html
    assert '<meta property="og:locale" content="de_DE">' in html
    assert html.count('<meta property="og:locale:alternate"') == len(LANGS) - 1


# --- Instruments -----------------------------------------------------------------------------
#
# Alimentée par la copie servie de `assets/instruments/catalogue.json` (voir `site_pages/instruments.py`).

# (la page dit, à la forme négative, « ne dit pas que tous les instruments sont compatibles » : autorisé)
FORBIDDEN = ("Tous les instruments sont compatibles", "testé dans Heartopia", "testés dans Heartopia",
             "validé dans le jeu", "validés dans le jeu", "63 instruments")


def catalogue():
    return inst_page.instrument_catalogue()


def test_instruments_page_lists_one_card_per_type(client):
    cat = catalogue()
    html = client.get("/fr/instruments").text
    assert html.count('<li class="inst">') == cat["total"] == len(cat["types"])
    assert html.count(">Piano</h3>") == 1
    for inst in cat["types"]:
        assert f">{inst['label_fr']}</h3>" in html, inst["id"]


def test_instruments_page_shows_instruments_without_jargon(client):
    """Demande du propriétaire (2026-09-21) : la page montre les instruments, sans l'état des profils de touches
    (« documenté », « candidat », « à relever »). Elle ne promet toujours rien de faux."""
    for path in ("/fr/instruments", "/fr/"):
        html = client.get(path).text
        for bad in FORBIDDEN:
            assert bad not in html, bad
        for state in inst_page.STATE_ORDER:
            assert inst_page.state_label("fr", state) not in html, (path, state)
        assert "profil de touches documenté" not in html and "pill--documented" not in html


def test_instruments_states_match_the_catalogue_data(client):
    cat = catalogue()
    counts = cat["counts"]
    assert sum(counts.values()) == cat["total"]
    by_id = {t["id"]: t for t in cat["types"]}
    for missing in ("xylophone", "saxophone", "harp", "steel-tongue-drum", "ocarina", "conch"):
        assert by_id[missing]["state"] == "unknown", missing
    for perc in ("conga", "cajon"):
        assert by_id[perc]["state"] == "candidate", perc
    assert by_id["piano"]["state"] == "documented"


def test_instruments_images_are_local_and_served(client):
    html = client.get("/en/instruments").text
    srcs = set(re.findall(r'<img[^>]+src="([^"]+)"', html))
    assert any(s.startswith("/static/instruments/") for s in srcs)
    for src in srcs:
        assert src.startswith("/static/"), src
        r = client.get(src)
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/"), src


def test_missing_image_falls_back_to_a_family_badge():
    html = inst_page.inst_media({"image": None, "category": "winds", "label_fr": "Conque", "label_en": "Conch"}, "fr")
    assert "inst__media--none" in html and 'role="img"' in html
    assert inst_page.FAMILY_FALLBACK["winds"] in html
    assert "saxophone" not in html.lower()


def test_no_variant_pages(client):
    for inst in catalogue()["types"][:3]:
        assert client.get(f"/fr/instruments/{inst['id']}").status_code == 404


def test_served_catalogue_copy_matches_the_repository():
    if not inst_page.REPO_INST_DIR.is_dir():
        pytest.skip("hors du dépôt : seule la copie de server/static est disponible")
    for name in ("catalogue.json", "layouts.json"):
        served, origin = inst_page.INST_DIR / name, inst_page.REPO_INST_DIR / name
        assert served.is_file(), f"copie manquante : {served}"
        assert served.read_bytes() == origin.read_bytes(), f"copie périmée : {name}"
    for origin in sorted(inst_page.REPO_IMG_DIR.glob("*.png")):
        served = inst_page.INST_DIR / origin.name
        assert served.is_file(), f"visuel manquant dans la copie : {origin.name}"
        assert served.read_bytes() == origin.read_bytes(), f"visuel périmé : {origin.name}"


def test_every_type_has_its_image_in_the_copy():
    cat = catalogue()
    urls = [t["image"]["url"] for t in cat["types"] if t["image"]]
    assert len(urls) == cat["total"]
    assert len(set(urls)) == cat["total"]


def test_home_announces_the_instrument_choice(client):
    cat = catalogue()
    html = client.get("/fr/").text
    assert 'id="choisir-instrument"' in html
    assert "<h2>Choisis ton instrument</h2>" in html
    assert 'href="/fr/instruments"' in html
    for bad in FORBIDDEN:
        assert bad not in html, bad
    assert html.count('src="/static/instruments/') >= 4
    assert str(cat["total"]) in html


def test_unreadable_catalogue_does_not_break_the_site(client, monkeypatch):
    monkeypatch.setattr(inst_page, "_CATALOGUE", dict(inst_page.EMPTY_CATALOGUE))
    site.invalidate(client.app)
    home = client.get("/fr/")
    assert home.status_code == 200 and 'id="choisir-instrument"' not in home.text
    r = client.get("/fr/instruments")
    assert r.status_code == 200 and "n'est pas consultable pour le moment" in r.text
    assert r.text.count("<h1") == 1


def test_instrument_layouts_are_described_from_the_data(client):
    cat = catalogue()
    html = client.get("/fr/instruments").text
    assert [lay["count"] for lay in cat["layouts"]] == [15, 15, 22, 37]
    for lay in cat["layouts"]:
        assert lay["id"] in html, lay["id"]
    assert "les deux dispositions à 15 notes ne diffèrent pas seulement par leur" in html


def test_instruments_page_keeps_the_visual_credits(client):
    html = client.get("/fr/instruments").text
    assert "Provenance des visuels" in html
    assert "build-heartopia.com" in html
    assert "licence de réutilisation libre" in html
    assert site.EDITEUR_COURRIEL in html


# --- Statiques ---------------------------------------------------------------------------------

def test_static_files(client):
    r = client.get("/static/site.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert "max-age" in r.headers["cache-control"]
    assert "--amber:#e8a531" in r.text and "prefers-color-scheme:dark" in r.text
    assert "unicode-range" in r.text and "prefers-reduced-motion" in r.text
    for path in ("/static/logo.png", "/static/favicon.ico", "/static/app-musique.png",
                 "/static/app-dessin.png", "/static/app-cuisine.png",
                 "/static/fonts/fredoka-latin.woff2", "/static/fonts/nunito-latin.woff2"):
        assert client.get(path).status_code == 200, path
    assert client.get("/static/fonts/nunito-latin.woff2").headers["content-type"] == "font/woff2"
    assert client.get("/favicon.ico").status_code == 200


def test_hashed_stylesheet_is_immutable(client):
    html = client.get("/fr/").text
    href = re.search(r'<link rel="stylesheet" href="(/static/site\.[0-9a-f]+\.css)">', html).group(1)
    r = client.get(href)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert "immutable" in r.headers["cache-control"]
    assert r.content == client.get("/static/site.css").content
    assert client.get("/static/site.0000000000.css").status_code == 404
    assert "immutable" in client.get("/static/logo.png?v=abc").headers["cache-control"]


def test_helpers():
    assert site.human_size(5 * 1024 * 1024) == "5,0 Mo"
    assert site.human_size(210 * 1024 * 1024) == "210 Mo"
    assert site.human_size(5 * 1024 * 1024, "en") == "5.0 MB"
    assert site.human_date("2026-09-14T10:00:00+00:00") == "14 septembre 2026"
    assert site.human_date("2026-09-14T10:00:00+00:00", "en") == "September 14, 2026"
    assert site.human_date("2026-09-14", "ja") == "2026年9月14日"
    assert site.human_date("pas une date") == ""
    assert site.dl_path("1.0.0", 'a"b.exe') == "/dl/1.0.0/a%22b.exe"
    assert i18n.negotiate("pt-BR") == "pt-BR" and i18n.negotiate("fr-CA") == "fr"


def test_plausible_new_style_script_is_initialised_with_the_csp_nonce(tmp_path):
    """Script Plausible `pa-<id>.js` : balise async + extrait `plausible.init()`, tous deux avec le nonce CSP,
    et l'hôte Plausible autorisé dans script-src et connect-src (sinon aucune visite n'est comptée)."""
    import re as _re
    from fastapi.testclient import TestClient as _TC
    from app.main import create_app as _create
    from tests.conftest import make_settings
    url = "https://plausible.example.org/js/pa-AbCdEf123.js"
    (tmp_path / "data").mkdir(exist_ok=True)
    with _TC(_create(make_settings(tmp_path, PLAUSIBLE_SCRIPT_URL=url))) as client:
        r = client.get("/fr/")
    csp = r.headers["content-security-policy"]
    nonce = _re.search(r"'nonce-([^']+)'", csp).group(1)
    head = r.text.split("</head>")[0]
    assert f'<script async nonce="{nonce}" src="{url}"></script>' in head
    assert f'<script nonce="{nonce}">window.plausible=' in head and "plausible.init()" in head
    assert "data-domain" not in head
    assert csp.count("https://plausible.example.org") == 2
