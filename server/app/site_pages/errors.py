"""Page 404 (traduite, `noindex`), rendue par `site.render_not_found`."""
from __future__ import annotations

from ..i18n import t
from ..site import esc, url_for


def render(settings, lang: str, ctx) -> str:
    links = "".join(f'<li><a href="{url_for(lang, pid)}">{esc(t(lang, f"site.nav.{pid}"))}</a></li>'
                    for pid in ("home", "download", "help", "instruments"))
    return f"""<section class="section"><div class="wrap">
  <div class="errorbox">
    <p class="eyebrow">404</p>
    <h1>{t(lang, "site.errors.404.h1")}</h1>
    <p class="lead">{t(lang, "site.errors.404.text")}</p>
    <ul class="footer-nav">{links}</ul>
  </div>
</div></section>
"""
