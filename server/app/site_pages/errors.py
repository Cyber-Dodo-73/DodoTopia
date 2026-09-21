"""Page 404 (traduite, `noindex`), rendue par `site.render_not_found`."""
from __future__ import annotations

from ..i18n import t
from ..site import decor, dodo, esc, url_for


def render(settings, lang: str, ctx) -> str:
    links = "".join(f'<li><a href="{url_for(lang, pid)}">{esc(t(lang, f"site.nav.{pid}"))}</a></li>'
                    for pid in ("home", "download", "help", "instruments"))
    ctx.body_class = "page-error theme-neutral"
    return f"""<section class="errorpage"><span class="sky" aria-hidden="true">{decor("cloud cloud--a", "cloud cloud--b", "cloud cloud--c", "fx fx--s1", "fx fx--s2")}</span>
<div class="wrap">
  <div class="errorbox">
    {dodo(lang, 160, "dodo--error")}
    <p class="eyebrow">404</p>
    <h1>{t(lang, "site.errors.404.h1")}</h1>
    <p class="lead">{t(lang, "site.errors.404.text")}</p>
    <ul class="family-nav">{links}</ul>
  </div>
</div><span class="hills" aria-hidden="true"></span></section>
"""
