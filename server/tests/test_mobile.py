"""Canal Android : dépôt de l'APK, publication, latest, téléchargement compté, lien `/telecharger/go/android`,
carte de la page Téléchargement, page Android (SEO, JSON-LD), sitemap. Les versions PC ne bougent pas."""
import hashlib
import json
import re
from html import unescape

import pytest

from app import db, i18n, site
from app.mobile_releases import APK_MEDIA_TYPE
from test_site import put_and_publish

LANGS = i18n.LANGS
APK = b"PK\x03\x04" + b"A" * (5 * 1024 * 1024 + 3)


def put_apk(client, headers, version="0.3.0", data=APK, filename=None, sha=None):
    filename = filename or f"DodoTopia-Mobile-{version}.apk"
    sha = sha or hashlib.sha256(data).hexdigest()
    return client.put(f"/api/admin/mobile/releases/{version}/apk", content=data,
                      headers={**headers, "X-Sha256": sha, "X-Filename": filename})


def publish_apk(client, headers, version="0.3.0", data=APK, notes=""):
    assert put_apk(client, headers, version, data).status_code == 200
    r = client.post(f"/api/admin/mobile/releases/{version}/publish", headers=headers, json={"notes": notes})
    assert r.status_code == 200, r.text
    return r.json()


def downloads(settings, version="0.3.0") -> int:
    conn = db.connect(settings)
    try:
        return conn.execute("SELECT downloads FROM mobile_releases WHERE version=?", (version,)).fetchone()["downloads"]
    finally:
        conn.close()


def ld_nodes(html: str) -> list[dict]:
    nodes = []
    for raw in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        data = json.loads(raw)
        nodes.extend(data.get("@graph", [data]))
    return nodes


# --- Dépôt et publication -------------------------------------------------------------------------

