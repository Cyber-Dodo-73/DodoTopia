"""Revue locale : lint SEO du site public (toutes pages × toutes langues) et revue visuelle de l'interface.

    py .tools/ux_check.py --seo     lint SEO seul (sans navigateur) -> artifacts/ux-review/seo.json
    py .tools/ux_check.py --ui      revue visuelle Playwright (interface de l'app + quelques pages du site)
    py .tools/ux_check.py           les deux

Code de retour non nul si le lint SEO trouve au moins une erreur. Données fictives uniquement : base SQLite
temporaire, aucune entrée envoyée à Heartopia, aucun service de production contacté.

Règles du lint, par (page, langue) : réponse 200 ; `<html lang>` ; titre ≤ 60 caractères et unique ; description
de 50 à 160 caractères et unique ; un seul `<h1>` ; canonical = URL de la page ; hreflang pour toutes les langues
+ x-default, réciproques ; og:image 1200×630 qui existe dans server/static, og:image:width/height cohérents ;
chaque `<img>` avec width, height et alt ; HTML < 120 Ko ; JSON-LD valide ; aucune clé `[site.…]` non traduite.
Plus : sitemap (une entrée par page × langue, lastmod), robots.txt, 404 traduite en noindex.
"""
from __future__ import annotations

import functools
import json
import re
import struct
import sys
import tempfile
import threading
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

OUT = ROOT / "artifacts/ux-review"
BASE = "https://dodotopia.cyber-dodo.fr"
MAX_HTML = 120 * 1024


# --------------------------------------------------------------------------------------------- lint SEO

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.html_lang = None
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.links: list[dict] = []
        self.h1 = 0
        self.imgs: list[dict] = []
        self.ld: list[str] = []
        self._in_ld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key and key not in self.meta:
                self.meta[key] = a.get("content", "")
        elif tag == "link":
            self.links.append(a)
        elif tag == "h1":
            self.h1 += 1
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_ld:
            self.ld.append("".join(self._buf))
            self._in_ld = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_ld:
            self._buf.append(data)


def png_size(path: Path):
    try:
        head = path.read_bytes()[:24]
    except OSError:
        return None
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def seed_release(settings) -> None:
    """Une version fictive publiée : la page de téléchargement et les nouveautés sont vues remplies."""
    from app import db
    conn = db.connect(settings)
    try:
        conn.execute("INSERT INTO releases (version, notes, mandatory, published_at) VALUES (?, ?, 0, ?)",
                     ("1.9.0", "Nouveaux instruments\nCorrections", "2026-09-15T10:00:00+00:00"))
        for platform, name, size in (("windows-setup", "DodoTopia-1.9.0-Setup.exe", 94_000_000),
                                     ("windows-portable", "DodoTopia-1.9.0-portable.zip", 120_000_000),
                                     ("linux-x64", "DodoTopia-1.9.0-linux-x64.tar.gz", 110_000_000)):
            conn.execute("INSERT INTO release_assets (version, platform, filename, sha256, size) VALUES (?, ?, ?, ?, ?)",
                         ("1.9.0", platform, name, "a" * 64, size))
        conn.commit()
    finally:
        conn.close()


