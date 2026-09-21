"""Ce que voient les navigateurs et les robots : fichiers servis sans gzip (Content-Length, Range), HEAD sur le site,
index du sitemap sans enfant vide, notes de version rendues depuis le Markdown, IndexNow.

Le client de test décompresse en silence : les tests de compression ne regardent que les EN-TÊTES."""
import re

import httpx
import pytest
from conftest import bearer, make_client, make_settings
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from app import db, i18n, indexnow, main, site
from test_announce import FakePost
from test_public_pages import approved_drawing, approved_song
from test_site import put_and_publish

LANGS = i18n.LANGS
GZIP = {"Accept-Encoding": "gzip"}
KEY = "0123456789abcdef0123456789abcdef"


def small_release(client, publish_headers, version="2.0.0", notes=""):
    """Petits binaires très compressibles (> 1 Kio) : gzip les prendrait s'ils n'étaient pas exclus."""
    return put_and_publish(client, publish_headers, version, notes=notes,
                           setup=b"S" * 5000, linux=b"L" * 6000, portable=b"P" * 7000)


# --- 1. Fichiers : jamais de gzip -------------------------------------------------------------------------------

def assert_plain_file(client, url, size=None, headers=None):
    r = client.get(url, headers={**GZIP, **(headers or {})})
    assert r.status_code == 200, (url, r.text)
    assert "content-encoding" not in r.headers, url
    assert "transfer-encoding" not in r.headers, url
    assert r.headers["accept-ranges"] == "bytes", url
    if size is None:
        size = len(r.content)
    assert int(r.headers["content-length"]) == size == len(r.content), url
    part = client.get(url, headers={**GZIP, **(headers or {}), "Range": "bytes=10-109"})
    assert part.status_code == 206, url
    assert "content-encoding" not in part.headers
    assert part.headers["content-length"] == "100" and len(part.content) == 100
    assert part.headers["content-range"] == f"bytes 10-109/{size}"
    return r


def test_release_files_are_served_without_gzip(client, publish_headers):
    sizes = small_release(client, publish_headers)
    r = assert_plain_file(client, "/dl/2.0.0/DodoTopia-2.0.0-linux-x64.tar.gz", sizes["linux-x64"])
    assert r.content == b"L" * 6000                      # l'archive telle quelle, pas un flux recompressé
    assert_plain_file(client, "/dl/2.0.0/DodoTopia-2.0.0-Setup.exe", sizes["windows-setup"])
    assert_plain_file(client, "/dl/2.0.0/DodoTopia-2.0.0-portable.zip", sizes["windows-portable"])


def test_song_and_drawing_files_are_served_without_gzip(client, user_token, admin_token):
    sid = approved_song(client, user_token, admin_token, n_notes=400)
    r = assert_plain_file(client, f"/api/songs/{sid}/download")
    assert len(r.content) > 1024 and r.content[:4] == b"MThd"
    did = approved_drawing(client, user_token, admin_token)
    for url in (f"/api/drawings/{did}.png", f"/api/drawings/{did}/thumb.png"):
        r = client.get(url, headers=GZIP)
        assert r.status_code == 200 and "content-encoding" not in r.headers
        assert int(r.headers["content-length"]) == len(r.content) and r.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize("path, skipped", [
    ("/dl/2.0.0/DodoTopia-2.0.0-linux-x64.tar.gz", True),
    ("/api/import/abcDEF123", True),
    ("/api/songs/12/download", True),
    ("/api/drawings/7.png", True),
    ("/api/drawings/7/thumb.png", True),
    ("/api/rooms/ABCD/song/" + "0" * 64, True),
    ("/api/import", False),
    ("/api/songs/12", False),
    ("/api/songs", False),
    ("/api/drawings/7", False),
    ("/api/drawings/7/cells", False),
    ("/api/rooms/ABCD/song", False),
    ("/fr/telecharger", False),
    ("/sitemap.xml", False),
])
def test_gzip_bypass_paths(path, skipped):
    assert bool(main.NO_GZIP_PATH.match(path)) is skipped