def test_deposit_requires_the_publish_token_and_valid_headers(client, publish_headers, settings):
    assert put_apk(client, {}).status_code == 403
    assert put_apk(client, {"X-Publish-Token": "faux"}).status_code == 403
    r = put_apk(client, publish_headers, sha="0" * 64)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "sha_mismatch"
    assert not list((settings.releases_dir / "android" / "0.3.0").glob("*"))        # ni fichier, ni .part
    r = client.put("/api/admin/mobile/releases/0.3.0/apk", content=b"abc", headers=publish_headers)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_sha256"
    for bad in ("../evil.apk", "DodoTopia.exe", ".cache.apk", "a.apk.part"):
        r = put_apk(client, publish_headers, filename=bad)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_filename", bad
    assert put_apk(client, publish_headers, version="v3").status_code == 422
    assert put_apk(client, publish_headers, data=b"").status_code == 400
    assert client.post("/api/admin/mobile/releases/0.3.0/publish", json={}).status_code == 403
    r = client.post("/api/admin/mobile/releases/0.3.0/publish", headers=publish_headers, json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "missing_asset"
    assert client.get("/api/mobile/latest").status_code == 404


def test_publish_flow_and_latest(client, publish_headers, settings):
    r = client.get("/api/mobile/latest")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_release"

    r = put_apk(client, publish_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"version": "0.3.0", "filename": "DodoTopia-Mobile-0.3.0.apk",
                        "sha256": hashlib.sha256(APK).hexdigest(), "size": len(APK),
                        "url": "http://testserver/dl/android/0.3.0/DodoTopia-Mobile-0.3.0.apk"}
    assert (settings.releases_dir / "android" / "0.3.0" / "DodoTopia-Mobile-0.3.0.apk").read_bytes() == APK
    assert put_apk(client, publish_headers).status_code == 200                      # idempotent

    # déposée mais pas publiée : invisible, et le fichier ne se télécharge pas
    assert client.get("/api/mobile/latest").status_code == 404
    assert client.get("/dl/android/0.3.0/DodoTopia-Mobile-0.3.0.apk").status_code == 404

    m = publish_apk(client, publish_headers, notes="Première version")
    assert m["version"] == "0.3.0" and m["published_at"] and m["notes"] == "Première version"
    latest = client.get("/api/mobile/latest?current=0.2.0").json()
    assert latest["update_available"] is True and latest["size"] == len(APK)
    assert latest["sha256"] == hashlib.sha256(APK).hexdigest()
    assert latest["url"] == "http://testserver/dl/android/0.3.0/DodoTopia-Mobile-0.3.0.apk"
    assert client.get("/api/mobile/latest?current=0.3.0").json()["update_available"] is False
    assert client.get("/api/mobile/latest").json()["update_available"] is False
    assert client.get("/api/mobile/latest?current=abc").status_code == 422

    # le tri suit le numéro de version, pas l'ordre de publication
    publish_apk(client, publish_headers, "0.10.0", b"NEW" * 10)
    publish_apk(client, publish_headers, "0.4.0", b"MID" * 10)
    assert client.get("/api/mobile/latest").json()["version"] == "0.10.0"

    # republier garde la date de première publication ; redéposer sous un autre nom retire l'ancien fichier
    first = client.get("/api/mobile/latest").json()["published_at"]
    assert put_apk(client, publish_headers, "0.10.0", b"FIX" * 10, "DodoTopia-Mobile-0.10.0-b.apk").status_code == 200
    assert not (settings.releases_dir / "android" / "0.10.0" / "DodoTopia-Mobile-0.10.0.apk").exists()
    again = client.post("/api/admin/mobile/releases/0.10.0/publish", headers=publish_headers, json={"notes": "n"})
    assert again.json()["published_at"] == first and again.json()["filename"] == "DodoTopia-Mobile-0.10.0-b.apk"

    # suppression
    assert client.delete("/api/admin/mobile/releases/0.10.0").status_code == 403
    assert client.delete("/api/admin/mobile/releases/0.10.0", headers=publish_headers).status_code == 200
    assert not (settings.releases_dir / "android" / "0.10.0").exists()
    assert client.get("/api/mobile/latest").json()["version"] == "0.4.0"
    assert client.delete("/api/admin/mobile/releases/0.10.0", headers=publish_headers).status_code == 404


def test_pc_channel_is_untouched(client, publish_headers):
    """L'Updater PC ne doit rien voir du canal Android : ni version, ni asset, ni manifeste modifié."""
    put_and_publish(client, publish_headers, "1.7.0")
    before = client.get("/api/releases/latest?current=1.6.0&platform=windows-setup").json()
    publish_apk(client, publish_headers, "9.9.9")
    after = client.get("/api/releases/latest?current=1.6.0&platform=windows-setup").json()
    assert after == before and after["version"] == "1.7.0"
    assert set(after["assets"]) == {"windows-setup", "windows-portable", "linux-x64"}
    assert [x["version"] for x in client.get("/api/releases").json()["items"]] == ["1.7.0"]
    assert client.get("/api/releases/9.9.9").status_code == 404
    assert client.get("/api/stats").json()["downloads_total"] == 0
    # et l'inverse : supprimer la version PC laisse l'APK en place
    assert client.delete("/api/admin/releases/1.7.0", headers=publish_headers).status_code == 200
    assert client.get("/api/mobile/latest").json()["version"] == "9.9.9"


# --- Téléchargement --------------------------------------------------------------------------------

def test_apk_download_type_range_and_counter(client, publish_headers, settings):
    publish_apk(client, publish_headers)
    url = "/dl/android/0.3.0/DodoTopia-Mobile-0.3.0.apk"
    r = client.get(url, headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.content == APK
    assert r.headers["content-type"] == APK_MEDIA_TYPE == "application/vnd.android.package-archive"
    assert "content-encoding" not in r.headers and r.headers["content-length"] == str(len(APK))
    assert r.headers["accept-ranges"] == "bytes"
    assert 'filename="DodoTopia-Mobile-0.3.0.apk"' in r.headers["content-disposition"]
    assert downloads(settings) == 1
    r = client.get(url, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == APK[10:20]
    assert downloads(settings) == 1                                   # reprise au milieu : même téléchargement
    r = client.head(url)
    assert r.status_code == 200 and not r.content and r.headers["content-length"] == str(len(APK))
    assert downloads(settings) == 1                                   # HEAD : rien de compté
    assert client.get(url + "?via=site").status_code == 200
    assert downloads(settings) == 1                                   # déjà compté par /telecharger/go/android
    for bad in ("/dl/android/0.3.0/absent.apk", "/dl/android/0.3.0/..%2Fdodo.db", "/dl/android/0.9.0/x.apk"):
        r = client.get(bad)
        assert r.status_code == 404 and r.headers["content-type"].startswith("application/json"), bad
    assert client.get("/api/mobile/latest").json()["downloads"] == 1


def test_download_go_android_redirects_and_counts(client, publish_headers, settings):
    assert client.get("/telecharger/go/android").status_code == 404
    publish_apk(client, publish_headers)
    r = client.get("/telecharger/go/android")
    assert r.status_code == 302
    assert r.headers["location"] == "/dl/android/0.3.0/DodoTopia-Mobile-0.3.0.apk?via=site"
    assert r.headers["cache-control"] == "no-store"
    assert client.get(r.headers["location"]).status_code == 200       # servi sans double comptage
    assert downloads(settings) == 1
    assert client.head("/telecharger/go/android").status_code in (302, 405)
    assert downloads(settings) == 1                                   # une vérification de lien ne compte pas
    assert client.get("/telecharger/go/windows").status_code == 404   # aucune version PC : inchangé
    # statistiques du jour : plateforme « android », à côté des plateformes PC
    counts = client.app.state.stats._counts
    assert sum(n for (_day, key, dim), n in counts.items() if key == "dl_app" and dim == "android") == 1
    robots = client.get("/robots.txt").text
    assert "Disallow: /dl/" in robots and "Disallow: /telecharger/go/" in robots


# --- Page Téléchargement -----------------------------------------------------------------------------

def test_download_page_android_card(client, publish_headers):
    html = client.get("/fr/telecharger").text
    card = html.split('<div class="dlcard dlcard--none dlcard--android" id="android">', 1)[1].split("</div>", 1)[0]
    assert "arrive bientôt" in card and 'href="/fr/android"' in card
    assert "/telecharger/go/" not in html and "/dl/" not in html      # jamais de lien mort
    assert 'class="faq__body" id="apk"' in html and "Autoriser les paramètres restreints" in html
    assert "installer des applis inconnues" in html and "service d'accessibilité" in html

    publish_apk(client, publish_headers)
    html = client.get("/fr/telecharger").text
    card = html.split('<div class="dlcard dlcard--android reveal" id="android">', 1)[1].split("</div>", 1)[0]
    assert 'href="/telecharger/go/android"' in card and "Dernière version : 0.3.0" in card
    assert site.human_size(len(APK)) in card and "DodoTopia-Mobile-0.3.0.apk" in card
    sha = hashlib.sha256(APK).hexdigest()
    assert sha in card and f"https://www.virustotal.com/gui/file/{sha}" in card
    assert "Bientôt disponible" in html                                # toujours aucune version PC
    assert "/telecharger/go/windows" not in html
    # avec une version PC : les trois cartes PC et la carte Android cohabitent
    put_and_publish(client, publish_headers, "2.0.0")
    html = client.get("/en/download").text
    assert html.count('<li class="dlcard') == 3 and html.count('<details class="dlcard__tech">') == 4
    assert 'href="/telecharger/go/android"' in html and 'href="/en/android"' in html
    assert "Allow restricted settings" in html


def test_hostile_mobile_data_is_escaped(client, settings):
    conn = db.connect(settings)
    try:
        conn.execute("INSERT INTO mobile_releases (version, filename, sha256, size, notes, published_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     ("0.3.0", 'x"><script>alert(1)</script>.apk', "f" * 64, 10, "", "2026-10-03T10:00:00Z"))
        conn.commit()
    finally:
        conn.close()
    site.invalidate(client.app)
    for path in ("/fr/telecharger", "/fr/android"):
        html = client.get(path).text
        assert "<script>alert(1)" not in html, path
        assert "&lt;script&gt;alert(1)" in html or "%3Cscript%3E" in html, path


# --- Page Android -------------------------------------------------------------------------------------

def test_android_page_in_every_language(client, publish_headers):
    titles, descriptions = set(), set()
    for lang in LANGS:
        path = f"/{lang}/android"
        assert site.url_for(lang, "android") == path
        r = client.get(path)
        assert r.status_code == 200, path
        html = r.text
        assert f'<html lang="{lang}">' in html and html.count("<h1") == 1 and "[site." not in html, path
        assert f'<link rel="canonical" href="http://testserver{path}">' in html
        alts = dict(re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', html))
        assert alts == {**{code: f"http://testserver/{code}/android" for code in LANGS},
                        "x-default": "http://testserver/en/android"}
        title = re.search(r"<title>([^<]*)</title>", html).group(1)
        desc = unescape(re.search(r'<meta name="description" content="([^"]*)">', html).group(1))
        assert "Android" in title and "Heartopia" in title and len(title) <= 60, (lang, title)
        assert 50 <= len(desc) <= 160 and "Heartopia" in desc, (lang, len(desc))
        titles.add(title)
        descriptions.add(desc)
        assert f'<meta property="og:image" content="http://testserver/static/og/android-{lang}.png?v=' in html
        assert '<meta name="robots" content="index, follow, max-image-preview:large">' in html
        assert html.count('<li class="step">') == 3 and 'id="etapes"' in html
        assert "/telecharger/go/" not in html                          # rien de publié : aucun lien de téléchargement
        assert f'href="{site.url_for(lang, "download")}#apk"' in html
        # liée depuis le pied de page de tout le site
        assert f'<li><a href="{path}">Android</a></li>' in client.get(site.url_for(lang, "help")).text
        nodes = ld_nodes(html)
        app_node = next(n for n in nodes if n.get("@type") == "SoftwareApplication")
        assert app_node["operatingSystem"] == "Android" and app_node["url"] == f"http://testserver{path}"
        assert app_node["author"]["@id"] == "http://testserver/#organization"
        assert "softwareVersion" not in app_node and "downloadUrl" not in app_node
        assert not {"aggregateRating", "review"} & set(app_node)       # ni note ni avis inventés
        assert [n for n in nodes if n.get("@type") == "FAQPage"] and [n for n in nodes if n.get("@type") == "BreadcrumbList"]
    assert len(titles) == len(LANGS) and len(descriptions) == len(LANGS)

    publish_apk(client, publish_headers)
    html = client.get("/fr/android").text
    assert html.count('href="/telecharger/go/android"') == 2          # en-tête et bas de page
    assert site.human_size(len(APK)) in html and "Dernière version : 0.3.0" in html
    app_node = next(n for n in ld_nodes(html) if n.get("@type") == "SoftwareApplication")
    assert app_node["softwareVersion"] == "0.3.0" and app_node["fileSize"] == str(len(APK))
    assert app_node["downloadUrl"] == "http://testserver/dl/android/0.3.0/DodoTopia-Mobile-0.3.0.apk"
    assert app_node["offers"]["price"] == "0"
    assert client.delete("/api/admin/mobile/releases/0.3.0", headers=publish_headers).status_code == 200
    assert "/telecharger/go/android" not in client.get("/fr/android").text      # cache invalidé


def test_android_page_promises_only_music(client):
    """Dessin et cuisine ne sont pas sur mobile : la page le dit, et ne propose pas de les télécharger."""
    html = client.get("/fr/android").text
    main = html.split("<main", 1)[1].split("</main>", 1)[0]
    assert "Le dessin et la cuisine ne sont pas encore dans l'appli Android" in main
    assert "Play Store" in main and "Confidentialité" in main and "Android 8.0" in main
    assert 'href="/fr/telecharger#apk"' in main and 'href="/fr/confidentialite"' in main
    en = client.get("/en/android").text.split("<main", 1)[1].split("</main>", 1)[0]
    assert 'href="/fr/' not in en and 'href="/en/download#apk"' in en and 'href="/en/privacy"' in en


def test_android_short_url_and_foreign_slug(client):
    r = client.get("/android", headers={"Accept-Language": "de-DE,de;q=0.9"})
    assert r.status_code == 302 and r.headers["location"] == "/de/android"
    assert client.get("/android").headers["location"] == "/en/android"
    assert client.get("/fr/android/").headers["location"] == "/fr/android"
    assert client.get("/instruments").headers["location"] == "/fr/instruments"   # les anciennes URL ne bougent pas


@pytest.mark.parametrize("key", [
    "site.nav.android", "site.meta.android.title", "site.meta.android.description", "site.android.h1",
    "site.android.lead", "site.android.what_body", "site.android.need.4", "site.android.step.3.text",
    "site.android.later_text", "site.android.privacy_text", "site.android.store_text", "site.android.faq.4.a",
    "site.download.android.title", "site.download.android.desc", "site.download.android.button",
    "site.download.android.soon", "site.download.apk_title", "site.download.apk_text",
    "site.download.apk_access", "site.download.apk_restricted",
])
def test_android_keys_are_translated_everywhere(key):
    values = set()
    for lang in LANGS:
        assert i18n.has(lang, key, strict=True), (lang, key)
        values.add(i18n.catalogue(lang)[key])
    if key not in ("site.nav.android", "site.download.android.title"):       # « Android », « APK » : invariables
        assert len(values) == len(LANGS), key


# --- Sitemap et IndexNow --------------------------------------------------------------------------------

def test_sitemap_lists_the_android_page(client, publish_headers):
    xml = client.get("/sitemap-pages.xml").text
    for lang in LANGS:
        assert f"<loc>http://testserver/{lang}/android</loc>" in xml
    entry = next(u for u in re.findall(r"<url>(.*?)</url>", xml) if "<loc>http://testserver/fr/android</loc>" in u)
    assert f"<lastmod>{site.ANDROID_PAGE_ISO}</lastmod>" in entry and "<priority>0.8</priority>" in entry
    assert entry.count("<xhtml:link") == len(LANGS) + 1
    conn = db.connect(client.app.state.settings)
    try:
        conn.execute("INSERT INTO mobile_releases (version, filename, sha256, size, published_at) "
                     "VALUES ('0.4.0', 'a.apk', ?, 3, '2031-02-03T10:00:00Z')", ("a" * 64,))
        conn.commit()
    finally:
        conn.close()
    xml = client.get("/sitemap-pages.xml").text
    entry = next(u for u in re.findall(r"<url>(.*?)</url>", xml) if "<loc>http://testserver/fr/android</loc>" in u)
    assert "<lastmod>2031-02-03</lastmod>" in entry


def test_indexnow_pings_android_pages_on_publish(tmp_path, monkeypatch):
    from conftest import PUBLISH_TOKEN, make_client, make_settings
    from app import indexnow
    calls = []

    class Reply:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(indexnow.httpx, "post", lambda url, **kw: calls.append(kw["json"]) or Reply())
    headers = {"X-Publish-Token": PUBLISH_TOKEN}
    with make_client(make_settings(tmp_path, INDEXNOW_KEY="0123456789abcdef0123456789abcdef")) as client:
        publish_apk(client, headers)
    assert len(calls) == 1
    urls = calls[0]["urlList"]
    assert len(urls) == 2 * len(LANGS) == len(set(urls))
    assert "http://testserver/fr/android" in urls and "http://testserver/de/herunterladen" in urls