def run_seo() -> dict:
    from fastapi.testclient import TestClient

    from app import i18n, site
    from app.config import Settings
    from app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="dodo-seo-"))
    settings = Settings(_env_file=None, DATA_DIR=str(tmp / "data"), RATE_LIMIT=0, PUBLIC_URL=BASE,
                        DATABASE_URL="")
    errors: list[dict] = []
    warnings: list[dict] = []
    pages: list[dict] = []

    def err(url, rule, detail=""):
        errors.append({"url": url, "rule": rule, "detail": detail})

    titles: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    alternates: dict[str, dict[str, str]] = {}

    with TestClient(create_app(settings), follow_redirects=False) as client:
        seed_release(settings)
        site.invalidate(client.app)
        for page_id in site.PAGE_IDS:
            for lang in i18n.LANGS:
                path = site.url_for(lang, page_id)
                url = BASE + path
                r = client.get(path)
                info = {"page": page_id, "lang": lang, "url": path, "status": r.status_code, "bytes": len(r.content)}
                pages.append(info)
                if r.status_code != 200:
                    err(path, "status", str(r.status_code))
                    continue
                html = r.text
                p = PageParser()
                p.feed(html)
                info["title"] = p.title
                info["title_len"] = len(p.title)
                desc = p.meta.get("description", "")
                info["description_len"] = len(desc)
                if p.html_lang != lang:
                    err(path, "html_lang", f"{p.html_lang!r}")
                if not p.title or len(p.title) > 60:
                    err(path, "title_length", f"{len(p.title)} : {p.title}")
                if p.title in titles:
                    err(path, "title_unique", f"identique à {titles[p.title]}")
                titles.setdefault(p.title, path)
                if not 50 <= len(desc) <= 160:
                    err(path, "description_length", f"{len(desc)} : {desc}")
                if desc in descriptions:
                    err(path, "description_unique", f"identique à {descriptions[desc]}")
                descriptions.setdefault(desc, path)
                if p.h1 != 1:
                    err(path, "h1_count", str(p.h1))
                canon = [lk.get("href") for lk in p.links if lk.get("rel") == "canonical"]
                if canon != [url]:
                    err(path, "canonical", f"{canon}")
                alts = {lk.get("hreflang"): lk.get("href") for lk in p.links
                        if lk.get("rel") == "alternate" and lk.get("hreflang")}
                alternates[url] = alts
                expected = set(i18n.LANGS) | {"x-default"}
                if set(alts) != expected:
                    err(path, "hreflang_set", f"manque {sorted(expected - set(alts))}, en trop {sorted(set(alts) - expected)}")
                if alts.get(lang) != url:
                    err(path, "hreflang_self", f"{alts.get(lang)}")
                if alts.get("x-default") != BASE + site.url_for(i18n.DEFAULT_LANG, page_id):
                    err(path, "hreflang_x_default", f"{alts.get('x-default')}")
                # og:image
                og = p.meta.get("og:image", "")
                if not og.startswith(BASE + "/static/og/"):
                    err(path, "og_image_page", og)
                else:
                    file = ROOT / "server" / "static" / og[len(BASE + "/static/"):].split("?")[0]
                    size = png_size(file)
                    if size != (1200, 630):
                        err(path, "og_image_size", f"{file.name} : {size}")
                if (p.meta.get("og:image:width"), p.meta.get("og:image:height")) != ("1200", "630"):
                    err(path, "og_image_dimensions_meta", f"{p.meta.get('og:image:width')}x{p.meta.get('og:image:height')}")
                if p.meta.get("og:locale") != i18n.LANG_INFO[lang]["og"]:
                    err(path, "og_locale", p.meta.get("og:locale", ""))
                if p.meta.get("twitter:card") != "summary_large_image":
                    err(path, "twitter_card", p.meta.get("twitter:card", ""))
                for img in p.imgs:
                    missing = [k for k in ("width", "height", "alt") if k not in img]
                    if missing:
                        err(path, "img_attributes", f"{img.get('src')} sans {missing}")
                    elif not img["alt"].strip():
                        warnings.append({"url": path, "rule": "img_alt_empty", "detail": img.get("src")})
                if len(r.content) >= MAX_HTML:
                    err(path, "html_size", f"{len(r.content)} octets")
                types = []
                for block in p.ld:
                    try:
                        data = json.loads(block)
                        types.append(data.get("@type"))
                    except ValueError as exc:
                        err(path, "json_ld", str(exc))
                info["json_ld"] = types
                if "Organization" not in types:
                    err(path, "json_ld_organization")
                if page_id != "home" and "BreadcrumbList" not in types:
                    err(path, "json_ld_breadcrumb")
                if page_id in ("home", "download") and "SoftwareApplication" not in types:
                    err(path, "json_ld_software")
                keys = sorted(set(re.findall(r"\[site\.[\w.\-]+\]", html)))
                if keys:
                    err(path, "untranslated_key", ", ".join(keys[:10]))
                if i18n.is_beta(lang) and 'class="beta"' not in html:
                    err(path, "beta_banner")
                if "__NONCE__" in html:
                    err(path, "nonce_placeholder")

        # réciprocité hreflang
        for url, alts in alternates.items():
            for code, target in alts.items():
                if code == "x-default":
                    continue
                back = alternates.get(target)
                if back is None:
                    err(url, "hreflang_target_unknown", f"{code} -> {target}")
                elif url not in back.values():
                    err(url, "hreflang_not_reciprocal", f"{code} -> {target}")

        # sitemap, robots, 404
        r = client.get("/sitemap.xml")
        if r.status_code != 200 or "sitemap-pages.xml" not in r.text or "<lastmod>" not in r.text:
            err("/sitemap.xml", "sitemap_index")
        r = client.get("/sitemap-pages.xml")
        locs = re.findall(r"<loc>([^<]+)</loc>", r.text)
        expected_locs = {BASE + site.url_for(lang, pid) for pid in site.PAGE_IDS for lang in i18n.LANGS}
        if set(locs) != expected_locs or len(locs) != len(expected_locs):
            err("/sitemap-pages.xml", "sitemap_urls", f"{len(locs)} entrées pour {len(expected_locs)} attendues")
        if r.text.count("<lastmod>") != len(expected_locs):
            err("/sitemap-pages.xml", "sitemap_lastmod")
        r = client.get("/robots.txt")
        if f"Sitemap: {BASE}/sitemap.xml" not in r.text:
            err("/robots.txt", "robots_sitemap")
        for lang in i18n.LANGS:
            r = client.get(f"/{lang}/page-qui-n-existe-pas")
            if r.status_code != 404 or "noindex" not in r.text or f'<html lang="{lang}">' not in r.text:
                err(f"/{lang}/page-qui-n-existe-pas", "not_found_page", str(r.status_code))

    report = {"pages": pages, "errors": errors, "warnings": warnings,
              "summary": {"pages": len(pages), "errors": len(errors), "warnings": len(warnings),
                          "completeness": {lang: round(i18n.completeness(lang), 3) for lang in i18n.LANGS}}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "seo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for e in errors[:40]:
        print(f"ERREUR {e['rule']:<26} {e['url']}  {e['detail']}")
    print(f"lint SEO : {len(pages)} pages, {len(errors)} erreur(s), {len(warnings)} avertissement(s) "
          f"-> {OUT / 'seo.json'}")
    return report


# --------------------------------------------------------------------------------------------- revue UI

def run_ui() -> None:
    sys.path.insert(0, str(ROOT / ".tools/python"))
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright

    from app.config import Settings
    from app.main import create_app

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="dodo-ui-"))
    settings = Settings(_env_file=None, DATA_DIR=str(tmp / "data"), RATE_LIMIT=0, PUBLIC_URL="http://127.0.0.1")
    with TestClient(create_app(settings)) as client:
        # CSP à nonce : la revue locale sert le HTML sans en-têtes, le script inline reste exécutable
        pages = {"/site-home": client.get("/fr/").text, "/site-instruments": client.get("/fr/instruments").text}

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path in pages:
                data = pages[self.path].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.startswith("/static/"):
                self.path = "/server" + self.path.split("?")[0]
            super().do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r"C:\Users\pizzp\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe", headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for width, height in [(1280, 812), (1024, 640), (768, 700), (390, 844), (320, 680)]:
            page.set_viewport_size({"width": width, "height": height})
            for name, route in [("music", "/ui/index.html?mock"), ("empty", "/ui/index.html?mock&empty"),
                                ("draw", "/ui/index.html?mock&image&tab=image"), ("cook", "/ui/index.html?mock&cook&tab=cook"),
                                ("settings", "/ui/index.html?mock&settings"), ("instruments-app", "/ui/index.html?mock&sel"),
                                ("discover", "/ui/index.html?mock&online&view=discover"),
                                ("together", "/ui/index.html?mock&view=together"),
                                ("home", "/site-home"), ("instruments", "/site-instruments")]:
                page.goto(base + route)
                page.wait_for_timeout(220)
                page.evaluate("document.fonts.ready")
                overflow = page.evaluate('''() => [...document.querySelectorAll('body *')].filter(e => {
                    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                    return r.width && r.height && s.visibility !== 'hidden' && (r.right > innerWidth + 2 || r.left < -2)
                        && !e.closest('.sr-only,.skip,.switch,.toast-stack,.header-nav');
                }).slice(0,12).map(e=>e.tagName+'#'+e.id+'.'+e.className)''')
                results.append({"screen": name, "width": width, "overflow": overflow, "errors": list(errors)})
                errors.clear()
                if width in (1280, 390):
                    page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)
        page.goto(base + "/ui/index.html?mock")
        page.wait_for_timeout(200)
        page.evaluate("window.dialogResult = null; dialog({title:'Supprimer ?',html:'Vérification',danger:true}).then(v => window.dialogResult=v)")
        page.wait_for_timeout(100)
        assert page.locator("#dlgCancel").evaluate("(e)=>e===document.activeElement")
        page.keyboard.press("Enter")
        assert page.evaluate("window.dialogResult") is False
        page.evaluate("menu($('btnImport'), [{label:'Premier',fn:()=>{}},{label:'Second',fn:()=>{}}])")
        page.wait_for_timeout(80)
        page.keyboard.press("ArrowDown")
        assert page.locator(".menu button").nth(1).evaluate("(e)=>e===document.activeElement")
        page.keyboard.press("Escape")
        assert page.locator("#btnImport").evaluate("(e)=>e===document.activeElement")
        browser.close()
    server.shutdown()
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([r for r in results if r["overflow"] or r["errors"]], ensure_ascii=False, indent=2))
    print(f"{len(results)} screens checked; dialog and menu keyboard checks passed")


def main(argv: list[str]) -> int:
    seo = "--seo" in argv or "--ui" not in argv
    ui = "--ui" in argv or "--seo" not in argv
    code = 0
    if seo:
        report = run_seo()
        code = 1 if report["errors"] else 0
    if ui:
        run_ui()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