def test_selective_gzip_bypasses_by_path_and_by_content_type():
    """Le contournement par chemin vaut quel que soit le type ; les types binaires sont exclus quel que soit le
    chemin."""
    async def inner(scope, receive, send):
        media = {"/bin": "application/octet-stream", "/tar": "application/x-tar", "/ico": "image/x-icon"}
        response = PlainTextResponse("x" * 5000, media_type=media.get(scope["path"], "text/plain"))
        await response(scope, receive, send)

    c = TestClient(main.SelectiveGZipMiddleware(inner, minimum_size=1024))
    assert c.get("/page", headers=GZIP).headers.get("content-encoding") == "gzip"
    for path in ("/dl/1.0.0/a.tar.gz", "/api/songs/3/download", "/bin", "/tar", "/ico"):
        r = c.get(path, headers=GZIP)
        assert "content-encoding" not in r.headers and r.headers["content-length"] == "5000", path


def test_pages_and_json_are_still_gzipped(client, publish_headers):
    small_release(client, publish_headers)
    for path in ("/fr/", "/fr/telecharger", "/sitemap-pages.xml", "/api/releases"):
        raw = client.get(path, headers={"Accept-Encoding": "identity"})
        assert len(raw.content) > 1024 and "content-encoding" not in raw.headers, path
        r = client.get(path, headers=GZIP)
        assert r.headers.get("content-encoding") == "gzip", path
        assert "accept-encoding" in r.headers.get("vary", "").lower(), path


# --- 2. HEAD -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/fr/", "/en/help", "/robots.txt", "/sitemap.xml", "/sitemap-pages.xml",
                                  "/sitemap-songs.xml", "/api/health", "/favicon.ico"])
def test_head_answers_like_get_without_body(client, path):
    r = client.head(path)
    assert r.status_code == 200, path
    assert int(r.headers["content-length"]) > 0 and r.content == b"", path
    get = client.get(path)
    assert r.headers["content-type"] == get.headers["content-type"], path
    assert r.headers.get("content-encoding") == get.headers.get("content-encoding"), path
    assert "content-security-policy" in r.headers and "x-robots-tag" not in r.headers


def test_head_has_the_exact_length_of_get(client):
    for headers in ({"Accept-Encoding": "identity"}, GZIP):          # robots.txt : sous 1 Kio, jamais compressé
        get = client.get("/robots.txt", headers=headers)
        head = client.head("/robots.txt", headers=headers)
        assert head.headers["content-length"] == get.headers["content-length"] == str(len(get.content))
    get = client.get("/sitemap-pages.xml", headers=GZIP)             # compressé : longueur du corps gzip
    head = client.head("/sitemap-pages.xml", headers=GZIP)
    assert head.headers["content-encoding"] == "gzip"
    assert head.headers["content-length"] == get.headers["content-length"]


def test_head_on_redirects_and_not_found(client):
    r = client.head("/", headers={"Accept-Language": "fr"})
    assert r.status_code == 302 and r.headers["location"] == "/fr/"
    r = client.head("/fr")
    assert r.status_code == 301 and r.headers["location"] == "/fr/"
    r = client.head("/instruments")
    assert r.status_code == 301 and r.headers["location"] == "/fr/instruments"
    r = client.head("/fr/nexiste-pas")
    assert r.status_code == 404 and r.content == b"" and r.headers["content-type"].startswith("text/html")


def test_head_leaves_the_api_alone_and_counts_no_download(client, publish_headers, settings):
    sizes = small_release(client, publish_headers)
    assert client.head("/api/songs").status_code == 405
    assert client.head("/api/stats").status_code == 405
    assert client.head("/telecharger/go/windows").status_code == 405      # lien compteur : GET seulement
    r = client.head("/dl/2.0.0/DodoTopia-2.0.0-Setup.exe", headers=GZIP)
    assert r.status_code == 200 and r.content == b""
    assert int(r.headers["content-length"]) == sizes["windows-setup"]
    assert r.headers["accept-ranges"] == "bytes" and "content-encoding" not in r.headers
    assert client.head("/dl/2.0.0/absent.exe").status_code == 404
    conn = db.connect(settings)
    try:
        assert conn.execute("SELECT SUM(downloads) FROM release_assets").fetchone()[0] == 0
    finally:
        conn.close()


# --- 3. Sitemaps --------------------------------------------------------------------------------------------------

def sitemap_entries(xml: str) -> dict:
    """{nom du sitemap enfant: lastmod} de l'index ; toute entrée sans <lastmod> fait échouer l'appelant."""
    entries = re.findall(r"<sitemap><loc>http://testserver/([^<]+)</loc>(?:<lastmod>([^<]*)</lastmod>)?</sitemap>", xml)
    assert len(entries) == xml.count("<sitemap>")
    return dict(entries)


