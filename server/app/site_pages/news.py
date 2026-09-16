"""Nouveautés : journal des versions publiées (notes de `releases.notes`, vingt dernières)."""
from __future__ import annotations

from ..i18n import t
from ..site import esc, human_date, url_for


def render(settings, lang: str, ctx) -> str:
    items = []
    for i, rel in enumerate(ctx.releases):
        lines = [line.strip(" -•\t") for line in (rel.get("notes") or "").splitlines() if line.strip()]
        body = ("<ul>" + "".join(f"<li>{esc(line)}</li>" for line in lines) + "</ul>") if lines \
            else f'<p class="dl-note">{esc(t(lang, "site.news.no_notes"))}</p>'
        date = human_date(rel.get("published_at"), lang)
        meta = f'<time datetime="{esc((rel.get("published_at") or "")[:10])}">{esc(date)}</time>' if date else ""
        badge = f' <span class="pill pill--candidate">{esc(t(lang, "site.news.mandatory"))}</span>' if rel.get("mandatory") else ""
        latest = f' <span class="pill pill--documented">{esc(t(lang, "site.news.latest"))}</span>' if i == 0 else ""
        items.append(f"""<article class="newsitem" id="v{esc(rel["version"]).replace(".", "-")}">
      <h2>{esc(t(lang, "site.news.version", version=rel["version"]))}{latest}{badge}</h2>
      <p class="newsitem__date">{meta}</p>
      {body}
    </article>""")
    if items:
        listing = "".join(items)
        cta = f'<p><a class="btn btn--cta" href="{url_for(lang, "download")}">{esc(t(lang, "site.common.download_cta"))}</a></p>'
    else:
        listing = f'<div class="soon"><h2>{esc(t(lang, "site.news.empty_title"))}</h2><p>{t(lang, "site.news.empty_text")}</p></div>'
        cta = ""
    return f"""<section class="section"><div class="wrap">
  <h1>{t(lang, "site.news.h1")}</h1>
  <p class="lead">{t(lang, "site.news.lead")}</p>
  {cta}
  <div class="newslist">{listing}</div>
</div></section>
"""