def test_sitemap_index_lists_only_non_empty_children(client, user_token, admin_token):
    assert list(sitemap_entries(client.get("/sitemap.xml").text)) == ["sitemap-pages.xml"]
    approved_song(client, user_token, admin_token, n_notes=20, title="Trop court")     # `noindex` : hors sitemap
    assert list(sitemap_entries(client.get("/sitemap.xml").text)) == ["sitemap-pages.xml"]
    approved_drawing(client, user_token, admin_token)
    entries = sitemap_entries(client.get("/sitemap.xml").text)
    assert list(entries) == ["sitemap-pages.xml", "sitemap-gallery.xml"]
    approved_song(client, user_token, admin_token, n_notes=60)
    entries = sitemap_entries(client.get("/sitemap.xml").text)
    assert list(entries) == ["sitemap-pages.xml", "sitemap-songs.xml", "sitemap-gallery.xml"]
    today = db.now_iso()[:10]
    assert entries["sitemap-songs.xml"] == today and entries["sitemap-gallery.xml"] == today
    for lastmod in entries.values():
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", lastmod)


def test_sitemaps_are_utf8_xml_and_indexable(client):
    for path in ("/sitemap.xml", "/sitemap-pages.xml", "/sitemap-songs.xml", "/sitemap-gallery.xml"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"] == "application/xml; charset=utf-8", path
        assert "x-robots-tag" not in r.headers, path
        assert r.text.startswith('<?xml version="1.0" encoding="UTF-8"?>'), path
    empty = client.get("/sitemap-songs.xml").text
    assert "<urlset" in empty and "</urlset>" in empty and "<url>" not in empty


# --- 4. Notes de version ------------------------------------------------------------------------------------------

NOTES = ("# Grand titre\n"
         "- **Huit langues** : français, anglais, et six en bêta.\n"
         "- Liens `dodotopia://` et \"guillemets\" <b>pas de HTML</b>.\n"
         "- Voir [le site](https://dodotopia.cyber-dodo.fr/fr/aide).\n")


def notes_block(html: str) -> str:
    return re.search(r'<(?:div|article) class="newsitem".*?</(?:div|article)>', html, re.S).group(0)


def test_release_notes_are_rendered_from_markdown(client, publish_headers):
    small_release(client, publish_headers, notes=NOTES)
    for path in ("/fr/telecharger", "/fr/nouveautes", "/ja/whats-new"):
        block = notes_block(client.get(path).text)
        assert "<strong>Huit langues</strong>" in block, path
        assert "**" not in block and "`" not in block, path
        assert "<code>dodotopia://</code>" in block
        assert "&quot;guillemets&quot; &lt;b&gt;pas de HTML&lt;/b&gt;" in block
        assert '<a href="https://dodotopia.cyber-dodo.fr/fr/aide" rel="noopener">le site</a>' in block
        assert "<h4>Grand titre</h4>" in block and "<h1>" not in block
        assert block.count("<li>") == 3


def test_release_notes_are_cut_before_conversion(client, publish_headers):
    notes = "\n".join(f"- **point {i}**" for i in range(1, 16))
    small_release(client, publish_headers, notes=notes)
    block = notes_block(client.get("/fr/telecharger").text)
    assert block.count("<li>") == 12 and block.count("<ul>") == block.count("</ul>") == 1
    assert "<strong>point 12</strong>" in block and "point 13" not in block
    assert i18n.t("fr", "site.download.notes_more") in block
    assert notes_block(client.get("/fr/nouveautes").text).count("<li>") == 15


def test_notes_html_unit():
    assert site.notes_html("") == "" and site.notes_html(None) == "" and site.notes_html(" \n\n") == ""
    assert site.notes_html("## a\n### b\n#### c") == "<h4>a</h4>\n<h4>b</h4>\n<h4>c</h4>"
    assert site.notes_html("• puce\n• autre") == "<ul>\n<li>puce</li>\n<li>autre</li>\n</ul>"
    assert site.notes_html("- a\n\n- b\n- c", max_items=2) == "<ul>\n<li>a</li>\n</ul>\n<ul>\n<li>b</li>\n</ul>"
    assert site.notes_line_count("- a\n\n- b\n- c") == 3
    hostile = site.notes_html('[x](https://a.b/"onmouseover="alert(1)) <script>alert("xss")</script>')
    assert '"onmouseover' not in hostile and "<script" not in hostile
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in hostile


# --- 5. IndexNow ---------------------------------------------------------------------------------------------------

@pytest.fixture
def fake_post(monkeypatch):
    fake = FakePost(status=200)
    monkeypatch.setattr(indexnow.httpx, "post", fake)
    return fake


def test_indexnow_key_file(tmp_path):
    with make_client(make_settings(tmp_path, INDEXNOW_KEY=KEY)) as c:
        r = c.get(f"/{KEY}.txt")
        assert r.status_code == 200 and r.text == KEY and r.headers["content-type"].startswith("text/plain")
        assert c.head(f"/{KEY}.txt").status_code == 200
        assert c.get("/autre-cle-0123456789.txt").status_code == 404
        assert "Sitemap:" in c.get("/robots.txt").text                    # robots.txt n'est pas masqué par la route


@pytest.mark.parametrize("key", ["", "court", "clé avec espaces et accents"])
def test_indexnow_disabled_without_a_valid_key(tmp_path, fake_post, key):
    settings = make_settings(tmp_path, INDEXNOW_KEY=key)
    assert settings.indexnow_key == ""
    with make_client(settings) as c:
        small_release(c, {"X-Publish-Token": settings.PUBLISH_TOKEN})
        assert c.get(f"/{key or 'x'}.txt").status_code == 404
    assert fake_post.calls == []
    assert indexnow.submit(settings, ["http://testserver/fr/"]) is False


def test_indexnow_pings_once_on_publish(tmp_path, fake_post):
    settings = make_settings(tmp_path, INDEXNOW_KEY=KEY)
    with make_client(settings) as c:
        small_release(c, {"X-Publish-Token": settings.PUBLISH_TOKEN})
    assert len(fake_post.calls) == 1
    call = fake_post.calls[0]
    assert call["url"] == "https://api.indexnow.org/indexnow" and call["timeout"] == 10
    body = call["json"]
    assert body["host"] == "testserver" and body["key"] == KEY
    assert body["keyLocation"] == f"http://testserver/{KEY}.txt"
    assert len(body["urlList"]) == 3 * len(LANGS) == len(set(body["urlList"]))
    for url in ("http://testserver/fr/", "http://testserver/fr/telecharger", "http://testserver/en/whats-new",
                "http://testserver/pt-BR/baixar"):
        assert url in body["urlList"]


def test_indexnow_pings_on_approval(tmp_path, fake_post):
    from conftest import login
    settings = make_settings(tmp_path, INDEXNOW_KEY=KEY)
    with make_client(settings) as c:
        user, admin = login(c, "111")[0], login(c, "999")[0]
        did = approved_drawing(c, user, admin)
        assert len(fake_post.calls) == 1
        urls = fake_post.calls[0]["json"]["urlList"]
        assert len(urls) == len(LANGS) and f"http://testserver/fr/galerie/{did}" in urls
        assert c.post(f"/api/admin/drawings/{did}/approve", headers=bearer(admin)).status_code == 200
        assert len(fake_post.calls) == 1                                  # déjà approuvé : pas de second signalement
        sid = approved_song(c, user, admin, n_notes=60, title="Clair de lune")
        assert len(fake_post.calls) == 2
        urls = fake_post.calls[1]["json"]["urlList"]
        assert len(urls) == len(LANGS) and f"http://testserver/en/songs/{sid}-clair-de-lune" in urls
        approved_song(c, user, admin, n_notes=20, title="Trop court")     # fiche `noindex` : rien à signaler
        assert len(fake_post.calls) == 2


@pytest.mark.parametrize("fake", [FakePost(status=500), FakePost(exc=httpx.ConnectError("réseau"))])
def test_indexnow_failure_never_breaks_the_request(tmp_path, monkeypatch, fake):
    monkeypatch.setattr(indexnow.httpx, "post", fake)
    settings = make_settings(tmp_path, INDEXNOW_KEY=KEY)
    with make_client(settings) as c:
        small_release(c, {"X-Publish-Token": settings.PUBLISH_TOKEN})     # la publication répond 200 malgré l'échec
        assert c.get("/api/releases/latest").json()["version"] == "2.0.0"
    assert len(fake.calls) == 1
